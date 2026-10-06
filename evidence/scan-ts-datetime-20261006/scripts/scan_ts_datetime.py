#!/usr/bin/env python3
"""Read-only scan of date/time handling in web/ TS/TSX.

Classifies every `new Date(...)` / `Date.parse(...)` call site and related
timezone-sensitive constructs into deterministic buckets. No file is modified.

Usage:
    python3 scan_ts_datetime.py --root <repo-root> --out <evidence-dir>

Outputs:
    <out>/data/hits.json    one record per hit, sorted by (path, line, bucket)
    <out>/data/stats.json   counts by bucket/sub-bucket + scan metadata
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

SKIP_DIRS = {"node_modules", ".next", "coverage", ".turbo"}
EXTS = {".ts", ".tsx"}
EXCLUDED_PREFIXES = ("web/tests/", "web/scripts/", "web/contracts/generated/")

RE_NEW_DATE = re.compile(r"\bnew\s+Date\s*\(")
RE_DATE_PARSE = re.compile(r"\bDate\.parse\s*\(")
RE_DATE_NOW = re.compile(r"\bDate\.now\s*\(")
RE_DATE_UTC = re.compile(r"\bDate\.UTC\s*\(")
RE_ISO_TRUNC = re.compile(r"\.toISOString\(\)\s*\.\s*(?:slice|substring|substr)\(\s*0\s*,\s*10\s*\)")
RE_TZ_OFFSET = re.compile(r"\bgetTimezoneOffset\s*\(")
RE_INTL_TZ = re.compile(r"resolvedOptions\(\)\s*\.\s*timeZone")
RE_TO_LOCALE = re.compile(r"\.toLocale(?:String|DateString|TimeString)\s*\(")
RE_TZ_OPTION = re.compile(r"timeZone\s*:")
RE_RELATIVE_FMT = re.compile(r"\bIntl\.RelativeTimeFormat\s*\(")
RE_TPL_TS = re.compile(r"`[^`]*\}T\d{2}:\d{2}(?::\d{2})?[^`]*`")
RE_DATE_ONLY_LIT = re.compile(r"^['\"]\d{4}-\d{2}-\d{2}['\"]$")
RE_DT_TZ_LIT = re.compile(r"^['\"]\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})['\"]$")
RE_DT_NO_TZ_LIT = re.compile(r"^['\"]\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?['\"]$")
RE_SLASH_LIT = re.compile(r"^['\"][^'\"]*\d{1,4}/\d{1,2}(?:/\d{1,4})?[^'\"]*['\"]$")
# identifier that looks like a timestamp/date field being compared to a quoted literal
RE_STR_CMP = re.compile(
    r"\b(?:[A-Za-z_$][\w$]*\.)?(?:[A-Za-z_$][\w$]*(?:[Aa]t|Time|time|_ts|Ts|Date|date))\s*"
    r"(?:===|!==|>=|<=|>|<)\s*['\"][^'\"]*\d[^'\"]*['\"]"
)
RE_EPOCH_DIV = re.compile(r"\.getTime\(\)\s*/\s*1000\b")
RE_HELPERS = re.compile(r"\b(?:parseKnowledgeTimestamp|formatKnowledgeTimestamp)\b")


def extract_call_arg(line: str, open_idx: int) -> str:
    """Return the argument text of a call whose '(' is at open_idx (balanced within line)."""
    depth = 0
    for i in range(open_idx, len(line)):
        ch = line[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return line[open_idx + 1 : i].strip()
    return "(multiline)"


def classify_date_call(arg: str) -> tuple[str, str]:
    """Return (bucket, sub) for a new Date/Date.parse argument."""
    a = arg.strip()
    if a == "" or a == "(multiline)":
        if a == "":
            return ("date_call", "no_arg")
        return ("date_call", "string_expr")
    if RE_DATE_ONLY_LIT.match(a):
        return ("date_call", "date_only_literal")
    if RE_DT_TZ_LIT.match(a):
        return ("date_call", "datetime_tz_literal")
    if RE_DT_NO_TZ_LIT.match(a):
        return ("date_call", "datetime_no_tz_literal")
    if RE_SLASH_LIT.match(a):
        return ("date_call", "non_iso_literal")
    if RE_DATE_UTC.search(a) or re.fullmatch(r"\d+", a) or "Date.now()" in a:
        return ("date_call", "epoch_ms")
    if "* 1000" in a or "*1000" in a:
        return ("date_call", "epoch_sec_to_ms")
    if RE_TPL_TS.search(a):
        return ("date_call", "composed_local_datetime")
    return ("date_call", "string_expr")


def scan(root: Path) -> tuple[list[dict], dict]:
    files = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix not in EXTS:
            continue
        rel = p.as_posix()
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if rel.startswith(EXCLUDED_PREFIXES):
            continue
        files.append(p)

    hits: list[dict] = []
    for path in files:
        rel = path.as_posix()
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for lineno, text in enumerate(lines, 1):
            stripped = text.strip()
            if stripped.startswith("//") or stripped.startswith("*"):
                continue
            for m in RE_NEW_DATE.finditer(text):
                arg = extract_call_arg(text, m.end() - 1)
                bucket, sub = classify_date_call(arg)
                hits.append(_hit(rel, lineno, bucket, sub, stripped))
            for m in RE_DATE_PARSE.finditer(text):
                arg = extract_call_arg(text, m.end() - 1)
                bucket, sub = classify_date_call(arg)
                hits.append(_hit(rel, lineno, "date_parse", sub, stripped))
            if RE_ISO_TRUNC.search(text):
                hits.append(_hit(rel, lineno, "iso_utc_truncate", "toISOString().slice(0,10)", stripped))
            if RE_TZ_OFFSET.search(text):
                hits.append(_hit(rel, lineno, "tz_offset_api", "getTimezoneOffset()", stripped))
            if RE_INTL_TZ.search(text):
                hits.append(_hit(rel, lineno, "intl_tz_send", "resolvedOptions().timeZone", stripped))
            if RE_TO_LOCALE.search(text):
                sub = "with_timeZone_option" if RE_TZ_OPTION.search(text) else "browser_local"
                hits.append(_hit(rel, lineno, "locale_display", sub, stripped))
            if RE_RELATIVE_FMT.search(text):
                hits.append(_hit(rel, lineno, "relative_format", "Intl.RelativeTimeFormat", stripped))
            if RE_STR_CMP.search(text):
                hits.append(_hit(rel, lineno, "string_ts_compare", "date-like id vs literal", stripped))
            if RE_EPOCH_DIV.search(text):
                hits.append(_hit(rel, lineno, "epoch_from_parse", "getTime()/1000", stripped))
            if RE_HELPERS.search(text):
                hits.append(_hit(rel, lineno, "central_helper", "knowledge-helpers", stripped))
            if RE_TPL_TS.search(text) and not RE_NEW_DATE.search(text) and not RE_DATE_PARSE.search(text):
                hits.append(_hit(rel, lineno, "composed_local_datetime", "template_no_tz", stripped))

    hits.sort(key=lambda h: (h["path"], h["line"], h["bucket"], h["sub"]))
    counts = Counter((h["bucket"], h["sub"]) for h in hits)
    stats = {
        "baseline_commit": _git_head(root),
        "files_scanned": len(files),
        "hits_total": len(hits),
        "counts": {f"{b}:{s}": c for (b, s), c in sorted(counts.items())},
    }
    return hits, stats


def _hit(path: str, line: int, bucket: str, sub: str, text: str) -> dict:
    return {"path": path, "line": line, "bucket": bucket, "sub": sub, "text": text[:300]}


def _git_head(root: Path) -> str:
    head = root / ".git"
    try:
        if head.is_file():
            gitdir = Path(head.read_text().split("gitdir:")[1].strip())
        else:
            gitdir = head
        headval = gitdir.joinpath("HEAD").read_text().strip()
        if headval.startswith("ref: "):
            common = gitdir / "commondir"
            common_dir = (gitdir / common.read_text().strip()).resolve() if common.exists() else gitdir
            ref = common_dir.joinpath(headval[5:])
            if not ref.exists():
                ref = gitdir.joinpath(headval[5:])
            headval = ref.read_text().strip() if ref.exists() else headval
        return headval[:12]
    except Exception:
        return "unknown"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="repo root containing web/")
    ap.add_argument("--out", required=True, help="evidence dir to write data/ into")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    out = Path(args.out).resolve()
    hits, stats = scan(root)
    out.joinpath("data").mkdir(parents=True, exist_ok=True)
    out.joinpath("data", "hits.json").write_text(
        json.dumps(hits, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    out.joinpath("data", "stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(f"files={stats['files_scanned']} hits={stats['hits_total']} head={stats['baseline_commit']}")
    for k, v in stats["counts"].items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
