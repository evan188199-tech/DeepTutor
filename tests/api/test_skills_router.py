"""API contract tests for ``deeptutor.api.routers.skills``.

Covers the ``/api/skills`` CRUD surface (tags, list/get/create/update/delete,
install) plus ``get_skill_service`` resolution, with the skill service fully
mocked behind ``TestClient`` — no server, no network, no credentials.

The in-app hub *browse* happy paths live in ``test_skills_hub_router.py``;
this file only adds the hub failure/4xx branches.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import httpx
from pydantic import ValidationError
import pytest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover - optional dependency in lightweight envs
    FastAPI = None
    TestClient = None

pytestmark = pytest.mark.skipif(
    FastAPI is None or TestClient is None, reason="fastapi not installed"
)

from deeptutor.api.routers import skills as skills_router
from deeptutor.services.skill import hub as hub_module
from deeptutor.services.skill import runtime as skill_runtime
from deeptutor.services.skill.hub import ClawHubProvider
from deeptutor.services.skill.service import (
    InvalidSkillNameError,
    InvalidTagError,
    SkillExistsError,
    SkillImportError,
    SkillNotFoundError,
    SkillReadOnlyError,
    TagExistsError,
    TagNotFoundError,
)


@dataclass
class _Info:
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return dict(self.payload)


class FakeSkillService:
    """Route-level double: records calls and raises what a test stages."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.errors: dict[str, Exception] = {}
        self.tags: list[str] = ["tutor"]
        self.own: list[dict[str, Any]] = [{"name": "note-taker", "source": "user"}]
        self.detail: dict[str, Any] = {"name": "note-taker", "content": "# note-taker"}

    def fail(self, method: str, exc: Exception) -> None:
        self.errors[method] = exc

    def _checkpoint(self, method: str) -> None:
        exc = self.errors.get(method)
        if exc is not None:
            raise exc

    def list_tags(self) -> list[str]:
        return list(self.tags)

    def create_tag(self, name: str) -> str:
        self.calls.append(("create_tag", {"name": name}))
        self._checkpoint("create_tag")
        return name

    def rename_tag(self, tag: str, rename_to: str) -> str:
        self.calls.append(("rename_tag", {"tag": tag, "rename_to": rename_to}))
        self._checkpoint("rename_tag")
        return rename_to

    def delete_tag(self, tag: str) -> None:
        self.calls.append(("delete_tag", {"tag": tag}))
        self._checkpoint("delete_tag")

    def list_skills(self) -> list[_Info]:
        self.calls.append(("list_skills", {}))
        return [_Info(item) for item in self.own]

    def get_detail(self, name: str) -> _Info:
        self.calls.append(("get_detail", {"name": name}))
        self._checkpoint("get_detail")
        return _Info(self.detail)

    def create(self, *, name: str, description: str, content: str, tags: list[str]) -> _Info:
        payload = {
            "name": name,
            "description": description,
            "content": content,
            "tags": list(tags),
        }
        self.calls.append(("create", payload))
        self._checkpoint("create")
        return _Info(payload)

    def update(
        self,
        name: str,
        *,
        description: str | None,
        content: str | None,
        rename_to: str | None,
        tags: list[str] | None,
    ) -> _Info:
        payload = {
            "name": name,
            "description": description,
            "content": content,
            "rename_to": rename_to,
            "tags": tags,
        }
        self.calls.append(("update", payload))
        self._checkpoint("update")
        return _Info({"name": rename_to or name})

    def delete(self, name: str) -> None:
        self.calls.append(("delete", {"name": name}))
        self._checkpoint("delete")


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(skills_router.router, prefix="/api/skills")
    return app


def _use_service(monkeypatch: pytest.MonkeyPatch, service: FakeSkillService) -> None:
    monkeypatch.setattr(skills_router, "get_skill_service", lambda: service)


def _as_user(
    monkeypatch: pytest.MonkeyPatch, *, user_id: str = "u-1", is_admin: bool = False
) -> None:
    monkeypatch.setattr(
        skills_router,
        "get_current_user",
        lambda: SimpleNamespace(id=user_id, is_admin=is_admin),
    )


def _use_workspace(monkeypatch: pytest.MonkeyPatch, workspace_id: str = "ws-9") -> None:
    fresh: ContextVar[str] = ContextVar("skill_library_workspace_test", default=workspace_id)
    monkeypatch.setattr(skill_runtime, "library_workspace", fresh)


# ── request model contracts ────────────────────────────────────────


def test_create_skill_request_defaults() -> None:
    payload = skills_router.CreateSkillRequest(name="demo")
    assert payload.description == ""
    assert payload.content == ""
    assert payload.tags == []


def test_update_skill_request_defaults_are_none() -> None:
    payload = skills_router.UpdateSkillRequest()
    assert payload.description is None
    assert payload.content is None
    assert payload.rename_to is None
    assert payload.tags is None


def test_install_skill_request_defaults() -> None:
    payload = skills_router.InstallSkillRequest(ref="eduhub:demo")
    assert payload.name is None
    assert payload.force is False
    assert payload.allow_unverified is False


def test_create_skill_request_rejects_oversized_name() -> None:
    with pytest.raises(ValidationError):
        skills_router.CreateSkillRequest(name="x" * 65)


# ── get_skill_service resolution ───────────────────────────────────


def test_get_skill_service_prefers_workspace_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_workspace(monkeypatch, "ws-9")
    sentinel = object()
    monkeypatch.setattr(skill_runtime, "workspace_skill_service", lambda workspace_id: sentinel)
    assert skills_router.get_skill_service() is sentinel


def test_get_skill_service_falls_back_to_account_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_workspace(monkeypatch, "")
    sentinel = object()
    monkeypatch.setattr(skills_router, "get_account_skill_service", lambda: sentinel)
    assert skills_router.get_skill_service() is sentinel


# ── tag routes ─────────────────────────────────────────────────────


def test_list_tags_returns_service_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = FakeSkillService()
    _use_service(monkeypatch, svc)
    resp = TestClient(_build_app()).get("/api/skills/tags/list")
    assert resp.status_code == 200
    assert resp.json() == {"tags": ["tutor"]}


def test_create_tag_success(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = FakeSkillService()
    _use_service(monkeypatch, svc)
    resp = TestClient(_build_app()).post("/api/skills/tags/create", json={"name": "new"})
    assert resp.status_code == 200
    assert resp.json() == {"name": "new"}
    assert svc.calls == [("create_tag", {"name": "new"})]


def test_create_tag_conflict_maps_to_409(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = FakeSkillService()
    svc.fail("create_tag", TagExistsError("tutor"))
    _use_service(monkeypatch, svc)
    resp = TestClient(_build_app()).post("/api/skills/tags/create", json={"name": "tutor"})
    assert resp.status_code == 409
    assert "Tag already exists" in resp.json()["detail"]


def test_create_tag_invalid_maps_to_400(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = FakeSkillService()
    svc.fail("create_tag", InvalidTagError("bad tag"))
    _use_service(monkeypatch, svc)
    resp = TestClient(_build_app()).post("/api/skills/tags/create", json={"name": "!"})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "bad tag"


def test_create_tag_rejects_blank_name_422(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_service(monkeypatch, FakeSkillService())
    resp = TestClient(_build_app()).post("/api/skills/tags/create", json={"name": ""})
    assert resp.status_code == 422


def test_rename_tag_success(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = FakeSkillService()
    _use_service(monkeypatch, svc)
    resp = TestClient(_build_app()).put("/api/skills/tags/tutor", json={"rename_to": "tutoring"})
    assert resp.status_code == 200
    assert resp.json() == {"name": "tutoring"}
    assert svc.calls == [("rename_tag", {"tag": "tutor", "rename_to": "tutoring"})]


def test_rename_tag_missing_maps_to_404(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = FakeSkillService()
    svc.fail("rename_tag", TagNotFoundError("tutor"))
    _use_service(monkeypatch, svc)
    resp = TestClient(_build_app()).put("/api/skills/tags/tutor", json={"rename_to": "tutoring"})
    assert resp.status_code == 404
    assert "tutor" in resp.json()["detail"]


def test_rename_tag_conflict_maps_to_409(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = FakeSkillService()
    svc.fail("rename_tag", TagExistsError("tutoring"))
    _use_service(monkeypatch, svc)
    resp = TestClient(_build_app()).put("/api/skills/tags/tutor", json={"rename_to": "tutoring"})
    assert resp.status_code == 409


def test_rename_tag_invalid_maps_to_400(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = FakeSkillService()
    svc.fail("rename_tag", InvalidTagError("bad tag"))
    _use_service(monkeypatch, svc)
    resp = TestClient(_build_app()).put("/api/skills/tags/tutor", json={"rename_to": "!"})
    assert resp.status_code == 400


def test_delete_tag_success(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = FakeSkillService()
    _use_service(monkeypatch, svc)
    resp = TestClient(_build_app()).delete("/api/skills/tags/tutor")
    assert resp.status_code == 200
    assert resp.json() == {"status": "deleted", "name": "tutor"}


def test_delete_tag_missing_maps_to_404(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = FakeSkillService()
    svc.fail("delete_tag", TagNotFoundError("tutor"))
    _use_service(monkeypatch, svc)
    resp = TestClient(_build_app()).delete("/api/skills/tags/tutor")
    assert resp.status_code == 404


def test_delete_tag_invalid_maps_to_400(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = FakeSkillService()
    svc.fail("delete_tag", InvalidTagError("bad tag"))
    _use_service(monkeypatch, svc)
    resp = TestClient(_build_app()).delete("/api/skills/tags/tutor")
    assert resp.status_code == 400


# ── list skills ────────────────────────────────────────────────────


def test_list_skills_admin_sees_own_only(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = FakeSkillService()
    _use_service(monkeypatch, svc)
    resp = TestClient(_build_app()).get("/api/skills/list")
    assert resp.status_code == 200
    assert resp.json() == {"skills": [{"name": "note-taker", "source": "user"}]}


def test_list_skills_merges_assigned_for_non_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = FakeSkillService()
    _use_service(monkeypatch, svc)
    _as_user(monkeypatch, is_admin=False)
    monkeypatch.setattr(
        skills_router,
        "assigned_skill_infos",
        lambda user_id: [
            {"name": "assigned-skill", "source": "admin", "assigned": True},
            {"name": "note-taker", "source": "admin", "assigned": True},
        ],
    )
    resp = TestClient(_build_app()).get("/api/skills/list")
    assert resp.status_code == 200
    merged = resp.json()["skills"]
    assert [item["name"] for item in merged] == ["note-taker", "assigned-skill"]
    assert merged[1]["assigned"] is True


def test_list_skills_workspace_scope_skips_assigned_merge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_workspace(monkeypatch, "ws-9")
    svc = FakeSkillService()
    _use_service(monkeypatch, svc)
    _as_user(monkeypatch, is_admin=False)

    def _unexpected(user_id: str) -> list[dict[str, Any]]:
        raise AssertionError("assigned_skill_infos must not be read in workspace scope")

    monkeypatch.setattr(skills_router, "assigned_skill_infos", _unexpected)
    resp = TestClient(_build_app()).get("/api/skills/list")
    assert resp.status_code == 200
    assert [item["name"] for item in resp.json()["skills"]] == ["note-taker"]


# ── get skill ──────────────────────────────────────────────────────


def test_get_skill_returns_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = FakeSkillService()
    _use_service(monkeypatch, svc)
    resp = TestClient(_build_app()).get("/api/skills/note-taker")
    assert resp.status_code == 200
    assert resp.json() == {"name": "note-taker", "content": "# note-taker"}


def test_get_skill_admin_missing_maps_to_404(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = FakeSkillService()
    svc.fail("get_detail", SkillNotFoundError("ghost"))
    _use_service(monkeypatch, svc)
    resp = TestClient(_build_app()).get("/api/skills/ghost")
    assert resp.status_code == 404
    assert "ghost" in resp.json()["detail"]


def test_get_skill_unassigned_non_admin_maps_to_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = FakeSkillService()
    svc.fail("get_detail", SkillNotFoundError("ghost"))
    _use_service(monkeypatch, svc)
    _as_user(monkeypatch, is_admin=False)
    monkeypatch.setattr(skills_router, "assigned_skill_ids", lambda user_id=None: set())
    resp = TestClient(_build_app()).get("/api/skills/ghost")
    assert resp.status_code == 403
    assert "not assigned" in resp.json()["detail"]


def test_get_skill_assigned_non_admin_gets_admin_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = FakeSkillService()
    svc.fail("get_detail", SkillNotFoundError("shared-skill"))
    _use_service(monkeypatch, svc)
    _as_user(monkeypatch, is_admin=False)
    monkeypatch.setattr(skills_router, "assigned_skill_ids", lambda user_id=None: {"shared-skill"})
    monkeypatch.setattr(
        skills_router,
        "assigned_skill_detail",
        lambda name: {"name": name, "source": "admin", "read_only": True},
    )
    resp = TestClient(_build_app()).get("/api/skills/shared-skill")
    assert resp.status_code == 200
    assert resp.json() == {"name": "shared-skill", "source": "admin", "read_only": True}


def test_get_skill_assigned_but_missing_detail_maps_to_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = FakeSkillService()
    svc.fail("get_detail", SkillNotFoundError("ghost"))
    _use_service(monkeypatch, svc)
    _as_user(monkeypatch, is_admin=False)
    monkeypatch.setattr(skills_router, "assigned_skill_ids", lambda user_id=None: {"ghost"})
    monkeypatch.setattr(skills_router, "assigned_skill_detail", lambda name: None)
    resp = TestClient(_build_app()).get("/api/skills/ghost")
    assert resp.status_code == 404


def test_get_skill_invalid_name_maps_to_400(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = FakeSkillService()
    svc.fail("get_detail", InvalidSkillNameError("bad name"))
    _use_service(monkeypatch, svc)
    resp = TestClient(_build_app()).get("/api/skills/bad%20name")
    assert resp.status_code == 400


# ── create skill ───────────────────────────────────────────────────


def test_create_skill_success_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = FakeSkillService()
    _use_service(monkeypatch, svc)
    body = {"name": "demo", "description": "d", "content": "c", "tags": ["a"]}
    resp = TestClient(_build_app()).post("/api/skills/create", json=body)
    assert resp.status_code == 200
    assert resp.json() == body
    assert svc.calls == [("create", body)]


def test_create_skill_conflict_maps_to_409(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = FakeSkillService()
    svc.fail("create", SkillExistsError("demo"))
    _use_service(monkeypatch, svc)
    resp = TestClient(_build_app()).post("/api/skills/create", json={"name": "demo"})
    assert resp.status_code == 409
    assert "demo" in resp.json()["detail"]


def test_create_skill_invalid_name_maps_to_400(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = FakeSkillService()
    svc.fail("create", InvalidSkillNameError("bad name"))
    _use_service(monkeypatch, svc)
    resp = TestClient(_build_app()).post("/api/skills/create", json={"name": "bad name"})
    assert resp.status_code == 400


def test_create_skill_invalid_tag_maps_to_400(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = FakeSkillService()
    svc.fail("create", InvalidTagError("bad tag"))
    _use_service(monkeypatch, svc)
    resp = TestClient(_build_app()).post("/api/skills/create", json={"name": "demo", "tags": ["!"]})
    assert resp.status_code == 400


def test_create_skill_blank_name_rejected_422(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_service(monkeypatch, FakeSkillService())
    resp = TestClient(_build_app()).post("/api/skills/create", json={"name": ""})
    assert resp.status_code == 422


def test_create_skill_oversized_name_rejected_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_service(monkeypatch, FakeSkillService())
    resp = TestClient(_build_app()).post("/api/skills/create", json={"name": "x" * 65})
    assert resp.status_code == 422


# ── update skill ───────────────────────────────────────────────────


def test_update_skill_success_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = FakeSkillService()
    _use_service(monkeypatch, svc)
    body = {
        "description": "d",
        "content": "c",
        "rename_to": "renamed",
        "tags": ["a", "b"],
    }
    resp = TestClient(_build_app()).put("/api/skills/demo", json=body)
    assert resp.status_code == 200
    assert resp.json() == {"name": "renamed"}
    assert svc.calls == [("update", {"name": "demo", **body})]


def test_update_skill_missing_maps_to_404(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = FakeSkillService()
    svc.fail("update", SkillNotFoundError("ghost"))
    _use_service(monkeypatch, svc)
    resp = TestClient(_build_app()).put("/api/skills/ghost", json={})
    assert resp.status_code == 404
    assert "ghost" in resp.json()["detail"]


def test_update_skill_read_only_maps_to_403(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = FakeSkillService()
    svc.fail("update", SkillReadOnlyError("builtin"))
    _use_service(monkeypatch, svc)
    resp = TestClient(_build_app()).put("/api/skills/builtin", json={})
    assert resp.status_code == 403


def test_update_skill_rename_conflict_maps_to_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = FakeSkillService()
    svc.fail("update", SkillExistsError("taken"))
    _use_service(monkeypatch, svc)
    resp = TestClient(_build_app()).put("/api/skills/demo", json={"rename_to": "taken"})
    assert resp.status_code == 409


def test_update_skill_invalid_name_maps_to_400(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = FakeSkillService()
    svc.fail("update", InvalidSkillNameError("bad name"))
    _use_service(monkeypatch, svc)
    resp = TestClient(_build_app()).put("/api/skills/demo", json={})
    assert resp.status_code == 400


def test_update_skill_invalid_tag_maps_to_400(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = FakeSkillService()
    svc.fail("update", InvalidTagError("bad tag"))
    _use_service(monkeypatch, svc)
    resp = TestClient(_build_app()).put("/api/skills/demo", json={"tags": ["!"]})
    assert resp.status_code == 400


# ── delete skill ───────────────────────────────────────────────────


def test_delete_skill_success(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = FakeSkillService()
    _use_service(monkeypatch, svc)
    resp = TestClient(_build_app()).delete("/api/skills/demo")
    assert resp.status_code == 200
    assert resp.json() == {"status": "deleted", "name": "demo"}
    assert svc.calls == [("delete", {"name": "demo"})]


def test_delete_skill_missing_maps_to_404(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = FakeSkillService()
    svc.fail("delete", SkillNotFoundError("ghost"))
    _use_service(monkeypatch, svc)
    resp = TestClient(_build_app()).delete("/api/skills/ghost")
    assert resp.status_code == 404


def test_delete_skill_read_only_maps_to_403(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = FakeSkillService()
    svc.fail("delete", SkillReadOnlyError("builtin"))
    _use_service(monkeypatch, svc)
    resp = TestClient(_build_app()).delete("/api/skills/builtin")
    assert resp.status_code == 403


def test_delete_skill_invalid_name_maps_to_400(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = FakeSkillService()
    svc.fail("delete", InvalidSkillNameError("bad name"))
    _use_service(monkeypatch, svc)
    resp = TestClient(_build_app()).delete("/api/skills/bad-name")
    assert resp.status_code == 400


# ── install skill ──────────────────────────────────────────────────


def _install_outcome(name: str = "demo") -> SimpleNamespace:
    return SimpleNamespace(
        result=SimpleNamespace(info=_Info({"name": name})),
        ref=SimpleNamespace(version="1.0.0"),
        verdict=SimpleNamespace(status="ok", detail="hub vouches"),
    )


def test_install_skill_success(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = FakeSkillService()
    _use_service(monkeypatch, svc)
    seen: dict[str, Any] = {}

    def fake_install(ref: str, **kwargs: Any) -> SimpleNamespace:
        seen.update(ref=ref, **kwargs)
        return _install_outcome()

    monkeypatch.setattr(hub_module, "install_from_hub", fake_install)
    resp = TestClient(_build_app()).post(
        "/api/skills/install",
        json={"ref": "eduhub:demo", "name": "local-name", "force": True, "allow_unverified": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["skill"] == {"name": "demo"}
    assert body["verdict"] == {"status": "ok", "detail": "hub vouches"}
    assert body["version"] == "1.0.0"
    assert seen["ref"] == "eduhub:demo"
    assert seen["service"] is svc
    assert seen["rename_to"] == "local-name"
    assert seen["force"] is True
    assert seen["allow_unverified"] is True


def test_install_skill_conflict_maps_to_409(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_service(monkeypatch, FakeSkillService())
    monkeypatch.setattr(
        hub_module,
        "install_from_hub",
        lambda ref, **kwargs: (_ for _ in ()).throw(SkillExistsError("demo")),
    )
    resp = TestClient(_build_app()).post("/api/skills/install", json={"ref": "eduhub:demo"})
    assert resp.status_code == 409


def test_install_skill_import_error_maps_to_400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_service(monkeypatch, FakeSkillService())
    monkeypatch.setattr(
        hub_module,
        "install_from_hub",
        lambda ref, **kwargs: (_ for _ in ()).throw(SkillImportError("bad package")),
    )
    resp = TestClient(_build_app()).post("/api/skills/install", json={"ref": "eduhub:demo"})
    assert resp.status_code == 400


def test_install_skill_invalid_name_maps_to_400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_service(monkeypatch, FakeSkillService())
    monkeypatch.setattr(
        hub_module,
        "install_from_hub",
        lambda ref, **kwargs: (_ for _ in ()).throw(InvalidSkillNameError("bad name")),
    )
    resp = TestClient(_build_app()).post("/api/skills/install", json={"ref": "eduhub:demo"})
    assert resp.status_code == 400


def test_install_skill_hub_error_maps_to_502(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_service(monkeypatch, FakeSkillService())
    monkeypatch.setattr(
        hub_module,
        "install_from_hub",
        lambda ref, **kwargs: (_ for _ in ()).throw(hub_module.HubError("hub down")),
    )
    resp = TestClient(_build_app()).post("/api/skills/install", json={"ref": "eduhub:demo"})
    assert resp.status_code == 502


def test_install_skill_blank_ref_rejected_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_service(monkeypatch, FakeSkillService())
    resp = TestClient(_build_app()).post("/api/skills/install", json={"ref": ""})
    assert resp.status_code == 422


def test_install_skill_oversized_ref_rejected_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_service(monkeypatch, FakeSkillService())
    resp = TestClient(_build_app()).post("/api/skills/install", json={"ref": "x" * 257})
    assert resp.status_code == 422


# ── hub browse failure branches (happy paths: test_skills_hub_router.py) ──


class _FailingCatalogProvider(ClawHubProvider):
    def catalog(self, *, query: str = "", limit: int = 50, sort: str = "createdAt"):
        raise hub_module.HubError("hub down")


class _FailingDetailProvider(ClawHubProvider):
    def detail(self, slug: str):
        raise hub_module.HubError("hub down")


def _idle_client() -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(500)))


def test_hub_catalog_unknown_hub_maps_to_400(monkeypatch: pytest.MonkeyPatch) -> None:
    def _unknown(name: str):
        raise hub_module.HubError(f"unknown hub: {name}")

    monkeypatch.setattr(hub_module, "get_hub_provider", _unknown)
    resp = TestClient(_build_app()).get("/api/skills/hub/catalog")
    assert resp.status_code == 400
    assert "unknown hub" in resp.json()["detail"]


def test_hub_catalog_non_browsable_hub_maps_to_400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        hub_module,
        "get_hub_provider",
        lambda name: SimpleNamespace(name="static", web_origin="https://static.example"),
    )
    resp = TestClient(_build_app()).get("/api/skills/hub/catalog")
    assert resp.status_code == 400
    assert "does not support browsing" in resp.json()["detail"]


def test_hub_catalog_provider_failure_maps_to_502(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _FailingCatalogProvider(client=_idle_client())
    monkeypatch.setattr(hub_module, "get_hub_provider", lambda name: provider)
    resp = TestClient(_build_app()).get("/api/skills/hub/catalog")
    assert resp.status_code == 502
    provider._client.close()


def test_hub_detail_provider_failure_maps_to_502(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _FailingDetailProvider(client=_idle_client())
    monkeypatch.setattr(hub_module, "get_hub_provider", lambda name: provider)
    resp = TestClient(_build_app()).get("/api/skills/hub/detail", params={"slug": "demo"})
    assert resp.status_code == 502
    provider._client.close()
