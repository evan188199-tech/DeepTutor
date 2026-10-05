"""Boundary coverage for the shared LLM-output JSON extractor.

Locks current behavior of ``extract_json_object`` and
``_decode_first_json_object`` on fenced output, prose noise, truncated
JSON, nested objects and unicode escapes, including explicit assertions
for inputs that must raise ``json.JSONDecodeError`` or return ``None``.
"""

from __future__ import annotations

import json

import pytest

from deeptutor.agents._shared.json_output import (
    _decode_first_json_object,
    extract_json_object,
)

NESTED_OBJECT = '{"outer": {"inner": {"deep": [1, {"x": null}]}}}'
NESTED_EXPECTED = {"outer": {"inner": {"deep": [1, {"x": None}]}}}
FENCE_IN_STRING_RAW = '{"a": 1, "b": "```json {\\"x\\": 2}```"}'
FENCE_IN_STRING_EXPECTED = {"a": 1, "b": '```json {"x": 2}```'}
BRACES_IN_STRING_RAW = '{"s": "brace } and bracket ] inside"}'
BRACES_IN_STRING_EXPECTED = {"s": "brace } and bracket ] inside"}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (None, {}),
        ("", {}),
        ("   \n\t  ", {}),
        ('{"a": 1}', {"a": 1}),
        ('  \n\t{"a": 1}\n  ', {"a": 1}),
        ('{\n  "multiline": true,\n  "list": [1, 2]\n}', {"multiline": True, "list": [1, 2]}),
        (NESTED_OBJECT, NESTED_EXPECTED),
        ('{"name": "\\u4f60\\u597d"}', {"name": "你好"}),
        ('{"emoji": "\\ud83d\\ude00"}', {"emoji": "\U0001f600"}),
        ('{"name": "é"}', {"name": "é"}),
        ('Sure thing!\n```json\n{"a": 1}\n```\nHope that helps', {"a": 1}),
        ('```json\n{"a": 1}\n```\n```json\n{"b": 2}\n```', {"a": 1}),
        ('```\n{"a": 1}\n```', {"a": 1}),
        ('Model preface: {"a": 1} — regards', {"a": 1}),
        ('{"a": 1} trailing prose', {"a": 1}),
        ('{"a": 1} {"b": 2}', {"a": 1}),
        ('{"a": 1}}', {"a": 1}),
        ('[{"a": 1}]', {"a": 1}),
        ('42 {"a": 1}', {"a": 1}),
        ('[1, 2] then {"a": 3}', {"a": 3}),
        ('<think>chain of thought</think>{"a": 1}', {"a": 1}),
        ('<think>unclosed {"a": 1}', {"a": 1}),
        (FENCE_IN_STRING_RAW, FENCE_IN_STRING_EXPECTED),
        (BRACES_IN_STRING_RAW, BRACES_IN_STRING_EXPECTED),
    ],
    ids=[
        "none-input",
        "empty-string",
        "whitespace-only",
        "bare-object",
        "whitespace-padded",
        "multiline-object",
        "nested-object",
        "unicode-escapes",
        "unicode-surrogate-pair",
        "raw-unicode",
        "fenced-with-prose",
        "first-fence-wins",
        "bare-fence",
        "noise-before",
        "noise-after",
        "first-of-two-objects",
        "extra-closing-brace",
        "object-inside-array",
        "scalar-prefix-skipped",
        "array-prefix-skipped",
        "think-block-stripped",
        "unclosed-think-fallback",
        "fence-inside-string-preserved",
        "braces-inside-string-preserved",
    ],
)
def test_extract_json_object_accepts(text: str | None, expected: dict) -> None:
    assert extract_json_object(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "hello world",
        "no object at all",
        "{'single': 'quotes'}",
        '{"a": 1',
        '{"a": tr}',
        '{"a": 1,}',
        "[]",
        "[1, 2]",
        "```json\n[1, 2]\n```",
        '```json\n{"a": 1',
        "null",
        '"quoted string"',
        "<think></think>",
    ],
    ids=[
        "prose-only",
        "words-without-braces",
        "single-quotes",
        "truncated-object",
        "invalid-value-token",
        "trailing-comma",
        "empty-array-only",
        "array-only",
        "fenced-array-only",
        "truncated-fence",
        "null-scalar",
        "string-scalar",
        "empty-think-only",
    ],
)
def test_extract_json_object_rejects(text: str) -> None:
    with pytest.raises(json.JSONDecodeError, match="No JSON object found"):
        extract_json_object(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("hello world", None),
        ('{"a": 1}', {"a": 1}),
        ('  {"a": 1}', {"a": 1}),
        ('{"a": 1} trailing prose', {"a": 1}),
        ('noise before {"a": 1}', {"a": 1}),
        ('{"a": 1} {"b": 2}', {"a": 1}),
        ('{"a": 1}}', {"a": 1}),
        ('{"a": 1', None),
        ('{"a": tr}', None),
        ("[]", None),
        ("[1, 2]", None),
        ('[{"a": 1}]', {"a": 1}),
        ("42", None),
        ("null", None),
        ('[1, 2] then {"a": 3}', {"a": 3}),
        (NESTED_OBJECT, NESTED_EXPECTED),
        ('{"name": "\\u4f60\\u597d"}', {"name": "你好"}),
    ],
    ids=[
        "none-input",
        "empty-string",
        "whitespace-only",
        "prose-only",
        "bare-object",
        "leading-whitespace",
        "trailing-prose",
        "noise-before",
        "first-of-two-objects",
        "extra-closing-brace",
        "truncated-object",
        "invalid-value-token",
        "empty-array",
        "array-only",
        "object-inside-array",
        "int-scalar",
        "null-scalar",
        "array-prefix-skipped",
        "nested-object",
        "unicode-escapes",
    ],
)
def test_decode_first_json_object(text: str | None, expected: dict | None) -> None:
    assert _decode_first_json_object(text) == expected
