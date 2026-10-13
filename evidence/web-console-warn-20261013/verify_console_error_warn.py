#!/usr/bin/env python3
"""Verify triage.csv against the working tree (read-only).

Reproduces the console.error/warn scan counts and validates every triage row:
  1. rg-equivalent scan of web/ (regex, no shell rg dependency) must find
     exactly 45 lines carrying console.error/warn, of which 38 error + 7 warn
     matches carry call parens (matching the agen-1787 baseline); rendered.ts
     carries 1 extra parenless identifier reference.
  2. Every triage.csv row (46 = 45 lines, iframe line carries 2 matches) must
     point at an existing file whose recorded line contains the recorded
     console token, with matching method.
  3. Tri-state totals must match the report (合理保留 36 / 疑似调试残留 7 / 误报 3).

Exit 0 = all checks pass. No file is modified.
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

EXTS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".mts", ".cts", ".cjs"}
SKIP_DIRS = {"node_modules", ".next"}
PAREN_RE = re.compile(r"console\.(error|warn)\(")
HERE = Path(__file__).resolve().parent
WEB = HERE.parent.parent / "web"

EXPECTED_TOTALS = {"合理保留": 36, "疑似调试残留": 7, "误报": 3}
EXPECTED_ERROR = 38
EXPECTED_WARN = 7
EXPECTED_LINES = 45


def scan() -> list[tuple[str, int, str]]:
    hits: list[tuple[str, int, str]] = []
    for path in sorted(WEB.rglob("*")):
        if not path.is_file() or path.suffix not in EXTS:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        rel = path.relative_to(WEB.parent).as_posix()
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            print(f"WARN unreadable {rel}: {exc}")
            continue
        for lineno, text in enumerate(lines, 1):
            if "console.error" in text or "console.warn" in text:
                hits.append((rel, lineno, text))
    return hits


def main() -> int:
    hits = scan()
    n_error = sum(1 for _, _, t in hits if PAREN_RE.search(t) and "console.error(" in t)
    n_warn = sum(1 for _, _, t in hits if "console.warn(" in t)
    print(f"scan: {len(hits)} lines, error(paren)={n_error}, warn(paren)={n_warn}")
    ok = True
    if len(hits) != EXPECTED_LINES:
        print(f"FAIL line count {len(hits)} != {EXPECTED_LINES}")
        ok = False
    if n_error != EXPECTED_ERROR:
        print(f"FAIL error count {n_error} != {EXPECTED_ERROR}")
        ok = False
    if n_warn != EXPECTED_WARN:
        print(f"FAIL warn count {n_warn} != {EXPECTED_WARN}")
        ok = False

    rows = list(csv.DictReader((HERE / "triage.csv").open(encoding="utf-8")))
    print(f"triage rows: {len(rows)}")
    if len(rows) != EXPECTED_ERROR + EXPECTED_WARN + 1:
        print(f"FAIL row count {len(rows)} != {EXPECTED_ERROR + EXPECTED_WARN + 1}")
        ok = False

    hit_index = {(f, n) for f, n, _ in hits}
    for row in rows:
        rel, line = row["file"], int(row["line"])
        token = f"console.{row['method']}("
        if (rel, line) not in hit_index and row["tri_state"] != "误报":
            print(f"FAIL row {row['match_id']}: {rel}:{line} not in scan hits")
            ok = False
        path = WEB.parent / rel
        if not path.is_file():
            print(f"FAIL row {row['match_id']}: missing file {rel}")
            ok = False
            continue
        text = path.read_text(encoding="utf-8", errors="replace").splitlines()[line - 1]
        if row["tri_state"] == "误报":
            if f"console.{row['method']}" not in text:
                print(f"FAIL row {row['match_id']}: {rel}:{line} lacks console.{row['method']}")
                ok = False
        elif token not in text:
            print(f"FAIL row {row['match_id']}: {rel}:{line} lacks call {token}")
            ok = False

    totals: dict[str, int] = {}
    for row in rows:
        totals[row["tri_state"]] = totals.get(row["tri_state"], 0) + 1
    print(f"tri-state totals: {totals}")
    for state, expected in EXPECTED_TOTALS.items():
        if totals.get(state, 0) != expected:
            print(f"FAIL {state} {totals.get(state, 0)} != {expected}")
            ok = False

    print("RESULT: PASS" if ok else "RESULT: FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
