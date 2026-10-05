"""Contract tests for the per-user MCP surface: gates, forwarding failures, visibility.

Complements ``test_space_mcp.py`` (isolation, refusals, secret hygiene). This
file pins the *failure-visibility* contract: what a caller sees when auth
fails, when the MCP forwarding underneath fails, and that every refusal keeps
the machine-readable ``{"code", "message"}`` shape the router introduced.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import space_mcp
from deeptutor.api.routers.auth import require_learning_surface


@pytest.fixture(autouse=True)
def _offline_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the lookup is stubbed; the address policy itself still runs."""
    import socket

    def _getaddrinfo(host: str, *args: object, **kwargs: object) -> list[tuple]:
        loopback = host in {"localhost", "127.0.0.1", "::1"}
        addr = "127.0.0.1" if loopback else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, 0))]

    monkeypatch.setattr("deeptutor.services.mcp.network.socket.getaddrinfo", _getaddrinfo)


@pytest.fixture(autouse=True)
def _no_public_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """The redirect URI must come from the request, not an operator override."""
    monkeypatch.delenv("DEEPTUTOR_PUBLIC_URL", raising=False)


@pytest.fixture
def owner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Redirect the data roots and make the acting owner switchable."""
    from deeptutor.multi_user import paths

    admin_root = (tmp_path / "data").resolve()
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(paths, "USERS_ROOT", admin_root / "users")
    monkeypatch.setattr(paths, "SYSTEM_ROOT", admin_root / "system")
    monkeypatch.setattr(paths, "_path_services", {})

    acting = {"id": "u_ada"}
    monkeypatch.setattr(space_mcp, "current_owner_id", lambda: acting["id"])
    monkeypatch.setattr(
        "deeptutor.services.mcp.config.mcp_config_path", lambda: tmp_path / "admin-mcp.json"
    )
    return acting


class _Manager:
    """A manager that never connects anything, recording what it was asked."""

    def __init__(self, warm_seconds: float = 0.0) -> None:
        self.warm_seconds = warm_seconds
        self.reloaded: list[str] = []

    async def reload_scope(self, owner_id: str) -> None:
        self.reloaded.append(owner_id)

    async def ensure_started(self) -> None:
        import asyncio

        if self.warm_seconds:
            await asyncio.sleep(self.warm_seconds)

    async def ensure_scope(self, owner_id: str) -> list[Any]:
        import asyncio

        if self.warm_seconds:
            await asyncio.sleep(self.warm_seconds)
        return []

    def status(self, owner_id: str = "_shared") -> list[dict[str, Any]]:
        return []


@pytest.fixture
def manager(owner: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> _Manager:
    instance = _Manager()
    monkeypatch.setattr(space_mcp, "get_mcp_manager", lambda: instance)
    return instance


@pytest.fixture
def client(manager: _Manager) -> TestClient:
    app = FastAPI()
    app.include_router(space_mcp.router, prefix="/api/space/mcp")
    return TestClient(app)


@pytest.fixture
def gated_client(
    owner: dict[str, str],
    manager: _Manager,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    """The router mounted exactly as ``api/main.py`` mounts it: behind the auth gate."""
    from deeptutor.api.routers import auth as auth_router

    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "decode_token", lambda token: None)

    app = FastAPI()
    app.include_router(
        space_mcp.router,
        prefix="/api/space/mcp",
        dependencies=[Depends(require_learning_surface)],
    )
    return TestClient(app)


def _remote(url: str = "https://mcp.example.com/mcp") -> dict[str, Any]:
    return {"config": {"url": url}, "secrets": {}}


# ---------------------------------------------------------------------------
# Auth gate
# ---------------------------------------------------------------------------


_AUTHED_ROUTES = [
    ("get", "/api/space/mcp/servers", None),
    ("put", "/api/space/mcp/servers/nm", _remote()),
    ("delete", "/api/space/mcp/servers/nm", None),
    ("post", "/api/space/mcp/servers/nm/authorize", None),
    ("post", "/api/space/mcp/servers/nm/test", _remote()),
    ("get", "/api/space/mcp/oauth/callback", None),
    ("get", "/api/space/mcp/catalog", None),
    ("post", "/api/space/mcp/catalog/eid/install", {"secrets": {}}),
]


@pytest.mark.parametrize(("method", "path", "body"), _AUTHED_ROUTES)
def test_an_unauthenticated_caller_is_refused_on_every_route(
    gated_client: TestClient, method: str, path: str, body: dict[str, Any] | None
) -> None:
    """The surface is auth-gated, not admin-gated — the gate must hold everywhere.

    Asserted request by request on an app mounted the way ``api/main.py`` does
    it: the dependency lives on the include, so a route can only be reached
    through it.
    """
    kwargs: dict[str, Any] = {"json": body} if body is not None else {}
    response = getattr(gated_client, method)(path, **kwargs)
    assert response.status_code == 401, response.text
    assert response.json()["detail"] == "Not authenticated"


def test_an_invalid_token_is_refused(gated_client: TestClient) -> None:
    response = gated_client.get(
        "/api/space/mcp/servers", headers={"Authorization": "Bearer not-a-token"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired token"


# ---------------------------------------------------------------------------
# MCP forwarding failures
# ---------------------------------------------------------------------------


def test_authorize_begins_nothing_for_an_unknown_server(client: TestClient) -> None:
    """A miss is a localized 404 naming the server — not a crash, not a leak."""
    response = client.post("/api/space/mcp/servers/ghost/authorize")
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert isinstance(detail, str)
    assert "ghost" in detail


def test_authorize_refuses_a_server_that_does_not_use_oauth(client: TestClient) -> None:
    client.put("/api/space/mcp/servers/svc", json=_remote())
    response = client.post("/api/space/mcp/servers/svc/authorize")
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "mcp.not_oauth"
    assert isinstance(detail["message"], str) and detail["message"]


def test_a_failed_oauth_start_is_reported_with_a_code(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the provider is unreachable the caller gets the reason, with a code."""

    async def _unreachable(**kwargs: Any) -> str:
        raise RuntimeError("provider unreachable")

    monkeypatch.setattr(space_mcp.oauth, "begin_authorization", _unreachable)
    client.put(
        "/api/space/mcp/servers/svc",
        json={"config": {"url": "https://svc.example/mcp", "auth": "oauth"}, "secrets": {}},
    )
    response = client.post("/api/space/mcp/servers/svc/authorize")
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "mcp.oauth_start_failed"
    assert "RuntimeError: provider unreachable" in detail["message"]


def test_a_failed_probe_reports_the_upstream_reason_in_the_body(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dead server must answer with a readable reason, not a 500."""
    import deeptutor.services.mcp.manager as manager_module

    async def _dead_transport(stack: Any, cfg: Any, **kwargs: Any) -> tuple[Any, Any]:
        raise RuntimeError("connection refused by probe test")

    monkeypatch.setattr(manager_module.MCPConnectionManager, "_open_transport", _dead_transport)
    response = client.post("/api/space/mcp/servers/svc/test", json=_remote())
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["tools"] == []
    assert "RuntimeError: connection refused by probe test" in body["error"]


def test_a_slow_warmup_does_not_hold_the_servers_page(
    owner: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A slow third-party host costs its own row's status, not the page."""
    monkeypatch.setattr(space_mcp, "get_mcp_manager", lambda: _Manager(warm_seconds=0.5))
    monkeypatch.setattr(space_mcp, "_STATUS_WARM_TIMEOUT_S", 0.01)
    app = FastAPI()
    app.include_router(space_mcp.router, prefix="/api/space/mcp")
    client = TestClient(app)

    response = client.get("/api/space/mcp/servers")

    assert response.status_code == 200
    body = response.json()
    assert body["servers"] == {}
    assert body["limits"]["max_servers"] > 0


# ---------------------------------------------------------------------------
# OAuth callback contract
# ---------------------------------------------------------------------------


def test_a_forged_oauth_callback_completes_nothing(client: TestClient) -> None:
    """A state nothing is waiting on answers the failure page and grants nothing."""
    response = client.get(
        "/api/space/mcp/oauth/callback", params={"code": "abc", "state": "forged"}
    )
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("text/html")
    assert "expired or already completed" in response.text


def test_a_provider_reported_oauth_error_is_shown_escaped(client: TestClient) -> None:
    """The provider's error reaches the person, but only through escaping."""
    response = client.get(
        "/api/space/mcp/oauth/callback",
        params={"error": "access_denied", "error_description": "provider said no & <b>bold</b>"},
    )
    assert response.status_code == 400
    assert "provider said no &amp; &lt;b&gt;bold&lt;/b&gt;" in response.text
    assert "<b>" not in response.text


def test_an_incomplete_oauth_callback_answers_with_the_page(client: TestClient) -> None:
    response = client.get("/api/space/mcp/oauth/callback")
    assert response.status_code == 400
    assert "incomplete" in response.text


def test_the_oauth_success_page_renders(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(space_mcp.oauth, "complete_authorization", lambda state, code: True)
    response = client.get(
        "/api/space/mcp/oauth/callback", params={"code": "abc", "state": "pending-flow"}
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "close this tab" in response.text


# ---------------------------------------------------------------------------
# Failure visibility (error-scan regression)
# ---------------------------------------------------------------------------


def test_a_config_that_fails_revalidation_answers_400_with_text(client: TestClient) -> None:
    """A labelled literal colliding with a config field must stay a client error.

    The 400-with-text detail on this path is the pinned contract: the caller is
    told the definition was rejected — never an unhandled 500.
    """
    response = client.put(
        "/api/space/mcp/servers/nm",
        json={
            "config": {"url": "https://svc.example/mcp", "auth": "oauth"},
            "secrets": {"token": "oauth"},
        },
    )
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], str)


def test_the_catalog_missing_entry_reports_the_id_in_a_localized_line(
    client: TestClient,
) -> None:
    """The unknown-entry 404 names the id in plain text — no raw exception text."""
    response = client.post("/api/space/mcp/catalog/no-such-entry/install", json={"secrets": {}})
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert isinstance(detail, str)
    assert "no-such-entry" in detail


def test_the_ninth_server_is_refused_with_a_code(client: TestClient, owner: dict[str, str]) -> None:
    """The per-account cap is a structured refusal, and the saved eight survive."""
    for index in range(space_mcp.MAX_SERVERS_PER_OWNER):
        saved = client.put(f"/api/space/mcp/servers/svc-{index}", json=_remote())
        assert saved.status_code == 200, saved.text

    over = client.put(
        f"/api/space/mcp/servers/svc-{space_mcp.MAX_SERVERS_PER_OWNER}", json=_remote()
    )
    assert over.status_code == 400
    assert over.json()["detail"]["code"] == "mcp.too_many_servers"
    assert len(client.get("/api/space/mcp/servers").json()["servers"]) == (
        space_mcp.MAX_SERVERS_PER_OWNER
    )


def _first_free_entry() -> Any:
    from deeptutor.services.mcp.catalog import load_catalog

    return next(
        entry
        for entry in load_catalog()
        if entry.self_service and not any(field.required for field in entry.fields)
    )


def test_the_install_path_refuses_a_deployment_name_with_a_code(
    client: TestClient, owner: dict[str, str], tmp_path: Path
) -> None:
    """The name-collision refusal holds on the install route too, with its code."""
    (tmp_path / "admin-mcp.json").write_text(
        '{"servers": {"github": {"url": "https://admin.example/mcp"}}}', encoding="utf-8"
    )
    entry = _first_free_entry()
    response = client.post(
        f"/api/space/mcp/catalog/{entry.id}/install", json={"name": "github", "secrets": {}}
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "mcp.name_reserved"


# ---------------------------------------------------------------------------
# Success paths
# ---------------------------------------------------------------------------


def test_authorize_returns_the_consent_url_for_an_oauth_server(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The flow starts only here, and the redirect returns to the browsing origin."""
    captured: dict[str, Any] = {}

    async def _begin(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "https://provider.example/authorize?state=s3cret"

    monkeypatch.setattr(space_mcp.oauth, "begin_authorization", _begin)
    saved = client.put(
        "/api/space/mcp/servers/svc",
        json={"config": {"url": "https://svc.example/mcp", "auth": "oauth"}, "secrets": {}},
    )
    assert saved.status_code == 200, saved.text

    response = client.post(
        "/api/space/mcp/servers/svc/authorize",
        headers={"x-forwarded-proto": "https", "x-forwarded-host": "proxy.example"},
    )

    assert response.status_code == 200
    assert response.json() == {"authorize_url": "https://provider.example/authorize?state=s3cret"}
    assert captured["server_name"] == "svc"
    assert captured["owner_id"] == "u_ada"
    assert captured["redirect_uri"] == "https://proxy.example/api/space/mcp/oauth/callback"
