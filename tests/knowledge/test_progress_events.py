"""Progress event publication order and subscriber decoupling."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from deeptutor.knowledge.initializer import KnowledgeBaseInitializer
from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.knowledge.progress_events import (
    broadcast_progress,
    emit_task_progress,
    install_progress_ports,
)
from deeptutor.knowledge.progress_tracker import ProgressStage, ProgressTracker
from deeptutor.runtime.mode import RunMode


class BroadcastRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, kb_name: str, progress: dict) -> None:
        self.calls.append((kb_name, progress))


class EmitRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    def __call__(self, task_id: str, event: str, progress: dict) -> None:
        self.calls.append((task_id, event, progress))


@pytest.fixture(autouse=True)
def _reset_progress_ports():
    install_progress_ports(broadcast=None, emit_task_event=None)
    yield
    install_progress_ports(broadcast=None, emit_task_event=None)


def _write_source_doc(directory: Path, name: str, payload: str = "hello") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(payload, encoding="utf-8")
    return path


@pytest.mark.asyncio
async def test_ports_default_to_silent_noops() -> None:
    await broadcast_progress("kb", {"percent": 50})
    emit_task_progress("task-1", {"percent": 50})


@pytest.mark.asyncio
async def test_installed_ports_receive_arguments_and_reinstall_replaces_subscribers() -> None:
    first_broadcast = BroadcastRecorder()
    first_emit = EmitRecorder()
    install_progress_ports(broadcast=first_broadcast, emit_task_event=first_emit)

    await broadcast_progress("kb-a", {"percent": 10})
    emit_task_progress("task-9", {"percent": 20})

    assert first_broadcast.calls == [("kb-a", {"percent": 10})]
    assert first_emit.calls == [("task-9", "progress", {"percent": 20})]

    second_broadcast = BroadcastRecorder()
    second_emit = EmitRecorder()
    install_progress_ports(broadcast=second_broadcast, emit_task_event=second_emit)

    await broadcast_progress("kb-b", {"percent": 30})
    emit_task_progress("task-9", {"percent": 40})

    assert second_broadcast.calls == [("kb-b", {"percent": 30})]
    assert second_emit.calls == [("task-9", "progress", {"percent": 40})]
    assert first_broadcast.calls == [("kb-a", {"percent": 10})]
    assert first_emit.calls == [("task-9", "progress", {"percent": 20})]


@pytest.mark.asyncio
async def test_tracker_update_forwards_task_events_in_order(tmp_path: Path) -> None:
    emit = EmitRecorder()
    install_progress_ports(broadcast=None, emit_task_event=emit)
    direct: list[dict] = []

    tracker = ProgressTracker("events-kb", tmp_path)
    tracker.task_id = "task-1"
    tracker.set_callback(direct.append)

    tracker.update(ProgressStage.INITIALIZING, "start")
    tracker.update(ProgressStage.PROCESSING_DOCUMENTS, "embedding", current=2, total=8)
    tracker.update(ProgressStage.ERROR, "boom", error="boom")

    assert [event for _, event, _ in emit.calls] == ["progress"] * 3
    assert [task_id for task_id, _, _ in emit.calls] == ["task-1"] * 3
    assert [payload["stage"] for _, _, payload in emit.calls] == [
        "initializing",
        "processing_documents",
        "error",
    ]
    assert [payload["stage"] for payload in direct] == [
        "initializing",
        "processing_documents",
        "error",
    ]


@pytest.mark.asyncio
async def test_broadcast_flows_only_in_server_mode_with_running_loop(
    tmp_path: Path,
    monkeypatch,
) -> None:
    broadcast = BroadcastRecorder()
    install_progress_ports(broadcast=broadcast, emit_task_event=None)

    tracker = ProgressTracker("mode-kb", tmp_path)
    monkeypatch.setattr("deeptutor.runtime.mode._current_mode", RunMode.SERVER)

    tracker.update(ProgressStage.PROCESSING_DOCUMENTS, "half", current=1, total=2)
    await asyncio.sleep(0)

    assert len(broadcast.calls) == 1
    assert broadcast.calls[0][0] == "mode-kb"
    assert broadcast.calls[0][1]["stage"] == "processing_documents"

    monkeypatch.setattr("deeptutor.runtime.mode._current_mode", RunMode.CLI)
    tracker.update(ProgressStage.PROCESSING_DOCUMENTS, "full", current=2, total=2)
    await asyncio.sleep(0)

    assert len(broadcast.calls) == 1


@pytest.mark.asyncio
async def test_initializer_publishes_stage_sequence_and_terminal_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    initializer = KnowledgeBaseInitializer(
        kb_name="seq-kb",
        base_dir=str(tmp_path),
        rag_provider="lightrag",
    )
    initializer.create_directory_structure()
    _write_source_doc(initializer.raw_dir, "doc.md")
    candidate = tmp_path / "seq-kb" / "version-1"
    candidate.mkdir()

    def on_initialize(kwargs: dict) -> None:
        kwargs["progress_callback"](1, 1)
        kwargs["before_publish"](candidate)

    def fake_rag(*, kb_base_dir: str, provider: str):
        class FakeRagService:
            async def initialize(self, **call_kwargs):
                on_initialize(call_kwargs)
                return True

        return FakeRagService()

    monkeypatch.setattr("deeptutor.knowledge.initializer.RAGService", fake_rag)

    seen: list[dict] = []
    initializer.progress_tracker.set_callback(seen.append)
    initializer.progress_tracker.task_id = "task-7"

    assert await initializer.process_documents() is True

    messages = [payload["message"] for payload in seen]
    assert messages == [
        "Starting to process documents with lightrag provider...",
        "Found 1 documents, starting to process...",
        "Embedding batches: 1/1 complete",
        "Finalizing index publication",
    ]
    assert all(payload["stage"] == "processing_documents" for payload in seen)

    persisted = json.loads((tmp_path / "seq-kb" / ".progress.json").read_text(encoding="utf-8"))
    assert persisted["stage"] == "completed"
    assert persisted["publication_version"] == "version-1"
    assert persisted["index_action"] == "create"
    assert persisted["progress_percent"] == 100
    assert persisted["task_id"] == "task-7"

    metadata = json.loads((tmp_path / "seq-kb" / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["rag_provider"] == "lightrag"
    assert metadata["last_indexed_action"] == "create"

    entry = KnowledgeBaseManager(base_dir=str(tmp_path)).get_kb_entry("seq-kb")
    assert entry["status"] == "processing"
    assert entry["progress"]["task_id"] == "task-7"


@pytest.mark.asyncio
async def test_initializer_emits_error_event_last_on_midrun_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    emit = EmitRecorder()
    install_progress_ports(broadcast=None, emit_task_event=emit)

    initializer = KnowledgeBaseInitializer(
        kb_name="emit-fail-kb",
        base_dir=str(tmp_path),
        rag_provider="lightrag",
    )
    initializer.create_directory_structure()
    _write_source_doc(initializer.raw_dir, "doc.md")

    def on_initialize(kwargs: dict) -> None:
        kwargs["progress_callback"](1, 2)

    def fake_rag(*, kb_base_dir: str, provider: str):
        class FakeRagService:
            async def initialize(self, **call_kwargs):
                on_initialize(call_kwargs)
                return False

        return FakeRagService()

    monkeypatch.setattr("deeptutor.knowledge.initializer.RAGService", fake_rag)
    initializer.progress_tracker.task_id = "task-8"

    with pytest.raises(RuntimeError, match="RAG pipeline returned failure"):
        await initializer.process_documents()

    assert [(task_id, payload["stage"]) for task_id, _, payload in emit.calls] == [
        ("task-8", "processing_documents"),
        ("task-8", "processing_documents"),
        ("task-8", "processing_documents"),
        ("task-8", "error"),
        ("task-8", "error"),
    ]
    assert [payload.get("error") for *_, payload in emit.calls] == [
        None,
        None,
        None,
        "RAG pipeline returned failure",
        "RAG pipeline returned failure",
    ]

    persisted = json.loads(
        (tmp_path / "emit-fail-kb" / ".progress.json").read_text(encoding="utf-8")
    )
    assert persisted["stage"] == "error"
    assert persisted["error"] == "RAG pipeline returned failure"
