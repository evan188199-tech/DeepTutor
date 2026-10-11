#!/usr/bin/env python3
"""Read-only AST scan for silent exception handlers (except ... : pass/continue).

Re-runs the DT-22 detection criteria on a given commit's working tree.
Usage: python3 scan_py_swallow.py [file ...]
With no args, scans the 10 DT-22 HIGH target files.
Output: one JSON object per silent handler on stdout.
"""
import ast
import json
import sys
from pathlib import Path

TARGETS = [
    "deeptutor/api/routers/knowledge.py",
    "deeptutor/api/routers/question.py",
    "deeptutor/knowledge/manager.py",
    "deeptutor/runtime/launcher.py",
    "deeptutor/runtime/update_worker.py",
    "deeptutor/services/embedding/client.py",
    "deeptutor/services/memory/snapshot/adapters.py",
    "deeptutor/services/rag/pipelines/graphrag/provider.py",
    "deeptutor/services/rag/pipelines/llamaindex/document_loader.py",
    "deeptutor/services/storage/file_library.py",
]


def exc_names(node):
    if node.type is None:
        return ["<bare>"]
    return ast.unparse(node.type).replace("(", "").replace(")", "").split(",")


def first_stmt_src(handler, lines):
    body = handler.body
    if not body:
        return ""
    ln = body[0].lineno
    col = body[0].col_offset
    text = lines[ln - 1][col:]
    stripped = text.strip()
    if not stripped and len(body) > 1:
        return ""
    return stripped


def enclosing_function(tree, node):
    parent_map = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parent_map[child] = parent
    cur = node
    while cur in parent_map:
        cur = parent_map[cur]
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return cur.name
    return "<module>"


def try_first_line(tree, handler, lines):
    parent_map = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parent_map[child] = parent
    cur = handler
    while cur in parent_map:
        cur = parent_map[cur]
        if isinstance(cur, ast.Try) or isinstance(cur, getattr(ast, "TryStar", ())):
            return first_stmt_src_with(cur, lines)
    return ""


def first_stmt_src_with(try_node, lines):
    body = try_node.body
    if not body:
        return ""
    ln = body[0].lineno
    col = body[0].col_offset
    return lines[ln - 1][col:].strip()


def scan_file(path):
    src = Path(path).read_text(encoding="utf-8", errors="replace")
    lines = src.splitlines()
    tree = ast.parse(src)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if len(node.body) != 1 or not isinstance(node.body[0], (ast.Pass, ast.Continue)):
            continue
        kind = "pass" if isinstance(node.body[0], ast.Pass) else "continue"
        out.append(
            {
                "file": str(path),
                "line": node.lineno,
                "exc": [n.strip() for n in exc_names(node)],
                "body": kind,
                "func": enclosing_function(tree, node),
                "try_first": try_first_line(tree, node, lines),
            }
        )
    return out


def main():
    files = sys.argv[1:] or TARGETS
    for f in files:
        for rec in scan_file(f):
            print(json.dumps(rec, ensure_ascii=False))


if __name__ == "__main__":
    main()
