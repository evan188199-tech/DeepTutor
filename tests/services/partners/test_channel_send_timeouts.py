"""Send-path timeout regressions for slack/wecom/qq/whatsapp/feishu/dingtalk.

``BaseChannel.send``/``send_delta`` implementations must raise on delivery
failure so the channel manager applies its retry policy. A hung platform API
is one such failure: every send-path network call is bounded by the channel's
``send_timeout_seconds`` config (shared default
``config.schema.SEND_TIMEOUT_SECONDS``) and raises ``asyncio.TimeoutError`` on
expiry. These tests lock that contract against mocked hanging clients.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from deeptutor.partners.bus.events import OutboundMessage
from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels.base import bounded_send_call
from deeptutor.partners.channels.dingtalk import DingTalkChannel, DingTalkConfig
from deeptutor.partners.channels.feishu import FeishuChannel
from deeptutor.partners.channels.qq import QQChannel, QQConfig
from deeptutor.partners.channels.slack import SlackChannel, SlackConfig
from deeptutor.partners.channels.wecom import WecomChannel, WecomConfig
from deeptutor.partners.channels.whatsapp import WhatsAppChannel, WhatsAppConfig
from deeptutor.partners.config.schema import SEND_TIMEOUT_SECONDS, DeliveryOverrides

TINY_TIMEOUT = 0.05
#: Generous wall-clock bound proving the await was released at the timeout,
#: not held for the full hang (async hangs sleep far longer).
MAX_ELAPSED_S = 5.0


def _bus() -> MagicMock:
    bus = MagicMock(spec=MessageBus)
    bus.publish_inbound = AsyncMock()
    return bus


async def _hang(*_args: Any, **_kwargs: Any) -> None:
    await asyncio.sleep(30)


def _hang_sync(*_args: Any, **_kwargs: Any) -> None:
    time.sleep(0.5)


def _message(
    channel: str, content: str = "hello", media: list[str] | None = None, **metadata: Any
) -> OutboundMessage:
    return OutboundMessage(
        channel=channel,
        chat_id="chat-1",
        content=content,
        media=list(media or []),
        metadata=dict(metadata),
    )


def _hanging_sync_mock(name: str) -> MagicMock:
    mock = MagicMock(side_effect=_hang_sync)
    mock.__name__ = name
    return mock


# ── shared constant / config override ────────────────────────────────


class TestSendTimeoutConfig:
    def test_delivery_overrides_default_to_the_shared_constant(self):
        overrides = DeliveryOverrides()
        assert overrides.send_timeout_seconds == SEND_TIMEOUT_SECONDS == 30.0

    def test_channel_config_accepts_snake_case_and_camel_case_overrides(self):
        assert SlackConfig.model_validate({"send_timeout_seconds": 7.5}).send_timeout_seconds == 7.5
        assert WecomConfig.model_validate({"sendTimeoutSeconds": 12}).send_timeout_seconds == 12

    def test_non_positive_timeout_is_rejected(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SlackConfig.model_validate({"send_timeout_seconds": 0})

    @pytest.mark.asyncio
    async def test_bounded_send_call_raises_timeout_with_context(self):
        with pytest.raises(asyncio.TimeoutError, match="Slack chat_postMessage timed out"):
            await bounded_send_call(
                _hang(), timeout=TINY_TIMEOUT, channel="Slack", call="chat_postMessage"
            )


# ── Slack ────────────────────────────────────────────────────────────


def _slack_channel() -> SlackChannel:
    return SlackChannel(
        SlackConfig.model_validate({"enabled": True, "send_timeout_seconds": TINY_TIMEOUT}),
        _bus(),
    )


class TestSlackSendTimeout:
    @pytest.mark.asyncio
    async def test_hanging_chat_post_message_raises_timeout(self):
        channel = _slack_channel()
        channel._web_client = MagicMock()
        channel._web_client.chat_postMessage = AsyncMock(side_effect=_hang)

        started = time.monotonic()
        with pytest.raises(asyncio.TimeoutError, match="chat_postMessage"):
            await channel.send(_message("slack"))
        assert time.monotonic() - started < MAX_ELAPSED_S

    @pytest.mark.asyncio
    async def test_hanging_file_upload_stays_best_effort(self):
        channel = _slack_channel()
        channel._web_client = MagicMock()
        channel._web_client.chat_postMessage = AsyncMock(return_value={"ok": True})
        channel._web_client.files_upload_v2 = AsyncMock(side_effect=_hang)

        msg = _message("slack", content="", media=["/tmp/badge.png"])
        await channel.send(msg)
        channel._web_client.files_upload_v2.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_timely_send_does_not_raise(self):
        channel = _slack_channel()
        channel._web_client = MagicMock()
        channel._web_client.chat_postMessage = AsyncMock(return_value={"ok": True})

        await channel.send(_message("slack"))
        channel._web_client.chat_postMessage.assert_awaited_once()


# ── WeCom ────────────────────────────────────────────────────────────


class TestWecomSendTimeout:
    @pytest.mark.asyncio
    async def test_hanging_reply_stream_raises_timeout(self):
        channel = WecomChannel(
            WecomConfig.model_validate({"send_timeout_seconds": TINY_TIMEOUT}), _bus()
        )
        channel._client = SimpleNamespace(reply_stream=AsyncMock(side_effect=_hang))
        channel._generate_req_id = lambda prefix: f"{prefix}-1"
        channel._chat_frames["chat-1"] = object()

        started = time.monotonic()
        with pytest.raises(asyncio.TimeoutError, match="reply_stream"):
            await channel.send(_message("wecom"))
        assert time.monotonic() - started < MAX_ELAPSED_S


# ── QQ ───────────────────────────────────────────────────────────────


def _qq_channel() -> QQChannel:
    channel = QQChannel(QQConfig.model_validate({"send_timeout_seconds": TINY_TIMEOUT}), _bus())
    channel._client = SimpleNamespace(
        api=SimpleNamespace(
            post_c2c_message=AsyncMock(side_effect=_hang),
            post_group_message=AsyncMock(side_effect=_hang),
        )
    )
    return channel


class TestQQSendTimeout:
    @pytest.mark.asyncio
    async def test_hanging_c2c_post_raises_timeout(self):
        with pytest.raises(asyncio.TimeoutError, match="post_c2c_message"):
            await _qq_channel().send(_message("qq"))

    @pytest.mark.asyncio
    async def test_hanging_group_post_raises_timeout(self):
        channel = _qq_channel()
        channel._chat_type_cache["chat-1"] = "group"

        with pytest.raises(asyncio.TimeoutError, match="post_group_message"):
            await channel.send(_message("qq"))


# ── WhatsApp ─────────────────────────────────────────────────────────


class TestWhatsAppSendTimeout:
    @pytest.mark.asyncio
    async def test_hanging_bridge_send_raises_timeout(self):
        channel = WhatsAppChannel(
            WhatsAppConfig.model_validate({"send_timeout_seconds": TINY_TIMEOUT}), _bus()
        )
        channel._ws = SimpleNamespace(send=AsyncMock(side_effect=_hang))
        channel._connected = True

        started = time.monotonic()
        with pytest.raises(asyncio.TimeoutError, match="bridge send"):
            await channel.send(_message("whatsapp"))
        assert time.monotonic() - started < MAX_ELAPSED_S


# ── Feishu ───────────────────────────────────────────────────────────


def _feishu_channel() -> FeishuChannel:
    channel = FeishuChannel(
        {
            "enabled": True,
            "appId": "app",
            "appSecret": "secret",
            "sendTimeoutSeconds": TINY_TIMEOUT,
        },
        MessageBus(),
    )
    channel._client = SimpleNamespace()
    return channel


class TestFeishuSendTimeout:
    @pytest.mark.asyncio
    async def test_hanging_text_delivery_raises_out_of_send(self):
        channel = _feishu_channel()
        channel._send_message_sync = _hanging_sync_mock("_send_message_sync")

        started = time.monotonic()
        with pytest.raises(asyncio.TimeoutError, match="_send_message_sync"):
            await channel.send(_message("feishu", "plain answer"))
        assert time.monotonic() - started < MAX_ELAPSED_S

    @pytest.mark.asyncio
    async def test_hanging_stream_card_create_raises_out_of_send_delta(self):
        channel = _feishu_channel()
        channel._create_streaming_card_sync = _hanging_sync_mock("_create_streaming_card_sync")

        with pytest.raises(asyncio.TimeoutError, match="_create_streaming_card_sync"):
            await channel.send_delta(
                "ou_user", "answer chunk", {"_stream_id": "turn:1", "_stream_delta": True}
            )

    @pytest.mark.asyncio
    async def test_hanging_thinking_notice_retract_does_not_fail_send(self):
        channel = _feishu_channel()
        channel._thinking_notices["chat-1"] = "om_notice"
        channel._delete_message_sync = _hanging_sync_mock("_delete_message_sync")
        channel._send_message_sync = MagicMock(return_value=True)

        await channel.send(_message("feishu", "plain answer"))

        channel._send_message_sync.assert_called_once()

    @pytest.mark.asyncio
    async def test_timely_send_does_not_raise(self):
        channel = _feishu_channel()
        channel._send_message_sync = MagicMock(return_value=True)

        await channel.send(_message("feishu", "plain answer"))
        channel._send_message_sync.assert_called_once()


# ── DingTalk ─────────────────────────────────────────────────────────


def _dingtalk_channel() -> DingTalkChannel:
    channel = DingTalkChannel(
        DingTalkConfig.model_validate({"send_timeout_seconds": TINY_TIMEOUT}), _bus()
    )
    channel._http = SimpleNamespace(post=AsyncMock(side_effect=_hang))
    return channel


class TestDingTalkSendTimeout:
    @pytest.mark.asyncio
    async def test_hanging_token_refresh_raises_timeout(self):
        with pytest.raises(asyncio.TimeoutError, match="accessToken refresh"):
            await _dingtalk_channel().send(_message("dingtalk"))

    @pytest.mark.asyncio
    async def test_hanging_batch_send_raises_timeout(self):
        channel = _dingtalk_channel()
        channel._access_token = "tok"
        channel._token_expiry = time.time() + 3600

        started = time.monotonic()
        with pytest.raises(asyncio.TimeoutError, match="send sampleMarkdown"):
            await channel.send(_message("dingtalk", "hi"))
        assert time.monotonic() - started < MAX_ELAPSED_S
