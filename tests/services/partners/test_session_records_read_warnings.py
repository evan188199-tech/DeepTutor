"""Corrupt-record warnings in PartnerSessionStore reads (history never hides gaps)."""

from __future__ import annotations

import json
import logging

from deeptutor.services.partners.sessions import PartnerSessionStore

_LOGGER = "deeptutor.services.partners.sessions"


def _write_lines(store: PartnerSessionStore, session_key: str, lines: list[str]) -> None:
    path = store._path(session_key)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_read_records_warns_and_skips_corrupt_lines(tmp_path, caplog) -> None:
    store = PartnerSessionStore(tmp_path)
    _write_lines(
        store,
        "telegram:7",
        [
            json.dumps({"role": "user", "content": "first"}),
            "{not valid json",
            json.dumps({"role": "assistant", "content": "second"}),
        ],
    )

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        records = store._read_records("telegram:7")

    assert [record["content"] for record in records] == ["first", "second"]
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "telegram:7" in warnings[0].getMessage()


def test_messages_page_warns_and_skips_corrupt_lines(tmp_path, caplog) -> None:
    store = PartnerSessionStore(tmp_path)
    _write_lines(
        store,
        "web:abc",
        [
            json.dumps({"role": "user", "content": "one"}),
            "not-json{",
            json.dumps({"role": "assistant", "content": "two"}),
        ],
    )

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        page = store.messages_page("web:abc")

    assert [message["content"] for message in page["messages"]] == ["one", "two"]
    assert page["total"] == 2
    assert page["next_before"] is None
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "web:abc" in warnings[0].getMessage()
