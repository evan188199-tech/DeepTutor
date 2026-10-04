#!/usr/bin/env python3
"""Collect web (TS/JS) package imports via regex.

Outputs raw/web_imports.json:
  files: [{path, imports: [{pkg, line, dynamic, require, static}]}]
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
WEB = ROOT / "web"
EXCLUDE_DIRS = {"node_modules", ".next", "coverage", "test-results", "playwright-report", ".turbo", "dist", "build", "vendor"}
EXTS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"}

PAT_FROM = re.compile(r"""\bfrom\s*['"]([^'"\n]+)['"]""")
PAT_IMPORT = re.compile(r"""\bimport\s*['"]([^'"\n]+)['"]""")
PAT_DYNAMIC = re.compile(r"""\bimport\(\s*['"]([^'"\n]+)['"]""")
PAT_REQUIRE = re.compile(r"""\brequire\(\s*['"]([^'"\n]+)['"]""")

ASSET_EXT = re.compile(r"""\.(css|scss|sass|less|png|jpe?g|gif|svg|webp|ico|woff2?|ttf|eot|mp4|webm|mp3|wasm|jsonc|vue|md|txt|csv|yaml|yml|node|pdf|wasm)$""", re.I)

SPEC_OK = re.compile(r"""^(@[A-Za-z0-9][A-Za-z0-9._-]*/)?[A-Za-z][A-Za-z0-9._/-]*$""")


def is_external(spec):
    if spec.startswith(("./", "../", "~/", "@/", "#")) or spec in (".", ".."):
        return False
    if spec.startswith("node:"):
        return False
    if ASSET_EXT.search(spec.split("?")[0]):
        return False
    return bool(SPEC_OK.match(spec)) and " " not in spec


def pkg_root(spec):
    if spec.startswith("@"):
        return "/".join(spec.split("/")[:2])
    return spec.split("/")[0]


def collect():
    files = []
    for p in sorted(WEB.rglob("*")):
        if not p.is_file() or p.suffix not in EXTS:
            continue
        parts = set(p.relative_to(WEB).parts)
        if parts & EXCLUDE_DIRS:
            continue
        rel = "web/" + str(p.relative_to(WEB))
        text = p.read_text(encoding="utf-8", errors="replace")
        found = {}
        lines = text.splitlines()

        def add(spec, kind, lineno):
            if not is_external(spec):
                return
            root = pkg_root(spec)
            rec = found.setdefault(root, {"pkg": root, "lines": set(), "dynamic": set(), "require": set(), "static": set()})
            rec["lines"].add(lineno)
            rec[kind].add(lineno)

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith(("//", "*", "/*")):
                continue  # comment prose like 'from "thinking" to "answered"'
            for m in PAT_FROM.finditer(line):
                add(m.group(1), "static", i)
            for m in PAT_IMPORT.finditer(line):
                add(m.group(1), "static", i)
            for m in PAT_DYNAMIC.finditer(line):
                add(m.group(1), "dynamic", i)
            for m in PAT_REQUIRE.finditer(line):
                add(m.group(1), "require", i)
        if found:
            files.append({"path": rel, "imports": [
                {"pkg": r["pkg"], "lines": sorted(r["lines"]),
                 "dynamic": sorted(r["dynamic"]), "require": sorted(r["require"]), "static": sorted(r["static"])}
                for r in sorted(found.values(), key=lambda x: x["pkg"])
            ]})
    return {"files": files}


if __name__ == "__main__":
    out = ROOT / "evidence/scan-deps-20261004/raw/web_imports.json"
    out.write_text(json.dumps(collect(), indent=1, ensure_ascii=False))
    print(f"wrote {out}")
