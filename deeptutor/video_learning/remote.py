"""SQLite storage for one-time renderer credentials and live playback state."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
from typing import Any

from deeptutor.multi_user.paths import SYSTEM_ROOT
from deeptutor.video_learning.models import (
    Device,
    DeviceCommand,
    PlayerCommand,
    PlayerSession,
)

BOOTSTRAP_TTL = timedelta(minutes=5)
SESSION_OFFLINE_AFTER = timedelta(seconds=15)
COMMAND_TTL = timedelta(seconds=30)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    bootstrap_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    device_name TEXT NOT NULL DEFAULT '',
    device_kind TEXT NOT NULL DEFAULT 'renderer',
    workspace_root TEXT NOT NULL DEFAULT '',
    token_hash TEXT NOT NULL,
    paired_at TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_remote_devices_owner ON devices(owner_id);
CREATE TABLE IF NOT EXISTS renderer_bootstraps (
    bootstrap_id TEXT PRIMARY KEY,
    ticket_hash TEXT NOT NULL UNIQUE,
    owner_id TEXT NOT NULL,
    username TEXT NOT NULL,
    role TEXT NOT NULL,
    token_user_id TEXT NOT NULL DEFAULT '',
    device_name TEXT NOT NULL DEFAULT 'Renderer',
    device_kind TEXT NOT NULL DEFAULT 'renderer',
    renderer_origin TEXT NOT NULL DEFAULT '',
    workspace_root TEXT NOT NULL DEFAULT '',
    material_id TEXT NOT NULL DEFAULT '',
    video_id TEXT NOT NULL DEFAULT '',
    position_ms INTEGER NOT NULL DEFAULT 0,
    expires_at TEXT NOT NULL,
    redeemed_at TEXT
);
CREATE TABLE IF NOT EXISTS renderer_material_bindings (
    device_id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    material_id TEXT NOT NULL,
    video_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS device_commands (
    command_id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    command_type TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    acked_at TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_remote_device_commands
ON device_commands(device_id, status, created_at);
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    instance_origin TEXT NOT NULL DEFAULT '',
    video_id TEXT NOT NULL,
    material_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    position_ms INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    playback_state TEXT NOT NULL DEFAULT 'unknown',
    playback_rate REAL NOT NULL DEFAULT 1.0,
    controller_token_hash TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    last_heartbeat_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_remote_sessions_owner ON sessions(owner_id);
CREATE INDEX IF NOT EXISTS idx_remote_sessions_device ON sessions(device_id);
CREATE TABLE IF NOT EXISTS commands (
    command_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    command_type TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    acked_at TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_remote_commands_session
ON commands(session_id, status, created_at);
"""


class RemoteControlError(RuntimeError):
    """A user-facing remote-control failure."""


class RemoteControlNotFound(RemoteControlError):
    """The requested remote-control record was not found."""


class RemoteControlConflict(RemoteControlError):
    """The requested remote-control transition is invalid."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(now: datetime | None = None) -> str:
    return (now or utcnow()).isoformat()


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def default_remote_db_path() -> Path:
    return SYSTEM_ROOT / "video_learning" / "remote.db"


class RemoteControlStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @classmethod
    def open_existing(cls, db_path: str | Path) -> RemoteControlStore | None:
        return cls(db_path) if Path(db_path).is_file() else None

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @staticmethod
    def _device(row: sqlite3.Row) -> Device:
        return Device(
            device_id=row["device_id"],
            owner_id=row["owner_id"],
            device_name=row["device_name"],
            device_kind=row["device_kind"],
            paired_at=row["paired_at"],
            last_seen=row["last_seen"],
            workspace_root=str(row["workspace_root"] or ""),
            active=bool(row["active"]),
        )

    @staticmethod
    def _session(row: sqlite3.Row) -> PlayerSession:
        return PlayerSession(
            session_id=row["session_id"],
            owner_id=row["owner_id"],
            device_id=row["device_id"],
            instance_origin=row["instance_origin"],
            video_id=row["video_id"],
            title=row["title"],
            position_ms=int(row["position_ms"]),
            duration_ms=int(row["duration_ms"]),
            playback_state=row["playback_state"],  # type: ignore[arg-type]
            playback_rate=float(row["playback_rate"]),
            updated_at=row["updated_at"],
            last_heartbeat_at=row["last_heartbeat_at"],
            controller_token_hash=str(row["controller_token_hash"] or ""),
            material_id=str(row["material_id"] or ""),
        )

    @staticmethod
    def _command(row: sqlite3.Row) -> PlayerCommand:
        return PlayerCommand(
            command_id=row["command_id"],
            session_id=row["session_id"],
            owner_id=row["owner_id"],
            device_id=row["device_id"],
            command_type=row["command_type"],
            payload=json.loads(row["payload"] or "{}"),
            status=row["status"],  # type: ignore[arg-type]
            created_at=row["created_at"],
            acked_at=row["acked_at"],
            error=row["error"],
        )

    @staticmethod
    def _device_command(row: sqlite3.Row) -> DeviceCommand:
        return DeviceCommand(
            command_id=row["command_id"],
            owner_id=row["owner_id"],
            device_id=row["device_id"],
            command_type=row["command_type"],
            payload=json.loads(row["payload"] or "{}"),
            status=row["status"],  # type: ignore[arg-type]
            created_at=row["created_at"],
            acked_at=row["acked_at"],
            error=row["error"],
        )

    def create_bootstrap(
        self,
        *,
        owner_id: str,
        username: str,
        role: str,
        token_user_id: str,
        device_name: str,
        device_kind: str,
        workspace_root: str,
        renderer_origin: str,
        material_id: str = "",
        video_id: str = "",
        position_ms: int = 0,
    ) -> tuple[str, str, str]:
        bootstrap_id = secrets.token_urlsafe(12)
        ticket = secrets.token_urlsafe(32)
        expires_at = _iso(utcnow() + BOOTSTRAP_TTL)
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO renderer_bootstraps
                   (bootstrap_id, ticket_hash, owner_id, username, role, token_user_id,
                    device_name, device_kind, workspace_root, renderer_origin, material_id, video_id,
                    position_ms, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    bootstrap_id,
                    _hash(ticket),
                    owner_id,
                    username,
                    role,
                    token_user_id,
                    device_name or "Renderer",
                    device_kind or "renderer",
                    workspace_root,
                    renderer_origin,
                    material_id,
                    video_id,
                    max(0, int(position_ms)),
                    expires_at,
                ),
            )
        return bootstrap_id, ticket, expires_at

    def redeem_bootstrap(self, ticket: str) -> tuple[Device, str, sqlite3.Row]:
        now = _iso()
        device_id = secrets.token_urlsafe(12)
        token = secrets.token_urlsafe(32)
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM renderer_bootstraps
                   WHERE ticket_hash = ? AND redeemed_at IS NULL""",
                (_hash(ticket),),
            ).fetchone()
            if row is None:
                raise RemoteControlNotFound("Renderer bootstrap ticket was not found.")
            if _parse_iso(row["expires_at"]) <= utcnow():
                conn.execute(
                    "UPDATE renderer_bootstraps SET redeemed_at = ? WHERE bootstrap_id = ?",
                    (now, row["bootstrap_id"]),
                )
                raise RemoteControlConflict("Renderer bootstrap ticket expired.")
            redeemed = conn.execute(
                """UPDATE renderer_bootstraps SET redeemed_at = ?
                   WHERE bootstrap_id = ? AND redeemed_at IS NULL""",
                (now, row["bootstrap_id"]),
            )
            if redeemed.rowcount != 1:
                raise RemoteControlConflict("Renderer bootstrap ticket already redeemed.")
            conn.execute(
                """INSERT INTO devices
                   (device_id, bootstrap_id, owner_id, device_name, device_kind, workspace_root, token_hash,
                    paired_at, last_seen, active)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (
                    device_id,
                    row["bootstrap_id"],
                    row["owner_id"],
                    row["device_name"],
                    row["device_kind"],
                    row["workspace_root"],
                    _hash(token),
                    now,
                    now,
                ),
            )
            if row["material_id"]:
                conn.execute(
                    """INSERT INTO renderer_material_bindings
                       (device_id, owner_id, material_id, video_id, created_at)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(device_id) DO UPDATE SET
                         owner_id = excluded.owner_id,
                         material_id = excluded.material_id,
                         video_id = excluded.video_id,
                         created_at = excluded.created_at""",
                    (device_id, row["owner_id"], row["material_id"], row["video_id"], now),
                )
            device = Device(
                device_id=device_id,
                owner_id=row["owner_id"],
                device_name=row["device_name"],
                device_kind=row["device_kind"],
                paired_at=now,
                last_seen=now,
                workspace_root=str(row["workspace_root"] or ""),
            )
        return device, token, row

    def verify_token(self, device_id: str, token: str) -> Device | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM devices WHERE device_id = ? AND active = 1",
                (device_id,),
            ).fetchone()
        if row is None:
            return None
        return self._device(row) if secrets.compare_digest(
            row["token_hash"], _hash(token)
        ) else None

    def touch_device(self, device_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE devices SET last_seen = ? WHERE device_id = ?",
                (_iso(), device_id),
            )

    def list_devices(self, owner_id: str) -> list[Device]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM devices WHERE owner_id = ? AND active = 1 ORDER BY paired_at DESC",
                (owner_id,),
            ).fetchall()
        return [self._device(row) for row in rows]

    def device_is_online(self, device: Device) -> bool:
        return device.active and utcnow() - _parse_iso(device.last_seen) <= SESSION_OFFLINE_AFTER

    def revoke_device(self, owner_id: str, device_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE devices SET active = 0 WHERE owner_id = ? AND device_id = ? AND active = 1",
                (owner_id, device_id),
            )
            return cursor.rowcount == 1

    def binding_for(self, owner_id: str, device_id: str) -> dict[str, str]:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT material_id, video_id FROM renderer_material_bindings
                   WHERE owner_id = ? AND device_id = ?""",
                (owner_id, device_id),
            ).fetchone()
        return dict(row) if row else {}

    def workspace_for_device(self, device_id: str) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT workspace_root FROM devices WHERE device_id = ?", (device_id,)
            ).fetchone()
        return str(row["workspace_root"] or "") if row else ""

    def upsert_session(
        self,
        *,
        device: Device,
        session_id: str | None,
        renderer_origin: str,
        video_id: str,
        title: str,
        position_ms: int,
        duration_ms: int,
        playback_state: str,
        playback_rate: float,
        material_id: str,
    ) -> PlayerSession:
        now = _iso()
        sid = session_id or secrets.token_urlsafe(12)
        with self._connect() as conn:
            existing = None
            if session_id:
                existing = conn.execute(
                    "SELECT session_id, video_id FROM sessions WHERE session_id = ? AND device_id = ?",
                    (session_id, device.device_id),
                ).fetchone()
            if existing is None:
                active = conn.execute(
                    """SELECT session_id, video_id FROM sessions
                       WHERE device_id = ? AND video_id = ? AND instance_origin = ?
                       ORDER BY last_heartbeat_at DESC LIMIT 1""",
                    (device.device_id, video_id, renderer_origin),
                ).fetchone()
                if active is not None:
                    sid = active["session_id"]
                    existing = active
            if existing is None:
                conn.execute(
                    """INSERT INTO sessions
                       (session_id, owner_id, device_id, instance_origin, video_id,
                        title, position_ms, duration_ms, playback_state, playback_rate,
                        updated_at, last_heartbeat_at, material_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        sid,
                        device.owner_id,
                        device.device_id,
                        renderer_origin,
                        video_id,
                        title,
                        max(0, int(position_ms)),
                        max(0, int(duration_ms)),
                        playback_state or "unknown",
                        min(4.0, max(0.25, float(playback_rate or 1.0))),
                        now,
                        now,
                        material_id,
                    ),
                )
            else:
                conn.execute(
                    """UPDATE sessions SET title = ?, position_ms = ?, duration_ms = ?,
                       video_id = ?, playback_state = ?, playback_rate = ?, material_id = ?,
                       updated_at = ?, last_heartbeat_at = ? WHERE session_id = ?""",
                    (
                        title,
                        max(0, int(position_ms)),
                        max(0, int(duration_ms)),
                        video_id,
                        playback_state or "unknown",
                        min(4.0, max(0.25, float(playback_rate or 1.0))),
                        material_id,
                        now,
                        now,
                        sid,
                    ),
                )
            conn.execute(
                """INSERT INTO renderer_material_bindings
                   (device_id, owner_id, material_id, video_id, created_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(device_id) DO UPDATE SET
                     owner_id = excluded.owner_id,
                     material_id = excluded.material_id,
                     video_id = excluded.video_id,
                     created_at = excluded.created_at""",
                (device.device_id, device.owner_id, material_id, video_id, now),
            )
            conn.execute(
                "UPDATE devices SET last_seen = ? WHERE device_id = ?",
                (now, device.device_id),
            )
            row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (sid,)).fetchone()
        return self._session(row)

    def list_sessions(self, owner_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sessions WHERE owner_id = ? ORDER BY last_heartbeat_at DESC",
                (owner_id,),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            session = self._session(row)
            serialized = asdict(session)
            serialized.pop("controller_token_hash", None)
            result.append({**serialized, "online": self.session_is_online(session)})
        return result

    def get_session(self, session_id: str, owner_id: str | None = None) -> PlayerSession | None:
        with self._connect() as conn:
            if owner_id is None:
                row = conn.execute(
                    "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM sessions WHERE session_id = ? AND owner_id = ?",
                    (session_id, owner_id),
                ).fetchone()
        return self._session(row) if row else None

    def latest_session(self, device_id: str) -> PlayerSession | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE device_id = ? ORDER BY last_heartbeat_at DESC LIMIT 1",
                (device_id,),
            ).fetchone()
        return self._session(row) if row else None

    def issue_controller(self, owner_id: str, session_id: str, secret: str) -> PlayerSession | None:
        if not secret:
            return None
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE sessions SET controller_token_hash = ? WHERE session_id = ? AND owner_id = ?",
                (_hash(secret), session_id, owner_id),
            )
            if cursor.rowcount != 1:
                return None
            row = conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return self._session(row) if row else None

    def verify_controller(self, owner_id: str, session_id: str, cookie: str | None) -> bool:
        if not cookie or ":" not in cookie:
            return False
        cookie_session_id, secret = cookie.split(":", 1)
        if cookie_session_id != session_id or not secret:
            return False
        with self._connect() as conn:
            row = conn.execute(
                "SELECT controller_token_hash FROM sessions WHERE session_id = ? AND owner_id = ?",
                (session_id, owner_id),
            ).fetchone()
        expected = str(row["controller_token_hash"] or "") if row else ""
        return bool(expected) and secrets.compare_digest(expected, _hash(secret))

    def session_is_online(self, session: PlayerSession) -> bool:
        return utcnow() - _parse_iso(session.last_heartbeat_at) <= SESSION_OFFLINE_AFTER

    def enqueue_device_command(
        self, *, owner_id: str, device_id: str, video_id: str
    ) -> DeviceCommand:
        device = next(
            (row for row in self.list_devices(owner_id) if row.device_id == device_id),
            None,
        )
        if device is None:
            raise RemoteControlNotFound("Renderer device was not found.")
        if not self.device_is_online(device):
            raise RemoteControlConflict("Renderer device is offline.")
        command_id, now = secrets.token_urlsafe(12), _iso()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO device_commands
                   (command_id, owner_id, device_id, command_type, payload, status, created_at)
                   VALUES (?, ?, ?, 'open_video', ?, 'pending', ?)""",
                (
                    command_id,
                    owner_id,
                    device_id,
                    json.dumps({"video_id": video_id}),
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM device_commands WHERE command_id = ?", (command_id,)
            ).fetchone()
        return self._device_command(row)

    def pending_device_commands(self, device_id: str) -> list[DeviceCommand]:
        cutoff = _iso(utcnow() - COMMAND_TTL)
        with self._connect() as conn:
            conn.execute(
                """UPDATE device_commands SET status = 'expired'
                   WHERE device_id = ? AND status = 'pending' AND created_at < ?""",
                (device_id, cutoff),
            )
            rows = conn.execute(
                """SELECT * FROM device_commands WHERE device_id = ? AND status = 'pending'
                   ORDER BY created_at""",
                (device_id,),
            ).fetchall()
        return [self._device_command(row) for row in rows]

    def get_device_command(
        self, owner_id: str, device_id: str, command_id: str
    ) -> DeviceCommand | None:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM device_commands
                   WHERE command_id = ? AND owner_id = ? AND device_id = ?""",
                (command_id, owner_id, device_id),
            ).fetchone()
        return self._device_command(row) if row else None

    def ack_device_command(
        self, device_id: str, command_id: str, ok: bool, error: str | None
    ) -> DeviceCommand:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM device_commands WHERE command_id = ? AND device_id = ?",
                (command_id, device_id),
            ).fetchone()
            if row is None:
                raise RemoteControlNotFound("Device command was not found.")
            conn.execute(
                """UPDATE device_commands SET status = ?, acked_at = ?, error = ?
                   WHERE command_id = ?""",
                ("acked" if ok else "failed", _iso(), error, command_id),
            )
            row = conn.execute(
                "SELECT * FROM device_commands WHERE command_id = ?", (command_id,)
            ).fetchone()
        return self._device_command(row)

    def enqueue_command(
        self,
        *,
        session: PlayerSession,
        command_type: str,
        payload: dict[str, Any],
        command_id: str | None = None,
    ) -> PlayerCommand:
        allowed = {"pause", "play", "seek", "volume", "mute", "playback_rate", "fullscreen"}
        if command_type not in allowed:
            raise RemoteControlConflict(f"Unsupported command type: {command_type}")
        if not self.session_is_online(session):
            raise RemoteControlConflict("Player session is offline.")
        cid = command_id or secrets.token_urlsafe(12)
        now = _iso()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT * FROM commands WHERE command_id = ?", (cid,)
            ).fetchone()
            if existing is not None:
                return self._command(existing)
            conn.execute(
                """INSERT INTO commands
                   (command_id, session_id, owner_id, device_id, command_type,
                    payload, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)""",
                (
                    cid,
                    session.session_id,
                    session.owner_id,
                    session.device_id,
                    command_type,
                    json.dumps(payload),
                    now,
                ),
            )
            row = conn.execute("SELECT * FROM commands WHERE command_id = ?", (cid,)).fetchone()
        return self._command(row)

    def pending_commands(
        self, device_id: str, session_id: str | None = None
    ) -> list[PlayerCommand]:
        cutoff = _iso(utcnow() - COMMAND_TTL)
        with self._connect() as conn:
            conn.execute(
                """UPDATE commands SET status = 'expired'
                   WHERE device_id = ? AND status = 'pending' AND created_at < ?""",
                (device_id, cutoff),
            )
            if session_id:
                rows = conn.execute(
                    """SELECT * FROM commands
                       WHERE device_id = ? AND session_id = ? AND status = 'pending'
                       ORDER BY created_at""",
                    (device_id, session_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM commands WHERE device_id = ? AND status = 'pending'
                       ORDER BY created_at""",
                    (device_id,),
                ).fetchall()
        return [self._command(row) for row in rows]

    def ack_command(
        self, device_id: str, command_id: str, ok: bool, error: str | None
    ) -> PlayerCommand:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM commands WHERE command_id = ? AND device_id = ?",
                (command_id, device_id),
            ).fetchone()
            if row is None:
                raise RemoteControlNotFound("Player command was not found.")
            if row["status"] not in {"acked", "failed"}:
                conn.execute(
                    """UPDATE commands SET status = ?, acked_at = ?, error = ?
                       WHERE command_id = ?""",
                    ("acked" if ok else "failed", _iso(), error, command_id),
                )
            row = conn.execute(
                "SELECT * FROM commands WHERE command_id = ?", (command_id,)
            ).fetchone()
        return self._command(row)

    def get_command(self, command_id: str, owner_id: str) -> PlayerCommand | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM commands WHERE command_id = ? AND owner_id = ?",
                (command_id, owner_id),
            ).fetchone()
        return self._command(row) if row else None


__all__ = [
    "BOOTSTRAP_TTL",
    "COMMAND_TTL",
    "RemoteControlConflict",
    "RemoteControlError",
    "RemoteControlNotFound",
    "RemoteControlStore",
    "SESSION_OFFLINE_AFTER",
    "default_remote_db_path",
]
