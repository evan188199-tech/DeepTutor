from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import websockets

from deeptutor.partners.bus.events import OutboundMessage
from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels.base import BaseChannel, deliver_outbound
from deeptutor.partners.channels.whatsapp import WhatsAppChannel, WhatsAppConfig


def _channel(**overrides: Any) -> WhatsAppChannel:
    kwargs: dict[str, Any] = {"enabled": True, "allow_from": ["*"]}
    kwargs.update(overrides)
    config = WhatsAppConfig(**kwargs)
    bus = MagicMock(spec=MessageBus)
    bus.publish_inbound = AsyncMock()
    return WhatsAppChannel(config, bus)


class FakeBridgeWS:
    """Stand-in for the websockets client connection (no real bridge)."""

    def __init__(self, incoming: list[str] | None = None, hang_after: bool = False):
        self.sent: list[str] = []
        self.incoming = list(incoming or [])
        self.hang_after = hang_after
        self.closed = False

    async def send(self, payload: str) -> None:
        self.sent.append(payload)

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self) -> "FakeBridgeWS":
        return self

    async def __anext__(self) -> str:
        if self.incoming:
            return self.incoming.pop(0)
        if self.hang_after:
            await asyncio.Event().wait()
        raise StopAsyncIteration

    async def __aenter__(self) -> "FakeBridgeWS":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


def _connected_channel() -> WhatsAppChannel:
    channel = _channel()
    channel._ws = FakeBridgeWS()
    channel._connected = True
    return channel


async def _wait_until(predicate, timeout: float = 2.0) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return predicate()


def _published(channel: WhatsAppChannel):
    return channel.bus.publish_inbound.await_args_list


# ── Setup state (existing coverage) ──────────────────────────────────


@pytest.mark.asyncio
async def test_bridge_qr_is_published_for_the_webui() -> None:
    channel = _channel()

    await channel._handle_bridge_message(json.dumps({"type": "qr", "qr": "scan-me"}))

    assert channel.setup_state == {
        "status": "waiting_for_scan",
        "qr_payload": "scan-me",
    }


@pytest.mark.asyncio
async def test_bridge_connection_status_is_published_for_the_webui() -> None:
    channel = _channel()

    await channel._handle_bridge_message(json.dumps({"type": "status", "status": "connected"}))

    assert channel.setup_state == {"status": "connected"}


# ── Inbound message parsing ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_message_uses_pn_for_sender_and_full_lid_for_chat() -> None:
    channel = _channel()

    await channel._handle_bridge_message(
        json.dumps(
            {
                "type": "message",
                "pn": "+15550001111@s.whatsapp.net",
                "sender": "987654321@lid",
                "content": "hi",
                "id": "m1",
                "timestamp": 1700000000,
                "isGroup": True,
            }
        )
    )

    assert len(_published(channel)) == 1
    inbound = _published(channel)[0].args[0]
    assert inbound.channel == "whatsapp"
    assert inbound.sender_id == "+15550001111"
    assert inbound.chat_id == "987654321@lid"  # replies go to the full LID
    assert inbound.content == "hi"
    assert inbound.media == []
    assert inbound.metadata == {
        "message_id": "m1",
        "timestamp": 1700000000,
        "is_group": True,
    }
    # WhatsApp cannot edit messages in place, so inbound turns must never
    # request live streaming.
    assert "_wants_stream" not in inbound.metadata


@pytest.mark.asyncio
async def test_message_falls_back_to_lid_when_pn_missing() -> None:
    channel = _channel()

    await channel._handle_bridge_message(
        json.dumps({"type": "message", "sender": "987654321@lid", "content": "hello", "id": "m2"})
    )

    inbound = _published(channel)[0].args[0]
    assert inbound.sender_id == "987654321"
    assert inbound.chat_id == "987654321@lid"


@pytest.mark.asyncio
async def test_message_handles_bare_number_without_at() -> None:
    channel = _channel()

    await channel._handle_bridge_message(
        json.dumps({"type": "message", "pn": "+15550001111", "content": "yo", "id": "m3"})
    )

    inbound = _published(channel)[0].args[0]
    assert inbound.sender_id == "+15550001111"
    # chat_id is always the raw LID `sender` field; legacy pn-only messages
    # carry no LID, so there is nothing to reply to (pinned quirk).
    assert inbound.chat_id == ""


@pytest.mark.asyncio
async def test_voice_message_gets_transcription_placeholder() -> None:
    channel = _channel()

    await channel._handle_bridge_message(
        json.dumps({"type": "message", "sender": "987654321@lid", "content": "[Voice Message]"})
    )

    inbound = _published(channel)[0].args[0]
    assert inbound.content == ("[Voice Message: Transcription not available for WhatsApp yet]")


@pytest.mark.asyncio
async def test_media_paths_become_mime_typed_content_tags() -> None:
    channel = _channel()

    await channel._handle_bridge_message(
        json.dumps(
            {
                "type": "message",
                "sender": "987654321@lid",
                "content": "see attached",
                "id": "m5",
                "media": ["/tmp/pic.png", "/tmp/report.pdf"],
            }
        )
    )

    inbound = _published(channel)[0].args[0]
    assert inbound.content == ("see attached\n[image: /tmp/pic.png]\n[file: /tmp/report.pdf]")
    assert inbound.media == ["/tmp/pic.png", "/tmp/report.pdf"]


@pytest.mark.asyncio
async def test_media_only_message_uses_tag_as_content() -> None:
    channel = _channel()

    await channel._handle_bridge_message(
        json.dumps(
            {
                "type": "message",
                "sender": "987654321@lid",
                "content": "",
                "id": "m6",
                "media": ["/tmp/pic.png"],
            }
        )
    )

    inbound = _published(channel)[0].args[0]
    assert inbound.content == "[image: /tmp/pic.png]"


@pytest.mark.asyncio
async def test_unlisted_sender_is_denied() -> None:
    channel = _channel(allow_from=["+15550001111"])

    await channel._handle_bridge_message(
        json.dumps(
            {
                "type": "message",
                "pn": "+15559999999@s.whatsapp.net",
                "sender": "987654321@lid",
                "content": "spam",
                "id": "m7",
            }
        )
    )

    assert len(_published(channel)) == 0


# ── Message-id dedup contract ────────────────────────────────────────


@pytest.mark.asyncio
async def test_duplicate_message_id_is_deduplicated() -> None:
    channel = _channel()
    raw = json.dumps({"type": "message", "sender": "987654321@lid", "content": "hi", "id": "dup-1"})

    await channel._handle_bridge_message(raw)
    await channel._handle_bridge_message(raw)

    assert len(_published(channel)) == 1


@pytest.mark.asyncio
async def test_processed_id_cache_evicts_oldest_beyond_1000() -> None:
    channel = _channel()
    for i in range(1000):
        channel._processed_message_ids[f"old-{i}"] = None

    await channel._handle_bridge_message(
        json.dumps({"type": "message", "sender": "u@lid", "content": "hi", "id": "new"})
    )

    assert len(channel._processed_message_ids) == 1000
    assert "old-0" not in channel._processed_message_ids
    assert "old-999" in channel._processed_message_ids
    assert "new" in channel._processed_message_ids


@pytest.mark.asyncio
async def test_message_without_id_bypasses_dedup() -> None:
    channel = _channel()
    raw = json.dumps({"type": "message", "sender": "u@lid", "content": "hi"})

    await channel._handle_bridge_message(raw)
    await channel._handle_bridge_message(raw)

    assert len(_published(channel)) == 2


# ── Malformed / unknown bridge traffic ───────────────────────────────


@pytest.mark.asyncio
async def test_invalid_json_from_bridge_is_ignored() -> None:
    channel = _channel()

    await channel._handle_bridge_message("not-json{{{")

    assert len(_published(channel)) == 0


@pytest.mark.asyncio
async def test_unknown_message_type_is_ignored() -> None:
    channel = _channel()

    await channel._handle_bridge_message(json.dumps({"type": "pong"}))

    assert len(_published(channel)) == 0


# ── Streaming contract (base.py send_delta alignment) ────────────────


def test_channel_never_claims_streaming_support() -> None:
    channel = _channel()

    assert type(channel).send_delta is BaseChannel.send_delta
    assert channel.supports_streaming is False


@pytest.mark.asyncio
async def test_stream_deltas_never_reach_the_bridge() -> None:
    channel = _connected_channel()

    await deliver_outbound(
        channel,
        OutboundMessage(
            channel="whatsapp",
            chat_id="987654321@lid",
            content="chunk",
            metadata={"_stream_delta": True, "_stream_id": "s1"},
        ),
    )
    await deliver_outbound(
        channel,
        OutboundMessage(
            channel="whatsapp",
            chat_id="987654321@lid",
            content="",
            metadata={"_stream_end": True, "_stream_id": "s1"},
        ),
    )

    assert channel._ws.sent == []


@pytest.mark.asyncio
async def test_streamed_final_without_delivery_confirmation_is_not_resent() -> None:
    channel = _connected_channel()

    await deliver_outbound(
        channel,
        OutboundMessage(
            channel="whatsapp",
            chat_id="987654321@lid",
            content="final answer",
            metadata={"_streamed": True, "_stream_id": "s1"},
        ),
    )

    # base.deliver_outbound only re-sends a `_streamed` final when the channel
    # exposes consume_stream_delivery to prove it never reached the user.
    # WhatsApp has no such hook, so the final is treated as delivered and no
    # bridge traffic is produced.
    assert channel._ws.sent == []


# ── Outbound delivery & failure visibility ───────────────────────────


@pytest.mark.asyncio
async def test_send_delivers_payload_to_lid_chat() -> None:
    channel = _connected_channel()

    await channel.send(
        OutboundMessage(channel="whatsapp", chat_id="987654321@lid", content="héllo 你好")
    )

    assert "你好" in channel._ws.sent[0]  # ensure_ascii=False keeps text readable
    payload = json.loads(channel._ws.sent[0])
    assert payload == {"type": "send", "to": "987654321@lid", "text": "héllo 你好"}


@pytest.mark.asyncio
async def test_send_transport_failure_propagates_for_manager_retry() -> None:
    channel = _connected_channel()
    channel._ws.send = AsyncMock(side_effect=ConnectionError("bridge gone"))

    with pytest.raises(ConnectionError):
        await channel.send(OutboundMessage(channel="whatsapp", chat_id="1", content="x"))


@pytest.mark.asyncio
async def test_send_while_disconnected_drops_without_error() -> None:
    channel = _channel()  # no ws, not connected

    await channel.send(OutboundMessage(channel="whatsapp", chat_id="1", content="x"))

    assert channel._ws is None


# ── Stop / lifecycle cleanup ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_stop_closes_bridge_and_clears_state() -> None:
    channel = _channel()
    ws = FakeBridgeWS()
    channel._ws = ws
    channel._connected = True
    channel._running = True

    await channel.stop()

    assert ws.closed is True
    assert channel._ws is None
    assert channel._connected is False
    assert channel._running is False
    assert channel.is_running is False
    assert channel.setup_state == {"status": "disconnected"}


@pytest.mark.asyncio
async def test_stop_without_connection_is_safe() -> None:
    channel = _channel()

    await channel.stop()  # must not raise

    assert channel._ws is None
    assert channel.setup_state == {"status": "disconnected"}


# ── start(): bridge connection lifecycle ─────────────────────────────


@pytest.mark.asyncio
async def test_start_sends_auth_token_and_dispatches_messages(monkeypatch) -> None:
    ws = FakeBridgeWS(
        incoming=[json.dumps({"type": "message", "sender": "u@lid", "content": "hi", "id": "m9"})],
        hang_after=True,
    )

    def fake_connect(url: str) -> FakeBridgeWS:
        assert url == "ws://localhost:3001"
        return ws

    monkeypatch.setattr(websockets, "connect", fake_connect)
    channel = _channel(bridge_token="tok-123")
    task = asyncio.create_task(channel.start())
    try:
        assert await _wait_until(lambda: len(_published(channel)) == 1)
        assert json.loads(ws.sent[0]) == {"type": "auth", "token": "tok-123"}
        assert channel._connected is True
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_start_connection_failure_sets_error_state_and_keeps_retrying(
    monkeypatch,
) -> None:
    calls = {"count": 0}

    def fake_connect(url: str) -> FakeBridgeWS:
        calls["count"] += 1
        raise ConnectionRefusedError("bridge down")

    monkeypatch.setattr(websockets, "connect", fake_connect)
    channel = _channel()
    task = asyncio.create_task(channel.start())
    try:
        assert await _wait_until(lambda: channel.setup_state.get("status") == "error")
        assert channel._connected is False
        assert calls["count"] == 1  # parked in the retry backoff sleep
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    assert channel.setup_state.get("status") == "error"


@pytest.mark.asyncio
async def test_start_error_in_one_bridge_message_does_not_kill_listener(
    monkeypatch,
) -> None:
    ws = FakeBridgeWS(
        incoming=[
            "not-json{{{",
            json.dumps({"type": "message", "sender": "u@lid", "content": "hi", "id": "m10"}),
        ],
        hang_after=True,
    )

    def fake_connect(url: str) -> FakeBridgeWS:
        return ws

    monkeypatch.setattr(websockets, "connect", fake_connect)
    channel = _channel()
    task = asyncio.create_task(channel.start())
    try:
        assert await _wait_until(lambda: len(_published(channel)) == 1)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
