"""Persist generated quiz questions into the notebook (question bank).

The quiz a chat turn generates used to live only in the streamed result
event: unless the learner answered in QuizViewer (a client-side,
best-effort upsert), the question never reached the question bank and
even wrong answers could stay invisible on the Dashboard (#575).

Generation-time persistence closes that gap: every generated question is
upserted immediately as an ``ungraded`` notebook entry keyed by
``(conversation, session_id, turn_id, question_id)`` — the exact identity
QuizViewer's per-question upserts use — so a later answer flips the same
row to correct/incorrect instead of duplicating it, and an incorrect
answer makes the practice triggers mark it as a mistake.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from deeptutor.core.context import UnifiedContext

if TYPE_CHECKING:
    from deeptutor.agents.question.pipeline import QuizPair

logger = logging.getLogger(__name__)


def _notebook_items(turn_id: str, qa_pairs: list[QuizPair]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for qa in qa_pairs:
        if not (qa.question_id or "").strip() or not (qa.question or "").strip():
            continue
        items.append(
            {
                "turn_id": turn_id,
                "question_id": qa.question_id,
                "question": qa.question,
                "question_type": qa.question_type,
                "options": qa.options or {},
                "correct_answer": qa.correct_answer,
                "explanation": qa.explanation,
                "difficulty": qa.difficulty,
                # Unanswered marker: the history loader and the bank stats
                # both treat empty ``user_answer`` + ``ungraded`` as "not
                # attempted yet" rather than "wrong".
                "user_answer": "",
                "result": "ungraded",
                "is_correct": False,
                "source": "deep_question",
            }
        )
    return items


async def persist_generated_quiz(context: UnifiedContext, qa_pairs: list[QuizPair]) -> int:
    """Upsert ``qa_pairs`` as ungraded notebook entries. Best-effort.

    Returns the number of persisted entries. Failures are logged and
    swallowed — the learner already received the quiz, so a persistence
    problem must never fail the turn that produced it.
    """
    session_id = str(getattr(context, "session_id", "") or "").strip()
    turn_id = str((getattr(context, "metadata", None) or {}).get("turn_id") or "").strip()
    if not session_id or not turn_id:
        # Without turn identity the write would land in the shared legacy
        # namespace where the next quiz's identically numbered questions
        # would pick it up as their own answers (#677).
        return 0
    items = _notebook_items(turn_id, qa_pairs)
    if not items:
        return 0
    try:
        from deeptutor.services.session.sqlite_store import get_sqlite_session_store

        count = await get_sqlite_session_store().upsert_notebook_entries(session_id, items)
    except Exception:
        logger.warning(
            "Failed to persist generated quiz to the question bank "
            "(session=%s turn=%s questions=%d)",
            session_id,
            turn_id,
            len(items),
            exc_info=True,
        )
        return 0
    if count:
        logger.info(
            "Persisted %d generated questions to the question bank (session=%s turn=%s)",
            count,
            session_id,
            turn_id,
        )
    return count


__all__ = ["persist_generated_quiz"]
