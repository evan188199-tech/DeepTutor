#!/usr/bin/env python3
"""Classify how catch blocks in web/ surface failures to the user.

Axis (B) — presentation surface of failure paths. This is the presentation
axis only: language-level swallowing of exceptions is owned by the
scan-ts-catch scan, and console noise shape by scan-console-noise. Entries
whose whole catch body is empty or comment-only are emitted with
overlap=scan-ts-catch so the two scans can be reconciled.

Surface categories (precedence, first match wins):
  toast_error       notify(..., tone: "error") / notify(msg, "error")
  toast_other       notify(...) with another or default tone
  inline_state      setState-shaped error variables (setError*, set*Error,
                    setErrorMessage, assignment to *Error state)
  banner            identifier mentions a banner in the block
  rethrow           throws (wraps or propagates for an outer surface)
  degrade_default   replaces data with a fallback value (e.g. `x = []`)
  console_only      only console.* side effects
  silent            empty body or comment-only body
  unclassified      logic with no recognized surface marker

Deterministic: sorted walks, stable JSON, no timestamps.
Usage: python3 scan_failure_surfacing.py <repo-root>
"""
import json
import re
import sys
from pathlib import Path

SKIP_DIRS = {"node_modules", ".next", "coverage", "dist", ".turbo", ".git"}
SKIP_PARTS = ("tests", "__tests__", "e2e")
SOURCE_SUFFIXES = {".ts", ".tsx"}
WEB = "web"

CATCH_RE = re.compile(r"\bcatch\s*(?:\([^)]*\))?\s*\{")
NOTIFY_ANY_RE = re.compile(r"\bnotify\s*\(")
NOTIFY_ERROR_RE = re.compile(r"""tone\s*:\s*["']error["']""")
SETERR_RE = re.compile(r"\bset\w*(?:[Ee]rror|Failure|Failed)\w*\s*\(")
SETTOAST_RE = re.compile(r"\bset(?:Toast|Notice)\s*\(")
ERR_ASSIGN_RE = re.compile(r"\b[A-Za-z_$]\w*Error(?:Message|Text)?\s*=[^=]")
BANNER_RE = re.compile(r"[Bb]anner")
THROW_RE = re.compile(r"\bthrow\b")
DEGRADE_RE = re.compile(r"=\s*(\[\s*\]|null|false|undefined|0)\b\s*;?")
CONSOLE_RE = re.compile(r"\bconsole\.")
COMMENT_ONLY_RE = re.compile(r"^(?:(?:/\*[\s\S]*?\*/)|(?://[^\n]*))?$", re.M)

CATEGORY_ORDER = [
    "toast_error", "toast_other", "inline_state", "banner", "rethrow",
    "degrade_default", "console_only", "silent", "unclassified",
]


def extract_block(text: str, open_idx: int) -> tuple[str, int]:
    """Return the balanced {...} block starting at open_idx and its end."""
    depth = 0
    i = open_idx
    in_str = None
    while i < len(text):
        ch = text[i]
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == in_str:
                in_str = None
        elif ch in {'"', "'", "`"}:
            in_str = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[open_idx + 1:i], i
        i += 1
    return text[open_idx + 1:], len(text) - 1


def classify(body: str) -> tuple[str, str]:
    stripped = body.strip()
    body_no_comments = re.sub(r"//[^\n]*", "", body)
    body_no_comments = re.sub(r"/\*[\s\S]*?\*/", "", body_no_comments)
    effective = body_no_comments.strip()
    if NOTIFY_ANY_RE.search(body):
        return ("toast_error", "") if NOTIFY_ERROR_RE.search(body) \
            else ("toast_other", "")
    if SETERR_RE.search(body) or ERR_ASSIGN_RE.search(body):
        return "inline_state", ""
    if SETTOAST_RE.search(body):
        return "toast_other", ""
    if BANNER_RE.search(body):
        return "banner", ""
    if THROW_RE.search(effective):
        return "rethrow", ""
    if DEGRADE_RE.search(effective):
        return "degrade_default", ""
    if not effective:
        return "silent", "scan-ts-catch"
    if CONSOLE_RE.search(effective) and not re.search(
            r"\b(?:set|notify|alert|throw)\b", effective):
        return "console_only", "scan-console-noise"
    return "unclassified", ""


def snippet(body: str) -> str:
    one_line = " ".join(body.split())
    return one_line[:160]


def main(repo_root: str) -> None:
    root = Path(repo_root).resolve()
    entries = []
    files_scanned = 0
    catch_total = 0
    web_root = root / WEB

    for path in sorted(web_root.rglob("*")):
        if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
            continue
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if any(part in SKIP_PARTS for part in rel.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        files_scanned += 1
        for m in CATCH_RE.finditer(text):
            body, end = extract_block(text, m.end() - 1)
            catch_total += 1
            category, overlap = classify(body)
            line = text.count("\n", 0, m.start()) + 1
            entries.append({
                "file": str(rel),
                "line": line,
                "category": category,
                "overlap": overlap,
                "snippet": snippet(body),
            })

    summary = {cat: 0 for cat in CATEGORY_ORDER}
    for e in entries:
        summary[e["category"]] += 1
    by_file = {}
    for e in entries:
        key = e["file"]
        by_file.setdefault(key, {}).setdefault(e["category"], 0)
        by_file[key][e["category"]] += 1

    result = {
        "scan": "web-failure-surfacing",
        "files_scanned": files_scanned,
        "catch_blocks_total": catch_total,
        "summary_by_category": summary,
        "entries": entries,
        "entries_by_file": {
            f: by_file[f] for f in sorted(by_file)},
    }
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main(sys.argv[1])
