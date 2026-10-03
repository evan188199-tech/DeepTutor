"""The quiz-judge WebSocket funnels every exit through ``_teardown``.

These tests pin the properties the handler relies on: teardown is
idempotent per connection, tolerant of close/reset failures (which must
leave a debug trace, not raise), skipped for anonymous sockets, and
wired into each error path plus the streaming ``finally``.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor.api.routers import auth, quiz_judge
from deeptutor.multi_user import context as user_context


class _FakeWebSocket:
    """Mimics Starlette: closing an already-closed socket raises."""

    def __init__(self) -> None:
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1
        if self.close_calls > 1:
            raise RuntimeError("Cannot send on a closed websocket")


def test_teardown_is_idempotent(monkeypatch) -> None:
    websocket = _FakeWebSocket()
    resets: list[object] = []
    monkeypatch.setattr(user_context, "reset_current_user", resets.append)

    asyncio.run(quiz_judge._teardown(websocket, "token-1"))  # type: ignore[arg-type]
    asyncio.run(quiz_judge._teardown(websocket, "token-1"))  # type: ignore[arg-type]

    assert websocket.close_calls == 1
    assert resets == ["token-1"]


def test_teardown_survives_close_and_reset_failures(monkeypatch, caplog) -> None:
    websocket = _FakeWebSocket()
    websocket.close_calls = 1  # first close() call raises like an already-dead socket

    def _explode(_token: object) -> None:
        raise ValueError("context already reset")

    monkeypatch.setattr(user_context, "reset_current_user", _explode)

    with caplog.at_level(logging.DEBUG, logger="deeptutor.api.routers.quiz_judge"):
        asyncio.run(quiz_judge._teardown(websocket, "token-1"))  # type: ignore[arg-type]

    assert websocket.close_calls == 2  # reset is still attempted after close fails
    debug_messages = [record.message for record in caplog.records]
    assert any("closing websocket" in message for message in debug_messages)
    assert any("resetting user context" in message for message in debug_messages)


def test_teardown_without_token_skips_reset(monkeypatch) -> None:
    websocket = _FakeWebSocket()
    resets: list[object] = []
    monkeypatch.setattr(user_context, "reset_current_user", resets.append)

    asyncio.run(quiz_judge._teardown(websocket, None))

    assert websocket.close_calls == 1
    assert resets == []


def _judge_client(monkeypatch, *, token: str | None, resets: list[object]) -> TestClient:
    async def allow(_websocket):
        return token

    monkeypatch.setattr(auth, "ws_require_auth", allow)
    monkeypatch.setattr(user_context, "reset_current_user", resets.append)
    app = FastAPI()
    app.include_router(quiz_judge.router, prefix="/ws")
    return TestClient(app)


def test_invalid_request_error_path_runs_teardown_once(monkeypatch) -> None:
    resets: list[object] = []
    client = _judge_client(monkeypatch, token="tok-1", resets=resets)

    with client.websocket_connect("/ws/questions/judge") as websocket:
        websocket.send_text("{not json")
        frame = websocket.receive_json()

    assert frame["type"] == "error"
    assert "Invalid request" in frame["content"]
    assert resets == ["tok-1"]


def test_missing_question_error_path_runs_teardown_once(monkeypatch) -> None:
    resets: list[object] = []
    client = _judge_client(monkeypatch, token="tok-1", resets=resets)

    with client.websocket_connect("/ws/questions/judge") as websocket:
        websocket.send_json({"user_answer": "an answer", "language": "en"})
        frame = websocket.receive_json()

    assert frame == {"type": "error", "content": "Question is required"}
    assert resets == ["tok-1"]


def test_empty_answer_error_path_runs_teardown_once(monkeypatch) -> None:
    resets: list[object] = []
    client = _judge_client(monkeypatch, token="tok-1", resets=resets)

    with client.websocket_connect("/ws/questions/judge") as websocket:
        websocket.send_json({"question": "What is 1+1?", "user_answer": "", "language": "en"})
        frame = websocket.receive_json()

    assert frame["type"] == "error"
    assert "No answer to judge" in frame["content"]
    assert resets == ["tok-1"]


def test_streaming_path_runs_teardown_in_finally(monkeypatch) -> None:
    resets: list[object] = []

    async def fake_stream(*, prompt: str, system_prompt: str, **_kwargs):
        for chunk in ("partial", " judgment"):
            yield chunk

    monkeypatch.setattr(quiz_judge, "llm_stream", fake_stream)
    client = _judge_client(monkeypatch, token="tok-1", resets=resets)

    with client.websocket_connect("/ws/questions/judge") as websocket:
        websocket.send_json({"question": "What is 1+1?", "user_answer": "2", "language": "en"})
        frames = []
        while True:
            frame = websocket.receive_json()
            frames.append(frame)
            if frame["type"] == "done":
                break

    assert [frame["type"] for frame in frames] == ["started", "text", "text", "done"]
    assert "".join(frame["content"] for frame in frames[1:-1]) == "partial judgment"
    assert resets == ["tok-1"]
