"""Co-Writer router 500s must answer with a coded neutral message, not str(e).

Every blanket-500 handler used to echo the raw exception text, which can name
host paths, provider payloads, or other internal state. The contract now is:
500 with {"code": "co_writer_internal_error", "message": <neutral retry hint>}
and the traceback (only) in the server log. This walks the full affected
surface so an endpoint that regresses to echoing fails here.
"""

from __future__ import annotations

from contextlib import contextmanager
import logging
from types import SimpleNamespace

from fastapi import FastAPI
import pytest
from starlette.testclient import TestClient

pytest.importorskip("fastapi")

import deeptutor.services.config as _dt_config

_dt_config.load_config_with_main = lambda *_a, **_k: {
    "paths": {},
    "logging": {},
    "system": {"language": "en"},
}

from deeptutor.api.routers import co_writer as co_writer_router
from deeptutor.co_writer import edit_agent

BOOM = RuntimeError("KERNEL_PANIC at /Users/secret/.deeptutor/state.db")


class _BoomStorage:
    """Answers every storage call with the same unexpected failure."""

    def list_documents(self):
        raise BOOM

    def create_document(self, **_kwargs):
        raise BOOM

    def load_document(self, _doc_id):
        raise BOOM

    def update_document(self, _doc_id, **_kwargs):
        raise BOOM

    def doc_exists(self, _doc_id):
        raise BOOM

    def delete_document(self, _doc_id):
        raise BOOM


class _BoomAgent:
    async def process(self, **_kwargs):
        raise BOOM

    async def auto_mark(self, **_kwargs):
        raise BOOM


async def _boom_react_edit(*_args, **_kwargs):
    raise BOOM


def _boom_markdown_to_docx(*_args, **_kwargs):
    raise BOOM


def _boom_docx_to_markdown(*_args, **_kwargs):
    raise BOOM


def _build_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    @contextmanager
    def _boom_selected_agent(_selection, *, language):
        yield _BoomAgent()

    def _boom_load_history():
        raise BOOM

    monkeypatch.setattr(
        "deeptutor.multi_user.context.get_current_user",
        lambda: SimpleNamespace(is_admin=True),
    )
    monkeypatch.setattr(co_writer_router, "get_co_writer_storage", lambda: _BoomStorage())
    monkeypatch.setattr(co_writer_router, "_selected_edit_agent", _boom_selected_agent)
    monkeypatch.setattr(co_writer_router, "_run_react_edit", _boom_react_edit)
    monkeypatch.setattr(co_writer_router, "_current_language", lambda: "en")
    monkeypatch.setattr(co_writer_router, "docx_to_markdown", _boom_docx_to_markdown)
    monkeypatch.setattr(co_writer_router, "markdown_to_docx", _boom_markdown_to_docx)
    monkeypatch.setattr(edit_agent, "load_history", _boom_load_history)
    monkeypatch.setattr(edit_agent, "tool_calls_dir", _boom_load_history)

    app = FastAPI()
    app.include_router(co_writer_router.router)
    return app


CRUD_REQUESTS = [
    ("GET", "/documents", None),
    ("POST", "/documents", {"title": "T", "content": "# Body"}),
    ("GET", "/documents/a1b2c3d4e5f6", None),
    ("PUT", "/documents/a1b2c3d4e5f6", {"title": "T", "content": "# Body"}),
    ("DELETE", "/documents/a1b2c3d4e5f6", None),
    ("GET", "/documents/history", None),
    ("GET", "/documents/history/op_1", None),
    ("GET", "/documents/tool-calls/op_1", None),
]

ACTION_REQUESTS = [
    ("POST", "/documents/actions/edit", {"text": "T", "instruction": "polish"}),
    ("POST", "/documents/actions/edit-react", {"selected_text": "T", "mode": "rewrite"}),
    ("POST", "/documents/actions/automark", {"text": "T"}),
    (
        "POST",
        "/documents/export/docx",
        {"title": "Notes", "content": "# Body"},
    ),
]


@pytest.mark.parametrize("method,url,body", CRUD_REQUESTS + ACTION_REQUESTS)
def test_unexpected_failures_return_a_neutral_coded_500(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    method: str,
    url: str,
    body,
) -> None:
    app = _build_app(monkeypatch)

    with (
        TestClient(app, raise_server_exceptions=False) as client,
        caplog.at_level(logging.ERROR, logger="deeptutor.api.routers.co_writer"),
    ):
        if isinstance(body, dict) and "file" in body:
            resp = client.post(url, files=body)
        else:
            resp = client.request(method, url, json=body)
        assert resp.status_code == 500, f"{method} {url} returned {resp.status_code}"
        detail = resp.json()["detail"]
        assert detail["code"] == "co_writer_internal_error", f"{method} {url} lost the error code"
        assert detail["message"] == (
            "The Co-Writer service hit an unexpected error. Please retry."
        ), f"{method} {url} changed the neutral wording"
        assert "KERNEL_PANIC" not in resp.text, f"{method} {url} leaked the exception"
        assert "/Users/secret" not in resp.text, f"{method} {url} leaked a host path"

    logged = [r for r in caplog.records if r.name == "deeptutor.api.routers.co_writer"]
    assert logged, f"{method} {url} was not logged"
    assert all(r.exc_info for r in logged), "a log entry carries no traceback"


@pytest.mark.parametrize("converter", [_boom_docx_to_markdown, lambda *_a, **_k: "# imported"])
def test_import_docx_conversion_and_storage_failures_are_neutral(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    converter,
) -> None:
    """Both the converter leg and the storage leg of the import stay coded."""

    app = _build_app(monkeypatch)
    monkeypatch.setattr(co_writer_router, "docx_to_markdown", converter)

    with (
        TestClient(app, raise_server_exceptions=False) as client,
        caplog.at_level(logging.ERROR, logger="deeptutor.api.routers.co_writer"),
    ):
        resp = client.post(
            "/documents/import/docx",
            files={"file": ("notes.docx", b"PK\x03\x04stub", "application/octet-stream")},
        )
    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert detail == {
        "code": "co_writer_internal_error",
        "message": "The Co-Writer service hit an unexpected error. Please retry.",
    }
    assert "KERNEL_PANIC" not in resp.text
    assert "/Users/secret" not in resp.text
    logged = [r for r in caplog.records if r.name == "deeptutor.api.routers.co_writer"]
    assert logged, "the import failure was not logged"
    assert all(r.exc_info for r in logged), "a log entry carries no traceback"
