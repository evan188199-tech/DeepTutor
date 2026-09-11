"""Scoped, revocable credentials for LinguaWave mobile and MCP clients."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import sqlite3
import threading
from typing import Iterator

from deeptutor.multi_user import paths as user_paths

from .store import MediaStoreError, new_id, utc_now


MEDIA_SCOPES = frozenset(
    {"media:read", "playlist:read", "playlist:write", "subscription:write", "import:write"}
)
_TOKEN_KINDS = frozenset({"mcp", "mobile"})


@dataclass(frozen=True)
class MediaPrincipal:
    token_id: str
    owner_id: str
    scopes: frozenset[str]
    kind: str


class MediaAccessStore:
    """Global security store; raw bearer secrets are never persisted."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path or user_paths.SYSTEM_ROOT / "media" / "access.sqlite3")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS media_access_schema(version INTEGER NOT NULL);
                INSERT INTO media_access_schema(version)
                    SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM media_access_schema);
                CREATE TABLE IF NOT EXISTS media_access_tokens (
                    token_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    token_prefix TEXT NOT NULL,
                    token_kind TEXT NOT NULL,
                    scopes_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL DEFAULT '',
                    revoked_at TEXT NOT NULL DEFAULT '',
                    last_used_at TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_media_access_owner ON media_access_tokens(owner_id, token_kind, revoked_at);
                CREATE TABLE IF NOT EXISTS media_pairing_sessions (
                    pairing_id TEXT PRIMARY KEY,
                    code_hash TEXT NOT NULL,
                    owner_id TEXT NOT NULL DEFAULT '',
                    device_name TEXT NOT NULL DEFAULT '',
                    expires_at TEXT NOT NULL,
                    confirmed_at TEXT NOT NULL DEFAULT '',
                    exchanged_at TEXT NOT NULL DEFAULT ''
                );
                """
            )

    @staticmethod
    def _hash(raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_scopes(scopes: list[str]) -> list[str]:
        normalized = sorted({scope.strip() for scope in scopes if scope.strip()})
        invalid = set(normalized) - MEDIA_SCOPES
        if invalid:
            raise MediaStoreError(f"Unsupported media token scope: {sorted(invalid)[0]}")
        if not normalized:
            raise MediaStoreError("At least one media token scope is required.")
        return normalized

    def issue_token(
        self,
        *,
        owner_id: str,
        name: str,
        scopes: list[str],
        kind: str = "mcp",
        expires_in_days: int | None = None,
    ) -> tuple[dict[str, object], str]:
        if kind not in _TOKEN_KINDS:
            raise MediaStoreError("Unsupported media credential kind.")
        safe_scopes = self._validate_scopes(scopes)
        if not name.strip():
            raise MediaStoreError("Token name is required.")
        token_id = new_id("media_token")
        raw_token = f"lw_{kind}_{secrets.token_urlsafe(32)}"
        prefix = raw_token[:16]
        created_at = utc_now()
        expires_at = ""
        if expires_in_days is not None:
            expires_at = (datetime.now(timezone.utc) + timedelta(days=expires_in_days)).isoformat()
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO media_access_tokens(
                    token_id, owner_id, name, token_hash, token_prefix, token_kind,
                    scopes_json, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (token_id, owner_id, name.strip(), self._hash(raw_token), prefix, kind, json.dumps(safe_scopes), created_at, expires_at),
            )
        return (
            {
                "token_id": token_id, "name": name.strip(), "prefix": prefix,
                "scopes": safe_scopes, "created_at": created_at, "last_used_at": "",
            },
            raw_token,
        )

    def list_tokens(self, owner_id: str, *, kind: str | None = None) -> list[dict[str, object]]:
        clauses = ["owner_id = ?", "revoked_at = ''"]
        values: list[object] = [owner_id]
        if kind:
            clauses.append("token_kind = ?")
            values.append(kind)
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM media_access_tokens WHERE {' AND '.join(clauses)} ORDER BY created_at DESC", values
            ).fetchall()
        return [
            {
                "token_id": str(row["token_id"]), "name": str(row["name"]),
                "prefix": str(row["token_prefix"]), "scopes": json.loads(str(row["scopes_json"])),
                "created_at": str(row["created_at"]), "last_used_at": str(row["last_used_at"]),
                "kind": str(row["token_kind"]),
            }
            for row in rows
        ]

    def revoke_token(self, owner_id: str, token_id: str) -> bool:
        with self._lock, self._connect() as conn:
            return bool(
                conn.execute(
                    "UPDATE media_access_tokens SET revoked_at = ? WHERE token_id = ? AND owner_id = ? AND revoked_at = ''",
                    (utc_now(), token_id, owner_id),
                ).rowcount
            )

    def verify(self, raw_token: str, *, allowed_kinds: set[str] | None = None) -> MediaPrincipal | None:
        if not raw_token.startswith("lw_"):
            return None
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM media_access_tokens WHERE token_hash = ? AND revoked_at = ''",
                (self._hash(raw_token),),
            ).fetchone()
            if row is None:
                return None
            expected_hash = str(row["token_hash"])
            if not hmac.compare_digest(expected_hash, self._hash(raw_token)):
                return None
            kind = str(row["token_kind"])
            if allowed_kinds is not None and kind not in allowed_kinds:
                return None
            expires_at = str(row["expires_at"])
            if expires_at and expires_at <= utc_now():
                return None
            conn.execute("UPDATE media_access_tokens SET last_used_at = ? WHERE token_id = ?", (utc_now(), str(row["token_id"])))
        return MediaPrincipal(
            token_id=str(row["token_id"]), owner_id=str(row["owner_id"]),
            scopes=frozenset(json.loads(str(row["scopes_json"]))), kind=kind,
        )

    def create_pairing_session(self, *, device_name: str = "LinguaWave") -> dict[str, str]:
        pairing_id = new_id("pair")
        code = secrets.token_urlsafe(24)
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO media_pairing_sessions(pairing_id, code_hash, device_name, expires_at) VALUES (?, ?, ?, ?)",
                (pairing_id, self._hash(code), device_name.strip()[:80] or "LinguaWave", expires_at),
            )
        return {"pairing_id": pairing_id, "pairing_code": code, "expires_at": expires_at}

    def confirm_pairing(self, pairing_id: str, pairing_code: str, *, owner_id: str) -> dict[str, str]:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM media_pairing_sessions WHERE pairing_id = ?", (pairing_id,)).fetchone()
            if row is None or str(row["expires_at"]) <= utc_now():
                raise MediaStoreError("Pairing session is missing or expired.")
            if not hmac.compare_digest(str(row["code_hash"]), self._hash(pairing_code)):
                raise MediaStoreError("Pairing code is invalid.")
            if str(row["owner_id"]) and str(row["owner_id"]) != owner_id:
                raise MediaStoreError("Pairing session belongs to another account.")
            conn.execute(
                "UPDATE media_pairing_sessions SET owner_id = ?, confirmed_at = ? WHERE pairing_id = ?",
                (owner_id, utc_now(), pairing_id),
            )
        return {"pairing_id": pairing_id, "status": "confirmed"}

    def exchange_pairing(self, pairing_id: str, pairing_code: str) -> tuple[dict[str, object], str]:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM media_pairing_sessions WHERE pairing_id = ?", (pairing_id,)).fetchone()
            if row is None or str(row["expires_at"]) <= utc_now():
                raise MediaStoreError("Pairing session is missing or expired.")
            if not hmac.compare_digest(str(row["code_hash"]), self._hash(pairing_code)):
                raise MediaStoreError("Pairing code is invalid.")
            if not str(row["confirmed_at"]) or not str(row["owner_id"]):
                raise MediaStoreError("Pairing has not been confirmed in DeepTutor yet.")
            if str(row["exchanged_at"]):
                raise MediaStoreError("Pairing code has already been exchanged.")
            owner_id = str(row["owner_id"])
            device_name = str(row["device_name"])
            conn.execute("UPDATE media_pairing_sessions SET exchanged_at = ? WHERE pairing_id = ?", (utc_now(), pairing_id))
        return self.issue_token(
            owner_id=owner_id,
            name=device_name,
            kind="mobile",
            scopes=["media:read", "playlist:read", "playlist:write", "subscription:write", "import:write"],
            expires_in_days=365,
        )


__all__ = ["MEDIA_SCOPES", "MediaAccessStore", "MediaPrincipal"]
