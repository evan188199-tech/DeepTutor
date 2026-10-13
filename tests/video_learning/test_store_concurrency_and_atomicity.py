"""Behavior contracts for TimedMediaStore concurrency, atomic writes, and
learning-field retention (deeptutor/video_learning/service.py:307-408, 684-693).

Axes covered:
- lock() mutual exclusion across threads and no lost updates for read-modify-write saves
- atomic_write_json never exposes a partial target file and leaves no residue
- legacy caption repair rewrites a material at most once
- resolve_material rewrites transcript/segments but keeps learning (progress + marks)

Deliberately out of scope: transcript bound truncation (covered by store bound
tests) and lock-file lifecycle counts (covered by lock cleanup tests).
"""

from __future__ import annotations

import json
from pathlib import Path
import threading
import time

import pytest

from deeptutor.services.file_io import atomic_write_json
from deeptutor.video_learning import service
from deeptutor.video_learning.marks import create_mark

VIDEO_ID = "dQw4w9WgXcQ"
LEGACY_TEXT = "Learn&nbsp;&nbsp;&amp; apply"


def _base_material(material_id: str) -> dict:
    return {
        "version": 1,
        "type": "timed_media",
        "material_id": material_id,
        "learning": {"last_position": 0, "marks": []},
    }


def _seed_legacy_material(store: service.TimedMediaStore, material_id: str) -> None:
    store.save(
        {
            **_base_material(material_id),
            "transcript": {
                "status": "ready",
                "cues": [{"start": 0, "end": 1, "text": LEGACY_TEXT}],
            },
            "segments": [{"locator": 1, "start": 0, "end": 1, "text": LEGACY_TEXT}],
            "learning": {
                "last_position": 9,
                "marks": [{"locator": 1, "quote": "keep&nbsp;me"}],
            },
        }
    )


def _count_saves(store: service.TimedMediaStore) -> dict[str, int]:
    calls = {"n": 0}
    original = store.save

    def counted(material: dict) -> dict:
        calls["n"] += 1
        return original(material)

    store.save = counted  # type: ignore[method-assign]
    return calls


class _Paths:
    def __init__(self, root: Path) -> None:
        self.root = root

    def get_workspace_feature_dir(self, feature: str) -> Path:
        assert feature == "timed_media"
        return self.root / "workspace" / feature


@pytest.fixture
def isolated(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(service, "get_current_path_service", lambda: _Paths(tmp_path))
    settings_path = tmp_path / "settings" / "video_learning.json"
    monkeypatch.setattr(service, "video_learning_settings_path", lambda: settings_path)
    return tmp_path


def test_lock_serializes_concurrent_holders(tmp_path: Path) -> None:
    store = service.TimedMediaStore(tmp_path / "timed_media")
    material_id = service.material_id_for(VIDEO_ID)
    threads_count = 6
    barrier = threading.Barrier(threads_count)
    guard = threading.Lock()
    state = {"active": 0, "max_active": 0}

    def worker() -> None:
        barrier.wait(timeout=5)
        with store.lock(material_id):
            with guard:
                state["active"] += 1
                state["max_active"] = max(state["max_active"], state["active"])
            time.sleep(0.01)
            with guard:
                state["active"] -= 1

    threads = [threading.Thread(target=worker) for _ in range(threads_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert state["max_active"] == 1


def test_concurrent_locked_saves_keep_every_mark_update(tmp_path: Path) -> None:
    store = service.TimedMediaStore(tmp_path / "timed_media")
    material_id = service.material_id_for(VIDEO_ID)
    store.save(_base_material(material_id))
    threads_count = 8

    def worker(index: int) -> None:
        with store.lock(material_id):
            latest = store.get(material_id, lock_held=True)
            marks = list(latest["learning"].get("marks", []))
            marks.append({"locator": 100 + index, "quote": f"m{index}"})
            latest["learning"]["marks"] = marks
            store.save(latest)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(threads_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    final = store.get(material_id)
    locators = sorted(mark["locator"] for mark in final["learning"]["marks"])
    assert locators == [100 + index for index in range(threads_count)]


def test_concurrent_saves_never_expose_partial_json(tmp_path: Path) -> None:
    store = service.TimedMediaStore(tmp_path / "timed_media")
    material_id = service.material_id_for(VIDEO_ID)
    store.save(_base_material(material_id))
    path = store._path(material_id)
    errors: list[Exception] = []
    stop = threading.Event()

    def reader() -> None:
        while not stop.is_set():
            try:
                raw = path.read_text(encoding="utf-8")
            except FileNotFoundError:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                errors.append(exc)
                continue
            if not isinstance(payload, dict) or payload.get("type") != "timed_media":
                errors.append(ValueError("incomplete payload observed"))

    reader_thread = threading.Thread(target=reader)
    reader_thread.start()

    def writer(worker_index: int) -> None:
        for step in range(15):
            with store.lock(material_id):
                latest = store.get(material_id, lock_held=True)
                latest["learning"]["last_position"] = worker_index * 100 + step
                store.save(latest)

    writers = [threading.Thread(target=writer, args=(index,)) for index in range(4)]
    for thread in writers:
        thread.start()
    for thread in writers:
        thread.join(timeout=60)
    stop.set()
    reader_thread.join(timeout=30)

    assert errors == []
    assert isinstance(store.get(material_id)["learning"]["last_position"], int)


def test_atomic_write_json_failure_preserves_previous_content(tmp_path: Path) -> None:
    path = tmp_path / "material.json"
    previous = {"type": "timed_media", "seq": 1}
    atomic_write_json(path, previous)
    before = path.read_text(encoding="utf-8")

    bad_payload = {
        "type": "timed_media",
        "filler_a": "x" * 4096,
        "filler_b": "y" * 4096,
        "boom": object(),
    }
    with pytest.raises(TypeError):
        atomic_write_json(path, bad_payload)

    assert path.read_text(encoding="utf-8") == before
    assert json.loads(path.read_text(encoding="utf-8")) == previous
    assert sorted(entry.name for entry in tmp_path.iterdir()) == ["material.json"]


def test_atomic_write_json_success_leaves_only_target_file(tmp_path: Path) -> None:
    path = tmp_path / "material.json"

    for seq in range(25):
        atomic_write_json(path, {"type": "timed_media", "seq": seq})

    assert sorted(entry.name for entry in tmp_path.iterdir()) == ["material.json"]
    final = json.loads(path.read_text(encoding="utf-8"))
    assert final["seq"] == 24


def test_legacy_caption_repair_rewrites_once_per_material(tmp_path: Path) -> None:
    store = service.TimedMediaStore(tmp_path / "timed_media")
    material_id = service.material_id_for(VIDEO_ID)
    _seed_legacy_material(store, material_id)
    calls = _count_saves(store)

    first = store.get(material_id)

    assert calls["n"] == 1
    assert first["transcript"]["cues"][0]["text"] == "Learn & apply"
    assert first["segments"][0]["text"] == "Learn & apply"
    assert first["learning"]["marks"][0]["quote"] == "keep&nbsp;me"
    assert first["_caption_text_version"] == 1

    path = store._path(material_id)
    persisted_after_first = json.loads(path.read_text(encoding="utf-8"))
    mtime_after_first = path.stat().st_mtime_ns

    for _ in range(2):
        again = store.get(material_id)
        assert again["transcript"]["cues"][0]["text"] == "Learn & apply"

    assert calls["n"] == 1
    assert json.loads(path.read_text(encoding="utf-8")) == persisted_after_first
    assert path.stat().st_mtime_ns == mtime_after_first


def test_legacy_repair_via_lock_held_get_saves_once(tmp_path: Path) -> None:
    store = service.TimedMediaStore(tmp_path / "timed_media")
    material_id = service.material_id_for(VIDEO_ID)
    _seed_legacy_material(store, material_id)
    calls = _count_saves(store)

    with store.lock(material_id):
        first = store.get(material_id, lock_held=True)
    assert calls["n"] == 1
    assert first["transcript"]["cues"][0]["text"] == "Learn & apply"

    with store.lock(material_id):
        second = store.get(material_id, lock_held=True)
    assert calls["n"] == 1
    assert second["_caption_text_version"] == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "_caption_text_version": 1,
            "transcript": {
                "status": "ready",
                "cues": [{"start": 0, "end": 1, "text": "Clean"}],
            },
            "segments": [{"locator": 1, "start": 0, "end": 1, "text": "Clean"}],
        },
        {
            "segments": [{"locator": 1, "start": 0, "end": 1, "text": "keep&nbsp;me"}],
        },
    ],
    ids=["already_versioned", "no_transcript_dict"],
)
def test_get_skips_repair_rewrite_when_gate_is_clean(tmp_path: Path, overrides: dict) -> None:
    store = service.TimedMediaStore(tmp_path / "timed_media")
    material_id = service.material_id_for(VIDEO_ID)
    store.save({**_base_material(material_id), **overrides})
    calls = _count_saves(store)

    payload = store.get(material_id)

    assert calls["n"] == 0
    if "transcript" in overrides:
        assert payload["transcript"]["cues"][0]["text"] == "Clean"
    else:
        assert payload["segments"][0]["text"] == "keep&nbsp;me"


@pytest.mark.asyncio
async def test_resolve_replaces_transcript_but_preserves_learning(
    monkeypatch, isolated: Path
) -> None:
    store = service.get_timed_media_store()
    material_id = service.material_id_for(VIDEO_ID)
    seeded = {
        **_base_material(material_id),
        "transcript": {
            "status": "ready",
            "cues": [{"start": 0, "end": 1, "text": "Old caption"}],
        },
        "segments": [{"locator": 1, "start": 0, "end": 1, "text": "Old caption"}],
        "metadata": {"title": "Old title", "duration_seconds": 99},
        "_caption_text_version": 1,
    }
    mark = create_mark(seeded, {"kind": "key_point", "start_seconds": 0, "end_seconds": 1})
    seeded["learning"] = {"last_position": 42, "marks": [mark]}
    store.save(seeded)

    async def youtube_metadata(_request):
        return {"title": "New title", "author_name": "Teacher", "lengthSeconds": 120}

    async def youtube_transcript(_video_id, _language):
        return ([{"start": 0, "end": 10, "text": "Fresh caption"}], "en", "youtube_transcript_api")

    monkeypatch.setattr(service, "_youtube_metadata", youtube_metadata)
    monkeypatch.setattr(service, "_youtube_transcript", youtube_transcript)

    public = await service.resolve_material(f"https://youtu.be/{VIDEO_ID}")

    assert [cue["text"] for cue in public["transcript"]["cues"]] == ["Fresh caption"]
    stored = store.get(material_id)
    assert [cue["text"] for cue in stored["transcript"]["cues"]] == ["Fresh caption"]
    assert [segment["text"] for segment in stored["segments"]] == ["Fresh caption"]
    assert stored["learning"] == {"last_position": 42, "marks": [mark]}
    assert stored["metadata"]["title"] == "New title"


@pytest.mark.asyncio
async def test_resolve_adopts_concurrent_progress_save_during_resolution(
    monkeypatch, isolated: Path
) -> None:
    store = service.get_timed_media_store()
    material_id = service.material_id_for(VIDEO_ID)
    store.save(_base_material(material_id))
    progress_landed = threading.Event()

    async def youtube_metadata(_request):
        # A concurrent progress save lands while resolution is still in flight,
        # before resolve_material takes its file lock (service.py:684-693).
        with store.lock(material_id):
            latest = store.get(material_id, lock_held=True)
            latest["learning"]["last_position"] = 77
            store.save(latest)
        progress_landed.set()
        return {"title": "Race", "lengthSeconds": 100}

    async def youtube_transcript(_video_id, _language):
        return ([{"start": 0, "end": 10, "text": "Hello"}], "en", "youtube_transcript_api")

    monkeypatch.setattr(service, "_youtube_metadata", youtube_metadata)
    monkeypatch.setattr(service, "_youtube_transcript", youtube_transcript)

    material = await service.resolve_material(f"https://youtu.be/{VIDEO_ID}")

    assert progress_landed.is_set()
    assert material["learning"]["last_position"] == 77
    stored = store.get(material_id)
    assert stored["learning"]["last_position"] == 77
