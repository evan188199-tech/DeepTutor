from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import video_remote_control
from deeptutor.api.routers.auth import require_learning_surface
from deeptutor.services.tunnel_handoff import TunnelState
from deeptutor.video_learning import service
from deeptutor.video_learning.marks import create_mark
from deeptutor.video_learning.remote import RemoteControlStore


class _Paths:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.workspace_root = root.parent

    def get_workspace_feature_dir(self, feature: str) -> Path:
        assert feature == "timed_media"
        return self.root / "workspace" / feature


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    db_path = tmp_path / "data" / "user" / "video_learning" / "remote.db"
    monkeypatch.setattr(video_remote_control, "_db_path", lambda: db_path)
    monkeypatch.setattr(
        service, "get_current_path_service", lambda: _Paths(tmp_path / "data" / "user")
    )
    monkeypatch.setattr(
        video_remote_control.service,
        "load_video_learning_settings",
        lambda: {
            "version": 1,
            "default_provider": "invidious",
            "youtube": {"transcript_provider": "none"},
            "invidious": {
                "api_base_url": "http://127.0.0.1:4302",
                "public_base_url": "https://invidious.example",
            },
        },
    )
    app = FastAPI()
    app.include_router(video_remote_control.router, prefix="/api/video-learning")
    app.dependency_overrides[require_learning_surface] = lambda: None
    return TestClient(app)


def _renderer(client: TestClient, **payload: object) -> dict:
    response = client.post("/api/video-learning/renderers", json=payload)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def _device(client: TestClient, ticket: str) -> tuple[dict, dict[str, str]]:
    redeemed = client.post("/api/video-learning/renderers/bootstrap", json={"ticket": ticket})
    assert redeemed.status_code == 200
    data = redeemed.json()
    return data, {"Authorization": f"VideoLearning {data['device_id']}:{data['token']}"}


def test_renderer_bootstrap_is_single_use_and_rejects_bad_tokens(client: TestClient):
    created = _renderer(client, video_id="dQw4w9WgXcQ")
    assert created["launch_url"].startswith("https://invidious.example/watch?")
    assert "#dt_bootstrap=" in created["launch_url"]
    assert created["material_id"] == service.material_id_for("dQw4w9WgXcQ")

    device, headers = _device(client, created["ticket"])
    assert device["material_id"] == created["material_id"]
    replay = client.post(
        "/api/video-learning/renderers/bootstrap", json={"ticket": created["ticket"]}
    )
    assert replay.status_code == 404
    assert (
        client.post(
            "/api/video-learning/player/presence",
            headers={"Authorization": f"VideoLearning {device['device_id']}:wrong"},
        ).status_code
        == 403
    )
    assert client.post("/api/video-learning/player/presence", headers=headers).status_code == 200


def test_player_sync_binds_material_and_commands_are_acked(client: TestClient):
    created = _renderer(client, video_id="dQw4w9WgXcQ", position_seconds=12)
    device, headers = _device(client, created["ticket"])
    synced = client.post(
        "/api/video-learning/player/sync",
        headers=headers,
        json={
            "renderer_origin": "https://invidious.example",
            "video_id": "dQw4w9WgXcQ",
            "title": "Demo",
            "position_ms": 42_000,
            "duration_ms": 120_000,
            "playback_state": "playing",
        },
    )
    assert synced.status_code == 200
    session = synced.json()["session"]
    assert session["material_id"] == created["material_id"]
    assert session["online"] is True

    command = client.post(
        f"/api/video-learning/sessions/{session['session_id']}/commands",
        json={"type": "seek", "delta_ms": -20_000},
    )
    assert command.status_code == 200
    assert command.json()["payload"] == {"position_ms": 22_000}
    command_id = command.json()["command_id"]

    polled = client.post(
        "/api/video-learning/player/sync",
        headers=headers,
        json={
            "session_id": session["session_id"],
            "renderer_origin": "https://invidious.example",
            "video_id": "dQw4w9WgXcQ",
            "position_ms": 22_000,
        },
    )
    assert [row["command_id"] for row in polled.json()["commands"]] == [command_id]
    acked = client.post(
        f"/api/video-learning/player/commands/{command_id}/ack",
        headers=headers,
        json={"ok": True},
    )
    assert acked.json()["status"] == "acked"


def test_phone_controller_replacement_and_remote_annotation(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        video_remote_control,
        "load_tunnel_state",
        lambda: TunnelState("https://deep.example.test", "deep.example.test"),
    )
    captured: list[str] = []

    def fake_pairing(payload, *, handoff):
        captured.append(handoff.cookies[0].value)
        assert payload.user_id == "local-admin"
        assert handoff.redirect_path.startswith(
            "/chat?capability=immersive_watching&viewer_session="
        )
        return "pairing-id", 300

    monkeypatch.setattr(video_remote_control, "create_pairing", fake_pairing)
    created = _renderer(client, video_id="dQw4w9WgXcQ")
    device, headers = _device(client, created["ticket"])
    synced = client.post(
        "/api/video-learning/player/sync",
        headers=headers,
        json={
            "renderer_origin": "https://invidious.example",
            "video_id": "dQw4w9WgXcQ",
            "title": "Demo",
            "position_ms": 12_000,
            "duration_ms": 120_000,
            "playback_state": "playing",
        },
    ).json()
    session_id = synced["session"]["session_id"]
    material_id = synced["session"]["material_id"]

    handoff = client.post("/api/video-learning/player/phone-handoff", headers=headers)
    assert handoff.status_code == 200
    assert handoff.json()["qr_url"] == "https://deep.example.test/access/device?pairing=pairing-id"
    cookie = captured[0]
    annotation_url = f"/api/video-learning/sessions/{session_id}/annotations"
    cookie_headers = {"Cookie": f"dt_video_controller={cookie}"}
    assert client.get(annotation_url).status_code == 403
    created_annotation = client.post(
        annotation_url,
        json={"kind": "question", "note": "Rewatch this"},
        headers=cookie_headers,
    )
    assert created_annotation.status_code == 201, created_annotation.text
    annotation = created_annotation.json()
    assert annotation["source"] == "remote_phone"
    assert annotation["start_seconds"] == 12
    assert annotation["metadata"]["session_id"] == session_id
    assert service.get_timed_media_store().get(material_id)["learning"]["marks"] == [annotation]

    replaced = client.post("/api/video-learning/player/phone-handoff", headers=headers)
    assert replaced.status_code == 200
    assert (
        client.post(
            f"/api/video-learning/sessions/{session_id}/commands", json={"type": "pause"}
        ).status_code
        == 403
    )
    assert client.get(annotation_url).status_code == 403
    cookie_headers = {"Cookie": f"dt_video_controller={captured[1]}"}
    updated = client.patch(
        f"{annotation_url}/{annotation['mark_id']}",
        json={"note": "Updated", "reviewed": True},
        headers=cookie_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["reviewed_at"]
    assert (
        client.delete(
            f"{annotation_url}/{annotation['mark_id']}", headers=cookie_headers
        ).status_code
        == 200
    )
    assert service.get_timed_media_store().get(material_id)["learning"]["marks"] == []


def test_player_sync_rebinds_material_when_video_changes(client: TestClient):
    created = _renderer(client, video_id="dQw4w9WgXcQ")
    device, headers = _device(client, created["ticket"])
    first_sync = client.post(
        "/api/video-learning/player/sync",
        headers=headers,
        json={
            "renderer_origin": "https://invidious.example",
            "video_id": "dQw4w9WgXcQ",
            "title": "First",
            "position_ms": 12_000,
            "duration_ms": 120_000,
        },
    ).json()
    first_session = first_sync["session"]
    first_store = service.get_timed_media_store()
    first_material = first_store.get(first_session["material_id"])
    first_mark = create_mark(
        first_material,
        {
            "kind": "key_point",
            "start_seconds": 12,
            "end_seconds": 12,
            "note": "Keep on the first video",
            "author": "user",
            "source": "remote_phone",
        },
    )
    first_store.save(first_material)

    second_sync = client.post(
        "/api/video-learning/player/sync",
        headers=headers,
        json={
            "session_id": first_session["session_id"],
            "renderer_origin": "https://invidious.example",
            "video_id": "89ThCi5qq-A",
            "title": "Second",
            "position_ms": 1_000,
            "duration_ms": 90_000,
        },
    )
    assert second_sync.status_code == 200
    second_session = second_sync.json()["session"]
    assert second_session["video_id"] == "89ThCi5qq-A"
    assert second_session["material_id"] != first_session["material_id"]

    store = service.get_timed_media_store()
    assert store.get(second_session["material_id"])["learning"].get("marks", []) == []
    assert store.get(first_session["material_id"])["learning"]["marks"] == [first_mark]


def test_device_commands_are_owner_scoped_and_expire(client: TestClient, tmp_path: Path):
    created = _renderer(client, video_id="dQw4w9WgXcQ")
    device, headers = _device(client, created["ticket"])
    assert client.post("/api/video-learning/player/presence", headers=headers).status_code == 200
    command = client.post(
        f"/api/video-learning/devices/{device['device_id']}/commands",
        json={"type": "open_video", "video_id": "89ThCi5qq-A"},
    )
    assert command.status_code == 200
    pending = client.post("/api/video-learning/player/presence", headers=headers).json()
    assert pending["commands"][0]["payload"] == {"video_id": "89ThCi5qq-A"}
    acked = client.post(
        f"/api/video-learning/player/device-commands/{command.json()['command_id']}/ack",
        headers=headers,
        json={"ok": False, "error": "player rejected"},
    )
    assert acked.json()["status"] == "failed"

    store = RemoteControlStore(video_remote_control._db_path())
    store.revoke_device("local-admin", device["device_id"])
    assert client.post("/api/video-learning/player/presence", headers=headers).status_code == 403
