"""Pass 2: for each with/async-with on a known lock, report body contents (awaits, I/O calls, sleeps, loops)."""
import ast
import os
import sys
import json

ROOT = sys.argv[1] if len(sys.argv) > 1 else "deeptutor"

LOCK_LEAVES = {"Lock", "RLock", "Semaphore", "BoundedSemaphore", "Condition", "Event", "Barrier"}
IO_HINTS = {
    "urlopen", "urllib", "requests", "httpx", "aiohttp", "embed", "embed_contents",
    "chat", "invoke", "complete", "generate", "post", "stream", "send",
    "open", "dump", "load", "write_text", "read_text", "write_bytes", "read_bytes",
    "unlink", "mkdir", "rmtree", "copy", "rename", "replace", "remove",
    "run", "Popen", "check_output", "check_call", "save", "flush", "commit", "execute",
    "acquire", "connect", "cursor", "fetchall", "fetchone",
}
SPAWN = {"run_in_executor", "to_thread", "create_task", "ensure_future", "gather", "Thread", "start"}


def dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


class LockRegionVisitor(ast.NodeVisitor):
    """Find with/async with statements whose context expr mentions a lock-ish name."""

    def __init__(self):
        self.lock_regions = []  # dicts

    @staticmethod
    def _lockish(expr):
        if expr is None:
            return None
        if isinstance(expr, ast.Call):
            name = dotted(expr.func) or ""
            leaf = name.split(".")[-1]
            # direct factory call in the with header, e.g. with _locks.setdefault(..., threading.Lock())
            if leaf in LOCK_LEAVES:
                base = dotted(expr.func).split(".")[0] if dotted(expr.func) else ""
                return f"{name} (inline factory)"
            return LockRegionVisitor._lockish(expr.func)
        d = dotted(expr)
        if d and any(p.lower().endswith("lock") or p.lower() in ("sem", "semaphore", "slots", "guard") for p in d.split(".")):
            return d
        return None

    def _walk_body(self, body, depth=0):
        out = []
        for n in body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            for sub in ast.walk(n):
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                    continue
                if isinstance(sub, ast.Call):
                    name = dotted(sub.func) or ""
                    out.append(("call", sub.lineno, name))
                if isinstance(sub, ast.Await) and isinstance(sub.value, ast.Call):
                    out.append(("await", sub.lineno, dotted(sub.value.func) or "<expr>"))
            if isinstance(n, (ast.For, ast.AsyncFor, ast.While)):
                out.append(("loop-start", n.lineno, type(n).__name__))
        return out

    def visit_With(self, node):
        self._visit_with(node)
        self.generic_visit(node)

    visit_AsyncWith = visit_With

    def _visit_with(self, node):
        for item in node.items:
            lk = self._lockish(item.context_expr)
            if lk:
                calls = self._walk_body(node.body)
                sleeps = [c for c in calls if c[2].split(".")[-1] == "sleep"]
                spawns = [c for c in calls if c[2].split(".")[-1] in SPAWN]
                io = [c for c in calls if c[2].split(".")[-1] in IO_HINTS]
                awaits = [c for c in calls if c[0] == "await"]
                calls_private = [c for c in calls if c[0] == "call" and not c[0] == "await" and
                                 (c[2].split(".")[-1].startswith("_") or c[2].startswith("self._"))]
                self.lock_regions.append({
                    "line": node.lineno,
                    "lock": lk,
                    "is_async": isinstance(node, ast.AsyncWith),
                    "end_line": max([getattr(n, "lineno", node.lineno) for n in ast.walk(node)] + [node.lineno]),
                    "sleeps": sleeps,
                    "spawns": spawns,
                    "io": io,
                    "awaits": awaits,
                    "calls_private": calls_private,
                    "ncalls": len(calls),
                })


def main():
    report = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", "tests", "node_modules")]
        for f in sorted(filenames):
            if not f.endswith(".py"):
                continue
            full = os.path.join(dirpath, f)
            rel = os.path.relpath(full, ".")
            try:
                tree = ast.parse(open(full, encoding="utf-8", errors="replace").read())
            except SyntaxError:
                continue
            v = LockRegionVisitor()
            v.visit(tree)
            for r in v.lock_regions:
                r["file"] = rel
                report.append(r)
    # report every region with awaits, private-method calls, sleeps, or spawns
    interesting = [r for r in report if r["sleeps"] or r["spawns"] or r["io"] or r["calls_private"] or r["awaits"]]
    print("=== REGIONS WITH AWAIT / SLEEP / SPAWN / IO / PRIVATE-CALL INSIDE LOCK ===")
    for r in sorted(interesting, key=lambda x: (x["file"], x["line"])):
        print(json.dumps(r))
    print(f"=== TOTAL lock regions: {len(report)}, interesting: {len(interesting)} ===")
    with open("evidence/lock-usage-20261005/lock-regions.json", "w") as fh:
        json.dump(report, fh, indent=1)


if __name__ == "__main__":
    main()
