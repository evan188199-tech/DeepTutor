"""Unit tests for the Slack channel implementation (Socket Mode).

All Slack transport is faked with AsyncMock clients — no real service is
contacted. Focus: message parsing (_to_mrkdwn), send chunking/media delivery,
Socket Mode event branches, and start/stop error paths.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from slack_sdk.socket_mode.request import SocketModeRequest

from deeptutor.partners.bus.events import OutboundMessage
from deeptutor.partners.bus.queue import MessageBus
import deeptutor.partners.channels.slack as slack_module
from deeptutor.partners.channels.slack import SlackChannel, SlackConfig


def _make_channel(**overrides) -> SlackChannel:
    defaults = {
        "enabled": True,
        "bot_token": "xoxb-test",
        "app_token": "xapp-test",
        "allow_from": ["*"],
    }
    defaults.update(overrides)
    config = SlackConfig.model_validate(defaults)
    bus = MagicMock(spec=MessageBus)
    bus.publish_inbound = AsyncMock()
    ch = SlackChannel(config, bus)
    ch._bot_user_id = "UBOT"
    return ch


def _outbound(**overrides) -> OutboundMessage:
    defaults = {
        "channel": "slack",
        "chat_id": "C123",
        "content": "hello",
        "metadata": {},
    }
    defaults.update(overrides)
    return OutboundMessage(**defaults)


def _socket_request(event: dict) -> SocketModeRequest:
    return SocketModeRequest(
        type="events_api",
        envelope_id="env-1",
        payload={"event": event},
    )


def _event(**overrides) -> dict:
    base = {
        "type": "message",
        "user": "U1",
        "channel": "C123",
        "text": "hello",
        "ts": "111.1",
        "channel_type": "im",
    }
    base.update(overrides)
    return base


class TestSlackConfig:
    def test_default_values(self):
        cfg = SlackConfig()
        assert cfg.enabled is False
        assert cfg.mode == "socket"
        assert cfg.bot_token == ""
        assert cfg.app_token == ""
        assert cfg.reply_in_thread is True
        assert cfg.react_emoji == "eyes"
        assert cfg.group_policy == "mention"
        assert cfg.dm.enabled is True
        assert cfg.dm.policy == "open"

    def test_default_config_by_alias(self):
        d = SlackChannel.default_config()
        assert isinstance(d, dict)
        assert d["enabled"] is False
        assert "botToken" in d
        assert "appToken" in d
        assert "replyInThread" in d
        assert "groupPolicy" in d
        assert d["reactEmoji"] == "eyes"

    def test_config_validates_camel_case_dict(self):
        cfg = SlackConfig.model_validate(
            {"botToken": "xoxb-1", "appToken": "xapp-1", "groupPolicy": "open"}
        )
        assert cfg.bot_token == "xoxb-1"
        assert cfg.app_token == "xapp-1"
        assert cfg.group_policy == "open"


class TestSend:
    @pytest.mark.asyncio
    async def test_send_without_client_returns_early(self):
        ch = _make_channel()
        ch._web_client = None
        await ch.send(_outbound())  # must not raise

    @pytest.mark.asyncio
    async def test_send_text_posts_mrkdwn(self):
        ch = _make_channel()
        ch._web_client = AsyncMock()
        await ch.send(_outbound(content="**bold**"))
        ch._web_client.chat_postMessage.assert_awaited_once()
        kwargs = ch._web_client.chat_postMessage.call_args.kwargs
        assert kwargs["channel"] == "C123"
        assert kwargs["text"].strip() == "*bold*"
        assert kwargs["thread_ts"] is None

    @pytest.mark.asyncio
    async def test_send_dm_ignores_thread_ts(self):
        ch = _make_channel()
        ch._web_client = AsyncMock()
        msg = _outbound(metadata={"slack": {"thread_ts": "1.2", "channel_type": "im"}})
        await ch.send(msg)
        kwargs = ch._web_client.chat_postMessage.call_args.kwargs
        assert kwargs["thread_ts"] is None

    @pytest.mark.asyncio
    async def test_send_channel_message_keeps_thread_ts(self):
        ch = _make_channel()
        ch._web_client = AsyncMock()
        msg = _outbound(
            metadata={"slack": {"thread_ts": "9.9", "channel_type": "channel"}},
        )
        await ch.send(msg)
        kwargs = ch._web_client.chat_postMessage.call_args.kwargs
        assert kwargs["thread_ts"] == "9.9"

    @pytest.mark.asyncio
    async def test_send_media_only_skips_text_post(self):
        ch = _make_channel()
        ch._web_client = AsyncMock()
        msg = _outbound(content="", media=["/tmp/a.png", "/tmp/b.png"])
        await ch.send(msg)
        ch._web_client.chat_postMessage.assert_not_awaited()
        assert ch._web_client.files_upload_v2.await_count == 2
        first = ch._web_client.files_upload_v2.call_args_list[0].kwargs
        assert first["channel"] == "C123"
        assert first["file"] == "/tmp/a.png"

    @pytest.mark.asyncio
    async def test_send_media_upload_failure_is_swallowed(self):
        ch = _make_channel()
        ch._web_client = AsyncMock()
        ch._web_client.files_upload_v2.side_effect = RuntimeError("upload boom")
        msg = _outbound(content="", media=["/tmp/a.png"])
        await ch.send(msg)  # best-effort upload must not raise

    @pytest.mark.asyncio
    async def test_send_text_failure_raises_for_retry(self):
        ch = _make_channel()
        ch._web_client = AsyncMock()
        ch._web_client.chat_postMessage.side_effect = RuntimeError("post boom")
        with pytest.raises(RuntimeError, match="post boom"):
            await ch.send(_outbound(content="hi"))

    @pytest.mark.asyncio
    async def test_send_empty_message_without_media_sends_blank(self):
        ch = _make_channel()
        ch._web_client = AsyncMock()
        await ch.send(_outbound(content=""))
        kwargs = ch._web_client.chat_postMessage.call_args.kwargs
        assert kwargs["text"] == " "


class TestToMrkdwn:
    def test_empty_text(self):
        assert SlackChannel._to_mrkdwn("") == ""

    def test_table_becomes_labeled_rows(self):
        table = "| Name | Age |\n| --- | --- |\n| Ann | 3 |"
        out = SlackChannel._to_mrkdwn(table).strip()
        assert out == "*Name*: Ann · *Age*: 3"

    def test_table_inside_prose_keeps_surroundings(self):
        text = "intro\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\noutro"
        out = SlackChannel._to_mrkdwn(text)
        assert "intro" in out
        assert "outro" in out
        assert "| A | B |" not in out
        assert "*A*: 1 · *B*: 2" in out

    def test_bold_and_header_converted(self):
        out = SlackChannel._to_mrkdwn("# Title\n\n**bold** text").strip()
        assert "*Title*" in out
        assert "**" not in out
        assert "*bold* text" in out

    def test_code_fence_preserved(self):
        text = "```python\nx = 1\n```"
        out = SlackChannel._to_mrkdwn(text)
        assert "```\nx = 1\n```" in out  # fence + body intact (language tag may drop)

    def test_bare_url_ampersand_unescaped(self):
        out = SlackChannel._to_mrkdwn("see https://x.com/a?b=1&amp;c=2 now").strip()
        assert "https://x.com/a?b=1&c=2" in out
        assert "&amp;" not in out


class TestOnSocketRequest:
    def _make(self, **config_overrides):
        ch = _make_channel(**config_overrides)
        ch._web_client = AsyncMock()
        client = SimpleNamespace(send_socket_mode_response=AsyncMock())
        ch._handle_message = AsyncMock()
        return ch, client

    @pytest.mark.asyncio
    async def test_events_api_is_acknowledged_and_dispatched(self):
        ch, client = self._make()
        await ch._on_socket_request(client, _socket_request(_event()))
        client.send_socket_mode_response.assert_awaited_once()
        assert client.send_socket_mode_response.call_args[0][0].envelope_id == "env-1"
        ch._handle_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_non_events_api_ignored_without_ack(self):
        ch, client = self._make()
        req = SocketModeRequest(type="hello", envelope_id="env-2", payload={})
        await ch._on_socket_request(client, req)
        client.send_socket_mode_response.assert_not_awaited()
        ch._handle_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unhandled_event_type_acked_but_not_dispatched(self):
        ch, client = self._make()
        await ch._on_socket_request(client, _socket_request(_event(type="reaction_added")))
        client.send_socket_mode_response.assert_awaited_once()
        ch._handle_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_subtyped_message_ignored(self):
        ch, client = self._make()
        await ch._on_socket_request(client, _socket_request(_event(subtype="message_changed")))
        ch._handle_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_bot_own_message_ignored(self):
        ch, client = self._make()
        await ch._on_socket_request(client, _socket_request(_event(user="UBOT")))
        ch._handle_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_plain_message_with_mention_defers_to_app_mention(self):
        ch, client = self._make()
        await ch._on_socket_request(
            client, _socket_request(_event(type="message", text="<@UBOT> hi"))
        )
        ch._handle_message.assert_not_awaited()
        ch._web_client.reactions_add.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_missing_sender_or_channel_ignored(self):
        ch, client = self._make()
        await ch._on_socket_request(client, _socket_request(_event(user=None)))
        await ch._on_socket_request(client, _socket_request(_event(channel=None)))
        ch._handle_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_im_message_dispatched_without_session_key(self):
        ch, client = self._make()
        await ch._on_socket_request(client, _socket_request(_event()))
        ch._handle_message.assert_awaited_once()
        kwargs = ch._handle_message.call_args.kwargs
        assert kwargs["sender_id"] == "U1"
        assert kwargs["chat_id"] == "C123"
        assert kwargs["content"] == "hello"
        assert kwargs["session_key"] is None
        assert kwargs["metadata"]["slack"]["channel_type"] == "im"

    @pytest.mark.asyncio
    async def test_app_mention_stripped_and_thread_scoped(self):
        ch, client = self._make()
        event = _event(
            type="app_mention",
            channel_type="channel",
            text="<@UBOT> help",
        )
        await ch._on_socket_request(client, _socket_request(event))
        kwargs = ch._handle_message.call_args.kwargs
        assert kwargs["content"] == "help"
        assert kwargs["session_key"] == "slack:C123:111.1"
        assert kwargs["metadata"]["slack"]["thread_ts"] == "111.1"
        ch._web_client.reactions_add.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_existing_thread_ts_wins_over_message_ts(self):
        ch, client = self._make()
        event = _event(
            type="app_mention",
            channel_type="channel",
            text="<@UBOT> in thread",
            thread_ts="777.7",
        )
        await ch._on_socket_request(client, _socket_request(event))
        kwargs = ch._handle_message.call_args.kwargs
        assert kwargs["session_key"] == "slack:C123:777.7"

    @pytest.mark.asyncio
    async def test_group_message_without_mention_not_dispatched(self):
        ch, client = self._make()
        event = _event(channel_type="channel", text="plain chat")
        await ch._on_socket_request(client, _socket_request(event))
        ch._handle_message.assert_not_awaited()
        ch._web_client.reactions_add.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_group_allowlist_rejects_other_channels(self):
        ch, client = self._make(group_policy="allowlist", group_allow_from=["C999"])
        event = _event(channel_type="channel", type="app_mention", text="<@UBOT> hi")
        await ch._on_socket_request(client, _socket_request(event))
        ch._handle_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reaction_failure_does_not_block_dispatch(self):
        ch, client = self._make()
        ch._web_client.reactions_add.side_effect = RuntimeError("reaction boom")
        await ch._on_socket_request(client, _socket_request(_event()))
        ch._handle_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_message_failure_is_logged_not_raised(self):
        ch, client = self._make()
        ch._handle_message.side_effect = RuntimeError("handler boom")
        await ch._on_socket_request(client, _socket_request(_event()))  # must not raise


class TestAccessPolicy:
    def test_dm_open_allows_all(self):
        ch = _make_channel()
        assert ch._is_allowed("U1", "D1", "im") is True

    def test_dm_disabled_blocks_all(self):
        ch = _make_channel(dm={"enabled": False})
        assert ch._is_allowed("U1", "D1", "im") is False

    def test_dm_allowlist(self):
        ch = _make_channel(dm={"policy": "allowlist", "allow_from": ["U1"]})
        assert ch._is_allowed("U1", "D1", "im") is True
        assert ch._is_allowed("U2", "D1", "im") is False

    def test_group_allowlist_by_chat_id(self):
        ch = _make_channel(group_policy="allowlist", group_allow_from=["C1"])
        assert ch._is_allowed("U1", "C1", "channel") is True
        assert ch._is_allowed("U1", "C2", "channel") is False

    def test_group_mention_policy_variants(self):
        ch = _make_channel()
        assert ch._should_respond_in_channel("app_mention", "x", "C1") is True
        assert ch._should_respond_in_channel("message", "<@UBOT> x", "C1") is True
        assert ch._should_respond_in_channel("message", "x", "C1") is False

    def test_group_open_policy_allows_plain_messages(self):
        ch = _make_channel(group_policy="open")
        assert ch._should_respond_in_channel("message", "x", "C1") is True

    def test_unknown_group_policy_denies(self):
        ch = _make_channel(group_policy="mystery")
        assert ch._should_respond_in_channel("message", "x", "C1") is False

    def test_strip_bot_mention(self):
        ch = _make_channel()
        assert ch._strip_bot_mention("<@UBOT> hi") == "hi"
        assert ch._strip_bot_mention("<@UBOT>hi") == "hi"
        assert ch._strip_bot_mention("no mention") == "no mention"
        assert ch._strip_bot_mention("") == ""


class TestStartStop:
    @pytest.mark.asyncio
    async def test_start_without_tokens_is_action_required(self):
        ch = _make_channel(bot_token="", app_token="")
        await ch.start()
        assert ch.is_running is False
        assert ch.setup_state["status"] == "action_required"

    @pytest.mark.asyncio
    async def test_start_unsupported_mode_is_action_required(self):
        ch = _make_channel(mode="http")
        await ch.start()
        assert ch.is_running is False
        assert ch.setup_state["status"] == "action_required"

    @pytest.mark.asyncio
    async def test_start_socket_timeout_stops_and_raises(self, monkeypatch):
        ch = _make_channel()
        socket_client = MagicMock()
        socket_client.socket_mode_request_listeners = []
        socket_client.connect = AsyncMock(side_effect=asyncio.TimeoutError())
        socket_client.close = AsyncMock()
        web_client = AsyncMock()
        web_client.auth_test.return_value = {"user_id": "UBOT"}
        monkeypatch.setattr(slack_module, "AsyncWebClient", lambda token: web_client)
        monkeypatch.setattr(slack_module, "SocketModeClient", lambda **kw: socket_client)

        with pytest.raises(RuntimeError, match="timed out"):
            await ch.start()

        assert ch.is_running is False
        socket_client.close.assert_awaited_once()
        assert ch._socket_client is None

    @pytest.mark.asyncio
    async def test_stop_closes_socket_and_clears_state(self):
        ch = _make_channel()
        socket_client = MagicMock()
        socket_client.close = AsyncMock()
        ch._socket_client = socket_client
        ch._running = True
        await ch.stop()
        assert ch.is_running is False
        socket_client.close.assert_awaited_once()
        assert ch._socket_client is None

    @pytest.mark.asyncio
    async def test_stop_close_failure_is_swallowed(self):
        ch = _make_channel()
        socket_client = MagicMock()
        socket_client.close = AsyncMock(side_effect=RuntimeError("close boom"))
        ch._socket_client = socket_client
        ch._running = True
        await ch.stop()  # must not raise
        assert ch._socket_client is None

    def test_socket_connect_timeout_constant_is_bounded(self):
        assert slack_module.SLACK_SOCKET_CONNECT_TIMEOUT_S > 0

    @pytest.mark.asyncio
    async def test_start_accepts_dict_config_and_registers_listener(self, monkeypatch):
        socket_client = MagicMock()
        socket_client.socket_mode_request_listeners = []
        socket_client.connect = AsyncMock(side_effect=asyncio.TimeoutError())
        socket_client.close = AsyncMock()
        web_client = AsyncMock()
        web_client.auth_test.return_value = {"user_id": "UBOT"}
        monkeypatch.setattr(slack_module, "AsyncWebClient", lambda token: web_client)
        monkeypatch.setattr(slack_module, "SocketModeClient", lambda **kw: socket_client)

        ch = SlackChannel(
            {"enabled": True, "bot_token": "xoxb-t", "app_token": "xapp-t"},
            MagicMock(spec=MessageBus),
        )
        ch._bot_user_id = None
        with pytest.raises(RuntimeError):
            await ch.start()
        assert socket_client.socket_mode_request_listeners == [ch._on_socket_request]
