"""Configurable 429 backoff coverage for OpenAI-compatible embeddings.

The two previously hardcoded waits in the adapter's 429 branch — the
``max(retry_after, 60)`` floor and the 65s all-keys-cooling wait — come from
runtime settings now (``system.json`` + ``DEEPTUTOR_EMBEDDING_*`` process-env
overrides), each clamped to an upper bound, and both gain uniform jitter so
concurrent workers that hit the same 429 no longer sleep and retry in
lockstep. Defaults reproduce the old 60s/65s cadence (plus jitter).
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from deeptutor.services.config import get_embedding_rate_limit_backoff
from deeptutor.services.embedding.adapters.base import EmbeddingRequest
from deeptutor.services.embedding.adapters.openai_compatible import (
    OpenAICompatibleEmbeddingAdapter,
)

_BACKOFF_ENV_KEYS = (
    "DEEPTUTOR_EMBEDDING_429_BACKOFF_FLOOR_SECONDS",
    "DEEPTUTOR_EMBEDDING_429_BACKOFF_JITTER_SECONDS",
    "DEEPTUTOR_EMBEDDING_KEY_COOLDOWN_WAIT_SECONDS",
)


@pytest.fixture(autouse=True)
def _clear_backoff_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _BACKOFF_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


class _RateLimitedTransport(httpx.AsyncBaseTransport):
    """Return 429s (optionally with Retry-After) before a success response."""

    def __init__(self, *, succeed_after: int | None, retry_after: str | None = None) -> None:
        self.succeed_after = succeed_after
        self.retry_after = retry_after
        self.calls = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.succeed_after is None or self.calls <= self.succeed_after:
            headers = {"Retry-After": self.retry_after} if self.retry_after else {}
            return httpx.Response(429, headers=headers, request=request)
        return httpx.Response(
            200,
            json={"data": [{"embedding": [0.1, 0.2]}], "model": "test-model"},
            request=request,
        )


class _CoolingThenReadyPool:
    """Key-pool stand-in: refetch inside the 429 branch finds every key cooling.

    The first ``next()`` serves the initial request; the refetch after the
    backoff sleep raises (all keys cooling), which is the branch that waits
    out the KeyPool cooldown; the fetch after that wait succeeds.
    """

    def __init__(self) -> None:
        self._calls = 0

    def mark_429(self, key: str) -> None:
        return None

    def next(self) -> str:
        self._calls += 1
        if self._calls == 2:
            raise RuntimeError("all keys cooling down")
        return "sk-test"


def _install_transport(
    monkeypatch: pytest.MonkeyPatch,
    transport: httpx.AsyncBaseTransport,
) -> None:
    real_client_init = httpx.AsyncClient.__init__

    def _patched_init(self: httpx.AsyncClient, *args: Any, **kwargs: Any) -> None:
        kwargs["transport"] = transport
        real_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", _patched_init)


def _make_adapter() -> OpenAICompatibleEmbeddingAdapter:
    return OpenAICompatibleEmbeddingAdapter(
        {
            "api_key": "sk-test",
            "base_url": "https://api.example.test/v1/embeddings",
            "model": "test-model",
            "request_timeout": 5,
        }
    )


def _record_sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    sleeps: list[float] = []

    async def _record(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", _record)
    return sleeps


@pytest.mark.asyncio
async def test_default_policy_keeps_floor_and_cooldown_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _RateLimitedTransport(succeed_after=1, retry_after="not-a-delay")
    _install_transport(monkeypatch, transport)
    sleeps = _record_sleeps(monkeypatch)

    await _make_adapter().embed(EmbeddingRequest(texts=["hello"], model="test-model"))

    policy = get_embedding_rate_limit_backoff()
    assert (policy.floor, policy.key_cooldown_wait) == (60, 65)
    assert len(sleeps) == 1
    assert policy.floor <= sleeps[0] <= policy.floor + policy.jitter
    assert policy.jitter > 0  # lockstep retries are de-synced by default


@pytest.mark.asyncio
async def test_backoff_floor_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPTUTOR_EMBEDDING_429_BACKOFF_FLOOR_SECONDS", "120")
    monkeypatch.setenv("DEEPTUTOR_EMBEDDING_429_BACKOFF_JITTER_SECONDS", "0")
    transport = _RateLimitedTransport(succeed_after=1, retry_after="not-a-delay")
    _install_transport(monkeypatch, transport)
    sleeps = _record_sleeps(monkeypatch)

    await _make_adapter().embed(EmbeddingRequest(texts=["hello"], model="test-model"))

    assert sleeps == [120]


@pytest.mark.asyncio
async def test_backoff_floor_env_clamped_to_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPTUTOR_EMBEDDING_429_BACKOFF_FLOOR_SECONDS", "999999")
    monkeypatch.setenv("DEEPTUTOR_EMBEDDING_429_BACKOFF_JITTER_SECONDS", "0")
    transport = _RateLimitedTransport(succeed_after=1, retry_after="not-a-delay")
    _install_transport(monkeypatch, transport)
    sleeps = _record_sleeps(monkeypatch)

    await _make_adapter().embed(EmbeddingRequest(texts=["hello"], model="test-model"))

    assert sleeps == [3600]


@pytest.mark.asyncio
async def test_retry_after_beats_configured_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPTUTOR_EMBEDDING_429_BACKOFF_FLOOR_SECONDS", "120")
    monkeypatch.setenv("DEEPTUTOR_EMBEDDING_429_BACKOFF_JITTER_SECONDS", "0")
    transport = _RateLimitedTransport(succeed_after=1, retry_after="200")
    _install_transport(monkeypatch, transport)
    sleeps = _record_sleeps(monkeypatch)

    await _make_adapter().embed(EmbeddingRequest(texts=["hello"], model="test-model"))

    assert sleeps == [200]


@pytest.mark.asyncio
async def test_key_cooldown_wait_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPTUTOR_EMBEDDING_429_BACKOFF_FLOOR_SECONDS", "120")
    monkeypatch.setenv("DEEPTUTOR_EMBEDDING_429_BACKOFF_JITTER_SECONDS", "0")
    monkeypatch.setenv("DEEPTUTOR_EMBEDDING_KEY_COOLDOWN_WAIT_SECONDS", "130")
    transport = _RateLimitedTransport(succeed_after=1, retry_after="not-a-delay")
    _install_transport(monkeypatch, transport)
    sleeps = _record_sleeps(monkeypatch)
    adapter = _make_adapter()
    adapter._key_pool = _CoolingThenReadyPool()

    await adapter.embed(EmbeddingRequest(texts=["hello"], model="test-model"))

    assert sleeps == [120, 130]


@pytest.mark.asyncio
async def test_key_cooldown_wait_env_clamped_to_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPTUTOR_EMBEDDING_429_BACKOFF_FLOOR_SECONDS", "120")
    monkeypatch.setenv("DEEPTUTOR_EMBEDDING_429_BACKOFF_JITTER_SECONDS", "0")
    monkeypatch.setenv("DEEPTUTOR_EMBEDDING_KEY_COOLDOWN_WAIT_SECONDS", "999999")
    transport = _RateLimitedTransport(succeed_after=1, retry_after="not-a-delay")
    _install_transport(monkeypatch, transport)
    sleeps = _record_sleeps(monkeypatch)
    adapter = _make_adapter()
    adapter._key_pool = _CoolingThenReadyPool()

    await adapter.embed(EmbeddingRequest(texts=["hello"], model="test-model"))

    assert sleeps == [120, 3600]


@pytest.mark.asyncio
async def test_jitter_keeps_both_waits_within_configured_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPTUTOR_EMBEDDING_429_BACKOFF_FLOOR_SECONDS", "120")
    monkeypatch.setenv("DEEPTUTOR_EMBEDDING_429_BACKOFF_JITTER_SECONDS", "10")
    monkeypatch.setenv("DEEPTUTOR_EMBEDDING_KEY_COOLDOWN_WAIT_SECONDS", "130")
    transport = _RateLimitedTransport(succeed_after=1, retry_after="not-a-delay")
    _install_transport(monkeypatch, transport)
    sleeps = _record_sleeps(monkeypatch)
    adapter = _make_adapter()
    adapter._key_pool = _CoolingThenReadyPool()

    await adapter.embed(EmbeddingRequest(texts=["hello"], model="test-model"))

    assert len(sleeps) == 2
    assert 120 <= sleeps[0] <= 130
    assert 130 <= sleeps[1] <= 140
