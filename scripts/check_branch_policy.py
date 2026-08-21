#!/usr/bin/env python3
"""Reject accidental direct commits in the control checkout."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys


def current_branch() -> str | None:
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() or None


def is_control_checkout() -> bool:
    top_level = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    common_git_dir = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return Path(top_level) == Path(common_git_dir).parent


def main() -> int:
    if is_control_checkout():
        print(
            "Direct commits in the control checkout are forbidden. Create a task "
            "worktree from origin/dev, then integrate through review.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
