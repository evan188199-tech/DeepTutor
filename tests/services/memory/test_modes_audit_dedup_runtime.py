"""Behavior/table-driven tests for the audit / dedup modes and their shared runtime.

Complements ``test_modes.py`` (happy-path E2E) with input/output contracts,
boundaries and failure paths for ``modes/audit.py``, ``modes/dedup.py`` and
``modes/_runtime.py``. The LLM boundary is mocked; chunker, line_doc, doc IO,
undo checkpoints and prompts run for real on a temp memory dir.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from deeptutor.services.memory import paths as paths_mod
from deeptutor.services.memory.consolidator import runs as runs_mod
from deeptutor.services.memory.consolidator.modes import _runtime as rt
from deeptutor.services.memory.consolidator.modes import audit as audit_mod
from deeptutor.services.memory.consolidator.modes import dedup as dedup_mod
from deeptutor.services.memory.consolidator.references import annotate_l2_line_with_evidence
from deeptutor.services.memory.document import Document, Entry, parse, serialize
from deeptutor.services.memory.ids import new_entry_id
from deeptutor.services.memory.settings import (
    DedupSettings,
    MemorySettings,
    MergeSettings,
)
from deeptutor.services.memory.snapshot.entity import Entity


def _memory_settings(iterations: int = 3, *, auto_after_dedup: bool = False) -> MemorySettings:
    return MemorySettings(
        dedup=DedupSettings(iterations=iterations, auto_after_update=False),
        merge=MergeSettings(
            auto_after_update=False, auto_after_audit=False, auto_after_dedup=auto_after_dedup
        ),
    )


@pytest.fixture(autouse=True)
def _fresh_prompt_caches():
    rt._PROMPT_CACHE.clear()
    rt._META_CACHE.clear()
    yield
    rt._PROMPT_CACHE.clear()
    rt._META_CACHE.clear()


@pytest.fixture()
def memory_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(paths_mod, "memory_root", lambda: tmp_path)
    (tmp_path / "L2").mkdir(parents=True, exist_ok=True)
    (tmp_path / "L3").mkdir(parents=True, exist_ok=True)
    (tmp_path / "trace").mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture()
def dedup_settings(monkeypatch):
    def _install(iterations: int = 3, *, auto_after_dedup: bool = False) -> MemorySettings:
        settings = _memory_settings(iterations, auto_after_dedup=auto_after_dedup)
        monkeypatch.setattr(dedup_mod, "load_memory_settings", lambda: settings)
        return settings

    return _install


@pytest.fixture()
def audit_settings(monkeypatch):
    def _install() -> MemorySettings:
        settings = _memory_settings()
        monkeypatch.setattr(audit_mod, "load_memory_settings", lambda: settings)
        return settings

    return _install


def _entity(eid: str, content: str = "user uses spaced repetition with FSRS scheduler.") -> Entity:
    return Entity(
        id=eid,
        label=f"entry {eid}",
        ts="2026-05-19T00:00:00Z",
        content=content,
        metadata={},
        fingerprint="fp",
    )


def _seed_doc(
    path: Path,
    title: str,
    section: str,
    entries: list[tuple[str, str, list[str]]],
) -> list[str]:
    ids = [eid if eid else new_entry_id() for eid, _text, _refs in entries]
    doc = Document(
        title=title,
        sections=[
            (
                section,
                [
                    Entry(id=eid, section=section, text=text, refs=refs)
                    for eid, (_text_t, text, refs) in zip(ids, entries, strict=True)
                ],
            )
        ],
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize(doc), encoding="utf-8")
    return ids


def _bullet_line(user_prompt: str, needle: str) -> int | None:
    """Find the numbered line index of the bullet containing ``needle``."""
    for ln in user_prompt.splitlines():
        s = ln.strip()
        head, sep, rest = s.partition(":")
        if sep and head.strip().isdigit() and rest.lstrip().startswith("- ") and needle in rest:
            return int(head.strip())
    return None


def _collector():
    events: list[dict] = []

    async def on_event(event: dict) -> None:
        events.append(event)

    return events, on_event


def _first(events: list[dict], stage: str) -> dict:
    return next(e for e in events if e.get("stage") == stage)


# ── _runtime: prompts ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("language", "expected_lang"),
    [("zh", "zh"), ("zh-CN", "zh"), ("ZH", "zh"), ("en", "en"), ("fr-FR", "en"), ("", "en")],
)
def test_load_prompt_routes_language_prefix_to_pack(language, expected_lang):
    prompt = rt.load_prompt("audit_l2", language)
    other = rt.load_prompt("audit_l2", "en" if expected_lang == "zh" else "zh")

    assert set(prompt) == {"system", "user"}
    assert prompt["system"] and prompt["user"]
    assert prompt["system"] != other["system"]


def test_load_prompt_unknown_name_raises():
    with pytest.raises(FileNotFoundError):
        rt.load_prompt("no_such_prompt_name", "en")


@pytest.mark.parametrize("content", ["system: only system\n", "- a plain list\n"])
def test_load_prompt_missing_required_keys_raises(tmp_path, monkeypatch, content):
    prompts = tmp_path / "en"
    prompts.mkdir(parents=True)
    (prompts / "broken.yaml").write_text(content, encoding="utf-8")
    monkeypatch.setattr(rt, "_PROMPTS_DIR", tmp_path)

    with pytest.raises(RuntimeError, match="missing 'system'/'user'"):
        rt.load_prompt("broken", "en")


def test_load_prompt_caches_per_language_and_name():
    first = rt.load_prompt("audit_l2", "zh-CN")
    assert rt.load_prompt("audit_l2", "zh-CN") is first
    assert rt.load_prompt("audit_l2", "zh") is first
    assert rt.load_prompt("dedup", "zh-CN") is not first
    assert rt._PROMPT_CACHE == {
        ("zh", "audit_l2"): first,
        ("zh", "dedup"): rt.load_prompt("dedup", "zh-CN"),
    }


# ── _runtime: emit / doc IO ─────────────────────────────────────────────


@pytest.mark.parametrize("scenario", ["no_consumer", "collects", "consumer_raises"])
@pytest.mark.asyncio
async def test_emit_consumer_contract(scenario):
    events, on_event = _collector()

    if scenario == "no_consumer":
        await rt.emit(None, {"stage": "progress"})  # must not raise
        assert events == []
    elif scenario == "collects":
        await rt.emit(on_event, {"stage": "a"})
        await rt.emit(on_event, {"stage": "b"})
        assert [e["stage"] for e in events] == ["a", "b"]
    else:

        async def broken(event: dict) -> None:
            raise ValueError("consumer exploded")

        await rt.emit(broken, {"stage": "a"})  # swallowed
        assert events == []


@pytest.mark.parametrize("seed", ["missing", "existing"])
def test_load_doc_contract(tmp_path, seed):
    path = tmp_path / "L2" / "chat.md"
    eid = new_entry_id()
    if seed == "existing":
        _seed_doc(path, "chat memory", "Topics", [(eid, "hello world", ["chat:01"])])

    doc = rt.load_doc(path, default_title="chat memory")

    if seed == "missing":
        assert doc.title == "chat memory"
        assert doc.all_entries() == []
    else:
        assert doc.title == "chat memory"
        entries = doc.all_entries()
        assert [e.id for e in entries] == [eid]
        assert entries[0].text == "hello world"
        assert entries[0].refs == ["chat:01"]


@pytest.mark.asyncio
async def test_write_doc_atomic_creates_parents_and_roundtrips(tmp_path):
    path = tmp_path / "deep" / "nested" / "L3" / "profile.md"
    doc = Document(
        title="User profile",
        sections=[
            (
                "Profile",
                [Entry(id=new_entry_id(), section="Profile", text="likes tea", refs=["chat:02"])],
            )
        ],
    )

    await rt.write_doc_atomic(path, doc)

    assert path.exists()
    parsed = parse(path.read_text(encoding="utf-8"))
    assert parsed.title == "User profile"
    assert [e.text for e in parsed.all_entries()] == ["likes tea"]
    assert path.parent.is_dir()


@pytest.mark.asyncio
async def test_write_doc_checkpoint_records_undo_and_emits(memory_dir):
    path = memory_dir / "L2" / "chat.md"
    events, on_event = _collector()
    eid = new_entry_id()
    doc1 = Document(
        title="chat memory", sections=[("Topics", [Entry(id=eid, section="Topics", text="v1")])]
    )
    doc2 = Document(
        title="chat memory", sections=[("Topics", [Entry(id=eid, section="Topics", text="v2")])]
    )

    depth = await rt.write_doc_checkpoint(
        path,
        doc1,
        layer="L2",
        key="chat",
        on_event=on_event,
        turn=1,
        label="dedup",
        action="apply_edits",
    )
    assert depth == 0  # no active run → no undo bookkeeping
    assert _first(events, "doc_updated")["undo_depth"] == 0

    run = runs_mod.Run(
        id="run-1",
        layer="L2",
        key="chat",
        mode="dedup",
        params={},
        language="en",
        user_label="tester",
    )
    token = runs_mod._current_run.set(run)
    try:
        depth = await rt.write_doc_checkpoint(
            path,
            doc2,
            layer="L2",
            key="chat",
            on_event=on_event,
            turn=2,
            label="dedup",
            action="apply_edits",
        )
    finally:
        runs_mod._current_run.reset(token)

    assert depth == 1
    assert len(run.undo_stack) == 1
    checkpoint = run.undo_stack[0]
    assert checkpoint.layer == "L2" and checkpoint.key == "chat"
    assert checkpoint.action == "apply_edits" and checkpoint.turn == 2
    assert checkpoint.existed is True
    assert checkpoint.previous_content == serialize(doc1)
    assert path.read_text(encoding="utf-8") == serialize(doc2)
    assert [e for e in events if e["stage"] == "doc_updated"][-1]["undo_depth"] == 1
    assert [e for e in events if e["stage"] == "doc_updated"][-1]["label"] == "dedup"


# ── _runtime: call_llm ──────────────────────────────────────────────────


@pytest.fixture()
def llm_config_ok(monkeypatch):
    monkeypatch.setattr(
        "deeptutor.services.llm.get_llm_config", lambda: SimpleNamespace(model="test-model")
    )


@pytest.mark.asyncio
async def test_call_llm_streaming_success_strips_thinking(llm_config_ok, monkeypatch):
    async def fake_stream(**kwargs):
        assert kwargs["system_prompt"] == "SYS" and kwargs["prompt"] == "USR"
        yield "<think>secret plan</think>Hello "
        yield "world"

    monkeypatch.setattr(rt, "llm_stream", fake_stream)
    events, on_event = _collector()

    response = await rt.call_llm(
        system_prompt="SYS", user_prompt="USR", on_event=on_event, turn=7, label="audit"
    )

    assert response == "Hello world"
    start = _first(events, "llm_io_start")
    assert start["system_prompt"] == "SYS" and start["user_prompt"] == "USR"
    assert start["turn"] == 7 and start["label"] == "audit" and start["model"] == "test-model"
    deltas = [e["delta"] for e in events if e["stage"] == "llm_io_delta"]
    assert deltas == ["Hello ", "world"]
    end = _first(events, "llm_io_end")
    assert end["response"] == "Hello world" and end["error"] is None


@pytest.mark.asyncio
async def test_call_llm_stream_failure_falls_back_to_complete(llm_config_ok, monkeypatch):
    async def broken_stream(**kwargs):
        raise RuntimeError("provider has no streaming")
        yield  # pragma: no cover

    async def fake_complete(**kwargs):
        assert kwargs["prompt"] == "USR" and kwargs["system_prompt"] == "SYS"
        return "<think>junk</think>Fallback text"

    monkeypatch.setattr(rt, "llm_stream", broken_stream)
    monkeypatch.setattr(rt, "llm_complete", fake_complete)
    events, on_event = _collector()

    response = await rt.call_llm(
        system_prompt="SYS", user_prompt="USR", on_event=on_event, turn=1, label="dedup"
    )

    assert response == "Fallback text"
    deltas = [e["delta"] for e in events if e["stage"] == "llm_io_delta"]
    assert deltas == ["Fallback text"]
    end = _first(events, "llm_io_end")
    assert end["response"] == "Fallback text" and end["error"] is None


@pytest.mark.asyncio
async def test_call_llm_total_failure_returns_empty_string(llm_config_ok, monkeypatch):
    async def broken_stream(**kwargs):
        raise RuntimeError("no streaming")
        yield  # pragma: no cover

    async def broken_complete(**kwargs):
        raise RuntimeError("complete exploded")

    monkeypatch.setattr(rt, "llm_stream", broken_stream)
    monkeypatch.setattr(rt, "llm_complete", broken_complete)
    events, on_event = _collector()

    response = await rt.call_llm(system_prompt="S", user_prompt="U", on_event=on_event, turn=3)

    assert response == ""
    assert [e["stage"] for e in events] == ["llm_io_start", "llm_io_end"]
    end = _first(events, "llm_io_end")
    assert end["response"] == "" and end["error"] == "complete exploded"


@pytest.mark.parametrize(
    ("delta", "in_block", "expected_out", "expected_state"),
    [
        ("plain text", False, "plain text", False),
        ("<think>hidden</think>visible", False, "visible", False),
        ("<think>still open", False, "", True),
        ("still hidden", True, "", True),
        ("</think>after close", True, "after close", False),
        ("<THINKING>case</THINKING>ok", False, "ok", False),
        ("keep<thinking>drop", False, "keep", True),
        ("<think>a</think>x<think>b</think>z", False, "xz", False),
    ],
)
def test_strip_thinking_delta_table(delta, in_block, expected_out, expected_state):
    assert rt._strip_thinking_delta(delta, in_block) == (expected_out, expected_state)


# ── dedup mode ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(("layer", "key"), [("L2", "chat"), ("L3", "profile")])
@pytest.mark.asyncio
async def test_run_dedup_missing_doc_short_circuits(memory_dir, dedup_settings, layer, key):
    dedup_settings()
    llm_calls: list[int] = []

    async def fake_llm(*args, **kwargs):
        llm_calls.append(1)
        return '{"edits": []}'

    with patch("deeptutor.services.memory.consolidator.modes.dedup.call_llm", side_effect=fake_llm):
        events, on_event = _collector()
        result = await dedup_mod.run_dedup(layer, key, on_event=on_event)

    assert (result.layer, result.key) == (layer, key)
    assert result.iterations_run == 0
    assert result.edits_applied == 0
    assert result.converged_early is True
    assert llm_calls == []
    assert events == [{"stage": "done", "no_doc": True, "edits_applied": 0}]
    assert not (memory_dir / layer / f"{key}.md").exists()


@pytest.mark.asyncio
async def test_run_dedup_empty_doc_short_circuits(memory_dir, dedup_settings):
    dedup_settings()
    path = memory_dir / "L2" / "chat.md"
    _seed_doc(path, "chat memory", "Topics", [])
    llm_calls: list[int] = []

    async def fake_llm(*args, **kwargs):
        llm_calls.append(1)
        return '{"edits": []}'

    with patch("deeptutor.services.memory.consolidator.modes.dedup.call_llm", side_effect=fake_llm):
        events, on_event = _collector()
        result = await dedup_mod.run_dedup("L2", "chat", on_event=on_event)

    assert result.iterations_run == 0 and result.edits_applied == 0
    assert result.converged_early is True
    assert llm_calls == []
    assert events[-1] == {"stage": "done", "no_doc": True, "edits_applied": 0}
    assert parse(path.read_text(encoding="utf-8")).all_entries() == []


@pytest.mark.parametrize("layer", ["L1", "l2"])
@pytest.mark.asyncio
async def test_run_dedup_unknown_layer_raises(memory_dir, dedup_settings, layer):
    dedup_settings()
    llm_calls: list[int] = []

    async def fake_llm(*args, **kwargs):
        llm_calls.append(1)
        return '{"edits": []}'

    with patch("deeptutor.services.memory.consolidator.modes.dedup.call_llm", side_effect=fake_llm):
        with pytest.raises(ValueError, match="unknown layer"):
            await dedup_mod.run_dedup(layer, "chat")

    assert llm_calls == []


@pytest.mark.asyncio
async def test_run_dedup_replace_then_converge(memory_dir, dedup_settings):
    dedup_settings(iterations=3)
    path = memory_dir / "L2" / "chat.md"
    _seed_doc(
        path,
        "chat memory",
        "Topics",
        [("", "alpha", ["chat:01"]), ("", "beta", ["chat:02"])],
    )
    calls: list[int] = []

    async def fake_llm(*, system_prompt, user_prompt, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            line = _bullet_line(user_prompt, "alpha")
            assert line is not None
            return (
                '{"edits": [{"op": "replace", "line": '
                + str(line)
                + ', "new_text": "alpha merged", "refs": ["chat:01"], "reason": "merge"}]}'
            )
        return '{"edits": []}'

    with patch("deeptutor.services.memory.consolidator.modes.dedup.call_llm", side_effect=fake_llm):
        events, on_event = _collector()
        result = await dedup_mod.run_dedup(
            "L2", "chat", language="en", user_label="tester", on_event=on_event
        )

    assert result.edits_applied == 1
    assert result.converged_early is True
    assert result.iterations_run == 2
    assert len(calls) == 2
    texts = [e.text for e in parse(path.read_text(encoding="utf-8")).all_entries()]
    assert texts == ["alpha merged", "beta"]
    progress = _first(events, "progress")
    assert progress == {"stage": "progress", "mode": "dedup", "turn": 1, "total": 3, "lines": 5}
    applied = _first(events, "op_applied")
    assert applied["applied"] == 1 and applied["rejected"] == 0
    assert any(e["stage"] == "doc_updated" for e in events)
    done = _first(events, "done")
    assert done == {
        "stage": "done",
        "edits_applied": 1,
        "iterations_run": 2,
        "converged_early": True,
    }


@pytest.mark.parametrize(("iterations", "expected_calls"), [(1, 1), (2, 2)])
@pytest.mark.asyncio
async def test_run_dedup_iterations_is_upper_bound(
    memory_dir, dedup_settings, iterations, expected_calls
):
    dedup_settings(iterations=iterations)
    path = memory_dir / "L2" / "chat.md"
    _seed_doc(
        path, "chat memory", "Topics", [("", "alpha", ["chat:01"]), ("", "beta", ["chat:02"])]
    )
    calls: list[int] = []

    async def fake_llm(*, system_prompt, user_prompt, **kwargs):
        calls.append(1)
        line = _bullet_line(user_prompt, "alpha")
        assert line is not None
        return (
            '{"edits": [{"op": "replace", "line": '
            + str(line)
            + ', "new_text": "alpha v'
            + str(len(calls))
            + '", "refs": ["chat:01"], "reason": "polish"}]}'
        )

    with patch("deeptutor.services.memory.consolidator.modes.dedup.call_llm", side_effect=fake_llm):
        result = await dedup_mod.run_dedup("L2", "chat")

    assert len(calls) == expected_calls
    assert result.iterations_run == expected_calls
    assert result.edits_applied == expected_calls
    assert result.converged_early is False


@pytest.mark.asyncio
async def test_run_dedup_rejected_edits_do_not_converge(memory_dir, dedup_settings):
    dedup_settings(iterations=1)
    path = memory_dir / "L2" / "chat.md"
    _seed_doc(
        path,
        "chat memory",
        "Topics",
        [("", "alpha", ["chat:01"]), ("", "beta", ["chat:02"])],
    )

    async def fake_llm(*, system_prompt, user_prompt, **kwargs):
        return (
            '{"edits": [{"op": "replace", "line": 999, "new_text": "hallucinated", '
            '"refs": ["chat:01"], "reason": "bad line"}]}'
        )

    with patch("deeptutor.services.memory.consolidator.modes.dedup.call_llm", side_effect=fake_llm):
        events, on_event = _collector()
        result = await dedup_mod.run_dedup("L2", "chat", on_event=on_event)

    assert result.edits_applied == 0
    assert result.converged_early is False
    assert result.iterations_run == 1
    applied = _first(events, "op_applied")
    assert applied["applied"] == 0 and applied["rejected"] == 1
    assert not any(e["stage"] == "doc_updated" for e in events)
    texts = [e.text for e in parse(path.read_text(encoding="utf-8")).all_entries()]
    assert texts == ["alpha", "beta"]


@pytest.mark.asyncio
async def test_run_dedup_invalid_llm_selection_degrades(
    memory_dir, dedup_settings, monkeypatch, caplog
):
    dedup_settings()
    path = memory_dir / "L2" / "chat.md"
    _seed_doc(path, "chat memory", "Topics", [("", "alpha", ["chat:01"])])
    reset_calls: list[object] = []

    def _boom(selection):
        raise RuntimeError("unresolvable selection")

    def _spy(token):
        reset_calls.append(token)

    monkeypatch.setattr("deeptutor.services.model_selection.runtime.activate_llm_selection", _boom)
    monkeypatch.setattr("deeptutor.services.model_selection.runtime.reset_llm_selection", _spy)

    async def fake_llm(*args, **kwargs):
        return '{"edits": []}'

    with patch("deeptutor.services.memory.consolidator.modes.dedup.call_llm", side_effect=fake_llm):
        with caplog.at_level(
            logging.WARNING, logger="deeptutor.services.memory.consolidator.modes.dedup"
        ):
            result = await dedup_mod.run_dedup(
                "L2", "chat", llm_selection={"provider": "does-not-exist"}
            )

    assert result.converged_early is True
    assert reset_calls == [None]
    assert any("ignoring unresolvable llm_selection" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_run_dedup_auto_merge_trigger(memory_dir, dedup_settings, monkeypatch):
    dedup_settings(iterations=1, auto_after_dedup=True)
    path = memory_dir / "L2" / "chat.md"
    _seed_doc(path, "chat memory", "Topics", [("", "alpha", ["chat:01"])])
    merge_calls: list[tuple] = []

    async def fake_merge(layer, key, *, language, user_label, on_event):
        merge_calls.append((layer, key, language, user_label, on_event is not None))

    monkeypatch.setattr("deeptutor.services.memory.consolidator.modes.merge.run_merge", fake_merge)

    async def fake_llm(*args, **kwargs):
        return '{"edits": []}'

    with patch("deeptutor.services.memory.consolidator.modes.dedup.call_llm", side_effect=fake_llm):
        result = await dedup_mod.run_dedup("L2", "chat", user_label="tester")

    assert result.converged_early is True
    assert merge_calls == [("L2", "chat", "en", "tester", False)]


# ── audit mode ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("layer", ["L1", "l2"])
@pytest.mark.asyncio
async def test_run_audit_unknown_layer_raises(memory_dir, audit_settings, layer):
    audit_settings()
    llm_calls: list[int] = []

    async def fake_llm(*args, **kwargs):
        llm_calls.append(1)
        return '{"edits": []}'

    with patch("deeptutor.services.memory.consolidator.modes.audit.call_llm", side_effect=fake_llm):
        with pytest.raises(ValueError, match="unknown layer"):
            await audit_mod.run_audit(layer, "chat")

    assert llm_calls == []


@pytest.mark.asyncio
async def test_run_audit_l3_preferences_rejected(memory_dir, audit_settings):
    audit_settings()
    with pytest.raises(ValueError, match="preferences"):
        await audit_mod.run_audit("L3", "preferences")


@pytest.mark.parametrize(("layer", "key"), [("L2", "chat"), ("L3", "profile")])
@pytest.mark.asyncio
async def test_run_audit_missing_doc_short_circuits(memory_dir, audit_settings, layer, key):
    audit_settings()
    llm_calls: list[int] = []

    async def fake_llm(*args, **kwargs):
        llm_calls.append(1)
        return '{"edits": []}'

    with patch("deeptutor.services.memory.consolidator.modes.audit.call_llm", side_effect=fake_llm):
        events, on_event = _collector()
        result = await audit_mod.run_audit(layer, key, budget=1, on_event=on_event)

    assert (result.layer, result.key) == (layer, key)
    assert result.no_doc is True
    assert result.chunks_processed == 0
    assert result.edits_applied == 0 and result.edits_rejected == 0
    assert llm_calls == []
    assert events == [{"stage": "done", "no_doc": True}]


@pytest.mark.asyncio
async def test_run_audit_l2_mixed_apply_and_reject(memory_dir, audit_settings, monkeypatch):
    audit_settings()
    path = memory_dir / "L2" / "chat.md"
    _seed_doc(
        path,
        "chat memory",
        "Topics",
        [("", "claims X", ["chat:01ABC"]), ("", "stable fact", ["chat:01DEF"])],
    )
    monkeypatch.setattr(
        "deeptutor.services.memory.consolidator.modes.audit.snap.read_snapshot",
        lambda surface: [
            _entity("01ABC", content="the user actually said Y, not X"),
            _entity("01DEF"),
        ],
    )
    calls: list[int] = []

    async def fake_llm(*, system_prompt, user_prompt, **kwargs):
        calls.append(1)
        line = _bullet_line(user_prompt, "claims X")
        assert line is not None
        return (
            '{"edits": ['
            '{"op": "replace", "line": 999, "new_text": "hallucinated", "refs": ["chat:01ABC"], "reason": "bad"}, '
            '{"op": "replace", "line": '
            + str(line)
            + ', "new_text": "claims Y", "refs": ["chat:01ABC"], "reason": "evidence"}'
            "]}"
        )

    with patch("deeptutor.services.memory.consolidator.modes.audit.call_llm", side_effect=fake_llm):
        events, on_event = _collector()
        result = await audit_mod.run_audit("L2", "chat", budget=1, on_event=on_event)

    assert len(calls) == 1
    assert result.chunks_processed == 1
    assert result.edits_applied == 1
    assert result.edits_rejected == 1
    assert result.no_doc is False
    texts = [e.text for e in parse(path.read_text(encoding="utf-8")).all_entries()]
    assert texts == ["claims Y", "stable fact"]
    chunked = _first(events, "chunked")
    assert chunked["chunks"] == 1 and chunked["budget"] == 1
    applied = _first(events, "op_applied")
    assert applied["op"] == "replace" and applied["turn"] == 1
    rejected = _first(events, "op_rejected")
    assert rejected["op"] == "replace"
    assert any(e["stage"] == "doc_updated" for e in events)
    done = _first(events, "done")
    assert (
        done["edits_applied"] == 1 and done["edits_rejected"] == 1 and done["chunks_processed"] == 1
    )


@pytest.mark.asyncio
async def test_run_audit_l3_replaces_with_l2_evidence(memory_dir, audit_settings):
    audit_settings()
    l2_id = new_entry_id()
    _seed_doc(
        memory_dir / "L2" / "chat.md",
        "chat memory",
        "Topics",
        [(l2_id, "User uses FSRS for review", ["chat:01ABC"])],
    )
    l3_path = memory_dir / "L3" / "profile.md"
    _seed_doc(
        l3_path,
        "User profile",
        "Profile",
        [(new_entry_id(), "User prefers simplified Chinese", [l2_id])],
    )
    prompts: list[str] = []

    async def fake_llm(*, system_prompt, user_prompt, **kwargs):
        prompts.append(user_prompt)
        line = _bullet_line(user_prompt, "simplified Chinese")
        assert line is not None
        return (
            '{"edits": [{"op": "replace", "line": '
            + str(line)
            + ', "new_text": "User prefers Traditional Chinese", "refs": ["'
            + l2_id
            + '"], "reason": "matches L2 evidence"}]}'
        )

    with patch("deeptutor.services.memory.consolidator.modes.audit.call_llm", side_effect=fake_llm):
        result = await audit_mod.run_audit("L3", "profile", budget=1)

    assert result.edits_applied == 1 and result.chunks_processed == 1
    texts = [e.text for e in parse(l3_path.read_text(encoding="utf-8")).all_entries()]
    assert texts == ["User prefers Traditional Chinese"]
    assert prompts and l2_id in prompts[0] and "User uses FSRS for review" in prompts[0]


@pytest.mark.asyncio
async def test_run_audit_invalid_llm_selection_degrades(
    memory_dir, audit_settings, monkeypatch, caplog
):
    audit_settings()
    path = memory_dir / "L2" / "chat.md"
    _seed_doc(path, "chat memory", "Topics", [("m_a", "alpha", ["chat:01ABC"])])
    monkeypatch.setattr(
        "deeptutor.services.memory.consolidator.modes.audit.snap.read_snapshot",
        lambda surface: [_entity("01ABC")],
    )
    reset_calls: list[object] = []

    def _boom(selection):
        raise RuntimeError("unresolvable selection")

    def _spy(token):
        reset_calls.append(token)

    monkeypatch.setattr("deeptutor.services.model_selection.runtime.activate_llm_selection", _boom)
    monkeypatch.setattr("deeptutor.services.model_selection.runtime.reset_llm_selection", _spy)

    async def fake_llm(*args, **kwargs):
        return '{"edits": []}'

    with patch("deeptutor.services.memory.consolidator.modes.audit.call_llm", side_effect=fake_llm):
        with caplog.at_level(
            logging.WARNING, logger="deeptutor.services.memory.consolidator.modes.audit"
        ):
            result = await audit_mod.run_audit(
                "L2", "chat", budget=1, llm_selection={"provider": "nope"}
            )

    assert result.chunks_processed == 1 and result.edits_applied == 0
    assert reset_calls == [None]
    assert any("ignoring unresolvable llm_selection" in r.message for r in caplog.records)


def test_build_l2_entry_lookup_skips_corrupt_and_missing(memory_dir):
    good_id = new_entry_id()
    _seed_doc(
        memory_dir / "L2" / "chat.md",
        "chat memory",
        "Topics",
        [(good_id, "chat fact", ["chat:01ABC"])],
    )
    (memory_dir / "L2" / "kb.md").write_bytes(b"\xff\xfe\xff not valid utf-8")

    lookup = audit_mod._build_l2_entry_lookup()

    assert list(lookup) == [good_id]
    assert lookup[good_id].text == "chat fact"


def test_build_annotated_l2_includes_evidence_and_ranges():
    entry = Entry(id="m_a", section="Topics", text="claims X", refs=["chat:01ABC"])
    doc = Document(title="chat memory", sections=[("Topics", [entry])])
    lookup = {"01ABC": _entity("01ABC", content="raw trace text")}

    text, ranges = audit_mod._build_annotated_l2(doc, "chat", lookup)

    assert text.startswith("# Line-numbered view (LLM-facing):")
    assert " 4: - claims X [^m_a]" in text
    block = annotate_l2_line_with_evidence(4, entry, surface="chat", entity_lookup=lookup)
    assert block in text
    assert "raw trace text" in text  # evidence is embedded without truncation
    assert len(ranges) == 1
    start, end = ranges[0]
    assert text[start:end] == block
