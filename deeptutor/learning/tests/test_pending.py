"""Tests for the pending-question translation helpers in
:mod:`deeptutor.learning.pending` — the pure multiple-choice rules shared by
registration, presentation, and grading.

These protect the boundaries that regressed before:

* a maths option like ``"x - 1 = 0"`` must never read as label ``X``
  (registration required the first label to be ``A`` for that reason);
* a well-formed label set maps by label, anything malformed falls back to
  reading options positionally so no text is dropped;
* an ambiguous submission resolves to "unreadable" (``""``), never silently
  to a wrong option;
* the public projection never leaks ``expected_answer`` or the explanation.
"""

from __future__ import annotations

import pytest

from deeptutor.learning.models import PendingOption, PendingQuestion
from deeptutor.learning.pending import (
    PublicPendingQuestion,
    canonical_labels,
    has_option_bodies,
    is_readable_choice_answer,
    option_label_intent,
    parse_options,
    positional_label,
    public_pending_question,
    resolve_answer,
    resolve_choice_submission,
)


def _pending_question(**overrides) -> PendingQuestion:
    fields = {
        "question_id": "q1",
        "knowledge_point_id": "kp1",
        "prompt": "Which one?",
        "question_type": "choice",
        "expected_answer": "B",
        "explanation": "because B",
        "options": [
            PendingOption(label="A", body="Paris"),
            PendingOption(label="B", body="Berlin"),
        ],
    }
    fields.update(overrides)
    return PendingQuestion(**fields)


class TestPositionalLabels:
    def test_labels_progress_from_a_to_z_then_numbers(self):
        assert positional_label(0) == "A"
        assert positional_label(25) == "Z"
        assert positional_label(26) == "27"
        assert positional_label(27) == "28"

    def test_canonical_label_set_matches_positions(self):
        assert canonical_labels(3) == {"A", "B", "C"}
        assert canonical_labels(0) == set()


class TestOptionLabelIntent:
    def test_reads_a_prefixed_labels_in_several_separator_styles(self):
        assert option_label_intent(["A. 太阳", "B) 月亮", "C、星星"]) == ["A", "B", "C"]

    def test_reads_legacy_bare_letter_rows(self):
        assert option_label_intent(["a", "B"]) == ["A", "B"]

    def test_rejects_unlabelled_options(self):
        assert option_label_intent(["太阳", "月亮"]) is None

    def test_rejects_prefix_not_starting_at_a(self):
        # "x - 1 = 0" matches the prefix pattern but is maths, not a label.
        assert option_label_intent(["x - 1 = 0", "y - 2 = 0"]) is None
        assert option_label_intent(["B. one", "C. two"]) is None

    def test_rejects_mixed_labelled_and_unlabelled_rows(self):
        assert option_label_intent(["A. one", "two"]) is None

    def test_ignores_blank_entries_before_deciding(self):
        assert option_label_intent(["", "  ", "A. 1"]) == ["A"]


class TestParseOptions:
    def test_well_formed_labelled_options_map_by_label(self):
        assert parse_options(["A. 3", "B. 4"]) == {"A": "3", "B": "4"}

    def test_label_sequence_with_gap_falls_back_to_positional(self):
        assert parse_options(["A. 1", "C. 2"]) == {"A": "A. 1", "B": "C. 2"}

    def test_duplicated_labels_fall_back_to_positional(self):
        assert parse_options(["A. 1", "A. 2"]) == {"A": "A. 1", "B": "A. 2"}

    def test_unlabelled_options_map_positionally(self):
        assert parse_options(["1) x", "2) y"]) == {"A": "1) x", "B": "2) y"}

    def test_blank_entries_are_dropped(self):
        assert parse_options(["", " A. x ", ""]) == {"A": "x"}

    def test_empty_input_yields_empty_map(self):
        assert parse_options([]) == {}


class TestHasOptionBodies:
    def test_accepts_real_bodies(self):
        assert has_option_bodies({"A": "x", "B": "y"})
        assert has_option_bodies({"A": " x ", "B": "y"})

    def test_rejects_label_only_maps_too_small_or_mismatched(self):
        assert not has_option_bodies({})
        assert not has_option_bodies({"A": "x"})
        assert not has_option_bodies({"A": "A", "B": "B"})


class TestResolveAnswer:
    OPTIONS = {"A": "Paris", "B": "Berlin"}

    def test_resolves_label_and_labelled_body(self):
        assert resolve_answer("b", self.OPTIONS) == "B"
        assert resolve_answer("A. Paris", self.OPTIONS) == "A"

    def test_resolves_unique_exact_body_case_insensitively(self):
        assert resolve_answer("paris", self.OPTIONS) == "A"

    def test_empty_answer_resolves_to_nothing(self):
        assert resolve_answer("   ", self.OPTIONS) == ""

    def test_ambiguous_fragment_resolves_to_nothing(self):
        options = {"A": "apple pie", "B": "apple tart"}
        assert resolve_answer("apple", options) == ""

    def test_unknown_answer_resolves_to_nothing(self):
        assert resolve_answer("Madrid", self.OPTIONS) == ""


class TestResolveChoiceSubmission:
    OPTIONS = {"A": "New York City", "B": "Paris"}

    def test_resolves_bare_label_case_insensitively(self):
        assert resolve_choice_submission("b", self.OPTIONS) == "B"

    def test_resolves_labelled_body(self):
        assert resolve_choice_submission("A. New York City", self.OPTIONS) == "A"

    def test_resolves_body_with_whitespace_and_case_squeezed(self):
        assert resolve_choice_submission("new   york CITY", self.OPTIONS) == "A"

    def test_resolves_single_mention_in_composer_text(self):
        assert resolve_choice_submission("选B", self.OPTIONS) == "B"
        assert resolve_choice_submission("答案是 B", self.OPTIONS) == "B"

    def test_rejects_multiple_mentioned_labels(self):
        assert resolve_choice_submission("A or B", self.OPTIONS) == ""

    def test_rejects_label_embedded_in_a_word(self):
        # The B inside "ABC" is not a standalone mention.
        assert resolve_choice_submission("ABC", self.OPTIONS) == ""

    def test_rejects_unknown_text(self):
        assert resolve_choice_submission("Madrid", self.OPTIONS) == ""

    def test_rejects_empty_submission(self):
        assert resolve_choice_submission("  ", self.OPTIONS) == ""


class TestIsReadableChoiceAnswer:
    OPTIONS = ["A. Paris", "B. Berlin"]

    def test_accepts_committed_label_forms(self):
        assert is_readable_choice_answer("B", self.OPTIONS)
        assert is_readable_choice_answer("b。", self.OPTIONS)
        assert is_readable_choice_answer("B!", self.OPTIONS)
        assert is_readable_choice_answer("答案是 B", self.OPTIONS)
        assert is_readable_choice_answer("我选B", self.OPTIONS)
        assert is_readable_choice_answer("I think it's B", self.OPTIONS)

    def test_accepts_labelled_body_and_exact_body(self):
        assert is_readable_choice_answer("B. Berlin", self.OPTIONS)
        assert is_readable_choice_answer("berlin", self.OPTIONS)

    def test_rejects_question_wording_even_when_one_label_is_named(self):
        assert not is_readable_choice_answer("why is B wrong?", self.OPTIONS)
        assert not is_readable_choice_answer("B 是什么意思?", self.OPTIONS)

    def test_rejects_multiple_labels(self):
        assert not is_readable_choice_answer("A or B", self.OPTIONS)

    def test_rejects_unmappable_text(self):
        assert not is_readable_choice_answer("Madrid", self.OPTIONS)
        assert not is_readable_choice_answer("   ", self.OPTIONS)

    def test_rejects_empty_option_set(self):
        assert not is_readable_choice_answer("A", [])


class TestPublicPendingQuestion:
    def test_choice_projection_keeps_options_and_hides_the_answer(self):
        pending = _pending_question(
            expected_answer="Berlin",
            explanation="the capital of Germany",
            options=[
                PendingOption(label="A", body="Paris"),
                PendingOption(label="B", body="Berlin"),
            ],
        )
        public = public_pending_question(pending)

        assert public.question_id == "q1"
        assert public.question_type == "choice"
        assert [option.label for option in public.options] == ["A", "B"]
        assert all(option.id == option.label for option in public.options)
        as_dict = public.to_dict()
        assert as_dict["options"] == [
            {"id": "A", "label": "A", "body": "Paris"},
            {"id": "B", "label": "B", "body": "Berlin"},
        ]
        assert "expected_answer" not in as_dict
        assert "explanation" not in as_dict
        assert "the capital of Germany" not in str(as_dict)

    def test_expected_answer_never_appears_in_any_projection(self):
        pending = _pending_question(
            expected_answer="Berlin",
            explanation="the capital of Germany",
            options=[
                PendingOption(label="A", body="Paris"),
                PendingOption(label="B", body="Berlin"),
            ],
        )
        public = public_pending_question(pending)

        assert "expected_answer" not in PublicPendingQuestion.__dataclass_fields__
        assert not hasattr(public, "expected_answer")
        assert not hasattr(public, "explanation")

    def test_non_choice_projection_drops_options(self):
        pending = _pending_question(
            question_type="short",
            options=[PendingOption(label="A", body="Paris")],
        )
        public = public_pending_question(pending)

        assert public.options == ()
        assert public.to_dict()["options"] == []

    def test_prompts_with_escaped_unicode_runs_are_decoded(self):
        pending = _pending_question(prompt="\\u4f60\\u597d\\u554a")
        assert public_pending_question(pending).prompt == "你好啊"

    def test_plain_prompt_passes_through_untouched(self):
        pending = _pending_question(prompt="Which one? B?")
        assert public_pending_question(pending).prompt == "Which one? B?"

    def test_projection_is_immutable(self):
        public = public_pending_question(_pending_question())
        with pytest.raises(AttributeError):
            public.prompt = "tampered"  # type: ignore[misc]
