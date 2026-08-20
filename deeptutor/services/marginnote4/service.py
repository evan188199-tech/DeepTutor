"""Transactional backend for the MarginNote 4 bridge.

The service deliberately does not know FastAPI or the chat tool protocol. Its
important invariant is that every device operation is bound server-side to a
DeepTutor user and one MN4 library; no request header can select a database.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
from pathlib import Path
import secrets
import sqlite3
from typing import Any
import uuid

from .models import (
    MARGINNOTE4_PROTOCOL_VERSION,
    AuthenticatedDevice,
    DeviceRecord,
    MarginNoteObject,
    PairingSession,
    PullResult,
    PushResult,
)

logger = logging.getLogger(__name__)


class MarginNote4Error(Exception):
    """Base class for expected bridge failures."""


class InvalidRequest(MarginNote4Error):
    """The device or session sent an invalid payload."""


class UnauthorizedDevice(MarginNote4Error):
    """Credentials are absent, revoked, or invalid."""


class OperationConflict(MarginNote4Error):
    """An operation ID was reused with a different payload."""


_SCHEMA_VERSION = 1
_SCHEMA = """
CREATE TABLE IF NOT EXISTS mn4_pairing_sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    library_id TEXT NOT NULL,
    library_name TEXT NOT NULL,
    code_hash TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    device_id TEXT,
    device_name TEXT NOT NULL DEFAULT '',
    device_kind TEXT NOT NULL DEFAULT 'macos',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mn4_devices (
    device_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    library_id TEXT NOT NULL,
    library_name TEXT NOT NULL,
    device_name TEXT NOT NULL DEFAULT '',
    device_kind TEXT NOT NULL DEFAULT 'macos',
    status TEXT NOT NULL,
    claim_secret_hash TEXT,
    token_hash TEXT UNIQUE,
    token_release_hash TEXT,
    paired_at TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    revoked_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_mn4_devices_owner
    ON mn4_devices (user_id, status);

CREATE TABLE IF NOT EXISTS mn4_objects (
    user_id TEXT NOT NULL,
    library_id TEXT NOT NULL,
    object_id TEXT NOT NULL,
    object_type TEXT NOT NULL,
    revision INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    excerpt TEXT,
    document_id TEXT,
    document_title TEXT,
    page INTEGER,
    tags TEXT NOT NULL DEFAULT '[]',
    links TEXT NOT NULL DEFAULT '[]',
    color TEXT,
    source_locator TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    raw TEXT NOT NULL DEFAULT '{}',
    deleted INTEGER NOT NULL DEFAULT 0,
    updated_by_device TEXT NOT NULL DEFAULT '',
    synced_at TEXT NOT NULL,
    PRIMARY KEY (user_id, library_id, object_id)
);

CREATE INDEX IF NOT EXISTS idx_mn4_objects_read
    ON mn4_objects (user_id, library_id, object_type, updated_at DESC);

CREATE TABLE IF NOT EXISTS mn4_operations (
    user_id TEXT NOT NULL,
    library_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    result_json TEXT NOT NULL,
    applied_at TEXT NOT NULL,
    PRIMARY KEY (user_id, library_id, operation_id)
);

CREATE TABLE IF NOT EXISTS mn4_changes (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    library_id TEXT NOT NULL,
    object_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    action TEXT NOT NULL,
    device_id TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    UNIQUE (user_id, library_id, object_id, revision, action)
);

CREATE INDEX IF NOT EXISTS idx_mn4_changes_cursor
    ON mn4_changes (user_id, library_id, seq);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _public_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _pairing_code() -> str:
    raw = secrets.token_urlsafe(12).replace("-", "").replace("_", "").upper()
    return f"MN4-{raw[:4]}-{raw[4:8]}"


def _required_text(value: Any, field_name: str, *, maximum: int = 512) -> str:
    text = str(value or "").strip()
    if not text:
        raise InvalidRequest(f"{field_name} is required")
    if len(text) > maximum:
        raise InvalidRequest(f"{field_name} is too long")
    return text


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class MarginNote4Service:
    """SQLite-backed state machine for pairing, sync, and connected reads."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)
            current = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if current == 0:
                conn.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
            elif current != _SCHEMA_VERSION:
                raise RuntimeError(f"Unsupported MN4 bridge schema version {current}")

    # -- pairing ------------------------------------------------------------

    def create_pairing_session(
        self,
        *,
        user_id: str,
        library_id: str,
        library_name: str = "",
        ttl_minutes: int = 10,
    ) -> tuple[PairingSession, str]:
        user_id = _required_text(user_id, "user_id")
        library_id = _required_text(library_id, "library_id")
        library_name = _required_text(library_name or library_id, "library_name")
        if ttl_minutes <= 0 or ttl_minutes > 60:
            raise InvalidRequest("ttl_minutes must be between 1 and 60")
        session_id = _public_id("mn4pair")
        code = _pairing_code()
        now = _now()
        expires = (datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)).isoformat()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO mn4_pairing_sessions
                   (session_id, user_id, library_id, library_name, code_hash, status,
                    device_name, device_kind, created_at, updated_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, 'pending', '', 'macos', ?, ?, ?)""",
                (session_id, user_id, library_id, library_name, _hash(code), now, now, expires),
            )
        return self.get_pairing_session(user_id, session_id), code

    def get_pairing_session(self, user_id: str, session_id: str) -> PairingSession:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM mn4_pairing_sessions WHERE user_id=? AND session_id=?",
                (user_id, session_id),
            ).fetchone()
        if row is None:
            raise KeyError("Pairing session not found")
        return _session_from_row(row)

    def list_pairing_sessions(
        self, user_id: str, *, include_expired: bool = False
    ) -> list[PairingSession]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM mn4_pairing_sessions WHERE user_id=? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        sessions = [_session_from_row(row) for row in rows]
        if include_expired:
            return sessions
        now = datetime.now(timezone.utc)
        return [session for session in sessions if datetime.fromisoformat(session.expires_at) > now]

    def claim_pairing_session(
        self,
        *,
        pairing_code: str,
        device_name: str,
        device_kind: str,
    ) -> dict[str, str]:
        pairing_code = _required_text(pairing_code, "pairing_code")
        device_name = _required_text(device_name, "device_name")
        if device_kind not in {"macos", "ipados"}:
            raise InvalidRequest("device_kind must be macos or ipados")
        code_hash = _hash(pairing_code)
        claim_secret = secrets.token_urlsafe(32)
        now = _now()
        device_id = _public_id("mn4dev")

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM mn4_pairing_sessions WHERE code_hash=?", (code_hash,)
            ).fetchone()
            if row is None or row["status"] != "pending":
                conn.execute("ROLLBACK")
                raise UnauthorizedDevice("Pairing code is invalid or already used")
            if datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
                conn.execute(
                    "UPDATE mn4_pairing_sessions SET status='expired', updated_at=? WHERE session_id=?",
                    (now, row["session_id"]),
                )
                conn.execute("ROLLBACK")
                raise UnauthorizedDevice("Pairing code has expired")

            conn.execute(
                """INSERT INTO mn4_devices
                   (device_id, user_id, library_id, library_name, device_name, device_kind,
                    status, claim_secret_hash, paired_at, last_seen)
                   VALUES (?, ?, ?, ?, ?, ?, 'claimed', ?, ?, ?)""",
                (
                    device_id,
                    row["user_id"],
                    row["library_id"],
                    row["library_name"],
                    device_name,
                    device_kind,
                    _hash(claim_secret),
                    now,
                    now,
                ),
            )
            conn.execute(
                """UPDATE mn4_pairing_sessions
                   SET status='claimed', device_id=?, device_name=?, device_kind=?, updated_at=?
                   WHERE session_id=? AND status='pending'""",
                (device_id, device_name, device_kind, now, row["session_id"]),
            )
            conn.execute("COMMIT")

        return {
            "session_id": row["session_id"],
            "device_id": device_id,
            "claim_secret": claim_secret,
            "status": "claimed",
        }

    def confirm_pairing_session(self, *, user_id: str, session_id: str) -> PairingSession:
        now = _now()
        release_secret = secrets.token_urlsafe(32)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM mn4_pairing_sessions WHERE user_id=? AND session_id=?",
                (user_id, session_id),
            ).fetchone()
            if row is None or row["status"] != "claimed" or not row["device_id"]:
                conn.execute("ROLLBACK")
                raise KeyError("Pairing session is not awaiting confirmation")
            conn.execute(
                "UPDATE mn4_pairing_sessions SET status='confirmed', updated_at=? WHERE session_id=?",
                (now, session_id),
            )
            conn.execute(
                """UPDATE mn4_devices SET status='approved', token_release_hash=?
                   WHERE device_id=? AND status='claimed'""",
                (_hash(release_secret), row["device_id"]),
            )
            conn.execute("COMMIT")
        return self.get_pairing_session(user_id, session_id)

    def cancel_pairing_session(self, *, user_id: str, session_id: str) -> PairingSession:
        now = _now()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM mn4_pairing_sessions WHERE user_id=? AND session_id=?",
                (user_id, session_id),
            ).fetchone()
            if row is None:
                raise KeyError("Pairing session not found")
            conn.execute(
                "UPDATE mn4_pairing_sessions SET status='cancelled', updated_at=? WHERE session_id=?",
                (now, session_id),
            )
            if row["device_id"]:
                conn.execute(
                    "UPDATE mn4_devices SET status='revoked', revoked_at=? WHERE device_id=?",
                    (now, row["device_id"]),
                )
        return self.get_pairing_session(user_id, session_id)

    def complete_pairing(self, *, device_id: str, claim_secret: str) -> tuple[str, dict[str, str]]:
        device_id = _required_text(device_id, "device_id")
        claim_secret = _required_text(claim_secret, "claim_secret")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM mn4_devices WHERE device_id=?", (device_id,)
            ).fetchone()
            if (
                row is None
                or not row["claim_secret_hash"]
                or not secrets.compare_digest(row["claim_secret_hash"], _hash(claim_secret))
            ):
                conn.execute("ROLLBACK")
                raise UnauthorizedDevice("Invalid device claim")
            if row["status"] == "claimed":
                conn.execute("ROLLBACK")
                return "", {"device_id": device_id, "status": "claimed"}
            if row["status"] != "approved" or not row["token_release_hash"]:
                conn.execute("ROLLBACK")
                raise UnauthorizedDevice("Device claim is not releasable")

            token = f"mn4_{secrets.token_urlsafe(48)}"
            now = _now()
            conn.execute(
                """UPDATE mn4_devices
                   SET status='active', token_hash=?, token_release_hash=NULL, last_seen=?
                   WHERE device_id=?""",
                (_hash(token), now, device_id),
            )
            conn.execute(
                """UPDATE mn4_pairing_sessions
                   SET status='connected', updated_at=? WHERE device_id=?""",
                (now, device_id),
            )
            conn.execute("COMMIT")
        return token, {"device_id": device_id, "status": "active"}

    # -- devices ------------------------------------------------------------

    def authenticate_device(self, token: str) -> AuthenticatedDevice:
        token = str(token or "").strip()
        if not token.startswith("mn4_"):
            raise UnauthorizedDevice("Invalid device token")
        now = _now()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM mn4_devices WHERE token_hash=?", (_hash(token),)
            ).fetchone()
            if row is None or row["status"] != "active":
                raise UnauthorizedDevice("Device token is invalid or revoked")
            conn.execute(
                "UPDATE mn4_devices SET last_seen=? WHERE device_id=?", (now, row["device_id"])
            )
        return AuthenticatedDevice(
            device_id=row["device_id"],
            user_id=row["user_id"],
            library_id=row["library_id"],
            library_name=row["library_name"],
        )

    def list_devices(self, user_id: str) -> list[DeviceRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM mn4_devices WHERE user_id=? ORDER BY paired_at", (user_id,)
            ).fetchall()
        return [_device_from_row(row) for row in rows]

    def rotate_device_token(self, *, user_id: str, device_id: str) -> str:
        token = f"mn4_{secrets.token_urlsafe(48)}"
        now = _now()
        with self._connect() as conn:
            cur = conn.execute(
                """UPDATE mn4_devices SET token_hash=?, last_seen=?
                   WHERE device_id=? AND user_id=? AND status='active'""",
                (_hash(token), now, device_id, user_id),
            )
            if cur.rowcount != 1:
                raise KeyError("Active device not found")
        return token

    def revoke_device(self, *, user_id: str, device_id: str) -> None:
        now = _now()
        with self._connect() as conn:
            cur = conn.execute(
                """UPDATE mn4_devices SET status='revoked', token_hash=NULL,
                   token_release_hash=NULL, revoked_at=?
                   WHERE device_id=? AND user_id=? AND status != 'revoked'""",
                (now, device_id, user_id),
            )
            if cur.rowcount != 1:
                raise KeyError("Device not found")

    def heartbeat(self, device: AuthenticatedDevice) -> dict[str, Any]:
        with self._connect() as conn:
            count = conn.execute(
                """SELECT COUNT(*) FROM mn4_objects
                   WHERE user_id=? AND library_id=? AND deleted=0""",
                (device.user_id, device.library_id),
            ).fetchone()[0]
            cursor = conn.execute(
                """SELECT COALESCE(MAX(seq), 0) FROM mn4_changes
                   WHERE user_id=? AND library_id=?""",
                (device.user_id, device.library_id),
            ).fetchone()[0]
        return {
            "status": "ok",
            "device_id": device.device_id,
            "object_count": count,
            "cursor": str(cursor),
            "protocol_version": MARGINNOTE4_PROTOCOL_VERSION,
        }

    # -- sync ---------------------------------------------------------------

    def push(
        self,
        device: AuthenticatedDevice,
        *,
        protocol_version: int,
        operation_id: str,
        objects: list[dict[str, Any]],
        deletions: list[dict[str, Any]],
    ) -> PushResult:
        if protocol_version != MARGINNOTE4_PROTOCOL_VERSION:
            raise InvalidRequest(
                f"Unsupported protocol version {protocol_version}; expected {MARGINNOTE4_PROTOCOL_VERSION}"
            )
        operation_id = _required_text(operation_id, "operation_id", maximum=128)
        normalized = [self._normalize_object(item) for item in objects]
        by_id = {item.object_id: item for item in normalized}
        if len(by_id) != len(normalized):
            raise InvalidRequest("An object_id appears more than once in one operation")

        deletions = [self._normalize_deletion(item) for item in deletions]
        deleted_ids = [item["object_id"] for item in deletions]
        if len(set(deleted_ids)) != len(deleted_ids):
            raise InvalidRequest("A deleted object_id appears more than once in one operation")
        overlap = set(by_id) & set(deleted_ids)
        if overlap:
            raise InvalidRequest(f"Objects cannot be both upserted and deleted: {sorted(overlap)}")

        fingerprint = _canonical(
            {
                "protocol_version": protocol_version,
                "objects": [
                    item.to_dict() for item in sorted(by_id.values(), key=lambda x: x.object_id)
                ],
                "deletions": sorted(deletions, key=lambda x: x["object_id"]),
            }
        )
        now = _now()
        accepted = updated = deleted = stale = 0
        conflicts: list[dict[str, Any]] = []

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            previous = conn.execute(
                """SELECT fingerprint, result_json FROM mn4_operations
                   WHERE user_id=? AND library_id=? AND operation_id=?""",
                (device.user_id, device.library_id, operation_id),
            ).fetchone()
            if previous is not None:
                conn.execute("ROLLBACK")
                if previous["fingerprint"] != fingerprint:
                    raise OperationConflict("operation_id was already used with another payload")
                return _result_from_json(previous["result_json"], replayed=True)

            for obj in sorted(by_id.values(), key=lambda x: x.object_id):
                current = conn.execute(
                    """SELECT revision, deleted, object_type, title, content FROM mn4_objects
                       WHERE user_id=? AND library_id=? AND object_id=?""",
                    (device.user_id, device.library_id, obj.object_id),
                ).fetchone()
                if current is not None and obj.revision < int(current["revision"]):
                    stale += 1
                    continue
                if (
                    current is not None
                    and obj.revision == int(current["revision"])
                    and (
                        bool(current["deleted"]) != obj.deleted
                        or str(current["object_type"]) != obj.object_type
                        or str(current["title"]) != obj.title
                        or str(current["content"]) != obj.content
                    )
                ):
                    conflicts.append(
                        {
                            "object_id": obj.object_id,
                            "reason": "same_revision_different_content",
                            "server_revision": int(current["revision"]),
                            "device_revision": obj.revision,
                        }
                    )
                    continue
                if current is not None and obj.revision == int(current["revision"]):
                    stale += 1
                    continue

                conn.execute(
                    """INSERT INTO mn4_objects
                       (user_id, library_id, object_id, object_type, revision, title, content,
                        excerpt, document_id, document_title, page, tags, links, color,
                        source_locator, created_at, updated_at, raw, deleted,
                        updated_by_device, synced_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(user_id, library_id, object_id) DO UPDATE SET
                         object_type=excluded.object_type,
                         revision=excluded.revision,
                         title=excluded.title,
                         content=excluded.content,
                         excerpt=excluded.excerpt,
                         document_id=excluded.document_id,
                         document_title=excluded.document_title,
                         page=excluded.page,
                         tags=excluded.tags,
                         links=excluded.links,
                         color=excluded.color,
                         source_locator=excluded.source_locator,
                         created_at=excluded.created_at,
                         updated_at=excluded.updated_at,
                         raw=excluded.raw,
                         deleted=excluded.deleted,
                         updated_by_device=excluded.updated_by_device,
                         synced_at=excluded.synced_at""",
                    (
                        device.user_id,
                        device.library_id,
                        obj.object_id,
                        obj.object_type,
                        obj.revision,
                        obj.title,
                        obj.content,
                        obj.excerpt,
                        obj.document_id,
                        obj.document_title,
                        obj.page,
                        _canonical(obj.tags),
                        _canonical(obj.links),
                        obj.color,
                        _canonical(obj.source_locator),
                        obj.created_at,
                        obj.updated_at,
                        _canonical(obj.raw),
                        int(obj.deleted),
                        device.device_id,
                        now,
                    ),
                )
                conn.execute(
                    """INSERT INTO mn4_changes
                       (user_id, library_id, object_id, revision, action, device_id, changed_at)
                       VALUES (?, ?, ?, ?, 'upsert', ?, ?)""",
                    (
                        device.user_id,
                        device.library_id,
                        obj.object_id,
                        obj.revision,
                        device.device_id,
                        now,
                    ),
                )
                if current is None:
                    accepted += 1
                else:
                    updated += 1

            for item in deletions:
                object_id = item["object_id"]
                revision = item["revision"]
                current = conn.execute(
                    """SELECT revision, deleted FROM mn4_objects
                       WHERE user_id=? AND library_id=? AND object_id=?""",
                    (device.user_id, device.library_id, object_id),
                ).fetchone()
                if current is not None and revision <= int(current["revision"]):
                    if bool(current["deleted"]):
                        stale += 1
                    else:
                        conflicts.append(
                            {
                                "object_id": object_id,
                                "reason": "delete_revision_not_after_server_revision",
                                "server_revision": int(current["revision"]),
                                "device_revision": revision,
                            }
                        )
                    continue

                if current is None:
                    conn.execute(
                        """INSERT INTO mn4_objects
                           (user_id, library_id, object_id, object_type, revision, deleted,
                            updated_by_device, synced_at)
                           VALUES (?, ?, ?, 'note', ?, 1, ?, ?)""",
                        (
                            device.user_id,
                            device.library_id,
                            object_id,
                            revision,
                            device.device_id,
                            now,
                        ),
                    )
                else:
                    conn.execute(
                        """UPDATE mn4_objects SET revision=?, deleted=1,
                           updated_by_device=?, synced_at=?
                           WHERE user_id=? AND library_id=? AND object_id=?""",
                        (
                            revision,
                            device.device_id,
                            now,
                            device.user_id,
                            device.library_id,
                            object_id,
                        ),
                    )
                conn.execute(
                    """INSERT INTO mn4_changes
                       (user_id, library_id, object_id, revision, action, device_id, changed_at)
                       VALUES (?, ?, ?, ?, 'delete', ?, ?)""",
                    (device.user_id, device.library_id, object_id, revision, device.device_id, now),
                )
                deleted += 1

            cursor_row = conn.execute("SELECT COALESCE(MAX(seq), 0) FROM mn4_changes").fetchone()[0]
            result = PushResult(
                operation_id=operation_id,
                cursor=str(cursor_row),
                accepted=accepted,
                updated=updated,
                deleted=deleted,
                ignored_stale=stale,
                conflicts=conflicts,
            )
            conn.execute(
                """INSERT INTO mn4_operations
                   (user_id, library_id, operation_id, device_id, fingerprint, result_json, applied_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    device.user_id,
                    device.library_id,
                    operation_id,
                    device.device_id,
                    fingerprint,
                    _canonical(asdict(result)),
                    now,
                ),
            )
            conn.execute("COMMIT")
        return result

    def pull(
        self,
        device: AuthenticatedDevice,
        *,
        cursor: str | int = 0,
        limit: int = 500,
    ) -> PullResult:
        try:
            cursor_value = int(cursor)
        except (TypeError, ValueError) as exc:
            raise InvalidRequest("cursor must be an integer change sequence") from exc
        if cursor_value < 0:
            raise InvalidRequest("cursor cannot be negative")
        limit = max(1, min(limit, 1000))
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT c.seq, c.action, c.revision, c.changed_at, o.*
                   FROM mn4_changes c
                   JOIN mn4_objects o
                     ON o.user_id=c.user_id AND o.library_id=c.library_id
                    AND o.object_id=c.object_id
                   WHERE c.user_id=? AND c.library_id=? AND c.seq>?
                   ORDER BY c.seq LIMIT ?""",
                (device.user_id, device.library_id, cursor_value, limit + 1),
            ).fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        changes = []
        for row in rows:
            obj = _object_from_row(row)
            payload = obj.to_dict()
            payload.update(
                {
                    "seq": int(row["seq"]),
                    "action": row["action"],
                    "changed_at": row["changed_at"],
                }
            )
            changes.append(payload)
        next_cursor = str(int(rows[-1]["seq"])) if rows else str(cursor_value)
        return PullResult(cursor=next_cursor, has_more=has_more, changes=changes)

    # -- connected reads ----------------------------------------------------

    def get_object(
        self,
        *,
        user_id: str,
        library_id: str,
        object_id: str,
        include_deleted: bool = False,
    ) -> MarginNoteObject | None:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM mn4_objects WHERE user_id=? AND library_id=? AND object_id=?""",
                (user_id, library_id, object_id),
            ).fetchone()
        if row is None or (bool(row["deleted"]) and not include_deleted):
            return None
        return _object_from_row(row)

    def search_objects(
        self,
        *,
        user_id: str,
        library_id: str,
        query: str = "",
        object_type: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 200))
        clauses = ["user_id=?", "library_id=?", "deleted=0"]
        params: list[Any] = [user_id, library_id]
        if query.strip():
            needle = f"%{query.strip().lower()}%"
            clauses.append(
                "(LOWER(title) LIKE ? OR LOWER(content) LIKE ? OR LOWER(COALESCE(excerpt,'')) LIKE ?)"
            )
            params.extend([needle, needle, needle])
        if object_type:
            clauses.append("object_type=?")
            params.append(object_type)
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT * FROM mn4_objects WHERE {" AND ".join(clauses)}
                    ORDER BY updated_at DESC LIMIT ?""",
                params,
            ).fetchall()
        return [_summary(_object_from_row(row), query) for row in rows]

    def status(self, *, user_id: str, library_id: str = "") -> dict[str, Any]:
        with self._connect() as conn:
            device_rows = conn.execute(
                "SELECT COUNT(*) FROM mn4_devices WHERE user_id=? AND status='active'",
                (user_id,),
            ).fetchone()[0]
            object_rows = conn.execute(
                "SELECT COUNT(*) FROM mn4_objects WHERE user_id=? AND deleted=0",
                (user_id,),
            ).fetchone()[0]
            cursor = conn.execute(
                "SELECT COALESCE(MAX(seq),0) FROM mn4_changes WHERE user_id=?",
                (user_id,),
            ).fetchone()[0]
        return {
            "protocol_version": MARGINNOTE4_PROTOCOL_VERSION,
            "active_devices": device_rows,
            "objects": object_rows,
            "cursor": str(cursor),
        }

    def list_documents(self, *, user_id: str, library_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT document_id, document_title, COUNT(*) AS object_count
                   FROM mn4_objects
                   WHERE user_id=? AND library_id=? AND deleted=0 AND document_id IS NOT NULL
                   GROUP BY document_id, document_title
                   ORDER BY COALESCE(document_title, document_id)""",
                (user_id, library_id),
            ).fetchall()
        return [
            {
                "document_id": row["document_id"],
                "title": row["document_title"] or row["document_id"],
                "object_count": int(row["object_count"]),
            }
            for row in rows
        ]

    def linked_objects(
        self, *, user_id: str, library_id: str, object_id: str
    ) -> list[dict[str, Any]]:
        obj = self.get_object(user_id=user_id, library_id=library_id, object_id=object_id)
        if obj is None:
            return []
        linked_ids = list(dict.fromkeys(obj.links))
        return [
            summary
            for linked_id in linked_ids
            if (
                linked := self.get_object(
                    user_id=user_id, library_id=library_id, object_id=linked_id
                )
            )
            is not None
            for summary in [_summary(linked, "")]
        ]

    def collect_tags(
        self, *, user_id: str, library_id: str, limit: int = 200
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT tags FROM mn4_objects
                   WHERE user_id=? AND library_id=? AND deleted=0""",
                (user_id, library_id),
            ).fetchall()
        counts: dict[str, int] = {}
        for row in rows:
            for tag in json.loads(row["tags"]):
                normalized = tag.strip()
                if normalized:
                    counts[normalized] = counts.get(normalized, 0) + 1
        return [
            {"tag": tag, "count": count}
            for tag, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
        ]

    def _normalize_object(self, item: dict[str, Any]) -> MarginNoteObject:
        if not isinstance(item, dict):
            raise InvalidRequest("Each object must be a JSON object")
        object_id = _required_text(item.get("object_id"), "object_id", maximum=256)
        object_type = _required_text(item.get("object_type"), "object_type")
        if object_type not in {"note", "excerpt", "card", "mindmap_node", "document", "comment"}:
            raise InvalidRequest(f"Unsupported object_type {object_type}")
        try:
            revision = int(item.get("revision"))
        except (TypeError, ValueError) as exc:
            raise InvalidRequest("revision must be a positive integer") from exc
        if revision <= 0:
            raise InvalidRequest("revision must be a positive integer")
        source_locator = item.get("source_locator") or {}
        raw = item.get("raw") or {}
        tags = item.get("tags") or []
        links = item.get("links") or []
        if not isinstance(source_locator, dict) or not isinstance(raw, dict):
            raise InvalidRequest("source_locator and raw must be JSON objects")
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise InvalidRequest("tags must be an array of strings")
        if not isinstance(links, list) or not all(isinstance(link, str) for link in links):
            raise InvalidRequest("links must be an array of strings")
        return MarginNoteObject(
            object_id=object_id,
            object_type=object_type,
            revision=revision,
            title=str(item.get("title") or ""),
            content=str(item.get("content") or ""),
            excerpt=_optional_text(item.get("excerpt")),
            document_id=_optional_text(item.get("document_id")),
            document_title=_optional_text(item.get("document_title")),
            page=_optional_int(item.get("page")),
            tags=tags,
            links=links,
            color=_optional_text(item.get("color")),
            source_locator=source_locator,
            created_at=str(item.get("created_at") or ""),
            updated_at=str(item.get("updated_at") or ""),
            raw=raw,
            deleted=bool(item.get("deleted", False)),
        )

    def _normalize_deletion(self, item: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(item, dict):
            raise InvalidRequest("Each deletion must be a JSON object")
        object_id = _required_text(item.get("object_id"), "object_id", maximum=256)
        try:
            revision = int(item.get("revision"))
        except (TypeError, ValueError) as exc:
            raise InvalidRequest("deletion revision must be a positive integer") from exc
        if revision <= 0:
            raise InvalidRequest("deletion revision must be a positive integer")
        return {"object_id": object_id, "revision": revision}


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise InvalidRequest("page must be an integer") from exc


def _session_from_row(row: sqlite3.Row) -> PairingSession:
    return PairingSession(
        session_id=row["session_id"],
        user_id=row["user_id"],
        library_id=row["library_id"],
        library_name=row["library_name"],
        status=row["status"],
        device_id=row["device_id"],
        device_name=row["device_name"],
        device_kind=row["device_kind"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        expires_at=row["expires_at"],
    )


def _device_from_row(row: sqlite3.Row) -> DeviceRecord:
    return DeviceRecord(
        device_id=row["device_id"],
        user_id=row["user_id"],
        library_id=row["library_id"],
        library_name=row["library_name"],
        device_name=row["device_name"],
        device_kind=row["device_kind"],
        status=row["status"],
        paired_at=row["paired_at"],
        last_seen=row["last_seen"],
        revoked_at=row["revoked_at"],
    )


def _object_from_row(row: sqlite3.Row) -> MarginNoteObject:
    return MarginNoteObject(
        object_id=row["object_id"],
        object_type=row["object_type"],
        revision=int(row["revision"]),
        title=row["title"],
        content=row["content"],
        excerpt=row["excerpt"],
        document_id=row["document_id"],
        document_title=row["document_title"],
        page=row["page"],
        tags=json.loads(row["tags"]),
        links=json.loads(row["links"]),
        color=row["color"],
        source_locator=json.loads(row["source_locator"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        raw=json.loads(row["raw"]),
        deleted=bool(row["deleted"]),
    )


def _summary(obj: MarginNoteObject, query: str) -> dict[str, Any]:
    body = obj.content or obj.excerpt or obj.title
    return {
        "object_id": obj.object_id,
        "object_type": obj.object_type,
        "revision": obj.revision,
        "title": obj.title,
        "snippet": _snippet(body, query),
        "document_id": obj.document_id,
        "document_title": obj.document_title,
        "source_locator": obj.source_locator,
        "updated_at": obj.updated_at,
    }


def _snippet(body: str, query: str, width: int = 180) -> str:
    text = " ".join(body.split())
    if not query:
        return text[:width]
    index = text.lower().find(query.lower())
    if index < 0:
        return text[:width]
    start = max(0, index - width // 3)
    return text[start : start + width]


def _result_from_json(payload: str, *, replayed: bool) -> PushResult:
    data = json.loads(payload)
    return PushResult(
        operation_id=data["operation_id"],
        cursor=data["cursor"],
        accepted=data["accepted"],
        updated=data["updated"],
        deleted=data["deleted"],
        ignored_stale=data["ignored_stale"],
        conflicts=data.get("conflicts", []),
        replayed=replayed,
    )


__all__ = ["MarginNote4Service"]
