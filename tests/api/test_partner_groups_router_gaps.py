"""Boundary contract tests for the Partner Groups router.

Complements ``tests/api/test_partner_groups_router.py`` with the branches that
file leaves open: payload/query validation bounds, unknown-group 404 matrix,
whiteboard pin error mapping, and WebSocket auth / close-code contracts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from starlette.testclient import WebSocketDisconnect
except Exception:  # pragma: no cover
    FastAPI = None
    TestClient = None

from deeptutor.services.partners.manager import PartnerConfig, PartnerManager

pytestmark = pytest.mark.skipif(
    FastAPI is None or TestClient is None, reason="fastapi not installed"
)

UNKNOWN_GROUP = "no-such-group"


@pytest.fixture
def client(tmp_path: Path, monkeypatch) -> TestClient:
    from deeptutor.api.routers import auth as auth_module
    from deeptutor.api.routers import partner_groups as router_module
    from deeptutor.multi_user import paths
    import deeptutor.services.partner_groups.manager as manager_module
    from deeptutor.services.partner_groups.manager import PartnerGroupManager

    admin_root = (tmp_path / "data").resolve()
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(paths, "USERS_ROOT", admin_root / "users")
    monkeypatch.setattr(paths, "SYSTEM_ROOT", admin_root / "system")
    monkeypatch.setattr(paths, "_path_services", {})
    admin_root.mkdir(parents=True, exist_ok=True)
    from deeptutor.multi_user.context import reset_current_user, set_current_user
    from deeptutor.multi_user.models import CurrentUser, UserScope

    token = set_current_user(
        CurrentUser(
            id="local-admin",
            username="local",
            role="admin",
            scope=UserScope(kind="admin", user_id="local-admin", root=admin_root),
        )
    )

    partners = PartnerManager()
    partners.save_config("ada", PartnerConfig(name="Ada"))
    partners.save_config("bob", PartnerConfig(name="Bob"))
    monkeypatch.setattr(manager_module, "get_partner_manager", lambda: partners)
    groups = PartnerGroupManager()
    monkeypatch.setattr(router_module, "get_partner_group_manager", lambda: groups)
    monkeypatch.setattr(auth_module, "AUTH_ENABLED", False)

    app = FastAPI()
    app.state.partner_groups = groups
    app.state.partners = partners
    app.include_router(router_module.router, prefix="/api/partner-groups")
    app.include_router(router_module.ws_router, prefix="/ws/partner-groups")
    try:
        yield TestClient(app)
    finally:
        reset_current_user(token)


def _create_group(client: TestClient, name: str = "Boundary panel") -> str:
    response = client.post("/api/partner-groups", json={"name": name, "member_ids": ["ada", "bob"]})
    assert response.status_code == 200
    return response.json()["group_id"]


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "", "member_ids": ["ada", "bob"]},
        {"name": "x" * 81, "member_ids": ["ada", "bob"]},
        {"name": "No members"},
        {"name": "One member", "member_ids": ["ada"]},
        {"name": "Empty members", "member_ids": []},
        {"name": "Duplicate members", "member_ids": ["ada", "ada"]},
        {"name": "Long description", "member_ids": ["ada", "bob"], "description": "d" * 501},
    ],
    ids=[
        "empty-name",
        "name-over-80",
        "member-ids-missing",
        "single-member",
        "empty-member-ids",
        "duplicate-members-collapse",
        "description-over-500",
    ],
)
def test_create_group_rejects_invalid_payloads(client: TestClient, payload: dict) -> None:
    response = client.post("/api/partner-groups", json=payload)
    assert response.status_code == 422
    assert client.get("/api/partner-groups").json() == []


@pytest.mark.parametrize(
    "changes",
    [
        {"name": ""},
        {"discussion_mode": "unknown_mode"},
        {"shared_memory": "unknown_memory"},
        {"member_ids": ["ada", "missing"]},
    ],
    ids=["empty-name", "unknown-mode", "unknown-memory", "unavailable-member"],
)
def test_update_group_rejects_invalid_payloads(client: TestClient, changes: dict) -> None:
    group_id = _create_group(client, name="Original name")

    response = client.patch(f"/api/partner-groups/{group_id}", json=changes)

    assert response.status_code == 422
    unchanged = client.get(f"/api/partner-groups/{group_id}")
    assert unchanged.status_code == 200
    assert unchanged.json()["name"] == "Original name"
    assert unchanged.json()["discussion_mode"] == "panel_parallel"


def test_unknown_group_boundary_returns_404(client: TestClient) -> None:
    base = f"/api/partner-groups/{UNKNOWN_GROUP}"
    assert client.get(base).status_code == 404
    assert client.patch(base, json={"name": "Renamed"}).status_code == 404
    assert client.delete(base).status_code == 404
    assert client.get(f"{base}/history").status_code == 404
    assert client.get(f"{base}/sessions").status_code == 404
    assert client.post(f"{base}/sessions").status_code == 404
    assert client.delete(f"{base}/sessions/default").status_code == 404
    assert client.get(f"{base}/whiteboard").status_code == 404
    assert client.post(f"{base}/whiteboard/pins", json={"event_id": "ev"}).status_code == 404
    assert client.delete(f"{base}/whiteboard/pins/ev").status_code == 404
    assert client.get(f"{base}/invocations").status_code == 404
    assert (
        client.post(
            f"{base}/invocations",
            json={
                "session_key": "s",
                "requester_partner_id": "ada",
                "target_partner_id": "bob",
                "question": "Question?",
            },
        ).status_code
        == 404
    )
    assert (
        client.post(f"{base}/invocations/inv-1/approve", json={"session_key": "s"}).status_code
        == 404
    )
    assert client.post(f"{base}/messages", json={"content": "Hello"}).status_code == 404
    assert (
        client.post(f"{base}/turns/t1/partners/ada/retry", json={"session_key": "s"}).status_code
        == 404
    )
    assert (
        client.post(
            f"{base}/rounds/t1/summary", json={"session_key": "s", "partner_id": "ada"}
        ).status_code
        == 404
    )


@pytest.mark.parametrize("limit", [0, 501])
def test_history_and_whiteboard_reject_out_of_bounds_limits(client: TestClient, limit: int) -> None:
    group_id = _create_group(client)

    assert (
        client.get(f"/api/partner-groups/{group_id}/history", params={"limit": limit}).status_code
        == 422
    )
    assert (
        client.get(
            f"/api/partner-groups/{group_id}/whiteboard", params={"limit": limit}
        ).status_code
        == 422
    )
    assert (
        client.get(
            f"/api/partner-groups/{group_id}/invocations", params={"limit": limit}
        ).status_code
        == 422
    )


def test_history_accepts_limit_boundaries(client: TestClient) -> None:
    group_id = _create_group(client)

    assert (
        client.get(f"/api/partner-groups/{group_id}/history", params={"limit": 1}).status_code
        == 200
    )
    assert (
        client.get(f"/api/partner-groups/{group_id}/history", params={"limit": 500}).status_code
        == 200
    )
    assert (
        client.get(f"/api/partner-groups/{group_id}/history", params={"limit": "nan"}).status_code
        == 422
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"content": ""},
        {"content": "   "},
        {},
        {"content": "Hello", "session_key": ""},
        {"content": "Hello", "session_key": "s" * 121},
    ],
    ids=[
        "empty-content",
        "blank-content",
        "content-missing",
        "empty-session-key",
        "session-key-over-120",
    ],
)
def test_message_payload_validation_returns_422(client: TestClient, payload: dict) -> None:
    group_id = _create_group(client)

    response = client.post(f"/api/partner-groups/{group_id}/messages", json=payload)

    assert response.status_code == 422


def test_whiteboard_pin_payload_and_lookup_errors(client: TestClient) -> None:
    group_id = _create_group(client)

    empty = client.post(f"/api/partner-groups/{group_id}/whiteboard/pins", json={"event_id": ""})
    assert empty.status_code == 422

    missing = client.post(
        f"/api/partner-groups/{group_id}/whiteboard/pins", json={"event_id": "missing-event"}
    )
    assert missing.status_code == 404

    unpinned = client.delete(f"/api/partner-groups/{group_id}/whiteboard/pins/missing-event")
    assert unpinned.status_code == 404
    assert unpinned.json()["detail"] == "Whiteboard pin not found"


def test_pin_failed_reply_returns_conflict(client: TestClient, monkeypatch) -> None:
    from types import SimpleNamespace

    partners = client.app.state.partners
    monkeypatch.setattr(
        partners,
        "get_partner",
        lambda partner_id: SimpleNamespace(running=True, partner_id=partner_id),
    )

    async def ada_fails(partner_id, content, **kwargs):
        _ = (content, kwargs)
        if partner_id == "ada":
            raise RuntimeError("temporary failure")
        return f"{partner_id} answer"

    monkeypatch.setattr(partners, "send_group_message", ada_fails)
    group_id = _create_group(client, name="Pin conflict panel")
    turn = client.post(
        f"/api/partner-groups/{group_id}/messages",
        json={"content": "Compare", "session_key": "pin-conflict"},
    ).json()
    failed = next(reply for reply in turn["replies"] if reply["author_id"] == "ada")
    assert failed["error"] is True

    response = client.post(
        f"/api/partner-groups/{group_id}/whiteboard/pins",
        json={"event_id": failed["event_id"]},
    )

    assert response.status_code == 409


def test_create_group_accepts_field_boundaries(client: TestClient) -> None:
    response = client.post(
        "/api/partner-groups",
        json={
            "name": "n" * 80,
            "description": "d" * 500,
            "member_ids": ["ada", "bob"],
            "emoji": "🧪",
            "color": "#FF00AA",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "n" * 80
    assert body["description"] == "d" * 500
    assert body["color"] == "#ff00aa"

    fallback = client.post(
        "/api/partner-groups",
        json={"name": "Default colors", "member_ids": ["ada", "bob"], "color": "not-a-color"},
    )
    assert fallback.status_code == 200
    assert fallback.json()["color"] == "#6366f1"


def test_ws_unknown_group_closes_4404(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect(f"/ws/partner-groups/{UNKNOWN_GROUP}"):
            pass
    assert excinfo.value.code == 4404


def test_ws_requires_auth_when_enabled(client: TestClient, monkeypatch) -> None:
    from deeptutor.api.routers import auth as auth_module

    monkeypatch.setattr(auth_module, "AUTH_ENABLED", True)

    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect(f"/ws/partner-groups/{_create_group(client)}"):
            pass
    assert excinfo.value.code == 4001


def test_ws_invalid_frames_answer_with_error(client: TestClient) -> None:
    group_id = _create_group(client)

    with client.websocket_connect(f"/ws/partner-groups/{group_id}") as ws:
        ws.send_text("this is not json")
        assert ws.receive_json() == {"type": "error", "content": "Invalid Group message"}

        ws.send_json({"action": "mystery"})
        assert ws.receive_json() == {"type": "error", "content": "Invalid Group message"}
