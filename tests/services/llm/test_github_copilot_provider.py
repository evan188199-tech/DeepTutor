"""Contract tests for the GitHub Copilot provider.

Everything runs offline: the HTTP layer is faked, and the only tokens in
play are throwaway placeholder strings — never real credentials. Header
assertions check presence and structure (a non-empty value where one is
required), not specific values.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import httpx
from openai import AuthenticationError, PermissionDeniedError
import pytest

from deeptutor.services.llm.provider_core import github_copilot_provider as module
from deeptutor.services.llm.provider_core import openai_compat_provider as compat_module
from deeptutor.services.llm.provider_core.base import LLMResponse
from deeptutor.services.llm.provider_core.github_copilot_provider import (
    DEFAULT_COPILOT_BASE_URL,
    DEFAULT_COPILOT_TOKEN_URL,
    EDITOR_PLUGIN_VERSION,
    EDITOR_VERSION,
    USER_AGENT,
    GitHubCopilotProvider,
)
from deeptutor.services.provider_registry import find_by_name

_CHAT_COMPLETIONS_URL = f"{DEFAULT_COPILOT_BASE_URL}/chat/completions"
_EDITOR_HEADER_KEYS = {"Editor-Version", "Editor-Plugin-Version", "User-Agent"}


def _make_provider() -> GitHubCopilotProvider:
    return GitHubCopilotProvider(configure_env=False)


def _auth_error(status: int) -> AuthenticationError:
    return AuthenticationError(
        f"HTTP {status}",
        response=httpx.Response(status, request=httpx.Request("POST", _CHAT_COMPLETIONS_URL)),
        body=None,
    )


def _forbidden_error() -> PermissionDeniedError:
    return PermissionDeniedError(
        "HTTP 403",
        response=httpx.Response(403, request=httpx.Request("POST", _CHAT_COMPLETIONS_URL)),
        body=None,
    )


class _FakeTokenResponse:
    def __init__(self, payload: dict[str, Any], status_error: Exception | None = None) -> None:
        self._payload = payload
        self._status_error = status_error

    def raise_for_status(self) -> None:
        if self._status_error is not None:
            raise self._status_error

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeTokenHttpClient:
    """Stands in for httpx.AsyncClient during token-exchange tests."""

    def __init__(self, response: _FakeTokenResponse, captures: list[dict[str, Any]]) -> None:
        self._response = response
        self._captures = captures

    async def __aenter__(self) -> "_FakeTokenHttpClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def get(self, url: str, headers: dict[str, str] | None = None) -> _FakeTokenResponse:
        self._captures.append({"url": url, "headers": dict(headers or {})})
        return self._response


def _patch_token_http(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, Any],
    captures: list[dict[str, Any]],
    status_error: Exception | None = None,
) -> None:
    client = _FakeTokenHttpClient(_FakeTokenResponse(payload, status_error), captures)

    class _Factory:
        def __init__(self, **kwargs: Any) -> None:
            captures.append({"client_kwargs": kwargs})

        async def __aenter__(self) -> _FakeTokenHttpClient:
            return client

        async def __aexit__(self, *args: Any) -> None:
            return None

    fake_httpx = SimpleNamespace(AsyncClient=_Factory, Timeout=httpx.Timeout)
    monkeypatch.setattr(module, "httpx", fake_httpx)


def _stub_stored_github_token(
    monkeypatch: pytest.MonkeyPatch, token: str | None
) -> GitHubCopilotProvider:
    provider = _make_provider()

    async def load() -> str | None:
        return token

    monkeypatch.setattr(provider, "_load_stored_github_token", load)
    return provider


def _content_chunk(text: str, finish_reason: str | None = None) -> SimpleNamespace:
    delta = SimpleNamespace(content=text, reasoning_content=None, reasoning=None, tool_calls=[])
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)])


def _reasoning_chunk(text: str) -> SimpleNamespace:
    delta = SimpleNamespace(content=None, reasoning_content=text, reasoning=None, tool_calls=[])
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=None)])


class _FakeStream:
    def __init__(self, chunks: list[Any]) -> None:
        self._chunks = chunks

    def __aiter__(self) -> "_FakeStream":
        self._iter = iter(self._chunks)
        return self

    async def __anext__(self) -> Any:
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


# ---------------------------------------------------------------------------
# Header assembly — presence and structure only
# ---------------------------------------------------------------------------


def test_init_installs_copilot_editor_headers_and_base_url() -> None:
    provider = _make_provider()

    assert provider.api_base == DEFAULT_COPILOT_BASE_URL
    assert _EDITOR_HEADER_KEYS <= set(provider.extra_headers)
    assert all(
        isinstance(provider.extra_headers[key], str) and provider.extra_headers[key]
        for key in _EDITOR_HEADER_KEYS
    )


@pytest.mark.asyncio
async def test_exchange_token_sends_structured_credential_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captures: list[dict[str, Any]] = []
    _patch_token_http(
        monkeypatch, {"token": "exchanged-token", "expires_at": 2_000_000_000}, captures
    )
    provider = _stub_stored_github_token(monkeypatch, "stored-github-token")

    token = await provider._exchange_token()

    assert token == "exchanged-token"
    call = next(c for c in captures if "url" in c)
    assert call["url"] == DEFAULT_COPILOT_TOKEN_URL
    headers = call["headers"]
    assert headers["Authorization"].startswith("token ")
    assert len(headers["Authorization"]) > len("token ")
    assert headers["Accept"] == "application/json"
    assert headers["User-Agent"] == USER_AGENT
    assert headers["Editor-Version"] == EDITOR_VERSION
    assert headers["Editor-Plugin-Version"] == EDITOR_PLUGIN_VERSION


# ---------------------------------------------------------------------------
# Token exchange branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exchange_token_without_stored_github_token_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _stub_stored_github_token(monkeypatch, None)

    with pytest.raises(RuntimeError):
        await provider._exchange_token()
    assert provider._copilot_access_token is None


@pytest.mark.asyncio
async def test_exchange_token_malformed_payload_without_token_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captures: list[dict[str, Any]] = []
    _patch_token_http(monkeypatch, {"expires_at": 2_000_000_000}, captures)
    provider = _stub_stored_github_token(monkeypatch, "stored-github-token")

    with pytest.raises(RuntimeError):
        await provider._exchange_token()
    assert provider._copilot_access_token is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [{"token": "t1", "refresh_in": 900}, {"token": "t2"}],
)
async def test_exchange_token_expiry_falls_back_to_refresh_window(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, Any],
) -> None:
    captures: list[dict[str, Any]] = []
    _patch_token_http(monkeypatch, payload, captures)
    provider = _stub_stored_github_token(monkeypatch, "stored-github-token")

    expected_window = int(payload.get("refresh_in") or 1500)
    before = time.time()
    await provider._exchange_token()
    after = time.time()

    assert provider._copilot_access_token == payload["token"]
    assert before + expected_window <= provider._copilot_expires_at <= after + expected_window


@pytest.mark.asyncio
async def test_exchange_token_prefers_explicit_expires_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captures: list[dict[str, Any]] = []
    _patch_token_http(monkeypatch, {"token": "t3", "expires_at": 1_900_000_000}, captures)
    provider = _stub_stored_github_token(monkeypatch, "stored-github-token")

    await provider._exchange_token()

    assert provider._copilot_expires_at == 1_900_000_000.0


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_exchange_token_http_auth_failures_propagate(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    captures: list[dict[str, Any]] = []
    status_error = httpx.HTTPStatusError(
        f"HTTP {status}",
        request=httpx.Request("GET", DEFAULT_COPILOT_TOKEN_URL),
        response=httpx.Response(status),
    )
    _patch_token_http(monkeypatch, {"token": "never-reached"}, captures, status_error=status_error)
    provider = _stub_stored_github_token(monkeypatch, "stored-github-token")

    with pytest.raises(httpx.HTTPStatusError):
        await provider._exchange_token()
    assert provider._copilot_access_token is None


# ---------------------------------------------------------------------------
# API-key lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_api_key_reuses_unexpired_copilot_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _make_provider()
    provider._copilot_access_token = "copilot-access-token"
    provider._copilot_expires_at = time.time() + 3600
    local_auth_calls: list[int] = []

    async def record_local_auth() -> None:
        local_auth_calls.append(1)

    monkeypatch.setattr(provider, "_try_existing_local_auth", record_local_auth)

    await provider._ensure_api_key()

    assert provider.api_key == "copilot-access-token"
    assert provider._client.api_key == "copilot-access-token"
    assert local_auth_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("remaining", [30, -1])
async def test_ensure_api_key_treats_expired_or_near_expiry_token_as_missing(
    monkeypatch: pytest.MonkeyPatch,
    remaining: float,
) -> None:
    provider = _make_provider()
    provider._copilot_access_token = "stale-token"
    provider._copilot_expires_at = time.time() + remaining
    local_auth_calls: list[int] = []

    async def record_local_auth() -> None:
        local_auth_calls.append(1)

    monkeypatch.setattr(provider, "_try_existing_local_auth", record_local_auth)

    await provider._ensure_api_key()

    assert local_auth_calls == [1]
    assert provider.api_key == "copilot"


# ---------------------------------------------------------------------------
# Model catalog resolution
# ---------------------------------------------------------------------------


def test_build_kwargs_strips_provider_prefix_and_targets_completion_tokens() -> None:
    provider = GitHubCopilotProvider.__new__(GitHubCopilotProvider)
    provider.default_model = "github-copilot/gpt-4.1"
    provider._spec = find_by_name("github_copilot")

    kwargs = provider._build_kwargs(
        messages=[{"role": "user", "content": "hello"}],
        tools=None,
        model="github-copilot/gpt-4.1",
        max_tokens=256,
        temperature=0.5,
        reasoning_effort=None,
        tool_choice=None,
    )

    assert kwargs["model"] == "gpt-4.1"
    assert "max_completion_tokens" in kwargs
    assert "max_tokens" not in kwargs


# ---------------------------------------------------------------------------
# Non-streaming path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_non_stream_parses_completion_and_sends_bearer_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _make_provider()
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="copilot answer",
                    reasoning_content=None,
                    reasoning=None,
                    tool_calls=None,
                ),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(prompt_tokens=3, completion_tokens=4, total_tokens=7),
    )
    captured: list[dict[str, Any]] = []

    async def fake_create(**kwargs: Any) -> Any:
        captured.append(kwargs)
        return completion

    monkeypatch.setattr(provider._client.chat.completions, "create", fake_create)

    result = await provider.chat(
        [{"role": "user", "content": "hi"}], model="github-copilot/gpt-4.1"
    )

    assert result.content == "copilot answer"
    assert result.finish_reason == "stop"
    assert result.usage["prompt_tokens"] == 3
    assert result.usage["completion_tokens"] == 4
    assert captured[0]["model"] == "gpt-4.1"
    headers = captured[0].get("extra_headers") or {}
    assert "Authorization" in headers
    assert headers["Authorization"].startswith("Bearer ")


@pytest.mark.asyncio
async def test_chat_malformed_empty_choices_becomes_error_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _make_provider()

    async def fake_create(**kwargs: Any) -> Any:
        return SimpleNamespace(choices=[])

    monkeypatch.setattr(provider._client.chat.completions, "create", fake_create)

    result = await provider.chat([{"role": "user", "content": "hi"}])

    assert result.finish_reason == "error"
    assert "empty choices" in (result.content or "").lower()


@pytest.mark.asyncio
async def test_chat_403_surfaces_error_without_token_exchange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _make_provider()

    async def forbidden(**kwargs: Any) -> Any:
        raise _forbidden_error()

    monkeypatch.setattr(provider._client.chat.completions, "create", forbidden)

    async def no_exchange() -> str:
        raise AssertionError("token exchange must not run for a 403")

    monkeypatch.setattr(provider, "_exchange_token", no_exchange)

    result = await provider.chat([{"role": "user", "content": "hi"}])

    assert result.finish_reason == "error"
    assert (result.content or "").startswith("Error")


# ---------------------------------------------------------------------------
# Streaming path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_stream_forwards_content_and_reasoning_deltas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _make_provider()
    chunks = [
        _content_chunk("Hel"),
        _reasoning_chunk("thinking"),
        _content_chunk("lo"),
        SimpleNamespace(choices=[]),
        _content_chunk("", finish_reason="stop"),
    ]
    content_deltas: list[str] = []
    reasoning_deltas: list[str] = []

    async def on_content_delta(text: str) -> None:
        content_deltas.append(text)

    async def on_reasoning_delta(text: str) -> None:
        reasoning_deltas.append(text)

    async def fake_create(**kwargs: Any) -> Any:
        assert kwargs.get("stream") is True
        return _FakeStream(chunks)

    monkeypatch.setattr(provider._client.chat.completions, "create", fake_create)

    result = await provider.chat_stream(
        [{"role": "user", "content": "hi"}],
        model="github-copilot/gpt-4.1",
        on_content_delta=on_content_delta,
        on_reasoning_delta=on_reasoning_delta,
    )

    assert result.content == "Hello"
    assert result.reasoning_content == "thinking"
    assert result.finish_reason == "stop"
    assert content_deltas == ["Hel", "lo"]
    assert reasoning_deltas == ["thinking"]


@pytest.mark.asyncio
async def test_chat_stream_401_exchanges_token_and_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _make_provider()
    exchange_calls: list[int] = []

    async def fake_exchange() -> str:
        exchange_calls.append(1)
        return "exchanged-access-token"

    monkeypatch.setattr(provider, "_exchange_token", fake_exchange)

    parent_calls: list[dict[str, Any]] = []

    async def fake_parent_stream(self: Any, **kwargs: Any) -> LLMResponse:
        parent_calls.append(kwargs)
        if len(parent_calls) == 1:
            raise _auth_error(401)
        return LLMResponse(content="stream-recovered", finish_reason="stop")

    monkeypatch.setattr(compat_module.OpenAICompatProvider, "chat_stream", fake_parent_stream)

    result = await provider.chat_stream(
        [{"role": "user", "content": "hi"}], model="github-copilot/gpt-4.1"
    )

    assert result.content == "stream-recovered"
    assert result.finish_reason == "stop"
    assert exchange_calls == [1]
    assert len(parent_calls) == 2
    assert provider.api_key == "exchanged-access-token"
    assert provider._client.api_key == "exchanged-access-token"


# ---------------------------------------------------------------------------
# 401 retry branch of _chat_impl (non-streaming)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_401_exchanges_token_and_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _make_provider()
    exchange_calls: list[int] = []

    async def fake_exchange() -> str:
        exchange_calls.append(1)
        return "exchanged-access-token"

    monkeypatch.setattr(provider, "_exchange_token", fake_exchange)

    parent_calls: list[dict[str, Any]] = []
    recovered = LLMResponse(content="recovered", finish_reason="stop")

    async def fake_parent_chat(self: Any, **kwargs: Any) -> LLMResponse:
        parent_calls.append(kwargs)
        if len(parent_calls) == 1:
            raise _auth_error(401)
        return recovered

    monkeypatch.setattr(compat_module.OpenAICompatProvider, "chat", fake_parent_chat)

    result = await provider.chat(
        [{"role": "user", "content": "hi"}], model="github-copilot/gpt-4.1"
    )

    assert result is recovered
    assert exchange_calls == [1]
    assert len(parent_calls) == 2
    assert provider.api_key == "exchanged-access-token"
    assert provider._client.api_key == "exchanged-access-token"
