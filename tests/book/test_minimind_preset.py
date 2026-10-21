from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.book.models import BookStatus, PageStatus
from deeptutor.book.presets.minimind import (
    BOOK_ID,
    build_minimind_book,
    install_minimind_book,
)
from deeptutor.book.storage import BookStorage
from deeptutor.services.path_service import PathService


def test_minimind_preset_builds_complete_book() -> None:
    book, inputs, spine, pages = build_minimind_book()

    assert book.id == BOOK_ID
    assert book.status == BookStatus.READY
    assert book.language == "zh"
    assert inputs.language == "zh"
    assert len(spine.chapters) == 6
    assert len(pages) == 6
    assert [page.order for page in pages] == [1, 2, 3, 4, 5, 6]
    assert all(page.status == PageStatus.READY for page in pages)
    assert all(len(page.blocks) == 4 for page in pages)

    chapter_ids = {chapter.id for chapter in spine.chapters}
    assert {page.chapter_id for page in pages} == chapter_ids
    assert {node.chapter_id for node in spine.concept_graph.nodes} <= chapter_ids
    node_ids = {node.id for node in spine.concept_graph.nodes}
    assert all(edge.src in node_ids and edge.dst in node_ids for edge in spine.concept_graph.edges)

    interactive_blocks = [
        block for page in pages for block in page.blocks if block.type.value == "interactive"
    ]
    assert len(interactive_blocks) == 6
    for block in interactive_blocks:
        html = str(block.payload["code"]["content"])
        assert "<!doctype html>" in html.lower()
        assert "<script>" in html
        assert "http://" not in html and "https://" not in html

    questions = [
        question
        for page in pages
        for block in page.blocks
        if block.type.value == "quiz"
        for question in block.payload["questions"]
    ]
    assert len(questions) == 12
    assert len({question["question_id"] for question in questions}) == 12
    for question in questions:
        assert question["correct_answer"] in question["options"]
        assert question["explanation"]


def test_minimind_preset_install_is_idempotent_and_preserves_progress(
    tmp_path: Path,
) -> None:
    storage = BookStorage(path_service=PathService(workspace_root=tmp_path))

    first = install_minimind_book(storage)
    assert first == {"status": "installed", "book_id": BOOK_ID, "pages": 6}

    progress = storage.load_progress(BOOK_ID)
    assert progress is not None
    progress.visited_page_ids = ["pg_pipeline", "pg_tokenizer"]
    progress.current_page_id = "pg_tokenizer"
    storage.save_progress(progress)

    second = install_minimind_book(storage)
    assert second == {"status": "already_installed", "book_id": BOOK_ID}

    forced = install_minimind_book(storage, force=True)
    assert forced == {"status": "installed", "book_id": BOOK_ID, "pages": 6}
    preserved = storage.load_progress(BOOK_ID)
    assert preserved is not None
    assert preserved.current_page_id == "pg_tokenizer"
    assert preserved.visited_page_ids == ["pg_pipeline", "pg_tokenizer"]


def test_minimind_preset_refuses_to_replace_unrelated_book(tmp_path: Path) -> None:
    storage = BookStorage(path_service=PathService(workspace_root=tmp_path))
    book, _inputs, _spine, _pages = build_minimind_book()
    book.metadata = {"preset": "another-book"}
    storage.save_book(book)

    with pytest.raises(ValueError, match="non-preset"):
        install_minimind_book(storage)
