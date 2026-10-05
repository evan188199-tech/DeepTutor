from __future__ import annotations

import asyncio

import pytest

from deeptutor.api.utils.progress_broadcaster import ProgressBroadcaster


class FakeWebSocket:
    """Minimal WebSocket stand-in recording sent frames."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.block_send: asyncio.Event | None = None

    async def send_json(self, payload: dict) -> None:
        if self.block_send is not None:
            await self.block_send.wait()
        self.sent.append(payload)


class BrokenWebSocket(FakeWebSocket):
    async def send_json(self, payload: dict) -> None:
        raise RuntimeError("connection closed")


@pytest.fixture()
def broadcaster() -> ProgressBroadcaster:
    ProgressBroadcaster._instance = None
    ProgressBroadcaster._connections = {}
    ProgressBroadcaster._lock = asyncio.Lock()
    instance = ProgressBroadcaster.get_instance()
    assert instance is not None
    return instance


@pytest.mark.asyncio
async def test_slow_client_does_not_block_other_kbs_or_lifecycle(
    broadcaster: ProgressBroadcaster,
) -> None:
    slow = FakeWebSocket()
    slow.block_send = asyncio.Event()
    fast = FakeWebSocket()

    await broadcaster.connect("stuck-kb", slow)
    await broadcaster.connect("live-kb", fast)

    blocked = asyncio.create_task(broadcaster.broadcast("stuck-kb", {"stage": "working"}))
    try:
        await asyncio.sleep(0.1)

        # Another KB's broadcast must complete while the slow send is in flight.
        await asyncio.wait_for(
            broadcaster.broadcast("live-kb", {"stage": "processing"}), timeout=1.0
        )
        assert fast.sent == [{"type": "progress", "data": {"stage": "processing"}}]

        # connect/disconnect must not be blocked either.
        extra = FakeWebSocket()
        await asyncio.wait_for(broadcaster.connect("live-kb", extra), timeout=1.0)
        await asyncio.wait_for(broadcaster.disconnect("live-kb", extra), timeout=1.0)
    finally:
        slow.block_send.set()
        await asyncio.wait_for(blocked, timeout=1.0)

    assert slow.sent == [{"type": "progress", "data": {"stage": "working"}}]


@pytest.mark.asyncio
async def test_broadcast_removes_failing_connection_and_keeps_message_shape(
    broadcaster: ProgressBroadcaster,
) -> None:
    failing = BrokenWebSocket()
    ok = FakeWebSocket()
    await broadcaster.connect("kb", failing)
    await broadcaster.connect("kb", ok)

    await broadcaster.broadcast("kb", {"progress_percent": 42})

    assert ok.sent == [{"type": "progress", "data": {"progress_percent": 42}}]
    assert broadcaster.get_connection_count("kb") == 1

    # The failing socket is gone: a later broadcast only reaches the healthy one.
    await broadcaster.broadcast("kb", {"progress_percent": 84})
    assert ok.sent == [
        {"type": "progress", "data": {"progress_percent": 42}},
        {"type": "progress", "data": {"progress_percent": 84}},
    ]


@pytest.mark.asyncio
async def test_broadcast_without_connections_is_noop(broadcaster: ProgressBroadcaster) -> None:
    await asyncio.wait_for(broadcaster.broadcast("missing-kb", {"stage": "working"}), timeout=1.0)
    assert broadcaster.get_connection_count("missing-kb") == 0
    assert ProgressBroadcaster._connections == {}
