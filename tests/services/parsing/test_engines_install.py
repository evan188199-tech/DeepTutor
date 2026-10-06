"""Branch tests for the one-click engine install/download background jobs.

These cover ``deeptutor/services/parsing/engines/_install.py`` runtime
behaviour that the allow-list tests in ``test_engines.py`` do not reach:
concurrent-launch rejection, launch failures, pump outcomes (done / failed /
cancelled), log throttling and trimming, and the post-install cache
invalidation. No real subprocess is spawned and nothing is installed —
``subprocess.Popen`` is always faked.
"""

from __future__ import annotations

import os
import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.services.parsing.engines import _install


class FakeProcess:
    """Minimal Popen stand-in: an in-memory line stream and exit code."""

    def __init__(
        self,
        lines: list[str],
        returncode: int = 0,
        hold: Any = None,
        terminate_error: Exception | None = None,
    ) -> None:
        self._lines = list(lines)
        self._returncode = returncode
        self._hold = hold
        self._terminate_error = terminate_error
        self.stdout = self._stream()
        self.terminate_calls = 0

    def _stream(self):
        for line in self._lines:
            yield line
            if self._hold is not None:
                self._hold.wait(timeout=10)

    def poll(self) -> int | None:
        return None

    def wait(self) -> int:
        return self._returncode

    def terminate(self) -> None:
        self.terminate_calls += 1
        if self._terminate_error is not None:
            raise self._terminate_error
        if self._hold is not None:
            self._hold.set()


class SteppedProcess:
    """Line stream whose entries carry a fake-clock delay before each line."""

    def __init__(self, script: list[tuple[float, str]], clock: dict) -> None:
        self._script = script
        self._clock = clock
        self.stdout = self._stream()

    def _stream(self):
        for delay, line in self._script:
            self._clock["now"] += delay
            yield line

    def poll(self) -> int | None:
        return None

    def wait(self) -> int:
        return 0


def _wait_terminal(manager: _install.BackgroundJobManager, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = manager.status()
        if status["state"] != "running":
            return status
        time.sleep(0.01)
    pytest.fail("background job never reached a terminal state")


def _install_fake_popen(monkeypatch, process: FakeProcess | SteppedProcess) -> list[dict]:
    calls: list[dict] = []

    def fake_popen(cmd, **kwargs):
        calls.append({"cmd": cmd, **kwargs})
        return process

    monkeypatch.setattr(_install.subprocess, "Popen", fake_popen)
    return calls


def test_start_install_launches_pip_with_isolated_env(monkeypatch) -> None:
    calls = _install_fake_popen(monkeypatch, FakeProcess([]))
    manager = _install.BackgroundJobManager()

    result = manager.start_install(engine="liteparse", specs=["liteparse>=2.14.2"])
    status = _wait_terminal(manager)

    assert result == {"ok": True, "message": ""}
    assert calls[0]["cmd"] == [
        _install.sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "--no-input",
        "liteparse>=2.14.2",
    ]
    assert calls[0]["shell"] is False
    assert calls[0]["text"] is True
    assert calls[0]["stderr"] == _install.subprocess.STDOUT
    assert calls[0]["env"]["PIP_DISABLE_PIP_VERSION_CHECK"] == "1"
    assert calls[0]["env"]["PATH"] == os.environ.get("PATH", "")
    assert status["state"] == "done"
    assert status["kind"] == "install"
    assert status["engine"] == "liteparse"


def test_start_install_reports_done_and_runs_on_success(monkeypatch) -> None:
    on_success_calls: list[str] = []
    monkeypatch.setattr(
        _install, "_invalidate_import_caches", lambda: on_success_calls.append("hit")
    )
    monkeypatch.setattr(_install, "_LINE_MIN_INTERVAL", 0.0)
    process = FakeProcess(["Collecting liteparse", "Successfully installed liteparse-2.14.2"])
    _install_fake_popen(monkeypatch, process)
    manager = _install.BackgroundJobManager()

    manager.start_install(engine="liteparse", specs=["liteparse>=2.14.2"])
    status = _wait_terminal(manager)

    assert on_success_calls == ["hit"]
    assert status["state"] == "done"
    assert status["message"] == "Finished."
    assert status["lines"] == [
        "Collecting liteparse",
        "Successfully installed liteparse-2.14.2",
    ]
    assert status["next_cursor"] == 2


def test_nonzero_exit_marks_failed_and_skips_on_success(monkeypatch) -> None:
    on_success_calls: list[str] = []
    monkeypatch.setattr(
        _install, "_invalidate_import_caches", lambda: on_success_calls.append("hit")
    )
    monkeypatch.setattr(_install, "_LINE_MIN_INTERVAL", 0.0)
    process = FakeProcess(["ERROR: No matching distribution"], returncode=1)
    _install_fake_popen(monkeypatch, process)
    manager = _install.BackgroundJobManager()

    manager.start_install(engine="docling", specs=["docling>=2.123.1"])
    status = _wait_terminal(manager)

    assert on_success_calls == []
    assert status["state"] == "failed"
    assert status["message"] == "Exited with code 1."
    assert status["lines"] == ["ERROR: No matching distribution"]


def test_popen_failure_marks_job_failed(monkeypatch) -> None:
    def broken_popen(cmd, **kwargs):
        raise RuntimeError("pip is missing")

    monkeypatch.setattr(_install.subprocess, "Popen", broken_popen)
    manager = _install.BackgroundJobManager()

    result = manager.start_install(engine="markitdown", specs=["markitdown[all]>=0.1.7"])

    assert result["ok"] is False
    assert result["message"] == "Failed to launch: pip is missing"
    status = manager.status()
    assert status["state"] == "failed"
    assert status["kind"] == "install"
    assert status["engine"] == "markitdown"
    assert status["message"] == "Failed to launch: pip is missing"


def test_second_launch_rejected_while_job_running(monkeypatch) -> None:
    hold = threading.Event()
    process = FakeProcess(["working..."], hold=hold)
    calls = _install_fake_popen(monkeypatch, process)
    manager = _install.BackgroundJobManager()

    first = manager.start_install(engine="docling", specs=["docling>=2.123.1"])
    assert first == {"ok": True, "message": ""}
    assert manager.status()["state"] == "running"

    second = manager.start_install(engine="liteparse", specs=["liteparse>=2.14.2"])
    assert second["ok"] is False
    assert second["message"] == "A install is already running (docling)."
    assert len(calls) == 1

    hold.set()
    _wait_terminal(manager)


def test_model_download_shares_the_running_guard(monkeypatch) -> None:
    hold = threading.Event()
    process = FakeProcess(["docling-tools models download"], hold=hold)
    calls = _install_fake_popen(monkeypatch, process)
    manager = _install.BackgroundJobManager()

    first = manager.start_model_download(
        engine="docling", cmd=["docling-tools", "models", "download"]
    )
    assert first == {"ok": True, "message": ""}
    assert calls[0]["cmd"] == ["docling-tools", "models", "download"]

    blocked = manager.start_model_download(
        engine="docling", cmd=["docling-tools", "models", "download"]
    )
    assert blocked["ok"] is False
    assert blocked["message"] == "A models is already running (docling)."

    hold.set()
    status = _wait_terminal(manager)
    assert status["kind"] == "models"
    assert status["state"] == "done"


def test_cancel_terminates_running_job_and_marks_cancelled(monkeypatch) -> None:
    hold = threading.Event()
    process = FakeProcess(["downloading..."], hold=hold)
    _install_fake_popen(monkeypatch, process)
    manager = _install.BackgroundJobManager()

    started = manager.start_model_download(
        engine="docling", cmd=["docling-tools", "models", "download"]
    )
    assert started == {"ok": True, "message": ""}

    result = manager.cancel()
    assert result == {"ok": True, "message": ""}
    assert process.terminate_calls == 1

    status = _wait_terminal(manager)
    assert status["state"] == "cancelled"
    assert status["message"] == "Cancelled."

    assert manager.cancel() == {"ok": False, "message": "No job is running."}


def test_cancel_when_idle_reports_no_job() -> None:
    manager = _install.BackgroundJobManager()

    assert manager.cancel() == {"ok": False, "message": "No job is running."}


def test_cancel_reports_terminate_failure(monkeypatch) -> None:
    hold = threading.Event()
    process = FakeProcess(["working..."], hold=hold, terminate_error=OSError("already reaped"))
    _install_fake_popen(monkeypatch, process)
    manager = _install.BackgroundJobManager()

    assert manager.start_install(engine="liteparse", specs=["liteparse>=2.14.2"])["ok"] is True

    result = manager.cancel()
    assert result["ok"] is False
    assert "Failed to cancel" in result["message"]
    assert "already reaped" in result["message"]

    # Cancellation was still requested, so the job ends up marked cancelled.
    hold.set()
    status = _wait_terminal(manager)
    assert status["state"] == "cancelled"


def test_log_lines_throttled_truncated_and_blank_skipped(monkeypatch) -> None:
    clock = {"now": 1000.0}
    monkeypatch.setattr(_install, "time", SimpleNamespace(monotonic=lambda: clock["now"]))
    script = [
        (0.0, ""),  # blank -> dropped before throttling
        (0.0, "   "),  # whitespace-only -> dropped
        (0.0, "x" * 500),  # accepted, truncated to 300 chars
        (0.0, "too fast"),  # within the min interval -> dropped
        (1.0, "later"),  # after the interval -> accepted
    ]
    _install_fake_popen(monkeypatch, SteppedProcess(script, clock))
    manager = _install.BackgroundJobManager()

    manager.start_install(engine="liteparse", specs=["liteparse>=2.14.2"])
    status = _wait_terminal(manager)

    assert status["lines"] == ["x" * 300, "later"]
    assert status["next_cursor"] == 2


def test_log_overflow_trims_head_and_keeps_cursor_consistent() -> None:
    manager = _install.BackgroundJobManager()

    for i in range(_install._MAX_LINES + 50):
        manager._append(f"line-{i}")

    assert len(manager._lines) == _install._MAX_LINES
    assert manager._base == 50

    full = manager.status(0)
    assert len(full["lines"]) == _install._MAX_LINES
    assert full["lines"][0] == "line-50"
    assert full["lines"][-1] == f"line-{_install._MAX_LINES + 49}"
    assert full["next_cursor"] == _install._MAX_LINES + 50

    after = manager.status(60)
    assert after["lines"][0] == "line-60"
    assert after["next_cursor"] == _install._MAX_LINES + 50


def test_resolve_model_downloader_missing_everywhere_returns_none(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(_install.sys, "executable", str(tmp_path / "bin" / "python"))
    monkeypatch.setattr(_install.shutil, "which", lambda command, path=None: None)

    assert _install.resolve_model_downloader("docling") is None


def test_invalidate_import_caches_clears_versions_and_formats(monkeypatch) -> None:
    cleared: list[str] = []
    monkeypatch.setattr(
        _install.importlib, "invalidate_caches", lambda: cleared.append("importlib")
    )
    monkeypatch.setattr(
        _install.package_version, "cache_clear", lambda: cleared.append("package_version")
    )

    _install._invalidate_import_caches()

    assert cleared == ["importlib", "package_version"]


def test_invalidate_import_caches_swallows_errors(monkeypatch, caplog) -> None:
    def broken() -> None:
        raise RuntimeError("cache backend unavailable")

    monkeypatch.setattr(_install.package_version, "cache_clear", broken)

    with caplog.at_level("ERROR", logger="deeptutor.services.parsing.engines._install"):
        _install._invalidate_import_caches()

    assert "Post-install cache invalidation failed" in caplog.text
