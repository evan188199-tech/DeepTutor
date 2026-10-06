"""Channel send-contract regressions for matrix / zulip / discord.

``BaseChannel`` requires ``send``/``send_delta`` implementations to raise on
delivery failure (so the channel manager applies its retry policy) and stateful
streaming implementations to key buffers by ``_stream_id`` rather than only by
``chat_id``. These tests lock both properties against mocked clients.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from deeptutor.partners.bus.events import OutboundMessage
from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels.discord import DiscordChannel
from deeptutor.partners.channels.matrix import MatrixChannel, MatrixConfig
from deeptutor.partners.channels.zulip import ZulipChannel, ZulipConfig


def _bus() -> MagicMock:
    bus = MagicMock(spec=MessageBus)
    bus.publish_inbound = AsyncMock()
    return bus


def _meta(stream_id: str, end: bool = False) -> dict[str, Any]:
    meta: dict[str, Any] = {"_stream_id": stream_id}
    if end:
        meta["_stream_end"] = True
    else:
        meta["_stream_delta"] = True
    return meta


# ── Matrix ───────────────────────────────────────────────────────────


def _matrix_channel() -> MatrixChannel:
    config = MatrixConfig.model_validate(
        {
            "enabled": True,
            "homeserver": "https://matrix.example.org",
            "accessToken": "token",
            "userId": "@bot:example.org",
            "allowFrom": ["*"],
        }
    )
    return MatrixChannel(config, _bus())


class TestMatrixSendContract:
    @pytest.mark.asyncio
    async def test_send_raises_on_room_send_error(self):
        from nio import RoomSendError

        ch = _matrix_channel()
        ch.client = MagicMock()
        ch.client.room_send = AsyncMock(return_value=RoomSendError("send failed", "M_UNKNOWN"))

        msg = OutboundMessage(channel="matrix", chat_id="!room:example.org", content="Hello")
        with pytest.raises(RuntimeError, match="Matrix send failed"):
            await ch.send(msg)
        ch.client.room_send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_returns_normally_on_success_response(self):
        from nio import RoomSendResponse

        ch = _matrix_channel()
        ch.client = MagicMock()
        ch.client.room_send = AsyncMock(return_value=RoomSendResponse("evt-1", "!room:example.org"))

        msg = OutboundMessage(channel="matrix", chat_id="!room:example.org", content="Hello")
        await ch.send(msg)
        ch.client.room_send.assert_awaited_once()


# ── Zulip ────────────────────────────────────────────────────────────


def _zulip_channel() -> ZulipChannel:
    config = ZulipConfig.model_validate(
        {
            "enabled": True,
            "site": "https://example.zulipchat.com",
            "email": "bot@example.com",
            "apiKey": "secret-key-123",
            "allowFrom": ["*"],
            "groupPolicy": "mention",
            "timeout": 60.0,
        }
    )
    return ZulipChannel(config, _bus())


class TestZulipSendContract:
    @pytest.mark.asyncio
    async def test_send_raises_on_api_error(self):
        ch = _zulip_channel()
        mock_client = MagicMock()
        mock_client.call_endpoint.return_value = {"result": "error", "msg": "unauthorized"}
        ch._client = mock_client

        msg = OutboundMessage(
            channel="zulip",
            chat_id="pm:42",
            content="Hello",
            metadata={"msg_type": "private", "recipient_user_id": "42"},
        )
        with pytest.raises(RuntimeError, match="Zulip send failed"):
            await ch.send(msg)

    @pytest.mark.asyncio
    async def test_send_raises_on_upload_error(self, tmp_path):
        test_file = tmp_path / "test.png"
        test_file.write_bytes(b"fake-image")

        ch = _zulip_channel()
        mock_client = MagicMock()
        mock_client.call_endpoint.return_value = {"result": "error", "msg": "too large"}
        ch._client = mock_client

        msg = OutboundMessage(
            channel="zulip",
            chat_id="pm:42",
            content="",
            media=[str(test_file)],
            metadata={"msg_type": "private", "recipient_user_id": "42"},
        )
        with pytest.raises(RuntimeError, match="Zulip upload failed"):
            await ch.send(msg)

    @pytest.mark.asyncio
    async def test_send_returns_normally_on_success(self, tmp_path):
        test_file = tmp_path / "test.png"
        test_file.write_bytes(b"fake-image")

        ch = _zulip_channel()
        mock_client = MagicMock()
        mock_client.call_endpoint.return_value = {
            "result": "success",
            "uri": "/user_uploads/img.png",
        }
        ch._client = mock_client

        msg = OutboundMessage(
            channel="zulip",
            chat_id="pm:42",
            content="Hello",
            media=[str(test_file)],
            metadata={"msg_type": "private", "recipient_user_id": "42"},
        )
        await ch.send(msg)
        # upload + attachment link message + original content message
        assert mock_client.call_endpoint.call_count == 3


# ── Discord ──────────────────────────────────────────────────────────


def _discord_response(payload: dict[str, Any]) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


def _discord_channel(*message_ids: str) -> DiscordChannel:
    ch = DiscordChannel({"enabled": True, "token": "t", "allowFrom": ["*"]}, MessageBus())
    ch._http = MagicMock()
    ids = iter(message_ids or ("555",))

    def _respond(_method: str, _url: str, **_kwargs: Any) -> MagicMock:
        try:
            message_id = next(ids)
        except StopIteration:
            message_id = "extra"
        return _discord_response({"id": message_id})

    ch._http.request = AsyncMock(side_effect=_respond)
    return ch


class TestDiscordStreamKeying:
    @pytest.mark.asyncio
    async def test_concurrent_streams_buffer_independently(self):
        ch = _discord_channel()

        await ch.send_delta("42", "alpha", _meta("s1"))
        await ch.send_delta("42", "beta", _meta("s2"))
        await ch.send_delta("42", "-more", _meta("s1"))

        assert ch._stream_bufs["s1"].text == "alpha-more"
        assert ch._stream_bufs["s2"].text == "beta"

    @pytest.mark.asyncio
    async def test_stream_end_flushes_only_its_own_buffer(self):
        ch = _discord_channel("m1", "m2")

        await ch.send_delta("42", "one", _meta("s1"))
        await ch.send_delta("42", "two", _meta("s2"))

        await ch.send_delta("42", "", _meta("s1", end=True))

        patch_calls = [c for c in ch._http.request.await_args_list if c.args[0] == "PATCH"]
        assert len(patch_calls) == 1
        assert patch_calls[0].args[1].endswith("/messages/m1")
        assert "s1" not in ch._stream_bufs
        assert ch._stream_bufs["s2"].text == "two"

    @pytest.mark.asyncio
    async def test_delta_without_stream_id_keys_by_chat(self):
        ch = _discord_channel()

        await ch.send_delta("42", "x", {"_stream_delta": True})
        await ch.send_delta("42", "y", {"_stream_delta": True})
        await ch.send_delta("42", "", {"_stream_end": True})

        assert ch._stream_bufs == {}
