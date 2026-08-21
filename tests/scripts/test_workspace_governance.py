"""Tests for workspace governance tooling."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

script_path = Path(__file__).resolve().parents[2] / "scripts" / "workspace_governance.py"
spec = importlib.util.spec_from_file_location("workspace_governance", script_path)
assert spec and spec.loader
workspace_governance = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = workspace_governance
spec.loader.exec_module(workspace_governance)

archive_workspace = workspace_governance.archive_workspace
inspect_workspace = workspace_governance.inspect_workspace
verify_archive = workspace_governance.verify_archive
list_worktrees = workspace_governance.list_worktrees
retire_workspace = workspace_governance.retire_workspace
normalize_task_branch = workspace_governance.normalize_task_branch
sync_workspace = workspace_governance.sync_workspace


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def test_task_branch_names_require_an_approved_type_and_slug() -> None:
    assert normalize_task_branch("feat/kids-library") == "codex/feat/kids-library"
    assert normalize_task_branch("codex/fix/login-timeout") == "codex/fix/login-timeout"

    for invalid in ("kids-library", "codex/kids-library", "codex/feat/Kids"):
        try:
            normalize_task_branch(invalid)
        except ValueError as error:
            assert "Task branch must match" in str(error)
        else:
            raise AssertionError(f"Expected {invalid!r} to be rejected")


def test_create_workspace_refuses_a_dirty_control_checkout(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-b", "main"], repo)
    _git(["config", "user.name", "Tester"], repo)
    _git(["config", "user.email", "tester@example.com"], repo)
    tracked = repo / "tracked.txt"
    tracked.write_text("dirty\n", encoding="utf-8")

    try:
        workspace_governance.create_workspace(
            "feat/should-not-start",
            repo_root=repo,
            target_parent=tmp_path / "worktrees",
        )
    except RuntimeError as error:
        assert "control checkout is dirty" in str(error)
    else:
        raise AssertionError("Expected create_workspace to refuse a dirty control checkout")


def test_sync_workspace_rebases_clean_task_branch_from_upstream_dev(
    monkeypatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []

    def fake_git(args: list[str], *, cwd: Path | None = None, check: bool = False):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    info = SimpleNamespace(
        path=str(tmp_path),
        head_sha="1234567890abcdef",
        branch="codex/feat/kids-library",
        is_clean=True,
        dirty_files=[],
        untracked_files=[],
        listening_ports=[],
        archived=False,
        safe_to_retire=True,
        retirement_blockers=[],
    )
    monkeypatch.setattr(workspace_governance, "_git", fake_git)
    monkeypatch.setattr(workspace_governance, "inspect_workspace", lambda *args, **kwargs: info)

    synced = sync_workspace(tmp_path, remote="origin", base_branch="dev")

    assert synced.branch == "codex/feat/kids-library"
    assert calls == [["fetch", "origin", "dev"], ["rebase", "origin/dev"]]


def test_inspect_workspace_detects_clean_and_dirty_state(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-b", "main"], repo)
    _git(["config", "user.name", "Tester"], repo)
    _git(["config", "user.email", "tester@example.com"], repo)

    test_file = repo / "hello.txt"
    test_file.write_text("initial content\n", encoding="utf-8")
    _git(["add", "hello.txt"], repo)
    _git(["commit", "-m", "Initial commit"], repo)

    clean_info = inspect_workspace(repo, repo)
    assert clean_info.is_main is True
    assert clean_info.is_clean is True
    assert clean_info.dirty_files == []
    assert clean_info.untracked_files == []
    assert clean_info.branch == "main"

    # Add dirty modifications and untracked file
    test_file.write_text("modified content\n", encoding="utf-8")
    untracked_file = repo / "untracked.log"
    untracked_file.write_text("log line\n", encoding="utf-8")

    dirty_info = inspect_workspace(repo, repo)
    assert dirty_info.is_clean is False
    assert "hello.txt" in dirty_info.dirty_files
    assert "untracked.log" in dirty_info.untracked_files


def test_archive_workspace_creates_verified_manifest_and_artifacts(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-b", "main"], repo)
    _git(["config", "user.name", "Tester"], repo)
    _git(["config", "user.email", "tester@example.com"], repo)

    tracked = repo / "tracked.py"
    tracked.write_text("x = 1\n", encoding="utf-8")
    _git(["add", "tracked.py"], repo)
    _git(["commit", "-m", "add tracked.py"], repo)

    # Create modification & untracked file
    tracked.write_text("x = 2\n", encoding="utf-8")
    untracked = repo / "secret.txt"
    untracked.write_text("secret_value\n", encoding="utf-8")

    archives_dir = tmp_path / "archives"
    archive_dir = archive_workspace(repo, repo, archive_dir=archives_dir, label="test-audit")

    assert archive_dir.exists()
    assert (archive_dir / "changes.patch").exists()
    assert (archive_dir / "untracked.tar.gz").exists()
    assert (archive_dir / "meta.json").exists()
    assert (archive_dir / "manifest.sha256").exists()

    meta = json.loads((archive_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["is_clean"] is False
    assert "tracked.py" in meta["dirty_files"]
    assert "secret.txt" in meta["untracked_files"]

    # Verify checksum manifest
    assert verify_archive(archive_dir) is True

    # Modify file and confirm checksum verification fails
    (archive_dir / "changes.patch").write_text("corrupted", encoding="utf-8")
    assert verify_archive(archive_dir) is False


def test_main_checkout_cannot_be_retired(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-b", "main"], repo)
    _git(["config", "user.name", "Tester"], repo)
    _git(["config", "user.email", "tester@example.com"], repo)

    info = inspect_workspace(repo, repo)
    assert info.is_main is True
    assert any("control checkout" in b for b in info.retirement_blockers)
    assert info.safe_to_retire is False


def test_retire_workspace_removes_linked_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-b", "main"], repo)
    _git(["config", "user.name", "Tester"], repo)
    _git(["config", "user.email", "tester@example.com"], repo)

    tracked = repo / "main.txt"
    tracked.write_text("content\n", encoding="utf-8")
    _git(["add", "main.txt"], repo)
    _git(["commit", "-m", "init"], repo)

    wt = tmp_path / "task-wt"
    _git(["worktree", "add", "-b", "task-branch", str(wt), "main"], repo)

    wt_info = inspect_workspace(wt, repo)
    assert wt_info.is_main is False
    assert wt_info.is_clean is True
    assert wt_info.safe_to_retire is True

    retire_workspace(wt, repo, force=False)
    worktrees = list_worktrees(repo)
    assert all(w.path != str(wt) for w in worktrees)
