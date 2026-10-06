"""Focused tests for ``deeptutor/logging/process_stream.py``.

Axes covered:
- stream chunking: every record becomes its own ordered event, gated by level
  and by the task/turn context filter;
- encoding tolerance: non-ASCII payloads round-trip intact and a malformed
  record or a failing sink never breaks the stream;
- teardown: the capture detaches on exit, an async sink whose owning loop is
  gone closes its pending coroutine, and a real subprocess exits cleanly after
  a full capture cycle.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
import subprocess
import sys
import warnings

from deeptutor.logging import (
    ProcessLogEvent,
    bind_log_context,
    capture_process_logs,
)
from deeptutor.logging.process_stream import ProcessLogHandler

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

_CHILD_SCRIPT = """
import asyncio
import logging
import sys
import threading

from deeptutor.logging import ProcessLogEvent, bind_log_context, capture_process_logs

events: list[ProcessLogEvent] = []


async def emit(event: ProcessLogEvent) -> None:
    events.append(event)


async def main() -> None:
    logger = logging.getLogger("deeptutor.tests.subprocess")
    logger.setLevel(logging.INFO)
    with bind_log_context(task_id="task-child", stage="reading"):
        with capture_process_logs(emit):
            logger.info("子进程记录: %s", "✅")

            def worker() -> None:
                logger.warning("线程记录 2/2")

            thread = threading.Thread(target=worker)
            thread.start()
            thread.join()
            await asyncio.sleep(0)
            await asyncio.sleep(0)

    logger.info("after capture")
    for event in events:
        print(f"{event.level}:{event.message}")
    print(f"EVENTS:{len(events)}")


asyncio.run(main())
"""


def _events_sink(events: list[ProcessLogEvent]):
    return events.append


def test_stream_emits_one_ordered_event_per_record() -> None:
    events: list[ProcessLogEvent] = []
    logger = logging.getLogger("deeptutor.tests.process")
    original_level = logger.level
    logger.setLevel(logging.INFO)

    try:
        with capture_process_logs(_events_sink(events)):
            logger.info("first: %s", "a")
            logger.warning("second: %s", "b")
            logger.error("third")
    finally:
        logger.setLevel(original_level)

    assert [event.message for event in events] == ["first: a", "second: b", "third"]
    assert [event.level for event in events] == ["INFO", "WARNING", "ERROR"]
    assert all(event.type == "process_log" for event in events)
    assert all(event.logger == "deeptutor.tests.process" for event in events)
    assert all(event.timestamp > 0 for event in events)
    assert [event.to_dict()["message"] for event in events] == [
        "first: a",
        "second: b",
        "third",
    ]


def test_stream_gates_records_below_min_level() -> None:
    events: list[ProcessLogEvent] = []
    logger = logging.getLogger("deeptutor.tests.process")
    original_level = logger.level
    logger.setLevel(logging.DEBUG)

    try:
        with capture_process_logs(_events_sink(events), min_level=logging.WARNING):
            logger.debug("noise")
            logger.info("also noise")
            logger.error("kept")
    finally:
        logger.setLevel(original_level)

    assert [event.message for event in events] == ["kept"]


def test_stream_splits_events_by_turn_id_filter() -> None:
    events: list[ProcessLogEvent] = []
    logger = logging.getLogger("deeptutor.tests.process")
    original_level = logger.level
    logger.setLevel(logging.INFO)

    try:
        with capture_process_logs(_events_sink(events), turn_id="turn-1"):
            with bind_log_context(turn_id="turn-other"):
                logger.info("wrong turn")
            with bind_log_context(turn_id="turn-1"):
                logger.info("right turn")
    finally:
        logger.setLevel(original_level)

    assert [event.message for event in events] == ["right turn"]
    assert events[0].context["turn_id"] == "turn-1"


def test_from_record_falls_back_to_record_attributes_for_context_fields() -> None:
    record = logging.LogRecord(
        name="deeptutor.tests.process",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="direct record %s",
        args=("payload",),
        exc_info=None,
    )
    record.request_id = "req-9"
    record.turn_id = "turn-9"

    event = ProcessLogEvent.from_record(record)

    assert event.message == "direct record payload"
    assert event.context["request_id"] == "req-9"
    assert event.context["turn_id"] == "turn-9"
    assert event.to_dict()["context"]["request_id"] == "req-9"


def test_non_ascii_message_round_trips_intact() -> None:
    events: list[ProcessLogEvent] = []
    logger = logging.getLogger("deeptutor.tests.process")
    original_level = logger.level
    logger.setLevel(logging.INFO)

    try:
        with capture_process_logs(_events_sink(events)):
            logger.info("进度 %d/%d：%s ✅", 3, 8, "检索完成")
    finally:
        logger.setLevel(original_level)

    assert len(events) == 1
    assert events[0].message == "进度 3/8：检索完成 ✅"
    assert events[0].to_dict()["message"] == "进度 3/8：检索完成 ✅"


def test_malformed_record_is_tolerated_and_stream_continues(monkeypatch, capsys) -> None:
    monkeypatch.setattr(logging, "raiseExceptions", False)
    events: list[ProcessLogEvent] = []
    logger = logging.getLogger("deeptutor.tests.process")
    original_level = logger.level
    logger.setLevel(logging.INFO)

    try:
        with capture_process_logs(_events_sink(events)):
            logger.info("%d items", "not-a-number")
            logger.info("recovered record")
    finally:
        logger.setLevel(original_level)

    assert [event.message for event in events] == ["recovered record"]
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err


def test_failing_sink_is_tolerated_and_stream_continues(monkeypatch) -> None:
    monkeypatch.setattr(logging, "raiseExceptions", False)
    calls: list[ProcessLogEvent] = []

    def flaky_emit(event: ProcessLogEvent) -> None:
        calls.append(event)
        if len(calls) == 1:
            raise RuntimeError("sink exploded")
        events.append(event)

    events: list[ProcessLogEvent] = []
    logger = logging.getLogger("deeptutor.tests.process")
    original_level = logger.level
    logger.setLevel(logging.INFO)

    try:
        with capture_process_logs(flaky_emit):
            logger.info("drops here")
            logger.info("keeps flowing")
    finally:
        logger.setLevel(original_level)

    assert len(calls) == 2
    assert [event.message for event in events] == ["keeps flowing"]


def test_async_sink_scheduled_on_the_running_loop() -> None:
    seen: list[str] = []

    async def scenario() -> None:
        async def emit(event: ProcessLogEvent) -> None:
            seen.append(event.message)

        logger = logging.getLogger("deeptutor.tests.process")
        original_level = logger.level
        logger.setLevel(logging.INFO)
        try:
            with capture_process_logs(emit, min_level=logging.INFO):
                logger.info("logged on the loop itself")
                await asyncio.sleep(0)
                await asyncio.sleep(0)
        finally:
            logger.setLevel(original_level)

    asyncio.run(scenario())

    assert seen == ["logged on the loop itself"]


def test_async_sink_that_outlived_its_loop_closes_pending_coroutines() -> None:
    seen: list[ProcessLogEvent] = []
    logger = logging.getLogger("deeptutor.tests.process")
    original_level = logger.level
    logger.setLevel(logging.INFO)

    async def emit(event: ProcessLogEvent) -> None:
        seen.append(event)

    async def build() -> ProcessLogHandler:
        return ProcessLogHandler(emit)

    loop = asyncio.new_event_loop()
    try:
        handler = loop.run_until_complete(build())
    finally:
        loop.close()

    root = logging.getLogger()
    root.addHandler(handler)
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            logger.info("event after the owning loop closed")
    finally:
        root.removeHandler(handler)
        handler.close()
        logger.setLevel(original_level)

    assert seen == []
    assert [w for w in caught if "never awaited" in str(w.message)] == []


def test_capture_teardown_detaches_handler_and_stops_the_stream() -> None:
    events: list[ProcessLogEvent] = []
    logger = logging.getLogger("deeptutor.tests.process")
    root = logging.getLogger()
    original_level = logger.level
    logger.setLevel(logging.INFO)

    try:
        with capture_process_logs(_events_sink(events)) as handler:
            assert handler in root.handlers
            logger.info("during capture")
        assert handler not in root.handlers
        logger.info("after capture")
    finally:
        logger.setLevel(original_level)

    assert [event.message for event in events] == ["during capture"]


def test_subprocess_capture_cycle_exits_cleanly() -> None:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(_PROJECT_ROOT), environment.get("PYTHONPATH", "")) if part
    )

    completed = subprocess.run(
        [sys.executable, "-c", _CHILD_SCRIPT],
        cwd=_PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )

    assert completed.returncode == 0, completed.stderr
    assert "EVENTS:2" in completed.stdout
    assert "INFO:子进程记录: ✅" in completed.stdout
    assert "WARNING:线程记录 2/2" in completed.stdout
    assert "after capture" not in completed.stdout
    assert "Never" not in completed.stderr
    assert "Traceback" not in completed.stderr
