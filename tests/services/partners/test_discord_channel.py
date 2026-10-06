"""Focused contract tests for the Discord channel.

Anchors: channel-contracts P0-3 (discord send_delta keyed by chat_id only)
re-verified 2026-10-06 against main @ f07029cfc. Covers the three scenario
classes the finding calls out:

- inbound gateway message parsing (discord.py ``_gateway_loop`` /
  ``_handle_message_create``)
- ``send_delta`` keyed by ``_stream_id`` per ``base.py:178``, including
  same-chat concurrent streams
- delivery-failure visibility per ``base.py:162-164`` (send raises so the
  channel manager retry policy applies)
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from deeptutor.partners.bus.events import InboundMessage, OutboundMessage
from deeptutor.partners.bus.queue import MessageBus
import deeptutor.partners.channels.discord as discord_mod
from deeptutor.partners.channels.discord import DiscordChannel


class _FakeResponse:
    def __init__(
        self, payload: dict[str, Any] | None = None, status_code: int = 200, content: bytes = b""
    ) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.content = content

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeGateway:
    """Minimal async-iterable websocket feeding scripted gateway frames."""

    def __init__(self, frames: list[str]) -> None:
        self._frames = list(frames)
        self.sent: list[str] = []

    def __aiter__(self) -> "_FakeGateway":
        self._iter = iter(self._frames)
        return self

    async def __anext__(self) -> str:
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration from None

    async def send(self, raw: str) -> None:
        self.sent.append(raw)


def _channel(tmp_path: Path, **overrides: Any) -> DiscordChannel:
    defaults: dict[str, Any] = {
        "enabled": True,
        "token": "test-token",
        "allow_from": ["*"],
        "group_policy": "mention",
    }
    defaults.update(overrides)
    bus = MagicMock(spec=MessageBus)
    bus.publish_inbound = AsyncMock()
    ch = DiscordChannel(defaults, bus)
    ch._bot_user_id = "bot-1"
    ch._http = MagicMock()
    ch._http.request = AsyncMock(return_value=_FakeResponse({"id": "555"}))
    ch._http.post = AsyncMock(return_value=_FakeResponse())
    ch._http.get = AsyncMock(return_value=_FakeResponse(content=b"data"))
    # Keep attachment downloads inside the test's tmp dir.
    ch.media_dir = lambda channel=None: tmp_path
    return ch


def _dm_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": "m1",
        "author": {"id": "u1", "bot": False},
        "channel_id": "ch1",
        "content": "hello",
        "attachments": [],
    }
    payload.update(overrides)
    return payload


def _meta(stream_id: str, end: bool = False) -> dict[str, Any]:
    meta: dict[str, Any] = {"_stream_id": stream_id}
    if end:
        meta["_stream_end"] = True
    else:
        meta["_stream_delta"] = True
    return meta


def _posts(ch: DiscordChannel) -> list[str]:
    return [
        c.kwargs["json"]["content"] for c in ch._http.request.await_args_list if c.args[0] == "POST"
    ]


# ── Inbound parsing ──────────────────────────────────────────────────


class TestInboundParsing:
    @pytest.mark.asyncio
    async def test_gateway_dispatches_ready_and_message_create(self, tmp_path):
        ch = _channel(tmp_path)
        frames = [
            "this is not json",
            json.dumps({"op": 10, "d": {"heartbeat_interval": 45000}}),
            json.dumps({"op": 0, "t": "READY", "s": 1, "d": {"user": {"id": "bot-1"}}}),
            json.dumps({"op": 0, "t": "MESSAGE_CREATE", "s": 2, "d": _dm_payload()}),
        ]
        ch._ws = _FakeGateway(frames)

        await ch._gateway_loop()

        # Garbage frame skipped, READY captured, IDENTIFY sent with token+intents.
        assert ch._bot_user_id == "bot-1"
        assert ch.setup_state["status"] == "connected"
        identify = json.loads(ch._ws.sent[0])
        assert identify["op"] == 2
        assert identify["d"]["token"] == "test-token"
        assert identify["d"]["intents"] == ch.config.intents

        ch.bus.publish_inbound.assert_awaited_once()
        msg: InboundMessage = ch.bus.publish_inbound.await_args.args[0]
        assert msg.channel == "discord"
        assert msg.sender_id == "u1"
        assert msg.chat_id == "ch1"
        assert msg.content == "hello"
        assert msg.metadata["message_id"] == "m1"
        assert msg.metadata["guild_id"] is None
        assert msg.metadata["reply_to"] is None

    @pytest.mark.asyncio
    async def test_bot_author_ignored(self, tmp_path):
        ch = _channel(tmp_path)
        await ch._handle_message_create(_dm_payload(author={"id": "b2", "bot": True}))
        ch.bus.publish_inbound.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_disallowed_sender_ignored(self, tmp_path):
        ch = _channel(tmp_path, allow_from=["u1"])
        await ch._handle_message_create(_dm_payload(author={"id": "u2", "bot": False}))
        ch.bus.publish_inbound.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_group_message_without_mention_ignored(self, tmp_path):
        ch = _channel(tmp_path)
        await ch._handle_message_create(_dm_payload(guild_id="g1"))
        ch.bus.publish_inbound.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_group_message_mentioned_via_array_published(self, tmp_path):
        ch = _channel(tmp_path)
        await ch._handle_message_create(_dm_payload(guild_id="g1", mentions=[{"id": "bot-1"}]))
        ch.bus.publish_inbound.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_group_message_mention_in_content_published(self, tmp_path):
        ch = _channel(tmp_path)
        await ch._handle_message_create(_dm_payload(guild_id="g1", content="<@!bot-1> please help"))
        ch.bus.publish_inbound.assert_awaited_once()
        msg: InboundMessage = ch.bus.publish_inbound.await_args.args[0]
        assert msg.content == "<@!bot-1> please help"

    @pytest.mark.asyncio
    async def test_attachment_downloaded_and_forwarded(self, tmp_path):
        ch = _channel(tmp_path)
        attachment = {
            "id": "a1",
            "url": "https://cdn.discord.test/pic.png",
            "filename": "pic.png",
            "size": 10,
        }
        await ch._handle_message_create(_dm_payload(attachments=[attachment]))

        expected = tmp_path / "a1_pic.png"
        assert expected.read_bytes() == b"data"
        msg: InboundMessage = ch.bus.publish_inbound.await_args.args[0]
        assert msg.media == [str(expected)]
        assert "[attachment:" in msg.content

    @pytest.mark.asyncio
    async def test_attachment_download_failure_degrades_to_tag(self, tmp_path):
        ch = _channel(tmp_path)
        ch._http.get = AsyncMock(side_effect=RuntimeError("cdn down"))
        attachment = {
            "id": "a1",
            "url": "https://cdn.discord.test/pic.png",
            "filename": "pic.png",
            "size": 10,
        }
        await ch._handle_message_create(_dm_payload(attachments=[attachment]))

        msg: InboundMessage = ch.bus.publish_inbound.await_args.args[0]
        assert msg.media == []
        assert "[attachment: pic.png - download failed]" in msg.content

    @pytest.mark.asyncio
    async def test_reply_reference_captured(self, tmp_path):
        ch = _channel(tmp_path)
        await ch._handle_message_create(_dm_payload(referenced_message={"id": "m0"}))
        msg: InboundMessage = ch.bus.publish_inbound.await_args.args[0]
        assert msg.metadata["reply_to"] == "m0"


# ── send_delta keyed by _stream_id (base.py:178) ─────────────────────


class TestSendDeltaStreamKeying:
    @pytest.mark.asyncio
    async def test_same_chat_concurrent_streams_do_not_crosstalk(self, tmp_path):
        ch = _channel(tmp_path)
        ch._http.request = AsyncMock(
            side_effect=[
                _FakeResponse({"id": "m-a1"}),
                _FakeResponse({"id": "m-b1"}),
                _FakeResponse({"id": "m-a2"}),
            ]
        )

        await ch.send_delta("chat1", "Alpha-1", _meta("A"))
        await ch.send_delta("chat1", "Beta-1", _meta("B"))
        await ch.send_delta("chat1", "Alpha-2", _meta("A"))

        # Each POST carries exactly one stream's text — never a mix.
        assert _posts(ch) == ["Alpha-1", "Beta-1", "Alpha-2"]
        buf = ch._stream_bufs["chat1"]
        assert buf.stream_id == "A"
        assert buf.text == "Alpha-2"
        assert buf.message_id == "m-a2"

    @pytest.mark.asyncio
    async def test_stream_end_ignores_mismatched_stream(self, tmp_path):
        ch = _channel(tmp_path)

        await ch.send_delta("chat1", "Beta", _meta("B"))
        assert ch._http.request.await_count == 1

        # End marker for the older stream A must not flush B's buffer.
        await ch.send_delta("chat1", "", _meta("A", end=True))
        assert ch._http.request.await_count == 1
        assert "chat1" in ch._stream_bufs

        await ch.send_delta("chat1", "", _meta("B", end=True))
        methods = [c.args[0] for c in ch._http.request.await_args_list]
        assert methods == ["POST", "PATCH"]
        patch_call = ch._http.request.await_args_list[-1]
        assert patch_call.kwargs["json"]["content"] == "Beta"
        assert "chat1" not in ch._stream_bufs

    @pytest.mark.asyncio
    async def test_sequential_streams_start_clean_after_end(self, tmp_path, monkeypatch):
        monkeypatch.setattr(discord_mod, "_STREAM_EDIT_INTERVAL", 0.0)
        ch = _channel(tmp_path)
        ch._http.request = AsyncMock(
            side_effect=[
                _FakeResponse({"id": "m-a"}),
                _FakeResponse(),
                _FakeResponse(),
                _FakeResponse({"id": "m-b"}),
            ]
        )

        await ch.send_delta("chat1", "Hello ", _meta("A"))
        await ch.send_delta("chat1", "done", _meta("A"))
        await ch.send_delta("chat1", "", _meta("A", end=True))
        assert "chat1" not in ch._stream_bufs

        await ch.send_delta("chat1", "Beta", _meta("B"))
        calls = ch._http.request.await_args_list
        assert calls[1].args[0] == "PATCH"
        assert calls[1].kwargs["json"]["content"] == "Hello done"
        assert calls[3].args[0] == "POST"
        assert calls[3].kwargs["json"]["content"] == "Beta"
        buf = ch._stream_bufs["chat1"]
        assert (buf.stream_id, buf.text, buf.message_id) == ("B", "Beta", "m-b")

    @pytest.mark.asyncio
    async def test_stream_end_overflow_splits_into_followups(self, tmp_path):
        ch = _channel(tmp_path)
        ch._http.request = AsyncMock(
            side_effect=[
                _FakeResponse({"id": "m1"}),
                _FakeResponse(),
                _FakeResponse({"id": "m2"}),
            ]
        )

        await ch.send_delta("chat1", "a" * 2500, _meta("A"))
        await ch.send_delta("chat1", "", _meta("A", end=True))

        patch_call = ch._http.request.await_args_list[1]
        followup = ch._http.request.await_args_list[2]
        assert patch_call.args[0] == "PATCH"
        assert patch_call.kwargs["json"]["content"] == "a" * 2000
        assert followup.args[0] == "POST"
        assert followup.kwargs["json"]["content"] == "a" * 500
        assert "chat1" not in ch._stream_bufs

    @pytest.mark.asyncio
    async def test_send_delta_without_http_client_drops_silently(self, tmp_path):
        ch = _channel(tmp_path)
        ch._http = None
        await ch.send_delta("chat1", "x", _meta("A"))
        assert ch._stream_bufs == {}


# ── send failure visibility (base.py:162-164) ────────────────────────


class TestSendFailureVisibility:
    @pytest.mark.asyncio
    async def test_send_raises_runtime_error_on_api_failure(self, tmp_path, monkeypatch):
        monkeypatch.setattr(asyncio, "sleep", AsyncMock())
        ch = _channel(tmp_path)
        ch._http.post = AsyncMock(return_value=_FakeResponse(status_code=500))
        msg = OutboundMessage(channel="discord", chat_id="chat9", content="hi")

        with pytest.raises(RuntimeError, match="chat9"):
            await ch.send(msg)
        # 3 in-channel attempts before giving up.
        assert ch._http.post.await_count == 3

    @pytest.mark.asyncio
    async def test_send_retries_rate_limit_then_delivers(self, tmp_path):
        ch = _channel(tmp_path)
        ch._http.post = AsyncMock(
            side_effect=[_FakeResponse({"retry_after": 0.0}, status_code=429), _FakeResponse()]
        )
        msg = OutboundMessage(channel="discord", chat_id="chat1", content="hi")

        await ch.send(msg)
        assert ch._http.post.await_count == 2
        assert ch._http.post.await_args.kwargs["json"] == {"content": "hi"}

    @pytest.mark.asyncio
    async def test_send_splits_long_content_reply_reference_on_first_only(self, tmp_path):
        ch = _channel(tmp_path)
        msg = OutboundMessage(channel="discord", chat_id="chat1", content="a" * 2500, reply_to="r1")

        await ch.send(msg)
        assert ch._http.post.await_count == 2
        first, second = (c.kwargs["json"] for c in ch._http.post.await_args_list)
        assert first["content"] == "a" * 2000
        assert second["content"] == "a" * 500
        assert first["message_reference"] == {"message_id": "r1"}
        assert "message_reference" not in second

    @pytest.mark.asyncio
    async def test_missing_media_becomes_visible_placeholder(self, tmp_path):
        ch = _channel(tmp_path)
        missing = str(tmp_path / "ghost.bin")
        msg = OutboundMessage(channel="discord", chat_id="chat1", content="", media=[missing])

        await ch.send(msg)
        ch._http.post.assert_awaited_once()
        assert (
            "[attachment: ghost.bin - send failed]"
            in (ch._http.post.await_args.kwargs["json"]["content"])
        )
