"""Offline lifecycle tests for web-source knowledge-base sync.

Drives the real crawl → diff → write → index → persist pipeline
(``crawl_docs_site`` → ``crawl_and_diff`` → ``sync_source``) against a
local ``httpx.MockTransport`` fixture site. No real HTTP egress happens:
every request, ``/robots.txt`` included, is served from an in-memory dict,
host checks are neutered, and pacing sleeps are stubbed.

Covered sync states:

- **added** — first sync persists crawled pages, hashes and success state.
- **updated** — a content change re-stages only the changed page.
- **failed** — a dead site marks the source ``error`` without advancing
  hashes or corrupting the raw snapshot; ``_fetch_page`` retries
  transient 5xx responses and gives up after ``_MAX_RETRIES``.
- **recovered** — the next healthy sync clears the error, skips
  unchanged pages, and re-attaches content staged during an indexing
  outage.

Plus snapshot/index consistency: raw/ files, persisted ``page_hashes``
and the (faked) retrieval index agree after changes and removals.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.services.web_source import crawler, robots
from deeptutor.services.web_source.crawler import (
    _MAX_RETRIES,
    _fetch_page,
    _source_filename,
)
from deeptutor.services.web_source.sync import sync_source

SITE_ORIGIN = "https://docs.example.com"
SEED_URL = f"{SITE_ORIGIN}/docs/"
PATH_PREFIX = "/docs/"


def _page(title: str, body: str, links: list[tuple[str, str]] | None = None) -> str:
    anchors = "".join(f'<a href="{href}">{text}</a>' for href, text in (links or []))
    return (
        f"<html><head><title>{title} | Docs</title></head><body>"
        f"<main><h1>{title}</h1><p>{body}</p>{anchors}</main></body></html>"
    )


class FakeDocsSite:
    """In-memory doc site served through ``httpx.MockTransport``."""

    def __init__(self) -> None:
        self.pages: dict[str, tuple[int, str]] = {}
        self.requests: list[str] = []

    def serve(self, path: str, html: str, status: int = 200) -> None:
        self.pages[path] = (status, html)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        status, html = self.pages.get(
            request.url.path, (404, "<html><body><p>not found</p></body></html>")
        )
        return httpx.Response(status, text=html)

    def client_factory(self):
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


@pytest.fixture
def crawl_clock(monkeypatch):
    """Offline pacing: no host checks, no real sleeping."""
    now = [100.0]
    monkeypatch.setattr(robots.time, "monotonic", lambda: now[0])

    async def sleep(delay):
        now[0] += delay

    monkeypatch.setattr(robots.asyncio, "sleep", sleep)
    monkeypatch.setattr(robots, "_is_disallowed_host", lambda _: False)
    monkeypatch.setattr(crawler, "_is_disallowed_host", lambda _: False)
    return now


def install_site(monkeypatch, site: FakeDocsSite) -> None:
    """Route the real ``crawl_docs_site`` through the fixture transport."""
    real_crawl = crawler.crawl_docs_site

    async def crawl(url, **kwargs):
        kwargs.setdefault("client_factory", site.client_factory)
        return await real_crawl(url, **kwargs)

    monkeypatch.setattr(crawler, "crawl_docs_site", crawl)


def make_kb(tmp_path: Path, kb_name: str = "kb") -> tuple[str, Path]:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    kb_dir = manager.base_dir / kb_name
    kb_dir.mkdir(parents=True)
    (kb_dir / "raw").mkdir()
    manager.register_knowledge_base(kb_name)
    (kb_dir / "metadata.json").write_text("{}", encoding="utf-8")
    return str(manager.base_dir), kb_dir


def raw_relpath(kb_dir: Path, path: Path) -> str:
    return str(path.resolve().relative_to((kb_dir / "raw").resolve()))


def raw_files(kb_dir: Path) -> set[str]:
    return {raw_relpath(kb_dir, path) for path in (kb_dir / "raw").rglob("*.md")}


def source_state(base_dir: str, kb: str = "kb") -> dict:
    return KnowledgeBaseManager(base_dir=base_dir).get_web_sources(kb)[0]


def page_filename(source: dict, page_url: str) -> str:
    return _source_filename(source, page_url, PATH_PREFIX)


async def run_sync(base_dir: str, **kwargs):
    source = source_state(base_dir)
    return await sync_source("kb", source, base_dir=base_dir, **kwargs)


def seed_site(site: FakeDocsSite, intro_body: str = "Introduction guide body") -> None:
    site.serve(
        "/docs/",
        _page(
            "Docs Home",
            "Welcome to the documentation home",
            links=[("/docs/intro", "Intro")],
        ),
    )
    site.serve("/docs/intro", _page("Intro", intro_body))


async def first_sync(tmp_path, monkeypatch, site: FakeDocsSite):
    install_site(monkeypatch, site)
    base_dir, kb_dir = make_kb(tmp_path)
    manager = KnowledgeBaseManager(base_dir=base_dir)
    manager.add_web_source("kb", SEED_URL)
    with patch(
        "deeptutor.knowledge.add_documents.add_documents", new_callable=AsyncMock
    ) as mock_add:
        mock_add.return_value = 2
        result = await run_sync(base_dir)
    assert result.ok, result.error
    return base_dir, kb_dir, mock_add


# ── added: first crawl lands in the KB ───────────────────────────────


@pytest.mark.asyncio
async def test_first_sync_persists_pages_hashes_and_success_state(
    tmp_path, monkeypatch, crawl_clock
):
    site = FakeDocsSite()
    seed_site(site)
    base_dir, kb_dir, mock_add = await first_sync(tmp_path, monkeypatch, site)

    state = source_state(base_dir)
    expected = {
        page_filename(state, f"{SITE_ORIGIN}/docs/"),
        page_filename(state, f"{SITE_ORIGIN}/docs/intro"),
    }
    assert state["last_sync_status"] == "success"
    assert not state["last_sync_error"]
    assert state["last_synced_at"]
    assert state["page_count"] == 2
    assert set(state["page_hashes"]) == expected

    assert raw_files(kb_dir) == expected
    intro_file = kb_dir / "raw" / page_filename(state, f"{SITE_ORIGIN}/docs/intro")
    assert intro_file.is_file()
    assert "Introduction guide body" in intro_file.read_text(encoding="utf-8")
    assert mock_add.await_count == 1

    # Every HTTP request stayed on the fixture origin.
    assert {url for url in site.requests if not url.endswith("/robots.txt")} and all(
        url.startswith(SITE_ORIGIN + "/") for url in site.requests
    )
    assert sorted(url for url in site.requests) == sorted(
        {
            f"{SITE_ORIGIN}/robots.txt",
            f"{SITE_ORIGIN}/docs/",
            f"{SITE_ORIGIN}/docs/intro",
        }
    )


# ── updated: content change re-stages only the changed page ─────────


@pytest.mark.asyncio
async def test_changed_content_updates_only_changed_pages(tmp_path, monkeypatch, crawl_clock):
    site = FakeDocsSite()
    seed_site(site)
    base_dir, kb_dir, _ = await first_sync(tmp_path, monkeypatch, site)
    hashes_before = source_state(base_dir)["page_hashes"]
    home_file = kb_dir / "raw" / page_filename(source_state(base_dir), f"{SITE_ORIGIN}/docs/")

    # Revision links to a brand-new page; the home page stays byte-identical.
    site.serve(
        "/docs/intro",
        _page(
            "Intro",
            "Revised introduction body",
            links=[("/docs/advanced", "Advanced")],
        ),
    )
    site.serve("/docs/advanced", _page("Advanced", "Advanced topics body"))

    with patch(
        "deeptutor.knowledge.add_documents.add_documents", new_callable=AsyncMock
    ) as mock_add:
        mock_add.return_value = 2
        result = await run_sync(base_dir)

    assert result.ok, result.error
    assert result.pages_added == 1
    assert result.pages_updated == 1
    assert result.pages_unchanged == 1

    state = source_state(base_dir)
    advanced_name = page_filename(state, f"{SITE_ORIGIN}/docs/advanced")
    intro_name = page_filename(state, f"{SITE_ORIGIN}/docs/intro")
    home_name = page_filename(state, f"{SITE_ORIGIN}/docs/")

    assert set(state["page_hashes"]) == {home_name, intro_name, advanced_name}
    assert state["page_hashes"][home_name] == hashes_before[home_name]
    assert state["page_hashes"][intro_name] != hashes_before[intro_name]
    assert state["last_sync_status"] == "success"

    intro_file = kb_dir / "raw" / intro_name
    advanced_file = kb_dir / "raw" / advanced_name
    assert "Revised introduction body" in intro_file.read_text(encoding="utf-8")
    assert "Advanced topics body" in advanced_file.read_text(encoding="utf-8")

    # Only the changed pages went to the index; the unchanged home page did not.
    indexed = {Path(p).name for p in mock_add.await_args.kwargs["source_files"]}
    assert indexed == {intro_file.name, advanced_file.name}


# ── failed: outage marks error without corrupting state ──────────────


@pytest.mark.asyncio
async def test_failed_sync_marks_error_and_preserves_snapshot(tmp_path, monkeypatch, crawl_clock):
    site = FakeDocsSite()
    seed_site(site)
    base_dir, kb_dir, _ = await first_sync(tmp_path, monkeypatch, site)
    hashes_before = source_state(base_dir)["page_hashes"]
    snapshot_before = {
        name: (kb_dir / "raw" / name).read_text(encoding="utf-8") for name in hashes_before
    }

    site.pages.clear()  # robots.txt still answers; every page 503s
    site.serve("/docs/", "upstream overloaded", status=503)
    site.serve("/docs/intro", "upstream overloaded", status=503)

    result = await run_sync(base_dir)

    assert result.ok is False
    assert "no pages" in result.error

    state = source_state(base_dir)
    assert state["last_sync_status"] == "error"
    assert "no pages" in state["last_sync_error"]
    assert state["last_synced_at"]
    # Failure must not advance or wipe hashes.
    assert state["page_hashes"] == hashes_before
    assert state["page_count"] == 2
    # The raw snapshot is byte-identical: a failed crawl writes nothing.
    assert raw_files(kb_dir) == set(hashes_before)
    assert {
        name: (kb_dir / "raw" / name).read_text(encoding="utf-8") for name in hashes_before
    } == snapshot_before


@pytest.mark.asyncio
async def test_fetch_page_retries_transient_5xx_then_succeeds(crawl_clock):
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) <= 2:
            return httpx.Response(503, text="overloaded")
        return httpx.Response(200, text="<html><body><p>recovered</p></body></html>")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _fetch_page(f"{SITE_ORIGIN}/docs/slow", client=client)

    assert result is not None
    html, final_url = result
    assert "recovered" in html
    assert final_url == f"{SITE_ORIGIN}/docs/slow"
    assert len(attempts) == 1 + _MAX_RETRIES


@pytest.mark.asyncio
async def test_fetch_page_gives_up_after_max_retries(crawl_clock):
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(503, text="still down")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _fetch_page(f"{SITE_ORIGIN}/docs/down", client=client)

    assert result is None
    assert len(attempts) == 1 + _MAX_RETRIES


# ── recovered: healthy sync clears the error state ───────────────────


@pytest.mark.asyncio
async def test_sync_recovers_after_transient_outage(tmp_path, monkeypatch, crawl_clock):
    site = FakeDocsSite()
    seed_site(site)
    base_dir, kb_dir, mock_add = await first_sync(tmp_path, monkeypatch, site)
    hashes_before = source_state(base_dir)["page_hashes"]

    site.pages.clear()
    site.serve("/docs/", "boom", status=503)
    site.serve("/docs/intro", "boom", status=503)
    failed = await run_sync(base_dir)
    assert failed.ok is False
    assert source_state(base_dir)["last_sync_status"] == "error"

    site.pages.clear()
    seed_site(site)  # site is healthy again, content identical
    with patch(
        "deeptutor.knowledge.add_documents.add_documents", new_callable=AsyncMock
    ) as recovery_add:
        recovered = await run_sync(base_dir)

    assert recovered.ok, recovered.error
    assert recovered.pages_added == 0
    assert recovered.pages_updated == 0
    assert recovered.pages_unchanged == 2

    state = source_state(base_dir)
    assert state["last_sync_status"] == "success"
    assert not state["last_sync_error"]
    assert state["page_hashes"] == hashes_before
    # Recovery must not re-index anything: hashes never advanced past the
    # outage, so unchanged pages are recognised.
    assert recovery_add.await_count == 0
    assert mock_add.await_count == 1
    assert raw_files(kb_dir) == set(hashes_before)


@pytest.mark.asyncio
async def test_indexing_outage_recovery_restages_changed_page(tmp_path, monkeypatch, crawl_clock):
    site = FakeDocsSite()
    seed_site(site)
    base_dir, kb_dir, _ = await first_sync(tmp_path, monkeypatch, site)
    hashes_v1 = source_state(base_dir)["page_hashes"]
    intro_name = page_filename(source_state(base_dir), f"{SITE_ORIGIN}/docs/intro")
    intro_file = kb_dir / "raw" / intro_name

    site.serve("/docs/intro", _page("Intro", "Revised introduction body"))

    with patch(
        "deeptutor.knowledge.add_documents.add_documents",
        new_callable=AsyncMock,
        side_effect=RuntimeError("index unavailable"),
    ):
        outcome = await run_sync(base_dir)

    assert outcome.ok is False
    state = source_state(base_dir)
    assert state["last_sync_status"] == "error"
    assert "index unavailable" in state["last_sync_error"]
    # Snapshot staged, hashes not advanced past the failed indexing.
    assert state["page_hashes"] == hashes_v1
    assert "Revised introduction body" in intro_file.read_text(encoding="utf-8")

    with patch(
        "deeptutor.knowledge.add_documents.add_documents", new_callable=AsyncMock
    ) as recovery_add:
        recovery_add.return_value = 1
        recovered = await run_sync(base_dir)

    assert recovered.ok, recovered.error
    assert recovered.pages_updated == 1
    assert recovered.pages_unchanged == 1
    state = source_state(base_dir)
    assert state["last_sync_status"] == "success"
    assert state["page_hashes"][intro_name] != hashes_v1[intro_name]
    assert {Path(p).name for p in recovery_add.await_args.kwargs["source_files"]} == {
        intro_file.name
    }


# ── snapshot & index consistency through change + removal ────────────


@pytest.mark.asyncio
async def test_snapshot_and_index_stay_consistent_through_change_and_removal(
    tmp_path, monkeypatch, crawl_clock
):
    site = FakeDocsSite()
    seed_site(site)
    site.serve("/docs/guide", _page("Guide", "Guide page body"))
    site.serve(
        "/docs/",
        _page(
            "Docs Home",
            "Welcome to the documentation home",
            links=[("/docs/intro", "Intro"), ("/docs/guide", "Guide")],
        ),
    )
    base_dir, kb_dir, _ = await first_sync(tmp_path, monkeypatch, site)

    state = source_state(base_dir)
    guide_name = page_filename(state, f"{SITE_ORIGIN}/docs/guide")
    metadata_path = kb_dir / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["file_hashes"] = {name: "indexed" for name in state["page_hashes"]}
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    # The guide disappears from the site; intro gets revised.
    site.pages.pop("/docs/guide", None)
    site.serve("/docs/intro", _page("Intro", "Revised introduction body"))

    with patch(
        "deeptutor.services.rag.service.RAGService.initialize", new_callable=AsyncMock
    ) as rebuild:
        rebuild.return_value = True
        result = await run_sync(base_dir)

    assert result.ok, result.error
    assert result.pages_removed == 1
    assert result.pages_updated == 1

    state = source_state(base_dir)
    remaining = raw_files(kb_dir)

    # Snapshot ↔ metadata: hashes cover exactly the files on disk.
    assert guide_name not in remaining
    assert remaining == set(state["page_hashes"])

    # Snapshot ↔ index: the rebuild saw exactly the surviving raw files,
    # so removed pages cannot stay retrievable and the revised page is in.
    assert rebuild.await_count == 1
    rebuilt = {raw_relpath(kb_dir, Path(p)) for p in rebuild.await_args.kwargs["file_paths"]}
    assert rebuilt == remaining

    # The removal purged the deleted page's indexed-hash record.
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert guide_name not in metadata.get("file_hashes", {})
    assert state["last_sync_status"] == "success"
