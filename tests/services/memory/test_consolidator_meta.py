"""Tests for per-doc consolidator metadata sidecars (consolidator/meta.py)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from deeptutor.services.memory import paths as paths_mod
from deeptutor.services.memory.consolidator import meta as meta_mod
from deeptutor.services.memory.consolidator.meta import (
    L2Meta,
    L3Meta,
    l2_meta_path,
    l3_meta_path,
    load_l2_meta,
    load_l3_meta,
    save_l2_meta,
    save_l3_meta,
)


@pytest.fixture()
def memory_root(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(paths_mod, "memory_root", lambda: tmp_path)
    return tmp_path


def _read_meta_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_all_exports_are_importable() -> None:
    assert sorted(meta_mod.__all__) == [
        "L2Meta",
        "L3Meta",
        "l2_meta_path",
        "l3_meta_path",
        "load_l2_meta",
        "load_l3_meta",
        "save_l2_meta",
        "save_l3_meta",
    ]
    for name in meta_mod.__all__:
        assert getattr(meta_mod, name) is not None


def test_l2_meta_path_anchors_to_memory_l2_dir(memory_root: Path) -> None:
    assert l2_meta_path("chat") == memory_root / "L2" / "chat.meta.json"
    assert l2_meta_path("notebook") == memory_root / "L2" / "notebook.meta.json"


def test_l3_meta_path_anchors_to_memory_l3_dir(memory_root: Path) -> None:
    assert l3_meta_path("recent") == memory_root / "L3" / "recent.meta.json"
    assert l3_meta_path("profile") == memory_root / "L3" / "profile.meta.json"


def test_save_l2_meta_writes_versioned_sorted_payload(memory_root: Path) -> None:
    meta = save_l2_meta("chat", seen_entity_refs={"b:02", "a:01"})

    assert meta.last_update_at is not None
    assert meta.seen_entity_refs == {"b:02", "a:01"}
    parsed = _read_meta_json(memory_root / "L2" / "chat.meta.json")
    assert parsed["version"] == 1
    assert parsed["last_update_at"] == meta.last_update_at
    assert parsed["seen_entity_refs"] == ["a:01", "b:02"]


def test_save_l2_meta_timestamp_is_utc_iso(memory_root: Path) -> None:
    meta = save_l2_meta("chat", seen_entity_refs=set())
    stamp = datetime.fromisoformat(meta.last_update_at)
    assert stamp.tzinfo is not None
    assert stamp.utcoffset().total_seconds() == 0


def test_save_l2_meta_creates_missing_parent_dirs(memory_root: Path) -> None:
    assert not (memory_root / "L2").exists()
    save_l2_meta("quiz", seen_entity_refs=set())
    assert (memory_root / "L2" / "quiz.meta.json").is_file()


def test_save_l2_meta_returns_snapshot_independent_of_input(memory_root: Path) -> None:
    refs: set[str] = {"chat:01"}
    meta = save_l2_meta("chat", seen_entity_refs=refs)
    refs.add("chat:02")
    meta.seen_entity_refs.add("chat:03")

    reloaded = load_l2_meta("chat")
    assert reloaded.seen_entity_refs == {"chat:01"}


def test_l2_meta_roundtrip_keeps_set_semantics(memory_root: Path) -> None:
    refs = {"chat:01HZK4AAAA", "chat:完全理解", "notebook:r1", "chat:01HZK4AAAA"}
    save_l2_meta("chat", seen_entity_refs=refs)
    reloaded = load_l2_meta("chat")
    assert reloaded.seen_entity_refs == refs


def test_save_l2_meta_replaces_previous_payload(memory_root: Path) -> None:
    save_l2_meta("chat", seen_entity_refs={"old:1"})
    save_l2_meta("chat", seen_entity_refs={"new:1"})
    reloaded = load_l2_meta("chat")
    assert reloaded.seen_entity_refs == {"new:1"}
    leftovers = list((memory_root / "L2").glob("chat.meta.json.*"))
    assert leftovers == []


def test_load_l2_meta_missing_file_behaves_as_first_run(memory_root: Path) -> None:
    meta = load_l2_meta("chat")
    assert meta == L2Meta()
    assert meta.last_update_at is None
    assert meta.seen_entity_refs == set()


def test_load_l2_meta_corrupted_json_degrades_to_defaults(memory_root: Path) -> None:
    path = l2_meta_path("chat")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")

    meta = load_l2_meta("chat")
    assert meta == L2Meta()


def test_load_l2_meta_unreadable_file_degrades_to_defaults(memory_root: Path) -> None:
    path = l2_meta_path("chat")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "seen_entity_refs": ["a"]}), encoding="utf-8")
    path.chmod(0o000)
    try:
        meta = load_l2_meta("chat")
    finally:
        path.chmod(0o644)
    assert meta == L2Meta()


@pytest.mark.parametrize(
    "payload,kept_last_update",
    [
        ({"version": 1, "seen_entity_refs": "chat:01"}, True),
        ({"version": 1, "seen_entity_refs": {"chat:01": 1}}, True),
        ({"version": 1, "seen_entity_refs": None}, True),
        ({"version": 1, "last_update_at": "2026-01-02T03:04:05+00:00", "extra": "ignored"}, True),
        ({}, False),
    ],
)
def test_load_l2_meta_coerces_malformed_refs(memory_root, payload, kept_last_update) -> None:
    path = l2_meta_path("chat")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")

    meta = load_l2_meta("chat")
    assert meta.seen_entity_refs == set()
    if kept_last_update:
        assert meta.last_update_at == payload.get("last_update_at")
    else:
        assert meta.last_update_at is None


def test_save_l3_meta_writes_versioned_sorted_payload(memory_root: Path) -> None:
    meta = save_l3_meta(
        "recent",
        seen_l2_entry_ids={"chat": {"m_b", "m_a"}, "notebook": {"m_c"}},
    )

    assert meta.last_update_at is not None
    assert meta.seen_l2_entry_ids == {"chat": {"m_a", "m_b"}, "notebook": {"m_c"}}
    parsed = _read_meta_json(memory_root / "L3" / "recent.meta.json")
    assert parsed["version"] == 1
    assert parsed["last_update_at"] == meta.last_update_at
    assert parsed["seen_l2_entry_ids"] == {"chat": ["m_a", "m_b"], "notebook": ["m_c"]}


def test_save_l3_meta_returns_snapshot_independent_of_input(memory_root: Path) -> None:
    seen: dict[str, set[str]] = {"chat": {"m_1"}}
    meta = save_l3_meta("recent", seen_l2_entry_ids=seen)
    seen["chat"].add("m_2")
    seen["late"] = {"m_3"}
    meta.seen_l2_entry_ids["chat"].add("m_4")

    reloaded = load_l3_meta("recent")
    assert reloaded.seen_l2_entry_ids == {"chat": {"m_1"}}


def test_l3_meta_roundtrip_across_surfaces(memory_root: Path) -> None:
    seen = {"chat": {"m_a"}, "notebook": {"m_b", "m_c"}, "quiz": set()}
    save_l3_meta("profile", seen_l2_entry_ids=seen)
    reloaded = load_l3_meta("profile")
    assert reloaded.seen_l2_entry_ids == seen


def test_load_l3_meta_missing_file_behaves_as_first_run(memory_root: Path) -> None:
    meta = load_l3_meta("recent")
    assert meta == L3Meta()
    assert meta.seen_l2_entry_ids == {}


def test_load_l3_meta_corrupted_json_degrades_to_defaults(memory_root: Path) -> None:
    path = l3_meta_path("recent")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("]] not json", encoding="utf-8")

    assert load_l3_meta("recent") == L3Meta()


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"version": 1, "seen_l2_entry_ids": ["not", "a", "dict"]}, {}),
        ({"version": 1, "seen_l2_entry_ids": None}, {}),
        ({"version": 1, "seen_l2_entry_ids": {"chat": "m_a"}}, {"chat": set()}),
        (
            {
                "version": 1,
                "last_update_at": "2026-03-04T05:06:07+00:00",
                "seen_l2_entry_ids": {"chat": ["m_a"], "notebook": {"m_b": 1}, "quiz": None},
            },
            {"chat": {"m_a"}, "notebook": set(), "quiz": set()},
        ),
        ({}, None),
    ],
)
def test_load_l3_meta_coerces_malformed_structures(memory_root, payload, expected) -> None:
    path = l3_meta_path("recent")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")

    meta = load_l3_meta("recent")
    if expected is None:
        assert meta == L3Meta()
    else:
        assert meta.seen_l2_entry_ids == expected
