"""Wall-clock ceiling for the opencode-family consult wait phase.

The end-of-turn ``POST /session/{id}/message`` and the SSE bus read run with
``read=None`` and no overall bound, so a silently hung remote made ``consult``
wait forever — only turn cancellation could interrupt it. These tests pin the
remedy: an opted-in ``idle_timeout_seconds`` cap cuts the wait with the
hermes-style ``idle_timeout`` failure surface (result code + EVENT_ERROR row,
best-effort abort), the family default (cap off) keeps the
wait-for-the-agent's-own-logic contract, and cancelling the turn still
interrupts a hanging wait. The transport is fully mocked via
``httpx.MockTransport`` — no CLI is spawned and no network is touched.
"""

from __future__ import annotations

import asyncio
import json
import typing

import httpx
import pytest

from deeptutor.services.subagent import opencode_family as of
from deeptutor.services.subagent.config import (
    BackendConfig,
    default_backend_config,
    settings_from_dict,
)
from deeptutor.services.subagent.opencode_family import OpencodeBackend

# Every hanging consult below is bounded by wait_for so a regression fails
# the test instead of wedging the suite; a working cap fires far earlier.
_HANG_GUARD_SECONDS = 5.0


class _FakeHandle:
    """Minimal stand-in for ``opencode_server.ServerHandle``."""

    base_url = "http://opencode.test"
    auth = None

    def __init__(self) -> None:
        self.touches = 0

    def touch(self) -> None:
        self.touches += 1


def _sse_bytes(events: typing.Sequence[dict]) -> bytes:
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events).encode()


async def _silent_after(events: typing.Sequence[dict]):
    """Yield the given events, then never yield again (a hung remote)."""
    yield _sse_bytes(events)
    await asyncio.Future()


async def _hang() -> None:
    await asyncio.Future()


def _install_transport(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    """Route every ``AsyncClient`` the driver opens through ``handler``."""
    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs.setdefault("transport", transport)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(of.httpx, "AsyncClient", factory)


def _hanging_router(
    *,
    sse_events: typing.Sequence[dict] = (),
    hang_session_create: bool = False,
):
    """A serve-API surface whose remote silently hangs where asked."""
    requests: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        requests.append((request.method, path))
        if request.method == "GET" and path == "/event":
            return httpx.Response(200, content=_silent_after(sse_events))
        if request.method == "POST" and path == "/session":
            if hang_session_create:
                await _hang()
            return httpx.Response(200, json={"id": "ses_new"})
        if request.method == "POST" and path.endswith("/message"):
            await _hang()  # the end-of-turn POST never returns
        if request.method == "POST" and path.endswith("/abort"):
            return httpx.Response(200, json={})
        return httpx.Response(404, json={"error": "unexpected route"})

    return handler, requests


async def _fake_acquire(monkeypatch: pytest.MonkeyPatch, handle: _FakeHandle) -> None:
    async def acquire(cli_command, **kwargs):
        return handle

    monkeypatch.setattr(of, "acquire_server", acquire)


async def _collect_events():
    emitted: list[tuple[str, str]] = []

    async def on_event(event):
        emitted.append((event.kind, event.text))

    return emitted, on_event


def _delta(session: str, pid: str, text: str) -> dict:
    return {
        "type": "message.part.delta",
        "properties": {"sessionID": session, "partID": pid, "field": "text", "delta": text},
    }


# ---- the cap cuts a silently hung remote --------------------------------------


@pytest.mark.asyncio
async def test_cap_cuts_hung_message_post_and_surfaces_idle_timeout(monkeypatch) -> None:
    handle = _FakeHandle()
    await _fake_acquire(monkeypatch, handle)
    # The bus streams one delta, then goes silent; the POST never returns.
    handler, requests = _hanging_router(sse_events=[_delta("ses_new", "p1", "partial answer")])
    _install_transport(monkeypatch, handler)
    emitted, on_event = await _collect_events()

    result = await asyncio.wait_for(
        OpencodeBackend().consult(
            "q", on_event=on_event, config=BackendConfig(idle_timeout_seconds=0.1)
        ),
        timeout=_HANG_GUARD_SECONDS,
    )

    assert result.success is False
    assert result.error == "idle_timeout"
    assert ("error", "idle_timeout") in emitted  # the failure is visible on the trace
    # whatever streamed before the hang is still handed back
    assert result.final_text == "partial answer"
    # the run was best-effort stopped — exactly once
    aborts = [r for r in requests if r[1].endswith("/abort")]
    assert aborts == [("POST", "/session/ses_new/abort")]
    assert handle.touches == 1


@pytest.mark.asyncio
async def test_cap_cuts_hung_session_create_without_abort(monkeypatch) -> None:
    handle = _FakeHandle()
    await _fake_acquire(monkeypatch, handle)
    handler, requests = _hanging_router(hang_session_create=True)
    _install_transport(monkeypatch, handler)
    emitted, on_event = await _collect_events()

    result = await asyncio.wait_for(
        OpencodeBackend().consult(
            "q", on_event=on_event, config=BackendConfig(idle_timeout_seconds=0.1)
        ),
        timeout=_HANG_GUARD_SECONDS,
    )

    assert result.success is False
    assert result.error == "idle_timeout"
    assert ("error", "idle_timeout") in emitted
    assert result.session_id is None
    assert not [r for r in requests if r[1].endswith("/abort")]  # nothing to stop yet
    assert handle.touches == 1


# ---- the default keeps the wait-unconditionally contract ----------------------


@pytest.mark.asyncio
async def test_default_config_waits_indefinitely_and_stays_cancellable(monkeypatch) -> None:
    handle = _FakeHandle()
    await _fake_acquire(monkeypatch, handle)
    handler, requests = _hanging_router()
    _install_transport(monkeypatch, handler)
    _, on_event = await _collect_events()

    # No config passed: the backend's own default applies (cap off).
    task = asyncio.create_task(OpencodeBackend().consult("q", on_event=on_event))
    await asyncio.sleep(0.3)
    assert not task.done()  # still waiting — no default wall-clock cut

    task.cancel()  # the turn being aborted remains the one interrupt
    with pytest.raises(asyncio.CancelledError):
        await task
    assert ("POST", "/session/ses_new/abort") in requests
    assert handle.touches == 1


# ---- configuration: knob defaults, persistence and clamping --------------------


def test_family_default_disables_cap_while_hermes_keeps_its_idle_default() -> None:
    assert default_backend_config("opencode").idle_timeout_seconds == 0
    assert default_backend_config("mimo").idle_timeout_seconds == 0
    assert default_backend_config("hermes_remote").idle_timeout_seconds == 600
    assert default_backend_config("codex").idle_timeout_seconds == 600


def test_settings_round_trip_persists_opted_in_family_cap() -> None:
    settings = settings_from_dict(
        {"backends": {"opencode": {"idle_timeout_seconds": 300}, "mimo": {"model": "m"}}}
    )
    assert settings.backend("opencode").idle_timeout_seconds == 300
    serialized = settings.to_dict()["backends"]
    assert serialized["opencode"]["idle_timeout_seconds"] == 300
    # the knob survives the save/load round-trip, including the off value
    reloaded = settings_from_dict(
        {"backends": {"opencode": serialized["opencode"], "mimo": serialized["mimo"]}}
    )
    assert reloaded.backend("opencode").idle_timeout_seconds == 300
    assert reloaded.backend("mimo").idle_timeout_seconds == 0
    # a fresh settings file without the knob keeps the family default (off)
    assert settings_from_dict({}).backend("opencode").idle_timeout_seconds == 0


def test_settings_clamp_range_keeps_hermes_floor() -> None:
    clamped = settings_from_dict({"backends": {"opencode": {"idle_timeout_seconds": 100_000}}})
    assert clamped.backend("opencode").idle_timeout_seconds == 86_400
    # hermes_remote keeps its historical floor of 1 (0 is only valid "off" for the family)
    hermes = settings_from_dict({"backends": {"hermes_remote": {"idle_timeout_seconds": 0}}})
    assert hermes.backend("hermes_remote").idle_timeout_seconds == 1
    off = settings_from_dict({"backends": {"opencode": {"idle_timeout_seconds": 0}}})
    assert off.backend("opencode").idle_timeout_seconds == 0
