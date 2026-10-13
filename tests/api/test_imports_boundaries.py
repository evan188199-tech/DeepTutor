"""Boundary tests for the chat-history import router and its sqlite writes.

Covers the export-import parity suggestion axis 3 (imports.py + sqlite_store):
message-ceiling truncation observability, message metadata passthrough,
``created_at`` fallback, title secondary truncation, empty agent attribution,
and ``GET /chat-history`` limit/offset validation.

Exercised through ``TestClient`` against a minimal app that mounts only the
imports router, with the per-user store factory monkeypatched to a tmp
database — no server process is started.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import imports as imports_router
from deeptutor.services.session.sqlite_store import SQLiteSessionStore, make_imported_session_id

DEFAULT_LIST_URL = "/api/imports/chat-history"


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SQLiteSessionStore:
    instance = SQLiteSessionStore(db_path=tmp_path / "test.db")
    monkeypatch.setattr(imports_router, "get_sqlite_session_store", lambda: instance)
    return instance


@pytest.fixture
def client(store: SQLiteSessionStore) -> TestClient:
    app = FastAPI()
    app.include_router(imports_router.router, prefix="/api/imports")
    return TestClient(app)


def _session_payload(
    external_id: str = "s1",
    title: str = "T",
    created_at: float = 7.0,
    updated_at: float = 8.0,
    messages: list[dict] | None = None,
) -> dict:
    return {
        "external_id": external_id,
        "title": title,
        "source_cwd": "/p",
        "created_at": created_at,
        "updated_at": updated_at,
        "messages": messages
        if messages is not None
        else [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "a"},
        ],
    }


def _post_session(
    client: TestClient,
    session: dict,
    agent_id: str = "",
    agent_name: str = "",
) -> dict:
    response = client.post(
        "/api/imports/chat-history",
        json={
            "source": "codex",
            "agent_id": agent_id,
            "agent_name": agent_name,
            "sessions": [session],
        },
    )
    assert response.status_code == 200
    return response.json()


def _stored_messages(store: SQLiteSessionStore, external_id: str) -> list[dict]:
    session_id = make_imported_session_id("codex", external_id)
    return asyncio.run(store.get_messages(session_id))


def test_message_ceiling_truncation_is_observable_in_result(
    client: TestClient, store: SQLiteSessionStore
) -> None:
    messages = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i:05d}"}
        for i in range(10001)
    ]
    body = _post_session(client, _session_payload(external_id="big", messages=messages))

    assert body["imported"] == 1
    assert body["skipped"] == 0
    assert body["sessions"][0]["external_id"] == "big"
    assert body["sessions"][0]["imported"] is True
    assert body["sessions"][0]["message_count"] == 10000

    stored = _stored_messages(store, "big")
    assert len(stored) == 10000
    assert stored[0]["content"] == "m00000"
    assert stored[-1]["content"] == "m09999"


def test_message_metadata_is_persisted_into_store(
    client: TestClient, store: SQLiteSessionStore
) -> None:
    messages = [
        {
            "role": "user",
            "content": "with meta",
            "metadata": {"had_images": True, "origin": "claude_code"},
        },
        {"role": "assistant", "content": "no meta"},
    ]
    body = _post_session(client, _session_payload(messages=messages))

    assert body["imported"] == 1
    stored = _stored_messages(store, "s1")
    assert stored[0]["metadata"] == {"had_images": True, "origin": "claude_code"}
    assert stored[1]["metadata"] == {}


def test_message_created_at_zero_falls_back_to_session_created_at(
    client: TestClient, store: SQLiteSessionStore
) -> None:
    messages = [
        {"role": "user", "content": "q", "created_at": 0.0},
        {"role": "assistant", "content": "a", "created_at": 7.5},
    ]
    _post_session(client, _session_payload(created_at=7.0, messages=messages))

    stored = _stored_messages(store, "s1")
    assert stored[0]["created_at"] == 7.0
    assert stored[1]["created_at"] == 7.5


def test_message_created_at_missing_falls_back_to_session_created_at(
    client: TestClient, store: SQLiteSessionStore
) -> None:
    messages = [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "a", "created_at": None},
    ]
    _post_session(client, _session_payload(created_at=7.0, messages=messages))

    stored = _stored_messages(store, "s1")
    assert stored[0]["created_at"] == 7.0
    assert stored[1]["created_at"] == 7.0


def test_title_of_101_chars_is_truncated_to_100(client: TestClient) -> None:
    title = "x" * 101
    body = _post_session(client, _session_payload(title=title))

    assert body["imported"] == 1
    listed = client.get(DEFAULT_LIST_URL, params={"limit": 50}).json()
    assert listed["sessions"][0]["title"] == "x" * 100
    assert len(listed["sessions"][0]["title"]) == 100


def test_title_of_150_chars_keeps_only_first_100(client: TestClient) -> None:
    title = "abcdefghij" * 15
    _post_session(client, _session_payload(title=title))

    listed = client.get(DEFAULT_LIST_URL, params={"limit": 50}).json()
    assert listed["sessions"][0]["title"] == title[:100]


def test_blank_title_falls_back_to_default_label(client: TestClient) -> None:
    _post_session(client, _session_payload(title="   "))

    listed = client.get(DEFAULT_LIST_URL, params={"limit": 50}).json()
    assert listed["sessions"][0]["title"] == "Imported conversation"


def test_empty_agent_fields_are_omitted_from_import_meta(client: TestClient) -> None:
    body = _post_session(client, _session_payload(), agent_id="", agent_name="")

    assert body["imported"] == 1
    listed = client.get(DEFAULT_LIST_URL, params={"limit": 50}).json()
    meta = listed["sessions"][0]["preferences"]["import"]
    assert set(meta) == {"source", "source_cwd", "external_id"}
    assert "agent_id" not in meta
    assert "agent_name" not in meta


def test_partial_agent_fields_only_nonempty_persisted(client: TestClient) -> None:
    _post_session(client, _session_payload(), agent_id="codex-a1", agent_name="")

    listed = client.get(DEFAULT_LIST_URL, params={"limit": 50}).json()
    meta = listed["sessions"][0]["preferences"]["import"]
    assert meta["agent_id"] == "codex-a1"
    assert "agent_name" not in meta


def test_list_rejects_out_of_range_limit_and_offset(client: TestClient) -> None:
    assert client.get(DEFAULT_LIST_URL, params={"limit": 0}).status_code == 422
    assert client.get(DEFAULT_LIST_URL, params={"limit": 201}).status_code == 422
    assert client.get(DEFAULT_LIST_URL, params={"offset": -1}).status_code == 422
    assert client.get(DEFAULT_LIST_URL, params={"limit": 1.5}).status_code == 422


def test_list_limit_upper_bound_offset_paging_and_empty_page(
    client: TestClient,
) -> None:
    for index, updated_at in ((1, 10.0), (2, 20.0), (3, 30.0)):
        body = _post_session(
            client,
            _session_payload(external_id=f"page{index}", updated_at=updated_at),
        )
        assert body["imported"] == 1

    def external_ids(sessions: list[dict]) -> list[str]:
        return [s["preferences"]["import"]["external_id"] for s in sessions]

    first_page = client.get(DEFAULT_LIST_URL, params={"limit": 2}).json()["sessions"]
    assert external_ids(first_page) == ["page3", "page2"]

    second_page = client.get(
        DEFAULT_LIST_URL, params={"limit": 2, "offset": 2}
    ).json()["sessions"]
    assert external_ids(second_page) == ["page1"]

    beyond = client.get(DEFAULT_LIST_URL, params={"limit": 2, "offset": 9}).json()
    assert beyond["sessions"] == []

    upper = client.get(DEFAULT_LIST_URL, params={"limit": 200})
    assert upper.status_code == 200
    assert len(upper.json()["sessions"]) == 3
