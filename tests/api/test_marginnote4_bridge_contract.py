"""Wire contract of the MarginNote 4 server-side device bridge.

Upstream issue #1242 documented that the published v0.1.0 add-on cannot talk
to the bridge it was built for. Mapping of that issue's defect items to
what server-side tests can and cannot pin:

* ``addon.js`` lines 191/222 hardcode ``/api/v1/marginnote4/...`` while
  DeepTutor v1.5.16 mounts the router at ``/api/marginnote4/*`` — pinned
  here (route surface + 404s for the drifted prefix);
* the MN3-style ``main.js`` entry points, the ``addon.js`` syntax error,
  and the MN3-era manifest version are client-package defects with no
  server-side surface, so they are out of scope for this file.

These tests pin the server side of the contract so a future refactor cannot
silently rename the mount again:

* the route surface is exactly the six documented endpoints, under the
  unversioned ``/api/marginnote4`` prefix (#1242 defect: path drift),
* the ``/api/v1/...`` prefix the old add-on dials is not served,
* session endpoints reject without a DeepTutor session while device
  endpoints authenticate purely by the pairing token
  (``Authorization: MarginNote <device_id>:<token>``),
* request/response shapes match what the add-on serialises.

Mounted on a bare FastAPI app with the production include from
``main.py`` (prefix + tags, no blanket dependency) so the suite does not
boot every other router. Behaviour-level auth/edge cases live in
``test_marginnote4_router.py``; nothing here overlaps with PR #1243, which
bundles the add-on client itself.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import auth as auth_router
from deeptutor.api.routers import marginnote4
from deeptutor.services.auth import TokenPayload
from deeptutor.services.path_service import PathService

# The production mount, verbatim from deeptutor/api/main.py.
PRODUCTION_PREFIX = "/api/marginnote4"

# The prefix the deprecated v0.1.0 add-on hardcodes (upstream #1242).
DRIFTED_PREFIX = "/api/v1/marginnote4"

EXPECTED_ROUTES: dict[str, set[str]] = {
    f"{PRODUCTION_PREFIX}/pair": {"POST"},
    f"{PRODUCTION_PREFIX}/devices": {"GET"},
    f"{PRODUCTION_PREFIX}/devices/{{device_id}}": {"DELETE"},
    f"{PRODUCTION_PREFIX}/status": {"GET"},
    f"{PRODUCTION_PREFIX}/sync": {"POST"},
    f"{PRODUCTION_PREFIX}/heartbeat": {"POST"},
}


@pytest.fixture
def home(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    yield tmp_path
    PathService.reset_instance()


@pytest.fixture
def app(home: Path) -> FastAPI:
    app = FastAPI()
    app.include_router(marginnote4.router, prefix=PRODUCTION_PREFIX, tags=["marginnote4"])
    return app


@pytest.fixture
def client(app: FastAPI):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def real_session_auth(monkeypatch):
    """AUTH_ENABLED=true, tokens accepted without a live user database."""
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(
        auth_router,
        "decode_token",
        lambda _t: TokenPayload(username="mn4-user", role="user", user_id="u_mn4"),
    )


@pytest.fixture
def session_out_of_way(app: FastAPI, real_session_auth):
    """Auth enforcement stays on, but a session is provided for every call.

    Mirrors ``test_marginnote4_router.py``: the session-auth 401 boundary is
    pinned by ``test_session_routes_reject_unauthenticated_calls``; here it
    only needs to be out of the way so pairing — which under a real user
    resolves a per-user workspace and 501s by design — yields a device
    credential for the shape and flow tests.
    """
    from deeptutor.api.routers.auth import require_auth

    app.dependency_overrides[require_auth] = lambda: None
    yield


def _effective_routes(app: FastAPI) -> Iterator[tuple[str, object]]:
    """Yield ``(effective_path, route)`` across flat and nested FastAPI releases.

    FastAPI 0.141 stopped flattening included routers into ``app.routes``;
    each included-router entry exposes its compiled routes through
    ``effective_route_contexts()``, where the context itself carries the
    effective path, methods, and dependencies.
    """
    for entry in app.routes:
        contexts = getattr(entry, "effective_route_contexts", None)
        if callable(contexts):
            for compiled in contexts():
                path = getattr(compiled, "path", None)
                if isinstance(path, str):
                    yield path, compiled
            continue
        if isinstance(getattr(entry, "path", None), str):
            yield entry.path, entry


def _bridge_routes(app: FastAPI) -> dict[str, set[str]]:
    surface: dict[str, set[str]] = {}
    for path, route in _effective_routes(app):
        if not path.startswith(PRODUCTION_PREFIX):
            continue
        methods = getattr(route, "methods", None)
        if methods:
            surface[path] = set(methods) - {"HEAD", "OPTIONS"}
    return surface


# -- route surface (#1242: mount prefix) -------------------------------------


def test_route_surface_is_exactly_the_six_documented_endpoints(app: FastAPI) -> None:
    """Every bridge endpoint lives under the unversioned /api/marginnote4 prefix."""
    surface = _bridge_routes(app)

    unexpected = set(surface) - set(EXPECTED_ROUTES)
    missing = set(EXPECTED_ROUTES) - set(surface)
    assert not unexpected, f"Undocumented bridge routes appeared: {sorted(unexpected)}"
    assert not missing, f"Bridge routes disappeared: {sorted(missing)}"
    assert surface == EXPECTED_ROUTES


def test_no_bridge_route_is_served_under_api_v1(app: FastAPI) -> None:
    """#1242: the add-on's hardcoded /api/v1/marginnote4/... prefix does not exist."""
    versioned = [path for path, _ in _effective_routes(app) if path.startswith(DRIFTED_PREFIX)]
    assert versioned == [], f"Routes leaked under {DRIFTED_PREFIX}: {versioned}"


def test_drifted_v1_urls_return_404(client) -> None:
    """The exact calls the v0.1.0 add-on makes (addon.js:191/222) hit nothing."""
    for path, method in [
        (f"{DRIFTED_PREFIX}/pair", "post"),
        (f"{DRIFTED_PREFIX}/sync", "post"),
        (f"{DRIFTED_PREFIX}/heartbeat", "post"),
        (f"{DRIFTED_PREFIX}/devices", "get"),
        (f"{DRIFTED_PREFIX}/status", "get"),
    ]:
        response = getattr(client, method)(path)
        assert response.status_code == 404, f"{method.upper()} {path} unexpectedly exists"


def test_bridge_routes_declare_their_own_auth_split(app: FastAPI) -> None:
    """Management routes carry require_auth in-router; device routes do not.

    ``main.py`` includes this router without a blanket dependency, so the
    split lives in the route declarations themselves — exactly what a
    re-mount under a different prefix must preserve.
    """
    from deeptutor.api.routers.auth import require_auth

    for path, route in _effective_routes(app):
        if not path.startswith(PRODUCTION_PREFIX):
            continue
        dependencies = [d.dependency for d in getattr(route, "dependencies", [])]
        needs_session = require_auth in dependencies
        if path.endswith(("/sync", "/heartbeat")):
            assert not needs_session, f"{path} must authenticate by device token, not session"
        else:
            assert needs_session, f"{path} must require a DeepTutor session"


# -- auth boundary under the production mount --------------------------------


def test_session_routes_reject_unauthenticated_calls(client, real_session_auth) -> None:
    headers = {"Authorization": "Bearer not-needed-here"}
    unauthenticated = {
        "post pair": lambda: client.post(f"{PRODUCTION_PREFIX}/pair", json={}),
        "get devices": lambda: client.get(f"{PRODUCTION_PREFIX}/devices"),
        "delete device": lambda: client.delete(f"{PRODUCTION_PREFIX}/devices/any-device"),
        "get status": lambda: client.get(f"{PRODUCTION_PREFIX}/status"),
    }
    for label, call in unauthenticated.items():
        response = call()
        assert response.status_code == 401, f"{label} without a session must be 401"
        assert response.json()["detail"] == "Not authenticated", label


def test_device_routes_accept_a_device_token_without_any_session(client, session_out_of_way) -> None:
    """#1242 contract: sync/heartbeat work for a headless add-on — no cookie,
    no bearer, only the pairing credential."""
    session = {"Authorization": "Bearer session-token"}
    paired = client.post(f"{PRODUCTION_PREFIX}/pair", json={"device_name": "iPad"}, headers=session)
    assert paired.status_code == 200, paired.text
    body = paired.json()

    device = {"Authorization": f"MarginNote {body['device_id']}:{body['token']}"}
    beat = client.post(f"{PRODUCTION_PREFIX}/heartbeat", headers=device)
    assert beat.status_code == 200, beat.text
    assert beat.json()["status"] == "ok"

    synced = client.post(
        f"{PRODUCTION_PREFIX}/sync",
        json={"cursor": "", "objects": [], "deleted_ids": []},
        headers=device,
    )
    assert synced.status_code == 200, synced.text


def test_device_routes_reject_without_device_credentials(client, real_session_auth) -> None:
    """A session-less call with no device header gets the *device* 401, not the session one."""
    for suffix in ("sync", "heartbeat"):
        response = client.post(f"{PRODUCTION_PREFIX}/{suffix}", json={})
        assert response.status_code == 401
        assert response.json()["detail"] == "Missing or malformed Authorization header.", suffix


# -- request / response shapes ------------------------------------------------


def test_pair_response_shape(client, session_out_of_way) -> None:
    headers = {"Authorization": "Bearer session-token"}
    named = client.post(
        f"{PRODUCTION_PREFIX}/pair",
        json={"device_name": "iPad Pro", "device_kind": "ipados"},
        headers=headers,
    )
    assert named.status_code == 200, named.text
    body = named.json()
    assert set(body) == {"device_id", "token", "device_name", "device_kind"}
    assert body["device_name"] == "iPad Pro"
    assert body["device_kind"] == "ipados"
    assert body["token"], "pairing must hand out a one-time token"

    default = client.post(f"{PRODUCTION_PREFIX}/pair", json={}, headers=headers).json()
    assert default["device_name"] == ""
    assert default["device_kind"] == "macos"


def test_sync_request_and_response_shape(client, session_out_of_way) -> None:
    headers = {"Authorization": "Bearer session-token"}
    body = client.post(f"{PRODUCTION_PREFIX}/pair", json={}, headers=headers).json()
    device = {"Authorization": f"MarginNote {body['device_id']}:{body['token']}"}

    synced = client.post(
        f"{PRODUCTION_PREFIX}/sync",
        json={
            "cursor": "cursor-7",
            "objects": [
                {
                    "object_id": "o1",
                    "object_type": "note",
                    "title": "Attention is all you need",
                    "content": "transformer note",
                    "excerpt": "highlighted text",
                    "document_id": "doc-1",
                    "document_title": "Deep Learning",
                    "page": 3,
                    "tags": ["ml", "nlp"],
                    "links": ["o2"],
                    "color": "yellow",
                    "created_at": "2026-10-04T00:00:00Z",
                    "updated_at": "2026-10-04T00:00:00Z",
                    "raw": {"mn": "payload"},
                }
            ],
            "deleted_ids": ["o9"],
        },
        headers=device,
    )
    assert synced.status_code == 200, synced.text
    result = synced.json()
    assert set(result) == {"stored", "updated", "deleted", "new_cursor"}
    assert result["stored"] == 1
    assert result["deleted"] == 1
    assert isinstance(result["new_cursor"], str)


def test_devices_list_and_revoke_shape(client, session_out_of_way) -> None:
    headers = {"Authorization": "Bearer session-token"}
    paired = client.post(f"{PRODUCTION_PREFIX}/pair", json={"device_name": "iPhone"}, headers=headers).json()

    devices = client.get(f"{PRODUCTION_PREFIX}/devices", headers=headers)
    assert devices.status_code == 200, devices.text
    listing = devices.json()
    assert isinstance(listing, list) and len(listing) == 1
    assert set(listing[0]) == {
        "device_id",
        "device_name",
        "device_kind",
        "paired_at",
        "last_seen",
        "active",
    }
    assert listing[0]["device_id"] == paired["device_id"]
    assert listing[0]["active"] is True

    revoked = client.delete(f"{PRODUCTION_PREFIX}/devices/{paired['device_id']}", headers=headers)
    assert revoked.status_code == 200, revoked.text
    assert revoked.json() == {"status": "revoked", "device_id": paired["device_id"]}

    gone = client.delete(f"{PRODUCTION_PREFIX}/devices/{paired['device_id']}", headers=headers)
    assert gone.status_code == 404


def test_status_shape(client, session_out_of_way) -> None:
    headers = {"Authorization": "Bearer session-token"}
    client.post(f"{PRODUCTION_PREFIX}/pair", json={}, headers=headers)

    status = client.get(f"{PRODUCTION_PREFIX}/status", headers=headers)
    assert status.status_code == 200, status.text
    body = status.json()
    assert set(body) == {"status", "devices", "objects"}
    assert body["status"] == "ok"
    assert body["devices"] == 1
    assert isinstance(body["objects"], int)
