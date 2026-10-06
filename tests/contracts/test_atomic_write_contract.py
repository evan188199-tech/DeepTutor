"""Cross-module persistence contract for atomic writes (fsync / rename / tmp).

Regression landing point for the 2026-10-05 atomic-write scan
(``evidence/atomic-write-2026-10-05/report.md`` on branch
``scan/atomic-write-tmp-fsync-20261005``; the 2026-10-06 drift re-check
confirms every finding still holds on ``origin/main`` @ ``f07029cfc``).

Contract axes, asserted by monkeypatching ``os.fsync`` / ``os.replace``:

- **durability** — file content is fsync'd before the target is replaced,
  and a rename is followed by a parent-directory fsync;
- **concurrency** — staging files get a unique name per write, never a
  fixed shared name;
- **residue** — a failed write leaves no staging file behind and never
  destroys the previous target content.

Findings that do not satisfy the contract yet are marked ``xfail(strict)``
and name the fix card that must promote them back to a passing test:

==========================  ==========================================
xfail marker                Scan finding / fix card
==========================  ==========================================
fix-fsync-durability        H1 file_io swallows fsync failures (PR #1751)
fix-dir-fsync-rename        H2 no parent-dir fsync after rename
fix-storage-write-fsync     M1 attachment_store / M2 file_library
fix-worker-process-fsync    M3 worker_process result write-back
fix-snapshot-store-fsync    M4 memory snapshot ``save_state``
fix-reading-store-fsync     M7 reading store directory swap
==========================  ==========================================
"""

from __future__ import annotations

import errno
import logging
import os
from pathlib import Path
import pickle
from typing import Any, Callable

import pytest

from deeptutor.reading.store import ReadingStore
from deeptutor.runtime import worker_process
from deeptutor.services import file_io
from deeptutor.services.file_io import atomic_write_json, atomic_write_text
from deeptutor.services.memory.snapshot import store as snapshot_store
from deeptutor.services.storage.attachment_store import LocalDiskAttachmentStore
from deeptutor.services.storage.file_library import FileLibraryStore

# ---------------------------------------------------------------------------
# Instrumentation: record fsync / replace order without changing behaviour
# ---------------------------------------------------------------------------


class _IoLog:
    """Ordered record of fsync / replace events observed during a test."""

    def __init__(self) -> None:
        self.events: list[tuple[str, Any, Any]] = []

    def _kinds(self) -> list[str]:
        return [kind for kind, _src, _dst in self.events]

    def replace_sources(self) -> list[Path]:
        return [Path(src) for kind, src, _dst in self.events if kind == "replace"]

    def fsync_before_first_replace(self) -> bool:
        """At least one fsync happened before the first rename."""
        kinds = self._kinds()
        if "replace" not in kinds:
            return False
        first_replace = kinds.index("replace")
        return "fsync" in kinds[:first_replace]

    def fsync_after_last_replace(self) -> bool:
        """At least one fsync happened after the final rename.

        A content fsync always precedes its own rename, so an fsync after the
        last rename can only be the parent-directory fsync that makes the
        rename itself durable (POSIX: rename metadata is only persisted by
        fsyncing the containing directory afterwards).
        """
        kinds = self._kinds()
        if "replace" not in kinds:
            return False
        last_replace = len(kinds) - 1 - kinds[::-1].index("replace")
        return "fsync" in kinds[last_replace + 1 :]


@pytest.fixture
def io_log(monkeypatch: pytest.MonkeyPatch) -> _IoLog:
    """Spy on ``os.fsync`` / ``os.replace`` pass-through.

    ``pathlib.Path.replace`` delegates to ``os.replace``, so one ``os.replace``
    spy observes every rename in the codebase, however it is invoked.
    """
    log = _IoLog()
    real_fsync = os.fsync
    real_replace = os.replace

    def spy_fsync(fd: int) -> None:
        log.events.append(("fsync", fd, None))
        real_fsync(fd)

    def spy_replace(src: Any, dst: Any, **kwargs: Any) -> None:
        log.events.append(("replace", Path(src), Path(dst)))
        real_replace(src, dst, **kwargs)

    monkeypatch.setattr(os, "fsync", spy_fsync)
    monkeypatch.setattr(os, "replace", spy_replace)
    return log


@pytest.fixture
def fail_replace(monkeypatch: pytest.MonkeyPatch) -> Callable[[Callable[[Path, Path], bool]], None]:
    """Make the replace calls matching ``predicate(src, dst)`` raise ``OSError``."""

    real_replace = os.replace

    def install(predicate: Callable[[Path, Path], bool]) -> None:
        def failing_replace(src: Any, dst: Any, **kwargs: Any) -> None:
            if predicate(Path(src), Path(dst)):
                raise OSError(errno.EIO, "simulated replace failure")
            real_replace(src, dst, **kwargs)

        monkeypatch.setattr(os, "replace", failing_replace)

    return install


def _assert_no_tmp_residue(directory: Path, target: Path) -> None:
    """No staging file may survive next to *target* after a failed write."""
    leftovers = [p.name for p in directory.iterdir() if p != target and p.name.endswith(".tmp")]
    assert leftovers == [], f"staging files leaked after failed write: {leftovers}"


# ---------------------------------------------------------------------------
# file_io.atomic_write_json / atomic_write_text (scan H1, H2)
# ---------------------------------------------------------------------------


def test_file_io_json_fsyncs_content_before_replace(tmp_path: Path, io_log: _IoLog) -> None:
    target = tmp_path / "nested" / "settings.json"

    atomic_write_json(target, {"ok": True})

    assert target.read_text(encoding="utf-8") == '{\n  "ok": true\n}\n'
    assert io_log.replace_sources(), "target must be installed via a rename"
    assert io_log.fsync_before_first_replace(), (
        "atomic_write_json must fsync the staging file before renaming it into place"
    )


def test_file_io_text_fsyncs_content_before_replace(tmp_path: Path, io_log: _IoLog) -> None:
    target = tmp_path / "note.md"

    atomic_write_text(target, "body")

    assert target.read_text(encoding="utf-8") == "body"
    assert io_log.fsync_before_first_replace(), (
        "atomic_write_text must fsync the staging file before renaming it into place"
    )


def test_file_io_staging_names_are_unique_across_writes(tmp_path: Path, io_log: _IoLog) -> None:
    target = tmp_path / "state.json"

    atomic_write_json(target, {"n": 1})
    atomic_write_json(target, {"n": 2})

    sources = io_log.replace_sources()
    assert len(sources) == 2
    assert sources[0] != sources[1], "concurrent writers must not share one staging name"
    assert sources[0].parent == target.parent, "staging file must live in the target directory"


def test_file_io_replace_failure_keeps_old_content_and_leaves_no_residue(
    tmp_path: Path, fail_replace: Callable[[Callable[[Path, Path], bool]], None]
) -> None:
    target = tmp_path / "state.json"
    atomic_write_text(target, "old")

    fail_replace(lambda src, dst: dst == target)
    with pytest.raises(OSError):
        atomic_write_text(target, "new")

    assert target.read_text(encoding="utf-8") == "old"
    _assert_no_tmp_residue(target.parent, target)


@pytest.mark.xfail(
    reason="fix-fsync-durability: file_io swallows fsync errors (scan H1, upstream PR #1751)",
    strict=True,
)
def test_file_io_surfaces_fsync_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def enospc(fd: int) -> None:
        raise OSError(errno.ENOSPC, "simulated fsync failure")

    monkeypatch.setattr(os, "fsync", enospc)
    target = tmp_path / "settings.json"

    surfaced = False
    with caplog.at_level(logging.WARNING):
        try:
            atomic_write_json(target, {"ok": True})
        except OSError:
            surfaced = True
    warned = any(record.levelno >= logging.WARNING for record in caplog.records)

    assert surfaced or warned, "a failed fsync must not be silently swallowed"


@pytest.mark.xfail(
    reason="fix-dir-fsync-rename: rename is never followed by a parent-dir fsync (scan H2)",
    strict=True,
)
def test_file_io_parent_dir_fsynced_after_replace(tmp_path: Path, io_log: _IoLog) -> None:
    atomic_write_json(tmp_path / "settings.json", {"ok": True})

    assert io_log.fsync_after_last_replace(), (
        "the rename must be made durable by fsyncing the parent directory afterwards"
    )


# ---------------------------------------------------------------------------
# storage/attachment_store (scan M1)
# ---------------------------------------------------------------------------


def _attachment_target(tmp_path: Path) -> Path:
    session_dir = tmp_path / "sessions" / "session-1"
    session_dir.mkdir(parents=True)
    return session_dir / "report.pdf"


@pytest.mark.xfail(
    reason="fix-storage-write-fsync: attachment bytes are never fsynced (scan M1)",
    strict=True,
)
def test_attachment_store_fsyncs_content_before_replace(tmp_path: Path, io_log: _IoLog) -> None:
    target = _attachment_target(tmp_path)

    LocalDiskAttachmentStore._write_sync(target, b"payload")

    assert target.read_bytes() == b"payload"
    assert io_log.fsync_before_first_replace(), (
        "attachment bytes must be fsynced before the rename exposes them"
    )


@pytest.mark.xfail(
    reason="fix-storage-write-fsync: fixed '<name>.tmp' staging name shared by concurrent "
    "writers (scan M1, unique-tmp axis)",
    strict=True,
)
def test_attachment_store_staging_names_are_unique_across_writes(
    tmp_path: Path, io_log: _IoLog
) -> None:
    target = _attachment_target(tmp_path)

    LocalDiskAttachmentStore._write_sync(target, b"first")
    LocalDiskAttachmentStore._write_sync(target, b"second")

    sources = io_log.replace_sources()
    assert len(sources) == 2
    assert sources[0] != sources[1], "concurrent uploads of one attachment must not share a name"


def test_attachment_store_replace_failure_keeps_old_content_and_leaves_no_residue(
    tmp_path: Path, fail_replace: Callable[[Callable[[Path, Path], bool]], None]
) -> None:
    target = _attachment_target(tmp_path)
    LocalDiskAttachmentStore._write_sync(target, b"old")

    fail_replace(lambda src, dst: dst == target)
    with pytest.raises(OSError):
        LocalDiskAttachmentStore._write_sync(target, b"new")

    assert target.read_bytes() == b"old"
    _assert_no_tmp_residue(target.parent, target)


# ---------------------------------------------------------------------------
# storage/file_library (scan M2)
# ---------------------------------------------------------------------------


def _library(tmp_path: Path) -> FileLibraryStore:
    return FileLibraryStore(db_path=tmp_path / "library.db", root=tmp_path / "files")


@pytest.mark.xfail(
    reason="fix-storage-write-fsync: library file bytes are never fsynced (scan M2)",
    strict=True,
)
def test_file_library_fsyncs_content_before_replace(tmp_path: Path, io_log: _IoLog) -> None:
    library = _library(tmp_path)

    library._write_file("docs/note.txt", b"payload")

    assert library._file_path("docs/note.txt").read_bytes() == b"payload"
    assert io_log.fsync_before_first_replace(), (
        "library bytes must be fsynced before the rename exposes them"
    )


def test_file_library_replace_failure_keeps_old_content_and_leaves_no_residue(
    tmp_path: Path, fail_replace: Callable[[Callable[[Path, Path], bool]], None]
) -> None:
    library = _library(tmp_path)
    target = library._file_path("docs/note.txt")
    library._write_file("docs/note.txt", b"old")

    fail_replace(lambda src, dst: dst == target)
    with pytest.raises(OSError):
        library._write_file("docs/note.txt", b"new")

    assert target.read_bytes() == b"old"
    _assert_no_tmp_residue(target.parent, target)


# ---------------------------------------------------------------------------
# runtime/worker_process (scan M3)
# ---------------------------------------------------------------------------


def _write_worker_io(tmp_path: Path) -> tuple[Path, Path]:
    request_path = tmp_path / "request.pkl"
    request_path.write_bytes(pickle.dumps({"callable_path": "builtins:hex", "args": [255]}))
    return request_path, tmp_path / "result.pkl"


def _run_worker(tmp_path: Path) -> tuple[int, Path]:
    request_path, result_path = _write_worker_io(tmp_path)
    code = worker_process.main([str(request_path), str(result_path)])
    return code, result_path


@pytest.mark.xfail(
    reason="fix-worker-process-fsync: result envelope is never fsynced (scan M3)",
    strict=True,
)
def test_worker_process_fsyncs_result_before_replace(tmp_path: Path, io_log: _IoLog) -> None:
    code, result_path = _run_worker(tmp_path)

    assert code == 0
    envelope = pickle.loads(result_path.read_bytes())
    assert envelope["ok"] is True
    assert io_log.fsync_before_first_replace(), (
        "the worker result envelope must be fsynced before the rename publishes it"
    )


@pytest.mark.xfail(
    reason="fix-worker-process-fsync: a failed result write leaks 'result.tmp' (scan M3 residue)",
    strict=True,
)
def test_worker_process_write_failure_leaves_no_residue(
    tmp_path: Path, fail_replace: Callable[[Callable[[Path, Path], bool]], None]
) -> None:
    request_path, result_path = _write_worker_io(tmp_path)
    result_path.write_bytes(b"stale")

    fail_replace(lambda src, dst: src.name == "result.tmp")
    code = worker_process.main([str(request_path), str(result_path)])

    assert code == 1
    assert result_path.read_bytes() == b"stale"
    _assert_no_tmp_residue(tmp_path, result_path)


# ---------------------------------------------------------------------------
# memory/snapshot/store.save_state (scan M4)
# ---------------------------------------------------------------------------


@pytest.fixture
def snapshot_surface(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    root = tmp_path / "memory"
    monkeypatch.setattr(snapshot_store, "memory_root", lambda: root)
    return "chat"


def _save_snapshot_state(surface: str) -> None:
    snapshot_store.save_state(
        surface,  # type: ignore[arg-type]
        fingerprints={"entity-1": "fp-1"},
        labels={"entity-1": "Entity One"},
        last_refresh="2026-10-06T00:00:00Z",
    )


@pytest.mark.xfail(
    reason="fix-snapshot-store-fsync: snapshot state is never fsynced (scan M4)",
    strict=True,
)
def test_snapshot_save_state_fsyncs_before_replace(snapshot_surface: str, io_log: _IoLog) -> None:
    _save_snapshot_state(snapshot_surface)

    state = snapshot_store.load_state(snapshot_surface)
    assert state["fingerprints"] == {"entity-1": "fp-1"}
    assert io_log.fsync_before_first_replace(), (
        "snapshot state must be fsynced before the rename publishes it"
    )


@pytest.mark.xfail(
    reason="fix-snapshot-store-fsync: a failed save leaks 'state.json.tmp' (scan M4 residue)",
    strict=True,
)
def test_snapshot_save_state_failure_leaves_no_residue(
    snapshot_surface: str,
    tmp_path: Path,
    fail_replace: Callable[[Callable[[Path, Path], bool]], None],
) -> None:
    snapshot_dir = tmp_path / "memory" / "snapshot" / snapshot_surface

    fail_replace(lambda src, dst: src.name == "state.json.tmp")
    with pytest.raises(OSError):
        _save_snapshot_state(snapshot_surface)

    _assert_no_tmp_residue(snapshot_dir, snapshot_dir / "state.json")


# ---------------------------------------------------------------------------
# reading/store directory swap (scan M7)
# ---------------------------------------------------------------------------


def _ingest_text(tmp_path: Path) -> tuple[ReadingStore, str, str]:
    source = tmp_path / "chapter.txt"
    source.write_text(
        "# Opening\n\nTrusted source text.\n\n## Next\n\nMore text.", encoding="utf-8"
    )
    store = ReadingStore(tmp_path / "reading")
    manifest = store.ingest(source)
    return store, manifest.material_id, store.unit_text(manifest.material_id, 1)


@pytest.mark.xfail(
    reason="fix-reading-store-fsync: directory swap renames are never fsynced (scan M7)",
    strict=True,
)
def test_reading_store_dir_swap_fsyncs_after_rename(tmp_path: Path, io_log: _IoLog) -> None:
    store, material_id, _ = _ingest_text(tmp_path)

    assert store.manifest(material_id).revision == 1
    assert io_log.replaces, "install must go through rename swaps"
    assert io_log.fsync_after_last_replace(), (
        "the material directory swap must be made durable by fsyncing the parent directory"
    )


def test_reading_store_swap_failure_rolls_back_without_residue(
    tmp_path: Path, fail_replace: Callable[[Callable[[Path, Path], bool]], None]
) -> None:
    store, material_id, first_unit = _ingest_text(tmp_path)
    material_dir = store._dir(material_id)

    # Re-install the material through the pre-extracted-units path: plain-text
    # materials keep no raw bytes, so this is the reachable re-install swap.
    fail_replace(lambda src, dst: dst == material_dir and src.name.endswith(".staging"))
    with pytest.raises(OSError):
        store.ingest_units(
            material_id,
            filename="chapter.txt",
            units=["# Replacement\n\nNew body text."],
        )

    # The previous material must be back in place and usable.
    assert store.manifest(material_id).revision == 1
    assert store.unit_text(material_id, 1) == first_unit
    leftovers = [
        entry.name for entry in store.root.iterdir() if entry.name.endswith((".staging", ".backup"))
    ]
    assert leftovers == [], f"swap failure leaked staging/backup directories: {leftovers}"
