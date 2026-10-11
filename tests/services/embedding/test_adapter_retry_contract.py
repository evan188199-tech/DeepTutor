"""Bounded-retry + redaction contract tests for the raw-httpx/DashScope adapters.

Companion to ``test_retry_after.py`` (OpenAI-compatible rate limits). Every
transport here is fake — no adapter under test reaches a real network.

Contract (per scan M-2/M-3/M-4/L-1, log-body P1#1/#2):
* 429/5xx and transport failures are retried with bounded attempts and
  exponential backoff (``adapters/retry.py``);
* a server ``Retry-After`` is honored (capped);
* exhausted retries preserve each adapter's error surface;
* error logs never contain the provider response body.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import types
from typing import Any

import httpx
import pytest

from deeptutor.services.embedding.adapters.base import EmbeddingRequest
from deeptutor.services.embedding.adapters.cohere import CohereEmbeddingAdapter
from deeptutor.services.embedding.adapters.dashscope_native import (
    DashScopeMultiModalEmbeddingAdapter,
)
from deeptutor.services.embedding.adapters.jina import JinaEmbeddingAdapter
from deeptutor.services.embedding.adapters.ollama import OllamaEmbeddingAdapter
from deeptutor.services.embedding.adapters.retry import MAX_RETRIES

_BODY_MARKER = "TOP-SECRET-PROVIDER-BODY-MARKER"

_COHERE_OK = {"embeddings": [[0.1, 0.2]], "model": "embed-english-v3.0"}
_JINA_OK = {"data": [{"embedding": [0.1, 0.2]}], "model": "jina-embeddings-v3"}
_OLLAMA_OK = {"embeddings": [[0.1, 0.2]], "model": "nomic-embed-text"}


def _ok(payload: dict[str, Any]):
    def _make(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    return _make


def _status(
    status_code: int,
    *,
    retry_after: str | None = None,
    body: str = _BODY_MARKER,
):
    headers = {"Retry-After": retry_after} if retry_after is not None else {}

    def _make(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, headers=headers, text=body, request=request)

    return _make


def _connect_error(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


class _ScriptedTransport(httpx.AsyncBaseTransport):
    """Serve scripted responses/exceptions; the last script entry repeats."""

    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.calls = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        index = min(self.calls, len(self.script)) - 1
        outcome = self.script[index]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome(request)


def _install_transport(
    monkeypatch: pytest.MonkeyPatch,
    transport: httpx.AsyncBaseTransport,
) -> dict[str, Any]:
    """Force every new ``httpx.AsyncClient`` onto *transport*; capture kwargs."""
    captured: dict[str, Any] = {}
    real_client_init = httpx.AsyncClient.__init__

    def _patched_init(self: httpx.AsyncClient, *args: Any, **kwargs: Any) -> None:
        captured["timeout"] = kwargs.get("timeout")
        kwargs["transport"] = transport
        real_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", _patched_init)
    return captured


def _record_sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    sleeps: list[float] = []

    async def _record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", _record_sleep)
    return sleeps


def _cohere_adapter() -> CohereEmbeddingAdapter:
    return CohereEmbeddingAdapter(
        {
            "api_key": "sk-test",
            "base_url": "https://api.cohere.test/v1/embed",
            "model": "embed-english-v3.0",
            "api_version": "v1",
            "request_timeout": 5,
        }
    )


def _jina_adapter() -> JinaEmbeddingAdapter:
    return JinaEmbeddingAdapter(
        {
            "api_key": "sk-test",
            "base_url": "https://api.jina.test/v1/embeddings",
            "model": "jina-embeddings-v3",
            "request_timeout": 5,
        }
    )


def _ollama_adapter() -> OllamaEmbeddingAdapter:
    return OllamaEmbeddingAdapter(
        {
            "api_key": "",
            "base_url": "https://ollama.test/api/embeddings",
            "model": "nomic-embed-text",
            "request_timeout": 5,
        }
    )


def _request(model: str) -> EmbeddingRequest:
    return EmbeddingRequest(texts=["hello"], model=model)


def _assert_no_body_logged(caplog: pytest.LogCaptureFixture) -> None:
    messages = [record.getMessage() for record in caplog.records]
    assert messages, "expected at least one retry/failure log record"
    for message in messages:
        assert _BODY_MARKER not in message
        assert "response body" not in message.lower()


# --------------------------------------------------------------------------
# Cohere
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cohere_retries_429_respecting_retry_after_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _ScriptedTransport([_status(429, retry_after="3"), _ok(_COHERE_OK)])
    _install_transport(monkeypatch, transport)
    sleeps = _record_sleeps(monkeypatch)

    result = await _cohere_adapter().embed(_request("embed-english-v3.0"))

    assert result.embeddings == [[0.1, 0.2]]
    assert transport.calls == 2
    assert sleeps == [3.0]


@pytest.mark.asyncio
async def test_cohere_retries_5xx_with_exponential_backoff_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _ScriptedTransport([_status(503), _status(500), _ok(_COHERE_OK)])
    _install_transport(monkeypatch, transport)
    sleeps = _record_sleeps(monkeypatch)

    result = await _cohere_adapter().embed(_request("embed-english-v3.0"))

    assert result.embeddings == [[0.1, 0.2]]
    assert transport.calls == 3
    assert sleeps == [1.0, 2.0]


@pytest.mark.asyncio
async def test_cohere_retries_transport_error_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _ScriptedTransport([_connect_error, _ok(_COHERE_OK)])
    _install_transport(monkeypatch, transport)
    sleeps = _record_sleeps(monkeypatch)

    result = await _cohere_adapter().embed(_request("embed-english-v3.0"))

    assert result.embeddings == [[0.1, 0.2]]
    assert transport.calls == 2
    assert sleeps == [1.0]


@pytest.mark.asyncio
async def test_cohere_429_bounded_final_failure_without_body_logging(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    transport = _ScriptedTransport([_status(429, body=_BODY_MARKER)])
    _install_transport(monkeypatch, transport)
    sleeps = _record_sleeps(monkeypatch)

    with pytest.raises(httpx.HTTPStatusError):
        await _cohere_adapter().embed(_request("embed-english-v3.0"))

    assert transport.calls == 1 + MAX_RETRIES
    assert sleeps == [1.0, 2.0, 4.0]
    _assert_no_body_logged(caplog)


@pytest.mark.asyncio
async def test_cohere_non_retryable_status_fails_fast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _ScriptedTransport([_status(401)])
    _install_transport(monkeypatch, transport)
    sleeps = _record_sleeps(monkeypatch)

    with pytest.raises(httpx.HTTPStatusError):
        await _cohere_adapter().embed(_request("embed-english-v3.0"))

    assert transport.calls == 1
    assert sleeps == []


# --------------------------------------------------------------------------
# Jina
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jina_retries_429_respecting_retry_after_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _ScriptedTransport([_status(429, retry_after="2"), _ok(_JINA_OK)])
    _install_transport(monkeypatch, transport)
    sleeps = _record_sleeps(monkeypatch)

    result = await _jina_adapter().embed(_request("jina-embeddings-v3"))

    assert result.embeddings == [[0.1, 0.2]]
    assert transport.calls == 2
    assert sleeps == [2.0]


@pytest.mark.asyncio
async def test_jina_retries_transport_error_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _ScriptedTransport([_connect_error, _ok(_JINA_OK)])
    _install_transport(monkeypatch, transport)
    sleeps = _record_sleeps(monkeypatch)

    result = await _jina_adapter().embed(_request("jina-embeddings-v3"))

    assert result.embeddings == [[0.1, 0.2]]
    assert transport.calls == 2
    assert sleeps == [1.0]


@pytest.mark.asyncio
async def test_jina_429_bounded_final_failure_without_body_logging(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    transport = _ScriptedTransport([_status(429, body=_BODY_MARKER)])
    _install_transport(monkeypatch, transport)
    sleeps = _record_sleeps(monkeypatch)

    with pytest.raises(httpx.HTTPStatusError):
        await _jina_adapter().embed(_request("jina-embeddings-v3"))

    assert transport.calls == 1 + MAX_RETRIES
    assert sleeps == [1.0, 2.0, 4.0]
    _assert_no_body_logged(caplog)


# --------------------------------------------------------------------------
# Ollama
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ollama_retries_connect_error_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _ScriptedTransport([_connect_error, _ok(_OLLAMA_OK)])
    _install_transport(monkeypatch, transport)
    sleeps = _record_sleeps(monkeypatch)

    result = await _ollama_adapter().embed(_request("nomic-embed-text"))

    assert result.embeddings == [[0.1, 0.2]]
    assert transport.calls == 2
    assert sleeps == [1.0]


@pytest.mark.asyncio
async def test_ollama_connect_error_bounded_final_failure_translated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _ScriptedTransport([_connect_error])
    _install_transport(monkeypatch, transport)
    sleeps = _record_sleeps(monkeypatch)

    with pytest.raises(ConnectionError, match="Cannot connect to Ollama"):
        await _ollama_adapter().embed(_request("nomic-embed-text"))

    assert transport.calls == 1 + MAX_RETRIES
    assert sleeps == [1.0, 2.0, 4.0]


@pytest.mark.asyncio
async def test_ollama_retries_503_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _ScriptedTransport([_status(503), _ok(_OLLAMA_OK)])
    _install_transport(monkeypatch, transport)
    sleeps = _record_sleeps(monkeypatch)

    result = await _ollama_adapter().embed(_request("nomic-embed-text"))

    assert result.embeddings == [[0.1, 0.2]]
    assert transport.calls == 2
    assert sleeps == [1.0]


@pytest.mark.asyncio
async def test_ollama_404_model_missing_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _tags(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": "llama3"}]}, request=request)

    transport = _ScriptedTransport([_status(404), _tags])
    _install_transport(monkeypatch, transport)
    sleeps = _record_sleeps(monkeypatch)

    with pytest.raises(ValueError, match="not found in Ollama.*llama3"):
        await _ollama_adapter().embed(_request("nomic-embed-text"))

    # One POST + one /api/tags health probe — the 404 is terminal, not retried.
    assert transport.calls == 2
    assert sleeps == []


@pytest.mark.asyncio
async def test_ollama_splits_connect_and_read_timeouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _ScriptedTransport([_ok(_OLLAMA_OK)])
    captured = _install_transport(monkeypatch, transport)
    _record_sleeps(monkeypatch)

    await _ollama_adapter().embed(_request("nomic-embed-text"))

    timeout = captured["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == 10.0
    assert timeout.read == 60.0
    assert timeout.write == 10.0


# --------------------------------------------------------------------------
# DashScope (SDK in a worker thread)
# --------------------------------------------------------------------------


class _FakeDashScopeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        output: dict | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.output = output if output is not None else {"embeddings": []}
        self.usage = {}
        self.code = ""
        self.message = ""
        self.request_id = "req-1"
        self.headers = headers or {}


_DASHSCOPE_OK = _FakeDashScopeResponse(
    output={"embeddings": [{"index": 0, "embedding": [0.1, 0.2]}]}
)


def _install_scripted_dashscope(
    monkeypatch: pytest.MonkeyPatch, outcomes: list[Any]
) -> dict[str, int]:
    """Stub the dashscope SDK with a scripted sync ``call``; count invocations."""
    calls = {"n": 0}

    def fake_call(**_kwargs: Any) -> Any:
        calls["n"] += 1
        index = min(calls["n"], len(outcomes)) - 1
        outcome = outcomes[index]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    fake_module = types.SimpleNamespace(
        MultiModalEmbedding=types.SimpleNamespace(call=fake_call),
        TextEmbedding=types.SimpleNamespace(call=fake_call),
    )
    monkeypatch.setitem(sys.modules, "dashscope", fake_module)
    return calls


def _dashscope_adapter() -> DashScopeMultiModalEmbeddingAdapter:
    return DashScopeMultiModalEmbeddingAdapter(
        {
            "api_key": "sk-dashscope",
            "base_url": "https://dashscope.aliyuncs.com/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding",
            "model": "qwen3-vl-embedding",
            "dimensions": 0,
            "request_timeout": 5,
        }
    )


@pytest.mark.asyncio
async def test_dashscope_retries_429_status_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    throttled = _FakeDashScopeResponse(status_code=429, headers={"Retry-After": "2"})
    calls = _install_scripted_dashscope(monkeypatch, [throttled, throttled, _DASHSCOPE_OK])
    sleeps = _record_sleeps(monkeypatch)

    result = await _dashscope_adapter().embed(_request("qwen3-vl-embedding"))

    assert result.embeddings == [[0.1, 0.2]]
    assert calls["n"] == 3
    assert sleeps == [2.0, 2.0]


@pytest.mark.asyncio
async def test_dashscope_429_bounded_final_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_scripted_dashscope(monkeypatch, [_FakeDashScopeResponse(status_code=429)])
    sleeps = _record_sleeps(monkeypatch)

    with pytest.raises(RuntimeError, match="status=429"):
        await _dashscope_adapter().embed(_request("qwen3-vl-embedding"))

    assert calls["n"] == 1 + MAX_RETRIES
    assert sleeps == [1.0, 2.0, 4.0]


@pytest.mark.asyncio
async def test_dashscope_retries_transport_exception_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_scripted_dashscope(
        monkeypatch, [ConnectionError("socket closed"), _DASHSCOPE_OK]
    )
    sleeps = _record_sleeps(monkeypatch)

    result = await _dashscope_adapter().embed(_request("qwen3-vl-embedding"))

    assert result.embeddings == [[0.1, 0.2]]
    assert calls["n"] == 2
    assert sleeps == [1.0]


@pytest.mark.asyncio
async def test_dashscope_400_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_scripted_dashscope(monkeypatch, [_FakeDashScopeResponse(status_code=400)])
    sleeps = _record_sleeps(monkeypatch)

    with pytest.raises(RuntimeError, match="status=400"):
        await _dashscope_adapter().embed(_request("qwen3-vl-embedding"))

    assert calls["n"] == 1
    assert sleeps == []
