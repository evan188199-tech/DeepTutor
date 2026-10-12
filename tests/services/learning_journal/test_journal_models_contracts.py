from __future__ import annotations

import pytest

from deeptutor.services.learning_journal.models import (
    LearningJournal,
    LearningMission,
    LearningRecord,
    LearningSessionNote,
)


def test_mission_is_empty_when_every_field_is_blank() -> None:
    assert LearningMission().is_empty()
    assert LearningMission(topic="  ").is_empty()
    assert LearningMission(why="  ", level="  ").is_empty()
    assert LearningMission(topic=" ", why=" ", level=" ").is_empty()
    assert not LearningMission(topic="t").is_empty()
    assert not LearningMission(why="w").is_empty()
    assert not LearningMission(level="beginner").is_empty()


def test_mission_from_dict_coerces_and_strips_values() -> None:
    mission = LearningMission.from_dict(
        {"topic": "  RL  ", "why": 42, "level": None, "updated_at": "2026-01-02T03:04:05Z"}
    )
    assert mission.topic == "RL"
    assert mission.why == "42"
    assert mission.level == ""
    assert mission.updated_at == "2026-01-02T03:04:05Z"


def test_mission_from_dict_rejects_non_mapping_and_missing_keys() -> None:
    assert LearningMission.from_dict(None) == LearningMission()
    assert LearningMission.from_dict(["topic"]) == LearningMission()
    assert LearningMission.from_dict({}) == LearningMission()


def test_mission_to_dict_returns_every_field() -> None:
    mission = LearningMission(topic="t", why="w", level="l", updated_at="u")
    assert mission.to_dict() == {"topic": "t", "why": "w", "level": "l", "updated_at": "u"}


def test_session_note_is_empty_ignores_updated_at() -> None:
    assert LearningSessionNote().is_empty()
    assert LearningSessionNote(updated_at="2026-01-01T00:00:00Z").is_empty()
    assert not LearningSessionNote(next_focus="derivatives").is_empty()


def test_session_note_round_trip_preserves_content() -> None:
    note = LearningSessionNote(summary="did X", next_focus="do Y", updated_at="u1")
    assert LearningSessionNote.from_dict(note.to_dict()) == note


def test_record_from_dict_requires_id_and_some_content() -> None:
    assert LearningRecord.from_dict({"id": "r1", "title": "T", "insight": "I"}) == LearningRecord(
        id="r1", title="T", insight="I"
    )
    assert LearningRecord.from_dict({"id": "r1", "title": "T"}) == LearningRecord(
        id="r1", title="T", insight=""
    )
    assert LearningRecord.from_dict({"id": "r1", "insight": "I"}) == LearningRecord(
        id="r1", title="", insight="I"
    )
    assert LearningRecord.from_dict({"id": "", "title": "T"}) is None
    assert LearningRecord.from_dict({"title": "T"}) is None
    assert LearningRecord.from_dict({"id": "r1"}) is None
    assert LearningRecord.from_dict({"id": "  ", "insight": "I"}) is None
    assert LearningRecord.from_dict("not a dict") is None
    assert LearningRecord.from_dict(None) is None


def test_record_from_dict_strips_fields() -> None:
    record = LearningRecord.from_dict({"id": " r1 ", "title": " T ", "insight": " I "})
    assert record == LearningRecord(id="r1", title="T", insight="I")


def test_journal_defaults_are_empty() -> None:
    journal = LearningJournal()
    assert journal.is_empty()
    assert journal.version == 1
    assert journal.records == []
    assert isinstance(journal.mission, LearningMission)
    assert isinstance(journal.last_session, LearningSessionNote)


def test_journal_is_empty_false_when_any_part_is_present() -> None:
    mission_only = LearningJournal(mission=LearningMission(topic="t"))
    session_only = LearningJournal(last_session=LearningSessionNote(summary="s"))
    record_only = LearningJournal(records=[LearningRecord(id="r", title="T", insight="I")])
    assert not mission_only.is_empty()
    assert not session_only.is_empty()
    assert not record_only.is_empty()


def test_journal_from_dict_drops_invalid_records_and_keeps_valid_ones() -> None:
    journal = LearningJournal.from_dict(
        {
            "version": 2,
            "updated_at": " 2026-05-06T07:08:09Z ",
            "mission": {"topic": "graph theory"},
            "last_session": {"summary": " Euler paths "},
            "records": [
                {"id": "r1", "title": "valid", "insight": "kept"},
                {"id": "", "title": "no id", "insight": "dropped"},
                "not a dict",
                None,
                {"id": "r2", "insight": "kept too"},
            ],
        }
    )
    assert journal.version == 2
    assert journal.updated_at == "2026-05-06T07:08:09Z"
    assert journal.mission == LearningMission(topic="graph theory")
    assert journal.last_session == LearningSessionNote(summary="Euler paths")
    assert journal.records == [
        LearningRecord(id="r1", title="valid", insight="kept"),
        LearningRecord(id="r2", title="", insight="kept too"),
    ]


def test_journal_from_dict_defaults_version_and_records() -> None:
    journal = LearningJournal.from_dict({"version": 2})
    assert journal.version == 2
    assert journal.records == []
    assert LearningJournal.from_dict({}) == LearningJournal()
    assert LearningJournal.from_dict({"records": None}) == LearningJournal()
    assert LearningJournal.from_dict(None) == LearningJournal()
    assert LearningJournal.from_dict(42) == LearningJournal()


def test_journal_from_dict_rejects_a_non_numeric_version() -> None:
    with pytest.raises(ValueError):
        LearningJournal.from_dict({"version": "not-an-int"})


def test_journal_to_dict_round_trip_is_lossless() -> None:
    journal = LearningJournal(
        version=3,
        updated_at="u",
        mission=LearningMission(topic="t", why="w", level="l"),
        last_session=LearningSessionNote(summary="s", next_focus="n"),
        records=[LearningRecord(id="r1", title="T", insight="I", created_at="c")],
    )
    assert LearningJournal.from_dict(journal.to_dict()) == journal
