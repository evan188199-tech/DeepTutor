"""HTTP-level verification for #1228: learner access to /api/courses.

Covers both sides of the fix merged in #1231:

1. A default ``learner`` account (policy surfaces ``["chat", "reading"]``)
   passes the surface guard on the real courses router and sees the courses
   it owns.
2. A guardian-restricted learner whose ``reading`` surface is revoked gets
   the server's 403 denial, and the course service is never consulted — the
   frontend receives a real error it can render instead of an empty list
   that would masquerade as the zero-courses state.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import auth
from deeptutor.api.routers import courses as courses_router
from deeptutor.multi_user import learning_access
from deeptutor.multi_user.identity import save_user
from deeptutor.services.auth import TokenPayload, hash_password
from deeptutor.services.courses import CourseService


def _learner_courses_app() -> FastAPI:
    """Mount the real courses router behind the real surface guard,
    mirroring ``app.include_router(courses.router, prefix="/api/courses",
    dependencies=_auth)`` in ``deeptutor/api/main.py``."""
    app = FastAPI()
    app.include_router(
        courses_router.router,
        prefix="/api/courses",
        dependencies=[Depends(auth.require_learning_surface)],
    )
    return app


def _login_as_learner(monkeypatch: pytest.MonkeyPatch, user: dict) -> None:
    token = TokenPayload(username="student", role="user", user_id=user["id"])
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth, "decode_token", lambda _token: token)


def test_default_learner_lists_own_courses_over_http(
    monkeypatch: pytest.MonkeyPatch, mu_isolated_root, tmp_path
) -> None:
    save_user("admin", hash_password("admin-password"), role="admin")
    learner = save_user("student", hash_password("student-password"), preset="learner")

    service = CourseService(tmp_path / "courses")
    created = service.create(name="Operating Systems")
    monkeypatch.setattr(courses_router, "get_course_service", lambda: service)

    _login_as_learner(monkeypatch, learner)
    response = TestClient(_learner_courses_app()).get(
        "/api/courses", headers={"Authorization": "Bearer student-token"}
    )

    assert response.status_code == 200, response.text
    courses = response.json()["courses"]
    assert [course["id"] for course in courses] == [created.id]
    assert courses[0]["name"] == "Operating Systems"


def test_learner_without_reading_surface_gets_real_403_over_http(
    monkeypatch: pytest.MonkeyPatch, mu_isolated_root, tmp_path
) -> None:
    save_user("admin", hash_password("admin-password"), role="admin")
    learner = save_user("student", hash_password("student-password"), preset="learner")

    service = CourseService(tmp_path / "courses")
    service.create(name="Operating Systems")
    calls: list[bool] = []
    monkeypatch.setattr(
        courses_router, "get_course_service", lambda: (calls.append(True), service)[1]
    )
    monkeypatch.setattr(
        learning_access,
        "learning_policy_for_user",
        lambda _user_id, **_kwargs: {"allowed_surfaces": ["chat"]},
    )

    _login_as_learner(monkeypatch, learner)
    response = TestClient(_learner_courses_app()).get(
        "/api/courses", headers={"Authorization": "Bearer student-token"}
    )

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == ("This learning account cannot use the reading surface.")
    assert calls == []
