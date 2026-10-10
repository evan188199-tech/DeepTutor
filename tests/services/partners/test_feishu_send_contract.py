"""Feishu ``send`` raises on delivery failure so manager retries apply.

``BaseChannel.send`` requires implementations to raise when delivery fails;
``ChannelManager.send_with_retry`` builds its backoff policy on that. These
tests inject failures through a mocked lark client and lock both the raise
and the resulting retry behavior.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from deeptutor.partners.bus.events import OutboundMessage
from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels.feishu import FeishuChannel
from deeptutor.partners.channels.manager import send_with_retry


def _response(*, ok: bool = True, data: object | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        success=lambda: ok,
        data=data,
        code=0 if ok else 230002,
        msg="ok" if ok else "receive id is invalid",
        get_log_id=lambda: "log-1",
    )


def _channel() -> FeishuChannel:
    channel = FeishuChannel({"enabled": True, "appId": "app", "appSecret": "secret"}, MessageBus())
    message = SimpleNamespace(
        create=MagicMock(return_value=_response()),
        reply=MagicMock(return_value=_response()),
    )
    image = SimpleNamespace(create=MagicMock(return_value=_response()))
    file = SimpleNamespace(create=MagicMock(return_value=_response()))
    reaction = SimpleNamespace(
        create=MagicMock(return_value=_response(data=SimpleNamespace(reaction_id="reaction-1"))),
        delete=MagicMock(return_value=_response()),
    )
    channel._client = SimpleNamespace(
        im=SimpleNamespace(
            v1=SimpleNamespace(message=message, image=image, file=file, message_reaction=reaction)
        )
    )
    return channel


def _outbound(**metadata: object) -> OutboundMessage:
    return OutboundMessage(
        channel="feishu",
        chat_id="ou_user",
        content="Answer",
        metadata=dict(metadata),
    )


class TestFeishuSendContract:
    @pytest.mark.asyncio
    async def test_send_raises_when_the_platform_rejects_the_message(self) -> None:
        pytest.importorskip("lark_oapi")
        channel = _channel()
        channel._client.im.v1.message.create.return_value = _response(ok=False)

        with pytest.raises(RuntimeError, match="Feishu text message send failed"):
            await channel.send(_outbound())

    @pytest.mark.asyncio
    async def test_send_propagates_transport_errors(self) -> None:
        pytest.importorskip("lark_oapi")
        channel = _channel()
        channel._client.im.v1.message.create.side_effect = TimeoutError("response lost")

        with pytest.raises(TimeoutError, match="response lost"):
            await channel.send(_outbound())

    @pytest.mark.asyncio
    async def test_send_raises_when_media_upload_fails(self, tmp_path) -> None:
        pytest.importorskip("lark_oapi")
        channel = _channel()
        channel._working_reactions["om_user"] = ("reaction-1", 0.0)
        channel._remove_reaction_sync = MagicMock(return_value=True)
        media = tmp_path / "photo.png"
        media.write_bytes(b"fake-image")
        channel._client.im.v1.image.create.return_value = _response(ok=False)

        message = OutboundMessage(
            channel="feishu",
            chat_id="ou_user",
            content="See this",
            media=[str(media)],
            metadata={"message_id": "om_user"},
        )
        with pytest.raises(RuntimeError, match="image upload failed"):
            await channel.send(message)
        # The working reaction survives a failed delivery for a later retry.
        assert "om_user" in channel._working_reactions
        channel._remove_reaction_sync.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_returns_normally_when_delivery_succeeds(self) -> None:
        pytest.importorskip("lark_oapi")
        channel = _channel()
        channel._working_reactions["om_user"] = ("reaction-1", 0.0)
        channel._remove_reaction_sync = MagicMock(return_value=True)

        await channel.send(_outbound(message_id="om_user"))

        channel._client.im.v1.message.reply.assert_called_once()
        channel._client.im.v1.message.create.assert_not_called()
        channel._remove_reaction_sync.assert_called_once_with("om_user", "reaction-1")


class TestFeishuManagerRetry:
    @pytest.mark.asyncio
    async def test_send_with_retry_recovers_a_transient_feishu_failure(self) -> None:
        pytest.importorskip("lark_oapi")
        channel = _channel()
        channel._client.im.v1.message.create.side_effect = [
            _response(ok=False),
            _response(ok=False),
            _response(),
        ]

        await send_with_retry(channel, _outbound(), max_attempts=3, retry_delays=(0, 0))

        assert channel._client.im.v1.message.create.call_count == 3

    @pytest.mark.asyncio
    async def test_send_with_retry_exhausts_attempts_on_persistent_failure(self) -> None:
        pytest.importorskip("lark_oapi")
        channel = _channel()
        channel._client.im.v1.message.create.return_value = _response(ok=False)

        # The manager owns the final-failure policy: it logs and returns
        # rather than raising, but only after the full attempt budget.
        await send_with_retry(channel, _outbound(), max_attempts=3, retry_delays=(0, 0))

        assert channel._client.im.v1.message.create.call_count == 3
