"""Objective preparation and task-classified evidence selection (#1902)."""

from __future__ import annotations

from deeptutor.learning.lesson_preparation import (
    ConceptSpec,
    EvidenceCache,
    EvidenceText,
    SourceRef,
    VisualCandidate,
    classify_visual,
    prepare_objective,
    select_evidence,
)

FIG1 = SourceRef(kb_name="kb", asset_id="fig-1", page=12, source_hash="doc-a")
TABLE1 = SourceRef(kb_name="kb", asset_id="tab-1", page=30, source_hash="doc-a")


def test_ordinary_explanation_requires_no_new_retrieval():
    # #1902: a general conceptual follow-up should be fast — no blanket
    # image rule, no forced retrieval per sentence.
    cache = EvidenceCache()
    plan = select_evidence(
        "explain",
        "kp-1",
        [
            VisualCandidate(FIG1, claim_dependency="none", importance="required"),
            VisualCandidate(TABLE1, claim_dependency="none", importance="useful"),
        ],
        cache,
    )
    assert [d.need for d in plan.decisions] == ["decorative", "decorative"]
    assert plan.fetch_refs == ()
    assert plan.reattach_refs == ()
    assert plan.retrieval_calls == 0


def test_source_dependent_claim_requires_original_pixels():
    # Correctness depends on the material → fetch and inspect the original;
    # a caption or URL is not "having seen it".
    cache = EvidenceCache()
    plan = select_evidence(
        "source_claim",
        "kp-1",
        [VisualCandidate(FIG1, claim_dependency="source", importance="required")],
        cache,
    )
    assert [d.need for d in plan.decisions] == ["necessary"]
    assert plan.fetch_refs == (FIG1,)
    assert plan.decisions[0].requires_pixels is True


def test_cached_evidence_is_reused_without_refetch():
    cache = EvidenceCache()
    cache.record("kp-1", FIG1, findings="Label 1 marks the artery; label 2 the vein.")
    plan = select_evidence(
        "source_claim",
        "kp-1",
        [VisualCandidate(FIG1, claim_dependency="source", importance="required")],
        cache,
    )
    assert [d.need for d in plan.decisions] == ["reusable"]
    assert plan.fetch_refs == ()
    assert plan.retrieval_calls == 0
    # Cached text must not imply the current model request sees pixels.
    assert plan.reusable_findings[FIG1.key].startswith("Label 1")
    assert cache.lookup("kp-1", FIG1).pixels_in_context is False


def test_practice_reuses_findings_but_reattaches_pixels():
    # Reuse retains source/objective identity, yet a pixel-dependent task
    # must re-attach the original image instead of trusting cached text.
    cache = EvidenceCache()
    cache.record("kp-1", FIG1, findings="Label 1 marks the artery.")
    plan = select_evidence(
        "practice",
        "kp-1",
        [VisualCandidate(FIG1, claim_dependency="source", importance="required")],
        cache,
    )
    assert [d.need for d in plan.decisions] == ["reusable"]
    assert plan.decisions[0].requires_pixels is True
    assert plan.fetch_refs == ()
    assert plan.reattach_refs == (FIG1,)
    assert plan.reusable_findings[FIG1.key] == "Label 1 marks the artery."


def test_decorative_visual_is_never_fetched():
    cache = EvidenceCache()
    candidate = VisualCandidate(FIG1, claim_dependency="none", importance="decorative")
    for task in ("explain", "source_claim", "practice", "review"):
        decision = classify_visual(task, candidate, cache.lookup("kp-1", FIG1))
        assert decision.need == "decorative"
        assert decision.requires_pixels is False


def test_changed_source_or_objective_invalidates_cache():
    cache = EvidenceCache()
    cache.record("kp-1", FIG1, findings="Label 1 marks the artery.")
    changed_source = SourceRef(
        kb_name="kb", asset_id="fig-1", page=12, source_hash="doc-a-reindexed"
    )
    for objective_id, ref in (("kp-1", changed_source), ("kp-2", FIG1)):
        decision = classify_visual(
            "source_claim",
            VisualCandidate(ref, claim_dependency="source", importance="required"),
            cache.lookup(objective_id, ref),
        )
        assert decision.need == "necessary"


def test_partial_retrieval_is_not_full_coverage():
    preparation = prepare_objective(
        objective_id="kp-1",
        concepts=(
            ConceptSpec("artery vs vein"),
            ConceptSpec("blood flow direction", prerequisites=("artery vs vein",)),
        ),
        evidence=(EvidenceText(source_hash="doc-a", covers=("artery vs vein",), partial=True),),
    )
    assert preparation.coverage == "partial"
    assert preparation.supported == ("artery vs vein",)
    assert preparation.unresolved == ("blood flow direction",)
    assert preparation.adequate is False


def test_adequate_preparation_is_reused_until_sources_change():
    evidence = (
        EvidenceText(source_hash="doc-a", covers=("artery vs vein", "blood flow direction")),
        EvidenceText(source_hash="doc-b", covers=("capillary exchange",)),
    )
    concepts = (
        ConceptSpec("artery vs vein"),
        ConceptSpec("blood flow direction"),
        ConceptSpec("capillary exchange"),
    )
    prior = prepare_objective(objective_id="kp-1", concepts=concepts, evidence=evidence)
    assert prior.adequate is True
    assert prior.missing_prerequisites == ()
    assert (
        prepare_objective(objective_id="kp-1", concepts=concepts, evidence=evidence, prior=prior)
        is prior
    )
    # A changed source set or objective invalidates the record.
    assert (
        prepare_objective(
            objective_id="kp-1",
            concepts=concepts,
            evidence=evidence[:1],
            prior=prior,
        ).coverage
        == "partial"
    )


def test_uncovered_prerequisites_are_reported_not_guessed():
    preparation = prepare_objective(
        objective_id="kp-1",
        concepts=(ConceptSpec("blood flow direction", prerequisites=("vessel structure",)),),
        evidence=(EvidenceText(source_hash="doc-a", covers=("blood flow direction",)),),
    )
    # The concept is supported, but its prerequisite is not in the material:
    # named as missing, never silently replaced by general knowledge.
    assert preparation.coverage == "supported"
    assert preparation.missing_prerequisites == ("vessel structure",)
