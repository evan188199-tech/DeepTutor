"""Gap tests for the web-source sync follow-ups (#902 remaining scope).

Focus: recovery semantics after a partially failed sync (indexing or page
removal), scheduler retry/resume behavior across those failures, and
isolation guarantees — web-source bookkeeping must never delete or rewrite
non-web documents in the same KB, and KBs without web sources must stay
untouched by the scheduler.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from deeptutor.knowledge.add_documents import remove_raw_document
from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.services.web_source.crawler import (
    CrawledPage,
    CrawlResult,
    _source_filename,
)
from deeptutor.services.web_source.repository import SQLiteWebSourceSyncRepository
from deeptutor.services.web_source.scheduler import WebSourceSyncScheduler
from deeptutor.services.web_source.sync import WebSyncResult, sync_source


def _make_manager(tmp_path: Path) -> KnowledgeBaseManager:
    return KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))


def _register_kb(manager: KnowledgeBaseManager, kb_name: str) -> Path:
    kb_dir = manager.base_dir / kb_name
    (kb_dir / "raw").mkdir(parents=True)
    manager.register_knowledge_base(kb_name)
    (kb_dir / "metadata.json").write_text("{}", encoding="utf-8")
    return kb_dir


def _page(url: str, markdown: str, content_hash: str) -> CrawledPage:
    return CrawledPage(url=url, title=url, markdown=markdown, content_hash=content_hash)


def _seed_hashes(
    manager: KnowledgeBaseManager, kb_name: str, source: dict, hashes: dict[str, str]
) -> None:
    source["page_hashes"] = hashes
    manager.update_web_source_state(kb_name, source["id"], page_hashes=hashes)


def _set_file_hashes(kb_dir: Path, file_hashes: dict[str, str]) -> None:
    metadata_path = kb_dir / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["file_hashes"] = file_hashes
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")


# ── recovery after a partially failed sync (on-demand axis) ─────────


@pytest.mark.asyncio
async def test_sync_after_indexing_failure_reindexes_changed_pages(tmp_path: Path):
    """A failed index run must not advance hashes, and a retry must re-index
    the same changed page and clear the error state."""
    manager = _make_manager(tmp_path)
    kb_dir = _register_kb(manager, "kb")
    source = manager.add_web_source("kb", "https://example.com/docs/")
    base_dir = str(manager.base_dir)
    name = _source_filename(source, "https://example.com/docs/", "/docs/")
    _seed_hashes(manager, "kb", source, {name: "old"})
    raw_file = kb_dir / "raw" / name
    raw_file.parent.mkdir(parents=True, exist_ok=True)
    raw_file.write_text("old page", encoding="utf-8")

    crawl = CrawlResult(pages=[_page("https://example.com/docs/", "new page", "new")])

    with patch(
        "deeptutor.services.web_source.crawler.crawl_docs_site", AsyncMock(return_value=crawl)
    ):
        with patch(
            "deeptutor.knowledge.add_documents.add_documents",
            AsyncMock(side_effect=RuntimeError("index unavailable")),
        ):
            outcome = await sync_source("kb", source, base_dir=base_dir)

    assert outcome.ok is False
    assert "index unavailable" in outcome.error
    # Partial state: raw content was re-staged, but hashes and status stopped.
    assert raw_file.read_text(encoding="utf-8") == "new page"
    stored = manager.get_web_sources("kb")[0]
    assert stored["page_hashes"] == {name: "old"}
    assert stored["last_sync_status"] == "error"

    with patch(
        "deeptutor.services.web_source.crawler.crawl_docs_site", AsyncMock(return_value=crawl)
    ):
        with patch(
            "deeptutor.knowledge.add_documents.add_documents", AsyncMock(return_value=1)
        ) as retried:
            outcome = await sync_source("kb", source, base_dir=base_dir)

    assert outcome.ok is True
    assert outcome.pages_updated == 1
    retried.assert_awaited_once()
    stored = manager.get_web_sources("kb")[0]
    assert stored["page_hashes"] == {name: "new"}
    assert stored["last_sync_status"] == "success"
    assert stored["last_sync_error"] is None


@pytest.mark.asyncio
async def test_sync_after_removal_failure_retries_page_removal(tmp_path: Path):
    """A removal failure must keep the deleted page and its hash record so the
    next sync retries the purge instead of losing it."""
    manager = _make_manager(tmp_path)
    kb_dir = _register_kb(manager, "kb")
    source = manager.add_web_source("kb", "https://example.com/docs/")
    old_name = _source_filename(source, "https://example.com/docs/old", "/docs/")
    source["page_hashes"] = {old_name: "oldh"}
    manager.update_web_source_state("kb", source["id"], page_hashes=source["page_hashes"])
    old_path = kb_dir / "raw" / old_name
    old_path.parent.mkdir(parents=True, exist_ok=True)
    old_path.write_text("old page", encoding="utf-8")
    _set_file_hashes(kb_dir, {old_name: "oldh"})

    crawl = CrawlResult(pages=[_page("https://example.com/docs/current", "current page", "newh")])

    def flaky_remove(kb_dir_arg, file_path):
        if str(file_path).endswith(old_name):
            raise RuntimeError("disk busy")
        return remove_raw_document(kb_dir_arg, file_path)

    with patch(
        "deeptutor.services.web_source.crawler.crawl_docs_site", AsyncMock(return_value=crawl)
    ):
        with patch(
            "deeptutor.knowledge.add_documents.remove_raw_document",
            side_effect=flaky_remove,
        ):
            outcome = await sync_source("kb", source, base_dir=str(manager.base_dir))

    assert outcome.ok is False
    assert "Failed to remove" in outcome.error
    assert old_path.exists()
    stored = manager.get_web_sources("kb")[0]
    assert stored["page_hashes"] == {old_name: "oldh"}
    assert stored["last_sync_status"] == "error"

    with patch(
        "deeptutor.services.web_source.crawler.crawl_docs_site", AsyncMock(return_value=crawl)
    ):
        with patch(
            "deeptutor.services.rag.service.RAGService.initialize",
            AsyncMock(return_value=True),
        ) as rebuild:
            outcome = await sync_source("kb", source, base_dir=str(manager.base_dir))

    assert outcome.ok is True
    assert outcome.pages_removed == 1
    assert not old_path.exists()
    stored = manager.get_web_sources("kb")[0]
    assert old_name not in stored["page_hashes"]
    metadata = json.loads((kb_dir / "metadata.json").read_text(encoding="utf-8"))
    assert old_name not in metadata["file_hashes"]
    rebuilt = rebuild.await_args.kwargs["file_paths"]
    assert all(old_name not in path for path in rebuilt)


# ── scheduler retry/resume across partial failures ───────────────────


@pytest.mark.asyncio
async def test_scheduler_failure_backoff_then_retry_succeeds(tmp_path: Path):
    """A failed sync run lands in the error state with attempt+1 and a
    deferred next run; a manual retry resets it and a later run succeeds."""
    manager = _make_manager(tmp_path)
    _register_kb(manager, "kb")
    manager.add_web_source("kb", "https://example.com/docs/")

    repository = SQLiteWebSourceSyncRepository(tmp_path / "jobs.sqlite")
    scheduler = WebSourceSyncScheduler(repository=repository, manager_factory=lambda: manager)
    await scheduler._synchronize_sources()
    job = repository.list_jobs("local-admin", "kb")[0]

    with patch(
        "deeptutor.services.web_source.sync.sync_source",
        AsyncMock(return_value=WebSyncResult(ok=False, error="site unreachable")),
    ):
        await scheduler._run_job(job)

    persisted = repository.get(repository.key(job))
    assert persisted is not None
    assert persisted.state == "error"
    assert persisted.attempt == 1
    assert persisted.error == "site unreachable"
    assert persisted.runner_id == ""
    assert persisted.lease_until_ms is None
    assert persisted.next_run_at_ms > persisted.last_run_at_ms  # type: ignore[operator]
    deferred = [item for item in repository.due_jobs() if item.source_id == job.source_id]
    assert deferred == []

    retried = repository.retry(repository.key(job))
    assert retried is not None
    assert retried.state == "pending"
    assert retried.attempt == 0
    assert retried.error is None

    with patch(
        "deeptutor.services.web_source.sync.sync_source",
        AsyncMock(return_value=WebSyncResult(ok=True)),
    ) as sync:
        await scheduler._run_job(repository.get(repository.key(job)))

    persisted = repository.get(repository.key(job))
    assert persisted is not None
    assert persisted.state == "pending"
    assert persisted.attempt == 0
    assert persisted.next_run_at_ms > persisted.last_run_at_ms  # type: ignore[operator]
    sync.assert_awaited_once()


@pytest.mark.asyncio
async def test_scheduler_interrupts_job_without_scanned_source_then_recovers(tmp_path: Path):
    """A job whose source inventory is not readable yet must be interrupted
    (kept retryable), never silently dropped or marked successful."""
    manager = _make_manager(tmp_path)
    _register_kb(manager, "kb")
    source = manager.add_web_source("kb", "https://example.com/docs/")

    repository = SQLiteWebSourceSyncRepository(tmp_path / "jobs.sqlite")
    key = ("local-admin", "kb", source["id"])
    repository.reconcile_sources({key})
    scheduler = WebSourceSyncScheduler(repository=repository, manager_factory=lambda: manager)

    job = repository.list_jobs("local-admin", "kb")[0]
    with patch(
        "deeptutor.services.web_source.sync.sync_source",
        AsyncMock(return_value=WebSyncResult(ok=True)),
    ) as sync:
        await scheduler._run_job(job)

    sync.assert_not_awaited()
    interrupted = repository.get(key)
    assert interrupted is not None
    assert interrupted.state == "interrupted"
    assert any(item.source_id == source["id"] for item in repository.due_jobs())

    await scheduler._synchronize_sources()
    job = repository.list_jobs("local-admin", "kb")[0]
    with patch(
        "deeptutor.services.web_source.sync.sync_source",
        AsyncMock(return_value=WebSyncResult(ok=True)),
    ) as sync:
        await scheduler._run_job(job)

    recovered = repository.get(key)
    assert recovered is not None
    assert recovered.state == "pending"
    sync.assert_awaited_once()


# ── isolation from non-web data ──────────────────────────────────────


@pytest.mark.asyncio
async def test_web_source_removal_preserves_non_web_documents_in_same_kb(tmp_path: Path):
    """Purging a removed web page must touch only that page: uploaded
    non-web documents survive, keep their hash record, and stay in the
    index rebuild."""
    manager = _make_manager(tmp_path)
    kb_dir = _register_kb(manager, "kb")
    source = manager.add_web_source("kb", "https://example.com/docs/")
    old_name = _source_filename(source, "https://example.com/docs/old", "/docs/")
    current_name = _source_filename(source, "https://example.com/docs/current", "/docs/")
    source["page_hashes"] = {old_name: "oldh"}
    manager.update_web_source_state("kb", source["id"], page_hashes=source["page_hashes"])

    old_path = kb_dir / "raw" / old_name
    old_path.parent.mkdir(parents=True, exist_ok=True)
    old_path.write_text("old page", encoding="utf-8")
    notes_path = kb_dir / "raw" / "notes.md"
    notes_path.write_text("user uploaded notes", encoding="utf-8")
    _set_file_hashes(kb_dir, {old_name: "oldh", "notes.md": "notes-hash"})

    crawl = CrawlResult(pages=[_page("https://example.com/docs/current", "current page", "newh")])
    with patch(
        "deeptutor.services.web_source.crawler.crawl_docs_site", AsyncMock(return_value=crawl)
    ):
        with patch(
            "deeptutor.services.rag.service.RAGService.initialize",
            AsyncMock(return_value=True),
        ) as rebuild:
            outcome = await sync_source("kb", source, base_dir=str(manager.base_dir))

    assert outcome.ok is True
    assert outcome.pages_removed == 1
    assert not old_path.exists()
    assert notes_path.exists()
    metadata = json.loads((kb_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["file_hashes"]["notes.md"] == "notes-hash"
    assert old_name not in metadata["file_hashes"]
    stored = manager.get_web_sources("kb")[0]
    assert stored["page_hashes"] == {current_name: "newh"}
    rebuilt = rebuild.await_args.kwargs["file_paths"]
    assert any(path.endswith("notes.md") for path in rebuilt)
    assert all(old_name not in path for path in rebuilt)


@pytest.mark.asyncio
async def test_scheduler_leaves_kbs_without_web_sources_alone(tmp_path: Path):
    """A KB with no web sources gets no scheduler jobs and no metadata or
    raw/ writes from a scheduler scan."""
    manager = _make_manager(tmp_path)
    _register_kb(manager, "webkb")
    plain_dir = _register_kb(manager, "plain")
    source = manager.add_web_source("webkb", "https://example.com/docs/")
    (plain_dir / "raw" / "manual.md").write_text("uploaded", encoding="utf-8")

    repository = SQLiteWebSourceSyncRepository(tmp_path / "jobs.sqlite")
    scheduler = WebSourceSyncScheduler(repository=repository, manager_factory=lambda: manager)
    await scheduler._synchronize_sources()

    assert [job.source_id for job in repository.list_jobs("local-admin", "webkb")] == [source["id"]]
    assert repository.list_jobs("local-admin", "plain") == []
    scanned_pairs = {(owner, kb) for owner, kb, _sid in scheduler._sources}
    assert ("local-admin", "plain") not in scanned_pairs

    plain_metadata = json.loads((plain_dir / "metadata.json").read_text(encoding="utf-8"))
    assert "web_sources" not in plain_metadata
    assert (plain_dir / "raw" / "manual.md").read_text(encoding="utf-8") == "uploaded"
