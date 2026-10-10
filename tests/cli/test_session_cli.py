"""CLI tests for ``deeptutor session`` commands (list/show/open/delete/rename)."""

from __future__ import annotations

import json
from typing import Any

from typer.testing import CliRunner

from deeptutor_cli.chat import ChatState
from deeptutor_cli.main import app

runner = CliRunner()


def _patch_session_store(monkeypatch, sessions: list[dict[str, Any]] | None = None):
    """Replace the DeepTutorApp session API with an in-memory fake.

    Returns the list of recorded ``(method, args, kwargs)`` calls so tests
    can assert argument forwarding.
    """
    store: dict[str, dict[str, Any]] = {
        str(session["id"]): dict(session) for session in (sessions or [])
    }
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def _list_sessions(self, limit: int = 50, offset: int = 0):  # noqa: ANN001
        calls.append(("list_sessions", (), {"limit": limit, "offset": offset}))
        return [dict(s) for s in list(store.values())[offset : offset + limit]]

    async def _get_session(self, session_id: str):  # noqa: ANN001
        calls.append(("get_session", (session_id,), {}))
        session = store.get(session_id)
        return dict(session) if session is not None else None

    async def _delete_session(self, session_id: str) -> bool:  # noqa: ANN001
        calls.append(("delete_session", (session_id,), {}))
        return store.pop(session_id, None) is not None

    async def _rename_session(self, session_id: str, title: str) -> bool:  # noqa: ANN001
        calls.append(("rename_session", (session_id,), {"title": title}))
        if session_id not in store:
            return False
        store[session_id]["title"] = title
        return True

    from deeptutor.app import facade

    monkeypatch.setattr(facade.DeepTutorApp, "list_sessions", _list_sessions)
    monkeypatch.setattr(facade.DeepTutorApp, "get_session", _get_session)
    monkeypatch.setattr(facade.DeepTutorApp, "delete_session", _delete_session)
    monkeypatch.setattr(facade.DeepTutorApp, "rename_session", _rename_session)
    return calls


def _sample_session(**overrides: Any) -> dict[str, Any]:
    session: dict[str, Any] = {
        "id": "sess-1",
        "title": "Photosynthesis",
        "capability": "chat",
        "status": "completed",
        "messages": [
            {"role": "user", "content": "How do plants use light?"},
            {"role": "assistant", "content": "Through photosynthesis."},
        ],
    }
    session.update(overrides)
    return session


def test_session_list_forwards_limit_to_store(monkeypatch) -> None:
    calls = _patch_session_store(
        monkeypatch,
        sessions=[
            _sample_session(id="sess-1", title="First"),
            _sample_session(id="sess-2", title="Second"),
        ],
    )

    result = runner.invoke(app, ["session", "list", "--limit", "1"])

    assert result.exit_code == 0, result.output
    assert calls == [
        ("list_sessions", (), {"limit": 1, "offset": 0}),
    ]
    assert "sess-1" in result.output
    assert "sess-2" not in result.output


def test_session_show_rich_renders_title_and_messages(monkeypatch) -> None:
    _patch_session_store(monkeypatch, sessions=[_sample_session()])

    result = runner.invoke(app, ["session", "show", "sess-1"])

    assert result.exit_code == 0, result.output
    assert "Photosynthesis" in result.output
    assert "sess-1" in result.output
    assert "capability=chat" in result.output
    assert "status=completed" in result.output
    assert "messages=2" in result.output
    assert "USER" in result.output
    assert "How do plants use light?" in result.output
    assert "ASSISTANT" in result.output
    assert "Through photosynthesis." in result.output


def test_session_show_json_outputs_parseable_payload(monkeypatch) -> None:
    session = _sample_session()
    _patch_session_store(monkeypatch, sessions=[session])

    result = runner.invoke(app, ["session", "show", "sess-1", "--format", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload == session


def test_session_show_missing_session_exits_one(monkeypatch) -> None:
    _patch_session_store(monkeypatch, sessions=[])

    result = runner.invoke(app, ["session", "show", "sess-missing"])

    assert result.exit_code == 1
    assert "Session not found" in result.output
    assert "sess-missing" in result.output


def test_session_open_forwards_chat_state_into_repl(monkeypatch) -> None:
    captured: list[ChatState] = []

    async def _fake_chat_repl(state: ChatState) -> None:  # noqa: ANN001
        captured.append(state)

    monkeypatch.setattr("deeptutor_cli.session_cmd._chat_repl", _fake_chat_repl)

    result = runner.invoke(app, ["session", "open", "sess-42"])

    assert result.exit_code == 0, result.output
    assert len(captured) == 1
    assert isinstance(captured[0], ChatState)
    assert captured[0].session_id == "sess-42"
    assert captured[0].capability == "chat"


def test_session_delete_success_reports_confirmation(monkeypatch) -> None:
    calls = _patch_session_store(monkeypatch, sessions=[_sample_session()])

    result = runner.invoke(app, ["session", "delete", "sess-1"])

    assert result.exit_code == 0, result.output
    assert "Deleted session sess-1" in result.output
    assert ("delete_session", ("sess-1",), {}) in calls


def test_session_delete_missing_session_exits_one(monkeypatch) -> None:
    _patch_session_store(monkeypatch, sessions=[])

    result = runner.invoke(app, ["session", "delete", "sess-missing"])

    assert result.exit_code == 1
    assert "Session not found" in result.output


def test_session_rename_success_reports_new_title(monkeypatch) -> None:
    sessions = [_sample_session()]
    calls = _patch_session_store(monkeypatch, sessions=sessions)

    result = runner.invoke(app, ["session", "rename", "sess-1", "--title", "New Title"])

    assert result.exit_code == 0, result.output
    assert "Renamed sess-1 -> New Title" in result.output
    assert ("rename_session", ("sess-1",), {"title": "New Title"}) in calls


def test_session_rename_missing_session_exits_one(monkeypatch) -> None:
    _patch_session_store(monkeypatch, sessions=[])

    result = runner.invoke(app, ["session", "rename", "sess-missing", "--title", "Nope"])

    assert result.exit_code == 1
    assert "Session not found" in result.output
