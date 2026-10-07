"""Subscription-lifecycle contract for the API progress broadcaster.

``deeptutor.api.utils.progress_broadcaster.ProgressBroadcaster`` tracks
WebSocket subscribers per knowledge-base channel. These tests pin the
subscription lifecycle:

* connect registers a subscriber and duplicate connects are idempotent,
* disconnect stops future delivery for that socket and prunes empty channels,
* broadcast fans out exactly one frame per active subscriber,
* a failing socket is isolated: surviving subscribers and other channels are
  unaffected, and the dropped socket is never retried.

Pure logic tests with a fake WebSocket; no server or real sockets involved.
"""

from __future__ import annotations

import asyncio

import pytest

from deeptutor.api.utils.progress_broadcaster import ProgressBroadcaster


class _FakeWebSocket:
    def __init__(self, send_error: Exception | None = None) -> None:
        self.frames: list[dict] = []
        self.send_calls = 0
        self._send_error = send_error

    async def send_json(self, payload: dict) -> None:
        self.send_calls += 1
        if self._send_error is not None:
            raise self._send_error
        self.frames.append(payload)


def _reset_state() -> None:
    ProgressBroadcaster._instance = None
    ProgressBroadcaster._connections = {}
    # The class-level lock binds to the loop that first awaits it; a fresh
    # lock per test keeps each test on its own function-scoped event loop.
    ProgressBroadcaster._lock = asyncio.Lock()


@pytest.fixture
def broadcaster():
    _reset_state()
    yield ProgressBroadcaster()
    _reset_state()


@pytest.mark.asyncio
async def test_connect_registers_subscriber_and_updates_count(broadcaster) -> None:
    first = _FakeWebSocket()
    second = _FakeWebSocket()

    await broadcaster.connect("kb-demo", first)
    assert broadcaster.get_connection_count("kb-demo") == 1

    await broadcaster.connect("kb-demo", second)
    assert broadcaster.get_connection_count("kb-demo") == 2
    assert broadcaster.get_connection_count("kb-other") == 0


@pytest.mark.asyncio
async def test_duplicate_connect_of_same_socket_is_idempotent(broadcaster) -> None:
    ws = _FakeWebSocket()

    await broadcaster.connect("kb-demo", ws)
    await broadcaster.connect("kb-demo", ws)

    assert broadcaster.get_connection_count("kb-demo") == 1

    await broadcaster.broadcast("kb-demo", {"stage": "parsing"})

    assert ws.frames == [{"type": "progress", "data": {"stage": "parsing"}}]


@pytest.mark.asyncio
async def test_disconnect_stops_future_delivery_for_that_socket(broadcaster) -> None:
    staying = _FakeWebSocket()
    leaving = _FakeWebSocket()
    await broadcaster.connect("kb-demo", staying)
    await broadcaster.connect("kb-demo", leaving)

    await broadcaster.disconnect("kb-demo", leaving)
    assert broadcaster.get_connection_count("kb-demo") == 1

    await broadcaster.broadcast("kb-demo", {"stage": "after-leave"})

    assert staying.frames == [{"type": "progress", "data": {"stage": "after-leave"}}]
    assert leaving.frames == []


@pytest.mark.asyncio
async def test_disconnect_of_last_subscriber_prunes_channel_entry(broadcaster) -> None:
    ws = _FakeWebSocket()
    await broadcaster.connect("kb-demo", ws)

    await broadcaster.disconnect("kb-demo", ws)

    assert broadcaster.get_connection_count("kb-demo") == 0
    assert "kb-demo" not in ProgressBroadcaster._connections


@pytest.mark.asyncio
async def test_resubscribe_after_disconnect_resumes_delivery(broadcaster) -> None:
    ws = _FakeWebSocket()
    await broadcaster.connect("kb-demo", ws)
    await broadcaster.broadcast("kb-demo", {"stage": "before"})
    await broadcaster.disconnect("kb-demo", ws)

    await broadcaster.broadcast("kb-demo", {"stage": "while-away"})
    await broadcaster.connect("kb-demo", ws)
    await broadcaster.broadcast("kb-demo", {"stage": "after-return"})

    assert [f["data"]["stage"] for f in ws.frames] == ["before", "after-return"]


@pytest.mark.asyncio
async def test_late_subscriber_receives_only_frames_after_subscribing(broadcaster) -> None:
    early = _FakeWebSocket()
    late = _FakeWebSocket()
    await broadcaster.connect("kb-demo", early)
    await broadcaster.broadcast("kb-demo", {"stage": 1})

    await broadcaster.connect("kb-demo", late)
    await broadcaster.broadcast("kb-demo", {"stage": 2})

    assert [f["data"]["stage"] for f in early.frames] == [1, 2]
    assert [f["data"]["stage"] for f in late.frames] == [2]


@pytest.mark.asyncio
async def test_broadcast_fans_out_one_frame_per_active_subscriber(broadcaster) -> None:
    sockets = [_FakeWebSocket() for _ in range(4)]
    for ws in sockets:
        await broadcaster.connect("kb-demo", ws)

    await broadcaster.broadcast("kb-demo", {"stage": "fanout"})

    for ws in sockets:
        assert ws.send_calls == 1
        assert ws.frames == [{"type": "progress", "data": {"stage": "fanout"}}]
    assert broadcaster.get_connection_count("kb-demo") == 4


@pytest.mark.asyncio
async def test_failing_socket_does_not_block_same_channel_survivors(broadcaster) -> None:
    broken = _FakeWebSocket(send_error=RuntimeError("connection closed"))
    healthy = _FakeWebSocket()
    await broadcaster.connect("kb-demo", broken)
    await broadcaster.connect("kb-demo", healthy)

    await broadcaster.broadcast("kb-demo", {"stage": "one"})

    assert healthy.frames == [{"type": "progress", "data": {"stage": "one"}}]
    assert broadcaster.get_connection_count("kb-demo") == 1


@pytest.mark.asyncio
async def test_failing_socket_does_not_block_other_channels(broadcaster) -> None:
    broken = _FakeWebSocket(send_error=RuntimeError("connection closed"))
    other_kb = _FakeWebSocket()
    await broadcaster.connect("kb-broken", broken)
    await broadcaster.connect("kb-healthy", other_kb)

    await broadcaster.broadcast("kb-broken", {"stage": "x"})

    assert other_kb.send_calls == 0
    assert "kb-broken" not in ProgressBroadcaster._connections

    await broadcaster.broadcast("kb-healthy", {"stage": "y"})
    assert other_kb.frames == [{"type": "progress", "data": {"stage": "y"}}]


@pytest.mark.asyncio
async def test_dropped_socket_is_not_retried_on_later_broadcasts(broadcaster) -> None:
    broken = _FakeWebSocket(send_error=RuntimeError("connection closed"))
    healthy = _FakeWebSocket()
    await broadcaster.connect("kb-demo", broken)
    await broadcaster.connect("kb-demo", healthy)

    await broadcaster.broadcast("kb-demo", {"stage": 1})
    await broadcaster.broadcast("kb-demo", {"stage": 2})

    assert broken.send_calls == 1
    assert [f["data"]["stage"] for f in healthy.frames] == [1, 2]


@pytest.mark.asyncio
async def test_concurrent_connects_are_all_registered_for_broadcast(broadcaster) -> None:
    sockets = [_FakeWebSocket() for _ in range(5)]

    await asyncio.gather(*(broadcaster.connect("kb-demo", ws) for ws in sockets))

    assert broadcaster.get_connection_count("kb-demo") == 5
    await broadcaster.broadcast("kb-demo", {"stage": "final"})
    for ws in sockets:
        assert ws.send_calls == 1
