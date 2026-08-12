"""Background service that periodically syncs GitHub sources into KBs.

Runs a single asyncio task that wakes every hour, scans all KBs for
``github_sources`` entries, and syncs any that are ``enabled=True`` and
haven't been synced in the last 24 hours (or never synced at all).

Mirrors the lifecycle of the cron service: ``start()`` / ``stop()`` are
called from the FastAPI ``lifespan`` handler.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from deeptutor.services.github_source.client import GitHubClient
from deeptutor.services.github_source.sync import (
    SYNC_INTERVAL_HOURS,
    SyncResult,
    sync_source,
)

logger = logging.getLogger(__name__)

_CHECK_INTERVAL_SECONDS = 3600  # wake every hour
_SYNC_STALE_SECONDS = SYNC_INTERVAL_HOURS * 3600


def _is_stale(source: dict) -> bool:
    """True when the source is due for a sync (or never synced)."""
    last = source.get("last_synced_at") or ""
    if not last:
        return True
    try:
        dt = datetime.fromisoformat(last)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except Exception:
        return True
    age = (datetime.now(timezone.utc) - dt).total_seconds()
    return age >= _SYNC_STALE_SECONDS


class GitHubSourceSyncService:
    """Single-process background sync loop."""

    def __init__(
        self,
        *,
        base_dir: str | None = None,
        client: GitHubClient | None = None,
        check_interval_s: int = _CHECK_INTERVAL_SECONDS,
    ) -> None:
        self._base_dir = base_dir
        self._client = client
        self._check_interval_s = check_interval_s
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(
            self._loop(), name="github-source-sync"
        )
        logger.info("GitHub source sync service started")

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("GitHub source sync service stopped")

    async def _loop(self) -> None:
        while self._running:
            try:
                await self.run_once()
            except Exception:
                logger.exception("GitHub source sync loop error")
            await asyncio.sleep(self._check_interval_s)

    async def run_once(self) -> list[tuple[str, str, SyncResult]]:
        """Sync all eligible sources once. Returns list of results.

        Used by both the background loop and manual ``sync now`` triggers.
        """
        from deeptutor.knowledge.manager import KnowledgeBaseManager

        base_dir = self._base_dir or str(
            _default_base_dir()
        )
        manager = KnowledgeBaseManager(base_dir=base_dir)
        all_sources = manager.get_all_github_sources()

        results: list[tuple[str, str, SyncResult]] = []
        for kb_name, source in all_sources:
            if not source.get("enabled", True):
                continue
            if not _is_stale(source):
                continue
            sid = source.get("id", "?")
            repo = source.get("repo", "?")
            logger.info("Syncing GitHub source %s for KB '%s'", repo, kb_name)
            try:
                result = await sync_source(
                    kb_name=kb_name,
                    source=source,
                    base_dir=base_dir,
                    client=self._client,
                )
                results.append((kb_name, sid, result))
                if not result.ok:
                    # Record error state in metadata
                    manager.update_github_source_state(
                        kb_name=kb_name,
                        source_id=sid,
                        last_sync_status="error",
                        last_sync_error=result.error,
                        last_synced_at=datetime.now(timezone.utc).isoformat(),
                    )
            except Exception as exc:
                logger.exception(
                    "Failed to sync GitHub source %s for KB '%s'", repo, kb_name
                )
                manager.update_github_source_state(
                    kb_name=kb_name,
                    source_id=sid,
                    last_sync_status="error",
                    last_sync_error=str(exc),
                    last_synced_at=datetime.now(timezone.utc).isoformat(),
                )
                results.append(
                    (kb_name, sid, SyncResult(ok=False, error=str(exc)))
                )
        return results


def _default_base_dir() -> str:
    """Resolve the default KB base directory from the path service."""
    try:
        from deeptutor.services.path_service import get_path_service

        return str(get_path_service().project_root / "data" / "knowledge_bases")
    except Exception:
        from deeptutor.knowledge.add_documents import DEFAULT_BASE_DIR

        return DEFAULT_BASE_DIR


# ── module-level singleton ──────────────────────────────────────────

_sync_service: GitHubSourceSyncService | None = None


def get_sync_service() -> GitHubSourceSyncService:
    global _sync_service
    if _sync_service is None:
        _sync_service = GitHubSourceSyncService()
    return _sync_service
