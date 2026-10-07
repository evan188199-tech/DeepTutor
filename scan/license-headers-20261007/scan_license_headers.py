#!/usr/bin/env python3
"""Read-only audit of source license/SPDX header consistency vs LICENSE.

Scope rules (deterministic, reproducible):
  1. Enumerate tracked files via `git ls-files` (HEAD content, working tree must be clean).
  2. Source extensions audited: .py .ts .tsx .js .jsx .mjs .cjs .mts .cts .sh .command .bat
  3. Excluded scopes (not counted as first-party gaps):
     - web/vendor/**            vendored third-party code (third-party notices axis)
     - node_modules/**          (never tracked, defensive)
     - files detected as GENERATED (auto-generation markers in the header zone)
  4. Header zone = first 30 lines of each file (shebang/encoding lines included).
  5. Baseline = LICENSE at repo root:
     - license id derived from LICENSE text (Apache License / Version 2.0 -> Apache-2.0)
     - canonical holder + year parsed from the "Copyright ..." line in LICENSE
  6. Per-file classification:
     - SPDX_OK      SPDX-License-Identifier equals the baseline id
     - SPDX_MISMATCH  SPDX present with a different id                      (HIGH)
     - HOLDER_DRIFT copyright line with a holder that is not the canonical   (MEDIUM)
     - YEAR_DRIFT   copyright years all older than the LICENSE baseline year (MEDIUM)
     - APACHE_NOTICE  prose "Licensed under ... Apache License" without SPDX (LOW)
     - NO_HEADER    no SPDX and no copyright line                            (LOW)
     - GENERATED    generated file, header not required                      (INFO)
  7. Reporting:
     - per-directory aggregate table (top-level dir + 2nd-level component)
     - drift list: per-file only for HIGH/MEDIUM; NO_HEADER and LOW buckets
       aggregated per directory (no per-file LOW listing)

Exit code 0 always: this is an inventory, not a gate.

Usage: python3 scan_license_headers.py [--json out.json] [--md out.md]
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import subprocess
import sys
from pathlib import Path

SOURCE_EXTS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts",
    ".sh", ".command", ".bat",
}
EXCLUDED_PREFIXES = ("web/vendor/",)
HEADER_ZONE_LINES = 30
GENERATED_PATH_RE = re.compile(r"/generated/|\.generated\.|\.generated$|\.d\.ts$")
GENERATED_MARKER = re.compile(
    r"auto[- ]?generated|regenerate with|generated from|do not edit", re.I
)
COMMENT_LINE_RE = re.compile(r"^\s*(?:#|//|/\*|\*|<!--|--;)")
SPDX_RE = re.compile(r"SPDX-License-Identifier\s*:\s*([A-Za-z0-9()._+\-]+)")
COPYWORD_RE = re.compile(r"copyright", re.I)
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
LICENSED_UNDER_RE = re.compile(r"licensed\s+under", re.I)
APACHE_PROSE_RE = re.compile(r"apache\s+license", re.I)
CLEAN_HOLDER_RE = re.compile(r"[\s\-*#]+")
YEAR_DRIFT_MAX_YEAR = 2025  # baseline year from LICENSE


def git_ls_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], capture_output=True, check=True
    ).stdout
    return [p.decode("utf-8") for p in out.split(b"\x00") if p]


def parse_license_baseline(root: Path) -> dict:
    text = (root / "LICENSE").read_text(encoding="utf-8", errors="replace")
    lic_id = "UNKNOWN"
    if re.search(r"apache license\s+version 2", text, re.I):
        lic_id = "Apache-2.0"
    holder, year = None, None
    # Apache-2.0 files carry the project copyright in the appendix at the tail;
    # earlier "copyright" hits are definition prose in the license body.
    for line in reversed(text.splitlines()):
        if COPYWORD_RE.search(line) and YEAR_RE.search(line):
            year = int(YEAR_RE.search(line).group(0))
            after = re.sub(r"copyright\s*(\(c\)|©)?\s*:?", "", line, flags=re.I)
            after = re.sub(r"^\s*(19|20)\d{2}\s*", "", after)
            holder = CLEAN_HOLDER_RE.sub(" ", after).strip() or None
            break
    return {"license_id": lic_id, "holder": holder, "year": year}


def classify(path: str, root: Path, baseline: dict) -> dict:
    p = root / path
    try:
        raw = p.read_bytes()
    except OSError as exc:
        return {"path": path, "bucket": "READ_ERROR", "detail": str(exc)}
    text = raw.decode("utf-8", errors="replace")
    head_lines = text.splitlines()[:HEADER_ZONE_LINES]
    head = "\n".join(head_lines)

    spdx = SPDX_RE.search(head)
    spdx_id = spdx.group(1) if spdx else None
    copy_lines = [ln for ln in head_lines if COPYWORD_RE.search(ln)]
    years: list[int] = []
    holder = None
    for ln in copy_lines:
        years.extend(int(y) for y in YEAR_RE.findall(ln))
        if holder is None:
            after = re.sub(r"copyright\s*(\(c\)|©)?\s*:?", "", ln, flags=re.I)
            after = re.sub(r"\b(19|20)\d{2}\b", "", after)
            after = re.sub(r"^\s*(?:\(c\)|©)", "", after.strip())
            holder = CLEAN_HOLDER_RE.sub(" ", after).strip() or None

    generated_by_path = bool(GENERATED_PATH_RE.search("/" + path))
    generated_by_marker = any(
        COMMENT_LINE_RE.match(ln) and GENERATED_MARKER.search(ln)
        for ln in head_lines
    )
    if generated_by_path or generated_by_marker:
        bucket = "GENERATED"
    elif spdx and baseline["license_id"] != "UNKNOWN" and spdx_id != baseline["license_id"]:
        bucket = "SPDX_MISMATCH"
    elif spdx:
        bucket = "SPDX_OK"
    elif not copy_lines:
        bucket = "NO_HEADER"
    elif holder and canonical_holder_key(holder) != canonical_holder_key(
        baseline.get("holder") or ""
    ):
        bucket = "HOLDER_DRIFT"
    elif years and max(years) < YEAR_DRIFT_MAX_YEAR:
        bucket = "YEAR_DRIFT"
    elif APACHE_PROSE_RE.search(head) or LICENSED_UNDER_RE.search(head):
        bucket = "APACHE_NOTICE"
    else:
        bucket = "COPYRIGHT_ONLY_NO_LICENSE_REF"

    return {
        "path": path,
        "bucket": bucket,
        "spdx_id": spdx_id,
        "holder": holder,
        "years": sorted(set(years)),
    }


def canonical_holder_key(holder: str) -> str:
    h = holder.lower()
    for token in ("hkuds", "data intelligence lab", "university of hong kong", "hku"):
        if token in h:
            return "canonical"
    return re.sub(r"[^a-z0-9]+", " ", h).strip()


def dir_key(path: str) -> str:
    parts = path.split("/")
    if len(parts) == 1:
        return "(root)"
    if parts[0] in {"web", "tests"} and len(parts) > 2:
        return "/".join(parts[:2])
    return parts[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="results.json")
    ap.add_argument("--md", default="report_tables.md")
    args = ap.parse_args()

    root = Path(subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, check=True, text=True,
    ).stdout.strip())
    baseline = parse_license_baseline(root)
    files = [
        f for f in git_ls_files()
        if Path(f).suffix.lower() in SOURCE_EXTS
        or (Path(f).suffix == "" and "scripts/hooks" in f)
    ]

    records = []
    vendor_files = [f for f in files if f.startswith(EXCLUDED_PREFIXES)]
    audited = [f for f in files if not f.startswith(EXCLUDED_PREFIXES)]
    for f in audited:
        rec = classify(f, root, baseline)
        rec["dir"] = dir_key(f)
        records.append(rec)

    counts = collections.Counter(r["bucket"] for r in records)
    by_dir: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for r in records:
        by_dir[r["dir"]][r["bucket"]] += 1

    result = {
        "baseline": baseline,
        "totals": dict(counts),
        "audited_files": len(records),
        "excluded_vendor_files": len(vendor_files),
        "vendor_paths": sorted(set(f.split("/")[1] + "/" + f.split("/")[2] for f in vendor_files)),
        "records": records,
        "by_dir": {k: dict(v) for k, v in sorted(by_dir.items())},
    }
    Path(args.json).write_text(json.dumps(result, indent=1, ensure_ascii=False))

    # Markdown tables fragment (report.md assembles around this).
    order = ["SPDX_OK", "APACHE_NOTICE", "COPYRIGHT_ONLY_NO_LICENSE_REF",
             "NO_HEADER", "HOLDER_DRIFT", "YEAR_DRIFT", "SPDX_MISMATCH",
             "GENERATED", "READ_ERROR"]
    lines = ["| directory | total | " + " | ".join(order) + " |",
             "|---|---|" + "---|" * len(order)]
    for d, c in sorted(by_dir.items()):
        total = sum(c.values())
        lines.append(f"| `{d}` | {total} | " + " | ".join(str(c.get(b, 0)) for b in order) + " |")
    lines.append(f"| **TOTAL** | **{len(records)}** | "
                 + " | ".join(f"**{counts.get(b, 0)}**" for b in order) + " |")
    Path(args.md).write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps({"baseline": baseline, "totals": dict(counts),
                      "audited": len(records), "vendor_excluded": len(vendor_files)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
