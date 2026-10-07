"""Tests for traffic control behavior."""

import asyncio
import time

import pytest

from deeptutor.services.llm.traffic_control import TrafficController


@pytest.mark.asyncio
async def test_traffic_control_context() -> None:
    """Traffic control context manager should acquire and release slots."""
    controller = TrafficController(
        provider_name="test",
        max_concurrency=1,
        requests_per_minute=60,
    )

    async with controller:
        assert controller._semaphore.locked() is True

    assert controller._semaphore.locked() is False


@pytest.mark.asyncio
async def test_cancel_during_token_wait_returns_slot() -> None:
    """Cancelling while waiting for a rate-limit token must return the slot."""
    controller = TrafficController(
        provider_name="test",
        max_concurrency=1,
        requests_per_minute=1,
    )
    controller._tokens = 0.0
    controller._last_refill = time.monotonic()

    task = asyncio.create_task(controller.__aenter__())
    await asyncio.sleep(0.1)
    assert controller._semaphore.locked() is True

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert controller._semaphore.locked() is False


@pytest.mark.asyncio
async def test_token_wait_error_returns_slot() -> None:
    """A failure while waiting for a rate-limit token must return the slot."""

    class TokenWaitError(Exception):
        pass

    controller = TrafficController(
        provider_name="test",
        max_concurrency=1,
        requests_per_minute=60,
    )

    async def failing_wait() -> None:
        raise TokenWaitError("rate limiter failed")

    controller._wait_for_token = failing_wait  # type: ignore[method-assign]

    with pytest.raises(TokenWaitError):
        await controller.__aenter__()

    assert controller._semaphore.locked() is False
