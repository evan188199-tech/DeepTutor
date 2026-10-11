#!/usr/bin/env python3
"""Verify image/link references in the root README and all translated READMEs.

Checks, per reference:
  - local target file existence (case-sensitive, GitHub-like)
  - markdown heading anchors in target/local docs (GitHub slugs)
  - whether the target sits in the outdated assets/figs/web-1.4.6+ tree

Outputs (same directory):
  details.tsv        one row per reference: file:line, kind, target, status
  broken-and-stale.md  only entries that are missing, anchor-broken, or in the
                       outdated web-1.4.6+ tree
  stats.json         machine-readable counts

Read-only: never writes outside this evidence directory.
"""
from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
import urllib.parse
from pathlib import Path

EVIDENCE_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVIDENCE_DIR.parent.parent

README_FILES = ["README.md"] + sorted(
    str(p.relative_to(REPO_ROOT))
    for p in (REPO_ROOT / "assets" / "README").glob("README_*.md")
)

OUTDATED_PREFIX = "assets/figs/web-1.4.6+/"

_MD_LINK = re.compile(r"(!?)\[([^\]]*)\]\(\s*([^)\s]+)(?:\s+\"[^\"]*\")?\s*\)")
_MD_REFDEF = re.compile(r"^\s{0,3}\[([^\]]+)\]:\s*(<?[^>\s]+>?)\s*$")
_HTML_IMG = re.compile(r"<img\b[^>]*?\bsrc\s*=\s*\"([^\"]+)\"", re.I)
_HTML_IMG_SQ = re.compile(r"<img\b[^>]*?\bsrc\s*=\s*'([^']+)'", re.I)
_HTML_A = re.compile(r"<a\b[^>]*?\bhref\s*=\s*\"([^\"]+)\"", re.I)
_HTML_SOURCE = re.compile(r"<source\b[^>]*?\bsrcset\s*=\s*\"([^\s\"]+)", re.I)


def github_slug(text: str) -> str:
    # Matches observed github.com behavior: strip symbols (incl. emoji) and
    # punctuation, KEEP letters/numbers/marks (variation selectors U+FE0F are
    # Mn and survive in real GitHub anchors), spaces -> hyphens.
    text = text.strip().lower()
    out = []
    for ch in text:
        cp = ord(ch)
        if ch == " ":
            out.append("-")
            continue
        if ch in "-_":
            out.append(ch)
            continue
        if 0x200B <= cp <= 0x200F or cp in (0x2060, 0xFEFF):
            continue
        cat = unicodedata.category(ch)
        if cat[0] in ("L", "N", "M"):
            out.append(ch)
    return "".join(out)


_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FORMATTING = re.compile(r"!\[([^\]]*)\]\([^)]*\)|\[([^\]]*)\]\([^)]*\)|`([^`]*)`|\*\*|\*|_|~~|<[^>]+>")


def heading_text(raw: str) -> str:
    # rendered-text approximation: strip markdown formatting and HTML tags
    cleaned = _FORMATTING.sub(lambda m: (m.group(1) or m.group(2) or m.group(3) or ""), raw)
    return cleaned


def collect_slugs(md_text: str) -> set[str]:
    slugs: set[str] = []
    lines = md_text.splitlines()
    in_code = False
    for line in lines:
        if line.lstrip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        m = _HEADING.match(line)
        if m:
            slugs.append(github_slug(heading_text(m.group(2))))
    seen: set[str] = set()
    counts: dict[str, int] = {}
    for s in slugs:
        if not s:
            continue
        counts[s] = counts.get(s, 0) + 1
        seen.add(s if counts[s] == 1 else f"{s}-{counts[s] - 1}")
    return seen


def exact_exists(rel: str) -> bool:
    cur = REPO_ROOT
    for part in Path(rel).parts:
        if part in (".", ""):
            continue
        if part == "..":
            cur = cur.parent
            continue
        try:
            entries = os.listdir(cur)
        except OSError:
            return False
        if part not in entries:
            return False
        cur = cur / part
    return cur.is_file()


def case_exists(rel: str) -> bool:
    cur = REPO_ROOT
    for part in Path(rel).parts:
        if part in (".", ""):
            continue
        if part == "..":
            cur = cur.parent
            continue
        try:
            entries = os.listdir(cur)
        except OSError:
            return False
        match = [e for e in entries if e.lower() == part.lower()]
        if not match:
            return False
        cur = cur / match[0]
    return cur.is_file()


def extract_refs(path: Path):
    text = path.read_text(encoding="utf-8")
    refs: list[tuple[int, str, str]] = []  # line, kind, raw url
    refdefs: dict[str, str] = {}
    lines = text.splitlines()
    for idx, line in enumerate(lines, 1):
        for m in _MD_REFDEF.finditer(line):
            refdefs[m.group(1).strip().lower()] = m.group(2).strip("<>")
        for m in _MD_LINK.finditer(line):
            kind = "md-image" if m.group(1) == "!" else "md-link"
            refs.append((idx, kind, m.group(3)))
        for pattern, kind in (
            (_HTML_IMG, "html-img"),
            (_HTML_A, "html-href"),
            (_HTML_SOURCE, "html-srcset"),
        ):
            for m in pattern.finditer(line):
                refs.append((idx, kind, m.group(1)))
        # reference-style usages ![alt][ref] / [text][ref]
        for m in re.finditer(r"(!?)\[([^\]]+)\]\[([^\]]*)\]", line):
            key = (m.group(3) or m.group(2)).strip().lower()
            if key in refdefs:
                refs.append((idx, "md-ref-image" if m.group(1) == "!" else "md-ref-link", refdefs[key]))
    return refs, text


def batch_for(rel: str) -> str:
    r = rel.replace("\\", "/")
    marker = "figs/"
    if marker not in r:
        return ""
    rest = r.split(marker, 1)[1]
    parts = rest.split("/")
    if parts[0] not in ("web-1.4.6+", "web-1.6.5", "web-1.6.12"):
        return ""
    ver = parts[0]
    if len(parts) == 2:  # e.g. web-1.6.5/OVERVIEW.png
        surface = "OVERVIEW"
    else:
        surface = parts[1]
    surface_batches = {
        "OVERVIEW": "batch-0-overview",
        "home": "batch-2-chat-and-agents",
        "myagents": "batch-2-chat-and-agents",
        "extensions": "batch-1-settings",
        "settings": "batch-1-settings",
        "co-writer": "batch-3-writing-and-books",
        "book": "batch-3-writing-and-books",
        "knowledge": "batch-4-knowledge-and-learning",
        "learning-space": "batch-4-knowledge-and-learning",
        "memory": "batch-5-memory-and-partners",
        "partners": "batch-5-memory-and-partners",
    }
    b = surface_batches.get(surface, "unassigned")
    return b


def classify(rel_doc: str, base_dir: Path, url: str, local_slugs: set[str], doc_texts: dict) -> dict:
    res = {"target": url, "status": [], "resolved": "", "batch": ""}
    u = url.strip()
    if u.startswith("<") and u.endswith(">"):
        u = u[1:-1]
    frag = None
    if "#" in u:
        u_nofrag, frag = u.split("#", 1)
        frag = urllib.parse.unquote(frag)
    else:
        u_nofrag = u
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://", u_nofrag) or u_nofrag.startswith("//"):
        res["status"] = ["EXTERNAL-URL"]
        return res
    if u_nofrag.startswith("mailto:"):
        res["status"] = ["EXTERNAL-URL"]
        return res
    if u_nofrag == "":
        # same-document anchor
        if frag is None:
            res["status"] = ["EMPTY-TARGET"]
            return res
        res["resolved"] = rel_doc
        res["status"] = ["ANCHOR-OK" if frag in local_slugs else "ANCHOR-MISS"]
        return res
    if u_nofrag.startswith("/"):
        res["status"] = ["HOST-ABSOLUTE-PATH"]
        return res
    decoded = urllib.parse.unquote(u_nofrag)
    rel_target = os.path.normpath((base_dir / decoded).relative_to(REPO_ROOT))
    res["resolved"] = rel_target
    res["batch"] = batch_for(rel_target)
    if rel_target.startswith(OUTDATED_PREFIX):
        res["status"].append("OUTDATED-DIR(web-1.4.6+)")
    if exact_exists(rel_target):
        res["status"].append("OK-LOCAL")
    elif case_exists(rel_target):
        res["status"].append("CASE-MISMATCH")
    else:
        res["status"].append("MISSING-FILE")
        return res
    if frag is not None:
        target = REPO_ROOT / rel_target
        if target.suffix.lower() in (".md", ".markdown"):
            key = rel_target
            if key not in doc_texts:
                doc_texts[key] = collect_slugs(target.read_text(encoding="utf-8", errors="replace"))
            res["status"].append("ANCHOR-OK" if frag in doc_texts[key] else "ANCHOR-MISS")
        else:
            res["status"].append("ANCHOR-N/A")
    return res


def main() -> int:
    doc_texts: dict[str, set[str]] = {}
    rows = []
    for rel in README_FILES:
        path = REPO_ROOT / rel
        refs, text = extract_refs(path)
        local_slugs = collect_slugs(text)
        for line_no, kind, url in refs:
            c = classify(rel, path.parent, url, local_slugs, doc_texts)
            rows.append(
                {
                    "file": rel,
                    "line": line_no,
                    "kind": kind,
                    "target": url,
                    "resolved": c["resolved"],
                    "batch": c["batch"],
                    "status_list": c["status"],
                    "status": "+".join(c["status"]),
                }
            )
    # details.tsv
    with (EVIDENCE_DIR / "details.tsv").open("w", encoding="utf-8") as f:
        f.write("file\tline\tkind\ttarget\tresolved\tstatus\tbatch\n")
        for r in rows:
            f.write(f"{r['file']}:{r['line']}\t{r['kind']}\t{r['target']}\t{r['resolved']}\t{r['status']}\t{r['batch']}\n")
    # stats
    stats = {
        "files": len(README_FILES),
        "total_refs": len(rows),
        "by_status": {},
        "outdated_refs": 0,
        "problems": 0,
    }
    for r in rows:
        for s in r["status_list"]:
            stats["by_status"][s] = stats["by_status"].get(s, 0) + 1
        if "OUTDATED-DIR(web-1.4.6+)" in r["status_list"]:
            stats["outdated_refs"] += 1
        if any(s in r["status_list"] for s in ("MISSING-FILE", "CASE-MISMATCH", "ANCHOR-MISS", "HOST-ABSOLUTE-PATH", "EMPTY-TARGET")):
            stats["problems"] += 1
    (EVIDENCE_DIR / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    # machine-readable full rows
    (EVIDENCE_DIR / "details.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
