"""AST-based scan for silent exception handlers in Python sources."""
import ast
import json
import os
import sys

ROOTS = ["deeptutor", "deeptutor_cli", "scripts", "tests"]
EXCLUDE_PARTS = {"node_modules", ".next", "build", "dist", "__pycache__", ".git"}


def is_silent_body(body):
    if not body:
        return True
    for stmt in body:
        if isinstance(stmt, ast.Pass):
            continue
        if isinstance(stmt, ast.Continue):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and stmt.value.value is Ellipsis:
            continue
        return False
    return True


def handler_type_name(node):
    t = node.type
    if t is None:
        return "<bare>"
    if isinstance(t, ast.Tuple):
        return ", ".join(ast.dump(e).split("'")[1] if isinstance(e, ast.Name) else "?" for e in t.elts)
    if isinstance(t, ast.Name):
        return t.id
    if isinstance(t, ast.Attribute):
        return t.attr
    return ast.dump(t)[:40]


class FuncCollector(ast.NodeVisitor):
    def __init__(self):
        self.parents = {}

    def generic_visit(self, node):
        for child in ast.iter_child_nodes(node):
            self.parents[child] = node
        super().generic_visit(node)


def enclosing_function(parents, node):
    cur = parents.get(node)
    while cur is not None:
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return cur.name
        cur = parents.get(cur)
    return "<module>"


def in_loop(parents, node):
    cur = parents.get(node)
    while cur is not None:
        if isinstance(cur, (ast.For, ast.While, ast.AsyncFor)):
            return True
        cur = parents.get(cur)
    return False


def scan_file(path):
    results = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            src = f.read()
        tree = ast.parse(src)
    except SyntaxError:
        return results
    parents = {}
    fc = FuncCollector()
    fc.parents = parents
    fc.visit(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for handler in node.handlers:
                if not is_silent_body(handler.body):
                    continue
                tname = handler_type_name(handler)
                try_first = ""
                if node.body:
                    try_first = ast.get_source_segment(src, node.body[0]) or ""
                    try_first = try_first.strip().split("\n")[0][:110]
                results.append({
                    "path": path,
                    "line": handler.lineno,
                    "type": tname,
                    "body": ("continue" if any(isinstance(s, ast.Continue) for s in handler.body) else "pass"),
                    "func": enclosing_function(parents, handler),
                    "in_loop": in_loop(parents, handler),
                    "try_first": try_first,
                })
    return results


def main():
    all_results = []
    for root in ROOTS:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_PARTS]
            for fn in filenames:
                if not fn.endswith(".py"):
                    continue
                all_results.extend(scan_file(os.path.join(dirpath, fn)))
    json.dump(all_results, sys.stdout, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
