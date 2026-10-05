from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient

journal_module = importlib.import_module("deeptutor.api.routers.learning_journal")
journal_router = journal_module.router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(journal_router, prefix="/api/learning-journal")
    return app


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch) -> Path:
    from deeptutor.services.path_service import PathService

    root = tmp_path / "data"
    monkeypatch.setattr(
        journal_module, "get_path_service", lambda: PathService(workspace_root=root)
    )
    return root


def _write_journal(root: Path, payload: object, *, raw: str | None = None) -> None:
    target = root / "learning_journal" / "journal.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(raw if raw is not None else json.dumps(payload), encoding="utf-8")


def test_missing_journal_file_returns_empty(workspace: Path) -> None:
    client = TestClient(_build_app())
    response = client.get("/api/learning-journal")
    assert response.status_code == 200
    body = response.json()
    assert body["is_empty"] is True
    assert body["version"] == 1
    assert body["mission"] == {"topic": "", "why": "", "level": "", "updated_at": ""}
    assert body["last_session"] == {"summary": "", "next_focus": "", "updated_at": ""}
    assert body["records"] == []


def test_returns_stored_mission_handoff_and_records(workspace: Path) -> None:
    _write_journal(
        workspace,
        {
            "version": 1,
            "updated_at": "2026-10-01T10:00:00Z",
            "mission": {
                "topic": "Linear algebra",
                "why": "Prepare for graduate school",
                "level": "intermediate",
                "updated_at": "2026-09-30T08:00:00Z",
            },
            "last_session": {
                "summary": "Reviewed eigenvalues and eigenvectors",
                "next_focus": "SVD applications",
                "updated_at": "2026-10-01T09:00:00Z",
            },
            "records": [
                {
                    "id": "rec-1",
                    "title": "Eigen intuition",
                    "insight": "Eigenvectors only get scaled, not rotated",
                    "created_at": "2026-09-28T08:00:00Z",
                },
                {
                    "id": "rec-2",
                    "title": "Determinant",
                    "insight": "Volume scaling factor of the transformation",
                    "created_at": "2026-09-29T08:00:00Z",
                },
            ],
        },
    )
    client = TestClient(_build_app())
    response = client.get("/api/learning-journal")
    assert response.status_code == 200
    body = response.json()
    assert body["is_empty"] is False
    assert body["updated_at"] == "2026-10-01T10:00:00Z"
    assert body["mission"]["topic"] == "Linear algebra"
    assert body["mission"]["level"] == "intermediate"
    assert body["last_session"]["summary"] == "Reviewed eigenvalues and eigenvectors"
    assert body["last_session"]["next_focus"] == "SVD applications"
    assert [record["id"] for record in body["records"]] == ["rec-1", "rec-2"]
    assert body["records"][0]["insight"] == "Eigenvectors only get scaled, not rotated"


def test_corrupt_journal_degrades_to_empty(workspace: Path) -> None:
    _write_journal(workspace, None, raw="{not valid json")
    client = TestClient(_build_app())
    response = client.get("/api/learning-journal")
    assert response.status_code == 200
    assert response.json()["is_empty"] is True


def test_non_object_journal_degrades_to_empty(workspace: Path) -> None:
    _write_journal(workspace, ["not", "a", "journal"])
    client = TestClient(_build_app())
    response = client.get("/api/learning-journal")
    assert response.status_code == 200
    assert response.json()["is_empty"] is True


def test_unreadable_journal_file_degrades_to_empty(workspace: Path) -> None:
    target = workspace / "learning_journal" / "journal.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"\xff\xfe\x00")
    client = TestClient(_build_app())
    response = client.get("/api/learning-journal")
    assert response.status_code == 200
    assert response.json()["is_empty"] is True


def test_partial_journal_drops_unusable_records(workspace: Path) -> None:
    # A record without an id, or without any title/insight text, is dropped
    # instead of failing the whole read — the same tolerance the journal
    # store applies when it parses the file.
    _write_journal(
        workspace,
        {
            "mission": {"topic": "  Spanish  "},
            "records": [
                {"id": "", "title": "no id", "insight": "dropped"},
                {"id": "rec-3"},
                {"id": "rec-4", "insight": "kept"},
            ],
        },
    )
    client = TestClient(_build_app())
    body = client.get("/api/learning-journal").json()
    assert body["mission"]["topic"] == "Spanish"
    assert [record["id"] for record in body["records"]] == ["rec-4"]
    assert body["is_empty"] is False


def test_mission_and_session_fields_coerce_non_strings(workspace: Path) -> None:
    _write_journal(
        workspace,
        {
            "mission": {"topic": 42, "why": None, "level": True},
            "last_session": {"summary": [], "next_focus": {"a": 1}},
        },
    )
    client = TestClient(_build_app())
    body = client.get("/api/learning-journal").json()
    assert body["mission"]["topic"] == "42"
    assert body["mission"]["why"] == ""
    assert body["mission"]["level"] == "True"
    assert body["last_session"]["summary"] == ""
    assert body["last_session"]["next_focus"] == "{'a': 1}"
    # The coerced mission strings are non-empty, so the journal is not empty.
    assert body["is_empty"] is False
