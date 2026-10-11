"""Measure the theoretical worst-case size of one per-user learning journal.

Offline and deterministic: builds a LearningJournal with MAX_RECORDS records
at the store's clip limits (models + store constants only, no I/O side
effects outside this directory's bounds.json), serializes exactly the way
atomic_write_json does (indent=2, ensure_ascii=False, trailing newline), and
reports bytes. Evidence only; no source changes.
"""

from __future__ import annotations

import json
from pathlib import Path

from deeptutor.services.learning_journal.models import (
    LearningJournal,
    LearningMission,
    LearningRecord,
    LearningSessionNote,
)
from deeptutor.services.learning_journal.store import (
    MAX_INSIGHT_CHARS,
    MAX_LEVEL_CHARS,
    MAX_NEXT_FOCUS_CHARS,
    MAX_RECORDS,
    MAX_SUMMARY_CHARS,
    MAX_TITLE_CHARS,
    MAX_TOPIC_CHARS,
    MAX_WHY_CHARS,
)


def _fill(char: str, limit: int) -> str:
    return (char * limit)[:limit]


def build_max_journal() -> LearningJournal:
    journal = LearningJournal(version=1, updated_at="2026-10-11T00:00:00Z")
    journal.mission = LearningMission(
        topic=_fill("t", MAX_TOPIC_CHARS),
        why=_fill("w", MAX_WHY_CHARS),
        level=_fill("l", MAX_LEVEL_CHARS),
        updated_at=journal.updated_at,
    )
    journal.last_session = LearningSessionNote(
        summary=_fill("s", MAX_SUMMARY_CHARS),
        next_focus=_fill("f", MAX_NEXT_FOCUS_CHARS),
        updated_at=journal.updated_at,
    )
    for n in range(1, MAX_RECORDS + 1):
        journal.records.append(
            LearningRecord(
                id=f"lr_{n:04d}",
                title=_fill("T", MAX_TITLE_CHARS),
                insight=_fill("i", MAX_INSIGHT_CHARS),
                created_at=journal.updated_at,
            )
        )
    return journal


def serialize(journal: LearningJournal) -> str:
    # Mirrors atomic_write_json (deeptutor/services/file_io.py:85-86).
    return json.dumps(journal.to_dict(), indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    journal = build_max_journal()
    payload = serialize(journal)
    per_record = [
        len(serialize(LearningJournal(version=1, records=[record]))) - len(
            serialize(LearningJournal(version=1))
        )
        for record in journal.records[:1]
    ]
    bounds = {
        "max_records": MAX_RECORDS,
        "clip_limits": {
            "topic": MAX_TOPIC_CHARS,
            "why": MAX_WHY_CHARS,
            "level": MAX_LEVEL_CHARS,
            "summary": MAX_SUMMARY_CHARS,
            "next_focus": MAX_NEXT_FOCUS_CHARS,
            "title": MAX_TITLE_CHARS,
            "insight": MAX_INSIGHT_CHARS,
        },
        "worst_case_journal_json_bytes": len(payload.encode("utf-8")),
        "worst_case_record_bytes_each": per_record[0],
        "mission_session_bytes": len(payload.encode("utf-8"))
        - MAX_RECORDS * per_record[0],
        "lock_file_bytes": 1,
        "growth_model": (
            "per-user bounded ~worst_case_journal_json_bytes; "
            "aggregate = users x worst_case_journal_json_bytes (linear in users, "
            "constant per user)"
        ),
    }
    out = Path(__file__).parent / "bounds.json"
    out.write_text(json.dumps(bounds, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(bounds, indent=2))


if __name__ == "__main__":
    main()
