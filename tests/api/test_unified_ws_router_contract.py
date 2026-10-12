"""Router-level contracts for the unified ``/ws`` adapter.

Covers the parts of ``deeptutor/api/routers/unified_ws.py`` the other
unified_ws suites do not: the ``protocol_version`` envelope on forwarded
subscription events, the subscribe/unsubscribe lifecycle (replacement and
targeted teardown), the remaining error frames, and disconnect semantics
(subscription teardown plus user-context reset).

Every test drives ``unified_websocket`` directly over a scripted socket, so
nothing listens on a port and each interleaving is deterministic.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from fastapi import WebSocketDisconnect
import pytest

from deeptutor.api.contracts.turn_protocol import PROTOCOL_VERSION
from deeptutor.api.routers import auth, unified_ws


class _FakeTurns:
    """Scripted subscription sources that record their own lifecycle."""

    def __init__(
        self,
        *,
        turn_scripts: list[list[dict]] | None = None,
        session_scripts: list[list[dict]] | None = None,
        turn_error: Exception | None = None,
        session_error: Exception | None = None,
        start_turn_error: Exception | None = None,
    ) -> None:
        self._turn_scripts = list(turn_scripts or [])
        self._session_scripts = list(session_scripts or [])
        self._turn_error = turn_error
        self._session_error = session_error
        self._start_turn_error = start_turn_error
        self.calls: list[tuple] = []
        self.cancelled: list[tuple] = []
        self.forwarded: list[tuple] = []

    async def start_turn(self, payload: dict):
        self.calls.append(("start_turn", payload))
        if self._start_turn_error is not None:
            raise self._start_turn_error
        return {"id": "session-1"}, {"id": "turn-new"}

    def subscribe_turn(self, turn_id: str, after_seq: int = 0):
        self.calls.append(("subscribe_turn", turn_id, after_seq))
        script = self._turn_scripts.pop(0) if self._turn_scripts else []
        return self._stream(script, ("turn", turn_id), self._turn_error)

    def subscribe_session(self, session_id: str, after_seq: int = 0):
        self.calls.append(("subscribe_session", session_id, after_seq))
        script = self._session_scripts.pop(0) if self._session_scripts else []
        return self._stream(script, ("session", session_id), self._session_error)

    async def _stream(self, script: list[dict], key: tuple, error: Exception | None):
        try:
            if error is not None:
                raise error
            for event in script:
                self.forwarded.append((key, event))
                yield event
            await asyncio.Event().wait()  # live subscription until cancelled
        except asyncio.CancelledError:
            self.cancelled.append(key)
            raise


class _ScriptedSocket:
    """Minimal WebSocket stand-in: scripted inbound frames, recorded outbound."""

    def __init__(
        self,
        turns: _FakeTurns,
        incoming: list,
        *,
        fail_send_index: int | None = None,
    ) -> None:
        self.turns = turns
        self.app = SimpleNamespace(
            state=SimpleNamespace(application_container=SimpleNamespace(turns=turns))
        )
        self._incoming = list(incoming)
        self._cursor = 0
        self._fail_send_index = fail_send_index
        self._send_index = 0
        self.accepted = False
        self.sent: list[str] = []

    async def accept(self) -> None:
        self.accepted = True

    async def receive_text(self) -> str:
        # One loop tick per inbound frame so pending subscription tasks get
        # scheduled, matching real I/O interleaving deterministically.
        await asyncio.sleep(0)
        if self._cursor >= len(self._incoming):
            raise WebSocketDisconnect(code=1000)
        raw = self._incoming[self._cursor]
        self._cursor += 1
        return raw if isinstance(raw, str) else json.dumps(raw)

    async def send_text(self, text: str) -> None:
        self._send_index += 1
        if self._send_index == self._fail_send_index:
            raise RuntimeError("send failed")
        self.sent.append(text)


def _install_auth(monkeypatch: pytest.MonkeyPatch, token=None, *, failed: bool = False) -> None:
    async def authenticate(_ws):
        return auth.ws_auth_failed if failed else token

    monkeypatch.setattr(auth, "ws_require_auth", authenticate)


def _track_reset(monkeypatch: pytest.MonkeyPatch) -> list:
    resets: list = []
    monkeypatch.setattr(
        "deeptutor.multi_user.context.reset_current_user",
        lambda token: resets.append(token),
    )
    return resets


def _run_socket(socket: _ScriptedSocket) -> None:
    asyncio.run(unified_ws.unified_websocket(socket))


def _frames(socket: _ScriptedSocket) -> list[dict]:
    return [json.loads(text) for text in socket.sent]


def test_forwarded_events_carry_the_protocol_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_auth(monkeypatch)
    events = [{"type": "content", "content": "hello"}, {"type": "done"}]
    turns = _FakeTurns(turn_scripts=[events])
    socket = _ScriptedSocket(
        turns,
        [
            {
                "protocol_version": PROTOCOL_VERSION,
                "type": "subscribe_turn",
                "turn_id": "turn-1",
            }
        ],
    )
    _run_socket(socket)

    assert turns.calls == [("subscribe_turn", "turn-1", 0)]
    # Every forwarded frame is the source event plus exactly one envelope key.
    assert _frames(socket) == [
        {**events[0], "protocol_version": PROTOCOL_VERSION},
        {**events[1], "protocol_version": PROTOCOL_VERSION},
    ]
    assert turns.forwarded == [
        (("turn", "turn-1"), events[0]),
        (("turn", "turn-1"), events[1]),
    ]
    # The client disconnects while the subscription is live; teardown cancels it.
    assert turns.cancelled == [("turn", "turn-1")]


def test_resubscribe_replaces_the_previous_turn_subscription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_auth(monkeypatch)
    first_events = [{"type": "progress", "content": "old"}]
    second_events = [{"type": "content", "content": "new"}]
    turns = _FakeTurns(turn_scripts=[first_events, second_events])
    socket = _ScriptedSocket(
        turns,
        [
            {
                "protocol_version": PROTOCOL_VERSION,
                "type": "subscribe_turn",
                "turn_id": "turn-1",
            },
            {
                "protocol_version": PROTOCOL_VERSION,
                "type": "subscribe_turn",
                "turn_id": "turn-1",
            },
        ],
    )
    _run_socket(socket)

    assert turns.calls == [
        ("subscribe_turn", "turn-1", 0),
        ("subscribe_turn", "turn-1", 0),
    ]
    # The replacement stops the first subscription before the second starts:
    # old frames stop arriving and each generator is torn down exactly once.
    assert _frames(socket) == [
        {**first_events[0], "protocol_version": PROTOCOL_VERSION},
        {**second_events[0], "protocol_version": PROTOCOL_VERSION},
    ]
    assert turns.forwarded == [
        (("turn", "turn-1"), first_events[0]),
        (("turn", "turn-1"), second_events[0]),
    ]
    assert turns.cancelled == [("turn", "turn-1"), ("turn", "turn-1")]


def test_unsubscribe_targets_each_scope_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_auth(monkeypatch)
    turn_events = [{"type": "content", "content": "turn"}]
    session_events = [{"type": "session", "content": "session"}]
    turns = _FakeTurns(turn_scripts=[turn_events], session_scripts=[session_events])
    socket = _ScriptedSocket(
        turns,
        [
            {
                "protocol_version": PROTOCOL_VERSION,
                "type": "subscribe_turn",
                "turn_id": "turn-1",
            },
            {
                "protocol_version": PROTOCOL_VERSION,
                "type": "subscribe_session",
                "session_id": "session-1",
                "after_seq": 3,
            },
            {"protocol_version": PROTOCOL_VERSION, "type": "unsubscribe", "turn_id": "turn-1"},
            {
                "protocol_version": PROTOCOL_VERSION,
                "type": "unsubscribe",
                "session_id": "session-1",
            },
            {
                "protocol_version": PROTOCOL_VERSION,
                "type": "unsubscribe",
                "turn_id": "turn-1",
                "session_id": "session-1",
            },
        ],
    )
    _run_socket(socket)

    assert turns.calls == [
        ("subscribe_turn", "turn-1", 0),
        ("subscribe_session", "session-1", 3),
    ]
    # Unsubscribe emits no frames of its own and re-unsubscribing is a no-op.
    assert _frames(socket) == [
        {**turn_events[0], "protocol_version": PROTOCOL_VERSION},
        {**session_events[0], "protocol_version": PROTOCOL_VERSION},
    ]
    assert turns.cancelled.count(("turn", "turn-1")) == 1
    assert turns.cancelled.count(("session", "session-1")) == 1


def test_resume_from_replays_from_the_requested_seq(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_auth(monkeypatch)
    replay_events = [{"type": "content", "content": "replay"}]
    turns = _FakeTurns(turn_scripts=[replay_events])
    socket = _ScriptedSocket(
        turns,
        [
            {
                "protocol_version": PROTOCOL_VERSION,
                "type": "resume_from",
                "turn_id": "turn-9",
                "seq": 7,
            }
        ],
    )
    _run_socket(socket)

    assert ("subscribe_turn", "turn-9", 7) in turns.calls
    assert _frames(socket) == [{**replay_events[0], "protocol_version": PROTOCOL_VERSION}]


def test_malformed_frames_get_error_frames(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_auth(monkeypatch)
    turns = _FakeTurns()
    socket = _ScriptedSocket(
        turns,
        [
            "{not json",
            "[1, 2]",
            json.dumps({"type": "teleport", "protocol_version": PROTOCOL_VERSION}),
        ],
    )
    _run_socket(socket)

    assert _frames(socket) == [
        {
            "type": "protocol_error",
            "error_code": "invalid_json",
            "message": "Invalid JSON.",
            "retryable": False,
            "session_id": "",
            "turn_id": "",
            "protocol_version": PROTOCOL_VERSION,
        },
        {
            "type": "protocol_error",
            "error_code": "invalid_command",
            "message": "WebSocket commands must be JSON objects.",
            "retryable": False,
            "session_id": "",
            "turn_id": "",
            "protocol_version": PROTOCOL_VERSION,
        },
        {
            "type": "protocol_error",
            "error_code": "invalid_command",
            "message": "Command does not match the turn protocol.",
            "retryable": False,
            "session_id": "",
            "turn_id": "",
            "protocol_version": PROTOCOL_VERSION,
        },
    ]
    assert turns.calls == []


@pytest.mark.parametrize(
    ("command", "error_code", "message"),
    [
        ({"type": "subscribe_turn", "turn_id": "   "}, "missing_turn_id", "Missing turn_id."),
        ({"type": "resume_from", "turn_id": "   "}, "missing_turn_id", "Missing turn_id."),
        (
            {"type": "subscribe_session", "session_id": "   "},
            "missing_session_id",
            "Missing session_id.",
        ),
    ],
)
def test_whitespace_only_ids_get_missing_id_error_frames(
    monkeypatch: pytest.MonkeyPatch, command: dict, error_code: str, message: str
) -> None:
    _install_auth(monkeypatch)
    turns = _FakeTurns()
    socket = _ScriptedSocket(turns, [{**command, "protocol_version": PROTOCOL_VERSION}])
    _run_socket(socket)

    assert _frames(socket) == [
        {
            "type": "protocol_error",
            "error_code": error_code,
            "message": message,
            "retryable": False,
            "session_id": "",
            "turn_id": "",
            "protocol_version": PROTOCOL_VERSION,
        }
    ]
    assert turns.calls == []


@pytest.mark.parametrize("scope", ["turn", "session"])
def test_subscription_failure_emits_a_retryable_error_frame(
    monkeypatch: pytest.MonkeyPatch, scope: str
) -> None:
    _install_auth(monkeypatch)
    if scope == "turn":
        turns = _FakeTurns(turn_error=RuntimeError("store offline"))
        command: dict = {"type": "subscribe_turn", "turn_id": "turn-1"}
        target = {"turn_id": "turn-1", "session_id": ""}
    else:
        turns = _FakeTurns(session_error=RuntimeError("store offline"))
        command = {"type": "subscribe_session", "session_id": "session-1"}
        target = {"turn_id": "", "session_id": "session-1"}
    socket = _ScriptedSocket(turns, [{**command, "protocol_version": PROTOCOL_VERSION}])
    _run_socket(socket)

    assert _frames(socket) == [
        {
            "type": "protocol_error",
            "error_code": "subscription_failed",
            "message": "store offline",
            "retryable": True,
            "session_id": target["session_id"],
            "turn_id": target["turn_id"],
            "protocol_version": PROTOCOL_VERSION,
        }
    ]


def test_start_turn_rejection_emits_a_terminal_error_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_auth(monkeypatch)
    turns = _FakeTurns(start_turn_error=RuntimeError("session busy"))
    socket = _ScriptedSocket(
        turns,
        [
            {
                "protocol_version": PROTOCOL_VERSION,
                "type": "start_turn",
                "content": "hi",
                "session_id": "session-1",
            }
        ],
    )
    _run_socket(socket)

    # The runtime handoff strips the framing keys; only request fields remain.
    assert turns.calls == [("start_turn", {"content": "hi", "session_id": "session-1"})]
    assert _frames(socket) == [
        {
            "type": "protocol_error",
            "error_code": "start_turn_rejected",
            "message": "session busy",
            "retryable": True,
            "session_id": "session-1",
            "turn_id": "",
            "protocol_version": PROTOCOL_VERSION,
        }
    ]


def test_disconnect_cancels_live_subscriptions_and_resets_user_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = object()
    _install_auth(monkeypatch, token=token)
    resets = _track_reset(monkeypatch)
    turns = _FakeTurns(
        turn_scripts=[[{"type": "content"}]],
        session_scripts=[[{"type": "session"}]],
    )
    socket = _ScriptedSocket(
        turns,
        [
            {
                "protocol_version": PROTOCOL_VERSION,
                "type": "subscribe_turn",
                "turn_id": "turn-1",
            },
            {
                "protocol_version": PROTOCOL_VERSION,
                "type": "subscribe_session",
                "session_id": "session-1",
            },
        ],
    )
    _run_socket(socket)

    assert socket.accepted is True
    assert turns.cancelled.count(("turn", "turn-1")) == 1
    assert turns.cancelled.count(("session", "session-1")) == 1
    assert resets == [token]


def test_auth_failure_returns_before_accept_and_without_context_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_auth(monkeypatch, failed=True)
    resets = _track_reset(monkeypatch)
    turns = _FakeTurns()
    socket = _ScriptedSocket(turns, [])
    _run_socket(socket)

    assert socket.accepted is False
    assert socket.sent == []
    assert resets == []
    assert turns.calls == []


def test_send_failure_marks_the_socket_closed_and_stops_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = object()
    _install_auth(monkeypatch, token=token)
    resets = _track_reset(monkeypatch)
    turns = _FakeTurns(turn_scripts=[[{"type": "content"}]])
    socket = _ScriptedSocket(
        turns,
        [
            {"protocol_version": PROTOCOL_VERSION, "type": "ping"},
            {
                "protocol_version": PROTOCOL_VERSION,
                "type": "subscribe_turn",
                "turn_id": "turn-1",
            },
        ],
        fail_send_index=1,
    )
    _run_socket(socket)  # must not raise

    # The failed pong is dropped, the read loop stops, and the queued
    # subscribe command is never processed; teardown still resets the context.
    assert socket.sent == []
    assert turns.calls == []
    assert turns.cancelled == []
    assert resets == [token]
