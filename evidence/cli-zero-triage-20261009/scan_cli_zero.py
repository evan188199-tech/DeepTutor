#!/usr/bin/env python3
"""Zero-test module triage for deeptutor_cli/**.

Deterministic, reproducible scan. For every Python module under
``deeptutor_cli`` it computes:

- ``loc``: physical line count of the module file.
- ``test_refs``: number of textual references (import / from-import /
  patch target strings) in any test file under ``tests/`` or ``web/tests``.
- ``test_files``: distinct test files referencing the module.
- ``fanin_repo``: distinct non-test source modules in the repository
  (deeptutor/, deeptutor_cli/, scripts/) that import the module.
- ``fanin_cli``: subset of fanin_repo coming from deeptutor_cli itself.

A module is "zero-test" iff ``test_refs == 0``.

Usage: python scan_cli_zero.py <repo-root> [out.json]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def module_name(rel: str) -> str:
    return rel.replace("/", ".").removesuffix(".py")


def main() -> int:
    root = Path(sys.argv[1]).resolve()
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    pkg = "deeptutor_cli"

    cli_dir = root / pkg
    modules = sorted(
        p for p in cli_dir.rglob("*.py")
        if "__pycache__" not in p.parts
    )
    mod_names = [module_name(p.relative_to(root).as_posix()) for p in modules]

    # Precompile per-module patterns: import X / from X import / "X." strings.
    patterns = {}
    rel_patterns = {}  # relative imports, valid only inside deeptutor_cli
    for name in mod_names:
        esc = re.escape(name)
        patterns[name] = re.compile(
            rf"(?:^|\n)\s*(?:import {esc}\b|from {esc}\b)|[\"']{esc}\b"
        )
        base = name.rsplit(".", 1)[-1]
        rel_patterns[name] = re.compile(rf"(?:^|\n)\s*from \.{base}\b")

    test_roots = [root / "tests", root / "web" / "tests"]
    src_roots = [root / "deeptutor", root / pkg, root / "scripts"]

    def iter_py(root_dir: Path) -> list[Path]:
        return [
            p for p in root_dir.rglob("*.py")
            if "__pycache__" not in p.parts
        ]

    test_files = [p for r in test_roots if r.exists() for p in iter_py(r)]
    src_files = [p for r in src_roots if r.exists() for p in iter_py(r)]

    rows = []
    for path, name in zip(modules, mod_names):
        rel = path.relative_to(root).as_posix()
        loc = len(path.read_text(encoding="utf-8", errors="replace").splitlines())

        test_refs = 0
        test_hit_files: list[str] = []
        for tf in test_files:
            text = tf.read_text(encoding="utf-8", errors="replace")
            n = len(patterns[name].findall(text))
            if n:
                test_refs += n
                test_hit_files.append(tf.relative_to(root).as_posix())

        fanin_files: list[str] = []
        for sf in src_files:
            if sf == path:
                continue
            text = sf.read_text(encoding="utf-8", errors="replace")
            hit = patterns[name].search(text)
            if not hit and sf.relative_to(root).as_posix().startswith(pkg + "/"):
                hit = rel_patterns[name].search(text)
            if hit:
                fanin_files.append(sf.relative_to(root).as_posix())

        fanin_cli = [f for f in fanin_files if f.startswith(pkg + "/")]
        rows.append({
            "path": rel,
            "loc": loc,
            "test_refs": test_refs,
            "test_files": sorted(test_hit_files),
            "fanin_repo": sorted(fanin_files),
            "fanin_repo_n": len(fanin_files),
            "fanin_cli_n": len(fanin_cli),
            "zero_test": test_refs == 0,
        })

    rows.sort(key=lambda r: (-r["loc"], r["path"]))
    payload = {
        "base_commit": __import__("subprocess").run(
            ["git", "rev-parse", "HEAD"], cwd=root,
            capture_output=True, text=True).stdout.strip(),
        "module_count": len(rows),
        "zero_test_count": sum(1 for r in rows if r["zero_test"]),
        "modules": rows,
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if out_path:
        Path(out_path).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
