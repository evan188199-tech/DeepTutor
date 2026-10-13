"""HTTP contract tests for the plugin catalog, state and admin lifecycle routes.

Covers ``GET /api/plugins/catalog``, ``GET /api/plugins/state``,
``POST /api/plugins/{plugin_id}/install`` and
``DELETE /api/plugins/{plugin_id}/installation``: the authenticated
introspection payloads, the admin gate protecting the lifecycle writes, the
install request passthrough (defaults and explicit fields), the 409 mapping
for distribution/state failures, and the 422 body-validation bound.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from deeptutor.api.routers import plugins as plugins_router
from deeptutor.plugins.distribution import PluginDistributionError
from deeptutor.plugins.registry import PluginStateError


class _FakeInstallManager:
    instances: list["_FakeInstallManager"] = []

    def __init__(self, *, lifecycle_factory) -> None:
        self.lifecycle_factory = lifecycle_factory
        _FakeInstallManager.instances.append(self)

    def install(self, plugin_id: str, *, version: str, allow_deprecated: bool):
        self.calls = (plugin_id, version, allow_deprecated)
        if plugin_id == "org.bad":
            raise PluginDistributionError("artifact rejected")
        return SimpleNamespace(
            lifecycle=SimpleNamespace(plugin_id=plugin_id, version=version, action="install")
        )


class _FakeLifecycleManager:
    def __init__(self, *, registry) -> None:
        self.registry = registry

    def uninstall(self, plugin_id: str):
        if plugin_id == "org.stuck":
            raise PluginStateError("cannot uninstall an enabled plugin")
        return SimpleNamespace(plugin_id=plugin_id, action="uninstall")


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(plugins_router, "CatalogInstallManager", _FakeInstallManager)
    monkeypatch.setattr(plugins_router, "PluginLifecycleManager", _FakeLifecycleManager)
    _FakeInstallManager.instances = []
    app = FastAPI()
    app.include_router(plugins_router.router, prefix="/api/plugins")
    return TestClient(app)


def _entry(payload: dict[str, Any]) -> Any:
    return SimpleNamespace(to_dict=lambda payload=payload: payload)


def test_catalog_returns_entries_payload(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    entries = [
        {"id": "org.deeptutor.learning_echo", "version": "1.0.0", "deprecated": False},
        {"id": "org.deeptutor.legacy", "version": "0.9.0", "deprecated": True},
    ]
    monkeypatch.setattr(
        plugins_router, "load_catalog", lambda *args, **kwargs: tuple(_entry(e) for e in entries)
    )

    res = client.get("/api/plugins/catalog")

    assert res.status_code == 200
    assert res.json() == {"entries": entries}


def test_catalog_requires_authentication(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def reject(*, authorization=None, dt_token=None, request=None):
        raise HTTPException(status_code=401, detail="Authentication required")

    monkeypatch.setattr(plugins_router, "require_auth", reject)

    assert client.get("/api/plugins/catalog").status_code == 401


def test_state_lists_registry_records(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    records = [
        SimpleNamespace(
            to_dict=lambda: {
                "id": "org.deeptutor.learning_echo",
                "status": "enabled",
                "distribution": "managed",
            }
        )
    ]
    monkeypatch.setattr(
        plugins_router, "_registry_factory", lambda: SimpleNamespace(list_plugins=lambda: records)
    )

    res = client.get("/api/plugins/state")

    assert res.status_code == 200
    assert res.json() == {
        "plugins": [
            {"id": "org.deeptutor.learning_echo", "status": "enabled", "distribution": "managed"}
        ]
    }


def test_state_with_empty_registry_returns_empty_list(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        plugins_router, "_registry_factory", lambda: SimpleNamespace(list_plugins=lambda: [])
    )

    res = client.get("/api/plugins/state")

    assert res.status_code == 200
    assert res.json() == {"plugins": []}


def test_state_requires_authentication(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def reject(*, authorization=None, dt_token=None, request=None):
        raise HTTPException(status_code=401, detail="Authentication required")

    monkeypatch.setattr(plugins_router, "require_auth", reject)

    assert client.get("/api/plugins/state").status_code == 401


def test_install_applies_defaults_and_returns_lifecycle_result(
    client: TestClient,
) -> None:
    res = client.post("/api/plugins/org.deeptutor.learning_echo/install", json={})

    assert res.status_code == 200
    assert res.json() == {
        "id": "org.deeptutor.learning_echo",
        "version": "latest",
        "action": "install",
        "approval_required": True,
    }
    assert len(_FakeInstallManager.instances) == 1
    assert _FakeInstallManager.instances[0].calls == (
        "org.deeptutor.learning_echo",
        "latest",
        False,
    )


def test_install_passes_explicit_version_and_deprecated_flag(
    client: TestClient,
) -> None:
    res = client.post(
        "/api/plugins/org.deeptutor.learning_echo/install",
        json={"version": "2.1.0", "allow_deprecated": True},
    )

    assert res.status_code == 200
    assert res.json()["version"] == "2.1.0"
    assert _FakeInstallManager.instances[0].calls == (
        "org.deeptutor.learning_echo",
        "2.1.0",
        True,
    )


def test_install_rejects_oversized_version_with_422(client: TestClient) -> None:
    res = client.post(
        "/api/plugins/org.deeptutor.learning_echo/install", json={"version": "v" * 65}
    )

    assert res.status_code == 422


def test_install_maps_distribution_failure_to_409(client: TestClient) -> None:
    res = client.post("/api/plugins/org.bad/install", json={})

    assert res.status_code == 409
    assert res.json()["detail"] == "artifact rejected"


def test_install_requires_admin(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def reject(*, payload=None):
        raise HTTPException(status_code=403, detail="Admin privileges required")

    monkeypatch.setattr(plugins_router, "require_admin", reject)

    assert (
        client.post("/api/plugins/org.deeptutor.learning_echo/install", json={}).status_code == 403
    )


def test_uninstall_returns_action_payload(client: TestClient) -> None:
    res = client.delete("/api/plugins/org.deeptutor.learning_echo/installation")

    assert res.status_code == 200
    assert res.json() == {"id": "org.deeptutor.learning_echo", "action": "uninstall"}


def test_uninstall_maps_state_error_to_409(client: TestClient) -> None:
    res = client.delete("/api/plugins/org.stuck/installation")

    assert res.status_code == 409
    assert "enabled" in res.json()["detail"]


def test_uninstall_requires_admin(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def reject(*, payload=None):
        raise HTTPException(status_code=403, detail="Admin privileges required")

    monkeypatch.setattr(plugins_router, "require_admin", reject)

    assert client.delete("/api/plugins/org.deeptutor.learning_echo/installation").status_code == 403
