"""Contract + failure-branch tests for the subagents router.

Complements tests/api/test_subagents_router.py: this file pins the request-model
validation (422), the blank/whitespace and boundary 4xx paths, the stale-kind
and non-local sync rejections, the streamed-run failure branch, and the fresh
(no chat session id) message path. Same isolation as the sibling file: a fake
KB manager, a stubbed detector/registry, and temp paths for every persisted
file, so no real CLI, credential, or network is touched.
"""

from __future__ import annotations

import importlib
import json

import pytest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover - optional dependency in lightweight envs
    FastAPI = None
    TestClient = None

pytestmark = pytest.mark.skipif(
    FastAPI is None or TestClient is None, reason="fastapi not installed"
)

if FastAPI is not None and TestClient is not None:
    subagents_module = importlib.import_module("deeptutor.api.routers.subagents")
else:  # pragma: no cover
    subagents_module = None


class _FakeKBManager:
    def __init__(self) -> None:
        self.kbs: dict[str, dict] = {}

    def list_knowledge_bases(self) -> list[str]:
        return sorted(self.kbs)

    def get_metadata(self, name: str | None = None) -> dict:
        return dict(self.kbs.get(name or "", {}))

    def register_subagent_connection(
        self, name, agent_kind, *, cwd="", partner_id="", description=""
    ):
        if name in self.kbs:
            raise ValueError(f"A knowledge base named '{name}' already exists.")
        entry = {
            "path": name,
            "type": "subagent",
            "agent_kind": agent_kind,
            "cwd": cwd,
            "partner_id": partner_id,
            "description": description or f"Connected subagent: {name}",
        }
        self.kbs[name] = entry
        return entry

    def delete_knowledge_base(self, name, confirm=False):
        self.kbs.pop(name, None)
        return True


@pytest.fixture
def client(monkeypatch, tmp_path):
    manager = _FakeKBManager()
    monkeypatch.setattr(subagents_module, "account_kb_manager", lambda: manager)
    monkeypatch.setattr(
        subagents_module,
        "list_backend_kinds",
        lambda: ["claude_code", "codex", "grok", "hermes_remote", "partner"],
    )
    monkeypatch.setattr(subagents_module, "assert_path_allowed", lambda p: p)
    monkeypatch.setattr(
        "deeptutor.services.subagent.config._settings_path",
        lambda: tmp_path / "subagent.json",
    )
    monkeypatch.setattr(
        "deeptutor.services.subagent.sessions._path",
        lambda: tmp_path / "sessions.json",
    )
    monkeypatch.setattr(subagents_module, "detect_all", lambda: _empty_detect())

    app = FastAPI()
    app.include_router(subagents_module.router, prefix="/api/subagents")
    app.dependency_overrides[subagents_module.require_admin] = lambda: None
    return TestClient(app)


async def _empty_detect():
    return []


def test_connect_missing_required_fields_is_422(client):
    # ConnectSubagentRequest: name and agent_kind are required (cwd defaults to "").
    assert client.post("/api/subagents/connections", json={}).status_code == 422
    assert (
        client.post("/api/subagents/connections", json={"name": "OnlyName"}).status_code == 422
    )
    assert (
        client.post("/api/subagents/connections", json={"agent_kind": "codex"}).status_code
        == 422
    )
    assert client.get("/api/subagents/connections").json()["connections"] == []


def test_connect_blank_name_or_kind_is_400(client):
    res = client.post(
        "/api/subagents/connections", json={"name": "   ", "agent_kind": "codex"}
    )
    assert res.status_code == 400
    assert res.json()["detail"] == "Both name and agent_kind are required."

    res = client.post(
        "/api/subagents/connections", json={"name": "MyCodex", "agent_kind": "  "}
    )
    assert res.status_code == 400
    assert res.json()["detail"] == "Both name and agent_kind are required."
    assert client.get("/api/subagents/connections").json()["connections"] == []


def test_connect_unknown_kind_returns_400_with_detail(client):
    res = client.post(
        "/api/subagents/connections", json={"name": "X", "agent_kind": "bogus"}
    )
    assert res.status_code == 400
    assert "Unknown agent kind" in res.json()["detail"]


def test_connect_rejects_cwd_outside_allowed_paths(client, monkeypatch):
    def deny(_p):
        raise ValueError("path is outside the allowed roots: /etc")

    monkeypatch.setattr(subagents_module, "assert_path_allowed", deny)
    res = client.post(
        "/api/subagents/connections",
        json={"name": "MyClaude", "agent_kind": "claude_code", "cwd": "/etc"},
    )
    assert res.status_code == 400
    assert "outside the allowed roots" in res.json()["detail"]
    assert client.get("/api/subagents/connections").json()["connections"] == []


def test_connect_duplicate_name_is_400(client):
    first = client.post(
        "/api/subagents/connections", json={"name": "Dup", "agent_kind": "codex"}
    )
    assert first.status_code == 200

    second = client.post(
        "/api/subagents/connections", json={"name": "Dup", "agent_kind": "grok"}
    )
    assert second.status_code == 400
    assert "already exists" in second.json()["detail"]
    # The original connection is untouched by the rejected re-registration.
    listed = client.get("/api/subagents/connections").json()["connections"]
    assert [c["name"] for c in listed] == ["Dup"]
    assert listed[0]["agent_kind"] == "codex"


def test_message_missing_message_field_is_422(client):
    client.post(
        "/api/subagents/connections", json={"name": "MyClaude", "agent_kind": "claude_code"}
    )
    assert (
        client.post("/api/subagents/connections/MyClaude/message", json={}).status_code
        == 422
    )


def test_message_blank_message_is_400(client):
    client.post(
        "/api/subagents/connections", json={"name": "MyClaude", "agent_kind": "claude_code"}
    )
    res = client.post(
        "/api/subagents/connections/MyClaude/message", json={"message": "   "}
    )
    assert res.status_code == 400
    assert res.json()["detail"] == "A non-empty 'message' is required."


def test_message_with_stale_stored_kind_is_400(client, monkeypatch):
    # Simulate a stored connection whose agent_kind no longer resolves to a
    # backend (the API itself rejects unknown kinds at connect time, so the row
    # is planted directly in the manager).
    stale_rows = {"MyClaude": {"type": "subagent", "agent_kind": "ghost_kind", "cwd": ""}}
    monkeypatch.setattr(
        subagents_module, "account_kb_manager", lambda: _StaticKBManager(stale_rows)
    )
    monkeypatch.setattr("deeptutor.services.subagent.get_backend", lambda kind: None)

    res = client.post(
        "/api/subagents/connections/MyClaude/message", json={"message": "hi"}
    )
    assert res.status_code == 400
    assert "Unknown agent kind" in res.json()["detail"]


class _StaticKBManager:
    """Read-only KB manager exposing fixed metadata rows."""

    def __init__(self, kbs: dict[str, dict]) -> None:
        self.kbs = kbs

    def list_knowledge_bases(self) -> list[str]:
        return sorted(self.kbs)

    def get_metadata(self, name: str | None = None) -> dict:
        return dict(self.kbs.get(name or "", {}))


def test_message_stream_reports_backend_failure(client, monkeypatch):
    client.post(
        "/api/subagents/connections", json={"name": "MyClaude", "agent_kind": "claude_code"}
    )

    from deeptutor.services.subagent.types import ConsultResult, SubagentEvent

    class _FailingBackend:
        kind = "claude_code"

        async def consult(
            self, message, *, on_event, cwd, session_id, config, images=None, partner_id=None
        ):
            await on_event(SubagentEvent(kind="text", text="starting"))
            raise RuntimeError("cli crashed")

    monkeypatch.setattr(
        "deeptutor.services.subagent.get_backend", lambda kind: _FailingBackend()
    )

    res = client.post(
        "/api/subagents/connections/MyClaude/message",
        json={"chat_session_id": "chatF", "message": "hello"},
    )
    assert res.status_code == 200
    lines = [json.loads(line) for line in res.text.splitlines() if line.strip()]
    assert lines[0] == {"channel": "user_question", "text": "hello"}
    # The streamed event that arrived before the crash is relayed…
    assert any(line.get("channel") == "text" and line.get("text") == "starting" for line in lines)
    # …then the failure surfaces as an error channel plus an unsuccessful done.
    assert {"channel": "error", "text": "cli crashed"} in lines
    assert lines[-1] == {"done": True, "success": False}


def test_message_without_chat_session_id_runs_fresh(client, monkeypatch, tmp_path):
    client.post(
        "/api/subagents/connections", json={"name": "MyClaude", "agent_kind": "claude_code"}
    )

    from deeptutor.services.subagent.types import ConsultResult, SubagentEvent

    class _FreshBackend:
        kind = "claude_code"

        async def consult(
            self, message, *, on_event, cwd, session_id, config, images=None, partner_id=None
        ):
            assert session_id is None, "a fresh run must not resume a remembered session"
            assert cwd is None, "an unconfigured connection passes no cwd"
            await on_event(SubagentEvent(kind="text", text="fresh hello"))
            return ConsultResult(
                final_text="fresh hello", session_id="fresh-1", success=True, event_count=1
            )

    monkeypatch.setattr(
        "deeptutor.services.subagent.get_backend", lambda kind: _FreshBackend()
    )

    res = client.post(
        "/api/subagents/connections/MyClaude/message", json={"message": "hello"}
    )
    assert res.status_code == 200
    lines = [json.loads(line) for line in res.text.splitlines() if line.strip()]
    assert lines[0] == {"channel": "user_question", "text": "hello"}
    # Events without a merge id are relayed verbatim (no namespacing key).
    assert {"channel": "text", "text": "fresh hello"} in lines
    assert lines[-1] == {"done": True, "success": True, "session_id": "fresh-1"}
    # Without a chat session id nothing is persisted for later turns.
    assert not (tmp_path / "sessions.json").exists()


def test_sync_rejects_remote_backend_kind(client, monkeypatch):
    class _RemoteBackend:
        local_cli = False

    monkeypatch.setattr(
        "deeptutor.services.subagent.get_backend", lambda kind: _RemoteBackend()
    )
    res = client.post("/api/subagents/backends/hermes_remote/sync")
    assert res.status_code == 400
    assert "Unknown agent kind" in res.json()["detail"]


def test_detect_returns_empty_backend_list(client):
    res = client.get("/api/subagents/detect")
    assert res.status_code == 200
    assert res.json() == {"backends": []}
