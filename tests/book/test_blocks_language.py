"""The blocks ``_language`` re-export and the rules it keeps alive."""

from __future__ import annotations

import pytest

import deeptutor.book.blocks._language as blocks_language
import deeptutor.services.prompt.language as shared_language
from deeptutor.book.blocks._language import (
    append_language_directive,
    language_directive,
    language_label,
    normalize_language,
)


def test_reexport_binds_to_the_shared_prompt_helpers() -> None:
    assert blocks_language.__all__ == [
        "append_language_directive",
        "language_directive",
        "language_label",
        "normalize_language",
    ]
    for name in blocks_language.__all__:
        assert getattr(blocks_language, name) is getattr(shared_language, name)


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("en", "en"),
        ("zh", "zh"),
        ("ZH-TW", "zh-tw"),
        ("  Fr  ", "fr"),
        ("pt-br", "pt-br"),
    ],
)
def test_normalize_matches_supported_codes(language: str, expected: str) -> None:
    assert normalize_language(language) == expected


@pytest.mark.parametrize("language", [None, "", "   ", "\n\t "])
def test_normalize_falls_back_to_english_when_nothing_usable(
    language: str | None,
) -> None:
    assert normalize_language(language) == "en"


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("zh-cn", "中文（简体）"),
        ("en", "English"),
        ("ja", "日本語"),
        ("ko", "한국어"),
        ("ar", "العربية"),
    ],
)
def test_label_hits_the_supported_language_table(
    language: str, expected: str
) -> None:
    assert language_label(language) == expected


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("zh-sg", "中文（简体）"),
        ("pt-BR", "Português"),
        ("de-AT", "Deutsch"),
    ],
)
def test_label_falls_back_to_the_base_language_for_regional_codes(
    language: str, expected: str
) -> None:
    assert language_label(language) == expected


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("xx", "xx"),
        ("xx-YY", "xx-YY"),
        (None, "English"),
    ],
)
def test_label_misses_resolve_without_crashing(
    language: str | None, expected: str
) -> None:
    assert language_label(language) == expected


@pytest.mark.parametrize(
    ("language", "expected_marker"),
    [
        ("zh", "请严格使用中文（简体）撰写所有面向读者的文本"),
        ("zh-tw", "繁體中文"),
        ("en", "Write ALL reader-facing text"),
        ("fr", "strictly in Français"),
        (None, "Write ALL reader-facing text"),
    ],
)
def test_directive_states_the_rule_for_each_language(
    language: str | None, expected_marker: str
) -> None:
    directive = language_directive(language)
    assert directive.startswith("\n\n[")
    assert expected_marker in directive


@pytest.mark.parametrize("language", ["zh", "en", "fr", None])
def test_directive_omits_the_override_tail_by_default(
    language: str | None,
) -> None:
    directive = language_directive(language)
    assert "honour that request" not in directive
    assert "用户当次的要求" not in directive


@pytest.mark.parametrize(
    ("language", "expected_tail"),
    [
        ("zh", "以用户当次的要求为准"),
        ("fr", "honour that request"),
    ],
)
def test_directive_appends_the_override_tail_only_when_allowed(
    language: str, expected_tail: str
) -> None:
    strict = language_directive(language)
    overridable = language_directive(language, allow_user_override=True)
    assert expected_tail not in strict
    assert overridable.startswith(strict)
    assert expected_tail in overridable


@pytest.mark.parametrize(
    ("system_prompt", "language"),
    [
        ("You are a patient tutor.", "ja"),
        ("You are a patient tutor.", None),
    ],
)
def test_append_joins_the_prompt_and_the_directive(
    system_prompt: str, language: str | None
) -> None:
    combined = append_language_directive(system_prompt, language)
    assert combined.startswith(system_prompt)
    assert combined[len(system_prompt) :].startswith("\n\n")
    assert combined.endswith(
        language_directive(language, allow_user_override=False).strip()
    )


@pytest.mark.parametrize("system_prompt", [None, "", "   \n  "])
def test_append_falls_back_to_the_directive_without_a_prompt(
    system_prompt: str | None,
) -> None:
    combined = append_language_directive(system_prompt, "ko")
    assert combined == language_directive("ko").strip()
