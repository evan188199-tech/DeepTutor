#!/usr/bin/env python3
"""Statically extract frontend API call paths from web/.

Finds string/template literals starting with /api/, /ws, /files/ in
.ts/.tsx/.js/.jsx sources (node_modules/.next excluded). Template heads are
truncated at the first ${...}. Outputs frontend_calls.tsv:
path_head<TAB>file:line<TAB>zone
"""
import re
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]) / "web"
EXTS = {".ts", ".tsx", ".js", ".jsx", ".mts", ".mjs"}
SKIP_DIRS = {"node_modules", ".next", "coverage", ".turbo", "dist"}
PREFIXES = ("/api/", "/api", "/ws/", "/ws", "/files/")

# Match a quoted string or backtick template head beginning with our prefixes.
LIT_RE = re.compile(
    r"""(?P<q>["`])(?P<path>/api(?:/[^"'`\s\\]*)?|/ws(?:/[^"'`\s\\]*)?|/files(?:/[^"'`\s\\]*)?)"""
)


def zone_of(rel: str) -> str:
    parts = rel.split("/")
    if parts[0] == "app":
        return "app(pages+next-route-handlers)" if "/api/" in rel else "app(pages)"
    if parts[0] in {"shared", "features", "lib", "components", "hooks", "context", "contracts", "i18n", "locales", "types", "vendor", "scripts", "tests", "public"}:
        return parts[0]
    return parts[0]


def main():
    rows = []
    seen = set()
    for f in sorted(ROOT.rglob("*")):
        if not f.is_file() or f.suffix not in EXTS:
            continue
        if any(p in f.parts for p in SKIP_DIRS):
            continue
        rel = f.relative_to(ROOT).as_posix()
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for m in LIT_RE.finditer(text):
            line_start = text.rfind("\n", 0, m.start()) + 1
            leading = text[line_start:m.start()].lstrip()
            if leading.startswith(("//", "*", "/*")):
                continue  # comment mention, not a call site
            raw = m.group("path")
            # cut template heads at ${ and drop trailing fragments
            head = raw.split("${")[0]
            parametric = "${" in raw
            head = head.rstrip("/")
            if head in ("", "/api", "/ws", "/files"):
                head = raw.split("${")[0]
            line = text.count("\n", 0, m.start()) + 1
            key = (head, rel, line)
            if key in seen:
                continue
            seen.add(key)
            rows.append((head + ("\tPARAM" if parametric else ""), f"{rel}:{line}", zone_of(rel)))
    for r in sorted(rows, key=lambda x: (x[0], x[1])):
        print("\t".join(r))


if __name__ == "__main__":
    main()
