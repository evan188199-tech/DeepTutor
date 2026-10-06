"""Focused tests for book.py structured 4xx error envelope + contract documentation.

Two axes, matching the card's deliverables:
1. Runtime: the 409 bodies raised by ``book.py`` match the documented envelope
   models (verbatim ``code`` values, unchanged messages).
2. Contract: ``app.openapi()`` / the export pipeline document those response
   models on exactly the operations that can emit them.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import auth as auth_router
from deeptutor.api.routers import book as book_router
from deeptutor.book.models import (
    Block,
    BlockStatus,
    BlockType,
    Book,
    BookStatus,
    Page,
    PageStatus,
)
from deeptutor.book.storage import BookStorage
from deeptutor.multi_user.book_permission import BookPermission
from deeptutor.services.auth import TokenPayload

REVISION_OPS = [
    "/api/books/confirm-proposal",
    "/api/books/confirm-spine",
    "/api/books/delete-block",
    "/api/books/move-block",
    "/api/books/update-block",
    "/api/books/{book_id}/refresh-fingerprints",
    "/api/books/rebuild",
]
MUTATION_OPS = [
    "/api/books/regenerate-block",
    "/api/books/insert-block",
    "/api/books/change-block-type",
    "/api/books/deep-dive",
    "/api/books/supplement",
]
PAUSED_OPS = ["/api/books/compile-page"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def shared_env(tmp_path, monkeypatch):
    from deeptutor.book import engine as engine_module
    from deeptutor.book import storage as storage_module
    from deeptutor.multi_user import audit, grants, identity, paths
    from deeptutor.multi_user.identity import save_user, set_book_permission
    from deeptutor.multi_user.paths import get_admin_path_service
    from deeptutor.services import auth as auth_service

    admin_root = (tmp_path / "data").resolve()
    system_root = admin_root / "system"
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(paths, "USERS_ROOT", admin_root / "users")
    monkeypatch.setattr(paths, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(paths, "LEGACY_MULTI_USER_ROOT", tmp_path / "multi-user")
    monkeypatch.setattr(paths, "_path_services", {})
    monkeypatch.setattr(identity, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(identity, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(identity, "AUTH_DIR", system_root / "auth")
    monkeypatch.setattr(identity, "USERS_FILE", system_root / "auth" / "users.json")
    monkeypatch.setattr(identity, "SECRET_FILE", system_root / "auth" / "auth_secret")
    monkeypatch.setattr(identity, "LEGACY_USERS_FILE", tmp_path / "missing-users.json")
    monkeypatch.setattr(identity, "LEGACY_SECRET_FILE", tmp_path / "missing-secret")
    monkeypatch.setattr(grants, "GRANTS_DIR", system_root / "grants")
    monkeypatch.setattr(audit, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "POCKETBASE_ENABLED", False)
    monkeypatch.setattr(auth_service, "AUTH_USERNAME", "")
    monkeypatch.setattr(auth_service, "AUTH_PASSWORD_HASH", "")
    storage_module._storages.clear()
    engine_module._engines.clear()

    editor = save_user("editor", "hash", role="user")
    set_book_permission(
        "editor", BookPermission(books=(("bk_shared", "edit"), ("bk_paused", "edit")))
    )
    tokens = {"editor": TokenPayload(username="editor", role="user", user_id=editor["id"])}
    monkeypatch.setattr(auth_router, "decode_token", lambda token: tokens.get(token))

    shared = BookStorage(path_service=get_admin_path_service())
    shared.save_book(Book(id="bk_shared", title="Shared", page_count=1))
    shared.save_book(Book(id="bk_paused", title="Paused", page_count=1, status=BookStatus.PAUSED))
    shared.save_page(
        Page(
            id="pg_1",
            book_id="bk_shared",
            title="Page",
            status=PageStatus.READY,
            blocks=[
                Block(
                    id="blk_1",
                    type=BlockType.TEXT,
                    status=BlockStatus.READY,
                    payload={"body": "Original"},
                )
            ],
        )
    )

    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/auth")
    app.include_router(
        book_router.router,
        prefix="/api",
        dependencies=[
            Depends(auth_router.require_auth),
            Depends(auth_router.require_learning_surface),
        ],
    )
    return TestClient(app)


def _update_block(client: TestClient, *, expected_revision: int | None) -> dict:
    payload: dict = {
        "book_id": "bk_shared",
        "page_id": "pg_1",
        "block_id": "blk_1",
        "body": "Edited",
    }
    if expected_revision is not None:
        payload["expected_revision"] = expected_revision
    response = client.post("/api/books/update-block", headers=_headers("editor"), json=payload)
    assert response.status_code == 409
    return response.json()


def test_revision_required_body_matches_envelope(shared_env) -> None:
    client = shared_env

    detail = _update_block(client, expected_revision=None)["detail"]

    assert detail["code"] == "book_revision_required"
    assert detail["message"] == "Refresh the shared book before editing."
    parsed = book_router.BookRevisionRequiredErrorDetail.model_validate(detail)
    assert parsed.current_revision == 1


def test_revision_conflict_body_matches_envelope(shared_env) -> None:
    client = shared_env

    detail = _update_block(client, expected_revision=99)["detail"]

    assert detail["code"] == "book_revision_conflict"
    assert detail["current_revision"] == 1
    parsed = book_router.BookRevisionConflictErrorDetail.model_validate(detail)
    assert parsed.expected_revision == 99


def test_paused_book_body_matches_envelope(shared_env) -> None:
    client = shared_env

    response = client.post(
        "/api/books/compile-page",
        headers=_headers("editor"),
        json={"book_id": "bk_paused", "page_id": "pg_1"},
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "book_paused"
    parsed = book_router.BookPausedErrorDetail.model_validate(detail)
    assert parsed.message == (
        "Book generation is paused. Resume it explicitly before generating content."
    )


@pytest.fixture(scope="module")
def openapi_schema() -> dict:
    from deeptutor.api.main import app

    return app.openapi()


def _ref_target(schema: dict) -> str:
    ref = schema.get("$ref")
    assert ref, f"expected a $ref schema, got {schema}"
    return ref.split("/")[-1]


def _response409(openapi: dict, path: str) -> dict:
    return openapi["paths"][path]["post"]["responses"]["409"]


def test_openapi_documents_structured_409_on_all_emitting_operations(openapi_schema) -> None:
    groups = {
        "BookRevisionErrorResponse": REVISION_OPS,
        "BookMutationErrorResponse": MUTATION_OPS,
        "BookPausedErrorResponse": PAUSED_OPS,
    }
    for wrapper, paths in groups.items():
        for path in paths:
            schema = _response409(openapi_schema, path)["content"]["application/json"]["schema"]
            assert _ref_target(schema) == wrapper, f"{path}: {schema}"


def test_openapi_wrapper_models_reference_the_detail_shapes(openapi_schema) -> None:
    components = openapi_schema["components"]["schemas"]

    paused = components["BookPausedErrorResponse"]["properties"]["detail"]
    assert _ref_target(paused) == "BookPausedErrorDetail"

    revision = components["BookRevisionErrorResponse"]["properties"]["detail"]
    assert {_ref_target(option) for option in revision["anyOf"]} == {
        "BookRevisionRequiredErrorDetail",
        "BookRevisionConflictErrorDetail",
    }

    mutation = components["BookMutationErrorResponse"]["properties"]["detail"]
    assert {_ref_target(option) for option in mutation["anyOf"]} == {
        "BookPausedErrorDetail",
        "BookRevisionRequiredErrorDetail",
        "BookRevisionConflictErrorDetail",
    }


def test_openapi_detail_models_pin_the_verbatim_error_codes(openapi_schema) -> None:
    components = openapi_schema["components"]["schemas"]
    paused = components["BookPausedErrorDetail"]
    required = components["BookRevisionRequiredErrorDetail"]
    conflict = components["BookRevisionConflictErrorDetail"]

    assert paused["properties"]["code"]["const"] == "book_paused"
    assert required["properties"]["code"]["const"] == "book_revision_required"
    assert conflict["properties"]["code"]["const"] == "book_revision_conflict"
    assert "current_revision" in required["properties"]
    assert "expected_revision" in conflict["properties"]
    assert "current_revision" in conflict["properties"]


def test_openapi_omits_envelope_409_where_no_envelope_is_emitted(openapi_schema) -> None:
    # ``/books/resume`` and ``/books/pause`` claim their revision with
    # ``strict=False`` and never catch ``BookPausedError``, so they cannot
    # emit a structured 409 — the contract must not claim one.
    for path in ("/api/books/resume", "/api/books/pause"):
        responses = openapi_schema["paths"][path]["post"]["responses"]
        assert "409" not in responses


def test_export_pipeline_renders_the_envelope_models() -> None:
    import json

    from deeptutor.api.contracts.export import render_contracts

    rendered = json.loads(render_contracts()["openapi.json"])
    schemas = rendered["components"]["schemas"]
    assert "BookPausedErrorDetail" in schemas
    assert "BookRevisionRequiredErrorDetail" in schemas
    assert "BookRevisionConflictErrorDetail" in schemas
    assert (
        _response409(rendered, "/api/books/regenerate-block")["content"]["application/json"][
            "schema"
        ]["$ref"]
        == "#/components/schemas/BookMutationErrorResponse"
    )
