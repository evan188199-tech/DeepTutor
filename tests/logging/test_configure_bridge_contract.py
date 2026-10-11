"""Focused contract tests for the logging assembly layer.

Covers ``deeptutor.logging.configure`` (handler assembly idempotency, level and
path parameter contracts, force reassembly) and ``deeptutor.logging.loguru_bridge``
(forwarding contract, level threshold, exception forwarding, and the missing
loguru branch). All file output goes to ``tmp_path`` — never the real log dir.
"""

from __future__ import annotations

import importlib
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

import pytest

from deeptutor.logging import LoggingConfig
from deeptutor.logging.formatters import ContextFilter
from deeptutor.logging.loguru_bridge import install_loguru_bridge

CONFIGURE = importlib.import_module("deeptutor.logging.configure")


@pytest.fixture(autouse=True)
def _reset_configure_state():
    """Keep module globals hermetic: no managed handlers, never pre-configured."""
    CONFIGURE._CONFIGURED = False
    CONFIGURE._remove_managed_handlers(logging.getLogger())
    yield
    CONFIGURE._CONFIGURED = False
    CONFIGURE._remove_managed_handlers(logging.getLogger())


def _managed_handlers() -> list[logging.Handler]:
    return [
        handler
        for handler in logging.getLogger().handlers
        if getattr(handler, CONFIGURE._MANAGED_ATTR, False)
    ]


def _file_config(tmp_path: Path, **overrides) -> LoggingConfig:
    defaults = {
        "level": "INFO",
        "console_output": True,
        "file_output": True,
        "log_dir": str(tmp_path),
        "max_bytes": 1024 * 1024,
        "backup_count": 1,
    }
    defaults.update(overrides)
    return LoggingConfig(**defaults)


class _RecordCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


# ---------------------------------------------------------------------------
# configure.py — handler assembly idempotency
# ---------------------------------------------------------------------------


def test_configure_logging_is_idempotent_without_force(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(CONFIGURE, "load_logging_config", lambda: _file_config(tmp_path))

    first = CONFIGURE.configure_logging(force=True)
    root = logging.getLogger()
    handlers_after_first = list(root.handlers)

    assert len(_managed_handlers()) == 2  # console + file
    assert root.level == logging.DEBUG
    deeptutor_logger = logging.getLogger("deeptutor")
    assert deeptutor_logger.level == logging.DEBUG
    assert deeptutor_logger.propagate is True

    for _ in range(2):
        again = CONFIGURE.configure_logging()
        assert again == first
        assert list(root.handlers) == handlers_after_first
    assert len(_managed_handlers()) == 2


def test_configure_logging_force_replaces_managed_handlers(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(CONFIGURE, "load_logging_config", lambda: _file_config(tmp_path))

    CONFIGURE.configure_logging(force=True)
    old = _managed_handlers()
    old_file = next(h for h in old if isinstance(h, RotatingFileHandler))

    second = CONFIGURE.configure_logging(force=True)
    assert isinstance(second, LoggingConfig)
    new = _managed_handlers()

    assert len(old) == 2
    assert len(new) == 2
    assert {id(h) for h in new}.isdisjoint({id(h) for h in old})
    assert old_file.stream is None  # replaced handler was closed
    for handler in new:
        assert any(isinstance(f, ContextFilter) for f in handler.filters)


def test_configure_logging_without_outputs_adds_no_handlers(monkeypatch):
    bridge_calls: list[int] = []

    def _spy_install(level: int) -> bool:
        bridge_calls.append(level)
        return False

    monkeypatch.setattr(
        CONFIGURE,
        "load_logging_config",
        lambda: LoggingConfig(file_output=False, console_output=False),
    )
    monkeypatch.setattr(CONFIGURE, "install_loguru_bridge", _spy_install)

    config = CONFIGURE.configure_logging(force=True)

    assert isinstance(config, LoggingConfig)
    assert _managed_handlers() == []
    assert logging.getLogger().level == logging.DEBUG
    assert bridge_calls == [logging.DEBUG]


# ---------------------------------------------------------------------------
# configure.py — level and path parameter contracts
# ---------------------------------------------------------------------------


def test_level_helper_contract():
    assert CONFIGURE._level(logging.WARNING) == logging.WARNING
    assert CONFIGURE._level(25) == 25
    assert CONFIGURE._level("warning") == logging.WARNING
    assert CONFIGURE._level("not-a-real-level") == logging.INFO


def test_configure_logging_applies_level_to_handlers(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        CONFIGURE,
        "load_logging_config",
        lambda: _file_config(tmp_path, level="warning", console_output=True, file_output=False),
    )

    CONFIGURE.configure_logging(force=True)

    console = _managed_handlers()[0]
    assert console.level == logging.WARNING
    assert logging.getLogger().level == logging.DEBUG  # root always stays DEBUG


def test_configure_logging_default_log_dir_fallback(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    created: dict = {}

    class _RecordingHandler(logging.Handler):
        def __init__(self, filename, maxBytes=0, backupCount=0, encoding=None):
            super().__init__()
            created["path"] = Path(filename)
            created["kwargs"] = {
                "maxBytes": maxBytes,
                "backupCount": backupCount,
                "encoding": encoding,
            }

    monkeypatch.setattr(CONFIGURE, "RotatingFileHandler", _RecordingHandler)
    monkeypatch.setattr(
        CONFIGURE,
        "load_logging_config",
        lambda: _file_config(tmp_path, console_output=False, file_output=True, log_dir=None),
    )

    CONFIGURE.configure_logging(force=True)

    assert created["path"] == Path("data/user/logs") / "deeptutor.jsonl"
    assert created["kwargs"] == {"maxBytes": 1024 * 1024, "backupCount": 1, "encoding": "utf-8"}
    # Default directory is derived under the CWD and no log file is written.
    assert (tmp_path / "data" / "user" / "logs").is_dir()
    assert not created["path"].exists()


# ---------------------------------------------------------------------------
# loguru_bridge.py — forwarding and exception branches
# ---------------------------------------------------------------------------


@pytest.fixture
def capture():
    pytest.importorskip("loguru")
    handler = _RecordCapture()
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        yield handler
    finally:
        root.removeHandler(handler)
        loguru_logger = importlib.import_module("loguru").logger
        loguru_logger.remove()


def test_install_loguru_bridge_returns_false_without_loguru(monkeypatch):
    monkeypatch.setitem(sys.modules, "loguru", None)
    assert install_loguru_bridge(logging.DEBUG) is False


def test_bridge_forwards_name_level_message_and_extra(capture):
    loguru_logger = importlib.import_module("loguru").logger

    assert install_loguru_bridge(logging.DEBUG) is True
    loguru_logger.info("bridge hello")

    assert len(capture.records) == 1
    record = capture.records[0]
    assert record.name == __name__
    assert record.levelno == logging.INFO
    assert record.getMessage() == "bridge hello"
    assert record.loguru is True
    assert record.exc_info is None


def test_bridge_forwards_exception_info(capture):
    loguru_logger = importlib.import_module("loguru").logger

    assert install_loguru_bridge(logging.DEBUG) is True
    try:
        raise ValueError("boom")
    except ValueError:
        loguru_logger.exception("seed failed")

    assert len(capture.records) == 1
    record = capture.records[0]
    assert record.getMessage() == "seed failed"
    assert record.exc_info is not None
    assert record.exc_info[0] is ValueError
    assert record.exc_info[1].args == ("boom",)


def test_bridge_respects_level_threshold(capture):
    loguru_logger = importlib.import_module("loguru").logger

    assert install_loguru_bridge(logging.WARNING) is True
    loguru_logger.info("too chatty")
    assert capture.records == []

    loguru_logger.warning("loud enough")
    assert [record.levelno for record in capture.records] == [logging.WARNING]


def test_bridge_install_twice_forwards_once(capture):
    loguru_logger = importlib.import_module("loguru").logger

    assert install_loguru_bridge(logging.DEBUG) is True
    assert install_loguru_bridge(logging.DEBUG) is True
    loguru_logger.info("single copy")

    assert [record.getMessage() for record in capture.records] == ["single copy"]
