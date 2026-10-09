"""Semantic free-form assessment beyond the alias fast path (#1901).

The deterministic alias/choice fast paths stay untouched; these tests cover
the extended boundary: contradiction detection (negation, reversed
relationships, label misplacement), the optional qualitative evaluator with
its correct/partial/incorrect/unreliable verdicts, and the guarantee that an
unreliable evaluation never records negative mastery evidence. All evaluator
calls are fakes — no real model is invoked.
"""

from __future__ import annotations

from hashlib import sha256
from types import SimpleNamespace

from PIL import Image, ImageDraw
import pymupdf
import pytest

from deeptutor.learning.models import (
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
)
from deeptutor.learning.policy import is_assessed_mastered
from deeptutor.learning.scheduler import SpacedRepetitionScheduler
from deeptutor.learning.service import LearningService
from deeptutor.learning.storage import LearningStore
from deeptutor.learning.visual_practice import prepare_visual
from deeptutor.services.parsing.types import ParsedDocument
from deeptutor.services.rag.visual_assets import VisualAssetStore, collect_visual_assets

QUOTE = "Number 1 refers to an artery. The artery lies left of the vein."


@pytest.fixture
def lesson(tmp_path, monkeypatch):
    kb = tmp_path / "kb"
    (kb / "raw").mkdir(parents=True)
    source = kb / "raw" / "anatomy.pdf"
    image = tmp_path / "images" / "numbered.png"
    image.parent.mkdir()
    picture = Image.new("RGB", (400, 250), "white")
    draw = ImageDraw.Draw(picture)
    draw.ellipse((40, 40, 160, 200), outline="red", width=4)
    draw.text((95, 110), "1", fill="black")
    draw.ellipse((220, 40, 340, 200), outline="blue", width=4)
    draw.text((270, 110), "2", fill="black")
    picture.save(image)
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((50, 50), QUOTE)
    page.insert_image(pymupdf.Rect(50, 80, 450, 330), filename=str(image))
    pdf.save(source, deflate=True)
    pdf.close()
    parsed = ParsedDocument(
        markdown="",
        asset_dir=image.parent,
        parser_signature="fixture",
        blocks=[
            {
                "type": "image",
                "img_path": str(image),
                "page_idx": 0,
                "image_caption": ["Figure 1: numbered structures"],
                "text": QUOTE,
            }
        ],
    )
    candidate = collect_visual_assets(parsed, source, kb)[0]
    VisualAssetStore(kb).publish([candidate])
    monkeypatch.setattr(
        "deeptutor.multi_user.knowledge_access.resolve_for_rag",
        lambda name: SimpleNamespace(base_dir=kb.parent, name=kb.name) if name == "kb" else None,
    )
    store = LearningStore(tmp_path / "learning")
    service = LearningService(store)
    progress = LearningProgress(book_id="visual")
    kp = KnowledgePoint(
        id="identify",
        name="Identify and interpret the original source",
        type=KnowledgeType.MEMORY,
        module_id="m1",
        required_visual_tasks=["identification"],
    )
    progress.modules = [
        LearningModule(id="m1", name="Source practice", order=0, knowledge_points=[kp])
    ]
    progress.knowledge_types[kp.id] = kp.type
    service.save(progress)
    return SimpleNamespace(
        kb=kb,
        asset=candidate.record["asset_id"],
        image_hash=candidate.record["image_sha256"],
        service=service,
        store=store,
        kp=kp,
    )


def posed(lesson, *, expected="artery", question_type="short", options=None):
    from deeptutor.learning.models import PendingOption, PendingQuestion

    option_rows = [PendingOption(**option) for option in (options or [])]
    option_map = {option["label"]: option["body"] for option in (options or [])}
    request = {
        "task": "identification",
        "sources": [{"kb_name": "kb", "asset_id": lesson.asset}],
        "reference_quote": QUOTE,
        "accepted_answers": ["artery", "an artery", "动脉"],
        "key_status": "verified",
        "answer_cues": "none",
    }
    context, aliases = prepare_visual(
        request,
        expected_answer=expected,
        options=option_map,
        attached_kbs=["kb"],
        inspected_image_hashes=[lesson.image_hash],
    )
    assert context["key_status"] == "verified"
    pending = PendingQuestion(
        question_id=sha256(
            (expected + question_type + str(option_map)).encode(), usedforsecurity=False
        ).hexdigest(),
        knowledge_point_id="identify",
        module_id="m1",
        prompt="Identify numbered structure 1 in the original figure.",
        question_type=question_type,
        expected_answer=expected,
        options=option_rows,
        visual_context=context,
        accepted_answers=aliases,
    )
    lesson.service.register_question("visual", pending)
    return pending.question_id


def grade(lesson, question_id, answer, evaluator=None):
    progress, interaction, _ = lesson.service.grade_interaction(
        "visual",
        answer=answer,
        question_id=question_id,
        scheduler=SpacedRepetitionScheduler(),
        semantic_evaluator=evaluator,
    )
    return progress, interaction


def refuse_call(reference):  # pragma: no cover - failing by design
    raise AssertionError("fast paths must not consult the evaluator")


def test_alias_fast_path_never_consults_the_evaluator(lesson):
    question_id = posed(lesson)
    progress, interaction = grade(lesson, question_id, "动脉", evaluator=refuse_call)
    assert interaction.result["result"] == "correct"
    assert interaction.result["is_correct"] is True
    assert progress.quiz_attempts[-1].independent
    from deeptutor.learning.policy import visual_achievements

    assert visual_achievements(progress, "identify") == ["identification"]


def test_choice_fast_path_stays_deterministic(lesson):
    options = [{"label": "A", "body": "vein"}, {"label": "B", "body": "artery"}]
    question_id = posed(
        lesson,
        expected="B",
        question_type="choice",
        options=options,
    )
    progress, interaction = grade(lesson, question_id, "A", evaluator=refuse_call)
    assert interaction.result["result"] == "incorrect"
    assert interaction.result["is_correct"] is False


def test_reversed_relationship_is_incorrect_without_an_evaluator(lesson):
    question_id = posed(lesson)
    progress, interaction = grade(lesson, question_id, "The vein lies left of the artery.")
    assert interaction.result["result"] == "incorrect"
    assert "revers" in interaction.result["diagnosis"].lower()
    assert progress.quiz_attempts[-1].is_correct is False
    assert not is_assessed_mastered(progress, lesson.kp)


def test_negated_answer_is_incorrect_with_specific_diagnosis(lesson):
    question_id = posed(lesson)
    progress, interaction = grade(lesson, question_id, "Structure 1 is not an artery.")
    assert interaction.result["result"] == "incorrect"
    assert "negat" in interaction.result["diagnosis"].lower()
    assert progress.quiz_attempts[-1].is_correct is False


def test_wrong_label_is_incorrect_with_misplacement_diagnosis(lesson):
    question_id = posed(lesson)
    progress, interaction = grade(lesson, question_id, "Number 2 refers to an artery.")
    assert interaction.result["result"] == "incorrect"
    assert "label" in interaction.result["diagnosis"].lower()
    assert progress.quiz_attempts[-1].is_correct is False


def test_consistent_restatement_stays_conservative_without_an_evaluator(lesson):
    question_id = posed(lesson)
    progress, interaction = grade(lesson, question_id, "The artery sits to the left of the vein.")
    assert interaction.result["result"] == "ungraded"
    assert interaction.result["is_correct"] is None
    assert not progress.quiz_attempts
    assert not is_assessed_mastered(progress, lesson.kp)


def test_evaluator_accepts_paraphrase_for_meaning(lesson):
    question_id = posed(lesson)
    seen = []

    def evaluator(reference):
        seen.append(reference)
        return {"verdict": "correct", "diagnosis": "Same structure, learner's own words."}

    progress, interaction = grade(
        lesson, question_id, "a blood vessel that carries blood away from the heart", evaluator
    )
    assert interaction.result["result"] == "correct"
    assert interaction.result["is_correct"] is True
    assert seen and seen[0]["reference_quote"] == QUOTE
    assert seen[0]["reference_answer"] == "artery"
    assert "动脉" in seen[0]["accepted_answers"]
    assert seen[0]["sources"][0]["kb_name"] == "kb"
    assert "blood vessel" in seen[0]["answer"]


def test_evaluator_partial_keeps_distinct_result_and_no_full_mastery(lesson):
    question_id = posed(lesson)
    before = lesson.store.load("visual")

    def evaluator(reference):
        return {
            "verdict": "partial",
            "diagnosis": "Names the vessel but omits the left-of relationship.",
        }

    progress, interaction = grade(
        lesson, question_id, "it is some kind of blood vessel, I think", evaluator
    )
    assert interaction.result["result"] == "partial"
    assert interaction.result["is_correct"] is False
    assert "left-of" in interaction.result["diagnosis"]
    assert progress.quiz_attempts[-1].is_correct is False
    assert not is_assessed_mastered(progress, lesson.kp)
    assert progress.mastery_levels.get("identify", 0.0) <= before.mastery_levels.get(
        "identify", 0.0
    )


def test_evaluator_unreliable_records_no_negative_evidence(lesson):
    question_id = posed(lesson)
    before = lesson.store.load("visual")
    attempts_before = len(before.quiz_attempts)
    evidence_before = len(before.learning_evidence)

    def evaluator(reference):
        return {"verdict": "unreliable", "diagnosis": "Cannot verify against the figure."}

    progress, interaction = grade(lesson, question_id, "maybe the big red thing", evaluator)
    assert interaction.result["result"] == "ungraded"
    assert interaction.result["is_correct"] is None
    assert len(progress.quiz_attempts) == attempts_before
    assert len(progress.learning_evidence) == evidence_before


def test_evaluator_failure_or_invalid_verdict_stays_ungraded(lesson):
    question_id = posed(lesson)

    def exploding(reference):
        raise RuntimeError("evaluator unavailable")

    progress, interaction = grade(lesson, question_id, "the red circle", exploding)
    assert interaction.result["result"] == "ungraded"
    assert not progress.quiz_attempts

    question_id = posed(lesson, expected="vein")
    progress, interaction = grade(
        lesson, question_id, "the red circle", lambda reference: {"verdict": "banana"}
    )
    assert interaction.result["result"] == "ungraded"
    assert not progress.quiz_attempts[-1:] and not progress.quiz_attempts


def test_blank_answer_asks_for_clarification(lesson):
    question_id = posed(lesson)
    progress, interaction = grade(lesson, question_id, "   ")
    assert interaction.result["result"] == "ungraded"
    assert "lif" in interaction.result["diagnosis"].lower() or "clarif" in (
        interaction.result["diagnosis"].lower()
    )
    assert not progress.quiz_attempts
