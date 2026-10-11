"""Focused contract tests for plugins router admin lifecycle and dispatch edges.

Complements ``test_plugins_router.py`` (introspection/frontend/worker axes) by
pinning the admin lifecycle endpoints, request validation envelopes, and the
dispatch edge branches — all against stubbed service-layer collaborators so no
real plugin distribution is installed.
"""

from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any

import pytest

try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover
    FastAPI = None
    TestClient = None

from deeptutor.plugins.distribution import PluginDistributionError
from deeptutor.plugins.lifecycle import PluginLifecycleError, PluginLifecycleManager
from deeptutor.plugins.manifest import parse_manifest
from deeptutor.plugins.registry import PluginInstallation, PluginRegistry, PluginStateError
from deeptutor.plugins.runtime import PluginHttpResponse, PluginRuntimeError

pytestmark = pytest.mark.skipif(
    FastAPI is None or TestClient is None, reason="fastapi not installed"
)

PLUGIN_ID = "org.deeptutor.learning_echo"
_MAX_JSON_BODY_BYTES = 1024 * 1024


def _raw_manifest() -> dict[str, Any]:
    return {
        "schema_version": "deeptutor.plugin/v1",
        "id": PLUGIN_ID,
        "name": "Learning Echo Example",
        "version": "1.0.0",
        "description_i18n": {"en": "Example"},
        "author": "DeepTutor",
        "license": "Apache-2.0",
        "homepage": "https://example.com",
        "source_url": "https://example.com/source",
        "compatibility": {"deeptutor": ">=1.6,<3", "api": {"http_route": "1"}},
        "permissions": {"network": []},
        "dependencies": [],
        "extensions": [
            {
                "type": "http_route",
                "id": "learning_echo_http",
                "entry_point": "learning_echo.worker",
                "path": "/echo",
                "methods": ["POST"],
                "auth": "public",
            }
        ],
    }


def _installation(tmp_path: Path) -> PluginInstallation:
    venv_path = tmp_path / "venv"
    venv_path.mkdir(exist_ok=True)
    return PluginInstallation(
        version="1.0.0",
        artifact_path=tmp_path / "learning_echo.whl",
        artifact_sha256="0" * 64,
        venv_path=venv_path,
        python_path=Path(sys.executable),
        installed_at="2026-10-11T00:00:00+00:00",
    )


def _registry(tmp_path: Path) -> PluginRegistry:
    manifest = parse_manifest(_raw_manifest())
    registry = PluginRegistry(
        state_path=tmp_path / "plugins.json",
        installed_distributions=[],
        deeptutor_version="1.6.0",
    )
    state = registry.state_snapshot()
    state["plugins"][PLUGIN_ID] = {
        "manifest": manifest.to_dict(),
        "installation": _installation(tmp_path).to_dict(),
        "history": [],
    }
    registry.replace_state(state)
    return registry


def _use_registry(monkeypatch: pytest.MonkeyPatch, registry: PluginRegistry) -> None:
    from deeptutor.api.routers import plugins

    monkeypatch.setattr(plugins, "_registry_factory", lambda: registry)


def _approved_registry(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> PluginRegistry:
    registry = _registry(tmp_path)
    registry.approve(PLUGIN_ID)
    _use_registry(monkeypatch, registry)
    return registry


def _install_worker_stub(monkeypatch: pytest.MonkeyPatch, *, response: Any) -> list[dict[str, Any]]:
    from deeptutor.api.routers import plugins

    calls: list[dict[str, Any]] = []

    class _StubWorkerRoute:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        def handle(self, **kwargs: Any) -> PluginHttpResponse:
            calls.append(kwargs)
            if isinstance(response, Exception):
                raise response
            return response

    monkeypatch.setattr(plugins, "PluginWorkerHttpRoute", _StubWorkerRoute)
    return calls


class _FakeCatalogEntry:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def to_dict(self) -> dict[str, Any]:
        return self._payload


@pytest.fixture
def client() -> TestClient:
    from deeptutor.api.routers import plugins

    app = FastAPI()
    app.include_router(plugins.router, prefix="/api/plugins")
    return TestClient(app)


def test_introspection_endpoints_require_authentication(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.api.routers import plugins

    _use_registry(monkeypatch, _registry(tmp_path))

    async def reject(
        *, authorization: str | None = None, dt_token: str | None = None, request=None
    ) -> None:
        raise HTTPException(status_code=401, detail="Authentication required")

    monkeypatch.setattr(plugins, "require_auth", reject)
    for path in (
        "/api/plugins/extensions",
        "/api/plugins/catalog",
        "/api/plugins/state",
        f"/api/plugins/{PLUGIN_ID}/info",
    ):
        assert client.get(path).status_code == 401, path


def test_admin_lifecycle_endpoints_require_admin(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.api.routers import plugins

    _use_registry(monkeypatch, _registry(tmp_path))

    async def reject(request: Request) -> None:
        raise HTTPException(status_code=403, detail="Admin access required")

    client.app.dependency_overrides[plugins._require_admin] = reject
    try:
        cases = [
            ("post", f"/api/plugins/{PLUGIN_ID}/approve", {"json": {"snapshot_digest": "0" * 64}}),
            ("post", f"/api/plugins/{PLUGIN_ID}/enable", {}),
            ("post", f"/api/plugins/{PLUGIN_ID}/disable", {}),
            ("post", f"/api/plugins/{PLUGIN_ID}/install", {"json": {}}),
            ("post", f"/api/plugins/{PLUGIN_ID}/rollback", {}),
            ("delete", f"/api/plugins/{PLUGIN_ID}/installation", {}),
        ]
        for method, path, kwargs in cases:
            response = getattr(client, method)(path, **kwargs)
            assert response.status_code == 403, path
            assert response.json() == {"detail": "Admin access required"}
    finally:
        client.app.dependency_overrides.clear()


def test_catalog_endpoint_returns_reviewed_entries(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.api.routers import plugins

    _use_registry(monkeypatch, _registry(tmp_path))
    monkeypatch.setattr(
        plugins,
        "load_catalog",
        lambda: [_FakeCatalogEntry({"id": "org.a", "version": "1.0.0"})],
    )

    response = client.get("/api/plugins/catalog")

    assert response.status_code == 200
    assert response.json() == {"entries": [{"id": "org.a", "version": "1.0.0"}]}


def test_state_endpoint_lists_installed_records_with_status(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _registry(tmp_path)
    _use_registry(monkeypatch, registry)

    response = client.get("/api/plugins/state")

    assert response.status_code == 200
    body = response.json()
    records = {plugin["id"]: plugin for plugin in body["plugins"]}
    assert PLUGIN_ID in records
    assert "status" in records[PLUGIN_ID]


def test_info_endpoint_returns_record_or_not_found(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_registry(monkeypatch, _registry(tmp_path))

    unknown = client.get("/api/plugins/does.not.exist/info")
    assert unknown.status_code == 404
    assert unknown.json() == {"detail": "Plugin not found"}

    known = client.get(f"/api/plugins/{PLUGIN_ID}/info")
    assert known.status_code == 200
    assert known.json()["id"] == PLUGIN_ID


def test_approve_rejects_malformed_snapshot_digest(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_registry(monkeypatch, _registry(tmp_path))

    for digest in ("", "z" * 64, "0" * 63, "0" * 65):
        response = client.post(
            f"/api/plugins/{PLUGIN_ID}/approve", json={"snapshot_digest": digest}
        )
        assert response.status_code == 422, digest
        detail = response.json()["detail"]
        assert isinstance(detail, list) and detail

    missing = client.post(f"/api/plugins/{PLUGIN_ID}/approve", json={})
    assert missing.status_code == 422


def test_install_endpoint_contract_and_error_envelopes(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.api.routers import plugins

    registry = _registry(tmp_path)
    _use_registry(monkeypatch, registry)
    captured: dict[str, Any] = {}

    class _StubInstallManager:
        def __init__(self, *, lifecycle_factory=None) -> None:
            captured["lifecycle_factory"] = lifecycle_factory

        def install(self, plugin_id: str, *, version: str, allow_deprecated: bool):
            captured["install_args"] = (plugin_id, version, allow_deprecated)
            error = captured.get("error")
            if error is not None:
                raise error
            return SimpleNamespace(
                lifecycle=SimpleNamespace(plugin_id=plugin_id, version=version, action="install")
            )

    produced: list[PluginRegistry] = []

    class _StubLifecycleManager:
        def __init__(self, *, registry=None) -> None:
            produced.append(registry)

    monkeypatch.setattr(plugins, "CatalogInstallManager", _StubInstallManager)
    monkeypatch.setattr(plugins, "PluginLifecycleManager", _StubLifecycleManager)

    response = client.post(
        f"/api/plugins/{PLUGIN_ID}/install",
        json={"version": "1.2.3", "allow_deprecated": True},
    )
    assert response.status_code == 200
    assert response.json() == {
        "id": PLUGIN_ID,
        "version": "1.2.3",
        "action": "install",
        "approval_required": True,
    }
    assert captured["install_args"] == (PLUGIN_ID, "1.2.3", True)
    assert isinstance(captured["lifecycle_factory"](), _StubLifecycleManager)
    assert produced == [registry]

    boundary = client.post(f"/api/plugins/{PLUGIN_ID}/install", json={"version": "9" * 64})
    assert boundary.status_code == 200
    assert boundary.json()["version"] == "9" * 64

    for error in (
        PluginStateError("bad state"),
        PluginLifecycleError("bad lifecycle"),
        PluginDistributionError("bad artifact"),
    ):
        captured["error"] = error
        failed = client.post(f"/api/plugins/{PLUGIN_ID}/install", json={})
        assert failed.status_code == 409
        assert failed.json() == {"detail": str(error)}


def test_rollback_and_uninstall_endpoints_contract(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.api.routers import plugins

    registry = _registry(tmp_path)
    _use_registry(monkeypatch, registry)
    captured: dict[str, Any] = {}

    class _StubLifecycleManager:
        def __init__(self, *, registry=None, root=None, runner=None) -> None:
            captured["registry"] = registry

        def rollback(self, plugin_id: str):
            captured["rollback"] = plugin_id
            error = captured.get("rollback_error")
            if error is not None:
                raise error
            return SimpleNamespace(plugin_id=plugin_id, version="0.9.0")

        def uninstall(self, plugin_id: str):
            captured["uninstall"] = plugin_id
            error = captured.get("uninstall_error")
            if error is not None:
                raise error
            return SimpleNamespace(plugin_id=plugin_id, action="uninstalled")

    monkeypatch.setattr(plugins, "PluginLifecycleManager", _StubLifecycleManager)

    rollback = client.post(f"/api/plugins/{PLUGIN_ID}/rollback")
    assert rollback.status_code == 200
    assert rollback.json() == {
        "id": PLUGIN_ID,
        "version": "0.9.0",
        "approval_required": True,
    }
    assert captured["rollback"] == PLUGIN_ID
    assert captured["registry"] is registry

    uninstalled = client.delete(f"/api/plugins/{PLUGIN_ID}/installation")
    assert uninstalled.status_code == 200
    assert uninstalled.json() == {"id": PLUGIN_ID, "action": "uninstalled"}
    assert captured["uninstall"] == PLUGIN_ID

    captured["rollback_error"] = PluginLifecycleError("cannot roll back")
    failed_rollback = client.post(f"/api/plugins/{PLUGIN_ID}/rollback")
    assert failed_rollback.status_code == 409
    assert failed_rollback.json() == {"detail": "cannot roll back"}

    captured["uninstall_error"] = PluginStateError("cannot uninstall")
    failed_uninstall = client.delete(f"/api/plugins/{PLUGIN_ID}/installation")
    assert failed_uninstall.status_code == 409
    assert failed_uninstall.json() == {"detail": "cannot uninstall"}


def test_normalize_plugin_path_contract() -> None:
    from deeptutor.api.routers import plugins

    assert plugins._normalize_plugin_path("echo") == "/echo"
    assert plugins._normalize_plugin_path("/echo/") == "/echo"
    for bad in ("", "%2e%2e", "a\\b", "a\x00b"):
        assert plugins._normalize_plugin_path(bad) is None


def test_dispatch_route_with_rejected_path_segment_is_not_found(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _approved_registry(client, tmp_path, monkeypatch)
    calls = _install_worker_stub(
        monkeypatch, response=PluginHttpResponse(status=200, body={"ok": True})
    )

    response = client.get(f"/api/plugins/{PLUGIN_ID}/a%25b")

    assert response.status_code == 404
    assert response.json() == {"detail": "Plugin route not found"}
    assert calls == []


def test_dispatch_rejects_body_above_hard_cap(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _approved_registry(client, tmp_path, monkeypatch)
    calls = _install_worker_stub(
        monkeypatch, response=PluginHttpResponse(status=200, body={"ok": True})
    )
    too_big = b'{"x":"' + b"a" * (_MAX_JSON_BODY_BYTES - 7) + b'"}'
    assert len(too_big) == _MAX_JSON_BODY_BYTES + 1

    rejected = client.post(
        f"/api/plugins/{PLUGIN_ID}/echo",
        content=too_big,
        headers={"Content-Type": "application/json"},
    )
    assert rejected.status_code == 413
    assert rejected.json() == {"detail": "Plugin request body is too large"}
    assert calls == []

    exact = b'{"x":"' + b"a" * (_MAX_JSON_BODY_BYTES - 8) + b'"}'
    assert len(exact) == _MAX_JSON_BODY_BYTES
    allowed = client.post(
        f"/api/plugins/{PLUGIN_ID}/echo",
        content=exact,
        headers={"Content-Type": "application/json"},
    )
    assert allowed.status_code == 200
    assert len(calls) == 1


def test_dispatch_forwards_repeated_query_values_and_method(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _approved_registry(client, tmp_path, monkeypatch)
    calls = _install_worker_stub(
        monkeypatch, response=PluginHttpResponse(status=200, body={"ok": True})
    )

    response = client.post(
        f"/api/plugins/{PLUGIN_ID}/echo?tag=math&tag=deep", json={"message": "hi"}
    )

    assert response.status_code == 200
    assert calls[-1]["method"] == "POST"
    assert calls[-1]["path"] == "/echo"
    assert calls[-1]["query"] == {"tag": ("math", "deep")}
    assert calls[-1]["body"] == {"message": "hi"}


def test_dispatch_method_mismatch_reports_allow_header(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _approved_registry(client, tmp_path, monkeypatch)
    calls = _install_worker_stub(
        monkeypatch, response=PluginHttpResponse(status=200, body={"ok": True})
    )

    response = client.get(f"/api/plugins/{PLUGIN_ID}/echo")

    assert response.status_code == 405
    assert response.json() == {"detail": "Method not allowed"}
    assert response.headers["allow"] == "POST"
    assert calls == []


def test_dispatch_maps_204_to_empty_response_with_headers(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _approved_registry(client, tmp_path, monkeypatch)
    _install_worker_stub(
        monkeypatch,
        response=PluginHttpResponse(status=204, body=None, headers={"X-Trace": "t1"}),
    )

    response = client.post(f"/api/plugins/{PLUGIN_ID}/echo", json={})

    assert response.status_code == 204
    assert response.headers["x-trace"] == "t1"
    assert response.content == b""


def test_dispatch_maps_worker_contract_failure_to_500(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _approved_registry(client, tmp_path, monkeypatch)
    _install_worker_stub(monkeypatch, response=PluginRuntimeError("worker violated contract"))

    response = client.post(f"/api/plugins/{PLUGIN_ID}/echo", json={})

    assert response.status_code == 500
    assert response.json() == {"detail": "Plugin route failed"}
