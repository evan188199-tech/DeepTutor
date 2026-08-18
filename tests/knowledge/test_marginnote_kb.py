"""Manager handling of connected MarginNote KBs (``type: marginnote``)."""

from __future__ import annotations

import json
from pathlib import Path

from deeptutor.knowledge.kb_types import CONNECTED_KB_TYPES, MARGINNOTE_KB_TYPE
from deeptutor.knowledge.manager import KnowledgeBaseManager


def test_marginnote_type_is_connected() -> None:
    assert MARGINNOTE_KB_TYPE in CONNECTED_KB_TYPES


def test_register_marginnote_notebook(tmp_path: Path) -> None:
    export = tmp_path / "mn-export"
    export.mkdir()
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    entry = manager.register_marginnote_notebook("Notes", str(export), adapter="export")
    assert entry["type"] == MARGINNOTE_KB_TYPE
    assert entry["notebook_path"] == str(export.resolve())
    assert entry["adapter"] == "export"
    meta = manager.get_metadata("Notes")
    assert meta["type"] == "marginnote"
    assert meta["notebook_path"] == str(export.resolve())


def test_marginnote_entry_survives_orphan_prune(tmp_path: Path) -> None:
    export = tmp_path / "mn-export"
    export.mkdir()
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    manager.register_marginnote_notebook("Notes", str(export))
    assert "Notes" in manager.list_knowledge_bases()
    persisted = json.loads(manager.config_file.read_text(encoding="utf-8"))
    assert "Notes" in persisted.get("knowledge_bases", {})


def test_reconcile_does_not_clobber_marginnote_entry(tmp_path: Path) -> None:
    export = tmp_path / "mn-export"
    export.mkdir()
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    manager.config.setdefault("knowledge_bases", {})["Notes"] = {
        "type": "marginnote",
        "notebook_path": str(export),
        "adapter": "export",
        "rag_provider": "pageindex",
    }
    manager._save_config()
    reloaded = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    entry = reloaded.config["knowledge_bases"]["Notes"]
    assert entry["type"] == "marginnote"
    assert entry.get("needs_reindex") is not True
    assert entry.get("rag_provider") == "pageindex"
