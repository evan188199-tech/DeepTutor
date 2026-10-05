"""Unit tests for the Email channel (IMAP polling) implementation.

Covers the DT-22 §7 MEDIUM finding at email.py:377 (``client.logout()``
swallowed in ``_fetch_messages``) plus the surrounding fetch/parse contract:
normal pull, connection-failure degradation in ``start()``, and resource
release after ``stop()``. All IMAP clients are fake — no network, no
real mailbox.
"""

from __future__ import annotations

import asyncio
from datetime import date
from email.message import EmailMessage
from email.utils import make_msgid
import imaplib
import threading
import types
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels import email as email_mod
from deeptutor.partners.channels.email import EmailChannel, EmailConfig


def _make_channel(**overrides) -> EmailChannel:
    defaults: dict[str, Any] = {
        "enabled": True,
        "consent_granted": True,
        "imap_host": "imap.example.com",
        "imap_port": 993,
        "imap_username": "bot@example.com",
        "imap_password": "secret-imap",
        "smtp_host": "smtp.example.com",
        "smtp_username": "bot@example.com",
        "smtp_password": "secret-smtp",
        "allow_from": ["*"],
    }
    defaults.update(overrides)
    config = EmailConfig.model_validate(defaults)
    bus = MagicMock(spec=MessageBus)
    bus.publish_inbound = AsyncMock()
    return EmailChannel(config, bus)


def _raw_email(
    *,
    sender: str = "Alice Example <Alice@Example.COM>",
    subject: str = "Café meeting",
    body: str = "Hello tutor",
    message_id: str = "<m1@example.com>",
    date_header: str = "Sat, 03 Oct 2026 10:00:00 +0000",
    raw: bytes | None = None,
) -> bytes:
    if raw is not None:
        return raw
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = "bot@example.com"
    msg["Subject"] = subject
    msg["Message-ID"] = message_id
    msg["Date"] = date_header
    msg.set_content(body)
    return bytes(msg)


class FakeImapClient:
    """Scripted stand-in for imaplib.IMAP4(_SSL) mirroring response shapes."""

    def __init__(
        self,
        *,
        messages: list[tuple[bytes, bytes, bytes]] | None = None,
        select_status: str = "OK",
        search_status: str = "OK",
        search_data: list[bytes] | None = None,
        fetch_status: str = "OK",
        fail_fetch_ids: tuple[bytes, ...] = (),
        login_error: Exception | None = None,
        logout_error: Exception | None = None,
    ):
        self.messages = messages or []
        self.select_status = select_status
        self.search_status = search_status
        self.search_data = search_data
        self.fetch_status = fetch_status
        self.fail_fetch_ids = set(fail_fetch_ids)
        self.login_error = login_error
        self.logout_error = logout_error
        self.calls: list[tuple[Any, ...]] = []
        self.stored: list[bytes] = []
        self.logout_count = 0

    def login(self, user, password):
        self.calls.append(("login", user, password))
        if self.login_error:
            raise self.login_error
        return "OK", [b"Logged in"]

    def select(self, mailbox):
        self.calls.append(("select", mailbox))
        return self.select_status, [b"1"]

    def search(self, charset, *criteria):
        self.calls.append(("search", tuple(criteria)))
        if self.search_status != "OK":
            return self.search_status, [b""]
        if self.search_data is not None:
            return "OK", self.search_data
        ids = b" ".join(entry[0] for entry in self.messages)
        return "OK", [ids]

    def fetch(self, imap_id, spec):
        self.calls.append(("fetch", imap_id, spec))
        if self.fetch_status != "OK" or imap_id in self.fail_fetch_ids:
            return self.fetch_status, [None]
        for entry in self.messages:
            if entry[0] == imap_id:
                header = b"%s (UID %s BODY[] {%d}" % (imap_id, entry[1], len(entry[2]))
                return "OK", [(header, entry[2]), b")"]
        return "OK", [None]

    def store(self, imap_id, command, flags):
        self.calls.append(("store", imap_id, command, flags))
        self.stored.append(imap_id)
        return "OK", [b""]

    def logout(self):
        self.calls.append(("logout",))
        self.logout_count += 1
        if self.logout_error:
            raise self.logout_error
        return "BYE", [b"See you"]


def _install_imap_factory(monkeypatch, *, clients=None, error=None):
    """Patch the email module's imaplib with a scripted client factory."""
    created: list[FakeImapClient] = []
    host_port: list[tuple[str, int]] = []
    factory_state = {"error": error}

    def factory(host, port, **kwargs):
        host_port.append((host, port))
        if factory_state["error"] is not None:
            raise factory_state["error"]
        client = clients.pop(0) if clients else FakeImapClient()
        created.append(client)
        return client

    monkeypatch.setattr(
        email_mod,
        "imaplib",
        types.SimpleNamespace(IMAP4_SSL=factory, IMAP4=factory),
    )
    factory.created = created
    factory.host_port = host_port
    factory.state = factory_state
    return factory


def _msg_entry(imap_id: bytes, uid: bytes, raw: bytes) -> tuple[bytes, bytes, bytes]:
    return (imap_id, uid, raw)


class TestFetchAndParse:
    def test_fetch_new_messages_parses_sender_subject_body_metadata(self, monkeypatch):
        raw = _raw_email()
        client = FakeImapClient(messages=[_msg_entry(b"7", b"101", raw)])
        factory = _install_imap_factory(monkeypatch, clients=[client])
        ch = _make_channel()

        items = ch._fetch_new_messages()

        assert factory.host_port == [("imap.example.com", 993)]
        assert len(items) == 1
        item = items[0]
        assert item["sender"] == "alice@example.com"
        assert item["subject"] == "Café meeting"
        assert item["message_id"] == "<m1@example.com>"
        assert item["metadata"]["uid"] == "101"
        assert item["metadata"]["sender_email"] == "alice@example.com"
        assert item["metadata"]["message_id"] == "<m1@example.com>"
        assert item["content"].startswith("Email received.\nFrom: alice@example.com\n")
        assert "Subject: Café meeting" in item["content"]
        assert "Hello tutor" in item["content"]

        assert client.calls[0] == ("login", "bot@example.com", "secret-imap")
        assert client.calls[1] == ("select", "INBOX")
        assert client.calls[2] == ("search", ("UNSEEN",))
        assert client.calls[3] == ("fetch", b"7", "(BODY.PEEK[] UID)")
        assert client.calls[4] == ("store", b"7", "+FLAGS", "\\Seen")
        assert client.calls[-1] == ("logout",)
        assert client.logout_count == 1

    def test_mark_seen_disabled_skips_store_flag_write(self, monkeypatch):
        client = FakeImapClient(
            messages=[_msg_entry(b"3", b"11", _raw_email(message_id=make_msgid()))]
        )
        _install_imap_factory(monkeypatch, clients=[client])
        ch = _make_channel(mark_seen=False)

        items = ch._fetch_new_messages()

        assert len(items) == 1
        assert client.stored == []
        assert not any(call[0] == "store" for call in client.calls)

    def test_uid_dedupe_skips_repeated_uids(self, monkeypatch):
        raw = _raw_email()
        first = FakeImapClient(messages=[_msg_entry(b"1", b"42", raw)])
        second = FakeImapClient(messages=[_msg_entry(b"1", b"42", raw)])
        _install_imap_factory(monkeypatch, clients=[first, second])
        ch = _make_channel()

        first_batch = ch._fetch_new_messages()
        second_batch = ch._fetch_new_messages()

        assert len(first_batch) == 1
        assert second_batch == []
        assert ch._processed_uids == {"42"}

    def test_limit_keeps_most_recent_ids(self, monkeypatch):
        entries = [
            _msg_entry(b"1", b"201", _raw_email(message_id="<a@x>")),
            _msg_entry(b"2", b"202", _raw_email(message_id="<b@x>")),
            _msg_entry(b"3", b"203", _raw_email(message_id="<c@x>")),
        ]
        client = FakeImapClient(messages=entries)
        _install_imap_factory(monkeypatch, clients=[client])
        ch = _make_channel(mark_seen=False)

        items = ch._fetch_messages(
            search_criteria=("UNSEEN",), mark_seen=False, dedupe=False, limit=1
        )

        assert [item["message_id"] for item in items] == ["<c@x>"]
        fetched_ids = [call[1] for call in client.calls if call[0] == "fetch"]
        assert fetched_ids == [b"3"]

    def test_empty_body_gets_placeholder(self, monkeypatch):
        raw = _raw_email(raw=b"From: plain@example.com\r\nSubject: hi\r\n\r\n")
        client = FakeImapClient(messages=[_msg_entry(b"5", b"301", raw)])
        _install_imap_factory(monkeypatch, clients=[client])
        ch = _make_channel()

        items = ch._fetch_new_messages()

        assert len(items) == 1
        assert "(empty email body)" in items[0]["content"]

    def test_body_truncated_to_max_body_chars(self, monkeypatch):
        client = FakeImapClient(messages=[_msg_entry(b"2", b"310", _raw_email(body="Hello tutor"))])
        _install_imap_factory(monkeypatch, clients=[client])
        ch = _make_channel(mark_seen=False, max_body_chars=5)

        items = ch._fetch_new_messages()

        assert "Hello" in items[0]["content"]
        assert "tutor" not in items[0]["content"]

    def test_multipart_plain_preferred_and_attachments_skipped(self, monkeypatch):
        msg = EmailMessage()
        msg["From"] = "Mixed Sender <mixed@example.com>"
        msg["To"] = "bot@example.com"
        msg["Subject"] = "Mixed"
        msg["Message-ID"] = "<mixed@x>"
        msg["Date"] = "Sat, 03 Oct 2026 09:00:00 +0000"
        msg.set_content("Plain part")
        msg.add_alternative("<p>HTML part</p>", subtype="html")
        msg.add_attachment(b"PDFDATA", maintype="application", subtype="pdf", filename="x.pdf")

        client = FakeImapClient(messages=[_msg_entry(b"9", b"401", bytes(msg))])
        _install_imap_factory(monkeypatch, clients=[client])
        ch = _make_channel(mark_seen=False)

        items = ch._fetch_new_messages()

        assert len(items) == 1
        assert "Plain part" in items[0]["content"]
        assert "HTML part" not in items[0]["content"]
        assert "PDFDATA" not in items[0]["content"]

    def test_html_only_body_converted_to_text(self, monkeypatch):
        msg = EmailMessage()
        msg["From"] = "html@example.com"
        msg["To"] = "bot@example.com"
        msg["Subject"] = "HTML only"
        msg["Message-ID"] = "<html@x>"
        msg.set_content("Hello<br/>World", subtype="html")

        client = FakeImapClient(messages=[_msg_entry(b"4", b"402", bytes(msg))])
        _install_imap_factory(monkeypatch, clients=[client])
        ch = _make_channel(mark_seen=False)

        items = ch._fetch_new_messages()

        assert "Hello\nWorld" in items[0]["content"]
        assert "<br/>" not in items[0]["content"]

    def test_fetch_between_dates_uses_imap_dates_and_limit(self, monkeypatch):
        client = FakeImapClient(
            messages=[
                _msg_entry(b"1", b"501", _raw_email(message_id="<d1@x>")),
                _msg_entry(b"2", b"502", _raw_email(message_id="<d2@x>")),
            ]
        )
        _install_imap_factory(monkeypatch, clients=[client])
        ch = _make_channel()

        items = ch.fetch_messages_between_dates(date(2026, 10, 1), date(2026, 10, 4), limit=5)

        assert [item["message_id"] for item in items] == ["<d1@x>", "<d2@x>"]
        assert client.calls[2] == (
            "search",
            ("SINCE", "01-Oct-2026", "BEFORE", "04-Oct-2026"),
        )
        assert client.stored == []

    def test_fetch_between_dates_empty_range_never_connects(self, monkeypatch):
        factory = _install_imap_factory(monkeypatch)
        ch = _make_channel()

        items = ch.fetch_messages_between_dates(date(2026, 10, 4), date(2026, 10, 4))

        assert items == []
        assert factory.host_port == []
        assert factory.created == []


class TestFailureAndSwallowPaths:
    def test_logout_failure_is_swallowed_and_messages_returned(self, monkeypatch):
        client = FakeImapClient(
            messages=[_msg_entry(b"6", b"601", _raw_email())],
            logout_error=imaplib.IMAP4.abort("connection closed during logout"),
        )
        _install_imap_factory(monkeypatch, clients=[client])
        ch = _make_channel(mark_seen=False)

        items = ch._fetch_new_messages()

        assert len(items) == 1
        assert client.logout_count == 1

    def test_select_failure_returns_empty_and_still_logs_out(self, monkeypatch):
        client = FakeImapClient(select_status="NO")
        _install_imap_factory(monkeypatch, clients=[client])
        ch = _make_channel()

        assert ch._fetch_new_messages() == []
        assert client.logout_count == 1
        assert not any(call[0] == "search" for call in client.calls)

    def test_search_failure_returns_empty_and_still_logs_out(self, monkeypatch):
        client = FakeImapClient(search_status="NO")
        _install_imap_factory(monkeypatch, clients=[client])
        ch = _make_channel()

        assert ch._fetch_new_messages() == []
        assert client.logout_count == 1
        assert not any(call[0] == "fetch" for call in client.calls)

    def test_failed_fetch_and_missing_sender_are_skipped(self, monkeypatch):
        no_sender = _raw_email(raw=b"Subject: who?\r\n\r\nbody\r\n")
        client = FakeImapClient(
            messages=[
                _msg_entry(b"1", b"701", _raw_email()),
                _msg_entry(b"2", b"702", no_sender),
            ],
            fail_fetch_ids=(b"1",),
        )
        _install_imap_factory(monkeypatch, clients=[client])
        ch = _make_channel(mark_seen=False)

        items = ch._fetch_new_messages()

        assert items == []
        assert client.stored == []

    def test_login_failure_propagates_but_logout_still_called(self, monkeypatch):
        client = FakeImapClient(login_error=imaplib.IMAP4.error("LOGIN failed"))
        _install_imap_factory(monkeypatch, clients=[client])
        ch = _make_channel()

        with pytest.raises(imaplib.IMAP4.error):
            ch._fetch_new_messages()
        assert client.logout_count == 1

    def test_non_ssl_config_uses_plain_imap(self, monkeypatch):
        client = FakeImapClient()
        factory = _install_imap_factory(monkeypatch, clients=[client])
        ch = _make_channel(imap_use_ssl=False, imap_port=143)

        items = ch._fetch_new_messages()

        assert items == []
        assert factory.host_port == [("imap.example.com", 143)]


def _install_gated_sleep(monkeypatch, gate: threading.Event) -> None:
    """Park the polling loop's sleep on *gate* so stop() timing is deterministic."""
    real_to_thread = asyncio.to_thread

    async def _sleep_until_gate(_seconds):
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, gate.wait)

    monkeypatch.setattr(
        email_mod,
        "asyncio",
        types.SimpleNamespace(to_thread=real_to_thread, sleep=_sleep_until_gate),
    )


async def _wait_for(predicate, timeout: float = 5.0) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate() and loop.time() < deadline:
        await asyncio.sleep(0.01)
    return predicate()


async def _stop_channel(ch: EmailChannel, task: asyncio.Task, gate: threading.Event) -> None:
    gate.set()
    await ch.stop()
    await asyncio.wait_for(task, timeout=10.0)


class TestStartStopLifecycle:
    @pytest.mark.asyncio
    async def test_start_without_consent_never_connects(self, monkeypatch):
        factory = _install_imap_factory(monkeypatch)
        ch = _make_channel(consent_granted=False)

        await asyncio.wait_for(ch.start(), timeout=5.0)

        assert ch._running is False
        assert ch.setup_state["status"] == "action_required"
        assert "consent" in ch.setup_state["message"].lower()
        assert factory.host_port == []

    @pytest.mark.asyncio
    async def test_start_with_missing_config_sets_action_required(self, monkeypatch):
        factory = _install_imap_factory(monkeypatch)
        ch = _make_channel(smtp_password="")

        await asyncio.wait_for(ch.start(), timeout=5.0)

        assert ch._running is False
        assert ch.setup_state["status"] == "action_required"
        assert factory.host_port == []

    @pytest.mark.asyncio
    async def test_connection_failure_degrades_to_error_state_and_keeps_retrying(self, monkeypatch):
        gate = threading.Event()
        _install_gated_sleep(monkeypatch, gate)
        factory = _install_imap_factory(monkeypatch, error=ConnectionRefusedError("refused"))
        ch = _make_channel()

        task = asyncio.create_task(ch.start())
        reached_error = await _wait_for(lambda: ch.setup_state.get("status") == "error")

        assert reached_error
        assert ch.setup_state["message"] == ("Channel connection failed; the listener will retry.")
        assert ch._running is True
        assert factory.host_port  # at least one connection attempt was made

        await _stop_channel(ch, task, gate)

    @pytest.mark.asyncio
    async def test_start_polls_inbound_and_publishes_to_bus(self, monkeypatch):
        gate = threading.Event()
        _install_gated_sleep(monkeypatch, gate)
        client = FakeImapClient(messages=[_msg_entry(b"8", b"801", _raw_email())])
        _install_imap_factory(monkeypatch, clients=[client])
        ch = _make_channel()

        task = asyncio.create_task(ch.start())
        published = await _wait_for(lambda: ch.bus.publish_inbound.await_count == 1)

        assert published
        assert ch.setup_state["status"] == "running"
        msg = ch.bus.publish_inbound.await_args.args[0]
        assert msg.channel == "email"
        assert msg.sender_id == "alice@example.com"
        assert msg.chat_id == "alice@example.com"
        assert "Hello tutor" in msg.content
        assert ch._last_subject_by_chat["alice@example.com"] == "Café meeting"
        assert ch._last_message_id_by_chat["alice@example.com"] == "<m1@example.com>"

        await _stop_channel(ch, task, gate)

    @pytest.mark.asyncio
    async def test_stop_exits_loop_and_releases_client(self, monkeypatch):
        gate = threading.Event()
        _install_gated_sleep(monkeypatch, gate)
        client = FakeImapClient(messages=[_msg_entry(b"8", b"801", _raw_email())])
        factory = _install_imap_factory(monkeypatch, clients=[client])
        ch = _make_channel()

        task = asyncio.create_task(ch.start())
        await _wait_for(lambda: ch.bus.publish_inbound.await_count == 1)

        assert ch.is_running is True
        assert client.logout_count == 1  # connection released between polls
        publishes_at_stop = ch.bus.publish_inbound.await_count
        clients_at_stop = len(factory.created)

        await _stop_channel(ch, task, gate)

        assert task.done() and task.exception() is None
        assert ch._running is False
        assert ch.bus.publish_inbound.await_count == publishes_at_stop
        assert len(factory.created) == clients_at_stop
        assert all(c.logout_count == 1 for c in factory.created)
