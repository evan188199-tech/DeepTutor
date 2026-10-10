"""Opper chat-completions wire contract exercised through a stubbed transport.

The opper LLM binding resolves to the OpenAI-compatible gateway at
https://api.opper.ai/v3/compat. Transport stubbing validates our wire
contract, not live availability.
"""

from __future__ import annotations

import json

import httpx
from openai import AsyncOpenAI
import pytest

from deeptutor.services.config.provider_runtime import resolve_llm_runtime_config
from deeptutor.services.llm.provider_core.openai_compat_provider import (
    OpenAICompatProvider,
)
from deeptutor.services.provider_registry import find_by_name


def _catalog() -> dict:
    return {
        "version": 1,
        "services": {
            "llm": {
                "active_profile_id": "llm-p",
                "active_model_id": "llm-m",
                "profiles": [
                    {
                        "id": "llm-p",
                        "name": "Opper",
                        "binding": "opper",
                        "base_url": "",
                        "api_key": "test-opper-key",
                        "api_version": "",
                        "extra_headers": {},
                        "models": [
                            {
                                "id": "llm-m",
                                "name": "Claude Sonnet 4.6",
                                "model": "claude-sonnet-4-6",
                            }
                        ],
                    }
                ],
            },
            "embedding": {"active_profile_id": None, "active_model_id": None, "profiles": []},
            "search": {"active_profile_id": None, "profiles": []},
        },
    }


async def _provider_with_transport(handler) -> OpenAICompatProvider:
    resolved = resolve_llm_runtime_config(catalog=_catalog())
    assert resolved.provider_name == "opper"
    assert resolved.provider_mode == "gateway"
    assert resolved.model == "claude-sonnet-4-6"
    assert resolved.effective_url == "https://api.opper.ai/v3/compat"

    provider = OpenAICompatProvider(
        api_key=resolved.api_key,
        api_base=resolved.effective_url,
        default_model=resolved.model,
        spec=find_by_name("opper"),
        provider_name="opper",
        configure_env=False,
    )
    await provider.aclose()
    provider._client = AsyncOpenAI(
        api_key="test-opper-key",
        base_url="https://api.opper.ai/v3/compat",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return provider


@pytest.mark.asyncio
async def test_opper_chat_binding_posts_bare_model_to_compat_chat_completions():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-1",
                "object": "chat.completion",
                "created": 1,
                "model": "claude-sonnet-4-6",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "OK"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    provider = await _provider_with_transport(handler)
    try:
        result = await provider.chat(messages=[{"role": "user", "content": "hi"}])
    finally:
        await provider.aclose()

    assert result.content == "OK"
    assert result.finish_reason == "stop"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://api.opper.ai/v3/compat/chat/completions"
    assert request.headers["authorization"] == "Bearer test-opper-key"
    assert json.loads(request.content) == {
        "model": "claude-sonnet-4-6",
        "messages": [{"role": "user", "content": "hi"}],
        "temperature": 0.7,
        "max_tokens": 4096,
    }


@pytest.mark.asyncio
async def test_opper_chat_http_error_surfaces_provider_body_with_error_finish():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "invalid opper api key"}})

    provider = await _provider_with_transport(handler)
    try:
        result = await provider.chat(messages=[{"role": "user", "content": "hi"}])
    finally:
        await provider.aclose()

    assert result.finish_reason == "error"
    assert "invalid opper api key" in result.content


@pytest.mark.asyncio
async def test_opper_chat_timeout_surfaces_as_error_finish_reason():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectTimeout("connection timed out", request=request)

    provider = await _provider_with_transport(handler)
    try:
        result = await provider.chat(messages=[{"role": "user", "content": "hi"}])
    finally:
        await provider.aclose()

    assert calls == 1
    assert result.finish_reason == "error"
    assert "timed out" in result.content.lower()
