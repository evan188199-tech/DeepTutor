"""The mastery question card: what the learner sees and what the gate rules.

``question_card`` is the seam between the persisted question and both
learner-facing surfaces: the card posed before the answer (which must never
carry the answer key) and the graded result (which releases it). These tests
pin the round-trip through JSON, the field defaults on sparsely posed
questions, and the degraded — never raised — behaviour on blank input.
"""

from __future__ import annotations

import json

from deeptutor.learning.models import LearningProgress, PendingOption, PendingQuestion, QuizAttempt
from deeptutor.learning.question_card import (
    GRADE_META_KEY,
    QUESTION_CARD_KEY,
    attempt_number,
    build_grade_result,
    build_question_card,
)


def _choice_pending(**overrides) -> PendingQuestion:
    fields: dict = {
        "question_id": "q-1",
        "knowledge_point_id": "kp-1",
        "prompt": "Which layer routes packets?",
        "question_type": "choice",
        "expected_answer": "B",
        "options": [
            {"label": "A", "body": "Physical"},
            {"label": "B", "body": "Network"},
        ],
        "explanation": "The network layer routes packets between hosts.",
        "difficulty": "medium",
    }
    fields.update(overrides)
    return PendingQuestion(**fields)


def test_constants_keep_their_channel_keys() -> None:
    """The posed card and the grade travel under their own metadata keys."""
    assert QUESTION_CARD_KEY == "mastery_question"
    assert GRADE_META_KEY == "mastery_grade"


def test_question_card_json_roundtrip_and_withheld_answer_key() -> None:
    """The posed card survives a JSON round-trip and never carries the key."""
    card = build_question_card(
        _choice_pending(),
        objective_name="Computer networks",
        attempt=2,
    )
    restored = json.loads(json.dumps(card))
    assert restored == card
    assert set(card) == {
        "question_id",
        "prompt",
        "question_type",
        "objective",
        "difficulty",
        "attempt",
        "options",
        "allow_free_text",
    }
    assert card["question_id"] == "q-1"
    assert card["objective"] == {"id": "kp-1", "name": "Computer networks"}
    assert card["options"] == [
        {"label": "A", "body": "Physical"},
        {"label": "B", "body": "Network"},
    ]
    assert card["allow_free_text"] is True
    assert "expected_answer" not in card
    assert "explanation" not in card


def test_question_card_defaults_on_sparsely_posed_question() -> None:
    """A question posed with only ids degrades to empty presentation fields."""
    card = build_question_card(PendingQuestion(question_id="q-2", knowledge_point_id="kp-9"))
    assert card["prompt"] == ""
    assert card["question_type"] == "short"
    assert card["objective"] == {"id": "kp-9", "name": ""}
    assert card["difficulty"] == ""
    assert card["attempt"] == 1
    assert card["options"] == []
    assert card["allow_free_text"] is True


def test_question_card_attempt_is_clamped_to_one() -> None:
    """A bad attempt hint can never show the learner attempt 0 or negative."""
    assert build_question_card(_choice_pending(), attempt=0)["attempt"] == 1
    assert build_question_card(_choice_pending(), attempt=-3)["attempt"] == 1
    assert build_question_card(_choice_pending(), attempt=5)["attempt"] == 5


def test_question_card_decodes_escaped_unicode_prompt() -> None:
    """A double-encoded prompt is decoded for display, not shown raw (#973)."""
    pending = _choice_pending(prompt="\\u4f60\\u597d\\u4e16\\u754c")
    assert build_question_card(pending)["prompt"] == "你好世界"
    plain = _choice_pending(prompt="Which layer routes packets?")
    assert build_question_card(plain)["prompt"] == "Which layer routes packets?"


def test_attempt_number_counts_committed_attempts_per_objective() -> None:
    """Committed attempts on this objective count; poses and other ids do not."""
    progress = LearningProgress(
        book_id="b1",
        quiz_attempts=[
            QuizAttempt(question_id="q-1", knowledge_point_id="kp-1", is_correct=True),
            QuizAttempt(question_id="q-1", knowledge_point_id="kp-1", is_correct=False),
            QuizAttempt(question_id="q-2", knowledge_point_id="kp-2", is_correct=True),
        ],
        pending_question=_choice_pending(),
    )
    assert attempt_number(progress, "kp-1") == 3
    assert attempt_number(progress, "kp-2") == 2
    assert attempt_number(progress, "kp-unseen") == 1


def test_attempt_number_degrades_on_blank_objective_id() -> None:
    """A blank objective id asks for the first attempt instead of raising."""
    progress = LearningProgress(
        book_id="b1",
        quiz_attempts=[QuizAttempt(question_id="q-1", knowledge_point_id="kp-1", is_correct=True)],
    )
    assert attempt_number(progress, "") == 1
    assert attempt_number(progress, None) == 1


def test_grade_result_releases_answer_key_and_resolves_body() -> None:
    """Once graded, the label is stripped and its body is resolved."""
    result = build_grade_result(
        question_id="q-1",
        is_correct=True,
        learner_answer="B",
        correct_label=" B ",
        choice_options={"A": "Physical", "B": "Network"},
        explanation="Routing happens at layer 3.",
    )
    restored = json.loads(json.dumps(result))
    assert restored == result
    assert result["correct_label"] == "B"
    assert result["correct_body"] == "Network"
    assert result["explanation"] == "Routing happens at layer 3."


def test_grade_result_degrades_on_blank_and_malformed_input() -> None:
    """Blank or ``None`` fields degrade to empty strings instead of raising."""
    result = build_grade_result(
        question_id=None,
        is_correct=None,
        learner_answer=None,
        correct_label=None,
        choice_options={},
        explanation=None,
    )
    assert result == {
        "question_id": "",
        "is_correct": False,
        "learner_answer": "",
        "correct_label": "",
        "correct_body": "",
        "explanation": "",
    }


def test_grade_result_unknown_label_yields_empty_body() -> None:
    """A label missing from the choice map shows no body rather than failing."""
    result = build_grade_result(
        question_id="q-1",
        is_correct=False,
        learner_answer="C",
        correct_label="C",
        choice_options={"A": "Physical", "B": "Network"},
        explanation="",
    )
    assert result["correct_label"] == "C"
    assert result["correct_body"] == ""


def test_choice_options_normalize_legacy_string_rows() -> None:
    """Legacy ``["A: body"]`` rows posed before the split still build a card."""
    card = build_question_card(_choice_pending(options=["A: Physical", "B: Network"]))
    assert card["options"] == [
        {"label": "A", "body": "Physical"},
        {"label": "B", "body": "Network"},
    ]
