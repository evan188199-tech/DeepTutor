"""Pure-logic coverage for the consolidator mode package.

Targets the modules the coverage-gaps scan marked zero-test:

* ``modes/_runtime.py`` — language routing, prompt/meta loading, SSE emit,
  thinking-tag stripping, doc load/atomic write.
* ``modes/_shims.py`` — layer selection (L2 surface vs L3 slot), the
  preferences guard, preview-mode rollback of new entries.
* ``modes/audit.py`` — line-index rendering and the cross-surface L2 lookup
  (missing/corrupt files must be skipped).
* ``modes/dedup.py`` — layer→path dispatch, default titles, numbered render.

Everything runs without an LLM or network; the store root is a tmp dir.
"""

from __future__ import annotations

from pathlib import Path
import re
from unittest.mock import AsyncMock

import pytest

from deeptutor.services.memory import paths as paths_mod
from deeptutor.services.memory.consolidator.line_doc import render_view
from deeptutor.services.memory.consolidator.modes import _runtime as rt
from deeptutor.services.memory.consolidator.modes import _shims as shims
from deeptutor.services.memory.consolidator.modes import audit as audit_mod
from deeptutor.services.memory.consolidator.modes import dedup as dedup_mod
from deeptutor.services.memory.consolidator.modes import update as update_mod
from deeptutor.services.memory.document import Document, Entry, parse, serialize
from deeptutor.services.memory.ids import new_entry_id


@pytest.fixture()
def memory_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(paths_mod, "memory_root", lambda: tmp_path)
    (tmp_path / "L2").mkdir(parents=True, exist_ok=True)
    (tmp_path / "L3").mkdir(parents=True, exist_ok=True)
    yield tmp_path


@pytest.fixture(autouse=True)
def fresh_prompt_caches(monkeypatch):
    monkeypatch.setattr(rt, "_PROMPT_CACHE", {})
    monkeypatch.setattr(rt, "_META_CACHE", {})


def _doc_with_entries(*entries: Entry) -> Document:
    sections: dict[str, list[Entry]] = {}
    for e in entries:
        sections.setdefault(e.section, []).append(e)
    return Document(title="chat memory", sections=list(sections.items()))


# ── _runtime: language routing ──────────────────────────────────────────


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("zh", "zh"),
        ("zh-CN", "zh"),
        ("ZH-tw", "zh"),
        ("en", "en"),
        ("en-US", "en"),
        ("fr", "en"),
        ("", "en"),
        (None, "en"),
    ],
)
def test_lang_code_boundaries(language, expected):
    assert rt._lang_code(language) == expected


# ── _runtime: prompt / focus-meta loading ───────────────────────────────


@pytest.mark.parametrize("language", ["en", "zh"])
def test_load_prompt_known_name_returns_system_and_user(language):
    prompt = rt.load_prompt("dedup", language)
    assert set(prompt) == {"system", "user"}
    assert prompt["system"].strip()
    assert prompt["user"].strip()


def test_load_prompt_unknown_language_falls_back_to_en():
    assert rt.load_prompt("dedup", "fr-FR") == rt.load_prompt("dedup", "en")


def test_load_prompt_unknown_name_raises_file_not_found():
    with pytest.raises(FileNotFoundError):
        rt.load_prompt("no_such_prompt", "en")


def test_load_prompt_missing_required_keys_raises(tmp_path, monkeypatch):
    (tmp_path / "en").mkdir()
    (tmp_path / "en" / "half_prompt.yaml").write_text("system: only system\n", encoding="utf-8")
    monkeypatch.setattr(rt, "_PROMPTS_DIR", tmp_path)
    with pytest.raises(RuntimeError, match="missing 'system'/'user'"):
        rt.load_prompt("half_prompt", "en")


def test_load_prompt_caches_per_language_and_name():
    assert rt.load_prompt("dedup", "en") is rt.load_prompt("dedup", "en")
    en = rt.load_prompt("dedup", "en")
    zh = rt.load_prompt("dedup", "zh")
    assert en is not zh


def test_surface_focus_known_surface_and_unknown_fallback():
    focus, sections = rt.surface_focus("en", "chat")
    assert isinstance(focus, str) and focus.strip()
    assert sections == ["Misconceptions", "Mastery", "Topics"]
    assert rt.surface_focus("en", "not-a-surface") == ("", [])


def test_slot_focus_known_slot_and_preferences_fallback():
    focus, sections = rt.slot_focus("en", "recent")
    assert focus.strip()
    assert sections == ["This week", "Earlier"]
    # preferences is intentionally absent from the focus map and from
    # auto-consolidation.
    assert rt.slot_focus("en", "preferences") == ("", [])


def test_load_focus_meta_cached_per_language():
    assert rt.load_focus_meta("en") is rt.load_focus_meta("en")
    assert isinstance(rt.load_focus_meta("en"), dict)


# ── _runtime: SSE emit ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_emit_without_consumer_is_noop():
    assert await rt.emit(None, {"stage": "x"}) is None


@pytest.mark.asyncio
async def test_emit_swallows_consumer_errors():
    seen: list[dict] = []

    async def flaky(event):
        if seen:
            raise RuntimeError("consumer broke")
        seen.append(event)

    await rt.emit(flaky, {"stage": "first"})
    await rt.emit(flaky, {"stage": "second"})  # must not raise
    assert [e["stage"] for e in seen] == ["first"]


# ── _runtime: thinking-tag stripping ────────────────────────────────────


@pytest.mark.parametrize(
    ("delta", "in_block", "expected_out", "expected_state"),
    [
        ("plain answer", False, "plain answer", False),
        ("<think>reasoning</think>final", False, "final", False),
        ("<think>started only", False, "", True),
        ("still hidden", True, "", True),
        ("</think>after", True, "after", False),
        ("<THINK>x</THINK>ok", False, "ok", False),
        ("<thinking>alt</thinking>b", False, "b", False),
        ("a<think></think>b", False, "ab", False),
    ],
)
def test_strip_thinking_delta_table(delta, in_block, expected_out, expected_state):
    assert rt._strip_thinking_delta(delta, in_block) == (expected_out, expected_state)


# ── _runtime: doc load / atomic write / date ────────────────────────────


def test_load_doc_missing_file_returns_default_title(tmp_path):
    doc = rt.load_doc(tmp_path / "absent.md", default_title="chat memory")
    assert doc.title == "chat memory"
    assert doc.all_entries() == []


def test_load_doc_existing_file_parses_entries(memory_dir):
    entry = Entry(id=new_entry_id(), section="Topics", text="alpha", refs=["chat:01"])
    path = memory_dir / "L2" / "chat.md"
    path.write_text(serialize(_doc_with_entries(entry)), encoding="utf-8")
    doc = rt.load_doc(path, default_title="ignored")
    assert [e.id for e in doc.all_entries()] == [entry.id]


@pytest.mark.asyncio
async def test_write_doc_atomic_creates_parents_and_serializes(tmp_path):
    entry = Entry(id=new_entry_id(), section="Topics", text="alpha", refs=[])
    target = tmp_path / "nested" / "dir" / "doc.md"
    await rt.write_doc_atomic(target, _doc_with_entries(entry))
    assert [e.id for e in parse(target.read_text(encoding="utf-8")).all_entries()] == [entry.id]


def test_today_iso_is_utc_date():
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", rt.today_iso())


# ── mode dispatch: update layer validation ─────────────────────────────


@pytest.mark.asyncio
async def test_run_update_rejects_unknown_layer(memory_dir, monkeypatch):
    monkeypatch.setattr(update_mod, "load_memory_settings", lambda: None)
    with pytest.raises(ValueError, match="unknown layer"):
        await update_mod.run_update("L9", "chat")


# ── _shims: layer selection / switching ─────────────────────────────────


@pytest.mark.asyncio
async def test_consolidate_l3_rejects_preferences_slot(memory_dir, monkeypatch):
    fake = AsyncMock(side_effect=AssertionError("must not run"))
    monkeypatch.setattr(shims, "run_update", fake)
    with pytest.raises(ValueError, match="preferences"):
        await shims.consolidate_l3("preferences")
    fake.assert_not_called()


@pytest.mark.asyncio
async def test_consolidate_l2_selects_update_mode_and_maps_result(memory_dir, monkeypatch):
    captured: dict = {}

    async def fake_run_update(layer, key, **kwargs):
        captured.update({"layer": layer, "key": key, **kwargs})
        return update_mod.UpdateResult(
            layer=layer, key=key, chunks_processed=2, facts_added=1, refs_dropped=0
        )

    monkeypatch.setattr(shims, "run_update", fake_run_update)
    result = await shims.consolidate_l2(
        "chat", language="zh-CN", user_label="tester", on_event=None
    )

    assert captured["layer"] == "L2"
    assert captured["key"] == "chat"
    assert captured["language"] == "zh-CN"
    assert captured["user_label"] == "tester"
    assert result.report.accepted is True
    assert result.report.reason == "applied via chunk-update (1 added)"
    assert result.backlog_count == 2
    assert result.proposed_ops == []


def test_to_consolidate_result_no_new_input_reason():
    result = update_mod.UpdateResult(
        layer="L3",
        key="recent",
        chunks_processed=0,
        facts_added=0,
        refs_dropped=0,
        no_new_input=True,
    )
    mapped = shims._to_consolidate_result(result)
    assert mapped.report.reason == "no new input"
    assert mapped.backlog_count == 0


@pytest.mark.asyncio
async def test_consolidate_l3_preview_mode_rolls_back_new_entries(memory_dir, monkeypatch):
    keeper = Entry(id=new_entry_id(), section="Timeline", text="keep me", refs=["chat:01"])
    preview = Entry(id=new_entry_id(), section="Timeline", text="preview only", refs=["chat:02"])
    path = memory_dir / "L3" / "recent.md"
    path.write_text(serialize(_doc_with_entries(keeper, preview)), encoding="utf-8")

    async def fake_run_update(layer, key, **kwargs):
        assert (layer, key) == ("L3", "recent")
        return update_mod.UpdateResult(
            layer=layer,
            key=key,
            chunks_processed=1,
            facts_added=1,
            refs_dropped=0,
            new_entry_ids=[preview.id],
        )

    monkeypatch.setattr(shims, "run_update", fake_run_update)
    result = await shims.consolidate_l3("recent", apply_ops=False)

    assert result.report.accepted is True
    remaining = parse(path.read_text(encoding="utf-8"))
    ids = {e.id for e in remaining.all_entries()}
    assert preview.id not in ids
    assert keeper.id in ids


def test_rollback_new_entries_skips_when_no_ids_or_missing_file(memory_dir):
    entry = Entry(id=new_entry_id(), section="Topics", text="alpha", refs=[])
    path = memory_dir / "L2" / "chat.md"
    original = serialize(_doc_with_entries(entry))
    path.write_text(original, encoding="utf-8")

    # Empty id list is a no-op.
    shims._rollback_new_entries("L2", "chat", [])
    assert path.read_text(encoding="utf-8") == original

    # Missing target file is a no-op as well.
    shims._rollback_new_entries("L2", "quiz", [new_entry_id()])


# ── audit: line index + cross-surface lookup ────────────────────────────


def test_render_line_index_numbers_every_line():
    e1 = Entry(id=new_entry_id(), section="Topics", text="alpha", refs=["chat:01"])
    e2 = Entry(id=new_entry_id(), section="Topics", text="beta", refs=["chat:02"])
    view = render_view(_doc_with_entries(e1, e2))
    rendered = audit_mod._render_line_index(view)
    assert rendered.startswith("# Line-numbered view (LLM-facing):\n")
    body_lines = rendered.splitlines()[1:]
    assert len(body_lines) == len(view.lines)
    for line, body in zip(view.lines, body_lines):
        assert body.split(":", 1)[0].strip() == str(line.number)
        assert body.split(":", 1)[1].strip() == line.text


def test_build_l2_entry_lookup_skips_missing_and_corrupt_files(memory_dir):
    good = Entry(id=new_entry_id(), section="Topics", text="alpha", refs=["chat:01"])
    (memory_dir / "L2" / "chat.md").write_text(serialize(_doc_with_entries(good)), encoding="utf-8")
    (memory_dir / "L2" / "notebook.md").write_bytes(b"\xff\xfe not utf-8")

    lookup = audit_mod._build_l2_entry_lookup()
    assert set(lookup) == {good.id}
    assert lookup[good.id].text == "alpha"


# ── dedup: layer dispatch helpers ───────────────────────────────────────


def test_path_for_maps_layers_to_store_files(memory_dir):
    assert dedup_mod._path_for("L2", "chat") == memory_dir / "L2" / "chat.md"
    assert dedup_mod._path_for("L3", "recent") == memory_dir / "L3" / "recent.md"


def test_path_for_rejects_unknown_layer():
    with pytest.raises(ValueError, match="unknown layer"):
        dedup_mod._path_for("L4", "chat")


@pytest.mark.parametrize(
    ("layer", "key", "expected"),
    [
        ("L2", "chat", "chat memory"),
        ("L2", "book", "book memory"),
        ("L3", "recent", "Recent summary"),
        ("L3", "profile", "User profile"),
        ("L3", "scope", "Knowledge scope"),
        ("L3", "preferences", "Preferences"),
        ("L3", "unknown-slot", "unknown-slot memory"),
    ],
)
def test_default_title_table(layer, key, expected):
    assert dedup_mod._default_title(layer, key) == expected


def test_render_with_numbers_pads_and_numbers_all_lines():
    entries = [
        Entry(id=new_entry_id(), section="Topics", text=f"fact {i}", refs=[]) for i in range(12)
    ]
    view = render_view(_doc_with_entries(*entries))
    rendered = dedup_mod._render_with_numbers(view)
    body = rendered.splitlines()
    assert len(body) == len(view.lines)
    width = max(2, len(str(len(view.lines))))
    assert body[0].startswith(f"{view.lines[0].number:>{width}}: ")
    for line, text in zip(view.lines, body):
        assert text.split(":", 1)[0].strip() == str(line.number)
