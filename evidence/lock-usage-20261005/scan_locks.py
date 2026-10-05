"""AST scanner: lock usage + in-lock I/O detection (read-only analysis tool)."""
import ast
import os
import json
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else "deeptutor"

LOCK_FACTORIES = {
    "Lock", "RLock", "Semaphore", "BoundedSemaphore", "Condition", "Barrier",
}
IO_CALLS = {
    # network
    "urlopen", "urllib", "requests", "httpx", "aiohttp", "fetch",
    "embed", "embed_contents", "post", "get", "put", "delete", "stream",
    "invoke", "chat", "complete", "generate",
    # disk / process
    "open", "dump", "load", "write_text", "read_text", "write_bytes", "read_bytes",
    "unlink", "mkdir", "rmtree", "copy", "rename", "replace", "remove",
    "run", "Popen", "call", "check_output", "check_call",
    "save", "save_all", "flush", "commit", "execute",
}
SLEEP_NAMES = {"sleep", "asyncio_sleep"}


class FuncInfo:
    def __init__(self):
        self.await_calls = []      # (line, name)
        self.io_calls = []         # (line, dotted-name)
        self.sleeps = []           # (line, name)
        self.spawns = []           # (line, what) run_in_executor / to_thread / create_task
        self.withs = []            # (line, expr-src)


def dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


class Scanner(ast.NodeVisitor):
    def __init__(self, path, rel):
        self.path = path
        self.rel = rel
        self.lock_defs = []    # (line, name, kind, scope: global/instance/local)
        self.results = []      # findings
        self.lock_names = {}   # var name -> kind (for tracking)

    def visit_Module(self, node):
        for stmt in node.body:
            self._scan_lock_def(stmt, "global")
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        for stmt in node.body:
            self._scan_lock_def(stmt, "class")
        self.generic_visit(node)

    def _scan_lock_def(self, stmt, scope):
        targets = []
        value = None
        if isinstance(stmt, ast.Assign):
            targets, value = stmt.targets, stmt.value
        elif isinstance(stmt, ast.AnnAssign):
            targets, value = [stmt.target], stmt.value
        if value is None:
            return
        name = None
        if isinstance(value, ast.Call):
            name = dotted(value.func)
        if name is None:
            return
        leaf = name.split(".")[-1]
        mod = name.split(".")[0] if "." in name else ""
        if leaf in LOCK_FACTORIES or leaf in ("Event",) and mod in ("threading", "asyncio"):
            kind = f"{mod}.{leaf}" if mod else leaf
            for t in targets:
                if isinstance(t, ast.Name):
                    self.lock_defs.append((stmt.lineno, t.id, kind, scope))
                elif isinstance(t, ast.Attribute):
                    self.lock_defs.append((stmt.lineno, t.attr, kind, scope))

    def visit_FunctionDef(self, node):
        self._scan_function(node)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def _scan_function(self, fn):
        for n in ast.walk(fn):
            if isinstance(n, ast.Call):
                name = dotted(n.func) or ""
                leaf = name.split(".")[-1]
                if leaf in IO_CALLS:
                    self.results.append(("io-call", n.lineno, name))
                elif leaf == "sleep":
                    self.results.append(("sleep", n.lineno, name))
                elif leaf in ("run_in_executor", "to_thread", "create_task", "ensure_future", "gather"):
                    self.results.append(("spawn", n.lineno, name))
            elif isinstance(n, ast.Await):
                inner = n.value
                if isinstance(inner, ast.Call):
                    name = dotted(inner.func) or "<expr>"
                    self.results.append(("await", n.lineno, name))


def analyze(path, rel):
    src = open(path, encoding="utf-8", errors="replace").read()
    tree = ast.parse(src)
    sc = Scanner(path, rel)
    sc.visit(tree)

    defs = [d for d in sc.lock_defs]
    # summarize sleeps inside while loops that also touch locks is hard via AST;
    # emit raw call evidence per file for manual review
    io = sorted(set(sc.results), key=lambda r: (r[1], r[0]))
    return {
        "file": rel,
        "lock_defs": defs,
        "calls": [
            {"kind": k, "line": ln, "name": nm} for k, ln, nm in io
        ],
    }


def main():
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", "tests", "node_modules")]
        for f in filenames:
            if not f.endswith(".py"):
                continue
            full = os.path.join(dirpath, f)
            rel = os.path.relpath(full, ".")
            try:
                out.append(analyze(full, rel))
            except SyntaxError as e:
                out.append({"file": rel, "error": str(e)})
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
