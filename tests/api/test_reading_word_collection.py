"""Contract tests for the vocabulary-extension word-collection endpoints.

The pair is the record slice of the Reading vocabulary extension: a collect
request grounded in the stored unit and the server's saved source anchor, and
a read-back route that returns exactly what was written. These tests drive a
real :class:`~deeptutor.reading.store.ReadingStore` and a real
:class:`~deeptutor.learning.storage.LearningStore` through the ASGI routes and
assert on persisted state, not just response bodies:

1. collect → read-back round-trip returns the word, locator, and source anchor;
2. a write without a server-side source anchor is rejected with a clear error
   and persists nothing;
3. a word that does not occur in the stored unit is rejected (grounding);
4. collecting the same word twice converges on one entry (idempotent).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

pytest.importorskip("fastapi")

from deeptutor.api.routers import reading_extensions
from deeptutor.learning.storage import LearningStore
from deeptutor.reading import ReadingStore
from deeptutor.reading.models import ReadingPosition
from deeptutor.services.path_service import PathService

MATERIAL_ID = "a5f6c0ffee12d"
COLLECT_BASE = f"/api/reading/materials/{MATERIAL_ID}/extensions/vocabulary/words"
UNIT_ONE = "The old harbor lights guided the ferry home."
UNIT_TWO = "A quiet estuary spread beyond the breakwater."


@pytest.fixture
def client(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    ReadingStore().ingest_units(
        MATERIAL_ID,
        filename="words.md",
        units=[UNIT_ONE, UNIT_TWO],
        unit="section",
        title="Word fixture",
    )
    app = FastAPI()
    app.include_router(reading_extensions.router, prefix="/api/reading")
    with TestClient(app) as test_client:
        yield test_client
    PathService.reset_instance()


def _save_anchored_position(locator: int = 1, anchor: str = "epubcfi(/6/4)") -> None:
    ReadingStore().save_position(
        MATERIAL_ID,
        ReadingPosition(locator=locator, source_anchor=anchor, percentage=0.5),
    )


def _collect(client: TestClient, **overrides):
    payload = {"locator": 1, "selection": "harbor"}
    payload.update(overrides)
    return client.post(COLLECT_BASE, json=payload)


def test_collect_roundtrips_through_read_back(client: TestClient) -> None:
    _save_anchored_position()

    saved = _collect(client)

    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["material_id"] == MATERIAL_ID
    assert body["word"] == "harbor"
    assert body["locator"] == 1
    assert body["source_anchor"] == "epubcfi(/6/4)"
    assert body["entry_id"]

    fetched = client.get(COLLECT_BASE)
    assert fetched.status_code == 200, fetched.text
    words = fetched.json()["words"]
    assert len(words) == 1
    for key, value in body.items():
        assert words[0][key] == value, f"read-back lost {key}"

    persisted = LearningStore().list_reading_words(MATERIAL_ID)
    assert [entry.word for entry in persisted] == ["harbor"]
    assert persisted[0].source_anchor == "epubcfi(/6/4)"


def test_collect_without_a_source_anchor_is_rejected(client: TestClient) -> None:
    response = _collect(client)

    assert response.status_code == 400
    assert "source anchor" in response.json()["detail"].lower()
    assert client.get(COLLECT_BASE).json()["words"] == []
    assert LearningStore().list_reading_words(MATERIAL_ID) == []


def test_collect_rejects_an_anchor_from_a_different_locator(client: TestClient) -> None:
    _save_anchored_position(locator=2, anchor="epubcfi(/6/8)")

    response = _collect(client, locator=1)

    assert response.status_code == 400
    assert "source anchor" in response.json()["detail"].lower()
    assert LearningStore().list_reading_words(MATERIAL_ID) == []


def test_collect_rejects_a_word_missing_from_the_stored_unit(client: TestClient) -> None:
    _save_anchored_position()

    response = _collect(client, selection="forged dictionary entry")

    assert response.status_code == 400
    assert "visible unit" in response.json()["detail"]
    assert LearningStore().list_reading_words(MATERIAL_ID) == []


def test_collect_rejects_an_out_of_range_locator(client: TestClient) -> None:
    _save_anchored_position()

    response = _collect(client, locator=9)

    assert response.status_code == 400
    assert LearningStore().list_reading_words(MATERIAL_ID) == []


def test_duplicate_collect_of_the_same_word_is_idempotent(client: TestClient) -> None:
    _save_anchored_position()

    first = _collect(client)
    second = _collect(client)

    assert first.status_code == second.status_code == 200
    assert second.json()["entry_id"] == first.json()["entry_id"]
    assert [entry.word for entry in LearningStore().list_reading_words(MATERIAL_ID)] == ["harbor"]


def test_store_rejects_a_word_write_without_a_source_anchor(tmp_path: Path) -> None:
    store = LearningStore(tmp_path / "learning")

    with pytest.raises(ValueError, match="source_anchor"):
        store.record_reading_word(MATERIAL_ID, locator=1, source_anchor="  ", word="harbor")
    assert store.list_reading_words(MATERIAL_ID) == []
