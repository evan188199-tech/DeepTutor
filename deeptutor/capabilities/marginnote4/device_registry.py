"""Global device registry used to route MarginNote auth to one KB store."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import secrets
import sqlite3
from typing import Any

from deeptutor.capabilities.marginnote4.store import _default_db_path


class DeviceRegistryError(Exception):
    pass


_SCHEMA = """
CREATE TABLE IF NOT EXISTS pairing_codes (
    code_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    kb_id TEXT NOT NULL,
    kb_name TEXT NOT NULL,
    db_path TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    kb_id TEXT NOT NULL,
    kb_name TEXT NOT NULL,
    db_path TEXT NOT NULL,
    device_name TEXT NOT NULL DEFAULT '',
    device_kind TEXT NOT NULL DEFAULT 'macos',
    token_hash TEXT NOT NULL,
    paired_at TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class DeviceRegistry:
    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = _default_db_path("_bridge_registry") if db_path is None else str(db_path)
        import pathlib

        pathlib.Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def create_pairing_code(
        self,
        *,
        user_id: str,
        kb_id: str,
        kb_name: str,
        db_path: str,
        ttl_seconds: int = 600,
    ) -> str:
        code = "mn4-" + secrets.token_urlsafe(24)
        expires = _now() + timedelta(seconds=max(30, ttl_seconds))
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO pairing_codes
                   (code_hash, user_id, kb_id, kb_name, db_path, expires_at, used)
                   VALUES (?, ?, ?, ?, ?, ?, 0)""",
                (
                    _hash(code),
                    user_id,
                    kb_id,
                    kb_name,
                    str(db_path),
                    _iso(expires),
                ),
            )
        return code

    def consume_pairing_code(self, code: str) -> dict[str, Any]:
        code_hash = _hash(code.strip())
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM pairing_codes WHERE code_hash = ?", (code_hash,)
            ).fetchone()
            if row is None or row["used"]:
                raise DeviceRegistryError("Invalid pairing code")
            expires = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
            if expires <= _now():
                raise DeviceRegistryError("Pairing code expired")
            changed = conn.execute(
                "UPDATE pairing_codes SET used = 1 WHERE code_hash = ? AND used = 0",
                (code_hash,),
            ).rowcount
            if changed != 1:
                raise DeviceRegistryError("Pairing code was already used")
            return dict(row)

    def register_device(
        self,
        pairing: dict[str, Any],
        *,
        device_name: str,
        device_kind: str,
    ) -> tuple[dict[str, Any], str]:
        device_id = "mn4dev-" + secrets.token_urlsafe(12)
        token = secrets.token_urlsafe(32)
        now = _iso(_now())
        device = {
            "device_id": device_id,
            "user_id": pairing["user_id"],
            "kb_id": pairing["kb_id"],
            "kb_name": pairing["kb_name"],
            "db_path": pairing["db_path"],
            "device_name": device_name,
            "device_kind": device_kind,
            "paired_at": now,
            "last_seen": now,
            "active": True,
        }
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO devices
                   (device_id, user_id, kb_id, kb_name, db_path, device_name,
                    device_kind, token_hash, paired_at, last_seen, active)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (
                    device_id,
                    device["user_id"],
                    device["kb_id"],
                    device["kb_name"],
                    device["db_path"],
                    device_name,
                    device_kind,
                    _hash(token),
                    now,
                    now,
                ),
            )
        return device, token

    def authenticate(self, device_id: str, token: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM devices WHERE device_id = ?", (device_id,)).fetchone()
        if row is None or not row["active"]:
            raise DeviceRegistryError("Unknown or inactive device")
        if not secrets.compare_digest(row["token_hash"], _hash(token)):
            raise DeviceRegistryError("Invalid device token")
        with self._connect() as conn:
            conn.execute(
                "UPDATE devices SET last_seen = ? WHERE device_id = ?",
                (_iso(_now()), device_id),
            )
        return dict(row)

    def list_devices(
        self, *, user_id: str, kb_id: str = "", include_inactive: bool = False
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM devices WHERE user_id = ?"
        params: list[Any] = [user_id]
        if kb_id:
            sql += " AND kb_id = ?"
            params.append(kb_id)
        if not include_inactive:
            sql += " AND active = 1"
        sql += " ORDER BY paired_at"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def revoke(self, device_id: str, *, user_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT user_id FROM devices WHERE device_id = ?", (device_id,)
            ).fetchone()
            if row is None or row["user_id"] != user_id:
                return False
            changed = conn.execute(
                "UPDATE devices SET active = 0 WHERE device_id = ? AND active = 1",
                (device_id,),
            ).rowcount
            return changed == 1


__all__ = ["DeviceRegistry", "DeviceRegistryError"]
