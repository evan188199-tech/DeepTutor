"""Validation, boundary, and exception-path tests for ``learning.grading``.

Complements ``test_grading.py``: this module pins the input-validation contract
(non-string inputs fail fast), the exact boundaries of the short-answer fuzzy
threshold and 30-character length gate, the open-answer 60% keyword-coverage
threshold, and the choice-type normalization scope.
"""

import pytest

from deeptutor.learning.grading import classify_error, grade_answer
from deeptutor.learning.models import ErrorType


class TestNonStringInputs:
    """No runtime type coercion: a non-string answer fails fast on ``str.strip``."""

    @pytest.mark.parametrize("user_answer", [None, 123, 3.14, ["a"]])
    def test_non_string_user_answer_raises(self, user_answer):
        with pytest.raises(AttributeError):
            grade_answer(user_answer, "expected", "short")

    @pytest.mark.parametrize("expected_answer", [None, 123, 3.14, ["a"]])
    def test_non_string_expected_answer_raises(self, expected_answer):
        with pytest.raises(AttributeError):
            grade_answer("answer", expected_answer, "short")

    @pytest.mark.parametrize("user_answer", [None, 123, ["a"]])
    def test_classify_error_non_string_raises(self, user_answer):
        with pytest.raises(AttributeError):
            classify_error(user_answer)


class TestDefaultQuestionType:
    def test_default_type_behaves_as_short(self):
        assert grade_answer("photosynthesi", "photosynthesis") is True
        assert grade_answer("completely different", "photosynthesis") is False

    def test_non_string_question_type_falls_through_to_false(self):
        assert grade_answer("a", "a", None) is False
        assert grade_answer("a", "a", 123) is False


class TestChoiceNormalization:
    def test_internal_spaces_removed_on_both_sides(self):
        assert grade_answer("A B", "AB", "choice") is True
        assert grade_answer("A  B", "A B", "choice") is True

    def test_case_and_whitespace_combined(self):
        assert grade_answer("  ab ", "AB", "choice") is True

    def test_only_spaces_removed_not_punctuation(self):
        assert grade_answer("A,B", "AB", "choice") is False

    def test_tabs_are_not_removed(self):
        assert grade_answer("A\tB", "AB", "choice") is False

    def test_non_ascii_answer(self):
        assert grade_answer("答案 a", "答案A", "choice") is True


class TestShortFuzzyBoundaries:
    """Short answers: exact match after normalization, else similarity
    ``>= 0.85`` only while the expected answer has at most 30 characters."""

    def test_just_below_threshold_fails(self):
        # "gravy" vs "gravity": ratio ~0.833
        assert grade_answer("gravy", "gravity", "short") is False

    def test_just_above_threshold_passes(self):
        # "gravty" vs "gravity": ratio ~0.923
        assert grade_answer("gravty", "gravity", "short") is True

    def test_deletion_of_last_char_passes(self):
        # "abcd" vs "abcde": ratio ~0.889
        assert grade_answer("abcd", "abcde", "short") is True

    def test_fuzzy_applies_at_exactly_30_chars(self):
        # ratio 58/60 ~0.967
        assert grade_answer("x" * 29 + "y", "x" * 30, "short") is True

    def test_fuzzy_disabled_from_31_chars(self):
        assert grade_answer("x" * 30 + "y", "x" * 31, "short") is False

    def test_exact_match_still_wins_above_30_chars(self):
        assert grade_answer("y" * 31, "y" * 31, "short") is True

    def test_normalization_applies_before_compare(self):
        assert grade_answer("  GRAVITY ", "gravity", "short") is True
        assert grade_answer("  " + "y" * 31 + " ", "y" * 31, "short") is True


class TestOpenKeywordThreshold:
    """Open answers: keyword coverage must reach exactly 60%."""

    def test_exactly_sixty_percent_passes(self):
        expected = "alpha, beta, gamma, delta, epsilon"
        user = "alpha and beta plus gamma, nothing else"
        assert grade_answer(user, expected, "open") is True

    def test_below_sixty_percent_fails(self):
        expected = "alpha, beta, gamma, delta, epsilon"
        user = "alpha and beta only"
        assert grade_answer(user, expected, "open") is False

    def test_two_of_three_passes(self):
        assert grade_answer("alpha beta", "alpha, beta, gamma", "open") is True

    def test_one_of_three_fails(self):
        assert grade_answer("alpha", "alpha, beta, gamma", "open") is False

    def test_one_of_two_fails(self):
        assert grade_answer("alpha", "alpha, beta", "open") is False

    def test_both_of_two_passes(self):
        assert grade_answer("beta then alpha", "alpha, beta", "open") is True

    def test_keyword_order_irrelevant(self):
        assert grade_answer("gamma beta alpha", "alpha, beta, gamma", "open") is True

    def test_case_insensitive_keyword_match(self):
        assert grade_answer("The NUCLEUS is big", "Nucleus", "open") is True

    def test_separator_only_expected_has_no_keywords(self):
        for expected in (",,;", "；。", "\n", " , ; "):
            assert grade_answer("anything", expected, "open") is False

    def test_keyword_substring_of_another_counts_separately(self):
        assert grade_answer("cell membrane", "cell, cell membrane", "open") is True

    def test_duplicate_keywords_match_together(self):
        assert grade_answer("cell", "cell, cell", "open") is True
        assert grade_answer("nothing", "cell, cell", "open") is False


class TestClassifyErrorBoundaries:
    def test_unicode_whitespace_only_is_metacognitive(self):
        assert classify_error("\u3000\n\t") is ErrorType.METACOGNITIVE

    def test_punctuation_only_answer_is_application_error(self):
        assert classify_error("???") is ErrorType.APPLICATION_ERROR
