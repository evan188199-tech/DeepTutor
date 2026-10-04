#!/usr/bin/env python3
"""Collect Python import statements with guard/lazy context via AST.

Outputs raw/py_imports.json:
  files: [{path, imports: [{module, top, line, lazy, guarded, weak_guard, type_checking}]}]
  dynamic: [{path, line, target, kind}]  # importlib.import_module / find_spec / __import__
"""
import ast
import json
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
SCAN_DIRS = ["deeptutor", "deeptutor_cli", "deeptutor_web", "scripts", "tests"]
EXCLUDE_PARTS = {".git", "node_modules", ".next", "__pycache__", ".venv", "venv", "build", "dist", ".ruff_cache", ".pytest_cache"}

GUARD_EXC = {"ImportError", "ModuleNotFoundError"}


def collect():
    files = []
    dynamic = []
    py_files = []
    for d in SCAN_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            if not any(part in EXCLUDE_PARTS for part in p.parts):
                py_files.append(p)
    for p in sorted(py_files):
        rel = str(p.relative_to(ROOT))
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as e:
            files.append({"path": rel, "error": str(e), "imports": []})
            continue

        imports = []
        specs_in_file = []

        # First pass: find dynamic import targets
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = None
                if isinstance(fn, ast.Attribute):
                    name = fn.attr
                    val = fn.value
                    if isinstance(val, ast.Name):
                        name = f"{val.id}.{fn.attr}"
                elif isinstance(fn, ast.Name):
                    name = fn.id
                if name in ("importlib.import_module", "import_module") and node.args:
                    if isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        dynamic.append({"path": rel, "line": node.lineno, "target": node.args[0].value, "kind": "import_module"})
                if name in ("importlib.util.find_spec", "find_spec", "util.find_spec") and node.args:
                    if isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        target = node.args[0].value
                        dynamic.append({"path": rel, "line": node.lineno, "target": target, "kind": "find_spec"})
                        specs_in_file.append(target.split(".")[0])

        # Second pass: classify each Import/ImportFrom with ancestor context
        def record(node, ctx):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append({
                        "module": alias.name,
                        "top": alias.name.split(".")[0],
                        "line": node.lineno,
                        "lazy": ctx[0],
                        "guarded": bool(ctx[1]),
                        "weak_guard": ctx[2],
                        "type_checking": ctx[3],
                        "relative": False,
                        "from_import": False,
                    })
                return
            if isinstance(node, ast.ImportFrom):
                base = node.module if node.module is not None else ""
                for alias in node.names:
                    if node.level and node.level > 0:
                        top = "."
                        mod = ("." * node.level) + base + ("::" + alias.name)
                    else:
                        top = base.split(".")[0] if base else "."
                        mod = base + ("::" + alias.name)
                    imports.append({
                        "module": mod,
                        "top": top,
                        "line": node.lineno,
                        "lazy": ctx[0],
                        "guarded": bool(ctx[1]),
                        "weak_guard": ctx[2],
                        "type_checking": ctx[3],
                        "relative": bool(node.level),
                        "from_import": True,
                    })
                return
            raise AssertionError("record() called on non-import node")

        def visit(node, ctx):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                record(node, ctx)
                return
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                for child in ast.iter_child_nodes(node):
                    visit(child, (True, ctx[1], ctx[2], ctx[3]))
                return
            if isinstance(node, ast.If):
                tcheck = _is_type_checking(node.test)
                for child in node.body:
                    visit(child, (ctx[0], ctx[1], ctx[2], ctx[3] or tcheck))
                for sub in node.orelse:
                    visit(sub, ctx)
                return
            if isinstance(node, ast.With):
                # `with suppress(ImportError):` counts as a guard
                for item in node.items:
                    cm = item.context_expr
                    if (isinstance(cm, ast.Call) and isinstance(cm.func, ast.Name)
                            and cm.func.id == "suppress" and cm.args
                            and isinstance(cm.args[0], ast.Name) and cm.args[0].id in GUARD_EXC):
                        ctx = (ctx[0], ctx[1] | {"suppressed"}, ctx[2], ctx[3])
                for child in ast.iter_child_nodes(node):
                    visit(child, ctx)
                return
            if isinstance(node, (ast.Try, getattr(ast, "TryStar", ast.Try))):
                g = set(ctx[1])
                w = ctx[2]
                for h in node.handlers:
                    names = set()
                    t = h.type
                    if t is None:
                        w = True
                    else:
                        if isinstance(t, ast.Name):
                            names.add(t.id)
                        elif isinstance(t, ast.Tuple):
                            names |= {e.id for e in t.elts if isinstance(e, ast.Name)}
                    if names & GUARD_EXC:
                        g.update(names)
                for sub in node.body:
                    visit(sub, (ctx[0], g, w, ctx[3]))
                for h in node.handlers:
                    for sub in h.body:
                        visit(sub, (ctx[0], ctx[1], ctx[2], ctx[3]))
                for sub in node.orelse + node.finalbody:
                    visit(sub, ctx)
                return
            for child in ast.iter_child_nodes(node):
                visit(child, ctx)

        visit(tree, (False, set(), False, False))
        files.append({"path": rel, "imports": imports, "spec_checks": sorted(set(specs_in_file))})

    return {"files": files, "dynamic": dynamic}


def _is_type_checking(test):
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING":
        return True
    if isinstance(test, ast.BoolOp):
        return any(_is_type_checking(v) for v in test.values)
    return False


if __name__ == "__main__":
    out = ROOT / "evidence/scan-deps-20261004/raw/py_imports.json"
    out.write_text(json.dumps(collect(), indent=1, ensure_ascii=False))
    print(f"wrote {out}")
