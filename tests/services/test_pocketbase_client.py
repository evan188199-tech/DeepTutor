"""Contract tests for deeptutor.services.pocketbase_client.

All PocketBase SDK and HTTP interactions are stubbed; no real service is
contacted. Covers request construction, error mapping (4xx/5xx/timeout/
network), retry/fallback contracts and the singleton/token caches.
"""

from __future__ import annotations

import sys
import time
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from deeptutor.services import pocketbase_client as pb_client

SETTINGS: dict[str, str] = {
    "url": "http://pb.test:8090",
    "admin_email": "admin@pb.test",
    "admin_password": "secret",
}


@pytest.fixture(autouse=True)
def _reset_module_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate singleton and token-cache globals; pin integrations settings."""
    monkeypatch.setattr(pb_client, "_client", None)
    monkeypatch.setattr(pb_client, "_client_initialised", False)
    monkeypatch.setattr(pb_client, "_client_key", "")
    monkeypatch.setattr(pb_client, "_TOKEN_CACHE", {})
    monkeypatch.setattr(pb_client, "_pocketbase_settings", lambda: dict(SETTINGS))


def _set_settings(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    values = {**SETTINGS, **overrides}
    monkeypatch.setattr(pb_client, "_pocketbase_settings", lambda: dict(values))


class _FakePocketBase:
    """Stub for the pocketbase SDK client; records calls, never touches network."""

    instances: list["_FakePocketBase"] = []
    auth_error: Exception | None = None
    refresh_error: Exception | None = None
    record: Any | None = None

    def __init__(self, url: str) -> None:
        self.url = url
        self.saved_tokens: list[str] = []
        self.auth_store = SimpleNamespace(save=self._save_token)
        self.admin_credentials: tuple[str, str] | None = None
        self.refresh_calls = 0
        type(self).instances.append(self)

    def _save_token(self, token: str, record: Any) -> None:
        self.saved_tokens.append(token)

    def collection(self, name: str) -> "_FakePocketBase":
        return self

    def auth_refresh(self) -> Any:
        self.refresh_calls += 1
        if type(self).refresh_error is not None:
            raise type(self).refresh_error
        return SimpleNamespace(record=type(self).record)

    @property
    def admins(self) -> "_FakePocketBase":
        return self

    def auth_with_password(self, email: str, password: str) -> None:
        self.admin_credentials = (email, password)
        if type(self).auth_error is not None:
            raise type(self).auth_error


@pytest.fixture()
def fake_sdk(monkeypatch: pytest.MonkeyPatch) -> type[_FakePocketBase]:
    import pocketbase as sdk

    _FakePocketBase.instances = []
    _FakePocketBase.auth_error = None
    _FakePocketBase.refresh_error = None
    _FakePocketBase.record = None
    monkeypatch.setattr(sdk, "PocketBase", _FakePocketBase)
    return _FakePocketBase


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _FakeAsyncClient:
    """Stub for httpx.AsyncClient used by ping_pocketbase."""

    instances: list["_FakeAsyncClient"] = []
    status_code: int = 200
    error: Exception | None = None

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.requested_urls: list[str] = []
        type(self).instances.append(self)

    async def get(self, url: str) -> _FakeResponse:
        self.requested_urls.append(url)
        if type(self).error is not None:
            raise type(self).error
        return _FakeResponse(type(self).status_code)

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False


@pytest.fixture()
def fake_http(monkeypatch: pytest.MonkeyPatch) -> type[_FakeAsyncClient]:
    _FakeAsyncClient.instances = []
    _FakeAsyncClient.status_code = 200
    _FakeAsyncClient.error = None
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    return _FakeAsyncClient


# ---------------------------------------------------------------------------
# is_pocketbase_enabled
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("url,expected", [("http://pb.test:8090", True), ("", False)])
def test_is_pocketbase_enabled_follows_configured_url(
    monkeypatch: pytest.MonkeyPatch, url: str, expected: bool
) -> None:
    _set_settings(monkeypatch, url=url)
    assert pb_client.is_pocketbase_enabled() is expected


def test_is_pocketbase_enabled_strips_trailing_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    def fake_settings() -> dict[str, str]:
        values = {**SETTINGS, "url": "http://pb.test:8090/"}
        captured["raw"] = values["url"]
        return values

    monkeypatch.setattr(pb_client, "_pocketbase_settings", fake_settings)
    assert pb_client.is_pocketbase_enabled() is True


# ---------------------------------------------------------------------------
# get_pb_client
# ---------------------------------------------------------------------------


def test_get_pb_client_requires_configured_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_settings(monkeypatch, url="")
    with pytest.raises(RuntimeError, match="not configured"):
        pb_client.get_pb_client()


def test_get_pb_client_missing_sdk_maps_import_error_to_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "pocketbase", None)
    with pytest.raises(RuntimeError, match="not installed"):
        pb_client.get_pb_client()


def test_get_pb_client_authenticates_admin_and_caches_singleton(fake_sdk) -> None:
    first = pb_client.get_pb_client()
    second = pb_client.get_pb_client()

    assert first is second
    assert len(fake_sdk.instances) == 1
    assert first.url == "http://pb.test:8090"
    assert first.admin_credentials == ("admin@pb.test", "secret")


def test_get_pb_client_rebuilds_when_credentials_change(
    monkeypatch: pytest.MonkeyPatch, fake_sdk
) -> None:
    first = pb_client.get_pb_client()
    _set_settings(monkeypatch, admin_email="other@pb.test")
    second = pb_client.get_pb_client()

    assert first is not second
    assert len(fake_sdk.instances) == 2
    assert second.admin_credentials == ("other@pb.test", "secret")


def test_get_pb_client_auth_failure_raises_and_is_not_cached(fake_sdk) -> None:
    fake_sdk.auth_error = RuntimeError("401 unauthorized")

    with pytest.raises(RuntimeError, match="401 unauthorized"):
        pb_client.get_pb_client()

    assert pb_client._client_initialised is False
    assert pb_client._client is None

    fake_sdk.auth_error = None
    retried = pb_client.get_pb_client()
    assert len(fake_sdk.instances) == 2
    assert retried.admin_credentials == ("admin@pb.test", "secret")


def test_get_pb_client_without_admin_credentials_skips_auth(
    monkeypatch: pytest.MonkeyPatch, fake_sdk, caplog: pytest.LogCaptureFixture
) -> None:
    _set_settings(monkeypatch, admin_email="", admin_password="")

    with caplog.at_level("WARNING"):
        client = pb_client.get_pb_client()

    assert client is not None
    assert client.admin_credentials is None
    assert any("without admin privileges" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# validate_pb_token
# ---------------------------------------------------------------------------


def test_validate_pb_token_returns_none_when_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_settings(monkeypatch, url="")
    assert pb_client.validate_pb_token("tok") is None


def test_validate_pb_token_builds_request_with_user_token(fake_sdk) -> None:
    fake_sdk.record = SimpleNamespace(
        email="u@x.test", name=None, username=None, id="r1", role="tutor"
    )
    payload = pb_client.validate_pb_token("tok-123")

    assert payload == {"username": "u@x.test", "role": "tutor"}
    client = fake_sdk.instances[0]
    assert client.url == "http://pb.test:8090"
    assert client.saved_tokens == ["tok-123"]
    assert client.refresh_calls == 1


def test_validate_pb_token_maps_refresh_failure_to_none(fake_sdk) -> None:
    fake_sdk.refresh_error = RuntimeError("400: failed to authenticate")
    assert pb_client.validate_pb_token("bad-token") is None


def test_validate_pb_token_username_precedence(fake_sdk) -> None:
    cases = [
        (
            SimpleNamespace(email="e@x.test", name="n", username="u", id="i", role="admin"),
            {"username": "e@x.test", "role": "admin"},
        ),
        (
            SimpleNamespace(email=None, name="n", username="u", id="i", role="user"),
            {"username": "n", "role": "user"},
        ),
        (
            SimpleNamespace(email=None, name=None, username="u", id="i", role="learner"),
            {"username": "u", "role": "learner"},
        ),
        (
            SimpleNamespace(email=None, name=None, username=None, id="i-9", role=None),
            {"username": "i-9", "role": "user"},
        ),
    ]
    for record, expected in cases:
        fake_sdk.record = record
        assert pb_client.validate_pb_token(f"tok-{expected['username']}") == expected


def test_validate_pb_token_serves_cached_payload_within_ttl(fake_sdk) -> None:
    fake_sdk.record = SimpleNamespace(
        email="u@x.test", name=None, username=None, id="r1", role="user"
    )
    first = pb_client.validate_pb_token("tok")

    fake_sdk.refresh_error = RuntimeError("401: token expired")
    second = pb_client.validate_pb_token("tok")

    assert first == second == {"username": "u@x.test", "role": "user"}
    assert fake_sdk.instances[0].refresh_calls == 1
    assert len(fake_sdk.instances) == 1


def test_validate_pb_token_refreshes_after_cache_ttl_expiry(
    monkeypatch: pytest.MonkeyPatch, fake_sdk
) -> None:
    fake_sdk.record = SimpleNamespace(
        email="new@x.test", name=None, username=None, id="r2", role="user"
    )
    pb_client._TOKEN_CACHE["tok"] = (
        {"username": "stale", "role": "user"},
        time.monotonic() - 1.0,
    )

    payload = pb_client.validate_pb_token("tok")

    assert payload == {"username": "new@x.test", "role": "user"}
    assert len(fake_sdk.instances) == 1
    assert fake_sdk.instances[0].refresh_calls == 1


def test_validate_pb_token_failure_is_not_cached(fake_sdk) -> None:
    fake_sdk.refresh_error = RuntimeError("network down")
    assert pb_client.validate_pb_token("tok") is None
    assert "tok" not in pb_client._TOKEN_CACHE


def test_validate_pb_token_cache_ttl_is_sixty_seconds() -> None:
    assert pb_client._TOKEN_CACHE_TTL == 60.0


# ---------------------------------------------------------------------------
# ping_pocketbase
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ping_pocketbase_returns_false_when_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_settings(monkeypatch, url="")
    assert await pb_client.ping_pocketbase() is False


@pytest.mark.asyncio
async def test_ping_pocketbase_healthy_returns_true(fake_http) -> None:
    assert await pb_client.ping_pocketbase() is True
    client = fake_http.instances[0]
    assert client.kwargs == {"timeout": 5.0}
    assert client.requested_urls == ["http://pb.test:8090/api/health"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 404, 500, 503])
async def test_ping_pocketbase_maps_http_errors_to_false(fake_http, status: int) -> None:
    fake_http.status_code = status
    assert await pb_client.ping_pocketbase() is False


@pytest.mark.asyncio
async def test_ping_pocketbase_maps_timeout_to_false(fake_http) -> None:
    fake_http.error = httpx.TimeoutException("timed out after 5s")
    assert await pb_client.ping_pocketbase() is False


@pytest.mark.asyncio
async def test_ping_pocketbase_maps_network_error_to_false(fake_http) -> None:
    fake_http.error = httpx.ConnectError("connection refused")
    assert await pb_client.ping_pocketbase() is False
