"""Unit tests for the partners message bus: events and queue semantics."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
import time

import pytest

from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.partners.bus import InboundMessage, MessageBus, OutboundMessage


def _make_inbound(**overrides) -> InboundMessage:
    defaults = dict(
        channel="telegram",
        sender_id="user-1",
        chat_id="chat-9",
        content="hello",
    )
    defaults.update(overrides)
    return InboundMessage(**defaults)


def _make_outbound(**overrides) -> OutboundMessage:
    defaults = dict(channel="telegram", chat_id="chat-9", content="hi")
    defaults.update(overrides)
    return OutboundMessage(**defaults)


def _make_actor(tmp_path: Path) -> CurrentUser:
    return CurrentUser(
        id="u-1",
        username="alice",
        role="user",
        scope=UserScope(kind="user", user_id="u-1", root=tmp_path / "u-1"),
    )


# ---------------------------------------------------------------------------
# Event payloads
# ---------------------------------------------------------------------------


def test_inbound_message_defaults() -> None:
    before = datetime.now()
    msg = _make_inbound()
    after = datetime.now()

    assert msg.media == []
    assert msg.metadata == {}
    assert msg.session_key_override is None
    assert msg.actor is None
    assert isinstance(msg.timestamp, datetime)
    assert before <= msg.timestamp <= after


def test_inbound_session_key_derived_from_channel_and_chat() -> None:
    msg = _make_inbound()
    assert msg.session_key == "telegram:chat-9"


def test_inbound_session_key_override_wins() -> None:
    msg = _make_inbound(session_key_override="telegram:chat-9:thread-3")
    assert msg.session_key == "telegram:chat-9:thread-3"


def test_inbound_actor_hidden_from_repr(tmp_path: Path) -> None:
    msg = _make_inbound(actor=_make_actor(tmp_path), metadata={"k": "v"})
    rendered = repr(msg)
    assert "channel='telegram'" in rendered
    assert "alice" not in rendered


def test_inbound_media_and_metadata_are_per_instance() -> None:
    first = _make_inbound()
    second = _make_inbound()
    first.media.append("https://example.com/a.png")
    first.metadata["edited"] = True
    assert second.media == []
    assert second.metadata == {}


def test_outbound_message_defaults() -> None:
    msg = _make_outbound()
    assert msg.reply_to is None
    assert msg.media == []
    assert msg.metadata == {}


def test_outbound_message_roundtrip_payload() -> None:
    msg = OutboundMessage(
        channel="discord",
        chat_id="chan-1",
        content="answer",
        reply_to="msg-42",
        media=["https://example.com/x.png"],
        metadata={"blocks": 2},
    )
    assert msg.channel == "discord"
    assert msg.chat_id == "chan-1"
    assert msg.content == "answer"
    assert msg.reply_to == "msg-42"
    assert msg.media == ["https://example.com/x.png"]
    assert msg.metadata == {"blocks": 2}


# ---------------------------------------------------------------------------
# Queue enqueue / dequeue semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inbound_fifo_ordering_and_identity() -> None:
    bus = MessageBus()
    msgs = [_make_inbound(content=f"m{i}") for i in range(5)]
    for m in msgs:
        await bus.publish_inbound(m)

    assert bus.inbound_size == 5
    for expected in msgs:
        assert await bus.consume_inbound() is expected
    assert bus.inbound_size == 0


@pytest.mark.asyncio
async def test_outbound_fifo_ordering_and_identity() -> None:
    bus = MessageBus()
    msgs = [_make_outbound(content=f"r{i}") for i in range(5)]
    for m in msgs:
        await bus.publish_outbound(m)

    assert bus.outbound_size == 5
    for expected in msgs:
        assert await bus.consume_outbound() is expected
    assert bus.outbound_size == 0


@pytest.mark.asyncio
async def test_consume_inbound_blocks_until_published() -> None:
    bus = MessageBus()
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(bus.consume_inbound(), timeout=0.05)

    msg = _make_inbound(content="late")
    await bus.publish_inbound(msg)
    assert await asyncio.wait_for(bus.consume_inbound(), timeout=1) is msg


@pytest.mark.asyncio
async def test_consume_outbound_blocks_until_published() -> None:
    bus = MessageBus()
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(bus.consume_outbound(), timeout=0.05)

    msg = _make_outbound(content="late")
    await bus.publish_outbound(msg)
    assert await asyncio.wait_for(bus.consume_outbound(), timeout=1) is msg


@pytest.mark.asyncio
async def test_inbound_and_outbound_lanes_are_independent() -> None:
    bus = MessageBus()
    inbound_msg = _make_inbound(content="q")
    outbound_msg = _make_outbound(content="a")
    await bus.publish_inbound(inbound_msg)
    await bus.publish_outbound(outbound_msg)

    assert bus.inbound_size == 1
    assert bus.outbound_size == 1
    assert await bus.consume_outbound() is outbound_msg
    assert bus.inbound_size == 1
    assert await bus.consume_inbound() is inbound_msg


# ---------------------------------------------------------------------------
# Full-queue / close behavior (pinned: the bus uses unbounded queues)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inbound_publish_never_blocks_on_volume() -> None:
    """The bus has no maxsize: publishing never blocks or rejects."""
    bus = MessageBus()
    for i in range(200):
        await asyncio.wait_for(bus.publish_inbound(_make_inbound(content=f"bulk-{i}")), timeout=1)
    assert bus.inbound_size == 200
    first = await bus.consume_inbound()
    assert first.content == "bulk-0"


@pytest.mark.asyncio
async def test_drained_queues_behave_as_closed() -> None:
    """There is no close API: a drained queue is the terminal state, and the
    non-blocking consumer reports it via None instead of waiting forever."""
    bus = MessageBus()
    await bus.publish_outbound(_make_outbound())
    assert await bus.consume_outbound() is not None
    assert bus.try_consume_outbound() is None
    assert bus.outbound_size == 0


# ---------------------------------------------------------------------------
# Outbound metadata stamping and non-blocking peek
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_outbound_stamps_monotonic_enqueued_at() -> None:
    bus = MessageBus()
    before = time.monotonic()
    msg = _make_outbound()
    await bus.publish_outbound(msg)
    after = time.monotonic()

    stamped = msg.metadata["_enqueued_at"]
    assert before <= stamped <= after
    consumed = await bus.consume_outbound()
    assert consumed.metadata["_enqueued_at"] == stamped


@pytest.mark.asyncio
async def test_publish_outbound_preserves_existing_enqueued_at() -> None:
    bus = MessageBus()
    original = 123.5
    msg = _make_outbound(metadata={"_enqueued_at": original})
    await bus.publish_outbound(msg)
    assert msg.metadata["_enqueued_at"] == original


@pytest.mark.asyncio
async def test_publish_outbound_non_dict_metadata_left_alone() -> None:
    bus = MessageBus()

    class OddMetadata:
        pass

    odd = OddMetadata()
    msg = _make_outbound(metadata=odd)  # type: ignore[arg-type]
    await bus.publish_outbound(msg)

    assert bus.outbound_size == 1
    consumed = await bus.consume_outbound()
    assert consumed.metadata is odd


@pytest.mark.asyncio
async def test_try_consume_outbound_fifo_without_waiting() -> None:
    bus = MessageBus()
    msgs = [_make_outbound(content=f"p{i}") for i in range(3)]
    for m in msgs:
        await bus.publish_outbound(m)

    for expected in msgs:
        assert bus.try_consume_outbound() is expected
    assert bus.try_consume_outbound() is None


# ---------------------------------------------------------------------------
# Cleanup / lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timestamp_default_uses_current_time_not_shared() -> None:
    first = _make_inbound()
    await asyncio.sleep(0.01)
    second = _make_inbound()
    assert second.timestamp - first.timestamp >= timedelta(0)
    assert first.timestamp != second.timestamp


@pytest.mark.asyncio
async def test_bus_instances_do_not_share_queues() -> None:
    first = MessageBus()
    second = MessageBus()
    await first.publish_inbound(_make_inbound())
    assert second.inbound_size == 0
    assert second.outbound_size == 0
