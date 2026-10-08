"""Scheduler durability tests for upstream #902 test debt.

Covers schedule/job persistence, cancellation semantics, recovery after
partial failures, and non-web KB isolation for the SQLite-backed
web-source sync scheduler.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import time
from unittest.mock import AsyncMock, patch

import pytest

from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.services.web_source.repository import SQLiteWebSourceSyncRepository
from deeptutor.services.web_source.scheduler import (
    WEB_SYNC_INTERVAL_HOURS,
    WEB_SYNC_MAX_INTERVAL_HOURS,
    WEB_SYNC_MIN_INTERVAL_HOURS,
    WebSourceSyncScheduler,
    normalize_sync_interval,
)
from deeptutor.services.web_source.sync import WebSyncResult

SYNC_TARGET = "deeptutor.services.web_source.sync.sync_source"
OWNER = "local-admin"
KB = "kb"
LEASE_MS = 3_600_000


def _make_manager(tmp_path: Path, *kb_names: str) -> KnowledgeBaseManager:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    for name in kb_names:
        (manager.base_dir / name).mkdir(parents=True, exist_ok=True)
        (manager.base_dir / name / "metadata.json").write_text("{}", encoding="utf-8")
        manager.register_knowledge_base(name)
    return manager


def _make_scheduler(manager: KnowledgeBaseManager, repository) -> WebSourceSyncScheduler:
    return WebSourceSyncScheduler(repository=repository, manager_factory=lambda: manager)


def _claim(repository: SQLiteWebSourceSyncRepository, key, runner_id: str = "runner-a"):
    job = repository.get(key)
    assert job is not None
    claimed = repository.claim(
        job, runner_id=runner_id, lease_until_ms=int(time.time() * 1000) + LEASE_MS
    )
    assert claimed is not None
    return claimed


async def _seed_scheduled_job(tmp_path: Path, url: str = "https://example.com/docs/"):
    manager = _make_manager(tmp_path, KB)
    manager.add_web_source(KB, url)
    repository = SQLiteWebSourceSyncRepository(tmp_path / "jobs.sqlite")
    scheduler = _make_scheduler(manager, repository)
    await scheduler._synchronize_sources()
    job = repository.list_jobs(OWNER, KB)[0]
    return manager, repository, scheduler, job, repository.key(job)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def test_job_rows_survive_repository_reopen(tmp_path: Path) -> None:
    path = tmp_path / "jobs.sqlite"
    repository = SQLiteWebSourceSyncRepository(path)
    key = OWNER, KB, "abc"
    repository.reconcile_sources({key})
    claimed = _claim(repository, key)
    repository.mark_failure(
        claimed, error="first crawl failed", next_run_at_ms=int(time.time() * 1000) + LEASE_MS
    )

    reopened = SQLiteWebSourceSyncRepository(path)
    persisted = reopened.get(key)
    assert persisted is not None
    assert persisted.state == "error"
    assert persisted.attempt == 1
    assert persisted.error == "first crawl failed"
    assert persisted.runner_id == ""
    assert persisted.lease_until_ms is None
    assert reopened.due_jobs() == []


def test_reconcile_preserves_existing_job_state(tmp_path: Path) -> None:
    repository = SQLiteWebSourceSyncRepository(tmp_path / "jobs.sqlite")
    key = OWNER, KB, "abc"
    repository.reconcile_sources({key})
    claimed = _claim(repository, key)
    repository.mark_failure(
        claimed, error="boom", next_run_at_ms=int(time.time() * 1000) + LEASE_MS
    )

    repository.reconcile_sources({key})

    after = repository.get(key)
    assert after is not None
    assert after.state == "error"
    assert after.attempt == 1
    assert after.error == "boom"


def test_due_jobs_returns_only_due_runnable_rows_in_order(tmp_path: Path) -> None:
    repository = SQLiteWebSourceSyncRepository(tmp_path / "jobs.sqlite")
    now = int(time.time() * 1000)
    keys = {
        (OWNER, KB, "due"),
        (OWNER, KB, "running"),
        (OWNER, KB, "cancelled"),
        (OWNER, KB, "future"),
        (OWNER, KB, "error"),
    }
    repository.reconcile_sources(keys)

    claimed = _claim(repository, (OWNER, KB, "error"))
    repository.mark_failure(claimed, error="boom", next_run_at_ms=now - 60_000)
    _claim(repository, (OWNER, KB, "running"))
    claimed = _claim(repository, (OWNER, KB, "future"))
    repository.mark_success(claimed, now + 1_000_000_000)
    assert repository.request_cancel((OWNER, KB, "cancelled")) is True

    due = repository.due_jobs()
    assert [job.source_id for job in due] == ["error", "due"]


def test_normalize_sync_interval_clamps_to_configured_bounds() -> None:
    assert normalize_sync_interval(0) == WEB_SYNC_MIN_INTERVAL_HOURS
    assert normalize_sync_interval(-5) == WEB_SYNC_MIN_INTERVAL_HOURS
    assert normalize_sync_interval(10_000) == WEB_SYNC_MAX_INTERVAL_HOURS
    assert normalize_sync_interval("not-a-number") == WEB_SYNC_INTERVAL_HOURS
    assert normalize_sync_interval(None) == WEB_SYNC_INTERVAL_HOURS
    assert normalize_sync_interval(6) == 6


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


def test_request_cancel_rejects_unknown_and_terminal_jobs(tmp_path: Path) -> None:
    repository = SQLiteWebSourceSyncRepository(tmp_path / "jobs.sqlite")
    key = OWNER, KB, "abc"
    assert repository.request_cancel(key) is False

    repository.reconcile_sources({key})
    assert repository.request_cancel(key) is True
    cancelled = repository.get(key)
    assert cancelled is not None
    assert cancelled.state == "cancelled"
    assert cancelled.cancel_requested is False
    assert repository.request_cancel(key) is False

    retried = repository.retry(key)
    assert retried is not None and retried.state == "pending"
    assert repository.request_cancel(key) is True


@pytest.mark.asyncio
async def test_cancel_request_before_sync_marks_cancelled_and_skips_crawl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _manager, repository, scheduler, job, key = await _seed_scheduled_job(tmp_path)
    original_claim = repository.claim

    def claim_then_request_cancel(src_job, *, runner_id, lease_until_ms):
        claimed = original_claim(src_job, runner_id=runner_id, lease_until_ms=lease_until_ms)
        if claimed is not None:
            repository.request_cancel(key)
        return claimed

    monkeypatch.setattr(repository, "claim", claim_then_request_cancel)

    sync = AsyncMock(return_value=WebSyncResult(ok=True))
    with patch(SYNC_TARGET, sync):
        await scheduler._run_job(job)

    sync.assert_not_awaited()
    persisted = repository.get(key)
    assert persisted is not None
    assert persisted.state == "cancelled"
    assert persisted.cancel_requested is False


@pytest.mark.asyncio
async def test_cancel_request_after_sync_blocks_success(tmp_path: Path) -> None:
    _manager, repository, scheduler, job, key = await _seed_scheduled_job(tmp_path)

    async def ok_then_request_cancel(**_kwargs):
        repository.request_cancel(key)
        return WebSyncResult(ok=True)

    with patch(SYNC_TARGET, ok_then_request_cancel):
        await scheduler._run_job(job)

    persisted = repository.get(key)
    assert persisted is not None
    assert persisted.state == "cancelled"
    assert persisted.attempt == 0


@pytest.mark.asyncio
async def test_cancelled_error_with_pending_cancel_marks_cancelled(tmp_path: Path) -> None:
    _manager, repository, scheduler, job, key = await _seed_scheduled_job(tmp_path)

    async def cancel_mid_sync(**_kwargs):
        repository.request_cancel(key)
        raise asyncio.CancelledError

    with patch(SYNC_TARGET, cancel_mid_sync):
        with pytest.raises(asyncio.CancelledError):
            await scheduler._run_job(job)

    persisted = repository.get(key)
    assert persisted is not None
    assert persisted.state == "cancelled"


@pytest.mark.asyncio
async def test_request_cancel_stops_a_running_task(tmp_path: Path) -> None:
    _manager, repository, scheduler, _job, key = await _seed_scheduled_job(tmp_path)

    entered = asyncio.Event()
    release = asyncio.Event()

    async def gated_sync(**_kwargs):
        entered.set()
        await release.wait()
        return WebSyncResult(ok=True)

    with patch(SYNC_TARGET, gated_sync):
        scheduler._start_due_jobs()
        task = scheduler._run_tasks[key]
        await asyncio.wait_for(entered.wait(), 5)
        assert await scheduler.request_cancel(*key) is True
        assert await scheduler.request_cancel(OWNER, KB, "missing") is False
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)

    persisted = repository.get(key)
    assert persisted is not None
    assert persisted.state == "cancelled"


# ---------------------------------------------------------------------------
# Recovery after partial failures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_sync_backs_off_then_manual_retry_recovers(tmp_path: Path) -> None:
    _manager, repository, scheduler, job, key = await _seed_scheduled_job(tmp_path)

    failing = AsyncMock(return_value=WebSyncResult(ok=False, error="crawl failed"))
    with patch(SYNC_TARGET, failing):
        await scheduler._run_job(job)

    failed = repository.get(key)
    assert failed is not None
    assert failed.state == "error"
    assert failed.attempt == 1
    assert failed.error == "crawl failed"
    assert repository.due_jobs() == []

    retried = repository.retry(key)
    assert retried is not None and retried.state == "pending"
    assert repository.due_jobs() != []

    succeeding = AsyncMock(return_value=WebSyncResult(ok=True))
    with patch(SYNC_TARGET, succeeding):
        await scheduler._run_job(repository.get(key))

    recovered = repository.get(key)
    assert recovered is not None
    assert recovered.state == "pending"
    assert recovered.attempt == 0
    assert recovered.error is None
    assert recovered.next_run_at_ms > recovered.last_run_at_ms


@pytest.mark.asyncio
async def test_sync_exception_marks_error_with_backoff(tmp_path: Path) -> None:
    _manager, repository, scheduler, job, key = await _seed_scheduled_job(tmp_path)

    boom = AsyncMock(side_effect=RuntimeError("network unreachable"))
    with patch(SYNC_TARGET, boom):
        await scheduler._run_job(job)

    failed = repository.get(key)
    assert failed is not None
    assert failed.state == "error"
    assert failed.attempt == 1
    assert "network unreachable" in failed.error
    assert failed.next_run_at_ms - failed.last_run_at_ms >= (
        WEB_SYNC_MIN_INTERVAL_HOURS * 3_600_000 - 60_000
    )


@pytest.mark.asyncio
async def test_restarted_scheduler_recovers_interrupted_job(tmp_path: Path) -> None:
    manager, repository, _scheduler, job, key = await _seed_scheduled_job(tmp_path)
    crashed = repository.claim(
        job,
        runner_id="crashed-runner",
        lease_until_ms=int(time.time() * 1000) - 1_000,
    )
    assert crashed is not None

    restarted = _make_scheduler(manager, repository)
    restarted.repo.recover_interrupted(restarted._runner_id)
    await restarted._synchronize_sources()

    recovered = repository.get(key)
    assert recovered is not None
    assert recovered.state == "interrupted"
    assert recovered.runner_id == ""
    due = restarted.repo.due_jobs()
    assert [(item.owner_id, item.kb_name, item.source_id) for item in due] == [key]

    succeeding = AsyncMock(return_value=WebSyncResult(ok=True))
    with patch(SYNC_TARGET, succeeding):
        await restarted._run_job(repository.get(key))

    done = repository.get(key)
    assert done is not None
    assert done.state == "pending"
    assert done.attempt == 0


@pytest.mark.asyncio
async def test_start_due_jobs_honors_concurrency_cap(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path, KB)
    for index in range(3):
        manager.add_web_source(KB, f"https://example{index}.com/docs/")
    repository = SQLiteWebSourceSyncRepository(tmp_path / "jobs.sqlite")
    scheduler = _make_scheduler(manager, repository)
    await scheduler._synchronize_sources()
    jobs = repository.list_jobs(OWNER, KB)
    assert len(jobs) == 3

    events = {job.source_id: asyncio.Event() for job in jobs}

    async def gated_sync(*, source, **_kwargs):
        await events[source["id"]].wait()
        return WebSyncResult(ok=True)

    with patch(SYNC_TARGET, gated_sync):
        scheduler._start_due_jobs()
        assert len(scheduler._run_tasks) == 2
        for event in events.values():
            event.set()
        await asyncio.gather(*list(scheduler._run_tasks.values()))
        for _ in range(5):
            await asyncio.sleep(0)
        assert len(scheduler._run_tasks) == 0
        scheduler._start_due_jobs()
        assert len(scheduler._run_tasks) == 1
        await asyncio.gather(*list(scheduler._run_tasks.values()))

    assert all(job.state == "pending" for job in repository.list_jobs(OWNER, KB))


# ---------------------------------------------------------------------------
# Non-web KB isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_web_kb_stays_isolated_from_scheduler(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path, "web-kb", "plain-kb")
    source = manager.add_web_source("web-kb", "https://example.com/docs/")
    repository = SQLiteWebSourceSyncRepository(tmp_path / "jobs.sqlite")
    scheduler = _make_scheduler(manager, repository)

    await scheduler._synchronize_sources()

    web_jobs = repository.list_jobs(OWNER, "web-kb")
    assert [job.source_id for job in web_jobs] == [source["id"]]
    assert repository.list_jobs(OWNER, "plain-kb") == []
    assert scheduler._sources.keys() == {(OWNER, "web-kb", source["id"])}

    assert manager.remove_web_source("web-kb", source["id"]) is True
    await scheduler._synchronize_sources()

    assert repository.list_jobs(OWNER, "web-kb") == []
    assert repository.get((OWNER, "web-kb", source["id"])) is None
    assert repository.list_jobs(OWNER, "plain-kb") == []


@pytest.mark.asyncio
async def test_one_source_failure_leaves_sibling_sources_untouched(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path, KB)
    good = manager.add_web_source(KB, "https://good.example.com/docs/")
    bad = manager.add_web_source(KB, "https://bad.example.com/docs/")
    repository = SQLiteWebSourceSyncRepository(tmp_path / "jobs.sqlite")
    scheduler = _make_scheduler(manager, repository)
    await scheduler._synchronize_sources()

    async def dispatch_sync(*, source, **_kwargs):
        if source["id"] == bad["id"]:
            return WebSyncResult(ok=False, error="crawl failed")
        return WebSyncResult(ok=True)

    with patch(SYNC_TARGET, dispatch_sync):
        scheduler._start_due_jobs()
        await asyncio.gather(*list(scheduler._run_tasks.values()))

    good_job = repository.get((OWNER, KB, good["id"]))
    bad_job = repository.get((OWNER, KB, bad["id"]))
    assert good_job is not None and bad_job is not None
    assert good_job.state == "pending"
    assert good_job.attempt == 0
    assert good_job.next_run_at_ms > good_job.last_run_at_ms
    assert bad_job.state == "error"
    assert bad_job.attempt == 1
    assert bad_job.error == "crawl failed"
