#!/usr/bin/env python3
r"""Scan for unreferenced static assets under assets/figs/ and web/public/.

Read-only and deterministic: given the same git tree (HEAD) the output is
identical. Nothing is deleted; no code is modified.

Reference corpus
    Every file from `git ls-files` EXCEPT paths under the scanned trees
    themselves (assets/figs/**, web/public/**) and any path under scan/
    (this report's own directory, so reruns after committing the report
    stay stable). Corpus files are searched as raw bytes.

Patterns per asset file — every pattern is matched with a leading boundary
guard (?<![A-Za-z0-9_./-]) so a short form can never match inside a longer
path pointing at a different asset (e.g. the basename `logo.png` inside
`assets/figs/logo/logo.png` does not count as a reference to
`web/public/logo.png`), plus a trailing guard (?![A-Za-z0-9_-]) that still
allows prose punctuation right after the name (`README.md.`).

    A1 rel-from-root : assets/figs/web-1.4.6+/home/home.png
    A2 figs-rel      : figs/web-1.4.6+/home/home.png           (figs only)
    A3 tree-rel      : web-1.4.6+/home/home.png                (figs only)
    B1 public-url    : /knowledge-engine-icons/llamaindex.png  (public only)
    B2 public-rel    : knowledge-engine-icons/llamaindex.png   (public only)
    C  basename      : llamaindex.png — ONLY when the basename is unique
                       across all 129 scanned assets; shared basenames
                       (e.g. 00-overview.png, OVERVIEW.png) are ambiguous
                       and never attribute a reference to one file.

A file is REFERENCED if any pattern matches any corpus file. Dynamic
construction is covered: web/components/common/ProviderIcon.tsx:88 builds
`/provider-icons/${spec.file}` from string literals (`file: "openai.svg"`)
which B1/B2/C match.

Weak signals (reported, never counted): word-boundary matches of the
basename stem, which on their own are collisions, not references.

Usage:
    python3 scan_unused_assets.py            # writes JSON + report.md
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCAN_DIR = Path(__file__).resolve().parent
FIGS_PREFIX = "assets/figs/"
PUB_PREFIX = "web/public/"
SCANNED_TREES = (FIGS_PREFIX, PUB_PREFIX)
CORPUS_EXCLUDE_PREFIXES = SCANNED_TREES + ("scan/",)
GUARD_L = rb"(?<![A-Za-z0-9_./-])"
GUARD_R = rb"(?![A-Za-z0-9_-])"
MAX_EVIDENCE_PER_PATTERN = 5


def git_ls_files() -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(REPO), "ls-files", "-z"],
        check=True, capture_output=True,
    ).stdout
    return sorted(p.decode("utf-8") for p in out.split(b"\0") if p)


def head_commit() -> str:
    return subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "HEAD"],
        check=True, capture_output=True,
    ).stdout.decode().strip()


def compile_patterns(assets: list[str]) -> dict[str, list[tuple[str, re.Pattern]]]:
    basename_counts = Counter(Path(a).name for a in assets)
    compiled: dict[str, list[tuple[str, re.Pattern]]] = {}

    def variants(name: str, raw: bytes) -> list[tuple[str, bytes]]:
        # Spaces also appear percent-encoded in Markdown/HTML references
        # (assets/figs/system/system%20architecture.png).
        out = [(name, raw)]
        if b" " in raw:
            out.append((name + "_pct20", raw.replace(b" ", b"%20")))
        return out

    for rel in assets:
        esc = re.escape
        pats: list[tuple[str, bytes]] = variants(
            "A1_rel_from_root", esc(rel.encode()))
        if rel.startswith(FIGS_PREFIX):
            pats += variants("A2_figs_rel", esc(rel[len("assets/"):].encode()))
            pats += variants("A3_tree_rel",
                             esc(rel[len(FIGS_PREFIX):].encode()))
        else:
            short = rel[len(PUB_PREFIX):].encode()
            pats += variants("B1_public_url", esc(b"/" + short))
            pats += variants("B2_public_rel", esc(short))
            pats += variants("B3_web_public_rel", esc(b"public/" + short))
        name = Path(rel).name.encode()
        if basename_counts[Path(rel).name] == 1:
            pats += variants("C_basename_unique", esc(name))
        compiled[rel] = [
            (pname, re.compile(GUARD_L + pat + GUARD_R)) for pname, pat in pats
        ]
    return compiled


def compile_stems(assets: list[str]) -> dict[str, re.Pattern]:
    return {
        rel: re.compile(rb"\b" + re.escape(Path(rel).stem.encode()) + rb"\b")
        for rel in assets
    }


def hits_in(data: bytes, rx: re.Pattern, limit: int) -> list[int]:
    return [
        data.count(b"\n", 0, m.start()) + 1
        for i, m in enumerate(rx.finditer(data))
        if i < limit
    ]


def main() -> int:
    tracked = git_ls_files()
    assets = [p for p in tracked if p.startswith(SCANNED_TREES)]
    corpus = [p for p in tracked if not p.startswith(CORPUS_EXCLUDE_PREFIXES)]

    patterns = compile_patterns(assets)
    stems = compile_stems(assets)

    hits = {rel: {} for rel in assets}
    weak = {rel: {} for rel in assets}

    for cf in corpus:
        data = (REPO / cf).read_bytes()
        for rel, pats in patterns.items():
            for pname, rx in pats:
                lines = hits_in(data, rx, MAX_EVIDENCE_PER_PATTERN)
                if lines:
                    hits[rel].setdefault(pname, {})[cf] = lines
        for rel, rx in stems.items():
            if hits[rel]:
                continue
            lines = hits_in(data, rx, 1)
            if lines:
                weak[rel][cf] = lines

    results = []
    for rel in assets:
        referenced = bool(hits[rel])
        results.append({
            "path": rel,
            "bytes": (REPO / rel).stat().st_size,
            "referenced": referenced,
            "evidence": hits[rel],
            "weak_stem_hits": {k: v for k, v in sorted(weak[rel].items())},
        })

    candidates = [r for r in results if not r["referenced"]]
    cand_bytes = sum(r["bytes"] for r in candidates)

    (SCAN_DIR / "scan_unused_assets.json").write_text(
        json.dumps({
            "head_commit": head_commit(),
            "assets_scanned": len(results),
            "corpus_files": len(corpus),
            "candidates": len(candidates),
            "candidate_bytes": cand_bytes,
            "results": results,
        }, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    n_figs = sum(1 for r in results if r["path"].startswith(FIGS_PREFIX))
    n_pub = len(results) - n_figs
    md: list[str] = []
    md.append("# Unused static assets — scan report (assets/figs + web/public)")
    md.append("")
    md.append(f"- HEAD: `{head_commit()}`")
    md.append(f"- Assets scanned: {len(results)} (assets/figs: {n_figs}, web/public: {n_pub})")
    md.append(f"- Corpus: {len(corpus)} tracked files (excl. the two scanned trees and scan/)")
    md.append(f"- Candidates: **{len(candidates)}** files, **{cand_bytes:,} bytes** "
              f"({cand_bytes / 1024 / 1024:.2f} MiB) total cleanable")
    md.append("")
    md.append("## Method (reproducible)")
    md.append("")
    md.append("`scan_unused_assets.py` (in this directory) walks `git ls-files`, then")
    md.append("searches every corpus file (tracked files outside `assets/figs/`,")
    md.append("`web/public/` and `scan/`) for the patterns below. All patterns use")
    md.append("boundary guards: a leading `(?<![A-Za-z0-9_./-])` so a short form")
    md.append("never matches inside a longer path pointing at a different asset,")
    md.append("and a trailing `(?![A-Za-z0-9_-])` that still allows prose or markup")
    md.append("punctuation right after the name (e.g. a sentence ending `README.md.`).")
    md.append("")
    md.append("| Pattern | Example |")
    md.append("| --- | --- |")
    md.append("| A1 rel-from-root | `assets/figs/web-1.4.6+/home/home.png` |")
    md.append("| A2 figs-rel | `figs/web-1.4.6+/home/home.png` |")
    md.append("| A3 tree-rel | `web-1.4.6+/home/home.png` |")
    md.append("| B1 public-url | `/knowledge-engine-icons/llamaindex.png` |")
    md.append("| B2 public-rel | `knowledge-engine-icons/llamaindex.png` |")
    md.append("| B3 web-public-rel | `public/agent-icons/README.md` |")
    md.append("| C basename-unique | `llamaindex.png` (only if unique across all scanned assets) |")
    md.append("")
    md.append("Any pattern containing a space is additionally searched percent-encoded")
    md.append("(`%20`), which is how the READMEs reference filenames with spaces")
    md.append("(e.g. `assets/figs/system/system%20architecture.png` at `README.md:667`).")
    md.append("")
    md.append("Dynamic construction is covered: `web/components/common/ProviderIcon.tsx:88`")
    md.append("builds `/provider-icons/${spec.file}` from string literals in the same file")
    md.append("(e.g. `file: \"openai.svg\"`), matched by B1/B2/C. Shared basenames such as")
    md.append("`00-overview.png` or `OVERVIEW.png` exist in several screenshot dirs, so")
    md.append("they are ambiguous: pattern C never applies to them, and a bare basename")
    md.append("match cannot make one of its siblings referenced.")
    md.append("")
    md.append("The candidate table lists each file's pattern set; \"0 hits\" means none")
    md.append("of the file's patterns matched any of the corpus files.")
    md.append("")
    md.append("Sibling references never count: the corpus excludes both scanned trees,")
    md.append("so the vendored-icon READMEs (`web/public/*/README.md`) and other")
    md.append("screenshots cannot vouch for their neighbours. Weak stem collisions are")
    md.append("recorded in `scan_unused_assets.json` but never counted as references.")
    md.append("")
    md.append("## Cleanup candidates (unreferenced)")
    md.append("")
    if candidates:
        md.append("| Path | Bytes | Judgment evidence |")
        md.append("| --- | --- | --- |")
        for r in sorted(candidates, key=lambda x: x["path"]):
            pats = ", ".join(
                ["A1", "A2", "A3"] if r["path"].startswith(FIGS_PREFIX)
                else ["A1", "B1", "B2", "B3", "C"]
            )
            ev = f"0 hits for patterns {pats} in {len(corpus)} corpus files"
            if r["weak_stem_hits"]:
                ev += "; weak stem hits (not references): " + ", ".join(
                    sorted(r["weak_stem_hits"]))
            md.append(f"| `{r['path']}` | {r['bytes']:,} | {ev} |")
    else:
        md.append("_None found._")
    md.append("")
    md.append("## False-positive exclusions")
    md.append("")
    md.append("None required by hand: every web/public icon resolves via a static")
    md.append("string literal (PROVIDER_ICONS map in `ProviderIcon.tsx`, the engine")
    md.append("map in `KnowledgeEngineIcon.tsx`, `OfficialAssetGlyph src=...` in")
    md.append("`agent-icons.tsx`), so no dynamically-only-used icon had to be")
    md.append("excluded from the candidate list. Shared-basename screenshots are")
    md.append("handled by the ambiguity rule above instead of manual overrides.")
    md.append("")
    md.append("## Notes")
    md.append("")
    md.append("- `web/public/knowledge-engine-icons/README.md` is a licensing/")
    md.append("  provenance record for the vendored engine icons (it is the only")
    md.append("  web/public candidate). Unreferenced by code, but recommend keeping")
    md.append("  it (or relocating it outside `public/`) rather than deleting.")
    md.append("- The 47 assets/figs candidates include three whole screenshot")
    md.append("  generations of the settings page that were never wired into any")
    md.append("  README: `web-1.6.12/settings/` (6 files), `web-1.6.5/settings/`")
    md.append("  (5 files) and most of `web-1.4.6+/` beyond the 27 screenshots the")
    md.append("  READMEs actually embed. This is the README staleness problem in")
    md.append("  reverse: docs keep pointing at web-1.4.6+/web-1.6.5 shots while")
    md.append("  newer captures accumulate unreferenced.")
    md.append("- Safe-delete caveat: candidates are unreferenced in this tree, but")
    md.append("  release notes under `assets/releases/` document history and were")
    md.append("  part of the corpus; nothing under `assets/releases/` references")
    md.append("  any candidate.")
    md.append("")
    md.append("## Referenced assets (not candidates)")
    md.append("")
    md.append(f"| Path | Bytes | Evidence (pattern: corpus file:lines, first {MAX_EVIDENCE_PER_PATTERN}) |")
    md.append("| --- | --- | --- |")
    for r in sorted(results, key=lambda x: x["path"]):
        if r["referenced"]:
            ev = []
            for pname, m in sorted(r["evidence"].items()):
                for cf, ls in sorted(m.items()):
                    ev.append(f"{pname}: {cf}:{','.join(map(str, ls))}")
            md.append(f"| `{r['path']}` | {r['bytes']:,} | {' \\| '.join(ev[:6])} |")
    md.append("")
    (SCAN_DIR / "report.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(f"scanned={len(results)} candidates={len(candidates)} "
          f"candidate_bytes={cand_bytes}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
