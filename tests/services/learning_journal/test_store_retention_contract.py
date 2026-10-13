"""Retention contract tests for the learning journal store.

Locks the storage-bound behavior the retention audit measured: the FIFO
record cap, the single-slot overwrite semantics of mission and
last_session, the file-size bound once the cap is reached, and the
distinct rejection branches for corrupted journal files.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.services.learning_journal.store import (
    MAX_INSIGHT_CHARS,
    MAX_LEVEL_CHARS,
    MAX_NEXT_FOCUS_CHARS,
    MAX_RECORDS,
    MAX_SUMMARY_CHARS,
    MAX_TOPIC_CHARS,
    MAX_WHY_CHARS,
    LearningJournalStore,
)
from deeptutor.services.path_service import PathService

MAX_JOURNAL_BYTES = 64 * 1024


@pytest.fixture()
def journal_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LearningJournalStore:
    service = PathService(workspace_root=tmp_path / "data")
    monkeypatch.setattr(
        "deeptutor.services.learning_journal.store.get_path_service",
        lambda: service,
    )
    return LearningJournalStore()


def _fill_records(store: LearningJournalStore, count: int, *, offset: int = 0) -> None:
    for n in range(offset, offset + count):
        result = store.add_record(title=f"title-{n:03d}", insight=f"insight-{n:03d}")
        assert result.accepted


def test_record_cap_admits_exactly_max_records(journal_store: LearningJournalStore) -> None:
    _fill_records(journal_store, MAX_RECORDS)
    records = journal_store.load().records
    assert [record.id for record in records] == [f"lr_{n:04d}" for n in range(1, MAX_RECORDS + 1)]


def test_51st_record_evicts_the_oldest_fifo(journal_store: LearningJournalStore) -> None:
    _fill_records(journal_store, MAX_RECORDS)
    result = journal_store.add_record(title="title-51", insight="insight-51")
    assert result.accepted
    assert result.record_id == f"lr_{MAX_RECORDS + 1:04d}"

    records = journal_store.load().records
    assert len(records) == MAX_RECORDS
    assert [record.id for record in records] == [f"lr_{n:04d}" for n in range(2, MAX_RECORDS + 2)]
    assert records[0].title == "title-001"
    assert records[-1].title == "title-51"
    raw = journal_store.journal_path().read_text(encoding="utf-8")
    assert "title-000" not in raw


def test_mission_slot_is_overwritten(journal_store: LearningJournalStore) -> None:
    first = journal_store.set_mission(topic="topic-one", why="why-one", level="level-one")
    assert first.accepted
    second = journal_store.set_mission(topic="topic-two", why="why-two", level="level-two")
    assert second.accepted

    journal = journal_store.load()
    assert journal.mission.topic == "topic-two"
    assert journal.mission.why == "why-two"
    assert journal.mission.level == "level-two"
    assert not journal.records
    raw = journal_store.journal_path().read_text(encoding="utf-8")
    assert "topic-one" not in raw
    assert "why-one" not in raw
    assert "level-one" not in raw


def test_last_session_slot_is_overwritten(journal_store: LearningJournalStore) -> None:
    journal_store.note_session(summary="summary-one", next_focus="focus-one")
    journal_store.note_session(summary="summary-two", next_focus="focus-two")

    journal = journal_store.load()
    assert journal.last_session.summary == "summary-two"
    assert journal.last_session.next_focus == "focus-two"
    raw = journal_store.journal_path().read_text(encoding="utf-8")
    assert "summary-one" not in raw
    assert "focus-one" not in raw


def test_repeated_single_slot_writes_keep_file_size_constant(
    journal_store: LearningJournalStore,
) -> None:
    path = journal_store.journal_path()
    journal_store.set_mission(topic="T" * (MAX_TOPIC_CHARS * 2))
    journal_store.note_session(summary="S" * (MAX_SUMMARY_CHARS * 2))
    first_size = path.stat().st_size

    for _ in range(5):
        journal_store.set_mission(topic="T" * (MAX_TOPIC_CHARS * 2))
        journal_store.note_session(summary="S" * (MAX_SUMMARY_CHARS * 2))

    journal = journal_store.load()
    assert journal.mission.topic == "T" * (MAX_TOPIC_CHARS - 1) + "…"
    assert len(journal.mission.topic) == MAX_TOPIC_CHARS
    assert len(journal.last_session.summary) == MAX_SUMMARY_CHARS
    assert path.stat().st_size == first_size
    assert path.stat().st_size <= MAX_JOURNAL_BYTES


def test_file_size_is_bounded_at_the_record_cap(journal_store: LearningJournalStore) -> None:
    path = journal_store.journal_path()
    journal_store.set_mission(
        topic="T" * (MAX_TOPIC_CHARS * 2),
        why="W" * (MAX_WHY_CHARS * 2),
        level="L" * (MAX_LEVEL_CHARS * 2),
    )
    journal_store.note_session(
        summary="S" * (MAX_SUMMARY_CHARS * 2),
        next_focus="F" * (MAX_NEXT_FOCUS_CHARS * 2),
    )
    _fill_records(journal_store, MAX_RECORDS, offset=1)
    at_cap_size = path.stat().st_size

    _fill_records(journal_store, 10, offset=MAX_RECORDS + 1)

    records = journal_store.load().records
    assert len(records) == MAX_RECORDS
    assert records[-1].id == f"lr_{MAX_RECORDS + 10:04d}"
    assert path.stat().st_size == at_cap_size
    assert path.stat().st_size <= MAX_JOURNAL_BYTES


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("[1, 2, 3]", "Invalid or unsupported learning journal"),
        ('{"version": 2, "records": []}', "Invalid or unsupported learning journal"),
        ('{"records": {"lr_0001": {}}}', "Invalid learning journal records"),
        ('{"mission": "signals"}', "Invalid learning journal mission"),
        ('{"last_session": []}', "Invalid learning journal last_session"),
        ('{"records": [{"id": "lr_0001", "title": "", "insight": ""}]}', "Invalid learning record"),
    ],
)
def test_each_corrupt_shape_reports_its_own_branch(
    journal_store: LearningJournalStore, content: str, message: str
) -> None:
    path = journal_store.journal_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        journal_store.load()
    with pytest.raises(ValueError, match=message):
        journal_store.add_record(title="t", insight="i")
    assert path.read_text(encoding="utf-8") == content


def test_oversized_insight_clips_and_still_counts_toward_cap(
    journal_store: LearningJournalStore,
) -> None:
    result = journal_store.add_record(title="clip", insight="x" * (MAX_INSIGHT_CHARS * 3))
    assert result.accepted
    journal = journal_store.load()
    assert len(journal.records) == 1
    assert len(journal.records[0].insight) == MAX_INSIGHT_CHARS
    assert journal.records[0].insight.endswith("…")
