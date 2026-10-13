"""Copy-drift contract for ``refresh_invidious_transcript`` (F4).

``refresh_invidious_transcript`` re-resolves captions for one stored
timed-media record. The contract it must keep is deliberately narrow:

* It rewrites only the timed-media copy (``transcript`` + ``segments``).
* The reading projection created by the watching→reading migration
  (TranscriptSegments ingested as units, notebook notes copied as
  annotations) is a snapshot that intentionally does NOT follow the
  refresh — the single-write behaviour is currently intentional, so any
  future change that makes the reading copy track the refresh must be a
  conscious product decision, not an accident.
* The refresh requires ``provider_cache.invidious_formats`` to exist;
  without it the refresh fails before any network call and before any
  storage mutation.

All network seams are faked; no test in this module reaches the network.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
import pytest_asyncio

from deeptutor.reading.catalog_store import ReadingCatalogStore
from deeptutor.reading.ingestion import (
    build_transcript_segments,
    normalize_transcript_segments,
    url_material_id,
)
from deeptutor.reading.store import ReadingStore
from deeptutor.services.notebook.service import NotebookManager
from deeptutor.video_learning import notes as video_notes
from deeptutor.video_learning import service
from deeptutor.video_learning.reading_migration import WatchingToReadingMigration

VIDEO_ID = "dQw4w9WgXcQ"
SOURCE_URL = f"https://youtu.be/{VIDEO_ID}"
INVIDIOUS_SETTINGS = {
    "default_provider": "invidious",
    "invidious": {"api_base_url": "http://invidious:3000"},
}
OLD_CUES = [
    {"start": 0, "end": 12, "text": "Opening idea."},
    {"start": 30, "end": 42, "text": "Later idea."},
]
NEW_CUES = [
    {"start": 0, "end": 12, "text": "Revised opening."},
    {"start": 30, "end": 42, "text": "Revised later."},
]
PROVIDER_CACHE = {"invidious_formats": [{"format_id": "18", "mime_type": "video/mp4"}]}


def _reading_snapshot_texts(cues: list[dict]) -> list[str]:
    segments = build_transcript_segments(normalize_transcript_segments(cues))
    return [row.text for row in segments]


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
    service.save_video_learning_settings(INVIDIOUS_SETTINGS)
    return tmp_path


@dataclass
class _Drift:
    timed_id: str
    reading_material_id: str
    timed_store: service.TimedMediaStore
    reading: ReadingStore
    reading_root: Path


@pytest_asyncio.fixture
async def migrated(isolated: Path, monkeypatch) -> _Drift:
    timed_id = service.material_id_for(VIDEO_ID)
    timed_store = service.get_timed_media_store()
    timed_store.save(
        {
            "version": 1,
            "type": "timed_media",
            "material_id": timed_id,
            "source": {"provider": "youtube", "video_id": VIDEO_ID, "url": SOURCE_URL},
            "metadata": {
                "title": "Legacy lecture",
                "duration_seconds": 120,
                "thumbnail_url": "https://img.example/cover.jpg",
            },
            "transcript": {
                "status": "ready",
                "reason": "",
                "language": "en",
                "source": "invidious",
                "cues": OLD_CUES,
            },
            "segments": service.build_segments(OLD_CUES),
            "learning": {"last_position": 35},
            "provider_cache": PROVIDER_CACHE,
            "_caption_text_version": 1,
        }
    )
    reading = ReadingStore(isolated / "reading")
    catalog = ReadingCatalogStore(reading.root)
    notebook = NotebookManager(base_dir=str(isolated / "notebooks"))
    monkeypatch.setattr(video_notes, "get_timed_media_store", lambda: timed_store)
    video_notes.create_note(notebook, timed_id, "Anchor note", 2)
    migration = WatchingToReadingMigration(
        timed_media_store=timed_store,
        reading_store=reading,
        catalog=catalog,
        notebook_manager=notebook,
    )
    await migration.migrate(timed_id)
    return _Drift(
        timed_id=timed_id,
        reading_material_id=url_material_id(SOURCE_URL),
        timed_store=timed_store,
        reading=reading,
        reading_root=reading.root,
    )


@pytest.fixture
def fake_transport(monkeypatch):
    calls = {"metadata": 0, "transcript": 0}

    async def metadata(_client, _base, _video_id):
        calls["metadata"] += 1
        return {"captions": [{"label": "English", "languageCode": "en"}]}

    async def transcript(_client, _base, _video_id, _captions, _language, **_kwargs):
        calls["transcript"] += 1
        return (NEW_CUES, "en", "invidious")

    monkeypatch.setattr(service, "_invidious_metadata", metadata)
    monkeypatch.setattr(service, "_invidious_transcript", transcript)
    return calls


@pytest.mark.asyncio
async def test_refresh_updates_only_the_timed_media_copy(migrated: _Drift, fake_transport) -> None:
    """The timed-media copy follows the refresh; the reading copy does not."""
    refreshed = await service.refresh_invidious_transcript(migrated.timed_id)

    assert [cue["text"] for cue in refreshed["transcript"]["cues"]] == [
        cue["text"] for cue in NEW_CUES
    ]
    assert refreshed["segments"] == service.build_segments(NEW_CUES)
    stored = migrated.timed_store.get(migrated.timed_id)
    assert [cue["text"] for cue in stored["transcript"]["cues"]] == [
        cue["text"] for cue in NEW_CUES
    ]
    assert stored["segments"] == service.build_segments(NEW_CUES)


@pytest.mark.asyncio
async def test_reading_segment_copy_does_not_follow_the_refresh(
    migrated: _Drift, fake_transport
) -> None:
    """Copy drift is currently intentional: single write, reading stays stale."""
    stale_texts = _reading_snapshot_texts(OLD_CUES)
    assert migrated.reading.manifest(migrated.reading_material_id).unit_count == len(stale_texts)

    await service.refresh_invidious_transcript(migrated.timed_id)

    for locator, stale_text in enumerate(stale_texts, start=1):
        assert migrated.reading.unit_text(migrated.reading_material_id, locator) == stale_text, (
            "the reading projection copy intentionally does not follow refresh"
        )


@pytest.mark.asyncio
async def test_migrated_annotations_do_not_follow_the_refresh(
    migrated: _Drift, fake_transport
) -> None:
    """Annotation quotes are migration-time snapshots and intentionally stay."""
    before = migrated.reading.annotations(migrated.reading_material_id)
    assert [row.kind for row in before] == ["note"]

    await service.refresh_invidious_transcript(migrated.timed_id)

    after = migrated.reading.annotations(migrated.reading_material_id)
    assert after == before


@pytest.mark.asyncio
async def test_refresh_rewrites_only_transcript_and_segments_within_the_record(
    migrated: _Drift, fake_transport
) -> None:
    """Single-write boundary inside the timed-media record itself."""
    original = migrated.timed_store.get(migrated.timed_id)
    learning_before = dict(original["learning"])
    metadata_before = dict(original["metadata"])
    source_before = dict(original["source"])
    cache_before = dict(original["provider_cache"])

    await service.refresh_invidious_transcript(migrated.timed_id)

    stored = migrated.timed_store.get(migrated.timed_id)
    assert stored["transcript"]["cues"] != original["transcript"]["cues"]
    assert stored["segments"] != original["segments"]
    assert stored["learning"] == learning_before
    assert stored["metadata"] == metadata_before
    assert stored["source"] == source_before
    assert stored["provider_cache"] == cache_before


@pytest.mark.asyncio
async def test_refresh_does_not_write_into_the_reading_store(
    migrated: _Drift, fake_transport
) -> None:
    before = {path: path.read_bytes() for path in sorted(migrated.reading_root.rglob("*.json"))}
    assert before

    await service.refresh_invidious_transcript(migrated.timed_id)

    after = {path: path.read_bytes() for path in sorted(migrated.reading_root.rglob("*.json"))}
    assert after == before


@pytest.mark.asyncio
async def test_refresh_requires_provider_cache_and_fails_without_it(
    monkeypatch, isolated: Path
) -> None:
    """Missing provider cache takes the failure branch before any network call."""
    timed_id = service.material_id_for(VIDEO_ID)
    timed_store = service.get_timed_media_store()
    timed_store.save(
        {
            "version": 1,
            "type": "timed_media",
            "material_id": timed_id,
            "source": {"provider": "youtube", "video_id": VIDEO_ID, "url": SOURCE_URL},
            "metadata": {"title": "Legacy lecture", "duration_seconds": 120},
            "transcript": {"status": "ready", "cues": OLD_CUES},
            "segments": service.build_segments(OLD_CUES),
            "learning": {"last_position": 35},
            "_caption_text_version": 1,
        }
    )
    calls = await _refresh_without_provider_cache(monkeypatch, timed_store, timed_id)
    assert calls == {"metadata": 0, "transcript": 0}


async def _refresh_without_provider_cache(monkeypatch, timed_store, timed_id) -> dict:
    calls = {"metadata": 0, "transcript": 0}

    async def metadata(_client, _base, _video_id):
        calls["metadata"] += 1
        return {"captions": []}

    async def transcript(_client, _base, _video_id, _captions, _language, **_kwargs):
        calls["transcript"] += 1
        return (NEW_CUES, "en", "invidious")

    monkeypatch.setattr(service, "_invidious_metadata", metadata)
    monkeypatch.setattr(service, "_invidious_transcript", transcript)

    with pytest.raises(service.TimedMediaError, match="not available"):
        await service.refresh_invidious_transcript(timed_id)
    return calls


@pytest.mark.asyncio
async def test_missing_provider_cache_leaves_timed_media_bytes_untouched(
    monkeypatch, isolated: Path
) -> None:
    timed_id = service.material_id_for(VIDEO_ID)
    timed_store = service.get_timed_media_store()
    timed_store.save(
        {
            "version": 1,
            "type": "timed_media",
            "material_id": timed_id,
            "source": {"provider": "youtube", "video_id": VIDEO_ID, "url": SOURCE_URL},
            "metadata": {"title": "Legacy lecture", "duration_seconds": 120},
            "transcript": {"status": "ready", "cues": OLD_CUES},
            "segments": service.build_segments(OLD_CUES),
            "learning": {"last_position": 35},
            "_caption_text_version": 1,
        }
    )
    before = {path: path.read_bytes() for path in timed_store.root.glob("*.json")}
    assert before

    await _refresh_without_provider_cache(monkeypatch, timed_store, timed_id)

    after = {path: path.read_bytes() for path in timed_store.root.glob("*.json")}
    assert after == before


@pytest.mark.asyncio
async def test_refresh_rejects_records_without_a_valid_video_id(
    monkeypatch, isolated: Path
) -> None:
    timed_store = service.get_timed_media_store()
    timed_id = "aaaaaaaaaaaaaaaaaaaa"
    timed_store.save(
        {
            "version": 1,
            "type": "timed_media",
            "material_id": timed_id,
            "source": {"provider": "youtube", "video_id": "bad id!", "url": SOURCE_URL},
            "metadata": {"title": "Broken source"},
            "transcript": {"status": "ready", "cues": OLD_CUES},
            "segments": service.build_segments(OLD_CUES),
            "learning": {"last_position": 35},
            "provider_cache": PROVIDER_CACHE,
            "_caption_text_version": 1,
        }
    )
    before = {path: path.read_bytes() for path in timed_store.root.glob("*.json")}

    async def metadata(_client, _base, _video_id):  # pragma: no cover - must not run
        raise AssertionError("network seam must not be reached for invalid ids")

    monkeypatch.setattr(service, "_invidious_metadata", metadata)

    with pytest.raises(service.TimedMediaNotFound):
        await service.refresh_invidious_transcript(timed_id)

    after = {path: path.read_bytes() for path in timed_store.root.glob("*.json")}
    assert after == before
