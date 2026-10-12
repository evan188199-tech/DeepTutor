"""API tests for the in-app EduHub skill browser endpoints.

``GET /api/skills/hub/catalog`` and ``/hub/detail`` proxy a hub's public
catalog so the web panel can render it in DeepTutor's own UI (no iframe, no
login). The hub provider is mocked over an ``httpx`` transport.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import httpx
import pytest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover - optional dependency in lightweight envs
    FastAPI = None
    TestClient = None

pytestmark = pytest.mark.skipif(
    FastAPI is None or TestClient is None, reason="fastapi not installed"
)

from deeptutor.services.skill import hub as hub_module
from deeptutor.services.skill.hub import ClawHubProvider


def _mock_provider() -> ClawHubProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/skills":
            return httpx.Response(
                200,
                json={
                    "skills": [
                        {
                            "slug": "socratic-tutor",
                            "displayName": "Socratic Tutor",
                            "summary": "Teach by asking.",
                            "version": "1.0.0",
                            "stats": {"downloads": 8, "stars": 2},
                            "owner": {
                                "displayName": "DeepTutor",
                                "htmlUrl": "https://deeptutor.info",
                            },
                        }
                    ]
                },
            )
        if path == "/api/v1/skills/socratic-tutor":
            return httpx.Response(
                200,
                json={
                    "skill": {
                        "slug": "socratic-tutor",
                        "displayName": "Socratic Tutor",
                        "summary": "Teach.",
                        "description": "---\nname: socratic-tutor\n---\n\n# Body\n",
                        "tags": ["tutor"],
                        "stats": {"downloads": 8, "stars": 2},
                    },
                    "owner": {"displayName": "DeepTutor", "htmlUrl": "https://deeptutor.info"},
                    "distTags": {"latest": "1.0.0"},
                },
            )
        return httpx.Response(404, text="nope")

    return ClawHubProvider(
        "eduhub",
        base_url="https://eduhub.deeptutor.info/api/v1",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def _build_app() -> FastAPI:
    router = importlib.import_module("deeptutor.api.routers.skills").router
    app = FastAPI()
    app.include_router(router, prefix="/api/skills")
    return app


def test_hub_catalog_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hub_module, "get_hub_provider", lambda name: _mock_provider())
    client = TestClient(_build_app())
    resp = client.get("/api/skills/hub/catalog")
    assert resp.status_code == 200
    data = resp.json()
    assert data["hub"] == "eduhub"
    assert data["web_url"] == "https://eduhub.deeptutor.info"
    row = data["skills"][0]
    assert row["slug"] == "socratic-tutor"
    assert row["downloads"] == 8 and row["stars"] == 2
    assert row["owner"] == "DeepTutor"


def test_hub_detail_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hub_module, "get_hub_provider", lambda name: _mock_provider())
    client = TestClient(_build_app())
    resp = client.get("/api/skills/hub/detail", params={"slug": "socratic-tutor"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["version"] == "1.0.0"
    assert "# Body" in data["content"]
    assert data["web_url"] == "https://eduhub.deeptutor.info/skills/socratic-tutor"


class _BrokenHubProvider(ClawHubProvider):
    def catalog(self, *, query: str = "", limit: int = 50, sort: str = "createdAt") -> list[dict]:
        raise hub_module.HubError("catalog unavailable")

    def detail(self, slug: str) -> dict:
        raise hub_module.HubError("detail unavailable")


def test_hub_catalog_unknown_hub_returns_400() -> None:
    client = TestClient(_build_app())
    resp = client.get("/api/skills/hub/catalog", params={"hub": "no-such-hub"})
    assert resp.status_code == 400


def test_hub_non_browsing_provider_returns_400(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hub_module, "get_hub_provider", lambda name: SimpleNamespace(name="cmdhub"))
    client = TestClient(_build_app())
    assert client.get("/api/skills/hub/catalog").status_code == 400
    assert (
        client.get("/api/skills/hub/detail", params={"slug": "socratic-tutor"}).status_code == 400
    )


def test_hub_provider_failure_returns_502(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        hub_module,
        "get_hub_provider",
        lambda name: _BrokenHubProvider("eduhub", base_url="https://eduhub.example"),
    )
    client = TestClient(_build_app())
    assert client.get("/api/skills/hub/catalog").status_code == 502
    assert (
        client.get("/api/skills/hub/detail", params={"slug": "socratic-tutor"}).status_code == 502
    )


def test_hub_detail_missing_slug_returns_502(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hub_module, "get_hub_provider", lambda name: _mock_provider())
    client = TestClient(_build_app())
    assert client.get("/api/skills/hub/detail", params={"slug": "ghost"}).status_code == 502
