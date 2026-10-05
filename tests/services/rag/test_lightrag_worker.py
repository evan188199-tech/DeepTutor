"""The worker loop must outlive jobs because native LightRAG shares locks."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
import logging
import threading

import pytest

from deeptutor.services.rag.pipelines.lightrag.worker import run_in_worker_loop


@pytest.mark.asyncio
async def test_concurrent_jobs_share_a_loop_for_process_wide_storage_lock() -> None:
    lock = asyncio.Lock()
    held = threading.Event()
    release = threading.Event()
    loop_ids: list[int] = []

    async def holder(_bridge) -> None:
        async with lock:
            loop_ids.append(id(asyncio.get_running_loop()))
            held.set()
            while not release.is_set():
                await asyncio.sleep(0.005)

    async def waiter(_bridge) -> None:
        async with lock:
            loop_ids.append(id(asyncio.get_running_loop()))

    first = asyncio.create_task(run_in_worker_loop(holder))
    await asyncio.wait_for(asyncio.to_thread(held.wait), timeout=2)
    second = asyncio.create_task(run_in_worker_loop(waiter))
    try:
        # The first waiter binds asyncio.Lock to its loop under contention.
        while not lock._waiters:
            await asyncio.sleep(0.005)
        third = asyncio.create_task(run_in_worker_loop(waiter))
        await asyncio.sleep(0.02)
    finally:
        release.set()
    await asyncio.wait_for(asyncio.gather(first, second, third), timeout=2)
    assert len(loop_ids) == 3
    assert len(set(loop_ids)) == 1


@pytest.mark.asyncio
async def test_cancel_waits_for_cleanup_without_stopping_other_jobs() -> None:
    active = threading.Event()
    cleaning = threading.Event()
    finish_cleanup = threading.Event()

    async def job(_bridge) -> None:
        active.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await asyncio.to_thread(finish_cleanup.wait)

    task = asyncio.create_task(run_in_worker_loop(job, cancel_grace_seconds=0.01))
    await asyncio.wait_for(asyncio.to_thread(active.wait), timeout=2)
    task.cancel()
    try:
        await asyncio.wait_for(asyncio.to_thread(cleaning.wait), timeout=2)
        await asyncio.sleep(0.03)
        assert not task.done()
        assert await run_in_worker_loop(lambda _bridge: asyncio.sleep(0, result=42)) == 42
        task.cancel()  # A repeated owner cancellation must not cancel cleanup.
    finally:
        finish_cleanup.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2)


@pytest.mark.asyncio
async def test_worker_keeps_the_request_context() -> None:
    user = ContextVar("worker_test_user")
    token = user.set("initiator")
    try:
        assert await run_in_worker_loop(lambda _bridge: asyncio.sleep(0, result=user.get())) == (
            "initiator"
        )
    finally:
        user.reset(token)


@pytest.mark.asyncio
async def test_worker_business_exception_propagates_to_caller() -> None:
    async def job(_bridge) -> None:
        raise ValueError("index failed")

    with pytest.raises(ValueError, match="index failed"):
        await run_in_worker_loop(job)


@pytest.mark.asyncio
async def test_cancelled_request_logs_worker_business_failure(caplog) -> None:
    active = threading.Event()

    async def job(_bridge) -> None:
        active.set()
        try:
            await asyncio.sleep(999)
        except asyncio.CancelledError:
            raise RuntimeError("storage flush failed during abort")

    worker_logger = "deeptutor.services.rag.pipelines.lightrag.worker"
    with caplog.at_level(logging.ERROR, logger=worker_logger):
        task = asyncio.create_task(run_in_worker_loop(job, cancel_grace_seconds=0.05))
        await asyncio.wait_for(asyncio.to_thread(active.wait), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=5)
    failures = [
        record
        for record in caplog.records
        if record.name == worker_logger
        and "worker job failed" in record.getMessage()
        and record.exc_info
        and record.exc_info[0] is RuntimeError
    ]
    assert failures, "a worker business failure must not vanish during request cancellation"
