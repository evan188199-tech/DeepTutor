"""Offline tests for the MarginNote notebook data adapters.

Covers the export Markdown/OPML parser, malformed/missing-field tolerance,
the Realm stub contract, and adapter diagnostics, all against synthetic
export folders (no MarginNote app required).
"""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.capabilities.marginnote.data import (
    AdapterError,
    ExportAdapter,
    RealmAdapter,
    open_adapter,
)
from deeptutor.capabilities.marginnote.data.base import (
    MarginNoteAdapter,
    Notebook,
)
from deeptutor.capabilities.marginnote.data.diagnostics import (
    KNOWN_ADAPTERS,
    PUBLIC_ADAPTERS,
    WRITE_MODE_IMPORT_QUEUE,
    WRITE_MODE_NONE,
    AdapterCapabilities,
    AdapterDiagnostics,
    ParseWarning,
    display_name_for,
)
from deeptutor.capabilities.marginnote.data.export_adapter import (
    WRITEBACK_DIRNAME,
    split_frontmatter,
)

SAMPLE_MD = """---
source: MarginNote
---
# Chapter 1

> First highlight text (p. 12) [color: red] #core

comment one #core

> Second highlight #extra

plain standalone note

# Chapter 2

> Third highlight (page 30)

thought without page
"""

SAMPLE_OPML = """<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0">
  <head><title>Map</title></head>
  <body>
    <outline text="Root A" _note="root note">
      <outline text="Child A1"/>
      <outline title="Child A2" note="alt note"/>
    </outline>
    <outline text="Root B"/>
  </body>
</opml>
"""


def _write(root, rel: str, payload) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, bytes):
        path.write_bytes(payload)
    else:
        path.write_text(payload, encoding="utf-8")


def _make_adapter(tmp_path, files: dict[str, Any], **kwargs) -> ExportAdapter:
    root = tmp_path / "notebook"
    root.mkdir(exist_ok=True)
    for rel, payload in files.items():
        _write(root, rel, payload)
    return ExportAdapter(str(root), **kwargs)


def _minimal_adapter(tmp_path) -> MarginNoteAdapter:
    class Minimal(MarginNoteAdapter):
        def load(self) -> Notebook:
            return Notebook(name="m", root=self.notebook_path)

        def search(self, query, *, tag="", limit=20):
            return []

        def read_item(self, item_id):
            return {}

        def list_documents(self):
            return []

        def read_highlights(self, document_id="", *, page_from=None, page_to=None, limit=100):
            return []

        def mindmap(self, node_id="", *, depth=3):
            return {}

        def tags(self, limit=200):
            return []

        def create_note(self, rel_path, content, frontmatter=None):
            return ""

        def append_note(self, ref, content):
            return ""

        def create_summary(self, scope, analysis, *, frontmatter=None):
            return ""

    return Minimal(str(tmp_path))


def test_open_adapter_factory_routes_and_rejects(tmp_path) -> None:
    root = tmp_path / "nb"
    root.mkdir()
    adapter = open_adapter(str(root))
    assert isinstance(adapter, ExportAdapter)
    assert adapter.adapter_name == "export"

    realm = open_adapter(str(root), adapter="realm")
    assert isinstance(realm, RealmAdapter)
    assert realm.adapter_name == "realm"

    upper = open_adapter(str(root), adapter="  EXPORT ")
    assert isinstance(upper, ExportAdapter)

    custom = open_adapter(str(root), writeback_path=str(tmp_path / "wb"))
    assert custom.writeback_path == str(tmp_path / "wb")

    with pytest.raises(AdapterError, match="Unknown MarginNote adapter"):
        open_adapter(str(root), adapter="realm2")


def test_export_adapter_rejects_missing_directory(tmp_path) -> None:
    with pytest.raises(AdapterError, match="not a directory"):
        ExportAdapter(str(tmp_path / "does-not-exist"))


def test_export_adapter_parses_markdown_documents(tmp_path) -> None:
    adapter = _make_adapter(tmp_path, {"doc.md": SAMPLE_MD})
    notebook = adapter.load()

    assert notebook.name == "notebook"
    assert len(notebook.documents) == 1
    document = notebook.documents[0]
    assert document.id == "doc.md"
    assert document.name == "doc"
    assert document.highlight_count == 3
    assert document.note_count == 3

    highlights = notebook.highlights
    assert [item.text for item in highlights] == [
        "First highlight text #core",
        "Second highlight #extra",
        "Third highlight",
    ]
    first, second, third = highlights
    assert first.page == 12
    assert first.color == "red"
    assert first.tags == ["core"]
    assert first.section == "Chapter 1"
    assert second.page is None
    assert second.color == ""
    assert third.page == 30
    assert third.section == "Chapter 2"

    notes = notebook.notes
    assert [item.text for item in notes] == [
        "comment one #core",
        "plain standalone note",
        "thought without page",
    ]
    comment, standalone, trailing = notes
    assert comment.highlight_id == first.id
    assert first.note_id == comment.id
    assert first.tags == ["core"]
    assert standalone.highlight_id == second.id
    assert second.note_id == standalone.id
    assert trailing.highlight_id == third.id
    assert trailing.page == 30
    assert adapter.tags() == [{"tag": "core", "count": 2}, {"tag": "extra", "count": 1}]


def test_export_adapter_parses_opml_mindmap(tmp_path) -> None:
    adapter = _make_adapter(tmp_path, {"map.opml": SAMPLE_OPML})
    notebook = adapter.load()

    assert len(notebook.mindmap) == 4
    by_title = {node.title: node for node in notebook.mindmap}
    root_a = by_title["Root A"]
    root_b = by_title["Root B"]
    child1 = by_title["Child A1"]
    child2 = by_title["Child A2"]

    assert root_a.parent_id == ""
    assert root_b.parent_id == ""
    assert root_a.note == "root note"
    assert child2.note == "alt note"
    assert root_a.children == [child1.id, child2.id]
    assert child1.parent_id == root_a.id
    assert child2.parent_id == root_a.id

    assert root_a.id in {document.id for document in notebook.documents}
    assert root_b.id in {document.id for document in notebook.documents}

    tree = adapter.mindmap(root_a.id, depth=1)
    assert tree["root_ids"] == [root_a.id]
    assert {node["id"] for node in tree["nodes"]} == {root_a.id, child1.id, child2.id}

    full = adapter.mindmap()
    assert set(full["root_ids"]) == {root_a.id, root_b.id}

    with pytest.raises(AdapterError, match="not found"):
        adapter.mindmap("no-such-node")


def test_export_adapter_opml_without_title_and_empty_body(tmp_path) -> None:
    adapter = _make_adapter(
        tmp_path,
        {
            "bare.opml": '<?xml version="1.0"?><opml><body><outline/></body></opml>',
            "empty.opml": '<?xml version="1.0"?><opml><body/></opml>',
        },
    )
    notebook = adapter.load()
    assert [node.title for node in notebook.mindmap] == ["(untitled)"]
    assert notebook.mindmap[0].note == ""
    assert notebook.documents
    assert notebook.documents[0].id == notebook.mindmap[0].id


def test_export_adapter_tolerates_missing_fields(tmp_path) -> None:
    adapter = _make_adapter(
        tmp_path,
        {
            "plain.md": "no frontmatter, no heading\n\n> quote without page or color\n",
        },
    )
    notebook = adapter.load()
    assert len(notebook.documents) == 1
    document = notebook.documents[0]
    assert document.name == "plain"
    assert document.highlight_count == 1
    assert document.note_count == 1

    highlight = notebook.highlights[0]
    assert highlight.page is None
    assert highlight.color == ""
    assert highlight.tags == []
    assert highlight.section == ""
    assert highlight.note_id == ""
    note = notebook.notes[0]
    assert note.page is None
    assert note.highlight_id == ""
    assert note.tags == []

    front, body = split_frontmatter("---\ntitle: T\ntags: [a, b]\n---\n\nBody here\n")
    assert front == {"title": "T", "tags": ["a", "b"]}
    assert body == "Body here\n"


def test_export_adapter_degrades_on_malformed_files(tmp_path) -> None:
    corrupt_opml = b"<opml><body><outline text='broken></body></opml>"
    adapter = _make_adapter(
        tmp_path,
        {
            "good.md": "> healthy highlight (p. 1)\n",
            "broken.opml": corrupt_opml,
            "empty.md": "",
            "frontmatter-only.md": "---\ntitle: x\n---\n",
            "bad-bytes.md": b"quote \xff\xfe broken bytes",
        },
    )
    notebook = adapter.load()
    warnings = {item.code: item for item in adapter.warnings}
    assert "corrupt_opml" in warnings
    assert "empty_file" in warnings
    assert "encoding" in warnings

    assert notebook.mindmap == []
    assert "good.md" in {document.id for document in notebook.documents}
    assert "frontmatter-only.md" in {document.id for document in notebook.documents}
    assert "empty.md" not in {document.id for document in notebook.documents}
    assert any(item.path == "empty.md" and item.code == "empty_file" for item in adapter.warnings)

    diagnosis = adapter.diagnose()
    assert diagnosis.compatible is True
    assert diagnosis.status_hint == "ready"
    assert diagnosis.warnings == list(adapter._warnings)
    assert "empty_file" in {item.code for item in diagnosis.warnings}


def test_export_adapter_unreadable_file_marks_degraded(tmp_path) -> None:
    adapter = _make_adapter(
        tmp_path,
        {
            "good.md": "> healthy highlight (p. 1)\n",
            "locked.md": "secret highlight (p. 2)\n",
        },
    )
    locked = adapter._root / "locked.md"
    locked.chmod(0o000)
    try:
        notebook = adapter.load()
        assert len(notebook.documents) == 1
        codes = {item.code for item in adapter.warnings}
        assert "unreadable" in codes

        diagnosis = adapter.diagnose()
        assert diagnosis.compatible is True
        assert diagnosis.status_hint == "degraded"
        assert diagnosis.recover_actions == ["fix_permissions"]
    finally:
        locked.chmod(0o644)


def test_export_adapter_empty_notebook_requires_user_action(tmp_path) -> None:
    adapter = _make_adapter(tmp_path, {})
    notebook = adapter.load()
    assert notebook.documents == []
    assert notebook.highlights == []

    diagnosis = adapter.diagnose()
    assert diagnosis.compatible is False
    assert diagnosis.status_hint == "requires_user_action"
    assert diagnosis.recover_actions == ["export_markdown_opml"]
    assert diagnosis.error
    public = diagnosis.to_public_dict()
    assert public["ok"] is False
    assert public["error"]
    assert public["counts"]["documents"] == 0

    assert adapter.source_file_count == 0
    assert len(adapter.content_hash) == 24
    assert adapter.cursor == adapter.content_hash

    with pytest.raises(AdapterError, match="needs a query or a tag"):
        adapter.search("   ")
    with pytest.raises(AdapterError, match="needs an id"):
        adapter.read_item("  ")
    with pytest.raises(AdapterError, match="was not found"):
        adapter.read_item("missing-id")


def test_export_adapter_diagnose_ready_public_dict(tmp_path) -> None:
    adapter = _make_adapter(tmp_path, {"doc.md": SAMPLE_MD})
    diagnosis = adapter.diagnose()

    assert diagnosis.compatible is True
    assert diagnosis.status_hint == "ready"
    assert diagnosis.error == ""
    assert diagnosis.adapter == "export"
    assert diagnosis.export_format == "markdown-opml"
    assert diagnosis.file_count == 1
    assert diagnosis.document_count == 1
    assert diagnosis.highlight_count == 3
    assert diagnosis.note_count == 3
    assert diagnosis.writeback_available is True
    assert diagnosis.notebook_name == "notebook"
    assert diagnosis.cursor == diagnosis.content_hash
    assert diagnosis.recover_actions == []

    capabilities = diagnosis.capabilities
    assert capabilities.can_read is True
    assert capabilities.official_write is False
    assert capabilities.write_mode == WRITE_MODE_IMPORT_QUEUE
    assert capabilities.write_block_reason

    public = diagnosis.to_public_dict()
    assert public["ok"] is True
    assert public["error"] is None
    assert public["counts"] == {
        "documents": 1,
        "highlights": 3,
        "notes": 3,
        "mindmap_nodes": 0,
    }
    assert public["capabilities"]["adapter"] == "export"


def test_export_adapter_writeback_unavailable_reports_block(tmp_path) -> None:
    blocker = tmp_path / "blocker.txt"
    blocker.write_text("not a directory", encoding="utf-8")
    adapter = _make_adapter(tmp_path, {"doc.md": "> hi (p. 1)\n"}, writeback_path=str(blocker))
    assert adapter._writeback_available() is False
    capabilities = adapter.capabilities()
    assert capabilities.write_block_reason == "Writeback folder is not writable."
    diagnosis = adapter.diagnose()
    assert diagnosis.writeback_available is False
    assert "choose_writeback_folder" in diagnosis.recover_actions


def test_export_adapter_search_query_tag_and_limit(tmp_path) -> None:
    files = {
        "doc.md": SAMPLE_MD,
        "map.opml": SAMPLE_OPML,
    }
    adapter = _make_adapter(tmp_path, files)

    hits = adapter.search("first highlight")
    assert hits
    assert hits[0]["kind"] == "highlight"
    assert hits[0]["text"] == "First highlight text #core"

    tagged = adapter.search("", tag="#core")
    assert tagged
    assert all("core" in item["tags"] for item in tagged)

    mindmap_hits = adapter.search("root", tag="")
    assert any(item["kind"] == "mindmap" for item in mindmap_hits)
    assert not any(item["kind"] == "mindmap" for item in adapter.search("root", tag="core"))

    limited = adapter.search("", tag="core", limit=1)
    assert len(limited) == 1

    assert adapter.search("no-such-needle-anywhere") == []


def test_export_adapter_writeback_notes_and_summaries(tmp_path) -> None:
    adapter = _make_adapter(tmp_path, {"doc.md": "> hi (p. 1)\n"})
    write_root = adapter._root / WRITEBACK_DIRNAME

    rel = adapter.create_note("notes/first", "body text")
    assert rel == "notes/first.md"
    created = write_root / "notes" / "first.md"
    assert created.read_text(encoding="utf-8").endswith("body text\n")
    assert "source: marginnote" in created.read_text(encoding="utf-8")

    with pytest.raises(AdapterError, match="already exists"):
        adapter.create_note("notes/first", "again")

    assert adapter.append_note("notes/first.md", "more") == rel
    assert adapter.append_note("notes/first", "even more") == rel
    assert created.read_text(encoding="utf-8").endswith("even more")

    with pytest.raises(AdapterError, match="was not found"):
        adapter.append_note("notes/absent", "x")
    with pytest.raises(AdapterError, match="needs a note path"):
        adapter.append_note("  ", "x")

    summary_rel = adapter.create_summary("Notebook Overview!", "part one")
    assert summary_rel == "summaries/Notebook-Overview.md"
    adapter.create_summary("Notebook Overview!", "part two")
    summary = write_root / "summaries" / "Notebook-Overview.md"
    text = summary.read_text(encoding="utf-8")
    assert "part one" in text
    assert "part two" in text
    assert "kind: summary" in text

    empty_rel = adapter.create_summary("   ", "scoped to notebook")
    assert empty_rel == "summaries/notebook.md"


def test_export_adapter_rejects_unsafe_paths(tmp_path) -> None:
    adapter = _make_adapter(tmp_path, {"doc.md": "> hi (p. 1)\n"})
    with pytest.raises(AdapterError, match="needs a non-empty path"):
        adapter.create_note("  ", "x")
    with pytest.raises(AdapterError, match="escapes the notebook"):
        adapter.create_note("../escape", "x")
    with pytest.raises(AdapterError, match="escapes the notebook"):
        adapter.create_note("notes/../../escape", "x")


def test_export_adapter_cache_refreshes_when_files_change(tmp_path) -> None:
    adapter = _make_adapter(tmp_path, {"doc.md": "> hi (p. 1)\n"})
    first = adapter.load()
    assert adapter.load() is first

    _write(adapter._root, "second.md", "> another (p. 2)\n")
    second = adapter.load()
    assert second is not first
    assert len(second.documents) == 2
    assert len(second.highlights) == 2
    assert adapter.source_file_count == 2
    assert adapter.diagnose().file_count == 2


def test_realm_adapter_blocked_contract(tmp_path) -> None:
    adapter = RealmAdapter(str(tmp_path / "nb"))
    assert adapter.adapter_name == "realm"

    with pytest.raises(AdapterError, match="not implemented"):
        adapter.load()
    with pytest.raises(AdapterError, match="not implemented"):
        adapter.search("anything")
    with pytest.raises(AdapterError, match="not implemented"):
        adapter.create_note("x.md", "body")

    capabilities = adapter.capabilities()
    assert capabilities.can_read is False
    assert capabilities.can_watch is False
    assert capabilities.write_mode == WRITE_MODE_NONE
    assert capabilities.write_block_reason

    diagnosis = adapter.diagnose()
    assert diagnosis.compatible is False
    assert diagnosis.adapter == "realm"
    assert diagnosis.export_format == "realm"
    assert diagnosis.status_hint == "disconnected"
    assert diagnosis.recover_actions == ["use_export_adapter"]
    assert diagnosis.error
    assert diagnosis.to_public_dict()["ok"] is False
    assert diagnosis.notebook_name == "nb"


def test_base_adapter_default_diagnose_and_capabilities(tmp_path) -> None:
    adapter = _minimal_adapter(tmp_path)
    assert adapter.source_signature() == ()

    capabilities = adapter.capabilities()
    assert capabilities.adapter == "export"
    assert capabilities.can_read is True
    assert capabilities.write_mode == WRITE_MODE_IMPORT_QUEUE

    diagnosis = adapter.diagnose()
    assert diagnosis.compatible is False
    assert diagnosis.adapter == "export"
    assert diagnosis.file_count == 0
    assert diagnosis.cursor == ""
    assert diagnosis.content_hash == ""
    assert diagnosis.warnings == []
    assert diagnosis.status_hint == "requires_user_action"
    assert diagnosis.recover_actions == ["export_markdown_opml"]
    assert diagnosis.error


def test_diagnostics_models_and_helpers() -> None:
    assert PUBLIC_ADAPTERS == {"export"}
    assert KNOWN_ADAPTERS == {"export", "realm"}

    assert display_name_for("/tmp/My Book") == "My Book"
    assert display_name_for("") == "notebook"
    assert display_name_for("notebook") == "notebook"

    warning = ParseWarning(path="a.md", code="empty_file", message="File is empty.")
    assert warning.to_dict() == {
        "path": "a.md",
        "code": "empty_file",
        "message": "File is empty.",
    }

    caps = AdapterCapabilities(adapter="export")
    assert caps.can_read is False
    assert caps.write_mode == WRITE_MODE_IMPORT_QUEUE
    assert caps.write_block_reason == ""
    assert caps.to_dict()["adapter"] == "export"

    diagnosis = AdapterDiagnostics(
        compatible=True,
        adapter="export",
        export_format="markdown-opml",
        file_count=1,
        document_count=1,
        highlight_count=0,
        note_count=0,
        mindmap_count=0,
        writeback_available=True,
        cursor="abc",
        content_hash="abc",
        capabilities=caps,
    )
    public = diagnosis.to_public_dict()
    assert public["ok"] is True
    assert public["error"] is None
    assert public["cursor"] == "abc"
    assert public["warnings"] == []

    broken = AdapterDiagnostics(
        compatible=False,
        adapter="export",
        export_format="markdown-opml",
        file_count=0,
        document_count=0,
        highlight_count=0,
        note_count=0,
        mindmap_count=0,
        writeback_available=False,
        cursor="",
        content_hash="",
        capabilities=caps,
        status_hint="requires_user_action",
        error="broken",
    )
    assert broken.to_public_dict()["ok"] is False
    assert broken.to_public_dict()["error"] == "broken"


def test_split_frontmatter_variants() -> None:
    front, body = split_frontmatter("---\ntitle: T\ntags: [a, b]\n---\n\nBody here\n")
    assert front == {"title": "T", "tags": ["a", "b"]}
    assert body == "Body here\n"

    plain, body_plain = split_frontmatter("plain text only")
    assert plain == {}
    assert body_plain == "plain text only"

    front_list, body_list = split_frontmatter("---\n- a\n- b\n---\nBody\n")
    assert front_list == {}
    assert body_list == "---\n- a\n- b\n---\nBody\n"

    front_bad, body_bad = split_frontmatter("---\ntitle: [unclosed\n---\nBody\n")
    assert front_bad == {}
    assert body_bad == "---\ntitle: [unclosed\n---\nBody\n"
