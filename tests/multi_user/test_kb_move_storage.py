"""Storage-level contracts of ``services.workspace.kb_move``.

The move is published as one unit: a verified copy, catalog entries, aliases,
and saved assignments. These tests mock the storage seams (snapshot copying,
renames, atomic config writes, cleanup) to prove the published state stays
consistent and that an interrupted move leaves no residue behind.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.multi_user.knowledge_access import current_kb_manager
from deeptutor.services.workspace import ContentWorkspaceService, WorkspaceError, kb_move
from deeptutor.services.workspace.context import workspace_context
from deeptutor.services.workspace.kb_move import move_kb, preview_kb_move
from deeptutor.services.workspace.knowledge import (
    _move_aliases_path,
    canonical_kb_id,
    move_aliases,
    qualified_kb_id,
)


def _make_kb(name: str, marker: bytes) -> None:
    manager = current_kb_manager()
    folder = manager.base_dir / name
    (folder / "raw").mkdir(parents=True)
    (folder / "raw" / "source.pdf").write_bytes(marker)
    (folder / "version-1" / "index").parent.mkdir()
    (folder / "version-1" / "index").write_bytes(b"index:" + marker)
    manager.config = manager._load_config()
    manager.config.setdefault("knowledge_bases", {})[name] = {
        "path": name,
        "rag_provider": "llamaindex",
        "status": "ready",
        "description": "an atlas",
    }
    manager._save_config()


def _staging_dirs(root: Path) -> list[str]:
    return [path.name for path in root.glob(".kb-move-*")]


def _hidden_dirs(root: Path) -> list[str]:
    return [path.name for path in root.glob(".kb-moved-*")]


def _config_payload(root: Path) -> dict:
    return json.loads((root / "kb_config.json").read_text(encoding="utf-8"))


def test_move_publishes_verified_copy_and_drops_source_state(as_user):
    with as_user("alice"):
        _make_kb("atlas", b"source-pixels")
        service = ContentWorkspaceService()
        destination = service.create_workspace("Research")["workspace_id"]
        with workspace_context(destination):
            _make_kb("other", b"keep-me")
        source_root = current_kb_manager().base_dir
        source_id = qualified_kb_id("atlas")
        target_id = qualified_kb_id("atlas", destination)
        consumer = service.create_workspace("Consumer", resources={"knowledge_bases": [source_id]})
        source_entry = _config_payload(source_root)["knowledge_bases"]["atlas"]

        result = move_kb(source_id, destination)

        assert result["status"] == "moved"
        assert result["target_id"] == target_id
        with workspace_context(destination):
            target_root = current_kb_manager().base_dir
            assert (target_root / "atlas" / "raw" / "source.pdf").read_bytes() == b"source-pixels"
            assert (
                target_root / "atlas" / "version-1" / "index"
            ).read_bytes() == b"index:source-pixels"
            assert _config_payload(target_root)["knowledge_bases"]["atlas"] == source_entry
            assert _staging_dirs(target_root) == []
        assert not (source_root / "atlas").exists()
        assert "atlas" not in _config_payload(source_root)["knowledge_bases"]
        assert _hidden_dirs(source_root) == []
        assert move_aliases()[source_id] == target_id
        row = next(
            row for row in service._catalog() if row["workspace_id"] == consumer["workspace_id"]
        )
        assert row["resources"]["knowledge_bases"] == [target_id]


def test_move_hands_off_default_kb_selection_to_target(as_user):
    with as_user("alice"):
        _make_kb("atlas", b"source")
        manager = current_kb_manager()
        manager.config = manager._load_config()
        manager.config["defaults"] = {"default_kb": "atlas"}
        manager._save_config()
        destination = ContentWorkspaceService().create_workspace("Research")["workspace_id"]

        move_kb(qualified_kb_id("atlas"), destination)

        source_config = _config_payload(current_kb_manager().base_dir)
        assert source_config["defaults"]["default_kb"] is None
        with workspace_context(destination):
            target_config = _config_payload(current_kb_manager().base_dir)
        assert target_config["defaults"]["default_kb"] == "atlas"


def test_repeat_move_rewrites_whole_alias_chain_to_newest_target(as_user):
    with as_user("alice"):
        _make_kb("atlas", b"source")
        service = ContentWorkspaceService()
        first = service.create_workspace("Research")["workspace_id"]
        second = service.create_workspace("Archive")["workspace_id"]
        original_id = qualified_kb_id("atlas")
        move_kb(original_id, first)
        first_id = qualified_kb_id("atlas", first)

        move_kb(first_id, second)

        final_id = qualified_kb_id("atlas", second)
        aliases = move_aliases()
        assert aliases[original_id] == final_id
        assert aliases[first_id] == final_id
        assert canonical_kb_id(original_id) == final_id
        assert not (current_kb_manager().base_dir / "atlas").exists()
        with workspace_context(second):
            assert (
                current_kb_manager().base_dir / "atlas" / "raw" / "source.pdf"
            ).read_bytes() == b"source"


def test_same_workspace_move_is_rejected(as_user):
    with as_user("alice"):
        _make_kb("atlas", b"source")
        source_id = qualified_kb_id("atlas")
        plan = preview_kb_move(source_id, "")
        assert "Choose a different storage workspace." in plan["blockers"]
        with pytest.raises(WorkspaceError, match="different storage workspace"):
            move_kb(source_id, "")
        assert (
            current_kb_manager().base_dir / "atlas" / "raw" / "source.pdf"
        ).read_bytes() == b"source"


def test_target_directory_on_disk_without_entry_blocks_move(as_user):
    with as_user("alice"):
        _make_kb("atlas", b"source")
        service = ContentWorkspaceService()
        destination = service.create_workspace("Research")["workspace_id"]
        with workspace_context(destination):
            target_root = current_kb_manager().base_dir
            (target_root / "atlas").mkdir()
            (target_root / "atlas" / "stray.bin").write_bytes(b"occupied")
        source_id = qualified_kb_id("atlas")

        plan = preview_kb_move(source_id, destination)
        assert any("already contains" in blocker for blocker in plan["blockers"])
        with pytest.raises(WorkspaceError, match="already contains"):
            move_kb(source_id, destination)
        assert (
            current_kb_manager().base_dir / "atlas" / "raw" / "source.pdf"
        ).read_bytes() == b"source"
        assert "atlas" in _config_payload(current_kb_manager().base_dir)["knowledge_bases"]
        with workspace_context(destination):
            assert _staging_dirs(target_root) == []


def test_alias_reserved_destination_blocks_new_same_name_kb(as_user):
    with as_user("alice"):
        service = ContentWorkspaceService()
        vacated = service.create_workspace("Research")["workspace_id"]
        with workspace_context(vacated):
            _make_kb("atlas", b"first")
        move_kb(qualified_kb_id("atlas", vacated), "")
        stashed = service.create_workspace("Stash")["workspace_id"]
        with workspace_context(stashed):
            _make_kb("atlas", b"second")
        source_id = qualified_kb_id("atlas", stashed)

        plan = preview_kb_move(source_id, vacated)
        assert plan["blockers"] == ["Destination ID is reserved by an earlier knowledge-base move."]
        with pytest.raises(WorkspaceError, match="reserved by an earlier"):
            move_kb(source_id, vacated)
        with workspace_context(stashed):
            assert (
                current_kb_manager().base_dir / "atlas" / "raw" / "source.pdf"
            ).read_bytes() == b"second"
            assert "atlas" in _config_payload(current_kb_manager().base_dir)["knowledge_bases"]
        with workspace_context(vacated):
            assert "atlas" not in _config_payload(current_kb_manager().base_dir)["knowledge_bases"]
            assert not (current_kb_manager().base_dir / "atlas").exists()


def test_conflict_rejection_leaves_configs_aliases_and_catalog_untouched(as_user):
    with as_user("alice"):
        _make_kb("atlas", b"source")
        service = ContentWorkspaceService()
        destination = service.create_workspace("Research")["workspace_id"]
        with workspace_context(destination):
            _make_kb("atlas", b"destination")
        source_root = current_kb_manager().base_dir
        source_config_before = _config_payload(source_root)
        with workspace_context(destination):
            target_root = current_kb_manager().base_dir
            target_config_before = _config_payload(target_root)
        consumer = service.create_workspace(
            "Consumer", resources={"knowledge_bases": [qualified_kb_id("atlas")]}
        )
        aliases_path = _move_aliases_path()

        with pytest.raises(WorkspaceError, match="already contains"):
            move_kb(qualified_kb_id("atlas"), destination)

        assert _config_payload(source_root) == source_config_before
        with workspace_context(destination):
            assert _config_payload(target_root) == target_config_before
            assert _staging_dirs(target_root) == []
        assert not aliases_path.exists()
        row = next(
            row for row in service._catalog() if row["workspace_id"] == consumer["workspace_id"]
        )
        assert row["resources"]["knowledge_bases"] == [qualified_kb_id("atlas")]


def test_processing_kb_is_blocked_from_moving(as_user):
    with as_user("alice"):
        _make_kb("atlas", b"source")
        manager = current_kb_manager()
        manager.config = manager._load_config()
        manager.config["knowledge_bases"]["atlas"]["status"] = "processing"
        manager._save_config()
        destination = ContentWorkspaceService().create_workspace("Research")["workspace_id"]

        plan = preview_kb_move(qualified_kb_id("atlas"), destination)
        assert any("finish processing" in blocker for blocker in plan["blockers"])
        with pytest.raises(WorkspaceError, match="finish processing"):
            move_kb(qualified_kb_id("atlas"), destination)
        assert (
            current_kb_manager().base_dir / "atlas" / "raw" / "source.pdf"
        ).read_bytes() == b"source"


def test_snapshot_failure_midcopy_removes_stage_and_keeps_both_stores(as_user, monkeypatch):
    with as_user("alice"):
        _make_kb("atlas", b"source")
        service = ContentWorkspaceService()
        destination = service.create_workspace("Research")["workspace_id"]
        with workspace_context(destination):
            _make_kb("existing", b"keep")
            target_root = current_kb_manager().base_dir
            target_config_before = _config_payload(target_root)
        source_root = current_kb_manager().base_dir
        source_config_before = _config_payload(source_root)
        consumer = service.create_workspace(
            "Consumer", resources={"knowledge_bases": [qualified_kb_id("atlas")]}
        )
        aliases_path = _move_aliases_path()

        original_snapshot = kb_move._snapshot

        def partial_snapshot(source, target, **kwargs):
            target.mkdir(parents=True, exist_ok=True)
            (target / "raw").mkdir(exist_ok=True)
            (target / "raw" / "partial.bin").write_bytes(b"half-written")
            raise OSError("simulated copy interruption")

        monkeypatch.setattr(kb_move, "_snapshot", partial_snapshot)
        with pytest.raises(OSError, match="simulated copy interruption"):
            move_kb(qualified_kb_id("atlas"), destination)
        monkeypatch.setattr(kb_move, "_snapshot", original_snapshot)

        assert _staging_dirs(target_root) == []
        assert not (target_root / "atlas").exists()
        assert _hidden_dirs(source_root) == []
        assert (source_root / "atlas" / "raw" / "source.pdf").read_bytes() == b"source"
        assert _config_payload(source_root) == source_config_before
        with workspace_context(destination):
            assert _config_payload(target_root) == target_config_before
        assert not aliases_path.exists()
        row = next(
            row for row in service._catalog() if row["workspace_id"] == consumer["workspace_id"]
        )
        assert row["resources"]["knowledge_bases"] == [qualified_kb_id("atlas")]


def test_keyboard_interrupt_after_publish_rolls_back_every_store(as_user, monkeypatch):
    with as_user("alice"):
        _make_kb("atlas", b"source")
        service = ContentWorkspaceService()
        destination = service.create_workspace("Research")["workspace_id"]
        with workspace_context(destination):
            _make_kb("existing", b"keep")
            target_root = current_kb_manager().base_dir
            target_config_before = _config_payload(target_root)
        source_root = current_kb_manager().base_dir
        source_config_before = _config_payload(source_root)
        source_id = qualified_kb_id("atlas")
        consumer = service.create_workspace("Consumer", resources={"knowledge_bases": [source_id]})
        aliases_path = _move_aliases_path()

        original_write = kb_move.atomic_write_json

        def interrupt_first_write(path, payload):
            interrupt_first_write.calls += 1
            if interrupt_first_write.calls == 1:
                raise KeyboardInterrupt("simulated crash during publication")
            return original_write(path, payload)

        interrupt_first_write.calls = 0
        monkeypatch.setattr(kb_move, "atomic_write_json", interrupt_first_write)
        with pytest.raises(KeyboardInterrupt):
            move_kb(source_id, destination)
        monkeypatch.setattr(kb_move, "atomic_write_json", original_write)

        assert not (target_root / "atlas").exists()
        with workspace_context(destination):
            assert _config_payload(target_root) == target_config_before
            assert _staging_dirs(target_root) == []
        assert (source_root / "atlas" / "raw" / "source.pdf").read_bytes() == b"source"
        assert _config_payload(source_root) == source_config_before
        assert _hidden_dirs(source_root) == []
        assert not aliases_path.exists()
        row = next(
            row for row in service._catalog() if row["workspace_id"] == consumer["workspace_id"]
        )
        assert row["resources"]["knowledge_bases"] == [source_id]


def test_failed_source_hide_restores_target_store_and_keeps_source(as_user, monkeypatch):
    with as_user("alice"):
        _make_kb("atlas", b"source")
        service = ContentWorkspaceService()
        destination = service.create_workspace("Research")["workspace_id"]
        with workspace_context(destination):
            _make_kb("existing", b"keep")
            target_root = current_kb_manager().base_dir
            target_config_before = _config_payload(target_root)
        source_root = current_kb_manager().base_dir
        source_config_before = _config_payload(source_root)
        source_id = qualified_kb_id("atlas")
        consumer = service.create_workspace("Consumer", resources={"knowledge_bases": [source_id]})
        aliases_path = _move_aliases_path()

        original_rename = Path.rename

        def failing_hide(self, target):
            if Path(target).name.startswith(".kb-moved-"):
                raise OSError("simulated hide interruption")
            return original_rename(self, target)

        monkeypatch.setattr(Path, "rename", failing_hide)
        with pytest.raises(OSError, match="simulated hide interruption"):
            move_kb(source_id, destination)
        monkeypatch.setattr(Path, "rename", original_rename)

        assert (source_root / "atlas" / "raw" / "source.pdf").read_bytes() == b"source"
        assert _config_payload(source_root) == source_config_before
        assert not (target_root / "atlas").exists()
        with workspace_context(destination):
            assert _config_payload(target_root) == target_config_before
            assert _staging_dirs(target_root) == []
        assert _hidden_dirs(source_root) == []
        assert not aliases_path.exists()
        row = next(
            row for row in service._catalog() if row["workspace_id"] == consumer["workspace_id"]
        )
        assert row["resources"]["knowledge_bases"] == [source_id]


def test_source_cleanup_failure_reports_recovery_path(as_user, monkeypatch):
    with as_user("alice"):
        _make_kb("atlas", b"source")
        destination = ContentWorkspaceService().create_workspace("Research")["workspace_id"]
        source_root = current_kb_manager().base_dir

        original_rmtree = kb_move.shutil.rmtree

        def failing_rmtree(path, *args, **kwargs):
            if Path(path).name.startswith(".kb-moved-"):
                raise OSError("simulated cleanup interruption")
            return original_rmtree(path, *args, **kwargs)

        monkeypatch.setattr(kb_move.shutil, "rmtree", failing_rmtree)
        result = move_kb(qualified_kb_id("atlas"), destination)
        monkeypatch.setattr(kb_move.shutil, "rmtree", original_rmtree)

        assert result["status"] == "moved"
        hidden = [name for name in _hidden_dirs(source_root)]
        assert len(hidden) == 1
        assert result["cleanup_path"] == str(source_root / hidden[0])
        assert (source_root / hidden[0] / "raw" / "source.pdf").read_bytes() == b"source"
        with workspace_context(destination):
            assert (
                current_kb_manager().base_dir / "atlas" / "raw" / "source.pdf"
            ).read_bytes() == b"source"
            assert "atlas" in current_kb_manager().list_knowledge_bases()
