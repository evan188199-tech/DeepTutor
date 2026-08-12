"""Tests for the GitHub source sync engine.

Uses a mock GitHubClient to simulate API responses.  The KB on disk is
real (created under tmp_path), but we stub out the ``add_documents``
indexing call to avoid needing a full RAG provider.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from deeptutor.services.github_source.client import (
    FileChange,
    GitHubAPIError,
    GitHubClient,
    TreeEntry,
)
from deeptutor.services.github_source.sync import (
    SyncResult,
    _filter_markdown_changes,
    _filter_markdown_entries,
    _is_markdown,
    _raw_rel_path,
    sync_source,
)
from deeptutor.services.github_source.sync_service import (
    GitHubSourceSyncService,
    _is_stale,
)


# ── helpers ───────────────────────────────────────────────────────────


class MockGitHubClient:
    """In-memory GitHub API mock for sync tests."""

    def __init__(
        self,
        *,
        latest_sha: str = "sha-aaa",
        tree: list[TreeEntry] | None = None,
        changes: list[FileChange] | None = None,
        file_contents: dict[str, bytes] | None = None,
        default_branch: str = "main",
        error_on_sha: bool = False,
    ) -> None:
        self._latest_sha = latest_sha
        self._tree = tree or []
        self._changes = changes or []
        self._file_contents = file_contents or {}
        self._default_branch = default_branch
        self._error_on_sha = error_on_sha

    async def get_default_branch(self, repo: str) -> str:
        return self._default_branch

    async def get_latest_commit_sha(self, repo: str, branch: str) -> str:
        if self._error_on_sha:
            raise GitHubAPIError(500, "server error")
        return self._latest_sha

    async def get_tree(
        self, repo: str, branch: str, *, path_prefix: str = "", glob: str = "*.md"
    ) -> list[TreeEntry]:
        return self._tree

    async def compare_commits(
        self, repo: str, base: str, head: str
    ) -> list[FileChange]:
        return self._changes

    async def download_file(self, repo: str, path: str, ref: str) -> bytes:
        return self._file_contents.get(path, b"# content")


def _make_kb(tmp_path: Path, kb_name: str = "kb") -> tuple[str, Path]:
    """Create a minimal KB with raw/ dir and metadata.json."""
    from deeptutor.knowledge.manager import KnowledgeBaseManager

    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    kb_dir = manager.base_dir / kb_name
    kb_dir.mkdir()
    raw_dir = kb_dir / "raw"
    raw_dir.mkdir()
    manager.register_knowledge_base(kb_name)
    (kb_dir / "metadata.json").write_text("{}", encoding="utf-8")
    return str(manager.base_dir), kb_dir


def _add_source(manager_base: str, kb_name: str, **overrides) -> dict:
    from deeptutor.knowledge.manager import KnowledgeBaseManager

    manager = KnowledgeBaseManager(base_dir=manager_base)
    source = manager.add_github_source(kb_name, "owner/repo", **overrides)
    return source


# ── pure-function unit tests ──────────────────────────────────────────


def test_is_markdown() -> None:
    assert _is_markdown("README.md") is True
    assert _is_markdown("docs/intro.markdown") is True
    assert _is_markdown("image.png") is False
    assert _is_markdown("script.py") is False


def test_raw_rel_path() -> None:
    assert _raw_rel_path("docs/intro.md", "docs/") == "intro.md"
    assert _raw_rel_path("docs/sub/x.md", "docs/") == "sub/x.md"
    assert _raw_rel_path("README.md", "") == "README.md"
    assert _raw_rel_path("README.md", "docs/") == "README.md"


def test_filter_markdown_entries() -> None:
    entries = [
        TreeEntry(path="docs/a.md", sha="1", type="blob"),
        TreeEntry(path="docs/b.txt", sha="2", type="blob"),
        TreeEntry(path="README.md", sha="3", type="blob"),
        TreeEntry(path="src/c.md", sha="4", type="blob"),
    ]
    result = _filter_markdown_entries(entries, path_prefix="docs", glob="*.md")
    assert [e.path for e in result] == ["docs/a.md"]


def test_filter_markdown_changes() -> None:
    changes = [
        FileChange(path="docs/a.md", status="added", sha="1"),
        FileChange(path="docs/b.png", status="added", sha="2"),
        FileChange(path="README.md", status="modified", sha="3"),
    ]
    result = _filter_markdown_changes(changes, path_prefix="", glob="*.md")
    assert {c.path for c in result} == {"docs/a.md", "README.md"}


# ── sync_source integration tests ─────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_source_first_run_downloads_all(tmp_path: Path) -> None:
    base_dir, kb_dir = _make_kb(tmp_path)
    source = _add_source(base_dir, "kb")

    mock_client = MockGitHubClient(
        latest_sha="sha-new",
        tree=[
            TreeEntry(path="README.md", sha="1", type="blob"),
            TreeEntry(path="docs/intro.md", sha="2", type="blob"),
        ],
        file_contents={
            "README.md": b"# README",
            "docs/intro.md": b"# Intro",
        },
    )

    with patch("deeptutor.services.github_source.sync._index_files", new_callable=AsyncMock) as m:
        m.return_value = 2
        result = await sync_source("kb", source, base_dir=base_dir, client=mock_client)

    assert result.ok is True
    assert result.skipped is False
    assert result.files_added == 2

    # Files should be on disk in raw/
    raw = kb_dir / "raw"
    assert (raw / "README.md").read_text() == "# README"
    assert (raw / "docs" / "intro.md").read_text() == "# Intro"


@pytest.mark.asyncio
async def test_sync_source_skips_when_unchanged(tmp_path: Path) -> None:
    base_dir, _kb_dir = _make_kb(tmp_path)
    source = _add_source(base_dir, "kb")
    source["last_synced_sha"] = "sha-same"  # already synced

    mock_client = MockGitHubClient(latest_sha="sha-same")

    result = await sync_source("kb", source, base_dir=base_dir, client=mock_client)
    assert result.ok is True
    assert result.skipped is True


@pytest.mark.asyncio
async def test_sync_source_api_error(tmp_path: Path) -> None:
    base_dir, _kb_dir = _make_kb(tmp_path)
    source = _add_source(base_dir, "kb")

    mock_client = MockGitHubClient(error_on_sha=True)

    result = await sync_source("kb", source, base_dir=base_dir, client=mock_client)
    assert result.ok is False
    assert "500" in result.error


@pytest.mark.asyncio
async def test_sync_source_incremental_added_and_removed(tmp_path: Path) -> None:
    base_dir, kb_dir = _make_kb(tmp_path)
    source = _add_source(base_dir, "kb")
    source["last_synced_sha"] = "sha-old"

    # Pre-stage a file that will be "removed"
    raw = kb_dir / "raw"
    (raw / "old.md").write_text("old", encoding="utf-8")

    mock_client = MockGitHubClient(
        latest_sha="sha-new",
        changes=[
            FileChange(path="new.md", status="added", sha="1"),
            FileChange(path="old.md", status="removed", sha="2"),
        ],
        file_contents={"new.md": b"# New"},
    )

    with patch("deeptutor.services.github_source.sync._index_files", new_callable=AsyncMock) as m:
        m.return_value = 1
        with patch(
            "deeptutor.knowledge.add_documents.remove_raw_document"
        ) as mock_remove:
            mock_remove.return_value = type("R", (), {"rel_path": "old.md", "was_indexed": True})()
            result = await sync_source("kb", source, base_dir=base_dir, client=mock_client)

    assert result.ok is True
    assert result.files_added == 1
    assert result.files_removed == 1
    assert (raw / "new.md").exists()
    mock_remove.assert_called_once()


@pytest.mark.asyncio
async def test_sync_source_persists_sha_on_success(tmp_path: Path) -> None:
    base_dir, kb_dir = _make_kb(tmp_path)
    source = _add_source(base_dir, "kb")

    mock_client = MockGitHubClient(
        latest_sha="sha-persisted",
        tree=[TreeEntry(path="a.md", sha="1", type="blob")],
        file_contents={"a.md": b"# A"},
    )

    with patch("deeptutor.services.github_source.sync._index_files", new_callable=AsyncMock) as m:
        m.return_value = 1
        await sync_source("kb", source, base_dir=base_dir, client=mock_client)

    metadata = json.loads((kb_dir / "metadata.json").read_text())
    src = metadata["github_sources"][0]
    assert src["last_synced_sha"] == "sha-persisted"
    assert src["last_sync_status"] == "success"
    assert src["files_synced"] == 1


# ── sync_service stale check ──────────────────────────────────────────


def test_is_stale_never_synced() -> None:
    assert _is_stale({"last_synced_at": ""}) is True


def test_is_stale_recently_synced() -> None:
    recent = datetime.now(timezone.utc).isoformat()
    assert _is_stale({"last_synced_at": recent}) is False


def test_is_stale_old_sync() -> None:
    old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    assert _is_stale({"last_synced_at": old}) is True


def test_is_stale_bad_timestamp() -> None:
    assert _is_stale({"last_synced_at": "garbage"}) is True
