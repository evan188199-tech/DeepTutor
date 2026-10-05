"""Regression tests for the ``TurnLifecycle.cancel_turn`` confirmation contract.

``cancel_turn`` (``deeptutor/services/session/turns/lifecycle.py``) cancels the
turn task and then awaits it inside ``except asyncio.CancelledError: pass``,
so whatever the task actually did — persist a terminal row, or absorb the
cancellation and vanish — is invisible to the caller: the method reports
``True`` either way. These tests pin down what a successful cancellation must
guarantee before it may report success:

* the durable turn row ends terminal (``cancelled``), never left ``running``;
* in-memory execution bookkeeping agrees with the durable row;
* repeated cancels are idempotent and never corrupt the terminal row;
* late waiter restores and in-flight events during the unwind cannot revive
  the cancelled turn.

The task bodies below mirror the task-side contract of
``TurnExecutor._run_turn``: a cooperative turn writes its terminal row (the
same dual-predecessor CAS as ``_transition_execution``) and re-raises, and its
``finally`` always unregisters the execution. The swallowing-turn cases are
the pathological variant whose silent outcome the current implementation
cannot see; they fail on the baseline and are the acceptance criteria for the
upcoming fix.
"""

from __future__ import annotations

import asyncio
import contextlib
from types import SimpleNamespace

import pytest

from deeptutor.services.session._turn_runtime_shared import (
    _LiveSubscriber,
    _TurnExecution,
)
from deeptutor.services.session.protocol import ActiveTurnConflict
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turns.lifecycle import TurnLifecycle

_SESSION_ID = "session-1"


async def _make_lifecycle(tmp_path, *, coordinator: SimpleNamespace | None = None):
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    lifecycle = TurnLifecycle(
        store=store,
        coordinator=coordinator,
        turn_engine=SimpleNamespace(),
    )
    return lifecycle, store


async def _register_turn(
    lifecycle: TurnLifecycle,
    store: SQLiteSessionStore,
    *,
    session_id: str = _SESSION_ID,
    capability: str = "chat",
) -> tuple[dict, _TurnExecution]:
    """Mirror ``start_turn``: create the running row, then the placeholder."""
    if await store.get_session(session_id) is None:
        await store.create_session(session_id=session_id)
    turn = await store.begin_turn(session_id, capability=capability)
    execution = _TurnExecution(
        turn_id=turn["id"],
        session_id=session_id,
        capability=capability,
        payload={"type": "start_turn", "session_id": session_id, "content": "hello"},
    )
    async with lifecycle._lock:
        lifecycle._executions[turn["id"]] = execution
    return turn, execution


async def _terminal_cancelled_write(store: SQLiteSessionStore, turn_id: str) -> bool:
    """The same dual-predecessor CAS ``_transition_execution`` performs."""
    for expected in ("running", "waiting_input"):
        if await store.transition_turn(
            turn_id, "cancelled", expected_status=expected, error="Turn cancelled"
        ):
            return True
    return False


async def _settle_ticks(count: int = 3) -> None:
    for _ in range(count):
        await asyncio.sleep(0)


def _cooperative_turn_body(
    lifecycle: TurnLifecycle,
    execution: _TurnExecution,
    store: SQLiteSessionStore,
    release: asyncio.Event,
    *,
    park: bool = False,
    emit_late_event: bool = False,
):
    """A faithful stand-in for ``_run_turn``'s cancellation contract.

    Optionally parks the turn at ``waiting_input`` (the ``ask_user`` pause)
    and/or emits a late live event to the execution's buffers and subscribers
    before the terminal write.
    """
    turn_id = execution.turn_id

    async def body() -> None:
        try:
            if park:
                entered = await store.transition_turn(
                    turn_id, "waiting_input", expected_status="running"
                )
                assert entered, "fixture: park transition must succeed"
            subscriber_queue = None
            if execution.subscribers:
                subscriber_queue = execution.subscribers[0].queue
            try:
                await release.wait()
            except asyncio.CancelledError:
                if emit_late_event:
                    event = {
                        "type": "delta",
                        "source": "chat",
                        "content": "late event during unwind",
                        "seq": execution.next_seq,
                    }
                    execution.next_seq += 1
                    execution.events.append(event)
                    if subscriber_queue is not None:
                        subscriber_queue.put_nowait(event)
                with contextlib.suppress(Exception):
                    await _terminal_cancelled_write(store, turn_id)
                raise
        finally:
            async with lifecycle._lock:
                current = lifecycle._executions.get(turn_id)
                if current is not None:
                    for subscriber in current.subscribers:
                        with contextlib.suppress(asyncio.QueueFull):
                            subscriber.queue.put_nowait(None)
                    lifecycle._executions.pop(turn_id, None)

    return body()


def _swallowing_turn_body(
    lifecycle: TurnLifecycle,
    execution: _TurnExecution,
    release: asyncio.Event,
):
    """The pathological turn body: absorbs cancellation, persists nothing.

    The real pipeline guards against most of this, but any turn coroutine that
    suppresses ``CancelledError`` (shield patterns, third-party tool code)
    produces exactly this outcome — and ``cancel_turn`` must still be able to
    observe it instead of reporting a blind ``True``.
    """
    turn_id = execution.turn_id

    async def body() -> None:
        try:
            try:
                await release.wait()
            except asyncio.CancelledError:
                pass
        finally:
            async with lifecycle._lock:
                lifecycle._executions.pop(turn_id, None)

    return body()


async def _settle_task(execution: _TurnExecution, release: asyncio.Event) -> None:
    release.set()
    task = execution.task
    if task is not None and not task.done():
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task


@pytest.mark.asyncio
async def test_cancel_confirms_terminal_state_when_task_swallows_cancellation(
    tmp_path,
) -> None:
    """A ``True`` return must imply the durable row reached a terminal state.

    The awaited task absorbs the cancellation and returns without persisting
    anything. ``cancel_turn`` still reports ``True`` while the row stays
    ``running``, so the session keeps an "active" turn forever — every later
    message in the session is refused with "Session already has an active
    turn". The caller must be able to trust the ``True``.
    """
    lifecycle, store = await _make_lifecycle(tmp_path)
    release = asyncio.Event()
    turn, execution = await _register_turn(lifecycle, store)
    execution.task = asyncio.create_task(_swallowing_turn_body(lifecycle, execution, release))
    try:
        await _settle_ticks()
        assert not execution.task.done(), "fixture: task must be parked"

        settled = await lifecycle.cancel_turn(turn["id"])

        assert settled is True
        row = await store.get_turn(turn["id"])
        assert row is not None
        # Fails on baseline: the row is still "running" because the task
        # swallowed the cancellation and the confirmation was swallowed with
        # it (lifecycle.py: ``except asyncio.CancelledError: pass``).
        assert row["status"] == "cancelled"
        assert await store.get_active_turn(_SESSION_ID) is None
        with pytest.raises(ActiveTurnConflict):
            await store.begin_turn(_SESSION_ID, capability="chat")
    finally:
        await _settle_task(execution, release)


@pytest.mark.asyncio
async def test_cancel_converges_memory_and_durable_state_for_taskless_execution(
    tmp_path,
) -> None:
    """Cancelling a task-less execution must not split memory from the store.

    A placeholder without a task (paused between setup and execution) is
    treated as not-live by the cancel fallback, which flips the durable row to
    ``cancelled`` and reports ``True`` — but the execution stays registered,
    so ``has_live_execution`` keeps reporting a live turn that the store says
    is cancelled. A ``True`` return must leave the two views agreeing.
    """
    lifecycle, store = await _make_lifecycle(tmp_path)
    turn, execution = await _register_turn(lifecycle, store)
    assert execution.task is None

    settled = await lifecycle.cancel_turn(turn["id"])

    row = await store.get_turn(turn["id"])
    assert row is not None
    if settled:
        assert row["status"] == "cancelled"
        # Fails on baseline: the placeholder was never unregistered, so the
        # in-memory view still claims the cancelled turn is live.
        assert not await lifecycle.has_live_execution(turn["id"])
        assert not await lifecycle.has_live_executions()
    else:
        assert row["status"] == "running"


@pytest.mark.asyncio
async def test_repeated_cancel_is_idempotent_after_settled_turn(tmp_path) -> None:
    """Cancelling a settled turn must not corrupt its terminal row.

    A cooperative turn is cancelled successfully; the row is terminal. Any
    further cancel call must be a no-op that returns ``False`` and leaves the
    row (and the in-memory bookkeeping) exactly as settled.
    """
    lifecycle, store = await _make_lifecycle(tmp_path)
    release = asyncio.Event()
    turn, execution = await _register_turn(lifecycle, store)
    execution.task = asyncio.create_task(
        _cooperative_turn_body(lifecycle, execution, store, release)
    )
    try:
        await _settle_ticks()
        first = await lifecycle.cancel_turn(turn["id"])
        second = await lifecycle.cancel_turn(turn["id"])

        assert first is True
        assert second is False
        row = await store.get_turn(turn["id"])
        assert row is not None
        assert row["status"] == "cancelled"
        assert not await lifecycle.has_live_execution(turn["id"])
        assert await store.get_active_turn(_SESSION_ID) is None
    finally:
        await _settle_task(execution, release)


@pytest.mark.asyncio
async def test_cancel_storm_converges_to_one_terminal_row(tmp_path) -> None:
    """Back-to-back cancels converge: the row ends terminal and stays there.

    The first cancel races a swallowing task (invisible outcome); the followup
    cancels must settle the row, then report ``False`` once it is terminal —
    the session must never be left with an un-cancellable "active" turn.
    """
    lifecycle, store = await _make_lifecycle(tmp_path)
    release = asyncio.Event()
    turn, execution = await _register_turn(lifecycle, store)
    execution.task = asyncio.create_task(_swallowing_turn_body(lifecycle, execution, release))
    try:
        await _settle_ticks()
        await lifecycle.cancel_turn(turn["id"])
        await lifecycle.cancel_turn(turn["id"])
        third = await lifecycle.cancel_turn(turn["id"])

        assert third is False
        row = await store.get_turn(turn["id"])
        assert row is not None
        assert row["status"] == "cancelled"
        assert not await lifecycle.has_live_execution(turn["id"])
        assert await store.get_active_turn(_SESSION_ID) is None
    finally:
        await _settle_task(execution, release)


@pytest.mark.asyncio
async def test_late_waiter_restore_and_events_cannot_revive_cancelled_turn(
    tmp_path,
) -> None:
    """Writes and events around the unwind must not resurrect the turn.

    A turn parked on ``ask_user`` is cancelled and a late live event reaches
    the subscriber queue during the unwind; once ``cancel_turn`` returns the
    row must be terminal — and a late replay of the waiter restore (the exact
    ``waiting_input`` → ``running`` write the parked waiter's ``finally``
    performs) must be rejected by the status fence instead of flipping the
    cancelled row back to ``running``.
    """
    lifecycle, store = await _make_lifecycle(tmp_path)
    release = asyncio.Event()
    turn, execution = await _register_turn(lifecycle, store)
    subscriber = _LiveSubscriber(queue=asyncio.Queue())
    execution.subscribers.append(subscriber)
    execution.task = asyncio.create_task(
        _cooperative_turn_body(
            lifecycle,
            execution,
            store,
            release,
            park=True,
            emit_late_event=True,
        )
    )
    try:
        await _settle_ticks()
        row = await store.get_turn(turn["id"])
        assert row is not None
        assert row["status"] == "waiting_input", "fixture: turn must be parked"

        settled = await lifecycle.cancel_turn(turn["id"])

        assert settled is True
        row = await store.get_turn(turn["id"])
        assert row is not None
        assert row["status"] == "cancelled"

        # The exact late write the waiter's ``finally`` performs: fenced by
        # the expected status, it must be a no-op on a cancelled row.
        revived = await store.transition_turn(
            turn["id"], "running", expected_status="waiting_input"
        )
        assert revived is False
        row = await store.get_turn(turn["id"])
        assert row is not None
        assert row["status"] == "cancelled"
        assert await store.get_active_turn(_SESSION_ID) is None

        # The in-memory execution is fully settled despite the in-flight event.
        assert not lifecycle._executions
        assert not await lifecycle.has_live_execution(turn["id"])
        assert not await lifecycle.has_live_executions()

        # The subscriber observed the late event and then the close sentinel.
        late_event = subscriber.queue.get_nowait()
        assert late_event["type"] == "delta"
        sentinel = subscriber.queue.get_nowait()
        assert sentinel is None
    finally:
        await _settle_task(execution, release)


@pytest.mark.asyncio
async def test_cancel_fallback_settles_orphaned_running_row(tmp_path) -> None:
    """With no local execution, a durable ``running`` row is cancelled in place."""
    lifecycle, store = await _make_lifecycle(tmp_path)
    turn = None
    await store.create_session(session_id=_SESSION_ID)
    turn = await store.begin_turn(_SESSION_ID, capability="chat")

    settled = await lifecycle.cancel_turn(turn["id"])

    assert settled is True
    row = await store.get_turn(turn["id"])
    assert row is not None
    assert row["status"] == "cancelled"
    assert row["error"] == "Turn cancelled"


@pytest.mark.asyncio
async def test_cancel_defers_to_coordinator_for_unowned_turn(tmp_path) -> None:
    """When a coordinator owns routing, an unowned row is not touched locally."""
    lifecycle, store = await _make_lifecycle(
        tmp_path, coordinator=SimpleNamespace(lease_ttl_seconds=30.0)
    )
    await store.create_session(session_id=_SESSION_ID)
    turn = await store.begin_turn(_SESSION_ID, capability="chat")

    settled = await lifecycle.cancel_turn(turn["id"])

    assert settled is False
    row = await store.get_turn(turn["id"])
    assert row is not None
    assert row["status"] == "running"


@pytest.mark.asyncio
async def test_cancel_returns_false_for_unknown_or_settled_turns(tmp_path) -> None:
    """Unknown ids and already-terminal rows report ``False`` without writes."""
    lifecycle, store = await _make_lifecycle(tmp_path)

    assert await lifecycle.cancel_turn("missing-turn") is False

    await store.create_session(session_id=_SESSION_ID)
    turn = await store.begin_turn(_SESSION_ID, capability="chat")
    assert await store.transition_turn(turn["id"], "completed")

    assert await lifecycle.cancel_turn(turn["id"]) is False
    row = await store.get_turn(turn["id"])
    assert row is not None
    assert row["status"] == "completed"
