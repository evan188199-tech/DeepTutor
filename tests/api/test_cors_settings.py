"""Tests for FastAPI CORS settings."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from deeptutor.api import main as api_main


def test_cors_defaults_to_explicit_allowlist_when_auth_disabled(
    monkeypatch,
) -> None:
    monkeypatch.delenv("AUTH_ENABLED", raising=False)
    monkeypatch.delenv("CORS_ORIGIN", raising=False)
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.delenv("CORS_PERMISSIVE", raising=False)
    monkeypatch.setenv("FRONTEND_PORT", "3782")

    settings = api_main._build_cors_settings()

    assert settings["allow_origin_regex"] is None
    assert settings["mode"] == "explicit"
    assert "http://localhost:3782" in settings["allow_origins"]
    assert "http://127.0.0.1:3782" in settings["allow_origins"]


def test_cors_permissive_regex_is_opt_in_when_auth_disabled(monkeypatch) -> None:
    monkeypatch.delenv("AUTH_ENABLED", raising=False)
    monkeypatch.setenv("CORS_PERMISSIVE", "true")

    settings = api_main._build_cors_settings()

    assert settings["allow_origin_regex"] == r"https?://.*"
    assert settings["mode"] == "permissive"


def test_cors_permissive_opt_in_is_ignored_when_auth_enabled(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("CORS_PERMISSIVE", "true")
    monkeypatch.setenv("CORS_ORIGIN", "https://app.example.com/")

    settings = api_main._build_cors_settings()

    assert settings["allow_origin_regex"] is None
    assert settings["mode"] == "explicit"
    assert "https://app.example.com" in settings["allow_origins"]


def test_cors_requires_explicit_origins_when_auth_enabled(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("CORS_ORIGIN", "https://app.example.com/")
    monkeypatch.setenv(
        "CORS_ORIGINS",
        "https://foo.example.com, https://bar.example.com\nhttps://foo.example.com",
    )

    settings = api_main._build_cors_settings()

    assert settings["allow_origin_regex"] is None
    assert "https://app.example.com" in settings["allow_origins"]
    assert "https://foo.example.com" in settings["allow_origins"]
    assert "https://bar.example.com" in settings["allow_origins"]
    assert settings["allow_origins"].count("https://foo.example.com") == 1


def test_cors_normalizes_common_origin_input_mistakes(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv(
        "CORS_ORIGIN",
        "172.26.0.10:3782; https://learn.example.com/app/",
    )
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000;api.example.com")

    settings = api_main._build_cors_settings()

    assert settings["allow_origin_regex"] is None
    assert "http://172.26.0.10:3782" in settings["allow_origins"]
    assert "https://learn.example.com" in settings["allow_origins"]
    assert "http://api.example.com" in settings["allow_origins"]


def test_cors_preflight_allows_partner_patch_save() -> None:
    client = TestClient(api_main.app)

    response = client.options(
        "/api/partners/partner",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    allowed_methods = {
        method.strip() for method in response.headers["access-control-allow-methods"].split(",")
    }
    assert "PATCH" in allowed_methods


def _cors_test_app(cors_settings: dict) -> FastAPI:
    """Assemble the middleware exactly like ``deeptutor.api.main`` does."""
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_settings["allow_origins"],
        allow_origin_regex=cors_settings["allow_origin_regex"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return app


def test_cors_preflight_rejects_unlisted_remote_origin_by_default(monkeypatch) -> None:
    monkeypatch.delenv("AUTH_ENABLED", raising=False)
    monkeypatch.delenv("CORS_PERMISSIVE", raising=False)

    client = TestClient(_cors_test_app(api_main._build_cors_settings()))

    response = client.options(
        "/",
        headers={
            "Origin": "http://203.0.113.7:3782",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_cors_preflight_accepts_remote_origin_when_permissive_opt_in(monkeypatch) -> None:
    monkeypatch.delenv("AUTH_ENABLED", raising=False)
    monkeypatch.setenv("CORS_PERMISSIVE", "true")

    client = TestClient(_cors_test_app(api_main._build_cors_settings()))

    response = client.options(
        "/",
        headers={
            "Origin": "http://203.0.113.7:3782",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://203.0.113.7:3782"
