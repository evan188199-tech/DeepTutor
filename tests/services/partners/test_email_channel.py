"""Unit tests for the Email channel IMAP fetch/logout error paths."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels.email import EmailChannel, EmailConfig


def _make_channel(**overrides) -> EmailChannel:
    defaults = {
        "enabled": True,
        "consent_granted": True,
        "imap_host": "imap.example.com",
        "imap_username": "bot@example.com",
        "imap_password": "secret",
        "smtp_host": "smtp.example.com",
        "smtp_username": "bot@example.com",
        "smtp_password": "secret",
        "from_address": "bot@example.com",
    }
    defaults.update(overrides)
    config = EmailConfig.model_validate(defaults)
    bus = MagicMock(spec=MessageBus)
    return EmailChannel(config, bus)


_RAW_EMAIL = (
    b"From: Alice <alice@example.com>\r\n"
    b"To: bot@example.com\r\n"
    b"Subject: Hello\r\n"
    b"Date: Mon, 05 Oct 2026 10:00:00 +0000\r\n"
    b"Message-ID: <m1@example.com>\r\n"
    b"\r\n"
    b"Hi there\r\n"
)


def _imap_client(*, with_message: bool = False) -> MagicMock:
    client = MagicMock()
    client.login.return_value = ("OK", [b"Logged in"])
    client.select.return_value = ("OK", [b"1"])
    client.search.return_value = ("OK", [b"1"] if with_message else [b""])
    client.fetch.return_value = ("OK", [(b"1 (UID 7 BODY[] {234})", _RAW_EMAIL), b")"])
    client.logout.return_value = ("BYE", [b"Logging out"])
    return client


class TestFetchMessagesLogout:
    def test_logout_failure_logged_and_messages_returned(self):
        ch = _make_channel()
        client = _imap_client(with_message=True)
        client.logout.side_effect = RuntimeError("connection already closed")

        with (
            patch("deeptutor.partners.channels.email.imaplib.IMAP4_SSL", return_value=client),
            patch("deeptutor.partners.channels.email.logger.debug") as mock_debug,
        ):
            messages = ch._fetch_messages(("UNSEEN",), mark_seen=True, dedupe=True, limit=0)

        client.logout.assert_called_once()
        assert len(messages) == 1
        assert messages[0]["sender"] == "alice@example.com"
        mock_debug.assert_called_once()
        assert "IMAP logout failed" in str(mock_debug.call_args)

    def test_logout_success_not_logged(self):
        ch = _make_channel()
        client = _imap_client()

        with (
            patch("deeptutor.partners.channels.email.imaplib.IMAP4_SSL", return_value=client),
            patch("deeptutor.partners.channels.email.logger.debug") as mock_debug,
        ):
            messages = ch._fetch_messages(("UNSEEN",), mark_seen=True, dedupe=True, limit=0)

        client.logout.assert_called_once()
        assert messages == []
        mock_debug.assert_not_called()

    def test_fetch_new_messages_survives_logout_failure(self):
        ch = _make_channel()
        client = _imap_client(with_message=True)
        client.logout.side_effect = RuntimeError("timeout")

        with (
            patch("deeptutor.partners.channels.email.imaplib.IMAP4_SSL", return_value=client),
            patch("deeptutor.partners.channels.email.logger.debug"),
        ):
            messages = ch._fetch_new_messages()

        assert len(messages) == 1
        assert messages[0]["metadata"]["uid"] == "7"
