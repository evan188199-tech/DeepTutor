#!/usr/bin/env python3
"""AST scan for Python fire-and-forget async tasks / threads (read-only).

Targets (scope of AGEN-453):
  - asyncio.create_task / asyncio.ensure_future / <loop>.create_task calls
    whose result is not retained (bare expression, no add_done_callback,
    not appended to a tracking collection) -> exceptions silently lost,
    task collectible by GC, not cancellable.
  - threading.Thread(target=...) started as a bare ``Thread(...).start()``
    expression -> no reference kept, cannot join/cancel, thread exceptions
    only hit stderr.

Never writes to the source tree; emits a JSON report to --out.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

SCAN_ROOTS = ("deeptutor", "deeptutor_cli", "scripts")
EXCLUDE_PARTS = {"tests", "test", ".venv", "node_modules", "build", "dist"}

TASK_TAILS = {"create_task", "ensure_future"}
TRACK_METHODS = {"add", "append", "update", "setdefault", "add_done_callback"}


def dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute):
        base = dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def tail(name: str | None) -> str | None:
    return name.rsplit(".", 1)[-1] if name else None


def src_line(path: Path, lineno: int) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[lineno - 1].strip()
    except Exception:
        return ""


def scan_file(path: Path, root: Path) -> list[dict]:
    src = path.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src, filename=str(path))
    parent: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node

    def p(n):
        return parent.get(n)

    def gp(n):
        q = p(n)
        return p(q) if q is not None else None

    hits: list[dict] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = dotted(node.func)
        t = tail(name)

        if t in TASK_TAILS and (name.startswith("asyncio.") or t == "create_task"):
            hits.extend(
                check_task(node, path, root, parent, p, gp)
            )
        elif t == "Thread" and "threading" in (name or ""):
            hits.extend(check_thread(node, path, root, p, gp))

    return hits


def check_task(call, path, root, parent, p, gp) -> list[dict]:
    par = p(call)
    gpar = gp(call)
    detail = None
    status = None  # lost | local_only | tracked | awaited

    if isinstance(par, ast.Await):
        return []
    if isinstance(par, ast.Expr):
        status, detail = "lost", "裸表达式调用，返回的 Task 引用被丢弃"
    elif isinstance(par, ast.Attribute) and par.attr in TRACK_METHODS and isinstance(gpar, ast.Call):
        # asyncio.create_task(c).add_done_callback(cb) / append(...)
        status = "tracked"
        detail = f"链式 .{par.attr}(...) 登记/回调"
    elif isinstance(par, ast.Assign):
        names = {t.id for t in par.targets if isinstance(t, ast.Name)}
        if not names:
            status, detail = "lost", "赋值到非简单目标，引用不持久"
        else:
            registered = name_registered_later(tree_parent := None, parent_map=parent, names=names, after_line=par.lineno)
            # add_done_callback on the same name
            if registered:
                status, detail = "tracked", f"保存到 {', '.join(sorted(names))} 并已登记/回调"
            else:
                status, detail = "local_only", f"保存到局部变量 {', '.join(sorted(names))} 但从未登记/回调，函数返回后失联"
    else:
        status, detail = "lost", "结果作为子表达式使用后未保存（非 await）"

    if status == "awaited":
        return []

    return [
        mk_hit(
            path,
            root,
            call.lineno,
            kind="create_task/ensure_future",
            status=status,
            detail=detail,
        )
    ]


def name_registered_later(tree, parent_map, names, after_line) -> bool:
    for node in parent_map:
        if not isinstance(node, ast.Call):
            continue
        if getattr(node, "lineno", 0) <= after_line:
            continue
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr in TRACK_METHODS:
            for arg in node.args + [kw.value for kw in node.keywords]:
                if isinstance(arg, ast.Name) and arg.id in names:
                    return True
            # x.add_done_callback(...) where x is the saved name
            if isinstance(f.value, ast.Name) and f.value.id in names and f.attr == "add_done_callback":
                return True
    return False


def check_thread(call, path, root, p, gp) -> list[dict]:
    par = p(call)
    gpar = gp(call)
    # pattern A: Thread(...).start()  => call(Thread) -> Attribute(start) -> Call(start)
    if isinstance(par, ast.Attribute) and par.attr == "start" and isinstance(gpar, ast.Call):
        top = p(gpar)
        if isinstance(top, ast.Expr):
            detail = "Thread(...).start() 裸调用：线程引用即弃，无法 join，异常仅打 stderr"
            status = "lost"
        else:
            detail = "Thread(...).start() 作为子表达式：引用未保存"
            status = "lost"
        return [mk_hit(path, root, call.lineno, kind="threading.Thread", status=status, detail=detail)]
    # pattern B: t = Thread(...); t.start() -> reference kept at least locally
    return []  # constructed-but-started-elsewhere: not fire-and-forget by construction


def mk_hit(path: Path, root: Path, line: int, *, kind: str, status: str, detail: str) -> dict:
    try:
        rel = str(path.relative_to(root))
    except ValueError:
        rel = str(path)
    return {
        "rel": rel,
        "file": str(path),
        "line": line,
        "kind": kind,
        "status": status,
        "detail": detail,
        "source": src_line(path, line),
    }


def iter_py_files(root: Path):
    for sub in SCAN_ROOTS:
        base = root / sub
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            if set(p.parts) & EXCLUDE_PARTS:
                continue
            yield p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    entries: list[dict] = []
    files_scanned = 0
    parse_errors = []
    for path in sorted(iter_py_files(args.root)):
        try:
            entries.extend(scan_file(path, args.root))
            files_scanned += 1
        except SyntaxError as e:
            parse_errors.append({"file": str(path), "error": str(e)})

    report = {
        "root": str(args.root),
        "files_scanned": files_scanned,
        "parse_errors": parse_errors,
        "entries": entries,
    }
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"files={files_scanned} hits={len(entries)} parse_errors={len(parse_errors)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
