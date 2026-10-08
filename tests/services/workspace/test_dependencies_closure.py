"""Focused failure-path coverage for workspace dependency closure."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from deeptutor.services.workspace.dependencies import _preferences, dependency_closure


class _FakePaths:
    def __init__(self, root: Path):
        self._root = root

    def get_book_dir(self) -> Path:
        return self._root / "books"

    def get_workspace_dir(self) -> Path:
        return self._root / "workspace"

    def get_chat_history_db(self) -> Path:
        return self._root / "chat_history.db"


@pytest.fixture
def paths(tmp_path, monkeypatch):
    import deeptutor.services.workspace.data_migration as data_migration

    monkeypatch.setattr(data_migration, "_backend", lambda: "sqlite")
    return _FakePaths(tmp_path)


def _session(sid, **preferences):
    return {"id": sid, "title": sid, "preferences_json": json.dumps(preferences)}


def _write_history_db(paths, messages=(), notebook_entries=()):
    db = paths.get_chat_history_db()
    db.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db)
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS messages (session_id TEXT, metadata_json TEXT)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS notebook_entries "
            "(id TEXT, session_id TEXT, followup_session_id TEXT)"
        )
        connection.executemany("INSERT INTO messages VALUES (?, ?)", messages)
        connection.executemany("INSERT INTO notebook_entries VALUES (?, ?, ?)", notebook_entries)
        connection.commit()
    finally:
        connection.close()


def test_missing_stores_resolve_requested_features_without_sessions(paths):
    sessions = [_session("s1")]

    selected, ids = dependency_closure(paths, sessions, ["chat"], session_ids={"s1"})
    assert selected == {"chat"}
    assert ids == {"s1"}

    selected, ids = dependency_closure(paths, sessions, ["book"])
    assert selected == {"book"}
    assert ids == set()


def test_corrupt_book_files_are_skipped_and_valid_book_still_closes(paths):
    books = paths.get_book_dir()
    (books / "book_broken").mkdir(parents=True)
    (books / "book_broken" / "manifest.json").write_text("{not json")
    (books / "book_good").mkdir()
    (books / "book_good" / "inputs.json").write_text(json.dumps({"chat_session_id": "s1"}))
    sessions = [_session("s1"), _session("s2")]

    selected, ids = dependency_closure(paths, sessions, ["book"], session_ids={"s2"})

    assert "book" in selected
    assert ids == {"s1", "s2"}


def test_corrupt_feature_documents_are_skipped_and_valid_references_kept(paths):
    workspace = paths.get_workspace_dir()
    (workspace / "notebook").mkdir(parents=True)
    (workspace / "notebook" / "doc.json").write_text(
        json.dumps({"items": [{"ref_id": "s1", "kind": "chat"}]})
    )
    (workspace / "notebook" / "broken.json").write_text("[truncated")
    (workspace / "co-writer").mkdir()
    (workspace / "co-writer" / "draft.json").write_text(json.dumps({"chat_session_id": "s3"}))
    sessions = [_session("s0"), _session("s1"), _session("s3")]

    selected, ids = dependency_closure(
        paths, sessions, ["notebook", "co-writer"], session_ids={"s0"}
    )

    assert ids == {"s0", "s1", "s3"}
    assert {"notebook", "co-writer", "chat"} <= selected


def test_empty_mastery_and_reading_databases_are_tolerated(paths):
    workspace = paths.get_workspace_dir()
    mastery = workspace / "learning" / "mastery"
    mastery.mkdir(parents=True)
    connection = sqlite3.connect(mastery / "mastery.sqlite3")
    connection.close()
    catalog = workspace / "reading"
    catalog.mkdir(parents=True)
    connection = sqlite3.connect(catalog / "_catalog.sqlite3")
    connection.close()

    sessions = [_session("s1", mastery_path_id="mp1")]

    selected, ids = dependency_closure(paths, sessions, ["learning", "reading"], session_ids={"s1"})

    assert {"learning", "reading"} <= selected
    assert ids == {"s1"}


def test_corrupt_message_metadata_is_skipped_and_valid_references_kept(paths):
    _write_history_db(
        paths,
        messages=[
            ("s1", "{broken json"),
            ("s1", json.dumps({"readingReferences": [{"material_id": "old"}]})),
            ("ghost", json.dumps({"bookReferences": ["b1"]})),
            ("s2", None),
        ],
    )
    sessions = [_session("s1"), _session("s2")]

    selected, ids = dependency_closure(paths, sessions, ["chat"], session_ids={"s1"})

    assert "reading" in selected
    assert ids == {"s1"}
    assert "ghost" not in ids


def test_notebook_followup_entries_link_source_and_followup_sessions(paths):
    _write_history_db(paths, notebook_entries=[("e1", "s1", "s2")])
    sessions = [_session("s1"), _session("s2"), _session("s3")]

    selected, ids = dependency_closure(paths, sessions, ["chat"], session_ids={"s1"})

    assert ids == {"s1", "s2"}


def test_circular_history_references_terminate_with_all_members(paths):
    sessions = [
        _session("s_a", history_references=["s_b"], parent_session_id="s_b"),
        _session("s_b", history_references=["s_a"], parent_session_id="s_a"),
    ]

    selected, ids = dependency_closure(paths, sessions, ["chat"], session_ids={"s_a"})

    assert ids == {"s_a", "s_b"}
    assert "chat" in selected


def test_self_and_dangling_references_do_not_expand_closure(paths):
    sessions = [
        _session("s1", history_references=["s1", "ghost"], parent_session_id="s1"),
    ]

    selected, ids = dependency_closure(paths, sessions, ["chat"], session_ids={"s1"})

    assert ids == {"s1"}


def test_closure_is_independent_of_session_order(paths):
    root = _session("root")
    mid = _session("mid", history_references=["root"])
    leaf = _session("leaf", history_references=["mid"], parent_session_id="mid")
    stray = _session("stray", history_references=["ghost"])
    orderings = [
        [root, mid, leaf, stray],
        [stray, leaf, mid, root],
        [leaf, root, stray, mid],
    ]

    results = [
        dependency_closure(paths, sessions, ["chat"], session_ids={"leaf"})
        for sessions in orderings
    ]

    assert results[0] == results[1] == results[2]
    selected, ids = results[0]
    assert ids == {"root", "mid", "leaf"}


def test_dangling_book_references_are_filtered_but_missing_stores_reported(paths):
    books = paths.get_book_dir()
    (books / "book_main").mkdir(parents=True)
    (books / "book_main" / "inputs.json").write_text(
        json.dumps(
            {
                "chat_session_id": "ghost_owner",
                "metadata": {"page_chat_sessions": {"p1": "ghost_page"}},
                "chat_selections": [
                    {"session_id": "s1"},
                    {"session_id": "ghost_selected"},
                ],
            }
        )
    )
    (books / "book_notebook").mkdir()
    (books / "book_notebook" / "inputs.json").write_text(
        json.dumps({"notebook_refs": ["nb-missing"]})
    )
    sessions = [_session("s1"), _session("s2")]

    selected, ids = dependency_closure(paths, sessions, ["book"], session_ids={"s2"})

    assert ids == {"s1", "s2"}
    assert "notebook" in selected


def test_question_references_without_history_db_resolve_to_nothing(paths):
    sessions = [_session("s1", question_notebook_references=["q1"])]

    selected, ids = dependency_closure(paths, sessions, ["chat"], session_ids={"s1"})

    assert ids == {"s1"}


def test_question_references_map_entries_to_known_sessions(paths):
    _write_history_db(
        paths,
        notebook_entries=[("q1", "s2", None), ("q9", "ghost", None)],
    )
    sessions = [_session("s1", question_notebook_references=["q1", "q_missing"])]

    selected, ids = dependency_closure(paths, sessions, ["chat"], session_ids={"s1"})

    assert ids == {"s1", "s2"}
    assert "ghost" not in ids


def test_workspace_dependencies_preferences_merge_without_duplicates():
    row = {
        "id": "s1",
        "preferences_json": json.dumps(
            {
                "history_references": ["a"],
                "workspace_dependencies": {
                    "history_references": ["a", "b"],
                    "notebook_references": ["n1"],
                },
            }
        ),
    }

    preferences = _preferences(row)

    assert preferences["history_references"] == ["a", "b"]
    assert preferences["notebook_references"] == ["n1"]
    assert _preferences({"id": "s2", "preferences_json": None}) == {}


def test_workspace_mode_maps_sessions_to_feature_stores(paths):
    sessions = [
        _session("m1", workspace_mode="mastery_path"),
        _session("r1", workspace_mode="immersive_reading"),
        _session("w1", workspace_mode="immersive_watching"),
        _session("p1"),
    ]

    selected, ids = dependency_closure(paths, sessions, ["learning", "reading", "timed_media"])

    assert ids == {"m1", "r1", "w1"}
    assert {"learning", "reading", "timed_media"} <= selected
    assert "chat" not in selected
