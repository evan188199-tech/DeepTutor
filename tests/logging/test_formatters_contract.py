"""Contract and snapshot tests for the stdlib logging formatters.

Focus axes: the record -> JSONL field contract (JsonlFormatter), behaviour
when context fields are missing (ContextFilter plus both formatters), and a
snapshot regression for ConsoleFormatter's human-readable line shape.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

import pytest

from deeptutor.logging.context import LOG_CONTEXT_FIELDS, bind_log_context
from deeptutor.logging.formatters import (
    ConsoleFormatter,
    ContextFilter,
    JsonlFormatter,
)

LOGGER_NAME = "deeptutor.test.formatters_contract"


def _record(
    msg: str,
    args: tuple = (),
    *,
    level: int = logging.INFO,
    exc_info=None,
    created: float | None = None,
    **attrs,
) -> logging.LogRecord:
    record = logging.LogRecord(
        name=LOGGER_NAME,
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,
        exc_info=exc_info,
        func="fn",
    )
    if created is not None:
        record.created = created
    for key, value in attrs.items():
        setattr(record, key, value)
    return record


class _CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def filtered_logger():
    capture = _CaptureHandler()
    log_filter = ContextFilter()
    logger = logging.getLogger(LOGGER_NAME + ".filtered")
    old_level = logger.level
    old_propagate = logger.propagate
    logger.addHandler(capture)
    logger.addFilter(log_filter)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        yield logger, capture
    finally:
        logger.removeHandler(capture)
        logger.removeFilter(log_filter)
        logger.setLevel(old_level)
        logger.propagate = old_propagate


class TestJsonlFieldContract:
    def test_emits_exactly_the_contract_fields(self):
        record = _record("ingested %d chunks", (12,), log_context={"task_id": "t-1"})
        entry = json.loads(JsonlFormatter().format(record))
        assert set(entry) == {"timestamp", "level", "logger", "message", "context"}
        assert entry["level"] == "INFO"
        assert entry["logger"] == LOGGER_NAME
        assert entry["message"] == "ingested 12 chunks"
        assert entry["context"] == {"task_id": "t-1"}

    def test_timestamp_is_utc_iso8601_derived_from_record_created(self):
        fixed = 1760000000.25
        record = _record("hello", created=fixed)
        entry = json.loads(JsonlFormatter().format(record))
        expected = datetime.fromtimestamp(fixed, timezone.utc).isoformat()
        assert entry["timestamp"] == expected
        assert entry["timestamp"].endswith("+00:00")
        assert datetime.fromisoformat(entry["timestamp"]).tzinfo is timezone.utc

    def test_level_field_uses_levelname(self):
        entry = json.loads(JsonlFormatter().format(_record("x", level=logging.WARNING)))
        assert entry["level"] == "WARNING"

    def test_exception_goes_to_dedicated_field_and_output_stays_single_line(self):
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            exc_info = sys.exc_info()
        record = _record("failed", exc_info=exc_info)
        out = JsonlFormatter().format(record)
        entry = json.loads(out)
        assert entry["message"] == "failed"
        assert "Traceback (most recent call last)" in entry["exception"]
        assert "RuntimeError: boom" in entry["exception"]
        assert "\n" not in out

    def test_non_ascii_message_is_written_unescaped(self):
        record = _record("知识库 ingestion 完成")
        out = JsonlFormatter().format(record)
        assert "知识库 ingestion 完成" in out
        assert json.loads(out)["message"] == "知识库 ingestion 完成"

    def test_unserializable_context_value_is_coerced_via_str(self):
        sentinel = object()
        record = _record("m", log_context={"request_id": sentinel})
        entry = json.loads(JsonlFormatter().format(record))
        assert entry["context"]["request_id"] == str(sentinel)


class TestMissingContextFields:
    def test_jsonl_defaults_to_empty_context_without_log_context_attribute(self):
        entry = json.loads(JsonlFormatter().format(_record("m")))
        assert entry["context"] == {}

    def test_jsonl_treats_none_log_context_as_empty(self):
        entry = json.loads(JsonlFormatter().format(_record("m", log_context=None)))
        assert entry["context"] == {}

    def test_console_omits_stage_and_task_without_context(self):
        out = ConsoleFormatter().format(_record("m"))
        assert "@" not in out
        assert "#" not in out

    def test_console_tolerates_none_context(self):
        out = ConsoleFormatter().format(_record("m", log_context=None))
        assert "@" not in out
        assert "#" not in out

    def test_console_omits_only_the_missing_suffix_for_partial_context(self):
        with_task = ConsoleFormatter().format(
            _record("m", log_context={"task_id": "t-9"})
        )
        assert " #t-9" in with_task
        assert "@" not in with_task
        with_stage = ConsoleFormatter().format(
            _record("m", log_context={"stage": "indexing"})
        )
        assert " @indexing" in with_stage
        assert "#" not in with_stage

    def test_console_ignores_falsy_stage_and_task_values(self):
        out = ConsoleFormatter().format(
            _record("m", log_context={"stage": "", "task_id": 0})
        )
        assert "@" not in out
        assert "#" not in out


class TestContextFilter:
    def test_without_bound_context_records_get_empty_context(self, filtered_logger):
        logger, capture = filtered_logger
        logger.info("no context")
        assert capture.records[0].log_context == {}

    def test_attaches_bound_fields_to_every_record(self, filtered_logger):
        logger, capture = filtered_logger
        with bind_log_context(request_id="req-7", stage="indexing"):
            logger.info("with context")
        assert capture.records[0].log_context == {
            "request_id": "req-7",
            "stage": "indexing",
        }

    def test_explicit_record_fields_win_over_bound_context(self, filtered_logger):
        logger, capture = filtered_logger
        with bind_log_context(request_id="req-7", stage="bound"):
            logger.info("m", extra={"stage": "explicit"})
        assert capture.records[0].log_context == {
            "request_id": "req-7",
            "stage": "explicit",
        }

    def test_none_valued_record_fields_do_not_shadow_bound_context(
        self, filtered_logger
    ):
        logger, capture = filtered_logger
        with bind_log_context(task_id="t-1"):
            logger.info("m", extra={"task_id": None, "capability": "rag"})
        assert capture.records[0].log_context == {
            "task_id": "t-1",
            "capability": "rag",
        }

    def test_filter_never_drops_records(self, filtered_logger):
        logger, capture = filtered_logger
        logger.warning("still delivered")
        assert len(capture.records) == 1
        assert all(key in LOG_CONTEXT_FIELDS for key in ("task_id", "capability"))


def test_jsonl_pipeline_writes_one_contract_line_per_record(tmp_path):
    log_file = tmp_path / "contract.jsonl"
    logger = logging.getLogger(LOGGER_NAME + ".file")
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(JsonlFormatter())
    context_filter = ContextFilter()
    old_handlers = logger.handlers[:]
    old_level = logger.level
    old_propagate = logger.propagate
    logger.addHandler(handler)
    logger.addFilter(context_filter)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        with bind_log_context(request_id="req-42", stage="emit"):
            logger.warning("wrote %d entries", 3)
    finally:
        handler.flush()
        handler.close()
        logger.removeHandler(handler)
        logger.removeFilter(context_filter)
        logger.setLevel(old_level)
        logger.propagate = old_propagate

    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert set(entry) == {"timestamp", "level", "logger", "message", "context"}
    assert entry["level"] == "WARNING"
    assert entry["message"] == "wrote 3 entries"
    assert entry["context"] == {"request_id": "req-42", "stage": "emit"}


class TestConsoleSnapshot:
    def test_info_line_with_stage_then_task_suffix(self):
        record = _record(
            "chunked %d pages",
            (7,),
            log_context={"stage": "indexing", "task_id": "t-1"},
        )
        out = ConsoleFormatter().format(record)
        assert (
            out
            == "INFO    deeptutor.test.formatters_contract @indexing #t-1 - chunked 7 pages"
        )

    def test_warning_line_at_exactly_seven_char_level_width(self):
        record = _record("disk nearly full", level=logging.WARNING)
        out = ConsoleFormatter().format(record)
        assert out == "WARNING deeptutor.test.formatters_contract - disk nearly full"

    def test_error_snapshot_keeps_message_line_before_traceback(self):
        try:
            raise ValueError("kaboom")
        except ValueError:
            exc_info = sys.exc_info()
        record = _record(
            "job died",
            level=logging.ERROR,
            exc_info=exc_info,
            log_context={"task_id": "t-2"},
        )
        out = ConsoleFormatter().format(record)
        first_line, _, rest = out.partition("\n")
        assert first_line == "ERROR   deeptutor.test.formatters_contract #t-2 - job died"
        assert rest.startswith("Traceback (most recent call last):")
        assert "ValueError: kaboom" in rest
