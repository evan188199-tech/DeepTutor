"""Read-only learning journal overview API (#1407).

Serves the journal snapshot the learner's tutor carries across sessions —
current mission, last-session handoff, and the confirmed records — so the
Learning Space panel shows exactly the state the turn executor would inject.
The journal itself is written only from conversation via the ``learning_update``
tool shipped with the journal data layer; this router never writes, so the
panel can never drift the stored state.

The file contract is the one the journal data layer owns:
``<workspace_root>/learning_journal/journal.json`` (see #740 / PR #1226). This
module deliberately does not import that layer — it ships separately, and the
panel must stay readable whether or not it has landed — so the parsing here
mirrors its tolerance: missing, unreadable, or malformed files degrade to an
empty journal instead of erroring, and records without an id or without any
title/insight text are dropped rather than failing the read.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)
router = APIRouter()

JOURNAL_VERSION = 1


class LearningMissionView(BaseModel):
    """Why the learner is studying — shown as-is from the store."""

    topic: str = ""
    why: str = ""
    level: str = ""
    updated_at: str = ""


class LearningSessionView(BaseModel):
    """Handoff between sessions: what happened and what to do next."""

    summary: str = ""
    next_focus: str = ""
    updated_at: str = ""


class LearningRecordView(BaseModel):
    """One durable insight that shapes the next lesson."""

    id: str
    title: str = ""
    insight: str = ""
    created_at: str = ""


class LearningJournalResponse(BaseModel):
    """The full read-only snapshot; empty fields mean "not set"."""

    version: int = JOURNAL_VERSION
    updated_at: str = ""
    mission: LearningMissionView = Field(default_factory=LearningMissionView)
    last_session: LearningSessionView = Field(default_factory=LearningSessionView)
    records: list[LearningRecordView] = Field(default_factory=list)
    is_empty: bool = True


def _learning_journal_file() -> Path:
    """Resolve the journal file per request so per-user scoping applies."""

    return get_path_service().workspace_root / "learning_journal" / "journal.json"


def _text(raw: dict[str, Any], key: str) -> str:
    return str(raw.get(key) or "").strip()


def _empty_response() -> LearningJournalResponse:
    return LearningJournalResponse()


def _parse_journal(raw: Any) -> LearningJournalResponse:
    if not isinstance(raw, dict):
        return _empty_response()

    mission_raw = raw.get("mission")
    mission = (
        LearningMissionView(
            topic=_text(mission_raw, "topic"),
            why=_text(mission_raw, "why"),
            level=_text(mission_raw, "level"),
            updated_at=_text(mission_raw, "updated_at"),
        )
        if isinstance(mission_raw, dict)
        else LearningMissionView()
    )

    session_raw = raw.get("last_session")
    last_session = (
        LearningSessionView(
            summary=_text(session_raw, "summary"),
            next_focus=_text(session_raw, "next_focus"),
            updated_at=_text(session_raw, "updated_at"),
        )
        if isinstance(session_raw, dict)
        else LearningSessionView()
    )

    records: list[LearningRecordView] = []
    for item in raw.get("records") or []:
        if not isinstance(item, dict):
            continue
        record_id = _text(item, "id")
        title = _text(item, "title")
        insight = _text(item, "insight")
        if not record_id or not (title or insight):
            continue
        records.append(
            LearningRecordView(
                id=record_id,
                title=title,
                insight=insight,
                created_at=_text(item, "created_at"),
            )
        )

    is_empty = (
        not (mission.topic or mission.why or mission.level)
        and not (last_session.summary or last_session.next_focus)
        and not records
    )
    return LearningJournalResponse(
        version=JOURNAL_VERSION,
        updated_at=_text(raw, "updated_at"),
        mission=mission,
        last_session=last_session,
        records=records,
        is_empty=is_empty,
    )


@router.get("", response_model=LearningJournalResponse)
async def get_learning_journal() -> LearningJournalResponse:
    """Return the learner's journal snapshot, or an empty journal."""

    path = _learning_journal_file()
    if not path.exists():
        return _empty_response()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning("learning journal unreadable at %s: %s", path, exc)
        return _empty_response()
    return _parse_journal(raw)
