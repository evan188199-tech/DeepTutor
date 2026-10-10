"""Boundary and error-message contract tests for KB name validation.

``validate_knowledge_base_name`` is the single gate every KB name passes
(manager register paths, CLI ``kb`` commands, the create route), and web and
CLI surfaces surface its messages verbatim to users. These tests lock the
validation boundaries and the exact copy so a refactor cannot silently drift
the wording. ``tests/knowledge/test_naming.py`` covers manager integration
and URL separators; this module owns the boundary matrix.
"""

from __future__ import annotations

import pytest

from deeptutor.knowledge.naming import validate_knowledge_base_name

_MAX_KB_NAME_LENGTH = 120

_REQUIRED_MSG = "Knowledge base name is required"
_DOT_DOT_MSG = "Knowledge base name cannot be '.' or '..'"
_TOO_LONG_MSG = "Knowledge base name is too long; maximum length is 120"
_CONTROL_MSG = "Knowledge base name cannot contain control characters"

_ALL_RESERVED_CHARS = '<>:"/\\|?*#%'


def _reserved_message(joined: str) -> str:
    return (
        "Knowledge base name contains reserved characters: "
        f"{joined}. Avoid path or URL separators such as /, \\, ?, #, and %."
    )


def _assert_error(raw: str, message: str) -> None:
    with pytest.raises(ValueError) as excinfo:
        validate_knowledge_base_name(raw)
    assert str(excinfo.value) == message


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a" * _MAX_KB_NAME_LENGTH, "a" * _MAX_KB_NAME_LENGTH),
        ("...", "..."),
        (".hidden", ".hidden"),
        ("v1.2-notes_final", "v1.2-notes_final"),
        ("  spaced  name  ", "spaced  name"),
        ("数学 📚 KB", "数学 📚 KB"),
        ("cafe\u0301", "caf\u00e9"),
        # 240 decomposed code points normalize to 120 composed ones, so the
        # length cap must be measured on the NFC form, not the raw input.
        ("e\u0301" * _MAX_KB_NAME_LENGTH, "\u00e9" * _MAX_KB_NAME_LENGTH),
    ],
)
def test_accepts_boundary_names_and_returns_normalized_form(raw: str, expected: str) -> None:
    assert validate_knowledge_base_name(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "\t\n"])
def test_missing_name_message_is_locked(raw: str) -> None:
    _assert_error(raw, _REQUIRED_MSG)


@pytest.mark.parametrize("raw", [".", "..", " .. ", " .\n"])
def test_dot_dot_message_is_locked_after_strip(raw: str) -> None:
    _assert_error(raw, _DOT_DOT_MSG)


@pytest.mark.parametrize("raw", ["a" * (_MAX_KB_NAME_LENGTH + 1), "数" * (_MAX_KB_NAME_LENGTH + 1)])
def test_overlength_message_is_locked(raw: str) -> None:
    _assert_error(raw, _TOO_LONG_MSG)


@pytest.mark.parametrize(
    "raw",
    ["a\x00b", "a\x07b", "a\x1fb", "a\x7fb", "line1\nline2", "a\tb"],
)
def test_control_character_message_is_locked(raw: str) -> None:
    _assert_error(raw, _CONTROL_MSG)


@pytest.mark.parametrize("reserved", _ALL_RESERVED_CHARS)
def test_every_reserved_character_message_is_locked(reserved: str) -> None:
    _assert_error(f"bad{reserved}name", _reserved_message(reserved))


@pytest.mark.parametrize(
    ("raw", "joined"),
    [
        # The "joined" literals below are hand-written, not computed from the
        # input, so the sorted ordering of the reported characters is part of
        # the locked contract.
        ("a|b<c", "< |"),
        ("x/y\\z", "/ \\"),
        (f"kb{_ALL_RESERVED_CHARS}name", '" # % * / : < > ? \\ |'),
    ],
)
def test_reserved_characters_reported_in_sorted_order(raw: str, joined: str) -> None:
    _assert_error(raw, _reserved_message(joined))
