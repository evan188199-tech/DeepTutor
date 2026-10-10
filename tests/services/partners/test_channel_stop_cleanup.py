"""Card G — stop() cleanup: resources closed, task cancellations awaited.

Two invariants per channel ``stop()``:

- teardown steps are independent: one resource failing to close must not
  skip the remaining cleanup;
- cancelled background tasks are *awaited* — ``stop()`` returns only once
  every cancellation has been processed, so no task outlives the channel.
"""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels import lark_http
from deeptutor.partners.channels.dingtalk import DingTalkChannel
from deeptutor.partners.channels.discord import DiscordChannel
from deeptutor.partners.channels.feishu import FeishuChannel, _FeishuStreamBuf
from deeptutor.partners.channels.mochat import MochatChannel
from deeptutor.partners.channels.slack import SlackChannel
from deeptutor.partners.channels.telegram import TelegramChannel
from deeptutor.partners.channels.zulip import ZulipChannel


async def _probe_task() -> tuple[asyncio.Task, list[bool]]:
    """A running task that records when its cancellation is actually processed.

    The task is yielded to once so it reaches its await point; the flag then
    only flips after the event loop delivers the CancelledError, so asserting
    on it immediately after ``await stop()`` proves the channel awaited the
    cancellation instead of firing ``cancel()`` and returning.
    """
    processed: list[bool] = []

    async def hang() -> None:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            processed.append(True)
            raise

    task = asyncio.create_task(hang())
    await asyncio.sleep(0)
    return task, processed


# ── Telegram ─────────────────────────────────────────────────────────


def _telegram_channel() -> TelegramChannel:
    ch = TelegramChannel({"enabled": True, "token": "t", "allowFrom": ["*"]}, MessageBus())
    ch._app = SimpleNamespace(
        updater=SimpleNamespace(stop=AsyncMock()),
        stop=AsyncMock(),
        shutdown=AsyncMock(),
    )
    return ch


class TestTelegramStop:
    @pytest.mark.asyncio
    async def test_stop_step_failure_does_not_skip_remaining_steps(self) -> None:
        ch = _telegram_channel()
        app = ch._app
        app.updater.stop.side_effect = RuntimeError("boom")

        await ch.stop()

        app.stop.assert_awaited_once()
        app.shutdown.assert_awaited_once()
        assert ch._app is None

    @pytest.mark.asyncio
    async def test_stop_awaits_typing_and_media_group_tasks(self) -> None:
        ch = _telegram_channel()
        typing_task, typing_done = await _probe_task()
        media_task, media_done = await _probe_task()
        ch._typing_tasks["1"] = typing_task
        ch._media_group_tasks["k"] = media_task

        await ch.stop()

        assert typing_done == [True]
        assert media_done == [True]
        assert typing_task.cancelled() and media_task.cancelled()
        assert ch._typing_tasks == {}
        assert ch._media_group_tasks == {}


# ── Slack ────────────────────────────────────────────────────────────


class TestSlackStop:
    def _channel(self) -> SlackChannel:
        return SlackChannel({"enabled": True, "botToken": "x", "appToken": "y"}, MessageBus())

    @pytest.mark.asyncio
    async def test_socket_close_failure_still_closes_web_client(self) -> None:
        ch = self._channel()
        socket_client = SimpleNamespace(close=AsyncMock(side_effect=RuntimeError("boom")))
        session = SimpleNamespace(close=AsyncMock())
        ch._socket_client = socket_client
        ch._web_client = SimpleNamespace(session=session)

        await ch.stop()

        socket_client.close.assert_awaited_once()
        session.close.assert_awaited_once()
        assert ch._socket_client is None
        assert ch._web_client is None

    @pytest.mark.asyncio
    async def test_stop_without_web_session_is_noop(self) -> None:
        ch = self._channel()
        ch._socket_client = None
        ch._web_client = SimpleNamespace(session=None)

        await ch.stop()

        assert ch._web_client is None


# ── Feishu ───────────────────────────────────────────────────────────


class TestFeishuStop:
    @pytest.mark.asyncio
    async def test_stop_clears_stream_state_and_closes_transport(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ch = FeishuChannel({"enabled": True, "appId": "a", "appSecret": "s"}, MessageBus())
        ch._stream_bufs["chat"] = _FeishuStreamBuf()
        ch._thinking_notices["chat"] = "om_x"
        ch._client = object()
        closed: list[bool] = []
        monkeypatch.setattr(
            lark_http, "close_keep_alive", lambda: closed.append(True), raising=False
        )

        await ch.stop()

        assert ch._stream_bufs == {}
        assert ch._thinking_notices == {}
        assert ch._client is None
        assert closed == [True]


# ── Mochat ───────────────────────────────────────────────────────────


class TestMochatStop:
    @pytest.mark.asyncio
    async def test_stop_awaits_refresh_and_cursor_save_tasks(self, tmp_path) -> None:
        ch = MochatChannel({"enabled": True, "clawToken": "tok"}, MessageBus())
        ch._state_dir = tmp_path
        ch._cursor_path = tmp_path / "session_cursors.json"
        refresh_task, refresh_done = await _probe_task()
        save_task, save_done = await _probe_task()
        ch._refresh_task = refresh_task
        ch._cursor_save_task = save_task

        await ch.stop()

        assert refresh_done == [True]
        assert save_done == [True]
        assert refresh_task.cancelled() and save_task.cancelled()
        assert ch._refresh_task is None
        assert ch._cursor_save_task is None


# ── DingTalk ─────────────────────────────────────────────────────────


class TestDingTalkStop:
    @pytest.mark.asyncio
    async def test_stop_awaits_background_tasks(self) -> None:
        ch = DingTalkChannel({"enabled": True, "clientId": "a", "clientSecret": "b"}, MessageBus())
        task, done = await _probe_task()
        ch._background_tasks.add(task)

        await ch.stop()

        assert done == [True]
        assert task.cancelled()
        assert ch._background_tasks == set()


# ── Discord ──────────────────────────────────────────────────────────


class TestDiscordStop:
    @pytest.mark.asyncio
    async def test_stop_awaits_heartbeat_and_typing_tasks(self) -> None:
        ch = DiscordChannel({"enabled": True, "token": "t"}, MessageBus())
        heartbeat, heartbeat_done = await _probe_task()
        typing, typing_done = await _probe_task()
        ch._heartbeat_task = heartbeat
        ch._typing_tasks["c"] = typing

        await ch.stop()

        assert heartbeat_done == [True]
        assert typing_done == [True]
        assert heartbeat.cancelled() and typing.cancelled()
        assert ch._heartbeat_task is None
        assert ch._typing_tasks == {}


# ── Zulip ────────────────────────────────────────────────────────────


class TestZulipStop:
    @pytest.mark.asyncio
    async def test_stop_awaits_typing_tasks(self) -> None:
        ch = ZulipChannel(
            {
                "enabled": True,
                "site": "https://example.zulipchat.com",
                "email": "bot@example.com",
                "apiKey": "k",
                "allowFrom": ["*"],
            },
            MessageBus(),
        )
        task, done = await _probe_task()
        ch._typing_tasks["pm:1"] = task
        client = MagicMock()
        ch._client = client
        ch._queue_id = "q"

        await ch.stop()

        assert done == [True]
        assert task.cancelled()
        assert ch._typing_tasks == {}
        client.deregister.assert_called_once_with("q")


# ── lark_http keep-alive transport ───────────────────────────────────


class TestKeepAliveClose:
    def test_sessions_are_tracked_and_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class FakeSession:
            def __init__(self) -> None:
                self.closed = False

            def close(self) -> None:
                self.closed = True

        monkeypatch.setattr(lark_http.requests, "Session", FakeSession)
        # Fresh thread-local cache so _session() builds a FakeSession even if
        # an earlier test in this thread already opened a real one.
        monkeypatch.setattr(lark_http, "_SESSIONS", threading.local())
        try:
            session = lark_http._session()
            assert session.closed is False

            lark_http.close_keep_alive()

            assert session.closed is True
            assert lark_http._OPEN_SESSIONS == []
        finally:
            lark_http.close_keep_alive()
