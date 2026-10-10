"""Regression coverage for QQ/WeCom replies that depend on volatile state.

Two defects locked here:

* QQ routed outbound replies by an in-memory ``_chat_type_cache`` whose miss
  fallback silently sent every unknown chat to the C2C endpoint — so a group
  reply after a restart (or any proactive send) hit the wrong API. Replies now
  carry ``chat_type`` metadata from the inbound message, and an undeterminable
  route raises instead of guessing.
* WeCom replies need the chat's stored frame; when it was gone the message
  disappeared with no accounting. The drop is now counted, logged, and
  reported to an optional hook.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

from deeptutor.partners.bus.events import InboundMessage, OutboundMessage
from deeptutor.partners.channels import qq as qq_mod
from deeptutor.partners.channels import wecom as wecom_mod


def _qq_channel() -> qq_mod.QQChannel:
    bus = Mock()
    bus.publish_inbound = AsyncMock()
    channel = qq_mod.QQChannel({"allow_from": ["*"]}, bus)
    channel._client = SimpleNamespace(
        api=SimpleNamespace(
            post_group_message=AsyncMock(),
            post_c2c_message=AsyncMock(),
        )
    )
    return channel


def _outbound(chat_id: str, metadata: dict[str, Any] | None = None) -> OutboundMessage:
    return OutboundMessage(
        channel="qq",
        chat_id=chat_id,
        content="reply",
        metadata={"message_id": "m1", **(metadata or {})},
    )


def test_qq_send_cache_miss_routes_group_via_metadata() -> None:
    """A reply whose chat is absent from the cache still reaches the group API."""
    channel = _qq_channel()

    async def run() -> None:
        await channel.send(_outbound("group-open-1", {"chat_type": "group"}))

    asyncio.run(run())

    channel._client.api.post_group_message.assert_awaited_once_with(
        group_openid="group-open-1",
        msg_type=0,
        msg_id="m1",
        msg_seq=channel._msg_seq,
        content="reply",
    )
    channel._client.api.post_c2c_message.assert_not_awaited()


def test_qq_send_cache_miss_routes_c2c_via_metadata() -> None:
    """A cache-miss c2c reply carries the same guarantee."""
    channel = _qq_channel()

    async def run() -> None:
        await channel.send(_outbound("user-open-1", {"chat_type": "c2c"}))

    asyncio.run(run())

    channel._client.api.post_c2c_message.assert_awaited_once_with(
        openid="user-open-1",
        msg_type=0,
        msg_id="m1",
        msg_seq=channel._msg_seq,
        content="reply",
    )
    channel._client.api.post_group_message.assert_not_awaited()


def test_qq_send_metadata_overrides_stale_cache() -> None:
    """The reply's own routing hint wins over a stale cached route."""
    channel = _qq_channel()
    channel._chat_type_cache["chat-1"] = "group"

    async def run() -> None:
        await channel.send(_outbound("chat-1", {"chat_type": "c2c"}))

    asyncio.run(run())

    channel._client.api.post_c2c_message.assert_awaited_once()
    channel._client.api.post_group_message.assert_not_awaited()


def test_qq_send_cache_still_used_when_metadata_absent() -> None:
    """Legacy sends without metadata keep routing through the cache."""
    channel = _qq_channel()
    channel._chat_type_cache["chat-1"] = "group"

    async def run() -> None:
        await channel.send(_outbound("chat-1"))

    asyncio.run(run())

    channel._client.api.post_group_message.assert_awaited_once()


def test_qq_send_unknown_route_refuses_instead_of_guessing() -> None:
    """No hint and no cache: the send must fail loudly, not guess an endpoint."""
    channel = _qq_channel()

    async def run() -> None:
        with pytest.raises(RuntimeError, match="unknown chat type"):
            await channel.send(_outbound("nowhere-1"))

    asyncio.run(run())

    channel._client.api.post_group_message.assert_not_awaited()
    channel._client.api.post_c2c_message.assert_not_awaited()


def test_qq_inbound_message_records_chat_type_metadata() -> None:
    """Group and c2c inbound messages publish their chat type for replies."""
    group_channel = _qq_channel()
    c2c_channel = _qq_channel()
    group_msg = SimpleNamespace(
        id="g1",
        content="hello",
        group_openid="group-open-1",
        author=SimpleNamespace(member_openid="member-1"),
    )
    c2c_msg = SimpleNamespace(
        id="c1",
        content="hi",
        author=SimpleNamespace(id="user-open-1"),
    )

    async def run() -> None:
        await group_channel._on_message(group_msg, is_group=True)
        await c2c_channel._on_message(c2c_msg, is_group=False)

    asyncio.run(run())

    published = [
        call.args[0].metadata
        for ch in (group_channel, c2c_channel)
        for call in ch.bus.publish_inbound.call_args_list
    ]
    assert published[0]["chat_type"] == "group"
    assert published[1]["chat_type"] == "c2c"


def test_runtime_delivery_meta_echoes_chat_type_onto_replies() -> None:
    """_thread_delivery_meta must copy chat_type so the route survives the bus."""
    from deeptutor.services.partners.runtime import _thread_delivery_meta

    inbound = InboundMessage(
        channel="qq",
        sender_id="member-1",
        chat_id="group-open-1",
        content="hello",
        metadata={"message_id": "g1", "chat_type": "group"},
    )

    meta = _thread_delivery_meta(inbound)

    assert meta["chat_type"] == "group"
    assert meta["message_id"] == "g1"


def _wecom_channel() -> wecom_mod.WecomChannel:
    channel = wecom_mod.WecomChannel({"bot_id": "bot", "secret": "s", "allow_from": ["*"]}, Mock())
    channel._client = Mock()
    channel._client.reply_stream = AsyncMock()
    channel._generate_req_id = lambda prefix: f"{prefix}-id"
    return channel


def _wecom_outbound() -> OutboundMessage:
    return OutboundMessage(channel="wecom", chat_id="chat-1", content="reply")


def test_wecom_send_without_frame_counts_logs_and_reports() -> None:
    """A frame-less reply is dropped but counted, logged and hook-reported."""
    from loguru import logger

    channel = _wecom_channel()
    hook_calls: list[str] = []
    channel.on_missing_frame = hook_calls.append
    logged: list[str] = []
    handler_id = logger.add(lambda message: logged.append(message), level="DEBUG")
    try:
        asyncio.run(channel.send(_wecom_outbound()))
        asyncio.run(channel.send(_wecom_outbound()))
    finally:
        logger.remove(handler_id)

    channel._client.reply_stream.assert_not_awaited()
    assert channel.missing_frame_drops == 2
    assert hook_calls == ["chat-1", "chat-1"]
    assert sum("no stored frame" in entry for entry in logged) == 2
    assert sum("missing_frame_drops=2" in entry for entry in logged) == 1


def test_wecom_send_with_frame_delivers_without_counting() -> None:
    """A stored frame keeps the normal delivery path and zero drop count."""
    channel = _wecom_channel()
    channel._chat_frames["chat-1"] = object()

    asyncio.run(channel.send(_wecom_outbound()))

    channel._client.reply_stream.assert_awaited_once()
    assert channel.missing_frame_drops == 0


def test_wecom_missing_frame_hook_failure_is_contained() -> None:
    """An alerting hook must not turn an accounted drop into a send error."""

    def bad_hook(chat_id: str) -> None:
        raise ValueError("hook exploded")

    channel = _wecom_channel()
    channel.on_missing_frame = bad_hook

    asyncio.run(channel.send(_wecom_outbound()))  # must not raise

    assert channel.missing_frame_drops == 1
    channel._client.reply_stream.assert_not_awaited()
