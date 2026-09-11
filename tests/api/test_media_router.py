from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import auth as auth_router
from deeptutor.api.routers import media
from deeptutor.media import access, store


class _Paths:
    def __init__(self, root: Path) -> None:
        self.root = root

    def get_user_root(self) -> Path:
        return self.root / "user"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", False)
    monkeypatch.setattr(store, "get_current_path_service", lambda: _Paths(tmp_path))
    monkeypatch.setattr(store.user_paths, "SYSTEM_ROOT", tmp_path / "system")
    monkeypatch.setattr(access.user_paths, "SYSTEM_ROOT", tmp_path / "system")
    app = FastAPI()
    app.include_router(media.public_router, prefix="/api/media")
    app.include_router(media.router, prefix="/api/media")
    return TestClient(app)


def test_playlist_import_preview_and_replay(client: TestClient) -> None:
    playlist = client.post("/api/media/playlists", json={"name": "周末精听", "kind": "manual"})
    assert playlist.status_code == 201
    playlist_id = playlist.json()["playlist_id"]

    preview = client.post(
        "/api/media/imports/preview",
        json={"sources": ["Artist - First", "this is unrecognized"], "target_playlist_id": playlist_id},
    )
    assert preview.status_code == 200
    candidate = preview.json()["candidates"][0]
    assert candidate["status"] == "needs_confirmation"

    body = {"preview_token": preview.json()["preview_token"], "selected_candidate_ids": [candidate["candidate_id"]]}
    headers = {"Idempotency-Key": "router-import-key"}
    first = client.post("/api/media/imports", json=body, headers=headers)
    replay = client.post("/api/media/imports", json=body, headers=headers)
    assert first.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["imported_item_count"] == 1

    detail = client.get(f"/api/media/playlists/{playlist_id}")
    assert len(detail.json()["items"]) == 1


def test_pairing_creates_separate_mobile_credential(client: TestClient) -> None:
    pairing = client.post("/api/media/pairing/sessions", json={"device_name": "Test iPhone"})
    assert pairing.status_code == 201
    confirmation = client.post(
        f"/api/media/pairing/sessions/{pairing.json()['pairing_id']}/confirm",
        json={"pairing_code": pairing.json()["pairing_code"]},
    )
    assert confirmation.status_code == 200
    exchange = client.post(
        f"/api/media/pairing/sessions/{pairing.json()['pairing_id']}/exchange",
        json={"pairing_code": pairing.json()["pairing_code"]},
    )
    assert exchange.status_code == 200
    assert exchange.json()["mobile_token"].startswith("lw_mobile_")
    mobile = client.get("/api/media/bootstrap", headers={"Authorization": f"Bearer {exchange.json()['mobile_token']}"})
    assert mobile.status_code == 200
