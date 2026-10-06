"""Knowledge router 500s must answer with a coded neutral message, not str(e).

Every blanket-500 handler used to echo the raw exception text, which can name
host paths, provider payloads, or other internal state. The contract now is:
500 with {"code": "knowledge_internal_error", "message": <neutral retry hint>}
and the traceback (only) in the server log. This walks the affected surface
across representative handler families so an endpoint that regresses to
echoing fails here.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
import pytest
from starlette.testclient import TestClient

pytest.importorskip("fastapi")

from deeptutor.api.routers import knowledge as knowledge_router

BOOM = RuntimeError("KERNEL_PANIC at /Users/secret/.deeptutor/state.db")
NEUTRAL_MESSAGE = "The knowledge service hit an unexpected error. Please retry."


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(knowledge_router.router, prefix="/api")
    return app


def test_config_read_failures_return_a_neutral_coded_500(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Provider listing and pipeline-config reads never echo the exception."""
    app = _build_app()

    def _boom(*_args, **_kwargs):
        raise BOOM

    monkeypatch.setattr("deeptutor.services.rag.service.RAGService.list_providers", _boom)
    monkeypatch.setattr(knowledge_router, "_pageindex_config_payload", _boom)
    monkeypatch.setattr(knowledge_router, "_ima_config_payload", _boom)

    requests = [
        ("GET", "/api/knowledge-bases/rag-providers"),
        ("GET", "/api/knowledge-bases/rag-pipelines/pageindex/config"),
        ("GET", "/api/knowledge-bases/rag-pipelines/ima/config"),
    ]

    with (
        TestClient(app, raise_server_exceptions=False) as client,
        caplog.at_level(logging.ERROR, logger="deeptutor.api.routers.knowledge"),
    ):
        for method, url in requests:
            resp = client.request(method, url)
            assert resp.status_code == 500, f"{method} {url} returned {resp.status_code}"
            detail = resp.json()["detail"]
            assert detail["code"] == "knowledge_internal_error", (
                f"{method} {url} lost the error code"
            )
            assert detail["message"] == NEUTRAL_MESSAGE, (
                f"{method} {url} changed the neutral wording"
            )
            assert "KERNEL_PANIC" not in resp.text, f"{method} {url} leaked the exception"
            assert "/Users/secret" not in resp.text, f"{method} {url} leaked a host path"

    logged = [r for r in caplog.records if r.name == "deeptutor.api.routers.knowledge"]
    assert len(logged) >= len(requests), "not every unexpected failure was logged"
    assert all(r.exc_info for r in logged), "a log entry carries no traceback"


def test_kb_read_failures_return_a_neutral_coded_500(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """KB detail, linked-folder and progress reads never echo the exception."""
    app = _build_app()

    def _boom(*_args, **_kwargs):
        raise BOOM

    monkeypatch.setattr(knowledge_router, "resolve_kb", _boom)

    requests = [
        ("GET", "/api/knowledge-bases/demo"),
        ("GET", "/api/knowledge-bases/demo/linked-folders"),
        ("GET", "/api/knowledge-bases/demo/progress"),
    ]

    with (
        TestClient(app, raise_server_exceptions=False) as client,
        caplog.at_level(logging.ERROR, logger="deeptutor.api.routers.knowledge"),
    ):
        for method, url in requests:
            resp = client.request(method, url)
            assert resp.status_code == 500, f"{method} {url} returned {resp.status_code}"
            detail = resp.json()["detail"]
            assert detail["code"] == "knowledge_internal_error", (
                f"{method} {url} lost the error code"
            )
            assert detail["message"] == NEUTRAL_MESSAGE, (
                f"{method} {url} changed the neutral wording"
            )
            assert "KERNEL_PANIC" not in resp.text, f"{method} {url} leaked the exception"
            assert "/Users/secret" not in resp.text, f"{method} {url} leaked a host path"

    logged = [r for r in caplog.records if r.name == "deeptutor.api.routers.knowledge"]
    assert len(logged) >= len(requests), "not every unexpected failure was logged"
    assert all(r.exc_info for r in logged), "a log entry carries no traceback"


def test_kb_write_failures_return_a_neutral_coded_500(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Default-KB reads and progress clears never echo the exception."""
    app = _build_app()

    def _boom(*_args, **_kwargs):
        raise BOOM

    monkeypatch.setattr(knowledge_router, "get_kb_manager", _boom)
    monkeypatch.setattr(knowledge_router, "_writable_kb", _boom)

    requests = [
        ("GET", "/api/knowledge-bases/default"),
        ("POST", "/api/knowledge-bases/demo/progress/clear"),
    ]

    with (
        TestClient(app, raise_server_exceptions=False) as client,
        caplog.at_level(logging.ERROR, logger="deeptutor.api.routers.knowledge"),
    ):
        for method, url in requests:
            resp = client.request(method, url)
            assert resp.status_code == 500, f"{method} {url} returned {resp.status_code}"
            detail = resp.json()["detail"]
            assert detail["code"] == "knowledge_internal_error", (
                f"{method} {url} lost the error code"
            )
            assert detail["message"] == NEUTRAL_MESSAGE, (
                f"{method} {url} changed the neutral wording"
            )
            assert "KERNEL_PANIC" not in resp.text, f"{method} {url} leaked the exception"
            assert "/Users/secret" not in resp.text, f"{method} {url} leaked a host path"

    logged = [r for r in caplog.records if r.name == "deeptutor.api.routers.knowledge"]
    assert len(logged) >= len(requests), "not every unexpected failure was logged"
    assert all(r.exc_info for r in logged), "a log entry carries no traceback"
