"""Owner-scoped MarginNote device and pairing-code registry.

The registry is deliberately separate from a synced library. A device token
must resolve to one immutable owner/workspace/library binding before any data
store path is constructed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import secrets
import sqlite3
from typing import Any


class PairingCodeError(RuntimeError):
    """A pairing code is unknown, expired, or has already been claimed."""


class ActiveDeviceError(RuntimeError):
    """The library already has an active sync device."""


@dataclass(slots=True)
class RegisteredDevice:
    device_id: str
    owner_id: str
    kb_name: str
    workspace_root: str
    device_name: str
    device_kind: str
    protocol_version: int
    paired_at: str
    last_seen: str
    revoked_at: str = ""

    @property
    def active(self) -> bool:
        return not self.revoked_at


@dataclass(slots=True)
class PairingCode:
    code: str
    expires_at: str


_SCHEMA = """
CREATE TABLE IF NOT EXISTS mn4_pairing_codes (
    code_hash TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    kb_name TEXT NOT NULL,
    workspace_root TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    claimed_at TEXT,
    device_id TEXT
);

CREATE TABLE IF NOT EXISTS mn4_registered_devices (
    device_id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    kb_name TEXT NOT NULL,
    workspace_root TEXT NOT NULL,
    device_name TEXT NOT NULL DEFAULT '',
    device_kind TEXT NOT NULL DEFAULT 'macos',
    token_hash TEXT NOT NULL UNIQUE,
    protocol_version INTEGER NOT NULL,
    paired_at TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    revoked_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_mn4_active_device
ON mn4_registered_devices (workspace_root, kb_name)
WHERE revoked_at IS NULL;
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class MarginNoteDeviceRegistry:
    """SQLite registry for one DeepTutor installation/owner scope."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def create_pairing_code(
        self,
        *,
        owner_id: str,
        kb_name: str,
        workspace_root: str,
        ttl_seconds: int = 600,
    ) -> PairingCode:
        code = secrets.token_urlsafe(9)
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=max(60, min(ttl_seconds, 900)))
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO mn4_pairing_codes
                   (code_hash, owner_id, kb_name, workspace_root,
                    created_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    _hash(code),
                    owner_id,
                    kb_name,
                    str(Path(workspace_root).resolve()),
                    now.isoformat(),
                    expires.isoformat(),
                ),
            )
        return PairingCode(code=code, expires_at=expires.isoformat())

    def claim(
        self,
        code: str,
        *,
        device_name: str = "",
        device_kind: str = "macos",
        protocol_version: int = 1,
    ) -> tuple[RegisteredDevice, str]:
        """Atomically exchange a one-time code for a device token."""
        code_hash = _hash((code or "").strip())
        now = _now()
        token = secrets.token_urlsafe(32)
        device_id = f"mn4d_{secrets.token_urlsafe(12)}"
        token_hash = _hash(token)

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM mn4_pairing_codes WHERE code_hash = ?",
                (code_hash,),
            ).fetchone()
            if row is None or row["claimed_at"]:
                raise PairingCodeError("Unknown or already-used pairing code.")
            if datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
                raise PairingCodeError("Pairing code has expired.")

            active = conn.execute(
                """SELECT device_id FROM mn4_registered_devices
                   WHERE workspace_root = ? AND kb_name = ?
                     AND revoked_at IS NULL""",
                (row["workspace_root"], row["kb_name"]),
            ).fetchone()
            if active is not None:
                raise ActiveDeviceError("This MarginNote library already has an active device.")

            conn.execute(
                """INSERT INTO mn4_registered_devices
                   (device_id, owner_id, kb_name, workspace_root, device_name,
                    device_kind, token_hash, protocol_version, paired_at, last_seen)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    device_id,
                    row["owner_id"],
                    row["kb_name"],
                    row["workspace_root"],
                    device_name,
                    device_kind,
                    token_hash,
                    protocol_version,
                    now,
                    now,
                ),
            )
            conn.execute(
                """UPDATE mn4_pairing_codes
                   SET claimed_at = ?, device_id = ? WHERE code_hash = ?""",
                (now, device_id, code_hash),
            )

        return self._device(
            conn.execute(
                "SELECT * FROM mn4_registered_devices WHERE device_id = ?",
                (device_id,),
            ).fetchone()
        ), token

    def authenticate(self, token: str) -> RegisteredDevice:
        row = self._get_by_token(token)
        if row["revoked_at"]:
            raise PermissionError("MarginNote device has been revoked.")
        return self._device(row)

    def _get_by_token(self, token: str) -> sqlite3.Row:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM mn4_registered_devices WHERE token_hash = ?",
                (_hash((token or "").strip()),),
            ).fetchone()
        if row is None:
            raise PermissionError("Invalid MarginNote device token.")
        return row

    def list_devices(
        self, *, owner_id: str, kb_name: str, workspace_root: str
    ) -> list[RegisteredDevice]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM mn4_registered_devices
                   WHERE owner_id = ? AND kb_name = ? AND workspace_root = ?
                   ORDER BY paired_at DESC""",
                (owner_id, kb_name, str(Path(workspace_root).resolve())),
            ).fetchall()
        return [self._device(row) for row in rows]

    def revoke(self, *, owner_id: str, device_id: str, workspace_root: str) -> RegisteredDevice:
        now = _now()
        root = str(Path(workspace_root).resolve())
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM mn4_registered_devices
                   WHERE device_id = ? AND owner_id = ? AND workspace_root = ?""",
                (device_id, owner_id, root),
            ).fetchone()
            if row is None:
                raise KeyError("Device not found.")
            conn.execute(
                "UPDATE mn4_registered_devices SET revoked_at = ? WHERE device_id = ?",
                (now, device_id),
            )
            row = conn.execute(
                "SELECT * FROM mn4_registered_devices WHERE device_id = ?",
                (device_id,),
            ).fetchone()
        return self._device(row)

    def touch(self, device_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE mn4_registered_devices SET last_seen = ? WHERE device_id = ?",
                (_now(), device_id),
            )

    @staticmethod
    def _device(row: sqlite3.Row | Any) -> RegisteredDevice:
        return RegisteredDevice(
            device_id=row["device_id"],
            owner_id=row["owner_id"],
            kb_name=row["kb_name"],
            workspace_root=row["workspace_root"],
            device_name=row["device_name"],
            device_kind=row["device_kind"],
            protocol_version=int(row["protocol_version"]),
            paired_at=row["paired_at"],
            last_seen=row["last_seen"],
            revoked_at=row["revoked_at"] or "",
        )


__all__ = [
    "ActiveDeviceError",
    "MarginNoteDeviceRegistry",
    "PairingCodeError",
    "PairingCode",
    "RegisteredDevice",
]
