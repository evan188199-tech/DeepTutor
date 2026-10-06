"""Focused tests for the lossless SQLite conversation transfer."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.workspace.models import WorkspaceError
from deeptutor.services.workspace.session_transfer import transfer_sessions
from tests.services.workspace.test_data_scope import account as account

WS_ID = "ws-target"


def _prepare(path: Path) -> SQLiteSessionStore:
    return SQLiteSessionStore(path)


def _seed_conversation(db: Path, session_id: str = "sess-a") -> None:
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at, preferences_json)"
            " VALUES (?, 'Seed conversation', 1.0, 2.0, ?)",
            (session_id, json.dumps({"theme": "dark"})),
        )
        conn.execute(
            "INSERT INTO messages (id, session_id, role, content, created_at, parent_message_id)"
            " VALUES (?, ?, 'user', ?, 1.0, NULL)",
            (5, session_id, "Read /files/attachments/sess-a/doc_notes.txt please"),
        )
        conn.execute(
            "INSERT INTO messages (id, session_id, role, content, created_at, parent_message_id)"
            " VALUES (?, ?, 'assistant', ?, 2.0, 5)",
            (7, session_id, "See /api/reading/material-m.pdf?page=3 for the citation"),
        )
        conn.execute(
            "INSERT INTO turns (id, session_id, status, created_at, updated_at,"
            " assistant_message_id) VALUES ('turn-a', ?, 'completed', 1.0, 3.0, 7)",
            (session_id,),
        )
        conn.execute(
            "INSERT INTO turn_events (id, turn_id, seq, type, timestamp, created_at)"
            " VALUES (11, 'turn-a', 3, 'token', 1.5, 1.5)"
        )
        conn.execute(
            "INSERT INTO notebook_categories (id, name, created_at) VALUES (1, 'Review', 1.0)"
        )
        conn.execute(
            "INSERT INTO notebook_entries (id, session_id, origin_ref, question_id, question,"
            " created_at, updated_at) VALUES (9, ?, 'book/one', 'question-one', 'Keep this',"
            " 1.0, 2.0)",
            (session_id,),
        )
        conn.execute("INSERT INTO notebook_entry_categories (entry_id, category_id) VALUES (9, 1)")
        conn.execute(
            "INSERT INTO assessment_attempts (attempt_id, notebook_entry_id, session_id,"
            " origin_ref, question_id, source, assessment_type, result, occurred_at,"
            " assessment_json) VALUES ('attempt-a', 9, ?, 'book/one', 'question-one',"
            " 'deep_question', 'quiz', 'correct', 2.5, '{}')",
            (session_id,),
        )


def _rows(db: Path, sql: str) -> list[tuple]:
    with sqlite3.connect(db) as conn:
        return conn.execute(sql).fetchall()


def test_transfer_round_trip_preserves_ids_references_and_rebinds_urls(account, tmp_path):
    source = _prepare(tmp_path / "src.db")
    destination = _prepare(tmp_path / "dst.db")
    _seed_conversation(source.db_path)

    assert transfer_sessions(source.db_path, destination.db_path, ["sess-a"], WS_ID) == 1

    prefs = json.loads(_rows(destination.db_path, "SELECT preferences_json FROM sessions")[0][0])
    assert prefs["workspace_id"] == WS_ID
    assert prefs["theme"] == "dark"
    messages = _rows(
        destination.db_path, "SELECT id, parent_message_id, content FROM messages ORDER BY id"
    )
    assert [row[0] for row in messages] == [5, 7]
    assert [row[1] for row in messages] == [None, 5]
    assert "dt_workspace=" + WS_ID in messages[0][2]
    assert "dt_workspace=" + WS_ID in messages[1][2]
    assert _rows(
        destination.db_path, "SELECT assistant_message_id FROM turns WHERE id = 'turn-a'"
    ) == [(7,)]
    assert _rows(destination.db_path, "SELECT turn_id, seq FROM turn_events") == [("turn-a", 3)]
    assert _rows(destination.db_path, "SELECT id, session_id FROM notebook_entries") == [
        (9, "sess-a")
    ]
    assert _rows(
        destination.db_path, "SELECT entry_id, category_id FROM notebook_entry_categories"
    ) == [(9, 1)]
    assert _rows(
        destination.db_path,
        "SELECT attempt_id, notebook_entry_id, session_id FROM assessment_attempts",
    ) == [("attempt-a", 9, "sess-a")]
    for table in ("sessions", "messages", "turns", "turn_events", "notebook_entries"):
        assert _rows(source.db_path, f"SELECT count(*) FROM {table}") == [(0,)]


def test_transfer_leaves_unrelated_destination_rows_alone(account, tmp_path):
    source = _prepare(tmp_path / "src.db")
    destination = _prepare(tmp_path / "dst.db")
    _seed_conversation(source.db_path, "sess-move")
    with sqlite3.connect(destination.db_path) as conn:
        conn.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at, preferences_json)"
            " VALUES ('sess-keep', 'Stays', 1.0, 1.0, '{}')"
        )
        conn.execute(
            "INSERT INTO reading_quiz_pending (material_id, locator, question_id, question_json,"
            " created_at) VALUES ('mat', 1, 'q', '{}', 1.0)"
        )

    assert transfer_sessions(source.db_path, destination.db_path, ["sess-move"], WS_ID) == 1

    assert _rows(destination.db_path, "SELECT id FROM sessions ORDER BY id") == [
        ("sess-keep",),
        ("sess-move",),
    ]
    assert _rows(destination.db_path, "SELECT material_id FROM reading_quiz_pending") == [("mat",)]


def test_identical_destination_category_is_deduplicated(account, tmp_path):
    source = _prepare(tmp_path / "src.db")
    destination = _prepare(tmp_path / "dst.db")
    _seed_conversation(source.db_path)
    with sqlite3.connect(destination.db_path) as conn:
        conn.execute(
            "INSERT INTO notebook_categories (id, name, created_at) VALUES (1, 'Review', 1.0)"
        )

    assert transfer_sessions(source.db_path, destination.db_path, ["sess-a"], WS_ID) == 1

    assert _rows(destination.db_path, "SELECT count(*) FROM notebook_categories") == [(1,)]
    assert _rows(
        destination.db_path, "SELECT entry_id, category_id FROM notebook_entry_categories"
    ) == [(9, 1)]


def test_active_turn_refuses_transfer_without_changes(account, tmp_path):
    source = _prepare(tmp_path / "src.db")
    destination = _prepare(tmp_path / "dst.db")
    _seed_conversation(source.db_path)
    with sqlite3.connect(source.db_path) as conn:
        conn.execute("UPDATE turns SET status = 'running'")

    with pytest.raises(WorkspaceError, match="active"):
        transfer_sessions(source.db_path, destination.db_path, ["sess-a"], WS_ID)

    assert _rows(source.db_path, "SELECT count(*) FROM sessions") == [(1,)]
    assert _rows(source.db_path, "SELECT count(*) FROM messages") == [(2,)]
    assert _rows(destination.db_path, "SELECT count(*) FROM sessions") == [(0,)]


def test_conflicting_destination_ids_refuse_without_changes(account, tmp_path):
    source = _prepare(tmp_path / "src.db")
    destination = _prepare(tmp_path / "dst.db")
    _seed_conversation(source.db_path)
    with sqlite3.connect(destination.db_path) as conn:
        conn.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at, preferences_json)"
            " VALUES ('sess-a', 'Existing', 1.0, 1.0, '{}')"
        )

    with pytest.raises(WorkspaceError, match="conflicting"):
        transfer_sessions(source.db_path, destination.db_path, ["sess-a"], WS_ID)

    assert _rows(destination.db_path, "SELECT title FROM sessions") == [("Existing",)]
    assert _rows(destination.db_path, "SELECT count(*) FROM messages") == [(0,)]
    assert _rows(source.db_path, "SELECT count(*) FROM sessions") == [(1,)]
    assert _rows(source.db_path, "SELECT count(*) FROM messages") == [(2,)]


def test_missing_selected_session_aborts_without_partial_copy(account, tmp_path):
    source = _prepare(tmp_path / "src.db")
    destination = _prepare(tmp_path / "dst.db")
    _seed_conversation(source.db_path)

    with pytest.raises(WorkspaceError, match="could not be verified"):
        transfer_sessions(source.db_path, destination.db_path, ["sess-a", "sess-missing"], WS_ID)

    assert _rows(source.db_path, "SELECT count(*) FROM sessions") == [(1,)]
    assert _rows(source.db_path, "SELECT count(*) FROM messages") == [(2,)]
    assert _rows(destination.db_path, "SELECT count(*) FROM sessions") == [(0,)]
    assert _rows(destination.db_path, "SELECT count(*) FROM messages") == [(0,)]


def test_empty_selection_or_same_path_is_a_noop(account, tmp_path):
    source = _prepare(tmp_path / "src.db")
    destination = tmp_path / "fresh.db"
    _seed_conversation(source.db_path)

    assert transfer_sessions(source.db_path, source.db_path, ["sess-a"], WS_ID) == 0
    assert transfer_sessions(source.db_path, destination, [], WS_ID) == 0
    assert not destination.exists()
    assert _rows(source.db_path, "SELECT count(*) FROM sessions") == [(1,)]


def test_corrupt_destination_database_is_rejected(account, tmp_path):
    source = _prepare(tmp_path / "src.db")
    destination = tmp_path / "garbage.db"
    _seed_conversation(source.db_path)
    destination.write_bytes(b"not a sqlite database" * 64)

    with pytest.raises(sqlite3.DatabaseError):
        transfer_sessions(source.db_path, destination, ["sess-a"], WS_ID)

    assert _rows(source.db_path, "SELECT count(*) FROM sessions") == [(1,)]


def test_failed_row_verification_rolls_back_both_databases(account, tmp_path):
    source = _prepare(tmp_path / "src.db")
    destination = _prepare(tmp_path / "dst.db")
    _seed_conversation(source.db_path)
    with sqlite3.connect(destination.db_path) as conn:
        conn.execute(
            "CREATE TRIGGER tamper_messages AFTER INSERT ON messages"
            " BEGIN UPDATE messages SET content = 'tampered' WHERE id = NEW.id; END"
        )

    with pytest.raises(WorkspaceError, match="could not be verified"):
        transfer_sessions(source.db_path, destination.db_path, ["sess-a"], WS_ID)

    assert _rows(destination.db_path, "SELECT count(*) FROM messages") == [(0,)]
    assert _rows(destination.db_path, "SELECT count(*) FROM sessions") == [(0,)]
    assert _rows(source.db_path, "SELECT count(*) FROM sessions") == [(1,)]
    assert _rows(source.db_path, "SELECT count(*) FROM messages") == [(2,)]


def test_direct_transfer_records_no_migration_operation(account, tmp_path):
    from deeptutor.services.workspace.data_migration import (
        assert_no_pending_recovery,
        operations,
    )

    source = _prepare(tmp_path / "src.db")
    destination = _prepare(tmp_path / "dst.db")
    _seed_conversation(source.db_path)

    assert transfer_sessions(source.db_path, destination.db_path, ["sess-a"], WS_ID) == 1
    assert operations() == []
    assert_no_pending_recovery()
    assert _rows(source.db_path, "SELECT count(*) FROM sessions") == [(0,)]
