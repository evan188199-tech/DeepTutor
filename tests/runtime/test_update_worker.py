from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import textwrap

import pytest

from deeptutor.runtime.update_worker import build_update_command, run_update_worker
from deeptutor.services.app_update import UpdateJob, UpdateJobStore

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _handoff_job(tmp_path: Path) -> tuple[UpdateJobStore, UpdateJob]:
    store = UpdateJobStore(tmp_path / "update")
    pending = store.create(current_version="1.6.1", target_version="1.7.0")
    home = tmp_path / "home"
    home.mkdir()
    job = store.prepare_handoff(
        pending.id,
        home=home,
        restart_argv=["start", "--home", str(home.resolve())],
    )
    return store, job


def test_worker_updates_then_restarts(tmp_path: Path) -> None:
    store, job = _handoff_job(tmp_path)
    captured: dict[str, object] = {}

    def run(command: list[str], cwd: Path, log_path: Path) -> int:
        captured.update(command=command, cwd=cwd, log_path=log_path)
        return 0

    def restart(value: UpdateJob, log_path: Path) -> None:
        captured.update(restart=value, restart_log=log_path)

    result = run_update_worker(
        store_root=store.root,
        parent_pid=123,
        wait_for_parent=lambda pid: captured.update(parent_pid=pid),
        command_runner=run,
        restart_launcher=restart,
    )

    assert result == 0
    assert captured["parent_pid"] == 123
    assert captured["command"] == build_update_command("1.7.0")
    assert isinstance(captured["restart"], UpdateJob)
    assert store.load().status == "restarting"
    assert store.load().restart_count == 1


def test_worker_failure_is_durable_and_restores_app(tmp_path: Path) -> None:
    store, _job = _handoff_job(tmp_path)
    restarted: list[UpdateJob] = []

    result = run_update_worker(
        store_root=store.root,
        parent_pid=123,
        wait_for_parent=lambda _pid: None,
        command_runner=lambda _command, _cwd, _log: 7,
        restart_launcher=lambda value, _log: restarted.append(value),
    )

    assert result == 1
    assert store.load().status == "failed"
    assert store.load().error == "pip exited with status 7"
    assert restarted and restarted[0].status == "failed"


def test_worker_records_pid_while_running_and_clears_it_after(tmp_path: Path) -> None:
    store, _job = _handoff_job(tmp_path)
    observed: list[int | None] = []

    def run(command: list[str], cwd: Path, log_path: Path) -> int:
        observed.append(store.read_worker_pid())
        return 0

    result = run_update_worker(
        store_root=store.root,
        parent_pid=123,
        wait_for_parent=lambda _pid: None,
        command_runner=run,
        restart_launcher=lambda _value, _log: None,
    )

    assert result == 0
    assert observed == [os.getpid()]
    assert store.read_worker_pid() is None


@pytest.mark.skipif(os.name == "nt", reason="POSIX signal delivery semantics")
def test_worker_interrupted_by_signal_marks_job_failed(tmp_path: Path) -> None:
    store, _job = _handoff_job(tmp_path)
    script = textwrap.dedent(
        f"""
        import os
        import signal
        import time
        from pathlib import Path

        from deeptutor.runtime.update_worker import run_update_worker
        from deeptutor.services.app_update import UpdateJobStore

        def interrupted_install(command, cwd, log_path):
            os.kill(os.getpid(), signal.SIGTERM)
            time.sleep(60)

        store = UpdateJobStore(Path({str(store.root)!r}))
        raise SystemExit(
            run_update_worker(
                store_root=store.root,
                parent_pid={os.getpid()},
                wait_for_parent=lambda _pid: None,
                command_runner=interrupted_install,
                restart_launcher=lambda _value, _log: None,
            )
        )
        """
    )
    completed = subprocess.run(  # noqa: S603 - fixed interpreter, no shell
        [sys.executable, "-c", script],
        cwd=_REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(_REPO_ROOT)},
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert completed.returncode == -signal.SIGTERM
    job = store.load()
    assert job.status == "failed"
    assert job.error == "Update worker interrupted by a termination signal"
    assert not store.active_path.exists()
    # The killed worker cannot run its finally block, so the pid record
    # survives as the marker a launcher startup uses to detect the stale job.
    assert store.read_worker_pid() is not None
    assert not _pid_is_alive(store.read_worker_pid())


def _pid_is_alive(pid: int | None) -> bool:
    from deeptutor.runtime.process import is_process_alive

    return is_process_alive(pid)


def test_worker_restores_previous_signal_handlers(tmp_path: Path) -> None:
    store, _job = _handoff_job(tmp_path)
    previous = signal.getsignal(signal.SIGTERM)

    result = run_update_worker(
        store_root=store.root,
        parent_pid=123,
        wait_for_parent=lambda _pid: None,
        command_runner=lambda _command, _cwd, _log: 7,
        restart_launcher=lambda _value, _log: None,
    )

    assert result == 1
    assert signal.getsignal(signal.SIGTERM) is previous


def test_update_command_rejects_non_stable_or_injected_versions() -> None:
    with pytest.raises(ValueError):
        build_update_command("1.7.0rc1")
    with pytest.raises(ValueError):
        build_update_command("1.7.0; touch /tmp/nope")
