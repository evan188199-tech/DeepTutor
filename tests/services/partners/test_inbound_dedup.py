"""Inbound replay dedup regression tests for push-based channels.

Platforms redeliver inbound events (webhook retries, stream reconnect
replays): the same platform message id arriving twice must produce exactly
one bus publish, while distinct ids and TTL-expired ids keep flowing.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels.dedup import InboundDeduplicator
from deeptutor.partners.channels.dingtalk import DingTalkChannel
from deeptutor.partners.channels.discord import DiscordChannel
from deeptutor.partners.channels.msteams import MSTeamsChannel, MSTeamsConfig
from deeptutor.partners.channels.slack import SlackChannel
from deeptutor.partners.config import paths as partner_paths


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    """Redirect the msteams runtime state dir to a temp directory."""
    monkeypatch.setattr(partner_paths, "get_runtime_subdir", lambda name: tmp_path)
    return tmp_path


class TestInboundDeduplicator:
    def test_first_delivery_not_duplicate(self):
        dedup = InboundDeduplicator(ttl_s=300)
        assert dedup.is_duplicate("m1", now=1000.0) is False

    def test_immediate_replay_is_duplicate(self):
        dedup = InboundDeduplicator(ttl_s=300)
        dedup.is_duplicate("m1", now=1000.0)
        assert dedup.is_duplicate("m1", now=1001.0) is True

    def test_id_free_again_after_ttl_window(self):
        dedup = InboundDeduplicator(ttl_s=300)
        dedup.is_duplicate("m1", now=1000.0)
        # Still inside the window: replay suppressed.
        assert dedup.is_duplicate("m1", now=1001.0) is True
        # Past the window: the guard no longer blocks this id.
        assert dedup.is_duplicate("m1", now=2000.0) is False

    def test_new_ids_never_blocked_by_window(self):
        dedup = InboundDeduplicator(ttl_s=300)
        dedup.is_duplicate("m1", now=1000.0)
        assert dedup.is_duplicate("m2", now=1000.5) is False
        assert dedup.is_duplicate("m3", now=1000.6) is False

    def test_empty_id_fails_open(self):
        dedup = InboundDeduplicator(ttl_s=300)
        assert dedup.is_duplicate(None) is False
        assert dedup.is_duplicate("") is False
        assert dedup.is_duplicate("   ") is False

    def test_duplicate_refreshes_ttl_window(self):
        dedup = InboundDeduplicator(ttl_s=300)
        dedup.is_duplicate("m1", now=1000.0)
        # Replay near the end of the window refreshes the entry.
        assert dedup.is_duplicate("m1", now=1299.0) is True
        # Original timestamp expired, but the refresh keeps the guard alive.
        assert dedup.is_duplicate("m1", now=1305.0) is True

    def test_size_bound_evicts_oldest_first(self):
        dedup = InboundDeduplicator(ttl_s=300, max_ids=2)
        dedup.is_duplicate("m1", now=1000.0)
        dedup.is_duplicate("m2", now=1000.1)
        dedup.is_duplicate("m3", now=1000.2)
        # "m1" was evicted by the size bound; the two newest ids remain.
        assert list(dedup._seen) == ["m2", "m3"]


def _msteams_channel(state_dir) -> MSTeamsChannel:
    config = MSTeamsConfig.model_validate(
        {
            "enabled": True,
            "appId": "app-1",
            "appPassword": "pw",
            "allowFrom": ["*"],
        }
    )
    return MSTeamsChannel(config, MessageBus())


def _activity(**overrides) -> dict:
    base = {
        "type": "message",
        "id": "act-1",
        "text": "Hello bot",
        "serviceUrl": "https://smba.trafficmanager.net/amer/",
        "from": {"id": "29:user", "aadObjectId": "aad-user-1", "name": "Test User"},
        "recipient": {"id": "28:bot"},
        "conversation": {"id": "a:conv-1", "conversationType": "personal"},
        "channelData": {"tenant": {"id": "tenant-1"}},
    }
    base.update(overrides)
    return base


class TestMSTeamsInboundDedup:
    @pytest.mark.asyncio
    async def test_activity_replay_published_once(self, state_dir):
        ch = _msteams_channel(state_dir)
        activity = _activity()
        await ch._handle_activity(activity)
        await ch._handle_activity(activity)
        assert ch.bus.inbound.qsize() == 1

    @pytest.mark.asyncio
    async def test_distinct_activity_ids_both_published(self, state_dir):
        ch = _msteams_channel(state_dir)
        await ch._handle_activity(_activity(id="act-1"))
        await ch._handle_activity(_activity(id="act-2"))
        assert ch.bus.inbound.qsize() == 2

    @pytest.mark.asyncio
    async def test_activity_without_id_fails_open(self, state_dir):
        ch = _msteams_channel(state_dir)
        activity = _activity(id="")
        await ch._handle_activity(activity)
        await ch._handle_activity(activity)
        assert ch.bus.inbound.qsize() == 2


def _discord_channel() -> DiscordChannel:
    return DiscordChannel({"enabled": True, "token": "t", "allowFrom": ["*"]}, MessageBus())


def _discord_payload(**overrides) -> dict:
    base = {
        "id": "msg-1",
        "author": {"id": "user-1"},
        "channel_id": "chan-1",
        "content": "hello",
    }
    base.update(overrides)
    return base


class TestDiscordInboundDedup:
    @pytest.mark.asyncio
    async def test_message_replay_published_once(self):
        ch = _discord_channel()
        payload = _discord_payload()
        await ch._handle_message_create(payload)
        await ch._handle_message_create(payload)
        assert ch.bus.inbound.qsize() == 1

    @pytest.mark.asyncio
    async def test_distinct_message_ids_both_published(self):
        ch = _discord_channel()
        await ch._handle_message_create(_discord_payload(id="msg-1"))
        await ch._handle_message_create(_discord_payload(id="msg-2"))
        assert ch.bus.inbound.qsize() == 2


def _slack_channel() -> SlackChannel:
    return SlackChannel(
        {
            "enabled": True,
            "botToken": "xoxb-test",
            "appToken": "xapp-test",
            "allowFrom": ["*"],
        },
        MessageBus(),
    )


def _slack_req(event: dict) -> SimpleNamespace:
    return SimpleNamespace(
        type="events_api",
        envelope_id="env-1",
        payload={"event": event},
    )


def _slack_client() -> SimpleNamespace:
    return SimpleNamespace(send_socket_mode_response=AsyncMock())


def _slack_dm_event(**overrides) -> dict:
    base = {
        "type": "message",
        "user": "U1",
        "channel": "D1",
        "channel_type": "im",
        "ts": "1000.0001",
        "text": "hello",
    }
    base.update(overrides)
    return base


class TestSlackInboundDedup:
    @pytest.mark.asyncio
    async def test_event_replay_published_once(self):
        ch = _slack_channel()
        client = _slack_client()
        req = _slack_req(_slack_dm_event())
        await ch._on_socket_request(client, req)
        await ch._on_socket_request(client, req)
        assert ch.bus.inbound.qsize() == 1

    @pytest.mark.asyncio
    async def test_distinct_ts_both_published(self):
        ch = _slack_channel()
        client = _slack_client()
        await ch._on_socket_request(client, _slack_req(_slack_dm_event(ts="1000.0001")))
        await ch._on_socket_request(client, _slack_req(_slack_dm_event(ts="1000.0002")))
        assert ch.bus.inbound.qsize() == 2

    @pytest.mark.asyncio
    async def test_message_and_app_mention_pair_processed_once(self):
        """A mention arrives as `message` + `app_mention` with the same ts."""
        ch = _slack_channel()
        ch._bot_user_id = "U_BOT"
        client = _slack_client()
        mention_event = _slack_dm_event(channel_type="channel", text="<@U_BOT> help")
        # The `message` twin is skipped by the mention guard (no id consumed).
        await ch._on_socket_request(client, _slack_req(mention_event))
        assert ch.bus.inbound.qsize() == 0
        app_mention = _slack_dm_event(
            channel_type="channel", text="<@U_BOT> help", type="app_mention"
        )
        await ch._on_socket_request(client, _slack_req(app_mention))
        assert ch.bus.inbound.qsize() == 1

    @pytest.mark.asyncio
    async def test_policy_skipped_delivery_does_not_consume_id(self):
        """A policy-skipped `message` must not block its `app_mention` twin."""
        ch = _slack_channel()
        ch._bot_user_id = None  # degraded: mention-text guard cannot fire
        client = _slack_client()
        # Group message without mention, mention policy → skipped by policy.
        plain = _slack_dm_event(channel_type="channel", ts="2000.0001", text="plain text")
        await ch._on_socket_request(client, _slack_req(plain))
        assert ch.bus.inbound.qsize() == 0
        # A later mention with the SAME ts (Slack edits redeliver the event)
        # must still be processed: the skip above consumed nothing.
        mention = _slack_dm_event(
            channel_type="channel", ts="2000.0001", text="plain text", type="app_mention"
        )
        await ch._on_socket_request(client, _slack_req(mention))
        assert ch.bus.inbound.qsize() == 1


def _dingtalk_channel() -> DingTalkChannel:
    return DingTalkChannel(
        {"enabled": True, "clientId": "cid", "clientSecret": "sec", "allowFrom": ["*"]},
        MessageBus(),
    )


class TestDingTalkInboundDedup:
    @pytest.mark.asyncio
    async def test_message_replay_published_once(self):
        ch = _dingtalk_channel()
        await ch._on_message("hi", "staff-1", "User", message_id="mid-1")
        await ch._on_message("hi", "staff-1", "User", message_id="mid-1")
        assert ch.bus.inbound.qsize() == 1

    @pytest.mark.asyncio
    async def test_distinct_message_ids_both_published(self):
        ch = _dingtalk_channel()
        await ch._on_message("hi", "staff-1", "User", message_id="mid-1")
        await ch._on_message("again", "staff-1", "User", message_id="mid-2")
        assert ch.bus.inbound.qsize() == 2

    @pytest.mark.asyncio
    async def test_message_without_id_fails_open(self):
        ch = _dingtalk_channel()
        await ch._on_message("hi", "staff-1", "User", message_id=None)
        await ch._on_message("hi", "staff-1", "User", message_id=None)
        assert ch.bus.inbound.qsize() == 2
