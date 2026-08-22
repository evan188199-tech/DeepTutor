"""HTTP contract tests for the MarginNote 4 production bridge."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor.api.routers import marginnote4


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(marginnote4.router, prefix="/api/v1/marginnote4")
    return TestClient(app)


def _pair(tmp_path: Path) -> tuple[dict, str]:
    workspace = tmp_path / "owners" / "alice"
    code = (
        marginnote4._system_registry()
        .create_pairing_code(owner_id="u_alice", kb_name="library", workspace_root=str(workspace))
        .code
    )
    response = _client().post(
        "/api/v1/marginnote4/pair/claim",
        json={"code": code, "device_name": "MacBook", "protocol_version": 1},
    )
    assert response.status_code == 200, response.text
    return response.json(), str(workspace)


def test_claim_sync_snapshot_commit_and_heartbeat(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    claim, workspace = _pair(tmp_path)
    headers = {"Authorization": f"Bearer MN4 {claim['token']}"}
    client = _client()

    initial = client.post(
        "/api/v1/marginnote4/sync",
        headers=headers,
        json={
            "protocol_version": 1,
            "batch_id": "batch-0001",
            "cursor": "",
            "objects": [
                {
                    "object_id": "note1",
                    "object_type": "note",
                    "title": "Photosynthesis",
                    "content": "Green plants convert light energy.",
                    "revision": 1,
                }
            ],
        },
    )
    assert initial.status_code == 200, initial.text
    cursor = initial.json()["new_cursor"]

    duplicate = client.post(
        "/api/v1/marginnote4/sync",
        headers=headers,
        json={
            "protocol_version": 1,
            "batch_id": "batch-0001",
            "cursor": "wrong-after-success",
            "objects": [],
        },
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["new_cursor"] == cursor

    stale = client.post(
        "/api/v1/marginnote4/sync",
        headers=headers,
        json={
            "protocol_version": 1,
            "batch_id": "batch-0002",
            "cursor": "stale",
            "objects": [],
        },
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["server_cursor"] == cursor

    snapshot = client.post(
        "/api/v1/marginnote4/snapshots",
        headers=headers,
        json={"protocol_version": 1, "total_batches": 1},
    )
    assert snapshot.status_code == 200, snapshot.text
    snapshot_id = snapshot.json()["snapshot_id"]
    batch = client.put(
        f"/api/v1/marginnote4/snapshots/{snapshot_id}/batches/1",
        headers=headers,
        json={
            "protocol_version": 1,
            "batch_id": "snapshot-batch-1",
            "objects": [
                {
                    "object_id": "replacement",
                    "object_type": "note",
                    "title": "Replacement",
                    "revision": 1,
                }
            ],
        },
    )
    assert batch.status_code == 200, batch.text

    heartbeat_before_commit = client.post("/api/v1/marginnote4/heartbeat", headers=headers)
    assert heartbeat_before_commit.json()["object_count"] == 1

    commit = client.post(f"/api/v1/marginnote4/snapshots/{snapshot_id}/commit", headers=headers)
    assert commit.status_code == 200, commit.text
    assert commit.json()["object_count"] == 1

    heartbeat = client.post("/api/v1/marginnote4/heartbeat", headers=headers)
    assert heartbeat.status_code == 200
    assert heartbeat.json()["object_count"] == 1
    assert heartbeat.json()["kb_name"] == "library"

    store = marginnote4._store_for_device(
        SimpleNamespace(device_id=claim["device_id"], kb_name="library", workspace_root=workspace)
    )
    assert store.get("note1") is None
    assert store.get("replacement") is not None


def test_claim_rejects_second_active_device(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    registry = marginnote4._system_registry()
    code = registry.create_pairing_code(
        owner_id="u_alice", kb_name="library", workspace_root=str(tmp_path)
    ).code
    first = _client().post("/api/v1/marginnote4/pair/claim", json={"code": code})
    assert first.status_code == 200
    second_code = registry.create_pairing_code(
        owner_id="u_alice", kb_name="library", workspace_root=str(tmp_path)
    ).code
    second = _client().post("/api/v1/marginnote4/pair/claim", json={"code": second_code})
    assert second.status_code == 409


def test_revoked_device_cannot_sync(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    claim, workspace = _pair(tmp_path)
    marginnote4._system_registry().revoke(
        owner_id="u_alice", device_id=claim["device_id"], workspace_root=workspace
    )
    response = _client().post(
        "/api/v1/marginnote4/sync",
        headers={"Authorization": f"Bearer MN4 {claim['token']}"},
        json={"protocol_version": 1, "batch_id": "after-revoke", "cursor": ""},
    )
    assert response.status_code == 403


def test_body_and_object_limits_are_rejected(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    claim, _ = _pair(tmp_path)
    headers = {"Authorization": f"Bearer MN4 {claim['token']}"}
    response = _client().post(
        "/api/v1/marginnote4/sync",
        headers=headers,
        json={
            "protocol_version": 1,
            "batch_id": "too-large",
            "cursor": "",
            "objects": [
                {
                    "object_id": "large",
                    "object_type": "note",
                    "content": "x" * 300000,
                    "raw": {"payload": "y" * 300000},
                    "revision": 1,
                }
            ],
        },
    )
    assert response.status_code == 422
