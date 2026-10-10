"""Contract: both login paths return one identical structured error envelope.

The login endpoint has two backends — PocketBase (email identity) and the
standard JWT+bcrypt store (username identity). They historically raised two
different plain-string details (``"Incorrect email or password"`` vs
``"Incorrect username or password"``), so clients could not tell a bad-credentials
401 from other 401s by string, nor map it to a localized message. Both paths
must return the same ``{"code", "message"}`` envelope, following the
structured-detail precedent in ``routers/book.py``.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

import deeptutor.api.routers.auth as auth_router

EXPECTED_DETAIL = {"code": "invalid_credentials", "message": "Incorrect email or password"}


@pytest.fixture
def login_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "PRIVATE_LOGIN_HOSTS", frozenset())
    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/auth")
    return TestClient(app)


def _post_bad_login(client: TestClient) -> dict[str, Any]:
    res = client.post(
        "/api/auth/login",
        json={"username": "whoever", "password": "wrong-password"},
    )
    assert res.status_code == 401
    return res.json()["detail"]


def test_standard_mode_login_failure_envelope(
    login_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auth_router, "POCKETBASE_ENABLED", False)
    monkeypatch.setattr(auth_router, "authenticate", lambda username, password: None)
    assert _post_bad_login(login_client) == EXPECTED_DETAIL


def test_pocketbase_mode_login_failure_envelope(
    login_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auth_router, "POCKETBASE_ENABLED", True)
    monkeypatch.setattr(auth_router, "authenticate_pb", lambda username, password: None)
    assert _post_bad_login(login_client) == EXPECTED_DETAIL


def test_both_login_paths_share_one_envelope(
    login_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auth_router, "POCKETBASE_ENABLED", False)
    monkeypatch.setattr(auth_router, "authenticate", lambda username, password: None)
    standard_detail = _post_bad_login(login_client)

    monkeypatch.setattr(auth_router, "POCKETBASE_ENABLED", True)
    monkeypatch.setattr(auth_router, "authenticate_pb", lambda username, password: None)
    pocketbase_detail = _post_bad_login(login_client)

    assert standard_detail == pocketbase_detail == EXPECTED_DETAIL
