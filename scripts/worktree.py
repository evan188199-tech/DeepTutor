#!/usr/bin/env python3
"""Create, inspect, and retire DeepTutor task worktrees."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from pathlib import Path
import re
import subprocess
import sys

BRANCH_PREFIX = "codex/"
WORKTREE_DIRECTORY = "DeepTutor-worktrees"
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$")


@dataclass(frozen=True)
class WorktreeRecord:
    path: str
    branch: str | None
    head: str
    state: str
    ahead: int | None
    behind: int | None


def run_git(
    *arguments: str,
    cwd: Path,
    check: bool = True,
    capture: bool = True,
    safe_root: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    command = ["git"]
    if safe_root is not None:
        command.extend(["-c", f"safe.directory={safe_root}"])
    command.extend(arguments)
    result = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=capture,
        text=True,
    )
    if check and result.returncode:
        message = (result.stderr or result.stdout).strip()
        raise RuntimeError(message or f"git {' '.join(arguments)} failed")
    return result


def repository_root(cwd: Path) -> Path:
    for candidate in (cwd.resolve(), *cwd.resolve().parents):
        git_path = candidate / ".git"
        if git_path.is_dir():
            return candidate.resolve()
        if git_path.is_file():
            gitdir = git_path.read_text(encoding="utf-8").strip()
            if gitdir.startswith("gitdir: "):
                resolved = Path(gitdir.removeprefix("gitdir: ")).resolve()
                # <repository>/.git/worktrees/<name>
                if resolved.parent.parent.name == ".git":
                    return resolved.parent.parent.parent.resolve()
            return candidate.resolve()
    raise RuntimeError(f"no Git repository found above {cwd}")


def validate_slug(slug: str) -> str:
    if not SLUG_PATTERN.fullmatch(slug):
        raise ValueError(
            "slug must contain lowercase letters, digits, or hyphens and cannot start "
            "or end with a hyphen"
        )
    return slug


def default_worktrees_root(root: Path) -> Path:
    return root.parent / WORKTREE_DIRECTORY


def worktree_records(root: Path) -> list[WorktreeRecord]:
    output = run_git("worktree", "list", "--porcelain", cwd=root, safe_root=root).stdout
    blocks: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in output.splitlines():
        if not line:
            if current:
                blocks.append(current)
                current = {}
            continue
        key, separator, value = line.partition(" ")
        current[key] = value if separator else ""
    if current:
        blocks.append(current)

    records: list[WorktreeRecord] = []
    for block in blocks:
        path_text = block.get("worktree")
        if not path_text:
            continue
        path = Path(path_text)
        branch = block.get("branch", "").removeprefix("refs/heads/") or None
        head = block.get("HEAD", "")
        if block.get("bare") == "true":
            state = "bare"
        elif block.get("prunable"):
            state = "prunable"
        elif not path.exists():
            state = "missing"
        elif run_git("status", "--porcelain", cwd=path, capture=True, safe_root=path).stdout:
            state = "dirty"
        else:
            state = "clean"

        ahead: int | None = None
        behind: int | None = None
        if path.exists() and state not in {"missing", "prunable"}:
            status = run_git(
                "status",
                "--porcelain=v2",
                "--branch",
                cwd=path,
                capture=True,
                safe_root=path,
            ).stdout
            for line in status.splitlines():
                fields = line.split()
                if len(fields) >= 4 and fields[:2] == ["#", "branch.ab"]:
                    try:
                        ahead = int(fields[2].removeprefix("+"))
                        behind = int(fields[3].removeprefix("-"))
                    except ValueError:
                        pass
        records.append(WorktreeRecord(str(path), branch, head, state, ahead, behind))
    return records


def create(slug: str, base: str = "origin/dev") -> WorktreeRecord:
    slug = validate_slug(slug)
    root = repository_root(Path.cwd())
    if run_git("status", "--porcelain", cwd=root, capture=True, safe_root=root).stdout:
        raise RuntimeError(f"anchor worktree is dirty: {root}")

    branch = f"{BRANCH_PREFIX}{slug}"
    if (
        run_git(
            "show-ref",
            "--verify",
            f"refs/heads/{branch}",
            cwd=root,
            check=False,
            safe_root=root,
        ).returncode
        == 0
    ):
        raise RuntimeError(f"branch already exists: {branch}")

    target = default_worktrees_root(root) / slug
    if target.exists():
        raise RuntimeError(f"worktree directory already exists: {target}")

    run_git("rev-parse", "--verify", f"{base}^{{commit}}", cwd=root, safe_root=root)
    target.parent.mkdir(parents=True, exist_ok=True)
    run_git("branch", branch, base, cwd=root, safe_root=root)
    try:
        run_git("worktree", "add", str(target), branch, cwd=root, safe_root=root)
    except RuntimeError:
        run_git("branch", "-D", branch, cwd=root, check=False, safe_root=root)
        raise

    return next(record for record in worktree_records(root) if record.path == str(target))


def status() -> list[WorktreeRecord]:
    root = repository_root(Path.cwd())
    return worktree_records(root)


def retire(slug: str) -> WorktreeRecord:
    slug = validate_slug(slug)
    root = repository_root(Path.cwd())
    branch = f"{BRANCH_PREFIX}{slug}"
    matches = [record for record in worktree_records(root) if record.branch == branch]
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one worktree for {branch}, found {len(matches)}")
    record = matches[0]
    if record.state != "clean":
        raise RuntimeError(f"refusing to retire {branch}: worktree is {record.state}")
    run_git("worktree", "remove", record.path, cwd=root, safe_root=root)
    return record


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    create_parser = commands.add_parser("create", help="create a branch and task worktree")
    create_parser.add_argument("slug")
    create_parser.add_argument("--base", default="origin/dev")

    commands.add_parser("status", help="list worktrees and their Git state")

    retire_parser = commands.add_parser("retire", help="remove a clean task worktree")
    retire_parser.add_argument("slug")

    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            result = create(args.slug, args.base)
        elif args.command == "status":
            result = status()
        else:
            result = retire(args.slug)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if isinstance(result, list):
        for record in result:
            print(asdict(record))
    else:
        print(asdict(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
