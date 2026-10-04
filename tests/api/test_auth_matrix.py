"""Auth-dependency matrix for representative api/routers.

``api/routers`` relies on two layers that had no systematic coverage: the
``require_auth`` / ``require_admin`` FastAPI dependencies and the request-local
``current_user`` ContextVar they install for the service layer. This module
samples one representative route from the settings, knowledge, sessions and
partners routers and asserts the allow/deny outcome for four identities:
anonymous, an invalid token, an ordinary user, and an administrator.

The routers are mounted exactly as ``api/main.py`` mounts them (through
``require_learning_surface``, whose ``require_auth`` dependency performs the
401s and installs the ContextVar), so a gate removed from a router or from
main.py's wiring fails here even though every endpoint test still passes.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from deeptutor.multi_user.context import get_current_user

auth_module = importlib.import_module("deeptutor.api.routers.auth")
auth_service = importlib.import_module("deeptutor.services.auth")
settings_module = importlib.import_module("deeptutor.api.routers.settings")
knowledge_module = importlib.import_module("deeptutor.api.routers.knowledge")
sessions_module = importlib.import_module("deeptutor.api.routers.sessions")
partners_module = importlib.import_module("deeptutor.api.routers.partners")

USER_ID = "matrix-user-1"
ADMIN_ID = "matrix-admin-1"


@pytest.fixture(autouse=True)
def _multi_user_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turn auth on and keep ``require_auth``'s workspace bookkeeping hermetic.

    The dependency also installs the request workspace scope and acquires the
    workspace activity lease; both touch on-disk runtime state that this
    matrix has no reason to exercise, so they are replaced with inert
    stand-ins rather than pointed at temporary directories.
    """
    monkeypatch.setattr(auth_module, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_service, "POCKETBASE_ENABLED", False)
    monkeypatch.setattr(auth_service, "AUTH_SECRET", "matrix-test-secret")
    workspace_context = importlib.import_module("deeptutor.services.workspace.context")
    workspace_activity = importlib.import_module("deeptutor.services.workspace.activity")
    monkeypatch.setattr(
        workspace_context,
        "install_workspace_scope",
        lambda _workspace_id=None: SimpleNamespace(archived=False),
    )
    monkeypatch.setattr(workspace_activity, "acquire_activity", lambda **_kwargs: None)


def _token(role: str, user_id: str) -> str:
    return auth_service.create_token(user_id, role=role, user_id=user_id)


@pytest.fixture
def user_token() -> str:
    return _token("user", USER_ID)


@pytest.fixture
def admin_token() -> str:
    return _token("admin", ADMIN_ID)


def _identity_headers(
    which: str, user_token: str, admin_token: str
) -> dict[str, str]:
    if which == "anonymous":
        return {}
    if which == "invalid":
        return {"Authorization": "Bearer not-a-jwt"}
    if which == "user":
        return {"Authorization": f"Bearer {user_token}"}
    if which == "admin":
        return {"Authorization": f"Bearer {admin_token}"}
    raise AssertionError(f"unknown identity {which}")


@pytest.fixture
def user_and_admin_tokens(user_token: str, admin_token: str) -> dict[str, str]:
    return {"user": user_token, "admin": admin_token}


# ---------------------------------------------------------------------------
# Route samples
# ---------------------------------------------------------------------------


class _StubKBManager:
    """Minimal KB manager for the health probe."""

    def __init__(self, root: Path) -> None:
        self.config_file = root / "kb_config.json"
        self.base_dir = root / "knowledge_bases"

    def list_knowledge_bases(self) -> list[str]:
        return []


class _StubSoulManager:
    def list_souls(self) -> list[dict[str, str]]:
        return [{"id": "soul-1", "name": "Soul One"}]

    def get_soul(self, soul_id: str) -> None:
        return None

    def create_soul(self, soul_id: str, name: str, content: str) -> dict[str, str]:
        return {"id": soul_id, "name": name}


class _RecordingSessionStore:
    """Session store that records the ContextVar identity it was called with."""

    def __init__(self) -> None:
        self.seen_user_ids: list[str] = []

    def _record(self) -> None:
        self.seen_user_ids.append(get_current_user().id)

    async def list_sessions(self, **_kwargs) -> list[dict[str, str]]:
        self._record()
        return []

    async def search_sessions(self, _q: str, **_kwargs) -> dict[str, object]:
        self._record()
        return {"sessions": [], "total": 0}


def _mount(*router_prefixes) -> FastAPI:
    """Mount routers with production wiring: the learning-surface gate chain.

    ``api/main.py`` wraps every router in ``[Depends(require_learning_surface)]``;
    that dependency itself depends on ``require_auth``, which answers 401 and
    installs the ``current_user`` ContextVar. Mounting through the same chain
    is what makes the 401 rows below meaningful.
    """
    app = FastAPI()
    for router, prefix in router_prefixes:
        app.include_router(
            router, prefix=prefix, dependencies=[Depends(auth_module.require_learning_surface)]
        )
    return app


@pytest.fixture
def settings_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(
        settings_module,
        "get_model_catalog_service",
        lambda: SimpleNamespace(load=lambda: {"version": 1, "services": {}}),
    )
    monkeypatch.setattr(
        settings_module,
        "list_llm_options",
        lambda _catalog: {"llm": [{"model_id": "admin-model"}]},
    )
    monkeypatch.setattr(
        settings_module,
        "allowed_llm_options",
        lambda: {"llm": [{"model_id": "granted-model"}]},
    )
    return TestClient(_mount((settings_module.router, "/api/settings")))


@pytest.fixture
def knowledge_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(knowledge_module, "get_kb_manager", lambda: _StubKBManager(tmp_path))
    kiwix_client_module = importlib.import_module(
        "deeptutor.services.rag.pipelines.kiwix.client"
    )

    async def _no_archives(cls, _base_url: str, _query: str = "", **_kwargs):
        return []

    monkeypatch.setattr(kiwix_client_module.KiwixClient, "list_archives", classmethod(_no_archives))
    return TestClient(_mount((knowledge_module.router, "/api")))


@pytest.fixture
def sessions_store() -> _RecordingSessionStore:
    return _RecordingSessionStore()


@pytest.fixture
def sessions_client(
    sessions_store: _RecordingSessionStore, monkeypatch: pytest.MonkeyPatch
) -> TestClient:
    monkeypatch.setattr(sessions_module, "get_session_store", lambda: sessions_store)
    return TestClient(_mount((sessions_module.router, "/api/sessions")))


@pytest.fixture
def partners_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(partners_module, "get_partner_manager", lambda: _StubSoulManager())
    return TestClient(_mount((partners_module.router, "/api/partners")))


# ---------------------------------------------------------------------------
# Matrix rows
# ---------------------------------------------------------------------------

#: Routes any authenticated identity may call.
OPEN_ROUTES: list[tuple[str, str, str, dict[str, object]]] = [
    ("settings", "GET", "/api/settings/llm-options", {}),
    ("knowledge", "GET", "/api/knowledge-bases/health", {}),
    ("sessions", "GET", "/api/sessions", {}),
    ("sessions", "GET", "/api/sessions/search", {"q": "needle"}),
    ("partners", "GET", "/api/partners/souls", {}),
]

#: Admin-gated routes: anonymous/invalid are 401, an ordinary user is 403.
ADMIN_ROUTES: list[tuple[str, str, str, dict[str, object]]] = [
    ("settings", "GET", "/api/settings/presets", {}),
    ("knowledge", "GET", "/api/knowledge-bases/kiwix-catalog", {"server_url": "http://kiwix.example"}),
    ("partners", "POST", "/api/partners/souls", {"id": "new-soul", "name": "New Soul", "content": "body"}),
]

_CLIENTS = {
    "settings": "settings_client",
    "knowledge": "knowledge_client",
    "sessions": "sessions_client",
    "partners": "partners_client",
}


def _client_for(request: pytest.FixtureRequest, router_name: str) -> TestClient:
    return request.getfixturevalue(_CLIENTS[router_name])


@pytest.mark.parametrize(
    "router_name,method,path,params", OPEN_ROUTES, ids=[f"{r}:{m} {p}" for r, m, p, _ in OPEN_ROUTES]
)
@pytest.mark.parametrize("identity", ["anonymous", "invalid", "user", "admin"])
def test_open_route_auth_matrix(
    request: pytest.FixtureRequest,
    user_and_admin_tokens: dict[str, str],
    identity: str,
    router_name: str,
    method: str,
    path: str,
    params: dict[str, object],
) -> None:
    client = _client_for(request, router_name)
    headers = (
        {}
        if identity in ("anonymous", "invalid")
        else {"Authorization": f"Bearer {user_and_admin_tokens[identity]}"}
    )
    if identity == "invalid":
        headers = {"Authorization": "Bearer not-a-jwt"}
    response = client.request(method, path, params=params or None, headers=headers)
    if identity in ("anonymous", "invalid"):
        assert response.status_code == 401, f"{identity} must be rejected with 401"
        return
    assert response.status_code == 200, f"{identity} must be allowed on {path}"


@pytest.mark.parametrize(
    "router_name,method,path,params_or_payload",
    ADMIN_ROUTES,
    ids=[f"{r}:{m} {p}" for r, m, p, _ in ADMIN_ROUTES],
)
@pytest.mark.parametrize("identity", ["anonymous", "invalid", "user", "admin"])
def test_admin_route_auth_matrix(
    request: pytest.FixtureRequest,
    user_and_admin_tokens: dict[str, str],
    identity: str,
    router_name: str,
    method: str,
    path: str,
    params_or_payload: dict[str, object],
) -> None:
    client = _client_for(request, router_name)
    headers = (
        {}
        if identity in ("anonymous", "invalid")
        else {"Authorization": f"Bearer {user_and_admin_tokens[identity]}"}
    )
    if identity == "invalid":
        headers = {"Authorization": "Bearer not-a-jwt"}
    kwargs: dict[str, object] = {"headers": headers}
    if method in ("POST", "PUT", "PATCH"):
        kwargs["json"] = params_or_payload
    else:
        kwargs["params"] = params_or_payload or None
    response = client.request(method, path, **kwargs)
    if identity in ("anonymous", "invalid"):
        assert response.status_code == 401, f"{identity} must be rejected with 401"
        return
    if identity == "user":
        assert response.status_code == 403, f"ordinary user must be refused on admin-only {path}"
        return
    assert response.status_code == 200, f"admin must be allowed on {path}"


def test_sessions_requests_run_as_the_token_identity(
    sessions_client: TestClient,
    sessions_store: _RecordingSessionStore,
    user_token: str,
    admin_token: str,
) -> None:
    """The ContextVar installed by ``require_auth`` carries the token identity.

    ``api/routers/sessions`` never names ``current_user`` itself — scoping
    happens deeper, through ``get_current_user()``. The recording store proves
    the dependency chain actually installed the caller's identity (and not,
    say, the local-admin fallback) by the time the service layer reads it.
    """
    user_response = sessions_client.get(
        "/api/sessions/search", params={"q": "needle"}, headers={"Authorization": f"Bearer {user_token}"}
    )
    assert user_response.status_code == 200
    assert sessions_store.seen_user_ids[-1] == USER_ID

    admin_response = sessions_client.get(
        "/api/sessions", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert admin_response.status_code == 200
    assert sessions_store.seen_user_ids[-1] == ADMIN_ID
    assert sessions_store.seen_user_ids == [USER_ID, ADMIN_ID]


def test_invalid_token_is_never_installed_as_local_admin(
    sessions_client: TestClient,
    sessions_store: _RecordingSessionStore,
) -> None:
    """A bad token answers 401 and must not fall back to the admin identity."""
    response = sessions_client.get(
        "/api/sessions", headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert response.status_code == 401
    assert sessions_store.seen_user_ids == []
