"""The Overview page is built without an LLM, so its copy is ours to get right.

Every other block's wording comes from the model in the book's language. This
one page is rendered deterministically, so its strings used to be
`"中文" if language == "zh" else "English"` conditionals in engine.py — which is
why the language picker could offer eleven languages while the book's own front
page spoke two.

These tests pin the table's shape and keep the remaining gap countable rather
than implicit.
"""

from __future__ import annotations

import pytest

from deeptutor.book.overview_copy import (
    _COPY,
    REQUIRED_KEYS,
    missing_languages,
    overview_copy,
)

# What the creator's picker offers (BookCreator.BOOK_LANGUAGES).
PICKER_LANGUAGES = [
    "en",
    "zh",
    "zh-tw",
    "ja",
    "ko",
    "es",
    "fr",
    "de",
    "ru",
    "pt",
    "it",
]


@pytest.mark.parametrize("language", sorted(_COPY))
def test_every_entry_defines_every_key(language: str) -> None:
    """A partial translation would render a stray English string mid-page."""
    missing = REQUIRED_KEYS - set(_COPY[language])
    assert not missing, f"{language} is missing {missing}"


@pytest.mark.parametrize("language", sorted(_COPY))
def test_the_intro_body_interpolates(language: str) -> None:
    body = _COPY[language]["intro_body"].format(concepts=7, chapters=3)
    assert "7" in body and "3" in body
    assert "{" not in body


@pytest.mark.parametrize("language", sorted(_COPY))
def test_objectives_are_a_non_empty_list_of_strings(language: str) -> None:
    objectives = _COPY[language]["objectives"]
    assert isinstance(objectives, list) and objectives
    assert all(isinstance(o, str) and o.strip() for o in objectives)


def test_a_regional_tag_resolves_to_its_base_language() -> None:
    assert overview_copy("zh-tw") is _COPY["zh"]
    assert overview_copy("zh-CN") is _COPY["zh"]


def test_an_unknown_language_falls_back_to_english_rather_than_breaking() -> None:
    for unknown in ("ja", "kl", "", None, "   "):
        assert overview_copy(unknown) is _COPY["en"]


def test_the_translation_gap_is_reported_honestly() -> None:
    """Not a failure — a ledger. Adding a language is one entry in _COPY."""
    gap = missing_languages(PICKER_LANGUAGES)
    covered = len(PICKER_LANGUAGES) - len(gap)
    assert covered >= 3, "en, zh and zh-tw (via fallback) must be covered"
    # If this trips, someone translated more languages — update the number,
    # and be glad.
    assert set(gap) <= {"ja", "ko", "es", "fr", "de", "ru", "pt", "it"}


def test_english_is_always_present_because_it_is_the_fallback() -> None:
    assert "en" in _COPY
    assert REQUIRED_KEYS <= set(_COPY["en"])


# --- Degenerate and oversized inputs resolve instead of raising -------------


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("ZH", "zh"),
        ("  zh  ", "zh"),
        ("ZH-TW", "zh"),
        ("zh-TW-Hant", "zh"),
        ("EN-gb", "en"),
    ],
)
def test_case_and_whitespace_are_normalized_before_lookup(tag: str, expected: str) -> None:
    assert overview_copy(tag) is _COPY[expected]


def test_an_oversized_language_tag_still_falls_back_without_raising() -> None:
    oversized = "z" * 10_000
    assert overview_copy(oversized) is _COPY["en"]


def test_regional_fallback_is_one_level_deep() -> None:
    """A three-part tag keeps only its base; anything past that falls to English."""
    assert overview_copy("zz-qq") is _COPY["en"]
    assert overview_copy("zz-qq-ww") is _COPY["en"]


def test_missing_languages_normalizes_its_input_before_judging() -> None:
    assert missing_languages([" ZH ", "EN", "zh-TW", "FR"]) == ["FR"]
    assert missing_languages([]) == []


def test_missing_languages_keeps_duplicates_countable() -> None:
    assert missing_languages(["xx", "xx", "xx"]) == ["xx", "xx", "xx"]


# --- A degenerate table entry is served verbatim and fails loudly -----------


def test_a_partial_translation_is_returned_verbatim_not_merged_with_english(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No silent English backfill: a broken entry reaches the consumer as-is."""
    partial = {"chapter_title": "仅存一个键"}
    monkeypatch.setitem(_COPY, "zh", partial)
    assert overview_copy("zh") is partial


def test_a_partial_translation_fails_loudly_at_the_consumer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """engine.py subscripts every key directly, so a gap raises instead of
    rendering a stray English string mid-page."""
    monkeypatch.setitem(_COPY, "zh", {"chapter_title": "仅存一个键"})
    copy = overview_copy("zh")
    with pytest.raises(KeyError):
        copy["intro_body"]  # noqa: B018


# --- The consumer's assembly contract ---------------------------------------


def test_every_key_the_engine_consumes_is_declared_required() -> None:
    """engine.py reads exactly these keys via direct subscript (lines 736-845)."""
    engine_consumed = {
        "chapter_title",
        "objectives",
        "chapter_summary",
        "untitled_book",
        "intro_title",
        "intro_body",
        "concept_map_title",
        "chapter_index_title",
        "chapter_index_heading",
    }
    assert engine_consumed == REQUIRED_KEYS
