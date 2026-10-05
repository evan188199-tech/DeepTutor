from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pytest

from deeptutor.services import file_io
from deeptutor.services.file_io import atomic_write_json, atomic_write_text

requires_odirectory = pytest.mark.skipif(
    not hasattr(os, "O_DIRECTORY"), reason="platform without os.O_DIRECTORY"
)


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


@requires_odirectory
def test_atomic_write_json_fsyncs_parent_directory_after_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    synced_dirs: list[Path] = []
    real_open = os.open

    def spy_open(path: str | os.PathLike[str], flags: int, *args: int, **kwargs: int) -> int:
        if flags & os.O_DIRECTORY:
            synced_dirs.append(Path(path))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(file_io.os, "open", spy_open)

    path = tmp_path / "nested" / "settings.json"

    atomic_write_json(path, {"value": 1})

    assert synced_dirs == [path.parent]


@requires_odirectory
def test_atomic_write_text_fsyncs_parent_directory_after_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    synced_dirs: list[Path] = []
    real_open = os.open

    def spy_open(path: str | os.PathLike[str], flags: int, *args: int, **kwargs: int) -> int:
        if flags & os.O_DIRECTORY:
            synced_dirs.append(Path(path))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(file_io.os, "open", spy_open)

    path = tmp_path / "nested" / "note.md"

    atomic_write_text(path, "hello")

    assert synced_dirs == [path.parent]


@requires_odirectory
def test_directory_fsync_failure_warns_but_still_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    dir_fds: set[int] = set()
    real_open = os.open
    real_fsync = os.fsync

    def spy_open(path: str | os.PathLike[str], flags: int, *args: int, **kwargs: int) -> int:
        fd = real_open(path, flags, *args, **kwargs)
        if flags & os.O_DIRECTORY:
            dir_fds.add(fd)
        return fd

    def failing_directory_fsync(fd: int) -> None:
        if fd in dir_fds:
            raise OSError("simulated directory sync failure")
        real_fsync(fd)

    monkeypatch.setattr(file_io.os, "open", spy_open)
    monkeypatch.setattr(file_io.os, "fsync", failing_directory_fsync)

    path = tmp_path / "nested" / "settings.json"
    with caplog.at_level(logging.WARNING, logger="deeptutor.services.file_io"):
        atomic_write_json(path, {"value": 1})

    assert json.loads(path.read_text(encoding="utf-8")) == {"value": 1}
    warnings = [record for record in caplog.records if record.levelno >= logging.WARNING]
    assert len(warnings) == 1
    assert str(path.parent) in warnings[0].getMessage()


def test_fsync_directory_is_noop_without_odirectory_support(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened_flags: list[int] = []
    real_open = os.open

    def spy_open(path: str | os.PathLike[str], flags: int, *args: int, **kwargs: int) -> int:
        opened_flags.append(flags)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(file_io.os, "open", spy_open)
    monkeypatch.delattr(file_io.os, "O_DIRECTORY", raising=False)

    file_io.fsync_directory(tmp_path)

    assert opened_flags == []
