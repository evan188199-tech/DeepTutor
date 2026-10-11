"""Table-driven boundary tests for notebook text shaping helpers."""

from __future__ import annotations

import pytest

from deeptutor.agents.notebook._text import clip_text

TRUNCATED = "\n...[truncated]"


@pytest.mark.parametrize(
    ("value", "limit", "expected"),
    [
        pytest.param("", 10, "", id="empty-string-under-limit"),
        pytest.param("", 0, "", id="empty-string-limit-zero"),
        pytest.param(None, 10, "", id="none-input-falls-back-to-empty"),
        pytest.param(None, 0, "", id="none-input-limit-zero"),
        pytest.param(0, 10, "", id="falsy-int-falls-back-to-empty"),
        pytest.param("   \n\t ", 5, "", id="whitespace-only-strips-to-empty"),
        pytest.param(42, 10, "42", id="non-string-int-stringified"),
        pytest.param("hello", 5, "hello", id="short-text-unchanged"),
        pytest.param("  spaced  ", 10, "spaced", id="surrounding-whitespace-stripped"),
        pytest.param("  padded  ", 6, "padded", id="stripped-length-exactly-at-limit"),
        pytest.param("abcde", 5, "abcde", id="exact-limit-no-marker"),
        pytest.param("ab\ncd", 5, "ab\ncd", id="internal-newline-preserved-no-marker"),
    ],
)
def test_clip_text_passthrough(value: object, limit: int, expected: str) -> None:
    assert clip_text(value, limit) == expected


@pytest.mark.parametrize(
    ("value", "limit", "prefix"),
    [
        pytest.param("abcdefgh", 4, "abcd", id="overlong-cut-at-limit"),
        pytest.param("abcd    x", 4, "abcd", id="overlong-rstrips-cut-boundary"),
        pytest.param("  abcdefgh  ", 4, "abcd", id="strip-before-length-accounting"),
        pytest.param("hello world", 0, "", id="limit-zero-marks-truncation"),
        pytest.param("abcdef", -1, "abcde", id="negative-limit-slices-from-end"),
        pytest.param("ab", -1, "a", id="negative-limit-single-char"),
    ],
)
def test_clip_text_overlong_appends_marker(value: object, limit: int, prefix: str) -> None:
    result = clip_text(value, limit)
    assert result == prefix + TRUNCATED
    assert result.startswith(prefix)
    assert result.endswith(TRUNCATED)


def test_clip_text_non_string_overlong_falls_back_to_str() -> None:
    assert clip_text(1234567, 4) == "1234" + TRUNCATED


def test_clip_text_marker_only_on_actual_truncation() -> None:
    assert TRUNCATED not in clip_text("a b", 3)
    assert TRUNCATED in clip_text("a bcd", 3)
