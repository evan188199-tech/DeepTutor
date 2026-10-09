"""Contract and failure-branch tests for the chat-history import router.

Complements ``tests/api/test_imports.py`` (which covers the happy path,
dedup and agent attribution against a real SQLite store) by pinning the
request-model contracts and the failure / 4xx branches: oversized requests,
oversized sessions, store errors, and query-parameter bounds — all against a
fake store, so nothing touches a real database or the network.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from deeptutor.api.routers import imports as imports_router
from deeptutor.api.routers.imports import (
    ChatHistoryImportRequest,
    ImportedMessage,
    ImportedSession,
    import_chat_history,
)
from deeptutor.services.session import make_imported_session_id

_SOURCES = ("chatgpt", "claude_code", "codex")


def _session(
    external_id: str = "s1", messages: list[dict[str, str]] | None = None
) -> dict[str, Any]:
    return {
        "external_id": external_id,
        "title": "T",
        "source_cwd": "/p",
        "created_at": 1.0,
        "updated_at": 2.0,
        "messages": (
            messages
            if messages is not None
            else [
                {"role": "user", "content": "q"},
                {"role": "assistant", "content": "a"},
            ]
        ),
    }


def _request(
    sessions: list[dict[str, Any]],
    source: str = "codex",
    agent_id: str = "",
    agent_name: str = "",
) -> ChatHistoryImportRequest:
    return ChatHistoryImportRequest(
        source=source, agent_id=agent_id, agent_name=agent_name, sessions=sessions
    )


class _FakeStore:
    """Records import calls; optionally fails selected external ids."""

    def __init__(self, fail_ids: set[str] | None = None) -> None:
        self.fail_ids = fail_ids or set()
        self.calls: list[dict[str, Any]] = []
        self.list_calls: list[dict[str, int]] = []

    async def import_session(
        self,
        session_id: str,
        title: str,
        created_at: float,
        updated_at: float,
        preferences: dict[str, Any] | None,
        messages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        external_id = (preferences or {}).get("import", {}).get("external_id", "")
        if external_id in self.fail_ids:
            raise RuntimeError("store exploded")
        self.calls.append(
            {
                "session_id": session_id,
                "title": title,
                "created_at": created_at,
                "updated_at": updated_at,
                "preferences": preferences,
                "messages": messages,
            }
        )
        return {"imported": True, "message_count": len(messages)}

    async def list_imported_sessions(
        self, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        self.list_calls.append({"limit": limit, "offset": offset})
        return [{"id": f"imported_x_{offset}"}]


@pytest.fixture
def store(
    monkeypatch: pytest.MonkeyPatch,
) -> _FakeStore:
    fake = _FakeStore()
    monkeypatch.setattr(imports_router, "get_sqlite_session_store", lambda: fake)
    return fake


# ---------------------------------------------------------------------------
# Request-model contracts (422 at the HTTP layer)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("source", _SOURCES)
def test_all_documented_sources_accepted(source: str) -> None:
    assert _request([], source=source).source == source


def test_blank_source_rejected() -> None:
    with pytest.raises(ValidationError):
        _request([], source="   ")


def test_imported_message_rejects_non_conversation_roles() -> None:
    for role in ("system", "tool", "", "User", "human"):
        with pytest.raises(ValidationError):
            ImportedMessage(role=role, content="x")


def test_imported_message_defaults() -> None:
    msg = ImportedMessage(role="user")
    assert msg.content == ""
    assert msg.created_at is None
    assert msg.metadata == {}


def test_imported_session_external_id_boundaries() -> None:
    with pytest.raises(ValidationError):
        ImportedSession(external_id="", created_at=1.0, updated_at=2.0)
    ok = ImportedSession(external_id="x" * 256, created_at=1.0, updated_at=2.0)
    assert len(ok.external_id) == 256
    with pytest.raises(ValidationError):
        ImportedSession(external_id="x" * 257, created_at=1.0, updated_at=2.0)


def test_imported_session_requires_timestamps_and_defaults_messages() -> None:
    with pytest.raises(ValidationError):
        ImportedSession(external_id="s", created_at=1.0)
    with pytest.raises(ValidationError):
        ImportedSession(external_id="s", updated_at=1.0)
    assert ImportedSession(external_id="s", created_at=1.0, updated_at=2.0).messages == []


@pytest.mark.parametrize("field", ("agent_id", "agent_name"))
def test_agent_fields_max_length_256(field: str) -> None:
    kwargs = {field: "a" * 257}
    with pytest.raises(ValidationError):
        _request([], **kwargs)
    assert _request([], **{field: "a" * 256}).model_dump()[field] == "a" * 256


# ---------------------------------------------------------------------------
# Handler branches against a fake store
# ---------------------------------------------------------------------------


def _run(payload: ChatHistoryImportRequest) -> dict[str, Any]:
    return asyncio.run(import_chat_history(payload))


def test_oversized_request_rejected_with_413(store: _FakeStore) -> None:
    payload = _request(
        [_session(f"s{i}") for i in range(imports_router._MAX_SESSIONS_PER_REQUEST + 1)]
    )
    with pytest.raises(HTTPException) as exc:
        _run(payload)
    assert exc.value.status_code == 413
    assert store.calls == []


def test_request_at_session_ceiling_is_accepted(store: _FakeStore) -> None:
    n = imports_router._MAX_SESSIONS_PER_REQUEST
    res = _run(
        _request([_session(f"s{i}", messages=[{"role": "user", "content": "q"}]) for i in range(n)])
    )
    assert res["imported"] == n
    assert res["skipped"] == 0
    assert len(store.calls) == n


def test_oversized_session_is_truncated_to_ceiling(store: _FakeStore) -> None:
    ceiling = imports_router._MAX_MESSAGES_PER_SESSION
    messages = [{"role": "user", "content": "q"}] * (ceiling + 5)
    res = _run(_request([_session("big", messages=messages)]))
    assert res["imported"] == 1
    truncated = store.calls[0]["messages"]
    assert len(truncated) == ceiling
    assert truncated[0]["role"] == "user" and truncated[-1]["content"] == "q"
    assert res["sessions"][0]["message_count"] == ceiling


def test_store_failure_marks_session_error_and_keeps_going(store: _FakeStore) -> None:
    store.fail_ids = {"bad"}
    res = _run(
        _request([_session("bad"), _session("good", messages=[{"role": "user", "content": "q"}])])
    )
    assert res["imported"] == 1
    assert res["skipped"] == 1
    by_id = {r["external_id"]: r for r in res["sessions"]}
    assert by_id["bad"] == {"external_id": "bad", "imported": False, "reason": "error"}
    assert by_id["good"]["imported"] is True
    assert len(store.calls) == 1
    assert store.calls[0]["preferences"]["import"]["external_id"] == "good"


def test_contentless_session_reports_empty_without_store_write(store: _FakeStore) -> None:
    res = _run(_request([_session("hollow", messages=[{"role": "assistant", "content": "\n\t"}])]))
    assert res["sessions"] == [{"external_id": "hollow", "imported": False, "reason": "empty"}]
    assert res["imported"] == 0 and res["skipped"] == 1
    assert store.calls == []


def test_store_receives_deterministic_imported_id_and_metadata(store: _FakeStore) -> None:
    call = _run(
        _request(
            [_session("cli-1", messages=[{"role": "user", "content": "q"}])],
            source="claude_code",
            agent_id="a1",
            agent_name="Agent",
        )
    )
    assert call["imported"] == 1
    recorded = store.calls[0]
    assert recorded["session_id"] == make_imported_session_id("claude_code", "cli-1")
    assert recorded["session_id"].startswith("imported_")
    assert recorded["session_id"] == make_imported_session_id("claude_code", "cli-1")
    assert recorded["title"] == "T"
    assert recorded["created_at"] == 1.0
    assert recorded["updated_at"] == 2.0
    meta = recorded["preferences"]["import"]
    assert meta == {
        "source": "claude_code",
        "source_cwd": "/p",
        "external_id": "cli-1",
        "agent_id": "a1",
        "agent_name": "Agent",
    }


def test_empty_agent_fields_omitted_from_import_meta(store: _FakeStore) -> None:
    _run(_request([_session("s9", messages=[{"role": "user", "content": "q"}])]))
    meta = store.calls[0]["preferences"]["import"]
    assert "agent_id" not in meta and "agent_name" not in meta


# ---------------------------------------------------------------------------
# HTTP surface: 4xx and query bounds via an in-process TestClient
# ---------------------------------------------------------------------------


@pytest.fixture
def client(store: _FakeStore) -> TestClient:
    app = FastAPI()
    app.include_router(imports_router.router)
    return TestClient(app)


def test_http_post_valid_import_returns_counts(client: TestClient) -> None:
    resp = client.post("/chat-history", json={"source": "codex", "sessions": [_session()]})
    assert resp.status_code == 200
    assert resp.json() == {
        "imported": 1,
        "skipped": 0,
        "sessions": [{"external_id": "s1", "imported": True, "message_count": 2}],
    }


def test_http_post_rejects_unknown_source_with_422(client: TestClient) -> None:
    resp = client.post("/chat-history", json={"source": "opencode", "sessions": [_session()]})
    assert resp.status_code == 422


def test_http_post_rejects_empty_sessions_with_400(client: TestClient) -> None:
    resp = client.post("/chat-history", json={"source": "codex", "sessions": []})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "No sessions to import"


def test_http_post_oversized_request_rejected_with_413(client: TestClient) -> None:
    n = imports_router._MAX_SESSIONS_PER_REQUEST + 1
    resp = client.post(
        "/chat-history",
        json={
            "source": "codex",
            "sessions": [
                _session(f"s{i}", messages=[{"role": "user", "content": "q"}]) for i in range(n)
            ],
        },
    )
    assert resp.status_code == 413
    assert "max" in resp.json()["detail"]


def test_http_get_query_bounds_enforced(client: TestClient) -> None:
    assert client.get("/chat-history", params={"limit": 0}).status_code == 422
    assert client.get("/chat-history", params={"limit": 201}).status_code == 422
    assert client.get("/chat-history", params={"offset": -1}).status_code == 422


def test_http_get_passes_paging_to_store(client: TestClient, store: _FakeStore) -> None:
    resp = client.get("/chat-history", params={"limit": 5, "offset": 10})
    assert resp.status_code == 200
    assert store.list_calls == [{"limit": 5, "offset": 10}]
    assert resp.json() == {"sessions": [{"id": "imported_x_10"}]}


def test_http_get_defaults_limit_50_offset_0(client: TestClient, store: _FakeStore) -> None:
    assert client.get("/chat-history").status_code == 200
    assert store.list_calls == [{"limit": 50, "offset": 0}]
