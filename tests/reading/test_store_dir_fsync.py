"""Durability of the reading store's directory swaps.

Materials are installed by renaming a fully written staging directory into
place (with a backup rollback), and deletions first stage the material
aside. A completed rename is durable only once the parent directory entry
itself is synced, so each of the four swap sites must fsync the store root.
These tests pin that contract, that a failing directory fsync degrades to a
warning without losing the swap, and that the swap still lands where
``O_DIRECTORY`` does not exist.
"""

from __future__ import annotations

import os
from pathlib import Path
import stat

import pytest

from deeptutor.reading import ReadingStore

MATERIAL_ID = "a1b2c3d4e5f6a7b8"


def _spy_directory_fsyncs(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Record the inodes of directories whose file descriptors get fsynced."""
    synced: list[int] = []
    real_fsync = os.fsync

    def spy(fd: int) -> None:
        info = os.fstat(fd)
        if stat.S_ISDIR(info.st_mode):
            synced.append(info.st_ino)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", spy)
    return synced


@pytest.fixture
def store(tmp_path: Path) -> ReadingStore:
    return ReadingStore(root=tmp_path / "materials")


def _write_markdown(tmp_path: Path) -> Path:
    source = tmp_path / "doc.md"
    source.write_text("# Title\n\nBody text.\n", encoding="utf-8")
    return source


def test_ingest_fsyncs_root_after_swap(
    store: ReadingStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    synced = _spy_directory_fsyncs(monkeypatch)

    manifest = store.ingest(_write_markdown(tmp_path))

    assert manifest.unit_count == 1
    assert os.stat(store.root).st_ino in synced


def test_refresh_document_fsyncs_root_after_swap(
    store: ReadingStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = store.ingest_units(
        MATERIAL_ID,
        filename="doc.md",
        units=["Body text."],
        title="Doc",
        raw_data=b"# Title\n\nBody text.\n",
    )
    synced = _spy_directory_fsyncs(monkeypatch)

    refreshed = store.refresh_document(manifest.material_id)

    assert refreshed.material_id == manifest.material_id
    assert os.stat(store.root).st_ino in synced


def test_ingest_units_fsyncs_root_after_swap(
    store: ReadingStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    synced = _spy_directory_fsyncs(monkeypatch)

    manifest = store.ingest_units(
        MATERIAL_ID, filename="notes.md", units=["Alpha body."], title="Notes"
    )

    assert manifest.material_id == MATERIAL_ID
    assert os.stat(store.root).st_ino in synced


def test_staged_delete_fsyncs_root_after_staging_rename(
    store: ReadingStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = store.ingest_units(
        MATERIAL_ID, filename="notes.md", units=["Alpha body."], title="Notes"
    )
    synced = _spy_directory_fsyncs(monkeypatch)

    with store.staged_delete(manifest.material_id):
        # The move-aside is durable before the coordinator's boundary runs.
        assert os.stat(store.root).st_ino in synced

    assert not (store.root / MATERIAL_ID).exists()


def test_dir_fsync_failure_warns_and_swap_still_lands(
    store: ReadingStore,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    real_fsync = os.fsync

    def failing_dir_fsync(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("disk says no")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", failing_dir_fsync)

    with caplog.at_level("WARNING", logger="deeptutor.reading.store"):
        manifest = store.ingest_units(
            MATERIAL_ID, filename="notes.md", units=["Alpha body."], title="Notes"
        )

    assert any(
        record.levelname == "WARNING" and "fsync" in record.getMessage()
        for record in caplog.records
    )
    assert store.manifest(manifest.material_id).unit_count == 1


def test_without_odirectory_support_swap_still_lands(
    store: ReadingStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delattr(os, "O_DIRECTORY", raising=False)

    manifest = store.ingest(_write_markdown(tmp_path))

    assert store.manifest(manifest.material_id).unit_count == 1
