"""The deployment MCP registry contract: read/write shape, 4xx refusals, and the
user-facing error texts.

Error strings leaving this router come from ``t()`` — three keys in all — so the
tests below lock both the HTTP contract and those exact translated messages.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import mcp_settings
from deeptutor.api.routers.auth import require_admin
from deeptutor.services.mcp.config import MCPConfig, MCPServerConfig

STATUS_STUB: list[dict[str, str]] = [{"server": "stub", "state": "stopped"}]


def _config_json(servers: dict[str, dict[str, Any]]) -> str:
    """Serialise a raw server map exactly as the API accepts it."""
    model = MCPConfig.model_validate({"servers": servers})
    return json.dumps(model.model_dump(mode="json"))


def _stdio(**overrides: Any) -> dict[str, Any]:
    return {"command": "uvx", "args": ["some-server"], **overrides}


def _on_disk(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        return {}
    return json.loads(config_path.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    """English messages and no DNS: the contract must not depend on either."""
    import socket

    monkeypatch.setattr("deeptutor.services.i18n.current_language", lambda default="en": "en")
    monkeypatch.setattr(
        "deeptutor.services.mcp.network.socket.getaddrinfo",
        lambda host, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))],
    )


class _RecordingManager:
    def __init__(self) -> None:
        self.started = 0
        self.reloads = 0

    async def ensure_started(self) -> None:
        self.started += 1

    async def reload(self) -> None:
        self.reloads += 1

    def status(self, owner: str = "_shared") -> list[dict[str, str]]:
        return STATUS_STUB


@pytest.fixture
def manager(monkeypatch: pytest.MonkeyPatch) -> _RecordingManager:
    instance = _RecordingManager()
    monkeypatch.setattr(mcp_settings, "get_mcp_manager", lambda: instance)
    return instance


@pytest.fixture
def config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "mcp.json"
    monkeypatch.setattr("deeptutor.services.mcp.config.mcp_config_path", lambda: path)
    return path


@pytest.fixture
def client(manager: _RecordingManager) -> TestClient:
    app = FastAPI()
    app.include_router(mcp_settings.router, prefix="/api/settings/mcp")
    app.dependency_overrides[require_admin] = lambda: None
    return TestClient(app)


def test_get_reports_servers_and_live_status(
    client: TestClient, config_path: Path, manager: _RecordingManager
) -> None:
    config_path.write_text(
        _config_json({"ws": _stdio(), "http": {"url": "https://mcp.example/mcp"}}),
        encoding="utf-8",
    )

    response = client.get("/api/settings/mcp")

    assert response.status_code == 200
    body = response.json()
    assert set(body["servers"]) == {"ws", "http"}
    assert body["servers"]["ws"]["command"] == "uvx"
    assert body["servers"]["http"]["url"] == "https://mcp.example/mcp"
    assert body["servers"]["http"]["enabled"] is True
    assert body["status"] == STATUS_STUB
    assert manager.started == 1


def test_get_on_missing_file_yields_an_empty_registry(
    client: TestClient, config_path: Path
) -> None:
    response = client.get("/api/settings/mcp")

    assert response.status_code == 200
    assert response.json() == {"servers": {}, "status": STATUS_STUB}
    assert config_path.exists() is False


def test_put_replaces_the_whole_map_and_persists(
    client: TestClient, config_path: Path, manager: _RecordingManager
) -> None:
    config_path.write_text(_config_json({"stale": _stdio()}), encoding="utf-8")

    response = client.put(
        "/api/settings/mcp",
        json={"servers": {"fresh": _stdio(env={"TOKEN": "s3cret"}, tool_timeout=90)}},
    )

    assert response.status_code == 200
    assert response.json()["status"] == STATUS_STUB
    assert manager.reloads == 1
    on_disk = _on_disk(config_path)
    assert set(on_disk["servers"]) == {"fresh"}
    assert on_disk["servers"]["fresh"]["env"] == {"TOKEN": "s3cret"}
    assert on_disk["servers"]["fresh"]["tool_timeout"] == 90


def test_put_refuses_a_server_without_command_or_url(
    client: TestClient, config_path: Path, manager: _RecordingManager
) -> None:
    response = client.put("/api/settings/mcp", json={"servers": {"ghost": {}}})

    assert response.status_code == 400
    assert (
        response.json()["detail"] == "Server 'ghost': configure either a command (stdio) or a url."
    )
    assert _on_disk(config_path) == {}
    assert manager.reloads == 0


def test_put_refuses_a_url_that_fails_validation(
    client: TestClient, config_path: Path, manager: _RecordingManager
) -> None:
    response = client.put(
        "/api/settings/mcp", json={"servers": {"remote": {"url": "ftp://mcp.example/mcp"}}}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Server 'remote': Only http/https allowed, got 'ftp'"
    assert _on_disk(config_path) == {}
    assert manager.reloads == 0


def test_put_rejects_an_invalid_server_name_with_400(
    client: TestClient, config_path: Path, manager: _RecordingManager
) -> None:
    response = client.put("/api/settings/mcp", json={"servers": {"bad name!": _stdio()}})

    assert response.status_code == 400
    assert "Invalid MCP server name" in response.json()["detail"]
    assert _on_disk(config_path) == {}
    assert manager.reloads == 0


def test_single_server_put_adds_an_entry_and_persists(
    client: TestClient, config_path: Path, manager: _RecordingManager
) -> None:
    config_path.write_text(
        _config_json({"keep": {"url": "https://keep.example/mcp"}}), encoding="utf-8"
    )

    response = client.put(
        "/api/settings/mcp/servers/added", json={"url": "https://added.example/mcp"}
    )

    assert response.status_code == 200
    assert set(response.json()["servers"]) == {"keep", "added"}
    assert response.json()["status"] == STATUS_STUB
    assert set(_on_disk(config_path)["servers"]) == {"keep", "added"}
    assert manager.reloads == 1


def test_single_server_put_refuses_an_invalid_server_without_persisting(
    client: TestClient, config_path: Path, manager: _RecordingManager
) -> None:
    original = _config_json({"keep": {"url": "https://keep.example/mcp"}})
    config_path.write_text(original, encoding="utf-8")

    response = client.put("/api/settings/mcp/servers/broken", json={})

    assert response.status_code == 400
    assert (
        response.json()["detail"] == "Server 'broken': configure either a command (stdio) or a url."
    )
    assert config_path.read_text(encoding="utf-8") == original
    assert manager.reloads == 0


def test_delete_of_a_missing_name_is_an_idempotent_success(
    client: TestClient, config_path: Path, manager: _RecordingManager
) -> None:
    config_path.write_text(
        _config_json({"kept": {"url": "https://kept.example/mcp"}}), encoding="utf-8"
    )

    response = client.delete("/api/settings/mcp/servers/ghost")

    assert response.status_code == 200
    assert set(response.json()["servers"]) == {"kept"}
    assert set(_on_disk(config_path)["servers"]) == {"kept"}
    assert manager.reloads == 1


def test_post_test_returns_the_probe_result(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[MCPServerConfig] = []

    async def fake_probe(cfg: MCPServerConfig, **kwargs: Any) -> dict[str, Any]:
        seen.append(cfg)
        return {"ok": True, "tools": [{"name": "echo", "description": ""}], "error": ""}

    monkeypatch.setattr(mcp_settings, "probe_server", fake_probe)

    response = client.post("/api/settings/mcp/test", json=_stdio())

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "tools": [{"name": "echo", "description": ""}],
        "error": "",
    }
    assert seen[0].command == "uvx"
    assert seen[0].args == ["some-server"]


def test_post_test_refuses_a_server_without_a_transport(client: TestClient) -> None:
    response = client.post("/api/settings/mcp/test", json={})

    assert response.status_code == 400
    assert (
        response.json()["detail"] == "Configure either a command (stdio) or a url before testing."
    )


def test_post_test_rejects_an_invalid_url_before_probing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail_probe(cfg: MCPServerConfig, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("probe must not run for an invalid url")

    monkeypatch.setattr(mcp_settings, "probe_server", fail_probe)

    response = client.post("/api/settings/mcp/test", json={"url": "ftp://mcp.example/mcp"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Only http/https allowed, got 'ftp'"
