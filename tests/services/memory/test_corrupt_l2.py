"""Corrupted-L2 handling: no silent skips, no empty-doc overwrites.

Regression tests for the swallow-and-continue paths around
``document.parse`` failures. Both corruption flavors are exercised
symmetrically everywhere:

* ``UNDECODABLE_BYTES`` — invalid UTF-8; ``read_text`` raises.
* ``UNPARSEABLE_MD`` — decodable but unrecognizable (e.g. an HTML
  error page); ``parse`` returns an empty doc without raising.

Guarantees:

* ``update._load_all_l2_docs`` / ``audit._build_l2_entry_lookup`` must
  warn (surface + path) instead of silently shrinking their input —
  for *both* flavors.
* An existing-but-corrupt target doc must NOT be rewritten as an empty
  document by ``run_update`` / ``run_merge`` / ``run_dedup``, and an
  undecodable target must be skipped with a warning instead of raising
  out of the mode.
* A surface skipped because its L2 is unreadable keeps its previously
  seen entry ids in the L3 meta (no mass re-consolidation after repair).
* ``run_merge`` defers the L3 legacy-ref migration while any L2 it
  would consult is unreadable (refs are not dropped on missing
  evidence).
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from deeptutor.services.memory import paths as paths_mod
from deeptutor.services.memory.consolidator.meta import load_l3_meta, save_l3_meta
from deeptutor.services.memory.consolidator.modes import audit as audit_mod
from deeptutor.services.memory.consolidator.modes import dedup as dedup_mod
from deeptutor.services.memory.consolidator.modes import merge as merge_mod
from deeptutor.services.memory.consolidator.modes import update as update_mod
from deeptutor.services.memory.document import Document, Entry, parse, serialize
from deeptutor.services.memory.ids import new_entry_id
from deeptutor.services.memory.snapshot.entity import Entity


@pytest.fixture()
def memory_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(paths_mod, "memory_root", lambda: tmp_path)
    (tmp_path / "L2").mkdir(parents=True, exist_ok=True)
    (tmp_path / "L3").mkdir(parents=True, exist_ok=True)
    (tmp_path / "trace").mkdir(parents=True, exist_ok=True)
    yield tmp_path


# Valid UTF-8 but nothing the memory doc parser can recognize (e.g. an
# HTML error page saved over the file). ``parse`` returns an empty doc
# without raising — the dangerous flavor of corruption.
UNPARSEABLE_MD = "<html><body><h1>503 Service Unavailable</h1></body></html>\n"

# Invalid UTF-8: ``read_text`` raises — the loud flavor of corruption.
UNDECODABLE_BYTES = b"\xff\xfe\x00corrupted binary blob"

# Both flavors, for symmetric parametrized coverage.
FLAVORS = [
    pytest.param("undecodable", id="undecodable"),
    pytest.param("unparseable", id="unparseable"),
]


def _corrupt_bytes(flavor: str) -> bytes:
    if flavor == "undecodable":
        return UNDECODABLE_BYTES
    return UNPARSEABLE_MD.encode("utf-8")


def _entity(eid: str, content: str = "user uses spaced repetition with FSRS scheduler.") -> Entity:
    return Entity(
        id=eid,
        label=f"entry {eid}",
        ts="2026-05-19T00:00:00Z",
        content=content,
        metadata={},
        fingerprint="fp",
    )


def _seed_l2(memory_dir: Path, surface: str, entries: list[Entry]) -> None:
    doc = Document(title=f"{surface} memory", sections=[("Topics", entries)])
    (memory_dir / "L2" / f"{surface}.md").write_text(serialize(doc), encoding="utf-8")


def _seed_l3(memory_dir: Path, slot: str, entries: list[Entry]) -> None:
    doc = Document(title=f"{slot} memory", sections=[("Highlights", entries)])
    (memory_dir / "L3" / f"{slot}.md").write_text(serialize(doc), encoding="utf-8")


def _settings_no_dedup():
    from deeptutor.services.memory.settings import DedupSettings, MemorySettings, MergeSettings

    return MemorySettings(
        dedup=DedupSettings(auto_after_update=False),
        merge=MergeSettings(auto_after_update=False, auto_after_dedup=False),
    )


def _warned(caplog, *needles: str) -> bool:
    return any(
        all(n in rec.getMessage() for n in needles)
        for rec in caplog.records
        if rec.levelno >= logging.WARNING
    )


# ── L3 update input: corrupted L2 is skipped loudly, never rewritten ─────


@pytest.mark.asyncio
@pytest.mark.parametrize("flavor", FLAVORS)
async def test_l3_update_warns_and_skips_corrupt_l2(memory_dir, caplog, flavor):
    chat_path = memory_dir / "L2" / "chat.md"
    chat_path.write_bytes(_corrupt_bytes(flavor))
    original = chat_path.read_bytes()
    _seed_l2(
        memory_dir,
        "notebook",
        [Entry(id=new_entry_id(), section="Topics", text="notebook fact", refs=["notebook:01A"])],
    )

    async def fake_llm(*, system_prompt, user_prompt, **kwargs):
        return '{"facts": [{"text": "synthesized note", "section": "Highlights", "refs": ["notebook"]}]}'

    with (
        patch("deeptutor.services.memory.consolidator.modes.update.call_llm", side_effect=fake_llm),
        patch.object(update_mod, "load_memory_settings") as mock_settings,
        caplog.at_level(logging.WARNING),
    ):
        mock_settings.return_value = _settings_no_dedup()
        result = await update_mod.run_update("L3", "recent", language="en")

    # The corrupted L2 is skipped as *input* only: bytes untouched.
    assert chat_path.read_bytes() == original
    # Healthy surfaces are still consolidated.
    assert result.facts_added >= 1
    # ... and the skip is no longer silent.
    assert _warned(caplog, "chat", str(chat_path)), [r.getMessage() for r in caplog.records]


@pytest.mark.parametrize("flavor", FLAVORS)
def test_audit_l3_lookup_warns_on_corrupt_l2(memory_dir, caplog, flavor):
    chat_path = memory_dir / "L2" / "chat.md"
    chat_path.write_bytes(_corrupt_bytes(flavor))
    entry = Entry(id=new_entry_id(), section="Topics", text="notebook fact", refs=["notebook:01A"])
    _seed_l2(memory_dir, "notebook", [entry])

    with caplog.at_level(logging.WARNING):
        lookup = audit_mod._build_l2_entry_lookup()

    assert entry.id in lookup
    assert _warned(caplog, "chat", str(chat_path)), [r.getMessage() for r in caplog.records]


@pytest.mark.asyncio
@pytest.mark.parametrize("flavor", FLAVORS)
async def test_l3_update_keeps_seen_ids_for_skipped_surface(memory_dir, flavor):
    chat_ids = {new_entry_id()}
    save_l3_meta("recent", seen_l2_entry_ids={"chat": set(chat_ids)})
    chat_path = memory_dir / "L2" / "chat.md"
    chat_path.write_bytes(_corrupt_bytes(flavor))
    _seed_l2(
        memory_dir,
        "notebook",
        [Entry(id=new_entry_id(), section="Topics", text="notebook fact", refs=["notebook:01A"])],
    )

    async def fake_llm(*, system_prompt, user_prompt, **kwargs):
        return '{"facts": [{"text": "synthesized note", "section": "Highlights", "refs": ["notebook"]}]}'

    with (
        patch("deeptutor.services.memory.consolidator.modes.update.call_llm", side_effect=fake_llm),
        patch.object(update_mod, "load_memory_settings") as mock_settings,
    ):
        mock_settings.return_value = _settings_no_dedup()
        await update_mod.run_update("L3", "recent", language="en")

    meta = load_l3_meta("recent")
    assert meta.seen_l2_entry_ids.get("chat") == chat_ids


# ── Update target: a corrupt doc must not be overwritten ─────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("flavor", FLAVORS)
async def test_update_l2_does_not_overwrite_corrupt_doc(memory_dir, monkeypatch, caplog, flavor):
    chat_path = memory_dir / "L2" / "chat.md"
    chat_path.write_bytes(_corrupt_bytes(flavor))
    original = chat_path.read_bytes()

    monkeypatch.setattr(
        "deeptutor.services.memory.consolidator.modes.update.snap.read_snapshot",
        lambda surface: [_entity("01ABC")],
    )

    async def fake_llm(*, system_prompt, user_prompt, **kwargs):
        return '{"facts": [{"text": "uses FSRS scheduling", "section": "Mastery", "refs": ["chat:01ABC"]}]}'

    with (
        patch("deeptutor.services.memory.consolidator.modes.update.call_llm", side_effect=fake_llm),
        patch.object(update_mod, "load_memory_settings") as mock_settings,
        caplog.at_level(logging.WARNING),
    ):
        mock_settings.return_value = _settings_no_dedup()
        result = await update_mod.run_update("L2", "chat", language="en")

    assert chat_path.read_bytes() == original
    assert result.corrupt_doc_skipped is True
    assert result.facts_added == 0
    assert _warned(caplog, "chat", str(chat_path)), [r.getMessage() for r in caplog.records]


@pytest.mark.asyncio
@pytest.mark.parametrize("flavor", FLAVORS)
async def test_update_l3_does_not_overwrite_corrupt_doc(memory_dir, caplog, flavor):
    recent_path = memory_dir / "L3" / "recent.md"
    recent_path.write_bytes(_corrupt_bytes(flavor))
    original = recent_path.read_bytes()
    _seed_l2(
        memory_dir,
        "notebook",
        [Entry(id=new_entry_id(), section="Topics", text="notebook fact", refs=["notebook:01A"])],
    )

    async def fake_llm(*, system_prompt, user_prompt, **kwargs):
        return '{"facts": [{"text": "synthesized note", "section": "Highlights", "refs": ["notebook"]}]}'

    with (
        patch("deeptutor.services.memory.consolidator.modes.update.call_llm", side_effect=fake_llm),
        patch.object(update_mod, "load_memory_settings") as mock_settings,
        caplog.at_level(logging.WARNING),
    ):
        mock_settings.return_value = _settings_no_dedup()
        result = await update_mod.run_update("L3", "recent", language="en")

    assert recent_path.read_bytes() == original
    assert result.corrupt_doc_skipped is True
    assert _warned(caplog, "recent", str(recent_path)), [r.getMessage() for r in caplog.records]


# ── Merge / dedup: standalone runs must not rewrite a corrupt doc ────────


@pytest.mark.asyncio
@pytest.mark.parametrize("flavor", FLAVORS)
async def test_run_merge_does_not_rewrite_corrupt_doc(memory_dir, caplog, flavor):
    chat_path = memory_dir / "L2" / "chat.md"
    chat_path.write_bytes(_corrupt_bytes(flavor))
    original = chat_path.read_bytes()

    with caplog.at_level(logging.WARNING):
        result = await merge_mod.run_merge("L2", "chat")

    assert chat_path.read_bytes() == original
    assert result.rewrote is False
    assert _warned(caplog, "chat", str(chat_path)), [r.getMessage() for r in caplog.records]


@pytest.mark.asyncio
@pytest.mark.parametrize("flavor", FLAVORS)
async def test_run_dedup_skips_corrupt_doc(memory_dir, caplog, flavor):
    chat_path = memory_dir / "L2" / "chat.md"
    chat_path.write_bytes(_corrupt_bytes(flavor))
    original = chat_path.read_bytes()

    with (
        patch.object(dedup_mod, "load_memory_settings") as mock_settings,
        caplog.at_level(logging.WARNING),
    ):
        mock_settings.return_value = _settings_no_dedup()
        result = await dedup_mod.run_dedup("L2", "chat", iterations=1)

    assert chat_path.read_bytes() == original
    assert result.edits_applied == 0
    assert _warned(caplog, "chat", str(chat_path)), [r.getMessage() for r in caplog.records]


@pytest.mark.asyncio
@pytest.mark.parametrize("flavor", FLAVORS)
async def test_run_merge_defers_l3_legacy_migration_when_l2_corrupt(memory_dir, caplog, flavor):
    legacy_id = new_entry_id()
    entry = Entry(id=new_entry_id(), section="Highlights", text="fact", refs=[legacy_id])
    _seed_l3(memory_dir, "recent", [entry])
    chat_path = memory_dir / "L2" / "chat.md"
    chat_path.write_bytes(_corrupt_bytes(flavor))

    with caplog.at_level(logging.WARNING):
        await merge_mod.run_merge("L3", "recent")

    doc = parse((memory_dir / "L3" / "recent.md").read_text(encoding="utf-8"))
    assert any(legacy_id in e.refs for e in doc.all_entries())
    assert _warned(caplog, "chat", str(chat_path)), [r.getMessage() for r in caplog.records]
