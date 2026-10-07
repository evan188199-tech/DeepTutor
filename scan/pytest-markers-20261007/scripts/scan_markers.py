#!/usr/bin/env python3
"""Static audit of pytest marker registration/usage consistency.

Read-only: parses pytest config (pyproject.toml) and every Python file under
the configured testpaths, then emits a deterministic JSON inventory.

Usage: python3 scan_markers.py <repo-root> <output-json-path>
Stdlib only. Same input -> same output (all results sorted).
"""

import ast
import json
import sys
import tomllib
from collections import Counter, defaultdict
from pathlib import Path

# Markers provided by pytest itself; never require registration.
BUILTIN_MARKERS = {
    "parametrize",
    "skip",
    "skipif",
    "xfail",
    "usefixtures",
    "filterwarnings",
    "tryfirst",
    "trylast",
}
# Markers provided by declared plugins (requirements/dev.txt).
PLUGIN_MARKERS = {"asyncio"}  # pytest-asyncio


def rel(repo: Path, p: Path) -> str:
    return p.relative_to(repo).as_posix()


def marker_chain(node: ast.AST) -> list[str] | None:
    """Return ['pytest', 'mark', name, ...] if node is pytest.mark.<chain>."""
    names = []
    cur = node
    while isinstance(cur, ast.Attribute):
        names.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name) and cur.id == "pytest" and names and names[-1] == "mark":
        names.append("pytest")
        names.reverse()
        return names
    return None


def marker_names_from(node: ast.AST) -> list[str]:
    """All marker names referenced by a pytest.mark.<...> expression.

    Unwraps calls (pytest.mark.skipif(cond, ...) is a Call wrapping the
    Attribute) and lists/tuples of such expressions.
    """
    if isinstance(node, ast.Call):
        return marker_names_from(node.func)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return [n for elt in node.elts for n in marker_names_from(elt)]
    chain = marker_chain(node)
    if not chain:
        return []
    # chain is pytest, mark, n1[, n2, ...]; chained attributes are all markers
    return chain[2:]


def marks_kwarg_names(node: ast.AST) -> list[str]:
    """Marker names inside a `marks=...` keyword of pytest.param/parametrize."""
    names = []
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        for elt in node.elts:
            names.extend(marker_names_from(elt))
    else:
        names.extend(marker_names_from(node))
    return names


def call_kwargs(call: ast.Call) -> tuple[dict[str, ast.AST], list[ast.AST]]:
    kwargs = {kw.arg: kw.value for kw in call.keywords if kw.arg}
    return kwargs, call.args


def main(repo_root: str, out_path: str) -> None:
    repo = Path(repo_root).resolve()
    ini = tomllib.loads((repo / "pyproject.toml").read_text(encoding="utf-8"))
    pytest_cfg = ini["tool"]["pytest"]["ini_options"]
    registered = sorted(
        m.split(":", 1)[0].strip() for m in pytest_cfg.get("markers", [])
    )
    testpaths = pytest_cfg.get("testpaths", ["tests"])

    files = sorted(
        p
        for tp in testpaths
        for p in (repo / tp).rglob("*.py")
        if p.is_file()
    )

    marker_use: dict[str, list] = defaultdict(list)  # name -> [{path,line,ctx}]
    no_reason: dict[str, list] = defaultdict(list)
    pytestmark_mods: list = []
    importorskip_no_reason: list = []
    selector_sites: list = []

    def add(name: str, path: str, line: int, ctx: str) -> None:
        marker_use[name].append({"path": path, "line": line, "ctx": ctx})

    def add_no_reason(kind: str, path: str, line: int, ctx: str) -> None:
        no_reason[kind].append({"path": path, "line": line, "ctx": ctx})

    for f in files:
        rp = rel(repo, f)
        src = f.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(f))
        # module-level pytestmark
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                if any(
                    isinstance(t, ast.Name) and t.id == "pytestmark" for t in targets
                ):
                    val = node.value
                    names = (
                        marker_names_from(val)
                        if val is not None
                        else []
                    )
                    if isinstance(val, (ast.List, ast.Tuple, ast.Set)):
                        names = [
                            n for elt in val.elts for n in marker_names_from(elt)
                        ]
                    pytestmark_mods.append(
                        {"path": rp, "line": node.lineno, "markers": sorted(names)}
                    )
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and marker_chain(node):
                for name in marker_names_from(node):
                    add(name, rp, node.lineno, "attribute")
            elif isinstance(node, ast.Call):
                fn = node.func
                # pytest.param(..., marks=...)
                if isinstance(fn, ast.Attribute) and fn.attr == "param":
                    for kw in node.keywords:
                        if kw.arg == "marks":
                            for name in marks_kwarg_names(kw.value):
                                add(name, rp, node.lineno, "pytest.param(marks=)")
                # pytest.skip / pytest.xfail runtime calls
                if isinstance(fn, ast.Attribute) and isinstance(
                    fn.value, ast.Name
                ) and fn.value.id == "pytest" and fn.attr in {"skip", "xfail"}:
                    kwargs, args = call_kwargs(node)
                    has_reason = "reason" in kwargs or bool(args)
                    if not has_reason:
                        add_no_reason(
                            f"pytest.{fn.attr}()",
                            rp,
                            node.lineno,
                            "call without message",
                        )
                # pytest.importorskip
                if isinstance(fn, ast.Attribute) and isinstance(
                    fn.value, ast.Name
                ) and fn.value.id == "pytest" and fn.attr == "importorskip":
                    kwargs, _ = call_kwargs(node)
                    if "reason" not in kwargs:
                        importorskip_no_reason.append(
                            {"path": rp, "line": node.lineno}
                        )

        # reason-less decorator marks: handled via marker_use context below

    # Second pass: decorator call sites for skip/skipif/xfail reason audit.
    for f in files:
        rp = rel(repo, f)
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        for node in ast.walk(tree):
            if not isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                continue
            for dec in node.decorator_list:
                for name in marker_names_from(dec):
                    add(name, rp, dec.lineno, f"decorator:{node.name}")
                    if name in {"skip", "skipif", "xfail"}:
                        bare = not isinstance(dec, ast.Call)
                        kwargs = {}
                        if isinstance(dec, ast.Call):
                            kwargs, _ = call_kwargs(dec)
                        if bare or "reason" not in kwargs:
                            add_no_reason(
                                f"mark.{name}" + (" (bare)" if bare else ""),
                                rp,
                                dec.lineno,
                                f"decorator on {node.name}",
                            )

    known = set(registered) | BUILTIN_MARKERS | PLUGIN_MARKERS
    unregistered = sorted(set(marker_use) - known)
    unused = sorted(set(registered) - set(marker_use))

    # pairwise co-occurrence per test function (module pytestmark merged in)
    mod_markers_by_file: dict[str, set] = defaultdict(set)
    for entry in pytestmark_mods:
        mod_markers_by_file[entry["path"]].update(entry["markers"])
    combos: Counter = Counter()
    func_markers: dict[tuple, set] = defaultdict(set)
    for f in files:
        rp = rel(repo, f)
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        for node in ast.walk(tree):
            if not isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                continue
            names: set = set(mod_markers_by_file.get(rp, ()))
            for dec in node.decorator_list:
                names.update(marker_names_from(dec))
            if names:
                key = (rp, node.name)
                func_markers[key].update(names)
    for key, names in func_markers.items():
        if len(names) > 1:
            for a in sorted(names):
                for b in sorted(names):
                    if a < b:
                        combos[(a, b)] += 1

    result = {
        "registered_markers": registered,
        "builtin_markers_exempt": sorted(BUILTIN_MARKERS),
        "plugin_markers_exempt": sorted(PLUGIN_MARKERS),
        "unregistered_in_use": unregistered,
        "registered_unused": unused,
        "marker_usage_points": {
            name: sorted(v, key=lambda d: (d["path"], d["line"]))
            for name, v in sorted(marker_use.items())
        },
        "no_reason_marks": {
            kind: sorted(v, key=lambda d: (d["path"], d["line"]))
            for kind, v in sorted(no_reason.items())
        },
        "importorskip_without_reason": sorted(
            importorskip_no_reason, key=lambda d: (d["path"], d["line"])
        ),
        "module_pytestmark": sorted(
            pytestmark_mods, key=lambda d: (d["path"], d["line"])
        ),
        "marker_pair_combos": sorted(
            ({"pair": list(k), "count": v} for k, v in combos.items()),
            key=lambda d: (-d["count"], d["pair"]),
        ),
        "files_scanned": len(files),
    }
    Path(out_path).write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"files={len(files)} markers={len(marker_use)} "
        f"unregistered={len(unregistered)} unused={len(unused)} "
        f"no_reason={sum(len(v) for v in no_reason.values())}"
    )


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
