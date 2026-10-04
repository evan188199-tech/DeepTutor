"""Multi-user permission matrix for the courses, chat and knowledge surfaces.

One assertion per matrix cell. The matrix crosses three account kinds
(learner — a ``learner``-preset account governed by a learning policy,
teacher — an ordinary non-admin staff account, admin — the deployment
administrator) with the read/write boundary of the three main resource
domains, and asserts for every cell whether the API answers 200, 401, 403
or 404.

Semantics under test (expected behaviour, one cell each):

* Unauthenticated requests are rejected with 401 on every domain.
* Resource isolation answers 404, not 403: a resource living in another
  account's workspace is indistinguishable from a missing one.
* Learning accounts get read/write access to their own courses and chat
  data, read-only access to knowledge bases, and no access to deployment
  engine configuration or account management (403).
* Non-admin accounts cannot read or write account management (403) and
  cannot change deployment-wide knowledge-engine configuration (403).
* Admin owns a separate workspace: user-scoped resources answer 404 to
  the admin as well, and admin management reads answer 200.

The routers are mounted exactly as ``api/main.py`` mounts them (through
``require_learning_surface``, whose ``require_auth`` dependency performs
the 401s and installs the request workspace), so a gate removed from a
router or from main.py's wiring fails here even though endpoint tests
still pass. No product code is modified by this module.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

FastAPI = pytest.importorskip("fastapi").FastAPI
Depends = pytest.importorskip("fastapi").Depends
TestClient = pytest.importorskip("fastapi.testclient").TestClient

TEST_PASSWORD = "matrix-password-123"
_LEARNER = "learner"
_TEACHER = "teacher"
_ADMIN = "admin"
_ANON = "anon"

# ---------------------------------------------------------------------------
# Hermetic import of the knowledge router
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _hermetic_knowledge_router(tmp_path_factory) -> None:
    """Import the knowledge router against a throwaway settings root.

    ``deeptutor.api.routers.knowledge`` loads ``main.yaml`` from
    ``PROJECT_ROOT / data/user/settings`` at import time. Pointing the config
    package at a temporary root before the first import keeps this module
    independent of whatever runtime state the surrounding checkout has.

    Scoped to this module and requested only by ``matrix_env``: the patch
    covers exactly the import below and is undone immediately afterwards, so
    no other module's view of ``PROJECT_ROOT`` is affected, whatever the
    collection order. If the router was already imported earlier in the
    session, the import is a cache hit and the patch is a harmless no-op.
    """
    config_module = importlib.import_module("deeptutor.services.config")
    root = tmp_path_factory.mktemp("perm-matrix-settings")
    settings_dir = root / "data" / "user" / "settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "main.yaml").write_text("{}\n", encoding="utf-8")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(config_module, "PROJECT_ROOT", root)
    importlib.import_module("deeptutor.api.routers.knowledge")
    monkeypatch.undo()


_routers: SimpleNamespace | None = None


def _load_routers() -> SimpleNamespace:
    global _routers
    if _routers is None:
        _routers = SimpleNamespace(
            auth=importlib.import_module("deeptutor.api.routers.auth"),
            courses=importlib.import_module("deeptutor.api.routers.courses"),
            knowledge=importlib.import_module("deeptutor.api.routers.knowledge"),
            multi_user=importlib.import_module("deeptutor.api.routers.multi_user"),
            sessions=importlib.import_module("deeptutor.api.routers.sessions"),
            auth_service=importlib.import_module("deeptutor.services.auth"),
        )
    return _routers


# ---------------------------------------------------------------------------
# Environment fixture
# ---------------------------------------------------------------------------


@dataclass
class MatrixEnv:
    identity: str
    headers: dict[str, str] = field(default_factory=dict)
    client: TestClient | None = None
    learner_course_id: str = ""
    learner_session_id: str = ""
    learner_kb: str = "learner-kb"
    teacher_kb: str = "teacher-kb"
    learner_user_id: str = ""
    teacher_user_id: str = ""
    admin_user_id: str = ""

    def request(self, method: str, url: str, **kwargs):
        return self.client.request(method, url, headers=self.headers, **kwargs)


@pytest.fixture
def matrix_env(tmp_path, monkeypatch, _hermetic_knowledge_router) -> MatrixEnv:
    """One isolated deployment per cell: users, scopes and routers under tmp."""
    mods = _load_routers()
    auth_module = mods.auth
    auth_service = mods.auth_service
    paths = importlib.import_module("deeptutor.multi_user.paths")
    identity = importlib.import_module("deeptutor.multi_user.identity")
    grants = importlib.import_module("deeptutor.multi_user.grants")

    admin_root = (tmp_path / "data").resolve()
    users_root = admin_root / "users"
    system_root = admin_root / "system"

    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(paths, "USERS_ROOT", users_root)
    monkeypatch.setattr(paths, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(paths, "LEGACY_MULTI_USER_ROOT", tmp_path / "multi-user")
    monkeypatch.setattr(paths, "_path_services", {})

    monkeypatch.setattr(identity, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(identity, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(identity, "AUTH_DIR", system_root / "auth")
    monkeypatch.setattr(identity, "USERS_FILE", system_root / "auth" / "users.json")
    monkeypatch.setattr(identity, "SECRET_FILE", system_root / "auth" / "auth_secret")
    monkeypatch.setattr(
        identity, "LEGACY_USERS_FILE", tmp_path / "data" / "user" / "auth_users.json"
    )
    monkeypatch.setattr(identity, "LEGACY_SECRET_FILE", tmp_path / "data" / "user" / "auth_secret")
    monkeypatch.setattr(grants, "GRANTS_DIR", system_root / "grants")

    monkeypatch.setattr(auth_service, "AUTH_USERNAME", "")
    monkeypatch.setattr(auth_service, "AUTH_PASSWORD_HASH", "")
    monkeypatch.setattr(auth_service, "POCKETBASE_ENABLED", False)
    monkeypatch.setattr(auth_service, "AUTH_SECRET", "permission-matrix-secret")
    monkeypatch.setattr(auth_module, "AUTH_ENABLED", True)

    # The workspace activity lease persists request bookkeeping on disk; the
    # matrix never asserts on it, so it is replaced with an inert stand-in.
    workspace_activity = importlib.import_module("deeptutor.services.workspace.activity")
    monkeypatch.setattr(workspace_activity, "acquire_activity", lambda **_kwargs: None)

    admin = identity.save_user("admin-user", _hashed_password(), "admin")
    teacher = identity.save_user("teacher-user", _hashed_password(), "teacher")
    learner = identity.save_user(
        "learner-user",
        _hashed_password(),
        "student",
        "learner",  # type: ignore[arg-type]
    )

    def _token(username: str, role: str, user_id: str) -> str:
        return auth_service.create_token(username, role=role, user_id=user_id)

    app = FastAPI()
    surface_guard = [Depends(auth_module.require_learning_surface)]
    app.include_router(mods.courses.router, prefix="/api/courses", dependencies=surface_guard)
    app.include_router(mods.sessions.router, prefix="/api/sessions", dependencies=surface_guard)
    app.include_router(mods.knowledge.router, prefix="/api", dependencies=surface_guard)
    app.include_router(mods.multi_user.router, prefix="/api/multi-user", dependencies=surface_guard)

    client = TestClient(app, raise_server_exceptions=False)

    env = MatrixEnv(identity=_ANON, client=client)
    env.learner_user_id = str(learner["id"])
    env.teacher_user_id = str(teacher["id"])
    env.admin_user_id = str(admin["id"])
    env.learner_course_id = _seed_learner_state(mods, client, learner, env)

    return env


_HASHED_PASSWORD: str | None = None


def _hashed_password() -> str:
    global _HASHED_PASSWORD
    if _HASHED_PASSWORD is None:
        _HASHED_PASSWORD = _load_routers().auth_service.hash_password(TEST_PASSWORD)
    return _HASHED_PASSWORD


def _seed_learner_state(mods, client: TestClient, learner: dict, env: MatrixEnv) -> str:
    """Create the learner-owned course, session and knowledge base once per cell.

    Everything is created through an authenticated scope so the
    foreign-access cells below exercise real cross-workspace isolation.
    """
    auth_service = mods.auth_service
    learner_headers = {
        "Authorization": "Bearer "
        + auth_service.create_token("learner-user", role="student", user_id=str(learner["id"]))
    }
    response = client.request(
        "POST", "/api/courses", headers=learner_headers, json={"name": "Learner Course"}
    )
    assert response.status_code == 200, response.text
    course_id = str(response.json()["course"]["id"])

    response = client.request(
        "POST",
        "/api/knowledge-bases",
        headers=learner_headers,
        data={"name": env.learner_kb},
        files={},
    )
    assert response.status_code == 403, (
        "precondition: learning accounts cannot manage knowledge bases"
    )

    session_store_module = importlib.import_module("deeptutor.services.session.sqlite_store")
    context_module = importlib.import_module("deeptutor.multi_user.context")
    models_module = importlib.import_module("deeptutor.multi_user.models")
    paths = importlib.import_module("deeptutor.multi_user.paths")

    learner_user = models_module.CurrentUser(
        id=str(learner["id"]),
        username="learner-user",
        role="student",
        scope=paths.scope_for_user(learner["id"], is_admin=False),
    )
    token = context_module.set_current_user(learner_user)
    try:
        store = session_store_module.SQLiteSessionStore()
        asyncio.run(store.create_session(title="Learner chat", session_id="sess-matrix-learner"))
    finally:
        context_module.reset_current_user(token)
    env.learner_session_id = "sess-matrix-learner"

    response = client.request(
        "POST",
        "/api/knowledge-bases",
        headers={
            "Authorization": "Bearer "
            + auth_service.create_token("teacher-user", role="teacher", user_id=env.teacher_user_id)
        },
        data={"name": env.teacher_kb},
        files={},
    )
    assert response.status_code == 200, response.text
    return course_id


# ---------------------------------------------------------------------------
# Matrix cells — one assertion per cell
# ---------------------------------------------------------------------------


def _learner_env(request) -> MatrixEnv:
    env: MatrixEnv = request.getfixturevalue("matrix_env")
    auth_service = _load_routers().auth_service
    env.headers = {
        "Authorization": "Bearer "
        + auth_service.create_token("learner-user", role="student", user_id=env.learner_user_id)
    }
    return env


@pytest.fixture
def learner_env(request) -> MatrixEnv:
    return _learner_env(request)


@pytest.fixture
def teacher_env(request) -> MatrixEnv:
    env: MatrixEnv = request.getfixturevalue("matrix_env")
    auth_service = _load_routers().auth_service
    env.headers = {
        "Authorization": "Bearer "
        + auth_service.create_token("teacher-user", role="teacher", user_id=env.teacher_user_id)
    }
    return env


@pytest.fixture
def admin_env(request) -> MatrixEnv:
    env: MatrixEnv = request.getfixturevalue("matrix_env")
    auth_service = _load_routers().auth_service
    env.headers = {
        "Authorization": "Bearer "
        + auth_service.create_token("admin-user", role="admin", user_id=env.admin_user_id)
    }
    return env


# --- Unauthenticated access is rejected on every domain ---------------------


def test_anon_courses_read(matrix_env) -> None:
    assert matrix_env.request("GET", "/api/courses").status_code == 401


def test_anon_courses_write(matrix_env) -> None:
    assert matrix_env.request("POST", "/api/courses", json={"name": "x"}).status_code == 401


def test_anon_chat_read(matrix_env) -> None:
    assert matrix_env.request("GET", "/api/sessions").status_code == 401


def test_anon_chat_write(matrix_env) -> None:
    assert matrix_env.request("DELETE", "/api/sessions/sess-matrix-learner").status_code == 401


def test_anon_kb_read(matrix_env) -> None:
    assert matrix_env.request("GET", "/api/knowledge-bases").status_code == 401


def test_anon_kb_write(matrix_env) -> None:
    assert (
        matrix_env.request(
            "POST", "/api/knowledge-bases", data={"name": "anon-kb"}, files={}
        ).status_code
        == 401
    )


def test_anon_kb_item_read(matrix_env) -> None:
    response = matrix_env.request("GET", f"/api/knowledge-bases/{matrix_env.learner_kb}")
    assert response.status_code == 401


def test_anon_admin_users(matrix_env) -> None:
    assert matrix_env.request("GET", "/api/multi-user/users").status_code == 401


def test_invalid_token_courses_read(matrix_env) -> None:
    matrix_env.headers = {"Authorization": "Bearer not-a-jwt"}
    assert matrix_env.request("GET", "/api/courses").status_code == 401


# --- Learner: own courses and chat, read-only knowledge ---------------------


def test_learner_courses_read(learner_env) -> None:
    assert learner_env.request("GET", "/api/courses").status_code == 200


def test_learner_courses_create_own(learner_env) -> None:
    response = learner_env.request("POST", "/api/courses", json={"name": "Second Course"})
    assert response.status_code == 200


def test_learner_courses_state_own(learner_env) -> None:
    response = learner_env.request("GET", f"/api/courses/{learner_env.learner_course_id}/state")
    assert response.status_code == 200


def test_learner_courses_delete_own(learner_env) -> None:
    response = learner_env.request("DELETE", f"/api/courses/{learner_env.learner_course_id}")
    assert response.status_code == 200


def test_learner_chat_read(learner_env) -> None:
    assert learner_env.request("GET", "/api/sessions").status_code == 200


def test_learner_chat_write_own(learner_env) -> None:
    response = learner_env.request(
        "PATCH", f"/api/sessions/{learner_env.learner_session_id}", json={"title": "renamed"}
    )
    assert response.status_code == 200


def test_learner_chat_write_missing(learner_env) -> None:
    response = learner_env.request("PATCH", "/api/sessions/sess-missing", json={"title": "x"})
    assert response.status_code == 404


def test_learner_kb_read(learner_env) -> None:
    assert learner_env.request("GET", "/api/knowledge-bases").status_code == 200


def test_learner_kb_read_missing(learner_env) -> None:
    response = learner_env.request("GET", "/api/knowledge-bases/kb-missing")
    assert response.status_code == 404


def test_learner_kb_create(learner_env) -> None:
    response = learner_env.request(
        "POST", "/api/knowledge-bases", data={"name": "learner-new-kb"}, files={}
    )
    assert response.status_code == 403


def test_learner_kb_upload(learner_env) -> None:
    response = learner_env.request("POST", f"/api/knowledge-bases/{learner_env.learner_kb}/upload")
    assert response.status_code == 403


def test_learner_kb_delete(learner_env) -> None:
    response = learner_env.request("DELETE", f"/api/knowledge-bases/{learner_env.learner_kb}")
    assert response.status_code == 403


def test_learner_engine_config_read(learner_env) -> None:
    assert learner_env.request("GET", "/api/knowledge-bases/rag-providers").status_code == 403


def test_learner_admin_users(learner_env) -> None:
    assert learner_env.request("GET", "/api/multi-user/users").status_code == 403


# --- Teacher: ordinary account, own resources only --------------------------


def test_teacher_courses_read(teacher_env) -> None:
    assert teacher_env.request("GET", "/api/courses").status_code == 200


def test_teacher_courses_create_own(teacher_env) -> None:
    response = teacher_env.request("POST", "/api/courses", json={"name": "Teacher Course"})
    assert response.status_code == 200


def test_teacher_courses_write_foreign(teacher_env) -> None:
    response = teacher_env.request(
        "PATCH", f"/api/courses/{teacher_env.learner_course_id}", json={"description": "d"}
    )
    assert response.status_code == 404


def test_teacher_courses_syllabus_foreign(teacher_env) -> None:
    response = teacher_env.request(
        "PUT",
        f"/api/courses/{teacher_env.learner_course_id}/syllabus",
        json={"units": [{"title": "unit", "topics": []}]},
    )
    assert response.status_code == 404


def test_teacher_courses_delete_foreign(teacher_env) -> None:
    response = teacher_env.request("DELETE", f"/api/courses/{teacher_env.learner_course_id}")
    assert response.status_code == 404


def test_teacher_chat_read(teacher_env) -> None:
    assert teacher_env.request("GET", "/api/sessions").status_code == 200


def test_teacher_chat_write_foreign(teacher_env) -> None:
    response = teacher_env.request(
        "PATCH", f"/api/sessions/{teacher_env.learner_session_id}", json={"title": "x"}
    )
    assert response.status_code == 404


def test_teacher_kb_read(teacher_env) -> None:
    assert teacher_env.request("GET", "/api/knowledge-bases").status_code == 200


def test_teacher_kb_create_own(teacher_env) -> None:
    response = teacher_env.request(
        "POST", "/api/knowledge-bases", data={"name": "teacher-kb-2"}, files={}
    )
    assert response.status_code == 200


def test_teacher_kb_read_own(teacher_env) -> None:
    response = teacher_env.request("GET", f"/api/knowledge-bases/{teacher_env.teacher_kb}")
    assert response.status_code == 200


def test_teacher_kb_read_foreign(teacher_env) -> None:
    response = teacher_env.request("GET", f"/api/knowledge-bases/{teacher_env.learner_kb}")
    assert response.status_code == 404


def test_teacher_kb_delete_own(teacher_env) -> None:
    response = teacher_env.request("DELETE", f"/api/knowledge-bases/{teacher_env.teacher_kb}")
    assert response.status_code == 200


def test_teacher_admin_users_read(teacher_env) -> None:
    assert teacher_env.request("GET", "/api/multi-user/users").status_code == 403


def test_teacher_admin_grant_write(teacher_env) -> None:
    response = teacher_env.request(
        "PUT",
        f"/api/multi-user/users/{teacher_env.learner_user_id}/grants",
        json={"grant": {}},
    )
    assert response.status_code == 403


def test_teacher_engine_config_sync_write(teacher_env) -> None:
    """Knowledge-engine configuration is deployment-wide; only admins change it."""
    response = teacher_env.request("POST", "/api/knowledge-bases/configs/sync")
    assert response.status_code == 403


def test_teacher_engine_config_active_model_write(teacher_env) -> None:
    """Engine model selection is global; non-admins are rejected before validation."""
    response = teacher_env.request(
        "PUT",
        "/api/knowledge-bases/rag-pipelines/active-model",
        json={"kind": "unsupported-kind", "profile_id": "p", "model_id": "m"},
    )
    assert response.status_code == 403


def test_teacher_engine_config_provider_mode_write(teacher_env) -> None:
    """Retrieval-mode defaults are global; non-admins are rejected before engine lookup."""
    response = teacher_env.request(
        "PUT",
        "/api/knowledge-bases/rag-providers/dummy-engine/mode",
        json={"mode": "hybrid"},
    )
    assert response.status_code == 403


# --- Admin: own workspace plus account management ---------------------------


def test_admin_courses_read(admin_env) -> None:
    assert admin_env.request("GET", "/api/courses").status_code == 200


def test_admin_courses_create_own(admin_env) -> None:
    response = admin_env.request("POST", "/api/courses", json={"name": "Admin Course"})
    assert response.status_code == 200


def test_admin_courses_write_user_scope(admin_env) -> None:
    response = admin_env.request(
        "PATCH", f"/api/courses/{admin_env.learner_course_id}", json={"description": "d"}
    )
    assert response.status_code == 404


def test_admin_chat_read(admin_env) -> None:
    assert admin_env.request("GET", "/api/sessions").status_code == 200


def test_admin_kb_read(admin_env) -> None:
    assert admin_env.request("GET", "/api/knowledge-bases").status_code == 200


def test_admin_kb_read_user_scope(admin_env) -> None:
    response = admin_env.request("GET", f"/api/knowledge-bases/{admin_env.learner_kb}")
    assert response.status_code == 404


def test_admin_admin_users_read(admin_env) -> None:
    assert admin_env.request("GET", "/api/multi-user/users").status_code == 200
