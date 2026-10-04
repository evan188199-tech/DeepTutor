#!/usr/bin/env python3
"""Refinement pass over raw scan JSON: reclassify storage & await usage.

Reads py_async_tasks.json, adds per-entry refinement:
  storage: bare | attr | local | other_expr
  awaited: True if the saved name is later awaited or passed to
           gather/wait/as_completed/ensure_future/shield
Read-only; writes refined JSON.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

AWAIT_PASSERS = {"gather", "wait", "as_completed", "ensure_future", "shield", "timeout"}


def refine(root: Path, entries: list[dict]) -> None:
    cache: dict[str, ast.Module] = {}

    def tree_for(rel: str) -> ast.Module:
        if rel not in cache:
            src = (root / rel).read_text(encoding="utf-8", errors="replace")
            cache[rel] = ast.parse(src, filename=rel)
        return cache[rel]

    for e in entries:
        if e["kind"] != "create_task/ensure_future":
            continue
        tree = tree_for(e["rel"])
        call = None
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and getattr(n, "lineno", None) == e["line"]:
                f = n.func
                t = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
                if t in ("create_task", "ensure_future"):
                    call = n
                    break
        if call is None:
            continue
        parent = None
        pmap = {}
        for n in ast.walk(tree):
            for c in ast.iter_child_nodes(n):
                pmap[c] = n
        parent = pmap.get(call)

        if isinstance(parent, ast.Expr):
            e["storage"] = "bare"
        elif isinstance(parent, ast.Assign):
            tgts = parent.targets[0]
            if isinstance(tgts, ast.Attribute):
                e["storage"] = "attr"
                e["storage_desc"] = f"{ast.unparse(tgts)}"
            elif isinstance(tgts, ast.Subscript):
                e["storage"] = "attr"
                e["storage_desc"] = f"{ast.unparse(tgts)}"
            elif isinstance(tgts, ast.Name):
                e["storage"] = "local"
                e["storage_desc"] = tgts.id
                e["awaited"] = local_name_consumed(tree, tgts.id, parent.lineno)
            else:
                e["storage"] = "other"
        else:
            e["storage"] = "expr"


def local_name_consumed(tree: ast.Module, name: str, after_line: int) -> bool:
    for n in ast.walk(tree):
        if isinstance(n, ast.Await):
            v = n.value
            if isinstance(v, ast.Name) and v.id == name and v.lineno > after_line:
                return True
        if isinstance(n, ast.Call):
            f = n.func
            t = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if t in AWAIT_PASSERS:
                for a in n.args + [k.value for k in n.keywords]:
                    if isinstance(a, (ast.Name, ast.Starred)) and (
                        (isinstance(a, ast.Name) and a.id == name)
                        or (isinstance(a, ast.Starred) and isinstance(a.value, ast.Name) and a.value.id == name)
                    ) and a.lineno > after_line:
                        return True
                    if isinstance(a, (ast.List, ast.Tuple, ast.Set)):
                        for el in a.elts:
                            if isinstance(el, ast.Name) and el.id == name and el.lineno > after_line:
                                return True
    return False


def main() -> int:
    root = Path(sys.argv[1])
    infile = Path(sys.argv[2])
    data = json.loads(infile.read_text())
    refine(root, data["entries"])
    infile.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    from collections import Counter
    print(Counter((e.get("storage", "-"), e.get("awaited"), e["status"]) for e in data["entries"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
