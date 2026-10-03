from __future__ import annotations

import asyncio
import json
import logging

from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.knowledge.progress_tracker import ProgressStage, ProgressTracker


def test_progress_tracker_persists_snapshot_and_config(tmp_path) -> None:
    tracker = ProgressTracker("demo-kb", tmp_path)

    tracker.update(
        ProgressStage.PROCESSING_DOCUMENTS,
        "Embedding batches: 2/8 complete",
        current=2,
        total=8,
    )

    assert tracker.progress_file.exists()

    with open(tracker.progress_file, encoding="utf-8") as f:
        payload = json.load(f)

    assert payload["stage"] == "processing_documents"
    assert payload["progress_percent"] == 25
    assert payload["message"] == "Embedding batches: 2/8 complete"

    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    status = manager.get_kb_status("demo-kb")

    assert status is not None
    assert status["status"] == "processing"
    assert status["progress"]["message"] == "Embedding batches: 2/8 complete"


def test_progress_tracker_get_progress_falls_back_to_config(tmp_path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    manager.update_kb_status(
        name="demo-kb",
        status="processing",
        progress={
            "stage": "processing_documents",
            "message": "Recovered from kb_config",
            "percent": 60,
            "current": 3,
            "total": 5,
        },
    )

    tracker = ProgressTracker("demo-kb", tmp_path)

    assert tracker.get_progress() == {
        "stage": "processing_documents",
        "message": "Recovered from kb_config",
        "percent": 60,
        "current": 3,
        "total": 5,
    }


def test_progress_tracker_persists_structured_failure_metadata(tmp_path) -> None:
    tracker = ProgressTracker("demo-kb", tmp_path)

    tracker.update(
        ProgressStage.ERROR,
        "GraphRAG model is incompatible",
        error="Choose a chat model that supports structured output.",
        error_code="graphrag_model_incompatible",
        retryable=False,
    )

    with open(tracker.progress_file, encoding="utf-8") as handle:
        payload = json.load(handle)

    assert payload["error_code"] == "graphrag_model_incompatible"
    assert payload["retryable"] is False

    status = KnowledgeBaseManager(base_dir=str(tmp_path)).get_kb_status("demo-kb")
    assert status is not None
    assert status["progress"]["error_code"] == "graphrag_model_incompatible"
    assert status["progress"]["retryable"] is False


def test_update_carries_a_translatable_template(tmp_path) -> None:
    """Progress lines render in the browser, which is where the language is.

    So the payload carries the English template plus its values; ``message``
    stays populated for every consumer that has no i18n of its own, rendered
    from that same template rather than duplicated at the call site.
    """
    from deeptutor.knowledge.progress_tracker import ProgressStage, ProgressTracker

    seen: list[dict] = []
    tracker = ProgressTracker("kb", tmp_path)
    tracker.set_callback(seen.append)

    tracker.update(
        ProgressStage.PROCESSING_DOCUMENTS,
        message_key="Describing images: {{current}}/{{total}}",
        message_params={"current": 3, "total": 7},
        current=3,
        total=7,
    )

    payload = seen[-1]
    assert payload["message_key"] == "Describing images: {{current}}/{{total}}"
    assert payload["message_params"] == {"current": 3, "total": 7}
    assert payload["message"] == "Describing images: 3/7"


def test_update_keeps_an_explicit_message_verbatim(tmp_path) -> None:
    from deeptutor.knowledge.progress_tracker import ProgressStage, ProgressTracker

    seen: list[dict] = []
    tracker = ProgressTracker("kb", tmp_path)
    tracker.set_callback(seen.append)

    tracker.update(ProgressStage.INITIALIZING, "already rendered")

    assert seen[-1]["message"] == "already rendered"
    assert "message_key" not in seen[-1]


def _force_server_mode(monkeypatch) -> None:
    from deeptutor.runtime import mode

    monkeypatch.setattr(mode, "_current_mode", mode.RunMode.SERVER)


def test_notify_logs_warning_once_when_broadcast_fails(tmp_path, monkeypatch, caplog) -> None:
    """A failing progress broadcast must surface as one warning, not vanish.

    KB rebuild/index progress is invisible otherwise: the scheduled broadcast
    task dies with an unretrieved exception while callers keep believing the
    frontend was updated (DT-22).
    """
    from deeptutor.knowledge import progress_events

    async def broken_broadcast(kb_name: str, progress: dict) -> None:
        raise RuntimeError("websocket hub unavailable")

    monkeypatch.setattr(progress_events, "_broadcast", broken_broadcast)
    monkeypatch.setattr(ProgressTracker, "_broadcast_failure_logged", False, raising=False)
    _force_server_mode(monkeypatch)

    seen: list[dict] = []
    tracker = ProgressTracker("kb", tmp_path)
    tracker.set_callback(seen.append)

    async def scenario() -> None:
        tracker._notify({"stage": "processing_documents"})
        tracker._notify({"stage": "processing_documents"})
        await asyncio.sleep(0.05)

    with caplog.at_level(logging.WARNING, logger="deeptutor.knowledge.progress_tracker"):
        asyncio.run(scenario())

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1
    assert "Progress broadcast" in warnings[0].getMessage()
    assert "websocket hub unavailable" in warnings[0].getMessage()
    assert len(seen) == 2


def test_notify_without_running_loop_stays_silent(tmp_path, monkeypatch, caplog) -> None:
    """No running loop is an expected CLI/thread condition, not a failure."""
    from deeptutor.knowledge import progress_events

    async def broken_broadcast(kb_name: str, progress: dict) -> None:
        raise AssertionError("must not be scheduled without a running loop")

    monkeypatch.setattr(progress_events, "_broadcast", broken_broadcast)
    monkeypatch.setattr(ProgressTracker, "_broadcast_failure_logged", False, raising=False)
    _force_server_mode(monkeypatch)

    seen: list[dict] = []
    tracker = ProgressTracker("kb", tmp_path)
    tracker.set_callback(seen.append)

    with caplog.at_level(logging.WARNING, logger="deeptutor.knowledge.progress_tracker"):
        tracker._notify({"stage": "processing_documents"})

    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(seen) == 1
