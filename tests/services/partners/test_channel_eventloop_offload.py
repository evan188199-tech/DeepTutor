"""Event-loop blocking regression tests for the zulip/msteams/weixin channels.

Each test drives a coroutine that used to run a synchronous blocking segment
(retry-with-sleep auth, queue deregister, thread join, HTTP server shutdown,
media file read+MD5, AES-ECB encryption) directly on the event loop, and
asserts a concurrently ticking heartbeat keeps running while the coroutine
makes progress. The blocking segments are simulated with short sleeps at the
exact call sites involved, so the tests fail as long as those calls execute
on the loop and pass once they are offloaded to worker threads.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels import weixin as weixin_mod
from deeptutor.partners.channels.msteams import MSTeamsChannel, MSTeamsConfig
from deeptutor.partners.channels.weixin import WeixinChannel, WeixinConfig
from deeptutor.partners.channels.zulip import ZulipChannel, ZulipConfig
from deeptutor.partners.config import paths as partner_paths

TICK_S = 0.02
BLOCK_S = 0.5
MAX_ALLOWED_GAP_S = 0.3


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    """Redirect channel runtime state dirs to a temp directory."""
    monkeypatch.setattr(partner_paths, "get_runtime_subdir", lambda name: tmp_path)
    return tmp_path


def _bus() -> MagicMock:
    bus = MagicMock(spec=MessageBus)
    bus.publish_inbound = AsyncMock()
    return bus


def _zulip_channel(**overrides) -> ZulipChannel:
    defaults = {
        "enabled": True,
        "site": "https://example.zulipchat.com",
        "email": "bot@example.com",
        "api_key": "secret-key-123",
        "allow_from": ["*"],
        "group_policy": "mention",
        "timeout": 60.0,
    }
    defaults.update(overrides)
    return ZulipChannel(ZulipConfig.model_validate(defaults), _bus())


def _msteams_channel() -> MSTeamsChannel:
    config = MSTeamsConfig.model_validate(
        {
            "enabled": True,
            "app_id": "app-123",
            "app_password": "secret-pass",
            "allow_from": ["*"],
        }
    )
    return MSTeamsChannel(config, _bus())


def _weixin_channel() -> WeixinChannel:
    config = WeixinConfig.model_validate(
        {"enabled": True, "allow_from": ["*"], "token": "token-123"}
    )
    return WeixinChannel(config, _bus())


async def _max_heartbeat_gap_while(awaitable, probe=None) -> float:
    """Await ``awaitable`` while a heartbeat task ticks on the event loop.

    Returns the largest gap in seconds between consecutive heartbeat ticks.
    A synchronous blocking segment inside the awaited coroutine freezes the
    heartbeat together with the loop, producing a gap of at least the block
    duration; once the segment is offloaded the gap stays at the tick period.
    """
    ticks: list[float] = []
    task = asyncio.ensure_future(awaitable)
    while not task.done():
        if probe is not None:
            probe()
        ticks.append(time.monotonic())
        await asyncio.sleep(TICK_S)
    await task
    ticks.append(time.monotonic())
    if len(ticks) < 2:
        return 0.0
    return max(b - a for a, b in zip(ticks, ticks[1:]))


class TestZulipStartAuthOffloaded:
    @pytest.mark.asyncio
    async def test_profile_auth_does_not_block_event_loop(self, monkeypatch):
        ch = _zulip_channel()
        profile = {
            "result": "success",
            "email": "bot@example.com",
            "user_id": 100,
            "full_name": "DeepTutor Bot",
        }

        def blocking_get_profile():
            time.sleep(BLOCK_S)
            return profile

        fake_client = MagicMock()
        fake_client.get_profile.side_effect = blocking_get_profile
        fake_client.register.return_value = {
            "result": "success",
            "queue_id": "q-1",
            "last_event_id": -1,
            "max_message_id": 0,
        }
        fake_client.get_events.return_value = {"result": "success", "events": []}
        fake_zulip = SimpleNamespace(Client=MagicMock(return_value=fake_client))
        monkeypatch.setitem(sys.modules, "zulip", fake_zulip)

        def stop_once_connected() -> None:
            if ch._bot_email:
                ch._running = False

        gap = await _max_heartbeat_gap_while(ch.start(), probe=stop_once_connected)

        assert gap < MAX_ALLOWED_GAP_S
        assert ch._bot_email == "bot@example.com"
        assert ch._bot_user_id == 100
        assert ch.setup_state["status"] == "connected"
        assert ch._listener_thread is not None
        ch._listener_thread.join(timeout=5)


class TestZulipStopOffloaded:
    @pytest.mark.asyncio
    async def test_stop_deregister_does_not_block_event_loop(self):
        ch = _zulip_channel()
        mock_client = MagicMock()

        def blocking_deregister(queue_id):
            time.sleep(BLOCK_S)

        mock_client.deregister.side_effect = blocking_deregister
        ch._client = mock_client
        ch._queue_id = "queue-1"
        ch._running = True

        gap = await _max_heartbeat_gap_while(ch.stop())

        assert gap < MAX_ALLOWED_GAP_S
        mock_client.deregister.assert_called_once_with("queue-1")
        assert ch._queue_id is None
        assert ch._client is None
        assert ch._running is False

    @pytest.mark.asyncio
    async def test_stop_listener_join_does_not_block_event_loop(self):
        ch = _zulip_channel()
        listener = threading.Thread(target=lambda: time.sleep(BLOCK_S), daemon=True)
        listener.start()
        ch._listener_thread = listener
        ch._running = True

        gap = await _max_heartbeat_gap_while(ch.stop())

        assert gap < MAX_ALLOWED_GAP_S
        listener.join(timeout=5)
        assert ch._listener_thread is None


class TestMSTeamsStopOffloaded:
    @pytest.mark.asyncio
    async def test_stop_server_shutdown_does_not_block_event_loop(self, state_dir):
        ch = _msteams_channel()
        server = MagicMock()
        server.shutdown.side_effect = lambda: time.sleep(BLOCK_S)
        ch._server = server
        ch._running = True

        gap = await _max_heartbeat_gap_while(ch.stop())

        assert gap < MAX_ALLOWED_GAP_S
        server.shutdown.assert_called_once()
        server.server_close.assert_called_once()
        assert ch._server is None
        assert ch._running is False

    @pytest.mark.asyncio
    async def test_stop_server_thread_join_does_not_block_event_loop(self, state_dir):
        ch = _msteams_channel()
        ch._server = MagicMock()
        server_thread = threading.Thread(target=lambda: time.sleep(BLOCK_S), daemon=True)
        server_thread.start()
        ch._server_thread = server_thread
        ch._running = True

        gap = await _max_heartbeat_gap_while(ch.stop())

        assert gap < MAX_ALLOWED_GAP_S
        server_thread.join(timeout=5)
        assert ch._server_thread is None


def _patch_weixin_upstream(ch: WeixinChannel) -> tuple[AsyncMock, AsyncMock]:
    async def fake_api_post(url, body):
        if url == "ilink/bot/getuploadurl":
            return {"upload_full_url": "https://cdn.example/upload", "upload_param": ""}
        return {"ret": 0, "errcode": 0}

    api_post = AsyncMock(side_effect=fake_api_post)
    ch._api_post = api_post

    cdn_resp = MagicMock()
    cdn_resp.status_code = 200
    cdn_resp.headers = {"x-encrypted-param": "dl-param"}
    cdn_resp.raise_for_status = MagicMock()
    client = MagicMock()
    client.post = AsyncMock(return_value=cdn_resp)
    ch._client = client
    return api_post, client.post


class TestWeixinMediaOffloaded:
    @pytest.mark.asyncio
    async def test_media_read_and_digest_does_not_block_event_loop(self, tmp_path, monkeypatch):
        ch = _weixin_channel()
        media = tmp_path / "photo.png"
        media.write_bytes(b"x" * 64)
        api_post, cdn_post = _patch_weixin_upstream(ch)

        real_read_bytes = Path.read_bytes

        def slow_read_bytes(self):
            time.sleep(BLOCK_S)
            return real_read_bytes(self)

        monkeypatch.setattr(Path, "read_bytes", slow_read_bytes)

        gap = await _max_heartbeat_gap_while(ch._send_media_file("user-1", str(media), "ctx-1"))

        assert gap < MAX_ALLOWED_GAP_S
        assert cdn_post.await_count == 1
        assert isinstance(cdn_post.call_args.kwargs.get("content"), bytes)

    @pytest.mark.asyncio
    async def test_media_encrypt_does_not_block_event_loop(self, tmp_path, monkeypatch):
        ch = _weixin_channel()
        media = tmp_path / "photo.png"
        media.write_bytes(b"y" * 64)
        api_post, cdn_post = _patch_weixin_upstream(ch)

        real_encrypt = weixin_mod._encrypt_aes_ecb

        def slow_encrypt(data, aes_key_b64):
            time.sleep(BLOCK_S)
            return real_encrypt(data, aes_key_b64)

        monkeypatch.setattr(weixin_mod, "_encrypt_aes_ecb", slow_encrypt)

        gap = await _max_heartbeat_gap_while(ch._send_media_file("user-1", str(media), "ctx-1"))

        assert gap < MAX_ALLOWED_GAP_S
        assert cdn_post.await_count == 1
        assert isinstance(cdn_post.call_args.kwargs.get("content"), bytes)
