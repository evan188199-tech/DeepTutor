from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import auth
from deeptutor.api.routers import knowledge as knowledge_router
from deeptutor.api.utils.task_id_manager import TaskIDManager


def _client(monkeypatch, base_dir: Path) -> TestClient:
    async def allow(_websocket):
        return None

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


def _utc_timestamp(seconds_ago: float) -> str:
    moment = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return moment.isoformat()


def _mark_kb_ready(monkeypatch) -> None:
    monkeypatch.setattr(
        knowledge_router.KnowledgeBaseManager,
        "get_info",
        lambda self, name: {"statistics": {"rag_initialized": True}},
    )


@pytest.fixture
def host_timezone():
    @contextmanager
    def _switch(tz_name: str):
        if not hasattr(time, "tzset"):
            pytest.skip("time.tzset() is unavailable on this platform")
        previous = os.environ.get("TZ")
        os.environ["TZ"] = tz_name
        time.tzset()
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = previous
            time.tzset()

    return _switch


@pytest.mark.parametrize("tz_name", ["UTC", "Pacific/Kiritimati"])
def test_fresh_aware_utc_progress_is_active_in_any_host_timezone(
    monkeypatch, tmp_path: Path, host_timezone, tz_name: str
) -> None:
    base_dir = tmp_path / "knowledge_bases"
    _write_progress(
        base_dir,
        {
            "task_id": "live-task",
            "stage": "processing_documents",
            "message": "working",
            "progress_percent": 40,
            "timestamp": _utc_timestamp(seconds_ago=5),
        },
    )
    _mark_kb_ready(monkeypatch)

    with host_timezone(tz_name):
        with _client(monkeypatch, base_dir).websocket_connect(
            "/ws/knowledge-bases/kb/progress"
        ) as websocket:
            frame = websocket.receive_json()

    assert frame["type"] == "progress"
    assert frame["data"]["stage"] == "processing_documents"
    assert frame["data"]["task_id"] == "live-task"


def test_stale_aware_utc_progress_takes_the_ready_fast_path(monkeypatch, tmp_path: Path) -> None:
    base_dir = tmp_path / "knowledge_bases"
    _write_progress(
        base_dir,
        {
            "task_id": "stale-task",
            "stage": "processing_documents",
            "message": "working",
            "progress_percent": 40,
            "timestamp": _utc_timestamp(seconds_ago=600),
        },
    )
    _mark_kb_ready(monkeypatch)

    with _client(monkeypatch, base_dir).websocket_connect(
        "/ws/knowledge-bases/kb/progress"
    ) as websocket:
        frame = websocket.receive_json()

    assert frame["type"] == "progress"
    assert frame["data"]["stage"] == "completed"
    assert frame["data"]["message"] == "Knowledge base is ready."


def test_legacy_naive_timestamp_still_counts_as_fresh(monkeypatch, tmp_path: Path) -> None:
    base_dir = tmp_path / "knowledge_bases"
    _write_progress(
        base_dir,
        {
            "task_id": "legacy-task",
            "stage": "processing_documents",
            "message": "working",
            "progress_percent": 40,
            "timestamp": (datetime.now() - timedelta(seconds=5)).isoformat(),
        },
    )
    _mark_kb_ready(monkeypatch)

    with _client(monkeypatch, base_dir).websocket_connect(
        "/ws/knowledge-bases/kb/progress"
    ) as websocket:
        frame = websocket.receive_json()

    assert frame["type"] == "progress"
    assert frame["data"]["stage"] == "processing_documents"
    assert frame["data"]["task_id"] == "legacy-task"


@pytest.mark.parametrize("bad_timestamp", ["not-a-timestamp", 12345])
def test_unparseable_timestamp_falls_back_to_ready_fast_path(
    monkeypatch, tmp_path: Path, bad_timestamp
) -> None:
    base_dir = tmp_path / "knowledge_bases"
    _write_progress(
        base_dir,
        {
            "task_id": "corrupt-task",
            "stage": "processing_documents",
            "message": "working",
            "progress_percent": 40,
            "timestamp": bad_timestamp,
        },
    )
    _mark_kb_ready(monkeypatch)

    with _client(monkeypatch, base_dir).websocket_connect(
        "/ws/knowledge-bases/kb/progress"
    ) as websocket:
        frame = websocket.receive_json()

    assert frame["type"] == "progress"
    assert frame["data"]["stage"] == "completed"
    assert frame["data"]["message"] == "Knowledge base is ready."


def test_terminal_replay_timestamp_is_aware_utc(monkeypatch, tmp_path: Path) -> None:
    base_dir = tmp_path / "knowledge_bases"
    (base_dir / "kb").mkdir(parents=True)
    monkeypatch.setattr(TaskIDManager, "_instance", None)
    task_manager = TaskIDManager.get_instance()
    task_id = task_manager.generate_task_id("kb_upload", "kb")
    task_manager.update_task_status(task_id, "completed")

    with _client(monkeypatch, base_dir).websocket_connect(
        f"/ws/knowledge-bases/kb/progress?task_id={task_id}"
    ) as websocket:
        frame = websocket.receive_json()

    assert frame["type"] == "progress"
    assert frame["data"]["stage"] == "completed"
    parsed = datetime.fromisoformat(frame["data"]["timestamp"])
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)
