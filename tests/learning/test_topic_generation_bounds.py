"""Bounded route generation stays inside its budgets, or fails loudly.

Covers the bounded mixed-source path of ``topic_generation`` that the wider
suite did not reach: which sources survive the payload quota and in what
order, what happens when the model's output cannot be parsed or arrives
truncated, and the boundary values of the region/waypoint caps and the
empty-source (goal-only) shape.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from deeptutor.learning.models import TopicSource, TopicSourceKind
from deeptutor.learning.topic_generation import (
    _MAX_OBJECTIVES_PER_MODULE,
    _MAX_SOURCE_EXCERPT,
    _MAX_SOURCE_TOTAL,
    _MAX_SOURCES,
    DEFAULT_MODULE_LIMIT,
    MAX_MODULE_LIMIT,
    TopicGenerationError,
    _module_objective,
    _retrieved_context,
    _source_payload,
    generate_topic_draft,
    materialize_modules,
    module_limit_for,
    source_documents,
)


def _source(
    source_id: str,
    *,
    position: int = 0,
    excerpt: str = "",
    label: str = "",
    documents: list[str] | None = None,
    documents_omitted: int = 0,
    kind: TopicSourceKind = TopicSourceKind.GOAL,
) -> TopicSource:
    metadata: dict[str, Any] = {}
    if documents is not None:
        metadata["documents"] = documents
    if documents_omitted:
        metadata["documents_omitted"] = documents_omitted
    return TopicSource(
        id=source_id,
        kind=kind,
        label=label or source_id,
        excerpt=excerpt,
        position=position,
        metadata=metadata,
    )


def _region(name: str, waypoints: int = 1) -> dict:
    return {
        "name": name,
        "knowledge_points": [
            {"name": f"{name} objective {index}", "type": "concept"} for index in range(waypoints)
        ],
    }


def _draft_response(regions: list[dict], description: str = "A route") -> str:
    return json.dumps({"description": description, "modules": regions})


# ── source payload: ordering and quotas ──────────────────────────────────────


def test_source_payload_follows_position_not_input_order() -> None:
    payload = _source_payload(
        [
            _source("late", position=2),
            _source("first", position=0),
            _source("middle", position=1),
        ]
    )

    assert [entry["label"] for entry in payload] == ["first", "middle", "late"]


def test_source_payload_keeps_at_most_the_source_quota() -> None:
    sources = [_source(f"s{index}", position=index) for index in range(_MAX_SOURCES + 2)]

    payload = _source_payload(sources)

    assert len(payload) == _MAX_SOURCES
    assert [entry["label"] for entry in payload[:2]] == ["s0", "s1"]


def test_source_payload_truncates_each_excerpt_to_the_per_source_cap() -> None:
    payload = _source_payload([_source("big", excerpt="a" * (_MAX_SOURCE_EXCERPT + 6_000))])

    assert len(payload[0]["excerpt"]) == _MAX_SOURCE_EXCERPT


def test_source_payload_spends_the_total_budget_in_position_order() -> None:
    # Six 3 900-character excerpts leave 600 characters of the 24 000 budget;
    # the seventh source is cut to that remainder, and the eighth is dropped
    # outright — earlier positions are always the ones that survive.
    full = _MAX_SOURCE_EXCERPT - 100
    sources = [_source(f"s{index}", position=index, excerpt="a" * full) for index in range(6)] + [
        _source("s6", position=6, excerpt="b" * _MAX_SOURCE_EXCERPT),
        _source("s7", position=7, excerpt="c" * _MAX_SOURCE_EXCERPT),
    ]

    payload = _source_payload(sources)

    assert len(payload) == 7
    assert [len(entry["excerpt"]) for entry in payload[:6]] == [full] * 6
    assert len(payload[6]["excerpt"]) == _MAX_SOURCE_TOTAL - 6 * full
    assert payload[6]["label"] == "s6"


def test_source_payload_carries_documents_and_omission_counts() -> None:
    payload = _source_payload(
        [
            _source("kb", documents=["a.pdf", "b.pdf"], documents_omitted=3),
            _source("bare", documents=[]),
        ]
    )

    assert payload[0]["documents"] == ["a.pdf", "b.pdf"]
    assert payload[0]["documents_omitted"] == 3
    assert "documents" not in payload[1]


def test_source_payload_truncates_long_labels() -> None:
    payload = _source_payload([_source("s", label="L" * 500)])

    assert len(payload[0]["label"]) == 200


def test_source_documents_ignores_non_list_metadata_and_blank_names() -> None:
    assert source_documents(_source("no-meta")) == []
    assert source_documents(_source("bad-meta", documents="not-a-list")) == []
    assert source_documents(_source("messy", documents=[None, "", "   ", "a.pdf", 42])) == [
        "a.pdf",
        "42",
    ]


# ── model output that cannot be used ────────────────────────────────────────


@pytest.mark.asyncio
async def test_prose_output_aborts_with_the_route_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "deeptutor.learning.topic_generation.complete",
        AsyncMock(return_value="I cannot design a route for that."),
    )

    with pytest.raises(TopicGenerationError, match="invalid route JSON"):
        await generate_topic_draft(name="T", goal="G", sources=[], language="en")


@pytest.mark.asyncio
async def test_json_array_output_is_rejected_as_a_route_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "deeptutor.learning.topic_generation.complete",
        AsyncMock(return_value=json.dumps([_region("Only region")])),
    )

    with pytest.raises(TopicGenerationError, match="invalid route JSON"):
        await generate_topic_draft(name="T", goal="G", sources=[], language="en")


@pytest.mark.asyncio
async def test_route_json_without_a_module_list_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "deeptutor.learning.topic_generation.complete",
        AsyncMock(return_value=json.dumps({"description": "No regions here"})),
    )

    with pytest.raises(TopicGenerationError, match="no module list"):
        await generate_topic_draft(name="T", goal="G", sources=[], language="en")


@pytest.mark.asyncio
async def test_truncated_module_list_degrades_to_a_loud_empty_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A response cut off mid-list repairs to an empty module list; generation
    # fails with the empty-route error rather than returning a hollow draft.
    monkeypatch.setattr(
        "deeptutor.learning.topic_generation.complete",
        AsyncMock(return_value='{"description": "Cut off", "modules": ['),
    )

    with pytest.raises(TopicGenerationError, match="no usable objectives"):
        await generate_topic_draft(name="T", goal="G", sources=[], language="en")


@pytest.mark.asyncio
async def test_empty_source_list_still_yields_a_goal_only_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    complete = AsyncMock(return_value=_draft_response([_region("Goal region")], "Goal only"))
    monkeypatch.setattr("deeptutor.learning.topic_generation.complete", complete)

    result = await generate_topic_draft(name="T", goal="G", sources=[], language="en")

    complete.assert_awaited_once()
    assert len(result["modules"]) == 1
    assert result["sources"] == []
    assert result["module_limit"] == DEFAULT_MODULE_LIMIT
    assert result["coverage"] == {
        "documents": 0,
        "covered": 0,
        "missing": [],
        "reported": False,
    }


# ── cap boundaries ──────────────────────────────────────────────────────────


def test_region_cap_clamps_to_the_maximum_in_a_forgiving_draft() -> None:
    raw = [_region(f"Region {index}") for index in range(MAX_MODULE_LIMIT + 5)]
    discarded: list[dict] = []

    modules = materialize_modules(
        "draft", raw, discarded_modules=discarded, module_limit=MAX_MODULE_LIMIT + 100
    )

    assert len(modules) == MAX_MODULE_LIMIT
    assert [item["reason"] for item in discarded] == ["module limit exceeded"] * 5


@pytest.mark.parametrize(
    ("module_limit", "expected_regions"),
    [(-3, 1), (0, DEFAULT_MODULE_LIMIT)],
)
def test_degenerate_region_limits_fall_back_to_sane_bounds(
    module_limit: int, expected_regions: int
) -> None:
    raw = [_region(f"Region {index}") for index in range(MAX_MODULE_LIMIT)]

    modules = materialize_modules("draft", raw, module_limit=module_limit)

    assert len(modules) == expected_regions


def test_waypoints_past_the_per_region_cap_are_trimmed_without_error() -> None:
    raw = [_region("Crowded", waypoints=_MAX_OBJECTIVES_PER_MODULE + 2)]

    modules = materialize_modules("draft", raw)

    assert len(modules[0].knowledge_points) == _MAX_OBJECTIVES_PER_MODULE


def test_module_limit_for_sits_between_the_default_and_the_ceiling() -> None:
    five = _source(
        "kb", kind=TopicSourceKind.KNOWLEDGE_BASE, documents=[f"d{i}.pdf" for i in range(5)]
    )
    twenty = _source(
        "kb",
        kind=TopicSourceKind.KNOWLEDGE_BASE,
        documents=[f"d{i:02d}.pdf" for i in range(MAX_MODULE_LIMIT * 2)],
    )

    assert module_limit_for([five]) == DEFAULT_MODULE_LIMIT
    assert module_limit_for([twenty]) == MAX_MODULE_LIMIT


# ── retrieval context assembly ──────────────────────────────────────────────


def test_retrieved_context_keeps_at_most_six_passages() -> None:
    result = {"sources": [{"title": f"t{index}", "content": "c" * 20} for index in range(8)]}

    context = _retrieved_context(result)

    assert context.count("\n\n") == 5
    assert "t7" not in context


def test_retrieved_context_reads_snippet_when_content_is_absent() -> None:
    context = _retrieved_context({"sources": [{"title": "s", "snippet": "x" * 600}]})

    assert context.startswith("s\n")
    assert "x" * 600 in context


def test_thin_passages_are_backed_by_the_answer_block() -> None:
    result = {
        "sources": [{"title": "t", "content": "short"}],
        "answer": "a" * 600,
    }

    context = _retrieved_context(result)

    assert "short" in context
    assert "a" * 600 in context


def test_substantial_passages_leave_the_answer_block_out() -> None:
    result = {
        "sources": [{"title": "t", "content": "c" * 600}],
        "answer": "a" * 600,
    }

    context = _retrieved_context(result)

    assert "a" * 600 not in context


def test_retrieved_context_is_capped_at_the_excerpt_budget() -> None:
    context = _retrieved_context(
        {"sources": [{"title": "t", "content": "c" * (_MAX_SOURCE_EXCERPT + 1_000)}]}
    )

    assert len(context) == _MAX_SOURCE_EXCERPT


# ── module objective fallback ───────────────────────────────────────────────


def test_module_objective_falls_through_the_known_keys_and_truncates() -> None:
    assert _module_objective({"objective": "O"}) == "O"
    assert _module_objective({"goal": "G"}) == "G"
    assert _module_objective({"purpose": "  P  "}) == "P"
    assert _module_objective({"summary": "S", "description": "D"}) == "S"
    assert _module_objective({"description": "D"}) == "D"
    assert _module_objective({"objective": "o" * 400}) == "o" * 300
    assert _module_objective({"objective": "   "}) == ""
    assert _module_objective({}) == ""
