"""Unit tests for the Mochat channel: inbound parsing, routing, lifecycle."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from deeptutor.partners.bus.events import OutboundMessage
from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels.mochat import (
    DelayState,
    MochatBufferedEntry,
    MochatChannel,
    MochatConfig,
    build_buffered_body,
    extract_mention_ids,
    normalize_mochat_content,
    parse_timestamp,
    resolve_mochat_target,
    resolve_require_mention,
    resolve_was_mentioned,
)


def _make_channel(partners_root: Path, **overrides) -> MochatChannel:
    defaults = {
        "enabled": True,
        "claw_token": "claw-secret",
        "agent_user_id": "agent-1",
        "allow_from": ["*"],
    }
    defaults.update(overrides)
    config = MochatConfig.model_validate(defaults)
    bus = MagicMock(spec=MessageBus)
    bus.publish_inbound = AsyncMock()
    return MochatChannel(config, bus)


def _message_event(
    *,
    message_id: str = "m-1",
    author: str = "user-1",
    content: object = "hello",
    group_id: str = "",
    timestamp: str = "2026-10-05T10:00:00Z",
    meta: dict | None = None,
    author_info: dict | None = None,
) -> dict:
    payload: dict = {"messageId": message_id, "author": author, "content": content}
    if group_id:
        payload["groupId"] = group_id
    if meta is not None:
        payload["meta"] = meta
    if author_info is not None:
        payload["authorInfo"] = author_info
    return {"type": "message.add", "timestamp": timestamp, "payload": payload}


def _published(channel: MochatChannel):
    assert channel.bus.publish_inbound.await_count > 0
    return channel.bus.publish_inbound.await_args_list[-1].args[0]


class TestPureHelpers:
    def test_normalize_content_strips_strings_and_serializes_structures(self) -> None:
        assert normalize_mochat_content("  hi  ") == "hi"
        assert normalize_mochat_content({"a": 1}) == '{"a": 1}'
        assert normalize_mochat_content([1, 2]) == "[1, 2]"

    def test_normalize_content_handles_none_and_unserializable(self) -> None:
        assert normalize_mochat_content(None) == ""
        sentinel = object()
        assert normalize_mochat_content(sentinel) == str(sentinel)

    def test_resolve_target_prefixes_and_session_inference(self) -> None:
        assert resolve_mochat_target("session_abc").id == "session_abc"
        assert resolve_mochat_target("session_abc").is_panel is False
        assert resolve_mochat_target("panel:xyz").id == "xyz"
        assert resolve_mochat_target("panel:xyz").is_panel is True
        assert resolve_mochat_target("group:g1").is_panel is True
        assert resolve_mochat_target("channel:g1").is_panel is True
        assert resolve_mochat_target("mochat:session_9").is_panel is False
        assert resolve_mochat_target("plain-id").is_panel is True

    def test_resolve_target_empty_variants(self) -> None:
        for raw in ("", "   ", "panel:", "mochat:", None):
            target = resolve_mochat_target(raw or "")
            assert target.id == ""
            assert target.is_panel is False

    def test_extract_mention_ids_heterogeneous(self) -> None:
        value = [
            "a",
            {"id": "b"},
            {"userId": "c"},
            {"_id": "d"},
            {"other": "ignored"},
            "",
            "  ",
            42,
        ]
        assert extract_mention_ids(value) == ["a", "b", "c", "d"]
        assert extract_mention_ids("not-a-list") == []
        assert extract_mention_ids(None) == []

    def test_was_mentioned_meta_flags_and_text_fallback(self) -> None:
        config = MochatConfig(agent_user_id="agent-1")
        assert resolve_was_mentioned({"meta": {"mentioned": True}}, "agent-1") is True
        assert resolve_was_mentioned({"meta": {"wasMentioned": True}}, "agent-1") is True
        assert (
            resolve_was_mentioned({"meta": {"mentionIds": [{"id": "agent-1"}]}}, "agent-1") is True
        )
        assert resolve_was_mentioned({"content": "hi <@agent-1>"}, "agent-1") is True
        assert resolve_was_mentioned({"content": "hi @agent-1"}, "agent-1") is True
        assert resolve_was_mentioned({"content": "hi there"}, "agent-1") is False
        assert resolve_was_mentioned({"meta": {"mentioned": True}}, "") is True
        assert resolve_was_mentioned({"content": "hi @agent-1"}, "") is False

    def test_parse_timestamp_variants(self) -> None:
        assert parse_timestamp("2026-10-05T10:00:00Z") is not None
        assert parse_timestamp("2026-10-05T10:00:00+00:00") is not None
        assert parse_timestamp("") is None
        assert parse_timestamp("   ") is None
        assert parse_timestamp("not-a-date") is None
        assert parse_timestamp(None) is None
        assert parse_timestamp(123) is None

    def test_build_buffered_body_grouping_and_empty_skip(self) -> None:
        assert build_buffered_body([], is_group=True) == ""
        entry = MochatBufferedEntry(raw_body="hi", author="u1")
        assert build_buffered_body([entry], is_group=False) == "hi"

        first = MochatBufferedEntry(
            raw_body="hi", author="u1", sender_name="Alice", sender_username=""
        )
        second = MochatBufferedEntry(
            raw_body="yo", author="u2", sender_name="", sender_username="bob"
        )
        third = MochatBufferedEntry(raw_body="", author="u3")
        entries = [first, second, third]
        assert build_buffered_body(entries, is_group=True) == "Alice: hi\nbob: yo"
        assert build_buffered_body(entries, is_group=False) == "hi\nyo"

    def test_resolve_require_mention_priority(self) -> None:
        config = MochatConfig(
            mention={"require_in_groups": True},
            groups={"g1": {"require_mention": False}, "sess-9": {"require_mention": True}},
        )
        assert resolve_require_mention(config, "any", "g1") is False
        assert resolve_require_mention(config, "sess-9", "") is True
        wildcard = MochatConfig(groups={"*": {"require_mention": True}})
        assert resolve_require_mention(wildcard, "any", "unlisted") is True
        assert resolve_require_mention(MochatConfig(), "any", "unlisted") is False


class TestInboundParsing:
    def test_session_message_dispatch_publishes_inbound(self, partners_root) -> None:
        channel = _make_channel(partners_root)

        asyncio.run(
            channel._process_inbound_event(
                "sess-1", _message_event(message_id="m-1", author="user-1"), "session"
            )
        )

        msg = _published(channel)
        assert msg.channel == "mochat"
        assert msg.sender_id == "user-1"
        assert msg.chat_id == "sess-1"
        assert msg.content == "hello"
        assert msg.metadata["target_kind"] == "session"
        assert msg.metadata["buffered_count"] == 1

    def test_empty_content_becomes_placeholder(self, partners_root) -> None:
        channel = _make_channel(partners_root)

        asyncio.run(
            channel._process_inbound_event("sess-1", _message_event(content=None), "session")
        )
        msg = _published(channel)
        assert msg.content == "[empty message]"

        asyncio.run(
            channel._process_inbound_event(
                "sess-1",
                _message_event(message_id="m-2", content="   "),
                "session",
            )
        )
        assert channel.bus.publish_inbound.await_count == 2
        assert _published(channel).content == "[empty message]"

    def test_malformed_payloads_are_ignored(self, partners_root) -> None:
        channel = _make_channel(partners_root)

        for event in (
            {"type": "message.add", "payload": "not-a-dict"},
            {"type": "message.add", "payload": {"messageId": "m", "content": "hi"}},
            {"type": "message.add", "payload": {"author": 123, "content": "hi"}},
            {"type": "message.add"},
        ):
            asyncio.run(channel._process_inbound_event("sess-1", event, "session"))

        assert channel.bus.publish_inbound.await_count == 0

    def test_self_author_and_disallowed_author_skipped(self, partners_root) -> None:
        channel = _make_channel(partners_root, agent_user_id="agent-1")

        asyncio.run(
            channel._process_inbound_event("sess-1", _message_event(author="agent-1"), "session")
        )
        assert channel.bus.publish_inbound.await_count == 0

        denied = _make_channel(partners_root, allow_from=["user-x"])
        asyncio.run(
            denied._process_inbound_event("sess-1", _message_event(author="user-1"), "session")
        )
        assert denied.bus.publish_inbound.await_count == 0

    def test_duplicate_message_id_deduped(self, partners_root) -> None:
        channel = _make_channel(partners_root)
        event = _message_event(message_id="m-dup")

        asyncio.run(channel._process_inbound_event("sess-1", event, "session"))
        asyncio.run(channel._process_inbound_event("sess-1", event, "session"))

        assert channel.bus.publish_inbound.await_count == 1

    def test_watch_payload_cold_session_bootstrap_discards_first_batch(self, partners_root) -> None:
        channel = _make_channel(partners_root, sessions=["sess-cold"])
        channel._seed_targets_from_config()
        assert "sess-cold" in channel._cold_sessions

        first = {
            "sessionId": "sess-cold",
            "cursor": 5,
            "events": [_message_event(message_id="m-old")],
        }
        asyncio.run(channel._handle_watch_payload(first, "session"))
        assert channel.bus.publish_inbound.await_count == 0
        assert channel._session_cursor["sess-cold"] == 5
        assert "sess-cold" not in channel._cold_sessions

        second = {
            "sessionId": "sess-cold",
            "cursor": 6,
            "events": [_message_event(message_id="m-new")],
        }
        asyncio.run(channel._handle_watch_payload(second, "session"))
        assert channel.bus.publish_inbound.await_count == 1

    def test_watch_payload_malformed_and_cursor_advance(self, partners_root) -> None:
        channel = _make_channel(partners_root, sessions=["s1"])
        channel._cold_sessions.discard("s1")

        for payload in (
            "not-a-dict",
            {"events": [_message_event()]},
            {"sessionId": "s1", "events": "not-a-list"},
            {"sessionId": "s1", "events": [{"type": "message.update"}]},
        ):
            asyncio.run(channel._handle_watch_payload(payload, "session"))
        assert channel.bus.publish_inbound.await_count == 0

        payload = {
            "sessionId": "s1",
            "cursor": 2,
            "events": [
                {"type": "message.update", "seq": 1},
                _message_event(message_id="m-live"),
            ],
        }
        asyncio.run(channel._handle_watch_payload(payload, "session"))
        assert channel.bus.publish_inbound.await_count == 1
        assert channel._session_cursor["s1"] == 2

    def test_notify_chat_message_builds_panel_event(self, partners_root) -> None:
        channel = _make_channel(partners_root, panels=["p1"], reply_delay_mode="off")

        asyncio.run(
            channel._handle_notify_chat_message(
                {
                    "groupId": "g1",
                    "converseId": "p1",
                    "_id": "m-9",
                    "author": "user-1",
                    "content": "panel hi",
                }
            )
        )
        msg = _published(channel)
        assert msg.chat_id == "p1"
        assert msg.content == "panel hi"
        assert msg.metadata["target_kind"] == "panel"
        assert msg.metadata["group_id"] == "g1"

    def test_notify_chat_message_requires_group_and_panel(self, partners_root) -> None:
        channel = _make_channel(partners_root, panels=["p1"])

        for payload in (
            {"converseId": "p1", "author": "user-1", "content": "x"},
            {"groupId": "g1", "author": "user-1", "content": "x"},
            {"groupId": "g1", "converseId": "unknown-panel", "author": "u", "content": "x"},
            "not-a-dict",
        ):
            asyncio.run(channel._handle_notify_chat_message(payload))
        assert channel.bus.publish_inbound.await_count == 0

    def test_notify_inbox_append_routes_via_converse_map(self, partners_root) -> None:
        channel = _make_channel(partners_root)
        channel._session_by_converse["c1"] = "sess-9"

        asyncio.run(
            channel._handle_notify_inbox_append(
                {
                    "type": "message",
                    "payload": {
                        "messageId": "m-5",
                        "messageAuthor": "user-1",
                        "messagePlainContent": "inbox hi",
                        "converseId": "c1",
                    },
                }
            )
        )
        msg = _published(channel)
        assert msg.chat_id == "sess-9"
        assert msg.content == "inbox hi"
        assert msg.metadata["target_kind"] == "session"

    def test_notify_inbox_append_malformed_shapes_ignored(self, partners_root) -> None:
        channel = _make_channel(partners_root)

        for payload in (
            {"type": "other"},
            {"type": "message"},
            {"type": "message", "payload": {"converseId": "c1", "groupId": "g1"}},
            "not-a-dict",
        ):
            asyncio.run(channel._handle_notify_inbox_append(payload))
        assert channel.bus.publish_inbound.await_count == 0


class TestPanelMentionAndDelay:
    def test_require_mention_off_mode_drops_unmentioned_panel_message(self, partners_root) -> None:
        channel = _make_channel(
            partners_root,
            groups={"g1": {"require_mention": True}},
            reply_delay_mode="off",
        )

        asyncio.run(
            channel._process_inbound_event(
                "p1",
                _message_event(group_id="g1", content="plain"),
                "panel",
            )
        )
        assert channel.bus.publish_inbound.await_count == 0

        asyncio.run(
            channel._process_inbound_event(
                "p1",
                _message_event(message_id="m-2", group_id="g1", meta={"mentioned": True}),
                "panel",
            )
        )
        msg = _published(channel)
        assert msg.metadata["was_mentioned"] is True

    def test_unmentioned_panel_message_buffered_until_mention_flush(self, partners_root) -> None:
        channel = _make_channel(partners_root)

        asyncio.run(
            channel._process_inbound_event(
                "p1", _message_event(message_id="m-1", group_id="g1"), "panel"
            )
        )
        asyncio.run(
            channel._process_inbound_event(
                "p1",
                _message_event(message_id="m-2", group_id="g1", content="second"),
                "panel",
            )
        )
        assert channel.bus.publish_inbound.await_count == 0
        state = channel._delay_states["panel:p1"]
        assert len(state.entries) == 2

        asyncio.run(channel._flush_delayed_entries("panel:p1", "p1", "panel", "mention", None))
        msg = _published(channel)
        assert msg.metadata["buffered_count"] == 2
        assert msg.metadata["was_mentioned"] is True
        assert msg.metadata["is_group"] is True
        assert state.entries == []
        assert state.timer is None

    def test_delay_timer_flushes_buffered_entries(self, partners_root) -> None:
        channel = _make_channel(partners_root, reply_delay_ms=30)

        async def scenario() -> None:
            await channel._process_inbound_event("p1", _message_event(group_id="g1"), "panel")
            await asyncio.sleep(0.3)

        asyncio.run(scenario())
        assert channel.bus.publish_inbound.await_count == 1
        msg = _published(channel)
        assert msg.metadata["buffered_count"] == 1
        assert msg.metadata["was_mentioned"] is False


class TestOutboundRouting:
    def test_send_session_target_posts_to_sessions_endpoint(self, partners_root) -> None:
        channel = _make_channel(partners_root)
        channel._post_json = AsyncMock(return_value={})

        asyncio.run(
            channel.send(
                OutboundMessage(
                    channel="mochat",
                    chat_id="session_abc",
                    content="hello",
                    reply_to="m-1",
                )
            )
        )
        path, body = channel._post_json.await_args.args
        assert path == "/api/claw/sessions/send"
        assert body == {"sessionId": "session_abc", "content": "hello", "replyTo": "m-1"}

    def test_send_panel_target_posts_to_panels_endpoint_with_group(self, partners_root) -> None:
        channel = _make_channel(partners_root)
        channel._post_json = AsyncMock(return_value={})

        asyncio.run(
            channel.send(
                OutboundMessage(
                    channel="mochat",
                    chat_id="panel:xyz",
                    content="hi",
                    metadata={"group_id": "g9"},
                )
            )
        )
        path, body = channel._post_json.await_args.args
        assert path == "/api/claw/groups/panels/send"
        assert body["panelId"] == "xyz"
        assert body["groupId"] == "g9"

    def test_send_empty_content_and_missing_token_skip_api(self, partners_root) -> None:
        channel = _make_channel(partners_root)
        channel._post_json = AsyncMock(return_value={})

        asyncio.run(
            channel.send(OutboundMessage(channel="mochat", chat_id="session_a", content="   "))
        )
        asyncio.run(channel.send(OutboundMessage(channel="mochat", chat_id="", content="hi")))
        assert channel._post_json.await_count == 0

        tokenless = _make_channel(partners_root, claw_token="")
        tokenless._post_json = AsyncMock(return_value={})
        asyncio.run(
            tokenless.send(OutboundMessage(channel="mochat", chat_id="session_a", content="hi"))
        )
        assert tokenless._post_json.await_count == 0

    def test_send_media_appended_to_content(self, partners_root) -> None:
        channel = _make_channel(partners_root)
        channel._post_json = AsyncMock(return_value={})

        asyncio.run(
            channel.send(
                OutboundMessage(
                    channel="mochat",
                    chat_id="session_a",
                    content="look",
                    media=["http://x/a.png", "  ", 42],
                )
            )
        )
        _, body = channel._post_json.await_args.args
        assert body["content"] == "look\nhttp://x/a.png"

    def test_send_failure_raises_for_manager_retry(self, partners_root) -> None:
        channel = _make_channel(partners_root)
        channel._post_json = AsyncMock(side_effect=RuntimeError("Mochat HTTP 500"))

        with pytest.raises(RuntimeError, match="Mochat HTTP 500"):
            asyncio.run(
                channel.send(OutboundMessage(channel="mochat", chat_id="session_a", content="hi"))
            )
        assert channel._post_json.await_count == 1


class TestLifecycle:
    def test_stop_on_fresh_instance_is_safe(self, partners_root) -> None:
        channel = _make_channel(partners_root)

        asyncio.run(channel.stop())

        assert channel._running is False
        assert channel._http is None
        assert channel._socket is None
        assert channel._refresh_task is None

    def test_stop_cancels_workers_saves_cursors_and_is_idempotent(
        self, partners_root, tmp_path
    ) -> None:
        channel = _make_channel(partners_root)
        channel._state_dir = tmp_path / "mochat-state"
        channel._cursor_path = channel._state_dir / "session_cursors.json"
        channel._session_cursor = {"s1": 7}

        async def scenario() -> None:
            channel._running = True
            channel._http = httpx.AsyncClient()
            refresh_task = asyncio.create_task(asyncio.sleep(3600))
            channel._refresh_task = refresh_task
            socket = MagicMock()
            socket.disconnect = AsyncMock()
            channel._socket = socket
            stray_timer = asyncio.create_task(asyncio.sleep(3600))
            channel._delay_states["panel:p1"] = DelayState(
                entries=[MochatBufferedEntry(raw_body="hi", author="u1")],
                timer=stray_timer,
            )

            await channel.stop()

            assert channel._running is False
            assert channel._http is None
            assert channel._socket is None
            assert channel._refresh_task is None
            assert channel._delay_states == {}
            assert socket.disconnect.await_count == 1
            with pytest.raises(asyncio.CancelledError):
                await refresh_task
            with pytest.raises(asyncio.CancelledError):
                await stray_timer

            await channel.stop()

        asyncio.run(scenario())
        cursor_file = json.loads(channel._cursor_path.read_text("utf-8"))
        assert cursor_file["cursors"] == {"s1": 7}

    def test_cursor_roundtrip_and_monotonic_guard(self, partners_root, tmp_path) -> None:
        writer = _make_channel(partners_root)
        state_dir = tmp_path / "cursors"
        writer._state_dir = state_dir
        writer._cursor_path = state_dir / "session_cursors.json"

        async def write_cursors() -> None:
            writer._mark_session_cursor("s1", 5)
            writer._mark_session_cursor("s1", 3)
            writer._mark_session_cursor("s1", -1)
            assert writer._session_cursor == {"s1": 5}
            await writer._save_session_cursors()
            if writer._cursor_save_task:
                writer._cursor_save_task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await writer._cursor_save_task

        asyncio.run(write_cursors())

        reader = _make_channel(partners_root)
        reader._state_dir = state_dir
        reader._cursor_path = state_dir / "session_cursors.json"
        asyncio.run(reader._load_session_cursors())
        assert reader._session_cursor == {"s1": 5}

    def test_cursor_load_ignores_corrupt_file(self, partners_root, tmp_path) -> None:
        channel = _make_channel(partners_root)
        channel._state_dir = tmp_path
        channel._cursor_path = tmp_path / "session_cursors.json"
        channel._cursor_path.write_text("{not json", "utf-8")

        asyncio.run(channel._load_session_cursors())

        assert channel._session_cursor == {}

    def test_default_config_exposes_camel_case_fields(self, partners_root) -> None:
        default = MochatChannel.default_config()

        assert default["clawToken"] == ""
        assert default["socketPath"] == "/socket.io"
        assert default["replyDelayMode"] == "non-mention"
