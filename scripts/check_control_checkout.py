#!/usr/bin/env python3
"""Ensure linked task worktrees are not checked out in the control directory."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys


def is_primary_worktree() -> bool:
    top_level = Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    common_git_dir = Path(
        subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    return top_level == common_git_dir.parent


def main() -> int:
    if not is_primary_worktree():
        return 0
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if branch not in {"main", "dev"}:
        print(
            "Task branches are not allowed in the control checkout. Switch back to "
            "main or dev and use scripts/workspace_governance.py create.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
