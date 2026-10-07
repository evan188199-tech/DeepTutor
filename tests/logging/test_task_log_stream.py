import asyncio
import json
import logging

import pytest

from deeptutor.api.utils.task_log_stream import (
    KnowledgeTaskStreamManager,
    capture_task_logs,
    get_task_stream_manager,
)
from deeptutor.logging import PROCESS_LOG_PRIVATE_ATTR


@pytest.mark.asyncio
async def test_knowledge_task_stream_emits_process_log_sse_event():
    manager = KnowledgeTaskStreamManager()
    manager.ensure_task("task-1")
    manager.emit_log("task-1", "Indexing started")

    stream = manager.stream("task-1")
    try:
        chunk = await anext(stream)
    finally:
        await stream.aclose()

    lines = chunk.splitlines()
    header, data_line = lines[:2]
    assert header == "event: process_log"
    payload = json.loads(data_line.removeprefix("data: "))
    assert payload["type"] == "process_log"
    assert payload["message"] == "Indexing started"
    assert payload["context"]["task_id"] == "task-1"


@pytest.mark.asyncio
async def test_knowledge_task_stream_keeps_idle_sse_connection_alive():
    manager = KnowledgeTaskStreamManager()
    manager._HEARTBEAT_SECONDS = 0.01
    manager.ensure_task("task-idle")

    stream = manager.stream("task-idle")
    try:
        heartbeat = await asyncio.wait_for(anext(stream), timeout=0.2)
        assert heartbeat == ": keep-alive\n\n"

        manager.emit_log("task-idle", "Indexing resumed")
        event = await asyncio.wait_for(anext(stream), timeout=0.2)
        assert "event: process_log" in event
        assert "Indexing resumed" in event
    finally:
        await stream.aclose()


def test_knowledge_task_stream_emits_structured_failure_metadata():
    manager = KnowledgeTaskStreamManager()
    manager.ensure_task("task-failed")

    manager.emit_failed(
        "task-failed",
        "Choose a compatible chat model.",
        details="internal traceback",
        error_code="graphrag_model_incompatible",
        retryable=False,
    )

    event = list(manager._buffers["task-failed"])[-1]
    assert event["event"] == "failed"
    assert event["payload"]["detail"] == "Choose a compatible chat model."
    assert event["payload"]["details"] == "internal traceback"
    assert event["payload"]["error_code"] == "graphrag_model_incompatible"
    assert event["payload"]["retryable"] is False


def test_capture_task_logs_forwards_lightrag_non_propagating_logger():
    original_instance = KnowledgeTaskStreamManager._instance
    lightrag_logger = logging.getLogger("lightrag")
    original_handlers = list(lightrag_logger.handlers)
    original_propagate = lightrag_logger.propagate
    original_level = lightrag_logger.level
    try:
        KnowledgeTaskStreamManager._instance = KnowledgeTaskStreamManager()
        lightrag_logger.handlers = []
        lightrag_logger.propagate = False
        lightrag_logger.setLevel(logging.INFO)

        with capture_task_logs("task-native"):
            lightrag_logger.info("Chunk 1 of 1 extracted 14 Ent + 13 Rel")

        manager = get_task_stream_manager()
        events = list(manager._buffers["task-native"])
    finally:
        KnowledgeTaskStreamManager._instance = original_instance
        lightrag_logger.handlers = original_handlers
        lightrag_logger.propagate = original_propagate
        lightrag_logger.setLevel(original_level)

    assert any(
        event["event"] == "process_log"
        and event["payload"]["logger"] == "lightrag"
        and event["payload"]["message"] == "Chunk 1 of 1 extracted 14 Ent + 13 Rel"
        and event["payload"]["context"]["task_id"] == "task-native"
        for event in events
    )


def test_capture_task_logs_forwards_graphrag_propagating_logger_once():
    original_instance = KnowledgeTaskStreamManager._instance
    graphrag_logger = logging.getLogger("graphrag.api.query")
    original_handlers = list(graphrag_logger.handlers)
    original_propagate = graphrag_logger.propagate
    original_level = graphrag_logger.level
    try:
        KnowledgeTaskStreamManager._instance = KnowledgeTaskStreamManager()
        graphrag_logger.handlers = []
        graphrag_logger.propagate = True
        graphrag_logger.setLevel(logging.INFO)

        with capture_task_logs("task-graphrag"):
            graphrag_logger.info("GraphRAG local search selected 3 text units")

        manager = get_task_stream_manager()
        events = list(manager._buffers["task-graphrag"])
    finally:
        KnowledgeTaskStreamManager._instance = original_instance
        graphrag_logger.handlers = original_handlers
        graphrag_logger.propagate = original_propagate
        graphrag_logger.setLevel(original_level)

    matches = [
        event
        for event in events
        if event["event"] == "process_log"
        and event["payload"]["logger"] == "graphrag.api.query"
        and event["payload"]["message"] == "GraphRAG local search selected 3 text units"
        and event["payload"]["context"]["task_id"] == "task-graphrag"
    ]
    assert len(matches) == 1


def test_capture_task_logs_excludes_private_non_propagating_library_diagnostics():
    original_instance = KnowledgeTaskStreamManager._instance
    graphrag_logger = logging.getLogger("graphrag")
    original_handlers = list(graphrag_logger.handlers)
    original_propagate = graphrag_logger.propagate
    original_level = graphrag_logger.level
    try:
        KnowledgeTaskStreamManager._instance = KnowledgeTaskStreamManager()
        graphrag_logger.handlers = []
        graphrag_logger.propagate = False
        graphrag_logger.setLevel(logging.INFO)

        with capture_task_logs("task-private"):
            graphrag_logger.error(
                "Stack trace contains sk-secret-must-not-leak",
                extra={PROCESS_LOG_PRIVATE_ATTR: True},
            )

        manager = get_task_stream_manager()
        events = list(manager._buffers["task-private"])
    finally:
        KnowledgeTaskStreamManager._instance = original_instance
        graphrag_logger.handlers = original_handlers
        graphrag_logger.propagate = original_propagate
        graphrag_logger.setLevel(original_level)

    assert events == []


def test_capture_task_logs_keeps_user_stages_and_drops_runtime_noise():
    original_instance = KnowledgeTaskStreamManager._instance
    loggers = {
        name: logging.getLogger(name)
        for name in (
            "root",
            "asyncio",
            "deeptutor.knowledge.progress_tracker",
            "deeptutor.services.rag.pipelines.pageindex.pipeline",
        )
    }
    original_levels = {name: logger.level for name, logger in loggers.items()}
    try:
        KnowledgeTaskStreamManager._instance = KnowledgeTaskStreamManager()
        for logger in loggers.values():
            logger.setLevel(logging.INFO)
        with capture_task_logs("task-curated"):
            loggers["root"].error("Request timed out")
            loggers["asyncio"].error("Event loop is closed")
            loggers["deeptutor.knowledge.progress_tracker"].info("duplicate progress")
            loggers["deeptutor.services.rag.pipelines.pageindex.pipeline"].info(
                "PageIndex: submitting manual.pdf"
            )
        events = list(get_task_stream_manager()._buffers["task-curated"])
    finally:
        KnowledgeTaskStreamManager._instance = original_instance
        for name, logger in loggers.items():
            logger.setLevel(original_levels[name])

    messages = [event["payload"]["message"] for event in events]
    assert messages == ["PageIndex: submitting manual.pdf"]


def test_completed_task_buffers_are_bounded_and_restore_terminal_event():
    manager = KnowledgeTaskStreamManager()
    manager._MAX_RETAINED_TASKS = 3

    for index in range(8):
        task_id = f"task-{index}"
        manager.ensure_task(task_id)
        manager.emit_log(task_id, "x" * 100)
        manager.emit_complete(task_id)

    assert manager.retained_task_count() == 3
    assert len(manager._terminal_tombstones) == 5

    manager.ensure_task("task-0")
    restored = list(manager._buffers["task-0"])
    assert restored[-1]["event"] == "complete"


def test_task_buffer_has_approximate_byte_ceiling():
    manager = KnowledgeTaskStreamManager()
    manager._MAX_BYTES_PER_TASK = 2_000
    manager.ensure_task("large-task")

    for _ in range(20):
        manager.emit_log("large-task", "x" * 500)

    assert manager._buffer_bytes["large-task"] <= manager._MAX_BYTES_PER_TASK
    assert len(manager._buffers["large-task"]) < 20


# ---------------------------------------------------------------------------
# Error-path coverage: stream interruption, early read-side disconnect,
# oversized event truncation, and idempotent close/cleanup semantics.
# ---------------------------------------------------------------------------


@pytest.fixture()
def no_memory_reclaim(monkeypatch):
    monkeypatch.setattr(
        KnowledgeTaskStreamManager, "_schedule_memory_reclaim", staticmethod(lambda: None)
    )


async def _drain_with_deadline(stream, timeout: float = 2.0) -> list[str]:
    chunks: list[str] = []
    while True:
        try:
            chunks.append(await asyncio.wait_for(anext(stream), timeout=timeout))
        except StopAsyncIteration:
            return chunks


async def _subscribe_task(manager, task_id):
    return manager.subscribe(task_id)


def test_event_bytes_falls_back_for_unserializable_event():
    circular: dict = {"event": "process_log", "payload": {}}
    circular["payload"]["self"] = circular

    assert KnowledgeTaskStreamManager._event_bytes(circular) == 256


def test_oversized_process_log_event_is_compacted_to_hard_byte_budget():
    manager = KnowledgeTaskStreamManager()
    manager.ensure_task("task-oversize-log")

    manager.emit_log("task-oversize-log", "x" * (3 * 1024 * 1024))

    events = list(manager._buffers["task-oversize-log"])
    assert len(events) == 1
    assert events[0]["event"] == "process_log"
    assert events[0]["payload"]["truncated"] is True
    assert manager._buffer_bytes["task-oversize-log"] <= manager._MAX_BYTES_PER_TASK


def test_oversized_failed_event_is_compacted_and_stays_terminal_visible(no_memory_reclaim):
    manager = KnowledgeTaskStreamManager()
    manager.ensure_task("task-oversize-failed")

    manager.emit_failed(
        "task-oversize-failed",
        "y" * (3 * 1024 * 1024),
        error_code="graphrag_model_incompatible",
    )

    events = list(manager._buffers["task-oversize-failed"])
    assert len(events) == 1
    assert events[0]["event"] == "failed"
    assert events[0]["payload"]["truncated"] is True
    assert events[0]["payload"]["detail"] == "y" * 8192
    assert "error_code" not in events[0]["payload"]
    assert manager._buffer_bytes["task-oversize-failed"] <= manager._MAX_BYTES_PER_TASK


@pytest.mark.asyncio
async def test_stream_yields_compacted_oversized_terminal_and_terminates(no_memory_reclaim):
    manager = KnowledgeTaskStreamManager()
    manager.ensure_task("task-oversize-stream")

    manager.emit_failed("task-oversize-stream", "z" * (3 * 1024 * 1024))

    stream = manager.stream("task-oversize-stream")
    try:
        chunks = await _drain_with_deadline(stream)
    finally:
        await stream.aclose()

    assert len(chunks) == 1
    assert chunks[0].startswith("event: failed\n")
    assert '"truncated": true' in chunks[0]
    assert "z" * 9000 not in chunks[0]
    assert manager._subscribers.get("task-oversize-stream") in (None, [])


def test_emit_skips_subscriber_bound_to_closed_event_loop():
    manager = KnowledgeTaskStreamManager()
    manager.ensure_task("task-closed-loop")
    loop = asyncio.new_event_loop()
    try:
        queue, _backlog, sub_loop = loop.run_until_complete(
            _subscribe_task(manager, "task-closed-loop")
        )
    finally:
        loop.close()

    manager.emit_log("task-closed-loop", "producer emits after the read loop closed")

    last = list(manager._buffers["task-closed-loop"])[-1]
    assert last["payload"]["message"] == "producer emits after the read loop closed"
    manager.unsubscribe("task-closed-loop", queue, sub_loop)
    assert "task-closed-loop" not in manager._subscribers


@pytest.mark.asyncio
async def test_full_subscriber_queue_drops_events_without_error():
    manager = KnowledgeTaskStreamManager()
    manager.ensure_task("task-full-queue")
    queue, _backlog, loop = manager.subscribe("task-full-queue")

    total = queue.maxsize + 25
    for index in range(total):
        manager.emit_log("task-full-queue", f"line-{index}")
    await asyncio.sleep(0)

    assert queue.qsize() == queue.maxsize
    assert queue.get_nowait()["payload"]["message"] == "line-0"
    manager.unsubscribe("task-full-queue", queue, loop)
    assert "task-full-queue" not in manager._subscribers


@pytest.mark.asyncio
async def test_stream_interrupted_midway_unsubscribes_and_manager_stays_usable():
    manager = KnowledgeTaskStreamManager()
    manager._HEARTBEAT_SECONDS = 0.01
    manager.ensure_task("task-mid-stream-disconnect")

    stream = manager.stream("task-mid-stream-disconnect")
    heartbeat = await asyncio.wait_for(anext(stream), timeout=1.0)
    assert heartbeat == ": keep-alive\n\n"
    await stream.aclose()
    await stream.aclose()

    assert manager._subscribers.get("task-mid-stream-disconnect") in (None, [])
    manager.emit_log("task-mid-stream-disconnect", "producer continues after disconnect")
    last = list(manager._buffers["task-mid-stream-disconnect"])[-1]
    assert last["payload"]["message"] == "producer continues after disconnect"


@pytest.mark.asyncio
async def test_stream_terminates_and_unsubscribes_on_failed_terminal_event(no_memory_reclaim):
    manager = KnowledgeTaskStreamManager()
    manager._HEARTBEAT_SECONDS = 0.01
    manager.ensure_task("task-failed-terminal")

    async def _fail_later():
        await asyncio.sleep(0.05)
        manager.emit_failed(
            "task-failed-terminal",
            "graphrag pipeline exploded",
            error_code="graphrag_model_incompatible",
        )

    emitter = asyncio.create_task(_fail_later())
    try:
        chunks = [chunk async for chunk in manager.stream("task-failed-terminal")]
    finally:
        await emitter

    assert any("event: failed" in chunk for chunk in chunks)
    assert any("graphrag_model_incompatible" in chunk for chunk in chunks)
    assert manager._subscribers.get("task-failed-terminal") in (None, [])


@pytest.mark.asyncio
async def test_stream_replaying_failed_backlog_returns_without_heartbeat_wait(no_memory_reclaim):
    manager = KnowledgeTaskStreamManager()
    manager.emit_failed("task-replay-failed", "late failure after disconnect")

    stream = manager.stream("task-replay-failed")
    try:
        chunks = await _drain_with_deadline(stream)
    finally:
        await stream.aclose()

    assert len(chunks) == 1
    assert "event: failed" in chunks[0]
    assert "late failure after disconnect" in chunks[0]
    assert manager._subscribers.get("task-replay-failed") in (None, [])


@pytest.mark.asyncio
async def test_unsubscribe_is_idempotent_for_same_queue():
    manager = KnowledgeTaskStreamManager()
    manager.ensure_task("task-unsub-twice")
    queue, _backlog, loop = manager.subscribe("task-unsub-twice")

    manager.unsubscribe("task-unsub-twice", queue, loop)
    manager.unsubscribe("task-unsub-twice", queue, loop)

    assert "task-unsub-twice" not in manager._subscribers
    assert manager.retained_task_count() == 1


@pytest.mark.asyncio
async def test_unsubscribe_unknown_task_is_silent_noop():
    manager = KnowledgeTaskStreamManager()
    queue: asyncio.Queue = asyncio.Queue(maxsize=1)

    manager.unsubscribe("task-never-subscribed", queue, asyncio.get_running_loop())

    assert manager.retained_task_count() == 0


def test_cleanup_of_task_without_terminal_event_leaves_no_tombstone():
    manager = KnowledgeTaskStreamManager()
    manager.ensure_task("task-dropped-mid-flight")
    manager.emit_log("task-dropped-mid-flight", "still running")

    manager._drop_task_locked("task-dropped-mid-flight")

    assert "task-dropped-mid-flight" not in manager._buffers
    assert "task-dropped-mid-flight" not in manager._terminal_tombstones
    assert manager.retained_task_count() == 0


@pytest.mark.asyncio
async def test_dropped_terminal_task_replays_tombstone_to_late_subscriber():
    manager = KnowledgeTaskStreamManager()
    manager.ensure_task("task-tombstone-replay")
    manager.emit_failed("task-tombstone-replay", "failed while nobody watched")
    manager._drop_task_locked("task-tombstone-replay")
    assert "task-tombstone-replay" in manager._terminal_tombstones

    stream = manager.stream("task-tombstone-replay")
    try:
        chunks = await _drain_with_deadline(stream)
    finally:
        await stream.aclose()

    assert len(chunks) == 1
    assert "event: failed" in chunks[0]
    assert "failed while nobody watched" in chunks[0]
    assert manager._subscribers.get("task-tombstone-replay") in (None, [])
