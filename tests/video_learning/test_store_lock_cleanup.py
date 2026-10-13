from __future__ import annotations

import os
from pathlib import Path
import threading

import pytest

from deeptutor.video_learning import service


def _store(tmp_path: Path) -> service.TimedMediaStore:
    return service.TimedMediaStore(root=tmp_path / "workspace" / "timed_media")


def _material(material_id: str) -> dict:
    return {
        "version": 1,
        "type": "timed_media",
        "material_id": material_id,
        "transcript": {"status": "ready", "cues": []},
    }


def _lock_paths(store: service.TimedMediaStore) -> list[Path]:
    lock_root = store.root / ".locks"
    if not lock_root.is_dir():
        return []
    return sorted(lock_root.glob("*.lock"))


def test_lock_file_is_removed_when_critical_section_ends(tmp_path: Path) -> None:
    store = _store(tmp_path)
    material_id = "a" * 32
    store.save(_material(material_id))

    with store.lock(material_id):
        assert (store.root / ".locks" / f"{material_id}.lock").is_file()
    assert not (store.root / ".locks" / f"{material_id}.lock").exists()

    # ``get()`` takes the lock internally for the legacy caption repair.
    store.get(material_id)
    assert _lock_paths(store) == []


def test_lock_file_is_removed_when_critical_section_raises(tmp_path: Path) -> None:
    store = _store(tmp_path)
    material_id = "b" * 32

    with pytest.raises(RuntimeError):
        with store.lock(material_id):
            raise RuntimeError("boom")

    assert _lock_paths(store) == []


def test_concurrent_locked_updates_stay_mutually_exclusive(tmp_path: Path) -> None:
    store = _store(tmp_path)
    material_id = "c" * 32
    store.save(_material(material_id))
    workers = 8
    rounds = 25
    barrier = threading.Barrier(workers)

    def worker() -> None:
        barrier.wait()
        for _ in range(rounds):
            with store.lock(material_id):
                material = store.get(material_id, lock_held=True)
                material["progress"] = int(material.get("progress", 0)) + 1
                store.save(material)

    threads = [threading.Thread(target=worker) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    assert not any(thread.is_alive() for thread in threads)

    assert store.get(material_id)["progress"] == workers * rounds
    assert _lock_paths(store) == []


def test_stale_lock_files_are_swept_and_material_files_untouched(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    stale_ids = ["d" * 32, "e" * 32]
    fresh_id = "1" * 32
    lock_root = store.root / ".locks"
    lock_root.mkdir(parents=True, exist_ok=True)
    stale_mtime = os.path.getmtime(lock_root) - service.STALE_LOCK_MAX_AGE_SECONDS - 3600
    for material_id in stale_ids:
        path = lock_root / f"{material_id}.lock"
        path.write_bytes(b"\0")
        os.utime(path, (stale_mtime, stale_mtime))
    fresh_path = lock_root / f"{fresh_id}.lock"
    fresh_path.write_bytes(b"\0")
    foreign_lock = lock_root / "not-a-material.lock"
    foreign_lock.write_bytes(b"\0")
    foreign_file = lock_root / "notes.txt"
    foreign_file.write_bytes(b"\0")
    for material_id in stale_ids + [fresh_id]:
        (store.root / f"{material_id}.json").write_text('{"type": "timed_media"}', encoding="utf-8")

    with store.lock("f" * 32):
        pass

    for material_id in stale_ids:
        assert not (lock_root / f"{material_id}.lock").exists()
    assert fresh_path.is_file()
    assert foreign_lock.is_file()
    assert foreign_file.is_file()
    for material_id in stale_ids + [fresh_id]:
        assert (store.root / f"{material_id}.json").read_text(
            encoding="utf-8"
        ) == '{"type": "timed_media"}'
