"""The structured error envelope is part of the rendered REST contract.

FastAPI does not document manually raised ``HTTPException``s, so the
``{"detail": {"code", "message", ...}}`` refusals these routers emit were
invisible to the generated contract (openapi-drift scan 2026-10-06: 0 of 44
affected operations documented any of them). The routes now declare the
envelope in ``responses=`` — declaratively only: no status code or message
changes. Each test here pins one half of that promise per router: the
rendered OpenAPI carries the model where the refusal is emitted, and the live
refusal body still validates against the documented model.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import notebook as notebook_router
from deeptutor.api.routers import settings as settings_router
from deeptutor.api.routers import space_cli_apps, space_mcp, video_learning
from deeptutor.api.routers._error_envelope import (
    CliInstallErrorResponse,
    NotebookUnreadableErrorResponse,
    StructuredErrorResponse,
)
from deeptutor.services.cli_apps.models import AppRuntime, InstallKind
from deeptutor.services.cli_apps.paths import abi_stamp
from deeptutor.services.cli_apps.state import InstalledApp, record_install
from deeptutor.services.codex_auth import CodexAuthError
from deeptutor.services.notebook.service import NotebookManager
from deeptutor.video_learning import service as video_service

# ─────────────────────────────────────────────────────────────────────────────
# OpenAPI rendering
# ─────────────────────────────────────────────────────────────────────────────


def _mounted(*routers: Any) -> FastAPI:
    app = FastAPI()
    for router, prefix in routers:
        app.include_router(router, prefix=prefix)
    return app


def _response_ref(schema: dict, path: str, method: str, status: int) -> str:
    """The component a rendered response entry points at, as JSON."""

    entry = schema["paths"][path][method]["responses"][str(status)]
    media_types = list(entry["content"])
    assert media_types == ["application/json"], (
        f"{method} {path} {status} documented as {media_types}, not JSON"
    )
    ref = entry["content"]["application/json"]["schema"]["$ref"]
    return ref.rsplit("/", 1)[-1]


def test_space_mcp_refusals_render_the_envelope() -> None:
    schema = _mounted((space_mcp.router, "/api/space/mcp")).openapi()

    assert (
        _response_ref(schema, "/api/space/mcp/servers/{name}", "put", 400)
        == StructuredErrorResponse.__name__
    )
    assert (
        _response_ref(schema, "/api/space/mcp/servers/{name}/authorize", "post", 400)
        == StructuredErrorResponse.__name__
    )
    install = schema["paths"]["/api/space/mcp/catalog/{entry_id}/install"]["post"]["responses"]
    assert (
        _response_ref(schema, "/api/space/mcp/catalog/{entry_id}/install", "post", 400)
        == StructuredErrorResponse.__name__
    )
    assert (
        _response_ref(schema, "/api/space/mcp/catalog/{entry_id}/install", "post", 403)
        == StructuredErrorResponse.__name__
    )
    assert "403" in install


def test_space_cli_apps_refusals_render_the_envelope() -> None:
    schema = _mounted((space_cli_apps.router, "/api/space/cli-apps")).openapi()

    assert (
        _response_ref(schema, "/api/space/cli-apps/apps/{app_id}/enabled", "put", 403)
        == StructuredErrorResponse.__name__
    )
    assert (
        _response_ref(schema, "/api/space/cli-apps/catalog/{app_id}/install", "post", 400)
        == CliInstallErrorResponse.__name__
    )


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/notebooks"),
        ("get", "/api/notebooks/statistics"),
        ("post", "/api/notebooks"),
        ("get", "/api/notebooks/{notebook_id}"),
        ("put", "/api/notebooks/{notebook_id}"),
        ("delete", "/api/notebooks/{notebook_id}"),
        ("post", "/api/notebooks/actions/add-record"),
        ("delete", "/api/notebooks/{notebook_id}/records/{record_id}"),
        ("put", "/api/notebooks/{notebook_id}/records/{record_id}"),
        ("post", "/api/notebooks/{notebook_id}/records/{record_id}/actions/copy"),
        ("post", "/api/notebooks/{notebook_id}/records/{record_id}/actions/move"),
        # The export route answers 200 as text/plain; its refusal stays JSON.
        ("get", "/api/notebooks/{notebook_id}/export"),
    ],
)
def test_every_notebook_refusal_renders_the_envelope(method: str, path: str) -> None:
    schema = _mounted((notebook_router.router, "/api")).openapi()

    assert _response_ref(schema, path, method, 409) == NotebookUnreadableErrorResponse.__name__


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/video-learning/materials/{material_id}/notes"),
        ("get", "/api/video-learning/materials/{material_id}/notes.md"),
        ("post", "/api/video-learning/materials/{material_id}/notes"),
        ("put", "/api/video-learning/materials/{material_id}/notes/{note_id}"),
        ("delete", "/api/video-learning/materials/{material_id}/notes/{note_id}"),
    ],
)
def test_every_video_note_refusal_renders_the_envelope(method: str, path: str) -> None:
    schema = _mounted((video_learning.router, "/api/video-learning")).openapi()

    assert _response_ref(schema, path, method, 409) == NotebookUnreadableErrorResponse.__name__


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/api/settings/providers/openai-codex/oauth/start"),
        ("get", "/api/settings/providers/openai-codex/oauth/status"),
        ("post", "/api/settings/providers/openai-codex/oauth/complete"),
        ("post", "/api/settings/providers/openai-codex/oauth/cancel"),
        ("post", "/api/settings/providers/openai-codex/oauth/logout"),
        ("post", "/api/settings/providers/openai-codex/models/refresh"),
        ("post", "/api/settings/providers/openai-codex/models/reasoning-effort"),
    ],
)
@pytest.mark.parametrize("status", [400, 401, 404, 408, 409, 429])
def test_codex_refusals_render_the_envelope(method: str, path: str, status: int) -> None:
    schema = _mounted((settings_router.router, "/api/settings")).openapi()

    assert _response_ref(schema, path, method, status) == StructuredErrorResponse.__name__


def test_codex_validation_422_keeps_its_own_shape() -> None:
    """The envelope documents domain refusals, not request validation."""

    schema = _mounted((settings_router.router, "/api/settings")).openapi()
    entry = schema["paths"]["/api/settings/providers/openai-codex/oauth/complete"]["post"][
        "responses"
    ]["422"]

    ref = entry["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("HTTPValidationError"), entry


def test_envelope_components_are_defined() -> None:
    schema = _mounted(
        (space_mcp.router, "/api/space/mcp"),
        (space_cli_apps.router, "/api/space/cli-apps"),
        (notebook_router.router, "/api"),
        (video_learning.router, "/api/video-learning"),
        (settings_router.router, "/api/settings"),
    ).openapi()

    components = schema["components"]["schemas"]
    for name in (
        "StructuredErrorEnvelope",
        "StructuredErrorResponse",
        "CliInstallErrorEnvelope",
        "CliInstallErrorResponse",
        "NotebookUnreadableErrorEnvelope",
        "NotebookUnreadableErrorResponse",
    ):
        assert name in components, name
    # The extras the subclasses document are part of the contract.
    assert "log" in components["CliInstallErrorEnvelope"]["properties"]
    assert "notebook_id" in components["NotebookUnreadableErrorEnvelope"]["properties"]


# ─────────────────────────────────────────────────────────────────────────────
# The live refusal bodies match the documented models
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def mcp_owner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from deeptutor.multi_user import paths

    admin_root = (tmp_path / "data").resolve()
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(paths, "USERS_ROOT", admin_root / "users")
    monkeypatch.setattr(paths, "SYSTEM_ROOT", admin_root / "system")
    monkeypatch.setattr(paths, "_path_services", {})
    monkeypatch.setattr(space_mcp, "current_owner_id", lambda: "u_ada")
    monkeypatch.setattr(
        "deeptutor.services.mcp.config.mcp_config_path", lambda: tmp_path / "admin-mcp.json"
    )


def test_space_mcp_refusal_body_matches_the_envelope(mcp_owner: None) -> None:
    app = _mounted((space_mcp.router, "/api/space/mcp"))
    with TestClient(app) as client:
        resp = client.put(
            "/api/space/mcp/servers/local",
            json={"config": {"command": "/bin/sh"}, "secrets": {}},
        )

    assert resp.status_code == 400
    envelope = StructuredErrorResponse.model_validate(resp.json())
    assert envelope.detail.code == "mcp.stdio_not_allowed"
    assert envelope.detail.message


@pytest.fixture
def cli_caller(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from deeptutor.multi_user import paths

    admin_root = (tmp_path / "data").resolve()
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(paths, "USERS_ROOT", admin_root / "users")
    monkeypatch.setattr(paths, "SYSTEM_ROOT", admin_root / "system")
    monkeypatch.setattr(paths, "_path_services", {})
    monkeypatch.setattr(space_cli_apps, "current_owner_id", lambda: "u_ada")
    monkeypatch.setattr(space_cli_apps, "allowed_cli_apps", lambda: set())
    monkeypatch.setattr(space_cli_apps, "exec_override", lambda: None)
    record_install(
        InstalledApp(
            id="blender",
            entry_point="cli-anything-blender",
            runtime=AppRuntime.PYTHON,
            kind=InstallKind.PINNED_HARNESS,
            target="git+https://example.invalid/x.git@abc",
            pin="abc",
            abi=abi_stamp(),
            installed_at="2026-07-29T00:00:00+00:00",
        )
    )


def test_space_cli_apps_refusal_body_matches_the_envelope(cli_caller: None) -> None:
    app = _mounted((space_cli_apps.router, "/api/space/cli-apps"))
    with TestClient(app) as client:
        resp = client.put("/api/space/cli-apps/apps/blender/enabled", json={"enabled": True})

    assert resp.status_code == 403
    envelope = StructuredErrorResponse.model_validate(resp.json())
    assert envelope.detail.code == "cli.not_granted"
    assert envelope.detail.message


def test_notebook_refusal_body_matches_the_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = NotebookManager(base_dir=str(tmp_path / "notebooks"))
    monkeypatch.setattr(notebook_router, "notebook_manager", manager)
    (manager.base_dir / "broken01.json").write_text("{ not json", encoding="utf-8")

    app = _mounted((notebook_router.router, "/api"))
    with TestClient(app) as client:
        resp = client.get("/api/notebooks/broken01")

    assert resp.status_code == 409
    envelope = NotebookUnreadableErrorResponse.model_validate(resp.json())
    assert envelope.detail.code == "notebook_unreadable"
    assert envelope.detail.notebook_id == "broken01"


def test_codex_refusal_body_matches_the_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.multi_user.models import CurrentUser, UserScope

    class _Refusing:
        async def start_login(self) -> dict[str, Any]:
            raise CodexAuthError("codex.state_mismatch", "Sign-in session expired.", 409)

    monkeypatch.setattr(settings_router, "get_codex_oauth_service", lambda: _Refusing())
    monkeypatch.setattr(
        settings_router,
        "get_current_user",
        lambda: CurrentUser(
            id="u_alice",
            username="u_alice",
            role="user",
            scope=UserScope(kind="user", user_id="u_alice", root=tmp_path / "alice"),
        ),
    )

    app = _mounted((settings_router.router, "/api/settings"))
    with TestClient(app) as client:
        resp = client.post("/api/settings/providers/openai-codex/oauth/start")

    assert resp.status_code == 409
    envelope = StructuredErrorResponse.model_validate(resp.json())
    assert envelope.detail.code == "codex.state_mismatch"
    assert envelope.detail.message == "Sign-in session expired."


def test_video_note_refusal_body_matches_the_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Paths:
        def get_workspace_feature_dir(self, feature: str) -> Path:
            assert feature == "timed_media"
            return tmp_path / feature

    monkeypatch.setattr(
        "deeptutor.video_learning.service.get_current_path_service", lambda: _Paths()
    )
    manager = NotebookManager(base_dir=str(tmp_path / "notebooks"))
    monkeypatch.setattr("deeptutor.video_learning.notes.get_notebook_manager", lambda: manager)
    material_id = video_service.material_id_for("dQw4w9WgXcQ")
    video_service.get_timed_media_store().save(
        {
            "version": 1,
            "type": "timed_media",
            "material_id": material_id,
            "source": {"provider": "youtube", "video_id": "dQw4w9WgXcQ"},
            "metadata": {"duration_seconds": 100},
            "transcript": {"status": "ready", "cues": []},
            "learning": {"last_position": 0},
        }
    )
    (manager.base_dir / "broken01.json").write_text("{ not json", encoding="utf-8")

    app = _mounted((video_learning.router, "/api/video-learning"))
    with TestClient(app) as client:
        resp = client.get(f"/api/video-learning/materials/{material_id}/notes")

    assert resp.status_code == 409
    envelope = NotebookUnreadableErrorResponse.model_validate(resp.json())
    assert envelope.detail.code == "notebook_unreadable"
    assert envelope.detail.notebook_id == "broken01"
