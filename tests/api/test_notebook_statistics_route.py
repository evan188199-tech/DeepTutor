"""HTTP contract tests for the notebook statistics route.

Covers ``GET /api/notebooks/statistics``: the success payload passthrough,
the 409 "notebook unreadable" envelope raised for a damaged notebook file,
the generic 500 fallback, and the auth gate that ``main.py`` applies to the
notebook router.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from deeptutor.api.routers import auth as auth_router
from deeptutor.api.routers import notebook as notebook_router
from deeptutor.services.auth import TokenPayload
from deeptutor.services.notebook.service import NotebookCorruptedError


class _FakeManager:
    def __init__(self, stats: dict[str, Any] | None = None, error: Exception | None = None):
        self.stats = stats or {}
        self.error = error
        self.calls = 0

    def get_statistics(self) -> dict[str, Any]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.stats


def _make_client(manager: _FakeManager, *, auth_guard: bool = False) -> TestClient:
    app = FastAPI()
    dependencies = [Depends(auth_router.require_learning_surface)] if auth_guard else None
    app.include_router(notebook_router.router, prefix="/api", dependencies=dependencies)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def manager(monkeypatch: pytest.MonkeyPatch) -> _FakeManager:
    fake = _FakeManager()
    monkeypatch.setattr(notebook_router, "notebook_manager", fake)
    return fake


_STATS = {
    "total_notebooks": 2,
    "total_entries": 17,
    "entries_by_course": {"course-a": 17},
    "review_due": 3,
}


def test_statistics_returns_manager_payload(
    manager: _FakeManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager.stats = _STATS
    client = _make_client(manager)

    res = client.get("/api/notebooks/statistics")

    assert res.status_code == 200
    assert res.json() == _STATS
    assert manager.calls == 1


def test_statistics_maps_corrupted_notebook_to_409_envelope(
    manager: _FakeManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager.error = NotebookCorruptedError(
        "nb-1", Path("/data/notebooks/nb-1.json"), ValueError("Expecting value")
    )
    client = _make_client(manager)

    res = client.get("/api/notebooks/statistics")

    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["code"] == "notebook_unreadable"
    assert detail["notebook_id"] == "nb-1"
    assert "nb-1.json" in detail["message"]


def test_statistics_maps_unexpected_failure_to_500(
    manager: _FakeManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager.error = RuntimeError("disk on fire")
    client = _make_client(manager)

    res = client.get("/api/notebooks/statistics")

    assert res.status_code == 500
    assert res.json()["detail"] == "disk on fire"


def test_auth_gate_blocks_anonymous_and_accepts_valid_token(
    manager: _FakeManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager.stats = _STATS
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    tokens: dict[str, TokenPayload | None] = {
        "tok-ok": TokenPayload(username="alice", role="admin", user_id="u-1")
    }
    monkeypatch.setattr(auth_router, "decode_token", lambda token: tokens.get(token))
    client = _make_client(manager, auth_guard=True)

    anonymous = client.get("/api/notebooks/statistics")
    assert anonymous.status_code == 401

    rejected = client.get(
        "/api/notebooks/statistics", headers={"Authorization": "Bearer tok-bad"}
    )
    assert rejected.status_code == 401

    ok = client.get("/api/notebooks/statistics", headers={"Authorization": "Bearer tok-ok"})
    assert ok.status_code == 200
    assert ok.json() == _STATS
