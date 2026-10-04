"""Regression tests for FileLibraryStore disk-deletion failure paths (DT-22).

Locks in the current behaviour of ``FileLibraryStore._delete_file``
(``deeptutor/services/storage/file_library.py``): the on-disk cleanup is
best-effort.  A failed ``unlink`` is only logged, and any exception raised
while pruning now-empty parent directories is swallowed entirely by a broad
``except Exception: pass`` around the parent-traversal loop.  These tests
pin that behaviour so a later fix that starts surfacing (or retrying) disk
errors must consciously update them — and so the known list-vs-disk
inconsistency window stays visible instead of rotting silently.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from deeptutor.services.storage.file_library import (
    FileLibraryStore,
    reset_file_library_store,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "file_library.db"


@pytest.fixture
def rooted_store(tmp_db_path: Path, tmp_path: Path) -> FileLibraryStore:
    """A store with an explicit library root under tmp_path.

    ``_delete_file`` prunes empty parent directories up to (but not
    including) the root, so the tests need a root they can inspect.
    """
    reset_file_library_store()
    root = tmp_path / "library-files"
    return FileLibraryStore(db_path=tmp_db_path, root=root)


# ---------------------------------------------------------------------------
# _delete_file — success path
# ---------------------------------------------------------------------------


def test_delete_file_removes_target_and_empty_parent_dirs(
    rooted_store: FileLibraryStore,
) -> None:
    """A successful delete removes the file and prunes now-empty parent
    directories, stopping at (and keeping) the library root."""
    store = rooted_store
    root = store._root
    library_path = "sub/deep/report.txt"
    store._write_file(library_path, b"payload")
    assert (root / "sub" / "deep" / "report.txt").is_file()

    store._delete_file(library_path)

    assert not (root / "sub" / "deep" / "report.txt").exists()
    assert not (root / "sub" / "deep").exists()  # emptied parents pruned
    assert not (root / "sub").exists()
    assert root.is_dir()  # root itself is never removed


def test_delete_file_keeps_nonempty_parent_dirs(rooted_store: FileLibraryStore) -> None:
    """Parent pruning must stop at directories that still hold other files."""
    store = rooted_store
    root = store._root
    store._write_file("batch/keep.txt", b"keep")
    store._write_file("batch/gone.txt", b"gone")

    store._delete_file("batch/gone.txt")

    assert not (root / "batch" / "gone.txt").exists()
    assert (root / "batch" / "keep.txt").is_file()  # untouched sibling
    assert (root / "batch").is_dir()  # non-empty parent kept


# ---------------------------------------------------------------------------
# _delete_file — target missing
# ---------------------------------------------------------------------------


def test_delete_file_missing_target_is_silent_noop(rooted_store: FileLibraryStore) -> None:
    """A library_path that does not exist on disk must be a silent no-op:
    no exception, no directories created, nothing written."""
    store = rooted_store
    root = store._root

    store._delete_file("never-existed.txt")

    assert not (root / "never-existed.txt").exists()
    if root.is_dir():
        assert list(root.iterdir()) == []  # nothing materialised on disk


def test_hard_delete_succeeds_when_disk_file_already_missing(
    rooted_store: FileLibraryStore,
) -> None:
    """DB-vs-disk sync: when the disk file has already vanished (e.g. pruned
    out-of-band), the hard-delete flow must still complete — the row is
    removed and the missing disk file is tolerated as a silent no-op."""
    store = rooted_store
    entry = store._add_file_sync(b"orphan payload", "orphan.txt", "text/plain")
    disk_path = store._file_path(entry["library_path"])
    assert disk_path.is_file()

    disk_path.unlink()  # file disappears out-of-band
    assert asyncio.run(store.delete_file(entry["id"])) is True
    assert asyncio.run(store.hard_delete_file(entry["id"])) is True

    assert asyncio.run(store.get_file(entry["id"])) is None  # row gone


# ---------------------------------------------------------------------------
# _delete_file — unlink failure
# ---------------------------------------------------------------------------


def test_delete_file_unlink_failure_only_logs_warning(
    rooted_store: FileLibraryStore, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """When ``unlink`` fails with OSError the failure is only logged — the
    file stays on disk and no exception propagates.  This pins the known
    best-effort gap: the DB row can be dropped while the file survives
    (list-vs-disk inconsistency window flagged by the DT-22 scan)."""
    store = rooted_store
    root = store._root
    library_path = "stuck/report.txt"
    store._write_file(library_path, b"payload")
    target = root / "stuck" / "report.txt"

    original_unlink = Path.unlink

    def failing_unlink(self: Path, missing_ok: bool = False) -> None:
        if self == target:
            raise PermissionError(13, f"simulated denial for {self}")
        original_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", failing_unlink)
    with caplog.at_level("WARNING", logger="deeptutor.services.storage.file_library"):
        store._delete_file(library_path)  # must not raise

    monkeypatch.undo()
    assert target.is_file()  # unlink failed -> file still on disk
    assert "failed to delete library file" in caplog.text
    assert str(target) in caplog.text


# ---------------------------------------------------------------------------
# _delete_file — parent-directory traversal exception (DT-22 HIGH, line 205)
# ---------------------------------------------------------------------------


def test_delete_file_parent_traversal_exception_is_swallowed(
    rooted_store: FileLibraryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DT-22: an exception raised while pruning empty parent directories is
    swallowed by the broad ``except Exception: pass`` around the traversal
    loop.  Current behaviour: the target file is still unlinked, the
    remaining parent cleanup is aborted mid-loop (empty directories are
    left behind), and no error surfaces to the caller."""
    store = rooted_store
    root = store._root
    library_path = "locked/report.txt"
    store._write_file(library_path, b"payload")
    locked_dir = root / "locked"

    original_iterdir = Path.iterdir

    def raising_iterdir(self: Path):
        if self == locked_dir:
            raise PermissionError(13, f"simulated denial for {self}")
        return original_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", raising_iterdir)
    store._delete_file(library_path)  # must not raise
    monkeypatch.undo()

    assert not (root / "locked" / "report.txt").exists()  # file still removed
    assert locked_dir.is_dir()  # traversal aborted -> empty dir left behind
