"""Unit tests for the API progress broadcaster (WebSocket progress delivery).

``deeptutor.api.utils.progress_broadcaster.ProgressBroadcaster`` fans progress
updates out to every WebSocket subscribed to a knowledge-base channel; the
``/ws/knowledge-bases/{name}/progress`` route in ``deeptutor.api.routers``
demonstrates only its edge (replay) behavior. These tests pin the delivery
contract directly:

* frame serialization — every payload is wrapped in the
  ``{"type": "progress", "data": ...}`` envelope and stays JSON-serializable,
* subscriber exception isolation — a socket failing mid-send must neither
  prevent the remaining sockets from receiving the frame nor wedge the loop,
* discard policy — dead sockets are dropped from the channel on first failure
  so they cannot accumulate; per-socket delivery preserves publish order.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from deeptutor.api.utils.progress_broadcaster import ProgressBroadcaster


class _FakeWebSocket:
    """Minimal stand-in for fastapi.WebSocket.send_json."""

    def __init__(self, send_error: Exception | None = None) -> None:
        self.frames: list[dict] = []
        self.send_calls = 0
        self._send_error = send_error

    async def send_json(self, payload: dict) -> None:
        self.send_calls += 1
        if self._send_error is not None:
            raise self._send_error
        self.frames.append(payload)


def _reset_broadcaster_state() -> None:
    ProgressBroadcaster._instance = None
    ProgressBroadcaster._connections = {}
    # The class-level lock binds to the loop that first awaits it; a fresh
    # lock per test keeps each test on its own function-scoped event loop.
    ProgressBroadcaster._lock = asyncio.Lock()


@pytest.fixture
def broadcaster():
    _reset_broadcaster_state()
    instance = ProgressBroadcaster.get_instance()
    yield instance
    _reset_broadcaster_state()


# ---------------------------------------------------------------------------
# Frame serialization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_broadcast_wraps_payload_in_progress_envelope(broadcaster) -> None:
    ws = _FakeWebSocket()
    await broadcaster.connect("kb-demo", ws)

    progress = {"task_id": "task-1", "stage": "parsing", "progress_percent": 40}
    await broadcaster.broadcast("kb-demo", progress)

    assert ws.frames == [{"type": "progress", "data": progress}]


@pytest.mark.asyncio
async def test_broadcast_frame_is_json_serializable(broadcaster) -> None:
    ws = _FakeWebSocket()
    await broadcaster.connect("kb-demo", ws)

    await broadcaster.broadcast(
        "kb-demo", {"task_id": "task-1", "stage": "completed", "progress_percent": 100}
    )

    restored = json.loads(json.dumps(ws.frames[0]))
    assert restored == {
        "type": "progress",
        "data": {"task_id": "task-1", "stage": "completed", "progress_percent": 100},
    }


@pytest.mark.asyncio
async def test_broadcast_reaches_every_subscriber_on_the_channel(broadcaster) -> None:
    first = _FakeWebSocket()
    second = _FakeWebSocket()
    await broadcaster.connect("kb-demo", first)
    await broadcaster.connect("kb-demo", second)
    assert broadcaster.get_connection_count("kb-demo") == 2

    await broadcaster.broadcast("kb-demo", {"stage": "done"})

    assert first.frames == [{"type": "progress", "data": {"stage": "done"}}]
    assert second.frames == [{"type": "progress", "data": {"stage": "done"}}]


@pytest.mark.asyncio
async def test_broadcast_is_isolated_per_channel(broadcaster) -> None:
    kb_a = _FakeWebSocket()
    kb_b = _FakeWebSocket()
    await broadcaster.connect("kb-a", kb_a)
    await broadcaster.connect("kb-b", kb_b)

    await broadcaster.broadcast("kb-a", {"stage": "kb-a-only"})

    assert kb_a.frames != []
    assert kb_b.frames == []


@pytest.mark.asyncio
async def test_frames_arrive_in_publish_order(broadcaster) -> None:
    ws = _FakeWebSocket()
    await broadcaster.connect("kb-demo", ws)

    for index in range(5):
        await broadcaster.broadcast("kb-demo", {"step": index})

    assert [frame["data"]["step"] for frame in ws.frames] == [0, 1, 2, 3, 4]


# ---------------------------------------------------------------------------
# Subscriber exception isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failing_subscriber_does_not_affect_other_subscribers(broadcaster) -> None:
    """The regression contract: a dead socket must not sink the broadcast."""
    broken = _FakeWebSocket(send_error=RuntimeError("connection closed"))
    healthy = _FakeWebSocket()
    await broadcaster.connect("kb-demo", broken)
    await broadcaster.connect("kb-demo", healthy)

    await broadcaster.broadcast("kb-demo", {"stage": "parsing"})

    assert healthy.frames == [{"type": "progress", "data": {"stage": "parsing"}}]

    # Later broadcasts keep flowing to the healthy subscriber.
    await broadcaster.broadcast("kb-demo", {"stage": "completed"})
    assert [frame["data"]["stage"] for frame in healthy.frames] == [
        "parsing",
        "completed",
    ]


@pytest.mark.asyncio
async def test_failing_subscriber_is_dropped_from_the_channel(broadcaster) -> None:
    """Discard policy: dead sockets are removed on first send failure."""
    broken = _FakeWebSocket(send_error=RuntimeError("connection closed"))
    healthy = _FakeWebSocket()
    await broadcaster.connect("kb-demo", broken)
    await broadcaster.connect("kb-demo", healthy)

    await broadcaster.broadcast("kb-demo", {"stage": "parsing"})

    assert broadcaster.get_connection_count("kb-demo") == 1
    assert broken.send_calls == 1  # attempted once, then dropped

    # And it is never attempted again.
    await broadcaster.broadcast("kb-demo", {"stage": "done"})
    assert broken.send_calls == 1
    assert len(healthy.frames) == 2


@pytest.mark.asyncio
async def test_channel_is_pruned_once_it_runs_empty(broadcaster) -> None:
    ws = _FakeWebSocket()
    await broadcaster.connect("kb-demo", ws)

    await broadcaster.disconnect("kb-demo", ws)

    assert broadcaster.get_connection_count("kb-demo") == 0
    assert "kb-demo" not in ProgressBroadcaster._connections


@pytest.mark.asyncio
async def test_disconnect_of_unknown_socket_or_channel_is_harmless(broadcaster) -> None:
    stranger = _FakeWebSocket()

    await broadcaster.disconnect("no-such-kb", stranger)

    assert broadcaster.get_connection_count("no-such-kb") == 0


@pytest.mark.asyncio
async def test_broadcast_without_subscribers_is_a_noop(broadcaster) -> None:
    await broadcaster.broadcast("kb-demo", {"stage": "parsing"})

    assert broadcaster.get_connection_count("kb-demo") == 0


# ---------------------------------------------------------------------------
# Singleton lifecycle
# ---------------------------------------------------------------------------


def test_get_instance_returns_the_same_singleton() -> None:
    _reset_broadcaster_state()
    try:
        assert ProgressBroadcaster.get_instance() is ProgressBroadcaster.get_instance()
    finally:
        _reset_broadcaster_state()
