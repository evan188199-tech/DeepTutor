"""Behavior tests for the shared notebook text shaping helpers."""

from __future__ import annotations

import pytest

from deeptutor.agents.notebook._text import clip_text

TRUNCATION_MARKER = "\n...[truncated]"


@pytest.mark.parametrize(
    ("value", "limit", "expected"),
    [
        (None, 10, ""),
        ("", 10, ""),
        ("   \n\t  ", 10, ""),
        (0, 10, ""),
        ("brief", 10, "brief"),
        ("exactly10", 9, "exactly10"),
        ("abcdefgh", 5, "abcde" + TRUNCATION_MARKER),
        ("abcd  ", 4, "abcd"),
        ("a b c d", 5, "a b c" + TRUNCATION_MARKER),
        (12345, 3, "123" + TRUNCATION_MARKER),
    ],
)
def test_clip_text_shapes_values_as_documented(value: object, limit: int, expected: str) -> None:
    assert clip_text(value, limit) == expected


@pytest.mark.parametrize(
    "value",
    ["word " * 20, "很长的中文内容" * 30],
)
def test_truncated_output_ends_with_a_single_marker(value: str) -> None:
    result = clip_text(value, 40)
    assert result.endswith(TRUNCATION_MARKER)
    assert result.count(TRUNCATION_MARKER) == 1
    assert result[: -len(TRUNCATION_MARKER)] == result[: -len(TRUNCATION_MARKER)].rstrip()


@pytest.mark.parametrize(
    ("value", "limit"),
    [("kept as-is", 40), ("kept as-is", 10)],
)
def test_values_within_the_limit_pass_through_untouched(value: str, limit: int) -> None:
    assert clip_text(value, limit) == value.strip()


def test_clipping_is_idempotent() -> None:
    once = clip_text("a long sentence that exceeds the limit", 12)
    assert clip_text(once, 12) == once
