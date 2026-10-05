"""Regression net for the consolidator wait–wake contract.

Locks the behavior of :meth:`RunManager.wait_for_events`
(``deeptutor/services/memory/consolidator/runs.py``) around the waiter
registry (``Run._waiters``):

* every exit path (wake-by-event, quiet run completion, cancellation)
  must remove the waiter exactly once and leave ``run._waiters`` clean;
* a blocked waiter must wake exactly once per wake-up, even when several
  events are emitted back to back (duplicate emits coalesce into a single
  ``Event.set`` — no duplicate resume, no stale entry);
* a waiter must never hang: a quiet run completion or an already finished
  run returns promptly;
* events a waiter is blocked for must never be silently dropped, even if
  the event ring wraps while it waits (currently fails — see the
  ``xfail`` test at the bottom; scan finding
  ``runs.py`` ``wait_for_events`` silent ``except ValueError: pass``).

These tests intentionally do not touch product code: they are the
acceptance net for the follow-up fix card.
"""

from __future__ import annotations

import asyncio
import time

import pytest

import deeptutor.services.memory.consolidator.runs as runs_module
from deeptutor.services.memory.consolidator.runs import RunManager


@pytest.fixture()
def manager() -> RunManager:
    return RunManager()


async def _start_gated_run(
    manager: RunManager,
    started: asyncio.Event,
    release: asyncio.Event,
    *,
    key: str = "chat",
    burst: int = 0,
):
    """Start a run that pauses on ``release`` and then emits ``burst`` events."""

    async def runner(on_event):
        started.set()
        await release.wait()
        for i in range(burst):
            await on_event({"stage": "progress", "i": i})

    run = await manager.start(layer="L2", key=key, mode="update", runner=runner)
    await asyncio.wait_for(started.wait(), timeout=2)
    return run


# ---------------------------------------------------------------------------
# Duplicate / exactly-once removal (waiter registry hygiene)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_waiter_removed_once_after_wake_by_event(manager: RunManager) -> None:
    started, release = asyncio.Event(), asyncio.Event()
    run = await _start_gated_run(manager, started, release, burst=1)

    cursor = run._next_seq
    task = asyncio.create_task(manager.wait_for_events(run, since=cursor))
    await asyncio.sleep(0.05)
    assert len(run._waiters) == 1  # blocked waiter registered

    release.set()
    events = await asyncio.wait_for(task, timeout=2)

    assert [event.seq for event in events] == [cursor, cursor + 1]
    assert run._waiters == []


@pytest.mark.asyncio
async def test_two_waiters_wake_once_each_on_single_emit(manager: RunManager) -> None:
    started, release = asyncio.Event(), asyncio.Event()
    run = await _start_gated_run(manager, started, release, burst=1)

    cursor = run._next_seq
    task_a = asyncio.create_task(manager.wait_for_events(run, since=cursor))
    task_b = asyncio.create_task(manager.wait_for_events(run, since=cursor))
    await asyncio.sleep(0.05)
    assert len(run._waiters) == 2

    release.set()
    events_a = await asyncio.wait_for(task_a, timeout=2)
    events_b = await asyncio.wait_for(task_b, timeout=2)

    assert [event.seq for event in events_a] == [event.seq for event in events_b]
    assert run._waiters == []


@pytest.mark.asyncio
async def test_repeated_cancel_of_waiter_does_not_leak_registry(
    manager: RunManager,
) -> None:
    for attempt in range(5):
        started, release = asyncio.Event(), asyncio.Event()
        run = await _start_gated_run(manager, started, release, key=f"chat-{attempt}", burst=0)

        cursor = run._next_seq
        task = asyncio.create_task(manager.wait_for_events(run, since=cursor))
        await asyncio.sleep(0.02)
        assert len(run._waiters) == 1

        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert run._waiters == []  # no leak per attach/cancel cycle

        release.set()
        await asyncio.gather(run._task, return_exceptions=True)


@pytest.mark.asyncio
async def test_duplicate_emit_coalesces_to_single_wake_and_single_removal(
    manager: RunManager,
) -> None:
    started, release = asyncio.Event(), asyncio.Event()
    run = await _start_gated_run(manager, started, release, burst=3)

    cursor = run._next_seq
    task = asyncio.create_task(manager.wait_for_events(run, since=cursor))
    await asyncio.sleep(0.05)

    release.set()
    events = await asyncio.wait_for(task, timeout=2)

    # Three back-to-back emits set the same waiter repeatedly; the waiter
    # must resume exactly once and observe every missed event exactly once.
    assert [event.seq for event in events] == list(range(cursor, cursor + 4))
    assert run._waiters == []


# ---------------------------------------------------------------------------
# Wake after event arrival (cursor semantics)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blocked_waiter_wakes_on_new_event_with_cursor_semantics(
    manager: RunManager,
) -> None:
    started, release = asyncio.Event(), asyncio.Event()
    run = await _start_gated_run(manager, started, release, burst=1)

    cursor = run._next_seq  # nothing buffered at or above the cursor yet
    assert [event.seq for event in run.events if event.seq >= cursor] == []

    task = asyncio.create_task(manager.wait_for_events(run, since=cursor))
    await asyncio.sleep(0.05)
    release.set()

    events = await asyncio.wait_for(task, timeout=2)
    assert [event.seq for event in events] == [cursor, cursor + 1]
    assert events[0].payload["stage"] == "progress"
    assert events[-1].payload["stage"] == "run_ended"
    assert run._waiters == []


# ---------------------------------------------------------------------------
# No-event / quiet completion must return, never hang
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quiet_run_completion_returns_promptly_without_hang(
    manager: RunManager,
) -> None:
    started, release = asyncio.Event(), asyncio.Event()
    run = await _start_gated_run(manager, started, release, burst=0)

    cursor = run._next_seq
    task = asyncio.create_task(manager.wait_for_events(run, since=cursor))
    await asyncio.sleep(0.05)

    loop = asyncio.get_running_loop()
    begin = loop.time()
    release.set()
    events = await asyncio.wait_for(task, timeout=2)
    elapsed = loop.time() - begin

    assert elapsed < 1.5  # terminal wake must be prompt, not timer-driven
    assert run.active is False
    assert [event.payload["stage"] for event in events][-1] == "run_ended"
    assert run._waiters == []


@pytest.mark.asyncio
async def test_done_run_returns_immediately_empty_for_future_cursor(
    manager: RunManager,
) -> None:
    async def runner(on_event):
        await on_event({"stage": "progress"})

    run = await manager.start(layer="L2", key="chat", mode="update", runner=runner)
    await asyncio.gather(run._task)
    assert run.active is False

    loop = asyncio.get_running_loop()
    begin = loop.time()
    events = await asyncio.wait_for(manager.wait_for_events(run, since=10**9), timeout=1)
    assert events == []  # no buffered events past the cursor, run inactive

    replay = await asyncio.wait_for(manager.wait_for_events(run, since=-5), timeout=1)
    assert [event.seq for event in replay] == list(range(run._next_seq))
    assert loop.time() - begin < 1.0


# ---------------------------------------------------------------------------
# Ring-wrap must not silently drop missed events (currently failing)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    reason=(
        "wait_for_events silently drops events between the waiter's cursor "
        "and the ring head when the event ring wraps while it waits; the "
        "waiter then resumes believing nothing was missed. Related to the "
        "runs.py wait_for_events waiter-hygiene finding."
    ),
)
async def test_ring_wrap_while_blocked_does_not_drop_missed_events(
    manager: RunManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runs_module, "_MAX_EVENTS_PER_RUN", 3)

    started, release = asyncio.Event(), asyncio.Event()
    run = await _start_gated_run(manager, started, release, key="chat", burst=5)

    cursor = 1  # waiter attached before the burst: seqs 1.. must be replayed
    task = asyncio.create_task(manager.wait_for_events(run, since=cursor))
    await asyncio.sleep(0.05)

    release.set()
    events = await asyncio.wait_for(task, timeout=2)
    got = [event.seq for event in events]

    # Contract: a wake must never skip silently. With the ring capped at 3
    # and six events emitted (5 burst + run_ended), seqs 1..3 were evicted
    # while the waiter was blocked; returning only the retained tail
    # [4, 5, 6] silently pretends 1..3 never happened.
    assert got == list(range(cursor, run._next_seq))
