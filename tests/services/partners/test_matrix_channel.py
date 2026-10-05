"""Unit tests for the Matrix (Element) channel implementation.

Covers inbound payload parsing, thread/session mapping, media attachment
download/upload error paths, group policy gating, and sync-loop reconnect /
graceful stop branches. All Matrix client I/O is faked; no network access.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from deeptutor.partners.bus.events import OutboundMessage
from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels import matrix as matrix_mod
from deeptutor.partners.channels.matrix import (
    MatrixChannel,
    MatrixConfig,
    _build_matrix_text_content,
    _filter_matrix_html_attribute,
    _render_markdown_html,
)
from deeptutor.partners.config import paths as partner_paths

BOT = "@bot:example.org"


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_channel(**overrides) -> MatrixChannel:
    defaults = {
        "enabled": True,
        "user_id": BOT,
        "access_token": "tok",
        "device_id": "DEV",
        "allow_from": ["*"],
    }
    defaults.update(overrides)
    config = MatrixConfig.model_validate(defaults)
    bus = MagicMock(spec=MessageBus)
    bus.publish_inbound = AsyncMock()
    return MatrixChannel(config, bus)


def _fake_client(**overrides) -> MagicMock:
    client = MagicMock(name="nio_client")
    client.room_send = AsyncMock(return_value=SimpleNamespace())
    client.room_typing = AsyncMock(return_value=SimpleNamespace())
    client.download = AsyncMock(return_value=SimpleNamespace(body=b"media-bytes"))
    client.upload = AsyncMock(return_value=SimpleNamespace(content_uri="mxc://hs/abc"))
    client.join = AsyncMock(return_value=SimpleNamespace())
    client.close = AsyncMock()
    client.stop_sync_forever = MagicMock()
    client.sync_forever = AsyncMock(return_value=SimpleNamespace())
    client.rooms = {}
    for key, value in overrides.items():
        setattr(client, key, value)
    return client


def _room(room_id: str = "!room:example.org", member_count: int = 2, **extra):
    room = SimpleNamespace(
        room_id=room_id,
        display_name="Test Room",
        member_count=member_count,
        encrypted=False,
    )
    for key, value in extra.items():
        setattr(room, key, value)
    return room


def _text_event(sender: str = "@alice:example.org", body: str = "hello", **extra):
    event = SimpleNamespace(
        sender=sender,
        event_id="$evt-text-1",
        body=body,
        source={"content": {"msgtype": "m.text"}},
    )
    for key, value in extra.items():
        setattr(event, key, value)
    return event


def _media_event(sender: str = "@alice:example.org", **extra):
    event = SimpleNamespace(
        sender=sender,
        event_id="$evt-media-1",
        body="report.txt",
        url="mxc://example.org/AbCdEf",
        key=None,
        hashes=None,
        iv=None,
        mimetype=None,
        source={
            "content": {
                "msgtype": "m.file",
                "info": {"size": 11, "mimetype": "text/plain"},
            }
        },
    )
    for key, value in extra.items():
        setattr(event, key, value)
    return event


@pytest.fixture
def media_dir(tmp_path, monkeypatch):
    target = tmp_path / "media"
    target.mkdir()
    monkeypatch.setattr(partner_paths, "get_media_dir", lambda channel=None: target)
    monkeypatch.setattr(partner_paths, "get_partner_media_dir", lambda pid, channel=None: target)
    return target


# ── Markdown / HTML parsing ──────────────────────────────────────────────


class TestMarkdownParsing:
    def test_plain_text_renders_no_html(self):
        assert _render_markdown_html("hello world") is None

    def test_markdown_renders_formatted_body(self):
        html = _render_markdown_html("**bold** and *italic*")
        assert html is not None
        assert "<strong>bold</strong>" in html
        assert "<em>italic</em>" in html

    def test_markdown_renders_table(self):
        html = _render_markdown_html("| a | b |\n|---|---|\n| 1 | 2 |")
        assert html is not None
        assert "<table>" in html and "<td>1</td>" in html

    def test_sanitizer_drops_disallowed_tags_and_links(self):
        html = _render_markdown_html("hello <script>bad()</script> [x](javascript:alert(1))")
        assert html is not None
        assert "<script" not in html
        assert "href=" not in html

    def test_attribute_filter_href_schemes(self):
        assert (
            _filter_matrix_html_attribute("a", "href", "https://example.org")
            == "https://example.org"
        )
        assert _filter_matrix_html_attribute("a", "href", "matrix:roomid") == "matrix:roomid"
        assert _filter_matrix_html_attribute("a", "href", "mailto:a@b.c") == "mailto:a@b.c"
        assert _filter_matrix_html_attribute("a", "href", "javascript:void(0)") is None
        assert _filter_matrix_html_attribute("a", "href", "data:text/plain,hi") is None

    def test_attribute_filter_img_src_requires_mxc(self):
        assert _filter_matrix_html_attribute("img", "src", "mxc://hs/id") == "mxc://hs/id"
        assert _filter_matrix_html_attribute("img", "src", "https://hs/id") is None

    def test_attribute_filter_code_class_language_only(self):
        assert (
            _filter_matrix_html_attribute("code", "class", "language-python") == "language-python"
        )
        assert (
            _filter_matrix_html_attribute("code", "class", "language-python highlight")
            == "language-python"
        )
        assert _filter_matrix_html_attribute("code", "class", "language-_hidden") is None
        assert _filter_matrix_html_attribute("code", "class", "highlight") is None
        assert _filter_matrix_html_attribute("td", "class", "anything") == "anything"

    def test_build_text_content_plain_vs_formatted(self):
        plain = _build_matrix_text_content("just text")
        assert plain["msgtype"] == "m.text"
        assert plain["body"] == "just text"
        assert "format" not in plain

        rich = _build_matrix_text_content("## Heading\n\nbody")
        assert rich["format"] == matrix_mod.MATRIX_HTML_FORMAT
        assert "formatted_body" in rich
        assert "<h2>" in rich["formatted_body"]

    def test_markdown_render_error_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            matrix_mod, "MATRIX_MARKDOWN", lambda _text: (_ for _ in ()).throw(RuntimeError("x"))
        )
        assert _render_markdown_html("**bold**") is None


# ── Thread / session mapping ─────────────────────────────────────────────


class TestThreadSessionMapping:
    def test_threaded_event_maps_to_session_metadata(self):
        event = _text_event(
            source={
                "content": {
                    "m.relates_to": {"rel_type": "m.thread", "event_id": "$root-1"},
                }
            },
            event_id="$reply-9",
        )
        channel = _make_channel()
        meta = channel._thread_metadata(event)
        assert meta == {
            "thread_root_event_id": "$root-1",
            "thread_reply_to_event_id": "$reply-9",
        }

    def test_non_thread_reply_has_no_thread_metadata(self):
        channel = _make_channel()
        event = _text_event(
            source={"content": {"m.relates_to": {"rel_type": "m.in_reply_to", "event_id": "$x"}}}
        )
        assert channel._thread_metadata(event) is None
        event_no_source = _text_event(source=None)
        assert channel._thread_metadata(event_no_source) is None

    def test_base_metadata_carries_room_and_event(self):
        channel = _make_channel()
        meta = channel._base_metadata(_room(), _text_event())
        assert meta["room"] == "Test Room"
        assert meta["event_id"] == "$evt-text-1"

    def test_build_thread_relates_to_roundtrip(self):
        build = MatrixChannel._build_thread_relates_to
        relates = build({"thread_root_event_id": "$root", "thread_reply_to_event_id": "$reply"})
        assert relates == {
            "rel_type": "m.thread",
            "event_id": "$root",
            "m.in_reply_to": {"event_id": "$reply"},
            "is_falling_back": True,
        }
        # Falls back to event_id when the reply marker is missing.
        relates = build({"thread_root_event_id": "$root", "event_id": "$e"})
        assert relates["m.in_reply_to"] == {"event_id": "$e"}

    def test_build_thread_relates_to_rejects_incomplete(self):
        build = MatrixChannel._build_thread_relates_to
        assert build(None) is None
        assert build({}) is None
        assert build({"thread_root_event_id": ""}) is None
        assert build({"thread_root_event_id": "$root"}) is None


# ── Media event parsing ──────────────────────────────────────────────────


class TestMediaEventParsing:
    def test_attachment_type_mapping(self):
        channel = _make_channel()
        assert channel._event_attachment_type(_media_event()) == "file"
        event = _media_event(source={"content": {"msgtype": "m.image"}})
        assert channel._event_attachment_type(event) == "image"
        event = _media_event(source={"content": {"msgtype": "m.audio"}})
        assert channel._event_attachment_type(event) == "audio"
        event = _media_event(source={"content": {"msgtype": "m.unknown"}})
        assert channel._event_attachment_type(event) == "file"
        event = _media_event(source="not-a-dict")
        assert channel._event_attachment_type(event) == "file"

    def test_event_filename_fallbacks(self):
        channel = _make_channel()
        assert channel._event_filename(_media_event(), "file") == "report.txt"
        assert channel._event_filename(_media_event(body="   "), "file") == "attachment"
        assert channel._event_filename(_media_event(body="   "), "image") == "image"

    def test_declared_size_and_mime_parsing(self):
        channel = _make_channel()
        assert channel._event_declared_size_bytes(_media_event()) == 11
        assert channel._event_declared_size_bytes(_media_event(source={"content": {}})) is None
        assert (
            channel._event_declared_size_bytes(
                _media_event(source={"content": {"info": {"size": -1}}})
            )
            is None
        )
        assert channel._event_mime(_media_event()) == "text/plain"
        assert channel._event_mime(_media_event(source={"content": {}})) is None
        assert (
            channel._event_mime(_media_event(source={"content": {}}, mimetype="image/png"))
            == "image/png"
        )

    def test_encrypted_media_event_detection(self):
        encrypted = _media_event(
            key={"k": "secret-key-material"}, hashes={"sha256": "digest"}, iv="initial-vector"
        )
        assert MatrixChannel._is_encrypted_media_event(encrypted) is True
        assert MatrixChannel._is_encrypted_media_event(_media_event()) is False
        assert MatrixChannel._is_encrypted_media_event(_media_event(key={"k": "x"})) is False


class TestAttachmentPath:
    def test_extension_guessed_from_mime(self):
        channel = _make_channel()
        path = channel._build_attachment_path(
            _media_event(body="noext"), "file", "noext", "text/csv"
        )
        assert path.suffix == ".csv"
        assert path.name.startswith("evt")

    def test_stem_and_suffix_truncated(self):
        channel = _make_channel()
        long_name = "n" * 200 + ".txt"
        path = channel._build_attachment_path(_media_event(), "file", long_name, None)
        name_stem = path.stem.split("_", 1)[1]
        assert len(name_stem) <= 72
        assert len(path.suffix) <= 16
        assert path.suffix == ".txt"

    def test_event_id_prefix_sanitized(self):
        channel = _make_channel()
        event = _media_event(event_id="$" + "a" * 40 + "/evil")
        path = channel._build_attachment_path(event, "file", "f.txt", None)
        assert "/" not in path.name
        assert path.name.startswith("a" * 24)


# ── Group policy / access gating ─────────────────────────────────────────


class TestPolicyGating:
    def test_direct_room_bypasses_group_policy(self):
        channel = _make_channel(group_policy="allowlist", group_allow_from=[])
        assert channel._should_process_message(_room(member_count=2), _text_event()) is True

    def test_open_policy_allows_group_rooms(self):
        channel = _make_channel(group_policy="open")
        assert channel._should_process_message(_room(member_count=5), _text_event()) is True

    def test_allowlist_policy_filters_rooms(self):
        channel = _make_channel(group_policy="allowlist", group_allow_from=["!allowed:example.org"])
        assert (
            channel._should_process_message(
                _room(room_id="!allowed:example.org", member_count=5), _text_event()
            )
            is True
        )
        assert (
            channel._should_process_message(
                _room(room_id="!other:example.org", member_count=5), _text_event()
            )
            is False
        )

    def test_mention_policy_requires_bot_mention(self):
        channel = _make_channel(group_policy="mention")
        plain = _room(member_count=5)
        assert channel._should_process_message(plain, _text_event()) is False
        mentioned = _text_event(source={"content": {"m.mentions": {"user_ids": [BOT]}}})
        assert channel._should_process_message(plain, mentioned) is True

    def test_denied_sender_rejected_everywhere(self):
        channel = _make_channel(allow_from=["@bob:example.org"])
        assert channel._should_process_message(_room(), _text_event()) is False

    def test_bot_mention_variants(self):
        channel = _make_channel()
        assert channel._is_bot_mentioned(_text_event()) is False
        assert channel._is_bot_mentioned(_text_event(source=None)) is False
        user_mention = _text_event(source={"content": {"m.mentions": {"user_ids": [BOT]}}})
        assert channel._is_bot_mentioned(user_mention) is True
        room_mention = _text_event(source={"content": {"m.mentions": {"room": True}}})
        assert channel._is_bot_mentioned(room_mention) is False
        permissive = _make_channel(allow_room_mentions=True)
        assert permissive._is_bot_mentioned(room_mention) is True

    def test_invite_joined_only_for_allowed_sender(self):
        channel = _make_channel(allow_from=["@alice:example.org"])
        channel.client = _fake_client()
        asyncio.run(channel._on_room_invite(_room(), SimpleNamespace(sender="@alice:example.org")))
        channel.client.join.assert_awaited_once_with("!room:example.org")

        channel.client.join.reset_mock()
        asyncio.run(
            channel._on_room_invite(_room(), SimpleNamespace(sender="@mallory:example.org"))
        )
        channel.client.join.assert_not_awaited()


# ── Inbound media: error paths and happy path ────────────────────────────


class TestInboundMedia:
    def test_invalid_mxc_url_returns_download_failed_marker(self, media_dir):
        channel = _make_channel()
        channel.client = _fake_client()
        event = _media_event(url="https://not-mxc.example.org/file")
        attachment, marker = asyncio.run(channel._fetch_media_attachment(_room(), event))
        assert attachment is None
        assert marker == "[attachment: report.txt - download failed]"
        channel.client.download.assert_not_awaited()

    def test_declared_size_over_limit_rejected_before_download(self, media_dir):
        channel = _make_channel(max_media_bytes=5)
        channel.client = _fake_client()
        attachment, marker = asyncio.run(channel._fetch_media_attachment(_room(), _media_event()))
        assert attachment is None
        assert "too large" in marker
        channel.client.download.assert_not_awaited()

    def test_download_error_returns_failed_marker(self, media_dir):
        from nio import DownloadError

        channel = _make_channel()
        channel.client = _fake_client(download=AsyncMock(return_value=DownloadError("nope")))
        attachment, marker = asyncio.run(channel._fetch_media_attachment(_room(), _media_event()))
        assert attachment is None
        assert "download failed" in marker

    def test_oversized_payload_rejected_after_download(self, media_dir):
        channel = _make_channel(max_media_bytes=5)
        channel.client = _fake_client(
            download=AsyncMock(return_value=SimpleNamespace(body=b"0123456789"))
        )
        event = _media_event(source={"content": {"msgtype": "m.file"}})  # no declared size
        attachment, marker = asyncio.run(channel._fetch_media_attachment(_room(), event))
        assert attachment is None
        assert "too large" in marker

    def test_write_failure_returns_failed_marker(self, media_dir, monkeypatch):
        channel = _make_channel()
        channel.client = _fake_client()

        def boom(_self, _data):
            raise OSError("disk full")

        monkeypatch.setattr(Path, "write_bytes", boom)
        attachment, marker = asyncio.run(channel._fetch_media_attachment(_room(), _media_event()))
        assert attachment is None
        assert "download failed" in marker

    def test_missing_decrypt_dependencies_returns_failed_marker(self, media_dir, monkeypatch):
        channel = _make_channel()
        channel.client = _fake_client()
        monkeypatch.setattr(matrix_mod, "decrypt_attachment", None)
        event = _media_event(key={"k": "k"}, hashes={"sha256": "h"}, iv="i")
        attachment, marker = asyncio.run(channel._fetch_media_attachment(_room(), event))
        assert attachment is None
        assert "download failed" in marker

    def test_decrypt_failure_returns_failed_marker(self, media_dir, monkeypatch):
        channel = _make_channel()
        channel.client = _fake_client()

        def bad_decrypt(*_args):
            raise ValueError("bad mac")

        monkeypatch.setattr(matrix_mod, "decrypt_attachment", bad_decrypt)
        event = _media_event(key={"k": "k"}, hashes={"sha256": "h"}, iv="i")
        attachment, marker = asyncio.run(channel._fetch_media_attachment(_room(), event))
        assert attachment is None
        assert "download failed" in marker

    def test_encrypted_media_decrypts_and_persists(self, media_dir, monkeypatch):
        channel = _make_channel()
        channel.client = _fake_client()
        monkeypatch.setattr(matrix_mod, "decrypt_attachment", lambda _c, _k, _h, _i: b"plain")
        event = _media_event(key={"k": "k"}, hashes={"sha256": "h"}, iv="i")
        attachment, marker = asyncio.run(channel._fetch_media_attachment(_room(), event))
        assert attachment is not None
        assert attachment["encrypted"] is True
        assert Path(attachment["path"]).read_bytes() == b"plain"
        assert marker == f"[attachment: {attachment['path']}]"

    def test_media_download_persists_file_and_marker(self, media_dir):
        channel = _make_channel()
        channel.client = _fake_client()
        attachment, marker = asyncio.run(channel._fetch_media_attachment(_room(), _media_event()))
        assert attachment is not None
        assert attachment["type"] == "file"
        assert attachment["mime"] == "text/plain"
        assert attachment["filename"] == "report.txt"
        assert attachment["size_bytes"] == 11
        assert attachment["event_id"] == "$evt-media-1"
        assert attachment["encrypted"] is False
        assert Path(attachment["path"]).read_bytes() == b"media-bytes"
        assert marker.startswith("[attachment: ")

    def test_media_message_routes_attachment_to_bus(self, media_dir):
        channel = _make_channel()
        channel.client = _fake_client()
        room = _room()
        asyncio.run(channel._on_media_message(room, _media_event()))
        channel.bus.publish_inbound.assert_awaited_once()
        msg = channel.bus.publish_inbound.await_args.args[0]
        assert msg.channel == "matrix"
        assert msg.chat_id == room.room_id
        assert msg.media and msg.media[0].endswith("report.txt")
        assert msg.metadata["attachments"][0]["type"] == "file"

    def test_audio_attachment_prefers_transcription(self, media_dir):
        channel = _make_channel()
        channel.client = _fake_client()
        channel.transcribe_audio = AsyncMock(return_value="hello there")
        event = _media_event(
            body="voice.ogg",
            source={"content": {"msgtype": "m.audio", "info": {"mimetype": "audio/ogg"}}},
        )
        asyncio.run(channel._on_media_message(_room(), event))
        channel.transcribe_audio.assert_awaited_once()
        msg = channel.bus.publish_inbound.await_args.args[0]
        assert "[transcription: hello there]" in msg.content

    def test_media_handler_clears_typing_on_bus_failure(self, media_dir):
        channel = _make_channel()
        channel.client = _fake_client()
        channel.bus.publish_inbound = AsyncMock(side_effect=RuntimeError("bus down"))
        with pytest.raises(RuntimeError):
            asyncio.run(channel._on_media_message(_room(), _media_event()))
        clear_calls = [
            c
            for c in channel.client.room_typing.await_args_list
            if c.kwargs.get("typing_state") is False
        ]
        assert clear_calls


# ── Inbound text ─────────────────────────────────────────────────────────


class TestInboundText:
    def test_text_message_publishes_inbound_with_metadata(self):
        channel = _make_channel()
        channel.client = _fake_client()
        room = _room()
        asyncio.run(channel._on_message(room, _text_event()))
        channel.bus.publish_inbound.assert_awaited_once()
        msg = channel.bus.publish_inbound.await_args.args[0]
        assert msg.content == "hello"
        assert msg.sender_id == "@alice:example.org"
        assert msg.metadata["room"] == "Test Room"

    def test_bot_own_messages_ignored(self):
        channel = _make_channel()
        channel.client = _fake_client()
        asyncio.run(channel._on_message(_room(), _text_event(sender=BOT)))
        channel.bus.publish_inbound.assert_not_awaited()

    def test_text_handler_clears_typing_on_failure(self):
        channel = _make_channel()
        channel.client = _fake_client()
        channel.bus.publish_inbound = AsyncMock(side_effect=RuntimeError("boom"))
        with pytest.raises(RuntimeError):
            asyncio.run(channel._on_message(_room(), _text_event()))
        clear_calls = [
            c
            for c in channel.client.room_typing.await_args_list
            if c.kwargs.get("typing_state") is False
        ]
        assert clear_calls


# ── Outbound send: error paths ───────────────────────────────────────────


class TestOutboundSend:
    def _msg(self, **overrides) -> OutboundMessage:
        defaults = {"channel": "matrix", "chat_id": "!room:example.org", "content": "reply"}
        defaults.update(overrides)
        return OutboundMessage(**defaults)

    def test_send_without_client_is_noop(self):
        channel = _make_channel()
        asyncio.run(channel.send(self._msg()))
        assert not channel._typing_tasks

    def test_send_plain_text_uses_room_send(self):
        channel = _make_channel()
        channel.client = _fake_client()
        asyncio.run(channel.send(self._msg(content="hi")))
        channel.client.room_send.assert_awaited_once()
        kwargs = channel.client.room_send.await_args.kwargs
        assert kwargs["room_id"] == "!room:example.org"
        content = kwargs["content"]
        assert content["msgtype"] == "m.text"
        assert content["body"] == "hi"
        assert "format" not in content
        channel.client.room_typing.assert_awaited_once()

    def test_send_progress_keeps_typing_active(self):
        channel = _make_channel()
        channel.client = _fake_client()
        asyncio.run(channel.send(self._msg(metadata={"_progress": True})))
        channel.client.room_send.assert_awaited_once()
        typing_off = [
            c
            for c in channel.client.room_typing.await_args_list
            if c.kwargs.get("typing_state") is False
        ]
        assert not typing_off

    def test_thread_metadata_restored_in_outbound(self):
        channel = _make_channel()
        channel.client = _fake_client()
        asyncio.run(
            channel.send(
                self._msg(metadata={"thread_root_event_id": "$root", "event_id": "$reply"})
            )
        )
        content = channel.client.room_send.await_args.kwargs["content"]
        assert content["m.relates_to"]["rel_type"] == "m.thread"
        assert content["m.relates_to"]["event_id"] == "$root"

    def test_media_upload_error_appends_marker(self, tmp_path):
        from nio import UploadError

        channel = _make_channel()
        channel.client = _fake_client(upload=AsyncMock(return_value=UploadError("no space")))
        target = tmp_path / "doc.pdf"
        target.write_bytes(b"%PDF-1.4")
        asyncio.run(channel.send(self._msg(content="see file", media=[str(target)])))
        content = channel.client.room_send.await_args.kwargs["content"]
        assert content["body"].startswith("see file")
        assert "[attachment: doc.pdf - upload failed]" in content["body"]

    def test_media_upload_success_sends_media_message(self, tmp_path):
        channel = _make_channel()
        channel.client = _fake_client()
        target = tmp_path / "pic.png"
        target.write_bytes(b"\x89PNG")
        asyncio.run(channel.send(self._msg(content="", media=[str(target)])))
        channel.client.room_send.assert_awaited_once()
        content = channel.client.room_send.await_args.kwargs["content"]
        assert content["msgtype"] == "m.image"
        assert content["url"] == "mxc://hs/abc"
        assert content["info"]["mimetype"] == "image/png"

    def test_media_over_local_limit_appends_too_large_marker(self, tmp_path):
        channel = _make_channel(max_media_bytes=4)
        channel.client = _fake_client()
        target = tmp_path / "big.bin"
        target.write_bytes(b"x" * 100)
        asyncio.run(channel.send(self._msg(content="", media=[str(target)])))
        content = channel.client.room_send.await_args.kwargs["content"]
        assert "[attachment: big.bin - too large]" in content["body"]

    def test_media_outside_workspace_rejected(self, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        target = outside / "secret.txt"
        target.write_bytes(b"data")
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        channel = _make_channel()
        channel._restrict_to_workspace = True
        channel._workspace = workspace
        channel.client = _fake_client()
        asyncio.run(channel.send(self._msg(content="", media=[str(target)])))
        content = channel.client.room_send.await_args.kwargs["content"]
        assert "[attachment: secret.txt - upload failed]" in content["body"]

    def test_duplicate_media_paths_sent_once(self, tmp_path):
        channel = _make_channel()
        channel.client = _fake_client()
        target = tmp_path / "same.txt"
        target.write_bytes(b"same")
        asyncio.run(channel.send(self._msg(content="", media=[str(target), str(target), "  "])))
        channel.client.upload.assert_awaited_once()

    def test_outbound_candidates_dedupe_and_filter(self):
        channel = _make_channel()
        raw = ["", "   ", 42, "a.txt", "./a.txt"]
        candidates = channel._collect_outbound_media_candidates(raw)  # type: ignore[arg-type]
        assert len(candidates) == 1

    def test_server_upload_limit_lower_bound_applies(self, tmp_path):
        channel = _make_channel(max_media_bytes=10_000_000)
        channel.client = _fake_client(
            content_repository_config=AsyncMock(return_value=SimpleNamespace(upload_size=8))
        )
        target = tmp_path / "f.txt"
        target.write_bytes(b"x" * 50)
        asyncio.run(channel.send(self._msg(content="", media=[str(target)])))
        content = channel.client.room_send.await_args.kwargs["content"]
        assert "[attachment: f.txt - too large]" in content["body"]

    def test_server_limit_query_failure_falls_back_to_local(self):
        channel = _make_channel(max_media_bytes=123)
        channel.client = _fake_client(
            content_repository_config=AsyncMock(side_effect=RuntimeError("offline"))
        )
        assert asyncio.run(channel._effective_media_limit_bytes()) == 123

    def test_upload_limit_resolved_once_per_lifecycle(self):
        config_query = AsyncMock(return_value=SimpleNamespace(upload_size=999))
        channel = _make_channel()
        channel.client = _fake_client(content_repository_config=config_query)
        assert asyncio.run(channel._resolve_server_upload_limit_bytes()) == 999
        assert asyncio.run(channel._resolve_server_upload_limit_bytes()) == 999
        config_query.assert_awaited_once()


class TestOutboundAttachmentContent:
    def test_msgtype_mapping_by_mime_prefix(self):
        build = MatrixChannel._build_outbound_attachment_content
        assert (
            build(filename="a.png", mime="image/png", size_bytes=1, mxc_url="mxc://x")["msgtype"]
            == "m.image"
        )
        assert (
            build(filename="a.ogg", mime="audio/ogg", size_bytes=1, mxc_url="mxc://x")["msgtype"]
            == "m.audio"
        )
        assert (
            build(filename="a.mp4", mime="video/mp4", size_bytes=1, mxc_url="mxc://x")["msgtype"]
            == "m.video"
        )
        assert (
            build(filename="a.pdf", mime="application/pdf", size_bytes=1, mxc_url="mxc://x")[
                "msgtype"
            ]
            == "m.file"
        )

    def test_encryption_info_moves_url_into_file(self):
        build = MatrixChannel._build_outbound_attachment_content
        plain = build(filename="f", mime="text/plain", size_bytes=1, mxc_url="mxc://x")
        assert plain["url"] == "mxc://x"
        enc = build(
            filename="f",
            mime="text/plain",
            size_bytes=1,
            mxc_url="mxc://x",
            encryption_info={"v": "v2", "key": "k"},
        )
        assert "url" not in enc
        assert enc["file"] == {"v": "v2", "key": "k", "url": "mxc://x"}


# ── Sync loop: reconnect and stop branches ───────────────────────────────


class TestSyncLoopLifecycle:
    async def _run_with_sleep_counter(self, monkeypatch):
        sleeps: list[float] = []

        async def fake_sleep(seconds):
            sleeps.append(seconds)

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)
        return sleeps

    @pytest.mark.asyncio
    async def test_sync_loop_retries_after_exception(self, monkeypatch):
        sleeps = await self._run_with_sleep_counter(monkeypatch)
        channel = _make_channel()
        channel._running = True
        calls = {"n": 0}

        async def flaky_sync(*_args, **_kwargs):
            calls["n"] += 1
            if calls["n"] >= 3:
                channel._running = False
            raise RuntimeError("sync failed")

        channel.client = _fake_client(sync_forever=AsyncMock(side_effect=flaky_sync))
        await channel._sync_loop()
        assert calls["n"] == 3
        assert sleeps == [2, 2, 2]

    @pytest.mark.asyncio
    async def test_sync_loop_exits_on_cancellation(self, monkeypatch):
        sleeps = await self._run_with_sleep_counter(monkeypatch)
        channel = _make_channel()
        channel._running = True

        async def cancelled_sync(*_args, **_kwargs):
            raise asyncio.CancelledError()

        channel.client = _fake_client(sync_forever=AsyncMock(side_effect=cancelled_sync))
        await channel._sync_loop()
        assert sleeps == []

    @pytest.mark.asyncio
    async def test_stop_cancels_hung_sync_task_after_grace(self):
        channel = _make_channel(sync_stop_grace_seconds=0)
        channel._running = True
        channel.client = _fake_client()

        async def hang():
            await asyncio.sleep(3600)

        channel._sync_task = asyncio.create_task(hang())
        await asyncio.sleep(0)
        await channel.stop()
        assert channel._sync_task.cancelled()
        channel.client.stop_sync_forever.assert_called_once()
        channel.client.close.assert_awaited_once()
        assert channel._running is False

    @pytest.mark.asyncio
    async def test_stop_joins_finished_sync_task(self, monkeypatch):
        sleeps = await self._run_with_sleep_counter(monkeypatch)
        channel = _make_channel()
        channel._running = True
        channel.client = _fake_client()
        done = asyncio.Event()

        async def finishing():
            await asyncio.sleep(0)
            done.set()

        channel._sync_task = asyncio.create_task(finishing())
        await channel.stop()
        assert done.is_set()
        assert not channel._sync_task.cancelled()
        channel.client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_without_client_or_task_is_safe(self):
        channel = _make_channel()
        await channel.stop()
        assert channel._running is False

    @pytest.mark.asyncio
    async def test_stop_cancels_typing_keepalive_tasks(self):
        channel = _make_channel()
        channel._running = True
        channel.client = _fake_client()
        channel._sync_task = None
        await channel._start_typing_keepalive("!room:example.org")
        task = channel._typing_tasks.get("!room:example.org")
        assert task is not None and not task.done()
        await channel.stop()
        assert channel._typing_tasks == {}
        assert task.cancelled()
        channel.client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_typing_keepalive_refreshes_and_stops_cleanly(self):
        channel = _make_channel()
        channel._running = False  # keepalive loop not spawned when not running
        channel.client = _fake_client()
        await channel._start_typing_keepalive("!room:1")
        await channel._start_typing_keepalive("!room:1")  # replaces prior session
        assert channel._typing_tasks == {}  # nothing spawned while not running
        await channel._stop_typing_keepalive("!room:1", clear_typing=True)
        channel.client.room_typing.assert_awaited()

    @pytest.mark.asyncio
    async def test_typing_failure_is_swallowed(self):
        channel = _make_channel()
        channel.client = _fake_client(room_typing=AsyncMock(side_effect=RuntimeError("offline")))
        await channel._set_typing("!room:1", True)
        channel.client.room_typing.assert_awaited_once()
