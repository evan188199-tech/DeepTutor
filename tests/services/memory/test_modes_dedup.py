"""Dedup-mode contract tests (run_dedup / DedupResult).

Complements the two dedup cases in ``test_modes.py`` with the missing-doc
and empty-doc no-op contracts, iteration-cap and early-converge bounds,
rejected-edit degradation, L3 layer handling, merge auto-run wiring,
llm_selection resolution/reset (success, unresolvable, inner failure)
and the emitted event stream. The LLM is mocked at the ``call_llm``
boundary; everything else runs for real on a temp memory dir.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deeptutor.services.memory import paths as paths_mod
from deeptutor.services.memory.consolidator.modes import dedup as dedup_mod
from deeptutor.services.memory.consolidator.modes import merge as merge_mod
from deeptutor.services.memory.document import Document, Entry, parse, serialize
from deeptutor.services.memory.ids import new_entry_id


@pytest.fixture()
def memory_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(paths_mod, "memory_root", lambda: tmp_path)
    (tmp_path / "L2").mkdir(parents=True, exist_ok=True)
    (tmp_path / "L3").mkdir(parents=True, exist_ok=True)
    (tmp_path / "trace").mkdir(parents=True, exist_ok=True)
    yield tmp_path


def _l2_doc(texts: list[str], refs: list[str] | None = None) -> Document:
    ids = [new_entry_id() for _ in texts]
    refs = refs or [f"chat:{i:02d}" for i in range(1, len(texts) + 1)]
    return Document(
        title="chat memory",
        sections=[
            (
                "Topics",
                [
                    Entry(id=ids[i], section="Topics", text=texts[i], refs=[refs[i]])
                    for i in range(len(texts))
                ],
            )
        ],
    )


def _seed_l2(memory_dir: Path, name: str, doc: Document) -> Path:
    path = memory_dir / "L2" / f"{name}.md"
    path.write_text(serialize(doc), encoding="utf-8")
    return path


def _bullet_lines(user_prompt: str, needle: str) -> list[int]:
    out = []
    for ln in user_prompt.splitlines():
        if needle in ln and ln.lstrip()[:2].rstrip(":").isdigit():
            out.append(int(ln.strip().split(":")[0]))
    return out


def _dedup_settings(iterations: int = 3, auto_after_dedup: bool = False):
    from deeptutor.services.memory.settings import (
        DedupSettings,
        MemorySettings,
        MergeSettings,
    )

    return MemorySettings(
        dedup=DedupSettings(iterations=iterations, auto_after_update=False),
        merge=MergeSettings(auto_after_dedup=auto_after_dedup),
    )


async def _collect_events(events: list[dict]):
    async def on_event(event: dict) -> None:
        events.append(event)

    return on_event


def _stage_names(events: list[dict]) -> list[str]:
    return [e["stage"] for e in events if "stage" in e]


async def _llm_empty(*args, **kwargs) -> str:
    return '{"edits": []}'


@pytest.mark.asyncio
async def test_dedup_missing_doc_is_noop(memory_dir, monkeypatch):
    events: list[dict] = []
    llm_calls: list[int] = []

    async def fake_llm(*args, **kwargs):
        llm_calls.append(1)
        return '{"edits": []}'

    with (
        patch("deeptutor.services.memory.consolidator.modes.dedup.call_llm", side_effect=fake_llm),
        patch.object(dedup_mod, "load_memory_settings", return_value=_dedup_settings()),
    ):
        result = await dedup_mod.run_dedup("L2", "chat", on_event=await _collect_events(events))

    assert llm_calls == []
    assert result.layer == "L2"
    assert result.key == "chat"
    assert result.iterations_run == 0
    assert result.edits_applied == 0
    assert result.converged_early is True
    done = [e for e in events if e.get("stage") == "done"]
    assert done == [{"stage": "done", "no_doc": True, "edits_applied": 0}]


@pytest.mark.asyncio
async def test_dedup_empty_doc_is_noop(memory_dir, monkeypatch):
    path = memory_dir / "L2" / "chat.md"
    path.write_text("# chat memory\n", encoding="utf-8")

    llm_calls: list[int] = []

    async def fake_llm(*args, **kwargs):
        llm_calls.append(1)
        return '{"edits": []}'

    with (
        patch("deeptutor.services.memory.consolidator.modes.dedup.call_llm", side_effect=fake_llm),
        patch.object(dedup_mod, "load_memory_settings", return_value=_dedup_settings()),
    ):
        result = await dedup_mod.run_dedup("L2", "chat")

    assert llm_calls == []
    assert result.iterations_run == 0
    assert result.edits_applied == 0
    assert result.converged_early is True
    assert path.read_text(encoding="utf-8") == "# chat memory\n"


@pytest.mark.asyncio
async def test_dedup_unknown_layer_raises_value_error(memory_dir, monkeypatch):
    with patch.object(dedup_mod, "load_memory_settings", return_value=_dedup_settings()):
        with pytest.raises(ValueError, match="unknown layer"):
            await dedup_mod.run_dedup("L9", "chat")

    assert list((memory_dir / "L2").glob("*.md")) == []


@pytest.mark.asyncio
async def test_dedup_zero_iterations_disables_pass(memory_dir, monkeypatch):
    _seed_l2(memory_dir, "chat", _l2_doc(["alpha", "alpha"]))
    path = memory_dir / "L2" / "chat.md"
    before = path.read_text(encoding="utf-8")

    llm_calls: list[int] = []

    async def fake_llm(*args, **kwargs):
        llm_calls.append(1)
        return '{"edits": []}'

    with (
        patch("deeptutor.services.memory.consolidator.modes.dedup.call_llm", side_effect=fake_llm),
        patch.object(dedup_mod, "load_memory_settings", return_value=_dedup_settings(iterations=0)),
    ):
        result = await dedup_mod.run_dedup("L2", "chat")

    assert llm_calls == []
    assert result.iterations_run == 0
    assert result.edits_applied == 0
    assert result.converged_early is False
    assert path.read_text(encoding="utf-8") == before


@pytest.mark.asyncio
async def test_dedup_unparseable_llm_payload_converges_early(memory_dir, monkeypatch):
    _seed_l2(memory_dir, "chat", _l2_doc(["alpha", "beta"]))

    async def fake_llm(*args, **kwargs):
        return "I could not produce JSON, sorry."

    with (
        patch("deeptutor.services.memory.consolidator.modes.dedup.call_llm", side_effect=fake_llm),
        patch.object(dedup_mod, "load_memory_settings", return_value=_dedup_settings(iterations=4)),
    ):
        result = await dedup_mod.run_dedup("L2", "chat")

    assert result.converged_early is True
    assert result.iterations_run == 1
    assert result.edits_applied == 0


@pytest.mark.asyncio
async def test_dedup_rejected_edits_do_not_write_or_converge(memory_dir, monkeypatch):
    path = _seed_l2(memory_dir, "chat", _l2_doc(["alpha", "beta"]))
    before = path.read_text(encoding="utf-8")
    events: list[dict] = []
    calls = {"n": 0}

    async def fake_llm(*, system_prompt, user_prompt, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return json.dumps(
                {
                    "edits": [
                        {
                            "op": "replace",
                            "line": 999,
                            "new_text": "hallucinated",
                            "refs": ["chat:01"],
                            "reason": "out of range",
                        }
                    ]
                }
            )
        return '{"edits": []}'

    with (
        patch("deeptutor.services.memory.consolidator.modes.dedup.call_llm", side_effect=fake_llm),
        patch.object(dedup_mod, "load_memory_settings", return_value=_dedup_settings(iterations=3)),
    ):
        result = await dedup_mod.run_dedup("L2", "chat", on_event=await _collect_events(events))

    assert calls["n"] == 2
    assert result.converged_early is True
    assert result.iterations_run == 2
    assert result.edits_applied == 0
    assert path.read_text(encoding="utf-8") == before
    op = next(e for e in events if e.get("stage") == "op_applied")
    assert op["applied"] == 0
    assert op["rejected"] == 1
    assert all(e.get("stage") != "doc_updated" for e in events)


@pytest.mark.asyncio
async def test_dedup_replace_and_delete_batch_merges_duplicates(memory_dir, monkeypatch):
    path = _seed_l2(memory_dir, "chat", _l2_doc(["loves FSRS", "loves FSRS"]))
    events: list[dict] = []
    calls = {"n": 0}

    async def fake_llm(*, system_prompt, user_prompt, **kwargs):
        calls["n"] += 1
        if calls["n"] > 1:
            return '{"edits": []}'
        lines = _bullet_lines(user_prompt, "loves FSRS")
        assert len(lines) == 2
        return json.dumps(
            {
                "edits": [
                    {
                        "op": "replace",
                        "line": lines[0],
                        "new_text": "uses FSRS daily",
                        "refs": ["^chat:01"],
                        "reason": "merged duplicates",
                    },
                    {
                        "op": "delete",
                        "line_start": lines[1],
                        "line_end": lines[1],
                        "reason": "duplicate",
                    },
                ]
            }
        )

    with (
        patch("deeptutor.services.memory.consolidator.modes.dedup.call_llm", side_effect=fake_llm),
        patch.object(dedup_mod, "load_memory_settings", return_value=_dedup_settings(iterations=2)),
    ):
        result = await dedup_mod.run_dedup("L2", "chat", on_event=await _collect_events(events))

    assert calls["n"] == 2
    assert result.edits_applied == 2
    assert result.iterations_run == 2
    assert result.converged_early is True

    final = parse(path.read_text(encoding="utf-8"))
    entries = final.all_entries()
    assert [e.text for e in entries] == ["uses FSRS daily"]
    assert entries[0].refs == ["chat:01"]

    op = next(e for e in events if e.get("stage") == "op_applied")
    assert op["turn"] == 1
    assert op["applied"] == 2
    assert op["rejected"] == 0
    doc_updated = [e for e in events if e.get("stage") == "doc_updated"]
    assert len(doc_updated) == 1
    assert doc_updated[0]["layer"] == "L2"
    assert doc_updated[0]["key"] == "chat"
    assert doc_updated[0]["action"] == "apply_edits"
    done = next(e for e in events if e.get("stage") == "done")
    assert done["edits_applied"] == 2
    assert done["iterations_run"] == 2
    assert done["converged_early"] is True


@pytest.mark.asyncio
async def test_dedup_runs_until_iteration_cap(memory_dir, monkeypatch):
    _seed_l2(memory_dir, "chat", _l2_doc(["alpha"]))
    path = memory_dir / "L2" / "chat.md"
    calls = {"n": 0}

    async def fake_llm(*, system_prompt, user_prompt, **kwargs):
        calls["n"] += 1
        lines = _bullet_lines(user_prompt, "alpha")
        return json.dumps(
            {
                "edits": [
                    {
                        "op": "replace",
                        "line": lines[0],
                        "new_text": f"alpha v{calls['n']}",
                        "refs": ["chat:01"],
                        "reason": "polish",
                    }
                ]
            }
        )

    with (
        patch("deeptutor.services.memory.consolidator.modes.dedup.call_llm", side_effect=fake_llm),
        patch.object(dedup_mod, "load_memory_settings", return_value=_dedup_settings(iterations=2)),
    ):
        result = await dedup_mod.run_dedup("L2", "chat")

    assert calls["n"] == 2
    assert result.iterations_run == 2
    assert result.edits_applied == 2
    assert result.converged_early is False
    final = parse(path.read_text(encoding="utf-8"))
    assert [e.text for e in final.all_entries()] == ["alpha v2"]


@pytest.mark.asyncio
async def test_dedup_l3_layer_keeps_entry_id_refs(memory_dir, monkeypatch):
    entry_ref = new_entry_id()
    path = memory_dir / "L3" / "profile.md"
    path.write_text(
        serialize(
            Document(
                title="User profile",
                sections=[
                    (
                        "Preferences",
                        [
                            Entry(
                                id=new_entry_id(),
                                section="Preferences",
                                text="likes morning runs",
                                refs=[entry_ref],
                            )
                        ],
                    )
                ],
            )
        ),
        encoding="utf-8",
    )

    calls = {"n": 0}

    async def fake_llm(*, system_prompt, user_prompt, **kwargs):
        calls["n"] += 1
        if calls["n"] > 1:
            return '{"edits": []}'
        lines = _bullet_lines(user_prompt, "likes morning runs")
        assert lines
        return json.dumps(
            {
                "edits": [
                    {
                        "op": "replace",
                        "line": lines[0],
                        "new_text": "runs every morning",
                        "refs": [entry_ref],
                        "reason": "clearer phrasing",
                    }
                ]
            }
        )

    with (
        patch("deeptutor.services.memory.consolidator.modes.dedup.call_llm", side_effect=fake_llm),
        patch.object(dedup_mod, "load_memory_settings", return_value=_dedup_settings()),
    ):
        result = await dedup_mod.run_dedup("L3", "profile")

    assert result.layer == "L3"
    assert result.key == "profile"
    assert result.edits_applied == 1
    final = parse(path.read_text(encoding="utf-8"))
    entries = final.all_entries()
    assert [e.text for e in entries] == ["runs every morning"]
    assert entries[0].refs == [entry_ref]


@pytest.mark.asyncio
async def test_dedup_merge_autorun_when_enabled(memory_dir, monkeypatch):
    _seed_l2(memory_dir, "chat", _l2_doc(["alpha", "beta"]))
    merge_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(merge_mod, "run_merge", merge_mock)

    with (
        patch(
            "deeptutor.services.memory.consolidator.modes.dedup.call_llm",
            side_effect=_llm_empty,
        ),
        patch.object(
            dedup_mod,
            "load_memory_settings",
            return_value=_dedup_settings(iterations=1, auto_after_dedup=True),
        ),
    ):
        await dedup_mod.run_dedup("L2", "chat", language="zh", user_label="u1")

    merge_mock.assert_awaited_once()
    kwargs = merge_mock.await_args.kwargs
    assert merge_mock.await_args.args == ("L2", "chat")
    assert kwargs["language"] == "zh"
    assert kwargs["user_label"] == "u1"


@pytest.mark.asyncio
async def test_dedup_merge_autorun_skipped_when_disabled(memory_dir, monkeypatch):
    _seed_l2(memory_dir, "chat", _l2_doc(["alpha"]))
    merge_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(merge_mod, "run_merge", merge_mock)

    with (
        patch(
            "deeptutor.services.memory.consolidator.modes.dedup.call_llm",
            side_effect=_llm_empty,
        ),
        patch.object(
            dedup_mod,
            "load_memory_settings",
            return_value=_dedup_settings(iterations=1, auto_after_dedup=False),
        ),
    ):
        await dedup_mod.run_dedup("L2", "chat")

    merge_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_dedup_llm_selection_unresolvable_degrades_gracefully(memory_dir, monkeypatch):
    _seed_l2(memory_dir, "chat", _l2_doc(["alpha"]))

    def broken_activate(selection):
        raise ValueError(f"cannot resolve {selection}")

    monkeypatch.setattr(
        "deeptutor.services.model_selection.runtime.activate_llm_selection", broken_activate
    )

    with (
        patch(
            "deeptutor.services.memory.consolidator.modes.dedup.call_llm",
            side_effect=_llm_empty,
        ),
        patch.object(dedup_mod, "load_memory_settings", return_value=_dedup_settings()),
    ):
        result = await dedup_mod.run_dedup("L2", "chat", llm_selection={"model": "nope"})

    assert result.converged_early is True
    assert result.iterations_run == 1
    assert result.edits_applied == 0


@pytest.mark.asyncio
async def test_dedup_llm_selection_token_reset_on_success(memory_dir, monkeypatch):
    token = object()
    activate = MagicMock(return_value=(object(), token))
    reset = MagicMock()
    monkeypatch.setattr(
        "deeptutor.services.model_selection.runtime.activate_llm_selection", activate
    )
    monkeypatch.setattr("deeptutor.services.model_selection.runtime.reset_llm_selection", reset)

    with (
        patch(
            "deeptutor.services.memory.consolidator.modes.dedup.call_llm",
            side_effect=_llm_empty,
        ),
        patch.object(dedup_mod, "load_memory_settings", return_value=_dedup_settings()),
    ):
        result = await dedup_mod.run_dedup("L2", "chat", llm_selection={"model": "picked"})

    assert result.converged_early is True
    activate.assert_called_once_with({"model": "picked"})
    reset.assert_called_once_with(token)


@pytest.mark.asyncio
async def test_dedup_llm_selection_token_reset_when_inner_raises(memory_dir, monkeypatch):
    _seed_l2(memory_dir, "chat", _l2_doc(["alpha"]))
    token = object()
    activate = MagicMock(return_value=(object(), token))
    reset = MagicMock()
    monkeypatch.setattr(
        "deeptutor.services.model_selection.runtime.activate_llm_selection", activate
    )
    monkeypatch.setattr("deeptutor.services.model_selection.runtime.reset_llm_selection", reset)

    async def exploding_llm(*args, **kwargs):
        raise RuntimeError("llm down")

    with (
        patch(
            "deeptutor.services.memory.consolidator.modes.dedup.call_llm",
            side_effect=exploding_llm,
        ),
        patch.object(dedup_mod, "load_memory_settings", return_value=_dedup_settings(iterations=2)),
    ):
        with pytest.raises(RuntimeError, match="llm down"):
            await dedup_mod.run_dedup("L2", "chat", llm_selection={"model": "picked"})

    activate.assert_called_once()
    reset.assert_called_once_with(token)


@pytest.mark.asyncio
async def test_dedup_event_sequence_progress_facts_done(memory_dir, monkeypatch):
    _seed_l2(memory_dir, "chat", _l2_doc(["alpha", "beta"]))
    events: list[dict] = []

    with (
        patch(
            "deeptutor.services.memory.consolidator.modes.dedup.call_llm",
            side_effect=_llm_empty,
        ),
        patch.object(dedup_mod, "load_memory_settings", return_value=_dedup_settings(iterations=1)),
    ):
        await dedup_mod.run_dedup("L2", "chat", on_event=await _collect_events(events))

    assert _stage_names(events) == ["progress", "facts_extracted", "done"]
    progress = events[0]
    assert progress["mode"] == "dedup"
    assert progress["turn"] == 1
    assert progress["total"] == 1
    assert progress["lines"] > 0
    assert events[1]["turn"] == 1
    assert events[1]["edits"] == 0
    done = events[2]
    assert done["edits_applied"] == 0
    assert done["iterations_run"] == 1
    assert done["converged_early"] is True


@pytest.mark.asyncio
async def test_dedup_on_event_consumer_raising_is_swallowed(memory_dir, monkeypatch):
    _seed_l2(memory_dir, "chat", _l2_doc(["alpha"]))

    async def broken_consumer(event: dict) -> None:
        raise RuntimeError("consumer boom")

    with (
        patch(
            "deeptutor.services.memory.consolidator.modes.dedup.call_llm",
            side_effect=_llm_empty,
        ),
        patch.object(dedup_mod, "load_memory_settings", return_value=_dedup_settings()),
    ):
        result = await dedup_mod.run_dedup("L2", "chat", on_event=broken_consumer)

    assert result.converged_early is True
    assert result.iterations_run == 1
