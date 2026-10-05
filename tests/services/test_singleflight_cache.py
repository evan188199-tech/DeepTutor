from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from deeptutor.services.singleflight_cache import AsyncSingleFlightTTLCache


@dataclass(frozen=True)
class Value:
    text: str
    created_at: float


def cache(clock: list[float], *, limit: int = 2) -> AsyncSingleFlightTTLCache[str, Value]:
    return AsyncSingleFlightTTLCache(
        limit=limit,
        ttl_seconds=10,
        value_timestamp=lambda value: value.created_at,
        now=lambda: clock[0],
    )


def test_recall_expires_values_and_evicts_oldest_insertions() -> None:
    clock = [5.0]
    subject = cache(clock)
    subject.remember("a", Value("a", 5.0))
    subject.remember("b", Value("b", 5.0))
    subject.remember("c", Value("c", 5.0))

    assert list(subject.values) == ["b", "c"]
    assert subject.recall("b") == Value("b", 5.0)

    clock[0] = 16.0
    assert subject.recall("b") is None
    assert "b" not in subject.values


@pytest.mark.asyncio
async def test_concurrent_callers_share_one_producer_and_cache_usable_result() -> None:
    clock = [1.0]
    subject = cache(clock)
    started = 0
    release = asyncio.Event()

    async def produce() -> Value:
        nonlocal started
        started += 1
        await release.wait()
        return Value("ready", clock[0])

    first = asyncio.create_task(subject.get_or_create("key", produce))
    second = asyncio.create_task(subject.get_or_create("key", produce))
    await asyncio.sleep(0)
    release.set()

    assert await first == await second == Value("ready", 1.0)
    assert started == 1
    assert subject.recall("key") == Value("ready", 1.0)
    assert subject.inflight == {}


@pytest.mark.asyncio
async def test_non_cacheable_results_and_failures_leave_no_state() -> None:
    subject = cache([1.0])

    value = await subject.get_or_create(
        "empty",
        lambda: asyncio.sleep(0, result=Value("", 1.0)),
        cache_when=lambda item: bool(item.text),
    )
    assert value.text == ""
    assert subject.values == {}

    async def fail() -> Value:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await subject.get_or_create("failed", fail)
    assert subject.inflight == {}


@pytest.mark.asyncio
async def test_different_keys_load_in_parallel_without_blocking() -> None:
    subject = cache([1.0])
    started = {"a": asyncio.Event(), "b": asyncio.Event()}
    release = {"a": asyncio.Event(), "b": asyncio.Event()}

    async def produce(key: str) -> Value:
        started[key].set()
        await release[key].wait()
        return Value(key, 1.0)

    first = asyncio.create_task(subject.get_or_create("a", lambda: produce("a")))
    await started["a"].wait()

    # While key "a" is still mid-flight, key "b" must be able to start its own
    # load; the watchdog timeouts turn a cross-key deadlock into a fast failure.
    second = asyncio.create_task(subject.get_or_create("b", lambda: produce("b")))
    await asyncio.wait_for(started["b"].wait(), timeout=1.0)
    assert not release["a"].is_set()

    release["b"].set()
    assert await asyncio.wait_for(second, timeout=1.0) == Value("b", 1.0)
    assert subject.recall("b") == Value("b", 1.0)

    release["a"].set()
    assert await asyncio.wait_for(first, timeout=1.0) == Value("a", 1.0)


@pytest.mark.asyncio
async def test_failed_load_propagates_to_every_waiter_and_the_key_can_retry() -> None:
    subject = cache([1.0])
    attempts = 0
    started = asyncio.Event()
    release = asyncio.Event()

    async def produce() -> Value:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            started.set()
            await release.wait()
            raise RuntimeError("boom")
        return Value("recovered", 1.0)

    waiters = [asyncio.create_task(subject.get_or_create("key", produce)) for _ in range(3)]
    await started.wait()
    await asyncio.sleep(0)
    release.set()

    outcomes = await asyncio.gather(*waiters, return_exceptions=True)
    failure = outcomes[0]
    assert attempts == 1
    assert isinstance(failure, RuntimeError)
    assert all(outcome is failure for outcome in outcomes)
    assert subject.recall("key") is None
    assert subject.inflight == {}

    # The failed load left no poisoned state: a later caller re-runs the
    # factory and its success is cached as usual.
    assert await subject.get_or_create("key", produce) == Value("recovered", 1.0)
    assert attempts == 2
    assert subject.recall("key") == Value("recovered", 1.0)


@pytest.mark.asyncio
async def test_cancelling_a_waiter_cancels_the_load_and_frees_the_slot() -> None:
    subject = cache([1.0])
    attempts = 0
    started = {"first": asyncio.Event(), "second": asyncio.Event()}
    release = {"first": asyncio.Event(), "second": asyncio.Event()}

    async def produce() -> Value:
        nonlocal attempts
        attempts += 1
        attempt = "first" if attempts == 1 else "second"
        started[attempt].set()
        await release[attempt].wait()
        return Value(attempt, 1.0)

    waiter = asyncio.create_task(subject.get_or_create("key", produce))
    await started["first"].wait()
    shared_load = subject.inflight["key"]

    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    # The cancellation propagates through the await into the shared load and
    # leaves neither a cached value nor an inflight slot behind.
    assert shared_load.cancelled()
    assert subject.recall("key") is None
    assert subject.inflight == {}

    # A later caller therefore starts a fresh load and its success is cached.
    newcomer = asyncio.create_task(subject.get_or_create("key", produce))
    await started["second"].wait()
    release["second"].set()
    assert await newcomer == Value("second", 1.0)
    assert attempts == 2
    assert subject.recall("key") == Value("second", 1.0)


@pytest.mark.asyncio
async def test_wait_for_timeout_cancels_the_load_and_leaves_no_state() -> None:
    subject = cache([1.0])
    started = asyncio.Event()
    release = asyncio.Event()

    async def produce() -> Value:
        started.set()
        await release.wait()
        return Value("slow", 1.0)

    waiter = asyncio.create_task(
        asyncio.wait_for(subject.get_or_create("key", produce), timeout=0.05)
    )
    await started.wait()
    shared_load = subject.inflight["key"]

    with pytest.raises(asyncio.TimeoutError):
        await waiter

    # The caller's timeout cancels the shared load too; nothing was cached and
    # no inflight entry survived, so the next caller retries from scratch.
    assert shared_load.cancelled()
    assert subject.recall("key") is None
    assert subject.values == {}
    assert subject.inflight == {}

    release.set()  # nothing is waiting on it anymore; keeps the gate balanced
