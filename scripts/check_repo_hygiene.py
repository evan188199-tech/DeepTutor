#!/usr/bin/env python3
"""Reject protected-branch commits and commonly regenerated files."""

from __future__ import annotations

import argparse
from pathlib import PurePosixPath
import subprocess
import sys

PROTECTED_BRANCHES = {"main", "dev", "multi-user"}
FORBIDDEN_PARTS = {
    ".DS_Store",
    ".pytest_cache",
    ".ruff_cache",
    ".turbo",
    "__pycache__",
    "htmlcov",
    "node_modules",
    "playwright-report",
    "run_code_workspace",
    "test-results",
}
FORBIDDEN_TOP_LEVEL_DIRECTORIES = {"data", "multi-user"}
FORBIDDEN_WEB_DIRECTORIES = {"build", "coverage", "dist", "out", "static"}
FORBIDDEN_SUFFIXES = (".pyc", ".pyo", ".tsbuildinfo")


def tracked_paths() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    return [path for path in result.stdout.decode("utf-8").split("\0") if path]


def staged_paths() -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "-z"],
        check=True,
        capture_output=True,
    )
    return [path for path in result.stdout.decode("utf-8").split("\0") if path]


def violation(path: str) -> str | None:
    pure_path = PurePosixPath(path)
    if not path:
        return "empty path"
    if pure_path.parts[0] in FORBIDDEN_TOP_LEVEL_DIRECTORIES:
        return "runtime data"
    if any(part.startswith(".next") for part in pure_path.parts):
        return "Next.js build output"
    if (
        len(pure_path.parts) > 1
        and pure_path.parts[0] == "web"
        and pure_path.parts[1]
        in {
            *FORBIDDEN_WEB_DIRECTORIES,
            ".next-deeptutor",
        }
    ):
        return "frontend build output"
    if any(part in FORBIDDEN_PARTS for part in pure_path.parts):
        return "generated output"
    if pure_path.suffix in FORBIDDEN_SUFFIXES:
        return "compiled bytecode"
    if path != path.strip() or any(
        ord(character) < 32 or ord(character) == 127 for character in path
    ):
        return "unusual filesystem whitespace"
    return None


def current_branch() -> str | None:
    result = subprocess.run(
        ["git", "symbolic-ref", "--quiet", "HEAD"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip().removeprefix("refs/heads/")


def main(staged: bool = False) -> int:
    errors: list[str] = []
    branch = current_branch()
    if staged and branch in PROTECTED_BRANCHES:
        errors.append(f"commits are not allowed directly on protected branch {branch}")

    paths = staged_paths() if staged else tracked_paths()
    errors.extend(f"{path}: {reason}" for path in paths if (reason := violation(path)) is not None)
    if errors:
        scope = "staged" if staged else "tracked"
        print(f"Repository hygiene check failed for {scope} paths:", file=sys.stderr)
        print("\n".join(errors), file=sys.stderr)
        if staged and branch in PROTECTED_BRANCHES:
            print("Create a codex/<task> branch and worktree instead.", file=sys.stderr)
        else:
            print(
                "Remove generated paths from the index with `git rm --cached`; keep local "
                "files when they are useful build output.",
                file=sys.stderr,
            )
        return 1

    print("Repository hygiene check passed.")
    return 0


def cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--staged",
        action="store_true",
        help="check staged files and reject commits on protected branches",
    )
    args = parser.parse_args()
    return main(staged=args.staged)


if __name__ == "__main__":
    raise SystemExit(cli())
