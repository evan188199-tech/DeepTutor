"""Idle-timeout streaming must close the SDK stream (cancel-hygiene H8).

``chat_stream`` wraps every SDK stream read in
``asyncio.wait_for(..., idle_timeout_s)``. ``wait_for`` only cancels the
pending ``__anext__``; without an explicit ``close()`` the abandoned response
holds its HTTP connection until GC, and frequent stalls can exhaust the
connection pool. These tests pin the fix: the stalled stream is closed exactly
once and never read again afterwards.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.services.llm.provider_core.azure_openai_provider import AzureOpenAIProvider
from deeptutor.services.llm.provider_core.openai_compat_provider import OpenAICompatProvider


class _StalledSDKStream:
    """SDK stream double whose reads stall until the idle timer fires.

    ``__anext__`` raises the same ``TimeoutError`` the provider's
    ``wait_for`` raises when a read exceeds ``idle_timeout_s``, so the test
    exercises the real timeout handling without idling for 90 seconds.
    """

    def __init__(self) -> None:
        self.close_calls = 0
        self.next_calls = 0

    def __aiter__(self) -> "_StalledSDKStream":
        return self

    async def __anext__(self) -> Any:
        self.next_calls += 1
        await asyncio.sleep(0)
        raise asyncio.TimeoutError()

    async def close(self) -> None:
        self.close_calls += 1


class _FinishedSDKStream:
    """SDK stream double that replays ``events`` and then ends."""

    def __init__(self, events: list[Any]) -> None:
        self._events = list(events)
        self.close_calls = 0

    def __aiter__(self) -> "_FinishedSDKStream":
        return self

    async def __anext__(self) -> Any:
        if not self._events:
            raise StopAsyncIteration
        return self._events.pop(0)

    async def close(self) -> None:
        self.close_calls += 1


def _azure_provider(stream: Any) -> AzureOpenAIProvider:
    provider = AzureOpenAIProvider(
        api_key="sk-test",
        api_base="https://res.openai.azure.com",
        default_model="gpt-4o",
    )

    async def create(**_body: Any) -> Any:
        return stream

    provider._client = SimpleNamespace(responses=SimpleNamespace(create=create))
    return provider


def _compat_provider(
    responses_stream: Any = None,
    chat_stream: Any = None,
    *,
    wire_api: str = "responses",
) -> OpenAICompatProvider:
    provider = OpenAICompatProvider(
        api_key="test-key",
        api_base="https://gateway.example/v1",
        default_model="gateway-model",
        wire_api=wire_api,
    )

    async def responses_create(**_body: Any) -> Any:
        assert responses_stream is not None
        return responses_stream

    async def chat_create(**_kwargs: Any) -> Any:
        assert chat_stream is not None
        return chat_stream

    provider._client = SimpleNamespace(
        responses=SimpleNamespace(create=responses_create),
        chat=SimpleNamespace(completions=SimpleNamespace(create=chat_create)),
    )
    return provider


def _messages() -> list[dict[str, Any]]:
    return [{"role": "user", "content": "hello"}]


@pytest.mark.asyncio
async def test_azure_chat_stream_closes_sdk_stream_on_idle_timeout() -> None:
    stalled = _StalledSDKStream()
    provider = _azure_provider(stalled)

    response = await provider.chat_stream(_messages())

    assert response.finish_reason == "error"
    assert "stalled" in (response.content or "")
    assert stalled.close_calls == 1
    # The stalled stream must not be read again after it was closed.
    await asyncio.sleep(0)
    assert stalled.next_calls == 1


@pytest.mark.asyncio
async def test_compat_responses_stream_is_closed_on_idle_timeout() -> None:
    stalled = _StalledSDKStream()
    provider = _compat_provider(responses_stream=stalled, wire_api="responses")

    response = await provider.chat_stream(_messages(), reasoning_effort="xhigh")

    assert response.finish_reason == "error"
    assert "stalled" in (response.content or "")
    assert stalled.close_calls == 1
    await asyncio.sleep(0)
    assert stalled.next_calls == 1


@pytest.mark.asyncio
async def test_compat_chat_completions_stream_is_closed_on_idle_timeout() -> None:
    stalled = _StalledSDKStream()
    provider = _compat_provider(chat_stream=stalled, wire_api="chat_completions")

    response = await provider.chat_stream(_messages())

    assert response.finish_reason == "error"
    assert "stalled" in (response.content or "")
    assert stalled.close_calls == 1
    await asyncio.sleep(0)
    assert stalled.next_calls == 1


@pytest.mark.asyncio
async def test_azure_chat_stream_closes_sdk_stream_after_normal_completion() -> None:
    finished = _FinishedSDKStream(
        [
            SimpleNamespace(type="response.output_text.delta", delta="Current answer."),
            SimpleNamespace(
                type="response.completed",
                response=SimpleNamespace(status="completed", usage=None),
            ),
        ]
    )
    provider = _azure_provider(finished)

    response = await provider.chat_stream(_messages())

    assert response.finish_reason == "stop"
    assert response.content == "Current answer."
    assert finished.close_calls == 1


@pytest.mark.asyncio
async def test_compat_responses_stream_is_closed_after_normal_completion() -> None:
    finished = _FinishedSDKStream(
        [
            SimpleNamespace(type="response.output_text.delta", delta="Current answer."),
            SimpleNamespace(
                type="response.completed",
                response=SimpleNamespace(status="completed", usage=None),
            ),
        ]
    )
    provider = _compat_provider(responses_stream=finished, wire_api="responses")

    response = await provider.chat_stream(_messages(), reasoning_effort="xhigh")

    assert response.finish_reason == "stop"
    assert response.content == "Current answer."
    assert finished.close_calls == 1


@pytest.mark.asyncio
async def test_compat_chat_completions_stream_is_closed_after_normal_completion() -> None:
    finished = _FinishedSDKStream(
        [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content="Hello",
                            reasoning_content=None,
                            reasoning=None,
                            tool_calls=[],
                        ),
                        finish_reason="stop",
                    )
                ],
                usage=None,
            ),
            SimpleNamespace(choices=[], usage=None),
        ]
    )
    provider = _compat_provider(chat_stream=finished, wire_api="chat_completions")

    response = await provider.chat_stream(_messages())

    assert response.finish_reason == "stop"
    assert response.content == "Hello"
    assert finished.close_calls == 1
