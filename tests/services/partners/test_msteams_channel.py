"""Unit tests for the Microsoft Teams channel implementation."""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from deeptutor.partners.bus.events import OutboundMessage
from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels import msteams as msteams_mod
from deeptutor.partners.channels.msteams import (
    MSTEAMS_DEPS_HINT,
    MSTEAMS_REF_FILENAME,
    MSTEAMS_REF_META_FILENAME,
    ConversationRef,
    MSTeamsChannel,
    MSTeamsConfig,
)
from deeptutor.partners.config import paths as partner_paths


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    """Redirect the channel's runtime state dir to a temp directory."""
    monkeypatch.setattr(partner_paths, "get_runtime_subdir", lambda name: tmp_path)
    return tmp_path


def _make_channel(**overrides) -> MSTeamsChannel:
    defaults = {
        "enabled": True,
        "app_id": "app-123",
        "app_password": "secret-pass",
        "allow_from": ["*"],
    }
    defaults.update(overrides)
    config = MSTeamsConfig.model_validate(defaults)
    bus = MagicMock(spec=MessageBus)
    bus.publish_inbound = AsyncMock()
    return MSTeamsChannel(config, bus)


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


class TestMSTeamsConfig:
    def test_default_values(self):
        cfg = MSTeamsConfig()
        assert cfg.enabled is False
        assert cfg.app_id == ""
        assert cfg.app_password == ""
        assert cfg.tenant_id == ""
        assert cfg.host == "0.0.0.0"
        assert cfg.port == 3978
        assert cfg.path == "/api/messages"
        assert cfg.allow_from == []
        assert cfg.reply_in_thread is True
        assert cfg.validate_inbound_auth is True
        assert cfg.ref_ttl_days == 30
        assert cfg.prune_web_chat_refs is True
        assert cfg.prune_non_personal_refs is True
        assert "smba.trafficmanager.net" in cfg.trusted_service_url_hosts
        # Inherited DeliveryOverrides flags
        assert cfg.send_progress is True
        assert cfg.send_tool_hints is True

    def test_camel_case_alias(self):
        cfg = MSTeamsConfig(app_id="a", app_password="p")
        d = cfg.model_dump(by_alias=True)
        assert "appId" in d
        assert "appPassword" in d
        assert "allowFrom" in d
        assert "validateInboundAuth" in d
        assert "trustedServiceUrlHosts" in d

    def test_from_camel_case_dict(self):
        d = {
            "enabled": True,
            "appId": "app-1",
            "appPassword": "pw",
            "allowFrom": ["*"],
            "refTtlDays": 7,
            "validateInboundAuth": False,
        }
        cfg = MSTeamsConfig.model_validate(d)
        assert cfg.app_id == "app-1"
        assert cfg.app_password == "pw"
        assert cfg.allow_from == ["*"]
        assert cfg.ref_ttl_days == 7
        assert cfg.validate_inbound_auth is False


class TestDefaultConfig:
    def test_default_config_returns_dict(self):
        cfg = MSTeamsChannel.default_config()
        assert isinstance(cfg, dict)
        assert cfg["enabled"] is False
        assert "appId" in cfg
        assert "appPassword" in cfg
        assert "trustedServiceUrlHosts" in cfg


class TestIsAllowed:
    def test_wildcard_allows_all(self, state_dir):
        ch = _make_channel(allow_from=["*"])
        assert ch.is_allowed("aad-user-1") is True
        assert ch.is_allowed("aad-anyone") is True

    def test_empty_list_denies_all(self, state_dir):
        ch = _make_channel(allow_from=[])
        assert ch.is_allowed("aad-user-1") is False
        assert ch.is_allowed("anyone") is False

    def test_sender_id_match(self, state_dir):
        ch = _make_channel(allow_from=["aad-user-1"])
        assert ch.is_allowed("aad-user-1") is True
        assert ch.is_allowed("aad-user-2") is False


class TestTrustedServiceUrl:
    def test_default_teams_host_trusted(self, state_dir):
        ch = _make_channel()
        assert ch._is_trusted_service_url("https://smba.trafficmanager.net/amer/") is True
        assert ch._is_trusted_service_url("https://SMBA.trafficmanager.net/amer/") is True

    def test_wildcard_subdomain_trusted(self, state_dir):
        ch = _make_channel()
        assert ch._is_trusted_service_url("https://smba.botframework.com/") is True
        assert ch._is_trusted_service_url("https://a.b.botframework.com/") is True

    def test_wildcard_does_not_match_bare_domain(self, state_dir):
        ch = _make_channel()
        assert ch._is_trusted_service_url("https://botframework.com/") is False
        assert ch._is_trusted_service_url("https://notbotframework.com/") is False

    def test_http_rejected(self, state_dir):
        ch = _make_channel()
        assert ch._is_trusted_service_url("http://smba.trafficmanager.net/amer/") is False
        assert ch._is_trusted_service_url("ftp://smba.trafficmanager.net/amer/") is False

    def test_unknown_host_rejected(self, state_dir):
        ch = _make_channel()
        assert ch._is_trusted_service_url("https://evil.example.com/") is False
        # Trusted suffix embedded in a larger host must not pass
        assert ch._is_trusted_service_url("https://smba.trafficmanager.net.evil.com/") is False

    def test_empty_rejected(self, state_dir):
        ch = _make_channel()
        assert ch._is_trusted_service_url("") is False
        assert ch._is_trusted_service_url("   ") is False


class TestWebchatDetection:
    def test_webchat_host_detected(self, state_dir):
        ch = _make_channel()
        assert ch._is_webchat_service_url("https://webchat.botframework.com/") is True
        assert ch._is_webchat_service_url("https://sub.webchat.botframework.com/x") is True

    def test_non_webchat_host_not_detected(self, state_dir):
        ch = _make_channel()
        assert ch._is_webchat_service_url("https://smba.trafficmanager.net/") is False
        assert ch._is_webchat_service_url("") is False


class TestSanitizeInboundText:
    def test_plain_text_passthrough(self, state_dir):
        ch = _make_channel()
        assert ch._sanitize_inbound_text(_activity(text="Hello there")) == "Hello there"
        assert (
            ch._sanitize_inbound_text(_activity(text="line one\nline two")) == "line one\nline two"
        )

    def test_strips_bot_mention_markup(self, state_dir):
        ch = _make_channel()
        out = ch._sanitize_inbound_text(_activity(text="<at>DeepTutor</at> explain entropy"))
        assert out == "explain entropy"
        out2 = ch._sanitize_inbound_text(_activity(text="<at>DeepTutor</at> hi <at>Other</at>"))
        assert out2 == "hi"

    def test_normalizes_html_entities(self, state_dir):
        ch = _make_channel()
        out = ch._sanitize_inbound_text(_activity(text="a&nbsp;&amp;&nbsp;b"))
        assert out == "a & b"
        out2 = ch._sanitize_inbound_text(_activity(text="price &lt; 5 &gt; 2"))
        assert out2 == "price < 5 > 2"

    def test_reply_wrapper_normalized(self, state_dir):
        ch = _make_channel()
        out = ch._sanitize_inbound_text(
            _activity(text="Replying to Bob Smith\nwhat about question 2?")
        )
        assert out == "User is replying to: Bob Smith\nUser reply: what about question 2?"
        assert "Replying to" not in out
        assert out.count("User reply:") == 1

    def test_reply_to_id_triggers_quote_normalization(self, state_dir):
        ch = _make_channel()
        out = ch._sanitize_inbound_text(
            _activity(text="Replying to Alice:\nfollow-up", replyToId="act-0")
        )
        assert out.startswith("User is replying to: Alice")
        assert "User reply: follow-up" in out

    def test_empty_text_returns_empty(self, state_dir):
        ch = _make_channel()
        assert ch._sanitize_inbound_text(_activity(text="")) == ""
        assert ch._sanitize_inbound_text(_activity(text="   ")) == ""


class TestHandleActivity:
    @pytest.mark.asyncio
    async def test_personal_message_dispatched(self, state_dir):
        ch = _make_channel()
        await ch._handle_activity(_activity())

        ch.bus.publish_inbound.assert_awaited_once()
        assert ch.bus.publish_inbound.await_count == 1
        msg = ch.bus.publish_inbound.call_args[0][0]
        assert msg.channel == "msteams"
        assert msg.sender_id == "aad-user-1"
        assert msg.chat_id == "a:conv-1"
        assert msg.content == "Hello bot"
        assert msg.metadata["msteams"]["conversation_type"] == "personal"
        assert msg.metadata["msteams"]["activity_id"] == "act-1"
        assert msg.metadata["msteams"]["from_name"] == "Test User"

    @pytest.mark.asyncio
    async def test_sender_id_falls_back_to_from_id(self, state_dir):
        ch = _make_channel()
        await ch._handle_activity(_activity(**{"from": {"id": "29:user"}}))
        msg = ch.bus.publish_inbound.call_args[0][0]
        assert msg.sender_id == "29:user"

        # aadObjectId wins when both ids are present
        await ch._handle_activity(_activity(**{"from": {"id": "29:user", "aadObjectId": "aad-9"}}))
        msg2 = ch.bus.publish_inbound.call_args[0][0]
        assert msg2.sender_id == "aad-9"

    @pytest.mark.asyncio
    async def test_non_message_type_ignored(self, state_dir):
        ch = _make_channel()
        await ch._handle_activity(_activity(type="conversationUpdate"))
        ch.bus.publish_inbound.assert_not_awaited()
        assert ch.bus.publish_inbound.await_count == 0
        assert ch._conversation_refs == {}

    @pytest.mark.asyncio
    async def test_untrusted_service_url_ignored(self, state_dir):
        ch = _make_channel()
        await ch._handle_activity(_activity(serviceUrl="https://evil.example.com/"))
        ch.bus.publish_inbound.assert_not_awaited()
        assert ch._conversation_refs == {}
        assert not (state_dir / MSTEAMS_REF_FILENAME).exists()

    @pytest.mark.asyncio
    async def test_own_echo_ignored(self, state_dir):
        ch = _make_channel()
        await ch._handle_activity(
            _activity(**{"from": {"id": "28:bot"}, "recipient": {"id": "28:bot"}})
        )
        ch.bus.publish_inbound.assert_not_awaited()
        assert ch.bus.publish_inbound.await_count == 0
        assert ch._conversation_refs == {}

    @pytest.mark.asyncio
    async def test_non_personal_conversation_ignored(self, state_dir):
        ch = _make_channel()
        await ch._handle_activity(
            _activity(conversation={"id": "19:thread", "conversationType": "groupChat"})
        )
        ch.bus.publish_inbound.assert_not_awaited()
        assert ch.bus.publish_inbound.await_count == 0
        assert ch._conversation_refs == {}
        assert not (state_dir / MSTEAMS_REF_FILENAME).exists()

    @pytest.mark.asyncio
    async def test_missing_sender_ignored(self, state_dir):
        ch = _make_channel()
        await ch._handle_activity(_activity(**{"from": {}}))
        ch.bus.publish_inbound.assert_not_awaited()
        assert ch.bus.publish_inbound.await_count == 0
        assert ch._conversation_refs == {}

    @pytest.mark.asyncio
    async def test_empty_conversation_type_treated_as_personal(self, state_dir):
        ch = _make_channel()
        await ch._handle_activity(_activity(conversation={"id": "a:conv-1"}))
        assert ch.bus.publish_inbound.await_count == 1
        msg = ch.bus.publish_inbound.call_args[0][0]
        assert msg.metadata["msteams"]["conversation_type"] == "personal"
        assert ch._conversation_refs["a:conv-1"].conversation_type is None

    @pytest.mark.asyncio
    async def test_missing_tenant_stores_none(self, state_dir):
        ch = _make_channel()
        await ch._handle_activity(_activity(channelData={}))
        assert ch.bus.publish_inbound.await_count == 1
        assert ch._conversation_refs["a:conv-1"].tenant_id is None
        assert ch._conversation_refs["a:conv-1"].bot_id == "28:bot"

    @pytest.mark.asyncio
    async def test_denied_sender_not_dispatched_and_no_ref_stored(self, state_dir):
        ch = _make_channel(allow_from=[])
        await ch._handle_activity(_activity())
        ch.bus.publish_inbound.assert_not_awaited()
        assert ch.bus.publish_inbound.await_count == 0
        assert ch._conversation_refs == {}
        assert not (state_dir / MSTEAMS_REF_FILENAME).exists()

    @pytest.mark.asyncio
    async def test_mention_only_text_uses_fallback_response(self, state_dir):
        ch = _make_channel()
        await ch._handle_activity(_activity(text="<at>DeepTutor</at>"))
        msg = ch.bus.publish_inbound.call_args[0][0]
        assert msg.content == ch.config.mention_only_response
        assert msg.chat_id == "a:conv-1"
        assert msg.sender_id == "aad-user-1"


class TestConversationRefs:
    @pytest.mark.asyncio
    async def test_ref_stored_and_persisted(self, state_dir):
        ch = _make_channel()
        await ch._handle_activity(_activity())

        ref = ch._conversation_refs["a:conv-1"]
        assert ref.service_url == "https://smba.trafficmanager.net/amer/"
        assert ref.activity_id == "act-1"
        assert ref.bot_id == "28:bot"
        assert ref.tenant_id == "tenant-1"
        assert ref.conversation_type == "personal"

        refs_on_disk = json.loads((state_dir / MSTEAMS_REF_FILENAME).read_text())
        assert "a:conv-1" in refs_on_disk
        assert refs_on_disk["a:conv-1"]["conversation_id"] == "a:conv-1"

        meta_on_disk = json.loads((state_dir / MSTEAMS_REF_META_FILENAME).read_text())
        assert meta_on_disk["a:conv-1"]["updated_at"] is not None

    @pytest.mark.asyncio
    async def test_refs_reload_on_new_instance(self, state_dir):
        ch1 = _make_channel()
        await ch1._handle_activity(_activity())

        ch2 = _make_channel()
        assert "a:conv-1" in ch2._conversation_refs
        assert ch2._conversation_refs["a:conv-1"].service_url == (
            "https://smba.trafficmanager.net/amer/"
        )
        assert ch2._conversation_refs["a:conv-1"].activity_id == "act-1"

    @pytest.mark.asyncio
    async def test_stale_ref_pruned_by_ttl_on_load(self, state_dir):
        ch1 = _make_channel()
        await ch1._handle_activity(_activity())

        stale_ts = time.time() - 31 * 24 * 60 * 60
        (state_dir / MSTEAMS_REF_META_FILENAME).write_text(
            json.dumps({"a:conv-1": {"updated_at": stale_ts}})
        )

        ch2 = _make_channel(ref_ttl_days=30)
        assert "a:conv-1" not in ch2._conversation_refs
        refs_on_disk = json.loads((state_dir / MSTEAMS_REF_FILENAME).read_text())
        assert refs_on_disk == {}

    @pytest.mark.asyncio
    async def test_fresh_ref_survives_ttl_on_load(self, state_dir):
        ch1 = _make_channel()
        await ch1._handle_activity(_activity())

        ch2 = _make_channel(ref_ttl_days=30)
        assert "a:conv-1" in ch2._conversation_refs
        assert ch2._conversation_refs["a:conv-1"].activity_id == "act-1"
        assert ch2._conversation_refs["a:conv-1"].tenant_id == "tenant-1"

    def test_normalize_ref_record_rejects_invalid(self, state_dir):
        ch = _make_channel()
        assert ch._normalize_ref_record(None) is None
        assert ch._normalize_ref_record("x") is None
        assert ch._normalize_ref_record({"service_url": "", "conversation_id": "c"}) is None
        assert (
            ch._normalize_ref_record({"service_url": "https://x/", "conversation_id": ""}) is None
        )

    def test_normalize_ref_record_minimal_fields(self, state_dir):
        ch = _make_channel()
        ref = ch._normalize_ref_record(
            {"service_url": "https://smba.trafficmanager.net/amer/", "conversation_id": "c1"}
        )
        assert ref is not None
        assert ref.conversation_id == "c1"
        assert ref.bot_id is None
        assert ref.activity_id is None
        assert ref.tenant_id is None

    def test_merge_keeps_newer_disk_ref(self, state_dir):
        ch = _make_channel()
        ch._conversation_refs["a:conv-1"] = ConversationRef(
            service_url="https://smba.trafficmanager.net/amer/",
            conversation_id="a:conv-1",
            updated_at=1000.0,
        )
        (state_dir / MSTEAMS_REF_FILENAME).write_text(
            json.dumps(
                {
                    "a:conv-1": {
                        "service_url": "https://smba.trafficmanager.net/amer/",
                        "conversation_id": "a:conv-1",
                        "activity_id": "newer",
                    }
                }
            )
        )
        (state_dir / MSTEAMS_REF_META_FILENAME).write_text(
            json.dumps({"a:conv-1": {"updated_at": 2000.0}})
        )
        ch._merge_refs_from_disk_locked()
        assert ch._conversation_refs["a:conv-1"].activity_id == "newer"

    def test_merge_keeps_memory_ref_when_disk_older(self, state_dir):
        ch = _make_channel()
        ch._conversation_refs["a:conv-1"] = ConversationRef(
            service_url="https://smba.trafficmanager.net/amer/",
            conversation_id="a:conv-1",
            activity_id="mem",
            updated_at=5000.0,
        )
        (state_dir / MSTEAMS_REF_FILENAME).write_text(
            json.dumps(
                {
                    "a:conv-1": {
                        "service_url": "https://smba.trafficmanager.net/amer/",
                        "conversation_id": "a:conv-1",
                    }
                }
            )
        )
        (state_dir / MSTEAMS_REF_META_FILENAME).write_text(
            json.dumps({"a:conv-1": {"updated_at": 1000.0}})
        )
        ch._merge_refs_from_disk_locked()
        assert ch._conversation_refs["a:conv-1"].activity_id == "mem"

    def test_prune_drops_webchat_refs(self, state_dir):
        ch = _make_channel()
        ch._conversation_refs["wc"] = ConversationRef(
            service_url="https://webchat.botframework.com/",
            conversation_id="wc",
            conversation_type="personal",
            updated_at=time.time(),
        )
        assert ch._prune_conversation_refs() is True
        assert "wc" not in ch._conversation_refs
        assert ch._conversation_refs == {}

    def test_prune_drops_non_personal_refs(self, state_dir):
        ch = _make_channel()
        ch._conversation_refs["grp"] = ConversationRef(
            service_url="https://smba.trafficmanager.net/amer/",
            conversation_id="grp",
            conversation_type="groupChat",
            updated_at=time.time(),
        )
        assert ch._prune_conversation_refs() is True
        assert "grp" not in ch._conversation_refs
        assert ch._conversation_refs == {}

    def test_prune_drops_untrusted_refs(self, state_dir):
        ch = _make_channel()
        ch._conversation_refs["bad"] = ConversationRef(
            service_url="https://evil.example.com/",
            conversation_id="bad",
            conversation_type="personal",
            updated_at=time.time(),
        )
        assert ch._prune_conversation_refs() is True
        assert "bad" not in ch._conversation_refs
        assert ch._conversation_refs == {}

    def test_prune_keeps_valid_refs(self, state_dir):
        ch = _make_channel()
        ch._conversation_refs["ok"] = ConversationRef(
            service_url="https://smba.trafficmanager.net/amer/",
            conversation_id="ok",
            conversation_type="personal",
            updated_at=time.time(),
        )
        assert ch._prune_conversation_refs() is False
        assert "ok" in ch._conversation_refs
        assert len(ch._conversation_refs) == 1

    def test_prune_empty_refs_is_noop(self, state_dir):
        ch = _make_channel()
        assert ch._prune_conversation_refs() is False
        assert ch._conversation_refs == {}

    def test_touch_updates_recent_timestamp_only_after_interval(self, state_dir):
        ch = _make_channel(ref_touch_interval_s=300)
        old_ts = time.time() - 10  # within the 300s interval
        ch._conversation_refs["c"] = ConversationRef(
            service_url="https://smba.trafficmanager.net/amer/",
            conversation_id="c",
            conversation_type="personal",
            updated_at=old_ts,
        )
        ch._touch_conversation_ref("c")
        assert ch._conversation_refs["c"].updated_at == old_ts

        ch._conversation_refs["c"].updated_at = time.time() - 600  # past interval
        ch._touch_conversation_ref("c")
        assert ch._conversation_refs["c"].updated_at > time.time() - 5

    def test_touch_unknown_chat_is_noop(self, state_dir):
        ch = _make_channel(ref_touch_interval_s=0)
        ch._touch_conversation_ref("missing")  # must not raise
        assert ch._conversation_refs == {}


class TestSend:
    @pytest.mark.asyncio
    async def test_send_without_http_client_raises(self, state_dir):
        ch = _make_channel()
        msg = OutboundMessage(channel="msteams", chat_id="a:conv-1", content="hi")
        with pytest.raises(RuntimeError) as exc:
            await ch.send(msg)
        assert "not initialized" in str(exc.value)

    @pytest.mark.asyncio
    async def test_send_without_ref_raises(self, state_dir):
        ch = _make_channel()
        ch._http = AsyncMock()
        msg = OutboundMessage(channel="msteams", chat_id="a:unknown", content="hi")
        with pytest.raises(RuntimeError) as exc:
            await ch.send(msg)
        assert "ref not found" in str(exc.value)
        assert "a:unknown" in str(exc.value)
        assert ch._http.post.await_count == 0

    @pytest.mark.asyncio
    async def test_send_untrusted_ref_raises(self, state_dir):
        ch = _make_channel()
        ch._http = AsyncMock()
        ch._conversation_refs["a:conv-1"] = ConversationRef(
            service_url="https://evil.example.com/",
            conversation_id="a:conv-1",
        )
        msg = OutboundMessage(channel="msteams", chat_id="a:conv-1", content="hi")
        with pytest.raises(RuntimeError) as exc:
            await ch.send(msg)
        assert "untrusted service_url" in str(exc.value)
        assert ch._http.post.await_count == 0

    @pytest.mark.asyncio
    async def test_send_posts_to_activities_endpoint(self, state_dir):
        ch = _make_channel()
        await ch._handle_activity(_activity())

        ch._http = AsyncMock()
        ch._token = "cached-token"
        ch._token_expires_at = time.time() + 3600
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        ch._http.post.return_value = resp

        msg = OutboundMessage(channel="msteams", chat_id="a:conv-1", content="Answer")
        await ch.send(msg)

        ch._http.post.assert_awaited_once()
        assert ch._http.post.await_count == 1
        call = ch._http.post.call_args
        assert call.args[0] == (
            "https://smba.trafficmanager.net/amer/v3/conversations/a:conv-1/activities"
        )
        assert call.kwargs["headers"]["Authorization"] == "Bearer cached-token"
        assert call.kwargs["json"]["text"] == "Answer"
        assert call.kwargs["json"]["replyToId"] == "act-1"  # reply_in_thread default
        assert call.kwargs["json"]["type"] == "message"
        assert call.kwargs["headers"]["Content-Type"] == "application/json"

    @pytest.mark.asyncio
    async def test_send_reply_in_thread_disabled_omits_reply_to_id(self, state_dir):
        ch = _make_channel(reply_in_thread=False)
        await ch._handle_activity(_activity())

        ch._http = AsyncMock()
        ch._token = "cached-token"
        ch._token_expires_at = time.time() + 3600
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        ch._http.post.return_value = resp

        await ch.send(OutboundMessage(channel="msteams", chat_id="a:conv-1", content="Answer"))
        payload = ch._http.post.call_args.kwargs["json"]
        assert "replyToId" not in payload
        assert payload["text"] == "Answer"
        assert payload["type"] == "message"

    @pytest.mark.asyncio
    async def test_send_empty_content_uses_placeholder_text(self, state_dir):
        ch = _make_channel()
        await ch._handle_activity(_activity())

        ch._http = AsyncMock()
        ch._token = "cached-token"
        ch._token_expires_at = time.time() + 3600
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        ch._http.post.return_value = resp

        await ch.send(OutboundMessage(channel="msteams", chat_id="a:conv-1", content=""))
        payload = ch._http.post.call_args.kwargs["json"]
        assert payload["text"] == " "
        assert payload["replyToId"] == "act-1"

    @pytest.mark.asyncio
    async def test_send_updates_ref_timestamp(self, state_dir):
        ch = _make_channel(ref_touch_interval_s=0)
        await ch._handle_activity(_activity())
        old_ts = ch._conversation_refs["a:conv-1"].updated_at

        ch._http = AsyncMock()
        ch._token = "cached-token"
        ch._token_expires_at = time.time() + 3600
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        ch._http.post.return_value = resp

        await ch.send(OutboundMessage(channel="msteams", chat_id="a:conv-1", content="x"))
        assert ch._conversation_refs["a:conv-1"].updated_at >= old_ts
        # The refreshed ref is persisted
        meta_on_disk = json.loads((state_dir / MSTEAMS_REF_META_FILENAME).read_text())
        assert meta_on_disk["a:conv-1"]["updated_at"] >= old_ts

    @pytest.mark.asyncio
    async def test_send_failure_raises_for_manager_retry(self, state_dir):
        ch = _make_channel()
        await ch._handle_activity(_activity())

        ch._http = AsyncMock()
        ch._token = "cached-token"
        ch._token_expires_at = time.time() + 3600
        ch._http.post.side_effect = RuntimeError("boom")

        msg = OutboundMessage(channel="msteams", chat_id="a:conv-1", content="Answer")
        with pytest.raises(RuntimeError) as exc:
            await ch.send(msg)
        assert "boom" in str(exc.value)
        assert ch._http.post.await_count == 1


class TestAccessToken:
    @pytest.mark.asyncio
    async def test_token_fetched_and_cached(self, state_dir):
        ch = _make_channel()
        ch._http = AsyncMock()
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"access_token": "tok-1", "expires_in": 3600}
        ch._http.post.return_value = resp

        assert await ch._get_access_token() == "tok-1"
        assert ch._http.post.await_count == 1
        url = ch._http.post.call_args.args[0]
        assert url == "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token"
        data = ch._http.post.call_args.kwargs["data"]
        assert data["grant_type"] == "client_credentials"
        assert data["client_id"] == "app-123"
        assert data["scope"] == "https://api.botframework.com/.default"

        # A cached, unexpired token avoids a second token request
        assert await ch._get_access_token() == "tok-1"
        assert ch._http.post.await_count == 1

    @pytest.mark.asyncio
    async def test_tenant_override_changes_token_url(self, state_dir):
        ch = _make_channel(tenant_id="tenant-9")
        ch._http = AsyncMock()
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"access_token": "tok-2", "expires_in": 3600}
        ch._http.post.return_value = resp

        assert await ch._get_access_token() == "tok-2"
        url = ch._http.post.call_args.args[0]
        assert url.startswith("https://login.microsoftonline.com/tenant-9/")
        assert ch._token == "tok-2"

    @pytest.mark.asyncio
    async def test_token_without_http_client_raises(self, state_dir):
        ch = _make_channel()
        with pytest.raises(RuntimeError) as exc:
            await ch._get_access_token()
        assert "not initialized" in str(exc.value)


class TestSupportsStreaming:
    def test_streaming_not_supported(self, state_dir):
        # msteams does not implement send_delta; supports_streaming must be False.
        ch = _make_channel()
        assert ch.supports_streaming is False
        assert type(ch).send_delta is msteams_mod.BaseChannel.send_delta


class TestValidateInboundAuth:
    @pytest.mark.asyncio
    async def test_missing_deps_raises_clear_error(self, state_dir, monkeypatch):
        ch = _make_channel()
        monkeypatch.setattr(msteams_mod, "MSTEAMS_AVAILABLE", False)
        with pytest.raises(RuntimeError) as exc:
            await ch._validate_inbound_auth("Bearer abc", _activity())
        assert MSTEAMS_DEPS_HINT in str(exc.value)

    @pytest.mark.asyncio
    async def test_missing_bearer_rejected(self, state_dir):
        ch = _make_channel()
        with pytest.raises(ValueError) as exc:
            await ch._validate_inbound_auth("", _activity())
        assert "missing bearer token" in str(exc.value)

    @pytest.mark.asyncio
    async def test_empty_bearer_rejected(self, state_dir):
        ch = _make_channel()
        with pytest.raises(ValueError) as exc:
            await ch._validate_inbound_auth("Bearer   ", _activity())
        assert "empty bearer token" in str(exc.value)

    @pytest.mark.asyncio
    async def test_non_bearer_scheme_rejected(self, state_dir):
        ch = _make_channel()
        with pytest.raises(ValueError) as exc:
            await ch._validate_inbound_auth("Basic abc", _activity())
        assert "bearer" in str(exc.value).lower()


@pytest.mark.skipif(not msteams_mod.MSTEAMS_AVAILABLE, reason="PyJWT[crypto] not installed")
class TestValidateInboundAuthSignature:
    @pytest.mark.asyncio
    async def test_token_without_kid_rejected(self, state_dir):
        import jwt as pyjwt

        ch = _make_channel()
        token = pyjwt.encode({"sub": "u"}, "secret", algorithm="HS256")
        with pytest.raises(ValueError) as exc:
            await ch._validate_inbound_auth(f"Bearer {token}", _activity())
        assert "kid" in str(exc.value)

    @pytest.mark.asyncio
    async def test_signing_key_lookup_miss_rejected(self, state_dir):
        from unittest.mock import patch

        import jwt as pyjwt

        ch = _make_channel()
        token = pyjwt.encode(
            {"sub": "u"}, "secret", algorithm="HS256", headers={"kid": "missing-kid"}
        )
        with patch.object(ch, "_get_botframework_jwks", new=AsyncMock(return_value={"keys": []})):
            with pytest.raises(ValueError) as exc:
                await ch._validate_inbound_auth(f"Bearer {token}", _activity())
        assert "signing key not found" in str(exc.value)
        assert "missing-kid" in str(exc.value)


class TestStop:
    @pytest.mark.asyncio
    async def test_stop_without_start_is_safe(self, state_dir):
        ch = _make_channel()
        ch._running = True
        await ch.stop()
        assert ch._running is False
        assert ch._server is None
        assert ch._http is None
