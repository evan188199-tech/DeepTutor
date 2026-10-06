"""Proposal validation failures must not echo pydantic validation details.

The confirm-proposal / confirm-spine and mastery-path module parsing endpoints
used to interpolate the full pydantic ``ValidationError`` (or ``exc.errors()``)
into the HTTP ``detail``. That leaks internal field paths and model names to
clients. These tests lock the neutral, entity-named wording and confirm the
validation details only reach the server-side log.
"""

from types import SimpleNamespace

from fastapi import HTTPException
import pytest

from deeptutor.api.routers import book as book_router
from deeptutor.api.routers import mastery_path as mastery_router

PYDANTIC_LEAK_MARKERS = (
    "ValidationError",
    "validation error",
    "Field required",
    "Input should be",
    "unable to parse string",
    "type=model",
    "type=missing",
)


def assert_neutral(detail: str, entity: str) -> None:
    assert entity in detail
    for marker in PYDANTIC_LEAK_MARKERS:
        assert marker not in detail


def _stub_book_resolution(monkeypatch) -> None:
    resolved = SimpleNamespace(engine=object())
    monkeypatch.setattr(book_router, "_resolve_book_or_404", lambda *a, **k: resolved)
    monkeypatch.setattr(book_router, "_claim_content_mutation", lambda *a, **k: 2)


@pytest.mark.asyncio
async def test_confirm_proposal_invalid_payload_returns_neutral_detail(monkeypatch, caplog):
    _stub_book_resolution(monkeypatch)

    req = book_router.ConfirmProposalRequest(
        book_id="bk", proposal={"estimated_chapters": "not-an-int"}
    )
    with caplog.at_level("WARNING", logger=book_router.__name__):
        with pytest.raises(HTTPException) as exc_info:
            await book_router.confirm_proposal(req)

    assert exc_info.value.status_code == 400
    assert_neutral(exc_info.value.detail, "proposal")
    assert exc_info.value.detail == (
        "The edited proposal is invalid — check chapter titles and source references."
    )
    # Validation details stay on the server side.
    assert any("confirm_proposal" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_confirm_spine_invalid_payload_returns_neutral_detail(monkeypatch, caplog):
    _stub_book_resolution(monkeypatch)

    req = book_router.ConfirmSpineRequest(
        book_id="bk", spine={"book_id": 123, "chapters": "not-a-list"}
    )
    with caplog.at_level("WARNING", logger=book_router.__name__):
        with pytest.raises(HTTPException) as exc_info:
            await book_router.confirm_spine(req)

    assert exc_info.value.status_code == 400
    assert_neutral(exc_info.value.detail, "spine")
    assert exc_info.value.detail == (
        "The edited spine is invalid — check chapter titles and source references."
    )
    assert any("confirm_spine" in r.message for r in caplog.records)


def test_parse_modules_invalid_knowledge_point_returns_neutral_detail(caplog):
    with caplog.at_level("WARNING", logger=mastery_router.__name__):
        with pytest.raises(HTTPException) as exc_info:
            mastery_router._parse_modules(
                [{"id": "m1", "name": "M", "order": 1, "knowledge_points": [{}]}]
            )

    assert exc_info.value.status_code == 422
    assert_neutral(exc_info.value.detail, "knowledge_point")
    assert exc_info.value.detail == (
        "Invalid knowledge_point data in modules[0] — check the knowledge point fields."
    )
    assert any("modules[0]" in r.message for r in caplog.records)


def test_parse_modules_invalid_module_returns_neutral_detail(caplog):
    with caplog.at_level("WARNING", logger=mastery_router.__name__):
        with pytest.raises(HTTPException) as exc_info:
            mastery_router._parse_modules([{"knowledge_points": []}])

    assert exc_info.value.status_code == 422
    assert_neutral(exc_info.value.detail, "module")
    assert exc_info.value.detail == ("Invalid module data in modules[0] — check the module fields.")
    assert any("modules[0]" in r.message for r in caplog.records)
