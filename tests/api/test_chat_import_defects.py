"""Regression tests for chat-history import dedup idempotency.

Each case pins one reproducible defect in the import contract: dedup-id
collisions that silently drop a whole conversation, and non-idempotent
re-import when the external id carries no usable characters. Both are
covered by the paired production fixes (digest-suffixed sanitization in
``make_imported_session_id`` and a content-derived fallback id).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from deeptutor.api.routers import imports as imports_router
from deeptutor.api.routers.imports import (
    ChatHistoryImportRequest,
    import_chat_history,
    list_imported_chat_history,
)
from deeptutor.services.session.sqlite_store import (
    SQLiteSessionStore,
    make_imported_session_id,
)


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SQLiteSessionStore:
    instance = SQLiteSessionStore(db_path=tmp_path / "test.db")
    monkeypatch.setattr(imports_router, "get_sqlite_session_store", lambda: instance)
    return instance


def _session(external_id: str, user_text: str, answer: str) -> dict:
    return {
        "external_id": external_id,
        "title": f"T {external_id}",
        "source_cwd": "/p",
        "created_at": 1.0,
        "updated_at": 2.0,
        "messages": [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": answer},
        ],
    }


def _listed(store: SQLiteSessionStore) -> list[dict]:
    listed = asyncio.run(list_imported_chat_history(limit=50, offset=0))
    return listed["sessions"]


def test_distinct_external_ids_do_not_collide_on_dedup_id() -> None:
    # `/` and `:` sanitize to the same `-`; two distinct conversations whose
    # ids differ only in separators must still get distinct dedup ids.
    first = make_imported_session_id("codex", "demo/notes")
    second = make_imported_session_id("codex", "demo:notes")
    assert first != second


def test_colliding_external_ids_keep_both_conversations(
    store: SQLiteSessionStore,
) -> None:
    payload = ChatHistoryImportRequest(
        source="codex",
        sessions=[
            _session("demo/notes", "conversation A question", "answer A"),
            _session("demo:notes", "conversation B question", "answer B"),
        ],
    )
    res = asyncio.run(import_chat_history(payload))

    assert res["imported"] == 2
    sessions = _listed(store)
    assert len(sessions) == 2
    contents = {s["message_count"] for s in sessions}
    assert contents == {2}


def test_blank_external_id_reimport_is_idempotent(store: SQLiteSessionStore) -> None:
    # A whitespace-only external id survives request validation; the dedup id
    # must not fall back to a fresh random value per call, or every re-import
    # of the same conversation duplicates it.
    first = asyncio.run(import_chat_history(_blank_payload()))
    second = asyncio.run(import_chat_history(_blank_payload()))

    assert first["imported"] == 1
    assert second["imported"] == 0
    assert len(_listed(store)) == 1


def _blank_payload() -> ChatHistoryImportRequest:
    return ChatHistoryImportRequest(
        source="codex",
        sessions=[_session("   ", "blank id question", "blank id answer")],
    )
