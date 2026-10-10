"""Persistence of linked-folder sync state (``metadata.json``).

``update_folder_sync_state()`` used to mutate the loaded metadata dict and
return without writing it back, so ``last_sync``/``synced_files`` silently
vanished while the API layer logged success. These tests pin the write-back.
The atomicity contract of the shared writer lives in
``tests/services/test_file_io.py``.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import time

import pytest

from deeptutor.api.routers.knowledge import LinkedFolderInfo
from deeptutor.knowledge import manager as manager_module
from deeptutor.knowledge.manager import KnowledgeBaseManager

requires_tzset = pytest.mark.skipif(
    not hasattr(time, "tzset"), reason="time.tzset() is required for TZ switching"
)


@contextmanager
def _local_timezone(name: str):
    """Run the block under a different local timezone (POSIX only)."""
    previous = os.environ.get("TZ")
    try:
        os.environ["TZ"] = name
        time.tzset()
        yield
    finally:
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time.tzset()


def _manager_with_linked_folder(tmp_path: Path) -> tuple[KnowledgeBaseManager, Path, str, Path]:
    """A registered KB with one linked folder containing one markdown file."""
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))

    kb_dir = manager.base_dir / "kb"
    kb_dir.mkdir()
    manager.register_knowledge_base("kb")

    source = tmp_path / "notes"
    source.mkdir()
    doc = source / "note.md"
    doc.write_text("hello", encoding="utf-8")

    folder_info = manager.link_folder("kb", str(source))
    assert folder_info["last_sync"] is None
    return manager, kb_dir / "metadata.json", folder_info["id"], doc


def test_update_folder_sync_state_persists_to_disk(tmp_path: Path) -> None:
    manager, metadata_file, folder_id, doc = _manager_with_linked_folder(tmp_path)

    manager.update_folder_sync_state("kb", folder_id, [str(doc)])

    on_disk = json.loads(metadata_file.read_text(encoding="utf-8"))
    folder = on_disk["linked_folders"][0]
    assert "last_sync" in folder
    assert str(doc) in folder["synced_files"]
    assert folder["file_count"] == 1

    # A fresh manager (new process in real life) must see the sync state too.
    reloaded = KnowledgeBaseManager(base_dir=str(manager.base_dir))
    folder = reloaded.get_linked_folders("kb")[0]
    assert "last_sync" in folder
    assert str(doc) in folder["synced_files"]

    info = LinkedFolderInfo(**folder)
    assert info.last_sync == folder["last_sync"]


def test_update_folder_sync_state_unknown_folder_writes_nothing(tmp_path: Path) -> None:
    manager, metadata_file, _folder_id, doc = _manager_with_linked_folder(tmp_path)
    before = metadata_file.read_bytes()

    manager.update_folder_sync_state("kb", "no-such-id", [str(doc)])

    assert metadata_file.read_bytes() == before


def test_sync_snapshot_preserves_change_made_during_indexing(tmp_path: Path) -> None:
    manager, _metadata_file, folder_id, doc = _manager_with_linked_folder(tmp_path)
    staged_mtime = "2026-09-01T10:00:00"
    manager.update_folder_sync_state("kb", folder_id, [str(doc)], {str(doc): staged_mtime})

    changes = manager.detect_folder_changes("kb", folder_id)
    assert changes["modified_files"] == [str(doc)]


def _stored_sync_state(metadata_file: Path, doc: Path, value) -> None:
    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    metadata["linked_folders"][0]["synced_files"] = {str(doc): value}
    metadata_file.write_text(json.dumps(metadata), encoding="utf-8")


def test_update_folder_sync_state_stores_aware_utc_mtime(tmp_path: Path) -> None:
    """Stored mtimes must be timezone-aware so they survive a TZ change."""
    manager, metadata_file, folder_id, doc = _manager_with_linked_folder(tmp_path)
    st_mtime = doc.stat().st_mtime

    manager.update_folder_sync_state("kb", folder_id, [str(doc)])

    on_disk = json.loads(metadata_file.read_text(encoding="utf-8"))
    stored = on_disk["linked_folders"][0]["synced_files"][str(doc)]
    parsed = datetime.fromisoformat(stored)
    assert parsed.tzinfo is not None
    assert parsed == datetime.fromtimestamp(st_mtime, tz=timezone.utc)


@requires_tzset
def test_detect_folder_changes_stable_when_local_timezone_moves_ahead(
    tmp_path: Path,
) -> None:
    """A TZ move must not make every synced file look modified.

    Sync state recorded as naive local wall time under ``America/New_York``
    reads back as wall time 14 hours earlier under ``Asia/Tokyo``; the naive
    comparison then flags every unchanged file as modified and re-indexes the
    whole folder on every scan after a machine/TZ change.
    """
    manager, _metadata_file, folder_id, doc = _manager_with_linked_folder(tmp_path)

    with _local_timezone("America/New_York"):
        manager.update_folder_sync_state("kb", folder_id, [str(doc)])

    with _local_timezone("Asia/Tokyo"):
        changes = manager.detect_folder_changes("kb", folder_id)

    assert changes["new_files"] == []
    assert changes["modified_files"] == []
    assert changes["has_changes"] is False


@requires_tzset
def test_detect_folder_changes_detects_real_edit_across_timezone_change(
    tmp_path: Path,
) -> None:
    manager, _metadata_file, folder_id, doc = _manager_with_linked_folder(tmp_path)

    with _local_timezone("America/New_York"):
        manager.update_folder_sync_state("kb", folder_id, [str(doc)])

    stat_result = doc.stat()
    os.utime(
        doc,
        ns=(stat_result.st_atime_ns, stat_result.st_mtime_ns + 2_000_000_000),
    )

    with _local_timezone("Asia/Tokyo"):
        changes = manager.detect_folder_changes("kb", folder_id)

    assert changes["modified_files"] == [str(doc)]


def test_detect_folder_changes_accepts_legacy_naive_local_values(
    tmp_path: Path,
) -> None:
    """Values written by older builds (naive local ISO) still parse locally."""
    manager, metadata_file, folder_id, doc = _manager_with_linked_folder(tmp_path)
    legacy = datetime.fromtimestamp(doc.stat().st_mtime).isoformat()

    _stored_sync_state(metadata_file, doc, legacy)

    changes = manager.detect_folder_changes("kb", folder_id)
    assert changes["has_changes"] is False


def test_detect_folder_changes_accepts_epoch_number_values(tmp_path: Path) -> None:
    manager, metadata_file, folder_id, doc = _manager_with_linked_folder(tmp_path)

    _stored_sync_state(metadata_file, doc, doc.stat().st_mtime)

    changes = manager.detect_folder_changes("kb", folder_id)
    assert changes["has_changes"] is False


def test_detect_folder_changes_treats_unparseable_stored_mtime_as_modified(
    tmp_path: Path,
) -> None:
    manager, metadata_file, folder_id, doc = _manager_with_linked_folder(tmp_path)

    _stored_sync_state(metadata_file, doc, "not-a-timestamp")

    changes = manager.detect_folder_changes("kb", folder_id)
    assert changes["modified_files"] == [str(doc)]


def test_empty_successful_sync_records_last_sync_without_changing_file_state(
    tmp_path: Path,
) -> None:
    manager, metadata_file, folder_id, doc = _manager_with_linked_folder(tmp_path)
    manager.update_folder_sync_state("kb", folder_id, [str(doc)])
    before = json.loads(metadata_file.read_text(encoding="utf-8"))["linked_folders"][0]

    manager.update_folder_sync_state("kb", folder_id, [])

    after = json.loads(metadata_file.read_text(encoding="utf-8"))["linked_folders"][0]
    assert after["last_sync"]
    assert after["last_sync"] >= before["last_sync"]
    assert after["synced_files"] == before["synced_files"]


def test_update_folder_sync_state_mtime_failure_is_visible_not_fake_synced(
    tmp_path: Path,
    caplog,
    monkeypatch,
) -> None:
    """A per-file mtime recording failure must surface, not vanish.

    ``update_folder_sync_state()`` used to swallow stat/fromtimestamp errors
    with ``except Exception: pass``. The sync then reported success while the
    file's state was never recorded, hiding the degradation. The failure must
    be logged and the file must stay un-recorded so the next scan re-syncs it.
    """
    manager, metadata_file, folder_id, doc = _manager_with_linked_folder(tmp_path)

    flavour = type(Path())  # PosixPath on POSIX, WindowsPath on Windows

    class _VanishedMidStatPath(flavour):
        """exists() wins the race, stat() loses it (source vanished mid-sync)."""

        def exists(self, **kwargs):
            return True

        def stat(self, **kwargs):
            raise OSError("source vanished before stat")

    monkeypatch.setattr(manager_module, "Path", _VanishedMidStatPath)

    with caplog.at_level(logging.WARNING, logger="deeptutor.knowledge.manager"):
        manager.update_folder_sync_state("kb", folder_id, [str(doc)])

    # Visibility: the swallowed failure is now a logged warning naming the file.
    warnings_for_doc = [
        record
        for record in caplog.records
        if record.levelno >= logging.WARNING and str(doc) in record.getMessage()
    ]
    assert warnings_for_doc, f"expected a logged warning mentioning {doc}, got none"

    # Fallback semantics: the file is not marked synced, so the next scan
    # re-detects it instead of trusting a fabricated "already synced" state.
    on_disk = json.loads(metadata_file.read_text(encoding="utf-8"))
    folder = on_disk["linked_folders"][0]
    assert folder["last_sync"]
    assert str(doc) not in folder["synced_files"]
    assert folder["file_count"] == 0
    assert manager.detect_folder_changes("kb", folder_id)["new_files"] == [str(doc)]


def test_unlink_removes_only_the_source_registration(tmp_path: Path) -> None:
    manager, _metadata_file, folder_id, _doc = _manager_with_linked_folder(tmp_path)
    kb_dir = manager.base_dir / "kb"
    raw_file = kb_dir / "raw" / "note.md"
    index_marker = kb_dir / "version-1" / "index.marker"
    raw_file.parent.mkdir(parents=True)
    index_marker.parent.mkdir(parents=True)
    raw_file.write_text("imported", encoding="utf-8")
    index_marker.write_text("index", encoding="utf-8")

    assert manager.unlink_folder("kb", folder_id) is True

    assert manager.get_linked_folders("kb") == []
    assert raw_file.read_text(encoding="utf-8") == "imported"
    assert index_marker.read_text(encoding="utf-8") == "index"
