"""Per-session deferred-tool state: registration, lookup, and reset semantics."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import deeptutor.services.mcp.session_state as session_state
from deeptutor.services.mcp.session_state import load_loaded_tools, record_loaded_tools


class _FakePathService:
    def __init__(self, root: Path) -> None:
        self.root = root

    def get_session_workspace(self, feature: str, session_id: str) -> Path:
        return self.root / feature / session_id


@pytest.fixture
def ws_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "ws"
    monkeypatch.setattr(session_state, "get_path_service", lambda: _FakePathService(root))
    return root


def _state_path(ws_root: Path, session_id: str) -> Path:
    return ws_root / "chat" / session_id / "loaded_tools.json"


def test_record_then_load_roundtrip(ws_root: Path) -> None:
    record_loaded_tools("s1", {"web_search", "reason"})
    assert load_loaded_tools("s1") == {"web_search", "reason"}


def test_record_writes_sorted_names(ws_root: Path) -> None:
    record_loaded_tools("s2", {"zeta", "alpha", "mid"})
    data = json.loads(_state_path(ws_root, "s2").read_text(encoding="utf-8"))
    assert data == {"loaded_tools": ["alpha", "mid", "zeta"]}


def test_record_empty_session_id_is_noop(ws_root: Path) -> None:
    record_loaded_tools("", {"web_search"})
    assert not (ws_root / "chat").exists()
    assert load_loaded_tools("") == set()


def test_record_creates_missing_workspace_dirs(ws_root: Path) -> None:
    record_loaded_tools("deep/nested", {"reason"})
    assert load_loaded_tools("deep/nested") == {"reason"}


def test_record_overwrites_previous_state(ws_root: Path) -> None:
    record_loaded_tools("s3", {"web_search", "reason", "paper_search"})
    record_loaded_tools("s3", {"reason"})
    assert load_loaded_tools("s3") == {"reason"}


def test_record_failure_is_swallowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "broken"
    root.mkdir(parents=True)
    (root / "chat").write_text("occupied", encoding="utf-8")
    monkeypatch.setattr(session_state, "get_path_service", lambda: _FakePathService(root))
    record_loaded_tools("s4", {"reason"})
    assert load_loaded_tools("s4") == set()


def test_load_missing_file_returns_empty(ws_root: Path) -> None:
    assert load_loaded_tools("absent") == set()


def test_load_corrupt_json_returns_empty(ws_root: Path) -> None:
    _state_path(ws_root, "s5").parent.mkdir(parents=True)
    _state_path(ws_root, "s5").write_text("{not json", encoding="utf-8")
    assert load_loaded_tools("s5") == set()


def test_load_non_dict_payload_returns_empty(ws_root: Path) -> None:
    _state_path(ws_root, "s6").parent.mkdir(parents=True)
    _state_path(ws_root, "s6").write_text(json.dumps(["web_search"]), encoding="utf-8")
    assert load_loaded_tools("s6") == set()


def test_load_non_list_loaded_tools_returns_empty(ws_root: Path) -> None:
    _state_path(ws_root, "s7").parent.mkdir(parents=True)
    _state_path(ws_root, "s7").write_text(
        json.dumps({"loaded_tools": "web_search"}), encoding="utf-8"
    )
    assert load_loaded_tools("s7") == set()


def test_load_drops_blank_names(ws_root: Path) -> None:
    _state_path(ws_root, "s8").parent.mkdir(parents=True)
    _state_path(ws_root, "s8").write_text(
        json.dumps({"loaded_tools": ["reason", "  ", "web_search"]}), encoding="utf-8"
    )
    assert load_loaded_tools("s8") == {"reason", "web_search"}


def test_sessions_are_isolated(ws_root: Path) -> None:
    record_loaded_tools("user-a", {"web_search"})
    record_loaded_tools("user-b", {"reason"})
    assert load_loaded_tools("user-a") == {"web_search"}
    assert load_loaded_tools("user-b") == {"reason"}
