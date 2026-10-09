"""Snapshot store tests — corrupt change-log lines and failed deletion
must leave a warning trace instead of vanishing silently.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from deeptutor.services.memory.snapshot import store as snapshot_store


@pytest.fixture
def tmp_snapshot_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "memory"
    monkeypatch.setattr(snapshot_store, "memory_root", lambda: root)
    return root


def _warn_records(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        rec.getMessage()
        for rec in caplog.records
        if rec.levelno == logging.WARNING and rec.name == "deeptutor.services.memory.snapshot.store"
    ]


def test_iter_changes_skips_corrupt_line_with_warning(
    tmp_snapshot_root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = snapshot_store.changes_file("chat")
    path.parent.mkdir(parents=True)
    good = json.dumps({"ts": "t", "kind": "added", "entity_id": "e1", "label": "L"})
    path.write_text("{ corrupt\n" + good + "\n", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        entries = list(snapshot_store.iter_changes("chat"))

    assert [e.entity_id for e in entries] == ["e1"]
    warnings = _warn_records(caplog)
    assert any(str(path) in w for w in warnings)


def test_clear_changes_unlink_failure_warns_without_raising(
    tmp_snapshot_root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = snapshot_store.changes_file("chat")
    path.parent.mkdir(parents=True)
    # A directory where the JSONL file should be makes unlink() fail with OSError.
    path.mkdir()

    with caplog.at_level(logging.WARNING):
        snapshot_store.clear_changes("chat")

    assert path.exists()
    warnings = _warn_records(caplog)
    assert any(str(path) in w for w in warnings)
