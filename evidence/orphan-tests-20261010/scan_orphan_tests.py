#!/usr/bin/env python3
"""Orphan-test three-state scan for DeepTutor.

Read-only over the working tree (assumed == origin/main). For every test
file under pytest testpaths (tests/, deeptutor/learning/tests/):

  1. collect deeptutor-local imports (absolute + in-package relative) and
     resolve each target module and `from M import n` symbol against the
     tree at HEAD;
  2. collect skip signals (pytestmark skip / skipif with statically true
     condition / module-level pytest.skip / importorskip of a local
     module);
  3. classify each file:
       valid    - every local import resolves, no long-term skip signal
       drift    - imports resolve but an active long-term skip signal
                  exists (target drifted; file never really runs)
       broken   - at least one local import cannot resolve at HEAD
                  (collection-time failure); suggest delete or rename
  4. sys.modules stub injection (in the file itself or any tests/
     conftest.py) suppresses a broken verdict for the stubbed module.

Usage: python3 scan_orphan_tests.py <repo-root> <out-json>
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

LONG_TERM_REASON = re.compile(
    r"legacy|deprecat|removed|no longer|migrat|obsolete|superseded|renamed|replaced|old ",
    re.IGNORECASE,
)

# string-target patch/setattr sinks: patch("a.b.c"), monkeypatch.setattr("a.b.c", ...)
PATCH_FUNCS = {"patch", "patch.object"}
PATCH_EXCLUDE = {"patch.dict", "patch.multiple", "patch.multiple.object"}


def resolve_patch_target(root: Path, target: str) -> tuple[Path | None, str, list[str]]:
    """Split a dotted target into (module, [attrs]) using the longest
    existing module prefix. Returns (module_file_or_None, module, attrs).
    module None means no prefix of the path resolves."""
    parts = target.split(".")
    for cut in range(len(parts), 0, -1):
        mod = ".".join(parts[:cut])
        mf = module_file(root, mod)
        if mf is not None:
            return mf, mod, parts[cut:]
    return None, "", parts


def module_file(root: Path, mod: str) -> Path | None:
    """Return the file backing `mod`, a namespace-package dir, or None."""
    base = root.joinpath(*mod.split("."))
    f = base.with_name(base.name + ".py")
    if f.is_file():
        return f
    init = base / "__init__.py"
    if init.is_file():
        return init
    if base.is_dir() and any(base.glob("*.py")):
        return base  # PEP 420 namespace package (no __init__.py)
    return None


def top_level_names(path: Path) -> set[str]:
    """Names importable from module `path` at module scope."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return set()
    names: set[str] = set()
    has_getattr = False
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
                elif isinstance(t, (ast.Tuple, ast.List)):
                    names.update(e.id for e in t.elts if isinstance(e, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.Import):
            for a in node.names:
                names.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name != "*":
                    names.add(a.asname or a.name)
        elif isinstance(node, ast.If):
            # conditional definitions (version guards etc.) still count
            for sub in ast.walk(node):
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names.add(sub.name)
        elif isinstance(node, ast.Try):
            for sub in ast.walk(node):
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names.add(sub.name)
                elif isinstance(sub, ast.Import):
                    names.update((a.asname or a.name).split(".")[0] for a in sub.names)
                elif isinstance(sub, ast.ImportFrom):
                    names.update(a.asname or a.name for a in sub.names if a.name != "*")
        elif (
            isinstance(node, ast.FunctionDef)
            and node.name == "__getattr__"
        ):
            has_getattr = True
    if has_getattr:
        names.add("__getattr__")
    return names


def resolve_symbol(root: Path, mod: str, name: str) -> bool:
    """True if `from mod import name` can resolve."""
    mf = module_file(root, mod)
    if mf is None:
        return False
    # `from pkg import submodule` also works (regular or namespace pkg)
    if module_file(root, mod + "." + name):
        return True
    if mf.is_dir():  # namespace package without matching submodule
        return False
    return name in top_level_names(mf) or "__getattr__" in top_level_names(mf)


def attr_chain(node: ast.expr) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def static_true(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant):
        return node.value is True or node.value == 1
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return isinstance(node.operand, ast.Constant) and node.operand.value is False
    return False


def main() -> None:
    root = Path(sys.argv[1]).resolve()
    out_path = Path(sys.argv[2])

    files = sorted(root.glob("tests/**/test_*.py")) + sorted(
        root.glob("deeptutor/learning/tests/test_*.py")
    )

    conftest_text = "\n".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in sorted(root.glob("tests/**/conftest.py"))
    )

    results = []
    for f in files:
        rel = f.relative_to(root).as_posix()
        src = f.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(src)
        except SyntaxError as e:
            results.append(
                {"file": rel, "verdict": "broken", "cases": [
                    {"kind": "syntax-error", "line": e.lineno, "detail": str(e.msg)}],
                 "skips": [], "notes": []}
            )
            continue

        # in-package tests live at deeptutor/learning/tests -> package deeptutor.learning.tests
        pkg_parts = f.parent.relative_to(root).parts

        cases: list[dict] = []
        skips: list[dict] = []
        notes: list[str] = []

        def is_local(mod: str) -> bool:
            return mod == "deeptutor" or mod.startswith("deeptutor.")

        def record_import(node: ast.ImportFrom | ast.Import, level: int = 0) -> None:
            stmt = ast.get_source_segment(src, node) or ""
            stmt = stmt.split("\n")[0][:160]
            if isinstance(node, ast.Import):
                for a in node.names:
                    mod = a.name
                    if is_local(mod):
                        ok = module_file(root, mod) is not None
                        cases.append({
                            "kind": "import-module", "line": node.lineno,
                            "stmt": stmt, "target": mod, "resolved": ok,
                        })
                return
            if node.module is None and level == 0:
                return
            if level > 0:
                # relative import: base = pkg_parts[: len(pkg_parts) - level]
                base = pkg_parts[: len(pkg_parts) - (level - 1) - 1] if level > 1 else pkg_parts[:-1]
                base = list(base)
                if node.module:
                    base += node.module.split(".")
                mod = ".".join(base) if base else ""
            else:
                mod = node.module or ""
            if not is_local(mod):
                return
            ok_mod = module_file(root, mod) is not None
            if not ok_mod:
                cases.append({
                    "kind": "from-module-missing", "line": node.lineno,
                    "stmt": stmt, "target": mod, "resolved": False,
                    "names": [a.name for a in node.names if a.name != "*"],
                })
                return
            for a in node.names:
                if a.name == "*":
                    continue
                ok = resolve_symbol(root, mod, a.name)
                if not ok:
                    cases.append({
                        "kind": "from-symbol-missing", "line": node.lineno,
                        "stmt": stmt, "target": f"{mod}.{a.name}", "resolved": False,
                    })

        module_skip_assign = None
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                record_import(node, node.level)
            elif isinstance(node, ast.Import):
                record_import(node, 0)
            elif isinstance(node, ast.Call):
                fn = node.func
                fname = attr_chain(fn) if isinstance(fn, ast.Attribute) else (
                    fn.id if isinstance(fn, ast.Name) else None)
                if fname in ("pytest.skip", "skip", "pytest.fail"):
                    allow = any(
                        kw.arg == "allow_module_level" and static_true(kw.value)
                        for kw in node.keywords
                    )
                    reason = ""
                    if node.args and isinstance(node.args[0], ast.Constant):
                        reason = str(node.args[0].value)
                    skips.append({
                        "kind": "module-skip" if allow else "skip-call",
                        "line": node.lineno, "reason": reason[:200],
                        "allow_module_level": allow,
                    })
                elif fname == "pytest.importorskip":
                    target = ""
                    if node.args and isinstance(node.args[0], ast.Constant):
                        target = str(node.args[0].value)
                    skips.append({
                        "kind": "importorskip", "line": node.lineno,
                        "target": target, "local": is_local(target),
                    })
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == "pytestmark":
                        val = node.value
                        call = val if isinstance(val, ast.Call) else (
                            val.elts[-1] if isinstance(val, (ast.Tuple, ast.List)) and val.elts
                            and isinstance(val.elts[-1], ast.Call) else None)
                        if call is not None and isinstance(call.func, ast.Attribute):
                            mark = call.func.attr
                            if mark in ("skip", "skipif"):
                                cond_true = bool(call.args) and static_true(call.args[0])
                                reason = ""
                                for arg in call.args[1 if mark == "skipif" else 0:]:
                                    if isinstance(arg, ast.Constant):
                                        reason = str(arg.value)
                                module_skip_assign = {
                                    "kind": "pytestmark", "line": node.lineno,
                                    "mark": mark, "static_true": cond_true,
                                    "reason": reason[:200],
                                }
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                        mark = dec.func.attr
                        if mark == "skipif" and dec.args and static_true(dec.args[0]):
                            reason = ""
                            for arg in dec.args[1:]:
                                if isinstance(arg, ast.Constant):
                                    reason = str(arg.value)
                            skips.append({
                                "kind": "skipif-static-true", "line": dec.lineno,
                                "on": node.name, "reason": reason[:200],
                            })
                        elif mark == "skip":
                            reason = ""
                            if dec.args and isinstance(dec.args[0], ast.Constant):
                                reason = str(dec.args[0].value)
                            skips.append({
                                "kind": "skip-unconditional", "line": dec.lineno,
                                "on": node.name, "reason": reason[:200],
                            })

        # string-target patch / monkeypatch.setattr orphan check (case level)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                continue
            fname = attr_chain(node.func) if isinstance(node.func, ast.Attribute) else (
                node.func.id if isinstance(node.func, ast.Name) else None)
            is_patch = fname in PATCH_FUNCS or (
                isinstance(fname, str) and fname.endswith(".patch") and fname != "patch.dict")
            is_setattr = fname == "monkeypatch.setattr" or fname == "mocker.setattr"
            if not (is_patch or is_setattr):
                continue
            target = node.args[0].value
            if not (target.startswith("deeptutor.") or target.startswith("tests.")):
                continue
            mf, mod, attrs = resolve_patch_target(root, target)
            if mf is None:
                cases.append({
                    "kind": "patch-module-missing", "line": node.lineno,
                    "stmt": f"{fname}({target!r})", "target": target, "resolved": False,
                })
                continue
            missing_attr = None
            if not attrs:
                continue  # target is the module itself
            head = attrs[0]
            if mf.is_dir() or mf.name == "__init__.py":
                # head may be a submodule of the package
                if module_file(root, mod + "." + head):
                    continue
            names = top_level_names(mf) if not mf.is_dir() else set()
            if head not in names:
                text = (
                    mf.read_text(encoding="utf-8", errors="replace")
                    if not mf.is_dir() else ""
                )
                # text fallback covers class methods / nested defs / dynamic defs
                if not re.search(r"\b" + re.escape(head) + r"\b", text):
                    missing_attr = head
            if missing_attr:
                cases.append({
                    "kind": "patch-attr-missing", "line": node.lineno,
                    "stmt": f"{fname}({target!r})",
                    "target": target, "module": mod, "missing": missing_attr,
                    "resolved": False,
                })

        # classify broken cases with stub suppression
        broken = []
        for c in cases:
            if c["resolved"]:
                continue
            stub_pat = re.compile(
                r"""sys\.modules[\.\[](\()?(setdefault|insert)?\(?[\[\"']+"""
                + re.escape(c["target"].rsplit(".", 1)[0] if c["kind"] == "from-symbol-missing" else c["target"])
            )
            target_full = c["target"]
            stubbed = False
            for probe in {target_full, target_full.rsplit(".", 1)[0]}:
                if re.search(r"""sys\.modules\[[\"']""" + re.escape(probe), conftest_text) or \
                   re.search(r"""sys\.modules\[[\"']""" + re.escape(probe), src) or \
                   re.search(r"""sys\.modules\.setdefault\([\"']""" + re.escape(probe), conftest_text) or \
                   re.search(r"""sys\.modules\.setdefault\([\"']""" + re.escape(probe), src):
                    stubbed = True
                    notes.append(f"stub-injected: {probe}")
                    break
            if not stubbed:
                broken.append(c)

        # drift signals: active long-term skip
        drift_signals = []
        for s in skips:
            if s["kind"] == "importorskip" and s.get("local"):
                tgt = s["target"]
                exists = module_file(root, tgt) is not None
                if not exists:
                    drift_signals.append({**s, "active": True,
                                          "detail": f"local module missing: {tgt}"})
                else:
                    drift_signals.append({**s, "active": False,
                                          "detail": f"local module present (dormant): {tgt}"})
            elif s["kind"] in ("pytestmark",) and (s["static_true"] or LONG_TERM_REASON.search(s.get("reason", ""))):
                drift_signals.append({**s, "active": s["static_true"] or bool(s.get("reason")),
                                      "detail": f"pytestmark {s['mark']}"})
            elif s["kind"] == "skipif-static-true":
                drift_signals.append({**s, "active": True, "detail": "skipif(static true)"})
            elif s["kind"] == "skip-unconditional":
                drift_signals.append({**s, "active": True, "detail": "unconditional skip"})
            elif s["kind"] == "module-skip" or (s["kind"] == "skip-call" and s.get("allow_module_level")):
                drift_signals.append({**s, "active": True, "detail": "module-level pytest.skip"})

        active_drift = [d for d in drift_signals if d.get("active")]
        import_broken = [
            c for c in broken
            if c["kind"] in ("import-module", "from-module-missing",
                             "from-symbol-missing", "syntax-error")
        ]
        patch_broken = [c for c in broken if c["kind"].startswith("patch-")]
        if import_broken:
            verdict = "broken"
        elif patch_broken or active_drift:
            verdict = "drift"
        else:
            verdict = "valid"

        results.append({
            "file": rel,
            "verdict": verdict,
            "cases": broken,
            "drift_signals": drift_signals,
            "notes": sorted(set(notes)),
        })

    out_path.write_text(json.dumps(results, indent=1, ensure_ascii=False))
    counts = {"valid": 0, "drift": 0, "broken": 0}
    for r in results:
        counts[r["verdict"]] += 1
    print(json.dumps({"total": len(results), **counts}))
    for r in results:
        if r["verdict"] != "valid":
            print(r["verdict"], r["file"], flush=True)


if __name__ == "__main__":
    main()
