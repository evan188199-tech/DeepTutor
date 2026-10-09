"""Failure-path coverage for the isolated worker protocol.

Real subprocesses are only used with short timeouts or fast fake tasks;
crash paths patch the worker entry point so no child can linger.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

from deeptutor.runtime import isolated_worker
from deeptutor.runtime.isolated_worker import (
    IsolatedWorkerCrashed,
    IsolatedWorkerError,
    IsolatedWorkerTimeout,
    run_in_isolated_process,
    run_in_isolated_process_sync,
)


def _assert_no_worker_children() -> None:
    psutil = pytest.importorskip("psutil")
    children = psutil.Process().children(recursive=True)
    stragglers = [
        " ".join(child.cmdline() or ())
        for child in children
        if "worker_process" in " ".join(child.cmdline() or ())
    ]
    assert stragglers == [], f"leftover isolated worker children: {stragglers}"


def test_sync_timeout_raises_and_kills_the_child() -> None:
    with pytest.raises(IsolatedWorkerTimeout, match="exceeded 0.1 seconds"):
        run_in_isolated_process_sync("time:sleep", 10, timeout=0.1)
    _assert_no_worker_children()


def test_sync_import_failure_maps_remote_details() -> None:
    with pytest.raises(IsolatedWorkerError) as raised:
        run_in_isolated_process_sync("deeptutor.runtime.__missing_module_xyz__:task", timeout=10)
    assert raised.value.remote_type == "ModuleNotFoundError"
    assert "deeptutor.runtime.__missing_module_xyz__" in str(raised.value)
    assert raised.value.remote_traceback
    _assert_no_worker_children()


def test_sync_rejects_non_positive_timeout() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        run_in_isolated_process_sync("operator:add", 1, 2, timeout=0)


@pytest.mark.asyncio
async def test_async_rejects_non_positive_timeout() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        await run_in_isolated_process("operator:add", 1, 2, timeout=-1)


_CRASH_WITH_STDERR = """import sys
print("boom-from-crash-worker", file=sys.stderr)
raise SystemExit(3)
"""

_CRASH_SILENT = "raise SystemExit(4)\n"


def _install_crashing_worker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, source: str) -> None:
    module_name = "dt_crash_worker_under_test"
    (tmp_path / f"{module_name}.py").write_text(source, encoding="utf-8")
    parts = [str(tmp_path)]
    existing = os.environ.get("PYTHONPATH")
    if existing:
        parts.append(existing)
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(parts))
    monkeypatch.setattr(isolated_worker, "_WORKER_MODULE", module_name)


def test_crash_without_result_carries_stderr_detail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_crashing_worker(monkeypatch, tmp_path, _CRASH_WITH_STDERR)
    with pytest.raises(IsolatedWorkerCrashed, match="boom-from-crash-worker"):
        run_in_isolated_process_sync("operator:add", 1, 2, timeout=10)
    _assert_no_worker_children()


def test_crash_without_stderr_leaves_a_plain_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_crashing_worker(monkeypatch, tmp_path, _CRASH_SILENT)
    with pytest.raises(IsolatedWorkerCrashed) as raised:
        run_in_isolated_process_sync("operator:add", 1, 2, timeout=10)
    assert str(raised.value).endswith("exited without a result")
    _assert_no_worker_children()


def test_invalid_result_pickle_raises_crashed(monkeypatch: pytest.MonkeyPatch) -> None:
    def _garbage_command(request_path: Path, result_path: Path) -> list[str]:
        writer = (
            "import pathlib; "
            f"pathlib.Path({str(result_path)!r}).write_bytes(b'definitely-not-a-pickle')"
        )
        return [sys.executable, "-c", writer]

    monkeypatch.setattr(isolated_worker, "_command", _garbage_command)
    with pytest.raises(IsolatedWorkerCrashed, match="invalid result"):
        run_in_isolated_process_sync("operator:add", 1, 2, timeout=10)


def test_success_envelope_returns_the_result() -> None:
    assert isolated_worker._unwrap({"ok": True, "result": 42}, "operator:add") == 42


def test_non_dict_envelope_raises_crashed() -> None:
    with pytest.raises(IsolatedWorkerCrashed, match="invalid envelope"):
        isolated_worker._unwrap(["ok", True], "operator:add")


def test_error_envelope_maps_remote_fields() -> None:
    with pytest.raises(IsolatedWorkerError) as raised:
        isolated_worker._unwrap(
            {
                "ok": False,
                "message": "child failed",
                "module": "builtins",
                "type": "ValueError",
                "traceback": "Traceback (most recent call last): ...",
                "attrs": {"filename": "doc.txt"},
            },
            "operator:add",
        )
    error = raised.value
    assert str(error) == "child failed"
    assert error.remote_module == "builtins"
    assert error.remote_type == "ValueError"
    assert error.remote_traceback.startswith("Traceback")
    assert error.remote_attrs == {"filename": "doc.txt"}


def test_error_envelope_with_non_dict_attrs_defaults_to_empty() -> None:
    with pytest.raises(IsolatedWorkerError) as raised:
        isolated_worker._unwrap({"ok": False, "message": "boom", "attrs": "oops"}, "x:y")
    assert raised.value.remote_attrs == {}


def test_error_envelope_without_message_falls_back_to_call_path() -> None:
    with pytest.raises(IsolatedWorkerError, match="'x:y' failed"):
        isolated_worker._unwrap({"ok": False}, "x:y")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("2", 2), ("0", 1), ("-3", 1), ("5", 5), ("junk", 2), ("", 2)],
)
def test_worker_limit_sanitizes_env(
    raw: str, expected: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPTUTOR_ISOLATED_WORKERS", raw)
    assert isolated_worker._worker_limit() == expected


def test_worker_limit_defaults_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPTUTOR_ISOLATED_WORKERS", raising=False)
    assert isolated_worker._worker_limit() == 2


def test_suite_leaves_no_worker_children_behind() -> None:
    _assert_no_worker_children()
