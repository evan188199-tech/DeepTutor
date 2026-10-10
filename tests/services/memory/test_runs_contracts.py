"""Contract and boundary tests for consolidator runs bookkeeping.

Locks the pieces of ``deeptutor/services/memory/consolidator/runs.py``
that the happy-path suite (``test_runs.py``) and the waiter-registry net
(``test_consolidator_waiters.py``) do not cover:

* ``Run`` / ``RunEvent`` / ``UndoCheckpoint`` dataclass contracts
  (``active`` flag, ``to_dict`` shape, optional-field defaults);
* ``RunBusyError`` typing and message context;
* cancel-path edges (unknown id, already-terminal run, restart after
  cancel/error, cancelled event trace);
* undo/checkpoint recovery (KeyError, busy guard, empty stack, LIFO
  ordering, ``existed=False`` file removal, payloads);
* registry lifecycle (FIFO eviction with active-run protection, param
  copy, defaults, ``list_for`` filters, singleton accessors);
* ``current_run`` contextvar scoping and the negative-cursor clamp.

These tests intentionally do not touch product code.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

import deeptutor.services.memory.consolidator.runs as runs_module
from deeptutor.services.memory.consolidator.runs import (
    Run,
    RunBusyError,
    RunEvent,
    RunManager,
    UndoCheckpoint,
    current_run,
    get_run_manager,
    push_undo_checkpoint,
    reset_run_manager_for_tests,
)


@pytest.fixture()
def manager() -> RunManager:
    return RunManager()


@pytest.fixture(autouse=True)
def _fresh_global_manager():
    reset_run_manager_for_tests()
    yield
    reset_run_manager_for_tests()


async def _await_run(run: Run) -> None:
    if run._task is not None:
        await run._task


async def _start_gated_run(
    manager: RunManager,
    started: asyncio.Event,
    release: asyncio.Event,
    *,
    layer: str = "L2",
    key: str = "chat",
):
    async def runner(on_event):
        started.set()
        await release.wait()

    run = await manager.start(layer=layer, key=key, mode="update", runner=runner)
    await asyncio.wait_for(started.wait(), timeout=2)
    return run


# ---------------------------------------------------------------------------
# Run / RunEvent / UndoCheckpoint dataclass contracts
# ---------------------------------------------------------------------------


def test_run_active_flag_across_all_statuses() -> None:
    def _run(status: str) -> Run:
        return Run(
            id="r",
            layer="L2",
            key="k",
            mode="update",
            params={},
            language="en",
            user_label="u",
            status=status,  # type: ignore[arg-type]
        )

    assert _run("queued").active is True
    assert _run("running").active is True
    assert _run("done").active is False
    assert _run("cancelled").active is False
    assert _run("error").active is False


def test_run_to_dict_shape_and_counts() -> None:
    run = Run(
        id="rid",
        layer="L2",
        key="chat",
        mode="audit",
        params={"turn": 3},
        language="zh",
        user_label="alice",
    )
    run.events.append(RunEvent(seq=0, ts="t0", payload={"stage": "x"}))
    run.undo_stack.append(
        UndoCheckpoint(
            id="c",
            ts="t1",
            layer="L2",
            key="chat",
            path="/tmp/x.md",
            existed=True,
            previous_content="old",
            action="write",
        )
    )
    data = run.to_dict()
    assert data["id"] == "rid"
    assert data["layer"] == "L2"
    assert data["key"] == "chat"
    assert data["mode"] == "audit"
    assert data["params"] == {"turn": 3}
    assert data["language"] == "zh"
    # user_label is deliberately not part of the serialized surface.
    assert "user_label" not in data
    assert data["status"] == "queued"
    assert data["ended_at"] is None
    assert data["error"] is None
    assert data["event_count"] == 1
    assert data["undo_count"] == 1
    assert set(data) == {
        "id",
        "layer",
        "key",
        "mode",
        "params",
        "language",
        "status",
        "started_at",
        "ended_at",
        "error",
        "event_count",
        "undo_count",
    }


def test_undo_checkpoint_optional_fields_default_to_none() -> None:
    cp = UndoCheckpoint(
        id="c1",
        ts="2026-10-10T00:00:00+00:00",
        layer="L3",
        key="k",
        path="/p",
        existed=False,
        previous_content="",
        action="delete",
    )
    assert cp.turn is None
    assert cp.label is None


def test_run_busy_error_is_runtime_error_with_layer_key_context() -> None:
    assert issubclass(RunBusyError, RuntimeError)
    err = RunBusyError("a run is already in progress for L2/chat")
    assert "L2" in str(err) and "chat" in str(err)


def test_run_event_timestamps_are_utc_iso() -> None:
    ev = RunEvent(seq=0, ts=runs_module._now_iso(), payload={})
    parsed = datetime.fromisoformat(ev.ts)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 0


# ---------------------------------------------------------------------------
# Busy guard boundaries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_busy_error_only_for_same_layer_and_key(manager: RunManager) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def runner(on_event):
        started.set()
        await release.wait()

    first = await manager.start(layer="L2", key="chat", mode="update", runner=runner)
    await started.wait()
    # Same key, different layer: independent slot.
    other_layer = await manager.start(layer="L3", key="chat", mode="update", runner=runner)
    await asyncio.wait_for(started.wait(), timeout=2)
    with pytest.raises(RunBusyError) as exc_info:
        await manager.start(layer="L2", key="chat", mode="audit", runner=runner)
    assert "L2/chat" in str(exc_info.value)
    release.set()
    await _await_run(first)
    await _await_run(other_layer)


@pytest.mark.asyncio
async def test_active_for_returns_run_while_running(manager: RunManager) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    run = await _start_gated_run(manager, started, release)
    live = manager.active_for("L2", "chat")
    assert live is run
    assert live.active is True
    release.set()
    await _await_run(run)
    assert manager.active_for("L2", "chat") is None


# ---------------------------------------------------------------------------
# Cancel-path edges
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_returns_false_for_unknown_and_terminal_runs(
    manager: RunManager,
) -> None:
    assert await manager.cancel("no-such-id") is False

    async def runner(on_event):
        await on_event({"stage": "progress"})

    run = await manager.start(layer="L2", key="chat", mode="update", runner=runner)
    await _await_run(run)
    assert run.status == "done"
    assert await manager.cancel(run.id) is False


@pytest.mark.asyncio
async def test_cancelled_run_emits_cancelled_trace_and_frees_slot(
    manager: RunManager,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    run = await _start_gated_run(manager, started, release)

    assert await manager.cancel(run.id) is True
    await _await_run(run)

    stages = [ev.payload.get("stage") for ev in run.events]
    assert "cancelled" in stages
    assert stages[-1] == "run_ended"
    assert run.events[-1].payload["status"] == "cancelled"
    assert run.status == "cancelled"
    assert run.ended_at is not None
    # Terminal run releases the (layer, key) slot.
    assert manager.active_for("L2", "chat") is None
    second = await manager.start(
        layer="L2",
        key="chat",
        mode="update",
        runner=lambda on_event: asyncio.sleep(0),
    )
    await _await_run(second)
    assert second.status == "done"


@pytest.mark.asyncio
async def test_error_run_frees_slot_and_records_trace(manager: RunManager) -> None:
    async def runner(on_event):
        raise ValueError("boom")

    run = await manager.start(layer="L2", key="chat", mode="update", runner=runner)
    await _await_run(run)

    assert run.status == "error"
    assert run.error == "boom"
    assert run.ended_at is not None
    stages = [ev.payload.get("stage") for ev in run.events]
    assert stages[-1] == "run_ended"
    error_events = [ev for ev in run.events if ev.payload.get("stage") == "error"]
    assert error_events and error_events[0].payload["message"] == "boom"
    assert manager.active_for("L2", "chat") is None
    # Restart on the same doc is allowed after the failure.
    second = await manager.start(
        layer="L2",
        key="chat",
        mode="update",
        runner=lambda on_event: asyncio.sleep(0),
    )
    await _await_run(second)
    assert second.status == "done"


@pytest.mark.asyncio
async def test_runner_set_terminal_status_is_not_overridden_to_done(
    manager: RunManager,
) -> None:
    async def runner(on_event):
        run = current_run()
        assert run is not None
        run.status = "error"
        run.error = "degraded by mode"

    run = await manager.start(layer="L2", key="chat", mode="update", runner=runner)
    await _await_run(run)
    # The driver only promotes running→done; an explicit terminal status stays.
    assert run.status == "error"
    assert run.error == "degraded by mode"
    assert run.events[-1].payload["status"] == "error"


# ---------------------------------------------------------------------------
# Undo checkpoints / recovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_undo_last_raises_keyerror_for_unknown_run(manager: RunManager) -> None:
    with pytest.raises(KeyError):
        await manager.undo_last("missing-run")


@pytest.mark.asyncio
async def test_undo_last_rejected_while_run_active(manager: RunManager) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    run = await _start_gated_run(manager, started, release)
    with pytest.raises(RunBusyError):
        await manager.undo_last(run.id)
    release.set()
    await _await_run(run)


@pytest.mark.asyncio
async def test_undo_last_returns_none_without_checkpoints(manager: RunManager) -> None:
    async def runner(on_event):
        await on_event({"stage": "progress"})

    run = await manager.start(layer="L2", key="chat", mode="update", runner=runner)
    await _await_run(run)
    assert run.undo_stack == []
    assert await manager.undo_last(run.id) is None


@pytest.mark.asyncio
async def test_undo_restores_lifo_and_reports_depth_and_metadata(
    manager: RunManager, tmp_path
) -> None:
    path = tmp_path / "chat.md"
    path.write_text("orig", encoding="utf-8")

    async def runner(on_event):
        assert (
            push_undo_checkpoint(
                layer="L2",
                key="chat",
                path=path,
                existed=True,
                previous_content="orig",
                action="first_write",
                turn=1,
                label="update",
            )
            == 1
        )
        path.write_text("edit1", encoding="utf-8")
        assert (
            push_undo_checkpoint(
                layer="L2",
                key="chat",
                path=path,
                existed=True,
                previous_content="edit1",
                action="second_write",
                turn=2,
                label="update",
            )
            == 2
        )
        path.write_text("edit2", encoding="utf-8")

    base_seq = 0
    run = await manager.start(layer="L2", key="chat", mode="update", runner=runner)
    await _await_run(run)
    assert path.read_text(encoding="utf-8") == "edit2"
    base_seq = run.events[-1].seq
    newest_cp_id, oldest_cp_id = run.undo_stack[-1].id, run.undo_stack[0].id

    # LIFO: the newest checkpoint wins first.
    event = await manager.undo_last(run.id)
    assert event is not None
    assert path.read_text(encoding="utf-8") == "edit1"
    assert event.seq == base_seq + 1  # seq stays monotonic after the run ended
    assert event.payload["stage"] == "undo_applied"
    assert event.payload["undo_id"] == newest_cp_id
    assert event.payload["undo_depth"] == 1
    assert event.payload["turn"] == 2
    assert event.payload["label"] == "update"
    assert event.payload["action"] == "second_write"

    event = await manager.undo_last(run.id)
    assert event is not None
    assert path.read_text(encoding="utf-8") == "orig"
    assert event.payload["undo_id"] == oldest_cp_id
    assert event.payload["undo_depth"] == 0
    assert event.payload["turn"] == 1
    assert event.payload["action"] == "first_write"
    # Exhausted stack behaves like the empty case.
    assert await manager.undo_last(run.id) is None


@pytest.mark.asyncio
async def test_undo_of_never_existed_file_removes_it_and_tolerates_missing(
    manager: RunManager, tmp_path
) -> None:
    path = tmp_path / "created.md"

    async def runner(on_event):
        # Simulate a run that created the file from nothing.
        path.write_text("fresh", encoding="utf-8")
        push_undo_checkpoint(
            layer="L2",
            key="chat",
            path=path,
            existed=False,
            previous_content="",
            action="create",
        )
        push_undo_checkpoint(
            layer="L2",
            key="chat",
            path=path,
            existed=False,
            previous_content="",
            action="create-again",
        )

    run = await manager.start(layer="L2", key="chat", mode="update", runner=runner)
    await _await_run(run)
    assert path.exists()

    event = await manager.undo_last(run.id)
    assert event is not None
    assert event.payload["action"] == "create-again"
    assert not path.exists()
    # Second undo targets an already-removed file: best effort, no raise.
    event = await manager.undo_last(run.id)
    assert event is not None
    assert event.payload["action"] == "create"
    assert not path.exists()


def test_push_undo_checkpoint_is_noop_without_active_run(tmp_path) -> None:
    assert current_run() is None
    assert (
        push_undo_checkpoint(
            layer="L2",
            key="chat",
            path=tmp_path / "x.md",
            existed=True,
            previous_content="old",
            action="write",
        )
        == 0
    )


# ---------------------------------------------------------------------------
# Registry lifecycle: eviction, defaults, listing, singleton
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_history_evicts_oldest_fifo_beyond_cap(
    manager: RunManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runs_module, "_MAX_HISTORY", 3)

    async def runner(on_event):
        await on_event({"stage": "progress"})

    ids: list[str] = []
    for i in range(4):
        run = await manager.start(layer="L2", key=f"k{i}", mode="update", runner=runner)
        await _await_run(run)
        ids.append(run.id)

    assert manager.get(ids[0]) is None  # oldest evicted
    assert manager.get(ids[1]) is not None
    assert manager.get(ids[3]) is not None
    assert [r.key for r in manager.list_for()] == ["k1", "k2", "k3"]


@pytest.mark.asyncio
async def test_active_run_is_protected_from_eviction(
    manager: RunManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runs_module, "_MAX_HISTORY", 2)
    started = asyncio.Event()
    release = asyncio.Event()
    active = await _start_gated_run(manager, started, release, key="held")

    async def runner(on_event):
        await on_event({"stage": "progress"})

    for i in range(3):
        run = await manager.start(layer="L2", key=f"spin{i}", mode="update", runner=runner)
        await _await_run(run)

    assert manager.get(active.id) is active  # never evicted while queued/running
    release.set()
    await _await_run(active)


@pytest.mark.asyncio
async def test_start_copies_params_and_applies_defaults(manager: RunManager) -> None:
    params = {"turn": 7}

    async def runner(on_event):
        await on_event({"stage": "progress"})

    run = await manager.start(layer="L2", key="chat", mode="update", runner=runner, params=params)
    params["turn"] = 99  # caller-side mutation must not leak into the run
    await _await_run(run)
    assert run.params == {"turn": 7}
    assert run.language == "en"
    assert run.user_label == "anonymous"

    bare = await manager.start(layer="L2", key="chat", mode="audit", runner=runner, params=None)
    await _await_run(bare)
    assert bare.params == {}


@pytest.mark.asyncio
async def test_list_for_filters_by_layer_and_key(manager: RunManager) -> None:
    async def runner(on_event):
        await on_event({"stage": "progress"})

    runs = []
    for layer, key in [("L2", "chat"), ("L2", "notebook"), ("L3", "chat")]:
        run = await manager.start(layer=layer, key=key, mode="update", runner=runner)
        await _await_run(run)
        runs.append(run)

    assert [r.id for r in manager.list_for()] == [r.id for r in runs]
    assert [r.key for r in manager.list_for(layer="L2")] == ["chat", "notebook"]
    assert [r.id for r in manager.list_for(key="chat")] == [runs[0].id, runs[2].id]
    assert [r.id for r in manager.list_for(layer="L3", key="chat")] == [runs[2].id]
    assert manager.list_for(layer="L9") == []


@pytest.mark.asyncio
async def test_wait_for_events_negative_cursor_clamps_to_zero(
    manager: RunManager,
) -> None:
    async def runner(on_event):
        for i in range(3):
            await on_event({"stage": "progress", "i": i})

    run = await manager.start(layer="L2", key="chat", mode="update", runner=runner)
    await _await_run(run)
    events = await manager.wait_for_events(run, since=-5)
    assert [ev.seq for ev in events] == [0, 1, 2, 3, 4]  # run_started + 3 + run_ended


def test_get_run_manager_is_singleton_and_resets() -> None:
    first = get_run_manager()
    assert get_run_manager() is first
    reset_run_manager_for_tests()
    assert get_run_manager() is not first


@pytest.mark.asyncio
async def test_current_run_scoped_to_task_and_cleared_afterwards(
    manager: RunManager,
) -> None:
    seen: list[str | None] = [current_run()]

    async def runner(on_event):
        seen.append(current_run().id if current_run() is not None else None)

    run = await manager.start(layer="L2", key="chat", mode="update", runner=runner)
    await _await_run(run)
    seen.append(current_run())
    assert seen[0] is None
    assert seen[1] == run.id
    assert seen[2] is None
