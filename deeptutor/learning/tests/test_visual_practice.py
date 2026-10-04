"""Source-figure practice: generate → grade → trusted progress evidence.

Covers the #1611 minimal vertical slice end to end: a verified KB visual
asset becomes one caption-grounded exercise, a deterministic grade turns
the submission into an ``AssessmentRecord``, and the canonical
``record_assessment`` writer persists it into the Question Notebook and —
only through trusted objective linkage — as ``LearningEvidence`` on a
mastery path.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from PIL import Image
import pytest

from deeptutor.learning.assessment import record_assessment
from deeptutor.learning.models import (
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
)
from deeptutor.learning.storage import LearningStore
from deeptutor.learning.visual_practice import (
    build_visual_practice_question,
    grade_visual_practice,
    practice_question_from_store,
    public_visual_practice_question,
    visual_practice_record,
)
from deeptutor.services.parsing.types import ParsedDocument
from deeptutor.services.rag.visual_assets import (
    VisualAssetStore,
    collect_visual_assets,
)
from deeptutor.services.session.sqlite_store import SQLiteSessionStore

ASSET_ID = "a" * 64


def _asset_record(**overrides) -> dict:
    record = {
        "asset_id": ASSET_ID,
        "source_document_id": "doc-hash",
        "source_path": "anatomy.pdf",
        "managed_source": True,
        "parser_engine": "mineru",
        "parser_signature": "mineru-signature",
        "source_hash": "source-hash",
        "source_locator": "blocks.json#/0",
        "page_index": 2,
        "page_number": 3,
        "bbox": [10, 20, 100, 200],
        "caption": "Figure 3.1: The fluid mosaic model of a plasma membrane",
        "context": "The membrane is described as a fluid mosaic of lipids and proteins.",
        "image_sha256": "image-hash",
        "mime_type": "image/png",
        "size": 1024,
    }
    record.update(overrides)
    return record


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SQLiteSessionStore:
    instance = SQLiteSessionStore(db_path=tmp_path / "assessment.db")
    monkeypatch.setattr(
        "deeptutor.services.session.get_sqlite_session_store",
        lambda: instance,
    )
    return instance


def _learning_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LearningStore:
    learning_store = LearningStore(root=tmp_path / "learning")
    learning_store.save(
        LearningProgress(
            book_id="path-1",
            modules=[
                LearningModule(
                    id="module-1",
                    name="Module",
                    order=0,
                    knowledge_points=[
                        KnowledgePoint(
                            id="kp-1",
                            name="Plasma membrane",
                            type=KnowledgeType.CONCEPT,
                            module_id="module-1",
                        )
                    ],
                )
            ],
            knowledge_types={"kp-1": KnowledgeType.CONCEPT},
        )
    )
    monkeypatch.setattr("deeptutor.learning.assessment._get_learning_store", lambda: learning_store)
    return learning_store


def test_labeled_caption_builds_figure_subject_question() -> None:
    question = build_visual_practice_question("biology", _asset_record())
    assert question is not None
    assert question.question_id == f"visual:{ASSET_ID[:24]}"
    assert question.kb_name == "biology"
    assert question.source_path == "anatomy.pdf"
    assert question.page_number == 3
    # The key is the caption subject, not the label.
    assert question.expected_answer == "The fluid mosaic model of a plasma membrane"
    assert "Figure 3.1" in question.prompt
    assert "anatomy.pdf" in question.prompt
    assert "page 3" in question.prompt
    # Long subject grades as open, short captions as short.
    assert question.question_type == "open"
    assert build_visual_practice_question(
        "biology", _asset_record(caption="Figure 1: Heart chamber")
    ).question_type == ("short")
    # Deterministic rebuild.
    again = build_visual_practice_question("biology", _asset_record())
    assert again == question


def test_unlabeled_caption_still_grounds_but_thin_captions_refuse() -> None:
    unlabeled = build_visual_practice_question(
        "biology", _asset_record(caption="Fluid mosaic model of the membrane")
    )
    assert unlabeled is not None
    assert unlabeled.expected_answer == "Fluid mosaic model of the membrane"
    assert "Figure" not in unlabeled.prompt

    # An asset without caption grounding must not become an answer key.
    assert build_visual_practice_question("biology", _asset_record(caption="")) is None
    assert build_visual_practice_question("biology", _asset_record(caption="chart")) is None
    assert build_visual_practice_question("biology", _asset_record(caption="Figure 3.1")) is None
    # A caption that is only a label is not a subject either.
    assert build_visual_practice_question("biology", _asset_record(caption="Figure 3.1: —")) is None
    # Malformed identity never produces a question.
    assert build_visual_practice_question("biology", _asset_record(asset_id="nothex")) is None


def test_public_projection_never_leaks_the_answer_key() -> None:
    question = build_visual_practice_question("biology", _asset_record())
    assert question is not None
    public = public_visual_practice_question(question)
    assert set(public) == {
        "question_id",
        "kb_name",
        "asset_id",
        "task",
        "prompt",
        "question_type",
    }
    assert question.expected_answer not in public.values()
    assert question.explanation not in public.values()


def test_grading_accepts_equivalent_terminology_and_rejects_wrong_answers() -> None:
    short = build_visual_practice_question(
        "biology", _asset_record(caption="Figure 1: Heart chamber")
    )
    assert short is not None
    assert grade_visual_practice(short, "heart chamber") is True
    assert grade_visual_practice(short, "Heart Chamber.") is True
    assert grade_visual_practice(short, "liver lobule") is False
    assert grade_visual_practice(short, "  ") is False

    long_subject = build_visual_practice_question("biology", _asset_record())
    assert long_subject is not None
    # Recomposed wording with the significant source terms still passes.
    assert (
        grade_visual_practice(long_subject, "the plasma membrane as a fluid mosaic model") is True
    )
    # A substantively different answer fails even though it is fluent.
    assert grade_visual_practice(long_subject, "the cell wall of a plant cell") is False


def test_question_resolves_from_a_real_visual_asset_store(tmp_path: Path) -> None:
    kb_dir = tmp_path / "kb"
    raw = kb_dir / "raw"
    raw.mkdir(parents=True)
    source = raw / "lesson.pdf"
    source.write_bytes(b"source document with a figure")
    assets = tmp_path / "parse-cache" / "images"
    assets.mkdir(parents=True)
    Image.new("RGB", (3, 2), color=(17, 99, 211)).save(assets / "figure.png")
    parsed = ParsedDocument(
        markdown="![Learning curve](images/figure.png)",
        blocks=[
            {
                "type": "image",
                "img_path": str(assets / "figure.png"),
                "page_idx": 2,
                "bbox": [10, 20, 100, 200],
                "image_caption": ["Learning curve"],
            }
        ],
        asset_dir=assets,
        source_hash="source-hash",
        parser_signature="mineru-signature",
        engine="mineru",
    )
    candidates = collect_visual_assets(parsed, source, kb_dir)
    asset_store = VisualAssetStore(kb_dir)
    asset_store.publish(candidates, replace=True)
    asset_id = candidates[0].record["asset_id"]

    question = practice_question_from_store(asset_store, "lesson-kb", asset_id)
    assert question is not None
    assert question.asset_id == asset_id
    assert question.expected_answer == "Learning curve"
    assert practice_question_from_store(asset_store, "lesson-kb", "x" * 64) is None


def test_graded_practice_becomes_trusted_learning_evidence(
    store: SQLiteSessionStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    learning_store = _learning_path(tmp_path, monkeypatch)
    question = build_visual_practice_question("biology", _asset_record())
    assert question is not None
    user_answer = "the plasma membrane as a fluid mosaic model"
    is_correct = grade_visual_practice(question, user_answer)
    assert is_correct is True

    outcome = asyncio.run(
        record_assessment(
            visual_practice_record(
                question,
                user_answer=user_answer,
                is_correct=is_correct,
                mastery_path_id="path-1",
                knowledge_point_id="kp-1",
            )
        )
    )
    assert outcome.attempt_recorded is True
    assert "linked_retention_updated" in outcome.diagnostics

    progress = learning_store.load("path-1")
    assert len(progress.learning_evidence) == 1
    evidence = progress.learning_evidence[0]
    assert evidence.source == "source_visual"
    assert evidence.knowledge_point_id == "kp-1"
    assert evidence.question_id == question.question_id
    assert evidence.result == "correct"
    assert progress.repetition_states["kp-1"].review_count == 1

    # The notebook keeps the source figure provenance for review.
    entry = asyncio.run(
        store.find_notebook_entry_by_origin(
            "document_analysis",
            f"visual:biology:{ASSET_ID[:12]}",
            question.question_id,
            turn_id=ASSET_ID,
        )
    )
    assert entry is not None
    assert entry["source"] == "source_visual"
    assert entry["section_id"] == ASSET_ID
    assert entry["correct_answer"] == question.expected_answer

    # A repeated submission of the same attempt counts once.
    retry = asyncio.run(
        record_assessment(
            visual_practice_record(
                question,
                user_answer=user_answer,
                is_correct=is_correct,
                mastery_path_id="path-1",
                knowledge_point_id="kp-1",
            )
        )
    )
    assert retry.attempt_recorded is False
    assert len(learning_store.load("path-1").learning_evidence) == 1


def test_wrong_answer_records_incorrect_evidence_once(
    store: SQLiteSessionStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    learning_store = _learning_path(tmp_path, monkeypatch)
    question = build_visual_practice_question("biology", _asset_record())
    assert question is not None
    assert grade_visual_practice(question, "the cell wall of a plant cell") is False

    asyncio.run(
        record_assessment(
            visual_practice_record(
                question,
                user_answer="the cell wall of a plant cell",
                is_correct=False,
                mastery_path_id="path-1",
                knowledge_point_id="kp-1",
            )
        )
    )
    progress = learning_store.load("path-1")
    assert progress.learning_evidence[0].result == "incorrect"
    assert progress.repetition_states["kp-1"].consecutive_wrong == 1


def test_untrusted_objective_linkage_keeps_the_attempt_but_writes_no_evidence(
    store: SQLiteSessionStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    learning_store = _learning_path(tmp_path, monkeypatch)
    question = build_visual_practice_question("biology", _asset_record())
    assert question is not None

    outcome = asyncio.run(
        record_assessment(
            visual_practice_record(
                question,
                user_answer="the plasma membrane as a fluid mosaic model",
                is_correct=True,
                mastery_path_id="path-1",
                knowledge_point_id="kp-does-not-exist",
            )
        )
    )
    assert "dropped_invalid_mastery_linkage" in outcome.diagnostics
    assert learning_store.load("path-1").learning_evidence == []
    entry = asyncio.run(
        store.find_notebook_entry_by_origin(
            "document_analysis",
            f"visual:biology:{ASSET_ID[:12]}",
            question.question_id,
            turn_id=ASSET_ID,
        )
    )
    assert entry is not None
    assert entry["mastery_path_id"] == ""
