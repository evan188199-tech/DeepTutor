"""Focused regression locks for legacy Watching data migration edge cases.

Complements ``test_reading_migration.py`` by locking:
- corrupted legacy store entries fail safe without creating Reading state,
- a corrupted entry never rewrites session preferences at the API boundary,
- migrated annotations keep the legacy note capture/update timestamps.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from deeptutor.api.routers import sessions as sessions_router
from deeptutor.reading.catalog_store import ReadingCatalogStore
from deeptutor.reading.store import ReadingStore
from deeptutor.services.notebook.service import NotebookManager
from deeptutor.video_learning import notes as video_notes
from deeptutor.video_learning.reading_migration import WatchingToReadingMigration
from deeptutor.video_learning.service import (
    TimedMediaNotFound,
    TimedMediaStore,
    material_id_for,
)


def _write_raw_payload(store: TimedMediaStore, timed_id: str, payload: str) -> None:
    store.root.mkdir(parents=True, exist_ok=True)
    (store.root / f"{timed_id}.json").write_text(payload, encoding="utf-8")


def _build_stores(
    tmp_path: Path,
) -> tuple[TimedMediaStore, ReadingStore, ReadingCatalogStore, NotebookManager]:
    timed_store = TimedMediaStore(tmp_path / "timed-media")
    reading = ReadingStore(tmp_path / "reading")
    catalog = ReadingCatalogStore(reading.root)
    notebook = NotebookManager(base_dir=str(tmp_path / "notebooks"))
    return timed_store, reading, catalog, notebook


def _legacy_session(timed_id: str) -> dict[str, Any]:
    return {
        "id": "legacy-session",
        "session_id": "legacy-session",
        "title": "Legacy lecture question",
        "preferences": {
            "capability": "immersive_watching",
            "workspace_mode": "immersive_watching",
            "session_kind": "immersive_watching",
            "timed_media_id": timed_id,
            "timed_media_viewport": {"time_seconds": 35},
        },
        "messages": [],
    }


class _SessionStore:
    def __init__(self, session: dict[str, Any]) -> None:
        self.session = session
        self.preference_updates: list[tuple[str, dict[str, Any]]] = []

    async def list_sessions(self, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        return [self.session][offset : offset + limit]

    async def get_session_with_messages(self, session_id: str) -> dict[str, Any] | None:
        return self.session if self.session["id"] == session_id else None

    async def update_session_preferences(
        self,
        session_id: str,
        updates: dict[str, Any],
    ) -> bool:
        self.preference_updates.append((session_id, updates))
        self.session.setdefault("preferences", {}).update(updates)
        return True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "expected_error"),
    [
        pytest.param(
            '{"version": 1, "type": "timed_media", "material_i',
            TimedMediaNotFound,
            id="corrupt-json",
        ),
        pytest.param(
            '{"version": 1, "type": "timed_media"}',
            ValueError,
            id="valid-json-missing-source",
        ),
    ],
)
async def test_corrupt_legacy_record_fails_without_creating_reading_state(
    tmp_path: Path,
    payload: str,
    expected_error: type[Exception],
) -> None:
    timed_store, reading, catalog, notebook = _build_stores(tmp_path)
    timed_id = material_id_for("abc123xyz00")
    _write_raw_payload(timed_store, timed_id, payload)
    migration = WatchingToReadingMigration(
        timed_media_store=timed_store,
        reading_store=reading,
        catalog=catalog,
        notebook_manager=notebook,
    )

    with pytest.raises(expected_error):
        await migration.migrate(timed_id)

    assert catalog.list_workspaces() == []


@pytest.mark.asyncio
async def test_corrupt_legacy_record_leaves_session_response_intact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timed_store, reading, catalog, notebook = _build_stores(tmp_path)
    timed_id = material_id_for("abc123xyz00")
    _write_raw_payload(timed_store, timed_id, "{corrupt")
    migration = WatchingToReadingMigration(
        timed_media_store=timed_store,
        reading_store=reading,
        catalog=catalog,
        notebook_manager=notebook,
    )
    monkeypatch.setattr(
        "deeptutor.video_learning.reading_migration.WatchingToReadingMigration",
        lambda: migration,
    )
    session = _legacy_session(timed_id)
    store = _SessionStore(session)
    monkeypatch.setattr(sessions_router, "get_session_store", lambda: store)

    response = await sessions_router.get_session("legacy-session")

    assert response["preferences"] == session["preferences"]
    assert store.preference_updates == []


@pytest.mark.asyncio
async def test_migrated_annotations_keep_note_timestamps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timed_store, reading, catalog, notebook = _build_stores(tmp_path)
    timed_id = material_id_for("abc123xyz00")
    timed_store.save(
        {
            "version": 1,
            "type": "timed_media",
            "material_id": timed_id,
            "source": {
                "provider": "youtube",
                "video_id": "abc123xyz00",
                "url": "https://youtu.be/abc123xyz00",
            },
            "metadata": {
                "title": "Legacy lecture",
                "duration_seconds": 120,
                "thumbnail_url": "https://img.example/cover.jpg",
            },
            "transcript": {
                "status": "ready",
                "cues": [
                    {"start": 0, "end": 12, "text": "Opening idea."},
                    {"start": 30, "end": 42, "text": "Later idea."},
                ],
            },
            "learning": {"last_position": 35},
        }
    )
    monkeypatch.setattr(video_notes, "get_timed_media_store", lambda: timed_store)
    first_note = video_notes.create_note(notebook, timed_id, "First note", 2)
    second_note = video_notes.create_note(notebook, timed_id, "Second note", 33)
    migration = WatchingToReadingMigration(
        timed_media_store=timed_store,
        reading_store=reading,
        catalog=catalog,
        notebook_manager=notebook,
    )
    result = await migration.migrate(timed_id)

    annotations = {row.note: row for row in reading.annotations(result.reading_material_id)}
    for note in (first_note, second_note):
        row = annotations[note["body"]]
        assert row.source_anchor == f"#t={int(note['time_seconds'])}"
        # Capture time survives verbatim. ``ReadingStore.save_annotation`` re-stamps
        # ``updated_at`` on every write, so only non-regression can be locked here.
        assert row.created_at == note["created_at"]
        assert row.updated_at >= note["updated_at"]
