"""SQLite storage for MarginNote 4 bridge objects and writeback jobs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
from pathlib import Path
import secrets
import sqlite3
from typing import Any

from deeptutor.capabilities.marginnote4.models import (
    ALL_TYPES,
    MarginNoteObject,
    PairedDevice,
    PairingCode,
    SyncBatch,
    SyncResult,
    WritebackPayload,
)

logger = logging.getLogger(__name__)
DEFAULT_PAIRING_TTL_SECONDS = 600
DEFAULT_LEASE_TTL_SECONDS = 120
MAX_DELETION_RATIO = 0.25


class MarginNoteStoreError(Exception):
    """Base class for deterministic store failures."""


class PairingError(MarginNoteStoreError):
    pass


class SyncConflict(MarginNoteStoreError):
    pass


class BulkDeleteGuard(MarginNoteStoreError):
    pass


class WritebackStateError(MarginNoteStoreError):
    pass


_SCHEMA = """
CREATE TABLE IF NOT EXISTS mn4_pairing_codes (
    code_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    kb_id TEXT NOT NULL,
    kb_name TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS mn4_devices (
    device_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    kb_id TEXT NOT NULL,
    kb_name TEXT NOT NULL,
    device_name TEXT NOT NULL DEFAULT '',
    device_kind TEXT NOT NULL DEFAULT 'macos',
    token_hash TEXT NOT NULL,
    paired_at TEXT NOT NULL DEFAULT '',
    last_seen TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    automation_verified INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS mn4_objects (
    object_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
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
    object_hash TEXT NOT NULL DEFAULT '',
    raw TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (object_id, device_id)
);
CREATE INDEX IF NOT EXISTS idx_mn4_type ON mn4_objects (object_type);
CREATE INDEX IF NOT EXISTS idx_mn4_doc ON mn4_objects (document_id);
CREATE INDEX IF NOT EXISTS idx_mn4_search ON mn4_objects (title);

CREATE TABLE IF NOT EXISTS mn4_cursors (
    device_id TEXT PRIMARY KEY,
    sequence INTEGER NOT NULL DEFAULT 0,
    snapshot_hash TEXT NOT NULL DEFAULT '',
    cursor TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS mn4_tombstones (
    object_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    deleted_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (object_id, device_id)
);

CREATE TABLE IF NOT EXISTS mn4_sync_batches (
    sync_id TEXT PRIMARY KEY,
    device_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    snapshot_hash TEXT NOT NULL,
    result_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mn4_writebacks (
    writeback_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    kb_id TEXT NOT NULL,
    status TEXT NOT NULL,
    title TEXT NOT NULL,
    markdown TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '[]',
    source_refs TEXT NOT NULL DEFAULT '[]',
    target_notebook TEXT NOT NULL DEFAULT '',
    payload_hash TEXT NOT NULL,
    delivery_mode TEXT NOT NULL DEFAULT 'import_queue',
    provider TEXT NOT NULL DEFAULT '',
    external_id TEXT NOT NULL DEFAULT '',
    attempts INTEGER NOT NULL DEFAULT 0,
    lease_token TEXT NOT NULL DEFAULT '',
    lease_expires_at TEXT NOT NULL DEFAULT '',
    last_error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    completed_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_mn4_writeback_status ON mn4_writebacks (status);
CREATE INDEX IF NOT EXISTS idx_mn4_writeback_user ON mn4_writebacks (user_id, kb_id);

CREATE TABLE IF NOT EXISTS mn4_automation_verifications (
    device_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    bundle_id TEXT NOT NULL,
    app_version TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    verified_at TEXT NOT NULL,
    test_external_id TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (device_id, provider)
);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_token(token: str) -> str:
    return _hash(token)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def object_hash(obj: MarginNoteObject) -> str:
    payload = obj.to_dict()
    payload.pop("synced_at", None)
    payload.pop("device_id", None)
    payload["object_hash"] = ""
    return _hash(_canonical_json(payload))


def payload_hash(payload: WritebackPayload) -> str:
    return _hash(_canonical_json(payload.canonical()))


def _default_db_path(kb_name: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in kb_name)
    if not safe:
        raise ValueError("KB name is required for a MarginNote 4 store")
    from deeptutor.services.path_service import get_path_service

    return get_path_service().user_data_dir / "marginnote4" / f"{safe}.db"


class MarginNoteStore:
    """Sequential-safe store for one MarginNote 4 KB."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            self._migrate(conn)

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        # Databases created by the exploratory branch may lack ownership columns.
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(mn4_devices)")}
        additions = {
            "user_id": "TEXT NOT NULL DEFAULT 'local-admin'",
            "kb_id": "TEXT NOT NULL DEFAULT ''",
            "kb_name": "TEXT NOT NULL DEFAULT ''",
            "automation_verified": "INTEGER NOT NULL DEFAULT 0",
        }
        for name, definition in additions.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE mn4_devices ADD COLUMN {name} {definition}")

    # -- pairing ------------------------------------------------------------

    def create_pairing_code(
        self,
        *,
        user_id: str,
        kb_id: str,
        kb_name: str,
        ttl_seconds: int = DEFAULT_PAIRING_TTL_SECONDS,
    ) -> PairingCode:
        code = "mn4-" + secrets.token_urlsafe(24)
        now = _now()
        expires = now + timedelta(seconds=max(30, int(ttl_seconds)))
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO mn4_pairing_codes
                   (code_hash, user_id, kb_id, kb_name, expires_at, created_at, used)
                   VALUES (?, ?, ?, ?, ?, ?, 0)""",
                (_hash(code), user_id, kb_id, kb_name, _iso(expires), _iso(now)),
            )
        return PairingCode(code, user_id, kb_id, kb_name, _iso(expires))

    def pair_device(
        self,
        code: str = "",
        *,
        device_name: str = "",
        device_kind: str = "macos",
        direct_user_id: str = "local-admin",
        direct_kb_id: str = "default",
        direct_kb_name: str = "default",
    ) -> tuple[PairedDevice, str]:
        """Pair with a one-time code. Direct pairing is test/legacy only."""
        now = _iso()
        if code:
            code_hash = _hash(code.strip())
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM mn4_pairing_codes WHERE code_hash = ?", (code_hash,)
                ).fetchone()
                if row is None or bool(row["used"]):
                    raise PairingError("Pairing code is invalid or already used.")
                if _parse_iso(row["expires_at"]) <= _now():
                    raise PairingError("Pairing code has expired.")
                claimed = conn.execute(
                    """UPDATE mn4_pairing_codes SET used = 1
                       WHERE code_hash = ? AND used = 0""",
                    (code_hash,),
                )
                if claimed.rowcount != 1:
                    raise PairingError("Pairing code was already used.")
                user_id = row["user_id"]
                kb_id = row["kb_id"]
                kb_name = row["kb_name"]
        else:
            user_id, kb_id, kb_name = direct_user_id, direct_kb_id, direct_kb_name

        device_id = "mn4dev-" + secrets.token_urlsafe(12)
        token = secrets.token_urlsafe(32)
        device = PairedDevice(
            device_id=device_id,
            user_id=user_id,
            kb_id=kb_id,
            kb_name=kb_name,
            device_name=device_name,
            device_kind=device_kind,
            paired_at=now,
            last_seen=now,
        )
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO mn4_devices
                   (device_id, user_id, kb_id, kb_name, device_name, device_kind,
                    token_hash, paired_at, last_seen, active, automation_verified)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0)""",
                (
                    device_id,
                    user_id,
                    kb_id,
                    kb_name,
                    device_name,
                    device_kind,
                    _hash_token(token),
                    now,
                    now,
                ),
            )
            conn.execute(
                """INSERT INTO mn4_cursors
                   (device_id, sequence, snapshot_hash, cursor) VALUES (?, 0, '', '')""",
                (device_id,),
            )
        return device, token

    def verify_token(
        self,
        device_id: str,
        token: str,
        *,
        user_id: str = "",
        kb_id: str = "",
    ) -> bool:
        identity = self.device_identity(device_id)
        if identity is None or not identity["active"]:
            return False
        if user_id and identity["user_id"] != user_id:
            return False
        if kb_id and identity["kb_id"] != kb_id:
            return False
        return secrets.compare_digest(str(identity["token_hash"]), _hash_token(token))

    def device_identity(self, device_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM mn4_devices WHERE device_id = ?", (device_id,)
            ).fetchone()
        return dict(row) if row else None

    def install_device(
        self,
        *,
        device_id: str,
        user_id: str,
        kb_id: str,
        kb_name: str,
        device_name: str,
        device_kind: str,
        token: str,
        paired_at: str = "",
    ) -> None:
        """Install a device paired by the router's global registry."""
        now = paired_at or _iso()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO mn4_devices
                   (device_id, user_id, kb_id, kb_name, device_name, device_kind,
                    token_hash, paired_at, last_seen, active, automation_verified)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0)
                   ON CONFLICT(device_id) DO UPDATE SET
                     active=1, token_hash=excluded.token_hash,
                     user_id=excluded.user_id, kb_id=excluded.kb_id,
                     kb_name=excluded.kb_name""",
                (
                    device_id,
                    user_id,
                    kb_id,
                    kb_name,
                    device_name,
                    device_kind,
                    _hash_token(token),
                    now,
                    now,
                ),
            )
            conn.execute(
                """INSERT OR IGNORE INTO mn4_cursors
                   (device_id, sequence, snapshot_hash, cursor) VALUES (?, 0, '', '')""",
                (device_id,),
            )

    def revoke_device(self, device_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE mn4_devices SET active = 0 WHERE device_id = ? AND active = 1",
                (device_id,),
            )
            return cur.rowcount > 0

    def list_devices(
        self, *, user_id: str = "", kb_id: str = "", include_inactive: bool = False
    ) -> list[PairedDevice]:
        sql = "SELECT * FROM mn4_devices WHERE 1=1"
        params: list[Any] = []
        if user_id:
            sql += " AND user_id = ?"
            params.append(user_id)
        if kb_id:
            sql += " AND kb_id = ?"
            params.append(kb_id)
        if not include_inactive:
            sql += " AND active = 1"
        sql += " ORDER BY paired_at"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_device(row) for row in rows]

    def touch_device(self, device_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE mn4_devices SET last_seen = ? WHERE device_id = ?",
                (_iso(), device_id),
            )

    # -- ingest -------------------------------------------------------------

    def ingest(self, batch: SyncBatch) -> SyncResult:
        now = _iso()
        stored = updated = deleted = skipped = 0
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT result_json FROM mn4_sync_batches WHERE sync_id = ?",
                (batch.sync_id,),
            ).fetchone()
            if existing:
                return SyncResult(**json.loads(existing["result_json"]))

            cursor_row = conn.execute(
                "SELECT sequence, snapshot_hash, cursor FROM mn4_cursors WHERE device_id = ?",
                (batch.device_id,),
            ).fetchone()
            current_sequence = int(cursor_row["sequence"]) if cursor_row else 0
            current_cursor = str(cursor_row["cursor"]) if cursor_row else ""
            if not batch.sync_id:
                # Store-level callers used the pre-protocol shape; HTTP always
                # supplies a durable sync_id.
                batch.sync_id = "legacy-" + secrets.token_urlsafe(12)
            if batch.sequence <= 0:
                batch.sequence = current_sequence + 1
            if not batch.base_cursor:
                batch.base_cursor = current_cursor
            if batch.sequence <= current_sequence:
                raise SyncConflict(
                    f"Stale sequence {batch.sequence}; server expects > {current_sequence}"
                )
            if current_cursor and batch.base_cursor != current_cursor:
                raise SyncConflict("Batch base cursor does not match the device cursor")

            device_count = int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM mn4_objects WHERE device_id = ?",
                    (batch.device_id,),
                ).fetchone()["n"]
            )
            if device_count and len(batch.deleted_ids) > device_count * MAX_DELETION_RATIO:
                raise BulkDeleteGuard("Refusing a deletion batch above the 25% safety threshold")

            for obj in batch.objects:
                if obj.object_type not in ALL_TYPES:
                    logger.warning("Skipping unknown MN4 type: %s", obj.object_type)
                    skipped += 1
                    continue
                obj.device_id = batch.device_id
                obj.synced_at = obj.synced_at or now
                obj.object_hash = object_hash(obj)
                prev = conn.execute(
                    """SELECT object_hash FROM mn4_objects
                       WHERE object_id = ? AND device_id = ?""",
                    (obj.object_id, batch.device_id),
                ).fetchone()
                if prev and secrets.compare_digest(prev["object_hash"], obj.object_hash):
                    skipped += 1
                    continue
                conn.execute(
                    """INSERT INTO mn4_objects
                       (object_id, device_id, object_type, title, content, excerpt,
                        document_id, document_title, page, tags, links, color,
                        created_at, updated_at, synced_at, object_hash, raw)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(object_id, device_id) DO UPDATE SET
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
                         object_hash=excluded.object_hash,
                         raw=excluded.raw""",
                    _object_params(obj),
                )
                if prev:
                    updated += 1
                else:
                    stored += 1

            for object_id in batch.deleted_ids:
                changed = conn.execute(
                    """DELETE FROM mn4_objects
                       WHERE object_id = ? AND device_id = ?""",
                    (object_id, batch.device_id),
                ).rowcount
                if changed:
                    conn.execute(
                        """INSERT OR REPLACE INTO mn4_tombstones
                           (object_id, device_id, deleted_at) VALUES (?, ?, ?)""",
                        (object_id, batch.device_id, now),
                    )
                    deleted += 1

            new_cursor = f"{batch.sequence}:{batch.snapshot_hash}"
            conn.execute(
                """INSERT INTO mn4_cursors
                   (device_id, sequence, snapshot_hash, cursor)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(device_id) DO UPDATE SET
                     sequence=excluded.sequence,
                     snapshot_hash=excluded.snapshot_hash,
                     cursor=excluded.cursor""",
                (batch.device_id, batch.sequence, batch.snapshot_hash, new_cursor),
            )
            result = SyncResult(
                stored=stored,
                updated=updated,
                deleted=deleted,
                skipped=skipped,
                new_cursor=new_cursor,
            )
            conn.execute(
                """INSERT INTO mn4_sync_batches
                   (sync_id, device_id, sequence, snapshot_hash, result_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    batch.sync_id,
                    batch.device_id,
                    batch.sequence,
                    batch.snapshot_hash,
                    _canonical_json(result.to_dict()),
                ),
            )
        return result

    def get_cursor(self, device_id: str) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT cursor FROM mn4_cursors WHERE device_id = ?", (device_id,)
            ).fetchone()
        return str(row["cursor"]) if row else ""

    # -- read ----------------------------------------------------------------

    def get(self, object_id: str, *, device_id: str = "") -> MarginNoteObject | None:
        with self._connect() as conn:
            if device_id:
                row = conn.execute(
                    "SELECT * FROM mn4_objects WHERE object_id = ? AND device_id = ?",
                    (object_id, device_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM mn4_objects WHERE object_id = ? LIMIT 1", (object_id,)
                ).fetchone()
        return _row_to_object(row) if row else None

    def search(
        self,
        query: str,
        *,
        object_type: str = "",
        device_id: str = "",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        query = (query or "").strip()
        if not query:
            return []
        needle = f"%{query.lower()}%"
        sql = """SELECT * FROM mn4_objects
                 WHERE (LOWER(title) LIKE ? OR LOWER(content) LIKE ?
                    OR LOWER(COALESCE(excerpt, '')) LIKE ?
                    OR LOWER(COALESCE(document_title, '')) LIKE ?)"""
        params: list[Any] = [needle, needle, needle, needle]
        if object_type:
            sql += " AND object_type = ?"
            params.append(object_type)
        if device_id:
            sql += " AND device_id = ?"
            params.append(device_id)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_to_summary(_row_to_object(row), query) for row in rows]

    def list_objects(
        self,
        *,
        object_type: str = "",
        document_id: str = "",
        device_id: str = "",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM mn4_objects WHERE 1=1"
        params: list[Any] = []
        if object_type:
            sql += " AND object_type = ?"
            params.append(object_type)
        if document_id:
            sql += " AND document_id = ?"
            params.append(document_id)
        if device_id:
            sql += " AND device_id = ?"
            params.append(device_id)
        sql += " ORDER BY COALESCE(document_title, title), updated_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_to_summary(_row_to_object(row), "") for row in rows]

    def list_documents(self, *, device_id: str = "") -> list[dict[str, Any]]:
        sql = """SELECT document_id, document_title, COUNT(*) AS n
                 FROM mn4_objects WHERE document_id IS NOT NULL"""
        params: list[Any] = []
        if device_id:
            sql += " AND device_id = ?"
            params.append(device_id)
        sql += " GROUP BY document_id, document_title ORDER BY document_title"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            {
                "document_id": row["document_id"],
                "title": row["document_title"] or "(untitled)",
                "count": int(row["n"]),
            }
            for row in rows
        ]

    def linked_objects(self, object_id: str, *, device_id: str = "") -> list[dict[str, Any]]:
        obj = self.get(object_id, device_id=device_id)
        if obj is None:
            return []
        linked_ids = set(obj.links)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT object_id FROM mn4_objects WHERE links LIKE ?",
                (f'%"{object_id}"%',),
            ).fetchall()
        linked_ids.update(row["object_id"] for row in rows)
        results = []
        for linked_id in linked_ids:
            linked = self.get(linked_id, device_id=device_id)
            if linked:
                results.append(_to_summary(linked, ""))
        return results

    def collect_tags(self, *, device_id: str = "", limit: int = 200) -> list[dict[str, Any]]:
        with self._connect() as conn:
            sql = "SELECT tags FROM mn4_objects"
            params: list[Any] = []
            if device_id:
                sql += " WHERE device_id = ?"
                params.append(device_id)
            rows = conn.execute(sql, params).fetchall()
        counts: dict[str, int] = {}
        for row in rows:
            for tag in json.loads(row["tags"]):
                tag = tag.strip()
                if tag:
                    counts[tag] = counts.get(tag, 0) + 1
        ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        return [{"tag": tag, "count": count} for tag, count in ranked[:limit]]

    def count(self, *, device_id: str = "") -> int:
        with self._connect() as conn:
            if device_id:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM mn4_objects WHERE device_id = ?",
                    (device_id,),
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) AS n FROM mn4_objects").fetchone()
        return int(row["n"])

    # -- writebacks -----------------------------------------------------------

    def create_writeback(
        self,
        *,
        user_id: str,
        kb_id: str,
        payload: WritebackPayload,
    ) -> dict[str, Any]:
        if not payload.title.strip() or not payload.markdown.strip():
            raise WritebackStateError("Writeback title and markdown are required")
        digest = payload_hash(payload)
        now = _iso()
        writeback_id = "mn4wb-" + secrets.token_urlsafe(12)
        with self._connect() as conn:
            existing = conn.execute(
                """SELECT * FROM mn4_writebacks
                   WHERE user_id = ? AND kb_id = ? AND payload_hash = ?
                     AND status NOT IN ('rejected', 'failed', 'conflicted')""",
                (user_id, kb_id, digest),
            ).fetchone()
            if existing:
                return _writeback_dict(existing)
            conn.execute(
                """INSERT INTO mn4_writebacks
                   (writeback_id, user_id, kb_id, status, title, markdown, tags,
                    source_refs, target_notebook, payload_hash, created_at, updated_at)
                   VALUES (?, ?, ?, 'pending_confirmation', ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    writeback_id,
                    user_id,
                    kb_id,
                    payload.title,
                    payload.markdown,
                    _canonical_json(payload.tags),
                    _canonical_json(payload.source_refs),
                    payload.target_notebook,
                    digest,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM mn4_writebacks WHERE writeback_id = ?", (writeback_id,)
            ).fetchone()
        return _writeback_dict(row)

    def list_writebacks(
        self, *, user_id: str, kb_id: str = "", status: str = ""
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM mn4_writebacks WHERE user_id = ?"
        params: list[Any] = [user_id]
        if kb_id:
            sql += " AND kb_id = ?"
            params.append(kb_id)
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_writeback_dict(row) for row in rows]

    def _owned_writeback(
        self, conn: sqlite3.Connection, writeback_id: str, *, user_id: str
    ) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM mn4_writebacks WHERE writeback_id = ?", (writeback_id,)
        ).fetchone()
        if row is None or row["user_id"] != user_id:
            raise WritebackStateError("Writeback not found")
        return row

    def approve_writeback(self, writeback_id: str, *, user_id: str) -> dict[str, Any]:
        return self._transition(
            writeback_id,
            user_id=user_id,
            expected=("pending_confirmation", "failed", "conflicted"),
            status="approved",
            clear_failure=True,
        )

    def reject_writeback(self, writeback_id: str, *, user_id: str) -> dict[str, Any]:
        return self._transition(
            writeback_id,
            user_id=user_id,
            expected=("pending_confirmation", "approved", "failed", "conflicted"),
            status="rejected",
        )

    def mark_imported(self, writeback_id: str, *, user_id: str) -> dict[str, Any]:
        return self._transition(
            writeback_id,
            user_id=user_id,
            expected=("awaiting_import",),
            status="imported",
        )

    def _transition(
        self,
        writeback_id: str,
        *,
        user_id: str,
        expected: tuple[str, ...],
        status: str,
        clear_failure: bool = False,
    ) -> dict[str, Any]:
        now = _iso()
        with self._connect() as conn:
            row = self._owned_writeback(conn, writeback_id, user_id=user_id)
            if row["status"] not in expected:
                raise WritebackStateError(f"Cannot move {row['status']} to {status}")
            conn.execute(
                """UPDATE mn4_writebacks
                   SET status = ?, updated_at = ?,
                       lease_token = '', lease_expires_at = '',
                       last_error = CASE WHEN ? THEN '' ELSE last_error END
                   WHERE writeback_id = ?""",
                (status, now, clear_failure, writeback_id),
            )
            updated = conn.execute(
                "SELECT * FROM mn4_writebacks WHERE writeback_id = ?", (writeback_id,)
            ).fetchone()
        return _writeback_dict(updated)

    def claim_writeback(
        self,
        *,
        device_id: str,
        lease_ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
    ) -> dict[str, Any] | None:
        identity = self.device_identity(device_id)
        if identity is None or not identity["active"]:
            raise WritebackStateError("Unknown or inactive device")
        now_dt = _now()
        lease_token = secrets.token_urlsafe(24)
        expires = _iso(now_dt + timedelta(seconds=max(15, lease_ttl_seconds)))
        with self._connect() as conn:
            conn.execute(
                """UPDATE mn4_writebacks
                   SET status = 'approved', lease_token = '', lease_expires_at = ''
                   WHERE status = 'leased' AND lease_expires_at != ''
                     AND lease_expires_at <= ?""",
                (_iso(),),
            )
            row = conn.execute(
                """SELECT * FROM mn4_writebacks
                   WHERE user_id = ? AND kb_id = ? AND status = 'approved'
                   ORDER BY created_at LIMIT 1""",
                (identity["user_id"], identity["kb_id"]),
            ).fetchone()
            if row is None:
                return None
            mode = "automation" if bool(identity["automation_verified"]) else "import_queue"
            conn.execute(
                """UPDATE mn4_writebacks
                   SET status = 'leased', delivery_mode = ?, attempts = attempts + 1,
                       lease_token = ?, lease_expires_at = ?, updated_at = ?
                   WHERE writeback_id = ?""",
                (mode, lease_token, expires, _iso(), row["writeback_id"]),
            )
            claimed = conn.execute(
                "SELECT * FROM mn4_writebacks WHERE writeback_id = ?",
                (row["writeback_id"],),
            ).fetchone()
        result = _writeback_dict(claimed)
        result["lease"] = {
            "token": lease_token,
            "expires_at": expires,
            "ttl_seconds": max(15, lease_ttl_seconds),
        }
        return result

    def renew_writeback(
        self, writeback_id: str, *, device_id: str, lease_token: str, ttl_seconds: int = 60
    ) -> dict[str, Any]:
        expires = _iso(_now() + timedelta(seconds=max(15, ttl_seconds)))
        with self._connect() as conn:
            row = self._require_lease(conn, writeback_id, device_id, lease_token)
            conn.execute(
                """UPDATE mn4_writebacks SET lease_expires_at = ?, updated_at = ?
                   WHERE writeback_id = ?""",
                (expires, _iso(), row["writeback_id"]),
            )
        return {"writeback_id": writeback_id, "lease_expires_at": expires}

    def _require_lease(
        self,
        conn: sqlite3.Connection,
        writeback_id: str,
        device_id: str,
        lease_token: str,
    ) -> sqlite3.Row:
        identity = self.device_identity(device_id)
        if identity is None:
            raise WritebackStateError("Unknown device")
        row = conn.execute(
            "SELECT * FROM mn4_writebacks WHERE writeback_id = ?", (writeback_id,)
        ).fetchone()
        if (
            row is None
            or row["user_id"] != identity["user_id"]
            or row["kb_id"] != identity["kb_id"]
            or row["status"] != "leased"
            or row["lease_token"] != lease_token
        ):
            raise WritebackStateError("Invalid writeback lease")
        if row["lease_expires_at"] and _parse_iso(row["lease_expires_at"]) <= _now():
            raise WritebackStateError("Writeback lease expired")
        return row

    def complete_writeback(
        self,
        writeback_id: str,
        *,
        device_id: str,
        lease_token: str,
        result: str,
        payload_hash: str,
        delivery_mode: str,
        provider: str,
        external_id: str = "",
        written_at: str = "",
        error: str = "",
    ) -> dict[str, Any]:
        valid = {"applied", "failed", "conflicted", "awaiting_import", "imported"}
        if result not in valid:
            raise WritebackStateError(f"Invalid receipt result: {result}")
        if delivery_mode not in {"automation", "import_queue"}:
            raise WritebackStateError(f"Invalid delivery mode: {delivery_mode}")
        if not provider.strip():
            raise WritebackStateError("Receipt provider is required")
        now = _iso()
        with self._connect() as conn:
            row = self._require_lease(conn, writeback_id, device_id, lease_token)
            if not secrets.compare_digest(row["payload_hash"], payload_hash.strip()):
                raise WritebackStateError("Receipt payload hash mismatch")
            if row["delivery_mode"] != delivery_mode:
                raise WritebackStateError("Receipt delivery mode mismatch")
            conn.execute(
                """UPDATE mn4_writebacks
                   SET status = ?, provider = ?, external_id = ?, last_error = ?,
                       lease_token = '', lease_expires_at = '', completed_at = ?,
                       updated_at = ?
                   WHERE writeback_id = ?""",
                (
                    result,
                    provider.strip(),
                    external_id,
                    error,
                    written_at or now,
                    now,
                    writeback_id,
                ),
            )
            updated = conn.execute(
                "SELECT * FROM mn4_writebacks WHERE writeback_id = ?", (writeback_id,)
            ).fetchone()
        return _writeback_dict(updated)

    # -- automation verification ---------------------------------------------

    def set_automation_verification(
        self,
        *,
        device_id: str,
        provider: str,
        bundle_id: str,
        app_version: str,
        config_hash: str,
        test_external_id: str = "",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO mn4_automation_verifications
                   (device_id, provider, bundle_id, app_version, config_hash,
                    verified_at, test_external_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(device_id, provider) DO UPDATE SET
                     bundle_id=excluded.bundle_id,
                     app_version=excluded.app_version,
                     config_hash=excluded.config_hash,
                     verified_at=excluded.verified_at,
                     test_external_id=excluded.test_external_id""",
                (
                    device_id,
                    provider,
                    bundle_id,
                    app_version,
                    config_hash,
                    _iso(),
                    test_external_id,
                ),
            )
            conn.execute(
                "UPDATE mn4_devices SET automation_verified = 1 WHERE device_id = ?",
                (device_id,),
            )

    def is_automation_verified(
        self,
        *,
        device_id: str,
        provider: str,
        bundle_id: str,
        app_version: str,
        config_hash: str,
    ) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM mn4_automation_verifications
                   WHERE device_id = ? AND provider = ?""",
                (device_id, provider),
            ).fetchone()
        return bool(
            row
            and row["bundle_id"] == bundle_id
            and row["app_version"] == app_version
            and secrets.compare_digest(row["config_hash"], config_hash)
        )


def _object_params(obj: MarginNoteObject) -> tuple[Any, ...]:
    return (
        obj.object_id,
        obj.device_id,
        obj.object_type,
        obj.title,
        obj.content,
        obj.excerpt,
        obj.document_id,
        obj.document_title,
        obj.page,
        _canonical_json(obj.tags),
        _canonical_json(obj.links),
        obj.color,
        obj.created_at,
        obj.updated_at,
        obj.synced_at,
        obj.object_hash,
        _canonical_json(obj.raw),
    )


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
        object_hash=row["object_hash"] if "object_hash" in row.keys() else "",
        device_id=row["device_id"],
        raw=json.loads(row["raw"]),
    )


def _row_to_device(row: sqlite3.Row) -> PairedDevice:
    keys = row.keys()
    return PairedDevice(
        device_id=row["device_id"],
        user_id=row["user_id"] if "user_id" in keys else "local-admin",
        kb_id=row["kb_id"] if "kb_id" in keys else "",
        kb_name=row["kb_name"] if "kb_name" in keys else "",
        device_name=row["device_name"],
        device_kind=row["device_kind"],
        paired_at=row["paired_at"],
        last_seen=row["last_seen"],
        active=bool(row["active"]),
        automation_verified=bool(row["automation_verified"])
        if "automation_verified" in keys
        else False,
    )


def _writeback_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "writeback_id": row["writeback_id"],
        "user_id": row["user_id"],
        "kb_id": row["kb_id"],
        "status": row["status"],
        "title": row["title"],
        "markdown": row["markdown"],
        "tags": json.loads(row["tags"]),
        "source_refs": json.loads(row["source_refs"]),
        "target_notebook": row["target_notebook"],
        "payload_hash": row["payload_hash"],
        "delivery_mode": row["delivery_mode"],
        "provider": row["provider"],
        "external_id": row["external_id"],
        "attempts": int(row["attempts"]),
        "last_error": row["last_error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "completed_at": row["completed_at"],
    }


def _to_summary(obj: MarginNoteObject, query: str) -> dict[str, Any]:
    body = obj.content or obj.excerpt or ""
    return {
        "object_id": obj.object_id,
        "object_type": obj.object_type,
        "title": obj.title,
        "document_title": obj.document_title,
        "page": obj.page,
        "tags": obj.tags,
        "snippet": _snippet(body, query),
        "updated_at": obj.updated_at,
    }


def _snippet(body: str, query: str, width: int = 160) -> str:
    if not body:
        return ""
    if not query:
        return body[:width].strip().replace("\n", " ")
    index = body.lower().find(query.lower())
    if index < 0:
        return body[:width].strip().replace("\n", " ")
    start = max(0, index - width // 3)
    suffix = "..." if start + width < len(body) else ""
    prefix = "..." if start else ""
    return prefix + body[start : start + width].strip().replace("\n", " ") + suffix


__all__ = [
    "BulkDeleteGuard",
    "DEFAULT_LEASE_TTL_SECONDS",
    "DEFAULT_PAIRING_TTL_SECONDS",
    "MarginNoteStore",
    "MarginNoteStoreError",
    "PairingError",
    "SyncConflict",
    "WritebackStateError",
    "_default_db_path",
    "object_hash",
    "payload_hash",
]
