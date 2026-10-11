"""Bounded reconnect backoff shared by channel listeners.

Replaces the per-channel fixed ``sleep(2)``/``sleep(5)``/``sleep(10)`` ladders:
without jitter, every channel in a fleet retries on the same beat, and without
a cap a fast-failing endpoint pins the ladder at its maximum forever after one
storm. ``ReconnectBackoff`` keeps the first retry near the historical delay
and only escalates while failures repeat.
"""

from __future__ import annotations

import random
from typing import Callable

DEFAULT_JITTER = 0.25


def backoff_delay(
    attempt: int,
    *,
    base: float,
    cap: float,
    jitter: float = DEFAULT_JITTER,
    rand: Callable[[], float] | None = None,
) -> float:
    """Delay before retry ``attempt`` (0-based consecutive failure count).

    ``min(cap, base * 2**attempt)`` spread by ±``jitter`` (full-jitter band
    around the ladder value, so the first retry stays near ``base``).
    """
    if base <= 0 or cap <= 0:
        raise ValueError("base and cap must be positive")
    if not 0 <= jitter < 1:
        raise ValueError("jitter must be within [0, 1)")
    attempt = max(0, attempt)
    delay = min(cap, base * (2**attempt))
    spread = delay * jitter
    draw = random.random if rand is None else rand
    return delay - spread + draw() * 2 * spread


class ReconnectBackoff:
    """Stateful ladder for one listener loop: ``delay()`` per failure, ``reset()`` on success."""

    def __init__(
        self,
        *,
        base: float,
        cap: float,
        jitter: float = DEFAULT_JITTER,
        rand: Callable[[], float] | None = None,
    ) -> None:
        self._base = base
        self._cap = cap
        self._jitter = jitter
        self._rand = rand
        self._failures = 0

    def delay(self) -> float:
        """Return the next retry delay and count the failure it answers."""
        delay = backoff_delay(
            self._failures,
            base=self._base,
            cap=self._cap,
            jitter=self._jitter,
            rand=self._rand,
        )
        self._failures += 1
        return delay

    def reset(self) -> None:
        self._failures = 0

    @property
    def failures(self) -> int:
        return self._failures
