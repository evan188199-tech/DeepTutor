"""Tests for the shared source-sync base class."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

import deeptutor.services.base_sync as base_sync
from deeptutor.services.base_sync import BaseSourceSyncService, default_base_dir, is_stale

# Fixed "now" so freshness-window boundaries are exact.
_FIXED_NOW = datetime(2026, 1, 2, 12, 0, 0, tzinfo=timezone.utc)


class _FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return _FIXED_NOW


@pytest.fixture
def frozen_now(monkeypatch):
    monkeypatch.setattr(base_sync, "datetime", _FixedDatetime)


# ── is_stale: freshness window boundaries ────────────────────────────


def test_is_stale_missing_key(frozen_now):
    assert is_stale({"id": "s"}) is True


def test_is_stale_none_value(frozen_now):
    assert is_stale({"id": "s", "last_synced_at": None}) is True


def test_is_stale_empty_value(frozen_now):
    assert is_stale({"id": "s", "last_synced_at": ""}) is True


def test_is_stale_invalid_timestamp(frozen_now):
    assert is_stale({"id": "s", "last_synced_at": "not-a-date"}) is True


def test_is_stale_exactly_at_window_boundary_is_stale(frozen_now):
    # Exactly stale_hours old → age >= threshold → stale (inclusive boundary).
    assert is_stale({"last_synced_at": "2026-01-01T12:00:00+00:00"}) is True


def test_is_stale_just_inside_window_is_fresh(frozen_now):
    assert is_stale({"last_synced_at": "2026-01-01T12:00:01+00:00"}) is False


def test_is_stale_naive_timestamp_treated_as_utc_at_boundary(frozen_now):
    # Naive timestamps are assumed UTC: exactly 24h old → stale.
    assert is_stale({"last_synced_at": "2026-01-01T12:00:00"}) is True
    assert is_stale({"last_synced_at": "2026-01-01T12:00:01"}) is False


def test_is_stale_offset_timestamp_compared_instant_aware(frozen_now):
    # 14:00+02:00 is 12:00Z — exactly at the boundary → stale.
    assert is_stale({"last_synced_at": "2026-01-01T14:00:00+02:00"}) is True


def test_is_stale_future_timestamp_is_fresh(frozen_now):
    assert is_stale({"last_synced_at": "2026-01-02T13:00:00+00:00"}) is False


def test_is_stale_custom_window_boundaries(frozen_now):
    # stale_hours=0.5 → boundary at exactly 30 minutes.
    assert is_stale({"last_synced_at": "2026-01-02T11:30:00+00:00"}, stale_hours=0.5) is True
    assert is_stale({"last_synced_at": "2026-01-02T11:30:01+00:00"}, stale_hours=0.5) is False


# ── default_base_dir ─────────────────────────────────────────────────


class _FakePathService:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root


def test_default_base_dir_uses_path_service(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "deeptutor.services.path_service.get_path_service",
        lambda: _FakePathService(tmp_path),
    )
    assert default_base_dir() == str(tmp_path / "data" / "knowledge_bases")


def test_default_base_dir_falls_back_when_path_service_fails(monkeypatch):
    def _boom():
        raise RuntimeError("path service unavailable")

    monkeypatch.setattr("deeptutor.services.path_service.get_path_service", _boom)
    from deeptutor.knowledge.add_documents import DEFAULT_BASE_DIR

    assert default_base_dir() == DEFAULT_BASE_DIR


# ── BaseSourceSyncService: construction & abstract contract ──────────


class _RecordingService(BaseSourceSyncService):
    """Minimal concrete subclass that records cycle calls."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.calls = 0
        self.first_cycle = asyncio.Event()
        self.fail_first = False
        self.stop_after = None  # stop the loop after N calls

    async def _sync_one_cycle(self) -> None:
        self.calls += 1
        if self.calls == 1:
            self.first_cycle.set()
            if self.fail_first:
                raise RuntimeError("cycle failed")
        if self.stop_after is not None and self.calls >= self.stop_after:
            self._running = False


def test_base_class_cannot_be_instantiated():
    with pytest.raises(TypeError):
        BaseSourceSyncService()


def test_subclass_without_cycle_impl_cannot_be_instantiated():
    class _Incomplete(BaseSourceSyncService):
        pass

    with pytest.raises(TypeError):
        _Incomplete()


def test_constructor_defaults():
    service = _RecordingService()
    assert service.task_name == "source-sync"
    assert service._check_interval_s == 3600
    assert service._base_dir is None
    assert service._running is False
    assert service._task is None


def test_effective_base_dir_prefers_explicit(monkeypatch):
    def _unexpected_default():
        raise AssertionError("default_base_dir must not be called")

    monkeypatch.setattr(base_sync, "default_base_dir", _unexpected_default)
    service = _RecordingService(base_dir="/explicit/kbs")
    assert service.effective_base_dir == "/explicit/kbs"


def test_effective_base_dir_falls_back_to_default(monkeypatch):
    monkeypatch.setattr(base_sync, "default_base_dir", lambda: "/default/kbs")
    service = _RecordingService()
    assert service.effective_base_dir == "/default/kbs"


# ── lifecycle: start/stop, re-entry protection ───────────────────────


@pytest.mark.asyncio
async def test_start_creates_named_task_and_stop_cancels():
    service = _RecordingService(base_dir="/kbs", check_interval_s=0)
    await service.start()
    assert service._running is True
    assert service._task is not None
    assert service._task.get_name() == "source-sync"
    assert not service._task.done()

    await asyncio.wait_for(service.first_cycle.wait(), timeout=5)

    await service.stop()
    assert service._running is False
    assert service._task is None
    assert service.calls >= 1


@pytest.mark.asyncio
async def test_start_twice_keeps_single_task():
    service = _RecordingService(base_dir="/kbs", check_interval_s=0)
    await service.start()
    first_task = service._task
    await service.start()
    assert service._task is first_task
    await service.stop()


@pytest.mark.asyncio
async def test_stop_without_start_is_a_noop():
    service = _RecordingService()
    await service.stop()
    assert service._running is False
    assert service._task is None


@pytest.mark.asyncio
async def test_stop_with_already_finished_task():
    service = _RecordingService(base_dir="/kbs", check_interval_s=0)
    service.stop_after = 1
    await service.start()
    await asyncio.wait_for(_wait_task_done(service._task), timeout=5)
    await service.stop()
    assert service._task is None
    assert service.calls == 1


@pytest.mark.asyncio
async def test_restart_after_stop_creates_new_task():
    service = _RecordingService(base_dir="/kbs", check_interval_s=0)
    await service.start()
    first_task = service._task
    await service.stop()

    service.first_cycle.clear()
    await service.start()
    assert service._task is not first_task
    assert service._task is not None
    await service.stop()


async def _wait_task_done(task: asyncio.Task) -> None:
    while not task.done():
        await asyncio.sleep(0)


# ── loop behaviour: iteration & failure resilience ────────────────────


@pytest.mark.asyncio
async def test_loop_runs_cycles_until_stopped():
    service = _RecordingService(check_interval_s=0)
    service._running = True  # normally set by start()
    service.stop_after = 3
    await service._loop()
    assert service.calls == 3


@pytest.mark.asyncio
async def test_loop_survives_cycle_failure_and_continues():
    service = _RecordingService(check_interval_s=0)
    service._running = True  # normally set by start()
    service.fail_first = True
    service.stop_after = 3
    await service._loop()  # must not raise despite first cycle failing
    assert service.calls == 3
