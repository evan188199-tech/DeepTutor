#!/usr/bin/env python3
"""Read-only tempfile-hygiene inventory scanner for DeepTutor.

Usage:
    python3 scan_tempfile_hygiene.py <repo-root> <output-dir>

Emits deterministic JSON inventories (sorted, relative paths, no timestamps):
    data/tempfile-usage.json       tempfile API call sites (AST-derived)
    data/tmp-path-patterns.json    ad-hoc .tmp path / TMPDIR / /tmp literal lines
    data/summary.json              counts derived from the two inventories

Stdlib only. Never writes inside <repo-root>. Deterministic by construction:
walk order is sorted, JSON keys are sorted, output is byte-stable across runs.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

SKIP_DIRS = {
    ".git",
    ".github",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".ruff_cache",
    ".mypy_cache",
    "dist",
    "build",
    "evidence",
    ".deeptutor",
    "web",
}

TEMPFILE_ATTRS = {
    "mkdtemp",
    "mkstemp",
    "NamedTemporaryFile",
    "TemporaryDirectory",
    "SpooledTemporaryFile",
    "mktemp",
    "gettempdir",
    "gettempprefix",
}

REGEX_PATTERNS = [
    ("adhoc_tmp_with_suffix", ".with_suffix(" or ".with_name(" and ".tmp"),
    ("adhoc_tmp_fstring", "/ f\""),
    ("env_tmp", "TMPDIR"),
    ("env_tmp_tmp", '"TMP"'),
    ("env_tmp_temp", '"TEMP"'),
    ("system_tmp_literal", '"/tmp'),
]


def iter_py_files(root: Path) -> list[Path]:
    return sorted(
        (p for p in root.rglob("*.py") if not any(part in SKIP_DIRS for part in p.parts)),
        key=lambda p: p.as_posix(),
    )


def build_parent_map(node: ast.AST) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(node):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    return parents


def flags_for(call: ast.Call, parents: dict[ast.AST, ast.AST]) -> dict[str, bool]:
    in_with = False
    in_try = False
    node: ast.AST | None = call
    while node is not None:
        parent = parents.get(node)
        if isinstance(parent, ast.With):
            if any(
                item.context_expr is node or _contains(item.context_expr, call)
                for item in parent.items
            ):
                in_with = True
        if isinstance(parent, ast.Try) and any(_contains(stmt, call) for stmt in parent.body):
            in_try = True
        node = parent
    return {"in_with": in_with, "in_try": in_try}


def _contains(container: ast.AST, target: ast.AST) -> bool:
    return any(child is target for child in ast.walk(container))


def kwarg_const(call: ast.Call, name: str) -> object | None:
    for kw in call.keywords:
        if kw.arg == name and isinstance(kw.value, ast.Constant):
            return kw.value.value
    return None


def scan_tempfile_calls(root: Path) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for path in iter_py_files(root):
        rel = path.relative_to(root).as_posix()
        source = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(source, filename=rel)
        except SyntaxError:
            continue
        lines = source.splitlines()
        parents = build_parent_map(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            api = None
            if isinstance(func, ast.Attribute) and func.attr in TEMPFILE_ATTRS:
                base = func.value
                if isinstance(base, ast.Name) and base.id == "tempfile":
                    api = func.attr
            if api is None:
                continue
            snippet = lines[node.lineno - 1].strip()[:200] if node.lineno <= len(lines) else ""
            findings.append(
                {
                    "api": api,
                    "delete": kwarg_const(node, "delete"),
                    "dir_kwarg": any(kw.arg == "dir" for kw in node.keywords),
                    "file": rel,
                    "flags": flags_for(node, parents),
                    "line": node.lineno,
                    "scope": "tests" if rel.startswith(("tests/", "scripts/")) else "prod",
                    "text": snippet,
                }
            )
    findings.sort(key=lambda f: (f["file"], f["line"], f["api"]))
    return findings


def scan_tmp_path_patterns(root: Path) -> list[dict[str, object]]:
    import re

    pattern_specs = [
        ("adhoc_tmp_with_suffix", re.compile(r"with_(?:suffix|name)\([^\n]*\.tmp")),
        ("adhoc_tmp_fstring", re.compile(r"/\s*f[\"'][^\n]*\.tmp[\"']")),
        ("env_tmp", re.compile(r"TMPDIR")),
        ("env_tmp_tmp", re.compile(r"[\"']TMP[\"']")),
        ("env_tmp_temp", re.compile(r"[\"']TEMP[\"']")),
        ("system_tmp_literal", re.compile(r"[\"']/tmp[/\"']")),
        ("deprecated_mktemp", re.compile(r"tempfile\.mktemp\(")),
        ("gettempdir", re.compile(r"gettempdir\(")),
    ]
    findings: list[dict[str, object]] = []
    for path in iter_py_files(root):
        rel = path.relative_to(root).as_posix()
        source = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(source.splitlines(), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            kinds = [name for name, rx in pattern_specs if rx.search(line)]
            if not kinds:
                continue
            findings.append(
                {
                    "file": rel,
                    "kinds": kinds,
                    "line": lineno,
                    "scope": "tests" if rel.startswith(("tests/", "scripts/")) else "prod",
                    "text": stripped[:200],
                }
            )
    findings.sort(key=lambda f: (f["file"], f["line"], tuple(f["kinds"])))
    return findings


def summarize(calls: list[dict[str, object]], patterns: list[dict[str, object]]) -> dict[str, object]:
    prod_calls = [c for c in calls if c["scope"] == "prod"]
    by_api: dict[str, int] = {}
    for call in prod_calls:
        by_api[str(call["api"])] = by_api.get(str(call["api"]), 0) + 1
    delete_false = [
        c for c in prod_calls if c["api"] == "NamedTemporaryFile" and c["delete"] is False
    ]
    return {
        "prod_files_with_tempfile_api": len({str(c["file"]) for c in prod_calls}),
        "prod_lines_with_tmp_path_patterns": len([p for p in patterns if p["scope"] == "prod"]),
        "prod_namedtemporaryfile_delete_false": len(delete_false),
        "prod_tempfile_calls_by_api": dict(sorted(by_api.items())),
        "prod_tempfile_calls_total": len(prod_calls),
        "test_tempfile_calls_total": len(calls) - len(prod_calls),
        "total_tempfile_calls": len(calls),
    }


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    root = Path(sys.argv[1]).resolve()
    out = Path(sys.argv[2]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    calls = scan_tempfile_calls(root)
    patterns = scan_tmp_path_patterns(root)
    summary = summarize(calls, patterns)
    (out / "tempfile-usage.json").write_text(
        json.dumps({"findings": calls}, indent=1, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out / "tmp-path-patterns.json").write_text(
        json.dumps({"findings": patterns}, indent=1, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out / "summary.json").write_text(
        json.dumps(summary, indent=1, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=1, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
