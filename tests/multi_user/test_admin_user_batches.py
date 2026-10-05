"""Regression tests for admin batch user provisioning and deletion."""

from __future__ import annotations

import pytest


@pytest.fixture
def batch_client(mu_isolated_root, seed_user, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import deeptutor.api.routers.auth as auth_router
    from deeptutor.services.auth import TokenPayload

    admin = seed_user("root", role="admin")
    tokens = {
        "admin-token": TokenPayload(username="root", role="admin", user_id=admin["id"]),
        "user-token": TokenPayload(username="alice", role="user", user_id="u_alice"),
    }
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "POCKETBASE_ENABLED", False)
    monkeypatch.setattr(auth_router, "decode_token", lambda token: tokens.get(token))

    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/auth")
    return TestClient(app), {
        "admin": {"Authorization": "Bearer admin-token"},
        "user": {"Authorization": "Bearer user-token"},
    }


def test_import_reports_rows_and_creates_only_ordinary_users(batch_client):
    client, headers = batch_client
    csv_data = (
        "username,password,preset\n"
        "alice,alice-password-123,learner\n"
        "bob,bob-password-123,standard\n"
        "carol,carol-password-123,custom\n"
        "alice,duplicate-password-123,standard\n"
        "carol,short,standard\n"
    )

    response = client.post(
        "/api/auth/users/import",
        files={"file": ("users.csv", csv_data.encode("utf-8"), "text/csv")},
        headers=headers["admin"],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["created_count"] == 3
    assert body["failed_count"] == 2
    assert [result["ok"] for result in body["results"]] == [True, True, True, False, False], body
    assert "Username already taken" in body["results"][3]["error"]
    assert "Password must be at least 8 characters" in body["results"][4]["error"]
    assert all(result["user"]["role"] == "user" for result in body["results"][:3])
    assert all(result["user"]["is_admin"] is False for result in body["results"][:3])

    users = {
        item["username"]: item
        for item in client.get("/api/auth/users", headers=headers["admin"]).json()
    }
    assert set(users) == {"root", "alice", "bob", "carol"}
    assert users["alice"]["preset"] == "learner"
    assert users["carol"]["preset"] == "custom"
    assert all(item["role"] == "user" for name, item in users.items() if name != "root")


def test_import_rejects_role_column_and_creates_nothing(batch_client):
    client, headers = batch_client
    csv_data = "username,password,preset,role\nalice,alice-password-123,standard,admin\n"

    response = client.post(
        "/api/auth/users/import",
        files={"file": ("users.csv", csv_data.encode("utf-8"), "text/csv")},
        headers=headers["admin"],
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "CSV header must be exactly: username,password,preset"
    usernames = {
        item["username"] for item in client.get("/api/auth/users", headers=headers["admin"]).json()
    }
    assert usernames == {"root"}


def test_import_rolls_back_learner_when_grant_initialization_fails(batch_client, monkeypatch):
    client, headers = batch_client
    from deeptutor.multi_user import grants

    def fail_save_grant(*args, **kwargs):
        raise RuntimeError("grant initialization unavailable")

    monkeypatch.setattr(grants, "save_grant", fail_save_grant)

    response = client.post(
        "/api/auth/users/import",
        files={
            "file": (
                "users.csv",
                b"username,password,preset\nalice,alice-password-123,learner\n",
                "text/csv",
            )
        },
        headers=headers["admin"],
    )

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["ok"] is False
    assert result["error"] == "The learner preset could not be initialized."
    usernames = {
        item["username"] for item in client.get("/api/auth/users", headers=headers["admin"]).json()
    }
    assert usernames == {"root"}


def test_import_requires_admin(batch_client):
    client, headers = batch_client

    response = client.post(
        "/api/auth/users/import",
        files={
            "file": (
                "users.csv",
                b"username,password,preset\nalice,alice-password-123,standard\n",
                "text/csv",
            )
        },
        headers=headers["user"],
    )

    assert response.status_code == 403


def test_batch_delete_requires_admin(batch_client):
    client, headers = batch_client

    response = client.post(
        "/api/auth/users/batch-delete",
        json={"usernames": ["alice"]},
        headers=headers["user"],
    )

    assert response.status_code == 403


def test_batch_delete_reports_partial_results_and_protects_current_admin(batch_client, seed_user):
    client, headers = batch_client
    seed_user("alice")
    seed_user("bob")

    response = client.post(
        "/api/auth/users/batch-delete",
        json={"usernames": ["alice", "root", "missing", "bob"]},
        headers=headers["admin"],
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "ok": False,
        "deleted_count": 2,
        "failed_count": 2,
        "results": [
            {"username": "alice", "ok": True, "error": None},
            {"username": "root", "ok": False, "error": "You cannot delete your own account"},
            {"username": "missing", "ok": False, "error": "User not found"},
            {"username": "bob", "ok": True, "error": None},
        ],
    }
    usernames = {
        item["username"] for item in client.get("/api/auth/users", headers=headers["admin"]).json()
    }
    assert usernames == {"root"}


def test_import_accepts_normalized_csv_header_without_losing_row_values(batch_client):
    client, headers = batch_client
    response = client.post(
        "/api/auth/users/import",
        files={
            "file": (
                "users.csv",
                b" Username ,Password,Preset\nalice,alice-password-123,learner\n",
                "text/csv",
            )
        },
        headers=headers["admin"],
    )
    assert response.status_code == 200
    assert response.json()["created_count"] == 1
    assert response.json()["results"][0]["username"] == "alice"


def _import_csv(client, headers, payload: bytes):
    return client.post(
        "/api/auth/users/import",
        files={"file": ("users.csv", payload, "text/csv")},
        headers=headers,
    )


def _listed_usernames(client, headers) -> set[str]:
    return {item["username"] for item in client.get("/api/auth/users", headers=headers).json()}


def test_import_rejects_row_with_extra_columns_and_keeps_valid_rows(batch_client):
    client, headers = batch_client
    csv_data = (
        "username,password,preset\n"
        "alice,alice-password-123,standard\n"
        "bob,bob-password-123,standard,extra-tail\n"
    )

    response = _import_csv(client, headers["admin"], csv_data.encode("utf-8"))

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["created_count"] == 1
    assert body["failed_count"] == 1
    assert body["results"][1]["row"] == 3
    assert body["results"][1]["ok"] is False
    assert "Row has more values than the CSV header." in body["results"][1]["error"]
    assert _listed_usernames(client, headers["admin"]) == {"root", "alice"}


def test_import_rejects_blank_username_row(batch_client):
    client, headers = batch_client
    csv_data = "username,password,preset\n,blank-password-123,standard\n"

    response = _import_csv(client, headers["admin"], csv_data.encode("utf-8"))

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["ok"] is False
    assert result["row"] == 2
    assert "Email cannot be empty" in result["error"]
    assert _listed_usernames(client, headers["admin"]) == {"root"}


def test_import_rejects_header_only_csv(batch_client):
    client, headers = batch_client

    response = _import_csv(client, headers["admin"], b"username,password,preset\n")

    assert response.status_code == 422
    assert response.json()["detail"] == "User import file contains no user rows."
    assert _listed_usernames(client, headers["admin"]) == {"root"}


def test_import_rejects_non_utf8_payload(batch_client):
    client, headers = batch_client

    response = _import_csv(
        client,
        headers["admin"],
        b"username,password,preset\nal\xffice,password-123,standard\n",
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "User import must be a UTF-8 CSV file."
    assert _listed_usernames(client, headers["admin"]) == {"root"}


def test_import_rejects_admin_preset_rows_and_creates_nothing(batch_client):
    client, headers = batch_client
    csv_data = (
        "username,password,preset\nalice,alice-password-123,admin\nbob,bob-password-123,ADMIN\n"
    )

    response = _import_csv(client, headers["admin"], csv_data.encode("utf-8"))

    assert response.status_code == 200
    body = response.json()
    assert body["created_count"] == 0
    assert body["failed_count"] == 2
    assert all(result["ok"] is False for result in body["results"])
    assert all("Input should be" in result["error"] for result in body["results"])
    users = {
        item["username"]: item
        for item in client.get("/api/auth/users", headers=headers["admin"]).json()
    }
    assert set(users) == {"root"}
    assert users["root"]["role"] == "admin"


def test_import_defaults_blank_preset_to_standard(batch_client):
    client, headers = batch_client

    response = _import_csv(
        client,
        headers["admin"],
        b"username,password,preset\nalice,alice-password-123,\n",
    )

    assert response.status_code == 200
    assert response.json()["created_count"] == 1
    created = response.json()["results"][0]
    assert created["ok"] is True
    assert created["user"]["preset"] == "standard"
    assert created["user"]["role"] == "user"


def test_import_duplicate_email_creates_single_account(batch_client):
    client, headers = batch_client
    csv_data = (
        "username,password,preset\n"
        "alice@example.com,alice-password-123,standard\n"
        "alice@example.com,other-password-123,learner\n"
    )

    response = _import_csv(client, headers["admin"], csv_data.encode("utf-8"))

    assert response.status_code == 200
    body = response.json()
    assert body["created_count"] == 1
    assert body["failed_count"] == 1
    assert body["results"][0]["ok"] is True
    assert body["results"][1]["ok"] is False
    assert "Username already taken" in body["results"][1]["error"]
    matches = [
        item
        for item in client.get("/api/auth/users", headers=headers["admin"]).json()
        if item["username"] == "alice@example.com"
    ]
    assert len(matches) == 1


def test_batch_delete_deduplicates_repeated_usernames(batch_client, seed_user):
    client, headers = batch_client
    seed_user("alice")

    response = client.post(
        "/api/auth/users/batch-delete",
        json={"usernames": ["alice", " alice ", "alice"]},
        headers=headers["admin"],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["deleted_count"] == 1
    assert body["failed_count"] == 0
    assert body["results"] == [{"username": "alice", "ok": True, "error": None}]
    assert _listed_usernames(client, headers["admin"]) == {"root"}


def test_batch_delete_rejects_blank_username_entry(batch_client):
    client, headers = batch_client

    response = client.post(
        "/api/auth/users/batch-delete",
        json={"usernames": ["alice", "  "]},
        headers=headers["admin"],
    )

    assert response.status_code == 422
    assert _listed_usernames(client, headers["admin"]) == {"root"}


def test_single_create_rejects_admin_preset(batch_client):
    client, headers = batch_client

    response = client.post(
        "/api/auth/users",
        json={"username": "alice", "password": "alice-password-123", "preset": "admin"},
        headers=headers["admin"],
    )

    assert response.status_code == 422
    assert _listed_usernames(client, headers["admin"]) == {"root"}
