"""Persistence tests for KB ``github_sources`` metadata.

Mirrors the pattern of ``test_linked_folder_sync.py``: exercises the
KnowledgeBaseManager add/remove/get/update lifecycle for GitHub source
entries, verifying that writes survive a fresh manager instance (simulating
a process restart).
"""

from __future__ import annotations

import json
from pathlib import Path

from deeptutor.knowledge.manager import KnowledgeBaseManager


def _make_manager_with_kb(tmp_path: Path) -> tuple[KnowledgeBaseManager, Path, str]:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    kb_dir = manager.base_dir / "kb"
    kb_dir.mkdir()
    manager.register_knowledge_base("kb")
    return manager, kb_dir / "metadata.json", "kb"


# ── add_github_source ─────────────────────────────────────────────────


def test_add_github_source_persists(tmp_path: Path) -> None:
    manager, metadata_file, kb = _make_manager_with_kb(tmp_path)

    info = manager.add_github_source(kb, "owner/repo", branch="main", path="docs/")

    assert info["repo"] == "owner/repo"
    assert info["branch"] == "main"
    assert info["path"] == "docs/"
    assert info["enabled"] is True
    assert info["last_sync_status"] == "pending"

    on_disk = json.loads(metadata_file.read_text(encoding="utf-8"))
    assert len(on_disk["github_sources"]) == 1
    assert on_disk["github_sources"][0]["repo"] == "owner/repo"


def test_add_github_source_idempotent(tmp_path: Path) -> None:
    manager, _meta, kb = _make_manager_with_kb(tmp_path)

    info1 = manager.add_github_source(kb, "owner/repo", branch="main", path="docs/")
    info2 = manager.add_github_source(kb, "owner/repo", branch="main", path="docs/")

    assert info1["id"] == info2["id"]
    assert len(manager.get_github_sources(kb)) == 1


def test_add_github_source_normalises_repo(tmp_path: Path) -> None:
    manager, _meta, kb = _make_manager_with_kb(tmp_path)

    info = manager.add_github_source(kb, "https://github.com/owner/repo.git")
    assert info["repo"] == "owner/repo"


def test_add_github_source_survives_reload(tmp_path: Path) -> None:
    manager, _meta, kb = _make_manager_with_kb(tmp_path)
    manager.add_github_source(kb, "owner/repo", branch="dev", path="wiki/")

    reloaded = KnowledgeBaseManager(base_dir=str(manager.base_dir))
    sources = reloaded.get_github_sources(kb)
    assert len(sources) == 1
    assert sources[0]["repo"] == "owner/repo"
    assert sources[0]["branch"] == "dev"


# ── remove_github_source ──────────────────────────────────────────────


def test_remove_github_source(tmp_path: Path) -> None:
    manager, _meta, kb = _make_manager_with_kb(tmp_path)
    info = manager.add_github_source(kb, "owner/repo")

    assert manager.remove_github_source(kb, info["id"]) is True
    assert manager.get_github_sources(kb) == []


def test_remove_github_source_not_found(tmp_path: Path) -> None:
    manager, _meta, kb = _make_manager_with_kb(tmp_path)
    assert manager.remove_github_source(kb, "nope") is False


# ── update_github_source_state ────────────────────────────────────────


def test_update_source_state_persists(tmp_path: Path) -> None:
    manager, metadata_file, kb = _make_manager_with_kb(tmp_path)
    info = manager.add_github_source(kb, "owner/repo")

    manager.update_github_source_state(
        kb_name=kb,
        source_id=info["id"],
        last_synced_sha="abc123",
        last_sync_status="success",
        files_synced=5,
    )

    on_disk = json.loads(metadata_file.read_text(encoding="utf-8"))
    src = on_disk["github_sources"][0]
    assert src["last_synced_sha"] == "abc123"
    assert src["last_sync_status"] == "success"
    assert src["files_synced"] == 5


def test_update_source_state_survives_reload(tmp_path: Path) -> None:
    manager, _meta, kb = _make_manager_with_kb(tmp_path)
    info = manager.add_github_source(kb, "owner/repo")

    manager.update_github_source_state(
        kb_name=kb, source_id=info["id"], last_sync_status="error", last_sync_error="boom"
    )

    reloaded = KnowledgeBaseManager(base_dir=str(manager.base_dir))
    sources = reloaded.get_github_sources(kb)
    assert sources[0]["last_sync_status"] == "error"
    assert sources[0]["last_sync_error"] == "boom"


# ── get_all_github_sources ────────────────────────────────────────────


def test_get_all_sources_across_kbs(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    for name in ("kb-a", "kb-b"):
        kb_dir = manager.base_dir / name
        kb_dir.mkdir()
        manager.register_knowledge_base(name)

    manager.add_github_source("kb-a", "a/repo")
    manager.add_github_source("kb-b", "b/repo")

    all_sources = manager.get_all_github_sources()
    kb_names = {kb for kb, _s in all_sources}
    assert kb_names == {"kb-a", "kb-b"}
    assert {s["repo"] for _kb, s in all_sources} == {"a/repo", "b/repo"}
