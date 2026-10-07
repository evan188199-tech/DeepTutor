from __future__ import annotations

import os
from pathlib import Path
import stat

import pytest

from deeptutor.services.path_service import PathService


def test_public_output_filter_allows_only_whitelisted_artifacts(tmp_path: Path) -> None:
    service = PathService.get_instance()
    original_root = service._project_root
    original_user_dir = service._user_data_dir

    try:
        service._project_root = tmp_path
        service._user_data_dir = tmp_path / "data" / "user"

        allowed = (
            service._user_data_dir
            / "workspace"
            / "chat"
            / "deep_solve"
            / "solve_1"
            / "artifacts"
            / "plot.png"
        )
        allowed.parent.mkdir(parents=True, exist_ok=True)
        allowed.write_text("png", encoding="utf-8")

        denied = service._user_data_dir / "settings" / "model_catalog.json"
        denied.parent.mkdir(parents=True, exist_ok=True)
        denied.write_text("{}", encoding="utf-8")

        assert (
            service.is_public_output_path("workspace/chat/deep_solve/solve_1/artifacts/plot.png")
            is True
        )
        assert service.is_public_output_path("settings/model_catalog.json") is False
        assert service.is_public_output_path("../outside.txt") is False
    finally:
        service._project_root = original_root
        service._user_data_dir = original_user_dir


def test_public_output_filter_allows_math_animator_artifacts(tmp_path: Path) -> None:
    service = PathService.get_instance()
    original_root = service._project_root
    original_user_dir = service._user_data_dir

    try:
        service._project_root = tmp_path
        service._user_data_dir = tmp_path / "data" / "user"

        allowed = (
            service._user_data_dir
            / "workspace"
            / "chat"
            / "math_animator"
            / "turn_1"
            / "artifacts"
            / "animation.mp4"
        )
        allowed.parent.mkdir(parents=True, exist_ok=True)
        allowed.write_text("video", encoding="utf-8")

        denied = (
            service._user_data_dir
            / "workspace"
            / "chat"
            / "math_animator"
            / "turn_1"
            / "source"
            / "scene.py"
        )
        denied.parent.mkdir(parents=True, exist_ok=True)
        denied.write_text("print('debug')", encoding="utf-8")

        assert (
            service.is_public_output_path(
                "workspace/chat/math_animator/turn_1/artifacts/animation.mp4"
            )
            is True
        )
        assert (
            service.is_public_output_path("workspace/chat/math_animator/turn_1/source/scene.py")
            is False
        )
    finally:
        service._project_root = original_root
        service._user_data_dir = original_user_dir


def test_public_output_filter_allows_chat_exec_artifacts(tmp_path: Path) -> None:
    service = PathService.get_instance()
    original_root = service._project_root
    original_user_dir = service._user_data_dir

    try:
        service._project_root = tmp_path
        service._user_data_dir = tmp_path / "data" / "user"

        allowed = (
            service._user_data_dir
            / "workspace"
            / "chat"
            / "chat"
            / "turn_1"
            / "exec"
            / "report.pdf"
        )
        allowed.parent.mkdir(parents=True, exist_ok=True)
        allowed.write_bytes(b"%PDF-1.4\n")

        private_script = allowed.with_name("build.py")
        private_script.write_text("print('internal')", encoding="utf-8")
        private_log = allowed.with_name("output.log")
        private_log.write_text("debug", encoding="utf-8")

        assert service.is_public_output_path("workspace/chat/chat/turn_1/exec/report.pdf") is True
        assert service.is_public_output_path("workspace/chat/chat/turn_1/exec/build.py") is False
        assert service.is_public_output_path("workspace/chat/chat/turn_1/exec/output.log") is False
    finally:
        service._project_root = original_root
        service._user_data_dir = original_user_dir


def test_task_workspace_maps_capabilities_into_workspace_chat(tmp_path: Path) -> None:
    service = PathService.get_instance()
    original_root = service._project_root
    original_user_dir = service._user_data_dir

    try:
        service._project_root = tmp_path
        service._user_data_dir = tmp_path / "data" / "user"

        assert service.get_task_workspace("chat", "turn_1") == (
            tmp_path / "data" / "user" / "workspace" / "chat" / "chat" / "turn_1"
        )
        assert service.get_task_workspace("deep_question", "turn_2") == (
            tmp_path / "data" / "user" / "workspace" / "chat" / "deep_question" / "turn_2"
        )
    finally:
        service._project_root = original_root
        service._user_data_dir = original_user_dir


def test_memory_dir_lookup_is_pure_and_explicit_migration_moves_legacy_markdown(
    tmp_path: Path,
) -> None:
    service = PathService.get_instance()
    original_root = service._project_root
    original_user_dir = service._user_data_dir
    original_workspace_root = service._workspace_root

    try:
        service._project_root = tmp_path
        service._workspace_root = tmp_path / "data"
        service._user_data_dir = tmp_path / "data" / "user"

        old_dir = service.get_workspace_feature_dir("memory")
        old_dir.mkdir(parents=True, exist_ok=True)
        (old_dir / "SUMMARY.md").write_text("legacy summary", encoding="utf-8")
        (old_dir / "PROFILE.md").write_text("legacy profile", encoding="utf-8")

        new_dir = tmp_path / "data" / "memory"
        new_dir.mkdir(parents=True, exist_ok=True)

        assert service.get_memory_dir() == new_dir
        assert not (new_dir / "SUMMARY.md").exists()
        assert service.migrate_legacy_memory_markdown() is True
        assert (new_dir / "SUMMARY.md").read_text(encoding="utf-8") == "legacy summary"
        assert (new_dir / "PROFILE.md").read_text(encoding="utf-8") == "legacy profile"
        assert not (old_dir / "SUMMARY.md").exists()
        assert service.migrate_legacy_memory_markdown() is False
    finally:
        service._project_root = original_root
        service._workspace_root = original_workspace_root
        service._user_data_dir = original_user_dir


def test_memory_dir_migration_preserves_conflicting_target_files(tmp_path: Path) -> None:
    service = PathService.get_instance()
    original_root = service._project_root
    original_user_dir = service._user_data_dir
    original_workspace_root = service._workspace_root

    try:
        service._project_root = tmp_path
        service._workspace_root = tmp_path / "data"
        service._user_data_dir = tmp_path / "data" / "user"

        old_dir = service.get_workspace_feature_dir("memory")
        old_dir.mkdir(parents=True, exist_ok=True)
        (old_dir / "PROFILE.md").write_text("legacy profile", encoding="utf-8")

        new_dir = tmp_path / "data" / "memory"
        new_dir.mkdir(parents=True, exist_ok=True)
        (new_dir / "PROFILE.md").write_text("current profile", encoding="utf-8")

        assert service.migrate_legacy_memory_markdown() is True
        assert (new_dir / "PROFILE.md").read_text(encoding="utf-8") == "current profile"
        assert (new_dir / "backup" / "legacy-workspace" / "PROFILE.md").read_text(
            encoding="utf-8"
        ) == "legacy profile"
    finally:
        service._project_root = original_root
        service._workspace_root = original_workspace_root
        service._user_data_dir = original_user_dir


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are not authoritative")
def test_ensure_all_directories_keeps_private_roots_owner_only(tmp_path: Path) -> None:
    service = PathService(workspace_root=tmp_path / "scope")

    service.ensure_all_directories()

    for path in (
        service.get_user_root(),
        service.get_settings_dir(),
        service.get_workspace_dir(),
        service.get_logs_dir(),
        service.get_memory_dir(),
    ):
        assert stat.S_IMODE(path.stat().st_mode) == 0o700


def _scoped_service(tmp_path: Path, name: str = "scope") -> PathService:
    return PathService(workspace_root=tmp_path / name / "data")


def _write_output(service: PathService, relative: str, content: str = "data") -> Path:
    path = service.user_data_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_custom_workspace_root_scopes_every_derived_root(tmp_path: Path) -> None:
    scope = tmp_path / "workspace-a" / "data"
    service = PathService(workspace_root=scope)

    assert service.workspace_root == scope.resolve()
    assert service.project_root == (tmp_path / "workspace-a").resolve()
    assert service.user_data_dir == scope.resolve() / "user"
    assert service.get_workspace_dir() == scope.resolve() / "user" / "workspace"
    assert service.get_memory_dir() == scope.resolve() / "memory"


def test_service_instances_do_not_share_containment_between_roots(tmp_path: Path) -> None:
    first = _scoped_service(tmp_path, "workspace-a")
    second = _scoped_service(tmp_path, "workspace-b")

    shared = first.user_data_dir / "workspace" / "chat" / "chat" / "turn_1" / "exec" / "report.pdf"
    shared.parent.mkdir(parents=True, exist_ok=True)
    shared.write_text("first", encoding="utf-8")

    assert first.resolve_public_output_path(shared) == shared.resolve()
    assert second.resolve_public_output_path(shared) is None
    assert second.get_workspace_dir() != first.get_workspace_dir()


def test_relative_public_output_resolves_against_user_root_to_canonical_path(
    tmp_path: Path,
) -> None:
    service = _scoped_service(tmp_path)
    real = _write_output(service, "workspace/chat/chat/turn_1/exec/report.pdf")

    from_string = service.resolve_public_output_path("workspace/chat/chat/turn_1/exec/report.pdf")
    from_path = service.resolve_public_output_path(
        Path("workspace/chat/chat/turn_1/exec/report.pdf")
    )

    assert from_string == real.resolve()
    assert from_path == from_string
    assert from_string is not None and from_string.is_relative_to(service.user_data_dir)


def test_public_output_resolution_requires_an_existing_regular_file(tmp_path: Path) -> None:
    service = _scoped_service(tmp_path)

    assert service.resolve_public_output_path("workspace/chat/chat/turn_1/exec/missing.pdf") is None

    exec_dir = service.user_data_dir / "workspace" / "chat" / "chat" / "turn_1" / "exec"
    exec_dir.mkdir(parents=True, exist_ok=True)
    assert service.resolve_public_output_path("workspace/chat/chat/turn_1/exec") is None


def test_forward_slash_relative_paths_resolve_on_every_platform(tmp_path: Path) -> None:
    service = _scoped_service(tmp_path)
    real = _write_output(service, "workspace/chat/deep_solve/turn_1/artifacts/plot.png")

    joined = os.path.join("workspace", "chat", "deep_solve", "turn_1", "artifacts", "plot.png")
    assert service.is_public_output_path("workspace/chat/deep_solve/turn_1/artifacts/plot.png")
    assert service.is_public_output_path(Path(*real.relative_to(service.user_data_dir).parts))
    assert service.resolve_public_output_path(joined) == real.resolve()


@pytest.mark.skipif(os.name == "nt", reason="POSIX treats backslash as a literal character")
def test_backslash_separated_names_do_not_alias_nested_outputs(tmp_path: Path) -> None:
    service = _scoped_service(tmp_path)
    real = _write_output(service, "workspace/chat/chat/turn_1/exec/report.pdf")

    assert service.is_public_output_path("workspace\\chat\\chat\\turn_1\\exec\\report.pdf") is False
    assert real.is_file()


def test_dot_and_parent_segments_inside_the_root_normalize_to_the_same_file(
    tmp_path: Path,
) -> None:
    service = _scoped_service(tmp_path)
    real = _write_output(service, "workspace/chat/chat/turn_1/exec/report.pdf")

    dotted = "./workspace//chat/./../chat/chat/./turn_1/exec/report.pdf"
    parented = "workspace/../workspace/chat/chat/turn_1/exec/report.pdf"

    assert service.resolve_public_output_path(dotted) == real.resolve()
    assert service.resolve_public_output_path(parented) == real.resolve()


def test_absolute_path_outside_the_user_root_is_not_served(tmp_path: Path) -> None:
    service = _scoped_service(tmp_path)
    outside = tmp_path / "outside" / "report.pdf"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("elsewhere", encoding="utf-8")

    assert service.resolve_public_output_path(outside) is None


def test_relative_parent_escape_is_rejected_after_normalization(tmp_path: Path) -> None:
    service = _scoped_service(tmp_path)

    assert service.resolve_public_output_path("../settings/model_catalog.json") is None
    assert service.resolve_public_output_path("../../outside.txt") is None
    assert service.is_public_output_path("workspace/../secrets/key.txt") is False


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink creation without privileges")
def test_containment_follows_the_resolved_target_not_the_visible_name(tmp_path: Path) -> None:
    service = _scoped_service(tmp_path)
    real = _write_output(service, "workspace/chat/chat/turn_1/exec/report.pdf")
    exec_dir = real.parent

    outside = tmp_path / "outside" / "report.pdf"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("elsewhere", encoding="utf-8")
    outbound_alias = exec_dir / "outbound.pdf"
    outbound_alias.symlink_to(outside)
    inbound_alias = exec_dir / "inbound.pdf"
    inbound_alias.symlink_to(real)

    assert service.resolve_public_output_path(outbound_alias) is None
    assert service.resolve_public_output_path(inbound_alias) == real.resolve()


def test_feature_and_agent_lookups_reject_unknown_names(tmp_path: Path) -> None:
    service = _scoped_service(tmp_path)

    with pytest.raises(ValueError):
        service.get_task_workspace("not-a-feature", "task_1")
    with pytest.raises(ValueError):
        service.get_session_workspace("not-a-feature", "session_1")
    with pytest.raises(KeyError):
        service.get_agent_dir("not-a-module")
    with pytest.raises(KeyError):
        service.get_task_dir("not-a-module", "task_1")


def test_settings_and_runtime_config_names_fall_back_to_expected_suffixes(
    tmp_path: Path,
) -> None:
    service = _scoped_service(tmp_path)

    assert service.get_settings_file("appearance") == (
        service.get_settings_dir() / "appearance.json"
    )
    assert service.get_settings_file("custom.yaml") == service.get_settings_dir() / "custom.yaml"
    assert service.get_runtime_config_file("model") == (service.get_settings_dir() / "model.yaml")
    assert service.get_runtime_config_file("providers.yaml") == (
        service.get_settings_dir() / "providers.yaml"
    )
    for path in (
        service.get_settings_file("appearance"),
        service.get_runtime_config_file("model"),
    ):
        assert path.is_relative_to(service.user_data_dir)


def test_memory_migration_drops_identical_conflict_and_marks_once(tmp_path: Path) -> None:
    service = PathService(workspace_root=tmp_path / "data")
    old_dir = service.get_workspace_feature_dir("memory")
    old_dir.mkdir(parents=True, exist_ok=True)
    (old_dir / "SUMMARY.md").write_text("same content", encoding="utf-8")

    new_dir = tmp_path / "data" / "memory"
    new_dir.mkdir(parents=True, exist_ok=True)
    (new_dir / "SUMMARY.md").write_text("same content", encoding="utf-8")

    assert service.migrate_legacy_memory_markdown() is True
    assert (new_dir / "SUMMARY.md").read_text(encoding="utf-8") == "same content"
    assert not (old_dir / "SUMMARY.md").exists()
    assert (old_dir / ".migrated-to-data-memory-v2").exists()
    assert not (new_dir / "backup" / "legacy-workspace").exists()
    assert service.migrate_legacy_memory_markdown() is False


def test_memory_migration_renames_repeated_backup_conflicts(tmp_path: Path) -> None:
    service = PathService(workspace_root=tmp_path / "data")
    old_dir = service.get_workspace_feature_dir("memory")
    old_dir.mkdir(parents=True, exist_ok=True)
    (old_dir / "PROFILE.md").write_text("legacy profile", encoding="utf-8")

    new_dir = tmp_path / "data" / "memory"
    backup_conflict = new_dir / "backup" / "legacy-workspace"
    backup_conflict.mkdir(parents=True, exist_ok=True)
    (backup_conflict / "PROFILE.md").write_text("earlier backup", encoding="utf-8")
    (new_dir / "PROFILE.md").write_text("current profile", encoding="utf-8")

    assert service.migrate_legacy_memory_markdown() is True
    assert (new_dir / "PROFILE.md").read_text(encoding="utf-8") == "current profile"
    assert (backup_conflict / "PROFILE.md").read_text(encoding="utf-8") == "earlier backup"
    assert (backup_conflict / "PROFILE-1.md").read_text(encoding="utf-8") == "legacy profile"
    assert not (old_dir / "PROFILE.md").exists()


def test_memory_migration_is_noop_for_non_default_workspace_root(tmp_path: Path) -> None:
    service = PathService(workspace_root=tmp_path / "alt-root")

    assert service.migrate_legacy_memory_markdown() is False
    assert not service.get_workspace_feature_dir("memory").exists()
    assert not service.get_memory_dir().exists()


def test_memory_migration_is_noop_when_marker_already_present(tmp_path: Path) -> None:
    service = PathService(workspace_root=tmp_path / "data")
    old_dir = service.get_workspace_feature_dir("memory")
    old_dir.mkdir(parents=True, exist_ok=True)
    legacy = old_dir / "SUMMARY.md"
    legacy.write_text("already archived", encoding="utf-8")
    (old_dir / ".migrated-to-data-memory-v2").write_text("marker\n", encoding="utf-8")

    assert service.migrate_legacy_memory_markdown() is False
    assert legacy.read_text(encoding="utf-8") == "already archived"
    assert not (tmp_path / "data" / "memory" / "SUMMARY.md").exists()


def test_memory_migration_is_noop_when_legacy_directory_is_missing(tmp_path: Path) -> None:
    service = PathService(workspace_root=tmp_path / "data")

    assert service.migrate_legacy_memory_markdown() is False
    assert not service.get_memory_dir().exists()
    assert not (tmp_path / "data" / "user" / "workspace" / "memory").exists()
