"""Starter-suggestion settings: file-level defaults, degradation, persistence.

Complements ``tests/services/test_starter_settings.py`` (the clamping surface
and the suggestions consumer) with the behaviors the weak-tail triage flagged:
default shapes, degraded reads (unreadable file, valid-but-non-dict JSON, junk
fields), and save-then-read consistency against a real temp file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from deeptutor.services.settings import starter_settings


class _FakePathService:
    def __init__(self, root: Path) -> None:
        self._root = root

    def get_settings_file(self, name: str) -> Path:
        return self._root / f"{name}.json"


class _UnreadableFile:
    """Stands in for a settings file that exists but cannot be read."""

    def exists(self) -> bool:
        return True

    def read_text(self, encoding: str) -> str:
        raise OSError("permission denied")


class _UnreadablePathService:
    def get_settings_file(self, name: str) -> _UnreadableFile:
        return _UnreadableFile()


def _install_root(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setattr(
        starter_settings, "get_path_service", lambda: _FakePathService(root)
    )


@pytest.fixture
def scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _install_root(monkeypatch, tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# Constants and defaults
# ---------------------------------------------------------------------------


def test_module_constants_state_the_contract() -> None:
    assert starter_settings.DEFAULT_TRACE_COUNT == 20
    assert starter_settings.TRACE_COUNT_RANGE == (3, 100)
    assert starter_settings.DEFAULT_STARTER_SETTINGS == {
        "version": 1,
        "trace_count": 20,
    }


def test_missing_file_returns_fresh_defaults(scope: Path) -> None:
    current = starter_settings.get_starter_settings()

    assert current == starter_settings.DEFAULT_STARTER_SETTINGS
    current["trace_count"] = 9999
    assert starter_settings.get_starter_settings() == {
        "version": 1,
        "trace_count": 20,
    }


# ---------------------------------------------------------------------------
# Clamping arithmetic (unit level)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "given,expected",
    [
        (2, 3),
        (3, 3),
        (100, 100),
        (101, 100),
    ],
)
def test_clamp_bounds_are_inclusive(given: int, expected: int) -> None:
    assert starter_settings._clamp(given) == expected


@pytest.mark.parametrize(
    "given,expected",
    [
        ("25", 25),
        (" 7 ", 7),
        (4.9, 4),
    ],
)
def test_clamp_coerces_numeric_strings_and_floats(given: Any, expected: int) -> None:
    assert starter_settings._clamp(given) == expected


@pytest.mark.parametrize(
    "given",
    [object(), [1, 2], {}, "abc", float("nan")],
)
def test_clamp_falls_back_to_default_for_unconvertible(given: Any) -> None:
    assert starter_settings._clamp(given) == starter_settings.DEFAULT_TRACE_COUNT


# ---------------------------------------------------------------------------
# Degraded reads
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    ["[1, 2]", '"text"', "42", "null", "true", ""],
)
def test_non_dict_json_degrades_to_defaults(
    scope: Path, content: str
) -> None:
    (scope / "starters.json").write_text(content, encoding="utf-8")

    assert starter_settings.get_starter_settings() == {
        "version": 1,
        "trace_count": 20,
    }


def test_unreadable_file_degrades_to_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        starter_settings, "get_path_service", lambda: _UnreadablePathService()
    )

    assert starter_settings.get_starter_settings() == {
        "version": 1,
        "trace_count": 20,
    }


def test_unknown_fields_are_dropped_and_version_is_forced(scope: Path) -> None:
    (scope / "starters.json").write_text(
        json.dumps({"version": 9, "trace_count": 5, "admin": True}),
        encoding="utf-8",
    )

    assert starter_settings.get_starter_settings() == {"version": 1, "trace_count": 5}


@pytest.mark.parametrize(
    "stored,expected",
    [
        ([1, 2], 20),
        ({"deep": 1}, 20),
        ("12", 12),
        (5.9, 5),
    ],
)
def test_file_trace_count_of_odd_type_is_normalized(
    scope: Path, stored: Any, expected: int
) -> None:
    (scope / "starters.json").write_text(
        json.dumps({"trace_count": stored}), encoding="utf-8"
    )

    assert starter_settings.get_starter_settings()["trace_count"] == expected


# ---------------------------------------------------------------------------
# Save-then-read consistency
# ---------------------------------------------------------------------------


def test_save_empty_settings_writes_defaults(scope: Path) -> None:
    saved = starter_settings.save_starter_settings({})

    assert saved == {"version": 1, "trace_count": 20}
    assert starter_settings.get_starter_settings() == saved


def test_save_none_value_normalizes_to_default(scope: Path) -> None:
    saved = starter_settings.save_starter_settings({"trace_count": None})

    assert saved["trace_count"] == 20
    assert starter_settings.get_starter_settings()["trace_count"] == 20


@pytest.mark.parametrize("boundary", [3, 100])
def test_save_then_read_preserves_range_boundaries(
    scope: Path, boundary: int
) -> None:
    starter_settings.save_starter_settings({"trace_count": boundary})

    assert starter_settings.get_starter_settings()["trace_count"] == boundary


def test_saved_payload_matches_disk_bytes(scope: Path) -> None:
    saved = starter_settings.save_starter_settings({"trace_count": 42, "junk": 1})

    on_disk = json.loads((scope / "starters.json").read_text(encoding="utf-8"))
    assert on_disk == saved == {"version": 1, "trace_count": 42}


def test_saving_overwrites_previous_content_completely(scope: Path) -> None:
    starter_settings.save_starter_settings({"trace_count": 50})
    starter_settings.save_starter_settings({"trace_count": 8})

    current = starter_settings.get_starter_settings()
    assert current == {"version": 1, "trace_count": 8}
    assert json.loads((scope / "starters.json").read_text(encoding="utf-8")) == current


def test_reads_resolve_the_file_per_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A per-user PathService installed between calls reroutes reads."""
    user_a, user_b = tmp_path / "a", tmp_path / "b"

    _install_root(monkeypatch, user_a)
    starter_settings.save_starter_settings({"trace_count": 7})

    _install_root(monkeypatch, user_b)
    assert starter_settings.get_starter_settings()["trace_count"] == 20

    _install_root(monkeypatch, user_a)
    assert starter_settings.get_starter_settings()["trace_count"] == 7
