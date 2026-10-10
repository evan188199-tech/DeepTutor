"""The sessions router refuses requests with the structured error envelope.

Every ``HTTPException`` raised by ``deeptutor/api/routers/sessions.py`` uses
the ``{"code", "message"}`` envelope shared with ``book.py`` and
``space_mcp.py``: the message text is the historical free-text detail (string
matching keeps working), and ``code`` is the machine-readable key the frontend
parses. The tests pin both halves — every raise site carries the envelope, and
representative refusals answer with the exact historical message plus the new
code.
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor.api.routers import sessions as sessions_router
from deeptutor.services.session.sqlite_store import SQLiteSessionStore

ROUTER_PATH = Path(sessions_router.__file__)


def _mounted(tmp_path, monkeypatch) -> tuple[TestClient, SQLiteSessionStore]:
    store = SQLiteSessionStore(tmp_path / "history.db")
    monkeypatch.setattr(sessions_router, "get_session_store", lambda: store)
    monkeypatch.setattr(sessions_router, "get_sqlite_session_store", lambda: store)
    app = FastAPI()
    app.include_router(sessions_router.router, prefix="/api/sessions")
    return TestClient(app), store


def test_every_http_exception_in_sessions_carries_the_envelope() -> None:
    tree = ast.parse(ROUTER_PATH.read_text())
    raised = [
        call
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "HTTPException"
    ]
    assert raised, "expected the sessions router to raise HTTPException somewhere"
    for call in raised:
        detail = next(kw for kw in call.keywords if kw.arg == "detail")
        assert isinstance(detail.value, ast.Dict), (
            "HTTPException detail must be the structured {'code', 'message'} envelope"
        )
        keys = {key.value for key in detail.value.keys}
        assert {"code", "message"} <= keys


def test_missing_session_answers_with_code_and_unchanged_message(tmp_path, monkeypatch) -> None:
    client, _ = _mounted(tmp_path, monkeypatch)

    body = client.get("/api/sessions/missing").json()["detail"]
    assert body == {"code": "session.not_found", "message": "Session not found"}

    body = client.patch("/api/sessions/missing", json={"title": "x"}).json()["detail"]
    assert body == {"code": "session.not_found", "message": "Session not found"}


def test_blank_search_query_refusal(tmp_path, monkeypatch) -> None:
    client, _ = _mounted(tmp_path, monkeypatch)

    response = client.get("/api/sessions/search", params={"q": "   "})

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "session.search_query_empty",
        "message": "Search query cannot be empty",
    }


def test_missing_message_trace_refusal(tmp_path, monkeypatch) -> None:
    client, store = _mounted(tmp_path, monkeypatch)
    session = asyncio.run(store.create_session(title="Trace"))

    response = client.get(f"/api/sessions/{session['id']}/messages/999999/events")

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "session.message_not_found",
        "message": "Message not found",
    }


def test_recycle_bin_refusals_keep_their_message(tmp_path, monkeypatch) -> None:
    client, _ = _mounted(tmp_path, monkeypatch)

    restore = client.post("/api/sessions/missing/restore").json()["detail"]
    purge = client.delete("/api/sessions/missing/purge").json()["detail"]

    assert restore == {
        "code": "session.not_in_recycle_bin",
        "message": "Session not found in recycle bin",
    }
    assert purge == {
        "code": "session.not_in_recycle_bin",
        "message": "Session not found in recycle bin",
    }


def test_empty_quiz_results_refusal(tmp_path, monkeypatch) -> None:
    client, _ = _mounted(tmp_path, monkeypatch)

    response = client.post("/api/sessions/any/quiz-results", json={"answers": []})

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "session.quiz_results_required",
        "message": "Quiz results are required",
    }


def test_self_parent_refusal(tmp_path, monkeypatch) -> None:
    client, store = _mounted(tmp_path, monkeypatch)
    session = asyncio.run(store.create_session(title="Parent"))

    response = client.patch(
        f"/api/sessions/{session['id']}/organization",
        json={"parent_session_id": session["id"]},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "session.self_parent",
        "message": "A session cannot be its own parent",
    }


def test_parent_assignment_refusals_pass_the_service_message_through(tmp_path, monkeypatch) -> None:
    client, store = _mounted(tmp_path, monkeypatch)
    session = asyncio.run(store.create_session(title="Child"))

    async def _invalid(*args, **kwargs):
        raise ValueError("Parent would create a cycle")

    async def _missing(*args, **kwargs):
        raise LookupError("parent missing")

    monkeypatch.setattr(sessions_router, "validate_parent_assignment", _invalid)
    response = client.patch(
        f"/api/sessions/{session['id']}/organization",
        json={"parent_session_id": "other"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "session.parent_assignment_invalid",
        "message": "Parent would create a cycle",
    }

    monkeypatch.setattr(sessions_router, "validate_parent_assignment", _missing)
    response = client.patch(
        f"/api/sessions/{session['id']}/organization",
        json={"parent_session_id": "other"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "session.parent_not_found",
        "message": "Parent session not found",
    }
