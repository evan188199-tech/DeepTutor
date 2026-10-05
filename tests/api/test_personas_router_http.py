"""HTTP contract tests for the personas CRUD router.

The existing ``test_personas_router.py`` covers the preset-merge logic by
calling the handlers directly; these tests exercise the mounted HTTP surface:
status codes, validation errors, conflict mapping, and the auth gate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from deeptutor.api.routers import auth as auth_router
from deeptutor.api.routers import personas as personas_router
from deeptutor.services.auth import TokenPayload
from deeptutor.services.persona import PersonaService


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    presets = PersonaService(root=tmp_path / "account" / "personas")
    active = PersonaService(root=tmp_path / "ws-1" / "personas")
    monkeypatch.setattr(personas_router, "_admin_persona_service", lambda: presets)
    monkeypatch.setattr(personas_router, "get_persona_service", lambda: active)
    return TestClient(_make_app())


def _make_app(*, auth_guard: bool = False) -> FastAPI:
    app = FastAPI()
    dependencies = [Depends(auth_router.require_learning_surface)] if auth_guard else None
    app.include_router(personas_router.router, prefix="/api", dependencies=dependencies)
    return app


def test_create_get_update_round_trip(client: TestClient) -> None:
    created = client.post(
        "/api/personas",
        json={"name": "coach", "description": "Socratic coach", "content": "Ask, don't tell."},
    )
    assert created.status_code == 200
    assert created.json()["name"] == "coach"

    fetched = client.get("/api/personas/coach")
    assert fetched.status_code == 200
    assert fetched.json()["description"] == "Socratic coach"

    listed = client.get("/api/personas")
    assert listed.status_code == 200
    assert [p["name"] for p in listed.json()["personas"]] == ["coach"]

    updated = client.put("/api/personas/coach", json={"description": "Kind coach"})
    assert updated.status_code == 200
    assert updated.json()["description"] == "Kind coach"
    assert "Ask, don't tell." in client.get("/api/personas/coach").json()["content"]


def test_create_duplicate_returns_409(client: TestClient) -> None:
    payload = {"name": "coach", "description": "", "content": ""}
    assert client.post("/api/personas", json=payload).status_code == 200
    conflict = client.post("/api/personas", json=payload)
    assert conflict.status_code == 409


def test_create_rejects_invalid_name_with_400(client: TestClient) -> None:
    res = client.post("/api/personas", json={"name": "Bad Name!", "description": ""})
    assert res.status_code == 400


def test_create_rejects_blank_name_with_422(client: TestClient) -> None:
    res = client.post("/api/personas", json={"name": "", "description": ""})
    assert res.status_code == 422


def test_get_unknown_persona_returns_404(client: TestClient) -> None:
    res = client.get("/api/personas/ghost")
    assert res.status_code == 404


def test_update_unknown_persona_returns_404(client: TestClient) -> None:
    res = client.put("/api/personas/ghost", json={"description": "x"})
    assert res.status_code == 404


def test_rename_to_existing_name_conflicts_409(client: TestClient) -> None:
    for name in ("alpha", "beta"):
        assert (
            client.post("/api/personas", json={"name": name, "description": ""}).status_code == 200
        )
    res = client.put("/api/personas/alpha", json={"rename_to": "beta"})
    assert res.status_code == 409


def test_delete_round_trip_and_missing_404(client: TestClient) -> None:
    assert client.post("/api/personas", json={"name": "temp", "description": ""}).status_code == 200
    deleted = client.delete("/api/personas/temp")
    assert deleted.status_code == 200
    assert deleted.json() == {"status": "deleted", "name": "temp"}
    assert client.get("/api/personas/temp").status_code == 404
    assert client.delete("/api/personas/temp").status_code == 404


def test_auth_gate_blocks_anonymous_and_accepts_valid_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    presets = PersonaService(root=tmp_path / "account" / "personas")
    monkeypatch.setattr(personas_router, "_admin_persona_service", lambda: presets)
    monkeypatch.setattr(
        personas_router,
        "get_persona_service",
        lambda: PersonaService(root=tmp_path / "ws-1" / "personas"),
    )
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    tokens: dict[str, TokenPayload | None] = {
        "tok-ok": TokenPayload(username="alice", role="admin", user_id="u-1")
    }
    monkeypatch.setattr(auth_router, "decode_token", lambda token: tokens.get(token))
    client = TestClient(_make_app(auth_guard=True))

    assert client.get("/api/personas").status_code == 401
    assert (
        client.get("/api/personas", headers={"Authorization": "Bearer tok-bad"}).status_code == 401
    )
    assert (
        client.get("/api/personas", headers={"Authorization": "Bearer tok-ok"}).status_code == 200
    )
