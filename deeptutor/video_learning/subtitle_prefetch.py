"""Owner-isolated, low-concurrency YouTube subtitle prefetching."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import tempfile
from typing import Any

from deeptutor.multi_user.models import LOCAL_ADMIN_ID
from deeptutor.multi_user.paths import USERS_ROOT
from deeptutor.services.path_service import PathService
from deeptutor.video_learning.service import (
    TimedMediaNotFound,
    TimedMediaStore,
    YouTubeResolver,
    build_segments,
    download_ytdlp_subtitle,
)
from deeptutor.video_learning.youtube_session import HostChromeSessionStore, YouTubeCookieStore

logger = logging.getLogger(__name__)
_RETRY_DELAYS = (15 * 60, 60 * 60, 6 * 60 * 60, 24 * 60 * 60, 3 * 24 * 60 * 60)
_FETCH_STATES = {"not_requested", "queued", "fetching", "ready", "retry_wait", "auth_required", "unavailable", "error"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def transcript_fetch(material: dict[str, Any]) -> dict[str, Any]:
    transcript = material.get("transcript") if isinstance(material.get("transcript"), dict) else {}
    fetch = transcript.get("fetch") if isinstance(transcript.get("fetch"), dict) else {}
    status = str(fetch.get("status") or "not_requested")
    return {
        "status": status if status in _FETCH_STATES else "not_requested",
        "attempts": max(0, int(fetch.get("attempts") or 0)),
        "next_retry_at": str(fetch.get("next_retry_at") or "") or None,
        "updated_at": str(fetch.get("updated_at") or "") or None,
        "error_code": str(fetch.get("error_code") or "") or None,
    }


def _set_fetch(material: dict[str, Any], **fields: Any) -> dict[str, Any]:
    transcript = material.setdefault("transcript", {})
    if not isinstance(transcript, dict):
        transcript = material["transcript"] = {}
    fetch = transcript.get("fetch") if isinstance(transcript.get("fetch"), dict) else {}
    fetch.update(fields)
    fetch["updated_at"] = _iso()
    transcript["fetch"] = fetch
    transcript.setdefault("language", "")
    transcript.setdefault("source", "")
    transcript.setdefault("cues", [])
    return fetch


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _owner_store(owner_id: str) -> TimedMediaStore:
    if owner_id == LOCAL_ADMIN_ID:
        return TimedMediaStore()
    return TimedMediaStore(root=PathService(workspace_root=USERS_ROOT / owner_id).get_workspace_feature_dir("timed_media"))


def _owner_ids() -> list[str]:
    owners = [LOCAL_ADMIN_ID]
    if USERS_ROOT.is_dir():
        owners.extend(path.name for path in USERS_ROOT.iterdir() if path.is_dir() and not path.name.startswith("."))
    return owners


class SubtitlePrefetchService:
    """A persistent-state queue with one process-wide worker."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
        self._pending: set[tuple[str, str]] = set()
        self._suspended_owners: set[str] = set()
        self._worker: asyncio.Task[None] | None = None
        self._scanner: asyncio.Task[None] | None = None
        self._stopping = False

    async def start(self) -> None:
        if self._worker and not self._worker.done():
            return
        self._stopping = False
        self._worker = asyncio.create_task(self._run(), name="youtube-subtitle-prefetch")
        self._scanner = asyncio.create_task(self._scan_loop(), name="youtube-subtitle-prefetch-scan")

    async def stop(self) -> None:
        self._stopping = True
        for task in (self._worker, self._scanner):
            if task and not task.done():
                task.cancel()
        await asyncio.gather(*(task for task in (self._worker, self._scanner) if task), return_exceptions=True)
        self._worker = self._scanner = None

    async def enqueue(self, owner_id: str, material_id: str, *, manual: bool = False) -> dict[str, Any]:
        store = _owner_store(owner_id)
        with store.lock(material_id):
            material = store.get(material_id)
            if (material.get("transcript") or {}).get("cues"):
                return transcript_fetch(material)
            fetch = transcript_fetch(material)
            if owner_id in self._suspended_owners:
                if YouTubeCookieStore.has_cookies(owner_id) or HostChromeSessionStore.enabled(owner_id):
                    self._suspended_owners.discard(owner_id)
                else:
                    return fetch
            retry_at = _parse_time(fetch["next_retry_at"])
            if fetch["status"] == "auth_required" and not (
                YouTubeCookieStore.has_cookies(owner_id) or HostChromeSessionStore.enabled(owner_id)
            ):
                return fetch
            if retry_at and retry_at > _now():
                return fetch
            _set_fetch(material, status="queued", next_retry_at=None, error_code=None)
            store.save(material)
            fetch = transcript_fetch(material)
        key = (owner_id, material_id)
        if key not in self._pending:
            self._pending.add(key)
            await self._queue.put(key)
        return fetch

    async def cancel_owner(self, owner_id: str) -> None:
        # Entries remain in the asyncio queue but are harmlessly skipped.  Do
        # not mutate cached transcripts when a user disconnects their account.
        self._suspended_owners.add(owner_id)
        self._pending = {key for key in self._pending if key[0] != owner_id}

    async def _run(self) -> None:
        while not self._stopping:
            owner_id, material_id = await self._queue.get()
            key = (owner_id, material_id)
            if key not in self._pending or owner_id in self._suspended_owners:
                continue
            try:
                await self._fetch_one(owner_id, material_id)
            except Exception:
                logger.exception("YouTube subtitle prefetch failed")
            finally:
                self._pending.discard(key)

    async def _fetch_one(self, owner_id: str, material_id: str) -> None:
        store = _owner_store(owner_id)
        with store.lock(material_id):
            try:
                material = store.get(material_id)
            except TimedMediaNotFound:
                return
            if (material.get("transcript") or {}).get("cues"):
                return
            before = transcript_fetch(material)
            _set_fetch(material, status="fetching", attempts=before["attempts"] + 1, next_retry_at=None, error_code=None)
            store.save(material)
            preferred = str((material.get("transcript") or {}).get("language") or "")
            video_id = str((material.get("source") or {}).get("video_id") or "")
        cues: list[dict[str, Any]] = []
        language = ""
        source = ""
        code = ""
        if YouTubeCookieStore.has_cookies(owner_id):
            with tempfile.TemporaryDirectory(prefix="deeptutor-youtube-cookie-") as temp_dir:
                cookiefile = YouTubeCookieStore.write_cookiefile(owner_id, Path(temp_dir))
                if cookiefile:
                    cues, language, result = await download_ytdlp_subtitle(video_id, preferred_language=preferred, cookiefile=cookiefile)
                    source = result if cues else ""
                    code = "" if cues else result
        elif HostChromeSessionStore.enabled(owner_id):
            cues, language, result = await download_ytdlp_subtitle(
                video_id,
                preferred_language=preferred,
                use_host_chrome=True,
            )
            source = result if cues else ""
            code = "" if cues else result
        if not cues:
            try:
                refreshed = await YouTubeResolver(timeout=12.0).refresh_transcript(
                    {"source": {"video_id": video_id}, "transcript": {"language": preferred, "cues": []}},
                    preferred_language=preferred,
                )
                transcript = refreshed.get("transcript") if isinstance(refreshed.get("transcript"), dict) else {}
                candidate = transcript.get("cues") if isinstance(transcript.get("cues"), list) else []
                if candidate:
                    cues = candidate
                    language = str(transcript.get("language") or "")
                    source = str(transcript.get("source") or "invidious")
            except Exception:
                code = code or "upstream_error"
        with store.lock(material_id):
            try:
                latest = store.get(material_id)
            except TimedMediaNotFound:
                return
            if (latest.get("transcript") or {}).get("cues"):
                return
            if cues:
                latest["transcript"] = {
                    "language": language or preferred,
                    "source": source or "youtube-captions",
                    "cues": cues,
                    "fetch": {"status": "ready", "attempts": transcript_fetch(latest)["attempts"], "next_retry_at": None, "updated_at": _iso(), "error_code": None},
                }
                latest["segments"] = build_segments(cues)
                store.save(latest)
                return
            fetch = transcript_fetch(latest)
            if code == "auth_required":
                _set_fetch(latest, status="auth_required", next_retry_at=None, error_code="auth_required")
            elif code == "unavailable":
                _set_fetch(latest, status="unavailable", next_retry_at=None, error_code="unavailable")
            else:
                delay = _RETRY_DELAYS[min(max(fetch["attempts"] - 1, 0), len(_RETRY_DELAYS) - 1)]
                _set_fetch(latest, status="retry_wait", next_retry_at=_iso(_now() + timedelta(seconds=delay)), error_code=code or "upstream_error")
            store.save(latest)

    async def _scan_loop(self) -> None:
        while not self._stopping:
            try:
                if 2 <= datetime.now().hour < 6:
                    await self.scan_nightly()
            except Exception:
                logger.exception("YouTube subtitle nightly scan failed")
            await asyncio.sleep(60)

    async def scan_nightly(self) -> None:
        """Queue at most ten due materials per user and thirty globally."""
        queued = 0
        for owner_id in _owner_ids():
            per_owner = 0
            store = _owner_store(owner_id)
            for path in sorted(store.root.glob("*.json")):
                if queued >= 30 or per_owner >= 10:
                    return
                material_id = path.stem
                try:
                    material = store.get(material_id)
                except TimedMediaNotFound:
                    continue
                if (material.get("transcript") or {}).get("cues"):
                    continue
                fetch = transcript_fetch(material)
                due = _parse_time(fetch["next_retry_at"])
                if fetch["status"] in {"auth_required", "unavailable"} or (due and due > _now()):
                    continue
                await self.enqueue(owner_id, material_id)
                queued += 1
                per_owner += 1


_service: SubtitlePrefetchService | None = None


def get_subtitle_prefetch_service() -> SubtitlePrefetchService:
    global _service
    if _service is None:
        _service = SubtitlePrefetchService()
    return _service
