"""Regression tests for the mimic-question stdout tee (``StdoutInterceptor``).

The interceptor is created inside ``websocket_mimic_generate``
(``deeptutor/api/routers/question.py``) and tees every ``print`` to two
sinks: the real terminal (``original_stdout.write``) and the frontend log
queue. Both forwarding attempts are wrapped in ``except: pass``-style
swallows (todo-scan evidence §7: ``question.py:131`` for the terminal write,
``:153`` for ``flush``), so a failing terminal silently loses that half of
the tee. These tests lock the *current* behavior:

1. normal forwarding — raw text (ANSI codes intact) reaches the terminal,
   ANSI-stripped text reaches the frontend;
2. a raising terminal ``write`` does not crash the task and the frontend
   copy still goes out;
3. that terminal failure leaves **no** log record at any level — the
   observability gap itself is pinned here, so a future fix that adds a
   warning must update this test on purpose;
4. a raising terminal ``flush`` is swallowed the same way.

No product code is modified: the router module is imported exactly as in
``tests/api/test_question_router.py`` (same stubbed import environment) and
exercised through the WebSocket endpoint with the generation seam
(``mimic_exam_questions``) replaced by a stub that prints.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import importlib
import logging
from pathlib import Path
import sys
import types

import pytest

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient

_QUESTION_LOGGER = "deeptutor.api.routers.question"

# Distinctive marker strings so the swallowing assertions can prove the
# failure left no trace in any log record.
_WRITE_FAILURE_TEXT = "tee terminal write gone"
_FLUSH_FAILURE_TEXT = "tee terminal flush gone"
_PRINT_MARKERS = {
    "plain": "tee plain stdout line",
    "ansi": "tee \x1b[31mcolored\x1b[0m line",
}


@pytest.fixture(autouse=True)
def _cleanup_question_router_module():
    yield
    sys.modules.pop("deeptutor.api.routers.question", None)


class _DummyProcessLogEvent:
    def __init__(self, **kwargs) -> None:
        self.data = {"type": "process_log", **kwargs}

    def to_dict(self):
        return self.data


@contextmanager
def _noop_context(*_args, **_kwargs):
    yield


def _package(name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__path__ = []
    return module


def _fake_config_module() -> types.ModuleType:
    """Stand in for ``deeptutor.services.config``; defers everything else.

    Same approach as ``tests/api/test_question_router.py``: only the two
    names the question router reads at import time are overridden; other
    attributes resolve to the real module, because the websocket handler
    lazily imports ``deeptutor.api.routers.auth`` out of related packages.
    """
    real = importlib.import_module("deeptutor.services.config")
    module = types.ModuleType("deeptutor.services.config")
    module.__getattr__ = lambda name: getattr(real, name)  # PEP 562
    module.PROJECT_ROOT = Path.cwd()
    module.load_config_with_main = lambda *_args, **_kwargs: {}
    return module


def _load_question_router_module(monkeypatch: pytest.MonkeyPatch):
    sys.modules.pop("deeptutor.api.routers.question", None)

    fake_logging = _package("deeptutor.logging")
    fake_logging.ProcessLogEvent = _DummyProcessLogEvent
    fake_logging.bind_log_context = _noop_context
    fake_logging.capture_process_logs = _noop_context
    fake_logging.current_log_context = lambda: {}
    monkeypatch.setitem(sys.modules, "deeptutor.logging", fake_logging)

    monkeypatch.setitem(sys.modules, "deeptutor.services.config", _fake_config_module())

    return importlib.import_module("deeptutor.api.routers.question")


def _build_app(router_module) -> FastAPI:
    app = FastAPI()
    app.include_router(router_module.router, prefix="/api/question")
    app.include_router(router_module.ws_router, prefix="/ws/questions")
    return app


class _TerminalStub:
    """Stand-in for the real terminal stream the interceptor tees into.

    ``write``/``flush`` can be rigged to raise, simulating a broken or
    closed terminal (EIO-style failures that the interceptor must survive).
    """

    def __init__(
        self,
        write_error: Exception | None = None,
        flush_error: Exception | None = None,
    ) -> None:
        self.writes: list[str] = []
        self.flush_count = 0
        self._write_error = write_error
        self._flush_error = flush_error

    def write(self, message: str) -> int:
        if self._write_error is not None:
            raise self._write_error
        self.writes.append(message)
        return len(message)

    def flush(self) -> None:
        if self._flush_error is not None:
            raise self._flush_error
        self.flush_count += 1


async def _drain_loop_turns(turns: int = 8) -> None:
    """Yield to the event loop so the log-pusher task can drain the queue."""
    for _ in range(turns):
        await asyncio.sleep(0)


def _run_mimic_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    terminal: _TerminalStub,
    mimic_stub,
):
    monkeypatch.setattr(sys, "stdout", terminal)
    router_module = _load_question_router_module(monkeypatch)
    monkeypatch.setattr(router_module, "mimic_exam_questions", mimic_stub)
    monkeypatch.setattr(router_module, "_mimic_output_dir", lambda: tmp_path / "mimic_papers")

    messages: list[dict] = []
    with TestClient(_build_app(router_module)) as client:
        with client.websocket_connect("/ws/questions/mimic") as websocket:
            websocket.send_json(
                {
                    "mode": "parsed",
                    "paper_path": str(tmp_path / "paper"),
                    "kb_name": "demo-kb",
                    "max_questions": 1,
                }
            )
            while True:
                message = websocket.receive_json()
                messages.append(message)
                if message.get("type") in {"complete", "error"}:
                    break
    return messages


def _process_logs(messages: list[dict]) -> list[str]:
    return [
        message.get("message", "") for message in messages if message.get("type") == "process_log"
    ]


def test_stdout_tee_forwards_print_to_terminal_and_frontend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    terminal = _TerminalStub()

    async def mimic_stub(**_kwargs):
        print(_PRINT_MARKERS["plain"])
        print(_PRINT_MARKERS["ansi"])
        await _drain_loop_turns()
        return {"success": True}

    messages = _run_mimic_session(monkeypatch, tmp_path, terminal, mimic_stub)

    # Terminal half of the tee: raw text, ANSI escape codes intact.
    joined_raw = "".join(terminal.writes)
    assert _PRINT_MARKERS["plain"] in joined_raw
    assert "\x1b[31mcolored\x1b[0m" in joined_raw

    # Frontend half: ANSI-stripped, whitespace-trimmed copies.
    forwarded = "".join(_process_logs(messages))
    assert _PRINT_MARKERS["plain"] in forwarded
    assert "tee colored line" in forwarded
    assert "\x1b[" not in forwarded

    assert messages[-1]["type"] == "complete"


def test_terminal_write_failure_does_not_crash_and_frontend_copy_survives(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    terminal = _TerminalStub(write_error=OSError(5, _WRITE_FAILURE_TEXT))

    async def mimic_stub(**_kwargs):
        print(_PRINT_MARKERS["plain"])
        await _drain_loop_turns()
        return {"success": True}

    messages = _run_mimic_session(monkeypatch, tmp_path, terminal, mimic_stub)

    # The raising terminal swallowed the write, nothing reached it.
    assert terminal.writes == []

    # The task kept running: the frontend copy still went out and the
    # generation finished with the regular complete signal (no error event).
    assert _PRINT_MARKERS["plain"] in "".join(_process_logs(messages))
    assert messages[-1]["type"] == "complete"


def test_terminal_write_failure_leaves_no_log_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Pins the observability gap at ``question.py:131``.

    Today a failing terminal write is swallowed with ``except Exception:
    pass`` and nothing is recorded anywhere. This assertion deliberately
    locks that gap; when the swallow is fixed to log a warning, this test
    must be updated in the same change.
    """
    terminal = _TerminalStub(write_error=OSError(5, _WRITE_FAILURE_TEXT))

    async def mimic_stub(**_kwargs):
        print(_PRINT_MARKERS["plain"])
        await _drain_loop_turns()
        return {"success": True}

    with caplog.at_level(logging.DEBUG):
        messages = _run_mimic_session(monkeypatch, tmp_path, terminal, mimic_stub)

    assert messages[-1]["type"] == "complete"

    # No record at any level mentioned the failure or even the logged line.
    assert not [
        record
        for record in caplog.records
        if _WRITE_FAILURE_TEXT in record.getMessage()
        or _PRINT_MARKERS["plain"] in record.getMessage()
    ]
    # ...and the router logger stayed silent at warning level and above.
    assert not [
        record
        for record in caplog.records
        if record.name == _QUESTION_LOGGER and record.levelno >= logging.WARNING
    ]


def test_terminal_flush_failure_is_swallowed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Same swallow family at ``question.py:153``: ``flush`` must not raise."""
    terminal = _TerminalStub(flush_error=OSError(5, _FLUSH_FAILURE_TEXT))

    async def mimic_stub(**_kwargs):
        print(_PRINT_MARKERS["plain"])
        sys.stdout.flush()
        await _drain_loop_turns()
        return {"success": True}

    with caplog.at_level(logging.DEBUG):
        messages = _run_mimic_session(monkeypatch, tmp_path, terminal, mimic_stub)

    assert terminal.writes  # the write half still reached the terminal
    assert terminal.flush_count == 0  # the flush half failed...
    assert messages[-1]["type"] == "complete"  # ...and nothing crashed
    assert not [record for record in caplog.records if _FLUSH_FAILURE_TEXT in record.getMessage()]
