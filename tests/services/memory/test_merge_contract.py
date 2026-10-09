"""Contract and boundary tests for the merge mode (``modes/merge.py``).

Complements ``test_merge.py`` (dedup / idempotency / L3 migration happy
paths) with the pieces it does not exercise: the ``MergeResult`` dataclass
contract, unknown-layer errors, event payloads, the ignored
``language`` / ``user_label`` kwargs, a raising ``on_event`` consumer, and
the L3 migration's degradation paths (malformed / missing L2 surfaces,
same-surface collapse, mixed ref sets, second-pass no-op).

No LLM, no network: everything runs against a temp memory root.
"""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import pytest

from deeptutor.services.memory import paths as paths_mod
from deeptutor.services.memory.consolidator.modes import merge as merge_mod
from deeptutor.services.memory.document import Document, Entry, parse, serialize


@pytest.fixture()
def memory_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(paths_mod, "memory_root", lambda: tmp_path)
    (tmp_path / "L2").mkdir(parents=True, exist_ok=True)
    (tmp_path / "L3").mkdir(parents=True, exist_ok=True)
    yield tmp_path


_LEGACY_DOC_WITH_DUPLICATES = """\
# notebook memory

## Concepts
- understands FSRS scheduling[^m_01HZK1ABCDEFGHJKMNPQRSTVWX]
- understands ε-δ definition[^m_01HZK2ABCDEFGHJKMNPQRSTVWX]
- understands monotone convergence[^m_01HZK3ABCDEFGHJKMNPQRSTVWX]

---

[^m_01HZK1ABCDEFGHJKMNPQRSTVWX]: notebook:3a563e6f
[^m_01HZK2ABCDEFGHJKMNPQRSTVWX]: notebook:3a563e6f
[^m_01HZK3ABCDEFGHJKMNPQRSTVWX]: notebook:3a563e6f
"""


def _seed_l2(surface: str, *entry_ids: str) -> None:
    """Write a one-section L2 md owning ``entry_ids``."""
    doc = Document(
        title=f"{surface} memory",
        sections=[
            (
                "Themes",
                [
                    Entry(
                        id=eid,
                        section="Themes",
                        text=f"fact {eid}",
                        refs=[f"{surface}:r1"],
                    )
                    for eid in entry_ids
                ],
            ),
        ],
    )
    target = paths_mod.l2_file(surface)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(serialize(doc), encoding="utf-8")


# ── MergeResult contract ────────────────────────────────────────────────


def test_merge_result_has_expected_fields_and_defaults():
    names = [f.name for f in fields(merge_mod.MergeResult)]
    assert names == [
        "layer",
        "key",
        "footnote_rows_before",
        "footnote_rows_after",
        "rewrote",
        "legacy_l3_refs_migrated",
    ]
    # Only the L3 migration counter is optional; everything else is required.
    plain = merge_mod.MergeResult(
        layer="L2", key="notebook", footnote_rows_before=5, footnote_rows_after=1, rewrote=True
    )
    assert plain.legacy_l3_refs_migrated == 0
    assert plain == merge_mod.MergeResult(
        layer="L2", key="notebook", footnote_rows_before=5, footnote_rows_after=1, rewrote=True
    )


# ── run_merge boundaries ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_merge_unknown_layer_raises_value_error(memory_dir):
    events: list[dict] = []

    async def collect(evt):
        events.append(evt)

    with pytest.raises(ValueError, match="unknown layer"):
        await merge_mod.run_merge("L4", "notebook", on_event=collect)
    # The failure happens before any event is emitted.
    assert events == []


@pytest.mark.asyncio
async def test_merge_l3_missing_doc_reports_no_doc(memory_dir):
    events: list[dict] = []

    async def collect(evt):
        events.append(evt)

    result = await merge_mod.run_merge("L3", "scope", on_event=collect)
    assert result.layer == "L3"
    assert result.key == "scope"
    assert result.rewrote is False
    assert result.footnote_rows_before == 0
    assert result.footnote_rows_after == 0
    assert result.legacy_l3_refs_migrated == 0
    assert not paths_mod.l3_file("scope").exists()
    assert [e["stage"] for e in events] == ["done"]
    assert events[0]["no_doc"] is True
    assert events[0]["rewrote"] is False


@pytest.mark.asyncio
async def test_merge_emits_progress_event_payload(memory_dir):
    target = paths_mod.l2_file("notebook")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_LEGACY_DOC_WITH_DUPLICATES, encoding="utf-8")

    events: list[dict] = []

    async def collect(evt):
        events.append(evt)

    await merge_mod.run_merge("L2", "notebook", on_event=collect)
    progress = [e for e in events if e["stage"] == "progress"]
    assert len(progress) == 1
    evt = progress[0]
    assert evt["mode"] == "merge"
    assert evt["footnote_rows_before"] == 3
    assert evt["footnote_rows_after"] == 1
    # No L3 migration happens on an L2 doc.
    assert evt["legacy_l3_refs_migrated"] == 0


@pytest.mark.asyncio
async def test_merge_accepts_language_and_user_label_kwargs(memory_dir):
    """Signature symmetry: merge ignores ``language`` / ``user_label``."""
    target = paths_mod.l2_file("notebook")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_LEGACY_DOC_WITH_DUPLICATES, encoding="utf-8")

    result = await merge_mod.run_merge(
        "L2", "notebook", language="zh", user_label="alice"
    )
    assert result.rewrote is True
    assert result.footnote_rows_before == 3
    assert result.footnote_rows_after == 1
    assert "[^1]: notebook:3a563e6f" in target.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_merge_tolerates_raising_on_event_consumer(memory_dir):
    """A broken SSE consumer must not abort the merge (emit swallows it)."""
    target = paths_mod.l2_file("notebook")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_LEGACY_DOC_WITH_DUPLICATES, encoding="utf-8")

    async def boom(_evt):
        raise RuntimeError("consumer is down")

    result = await merge_mod.run_merge("L2", "notebook", on_event=boom)
    assert result.rewrote is True
    new_text = target.read_text(encoding="utf-8")
    assert new_text.count("[^1]: notebook:3a563e6f") == 1
    assert new_text.count("[^m_") == 0


@pytest.mark.asyncio
async def test_merge_entryless_doc_is_a_no_op(memory_dir):
    """A doc with zero entries: rows 0/0, file already canonical, no rewrite."""
    target = paths_mod.l2_file("notebook")
    target.parent.mkdir(parents=True, exist_ok=True)
    canonical = serialize(Document(title="notebook memory"))
    target.write_text(canonical, encoding="utf-8")

    result = await merge_mod.run_merge("L2", "notebook")
    assert result.layer == "L2"
    assert result.key == "notebook"
    assert result.footnote_rows_before == 0
    assert result.footnote_rows_after == 0
    assert result.rewrote is False
    assert target.read_text(encoding="utf-8") == canonical


# ── L3 legacy-ref migration: degradation branches ───────────────────────


@pytest.mark.asyncio
async def test_merge_l3_migration_survives_malformed_and_missing_l2(memory_dir):
    """One L2 surface is unreadable (directory), one file is absent — the
    migration still resolves what it can and silently drops the rest."""
    chat_id = "m_01HZK1ABCDEFGHJKMNPQRSTVWX"
    notebook_id = "m_01HZK2ABCDEFGHJKMNPQRSTVWX"
    quiz_id = "m_01HZK3ABCDEFGHJKMNPQRSTVWX"

    _seed_l2("chat", chat_id)
    # A directory where notebook.md should be → read_text raises → caught.
    paths_mod.l2_file("notebook").mkdir(parents=True, exist_ok=True)
    # quiz has no L2 file at all → skipped.

    legacy_l3 = f"""# User profile

## Knowledge
- synthesized claim[^m_01HZK9ABCDEFGHJKMNPQRSTVWX]

[^m_01HZK9ABCDEFGHJKMNPQRSTVWX]: {chat_id}, {notebook_id}, {quiz_id}
"""
    target = paths_mod.l3_file("profile")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(legacy_l3, encoding="utf-8")

    result = await merge_mod.run_merge("L3", "profile")
    # All three refs were entry ids → all three counted as visited.
    assert result.legacy_l3_refs_migrated == 3
    # Only the resolvable one survives, rewritten to its surface name.
    doc = parse(target.read_text(encoding="utf-8"))
    assert doc.all_entries()[0].refs == ["chat"]


@pytest.mark.asyncio
async def test_merge_l3_collapses_entry_ids_sharing_one_surface(memory_dir):
    """Two distinct entry ids owned by the same L2 surface collapse to a
    single surface ref; the migrated count still reports every visit."""
    id_a = "m_01HZK1ABCDEFGHJKMNPQRSTVWX"
    id_b = "m_01HZK2ABCDEFGHJKMNPQRSTVWX"
    _seed_l2("chat", id_a, id_b)

    legacy_l3 = f"""# User profile

## Knowledge
- claim synthesizing two chat entries[^m_01HZK9ABCDEFGHJKMNPQRSTVWX]

[^m_01HZK9ABCDEFGHJKMNPQRSTVWX]: {id_a}, {id_b}
"""
    target = paths_mod.l3_file("profile")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(legacy_l3, encoding="utf-8")

    result = await merge_mod.run_merge("L3", "profile")
    assert result.legacy_l3_refs_migrated == 2
    doc = parse(target.read_text(encoding="utf-8"))
    assert doc.all_entries()[0].refs == ["chat"]
    new_text = target.read_text(encoding="utf-8")
    assert new_text.count("[^1]: chat") == 1
    assert "[^2]" not in new_text


@pytest.mark.asyncio
async def test_merge_l3_mixed_surface_ref_and_entry_id_dedup(memory_dir):
    """A surface ref kept alongside an entry id that resolves to the same
    surface: the plain ref stays first, the duplicate resolution is dropped."""
    notebook_id = "m_01HZK2ABCDEFGHJKMNPQRSTVWX"
    _seed_l2("notebook", notebook_id)

    legacy_l3 = f"""# User profile

## Knowledge
- claim[^m_01HZK9ABCDEFGHJKMNPQRSTVWX]

[^m_01HZK9ABCDEFGHJKMNPQRSTVWX]: notebook, {notebook_id}
"""
    target = paths_mod.l3_file("profile")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(legacy_l3, encoding="utf-8")

    result = await merge_mod.run_merge("L3", "profile")
    assert result.legacy_l3_refs_migrated == 1
    doc = parse(target.read_text(encoding="utf-8"))
    assert doc.all_entries()[0].refs == ["notebook"]


@pytest.mark.asyncio
async def test_merge_l3_second_pass_is_idempotent(memory_dir):
    """Re-merging an already-migrated L3 doc rewrites nothing and reports
    zero migrations."""
    chat_id = "m_01HZK1ABCDEFGHJKMNPQRSTVWX"
    _seed_l2("chat", chat_id)

    legacy_l3 = f"""# User profile

## Knowledge
- claim[^m_01HZK9ABCDEFGHJKMNPQRSTVWX]

[^m_01HZK9ABCDEFGHJKMNPQRSTVWX]: {chat_id}
"""
    target = paths_mod.l3_file("profile")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(legacy_l3, encoding="utf-8")

    first = await merge_mod.run_merge("L3", "profile")
    assert first.rewrote is True
    assert first.legacy_l3_refs_migrated == 1
    after_first = target.read_text(encoding="utf-8")

    events: list[dict] = []

    async def collect(evt):
        events.append(evt)

    second = await merge_mod.run_merge("L3", "profile", on_event=collect)
    assert second.rewrote is False
    assert second.legacy_l3_refs_migrated == 0
    assert target.read_text(encoding="utf-8") == after_first
    assert "doc_updated" not in {e["stage"] for e in events}
