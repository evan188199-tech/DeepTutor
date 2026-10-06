"""Inventory the pytest conftest/fixture layer of DeepTutor's test suite.

Read-only scan. Run from the repository root:

    python evidence/scan-conftest-dup-20261006/scripts/scan_conftest.py > \
        evidence/scan-conftest-dup-20261006/data/conftest_inventory.json

Emits one JSON document with:
- every conftest.py under tests/ and the fixtures it declares (name, line,
  scope, autouse, docstring)
- same-name collisions between conftest fixtures and module-level
  definitions (fixtures or plain helpers) in the modules they cover
- occurrences of the inline "redirect multi_user roots" patch block in
  test modules (the copy-pasted path-isolation pattern)

No repository file is modified.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

PATTERN_SNIPPET = 'setattr(paths, "ADMIN_WORKSPACE_ROOT"'


def _decorator_info(dec: ast.AST) -> dict:
    info = {"is_pytest_fixture": False, "scope": "function", "autouse": False}
    target = dec
    if isinstance(dec, ast.Call):
        target = dec.func
        for kw in dec.keywords:
            if kw.arg == "scope" and isinstance(kw.value, ast.Constant):
                info["scope"] = kw.value.value
            if kw.arg == "autouse":
                info["autouse"] = bool(kw.value.value)
    if isinstance(target, ast.Attribute):
        if (
            isinstance(target.value, ast.Name)
            and target.value.id == "pytest"
            and target.attr == "fixture"
        ):
            info["is_pytest_fixture"] = True
    return info


def _fixtures_in(path: Path) -> list[dict]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            info = _decorator_info(dec)
            if info["is_pytest_fixture"]:
                doc = ast.get_docstring(node)
                out.append(
                    {
                        "name": node.name,
                        "path": str(path),
                        "line": node.lineno,
                        "scope": info["scope"],
                        "autouse": info["autouse"],
                        "doc": (doc or "").splitlines()[0] if doc else "",
                    }
                )
                break
    return out


def _module_defs(path: Path) -> list[dict]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            has_fixture = any(_decorator_info(d)["is_pytest_fixture"] for d in node.decorator_list)
            out.append(
                {
                    "name": node.name,
                    "path": str(path),
                    "line": node.lineno,
                    "kind": "fixture" if has_fixture else "plain-function",
                }
            )
    return out


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    tests = root / "tests"
    conftests = sorted(tests.rglob("conftest.py"))

    inventory = {
        "repo_head": "",
        "conftests": [],
        "module_fixture_defs": [],
        "name_collisions": [],
        "inline_path_redirect_modules": [],
    }

    head = (root / ".git").exists()
    if head:
        import subprocess

        inventory["repo_head"] = (
            subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True
            ).stdout.strip()
        )

    for cf in conftests:
        tree = ast.parse(cf.read_text(encoding="utf-8"))
        has_addoption = any(
            isinstance(n, ast.FunctionDef) and n.name == "pytest_addoption" for n in tree.body
        )
        inventory["conftests"].append(
            {
                "path": str(cf),
                "lines": len(cf.read_text(encoding="utf-8").splitlines()),
                "pytest_addoption": has_addoption,
                "fixtures": _fixtures_in(cf),
            }
        )

    fixture_names = {
        f["name"] for c in inventory["conftests"] for f in c["fixtures"]
    }

    for module in sorted(tests.rglob("*.py")):
        if module.name == "conftest.py":
            continue
        rel = str(module)
        text = module.read_text(encoding="utf-8")
        if PATTERN_SNIPPET in text:
            inventory["inline_path_redirect_modules"].append(rel)
        defs = _module_defs(module)
        inventory["module_fixture_defs"].extend(d for d in defs if d["kind"] == "fixture")
        for d in defs:
            if d["name"] in fixture_names:
                inventory["name_collisions"].append(d)

    print(json.dumps(inventory, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
