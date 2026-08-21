"""SQLite-backed production storage for synced MarginNote 4 objects."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any
import uuid

from deeptutor.capabilities.marginnote4.models import (
    ALL_TYPES,
    DeletedMarginNoteObject,
    MarginNoteObject,
    MarginNoteSyncConflict,
    SyncBatch,
    SyncResult,
)

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mn4_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mn4_objects (
    generation_id TEXT NOT NULL,
    object_id TEXT NOT NULL,
    source_device_id TEXT NOT NULL,
    object_type TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    excerpt TEXT,
    document_id TEXT,
    document_title TEXT,
    page INTEGER,
    tags TEXT NOT NULL DEFAULT '[]',
    links TEXT NOT NULL DEFAULT '[]',
    color TEXT,
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    synced_at TEXT NOT NULL DEFAULT '',
    revision INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT NOT NULL DEFAULT '',
    raw TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (generation_id, object_id)
);

CREATE INDEX IF NOT EXISTS idx_mn4_generation_type
    ON mn4_objects (generation_id, object_type);
CREATE INDEX IF NOT EXISTS idx_mn4_generation_doc
    ON mn4_objects (generation_id, document_id);
CREATE INDEX IF NOT EXISTS idx_mn4_generation_updated
    ON mn4_objects (generation_id, updated_at);

CREATE TABLE IF NOT EXISTS mn4_tombstones (
    generation_id TEXT NOT NULL,
    object_id TEXT NOT NULL,
    source_device_id TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT '',
    deleted_at TEXT NOT NULL,
    PRIMARY KEY (generation_id, object_id)
);

CREATE TABLE IF NOT EXISTS mn4_live_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    generation_id TEXT NOT NULL,
    cursor TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mn4_device_cursors (
    device_id TEXT PRIMARY KEY,
    cursor TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mn4_sync_batches (
    device_id TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    cursor TEXT NOT NULL,
    response_json TEXT NOT NULL,
    received_at TEXT NOT NULL,
    PRIMARY KEY (device_id, batch_id)
);

CREATE TABLE IF NOT EXISTS mn4_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    generation_id TEXT NOT NULL UNIQUE,
    device_id TEXT NOT NULL,
    total_batches INTEGER NOT NULL,
    next_sequence INTEGER NOT NULL DEFAULT 1,
    state TEXT NOT NULL DEFAULT 'staging',
    created_at TEXT NOT NULL,
    committed_at TEXT
);

CREATE TABLE IF NOT EXISTS mn4_snapshot_batches (
    snapshot_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    batch_id TEXT NOT NULL,
    response_json TEXT NOT NULL,
    received_at TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, sequence),
    UNIQUE (snapshot_id, batch_id)
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_cursor() -> str:
    return f"{_now_iso()}:{uuid.uuid4().hex}"


def _default_db_path(kb_name: str) -> Path:
    """Return the server-owned database path for the current user scope."""
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in kb_name)
    from deeptutor.services.path_service import get_path_service

    return get_path_service().user_data_dir / "marginnote4" / f"{safe}.db"


def _object_hash(obj: MarginNoteObject) -> str:
    payload = obj.to_dict()
    for key in ("synced_at", "device_id", "content_hash"):
        payload.pop(key, None)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class MarginNoteStore:
    """CRUD, search, idempotent incremental sync, and staged snapshots."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._fts_available = False
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            old_objects = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='mn4_objects'"
            ).fetchone()
            old_columns = (
                {row["name"] for row in conn.execute("PRAGMA table_info(mn4_objects)").fetchall()}
                if old_objects
                else set()
            )
            migrating = bool(old_columns and "generation_id" not in old_columns)
            if migrating:
                conn.execute("ALTER TABLE mn4_objects RENAME TO mn4_objects_v1")
            conn.executescript(_SCHEMA)
            if migrating:
                conn.execute(
                    """INSERT INTO mn4_objects
                       (generation_id, object_id, source_device_id, object_type,
                        title, content, excerpt, document_id, document_title, page,
                        tags, links, color, created_at, updated_at, synced_at,
                        revision, content_hash, raw)
                       SELECT 'legacy_v1', object_id, device_id, object_type,
                        title, content, excerpt, document_id, document_title, page,
                        tags, links, color, created_at, updated_at, synced_at,
                        1, 'legacy:' || object_id, raw
                       FROM mn4_objects_v1
                       GROUP BY object_id"""
                )
                conn.execute("DROP TABLE mn4_objects_v1")
                conn.execute(
                    """INSERT OR REPLACE INTO mn4_live_state
                       (id, generation_id, cursor, updated_at)
                       VALUES (1, 'legacy_v1', ?, ?)""",
                    (_new_cursor(), _now_iso()),
                )
            conn.execute(
                "INSERT OR IGNORE INTO mn4_metadata (key, value) VALUES ('schema_version', ?)",
                (str(_SCHEMA_VERSION),),
            )
            conn.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
            row = conn.execute(
                "SELECT value FROM mn4_metadata WHERE key='schema_version'"
            ).fetchone()
            if row is None or int(row["value"]) > _SCHEMA_VERSION:
                raise RuntimeError("MarginNote store was created by a newer DeepTutor")
            self._create_fts(conn)

    def _create_fts(self, conn: sqlite3.Connection) -> None:
        try:
            conn.execute(
                """CREATE VIRTUAL TABLE IF NOT EXISTS mn4_objects_fts USING fts5(
                       doc UNINDEXED,
                       title,
                       content,
                       excerpt,
                       document_title,
                       tokenize='unicode61'
                   )"""
            )
            self._fts_available = True
        except sqlite3.OperationalError:
            self._fts_available = False
            logger.info("SQLite FTS5 unavailable; MarginNote search uses LIKE fallback")

    @property
    def schema_version(self) -> int:
        with self._connect() as conn:
            row = conn.execute("PRAGMA user_version").fetchone()
        return int(row[0])

    @staticmethod
    def _row_to_object(row: sqlite3.Row) -> MarginNoteObject:
        return MarginNoteObject(
            object_id=row["object_id"],
            object_type=row["object_type"],
            title=row["title"],
            content=row["content"],
            excerpt=row["excerpt"],
            document_id=row["document_id"],
            document_title=row["document_title"],
            page=row["page"],
            tags=json.loads(row["tags"]),
            links=json.loads(row["links"]),
            color=row["color"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            synced_at=row["synced_at"],
            device_id=row["source_device_id"],
            revision=int(row["revision"]),
            content_hash=row["content_hash"],
            raw=json.loads(row["raw"]),
        )

    def _live_generation(self, conn: sqlite3.Connection) -> str:
        row = conn.execute("SELECT generation_id FROM mn4_live_state WHERE id=1").fetchone()
        if row is None:
            generation = f"gen_{uuid.uuid4().hex}"
            conn.execute(
                """INSERT INTO mn4_live_state
                   (id, generation_id, cursor, updated_at) VALUES (1, ?, ?, ?)""",
                (generation, _new_cursor(), _now_iso()),
            )
            return generation
        return row["generation_id"]

    def server_cursor(self) -> str:
        with self._connect() as conn:
            row = conn.execute("SELECT cursor FROM mn4_live_state WHERE id=1").fetchone()
        return row["cursor"] if row else ""

    @staticmethod
    def _upsert_object(conn: sqlite3.Connection, generation: str, obj: MarginNoteObject) -> str:
        if obj.object_type not in ALL_TYPES:
            logger.warning("Skipping unknown MN4 type: %s", obj.object_type)
            return "skipped"
        previous = conn.execute(
            """SELECT revision, content_hash FROM mn4_objects
               WHERE generation_id=? AND object_id=?""",
            (generation, obj.object_id),
        ).fetchone()
        content_hash = _object_hash(obj)
        if previous and (
            int(previous["revision"]) > obj.revision
            or (
                int(previous["revision"]) == obj.revision
                and previous["content_hash"] == content_hash
            )
        ):
            return "skipped"
        conn.execute(
            """INSERT INTO mn4_objects
               (generation_id, object_id, source_device_id, object_type, title,
                content, excerpt, document_id, document_title, page, tags, links,
                color, created_at, updated_at, synced_at, revision, content_hash, raw)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(generation_id, object_id) DO UPDATE SET
                 source_device_id=excluded.source_device_id,
                 object_type=excluded.object_type,
                 title=excluded.title,
                 content=excluded.content,
                 excerpt=excluded.excerpt,
                 document_id=excluded.document_id,
                 document_title=excluded.document_title,
                 page=excluded.page,
                 tags=excluded.tags,
                 links=excluded.links,
                 color=excluded.color,
                 created_at=excluded.created_at,
                 updated_at=excluded.updated_at,
                 synced_at=excluded.synced_at,
                 revision=excluded.revision,
                 content_hash=excluded.content_hash,
                 raw=excluded.raw""",
            (
                generation,
                obj.object_id,
                obj.device_id,
                obj.object_type,
                obj.title,
                obj.content,
                obj.excerpt,
                obj.document_id,
                obj.document_title,
                obj.page,
                json.dumps(obj.tags, ensure_ascii=False),
                json.dumps(obj.links, ensure_ascii=False),
                obj.color,
                obj.created_at,
                obj.updated_at,
                obj.synced_at or _now_iso(),
                obj.revision,
                content_hash,
                json.dumps(obj.raw, ensure_ascii=False),
            ),
        )
        conn.execute(
            "DELETE FROM mn4_tombstones WHERE generation_id=? AND object_id=?",
            (generation, obj.object_id),
        )
        return "updated" if previous else "stored"

    @staticmethod
    def _delete_object(
        conn: sqlite3.Connection,
        generation: str,
        object_id: str,
        device_id: str,
        updated_at: str,
    ) -> bool:
        existed = conn.execute(
            "SELECT 1 FROM mn4_objects WHERE generation_id=? AND object_id=?",
            (generation, object_id),
        ).fetchone()
        conn.execute(
            """INSERT OR REPLACE INTO mn4_tombstones
               (generation_id, object_id, source_device_id, updated_at, deleted_at)
               VALUES (?, ?, ?, ?, ?)""",
            (generation, object_id, device_id, updated_at, _now_iso()),
        )
        conn.execute(
            "DELETE FROM mn4_objects WHERE generation_id=? AND object_id=?",
            (generation, object_id),
        )
        return existed is not None

    def _update_fts_docs(self, generation: str, object_ids: list[str]) -> None:
        if not self._fts_available:
            return
        with self._connect() as conn:
            for object_id in object_ids:
                conn.execute(
                    "DELETE FROM mn4_objects_fts WHERE doc=?", (f"{generation}:{object_id}",)
                )
            placeholders = ",".join("?" for _ in object_ids)
            rows = (
                conn.execute(
                    f"""SELECT * FROM mn4_objects
                    WHERE generation_id=? AND object_id IN ({placeholders})""",
                    (generation, *object_ids),
                ).fetchall()
                if object_ids
                else []
            )
            for row in rows:
                conn.execute(
                    """INSERT INTO mn4_objects_fts
                       (doc, title, content, excerpt, document_title)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        f"{generation}:{row['object_id']}",
                        row["title"],
                        row["content"],
                        row["excerpt"] or "",
                        row["document_title"] or "",
                    ),
                )

    def _rebuild_fts(self, generation: str) -> None:
        if not self._fts_available:
            return
        with self._connect() as conn:
            conn.execute("DELETE FROM mn4_objects_fts")
            conn.execute(
                """INSERT INTO mn4_objects_fts
                   (doc, title, content, excerpt, document_title)
                   SELECT generation_id || ':' || object_id, title, content,
                          COALESCE(excerpt, ''), COALESCE(document_title, '')
                   FROM mn4_objects WHERE generation_id=?""",
                (generation,),
            )

    def ingest(self, batch: SyncBatch) -> SyncResult:
        """Apply an idempotent incremental batch and advance the server cursor."""
        if not batch.batch_id:
            raise ValueError("batch_id is required")
        deleted_objects = list(batch.deleted_objects)
        if batch.deleted_ids:
            deleted_objects.extend(
                DeletedMarginNoteObject(object_id=object_id) for object_id in batch.deleted_ids
            )
        changed_ids: list[str] = []
        with self._connect() as conn:
            previous = conn.execute(
                "SELECT response_json FROM mn4_sync_batches WHERE device_id=? AND batch_id=?",
                (batch.device_id, batch.batch_id),
            ).fetchone()
            if previous:
                result = SyncResult(**json.loads(previous["response_json"]))
                result.duplicate = True
                return result

            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT generation_id, cursor FROM mn4_live_state WHERE id=1"
            ).fetchone()
            if row is None:
                generation = self._live_generation(conn)
                server_cursor = ""
            else:
                generation = row["generation_id"]
                server_cursor = row["cursor"]
            if batch.cursor != server_cursor:
                raise MarginNoteSyncConflict(server_cursor)

            counts = {"stored": 0, "updated": 0, "skipped": 0}
            for obj in batch.objects:
                obj.device_id = batch.device_id
                outcome = self._upsert_object(conn, generation, obj)
                counts[outcome] += 1
                if outcome != "skipped":
                    changed_ids.append(obj.object_id)

            deleted = 0
            for deleted_object in deleted_objects:
                existed = self._delete_object(
                    conn,
                    generation,
                    deleted_object.object_id,
                    batch.device_id,
                    deleted_object.updated_at,
                )
                if existed:
                    deleted += 1
                    changed_ids.append(deleted_object.object_id)

            cursor = _new_cursor()
            result = SyncResult(
                stored=counts["stored"],
                updated=counts["updated"],
                deleted=deleted,
                skipped=counts["skipped"],
                new_cursor=cursor,
            )
            conn.execute(
                """INSERT INTO mn4_sync_batches
                   (device_id, batch_id, cursor, response_json, received_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    batch.device_id,
                    batch.batch_id,
                    batch.cursor,
                    json.dumps(asdict(result)),
                    _now_iso(),
                ),
            )
            conn.execute(
                "INSERT OR REPLACE INTO mn4_device_cursors (device_id, cursor) VALUES (?, ?)",
                (batch.device_id, cursor),
            )
            conn.execute(
                "UPDATE mn4_live_state SET cursor=?, updated_at=? WHERE id=1",
                (cursor, _now_iso()),
            )
        self._update_fts_docs(generation, changed_ids)
        return result

    def get_cursor(self, device_id: str) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT cursor FROM mn4_device_cursors WHERE device_id=?",
                (device_id,),
            ).fetchone()
        return row["cursor"] if row else ""

    def create_snapshot(self, *, device_id: str, total_batches: int) -> dict[str, Any]:
        if not 1 <= total_batches <= 100_000:
            raise ValueError("total_batches must be between 1 and 100000")
        token = uuid.uuid4().hex
        snapshot_id = f"snap_{token[:20]}"
        generation = f"gen_{token}"
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO mn4_snapshots
                   (snapshot_id, generation_id, device_id, total_batches,
                    next_sequence, state, created_at)
                   VALUES (?, ?, ?, ?, 1, 'staging', ?)""",
                (snapshot_id, generation, device_id, total_batches, now),
            )
        return {
            "snapshot_id": snapshot_id,
            "total_batches": total_batches,
            "next_sequence": 1,
            "state": "staging",
        }

    def append_snapshot(
        self,
        snapshot_id: str,
        *,
        sequence: int,
        batch_id: str,
        objects: list[MarginNoteObject],
    ) -> dict[str, Any]:
        if not batch_id:
            raise ValueError("batch_id is required")
        with self._connect() as conn:
            snapshot = self._snapshot_or_404(conn, snapshot_id)
            if snapshot["state"] != "staging":
                raise ValueError("Snapshot is not staging")
            existing = conn.execute(
                """SELECT batch_id, response_json FROM mn4_snapshot_batches
                   WHERE snapshot_id=? AND sequence=?""",
                (snapshot_id, sequence),
            ).fetchone()
            if existing:
                if existing["batch_id"] != batch_id:
                    raise MarginNoteSyncConflict(self.server_cursor())
                return {**json.loads(existing["response_json"]), "duplicate": True}
            if sequence != int(snapshot["next_sequence"]):
                raise MarginNoteSyncConflict(self.server_cursor())
            if len(objects) > 250:
                raise ValueError("A snapshot batch may contain at most 250 objects")

            conn.execute("BEGIN IMMEDIATE")
            counts = {"stored": 0, "updated": 0, "skipped": 0}
            for obj in objects:
                obj.device_id = snapshot["device_id"]
                outcome = self._upsert_object(conn, snapshot["generation_id"], obj)
                counts[outcome] += 1
            response = {
                "stored": counts["stored"],
                "updated": counts["updated"],
                "skipped": counts["skipped"],
                "next_sequence": sequence + 1,
                "duplicate": False,
            }
            conn.execute(
                """INSERT INTO mn4_snapshot_batches
                   (snapshot_id, sequence, batch_id, response_json, received_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (snapshot_id, sequence, batch_id, json.dumps(response), _now_iso()),
            )
            conn.execute(
                "UPDATE mn4_snapshots SET next_sequence=? WHERE snapshot_id=?",
                (sequence + 1, snapshot_id),
            )
        return response

    def commit_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            snapshot = self._snapshot_or_404(conn, snapshot_id)
            if snapshot["state"] == "committed":
                return {
                    "snapshot_id": snapshot_id,
                    "state": "committed",
                    "object_count": self.count(),
                    "cursor": self.server_cursor(),
                    "duplicate": True,
                }
            if snapshot["state"] != "staging":
                raise ValueError("Snapshot is not staging")
            expected = int(snapshot["total_batches"]) + 1
            if int(snapshot["next_sequence"]) != expected:
                raise ValueError(
                    f"Snapshot expects sequence {int(snapshot['next_sequence'])}, "
                    f"not commit before all {snapshot['total_batches']} batches"
                )
            conn.execute("BEGIN IMMEDIATE")
            cursor = _new_cursor()
            conn.execute(
                """UPDATE mn4_live_state
                   SET generation_id=?, cursor=?, updated_at=?
                   WHERE id=1""",
                (snapshot["generation_id"], cursor, _now_iso()),
            )
            conn.execute(
                "INSERT OR REPLACE INTO mn4_device_cursors (device_id, cursor) VALUES (?, ?)",
                (snapshot["device_id"], cursor),
            )
            conn.execute(
                """UPDATE mn4_snapshots SET state='committed', committed_at=?
                   WHERE snapshot_id=?""",
                (_now_iso(), snapshot_id),
            )
            old_generations = conn.execute(
                """SELECT DISTINCT generation_id FROM mn4_objects
                   WHERE generation_id != ?""",
                (snapshot["generation_id"],),
            ).fetchall()
            for row in old_generations:
                conn.execute(
                    "DELETE FROM mn4_objects WHERE generation_id=?",
                    (row["generation_id"],),
                )
                conn.execute(
                    "DELETE FROM mn4_tombstones WHERE generation_id=?",
                    (row["generation_id"],),
                )
        self._rebuild_fts(snapshot["generation_id"])
        return {
            "snapshot_id": snapshot_id,
            "state": "committed",
            "object_count": self.count(),
            "cursor": self.server_cursor(),
            "duplicate": False,
        }

    @staticmethod
    def _snapshot_or_404(conn: sqlite3.Connection, snapshot_id: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM mn4_snapshots WHERE snapshot_id=?",
            (snapshot_id,),
        ).fetchone()
        if row is None:
            raise KeyError("Snapshot not found")
        return row

    def get(self, object_id: str) -> MarginNoteObject | None:
        with self._connect() as conn:
            generation = self._live_generation(conn)
            row = conn.execute(
                "SELECT * FROM mn4_objects WHERE generation_id=? AND object_id=?",
                (generation, object_id),
            ).fetchone()
        return self._row_to_object(row) if row else None

    def search(
        self,
        query: str,
        *,
        object_type: str = "",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        query = (query or "").strip()
        if not query:
            return []
        with self._connect() as conn:
            generation = self._live_generation(conn)
            if self._fts_available:
                phrase = '"' + query.replace('"', '""') + '"'
                docs = conn.execute(
                    """SELECT doc FROM mn4_objects_fts
                       WHERE mn4_objects_fts MATCH ?
                       ORDER BY rank LIMIT ?""",
                    (phrase, max(limit * 3, 60)),
                ).fetchall()
                ids = [row["doc"].rsplit(":", 1)[-1] for row in docs]
                if ids:
                    placeholders = ",".join("?" for _ in ids)
                    rows = conn.execute(
                        f"""SELECT * FROM mn4_objects
                            WHERE generation_id=? AND object_id IN ({placeholders})
                            ORDER BY updated_at DESC""",
                        (generation, *ids),
                    ).fetchall()
                else:
                    rows = []
            else:
                needle = f"%{query.lower()}%"
                rows = conn.execute(
                    """SELECT * FROM mn4_objects WHERE generation_id=?
                       AND (LOWER(title) LIKE ? OR LOWER(content) LIKE ?
                            OR LOWER(COALESCE(excerpt,'')) LIKE ?
                            OR LOWER(COALESCE(document_title,'')) LIKE ?)
                       ORDER BY updated_at DESC LIMIT ?""",
                    (generation, needle, needle, needle, needle, limit),
                ).fetchall()
        objects = [self._row_to_object(row) for row in rows]
        if object_type:
            objects = [obj for obj in objects if obj.object_type == object_type]
        return [_to_summary(obj, query) for obj in objects[:limit]]

    def list_objects(
        self,
        *,
        object_type: str = "",
        document_id: str = "",
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM mn4_objects WHERE generation_id=?"
        params: list[Any] = []
        if object_type:
            sql += " AND object_type=?"
            params.append(object_type)
        if document_id:
            sql += " AND document_id=?"
            params.append(document_id)
        sql += " ORDER BY COALESCE(document_title,title), updated_at DESC LIMIT ? OFFSET ?"
        params.extend((limit, offset))
        with self._connect() as conn:
            generation = self._live_generation(conn)
            rows = conn.execute(sql, (generation, *params)).fetchall()
        return [_to_summary(self._row_to_object(row), "") for row in rows]

    def list_documents(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            generation = self._live_generation(conn)
            rows = conn.execute(
                """SELECT document_id, document_title, COUNT(*) AS n
                   FROM mn4_objects
                   WHERE generation_id=? AND document_id IS NOT NULL
                   GROUP BY document_id, document_title
                   ORDER BY document_title""",
                (generation,),
            ).fetchall()
        return [
            {
                "document_id": row["document_id"],
                "title": row["document_title"] or "(untitled)",
                "count": int(row["n"]),
            }
            for row in rows
        ]

    def linked_objects(self, object_id: str) -> list[dict[str, Any]]:
        obj = self.get(object_id)
        if obj is None:
            return []
        linked_ids = set(obj.links)
        with self._connect() as conn:
            generation = self._live_generation(conn)
            rows = conn.execute(
                "SELECT object_id, links FROM mn4_objects WHERE generation_id=?",
                (generation,),
            ).fetchall()
        for row in rows:
            if object_id in set(json.loads(row["links"])):
                linked_ids.add(row["object_id"])
        results = []
        for linked_id in linked_ids:
            linked = self.get(linked_id)
            if linked:
                results.append(_to_summary(linked, ""))
        return results

    def collect_tags(self, *, limit: int = 200) -> list[dict[str, Any]]:
        with self._connect() as conn:
            generation = self._live_generation(conn)
            rows = conn.execute(
                "SELECT tags FROM mn4_objects WHERE generation_id=?",
                (generation,),
            ).fetchall()
        counts: dict[str, int] = {}
        for row in rows:
            for tag in json.loads(row["tags"]):
                tag = tag.strip()
                if tag:
                    counts[tag] = counts.get(tag, 0) + 1
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        return [{"tag": tag, "count": count} for tag, count in ranked[:limit]]

    def count(self) -> int:
        with self._connect() as conn:
            generation = self._live_generation(conn)
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM mn4_objects WHERE generation_id=?",
                (generation,),
            ).fetchone()
        return int(row["n"])

    def check_integrity(self) -> bool:
        with self._connect() as conn:
            row = conn.execute("PRAGMA quick_check").fetchone()
        return bool(row and row[0].lower() == "ok")

    def reset_for_resync(self) -> None:
        """Drop synced generations after integrity failure and prepare a fresh live set."""
        generation = f"gen_{uuid.uuid4().hex}"
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM mn4_objects")
            conn.execute("DELETE FROM mn4_tombstones")
            conn.execute("DELETE FROM mn4_snapshots")
            conn.execute("DELETE FROM mn4_snapshot_batches")
            conn.execute(
                """INSERT OR REPLACE INTO mn4_live_state
                   (id, generation_id, cursor, updated_at) VALUES (1, ?, ?, ?)""",
                (generation, _new_cursor(), _now_iso()),
            )
        self._rebuild_fts(generation)


def _to_summary(obj: MarginNoteObject, query: str) -> dict[str, Any]:
    body = obj.content or obj.excerpt or ""
    return {
        "object_id": obj.object_id,
        "object_type": obj.object_type,
        "title": obj.title,
        "document_id": obj.document_id,
        "document_title": obj.document_title,
        "page": obj.page,
        "tags": obj.tags,
        "snippet": _snippet(body, query),
        "revision": obj.revision,
        "updated_at": obj.updated_at,
        "locator": _locator(obj),
    }


def _locator(obj: MarginNoteObject) -> str:
    source = obj.document_title or obj.document_id or "MarginNote library"
    return f"{source}:{obj.object_id}" + (f":p{obj.page}" if obj.page is not None else "")


def _snippet(body: str, query: str, width: int = 160) -> str:
    if not body:
        return ""
    if not query:
        return body[:width].strip().replace("\n", " ")
    lowered = body.lower()
    idx = lowered.find(query.lower())
    if idx < 0:
        return body[:width].strip().replace("\n", " ")
    start = max(0, idx - width // 3)
    tail = "..." if start + width < len(body) else ""
    return ("..." if start else "") + body[start : start + width].strip().replace("\n", " ") + tail


__all__ = ["MarginNoteStore"]
