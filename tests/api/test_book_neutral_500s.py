"""Book router 500s must answer with a coded neutral message, not str(e).

Every blanket-500 handler used to echo the raw exception text, which can name
host paths, provider payloads, or other internal state. The contract now is:
500 with {"code": "book_internal_error", "message": <neutral retry hint>} and
the traceback (only) in the server log. This walks the full affected surface
so an endpoint that regresses to echoing fails here.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
import pytest
from starlette.testclient import TestClient

pytest.importorskip("fastapi")

from deeptutor.api.routers import book as book_router
from deeptutor.book.models import Book
from deeptutor.multi_user.book_access import ResolvedBook

BOOM = RuntimeError("KERNEL_PANIC at /Users/secret/.deeptutor/state.db")


class _BoomEngine:
    """Answers every engine call with the same unexpected failure."""

    def load_book(self, book_id: str) -> Book:
        return Book(id=book_id, title="T", revision=1)

    async def create_book(self, **_kwargs):
        raise BOOM

    async def confirm_proposal(self, **_kwargs):
        raise BOOM

    async def confirm_spine(self, **_kwargs):
        raise BOOM

    async def compile_page(self, **_kwargs):
        raise BOOM

    async def regenerate_block(self, **_kwargs):
        raise BOOM

    async def insert_block(self, **_kwargs):
        raise BOOM

    async def change_block_type(self, **_kwargs):
        raise BOOM

    async def create_deep_dive_subpage(self, **_kwargs):
        raise BOOM

    async def supplement_for_weakness(self, **_kwargs):
        raise BOOM

    async def resume_book(self, **_kwargs):
        raise BOOM

    async def pause_book(self, **_kwargs):
        raise BOOM

    async def rebuild_book(self, **_kwargs):
        raise BOOM


REQUESTS = [
    ("POST", "/api/books", {"user_intent": "Learn calculus"}),
    ("POST", "/api/books/confirm-proposal", {"book_id": "bk_1"}),
    ("POST", "/api/books/confirm-spine", {"book_id": "bk_1"}),
    ("POST", "/api/books/compile-page", {"book_id": "bk_1", "page_id": "pg_1"}),
    (
        "POST",
        "/api/books/regenerate-block",
        {"book_id": "bk_1", "page_id": "pg_1", "block_id": "bl_1"},
    ),
    (
        "POST",
        "/api/books/insert-block",
        {"book_id": "bk_1", "page_id": "pg_1", "block_type": "text"},
    ),
    (
        "POST",
        "/api/books/change-block-type",
        {"book_id": "bk_1", "page_id": "pg_1", "block_id": "bl_1", "new_type": "text"},
    ),
    (
        "POST",
        "/api/books/deep-dive",
        {"book_id": "bk_1", "parent_page_id": "pg_1", "topic": "Fourier"},
    ),
    ("POST", "/api/books/supplement", {"book_id": "bk_1", "page_id": "pg_1", "topic": "Fourier"}),
    ("POST", "/api/books/resume", {"book_id": "bk_1"}),
    ("POST", "/api/books/pause", {"book_id": "bk_1"}),
    ("POST", "/api/books/rebuild", {"book_id": "bk_1"}),
]


def _build_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    engine = _BoomEngine()

    def _resolve(book_id: str) -> ResolvedBook:
        return ResolvedBook(
            engine=engine,
            source="own",
            permission="edit",
            can_edit=True,
            can_delete=True,
            learning=None,
        )

    monkeypatch.setattr(book_router, "get_book_engine", lambda: engine)
    monkeypatch.setattr(book_router, "resolve_book", _resolve)
    monkeypatch.setattr(book_router, "can_create_book", lambda: True)

    app = FastAPI()
    app.include_router(book_router.router, prefix="/api")
    return app


def test_unexpected_failures_return_a_neutral_coded_500(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = _build_app(monkeypatch)

    with (
        TestClient(app, raise_server_exceptions=False) as client,
        caplog.at_level(logging.ERROR, logger="deeptutor.api.routers.book"),
    ):
        for method, url, body in REQUESTS:
            resp = client.request(method, url, json=body)
            assert resp.status_code == 500, f"{method} {url} returned {resp.status_code}"
            detail = resp.json()["detail"]
            assert detail["code"] == "book_internal_error", f"{method} {url} lost the error code"
            assert detail["message"] == (
                "The book engine hit an unexpected error. Please retry."
            ), f"{method} {url} changed the neutral wording"
            assert "KERNEL_PANIC" not in resp.text, f"{method} {url} leaked the exception"
            assert "/Users/secret" not in resp.text, f"{method} {url} leaked a host path"

    logged = [r for r in caplog.records if r.name == "deeptutor.api.routers.book"]
    assert len(logged) >= len(REQUESTS), "not every unexpected failure was logged"
    assert all(r.exc_info for r in logged), "a log entry carries no traceback"
