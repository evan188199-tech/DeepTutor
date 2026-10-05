"""Web-driven personal-WeChat QR login (#951).

The reporter's problem, in the WeChat case: the channel already knew how to log
in by QR, but drew the code on the server's stdout — a supervisord log on any
container deployment, so nobody configuring a partner could ever scan it.

These cover the two things that decides: reading WeChat's status payload
correctly, and never letting the bot token out of the server.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from deeptutor.partners.channels.weixin_qr import (
    QrCode,
    QrOutcome,
    interpret_status,
    is_retryable_poll_error,
    normalize_host,
)
from deeptutor.services.partners import weixin_onboarding


@pytest.fixture(autouse=True)
def _clean_attempts():
    weixin_onboarding._attempts.clear()
    yield
    weixin_onboarding._attempts.clear()


@pytest.fixture
def stub_partner(monkeypatch) -> dict[str, Any]:
    """A partner whose channel config we can read back after a login."""
    saved: dict[str, Any] = {"channels": {"weixin": {}}}

    class _Config:
        channels = saved["channels"]

    class _Manager:
        def __init__(self) -> None:
            self.reload_calls = 0

        def get_partner(self, partner_id: str):  # noqa: ARG002
            return None

        def load_config(self, partner_id: str):  # noqa: ARG002
            return _Config()

        def merge_config(self, partner_id: str, overrides):  # noqa: ARG002
            saved["channels"] = overrides["channels"]
            return _Config()

        def save_config(self, partner_id: str, config, **kwargs):  # noqa: ARG002
            saved["channels"] = config.channels
            saved["written"] = True

        async def reload_channels(self, partner_id: str):  # noqa: ARG002
            self.reload_calls += 1

    monkeypatch.setattr(
        "deeptutor.services.partners.manager.get_partner_manager", lambda: _Manager()
    )
    return saved


def _stub_exchange(monkeypatch, *, code: str = "qr-1", outcomes: list[QrOutcome] | None = None):
    calls = {"fetched": 0}

    async def _fetch(client, base_url, **kwargs):  # noqa: ARG001
        calls["fetched"] += 1
        # A re-issued code is a different code: distinct payload each time.
        return QrCode(
            qrcode_id=f"{code}-{calls['fetched']}",
            scan_payload=f"scan-{code}-{calls['fetched']}",
        )

    queue = list(outcomes or [])

    async def _poll(client, base_url, qrcode_id, **kwargs):  # noqa: ARG001
        return queue.pop(0) if queue else QrOutcome(status="waiting")

    monkeypatch.setattr(weixin_onboarding, "fetch_qr_code", _fetch)
    monkeypatch.setattr(weixin_onboarding, "poll_qr_code", _poll)
    return calls


# ---- reading WeChat's answers ------------------------------------------------


def test_confirmed_without_a_token_is_a_failure_not_a_success() -> None:
    """Storing an empty token would fail later, far from the cause."""
    assert interpret_status({"status": "confirmed"}).status == "error"


def test_an_unrecognised_status_means_keep_waiting() -> None:
    """A future WeChat status string must not end a login that is still live."""
    assert interpret_status({"status": "something_new"}).status == "unknown"
    assert interpret_status("not a dict").status == "unknown"


def test_redirect_is_a_scan_in_progress_carrying_a_new_host() -> None:
    outcome = interpret_status(
        {"status": "scaned_but_redirect", "redirect_host": "other.weixin.qq.com"}
    )

    assert outcome.status == "scanned"
    assert outcome.poll_base_url == "https://other.weixin.qq.com"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("host.qq.com", "https://host.qq.com"),
        ("https://host.qq.com", "https://host.qq.com"),
        ("http://host.qq.com", "http://host.qq.com"),
        ("", ""),
    ],
)
def test_redirect_hosts_are_normalised(raw: str, expected: str) -> None:
    assert normalize_host(raw) == expected


def test_only_transient_failures_are_worth_another_poll() -> None:
    assert is_retryable_poll_error(httpx.ConnectTimeout("x")) is True
    assert (
        is_retryable_poll_error(
            httpx.HTTPStatusError(
                "x", request=httpx.Request("GET", "https://x"), response=httpx.Response(503)
            )
        )
        is True
    )
    assert (
        is_retryable_poll_error(
            httpx.HTTPStatusError(
                "x", request=httpx.Request("GET", "https://x"), response=httpx.Response(403)
            )
        )
        is False
    )


# ---- the web-driven attempt --------------------------------------------------


@pytest.mark.asyncio
async def test_start_returns_something_the_browser_can_draw(monkeypatch, stub_partner) -> None:
    _stub_exchange(monkeypatch)

    started = await weixin_onboarding.start_login("p1")

    assert started["scan_payload"] == "scan-qr-1-1"
    assert started["status"] == "waiting"
    assert started["session_id"]


@pytest.mark.asyncio
async def test_a_confirmed_scan_writes_the_token_into_the_channel_config(
    monkeypatch, stub_partner
) -> None:
    _stub_exchange(
        monkeypatch,
        outcomes=[QrOutcome(status="confirmed", token="bot-token", base_url="https://edge")],
    )
    started = await weixin_onboarding.start_login("p1")

    status = await weixin_onboarding.poll_login("p1", started["session_id"])

    assert status["status"] == "confirmed"
    assert stub_partner["channels"]["weixin"]["token"] == "bot-token"
    assert stub_partner["channels"]["weixin"]["base_url"] == "https://edge"
    assert stub_partner["channels"]["weixin"]["enabled"] is True
    assert stub_partner["channels"]["weixin"]["allow_from"] == ["*"]
    assert stub_partner["written"] is True


@pytest.mark.asyncio
async def test_a_running_partner_reloads_with_the_new_identity(monkeypatch) -> None:
    saved: dict[str, Any] = {"channels": {"weixin": {"enabled": False}}}

    class _Config:
        def __init__(self) -> None:
            self.channels = saved["channels"]

    class _Instance:
        def __init__(self) -> None:
            self.config = _Config()

    class _Manager:
        def __init__(self) -> None:
            self.instance = _Instance()
            self.reloaded_with = ""

        def get_partner(self, partner_id: str):  # noqa: ARG002
            return self.instance

        def load_config(self, partner_id: str):  # noqa: ARG002
            # start_login reads provider options from disk; persistence must
            # still update the running instance's object before reload.
            return self.instance.config

        def save_config(self, partner_id: str, config, **kwargs):  # noqa: ARG002
            saved["channels"] = config.channels

        async def reload_channels(self, partner_id: str):  # noqa: ARG002
            self.reloaded_with = self.instance.config.channels["weixin"]["token"]

    manager = _Manager()
    monkeypatch.setattr("deeptutor.services.partners.manager.get_partner_manager", lambda: manager)
    _stub_exchange(monkeypatch, outcomes=[QrOutcome(status="confirmed", token="live-token")])

    started = await weixin_onboarding.start_login("p1")
    status = await weixin_onboarding.poll_login("p1", started["session_id"])

    assert status["status"] == "confirmed"
    assert manager.reloaded_with == "live-token"
    assert manager.instance.config.channels["weixin"]["enabled"] is True
    assert manager.instance.config.channels["weixin"]["allow_from"] == ["*"]


@pytest.mark.asyncio
async def test_the_token_never_appears_in_a_response(monkeypatch, stub_partner) -> None:
    """A status reply says whether it worked, never what it produced."""
    _stub_exchange(monkeypatch, outcomes=[QrOutcome(status="confirmed", token="s3cret")])
    started = await weixin_onboarding.start_login("p1")

    status = await weixin_onboarding.poll_login("p1", started["session_id"])

    assert "s3cret" not in str(started)
    assert "s3cret" not in str(status)
    assert "token" not in status


@pytest.mark.asyncio
async def test_a_redirect_moves_where_the_attempt_polls_next(monkeypatch, stub_partner) -> None:
    _stub_exchange(
        monkeypatch,
        outcomes=[QrOutcome(status="scanned", poll_base_url="https://edge-2")],
    )
    started = await weixin_onboarding.start_login("p1")

    status = await weixin_onboarding.poll_login("p1", started["session_id"])

    assert status["status"] == "scanned"
    assert weixin_onboarding._attempts[started["session_id"]].poll_base_url == "https://edge-2"


@pytest.mark.asyncio
async def test_an_expired_code_is_reissued_so_a_slow_scan_is_not_a_dead_end(
    monkeypatch, stub_partner
) -> None:
    calls = _stub_exchange(monkeypatch, outcomes=[QrOutcome(status="expired")])
    started = await weixin_onboarding.start_login("p1")

    status = await weixin_onboarding.poll_login("p1", started["session_id"])

    assert status["status"] == "waiting"
    assert calls["fetched"] == 2  # the original, plus the replacement


@pytest.mark.asyncio
async def test_repeated_expiry_eventually_ends_the_attempt(monkeypatch, stub_partner) -> None:
    _stub_exchange(monkeypatch, outcomes=[QrOutcome(status="expired")] * 6)
    started = await weixin_onboarding.start_login("p1")

    for _ in range(5):
        status = await weixin_onboarding.poll_login("p1", started["session_id"])

    assert status["status"] == "expired"


@pytest.mark.asyncio
async def test_an_unknown_status_keeps_the_attempt_alive(monkeypatch, stub_partner) -> None:
    _stub_exchange(monkeypatch, outcomes=[QrOutcome(status="unknown")])
    started = await weixin_onboarding.start_login("p1")

    status = await weixin_onboarding.poll_login("p1", started["session_id"])

    assert status["status"] == "waiting"


@pytest.mark.asyncio
async def test_confirmed_without_token_is_reported_as_an_error(monkeypatch, stub_partner) -> None:
    _stub_exchange(monkeypatch, outcomes=[QrOutcome(status="error")])
    started = await weixin_onboarding.start_login("p1")

    status = await weixin_onboarding.poll_login("p1", started["session_id"])

    assert status["status"] == "error"
    assert status["error"]
    assert "token" not in stub_partner["channels"]["weixin"]


@pytest.mark.asyncio
async def test_a_transient_poll_failure_is_not_a_verdict(monkeypatch, stub_partner) -> None:
    _stub_exchange(monkeypatch)
    started = await weixin_onboarding.start_login("p1")

    async def _boom(*args, **kwargs):
        raise httpx.ConnectTimeout("network blip")

    monkeypatch.setattr(weixin_onboarding, "poll_qr_code", _boom)
    status = await weixin_onboarding.poll_login("p1", started["session_id"])

    assert status["status"] == "waiting"


@pytest.mark.asyncio
async def test_a_session_belonging_to_another_partner_is_not_readable(
    monkeypatch, stub_partner
) -> None:
    _stub_exchange(monkeypatch)
    started = await weixin_onboarding.start_login("p1")

    status = await weixin_onboarding.poll_login("p2", started["session_id"])

    assert status["status"] == "expired"


@pytest.mark.asyncio
async def test_a_settled_attempt_stops_re_running_the_exchange(monkeypatch, stub_partner) -> None:
    _stub_exchange(monkeypatch, outcomes=[QrOutcome(status="confirmed", token="t")])
    started = await weixin_onboarding.start_login("p1")
    await weixin_onboarding.poll_login("p1", started["session_id"])

    async def _boom(*args, **kwargs):
        raise AssertionError("a confirmed attempt must not poll again")

    monkeypatch.setattr(weixin_onboarding, "poll_qr_code", _boom)
    status = await weixin_onboarding.poll_login("p1", started["session_id"])

    assert status["status"] == "confirmed"


@pytest.mark.asyncio
async def test_start_renders_the_code_server_side(monkeypatch, stub_partner) -> None:
    """The web bundle carries no QR library, so the SVG is drawn here."""
    _stub_exchange(monkeypatch)

    started = await weixin_onboarding.start_login("p1")

    assert started["qr_svg"].lstrip().startswith("<?xml")
    assert "<svg" in started["qr_svg"]


@pytest.mark.asyncio
async def test_a_reissued_code_ships_a_fresh_image_to_redraw(monkeypatch, stub_partner) -> None:
    """Expiry silently swaps the code; polling is the browser's only notice."""
    _stub_exchange(monkeypatch, outcomes=[QrOutcome(status="expired")])
    started = await weixin_onboarding.start_login("p1")

    status = await weixin_onboarding.poll_login("p1", started["session_id"])

    assert status["status"] == "waiting"
    assert "<svg" in status["qr_svg"]


@pytest.mark.asyncio
async def test_an_unchanged_code_does_not_resend_the_image(monkeypatch, stub_partner) -> None:
    _stub_exchange(monkeypatch, outcomes=[QrOutcome(status="waiting")])
    started = await weixin_onboarding.start_login("p1")

    status = await weixin_onboarding.poll_login("p1", started["session_id"])

    assert "qr_svg" not in status


def test_a_deployment_without_the_qrcode_library_still_gets_a_page(monkeypatch) -> None:
    """A trimmed deployment may still lack `qrcode`; missing it must degrade, not fail."""
    import builtins

    real_import = builtins.__import__

    def _no_qrcode(name, *args, **kwargs):
        if name.startswith("qrcode"):
            raise ImportError("no qrcode here")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_qrcode)

    assert weixin_onboarding.render_qr_svg("payload") == ""


def test_an_empty_payload_draws_nothing() -> None:
    assert weixin_onboarding.render_qr_svg("") == ""


# ---- expiry, cleanup and failure branches -------------------------------------


@pytest.mark.asyncio
async def test_a_session_left_open_past_the_ttl_reports_expired_and_is_pruned(
    monkeypatch, stub_partner
) -> None:
    """An overnight tab must not hold a pending login forever."""
    _stub_exchange(monkeypatch)
    started = await weixin_onboarding.start_login("p1")
    weixin_onboarding._attempts[started["session_id"]].created_at -= (
        weixin_onboarding._SESSION_TTL_SECONDS + 1
    )

    status = await weixin_onboarding.poll_login("p1", started["session_id"])

    assert status["status"] == "expired"
    assert status["expires_in"] == 0
    assert status["error"] == ""
    # The stale attempt is really gone, not just re-reported.
    assert started["session_id"] not in weixin_onboarding._attempts
    assert weixin_onboarding.current_scan_payload("p1", started["session_id"]) == ""


@pytest.mark.asyncio
async def test_pruning_takes_only_the_stale_sessions(monkeypatch, stub_partner) -> None:
    """Sweeping an expired tab must not kill a login that is still in progress."""
    _stub_exchange(monkeypatch)
    stale = await weixin_onboarding.start_login("p1")
    fresh = await weixin_onboarding.start_login("p1")
    weixin_onboarding._attempts[stale["session_id"]].created_at -= (
        weixin_onboarding._SESSION_TTL_SECONDS + 1
    )

    assert (await weixin_onboarding.poll_login("p1", stale["session_id"]))["status"] == "expired"
    assert (await weixin_onboarding.poll_login("p1", fresh["session_id"]))["status"] == "waiting"


@pytest.mark.asyncio
async def test_current_scan_payload_serves_the_latest_code_to_its_owner_only(
    monkeypatch, stub_partner
) -> None:
    """The browser re-reads what to draw; wrong partner or dead id draws nothing."""
    _stub_exchange(monkeypatch, outcomes=[QrOutcome(status="expired")])
    started = await weixin_onboarding.start_login("p1")
    assert weixin_onboarding.current_scan_payload("p1", started["session_id"]) == "scan-qr-1-1"

    await weixin_onboarding.poll_login("p1", started["session_id"])  # expiry re-issues the code

    assert weixin_onboarding.current_scan_payload("p1", started["session_id"]) == "scan-qr-1-2"
    assert weixin_onboarding.current_scan_payload("p2", started["session_id"]) == ""
    assert weixin_onboarding.current_scan_payload("p1", "no-such-session") == ""


@pytest.mark.asyncio
async def test_forget_drops_the_attempt_and_tolerates_unknown_ids(
    monkeypatch, stub_partner
) -> None:
    _stub_exchange(monkeypatch)
    started = await weixin_onboarding.start_login("p1")

    weixin_onboarding.forget("no-such-session")  # must be a no-op, not a raise
    weixin_onboarding.forget(started["session_id"])

    assert started["session_id"] not in weixin_onboarding._attempts
    status = await weixin_onboarding.poll_login("p1", started["session_id"])
    assert status["status"] == "expired"


@pytest.mark.asyncio
async def test_a_hard_poll_failure_ends_the_attempt_and_stays_put(
    monkeypatch, stub_partner
) -> None:
    """A non-transient failure is a verdict; polling it again repeats the verdict."""
    _stub_exchange(monkeypatch)
    started = await weixin_onboarding.start_login("p1")

    async def _hard_fail(*args, **kwargs):  # noqa: ARG001
        raise ValueError("4xx-style refusal")

    monkeypatch.setattr(weixin_onboarding, "poll_qr_code", _hard_fail)
    status = await weixin_onboarding.poll_login("p1", started["session_id"])
    assert status["status"] == "error"
    assert status["error"]

    async def _must_not_poll_again(*args, **kwargs):  # noqa: ARG001
        raise AssertionError("a failed attempt must not poll again")

    monkeypatch.setattr(weixin_onboarding, "poll_qr_code", _must_not_poll_again)
    again = await weixin_onboarding.poll_login("p1", started["session_id"])
    assert again["status"] == "error"
    assert again["error"] == status["error"]


@pytest.mark.asyncio
async def test_a_confirmed_login_that_cannot_be_saved_reports_a_recoverable_error(
    monkeypatch,
) -> None:
    """The scan worked but persistence failed: say so, and leak no token."""
    saved: dict[str, Any] = {"channels": {"weixin": {}}}

    class _Config:
        channels = saved["channels"]

    class _Manager:
        def get_partner(self, partner_id: str):  # noqa: ARG002
            return None

        def load_config(self, partner_id: str):  # noqa: ARG002
            return _Config()

        def save_config(self, partner_id: str, config, **kwargs):  # noqa: ARG002
            raise OSError("disk full")

        async def reload_channels(self, partner_id: str):  # noqa: ARG002
            raise AssertionError("must not reload a channel that failed to save")

    monkeypatch.setattr(
        "deeptutor.services.partners.manager.get_partner_manager", lambda: _Manager()
    )
    _stub_exchange(monkeypatch, outcomes=[QrOutcome(status="confirmed", token="s3cret")])
    started = await weixin_onboarding.start_login("p1")

    status = await weixin_onboarding.poll_login("p1", started["session_id"])

    assert status["status"] == "error"
    assert "could not save" in status["error"]
    assert "s3cret" not in str(status)
    assert "token" not in status


@pytest.mark.asyncio
async def test_confirming_a_partner_that_no_longer_exists_is_an_error_not_a_crash(
    monkeypatch,
) -> None:
    class _Manager:
        def get_partner(self, partner_id: str):  # noqa: ARG002
            return None

        def load_config(self, partner_id: str):  # noqa: ARG002
            return None

    monkeypatch.setattr(
        "deeptutor.services.partners.manager.get_partner_manager", lambda: _Manager()
    )
    _stub_exchange(monkeypatch, outcomes=[QrOutcome(status="confirmed", token="t")])
    started = await weixin_onboarding.start_login("p1")

    status = await weixin_onboarding.poll_login("p1", started["session_id"])

    assert status["status"] == "error"
    assert "could not save" in status["error"]


@pytest.mark.asyncio
async def test_a_failed_reissue_declares_the_attempt_expired(monkeypatch, stub_partner) -> None:
    """No replacement code means the slow scan really is over."""
    calls = _stub_exchange(monkeypatch, outcomes=[QrOutcome(status="expired")])
    started = await weixin_onboarding.start_login("p1")

    async def _reissue_boom(*args, **kwargs):  # noqa: ARG001
        raise httpx.ConnectTimeout("WeChat unreachable")

    monkeypatch.setattr(weixin_onboarding, "fetch_qr_code", _reissue_boom)
    status = await weixin_onboarding.poll_login("p1", started["session_id"])

    assert status["status"] == "expired"
    assert calls["fetched"] == 1  # only the original issue; the replacement failed


@pytest.mark.asyncio
async def test_expires_in_counts_down_while_the_attempt_is_alive(monkeypatch, stub_partner) -> None:
    _stub_exchange(monkeypatch)
    started = await weixin_onboarding.start_login("p1")
    weixin_onboarding._attempts[started["session_id"]].created_at -= (
        weixin_onboarding._SESSION_TTL_SECONDS - 30
    )

    status = await weixin_onboarding.poll_login("p1", started["session_id"])

    assert status["status"] == "waiting"
    assert 0 < status["expires_in"] <= 30


@pytest.mark.asyncio
async def test_a_garbled_channel_config_still_falls_back_to_the_default_endpoint(
    monkeypatch,
) -> None:
    """Bad partner config must not stop a login from starting."""
    seen: dict[str, Any] = {}

    class _Config:
        channels = None  # not a dict — the reader must tolerate it

    class _Manager:
        def load_config(self, partner_id: str):  # noqa: ARG002
            return _Config()

    monkeypatch.setattr(
        "deeptutor.services.partners.manager.get_partner_manager", lambda: _Manager()
    )

    async def _fetch(client, base_url, **kwargs):  # noqa: ARG001
        seen["base_url"] = base_url
        seen["route_tag"] = kwargs.get("route_tag")
        return QrCode(qrcode_id="qr-x", scan_payload="scan-x")

    monkeypatch.setattr(weixin_onboarding, "fetch_qr_code", _fetch)

    started = await weixin_onboarding.start_login("p1")

    assert started["status"] == "waiting"
    assert started["scan_payload"] == "scan-x"
    assert seen["base_url"] == weixin_onboarding._DEFAULT_BASE_URL
    assert seen["route_tag"] == ""
