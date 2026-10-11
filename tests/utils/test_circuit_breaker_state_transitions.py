"""Complementary tests for the circuit breaker probe contract and boundaries.

Focuses on the contract points not exercised by ``test_circuit_breaker.py``:
half-open probe passthrough, probe-failure re-open semantics, strict recovery
timeout boundary, and the defensive fail-closed path. All timing is driven by
an injectable fake clock - no real waiting, no network.
"""

from __future__ import annotations

from contextlib import contextmanager
import logging
import threading
from types import SimpleNamespace
from typing import Callable, Iterator
from unittest.mock import patch

import pytest

from deeptutor.utils.network import circuit_breaker as mod
from deeptutor.utils.network.circuit_breaker import CircuitBreaker

LOGGER_NAME = "deeptutor.utils.network.circuit_breaker"


@contextmanager
def fake_clock(start: float = 1_000_000.0) -> Iterator[Callable[[float], None]]:
    """Replace the module's ``time`` reference with a controllable clock."""
    clock = {"now": start}

    def advance(seconds: float) -> None:
        clock["now"] += seconds

    fake_time_module = SimpleNamespace(time=lambda: clock["now"])
    with patch.object(mod, "time", fake_time_module):
        yield advance


# ---------------------------------------------------------------------------
# Half-open probe contract
# ---------------------------------------------------------------------------


class TestHalfOpenProbeContract:
    def test_call_allowed_during_half_open_probe_and_stays_half_open(self) -> None:
        """A probe call in half-open state passes through without closing."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60)
        cb.record_failure("p")
        cb.state["p"] = "half-open"
        assert cb.call("p") is True
        assert cb.state["p"] == "half-open"

    def test_failed_probe_reopens_and_restarts_recovery_window(self) -> None:
        """A failed probe re-opens the circuit with a fresh recovery window."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10)
        with fake_clock() as advance:
            cb.record_failure("p")
            assert cb.state["p"] == "open"

            advance(11)
            assert cb.call("p") is True  # probe allowed
            assert cb.state["p"] == "half-open"

            cb.record_failure("p")  # probe failed -> open again
            assert cb.state["p"] == "open"
            assert cb.call("p") is False  # inside the fresh window

            advance(5)
            assert cb.call("p") is False  # only 5s of the fresh window elapsed

            advance(6)
            assert cb.call("p") is True  # fresh window elapsed, probe again

    def test_successful_probe_closes_and_clears_count(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10)
        with fake_clock() as advance:
            cb.record_failure("p")
            advance(11)
            assert cb.call("p") is True
            cb.record_success("p")
            assert cb.state["p"] == "closed"
            assert cb.failure_count["p"] == 0
            assert cb.call("p") is True


# ---------------------------------------------------------------------------
# Recovery timeout boundary
# ---------------------------------------------------------------------------


class TestRecoveryTimeoutBoundary:
    def test_call_blocked_at_exact_recovery_timeout(self) -> None:
        """The recovery check is strict: exactly recovery_timeout stays open."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=30)
        with fake_clock() as advance:
            cb.record_failure("p")
            advance(30)
            assert cb.call("p") is False
            assert cb.state["p"] == "open"

            advance(0.001)
            assert cb.call("p") is True
            assert cb.state["p"] == "half-open"


# ---------------------------------------------------------------------------
# Threshold boundary
# ---------------------------------------------------------------------------


class TestThresholdBoundary:
    @pytest.mark.parametrize(
        ("failures", "threshold", "expected_open"),
        [
            (0, 1, False),
            (1, 1, True),
            (2, 3, False),
            (3, 3, True),
            (4, 3, True),
        ],
    )
    def test_opens_exactly_at_threshold(
        self, failures: int, threshold: int, expected_open: bool
    ) -> None:
        cb = CircuitBreaker(failure_threshold=threshold, recovery_timeout=60)
        for _ in range(failures):
            cb.record_failure("p")
        assert (cb.state.get("p") == "open") is expected_open
        assert cb.call("p") is (not expected_open)

    def test_failures_while_open_keep_circuit_open(self) -> None:
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=60)
        cb.record_failure("p")
        cb.record_failure("p")
        for _ in range(3):
            cb.record_failure("p")
        assert cb.state["p"] == "open"
        assert cb.failure_count["p"] == 5
        assert cb.call("p") is False

    def test_record_success_while_open_is_noop(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60)
        cb.record_failure("p")
        cb.record_success("p")
        assert cb.state["p"] == "open"
        assert cb.failure_count["p"] == 1
        assert cb.call("p") is False


# ---------------------------------------------------------------------------
# Defensive behavior
# ---------------------------------------------------------------------------


class TestDefensiveBehavior:
    def test_call_with_unexpected_state_fails_closed(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60)
        cb.state["p"] = "corrupted"
        with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
            assert cb.call("p") is False
        assert any("unexpected state" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# Full lifecycle driven by the fake clock
# ---------------------------------------------------------------------------


class TestFullLifecycle:
    def test_closed_open_half_open_closed_cycle(self) -> None:
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=10)
        with fake_clock() as advance:
            assert cb.call("p") is True  # closed

            cb.record_failure("p")
            cb.record_failure("p")
            assert cb.state["p"] == "open"
            assert cb.call("p") is False

            advance(10)
            assert cb.call("p") is False  # exact boundary still open

            advance(0.5)
            assert cb.call("p") is True  # probe
            assert cb.state["p"] == "half-open"

            cb.record_success("p")
            assert cb.state["p"] == "closed"
            assert cb.failure_count["p"] == 0
            assert cb.call("p") is True


# ---------------------------------------------------------------------------
# Locking
# ---------------------------------------------------------------------------


class TestLocking:
    def test_concurrent_failures_are_serialized_by_the_lock(self) -> None:
        cb = CircuitBreaker(failure_threshold=8, recovery_timeout=60)
        threads = [threading.Thread(target=cb.record_failure, args=("p",)) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert cb.failure_count["p"] == 8
        assert cb.state["p"] == "open"
        assert cb.call("p") is False
