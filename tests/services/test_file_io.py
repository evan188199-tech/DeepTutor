from __future__ import annotations

import errno
import json
import logging
from pathlib import Path
import time

import pytest

from deeptutor.services import file_io
from deeptutor.services.file_io import atomic_write_json, atomic_write_text


def _failing_fsync(_fd: int) -> None:
    raise OSError("simulated disk failure")


def test_atomic_write_json_creates_parent_and_replaces_content(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "settings.json"

    atomic_write_json(path, {"greeting": "你好"})

    assert path.read_text(encoding="utf-8") == '{\n  "greeting": "你好"\n}\n'

    atomic_write_json(path, {"value": 2})

    assert json.loads(path.read_text(encoding="utf-8")) == {"value": 2}
    assert list(path.parent.iterdir()) == [path]


def test_atomic_write_json_cleans_up_temporary_file_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "nested" / "settings.json"

    def fail_dump(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("serialization failed")

    monkeypatch.setattr(file_io.json, "dump", fail_dump)

    with pytest.raises(RuntimeError, match="serialization failed"):
        atomic_write_json(path, {"value": 1})

    assert list(path.parent.iterdir()) == []


def test_atomic_write_json_preserves_original_on_failure(tmp_path: Path) -> None:
    target = tmp_path / "metadata.json"
    target.write_text('{"ok": true}', encoding="utf-8")

    with pytest.raises(TypeError):
        atomic_write_json(target, {"bad": object()})

    assert json.loads(target.read_text(encoding="utf-8")) == {"ok": True}
    # The failed write must not litter temp files next to the target.
    assert [p.name for p in tmp_path.iterdir()] == ["metadata.json"]


def test_atomic_write_text_creates_parent_and_replaces_content(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "note.md"

    atomic_write_text(path, "first")
    atomic_write_text(path, "second")

    assert path.read_text(encoding="utf-8") == "second"
    assert list(path.parent.iterdir()) == [path]


def test_atomic_write_json_warns_and_still_writes_when_fsync_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(file_io.os, "fsync", _failing_fsync)
    monkeypatch.setattr(file_io, "_last_fsync_warning_at", None)
    path = tmp_path / "nested" / "settings.json"

    with caplog.at_level(logging.WARNING, logger="deeptutor.services.file_io"):
        atomic_write_json(path, {"value": 1})

    assert json.loads(path.read_text(encoding="utf-8")) == {"value": 1}
    assert [p.name for p in path.parent.iterdir()] == ["settings.json"]
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "fsync" in warnings[0].getMessage()
    assert str(path) in warnings[0].getMessage()


def test_atomic_write_text_warns_and_still_writes_when_fsync_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(file_io.os, "fsync", _failing_fsync)
    monkeypatch.setattr(file_io, "_last_fsync_warning_at", None)
    path = tmp_path / "nested" / "note.md"

    with caplog.at_level(logging.WARNING, logger="deeptutor.services.file_io"):
        atomic_write_text(path, "content")

    assert path.read_text(encoding="utf-8") == "content"
    assert [p.name for p in path.parent.iterdir()] == ["note.md"]
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "fsync" in warnings[0].getMessage()
    assert str(path) in warnings[0].getMessage()


def test_read_text_with_retry_reads_explicit_utf8(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text('{"greeting": "你好"}', encoding="utf-8")

    assert file_io.read_text_with_retry(path) == '{"greeting": "你好"}'


def test_read_text_with_retry_recovers_from_transient_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "state.json"
    path.write_text("{}", encoding="utf-8")
    real_read_text = Path.read_text
    attempts = {"count": 0}

    def flaky_read_text(self, *args, **kwargs):
        attempts["count"] += 1
        if attempts["count"] <= 2:
            raise PermissionError(errno.EACCES, "Permission denied")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", flaky_read_text)
    monkeypatch.setattr(file_io, "_READ_RETRY_INITIAL_DELAY_SECONDS", 0.001)
    monkeypatch.setattr(file_io, "_READ_RETRY_MAX_DELAY_SECONDS", 0.002)

    assert file_io.read_text_with_retry(path) == "{}"
    assert attempts["count"] == 3


def test_read_text_with_retry_stops_past_bounded_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "state.json"
    path.write_text("{}", encoding="utf-8")
    attempts = {"count": 0}

    def always_locked(self, *args, **kwargs):
        attempts["count"] += 1
        raise PermissionError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(Path, "read_text", always_locked)
    monkeypatch.setattr(file_io, "_READ_RETRY_DEADLINE_SECONDS", 0.03)
    monkeypatch.setattr(file_io, "_READ_RETRY_INITIAL_DELAY_SECONDS", 0.005)
    monkeypatch.setattr(file_io, "_READ_RETRY_MAX_DELAY_SECONDS", 0.01)

    with pytest.raises(PermissionError):
        file_io.read_text_with_retry(path)

    assert 2 <= attempts["count"] <= 30


def test_read_text_with_retry_passes_through_non_conflict_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = {"count": 0}

    def failing(self, *args, **kwargs):
        attempts["count"] += 1
        raise OSError(errno.EIO, "I/O error")

    monkeypatch.setattr(Path, "read_text", failing)

    with pytest.raises(OSError, match="I/O error"):
        file_io.read_text_with_retry(tmp_path / "state.json")

    assert attempts["count"] == 1


def test_read_text_with_retry_keeps_missing_file_distinct(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        file_io.read_text_with_retry(tmp_path / "absent.json")


def test_transient_conflict_classification_covers_windows_sharing_winerrors() -> None:
    assert file_io._is_transient_read_conflict(PermissionError(errno.EACCES, "denied"))
    sharing = OSError(errno.EACCES, "sharing violation")
    sharing.winerror = 32
    assert file_io._is_transient_read_conflict(sharing)
    locked = OSError(errno.EACCES, "lock violation")
    locked.winerror = 33
    assert file_io._is_transient_read_conflict(locked)
    assert not file_io._is_transient_read_conflict(OSError(errno.EIO, "I/O error"))


def test_fsync_warning_is_rate_limited_but_recovers_after_interval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(file_io.os, "fsync", _failing_fsync)
    monkeypatch.setattr(file_io, "_last_fsync_warning_at", None)
    path = tmp_path / "nested" / "note.md"

    with caplog.at_level(logging.WARNING, logger="deeptutor.services.file_io"):
        for attempt in range(3):
            atomic_write_text(path, f"attempt-{attempt}")

    assert path.read_text(encoding="utf-8") == "attempt-2"
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1

    monkeypatch.setattr(
        file_io,
        "_last_fsync_warning_at",
        time.monotonic() - file_io._FSYNC_WARNING_INTERVAL_SECONDS - 1.0,
    )

    with caplog.at_level(logging.WARNING, logger="deeptutor.services.file_io"):
        atomic_write_text(path, "after-interval")

    assert path.read_text(encoding="utf-8") == "after-interval"
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 2
