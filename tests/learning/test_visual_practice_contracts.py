"""Source-bound visual practice: key verification, cues and grading gates."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.learning.models import PendingOption, PendingQuestion
import deeptutor.learning.visual_practice as vp
from deeptutor.learning.visual_practice import (
    account_for_recent_assistance,
    evaluate_visual,
    normalized_answer,
    prepare_visual,
    public_visual,
)
import deeptutor.multi_user.knowledge_access as knowledge_access
import deeptutor.services.rag.kb_paths as kb_paths
import deeptutor.services.rag.source_visuals as source_visuals

RECORD = {
    "asset_id": "a1",
    "source_path": "paper.pdf",
    "page_number": 3,
    "source_document_id": "doc123",
    "region": None,
    "text": "The mitochondrion is the powerhouse of the cell.",
}
PAGE_TEXT = "The cell wall is rigid and lies outside the membrane."


class _Resource:
    base_dir = "/data/kbs"
    name = "kb"


class _Evidence:
    def __init__(self, record=None, *, error="", images=None):
        self.error = error
        self.content = error
        self.images = images if images is not None else [(record or RECORD, b"png-bytes")]
        self.sources = [{"visual_asset_url": "/assets/a1.png", "url": "/source/paper.pdf#p3"}]


def _install_rag(monkeypatch, tmp_path, *, evidence=None, resource=_Resource()):
    seen: dict[str, object] = {}

    def fake_retrieve(kb_dir, kb_name, **selectors):
        seen["kb_dir"] = kb_dir
        seen["kb_name"] = kb_name
        seen["selectors"] = selectors
        if evidence is not None:
            if isinstance(evidence, Exception):
                raise evidence
            return evidence
        return _Evidence()

    monkeypatch.setattr(knowledge_access, "resolve_for_rag", lambda kb_name: resource)
    monkeypatch.setattr(kb_paths, "resolve_kb_dir", lambda base, name: tmp_path / "kb")
    monkeypatch.setattr(source_visuals, "retrieve_visual", fake_retrieve)
    return seen


def _request(**overrides) -> dict:
    request = {
        "task": "identification",
        "sources": [{"kb_name": "kb", "asset_id": "a1", "source_path": "paper.pdf"}],
        "reference_quote": "mitochondrion is the powerhouse",
        "key_status": "verified",
        "answer_cues": "none",
        "pixels_inspected": True,
    }
    request.update(overrides)
    return request


def test_normalized_answer_collapses_whitespace_and_strips_trailing_marks() -> None:
    assert normalized_answer("  a  b\t\nc。") == "a b c"
    assert normalized_answer("对！") == "对"
    assert normalized_answer("Yes.") == "yes"


def test_normalized_answer_nfkc_and_casefold() -> None:
    assert normalized_answer("ＡＴＰ") == "atp"
    assert normalized_answer("ＡｂＣ\n\tＤ") == "abc d"
    assert normalized_answer("MiToChOnDrIoN") == "mitochondrion"


@pytest.mark.parametrize(
    ("answer", "quote", "expected"),
    [
        ("cell", "the cellulose wall", False),
        ("cell", "a cell wall", True),
        ("线粒体", "叶绿体和线粒体都存在", True),
        ("", "anything", False),
        ("rigid.", "the cell wall is rigid", True),
    ],
)
def test_answer_in_quote_boundaries(answer: str, quote: str, expected: bool) -> None:
    assert vp._answer_in_quote(answer, normalized_answer(quote)) is expected


def test_public_visual_projects_only_learner_safe_keys() -> None:
    context = {
        "task": "identification",
        "sources": [{"kb_name": "kb"}],
        "answer_cues": "visible",
        "key_status": "unverified",
        "hints_used": 2,
        "pixels_inspected": True,
        "reference_quote": "hidden",
        "reference_answer": "hidden",
    }
    assert public_visual(context) == {
        "task": "identification",
        "sources": [{"kb_name": "kb"}],
        "answer_cues": "visible",
        "key_status": "unverified",
        "hints_used": 2,
        "pixels_inspected": True,
    }


def test_public_visual_skips_absent_keys() -> None:
    assert public_visual({"task": "identification"}) == {"task": "identification"}


@pytest.mark.parametrize("task", ["quiz", "IDENTIFICATION"])
def test_prepare_visual_rejects_unknown_task(task: str, monkeypatch, tmp_path) -> None:
    _install_rag(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="identification, relationship"):
        prepare_visual(_request(task=task), expected_answer="B", options={"B": "body"})


def test_prepare_visual_requires_two_sources_for_comparison(monkeypatch, tmp_path) -> None:
    _install_rag(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="requires both original sources"):
        prepare_visual(_request(task="comparison"), expected_answer="B", options={"B": "body"})


@pytest.mark.parametrize("refs", [[], [{"kb_name": "kb"}, {"kb_name": "kb"}, {"kb_name": "kb"}]])
def test_prepare_visual_bounds_source_count(refs: list, monkeypatch, tmp_path) -> None:
    _install_rag(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="one or two exact source"):
        prepare_visual(_request(sources=refs), expected_answer="B", options={"B": "body"})


def test_prepare_visual_rejects_non_object_sources(monkeypatch, tmp_path) -> None:
    _install_rag(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="must be an object"):
        prepare_visual(_request(sources=["paper.pdf"]), expected_answer="B", options={"B": "body"})


def test_prepare_visual_rejects_unattached_knowledge_base(monkeypatch, tmp_path) -> None:
    _install_rag(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="attached to this topic"):
        prepare_visual(
            _request(),
            expected_answer="B",
            options={"B": "body"},
            attached_kbs=["other-kb"],
        )


def test_prepare_visual_rejects_inaccessible_source(monkeypatch, tmp_path) -> None:
    _install_rag(monkeypatch, tmp_path, resource=None)
    with pytest.raises(ValueError, match="not accessible"):
        prepare_visual(_request(), expected_answer="B", options={"B": "body"})


@pytest.mark.parametrize("evidence", [_Evidence(error="missing"), _Evidence(images=[])])
def test_prepare_visual_requires_visual_evidence(evidence, monkeypatch, tmp_path) -> None:
    _install_rag(monkeypatch, tmp_path, evidence=evidence)
    with pytest.raises(ValueError, match="original visual evidence"):
        prepare_visual(_request(), expected_answer="B", options={"B": "body"})


def test_prepare_visual_caps_accepted_answers(monkeypatch, tmp_path) -> None:
    _install_rag(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="at most 12"):
        prepare_visual(
            _request(accepted_answers=[f"alias{i}" for i in range(13)]),
            expected_answer="B",
            options={"B": "body"},
        )


def test_prepare_visual_validates_answer_cues(monkeypatch, tmp_path) -> None:
    _install_rag(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="none, visible or unverified"):
        prepare_visual(_request(answer_cues="obvious"), expected_answer="B", options={"B": "body"})


def test_prepare_visual_keeps_unverified_without_pixel_inspection(monkeypatch, tmp_path) -> None:
    _install_rag(monkeypatch, tmp_path)
    prepared, _ = prepare_visual(
        _request(pixels_inspected=False), expected_answer="B", options={"B": "body"}
    )
    assert prepared["key_status"] == "unverified"
    assert prepared["pixels_inspected"] is False
    assert prepared["answer_cues"] == "unverified"


def test_prepare_visual_verifies_quote_backed_key(monkeypatch, tmp_path) -> None:
    seen = _install_rag(monkeypatch, tmp_path)
    prepared, aliases = prepare_visual(
        _request(accepted_answers=[" powerhouse "]),
        expected_answer="B",
        options={"B": "Mitochondrion"},
    )

    assert seen["kb_name"] == "kb"
    assert seen["selectors"] == {"asset_id": "a1", "source_path": "paper.pdf"}
    assert prepared["key_status"] == "verified"
    assert prepared["pixels_inspected"] is True
    assert prepared["answer_cues"] == "none"
    assert prepared["reference_answer"] == "Mitochondrion"
    assert prepared["hints_used"] == 0
    assert aliases == ["Mitochondrion", "powerhouse"]


def test_prepare_visual_reports_page_only_source_as_visible_cue(monkeypatch, tmp_path) -> None:
    record = {
        "asset_id": "",
        "source_path": "paper.pdf",
        "page_number": 3,
        "source_document_id": "doc123",
        "text": PAGE_TEXT,
    }
    _install_rag(monkeypatch, tmp_path, evidence=_Evidence(record=record))
    prepared, _ = prepare_visual(
        _request(
            sources=[{"kb_name": "kb", "source_path": "paper.pdf", "page": 3}],
            reference_quote="the cell wall is rigid",
        ),
        expected_answer="rigid",
        options={"rigid": "rigid"},
    )

    assert prepared["sources"][0]["visible_answer_text"] is True
    assert prepared["answer_cues"] == "visible"
    assert prepared["hints_used"] == 1
    assert prepared["key_status"] == "verified"


def test_prepare_visual_hides_visible_cue_when_asset_is_inspected(monkeypatch, tmp_path) -> None:
    record = {**RECORD, "text": "An unlabeled figure."}
    _install_rag(monkeypatch, tmp_path, evidence=_Evidence(record=record))
    prepared, _ = prepare_visual(_request(), expected_answer="B", options={"B": "body"})
    assert prepared["sources"][0]["visible_answer_text"] is False
    assert prepared["answer_cues"] == "none"


def test_prepare_visual_preserves_declared_hints(monkeypatch, tmp_path) -> None:
    _install_rag(monkeypatch, tmp_path)
    prepared, _ = prepare_visual(_request(hints_used=2), expected_answer="B", options={"B": "body"})
    assert prepared["hints_used"] == 2


def _attempt(**overrides) -> SimpleNamespace:
    fields = {
        "knowledge_point_id": "kp1",
        "voided": False,
        "timestamp": 0.0,
        "visual_context": {},
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _visual_context(**overrides) -> dict:
    context = {
        "task": "identification",
        "sources": [{"source_hash": "doc123", "page": 3}],
        "answer_cues": "none",
        "key_status": "verified",
        "hints_used": 0,
        "pixels_inspected": True,
        "reference_quote": "the cell wall is rigid",
        "reference_answer": "rigid",
    }
    context.update(overrides)
    return context


def test_recent_assistance_flags_repeated_same_question() -> None:
    import time

    prior = _attempt(
        timestamp=time.time() - 60,
        visual_context=_visual_context(),
    )
    assisted = account_for_recent_assistance(_visual_context(), [prior], "kp1")
    assert assisted["recently_assisted"] is True
    assert assisted["hints_used"] == 1


def test_recent_assistance_ignores_voided_or_stale_attempts() -> None:
    import time

    stale = _attempt(timestamp=time.time() - 3 * 86400, visual_context=_visual_context())
    voided = _attempt(timestamp=time.time() - 60, voided=True, visual_context=_visual_context())
    for attempt in (stale, voided):
        context = account_for_recent_assistance(_visual_context(), [attempt], "kp1")
        assert "recently_assisted" not in context


def test_recent_assistance_ignores_other_objectives_and_locations() -> None:
    import time

    other_kp = _attempt(timestamp=time.time() - 60, knowledge_point_id="kp2")
    other_kp.visual_context = _visual_context()
    moved = _attempt(
        timestamp=time.time() - 60,
        visual_context=_visual_context(sources=[{"source_hash": "other", "page": 9}]),
    )
    for attempt in (other_kp, moved):
        context = account_for_recent_assistance(_visual_context(), [attempt], "kp1")
        assert "recently_assisted" not in context
        assert context["hints_used"] == 0


def _pending(**overrides) -> PendingQuestion:
    fields = {
        "question_id": "q1",
        "knowledge_point_id": "kp1",
        "question_type": "short",
        "expected_answer": "photosynthesis",
        "accepted_answers": ["Photosynthesis."],
        "visual_context": _visual_context(
            sources=[{"kb_name": "kb", "asset_id": "a1", "source_path": "paper.pdf"}]
        ),
    }
    fields.update(overrides)
    return PendingQuestion(**fields)


def test_evaluate_visual_refuses_uninspected_pixels(monkeypatch) -> None:
    pending = _pending()
    pending.visual_context["pixels_inspected"] = False
    result, diagnosis = evaluate_visual(pending, "photosynthesis")
    assert result == "ungraded"
    assert diagnosis.startswith("No matching source pixels")


def test_evaluate_visual_refuses_unverified_key(monkeypatch) -> None:
    pending = _pending()
    pending.visual_context["key_status"] = "unverified"
    result, _ = evaluate_visual(pending, "photosynthesis")
    assert result == "ungraded"


def test_evaluate_visual_refuses_missing_sources(monkeypatch, tmp_path) -> None:
    _install_rag(monkeypatch, tmp_path)
    pending = _pending()
    pending.visual_context["sources"] = []
    result, _ = evaluate_visual(pending, "photosynthesis")
    assert result == "ungraded"


def test_evaluate_visual_downgrades_when_source_access_is_gone(monkeypatch, tmp_path) -> None:
    _install_rag(monkeypatch, tmp_path, resource=None)
    result, diagnosis = evaluate_visual(_pending(), "photosynthesis")
    assert result == "ungraded"
    assert "Source access is unavailable" in diagnosis


def test_evaluate_visual_downgrades_when_evidence_changed(monkeypatch, tmp_path) -> None:
    _install_rag(monkeypatch, tmp_path, evidence=_Evidence(error="moved"))
    result, diagnosis = evaluate_visual(_pending(), "photosynthesis")
    assert result == "ungraded"
    assert "changed or is unavailable" in diagnosis


def test_evaluate_visual_accepts_verified_equivalent(monkeypatch, tmp_path) -> None:
    _install_rag(monkeypatch, tmp_path)
    result, diagnosis = evaluate_visual(_pending(), "PHOTOSYNTHESIS")
    assert (result, diagnosis) == ("correct", "Accepted source-specific equivalent terminology.")


def _choice_pending(expected: str) -> PendingQuestion:
    return _pending(
        question_type="choice",
        expected_answer=expected,
        options=[
            PendingOption(label="A", body="Respiration"),
            PendingOption(label="B", body="Photosynthesis"),
        ],
        accepted_answers=[],
    )


def test_evaluate_visual_grades_committed_choice(monkeypatch, tmp_path) -> None:
    _install_rag(monkeypatch, tmp_path)
    assert evaluate_visual(_choice_pending("B"), "B")[0] == "correct"
    assert evaluate_visual(_choice_pending("B"), "select B")[0] == "correct"
    assert evaluate_visual(_choice_pending("A"), "B")[0] == "incorrect"


def test_evaluate_visual_treats_unmappable_choice_as_ungraded(monkeypatch, tmp_path) -> None:
    _install_rag(monkeypatch, tmp_path)
    result, diagnosis = evaluate_visual(_choice_pending("B"), "why is B wrong?")
    assert result == "ungraded"
    assert "Clarify the selected answer" in diagnosis


def test_evaluate_visual_never_infers_from_prose_similarity(monkeypatch, tmp_path) -> None:
    _install_rag(monkeypatch, tmp_path)
    result, diagnosis = evaluate_visual(_pending(), "photosynthesizing broadly")
    assert result == "ungraded"
    assert "not a verified equivalent" in diagnosis
