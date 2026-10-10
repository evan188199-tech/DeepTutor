"""Route-layer contract tests for the task board router.

``tests/multi_user/test_task_board.py`` exercises the board through the real
auth/workspace dependencies; this file isolates the thin route layer itself.
The store is stubbed via ``get_task_board_store`` and the workspace scope is
faked, so each test pins one routing contract: response envelope, request
validation boundaries, and the error mapping the routes apply on top of
``TaskBoardStore`` (``KeyError`` and ``WorkspaceError`` -> 404).
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import task_board
from deeptutor.services.task_board import TaskBoard, TaskBoardStore
from deeptutor.services.workspace.models import WorkspaceError


@pytest.fixture
def store(tmp_path: Path) -> TaskBoardStore:
    return TaskBoardStore(tmp_path / "board" / "tasks.sqlite")


@pytest.fixture
def client(monkeypatch, store: TaskBoardStore) -> TestClient:
    monkeypatch.setattr(task_board, "get_task_board_store", lambda: store)
    app = FastAPI()
    app.include_router(task_board.router, prefix="/api/task-board")
    with TestClient(app) as test_client:
        yield test_client


def create_card(client: TestClient, title: str = "Review") -> dict:
    response = client.post("/api/task-board/cards", json={"title": title})
    assert response.status_code == 201
    return response.json()


def test_get_board_returns_full_task_board_envelope(client: TestClient) -> None:
    response = client.get("/api/task-board")

    assert response.status_code == 200
    assert response.json() == TaskBoard(cards=[]).model_dump()


def test_create_card_strips_title_defaults_note_and_bumps_revision(client: TestClient) -> None:
    body = create_card(client, title="  Review derivatives  ")

    assert body["revision"] == 1
    card = body["cards"][0]
    assert card["title"] == "Review derivatives"
    assert card["note"] == ""
    assert card["status"] == "todo"
    assert card["archived"] is False
    assert card["workspace_id"] is None


def test_create_card_accepts_boundary_lengths(client: TestClient) -> None:
    assert client.post("/api/task-board/cards", json={"title": "x" * 160}).status_code == 201
    assert (
        client.post(
            "/api/task-board/cards", json={"title": "Note cap", "note": "y" * 2000}
        ).status_code
        == 201
    )
    assert len(client.get("/api/task-board").json()["cards"]) == 2


@pytest.mark.parametrize(
    "payload",
    [{"title": 5}, {"title": ["Review"]}, {"title": "Valid", "note": 3}, []],
)
def test_create_card_rejects_wrong_typed_payloads(
    client: TestClient, store: TaskBoardStore, payload: object
) -> None:
    response = client.post("/api/task-board/cards", json=payload)

    assert response.status_code == 422
    assert store.read().cards == []


def test_create_card_rejects_malformed_json_body(client: TestClient) -> None:
    response = client.post(
        "/api/task-board/cards",
        content=b"{not json",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert client.get("/api/task-board").json()["cards"] == []


def test_update_missing_card_maps_key_error_to_404_detail(client: TestClient) -> None:
    response = client.patch("/api/task-board/cards/missing", json={"status": "done"})

    assert response.status_code == 404
    assert response.json()["detail"] == "Task card not found."


def test_update_without_store_file_maps_to_404(client: TestClient, store: TaskBoardStore) -> None:
    assert not store.path.exists()

    response = client.patch("/api/task-board/cards/missing", json={})

    assert response.status_code == 404
    assert response.json()["detail"] == "Task card not found."
    assert not store.path.exists()


def test_update_maps_workspace_error_to_404_detail_without_touching_store(
    monkeypatch, client: TestClient, store: TaskBoardStore
) -> None:
    @contextmanager
    def archived_scope(workspace_id):
        raise WorkspaceError("Restore this workspace before assigning tasks.")
        yield

    monkeypatch.setattr(task_board, "workspace_context", archived_scope)
    card = create_card(client)["cards"][0]

    response = client.patch(
        f"/api/task-board/cards/{card['id']}", json={"workspace_id": "archived"}
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Restore this workspace before assigning tasks."
    assert store.read().cards[0].workspace_id is None


def test_update_writes_normalized_workspace_scope_id(monkeypatch, client: TestClient) -> None:
    @contextmanager
    def fake_scope(workspace_id):
        yield SimpleNamespace(workspace_id="ws-normalized", archived=False)

    monkeypatch.setattr(task_board, "workspace_context", fake_scope)
    card = create_card(client)["cards"][0]

    response = client.patch(
        f"/api/task-board/cards/{card['id']}", json={"workspace_id": "raw-input"}
    )

    assert response.status_code == 200
    assert response.json()["cards"][0]["workspace_id"] == "ws-normalized"


def test_update_skips_workspace_context_without_explicit_workspace_id(
    monkeypatch, client: TestClient
) -> None:
    entered: list[str] = []

    @contextmanager
    def spy_scope(workspace_id):
        entered.append(workspace_id)
        yield SimpleNamespace(workspace_id=workspace_id, archived=False)

    monkeypatch.setattr(task_board, "workspace_context", spy_scope)
    card = create_card(client)["cards"][0]
    url = f"/api/task-board/cards/{card['id']}"

    assert client.patch(url, json={"status": "doing"}).status_code == 200
    assert client.patch(url, json={"workspace_id": None}).status_code == 200
    assert entered == []


def test_update_rejects_unknown_fields_and_overlong_workspace_id(
    client: TestClient, store: TaskBoardStore
) -> None:
    card = create_card(client)["cards"][0]
    url = f"/api/task-board/cards/{card['id']}"

    assert client.patch(url, json={"workspace": "extra"}).status_code == 422
    assert client.patch(url, json={"workspace_id": "w" * 201}).status_code == 422
    unchanged = store.read().cards[0]
    assert unchanged.title == card["title"]
    assert unchanged.workspace_id is None
