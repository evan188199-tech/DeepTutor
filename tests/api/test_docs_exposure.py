"""Tests for the interactive docs / OpenAPI endpoint exposure switch."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor.api import main as api_main


def _resolve(
    monkeypatch, *, auth: str | None = None, env: str | None = None, docs: str | None = None
) -> dict:
    monkeypatch.delenv("AUTH_ENABLED", raising=False)
    monkeypatch.delenv("NEXT_PUBLIC_AUTH_ENABLED", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("DEEPTUTOR_API_DOCS_ENABLED", raising=False)
    if auth is not None:
        monkeypatch.setenv("AUTH_ENABLED", auth)
    if env is not None:
        monkeypatch.setenv("ENVIRONMENT", env)
    if docs is not None:
        monkeypatch.setenv("DEEPTUTOR_API_DOCS_ENABLED", docs)
    return api_main._resolve_docs_urls()


def test_docs_enabled_by_default_for_local_development(monkeypatch) -> None:
    urls = _resolve(monkeypatch)

    assert urls["docs_url"] == "/docs"
    assert urls["redoc_url"] == "/redoc"
    assert urls["openapi_url"] == "/openapi.json"


def test_docs_disabled_by_default_when_auth_enabled(monkeypatch) -> None:
    urls = _resolve(monkeypatch, auth="true")

    assert urls["docs_url"] is None
    assert urls["redoc_url"] is None
    assert urls["openapi_url"] is None


def test_docs_disabled_by_default_in_production(monkeypatch) -> None:
    for env in ("prod", "production", "Production"):
        urls = _resolve(monkeypatch, env=env)
        assert urls["docs_url"] is None
        assert urls["openapi_url"] is None


def test_docs_env_override_forces_enabled_when_auth_is_on(monkeypatch) -> None:
    urls = _resolve(monkeypatch, auth="true", docs="true")

    assert urls["docs_url"] == "/docs"
    assert urls["redoc_url"] == "/redoc"
    assert urls["openapi_url"] == "/openapi.json"


def test_docs_env_override_forces_disabled_for_local_development(monkeypatch) -> None:
    urls = _resolve(monkeypatch, docs="false")

    assert urls["docs_url"] is None
    assert urls["redoc_url"] is None
    assert urls["openapi_url"] is None


def test_docs_env_override_rejects_unknown_values_by_keeping_default(monkeypatch) -> None:
    urls = _resolve(monkeypatch, docs="maybe")

    assert urls["docs_url"] == "/docs"


def test_docs_urls_reachability_follows_the_resolved_switch() -> None:
    enabled_app = FastAPI(**api_main._DOCS_URLS_ENABLED)
    disabled_app = FastAPI(**api_main._DOCS_URLS_DISABLED)

    enabled_client = TestClient(enabled_app)
    assert enabled_client.get("/docs").status_code == 200
    assert enabled_client.get("/redoc").status_code == 200
    assert enabled_client.get("/openapi.json").status_code == 200

    disabled_client = TestClient(disabled_app)
    assert disabled_client.get("/docs").status_code == 404
    assert disabled_client.get("/redoc").status_code == 404
    assert disabled_client.get("/openapi.json").status_code == 404


def test_api_app_docs_urls_match_the_resolver_output() -> None:
    # The real app is assembled once at import; whatever the resolver decided
    # back then must be exactly what FastAPI received.
    assert api_main.app.docs_url == api_main._docs_urls["docs_url"]
    assert api_main.app.redoc_url == api_main._docs_urls["redoc_url"]
    assert api_main.app.openapi_url == api_main._docs_urls["openapi_url"]
