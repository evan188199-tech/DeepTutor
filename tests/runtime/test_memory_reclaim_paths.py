"""Boundary coverage for best-effort memory reclamation."""

from __future__ import annotations

import asyncio
import gc
import sys
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.runtime import memory_reclaim


def test_non_linux_release_skips_malloc_trim(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(memory_reclaim.sys, "platform", "darwin")
    monkeypatch.setattr(gc, "collect", lambda: 5)
    assert memory_reclaim.release_unused_memory() == (5, False)


def test_linux_release_trims_when_malloc_trim_is_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(memory_reclaim.sys, "platform", "linux")
    monkeypatch.setattr(gc, "collect", lambda: 2)
    pads: list[int] = []

    class _FakeTrim:
        argtypes: list[Any] = []
        restype: Any = None

        def __call__(self, pad: int) -> int:
            pads.append(pad)
            return 1

    fake_ctypes = SimpleNamespace(
        CDLL=lambda _name: SimpleNamespace(malloc_trim=_FakeTrim()),
        c_size_t=int,
        c_int=int,
    )
    monkeypatch.setitem(sys.modules, "ctypes", fake_ctypes)
    assert memory_reclaim.release_unused_memory() == (2, True)
    assert pads == [0]


def test_linux_release_without_malloc_trim_stays_portable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if sys.platform.startswith("linux"):
        pytest.skip("glibc always exposes malloc_trim")
    monkeypatch.setattr(memory_reclaim.sys, "platform", "linux")
    collected, trimmed = memory_reclaim.release_unused_memory()
    assert trimmed is False
    assert isinstance(collected, int)


def test_release_swallows_malloc_trim_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(memory_reclaim.sys, "platform", "linux")
    monkeypatch.setattr(gc, "collect", lambda: 1)

    def _broken_cdll(_name: object) -> Any:
        raise RuntimeError("no libc handle")

    fake_ctypes = SimpleNamespace(CDLL=_broken_cdll)
    monkeypatch.setitem(sys.modules, "ctypes", fake_ctypes)
    assert memory_reclaim.release_unused_memory() == (1, False)


def test_schedule_without_a_running_loop_returns_none() -> None:
    assert memory_reclaim.schedule_memory_reclaim() is None


@pytest.mark.asyncio
async def test_completed_reclaim_is_replaced_by_a_fresh_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(memory_reclaim, "release_unused_memory", lambda: (1, False))

    first = memory_reclaim.schedule_memory_reclaim()
    assert first is not None
    assert await first == (1, False)
    await asyncio.sleep(0)
    assert memory_reclaim._reclaim_tasks == {}

    second = memory_reclaim.schedule_memory_reclaim()
    assert second is not None
    assert second is not first
    assert await second == (1, False)
    await asyncio.sleep(0)
    assert memory_reclaim._reclaim_tasks == {}


@pytest.mark.asyncio
async def test_failed_reclaim_task_is_replaced_on_the_next_schedule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom() -> tuple[int, bool]:
        raise RuntimeError("reclaim exploded")

    monkeypatch.setattr(memory_reclaim, "release_unused_memory", _boom)
    failed = memory_reclaim.schedule_memory_reclaim()
    assert failed is not None
    with pytest.raises(RuntimeError, match="reclaim exploded"):
        await failed
    await asyncio.sleep(0)
    assert memory_reclaim._reclaim_tasks == {}

    monkeypatch.setattr(memory_reclaim, "release_unused_memory", lambda: (0, False))
    retry = memory_reclaim.schedule_memory_reclaim()
    assert retry is not None
    assert retry is not failed
    assert await retry == (0, False)
