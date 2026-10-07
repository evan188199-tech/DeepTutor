#!/usr/bin/env python3
"""AST inventory of signal-handler, atexit and child-termination sites.

Companion scanner for the signal/exit-path audit. Walks a package tree and
prints one line per site as
``path:line<TAB>kind<TAB>detail``
with paths sorted and lines ascending, so the output is byte-stable for the
same input tree (reproducibility acceptance for this scan).

Kinds emitted:
  signal_signal        signal.signal(<SIG...>, <handler>)          registration
  signal_ignore        signal.signal(<SIG...>, SIG_IGN/SIG_DFL)
  add_signal_handler   loop.add_signal_handler(<SIG...>, <cb>)
  remove_signal_handler loop.remove_signal_handler(<SIG...>)
  atexit_register      atexit.register / @atexit.register
  sig_send             os.kill / os.killpg / proc.terminate / proc.kill / taskkill argv
  proc_wait            proc.wait / waitpid / communicate  (+timeout=present|absent)
  kbd_interrupt        ``except KeyboardInterrupt`` handlers

Usage: python3 audit_signal_exit.py <package-root>...
"""

from __future__ import annotations

import ast
import pathlib
import sys

SIGNAL_NAMES = {
    name
    for name in dir(__import__("signal"))
    if name.startswith("SIG") and not name.startswith("SIG_")
}


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        owner = ast.unparse(func.value) if hasattr(ast, "unparse") else "?"
        return f"{owner}.{func.attr}"
    if isinstance(func, ast.Name):
        return func.id
    return ast.unparse(func) if hasattr(ast, "unparse") else "?"


def _arg_text(node: ast.Call, index: int) -> str:
    try:
        return ast.unparse(node.args[index])
    except Exception:  # noqa: BLE001 - unparse is best-effort only
        return "?"


def _kw_text(node: ast.Call, name: str) -> str | None:
    for kw in node.keywords:
        if kw.arg == name:
            try:
                return ast.unparse(kw.value)
            except Exception:  # noqa: BLE001
                return "?"
    return None


def _classify_call(node: ast.Call) -> tuple[str, str] | None:
    name = _call_name(node)
    owner, _, attr = name.rpartition(".")
    if name in {"signal.signal", "signal.pthread_sigmask"} or (
        owner == "signal" and attr == "signal"
    ):
        sig = _arg_text(node, 0)
        handler = _arg_text(node, 1)
        kind = "signal_ignore" if handler in {"signal.SIG_IGN", "signal.SIG_DFL"} else "signal_signal"
        return kind, f"{sig} handler={handler}"
    if attr == "add_signal_handler":
        return "add_signal_handler", f"{_arg_text(node, 0)} cb={_arg_text(node, 1)}"
    if attr == "remove_signal_handler":
        return "remove_signal_handler", _arg_text(node, 0)
    if name == "atexit.register" or (owner == "atexit" and attr == "register"):
        target = _arg_text(node, 0) if node.args else "(decorator)"
        return "atexit_register", f"fn={target}"
    if name in {"os.kill", "os.killpg", "os.pkill"}:
        return "sig_send", f"{name}({', '.join(_arg_text(node, i) for i in range(len(node.args)))})"
    if attr in {"terminate", "kill", "send_signal"} and owner not in {"signal"}:
        return "sig_send", f"{name}()"
    if attr == "waitpid":
        return "proc_wait", f"os.waitpid({_arg_text(node, 0)}, opts={_arg_text(node, 1) if len(node.args) > 1 else _kw_text(node, 'options') or '0'})"
    if attr in {"wait", "communicate"} and owner.startswith(("process", "proc", "self._", "handle.")):
        timeout = "present" if _kw_text(node, "timeout") else "absent"
        return "proc_wait", f"{name}(timeout={timeout})"
    if attr in {"wait_for"} and "asyncio" in owner:
        timeout = _kw_text(node, "timeout")
        if timeout is not None:
            return "proc_wait", f"asyncio.wait_for(timeout={timeout})"
    if attr == "run" and owner == "subprocess":
        timeout = "present" if _kw_text(node, "timeout") else "absent"
        return "proc_wait", f"subprocess.run(timeout={timeout})"
    return None


def _taskkill_argv(node: ast.Call) -> bool:
    for arg in node.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value == "taskkill":
            return True
    return False


def scan(root: pathlib.Path) -> list[str]:
    rows: list[tuple[str, int, str, str]] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        try:
            tree = ast.parse(path.read_text(errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if _taskkill_argv(node):
                    rows.append((str(rel), node.lineno, "sig_send", "taskkill /T argv"))
                    continue
                hit = _classify_call(node)
                if hit:
                    rows.append((str(rel), node.lineno, hit[0], hit[1]))
            elif isinstance(node, ast.ExceptHandler):
                if isinstance(node.type, ast.Name) and node.type.id == "KeyboardInterrupt":
                    rows.append((str(rel), node.lineno, "kbd_interrupt", "except KeyboardInterrupt"))
    return [
        f"{rel}:{line}\t{kind}\t{detail}"
        for rel, line, kind, detail in sorted(rows, key=lambda r: (r[0], r[1], r[2]))
    ]


def main(roots: list[str]) -> int:
    lines: list[str] = []
    for root in roots:
        lines.extend(scan(pathlib.Path(root)))
    for line in lines:
        print(line)
    print(f"# total: {len(lines)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1:]))
