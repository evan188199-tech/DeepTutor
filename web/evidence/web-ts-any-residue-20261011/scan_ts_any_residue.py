#!/usr/bin/env python3
"""Scan web/ for explicit `any` usage and ts-ignore/ts-expect-error residues.

Read-only inventory. Produces inventory.json + summary.json next to this file.
Scope: tsconfig.json include set (app/components/context/contracts/features/
hooks/i18n/lib/shared/scripts/tests/types + proxy.ts) plus vendor/ (linted by
eslint but outside tsc include) plus root config files.

Precision rules:
- prose filter: `any` immediately followed by a letter (English prose such as
  ": any bad ref" or doc-comment "any authenticated user") is dropped.
- ts-directive lines are never prose-filtered.
Cause taxonomy (heuristic, reason per entry):
- vendored: vendor/ upstream code
- third-party-integration: react-markdown components/plugin maps or ambient
  d.ts declarations
- boundary: tests/scripts/contracts/proxy, or line touches IO/event/parse/
  global-stub surface
- app-bypass: everything else (in-app suppression)
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

WEB = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent

TSCONFIG_DIRS = [
    "app", "components", "context", "contracts", "features", "hooks",
    "i18n", "lib", "shared", "scripts", "tests", "types",
]
ROOT_FILES = ["proxy.ts", "playwright.config.ts", "vitest.config.mts"]

PROSE_AFTER = re.compile(r"\bany\b[ \t]*[A-Za-z_]")

RMD_KEYS = (
    "p", "h1", "h2", "h3", "h4", "h5", "h6", "strong", "em", "a", "blockquote",
    "pre", "code", "ul", "ol", "li", "table", "thead", "tbody", "tr", "th", "td",
    "input", "details", "summary", "img", "hr", "span", "section", "dl", "dt",
    "dd", "figure", "figcaption", "sup", "sub", "del", "ins",
)
RMD_KEY_RE = re.compile(
    r"^\s*(?:%s)\s*:\s*" % "|".join(RMD_KEYS)
)
RMD_CTX_RE = re.compile(r"components\s*=|remarkPlugins|rehypePlugins")
RMD_NODE_RE = re.compile(r"\(\s*(?:\{[^}]*\bnode\b[^}]*\}|node)\s*:\s*any\b")
RMD_AUX_RE = re.compile(r"ComponentType<any>|Array<any>")
AUX = re.compile(r"(?<=[,<=(=])\s*any\b")  # generic/param/default positions

FAMILIES = {
    "annot-any": re.compile(r":\s*any\b"),
    "as-any": re.compile(r"\bas\s+any\b"),
    "ts-ignore": re.compile(r"@ts-ignore\b"),
    "ts-expect-error": re.compile(r"@ts-expect-error\b"),
}

THIRD_PARTY_RE = re.compile(
    r"window\.|webkit|speechSynthesis|MediaRecorder|navigator\.|"
    r"pdfjs|epubjs|JSZip|monaco|wasm|import\(|require\(|global\.window",
    re.IGNORECASE,
)
BOUNDARY_RE = re.compile(
    r"JSON\.parse|\.json\(\)|localStorage|sessionStorage|FormData|"
    r"URLSearchParams|MessageEvent|postMessage|addEventListener|"
    r"\bevent\b|\bresponse\b|fetch\(|headers|searchParams|\bvi\.mock\b|"
    r"\bmocks\b|\bfixture\b",
)

VENDOR_PREFIX = "vendor/"


def file_imports(text: str, module: str) -> bool:
    return re.search(r'from\s+"%s"' % re.escape(module), text) is not None


def classify(rel: str, line: str, is_rmd_file: bool) -> tuple[str, str]:
    if rel.startswith(VENDOR_PREFIX):
        return "vendored", "vendored upstream source"
    if rel.startswith("types/") and rel.endswith(".d.ts"):
        return "third-party-integration", "ambient declaration file"
    if is_rmd_file and (
        RMD_KEY_RE.match(line)
        or RMD_CTX_RE.search(line)
        or RMD_NODE_RE.search(line)
    ):
        return "third-party-integration", "react-markdown components/plugin map"
    if rel.startswith(("tests/", "scripts/", "contracts/")) or rel == "proxy.ts":
        if THIRD_PARTY_RE.search(line):
            return "boundary", "test global/external stub"
        return "boundary", "tests/scripts/contracts/proxy boundary layer"
    if THIRD_PARTY_RE.search(line):
        return "third-party-integration", "line references global/external API"
    if BOUNDARY_RE.search(line):
        return "boundary", "line touches IO/event/parse boundary"
    return "app-bypass", "app-code suppression, no boundary/third-party marker"


def iter_files():
    seen = set()
    for d in TSCONFIG_DIRS:
        base = WEB / d
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file() and p.suffix in (".ts", ".tsx", ".mts"):
                seen.add(p)
    for name in ROOT_FILES:
        p = WEB / name
        if p.exists():
            seen.add(p)
    vendor = WEB / "vendor"
    if vendor.exists():
        for p in sorted(vendor.rglob("*")):
            if p.is_file() and p.suffix in (".ts", ".tsx"):
                seen.add(p)
    return sorted(seen)


def main() -> None:
    entries = []
    aux_entries = []
    dropped_prose = 0
    for p in iter_files():
        rel = str(p.relative_to(WEB))
        scope = (
            "tsconfig"
            if rel.startswith(tuple(d + "/" for d in TSCONFIG_DIRS)) or rel in ROOT_FILES
            else "outside-tsconfig"
        )
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        is_rmd = file_imports(text, "react-markdown")
        lines = text.splitlines()
        for lineno, line in enumerate(lines, start=1):
            fam_hits = [f for f, rx in FAMILIES.items() if rx.search(line)]
            stripped = line.strip()
            directive = any(f in ("ts-ignore", "ts-expect-error") for f in fam_hits)
            prose = bool(PROSE_AFTER.search(line))
            for fam in fam_hits:
                if fam in ("annot-any", "as-any") and prose and not directive:
                    dropped_prose += 1
                    continue
                cause, reason = classify(rel, line, is_rmd)
                entries.append({
                    "file": rel, "line": lineno, "family": fam,
                    "cause": cause, "reason": reason, "scope": scope,
                    "snippet": stripped[:240],
                })
            if (
                AUX.search(line)
                and not fam_hits
                and not prose
            ):
                cause, reason = classify(rel, line, is_rmd)
                if is_rmd and RMD_AUX_RE.search(line):
                    cause, reason = (
                        "third-party-integration",
                        "react-markdown components/plugin map",
                    )
                aux_entries.append({
                    "file": rel, "line": lineno, "family": "aux-any-pos",
                    "cause": cause, "reason": reason, "scope": scope,
                    "snippet": stripped[:240],
                })

    inv = {
        "generated_by": "scan_ts_any_residue.py",
        "families": list(FAMILIES) + ["aux-any-pos"],
        "dropped_prose_matches": dropped_prose,
        "notes": [
            "primary families: annot-any (`: any`), as-any (`as any`),",
            "ts-ignore, ts-expect-error; aux-any-pos = other explicit any",
            "positions (generics/defaults), secondary signal only.",
            "prose filter drops `any` followed by a letter (English text).",
            "cause labels are heuristic; per-entry reason documents the rule.",
        ],
        "primary": entries,
        "aux": aux_entries,
    }
    (OUT / "inventory.json").write_text(
        json.dumps(inv, indent=1, ensure_ascii=False), "utf-8"
    )

    def bucket(items, key):
        return dict(Counter(e[key] for e in items).most_common())

    by_dir = defaultdict(Counter)
    for e in entries:
        by_dir[e["file"].split("/")[0]][e["family"]] += 1
    files_rank = Counter(e["file"] for e in entries)

    summary = {
        "primary_total": len(entries),
        "by_family": bucket(entries, "family"),
        "by_cause": bucket(entries, "cause"),
        "by_dir": {k: dict(v.most_common()) for k, v in sorted(by_dir.items())},
        "by_file": dict(files_rank.most_common()),
        "aux_total": len(aux_entries),
        "aux_by_file": bucket(aux_entries, "file"),
    }
    (OUT / "summary.json").write_text(
        json.dumps(summary, indent=1, ensure_ascii=False), "utf-8"
    )
    print(json.dumps(
        {k: summary[k] for k in ("primary_total", "by_family", "by_cause")},
        indent=1,
    ))
    print("dropped_prose:", dropped_prose, "| files:", len(files_rank))


if __name__ == "__main__":
    main()
