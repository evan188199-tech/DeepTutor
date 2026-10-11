from __future__ import annotations

from pathlib import Path
import time
from typing import Any

import pytest

from deeptutor.services.notebook.service import NotebookCorruptedError, RecordType
from deeptutor.video_learning import notes, service
from deeptutor.video_learning.service import TimedMediaError, TimedMediaNotFound


class FakeNotebookManager:
    def __init__(self) -> None:
        self._notebooks: dict[str, dict[str, Any]] = {}
        self._records: dict[str, list[dict[str, Any]]] = {}
        self._corrupted: set[str] = set()
        self.reload_calls: list[str] = []
        self.blocked_remove_ids: set[str] = set()
        self.forced_add_result: dict[str, Any] | None = None
        self._seq = 0

    def add_notebook(self, notebook_id: str, *, unreadable: bool = False) -> str:
        self._notebooks[notebook_id] = {"id": notebook_id, "unreadable": unreadable}
        self._records.setdefault(notebook_id, [])
        return notebook_id

    def mark_corrupted(self, notebook_id: str) -> None:
        self._corrupted.add(notebook_id)

    def list_notebooks(self) -> list[dict[str, Any]]:
        return [dict(notebook) for notebook in self._notebooks.values()]

    def get_notebook(self, notebook_id: str) -> dict[str, Any] | None:
        self.reload_calls.append(notebook_id)
        notebook = self._notebooks.get(notebook_id)
        if notebook is not None:
            notebook.pop("unreadable", None)
        return notebook

    def get_records(self, notebook_id: str) -> list[dict[str, Any]]:
        if notebook_id in self._corrupted:
            raise NotebookCorruptedError(
                notebook_id, Path(f"{notebook_id}.json"), ValueError("bad json")
            )
        return [dict(record) for record in self._records.get(notebook_id, [])]

    def get_or_create_notebook(self, name: str, **_kwargs: Any) -> dict[str, Any]:
        for notebook in self._notebooks.values():
            if notebook.get("name") == name:
                return notebook
        self._seq += 1
        notebook = {"id": f"nb-{self._seq}", "name": name}
        self._notebooks[notebook["id"]] = notebook
        self._records.setdefault(notebook["id"], [])
        return notebook

    def add_record(
        self,
        notebook_ids: list[str],
        record_type: RecordType | str,
        title: str,
        user_query: str,
        output: str,
        summary: str = "",
        metadata: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        self._seq += 1
        resolved_type = str(getattr(record_type, "value", record_type))
        record = {
            "id": f"rec-{self._seq:04d}",
            "type": resolved_type,
            "title": title,
            "summary": summary,
            "user_query": user_query,
            "output": output,
            "metadata": dict(metadata or {}),
            "created_at": time.time(),
        }
        if self.forced_add_result is not None:
            return self.forced_add_result
        added_to: list[str] = []
        for notebook_id in notebook_ids:
            if notebook_id in self._corrupted:
                continue
            self._records.setdefault(notebook_id, []).append(dict(record))
            added_to.append(notebook_id)
        return {"record": record, "added_to_notebooks": added_to}

    def update_record(
        self,
        notebook_id: str,
        record_id: str,
        *,
        summary: str | None = None,
        output: str | None = None,
        metadata: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any] | None:
        for record in self._records.get(notebook_id, []):
            if str(record.get("id")) != str(record_id):
                continue
            if summary is not None:
                record["summary"] = summary
            if output is not None:
                record["output"] = output
            if metadata is not None:
                record["metadata"] = {**(record.get("metadata") or {}), **metadata}
            return dict(record)
        return None

    def remove_record(self, notebook_id: str, record_id: str) -> bool:
        records = self._records.get(notebook_id, [])
        for index, record in enumerate(records):
            if str(record.get("id")) == str(record_id):
                if record_id in self.blocked_remove_ids:
                    return False
                records.pop(index)
                return True
        return False

    def copy_record_to(self, notebook_id: str, record: dict[str, Any]) -> None:
        self._records.setdefault(notebook_id, []).append(dict(record))

    def clear_records(self, notebook_id: str) -> None:
        self._records[notebook_id] = []


@pytest.fixture
def manager() -> FakeNotebookManager:
    return FakeNotebookManager()


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> service.TimedMediaStore:
    real_store = service.TimedMediaStore(tmp_path / "timed_media")
    monkeypatch.setattr(notes, "get_timed_media_store", lambda: real_store)
    return real_store


def material_id() -> str:
    return service.material_id_for("dQw4w9WgXcQ")


def seed_material(store: service.TimedMediaStore, **overrides: Any) -> dict[str, Any]:
    material = {
        "version": 1,
        "type": "timed_media",
        "material_id": material_id(),
        "source": {"provider": "youtube", "video_id": "dQw4w9WgXcQ"},
        "metadata": {"title": "  Nested   quotes  ", "duration_seconds": 120},
        "transcript": {
            "status": "ready",
            "language": "en",
            "cues": [
                {"start": 0.0, "end": 20.0, "text": "First cue."},
                {"start": 20.0, "end": 45.0, "text": "Second cue."},
            ],
        },
        "segments": [
            {"locator": 1, "start": 0.0, "end": 30.0, "text": "First idea."},
            {"locator": 2, "start": 30.0, "end": 60.0, "text": "Second idea."},
        ],
        "learning": {},
    }
    material.update(overrides)
    store.save(material)
    return material


def test_format_time_and_clip_helpers_follow_the_display_contract() -> None:
    assert notes._format_time(0) == "0:00"
    assert notes._format_time(35) == "0:35"
    assert notes._format_time(60) == "1:00"
    assert notes._format_time(3671) == "1:01:11"
    assert notes._format_time(-5) == "0:00"
    assert notes._clip_text("  sparse\n\n  text  ") == "sparse text"
    clipped = notes._clip_text("x" * 400)
    assert len(clipped) == notes.MAX_QUOTE_CHARS
    assert clipped.endswith("...")


def test_create_note_stamps_segment_quote_locator_and_notebook(
    manager: FakeNotebookManager, store: service.TimedMediaStore
) -> None:
    seed_material(store)
    note = notes.create_note(manager, material_id(), "  Key point here  ", 35)

    assert note["material_id"] == material_id()
    assert note["body"] == "Key point here"
    assert note["time_seconds"] == 35.0
    assert note["locator"] == 2
    assert note["quote"] == "Second idea."
    assert note["notebook_id"].startswith("nb-")
    assert note["note_id"].startswith("rec-")
    assert note["updated_at"] > 0

    records = manager.get_records(note["notebook_id"])
    assert len(records) == 1
    record = records[0]
    assert record["type"] == RecordType.VIDEO_LEARNING
    assert record["title"] == "Nested quotes - 0:35"
    assert record["summary"] == "Key point here"
    assert record["user_query"] == "Second idea."
    assert record["metadata"]["material_id"] == material_id()
    assert record["metadata"]["locator"] == 2


def test_create_note_falls_back_to_transcript_cues_for_locators(
    manager: FakeNotebookManager, store: service.TimedMediaStore
) -> None:
    seed_material(store, segments=[])
    note = notes.create_note(manager, material_id(), "Cue anchored", 30)

    assert note["locator"] == 2
    assert note["quote"] == "Second cue."


def test_create_note_rejects_empty_body_and_timestamps_beyond_duration(
    manager: FakeNotebookManager, store: service.TimedMediaStore
) -> None:
    seed_material(store)
    with pytest.raises(TimedMediaError):
        notes.create_note(manager, material_id(), "   ", 10)
    with pytest.raises(TimedMediaError):
        notes.create_note(manager, material_id(), "Too late", 121)
    assert manager.list_notebooks() == []


def test_create_note_raises_when_the_notebook_rejects_the_save(
    manager: FakeNotebookManager, store: service.TimedMediaStore
) -> None:
    seed_material(store)
    manager.forced_add_result = {"record": {"id": "rec-0001"}, "added_to_notebooks": []}
    with pytest.raises(TimedMediaError, match="could not be saved"):
        notes.create_note(manager, material_id(), "Unsaved", 10)


def test_list_notes_dedupes_copies_sorts_by_timestamp_and_filters(
    manager: FakeNotebookManager, store: service.TimedMediaStore
) -> None:
    seed_material(store)
    late = notes.create_note(manager, material_id(), "Late", 60)
    early = notes.create_note(manager, material_id(), "Early", 10)
    middle = notes.create_note(manager, material_id(), "Middle", 35)
    stray = manager.get_records(late["notebook_id"])[0]
    manager.copy_record_to(late["notebook_id"], {**stray, "metadata": {"material_id": "other"}})
    manager.copy_record_to(
        late["notebook_id"],
        {**stray, "id": "rec-other", "type": RecordType.READING},
    )
    manager.add_notebook("nb-shadow")
    manager.copy_record_to("nb-shadow", dict(stray))

    listed = notes.list_notes(manager, material_id())

    assert [note["note_id"] for note in listed] == [
        early["note_id"],
        middle["note_id"],
        late["note_id"],
    ]
    assert all(note["notebook_id"] == early["notebook_id"] for note in listed)


def test_list_notes_skips_unreadable_and_corrupted_notebooks(
    manager: FakeNotebookManager, store: service.TimedMediaStore
) -> None:
    seed_material(store)
    saved = notes.create_note(manager, material_id(), "Kept", 12)
    manager.add_notebook("nb-recovering", unreadable=True)
    manager.add_notebook("nb-corrupted")
    manager.mark_corrupted("nb-corrupted")
    record = dict(manager.get_records(saved["notebook_id"])[0])
    manager.copy_record_to("nb-recovering", record)
    manager.copy_record_to("nb-corrupted", record)
    manager.clear_records(saved["notebook_id"])

    listed = notes.list_notes(manager, material_id())

    assert manager.reload_calls == ["nb-recovering"]
    assert [note["body"] for note in listed] == ["Kept"]
    assert listed[0]["notebook_id"] == "nb-recovering"


def test_update_note_merges_metadata_and_refreshes_every_copy(
    manager: FakeNotebookManager, store: service.TimedMediaStore
) -> None:
    seed_material(store)
    note = notes.create_note(manager, material_id(), "Before", 35)
    manager.add_notebook("nb-copy")
    manager.copy_record_to("nb-copy", dict(manager.get_records(note["notebook_id"])[0]))
    original_updated_at = note["updated_at"]

    updated = notes.update_note(manager, material_id(), note["note_id"], "Rewritten body")

    assert updated["body"] == "Rewritten body"
    assert updated["time_seconds"] == 35.0
    assert updated["locator"] == 2
    assert updated["quote"] == "Second idea."
    assert updated["updated_at"] >= original_updated_at
    for notebook_id in (note["notebook_id"], "nb-copy"):
        record = manager.get_records(notebook_id)[0]
        assert record["output"] == "Rewritten body"
        assert record["summary"] == "Rewritten body"
        assert record["metadata"]["material_id"] == material_id()
        assert record["metadata"]["time_seconds"] == 35.0
        assert record["metadata"]["updated_at"] == updated["updated_at"]


def test_update_and_delete_require_an_existing_note_with_text(
    manager: FakeNotebookManager, store: service.TimedMediaStore
) -> None:
    seed_material(store)
    with pytest.raises(TimedMediaError):
        notes.update_note(manager, material_id(), "rec-missing", "   ")
    with pytest.raises(TimedMediaNotFound):
        notes.update_note(manager, material_id(), "rec-missing", "Edited")
    with pytest.raises(TimedMediaNotFound):
        notes.delete_note(manager, material_id(), "rec-missing")


def test_delete_note_removes_every_copy_and_reports(
    manager: FakeNotebookManager, store: service.TimedMediaStore
) -> None:
    seed_material(store)
    note = notes.create_note(manager, material_id(), "Doomed", 20)
    manager.add_notebook("nb-copy")
    manager.copy_record_to("nb-copy", dict(manager.get_records(note["notebook_id"])[0]))

    assert notes.delete_note(manager, material_id(), note["note_id"]) is True
    assert manager.get_records(note["notebook_id"]) == []
    assert manager.get_records("nb-copy") == []
    assert notes.list_notes(manager, material_id()) == []

    survivor = notes.create_note(manager, material_id(), "Stuck", 40)
    manager.blocked_remove_ids.add(survivor["note_id"])
    assert notes.delete_note(manager, material_id(), survivor["note_id"]) is False
    assert manager.get_records(survivor["notebook_id"])


def test_export_notes_renders_sorted_sections_quotes_and_the_empty_state(
    manager: FakeNotebookManager, store: service.TimedMediaStore
) -> None:
    seed_material(store)
    empty = notes.export_notes(manager, material_id())
    assert empty.startswith("# Video notes: Nested quotes\n")
    assert "_No timestamped notes captured yet._" in empty
    assert empty.endswith("\n")

    notes.create_note(manager, material_id(), "Later thought", 60)
    notes.create_note(manager, material_id(), "First thought", 10)
    exported = notes.export_notes(manager, material_id())

    assert exported.index("## 0:10") < exported.index("## 1:00")
    assert "First thought" in exported
    assert "Later thought" in exported
    assert "> Second idea." in exported


def test_export_notes_clips_long_titles_and_falls_back_to_generic(
    manager: FakeNotebookManager, store: service.TimedMediaStore
) -> None:
    seed_material(store, metadata={"title": "T" * 300})
    heading = notes.export_notes(manager, material_id()).splitlines()[0]
    assert heading == f"# Video notes: {'T' * 137}..."

    seed_material(store, metadata={})
    heading = notes.export_notes(manager, material_id()).splitlines()[0]
    assert heading == "# Video notes: Timed media"


def test_note_reads_require_the_material_to_exist(
    manager: FakeNotebookManager, store: service.TimedMediaStore
) -> None:
    with pytest.raises(TimedMediaNotFound):
        notes.list_notes(manager, material_id())
    with pytest.raises(TimedMediaNotFound):
        notes.create_note(manager, material_id(), "Orphaned", 5)
    assert store.root.is_dir()
