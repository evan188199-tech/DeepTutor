"""Route-surface matrix for the learning-account second-stage guard.

``require_learning_surface`` is the default-deny dependency ``main.py``
mounts in front of every HTTP router. These tests mount sampled real
routers the same way production does and pin the deny/allow outcome for
learner-preset accounts across the mapped surface families — reading,
books, chat (including the knowledge-base read template and the settings
self-service writes) — plus the unmapped admin surfaces that must stay
denied.

WebSocket routes (``tests/api/test_websocket_routing.py``) and the
video-learning router (``tests/video_learning/test_router.py``) carry
their own guard tests and are out of scope here. The per-path surface
mapping itself is pinned by ``tests/multi_user/test_learning_surface_map.py``
and ``tests/api/test_knowledge_router.py``; this file is about what the
mounted guard does for a learning account behind real routers.
"""

from __future__ import annotations

from copy import deepcopy

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.multi_user.book_permission import BookPermission
from deeptutor.multi_user.grants import learner_grant, save_grant
from deeptutor.multi_user.identity import save_user, set_book_permission
from deeptutor.services.auth import TokenPayload


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def matrix_env(tmp_path, monkeypatch):
    """Sampled routers behind the production learning-surface dependency.

    Isolates every persisted root under ``tmp_path`` the same way
    ``tests/api/test_book_shared_access.py`` does, then mounts real routers
    with ``Depends(require_learning_surface)`` — the dependency stack
    ``main.py`` puts in front of these prefixes.
    """
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.api.routers import book as book_router
    from deeptutor.api.routers import knowledge as knowledge_router
    from deeptutor.api.routers import memory as memory_router
    from deeptutor.api.routers import personas as personas_router
    from deeptutor.api.routers import reading as reading_router
    from deeptutor.api.routers import settings as settings_router
    from deeptutor.api.routers import system as system_router
    from deeptutor.api.routers import task_board as task_board_router
    from deeptutor.book import engine as book_engine
    from deeptutor.book import storage as book_storage
    from deeptutor.multi_user import audit, grants, identity, paths
    from deeptutor.services import auth as auth_service

    admin_root = (tmp_path / "data").resolve()
    system_root = admin_root / "system"

    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(paths, "USERS_ROOT", admin_root / "users")
    monkeypatch.setattr(paths, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(paths, "LEGACY_MULTI_USER_ROOT", tmp_path / "multi-user")
    monkeypatch.setattr(paths, "_path_services", {})
    monkeypatch.setattr(identity, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(identity, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(identity, "AUTH_DIR", system_root / "auth")
    monkeypatch.setattr(identity, "USERS_FILE", system_root / "auth" / "users.json")
    monkeypatch.setattr(identity, "SECRET_FILE", system_root / "auth" / "auth_secret")
    monkeypatch.setattr(identity, "LEGACY_USERS_FILE", tmp_path / "missing-users.json")
    monkeypatch.setattr(identity, "LEGACY_SECRET_FILE", tmp_path / "missing-secret")
    monkeypatch.setattr(grants, "GRANTS_DIR", system_root / "grants")
    monkeypatch.setattr(audit, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_service, "AUTH_USERNAME", "")
    monkeypatch.setattr(auth_service, "AUTH_PASSWORD_HASH", "")
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "POCKETBASE_ENABLED", False)
    book_storage._storages.clear()
    book_engine._engines.clear()

    admin = save_user("admin", "hash", role="admin")
    learner = save_user("student", "hash", role="user", preset="learner")
    book_learner = save_user("book-student", "hash", role="user", preset="learner")
    set_book_permission("book-student", BookPermission(create=False))
    grant = deepcopy(learner_grant(book_learner["id"]))
    grant["learning_policy"]["allowed_surfaces"] = ["chat", "reading", "books"]
    save_grant(book_learner["id"], grant)

    tokens = {
        "token-admin": TokenPayload(username="admin", role="admin", user_id=admin["id"]),
        "token-learner": TokenPayload(username="student", role="user", user_id=learner["id"]),
        "token-book-learner": TokenPayload(
            username="book-student", role="user", user_id=book_learner["id"]
        ),
    }
    monkeypatch.setattr(auth_router, "decode_token", lambda token: tokens.get(token))

    app = FastAPI()
    guard = [Depends(auth_router.require_learning_surface)]
    app.include_router(task_board_router.router, prefix="/api/task-board", dependencies=guard)
    app.include_router(settings_router.router, prefix="/api/settings", dependencies=guard)
    app.include_router(reading_router.router, prefix="/api/reading", dependencies=guard)
    app.include_router(knowledge_router.router, prefix="/api", dependencies=guard)
    app.include_router(book_router.router, prefix="/api", dependencies=guard)
    app.include_router(personas_router.router, prefix="/api", dependencies=guard)
    app.include_router(system_router.router, prefix="/api/system", dependencies=guard)
    app.include_router(memory_router.router, prefix="/api/memory", dependencies=guard)
    return TestClient(app)


@pytest.mark.parametrize(
    ("method", "url", "token", "surface", "payload"),
    [
        # chat: the account task board.
        ("GET", "/api/task-board", "token-learner", "chat", None),
        # chat: model choice for a chat turn (exact settings path).
        ("GET", "/api/settings/llm-options", "token-learner", "chat", None),
        # chat: the per-user UI settings draft write.
        ("PUT", "/api/settings/ui", "token-learner", "chat", {"theme": "dark"}),
        # reading: the account material library.
        ("GET", "/api/reading/library/materials", "token-learner", "reading", None),
        # reading via the resolved KB route template: browsing stays open.
        ("GET", "/api/knowledge-bases/list", "token-learner", "reading", None),
        # books: only with the surface explicitly granted.
        ("GET", "/api/books", "token-book-learner", "books", None),
    ],
)
def test_learner_allowed_surfaces_pass_the_guard(
    matrix_env: TestClient,
    method: str,
    url: str,
    token: str,
    surface: str,
    payload: dict[str, str] | None,
) -> None:
    response = matrix_env.request(method, url, headers=_headers(token), json=payload)
    assert response.status_code == 200, response.text


@pytest.mark.parametrize(
    ("method", "url", "surface_gap"),
    [
        # books is a grantable surface the default learner policy omits.
        ("GET", "/api/books", "books surface not granted"),
        # KB writes and diagnostics share the browsing prefix but stay denied.
        ("GET", "/api/knowledge-bases/health", "KB diagnostics"),
        ("POST", "/api/knowledge-bases", "KB write"),
        # Settings reads and admin-grade writes stay denied; only the
        # exact self-service routes above pass.
        ("GET", "/api/settings", "settings view"),
        ("POST", "/api/settings/apply/registry", "catalog apply"),
        # Routers outside every mapped surface default-deny.
        ("GET", "/api/personas", "personas"),
        ("GET", "/api/system/status", "system"),
        ("GET", "/api/memory/overview", "memory"),
    ],
)
def test_learner_denied_surfaces_get_403(
    matrix_env: TestClient, method: str, url: str, surface_gap: str
) -> None:
    response = matrix_env.request(method, url, headers=_headers("token-learner"))
    assert response.status_code == 403, response.text


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("GET", "/api/task-board"),
        ("GET", "/api/personas"),
    ],
)
def test_accounts_without_learning_policy_are_not_blocked(
    matrix_env: TestClient, method: str, url: str
) -> None:
    """The guard only fires for accounts carrying a learning policy."""
    response = matrix_env.request(method, url, headers=_headers("token-admin"))
    assert response.status_code == 200, response.text


def test_guard_chain_requires_authentication_first(matrix_env: TestClient) -> None:
    assert matrix_env.get("/api/task-board").status_code == 401
    assert matrix_env.get("/api/knowledge-bases/health").status_code == 401
