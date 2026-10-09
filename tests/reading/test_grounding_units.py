from __future__ import annotations

import json

import pytest

from deeptutor.reading._grounding import (
    MAX_GROUNDING_CONTEXT_CHARS,
    evidence_key,
    grounded_prompt,
    grounding_context,
    normalized_with_map,
    selection_range,
)
from deeptutor.reading.extensions import ReadingContext


class TestNormalizedWithMap:
    def test_every_output_character_maps_to_a_source_index(self) -> None:
        normalized, positions = normalized_with_map("ab  cd")

        assert normalized == "ab cd"
        assert positions == [0, 1, 2, 4, 5]
        source = "ab  cd"
        assert "".join(source[p] for p in positions) == normalized

    def test_whitespace_free_string_is_an_identity_map(self) -> None:
        value = "DeepTutor"

        normalized, positions = normalized_with_map(value)

        assert normalized == value
        assert positions == list(range(len(value)))

    def test_leading_whitespace_is_dropped(self) -> None:
        normalized, positions = normalized_with_map("\n\t  kept")

        assert normalized == "kept"
        assert positions == [4, 5, 6, 7]

    def test_trailing_whitespace_is_dropped(self) -> None:
        normalized, positions = normalized_with_map("kept  \n")

        assert normalized == "kept"
        assert positions == [0, 1, 2, 3]

    def test_whitespace_only_value_normalizes_to_empty(self) -> None:
        assert normalized_with_map("   \t\n ") == ("", [])
        assert normalized_with_map("") == ("", [])

    def test_mixed_whitespace_runs_collapse_to_one_space(self) -> None:
        normalized, positions = normalized_with_map("a \t\n b")

        assert normalized == "a b"
        assert positions == [0, 1, 5]

    def test_unicode_whitespace_collapses_like_ascii(self) -> None:
        normalized, positions = normalized_with_map("a\xa0\xa0b")

        assert normalized == "a b"
        assert positions == [0, 1, 3]


class TestSelectionRange:
    def test_empty_selection_returns_none(self) -> None:
        assert selection_range("any text", "") is None

    def test_whitespace_only_selection_returns_none(self) -> None:
        assert selection_range("no runs here", "   ") is None

    def test_exact_match_returns_source_bounds(self) -> None:
        text = "head verified tail"

        assert selection_range(text, "verified") == (5, 13)
        assert text[5:13] == "verified"

    def test_exact_match_takes_the_first_occurrence(self) -> None:
        text = "aa b aa b"

        assert selection_range(text, "aa b") == (0, 4)

    def test_exact_match_spanning_the_whole_text(self) -> None:
        text = "exact whole"

        assert selection_range(text, text) == (0, len(text))

    def test_collapsed_whitespace_selection_maps_back_to_source(self) -> None:
        text = "head\n\tverified   phrase\ntail"

        bounds = selection_range(text, "verified phrase")

        assert bounds is not None
        assert text[bounds[0] : bounds[1]] == "verified   phrase"

    def test_collapsed_selection_touching_the_text_end(self) -> None:
        text = "start verified  phrase"

        bounds = selection_range(text, "verified phrase")

        assert bounds is not None
        assert bounds[1] == len(text)
        assert text[bounds[0] :] == "verified  phrase"

    def test_absent_selection_returns_none_after_normalization(self) -> None:
        assert selection_range("nothing matches this", "missing phrase") is None

    def test_selection_longer_than_text_returns_none(self) -> None:
        assert selection_range("short", "a much longer selection than the text") is None

    def test_tab_and_newline_only_selection_degrades_to_none(self) -> None:
        assert selection_range("plain text", "\t\n ") is None


class TestEvidenceKey:
    def test_drops_number_only_margin_lines(self) -> None:
        assert evidence_key("fall short in\n3\ndelivering") == "fallshortindelivering"

    def test_rejoins_words_broken_by_hyphen_and_line_number(self) -> None:
        assert evidence_key("DeepTu-\n4\ntor") == "deeptutor"

    def test_comparison_is_case_insensitive(self) -> None:
        assert evidence_key("DeepTutor") == evidence_key("deeptutor")
        assert evidence_key("MiXeD CaSe") == "mixedcase"

    def test_unicode_hyphen_variants_are_dropped(self) -> None:
        assert evidence_key("co\u00adop") == "coop"
        assert evidence_key("co\u2010op\u2011op") == "coopop"

    def test_line_number_with_surrounding_blank_characters_is_dropped(self) -> None:
        assert evidence_key("before\n  12  \nafter") == "beforeafter"

    def test_numbers_inside_a_line_are_kept(self) -> None:
        assert evidence_key("line 3 stays") == "line3stays"

    def test_five_digit_line_is_not_treated_as_a_margin_number(self) -> None:
        assert evidence_key("a\n12345\nb") == "a12345b"

    def test_empty_value_has_empty_key(self) -> None:
        assert evidence_key("") == ""


class TestGroundingContext:
    def test_non_positive_max_chars_degrades_to_empty(self) -> None:
        text = "some text"

        assert grounding_context(text, "some", max_chars=0) == ""
        assert grounding_context(text, "some", max_chars=-5) == ""

    def test_empty_selection_returns_truncated_prefix(self) -> None:
        text = "A" * 50

        assert grounding_context(text, "", max_chars=10) == "A" * 10

    def test_absent_selection_returns_truncated_prefix(self) -> None:
        text = "abcde" * 10

        assert grounding_context(text, "not present", max_chars=7) == "abcdeab"

    def test_short_text_is_returned_in_full(self) -> None:
        text = "tiny page"

        assert grounding_context(text, "tiny", max_chars=MAX_GROUNDING_CONTEXT_CHARS) == text

    def test_window_is_exactly_max_chars_and_keeps_the_selection(self) -> None:
        text = "A" * 100 + "NEEDLE" + "B" * 100

        window = grounding_context(text, "NEEDLE", max_chars=20)

        assert len(window) == 20
        assert "NEEDLE" in window
        assert window == text[93:113]

    def test_selection_near_the_start_clamps_to_the_prefix(self) -> None:
        text = "HEAD" + "x" * 100

        window = grounding_context(text, "HEAD", max_chars=10)

        assert window == text[:10]

    def test_selection_near_the_end_clamps_to_the_suffix(self) -> None:
        text = "x" * 100 + "TAIL"

        window = grounding_context(text, "TAIL", max_chars=10)

        assert window == text[-10:]
        assert window.endswith("TAIL")

    def test_empty_text_degrades_to_empty_window(self) -> None:
        assert grounding_context("", "", max_chars=100) == ""
        assert grounding_context("", "needle", max_chars=100) == ""


class TestGroundedPrompt:
    def test_payload_carries_selection_and_bounded_context(self) -> None:
        visible = "A" * 3_000 + "verified   phrase" + "B" * 3_000
        context = ReadingContext(
            material_id="m-1",
            locator=1,
            selection="verified phrase",
            visible_text=visible,
        )

        payload = json.loads(grounded_prompt(context))

        assert payload["selection"] == "verified phrase"
        assert len(payload["surrounding_context"]) == MAX_GROUNDING_CONTEXT_CHARS
        assert "verified   phrase" in payload["surrounding_context"]

    def test_short_page_is_passed_through_in_full(self) -> None:
        context = ReadingContext(
            material_id="m-1",
            locator=1,
            selection="kept",
            visible_text="short page with kept selection",
        )

        payload = json.loads(grounded_prompt(context))

        assert payload["surrounding_context"] == "short page with kept selection"

    def test_non_ascii_selection_survives_without_escaping(self) -> None:
        context = ReadingContext(
            material_id="m-2",
            locator=2,
            selection="重要段落",
            visible_text="前文 重要段落 后文",
        )

        raw = grounded_prompt(context)

        assert "重要段落" in raw
        assert json.loads(raw)["surrounding_context"] == "前文 重要段落 后文"

    def test_absent_selection_keeps_the_truncated_page(self) -> None:
        context = ReadingContext(
            material_id="m-3",
            locator=3,
            selection="never present",
            visible_text="p" * 40,
        )

        payload = json.loads(grounded_prompt(context))

        assert payload["selection"] == "never present"
        assert payload["surrounding_context"] == "p" * 40


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", ("", [])),
        ("x", ("x", [0])),
    ],
)
def test_normalized_with_map_boundaries(value: str, expected: tuple[str, list[int]]) -> None:
    assert normalized_with_map(value) == expected
