"""Tests for learner-facing unicode escape decoding (#973)."""

from __future__ import annotations

from deeptutor.utils.text_display import decode_escaped_unicode_for_display


def test_decodes_dense_non_ascii_runs() -> None:
    escaped = "\\u300c\\u6570\\u5236\\u8f6c\\u6362\\u300d"
    assert decode_escaped_unicode_for_display(escaped) == "「数制转换」"


def test_leaves_short_ascii_runs_alone() -> None:
    text = "A JSON string can encode A as \\u0041."
    assert decode_escaped_unicode_for_display(text) == text


def test_empty_and_plain_text_passthrough() -> None:
    assert decode_escaped_unicode_for_display("") == ""
    assert decode_escaped_unicode_for_display("hello") == "hello"


def test_dense_ascii_run_is_left_untouched() -> None:
    """3+ escapes decode to pure ASCII, so the run must stay literal."""
    text = "ids \\u0041\\u0042\\u0043 stay literal"
    assert decode_escaped_unicode_for_display(text) == text


def test_decodes_run_embedded_in_prose() -> None:
    text = "prefix \\u4e2d\\u6587\\u6d4b\\u8bd5 suffix"
    assert decode_escaped_unicode_for_display(text) == "prefix 中文测试 suffix"


def test_decodes_each_run_independently() -> None:
    text = "\\u7b2c\\u4e00\\u6bb5 and \\u7b2c\\u4e8c\\u6bb5"
    assert decode_escaped_unicode_for_display(text) == "第一段 and 第二段"
