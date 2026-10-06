"""Tests for local-server model discovery and the deprecated call shims."""

from __future__ import annotations

from collections.abc import Callable
from types import TracebackType

from _pytest.monkeypatch import MonkeyPatch
import aiohttp
import pytest

from deeptutor.services.llm import local_provider


class _FakeResponse:
    def __init__(self, status: int, json_data: object) -> None:
        self.status = status
        self._json_data = json_data

    async def __aenter__(self):
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def json(self):
        return self._json_data


class _FakeSession:
    def __init__(self, route: Callable[[str], _FakeResponse]) -> None:
        self._route = route
        self.urls: list[str] = []
        self.headers: list[dict[str, str]] = []

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    def get(self, url: str, **kwargs: object) -> _FakeResponse:
        self.urls.append(url)
        self.headers.append(dict(kwargs.get("headers") or {}))  # type: ignore[arg-type]
        return self._route(url)


def _install(monkeypatch: MonkeyPatch, route: Callable[[str], _FakeResponse]) -> _FakeSession:
    session = _FakeSession(route)
    monkeypatch.setattr(local_provider.aiohttp, "ClientSession", lambda *a, **kw: session)
    return session


@pytest.mark.asyncio
async def test_ollama_models_come_from_api_tags(monkeypatch: MonkeyPatch) -> None:
    session = _install(
        monkeypatch,
        lambda url: (
            _FakeResponse(200, {"models": [{"name": "llama3"}, {"name": "qwen"}]})
            if url.endswith("/api/tags")
            else _FakeResponse(404, {})
        ),
    )

    models = await local_provider.fetch_models("http://localhost:11434/v1")

    assert models == ["llama3", "qwen"]
    assert session.urls == ["http://localhost:11434/api/tags"]


@pytest.mark.asyncio
async def test_openai_compatible_models_come_from_models_endpoint(
    monkeypatch: MonkeyPatch,
) -> None:
    session = _install(
        monkeypatch,
        lambda url: _FakeResponse(200, {"data": [{"id": "local-a"}, {"id": "local-b"}]}),
    )

    models = await local_provider.fetch_models("http://localhost:1234/v1")

    assert models == ["local-a", "local-b"]
    assert session.urls == ["http://localhost:1234/v1/models"]


@pytest.mark.asyncio
async def test_stream_shim_forwards_to_factory(monkeypatch: MonkeyPatch) -> None:
    from deeptutor.services.llm import factory

    async def fake_stream(prompt: str, **kwargs: object):
        yield f"{prompt}:{kwargs['model']}"

    monkeypatch.setattr(factory, "stream", fake_stream)
    with pytest.warns(DeprecationWarning):
        chunks = [
            chunk
            async for chunk in local_provider.stream(
                "hello", model="local-test", base_url="http://localhost:8000/v1"
            )
        ]

    assert chunks == ["hello:local-test"]


@pytest.mark.asyncio
async def test_ollama_tags_failure_falls_back_to_models_endpoint(
    monkeypatch: MonkeyPatch,
) -> None:
    """When /api/tags is unreachable the OpenAI-compatible /models endpoint is still tried."""

    def route(url: str) -> _FakeResponse:
        if url.endswith("/api/tags"):
            raise aiohttp.ClientError("connection refused")
        return _FakeResponse(200, {"data": [{"id": "fallback"}]})

    session = _install(monkeypatch, route)

    models = await local_provider.fetch_models("http://localhost:11434")

    assert models == ["fallback"]
    assert session.urls == [
        "http://localhost:11434/api/tags",
        "http://localhost:11434/models",
    ]


@pytest.mark.asyncio
async def test_models_endpoint_non_200_returns_empty(monkeypatch: MonkeyPatch) -> None:
    _install(monkeypatch, lambda url: _FakeResponse(503, {"error": "warming up"}))

    assert await local_provider.fetch_models("http://localhost:8000/v1", "k") == []


@pytest.mark.asyncio
async def test_models_endpoint_connection_error_returns_empty(
    monkeypatch: MonkeyPatch,
) -> None:
    """A dead server degrades to an empty list instead of raising."""

    def route(url: str) -> _FakeResponse:
        raise aiohttp.ClientError("nothing listening")

    _install(monkeypatch, route)

    assert await local_provider.fetch_models("http://localhost:8000/v1") == []


@pytest.mark.asyncio
async def test_models_endpoint_supports_models_key_and_bare_list(
    monkeypatch: MonkeyPatch,
) -> None:
    session = _install(monkeypatch, lambda url: _FakeResponse(200, {"models": [{"name": "q"}]}))
    assert await local_provider.fetch_models("http://localhost:1234/v1") == ["q"]

    session = _install(monkeypatch, lambda url: _FakeResponse(200, [{"id": "bare"}]))
    assert await local_provider.fetch_models("http://localhost:1234/v1") == ["bare"]

    session = _install(monkeypatch, lambda url: _FakeResponse(200, {"data": "oops"}))
    assert await local_provider.fetch_models("http://localhost:1234/v1") == []


@pytest.mark.asyncio
async def test_api_key_sent_as_bearer_without_content_type(
    monkeypatch: MonkeyPatch,
) -> None:
    session = _install(monkeypatch, lambda url: _FakeResponse(200, {"data": []}))

    await local_provider.fetch_models("http://localhost:1234/v1", "secret")

    assert session.headers == [{"Authorization": "Bearer secret"}]

    session = _install(monkeypatch, lambda url: _FakeResponse(200, {"data": []}))
    await local_provider.fetch_models("http://localhost:1234/v1")
    assert session.headers == [{}]


@pytest.mark.asyncio
async def test_complete_shim_forwards_to_factory(monkeypatch: MonkeyPatch) -> None:
    from deeptutor.services.llm import factory

    captured: dict[str, object] = {}

    async def fake_complete(prompt: str, **kwargs: object) -> str:
        captured["prompt"] = prompt
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(factory, "complete", fake_complete)
    with pytest.warns(DeprecationWarning):
        result = await local_provider.complete("hello", model="local-test")

    assert result == "ok"
    assert captured == {"prompt": "hello", "model": "local-test"}


@pytest.mark.asyncio
async def test_stream_shim_propagates_mid_stream_interruption(
    monkeypatch: MonkeyPatch,
) -> None:
    """Chunks already yielded survive; the upstream failure is never swallowed."""
    from deeptutor.services.llm import factory

    async def fake_stream(prompt: str, **kwargs: object):
        yield "first"
        raise RuntimeError("local server dropped mid-stream")

    monkeypatch.setattr(factory, "stream", fake_stream)
    chunks: list[str] = []
    with pytest.warns(DeprecationWarning), pytest.raises(RuntimeError, match="dropped"):
        async for chunk in local_provider.stream("hello"):
            chunks.append(chunk)

    assert chunks == ["first"]
