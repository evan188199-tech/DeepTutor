from datetime import datetime, timezone
import json
from pathlib import Path
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from deeptutor.multi_user.paths import owner_secrets_dir
from deeptutor.video_learning.invidious_auth import (
    AuthStateStore,
    InvidiousTokenStore,
    disconnect_account,
    get_authorization_url,
    get_invidious_home_feed,
    get_invidious_public_base_url,
    get_user_history_ids,
    get_user_preferences,
    sync_watch_history,
)
from deeptutor.video_learning.service import (
    TimedMediaError,
    _is_html_error_response,
    _is_local_host,
    _rank_captions,
    _validate_instance_url,
)


def test_tailnet_host_validation():
    assert _is_local_host("localhost")
    assert _is_local_host("127.0.0.1")
    assert _is_local_host("100.101.207.44")  # Tailscale CGNAT IP
    assert _is_local_host("mac-mini.tail47dc0a.ts.net")  # Tailscale cert domain
    assert _is_local_host("192.168.1.50")  # LAN private IP
    assert not _is_local_host("8.8.8.8")
    assert not _is_local_host("youtube.com")

    # Tailscale IP is allowed via HTTP
    valid_tailnet = _validate_instance_url("http://100.101.207.44:3000")
    assert valid_tailnet == "http://100.101.207.44:3000"

    # Public IP requires HTTPS
    with pytest.raises(TimedMediaError, match="HTTPS"):
        _validate_instance_url("http://93.184.216.34:3000")


def test_public_invidious_url_skips_ssrf_dns(monkeypatch):
    monkeypatch.setattr(
        "deeptutor.services.config.runtime_settings.load_integrations_settings",
        lambda: {"invidious_public_base_url": "https://uses-firewall-coupon-wal.trycloudflare.com/"},
    )
    assert get_invidious_public_base_url() == "https://uses-firewall-coupon-wal.trycloudflare.com"


def test_invidious_token_store(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("deeptutor.multi_user.paths.SYSTEM_ROOT", tmp_path / "system")
    owner_a = "user_a"
    owner_b = "user_b"

    assert InvidiousTokenStore.get_token(owner_a) is None
    assert not InvidiousTokenStore.has_token(owner_a)

    InvidiousTokenStore.set_token(owner_a, "token_alpha_123")
    assert InvidiousTokenStore.has_token(owner_a)
    assert InvidiousTokenStore.get_token(owner_a) == "token_alpha_123"

    # Owner isolation: user_b cannot see user_a token
    assert InvidiousTokenStore.get_token(owner_b) is None

    # Delete token
    InvidiousTokenStore.delete_token(owner_a)
    assert InvidiousTokenStore.get_token(owner_a) is None


@pytest.mark.asyncio
async def test_auth_state_store():
    owner = "test_owner"
    state = await AuthStateStore.create_state(owner, ttl_seconds=2)
    assert state

    # Single-use consumption
    consumed_owner = await AuthStateStore.validate_and_consume_state(state)
    assert consumed_owner == owner

    # Second consumption must return None (consumed)
    assert await AuthStateStore.validate_and_consume_state(state) is None

    # Expired state
    expired_state = await AuthStateStore.create_state(owner, ttl_seconds=0)
    time.sleep(0.05)
    assert await AuthStateStore.validate_and_consume_state(expired_state) is None


@pytest.mark.asyncio
async def test_authorization_url_generation(monkeypatch):
    monkeypatch.setattr(
        "deeptutor.services.config.runtime_settings.load_integrations_settings",
        lambda: {"invidious_public_base_url": "http://100.101.207.44:3000"},
    )
    monkeypatch.setattr(
        "deeptutor.services.config.runtime_settings.load_system_settings",
        lambda: {"next_public_api_base_external": "http://100.101.207.44:8001"},
    )
    auth_url = await get_authorization_url("admin_user")
    assert auth_url.startswith("http://100.101.207.44:3000/authorize_token?")
    assert "scopes=" in auth_url
    assert "callback_url=" in auth_url
    assert "100.101.207.44%3A8001" in auth_url or "100.101.207.44:8001" in auth_url
    query = parse_qs(urlsplit(auth_url).query)
    assert query["scopes"] == [
        "GET:preferences,GET:feed,GET:playlists,GET:history,POST:history/*,"
        "POST:tokens/unregister,POST:deeptutor/renderer-session*,POST:/deeptutor/renderer-session*"
    ]


@pytest.mark.asyncio
async def test_authorization_url_uses_current_tunnel_when_external_base_is_empty(
    monkeypatch, tmp_path: Path
):
    system_root = tmp_path / "system"
    state_path = system_root / "auth" / "deeptutor_tunnel.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps({"url": "https://current-deeptutor.trycloudflare.com"}),
        encoding="utf-8",
    )
    monkeypatch.setattr("deeptutor.multi_user.paths.SYSTEM_ROOT", system_root)
    monkeypatch.setattr(
        "deeptutor.services.config.runtime_settings.load_integrations_settings",
        lambda: {"invidious_public_base_url": "https://invidious.example"},
    )
    monkeypatch.setattr(
        "deeptutor.services.config.runtime_settings.load_system_settings",
        lambda: {"next_public_api_base_external": ""},
    )
    monkeypatch.setattr(
        "deeptutor.video_learning.invidious_auth._validate_instance_url",
        lambda value: value,
    )
    auth_url = await get_authorization_url("admin_user")
    query = parse_qs(urlsplit(auth_url).query)
    callback_url = query["callback_url"][0]
    assert callback_url.startswith(
        "https://current-deeptutor.trycloudflare.com/api/v1/video-learning/invidious/callback?state="
    )


def test_html_error_detection():
    assert _is_html_error_response("<!DOCTYPE html><html><title>Sorry...</title></html>")
    assert _is_html_error_response("<HTML><head>...</head><body>Google error</body></html>")
    assert not _is_html_error_response("WEBVTT\n\n00:00.000 --> 00:05.000\nHello world")
    assert not _is_html_error_response('{"cues": [{"text": "Hello"}]}')


def test_rank_captions():
    captions = [
        {"label": "English (auto-generated)", "languageCode": "en", "autoGenerated": True},
        {"label": "English", "languageCode": "en", "autoGenerated": False},
        {"label": "Chinese (Simplified)", "languageCode": "zh-CN", "autoGenerated": False},
    ]
    ranked = _rank_captions(captions, preferred_language="zh-CN")
    assert ranked[0]["languageCode"] == "zh-CN"
    assert ranked[1]["autoGenerated"] is False


@pytest.mark.asyncio
async def test_watch_history_sync_and_home_feed(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("deeptutor.multi_user.paths.SYSTEM_ROOT", tmp_path / "system")
    owner = "test_user_history"
    InvidiousTokenStore.set_token(owner, "mock_token")

    monkeypatch.setattr(
        "deeptutor.services.config.runtime_settings.load_integrations_settings",
        lambda: {
            "invidious_base_url": "http://127.0.0.1:3000",
            "invidious_public_base_url": "http://100.101.207.44:3000",
        },
    )

    class MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/api/v1/auth/history/dQw4w9WgXcQ" in url:
                return httpx.Response(200, json={"status": "ok"})
            if "/api/v1/auth/history" in url:
                return httpx.Response(200, json=[{"videoId": "dQw4w9WgXcQ", "title": "Never Gonna Give You Up"}])
            if "/api/v1/auth/preferences" in url:
                return httpx.Response(200, json={"default_home": "Popular"})
            if "/api/v1/popular" in url:
                return httpx.Response(200, json=[
                    {"videoId": "dQw4w9WgXcQ", "title": "Rick Astley", "author": "RickAstleyVEVO", "lengthSeconds": 213, "viewCount": 1000000},
                    {"videoId": "other123456", "title": "Other Video", "author": "OtherAuthor", "lengthSeconds": 100, "viewCount": 500},
                ])
            return httpx.Response(404)

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        "deeptutor.video_learning.invidious_auth.httpx.AsyncClient",
        lambda *args, **kwargs: real_async_client(transport=MockTransport()),
    )

    # Test sync history
    ok, reason = await sync_watch_history(owner, "dQw4w9WgXcQ")
    assert ok is True
    assert reason == "synced"

    # Test home feed
    feed = await get_invidious_home_feed(owner)
    assert feed["connected"] is True
    assert feed["default_home"] == "Popular"
    assert len(feed["items"]) == 2
    # dQw4w9WgXcQ is in history, so watched must be True
    assert feed["items"][0]["video_id"] == "dQw4w9WgXcQ"
    assert feed["items"][0]["watched"] is True
    assert feed["items"][1]["watched"] is False


@pytest.mark.asyncio
async def test_subscriptions_feed_dict_format(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("deeptutor.multi_user.paths.SYSTEM_ROOT", tmp_path / "system")
    owner = "test_user_subs"
    InvidiousTokenStore.set_token(owner, "mock_token")

    monkeypatch.setattr(
        "deeptutor.services.config.runtime_settings.load_integrations_settings",
        lambda: {
            "invidious_base_url": "http://127.0.0.1:3000",
            "invidious_public_base_url": "http://100.101.207.44:3000",
        },
    )

    class MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/api/v1/auth/preferences" in url:
                return httpx.Response(200, json={"default_home": "Subscriptions"})
            if "/api/v1/auth/history" in url:
                return httpx.Response(200, json=[])
            if "/api/v1/auth/feed" in url:
                return httpx.Response(200, json={
                    "notifications": [],
                    "videos": [
                        {
                            "videoId": "subVid12345",
                            "title": "Subscribed Channel Video",
                            "author": "CoolChannel",
                            "lengthSeconds": 450,
                            "viewCount": 12000,
                            "publishedText": "2 hours ago",
                        }
                    ]
                })
            return httpx.Response(404)

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        "deeptutor.video_learning.invidious_auth.httpx.AsyncClient",
        lambda *args, **kwargs: real_async_client(transport=MockTransport()),
    )

    feed = await get_invidious_home_feed(owner, tab="Subscriptions")
    assert feed["connected"] is True
    assert feed["current_tab"] == "Subscriptions"
    assert len(feed["items"]) == 1
    assert feed["items"][0]["video_id"] == "subVid12345"
    assert feed["items"][0]["title"] == "Subscribed Channel Video"
    assert feed["items"][0]["author"] == "CoolChannel"
    assert feed["items"][0]["duration_seconds"] == 450


@pytest.mark.asyncio
async def test_history_merges_local_and_remote(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("deeptutor.multi_user.paths.SYSTEM_ROOT", tmp_path / "system")
    owner = "test_user_hist_merge"
    InvidiousTokenStore.set_token(owner, "mock_token")

    from deeptutor.video_learning.service import TimedMediaStore
    store = TimedMediaStore(root=tmp_path / "timed_media")
    store.create({
        "type": "timed_media",
        "material_id": "a" * 32,
        "source": {"provider": "youtube", "video_id": "localVid111", "duration_seconds": 300},
        "metadata": {"title": "Local Studied Video", "author": "DeepTutor Author", "duration_seconds": 300},
        "learning": {"last_position": 45.0, "notes": [{"text": "My note"}], "marks": []},
        "updated_at": "2026-08-28T10:00:00Z",
    })
    monkeypatch.setattr("deeptutor.video_learning.service.get_timed_media_store", lambda: store)

    monkeypatch.setattr(
        "deeptutor.services.config.runtime_settings.load_integrations_settings",
        lambda: {
            "invidious_base_url": "http://127.0.0.1:3000",
            "invidious_public_base_url": "http://100.101.207.44:3000",
        },
    )

    class MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/api/v1/auth/preferences" in url:
                return httpx.Response(200, json={"default_home": "History"})
            if "/api/v1/auth/history" in url:
                return httpx.Response(200, json=[
                    {"videoId": "remoteVid222", "title": "Remote Invidious Video", "author": "Remote Creator", "lengthSeconds": 200},
                ])
            return httpx.Response(404)

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        "deeptutor.video_learning.invidious_auth.httpx.AsyncClient",
        lambda *args, **kwargs: real_async_client(transport=MockTransport()),
    )

    feed = await get_invidious_home_feed(owner, tab="History")
    assert feed["connected"] is True
    assert feed["current_tab"] == "History"
    assert len(feed["items"]) == 2
    video_ids = {it["video_id"] for it in feed["items"]}
    assert "localVid111" in video_ids
    assert "remoteVid222" in video_ids
    local_item = next(it for it in feed["items"] if it["video_id"] == "localVid111")
    assert local_item["watched"] is True
    assert local_item["notes_count"] == 1
    assert local_item["last_position_seconds"] == 45.0
