from __future__ import annotations

from datetime import datetime, timedelta
import json
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocket, WebSocketDisconnect

from deeptutor.api.routers import auth
from deeptutor.api.routers import knowledge as knowledge_router
from deeptutor.api.utils.progress_broadcaster import ProgressBroadcaster
from deeptutor.multi_user import context as multi_user_context

_PROGRESS_WS_LOGGER = "deeptutor.api.routers.knowledge"


def _client(monkeypatch, base_dir: Path, token: str | None = None) -> TestClient:
    async def allow(_websocket):
        return token

    monkeypatch.setattr(auth, "ws_require_auth", allow)
    monkeypatch.setattr(knowledge_router, "_current_kb_base_dir", lambda: base_dir)
    app = FastAPI()
    app.include_router(knowledge_router.ws_router, prefix="/ws")
    return TestClient(app)


def _write_progress(base_dir: Path, payload: dict) -> None:
    kb_dir = base_dir / "kb"
    kb_dir.mkdir(parents=True, exist_ok=True)
    (kb_dir / ".progress.json").write_text(json.dumps(payload), encoding="utf-8")


def test_completed_progress_is_replayed_for_expected_task(monkeypatch, tmp_path: Path) -> None:
    base_dir = tmp_path / "knowledge_bases"
    _write_progress(
        base_dir,
        {
            "task_id": "completed-task",
            "stage": "completed",
            "message": "done",
            "progress_percent": 100,
            "timestamp": "2026-09-02T00:00:00",
        },
    )

    with _client(monkeypatch, base_dir).websocket_connect(
        "/ws/knowledge-bases/kb/progress?task_id=completed-task"
    ) as websocket:
        frame = websocket.receive_json()

    assert frame["type"] == "progress"
    assert frame["data"]["stage"] == "completed"
    assert frame["data"]["task_id"] == "completed-task"


def test_orphaned_live_progress_becomes_retryable_error(monkeypatch, tmp_path: Path) -> None:
    base_dir = tmp_path / "knowledge_bases"
    _write_progress(
        base_dir,
        {
            "task_id": "orphaned-after-restart",
            "stage": "processing_documents",
            "message": "working",
            "progress_percent": 40,
            "timestamp": "2026-09-02T00:00:00",
        },
    )

    with _client(monkeypatch, base_dir).websocket_connect(
        "/ws/knowledge-bases/kb/progress?task_id=orphaned-after-restart"
    ) as websocket:
        frame = websocket.receive_json()

    assert frame["type"] == "progress"
    assert frame["data"]["stage"] == "error"
    assert frame["data"]["error_code"] == "knowledge_task_interrupted"
    assert frame["data"]["retryable"] is True

    persisted = json.loads((base_dir / "kb" / ".progress.json").read_text(encoding="utf-8"))
    assert persisted["stage"] == "error"
    assert persisted["task_id"] == "orphaned-after-restart"


# ---------------------------------------------------------------------------
# DT-22 HIGH regression: websocket_progress error paths (evidence report
# §2/§7, agent/dt22-todo-scan). Evidence line numbers drifted; current sites
# on origin/main @ ef2d9e5c3 are knowledge.py:4353 (stale-check timestamp),
# :4402 (freshness timestamp), :4480 (error push), :4486 (close), :4491
# (user reset). Each test pins the designed-degradation contract for one
# HIGH site: the swallowed handler must degrade deterministically without
# crashing, hanging, or leaking the broadcaster subscription / user context.
# The underlying silent handlers are still unfixed upstream, so these tests
# assert the degradation contract only; the missing per-site observability
# (warning-level surfacing) is recorded as a current-state exemption in the
# card comment, not asserted here.
# ---------------------------------------------------------------------------


def test_malformed_progress_timestamp_still_settles_connection(monkeypatch, tmp_path: Path) -> None:
    """Site knowledge.py:4353 — an unparseable ``timestamp`` in the stored
    progress raises inside the stale-check and is swallowed. Designed
    degradation: treat activity as unknown (not active), settle the socket
    on the fast path with the last-known state, and clean up."""
    base_dir = tmp_path / "knowledge_bases"
    _write_progress(
        base_dir,
        {
            "stage": "indexing",
            "message": "working",
            "progress_percent": 40,
            "timestamp": "not-a-timestamp",
        },
    )

    with _client(monkeypatch, base_dir).websocket_connect(
        "/ws/knowledge-bases/kb/progress"
    ) as websocket:
        frame = websocket.receive_json()

    assert frame["type"] == "progress"
    assert frame["data"]["stage"] == "indexing"
    assert ProgressBroadcaster.get_instance().get_connection_count("kb") == 0


def test_stale_progress_timestamp_is_treated_as_not_active(monkeypatch, tmp_path: Path) -> None:
    """Site knowledge.py:4353 — the stale half: a valid but older-than-120s
    timestamp on a non-terminal stage must not wedge the connection into the
    polling loop; the endpoint settles via the fast path."""
    base_dir = tmp_path / "knowledge_bases"
    _write_progress(
        base_dir,
        {
            "stage": "indexing",
            "message": "working",
            "progress_percent": 40,
            "timestamp": (datetime.now() - timedelta(minutes=10)).isoformat(),
        },
    )

    with _client(monkeypatch, base_dir).websocket_connect(
        "/ws/knowledge-bases/kb/progress"
    ) as websocket:
        frame = websocket.receive_json()

    assert frame["type"] == "progress"
    assert frame["data"]["stage"] == "indexing"
    assert ProgressBroadcaster.get_instance().get_connection_count("kb") == 0


def test_malformed_freshness_timestamp_suppresses_stale_replay(monkeypatch, tmp_path: Path) -> None:
    """Site knowledge.py:4402 — an unparseable ``timestamp`` in the freshness
    check is swallowed and treated as not-fresh. Designed degradation: the
    possibly-stale snapshot is NOT replayed as authoritative (no initial
    frame); the connection stays open for live polling and settles cleanly
    on client disconnect."""
    base_dir = tmp_path / "knowledge_bases"
    _write_progress(
        base_dir,
        {
            "stage": "indexing",
            "message": "working",
            "progress_percent": 40,
            "timestamp": "not-a-timestamp",
        },
    )

    class _StubTaskIDManager:
        @classmethod
        def get_instance(cls) -> "_StubTaskIDManager":
            return cls()

        def get_task_metadata(self, task_id: str) -> dict:
            return {"status": "processing"}

    class _ReadyKBManager:
        def __init__(self, base_dir: str | None = None) -> None:
            pass

        def get_info(self, kb_name: str) -> dict:
            return {"statistics": {"rag_initialized": True}}

    monkeypatch.setattr(knowledge_router, "TaskIDManager", _StubTaskIDManager)
    monkeypatch.setattr(knowledge_router, "KnowledgeBaseManager", _ReadyKBManager)

    with _client(monkeypatch, base_dir).websocket_connect(
        "/ws/knowledge-bases/kb/progress?task_id=watched-task"
    ) as websocket:
        websocket.close()
        with pytest.raises(WebSocketDisconnect):
            websocket.receive_json()

    assert ProgressBroadcaster.get_instance().get_connection_count("kb") == 0


def test_failed_error_push_still_completes_cleanup(
    monkeypatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Site knowledge.py:4480 — when the terminal ``{"type": "error"}`` push
    itself fails, the inner handler swallows it. Contract: the failure stays
    contained (no escape from the endpoint), the outer error is at least
    debug-logged, and the finally-block cleanup still runs: broadcaster
    disconnect, socket close, user-context reset."""

    def broken_base_dir() -> Path:
        raise RuntimeError("config unavailable")

    monkeypatch.setattr(knowledge_router, "_current_kb_base_dir", broken_base_dir)

    async def failing_send_json(self, message, mode="text", **kwargs):
        raise RuntimeError("socket send failed")

    monkeypatch.setattr(WebSocket, "send_json", failing_send_json)

    reset_calls: list[str] = []

    def spy_reset(token: str) -> None:
        reset_calls.append(token)

    monkeypatch.setattr(multi_user_context, "reset_current_user", spy_reset)

    with caplog.at_level(logging.DEBUG, logger=_PROGRESS_WS_LOGGER):
        with _client(monkeypatch, tmp_path / "knowledge_bases", token="token-t4").websocket_connect(
            "/ws/knowledge-bases/kb/progress"
        ) as websocket:
            with pytest.raises(WebSocketDisconnect):
                websocket.receive_json()

    assert reset_calls == ["token-t4"]
    assert ProgressBroadcaster.get_instance().get_connection_count("kb") == 0
    assert any("Progress WS error" in record.message for record in caplog.records)


def test_close_failure_does_not_block_user_reset(monkeypatch, tmp_path: Path) -> None:
    """Site knowledge.py:4486 — a failing ``websocket.close()`` is swallowed.
    Contract: best-effort close must not prevent the user-context reset, must
    not escape the endpoint, and the socket must still be torn down."""
    base_dir = tmp_path / "knowledge_bases"
    _write_progress(
        base_dir,
        {
            "stage": "indexing",
            "message": "working",
            "progress_percent": 40,
            "timestamp": (datetime.now() - timedelta(minutes=10)).isoformat(),
        },
    )

    real_close = WebSocket.close

    async def close_then_fail(self, code: int = 1000, reason: str | None = None):
        await real_close(self, code, reason)
        raise RuntimeError("close bookkeeping failed")

    monkeypatch.setattr(WebSocket, "close", close_then_fail)

    reset_calls: list[str] = []

    def spy_reset(token: str) -> None:
        reset_calls.append(token)

    monkeypatch.setattr(multi_user_context, "reset_current_user", spy_reset)

    with _client(monkeypatch, base_dir, token="token-t5").websocket_connect(
        "/ws/knowledge-bases/kb/progress"
    ) as websocket:
        frame = websocket.receive_json()
        assert frame["type"] == "progress"
        assert frame["data"]["stage"] == "indexing"
        with pytest.raises(WebSocketDisconnect):
            websocket.receive_json()

    assert reset_calls == ["token-t5"]
    assert ProgressBroadcaster.get_instance().get_connection_count("kb") == 0


def test_reset_current_user_failure_does_not_escape(monkeypatch, tmp_path: Path) -> None:
    """Site knowledge.py:4491 — a failing ``reset_current_user`` is swallowed.
    Contract: best-effort reset must not escape the endpoint nor block the
    socket teardown; the connection still settles and cleans up."""
    base_dir = tmp_path / "knowledge_bases"
    _write_progress(
        base_dir,
        {
            "stage": "indexing",
            "message": "working",
            "progress_percent": 40,
            "timestamp": (datetime.now() - timedelta(minutes=10)).isoformat(),
        },
    )

    reset_calls: list[str] = []

    def failing_reset(token: str) -> None:
        reset_calls.append(token)
        raise RuntimeError("context teardown failed")

    monkeypatch.setattr(multi_user_context, "reset_current_user", failing_reset)

    with _client(monkeypatch, base_dir, token="token-t6").websocket_connect(
        "/ws/knowledge-bases/kb/progress"
    ) as websocket:
        frame = websocket.receive_json()
        assert frame["type"] == "progress"
        assert frame["data"]["stage"] == "indexing"
        with pytest.raises(WebSocketDisconnect):
            websocket.receive_json()

    assert reset_calls == ["token-t6"]
    assert ProgressBroadcaster.get_instance().get_connection_count("kb") == 0
