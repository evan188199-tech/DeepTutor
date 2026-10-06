"""Contract tests for the agent-config router.

The single-agent lookup used to answer unknown agent types with HTTP 200 and a
plain ``{"error": ...}`` body, so clients could not distinguish a refusal from
a real config. These tests pin the corrected contract: success payloads are
unchanged, refusals carry a 4xx status and the structured
``{"detail": {"code", "message"}}`` envelope used across the API.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import agent_config


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(agent_config.router, prefix="/api/agent-config")
    return TestClient(app)


def test_list_returns_full_registry(client: TestClient) -> None:
    response = client.get("/api/agent-config/agents")

    assert response.status_code == 200
    assert response.json() == agent_config.AGENT_REGISTRY


def test_known_agent_returns_metadata(client: TestClient) -> None:
    response = client.get("/api/agent-config/agents/solve")

    assert response.status_code == 200
    assert response.json() == {
        "icon": "HelpCircle",
        "color": "blue",
        "label_key": "Problem Solved",
    }


@pytest.mark.parametrize("agent_type", ["unknown", "solve2", "not an agent"])
def test_unknown_agent_is_refused_with_envelope(client: TestClient, agent_type: str) -> None:
    response = client.get(f"/api/agent-config/agents/{agent_type}")

    assert not response.is_success
    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"detail"}
    detail = body["detail"]
    assert detail["code"] == "agent_not_found"
    assert "message" in detail
    assert "error" not in body
    assert agent_type in detail["message"]
