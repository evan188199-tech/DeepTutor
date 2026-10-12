#!/usr/bin/env python3
"""Verify code-reference anchors in docs/ against latest origin/main.

Ground truth per anchor:
  1. resolve the claimed file (path / basename / rel-context / symbol-repo)
  2. compare claimed line content NOW vs at the docs' declared baseline
     (fe003ddce) — unchanged content => anchor still accurate
  3. moved content => relocate inside file => drifted + current path:line
  4. gone content/symbol/file => dead (+ relocation note when applicable)

Statuses: valid / drifted / dead.  A second axis records whether the anchor
was already wrong at the declared baseline (authoring-time error) or broke
after it (post-baseline drift).
"""
import csv
import json
import re
import subprocess
from pathlib import Path

WT = Path("/Users/Shared/DeepTutor/.wt-agen1837-docsanchors")
BASELINE = "fe003ddce"
DOCS = [
    "docs/INDEXING_RECOVERY.md",
    "docs/SCIENTIFIC_RESEARCH.md",
    "docs/guides/events-and-progress-chain.md",
    "docs/guides/tools-surface.md",
    "docs/plugin-platform-rfc.md",
]
BUILTIN_FILE = "deeptutor/tools/builtin/__init__.py"

BUILTIN_EXC = {
    "ValueError", "TypeError", "KeyError", "OSError", "RuntimeError",
    "ImportError", "AttributeError", "TimeoutError", "Exception",
    "HTTPException", "JSONDecodeError", "NotImplementedError", "error",
}

BASENAME_HINTS = {
    "knowledge.py": "deeptutor/api/routers/knowledge.py",
    "progress_tracker.py": "deeptutor/knowledge/progress_tracker.py",
    "progress_events.py": "deeptutor/knowledge/progress_events.py",
    "progress_broadcaster.py": "deeptutor/api/utils/progress_broadcaster.py",
    "task_log_stream.py": "deeptutor/api/utils/task_log_stream.py",
    "task_id_manager.py": "deeptutor/api/utils/task_id_manager.py",
    "event_bus.py": "deeptutor/events/event_bus.py",
    "orchestrator.py": "deeptutor/runtime/orchestrator.py",
    "lifecycle.py": "deeptutor/services/session/turns/lifecycle.py",
    "api/main.py": "deeptutor/api/main.py",
    "book.py": "deeptutor/api/routers/book.py",
    "partners.py": "deeptutor/api/routers/partners.py",
    "manager.py": "deeptutor/services/partners/manager.py",
    "mastery_path.py": "deeptutor/api/routers/mastery_path.py",
}

DEF_PATTERNS = [
    r"^\s*(?:async\s+)?def\s+{n}\b",
    r"^\s*class\s+{n}\b",
    r"^\s*{n}\s*[:=]",
    r"(?:function|const|let|var|class|interface|type)\s+{n}\b",
]


def git(*args, cwd=WT):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def read_current(path):
    p = WT / path
    if not p.is_file():
        return None
    return p.read_text(errors="replace").splitlines()


def read_baseline(path):
    r = git("show", f"{BASELINE}:{path}")
    return r.stdout.splitlines() if r.returncode == 0 else None


def repo_path_candidates(core):
    out = []
    for c in [core, f"deeptutor/{core}", f"deeptutor/tools/{core}", f"web/{core}", f"tests/{core}"]:
        if (WT / c).is_file():
            out.append(c)
    return out


class Index:
    def __init__(self):
        self.by_base = {}
        for line in git("ls-files", "--", "*.py", "*.ts", "*.tsx").stdout.splitlines():
            self.by_base.setdefault(Path(line).name, []).append(line)


IDX = Index()


def resolve_path_core(core):
    if "/" in core:
        return repo_path_candidates(core) or None
    hits = IDX.by_base.get(Path(core).name, [])
    hint = BASENAME_HINTS.get(core)
    return ([hint] if hint in hits else hits) or None


def symbol_base(label):
    lab = label.strip()
    if "." in lab:
        lab = lab.split(".")[-1]
    return lab.split(" ")[0].split("(")[0]


def find_best(lines, pattern, s, e):
    """Match lines; prefer one within [s-2, e+2], else nearest to s."""
    try:
        rx = re.compile(pattern)
    except re.error:
        return None
    hits = [i for i, ln in enumerate(lines, 1) if rx.search(ln)]
    if not hits:
        return None
    inside = [h for h in hits if s - 2 <= h <= max(e, s) + 2]
    return inside[0] if inside else min(hits, key=lambda h: abs(h - s))


def def_hits(lines, name):
    for rank, pat in enumerate(DEF_PATTERNS):
        try:
            rx = re.compile(pat.replace("{n}", re.escape(name)))
        except re.error:
            continue
        hits = [i for i, ln in enumerate(lines, 1) if rx.search(ln)]
        if hits:
            return rank, hits
    return None, []


_sym_cache = {}


def resolve_symbol(name, prefer):
    """prefer-file-first, then repo-wide by (rank, file, line)."""
    key = (name, tuple(prefer or []))
    if key in _sym_cache:
        return _sym_cache[key]
    for f in prefer or []:
        lines = read_current(f)
        if lines is None:
            continue
        rank, hits = def_hits(lines, name)
        if hits:
            res = (f, hits[0])
            _sym_cache[key] = res
            return res
    r = git("grep", "-l", "-F", name, "--", "*.py", "*.ts", "*.tsx")
    best = None
    for f in [l for l in r.stdout.splitlines() if l]:
        lines = read_current(f)
        if lines is None:
            continue
        rank, hits = def_hits(lines, name)
        if hits:
            k = (rank, f, hits[0])
            if best is None or k < best:
                best = k
    res = (best[1], best[2]) if best else None
    _sym_cache[key] = res
    return res


TOKEN = re.compile(
    r"(?P<path>[\w][\w/.\-]*\.(?:py|ts|tsx)(?::\d+(?:-\d+)?)?)"
    r"|(?P<sym>`(?P<symname>[A-Za-z_][A-Za-z0-9_]*):(?P<syms>\d+)(?:-(?P<syme>\d+))?`)"
    r"|(?P<rel>(?<![\w.]):(?P<rels>\d+)(?:-(?P<rele>\d+))?(?![\w.\]:]))"
)
BULLET_MODULE = re.compile(r"^- \*\*([\w/]+\.(?:py|ts|tsx))\b")


def build_line_context(text):
    out, section, prefer = [], "", None
    for line in text.splitlines():
        st = line.strip()
        if st.startswith("### "):
            section = st[4:]
            prefer = BUILTIN_FILE if section.startswith("4.1") else (
                None if section.startswith("4.2") else prefer)
        m = BULLET_MODULE.match(st)
        if m:
            cands = repo_path_candidates(m.group(1))
            if cands:
                prefer = cands[0]
        out.append(prefer)
    return out


def extract_anchors():
    anchors = []
    for doc in DOCS:
        text = (WT / doc).read_text()
        masked = re.sub(r"```bash.*?```", lambda m: " " * len(m.group(0)), text, flags=re.S)
        lctx = build_line_context(masked)
        starts, acc = [0], 0
        for ln in masked.splitlines(keepends=True):
            acc += len(ln)
            starts.append(acc)

        def prefer_at(off):
            li = 0
            for i, stp in enumerate(starts):
                if stp > off:
                    li = i - 1
                    break
            return lctx[max(0, min(li, len(lctx) - 1))]

        cur, seen, recent = None, set(), []

        def add(a):
            key = (a["doc"], str(a.get("file")), a.get("symbol"), a["start"], a["end"])
            if key not in seen:
                seen.add(key)
                anchors.append(a)

        def push_recent(f):
            if isinstance(f, str):
                if f in recent:
                    recent.remove(f)
                recent.insert(0, f)
                del recent[6:]

        for m in TOKEN.finditer(masked):
            pref_sec = prefer_at(m.start())
            if m.group("path"):
                tok = m.group("path")
                core, _, lineno = tok.partition(":")
                cands = resolve_path_core(core)
                cur = cands[0] if cands and len(cands) == 1 else (cands or None)
                push_recent(cur)
                if lineno:
                    s, _, e = lineno.partition("-")
                    add({"doc": doc, "anchor": tok, "kind": "path", "file": cur,
                         "start": int(s), "end": int(e or 0), "symbol": None,
                         "prefer": cands or []})
            elif m.group("sym"):
                name = m.group("symname")
                if name in BUILTIN_EXC:
                    continue
                s, e = int(m.group("syms")), int(m.group("syme") or 0)
                pref = []
                for f in [pref_sec] + recent:
                    if isinstance(f, str) and f not in pref:
                        pref.append(f)
                add({"doc": doc, "anchor": f"{name}:{s}" + (f"-{e}" if e else ""),
                     "kind": "symbol", "file": None, "start": s, "end": e,
                     "symbol": name, "prefer": pref})
                res = resolve_symbol(name, pref)
                if res:
                    cur = res[0]
                    push_recent(cur)
            else:
                if cur is None:
                    continue
                s, e = int(m.group("rels")), int(m.group("rele") or 0)
                add({"doc": doc, "anchor": f":{s}" + (f"-{e}" if e else ""),
                     "kind": "rel", "file": cur, "start": s, "end": e,
                     "symbol": None, "prefer": cur if isinstance(cur, list) else [cur]})

    # curated supplemental + existence anchors
    anchors.append({"doc": "docs/guides/tools-surface.md", "anchor": "MAX_QUESTIONS=4/MAX_OPTIONS=8:30-31",
                    "kind": "curated", "file": "deeptutor/tools/ask_user.py", "start": 30, "end": 31,
                    "symbol": "MAX_QUESTIONS", "prefer": ["deeptutor/tools/ask_user.py"]})
    anchors.append({"doc": "docs/guides/tools-surface.md", "anchor": "success=ok and exit_code==0:366",
                    "kind": "curated", "file": "deeptutor/tools/exec_tool.py", "start": 366, "end": 366,
                    "symbol": None, "prefer": ["deeptutor/tools/exec_tool.py"]})
    anchors.append({"doc": "docs/guides/tools-surface.md", "anchor": "rag ValueError raise:41",
                    "kind": "curated", "file": "deeptutor/tools/rag_tool.py", "start": 41, "end": 41,
                    "symbol": None, "prefer": ["deeptutor/tools/rag_tool.py"]})
    existence = [
        ("docs/INDEXING_RECOVERY.md", ".indexing-run.json", r"\.indexing-run\.json", "deeptutor"),
        ("docs/INDEXING_RECOVERY.md", ".progress.json", r"\.progress\.json", "deeptutor/knowledge"),
        ("docs/INDEXING_RECOVERY.md", "GET .../indexing-readiness", r"indexing-readiness", "deeptutor/api/routers"),
        ("docs/INDEXING_RECOVERY.md", "MinerU 600s/7200s limits", r"7200", "deeptutor"),
        ("docs/SCIENTIFIC_RESEARCH.md", "preprint tool", r"\"preprint\"|'preprint'|def preprint", "deeptutor"),
        ("docs/SCIENTIFIC_RESEARCH.md", "research_audit tool", r"research_audit", "deeptutor"),
        ("docs/SCIENTIFIC_RESEARCH.md", "research_lit tool", r"research_lit", "deeptutor"),
        ("docs/SCIENTIFIC_RESEARCH.md", "allow_private_network flag", r"allow_private_network", "deeptutor"),
        ("docs/plugin-platform-rfc.md", "PluginRegistry", r"class PluginRegistry", "deeptutor"),
        ("docs/plugin-platform-rfc.md", "PluginLifecycleManager", r"class PluginLifecycleManager", "deeptutor"),
        ("docs/plugin-platform-rfc.md", "deeptutor.plugin.json", r"deeptutor\.plugin\.json", "deeptutor"),
        ("docs/plugin-platform-rfc.md", "settings/plugins.json state file",
         r"get_settings_file\(\s*[\"']plugins[\"']\s*\)", "deeptutor"),
        ("docs/plugin-platform-rfc.md", "GET /api/plugins/extensions", r"plugins/extensions", "deeptutor"),
        ("docs/plugin-platform-rfc.md", "learning_echo example", r"learning_echo", "deeptutor"),
    ]
    for doc, label, rx, hint in existence:
        anchors.append({"doc": doc, "anchor": label, "kind": "existence", "file": None,
                        "start": 0, "end": 0, "symbol": label, "rx": rx, "hint": hint})
    return anchors


def classify(a):
    row = dict(a)
    row.update({"resolved_path": "", "status": "", "baseline_status": "n/a",
                "current_ref": "", "note": ""})
    s, e = a["start"], a["end"] or a["start"]

    if a["kind"] == "existence":
        rx, hint = a["rx"], a["hint"]
        r = git("grep", "-l", "-E", rx, "--", "*.py", "*.ts", "*.tsx", "*.json")
        hits = [l for l in r.stdout.splitlines() if l]
        pref = [l for l in hits if hint in l] or hits
        if pref:
            f = pref[0]
            ln = git("grep", "-n", "-E", rx, "--", f).stdout.splitlines()
            ref = ln[0] if ln else f
            parts = ref.split(":", 1)
            row["resolved_path"] = f
            row["current_ref"] = f"{f}:{parts[1].split(':', 1)[0]}" if len(parts) > 1 else f
            row["status"] = "valid"
            row["note"] = "exists in current main"
        else:
            row["status"] = "dead"
            row["note"] = "no match in current main"
        return row

    files = a["file"] if isinstance(a["file"], list) else ([a["file"]] if a["file"] else [])
    sym = a.get("symbol")
    prefer = [f for f in (a.get("prefer") or []) if isinstance(f, str)]

    if not files and sym:
        res = resolve_symbol(sym, prefer)
        if res:
            files = [res[0]]
    if not files:
        row["status"] = "dead"
        row["note"] = "file/symbol not resolvable in current main"
        return row

    f0 = files[0]

    def at(lines, n):
        return lines[n - 1].strip() if lines and 0 < n <= len(lines) else None

    # pass 1: content-equality on the resolved file, then on prefer files that
    # plausibly contain the symbol (sym anchors may name a file implicitly)
    candidates = [f0] + [f for f in prefer if f != f0]
    if sym:
        candidates = [f for f in candidates
                      if not read_current(f) or any(sym in ln for ln in read_current(f)[:0])] or candidates
    for cand in candidates:
        c_cur, c_base = read_current(cand), read_baseline(cand)
        if c_cur is None or s > len(c_cur):
            continue
        if at(c_base, s) is not None and at(c_cur, s) == at(c_base, s) and at(c_base, s):
            end_ok = e <= s or at(c_cur, e) == at(c_base, e)
            if end_ok or cand != f0:
                row["resolved_path"] = cand
                row["status"] = "valid"
                row["note"] = "claimed line content identical to baseline"
                row["baseline_status"] = "ok-at-baseline"
                return row
        if cand == f0:
            cur_lines, base_lines = c_cur, c_base
            break
    else:
        cur_lines, base_lines = read_current(f0), read_baseline(f0)

    row["resolved_path"] = f0
    if cur_lines is None:
        row["status"] = "dead"
        row["note"] = ("file deleted since baseline" if base_lines is not None
                       else "file missing in current main")
        row["baseline_status"] = ("file-missing-at-baseline" if base_lines is None
                                  else "ok-at-baseline")
        return row
    if s > len(cur_lines):
        row["status"] = "dead"
        row["note"] = f"line {s} beyond EOF ({len(cur_lines)} lines now)"
        row["baseline_status"] = ("file-missing-at-baseline" if base_lines is None
                                  else "ok-at-baseline" if s <= len(base_lines) else "claim-oob-at-baseline")
        return row

    base_at, base_end_at = at(base_lines, s), at(base_lines, e)
    cur_at, cur_end_at = at(cur_lines, s), at(cur_lines, e)
    row["baseline_status"] = ("ok-at-baseline" if base_at is not None
                              else "claim-oob-at-baseline" if base_lines is not None
                              else "file-missing-at-baseline")

    sym_line = None
    if sym:
        sym_line = find_best(cur_lines, r"\b" + re.escape(symbol_base(sym)) + r"\b", s, max(e, s))
        if sym_line is None:
            res = resolve_symbol(symbol_base(sym), prefer)
            if res:
                sym_line = res[1]
    lo, hi = s - 2, max(e, s) + 2
    sym_here = sym_line is not None and lo <= sym_line <= hi

    if base_at is None:
        if sym_here or (cur_at and cur_end_at):
            row["status"] = "valid"
            row["note"] = "structural/symbol match on current main (no baseline content at claim)"
        else:
            row["status"] = "drifted"
            row["note"] = f"claim line content now: {cur_at[:60]!r}"
        return row

    start_ok = cur_at == base_at and bool(base_at)
    end_ok = (e <= s) or (cur_end_at == base_end_at)
    if start_ok and end_ok:
        row["status"] = "valid"
        row["note"] = "claimed line content identical to baseline" + (
            "; symbol definition also in range" if sym_here else "")
        return row

    def relocate(content):
        """Neighborhood-scored relocation of a baseline line inside current file."""
        if not content:
            return None
        hits = [i for i, ln in enumerate(cur_lines, 1) if ln.strip() == content]
        if not hits:
            return None
        def score(h):
            n = 0
            for j in range(-2, 3):
                b, c = at(base_lines, s + j), at(cur_lines, h + j)
                if b is not None and b == c:
                    n += 1
            return (-n, abs(h - (sym_line or s)))
        return min(hits, key=score)

    new_start = relocate(base_at)
    if new_start:
        sug_end = new_start + (e - s) if e > s else new_start
        row["status"] = "drifted"
        row["current_ref"] = f"{f0}:{new_start}" if e <= s else f"{f0}:{new_start}-{sug_end}"
        row["note"] = f"claimed content now at line {new_start} (was {s}" + (
            f"-{e}; suggest re-checking span length)" if e > s else ")")
        return row

    if sym_line and lo <= sym_line or (sym_line and sym_line <= len(cur_lines)):
        row["status"] = "drifted"
        row["current_ref"] = f"{f0}:{sym_line}"
        row["note"] = f"claimed line content changed; documented symbol now at line {sym_line}"
        return row

    if sym:
        res = resolve_symbol(symbol_base(sym), [])
        if res:
            row["status"] = "dead"
            row["current_ref"] = f"{res[0]}:{res[1]}"
            row["note"] = f"content gone from {f0}; symbol relocated to {res[0]}:{res[1]}"
            return row
    row["status"] = "dead"
    row["note"] = f"claimed content no longer present in {f0}" + (
        f" (symbol {sym} not found)" if sym else "")
    return row


def main():
    rows = [classify(a) for a in extract_anchors()]
    outdir = Path("evidence")
    outdir.mkdir(exist_ok=True)
    cols = ["doc", "anchor", "kind", "resolved_path", "start", "end", "symbol",
            "status", "baseline_status", "current_ref", "note"]
    with open(outdir / "anchor_inventory.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    head = git("log", "-1", "--format=%H %s").stdout.strip()
    (outdir / "summary.json").write_text(json.dumps(
        {"worktree_head": head, "baseline": BASELINE,
         "total": len(rows), "status_counts": counts}, indent=1))
    print(json.dumps(counts, indent=1), "total:", len(rows))


if __name__ == "__main__":
    main()
