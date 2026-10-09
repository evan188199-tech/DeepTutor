"""The project's one rule for a structured call a reasoning model starved.

A reasoning model pays for hidden tokens out of the same ``max_tokens`` as its
answer, so a one-shot structured call can come back empty with no error —
Book's spine collapsing to a single "Overview" chapter (#1316), the quiz plan
emitting zero templates (#1318), a research topic decomposing to one
sub-topic. The remedy is always the same: ask again with thinking turned down.

These tests pin the two things that make it safe to share: the retry actually
happens, and deciding "the model answered" stays with the caller.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from deeptutor.services.llm.reasoning_params import RETRY_REASONING_EFFORT
from deeptutor.services.llm.structured_retry import (
    json_payload_is_usable,
    json_with_reasoning_retry,
    payload_with_reasoning_retry,
)


def _recorder(*responses: str):
    """A ``run`` that returns the given bodies in order, logging the effort."""
    efforts: list[str | None] = []
    remaining = list(responses)

    async def run(reasoning_effort: str | None) -> str:
        efforts.append(reasoning_effort)
        return remaining.pop(0) if remaining else ""

    return run, efforts


@pytest.mark.asyncio
async def test_a_usable_first_answer_is_not_paid_for_twice() -> None:
    run, efforts = _recorder('{"spine": [1]}')
    result = await json_with_reasoning_retry(run, expected_key="spine")
    assert result == {"spine": [1]}
    assert efforts == [None], "a good answer must not trigger a second call"


@pytest.mark.asyncio
async def test_a_starved_answer_is_retried_with_thinking_turned_down() -> None:
    run, efforts = _recorder("", '{"spine": [1]}')
    result = await json_with_reasoning_retry(run, expected_key="spine")
    assert result == {"spine": [1]}
    assert efforts == [None, RETRY_REASONING_EFFORT]


@pytest.mark.asyncio
async def test_the_expected_key_is_what_counts_as_answered() -> None:
    """A well-formed object missing the key is still a starved answer.

    This is the #1316 shape exactly: valid JSON, no content, and a caller that
    would have degraded silently.
    """
    run, efforts = _recorder('{"notes": "thinking..."}', '{"spine": [1]}')
    result = await json_with_reasoning_retry(run, expected_key="spine")
    assert result == {"spine": [1]}
    assert efforts == [None, RETRY_REASONING_EFFORT]


@pytest.mark.asyncio
async def test_two_starved_attempts_return_the_callers_empty_fallback() -> None:
    run, _ = _recorder("", "")
    assert await json_with_reasoning_retry(run, expected_key="spine") == {}


@pytest.mark.asyncio
async def test_the_object_shaped_helper_never_hands_back_a_list() -> None:
    """Callers of the object form index the result, so it must be a dict."""
    run, _ = _recorder("[1, 2, 3]", "[4]")
    assert await json_with_reasoning_retry(run, expected_key=None) == {}


@pytest.mark.asyncio
async def test_a_caller_that_accepts_an_array_keeps_its_array() -> None:
    """The generic form must not impose the object shape on everyone.

    Research's decompose accepts a bare array of sub-topics. Judging that
    "unusable" would retry a perfectly good answer and then discard it — a
    regression the object-shaped helper would have caused if it were the only
    entry point.
    """

    def accepts_anything_non_empty(payload: Any) -> bool:
        return bool(payload)

    run, efforts = _recorder("[1, 2, 3]")
    result = await payload_with_reasoning_retry(run, is_usable=accepts_anything_non_empty)
    assert result == [1, 2, 3]
    assert efforts == [None]


@pytest.mark.asyncio
async def test_nothing_usable_and_nothing_non_empty_is_none() -> None:
    run, _ = _recorder("", "")
    assert await payload_with_reasoning_retry(run, is_usable=bool) is None


@pytest.mark.parametrize(
    ("payload", "expected_key", "usable"),
    [
        ({"spine": [1]}, "spine", True),
        ({"spine": []}, "spine", False),
        ({}, None, False),
        ({"anything": 1}, None, True),
        ([1], None, False),
        ("not json", None, False),
    ],
)
def test_object_usability_rule(payload: Any, expected_key: str | None, usable: bool) -> None:
    assert json_payload_is_usable(payload, expected_key) is usable


# --- Degradation branches: malformed bodies, transport errors, fallback order ---
#
# A starved call rarely comes back as a clean empty string. The provider may
# return reasoning prose with no JSON in it, a body cut off mid-object, or no
# body at all because the request timed out or the key hit its rate limit.
# These tests pin how the one rule degrades in each of those shapes.


@pytest.mark.asyncio
async def test_prose_without_json_is_retried_and_the_retry_answers() -> None:
    """Reasoning prose that never reaches the JSON is the #1316 body shape."""
    run, efforts = _recorder("Thinking about the book structure...", '{"spine": ["Overview"]}')
    result = await json_with_reasoning_retry(run, expected_key="spine")
    assert result == {"spine": ["Overview"]}
    assert efforts == [None, RETRY_REASONING_EFFORT]


@pytest.mark.asyncio
async def test_both_attempts_malformed_return_the_empty_fallback() -> None:
    run, efforts = _recorder("no json here at all", "```json\nnot even json\n```")
    result = await json_with_reasoning_retry(run, expected_key="spine")
    assert result == {}
    assert efforts == [None, RETRY_REASONING_EFFORT]


@pytest.mark.asyncio
async def test_timeout_on_the_first_attempt_propagates_without_a_retry() -> None:
    """A transport failure is not a starved answer — it must stay visible."""

    calls: list[str | None] = []

    async def run(reasoning_effort: str | None) -> str:
        calls.append(reasoning_effort)
        raise TimeoutError("provider timed out")

    with pytest.raises(TimeoutError):
        await json_with_reasoning_retry(run, expected_key="spine")
    assert calls == [None], "an exception must not be retried or swallowed"


class _ProviderRateLimited(RuntimeError):
    """Stand-in for a provider rate-limit error, like the real 429 paths."""


@pytest.mark.asyncio
async def test_rate_limit_on_the_first_attempt_propagates_without_a_retry() -> None:
    calls: list[str | None] = []

    async def run(reasoning_effort: str | None) -> str:
        calls.append(reasoning_effort)
        raise _ProviderRateLimited("429 too many requests")

    with pytest.raises(_ProviderRateLimited):
        await payload_with_reasoning_retry(run, is_usable=lambda value: bool(value))
    assert calls == [None]


@pytest.mark.asyncio
async def test_two_unusable_but_non_empty_attempts_keep_the_first() -> None:
    """When both attempts answered something, the first one is what returns."""
    run, efforts = _recorder('{"notes": "half a thought"}', '{"other": 1}')
    result = await payload_with_reasoning_retry(
        run,
        is_usable=lambda value: json_payload_is_usable(value, "spine"),
    )
    assert result == {"notes": "half a thought"}
    assert efforts == [None, RETRY_REASONING_EFFORT]


@pytest.mark.asyncio
async def test_a_generic_retry_that_never_succeeds_returns_the_first_body() -> None:
    run, _ = _recorder("[1, 2]", "just prose")
    result = await payload_with_reasoning_retry(run, is_usable=lambda value: False)
    assert result == [1, 2]


@pytest.mark.asyncio
async def test_retry_runs_at_most_twice() -> None:
    """The rule is one retry, not a loop — a hopeless call stops paying."""
    run, efforts = _recorder("", "", "")
    assert await json_with_reasoning_retry(run, expected_key="spine") == {}
    assert efforts == [None, RETRY_REASONING_EFFORT]


@pytest.mark.asyncio
async def test_the_callers_logger_reaches_the_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    import deeptutor.services.llm.structured_retry as structured_retry

    seen: list[Any] = []
    original = structured_retry.parse_json_response

    def spy(response: str, logger_instance: Any = None, fallback: Any = None) -> Any:
        seen.append(logger_instance)
        return original(response, logger_instance=logger_instance, fallback=fallback)

    monkeypatch.setattr(structured_retry, "parse_json_response", spy)
    logger = logging.getLogger("structured-retry-test")
    run, _ = _recorder("", '{"spine": [1]}')
    await payload_with_reasoning_retry(
        run, is_usable=lambda value: bool(value), logger_instance=logger
    )
    assert seen == [logger, logger]


@pytest.mark.parametrize(
    ("payload", "expected_key", "usable"),
    [
        ({"spine": {"nested": 1}}, "spine", True),
        ({"spine": "text"}, "spine", True),
        ({"spine": ""}, "spine", False),
        ({"spine": 0}, "spine", False),
        ({"spine": None}, "spine", False),
        (None, "spine", False),
        (3, "spine", False),
    ],
)
def test_falsy_expected_key_values_are_not_answers(
    payload: Any, expected_key: str | None, usable: bool
) -> None:
    assert json_payload_is_usable(payload, expected_key) is usable


@pytest.mark.asyncio
async def test_expected_key_none_accepts_any_non_empty_object() -> None:
    run, efforts = _recorder('{"anything": [1]}')
    result = await json_with_reasoning_retry(run, expected_key=None)
    assert result == {"anything": [1]}
    assert efforts == [None]
