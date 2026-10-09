"""Branch-gap pins for the choice-question data contract.

``deeptutor/learning/tests/test_mastery_choices.py`` already covers the four
boundaries of :mod:`deeptutor.capabilities.mastery.choices` end to end. These
tests pin only the shapes and matching rules that file leaves open: mixed
payloads, blank-keyed maps, case-insensitive labels, prompt-prefix recovery
matching, and the agreement between the registration grader and the card
grader.
"""

from __future__ import annotations

import pytest

from deeptutor.capabilities.mastery.choices import (
    has_option_bodies,
    parse_options,
    read_option_objects,
    recover_options_from_turn,
    resolve_answer,
    resolve_choice_submission,
    split_label_and_body,
)

_OPTIONS = {"A": "alpha", "B": "beta", "C": "gamma"}


# ── registration: mixed and blank-edged payloads ────────────────────────────


def test_a_mixed_string_and_object_list_reads_through_the_object_path():
    """One object among the strings switches the whole list to the object path."""
    options, unreadable = read_option_objects(["A: first", {"label": "B", "body": "second"}])

    assert options == [{"label": "A", "body": "first"}, {"label": "B", "body": "second"}]
    assert unreadable == []


def test_a_mapping_with_a_blank_value_defers_to_the_legacy_path():
    assert read_option_objects({"A": "first", "B": "   "}) is None


def test_a_mapping_with_a_blank_key_defers_to_the_legacy_path():
    assert read_option_objects({"": "first"}) is None


def test_a_body_that_merely_restates_its_label_case_insensitively_is_not_a_body():
    assert has_option_bodies({"A": "a", "B": "b"}) is False
    assert has_option_bodies({"A": "A ", "B": "B"}) is False


def test_lowercased_and_dotted_prefix_forms_split_to_uppercase_labels():
    assert split_label_and_body("c) third") == ("C", "third")
    assert split_label_and_body("A. first") == ("A", "first")


def test_a_skipped_label_falls_back_positionally_keeping_every_row_whole():
    assert parse_options(["A. first", "C. third"]) == {"A": "A. first", "B": "C. third"}


# ── grading and card answering agree on one label ───────────────────────────


def test_lowercase_labels_resolve_on_the_registration_path():
    assert resolve_answer("b", _OPTIONS) == "B"


def test_both_graders_agree_on_the_same_submissions():
    """Label, labelled body, and exact body land on one label from either path."""
    for submission, expected in [("A", "A"), ("B: beta", "B"), ("gamma", "C")]:
        assert resolve_answer(submission, _OPTIONS) == expected
        assert resolve_choice_submission(submission, _OPTIONS) == expected


# ── legacy recovery: tolerant prompt matching, most recent card wins ────────


class _FakeStore:
    def __init__(self, events):
        self._events = events

    async def get_turn_events(self, turn_id, after_seq=0):
        return self._events


def _ask_user_event(prompt, labels=("A", "B"), bodies=("first choice", "second choice")):
    return {
        "type": "tool_call",
        "metadata": {
            "tool_name": "ask_user",
            "args": {
                "questions": [
                    {
                        "prompt": prompt,
                        "options": [
                            {"label": label, "description": body}
                            for label, body in zip(labels, bodies)
                        ],
                    }
                ]
            },
        },
    }


@pytest.mark.asyncio
async def test_recovery_matches_a_question_that_extends_the_card_prompt():
    store = _FakeStore([_ask_user_event("Where is the stop condition added?")])

    recovered = await recover_options_from_turn(
        store, "turn_1", "Where is the stop condition added? (chapter 3)"
    )

    assert recovered == {"A": "first choice", "B": "second choice"}


@pytest.mark.asyncio
async def test_recovery_matches_a_card_prompt_that_extends_the_question():
    store = _FakeStore([_ask_user_event("Where is the stop condition added? Step by step.")])

    assert await recover_options_from_turn(store, "turn_1", "Where is the stop condition added?") == {
        "A": "first choice",
        "B": "second choice",
    }


@pytest.mark.asyncio
async def test_recovery_takes_the_most_recent_matching_card():
    store = _FakeStore(
        [
            _ask_user_event("Where is the stop condition added?", bodies=("old first", "old second")),
            _ask_user_event("Where is the stop condition added?"),
        ]
    )

    recovered = await recover_options_from_turn(store, "turn_1", "Where is the stop condition added?")

    assert recovered == {"A": "first choice", "B": "second choice"}
