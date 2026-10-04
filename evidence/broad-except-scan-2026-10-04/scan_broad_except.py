#!/usr/bin/env python3
"""AST scan for broad exception handlers (except Exception / BaseException).

Read-only: walks the repository (default: the directory containing this
script's repo root) and reports every ``except Exception`` /
``except BaseException`` handler with enough context to classify it.

Usage:
    python3 evidence/broad-except-scan-<date>/scan_broad_except.py [repo_root]

Output: JSON list on stdout (or ``--out`` file). Stdlib only.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

BROAD_NAMES = {"Exception", "BaseException"}
SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".next", "build", "dist"}
DEFAULT_ROOTS = ["deeptutor", "deeptutor_cli", "scripts", "tests"]


def silent_body(handler: ast.ExceptHandler) -> bool:
    """Match DT-22 definition: every stmt is pass / continue / `...`."""
    for stmt in handler.body:
        if isinstance(stmt, (ast.Pass, ast.Continue)):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and stmt.value.value is Ellipsis:
            continue
        return False
    return True


def exc_type_src(node: ast.expr | None, src: str) -> str | None:
    """Return source text of the handler's exception type, or None for bare."""
    if node is None:
        return None
    return ast.get_source_segment(src, node)


def is_broad(type_src: str | None) -> bool:
    if type_src is None:
        return False
    parts = [p.strip().strip("()") for p in type_src.split(",")]
    return any(p in BROAD_NAMES for p in parts)


class _Parents(ast.NodeVisitor):
    """Build a child->parent map so handlers can find their function."""

    def __init__(self) -> None:
        self.parent: dict[ast.AST, ast.AST] = {}

    def visit(self, node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            self.parent[child] = node
        super().visit(node)


def enclosing_name(parents: dict[ast.AST, ast.AST], node: ast.AST) -> str:
    cur = parents.get(node)
    while cur is not None:
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            prefix = ""
            cls = parents.get(cur)
            while cls is not None:
                if isinstance(cls, ast.ClassDef):
                    prefix = f"{cls.name}."
                    break
                cls = parents.get(cls)
            return f"{prefix}{cur.name}"
        cur = parents.get(cur)
    return "<module>"


def in_async_context(parents: dict[ast.AST, ast.AST], node: ast.AST) -> bool:
    cur = parents.get(node)
    while cur is not None:
        if isinstance(cur, ast.AsyncFunctionDef):
            return True
        if isinstance(cur, (ast.FunctionDef, ast.Module)):
            return False
        cur = parents.get(cur)
    return False


def handler_body(src: str, handler: ast.ExceptHandler, max_lines: int = 3) -> str:
    lines = []
    for stmt in handler.body[:2]:
        seg = ast.get_source_segment(src, stmt) or ""
        for ln in seg.splitlines()[: max_lines - len(lines)]:
            lines.append(ln.strip())
    return " | ".join(lines)[:300]


def scan_repo(root: Path, roots: list[str]) -> tuple[list[dict], dict]:
    results: list[dict] = []
    bare: list[str] = []
    py_files: list[Path] = []
    for sub in roots:
        base = root / sub
        if base.is_file() and base.suffix == ".py":
            py_files.append(base)
            continue
        if not base.is_dir():
            continue
        py_files.extend(
            p for p in base.rglob("*.py")
            if not any(part in SKIP_DIRS for part in p.relative_to(root).parts)
        )
    py_files = sorted(set(py_files))
    for py in py_files:
        rel = py.relative_to(root).as_posix()
        try:
            src = py.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src, filename=str(py))
        except SyntaxError:
            continue
        pv = _Parents()
        pv.visit(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            try_first = ""
            if node.body:
                seg = ast.get_source_segment(src, node.body[0]) or ""
                try_first = seg.splitlines()[0].strip()[:160]
            for handler in node.handlers:
                tsrc = exc_type_src(handler.type, src)
                entry = {
                    "path": rel,
                    "line": handler.lineno,
                    "end_line": handler.end_lineno,
                    "exc_type": tsrc,
                    "broad": is_broad(tsrc),
                    "bare": tsrc is None,
                    "is_pass": len(handler.body) == 1 and isinstance(handler.body[0], ast.Pass),
                    "silent": silent_body(handler),
                    "handler_body": handler_body(src, handler),
                    "function": enclosing_name(pv.parent, handler),
                    "async": in_async_context(pv.parent, handler),
                    "try_body_first_line": try_first,
                }
                if entry["bare"]:
                    bare.append(f"{rel}:{handler.lineno}")
                if entry["broad"]:
                    results.append(entry)
    stats = {
        "files_scanned": len(py_files),
        "broad_handlers": len(results),
        "bare_handlers": len(bare),
    }
    return results, stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("repo_root", nargs="?", help="repo root (default: auto-detect)")
    ap.add_argument("--out", help="write JSON here instead of stdout")
    args = ap.parse_args()

    root = Path(args.repo_root).resolve() if args.repo_root else Path(__file__).resolve().parents[2]
    entries, stats = scan_repo(root, DEFAULT_ROOTS)
    payload = {"stats": stats, "entries": entries}
    text = json.dumps(payload, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {len(entries)} broad handlers to {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
