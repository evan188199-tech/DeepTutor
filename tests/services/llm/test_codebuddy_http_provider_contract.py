"""Contract tests for the CodeBuddy HTTP provider surface.

Exercises the branches of ``normalize_api_key``, ``CodeBuddyHTTPProvider``,
``codebuddy_http_available``, ``sdk_installed`` and ``build_codebuddy_provider``
that the module's own test file does not cover: key normalization, constructor
auth selection, the AuthenticationError reload-and-retry path, idle-timeout and
malformed-stream surfacing, availability probing, and backend dispatch. All
HTTP is mocked; no real credentials, network, or SDK install is required.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
import time
from typing import Any

import httpx
from openai import AuthenticationError
import pytest

from deeptutor.services.codebuddy_credentials import (
    INTERNAL_ENDPOINT,
    OVERSEAS_ENDPOINT,
    CodeBuddyAuthUnavailable,
)
from deeptutor.services.llm.provider_core import codebuddy_http_provider as http_module
from deeptutor.services.llm.provider_core.base import LLMResponse
from deeptutor.services.llm.provider_core.codebuddy_http_provider import (
    DEFAULT_CODEBUDDY_MODEL,
    CodeBuddyHTTPProvider,
    build_codebuddy_provider,
    codebuddy_http_available,
    normalize_api_key,
    sdk_installed,
)
from deeptutor.services.llm.provider_core.codebuddy_provider import CodeBuddyProvider


def _write_session(
    path: Path,
    *,
    domain: str = "www.codebuddy.cn",
    token: str = "access-token",
    expires_in: float = 86400.0,
) -> None:
    path.write_text(
        json.dumps(
            {
                "account": {"uid": "uid-1", "nickname": "tester"},
                "auth": {
                    "accessToken": token,
                    "refreshToken": "refresh-token",
                    "expiresAt": int((time.time() + expires_in) * 1000),
                    "refreshExpiresAt": int((time.time() + 7776000) * 1000),
                    "domain": domain,
                },
            }
        ),
        encoding="utf-8",
    )


def _sign_in(tmp_path: Path, monkeypatch, **kwargs) -> Path:
    path = tmp_path / "Tencent-Cloud.coding-copilot.info"
    _write_session(path, **kwargs)
    monkeypatch.setenv("DEEPTUTOR_CODEBUDDY_AUTH_FILE", str(path))
    return path


def _auth_error() -> AuthenticationError:
    request = httpx.Request("POST", INTERNAL_ENDPOINT + "/v2/chat/completions")
    return AuthenticationError(
        "Unauthorized", response=httpx.Response(401, request=request), body=None
    )


def _stub_compat_stream(monkeypatch, outcomes: list[Any] | None = None) -> list[dict[str, Any]]:
    """Replace the compat base's ``chat_stream``; record every provider call."""
    calls: list[dict[str, Any]] = []
    pending = list(outcomes or [])

    async def fake_chat_stream(self, **kwargs):
        calls.append(
            {
                "api_key": self._client.api_key,
                "base_url": str(self._client.base_url).rstrip("/"),
                "kwargs": kwargs,
            }
        )
        outcome = pending.pop(0) if pending else LLMResponse(content="OK")
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(
        "deeptutor.services.llm.provider_core.openai_compat_provider."
        "OpenAICompatProvider.chat_stream",
        fake_chat_stream,
    )
    return calls


class _GarbageChunkStream:
    def __aiter__(self):
        return self

    async def __anext__(self):
        return object()


class _EmptyStream:
    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


# ----------------------------------------------------------------------
# normalize_api_key
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("sk-no-key-required", None),
        ("  sk-no-key-required  ", None),
        ("cb-key", "cb-key"),
        ("  cb-key  ", "cb-key"),
    ],
)
def test_normalize_api_key_contract(raw: str | None, expected: str | None) -> None:
    assert normalize_api_key(raw) == expected


# ----------------------------------------------------------------------
# Constructor auth selection
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_explicit_api_key_bypasses_disk_session(monkeypatch) -> None:
    def forbidden():
        raise AssertionError("explicit-key mode must not read the session file")

    monkeypatch.setattr(http_module, "load_credentials", forbidden)
    calls = _stub_compat_stream(monkeypatch)

    provider = CodeBuddyHTTPProvider(api_key="  cb-key  ")
    response = await provider.chat_stream(messages=[{"role": "user", "content": "hi"}])

    assert response.content == "OK"
    assert provider.extra_headers == {"X-API-Key": "cb-key"}
    assert "X-User-Id" not in provider.extra_headers
    assert provider.api_base == OVERSEAS_ENDPOINT + "/v2"
    assert calls[0]["api_key"] == "cb-key"


def test_placeholder_api_key_falls_back_to_local_session(tmp_path, monkeypatch) -> None:
    _sign_in(tmp_path, monkeypatch)

    provider = CodeBuddyHTTPProvider(api_key="sk-no-key-required")

    assert "X-API-Key" not in provider.extra_headers
    assert provider.extra_headers["X-User-Id"] == "uid-1"


def test_session_sign_in_sets_user_header_regional_base_and_default_model(
    tmp_path, monkeypatch
) -> None:
    _sign_in(tmp_path, monkeypatch, domain="www.codebuddy.cn")

    provider = CodeBuddyHTTPProvider()

    assert provider.extra_headers == {"X-User-Id": "uid-1"}
    assert provider.api_base == INTERNAL_ENDPOINT + "/v2"
    assert provider.get_default_model() == DEFAULT_CODEBUDDY_MODEL
    assert CodeBuddyHTTPProvider(default_model="").get_default_model() == DEFAULT_CODEBUDDY_MODEL


# ----------------------------------------------------------------------
# Authentication reload / retry
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authentication_error_reloads_rotated_session_and_retries_once(
    tmp_path, monkeypatch
) -> None:
    path = _sign_in(tmp_path, monkeypatch, domain="www.codebuddy.cn", token="stale-token")
    calls = _stub_compat_stream(monkeypatch, outcomes=[_auth_error(), LLMResponse(content="OK")])

    provider = CodeBuddyHTTPProvider()
    _write_session(path, domain="codebuddy.ai", token="fresh-token")

    response = await provider.chat_stream(messages=[{"role": "user", "content": "hi"}])

    assert response.content == "OK"
    assert [call["api_key"] for call in calls] == ["stale-token", "fresh-token"]
    assert calls[0]["base_url"] == INTERNAL_ENDPOINT + "/v2"
    assert calls[1]["base_url"] == OVERSEAS_ENDPOINT + "/v2"


@pytest.mark.asyncio
async def test_second_authentication_error_is_not_retried_again(tmp_path, monkeypatch) -> None:
    _sign_in(tmp_path, monkeypatch)
    calls = _stub_compat_stream(monkeypatch, outcomes=[_auth_error(), _auth_error()])

    provider = CodeBuddyHTTPProvider()

    with pytest.raises(AuthenticationError):
        await provider.chat_stream(messages=[{"role": "user", "content": "hi"}])

    assert len(calls) == 2


@pytest.mark.asyncio
async def test_authentication_error_reload_falls_back_to_cached_session(
    tmp_path, monkeypatch
) -> None:
    path = _sign_in(tmp_path, monkeypatch)
    provider = CodeBuddyHTTPProvider()
    calls = _stub_compat_stream(monkeypatch, outcomes=[_auth_error(), LLMResponse(content="OK")])
    path.unlink()

    response = await provider.chat_stream(messages=[{"role": "user", "content": "hi"}])

    assert response.content == "OK"
    assert [call["api_key"] for call in calls] == ["access-token", "access-token"]


@pytest.mark.asyncio
async def test_chat_stream_forwards_delta_callbacks(tmp_path, monkeypatch) -> None:
    _sign_in(tmp_path, monkeypatch)

    async def on_content_delta(text: str) -> None:
        return None

    async def on_reasoning_delta(text: str) -> None:
        return None

    calls = _stub_compat_stream(monkeypatch)

    await CodeBuddyHTTPProvider().chat_stream(
        messages=[{"role": "user", "content": "hi"}],
        on_content_delta=on_content_delta,
        on_reasoning_delta=on_reasoning_delta,
    )

    assert calls[0]["kwargs"]["on_content_delta"] is on_content_delta
    assert calls[0]["kwargs"]["on_reasoning_delta"] is on_reasoning_delta


# ----------------------------------------------------------------------
# Timeout / malformed stream surfacing
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idle_timeout_surfaces_as_error_response(tmp_path, monkeypatch) -> None:
    _sign_in(tmp_path, monkeypatch)

    async def stalled(**kwargs):
        raise asyncio.TimeoutError()

    provider = CodeBuddyHTTPProvider()
    monkeypatch.setattr(provider._client.chat.completions, "create", stalled)

    response = await provider.chat_stream(messages=[{"role": "user", "content": "hi"}])

    assert response.finish_reason == "error"
    assert "stalled" in response.content


@pytest.mark.asyncio
async def test_malformed_stream_chunk_surfaces_as_error_response(tmp_path, monkeypatch) -> None:
    _sign_in(tmp_path, monkeypatch)

    async def broken(**kwargs):
        return _GarbageChunkStream()

    provider = CodeBuddyHTTPProvider()
    monkeypatch.setattr(provider._client.chat.completions, "create", broken)

    response = await provider.chat_stream(messages=[{"role": "user", "content": "hi"}])

    assert response.finish_reason == "error"
    assert response.content.startswith("Error calling LLM")


@pytest.mark.asyncio
async def test_stream_without_chunks_yields_empty_stop_response(tmp_path, monkeypatch) -> None:
    _sign_in(tmp_path, monkeypatch)

    async def empty(**kwargs):
        return _EmptyStream()

    provider = CodeBuddyHTTPProvider()
    monkeypatch.setattr(provider._client.chat.completions, "create", empty)

    response = await provider.chat_stream(messages=[{"role": "user", "content": "hi"}])

    assert response.finish_reason == "stop"
    assert response.content is None


# ----------------------------------------------------------------------
# codebuddy_http_available / sdk_installed
# ----------------------------------------------------------------------


def test_http_available_with_explicit_key_short_circuits(monkeypatch) -> None:
    def forbidden():
        raise AssertionError("an explicit key must answer without touching the session file")

    monkeypatch.setattr(http_module, "load_credentials", forbidden)

    assert codebuddy_http_available("cb-key") is True


def test_http_available_with_env_key_short_circuits(monkeypatch) -> None:
    def forbidden():
        raise AssertionError("an env key must answer without touching the session file")

    monkeypatch.setattr(http_module, "load_credentials", forbidden)
    monkeypatch.setenv("CODEBUDDY_API_KEY", "  env-key  ")

    assert codebuddy_http_available() is True


def test_http_available_follows_session_state(tmp_path, monkeypatch) -> None:
    assert codebuddy_http_available() is False

    _sign_in(tmp_path, monkeypatch)

    assert codebuddy_http_available() is True


def test_sdk_installed_reflects_find_spec(monkeypatch) -> None:
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name: object() if name == "codebuddy_agent_sdk" else None,
    )
    assert sdk_installed() is True

    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    assert sdk_installed() is False


# ----------------------------------------------------------------------
# build_codebuddy_provider dispatch
# ----------------------------------------------------------------------


def test_dispatch_backend_env_http_forces_http_despite_sdk(monkeypatch) -> None:
    monkeypatch.setenv("DEEPTUTOR_CODEBUDDY_BACKEND", "http")
    monkeypatch.setattr(http_module, "sdk_installed", lambda: True)

    assert isinstance(build_codebuddy_provider(), CodeBuddyHTTPProvider)


def test_dispatch_backend_env_sdk_uses_sdk_when_installed(monkeypatch) -> None:
    monkeypatch.setenv("DEEPTUTOR_CODEBUDDY_BACKEND", "sdk")
    monkeypatch.setattr(http_module, "sdk_installed", lambda: True)

    provider = build_codebuddy_provider()

    assert isinstance(provider, CodeBuddyProvider)
    assert not isinstance(provider, CodeBuddyHTTPProvider)


def test_dispatch_backend_env_sdk_falls_back_to_http_without_sdk(monkeypatch) -> None:
    monkeypatch.setenv("DEEPTUTOR_CODEBUDDY_BACKEND", "sdk")
    monkeypatch.setattr(http_module, "sdk_installed", lambda: False)

    assert isinstance(build_codebuddy_provider(), CodeBuddyHTTPProvider)


def test_dispatch_without_auth_or_env_picks_sdk_when_present(monkeypatch) -> None:
    monkeypatch.setattr(http_module, "sdk_installed", lambda: True)

    assert isinstance(build_codebuddy_provider(), CodeBuddyProvider)
