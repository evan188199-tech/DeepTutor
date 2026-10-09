#!/usr/bin/env python3
"""Aggregate coverage_raw.json into per-subpackage stats + zero/weak lists.

Also computes import fan-in (internal reverse-dependency count) as a risk proxy.
Stdlib only. Read-only over the repo tree.

AGEN-1209 intree fix: the scanner's test universe now includes in-tree test
files (deeptutor/**/test_*.py), so every module's ``covered``/``n_cover``
already reflects tests/ + in-tree tests. zero/weak are determined purely from
``n_cover``; the in-tree bookkeeping (``intree_tests`` count and the single
``intree_test_modules`` list) is kept for traceability and is derived from the
same basename criterion the scanner uses, so ``totals.tests`` (raw n_tests)
and ``totals.intree_tests`` share one source and never double-count.
"""
import ast
import json
import os
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PKG = os.path.join(ROOT, "deeptutor")

with open(os.path.join(HERE, "coverage_raw.json")) as f:
    raw = json.load(f)

mods = raw["modules"]
# in-package test files (e.g. deeptutor/learning/tests/test_*.py) are tests, not modules
INTREE_TESTS = [m for m in mods if os.path.basename(m["path"]).startswith("test_")]
mods = [m for m in mods if not os.path.basename(m["path"]).startswith("test_")]

def fk(name):
    return "deeptutor." + name

# intree test imports map like tests/ imports (informational only since the
# scanner now folds in-tree tests into covered/n_cover)
intree_imports = {}
for t in INTREE_TESTS:
    p = os.path.join(ROOT, t["path"])
    names = set()
    try:
        tree = ast.parse(open(p, encoding="utf-8", errors="replace").read())
    except SyntaxError:
        tree = None
    if tree:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
                names |= {node.module + "." + a.name for a in node.names}
    intree_imports[t["module"]] = {n for n in names if n == "deeptutor" or n.startswith("deeptutor.")}

by_key = {m["module"]: m for m in mods}

# --- import fan-in: reverse internal dependency count ---
fanin = defaultdict(set)
for dirpath, dirnames, filenames in os.walk(PKG):
    dirnames[:] = [d for d in dirnames if d != "__pycache__"]
    for fn in filenames:
        if not fn.endswith(".py"):
            continue
        p = os.path.join(dirpath, fn)
        rel = os.path.relpath(p, PKG)[:-3].split(os.sep)
        is_init_mod = rel[-1] == "__init__"
        if is_init_mod:
            rel = rel[:-1]
        src = ".".join(rel)
        pkg_parts = rel if is_init_mod else rel[:-1]
        try:
            tree = ast.parse(open(p, encoding="utf-8", errors="replace").read())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.startswith("deeptutor.") and a.name != src:
                        fanin[a.name].add(src)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = pkg_parts[: len(pkg_parts) - (node.level - 1)] if node.level > 1 else pkg_parts
                    mod = ".".join(["deeptutor"] + base + ([node.module] if node.module else []))
                else:
                    mod = node.module or ""
                if mod.startswith("deeptutor.") and mod != "deeptutor." + src:
                    fanin[mod].add("deeptutor." + src)
                    for a in node.names:
                        full = mod + "." + a.name
                        if full != "deeptutor." + src:
                            fanin[full].add("deeptutor." + src)

# --- per-subpackage aggregation ---
sub = defaultdict(lambda: {"total": 0, "init": 0, "covered": 0, "zero": 0, "zero_loc": 0})
zero_noninit, covered_weak = [], []
intree_cover = defaultdict(set)  # module -> intree test modules covering it
for tmod, names in intree_imports.items():
    for n in names:
        bare = n[len("deeptutor."):] if n.startswith("deeptutor.") else n
        if bare in by_key:
            intree_cover[bare].add(tmod)
for m in mods:
    m["intree_tests"] = sorted(intree_cover.get(m["module"], ()))
    top = m["module"].split(".")[0]
    s = sub[top]
    s["total"] += 1
    if m["is_init"]:
        s["init"] += 1
        if m["n_cover"] == 0:
            s["zero"] += 1
        else:
            s["covered"] += 1
        continue
    if m["n_cover"] == 0:
        s["zero"] += 1
        s["zero_loc"] += m["loc"]
        zero_noninit.append(m)
    else:
        s["covered"] += 1
        m["fanin"] = len(fanin.get(fk(m["module"]), ()))
        # weak = exactly one covering test file across tests/ + in-tree
        if m["n_cover"] == 1:
            covered_weak.append(m)

zero_noninit.sort(key=lambda m: (-m["loc"], -len(fanin.get(fk(m["module"]), ()))))
covered_weak.sort(key=lambda m: (m["loc"], ), reverse=True)

summary = {
    "root_commit": raw.get("root_commit"),
    "totals": {"modules": raw["n_modules"] - len(INTREE_TESTS), "tests": raw["n_tests"],
               "intree_tests": len(INTREE_TESTS),
               "noninit": sum(1 for m in mods if not m["is_init"]),
               "zero_noninit": len(zero_noninit),
               "weak_single_test": len(covered_weak)},
    "subpackages": {k: dict(v) for k, v in sorted(sub.items())},
    "fanin_top50": sorted(((k, len(v)) for k, v in fanin.items()), key=lambda x: -x[1])[:50],
    "zero_top200": [{"module": m["module"], "loc": m["loc"],
                     "fanin": len(fanin.get(fk(m["module"]), ())),
                     "path": m["path"]} for m in zero_noninit[:200]],
    "weak_top100": [{"module": m["module"], "loc": m["loc"],
                     "fanin": len(fanin.get(fk(m["module"]), ())),
                     "path": m["path"],
                     "tests": m["covered"]} for m in covered_weak[:100]],
    "intree_test_modules": [m["module"] for m in INTREE_TESTS],
}
with open(os.path.join(HERE, "summary.json"), "w") as f:
    json.dump(summary, f, ensure_ascii=False, indent=1)

# console digest
print("== per-subpackage ==")
for k, v in sorted(sub.items()):
    noninit = v["total"] - v["init"]
    print(f"{k:20s} total={v['total']:4d} noninit={noninit:4d} covered={v['covered']:4d} zero={v['zero']:3d} zero_loc={v['zero_loc']}")
print("zero_noninit:", len(zero_noninit), "| weak(single-test):", len(covered_weak), "| intree_tests:", len(INTREE_TESTS))
print("== fanin top 15 ==")
for k, n in summary["fanin_top50"][:15]:
    print(f"  {k}: {n}")
