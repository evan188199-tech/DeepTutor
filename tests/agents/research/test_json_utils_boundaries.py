"""Boundary coverage for ``extract_json_from_text``.

Locks current behavior of the research-side extractor on fenced output,
prose noise, truncated JSON, nested objects and unicode escapes, plus the
explicit ``None`` results for failure inputs.
"""

from __future__ import annotations

import pytest

from deeptutor.agents.research.utils.json_utils import extract_json_from_text

NESTED_OBJECT = '{"outer": {"inner": {"deep": [1, {"x": null}]}}}'
NESTED_EXPECTED = {"outer": {"inner": {"deep": [1, {"x": None}]}}}
FENCE_IN_STRING_RAW = '{"a": 1, "b": "```json {\\"x\\": 2}```"}'
FENCE_IN_STRING_EXPECTED = {"a": 1, "b": '```json {"x": 2}```'}
BRACES_IN_STRING_RAW = '{"s": "brace } and bracket ] inside"}'
BRACES_IN_STRING_EXPECTED = {"s": "brace } and bracket ] inside"}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"a": 1}', {"a": 1}),
        ("[1, 2]", [1, 2]),
        ("[]", []),
        ('[{"a": 1}]', [{"a": 1}]),
        ('Sure thing!\n```json\n{"a": 1}\n```\nHope that helps', {"a": 1}),
        ("```json\n[1, 2]\n```", [1, 2]),
        ('```json\n{"a": 1}\n```\n```json\n{"b": 2}\n```', {"a": 1}),
        ('```json\n{"fence": 1}\n```\nalso {"plain": 2}', {"fence": 1}),
        (FENCE_IN_STRING_RAW, FENCE_IN_STRING_EXPECTED),
        ('result: {"x": true} done', {"x": True}),
        ('{"a": 1} {"b": 2}', {"a": 1}),
        ('[1, 2] then {"a": 3}', [1, 2]),
        (NESTED_OBJECT, NESTED_EXPECTED),
        ('{"name": "\\u4f60\\u597d"}', {"name": "你好"}),
        ('{"emoji": "\\ud83d\\ude00"}', {"emoji": "\U0001f600"}),
        ("42", 42),
        ('"quoted string"', "quoted string"),
        ('{"a": 1}}', {"a": 1}),
        (BRACES_IN_STRING_RAW, BRACES_IN_STRING_EXPECTED),
    ],
    ids=[
        "bare-object",
        "bare-array",
        "empty-array",
        "array-of-objects",
        "fenced-object-with-prose",
        "fenced-array",
        "first-fence-wins",
        "fence-beats-later-raw-object",
        "fence-inside-string-full-object",
        "noise-before-and-after",
        "first-of-two-objects",
        "array-beats-later-object",
        "nested-object",
        "unicode-escapes",
        "unicode-surrogate-pair",
        "int-scalar-passthrough",
        "string-scalar-passthrough",
        "extra-closing-brace",
        "braces-inside-string-preserved",
    ],
)
def test_extract_json_from_text_accepts(text: str, expected: object) -> None:
    assert extract_json_from_text(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "   ",
        "hello world",
        "no object at all",
        '{"a": 1',
        '{"a": tr}',
        '{"a": 1,}',
        "{'single': 'quotes'}",
        '```json\n{"a": 1',
        "<think></think>",
        "null",
    ],
    ids=[
        "none-input",
        "empty-string",
        "whitespace-only",
        "prose-only",
        "words-without-braces",
        "truncated-object",
        "invalid-value-token",
        "trailing-comma",
        "single-quotes",
        "truncated-fence",
        "empty-think-only",
        "null-scalar",
    ],
)
def test_extract_json_from_text_returns_none(text: str | None) -> None:
    assert extract_json_from_text(text) is None
