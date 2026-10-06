"""Durability and cleanup contract for the private worker entry point."""

from __future__ import annotations

import os
from pathlib import Path
import pickle
from typing import Any

from deeptutor.runtime.worker_process import main


def _write_request(path: Path) -> None:
    path.write_bytes(pickle.dumps({"callable_path": "operator:add", "args": (20, 22)}))


def test_main_fsyncs_staged_file_before_replace(tmp_path: Path, monkeypatch: Any) -> None:
    request = tmp_path / "request.pickle"
    result = tmp_path / "result.pickle"
    _write_request(request)
    calls: list[str] = []
    real_fsync = os.fsync
    real_replace = os.replace

    def tracking_fsync(fd: int) -> None:
        calls.append("fsync")
        real_fsync(fd)

    def tracking_replace(src: Any, dst: Any) -> None:
        calls.append("replace")
        real_replace(src, dst)

    monkeypatch.setattr(os, "fsync", tracking_fsync)
    monkeypatch.setattr(os, "replace", tracking_replace)

    assert main([str(request), str(result)]) == 0
    assert calls == ["fsync", "replace"]
    assert pickle.loads(result.read_bytes()) == {"ok": True, "result": 42}
    assert not (tmp_path / "result.tmp").exists()


def test_main_tolerates_fsync_failure(tmp_path: Path, monkeypatch: Any) -> None:
    request = tmp_path / "request.pickle"
    result = tmp_path / "result.pickle"
    _write_request(request)
    attempts: list[int] = []

    def failing_fsync(fd: int) -> None:
        attempts.append(fd)
        raise OSError("fsync unavailable")

    monkeypatch.setattr(os, "fsync", failing_fsync)

    assert main([str(request), str(result)]) == 0
    assert attempts, "worker must attempt fsync before publishing the result"
    assert pickle.loads(result.read_bytes()) == {"ok": True, "result": 42}
    assert not (tmp_path / "result.tmp").exists()


def test_main_removes_staged_file_when_replace_fails(tmp_path: Path, monkeypatch: Any) -> None:
    request = tmp_path / "request.pickle"
    result = tmp_path / "result.pickle"
    _write_request(request)

    def failing_replace(src: Any, dst: Any) -> None:
        raise OSError("replace rejected")

    monkeypatch.setattr(os, "replace", failing_replace)

    assert main([str(request), str(result)]) == 1
    assert not (tmp_path / "result.tmp").exists()
    assert not result.exists()
