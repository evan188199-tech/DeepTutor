"""Contract tests for the legacy-API shims in ``modes._shims``.

``consolidate_l2`` / ``consolidate_l3`` are thin compatibility wrappers
around ``modes.update.run_update`` (with a best-effort preview rollback
for ``apply_ops=False``). These tests pin the forwarding contract, the
``UpdateResult`` → ``ConsolidateResult`` alias mapping, and the
``_rollback_new_entries`` file-level fallback behaviour on a temp memory
dir. No LLM is involved: ``run_update`` is replaced at the shim boundary.

Dedup note: pipeline-internal behaviour (chunking, ref filtering, meta)
is covered by ``tests/services/memory/test_modes.py``; waiter semantics
by ``test_consolidator.py``. Here we only pin the shim surface.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.services.memory import paths as paths_mod
from deeptutor.services.memory.consolidator.modes import _shims
from deeptutor.services.memory.consolidator.modes._shims import (
    ConsolidateResult,
    _rollback_new_entries,
    consolidate_l2,
    consolidate_l3,
)
from deeptutor.services.memory.consolidator.modes.update import UpdateResult
from deeptutor.services.memory.document import Document, Entry, parse, serialize
from deeptutor.services.memory.ids import new_entry_id


@pytest.fixture()
def memory_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(paths_mod, "memory_root", lambda: tmp_path)
    (tmp_path / "L2").mkdir(parents=True, exist_ok=True)
    (tmp_path / "L3").mkdir(parents=True, exist_ok=True)
    yield tmp_path


def _result(
    *,
    layer: str,
    key: str,
    chunks_processed: int = 0,
    facts_added: int = 0,
    new_entry_ids: list[str] | None = None,
    no_new_input: bool = False,
) -> UpdateResult:
    return UpdateResult(
        layer=layer,
        key=key,
        chunks_processed=chunks_processed,
        facts_added=facts_added,
        refs_dropped=0,
        new_entry_ids=new_entry_ids or [],
        no_new_input=no_new_input,
    )


def _seed_doc(path: Path, texts: list[str]) -> list[str]:
    ids = [new_entry_id() for _ in texts]
    doc = Document(
        title=path.stem + " memory",
        sections=[
            ("Topics", [Entry(id=i, section="Topics", text=t, refs=[]) for i, t in zip(ids, texts)])
        ],
    )
    path.write_text(serialize(doc), encoding="utf-8")
    return ids


# ── forwarding: shim → run_update ───────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("shim", "layer"),
    [
        (consolidate_l2, "L2"),
        (consolidate_l3, "L3"),
    ],
)
async def test_shims_forward_layer_and_kwargs(shim, layer, monkeypatch):
    captured: dict = {}

    async def fake_run_update(run_layer, key, **kwargs):
        captured["layer"] = run_layer
        captured["key"] = key
        captured["kwargs"] = kwargs
        return _result(
            layer=run_layer, key=key, facts_added=2, chunks_processed=3, new_entry_ids=["X1", "X2"]
        )

    async def on_event(event):  # identity must be passed through untouched
        return None

    monkeypatch.setattr(_shims, "run_update", fake_run_update)
    got = await shim(
        "chat" if layer == "L2" else "profile", language="zh", user_label="u1", on_event=on_event
    )

    assert captured["layer"] == layer
    assert captured["kwargs"]["language"] == "zh"
    assert captured["kwargs"]["user_label"] == "u1"
    assert captured["kwargs"]["on_event"] is on_event
    assert isinstance(got, ConsolidateResult)


@pytest.mark.asyncio
async def test_consolidate_l3_preferences_rejected_before_run_update(monkeypatch):
    called: list = []

    async def fake_run_update(*args, **kwargs):
        called.append(1)
        return _result(layer="L3", key="preferences")

    monkeypatch.setattr(_shims, "run_update", fake_run_update)
    with pytest.raises(ValueError, match="preferences"):
        await consolidate_l3("preferences")
    assert called == []


# ── alias mapping: UpdateResult → ConsolidateResult ────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("no_new_input", "facts_added", "chunks", "expected_reason"),
    [
        (True, 0, 0, "no new input"),
        (False, 3, 2, "applied via chunk-update (3 added)"),
        (False, 0, 1, "applied via chunk-update (0 added)"),
    ],
)
async def test_result_alias_mapping_table(
    no_new_input, facts_added, chunks, expected_reason, monkeypatch
):
    async def fake_run_update(layer, key, **kwargs):
        return _result(
            layer=layer,
            key=key,
            chunks_processed=chunks,
            facts_added=facts_added,
            no_new_input=no_new_input,
        )

    monkeypatch.setattr(_shims, "run_update", fake_run_update)
    got = await consolidate_l2("chat")
    assert got.report.accepted is True
    assert got.report.reason == expected_reason
    assert got.report.results == []
    assert got.backlog_count == chunks
    assert got.proposed_ops == []


# ── apply_ops preview: rollback only when apply_ops=False ──────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("apply_ops", [True, False])
async def test_apply_ops_toggle_controls_rollback(memory_dir, apply_ops, monkeypatch):
    path = memory_dir / "L2" / "chat.md"
    keep, added = _seed_doc(path, ["keep me", "brand new fact"])

    async def fake_run_update(layer, key, **kwargs):
        return _result(layer=layer, key=key, new_entry_ids=[added])

    monkeypatch.setattr(_shims, "run_update", fake_run_update)
    await consolidate_l2("chat", apply_ops=apply_ops)

    doc = parse(path.read_text(encoding="utf-8"))
    texts = [e.text for e in doc.all_entries()]
    if apply_ops:
        assert "brand new fact" in texts  # real write stays
    else:
        assert "brand new fact" not in texts  # preview rolled the id back
    assert "keep me" in texts


@pytest.mark.asyncio
async def test_l3_preview_rollback_targets_slot_file(memory_dir, monkeypatch):
    path = memory_dir / "L3" / "profile.md"
    keep, added = _seed_doc(path, ["old profile line", "new profile line"])

    async def fake_run_update(layer, key, **kwargs):
        assert key == "profile"
        return _result(layer=layer, key=key, new_entry_ids=[added])

    monkeypatch.setattr(_shims, "run_update", fake_run_update)
    await consolidate_l3("profile", apply_ops=False)

    doc = parse(path.read_text(encoding="utf-8"))
    assert [e.id for e in doc.all_entries()] == [keep]


# ── _rollback_new_entries fallback behaviour ───────────────────────────


@pytest.mark.parametrize(
    ("layer", "filename"),
    [("L2", "L2/chat.md"), ("L3", "L3/scope.md")],
)
def test_rollback_maps_layer_to_file(memory_dir, layer, filename):
    path = memory_dir / filename
    ids = _seed_doc(path, ["a", "b", "c"])
    _rollback_new_entries(layer, path.stem, [ids[0], ids[2]])

    doc = parse(path.read_text(encoding="utf-8"))
    remaining = [e.text for e in doc.all_entries()]
    assert remaining == ["b"]


def test_rollback_unknown_ids_are_best_effort(memory_dir):
    path = memory_dir / "L2" / "notebook.md"
    _ids = _seed_doc(path, ["kept entry", "preview entry"])
    _rollback_new_entries("L2", "notebook", [_ids[1], "01UNKNOWN000000000000000000"])

    doc = parse(path.read_text(encoding="utf-8"))
    assert [e.text for e in doc.all_entries()] == ["kept entry"]


def test_rollback_noop_without_ids_or_file(memory_dir):
    path = memory_dir / "L2" / "book.md"
    ids = _seed_doc(path, ["safe"])

    _rollback_new_entries("L2", "book", [])  # empty id list → untouched
    assert [e.text for e in parse(path.read_text(encoding="utf-8")).all_entries()] == ["safe"]

    _rollback_new_entries("L2", "quiz", ["01MISSING"])  # no such file → no error
    assert not (memory_dir / "L2" / "quiz.md").exists()

    doc = parse(path.read_text(encoding="utf-8"))
    assert [e.id for e in doc.all_entries()] == ids
