"""Table-driven tests for the conservative objective grader in practice answers."""

from __future__ import annotations

import pytest

from deeptutor.services.practice.answers import check_answer

CHOICES = {
    "A": "Photosynthesis",
    "B": "Respiration",
    "C": "Chlorophyll",
    "D": "Mitosis",
}


def _entry(
    kind: str = "single_choice",
    options: dict[str, str] | None = CHOICES,
    options_json: str | None = None,
    correct: str = "A",
) -> dict:
    item: dict = {"question_type": kind, "correct_answer": correct}
    if options is not None:
        item["options"] = options
    if options_json is not None:
        item["options_json"] = options_json
    return item


GRADES = [
    # --- single choice: key equivalence ---
    pytest.param({}, "A", True, id="single-exact-key"),
    pytest.param({}, "a", True, id="single-key-case-insensitive"),
    pytest.param({}, "  a  ", True, id="single-key-padded"),
    pytest.param({"correct": " a "}, "A", True, id="single-correct-key-padded"),
    # --- single choice: full option text forms ---
    pytest.param({}, "Photosynthesis", True, id="single-bare-text"),
    pytest.param({}, "A. Photosynthesis", True, id="single-key-dot-text"),
    pytest.param({}, "a) photosynthesis", True, id="single-key-paren-text-lower"),
    pytest.param({}, "A.  Photosynthesis ", True, id="single-text-whitespace-folded"),
    pytest.param({"correct": "A. Photosynthesis"}, "A", True, id="single-correct-given-as-text"),
    # --- single choice: mismatches ---
    pytest.param({"correct": "A"}, "B", False, id="single-wrong-key"),
    pytest.param({"correct": "A"}, "Photosynthes", False, id="single-text-prefix-no-match"),
    pytest.param({"correct": "A"}, "photosynthesis, A", False, id="single-combined-forms-mismatch"),
    pytest.param({"correct": "A"}, "", False, id="single-empty-answer-is-wrong"),
    pytest.param({"correct": "A"}, "   ", False, id="single-blank-answer-is-wrong"),
    # --- generic (unknown) kind grades by equality; numeric option text exact only ---
    pytest.param(
        {"kind": "", "options": {"A": "42", "B": "43"}, "correct": "A"},
        "42",
        True,
        id="numeric-text-exact-match",
    ),
    pytest.param(
        {"kind": "", "options": {"A": "42", "B": "43"}, "correct": "A"},
        " 42 ",
        True,
        id="numeric-text-padded-match",
    ),
    pytest.param(
        {"kind": "", "options": {"A": "42", "B": "43"}, "correct": "A"},
        "42.0",
        False,
        id="numeric-text-no-normalization",
    ),
    pytest.param(
        {"kind": "true_false", "options": {"A": "True", "B": "False"}, "correct": "A"},
        "B",
        False,
        id="true-false-wrong-key",
    ),
    # --- multi choice: separated keys ---
    pytest.param({"kind": "multi_choice", "correct": "A,C"}, "A,C", True, id="multi-comma-match"),
    pytest.param({"kind": "multi_choice", "correct": "A,C"}, "C, A", True, id="multi-order-insensitive"),
    pytest.param({"kind": "multi_choice", "correct": "A,C"}, "A；C", True, id="multi-fullwidth-semicolon"),
    pytest.param({"kind": "multi_choice", "correct": "A,C"}, "A C", True, id="multi-space-separated"),
    pytest.param({"kind": "multi_choice", "correct": "A,C"}, "a,c", True, id="multi-lowercase-keys"),
    # --- multi choice: concatenated letters ---
    pytest.param({"kind": "multi_choice", "correct": "A,C"}, "AC", True, id="multi-concatenated"),
    pytest.param({"kind": "multi_choice", "correct": "A,C"}, "ca", True, id="multi-concatenated-lower"),
    pytest.param(
        {"kind": "multiple_select", "correct": "B,D"}, "BD", True, id="multi-select-alias-concatenated"
    ),
    pytest.param({"kind": "multi_choice", "correct": "AC"}, "A,C", True, id="multi-legacy-concat-correct"),
    # --- multi choice: partial / extra / invalid selections ---
    pytest.param({"kind": "multi_choice", "correct": "A,C"}, "A", False, id="multi-partial-is-wrong"),
    pytest.param({"kind": "multi_choice", "correct": "A,C"}, "A,B,C", False, id="multi-extra-is-wrong"),
    pytest.param({"kind": "multi_choice", "correct": "A,C"}, "XYZ", False, id="multi-unknown-letters-wrong"),
    pytest.param({"kind": "multi_choice", "correct": "A,C"}, "", False, id="multi-empty-is-wrong"),
    # --- options supplied via options_json only ---
    pytest.param(
        {"options": None, "options_json": '{"A": "Tokyo", "B": "Osaka"}', "correct": "A"},
        "Tokyo",
        True,
        id="options-from-json-text-match",
    ),
    pytest.param(
        {"options": None, "options_json": '{"A": "Tokyo", "B": "Osaka"}', "correct": "A"},
        "Osaka",
        False,
        id="options-from-json-wrong",
    ),
    # --- inline options dict wins over options_json ---
    pytest.param(
        {
            "options": {"A": "Tokyo", "B": "Osaka"},
            "options_json": '{"A": "Ignored", "B": "Also ignored"}',
            "correct": "A",
        },
        "A. Tokyo",
        True,
        id="inline-options-take-precedence",
    ),
]

NONE_CASES = [
    pytest.param({"options": None}, "A", id="none-no-options"),
    pytest.param({"options": {}}, "A", id="none-empty-options-dict"),
    pytest.param({"options": None, "options_json": "{}"}, "A", id="none-empty-options-json"),
    pytest.param({"options": None, "options_json": ""}, "A", id="none-blank-options-json"),
    pytest.param({"correct": ""}, "A", id="none-empty-correct"),
    pytest.param({"correct": "   "}, "A", id="none-blank-correct"),
    pytest.param({"kind": "qualitative"}, "A", id="none-kind-qualitative"),
    pytest.param({"kind": "short_answer"}, "A", id="none-kind-short-answer"),
    pytest.param({"kind": "essay"}, "A", id="none-kind-essay"),
    pytest.param({"kind": "free_response"}, "A", id="none-kind-free-response"),
    pytest.param({"correct": "Z"}, "A", id="none-correct-key-outside-options"),
    pytest.param({"correct": "42"}, "42", id="none-correct-not-an-option-key"),
    pytest.param({"kind": "multi_choice", "correct": "AZ"}, "A", id="none-multi-correct-partially-invalid"),
]


@pytest.mark.parametrize(
    ("overrides", "answer", "expected"),
    GRADES,
    ids=[case.id for case in GRADES],
)
def test_check_answer_grades(overrides: dict, answer: str, expected: bool) -> None:
    assert check_answer(_entry(**overrides), answer) is expected


@pytest.mark.parametrize(
    ("overrides", "answer"),
    NONE_CASES,
    ids=[case.id for case in NONE_CASES],
)
def test_check_answer_defers_to_self_assessment(overrides: dict, answer: str) -> None:
    assert check_answer(_entry(**overrides), answer) is None
