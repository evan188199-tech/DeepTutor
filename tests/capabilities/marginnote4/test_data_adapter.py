from __future__ import annotations

from pathlib import Path

from deeptutor.capabilities.marginnote4.data.export_adapter import ExportAdapter


def _write_notebook(root: Path) -> None:
    (root / "Book.md").write_text(
        """# Chapter One

> Light is converted into chemical energy. (p. 12) [color: yellow] #biology

Plants store energy as glucose. #plant
""",
        encoding="utf-8",
    )
    (root / "map.opml").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0"><body>
  <outline text="Energy"><outline text="Photosynthesis"/><outline text="Respiration"/></outline>
</body></opml>
""",
        encoding="utf-8",
    )


def test_export_adapter_parses_markdown_and_opml(tmp_path: Path) -> None:
    _write_notebook(tmp_path)
    adapter = ExportAdapter(str(tmp_path))
    notebook = adapter.load()
    assert len(notebook.documents) == 1
    assert len(notebook.highlights) == 1
    assert len(notebook.notes) == 1
    assert len(notebook.mindmap) == 3
    assert adapter.list_documents()[0]["highlight_count"] == 1
    assert adapter.read_highlights()[0]["page"] == 12
    assert adapter.tags()[0]["tag"] in {"biology", "plant"}
    assert adapter.mindmap()["root_ids"]


def test_export_adapter_diagnostics_and_writeback_guard(tmp_path: Path) -> None:
    _write_notebook(tmp_path)
    diagnostics = ExportAdapter(str(tmp_path)).diagnose()
    assert diagnostics.compatible is True
    assert diagnostics.cursor == diagnostics.content_hash
    assert diagnostics.capabilities.write_mode == "import_queue"
