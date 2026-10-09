"""Contract tests for TurnEventJournal publication, batching, and replay.

Covers the assembly clamps of ``TurnEventJournal``, the publish-then-buffer
ordering contract, batch/interval driven flushes, flush failure restore and
retry, the terminal gap-fill against the durable store, and replay merge and
conflict detection. All collaborators are in-memory fakes: no network, no
real coordinator or repository is required.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from deeptutor.runtime.coordination.journal import TurnEventJournal
from deeptutor.runtime.coordination.types import TurnLease

TURN_ID = "turn-1"


def make_lease(fencing_token: int = 7) -> TurnLease:
    return TurnLease(
        turn_id=TURN_ID,
        session_id="session-1",
        owner_id="worker-a",
        fencing_token=fencing_token,
        expires_at=time.time() + 30,
    )


def ev(seq: int, **fields: Any) -> dict[str, Any]:
    event = {"type": "content", "turn_id": TURN_ID, "seq": seq}
    event.update(fields)
    return event


class FakeCoordinator:
    """In-memory stand-in for the shared live-event stream."""

    def __init__(self) -> None:
        self._events: dict[str, list[dict[str, Any]]] = {}
        self.publish_calls: list[tuple[str, dict[str, Any]]] = []
        self.publish_error: Exception | None = None

    async def publish_event(self, turn_id: str, event: dict[str, Any]) -> dict[str, Any]:
        self.publish_calls.append((turn_id, dict(event)))
        if self.publish_error is not None:
            raise self.publish_error
        rows = self._events.setdefault(turn_id, [])
        payload = dict(event)
        seq = int(payload.get("seq") or 0)
        if seq <= 0:
            seq = (int(rows[-1]["seq"]) if rows else 0) + 1
        payload["turn_id"] = payload.get("turn_id") or turn_id
        payload["seq"] = seq
        rows.append(payload)
        return dict(payload)

    async def read_events(self, turn_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
        return [
            dict(event)
            for event in self._events.get(turn_id, [])
            if int(event["seq"]) > max(0, int(after_seq))
        ]


class FakeRepository:
    """In-memory stand-in for the durable turn-event repository."""

    def __init__(self) -> None:
        self.durable: dict[str, list[dict[str, Any]]] = {}
        self.append_calls: list[dict[str, Any]] = []
        self.append_error: Exception | None = None
        self.on_append: Any = None

    async def append_events(
        self, turn_id: str, events: list[dict[str, Any]], fencing_token: int | None = None
    ) -> None:
        self.append_calls.append(
            {
                "turn_id": turn_id,
                "events": [dict(event) for event in events],
                "fencing_token": fencing_token,
            }
        )
        if self.on_append is not None:
            self.on_append()
        if self.append_error is not None:
            raise self.append_error
        self.durable.setdefault(turn_id, []).extend(dict(event) for event in events)

    async def get_events(self, turn_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
        return [
            dict(event)
            for event in self.durable.get(turn_id, [])
            if int(event["seq"]) > max(0, int(after_seq))
        ]


def make_journal(
    coordinator: FakeCoordinator | None = None,
    repository: FakeRepository | None = None,
    *,
    fencing_token: int = 7,
    **kwargs: Any,
) -> tuple[TurnEventJournal, FakeCoordinator, FakeRepository]:
    coordinator = coordinator or FakeCoordinator()
    repository = repository or FakeRepository()
    journal = TurnEventJournal(coordinator, repository, make_lease(fencing_token), **kwargs)
    return journal, coordinator, repository


@pytest.mark.asyncio
async def test_constructor_clamps_invalid_batch_size_and_interval() -> None:
    journal, _, _ = make_journal(batch_size=0, flush_interval_seconds=-5)
    assert journal.batch_size == 1
    assert journal.flush_interval_seconds == 0.01

    journal, _, _ = make_journal(batch_size=-3, flush_interval_seconds=0)
    assert journal.batch_size == 1
    assert journal.flush_interval_seconds == 0.01

    journal, _, _ = make_journal(batch_size=2.9, flush_interval_seconds=0.5)
    assert journal.batch_size == 2
    assert journal.flush_interval_seconds == 0.5


@pytest.mark.asyncio
async def test_publish_propagates_stream_failure_without_buffering() -> None:
    journal, coordinator, repository = make_journal()
    coordinator.publish_error = RuntimeError("stream down")

    with pytest.raises(RuntimeError, match="stream down"):
        await journal.publish({"type": "content", "content": "lost"})

    assert await coordinator.read_events(TURN_ID) == []
    assert repository.append_calls == []
    assert journal._pending == []


@pytest.mark.asyncio
async def test_publish_buffers_persisted_copy_and_returns_it() -> None:
    journal, coordinator, repository = make_journal(batch_size=100, flush_interval_seconds=60)

    raw = {"type": "content", "content": "hello"}
    persisted = await journal.publish(raw)

    assert persisted["turn_id"] == TURN_ID
    assert persisted["seq"] == 1
    assert await coordinator.read_events(TURN_ID) == [persisted]
    assert journal._pending == [persisted]
    raw["content"] = "mutated"
    assert journal._pending[0]["content"] == "hello"
    assert repository.append_calls == []


@pytest.mark.asyncio
async def test_publish_auto_flushes_when_batch_size_reached() -> None:
    journal, coordinator, repository = make_journal(batch_size=2, flush_interval_seconds=60)

    first = await journal.publish({"type": "content", "content": "a"})
    assert repository.append_calls == []

    second = await journal.publish({"type": "content", "content": "b"})
    assert len(repository.append_calls) == 1
    call = repository.append_calls[0]
    assert call["turn_id"] == TURN_ID
    assert call["events"] == [first, second]
    assert call["fencing_token"] == 7
    assert journal._pending == []
    assert await repository.get_events(TURN_ID) == [first, second]


@pytest.mark.asyncio
async def test_publish_auto_flushes_when_interval_elapsed() -> None:
    journal, _, repository = make_journal(batch_size=100, flush_interval_seconds=0.05)

    first = await journal.publish({"type": "content", "content": "a"})
    assert repository.append_calls == []

    journal._last_flush = time.monotonic() - 1
    second = await journal.publish({"type": "content", "content": "b"})
    assert len(repository.append_calls) == 1
    assert repository.append_calls[0]["events"] == [first, second]
    assert journal._pending == []

    third = await journal.publish({"type": "content", "content": "c"})
    assert len(repository.append_calls) == 1
    assert journal._pending == [third]


@pytest.mark.asyncio
async def test_flush_without_pending_returns_zero_and_skips_repository() -> None:
    journal, _, repository = make_journal()
    baseline_flush = journal._last_flush

    assert await journal.flush() == 0
    assert repository.append_calls == []
    assert journal._last_flush == baseline_flush


@pytest.mark.asyncio
async def test_flush_sends_batch_with_fencing_token_and_clears_pending() -> None:
    journal, _, repository = make_journal(batch_size=100, flush_interval_seconds=60)

    events = [await journal.publish({"type": "content", "content": str(i)}) for i in range(3)]

    assert await journal.flush() == 3
    assert repository.append_calls[0]["events"] == events
    assert repository.append_calls[0]["fencing_token"] == 7
    assert journal._pending == []
    assert await journal.flush() == 0
    assert len(repository.append_calls) == 1


@pytest.mark.asyncio
async def test_flush_failure_restores_pending_order_and_retry_succeeds() -> None:
    journal, coordinator, repository = make_journal(batch_size=100, flush_interval_seconds=60)

    first = await journal.publish({"type": "content", "content": "a"})
    second = await journal.publish({"type": "content", "content": "b"})
    repository.append_error = RuntimeError("durable store down")
    with pytest.raises(RuntimeError, match="durable store down"):
        await journal.flush()

    assert [event["content"] for event in journal._pending] == ["a", "b"]
    assert await coordinator.read_events(TURN_ID) == [first, second]
    assert repository.durable.get(TURN_ID) is None

    repository.append_error = None
    assert await journal.flush() == 2
    assert repository.append_calls[-1]["events"] == [first, second]
    assert await repository.get_events(TURN_ID) == [first, second]
    assert journal._pending == []


@pytest.mark.asyncio
async def test_flush_failure_merge_keeps_restored_events_before_concurrent_ones() -> None:
    journal, _, repository = make_journal(batch_size=100, flush_interval_seconds=60)

    first = await journal.publish({"type": "content", "content": "a"})
    second = await journal.publish({"type": "content", "content": "b"})

    concurrent = ev(3, content="c")

    def simulate_concurrent_publish() -> None:
        journal._pending.append(dict(concurrent))

    repository.on_append = simulate_concurrent_publish
    repository.append_error = RuntimeError("durable store down")
    with pytest.raises(RuntimeError, match="durable store down"):
        await journal.flush()
    repository.on_append = None
    repository.append_error = None

    assert [event["content"] for event in journal._pending] == ["a", "b", "c"]
    assert await journal.flush() == 3
    assert repository.append_calls[-1]["events"] == [first, second, concurrent]


@pytest.mark.asyncio
async def test_flush_terminal_appends_missing_live_events_after_durable_seq() -> None:
    journal, coordinator, repository = make_journal()

    await repository.append_events(TURN_ID, [ev(1, content="durable")], fencing_token=7)
    live_second = ev(2, content="live-2")
    live_third = ev(3, content="live-3")
    coordinator._events[TURN_ID] = [
        ev(1, content="durable"),
        live_second,
        live_third,
    ]

    assert await journal.flush_terminal() == 2
    assert repository.append_calls[-1]["events"] == [live_second, live_third]
    assert repository.append_calls[-1]["fencing_token"] == 7
    assert [event["seq"] for event in await repository.get_events(TURN_ID)] == [1, 2, 3]


@pytest.mark.asyncio
async def test_flush_terminal_returns_zero_when_durable_covers_stream() -> None:
    journal, coordinator, repository = make_journal()

    durable = [ev(1, content="a"), ev(2, content="b")]
    await repository.append_events(TURN_ID, durable, fencing_token=7)
    coordinator._events[TURN_ID] = [dict(event) for event in durable]

    assert await journal.flush_terminal() == 0
    assert len(repository.append_calls) == 1


@pytest.mark.asyncio
async def test_replay_merges_durable_and_live_sorted_by_seq() -> None:
    journal, coordinator, repository = make_journal()

    await repository.append_events(
        TURN_ID, [ev(2, content="two"), ev(1, content="one")], fencing_token=7
    )
    coordinator._events[TURN_ID] = [
        ev(1, content="one"),
        ev(2, content="two"),
        ev(3, content="three"),
    ]

    replayed = await journal.replay()
    assert [event["seq"] for event in replayed] == [1, 2, 3]
    assert replayed[2]["content"] == "three"

    tail = await journal.replay(after_seq=2)
    assert [event["seq"] for event in tail] == [3]


@pytest.mark.asyncio
async def test_replay_uses_live_copy_for_seqs_missing_from_durable() -> None:
    journal, coordinator, repository = make_journal()

    await repository.append_events(TURN_ID, [ev(1, content="one")], fencing_token=7)
    live_only = ev(2, content="live-two")
    coordinator._events[TURN_ID] = [ev(1, content="one"), live_only]

    replayed = await journal.replay()
    assert replayed == [ev(1, content="one"), live_only]


@pytest.mark.asyncio
async def test_replay_rejects_conflicting_live_event_for_durable_seq() -> None:
    journal, coordinator, repository = make_journal()

    await repository.append_events(TURN_ID, [ev(1, content="one")], fencing_token=7)
    coordinator._events[TURN_ID] = [ev(1, content="tampered")]

    with pytest.raises(ValueError, match="Turn event conflict"):
        await journal.replay()


@pytest.mark.asyncio
async def test_replay_tolerates_untracked_field_drift() -> None:
    journal, coordinator, repository = make_journal()

    durable = ev(1, content="one")
    durable["trace_id"] = "abc"
    await repository.append_events(TURN_ID, [durable], fencing_token=7)
    live = ev(1, content="one")
    coordinator._events[TURN_ID] = [live]

    replayed = await journal.replay()
    assert replayed == [live]
