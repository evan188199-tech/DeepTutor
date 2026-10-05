"""Durability and concurrency tests for LocalDiskAttachmentStore writes."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import threading

import pytest

from deeptutor.services.storage.attachment_store import LocalDiskAttachmentStore


def _make_store(tmp_path: Path) -> LocalDiskAttachmentStore:
    return LocalDiskAttachmentStore(root=tmp_path / "attachments")


def _put(store: LocalDiskAttachmentStore, data: bytes) -> str:
    return asyncio.run(
        store.put(
            session_id="session",
            attachment_id="pdf",
            filename="notes.pdf",
            data=data,
        )
    )


# ---------------------------------------------------------------------------
# fsync before replace
# ---------------------------------------------------------------------------


def test_put_fsyncs_tmp_before_replacing_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The write path must fsync the staged file before renaming it into place."""
    store = _make_store(tmp_path)
    events: list[str] = []
    real_fsync, real_replace = os.fsync, os.replace

    def spy_fsync(fd: int) -> None:
        events.append("fsync")
        real_fsync(fd)

    def spy_replace(src: str, dst: str) -> None:
        events.append("replace")
        real_replace(src, dst)

    monkeypatch.setattr(os, "fsync", spy_fsync)
    monkeypatch.setattr(os, "replace", spy_replace)

    _put(store, b"durable bytes")

    assert events == ["fsync", "replace"]


# ---------------------------------------------------------------------------
# unique tmp names
# ---------------------------------------------------------------------------


def test_write_sync_uses_unique_tmp_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each write must stage through its own tmp name, not a shared fixed one."""
    store = _make_store(tmp_path)
    staged: list[Path] = []
    real_replace = os.replace

    def spy_replace(src: str, dst: str) -> None:
        staged.append(Path(src))
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy_replace)

    target = store.root / "session" / "pdf_notes.pdf"
    LocalDiskAttachmentStore._write_sync(target, b"first")
    LocalDiskAttachmentStore._write_sync(target, b"second")

    assert len(staged) == 2
    assert staged[0] != staged[1]
    for tmp in staged:
        assert tmp.parent == target.parent
        assert tmp.name != target.name
        assert tmp.name.startswith("pdf_notes.pdf.")
        assert tmp.name.endswith(".tmp")
    assert not list(store.root.rglob("*.tmp"))
    assert target.read_bytes() == b"second"


def test_concurrent_writes_to_same_target_keep_content_whole(tmp_path: Path) -> None:
    """Concurrent writers of the same target must never mix or truncate bytes."""
    store = _make_store(tmp_path)
    target = store.root / "session" / "pdf_notes.pdf"
    payloads = [(f"writer-{i}-").encode() * 256 for i in range(6)]
    writes_per_thread = 10
    barrier = threading.Barrier(len(payloads))

    def writer(payload: bytes) -> None:
        barrier.wait()
        for _ in range(writes_per_thread):
            LocalDiskAttachmentStore._write_sync(target, payload)

    threads = [threading.Thread(target=writer, args=(p,)) for p in payloads]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    final = target.read_bytes()
    assert any(final == p for p in payloads), "target holds torn or mixed bytes"
    assert not list(store.root.rglob("*.tmp"))


# ---------------------------------------------------------------------------
# cleanup semantics
# ---------------------------------------------------------------------------


def test_write_sync_cleans_up_tmp_when_fsync_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed fsync must abort the write and leave no tmp file behind."""

    def boom(fd: int) -> None:
        raise OSError("fsync rejected")

    monkeypatch.setattr(os, "fsync", boom)
    store = _make_store(tmp_path)
    target = store.root / "session" / "pdf_notes.pdf"

    with pytest.raises(OSError):
        LocalDiskAttachmentStore._write_sync(target, b"data")

    assert not target.exists()
    assert not list(store.root.rglob("*.tmp"))


def test_put_persists_bytes_without_tmp_leftover(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    _put(store, b"payload")

    target = store.root / "session" / "pdf_notes.pdf"
    assert target.read_bytes() == b"payload"
    assert not list(store.root.rglob("*.tmp"))
