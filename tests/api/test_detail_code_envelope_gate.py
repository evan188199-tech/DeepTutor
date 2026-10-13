"""Gate: already-converted routers must keep emitting the ``code`` envelope.

Several routers were promoted from plaintext 4xx details to structured
``detail = {"code": ..., ...}`` payloads (the detail-inventory scan of
2026-10-11). The frontend keys its error toasts off ``detail.code``, so a
regression back to a bare string quietly degrades every error message this
app shows for those routes.

This file is an independent gate surface — it does not replace the
per-card tests that introduced each envelope, it walks one representative
4xx emission point per converted route file and pins two things per case:
the response status, and a ``detail`` that still carries ``code``.

Everything here runs against FastAPI's ``TestClient``; no server is started.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import notebook as notebook_router_module
from deeptutor.api.routers import settings as settings_router
from deeptutor.api.routers import space_cli_apps, space_mcp, video_learning
from deeptutor.services.codex_auth.contracts import CodexAuthError
from deeptutor.services.mcp import MCPServerConfig
from deeptutor.services.mcp.config import MCPConfig
from deeptutor.services.notebook.service import NotebookManager
from deeptutor.video_learning import notes as video_notes
from deeptutor.video_learning import service as video_service

CLI_APP = "blender"
VIDEO_SOURCE_ID = "dQw4w9WgXcQ"


@pytest.fixture(autouse=True)
def _isolated_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every case away from the developer's real data roots."""
    from deeptutor.multi_user import paths

    admin_root = (tmp_path / "data").resolve()
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(paths, "USERS_ROOT", admin_root / "users")
    monkeypatch.setattr(paths, "SYSTEM_ROOT", admin_root / "system")
    monkeypatch.setattr(paths, "_path_services", {})
    admin_root.mkdir(parents=True, exist_ok=True)


@pytest.fixture(autouse=True)
def _offline_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the lookup is stubbed; the address policy itself still runs."""
    import socket

    def _getaddrinfo(host: str, *args: object, **kwargs: object) -> list[tuple]:
        loopback = host in {"localhost", "127.0.0.1", "::1"}
        addr = "127.0.0.1" if loopback else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, 0))]

    monkeypatch.setattr("deeptutor.services.mcp.network.socket.getaddrinfo", _getaddrinfo)


# ── space_mcp ─────────────────────────────────────────────────────────────


@pytest.fixture
def mcp_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    class _Manager:
        async def reload_scope(self, owner_id: str) -> None: ...
        async def ensure_started(self) -> None: ...
        async def ensure_scope(self, owner_id: str) -> list[Any]:
            return []

        def status(self, owner_id: str = "_shared") -> list[dict[str, Any]]:
            return []

    monkeypatch.setattr(space_mcp, "current_owner_id", lambda: "u_ada")
    monkeypatch.setattr(space_mcp, "get_mcp_manager", lambda: _Manager())
    app = FastAPI()
    app.include_router(space_mcp.router, prefix="/api/space/mcp")
    return TestClient(app)


def _patch_mcp_scenario(monkeypatch: pytest.MonkeyPatch, scenario: str) -> None:
    """Point the shared MCP services at the state each refusal presupposes."""
    if scenario == "name_reserved":
        monkeypatch.setattr(
            space_mcp,
            "load_mcp_config",
            lambda: MCPConfig(
                servers={"shared-svc": MCPServerConfig(url="https://mcp.example.com/mcp")}
            ),
        )
    elif scenario in {"not_oauth", "oauth_start_failed"}:
        cfg = MCPServerConfig(url="https://mcp.example.com/mcp")
        if scenario == "oauth_start_failed":
            cfg = MCPServerConfig(url="https://mcp.example.com/mcp", auth="oauth")

            async def _fail_begin(*args: object, **kwargs: object) -> str:
                raise RuntimeError("connect refused")

            monkeypatch.setattr(space_mcp.oauth, "begin_authorization", _fail_begin)
        monkeypatch.setattr(
            space_mcp,
            "load_user_mcp_config",
            lambda owner: (MCPConfig(servers={"remote-svc": cfg}), []),
        )


@pytest.mark.parametrize(
    ("scenario", "method", "url", "payload", "expected_status", "expected_code"),
    [
        (
            "name_reserved",
            "PUT",
            "/api/space/mcp/servers/shared-svc",
            {"config": {"url": "https://mcp.example.com/mcp"}, "secrets": {}},
            400,
            "mcp.name_reserved",
        ),
        (
            "not_oauth",
            "POST",
            "/api/space/mcp/servers/remote-svc/authorize",
            None,
            400,
            "mcp.not_oauth",
        ),
        (
            "oauth_start_failed",
            "POST",
            "/api/space/mcp/servers/remote-svc/authorize",
            None,
            400,
            "mcp.oauth_start_failed",
        ),
        (
            "entry_admin_only",
            "POST",
            "/api/space/mcp/catalog/aws-docs/install",
            {},
            403,
            "mcp.entry_admin_only",
        ),
        (
            "missing_credential",
            "POST",
            "/api/space/mcp/catalog/airtable/install",
            {},
            400,
            "mcp.missing_credential",
        ),
    ],
)
def test_space_mcp_4xx_carries_the_code_envelope(
    mcp_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
    method: str,
    url: str,
    payload: dict[str, Any] | None,
    expected_status: int,
    expected_code: str,
) -> None:
    _patch_mcp_scenario(monkeypatch, scenario)
    response = mcp_client.request(method, url, json=payload)

    assert response.status_code == expected_status, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, dict), f"regressed to plaintext detail: {detail!r}"
    assert detail["code"] == expected_code


# ── space_cli_apps ────────────────────────────────────────────────────────


@pytest.fixture
def cli_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(space_cli_apps, "current_owner_id", lambda: "u_ada")
    monkeypatch.setattr(space_cli_apps, "allowed_cli_apps", lambda: set())
    monkeypatch.setattr(space_cli_apps, "exec_override", lambda: None)
    app = FastAPI()
    app.include_router(space_cli_apps.router, prefix="/api/space/cli-apps")
    return TestClient(app)


@pytest.mark.parametrize(
    ("method", "url", "payload", "expected_status", "expected_code"),
    [
        (
            "PUT",
            f"/api/space/cli-apps/apps/{CLI_APP}/enabled",
            {"enabled": True},
            403,
            "cli.not_granted",
        ),
        (
            "POST",
            f"/api/space/cli-apps/catalog/{CLI_APP}/install",
            None,
            400,
            "cli.install_failed",
        ),
        (
            "POST",
            "/api/space/cli-apps/catalog/jimeng/install",
            None,
            400,
            "cli.not_installable",
        ),
    ],
)
def test_space_cli_apps_4xx_carries_the_code_envelope(
    cli_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    method: str,
    url: str,
    payload: dict[str, Any] | None,
    expected_status: int,
    expected_code: str,
) -> None:
    from deeptutor.services.cli_apps.installer import InstallOutcome
    from deeptutor.services.cli_apps.models import AppRuntime, InstallKind
    from deeptutor.services.cli_apps.paths import abi_stamp
    from deeptutor.services.cli_apps.state import InstalledApp, record_install

    record_install(
        InstalledApp(
            id=CLI_APP,
            entry_point=f"cli-anything-{CLI_APP}",
            runtime=AppRuntime.PYTHON,
            kind=InstallKind.PINNED_HARNESS,
            target="git+https://example.invalid/x.git@abc",
            pin="abc",
            abi=abi_stamp(),
            installed_at="2026-10-13T00:00:00+00:00",
        )
    )
    if expected_code == "cli.install_failed":

        async def _fail_install(entry: Any) -> InstallOutcome:
            return InstallOutcome(
                ok=False,
                app_id=entry.id,
                code="cli.install_failed",
                message="`pip` exited 1",
                log="$ pip install ...\nERROR: No matching distribution",
            )

        monkeypatch.setattr("deeptutor.services.cli_apps.installer.install_app", _fail_install)

    response = cli_client.request(method, url, json=payload)

    assert response.status_code == expected_status, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, dict), f"regressed to plaintext detail: {detail!r}"
    assert detail["code"] == expected_code


# ── notebook ──────────────────────────────────────────────────────────────


@pytest.fixture
def notebook_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    manager = NotebookManager(base_dir=str(tmp_path / "notebooks"))
    monkeypatch.setattr(notebook_router_module, "notebook_manager", manager)
    app = FastAPI()
    app.include_router(notebook_router_module.router, prefix="/api")
    return TestClient(app)


@pytest.mark.parametrize(
    ("method", "url", "payload", "expected_status", "expected_code"),
    [
        ("GET", "/api/notebooks/broken01", None, 409, "notebook_unreadable"),
        ("PUT", "/api/notebooks/broken01", {"name": "Renamed"}, 409, "notebook_unreadable"),
    ],
)
def test_notebook_4xx_carries_the_code_envelope(
    notebook_client: TestClient,
    method: str,
    url: str,
    payload: dict[str, Any] | None,
    expected_status: int,
    expected_code: str,
) -> None:
    manager = notebook_router_module.notebook_manager
    (manager.base_dir / "broken01.json").write_text("{ not json", encoding="utf-8")

    response = notebook_client.request(method, url, json=payload)

    assert response.status_code == expected_status, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, dict), f"regressed to plaintext detail: {detail!r}"
    assert detail["code"] == expected_code


# ── settings (Codex OAuth lifecycle) ──────────────────────────────────────


@pytest.fixture
def settings_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(
        settings_router, "get_current_user", lambda: SimpleNamespace(id="u_ada", is_admin=False)
    )
    app = FastAPI()
    app.include_router(settings_router.router, prefix="/api/settings")
    return TestClient(app)


class _FailingCodexService:
    """Raises the mapped :class:`CodexAuthError` from one lifecycle call."""

    def __init__(self, code: str, message: str, http_status: int, call: str) -> None:
        self._error = CodexAuthError(code, message, http_status)
        self._call = call

    async def _raise(self, *args: object, **kwargs: object) -> dict[str, Any]:
        raise self._error

    def __getattr__(self, name: str) -> Any:
        if name != self._call:
            raise AssertionError(f"unexpected service call {name!r}")
        return self._raise


@pytest.mark.parametrize(
    ("call", "method", "url", "payload", "expected_status", "expected_code"),
    [
        (
            "start_login",
            "POST",
            "/api/settings/providers/openai-codex/oauth/start",
            None,
            401,
            "codex.token_expired",
        ),
        (
            "complete_login_with_callback_url",
            "POST",
            "/api/settings/providers/openai-codex/oauth/complete",
            {"callback_url": "http://127.0.0.1:9/callback?code=x"},
            400,
            "codex.callback_invalid",
        ),
    ],
)
def test_settings_codex_4xx_carries_the_code_envelope(
    settings_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    call: str,
    method: str,
    url: str,
    payload: dict[str, Any] | None,
    expected_status: int,
    expected_code: str,
) -> None:
    monkeypatch.setattr(
        settings_router,
        "get_codex_oauth_service",
        lambda: _FailingCodexService(
            expected_code, "Codex sign-in could not be completed.", expected_status, call
        ),
        raising=False,
    )

    response = settings_client.request(method, url, json=payload)

    assert response.status_code == expected_status, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, dict), f"regressed to plaintext detail: {detail!r}"
    assert detail["code"] == expected_code


# ── video_learning ────────────────────────────────────────────────────────


class _Paths:
    def __init__(self, root: Path) -> None:
        self.root = root

    def get_workspace_feature_dir(self, feature: str) -> Path:
        assert feature == "timed_media"
        return self.root / feature


@pytest.fixture
def video_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    manager = NotebookManager(base_dir=str(tmp_path / "notebooks"))
    monkeypatch.setattr(video_service, "get_current_path_service", lambda: _Paths(tmp_path))
    monkeypatch.setattr(
        video_service, "video_learning_settings_path", lambda: tmp_path / "video_learning.json"
    )
    monkeypatch.setattr(video_notes, "get_notebook_manager", lambda: manager)
    app = FastAPI()
    app.include_router(video_learning.router, prefix="/api/video-learning")
    return TestClient(app)


def _seed_video_material() -> str:
    material_id = video_service.material_id_for(VIDEO_SOURCE_ID)
    video_service.get_timed_media_store().save(
        {
            "version": 1,
            "type": "timed_media",
            "material_id": material_id,
            "source": {
                "provider": "youtube",
                "video_id": VIDEO_SOURCE_ID,
                "url": f"https://youtu.be/{VIDEO_SOURCE_ID}",
            },
            "metadata": {"duration_seconds": 100},
            "transcript": {"status": "ready", "cues": []},
        }
    )
    return material_id


@pytest.mark.parametrize(
    ("with_index_row", "method", "payload", "expected_status", "expected_code"),
    [
        (False, "GET", None, 409, "notebook_unreadable"),
        (True, "POST", {"body": "Note", "time_seconds": 2}, 409, "notebook_unreadable"),
    ],
)
def test_video_learning_4xx_carries_the_code_envelope(
    video_client: TestClient,
    tmp_path: Path,
    with_index_row: bool,
    method: str,
    payload: dict[str, Any] | None,
    expected_status: int,
    expected_code: str,
) -> None:
    material_id = _seed_video_material()
    manager = video_notes.get_notebook_manager()
    notes_dir: Path = manager.base_dir
    (notes_dir / "broken01.json").write_text("{ not json", encoding="utf-8")
    if with_index_row:
        # The create path resolves the notes notebook by name through the index,
        # so the damaged file must be indexed for that lookup to hit it.
        atomic_index = {"notebooks": [{"id": "broken01", "name": video_notes.NOTEBOOK_NAME}]}
        (notes_dir / "notebooks_index.json").write_text(json.dumps(atomic_index), encoding="utf-8")

    response = video_client.request(
        method, f"/api/video-learning/materials/{material_id}/notes", json=payload
    )

    assert response.status_code == expected_status, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, dict), f"regressed to plaintext detail: {detail!r}"
    assert detail["code"] == expected_code
