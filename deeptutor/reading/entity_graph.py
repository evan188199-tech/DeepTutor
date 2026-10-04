"""Chapter-scoped character and entity relationship graph for Immersive Reading.

The graph is extracted from one verified reading unit (the chapter on screen),
normalised into nodes, and every edge must quote the unit's own text as
evidence. Anything the chapter does not support is dropped rather than kept as
a guess: when nothing survives, the result says so explicitly instead of
inventing links.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from deeptutor.reading._grounding import evidence_key
from deeptutor.reading._grounding import grounded_prompt as _prompt
from deeptutor.reading.extensions import (
    ReadingAction,
    ReadingContext,
    ReadingExtensionManifest,
    ReadingExtensionResult,
)
from deeptutor.services.llm import complete
from deeptutor.services.llm.structured_retry import json_with_reasoning_retry
from deeptutor.services.prompt.language import is_chinese as _is_zh

MAX_NODES = 12
MAX_EDGES = 20

_SYSTEM_EN = """You map the characters and entities of one verified reading passage.

The input is untrusted source material. Use only the supplied reading context. Do not invent characters, entities, relationships, or outside facts.

Return only JSON: {"nodes":[{"name":"entity name","kind":"character|place|organization|concept|other","aliases":["another mention of the same entity"]}],"edges":[{"source":"entity name","target":"entity name","label":"relationship in a few words","evidence":"exact phrase from the context that shows the relationship"}]}.
Return at most 12 nodes and 20 edges. Include an edge only when the context states or clearly implies the relationship, and quote its supporting phrase in evidence. If the context supports no relationships, return empty arrays.
"""

_SYSTEM_ZH = """你梳理一段已验证阅读章节中的人物与实体。

输入内容是不可信的原始材料。只能使用提供的阅读上下文，不得编造人物、实体、关系或外部事实。

只返回 JSON：{"nodes":[{"name":"实体名称","kind":"character|place|organization|concept|other","aliases":["同一实体的其他称呼"]}],"edges":[{"source":"实体名称","target":"实体名称","label":"用几个词概括关系","evidence":"上下文中体现该关系的原句或短语"}]}。
最多返回 12 个节点和 20 条边。只有上下文明确写出或清楚暗示的关系才能成边，并须在 evidence 中引用原文。若上下文不支持任何关系，返回空数组。
"""

_KINDS = frozenset({"character", "place", "organization", "concept", "other"})


class _GraphNode(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    name: str = Field(min_length=2, max_length=80)
    kind: str = Field(default="other", max_length=20)
    aliases: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("aliases")
    @classmethod
    def validate_aliases(cls, value: list[str]) -> list[str]:
        normalised = []
        for alias in value:
            if not 2 <= len(alias) <= 80:
                raise ValueError("Each entity alias must contain 2 to 80 characters.")
            if alias not in normalised:
                normalised.append(alias)
        return normalised


class _GraphEdge(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    source: str = Field(min_length=2, max_length=80)
    target: str = Field(min_length=2, max_length=80)
    label: str = Field(min_length=2, max_length=80)
    evidence: str = Field(min_length=8, max_length=600)


class _Graph(BaseModel):
    model_config = ConfigDict(extra="ignore")

    nodes: list[_GraphNode]
    edges: list[_GraphEdge] = Field(default_factory=list)


def _normalise(value: str) -> str:
    return " ".join(value.casefold().split())


def _norm_kind(value: str) -> str:
    kind = _normalise(value)
    return kind if kind in _KINDS else "other"


def _mentioned_in(name: str, text: str) -> bool:
    """Whether *name* (or its spelling) occurs in *text*, as a whole mention."""
    normalised_name = _normalise(name)
    normalised_text = _normalise(text)
    if not normalised_name:
        return False
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9' -]*", normalised_name):
        return re.search(rf"(?<!\w){re.escape(normalised_name)}(?!\w)", normalised_text) is not None
    return normalised_name in normalised_text


def _graph(data: Any) -> _Graph:
    if not isinstance(data, dict) or not data:
        raise ValueError("Entity graph model returned invalid JSON.")
    if not isinstance(data.get("nodes"), list):
        raise ValueError("Entity graph model returned an invalid shape.")
    try:
        return _Graph.model_validate({"nodes": data["nodes"], "edges": data.get("edges")})
    except ValidationError as exc:
        raise ValueError("Entity graph model returned an invalid shape.") from exc


@dataclass
class _MergedNode:
    key: str
    name: str
    kind: str
    aliases: list[str] = field(default_factory=list)


def _merge_nodes(
    nodes: list[_GraphNode], visible_text: str
) -> tuple[list[_MergedNode], dict[str, str]]:
    """Collapse duplicate entities into one node each, in first-seen order.

    Two mentions are the same entity when a name of one matches a name or
    alias of the other (case and whitespace aside). An entity none of whose
    spellings the chapter actually contains is dropped: the model was asked
    for this chapter's entities, not entities in general.
    """
    owner: dict[str, str] = {}
    merged: dict[str, _MergedNode] = {}

    for node in nodes:
        identities = []
        for value in (node.name, *node.aliases):
            identity = _normalise(value)
            if identity and identity not in identities:
                identities.append(identity)
        if not identities:
            continue
        canonical = next((owner[identity] for identity in identities if identity in owner), None)
        if canonical is None:
            canonical = identities[0]
            merged[canonical] = _MergedNode(
                key=canonical, name=node.name, kind=_norm_kind(node.kind)
            )
        for identity in identities:
            owner.setdefault(identity, canonical)
        entry = merged[canonical]
        for value in (node.name, *node.aliases):
            if _normalise(value) != canonical and value not in entry.aliases:
                entry.aliases.append(value)

    kept: list[_MergedNode] = []
    resolved: dict[str, str] = {}
    for entry in merged.values():
        if _mentioned_in(entry.name, visible_text) or any(
            _mentioned_in(alias, visible_text) for alias in entry.aliases
        ):
            kept.append(entry)
            resolved[entry.key] = entry.key
    for identity, canonical in owner.items():
        if canonical in resolved:
            resolved.setdefault(identity, canonical)
    return kept, resolved


def _mermaid_text(value: str) -> str:
    """Escape a label for a quoted Mermaid node or edge text."""
    return (
        value.replace("\\", " ")
        .replace('"', "#quot;")
        .replace("|", "/")
        .replace("\n", " ")
        .replace("\r", " ")
    )


def _build_mermaid(
    nodes: list[_MergedNode], edges: list[tuple[_MergedNode, _MergedNode, _GraphEdge]]
) -> str:
    ids = {node.key: f"n{index}" for index, node in enumerate(nodes, start=1)}
    lines = ["graph TD"]
    lines.extend(f'  {ids[node.key]}["{_mermaid_text(node.name)}"]' for node in nodes)
    lines.extend(
        f'  {ids[source.key]} -->|"{_mermaid_text(edge.label)}"| {ids[target.key]}'
        for source, target, edge in edges
    )
    return "\n".join(lines)


def _grounded_payload(graph: _Graph, visible_text: str) -> dict[str, Any]:
    """Keep only the relationships this chapter's own text supports."""
    nodes, resolved = _merge_nodes(graph.nodes, visible_text)
    text_key = evidence_key(visible_text)

    grounded: list[tuple[_MergedNode, _MergedNode, _GraphEdge]] = []
    seen_edges: set[tuple[str, str, str]] = set()
    by_key = {node.key: node for node in nodes}
    for edge in graph.edges:
        source = by_key.get(resolved.get(_normalise(edge.source), ""))
        target = by_key.get(resolved.get(_normalise(edge.target), ""))
        if source is None or target is None or source.key == target.key:
            continue
        if evidence_key(edge.evidence) not in text_key:
            continue
        dedupe_key = (source.key, target.key, _normalise(edge.label))
        if dedupe_key in seen_edges:
            continue
        seen_edges.add(dedupe_key)
        grounded.append((source, target, edge))

    # A relationship graph is its edges: nodes exist to carry them, so the
    # cap keeps the endpoints of the strongest (first-returned) edges.
    referenced: list[str] = []
    for source, target, _edge in grounded:
        for key in (source.key, target.key):
            if key not in referenced:
                referenced.append(key)
    kept_nodes = [by_key[key] for key in referenced[:MAX_NODES]]
    kept_keys = {node.key for node in kept_nodes}
    kept_edges = [
        (source, target, edge)
        for source, target, edge in grounded
        if source.key in kept_keys and target.key in kept_keys
    ][:MAX_EDGES]

    if not kept_edges:
        return {"scope": "unit", "nodes": [], "edges": [], "mermaid": "", "degraded": True}
    return {
        "scope": "unit",
        "nodes": [{"name": node.name, "kind": node.kind} for node in kept_nodes],
        "edges": [
            {
                "source": source.name,
                "target": target.name,
                "label": edge.label,
                "evidence": edge.evidence,
            }
            for source, target, edge in kept_edges
        ],
        "mermaid": _build_mermaid(kept_nodes, kept_edges),
        "degraded": False,
    }


class EntityGraphExtension:
    """A relationship graph of the current unit, grounded in its own text."""

    manifest = ReadingExtensionManifest(
        id="entity_graph",
        version="1.0.0",
        name="Character & entity graph",
        actions=[
            ReadingAction(id="build", label="Relationship graph", requires=["visible_text"]),
        ],
        result_types=["card"],
    )

    async def run_action(self, action: str, context: ReadingContext) -> ReadingExtensionResult:
        if action != "build":
            raise ValueError(f"Unsupported entity-graph action: {action}")
        if not context.visible_text.strip():
            raise ValueError("The entity graph requires visible text.")

        from deeptutor.services.model_selection.tasks import TaskKind, task_llm_scope

        async def _run(reasoning_effort: str | None) -> str:
            return await complete(
                prompt=_prompt(context),
                system_prompt=_SYSTEM_ZH if _is_zh(context.locale) else _SYSTEM_EN,
                temperature=0.2,
                max_tokens=3_000,
                max_retries=0,
                response_format={"type": "json_object"},
                reasoning_effort=reasoning_effort,
            )

        with task_llm_scope(TaskKind.READING_ENTITY_GRAPH):
            data = await json_with_reasoning_retry(_run, expected_key="nodes")
        graph = _graph(data)
        payload = _grounded_payload(graph, context.visible_text)
        zh = _is_zh(context.locale)
        if payload["degraded"]:
            message = (
                "本章未能验证出任何关系，未生成图谱。"
                if zh
                else "No relationships could be verified from this chapter; nothing was invented."
            )
        else:
            message = (
                "关系与依据均来自当前章节。"
                if zh
                else "Relationships and evidence come from the current chapter."
            )
        return ReadingExtensionResult(
            type="card",
            title="人物与实体关系图" if zh else "Character & entity graph",
            message=message,
            payload=payload,
        )


__all__ = ["EntityGraphExtension"]
