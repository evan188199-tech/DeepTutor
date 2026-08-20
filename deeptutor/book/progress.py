"""
Reading progress
================

Where the reader is in a book, what they have bookmarked, and how they did on
its quizzes.

Pure functions over a :class:`Progress` value — no storage, no engine, no IO.
Two reasons:

- The engine stays a scheduler. Progress is a different concern with different
  rules, and mixing them is what left ``visited_page_ids`` and
  ``bookmarked_page_ids`` declared but never written for the whole life of the
  feature.
- Immersive reading tracks the same three things (position, bookmarks,
  comprehension checks) in its own silo. When those merge, this is the layer
  that generalises, and it can be tested without a filesystem.

Derived, not accumulated
------------------------

``score`` and ``weak_chapters`` are recomputed from the **latest** attempt per
question rather than incremented as attempts arrive. Accumulating meant
re-answering a question you already knew inflated your score, and a chapter
stayed "weak" forever once you had missed anything in it — a progress display
that only ever ratchets one way tells the reader nothing.
"""

from __future__ import annotations

import json
import math
from typing import Any

from .models import LearningActivity, Progress, QuizAttempt

LEARNING_ACTIVITY_SCHEMA_VERSION = 1
MAX_LEARNING_ACTIVITIES = 500
MAX_LEARNING_ACTIVITY_EVENT_ID_LENGTH = 128
MAX_LEARNING_ACTIVITY_OBJECTIVES = 12
MAX_LEARNING_ACTIVITY_OBJECTIVE_ID_LENGTH = 128
MAX_LEARNING_ACTIVITY_TYPE_LENGTH = 64
MAX_LEARNING_ACTIVITY_PAYLOAD_BYTES = 8 * 1024
LEARNING_ACTIVITY_RESULTS = frozenset({"observed", "completed", "struggled", "mastered"})


def learning_activity_payload_size(payload: dict[str, Any]) -> int:
    """Return the compact JSON payload size in UTF-8 bytes."""
    try:
        encoded = json.dumps(
            payload,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (RecursionError, TypeError, ValueError) as exc:
        raise ValueError("learning activity payload must be JSON serializable") from exc
    return len(encoded)


def normalize_learning_objective_ids(objective_ids: list[str]) -> list[str]:
    """Trim and de-duplicate objective ids while preserving their order."""
    if len(objective_ids) > MAX_LEARNING_ACTIVITY_OBJECTIVES:
        raise ValueError("learning activity contains too many objective ids")
    normalized: list[str] = []
    for objective_id in objective_ids:
        clean_id = objective_id.strip()
        if len(clean_id) > MAX_LEARNING_ACTIVITY_OBJECTIVE_ID_LENGTH:
            raise ValueError("learning activity objective id is too long")
        if clean_id and clean_id not in normalized:
            normalized.append(clean_id)
    return normalized


def _question_key(attempt: QuizAttempt) -> tuple[str, str]:
    return (attempt.block_id, attempt.question_id)


def latest_attempts(progress: Progress) -> dict[tuple[str, str], QuizAttempt]:
    """The most recent attempt per question, keyed by (block, question)."""
    latest: dict[tuple[str, str], QuizAttempt] = {}
    for attempt in progress.quiz_attempts:
        key = _question_key(attempt)
        current = latest.get(key)
        if current is None or attempt.timestamp >= current.timestamp:
            latest[key] = attempt
    return latest


def recompute_score(progress: Progress) -> int:
    """Number of distinct questions currently answered correctly."""
    return sum(1 for a in latest_attempts(progress).values() if a.is_correct is True)


def recompute_weak_chapters(progress: Progress, page_to_chapter: dict[str, str]) -> list[str]:
    """Chapters holding at least one question whose latest answer was wrong.

    A chapter drops off this list as soon as the reader gets its questions
    right — being wrong once should not brand a chapter permanently.
    """
    weak: set[str] = set()
    for attempt in latest_attempts(progress).values():
        if attempt.is_correct is not False:
            continue
        chapter_id = page_to_chapter.get(attempt.page_id, "")
        if chapter_id:
            weak.add(chapter_id)
    return sorted(weak)


def record_attempt(
    progress: Progress,
    *,
    page_id: str,
    block_id: str,
    question_id: str,
    user_answer: str,
    is_correct: bool | None,
    page_to_chapter: dict[str, str],
) -> Progress:
    """Append an attempt and refresh everything derived from the set."""
    progress.quiz_attempts.append(
        QuizAttempt(
            block_id=block_id,
            page_id=page_id,
            question_id=question_id,
            user_answer=user_answer,
            is_correct=is_correct,
        )
    )
    progress.score = recompute_score(progress)
    progress.weak_chapters = recompute_weak_chapters(progress, page_to_chapter)
    return progress


def record_learning_activity(
    progress: Progress,
    *,
    schema_version: int,
    event_id: str,
    page_id: str,
    block_id: str,
    objective_ids: list[str],
    activity_type: str,
    result: str,
    payload: dict[str, Any],
    occurred_at: float,
) -> bool:
    """Validate and append one idempotent, size-bounded activity event."""
    if schema_version != LEARNING_ACTIVITY_SCHEMA_VERSION:
        raise ValueError("unsupported learning activity schema version")
    clean_event_id = event_id.strip()
    if not clean_event_id:
        raise ValueError("learning activity event_id is required")
    if len(clean_event_id) > MAX_LEARNING_ACTIVITY_EVENT_ID_LENGTH:
        raise ValueError("learning activity event_id is too long")
    if any(activity.event_id == clean_event_id for activity in progress.learning_activities):
        return False

    clean_objective_ids = normalize_learning_objective_ids(objective_ids)
    clean_activity_type = activity_type.strip()
    if not clean_activity_type:
        raise ValueError("learning activity activity_type is required")
    if len(clean_activity_type) > MAX_LEARNING_ACTIVITY_TYPE_LENGTH:
        raise ValueError("learning activity activity_type is too long")
    if result not in LEARNING_ACTIVITY_RESULTS:
        raise ValueError("learning activity result is invalid")
    if learning_activity_payload_size(payload) > MAX_LEARNING_ACTIVITY_PAYLOAD_BYTES:
        raise ValueError("learning activity payload is too large")

    clean_occurred_at = float(occurred_at)
    if not math.isfinite(clean_occurred_at) or clean_occurred_at < 0:
        raise ValueError("learning activity occurred_at is invalid")
    # Browser timestamps conventionally use milliseconds. Progress timestamps
    # use Unix seconds, so accept either at the boundary and persist one unit.
    if clean_occurred_at >= 100_000_000_000:
        clean_occurred_at /= 1000

    progress.learning_activities.append(
        LearningActivity(
            schema_version=schema_version,
            event_id=clean_event_id,
            block_id=block_id,
            page_id=page_id,
            objective_ids=clean_objective_ids,
            activity_type=clean_activity_type,
            result=result,
            payload=payload,
            occurred_at=clean_occurred_at,
        )
    )
    if len(progress.learning_activities) > MAX_LEARNING_ACTIVITIES:
        del progress.learning_activities[:-MAX_LEARNING_ACTIVITIES]
    progress.updated_at = max(progress.updated_at, progress.learning_activities[-1].recorded_at)
    return True


def mark_visited(progress: Progress, page_id: str) -> bool:
    """Record that the reader opened *page_id*. True when anything changed.

    The caller uses the return value to skip a disk write on the common case:
    re-reading a page you have already seen.
    """
    changed = False
    if progress.current_page_id != page_id:
        progress.current_page_id = page_id
        changed = True
    if page_id not in progress.visited_page_ids:
        progress.visited_page_ids.append(page_id)
        changed = True
    return changed


def toggle_bookmark(progress: Progress, page_id: str) -> bool:
    """Flip *page_id*'s bookmark. Returns whether it is bookmarked now."""
    if page_id in progress.bookmarked_page_ids:
        progress.bookmarked_page_ids.remove(page_id)
        return False
    progress.bookmarked_page_ids.append(page_id)
    return True


def completion_ratio(progress: Progress, total_pages: int) -> float:
    """Fraction of the book visited, clamped to [0, 1]."""
    if total_pages <= 0:
        return 0.0
    seen = len({p for p in progress.visited_page_ids})
    return min(1.0, seen / total_pages)


__all__ = [
    "latest_attempts",
    "recompute_score",
    "recompute_weak_chapters",
    "record_attempt",
    "record_learning_activity",
    "learning_activity_payload_size",
    "normalize_learning_objective_ids",
    "mark_visited",
    "toggle_bookmark",
    "completion_ratio",
]
