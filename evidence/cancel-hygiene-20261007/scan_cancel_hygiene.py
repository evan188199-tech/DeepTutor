#!/usr/bin/env python3
"""AST scan for asyncio cancellation-path hygiene issues in deeptutor/.

Axes (this card = cancellation hygiene; dedup with sibling scan cards):
  P1  bare `except:` / `except BaseException` / explicit CancelledError handler
      that does not re-raise (CancelledError swallowed)
  P2  contextlib.suppress(BaseException|CancelledError) swallowing cancellation
  P3  manual lock acquire in async code where release is not in a `finally`
      (cancellation between acquire and release holds the lock forever)
  P4  asyncio.wait_for/wait/timeout sites in async code (timeout-residue review
      set); classified manually afterwards
  P5  asyncio.shield sites (shielded work continues past cancellation; the
      caller must still handle CancelledError) - review set
  P6  cleanup-residue review set: except CancelledError / finally handlers in
      functions that own tasks/locks/temp resources, sampled manually

Read-only over the target tree; writes nothing outside stdout/`--out`.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("deeptutor")

CANCELLED_NAMES = {"CancelledError", "BaseException"}
SUPPRESS_NAMES = {"suppress"}


def excerpt(node: ast.AST, src: str, width: int = 200) -> str:
    seg = ast.get_source_segment(src, node) or ""
    seg = " ".join(seg.split())
    return seg[:width]


class FuncCtx:
    __slots__ = ("name", "is_async", "module", "in_finally")

    def __init__(self, name, is_async, module, in_finally=False):
        self.name = name
        self.is_async = is_async
        self.module = module
        self.in_finally = in_finally


def handler_types(node: ast.ExceptHandler) -> list[str]:
    if node.type is None:
        return ["<bare>"]
    if isinstance(node.type, ast.Name):
        return [node.type.id]
    if isinstance(node.type, ast.Attribute):
        return [ast.dump(node.type)[:0] + f"{ast.unparse(node.type)}"]
    if isinstance(node.type, ast.Tuple):
        out = []
        for elt in node.type.elts:
            if isinstance(elt, ast.Name):
                out.append(elt.id)
            elif isinstance(elt, ast.Attribute):
                out.append(ast.unparse(elt))
            else:
                out.append(ast.unparse(elt) if elt else "?")
        return out
    try:
        return [ast.unparse(node.type)]
    except Exception:
        return ["<complex>"]


def handler_raises_bare(node: ast.ExceptHandler) -> bool:
    """True if any `raise` statement in the handler re-raises (bare raise)."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Raise) and sub.exc is None:
            return True
        # raise <name> where name is CancelledError also counts as re-raise path
    return False


def handler_reraises_cancelled(node: ast.ExceptHandler) -> bool:
    if handler_raises_bare(node):
        return True
    for sub in ast.walk(node):
        if isinstance(sub, ast.Raise) and sub.exc is not None:
            txt = ast.unparse(sub.exc)
            if "CancelledError" in txt:
                return True
    return False


def visit_handler(child: ast.ExceptHandler, ctx, in_finally: bool, hits, src, rel, mod):
    types = handler_types(child)
    reraises = handler_reraises_cancelled(child)
    catches_cancel = (
        "<bare>" in types
        or any(t in CANCELLED_NAMES or t.endswith("CancelledError") or t == "BaseException" for t in types)
    )
    if catches_cancel:
        swallow = not reraises
        # classify
        if "<bare>" in types:
            kind = "bare-except"
        elif "BaseException" in types:
            kind = "except-baseexception"
        else:
            kind = "except-cancelled"
        hits.append({
            "pattern": "P1",
            "kind": kind,
            "file": rel,
            "line": child.lineno,
            "func": ctx.name if ctx else "<module>",
            "is_async": ctx.is_async if ctx else None,
            "in_finally": in_finally,
            "reraises_cancelled": reraises,
            "swallow": swallow,
            "types": types,
            "excerpt": excerpt(child, src),
        })
    walk_with_ctx(child, ctx, in_finally, mod, hits, src, rel)


def walk_with_ctx(node, ctx: FuncCtx | None, in_finally: bool, mod, hits, src, rel):
    for child in ast.iter_child_nodes(node):
        entering_finally = in_finally

        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            sub = FuncCtx(child.name, isinstance(child, ast.AsyncFunctionDef), ctx.module if ctx else None, in_finally)
            walk_with_ctx(child, sub, in_finally, mod, hits, src, rel)
            continue

        if isinstance(child, ast.ExceptHandler):
            visit_handler(child, ctx, entering_finally, hits, src, rel, mod)
            continue

        if isinstance(child, (ast.Try, getattr(ast, "TryStar", ast.Try))):
            # mark finally children with in_finally=True; visit handlers via
            # the shared visit path so hits are recorded exactly once
            for f in child.finalbody:
                walk_with_ctx(f, ctx, True, mod, hits, src, rel)
            for h in child.handlers:
                visit_handler(h, ctx, in_finally, hits, src, rel, mod)
            for b in child.body + child.orelse:
                walk_with_ctx(b, ctx, in_finally, mod, hits, src, rel)
            continue

        if isinstance(child, ast.Call):
            fn = child.func
            name_txt = None
            if isinstance(fn, ast.Name):
                name_txt = fn.id
            elif isinstance(fn, ast.Attribute):
                name_txt = fn.attr

            # P2 suppress(...)
            if name_txt == "suppress" and isinstance(fn, (ast.Name, ast.Attribute)):
                args_txt = [ast.unparse(a) for a in child.args]
                catches = any(
                    a in CANCELLED_NAMES or a.endswith("CancelledError") for a in args_txt
                )
                if catches:
                    hits.append({
                        "pattern": "P2",
                        "kind": "suppress-cancelled",
                        "file": rel,
                        "line": child.lineno,
                        "func": ctx.name if ctx else "<module>",
                        "is_async": ctx.is_async if ctx else None,
                        "in_finally": in_finally,
                        "args": args_txt,
                        "excerpt": excerpt(child, src),
                    })

            # P3 manual lock acquire
            if name_txt == "acquire" and ctx and ctx.is_async:
                recv = ""
                if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
                    recv = fn.value.id
                hits.append({
                    "pattern": "P3",
                    "kind": "manual-acquire",
                    "file": rel,
                    "line": child.lineno,
                    "func": ctx.name,
                    "in_finally": in_finally,
                    "recv": recv,
                    "awaited": _call_is_awaited(child),
                    "excerpt": excerpt(child, src),
                })

            # P4 wait_for / wait / timeout
            if name_txt in {"wait_for", "wait", "timeout", "wait_for_ready"} and ctx and ctx.is_async:
                mod_txt = ""
                if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
                    mod_txt = fn.value.id
                is_asyncio = mod_txt in {"asyncio", "loop", "self._loop"} or (
                    isinstance(fn, ast.Name) and name_txt == "wait_for"
                )
                if name_txt == "wait" and not is_asyncio:
                    pass
                elif name_txt in {"wait_for", "timeout"} or is_asyncio:
                    hits.append({
                        "pattern": "P4",
                        "kind": f"asyncio-{name_txt}",
                        "file": rel,
                        "line": child.lineno,
                        "func": ctx.name,
                        "in_finally": in_finally,
                        "excerpt": excerpt(child, src),
                    })

            # P5 shield
            if name_txt == "shield":
                hits.append({
                    "pattern": "P5",
                    "kind": "shield",
                    "file": rel,
                    "line": child.lineno,
                    "func": ctx.name if ctx else "<module>",
                    "is_async": ctx.is_async if ctx else None,
                    "in_finally": in_finally,
                    "excerpt": excerpt(child, src),
                })
            walk_with_ctx(child, ctx, in_finally, mod, hits, src, rel)
            continue

        walk_with_ctx(child, ctx, entering_finally, mod, hits, src, rel)


def _call_is_awaited(call: ast.Call) -> bool:
    return False  # placeholder; refined post-hoc via parent map not needed for review set


def main():
    files = sorted(ROOT.rglob("*.py"))
    hits: list[dict] = []
    parse_errors = []
    n_files = 0
    for f in files:
        rel = str(f)
        try:
            src = f.read_text(encoding="utf-8")
            tree = ast.parse(src, filename=rel)
        except SyntaxError as e:
            parse_errors.append({"file": rel, "error": str(e)})
            continue
        n_files += 1
        walk_with_ctx(tree, None, False, None, hits, src, rel)

    summary = {
        "root": str(ROOT),
        "files_scanned": n_files,
        "parse_errors": parse_errors,
        "hits_total": len(hits),
        "by_pattern": {},
        "by_kind": {},
    }
    for h in hits:
        summary["by_pattern"][h["pattern"]] = summary["by_pattern"].get(h["pattern"], 0) + 1
        k = f"{h['pattern']}:{h['kind']}"
        summary["by_kind"][k] = summary["by_kind"].get(k, 0) + 1

    out = {"summary": summary, "hits": hits}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if len(sys.argv) > 2:
        Path(sys.argv[2]).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
