"""HTTP surface of the LTI router: flag-off 404s and the launch round trip."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import lti as lti_router
from deeptutor.services.lti import LtiPlatform, LtiService
from tests.services.lti.conftest import (
    AUTH_LOGIN_URL,
    CLIENT_ID,
    DEPLOYMENT_ID,
    ISSUER,
    LEARNER_ROLE,
    TARGET_LINK_URI,
    jwk_for_key,
    make_id_token,
)


@pytest.fixture
def lti_identity_root(tmp_path, monkeypatch):
    """Redirect the identity store under ``tmp_path`` (mirrors tests/multi_user)."""
    from deeptutor.multi_user import identity, paths

    project_root = tmp_path
    system_root = (project_root / "data" / "system").resolve()

    monkeypatch.setattr(paths, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(paths, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(paths, "USERS_ROOT", system_root / "users")
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", (project_root / "data").resolve())
    monkeypatch.setattr(paths, "_path_services", {})
    monkeypatch.setattr(identity, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(identity, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(identity, "AUTH_DIR", system_root / "auth")
    monkeypatch.setattr(identity, "USERS_FILE", system_root / "auth" / "users.json")
    monkeypatch.setattr(identity, "SECRET_FILE", system_root / "auth" / "auth_secret")

    from deeptutor.services import auth as auth_service

    monkeypatch.setattr(auth_service, "AUTH_USERNAME", "")
    monkeypatch.setattr(auth_service, "AUTH_PASSWORD_HASH", "")
    return tmp_path


@pytest.fixture
def idp_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def service(idp_key) -> LtiService:
    return LtiService(
        platforms=[
            LtiPlatform(
                issuer=ISSUER,
                client_id=CLIENT_ID,
                deployment_ids=frozenset({DEPLOYMENT_ID}),
                auth_login_url=AUTH_LOGIN_URL,
                target_link_uri=TARGET_LINK_URI,
                key_set={"keys": [jwk_for_key(idp_key)]},
            )
        ]
    )


@pytest.fixture
def app_client(lti_identity_root, monkeypatch, service) -> TestClient:
    from deeptutor.services import auth as auth_service

    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_service, "POCKETBASE_ENABLED", False)
    monkeypatch.setattr(auth_service, "AUTH_SECRET", "lti-test-secret")
    monkeypatch.setattr(lti_router, "_service", service)

    app = FastAPI()
    app.include_router(lti_router.router, prefix="/api/lti")
    return TestClient(app)


def _begin_login(client: TestClient) -> tuple[str, str]:
    response = client.get(
        "/api/lti/login",
        params={
            "iss": ISSUER,
            "login_hint": "lms-user-1",
            "target_link_uri": TARGET_LINK_URI,
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["cache-control"] == "no-store"
    query = {k: v[-1] for k, v in parse_qs(urlsplit(response.headers["location"]).query).items()}
    return query["state"], query["nonce"]


def test_endpoints_report_404_when_lti_is_disabled(monkeypatch) -> None:
    monkeypatch.setattr(lti_router, "_service", LtiService(platforms=[]))
    from deeptutor.services import auth as auth_service

    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_service, "POCKETBASE_ENABLED", False)

    app = FastAPI()
    app.include_router(lti_router.router, prefix="/api/lti")
    client = TestClient(app)

    assert client.get("/api/lti/login", follow_redirects=False).status_code == 404
    assert client.post("/api/lti/launch", data={"state": "s", "id_token": "t"}).status_code == 404


def test_endpoints_report_404_when_auth_is_disabled(monkeypatch, service) -> None:
    monkeypatch.setattr(lti_router, "_service", service)
    from deeptutor.services import auth as auth_service

    monkeypatch.setattr(auth_service, "AUTH_ENABLED", False)

    app = FastAPI()
    app.include_router(lti_router.router, prefix="/api/lti")
    client = TestClient(app)

    assert client.get("/api/lti/login", follow_redirects=False).status_code == 404


def test_login_endpoint_redirects_to_platform(app_client) -> None:
    _, _ = _begin_login(app_client)


def test_launch_endpoint_provisions_user_and_sets_session_cookie(app_client, idp_key) -> None:
    state, nonce = _begin_login(app_client)
    token = make_id_token(idp_key, nonce=nonce, sub="student-42", roles=[LEARNER_ROLE])

    response = app_client.post("/api/lti/launch", data={"state": state, "id_token": token})

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["ok"] is True
    assert body["role"] == "student"
    assert body["is_admin"] is False
    assert body["username"].startswith("lti-")

    cookie = response.headers["set-cookie"]
    assert "dt_token=" in cookie
    assert "httponly" in cookie.lower()

    from jose import jwt as jose_jwt

    claims = jose_jwt.decode(
        response.cookies["dt_token"],
        "lti-test-secret",
        algorithms=["HS256"],
    )
    assert claims["sub"] == body["username"]
    assert claims["role"] == "student"

    from deeptutor.multi_user.identity import load_users

    users = load_users()
    assert body["username"] in users
    assert users[body["username"]]["preset"] == "learner"


def test_launch_endpoint_rejects_forged_state_without_echoing_it(app_client, idp_key) -> None:
    token = make_id_token(idp_key, nonce="whatever")
    response = app_client.post("/api/lti/launch", data={"state": "forged-state", "id_token": token})

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_state"
    assert "forged-state" not in response.text
