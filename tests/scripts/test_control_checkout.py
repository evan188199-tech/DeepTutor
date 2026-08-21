from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys


def _load_control_checkout_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "check_control_checkout.py"
    module_name = "control_checkout_under_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _run_script(cwd: Path) -> subprocess.CompletedProcess[str]:
    script = Path(__file__).resolve().parents[2] / "scripts" / "check_control_checkout.py"
    return subprocess.run(
        [sys.executable, str(script)],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def test_control_checkout_script_rejects_task_branch_and_allows_worktree(tmp_path: Path) -> None:
    _load_control_checkout_module()
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=repo, check=True)
    marker = repo / "marker.txt"
    marker.write_text("initial\n", encoding="utf-8")
    subprocess.run(["git", "add", "marker.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True)

    worktree = tmp_path / "task-worktree"
    subprocess.run(
        ["git", "worktree", "add", "-b", "codex/fix/example", str(worktree), "main"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "switch", "-c", "codex/fix/control"], cwd=repo, check=True)

    rejected = _run_script(repo)
    allowed = _run_script(worktree)

    assert rejected.returncode == 1
    assert "Task branches are not allowed in the control checkout" in rejected.stderr
    assert allowed.returncode == 0
