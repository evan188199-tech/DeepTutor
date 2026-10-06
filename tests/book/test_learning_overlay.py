from __future__ import annotations

import json
from pathlib import Path

from deeptutor.book.learning_overlay import BookLearningOverlay
from deeptutor.book.models import LearningCapture, LearningCaptureStatus, Progress
from deeptutor.services.path_service import PathService


def _build_overlay(tmp_path: Path) -> BookLearningOverlay:
    service = PathService(workspace_root=tmp_path / "data")
    return BookLearningOverlay(service)


def _capture(
    book_id: str,
    page_id: str,
    updated_at: float,
    note: str = "",
    status: LearningCaptureStatus = LearningCaptureStatus.CAPTURED,
) -> LearningCapture:
    return LearningCapture(
        book_id=book_id,
        page_id=page_id,
        source_text=f"text-{page_id}",
        content_hash=f"h-{page_id}",
        user_note=note,
        status=status,
        updated_at=updated_at,
    )


# ── assembly ────────────────────────────────────────────────────────────────


def test_book_root_layout(tmp_path: Path) -> None:
    overlay = _build_overlay(tmp_path)
    expected = tmp_path / "data" / "user" / "workspace" / "book_learning" / "book_bk_1"
    assert overlay.book_root("bk_1") == expected


def test_progress_roundtrip(tmp_path: Path) -> None:
    overlay = _build_overlay(tmp_path)
    progress = Progress(book_id="bk_rt", current_page_id="pg_2", score=7)

    overlay.save_progress(progress)

    loaded = overlay.load_progress("bk_rt")
    assert loaded == progress
    assert (overlay.book_root("bk_rt") / "progress.json").exists()


def test_captures_assembly_sorted_desc_with_lookup(tmp_path: Path) -> None:
    overlay = _build_overlay(tmp_path)
    book_id = "bk_sort"
    first = _capture(book_id, "pg_1", updated_at=1)
    second = _capture(book_id, "pg_2", updated_at=5)
    third = _capture(book_id, "pg_3", updated_at=3)

    overlay.upsert_learning_capture(first)
    overlay.upsert_learning_capture(second)
    overlay.upsert_learning_capture(third)

    captures = overlay.load_learning_captures(book_id)
    assert [capture.id for capture in captures] == [second.id, third.id, first.id]

    assert overlay.load_learning_capture(book_id, third.id) == third
    assert overlay.load_learning_capture(book_id, "lc_missing") is None


def test_captures_filter_by_status(tmp_path: Path) -> None:
    overlay = _build_overlay(tmp_path)
    book_id = "bk_filter"
    approved = _capture(book_id, "pg_1", updated_at=1, status=LearningCaptureStatus.APPROVED)
    overlay.upsert_learning_capture(approved)
    rejected = _capture(book_id, "pg_1", updated_at=2, status=LearningCaptureStatus.REJECTED)
    overlay.upsert_learning_capture(rejected)

    assert overlay.load_learning_captures(book_id, status=LearningCaptureStatus.APPROVED) == [
        approved
    ]
    assert overlay.load_learning_captures(book_id, status=LearningCaptureStatus.REJECTED) == [
        rejected
    ]
    assert len(overlay.load_learning_captures(book_id)) == 2


def test_page_chat_session_roundtrip(tmp_path: Path) -> None:
    overlay = _build_overlay(tmp_path)
    book_id = "bk_chat"

    overlay.set_page_chat_session(book_id, "pg_1", "sess_1")
    overlay.set_page_chat_session(book_id, "pg_2", "sess_2")

    assert overlay.load_page_chat_sessions(book_id) == {
        "pg_1": "sess_1",
        "pg_2": "sess_2",
    }


# ── empty state / degradation ───────────────────────────────────────────────


def test_empty_state_defaults(tmp_path: Path) -> None:
    overlay = _build_overlay(tmp_path)

    assert overlay.load_progress("bk_empty") is None
    assert overlay.load_learning_captures("bk_empty") == []
    assert overlay.load_learning_capture("bk_empty", "lc_x") is None
    assert overlay.load_page_chat_sessions("bk_empty") == {}


def test_malformed_files_degrade_to_empty(tmp_path: Path) -> None:
    overlay = _build_overlay(tmp_path)
    book_id = "bk_bad"
    root = overlay.book_root(book_id)
    root.mkdir(parents=True)
    (root / "progress.json").write_text("{not-json", encoding="utf-8")
    (root / "learning_captures.json").write_text("{oops", encoding="utf-8")
    (root / "page_chat_sessions.json").write_text("[oops", encoding="utf-8")

    assert overlay.load_progress(book_id) is None
    assert overlay.load_learning_captures(book_id) == []
    assert overlay.load_page_chat_sessions(book_id) == {}


def test_wrong_payload_shapes_degrade_to_empty(tmp_path: Path) -> None:
    overlay = _build_overlay(tmp_path)
    book_id = "bk_shape"
    root = overlay.book_root(book_id)
    root.mkdir(parents=True)
    (root / "progress.json").write_text('["not", "an", "object"]', encoding="utf-8")
    (root / "learning_captures.json").write_text('{"a": 1}', encoding="utf-8")
    (root / "page_chat_sessions.json").write_text('["a", "b"]', encoding="utf-8")

    assert overlay.load_progress(book_id) is None
    assert overlay.load_learning_captures(book_id) == []
    assert overlay.load_page_chat_sessions(book_id) == {}


def test_invalid_progress_payload_returns_none(tmp_path: Path) -> None:
    overlay = _build_overlay(tmp_path)
    book_id = "bk_progress_bad"
    root = overlay.book_root(book_id)
    root.mkdir(parents=True)
    (root / "progress.json").write_text('{"score": 1}', encoding="utf-8")

    assert overlay.load_progress(book_id) is None


def test_invalid_capture_entries_skipped(tmp_path: Path) -> None:
    overlay = _build_overlay(tmp_path)
    book_id = "bk_skip"
    valid = _capture(book_id, "pg_1", updated_at=2)
    payload = [
        valid.model_dump(mode="json"),
        {"id": "lc_bad", "book_id": book_id},
    ]
    root = overlay.book_root(book_id)
    root.mkdir(parents=True)
    (root / "learning_captures.json").write_text(json.dumps(payload), encoding="utf-8")

    assert overlay.load_learning_captures(book_id) == [valid]


def test_page_chat_blank_entries_filtered(tmp_path: Path) -> None:
    overlay = _build_overlay(tmp_path)
    book_id = "bk_blank"
    root = overlay.book_root(book_id)
    root.mkdir(parents=True)
    (root / "page_chat_sessions.json").write_text(
        json.dumps({"pg_1": "sess_1", "  ": "sess_2", "pg_2": "  "}),
        encoding="utf-8",
    )

    assert overlay.load_page_chat_sessions(book_id) == {"pg_1": "sess_1"}


# ── overwrite update semantics ──────────────────────────────────────────────


def test_upsert_replaces_existing_capture(tmp_path: Path) -> None:
    overlay = _build_overlay(tmp_path)
    book_id = "bk_upsert"
    original = _capture(book_id, "pg_1", updated_at=1)
    overlay.upsert_learning_capture(original)

    replacement = _capture(book_id, "pg_1", updated_at=9, note="edited")
    replacement.id = original.id
    overlay.upsert_learning_capture(replacement)

    captures = overlay.load_learning_captures(book_id)
    assert len(captures) == 1
    assert captures[0].id == original.id
    assert captures[0].user_note == "edited"
    assert captures[0].updated_at == 9


def test_upsert_reorders_after_replacement(tmp_path: Path) -> None:
    overlay = _build_overlay(tmp_path)
    book_id = "bk_reorder"
    older = _capture(book_id, "pg_1", updated_at=1)
    newer = _capture(book_id, "pg_2", updated_at=5)
    overlay.upsert_learning_capture(older)
    overlay.upsert_learning_capture(newer)

    refreshed = _capture(book_id, "pg_1", updated_at=10)
    refreshed.id = older.id
    overlay.upsert_learning_capture(refreshed)

    assert [capture.id for capture in overlay.load_learning_captures(book_id)] == [
        refreshed.id,
        newer.id,
    ]


def test_save_progress_overwrites_previous(tmp_path: Path) -> None:
    overlay = _build_overlay(tmp_path)
    book_id = "bk_progress_overwrite"

    overlay.save_progress(Progress(book_id=book_id, current_page_id="pg_1", score=1))
    overlay.save_progress(Progress(book_id=book_id, current_page_id="pg_2", score=42))

    loaded = overlay.load_progress(book_id)
    assert loaded is not None
    assert loaded.current_page_id == "pg_2"
    assert loaded.score == 42


def test_set_page_chat_session_overwrites_same_page(tmp_path: Path) -> None:
    overlay = _build_overlay(tmp_path)
    book_id = "bk_chat_overwrite"

    overlay.set_page_chat_session(book_id, "pg_1", "sess_old")
    overlay.set_page_chat_session(book_id, "pg_1", "sess_new")

    assert overlay.load_page_chat_sessions(book_id) == {"pg_1": "sess_new"}
