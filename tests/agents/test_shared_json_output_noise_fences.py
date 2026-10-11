"""FT79 contract tests for ``agents/_shared/json_output``.

Focused on noisy prefix/suffix inputs, nested-fence inputs, and the
consistency boundary with ``utils.json_parser.parse_json_response``.
"""

from __future__ import annotations

import json

import pytest

from deeptutor.agents._shared.json_output import extract_json_object
from deeptutor.utils.json_parser import parse_json_response

# ---------------------------------------------------------------------------
# Noisy prefix / suffix around the payload
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"value": 1}\nNote: see {docs} for details', {"value": 1}),
        ('{"value": 1}\nAlso ranked: [9, 8]', {"value": 1}),
        ("# Analysis\n- point one\n- point two\n\n" + '{"value": 1}', {"value": 1}),
        (
            "Step 1: think.\nStep 2: act.\n\n" + '{"action": "go", "count": 3}',
            {"action": "go", "count": 3},
        ),
    ],
    ids=[
        "brace-bearing-suffix",
        "array-noise-suffix",
        "markdown-bullet-prefix",
        "numbered-steps-prefix",
    ],
)
def test_noisy_surroundings_do_not_shadow_payload(text: str, expected: dict[str, object]) -> None:
    assert extract_json_object(text) == expected


# ---------------------------------------------------------------------------
# Nested and unusual fences
# ---------------------------------------------------------------------------


def test_non_json_language_fence_still_yields_object() -> None:
    raw = "```python\n" + '{"value": 1}\n' + "```"

    assert extract_json_object(raw) == {"value": 1}


def test_unclosed_fence_still_yields_object() -> None:
    raw = "```json\n" + '{"value": 1}'

    assert extract_json_object(raw) == {"value": 1}


def test_outer_fence_with_inner_prose_fence_still_yields_object() -> None:
    raw = "```\npreamble\n```\n" + '{"value": 1}\n' + "```"

    assert extract_json_object(raw) == {"value": 1}


# ---------------------------------------------------------------------------
# Consistency with utils.json_parser.parse_json_response
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        '{"value": 1}',
        'Answer:\n```json\n{"value": 1}\n```\nDone.',
        '<think>plan {"x": 1}</think>\n{"value": 1}',
        '<think>plan</think>\n```json\n{"value": 1}\n```\nDone.',
    ],
    ids=[
        "bare",
        "fenced-with-prose",
        "closed-think-with-draft",
        "closed-think-with-fenced-payload",
    ],
)
def test_agrees_with_parse_json_response(text: str) -> None:
    assert extract_json_object(text) == {"value": 1}
    assert parse_json_response(text) == {"value": 1}


@pytest.mark.parametrize("text", ["", "   \n\t"], ids=["empty", "whitespace"])
def test_empty_input_yields_empty_dict_for_both_parsers(text: str) -> None:
    assert extract_json_object(text) == {}
    assert parse_json_response(text) == {}


def test_prose_without_json_is_strict_in_extract_fallback_in_parse() -> None:
    text = "No structured output here."

    with pytest.raises(json.JSONDecodeError, match="No JSON object found"):
        extract_json_object(text)

    assert parse_json_response(text) == {}
    assert parse_json_response(text, fallback=None) is None


def test_nested_fence_inside_string_value_diverges_between_parsers() -> None:
    expected = {"code": "```python\nprint(1)\n```", "value": 2}
    raw = "```json\n" + json.dumps(expected) + "\n```\nHope this helps."

    assert extract_json_object(raw) == expected
    assert parse_json_response(raw) == {"code": ""}


def test_first_object_precedence_diverges_from_longest_value() -> None:
    text = 'Prefix {"a": 1} then payload {"b": 2, "c": 3}'

    assert extract_json_object(text) == {"a": 1}
    assert parse_json_response(text) == {"b": 2, "c": 3}


def test_invalid_brace_fragment_in_prefix_diverges() -> None:
    text = 'See {diagram} below.\n{"value": 1}'

    with pytest.raises(json.JSONDecodeError):
        extract_json_object(text)

    assert parse_json_response(text) == {"value": 1}


def test_unclosed_think_precedence_diverges() -> None:
    text = '<think>Reasoning about {"q": 1}\n{"value": 42}'

    assert extract_json_object(text) == {"q": 1}
    assert parse_json_response(text) == {"value": 42}


def test_non_dict_first_fence_skipped_for_dict_fence_diverges() -> None:
    text = 'Analysis:\n```\n[1, 2, 3]\n```\n```json\n{"value": 1}\n```'

    assert extract_json_object(text) == {"value": 1}
    assert parse_json_response(text) == [1, 2, 3]
