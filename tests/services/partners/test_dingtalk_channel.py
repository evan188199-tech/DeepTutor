"""Unit tests for the DingTalk channel implementation.

Covers inbound message parsing (NanobotDingTalkHandler), chat routing
semantics (private vs "group:"-prefixed ids), lifecycle (start gating,
stop cleanup) and access-token handling. All credentials used here are
neutral placeholders — nothing in this file is a real secret.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels import dingtalk as dingtalk_mod
from deeptutor.partners.channels.dingtalk import (
    DingTalkChannel,
    DingTalkConfig,
    NanobotDingTalkHandler,
)

try:
    from dingtalk_stream import AckMessage
    from dingtalk_stream.chatbot import ChatbotMessage

    _SDK_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without the SDK
    _SDK_AVAILABLE = False


def _make_channel(**overrides) -> DingTalkChannel:
    defaults = {
        "enabled": True,
        "client_id": "test-client-id",
        "client_secret": "test-secret",
        "allow_from": ["*"],
    }
    defaults.update(overrides)
    config = DingTalkConfig.model_validate(defaults)
    bus = MagicMock(spec=MessageBus)
    bus.publish_inbound = AsyncMock()
    return DingTalkChannel(config, bus)


def _stream_message(data) -> SimpleNamespace:
    """Stand-in for the SDK CallbackMessage: process() only touches .data."""
    return SimpleNamespace(data=data)


async def _drain_background_tasks(channel: DingTalkChannel) -> None:
    """Let the handler-spawned forwarding tasks finish before asserting."""
    tasks = list(channel._background_tasks)
    for _ in range(3):
        await asyncio.sleep(0)
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def _text_data(**overrides) -> dict:
    base = {
        "msgId": "msg-1",
        "msgtype": "text",
        "text": {"content": "  hello bot  "},
        "senderId": "sender-1",
        "senderStaffId": "staff-1",
        "senderNick": "Xiao Ming",
        "conversationType": "1",
        "conversationId": "cid-1",
    }
    base.update(overrides)
    return base


requires_sdk = pytest.mark.skipif(not _SDK_AVAILABLE, reason="dingtalk-stream SDK not installed")


class TestDingTalkConfig:
    def test_config_defaults_and_camel_case_aliases(self):
        cfg = DingTalkConfig()
        assert cfg.enabled is False
        assert cfg.client_id == ""
        assert cfg.client_secret == ""
        assert cfg.allow_from == []
        # Inherited DeliveryOverrides flags
        assert cfg.send_progress is True
        assert cfg.send_tool_hints is True

        dump = DingTalkConfig(client_id="id-1", client_secret="sec-1", allow_from=["u1"])
        d = dump.model_dump(by_alias=True)
        assert d["clientId"] == "id-1"
        assert d["clientSecret"] == "sec-1"
        assert d["allowFrom"] == ["u1"]

    def test_default_config_exposes_camelcase_keys(self):
        cfg = DingTalkChannel.default_config()
        assert isinstance(cfg, dict)
        assert cfg["enabled"] is False
        assert "clientId" in cfg
        assert "clientSecret" in cfg
        assert "allowFrom" in cfg


@pytest.mark.asyncio
@requires_sdk
class TestHandlerMessageParsing:
    async def test_process_text_message_forwards_full_semantics(self):
        ch = _make_channel()
        ch._on_message = AsyncMock()
        handler = NanobotDingTalkHandler(ch)

        status, reply = await handler.process(_stream_message(_text_data()))
        await _drain_background_tasks(ch)

        assert status == AckMessage.STATUS_OK
        assert reply == "OK"
        ch._on_message.assert_awaited_once_with("hello bot", "staff-1", "Xiao Ming", "1", "cid-1")

    async def test_process_voice_recognition_fallback_used_when_no_text(self):
        ch = _make_channel()
        ch._on_message = AsyncMock()
        handler = NanobotDingTalkHandler(ch)

        data = {
            "msgtype": "voice",
            "content": {"recognition": "what time is it"},
            "senderId": "sender-2",
            "senderNick": "Nick",
            "conversationType": "1",
        }
        status, reply = await handler.process(_stream_message(data))
        await _drain_background_tasks(ch)

        assert status == AckMessage.STATUS_OK
        ch._on_message.assert_awaited_once_with("what time is it", "sender-2", "Nick", "1", None)

    async def test_process_empty_content_acks_without_forwarding(self):
        ch = _make_channel()
        ch._on_message = AsyncMock()
        handler = NanobotDingTalkHandler(ch)

        data = {
            "msgtype": "picture",
            "content": {"downloadCode": "code-x"},
            "senderId": "sender-3",
            "senderNick": "Pic Sender",
        }
        status, reply = await handler.process(_stream_message(data))
        await _drain_background_tasks(ch)

        assert status == AckMessage.STATUS_OK
        assert reply == "OK"
        ch._on_message.assert_not_awaited()

    async def test_process_prefers_staff_id_and_falls_back_to_unknown_nick(self):
        ch = _make_channel()
        ch._on_message = AsyncMock()
        handler = NanobotDingTalkHandler(ch)

        data = {
            "msgtype": "text",
            "text": {"content": "hi"},
            "senderId": "plain-id",
            "senderNick": None,
            "conversationType": "1",
        }
        await handler.process(_stream_message(data))
        await _drain_background_tasks(ch)

        ch._on_message.assert_awaited_once()
        args = ch._on_message.await_args.args
        assert args[1] == "plain-id"  # no senderStaffId -> senderId used
        assert args[2] == "Unknown"  # missing nick -> "Unknown"

    async def test_process_malformed_message_returns_ok_without_raising(self):
        ch = _make_channel()
        ch._on_message = AsyncMock()
        handler = NanobotDingTalkHandler(ch)

        status, reply = await handler.process(_stream_message(None))

        assert status == AckMessage.STATUS_OK
        assert reply == "Error"
        ch._on_message.assert_not_awaited()

    async def test_process_group_message_routes_with_group_prefix(self):
        """Full pipeline: handler -> channel._on_message -> bus publish."""
        ch = _make_channel()
        handler = NanobotDingTalkHandler(ch)

        data = _text_data(
            conversationType="2",
            openConversationId="oc-group-9",
        )
        data.pop("conversationId")
        await handler.process(_stream_message(data))
        await _drain_background_tasks(ch)

        msg = ch.bus.publish_inbound.await_args.args[0]
        assert msg.chat_id == "group:oc-group-9"
        assert msg.channel == "dingtalk"
        assert msg.metadata["platform"] == "dingtalk"
        assert msg.metadata["conversation_type"] == "2"


@pytest.mark.asyncio
class TestOnMessageRouting:
    async def test_private_chat_routes_to_sender_id_with_metadata(self):
        ch = _make_channel()

        await ch._on_message("hi there", "user-9", "Alice", "1", None)

        msg = ch.bus.publish_inbound.await_args.args[0]
        assert msg.chat_id == "user-9"
        assert msg.sender_id == "user-9"
        assert msg.content == "hi there"
        assert msg.metadata == {
            "sender_name": "Alice",
            "platform": "dingtalk",
            "conversation_type": "1",
        }

    async def test_group_chat_chat_id_gets_group_prefix(self):
        ch = _make_channel()

        await ch._on_message("hi", "user-9", "Alice", "2", "cid77")

        msg = ch.bus.publish_inbound.await_args.args[0]
        assert msg.chat_id == "group:cid77"
        assert msg.sender_id == "user-9"

    async def test_group_without_conversation_id_stays_private(self):
        ch = _make_channel()

        await ch._on_message("hi", "user-9", "Alice", "2", None)

        msg = ch.bus.publish_inbound.await_args.args[0]
        assert msg.chat_id == "user-9"

    async def test_allow_from_deny_blocks_publish(self):
        ch = _make_channel(allow_from=["staff-ok"])

        await ch._on_message("hi", "staff-no", "Bob", "1", None)

        ch.bus.publish_inbound.assert_not_awaited()


@pytest.mark.asyncio
class TestLifecycle:
    async def test_start_unavailable_when_sdk_missing(self, monkeypatch):
        monkeypatch.setattr(dingtalk_mod, "DINGTALK_AVAILABLE", False)
        ch = _make_channel()

        await ch.start()

        assert ch.setup_state["status"] == "unavailable"
        assert ch._running is False
        assert ch._client is None

    async def test_start_action_required_without_credentials(self):
        ch = _make_channel(client_id="", client_secret="")

        await ch.start()

        assert ch.setup_state["status"] == "action_required"
        assert ch._running is False

    async def test_start_registers_handler_and_marks_running(self, monkeypatch):
        ch = _make_channel()
        registered = {}

        class FakeStreamClient:
            def __init__(self, credential):
                self.credential = credential

            def register_callback_handler(self, topic, handler):
                registered["topic"] = topic
                registered["handler"] = handler

            async def start(self):
                # Stream ends immediately; the reconnect loop must exit.
                ch._running = False

        monkeypatch.setattr(dingtalk_mod, "DingTalkStreamClient", FakeStreamClient)

        await ch.start()

        assert registered["topic"] == ChatbotMessage.TOPIC
        assert isinstance(registered["handler"], NanobotDingTalkHandler)
        assert registered["handler"].channel is ch
        assert ch.setup_state["status"] == "running"
        assert ch._http is not None

        await ch.stop()

    async def test_stop_cancels_background_tasks_and_closes_http(self):
        ch = _make_channel()
        ch._http = httpx.AsyncClient()
        done = asyncio.Event()

        async def blocker():
            await done.wait()

        task = asyncio.create_task(blocker())
        ch._background_tasks.add(task)
        await asyncio.sleep(0)  # let the task reach its wait point

        await ch.stop()
        done.set()
        await asyncio.sleep(0)

        assert task.cancelled()
        assert ch._background_tasks == set()
        assert ch._http is None
        assert ch.is_running is False
        # stop() is idempotent: a second call must not raise.
        await ch.stop()


@pytest.mark.asyncio
class TestAccessToken:
    async def test_cached_token_reused_within_expiry(self):
        ch = _make_channel()
        ch._access_token = "cached-token"
        ch._token_expiry = time.time() + 600
        ch._http = AsyncMock()

        token = await ch._get_access_token()

        assert token == "cached-token"
        ch._http.post.assert_not_awaited()

    async def test_refresh_posts_credentials_and_sets_expiry_margin(self):
        ch = _make_channel()
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"accessToken": "fresh-token", "expireIn": 7200}
        http = AsyncMock()
        http.post.return_value = resp
        ch._http = http

        token = await ch._get_access_token()

        assert token == "fresh-token"
        url = http.post.await_args.args[0]
        assert url == "https://api.dingtalk.com/v1.0/oauth2/accessToken"
        assert http.post.await_args.kwargs["json"] == {
            "appKey": "test-client-id",
            "appSecret": "test-secret",
        }
        # Expiry sits 60s inside the server-side window.
        assert 0 < ch._token_expiry - time.time() <= 7200 - 60

    async def test_refresh_failure_returns_none_and_keeps_no_token(self):
        ch = _make_channel()
        http = AsyncMock()
        http.post.side_effect = RuntimeError("boom")
        ch._http = http

        assert await ch._get_access_token() is None
        assert ch._access_token is None

    async def test_missing_http_client_returns_none(self):
        ch = _make_channel()
        ch._http = None
        ch._access_token = None

        assert await ch._get_access_token() is None
