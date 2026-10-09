"""Failure and 4xx branch coverage for the visualizer lifecycle routes.

Complements ``tests/api/test_visualizers_router.py`` (happy paths) by pinning
the store-error to HTTP-status mapping and the catalog/lifecycle contract of
the per-user visualizer endpoints: ``list_visualizers``, ``install_bundled``,
``enable_visualizer`` and ``disable_visualizer``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from deeptutor.api.routers import visualizers as visualizers_router
from deeptutor.visualizers.registry import VisualizerRegistry
from deeptutor.visualizers.store import VisualizerStore, VisualizerStoreError


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    registry = VisualizerRegistry(
        store=VisualizerStore(
            root=tmp_path / "visualizers",
            state_file=tmp_path / "visualizers.json",
        )
    )
    monkeypatch.setattr(
        visualizers_router,
        "get_visualizer_registry",
        lambda: registry,
    )
    app = FastAPI()
    app.include_router(visualizers_router.router, prefix="/api/visualizers")
    return TestClient(app)


def _catalog_entry(client: TestClient, visualizer_id: str) -> dict:
    visualizers = client.get("/api/visualizers/list").json()["visualizers"]
    return next(item for item in visualizers if item["id"] == visualizer_id)


def test_error_mapping_assigns_404_409_and_400() -> None:
    mapping = {
        "bundled visualizer not found: nope": 404,
        "visualizer not found: nope": 404,
        "visualizer asset not found": 404,
        "visualizer already installed: dup": 409,
        "visualizer id is reserved by the host: svg": 409,
        "visualizer is not installed: svg": 400,
        "core visualizers cannot be uninstalled; disable them": 400,
        "invalid visualizer id": 400,
    }
    for detail, expected in mapping.items():
        error = visualizers_router._http_error(VisualizerStoreError(detail))
        assert isinstance(error, HTTPException)
        assert error.status_code == expected, detail
        assert error.detail == detail


def test_list_catalog_contract_schema_and_flags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(tmp_path, monkeypatch)
    response = client.get("/api/visualizers/list")
    assert response.status_code == 200

    body = response.json()
    assert body["schema_version"] == "deeptutor.visualizer-catalog/v1"
    entries = body["visualizers"]
    assert entries, "bundled visualizers must always be listed"

    ids = [item["id"] for item in entries]
    assert len(ids) == len(set(ids))
    for item in entries:
        assert {"id", "origin", "installed", "enabled", "uninstallable"} <= set(item)
        assert "prompt" not in item
        if not item["installed"]:
            assert item["enabled"] is False
        if item["origin"] == "core":
            assert item["uninstallable"] is False

    bundled = _catalog_entry(client, "geogebra")
    assert bundled["origin"] == "bundled"
    assert bundled["installed"] is False
    assert bundled["enabled"] is False


def test_install_bundled_unknown_id_returns_404(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(tmp_path, monkeypatch)
    response = client.post("/api/visualizers/bundled/does_not_exist/install")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]
    assert "does_not_exist" in response.json()["detail"]

    assert _catalog_entry(client, "geogebra")["installed"] is False


def test_install_bundled_rejects_core_visualizer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(tmp_path, monkeypatch)
    core_ids = [
        item["id"]
        for item in client.get("/api/visualizers/list").json()["visualizers"]
        if item["origin"] == "core"
    ]
    assert core_ids, "core visualizers must always be listed"

    response = client.post(f"/api/visualizers/bundled/{core_ids[0]}/install")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]
    assert core_ids[0] in response.json()["detail"]


def test_install_bundled_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(tmp_path, monkeypatch)
    for _ in range(2):
        response = client.post("/api/visualizers/bundled/geogebra/install")
        assert response.status_code == 200
        assert response.json() == {
            "status": "installed",
            "visualizer": "geogebra",
        }

    bundled = _catalog_entry(client, "geogebra")
    assert bundled["installed"] is True
    assert bundled["enabled"] is True


def test_enable_unknown_visualizer_returns_400(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(tmp_path, monkeypatch)
    response = client.post("/api/visualizers/does_not_exist/enable")
    assert response.status_code == 400
    assert "not installed" in response.json()["detail"]
    assert "does_not_exist" in response.json()["detail"]


def test_disable_before_install_returns_400(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(tmp_path, monkeypatch)
    assert _catalog_entry(client, "geogebra")["installed"] is False

    response = client.post("/api/visualizers/geogebra/disable")
    assert response.status_code == 400
    assert "not installed" in response.json()["detail"]


def test_disable_enable_lifecycle_updates_catalog_flags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(tmp_path, monkeypatch)
    assert client.post("/api/visualizers/bundled/geogebra/install").status_code == 200
    assert _catalog_entry(client, "geogebra")["enabled"] is True

    disabled = client.post("/api/visualizers/geogebra/disable")
    assert disabled.status_code == 200
    assert disabled.json() == {"status": "disabled", "visualizer": "geogebra"}
    entry = _catalog_entry(client, "geogebra")
    assert entry["installed"] is True
    assert entry["enabled"] is False

    again = client.post("/api/visualizers/geogebra/disable")
    assert again.status_code == 200

    enabled = client.post("/api/visualizers/geogebra/enable")
    assert enabled.status_code == 200
    assert enabled.json() == {"status": "enabled", "visualizer": "geogebra"}
    entry = _catalog_entry(client, "geogebra")
    assert entry["installed"] is True
    assert entry["enabled"] is True
