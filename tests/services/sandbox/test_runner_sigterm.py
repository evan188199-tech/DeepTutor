"""SIGTERM/SIGINT shutdown pins for the sandbox runner HTTP server.

Signal audit #15: ``runner.server.main`` only catches ``KeyboardInterrupt``,
so SIGTERM hits the default disposition and kills the process before the
``finally: server_close()`` runs. These tests execute the real ``main()`` in
a subprocess (signal dispositions are process-wide) and record whether
``server_close`` executed:

* SIGINT  -> KeyboardInterrupt path: ``server_close`` runs, exit code 0.
* SIGTERM -> default disposition: process dies by SIGTERM and ``server_close``
  is skipped (current behaviour, pinned so a future fix must flip this test).

The child binds an ephemeral 127.0.0.1-only port; nothing is reachable from
outside the machine.
"""

from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request

import pytest

#: Repo root, so the child imports the worktree's own ``deeptutor`` copy.
_REPO_ROOT = str(Path(__file__).resolve().parents[3])

# The child runs main() as-is. The ThreadingHTTPServer subclass keeps the
# server code path identical but rewrites the bind address to loopback (and
# records the actually bound port), while a server_close wrapper appends to
# MARKER if and only if the cleanup hook executes.
_HARNESS = """
import os
import sys

sys.path.insert(0, sys.argv[1])
marker_path = sys.argv[2]
port_path = sys.argv[3]

from deeptutor.services.sandbox.runner import server

_Base = server.ThreadingHTTPServer


class _LoopbackOnly(_Base):
    def __init__(self, address, handler_cls):
        super().__init__(("127.0.0.1", address[1]), handler_cls)
        with open(port_path, "w", encoding="utf-8") as fh:
            fh.write(str(self.server_address[1]))


_original_close = _Base.server_close


def _traced_close(self):
    with open(marker_path, "a", encoding="utf-8") as fh:
        fh.write("server_close")
    _original_close(self)


_Base.server_close = _traced_close
server.ThreadingHTTPServer = _LoopbackOnly

os.environ["RUNNER_PORT"] = "0"
server.main()
"""


def _spawn_runner(tmp_path: Path, tag: str) -> tuple[subprocess.Popen[None], Path, Path]:
    marker = tmp_path / f"server-close-{tag}.marker"
    port_file = tmp_path / f"bound-port-{tag}.txt"
    proc = subprocess.Popen(
        [sys.executable, "-c", _HARNESS, _REPO_ROOT, str(marker), str(port_file)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    return proc, marker, port_file


def _wait_for_bound_port(proc: subprocess.Popen[None], port_file: Path) -> int:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if port_file.exists():
            text = port_file.read_text().strip()
            if text:
                return int(text)
        if proc.poll() is not None:
            stderr = proc.stderr.read() if proc.stderr else ""
            raise AssertionError(f"runner exited before binding a port: {stderr!r}")
        time.sleep(0.05)
    _stop(proc)
    raise AssertionError("runner did not bind a port within 30s")


def _wait_until_healthy(port: int) -> None:
    deadline = time.monotonic() + 10
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                if response.status == 200:
                    return
        except OSError as exc:
            last_error = exc
        time.sleep(0.05)
    raise AssertionError(f"runner never became healthy on 127.0.0.1:{port}: {last_error}")


def _signal_and_collect(proc: subprocess.Popen[None], signum: signal.Signals) -> int:
    proc.send_signal(signum)
    try:
        return proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise AssertionError(f"runner ignored signal {signum}") from None


def _stop(proc: subprocess.Popen[None]) -> None:
    if proc.poll() is None:
        proc.kill()
    proc.wait()


_POSIX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal semantics")


@_POSIX_ONLY
def test_sigterm_kills_runner_and_skips_server_close(tmp_path: Path) -> None:
    proc, marker, port_file = _spawn_runner(tmp_path, "sigterm")
    try:
        port = _wait_for_bound_port(proc, port_file)
        _wait_until_healthy(port)
        returncode = _signal_and_collect(proc, signal.SIGTERM)
    finally:
        _stop(proc)

    # Default SIGTERM disposition: death by signal, cleanup hook never ran.
    assert returncode == -signal.SIGTERM
    assert not marker.exists(), "server_close ran under SIGTERM; the #15 fix landed"


@_POSIX_ONLY
def test_sigint_still_runs_server_close(tmp_path: Path) -> None:
    proc, marker, port_file = _spawn_runner(tmp_path, "sigint")
    try:
        port = _wait_for_bound_port(proc, port_file)
        _wait_until_healthy(port)
        returncode = _signal_and_collect(proc, signal.SIGINT)
    finally:
        _stop(proc)

    # KeyboardInterrupt path: graceful shutdown, exactly as main() intends.
    assert returncode == 0
    assert marker.read_text() == "server_close"
