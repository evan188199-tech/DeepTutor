"""Contract tests for the unified not_found 404 template.

Locks the rendered detail shapes of ``deeptutor.api.errors.not_found`` and
asserts the api/routers tree holds zero hardcoded 404 detail literals
(``scripts/check_not_found_unified.py`` powers the scan).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient

from deeptutor.api.errors import not_found
from scripts.check_not_found_unified import scan

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_not_found_without_identifier() -> None:
    exc = not_found("Session")
    assert isinstance(exc, HTTPException)
    assert exc.status_code == 404
    assert exc.detail == "Session not found"


def test_not_found_with_identifier() -> None:
    exc = not_found("Knowledge base", "math")
    assert exc.status_code == 404
    assert exc.detail == "Knowledge base 'math' not found"


def test_not_found_with_non_string_identifier() -> None:
    exc = not_found("Material", 42)
    assert exc.detail == "Material '42' not found"


def test_not_found_surfaces_over_http() -> None:
    app = FastAPI()
    router = APIRouter()

    @router.get("/thing/{thing_id}")
    def get_thing(thing_id: str) -> dict[str, str]:
        if thing_id != "real":
            raise not_found("Thing", thing_id)
        return {"thing_id": thing_id}

    app.include_router(router)
    client = TestClient(app)
    res = client.get("/thing/missing")
    assert res.status_code == 404
    assert res.json() == {"detail": "Thing 'missing' not found"}


def test_routers_have_no_hardcoded_404_details() -> None:
    residuals, _passthrough = scan(REPO_ROOT / "deeptutor" / "api" / "routers")
    assert residuals == [], "hardcoded 404 details must use not_found():\n" + "\n".join(residuals)
