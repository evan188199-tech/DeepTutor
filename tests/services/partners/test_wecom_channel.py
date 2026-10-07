"""Regression coverage for the WeCom SDK integration."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from pathlib import Path
import sys
from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from deeptutor.partners.bus.events import InboundMessage, OutboundMessage
from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels import wecom


class CapturingWSClient:
    """Minimal wecom-aibot-sdk 1.0.8-compatible client used by the channel test."""

    connected = asyncio.Event()
    instance: CapturingWSClient | None = None

    def __init__(
        self,
        bot_id: str,
        secret: str,
        *,
        reconnect_interval: int = 1000,
        max_reconnect_attempts: int = 10,
        heartbeat_interval: int = 30000,
    ) -> None:
        self.bot_id = bot_id
        self.secret = secret
        self.reconnect_interval = reconnect_interval
        self.max_reconnect_attempts = max_reconnect_attempts
        self.heartbeat_interval = heartbeat_interval
        self.handlers: dict[str, Any] = {}
        self.did_connect = False
        self.did_disconnect = False
        type(self).instance = self

    def on(self, event: str, handler: Any) -> None:
        self.handlers[event] = handler

    async def connect(self) -> None:
        self.did_connect = True
        type(self).connected.set()

    async def disconnect(self) -> None:
        self.did_disconnect = True


def test_wecom_channel_uses_the_pinned_sdk_startup_contract(monkeypatch: Any) -> None:
    """Use the positional constructor, connect(), and zero-argument lifecycle events."""
    # Regression for https://github.com/HKUDS/DeepTutor/issues/616
    sdk = ModuleType("wecom_aibot_sdk")
    sdk.WSClient = CapturingWSClient
    sdk.generate_req_id = lambda prefix: f"{prefix}-request"
    monkeypatch.setitem(sys.modules, "wecom_aibot_sdk", sdk)
    monkeypatch.setattr(wecom, "WECOM_AVAILABLE", True)

    async def exercise_startup() -> None:
        CapturingWSClient.connected = asyncio.Event()
        CapturingWSClient.instance = None
        channel = wecom.WecomChannel(
            {"bot_id": "bot-id", "secret": "bot-secret"},
            Mock(),
        )
        startup = asyncio.create_task(channel.start())
        await asyncio.wait_for(CapturingWSClient.connected.wait(), timeout=1)

        client = CapturingWSClient.instance
        assert client is not None
        assert (client.bot_id, client.secret) == ("bot-id", "bot-secret")
        assert client.reconnect_interval == 1000
        assert client.max_reconnect_attempts == -1
        assert client.heartbeat_interval == 30000
        assert client.did_connect

        await client.handlers["connected"]()
        await client.handlers["authenticated"]()

        startup.cancel()
        try:
            await startup
        except asyncio.CancelledError:
            pass

    asyncio.run(exercise_startup())


# ---------------------------------------------------------------------------
# Fakes and helpers for the strengthened contract tests below.
# ---------------------------------------------------------------------------


@dataclass
class FakeFrame:
    """Stand-in for the SDK's WsFrame: only ``body`` matters to the channel."""

    body: Any = None


class FakeWSClient:
    """wecom-aibot-sdk-compatible client that records every side effect."""

    instance: FakeWSClient | None = None
    ready: asyncio.Event | None = None

    def __init__(
        self,
        bot_id: str,
        secret: str,
        *,
        reconnect_interval: int = 1000,
        max_reconnect_attempts: int = 10,
        heartbeat_interval: int = 30000,
    ) -> None:
        self.bot_id = bot_id
        self.secret = secret
        self.reconnect_interval = reconnect_interval
        self.max_reconnect_attempts = max_reconnect_attempts
        self.heartbeat_interval = heartbeat_interval
        self.handlers: dict[str, Any] = {}
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.stream_replies: list[dict[str, Any]] = []
        self.welcome_replies: list[tuple[Any, dict[str, Any]]] = []
        self.download_requests: list[tuple[str, str]] = []
        self.download_results: list[tuple[bytes, str] | Exception] = []
        self.fail_stream: Exception | None = None
        self.fail_welcome: Exception | None = None
        type(self).instance = self

    def on(self, event: str, handler: Any) -> None:
        self.handlers[event] = handler

    async def connect(self) -> None:
        self.connect_calls += 1
        if type(self).ready is not None:
            type(self).ready.set()

    async def disconnect(self) -> None:
        self.disconnect_calls += 1

    async def reply_stream(self, frame: Any, stream_id: str, content: str, *, finish: bool) -> None:
        if self.fail_stream is not None:
            raise self.fail_stream
        self.stream_replies.append(
            {"frame": frame, "stream_id": stream_id, "content": content, "finish": finish}
        )

    async def reply_welcome(self, frame: Any, payload: dict[str, Any]) -> None:
        if self.fail_welcome is not None:
            raise self.fail_welcome
        self.welcome_replies.append((frame, payload))

    async def download_file(self, file_url: str, aes_key: str) -> tuple[bytes, str]:
        self.download_requests.append((file_url, aes_key))
        result = self.download_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _make_channel(**config_overrides: Any) -> wecom.WecomChannel:
    """Build a WeCom channel with a recording bus, allow-all sender policy."""
    config = {
        "bot_id": "bot-id",
        "secret": "bot-secret",
        "allow_from": ["*"],
    }
    config.update(config_overrides)
    bus = MagicMock(spec=MessageBus)
    bus.publish_inbound = AsyncMock()
    return wecom.WecomChannel(config, bus)


def _text_frame(
    msgid: str = "m1",
    chatid: str = "chat-1",
    text: str = "hello",
    *,
    from_info: Any = None,
    chattype: str | None = None,
) -> FakeFrame:
    if from_info is None:
        from_info = {"userid": "user-1"}
    body: dict[str, Any] = {
        "msgid": msgid,
        "chatid": chatid,
        "from": from_info,
        "text": {"content": text},
    }
    if chattype is not None:
        body["chattype"] = chattype
    return FakeFrame(body=body)


def _install_fake_sdk(monkeypatch: Any) -> None:
    sdk = ModuleType("wecom_aibot_sdk")
    sdk.WSClient = FakeWSClient
    sdk.generate_req_id = lambda prefix: f"{prefix}-gen"
    monkeypatch.setitem(sys.modules, "wecom_aibot_sdk", sdk)
    monkeypatch.setattr(wecom, "WECOM_AVAILABLE", True)


async def _start_channel(
    monkeypatch: Any, **config_overrides: Any
) -> tuple[wecom.WecomChannel, FakeWSClient, asyncio.Task[None]]:
    """Start a channel against the fake SDK and wait for it to connect."""
    FakeWSClient.ready = asyncio.Event()
    FakeWSClient.instance = None
    _install_fake_sdk(monkeypatch)
    channel = _make_channel(**config_overrides)
    task = asyncio.create_task(channel.start())
    await asyncio.wait_for(FakeWSClient.ready.wait(), timeout=1)
    client = FakeWSClient.instance
    assert client is not None
    return channel, client, task


@pytest.fixture
def media_root(tmp_path: Any, monkeypatch: Any) -> Path:
    """Redirect the channel media dir to a temp directory."""
    from deeptutor.partners.config import paths as partner_paths

    media = tmp_path / "media"
    media.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(partner_paths, "get_media_dir", lambda name: media)
    return media


# ---------------------------------------------------------------------------
# Inbound message processing
# ---------------------------------------------------------------------------


class TestInboundProcessing:
    @pytest.mark.asyncio
    async def test_text_message_forwarded_to_bus(self) -> None:
        channel = _make_channel()
        frame = _text_frame(chattype="group")

        await channel._on_text_message(frame)

        assert channel.bus.publish_inbound.await_count == 1
        msg = channel.bus.publish_inbound.await_args.args[0]
        assert isinstance(msg, InboundMessage)
        assert msg.channel == "wecom"
        assert msg.sender_id == "user-1"
        assert msg.chat_id == "chat-1"
        assert msg.content == "hello"
        assert msg.metadata == {
            "message_id": "m1",
            "msg_type": "text",
            "chat_type": "group",
        }
        # The frame is cached so later replies can target this chat.
        assert channel._chat_frames["chat-1"] is frame

    @pytest.mark.asyncio
    async def test_sender_denied_when_allow_from_empty(self) -> None:
        channel = _make_channel(allow_from=[])

        await channel._on_text_message(_text_frame())

        assert channel.bus.publish_inbound.await_count == 0

    @pytest.mark.asyncio
    async def test_single_chat_without_chatid_uses_sender_userid(self) -> None:
        channel = _make_channel()
        frame = FakeFrame(
            body={"msgid": "m9", "from": {"userid": "user-9"}, "text": {"content": "dm"}}
        )

        await channel._on_text_message(frame)

        msg = channel.bus.publish_inbound.await_args.args[0]
        assert msg.sender_id == "user-9"
        assert msg.chat_id == "user-9"
        assert msg.metadata["chat_type"] == "single"

    @pytest.mark.asyncio
    async def test_non_dict_from_field_defaults_to_unknown_sender(self) -> None:
        channel = _make_channel()
        frame = _text_frame(msgid="m2", chatid="chat-2", from_info="user-string")

        await channel._on_text_message(frame)

        msg = channel.bus.publish_inbound.await_args.args[0]
        assert msg.sender_id == "unknown"
        assert msg.chat_id == "chat-2"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "frame",
        [
            FakeFrame(body=None),
            FakeFrame(body="corrupt-string"),
            "not-a-frame",
        ],
        ids=["none-body", "non-dict-body", "non-dict-frame"],
    )
    async def test_malformed_frames_are_ignored(self, frame: Any) -> None:
        channel = _make_channel()

        await channel._on_text_message(frame)

        assert channel.bus.publish_inbound.await_count == 0
        assert channel._chat_frames == {}

    @pytest.mark.asyncio
    async def test_empty_text_publishes_nothing(self) -> None:
        channel = _make_channel()
        frame = _text_frame(text="")

        await channel._on_text_message(frame)

        assert channel.bus.publish_inbound.await_count == 0

    @pytest.mark.asyncio
    async def test_unknown_msg_type_renders_placeholder(self) -> None:
        channel = _make_channel()
        frame = _text_frame()
        frame.body["msgid"] = "m-loc"

        await channel._process_message(frame, "location")

        msg = channel.bus.publish_inbound.await_args.args[0]
        assert msg.content == "[location]"
        assert msg.metadata["msg_type"] == "location"

    @pytest.mark.asyncio
    async def test_mixed_message_combines_text_and_placeholders(self) -> None:
        channel = _make_channel()
        frame = _text_frame()
        frame.body["mixed"] = {
            "item": [
                {"type": "text", "text": {"content": "see this"}},
                {"type": "image"},
                {"type": "sticker"},
            ]
        }

        await channel._on_mixed_message(frame)

        msg = channel.bus.publish_inbound.await_args.args[0]
        assert msg.content == "see this\n[image]\n[sticker]"
        assert msg.metadata["msg_type"] == "mixed"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("voice_body", "expected"),
        [
            ({"content": "transcribed words"}, "[voice] transcribed words"),
            ({}, "[voice]"),
        ],
        ids=["with-content", "placeholder-only"],
    )
    async def test_voice_message_variants(self, voice_body: dict[str, Any], expected: str) -> None:
        channel = _make_channel()
        frame = _text_frame()
        frame.body["voice"] = voice_body

        await channel._on_voice_message(frame)

        msg = channel.bus.publish_inbound.await_args.args[0]
        assert msg.content == expected


class TestInboundDeduplication:
    @pytest.mark.asyncio
    async def test_duplicate_msgid_suppressed(self) -> None:
        channel = _make_channel()

        await channel._on_text_message(_text_frame(msgid="dup"))
        await channel._on_text_message(_text_frame(msgid="dup"))

        assert channel.bus.publish_inbound.await_count == 1

    @pytest.mark.asyncio
    async def test_missing_msgid_falls_back_to_chatid_and_sendertime(self) -> None:
        channel = _make_channel()
        body = {
            "chatid": "chat-7",
            "sendertime": "1699000000",
            "from": {"userid": "user-7"},
            "text": {"content": "no msgid"},
        }

        await channel._on_text_message(FakeFrame(body=dict(body)))
        await channel._on_text_message(FakeFrame(body=dict(body)))

        assert channel.bus.publish_inbound.await_count == 1
        msg = channel.bus.publish_inbound.await_args.args[0]
        assert msg.metadata["message_id"] == "chat-7_1699000000"

    @pytest.mark.asyncio
    async def test_dedup_and_frame_caches_are_lru_bounded(self) -> None:
        channel = _make_channel()

        for i in range(1001):
            await channel._on_text_message(_text_frame(msgid=f"m{i}", chatid=f"chat{i}"))

        assert channel.bus.publish_inbound.await_count == 1001
        assert len(channel._processed_message_ids) == 1000
        assert "m0" not in channel._processed_message_ids
        assert "m1000" in channel._processed_message_ids
        assert len(channel._chat_frames) == 1000
        assert "chat0" not in channel._chat_frames
        assert "chat1000" in channel._chat_frames


# ---------------------------------------------------------------------------
# Media-bearing inbound messages
# ---------------------------------------------------------------------------


class TestInboundMedia:
    @pytest.mark.asyncio
    async def test_image_message_embeds_downloaded_source_path(self, media_root: Path) -> None:
        channel = _make_channel()
        client = FakeWSClient("bot-id", "bot-secret")
        client.download_results.append((b"image-bytes", "cam.png"))
        channel._client = client
        frame = _text_frame()
        frame.body["image"] = {"url": "https://media/img", "aeskey": "key"}

        await channel._on_image_message(frame)

        assert client.download_requests == [("https://media/img", "key")]
        msg = channel.bus.publish_inbound.await_args.args[0]
        saved = media_root / "cam.png"
        assert saved.read_bytes() == b"image-bytes"
        assert msg.content == f"[image: cam.png]\n[Image: source: {saved}]"
        assert msg.metadata["msg_type"] == "image"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "image_body",
        [
            {"url": "", "aeskey": ""},
            {"url": "https://media/img", "aeskey": "key"},
        ],
        ids=["missing-url-or-key", "download-returns-empty-data"],
    )
    async def test_image_message_marks_download_failed(self, image_body: dict[str, Any]) -> None:
        channel = _make_channel()
        client = FakeWSClient("bot-id", "bot-secret")
        client.download_results.append((b"", ""))
        channel._client = client
        frame = _text_frame()
        frame.body["image"] = image_body

        await channel._on_image_message(frame)

        msg = channel.bus.publish_inbound.await_args.args[0]
        assert msg.content == "[image: download failed]"

    @pytest.mark.asyncio
    async def test_file_message_success_and_failure_variants(self, media_root: Path) -> None:
        channel = _make_channel()
        client = FakeWSClient("bot-id", "bot-secret")
        client.download_results.append((b"pdf-bytes", "sdk-name.pdf"))
        client.download_results.append((b"", ""))
        channel._client = client

        ok_frame = _text_frame(msgid="f1", chatid="chat-f1")
        ok_frame.body["file"] = {"url": "https://media/ok", "aeskey": "k1", "name": "notes.txt"}
        await channel._on_file_message(ok_frame)

        fail_frame = _text_frame(msgid="f2", chatid="chat-f2")
        fail_frame.body["file"] = {"url": "https://media/bad", "aeskey": "k2", "name": "gone.pdf"}
        await channel._on_file_message(fail_frame)

        saved = media_root / "notes.txt"
        assert saved.read_bytes() == b"pdf-bytes"
        contents = [call.args[0].content for call in channel.bus.publish_inbound.await_args_list]
        assert contents == [
            f"[file: notes.txt]\n[File: source: {saved}]",
            "[file: gone.pdf: download failed]",
        ]

    @pytest.mark.asyncio
    async def test_file_message_without_url_marks_download_failed(self) -> None:
        channel = _make_channel()
        client = FakeWSClient("bot-id", "bot-secret")
        channel._client = client
        frame = _text_frame()
        frame.body["file"] = {"url": "", "aeskey": "", "name": "offline.doc"}

        await channel._on_file_message(frame)

        assert client.download_requests == []
        msg = channel.bus.publish_inbound.await_args.args[0]
        assert msg.content == "[file: offline.doc: download failed]"


class TestMediaDownload:
    @pytest.mark.asyncio
    async def test_writes_payload_under_media_dir(self, media_root: Path) -> None:
        channel = _make_channel()
        client = FakeWSClient("bot-id", "bot-secret")
        client.download_results.append((b"payload", "sdk.bin"))
        channel._client = client

        path = await channel._download_and_save_media("https://media/f", "key", "file", "a.bin")

        assert path is not None
        saved = Path(path)
        assert saved.parent == media_root
        assert saved.name == "a.bin"
        assert saved.read_bytes() == b"payload"

    @pytest.mark.asyncio
    async def test_collapses_filename_to_basename(self, media_root: Path) -> None:
        channel = _make_channel()
        client = FakeWSClient("bot-id", "bot-secret")
        client.download_results.append((b"payload", "ignored.bin"))
        channel._client = client

        path = await channel._download_and_save_media(
            "https://media/f", "key", "file", "../../outside.bin"
        )

        assert path is not None
        saved = Path(path)
        assert saved.parent == media_root
        assert saved.name == "outside.bin"
        assert saved.read_bytes() == b"payload"

    @pytest.mark.asyncio
    async def test_generates_name_when_sdk_and_caller_provide_none(self, media_root: Path) -> None:
        channel = _make_channel()
        client = FakeWSClient("bot-id", "bot-secret")
        client.download_results.append((b"payload", ""))
        channel._client = client
        url = "https://media/no-name"

        path = await channel._download_and_save_media(url, "key", "image")

        assert path is not None
        expected = media_root / f"image_{hash(url) % 100000}"
        assert Path(path) == expected
        assert expected.read_bytes() == b"payload"

    @pytest.mark.asyncio
    async def test_returns_none_on_empty_data(self, media_root: Path) -> None:
        channel = _make_channel()
        client = FakeWSClient("bot-id", "bot-secret")
        client.download_results.append((b"", "empty.png"))
        channel._client = client

        assert await channel._download_and_save_media("https://media/x", "key", "image") is None
        assert list(media_root.iterdir()) == []

    @pytest.mark.asyncio
    async def test_returns_none_on_transport_error(self, media_root: Path) -> None:
        channel = _make_channel()
        client = FakeWSClient("bot-id", "bot-secret")
        client.download_results.append(RuntimeError("download exploded"))
        channel._client = client

        assert await channel._download_and_save_media("https://media/x", "key", "image") is None
        assert list(media_root.iterdir()) == []


# ---------------------------------------------------------------------------
# Outbound delivery
# ---------------------------------------------------------------------------


def _outbound(content: str, chat_id: str = "chat-1") -> OutboundMessage:
    return OutboundMessage(channel="wecom", chat_id=chat_id, content=content)


class TestOutboundSend:
    @pytest.mark.asyncio
    async def test_replies_via_stream_using_cached_frame(self) -> None:
        channel = _make_channel()
        client = FakeWSClient("bot-id", "bot-secret")
        channel._client = client
        channel._generate_req_id = lambda prefix: f"{prefix}-gen"
        frame = _text_frame()
        await channel._on_text_message(frame)

        await channel.send(_outbound("pong"))

        assert client.stream_replies == [
            {"frame": frame, "stream_id": "stream-gen", "content": "pong", "finish": True}
        ]

    @pytest.mark.asyncio
    async def test_noop_without_client(self) -> None:
        channel = _make_channel()

        await channel.send(_outbound("ping"))  # must not raise

        assert channel.bus.publish_inbound.await_count == 0

    @pytest.mark.asyncio
    async def test_noop_without_cached_frame(self) -> None:
        channel = _make_channel()
        client = FakeWSClient("bot-id", "bot-secret")
        channel._client = client
        channel._generate_req_id = lambda prefix: f"{prefix}-gen"

        await channel.send(_outbound("no frame for this chat"))

        assert client.stream_replies == []

    @pytest.mark.asyncio
    async def test_noop_for_blank_content(self) -> None:
        channel = _make_channel()
        client = FakeWSClient("bot-id", "bot-secret")
        channel._client = client
        channel._generate_req_id = lambda prefix: f"{prefix}-gen"
        await channel._on_text_message(_text_frame())

        await channel.send(_outbound("   \n  "))

        assert client.stream_replies == []

    @pytest.mark.asyncio
    async def test_noop_without_request_id_generator(self) -> None:
        channel = _make_channel()
        client = FakeWSClient("bot-id", "bot-secret")
        channel._client = client
        channel._generate_req_id = None
        await channel._on_text_message(_text_frame())

        await channel.send(_outbound("no generator"))

        assert client.stream_replies == []

    @pytest.mark.asyncio
    async def test_propagates_stream_failure_for_manager_retry(self) -> None:
        channel = _make_channel()
        client = FakeWSClient("bot-id", "bot-secret")
        client.fail_stream = RuntimeError("stream send failed")
        channel._client = client
        channel._generate_req_id = lambda prefix: f"{prefix}-gen"
        await channel._on_text_message(_text_frame())

        with pytest.raises(RuntimeError, match="stream send failed"):
            await channel.send(_outbound("boom"))


# ---------------------------------------------------------------------------
# Setup-state machine and lifecycle
# ---------------------------------------------------------------------------


class TestSetupStateMachine:
    @pytest.mark.asyncio
    async def test_start_reports_unavailable_without_sdk(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(wecom, "WECOM_AVAILABLE", False)
        channel = _make_channel()

        await asyncio.wait_for(channel.start(), timeout=1)  # returns, does not listen

        state = channel.setup_state
        assert state["status"] == "unavailable"
        assert "not installed" in state["message"]
        assert channel._client is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "overrides",
        [{"bot_id": ""}, {"secret": ""}],
        ids=["missing-bot-id", "missing-secret"],
    )
    async def test_start_requires_bot_credentials(
        self, monkeypatch: Any, overrides: dict[str, Any]
    ) -> None:
        _install_fake_sdk(monkeypatch)
        channel = _make_channel(**overrides)

        await asyncio.wait_for(channel.start(), timeout=1)

        state = channel.setup_state
        assert state["status"] == "action_required"
        assert "Required fields are missing" in state["message"]
        assert channel._client is None

    @pytest.mark.asyncio
    async def test_connection_lifecycle_state_transitions(self) -> None:
        channel = _make_channel()

        await channel._on_connected()
        assert channel.setup_state == {"status": "connecting"}

        await channel._on_authenticated()
        assert channel.setup_state == {"status": "connected"}

        await channel._on_disconnected(FakeFrame(body="server closed"))
        assert channel.setup_state == {"status": "connecting"}

        await channel._on_error(FakeFrame(body={"code": 500}))
        state = channel.setup_state
        assert state["status"] == "error"
        assert "retry" in state["message"]

        assert channel.setup_revision == 4

    @pytest.mark.asyncio
    async def test_start_registers_sdk_event_handlers(self, monkeypatch: Any) -> None:
        channel, client, task = await _start_channel(monkeypatch)
        try:
            assert set(client.handlers) == {
                "connected",
                "authenticated",
                "disconnected",
                "error",
                "message.text",
                "message.image",
                "message.voice",
                "message.file",
                "message.mixed",
                "event.enter_chat",
            }
            for handler in client.handlers.values():
                assert asyncio.iscoroutinefunction(handler)
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    @pytest.mark.asyncio
    async def test_stop_ends_run_loop_and_disconnects(self, monkeypatch: Any) -> None:
        channel, client, task = await _start_channel(monkeypatch)
        assert channel.is_running

        await channel.stop()
        await asyncio.wait_for(task, timeout=2)  # run loop must exit promptly

        assert channel.is_running is False
        assert client.disconnect_calls == 1

    @pytest.mark.asyncio
    async def test_stop_without_client_is_safe(self) -> None:
        channel = _make_channel()
        channel._running = True

        await asyncio.wait_for(channel.stop(), timeout=1)

        assert channel.is_running is False


# ---------------------------------------------------------------------------
# enter_chat welcome flow
# ---------------------------------------------------------------------------


class TestEnterChat:
    @pytest.mark.asyncio
    async def test_replies_with_configured_welcome(self) -> None:
        channel = _make_channel(welcome_message="Hi there!")
        client = FakeWSClient("bot-id", "bot-secret")
        channel._client = client
        frame = FakeFrame(body={"chatid": "chat-1"})

        await channel._on_enter_chat(frame)

        assert client.welcome_replies == [
            (
                frame,
                {"msgtype": "text", "text": {"content": "Hi there!"}},
            )
        ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("config", "body"),
        [
            ({"welcome_message": ""}, {"chatid": "chat-1"}),
            ({"welcome_message": "Hi"}, {}),
        ],
        ids=["no-welcome-configured", "no-chatid-in-event"],
    )
    async def test_noop_without_welcome_or_chatid(
        self, config: dict[str, Any], body: dict[str, Any]
    ) -> None:
        channel = _make_channel(**config)
        client = FakeWSClient("bot-id", "bot-secret")
        channel._client = client

        await channel._on_enter_chat(FakeFrame(body=body))

        assert client.welcome_replies == []

    @pytest.mark.asyncio
    async def test_swallows_welcome_reply_failure(self) -> None:
        channel = _make_channel(welcome_message="Hi")
        client = FakeWSClient("bot-id", "bot-secret")
        client.fail_welcome = RuntimeError("welcome send failed")
        channel._client = client

        await channel._on_enter_chat(FakeFrame(body={"chatid": "chat-1"}))  # must not raise

        assert client.welcome_replies == []
