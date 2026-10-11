from __future__ import annotations

import json

import pytest

from deeptutor.agents._shared.json_output import extract_json_object


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", {}),
        ('{"value": 1}', {"value": 1}),
        ('Result:\n```json\n{"value": 2}\n```', {"value": 2}),
        ('Model preface\n{"value": 3}', {"value": 3}),
        ('{"value": 4}\nTrailing explanation', {"value": 4}),
    ],
)
def test_extract_json_object(text: str, expected: dict[str, int]) -> None:
    assert extract_json_object(text) == expected


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
def test_extract_json_object_ignores_noise_around_payload(
    text: str, expected: dict[str, object]
) -> None:
    assert extract_json_object(text) == expected


def test_extract_json_object_reads_non_json_language_fence() -> None:
    raw = "```python\n" + '{"value": 1}\n' + "```"

    assert extract_json_object(raw) == {"value": 1}


def test_extract_json_object_reads_unclosed_fence() -> None:
    raw = "```json\n" + '{"value": 1}'

    assert extract_json_object(raw) == {"value": 1}


def test_extract_json_object_reads_payload_between_stray_fences() -> None:
    raw = "```\npreamble\n```\n" + '{"value": 1}\n' + "```"

    assert extract_json_object(raw) == {"value": 1}


def test_extract_json_object_rejects_output_without_an_object() -> None:
    with pytest.raises(json.JSONDecodeError, match="No JSON object found"):
        extract_json_object("No structured output")


@pytest.mark.parametrize(
    "reasoning",
    [
        "<think>Deriving \\frac{1}{2} and PE_{pos, 2i}.\n</think>",
        '<think>Consider {"draft": true} first.</think>',
        '<think>Draft:\n```json\n{"draft": true}\n```\n</think>',
        '<THINK>Formula {2i/d_model}</THINK>\n<think>{"draft": true}</think>\n',
    ],
    ids=["latex", "draft-object", "fenced-draft", "multiple-mixed-case-blocks"],
)
@pytest.mark.parametrize(
    "payload",
    [
        '{"value": 42}',
        '```json\n{"value": 42}\n```',
        '{"value": 42}\nTrailing explanation',
    ],
    ids=["bare", "fenced", "trailing-prose"],
)
def test_extract_json_object_ignores_leading_reasoning(reasoning: str, payload: str) -> None:
    assert extract_json_object(f" \n{reasoning}{payload}") == {"value": 42}


@pytest.mark.parametrize(
    "wrapper",
    [
        "{payload}",
        "```json\n{payload}\n```",
        "<think>Prepare the answer.</think>{payload}",
        "<think>Prepare the answer.</think>```json\n{payload}\n```",
    ],
    ids=["bare", "fenced", "after-reasoning", "fenced-after-reasoning"],
)
def test_extract_json_object_preserves_literal_think_tags(wrapper: str) -> None:
    expected = {"text": "a <think>b</think> c"}
    raw = wrapper.format(payload=json.dumps(expected))

    assert extract_json_object(raw) == expected


def test_extract_json_object_preserves_fenced_example_inside_valid_json() -> None:
    expected = {"example": "```json {} ```", "text": "<think>literal</think>"}

    assert extract_json_object(json.dumps(expected)) == expected


@pytest.mark.parametrize(
    "text",
    [
        '<think>{"draft": true}</think>',
        '<think>```json\n{"draft": true}\n```</think>Not a JSON answer',
        '<think>{"draft": true}</think>{"value": broken}',
    ],
    ids=["reasoning-only", "non-json-answer", "invalid-json-answer"],
)
def test_extract_json_object_does_not_fall_back_to_reasoning(text: str) -> None:
    with pytest.raises(json.JSONDecodeError, match="No JSON object found"):
        extract_json_object(text)
