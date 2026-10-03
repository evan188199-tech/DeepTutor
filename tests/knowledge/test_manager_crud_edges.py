"""CRUD edge tests for ``KnowledgeBaseManager`` (coverage gap #8, 329 missing).

Scope: KB-level add / delete / query boundaries only — the routing layer has
its own card. Three groups:

1. Add/delete → list & count consistency (auto-discovery, delete bookkeeping,
   default-KB bookkeeping, manifest-defined document counts).
2. Name conflicts (reserved characters, reserved-by-move IDs, duplicate
   registration, missing directory).
3. Empty-KB boundaries (fresh manager, empty/corrupt config file, grace
   window, unindexed directory, empty KB dir).

Two tests are intentionally *failing* against ``origin/main`` and are the
contract for the follow-up fix card — each is marked with
``xfail_candidate`` in its docstring:

* ``test_delete_default_kb_clears_centralized_default`` — deleting the KB
  that ``defaults.default_kb`` points at leaves the stale name behind in
  ``kb_config.json``; ``manager.get_default()`` only self-heals by accident
  (membership fallback), so any direct consumer of
  ``KnowledgeBaseConfigService.get_default_kb()`` still sees the deleted KB.
* ``test_register_duplicate_name_preserves_existing_metadata`` —
  re-registering an existing name replaces the entry with a bare
  ``{"path", "description"}`` dict, wiping ``status`` / ``created_at`` /
  ``rag_provider``. ``register_connected_entry`` already treats registration
  as idempotent (returns ``False``, leaves the entry untouched); the plain
  path must not downgrade metadata either.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path

import pytest

from deeptutor.knowledge.manager import KnowledgeBaseManager
import deeptutor.services.config as config_service_module
from deeptutor.services.config.knowledge_base_config import (
    KnowledgeBaseConfigService,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _seed_kb(
    manager: KnowledgeBaseManager,
    name: str,
    *,
    description: str = "",
    status: str = "ready",
    updated_at: str | None = None,
    raw_files: int = 0,
) -> Path:
    """Create an on-disk KB directory plus its ``kb_config.json`` entry."""
    kb_dir = manager.base_dir / name
    (kb_dir / "raw").mkdir(parents=True, exist_ok=True)
    (kb_dir / "version-1").mkdir(parents=True, exist_ok=True)
    (kb_dir / "version-1" / "docstore.json").write_text("{}", encoding="utf-8")
    for i in range(raw_files):
        (kb_dir / "raw" / f"doc-{i}.txt").write_text(f"content {i}", encoding="utf-8")
    entry: dict = {"path": name, "description": description}
    if status:
        entry["status"] = status
    if updated_at:
        entry["updated_at"] = updated_at
    manager.config.setdefault("knowledge_bases", {})[name] = entry
    manager._save_config()
    return kb_dir


def _read_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _persisted_kbs(manager: KnowledgeBaseManager) -> dict:
    """The persisted ``knowledge_bases`` map; ``{}`` when never written."""
    if not manager.config_file.exists():
        return {}
    return _read_config(manager.config_file).get("knowledge_bases", {})


@pytest.fixture
def central_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> KnowledgeBaseConfigService:
    """A ``KnowledgeBaseConfigService`` isolated to ``tmp_path``.

    ``set_default`` / ``get_default`` do a lazy ``from deeptutor.services.config
    import get_kb_config_service``, so patching the module attribute is enough
    to keep the test off the developer's real ``data/`` tree.
    """
    service = KnowledgeBaseConfigService(config_path=tmp_path / "central" / "kb_config.json")
    monkeypatch.setattr(config_service_module, "get_kb_config_service", lambda: service)
    return service


# ---------------------------------------------------------------------------
# 1. Add / delete → list & count consistency
# ---------------------------------------------------------------------------


def test_add_then_delete_keeps_list_and_config_consistent(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    _seed_kb(manager, "alpha")
    # "beta" exists only on disk — list_knowledge_bases must auto-discover it.
    # Discovery probes for genuine provider output, so the version needs both
    # LlamaIndex store files (docstore.json alone is not "ready" to the probe).
    beta_dir = manager.base_dir / "beta"
    (beta_dir / "raw").mkdir(parents=True)
    (beta_dir / "version-1").mkdir(parents=True)
    (beta_dir / "version-1" / "docstore.json").write_text("{}", encoding="utf-8")
    (beta_dir / "version-1" / "index_store.json").write_text("{}", encoding="utf-8")

    assert manager.list_knowledge_bases() == ["alpha", "beta"]

    assert manager.delete_knowledge_base("alpha", confirm=True) is True

    assert manager.list_knowledge_bases() == ["beta"]
    assert not (manager.base_dir / "alpha").exists()
    persisted = _persisted_kbs(manager)
    assert "alpha" not in persisted
    assert "beta" in persisted


def test_get_info_document_count_follows_manifest_definition(tmp_path: Path) -> None:
    """``statistics.raw_documents`` is the canonical manifest count: every
    non-hidden regular file under ``raw/`` (recursively), nothing else."""
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    _seed_kb(manager, "docs", raw_files=2)
    raw_dir = manager.base_dir / "docs" / "raw"
    (raw_dir / "sub").mkdir()
    (raw_dir / "sub" / "nested.txt").write_text("nested", encoding="utf-8")
    (raw_dir / ".DS_Store").write_text("junk", encoding="utf-8")

    info = manager.get_info("docs")
    assert info["statistics"]["raw_documents"] == 3

    (raw_dir / "late.txt").write_text("late", encoding="utf-8")
    assert manager.get_info("docs")["statistics"]["raw_documents"] == 4

    (raw_dir / "late.txt").unlink()
    assert manager.get_info("docs")["statistics"]["raw_documents"] == 3


def test_delete_unknown_kb_raises(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    with pytest.raises(ValueError, match="not found"):
        manager.delete_knowledge_base("ghost", confirm=True)


def test_set_default_requires_listed_kb(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    _seed_kb(manager, "only")
    with pytest.raises(ValueError, match="not found"):
        manager.set_default("never-created")
    manager.set_default("only")


def test_update_kb_status_auto_registers_and_persists(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    manager.update_kb_status("incoming", "processing", progress={"stage": "parsing"})

    entry = manager.get_kb_entry("incoming")
    assert entry is not None
    assert entry["status"] == "processing"
    assert entry["path"] == "incoming"
    # The directory does not exist yet, but the entry was just written — the
    # 60s orphan-prune grace must keep it listed mid-creation.
    assert manager.list_knowledge_bases() == ["incoming"]
    assert "incoming" in _read_config(manager.config_file).get("knowledge_bases", {})


def test_delete_default_kb_clears_centralized_default(
    central_service: KnowledgeBaseConfigService, tmp_path: Path
) -> None:
    """xfail_candidate — deleting the default KB leaves a stale
    ``defaults.default_kb`` pointing at the deleted name.

    The manager is the one component that deletes KBs (CLI ``delete`` and both
    the knowledge and subagents routers go through it), yet it never tells
    ``KnowledgeBaseConfigService`` — whose singleton keeps serving the deleted
    name from ``get_default_kb()``. ``manager.get_default()`` only recovers via
    its membership fallback, which is an accident of one caller, not a
    contract. Expected: after deleting the KB the persisted default is either
    ``None`` or another listed KB — never the deleted one.
    """
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    _seed_kb(manager, "alpha")
    _seed_kb(manager, "beta")

    manager.set_default("alpha")
    assert central_service.get_default_kb() == "alpha"

    manager.delete_knowledge_base("alpha", confirm=True)

    # The manager-facing read self-heals (documents the fallback contract)…
    assert manager.get_default() == "beta"
    # …but the persisted default must not keep naming a deleted KB.
    assert central_service.get_default_kb() != "alpha"


# ---------------------------------------------------------------------------
# 2. Name conflicts
# ---------------------------------------------------------------------------


def test_register_rejects_reserved_characters(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    _seed_kb(manager, "alpha")
    with pytest.raises(ValueError, match="reserved characters"):
        manager.register_knowledge_base("bad/name")
    assert manager.list_knowledge_bases() == ["alpha"]
    assert "bad/name" not in _persisted_kbs(manager)


def test_register_duplicate_name_preserves_existing_metadata(tmp_path: Path) -> None:
    """xfail_candidate — re-registering an existing name currently replaces
    the entry with a bare ``{"path", "description"}``, silently wiping
    ``status`` / ``created_at`` / ``rag_provider``.

    ``register_connected_entry`` already defines the contract: registration is
    idempotent and must not clobber an existing entry. The plain path is used
    by the manager CLI, so re-running a create command must not downgrade a
    ready KB to an unstatused one. Expected: description is refreshed but
    operational metadata survives.
    """
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    kb_dir = _seed_kb(manager, "alpha", description="old", status="ready")
    entry_before = manager.get_kb_entry("alpha")
    entry_before["created_at"] = "2026-01-01T00:00:00"
    manager.config["knowledge_bases"]["alpha"] = entry_before
    manager._save_config()

    manager.register_knowledge_base("alpha", description="refreshed")

    entry = manager.get_kb_entry("alpha")
    assert entry["description"] == "refreshed"
    assert entry["status"] == "ready"
    assert entry["created_at"] == "2026-01-01T00:00:00"
    assert kb_dir.exists()


def test_register_name_reserved_by_move_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A name that aliases a saved moved-KB redirect must be refused before
    the directory check, and a manager outside any workspace catalog must not
    trip the guard."""
    import deeptutor.services.workspace.knowledge as workspace_knowledge

    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))

    monkeypatch.setattr(workspace_knowledge, "workspace_id_for_kb_base_dir", lambda _b: "ws-1")
    monkeypatch.setattr(workspace_knowledge, "qualified_kb_id", lambda name, ws: f"{name}@{ws}")
    monkeypatch.setattr(
        workspace_knowledge,
        "canonical_kb_id",
        lambda rid: "renamed@ws-1" if rid == "alpha@ws-1" else rid,
    )
    with pytest.raises(ValueError, match="reserved by an earlier move"):
        manager.register_knowledge_base("alpha")
    assert manager.list_knowledge_bases() == []

    monkeypatch.setattr(workspace_knowledge, "workspace_id_for_kb_base_dir", lambda _b: None)
    _seed_kb(manager, "alpha")
    manager.register_knowledge_base("alpha", description="outside catalog")
    assert manager.list_knowledge_bases() == ["alpha"]


def test_register_requires_existing_directory(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    with pytest.raises(ValueError, match="does not exist"):
        manager.register_knowledge_base("missing-dir")
    assert manager.list_knowledge_bases() == []
    assert _persisted_kbs(manager) == {}


# ---------------------------------------------------------------------------
# 3. Empty-KB boundaries
# ---------------------------------------------------------------------------


def test_fresh_manager_boundaries(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    assert manager.list_knowledge_bases() == []
    assert manager.get_default() is None
    assert manager.get_metadata() == {}
    assert manager.get_kb_entry("any") is None
    assert manager.get_kb_status("any") is None
    with pytest.raises(ValueError, match="No knowledge base name provided"):
        manager.get_info()


def test_empty_and_corrupt_config_files_are_tolerated(tmp_path: Path) -> None:
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    (empty_dir / "kb_config.json").write_text("", encoding="utf-8")
    manager = KnowledgeBaseManager(base_dir=str(empty_dir))
    assert manager.list_knowledge_bases() == []

    corrupt_dir = tmp_path / "corrupt"
    corrupt_dir.mkdir()
    (corrupt_dir / "kb_config.json").write_text("{not json", encoding="utf-8")
    manager = KnowledgeBaseManager(base_dir=str(corrupt_dir))
    assert manager.list_knowledge_bases() == []
    # The manager stays functional after the bad read.
    _seed_kb(manager, "recovered")
    assert manager.list_knowledge_bases() == ["recovered"]


def test_orphan_prune_honors_grace_window(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    _seed_kb(manager, "mid-init", status="initializing", updated_at=datetime.now().isoformat())
    _seed_kb(
        manager,
        "zombie",
        status="ready",
        updated_at=(datetime.now() - timedelta(days=3)).isoformat(),
    )
    import shutil

    shutil.rmtree(manager.base_dir / "mid-init")
    shutil.rmtree(manager.base_dir / "zombie")

    # The stale entry is pruned; the fresh one survives the 60s grace window.
    assert manager.list_knowledge_bases() == ["mid-init"]
    persisted = _read_config(manager.config_file).get("knowledge_bases", {})
    assert "zombie" not in persisted
    assert "mid-init" in persisted


def test_unindexed_directory_without_entry_is_not_listed(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    (manager.base_dir / "rawonly" / "raw").mkdir(parents=True)
    (manager.base_dir / "__pycache__").mkdir()

    assert manager.list_knowledge_bases() == []
    assert "rawonly" not in _persisted_kbs(manager)


def test_empty_kb_dir_reports_unknown_with_zero_counts(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    (manager.base_dir / "hollow").mkdir()
    manager.config.setdefault("knowledge_bases", {})["hollow"] = {"path": "hollow"}
    manager._save_config()

    info = manager.get_info("hollow")
    assert info["status"] == "unknown"
    assert info["statistics"]["raw_documents"] == 0
    assert info["statistics"]["images"] == 0
    assert info["statistics"]["rag_initialized"] is False

    assert manager.delete_knowledge_base("hollow", confirm=True) is True
    assert manager.list_knowledge_bases() == []
