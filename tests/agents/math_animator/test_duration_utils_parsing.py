"""Parsing and formatting boundaries for math animator duration helpers."""

from __future__ import annotations

import pytest

from deeptutor.agents.math_animator.duration_utils import parse_target_duration_seconds


@pytest.mark.parametrize("text", ["", "   ", None])
def test_blank_input_returns_none(text: str | None) -> None:
    assert parse_target_duration_seconds(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "explain the chain rule",
        "make it fast please",
        "100 frames",
        "12 dots",
        "1ms and 3 apples",
    ],
)
def test_text_without_duration_unit_returns_none(text: str) -> None:
    assert parse_target_duration_seconds(text) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("30s", 30.0),
        ("last 30 sec", 30.0),
        ("about 45 secs", 45.0),
        ("in 20 seconds", 20.0),
        ("Give me a 1.5s clip", 1.5),
        ("30 S", 30.0),
        ("30 Seconds", 30.0),
        (" lasts 20秒", 20.0),
        ("30秒钟", 30.0),
        ("0.5 秒", 0.5),
    ],
)
def test_second_forms_parse(text: str, expected: float) -> None:
    assert parse_target_duration_seconds(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2 min", 120.0),
        ("3 minute", 180.0),
        ("roughly 4 minutes", 240.0),
        ("5 m", 300.0),
        ("1.5 minutes", 90.0),
        ("10分钟", 600.0),
        ("2.5分钟", 150.0),
    ],
)
def test_minute_forms_parse(text: str, expected: float) -> None:
    assert parse_target_duration_seconds(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("wait 10 seconds or 2 minutes", 120.0),
        ("90 s and 2 min", 120.0),
        ("1.5 min plus 45 sec", 90.0),
    ],
)
def test_multiple_targets_take_the_max(text: str, expected: float) -> None:
    assert parse_target_duration_seconds(text) == expected


def test_millisecond_suffix_is_not_parsed_as_second_or_minute() -> None:
    # "2ms" contributes nothing; only the explicit second target counts.
    assert parse_target_duration_seconds("2ms and 3s") == 3.0


def test_decimal_fraction_of_second_is_not_rounded() -> None:
    assert parse_target_duration_seconds("1.25s") == 1.25
