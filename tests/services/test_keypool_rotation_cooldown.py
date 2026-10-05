"""Supplementary KeyPool tests: cooldown boundaries, strike recovery, exhaustion, concurrency."""

from __future__ import annotations

import threading

import pytest

from deeptutor.services.keypool import KeyPool


def _fake_clock(monkeypatch: pytest.MonkeyPatch, start: float) -> dict[str, float]:
    from deeptutor.services import keypool as keypool_module

    now = {"value": start}
    monkeypatch.setattr(keypool_module, "monotonic", lambda: now["value"])
    return now


def test_keypool_rejects_a_pool_with_no_usable_keys() -> None:
    with pytest.raises(ValueError):
        KeyPool([])
    with pytest.raises(ValueError):
        KeyPool(["", "   "])


def test_keypool_strips_keys_and_drops_blanks() -> None:
    pool = KeyPool([" key-a ", "key-b", "   "])

    assert len(pool) == 2
    assert pool.next() == "key-a"
    assert pool.next() == "key-b"


def test_keypool_never_cools_after_a_single_429() -> None:
    """One strike is only a tally — rotation is untouched until the second."""
    pool = KeyPool(["key-a", "key-b"])

    pool.mark_429("key-a")

    assert [pool.next(), pool.next()] == ["key-a", "key-b"]


def test_keypool_ignores_marks_for_unknown_keys() -> None:
    pool = KeyPool(["key-a", "key-b"])

    pool.mark_429("not-in-pool")

    assert [pool.next(), pool.next()] == ["key-a", "key-b"]


def test_keypool_cooldown_expires_exactly_after_cooldown_s(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = _fake_clock(monkeypatch, start=10.0)
    pool = KeyPool(["key-a", "key-b"], cooldown_s=30)

    assert pool.next() == "key-a"
    pool.mark_429("key-a")
    pool.mark_429("key-a")

    now["value"] = 39.9
    assert pool.next() == "key-b"
    now["value"] = 40.0
    assert pool.next() == "key-a"


def test_keypool_cooldown_starts_at_the_second_strike(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = _fake_clock(monkeypatch, start=0.0)
    pool = KeyPool(["key-a", "key-b"], cooldown_s=30)

    pool.mark_429("key-a")
    now["value"] = 25.0
    pool.mark_429("key-a")

    now["value"] = 54.9
    assert pool.next() == "key-b"
    now["value"] = 55.0
    assert pool.next() == "key-a"


def test_keypool_resets_strikes_when_a_recovered_key_is_served(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A recovered key must earn a fresh pair of strikes before cooling again."""
    now = _fake_clock(monkeypatch, start=0.0)
    pool = KeyPool(["key-a", "key-b"], cooldown_s=20)

    pool.mark_429("key-a")
    pool.mark_429("key-a")
    now["value"] = 20.0
    assert pool.next() == "key-a"

    pool.mark_429("key-a")
    now["value"] = 21.0
    assert [pool.next(), pool.next(), pool.next()] == ["key-b", "key-a", "key-b"]


def test_keypool_with_zero_cooldown_serves_the_key_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_clock(monkeypatch, start=0.0)
    pool = KeyPool(["key-a", "key-b"], cooldown_s=0)

    pool.mark_429("key-a")
    pool.mark_429("key-a")

    assert pool.next() == "key-a"


def test_keypool_serves_the_soonest_recovering_key_when_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exhaustion still serves: keys come back in the order they cooled."""
    now = _fake_clock(monkeypatch, start=0.0)
    pool = KeyPool(["key-a", "key-b", "key-c"], cooldown_s=10)

    pool.mark_429("key-a")
    pool.mark_429("key-a")
    now["value"] = 1.0
    pool.mark_429("key-b")
    pool.mark_429("key-b")
    now["value"] = 2.0
    pool.mark_429("key-c")
    pool.mark_429("key-c")

    now["value"] = 3.0
    assert pool.next() == "key-a"

    now["value"] = 10.0
    assert pool.next() == "key-a"
    now["value"] = 10.5
    assert pool.next() == "key-a"

    now["value"] = 11.0
    assert pool.next() == "key-b"
    now["value"] = 12.0
    assert pool.next() == "key-c"


def test_keypool_balances_selection_across_threads() -> None:
    """Round-robin stays exact under contention — the lock makes each pick atomic."""
    keys = ["fake-key-1", "fake-key-2", "fake-key-3", "fake-key-4"]
    pool = KeyPool(keys)
    threads: list[threading.Thread] = []
    results: list[str] = []
    results_lock = threading.Lock()
    start = threading.Barrier(8)
    calls_per_thread = 50

    def pick() -> None:
        start.wait()
        picks = [pool.next() for _ in range(calls_per_thread)]
        with results_lock:
            results.extend(picks)

    for _ in range(8):
        thread = threading.Thread(target=pick)
        threads.append(thread)
        thread.start()
    for thread in threads:
        thread.join()

    assert len(results) == 8 * calls_per_thread
    assert set(results) == set(keys)
    assert [results.count(key) for key in keys] == [100, 100, 100, 100]


def test_keypool_survives_concurrent_selection_and_429_marks() -> None:
    """Interleaved next() and mark_429() never raise or hand out a foreign key."""
    keys = ["fake-key-1", "fake-key-2", "fake-key-3", "fake-key-4"]
    pool = KeyPool(keys)
    results: list[str] = []
    results_lock = threading.Lock()
    start = threading.Barrier(10)

    def pick(times: int) -> None:
        start.wait()
        for _ in range(times):
            key = pool.next()
            with results_lock:
                results.append(key)

    def strike(times: int) -> None:
        start.wait()
        for index in range(times):
            pool.mark_429(keys[index % len(keys)])

    threads = [threading.Thread(target=pick, args=(40,)) for _ in range(6)]
    threads += [threading.Thread(target=strike, args=(40,)) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(results) == 6 * 40
    assert set(results) <= set(keys)
