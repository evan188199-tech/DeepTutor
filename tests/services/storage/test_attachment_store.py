"""Contract tests for the local-disk chat attachment store.

Covers ``LocalDiskAttachmentStore`` write/cleanup/read-back/delete semantics:

* ``_write_sync`` success leaves no ``.tmp`` residue.
* ``_write_sync`` failure propagates the original error, removes the staged
  ``.tmp`` file, and keeps the previous target bytes intact.
* A failing ``.tmp`` cleanup inside the ``finally`` block is swallowed so it
  cannot mask the primary failure (noted by the persistence scan at
  ``attachment_store.py`` ``_write_sync``).
* Repeated writes to the same stored path overwrite; distinct attachment ids
  never collide.
* Bytes survive a ``put`` -> ``resolve_path`` read-back unchanged.
* Deletes remove only the targeted attachment / session directories.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from deeptutor.services.storage.attachment_store import LocalDiskAttachmentStore


def _store(tmp_path: Path, legacy: Path | None = None) -> LocalDiskAttachmentStore:
    root = tmp_path / "attachments"
    return LocalDiskAttachmentStore(root=root, legacy_root=legacy)


def _tmp_path_for(target: Path) -> Path:
    return target.with_suffix(target.suffix + ".tmp")


def _put(store: LocalDiskAttachmentStore, **kwargs) -> str:
    return asyncio.run(
        store.put(
            session_id=kwargs["session_id"],
            attachment_id=kwargs["attachment_id"],
            filename=kwargs["filename"],
            data=kwargs["data"],
        )
    )


# ---------------------------------------------------------------------------
# _write_sync: success and failure paths
# ---------------------------------------------------------------------------


class TestWriteSync:
    def test_success_writes_bytes_and_leaves_no_tmp_residue(self, tmp_path: Path) -> None:
        target = tmp_path / "sess-1" / "a1_notes.txt"

        LocalDiskAttachmentStore._write_sync(target, b"hello attachment")

        assert target.is_file()
        assert target.read_bytes() == b"hello attachment"
        assert not _tmp_path_for(target).exists()

    def test_failure_propagates_original_error_and_keeps_target_intact(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / "sess-1" / "a1_notes.txt"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"previous bytes")
        staged = _tmp_path_for(target)
        staged.mkdir()  # occupy the staged path so open("wb") fails

        with pytest.raises(OSError, match="notes.txt.tmp"):
            LocalDiskAttachmentStore._write_sync(target, b"new bytes")

        # The staged path being a directory also makes the finally-block
        # unlink fail; that cleanup error must be swallowed, and the original
        # open error is the one that surfaces.
        assert staged.is_dir()
        assert target.read_bytes() == b"previous bytes"

    def test_failure_removes_staged_tmp_residue(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "sess-1" / "a1_notes.txt"
        target.parent.mkdir(parents=True)

        def _fail_replace(src: object, dst: object) -> None:
            raise OSError("replace failed")

        monkeypatch.setattr(os, "replace", _fail_replace)

        with pytest.raises(OSError, match="replace failed"):
            LocalDiskAttachmentStore._write_sync(target, b"payload")

        assert not _tmp_path_for(target).exists()

    def test_failing_tmp_cleanup_does_not_mask_primary_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "sess-1" / "a1_notes.txt"
        target.parent.mkdir(parents=True)
        staged = _tmp_path_for(target)

        def _fail_replace(src: object, dst: object) -> None:
            raise OSError("replace failed")

        real_unlink = Path.unlink

        def _fail_unlink(self: Path, missing_ok: bool = False) -> None:
            if self.name.endswith(".tmp"):
                raise OSError("unlink failed")
            real_unlink(self, missing_ok=missing_ok)

        monkeypatch.setattr(os, "replace", _fail_replace)
        monkeypatch.setattr(Path, "unlink", _fail_unlink)

        # The primary "replace failed" error must surface; the cleanup error
        # inside the finally block must be swallowed, not raised instead.
        with pytest.raises(OSError, match="replace failed"):
            LocalDiskAttachmentStore._write_sync(target, b"payload")

        assert staged.exists()  # cleanup failed, residue remains by design
        assert not target.exists()

    def test_missing_parent_is_a_hard_failure(self, tmp_path: Path) -> None:
        blocker = tmp_path / "sess-1"
        blocker.write_bytes(b"not a directory")  # session "dir" is a file

        target = blocker / "a1_notes.txt"
        with pytest.raises(OSError):
            LocalDiskAttachmentStore._write_sync(target, b"payload")


# ---------------------------------------------------------------------------
# put: overwrite and collision semantics
# ---------------------------------------------------------------------------


class TestPutOverwrite:
    def test_same_path_repeated_write_overwrites(self, tmp_path: Path) -> None:
        store = _store(tmp_path)

        first_url = _put(
            store,
            session_id="sess-1",
            attachment_id="a1",
            filename="notes.txt",
            data=b"first",
        )
        second_url = _put(
            store,
            session_id="sess-1",
            attachment_id="a1",
            filename="notes.txt",
            data=b"second-payload",
        )

        assert first_url == second_url
        resolved = store.resolve_path(session_id="sess-1", attachment_id="a1", filename="notes.txt")
        assert resolved is not None
        assert resolved.read_bytes() == b"second-payload"
        session_files = list((tmp_path / "attachments" / "sess-1").iterdir())
        assert [p.name for p in session_files] == ["a1_notes.txt"]
        assert not _tmp_path_for(resolved).exists()

    def test_distinct_attachment_ids_do_not_collide(self, tmp_path: Path) -> None:
        store = _store(tmp_path)

        _put(store, session_id="sess-1", attachment_id="a1", filename="notes.txt", data=b"one")
        _put(store, session_id="sess-1", attachment_id="a2", filename="notes.txt", data=b"two")

        session_dir = tmp_path / "attachments" / "sess-1"
        assert sorted(p.name for p in session_dir.iterdir()) == ["a1_notes.txt", "a2_notes.txt"]
        resolved = store.resolve_path(session_id="sess-1", attachment_id="a2", filename="notes.txt")
        assert resolved is not None
        assert resolved.read_bytes() == b"two"


# ---------------------------------------------------------------------------
# put -> resolve_path: byte consistency
# ---------------------------------------------------------------------------


class TestReadBack:
    def test_binary_bytes_roundtrip_unchanged(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        payload = bytes(range(256)) + "中文内容".encode("utf-8")

        url = _put(
            store,
            session_id="sess-1",
            attachment_id="a1",
            filename="report final.pdf",
            data=payload,
        )

        assert url.startswith("/files/attachments/")
        resolved = store.resolve_path(
            session_id="sess-1", attachment_id="a1", filename="report final.pdf"
        )
        assert resolved is not None
        assert resolved.read_bytes() == payload

    def test_legacy_root_is_only_used_when_primary_copy_is_missing(self, tmp_path: Path) -> None:
        primary_root = tmp_path / "attachments"
        legacy_root = tmp_path / "legacy"
        store = LocalDiskAttachmentStore(root=primary_root, legacy_root=legacy_root)

        legacy_target = legacy_root / "sess-1" / "a9_old.txt"
        legacy_target.parent.mkdir(parents=True)
        legacy_target.write_bytes(b"legacy bytes")

        resolved = store.resolve_path(session_id="sess-1", attachment_id="a9", filename="old.txt")
        assert resolved == legacy_target


# ---------------------------------------------------------------------------
# delete semantics
# ---------------------------------------------------------------------------


class TestDelete:
    def test_delete_attachment_removes_only_matching_prefix(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        _put(store, session_id="sess-1", attachment_id="a1", filename="one.txt", data=b"1")
        _put(store, session_id="sess-1", attachment_id="a2", filename="two.txt", data=b"2")

        asyncio.run(store.delete_attachment("sess-1", "a1"))

        session_dir = tmp_path / "attachments" / "sess-1"
        assert [p.name for p in session_dir.iterdir()] == ["a2_two.txt"]
        assert (
            store.resolve_path(session_id="sess-1", attachment_id="a1", filename="one.txt") is None
        )
        assert (
            store.resolve_path(session_id="sess-1", attachment_id="a2", filename="two.txt")
            is not None
        )

    def test_delete_last_attachment_removes_empty_session_dir(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        _put(store, session_id="sess-1", attachment_id="a1", filename="one.txt", data=b"1")

        asyncio.run(store.delete_attachment("sess-1", "a1"))

        assert not (tmp_path / "attachments" / "sess-1").exists()

    def test_delete_session_cleans_primary_and_legacy_roots(self, tmp_path: Path) -> None:
        legacy_root = tmp_path / "legacy"
        store = _store(tmp_path, legacy=legacy_root)
        _put(store, session_id="sess-1", attachment_id="a1", filename="one.txt", data=b"1")

        legacy_dir = legacy_root / "sess-1"
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "a0_legacy.txt").write_bytes(b"legacy")

        asyncio.run(store.delete_session("sess-1"))

        assert not (tmp_path / "attachments" / "sess-1").exists()
        assert not legacy_dir.exists()
        assert (
            store.resolve_path(session_id="sess-1", attachment_id="a1", filename="one.txt") is None
        )

    def test_delete_session_on_unknown_session_is_noop(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        asyncio.run(store.delete_session("missing-session"))
        asyncio.run(store.delete_attachment("missing-session", "a1"))
        assert not (tmp_path / "attachments" / "missing-session").exists()
