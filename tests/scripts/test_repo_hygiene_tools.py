from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest


def _load_module(name: str, path: Path):
    module_name = f"{name}_under_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_hygiene_violation_rejects_generated_and_runtime_paths() -> None:
    hygiene = _load_module(
        "check_repo_hygiene", Path(__file__).parents[2] / "scripts" / "check_repo_hygiene.py"
    )

    assert hygiene.violation("web/.next-deeptutor/BUILD_ID") == "Next.js build output"
    assert hygiene.violation("web/out/index.html") == "frontend build output"
    assert hygiene.violation("data/user/settings/main.json") == "runtime data"
    assert hygiene.violation("tests/__pycache__/test.pyc") == "generated output"
    assert hygiene.violation("deeptutor/runtime/launcher.py") is None


def test_staged_hygiene_rejects_protected_branch(monkeypatch, capsys) -> None:
    hygiene = _load_module(
        "check_repo_hygiene", Path(__file__).parents[2] / "scripts" / "check_repo_hygiene.py"
    )
    monkeypatch.setattr(hygiene, "current_branch", lambda: "dev")
    monkeypatch.setattr(hygiene, "staged_paths", lambda: [])

    assert hygiene.main(staged=True) == 1
    assert "protected branch dev" in capsys.readouterr().err


def _init_repository(path: Path) -> None:
    path.mkdir()
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.email", "tests@example.com")
    _git(path, "config", "user.name", "DeepTutor Tests")
    (path / "README.md").write_text("test\n", encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "initial")
    _git(path, "update-ref", "refs/remotes/origin/dev", "HEAD")


def test_worktree_create_status_and_retire(tmp_path: Path, monkeypatch) -> None:
    worktree = _load_module("worktree", Path(__file__).parents[2] / "scripts" / "worktree.py")
    repository = tmp_path / "DeepTutor"
    _init_repository(repository)
    monkeypatch.chdir(repository)

    record = worktree.create("feature-task")
    expected_path = tmp_path / "DeepTutor-worktrees" / "feature-task"
    assert record.path == str(expected_path.resolve())
    assert record.branch == "codex/feature-task"
    assert record.state == "clean"
    assert expected_path.is_dir()

    with pytest.raises(RuntimeError, match="branch already exists"):
        worktree.create("feature-task")

    (expected_path / "local.txt").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="worktree is dirty"):
        worktree.retire("feature-task")

    (expected_path / "local.txt").unlink()
    retired = worktree.retire("feature-task")
    assert retired.path == record.path
    assert not expected_path.exists()
    assert _git(repository, "show-ref", "--verify", "refs/heads/codex/feature-task")
