from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import video_learning
from deeptutor.api.routers.auth import require_auth
from deeptutor.services.notebook import service as notebook_service
from deeptutor.services.path_service import PathService
from deeptutor.video_learning.store import VideoLearningStore, default_db_path


@pytest.fixture
def home(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    notebook_service._instances.clear()
    yield tmp_path
    PathService.reset_instance()
    notebook_service._instances.clear()


@pytest.fixture
def client(home: Path):
    app = FastAPI()
    app.include_router(video_learning.router, prefix="/api/v1/video-learning")
    app.dependency_overrides[require_auth] = lambda: None
    with TestClient(app) as test_client:
        yield test_client


def _pair_and_sync(client: TestClient) -> tuple[str, dict[str, str], str]:
    created = client.post("/api/v1/video-learning/pairings")
    assert created.status_code == 200, created.text
    pairing = created.json()

    claimed = client.post(
        "/api/v1/video-learning/pairings/claim",
        json={"code": pairing["code"], "device_name": "Living Room iPad"},
    )
    assert claimed.status_code == 200, claimed.text

    status = client.get(
        f"/api/v1/video-learning/pairings/{pairing['pairing_id']}/status",
        params={"claim_secret": pairing["claim_secret"]},
    )
    assert status.status_code == 200, status.text
    body = status.json()
    token = body["token"]
    device_id = body["device_id"]
    auth = {"Authorization": f"VideoLearning {device_id}:{token}"}

    synced = client.post(
        "/api/v1/video-learning/player/sync",
        headers=auth,
        json={
            "instance_origin": "http://127.0.0.1:3000",
            "video_id": "dQw4w9WgXcQ",
            "title": "Demo",
            "position_ms": 15000,
            "duration_ms": 60000,
            "playback_state": "playing",
            "playback_rate": 1.0,
        },
    )
    assert synced.status_code == 200, synced.text
    session_id = synced.json()["session"]["session_id"]
    return session_id, auth, device_id


def test_unauthenticated_sync_writes_nothing(client, home: Path) -> None:
    response = client.post(
        "/api/v1/video-learning/player/sync",
        json={
            "instance_origin": "http://127.0.0.1:3000",
            "video_id": "dQw4w9WgXcQ",
            "position_ms": 1000,
        },
        headers={"Authorization": "VideoLearning fake:token"},
    )
    assert response.status_code == 403
    assert not (PathService.get_instance().user_data_dir / "video_learning").exists()


def test_pair_claim_sync_command_note_round_trip(client) -> None:
    session_id, auth, _device_id = _pair_and_sync(client)

    command = client.post(
        f"/api/v1/video-learning/sessions/{session_id}/commands",
        json={"type": "seek", "delta_ms": -10000, "command_id": "c1"},
    )
    assert command.status_code == 200, command.text
    assert command.json()["payload"]["position_ms"] == 5000

    polled = client.post(
        "/api/v1/video-learning/player/sync",
        headers=auth,
        json={
            "session_id": session_id,
            "instance_origin": "http://127.0.0.1:3000",
            "video_id": "dQw4w9WgXcQ",
            "title": "Demo",
            "position_ms": 15000,
            "duration_ms": 60000,
            "playback_state": "playing",
            "playback_rate": 1.0,
        },
    )
    assert polled.status_code == 200
    assert polled.json()["commands"][0]["command_id"] == "c1"

    acked = client.post(
        "/api/v1/video-learning/player/commands/c1/ack",
        headers=auth,
        json={"ok": True},
    )
    assert acked.status_code == 200
    assert acked.json()["status"] == "acked"

    note = client.post(
        "/api/v1/video-learning/videos/dQw4w9WgXcQ/notes",
        json={"body": "mark this", "position_ms": 15000, "title": "Demo", "instance_origin": "http://127.0.0.1:3000"},
    )
    assert note.status_code == 201, note.text
    body = note.json()
    assert body["position_ms"] == 15000
    assert body["notebook_id"]
    assert body["record_id"]
    assert "note_id" not in body

    listed = client.get("/api/v1/video-learning/videos/dQw4w9WgXcQ/notes")
    assert listed.status_code == 200
    assert len(listed.json()["notes"]) == 1

    updated = client.patch(
        f"/api/v1/video-learning/notes/{body['notebook_id']}/{body['record_id']}",
        json={"body": "edited"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["body"] == "edited"

    deleted = client.delete(
        f"/api/v1/video-learning/notes/{body['notebook_id']}/{body['record_id']}"
    )
    assert deleted.status_code == 200


def test_capture_timestamp_pause_and_offline_reject(client, home: Path) -> None:
    session_id, auth, _device_id = _pair_and_sync(client)

    import threading
    import time

    def ack_pause():
        # Poll until pause command appears, then ack and sync paused position.
        deadline = time.time() + 5
        while time.time() < deadline:
            polled = client.post(
                "/api/v1/video-learning/player/sync",
                headers=auth,
                json={
                    "session_id": session_id,
                    "instance_origin": "http://127.0.0.1:3000",
                    "video_id": "dQw4w9WgXcQ",
                    "title": "Demo",
                    "position_ms": 15100,
                    "duration_ms": 60000,
                    "playback_state": "paused",
                    "playback_rate": 1.0,
                },
            )
            assert polled.status_code == 200
            commands = polled.json().get("commands") or []
            if commands:
                command_id = commands[0]["command_id"]
                acked = client.post(
                    f"/api/v1/video-learning/player/commands/{command_id}/ack",
                    headers=auth,
                    json={"ok": True},
                )
                assert acked.status_code == 200
                return
            time.sleep(0.1)

    worker = threading.Thread(target=ack_pause, daemon=True)
    worker.start()
    captured = client.post(f"/api/v1/video-learning/sessions/{session_id}/capture-timestamp")
    worker.join(timeout=6)
    assert captured.status_code == 200, captured.text
    assert captured.json()["position_ms"] == 15100

    # Force offline and ensure capture is rejected.
    store = VideoLearningStore(default_db_path(path_service=PathService.get_instance()))
    with store._connect() as conn:
        conn.execute(
            "UPDATE sessions SET last_heartbeat_at = ? WHERE session_id = ?",
            ((datetime.now(timezone.utc) - timedelta(seconds=20)).isoformat(), session_id),
        )
    offline = client.post(f"/api/v1/video-learning/sessions/{session_id}/capture-timestamp")
    assert offline.status_code == 409
