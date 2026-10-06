#!/usr/bin/env python3
"""AST cross-check for the subprocess spawn-site inventory.

Walks a package tree and prints every real spawn call site as
``path:line<TAB>fn<TAB>timeout=<absent|present><TAB>capture=<flags>``,
so the count can be reproduced and diffed against report.md.

Usage: python3 audit_subprocess_ast.py deeptutor
"""

from __future__ import annotations

import ast
import pathlib
import sys

SUBPROCESS_FNS = {"run", "Popen", "check_output", "check_call", "call", "getoutput", "getstatusoutput"}
ASYNC_FNS = {"create_subprocess_exec", "create_subprocess_shell"}
CAPTURE_FLAGS = {"capture_output", "stdout", "stderr"}


def _kw_value(call: ast.Call, name: str) -> str | None:
    for kw in call.keywords:
        if kw.arg == name:
            try:
                return ast.unparse(kw.value)
            except Exception:  # noqa: BLE001
                return "?"
    return None


def main(root: str) -> int:
    found: list[str] = []
    for path in sorted(pathlib.Path(root).rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            fn = node.func.attr
            owner = ast.unparse(node.func.value) if hasattr(ast, "unparse") else ""
            if (owner == "subprocess" and fn in SUBPROCESS_FNS) or (
                owner == "asyncio" and fn in ASYNC_FNS
            ):
                timeout = "present" if _kw_value(node, "timeout") else "absent"
                capture = ",".join(k for k in CAPTURE_FLAGS if _kw_value(node, k))
                found.append(f"{path}:{node.lineno}\t{owner}.{fn}\ttimeout={timeout}\tcapture={capture or '-'}")
    for line in found:
        print(line)
    print(f"# total: {len(found)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "deeptutor"))
