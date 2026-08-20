from __future__ import annotations

import pytest

from deeptutor.book.engine import BookEngine
from deeptutor.book.models import Block, BlockType, Book, Page, Progress


class _Storage:
    def __init__(self, page: Page) -> None:
        self.page = page
        self.progress: Progress | None = None
        self.saved: list[Progress] = []

    def load_book(self, book_id: str) -> Book | None:
        return Book(id=book_id) if book_id == self.page.book_id else None

    def load_page(self, book_id: str, page_id: str) -> Page | None:
        return self.page if book_id == self.page.book_id and page_id == self.page.id else None

    def load_progress(self, book_id: str) -> Progress | None:
        return self.progress if book_id == self.page.book_id else None

    def save_progress(self, progress: Progress) -> None:
        self.progress = progress
        self.saved.append(progress)


def _engine(page: Page) -> tuple[BookEngine, _Storage]:
    engine = BookEngine.__new__(BookEngine)
    storage = _Storage(page)
    engine.storage = storage
    return engine, storage


def _interactive_page() -> Page:
    block = Block(
        id="blk_lab",
        type=BlockType.INTERACTIVE,
        payload={"learning_objectives": [{"id": "obj_one", "label": "Explain slope"}]},
    )
    return Page(id="pg_one", book_id="bk_one", blocks=[block])


def _activity(**overrides):
    payload = {
        "book_id": "bk_one",
        "page_id": "pg_one",
        "block_id": "blk_lab",
        "schema_version": 1,
        "event_id": "event_one",
        "objective_ids": ["obj_one"],
        "activity_type": "parameter_change",
        "result": "completed",
        "payload": {"parameter": "slope"},
        "occurred_at": 1.0,
    }
    payload.update(overrides)
    return payload


def test_engine_records_an_objective_linked_activity_once():
    engine, storage = _engine(_interactive_page())

    first = engine.record_learning_activity(**_activity())
    second = engine.record_learning_activity(**_activity())

    assert first is not None and second is not None
    assert len(first.learning_activities) == 1
    assert len(storage.saved) == 2  # initial progress creation, then one event


def test_engine_rejects_objectives_not_declared_by_the_block():
    engine, _ = _engine(_interactive_page())

    with pytest.raises(ValueError, match="unknown objective"):
        engine.record_learning_activity(**_activity(objective_ids=["obj_injected"]))


def test_engine_rejects_non_interactive_blocks():
    page = _interactive_page()
    page.blocks[0].type = BlockType.QUIZ
    engine, _ = _engine(page)

    assert engine.record_learning_activity(**_activity()) is None
