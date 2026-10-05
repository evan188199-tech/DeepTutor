"""Contract tests for the visualizers router beyond the happy-path flow.

Covers catalog shape, import validation (non-zip, oversize), the store-error
to HTTP-status mapping for unknown/conflicting visualizers, and the auth gate
applied by ``main.py``.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
import zipfile

import pytest

pytest.importorskip("fastapi")
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from deeptutor.api.routers import auth as auth_router
from deeptutor.api.routers import visualizers as visualizers_router
from deeptutor.services.auth import TokenPayload
from deeptutor.visualizers.registry import VisualizerRegistry
from deeptutor.visualizers.store import VisualizerStore


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    registry = VisualizerRegistry(
        store=VisualizerStore(
            root=tmp_path / "visualizers",
            state_file=tmp_path / "visualizers.json",
        )
    )
    monkeypatch.setattr(visualizers_router, "get_visualizer_registry", lambda: registry)
    return TestClient(_make_app())


def _make_app(*, auth_guard: bool = False) -> FastAPI:
    app = FastAPI()
    dependencies = [Depends(auth_router.require_learning_surface)] if auth_guard else None
    app.include_router(
        visualizers_router.router, prefix="/api/visualizers", dependencies=dependencies
    )
    return app


def _archive(visualizer_id: str = "fraction_tiles") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "visualizer.json",
            json.dumps(
                {
                    "id": visualizer_id,
                    "display_name": "Fraction Tiles",
                    "description": "Interactive fraction tiles.",
                    "render_target": "iframe",
                    "renderer_entry": "index.html",
                    "payload_format": "application/json",
                    "payload_kind": "json",
                    "prompt": "Return strict JSON with fraction rows.",
                }
            ),
        )
        archive.writestr("index.html", "<!doctype html><title>Fraction Tiles</title>")
    return buffer.getvalue()


def test_catalog_lists_schema_version_and_install_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    res = client.get("/api/visualizers/list")
    assert res.status_code == 200
    body = res.json()
    assert body["schema_version"] == "deeptutor.visualizer-catalog/v1"
    geogebra = next(item for item in body["visualizers"] if item["id"] == "geogebra")
    assert geogebra["installed"] is False


def test_import_rejects_non_zip_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    res = client.post(
        "/api/visualizers/import",
        files={"file": ("bundle.tar", b"not a zip", "application/octet-stream")},
    )
    assert res.status_code == 400
    assert "zip" in res.json()["detail"].lower()


def test_import_rejects_oversize_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(visualizers_router, "_MAX_UPLOAD_BYTES", 16)
    client = _client(tmp_path, monkeypatch)
    res = client.post(
        "/api/visualizers/import",
        files={"file": ("big.zip", b"x" * 64, "application/zip")},
    )
    assert res.status_code == 413


def test_unknown_visualizer_error_mapping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    assert client.post("/api/visualizers/ghost/enable").status_code == 400
    assert client.post("/api/visualizers/ghost/disable").status_code == 400
    assert client.delete("/api/visualizers/ghost").status_code == 404
    assert client.post("/api/visualizers/bundled/ghost/install").status_code == 404
    assert client.get("/api/visualizers/ghost/assets/index.html").status_code == 404


def test_duplicate_import_conflicts_with_409(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    files = {"file": ("fraction-tiles.zip", _archive(), "application/zip")}
    assert client.post("/api/visualizers/import", files=files).status_code == 200
    conflict = client.post("/api/visualizers/import", files=files)
    assert conflict.status_code == 409
    assert "fraction_tiles" in conflict.json()["detail"]


def test_auth_gate_blocks_anonymous_and_accepts_valid_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    tokens: dict[str, TokenPayload | None] = {
        "tok-ok": TokenPayload(username="alice", role="admin", user_id="u-1")
    }
    monkeypatch.setattr(auth_router, "decode_token", lambda token: tokens.get(token))
    client = TestClient(_make_app(auth_guard=True))

    assert client.get("/api/visualizers/list").status_code == 401
    assert (
        client.get("/api/visualizers/list", headers={"Authorization": "Bearer tok-bad"}).status_code
        == 401
    )
    assert (
        client.get("/api/visualizers/list", headers={"Authorization": "Bearer tok-ok"}).status_code
        == 200
    )
