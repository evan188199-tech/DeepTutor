"""Focused tests for :mod:`deeptutor.services.sandbox.quota`.

Covers the per-user execution quota gates in ``UserExecQuota``: limit
clamping, the sliding 60-second rate window (including exact-boundary
semantics), over-limit rejection branches, and lease release guarantees.

All cases are deterministic — timestamps are injected via ``acquire(now=...)``
so no wall-clock sleeping is needed.
"""

from __future__ import annotations

import pytest

from deeptutor.services.sandbox.quota import QuotaExceeded, UserExecQuota


@pytest.mark.asyncio
async def test_nonpositive_concurrent_limit_clamped_to_one() -> None:
    """A concurrency cap of 0 is clamped to 1 instead of disabling the guard."""
    quota = UserExecQuota(max_concurrent=0, max_per_minute=10)
    async with await quota.acquire("u1", now=0.0):
        with pytest.raises(QuotaExceeded, match="concurrent"):
            await quota.acquire("u1", now=1.0)


@pytest.mark.asyncio
async def test_nonpositive_rate_limit_clamped_to_one() -> None:
    """A rate cap of 0 is clamped to 1: a second start in the window is rejected."""
    quota = UserExecQuota(max_concurrent=10, max_per_minute=0)
    async with await quota.acquire("u1", now=0.0):
        with pytest.raises(QuotaExceeded, match="rate"):
            await quota.acquire("u1", now=1.0)


@pytest.mark.asyncio
async def test_rate_window_is_sliding_with_exact_boundary() -> None:
    """Entries older than 60s slide out; an entry exactly 60s old still counts."""
    quota = UserExecQuota(max_concurrent=10, max_per_minute=2)
    async with await quota.acquire("u1", now=0.0):
        pass
    async with await quota.acquire("u1", now=0.5):
        pass
    # Window is full within the 60s window.
    with pytest.raises(QuotaExceeded, match="rate"):
        await quota.acquire("u1", now=30.0)
    # At now=60.0 the cutoff is 0.0 and eviction is strict (<), so both
    # entries (0.0, 0.5) are still counted and the request is rejected.
    with pytest.raises(QuotaExceeded, match="rate"):
        await quota.acquire("u1", now=60.0)
    # By 60.5 the 0.0 entry has aged out: one slot is free again.
    async with await quota.acquire("u1", now=60.5):
        pass


@pytest.mark.asyncio
async def test_rate_rejection_does_not_consume_window_slot() -> None:
    """A rate-limited acquire must not append a timestamp to the window."""
    quota = UserExecQuota(max_concurrent=10, max_per_minute=1)
    async with await quota.acquire("u1", now=0.0):
        pass
    for rejected_at in (1.0, 2.0, 3.0):
        with pytest.raises(QuotaExceeded, match="rate"):
            await quota.acquire("u1", now=rejected_at)
    # No phantom entries: at 60.5 the single legitimate entry aged out,
    # so the window is empty and the acquire succeeds.
    async with await quota.acquire("u1", now=60.5):
        pass


@pytest.mark.asyncio
async def test_concurrency_boundary_allows_exactly_max_in_flight() -> None:
    """Exactly max_concurrent leases are granted; the next is rejected."""
    quota = UserExecQuota(max_concurrent=2, max_per_minute=100)
    lease1 = await quota.acquire("u1", now=0.0)
    lease2 = await quota.acquire("u1", now=0.1)
    with pytest.raises(QuotaExceeded, match="concurrent"):
        await quota.acquire("u1", now=0.2)
    await lease1.__aexit__(None, None, None)
    # One slot freed -> the next acquire is granted again.
    lease3 = await quota.acquire("u1", now=0.3)
    await lease2.__aexit__(None, None, None)
    await lease3.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_lease_releases_slot_when_body_raises() -> None:
    """The lease releases the concurrency slot even if the body raises."""
    quota = UserExecQuota(max_concurrent=1, max_per_minute=10)
    with pytest.raises(RuntimeError, match="boom"):
        async with await quota.acquire("u1", now=0.0):
            raise RuntimeError("boom")
    async with await quota.acquire("u1", now=1.0):
        pass


@pytest.mark.asyncio
async def test_concurrency_gate_precedes_rate_gate() -> None:
    """When both caps are hit, the concurrency branch wins and consumes no rate slot."""
    quota = UserExecQuota(max_concurrent=1, max_per_minute=1)
    async with await quota.acquire("u1", now=0.0):
        with pytest.raises(QuotaExceeded, match="concurrent"):
            await quota.acquire("u1", now=1.0)
    # The rejected-while-full attempt left no rate entry behind: once the
    # legitimate entry (0.0) ages out, the user may execute again.
    async with await quota.acquire("u1", now=60.5):
        pass


@pytest.mark.asyncio
async def test_rate_windows_are_per_user() -> None:
    """One user exhausting their rate window does not starve another user."""
    quota = UserExecQuota(max_concurrent=10, max_per_minute=1)
    async with await quota.acquire("u1", now=0.0):
        pass
    with pytest.raises(QuotaExceeded, match="rate"):
        await quota.acquire("u1", now=1.0)
    async with await quota.acquire("u2", now=1.1):
        pass


@pytest.mark.asyncio
async def test_acquire_defaults_to_monotonic_clock() -> None:
    """Without an explicit ``now``, acquire works against the real clock."""
    quota = UserExecQuota(max_concurrent=1, max_per_minute=1)
    async with await quota.acquire("u1"):
        pass
