"""Contract tests for the dashboard library routes.

Covers ``/recent``, ``/learning-index``, ``/source-library/{kind}`` and
``/learning-library/{kind}`` with a fake session store and faked index
readers; ``/suggestions`` and ``/{entry_id}`` already have coverage in
``test_dashboard_suggestions.py``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from deeptutor.api.routers import auth as auth_router
from deeptutor.api.routers import dashboard as dashboard_router
from deeptutor.services.auth import TokenPayload

IndexReader = Callable[[Callable[[], Any]], Awaitable[tuple[list[dict[str, Any]], list[str]]]]


class FakeSessionStore:
    def __init__(self, sessions: list[dict[str, Any]]) -> None:
        self._sessions = sessions

    async def list_sessions(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        return self._sessions[offset : offset + limit]

    async def get_session_with_messages(self, session_id: str) -> dict[str, Any] | None:
        return next((s for s in self._sessions if s.get("session_id") == session_id), None)


def _sessions() -> list[dict[str, Any]]:
    return [
        {
            "session_id": "s-chat",
            "capability": "chat",
            "title": "Chat session",
            "updated_at": 20,
            "created_at": 10,
            "last_message": "hello there",
            "message_count": 4,
            "status": "idle",
            "active_turn_id": None,
        },
        {
            "session_id": "s-research",
            "capability": "deep_research",
            "title": "Research session",
            "updated_at": 30,
            "created_at": 15,
            "last_message": "",
            "message_count": 9,
            "status": "idle",
            "active_turn_id": "t-1",
        },
        {
            "session_id": "s-watch",
            "capability": "chat",
            "title": "Watch session",
            "updated_at": 40,
            "created_at": 12,
            "last_message": None,
            "message_count": 1,
            "status": "idle",
            "active_turn_id": None,
            "preferences": {"workspace_mode": "immersive_watching"},
        },
    ]


async def _fake_snapshot(store: Any) -> list[dict[str, Any]]:
    del store
    return []


async def _default_indexes(
    reader: Callable[[], Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    rows = reader()
    if hasattr(rows, "__await__"):
        rows = await rows
    return rows, []


def _patch_readers(
    monkeypatch: pytest.MonkeyPatch,
    *,
    snapshot: Callable[..., Any] | None = None,
    indexes: IndexReader | None = None,
) -> None:
    import deeptutor.api.routers.book as book_mod
    import deeptutor.api.routers.mastery_path as mastery_mod
    import deeptutor.api.routers.reading as reading_mod
    import deeptutor.services.session.organization as organization_mod
    import deeptutor.services.workspace.navigation as navigation_mod

    async def fake_list_books() -> dict[str, Any]:
        return {"books": [{"id": "b-1", "title": "A book"}], "can_create": False}

    async def fake_list_topics() -> dict[str, Any]:
        return {"topics": [{"id": "t-1", "title": "A topic"}]}

    async def fake_list_workspaces(search: str) -> dict[str, Any]:
        return {"workspaces": [{"id": "w-1"}]}

    monkeypatch.setattr(book_mod, "list_books", fake_list_books)
    monkeypatch.setattr(mastery_mod, "list_topics", fake_list_topics)
    monkeypatch.setattr(reading_mod, "list_workspaces", fake_list_workspaces)
    monkeypatch.setattr(organization_mod, "list_all_sessions_snapshot", snapshot or _fake_snapshot)
    monkeypatch.setattr(navigation_mod, "read_workspace_indexes", indexes or _default_indexes)


def _make_app(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    snapshot: Callable[..., Any] | None = None,
    indexes: IndexReader | None = None,
    auth_guard: bool = False,
) -> TestClient:
    store = FakeSessionStore(_sessions())
    monkeypatch.setattr(dashboard_router, "get_session_store", lambda: store)
    _patch_readers(monkeypatch, snapshot=snapshot, indexes=indexes)

    app = FastAPI()
    dependencies = [Depends(auth_router.require_learning_surface)] if auth_guard else None
    app.include_router(dashboard_router.router, prefix="/api/dashboard", dependencies=dependencies)
    return TestClient(app)


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    return _make_app(monkeypatch, tmp_path)


def test_recent_activities_maps_session_fields(client: TestClient) -> None:
    res = client.get("/api/dashboard/recent")
    assert res.status_code == 200
    rows = res.json()
    by_id = {row["id"]: row for row in rows}
    chat = by_id["s-chat"]
    assert chat["type"] == "chat"
    assert chat["capability"] == "chat"
    assert chat["title"] == "Chat session"
    assert chat["timestamp"] == 20
    assert chat["summary"] == "hello there"
    assert chat["session_ref"] == "sessions/s-chat"
    research = by_id["s-research"]
    assert research["type"] == "research"
    assert research["capability"] == "deep_research"
    assert research["active_turn_id"] == "t-1"


def test_recent_filters_by_activity_type(client: TestClient) -> None:
    res = client.get("/api/dashboard/recent", params={"type": "research"})
    assert res.status_code == 200
    assert [row["id"] for row in res.json()] == ["s-research"]


def test_recent_respects_limit(client: TestClient) -> None:
    res = client.get("/api/dashboard/recent", params={"limit": 2})
    assert res.status_code == 200
    assert len(res.json()) == 2


def test_learning_index_aggregates_all_kinds(client: TestClient) -> None:
    res = client.get("/api/dashboard/learning-index")
    assert res.status_code == 200
    body = res.json()
    assert body["failed"] == []
    assert [b["id"] for b in body["sources"]["books"]] == ["b-1"]
    assert [t["id"] for t in body["sources"]["mastery"]] == ["t-1"]
    assert [w["id"] for w in body["sources"]["reading"]] == ["w-1"]


def test_learning_index_reports_unavailable_kinds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"count": 0}

    async def flaky_indexes(
        reader: Callable[[], Any],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        calls["count"] += 1
        if calls["count"] == 1:
            return [], ["books"]
        rows = reader()
        if hasattr(rows, "__await__"):
            rows = await rows
        return rows, []

    client = _make_app(monkeypatch, tmp_path, indexes=flaky_indexes)
    res = client.get("/api/dashboard/learning-index")
    assert res.status_code == 200
    assert res.json()["failed"] == ["books"]


def test_source_library_unknown_kind_404(client: TestClient) -> None:
    res = client.get("/api/dashboard/source-library/unknown-kind")
    assert res.status_code == 404


def test_source_library_chats_lists_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_snapshot(store: Any) -> list[dict[str, Any]]:
        return [{"session_id": "s-chat"}, {"session_id": "s-watch"}]

    client = _make_app(monkeypatch, tmp_path, snapshot=fake_snapshot)
    res = client.get("/api/dashboard/source-library/chats")
    assert res.status_code == 200
    body = res.json()
    assert [row["session_id"] for row in body["items"]] == ["s-chat", "s-watch"]
    assert body["unavailable_workspaces"] == []


def test_learning_library_unknown_kind_404(client: TestClient) -> None:
    res = client.get("/api/dashboard/learning-library/unknown-kind")
    assert res.status_code == 404


def test_learning_library_books_carries_can_create(client: TestClient) -> None:
    res = client.get("/api/dashboard/learning-library/books")
    assert res.status_code == 200
    body = res.json()
    assert [row["id"] for row in body["items"]] == ["b-1"]
    assert body["can_create"] is False
    assert body["unavailable_workspaces"] == []


def test_auth_gate_blocks_anonymous_and_accepts_valid_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    tokens: dict[str, TokenPayload | None] = {
        "tok-ok": TokenPayload(username="alice", role="admin", user_id="u-1")
    }
    monkeypatch.setattr(auth_router, "decode_token", lambda token: tokens.get(token))
    client = _make_app(monkeypatch, tmp_path, auth_guard=True)

    assert client.get("/api/dashboard/recent").status_code == 401
    assert (
        client.get("/api/dashboard/recent", headers={"Authorization": "Bearer tok-bad"}).status_code
        == 401
    )
    assert (
        client.get("/api/dashboard/recent", headers={"Authorization": "Bearer tok-ok"}).status_code
        == 200
    )
