"""SQLite persistence for the media domain.

There are deliberately two stores: a deployment-wide cache for public catalog
metadata, and one private database per DeepTutor workspace.  Only canonical
identifiers and stable metadata enter either database; signed stream URLs are
capabilities, not records.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import threading
from typing import Any, Iterator, Sequence
import uuid

from deeptutor.multi_user import paths as user_paths
from deeptutor.multi_user.paths import get_current_path_service

from .models import (
    ImportJobStatus,
    MediaItem,
    MediaType,
    PlaylistKind,
    SmartPlaylistRule,
)


class MediaStoreError(ValueError):
    """A request could not be represented safely in the media store."""


class MediaNotFound(MediaStoreError):
    pass


class PlaylistNotFound(MediaStoreError):
    pass


class ImportPreviewNotFound(MediaStoreError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _loads(value: object, default: Any) -> Any:
    if not isinstance(value, str) or not value:
        return default
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return default
    return loaded if isinstance(loaded, type(default)) else default


def media_id_for(canonical_id: str) -> str:
    digest = hashlib.sha256(canonical_id.encode("utf-8")).hexdigest()[:24]
    return f"media_{digest}"


class _SQLiteStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        raise NotImplementedError


class CatalogStore(_SQLiteStore):
    """Bounded, deployment-level cache of public metadata.

    It is intentionally not a shared user library: favorites, progress,
    subscriptions, source preferences and imported playlist items remain in
    ``MediaStore`` only.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        path = db_path or (user_paths.SYSTEM_ROOT / "media" / "catalog.sqlite3")
        super().__init__(Path(path))

    def _initialize(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS media_catalog_schema (version INTEGER NOT NULL);
                INSERT INTO media_catalog_schema(version)
                    SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM media_catalog_schema);
                CREATE TABLE IF NOT EXISTS catalog_items (
                    canonical_id TEXT PRIMARY KEY,
                    media_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    creator TEXT NOT NULL DEFAULT '',
                    collection_title TEXT NOT NULL DEFAULT '',
                    artwork_url TEXT NOT NULL DEFAULT '',
                    language TEXT NOT NULL DEFAULT '',
                    duration_seconds REAL NOT NULL DEFAULT 0,
                    published_at TEXT NOT NULL DEFAULT '',
                    source_url TEXT NOT NULL DEFAULT '',
                    cached_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_catalog_items_title ON catalog_items(title COLLATE NOCASE);
                """
            )

    def upsert(self, item: MediaItem) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO catalog_items (
                    canonical_id, media_type, title, creator, collection_title,
                    artwork_url, language, duration_seconds, published_at,
                    source_url, cached_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(canonical_id) DO UPDATE SET
                    media_type=excluded.media_type, title=excluded.title,
                    creator=excluded.creator, collection_title=excluded.collection_title,
                    artwork_url=excluded.artwork_url, language=excluded.language,
                    duration_seconds=excluded.duration_seconds,
                    published_at=excluded.published_at, source_url=excluded.source_url,
                    cached_at=excluded.cached_at
                """,
                (
                    item.canonical_id,
                    item.media_type.value,
                    item.title,
                    item.creator,
                    item.collection_title,
                    item.artwork_url,
                    item.language,
                    item.duration_seconds,
                    item.published_at,
                    item.source_url,
                    utc_now(),
                ),
            )

    def search(self, query: str, limit: int = 20) -> list[MediaItem]:
        normalized = query.strip()
        if not normalized:
            return []
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM catalog_items
                WHERE title LIKE ? COLLATE NOCASE OR creator LIKE ? COLLATE NOCASE
                ORDER BY cached_at DESC LIMIT ?
                """,
                (f"%{normalized}%", f"%{normalized}%", max(1, min(limit, 100))),
            ).fetchall()
        return [
            MediaItem(
                item_id=media_id_for(str(row["canonical_id"])),
                canonical_id=str(row["canonical_id"]),
                media_type=MediaType(str(row["media_type"])),
                title=str(row["title"]),
                creator=str(row["creator"]),
                collection_title=str(row["collection_title"]),
                artwork_url=str(row["artwork_url"]),
                language=str(row["language"]),
                duration_seconds=float(row["duration_seconds"]),
                published_at=str(row["published_at"]),
                source_url=str(row["source_url"]),
            )
            for row in rows
        ]


class MediaStore(_SQLiteStore):
    """Private music, podcast, playlist and sync metadata for one owner."""

    def __init__(self, root: Path | str | None = None) -> None:
        if root is None:
            root = get_current_path_service().get_user_root() / "media"
        root_path = Path(root)
        super().__init__(root_path / "media.sqlite3")

    def _initialize(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS media_schema (version INTEGER NOT NULL);
                INSERT INTO media_schema(version)
                    SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM media_schema);

                CREATE TABLE IF NOT EXISTS media_items (
                    item_id TEXT PRIMARY KEY,
                    canonical_id TEXT NOT NULL UNIQUE,
                    media_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    creator TEXT NOT NULL DEFAULT '',
                    collection_title TEXT NOT NULL DEFAULT '',
                    artwork_url TEXT NOT NULL DEFAULT '',
                    language TEXT NOT NULL DEFAULT '',
                    duration_seconds REAL NOT NULL DEFAULT 0,
                    published_at TEXT NOT NULL DEFAULT '',
                    source_url TEXT NOT NULL DEFAULT '',
                    is_favorite INTEGER NOT NULL DEFAULT 0,
                    is_downloaded INTEGER NOT NULL DEFAULT 0,
                    playback_position_seconds REAL NOT NULL DEFAULT 0,
                    playback_duration_seconds REAL NOT NULL DEFAULT 0,
                    playback_completed INTEGER NOT NULL DEFAULT 0,
                    learning_progress REAL NOT NULL DEFAULT 0,
                    added_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_media_items_title ON media_items(title COLLATE NOCASE);
                CREATE INDEX IF NOT EXISTS idx_media_items_added ON media_items(added_at DESC);
                CREATE INDEX IF NOT EXISTS idx_media_items_progress ON media_items(playback_position_seconds DESC);

                CREATE TABLE IF NOT EXISTS playlists (
                    playlist_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    kind TEXT NOT NULL,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    cover_url TEXT NOT NULL DEFAULT '',
                    rule_json TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_playlists_visible ON playlists(deleted_at, pinned DESC, updated_at DESC);

                CREATE TABLE IF NOT EXISTS playlist_items (
                    playlist_item_id TEXT PRIMARY KEY,
                    playlist_id TEXT NOT NULL REFERENCES playlists(playlist_id) ON DELETE CASCADE,
                    item_id TEXT NOT NULL REFERENCES media_items(item_id) ON DELETE RESTRICT,
                    position INTEGER NOT NULL,
                    added_at TEXT NOT NULL,
                    added_from TEXT NOT NULL DEFAULT 'manual',
                    note TEXT NOT NULL DEFAULT '',
                    UNIQUE(playlist_id, item_id),
                    UNIQUE(playlist_id, position)
                );
                CREATE INDEX IF NOT EXISTS idx_playlist_items_position ON playlist_items(playlist_id, position);

                CREATE TABLE IF NOT EXISTS subscriptions (
                    feed_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL DEFAULT '',
                    source_url TEXT NOT NULL DEFAULT '',
                    language TEXT NOT NULL DEFAULT '',
                    subscribed_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS source_mappings (
                    canonical_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    source_url TEXT NOT NULL DEFAULT '',
                    confirmed INTEGER NOT NULL DEFAULT 0,
                    preferred INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(canonical_id, provider, source_id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_media_preferred_source
                    ON source_mappings(canonical_id) WHERE preferred = 1;

                CREATE TABLE IF NOT EXISTS timed_text (
                    item_id TEXT PRIMARY KEY REFERENCES media_items(item_id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    language TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '',
                    cues_json TEXT NOT NULL DEFAULT '[]',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS learning_artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    item_id TEXT NOT NULL REFERENCES media_items(item_id) ON DELETE CASCADE,
                    segment_id TEXT NOT NULL,
                    completed INTEGER NOT NULL DEFAULT 0,
                    note TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    UNIQUE(item_id, segment_id)
                );

                CREATE TABLE IF NOT EXISTS import_previews (
                    preview_token TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    target_playlist_id TEXT,
                    suggested_playlist_name TEXT NOT NULL DEFAULT '',
                    item_count INTEGER NOT NULL,
                    expires_at TEXT NOT NULL,
                    consumed_at TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS import_jobs (
                    job_id TEXT PRIMARY KEY,
                    preview_token TEXT NOT NULL REFERENCES import_previews(preview_token),
                    playlist_id TEXT,
                    status TEXT NOT NULL,
                    imported_item_count INTEGER NOT NULL DEFAULT 0,
                    failed_item_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS idempotency_keys (
                    key TEXT PRIMARY KEY,
                    operation TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sync_mutations (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    mutation_id TEXT NOT NULL UNIQUE,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    occurred_at TEXT NOT NULL
                );
                """
            )
            conn.execute("UPDATE media_schema SET version = 1")

    # -- media -----------------------------------------------------------

    def upsert_media(self, item: MediaItem) -> MediaItem:
        if len(item.canonical_id) > 512 or not item.canonical_id.strip():
            raise MediaStoreError("A stable canonical media id is required.")
        now = utc_now()
        item_id = item.item_id or media_id_for(item.canonical_id)
        with self._lock, self._connect() as conn:
            existing = conn.execute(
                "SELECT added_at FROM media_items WHERE canonical_id = ?", (item.canonical_id,)
            ).fetchone()
            added_at = str(existing["added_at"]) if existing else (item.added_at or now)
            conn.execute(
                """
                INSERT INTO media_items (
                    item_id, canonical_id, media_type, title, creator, collection_title,
                    artwork_url, language, duration_seconds, published_at, source_url,
                    is_favorite, is_downloaded, playback_position_seconds,
                    playback_duration_seconds, playback_completed, learning_progress,
                    added_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(canonical_id) DO UPDATE SET
                    media_type=excluded.media_type, title=excluded.title,
                    creator=excluded.creator, collection_title=excluded.collection_title,
                    artwork_url=excluded.artwork_url, language=excluded.language,
                    duration_seconds=excluded.duration_seconds, published_at=excluded.published_at,
                    source_url=excluded.source_url, updated_at=excluded.updated_at
                """,
                (
                    item_id,
                    item.canonical_id,
                    item.media_type.value,
                    item.title.strip() or item.canonical_id,
                    item.creator,
                    item.collection_title,
                    item.artwork_url,
                    item.language,
                    item.duration_seconds,
                    item.published_at,
                    item.source_url,
                    int(item.is_favorite),
                    int(item.is_downloaded),
                    item.playback_position_seconds,
                    0,
                    0,
                    item.learning_progress,
                    added_at,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM media_items WHERE canonical_id = ?", (item.canonical_id,)
            ).fetchone()
        assert row is not None
        return self._media_from_row(row)

    def _media_from_row(self, row: sqlite3.Row) -> MediaItem:
        return MediaItem(
            item_id=str(row["item_id"]),
            canonical_id=str(row["canonical_id"]),
            media_type=MediaType(str(row["media_type"])),
            title=str(row["title"]),
            creator=str(row["creator"]),
            collection_title=str(row["collection_title"]),
            artwork_url=str(row["artwork_url"]),
            language=str(row["language"]),
            duration_seconds=float(row["duration_seconds"]),
            published_at=str(row["published_at"]),
            source_url=str(row["source_url"]),
            is_favorite=bool(row["is_favorite"]),
            is_downloaded=bool(row["is_downloaded"]),
            playback_position_seconds=float(row["playback_position_seconds"]),
            learning_progress=float(row["learning_progress"]),
            added_at=str(row["added_at"]),
        )

    def get_media(self, item_id: str) -> MediaItem:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM media_items WHERE item_id = ?", (item_id,)).fetchone()
        if row is None:
            raise MediaNotFound("Media item was not found.")
        return self._media_from_row(row)

    def get_media_by_canonical_id(self, canonical_id: str) -> MediaItem | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM media_items WHERE canonical_id = ?", (canonical_id,)
            ).fetchone()
        return self._media_from_row(row) if row else None

    def list_media(self, *, limit: int = 100, query: str = "") -> list[MediaItem]:
        with self._lock, self._connect() as conn:
            if query.strip():
                rows = conn.execute(
                    """SELECT * FROM media_items
                       WHERE title LIKE ? COLLATE NOCASE OR creator LIKE ? COLLATE NOCASE
                       ORDER BY added_at DESC LIMIT ?""",
                    (f"%{query.strip()}%", f"%{query.strip()}%", max(1, min(limit, 500))),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM media_items ORDER BY added_at DESC LIMIT ?",
                    (max(1, min(limit, 500)),),
                ).fetchall()
        return [self._media_from_row(row) for row in rows]

    def set_playback(
        self, item_id: str, *, position_seconds: float, duration_seconds: float, completed: bool
    ) -> MediaItem:
        with self._lock, self._connect() as conn:
            existing = conn.execute("SELECT item_id FROM media_items WHERE item_id = ?", (item_id,)).fetchone()
            if existing is None:
                raise MediaNotFound("Media item was not found.")
            duration = max(0.0, duration_seconds)
            position = max(0.0, min(position_seconds, duration)) if duration else max(0.0, position_seconds)
            conn.execute(
                """UPDATE media_items SET playback_position_seconds = ?, playback_duration_seconds = ?,
                   playback_completed = ?, updated_at = ? WHERE item_id = ?""",
                (position, duration, int(completed), utc_now(), item_id),
            )
            row = conn.execute("SELECT * FROM media_items WHERE item_id = ?", (item_id,)).fetchone()
        assert row is not None
        return self._media_from_row(row)

    def set_favorite_or_download(self, item_id: str, *, favorite: bool | None = None, downloaded: bool | None = None) -> MediaItem:
        assignments: list[str] = []
        values: list[object] = []
        if favorite is not None:
            assignments.append("is_favorite = ?")
            values.append(int(favorite))
        if downloaded is not None:
            assignments.append("is_downloaded = ?")
            values.append(int(downloaded))
        if not assignments:
            return self.get_media(item_id)
        assignments.append("updated_at = ?")
        values.append(utc_now())
        values.append(item_id)
        with self._lock, self._connect() as conn:
            updated = conn.execute(
                f"UPDATE media_items SET {', '.join(assignments)} WHERE item_id = ?", values
            ).rowcount
            if not updated:
                raise MediaNotFound("Media item was not found.")
            row = conn.execute("SELECT * FROM media_items WHERE item_id = ?", (item_id,)).fetchone()
        assert row is not None
        return self._media_from_row(row)

    # -- playlists -------------------------------------------------------

    def ensure_system_playlists(self) -> None:
        defaults: Sequence[tuple[str, str, SmartPlaylistRule]] = (
            ("liked", "我喜欢的", SmartPlaylistRule(favorite=True)),
            ("recently_added", "最近添加", SmartPlaylistRule()),
            ("recently_played", "最近播放", SmartPlaylistRule(playback_state="played")),
            ("continue_listening", "继续收听", SmartPlaylistRule(playback_state="in_progress")),
            ("new_podcast_episodes", "新播客单集", SmartPlaylistRule(media_types=[MediaType.EPISODE])),
            ("to_learn", "待学习", SmartPlaylistRule(learning_state="not_started")),
            ("downloaded", "已下载", SmartPlaylistRule(downloaded=True)),
            ("weekly_deep_listening", "本周精听", SmartPlaylistRule(learning_state="in_progress")),
        )
        now = utc_now()
        with self._lock, self._connect() as conn:
            for suffix, name, rule in defaults:
                playlist_id = f"system_{suffix}"
                conn.execute(
                    """INSERT OR IGNORE INTO playlists(
                        playlist_id, name, kind, rule_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)""",
                    (playlist_id, name, PlaylistKind.SYSTEM.value, _json(rule.model_dump(mode="json")), now, now),
                )

    def create_playlist(
        self,
        *,
        name: str,
        description: str,
        kind: PlaylistKind,
        pinned: bool = False,
        rule: SmartPlaylistRule | None = None,
    ) -> dict[str, Any]:
        if kind not in {PlaylistKind.MANUAL, PlaylistKind.SMART, PlaylistKind.EXTERNAL_IMPORT}:
            raise MediaStoreError("Only manual, smart or imported playlists may be created.")
        if not name.strip():
            raise MediaStoreError("Playlist name is required.")
        now = utc_now()
        playlist_id = new_id("playlist")
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO playlists(
                    playlist_id, name, description, kind, pinned, rule_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    playlist_id,
                    name.strip(),
                    description.strip(),
                    kind.value,
                    int(pinned),
                    _json(rule.model_dump(mode="json")) if rule else "",
                    now,
                    now,
                ),
            )
        self._record_mutation("playlist", playlist_id, "upsert", {"name": name.strip()})
        return self.get_playlist_row(playlist_id)

    def list_playlists(self) -> list[dict[str, Any]]:
        self.ensure_system_playlists()
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """SELECT p.*, COUNT(i.playlist_item_id) AS stored_item_count
                   FROM playlists p LEFT JOIN playlist_items i ON i.playlist_id = p.playlist_id
                   WHERE p.deleted_at = '' GROUP BY p.playlist_id
                   ORDER BY p.pinned DESC, p.updated_at DESC"""
            ).fetchall()
        return [self._playlist_from_row(row) for row in rows]

    def get_playlist_row(self, playlist_id: str) -> dict[str, Any]:
        self.ensure_system_playlists()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """SELECT p.*, COUNT(i.playlist_item_id) AS stored_item_count
                   FROM playlists p LEFT JOIN playlist_items i ON i.playlist_id = p.playlist_id
                   WHERE p.playlist_id = ? AND p.deleted_at = '' GROUP BY p.playlist_id""",
                (playlist_id,),
            ).fetchone()
        if row is None:
            raise PlaylistNotFound("Playlist was not found.")
        return self._playlist_from_row(row)

    def _playlist_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        rule_raw = _loads(row["rule_json"], {})
        rule = SmartPlaylistRule.model_validate(rule_raw) if rule_raw else None
        kind = PlaylistKind(str(row["kind"]))
        count = int(row["stored_item_count"])
        if kind in {PlaylistKind.SMART, PlaylistKind.SYSTEM}:
            count = len(self.materialize_smart_playlist(rule or SmartPlaylistRule()))
        return {
            "playlist_id": str(row["playlist_id"]),
            "name": str(row["name"]),
            "description": str(row["description"]),
            "kind": kind.value,
            "pinned": bool(row["pinned"]),
            "cover_url": str(row["cover_url"]),
            "rule": rule.model_dump(mode="json") if rule else None,
            "item_count": count,
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    def get_playlist_items(self, playlist_id: str) -> list[dict[str, Any]]:
        playlist = self.get_playlist_row(playlist_id)
        if playlist["kind"] in {PlaylistKind.SMART.value, PlaylistKind.SYSTEM.value}:
            rule = SmartPlaylistRule.model_validate(playlist["rule"] or {})
            return [
                {
                    "item_id": f"smart_{media.item_id}",
                    "media": media.model_dump(mode="json"),
                    "position": index,
                    "added_at": media.added_at,
                    "added_from": "smart_rule",
                    "note": "",
                }
                for index, media in enumerate(self.materialize_smart_playlist(rule))
            ]
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """SELECT i.playlist_item_id, i.position, i.added_at, i.added_from, i.note,
                          m.* FROM playlist_items i JOIN media_items m ON m.item_id = i.item_id
                   WHERE i.playlist_id = ? ORDER BY i.position ASC""",
                (playlist_id,),
            ).fetchall()
        return [
            {
                "item_id": str(row["playlist_item_id"]),
                "media": self._media_from_row(row).model_dump(mode="json"),
                "position": int(row["position"]),
                "added_at": str(row["added_at"]),
                "added_from": str(row["added_from"]),
                "note": str(row["note"]),
            }
            for row in rows
        ]

    def update_playlist(
        self,
        playlist_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        pinned: bool | None = None,
        rule: SmartPlaylistRule | None = None,
    ) -> dict[str, Any]:
        current = self.get_playlist_row(playlist_id)
        if current["kind"] == PlaylistKind.SYSTEM.value:
            raise MediaStoreError("System playlists cannot be edited.")
        assignments: list[str] = []
        values: list[object] = []
        if name is not None:
            assignments.append("name = ?")
            values.append(name.strip())
        if description is not None:
            assignments.append("description = ?")
            values.append(description.strip())
        if pinned is not None:
            assignments.append("pinned = ?")
            values.append(int(pinned))
        if rule is not None:
            assignments.append("rule_json = ?")
            values.append(_json(rule.model_dump(mode="json")))
        if assignments:
            assignments.append("updated_at = ?")
            values.append(utc_now())
            values.append(playlist_id)
            with self._lock, self._connect() as conn:
                conn.execute(
                    f"UPDATE playlists SET {', '.join(assignments)} WHERE playlist_id = ?", values
                )
            self._record_mutation("playlist", playlist_id, "upsert", {"updated": True})
        return self.get_playlist_row(playlist_id)

    def delete_playlist(self, playlist_id: str) -> None:
        current = self.get_playlist_row(playlist_id)
        if current["kind"] == PlaylistKind.SYSTEM.value:
            raise MediaStoreError("System playlists cannot be deleted.")
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE playlists SET deleted_at = ?, updated_at = ? WHERE playlist_id = ?",
                (utc_now(), utc_now(), playlist_id),
            )
        self._record_mutation("playlist", playlist_id, "delete", {})

    def add_playlist_items(
        self, playlist_id: str, canonical_ids: Sequence[str], *, added_from: str, note: str
    ) -> list[dict[str, Any]]:
        playlist = self.get_playlist_row(playlist_id)
        if playlist["kind"] not in {PlaylistKind.MANUAL.value, PlaylistKind.EXTERNAL_IMPORT.value}:
            raise MediaStoreError("Only manual playlists hold stored items.")
        with self._lock, self._connect() as conn:
            rows = [
                conn.execute("SELECT item_id FROM media_items WHERE canonical_id = ?", (canonical_id,)).fetchone()
                for canonical_id in canonical_ids
            ]
            if any(row is None for row in rows):
                raise MediaNotFound("One or more media items were not found in the library.")
            position = int(
                conn.execute(
                    "SELECT COALESCE(MAX(position), -1) + 1 FROM playlist_items WHERE playlist_id = ?",
                    (playlist_id,),
                ).fetchone()[0]
            )
            now = utc_now()
            for row in rows:
                assert row is not None
                try:
                    conn.execute(
                        """INSERT INTO playlist_items(
                            playlist_item_id, playlist_id, item_id, position, added_at, added_from, note
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (new_id("playlist_item"), playlist_id, str(row["item_id"]), position, now, added_from, note),
                    )
                    position += 1
                except sqlite3.IntegrityError:
                    continue
            conn.execute("UPDATE playlists SET updated_at = ? WHERE playlist_id = ?", (now, playlist_id))
        self._record_mutation("playlist", playlist_id, "upsert", {"items_added": len(canonical_ids)})
        return self.get_playlist_items(playlist_id)

    def remove_playlist_item(self, playlist_id: str, playlist_item_id: str) -> bool:
        playlist = self.get_playlist_row(playlist_id)
        if playlist["kind"] not in {PlaylistKind.MANUAL.value, PlaylistKind.EXTERNAL_IMPORT.value}:
            raise MediaStoreError("Smart playlists calculate their own items.")
        with self._lock, self._connect() as conn:
            deleted = conn.execute(
                "DELETE FROM playlist_items WHERE playlist_id = ? AND playlist_item_id = ?",
                (playlist_id, playlist_item_id),
            ).rowcount
            if deleted:
                self._normalize_positions(conn, playlist_id)
                conn.execute("UPDATE playlists SET updated_at = ? WHERE playlist_id = ?", (utc_now(), playlist_id))
        if deleted:
            self._record_mutation("playlist_item", playlist_item_id, "delete", {"playlist_id": playlist_id})
        return bool(deleted)

    def reorder_playlist_items(self, playlist_id: str, item_ids: Sequence[str]) -> list[dict[str, Any]]:
        playlist = self.get_playlist_row(playlist_id)
        if playlist["kind"] not in {PlaylistKind.MANUAL.value, PlaylistKind.EXTERNAL_IMPORT.value}:
            raise MediaStoreError("Smart playlists cannot be reordered.")
        with self._lock, self._connect() as conn:
            existing = [
                str(row["playlist_item_id"])
                for row in conn.execute(
                    "SELECT playlist_item_id FROM playlist_items WHERE playlist_id = ? ORDER BY position",
                    (playlist_id,),
                ).fetchall()
            ]
            if set(existing) != set(item_ids) or len(existing) != len(item_ids):
                raise MediaStoreError("The ordering must contain each playlist item exactly once.")
            for position, item_id in enumerate(item_ids):
                conn.execute(
                    "UPDATE playlist_items SET position = ? WHERE playlist_id = ? AND playlist_item_id = ?",
                    (-position - 1, playlist_id, item_id),
                )
            for position, item_id in enumerate(item_ids):
                conn.execute(
                    "UPDATE playlist_items SET position = ? WHERE playlist_id = ? AND playlist_item_id = ?",
                    (position, playlist_id, item_id),
                )
            conn.execute("UPDATE playlists SET updated_at = ? WHERE playlist_id = ?", (utc_now(), playlist_id))
        self._record_mutation("playlist", playlist_id, "upsert", {"reordered": True})
        return self.get_playlist_items(playlist_id)

    @staticmethod
    def _normalize_positions(conn: sqlite3.Connection, playlist_id: str) -> None:
        rows = conn.execute(
            "SELECT playlist_item_id FROM playlist_items WHERE playlist_id = ? ORDER BY position", (playlist_id,)
        ).fetchall()
        for position, row in enumerate(rows):
            conn.execute(
                "UPDATE playlist_items SET position = ? WHERE playlist_item_id = ?",
                (position, str(row["playlist_item_id"])),
            )

    def materialize_smart_playlist(self, rule: SmartPlaylistRule, limit: int = 200) -> list[MediaItem]:
        clauses: list[str] = []
        values: list[object] = []
        if rule.media_types:
            clauses.append("media_type IN (%s)" % ",".join("?" for _ in rule.media_types))
            values.extend(kind.value for kind in rule.media_types)
        if rule.downloaded is not None:
            clauses.append("is_downloaded = ?")
            values.append(int(rule.downloaded))
        if rule.favorite is not None:
            clauses.append("is_favorite = ?")
            values.append(int(rule.favorite))
        if rule.language:
            clauses.append("language = ?")
            values.append(rule.language)
        if rule.min_duration_seconds is not None:
            clauses.append("duration_seconds >= ?")
            values.append(rule.min_duration_seconds)
        if rule.max_duration_seconds is not None:
            clauses.append("duration_seconds <= ?")
            values.append(rule.max_duration_seconds)
        if rule.playback_state == "unplayed":
            clauses.append("playback_position_seconds = 0 AND playback_completed = 0")
        elif rule.playback_state == "in_progress":
            clauses.append("playback_position_seconds > 0 AND playback_completed = 0")
        elif rule.playback_state == "played":
            clauses.append("playback_position_seconds > 0")
        if rule.learning_state == "not_started":
            clauses.append("learning_progress = 0")
        elif rule.learning_state == "in_progress":
            clauses.append("learning_progress > 0 AND learning_progress < 1")
        elif rule.learning_state == "complete":
            clauses.append("learning_progress >= 1")
        if rule.added_after:
            clauses.append("added_at >= ?")
            values.append(rule.added_after)
        if rule.published_after:
            clauses.append("published_at >= ?")
            values.append(rule.published_after)
        if rule.subscribed_only:
            clauses.append("EXISTS (SELECT 1 FROM subscriptions s WHERE s.feed_id = media_items.canonical_id OR media_items.source_url LIKE s.source_url || '%')")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM media_items{where} ORDER BY added_at DESC LIMIT ?",
                [*values, max(1, min(limit, 500))],
            ).fetchall()
        return [self._media_from_row(row) for row in rows]

    # -- subscriptions, sources and learning ---------------------------

    def upsert_subscription(self, feed_id: str, *, title: str, source_url: str, language: str) -> dict[str, Any]:
        now = utc_now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO subscriptions(feed_id, title, source_url, language, subscribed_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(feed_id) DO UPDATE SET title=excluded.title, source_url=excluded.source_url,
                       language=excluded.language, updated_at=excluded.updated_at""",
                (feed_id, title, source_url, language, now, now),
            )
        self._record_mutation("subscription", feed_id, "upsert", {"title": title})
        return {"feed_id": feed_id, "title": title, "source_url": source_url, "language": language}

    def remove_subscription(self, feed_id: str) -> bool:
        with self._lock, self._connect() as conn:
            deleted = conn.execute("DELETE FROM subscriptions WHERE feed_id = ?", (feed_id,)).rowcount
        if deleted:
            self._record_mutation("subscription", feed_id, "delete", {})
        return bool(deleted)

    def list_subscriptions(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM subscriptions ORDER BY updated_at DESC").fetchall()
        return [dict(row) for row in rows]

    def put_source_mapping(
        self, canonical_id: str, *, provider: str, source_id: str, source_url: str, confirmed: bool, preferred: bool
    ) -> dict[str, Any]:
        now = utc_now()
        with self._lock, self._connect() as conn:
            if preferred:
                conn.execute("UPDATE source_mappings SET preferred = 0 WHERE canonical_id = ?", (canonical_id,))
            conn.execute(
                """INSERT INTO source_mappings(canonical_id, provider, source_id, source_url, confirmed, preferred, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(canonical_id, provider, source_id) DO UPDATE SET source_url=excluded.source_url,
                       confirmed=excluded.confirmed, preferred=excluded.preferred, updated_at=excluded.updated_at""",
                (canonical_id, provider, source_id, source_url, int(confirmed), int(preferred), now),
            )
        return {
            "canonical_id": canonical_id, "provider": provider, "source_id": source_id,
            "source_url": source_url, "confirmed": confirmed, "preferred": preferred,
        }

    def list_source_mappings(self, canonical_id: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM source_mappings WHERE canonical_id = ? ORDER BY preferred DESC, confirmed DESC, updated_at DESC",
                (canonical_id,),
            ).fetchall()
        return [
            {
                "canonical_id": str(row["canonical_id"]), "provider": str(row["provider"]),
                "source_id": str(row["source_id"]), "source_url": str(row["source_url"]),
                "confirmed": bool(row["confirmed"]), "preferred": bool(row["preferred"]),
            }
            for row in rows
        ]

    def delete_preferred_source(self, canonical_id: str) -> bool:
        with self._lock, self._connect() as conn:
            return bool(conn.execute("UPDATE source_mappings SET preferred = 0 WHERE canonical_id = ?", (canonical_id,)).rowcount)

    def get_timed_text(self, item_id: str) -> dict[str, Any]:
        self.get_media(item_id)
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM timed_text WHERE item_id = ?", (item_id,)).fetchone()
        if not row:
            return {"item_id": item_id, "status": "unavailable", "language": "", "source": "", "cues": []}
        return {
            "item_id": item_id, "status": str(row["status"]), "language": str(row["language"]),
            "source": str(row["source"]), "cues": _loads(row["cues_json"], []),
        }

    def create_learning_artifact(self, item_id: str, segment_id: str, *, completed: bool, note: str) -> dict[str, Any]:
        self.get_media(item_id)
        now = utc_now()
        artifact_id = new_id("learning")
        with self._lock, self._connect() as conn:
            existing = conn.execute(
                "SELECT artifact_id FROM learning_artifacts WHERE item_id = ? AND segment_id = ?",
                (item_id, segment_id),
            ).fetchone()
            if existing:
                artifact_id = str(existing["artifact_id"])
            conn.execute(
                """INSERT INTO learning_artifacts(artifact_id, item_id, segment_id, completed, note, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(item_id, segment_id) DO UPDATE SET completed=excluded.completed,
                       note=excluded.note, updated_at=excluded.updated_at""",
                (artifact_id, item_id, segment_id, int(completed), note, now),
            )
            progress = conn.execute(
                "SELECT AVG(completed) AS value FROM learning_artifacts WHERE item_id = ?", (item_id,)
            ).fetchone()["value"]
            conn.execute("UPDATE media_items SET learning_progress = ?, updated_at = ? WHERE item_id = ?", (float(progress or 0), now, item_id))
        return {"artifact_id": artifact_id, "item_id": item_id, "segment_id": segment_id, "status": "ready", "completed": completed, "note": note}

    # -- import and sync bookkeeping -----------------------------------

    def save_import_preview(
        self, *, candidates: list[dict[str, Any]], target_playlist_id: str | None, suggested_playlist_name: str
    ) -> dict[str, Any]:
        token = secrets.token_urlsafe(32)
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
        payload = {"candidates": candidates}
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO import_previews(preview_token, payload_json, target_playlist_id, suggested_playlist_name, item_count, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (token, _json(payload), target_playlist_id, suggested_playlist_name, len(candidates), expires_at),
            )
        return {
            "preview_token": token, "expires_at": expires_at, "candidates": candidates,
            "target_playlist_id": target_playlist_id, "suggested_playlist_name": suggested_playlist_name,
            "item_count": len(candidates),
        }

    def get_import_preview(self, preview_token: str, *, allow_consumed: bool = False) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM import_previews WHERE preview_token = ?", (preview_token,)).fetchone()
        if row is None:
            raise ImportPreviewNotFound("Import preview was not found.")
        if str(row["expires_at"]) <= utc_now():
            raise ImportPreviewNotFound("Import preview has expired. Create a new preview.")
        if str(row["consumed_at"]) and not allow_consumed:
            raise MediaStoreError("Import preview has already been applied.")
        payload = _loads(row["payload_json"], {"candidates": []})
        return {
            "preview_token": str(row["preview_token"]), "expires_at": str(row["expires_at"]),
            "candidates": payload.get("candidates", []),
            "target_playlist_id": str(row["target_playlist_id"]) if row["target_playlist_id"] else None,
            "suggested_playlist_name": str(row["suggested_playlist_name"]), "item_count": int(row["item_count"]),
            "consumed_at": str(row["consumed_at"]),
        }

    def consume_import_preview(self, preview_token: str) -> None:
        with self._lock, self._connect() as conn:
            changed = conn.execute(
                "UPDATE import_previews SET consumed_at = ? WHERE preview_token = ? AND consumed_at = ''",
                (utc_now(), preview_token),
            ).rowcount
        if not changed:
            raise MediaStoreError("Import preview has already been applied.")

    def create_import_job(self, preview_token: str) -> dict[str, Any]:
        now = utc_now()
        job_id = new_id("import")
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO import_jobs(job_id, preview_token, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (job_id, preview_token, ImportJobStatus.QUEUED.value, now, now),
            )
        return self.get_import_job(job_id)

    def update_import_job(self, job_id: str, *, status: ImportJobStatus, playlist_id: str | None = None, imported: int = 0, failed: int = 0, error: str = "") -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            conn.execute(
                """UPDATE import_jobs SET status=?, playlist_id=COALESCE(?, playlist_id),
                   imported_item_count=?, failed_item_count=?, error=?, updated_at=? WHERE job_id=?""",
                (status.value, playlist_id, imported, failed, error, utc_now(), job_id),
            )
        return self.get_import_job(job_id)

    def get_import_job(self, job_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM import_jobs WHERE job_id = ?", (job_id,)).fetchone()
        if not row:
            raise MediaNotFound("Import job was not found.")
        return {
            "job_id": str(row["job_id"]), "status": str(row["status"]),
            "preview_token": str(row["preview_token"]), "playlist_id": str(row["playlist_id"]) if row["playlist_id"] else None,
            "imported_item_count": int(row["imported_item_count"]), "failed_item_count": int(row["failed_item_count"]),
            "created_at": str(row["created_at"]), "updated_at": str(row["updated_at"]), "error": str(row["error"]),
        }

    def get_idempotent_response(self, key: str, operation: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM idempotency_keys WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        if str(row["operation"]) != operation:
            raise MediaStoreError("Idempotency-Key was already used for a different operation.")
        return _loads(row["response_json"], {})

    def save_idempotent_response(self, key: str, operation: str, response: dict[str, Any]) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO idempotency_keys(key, operation, response_json, created_at) VALUES (?, ?, ?, ?)",
                (key, operation, _json(response), utc_now()),
            )

    def _record_mutation(self, entity_type: str, entity_id: str, operation: str, payload: dict[str, Any]) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO sync_mutations(mutation_id, entity_type, entity_id, operation, payload_json, occurred_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (new_id("mutation"), entity_type, entity_id, operation, _json(payload), utc_now()),
            )

    def push_mutations(self, mutations: Sequence[dict[str, Any]]) -> str:
        with self._lock, self._connect() as conn:
            for mutation in mutations:
                conn.execute(
                    """INSERT OR IGNORE INTO sync_mutations(mutation_id, entity_type, entity_id, operation, payload_json, occurred_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        mutation["mutation_id"], mutation["entity_type"], mutation["entity_id"],
                        mutation["operation"], _json(mutation.get("payload") or {}), mutation.get("occurred_at") or utc_now(),
                    ),
                )
            cursor = conn.execute("SELECT COALESCE(MAX(sequence), 0) AS cursor FROM sync_mutations").fetchone()["cursor"]
        return str(cursor)

    def pull_mutations(self, cursor: str, limit: int = 500) -> dict[str, Any]:
        try:
            sequence = max(0, int(cursor or "0"))
        except ValueError as exc:
            raise MediaStoreError("Sync cursor is invalid.") from exc
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sync_mutations WHERE sequence > ? ORDER BY sequence ASC LIMIT ?",
                (sequence, max(1, min(limit, 500))),
            ).fetchall()
        next_cursor = str(rows[-1]["sequence"]) if rows else str(sequence)
        return {
            "cursor": next_cursor,
            "mutations": [
                {
                    "mutation_id": str(row["mutation_id"]), "entity_type": str(row["entity_type"]),
                    "entity_id": str(row["entity_id"]), "operation": str(row["operation"]),
                    "payload": _loads(row["payload_json"], {}), "occurred_at": str(row["occurred_at"]),
                }
                for row in rows
            ],
        }


__all__ = [
    "CatalogStore", "ImportPreviewNotFound", "MediaNotFound", "MediaStore", "MediaStoreError",
    "PlaylistNotFound", "media_id_for", "new_id", "utc_now",
]
