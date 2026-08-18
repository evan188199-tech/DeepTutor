"""Tests for MarginNoteSyncCoordinator, probe_marginnote, and official write probe."""

from __future__ import annotations

from pathlib import Path
import pytest

from deeptutor.capabilities.marginnote.probe import probe_marginnote
from deeptutor.capabilities.marginnote.official import probe_official_write_interface
from deeptutor.capabilities.marginnote.sync import (
    MarginNoteSyncCoordinator,
    coordinator_for,
    drop_coordinator,
)


def _seed(root: Path) -> None:
    (root / "Fourier.md").write_text(
        "# Fourier Analysis\n\n"
        "> A transform maps time to frequency (p.42) [color:yellow]\n"
        "I think this is the core definition. #transform\n",
        encoding="utf-8",
    )


def test_probe_marginnote_detects_structure(tmp_path: Path) -> None:
    _seed(tmp_path)
    res = probe_marginnote(str(tmp_path))
    assert res["compatible"] is True
    assert res["adapter"] == "export"
    assert res["counts"]["highlights"] == 1
    assert res["capabilities"]["can_read"] is True
    assert res["capabilities"]["official_write"] is False


def test_probe_marginnote_handles_missing_dir(tmp_path: Path) -> None:
    non_existent = tmp_path / "missing"
    res = probe_marginnote(str(non_existent))
    assert res["compatible"] is False
    assert "choose_existing_export" in res["recover_actions"]


def test_probe_official_write_interface() -> None:
    probe = probe_official_write_interface()
    payload = probe.to_dict()
    assert "write_api_verified" in payload
    assert payload["write_api_verified"] is False


def test_sync_coordinator_lifecycle_and_events(tmp_path: Path) -> None:
    _seed(tmp_path)
    coord = MarginNoteSyncCoordinator(
        kb_name="test-mn-kb",
        notebook_path=str(tmp_path),
        poll_interval=0.5,
    )
    events = []
    coord.subscribe(lambda ev: events.append(ev))

    st = coord.sync_once()
    assert st["status"] == "ready"
    assert st["counts"]["highlights"] == 1
    assert st["pending_write_count"] == 0

    item = coord.enqueue_write("notes/test.md", kind="note", content="My note content")
    assert item.status == "awaiting_import"
    assert any(e.get("type") == "write_queued" for e in events)
    assert coord.status()["pending_write_count"] == 1

    coord.mark_imported(item.id)
    assert coord.status()["pending_write_count"] == 0
    assert any(e.get("type") == "write_imported" for e in events)

    coord.stop()
