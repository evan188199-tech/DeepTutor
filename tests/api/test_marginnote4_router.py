from __future__ import annotations

from pathlib import Path

import pytest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover - optional server dependency
    FastAPI = None
    TestClient = None

from deeptutor.api.routers import marginnote4 as router_module
from deeptutor.api.routers.auth import require_auth
from deeptutor.capabilities.marginnote4.device_registry import DeviceRegistry
from deeptutor.capabilities.marginnote4.store import MarginNoteStore

pytestmark = pytest.mark.skipif(
    FastAPI is None or TestClient is None, reason="fastapi is not installed"
)


def _object(object_id: str) -> dict:
    return {
        "object_id": object_id,
        "object_type": "note",
        "title": object_id,
        "content": f"Content {object_id}",
    }


def _build_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    remote: bool = False,
) -> TestClient:
    store = MarginNoteStore(tmp_path / "kb.db")
    registry = DeviceRegistry(str(tmp_path / "registry.db"))
    monkeypatch.setattr(router_module, "DeviceRegistry", lambda: registry)
    monkeypatch.setattr(
        router_module,
        "_session_store",
        lambda kb_name: ("local-admin", "kb-1", store),
    )
    app = FastAPI()
    app.include_router(router_module.router, prefix="/api/v1/marginnote4")
    app.dependency_overrides[require_auth] = lambda: None
    client_kwargs = {} if not remote else {"client": ("203.0.113.10", "12345")}
    return TestClient(app, **client_kwargs)


def test_pair_sync_writeback_and_automation_flow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _build_client(monkeypatch, tmp_path) as client:
        issued = client.post("/api/v1/marginnote4/pairing-codes", json={"kb_name": "notes"})
        assert issued.status_code == 200, issued.text
        code = issued.json()["code"]
        assert issued.json()["command"].startswith("deeptutor mn4 bridge pair --server")

        paired = client.post(
            "/api/v1/marginnote4/devices/pair",
            json={"code": code, "device_name": "Mac", "device_kind": "macos"},
        )
        assert paired.status_code == 200, paired.text
        device = paired.json()
        auth = {"Authorization": f"MarginNote {device['device_id']}:{device['token']}"}

        synced = client.post(
            "/api/v1/marginnote4/sync/batches",
            headers=auth,
            json={
                "sync_id": "sync-1",
                "sequence": 1,
                "final": True,
                "snapshot_hash": "snapshot-a",
                "objects": [_object("note:1")],
                "deleted_ids": [],
            },
        )
        assert synced.status_code == 200, synced.text
        assert synced.json()["stored"] == 1

        created = client.post(
            "/api/v1/marginnote4/writebacks",
            json={
                "kb_name": "notes",
                "title": "Summary",
                "markdown": "Reviewed note",
                "source_refs": ["note:1"],
            },
        )
        assert created.status_code == 200, created.text
        writeback_id = created.json()["writeback_id"]

        approved = client.post(
            f"/api/v1/marginnote4/writebacks/{writeback_id}/approve",
            json={"kb_name": "notes"},
        )
        claimed = client.post("/api/v1/marginnote4/jobs/claim", headers=auth)
        assert claimed.status_code == 200
        job = claimed.json()["job"]
        assert job["writeback_id"] == writeback_id
        assert job["delivery_mode"] == "import_queue"
        assert approved.json()["status"] == "approved"

        completed = client.post(
            "/api/v1/marginnote4/jobs/complete",
            headers=auth,
            json={
                "writeback_id": writeback_id,
                "lease_token": job["lease"]["token"],
                "payload_hash": job["payload_hash"],
                "delivery_mode": "import_queue",
                "provider": "import_queue",
                "result": "awaiting_import",
                "written_at": "2026-01-01T00:00:00+00:00",
            },
        )
        assert completed.status_code == 200, completed.text
        assert completed.json()["completed_at"] == "2026-01-01T00:00:00+00:00"

        verification = {
            "provider": "applescript",
            "bundle_id": "com.marginnote.MarginNote4",
            "app_version": "4.2",
            "config_hash": "cfg-hash",
        }
        assert (
            client.get(
                "/api/v1/marginnote4/automation/verification",
                headers=auth,
                params=verification,
            ).json()["verified"]
            is False
        )
        recorded = client.post(
            "/api/v1/marginnote4/automation/verification",
            headers=auth,
            json={**verification, "test_external_id": "note-id", "verified": True},
        )
        assert recorded.status_code == 200
        assert (
            client.get(
                "/api/v1/marginnote4/automation/verification",
                headers=auth,
                params=verification,
            ).json()["verified"]
            is True
        )


def test_remote_plain_http_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with _build_client(monkeypatch, tmp_path, remote=True) as client:
        response = client.post(
            "/api/v1/marginnote4/devices/pair",
            json={"code": "mn4-invalid"},
        )
    assert response.status_code == 426
    assert response.json()["detail"] == "MarginNote bridge requires HTTPS for non-local servers"


def test_url_scheme_verification_requires_confirmed_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _build_client(monkeypatch, tmp_path) as client:
        issued = client.post("/api/v1/marginnote4/pairing-codes", json={"kb_name": "notes"})
        paired = client.post(
            "/api/v1/marginnote4/devices/pair",
            json={"code": issued.json()["code"]},
        )
        auth = {
            "Authorization": (f"MarginNote {paired.json()['device_id']}:{paired.json()['token']}")
        }
        response = client.post(
            "/api/v1/marginnote4/automation/verification",
            headers=auth,
            json={
                "provider": "url_scheme",
                "bundle_id": "unknown",
                "app_version": "unknown",
                "config_hash": "cfg",
                "verified": True,
            },
        )
    assert response.status_code == 400
    assert "confirmed test note" in response.json()["detail"]
