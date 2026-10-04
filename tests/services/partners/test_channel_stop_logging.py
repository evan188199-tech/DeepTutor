"""Channel stop()/logout() failures must be logged, not swallowed.

A close failure during shutdown used to disappear into ``except Exception:
pass`` — connections leaked with nothing to diagnose. These tests lock the
``close_quietly`` / ``aclose_quietly`` contract and its use in the partner
channels: each failed close logs a warning, the remaining cleanup still runs,
and multi-close stops aggregate the failed steps.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from deeptutor.partners.bus.queue import MessageBus


@pytest.fixture
def loguru_sink():
    """Capture loguru records (level >= DEBUG) with their level names."""
    from loguru import logger

    records: list[dict] = []
    sink_id = logger.add(lambda message: records.append(message.record), level="DEBUG")
    yield records
    logger.remove(sink_id)


def _warnings(records: list[dict]) -> list[str]:
    return [r["message"] for r in records if r["level"].name == "WARNING"]


def _make_bus() -> MagicMock:
    bus = MagicMock(spec=MessageBus)
    bus.publish_inbound = AsyncMock()
    return bus


# ---------------------------------------------------------------------------
# helpers: close_quietly / aclose_quietly
# ---------------------------------------------------------------------------


class TestCloseHelpers:
    @pytest.mark.asyncio
    async def test_aclose_quietly_awaits_async_close(self) -> None:
        from deeptutor.partners.helpers import aclose_quietly

        closed = AsyncMock()
        assert await aclose_quietly("thing", closed) is True
        closed.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_aclose_quietly_supports_sync_close(self) -> None:
        from deeptutor.partners.helpers import aclose_quietly

        closed = MagicMock()
        assert await aclose_quietly("thing", closed) is True
        closed.assert_called_once()

    @pytest.mark.asyncio
    async def test_aclose_quietly_logs_warning_and_returns_false(self, loguru_sink) -> None:
        from deeptutor.partners.helpers import aclose_quietly

        async def boom() -> None:
            raise RuntimeError("boom")

        assert await aclose_quietly("my resource", boom) is False
        assert any(
            "Failed to close my resource" in r and "boom" in r for r in _warnings(loguru_sink)
        )

    def test_close_quietly_sync_success(self) -> None:
        from deeptutor.partners.helpers import close_quietly

        closed = MagicMock()
        assert close_quietly("thing", closed) is True
        closed.assert_called_once()

    def test_close_quietly_logs_warning_and_returns_false(self, loguru_sink) -> None:
        from deeptutor.partners.helpers import close_quietly

        def boom() -> None:
            raise ValueError("nope")

        assert close_quietly("my resource", boom) is False
        assert any(
            "Failed to close my resource" in r and "nope" in r for r in _warnings(loguru_sink)
        )


# ---------------------------------------------------------------------------
# napcat: stop() must finish cleanup and log every failed close
# ---------------------------------------------------------------------------


class TestNapcatStop:
    def _make_channel(self):
        from deeptutor.partners.channels.napcat import NapcatChannel, NapcatConfig

        config = NapcatConfig.model_validate(
            {
                "enabled": True,
                "ws_url": "ws://127.0.0.1:3001",
                "access_token": "secret-token-123",
            }
        )
        return NapcatChannel(config, _make_bus())

    @pytest.mark.asyncio
    async def test_ws_close_failure_logs_and_http_still_closed(self, loguru_sink) -> None:
        ch = self._make_channel()
        ws = MagicMock()
        ws.close = AsyncMock(side_effect=RuntimeError("ws refused"))
        http = MagicMock()
        http.close = AsyncMock()
        ch._ws = ws
        ch._http = http

        await ch.stop()  # must not raise

        ws.close.assert_awaited_once()
        http.close.assert_awaited_once()
        assert ch._ws is None and ch._http is None
        warns = _warnings(loguru_sink)
        assert any("Failed to close napcat websocket" in r for r in warns)
        assert any("cleanup failures: websocket" in r for r in warns)

    @pytest.mark.asyncio
    async def test_http_close_failure_does_not_raise(self, loguru_sink) -> None:
        ch = self._make_channel()
        ws = MagicMock()
        ws.close = AsyncMock()
        http = MagicMock()
        http.close = AsyncMock(side_effect=RuntimeError("http refused"))
        ch._ws = ws
        ch._http = http

        await ch.stop()

        ws.close.assert_awaited_once()
        http.close.assert_awaited_once()
        assert any("Failed to close napcat HTTP client" in r for r in _warnings(loguru_sink))

    @pytest.mark.asyncio
    async def test_stop_is_idempotent(self, loguru_sink) -> None:
        ch = self._make_channel()
        ws = MagicMock()
        ws.close = AsyncMock()
        ch._ws = ws

        await ch.stop()
        await ch.stop()  # second call: nothing left to close, still fine

        ws.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# mochat: stop() must finish cleanup and log every failed close
# ---------------------------------------------------------------------------


class TestMochatStop:
    def _make_channel(self):
        from deeptutor.partners.channels.mochat import MochatChannel, MochatConfig

        config = MochatConfig.model_validate({"enabled": True, "claw_token": "tok"})
        channel = MochatChannel(config, _make_bus())
        channel.partner_id = "partner-test"
        return channel

    @pytest.mark.asyncio
    async def test_socket_disconnect_failure_keeps_http_cleanup(self, loguru_sink) -> None:
        ch = self._make_channel()
        socket = MagicMock()
        socket.disconnect = AsyncMock(side_effect=RuntimeError("socket stuck"))
        http = MagicMock()
        http.aclose = AsyncMock()
        ch._socket = socket
        ch._http = http

        await ch.stop()  # must not raise

        socket.disconnect.assert_awaited_once()
        http.aclose.assert_awaited_once()
        assert ch._socket is None and ch._http is None
        warns = _warnings(loguru_sink)
        assert any("Failed to close Mochat websocket" in r for r in warns)
        assert any("cleanup failures: websocket" in r for r in warns)

    @pytest.mark.asyncio
    async def test_http_aclose_failure_does_not_abort_stop(self, loguru_sink) -> None:
        ch = self._make_channel()
        socket = MagicMock()
        socket.disconnect = AsyncMock()
        http = MagicMock()
        http.aclose = AsyncMock(side_effect=RuntimeError("http stuck"))
        ch._socket = socket
        ch._http = http

        await ch.stop()  # must not raise despite http.aclose failing

        socket.disconnect.assert_awaited_once()
        http.aclose.assert_awaited_once()
        assert ch._socket is None and ch._http is None
        assert ch._ws_connected is False and ch._ws_ready is False
        warns = _warnings(loguru_sink)
        assert any("Failed to close Mochat HTTP client" in r for r in warns)
        assert any("cleanup failures: HTTP client" in r for r in warns)


# ---------------------------------------------------------------------------
# qq: stop() must log a failed client close and still finish
# ---------------------------------------------------------------------------


class TestQQStop:
    def _make_channel(self):
        from deeptutor.partners.channels.qq import QQChannel, QQConfig

        config = QQConfig.model_validate({"enabled": True, "app_id": "id", "secret": "s"})
        return QQChannel(config, _make_bus())

    @pytest.mark.asyncio
    async def test_client_close_failure_logs_warning(self, loguru_sink) -> None:
        ch = self._make_channel()
        client = MagicMock()
        client.close = AsyncMock(side_effect=RuntimeError("botpy died"))
        ch._client = client

        await ch.stop()  # must not raise

        client.close.assert_awaited_once()
        assert any("Failed to close QQ bot client" in r for r in _warnings(loguru_sink))


# ---------------------------------------------------------------------------
# zulip: stop() must log a failed queue deregister and still finish
# ---------------------------------------------------------------------------


class TestZulipStop:
    def _make_channel(self):
        from deeptutor.partners.channels.zulip import ZulipChannel, ZulipConfig

        config = ZulipConfig.model_validate(
            {
                "enabled": True,
                "site": "https://zulip.example",
                "email": "b@example.com",
                "api_key": "k",
            }
        )
        return ZulipChannel(config, _make_bus())

    @pytest.mark.asyncio
    async def test_deregister_failure_logs_warning_and_clears_state(self, loguru_sink) -> None:
        ch = self._make_channel()
        client = MagicMock()
        client.deregister = MagicMock(side_effect=RuntimeError("queue gone"))
        ch._client = client
        ch._queue_id = "q123"

        await ch.stop()  # must not raise

        client.deregister.assert_called_once_with("q123")
        assert ch._client is None and ch._queue_id is None
        assert any("Failed to close zulip event queue" in r for r in _warnings(loguru_sink))


# ---------------------------------------------------------------------------
# email: IMAP logout failure must be logged, fetched messages still returned
# ---------------------------------------------------------------------------


class TestEmailLogout:
    def _make_channel(self):
        from deeptutor.partners.channels.email import EmailChannel, EmailConfig

        config = EmailConfig.model_validate(
            {
                "enabled": True,
                "imap_host": "imap.example.com",
                "imap_username": "u",
                "imap_password": "p",
                "smtp_host": "smtp.example.com",
                "smtp_username": "u",
                "smtp_password": "p",
            }
        )
        return EmailChannel(config, _make_bus())

    def test_logout_failure_logs_warning_and_returns_messages(
        self, loguru_sink, monkeypatch
    ) -> None:
        from deeptutor.partners.channels import email as email_module

        ch = self._make_channel()
        imap_client = MagicMock()
        imap_client.login.return_value = ("OK", [b"Logged in"])
        imap_client.select.return_value = ("NO", [b"no mailbox"])
        imap_client.logout.side_effect = RuntimeError("logout refused")
        monkeypatch.setattr(email_module.imaplib, "IMAP4_SSL", lambda *a, **kw: imap_client)

        messages = ch._fetch_messages(("UNSEEN",), mark_seen=False, dedupe=False, limit=0)

        assert messages == []
        imap_client.logout.assert_called_once()
        assert any("Failed to close IMAP session" in r for r in _warnings(loguru_sink))


# ---------------------------------------------------------------------------
# matrix: _set_typing exceptions must not escape (best-effort indicator)
# ---------------------------------------------------------------------------


class TestMatrixSetTyping:
    def _make_channel(self):
        # matrix.py raises on import when its optional deps are absent, so
        # guard on those deps themselves to make this test skip cleanly.
        pytest.importorskip("mistune")
        pytest.importorskip("nh3")
        pytest.importorskip("nio")
        from deeptutor.partners.channels.matrix import MatrixChannel, MatrixConfig

        config = MatrixConfig.model_validate({"enabled": True})
        return MatrixChannel(config, _make_bus())

    @pytest.mark.asyncio
    async def test_typing_exception_is_swallowed_with_debug_log(self, loguru_sink) -> None:
        ch = self._make_channel()
        client = MagicMock()
        client.room_typing = AsyncMock(side_effect=RuntimeError("typing endpoint gone"))
        ch.client = client

        await ch._set_typing("!room", True)  # must not raise

        client.room_typing.assert_awaited_once()
        debugs = [r["message"] for r in loguru_sink if r["level"].name == "DEBUG"]
        assert any("Matrix typing update failed for !room" in m for m in debugs)
