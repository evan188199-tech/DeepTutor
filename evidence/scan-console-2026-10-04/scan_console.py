#!/usr/bin/env python3
"""AGEN-520: scan web/ for console.* / debugger / commented debug blocks.

Read-only static scan. Produces console_findings.json (authoritative raw data).
Classification (degrade / leftover / swallow) is applied afterwards in
console_classified.json; this script only detects and tags occurrences.

Method:
  1. Mask comments and string-literal contents (keep ${...} interpolation code).
  2. Regex console.<method>( / debugger; over masked source -> real code hits.
  3. Regex over original source; hits not in the code set are tagged by the
     mask (comment vs string).
  4. Brace-depth tracking over masked source tags each code hit with
     in_catch (inside a catch block / .catch() handler).

Tags per finding:
  surface: code | string | comment
  in_catch: bool (code hits only)
  area: app | components | features | context | lib | scripts | tests | other
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # worktree root
WEB = ROOT / "web"
OUT = Path(__file__).resolve().parent / "console_findings.json"

EXTS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".mts", ".cts", ".cjs"}
EXCLUDE_DIRS = {"node_modules", ".next"}
METHODS = (
    "log|warn|error|debug|info|trace|dir|table|assert|count|group|"
    "groupEnd|groupCollapsed|time|timeEnd|timeLog|timeStamp|profile"
)
CALL_PAREN_RE = re.compile(rf"console\.({METHODS})\s*\(")
CALL_ANY_RE = re.compile(rf"console\.({METHODS})\b")
DEBUGGER_RE = re.compile(r"\bdebugger\b")
DEBUGGER_STMT_RE = re.compile(r"\bdebugger\s*;")


def area_of(rel: str) -> str:
    parts = rel.split("/")
    if len(parts) >= 2 and parts[0] == "web":
        second = parts[1]
        if second in {"app", "components", "features", "context", "lib",
                      "scripts", "tests"}:
            return second
    return "other"


def mask_source(src: str):
    """Return masked text + is_code flag array (same length as src).

    Comments and string contents become spaces; newlines preserved.
    Template ${...} interpolation keeps its code.
    """
    n = len(src)
    masked = list(src)
    is_code = [True] * n
    i = 0
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":  # line comment
            j = i
            while j < n and src[j] != "\n":
                is_code[j] = False
                masked[j] = " " if src[j] != "\n" else "\n"
                j += 1
            i = j
            continue
        if c == "/" and nxt == "*":  # block comment
            j = i
            end = src.find("*/", i + 2)
            end = n if end == -1 else end + 2
            while j < end:
                is_code[j] = False
                if src[j] != "\n":
                    masked[j] = " "
                j += 1
            i = end
            continue
        if c in "'\"`":
            quote = c
            j = i + 1
            is_code[i] = True
            exit_i = None
            while j < n:
                if src[j] == "\\":
                    is_code[j] = False
                    masked[j] = " "
                    if j + 1 < n:
                        is_code[j + 1] = False
                        masked[j + 1] = " "
                    j += 2
                    continue
                if src[j] == "\n" and quote != "`":
                    exit_i = j  # unterminated; resume at newline
                    break
                if src[j] == quote:
                    exit_i = j + 1  # resume after closing quote
                    break
                if quote == "`" and src[j] == "$" and \
                        j + 1 < n and src[j + 1] == "{":
                    # keep interpolation code unmasked: skip to matching },
                    # then continue masking the rest of the template
                    depth = 1
                    k = j + 2
                    while k < n and depth:
                        if src[k] == "{":
                            depth += 1
                        elif src[k] == "}":
                            depth -= 1
                            if depth == 0:
                                break
                        k += 1
                    j = k + 1
                    continue
                is_code[j] = False
                masked[j] = " "
                j += 1
            if exit_i is None:
                exit_i = n
            i = exit_i
            continue
        i += 1
    return "".join(masked), is_code


def find_catch_ranges(masked: str):
    """Return list of (open_brace_offset, close_brace_offset) for catch
    blocks and .catch() handlers, via brace-depth tracking."""
    ranges = []
    depth = 0
    pending_catch = False
    stack = []  # (open_brace_offset, is_catch)
    i, n = 0, len(masked)
    while i < n:
        c = masked[i]
        if masked[i:i + 7] == ".catch(":
            pending_catch = True
            i += 6
            continue
        if masked[i:i + 5] == "catch" and \
                (i == 0 or not (masked[i - 1].isalnum() or
                                masked[i - 1] in "_$.")):
            m = re.match(r"catch\s*\(", masked[i:])
            if m:
                pending_catch = True
                i += m.end()
                continue
        if c == "{":
            depth += 1
            stack.append((i, pending_catch))
            pending_catch = False
            i += 1
            continue
        if c == "}":
            if stack:
                open_off, is_catch = stack.pop()
                if is_catch:
                    ranges.append((open_off, i))
            depth -= 1
            i += 1
            continue
        i += 1
    return ranges


def line_col_of(offset: int, line_starts):
    import bisect
    line = bisect.bisect_right(line_starts, offset)
    col = offset - line_starts[line - 1]
    return line, col + 1


def scan_file(path: Path):
    rel = str(path.relative_to(ROOT))
    src = path.read_text(encoding="utf-8", errors="replace")
    masked, is_code = mask_source(src)
    line_starts = [0]
    for m in re.finditer("\n", src):
        line_starts.append(m.end())

    findings = []
    catch_ranges = find_catch_ranges(masked)

    def in_catch(offset: int) -> bool:
        return any(s <= offset < e for s, e in catch_ranges)

    code_seen = set()
    for m in CALL_PAREN_RE.finditer(masked):
        if not all(is_code[k] for k in range(m.start(), m.end())):
            continue
        line, col = line_col_of(m.start(), line_starts)
        code_seen.add((line, col))
        findings.append({
            "file": rel, "line": line, "col": col,
            "kind": "console_call", "method": m.group(1),
            "surface": "code", "in_catch": in_catch(m.start()),
            "area": area_of(rel),
        })
    for m in DEBUGGER_STMT_RE.finditer(masked):
        if not is_code[m.start()]:
            continue
        line, col = line_col_of(m.start(), line_starts)
        findings.append({
            "file": rel, "line": line, "col": col,
            "kind": "debugger_stmt", "method": None,
            "surface": "code", "in_catch": in_catch(m.start()),
            "area": area_of(rel),
        })
    # bare identifier references (no call paren), e.g. test spying setup
    for m in CALL_ANY_RE.finditer(masked):
        if not all(is_code[k] for k in range(m.start(), m.end())):
            continue
        after = masked[m.end():m.end() + 8]
        if after.lstrip().startswith("("):
            continue  # already captured as console_call
        line, col = line_col_of(m.start(), line_starts)
        if (line, col) in {(f["line"], f["col"]) for f in findings}:
            continue
        findings.append({
            "file": rel, "line": line, "col": col,
            "kind": "console_reference", "method": m.group(1),
            "surface": "code", "in_catch": in_catch(m.start()),
            "area": area_of(rel),
        })
    # non-code mentions (comments / string contents)
    lines = src.split("\n")
    offset = 0
    for idx, text in enumerate(lines, 1):
        for m in CALL_ANY_RE.finditer(text):
            abs_off = offset + m.start()
            if is_code[abs_off]:
                continue
            surface = "string"
            # decide comment vs string via masked char classification is not
            # enough (both non-code); use masked text: comments were spaces,
            # string contents also spaces. Use line inspection: leading //,
            # /* or * -> comment
            stripped = text.strip()
            if stripped.startswith("//") or stripped.startswith("/*") or \
                    stripped.startswith("*"):
                surface = "comment"
            else:
                head = text[:m.start()]
                if head.count('"') % 2 == 1 or head.count("'") % 2 == 1 or \
                        head.count("`") % 2 == 1:
                    surface = "string"
                else:
                    # whole-line comment continuation inside block comment:
                    # masked line is all spaces beyond code chars -> comment
                    masked_line = masked[offset + m.start() -
                                         (m.start() - 0):][:len(text)]
                    if not any(is_code[offset + k]
                               for k in range(0, len(text))):
                        surface = "comment"
            findings.append({
                "file": rel, "line": idx,
                "col": m.start() + 1,
                "kind": "console_mention", "method": m.group(1),
                "surface": surface, "in_catch": False,
                "area": area_of(rel), "text": stripped[:160],
            })
        dm = DEBUGGER_RE.search(text)
        if dm and not is_code[offset + dm.start()]:
            stripped = text.strip()
            if stripped.startswith("//") or stripped.startswith("/*") or \
                    stripped.startswith("*"):
                findings.append({
                    "file": rel, "line": idx,
                    "col": dm.start() + 1,
                    "kind": "debugger_mention", "method": None,
                    "surface": "comment", "in_catch": False,
                    "area": area_of(rel), "text": stripped[:160],
                })
        offset += len(text) + 1

    return findings


def main():
    all_findings = []
    files_scanned = 0
    for path in sorted(WEB.rglob("*")):
        if not path.is_file() or path.suffix not in EXTS:
            continue
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        all_findings.extend(scan_file(path))
        files_scanned += 1

    all_findings.sort(key=lambda f: (f["file"], f["line"], f["col"]))
    OUT.write_text(json.dumps({
        "files_scanned": files_scanned,
        "total": len(all_findings),
        "findings": all_findings,
    }, ensure_ascii=False, indent=2))
    print(f"files={files_scanned} findings={len(all_findings)} -> {OUT}")


if __name__ == "__main__":
    main()
