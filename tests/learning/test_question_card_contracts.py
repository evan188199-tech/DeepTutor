"""Contracts for the posed mastery-question card and its graded result."""

from __future__ import annotations

from deeptutor.learning.models import LearningProgress, PendingOption, PendingQuestion, QuizAttempt
from deeptutor.learning.question_card import (
    GRADE_META_KEY,
    QUESTION_CARD_KEY,
    attempt_number,
    build_grade_result,
    build_question_card,
)


def _progress(*kp_ids: str) -> LearningProgress:
    return LearningProgress(
        book_id="b1",
        quiz_attempts=[
            QuizAttempt(
                question_id=f"q{i}",
                knowledge_point_id=kp_id,
                is_correct=True,
            )
            for i, kp_id in enumerate(kp_ids)
        ],
    )


def test_card_keys_are_stable() -> None:
    assert QUESTION_CARD_KEY == "mastery_question"
    assert GRADE_META_KEY == "mastery_grade"


def test_attempt_number_is_one_based_per_objective() -> None:
    progress = _progress("kp1", "kp2", "kp1")
    assert attempt_number(progress, "kp1") == 3
    assert attempt_number(progress, "kp2") == 2
    assert attempt_number(progress, "kp3") == 1


def test_attempt_number_ignores_blank_objective() -> None:
    progress = _progress("kp1")
    assert attempt_number(progress, "") == 1
    assert attempt_number(progress, None) == 1


def _choice_pending(**overrides) -> PendingQuestion:
    fields = {
        "question_id": "q1",
        "knowledge_point_id": "kp1",
        "prompt": "Which organelle produces ATP?",
        "question_type": "choice",
        "expected_answer": "B",
        "explanation": "Mitochondria host oxidative phosphorylation.",
        "difficulty": "hard",
        "options": [
            PendingOption(label="A", body="Ribosome"),
            PendingOption(label="B", body="Mitochondrion"),
        ],
    }
    fields.update(overrides)
    return PendingQuestion(**fields)


def test_question_card_projects_public_shape_and_withholds_answer_key() -> None:
    card = build_question_card(_choice_pending(), objective_name="Cell biology", attempt=2)

    assert card["question_id"] == "q1"
    assert card["prompt"] == "Which organelle produces ATP?"
    assert card["question_type"] == "choice"
    assert card["objective"] == {"id": "kp1", "name": "Cell biology"}
    assert card["difficulty"] == "hard"
    assert card["attempt"] == 2
    assert card["allow_free_text"] is True
    assert card["options"] == [
        {"label": "A", "body": "Ribosome"},
        {"label": "B", "body": "Mitochondrion"},
    ]
    assert "expected_answer" not in card
    assert "explanation" not in card
    assert "Mitochondrion" == card["options"][1]["body"]


def test_question_card_options_absent_for_open_questions() -> None:
    card = build_question_card(_choice_pending(question_type="short", options=[]))
    assert card["options"] == []
    assert card["allow_free_text"] is True


def test_question_card_defaults_and_attempt_floor() -> None:
    pending = _choice_pending(difficulty="")
    card = build_question_card(pending, attempt=0)

    assert card["objective"] == {"id": "kp1", "name": ""}
    assert card["difficulty"] == ""
    assert card["attempt"] == 1


def test_question_card_carries_public_visual_only() -> None:
    pending = _choice_pending(
        visual_context={
            "task": "identification",
            "sources": [{"kb_name": "kb", "asset_id": "a1"}],
            "answer_cues": "none",
            "key_status": "verified",
            "hints_used": 0,
            "pixels_inspected": True,
            "reference_quote": "server-side only",
            "reference_answer": "server-side only",
        }
    )
    card = build_question_card(pending)

    assert card["visual"] == {
        "task": "identification",
        "sources": [{"kb_name": "kb", "asset_id": "a1"}],
        "answer_cues": "none",
        "key_status": "verified",
        "hints_used": 0,
        "pixels_inspected": True,
    }
    assert "reference_quote" not in card["visual"]
    assert "reference_answer" not in card["visual"]


def test_grade_result_releases_answer_key() -> None:
    result = build_grade_result(
        question_id="q1",
        is_correct=True,
        learner_answer=" B ",
        correct_label=" B ",
        choice_options={"B": "Mitochondrion", "A": "Ribosome"},
        explanation="Oxidative phosphorylation.",
        result="correct",
        independent=True,
    )

    assert result == {
        "question_id": "q1",
        "is_correct": True,
        "learner_answer": " B ",
        "correct_label": "B",
        "correct_body": "Mitochondrion",
        "explanation": "Oxidative phosphorylation.",
        "result": "correct",
        "independent": True,
    }


def test_grade_result_omits_optional_fields() -> None:
    result = build_grade_result(
        question_id="q1",
        is_correct=False,
        learner_answer="C",
        correct_label="",
        choice_options={"B": "Mitochondrion"},
        explanation="",
    )

    assert result["correct_label"] == ""
    assert result["correct_body"] == ""
    assert result["explanation"] == ""
    assert "result" not in result
    assert "independent" not in result


def test_grade_result_unknown_label_yields_empty_body() -> None:
    result = build_grade_result(
        question_id="q1",
        is_correct=False,
        learner_answer="Z",
        correct_label="Z",
        choice_options={"B": "Mitochondrion"},
        explanation="n/a",
    )
    assert result["correct_body"] == ""
