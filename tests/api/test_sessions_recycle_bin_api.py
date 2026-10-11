"""HTTP contract tests for the session recycle-bin routes.

Covers ``GET /api/sessions/recycle-bin``, ``POST /api/sessions/{id}/restore``
and ``DELETE /api/sessions/{id}/purge``: paging bounds, the 404 branch when a
session is not restorable/purgeable, the side-data cleanup a purge must run
(mastery, attachments, reading catalog, task board), and the authentication
gate applied by ``main.py``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from deeptutor.api.routers import auth as auth_router
from deeptutor.api.routers import sessions as sessions_router
from deeptutor.services.auth import TokenPayload


class _FakeStore:
    """Stand-in for the session store's recycle-bin slice."""

    def __init__(self) -> None:
        self.deleted: list[dict[str, Any]] = [
            {"session_id": "s-1", "title": "deleted one"},
            {"session_id": "s-2", "title": "deleted two"},
        ]
        self.live: dict[str, dict[str, Any]] = {}
        self.restorable: set[str] = {"s-1"}
        self.purgeable: set[str] = {"s-1"}
        self.calls: list[tuple[Any, ...]] = []

    async def list_deleted_sessions(self, *, limit: int, offset: int) -> list[dict[str, Any]]:
        self.calls.append(("list", limit, offset))
        return self.deleted[offset : offset + limit]

    async def restore_session(self, session_id: str) -> bool:
        self.calls.append(("restore", session_id))
        if session_id not in self.restorable:
            return False
        self.live[session_id] = {"session_id": session_id, "title": "back again"}
        return True

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        return self.live.get(session_id)

    async def hard_delete_session(self, session_id: str) -> bool:
        self.calls.append(("purge", session_id))
        return session_id in self.purgeable


class _LearningStoreStub:
    instances: list[_LearningStoreStub] = []

    def __init__(self) -> None:
        self.calls: list[str] = []
        _LearningStoreStub.instances.append(self)

    def detach_session(self, session_id: str) -> None:
        self.calls.append(session_id)


class _ReadingCatalogStub:
    instances: list[_ReadingCatalogStub] = []

    def __init__(self) -> None:
        self.calls: list[str] = []
        _ReadingCatalogStub.instances.append(self)

    def forget_session(self, session_id: str) -> None:
        self.calls.append(session_id)


class _AttachmentStub:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def delete_session(self, session_id: str) -> None:
        self.calls.append(session_id)


class _TaskBoardStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def remove_session(self, workspace_id: str, session_id: str) -> None:
        self.calls.append((workspace_id, session_id))


def _make_app(store: _FakeStore) -> TestClient:
    app = FastAPI()
    app.include_router(
        sessions_router.router,
        prefix="/api/sessions",
        dependencies=[Depends(auth_router.require_learning_surface)],
    )
    return TestClient(app)


@pytest.fixture
def recycle_env(monkeypatch: pytest.MonkeyPatch) -> tuple[_FakeStore, dict[str, Any]]:
    from deeptutor.services import task_board as task_board_module
    from deeptutor.services.workspace import context as workspace_context

    store = _FakeStore()
    learning = _LearningStoreStub()
    catalog = _ReadingCatalogStub()
    attachments = _AttachmentStub()
    board = _TaskBoardStub()

    monkeypatch.setattr(sessions_router, "get_session_store", lambda: store)
    monkeypatch.setattr(sessions_router, "LearningStore", lambda: learning)
    monkeypatch.setattr(sessions_router, "ReadingCatalogStore", lambda: catalog)
    monkeypatch.setattr(sessions_router, "get_attachment_store", lambda: attachments)
    monkeypatch.setattr(task_board_module, "get_task_board_store", lambda **_: board)
    monkeypatch.setattr(workspace_context, "current_workspace_id", lambda: "ws-1")
    _LearningStoreStub.instances = []
    _ReadingCatalogStub.instances = []
    return store, {
        "learning": learning,
        "catalog": catalog,
        "attachments": attachments,
        "board": board,
    }


def test_recycle_bin_lists_deleted_sessions_with_default_paging(
    recycle_env: tuple[_FakeStore, dict[str, Any]],
) -> None:
    store, _ = recycle_env
    response = _make_app(store).get("/api/sessions/recycle-bin")
    assert response.status_code == 200
    assert response.json() == {"sessions": store.deleted}
    assert store.calls == [("list", 50, 0)]


def test_recycle_bin_rejects_out_of_range_paging(
    recycle_env: tuple[_FakeStore, dict[str, Any]],
) -> None:
    store, _ = recycle_env
    client = _make_app(store)

    assert client.get("/api/sessions/recycle-bin", params={"limit": 0}).status_code == 422
    assert client.get("/api/sessions/recycle-bin", params={"limit": 201}).status_code == 422
    assert client.get("/api/sessions/recycle-bin", params={"offset": -1}).status_code == 422
    assert store.calls == []

    ok = client.get("/api/sessions/recycle-bin", params={"limit": 200, "offset": 1})
    assert ok.status_code == 200
    assert store.calls[-1] == ("list", 200, 1)


def test_restore_returns_the_revived_session(
    recycle_env: tuple[_FakeStore, dict[str, Any]],
) -> None:
    store, _ = recycle_env
    response = _make_app(store).post("/api/sessions/s-1/restore")
    assert response.status_code == 200
    assert response.json() == {
        "restored": True,
        "session": {"session_id": "s-1", "title": "back again"},
    }
    assert store.calls == [("restore", "s-1")]


def test_restore_unknown_session_answers_404(
    recycle_env: tuple[_FakeStore, dict[str, Any]],
) -> None:
    store, _ = recycle_env
    response = _make_app(store).post("/api/sessions/s-ghost/restore")
    assert response.status_code == 404
    assert response.json()["detail"] == "Session not found in recycle bin"


def test_purge_cascades_cleanup_to_side_data(
    recycle_env: tuple[_FakeStore, dict[str, Any]],
) -> None:
    store, cleanup = recycle_env
    response = _make_app(store).delete("/api/sessions/s-1/purge")
    assert response.status_code == 200
    assert response.json() == {"purged": True, "session_id": "s-1"}
    assert cleanup["learning"].calls == ["s-1"]
    assert cleanup["attachments"].calls == ["s-1"]
    assert cleanup["catalog"].calls == ["s-1"]
    assert cleanup["board"].calls == [("ws-1", "s-1")]


def test_purge_unknown_session_answers_404_without_cleanup(
    recycle_env: tuple[_FakeStore, dict[str, Any]],
) -> None:
    store, cleanup = recycle_env
    response = _make_app(store).delete("/api/sessions/s-ghost/purge")
    assert response.status_code == 404
    assert response.json()["detail"] == "Session not found in recycle bin"
    assert cleanup["learning"].calls == []
    assert cleanup["attachments"].calls == []
    assert cleanup["board"].calls == []


def test_recycle_bin_requires_authentication_when_enabled(
    recycle_env: tuple[_FakeStore, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _ = recycle_env
    tokens: dict[str, TokenPayload | None] = {
        "tok-admin": TokenPayload(username="root", role="admin", user_id="u-admin"),
        "tok-user": TokenPayload(username="alice", role="user", user_id="u-alice"),
    }
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "decode_token", lambda token: tokens.get(token))
    client = _make_app(store)

    for method, url in (
        ("get", "/api/sessions/recycle-bin"),
        ("post", "/api/sessions/s-1/restore"),
        ("delete", "/api/sessions/s-1/purge"),
    ):
        assert getattr(client, method)(url).status_code == 401

    # Any authenticated account may read the bin; the recycle routes carry no
    # extra admin gate beyond the router-level authentication dependency.
    assert (
        client.get(
            "/api/sessions/recycle-bin", headers={"Authorization": "Bearer tok-user"}
        ).status_code
        == 200
    )
    assert (
        client.get(
            "/api/sessions/recycle-bin", headers={"Authorization": "Bearer tok-admin"}
        ).status_code
        == 200
    )

    restored = client.post(
        "/api/sessions/s-1/restore", headers={"Authorization": "Bearer tok-admin"}
    )
    assert restored.status_code == 200
    purged = client.delete("/api/sessions/s-1/purge", headers={"Authorization": "Bearer tok-admin"})
    assert purged.status_code == 200
