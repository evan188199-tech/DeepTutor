"""Failure-branch and response-parsing tests for the native Gemini adapter.

All HTTP traffic is faked through an in-memory httpx transport and
``asyncio.sleep`` is stubbed, so no network is touched and no real key is
used. Complements ``test_gemini_adapter.py``, which covers request
construction on the happy path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any

import httpx
import pytest

from deeptutor.services.embedding.adapters.base import (
    EmbeddingProviderError,
    EmbeddingRequest,
)
from deeptutor.services.embedding.adapters.gemini import GeminiEmbeddingAdapter

NATIVE_GEMINI2_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-2:batchEmbedContents"
)
NATIVE_GEMINI001_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-embedding-001:batchEmbedContents"
)


class _ScriptedTransport(httpx.AsyncBaseTransport):
    """Replay a scripted list of outcomes, one per attempted request."""

    def __init__(self, script: list[httpx.Response | Exception]) -> None:
        self.script = list(script)
        self.requests: list[dict[str, Any]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if not self.script:
            raise AssertionError("adapter issued more requests than the script allows")
        outcome = self.script.pop(0)
        self.requests.append(
            {"url": str(request.url), "json": json.loads(request.content.decode("utf-8"))}
        )
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@dataclass
class _HttpHarness:
    """Installer for scripted responses plus every timeout the adapter used."""

    timeouts: list[httpx.Timeout] = field(default_factory=list)
    transports: list[_ScriptedTransport] = field(default_factory=list)

    def install(self, script: list[httpx.Response | Exception]) -> _ScriptedTransport:
        transport = _ScriptedTransport(script)
        self.transports.append(transport)
        return transport


@pytest.fixture
def http_harness(monkeypatch: pytest.MonkeyPatch) -> _HttpHarness:
    """Route adapter HTTP calls through scripted in-memory transports."""

    harness = _HttpHarness()
    real_client_init = httpx.AsyncClient.__init__

    def _patched_init(self: httpx.AsyncClient, *args: Any, **kwargs: Any) -> None:
        if "timeout" in kwargs:
            harness.timeouts.append(kwargs["timeout"])
        kwargs["transport"] = harness.transports[-1]
        real_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", _patched_init)
    return harness


@pytest.fixture
def stub_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record retry waits instead of actually sleeping."""

    waits: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr("asyncio.sleep", _fake_sleep)
    return waits


def _adapter(
    *,
    model: str = "gemini-embedding-2",
    base_url: str = NATIVE_GEMINI2_ENDPOINT,
    dimensions: int = 768,
    request_timeout: int = 5,
) -> GeminiEmbeddingAdapter:
    return GeminiEmbeddingAdapter(
        {
            "api_key": "gemini-test-key",
            "base_url": base_url,
            "model": model,
            "dimensions": dimensions,
            "send_dimensions": None,
            "request_timeout": request_timeout,
            "extra_headers": {},
        }
    )


def _request(**kwargs: Any) -> EmbeddingRequest:
    kwargs.setdefault("texts", ["query"])
    kwargs.setdefault("model", "gemini-embedding-2")
    return EmbeddingRequest(**kwargs)


def _embeddings_body(dimension: int, count: int = 1) -> dict[str, Any]:
    return {
        "embeddings": [{"values": [0.1] * dimension} for _ in range(count)],
        "usageMetadata": {"totalTokenCount": 12},
    }


@pytest.mark.asyncio
async def test_rate_limit_honors_retry_after_header_then_succeeds(
    http_harness: _HttpHarness, stub_sleep: list[float]
) -> None:
    transport = http_harness.install(
        [
            # Only a Retry-After longer than the exponential backoff wins,
            # because the adapter waits for max(retry_after, backoff).
            httpx.Response(429, json={}, headers={"Retry-After": "30"}),
            httpx.Response(200, json=_embeddings_body(768)),
        ]
    )

    response = await _adapter().embed(_request(dimensions=768))

    assert len(transport.requests) == 2
    assert stub_sleep == [30.0]
    assert response.embeddings == [[0.1] * 768]
    assert response.usage == {"totalTokenCount": 12}


@pytest.mark.asyncio
async def test_rate_limit_without_valid_retry_after_uses_backoff(
    http_harness: _HttpHarness, stub_sleep: list[float]
) -> None:
    transport = http_harness.install(
        [
            httpx.Response(429, json={}, headers={"Retry-After": "soon"}),
            httpx.Response(429, json={}),
            httpx.Response(200, json=_embeddings_body(768)),
        ]
    )

    response = await _adapter().embed(_request(dimensions=768))

    assert len(transport.requests) == 3
    assert stub_sleep == [5.0, 10.0]
    assert response.model == "gemini-embedding-2"


@pytest.mark.asyncio
async def test_exhausted_rate_limit_retries_raise_provider_error(
    http_harness: _HttpHarness, stub_sleep: list[float]
) -> None:
    transport = http_harness.install(
        [httpx.Response(429, json={}, headers={"Retry-After": "1"}) for _ in range(3)]
    )
    adapter = _adapter()
    adapter._MAX_RETRIES = 2

    with pytest.raises(EmbeddingProviderError) as caught:
        await adapter.embed(_request())

    # Three attempts, and the final 429 also records its backoff before the
    # for/else raises the carried provider error.
    assert len(transport.requests) == 3
    assert stub_sleep == [5.0, 10.0, 20.0]
    assert caught.value.status == 429
    assert caught.value.provider == "gemini"


@pytest.mark.asyncio
async def test_transport_error_is_retried_then_succeeds(
    http_harness: _HttpHarness, stub_sleep: list[float]
) -> None:
    transport = http_harness.install(
        [
            httpx.ConnectError("connection reset"),
            httpx.Response(200, json=_embeddings_body(768)),
        ]
    )
    adapter = _adapter()
    adapter._MAX_RETRIES = 1

    response = await adapter.embed(_request())

    assert len(transport.requests) == 2
    assert stub_sleep == [1.0]
    assert response.embeddings == [[0.1] * 768]


@pytest.mark.asyncio
async def test_transport_error_after_exhausted_retries_raises_provider_error(
    http_harness: _HttpHarness, stub_sleep: list[float]
) -> None:
    transport = http_harness.install([httpx.ReadTimeout("timed out") for _ in range(2)])
    adapter = _adapter()
    adapter._MAX_RETRIES = 1

    with pytest.raises(EmbeddingProviderError, match="transport error") as caught:
        await adapter.embed(_request())

    assert len(transport.requests) == 2
    assert len(stub_sleep) == 1
    assert caught.value.status is None
    assert caught.value.__cause__ is None


@pytest.mark.asyncio
async def test_non_json_success_response_raises_provider_error(http_harness: _HttpHarness) -> None:
    http_harness.install([httpx.Response(200, text="<html>gateway error</html>")])

    with pytest.raises(EmbeddingProviderError, match="non-JSON") as caught:
        await _adapter().embed(_request())

    assert caught.value.status == 200
    assert "gemini-test-key" not in str(caught.value)


@pytest.mark.asyncio
async def test_missing_embeddings_list_raises_value_error(http_harness: _HttpHarness) -> None:
    http_harness.install([httpx.Response(200, json={})])

    with pytest.raises(ValueError, match="missing the `embeddings` list"):
        await _adapter().embed(_request())


@pytest.mark.asyncio
async def test_response_count_mismatch_raises_value_error(http_harness: _HttpHarness) -> None:
    http_harness.install([httpx.Response(200, json=_embeddings_body(768, count=1))])

    with pytest.raises(ValueError, match="count does not match"):
        await _adapter().embed(_request(texts=["one", "two"]))


@pytest.mark.asyncio
async def test_unusable_vectors_raise_value_error(http_harness: _HttpHarness) -> None:
    http_harness.install([httpx.Response(200, json={"embeddings": [{"values": []}]})])

    with pytest.raises(ValueError, match="no usable vectors"):
        await _adapter().embed(_request())


@pytest.mark.asyncio
async def test_truncated_001_vectors_are_l2_normalized(http_harness: _HttpHarness) -> None:
    transport = http_harness.install(
        [httpx.Response(200, json={"embeddings": [{"values": [3.0, 4.0]}]})]
    )

    response = await _adapter(
        model="gemini-embedding-001", base_url=NATIVE_GEMINI001_ENDPOINT, dimensions=768
    ).embed(_request(model="gemini-embedding-001", dimensions=768))

    assert transport.requests[0]["json"]["requests"][0]["model"] == "models/gemini-embedding-001"
    assert response.embeddings == [[0.6, 0.8]]
    assert response.dimensions == 2


@pytest.mark.asyncio
async def test_read_timeout_floor_is_enforced_in_client_config(
    http_harness: _HttpHarness,
) -> None:
    http_harness.install([httpx.Response(200, json=_embeddings_body(768))])

    await _adapter(request_timeout=5).embed(_request())

    (timeout,) = http_harness.timeouts
    assert timeout.connect == 10.0
    assert timeout.read == 60.0
    assert timeout.write == 10.0
    assert timeout.pool == 10.0
