"""Exception-visibility contract for the LightRAG worker loop.

``run_in_worker_loop`` promises that worker exceptions are re-raised in the
awaiting owner task, but its owner-cancellation handler retrieves the worker's
terminal exception and discards it with ``except BaseException: pass``. When a
genuine worker failure races the owner's cancellation, the failure vanishes
without a trace: the caller only ever sees ``CancelledError``.

These tests lock the contract a fix must satisfy:

- a worker error with no concurrent cancellation reaches the caller unchanged;
- a worker error racing a concurrent owner cancellation must not be dropped
  silently — it has to be reported through the module logger at ERROR level
  (expected cancellations of the worker stay exempt from that reporting);
- normal completion returns the job result and runs owner-loop callbacks on
  the owner loop;
- the caller's ``CancelledError`` surfaces only after the job's cleanup has
  finished, and the process-wide worker loop stays usable afterwards;
- an in-flight job stops cooperatively at the next ``OwnerLoopBridge``
  boundary and still runs its cleanup before the caller observes the cancel.
"""

from __future__ import annotations

import asyncio
import logging
import threading

import pytest

from deeptutor.services.rag.pipelines.lightrag.worker import OwnerLoopBridge
from deeptutor.services.rag.pipelines.lightrag.worker import run_in_worker_loop

WORKER_LOGGER = "deeptutor.services.rag.pipelines.lightrag.worker"


def _record_mentions(record: logging.LogRecord, text: str) -> bool:
    """Match either a formatted message or an attached exception chain."""
    if text in record.getMessage():
        return True
    exc = record.exc_info[1] if record.exc_info else None
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if text in str(exc):
            return True
        exc = exc.__context__ or exc.__cause__
    return False


@pytest.mark.asyncio
async def test_worker_error_reraises_in_awaiting_owner_task() -> None:
    """Without cancellation, a worker failure reaches the caller unchanged."""

    async def job(_bridge: OwnerLoopBridge) -> None:
        raise RuntimeError("lightrag worker boom")

    with pytest.raises(RuntimeError, match="lightrag worker boom"):
        await run_in_worker_loop(job)


@pytest.mark.asyncio
async def test_worker_error_racing_owner_cancel_is_reported(caplog) -> None:
    """A genuine worker failure must not vanish when the owner cancels.

    The caller keeps seeing ``CancelledError`` (the owner's cancellation
    stays authoritative), but the worker's terminal exception has to be
    reported through the module logger at ERROR level instead of being
    discarded by the bare ``except BaseException: pass``.
    """
    started = threading.Event()

    async def job(_bridge: OwnerLoopBridge) -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise RuntimeError("lightrag worker failed during owner cancel")

    with caplog.at_level(logging.ERROR, logger=WORKER_LOGGER):
        task = asyncio.create_task(run_in_worker_loop(job))
        assert await asyncio.to_thread(started.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=10)

    reports = [
        record
        for record in caplog.records
        if _record_mentions(record, "lightrag worker failed during owner cancel")
    ]
    assert reports, "worker terminal error was silently discarded during owner cancel"
    assert any(record.levelno >= logging.ERROR for record in reports)


@pytest.mark.asyncio
async def test_normal_completion_returns_result_and_bridge_targets_owner_loop() -> None:
    """The job result is returned and owner callbacks run on the owner loop."""
    owner_loop = asyncio.get_running_loop()
    callback_loops: list[asyncio.AbstractEventLoop] = []

    def owner_callback() -> str:
        callback_loops.append(asyncio.get_running_loop())
        return "bridge-ok"

    async def job(bridge: OwnerLoopBridge) -> str:
        note = await bridge.call(owner_callback)
        return f"result:{note}"

    assert await run_in_worker_loop(job) == "result:bridge-ok"
    assert callback_loops == [owner_loop]


@pytest.mark.asyncio
async def test_owner_cancel_waits_for_job_cleanup_and_loop_stays_usable() -> None:
    """CancelledError surfaces only after the job's cleanup confirmed done."""
    started = threading.Event()
    release_cleanup = threading.Event()
    cleaned = threading.Event()

    async def job(_bridge: OwnerLoopBridge) -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.to_thread(release_cleanup.wait)
            cleaned.set()

    task = asyncio.create_task(run_in_worker_loop(job, cancel_grace_seconds=0.05))
    assert await asyncio.to_thread(started.wait, 5)
    task.cancel()
    await asyncio.sleep(0.1)
    assert not task.done()
    assert not cleaned.is_set()
    release_cleanup.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=10)
    assert cleaned.is_set()
    assert await run_in_worker_loop(lambda _bridge: asyncio.sleep(0, result=7)) == 7


@pytest.mark.asyncio
async def test_owner_cancel_stops_job_at_bridge_boundary_and_runs_cleanup() -> None:
    """An in-flight job stops cooperatively at the next bridge boundary."""
    ticks: list[bool] = []
    stopped_at_boundary = threading.Event()
    cleaned = threading.Event()

    async def job(bridge: OwnerLoopBridge) -> None:
        try:
            while True:
                await bridge.call(lambda: ticks.append(True))
        except asyncio.CancelledError:
            stopped_at_boundary.set()
            raise
        finally:
            cleaned.set()

    task = asyncio.create_task(run_in_worker_loop(job, cancel_grace_seconds=5.0))
    try:
        while not ticks:
            await asyncio.sleep(0.005)
    finally:
        task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=10)
    assert stopped_at_boundary.is_set()
    assert cleaned.is_set()
