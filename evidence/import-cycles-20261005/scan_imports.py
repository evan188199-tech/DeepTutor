#!/usr/bin/env python3
"""Read-only scanner: import cycles, function-level (lazy) import hotspots,
and import-time side effects for a Python source tree.

Standard library only. Never writes to the scanned tree; all output goes to
the directory given via --out.

Usage:
    python3 scan_imports.py --repo <repo-root> --out <evidence-dir> \
        --roots deeptutor deeptutor_cli scripts
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict, deque

# --------------------------------------------------------------------------
# file collection
# --------------------------------------------------------------------------


def is_test_path(rel: str) -> bool:
    parts = rel.split(os.sep)
    base = parts[-1]
    if "tests" in parts or "testing" in parts:
        return True
    if base.startswith("test_") or base.endswith("_test.py") or base == "conftest.py":
        return True
    return False


def collect_files(repo: str, roots: list[str]) -> dict[str, str]:
    """Return {dotted_module_name: relative_posix_path}."""
    index: dict[str, str] = {}
    for root in roots:
        base = os.path.join(repo, root)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [
                d for d in dirnames
                if d not in ("__pycache__", ".git", "node_modules")
            ]
            for fn in filenames:
                if not fn.endswith(".py"):
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, repo)
                posix = rel.replace(os.sep, "/")
                if is_test_path(posix):
                    continue
                dotted = posix[:-3].replace("/", ".")
                if dotted.endswith(".__init__"):
                    dotted = dotted[: -len(".__init__")]
                index[dotted] = posix
    return index


# --------------------------------------------------------------------------
# AST parsing
# --------------------------------------------------------------------------


class ModuleScan:
    __slots__ = (
        "dotted", "rel", "tree", "top_imports", "lazy_imports",
        "top_assign_calls", "top_calls", "environ_writes", "dynamic_imports",
        "top_try_imports", "log_configs", "io_calls", "atexit_signal",
        "parse_error",
    )

    def __init__(self, dotted: str, rel: str):
        self.dotted = dotted
        self.rel = rel
        self.tree = None
        self.top_imports: list[dict] = []
        self.lazy_imports: list[dict] = []
        self.top_assign_calls: list[dict] = []
        self.top_calls: list[dict] = []
        self.environ_writes: list[dict] = []
        self.dynamic_imports: list[dict] = []
        self.top_try_imports: list[dict] = []
        self.log_configs: list[dict] = []
        self.io_calls: list[dict] = []
        self.atexit_signal: list[dict] = []
        self.parse_error: str | None = None


def callee_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = callee_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Call):
        return callee_name(node.func)
    return ""


def assign_target_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Tuple):
        return ",".join(assign_target_name(e) for e in node.elts)
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return assign_target_name(node.value) + "[...]"
    return "?"


def is_environ_target(node: ast.AST) -> bool:
    if isinstance(node, ast.Subscript):
        node = node.value
    if isinstance(node, ast.Attribute):
        if node.attr == "environ":
            return True
        return is_environ_target(node.value)
    if isinstance(node, ast.Name):
        return node.id == "environ"
    return False


SIDE_EFFECT_CALL_RE = (
    "setup", "configure", "config", "init", "initialise", "initialize",
    "register", "install", "load", "connect", "start", "run", "migrate",
    "ensure", "create", "bootstrap", "activate", "enable", "patch",
)

SINGLETON_HINTS = (
    "Service", "Manager", "Store", "Client", "Config", "Registry",
    "Provider", "Factory", "Tracker", "Cache", "Pool", "Container",
    "Context", "Engine", "Helper", "Resolver", "Locator", "Coordinator",
)

# constructors that are cheap constants with no observable side effect
CHEAP_CONSTRUCTORS = {
    "threading.Lock", "threading.RLock", "threading.Semaphore",
    "threading.Event", "threading.Condition", "threading.local",
    "ContextVar", "Path", "PurePath", "PurePosixPath",
    "deque", "defaultdict", "OrderedDict", "Counter",
    "TypeVar", "ParamSpec", "TypeAdapter", "dataclass", "re.compile",
    "Decimal", "timezone.utc", "Enum", "IntEnum", "StrEnum", "Flag",
    "partial", "lru_cache", "cache", "SimpleNamespace", "struct",
}


def _hints_singleton(last: str) -> bool:
    return last.endswith(SINGLETON_HINTS)


def stmt_snippet(node: ast.AST, limit: int = 110) -> str:
    try:
        text = ast.unparse(node)
    except Exception:
        text = node.__class__.__name__
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text


def scan_module(dotted: str, rel: str, full: str) -> ModuleScan:
    m = ModuleScan(dotted, rel)
    try:
        with open(full, "rb") as fh:
            src = fh.read()
        m.tree = ast.parse(src, filename=full)
    except SyntaxError as exc:
        m.parse_error = f"{exc.lineno}: {exc.msg}"
        return m

    pkg_parts = dotted.split(".")
    # for a package (__init__), the package is the module itself;
    # for a plain module, the package is its parent.
    is_package = rel.endswith("__init__.py")

    def resolve_relative(level: int) -> list[str]:
        base = pkg_parts if is_package else pkg_parts[:-1]
        if level > len(base):
            return []
        return base[: len(base) - (level - 1)] if level > 0 else base

    for top in m.tree.body:
        # top-level direct statements
        if isinstance(top, (ast.Import, ast.ImportFrom)):
            m.top_imports.append(_import_record(top, [], []))
        elif isinstance(top, ast.Expr) and isinstance(top.value, ast.Call):
            name = callee_name(top.value.func)
            m.top_calls.append({
                "line": top.lineno, "callee": name,
                "snippet": stmt_snippet(top),
            })
            if name in ("logging.basicConfig", "logging.config.dictConfig",
                        "structlog.configure"):
                m.log_configs.append({"line": top.lineno, "callee": name})
            if name in ("atexit.register",):
                m.atexit_signal.append({"line": top.lineno, "callee": name})
            if name in ("signal.signal",):
                m.atexit_signal.append({"line": top.lineno, "callee": name})
            if name.split(".")[-1] in ("mkdir", "makedirs"):
                m.io_calls.append({"line": top.lineno, "callee": name,
                                   "snippet": stmt_snippet(top)})
            if name in ("open", "json.load", "yaml.safe_load", "tomllib.load"):
                m.io_calls.append({"line": top.lineno, "callee": name,
                                   "snippet": stmt_snippet(top)})
        elif isinstance(top, (ast.Assign, ast.AnnAssign)):
            targets = top.targets if isinstance(top, ast.Assign) else [top.target]
            value = top.value
            if isinstance(value, ast.Call):
                cname = callee_name(value.func)
                tnames = [assign_target_name(t) for t in targets]
                if any(is_environ_target(t) for t in targets):
                    m.environ_writes.append({
                        "line": top.lineno, "snippet": stmt_snippet(top),
                    })
                elif cname:
                    const_target = any(
                        t.isupper() and len(t) > 2 and t.replace("_", "").isalpha()
                        for t in tnames
                    )
                    classish = cname.split(".")[-1][:1].isupper()
                    if const_target or classish:
                        m.top_assign_calls.append({
                            "line": top.lineno, "target": ",".join(tnames),
                            "callee": cname, "snippet": stmt_snippet(top),
                        })
            else:
                if any(is_environ_target(t) for t in targets):
                    m.environ_writes.append({
                        "line": top.lineno, "snippet": stmt_snippet(top),
                    })
        elif isinstance(top, ast.Try):
            for sub in ast.walk(top):
                if isinstance(sub, (ast.Import, ast.ImportFrom)):
                    handlers = top.handlers
                    broad = any(
                        h.type is None
                        or (isinstance(h.type, ast.Name) and h.type.id == "Exception")
                        or (isinstance(h.type, ast.Attribute) and h.type.attr == "Exception")
                        for h in handlers
                    )
                    m.top_try_imports.append({
                        "line": sub.lineno,
                        "broad_except": broad,
                        "snippet": stmt_snippet(sub, 80),
                    })
                elif isinstance(sub, ast.Call):
                    name = callee_name(sub.func)
                    m.top_calls.append({
                        "line": sub.lineno, "callee": name,
                        "snippet": "(inside top-level try) " + stmt_snippet(sub, 90),
                    })

    # function-level imports (the lazy ones), anywhere in the tree
    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: list[str] = []
            self.type_checking_depth = 0

        def _imports(self, node, in_type_checking: bool):
            rec = _import_record(node, list(self.stack), [])
            rec["in_type_checking"] = in_type_checking
            rec["lazy"] = bool(self.stack) or in_type_checking
            (m.lazy_imports if rec["lazy"] else m.top_imports).append(rec)

        def visit_If(self, node: ast.If) -> None:
            tc = self._is_type_checking(node.test)
            if self._is_main_guard(node.test):
                return  # does not execute at import time
            if tc:
                self.type_checking_depth += 1
            self.generic_visit(node)
            if tc:
                self.type_checking_depth -= 1

        @staticmethod
        def _is_type_checking(test) -> bool:
            if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
                return True
            if isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING":
                return True
            if isinstance(test, ast.BoolOp):
                return any(Visitor._is_type_checking(v) for v in test.values)
            return False

        @staticmethod
        def _is_main_guard(test) -> bool:
            if isinstance(test, ast.Compare):
                try:
                    return "__name__" in ast.unparse(test)
                except Exception:
                    return False
            return False

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Import(self, node: ast.Import) -> None:
            self._imports(node, self.type_checking_depth > 0)

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            self._imports(node, self.type_checking_depth > 0)

    Visitor().visit(m.tree)

    # dynamic imports
    for node in ast.walk(m.tree):
        if isinstance(node, ast.Call):
            name = callee_name(node.func)
            if name in ("importlib.import_module", "__import__"):
                m.dynamic_imports.append({
                    "line": node.lineno, "callee": name,
                    "snippet": stmt_snippet(node, 90),
                })
    return m


def _import_record(node, func_stack: list[str], extra: list) -> dict:
    rec: dict = {"line": node.lineno, "func": ".".join(func_stack)}
    if isinstance(node, ast.Import):
        rec["kind"] = "import"
        rec["modules"] = [a.name for a in node.names]
        rec["display"] = ", ".join(a.name for a in node.names)
    else:
        rec["kind"] = "from"
        rec["module"] = node.module or ""
        rec["level"] = node.level
        rec["names"] = [a.name for a in node.names]
        shown = f"{'.' * node.level}{node.module or ''}"
        rec["display"] = f"from {shown} import {', '.join(rec['names'])}"
    return rec


# --------------------------------------------------------------------------
# resolution & graph
# --------------------------------------------------------------------------


def resolve_import(rec: dict, dotted: str, index: dict[str, str],
                   is_package: bool) -> list[str]:
    """Resolve one import record to internal module dotted names."""
    pkg_parts = dotted.split(".")
    base = pkg_parts if is_package else pkg_parts[:-1]

    def abs_name(module: str, level: int) -> str:
        if level == 0:
            return module
        b = list(base)
        if level > len(b):
            return module
        b = b[: len(b) - (level - 1)]
        return ".".join(b + ([module] if module else []))

    targets: list[str] = []
    if rec["kind"] == "import":
        for name in rec["modules"]:
            if name in index:
                targets.append(name)
            else:
                # importing a submodule also runs parent packages, but for
                # cycle purposes keep the leaf; if leaf missing, try parents
                parts = name.split(".")
                for i in range(len(parts) - 1, 0, -1):
                    cand = ".".join(parts[:i])
                    if cand in index:
                        targets.append(cand)
                        break
    else:
        mod = abs_name(rec["module"], rec["level"])
        resolved_mod = None
        if rec["module"] == "" and rec["level"] > 0:
            resolved_mod = ".".join(base)
        elif mod in index:
            resolved_mod = mod
        else:
            parts = mod.split(".")
            for i in range(len(parts) - 1, 0, -1):
                cand = ".".join(parts[:i])
                if cand in index:
                    resolved_mod = cand
                    break
        for nm in rec["names"]:
            if nm == "*":
                if resolved_mod:
                    targets.append(resolved_mod)
                continue
            sub = f"{resolved_mod}.{nm}" if resolved_mod else nm
            if sub in index:
                targets.append(sub)
            elif resolved_mod in index:
                targets.append(resolved_mod)
            else:
                parts = sub.split(".")
                for i in range(len(parts) - 1, 0, -1):
                    cand = ".".join(parts[:i])
                    if cand in index:
                        targets.append(cand)
                        break
    return sorted(set(targets))


# --------------------------------------------------------------------------
# cycles (Tarjan SCC + concrete path)
# --------------------------------------------------------------------------


def tarjan_scc(graph: dict[str, set[str]]) -> list[list[str]]:
    idx_counter = [0]
    stack: list[str] = []
    on_stack: set[str] = set()
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    result: list[list[str]] = []

    def strongconnect(v: str) -> None:
        work = [(v, iter(sorted(graph.get(v, ()))))]
        index[v] = low[v] = idx_counter[0]
        idx_counter[0] += 1
        stack.append(v)
        on_stack.add(v)
        while work:
            node, it = work[-1]
            advanced = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = idx_counter[0]
                    idx_counter[0] += 1
                    stack.append(w)
                    on_stack.add(w)
                    work.append((w, iter(sorted(graph.get(w, ())))))
                    advanced = True
                    break
                elif w in on_stack:
                    low[node] = min(low[node], index[w])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                comp = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == node:
                        break
                result.append(comp)

    for v in sorted(graph):
        if v not in index:
            strongconnect(v)
    return result


def find_cycle_path(scc: set[str], graph: dict[str, set[str]]) -> list[str] | None:
    start = sorted(scc)[0]
    q: deque[list[str]] = deque([[start]])
    seen = {start}
    while q:
        path = q.popleft()
        cur = path[-1]
        for nxt in sorted(graph.get(cur, ())):
            if nxt == start and len(path) >= 2:
                return path + [start]
            if nxt in scc and nxt not in seen:
                seen.add(nxt)
                q.append(path + [nxt])
    return None


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--roots", nargs="+", default=["deeptutor", "deeptutor_cli", "scripts"])
    ap.add_argument("--entrypoints", nargs="*", default=[
        "deeptutor_cli.__main__", "deeptutor_cli.main", "deeptutor.__main__",
        "deeptutor.api.main", "scripts.start_web", "scripts.start_tour",
        "scripts.update",
    ])
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)

    index = collect_files(repo, args.roots)
    scans: dict[str, ModuleScan] = {}
    pkg_of: dict[str, bool] = {}
    for dotted, rel in index.items():
        full = os.path.join(repo, rel)
        scans[dotted] = scan_module(dotted, rel, full)
        pkg_of[dotted] = rel.endswith("__init__.py")

    # ---- graph edges -------------------------------------------------
    # edge_kind: "top" (module level) dominates "lazy"
    edges: dict[str, dict[str, dict]] = defaultdict(dict)
    for dotted, m in scans.items():
        for rec in m.top_imports:
            for tgt in resolve_import(rec, dotted, index, pkg_of[dotted]):
                if tgt == dotted:
                    continue
                e = edges[dotted].setdefault(tgt, {"kind": "top", "lines": []})
                e["lines"].append((m.rel, rec["line"], rec["display"]))
        for rec in m.lazy_imports:
            for tgt in resolve_import(rec, dotted, index, pkg_of[dotted]):
                if tgt == dotted:
                    continue
                e = edges[dotted].setdefault(tgt, {"kind": "lazy", "lines": []})
                e["lines"].append((m.rel, rec["line"], rec["display"]))

    graph_top = {s: {t for t, e in ts.items() if e["kind"] == "top"}
                 for s, ts in edges.items()}
    graph_all = {s: set(ts) for s, ts in edges.items()}

    # ---- SCCs --------------------------------------------------------
    sccs_all = [c for c in tarjan_scc(graph_all) if len(c) > 1]
    sccs_top = [c for c in tarjan_scc(graph_top) if len(c) > 1]
    top_cycle_nodes: set[str] = set()
    for comp in sccs_top:
        top_cycle_nodes.update(comp)

    cycles = []
    for comp in sorted(sccs_all, key=len, reverse=True):
        cs = set(comp)
        path = find_cycle_path(cs, graph_all)
        # risk: is the induced top-level subgraph itself cyclic?
        induced_top = {
            n: {t for t in graph_top.get(n, ()) if t in cs} for n in comp
        }
        induced_sccs = [c for c in tarjan_scc(induced_top) if len(c) > 1]
        has_top = bool(induced_sccs)
        top_edges, lazy_edges = [], []
        for a in comp:
            for b, e in edges.get(a, {}).items():
                if b in cs:
                    first = e["lines"][0]
                    rec = {
                        "src": a, "dst": b, "kind": e["kind"],
                        "file": first[0], "line": first[1], "stmt": first[2],
                    }
                    (top_edges if e["kind"] == "top" else lazy_edges).append(rec)
        top_edges.sort(key=lambda r: (r["src"], r["dst"]))
        lazy_edges.sort(key=lambda r: (r["src"], r["dst"]))
        cycle_edges = []
        if path:
            for a, b in zip(path, path[1:]):
                e = edges.get(a, {}).get(b)
                if e:
                    first = e["lines"][0]
                    cycle_edges.append({
                        "src": a, "dst": b, "kind": e["kind"],
                        "file": first[0], "line": first[1], "stmt": first[2],
                    })
        cycles.append({
            "size": len(comp),
            "import_time_risk": has_top,
            "induced_top_sccs": induced_sccs[:5],
            "top_edge_count": len(top_edges),
            "lazy_edge_count": len(lazy_edges),
            "top_edges_sample": top_edges[:25],
            "members": sorted(comp),
            "path": path,
            "edges": cycle_edges,
        })

    # ---- lazy import hotspots ----------------------------------------
    hotspot: dict[tuple[str, str], dict] = {}
    per_file_repeats: list[dict] = []
    total_lazy = 0
    files_with_lazy = set()
    for dotted, m in scans.items():
        per_file: dict[tuple[str, str], list[int]] = defaultdict(list)
        for rec in m.lazy_imports:
            total_lazy += 1
            if rec.get("in_type_checking"):
                continue  # typing-only imports do not count as runtime lazy
            files_with_lazy.add(dotted)
            if rec["kind"] == "from":
                key_disp = rec["display"]
                mod = rec["module"]
                sym = ",".join(rec["names"])
            else:
                key_disp = rec["display"]
                mod = rec["modules"][0] if rec["modules"] else ""
                sym = ""
            key = (mod, sym)
            h = hotspot.setdefault(key, {"count": 0, "files": set(),
                                         "display": key_disp, "sites": []})
            h["count"] += 1
            h["files"].add(dotted)
            h["sites"].append((m.rel, rec["line"], rec["func"] or "<module>"))
            per_file[key].append(rec["line"])
        for key, lines in per_file.items():
            if len(lines) > 1:
                per_file_repeats.append({
                    "file": m.rel, "import": hotspot[key]["display"],
                    "count": len(lines), "lines": lines[:12],
                })

    top_hotspots = sorted(
        hotspot.items(), key=lambda kv: (-kv[1]["count"], -len(kv[1]["files"]))
    )[:20]

    # ---- import-time side effects ------------------------------------
    # startup reachability: forward BFS over top-level graph (files executed
    # during startup = entrypoints plus everything they import at module level)
    fwd: dict[str, set[str]] = {s: set(ts) for s, ts in graph_top.items()}
    entries = [e for e in args.entrypoints if e in index]
    reach: set[str] = set(entries)
    q = deque(entries)
    while q:
        cur = q.popleft()
        for nxt in fwd.get(cur, ()):
            if nxt not in reach:
                reach.add(nxt)
                q.append(nxt)

    side_effects: list[dict] = []
    for dotted, m in scans.items():
        on_startup = dotted in reach

        def add(category: str, risk: str, line: int, snippet: str,
                note: str = "") -> None:
            side_effects.append({
                "file": m.rel, "dotted": dotted, "line": line,
                "category": category, "risk": risk,
                "startup_reachable": on_startup,
                "snippet": snippet, "note": note,
            })

        for c in m.log_configs:
            add("logging config at import", "medium", c["line"], c["callee"])
        for c in m.environ_writes:
            r = "high" if on_startup else "low"
            add("os.environ write at import", r, c["line"], c["snippet"])
        for c in m.io_calls:
            r = "high" if on_startup else "medium"
            add("file/dir IO at import", r, c["line"], c["snippet"])
        for c in m.atexit_signal:
            add("atexit/signal registration at import", "medium",
                c["line"], c["callee"])
        for c in m.top_assign_calls:
            const = c["target"].isupper() and len(c["target"]) > 2
            last = c["callee"].split(".")[-1]
            classish = last[:1].isupper()
            if c["callee"] in CHEAP_CONSTRUCTORS or last in {
                n.split(".")[-1] for n in CHEAP_CONSTRUCTORS
            }:
                continue  # cheap constant, no startup impact
            if const and classish:
                risk = "high" if on_startup else "medium"
                add("module-level instance/singleton", risk, c["line"],
                    c["snippet"])
            elif _hints_singleton(last) or (classish and on_startup):
                risk = "medium" if on_startup else "low"
                add("module-level instance/singleton", risk, c["line"],
                    c["snippet"])
        for c in m.top_calls:
            low = callee_last = c["callee"].split(".")[-1]
            if callee_last.startswith("_") or callee_last in ("main", "mainloop"):
                continue
            if any(k in callee_last.lower() for k in SIDE_EFFECT_CALL_RE):
                risk = "high" if on_startup else "medium"
                add("module-level call", risk, c["line"], c["snippet"])
        for c in m.top_try_imports:
            if c["broad_except"]:
                add("top-level import in try/broad-except", "medium",
                    c["line"], c["snippet"],
                    note="import 失败被静默吞掉（DT-22 症状）")
        for c in m.dynamic_imports:
            add("dynamic import", "low", c["line"], c["snippet"])

    side_effects.sort(key=lambda d: (
        {"high": 0, "medium": 1, "low": 2}[d["risk"]],
        0 if d["startup_reachable"] else 1,
        d["file"], d["line"],
    ))

    # ---- stats --------------------------------------------------------
    parse_errors = [
        {"file": m.rel, "error": m.parse_error}
        for m in scans.values() if m.parse_error
    ]
    stats = {
        "files_scanned": len(index),
        "roots": args.roots,
        "entrypoints_found": entries,
        "startup_reachable_files": len(reach),
        "total_import_records_top": sum(len(m.top_imports) for m in scans.values()),
        "total_lazy_imports": total_lazy,
        "files_with_lazy": len(files_with_lazy),
        "cycles_scc_all": len(sccs_all),
        "cycles_scc_import_time": len(sccs_top),
        "side_effect_hits": len(side_effects),
        "parse_errors": parse_errors,
    }

    # ---- emit json ----------------------------------------------------
    def dump(name: str, obj) -> None:
        with open(os.path.join(out, name), "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2)

    dump("cycles.json", {
        "summary": {k: v for k, v in stats.items()},
        "import_time_sccs": [c for c in cycles if c["import_time_risk"]],
        "lazy_only_sccs": [c for c in cycles if not c["import_time_risk"]],
    })
    dump("lazy_hotspots.json", {
        "total_lazy": total_lazy,
        "files_with_lazy": len(files_with_lazy),
        "top20": [
            {
                "display": h["display"], "count": h["count"],
                "distinct_files": len(h["files"]),
                "files": sorted(h["files"]),
                "sites": [
                    {"file": s[0], "line": s[1], "func": s[2]}
                    for s in h["sites"][:40]
                ],
            }
            for _, h in top_hotspots
        ],
        "per_file_repeats": sorted(
            per_file_repeats, key=lambda d: -d["count"]
        )[:60],
    })
    dump("side_effects.json", {
        "startup_reachable_files": sorted(reach),
        "hits": side_effects,
    })

    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


def _split_disp(disp: str) -> tuple[str, str]:
    if disp.startswith("from "):
        rest = disp[len("from "):]
        mod, _, names = rest.partition(" import ")
        return mod, names
    return disp, ""


if __name__ == "__main__":
    sys.exit(main())
