#!/usr/bin/env python3
"""Read-only static coverage-gap scanner for AGEN-662/873.

Maps every module under deeptutor/ to test files using two tiers:
  T1 path-correspondence : test file path contains the module's stem
  T2 import-correspondence: test file imports the module (ast-based,
    exact dotted-name match)

Test universe (AGEN-1209 intree fix): root tests/ plus in-tree test files
deeptutor/**/test_*.py (the 24 files under deeptutor/learning/tests/ and the
package-internal deeptutor/services/config/test_runner.py), so T1/T2 mapping
and n_tests see the full test universe. In-tree tests import via absolute
``deeptutor.*`` names (learning: 24/24, see evidence/learning-intree-20261009);
the one intree file using relative imports (test_runner.py) is resolved
against its own package root instead of tests/. Provenance is recorded as
``deeptutor_tree`` (object name of HEAD:deeptutor) instead of the old
HEAD sha, so re-runs at a branch tip that only adds evidence files stay
byte-identical.

Deterministic (AGEN-873): T2 previously matched via `" ".join(set)` substring
concatenation, whose result depended on PYTHONHASHSEED-driven set iteration
order. Matching is now an exact dotted-prefix test over sorted iteration, so
output is byte-identical across seeds.

Outputs JSON stats consumed by report generation. Stdlib only.
"""
import ast
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PKG = os.path.join(ROOT, "deeptutor")
TESTS = os.path.join(ROOT, "tests")
EVIDENCE_DIR = os.path.join(ROOT, "evidence", "coverage-gaps-intree-20261009")


def py_files(base):
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in (".venv", "node_modules", "__pycache__")]
        for fn in filenames:
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)


def module_key(path):
    """deeptutor/services/xxx/foo.py -> 'services.xxx.foo'"""
    rel = os.path.relpath(path, PKG)
    parts = rel[:-3].split(os.sep)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def stem(path):
    return os.path.splitext(os.path.basename(path))[0]


def test_imports(path, intree=False):
    """Return set of dotted names imported from deeptutor package."""
    names = set()
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            tree = ast.parse(f.read(), filename=path)
    except SyntaxError:
        return names
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                names.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                if intree:
                    # package-internal test: resolve relative imports against
                    # its own package root (deeptutor/), not tests/
                    pkg = os.path.relpath(os.path.dirname(path), PKG).replace(os.sep, ".").split(".")
                    base = pkg[: len(pkg) - (node.level - 1)]
                else:
                    # relative import inside tests: resolve against tests/ package root
                    pkg = os.path.relpath(os.path.dirname(path), TESTS).replace(os.sep, ".")
                    base = pkg.split(".")[: node.level]
                if node.module:
                    names.add(".".join(base + [node.module]))
                for a in node.names:
                    names.add(".".join(base + [node.module or "", a.name]).strip("."))
            elif node.module:
                names.add(node.module)
                for a in node.names:
                    names.add(node.module + "." + a.name)
    return {n for n in names if n == "deeptutor" or n.startswith("deeptutor.")}


def main():
    modules = [p for p in py_files(PKG)]
    root_tests = [p for p in py_files(TESTS)]
    intree_tests = sorted(m for m in modules if os.path.basename(m).startswith("test_"))
    tests = root_tests + intree_tests
    intree_set = set(intree_tests)

    test_rel_imports = {}
    stem_index = defaultdict(set)  # test stem -> set of test paths
    for t in tests:
        test_rel_imports[t] = test_imports(t, intree=t in intree_set)
        stem_index[stem(t)].add(t)

    mod_records = []
    for m in modules:
        key = module_key(m)
        is_init = stem(m) == "__init__"
        s = stem(m)
        # T1: path correspondence (test file name contains module stem)
        t1 = set()
        if s and s != "__init__":
            for ts in sorted(stem_index):
                if s == ts or s in ts.split("_"):
                    t1 |= stem_index[ts]
        # T2: import correspondence (exact dotted-name match against the
        # fully-qualified module path "deeptutor.<key>"; an import of any
        # dotted submodule also counts, since it executes this module).
        full = "deeptutor." + key if key else "deeptutor"
        t2 = set()
        for t in sorted(test_rel_imports):
            names = test_rel_imports[t]
            if full in names or any(n.startswith(full + ".") for n in sorted(names)):
                t2.add(t)
        covered = t1 | t2
        mod_records.append({
            "module": key,
            "path": os.path.relpath(m, ROOT),
            "loc": sum(1 for _ in open(m, encoding="utf-8", errors="replace")),
            "is_init": is_init,
            "t1": sorted(os.path.relpath(x, ROOT) for x in t1),
            "t2": sorted(os.path.relpath(x, ROOT) for x in t2),
            "covered": sorted(os.path.relpath(x, ROOT) for x in covered),
            "n_cover": len(covered),
        })

    out = {
        "deeptutor_tree": os.popen("git rev-parse HEAD:deeptutor").read().strip() if os.path.isdir(os.path.join(ROOT, ".git")) or os.path.exists(os.path.join(ROOT, ".git")) else "unknown",
        "n_modules": len(modules),
        "n_tests": len(tests),
        "n_root_tests": len(root_tests),
        "n_intree_tests": len(intree_tests),
        "intree_test_files": sorted(os.path.relpath(x, ROOT) for x in intree_tests),
        "modules": mod_records,
    }
    with open(os.path.join(EVIDENCE_DIR, "coverage_raw.json"), "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"modules={len(modules)} tests={len(tests)} (root={len(root_tests)} intree={len(intree_tests)})")


if __name__ == "__main__":
    sys.exit(main())
