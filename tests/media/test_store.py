from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.media.models import MediaItem, MediaType, SmartPlaylistRule
from deeptutor.media.service import MediaService
from deeptutor.media.store import MediaStore, MediaStoreError


def _item(canonical_id: str, media_type: MediaType = MediaType.MUSIC) -> MediaItem:
    return MediaItem(
        item_id=f"item_{canonical_id[-4:]}",
        canonical_id=canonical_id,
        media_type=media_type,
        title=f"Title {canonical_id[-4:]}",
        creator="Creator",
        duration_seconds=120,
    )


def test_manual_and_smart_playlists_keep_distinct_storage_models(tmp_path: Path) -> None:
    store = MediaStore(tmp_path)
    first = store.upsert_media(_item("mbid:recording:one"))
    second = store.upsert_media(_item("rss:two", MediaType.EPISODE))
    store.set_favorite_or_download(first.item_id, favorite=True)

    manual = store.create_playlist(name="Mixed", description="", kind=__import__("deeptutor.media.models", fromlist=["PlaylistKind"]).PlaylistKind.MANUAL)
    store.add_playlist_items(manual["playlist_id"], [first.canonical_id, second.canonical_id], added_from="test", note="")
    items = store.get_playlist_items(manual["playlist_id"])
    assert [row["media"]["media_type"] for row in items] == ["music", "episode"]

    reordered = store.reorder_playlist_items(manual["playlist_id"], [items[1]["item_id"], items[0]["item_id"]])
    assert [row["media"]["canonical_id"] for row in reordered] == [second.canonical_id, first.canonical_id]

    smart = store.create_playlist(
        name="Liked",
        description="",
        kind=__import__("deeptutor.media.models", fromlist=["PlaylistKind"]).PlaylistKind.SMART,
        rule=SmartPlaylistRule(favorite=True),
    )
    assert store.get_playlist_items(smart["playlist_id"])[0]["media"]["canonical_id"] == first.canonical_id
    with pytest.raises(MediaStoreError, match="cannot be reordered"):
        store.reorder_playlist_items(smart["playlist_id"], ["anything"])


def test_import_preview_is_lossless_and_idempotent(tmp_path: Path) -> None:
    service = MediaService(store=MediaStore(tmp_path), catalog=__import__("deeptutor.media.store", fromlist=["CatalogStore"]).CatalogStore(tmp_path / "catalog.sqlite3"))
    preview = service.preview_import(
        [
            "https://musicbrainz.org/recording/12345678-1234-1234-1234-123456789012",
            "Not a supported source",
            "Artist - Confirmed title",
        ],
        target_playlist_id=None,
        playlist_name="Imported",
    )
    statuses = [candidate["status"] for candidate in preview["candidates"]]
    assert statuses == ["matched", "unrecognized", "needs_confirmation"]

    first = service.apply_import(
        preview_token=preview["preview_token"],
        selected_candidate_ids=None,
        target_playlist_id=None,
        playlist_name="Imported",
        idempotency_key="test-import-key",
    )
    second = service.apply_import(
        preview_token=preview["preview_token"],
        selected_candidate_ids=None,
        target_playlist_id=None,
        playlist_name="Imported",
        idempotency_key="test-import-key",
    )
    assert first.payload == second.payload
    assert first.payload["imported_item_count"] == 2
    assert len(first.payload["playlist"]["items"]) == 2


def test_home_promotes_downloads_when_offline_and_keeps_section_ids_unique(tmp_path: Path) -> None:
    store = MediaStore(tmp_path)
    downloaded = store.upsert_media(_item("mbid:recording:offline"))
    store.set_favorite_or_download(downloaded.item_id, downloaded=True)
    service = MediaService(store=store, catalog=__import__("deeptutor.media.store", fromlist=["CatalogStore"]).CatalogStore(tmp_path / "catalog.sqlite3"))

    sections = service.home(offline=True)
    assert sections[0].kind.value == "offline"
    assert len({section.section_id for section in sections}) == len(sections)
