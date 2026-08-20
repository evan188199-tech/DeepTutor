from __future__ import annotations

from pathlib import Path

from deeptutor.knowledge.kb_types import MARGINNOTE4_KB_TYPE, is_connected_kb
from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.knowledge.manifest import UNAVAILABLE_REMOTE, build_manifest


def test_marginnote4_kb_is_connected_pointer(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(tmp_path)
    entry = manager.register_marginnote4_kb("Research", library_id="mn4-lib-1")

    assert entry["type"] == MARGINNOTE4_KB_TYPE
    assert entry["library_id"] == "mn4-lib-1"
    assert is_connected_kb(entry)
    assert manager.get_metadata("Research")["library_id"] == "mn4-lib-1"

    manifest = build_manifest(
        name="Research",
        kb_dir=tmp_path / "Research",
        entry=entry,
    )
    assert manifest.unavailable == UNAVAILABLE_REMOTE
