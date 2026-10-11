"""Focused unit tests for services.workspace.session_move (seed C89).

Complements the migration integration tests with the move_chat /
migrate_legacy_bindings rejection branches, same-scope short circuit,
PocketBase fallback return path, and legacy-adoption retry semantics.
"""

from __future__ import annotations

import json

import pytest

from deeptutor.services.path_service import get_path_service
from deeptutor.services.session import get_sqlite_session_store
from deeptutor.services.workspace.context import workspace_context
from deeptutor.services.workspace.data_migration import _journal_root, _sessions
from deeptutor.services.workspace.models import WorkspaceError
from deeptutor.services.workspace.session_move import migrate_legacy_bindings, move_chat
from tests.services.session.test_pocketbase_isolation import fake_pb as fake_pb
from tests.services.workspace.test_data_scope import account as account

MARKER = "default-adoption-v1.json"
BACKUP = "default-adoption-backup.json"


def _marker():
    return _journal_root() / MARKER


def test_move_chat_unknown_session_raises_without_migrating(account, monkeypatch):
    from deeptutor.services.workspace import session_move

    target = account.create_workspace("Destination")["workspace_id"]
    monkeypatch.setattr(
        session_move, "preview", lambda *a, **k: pytest.fail("preview must not run")
    )
    monkeypatch.setattr(
        session_move, "migrate_data", lambda *a, **k: pytest.fail("migration must not run")
    )
    with pytest.raises(WorkspaceError, match="not found"):
        move_chat("missing-session", target)


def test_move_chat_refuses_learning_linked_bundle(account, monkeypatch):
    from deeptutor.services.workspace import session_move

    target = account.create_workspace("Destination")["workspace_id"]
    migrated = []
    monkeypatch.setattr(session_move, "_sessions", lambda paths: [{"id": "s-linked"}])
    monkeypatch.setattr(
        session_move,
        "preview",
        lambda *a, **k: {"features": ["chat", "book"], "session_ids": ["s-linked"]},
    )
    monkeypatch.setattr(session_move, "migrate_data", lambda *a, **k: migrated.append(a))
    with pytest.raises(WorkspaceError, match="learning data"):
        move_chat("s-linked", target)
    assert migrated == []


@pytest.mark.asyncio
async def test_move_chat_same_scope_returns_record_without_migration(account, monkeypatch):
    from deeptutor.services.workspace import session_move

    session = await get_sqlite_session_store().create_session("Stays put")
    monkeypatch.setattr(
        session_move, "preview", lambda *a, **k: pytest.fail("same scope must not plan")
    )
    monkeypatch.setattr(
        session_move, "migrate_data", lambda *a, **k: pytest.fail("same scope must not migrate")
    )
    moved = move_chat(session["id"], "")
    assert moved["id"] == session["id"]
    assert moved["title"] == "Stays put"


def test_move_chat_pocketbase_backend_returns_remote_record(account, monkeypatch):
    from deeptutor.services.session import pocketbase_store as pb_store
    from deeptutor.services.workspace import data_migration, session_move

    target = account.create_workspace("Remote target")["workspace_id"]
    pb_client = object()
    remote_row = {"record": "pb-row"}
    seen = {}
    migrated = []

    def fake_find(pb, session_id, user_id):
        seen.update(pb=pb, session_id=session_id, user_id=user_id)
        return remote_row

    class _FakeRemoteStore:
        def _session_record_to_dict(self, record):
            seen["record"] = record
            return {"id": "s-remote", "title": "Remote", "backend": "pocketbase"}

    monkeypatch.setattr(session_move, "_sessions", lambda paths: [{"id": "s-remote"}])
    monkeypatch.setattr(
        session_move,
        "preview",
        lambda source, dest, features, session_ids=None: {
            "features": list(features),
            "session_ids": sorted(session_ids or []),
        },
    )
    monkeypatch.setattr(
        session_move,
        "migrate_data",
        lambda source, dest, features, session_ids=None: migrated.append(
            (source, dest, features, session_ids)
        ),
    )
    monkeypatch.setattr(data_migration, "_backend", lambda: "pocketbase")
    monkeypatch.setattr(pb_store, "_find_session_record", fake_find)
    monkeypatch.setattr(pb_store, "_pb", lambda: pb_client)
    monkeypatch.setattr(pb_store, "_current_user_id", lambda: "scope-test")
    monkeypatch.setattr(pb_store, "PocketBaseSessionStore", _FakeRemoteStore)

    moved = move_chat("s-remote", target)

    assert moved == {"id": "s-remote", "title": "Remote", "backend": "pocketbase"}
    assert seen == {
        "pb": pb_client,
        "session_id": "s-remote",
        "user_id": "scope-test",
        "record": remote_row,
    }
    assert migrated == [("", target, ["chat"], {"s-remote"})]


@pytest.mark.asyncio
async def test_move_chat_between_workspaces_relocates_listing(account):
    target = account.create_workspace("Destination")["workspace_id"]
    store = get_sqlite_session_store()
    session = await store.create_session("Plain move")

    moved = move_chat(session["id"], target)

    assert moved["id"] == session["id"]
    assert moved["preferences"]["workspace_id"] == target
    with workspace_context():
        assert session["id"] not in {row["id"] for row in _sessions(get_path_service())}
    with workspace_context(target):
        assert session["id"] in {row["id"] for row in _sessions(get_path_service())}


def test_migrate_legacy_bindings_marker_short_circuits_before_journal_check(account, monkeypatch):
    from deeptutor.services.workspace import data_migration

    marker = _marker()
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text('{"version": 1, "sessions": 0}')
    monkeypatch.setattr(
        data_migration,
        "assert_no_pending_recovery",
        lambda **kwargs: pytest.fail("adoption must not inspect journals when already adopted"),
    )
    assert migrate_legacy_bindings() == 0
    assert marker.read_text() == '{"version": 1, "sessions": 0}'


@pytest.mark.asyncio
async def test_migrate_legacy_bindings_retry_merges_preserved_backup(account):
    store = get_sqlite_session_store()
    session = await store.create_session("Legacy binding")
    await store.update_session_preferences(session["id"], {"workspace_id": "old-ws"})
    backup = _journal_root() / BACKUP
    backup.write_text(
        json.dumps([{"id": "s-earlier", "preferences": {"workspace_id": "older-ws"}}])
    )

    assert migrate_legacy_bindings() == 1

    merged = {
        row["id"]: row["preferences"]["workspace_id"] for row in json.loads(backup.read_text())
    }
    assert merged == {"s-earlier": "older-ws", session["id"]: "old-ws"}
    prefs = (await store.get_session(session["id"]))["preferences"]
    assert prefs["workspace_id"] == ""
    assert prefs["legacy_workspace_id"] == "old-ws"
    assert json.loads(_marker().read_text()) == {"version": 1, "sessions": 1}


@pytest.mark.asyncio
async def test_migrate_legacy_bindings_adopts_pocketbase_rows_once(account, fake_pb, monkeypatch):
    from deeptutor.services.session.pocketbase_store import _current_user_id
    from deeptutor.services.workspace.data_migration import _backend

    monkeypatch.setattr(
        "deeptutor.services.workspace.data_migration._backend", lambda: "pocketbase"
    )
    owner = _current_user_id()
    collection = fake_pb.collection("sessions")
    collection.create(
        {
            "user_id": owner,
            "session_id": "s-legacy",
            "title": "Legacy",
            "preferences_json": {"workspace_id": "old-ws"},
        }
    )
    collection.create(
        {
            "user_id": owner,
            "session_id": "s-plain",
            "title": "Plain",
            "preferences_json": {},
        }
    )

    assert migrate_legacy_bindings() == 1

    rows = {record.session_id: record for record in collection._rows}
    assert rows["s-legacy"].preferences_json == {
        "workspace_id": "",
        "legacy_workspace_id": "old-ws",
    }
    assert rows["s-plain"].preferences_json == {}
    assert json.loads(_marker().read_text()) == {"version": 1, "sessions": 1}
    assert migrate_legacy_bindings() == 0
