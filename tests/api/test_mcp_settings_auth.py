"""The deployment MCP registry is admin-only, and single-server writes are surgical.

A ``stdio`` server's ``command`` runs on the host as the application user, so
every route that can read or change this registry is administrator-gated. That
gate had no test at all.

Also pins the rest of the route surface: the read/whole-map-write endpoints,
the pre-save Test probe, and the gate's 401/403 HTTP mapping.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import mcp_settings
from deeptutor.api.routers.auth import require_admin
from deeptutor.services.auth import TokenPayload
from deeptutor.services.mcp.config import (
    MCPConfig,
    MCPServerConfig,
    load_mcp_config,
)


@pytest.fixture(autouse=True)
def _offline_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """The URL guard resolves DNS; a unit test must not depend on a resolver."""
    import socket

    monkeypatch.setattr(
        "deeptutor.services.mcp.network.socket.getaddrinfo",
        lambda host, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))],
    )


@pytest.fixture
def admin_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Mount the router with the admin gate satisfied and config on tmp disk."""
    config_path = tmp_path / "mcp.json"
    monkeypatch.setattr(
        "deeptutor.services.mcp.config.mcp_config_path",
        lambda: config_path,
    )

    class _Manager:
        async def ensure_started(self) -> None: ...

        async def reload(self) -> None: ...

        def status(self, owner: str = "_shared") -> list[dict[str, object]]:
            return []

    monkeypatch.setattr(mcp_settings, "get_mcp_manager", lambda: _Manager())

    app = FastAPI()
    app.include_router(mcp_settings.router, prefix="/api/settings/mcp")
    app.dependency_overrides[require_admin] = lambda: None
    return TestClient(app)


def _write(config_path: Path, config: MCPConfig) -> None:
    config_path.write_text(config.model_dump_json(indent=2), encoding="utf-8")


def test_every_route_is_admin_gated() -> None:
    """Asserted on the router itself: a route added later inherits the gate.

    Checking each path individually would pass while a newly added route sat
    ungated, because the dependency lives on the router.
    """
    gated = {
        dependency.dependency
        for dependency in mcp_settings.router.dependencies
        if dependency.dependency is not None
    }
    assert require_admin in gated


def test_single_server_put_preserves_the_other_entries(
    admin_client: TestClient, tmp_path: Path
) -> None:
    config_path = tmp_path / "mcp.json"
    _write(
        config_path,
        MCPConfig(
            servers={
                "keep": MCPServerConfig(url="https://keep.example/mcp", disabled_tools=["noisy"]),
                "edit": MCPServerConfig(url="https://old.example/mcp"),
            }
        ),
    )

    response = admin_client.put(
        "/api/settings/mcp/servers/edit",
        json={"url": "https://new.example/mcp"},
    )

    assert response.status_code == 200
    servers = response.json()["servers"]
    assert servers["edit"]["url"] == "https://new.example/mcp"
    # The untouched entry keeps a field the editor does not model.
    assert servers["keep"]["disabled_tools"] == ["noisy"]


def test_single_server_delete_removes_only_that_entry(
    admin_client: TestClient, tmp_path: Path
) -> None:
    config_path = tmp_path / "mcp.json"
    _write(
        config_path,
        MCPConfig(
            servers={
                "a": MCPServerConfig(url="https://a.example/mcp"),
                "b": MCPServerConfig(url="https://b.example/mcp"),
            }
        ),
    )

    response = admin_client.delete("/api/settings/mcp/servers/a")

    assert response.status_code == 200
    assert set(response.json()["servers"]) == {"b"}


def test_an_invalid_server_name_is_refused(admin_client: TestClient, tmp_path: Path) -> None:
    (tmp_path / "mcp.json").write_text('{"servers": {}}', encoding="utf-8")
    response = admin_client.put(
        "/api/settings/mcp/servers/bad name!",
        json={"url": "https://x.example/mcp"},
    )
    assert response.status_code == 400


@pytest.fixture
def gated_client() -> TestClient:
    """The router mounted with the real admin gate active — no overrides."""
    app = FastAPI()
    app.include_router(mcp_settings.router, prefix="/api/settings/mcp")
    return TestClient(app)


def test_missing_token_is_unauthorized(
    gated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("deeptutor.api.routers.auth.AUTH_ENABLED", True)
    response = gated_client.get("/api/settings/mcp")
    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"
    assert response.headers["www-authenticate"] == "Bearer"


def test_non_admin_token_is_forbidden(
    gated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("deeptutor.api.routers.auth.AUTH_ENABLED", True)
    monkeypatch.setattr(
        "deeptutor.api.routers.auth.decode_token",
        lambda token: TokenPayload(username="worker", role="user", user_id="u_worker"),
    )
    response = gated_client.get(
        "/api/settings/mcp", headers={"Authorization": "Bearer worker-token"}
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Admin access required"


def test_get_returns_an_empty_registry_before_the_first_save(admin_client: TestClient) -> None:
    response = admin_client.get("/api/settings/mcp")
    assert response.status_code == 200
    assert response.json() == {"servers": {}, "status": []}


def test_get_serializes_saved_servers_alongside_live_status(
    admin_client: TestClient, tmp_path: Path
) -> None:
    _write(
        tmp_path / "mcp.json",
        MCPConfig(servers={"local": MCPServerConfig(command="uvx", args=["mcp-server-fetch"])}),
    )
    body = admin_client.get("/api/settings/mcp").json()
    assert body["servers"]["local"]["command"] == "uvx"
    assert body["servers"]["local"]["args"] == ["mcp-server-fetch"]
    assert body["servers"]["local"]["tool_timeout"] == 30
    assert body["status"] == []


def test_whole_map_put_replaces_the_registry(admin_client: TestClient, tmp_path: Path) -> None:
    config_path = tmp_path / "mcp.json"
    _write(
        config_path,
        MCPConfig(servers={"stale": MCPServerConfig(url="https://stale.example/mcp")}),
    )

    response = admin_client.put(
        "/api/settings/mcp",
        json={"servers": {"fresh": {"command": "uvx", "args": ["mcp-server-fetch"]}}},
    )

    assert response.status_code == 200
    assert response.json()["status"] == []
    assert set(load_mcp_config().servers) == {"fresh"}


def test_whole_map_put_rejects_a_server_without_transport(admin_client: TestClient) -> None:
    response = admin_client.put("/api/settings/mcp", json={"servers": {"blank": {}}})
    assert response.status_code == 400
    assert load_mcp_config().servers == {}


def test_whole_map_put_rejects_an_invalid_url(admin_client: TestClient) -> None:
    response = admin_client.put(
        "/api/settings/mcp",
        json={"servers": {"web": {"url": "ftp://example.com/mcp"}}},
    )
    assert response.status_code == 400
    assert load_mcp_config().servers == {}


def test_whole_map_put_rejects_an_invalid_server_name(admin_client: TestClient) -> None:
    response = admin_client.put(
        "/api/settings/mcp",
        json={"servers": {"bad name!": {"command": "uvx"}}},
    )
    assert response.status_code == 400


def test_whole_map_put_rejects_a_malformed_payload(admin_client: TestClient) -> None:
    response = admin_client.put("/api/settings/mcp", json={"servers": "everything"})
    assert response.status_code == 422


async def _fake_probe(cfg: MCPServerConfig) -> dict[str, object]:
    return {"ok": True, "tools": [{"name": "fetch", "description": ""}], "error": ""}


def test_probe_passes_the_config_through_and_returns_the_result(
    admin_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    probe: Callable[[MCPServerConfig], Awaitable[dict[str, object]]] = _fake_probe
    monkeypatch.setattr(mcp_settings, "probe_server", probe)
    response = admin_client.post("/api/settings/mcp/test", json={"command": "uvx", "args": ["srv"]})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert [tool["name"] for tool in body["tools"]] == ["fetch"]


def test_probe_refuses_a_server_without_transport(admin_client: TestClient) -> None:
    response = admin_client.post("/api/settings/mcp/test", json={})
    assert response.status_code == 400


def test_probe_rejects_an_invalid_url(admin_client: TestClient) -> None:
    response = admin_client.post("/api/settings/mcp/test", json={"url": "ftp://example.com/sse"})
    assert response.status_code == 400
