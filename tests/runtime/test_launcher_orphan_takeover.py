"""Regression coverage for the interrupted-shutdown orphan scenario (#1795).

A launcher killed between stopping the frontend and stopping the backend
left the backend orphaned and holding its port; the next non-interactive
start then exited on the port check instead of reclaiming it, which under a
KeepAlive supervisor loops forever. These tests use fake child processes
(short-lived sleepers) and simulated port occupancy — no real backend,
frontend or daemon is started.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

from deeptutor.runtime import launcher
from deeptutor.runtime.launcher import ManagedProcess, _ManagedStopper

OWN_BACKEND_COMMAND = (
    "/Users/alpha/deeptutor/.venv/bin/python -m uvicorn "
    "deeptutor.api.main:app --host 0.0.0.0 --port 8001 --log-level info"
)
NEXT_FRONTEND_COMMAND = "node /opt/deeptutor/web/node_modules/next/dist/bin/next dev"
FOREIGN_COMMAND = "/usr/local/bin/python -m http.server 8001"


def _spawn_sleeper(name: str) -> ManagedProcess:
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return ManagedProcess(name=name, process=process, pgid=launcher._get_pgid(process.pid))


def _reap(proc: ManagedProcess) -> None:
    if proc.process.poll() is None:
        proc.process.kill()
    proc.process.wait(timeout=10)


# --- cleanup: signal as a unit, re-enterable -------------------------------


def test_stopper_signals_every_child_before_waiting_on_any(monkeypatch) -> None:
    """Both trees get SIGTERM before the stopper blocks on any child exit."""
    backend = _spawn_sleeper("backend")
    frontend = _spawn_sleeper("frontend")
    procs = [backend, frontend]
    events: list[str] = []
    real_signal = launcher._send_tree_signal

    def recording_signal(pid: int, pgid: int | None, sig: int) -> None:
        events.append(f"signal:{pid}")
        real_signal(pid, pgid, sig)

    def recording_terminate(proc: ManagedProcess | None) -> None:
        if proc is not None:
            events.append(f"wait:{proc.process.pid}")

    monkeypatch.setattr(launcher, "_send_tree_signal", recording_signal)
    monkeypatch.setattr(launcher, "_terminate", recording_terminate)

    try:
        _ManagedStopper().stop(procs)
    finally:
        for proc in procs:
            _reap(proc)

    first_wait = next(index for index, event in enumerate(events) if event.startswith("wait:"))
    signaled = [event for event in events[:first_wait] if event.startswith("signal:")]
    assert {event.split(":")[1] for event in signaled} == {str(proc.process.pid) for proc in procs}
    # The backend — the child whose survival orphans the installation — is
    # signalled first.
    assert events[0] == f"signal:{backend.process.pid}"


def test_stopper_interrupted_pass_still_signals_backend(monkeypatch) -> None:
    """A stop interrupted before any wait still delivered SIGTERM to both
    children, so neither can survive as an orphan (#1795)."""
    backend = _spawn_sleeper("backend")
    frontend = _spawn_sleeper("frontend")
    procs = [backend, frontend]

    def interrupted_terminate(proc: ManagedProcess | None) -> None:
        raise RuntimeError("interrupted mid-cleanup")

    monkeypatch.setattr(launcher, "_terminate", interrupted_terminate)

    stopper = _ManagedStopper()
    try:
        with pytest.raises(RuntimeError):
            stopper.stop(procs)

        # Both sleepers already received SIGTERM and exit on their own even
        # though no wait ever ran.
        for proc in procs:
            proc.process.wait(timeout=10)
    finally:
        for proc in procs:
            _reap(proc)


def test_stopper_resumed_pass_finishes_remaining_child(monkeypatch) -> None:
    """Re-entering an interrupted stop stops the child the first pass never
    reached, instead of returning early."""
    backend = _spawn_sleeper("backend")
    frontend = _spawn_sleeper("frontend")
    procs = [backend, frontend]
    waited: list[int] = []
    signals: list[int] = []
    real_terminate = launcher._terminate
    real_signal = launcher._send_tree_signal

    def recording_signal(pid: int, pgid: int | None, sig: int) -> None:
        signals.append(pid)
        real_signal(pid, pgid, sig)

    def terminate_once(proc: ManagedProcess | None) -> None:
        if proc is not None:
            waited.append(proc.process.pid)
        if len(waited) == 1:
            raise RuntimeError("interrupted after first wait")

    monkeypatch.setattr(launcher, "_send_tree_signal", recording_signal)
    monkeypatch.setattr(launcher, "_terminate", terminate_once)

    stopper = _ManagedStopper()
    try:
        with pytest.raises(RuntimeError):
            stopper.stop(procs)
        # The interruption happened after the first child's wait only.
        assert waited == [backend.process.pid]

        monkeypatch.setattr(launcher, "_terminate", real_terminate)
        stopper.stop(procs)

        # The resumed pass converged both children — the one the first pass
        # stopped and the one it never reached.
        for proc in procs:
            proc.process.wait(timeout=10)
        assert set(signals) == {proc.process.pid for proc in procs}
    finally:
        for proc in procs:
            _reap(proc)


def test_stopper_second_full_pass_is_a_noop() -> None:
    """A completed stop can be re-entered harmlessly (finally + atexit)."""
    backend = _spawn_sleeper("backend")
    frontend = _spawn_sleeper("frontend")
    procs = [backend, frontend]
    signals: list[int] = []

    real_signal = launcher._send_tree_signal

    def recording_signal(pid: int, pgid: int | None, sig: int) -> None:
        signals.append(pid)
        real_signal(pid, pgid, sig)

    launcher._send_tree_signal = recording_signal
    try:
        stopper = _ManagedStopper()
        stopper.stop(procs)
        for proc in procs:
            proc.process.wait(timeout=10)
        first_pass_signals = list(signals)

        stopper.stop(procs)

        assert signals == first_pass_signals
    finally:
        launcher._send_tree_signal = real_signal
        for proc in procs:
            _reap(proc)


# --- ownership matchers -----------------------------------------------------


def test_is_own_backend_listener_matches_launcher_spawned_uvicorn() -> None:
    assert launcher._is_own_backend_listener(OWN_BACKEND_COMMAND)
    assert not launcher._is_own_backend_listener(FOREIGN_COMMAND)
    assert not launcher._is_own_backend_listener("?")
    assert not launcher._is_own_backend_listener("")


def test_looks_like_next_command_matches_next_processes() -> None:
    assert launcher._looks_like_next_command(NEXT_FRONTEND_COMMAND)
    assert launcher._looks_like_next_command("next-server (v15.1.6)")
    assert not launcher._looks_like_next_command(FOREIGN_COMMAND)
    assert not launcher._looks_like_next_command("")
    assert not launcher._looks_like_next_command("?")


# --- non-interactive restart: reclaim instead of exit ------------------------


def test_non_tty_start_reclaims_orphaned_own_backend(tmp_path: Path, monkeypatch) -> None:
    """A supervised restart takes over a leftover backend of this
    installation instead of exiting (#1795)."""
    occupied = {8001}
    killed: list[int] = []
    monkeypatch.setattr(launcher, "_port_accepts_connection", lambda port: port in occupied)
    monkeypatch.setattr(
        launcher,
        "_port_listeners",
        lambda port: [(1919, OWN_BACKEND_COMMAND)] if port == 8001 else [],
    )

    def fake_signal(pid: int, pgid: int | None, sig: int) -> None:
        killed.append(pid)
        occupied.clear()

    monkeypatch.setattr(launcher, "_send_tree_signal", fake_signal)
    monkeypatch.setattr(launcher.sys, "stdin", None)

    result = launcher._resolve_port_conflicts(
        backend_port=8001,
        frontend_port=3782,
        check_frontend=True,
        settings_dir=tmp_path,
    )

    assert result == (8001, 3782)
    assert killed == [1919]


def test_non_tty_start_still_exits_for_foreign_listener(tmp_path: Path, monkeypatch) -> None:
    occupied = {8001}
    killed: list[int] = []
    monkeypatch.setattr(launcher, "_port_accepts_connection", lambda port: port in occupied)
    monkeypatch.setattr(
        launcher,
        "_port_listeners",
        lambda port: [(4242, FOREIGN_COMMAND)] if port == 8001 else [],
    )
    monkeypatch.setattr(launcher, "_send_tree_signal", lambda pid, pgid, sig: killed.append(pid))
    monkeypatch.setattr(launcher.sys, "stdin", None)

    with pytest.raises(SystemExit) as excinfo:
        launcher._resolve_port_conflicts(
            backend_port=8001,
            frontend_port=3782,
            check_frontend=True,
            settings_dir=tmp_path,
        )

    assert "8001" in str(excinfo.value)
    assert killed == []


def test_non_tty_start_exits_when_own_and_foreign_share_the_port(
    tmp_path: Path, monkeypatch
) -> None:
    """A foreign process mixed in is never killed unattended."""
    occupied = {8001}
    killed: list[int] = []
    monkeypatch.setattr(launcher, "_port_accepts_connection", lambda port: port in occupied)
    monkeypatch.setattr(
        launcher,
        "_port_listeners",
        lambda port: [(1919, OWN_BACKEND_COMMAND), (4242, FOREIGN_COMMAND)] if port == 8001 else [],
    )
    monkeypatch.setattr(launcher, "_send_tree_signal", lambda pid, pgid, sig: killed.append(pid))
    monkeypatch.setattr(launcher.sys, "stdin", None)

    with pytest.raises(SystemExit):
        launcher._resolve_port_conflicts(
            backend_port=8001,
            frontend_port=3782,
            check_frontend=True,
            settings_dir=tmp_path,
        )

    assert killed == []


def test_non_tty_start_exits_for_unidentified_listener(tmp_path: Path, monkeypatch) -> None:
    """Ownership must be positively established; unknown means foreign."""
    occupied = {8001}
    monkeypatch.setattr(launcher, "_port_accepts_connection", lambda port: port in occupied)
    monkeypatch.setattr(launcher, "_port_listeners", lambda port: [(1, "?")])
    monkeypatch.setattr(launcher.sys, "stdin", None)

    with pytest.raises(SystemExit):
        launcher._resolve_port_conflicts(
            backend_port=8001,
            frontend_port=3782,
            check_frontend=True,
            settings_dir=tmp_path,
        )


def test_non_tty_start_reclaims_next_frontend(tmp_path: Path, monkeypatch) -> None:
    occupied = {3782}
    killed: list[int] = []
    monkeypatch.setattr(launcher, "_port_accepts_connection", lambda port: port in occupied)
    monkeypatch.setattr(
        launcher,
        "_port_listeners",
        lambda port: [(1925, NEXT_FRONTEND_COMMAND)] if port == 3782 else [],
    )

    def fake_signal(pid: int, pgid: int | None, sig: int) -> None:
        killed.append(pid)
        occupied.clear()

    monkeypatch.setattr(launcher, "_send_tree_signal", fake_signal)
    monkeypatch.setattr(launcher.sys, "stdin", None)

    result = launcher._resolve_port_conflicts(
        backend_port=8001,
        frontend_port=3782,
        check_frontend=True,
        settings_dir=tmp_path,
    )

    assert result == (8001, 3782)
    assert killed == [1925]


def test_non_tty_start_exits_when_reclaim_fails(tmp_path: Path, monkeypatch) -> None:
    """Reclaim is attempted exactly once; a listener that survives it keeps
    the historical exit instead of looping."""
    occupied = {8001}
    attempts: list[int] = []
    monkeypatch.setattr(launcher, "_port_accepts_connection", lambda port: port in occupied)
    monkeypatch.setattr(
        launcher,
        "_port_listeners",
        lambda port: [(1919, OWN_BACKEND_COMMAND)] if port == 8001 else [],
    )
    monkeypatch.setattr(
        launcher,
        "_kill_port_listeners",
        lambda listeners: attempts.extend(sorted(listeners)),
    )
    monkeypatch.setattr(launcher.sys, "stdin", None)

    with pytest.raises(SystemExit) as excinfo:
        launcher._resolve_port_conflicts(
            backend_port=8001,
            frontend_port=3782,
            check_frontend=True,
            settings_dir=tmp_path,
        )

    assert "8001" in str(excinfo.value)
    assert attempts == [8001]


def test_tty_path_still_prompts_instead_of_reclaiming(tmp_path: Path, monkeypatch) -> None:
    """Interactive sessions keep the explicit change-or-kill prompt."""
    import builtins

    class _RealTty:
        def isatty(self) -> bool:
            return True

    def _refuse_prompt(prompt: str = "") -> str:
        raise AssertionError("interactive path must prompt instead of auto-reclaiming")

    monkeypatch.setattr(launcher, "_port_accepts_connection", lambda port: port == 8001)
    monkeypatch.setattr(
        launcher,
        "_port_listeners",
        lambda port: [(1919, OWN_BACKEND_COMMAND)] if port == 8001 else [],
    )
    monkeypatch.setattr(launcher.sys, "stdin", _RealTty())
    monkeypatch.setattr(builtins, "input", _refuse_prompt)

    with pytest.raises(AssertionError):
        launcher._resolve_port_conflicts(
            backend_port=8001,
            frontend_port=3782,
            check_frontend=True,
            settings_dir=tmp_path,
        )
