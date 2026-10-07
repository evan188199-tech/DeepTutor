"""Semantic tests for the failed-login rate limiter.

Pure-logic tests: every decision is driven by an explicitly injected epoch
timestamp (the ``now`` parameter or a patched module clock), so the suite
never sleeps and never depends on the wall clock. ``time.time()`` returns
UTC epoch seconds, which carry no timezone, so the same injected ``now``
must produce the same verdict whatever the process local timezone is —
that assumption is pinned by ``test_verdicts_are_timezone_independent``.
"""

from __future__ import annotations

import os
import time
from types import SimpleNamespace

import pytest

from deeptutor.services.login_rate_limit import (
    MAX_FAILED_ATTEMPTS,
    WINDOW_SECONDS,
    LoginRateLimited,
    LoginRateLimiter,
    login_rate_limiter,
)


@pytest.fixture
def set_tz():
    """Switch the process local timezone for the test, then restore it."""
    original = os.environ.get("TZ")

    def _set(tz: str) -> None:
        os.environ["TZ"] = tz
        time.tzset()

    yield _set

    if original is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = original
    time.tzset()


# ---------------------------------------------------------------------------
# In-window counting
# ---------------------------------------------------------------------------


def test_fresh_key_is_allowed() -> None:
    limiter = LoginRateLimiter()

    limiter.ensure_allowed("ip-a", now=1000.0)


def test_failures_below_threshold_within_window_are_allowed() -> None:
    limiter = LoginRateLimiter(max_attempts=5, window_seconds=900)

    for offset in range(4):
        limiter.register_failure("ip-a", now=1000.0 + offset)

    limiter.ensure_allowed("ip-a", now=1100.0)


def test_keys_are_tracked_independently() -> None:
    limiter = LoginRateLimiter(max_attempts=3, window_seconds=900)

    for offset in range(3):
        limiter.register_failure("ip-a", now=1000.0 + offset)

    with pytest.raises(LoginRateLimited):
        limiter.ensure_allowed("ip-a", now=1005.0)

    limiter.ensure_allowed("ip-b", now=1005.0)


def test_ensure_allowed_does_not_record_a_failure() -> None:
    limiter = LoginRateLimiter(max_attempts=3, window_seconds=900)

    for offset in range(3):
        limiter.register_failure("ip-a", now=1000.0 + offset)

    for _ in range(10):
        with pytest.raises(LoginRateLimited):
            limiter.ensure_allowed("ip-a", now=1050.0)

    # If the lock check itself logged attempts, the oldest entry would have
    # been replaced and the lockout would drift; it must not.
    limiter.register_failure("ip-a", now=1051.0)
    with pytest.raises(LoginRateLimited) as excinfo:
        limiter.ensure_allowed("ip-a", now=1052.0)
    assert excinfo.value.retry_after == int(1000.0 + 900 - 1052)


# ---------------------------------------------------------------------------
# Lockout threshold
# ---------------------------------------------------------------------------


def test_lockout_raises_at_threshold() -> None:
    limiter = LoginRateLimiter(max_attempts=5, window_seconds=900)

    for offset in range(4):
        limiter.register_failure("ip-a", now=1000.0 + offset)
    limiter.ensure_allowed("ip-a", now=1004.0)

    limiter.register_failure("ip-a", now=1005.0)
    with pytest.raises(LoginRateLimited):
        limiter.ensure_allowed("ip-a", now=1006.0)


def test_retry_after_counts_from_oldest_attempt() -> None:
    limiter = LoginRateLimiter(max_attempts=5, window_seconds=900)

    for offset in range(5):
        limiter.register_failure("ip-a", now=1000.0 + offset)

    with pytest.raises(LoginRateLimited) as excinfo:
        limiter.ensure_allowed("ip-a", now=1100.0)
    assert excinfo.value.retry_after == 800  # 1000 (oldest) + 900 - 1100


def test_retry_after_shrinks_as_injected_clock_advances() -> None:
    limiter = LoginRateLimiter(max_attempts=2, window_seconds=900)

    limiter.register_failure("ip-a", now=1000.0)
    limiter.register_failure("ip-a", now=1001.0)

    with pytest.raises(LoginRateLimited) as early:
        limiter.ensure_allowed("ip-a", now=1050.0)
    assert early.value.retry_after == 850

    with pytest.raises(LoginRateLimited) as late:
        limiter.ensure_allowed("ip-a", now=1800.0)
    assert late.value.retry_after == 100


def test_extra_failures_during_lockout_do_not_extend_the_lock() -> None:
    """The lock expires when the oldest in-window failure expires.

    Failures appended while already locked can only take over once the
    original batch has been pruned, so they must not push the retry point
    further out.
    """
    limiter = LoginRateLimiter(max_attempts=2, window_seconds=900)

    limiter.register_failure("ip-a", now=1000.0)
    limiter.register_failure("ip-a", now=1001.0)
    limiter.register_failure("ip-a", now=1500.0)

    with pytest.raises(LoginRateLimited) as excinfo:
        limiter.ensure_allowed("ip-a", now=1600.0)
    assert excinfo.value.retry_after == 300  # anchored at 1000, not 1500


# ---------------------------------------------------------------------------
# Window reset
# ---------------------------------------------------------------------------


def test_window_expiry_allows_login_again() -> None:
    limiter = LoginRateLimiter(max_attempts=3, window_seconds=900)

    for offset in range(3):
        limiter.register_failure("ip-a", now=1000.0 + offset)

    with pytest.raises(LoginRateLimited):
        limiter.ensure_allowed("ip-a", now=1500.0)

    limiter.ensure_allowed("ip-a", now=1901.0)

    # The limiter is fresh again: a whole new batch is needed to re-lock.
    for offset in range(2):
        limiter.register_failure("ip-a", now=1902.0 + offset)
    limiter.ensure_allowed("ip-a", now=1910.0)


def test_attempt_exactly_at_cutoff_is_pruned() -> None:
    """A failure lives for exactly window_seconds, boundary inclusive.

    Pruning uses ``<= cutoff``, so a failure recorded at ``t`` no longer
    counts at ``t + window_seconds``; one tick earlier it still does.
    """
    limiter = LoginRateLimiter(max_attempts=2, window_seconds=900)

    limiter.register_failure("ip-a", now=1000.0)
    limiter.register_failure("ip-a", now=1000.0)

    with pytest.raises(LoginRateLimited):
        limiter.ensure_allowed("ip-a", now=1899.999)

    limiter.ensure_allowed("ip-a", now=1900.0)


def test_register_success_clears_failures() -> None:
    limiter = LoginRateLimiter(max_attempts=2, window_seconds=900)

    limiter.register_failure("ip-a", now=1000.0)
    limiter.register_failure("ip-a", now=1001.0)
    with pytest.raises(LoginRateLimited):
        limiter.ensure_allowed("ip-a", now=1002.0)

    limiter.register_success("ip-a")
    limiter.ensure_allowed("ip-a", now=1003.0)

    # And the slate is truly clean: a fresh batch is needed to re-lock.
    limiter.register_failure("ip-a", now=1004.0)
    limiter.ensure_allowed("ip-a", now=1005.0)


def test_register_success_is_a_noop_for_unknown_keys() -> None:
    limiter = LoginRateLimiter()

    limiter.register_success("ip-never-seen")

    limiter.ensure_allowed("ip-never-seen", now=1000.0)


# ---------------------------------------------------------------------------
# Clock boundaries (fixed clock injection, cross-timezone)
# ---------------------------------------------------------------------------


def test_retry_after_is_at_least_one_second_near_expiry() -> None:
    limiter = LoginRateLimiter(max_attempts=1, window_seconds=900)

    limiter.register_failure("ip-a", now=1000.0)

    with pytest.raises(LoginRateLimited) as excinfo:
        limiter.ensure_allowed("ip-a", now=1899.5)
    assert excinfo.value.retry_after == 1  # 0.5s left, never reported as 0

    with pytest.raises(LoginRateLimited) as excinfo:
        limiter.ensure_allowed("ip-a", now=1899.999)
    assert excinfo.value.retry_after == 1

    with pytest.raises(LoginRateLimited) as excinfo:
        limiter.ensure_allowed("ip-a", now=1899.0)
    assert excinfo.value.retry_after == 1  # exactly 1s left


def test_module_default_clock_is_injectable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without ``now`` the limiter reads ``time.time()`` from its module."""
    from deeptutor.services import login_rate_limit as module

    monkeypatch.setattr(
        module,
        "time",
        SimpleNamespace(time=lambda: 5000.0),
    )
    limiter = LoginRateLimiter(max_attempts=1, window_seconds=900)

    limiter.register_failure("ip-a")

    with pytest.raises(LoginRateLimited) as excinfo:
        limiter.ensure_allowed("ip-a")
    assert excinfo.value.retry_after == 900

    monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: 6000.0))
    limiter.ensure_allowed("ip-a")


def test_singleton_uses_module_defaults() -> None:
    assert login_rate_limiter.max_attempts == MAX_FAILED_ATTEMPTS == 5
    assert login_rate_limiter.window_seconds == WINDOW_SECONDS == 900


def test_verdicts_are_timezone_independent(set_tz) -> None:
    """Epoch arithmetic only: the local timezone must not move the lock.

    Runs the identical scenario under a UTC+14 and a UTC-11 zone and
    requires byte-identical verdicts and retry windows.
    """
    zones = ["Pacific/Kiritimati", "Pacific/Midway"]
    observed = []

    for zone in zones:
        set_tz(zone)
        # Guard against a silent tzset no-op making this test vacuous.
        assert time.tzname is not None

        limiter = LoginRateLimiter(max_attempts=3, window_seconds=900)
        for offset in range(3):
            limiter.register_failure("ip-a", now=1000.0 + offset)

        verdicts = []
        for probe in (1500.0, 1899.5, 1900.0):
            try:
                limiter.ensure_allowed("ip-a", now=probe)
                verdicts.append(("allowed", None))
            except LoginRateLimited as exc:
                verdicts.append(("blocked", exc.retry_after))

        observed.append((time.tzname, verdicts))

    assert observed[0][1] == observed[1][1]
    assert observed[0][0] != observed[1][0]
    assert observed[0][1] == [
        ("blocked", 400),
        ("blocked", 1),
        ("allowed", None),
    ]
