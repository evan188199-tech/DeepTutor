"""Unit tests for :mod:`deeptutor.services.memory.consolidator.modes._runtime`.

Covers the shared mode-runtime plumbing directly: prompt/meta loading and
caching, SSE ``emit``, the ``call_llm`` wrapper (streaming main path,
streaming-failure fallback to ``complete``, double failure, consumer
errors, cancellation), document load/save, run-scoped write checkpoints
(storage boundary mocked), and the streamed ``<think>`` stripper.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from deeptutor.services.memory.consolidator.modes import _runtime as rt
from deeptutor.services.memory.document import Document, Entry, parse, serialize


@pytest.fixture(autouse=True)
def fresh_caches(monkeypatch):
    """Isolate the module-level prompt/meta caches between tests."""
    monkeypatch.setattr(rt, "_PROMPT_CACHE", {})
    monkeypatch.setattr(rt, "_META_CACHE", {})


@pytest.fixture()
def fake_llm_config(monkeypatch):
    monkeypatch.setattr(
        "deeptutor.services.llm.get_llm_config",
        lambda: SimpleNamespace(model="unit-test-model"),
    )


def _fake_stream(chunks: list[str], *, fail_after: BaseException | None = None):
    async def stream(**kwargs):
        for chunk in chunks:
            yield chunk
        if fail_after is not None:
            raise fail_after

    return stream


def _events() -> tuple[list[dict[str, Any]], Any]:
    seen: list[dict[str, Any]] = []

    async def on_event(event: dict[str, Any]) -> None:
        seen.append(event)

    return seen, on_event


def _doc() -> Document:
    doc = Document(title="Profile")
    doc.section_entries("Mastery").append(
        Entry(
            id="m_00000000000000000000000000",
            section="Mastery",
            text="uses FSRS",
            refs=["chat:abc"],
        )
    )
    return doc


# ── prompt / meta loading ───────────────────────────────────────────────


def test_load_prompt_loads_caches_and_maps_language_variants():
    en_first = rt.load_prompt("update_l2", "en")
    en_again = rt.load_prompt("update_l2", "en")
    zh = rt.load_prompt("update_l2", "zh-CN")

    assert en_first is en_again, "second load must hit the cache (same object)"
    assert en_first is not zh
    assert set(en_first) == {"system", "user"}
    assert en_first["system"]  # real prompt files carry non-empty system text
    assert zh["system"]
    assert rt._PROMPT_CACHE[("en", "update_l2")] is en_first
    assert rt._PROMPT_CACHE[("zh", "update_l2")] is zh
    assert rt.load_prompt("update_l2", "") is rt.load_prompt("update_l2", "fr-CA")


def test_load_prompt_rejects_invalid_yaml_and_does_not_cache_failure(tmp_path: Path, monkeypatch):
    prompts = tmp_path / "en"
    prompts.mkdir()
    (prompts / "empty.yaml").write_text("", encoding="utf-8")
    (prompts / "partial.yaml").write_text("system: only-sys\n", encoding="utf-8")
    monkeypatch.setattr(rt, "_PROMPTS_DIR", tmp_path)

    for name in ("empty", "partial"):
        with pytest.raises(RuntimeError, match=name):
            rt.load_prompt(name, "en")
    assert rt._PROMPT_CACHE == {}, "invalid prompts must not be cached"


def test_load_focus_meta_caches_per_language(tmp_path: Path, monkeypatch):
    en_dir = tmp_path / "en"
    zh_dir = tmp_path / "zh"
    en_dir.mkdir()
    zh_dir.mkdir()
    (en_dir / "_meta.yaml").write_text(
        yaml.safe_dump({"surfaces": {"profile": {"focus": "facts"}}}), "utf-8"
    )
    (zh_dir / "_meta.yaml").write_text(yaml.safe_dump({"surfaces": {}}), "utf-8")
    monkeypatch.setattr(rt, "_PROMPTS_DIR", tmp_path)

    en_meta = rt.load_focus_meta("en")
    assert en_meta["surfaces"]["profile"]["focus"] == "facts"
    assert rt.load_focus_meta("en") is en_meta, "meta load must be cached per language"
    zh_meta = rt.load_focus_meta("zh-TW")
    assert zh_meta is not en_meta


def test_surface_and_slot_focus_extract_or_default(tmp_path: Path, monkeypatch):
    meta_dir = tmp_path / "en"
    meta_dir.mkdir()
    (meta_dir / "_meta.yaml").write_text(
        yaml.safe_dump(
            {
                "surfaces": {
                    "profile": {"focus": "stable facts", "sections": ["Mastery", "Prefs"]}
                },
                "slots": {"goals": {"focus": "learning goals"}},
            }
        ),
        "utf-8",
    )
    monkeypatch.setattr(rt, "_PROMPTS_DIR", tmp_path)

    assert rt.surface_focus("en", "profile") == ("stable facts", ["Mastery", "Prefs"])
    assert rt.slot_focus("en", "goals") == ("learning goals", [])
    assert rt.surface_focus("en", "unknown-surface") == ("", [])
    assert rt.slot_focus("en", "nope") == ("", [])


# ── emit ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_emit_is_noop_without_consumer():
    assert await rt.emit(None, {"stage": "anything"}) is None


@pytest.mark.asyncio
async def test_emit_swallows_consumer_errors(caplog):
    consumed: list[dict[str, Any]] = []

    async def flaky(event):
        if event["stage"] == "boom":
            raise ValueError("consumer broke")
        consumed.append(event)

    await rt.emit(flaky, {"stage": "ok"})
    await rt.emit(flaky, {"stage": "boom"})
    assert consumed == [{"stage": "ok"}]


# ── call_llm — streaming main path ───────────────────────────────────────


@pytest.mark.asyncio
async def test_call_llm_streams_deltas_and_emits_trace_events(fake_llm_config, monkeypatch):
    seen, on_event = _events()
    stream_kwargs: dict[str, Any] = {}

    async def stream(**kwargs):
        stream_kwargs.update(kwargs)
        for chunk in ["Hel", "", "lo"]:
            yield chunk

    monkeypatch.setattr(rt, "llm_stream", stream)
    monkeypatch.setattr(
        rt, "llm_complete", lambda **kw: pytest.fail("fallback must not run on success")
    )

    result = await rt.call_llm(
        system_prompt="SYS",
        user_prompt="USR",
        temperature=0.7,
        max_tokens=99,
        on_event=on_event,
        turn=3,
        chunk_index=1,
        label="update_l2",
    )

    assert result == "Hello"
    assert stream_kwargs["prompt"] == "USR"
    assert stream_kwargs["system_prompt"] == "SYS"
    assert stream_kwargs["temperature"] == 0.7
    assert stream_kwargs["max_tokens"] == 99
    stages = [e["stage"] for e in seen]
    assert stages == ["llm_io_start", "llm_io_delta", "llm_io_delta", "llm_io_end"]
    start = seen[0]
    assert start["model"] == "unit-test-model"
    assert start["system_prompt"] == "SYS"
    assert start["user_prompt"] == "USR"
    assert start["turn"] == 3 and start["chunk_index"] == 1 and start["label"] == "update_l2"
    assert [e["delta"] for e in seen if e["stage"] == "llm_io_delta"] == ["Hel", "lo"]
    end = seen[-1]
    assert end["response"] == "Hello" and end["error"] is None


@pytest.mark.asyncio
async def test_call_llm_strips_thinking_blocks_from_stream_and_result(fake_llm_config, monkeypatch):
    seen, on_event = _events()
    monkeypatch.setattr(
        rt, "llm_stream", _fake_stream(["<think>secret", "bits</think>Vis", "ible"])
    )
    monkeypatch.setattr(rt, "llm_complete", lambda **kw: pytest.fail("fallback must not run"))

    result = await rt.call_llm(system_prompt="s", user_prompt="u", on_event=on_event)

    assert result == "Visible"
    visible = "".join(e["delta"] for e in seen if e["stage"] == "llm_io_delta")
    assert visible == "Visible"
    assert "secret" not in visible


@pytest.mark.asyncio
async def test_call_llm_without_consumer_skips_empty_deltas(monkeypatch):
    async def stream(**kwargs):
        for chunk in ["", "ok", ""]:
            yield chunk

    monkeypatch.setattr(rt, "llm_stream", stream)

    result = await rt.call_llm(system_prompt="s", user_prompt="u", on_event=None)
    assert result == "ok"


# ── call_llm — failure / fallback / cancel paths ─────────────────────────


@pytest.mark.asyncio
async def test_call_llm_falls_back_to_complete_when_streaming_fails(
    fake_llm_config, monkeypatch, caplog
):
    seen, on_event = _events()
    monkeypatch.setattr(
        rt,
        "llm_stream",
        _fake_stream(["partial"], fail_after=RuntimeError("no streaming here")),
    )
    complete_calls: list[dict[str, Any]] = []

    async def complete(**kwargs):
        complete_calls.append(kwargs)
        return "<think>junk</think>Fallback body"

    monkeypatch.setattr(rt, "llm_complete", complete)

    with caplog.at_level("WARNING", logger="deeptutor.services.memory.consolidator.modes._runtime"):
        result = await rt.call_llm(system_prompt="s", user_prompt="u", on_event=on_event)

    assert result == "Fallback body"
    assert len(complete_calls) == 1
    assert complete_calls[0]["prompt"] == "u"
    assert any("falling back" in rec.message for rec in caplog.records)
    deltas = [e["delta"] for e in seen if e["stage"] == "llm_io_delta"]
    assert deltas == ["partial", "Fallback body"], (
        "streamed partial is emitted live; fallback body emitted once"
    )
    end = seen[-1]
    assert end["stage"] == "llm_io_end" and end["error"] is None
    assert end["response"] == "Fallback body", (
        "failed stream partials must not leak into the final response"
    )


@pytest.mark.asyncio
async def test_call_llm_returns_empty_and_reports_error_when_both_paths_fail(
    fake_llm_config, monkeypatch
):
    seen, on_event = _events()
    monkeypatch.setattr(rt, "llm_stream", _fake_stream([], fail_after=RuntimeError("stream down")))

    async def complete(**kwargs):
        raise RuntimeError("complete down too")

    monkeypatch.setattr(rt, "llm_complete", complete)

    result = await rt.call_llm(system_prompt="s", user_prompt="u", on_event=on_event)

    assert result == ""
    end = seen[-1]
    assert end["stage"] == "llm_io_end"
    assert end["response"] == ""
    assert "complete down too" in end["error"]


@pytest.mark.asyncio
async def test_call_llm_returns_empty_without_consumer_on_double_failure(monkeypatch):
    monkeypatch.setattr(rt, "llm_stream", _fake_stream([], fail_after=RuntimeError("down")))

    async def complete(**kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(rt, "llm_complete", complete)
    assert await rt.call_llm(system_prompt="s", user_prompt="u") == ""


@pytest.mark.asyncio
async def test_call_llm_lets_cancellation_propagate_without_fallback(fake_llm_config, monkeypatch):
    seen, on_event = _events()
    monkeypatch.setattr(rt, "llm_stream", _fake_stream([], fail_after=asyncio.CancelledError()))
    complete_calls: list[dict[str, Any]] = []

    async def complete(**kwargs):
        complete_calls.append(kwargs)
        return "should not be used"

    monkeypatch.setattr(rt, "llm_complete", complete)

    with pytest.raises(asyncio.CancelledError):
        await rt.call_llm(system_prompt="s", user_prompt="u", on_event=on_event)

    assert complete_calls == [], "cancellation must not silently fall back to complete()"
    assert [e["stage"] for e in seen] == ["llm_io_start"], (
        "no success/error end event after cancellation"
    )


@pytest.mark.asyncio
async def test_call_llm_consumer_error_on_start_event_propagates(fake_llm_config, monkeypatch):
    stream_called = False

    async def stream(**kwargs):
        nonlocal stream_called
        stream_called = True
        yield "x"

    monkeypatch.setattr(rt, "llm_stream", stream)

    async def bad_consumer(event):
        raise ValueError("consumer rejects start")

    with pytest.raises(ValueError, match="consumer rejects start"):
        await rt.call_llm(system_prompt="s", user_prompt="u", on_event=bad_consumer)

    assert stream_called is False


@pytest.mark.asyncio
async def test_call_llm_consumer_error_during_delta_degrades_to_empty_result(
    fake_llm_config, monkeypatch
):
    """Pins current contract: a consumer that rejects delta events degrades a
    successful LLM answer to "" (delta emissions are inside the fallback's
    guarded block), while the closing error event is still delivered."""
    seen, _ = _events()

    async def selective_consumer(event):
        seen.append(event)
        if event["stage"] == "llm_io_delta":
            raise ValueError("UI gone")

    monkeypatch.setattr(rt, "llm_stream", _fake_stream(["Hel", "lo"]))

    async def complete(**kwargs):
        return "ok"

    monkeypatch.setattr(rt, "llm_complete", complete)

    result = await rt.call_llm(system_prompt="s", user_prompt="u", on_event=selective_consumer)
    assert result == ""
    assert seen[-1]["stage"] == "llm_io_end" and "UI gone" in seen[-1]["error"]


# ── document load / save ──────────────────────────────────────────────────


def test_load_doc_defaults_when_missing_and_parses_when_present(tmp_path: Path):
    missing = tmp_path / "nested" / "L2.md"
    doc = rt.load_doc(missing, default_title="Default Title")
    assert doc.title == "Default Title" and doc.sections == []

    existing = tmp_path / "L2.md"
    existing.write_text(serialize(_doc()), encoding="utf-8")
    loaded = rt.load_doc(existing, default_title="ignored")
    assert loaded.title == "Profile"
    assert loaded.all_entries()[0].text == "uses FSRS"


@pytest.mark.asyncio
async def test_write_doc_atomic_creates_parents_and_round_trips(tmp_path: Path):
    target = tmp_path / "a" / "b" / "L2.md"
    await rt.write_doc_atomic(target, _doc())
    assert target.exists()
    assert parse(target.read_text(encoding="utf-8")).title == "Profile"


# ── write checkpoint (runs-facade boundary; storage mocked) ──────────────


@pytest.mark.asyncio
async def test_write_doc_checkpoint_snapshots_previous_and_emits(tmp_path: Path, monkeypatch):
    path = tmp_path / "L2" / "profile.md"
    path.parent.mkdir()
    path.write_text("old content", encoding="utf-8")
    recorded: dict[str, Any] = {}

    def fake_push(**kwargs):
        recorded.update(kwargs)
        return 3

    monkeypatch.setattr(
        "deeptutor.services.memory.consolidator.runs.push_undo_checkpoint", fake_push
    )
    seen, on_event = _events()

    depth = await rt.write_doc_checkpoint(
        path,
        _doc(),
        layer="L2",
        key="profile",
        on_event=on_event,
        turn=7,
        label="update_l2",
    )

    assert depth == 3
    assert recorded["layer"] == "L2"
    assert recorded["key"] == "profile"
    assert recorded["path"] == path
    assert recorded["existed"] is True
    assert recorded["previous_content"] == "old content"
    assert recorded["action"] == "write"
    assert recorded["turn"] == 7 and recorded["label"] == "update_l2"
    assert parse(path.read_text(encoding="utf-8")).title == "Profile"
    event = seen[-1]
    assert event["stage"] == "doc_updated"
    assert event["undo_depth"] == 3
    assert event["action"] == "write" and event["turn"] == 7


@pytest.mark.asyncio
async def test_write_doc_checkpoint_first_write_reports_not_existed(tmp_path: Path, monkeypatch):
    path = tmp_path / "fresh" / "doc.md"
    recorded: dict[str, Any] = {}

    def fake_push(**kwargs):
        recorded.update(kwargs)
        return 1

    monkeypatch.setattr(
        "deeptutor.services.memory.consolidator.runs.push_undo_checkpoint", fake_push
    )

    depth = await rt.write_doc_checkpoint(path, Document(title="New"), layer="L3", key="doc")

    assert depth == 1
    assert recorded["existed"] is False
    assert recorded["previous_content"] == ""
    assert path.exists()


@pytest.mark.asyncio
async def test_write_doc_checkpoint_without_active_run_reports_depth_zero(tmp_path: Path):
    """Real runs boundary: with no active run context, the checkpoint is a
    plain write and undo depth is 0 — no storage is touched."""
    path = tmp_path / "L2" / "doc.md"
    seen, on_event = _events()

    depth = await rt.write_doc_checkpoint(path, _doc(), layer="L2", key="doc", on_event=on_event)

    assert depth == 0
    assert seen[-1]["undo_depth"] == 0
    assert path.exists()


# ── streamed <think> stripper ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("delta", "in_block", "expected_out", "expected_state"),
    [
        ("plain text", False, "plain text", False),
        ("<think>hidden</think>visible", False, "visible", False),
        ("<THINK>x</THINK>tail", False, "tail", False),
        ("<thinking>y</thinking>z", False, "z", False),
        ("still hidden", True, "", True),
        ("</think>after", True, "after", False),
        ("<think>unclosed", False, "", True),
        ("a<think>b", False, "a", True),
        ("", False, "", False),
    ],
)
def test_strip_thinking_delta_transitions(delta, in_block, expected_out, expected_state):
    assert rt._strip_thinking_delta(delta, in_block) == (expected_out, expected_state)


# ── today_iso ─────────────────────────────────────────────────────────────


def test_today_iso_is_utc_date():
    assert rt.today_iso() == datetime.now(tz=timezone.utc).date().isoformat()
