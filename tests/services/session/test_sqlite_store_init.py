"""Initialization, upgrade and fallback coverage for the SQLite session store.

Focus areas (kept deliberately disjoint from ``test_sqlite_store.py``,
``test_pocketbase_isolation.py`` and ``test_history_search.py``):

- fresh-database DDL completeness and reopen idempotency,
- upgrade of a pre-preferences legacy schema (column additions, parent
  backfill, legacy ``kind`` cleanup),
- the swallowed ``ALTER TABLE ... DROP COLUMN`` failure branch in
  ``_initialize`` (DT-22, MEDIUM): the store must stay usable even when the
  legacy column cannot be dropped,
- session CRUD read-back and ``list_sessions`` limit/offset pagination.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from pathlib import Path
import sqlite3

from deeptutor.services.session.sqlite_store import SQLiteSessionStore

CORE_TABLES = (
    "sessions",
    "messages",
    "turns",
    "turn_events",
    "notebook_entries",
    "assessment_attempts",
    "reading_quiz_pending",
    "reading_quiz_rewards",
    "notebook_categories",
    "notebook_entry_categories",
)

CORE_INDEXES = (
    "idx_messages_session_created",
    "idx_messages_parent",
    "idx_sessions_updated_at",
    "idx_turns_session_updated",
    "idx_turn_events_turn_seq",
)


def _table_names(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _index_names(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}


def _column_names(db_path: Path, table: str) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _make_legacy_db(db_path: Path) -> None:
    """Create a pre-preferences schema: sessions still carry ``kind`` and
    messages predate ``metadata_json`` / ``parent_message_id``."""
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
        conn.executemany(
            "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            [
                ("legacy-1", "user", "first question", now),
                ("legacy-1", "assistant", "first answer", now),
                ("legacy-1", "user", "second question", now),
            ],
        )


class _DropColumnBlockedConnection:
    """Delegate to a real connection but fail ``DROP COLUMN`` statements the
    way an old SQLite build (without ALTER TABLE DROP COLUMN support) does."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def execute(self, sql: str, parameters: tuple = ()) -> sqlite3.Cursor:
        if "DROP COLUMN" in sql.upper():
            raise sqlite3.OperationalError('near "DROP": syntax error')
        return self._conn.execute(sql, parameters)

    def __getattr__(self, name: str):
        return getattr(self._conn, name)

    def __enter__(self) -> "_DropColumnBlockedConnection":
        self._conn.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return bool(self._conn.__exit__(exc_type, exc, tb))


@contextmanager
def _old_sqlite_connect(self):
    conn = sqlite3.connect(self.db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    try:
        with conn:
            yield _DropColumnBlockedConnection(conn)
    finally:
        conn.close()


# Risk: fresh-install DDL completeness — a brand-new database must expose
# every table/index/column later code paths rely on, and reopening must be
# non-destructive.
def test_fresh_db_builds_full_schema_and_reopens_without_loss(tmp_path: Path) -> None:
    db_path = tmp_path / "fresh.db"
    store = SQLiteSessionStore(db_path=db_path)
    asyncio.run(store.create_session(title="Survivor", session_id="fresh-1"))

    tables = _table_names(db_path)
    for table in CORE_TABLES:
        assert table in tables
    indexes = _index_names(db_path)
    for index in CORE_INDEXES:
        assert index in indexes
    session_columns = _column_names(db_path, "sessions")
    assert {"preferences_json", "deleted_at"} <= session_columns
    message_columns = _column_names(db_path, "messages")
    assert {"metadata_json", "parent_message_id"} <= message_columns
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"

    reopened = SQLiteSessionStore(db_path=db_path)
    survivor = asyncio.run(reopened.get_session("fresh-1"))
    assert survivor is not None
    assert survivor["title"] == "Survivor"


# Risk: legacy-schema upgrade — databases created before the preferences /
# soft-delete / branching eras must be upgraded in place: new columns appear,
# the obsolete ``kind`` column is removed, and existing messages get a
# connected ``parent_message_id`` chain without losing data.
def test_upgrade_adds_columns_backfills_parents_and_drops_kind(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    _make_legacy_db(db_path)

    store = SQLiteSessionStore(db_path=db_path)

    session_columns = _column_names(db_path, "sessions")
    assert {"preferences_json", "deleted_at"} <= session_columns
    assert "kind" not in session_columns
    message_columns = _column_names(db_path, "messages")
    assert {"metadata_json", "parent_message_id"} <= message_columns

    session = asyncio.run(store.get_session("legacy-1"))
    assert session is not None
    assert session["title"] == "Legacy"
    assert session["preferences"] == {}

    messages = asyncio.run(store.get_messages("legacy-1"))
    assert [m["content"] for m in messages] == [
        "first question",
        "first answer",
        "second question",
    ]
    assert messages[0]["parent_message_id"] is None
    assert messages[1]["parent_message_id"] == messages[0]["id"]
    assert messages[2]["parent_message_id"] == messages[1]["id"]
    assert all(m["metadata"] == {} for m in messages)

    reopened = SQLiteSessionStore(db_path=db_path)
    assert asyncio.run(reopened.get_session("legacy-1")) is not None


# Risk: DT-22 (MEDIUM, sqlite_store.py `_initialize`) — the
# ``ALTER TABLE sessions DROP COLUMN kind`` failure is swallowed, so the
# upgrade must still complete and leave a fully usable store even though the
# legacy column survives.
def test_initialize_survives_drop_column_failure_and_stays_usable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "legacy-strict-sqlite.db"
    _make_legacy_db(db_path)

    monkeypatch.setattr(SQLiteSessionStore, "_connect", _old_sqlite_connect)
    store = SQLiteSessionStore(db_path=db_path)
    monkeypatch.undo()

    session_columns = _column_names(db_path, "sessions")
    assert "kind" in session_columns  # drop skipped, not fatal
    assert {"preferences_json", "deleted_at"} <= session_columns
    message_columns = _column_names(db_path, "messages")
    assert {"metadata_json", "parent_message_id"} <= message_columns

    reopened = SQLiteSessionStore(db_path=db_path)
    created = asyncio.run(reopened.create_session(title="After fallback", session_id="post-dt22"))
    assert created["id"] == "post-dt22"
    loaded = asyncio.run(reopened.get_session("post-dt22"))
    assert loaded is not None
    assert loaded["title"] == "After fallback"
    assert asyncio.run(reopened.list_sessions(limit=10, offset=0))[0]["id"] == "post-dt22"


# Risk: session CRUD read-back — create/get/message-append/title-update/delete
# must round-trip values (preferences, metadata, parent chaining) and report
# misses instead of raising.
def test_session_crud_roundtrip_and_message_readback(tmp_path: Path) -> None:
    store = SQLiteSessionStore(db_path=tmp_path / "crud.db")

    created = asyncio.run(store.create_session(title="  Padded  ", session_id="crud-1"))
    assert created["title"] == "Padded"

    session = asyncio.run(store.get_session("crud-1"))
    assert session is not None
    assert session["status"] == "idle"
    assert session["active_turn_id"] == ""
    assert isinstance(session["preferences"], dict)

    first_id = asyncio.run(
        store.add_message("crud-1", "user", "hello", metadata={"origin": "test"})
    )
    second_id = asyncio.run(store.add_message("crud-1", "assistant", "hi there"))
    messages = asyncio.run(store.get_messages("crud-1"))
    assert [m["id"] for m in messages] == [first_id, second_id]
    assert messages[0]["parent_message_id"] is None
    assert messages[1]["parent_message_id"] == first_id
    assert messages[0]["metadata"] == {"origin": "test"}

    assert asyncio.run(store.update_session_title("crud-1", "Renamed")) is True
    assert asyncio.run(store.get_session("crud-1"))["title"] == "Renamed"
    assert asyncio.run(store.update_session_title("missing", "Renamed")) is False

    assert asyncio.run(store.delete_session("crud-1")) is True
    assert asyncio.run(store.get_session("crud-1")) is None
    assert asyncio.run(store.delete_session("crud-1")) is False


# Risk: list_sessions pagination read-back — limit/offset windows must be
# stable over the updated_at-descending order, recycled sessions must vanish
# from pages until restored, and a live session must not be purged by the
# recycle-bin-only hard delete.
def test_list_sessions_pagination_windows_and_recycle_bin(tmp_path: Path) -> None:
    db_path = tmp_path / "pager.db"
    store = SQLiteSessionStore(db_path=db_path)
    for index in range(1, 6):
        asyncio.run(store.create_session(title=f"S{index}", session_id=f"page-{index}"))
    asyncio.run(store.add_message("page-3", "user", "latest of page-3"))
    # Pin updated_at so the page order is deterministic regardless of timing.
    pinned = {"page-1": 500.0, "page-2": 400.0, "page-3": 300.0, "page-4": 200.0, "page-5": 100.0}
    with sqlite3.connect(db_path) as conn:
        for session_id, updated_at in pinned.items():
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?", (updated_at, session_id)
            )

    page_one = asyncio.run(store.list_sessions(limit=2, offset=0))
    page_two = asyncio.run(store.list_sessions(limit=2, offset=2))
    page_three = asyncio.run(store.list_sessions(limit=2, offset=4))
    beyond = asyncio.run(store.list_sessions(limit=2, offset=5))
    assert [s["id"] for s in page_one] == ["page-1", "page-2"]
    assert [s["id"] for s in page_two] == ["page-3", "page-4"]
    assert [s["id"] for s in page_three] == ["page-5"]
    assert beyond == []
    assert page_two[0]["message_count"] == 1
    assert page_two[0]["last_message"] == "latest of page-3"

    assert asyncio.run(store.soft_delete_session("page-1")) is True
    shrunk = asyncio.run(store.list_sessions(limit=2, offset=0))
    assert [s["id"] for s in shrunk] == ["page-2", "page-3"]

    assert asyncio.run(store.hard_delete_session("page-2")) is False  # recycle bin only
    assert asyncio.run(store.restore_session("page-1")) is True
    restored = asyncio.run(store.list_sessions(limit=1, offset=0))
    assert [s["id"] for s in restored] == ["page-1"]

    assert asyncio.run(store.soft_delete_session("page-1")) is True
    assert asyncio.run(store.hard_delete_session("page-1")) is True
    assert all(s["id"] != "page-1" for s in asyncio.run(store.list_sessions(limit=50, offset=0)))
