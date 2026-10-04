"""AST scan: text-mode file/subprocess calls without an explicit encoding.

Counts calls to open()/Path.read_text/write_text whose text mode lacks
``encoding=`` (positional or keyword), and subprocess text=True /
universal_newlines=True calls without ``encoding=``. Binary modes and
non-file opens (webbrowser/wave/tarfile/pymupdf/httpx) are filtered by
receiver name allow-list.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOTS = sys.argv[1:] or ["deeptutor", "deeptutor_cli", "scripts"]

FILE_METHODS = {"read_text", "write_text", "read_bytes", "write_bytes"}
TEXT_NEEDING = {"read_text", "write_text"}
NON_FILE_OPENS = {
    "webbrowser", "wave", "tarfile", "pymupdf", "fitz", "urllib", "httpx",
    "Image", "archive", "zipfile", "gzip", "io",
}


def call_name(node: ast.Call) -> tuple[str, str]:
    func = node.func
    if isinstance(func, ast.Name):
        return "", func.id
    if isinstance(func, ast.Attribute):
        base = func.value
        base_name = ""
        if isinstance(base, ast.Name):
            base_name = base.id
        elif isinstance(base, ast.Attribute):
            base_name = base.attr
        elif isinstance(base, ast.Call):
            base_name = "call"
        return base_name, func.attr
    return "", ""


def has_encoding(node: ast.Call, encoding_pos: int) -> bool:
    if len(node.args) > encoding_pos:
        return True
    return any(kw.arg == "encoding" for kw in node.keywords)


def open_mode(node: ast.Call, method: bool) -> str:
    mode = "r"
    idx = 0 if method else 1
    if len(node.args) > idx and isinstance(node.args[idx], ast.Constant):
        mode = str(node.args[idx].value)
    for kw in node.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            mode = str(kw.value)
    return mode


def receiver_is_fileish(base: str, attr: str) -> bool:
    if attr in TEXT_NEEDING:
        return True
    if base in NON_FILE_OPENS:
        return False
    return True


def main() -> None:
    findings: list[tuple[str, int, str]] = []
    files = 0
    for root in ROOTS:
        for path in Path(root).rglob("*.py"):
            files += 1
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                base, attr = call_name(node)
                if attr in TEXT_NEEDING and receiver_is_fileish(base, attr):
                    if not has_encoding(node, 0):
                        findings.append((str(path), node.lineno, f"{base}.{attr}() no encoding"))
                elif attr == "open" or (not attr and base == "open"):
                    if base in NON_FILE_OPENS:
                        continue
                    mode = open_mode(node, method=isinstance(node.func, ast.Attribute))
                    if "b" not in mode and not has_encoding(node, 3):
                        has_errors = any(kw.arg == "errors" for kw in node.keywords)
                        findings.append((str(path), node.lineno, f"open(mode={mode!r}) no encoding" + (" (errors= set)" if has_errors else "")))
                if attr in {"run", "Popen", "check_output", "check_call"} or (not attr and base in {"run", "Popen"}):
                    text_mode = any(
                        (kw.arg in ("text", "universal_newlines") and isinstance(kw.value, ast.Constant) and kw.value.value)
                        for kw in node.keywords
                    )
                    if text_mode and not has_encoding(node, 8):
                        findings.append((str(path), node.lineno, f"subprocess.{attr}(text=True) no encoding"))
    print(f"# files scanned: {files}")
    for path, line, what in sorted(findings):
        print(f"{path}:{line}: {what}")
    print(f"# total findings: {len(findings)}")


if __name__ == "__main__":
    main()
