"""AST scan: find logging calls that embed SDK exception bodies.

Scope dirs passed as argv. Reports path:line, log method, leak vector, snippet.
Vectors:
  - direct exception name (e/exc/err/...) or str()/repr() of it inside log args
  - f-string interpolation of it
  - %-style positional arg
  - attribute access on it: .body .response .message .reason .stderr .stdout .output
    .text .content .details .json() .read()
  - exc_info=True literal
  - logger.exception(...) / .critical / .fatal (traceback embeds message)
  - one-level indirect: var assigned exception-derived expr, then logged
"""
import ast
import json
import sys
from pathlib import Path

LOG_METHODS = {"debug", "info", "warning", "warn", "error", "exception", "critical", "fatal", "log"}
EXC_NAMES = {"e", "ex", "exc", "err", "error", "exception", "http_exc", "api_error", "sdk_error"}
ATTR_VECS = {"body", "response", "message", "reason", "stderr", "stdout", "output", "text", "content", "details", "args"}


class FuncVisitor(ast.NodeVisitor):
    def __init__(self, relpath, src_lines, results):
        self.relpath = relpath
        self.lines = src_lines
        self.results = results

    def _snippet(self, lineno):
        lo = max(0, lineno - 3)
        return "\n".join(self.lines[lo:lineno]).strip()

    def visit_FunctionDef(self, node):
        self._scan_func(node)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def _scan_func(self, func):
        # collect exception bindings in this function (including nested handlers)
        exc_names = set()
        for n in ast.walk(func):
            if isinstance(n, ast.ExceptHandler) and n.name:
                exc_names.add(n.name)

        def is_exc(name):
            return name in exc_names or name.lower() in EXC_NAMES

        # one-level indirect map: var -> reason
        derived = {}
        for n in ast.walk(func):
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                tgt = n.targets[0].id
                if _exc_derived(n.value, is_exc):
                    derived[tgt] = _describe(n.value, is_exc)

        for n in ast.walk(func):
            if not isinstance(n, ast.Call) or not isinstance(n.func, ast.Attribute):
                continue
            meth = n.func.attr
            if meth not in LOG_METHODS:
                continue
            # receiver should look like a logger
            recv = n.func.value
            recv_name = None
            if isinstance(recv, ast.Name):
                recv_name = recv.id
            elif isinstance(recv, ast.Attribute):
                recv_name = recv.attr
            if recv_name is None or not ("log" in recv_name.lower() or recv_name.lower() in ("logger", "_logger", "LOGGER")):
                continue

            vectors = []

            def walk_arg(node, depth=0):
                if depth > 6:
                    return
                if isinstance(node, ast.Name):
                    if is_exc(node.id):
                        vectors.append(f"direct<{node.id}>")
                    elif node.id in derived:
                        vectors.append(f"indirect<{node.id}:{derived[node.id]}>")
                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name) and node.func.id == "type":
                        return
                    if isinstance(node.func, ast.Name) and node.func.id in ("str", "repr") and node.args:
                        a = node.args[0]
                        if isinstance(a, ast.Name) and is_exc(a.id):
                            vectors.append(f"{node.func.id}<{a.id}>")
                        elif isinstance(a, ast.Name) and a.id in derived:
                            vectors.append(f"{node.func.id}<indirect:{a.id}>")
                    for a in node.args:
                        walk_arg(a, depth + 1)
                    for k in node.keywords:
                        walk_arg(k.value, depth + 1)
                elif isinstance(node, ast.JoinedStr):
                    for v in node.values:
                        walk_arg(v, depth + 1)
                elif isinstance(node, ast.FormattedValue):
                    walk_arg(node.value, depth + 1)
                elif isinstance(node, ast.Attribute):
                    if isinstance(node.value, ast.Name) and is_exc(node.value.id) and node.attr in ATTR_VECS:
                        vectors.append(f"attr<{node.value.id}.{node.attr}>")
                    walk_arg(node.value, depth + 1)
                elif isinstance(node, ast.BinOp):
                    walk_arg(node.left, depth + 1)
                    walk_arg(node.right, depth + 1)

            for a in n.args:
                walk_arg(a)
            for k in n.keywords:
                if k.arg == "exc_info":
                    if isinstance(k.value, ast.Constant) and k.value.value is True:
                        vectors.append("exc_info=True")
                    elif isinstance(k.value, ast.Name) and is_exc(k.value.id.lower() if isinstance(k.value.id, str) else ""):
                        pass
                walk_arg(k.value)
            if meth == "exception":
                vectors.append("logger.exception(traceback)")
            if meth in ("critical", "fatal"):
                vectors.append(f"{meth}(traceback-if-exc_info)")

            if vectors:
                key = (self.relpath, n.lineno, meth)
                if any((r['path'], r['line'], r['method']) == key for r in self.results):
                    continue
                self.results.append({
                    "path": self.relpath,
                    "line": n.lineno,
                    "method": meth,
                    "vectors": sorted(set(vectors)),
                    "snippet": self._snippet(n.lineno),
                })


def _exc_derived(node, is_exc):
    try:
        _describe(node, is_exc)
        return True
    except _No:
        return False


class _No(Exception):
    pass


def _describe(node, is_exc):
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("str", "repr") and node.args and isinstance(node.args[0], ast.Name) and is_exc(node.args[0].id):
        return f"{node.func.id}({node.args[0].id})"
    if isinstance(node, ast.Name) and is_exc(node.id):
        return node.id
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.FormattedValue):
                parts.append(_describe(v.value, is_exc))
        if parts:
            return "f-string(" + ",".join(parts) + ")"
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        try:
            return "%" + _describe(node.right, is_exc)
        except _No:
            raise _No()
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and is_exc(node.value.id) and node.attr in ATTR_VECS:
        return f"{node.value.id}.{node.attr}"
    raise _No()


def scan(root: Path, rel: str):
    results = []
    try:
        tree = ast.parse("\n".join(root.joinpath(rel).read_text().splitlines()))
    except SyntaxError as err:
        print(f"SYNTAXERR {rel}: {err}", file=sys.stderr)
        return results
    lines = root.joinpath(rel).read_text().splitlines()
    FuncVisitor(rel, lines, results).visit(tree)
    return results


def main():
    root = Path(sys.argv[1])
    targets = []
    for d in sys.argv[2:]:
        p = root / d
        if p.is_dir():
            targets.extend(str(q.relative_to(root)) for q in sorted(p.rglob("*.py")))
        elif p.suffix == ".py":
            targets.append(d)
    out = []
    for rel in targets:
        out.extend(scan(root, rel))
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
