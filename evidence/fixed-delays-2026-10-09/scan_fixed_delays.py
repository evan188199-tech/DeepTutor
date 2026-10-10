"""Scan DeepTutor Python sources for fixed delays, poll loops, and hardcoded timeouts.

Scope: deeptutor/, deeptutor_cli/, scripts/ (product source). Excludes any
tests/ tree, web/, assets/, docs/, examples/. Read-only: prints a CSV of
findings with path:line, kind, numeric value, blocking surface, and the
path rule used to grade the surface.

Usage: python3 scan_fixed_delays.py <repo-root> <out-csv>
"""

from __future__ import annotations

import ast
import csv
import sys
from pathlib import Path

REPO = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2])

INCLUDE_ROOTS = ("deeptutor", "deeptutor_cli", "scripts")
EXCLUDE_PARTS = {"tests", "web", "assets", "docs", "examples", "node_modules", ".wt-"}

# Blocking-surface rules, most specific first. (path_prefix_or_file, surface, rule_label)
SURFACE_RULES = [
    ("scripts/", "cli", "rule:scripts->cli"),
    ("deeptutor_cli/", "cli", "rule:deeptutor_cli->cli"),
    ("deeptutor/services/cli_apps/", "cli", "rule:services/cli_apps->cli"),
    ("deeptutor/services/codex_auth/", "cli", "rule:services/codex_auth->cli"),
    ("deeptutor/services/codebuddy_auth.py", "cli", "rule:services/codebuddy_auth->cli"),
    ("deeptutor/services/github_copilot_auth.py", "cli", "rule:services/github_copilot_auth->cli"),
    ("deeptutor/runtime/launcher.py", "cli", "rule:runtime/launcher->cli"),
    ("deeptutor/api/", "request", "rule:api->request"),
    ("deeptutor/app/", "request", "rule:app->request"),
    ("deeptutor/services/codebuddy_credentials.py", "request", "rule:services/codebuddy_credentials->request"),
    ("deeptutor/services/parsing/", "worker", "rule:services/parsing->worker"),
    ("deeptutor/reading/ingestion.py", "worker", "rule:reading/ingestion->worker"),
    ("deeptutor/services/embedding/", "worker", "rule:services/embedding->worker"),
    ("deeptutor/services/videogen/", "worker", "rule:services/videogen->worker"),
    ("deeptutor/services/imagegen/", "worker", "rule:services/imagegen->worker"),
    ("deeptutor/services/sandbox/", "worker", "rule:services/sandbox->worker"),
    ("deeptutor/plugins/", "worker", "rule:plugins->worker"),
    ("deeptutor/services/subagent/", "worker", "rule:services/subagent->worker"),
    ("deeptutor/partners/", "background", "rule:partners->background"),
    ("deeptutor/services/partners/", "background", "rule:services/partners->background"),
    ("deeptutor/services/web_source/", "background", "rule:services/web_source->background"),
    ("deeptutor/services/base_sync.py", "background", "rule:services/base_sync->background"),
    ("deeptutor/services/cron/", "background", "rule:services/cron->background"),
    ("deeptutor/events/", "background", "rule:events->background"),
    ("deeptutor/runtime/", "background", "rule:runtime->background"),
    ("deeptutor/services/app_update.py", "background", "rule:services/app_update->background"),
    ("deeptutor/services/memory/", "background", "rule:services/memory->background"),
]

SUGGESTIONS = {
    "sleep-fixed": "move to config/env (e.g. <MODULE>_<PURPOSE>_INTERVAL_S), keep current value as default; for poll loops add an upper bound on total wait",
    "sleep-yield": "keep (cooperative yield, not a real delay); optionally replace with asyncio.sleep(0) idiom constant",
    "timeout-net": "expose as client/config parameter with layered budgets (connect < read < total); align with caller timeout budget",
    "timeout-lock": "unify sqlite connect/busy_timeout values into one shared constant/config instead of per-module literals",
    "timeout-wait": "expose as parameter (default = current value); prefer cancellation/notification over fixed waits for long tasks",
}

UNIT_RULES = {
    "sync_forever": "ms",
    "pragma_busy_timeout": "ms",
}


def iter_py_files():
    for root in INCLUDE_ROOTS:
        base = REPO / root
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            rel = p.relative_to(REPO)
            if any(part in EXCLUDE_PARTS for part in rel.parts):
                continue
            if "tests" in rel.parts:
                continue
            yield p, rel.as_posix()


def dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def numeric_value(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        v = numeric_value(node.operand)
        return -v if v is not None else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
        a = numeric_value(node.left)
        b = numeric_value(node.right)
        if a is None or b is None:
            return None
        if isinstance(node.op, ast.Add):
            return a + b
        if isinstance(node.op, ast.Sub):
            return a - b
        if isinstance(node.op, ast.Mult):
            return a * b
        if isinstance(node.op, ast.Div):
            return a / b if b else None
        return a ** b if abs(b) < 16 else None
    return None


class ConstIndex:
    """Resolve simple module/class/self-attribute constants to numeric values."""

    def __init__(self, tree):
        self.module = {}
        self.init_params = {}  # class qualname -> {param: default}
        self.class_attrs = {}  # class qualname -> {name: value}
        self.self_attrs = {}   # class qualname -> {attr: value}
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                value = node.value
                scope_key = self._scope_of(node)
                val = numeric_value(value) if value is not None else None
                for t in targets:
                    if not isinstance(t, ast.Name):
                        continue
                    if val is not None:
                        if scope_key is None:
                            self.module[t.id] = val
                        else:
                            self.class_attrs.setdefault(scope_key, {})[t.id] = val
                    elif isinstance(value, (ast.Tuple, ast.List)):
                        elems = [numeric_value(e) for e in value.elts]
                        if elems and all(e is not None for e in elems):
                            if scope_key is None:
                                self.module_tuples[t.id] = elems
                            else:
                                self.class_tuples.setdefault(scope_key, {})[t.id] = elems
                    elif isinstance(value, ast.Name) and value.id in self.module:
                        self.module[t.id] = self.module[value.id]
                    elif isinstance(value, ast.Attribute) and isinstance(value.value, ast.Name):
                        # e.g. CONST = other_mod.CONST -- unresolvable; skip
                        pass
                # self.attr = literal (inside a class)
                if scope_key is not None and value is not None:
                    v = numeric_value(value)
                    if v is None and isinstance(value, ast.Name):
                        v = self.module.get(value.id)
                    if v is not None:
                        for t in targets:
                            if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self":
                                self.self_attrs.setdefault(scope_key, {})[t.attr] = v
        # second pass: self.attr = NAME where NAME is module const, inside __init__ or body
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                scope_key = self._scope_of(node)
                if scope_key is None or node.value is None:
                    continue
                if isinstance(node.value, ast.Name) and node.value.id in self.module:
                    v = self.module[node.value.id]
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for t in targets:
                        if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self":
                            self.self_attrs.setdefault(scope_key, {})[t.attr] = v

        # third pass: __init__ parameter defaults -> self.attr = <param> / max(lit, float(param))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "__init__":
                scope_key = self._scope_of(node.args if False else node)
                scope_key = getattr(node, "_cls_scope", None)
                if scope_key is None:
                    continue
                params = {}
                all_args = list(node.args.posonlyargs) + list(node.args.args) + list(node.args.kwonlyargs)
                defaults = [None] * (len(all_args) - len(node.args.defaults) - len(node.args.kw_defaults)) + list(node.args.defaults) + list(node.args.kw_defaults)
                for a, d in zip(all_args, defaults):
                    if a.arg in {"self", "cls"} or d is None:
                        continue
                    dv = numeric_value(d)
                    if dv is not None:
                        params[a.arg] = dv
                self.init_params[scope_key] = params
                for stmt in ast.walk(node):
                    if isinstance(stmt, (ast.Assign, ast.AnnAssign)) and stmt.value is not None:
                        targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                        v = self._init_value(stmt.value, params)
                        if v is not None:
                            for t in targets:
                                if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self":
                                    self.self_attrs.setdefault(scope_key, {}).setdefault(t.attr, v)

    @staticmethod
    def _init_value(value, params):
        v = numeric_value(value)
        if v is not None:
            return v
        if isinstance(value, ast.Name) and value.id in params:
            return params[value.id]
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in {"float", "int"} and value.args:
            return ConstIndex._init_value(value.args[0], params)
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in {"max", "min"} and len(value.args) == 2:
            a = ConstIndex._init_value(value.args[0], params)
            b = ConstIndex._init_value(value.args[1], params)
            if a is not None and b is not None:
                return max(a, b) if value.func.id == "max" else min(a, b)
        return None

    _tuple_consts: dict = {}
    module_tuples: dict = {}
    class_tuples: dict = {}

    @staticmethod
    def _scope_of(node):
        return getattr(node, "_cls_scope", None)


class ScopeTagger(ast.NodeVisitor):
    """Tag class-body statements with their class qualname via a parallel walk."""

    def __init__(self):
        self.stack = []

    def visit_ClassDef(self, node):
        name = (self.stack[-1] + "." if self.stack else "") + node.name
        self.stack.append(name)
        for stmt in ast.walk(node):
            if isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.FunctionDef, ast.AsyncFunctionDef)):
                if not hasattr(stmt, "_cls_scope") or isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    stmt._cls_scope = name
        self.generic_visit(node)
        self.stack.pop()


def eval_num(node, consts, cls_scope, depth=0):
    """Evaluate a simple numeric expression using module/class/self constants."""
    if depth > 6:
        return None
    v = numeric_value(node)
    if v is not None:
        return v
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
        a = eval_num(node.left, consts, cls_scope, depth + 1)
        b = eval_num(node.right, consts, cls_scope, depth + 1)
        if a is None or b is None:
            return None
        if isinstance(node.op, ast.Add):
            return a + b
        if isinstance(node.op, ast.Sub):
            return a - b
        if isinstance(node.op, ast.Mult):
            return a * b
        return a / b if b else None
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = eval_num(node.operand, consts, cls_scope, depth + 1)
        return -v if isinstance(node.op, ast.USub) and v is not None else v
    if isinstance(node, ast.Name):
        if node.id in consts.module:
            return consts.module[node.id]
        if cls_scope:
            return consts.class_attrs.get(cls_scope, {}).get(node.id)
        return None
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
        attr = node.attr
        if cls_scope:
            if attr in consts.self_attrs.get(cls_scope, {}):
                return consts.self_attrs[cls_scope][attr]
            return consts.class_attrs.get(cls_scope, {}).get(attr)
        return None
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
        idx = eval_num(node.slice, consts, cls_scope, depth + 1)
        name = node.value.id
        elems = consts.module_tuples.get(name)
        if elems is None and cls_scope:
            elems = consts.class_tuples.get(cls_scope, {}).get(name)
        if elems and idx is not None and 0 <= int(idx) < len(elems):
            return elems[int(idx)]
    return None


def tuple_of(node, consts, cls_scope):
    """Return list of numeric values if node resolves to a known constant tuple."""
    if isinstance(node, ast.Name):
        if node.id in consts.module_tuples:
            return consts.module_tuples[node.id]
        if cls_scope:
            return consts.class_tuples.get(cls_scope, {}).get(node.id)
    return None


def is_subprocessish(func, root_names, line_text):
    f = func or ""
    if "subprocess" in f or "Popen" in f:
        return True
    leaf = f.rsplit(".", 1)[-1]
    root = f.split(".")[0] if f else ""
    if leaf in {"communicate"}:
        return True
    if leaf in {"wait", "join"} and root in {"process", "proc", "popen", "child", "proc_obj"}:
        return True
    if root in {"subprocess"}:
        return True
    return False


def main():
    rows = []
    excluded_subprocess = 0
    files_scanned = 0
    stats = {"dynamic_timeout_kw": 0, "blocking_sleep_in_async": []}
    nonlocal_excluded = [0]
    excluded_dump = []

    for path, rel in iter_py_files():
        src = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        files_scanned += 1
        ScopeTagger().visit(tree)
        consts = ConstIndex(tree)
        imports_subprocess = "import subprocess" in src or "from subprocess" in src

        class Visitor(ast.NodeVisitor):
            def __init__(self):
                self.stack = []          # (kind, name, is_async) for FunctionDef
                self.while_depth = 0

            @property
            def cls_scope(self):
                for k, n, a in reversed(self.stack):
                    if k == "class":
                        return n
                return None

            @property
            def in_async(self):
                for k, n, a in reversed(self.stack):
                    if k == "func":
                        return a
                return False

            def visit_ClassDef(self, node):
                self.stack.append(("class", (self.cls_scope + "." if self.cls_scope else "") + node.name, False))
                self.generic_visit(node)
                self.stack.pop()

            def visit_FunctionDef(self, node):
                self.stack.append(("func", node.name, False))
                self.generic_visit(node)
                self.stack.pop()

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_AsyncFunctionDef(self, node):
                self.stack.append(("func", node.name, True))
                self.generic_visit(node)
                self.stack.pop()

            def visit_While(self, node):
                self.while_depth += 1
                self.generic_visit(node)
                self.while_depth -= 1

            def visit_Call(self, node):
                self.generic_visit(node)
                f = node.func
                name = dotted(f) or ""
                leaf = name.rsplit(".", 1)[-1] if name else ""
                line_text = src.splitlines()[node.lineno - 1].strip()[:160]
                kind = None
                value_s = None
                unit = "s"
                value_expr = ""

                # 1) sleeps
                if name.endswith("time.sleep") or (leaf == "sleep" and name.endswith("asyncio.sleep")):
                    arg = node.args[0] if node.args else None
                    if arg is None:
                        value_s, value_expr = None, ""
                    else:
                        value_s = eval_num(arg, consts, self.cls_scope)
                        value_expr = ast.unparse(arg)
                        tpl = tuple_of(arg.value if isinstance(arg, ast.Subscript) else arg, consts, self.cls_scope) \
                            if isinstance(arg, (ast.Subscript, ast.Name)) else None
                        if value_s is None and tpl:
                            value_expr = f"{value_expr} -> tuple({', '.join(str(t) for t in tpl)})"
                    if value_s == 0.0:
                        kind = "sleep-yield"
                    else:
                        kind = "sleep-fixed"
                    if imports_subprocess is None:
                        pass
                # 2) httpx.Timeout / aiohttp.ClientTimeout constructors
                elif name.endswith("httpx.Timeout") or name.endswith("aiohttp.ClientTimeout"):
                    kind = "timeout-net"
                    parts = []
                    for a in node.args:
                        v = numeric_value(a)
                        parts.append(str(v) if v is not None else ast.unparse(a))
                    for kw in node.keywords:
                        v = numeric_value(kw.value)
                        parts.append(f"{kw.arg}={v}" if v is not None else f"{kw.arg}={ast.unparse(kw.value)}")
                    value_expr = "; ".join(parts)
                    if node.args:
                        value_s = numeric_value(node.args[0])
                    else:
                        for kw in node.keywords:
                            if kw.arg == "total":
                                value_s = numeric_value(kw.value)
                                break
                # 3) PRAGMA busy_timeout
                elif leaf == "execute" and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str) and "busy_timeout" in node.args[0].value:
                    kind = "timeout-lock"
                    unit = "ms"
                    txt = node.args[0].value
                    digits = "".join(ch for ch in txt.split("=")[-1] if ch.isdigit())
                    value_s = float(digits) if digits else None
                    value_expr = txt.strip()[:80]
                # 4) generic timeout kwarg with literal value
                else:
                    for kw in node.keywords:
                        if kw.arg == "timeout":
                            v = eval_num(kw.value, consts, self.cls_scope)
                            if v is None and isinstance(kw.value, ast.Constant) and not isinstance(kw.value.value, (int, float)):
                                continue  # timeout=None / timeout="30s"
                            if v is None:
                                stats["dynamic_timeout_kw"] += 1
                                continue  # dynamic values recorded via sleep/Timeout paths only for now
                            value_s, value_expr = v, ast.unparse(kw.value)
                            if leaf == "connect" and name.startswith("sqlite3"):
                                kind = "timeout-lock"
                            else:
                                kind = "timeout-wait" if leaf in {"wait_for", "wait", "join", "result"} else "timeout-net"
                            if leaf == "sync_forever":
                                unit = "ms"
                            break
                    # 5) positional numeric timeout on .wait/.join/.result (Event.wait(0.25))
                    if kind is None and node.args and leaf in {"wait", "join", "result"}:
                        v = eval_num(node.args[0], consts, self.cls_scope)
                        if v is not None:
                            value_s, value_expr = v, ast.unparse(node.args[0])
                            kind = "timeout-wait"

                if kind is None:
                    return
                if kind in {"timeout-wait", "timeout-net", "timeout-lock"} and is_subprocessish(name, None, line_text):
                    nonlocal_excluded[0] += 1
                    excluded_dump.append(f"{rel}:{node.lineno}\t{kind}\t{line_text}")
                    return
                if kind == "sleep-fixed" and name.endswith("time.sleep") and self.in_async:
                    stats["blocking_sleep_in_async"].append(f"{rel}:{node.lineno}")

                surface, rule = "request", "rule:default->request"
                for prefix, sfc, lbl in SURFACE_RULES:
                    if rel.startswith(prefix) or rel == prefix:
                        surface, rule = sfc, lbl
                        break

                rows.append({
                    "path_line": f"{rel}:{node.lineno}",
                    "kind": kind,
                    "value_s": "" if value_s is None else (int(value_s) if float(value_s).is_integer() else value_s),
                    "unit": unit,
                    "value_expr": value_expr,
                    "in_while": self.while_depth > 0,
                    "in_async_fn": self.in_async,
                    "surface": surface,
                    "surface_rule": rule,
                    "call": line_text,
                    "config_suggestion": SUGGESTIONS[kind],
                })

        nonlocal_excluded = [0]
        v = Visitor()
        v.visit(tree)
        excluded_subprocess += nonlocal_excluded[0]
        nonlocal_excluded[0] = 0

    rows.sort(key=lambda r: (r["path_line"].split(":")[0], int(r["path_line"].split(":")[1])))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else
                                ["path_line", "kind", "value_s", "unit", "value_expr", "in_while", "in_async_fn", "surface", "surface_rule", "call", "config_suggestion"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"files_scanned={files_scanned} rows={len(rows)} excluded_subprocess_axis={excluded_subprocess} "
          f"dynamic_timeout_kw_skipped={stats['dynamic_timeout_kw']} "
          f"blocking_time_sleep_in_async={len(stats['blocking_sleep_in_async'])}")
    for item in stats["blocking_sleep_in_async"]:
        print(f"  blocking-sleep-in-async: {item}")
    import os
    if os.environ.get("SCANDUMP"):
        with open(os.environ["SCANDUMP"], "w", encoding="utf-8") as fh:
            fh.write("\n".join(excluded_dump) + "\n")
        print(f"excluded rows dumped to {os.environ['SCANDUMP']}")


if __name__ == "__main__":
    main()
