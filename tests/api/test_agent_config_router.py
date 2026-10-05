"""Contract tests for the agent-config UI metadata surface.

``/api/agent-config`` is the data-driven registry the frontend renders agent
chips from. It ships as a plain router whose auth gate is attached by
``main.py``; these tests mount it the same way and pin the response shapes,
the documented unknown-agent behaviour, and the gate's 401/403 mapping.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import agent_config
from deeptutor.api.routers.auth import require_auth, require_learning_surface

PREFIX = "/api/agent-config"


@pytest.fixture
def app() -> FastAPI:
    """The router mounted exactly as ``main.py`` mounts it, auth satisfied."""
    fast_app = FastAPI()
    fast_app.include_router(
        agent_config.router, prefix=PREFIX, dependencies=[Depends(require_learning_surface)]
    )
    fast_app.dependency_overrides[require_auth] = lambda: None
    return fast_app


def test_agents_lists_the_full_registry(app: FastAPI) -> None:
    body = TestClient(app).get(f"{PREFIX}/agents").json()
    assert set(body) == {"solve", "question", "research", "co_writer"}
    for meta in body.values():
        assert set(meta) == {"icon", "color", "label_key"}
        assert meta["icon"]
        assert meta["label_key"]


def test_single_agent_returns_ui_metadata(app: FastAPI) -> None:
    response = TestClient(app).get(f"{PREFIX}/agents/solve")
    assert response.status_code == 200
    assert response.json() == {"icon": "HelpCircle", "color": "blue", "label_key": "Problem Solved"}


def test_unknown_agent_returns_error_body_with_200(app: FastAPI) -> None:
    """Pinned deliberately: unknown types answer 200 + an error dict, not 404."""
    response = TestClient(app).get(f"{PREFIX}/agents/no_such_agent")
    assert response.status_code == 200
    assert response.json() == {"error": "Agent type 'no_such_agent' not found"}


def test_missing_token_is_unauthorized_when_auth_enabled(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("deeptutor.api.routers.auth.AUTH_ENABLED", True)
    app.dependency_overrides.pop(require_auth, None)
    response = TestClient(app).get(f"{PREFIX}/agents")
    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"
    assert response.headers["www-authenticate"] == "Bearer"


def test_malformed_token_is_unauthorized_when_auth_enabled(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("deeptutor.api.routers.auth.AUTH_ENABLED", True)
    app.dependency_overrides.pop(require_auth, None)
    response = TestClient(app).get(
        f"{PREFIX}/agents", headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired token"


def test_learning_surface_guard_maps_denial_to_403(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _deny(_surface: str) -> None:
        raise PermissionError("denied by policy")

    monkeypatch.setattr("deeptutor.multi_user.learning_access.assert_learning_surface", _deny)
    response = TestClient(app).get(f"{PREFIX}/agents")
    assert response.status_code == 403
    assert "denied by policy" in response.json()["detail"]
