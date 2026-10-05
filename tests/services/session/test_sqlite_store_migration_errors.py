"""Regression tests for the ``sessions.kind`` drop migration error handling.

DT-22 (MEDIUM, ``sqlite_store.py`` ``_initialize``): the
``ALTER TABLE sessions DROP COLUMN kind`` statement wrapped its
``OperationalError`` in a bare ``pass``, so a tolerable failure (old SQLite
build without DROP COLUMN support, or the column already gone) and a real
migration failure (locked DB, disk error, ...) were indistinguishable and
neither produced a log line.

These tests pin the two paths separately:

- tolerable failures keep the store usable and idempotent across reopens,
- any other ``OperationalError`` is logged and re-raised so startup fails
  loudly instead of silently drifting.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from pathlib import Path
import sqlite3

import pytest

from deeptutor.services.session.sqlite_store import SQLiteSessionStore

DROP_KIND_SQL = "ALTER TABLE sessions DROP COLUMN kind"


def _make_legacy_db(db_path: Path) -> None:
    """Pre-preferences schema whose ``sessions`` table still has ``kind``."""
    now = 1_000.0
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT 'New conversation',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                compressed_summary TEXT DEFAULT '',
                summary_up_to_msg_id INTEGER DEFAULT 0,
                kind TEXT DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                capability TEXT DEFAULT '',
                events_json TEXT DEFAULT '',
                attachments_json TEXT DEFAULT '',
                created_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at, kind) "
            "VALUES ('legacy-1', 'Legacy', ?, ?, 'chat')",
            (now, now),
        )


class _FailingDropConnection:
    """Proxy a real connection but make ``DROP COLUMN`` fail with a chosen error."""

    def __init__(self, conn: sqlite3.Connection, error: sqlite3.OperationalError) -> None:
        self._conn = conn
        self._error = error

    def execute(self, sql: str, parameters: tuple = ()) -> sqlite3.Cursor:
        if "DROP COLUMN" in sql.upper():
            raise self._error
        return self._conn.execute(sql, parameters)

    def __getattr__(self, name: str):
        return getattr(self._conn, name)

    def __enter__(self) -> "_FailingDropConnection":
        self._conn.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return bool(self._conn.__exit__(exc_type, exc, tb))


def _patch_drop_failure(monkeypatch, error: sqlite3.OperationalError) -> None:
    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        try:
            with conn:
                yield _FailingDropConnection(conn, error)
        finally:
            conn.close()

    monkeypatch.setattr(SQLiteSessionStore, "_connect", _connect)


def test_tolerable_drop_failures_keep_store_usable_and_idempotent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # Old SQLite builds reject the statement with a syntax error near DROP;
    # either way the app never reads the legacy column again, so startup must
    # succeed and reopening must not regress.
    _patch_drop_failure(monkeypatch, sqlite3.OperationalError('near "DROP": syntax error'))
    db_path = tmp_path / "legacy-old-sqlite.db"
    _make_legacy_db(db_path)

    store = SQLiteSessionStore(db_path=db_path)
    monkeypatch.undo()
    asyncio.run(store.create_session(title="Usable", session_id="s1"))

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
    assert "kind" in columns  # column survives, but the store stays functional

    reopened = SQLiteSessionStore(db_path=db_path)
    assert asyncio.run(reopened.get_session("s1")) is not None


def test_missing_kind_column_error_is_tolerated(tmp_path: Path, monkeypatch) -> None:
    # A concurrent migration (or a partially-applied earlier run) can drop the
    # column between the PRAGMA read and the ALTER: that "no such column"
    # outcome is the desired end state, not a failure.
    _patch_drop_failure(monkeypatch, sqlite3.OperationalError("no such column: kind"))
    db_path = tmp_path / "legacy-race.db"
    _make_legacy_db(db_path)

    store = SQLiteSessionStore(db_path=db_path)
    monkeypatch.undo()
    assert asyncio.run(store.get_session("legacy-1")) is not None


def test_real_drop_failure_is_logged_and_raised(tmp_path: Path, monkeypatch, caplog) -> None:
    # Anything that is not a known-tolerable outcome (old build / column
    # already gone) is a real migration failure: it must be logged and
    # propagate so startup fails loudly instead of silently drifting.
    import logging

    _patch_drop_failure(monkeypatch, sqlite3.OperationalError("database is locked"))
    db_path = tmp_path / "legacy-locked.db"
    _make_legacy_db(db_path)

    with caplog.at_level(logging.ERROR, logger="deeptutor.services.session.sqlite_store"):
        with pytest.raises(sqlite3.OperationalError, match="database is locked"):
            SQLiteSessionStore(db_path=db_path)

    drop_logs = [
        record
        for record in caplog.records
        if "kind" in record.getMessage() or "DROP COLUMN" in record.getMessage()
    ]
    assert drop_logs, "real migration failure must leave an error log"
    assert any(record.levelno == logging.ERROR for record in drop_logs)
