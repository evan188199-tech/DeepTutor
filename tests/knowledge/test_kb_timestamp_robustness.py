"""Focused tests for KB timestamp robustness.

``_entry_updated_after`` compares a config entry's ``updated_at`` against a
naive-local cutoff. An aware (UTC) ``updated_at`` — produced by the ISO
write points in ``add_documents``/``initializer`` — must not crash the
orphan-prune path, and unparseable values must degrade to "old" instead of
raising.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from deeptutor.knowledge.add_documents import DocumentAdder
from deeptutor.knowledge.initializer import KnowledgeBaseInitializer
from deeptutor.knowledge.manager import KnowledgeBaseManager, _entry_updated_after


def _cutoff() -> datetime:
    return datetime.now() - timedelta(seconds=60)


def test_aware_updated_at_survives_naive_cutoff_comparison() -> None:
    entry = {"updated_at": datetime.now(timezone.utc).isoformat()}
    assert _entry_updated_after(entry, _cutoff()) is True


def test_aware_past_updated_at_is_not_recent() -> None:
    entry = {"updated_at": datetime.now(timezone.utc).isoformat()}
    assert _entry_updated_after(entry, datetime.now() + timedelta(seconds=60)) is False


def test_malformed_updated_at_degrades_to_old() -> None:
    for raw in ("not-a-timestamp", "2026-13-45T99:99:99", "", "05/10/2026 9am"):
        assert _entry_updated_after({"updated_at": raw}, _cutoff()) is False


def test_non_string_updated_at_degrades_to_old() -> None:
    for raw in (None, 1760000000, datetime.now()):
        assert _entry_updated_after({"updated_at": raw}, _cutoff()) is False


def test_list_keeps_recent_aware_entry_with_missing_dir(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    manager.config.setdefault("knowledge_bases", {})["in-flight"] = {
        "path": "in-flight",
        "status": "initializing",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    manager._save_config()

    assert manager.list_knowledge_bases() == ["in-flight"]


def test_document_adder_writes_aware_iso_last_updated(tmp_path: Path) -> None:
    kb_dir = tmp_path / "kb"
    (kb_dir / "raw").mkdir(parents=True)
    version_dir = kb_dir / "version-1"
    version_dir.mkdir()
    (version_dir / "docstore.json").write_text("{}", encoding="utf-8")
    (version_dir / "index_store.json").write_text("{}", encoding="utf-8")
    (version_dir / "meta.json").write_text(
        json.dumps({"provider": "llamaindex", "signature": "llamaindex", "version": "version-1"}),
        encoding="utf-8",
    )

    adder = DocumentAdder(kb_name="kb", base_dir=str(tmp_path), rag_provider="llamaindex")
    adder.update_metadata(2)

    metadata = json.loads((kb_dir / "metadata.json").read_text(encoding="utf-8"))
    parsed = datetime.fromisoformat(metadata["last_updated"])
    assert parsed.tzinfo is not None


def test_initializer_writes_aware_iso_last_updated(tmp_path: Path) -> None:
    initializer = KnowledgeBaseInitializer(kb_name="demo", base_dir=str(tmp_path))
    initializer._update_metadata_with_provider("lightrag")

    metadata = json.loads((tmp_path / "demo" / "metadata.json").read_text(encoding="utf-8"))
    parsed = datetime.fromisoformat(metadata["last_updated"])
    assert parsed.tzinfo is not None
