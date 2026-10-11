"""Focused coverage for ``agents.research.utils.json_utils``.

Locks the current lenient-parsing behavior of ``extract_json_from_text``
(fenced output, prose noise, truncated JSON, scalar passthrough) plus the
strict validation helpers, ``safe_json_loads`` degradation and
``json_to_text`` serialization.
"""

from __future__ import annotations

import pytest

from deeptutor.agents.research.utils.json_utils import (
    ensure_json_dict,
    ensure_json_list,
    ensure_keys,
    extract_json_from_text,
    json_to_text,
    safe_json_loads,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"a": 1}', {"a": 1}),
        ("[1, 2, 3]", [1, 2, 3]),
        ('前缀噪声\n```json\n{"a": 1}\n```\n后缀', {"a": 1}),
        ('```\n{"b": 2}\n```', {"b": 2}),
        ('```json\n{"deep": {"x": [1, 2]}}\n```', {"deep": {"x": [1, 2]}}),
        ('Here is the plan: {"steps": [1, 2]}', {"steps": [1, 2]}),
        ('noise {"x": 0} tail {"y": [1,', {"x": 0}),
        ('```json\nnot json\n``` tail {"ok": 1}', {"ok": 1}),
        ('{"名称": "值"}', {"名称": "值"}),
        ("42", 42),
        ("true", True),
        ('"quoted string"', "quoted string"),
    ],
    ids=[
        "bare-object",
        "bare-array",
        "fenced-object-with-cjk-prose",
        "fence-without-language-tag",
        "fenced-nested-object",
        "prose-prefix-before-object",
        "truncated-tail-keeps-first-complete",
        "invalid-fence-falls-back-to-fragment",
        "unicode-keys-preserved",
        "int-scalar-passthrough",
        "bool-scalar-passthrough",
        "string-scalar-passthrough",
    ],
)
def test_extract_accepts(text: str, expected: object) -> None:
    assert extract_json_from_text(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        None,
        "   ",
        "hello world",
        '{"a": 1',
        '{"a": [1, 2',
        '```json\n{"a": 1',
        "{",
        "[",
    ],
    ids=[
        "empty-string",
        "none-input",
        "whitespace-only",
        "prose-only",
        "truncated-object",
        "truncated-array",
        "truncated-fence-no-closing",
        "lone-open-brace",
        "lone-open-bracket",
    ],
)
def test_extract_returns_none(text: str | None) -> None:
    assert extract_json_from_text(text) is None


def test_extract_scalar_null_parses_to_none() -> None:
    assert extract_json_from_text("null") is None


def test_ensure_json_dict_passes_through_same_object() -> None:
    data = {"a": 1}
    assert ensure_json_dict(data) is data


def test_ensure_json_list_passes_through_same_object() -> None:
    data = [1, 2]
    assert ensure_json_list(data) is data


@pytest.mark.parametrize(
    ("data", "err"),
    [
        ([1, 2], "Expected JSON object"),
        ("not a dict", "Expected JSON object"),
        (None, "Expected JSON object"),
        ("not a dict", "custom dict error"),
    ],
    ids=["list-rejected", "string-rejected", "none-rejected", "custom-message"],
)
def test_ensure_json_dict_rejects(data: object, err: str) -> None:
    with pytest.raises(ValueError, match=err):
        ensure_json_dict(data, err)


@pytest.mark.parametrize(
    ("data", "err"),
    [
        ({"a": 1}, "Expected JSON array"),
        ("not a list", "Expected JSON array"),
        (None, "Expected JSON array"),
        ({"a": 1}, "custom list error"),
    ],
    ids=["dict-rejected", "string-rejected", "none-rejected", "custom-message"],
)
def test_ensure_json_list_rejects(data: object, err: str) -> None:
    with pytest.raises(ValueError, match=err):
        ensure_json_list(data, err)


def test_ensure_keys_all_present_returns_data() -> None:
    data = {"a": 1, "b": 2}
    assert ensure_keys(data, ["a", "b"]) is data


def test_ensure_keys_empty_requirement_returns_data() -> None:
    data = {"a": 1}
    assert ensure_keys(data, []) is data


def test_ensure_keys_single_missing_message() -> None:
    with pytest.raises(KeyError, match="Missing required keys: b"):
        ensure_keys({"a": 1}, ["a", "b"])


def test_ensure_keys_multiple_missing_keeps_order() -> None:
    with pytest.raises(KeyError, match="Missing required keys: b, c"):
        ensure_keys({"a": 1}, ("b", "c"))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"a": 1}', {"a": 1}),
        ("[1, 2]", [1, 2]),
        ("null", None),
    ],
    ids=["object", "array", "json-null"],
)
def test_safe_json_loads_valid(text: str, expected: object) -> None:
    assert safe_json_loads(text, default="fallback") == expected


def test_safe_json_loads_json_null_not_replaced_by_default() -> None:
    assert safe_json_loads("null", default={"fallback": True}) is None


def test_safe_json_loads_invalid_uses_default_none() -> None:
    assert safe_json_loads("{bad json") is None


def test_safe_json_loads_invalid_uses_custom_default() -> None:
    sentinel = {"fallback": True}
    assert safe_json_loads("{bad json", default=sentinel) is sentinel


@pytest.mark.parametrize(
    ("text", "default"),
    [
        (None, "fallback"),
        (["not", "a", "string"], 0),
        (123, None),
    ],
    ids=["none-input", "list-input", "int-input"],
)
def test_safe_json_loads_type_error_degrades_to_default(text: object, default: object) -> None:
    assert safe_json_loads(text, default=default) == default


def test_json_to_text_default_indent_and_no_ascii_escape() -> None:
    assert json_to_text({"名称": "值"}) == '{\n  "名称": "值"\n}'


def test_json_to_text_ascii_indent_zero() -> None:
    assert json_to_text({"a": 1}, indent=0) == '{\n"a": 1\n}'


def test_json_to_text_list_round_trip() -> None:
    data = [{"b": [1, 2]}, "文本"]
    assert extract_json_from_text(json_to_text(data)) == data
