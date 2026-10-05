"""Contract tests for the capabilities settings endpoints.

``/api/capabilities/settings`` reads and writes ``agents.yaml`` and, for
runtime knobs, ``main.yaml`` — a settings write path that had no test at
all. These pin the GET schema, the merge semantics that must not drop
unrelated YAML keys, the coerce/clamp behaviour on bad input, and the
auth gate's 401/403 mapping.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest
import yaml

from deeptutor.api.routers import capabilities_settings as router_module
from deeptutor.api.routers.auth import require_auth, require_learning_surface
from deeptutor.services.config import capabilities_settings as service_module
from deeptutor.utils.config_manager import ConfigManager

PREFIX = "/api/capabilities"


def _agents_yaml_path(root: Path) -> Path:
    return root / "data" / "user" / "settings" / "agents.yaml"


@pytest.fixture
def settings_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point agents.yaml and main.yaml at an empty per-test settings tree."""
    root = tmp_path / "home"
    (root / "data" / "user" / "settings").mkdir(parents=True)
    monkeypatch.setattr(service_module, "PROJECT_ROOT", root)
    monkeypatch.setattr(
        ConfigManager(),
        "config_path",
        root / "data" / "user" / "settings" / "main.yaml",
    )
    return root


@pytest.fixture
def client(settings_env: Path) -> TestClient:
    """The router mounted exactly as ``main.py`` mounts it, auth satisfied."""
    app = FastAPI()
    app.include_router(
        router_module.router, prefix=PREFIX, dependencies=[Depends(require_learning_surface)]
    )
    app.dependency_overrides[require_auth] = lambda: None
    return TestClient(app)


def test_get_returns_schema_with_defaults(client: TestClient) -> None:
    response = client.get(f"{PREFIX}/settings")
    assert response.status_code == 200
    body = response.json()
    assert {
        "chat",
        "solve",
        "research",
        "question",
        "visualize",
        "co_writer",
        "vision_solver",
        "math_animator",
    } <= set(body)
    assert body["solve"]["temperature"] == 0.3
    assert body["solve"]["max_tokens"] == 8192
    assert body["question"]["temperature"] == 0.7
    assert body["question"]["max_tokens"] == 4096
    assert set(body["chat"]["stage_budgets"]) == {"exploring", "responding"}


def test_get_reflects_agents_yaml_overrides(client: TestClient, settings_env: Path) -> None:
    _agents_yaml_path(settings_env).write_text(
        yaml.safe_dump({"capabilities": {"solve": {"temperature": 0.9}}}), encoding="utf-8"
    )
    body = client.get(f"{PREFIX}/settings").json()
    assert body["solve"]["temperature"] == 0.9
    assert body["solve"]["max_tokens"] == 8192


def test_put_round_trips_values_into_agents_yaml(client: TestClient, settings_env: Path) -> None:
    response = client.put(
        f"{PREFIX}/settings",
        json={"solve": {"temperature": 0.75, "max_tokens": 12345}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["solve"]["temperature"] == 0.75
    assert body["solve"]["max_tokens"] == 12345
    on_disk = yaml.safe_load(_agents_yaml_path(settings_env).read_text(encoding="utf-8"))
    assert on_disk["capabilities"]["solve"] == {"temperature": 0.75, "max_tokens": 12345}


def test_put_preserves_unrelated_yaml_keys(client: TestClient, settings_env: Path) -> None:
    seeded = {
        "capabilities": {"solve": {"temperature": 0.1, "note": "keep me"}},
        "unrelated": {"section": True},
    }
    _agents_yaml_path(settings_env).write_text(yaml.safe_dump(seeded), encoding="utf-8")
    response = client.put(f"{PREFIX}/settings", json={"solve": {"temperature": 0.8}})
    assert response.status_code == 200
    on_disk = yaml.safe_load(_agents_yaml_path(settings_env).read_text(encoding="utf-8"))
    assert on_disk["unrelated"] == {"section": True}
    assert on_disk["capabilities"]["solve"]["note"] == "keep me"
    assert on_disk["capabilities"]["solve"]["temperature"] == 0.8


def test_put_coerces_and_clamps_invalid_values(client: TestClient) -> None:
    response = client.put(
        f"{PREFIX}/settings",
        json={"research": {"temperature": "not-a-number", "max_tokens": -5}},
    )
    assert response.status_code == 200
    body = response.json()["research"]
    assert body["temperature"] == 0.5
    assert body["max_tokens"] == 1


def test_put_drops_unknown_capability_keys(client: TestClient, settings_env: Path) -> None:
    response = client.put(f"{PREFIX}/settings", json={"no_such_capability": {"temperature": 1.9}})
    assert response.status_code == 200
    assert "no_such_capability" not in response.json()
    on_disk = yaml.safe_load(_agents_yaml_path(settings_env).read_text(encoding="utf-8")) or {}
    assert "no_such_capability" not in (on_disk.get("capabilities") or {})


def test_put_writes_main_yaml_runtime_knobs(client: TestClient, settings_env: Path) -> None:
    response = client.put(
        f"{PREFIX}/settings", json={"solve": {"max_rounds": 30, "max_replans": 3}}
    )
    assert response.status_code == 200
    assert response.json()["solve"]["max_rounds"] == 30
    on_disk = yaml.safe_load(
        (settings_env / "data" / "user" / "settings" / "main.yaml").read_text(encoding="utf-8")
    )
    assert on_disk["capabilities"]["solve"] == {"max_rounds": 30, "max_replans": 3}


def test_put_clamps_runtime_knobs_into_range(client: TestClient) -> None:
    body = client.put(
        f"{PREFIX}/settings", json={"solve": {"max_rounds": 999, "max_replans": 99}}
    ).json()["solve"]
    assert body["max_rounds"] == 50
    assert body["max_replans"] == 10


def test_put_rejects_non_object_payload(client: TestClient) -> None:
    response = client.put(f"{PREFIX}/settings", json=[1, 2, 3])
    assert response.status_code == 422


def test_missing_token_is_unauthorized_when_auth_enabled(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("deeptutor.api.routers.auth.AUTH_ENABLED", True)
    client.app.dependency_overrides.pop(require_auth, None)
    response = client.put(f"{PREFIX}/settings", json={})
    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"


def test_learning_surface_guard_maps_denial_to_403(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _deny(_surface: str) -> None:
        raise PermissionError("denied by policy")

    monkeypatch.setattr("deeptutor.multi_user.learning_access.assert_learning_surface", _deny)
    response = client.get(f"{PREFIX}/settings")
    assert response.status_code == 403
    assert "denied by policy" in response.json()["detail"]
