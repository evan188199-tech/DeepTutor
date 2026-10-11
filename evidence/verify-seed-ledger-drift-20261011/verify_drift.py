#!/usr/bin/env python3
"""seed-ledger-20261010 claimable drift verification (AGEN-1686, read-only).

Re-evaluates the 131 claimable seeds of myfork evidence/seed-ledger-20261010
against (1) the current Multica board snapshot, (2) the current reserve
backlog pool, (3) latest origin/main (module existence; coverage state is
unchanged because origin/main == 6cf793bd8, the exact commit the ledger's
fresh re-scan used).

Matching semantics ported from build_ledger.py (AGEN-1365): path slash/dotted
forms -> unique stems (KW guard + DEEPER rule) -> manual overrides; claim vs
related by title head word; cancelled cards do not dedup. Title forms the
matcher cannot see (space-separated module words, description-only scopes)
are covered by MANUAL_ADDITIONS below, each justified by reading the card.

Inputs (all read-only):
  SEED_LEDGER_DIR  checkout of myfork evidence/seed-ledger-20261010 (seeds.json)
  BACKLOG_DIR      glm-reserve reserve/backlog/*.jsonl
  BOARD_SNAP       board snapshot jsonl; when absent, fetched via
                   `multica issue list --output json --limit 100 --offset N
                   --fields identifier,title,status` (paged, ~17 requests)
  DT_REPO          DeepTutor repo with origin/main fetched

Outputs (into OUT_DIR, default next to this script):
  drift-conclusions-20261011.md  131-row conclusions (<=200 lines)
  still-claimable-20261011.md    harvest list for the next round
  seeds-state-20261011.json      machine-readable per-seed verdicts
Stdlib only.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections import Counter, OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER_DIR = os.environ.get(
    "SEED_LEDGER_DIR", "/private/tmp/dt-agen1365-wt/evidence/seed-ledger-20261010")
BACKLOG_DIR = os.environ.get(
    "BACKLOG_DIR",
    "/Users/xzh/services/ai-development/multica-board-agent/glm-reserve/reserve/backlog")
REPO = os.environ.get("DT_REPO", "/Users/Shared/DeepTutor")
BOARD_SNAP = os.environ.get("BOARD_SNAP", os.path.join(HERE, "board-snapshot-20261011.jsonl"))
OUT_DIR = os.environ.get("OUT_DIR", HERE)
SNAP_DATE = "2026-10-11"
FRESH_COMMIT = "6cf793bd868ba5ecbe64722936d4be8fab5a01df"  # v1.6.14

MANUAL_ADDITIONS = {
    # seed_id -> [(card, justification)] — wording the title matcher cannot see;
    # every entry verified by reading the card's title AND description.
    "C41": [("AGEN-1305", "desc 点名 CodeBuddy HTTP provider 离线契约补测（done）")],
    "C47": [("AGEN-596", "desc 点名 markitdown 支持格式探测回归（done）"),
            ("AGEN-729", "同模块吞错修复（in_review）")],
    "C78": [("AGEN-1306", "desc 点名 LlamaIndex 向量库选择 faiss 路径")],
    "D1": [("AGEN-1447", "desc=通道契约卡 A：feishu send 抛错、恢复 manager 重试")],
    "D2": [("AGEN-1449", "desc=通道契约卡 B：mochat send 抛错并修订锁死测试")],
    "D3": [("AGEN-1451", "desc=通道契约卡 C：dingtalk 抛错+超时+StreamClient 关闭")],
    "D7": [("AGEN-1452", "desc=通道契约卡 G：stop 资源关闭与取消 await")],
    "D9": [("AGEN-1453", "desc=通道契约卡 I：zulip/msteams/weixin 事件循环阻塞")],
    "D10": [("AGEN-1497", "desc 点名 seed-ledger D10：入站幂等补齐四通道")],
    "D11": [("AGEN-1498", "desc=qq 路由缓存兜底 + wecom frame 静默丢")],
    "D12": [("AGEN-1499", "desc 点名 seed-ledger D12：六通道发送超时归一")],
    "D13": [("AGEN-1504", "desc 点名 seed-ledger D13：not-running 契约 16 通道")],
    "E13": [("AGEN-1509", "desc 点名 LANG-MIX 残留主项：后端 routers 接入 t()")],
    "E15": [("AGEN-1506", "desc=后端 routers not_found 15+ 写法统一模板（done）")],
    "FZ20": [("AGEN-736", "desc 点名 qq 通道解析契约补测")],
    "FZ27": [("AGEN-1058", "title 点名 book blocks RAG helpers 契约补测")],
    "FZ49": [("AGEN-851", "desc 点名 agents/visual_review_agent.py（100 LOC=FZ49）")],
    "FZ53": [("AGEN-1067", "desc 点名 visualize/agents/review_agent.py（75 行=FZ53）")],
    "FZ70": [("AGEN-1055", "title 点名 MCP session state 状态机补测")],
    "FZ73": [("AGEN-1061", "title 点名 runtime worker tasks 任务注册补测")],
    "FZ77": [("AGEN-1062", "title 空格形式 knowledge progress events（匹配器不可见）")],
    "FZ84": [("AGEN-967", "desc 点名 engines/formats.py（29 行）格式注册边界")],
    "FZ85": [("AGEN-996", "desc 点名 core/response_languages.py 与 response_languages 包"),
             ("AGEN-906", "desc 点名同两文件批量补测")],
    "FZ88": [("AGEN-1068", "desc 点名 turns/context_assembler.py（20 行）")],
    "FZ93": [("AGEN-996", "desc 点名 response_languages 包"),
             ("AGEN-906", "desc 点名同文件批量补测")],
    "FT1": [("AGEN-1376", "title 点名 liteparse formats 版本边界（+rework AGEN-1431）")],
    "FT39": [("AGEN-638", "desc 点名 lightrag/cache_reuse.py 继承缓存解析")],
    "FT53": [("AGEN-806", "desc 点名 invidious_account_client.py（85 行）一并覆盖")],
    "FT64": [("AGEN-791", "desc 点名 textbook_struct/chapter_rebuild.py")],
    "FT104": [("AGEN-1344", "desc 点名 math_animator/agents/code_generator_agent.py（FT120 同名异包不受影响）")],
    "FT110": [("AGEN-670", "desc 点名 services/cron/（executor/service/repository）")],
    "FT113": [("AGEN-1017", "desc 范围含 videogen adapters/ 与任务状态流转（=async_task）")],
    "FT121": [("AGEN-1644", "desc 点名 claimable FT121 concept_analysis_agent")],
    "FT124": [("AGEN-1644", "desc 点名 claimable FT124 summary_agent")],
    "FT127": [("AGEN-1644", "desc 点名 claimable FT127 concept_design_agent")],
}

# verdict notes for claim cards whose status is done (product may not be merged)
DONE_NOTE = "卡已 done；main 未前移（仍 6cf793bd8），产出未合入 main，续卡前先核验原卡产出"

# per-seed caveats surfaced during manual review, shown in the conclusions table
NOTES_EXTRA = {
    "E14": "子集卡在案（AGEN-1364 sessions.py、AGEN-880 web 解析层）；主项系统性 code 信封仍无卡",
    "FT35": "AGEN-806 覆盖 invidious_account(.py)+client，storage.py 未含",
    "FT75": "AGEN-791 称 page_headers 现有测试；领取前 fresh 复扫确认触达数",
    "FT116": "AGEN-1240 为 web lib settings-presets，非本后端模块",
    "FT120": "AGEN-1344 仅 math_animator 同名代理，visualize 侧无卡",
    "FT129": "AGEN-1009 文件清单（oauth/service/storage/catalog）不含 client_version.py",
    "FT50": "AGEN-1046 为 scan 级，不去重",
}

# ------------------------------------------------------------------ load seeds
with open(os.path.join(LEDGER_DIR, "seeds.json"), encoding="utf-8") as f:
    LEDGER = json.load(f)
SEEDS = LEDGER["seeds"]
CLAIMABLE = [s for s in SEEDS if s["state"] == "仍可建卡"]
assert len(CLAIMABLE) == 131, len(CLAIMABLE)
BY_ID = {s["seed_id"]: s for s in CLAIMABLE}

# ------------------------------------------------------------- load card pools
def fetch_board_snapshot(path: str) -> None:
    off, total = 0, 0
    with open(path, "w", encoding="utf-8") as f:
        while True:
            p = subprocess.run(
                ["multica", "issue", "list", "--output", "json", "--limit", "100",
                 "--offset", str(off), "--fields", "identifier,title,status"],
                capture_output=True, text=True)
            if p.returncode != 0:
                sys.exit("board fetch failed at offset %d: %s" % (off, p.stderr[:200]))
            d = json.loads(p.stdout)
            rows = d.get("issues", d if isinstance(d, list) else [])
            for r in rows:
                f.write(json.dumps({k: r.get(k) for k in ("identifier", "title", "status")},
                                   ensure_ascii=False) + "\n")
            total += len(rows)
            off += len(rows) if rows else 100
            if not d.get("has_more") or not rows:
                break
    print("board snapshot: %d issues" % total)

def load_board():
    if not os.path.exists(BOARD_SNAP):
        fetch_board_snapshot(BOARD_SNAP)
    rows = []
    with open(BOARD_SNAP, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows

def load_reserve():
    rows = []
    for name in sorted(os.listdir(BACKLOG_DIR)):
        if not name.endswith(".jsonl"):
            continue
        with open(os.path.join(BACKLOG_DIR, name), encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    rows.append({"identifier": r["key"], "title": r.get("title", ""),
                                 "status": "reserve", "_src": name})
    return rows

BOARD = load_board()
RESERVE = load_reserve()
BOARD_BY_ID = {r["identifier"]: r for r in BOARD}

# ------------------------------------------------- ported matching machinery
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
CLAIMING_PREFIX = ("test", "fix", "补测", "refactor", "chore", "rework", "pr-ready")
RELATED_PREFIX = ("guide", "docs", "scan", "verify", "review")

def card_class(title):
    head = re.split(r"[:：( (]", title, maxsplit=1)[0].strip().lower()
    if head.startswith(CLAIMING_PREFIX):
        return "claim"
    if head.startswith(RELATED_PREFIX):
        return "related"
    return "claim"

def stem_unique_map():
    stems = {}
    for row in SEEDS:
        path = row.get("path")
        if path:
            stem = os.path.splitext(os.path.basename(path))[0]
            stems.setdefault(stem, []).append(row["seed_id"])
    return {s for s, sids in stems.items() if len(sids) == 1}

UNIQUE_STEMS = stem_unique_map()
ALL_SEED_STEMS = {os.path.splitext(os.path.basename(r["path"]))[0]
                  for r in SEEDS if r.get("path")}
DEEPER = {}
for row in SEEDS:
    p = row.get("path")
    if not p:
        continue
    segs = p[:-3].split("/") if p.endswith(".py") else p.split("/")
    for row2 in SEEDS:
        p2 = row2.get("path")
        if not p2 or row2["seed_id"] == row["seed_id"]:
            continue
        segs2 = p2[:-3].split("/") if p2.endswith(".py") else p2.split("/")
        if len(segs2) == len(segs) + 1 and segs2[:len(segs)] == segs:
            DEEPER.setdefault(segs[-1], set()).add(segs2[-1])

def match_cards(path, pool):
    rel = path[len("deeptutor/"):] if path.startswith("deeptutor/") else path
    noext = rel[:-3] if rel.endswith(".py") else rel
    parts = noext.split("/")
    slash_forms = {"/".join(parts[i:]) for i in range(len(parts) - 1)}
    dotted_forms = {".".join(parts[i:]) for i in range(len(parts) - 1)}
    stem = parts[-1]
    stem_ok = (stem in UNIQUE_STEMS and stem not in STOP_STEMS and len(stem) >= 4)
    token_re = re.compile(r"[A-Za-z0-9_-]*" + re.escape(stem) + r"[A-Za-z0-9_-]*")
    hits = []
    for iss in pool:
        t = (iss.get("title") or "").lower()
        matched = any(f in t for f in slash_forms) or any(d in t for d in dotted_forms)
        if not matched and stem_ok and any(k in t for k in KW):
            ok = bool(re.search(r"(?<![A-Za-z0-9_-])" + re.escape(stem) + r"(?![A-Za-z0-9_-])", t))
            if not ok:
                for m in token_re.finditer(t):
                    tok = m.group(0)
                    i = m.start() + tok.index(stem)
                    j = i + len(stem)
                    sep = (i > 0 and t[i - 1] in "_-/") or (j < len(t) and t[j] in "_-/.")
                    if sep and tok not in ALL_SEED_STEMS:
                        ok = True
                        break
            if ok and stem in DEEPER:
                for dl in DEEPER[stem]:
                    if re.search(re.escape(stem) + r"/" + re.escape(dl) + r"\b", t):
                        ok = False
                        break
            if ok:
                matched = True
        if matched:
            hits.append(iss)
    return hits

def module_exists_on_main(path):
    return subprocess.run(["git", "-C", REPO, "cat-file", "-e",
                           "origin/main:" + path, "--"],
                          capture_output=True).returncode == 0

# ------------------------------------------------------------------- verdicts
results = []
for seed in CLAIMABLE:
    sid = seed["seed_id"]
    out = OrderedDict(seed_id=sid, axis=seed["axis"], ledger_state="仍可建卡",
                      verdict="仍可领取", board_claims=[], board_related=[],
                      reserve_claims=[], notes=[])
    path = seed.get("path")
    on_main = module_exists_on_main(path) if path else None
    if path:
        for iss in match_cards(path, BOARD):
            tgt = out["board_claims"] if card_class(iss["title"]) == "claim" else out["board_related"]
            tgt.append({"id": iss["identifier"], "title": iss["title"], "status": iss["status"]})
        for iss in match_cards(path, RESERVE):
            tgt = out["reserve_claims"] if card_class(iss["title"]) == "claim" else out["board_related"]
            out["reserve_claims" if tgt is out["reserve_claims"] else "board_related"].append(
                {"id": iss["identifier"], "title": iss["title"], "status": "reserve", "src": iss["_src"]})
    for card, why in MANUAL_ADDITIONS.get(sid, []):
        b = BOARD_BY_ID.get(card)
        if b and b["status"] != "cancelled" and all(c["id"] != card for c in out["board_claims"]):
            out["board_claims"].append({"id": card, "title": b["title"], "status": b["status"],
                                        "why": why, "manual": True})
    live = [c for c in out["board_claims"] if c["status"] != "cancelled"]
    done = [c for c in live if c["status"] == "done"]
    if on_main is False:
        out["verdict"] = "主题被覆盖"
        out["notes"].append("模块已不在 origin/main")
    elif live or out["reserve_claims"]:
        out["verdict"] = "已建卡"
        if done:
            out["notes"].append(DONE_NOTE + "（" + ",".join(c["id"] for c in done) + "）")
        if out["board_related"]:
            out["notes"].append("相关卡：" + ",".join(
                c["id"] + ("(储备)" if c.get("src") else "") for c in out["board_related"]))
    else:
        out["verdict"] = "仍可领取"
        if out["board_related"]:
            out["notes"].append("仅相关卡（不构成领取去重）：" +
                                ",".join(c["id"] + ("(储备)" if c.get("src") else "")
                                         for c in out["board_related"]))
    if sid in NOTES_EXTRA:
        out["notes"].append(NOTES_EXTRA[sid])
    if on_main is not None:
        out["module_on_main"] = on_main
    results.append(out)

carded = [r for r in results if r["verdict"] == "已建卡"]
covered = [r for r in results if r["verdict"] == "主题被覆盖"]
still = [r for r in results if r["verdict"] == "仍可领取"]
assert len(carded) + len(covered) + len(still) == 131

# -------------------------------------------------------------------- outputs
def esc(s):
    return str(s).replace("|", "/").replace("\n", " ")

def topic(r):
    seed = BY_ID[r["seed_id"]]
    if seed.get("module"):
        return "`%s`" % seed["module"]
    if seed["axis"].startswith("D:"):
        return esc(seed["tag"] + " " + seed["title"])
    return esc("#%d %s" % (seed["rank"], seed["title"]))

def ev(r):
    parts = ["%s(%s)" % (c["id"], c["status"]) for c in r["board_claims"]]
    parts += ["%s(储备)" % c["id"] for c in r["reserve_claims"]]
    return "、".join(parts) if parts else "-"

L = []
L.append("# seed-ledger-20261010 可领取种子漂移复核（AGEN-1686，%s）" % SNAP_DATE)
L.append("")
L.append("- 输入：myfork `evidence/seed-ledger-20261010`（131 条 claimable）＋当日看板快照 %d 张＋储备池 %d 张＋`origin/main %s`（与台账 fresh 复扫同一 commit，main 侧覆盖状态不变）" % (len(BOARD), len(RESERVE), FRESH_COMMIT[:9]))
L.append("- 口径：**已建卡**=看板或储备池存在指向该种子的非取消卡（含人工复核补配，依据=卡 key＋描述核对）；**主题被覆盖**=模块已不在 main；**仍可领取**=两者皆无（仅 guide/docs/scan/verify/review 相关卡不去重）")
L.append("- 汇总：131 = 已建卡 **%d** + 主题被覆盖 **%d** + 仍可领取 **%d**" % (len(carded), len(covered), len(still)))
L.append("- 轴分布（仍可领取）：E=%d，D=%d，C=%d，F=%d" % (
    sum(1 for r in still if r["axis"].startswith("E")),
    sum(1 for r in still if r["axis"].startswith("D")),
    sum(1 for r in still if r["axis"].startswith("C")),
    sum(1 for r in still if r["axis"].startswith("F"))))
manual_decisive = [r for r in results if any(c.get("manual") for c in r["board_claims"])
                   and not r["reserve_claims"]
                   and not [c for c in r["board_claims"] if not c.get("manual")]]
L.append("- 人工复核补配：据此改判 %d 个种子（另为 FZ77 补上看板卡证据），共 %d 张卡；标题空格形式/描述点名/批量卡 scope，逐条读卡核对，理由见 seeds-state-20261011.json 的 why 字段" % (
    len(manual_decisive), sum(len(v) for v in MANUAL_ADDITIONS.values())))
L.append("")
L.append("| ID | 主题 | 结论 | 依据（卡 状态） | 备注 |")
L.append("|---|---|---|---|---|")
for r in results:
    L.append("| %s | %s | %s | %s | %s |" % (
        r["seed_id"], topic(r), r["verdict"], esc(ev(r)), esc("；".join(r["notes"])) or "-"))
L.append("")
L.append("## 复核命令")
L.append("")
L.append("```bash")
L.append("# 1) 看板快照（约 17 页）")
L.append("python3 evidence/verify-seed-ledger-drift-20261011/verify_drift.py  # 缺快照时自动经 multica issue list 拉取")
L.append("# 2) 校验产物")
L.append("shasum -a 256 -c evidence/verify-seed-ledger-drift-20261011/SHA256SUMS")
L.append("# 3) main 侧覆盖不变的依据：origin/main 与台账 fresh 扫描为同一 commit")
L.append("git -C /Users/Shared/DeepTutor rev-parse origin/main   # 6cf793bd868ba…=台账 FRESH_COMMIT")
L.append("```")
L.append("")
report = "\n".join(L) + "\n"
assert len(report.splitlines()) <= 200, len(report.splitlines())

S = []
S.append("# 仍可领取种子清单（still-claimable %s）" % SNAP_DATE)
S.append("")
S.append("口径：drift-conclusions-20261011.md 中结论为「仍可领取」的种子，共 %d 条，供下轮 harvest 直接取用；领卡前按当日看板再做一次快照复核。" % len(still))
S.append("")
S.append("| ID | 轴 | 模块/主题 | LOC | fanin | 测试焦点/备注 |")
S.append("|---|---|---|---:|---:|---|")
for r in still:
    seed = BY_ID[r["seed_id"]]
    focus = seed.get("focus") or ("★AGEN-1315 焦点见 seed-ledger.md" if seed.get("in_tail23") else "")
    note_bits = []
    if r["board_related"]:
        note_bits.append("相关卡（不去重）：" + ",".join(c["id"] for c in r["board_related"]))
    if r["seed_id"] == "E14":
        note_bits.append("子集卡在案（AGEN-1364 sessions.py、AGEN-880 web 解析层），主项系统性 code 信封仍无卡")
    if r["seed_id"] == "FT75":
        note_bits.append("AGEN-791 称 page_headers 现有测试，领取前 fresh 复扫确认触达数")
    if r["seed_id"] == "FT116":
        note_bits.append("AGEN-1240 为 web lib settings-presets，非本后端模块")
    if r["seed_id"] == "FT129":
        note_bits.append("AGEN-1009 文件清单（oauth/service/storage/catalog）不含 client_version.py")
    if r["seed_id"] == "FT120":
        note_bits.append("AGEN-1344 仅 math_animator 同名代理，visualize 侧无卡")
    if r["seed_id"] == "FT35":
        note_bits.append("AGEN-806 覆盖 invidious_account(.py)+client，storage.py 未含")
    if r["seed_id"] in ("FZ92", "FZ96", "FT50"):
        note_bits.append("仅有 guide/scan/verify 级相关卡，不构成去重")
    notes = "；".join(note_bits)
    S.append("| %s | %s | %s | %s | %s | %s |" % (
        r["seed_id"], r["axis"].split(":")[0],
        "`%s`" % seed["module"] if seed.get("module") else esc(topic(r)),
        seed.get("loc", "-"), seed.get("fanin", "-"),
        esc("；".join(x for x in (focus, notes) if x)) or "-"))
S.append("")
still_md = "\n".join(S) + "\n"

json_out = {
    "date": SNAP_DATE,
    "ledger": "myfork:evidence/seed-ledger-20261010 (131 claimable)",
    "main_commit": FRESH_COMMIT,
    "board_snapshot": {"issues": len(BOARD), "date": SNAP_DATE},
    "reserve_pool": {"cards": len(RESERVE), "dir": BACKLOG_DIR},
    "totals": {"carded": len(carded), "topic_covered": len(covered),
               "still_claimable": len(still)},
    "per_axis_still_claimable": dict(Counter(r["axis"].split(":")[0] for r in still)),
    "manual_additions": {k: v for k, v in MANUAL_ADDITIONS.items()},
    "results": results,
}

os.makedirs(OUT_DIR, exist_ok=True)
with open(os.path.join(OUT_DIR, "drift-conclusions-20261011.md"), "w", encoding="utf-8") as f:
    f.write(report)
with open(os.path.join(OUT_DIR, "still-claimable-20261011.md"), "w", encoding="utf-8") as f:
    f.write(still_md)
with open(os.path.join(OUT_DIR, "seeds-state-20261011.json"), "w", encoding="utf-8") as f:
    json.dump(json_out, f, ensure_ascii=False, indent=1)

print("verdicts: carded=%d topic_covered=%d still_claimable=%d" % (len(carded), len(covered), len(still)))
print("still:", " ".join(r["seed_id"] for r in still))
print("report lines:", len(report.splitlines()))
