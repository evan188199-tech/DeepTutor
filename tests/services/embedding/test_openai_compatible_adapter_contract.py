"""Contract tests for the OpenAI-compatible embedding adapter.

Fake transport only: ``httpx.AsyncClient`` is replaced (or given an in-memory
transport), no real network, no real keys. Focus: structured provider errors,
non-JSON gateways, transport-error retries, Azure-style auth header, and
response model/usage parsing — the branches not already covered by
``test_encoding_format`` / ``test_retry_after`` / ``test_send_dimensions``.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from deeptutor.services.embedding.adapters.base import (
    EmbeddingProviderError,
    EmbeddingRequest,
)
from deeptutor.services.embedding.adapters.openai_compatible import (
    OpenAICompatibleEmbeddingAdapter,
)

BASE_URL = "https://api.example.test/v1/embeddings"


def _install_transport(monkeypatch: pytest.MonkeyPatch, transport: Any) -> None:
    real_client_init = httpx.AsyncClient.__init__

    def _patched_init(self: httpx.AsyncClient, *args: Any, **kwargs: Any) -> None:
        kwargs["transport"] = transport
        real_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", _patched_init)


def _make_adapter(**overrides: Any) -> OpenAICompatibleEmbeddingAdapter:
    config: dict[str, Any] = {
        "api_key": "sk-test",
        "base_url": BASE_URL,
        "model": "bge-large",
        "request_timeout": 5,
    }
    config.update(overrides)
    return OpenAICompatibleEmbeddingAdapter(config)


class _ScriptedTransport(httpx.AsyncBaseTransport):
    """Replays scripted responses/exceptions in order."""

    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def _embedding_body(vector: list[float], **extra: Any) -> httpx.Response:
    body: dict[str, Any] = {
        "data": [{"embedding": vector}],
        "model": "bge-large",
        "usage": {"prompt_tokens": 3, "total_tokens": 3},
    }
    body.update(extra)
    return httpx.Response(200, json=body, request=httpx.Request("POST", BASE_URL))


@pytest.mark.asyncio
async def test_http_500_raises_structured_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failure branch: >=400 becomes EmbeddingProviderError with full context."""
    transport = _ScriptedTransport(
        [httpx.Response(500, text="internal error", request=httpx.Request("POST", BASE_URL))]
    )
    _install_transport(monkeypatch, transport)

    with pytest.raises(EmbeddingProviderError) as excinfo:
        await _make_adapter().embed(EmbeddingRequest(texts=["hello"], model="bge-large"))

    err = excinfo.value
    assert err.status == 500
    assert err.body == "internal error"
    assert err.model == "bge-large"
    assert err.url == BASE_URL
    assert err.provider == "openai_compat"
    assert "HTTP 500" in str(err)
    assert len(transport.requests) == 1  # non-transport errors are not retried


@pytest.mark.asyncio
async def test_html_2xx_body_raises_non_json_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failure branch: a 200 HTML page (wrong URL/gateway) is diagnosed, not parsed."""
    transport = _ScriptedTransport(
        [
            httpx.Response(
                200,
                text="<html><body>Not Found</body></html>",
                headers={"content-type": "text/html"},
                request=httpx.Request("POST", BASE_URL),
            )
        ]
    )
    _install_transport(monkeypatch, transport)

    with pytest.raises(EmbeddingProviderError, match="non-JSON response") as excinfo:
        await _make_adapter().embed(EmbeddingRequest(texts=["hello"], model="bge-large"))

    assert "HTML" in str(excinfo.value)
    assert excinfo.value.status == 200


@pytest.mark.asyncio
async def test_error_payload_on_200_raises_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failure branch: HTTP 200 with an ``{"error": ...}`` body must not parse."""
    transport = _ScriptedTransport(
        [
            httpx.Response(
                200,
                json={
                    "error": {
                        "message": "quota exceeded",
                        "code": "insufficient_quota",
                        "type": "invalid_request_error",
                    }
                },
                request=httpx.Request("POST", BASE_URL),
            )
        ]
    )
    _install_transport(monkeypatch, transport)

    with pytest.raises(ValueError, match="Embedding provider returned error payload") as excinfo:
        await _make_adapter().embed(EmbeddingRequest(texts=["hello"], model="bge-large"))
    assert "quota exceeded" in str(excinfo.value)


@pytest.mark.asyncio
async def test_transport_error_recovers_within_retry_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Transient transport errors retry with backoff, then succeed."""
    transport = _ScriptedTransport(
        [
            httpx.ConnectError("boom-1"),
            httpx.ReadTimeout("boom-2"),
            _embedding_body([0.1, 0.2]),
        ]
    )
    _install_transport(monkeypatch, transport)
    sleeps: list[float] = []

    async def _record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", _record_sleep)

    response = await _make_adapter().embed(EmbeddingRequest(texts=["hello"], model="bge-large"))

    assert response.embeddings == [[0.1, 0.2]]
    assert len(transport.requests) == 3
    # Exponential backoff: 1.0 * 2**attempt for the two failed attempts.
    assert sleeps == [1.0, 2.0]


@pytest.mark.asyncio
async def test_persistent_transport_errors_raise_after_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failure branch: once the retry budget is spent, the transport error raises."""
    transport = _ScriptedTransport([httpx.ConnectError("down")] * 10)
    _install_transport(monkeypatch, transport)

    async def _skip_sleep(delay: float) -> None:
        del delay

    monkeypatch.setattr(asyncio, "sleep", _skip_sleep)

    with pytest.raises(httpx.ConnectError):
        await _make_adapter().embed(EmbeddingRequest(texts=["hello"], model="bge-large"))

    assert len(transport.requests) == 1 + OpenAICompatibleEmbeddingAdapter._MAX_RETRIES


@pytest.mark.asyncio
async def test_response_model_falls_back_and_usage_passthrough(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parsing: missing response ``model`` falls back to the request model;
    ``usage`` is forwarded verbatim."""
    transport = _ScriptedTransport(
        [
            httpx.Response(
                200,
                json={"data": [{"embedding": [0.5, 0.6, 0.7]}]},
                request=httpx.Request("POST", BASE_URL),
            )
        ]
    )
    _install_transport(monkeypatch, transport)

    response = await _make_adapter().embed(EmbeddingRequest(texts=["hello"], model="bge-large"))

    assert response.model == "bge-large"
    assert response.dimensions == 3
    assert response.usage == {}


@pytest.mark.asyncio
async def test_azure_api_version_uses_api_key_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Auth: an ``api_version`` (Azure) switches the header to ``api-key``."""
    captured: dict[str, Any] = {}

    class _HeaderTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["headers"] = dict(request.headers)
            return _embedding_body([0.1, 0.2])

    _install_transport(monkeypatch, _HeaderTransport())

    response = await _make_adapter(
        api_key="az-key", api_version="2024-02-01", base_url=BASE_URL
    ).embed(EmbeddingRequest(texts=["hello"], model="bge-large"))

    assert response.embeddings == [[0.1, 0.2]]
    assert captured["url"] == f"{BASE_URL}?api-version=2024-02-01"
    assert captured["headers"].get("api-key") == "az-key"
    assert "authorization" not in captured["headers"]


@pytest.mark.asyncio
async def test_encoding_format_retry_payload_is_json_serializable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The outbound body stays a JSON object across attempts (transport-level
    guard for the #934 retry path)."""
    payloads: list[dict[str, Any]] = []

    class _CountingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            payloads.append(json.loads(request.content.decode("utf-8")))
            if len(payloads) == 1:
                return httpx.Response(
                    400,
                    json={"message": "encoding_format must be 'float' or 'base64', got ''"},
                    request=request,
                )
            return _embedding_body([0.1, 0.2])

    _install_transport(monkeypatch, _CountingTransport())

    response = await _make_adapter().embed(EmbeddingRequest(texts=["hello"], model="bge-large"))

    assert response.embeddings == [[0.1, 0.2]]
    assert "encoding_format" not in payloads[0]
    assert payloads[1]["encoding_format"] == "float"
    assert payloads[1]["model"] == "bge-large"
    assert payloads[1]["input"] == ["hello"]
