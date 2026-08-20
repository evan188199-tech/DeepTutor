from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor.api.routers import marginnote4
from deeptutor.services.marginnote4.service import MarginNote4Service


def _client(tmp_path: Path, user_id: str = "user-a") -> TestClient:
    marginnote4._current_user_id = lambda: user_id
    app = FastAPI()
    app.state.marginnote4_service = MarginNote4Service(tmp_path / "bridge.sqlite3")
    app.state.marginnote4_allow_test_transport = True
    app.dependency_overrides[marginnote4.require_auth] = lambda: None
    app.include_router(marginnote4.router, prefix="/api/v1/marginnote4")
    client = TestClient(app)
    client.headers.update({"X-Test-User": user_id})
    return client


def _active_device(client: TestClient, library_id: str) -> tuple[str, dict[str, Any]]:
    created = client.post(
        "/api/v1/marginnote4/pairing-sessions",
        json={"library_id": library_id, "library_name": f"Library {library_id}"},
    )
    assert created.status_code == 200
    session = created.json()["session"]
    code = created.json()["pairing_code"]

    claimed = client.post(
        "/api/v1/marginnote4/device/claim",
        json={"pairing_code": code, "device_name": "iPad", "device_kind": "ipados"},
    )
    assert claimed.status_code == 200
    assert (
        client.post(
            f"/api/v1/marginnote4/pairing-sessions/{session['session_id']}/confirm"
        ).status_code
        == 200
    )
    token_response = client.post(
        f"/api/v1/marginnote4/device/{claimed.json()['device_id']}/token",
        json={"claim_secret": claimed.json()["claim_secret"]},
    )
    assert token_response.status_code == 200
    return token_response.json()["token"], claimed.json()


def test_full_pair_sync_revoke_flow_ignores_client_library_header(tmp_path: Path) -> None:
    client = _client(tmp_path)
    token, device = _active_device(client, "library-a")
    headers = {"Authorization": f"Bearer {token}", "X-MN4-KB": "attacker-library"}

    pushed = client.post(
        "/api/v1/marginnote4/device/sync",
        headers=headers,
        json={
            "protocol_version": 1,
            "operation_id": "op-1",
            "objects": [
                {
                    "object_id": "note-1",
                    "object_type": "note",
                    "revision": 1,
                    "content": "synced",
                    "source_locator": {"uri": "marginnote3app://note/1"},
                }
            ],
            "deletions": [],
        },
    )
    assert pushed.status_code == 200
    assert pushed.json()["accepted"] == 1

    pulled = client.get(
        "/api/v1/marginnote4/device/changes",
        headers=headers,
        params={"cursor": 0},
    )
    assert pulled.status_code == 200
    assert pulled.json()["changes"][0]["object_id"] == "note-1"

    service: MarginNote4Service = client.app.state.marginnote4_service
    assert (
        service.get_object(user_id="user-a", library_id="library-a", object_id="note-1") is not None
    )
    assert (
        service.get_object(user_id="user-a", library_id="attacker-library", object_id="note-1")
        is None
    )

    assert client.delete(f"/api/v1/marginnote4/devices/{device['device_id']}").status_code == 200
    assert client.post("/api/v1/marginnote4/device/heartbeat", headers=headers).status_code == 401


def test_pairing_sessions_are_user_scoped(tmp_path: Path) -> None:
    owner = _client(tmp_path, "user-a")
    created = owner.post(
        "/api/v1/marginnote4/pairing-sessions",
        json={"library_id": "library-a"},
    ).json()
    session_id = created["session"]["session_id"]

    other = _client(tmp_path, "user-b")
    assert other.get("/api/v1/marginnote4/pairing-sessions").json() == []
    assert (
        other.post(f"/api/v1/marginnote4/pairing-sessions/{session_id}/confirm").status_code == 404
    )


def test_non_loopback_plain_http_device_route_is_refused(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.app.state.marginnote4_allow_test_transport = False
    response = client.post(
        "/api/v1/marginnote4/device/claim",
        json={"pairing_code": "unused", "device_name": "Mac", "device_kind": "macos"},
    )
    assert response.status_code == 403
    assert "HTTPS" in response.json()["detail"]
