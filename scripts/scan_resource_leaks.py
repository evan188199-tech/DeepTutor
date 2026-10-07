#!/usr/bin/env python3
"""Static resource-leak inventory scanner (pure stdlib, read-only, AST-based).

Scope (AGEN-964, axis: "resources not released"):
  - aiohttp ClientSession / httpx AsyncClient|Client created but never closed
    (local / attribute / module scope)
  - sqlite3.connect / aiosqlite.connect connections never closed
  - file handles from open()/Path.open()/zipfile.ZipFile without with/close
  - subprocess.Popen / asyncio.create_subprocess_exec|shell never reaped
    (no wait/communicate/poll/kill/terminate) or dropped without assignment
  - ThreadPoolExecutor / ProcessPoolExecutor never shut down

Explicit non-goals (dedup with sibling scan cards):
  - asyncio task lifecycle (scan-async-tasks axis)
  - subprocess timeout handling (scan-subprocess-timeouts axis)
  - tempfile cleanup hygiene (scan-tempfile-hygiene axis)

Determinism: the scan is fully deterministic; an identical tree plus the same
--seed produce identical findings (the seed only drives sample selection).

Usage:
  python scripts/scan_resource_leaks.py --root . --out evidence --seed 20261006
"""

from __future__ import annotations

import argparse
import ast
import json
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

SKIP_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", "node_modules",
    ".venv", "venv", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "dist", "build", ".tox",
}

MANAGED_VERBS = {
    "file": {"close", "__enter__", "__exit__"},
    "session": {"close", "aclose", "__aenter__", "__aexit__", "__enter__", "__exit__"},
    "httpx": {"close", "aclose", "__aenter__", "__aexit__", "__enter__", "__exit__"},
    "dbconn": {"close", "__enter__", "__exit__"},
    "popen": {"wait", "communicate", "poll", "kill", "terminate", "send_signal"},
    "executor": {"shutdown"},
}

CTOR_LABEL = {
    "session": "aiohttp ClientSession",
    "httpx": "httpx AsyncClient/Client",
    "dbconn": "sqlite3/aiosqlite 连接",
    "file": "文件句柄",
    "popen": "子进程",
    "executor": "executor",
}

CLIENT_LOCAL_RULES = {"session": "R1", "httpx": "R1", "dbconn": "R1"}

RULE_META = {
    "R1": {
        "name": "client-local-no-close",
        "severity": "medium",
        "fix": "用 `async with <client>(...) as c:` 包住使用区间，或在 finally 中 `await c.close()`（aiohttp/httpx/aiosqlite）。",
    },
    "R2": {
        "name": "client-attr-no-close",
        "severity": "high",
        "fix": "为宿主类补 `async def aclose()` 并在其中 `await self.<attr>.close()`，接入应用关停路径。",
    },
    "R3": {
        "name": "file-handle-local-no-close",
        "severity": "medium",
        "fix": "改为 `with open(...) as f:`，保证异常路径也释放句柄。",
    },
    "R4": {
        "name": "file-handle-transient-no-with",
        "severity": "low",
        "fix": "一次性 read/write 也建议用 with 包裹，避免依赖 CPython 引用计数即时回收。",
    },
    "R5": {
        "name": "file-handle-attr-no-close",
        "severity": "high",
        "fix": "为宿主类补 `close()` 或上下文管理器协议，确保 `self.<attr>.close()` 被调用。",
    },
    "R6": {
        "name": "subprocess-not-reaped",
        "severity": "medium",
        "fix": "在 scope 末尾调用 `p.wait()`（或 communicate/poll），避免僵尸进程累积。",
    },
    "R7": {
        "name": "subprocess-handle-dropped",
        "severity": "high",
        "fix": "保存 Popen 返回值并在合适时机 wait/terminate；长期驻留进程登记到管理器统一回收。",
    },
    "R8": {
        "name": "executor-no-shutdown",
        "severity": "high",
        "fix": "用 `with ThreadPoolExecutor(...) as ex:` 或显式 `ex.shutdown(wait=True)`；模块级单例需提供关停钩子。",
    },
    "R9": {
        "name": "ownership-transferred-verify",
        "severity": "low",
        "fix": "资源所有权被转移（return/存储到其他对象），请确认接收方负责 close/wait/shutdown。",
    },
}


def find_py_files(root: Path) -> list[Path]:
    files = []
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        files.append(p)
    return files


def _call_name(node: ast.AST) -> tuple[str, ...] | None:
    parts: list[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return tuple(reversed(parts))
    return None


def _resource_kind(call: ast.Call, imports: dict[str, str]) -> str | None:
    func = call.func
    if isinstance(func, ast.Name):
        if func.id == "open":
            return "file"
        head, last = func.id, func.id
        nparts = 1
    elif isinstance(func, ast.Attribute):
        base = func.value
        if func.attr == "open":
            if isinstance(base, ast.Call):
                return "file"  # e.g. Path(...).open()
            if isinstance(base, ast.Name):
                b = base.id.lower()
                if (
                    "path" in b
                    or b in ("f", "fp", "fh", "file", "gzip", "tarfile", "bz2", "lzma", "codecs")
                    or b.endswith("_file")
                    or b.endswith("_path")
                ):
                    return "file"
            return None
        name = _call_name(func)
        if name is None:
            return None
        head, last, nparts = name[0], name[-1], len(name)
    else:
        return None

    mod = imports.get(head)
    if mod == "aiohttp" and last == "ClientSession" and nparts <= 2:
        return "session"
    if mod == "httpx" and last in ("AsyncClient", "Client") and nparts <= 2:
        return "httpx"
    if mod in ("sqlite3", "aiosqlite") and last == "connect" and nparts <= 2:
        return "dbconn"
    if mod == "zipfile" and last == "ZipFile" and nparts <= 2:
        return "file"
    if mod == "subprocess" and last == "Popen" and nparts <= 2:
        return "popen"
    if (
        mod == "asyncio"
        and last in ("create_subprocess_exec", "create_subprocess_shell")
        and nparts <= 2
    ):
        return "async_popen"
    if (
        mod == "concurrent.futures"
        and last in ("ThreadPoolExecutor", "ProcessPoolExecutor")
        and nparts <= 2
    ):
        return "executor"
    return None


class ImportCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.modules: dict[str, str] = {}

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.modules[alias.asname or alias.name.split(".")[0]] = alias.name.split(".")[0]

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module is None:
            return
        for alias in node.names:
            self.modules[alias.asname or alias.name] = node.module


def _normalized(kind: str) -> str:
    return "popen" if kind == "async_popen" else kind


def _snippet(line: str) -> str:
    return " ".join(line.split())[:160]


class ScopeAnalyzer:
    def __init__(self, rel_path: str, source: str, tree: ast.Module, lines: list[str]):
        self.rel_path = rel_path
        self.tree = tree
        self.lines = lines
        self.findings: list[dict] = []
        collector = ImportCollector()
        collector.visit(tree)
        self.imports = collector.modules

    def emit(self, rule: str, node: ast.AST, detail: str, symbol: str, scope: str,
             severity: str | None = None) -> None:
        meta = RULE_META[rule]
        lineno = getattr(node, "lineno", 0)
        self.findings.append(
            {
                "rule": rule,
                "rule_name": meta["name"],
                "severity": severity or meta["severity"],
                "path": self.rel_path,
                "line": lineno,
                "col": getattr(node, "col_offset", 0) + 1,
                "snippet": _snippet(self.lines[lineno - 1]) if 0 < lineno <= len(self.lines) else "",
                "detail": detail,
                "suggestion": meta["fix"],
                "scope": scope,
                "symbol": symbol,
            }
        )

    # ---------- helpers ----------

    @staticmethod
    def _verbs_used(var: str, verbs: set[str], subtree: ast.AST) -> set[str]:
        used: set[str] = set()
        for node in ast.walk(subtree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in verbs:
                    val = node.func.value
                    if isinstance(val, ast.Name) and val.id == var:
                        used.add(node.func.attr)
                    elif isinstance(val, ast.Attribute) and val.attr == var:
                        used.add(node.func.attr)
        return used

    def _verbs_used_for_attr(
        self, cls: ast.ClassDef, var: str, verbs: set[str]
    ) -> set[str]:
        """Verb usage within this class, or module code outside any other class.

        Attribute names are class-scoped: checking the whole module tree would
        let an unrelated class's `other._x.close()` mask this class's leak.
        Local aliases (`c = self._x` ... `c.close()`) are followed too.
        """
        used = self._verbs_used(var, verbs, cls)
        if used:
            return used
        for alias in self._alias_names(cls, var):
            used |= self._verbs_used(alias, verbs, cls)
        if used:
            return used
        outside = ast.Module(body=[], type_ignores=[])
        outside.body = [
            s
            for s in self.tree.body
            if not (isinstance(s, ast.ClassDef) and s is not cls)
        ]
        return self._verbs_used(var, verbs, outside)

    @staticmethod
    def _alias_names(cls: ast.ClassDef, var: str) -> set[str]:
        """Local names bound to `self.<var>` (or `<something>.<var>`) in cls."""
        aliases: set[str] = set()
        for node in ast.walk(cls):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Attribute):
                if node.value.attr == var:
                    for tgt in node.targets:
                        if isinstance(tgt, ast.Name):
                            aliases.add(tgt.id)
        return aliases

    @staticmethod
    def _with_var_names(subtree: ast.AST) -> set[str]:
        names: set[str] = set()
        for node in ast.walk(subtree):
            if isinstance(node, (ast.With, ast.AsyncWith)):
                for item in node.items:
                    ctx = item.context_expr
                    if isinstance(ctx, ast.Name):
                        names.add(ctx.id)
                    elif isinstance(ctx, ast.Attribute):
                        names.add(ctx.attr)
        return names

    @staticmethod
    def _returned_names(subtree: ast.AST) -> set[str]:
        names: set[str] = set()
        for node in ast.walk(subtree):
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Name):
                names.add(node.value.id)
        return names

    @staticmethod
    def _stored_into_object(var: str, subtree: ast.AST) -> bool:
        """var assigned as kwarg value, attr target, or subscript value."""
        for node in ast.walk(subtree):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if isinstance(kw.value, ast.Name) and kw.value.id == var:
                        return True
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Name):
                if node.value.id != var:
                    continue
                for tgt in node.targets:
                    if isinstance(tgt, (ast.Attribute, ast.Subscript)):
                        return True
        return False

    @staticmethod
    def _target_names(tgt: ast.AST) -> list[str]:
        if isinstance(tgt, ast.Name):
            return [tgt.id]
        if isinstance(tgt, ast.Tuple):
            out: list[str] = []
            for elt in tgt.elts:
                out.extend(ScopeAnalyzer._target_names(elt))
            return out
        if isinstance(tgt, ast.Attribute):
            return [tgt.attr]
        return []

    def _ctor_calls_in_value(self, value: ast.AST) -> list[tuple[ast.Call, str, bool]]:
        """Resource ctor calls inside an assignment value (BoolOp/IfExp/etc).

        Walks the value expression but does NOT descend into Call arguments
        (so `x = foo(httpx.AsyncClient())` is not treated as binding the client)
        nor into Lambda bodies (factory-held resources are untraceable).
        The bool marks calls nested inside a comprehension (element resources).
        """
        out: list[tuple[ast.Call, str, bool]] = []
        stack = [(value, False)]
        while stack:
            node, in_comp = stack.pop()
            if isinstance(node, ast.Lambda):
                continue
            if isinstance(node, ast.Call):
                kind = _resource_kind(node, self.imports)
                if kind:
                    out.append((node, kind, in_comp))
                continue  # do not descend into call args
            child_comp = in_comp or isinstance(
                node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
            )
            for child in ast.iter_child_nodes(node):
                stack.append((child, child_comp))
        return out

    def _assignments_in(
        self, stmts: list[ast.AST], attrs_only: bool = False
    ) -> list[tuple[str, ast.Call, str, bool]]:
        """Yield (var, ctor_call, kind, in_comprehension) for resource bindings."""
        out: list[tuple[str, ast.Call, str, bool]] = []
        for st in stmts:
            targets: list[ast.AST] = []
            if isinstance(st, ast.Assign):
                targets = list(st.targets)
            elif isinstance(st, ast.AnnAssign) and st.value is not None:
                targets = [st.target]
            value = getattr(st, "value", None)
            if value is None or not targets:
                continue
            for call, kind, in_comp in self._ctor_calls_in_value(value):
                for tgt in targets:
                    if attrs_only:
                        if not isinstance(tgt, ast.Attribute):
                            continue
                    elif isinstance(tgt, ast.Attribute):
                        continue  # attribute bindings belong to the class pass
                    for name in self._target_names(tgt):
                        out.append((name, call, kind, in_comp))
        return out

    @staticmethod
    def _direct_stmts(func: ast.AST) -> list[ast.AST]:
        """Statements in this function's control flow, excluding nested defs/classes."""
        stmts: list[ast.AST] = []

        def walk(body: list[ast.stmt]) -> None:
            for st in body:
                if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                stmts.append(st)
                for field in ("body", "orelse", "finalbody"):
                    sub = getattr(st, field, None)
                    if isinstance(sub, list):
                        walk(sub)

        walk(func.body)
        return stmts

    # ---------- passes ----------

    @staticmethod
    def _passed_positionally(var: str, subtree: ast.AST) -> bool:
        """var given as a positional arg of another call (e.g. reap helpers)."""
        for node in ast.walk(subtree):
            if isinstance(node, ast.Call):
                for arg in node.args:
                    if isinstance(arg, ast.Name) and arg.id == var:
                        return True
        return False

    def analyze(self) -> list[dict]:
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._analyze_function(node)
        self._analyze_module_scope()
        self._analyze_class_scope()
        return self.findings

    def _analyze_function(self, func: ast.AST) -> None:
        fname = func.name
        stmts = self._direct_stmts(func)
        bindings = self._assignments_in(stmts)

        with_ctor_calls: set[int] = set()
        for node in ast.walk(func):
            if isinstance(node, (ast.With, ast.AsyncWith)):
                for item in node.items:
                    if isinstance(item.context_expr, ast.Call):
                        with_ctor_calls.add(id(item.context_expr))

        for var, call, kind, in_comp in bindings:
            if id(call) in with_ctor_calls:
                continue
            nkind = _normalized(kind)
            verbs = MANAGED_VERBS[nkind]
            if self._verbs_used(var, verbs, func):
                continue
            if var in self._with_var_names(func):
                continue
            if in_comp:
                self.emit(
                    "R9", call,
                    f"{CTOR_LABEL[nkind]} 在 `{fname}` 的推导式/集合字面量内创建并整体绑定到 `{var}`，"
                    "请确认每个元素都被 close/wait/shutdown 回收。",
                    var, f"func:{fname}", severity="low",
                )
                continue
            if var in self._returned_names(func):
                if nkind == "file":
                    continue  # factory pattern: caller manages
                self.emit(
                    "R9", call,
                    f"{nkind} 对象 `{var}` 在函数 `{fname}` 中被 return，所有权转移，需确认调用方释放。",
                    var, f"func:{fname}",
                )
                continue
            if self._stored_into_object(var, func):
                if nkind in ("popen", "async_popen", "executor", "session", "httpx", "dbconn"):
                    self.emit(
                        "R9", call,
                        f"{CTOR_LABEL[nkind]} 对象 `{var}` 在函数 `{fname}` 中被存储/传参给其他对象，所有权转移，需确认接收方释放。",
                        var, f"func:{fname}",
                    )
                continue
            if nkind in ("popen", "async_popen", "executor") and self._passed_positionally(var, func):
                self.emit(
                    "R9", call,
                    f"{CTOR_LABEL[nkind]} 对象 `{var}` 在 `{fname}` 中被作为位置参数传入其他函数"
                    "（通常是回收/托管 helper），请确认接收方负责 wait/shutdown。",
                    var, f"func:{fname}",
                )
                continue
            rule = CLIENT_LOCAL_RULES.get(nkind) or {
                "file": "R3", "popen": "R6", "async_popen": "R6", "executor": "R8"
            }[nkind]
            detail = {
                "file": f"文件句柄 `{var}` 由 open() 创建，函数 `{fname}` 内未见 close()/with 管理。",
                "popen": f"子进程 `{var}` 在 `{fname}` 内未见 wait()/communicate()/poll() 等回收调用。",
                "executor": f"executor `{var}` 在 `{fname}` 内未见 shutdown()/with 管理。",
            }.get(
                nkind,
                f"{CTOR_LABEL[nkind]} `{var}` 在 `{fname}` 内未见 close()/aclose() 或 with/async with 管理。",
            )
            self.emit(rule, call, detail, var, f"func:{fname}")

        # unassigned direct ctor calls (handle dropped / transient).
        # Calls consumed by ANY assignment (name or attribute target) are owned
        # by the binding passes, not here.
        assigned_call_ids = {id(c) for _, c, _, _ in bindings} | {
            id(c)
            for _, c, _, _ in self._assignments_in(self._direct_stmts(func), attrs_only=True)
        }
        arg_call_ids: set[int] = set()
        for node in ast.walk(func):
            if isinstance(node, ast.Call):
                for arg in node.args:
                    if isinstance(arg, ast.Call):
                        arg_call_ids.add(id(arg))
                for kw in node.keywords:
                    if isinstance(kw.value, ast.Call):
                        arg_call_ids.add(id(kw.value))
        return_call_ids = {
            id(n.value)
            for n in ast.walk(func)
            if isinstance(n, ast.Return) and isinstance(n.value, ast.Call)
        }
        lambda_call_ids: set[int] = set()
        for n in ast.walk(func):
            if isinstance(n, ast.Lambda):
                for sub in ast.walk(n.body):
                    if isinstance(sub, ast.Call):
                        lambda_call_ids.add(id(sub))

        for node in ast.walk(func):
            if not isinstance(node, ast.Call) or id(node) in with_ctor_calls:
                continue
            kind = _resource_kind(node, self.imports)
            if not kind:
                continue
            if id(node) in assigned_call_ids:
                continue
            if id(node) in return_call_ids or id(node) in lambda_call_ids:
                # factory shape: ownership moves to the call site of the
                # factory; still worth a low-severity "verify caller" note
                # for long-lived resources, but not a leak verdict.
                if kind != "file":
                    where = "return" if id(node) in return_call_ids else "lambda 工厂"
                    self.emit(
                        "R9", node,
                        f"{CTOR_LABEL[kind]} 在 `{fname}` 中经 {where} 转移所有权，请确认调用方负责 close/wait/shutdown。",
                        "<factory>", f"func:{fname}",
                    )
                continue
            nkind = _normalized(kind)
            if nkind == "file":
                self.emit(
                    "R4", node,
                    f"open() 返回的句柄未绑定变量且不经 with 管理（函数 `{fname}`），依赖即时 GC 关闭。",
                    "<expr>", f"func:{fname}",
                )
            elif kind in ("popen", "async_popen"):
                if id(node) in arg_call_ids:
                    continue
                self.emit(
                    "R7", node,
                    f"子进程句柄未保存（函数 `{fname}`）：返回值被丢弃，之后无法 wait/terminate。",
                    "<dropped>", f"func:{fname}",
                )
            elif kind in ("session", "httpx", "dbconn"):
                if id(node) in arg_call_ids:
                    continue
                self.emit(
                    "R2", node,
                    f"{CTOR_LABEL[kind]} 实例未被保存或管理（函数 `{fname}`），创建后即失联。",
                    "<dropped>", f"func:{fname}",
                )

    def _analyze_module_scope(self) -> None:
        stmts = [
            s for s in self.tree.body
            if not isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ]
        for var, call, kind, _in_comp in self._assignments_in(stmts):
            nkind = _normalized(kind)
            if nkind == "file":
                continue  # module-level file handles are rare; low signal
            verbs = MANAGED_VERBS[nkind]
            if self._verbs_used(var, verbs, self.tree) or var in self._with_var_names(self.tree):
                continue
            rule = {"session": "R2", "httpx": "R2", "dbconn": "R2",
                    "popen": "R6", "async_popen": "R6", "executor": "R8"}[nkind]
            self.emit(
                rule, call,
                f"模块级 {CTOR_LABEL[nkind]} `{var}` 未在模块内见到 close/wait/shutdown 管理路径。",
                var, "module",
                severity="medium" if rule == "R8" else None,
            )

    def _analyze_class_scope(self) -> None:
        for cls in (n for n in ast.walk(self.tree) if isinstance(n, ast.ClassDef)):
            for method in (m for m in cls.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))):
                for var, call, kind, _in_comp in self._assignments_in(self._direct_stmts(method), attrs_only=True):
                    nkind = _normalized(kind)
                    rule = {"session": "R2", "httpx": "R2", "dbconn": "R2",
                            "popen": "R6", "async_popen": "R6", "executor": "R8", "file": "R5"}[nkind]
                    verbs = MANAGED_VERBS[nkind]
                    if self._verbs_used_for_attr(cls, var, verbs) or var in self._with_var_names(self.tree):
                        continue
                    self.emit(
                        rule, call,
                        f"类 `{cls.name}` 属性 `{var}`（{CTOR_LABEL[nkind]}）在整个模块内未见 close/wait/shutdown 管理路径。",
                        var, f"class:{cls.name}",
                    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Static resource-leak inventory scanner")
    parser.add_argument("--root", default=".", help="repo root to scan")
    parser.add_argument("--out", default="evidence", help="output dir (relative to root)")
    parser.add_argument("--seed", type=int, default=20261006, help="deterministic sample seed")
    parser.add_argument("--sample-size", type=int, default=6)
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    files = find_py_files(root)
    all_findings: list[dict] = []
    skipped: list[dict] = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            skipped.append({"path": rel, "reason": f"syntax error: {exc.msg}"})
            continue
        lines = source.splitlines()
        all_findings.extend(ScopeAnalyzer(rel, source, tree, lines).analyze())

    seen: set = set()
    unique: list[dict] = []
    for f in all_findings:
        key = (f["path"], f["line"], f["col"], f["rule"], f["symbol"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(f)
    unique.sort(key=lambda f: (f["path"], f["line"], f["col"], f["rule"], f["symbol"]))
    for i, f in enumerate(unique, 1):
        f["id"] = f"RL-{i:04d}"

    severity_counts = Counter(f["severity"] for f in unique)
    rule_counts = Counter(f["rule_name"] for f in unique)

    pool = [f for f in unique if f["severity"] in ("high", "medium")]
    if len(pool) < args.sample_size:
        pool = unique
    rng = random.Random(args.seed)
    sample = rng.sample(pool, min(args.sample_size, len(pool))) if pool else []

    outdir = root / args.out
    outdir.mkdir(parents=True, exist_ok=True)
    findings_path = outdir / "resource-leaks-findings.json"
    findings_path.write_text(
        json.dumps(
            {
                "meta": {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "root": str(root),
                    "seed": args.seed,
                    "files_scanned": len(files),
                    "files_skipped": skipped,
                    "total_findings": len(unique),
                    "severity": dict(severity_counts),
                    "by_rule": dict(rule_counts),
                    "manual_sample_ids": sorted(f["id"] for f in sample),
                },
                "findings": unique,
            },
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "files_scanned": len(files),
                "skipped": len(skipped),
                "total_findings": len(unique),
                "severity": dict(severity_counts),
                "by_rule": dict(rule_counts),
                "findings_json": str(findings_path),
                "sample_ids": sorted(f["id"] for f in sample),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
