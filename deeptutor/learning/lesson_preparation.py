"""Reusable objective preparation and task-classified evidence selection.

Reliable access to a figure is not the same as reliably deciding *when* that
figure is needed (#1902). The Mastery Path tutor already has exact-source tools
— ``read_source`` over the topic-materials manifest, ``rag`` over attached
knowledge bases, and the source-bound visual pipeline in
:mod:`deeptutor.learning.visual_practice` whose ``prepare_visual`` /
``evaluate_visual`` never grade pixels the model has not seen. What those tools
lack is a small, plain decision layer in front of them: what an objective
actually needs before it is taught, and whether *this* task justifies paying
for evidence again.

This module is that layer, and it is deliberately pure: no I/O, no LLM calls,
no retrieval. The tutor loop supplies what it already knows (the objective's
concepts, the passages and figures a turn can see, what was inspected earlier)
and gets back a plan it can follow with the tools it already has. Three rules
encode the requested balance:

- Ordinary explanation uses established knowledge and previously checked
  material — no retrieval call is planned for it.
- Claims whose correctness depends on a particular figure, table, label or
  unit plan a fetch-and-inspect of the original. A caption or an image URL is
  never treated as having seen the image, so a miss is a miss even when the
  candidate is already described somewhere.
- Verified evidence is reusable across explanation, follow-up and practice
  *for the same objective and the same source*, and reuse keeps its identity:
  a changed source hash or objective invalidates the entry, and cached
  findings never claim the current model request can inspect pixels it no
  longer has. A pixel-dependent task re-attaches the original instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

#: What the tutor is about to do with the objective this turn.
TaskKind = Literal["explain", "source_claim", "practice", "review"]

#: Whether a visual's correctness bearing on the task comes from its source.
ClaimDependency = Literal["none", "source"]

#: How much the visual matters to the task at hand.
Importance = Literal["required", "useful", "decorative"]

#: The three-way classification every candidate resolves to.
VisualNeed = Literal["necessary", "reusable", "decorative"]

#: Tasks whose answers are only trustworthy against live source pixels.
_PIXEL_TASKS: frozenset[str] = frozenset({"practice", "review"})


@dataclass(frozen=True)
class SourceRef:
    """Identity of one piece of visual evidence.

    Mirrors the selectors ``retrieve_visual`` accepts, so a plan's refs can be
    resolved without translation. ``source_hash`` is the source document id:
    a reindexed or replaced document changes it, which is exactly what must
    invalidate cached findings for that figure.
    """

    kb_name: str = ""
    asset_id: str = ""
    source_path: str = ""
    page: int | None = None
    source_hash: str = ""

    @property
    def key(self) -> str:
        """Return a stable identity string for cache keys and reports."""
        return "|".join(
            (
                self.kb_name,
                self.asset_id,
                self.source_path,
                "" if self.page is None else str(self.page),
                self.source_hash,
            )
        )


@dataclass(frozen=True)
class VisualCandidate:
    """One visual the objective *could* use, with why it would.

    ``claim_dependency`` says whether the correctness of what this turn will
    say depends on this particular source ("which label is the artery"), as
    opposed to general knowledge that merely happens to have a picture
    nearby. ``importance`` is the tutor's judgement of how much the task
    needs it: necessary to understand or assess, useful for clarification,
    or merely decorative.
    """

    ref: SourceRef
    claim_dependency: ClaimDependency = "none"
    importance: Importance = "decorative"


@dataclass(frozen=True)
class ConceptSpec:
    """One essential concept an objective is made of.

    ``prerequisites`` names concepts the learner needs first; the preparation
    reports the ones the selected material does not cover instead of letting
    general knowledge silently stand in for them.
    """

    name: str
    prerequisites: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvidenceText:
    """One retrieved passage available to the objective.

    ``covers`` names the concepts the passage actually speaks to.
    ``partial`` marks a passage that is only a partial view of its source or
    chapter — one successful retrieval must not imply complete coverage
    (#1902), so a partial passage keeps the whole preparation honestly
    incomplete however many concepts it happens to name.
    """

    source_hash: str
    text: str = ""
    covers: tuple[str, ...] = ()
    partial: bool = False


@dataclass(frozen=True)
class ObjectivePreparation:
    """A compact, reusable preparation record for one objective.

    Tracks what the objective consists of, which of it the selected material
    supports, what is still unresolved, and which prerequisites are missing —
    the scope/coverage half of #1902's requested orchestration, in the shape
    its "suggested direction" describes: essential concepts, selected
    evidence, unresolved gaps. No new framework, no second AI pass; the tutor
    reads it and teaches.
    """

    objective_id: str
    concepts: tuple[str, ...]
    supported: tuple[str, ...]
    unresolved: tuple[str, ...]
    missing_prerequisites: tuple[str, ...]
    coverage: Literal["supported", "partial"]
    source_hashes: tuple[str, ...]

    @property
    def adequate(self) -> bool:
        """Whether this record can be reused instead of recomputed."""
        return self.coverage == "supported" and not self.unresolved


def prepare_objective(
    *,
    objective_id: str,
    concepts: tuple[ConceptSpec, ...],
    evidence: tuple[EvidenceText, ...],
    prior: ObjectivePreparation | None = None,
) -> ObjectivePreparation:
    """Establish an objective's scope and coverage from available evidence.

    Reuses an adequate prior record when the objective and the source set are
    unchanged — preparation repeats on every turn otherwise, which is the
    redundant work #1902 asks to avoid. Any change (different objective,
    different sources, unresolved gaps in the prior) recomputes from the
    evidence given.

    Args:
        objective_id: Stable id of the objective (e.g. a knowledge point id).
        concepts: The objective's essential concepts, with prerequisites.
        evidence: Passages retrievable for this objective right now.
        prior: A previously established record for the same objective.

    Returns:
        The preparation to teach from this turn: ``prior`` itself when it is
        still valid, otherwise a freshly computed record.
    """
    source_hashes = tuple(sorted({item.source_hash for item in evidence}))
    if (
        prior is not None
        and prior.adequate
        and prior.objective_id == objective_id
        and prior.source_hashes == source_hashes
    ):
        return prior
    covered: set[str] = set()
    partial_view = False
    for item in evidence:
        covered.update(item.covers)
        partial_view = partial_view or item.partial
    names = tuple(dict.fromkeys(concept.name for concept in concepts))
    supported = tuple(name for name in names if name in covered)
    unresolved = tuple(name for name in names if name not in covered)
    wanted: list[str] = []
    for concept in concepts:
        for prerequisite in concept.prerequisites:
            if prerequisite not in covered and prerequisite not in names:
                wanted.append(prerequisite)
    return ObjectivePreparation(
        objective_id=objective_id,
        concepts=names,
        supported=supported,
        unresolved=unresolved,
        missing_prerequisites=tuple(dict.fromkeys(wanted)),
        coverage="partial" if partial_view or unresolved else "supported",
        source_hashes=source_hashes,
    )


@dataclass(frozen=True)
class CachedFinding:
    """What an earlier turn verified about one visual.

    ``pixels_in_context`` is always False by construction: findings are text
    recorded at inspection time, and the model request that inspects them
    later has no pixels unless the plan re-attaches the original. Cached text
    must not imply otherwise (#1902).
    """

    objective_id: str
    ref: SourceRef
    findings: str
    pixels_in_context: bool = False


class EvidenceCache:
    """Turn-spanning record of evidence already inspected for an objective.

    Keyed by objective id and figure identity, including the source document
    hash: a changed source is a different figure even at the same page, so it
    misses rather than silently redirecting old findings to new material.
    """

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], CachedFinding] = {}

    def record(self, objective_id: str, ref: SourceRef, *, findings: str = "") -> CachedFinding:
        """Store what an inspection of ``ref`` established for ``objective_id``."""
        entry = CachedFinding(objective_id=objective_id, ref=ref, findings=str(findings or ""))
        self._entries[(objective_id, ref.key)] = entry
        return entry

    def lookup(self, objective_id: str, ref: SourceRef) -> CachedFinding | None:
        """Return the cached finding for this objective and figure, if still valid."""
        entry = self._entries.get((objective_id, ref.key))
        if entry is None or entry.ref.source_hash != ref.source_hash:
            return None
        return entry


@dataclass(frozen=True)
class VisualDecision:
    """The classification of one visual candidate for one task."""

    ref: SourceRef
    need: VisualNeed
    reason: str
    requires_pixels: bool = False


def classify_visual(
    task: TaskKind,
    candidate: VisualCandidate,
    cached: CachedFinding | None,
) -> VisualDecision:
    """Classify one candidate as necessary, reusable or decorative.

    The rule is proportionate, not blanket: decoration never justifies work;
    ordinary explanation with no source dependency plans none either; and a
    task whose correctness depends on a particular source either reuses what
    an earlier turn verified or plans to fetch and inspect the original —
    never settles for the caption.
    """
    ref = candidate.ref
    if candidate.importance == "decorative":
        return VisualDecision(ref, "decorative", "decorative for this task")
    if candidate.claim_dependency != "source":
        return VisualDecision(ref, "decorative", "claim does not depend on this source")
    if task == "explain" or candidate.importance == "useful":
        if cached is not None:
            return VisualDecision(ref, "reusable", "verified earlier for this objective")
        if task in _PIXEL_TASKS:
            # Assessment fetches what assessing actually needs; a useful-but-
            # optional panel waits until something depends on it.
            return VisualDecision(ref, "decorative", "not required for this task; fetch on demand")
        return VisualDecision(ref, "necessary", "source-dependent claim; inspect the original")
    # Source-dependent and required: reuse keeps the verified findings, but a
    # pixel-bearing task must re-attach the original to act on them.
    if cached is not None:
        return VisualDecision(
            ref,
            "reusable",
            "verified earlier for this objective",
            requires_pixels=task in _PIXEL_TASKS,
        )
    return VisualDecision(
        ref,
        "necessary",
        "source-dependent claim; inspect the original",
        requires_pixels=True,
    )


@dataclass(frozen=True)
class EvidencePlan:
    """What this task needs done with evidence, as plain followable lists.

    ``fetch_refs`` are figures to retrieve and inspect now (a caption or URL
    is not "seen"). ``reattach_refs`` are already-verified figures a pixel-
    dependent task must put back in front of the model — reuse without
    pretending cached text is pixels. Everything else is settled.
    """

    decisions: tuple[VisualDecision, ...] = ()
    fetch_refs: tuple[SourceRef, ...] = ()
    reattach_refs: tuple[SourceRef, ...] = ()
    reusable_findings: dict[str, str] = field(default_factory=dict)

    @property
    def retrieval_calls(self) -> int:
        """How many evidence retrievals this task plan actually costs."""
        return len(self.fetch_refs) + len(self.reattach_refs)


def select_evidence(
    task: TaskKind,
    objective_id: str,
    candidates: tuple[VisualCandidate, ...] | list[VisualCandidate],
    cache: EvidenceCache,
) -> EvidencePlan:
    """Choose evidence for one task on one objective.

    Args:
        task: What the tutor is about to do (explain, source_claim,
            practice, review).
        objective_id: The objective the findings would belong to; findings
            verified for another objective are not reused.
        candidates: The visuals this turn could involve, each annotated with
            its claim dependency and importance.
        cache: The record of what earlier turns inspected.

    Returns:
        The plan: per-candidate classification, the originals to fetch, the
        originals to re-attach, and the findings that carry over.
    """
    decisions: list[VisualDecision] = []
    fetch: list[SourceRef] = []
    reattach: list[SourceRef] = []
    findings: dict[str, str] = {}
    for candidate in candidates:
        cached = cache.lookup(objective_id, candidate.ref)
        decision = classify_visual(task, candidate, cached)
        decisions.append(decision)
        if decision.need == "necessary":
            fetch.append(candidate.ref)
        elif decision.need == "reusable":
            if cached is not None and cached.findings:
                findings[candidate.ref.key] = cached.findings
            if decision.requires_pixels:
                reattach.append(candidate.ref)
    return EvidencePlan(
        decisions=tuple(decisions),
        fetch_refs=tuple(fetch),
        reattach_refs=tuple(reattach),
        reusable_findings=findings,
    )


__all__ = [
    "CachedFinding",
    "ConceptSpec",
    "EvidenceCache",
    "EvidencePlan",
    "EvidenceText",
    "ObjectivePreparation",
    "SourceRef",
    "VisualCandidate",
    "VisualDecision",
    "classify_visual",
    "prepare_objective",
    "select_evidence",
]
