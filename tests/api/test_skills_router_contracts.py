"""HTTP contract tests for the skills CRUD and tag routes.

The hub browser endpoints have coverage in ``test_skills_hub_router.py``;
these tests exercise the mounted account-level CRUD surface: status codes,
validation errors, and conflict mapping for skills and tags.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from deeptutor.api.routers import auth as auth_router
from deeptutor.api.routers import skills as skills_router
from deeptutor.services.auth import TokenPayload
from deeptutor.services.skill.service import SkillService


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    service = SkillService(root=tmp_path / "skills", builtin_root=tmp_path / "no-builtin")
    monkeypatch.setattr(skills_router, "get_skill_service", lambda: service)
    return TestClient(_make_app())


def _make_app(*, auth_guard: bool = False) -> FastAPI:
    app = FastAPI()
    dependencies = [Depends(auth_router.require_learning_surface)] if auth_guard else None
    app.include_router(skills_router.router, prefix="/api/skills", dependencies=dependencies)
    return app


def test_create_get_list_round_trip(client: TestClient) -> None:
    created = client.post(
        "/api/skills/create",
        json={"name": "coach", "description": "Socratic coach", "content": "# coach"},
    )
    assert created.status_code == 200
    assert created.json()["name"] == "coach"

    fetched = client.get("/api/skills/coach")
    assert fetched.status_code == 200
    assert fetched.json()["description"] == "Socratic coach"

    listed = client.get("/api/skills/list")
    assert listed.status_code == 200
    assert [s["name"] for s in listed.json()["skills"]] == ["coach"]


def test_create_duplicate_returns_409(client: TestClient) -> None:
    payload = {"name": "coach", "description": "", "content": ""}
    assert client.post("/api/skills/create", json=payload).status_code == 200
    conflict = client.post("/api/skills/create", json=payload)
    assert conflict.status_code == 409


def test_create_rejects_invalid_name_with_400(client: TestClient) -> None:
    res = client.post("/api/skills/create", json={"name": "Bad Name!"})
    assert res.status_code == 400


def test_create_rejects_blank_name_with_422(client: TestClient) -> None:
    res = client.post("/api/skills/create", json={"name": ""})
    assert res.status_code == 422


def test_get_update_delete_missing_skill_404(client: TestClient) -> None:
    assert client.get("/api/skills/ghost").status_code == 404
    assert client.put("/api/skills/ghost", json={"description": "x"}).status_code == 404
    assert client.delete("/api/skills/ghost").status_code == 404


def test_update_and_delete_round_trip(client: TestClient) -> None:
    assert client.post("/api/skills/create", json={"name": "temp"}).status_code == 200
    updated = client.put("/api/skills/temp", json={"description": "fresh"})
    assert updated.status_code == 200
    assert updated.json()["description"] == "fresh"

    deleted = client.delete("/api/skills/temp")
    assert deleted.status_code == 200
    assert deleted.json() == {"status": "deleted", "name": "temp"}
    assert client.get("/api/skills/temp").status_code == 404


def test_tag_lifecycle_round_trip(client: TestClient) -> None:
    created = client.post("/api/skills/tags/create", json={"name": "tutoring"})
    assert created.status_code == 200
    assert created.json() == {"name": "tutoring"}

    tags = client.get("/api/skills/tags/list").json()["tags"]
    assert "tutoring" in tags

    renamed = client.put("/api/skills/tags/tutoring", json={"rename_to": "teaching"})
    assert renamed.status_code == 200
    assert renamed.json() == {"name": "teaching"}
    tags = client.get("/api/skills/tags/list").json()["tags"]
    assert "teaching" in tags
    assert "tutoring" not in tags

    noop = client.put("/api/skills/tags/teaching", json={"rename_to": "teaching"})
    assert noop.status_code == 200
    assert noop.json() == {"name": "teaching"}

    deleted = client.delete("/api/skills/tags/teaching")
    assert deleted.status_code == 200
    assert "teaching" not in client.get("/api/skills/tags/list").json()["tags"]


def test_tag_error_mapping(client: TestClient) -> None:
    assert client.post("/api/skills/tags/create", json={"name": "tutoring"}).status_code == 200
    assert client.post("/api/skills/tags/create", json={"name": "other"}).status_code == 200
    assert client.post("/api/skills/tags/create", json={"name": "tutoring"}).status_code == 409
    assert client.post("/api/skills/tags/create", json={"name": "Bad Tag!"}).status_code == 400
    assert client.put("/api/skills/tags/ghost", json={"rename_to": "other"}).status_code == 404
    assert client.put("/api/skills/tags/tutoring", json={"rename_to": "other"}).status_code == 409
    assert client.delete("/api/skills/tags/ghost").status_code == 404


def test_auth_gate_blocks_anonymous_and_accepts_valid_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = SkillService(root=tmp_path / "skills", builtin_root=tmp_path / "no-builtin")
    monkeypatch.setattr(skills_router, "get_skill_service", lambda: service)
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    tokens: dict[str, TokenPayload | None] = {
        "tok-ok": TokenPayload(username="alice", role="admin", user_id="u-1")
    }
    monkeypatch.setattr(auth_router, "decode_token", lambda token: tokens.get(token))
    client = TestClient(_make_app(auth_guard=True))

    assert client.get("/api/skills/list").status_code == 401
    assert (
        client.get("/api/skills/list", headers={"Authorization": "Bearer tok-bad"}).status_code
        == 401
    )
    assert (
        client.get("/api/skills/list", headers={"Authorization": "Bearer tok-ok"}).status_code
        == 200
    )
