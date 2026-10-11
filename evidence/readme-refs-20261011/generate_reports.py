#!/usr/bin/env python3
"""Generate broken-and-stale.md and summary-by-batch.md from details.json.

Read-only with respect to the repository; writes only into this evidence dir.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

EVIDENCE_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVIDENCE_DIR.parent.parent

OUTDATED = "OUTDATED-DIR(web-1.4.6+)"
BATCH_ORDER = [
    "batch-0-overview",
    "batch-1-settings",
    "batch-2-chat-and-agents",
    "batch-3-writing-and-books",
    "batch-4-knowledge-and-learning",
    "batch-5-memory-and-partners",
]


def main() -> int:
    rows = json.loads((EVIDENCE_DIR / "details.json").read_text(encoding="utf-8"))
    stats = json.loads((EVIDENCE_DIR / "stats.json").read_text(encoding="utf-8"))

    # ---- repo-side figs inventory for orphan analysis ----
    figs_root = REPO_ROOT / "assets" / "figs"
    all_figs = {
        str(p.relative_to(REPO_ROOT))
        for p in figs_root.rglob("*")
        if p.is_file()
    }
    referenced_local = {r["resolved"] for r in rows if r["resolved"]}
    orphans = sorted(f for f in all_figs if f not in referenced_local)
    orphan_outdated = [f for f in orphans if f.startswith("assets/figs/web-1.4.6+")]
    refs_new = sorted(
        {(r["resolved"], r["file"]) for r in rows if "web-1.6.5" in r["resolved"] or "web-1.6.12" in r["resolved"]}
    )

    # ---- broken-and-stale.md ----
    problems = [r for r in rows if any(s in r["status"] for s in ("MISSING-FILE", "CASE-MISMATCH", "ANCHOR-MISS", "HOST-ABSOLUTE-PATH", "EMPTY-TARGET"))]
    outdated = [r for r in rows if OUTDATED in r["status"]]

    lines: list[str] = []
    lines.append("# README asset reference check — broken & outdated details")
    lines.append("")
    lines.append(f"- Scope: root `README.md` + 11 translated READMEs under `assets/README/` (repo state: origin/main @ 6cf793bd8, v1.6.14).")
    lines.append(f"- Total references scanned: {stats['total_refs']} across {stats['files']} files.")
    lines.append(f"- Broken references (missing file / case mismatch / dead anchor): **{len(problems)}**.")
    lines.append(f"- References into the outdated `assets/figs/web-1.4.6+` tree: **{len(outdated)}** ({len({r['resolved'] for r in outdated})} distinct targets, same 19 targets repeated across all 12 files).")
    lines.append("- Anchor validation is cross-checked against anchor ids in github.com's own rendered HTML; see `github-anchor-crosscheck.md`.")
    lines.append("- External http(s) URLs (1093) were not fetched; shields.io / badge / avatars are marked EXTERNAL-URL and out of scope.")
    lines.append("")
    if problems:
        lines.append("## Broken references")
        lines.append("")
        lines.append("| file:line | kind | target | resolved | status |")
        lines.append("| --- | --- | --- | --- | --- |")
        for r in problems:
            lines.append(f"| `{r['file']}:{r['line']}` | {r['kind']} | `{r['target']}` | `{r['resolved']}` | {r['status']} |")
        lines.append("")
    else:
        lines.append("## Broken references")
        lines.append("")
        lines.append("None. Every local file target exists (case-sensitive), every markdown heading anchor resolves (verified against GitHub-rendered anchors).")
        lines.append("")
    lines.append("## Outdated references (assets/figs/web-1.4.6+)")
    lines.append("")
    lines.append("Per HKUDS/DeepTutor#1262, screenshots under `web-1.4.6+` pre-date the v1.6.x UI reorganization. Status below is `OK-LOCAL+OUTDATED-DIR(web-1.4.6+)`: the file exists today but shows the outdated UI.")
    lines.append("")
    lines.append("| file:line | target (as written) | resolved | status |")
    lines.append("| --- | --- | --- | --- |")
    for r in outdated:
        lines.append(f"| `{r['file']}:{r['line']}` | `{r['target']}` | `{r['resolved']}` | {r['status']} |")
    lines.append("")
    lines.append(f"Total rows: {len(outdated)} (each of the 19 distinct legacy screenshots is referenced once per README file, 12 files).")
    (EVIDENCE_DIR / "broken-and-stale.md").write_text("\n".join(lines), encoding="utf-8")

    # ---- summary-by-batch.md ----
    by_batch: dict[str, list] = defaultdict(list)
    for r in outdated:
        by_batch[r["batch"]].append(r)

    s = []
    s.append("# Outdated reference summary by HKUDS/DeepTutor#1262 capture batch")
    s.append("")
    s.append("Outdated = reference resolves into `assets/figs/web-1.4.6+` (pre-v1.6.x UI). Neutral inventory for the #1262 capture batches; no docs were modified in this evidence branch.")
    s.append("")
    s.append("| Batch | Outdated refs | Distinct legacy targets | Files affected |")
    s.append("| --- | --- | --- | --- |")
    for b in BATCH_ORDER:
        rows_b = by_batch.get(b, [])
        s.append(f"| {b} | {len(rows_b)} | {len({r['resolved'] for r in rows_b})} | {len({r['file'] for r in rows_b})} |")
    other = [r for r in outdated if r["batch"] not in BATCH_ORDER]
    s.append(f"| unassigned | {len(other)} | {len({r['resolved'] for r in other})} | {len({r['file'] for r in other})} |")
    s.append(f"| **total** | **{len(outdated)}** | **{len({r['resolved'] for r in outdated})}** | **{len({r['file'] for r in outdated})}** |")
    s.append("")

    for b in BATCH_ORDER:
        rows_b = by_batch.get(b, [])
        s.append(f"## {b}")
        if not rows_b:
            s.append("")
            s.append("No outdated references. Batch-0 overview already uses the new `assets/figs/web-1.6.5/OVERVIEW.png` capture (landed via #1263).")
            s.append("")
            continue
        s.append("")
        uniq: dict[str, list] = {}
        for r in rows_b:
            uniq.setdefault(r["resolved"], []).append(r)
        for resolved, entries in sorted(uniq.items()):
            written = sorted({e["target"] for e in entries})
            files = sorted({e["file"] for e in entries})
            s.append(f"- `{resolved}`")
            s.append(f"  - written as: {'; '.join(f'`{w}`' for w in written)}")
            s.append(f"  - referenced by: {', '.join(f'`{f}`' for f in files)} ({len(files)} files)")
        s.append("")

    s.append("## Already-updated (new capture dirs) — context")
    s.append("")
    if refs_new:
        seen: dict[str, set] = defaultdict(set)
        for resolved, f in refs_new:
            seen[resolved].add(f)
        for resolved, files in sorted(seen.items()):
            s.append(f"- `{resolved}` referenced by {len(files)} file(s)")
    else:
        s.append("- No README references into `assets/figs/web-1.6.5/` or `assets/figs/web-1.6.12/` beyond the overview image above.")
    s.append("")
    s.append("Note: `assets/figs/web-1.6.12/settings/` (6 files) and `assets/figs/web-1.6.5/settings/` (5 files) exist on main but no README currently points at them — they align with batch-1 scope and can back the batch-1/integration replacement.")
    s.append("")
    s.append("## Unreferenced legacy captures in web-1.4.6+ (orphans, for batch planning)")
    s.append("")
    s.append(f"{len(orphan_outdated)} files under `assets/figs/web-1.4.6+` are not referenced by any README (candidates to drop or re-capture, not urgent for reference replacement):")
    s.append("")
    for f in orphan_outdated:
        s.append(f"- `{f}`")
    s.append("")
    (EVIDENCE_DIR / "summary-by-batch.md").write_text("\n".join(s), encoding="utf-8")

    print(f"problems={len(problems)} outdated={len(outdated)} orphans={len(orphan_outdated)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
