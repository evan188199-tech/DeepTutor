"""HTTP contract tests for the system update routes.

Covers ``POST /api/system/update/check``, ``GET /api/system/update/job`` and
``PUT /api/system/update/settings``: the forced-check payload, the disabled
check flag, the 503 branch of a failing forced check, the empty/loaded job
store, settings persistence, request validation bounds, and the admin gate
that protects the write routes while the job view stays authenticated-only.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from deeptutor.api.routers import auth as auth_router
from deeptutor.api.routers import system as system_router
from deeptutor.services.app_update import (
    Installation,
    ReleaseInfo,
    UpdateJobStore,
    VersionCheckError,
    VersionCheckResult,
)
from deeptutor.services.auth import TokenPayload


class _Settings:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.saved: list[dict[str, Any]] = []

    def load_system(self, **_kwargs: object) -> dict[str, Any]:
        return {"version_check_enabled": self.enabled}

    def save_system(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.saved.append(payload)
        self.enabled = bool(payload.get("version_check_enabled"))
        return payload


class _VersionService:
    def __init__(
        self, result: VersionCheckResult | None = None, error: Exception | None = None
    ) -> None:
        self.result = result
        self.error = error
        self.forces: list[bool] = []

    async def check(self, *, force: bool = False) -> VersionCheckResult:
        self.forces.append(force)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result

    def cached(self) -> VersionCheckResult | None:
        return self.result


def _result(*, cached: bool = False) -> VersionCheckResult:
    return VersionCheckResult(
        current_version="1.6.1",
        release=ReleaseInfo(
            version="1.7.0",
            name="DeepTutor 1.7",
            published_at="2026-08-30T00:00:00Z",
            url="https://github.com/HKUDS/DeepTutor/releases/tag/v1.7.0",
            excerpt="A stable release.",
            migration_warning=False,
        ),
        checked_at="2026-08-30T00:00:00+00:00",
        cached=cached,
    )


def _installation() -> Installation:
    return Installation(
        mode="pypi",
        current_version="1.6.1",
        automatic_update=True,
        command="pip install -U deeptutor",
        reason="",
    )


def _make_app() -> TestClient:
    app = FastAPI()
    app.include_router(
        system_router.router,
        prefix="/api/system",
        dependencies=[Depends(auth_router.require_learning_surface)],
    )
    return TestClient(app)


@pytest.fixture
def update_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = UpdateJobStore(tmp_path / "update")
    settings = _Settings(enabled=True)
    service = _VersionService(_result())
    monkeypatch.setattr(system_router, "get_update_job_store", lambda: store)
    monkeypatch.setattr(system_router, "get_update_installation", _installation)
    monkeypatch.setattr(system_router, "launcher_available", lambda: False)
    monkeypatch.setattr(system_router, "get_runtime_settings_service", lambda: settings)
    monkeypatch.setattr(system_router, "get_version_check_service", lambda: service)
    return SimpleNamespace(store=store, settings=settings, service=service)


def test_check_for_update_returns_forced_release_payload(update_env) -> None:
    response = _make_app().post("/api/system/update/check")

    assert response.status_code == 200
    body = response.json()
    assert body["update_available"] is True
    assert body["current_version"] == "1.6.1"
    assert body["check_enabled"] is True
    assert body["checked_at"] == "2026-08-30T00:00:00+00:00"
    assert body["cached"] is False
    assert body["release"]["version"] == "1.7.0"
    assert body["installation"]["mode"] == "pypi"
    assert body["launcher_managed"] is False
    assert body["job"] is None
    assert update_env.service.forces == [True]


def test_check_for_update_skips_probe_when_disabled(update_env) -> None:
    update_env.settings.enabled = False
    update_env.service.result = _result(cached=True)

    response = _make_app().post("/api/system/update/check")

    assert response.status_code == 200
    body = response.json()
    assert body["check_enabled"] is False
    assert body["cached"] is True
    assert update_env.service.forces == []


def test_check_for_update_answers_503_when_forced_check_fails(update_env) -> None:
    update_env.service.error = VersionCheckError("upstream down")

    response = _make_app().post("/api/system/update/check")

    assert response.status_code == 503
    assert response.json()["detail"] == "upstream down"


def test_update_job_reports_empty_then_pending_store(update_env) -> None:
    client = _make_app()

    empty = client.get("/api/system/update/job")
    assert empty.status_code == 200
    assert empty.json() is None

    created = update_env.store.create(current_version="1.6.1", target_version="1.7.0")
    loaded = client.get("/api/system/update/job")

    assert loaded.status_code == 200
    body = loaded.json()
    assert body["id"] == created.id
    assert body["status"] == "pending"
    assert body["current_version"] == "1.6.1"
    assert body["target_version"] == "1.7.0"
    assert body["restart_count"] == 0


def test_update_settings_persists_flag_and_echoes_payload(update_env) -> None:
    client = _make_app()

    disabled = client.put("/api/system/update/settings", json={"enabled": False})
    assert disabled.status_code == 200
    assert disabled.json()["check_enabled"] is False
    assert update_env.settings.saved[-1] == {"version_check_enabled": False}
    assert update_env.service.forces == []

    update_env.settings.enabled = True
    enabled = client.put("/api/system/update/settings", json={"enabled": True})
    assert enabled.status_code == 200
    assert enabled.json()["check_enabled"] is True
    assert update_env.service.forces == [False]


def test_update_settings_rejects_non_boolean_flag(update_env) -> None:
    client = _make_app()

    assert client.put("/api/system/update/settings", json={"enabled": "maybe"}).status_code == 422
    assert client.put("/api/system/update/settings", json={"enabled": []}).status_code == 422
    assert update_env.settings.saved == []


def test_update_write_routes_are_admin_only_but_job_view_is_user_readable(
    update_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    tokens: dict[str, TokenPayload | None] = {
        "tok-admin": TokenPayload(username="root", role="admin", user_id="u-admin"),
        "tok-user": TokenPayload(username="alice", role="user", user_id="u-alice"),
    }
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "decode_token", lambda token: tokens.get(token))
    client = _make_app()

    anonymous_check = client.post("/api/system/update/check")
    assert anonymous_check.status_code == 401

    learner_check = client.post(
        "/api/system/update/check", headers={"Authorization": "Bearer tok-user"}
    )
    assert learner_check.status_code == 403
    assert learner_check.json()["detail"] == "Admin access required"

    admin_check = client.post(
        "/api/system/update/check", headers={"Authorization": "Bearer tok-admin"}
    )
    assert admin_check.status_code == 200

    anonymous_job = client.get("/api/system/update/job")
    assert anonymous_job.status_code == 401

    learner_job = client.get("/api/system/update/job", headers={"Authorization": "Bearer tok-user"})
    assert learner_job.status_code == 200

    anonymous_settings = client.put("/api/system/update/settings", json={"enabled": False})
    assert anonymous_settings.status_code == 401

    learner_settings = client.put(
        "/api/system/update/settings",
        json={"enabled": False},
        headers={"Authorization": "Bearer tok-user"},
    )
    assert learner_settings.status_code == 403
