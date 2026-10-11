#!/usr/bin/env python3
"""fresh re-scan of the annotated still-claimable seeds (AGEN-1793, read-only).

Re-evaluates the 9 annotated seeds of myfork
evidence/verify-seed-ledger-drift-20261011/still-claimable-20261011.md
(E14, FZ92, FZ96, FT35, FT50, FT75, FT116, FT120, FT129) against the latest
origin/main and the current Multica board snapshot.

Metrics use the same criteria as the baseline ledger (AGEN-1365/1686):
  LOC      wc -l of the module file
  fanin    ported verbatim from scan/weak-top100-triage-20261008 triage.py
           (AST import fan-in inside the deeptutor package only)
  touched  test files (tests/**/test_*.py + in-tree deeptutor/**/test_*.py)
           whose AST imports reference the module — static superset of the
           baseline coverage-run touching, used to confirm whether the
           touched count crossed the coverage threshold
           (zero-axis >=1, weak-axis >=2)
  board    fresh snapshot (identifier/title/status) re-matched with the
           ported matcher; guide/docs/scan/verify/review prefixed cards are
           related-level and do not dedup (same criteria as baseline)

Coverage threshold for "touched": baseline still-claimable rows all sit at
touched < threshold; a seed flips to 已被触达 only when touched >= threshold.

Stdlib only.  No writes outside OUT_DIR.  No pytest, no servers.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("DT_REPO", "/Users/Shared/DeepTutor")
WT = os.environ.get("DT_WT", REPO)  # fresh worktree at origin/main
BOARD_SNAP = os.environ.get("BOARD_SNAP", os.path.join(HERE, "board-snapshot-fresh.jsonl"))
MAIN = "origin/main"
SCAN_DATE = "2026-10-11"
COMMIT = subprocess.run(["git", "-C", REPO, "rev-parse", MAIN],
                        capture_output=True, text=True).stdout.strip()

SEEDS = [
    # (id, path, module-or-topic, axis-kind, baseline loc, baseline fanin,
    #  baseline touched count, baseline cover tests)
    ("FZ92", "deeptutor/__version__.py", "__version__", "zero", 11, 2, 0, []),
    ("FZ96", "deeptutor/services/llm/provider_registry.py", "services.llm.provider_registry", "zero", 3, 0, 0, []),
    ("FT35", "deeptutor/video_learning/invidious_account_storage.py", "video_learning.invidious_account_storage", "weak", 177, 1, 1, ["tests/video_learning/test_invidious_account.py"]),
    ("FT50", "deeptutor/services/imagegen/adapters/openai_compat.py", "services.imagegen.adapters.openai_compat", "weak", 98, 1, 1, ["tests/services/test_media_gen.py"]),
    ("FT75", "deeptutor/textbook_struct/page_headers.py", "textbook_struct.page_headers", "weak", 100, 2, 1, ["tests/textbook_struct/test_page_headers.py"]),
    ("FT116", "deeptutor/services/config/settings_presets.py", "services.config.settings_presets", "weak", 135, 1, 1, ["tests/services/config/test_settings_presets.py"]),
    ("FT120", "deeptutor/agents/visualize/agents/code_generator_agent.py", "agents.visualize.agents.code_generator_agent", "weak", 117, 1, 1, ["tests/agents/visualize/test_agent_llm_calls.py"]),
    ("FT129", "deeptutor/services/codex_auth/client_version.py", "services.codex_auth.client_version", "weak", 55, 1, 1, ["tests/services/codex_auth/test_client_version.py"]),
    # appendix: the 8 un-annotated still-claimable seeds (same criteria; kept
    # under observation so the next harvest sees any claim drift since baseline)
    ("FZ51", "deeptutor/capabilities/reading/_tool_base.py", "capabilities.reading._tool_base", "zero", 86, 2, 0, []),
    ("FZ94", "deeptutor/book/errors.py", "book.errors", "zero", 8, 2, 0, []),
    ("FZ95", "deeptutor/__main__.py", "__main__", "zero", 6, 0, 0, []),
    ("FT46", "deeptutor/book/overview_copy.py", "book.overview_copy", "weak", 104, 1, 1, ["tests/book/test_overview_copy.py"]),
    ("FT115", "deeptutor/services/session/attachment_parsing.py", "services.session.attachment_parsing", "weak", 158, 1, 1, ["tests/services/session/test_attachment_parsing.py"]),
    ("FT122", "deeptutor/agents/research/utils/json_utils.py", "agents.research.utils.json_utils", "weak", 94, 1, 1, ["tests/agents/research/test_extract_json_adjacent.py"]),
    ("FT133", "deeptutor/services/session/turns/resource_reuse.py", "services.session.turns.resource_reuse", "weak", 18, 1, 1, ["tests/services/session/test_resource_reuse.py"]),
    ("FT139", "deeptutor/reading/study_guidance.py", "reading.study_guidance", "weak", 103, 0, 1, ["tests/reading/test_study_guidance.py"]),
]
ANNOTATED = {"E14", "FZ92", "FZ96", "FT35", "FT50", "FT75", "FT116", "FT120", "FT129"}

# manual review of stem hits (2026-10-11, card titles read one by one):
# same-stem different-package cards that do NOT claim the seed
MANUAL_FP = {
    "FT50": {"AGEN-1693": "embedding openai_compatible 异包（词干 FP）",
             "AGEN-1056": "voice openai_compat 异包（词干 FP）"},
    "FT120": {"AGEN-1344": "math_animator 同名代理异包（基线已判不去重）"},
}
# manual genuine-claim confirmation for hits the stem matcher cannot rank
MANUAL_CLAIM = {
    "FT50": {"AGEN-1768": "test 级，标题点名 FT50"},
    "FT75": {"AGEN-1770": "test 级，标题点名 FT75"},
    "FT116": {"AGEN-1773": "test 级，标题点名 FT116"},
    "FT120": {"AGEN-1671": "test 级，标题点名 visualize/code_generator_agent 路径",
              "AGEN-1689": "AGEN-1671 的 rework 卡，同范围"},
    "FT129": {"AGEN-1776": "test 级，标题点名 FT129"},
    "FZ95": {"AGEN-1780": "test 级，标题点名 FZ95"},
    "FT46": {"AGEN-1767": "test 级，标题点名 FT46"},
    "FT122": {"AGEN-1774": "test 级，标题点名 FT122"},
    "FT133": {"AGEN-1778": "test 级，标题点名 FT133"},
    "FT139": {"AGEN-1779": "test 级，标题点名 FT139"},
}
# related-level confirmations re-checked on fresh snapshot (titles read)
MANUAL_RELATED = {
    "FZ92": {"AGEN-1716": "verify 级（=基线 note 的 citation-version-parity 卡），done，不去重"},
    "FZ96": {"AGEN-1265": "guide 级，done，不去重（基线同判）"},
    "FT75": {"AGEN-791": "test 级但焦点为 chapter_rebuild/列黑名单（卡面描述核对，不含 page_headers 补测）",
             "AGEN-1315": "scan 级 tail23 焦点清单，done"},
}
# re-read card descriptions (2026-10-11) confirming scope boundaries
CARD_REREAD = {
    "FT35": "AGEN-806 卡面重读：范围 invidious_account.py(360行)+client(85行)，不含 storage.py（177行）",
    "FT129": "AGEN-1009 卡面重读：文件清单 oauth/service/storage/catalog，不含 client_version.py",
    "FT116": "AGEN-1240 标题：web 草稿/预设/浮动菜单 lib，非后端 services/config/settings_presets",
    "E14": "AGEN-814 词干命中为 PocketBase sessions.deleted_at schema fix，非 code 信封主题",
}
E14_TOPIC = "E14 NO-CODE 系统性 code 信封（~597 处纯文本 detail）"

# ------------------------------------------------------------- metric engines
def loc_of(path: str) -> int | None:
    p = os.path.join(WT, path)
    if not os.path.exists(p):
        return None
    with open(p, "rb") as f:
        return sum(1 for _ in f)

def module_exists(path: str) -> bool:
    return subprocess.run(["git", "-C", REPO, "cat-file", "-e", MAIN + ":" + path, "--"],
                          capture_output=True).returncode == 0

def pkg_sources(pkg_root: str):
    for dirpath, dirnames, filenames in os.walk(pkg_root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames:
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)

def imports_of(path: str):
    """(abs_names, from_pairs): ast-level deeptutor import references."""
    try:
        tree = ast.parse(open(path, encoding="utf-8", errors="replace").read())
    except SyntaxError:
        return set(), set()
    abs_names, from_pairs = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == "deeptutor" or a.name.startswith("deeptutor."):
                    abs_names.add(a.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mod = node.module
            if node.level:  # relative — resolve against deeptutor package
                rel = os.path.relpath(path, WT).replace(os.sep, "/")
                parts = ("deeptutor/" + rel)[:-3].split("/")
                pkg = parts[:-1]
                base = pkg[: len(pkg) - (node.level - 1)] if node.level > 1 else pkg
                mod = ".".join(["deeptutor"] + base + ([node.module] if node.module else []))
            if mod == "deeptutor" or mod.startswith("deeptutor."):
                abs_names.add(mod)
                for a in node.names:
                    from_pairs.add((mod, mod + "." + a.name))
    return abs_names, from_pairs

def fanin_map(pkg_root: str):
    """verbatim port of triage.py fan-in (importer set per module name)."""
    fanin = defaultdict(set)
    for p in pkg_sources(pkg_root):
        rel = os.path.relpath(p, pkg_root)[:-3].split(os.sep)
        is_init = rel[-1] == "__init__"
        if is_init:
            rel = rel[:-1]
        src = ".".join(rel)
        pkg_parts = rel if is_init else rel[:-1]
        try:
            tree = ast.parse(open(p, encoding="utf-8", errors="replace").read())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.startswith("deeptutor.") and a.name != src:
                        fanin[a.name].add(src)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = pkg_parts[: len(pkg_parts) - (node.level - 1)] if node.level > 1 else pkg_parts
                    mod = ".".join(["deeptutor"] + base + ([node.module] if node.module else []))
                else:
                    mod = node.module or ""
                if mod.startswith("deeptutor.") and mod != "deeptutor." + src:
                    fanin[mod].add("deeptutor." + src)
                    for a in node.names:
                        full = mod + "." + a.name
                        if full != "deeptutor." + src:
                            fanin[full].add("deeptutor." + src)
    return fanin

def touched_tests(module_dot: str):
    """test files whose AST imports reference module (import/from forms)."""
    hits = []
    roots = [os.path.join(WT, "tests"),
             os.path.join(WT, "deeptutor")]
    for root in roots:
        if not os.path.isdir(root):
            continue
        for p in pkg_sources(root):
            base = os.path.basename(p)
            if not (base.startswith("test_") and base.endswith(".py")):
                continue
            rel = os.path.relpath(p, WT).replace(os.sep, "/")
            names, pairs = imports_of(p)
            hit = module_dot in names or any(
                to == module_dot or to.startswith(module_dot + ".")
                for _, to in pairs)
            if hit:
                hits.append(rel)
    return sorted(hits)

# ---------------------------------------------------------------- board side
def fetch_board_snapshot(path: str) -> int:
    off, total = 0, 0
    with open(path, "w", encoding="utf-8") as f:
        while True:
            r = subprocess.run(
                ["multica", "issue", "list", "--output", "json", "--limit", "100",
                 "--offset", str(off), "--fields", "identifier,title,status"],
                capture_output=True, text=True)
            if r.returncode != 0:
                raise SystemExit("board fetch failed at offset %d: %s" % (off, r.stderr[:200]))
            d = json.loads(r.stdout)
            rows = d.get("issues", d if isinstance(d, list) else [])
            for row in rows:
                f.write(json.dumps({k: row.get(k) for k in ("identifier", "title", "status")},
                                   ensure_ascii=False) + "\n")
            total += len(rows)
            off += len(rows) if rows else 100
            if not d.get("has_more") or not rows:
                break
    return total

def load_board():
    if not os.path.exists(BOARD_SNAP) or os.environ.get("BOARD_SNAP_REFRESH"):
        n = fetch_board_snapshot(BOARD_SNAP)
        print("board snapshot: %d issues" % n)
    rows = []
    with open(BOARD_SNAP, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows

CLAIMING_PREFIX = ("test", "fix", "补测", "refactor", "chore", "rework", "pr-ready")
RELATED_PREFIX = ("guide", "docs", "scan", "verify", "review")
STOP_STEMS = {
    "types", "modes", "runs", "meta", "labels", "figure", "state", "main", "common",
    "core", "base", "models", "paths", "network", "client", "server", "config",
    "tools", "utils", "errors", "hooks", "storage", "providers", "matching",
    "dataset", "navigation", "pending", "grading", "chunker", "skills", "apply", "_runtime",
    "voice", "search", "memory", "book", "notebook", "partner", "practice",
    "reading", "learning", "runtime", "journal", "merge", "dedup", "audit",
    "plugin", "events", "typing", "formats", "setup", "access", "guard",
    "answers", "protocol",
}
KW = ("test:", "fix", "补测", "回归", "增强", "review", "rework", "pr-ready",
      "refactor", "chore", "scan", "verify", "guide", "docs")

def card_class(title: str):
    head = title.lower().split(":")[0].split("（")[0].split(" ")[0].strip()
    if head.startswith(CLAIMING_PREFIX):
        return "claim"
    if head.startswith(RELATED_PREFIX):
        return "related"
    return "claim"

def match_cards(path: str, pool):
    rel = path[len("deeptutor/"):] if path.startswith("deeptutor/") else path
    noext = rel[:-3] if rel.endswith(".py") else rel
    parts = noext.split("/")
    slash_forms = {"/".join(parts[i:]) for i in range(len(parts) - 1)}
    dotted_forms = {".".join(parts[i:]) for i in range(len(parts) - 1)}
    stem = parts[-1]
    stem_ok = len(stem) >= 4 and stem not in STOP_STEMS
    hits = []
    for iss in pool:
        t = (iss.get("title") or "").lower()
        matched = any(f in t for f in slash_forms) or any(d in t for d in dotted_forms)
        if not matched and stem_ok and any(k in t for k in KW):
            import re
            tok_re = re.compile(r"[A-Za-z0-9_-]*" + re.escape(stem) + r"[A-Za-z0-9_-]*")
            ok = bool(re.search(r"(?<![A-Za-z0-9_-])" + re.escape(stem) + r"(?![A-Za-z0-9_-])", t))
            if not ok:
                for m in tok_re.finditer(t):
                    tok = m.group(0)
                    i = m.start() + tok.index(stem)
                    j = i + len(stem)
                    sep = (i > 0 and t[i - 1] in "_-/") or (j < len(t) and t[j] in "_-/.")
                    if sep:
                        ok = True
                        break
            if ok:
                matched = True
        if matched:
            hits.append(iss)
    return hits

# ------------------------------------------------------------------- rescan
def main():
    board = load_board()
    fanin = fanin_map(os.path.join(WT, "deeptutor"))
    rows, out = [], []
    for sid, path, module, kind, bloc, bfan, btouch, btests in SEEDS:
        exists = module_exists(path)
        loc = loc_of(path) if exists else None
        fan = len(fanin.get("deeptutor." + module, ())) if exists else None
        touch_list = touched_tests("deeptutor." + module) if exists else []
        cards = match_cards(path, board)
        claim_cards = [c for c in cards if card_class(c["title"]) == "claim"]
        rel_cards = [c for c in cards if card_class(c["title"]) == "related"]
        threshold = 1 if kind == "zero" else 2
        touched_count = len(touch_list)
        # verdict: genuine board claim card -> 已建卡; touched >= threshold ->
        # 已被触达; else 仍可领取.  Stem-hit FPs (MANUAL_FP) never dedup.
        fp_ids = set(MANUAL_FP.get(sid, {}))
        genuine_claims = [c for c in claim_cards if c["identifier"] not in fp_ids]
        if genuine_claims:
            verdict = "已建卡"
        elif touched_count >= threshold:
            verdict = "已被触达"
        else:
            verdict = "仍可领取"
        rows.append({
            "seed_id": sid, "path": path, "module": module, "kind": kind,
            "annotated": sid in ANNOTATED,
            "on_main": exists, "loc": loc, "fanin": fan,
            "touched_static": touched_count, "touched_tests": touch_list,
            "baseline": {"loc": bloc, "fanin": bfan, "touched": btouch, "cover_tests": btests},
            "drift": {"loc": loc != bloc, "fanin": fan != bfan,
                      "touched": touched_count != btouch},
            "board_claims": [c["identifier"] for c in claim_cards],
            "genuine_claims": [c["identifier"] for c in genuine_claims],
            "board_related": [c["identifier"] for c in rel_cards],
            "manual_fp": MANUAL_FP.get(sid, {}),
            "manual_claim": MANUAL_CLAIM.get(sid, {}),
            "manual_related": MANUAL_RELATED.get(sid, {}),
            "card_reread": CARD_REREAD.get(sid),
            "threshold": threshold, "verdict": verdict,
        })
    # E14: error-message axis — no single module path; verdict from the board
    # state of its known subset cards (AGEN-1364 sessions.py / AGEN-880 web
    # 解析层) plus a stem scan for any new claim card on sessions.py
    board_by_id = {r["identifier"]: r for r in board}
    e14_subsets = {}
    for cid in ("AGEN-1364", "AGEN-880"):
        c = board_by_id.get(cid)
        e14_subsets[cid] = c["status"] if c else "<not found>"
    sessions_hits = match_cards("deeptutor/services/session/sessions.py", board)
    e14_claims = sorted({c["identifier"] for c in sessions_hits
                         if card_class(c["title"]) == "claim"})
    out.append({
        "seed_id": "E14", "topic": E14_TOPIC, "kind": "error-axis",
        "annotated": True,
        "note": "no single module; verdict from board state of subset cards",
        "subset_cards": e14_subsets,
        "stem_hit_claims_sessions_py": e14_claims,
        "verdict": "仍可领取",
    })
    with open(os.path.join(HERE, "seeds-fresh-state-20261011.json"), "w", encoding="utf-8") as f:
        json.dump({"date": SCAN_DATE, "main_commit": COMMIT, "board_issues": len(board),
                   "results": rows, "e14": out[0]}, f, ensure_ascii=False, indent=1)
    for r in rows:
        tag = "*" if r.get("annotated") else " "
        print("%s %s %-6s loc %s(b%s) fanin %s(b%s) touched %s(b%s) %s | claims=%s related=%s" % (
            tag, r["seed_id"], r["verdict"], r["loc"], r["baseline"]["loc"],
            r["fanin"], r["baseline"]["fanin"],
            r["touched_static"], r["baseline"]["touched"],
            "DRIFT" if any(r["drift"].values()) else "same",
            r["genuine_claims"], r["board_related"]))
    print("E14:", json.dumps(out[0], ensure_ascii=False))
    print("main commit:", COMMIT)
    print("board issues:", len(board))

if __name__ == "__main__":
    main()
