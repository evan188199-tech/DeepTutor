#!/usr/bin/env python3
"""Read-only scan of web/ for empty catch blocks and no-op .catch handlers.

Classifies every hit into three action types:
  report      - failure must be surfaced (console/telemetry/user feedback)
  degrade     - failure tolerated but must land in an explicit error/fallback state
  best_effort - intentional best-effort swallow; keep, document intent

Usage: python3 scan_ts_catch.py > ts_catch_details.json
Scope: web/**/*.{ts,tsx,js,jsx,mjs}, node_modules excluded. Never modifies files.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]  # evidence/ts-catch-scan-<date>/ -> repo root
WEB_DIR = "web"
GLOBS = ["*.{ts,tsx,js,jsx,mjs}"]

EMPTY_CATCH_RE = re.compile(r"catch\s*(\([^)]*\))?\s*\{\s*\}", re.DOTALL)
NOOP_CATCH_RE = re.compile(
    r"\.catch\(\s*\(\s*\)\s*=>\s*(\{\s*\}|undefined|null|void 0)\s*\)", re.DOTALL
)

# function-ish context line detectors
FUNC_RE = re.compile(
    r"(?:async\s+)?(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(|"
    r"(?:export\s+)?(?:default\s+)?(?:async\s+)?(\w+)\s*\([^)]*\)\s*(?::\s*[^{]+)?\{)"
)

CLASSIFY = {}  # (file, line) -> (action, reason) filled by manual review table below


def ripgrep_files():
    out = subprocess.run(
        ["rg", "--files", str(REPO_ROOT / WEB_DIR)]
        + sum([["-g", g] for g in GLOBS], [])
        + ["-g", "!node_modules/**", "-g", "!.next/**"],
        capture_output=True,
        text=True,
        check=True,
    )
    return sorted(line.removeprefix(str(REPO_ROOT) + "/") for line in out.stdout.splitlines())


def statement_start(lines, idx):
    """Walk upwards from match line to find the first line of the statement chain."""
    start = idx
    depth = 0
    j = idx
    while j >= 0:
        line = lines[j]
        depth += line.count(")") - line.count("(")
        stripped = line.strip()
        if depth <= 0 and (
            re.match(r"^(?:await\s+|void\s+|return\s+|const\s|let\s|var\s|\}|;|$)", stripped)
            or (j < idx and stripped.endswith(";"))
        ):
            start = j
            if re.match(r"^(?:await\s+|void\s+|return\s+|const\s|let\s|var\s)", stripped):
                break
        j -= 1
    return start


def enclosing_block(lines, idx):
    """Best-effort enclosing function name above the match line."""
    for j in range(idx, max(idx - 80, -1), -1):
        m = FUNC_RE.search(lines[j])
        if m:
            name = next((g for g in m.groups() if g), "<anonymous>")
            return name
    return "<top-level>"


def scan():
    items = []
    for rel in ripgrep_files():
        path = REPO_ROOT / rel
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        lines = text.splitlines()
        # union of both pattern hit line numbers
        hits = []
        for m in EMPTY_CATCH_RE.finditer(text):
            ln = text.count("\n", 0, m.start()) + 1
            hits.append((ln, "empty_catch", m.group(0)))
        for m in NOOP_CATCH_RE.finditer(text):
            ln = text.count("\n", 0, m.start()) + 1
            hits.append((ln, "noop_catch", m.group(0)))
        hits.sort()
        for ln, kind, matched in hits:
            idx = ln - 1
            s_start = statement_start(lines, idx) if kind == "noop_catch" else idx
            statement = " ".join(
                l.strip() for l in lines[s_start : idx + 1] if l.strip()
            )
            statement = statement[:300]
            context = "\n".join(
                lines[max(0, idx - 12) : min(len(lines), idx + 6)]
            )
            items.append(
                {
                    "file": rel,
                    "line": ln,
                    "kind": kind,
                    "matched": matched.strip()[:80],
                    "enclosing": enclosing_block(lines, idx),
                    "statement": statement,
                    "context": context,
                }
            )
    return items


if __name__ == "__main__":
    items = scan()
    payload = {
        "scan": "ts-catch-scan",
        "scope": WEB_DIR,
        "total": len(items),
        "counts": {
            "empty_catch": sum(1 for i in items if i["kind"] == "empty_catch"),
            "noop_catch": sum(1 for i in items if i["kind"] == "noop_catch"),
        },
        "items": items,
    }
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    print()
