"""Tests for the MarginNote knowledge capability: adapters, hooks, tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.agents._shared.tool_composition import ToolMountFlags, compose_enabled_tools
from deeptutor.capabilities import any_exclusive_capability_active
from deeptutor.capabilities.marginnote import MARGINNOTE_TOOL_NAMES, MarginNoteCapability
from deeptutor.capabilities.marginnote import binding as mn_binding
from deeptutor.capabilities.marginnote.data import AdapterError, RealmAdapter, open_adapter
from deeptutor.capabilities.marginnote.data.export_adapter import ExportAdapter
from deeptutor.capabilities.marginnote.tools import (
    MarginNoteAppendNoteTool,
    MarginNoteCreateNoteTool,
    MarginNoteCreateSummaryTool,
    MarginNoteReadNoteTool,
    MarginNoteSearchTool,
)
from deeptutor.core.context import UnifiedContext
from deeptutor.runtime.registry.tool_registry import get_tool_registry


def _seed_export(root: Path) -> None:
    (root / "Fourier.md").write_text(
        "# Fourier Analysis\n\n"
        "> A transform maps time to frequency (p.42) [color:yellow]\n"
        "I think this is the core definition. #transform\n\n"
        "> Convolution in time is multiplication in frequency (p.43)\n"
        "Need an example. #convolution\n",
        encoding="utf-8",
    )
    (root / "map.opml").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0">
  <head><title>Fourier</title></head>
  <body>
    <outline text="Fourier Analysis">
      <outline text="Transform" _note="time to frequency"/>
      <outline text="Convolution"/>
    </outline>
  </body>
</opml>
""",
        encoding="utf-8",
    )


def test_export_adapter_parses_highlights_notes_tags_and_pages(tmp_path: Path) -> None:
    _seed_export(tmp_path)
    adapter = ExportAdapter(str(tmp_path))
    notebook = adapter.load()
    assert len(notebook.highlights) == 2
    first = notebook.highlights[0]
    assert first.page == 42
    assert first.color == "yellow"
    assert "transform" in first.tags
    assert first.note_id
    assert adapter.tags()[0]["tag"] in {"transform", "convolution"}
    docs = adapter.list_documents()
    assert any(doc["name"] == "Fourier" for doc in docs)


def test_export_adapter_parses_opml_hierarchy(tmp_path: Path) -> None:
    _seed_export(tmp_path)
    adapter = ExportAdapter(str(tmp_path))
    overview = adapter.mindmap(depth=2)
    assert overview["root_ids"]
    titles = {node["title"] for node in overview["nodes"]}
    assert {"Fourier Analysis", "Transform", "Convolution"} <= titles


def test_export_adapter_search_and_refresh(tmp_path: Path) -> None:
    _seed_export(tmp_path)
    adapter = ExportAdapter(str(tmp_path))
    hits = adapter.search("convolution")
    assert hits and hits[0]["kind"] in {"highlight", "note"}
    (tmp_path / "Fourier.md").write_text(
        "> A brand new excerpt about wavelets (p.9)\n", encoding="utf-8"
    )
    refreshed = adapter.search("wavelets")
    assert refreshed and refreshed[0]["page"] == 9


def test_writeback_is_additive_and_refuses_escape(tmp_path: Path) -> None:
    _seed_export(tmp_path)
    adapter = ExportAdapter(str(tmp_path))
    created = adapter.create_note(
        "recap.md",
        "Summary of Fourier",
        {"document": "Fourier", "source_url": "", "mastery_path_id": "p1"},
    )
    assert created == "recap.md"
    body = (tmp_path / "deeptutor-notes" / "recap.md").read_text(encoding="utf-8")
    assert "mastery_path_id: p1" in body
    assert "Summary of Fourier" in body
    with pytest.raises(AdapterError):
        adapter.create_note("recap.md", "dup")
    adapter.append_note("recap", "extra line")
    assert "extra line" in (tmp_path / "deeptutor-notes" / "recap.md").read_text(
        encoding="utf-8"
    )
    with pytest.raises(AdapterError):
        adapter.create_note("../escape.md", "x")


def test_realm_adapter_is_explicit_stub(tmp_path: Path) -> None:
    adapter = RealmAdapter(str(tmp_path))
    with pytest.raises(AdapterError, match="not implemented"):
        adapter.load()
    with pytest.raises(AdapterError, match="Unknown"):
        open_adapter(str(tmp_path), adapter="sqlite")


def _bind(monkeypatch, notebook_path: str, name: str = "mynotes") -> None:
    monkeypatch.setattr(
        "deeptutor.multi_user.knowledge_access.resolve_kb_metadata",
        lambda ref: (
            {
                "name": ref,
                "type": "marginnote",
                "notebook_path": notebook_path,
                "adapter": "export",
            }
            if ref == name
            else {"name": ref, "type": None}
        ),
    )


def test_capability_inactive_without_marginnote_kb(monkeypatch, tmp_path: Path) -> None:
    _bind(monkeypatch, str(tmp_path))
    cap = MarginNoteCapability()
    ctx = UnifiedContext(user_message="hi", knowledge_bases=["plain-kb"])
    assert cap.is_active(ctx) is False
    assert cap.system_block(ctx, language="en", prompts={}) is None


def test_capability_active_injects_notebook_path(monkeypatch, tmp_path: Path) -> None:
    _bind(monkeypatch, str(tmp_path))
    cap = MarginNoteCapability()
    ctx = UnifiedContext(
        user_message="hi",
        knowledge_bases=["mynotes"],
        metadata={"mastery_path_id": "path-1"},
    )
    assert cap.is_active(ctx) is True
    assert tuple(cap.owned_tools) == MARGINNOTE_TOOL_NAMES
    injected = cap.augment_kwargs("mn_search", {}, ctx)
    assert injected["_notebook_path"] == str(tmp_path)
    assert injected["_adapter"] == "export"
    assert injected["_mastery_path_id"] == "path-1"
    assert cap.augment_kwargs("mn_search", {"_notebook_path": "/etc"}, ctx)[
        "_notebook_path"
    ] == str(tmp_path)
    assert "_notebook_path" not in cap.augment_kwargs("rag", {}, ctx)
    block = cap.system_block(ctx, language="en", prompts={})
    assert block is not None and "mynotes" in block.content


def test_binding_resolved_once_and_cached(monkeypatch, tmp_path: Path) -> None:
    calls = {"n": 0}

    def fake(ref):
        calls["n"] += 1
        return {
            "name": ref,
            "type": "marginnote",
            "notebook_path": str(tmp_path),
            "adapter": "export",
        }

    monkeypatch.setattr("deeptutor.multi_user.knowledge_access.resolve_kb_metadata", fake)
    ctx = UnifiedContext(user_message="hi", knowledge_bases=["n"])
    mn_binding.notebook_for_turn(ctx)
    mn_binding.notebook_for_turn(ctx)
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_tools_fail_without_notebook_path() -> None:
    res = await MarginNoteSearchTool().execute(query="x")
    assert res.success is False and "marginnote" in res.content.lower()


@pytest.mark.asyncio
async def test_tools_round_trip_against_export(tmp_path: Path) -> None:
    _seed_export(tmp_path)
    path = str(tmp_path)
    hits = json.loads(
        (await MarginNoteSearchTool().execute(query="frequency", _notebook_path=path)).content
    )
    assert hits["count"] >= 1
    item_id = hits["results"][0]["id"]
    read = json.loads(
        (await MarginNoteReadNoteTool().execute(id=item_id, _notebook_path=path)).content
    )
    assert read["kind"] in {"highlight", "note"}
    created = await MarginNoteCreateNoteTool().execute(
        path="cards/one.md",
        content="hello",
        document="Fourier",
        _notebook_path=path,
    )
    assert created.success
    appended = await MarginNoteAppendNoteTool().execute(
        note="cards/one.md", content="more", _notebook_path=path
    )
    assert appended.success
    summary = await MarginNoteCreateSummaryTool().execute(
        scope="Fourier", analysis="Core idea is the transform.", _notebook_path=path
    )
    assert summary.success
    written = json.loads(summary.content)["path"]
    assert (tmp_path / "deeptutor-notes" / written).is_file()


def test_exclusive_compose_includes_marginnote_tools() -> None:
    composed = compose_enabled_tools(
        registry=get_tool_registry(),
        requested_tools=["web_search"],
        optional_whitelist=["web_search"],
        mount_flags=ToolMountFlags(has_kb=False),
        capability_owned=["mn_search", "mn_read_note"],
        exclusive=True,
    )
    assert set(composed) == {"mn_search", "mn_read_note", "ask_user"}


def test_registry_flags_marginnote_turn_as_exclusive(monkeypatch, tmp_path: Path) -> None:
    _bind(monkeypatch, str(tmp_path))
    mn_turn = UnifiedContext(user_message="hi", knowledge_bases=["mynotes"])
    plain_turn = UnifiedContext(user_message="hi", knowledge_bases=["plain-kb"])
    assert any_exclusive_capability_active(mn_turn) is True
    assert any_exclusive_capability_active(plain_turn) is False
