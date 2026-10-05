"""Focused persistence and parsing coverage for Invidious account binding.

Exercises the owner-private store (round-trip, forget, corrupted-file
tolerance, concurrent writes) and the HTTP boundary's response-parsing guards.
All filesystem work lives under tmp_path via a redirected SYSTEM_ROOT; no real
Invidious instance or network is involved.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import stat
import time
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from deeptutor.multi_user import paths
from deeptutor.video_learning import invidious_account as account
from deeptutor.video_learning import invidious_account_client as account_client
from deeptutor.video_learning import invidious_account_storage as account_storage
from deeptutor.video_learning.service import TimedMediaError


def _settings(base: str) -> dict[str, Any]:
    return {
        "version": 1,
        "default_provider": "youtube",
        "youtube": {"transcript_provider": "none"},
        "invidious": {"api_base_url": base, "public_base_url": ""},
    }


def _state_from_authorize_url(url: str) -> str:
    callback_url = parse_qs(urlsplit(url).query)["callback_url"][0]
    return parse_qs(urlsplit(callback_url).query)["state"][0]


def _mock_async_client(
    handler: Callable[[httpx.Request], httpx.Response],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = account_client.httpx.AsyncClient

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        return original(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(account_client.httpx, "AsyncClient", factory)


@pytest.fixture
def system_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = (tmp_path / "data" / "system").resolve()
    monkeypatch.setattr(paths, "SYSTEM_ROOT", root)
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", (tmp_path / "data").resolve())
    monkeypatch.setattr(paths, "USERS_ROOT", (tmp_path / "data" / "users").resolve())
    return root


def test_account_roundtrip_is_owner_scoped_and_private(system_root: Path) -> None:
    payload = {"version": 1, "token": {"session": "s1"}}
    other = {"version": 1, "token": {"session": "s2"}}

    account_storage.write_account("u_ada", payload)
    account_storage.write_account("u_bob", other)

    ada_path = account_storage.account_path("u_ada")
    assert account_storage.read_account("u_ada") == payload
    assert account_storage.read_account("u_bob") == other
    assert stat.S_IMODE(ada_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(ada_path.parent.stat().st_mode) == 0o700


def test_forget_account_removes_the_secret_and_tolerates_a_missing_record(
    system_root: Path,
) -> None:
    account_storage.write_account("u_ada", {"version": 1})

    account_storage.forget_account("u_ada")

    assert account_storage.read_account("u_ada") == {}
    assert not account_storage.account_path("u_ada").exists()
    account_storage.forget_account("u_ada")


def test_corrupted_account_file_reads_as_disconnected_and_local_forget_still_works(
    system_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = account_storage.account_path("u_ada")
    path.write_bytes(b"\xff\xfe not json {")
    assert account_storage.read_account("u_ada") == {}
    assert account.invidious_account_status("u_ada") == {"connected": False}

    async def revoke(*, api_base_url: str, token: dict[str, Any]) -> None:
        raise AssertionError("a corrupted local record must not reach the instance")

    monkeypatch.setattr(account, "_revoke_token", revoke)

    status = asyncio.run(account.disconnect_invidious_account(owner_id="u_ada"))
    assert status == {"connected": False}
    assert not path.exists()


@pytest.mark.parametrize("raw", [b"[1, 2, 3]", b'"u_ada"', b"null", b"{ broken"])
def test_non_object_account_payloads_are_treated_as_absent(
    system_root: Path,
    raw: bytes,
) -> None:
    path = account_storage.account_path("u_ada")

    path.write_bytes(raw)

    assert account_storage.read_account("u_ada") == {}
    assert account.invidious_account_status("u_ada") == {"connected": False}


def test_purge_expired_removes_corrupted_and_expired_flows_but_keeps_live_ones(
    system_root: Path,
) -> None:
    def write_flow(state: str, expires_at: float) -> None:
        account_storage.write_private_json(
            account_storage.flow_path("u_ada", state),
            {
                "version": 1,
                "owner_id": "u_ada",
                "api_base_url": "https://a.test",
                "callback_url": "https://a.test/callback",
                "expires_at": expires_at,
            },
        )

    write_flow("state-live", time.time() + 600.0)
    write_flow("state-expired", time.time() - 600.0)
    corrupted = account_storage.pending_dir("u_ada") / "garbage.json"
    corrupted.write_bytes(b"{ not json")

    account_storage.purge_expired("u_ada", now=time.time())

    assert not corrupted.exists()
    assert not account_storage.flow_path("u_ada", "state-expired").exists()
    claimed = account_storage.consume_pending_flow("u_ada", "state-live")
    assert claimed is not None
    assert claimed.api_base_url == "https://a.test"


def test_replace_pending_flow_invalidates_same_instance_and_keeps_other_instances(
    system_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_uri = "https://app.example.test/callback"

    def begin(base: str) -> str:
        monkeypatch.setattr(account, "load_video_learning_settings", lambda: _settings(base))
        url = account.begin_invidious_account_authorization(
            owner_id="u_ada", redirect_uri=redirect_uri
        )
        return _state_from_authorize_url(url)

    state_a1 = begin("https://a.test")
    state_a2 = begin("https://a.test")
    assert not account_storage.flow_path("u_ada", state_a1).exists()
    assert account_storage.flow_path("u_ada", state_a2).is_file()

    state_b = begin("https://b.test")
    assert account_storage.flow_path("u_ada", state_a2).is_file()
    assert account_storage.flow_path("u_ada", state_b).is_file()

    state_a3 = begin("https://a.test")
    assert not account_storage.flow_path("u_ada", state_a2).exists()
    assert account_storage.flow_path("u_ada", state_b).is_file()
    assert account_storage.flow_path("u_ada", state_a3).is_file()


def test_concurrent_account_writes_stay_valid_and_leave_no_temp_residue(
    system_root: Path,
) -> None:
    payloads = [{"version": 1, "revision": index} for index in range(12)]

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(
            executor.map(
                lambda payload: account_storage.write_account("u_ada", payload),
                payloads,
            )
        )

    final = account_storage.read_account("u_ada")
    assert final in payloads
    assert stat.S_IMODE(account_storage.account_path("u_ada").stat().st_mode) == 0o600
    residue = [
        entry.name
        for entry in account_storage.asset_dir("u_ada").iterdir()
        if entry.name != "pending"
    ]
    assert residue == ["account.json"]
    assert list(account_storage.pending_dir("u_ada").iterdir()) == []


def test_concurrent_writes_to_distinct_owners_stay_isolated(system_root: Path) -> None:
    payloads = {f"u_owner_{index}": {"version": 1, "revision": index} for index in range(6)}

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(
            executor.map(
                lambda item: account_storage.write_account(item[0], item[1]),
                payloads.items(),
            )
        )

    for owner_id, payload in payloads.items():
        assert account_storage.read_account(owner_id) == payload


@pytest.mark.parametrize(
    ("status_code", "body", "match"),
    [
        (200, "not-json", "invalid account preferences"),
        (200, "[]", "invalid account preferences"),
        (200, '"locale"', "invalid account preferences"),
        (200, "42", "invalid account preferences"),
        (401, "{}", "verification failed with HTTP 401"),
        (500, "{}", "verification failed with HTTP 500"),
    ],
)
def test_request_preferences_only_accepts_json_object_bodies(
    status_code: int,
    body: str,
    match: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_async_client(lambda request: httpx.Response(status_code, text=body), monkeypatch)

    with pytest.raises(TimedMediaError, match=match):
        asyncio.run(
            account_client.request_preferences(
                api_base_url="https://invidious.example.test",
                token={"session": "s", "signature": "g"},
            )
        )


def test_request_preferences_returns_the_parsed_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_async_client(lambda request: httpx.Response(200, json={"locale": "en-US"}), monkeypatch)

    preferences = asyncio.run(
        account_client.request_preferences(
            api_base_url="https://invidious.example.test",
            token={"session": "s", "signature": "g"},
        )
    )
    assert preferences == {"locale": "en-US"}


@pytest.mark.parametrize(
    ("status_code", "body", "match"),
    [
        (200, "oops", "could not load videos"),
        (200, "42", "could not load videos"),
        (200, '"catalog"', "could not load videos"),
        (401, "{}", "Reconnect your Invidious account"),
        (403, "{}", "Reconnect your Invidious account"),
        (503, "{}", "could not load videos"),
    ],
)
def test_request_catalog_rejects_non_collection_and_error_bodies(
    status_code: int,
    body: str,
    match: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_async_client(lambda request: httpx.Response(status_code, text=body), monkeypatch)

    with pytest.raises(TimedMediaError, match=match):
        asyncio.run(
            account_client.request_catalog(
                api_base_url="https://invidious.example.test",
                path="/api/v1/auth/feed",
                params={},
                token=None,
            )
        )


def test_request_catalog_returns_parsed_list_bodies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_async_client(
        lambda request: httpx.Response(200, json=[{"videoId": "aircAruvnKk"}]),
        monkeypatch,
    )

    data = asyncio.run(
        account_client.request_catalog(
            api_base_url="https://invidious.example.test",
            path="/api/v1/search",
            params={},
            token=None,
        )
    )
    assert data == [{"videoId": "aircAruvnKk"}]


def test_bearer_token_serialization_is_compact_and_unicode_safe() -> None:
    token = {"session": "v1:会话+值", "signature": "签", "scopes": ["GET:preferences"]}

    serialized = account_client.bearer_token(token)

    assert "会话" in serialized
    assert ": " not in serialized
    assert ", " not in serialized
    assert json.loads(serialized) == token


@pytest.mark.parametrize(
    ("raw", "match"),
    [
        ("", "invalid account token"),
        ("null", "invalid account token"),
        ("[1, 2]", "invalid account token"),
        ('{"session": "s"}', "incomplete account token"),
        ('{"session": "s", "signature": "sig"}', "incomplete account token"),
        (
            '{"session": "s", "signature": "sig", "scopes": "GET:preferences"}',
            "incomplete account token",
        ),
        (
            '{"session": "s", "signature": "sig", "scopes": ["GET:preferences"]}',
            "missing a required scope",
        ),
        (
            json.dumps(
                {
                    "session": "s",
                    "signature": "sig",
                    "scopes": list(account.ACCOUNT_SCOPES),
                    "expire": "soon",
                }
            ),
            "invalid token expiration",
        ),
        ("x" * 8193, "invalid account token"),
    ],
)
def test_parse_token_rejects_malformed_payloads(raw: str, match: str) -> None:
    with pytest.raises(TimedMediaError, match=match):
        account._parse_token(raw)
