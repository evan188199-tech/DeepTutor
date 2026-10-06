"""Durability of the snapshot state write.

``save_state`` publishes ``state.json`` via temp-file + rename; that only
survives a power loss if the temp file's bytes are flushed and fsync'd
*before* the rename. These tests pin the fsync-before-replace ordering and
that an fsync failure degrades to a warning instead of losing the write.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from deeptutor.services.memory.snapshot import store


@pytest.fixture
def tmp_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "memory"
    monkeypatch.setattr(store, "memory_root", lambda: root)
    return root


def test_save_state_fsyncs_before_replace(
    tmp_memory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[tuple[str, int]] = []
    real_fsync = os.fsync
    real_replace = os.replace

    def spy_fsync(fd: int) -> None:
        events.append(("fsync", os.fstat(fd).st_ino))
        real_fsync(fd)

    def spy_replace(src: str, dst: str) -> None:
        events.append(("replace", os.stat(src).st_ino))
        real_replace(src, dst)

    monkeypatch.setattr(os, "fsync", spy_fsync)
    monkeypatch.setattr(os, "replace", spy_replace)

    store.save_state(
        "chat",
        fingerprints={"e1": "fp1"},
        labels={"e1": "Entry one"},
        last_refresh="2026-10-06T00:00:00+00:00",
    )

    assert [name for name, _ in events] == ["fsync", "replace"]
    target = tmp_memory / "snapshot" / "chat" / "state.json"
    assert target.exists()
    # The published file is the exact inode whose bytes were fsync'd.
    assert events[0][1] == os.stat(target).st_ino
    assert events[1][1] == os.stat(target).st_ino


def test_save_state_fsync_failure_warns_and_still_writes(
    tmp_memory: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def broken_fsync(fd: int) -> None:
        raise OSError("disk says no")

    monkeypatch.setattr(os, "fsync", broken_fsync)

    with caplog.at_level("WARNING", logger=store.__name__):
        store.save_state(
            "chat",
            fingerprints={"e1": "fp1"},
            labels={"e1": "Entry one"},
            last_refresh="2026-10-06T00:00:00+00:00",
        )

    assert any(
        record.levelname == "WARNING" and "fsync" in record.getMessage()
        for record in caplog.records
    )
    # The write still lands and the on-disk format is unchanged.
    target = tmp_memory / "snapshot" / "chat" / "state.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload == {
        "fingerprints": {"e1": "fp1"},
        "labels": {"e1": "Entry one"},
        "last_refresh": "2026-10-06T00:00:00+00:00",
    }
    assert store.load_state("chat") == payload
    assert not (tmp_memory / "snapshot" / "chat" / "state.json.tmp").exists()


def test_save_state_roundtrip_preserves_format(tmp_memory: Path) -> None:
    store.save_state(
        "kb",
        fingerprints={"a": "fa", "b": "fb"},
        labels={"a": "A", "b": "B"},
        last_refresh="2026-10-06T12:34:56+00:00",
    )
    state = store.load_state("kb")
    assert state == {
        "fingerprints": {"a": "fa", "b": "fb"},
        "labels": {"a": "A", "b": "B"},
        "last_refresh": "2026-10-06T12:34:56+00:00",
    }
