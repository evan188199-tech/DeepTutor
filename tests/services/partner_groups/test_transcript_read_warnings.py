"""Read-failure warnings in Partner Group transcript and whiteboard stores."""

from __future__ import annotations

import json
import logging
from uuid import uuid4

from deeptutor.services.partner_groups.memory import WhiteboardMemory
from deeptutor.services.partner_groups.models import GroupMessage, utc_now
from deeptutor.services.partner_groups.store import GroupTranscriptStore

_STORE_LOGGER = "deeptutor.services.partner_groups.store"
_MEMORY_LOGGER = "deeptutor.services.partner_groups.memory"


def _message(content: str, session_key: str = "pg-session") -> GroupMessage:
    return GroupMessage(
        event_id=uuid4().hex,
        turn_id=uuid4().hex,
        session_key=session_key,
        role="user",
        content=content,
        author_id="test-admin",
        author_name="test-admin",
        created_at=utc_now(),
    )


def test_transcript_read_warns_and_skips_corrupt_lines(tmp_path, caplog) -> None:
    transcript = GroupTranscriptStore(tmp_path)
    transcript.append(_message("first"))
    transcript.append(_message("second"))
    with transcript._path("pg-session").open("a", encoding="utf-8") as handle:
        handle.write("{not valid json\n")

    with caplog.at_level(logging.WARNING, logger=_STORE_LOGGER):
        rows = transcript.messages("pg-session")

    assert [row.content for row in rows] == ["first", "second"]
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "pg-session" in warnings[0].getMessage()


def test_transcript_read_warns_on_unreadable_file(tmp_path, caplog) -> None:
    transcript = GroupTranscriptStore(tmp_path)
    # A directory where the JSONL file belongs makes every open() fail.
    transcript.directory.mkdir(parents=True, exist_ok=True)
    transcript._path("pg-session").mkdir()

    with caplog.at_level(logging.WARNING, logger=_STORE_LOGGER):
        rows = transcript.messages("pg-session")

    assert rows == []
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "pg-session" in warnings[0].getMessage()


def test_whiteboard_entries_warn_and_skip_corrupt_lines(tmp_path, caplog) -> None:
    whiteboard = WhiteboardMemory(group_dir=tmp_path)
    message = _message("public insight")
    whiteboard.pin(message, pinned_at=utc_now())
    with whiteboard.path.open("a", encoding="utf-8") as handle:
        handle.write("not-json{\n")

    with caplog.at_level(logging.WARNING, logger=_MEMORY_LOGGER):
        entries = whiteboard.entries()

    assert [entry["content"] for entry in entries] == ["public insight"]
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "whiteboard.jsonl" in warnings[0].getMessage()


def test_whiteboard_entries_warn_on_unreadable_file(tmp_path, caplog) -> None:
    whiteboard = WhiteboardMemory(group_dir=tmp_path)
    whiteboard.path.parent.mkdir(parents=True, exist_ok=True)
    whiteboard.path.mkdir()

    with caplog.at_level(logging.WARNING, logger=_MEMORY_LOGGER):
        entries = whiteboard.entries()

    assert entries == []
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "whiteboard.jsonl" in warnings[0].getMessage()
