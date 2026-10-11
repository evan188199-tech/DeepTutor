#!/usr/bin/env python3
"""Cross-check computed heading slugs against GitHub's rendered anchors.

Reads GitHub-rendered HTML (fetched via `gh api repos/HKUDS/DeepTutor/contents/<path>`
with Accept: application/vnd.github.html) from the render_*.html files and the
computed slug sets from verify_refs.collect_slugs, and reports per-file deltas.
Writes github-anchor-crosscheck.md in this directory.
"""
from __future__ import annotations

import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_refs import REPO_ROOT, README_FILES, collect_slugs  # noqa: E402

EVIDENCE_DIR = Path(__file__).resolve().parent
RENDER_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else EVIDENCE_DIR / "rendered-html"
_ID = re.compile(r'user-content-([^"\s<]+)')


def gh_anchors(path_key: str) -> set[str]:
    raw = (RENDER_DIR / f"render_{path_key}.html").read_text(encoding="utf-8")
    return {html.unescape(m) for m in _ID.findall(raw)}


def main() -> int:
    lines = ["# GitHub anchor cross-check", "",
             "Computed GitHub-style slugs (verify_refs.github_slug) vs. anchor ids in",
             "github.com's own rendered HTML for the same files (origin/main @ 6cf793bd8).",
             ""]
    all_ok = True
    for rel in README_FILES:
        key = rel.replace("/", "_")
        computed = collect_slugs((REPO_ROOT / rel).read_text(encoding="utf-8"))
        truth = gh_anchors(key)
        missing = truth - computed  # anchor GitHub has, we did not compute
        extra = computed - truth  # we computed, GitHub's render lacks
        status = "MATCH" if not missing and not extra else "DELTA"
        if missing or extra:
            all_ok = False
        lines.append(f"## {rel} — {status} (computed {len(computed)}, github {len(truth)})")
        for m in sorted(missing):
            lines.append(f"- github-only: `{m}`")
        for e in sorted(extra):
            lines.append(f"- computed-only: `{e}`")
        lines.append("")
    lines.append(f"Overall: {'ALL MATCH' if all_ok else 'DELTAS PRESENT (review above)'}")
    (EVIDENCE_DIR / "github-anchor-crosscheck.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[-1:]))
    for l in lines:
        if "DELTA" in l or "github-only" in l or "computed-only" in l:
            print(l)
    return 0


if __name__ == "__main__":
    sys.exit(main())
