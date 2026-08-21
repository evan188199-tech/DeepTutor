"""Tests for the MarginNote 4 production SQLite store."""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.capabilities.marginnote4.models import (
    CARD,
    MINDMAP_NODE,
    NOTE,
    DeletedMarginNoteObject,
    MarginNoteObject,
    MarginNoteSyncConflict,
    SyncBatch,
)
from deeptutor.capabilities.marginnote4.store import MarginNoteStore


def _objects(device_id: str = "dev1") -> list[MarginNoteObject]:
    return [
        MarginNoteObject(
            object_id="note1",
            object_type=NOTE,
            title="Photosynthesis",
            content="Plants convert light into chemical energy.",
            excerpt="The process by which green plants use sunlight...",
            document_id="doc1",
            document_title="Biology Textbook",
            page=42,
            tags=["biology", "plants"],
            links=["card1"],
            color="yellow",
            created_at="2025-01-01T00:00:00Z",
            updated_at="2025-01-02T00:00:00Z",
            device_id=device_id,
            revision=1,
            raw={"mnId": "note1"},
        ),
        MarginNoteObject(
            object_id="card1",
            object_type=CARD,
            title="What is photosynthesis?",
            content="Process of converting light energy to chemical energy",
            tags=["biology"],
            links=["note1"],
            device_id=device_id,
            revision=1,
        ),
        MarginNoteObject(
            object_id="node1",
            object_type=MINDMAP_NODE,
            title="Energy Conversion",
            content="Central concept linking photosynthesis and respiration",
            links=["note1", "card1"],
            device_id=device_id,
            revision=1,
        ),
    ]


def _sync(
    store: MarginNoteStore,
    *,
    batch_id: str,
    cursor: str,
    objects: list[MarginNoteObject] | None = None,
    deleted: list[DeletedMarginNoteObject] | None = None,
) -> object:
    return store.ingest(
        SyncBatch(
            device_id="dev1",
            batch_id=batch_id,
            cursor=cursor,
            objects=_objects() if objects is None else objects,
            deleted_objects=deleted or [],
        )
    )


def test_schema_v2_and_integrity(tmp_path: Path) -> None:
    store = MarginNoteStore(tmp_path / "test.db")
    assert store.schema_version == 2
    assert store.check_integrity() is True


def test_incremental_ingest_is_idempotent(tmp_path: Path) -> None:
    store = MarginNoteStore(tmp_path / "test.db")
    first = _sync(store, batch_id="batch-0001", cursor=store.server_cursor())
    assert (first.stored, first.updated, first.deleted) == (3, 0, 0)
    assert store.count() == 3

    second = _sync(
        store,
        batch_id="batch-0001",
        cursor="obsolete-client-cursor",
        objects=[_objects()[0]],
    )
    assert second.duplicate is True
    assert second.new_cursor == first.new_cursor
    assert store.count() == 3


def test_incremental_update_and_delete(tmp_path: Path) -> None:
    store = MarginNoteStore(tmp_path / "test.db")
    first = _sync(store, batch_id="batch-0001", cursor=store.server_cursor())
    updated = _objects()[:1]
    updated[0].title = "Photosynthesis Updated"
    updated[0].revision = 2
    second = _sync(store, batch_id="batch-0002", cursor=first.new_cursor, objects=updated)
    assert second.updated == 1
    assert store.get("note1").title == "Photosynthesis Updated"

    third = _sync(
        store,
        batch_id="batch-0003",
        cursor=second.new_cursor,
        objects=[],
        deleted=[DeletedMarginNoteObject("note1", "2025-01-03T00:00:00Z")],
    )
    assert third.deleted == 1
    assert store.get("note1") is None


def test_stale_cursor_returns_server_cursor(tmp_path: Path) -> None:
    store = MarginNoteStore(tmp_path / "test.db")
    _sync(store, batch_id="batch-0001", cursor=store.server_cursor())
    with pytest.raises(MarginNoteSyncConflict) as exc_info:
        _sync(store, batch_id="batch-0002", cursor="stale", objects=[])
    assert exc_info.value.server_cursor == store.server_cursor()


def test_snapshot_is_invisible_until_commit_and_commit_is_idempotent(tmp_path: Path) -> None:
    store = MarginNoteStore(tmp_path / "test.db")
    _sync(store, batch_id="initial", cursor=store.server_cursor())
    snapshot = store.create_snapshot(device_id="dev1", total_batches=1)
    replacement = MarginNoteObject(
        object_id="new1", object_type=NOTE, title="Replacement", revision=1
    )
    response = store.append_snapshot(
        snapshot["snapshot_id"], sequence=1, batch_id="snap-batch-1", objects=[replacement]
    )
    assert response["stored"] == 1
    assert store.get("new1") is None
    assert store.count() == 3

    committed = store.commit_snapshot(snapshot["snapshot_id"])
    assert committed["state"] == "committed"
    assert store.count() == 1
    assert store.get("new1") is not None

    duplicate = store.commit_snapshot(snapshot["snapshot_id"])
    assert duplicate["duplicate"] is True
    assert store.count() == 1


def test_snapshot_batch_retry_is_idempotent(tmp_path: Path) -> None:
    store = MarginNoteStore(tmp_path / "test.db")
    snapshot = store.create_snapshot(device_id="dev1", total_batches=2)
    args = (snapshot["snapshot_id"],)
    kwargs = {"sequence": 1, "batch_id": "same-id", "objects": _objects()}
    first = store.append_snapshot(*args, **kwargs)
    retry = store.append_snapshot(*args, **kwargs)
    assert first["duplicate"] is False
    assert retry["duplicate"] is True


def test_search_reads_only_live_generation_and_filters_type(tmp_path: Path) -> None:
    store = MarginNoteStore(tmp_path / "test.db")
    _sync(store, batch_id="initial", cursor=store.server_cursor())
    hits = store.search("photosynthesis")
    assert {hit["object_id"] for hit in hits} >= {"note1", "card1", "node1"}
    cards = store.search("photosynthesis", object_type="card")
    assert [hit["object_id"] for hit in cards] == ["card1"]
    assert all(hit["locator"] for hit in hits)


def test_documents_tags_links_and_pagination(tmp_path: Path) -> None:
    store = MarginNoteStore(tmp_path / "test.db")
    _sync(store, batch_id="initial", cursor=store.server_cursor())
    documents = store.list_documents()
    assert documents[0]["document_id"] == "doc1"
    assert {item["tag"] for item in store.collect_tags()} == {"biology", "plants"}
    assert {item["object_id"] for item in store.linked_objects("note1")} >= {
        "card1",
        "node1",
    }
    page_one = store.list_objects(limit=2, offset=0)
    page_two = store.list_objects(limit=2, offset=2)
    assert len(page_one) == 2
    assert len(page_two) == 1
    assert len({item["object_id"] for item in page_one + page_two}) == 3


def test_reset_for_resync_creates_clean_generation(tmp_path: Path) -> None:
    store = MarginNoteStore(tmp_path / "test.db")
    _sync(store, batch_id="initial", cursor=store.server_cursor())
    store.reset_for_resync()
    assert store.count() == 0
    assert store.search("photosynthesis") == []
    _sync(store, batch_id="after-reset", cursor=store.server_cursor())
    assert store.count() == 3
