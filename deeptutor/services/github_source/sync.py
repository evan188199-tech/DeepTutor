"""Core sync logic: pull Markdown from a GitHub repo into a KB's raw/ dir.

``sync_source()`` is the single entrypoint.  It:
1. Checks the latest commit SHA for the configured branch.
2. If unchanged since last sync, returns early.
3. On first run — downloads the full tree of matching ``.md`` files.
   On subsequent runs — diffs old…new and processes only changed files.
4. Writes new/modified files into the KB ``raw/`` directory (preserving
   relative paths), feeds them to ``add_documents()`` for indexing.
5. Removes files deleted upstream via ``remove_raw_document()``.
6. Persists the new SHA + sync status back into ``metadata.json``.

Errors from the GitHub API or the indexing pipeline are caught and
recorded into ``last_sync_error`` without propagating — the background
scheduler relies on this isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Any

from deeptutor.knowledge.add_documents import DEFAULT_BASE_DIR
from deeptutor.services.github_source.client import (
    FileChange,
    GitHubAPIError,
    GitHubClient,
    TreeEntry,
)

logger = logging.getLogger(__name__)

SYNC_INTERVAL_HOURS = 24
MARKDOWN_EXTENSIONS = (".md", ".markdown")


@dataclass
class SyncResult:
    """Outcome of a single ``sync_source()`` invocation."""

    ok: bool
    skipped: bool = False
    files_added: int = 0
    files_updated: int = 0
    files_removed: int = 0
    error: str = ""

    @property
    def total_changes(self) -> int:
        return self.files_added + self.files_updated + self.files_removed


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_markdown(path: str) -> bool:
    return path.lower().endswith(MARKDOWN_EXTENSIONS)


def _raw_rel_path(github_path: str, path_prefix: str) -> str:
    """Convert a GitHub repo path to a stable raw/ relative path.

    If ``path_prefix`` is ``docs/`` and the file is ``docs/intro.md``,
    the rel path is ``intro.md``.  If no prefix, the full repo path is used.
    """
    prefix = path_prefix.strip("/")
    if prefix and github_path.startswith(prefix + "/"):
        return github_path[len(prefix) + 1:]
    return github_path


def _filter_markdown_changes(
    changes: list[FileChange], path_prefix: str, glob: str
) -> list[FileChange]:
    """Keep only changes that match our markdown glob + prefix."""
    from fnmatch import fnmatch

    prefix = path_prefix.strip("/")
    result: list[FileChange] = []
    for ch in changes:
        p = ch.path
        if prefix and not p.startswith(prefix + "/") and p != prefix:
            continue
        if not (_is_markdown(p) and (fnmatch(p, glob) or fnmatch(p.rsplit("/", 1)[-1], glob))):
            continue
        result.append(ch)
    return result


def _filter_markdown_entries(
    entries: list[TreeEntry], path_prefix: str, glob: str
) -> list[TreeEntry]:
    """Keep only tree entries that match our markdown glob + prefix."""
    from fnmatch import fnmatch

    prefix = path_prefix.strip("/")
    result: list[TreeEntry] = []
    for e in entries:
        p = e.path
        if prefix and not p.startswith(prefix + "/") and p != prefix:
            continue
        if not (_is_markdown(p) and (fnmatch(p, glob) or fnmatch(p.rsplit("/", 1)[-1], glob))):
            continue
        result.append(e)
    return result


async def sync_source(
    kb_name: str,
    source: dict[str, Any],
    *,
    base_dir: str = DEFAULT_BASE_DIR,
    client: GitHubClient | None = None,
) -> SyncResult:
    """Synchronise a single GitHub source into the named KB.

    ``source`` is the dict stored in ``metadata.json["github_sources"][i]``
    containing at least ``repo``, ``branch``, ``path``, ``glob``, and
    ``last_synced_sha``.
    """
    client = client or GitHubClient()
    kb_dir = Path(base_dir) / kb_name
    raw_dir = kb_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    repo = source["repo"]
    branch = source.get("branch") or "main"
    path_prefix = source.get("path") or ""
    glob = source.get("glob") or "*.md"
    old_sha = source.get("last_synced_sha") or ""

    try:
        latest_sha = await client.get_latest_commit_sha(repo, branch)
    except GitHubAPIError as exc:
        return SyncResult(ok=False, error=str(exc))
    except Exception as exc:
        return SyncResult(ok=False, error=f"Failed to fetch latest SHA: {exc}")

    if old_sha and old_sha == latest_sha:
        logger.debug("GitHub source %s@%s unchanged (%s)", repo, branch, latest_sha)
        return SyncResult(ok=True, skipped=True)

    try:
        if not old_sha:
            result = await _full_sync(
                client, kb_name, raw_dir, repo, branch, path_prefix, glob, latest_sha, base_dir
            )
        else:
            result = await _incremental_sync(
                client, kb_name, raw_dir, repo, branch, path_prefix, glob,
                old_sha, latest_sha, base_dir,
            )
    except GitHubAPIError as exc:
        return SyncResult(ok=False, error=str(exc))
    except Exception as exc:
        logger.exception("Unexpected error syncing %s", repo)
        return SyncResult(ok=False, error=str(exc))

    if not result.ok:
        return result

    # Persist sync state
    from deeptutor.knowledge.manager import KnowledgeBaseManager

    manager = KnowledgeBaseManager(base_dir=base_dir)
    manager.update_github_source_state(
        kb_name=kb_name,
        source_id=source["id"],
        last_synced_sha=latest_sha,
        last_synced_at=_utcnow_iso(),
        last_sync_status="success",
        last_sync_error=None,
        files_synced=result.files_added + result.files_updated,
    )
    return result


async def _full_sync(
    client: GitHubClient,
    kb_name: str,
    raw_dir: Path,
    repo: str,
    branch: str,
    path_prefix: str,
    glob: str,
    latest_sha: str,
    base_dir: str,
) -> SyncResult:
    """Download all matching files on first sync."""
    tree = await client.get_tree(repo, branch, path_prefix=path_prefix, glob=glob)
    entries = _filter_markdown_entries(tree, path_prefix, glob)

    downloaded: list[str] = []
    for entry in entries:
        rel = _raw_rel_path(entry.path, path_prefix)
        dest = raw_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        content = await client.download_file(repo, entry.path, latest_sha)
        dest.write_bytes(content)
        downloaded.append(str(dest))

    indexed = 0
    if downloaded:
        indexed = await _index_files(kb_name, downloaded, base_dir)

    logger.info(
        "Full sync %s@%s: %d files downloaded, %d indexed",
        repo, branch, len(downloaded), indexed,
    )
    return SyncResult(ok=True, files_added=len(downloaded))


async def _incremental_sync(
    client: GitHubClient,
    kb_name: str,
    raw_dir: Path,
    repo: str,
    branch: str,
    path_prefix: str,
    glob: str,
    old_sha: str,
    new_sha: str,
    base_dir: str,
) -> SyncResult:
    """Process only files changed between old_sha and new_sha."""
    all_changes = await client.compare_commits(repo, old_sha, new_sha)
    changes = _filter_markdown_changes(all_changes, path_prefix, glob)

    added_or_modified: list[str] = []
    removed: list[str] = []

    for ch in changes:
        rel = _raw_rel_path(ch.path, path_prefix)
        if ch.status == "removed":
            removed.append(rel)
        else:
            added_or_modified.append(ch.path)

    # Download and stage added/modified files
    downloaded: list[str] = []
    for gh_path in added_or_modified:
        content = await client.download_file(repo, gh_path, new_sha)
        rel = _raw_rel_path(gh_path, path_prefix)
        dest = raw_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        downloaded.append(str(dest))

    indexed = 0
    if downloaded:
        indexed = await _index_files(kb_name, downloaded, base_dir)

    # Remove deleted files
    removed_count = 0
    for rel in removed:
        target = raw_dir / rel
        if target.exists():
            try:
                from deeptutor.knowledge.add_documents import remove_raw_document

                kb_dir = Path(base_dir) / kb_name
                remove_raw_document(kb_dir, target)
                removed_count += 1
            except Exception as exc:
                logger.warning("Failed to remove %s: %s", rel, exc)

    logger.info(
        "Incremental sync %s@%s (%s..%s): %d added/modified (%d indexed), %d removed",
        repo, branch, old_sha[:8], new_sha[:8],
        len(downloaded), indexed, removed_count,
    )
    return SyncResult(
        ok=True,
        files_added=len(downloaded),
        files_removed=removed_count,
    )


async def _index_files(kb_name: str, file_paths: list[str], base_dir: str) -> int:
    """Feed files through the standard KB add_documents pipeline."""
    if not file_paths:
        return 0
    try:
        from deeptutor.knowledge.add_documents import add_documents

        count = await add_documents(
            kb_name=kb_name,
            source_files=file_paths,
            base_dir=base_dir,
            allow_duplicates=False,
        )
        return count or 0
    except Exception as exc:
        logger.warning("Indexing failed for GitHub source files: %s", exc)
        return 0
