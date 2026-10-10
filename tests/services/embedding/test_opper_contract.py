"""Exercise the Opper catalog-to-HTTP path without paid provider calls.

The qualified model ID is documented at
https://opper.ai/openai/text-embedding-3-large. Transport stubbing validates
our wire contract, not live availability or whether aliases are accepted.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from deeptutor.services.config.provider_runtime import EMBEDDING_PROVIDERS
from deeptutor.services.embedding.adapters.base import (
    EmbeddingProviderError,
    EmbeddingRequest,
)
from deeptutor.services.embedding.adapters.openai_compatible import (
    OpenAICompatibleEmbeddingAdapter,
)
from deeptutor.services.embedding.client import EmbeddingClient
from deeptutor.services.embedding.config import get_embedding_config


@pytest.mark.asyncio
async def test_opper_default_embedding_posts_qualified_model_and_reads_vectors(monkeypatch):
    spec = EMBEDDING_PROVIDERS["opper"]
    profile = {
        "id": "opper-profile",
        "binding": "opper",
        "base_url": "",
        "api_key": "test-opper-key",
        "models": [
            {"id": "embedding-model", "model": spec.default_model, "dimension": spec.default_dim}
        ],
    }
    catalog = {
        "version": 1,
        "services": {
            "embedding": {
                "active_profile_id": profile["id"],
                "active_model_id": "embedding-model",
                "profiles": [profile],
            }
        },
    }
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "POST"
        assert str(request.url) == "https://api.opper.ai/v3/compat/embeddings"
        assert request.headers["Authorization"] == "Bearer test-opper-key"
        assert json.loads(request.content) == {
            "model": "openai/text-embedding-3-large",
            "input": ["first", "second"],
        }
        return httpx.Response(
            200,
            json={
                "object": "list",
                "model": "openai/text-embedding-3-large",
                "data": [
                    {"object": "embedding", "index": 0, "embedding": [0.1] * 3072},
                    {"object": "embedding", "index": 1, "embedding": [0.2] * 3072},
                ],
                "usage": {"prompt_tokens": 2, "total_tokens": 2},
            },
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    result = await EmbeddingClient(get_embedding_config(catalog=catalog)).embed(["first", "second"])
    assert result == [[0.1] * 3072, [0.2] * 3072]
    assert len(requests) == 1


def _install_transport(
    monkeypatch: pytest.MonkeyPatch, transport: httpx.AsyncBaseTransport
) -> None:
    real_client_init = httpx.AsyncClient.__init__

    def _patched_init(self: httpx.AsyncClient, *args: Any, **kwargs: Any) -> None:
        kwargs["transport"] = transport
        real_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", _patched_init)


def _opper_adapter() -> OpenAICompatibleEmbeddingAdapter:
    spec = EMBEDDING_PROVIDERS["opper"]
    return OpenAICompatibleEmbeddingAdapter(
        {
            "api_key": "test-opper-key",
            "base_url": spec.default_api_base,
            "model": spec.default_model,
            "request_timeout": 5,
        }
    )


@pytest.mark.asyncio
async def test_opper_embedding_http_error_raises_structured_provider_error(monkeypatch):
    spec = EMBEDDING_PROVIDERS["opper"]

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "invalid api key"}})

    _install_transport(monkeypatch, httpx.MockTransport(respond))

    with pytest.raises(EmbeddingProviderError) as excinfo:
        await _opper_adapter().embed(EmbeddingRequest(texts=["hello"], model=spec.default_model))

    error = excinfo.value
    assert error.status == 401
    assert error.model == spec.default_model
    assert error.url == spec.default_api_base
    assert "HTTP 401" in str(error)


@pytest.mark.asyncio
async def test_opper_embedding_persistent_rate_limit_exhausts_retry_budget(monkeypatch):
    spec = EMBEDDING_PROVIDERS["opper"]
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "0"}, request=request)

    _install_transport(monkeypatch, httpx.MockTransport(respond))
    sleeps: list[float] = []

    async def _record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", _record_sleep)

    with pytest.raises(EmbeddingProviderError) as excinfo:
        await _opper_adapter().embed(EmbeddingRequest(texts=["hello"], model=spec.default_model))

    assert excinfo.value.status == 429
    assert "rate limited" in str(excinfo.value)
    assert calls == 9
    assert sleeps == [60] * 8


@pytest.mark.asyncio
async def test_opper_embedding_connect_timeout_is_retried_then_raised(monkeypatch):
    spec = EMBEDDING_PROVIDERS["opper"]
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectTimeout("connection timed out", request=request)

    _install_transport(monkeypatch, httpx.MockTransport(respond))
    sleeps: list[float] = []

    async def _record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", _record_sleep)

    with pytest.raises(httpx.ConnectTimeout):
        await _opper_adapter().embed(EmbeddingRequest(texts=["hello"], model=spec.default_model))

    assert calls == 6
    assert sleeps == [1, 2, 4, 8, 16]


@pytest.mark.asyncio
async def test_opper_embedding_explicit_send_dimensions_writes_dimensions_param(monkeypatch):
    spec = EMBEDDING_PROVIDERS["opper"]
    profile = {
        "id": "opper-profile",
        "binding": "opper",
        "base_url": "",
        "api_key": "test-opper-key",
        "models": [
            {
                "id": "embedding-model",
                "model": spec.default_model,
                "dimension": spec.default_dim,
                "send_dimensions": True,
            }
        ],
    }
    catalog = {
        "version": 1,
        "services": {
            "embedding": {
                "active_profile_id": profile["id"],
                "active_model_id": "embedding-model",
                "profiles": [profile],
            }
        },
    }
    bodies = []

    def respond(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "object": "list",
                "model": spec.default_model,
                "data": [
                    {"object": "embedding", "index": 0, "embedding": [0.1] * 3072},
                    {"object": "embedding", "index": 1, "embedding": [0.2] * 3072},
                ],
                "usage": {"prompt_tokens": 2, "total_tokens": 2},
            },
        )

    _install_transport(monkeypatch, httpx.MockTransport(respond))
    result = await EmbeddingClient(get_embedding_config(catalog=catalog)).embed(["first", "second"])

    assert bodies == [
        {
            "model": spec.default_model,
            "input": ["first", "second"],
            "dimensions": 3072,
        }
    ]
    assert result == [[0.1] * 3072, [0.2] * 3072]
