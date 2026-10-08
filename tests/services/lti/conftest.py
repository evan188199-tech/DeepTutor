"""Shared fixtures for the LTI 1.3 service tests.

Everything is offline: the platform's JWKS is supplied inline (``key_set``),
so no HTTP client is ever constructed. IdP keys are generated per test run and
id_tokens are signed with ``python-jose`` exactly like a real LMS would.
"""

from __future__ import annotations

import time
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import pytest

from deeptutor.services.lti import LtiPlatform, LtiService

ISSUER = "https://lms.example.edu"
CLIENT_ID = "deeptutor-client-1"
DEPLOYMENT_ID = "deployment-7"
AUTH_LOGIN_URL = "https://lms.example.edu/mod/lti/auth.php"
TARGET_LINK_URI = "https://deeptutor.example.edu/app"
REDIRECT_URI = "https://deeptutor.example.edu/api/lti/launch"
KID = "test-key-1"

INSTRUCTOR_ROLE = "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"
TEACHING_ASSISTANT_ROLE = "http://purl.imsglobal.org/vocab/lis/v2/membership#TeachingAssistant"
LEARNER_ROLE = "http://purl.imsglobal.org/vocab/lis/v2/membership#Learner"


def _b64url_uint(value: int) -> str:
    from base64 import urlsafe_b64encode

    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return urlsafe_b64encode(raw).decode().rstrip("=")


def jwk_for_key(key: rsa.RSAPrivateKey, kid: str = KID) -> dict[str, Any]:
    numbers = key.public_key().public_numbers()
    return {
        "kty": "RSA",
        "kid": kid,
        "use": "sig",
        "alg": "RS256",
        "n": _b64url_uint(numbers.n),
        "e": _b64url_uint(numbers.e),
    }


def private_pem(key: rsa.RSAPrivateKey) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()


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
def login_result(service: LtiService):
    return service.begin_login(
        {
            "iss": ISSUER,
            "login_hint": "lms-user-1",
            "target_link_uri": TARGET_LINK_URI,
            "client_id": CLIENT_ID,
            "lti_message_hint": "course-message-hint",
        },
        redirect_uri=REDIRECT_URI,
    )


def make_id_token(
    idp_key: rsa.RSAPrivateKey,
    *,
    nonce: str,
    iss: str = ISSUER,
    aud: str = CLIENT_ID,
    sub: str = "lms-user-1",
    exp: int | None = None,
    iat: int | None = None,
    deployment_id: Any = DEPLOYMENT_ID,
    message_type: str = "LtiResourceLinkRequest",
    target_link_uri: str = TARGET_LINK_URI,
    roles: list[str] | None = None,
    resource_link: Any = None,
    kid: str = KID,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    from jose import jwt as jose_jwt

    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": iss,
        "aud": aud,
        "sub": sub,
        "exp": exp if exp is not None else now + 300,
        "iat": iat if iat is not None else now,
        "nonce": nonce,
        "azp": aud,
        "https://purl.imsglobal.org/spec/lti/claim/message_type": message_type,
        "https://purl.imsglobal.org/spec/lti/claim/deployment_id": deployment_id,
        "https://purl.imsglobal.org/spec/lti/claim/target_link_uri": target_link_uri,
        "https://purl.imsglobal.org/spec/lti/claim/roles": roles or [LEARNER_ROLE],
        "https://purl.imsglobal.org/spec/lti/claim/resource_link": resource_link
        if resource_link is not None
        else {"id": "resource-link-1"},
    }
    if extra_claims:
        claims.update(extra_claims)
    return jose_jwt.encode(claims, private_pem(idp_key), algorithm="RS256", headers={"kid": kid})
