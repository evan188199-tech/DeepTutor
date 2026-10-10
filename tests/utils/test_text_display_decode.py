"""Boundary tests for display-side ``\\uXXXX`` decode (#973).

Complements ``tests/utils/test_text_display.py`` with the dense-run
threshold edges, non-text run preservation, and idempotency of the
pure decoder in ``deeptutor.utils.text_display``.
"""

from __future__ import annotations

import pytest

from deeptutor.utils.text_display import decode_escaped_unicode_for_display

CASES = [
    (
        "below-threshold-two-escapes-stay-literal",
        "\\u4e2d\\u6587",
        "\\u4e2d\\u6587",
    ),
    (
        "threshold-minimum-three-escapes-decode",
        "\\u4e2d\\u6587\\u6d4b",
        "中文测",
    ),
    (
        "short-run-preserved-while-dense-run-decoded",
        "\\u4e2d\\u6587 \\u4e2d\\u6587\\u6d4b\\u8bd5",
        "\\u4e2d\\u6587 中文测试",
    ),
    (
        "dense-ascii-only-run-stays-literal",
        "\\u0041\\u0042\\u0043",
        "\\u0041\\u0042\\u0043",
    ),
    (
        "dense-ascii-run-with-control-char-stays-literal",
        "line1\\u0061\\u0062\\u000aline2",
        "line1\\u0061\\u0062\\u000aline2",
    ),
    (
        "adjacent-surrogate-pairs-join-separately",
        "\\ud83d\\ude00\\ud83d\\ude04",
        "😀😄",
    ),
    (
        "decoded-run-embedded-in-prose",
        "prefix \\u7b2c\\u4e00\\u6bb5 suffix",
        "prefix 第一段 suffix",
    ),
]


@pytest.mark.parametrize(
    ("text", "expected"),
    [(text, expected) for _, text, expected in CASES],
    ids=[name for name, _, _ in CASES],
)
def test_decode_boundaries(text: str, expected: str) -> None:
    assert decode_escaped_unicode_for_display(text) == expected


@pytest.mark.parametrize(
    "text",
    [text for _, text, _ in CASES],
    ids=[name for name, _, _ in CASES],
)
def test_decode_is_idempotent(text: str) -> None:
    once = decode_escaped_unicode_for_display(text)
    assert decode_escaped_unicode_for_display(once) == once
