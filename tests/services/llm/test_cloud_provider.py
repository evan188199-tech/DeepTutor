"""Tests for hosted-endpoint model discovery and the deprecated call shims."""

from __future__ import annotations

import importlib
import json
from types import TracebackType

from _pytest.monkeypatch import MonkeyPatch
import aiohttp
import pytest

cloud_provider = importlib.import_module("deeptutor.services.llm.cloud_provider")


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
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.requests: list[tuple[str, dict[str, str]]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    def get(self, url: str, **kwargs: object) -> _FakeResponse:
        self.requests.append((url, dict(kwargs.get("headers") or {})))  # type: ignore[arg-type]
        return self._response


def _install_session(monkeypatch: MonkeyPatch, response: _FakeResponse) -> _FakeSession:
    session = _FakeSession(response)
    monkeypatch.setattr(cloud_provider.aiohttp, "ClientSession", lambda *a, **kw: session)
    return session


@pytest.mark.asyncio
async def test_cloud_fetch_models(monkeypatch: MonkeyPatch) -> None:
    """Fetch models should parse model lists from the response."""
    session = _install_session(
        monkeypatch, _FakeResponse(200, {"data": [{"id": "m1"}, {"id": "m2"}]})
    )

    models = await cloud_provider.fetch_models("https://api.openai.com/v1", "sk-test")

    assert models == ["m1", "m2"]
    url, headers = session.requests[0]
    assert url == "https://api.openai.com/v1/models"
    assert headers["Authorization"] == "Bearer sk-test"
    assert "Content-Type" not in headers


@pytest.mark.asyncio
async def test_cloud_fetch_models_anthropic_format_uses_anthropic_headers(
    monkeypatch: MonkeyPatch,
) -> None:
    """A custom endpoint speaking Anthropic Messages is listed with x-api-key."""
    session = _install_session(monkeypatch, _FakeResponse(200, {"data": [{"id": "claude"}]}))

    models = await cloud_provider.fetch_models(
        "https://relay.example/anthropic", "ak", binding="custom", api_format="anthropic"
    )

    assert models == ["claude"]
    _, headers = session.requests[0]
    assert headers["x-api-key"] == "ak"
    assert "Authorization" not in headers


@pytest.mark.asyncio
async def test_cloud_fetch_models_non_200_returns_empty(monkeypatch: MonkeyPatch) -> None:
    _install_session(monkeypatch, _FakeResponse(401, {"error": "nope"}))

    assert await cloud_provider.fetch_models("https://api.openai.com/v1", "bad") == []


@pytest.mark.asyncio
async def test_cloud_fetch_models_normalizes_base_url_and_binding(
    monkeypatch: MonkeyPatch,
) -> None:
    """Trailing slashes are stripped and the binding name is matched case-insensitively."""
    session = _install_session(monkeypatch, _FakeResponse(200, {"data": [{"id": "m"}]}))

    models = await cloud_provider.fetch_models("https://api.example.com/v1/", "k", binding="OPENAI")

    assert models == ["m"]
    url, headers = session.requests[0]
    assert url == "https://api.example.com/v1/models"
    assert headers["Authorization"] == "Bearer k"


@pytest.mark.asyncio
async def test_cloud_fetch_models_accepts_bare_list_payload(monkeypatch: MonkeyPatch) -> None:
    """Endpoints that answer with a bare JSON array are supported too."""
    _install_session(
        monkeypatch,
        _FakeResponse(200, [{"id": "a"}, {"name": "b"}, {"model": "c"}, "raw-id"]),
    )

    assert await cloud_provider.fetch_models("https://x/v1") == ["a", "b", "c", "raw-id"]


@pytest.mark.asyncio
async def test_cloud_fetch_models_ignores_unexpected_payload_shapes(
    monkeypatch: MonkeyPatch,
) -> None:
    _install_session(monkeypatch, _FakeResponse(200, {"object": "list"}))
    assert await cloud_provider.fetch_models("https://x/v1") == []

    _install_session(monkeypatch, _FakeResponse(200, {"data": {"id": "not-a-list"}}))
    assert await cloud_provider.fetch_models("https://x/v1") == []


class _InterruptedSession:
    """Fake session whose request dies mid-flight."""

    async def __aenter__(self) -> "_InterruptedSession":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    def get(self, url: str, **_kwargs: object) -> "_FakeResponse":
        raise aiohttp.ClientError("connection reset mid-request")


@pytest.mark.asyncio
async def test_cloud_fetch_models_connection_interrupted_returns_empty(
    monkeypatch: MonkeyPatch,
) -> None:
    """A dropped connection degrades to an empty list instead of raising."""
    monkeypatch.setattr(
        cloud_provider.aiohttp, "ClientSession", lambda *a, **kw: _InterruptedSession()
    )

    assert await cloud_provider.fetch_models("https://api.openai.com/v1", "k") == []


@pytest.mark.asyncio
async def test_cloud_fetch_models_malformed_json_returns_empty(
    monkeypatch: MonkeyPatch,
) -> None:
    class _BadJsonResponse(_FakeResponse):
        async def json(self):
            raise json.JSONDecodeError("Expecting value", "", 0)

    _install_session(monkeypatch, _BadJsonResponse(200, None))

    assert await cloud_provider.fetch_models("https://api.openai.com/v1") == []


@pytest.mark.asyncio
async def test_cloud_fetch_models_server_error_returns_empty(
    monkeypatch: MonkeyPatch,
) -> None:
    _install_session(monkeypatch, _FakeResponse(500, {"error": "upstream down"}))

    assert await cloud_provider.fetch_models("https://api.openai.com/v1", "k") == []


def test_ssl_connector(monkeypatch: MonkeyPatch) -> None:
    """The aiohttp connector only appears when TLS verification is disabled."""
    monkeypatch.delenv("DISABLE_SSL_VERIFY", raising=False)
    assert cloud_provider._get_aiohttp_connector() is None

    class _FakeConnector:
        pass

    monkeypatch.setenv("DISABLE_SSL_VERIFY", "1")
    monkeypatch.setitem(cloud_provider.__dict__, "_ssl_warning_logged", False)
    monkeypatch.setattr(cloud_provider.aiohttp, "TCPConnector", lambda **_kw: _FakeConnector())
    assert cloud_provider._get_aiohttp_connector() is not None


@pytest.mark.asyncio
async def test_complete_shim_forwards_to_factory(monkeypatch: MonkeyPatch) -> None:
    """The retired aiohttp path now forwards to the one real LLM entry point."""
    from deeptutor.services.llm import factory

    captured: dict[str, object] = {}

    async def fake_complete(prompt: str, **kwargs: object) -> str:
        captured["prompt"] = prompt
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(factory, "complete", fake_complete)
    with pytest.warns(DeprecationWarning):
        result = await cloud_provider.complete("hello", model="gpt-test", binding="openai")

    assert result == "ok"
    assert captured == {"prompt": "hello", "model": "gpt-test", "binding": "openai"}


@pytest.mark.asyncio
async def test_cloud_stream_shim_forwards_to_factory(monkeypatch: MonkeyPatch) -> None:
    from deeptutor.services.llm import factory

    async def fake_stream(prompt: str, **kwargs: object):
        yield "a"
        yield "b"

    monkeypatch.setattr(factory, "stream", fake_stream)
    with pytest.warns(DeprecationWarning):
        chunks = [chunk async for chunk in cloud_provider.stream("hi", model="m")]

    assert chunks == ["a", "b"]


@pytest.mark.asyncio
async def test_cloud_stream_shim_propagates_mid_stream_interruption(
    monkeypatch: MonkeyPatch,
) -> None:
    """The shim is a pure forwarder: chunks already received survive, the failure raises."""
    from deeptutor.services.llm import factory

    async def fake_stream(prompt: str, **kwargs: object):
        yield "first"
        raise RuntimeError("stream interrupted upstream")

    monkeypatch.setattr(factory, "stream", fake_stream)
    chunks: list[str] = []
    with pytest.warns(DeprecationWarning), pytest.raises(RuntimeError, match="interrupted"):
        async for chunk in cloud_provider.stream("hi"):
            chunks.append(chunk)

    assert chunks == ["first"]


@pytest.mark.asyncio
async def test_cloud_complete_shim_propagates_factory_failure_untouched(
    monkeypatch: MonkeyPatch,
) -> None:
    """Errors cross the shim without remapping; classification belongs to the factory layer."""
    from deeptutor.services.llm import factory

    failure = RuntimeError("provider down")

    async def boom(prompt: str, **kwargs: object) -> str:
        raise failure

    monkeypatch.setattr(factory, "complete", boom)
    with pytest.warns(DeprecationWarning), pytest.raises(RuntimeError) as exc_info:
        await cloud_provider.complete("hi")

    assert exc_info.value is failure
