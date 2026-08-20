"""Reading progress: position, bookmarks, and derived quiz stats.

These three fields existed on the model from the beginning and were never once
written to, so none of this behaviour had cover.
"""

import pytest

from deeptutor.book import progress as progress_ops
from deeptutor.book.models import Progress, QuizAttempt

PAGE_TO_CHAPTER = {"pg_1": "ch_1", "pg_2": "ch_2"}


def _attempt(question: str, correct: bool | None, *, page="pg_1", ts=1.0) -> QuizAttempt:
    return QuizAttempt(
        block_id="blk_1",
        page_id=page,
        question_id=question,
        user_answer="A",
        is_correct=correct,
        timestamp=ts,
    )


# ── Position ────────────────────────────────────────────────────────────


def test_visiting_a_page_records_position_once() -> None:
    progress = Progress(book_id="bk")

    assert progress_ops.mark_visited(progress, "pg_1") is True
    assert progress.current_page_id == "pg_1"
    assert progress.visited_page_ids == ["pg_1"]

    # Re-reading the same page is not a change worth a disk write.
    assert progress_ops.mark_visited(progress, "pg_1") is False
    assert progress.visited_page_ids == ["pg_1"]


def test_moving_on_updates_position_without_forgetting_history() -> None:
    progress = Progress(book_id="bk")
    progress_ops.mark_visited(progress, "pg_1")
    progress_ops.mark_visited(progress, "pg_2")

    assert progress.current_page_id == "pg_2"
    assert progress.visited_page_ids == ["pg_1", "pg_2"]


def test_bookmarks_toggle() -> None:
    progress = Progress(book_id="bk")
    assert progress_ops.toggle_bookmark(progress, "pg_1") is True
    assert progress.bookmarked_page_ids == ["pg_1"]
    assert progress_ops.toggle_bookmark(progress, "pg_1") is False
    assert progress.bookmarked_page_ids == []


def test_completion_ratio_is_clamped() -> None:
    progress = Progress(book_id="bk", visited_page_ids=["pg_1", "pg_1", "pg_2"])
    assert progress_ops.completion_ratio(progress, 4) == 0.5
    assert progress_ops.completion_ratio(progress, 1) == 1.0
    assert progress_ops.completion_ratio(progress, 0) == 0.0


# ── Derived stats ───────────────────────────────────────────────────────


def test_answering_the_same_question_again_does_not_inflate_the_score() -> None:
    progress = Progress(book_id="bk")
    for ts in (1.0, 2.0, 3.0):
        progress_ops.record_attempt(
            progress,
            page_id="pg_1",
            block_id="blk_1",
            question_id="q1",
            user_answer="A",
            is_correct=True,
            page_to_chapter=PAGE_TO_CHAPTER,
        )
    assert progress.score == 1


def test_getting_it_right_clears_the_weak_chapter() -> None:
    progress = Progress(book_id="bk")
    progress_ops.record_attempt(
        progress,
        page_id="pg_1",
        block_id="blk_1",
        question_id="q1",
        user_answer="B",
        is_correct=False,
        page_to_chapter=PAGE_TO_CHAPTER,
    )
    assert progress.weak_chapters == ["ch_1"]

    progress_ops.record_attempt(
        progress,
        page_id="pg_1",
        block_id="blk_1",
        question_id="q1",
        user_answer="A",
        is_correct=True,
        page_to_chapter=PAGE_TO_CHAPTER,
    )
    assert progress.weak_chapters == [], "a corrected mistake must not brand the chapter"
    assert progress.score == 1


def test_an_ungraded_written_answer_counts_neither_way() -> None:
    progress = Progress(book_id="bk")
    progress_ops.record_attempt(
        progress,
        page_id="pg_1",
        block_id="blk_1",
        question_id="q1",
        user_answer="",
        is_correct=None,
        page_to_chapter=PAGE_TO_CHAPTER,
    )
    assert progress.score == 0
    assert progress.weak_chapters == []


def test_latest_attempt_wins_per_question() -> None:
    progress = Progress(
        book_id="bk",
        quiz_attempts=[
            _attempt("q1", False, ts=1.0),
            _attempt("q1", True, ts=2.0),
            _attempt("q2", True, ts=1.0),
            _attempt("q2", False, ts=2.0, page="pg_2"),
        ],
    )
    assert progress_ops.recompute_score(progress) == 1
    assert progress_ops.recompute_weak_chapters(progress, PAGE_TO_CHAPTER) == ["ch_2"]


def test_learning_activities_are_idempotent_by_event_id() -> None:
    progress = Progress(book_id="bk")
    args = {
        "schema_version": 1,
        "event_id": "event-1",
        "page_id": "pg_1",
        "block_id": "blk_1",
        "objective_ids": ["obj_one"],
        "activity_type": "parameter_change",
        "result": "completed",
        "payload": {"parameter": "amplitude", "value": 2},
        "occurred_at": 1.0,
    }

    assert progress_ops.record_learning_activity(progress, **args) is True
    assert progress_ops.record_learning_activity(progress, **args) is False
    assert len(progress.learning_activities) == 1
    assert progress.learning_activities[0].objective_ids == ["obj_one"]
    assert progress.learning_activities[0].payload == args["payload"]


def test_learning_activity_schema_and_event_id_are_validated() -> None:
    progress = Progress(book_id="bk")
    common = {
        "page_id": "pg_1",
        "block_id": "blk_1",
        "objective_ids": [],
        "activity_type": "interactive_lab",
        "result": "observed",
        "payload": {},
        "occurred_at": 1.0,
    }

    with pytest.raises(ValueError, match="schema"):
        progress_ops.record_learning_activity(
            progress, schema_version=2, event_id="event-1", **common
        )

    with pytest.raises(ValueError, match="event_id"):
        progress_ops.record_learning_activity(progress, schema_version=1, event_id=" ", **common)

    with pytest.raises(ValueError, match="objective id"):
        progress_ops.record_learning_activity(
            progress,
            schema_version=1,
            event_id="event-2",
            **{**common, "objective_ids": ["x" * 129]},
        )


def test_learning_activity_normalizes_ids_and_browser_timestamps() -> None:
    progress = Progress(book_id="bk")
    args = {
        "schema_version": 1,
        "page_id": "pg_1",
        "block_id": "blk_1",
        "objective_ids": [" obj_one ", "obj_one"],
        "activity_type": " parameter_change ",
        "result": "completed",
        "payload": {},
        "occurred_at": 1_760_000_000_000,
    }

    assert progress_ops.record_learning_activity(progress, event_id=" event-1 ", **args) is True
    assert progress_ops.record_learning_activity(progress, event_id="event-1", **args) is False
    activity = progress.learning_activities[0]
    assert activity.event_id == "event-1"
    assert activity.objective_ids == ["obj_one"]
    assert activity.activity_type == "parameter_change"
    assert activity.occurred_at == 1_760_000_000


def test_learning_activity_retains_the_latest_bounded_history() -> None:
    progress = Progress(book_id="bk")
    common = {
        "schema_version": 1,
        "page_id": "pg_1",
        "block_id": "blk_1",
        "objective_ids": [],
        "activity_type": "interactive_lab",
        "result": "observed",
        "payload": {},
        "occurred_at": 1.0,
    }

    for index in range(progress_ops.MAX_LEARNING_ACTIVITIES + 1):
        assert progress_ops.record_learning_activity(progress, event_id=f"event-{index}", **common)

    assert len(progress.learning_activities) == progress_ops.MAX_LEARNING_ACTIVITIES
    assert progress.learning_activities[0].event_id == "event-1"
    assert progress.learning_activities[-1].event_id == "event-500"
