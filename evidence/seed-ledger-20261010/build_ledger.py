#!/usr/bin/env python3
"""Cross-report seed ledger builder (AGEN-1365, read-only).

Consolidates the executable seeds published by six scan reports into one
tri-state ledger (已建卡 / 已被main测试覆盖 / 仍可建卡) and a claimable list
for the next harvest round.

Inputs (all under inputs/, provenance in README.md):
  baseline-summary-f07029cf.json   coverage-gaps-20261007 summary (zero96/weak100 @ v1.6.13)
  baseline-weak242-rows.json       triage.py rerun rows (full weak242 @ v1.6.13, incl. DONE map)
  rerun-main-6cf793bd8-coverage.json  distilled fresh per-seed coverage (@ v1.6.14)
  rerun-main-6cf793bd8-cli.json    cli zero rerun (@ v1.6.14)  [cli_zero_fresh.json]
  rerun-main-6cf793bd8-cmdcov.json cli command coverage (@ v1.6.14) [cmd_cov_fresh.json]
  tail-triage-23.json              AGEN-1315 weak242 tail seeds (23, fanin>=2)
  backlog-keys-20261010.jsonl      Multica board snapshot (identifier/title/status)

Outputs: seed-ledger.md, claimable-seeds.md, seeds.json (written next to this file).
Stdlib only. Read-only over the repo tree.
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
IN = os.path.join(HERE, "inputs")

BASELINE_COMMIT = "f07029cfcf2c8dfccdb671cdfc343db8334f5741"  # v1.6.13
FRESH_COMMIT = "6cf793bd868ba5ecbe64722936d4be8fab5a01df"      # v1.6.14
LEDGER_DATE = "2026-10-10"

# ---------------------------------------------------------------- load inputs

def load_json(name):
    with open(os.path.join(IN, name), encoding="utf-8") as f:
        return json.load(f)

baseline_summary = load_json("baseline-summary-f07029cf.json")
baseline_rows = load_json("baseline-weak242-rows.json")["rows"]
fresh_cov = load_json("rerun-main-6cf793bd8-coverage.json")
fresh_cli = load_json("rerun-main-6cf793bd8-cli.json")
fresh_cmdcov = load_json("rerun-main-6cf793bd8-cmdcov.json")
tail23 = load_json("tail-triage-23.json")

issues = []
with open(os.path.join(IN, "backlog-keys-20261010.jsonl"), encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            issues.append(json.loads(line))
issues.sort(key=lambda r: int(r["identifier"].split("-")[1]))

fresh_by_module = {s["module"]: s for s in fresh_cov["seeds"] if s.get("path")}
fresh_cli_by_path = {m["path"]: m for m in fresh_cli["modules"]}
cmdcov_by_name = {m["module"]: m for m in fresh_cmdcov["modules"]}

baseline_zero = baseline_summary["zero_top200"]           # 96
baseline_weak_all = baseline_rows                          # 242, triage order
baseline_weak_top100 = baseline_weak_all[:100]
baseline_weak_tail = baseline_weak_all[100:]
tail23_mods = {r["module"] for r in tail23["rows"]}
tail23_by_module = {r["module"]: r for r in tail23["rows"]}

# ------------------------------------------------------------------ seed axes

SEED_ID = {}          # seed_id -> row dict (all axes)
ORDER = []            # ordered seed ids

def add_seed(sid, axis, **kw):
    kw["seed_id"] = sid
    kw["axis"] = axis
    assert sid not in SEED_ID, sid
    SEED_ID[sid] = kw
    ORDER.append(sid)
    return kw

# Axis A: todo-sweep-20261009 -> 0 seeds (2 noise hits, report says 不建卡).
AXIS_A = {"report": "scan/todo-sweep-20261009", "seeds": 0,
          "note": "内联 TODO/FIXME 清点：命中 2 处均为陈旧 docstring 噪音，报告结论 0 种子"}

# Axis B: cli-zero-triage-20261009 -> 6 seeds (published order).
CLI_SEEDS = [
    ("deeptutor_cli/notebook.py", "notebook", "list/create/show/remove-record"),
    ("deeptutor_cli/partner.py", "partner", "list/start/stop/create"),
    ("deeptutor_cli/session_cmd.py", "session", "show/open/delete/rename"),
    ("deeptutor_cli/_tool_result.py", "_tool_result", "ToolResultBuffer/ToolResultEntry/truncate_for_display"),
    ("deeptutor_cli/book.py", "book", "list/health/refresh-fingerprints"),
    ("deeptutor_cli/memory.py", "memory", "show/clear"),
]
CLI_CARDS = {
    "deeptutor_cli/notebook.py": ["AGEN-1368"],
    "deeptutor_cli/partner.py": ["AGEN-1369"],
    "deeptutor_cli/session_cmd.py": ["AGEN-1370"],
    "deeptutor_cli/_tool_result.py": ["AGEN-1371"],
    "deeptutor_cli/book.py": ["AGEN-1372"],
    "deeptutor_cli/memory.py": ["AGEN-1373"],
}
for i, (path, grp, cmds) in enumerate(CLI_SEEDS, 1):
    add_seed(f"B{i}", "B:cli-zero-triage-20261009", path=path, group=grp, cmds=cmds)

# Axis C: weak-triage-20261008 top100 (triage order = score order).
for i, r in enumerate(baseline_weak_top100, 1):
    add_seed(f"C{i}", "C:weak-triage-20261008", module=r["module"], path=r["path"],
             loc=r["loc"], fanin=r["fanin"], score=r["score"], risk=r["risk"],
             focus=r["focus"], triage_done=list(r["done"] or []), drift=r["drift"], rank=i)

# Axis D: channel-contracts-20261005 cards A-M (manual mapping, curated).
AXIS_D = [
    ("D1", "A", "P0", "feishu send 抛错语义", "feishu.py:2322-2323 send 吞一切，manager 重试失效",
     [], "AGEN-262 为卡片正文/视频域，非 send 契约"),
    ("D2", "B", "P0", "mochat send 抛错语义", "mochat.py:409-410 吞一切；需同步改 test_send_failure_does_not_raise",
     [], "AGEN-690/694 为解析/生命周期测试卡，不含 send 契约修复"),
    ("D3", "C", "P0+P1", "dingtalk 投递与资源", "send 失败 raise + client 超时 + stop 关闭 SDK StreamClient",
     [], "AGEN-735 为解析/签名测试卡，不含本修复"),
    ("D4", "D", "P0", "zulip send API 错误抛出", "zulip.py:749-750/783-785 改 raise，修正注释矛盾",
     ["AGEN-821"], ""),
    ("D5", "E", "P1", "BaseChannel 双重启动防护", "base 层收敛 16 通道二次 start 泄漏",
     ["AGEN-1131"], ""),
    ("D6", "F", "P0", "weixin stop 守卫与死字段", "未 start 过不 _save_state；删 _poll_task 死字段",
     ["AGEN-820"], "修复未落 main（6cf793bd8 weixin.py stop 仍无条件 _save_state）"),
    ("D7", "G", "P1", "stop 清理补全", "feishu lark Client/流缓冲、slack web client、telegram/mochat/dingtalk/discord/zulip 取消 await",
     [], "AGEN-493 仅吞错收口（且未落 main），本卡范围为其遗留"),
    ("D8", "H", "P0", "discord send_delta _stream_id 键控", "discord.py:68/199-222 违反 base.py:178",
     ["AGEN-821", "AGEN-954"], ""),
    ("D9", "I", "P1", "事件循环阻塞治理", "zulip 鉴权/deregister+join、msteams shutdown/join、weixin 媒体加密移出循环",
     [], "AGEN-998 为全仓 async 阻塞扫描轴、AGEN-861 为 zulip 测试侧，均非本修复"),
    ("D10", "J", "P2", "入站幂等补齐", "msteams/discord/slack/dingtalk 入站去重缺口",
     [], "AGEN-493 是 stop 幂等，非入站幂等"),
    ("D11", "K", "P1", "qq/wecom 易失状态", "qq 路由缓存未命中兜底发错 API；wecom frame 缺失静默丢",
     [], "AGEN-736/1051 为解析/收发测试卡，不含本修复"),
    ("D12", "L", "P2", "发送超时归一", "slack/wecom/qq/whatsapp/feishu/dingtalk 发送路径补超时",
     [], "AGEN-578 为 HTTP 客户端超时扫描轴"),
    ("D13", "M", "P2", "not-running 契约文档化", "base.py 注明未运行时 send 预期行为并统一 16 通道",
     [], ""),
]
for sid, tag, pri, title, detail, cards, note in AXIS_D:
    add_seed(sid, "D:channel-contracts-20261005", tag=tag, priority=pri, title=title,
             detail=detail, manual_cards=list(cards), note=note)

# Axis E: error-messages Top15 (manual mapping, curated).
AXIS_E = [
    ("E1", 1, "P0", "knowledge.py:1403 health 响应带 traceback + str(e)",
     ["AGEN-783"], "修复未落 main（6cf793bd8 knowledge.py:1410 仍含 traceback.format_exc()）"),
    ("E2", 2, "P0", "blanket except→500 detail=str(e) ×62（book/co_writer/knowledge/notebook）",
     ["AGEN-827", "AGEN-902", "AGEN-903", "AGEN-781"],
     "四卡合计覆盖报告点名文件；未落 main（同文件 blanket-500 仍 20/18/60/12 处）"),
    ("E3", 3, "P0", "web client.ts messageFromBody 原样透出后端 detail（~250 调用点）",
     ["AGEN-1279"], "另见 AGEN-880（web detail.code 解析层）；未落 main"),
    ("E4", 4, "P0", "session/turns/executor.py:1349 聊天流错误事件 content=str(exc)",
     ["AGEN-785"], "未落 main（executor.py:1368 仍 content=str(exc)）"),
    ("E5", 5, "P0", "partners/runtime.py 伙伴回复失败带异常类名",
     ["AGEN-784"], ""),
    ("E6", 6, "P0", "供应商 resp.text[:400] 拼进异常透传（voice/search/embedding 等 10+ 处）",
     ["AGEN-779", "AGEN-1277"], "部分残留：generation_http.py:80 resp.text 仍在 main 且无修复卡"),
    ("E7", 7, "P0", "format_exception_message 白名单/脱敏/截断收敛",
     ["AGEN-774"], "未落 main（error_utils.py 仍为 pass-through）"),
    ("E8", 8, "P0", "pydantic ValidationError 全文回显（book/mastery_path）",
     ["AGEN-825"], ""),
    ("E9", 9, "P0", "llm/error_mapping.py:170 供应商 SDK 原文进用户流",
     ["AGEN-823"], "未落 main（error_mapping 仍 str(exc) 直传）"),
    ("E10", 10, "P0", "api/routers/notebook.py ×12 blanket-500",
     ["AGEN-781"], "未落 main"),
    ("E11", 11, "P0", "reading_extensions PermissionError str → 403 带服务端路径",
     ["AGEN-907"], ""),
    ("E12", 12, "P0", "practice/question 路径/key 泄漏与供应商原文下发",
     ["AGEN-786"], ""),
    ("E13", 13, "P1", "LANG-MIX：后端 routers 不走 t()、web 硬编码文案绕过 locale",
     [], "残留主项：后端 routers t() 收敛无卡；已建卡子项 AGEN-905（web 9 文件）/AGEN-904（fr/pl/uk 键）/AGEN-1366（co_writer 中文 detail）"),
    ("E14", 14, "P1", "NO-CODE：~597 处纯文本 detail 无机器可读 code",
     [], "残留主项：系统性 code 信封无卡；子集 AGEN-1364（sessions.py 27 处）、web 侧 AGEN-880"),
    ("E15", 15, "P1", "INCONSISTENT：not_found 15+ 种写法、网络失败/限流话术分裂",
     [], "残留主项：后端 not_found 模板统一无卡；web 侧 AGEN-910、跨文件话术 AGEN-1361"),
]
E_SEED_PATHS = {
    "E2": ["deeptutor/api/routers/book.py", "deeptutor/api/routers/co_writer.py",
           "deeptutor/api/routers/knowledge.py"],
    "E10": ["deeptutor/api/routers/notebook.py"],
}
for sid, rank, pri, title, cards, note in AXIS_E:
    add_seed(sid, "E:error-messages-20261004", rank=rank, priority=pri, title=title,
             manual_cards=list(cards), note=note, related_paths=list(E_SEED_PATHS.get(sid, [])))

# Axis F: coverage-gaps zero/weak lists (baseline lists, top100 deduped into C).
for i, z in enumerate(baseline_zero, 1):
    add_seed(f"FZ{i}", "F:coverage-gaps-zero", module=z["module"], path=z["path"],
             loc=z["loc"], fanin=z["fanin"], kind="zero")
seen_top100 = {r["module"] for r in baseline_weak_top100}
n = 0
for r in baseline_weak_tail:
    n += 1
    add_seed(f"FT{n}", "F:coverage-gaps-weak-tail", module=r["module"], path=r["path"],
             loc=r["loc"], fanin=r["fanin"], score=r["score"], kind="weak",
             triage_done=list(r["done"] or []), drift=r["drift"],
             in_tail23=r["module"] in tail23_mods, rank=100 + n)
assert len(SEED_ID) == 6 + 100 + 13 + 15 + 96 + 142, len(SEED_ID)

# ------------------------------------------------------- module->card matching

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
# card title classes: which prefixes CLAIM a test/fix seed vs merely relate to it
CLAIMING_PREFIX = ("test", "fix", "补测", "refactor", "chore", "rework", "pr-ready")
RELATED_PREFIX = ("guide", "docs", "scan", "verify", "review")

def card_class(key):
    t = key.lower()
    if t.startswith(CLAIMING_PREFIX):
        return "claim"
    if t.startswith(RELATED_PREFIX):
        return "related"
    return "claim"

def stem_unique_map():
    stems = {}
    for sid in ORDER:
        row = SEED_ID[sid]
        path = row.get("path")
        if not path:
            continue
        stem = os.path.splitext(os.path.basename(path))[0]
        stems.setdefault(stem, []).append(sid)
    return {s: sids for s, sids in stems.items() if len(sids) == 1}

UNIQUE_STEMS = stem_unique_map()

ALL_SEED_STEMS = set()
for _sid in ORDER:
    _p = SEED_ID[_sid].get("path")
    if _p:
        ALL_SEED_STEMS.add(os.path.splitext(os.path.basename(_p))[0])

# deeper-directory map: for seed S (…/X/stem.py) with another seed S2 at …/X/stem/<…>/last.py,
# a title mentioning "stem/last" references S2, not S.
DEEPER = {}  # stem -> set of deeper last-segments
for sid in ORDER:
    row = SEED_ID[sid]
    p = row.get("path")
    if not p:
        continue
    segs = p[:-3].split("/") if p.endswith(".py") else p.split("/")
    stem = segs[-1]
    for sid2 in ORDER:
        p2 = SEED_ID[sid2].get("path")
        if not p2 or sid2 == sid:
            continue
        segs2 = p2[:-3].split("/") if p2.endswith(".py") else p2.split("/")
        if len(segs2) == len(segs) + 1 and segs2[:len(segs)] == segs:
            DEEPER.setdefault(stem, set()).add(segs2[-1])

def match_titles(path):
    """Return card keys whose title targets this module path."""
    rel = path[len("deeptutor/"):] if path.startswith("deeptutor/") else path
    noext = rel[:-3] if rel.endswith(".py") else rel
    parts = noext.split("/")
    slash_forms = {"/".join(parts[i:]) for i in range(len(parts) - 1)}
    dotted_full = ".".join(parts)
    dotted_forms = {".".join(parts[i:]) for i in range(len(parts) - 1)}
    stem = parts[-1]
    stem_ok = (stem in UNIQUE_STEMS and stem not in STOP_STEMS and len(stem) >= 4)
    token_re = re.compile(r"[A-Za-z0-9_-]*" + re.escape(stem) + r"[A-Za-z0-9_-]*")
    hits = []
    for iss in issues:
        t = iss["title"].lower()
        matched = any(f in t for f in slash_forms) or any(d in t for d in dotted_forms)
        if not matched and stem_ok and any(k in t for k in KW):
            ok = bool(re.search(r"(?<![A-Za-z0-9_-])" + re.escape(stem) + r"(?![A-Za-z0-9_-])", t))
            if not ok:
                # allow stem inside a larger token only when the extension
                # crosses a separator and the token is not another seed's stem
                # (ask_user_trace / build_tool_options -> check; reasoning -> reject)
                for m in token_re.finditer(t):
                    tok = m.group(0)
                    i = m.start() + tok.index(stem)
                    j = i + len(stem)
                    sep = (i > 0 and t[i - 1] in "_-/") or (j < len(t) and t[j] in "_-/.")
                    if sep and tok not in ALL_SEED_STEMS:
                        ok = True
                        break
            if ok and stem in DEEPER:
                # "stem/deeper_last" points at the deeper module, not this one
                for dl in DEEPER[stem]:
                    if re.search(re.escape(stem) + r"/" + re.escape(dl) + r"\b", t):
                        ok = False
                        break
            if ok:
                matched = True
        if matched:
            hits.append((iss["identifier"], iss["title"], iss["status"]))
    return hits

# -------------------------------------------------------------- status engine

def key_status(keys):
    out = {}
    for k in keys:
        m = [i for i in issues if i["identifier"] == k]
        out[k] = m[0]["status"] if m else "?"
    return out

def classify(sid):
    row = SEED_ID[sid]
    axis = row["axis"]
    note_parts = []

    if axis.startswith(("D:", "E:")):
        covered = False
        evidence = ""
        cards = []
        fr = {}
    elif axis.startswith("B:"):
        fr = fresh_cli_by_path.get(row["path"], {})
        covered = fr.get("test_refs", 0) > 0
        evidence = ", ".join(fr.get("test_files", []))
        cards = list(CLI_CARDS[row["path"]])
    else:
        mod = row["module"]
        fr = fresh_by_module.get(mod, {})
        ntouch = fr.get("n_cover", 0) + fr.get("n_intree", 0)
        baseline_kind = row.get("kind", "weak")
        threshold = 1 if baseline_kind == "zero" else 2
        covered = ntouch >= threshold
        tests = fr.get("cover_tests", [])
        evidence = ", ".join(tests[:3]) + (f"（共 {len(tests)} 个）" if len(tests) > 3 else "")
        cards = list(row.get("triage_done", []))
        # drift notes: fresh state class vs baseline
        if covered:
            pass
        elif baseline_kind == "weak" and ntouch == 0:
            note_parts.append("漂移：v1.6.14 中唯一覆盖测试已消失（weak→zero）")
        elif baseline_kind == "zero" and ntouch == 1:
            note_parts.append("漂移：v1.6.14 中新增 1 个覆盖测试（zero→weak，仍不足）")

    titles = match_titles(row["path"]) if row.get("path") else []
    auto_claim, auto_related = [], []
    for k, _t, _s in titles:
        if k in cards:
            continue
        title_txt = next(t for kk, t, _s in titles if kk == k)
        head = re.split(r"[:：( (]", title_txt, maxsplit=1)[0].strip().lower()
        (auto_claim if card_class(head) == "claim" else auto_related).append(k)
    claims = cards + auto_claim
    related = auto_related
    override = MANUAL_OVERRIDES.get(sid, [])
    if override:
        claims = claims + [k for k in override if k not in claims]
        st = None
    st = key_status(claims)
    live_claims = [k for k in claims if st.get(k) not in ("cancelled",)]
    cancelled = [k for k in claims if st.get(k) == "cancelled"]
    done_unlanded = [k for k in claims if st.get(k) == "done"]

    if covered:
        state = "已被main测试覆盖"
    elif live_claims:
        state = "已建卡"
    else:
        state = "仍可建卡"
        if cancelled:
            note_parts.append("仅存取消卡：" + ",".join(cancelled))
        if done_unlanded:
            note_parts.append("存在 done 卡（%s）但 fresh 复扫模块仍零/弱覆盖，领卡前先核验原卡产出" % ",".join(done_unlanded))
        if related:
            note_parts.append("仅相关卡（guide/docs/scan/review，不构成领取去重）：" + ",".join(related))
    manual = row.get("manual_cards")
    if manual is not None:
        mst = key_status(manual)
        live_manual = [k for k in manual if mst.get(k) != "cancelled"]
        if state != "已被main测试覆盖":
            state = "已建卡" if live_manual else "仍可建卡"
        claims = claims + [k for k in manual if k not in claims]
        st.update(mst)
    if state == "已建卡" and auto_claim and not row.get("triage_done") and not manual:
        note_parts.append("本卡新增匹配卡（不在 triage DONE 映射内）：" + ",".join(auto_claim))
    if row.get("note"):
        note_parts.append(row["note"])
    row["state"] = state
    row["cards"] = claims
    row["related_cards"] = related
    row["card_status"] = st
    row["evidence"] = evidence if state == "已被main测试覆盖" else (
        "、".join("card " + c for c in claims) if claims else
        ("报告种子（%s）" % row["path"] if row.get("path") else "报告种子（报告锚点即依据）"))
    row["notes"] = "；".join(note_parts)
    # cross-refs for E axis
    if axis.startswith("E:"):
        cross = []
        for p in row.get("related_paths", []):
            for sid2 in ORDER:
                r2 = SEED_ID[sid2]
                if r2.get("path") == p and sid2 != sid:
                    cross.append(sid2)
        if cross:
            row["notes"] = (row["notes"] + "；" if row["notes"] else "") + "模块种子另见 " + ",".join(cross)

# Manual card-key overrides found during audit (title lacks the module stem but
# targets it explicitly): seed_id -> [card keys]
MANUAL_OVERRIDES = {
    "C15": ["AGEN-1285"],   # test: runtime/coordination 协议契约补测 -> protocol.py
    "FZ40": ["AGEN-969"],   # test: runtime 层 turn_engine 与 coordination types 补测
    "FZ52": ["AGEN-774"],   # fix 卡重写 format_exception_message（E7），回归测试覆盖本模块
    "FT80": ["AGEN-1011"],  # AGEN-1315 去重：github_source 轴（in_progress）明确覆盖 sync_service
    "FT26": ["AGEN-1346"],  # title 写 capabilities/setup apply（空格形式，slash/dotted 规则未覆盖）
}

for sid in ORDER:
    classify(sid)

# ------------------------------------------------------------------- counting

def count_by(f):
    out = {}
    for sid in ORDER:
        out[f(SEED_ID[sid])] = out.get(f(SEED_ID[sid]), 0) + 1
    return out

per_axis_total = count_by(lambda r: r["axis"].split(":")[0])
per_axis_state = {}
for ax in ("B", "C", "D", "E", "F"):
    sub = {sid: SEED_ID[sid] for sid in ORDER if SEED_ID[sid]["axis"].split(":")[0] == ax}
    per_axis_state[ax] = {
        "total": len(sub),
        "已建卡": sum(1 for r in sub.values() if r["state"] == "已建卡"),
        "已被main测试覆盖": sum(1 for r in sub.values() if r["state"] == "已被main测试覆盖"),
        "仍可建卡": sum(1 for r in sub.values() if r["state"] == "仍可建卡"),
    }
claimable = [sid for sid in ORDER if SEED_ID[sid]["state"] == "仍可建卡"]
covered = [sid for sid in ORDER if SEED_ID[sid]["state"] == "已被main测试覆盖"]
carded = [sid for sid in ORDER if SEED_ID[sid]["state"] == "已建卡"]

# --------------------------------------------------------------------- output

def esc(s):
    return str(s).replace("|", "/").replace("\n", " ")

L = []
L.append("# 跨扫描报告种子台账（seed-ledger 2026-10-10）")
L.append("")
L.append(f"- 基线：已发布清单 @ `origin/main {BASELINE_COMMIT[:9]}`（v1.6.13）；")
L.append(f"- 现势复核：`origin/main {FRESH_COMMIT[:9]}`（v1.6.14，本卡 fetch 于 {LEDGER_DATE}，独立 worktree 新分支，只读）")
L.append("- 三态口径：**已建卡**=看板存在指向该种子的非取消卡（依据=卡 key）；**已被main测试覆盖**=fresh 复扫中该模块触达数达到阈值（zero≥1 / weak≥2，依据=测试路径）；**仍可建卡**=两者皆无")
L.append("- 汇总：种子 **%d** 条 = 已建卡 %d + 已被main测试覆盖 %d + 仍可建卡 %d" % (len(ORDER), len(carded), len(covered), len(claimable)))
L.append("- 去重边界：weak100 三态沿用 AGEN-1154 triage（本卡不重排）；weak242 tail 的 23 个 fanin≥2 种子沿用 AGEN-1315；card→模块覆盖漂移方向见 AGEN-1316")
L.append("")
L.append("## 轴汇总")
L.append("")
L.append("| 轴 | 报告 | 种子 | 已建卡 | 已被main测试覆盖 | 仍可建卡 |")
L.append("|---|---|---:|---:|---:|---:|")
axis_names = {
    "B": ("B", "evidence/cli-zero-triage-20261009（CLI 零测试 6 模块）"),
    "C": ("C", "scan/weak-top100-triage-20261008（weak100 triage）"),
    "D": ("D", "scan/channel-contracts-20261005（通道契约修复卡 A–M）"),
    "E": ("E", "scan/error-messages-20261004（Top15 修复）"),
    "F": ("F", "scan/coverage-gaps-20261007（zero96 + weak242 模块清单）"),
}
for ax, (label, desc) in axis_names.items():
    s = per_axis_state[ax]
    L.append("| %s | %s | %d | %d | %d | %d |" % (label, desc, s["total"], s["已建卡"], s["已被main测试覆盖"], s["仍可建卡"]))
L.append("| A | scan/todo-sweep-20261009 | 0（2 噪音，不建卡） | - | - | - |")
L.append("")
L.append("## 轴 A：todo-sweep-20261009")
L.append("")
L.append(AXIS_A["note"] + "。")
L.append("")

# Axis B
L.append("## 轴 B：cli-zero-triage-20261009（6 种子）")
L.append("")
L.append("| ID | path | 三态 | 依据/卡 | 备注 |")
L.append("|---|---|---|---|---|")
for i, (path, grp, cmds) in enumerate(CLI_SEEDS, 1):
    r = SEED_ID[f"B{i}"]
    L.append("| %s | `%s` | %s | %s | %s |" % (r["seed_id"], path, r["state"], r["evidence"], esc(r["notes"])))
L.append("")

# Axis C
L.append("## 轴 C：weak-triage-20261008 top100（100 种子，triage 分序）")
L.append("")
L.append("| ID | rank | 模块 | LOC | fanin | score | 风险 | 三态 | 依据/卡 | 备注 |")
L.append("|---|---|---|---:|---:|---:|---|---|---|---|")
for i, r0 in enumerate(baseline_weak_top100, 1):
    r = SEED_ID[f"C{i}"]
    L.append("| %s | %d | `%s` | %d | %d | %d | %s | %s | %s | %s |" % (
        r["seed_id"], i, r["module"], r["loc"], r["fanin"], r["score"], r["risk"],
        r["state"], esc(r["evidence"]), esc(r["notes"])))
L.append("")

# Axis D
L.append("## 轴 D：channel-contracts-20261005 修复卡种子 A–M（13 种子）")
L.append("")
L.append("| ID | 卡 | 优先 | 内容 | 三态 | 依据/卡 | 备注 |")
L.append("|---|---|---|---|---|---|---|")
for sid, tag, pri, title, detail, cards, note in AXIS_D:
    r = SEED_ID[sid]
    L.append("| %s | %s | %s | %s | %s | %s | %s |" % (
        sid, tag, pri, esc(title + "：" + detail), r["state"], esc(r["evidence"]), esc(r["notes"])))
L.append("")

# Axis E
L.append("## 轴 E：error-messages-20261004 Top15（15 种子）")
L.append("")
L.append("| ID | # | 内容 | 三态 | 依据/卡 | 备注 |")
L.append("|---|---|---|---|---|---|")
for sid, rank, pri, title, cards, note in AXIS_E:
    r = SEED_ID[sid]
    L.append("| %s | %d | %s | %s | %s | %s |" % (sid, rank, esc(title), r["state"], esc(r["evidence"]), esc(r["notes"])))
L.append("")

# Axis F zero
L.append("## 轴 F：coverage-gaps zero/weak 清单")
L.append("")
L.append("### FZ zero96（基线 zero_top200 全量 96）")
L.append("")
L.append("| ID | 模块 | path | LOC | fanin | 三态 | 依据/卡 | 备注 |")
L.append("|---|---|---|---:|---:|---|---|---|")
for i, z in enumerate(baseline_zero, 1):
    r = SEED_ID[f"FZ{i}"]
    L.append("| %s | `%s` | `%s` | %d | %d | %s | %s | %s |" % (
        r["seed_id"], z["module"], z["path"], z["loc"], z["fanin"], r["state"], esc(r["evidence"]), esc(r["notes"])))
L.append("")
L.append("### FT weak242 tail（top100 之外 142）")
L.append("")
L.append("AGEN-1315 已为 tail 中 fanin≥2 的 23 个种子给出测试焦点（下表 ★）；其余 119 个（fanin≤1 为主）任何报告未给焦点，拆卡前需自审职责。")
L.append("")
L.append("| ID | rank | 模块 | path | LOC | fanin | ★ | 三态 | 依据/卡 | 备注 |")
L.append("|---|---|---|---|---:|---:|---|---|---|---|")
for n, r0 in enumerate(baseline_weak_tail, 1):
    r = SEED_ID[f"FT{n}"]
    L.append("| %s | %d | `%s` | `%s` | %d | %d | %s | %s | %s | %s |" % (
        r["seed_id"], r["rank"], r0["module"], r0["path"], r0["loc"], r0["fanin"],
        "★" if r["in_tail23"] else "", r["state"], esc(r["evidence"]), esc(r["notes"])))
L.append("")

# fresh drift appendix
L.append("## 附：v1.6.13→v1.6.14 覆盖漂移（对已发布清单的影响）")
L.append("")
zero_now_covered = [SEED_ID[f"FZ{i}"] for i, z in enumerate(baseline_zero, 1) if SEED_ID[f"FZ{i}"]["state"] == "已被main测试覆盖"]
weak_now_covered = [SEED_ID[f"C{i}"] for i in range(1, 101) if SEED_ID[f"C{i}"]["state"] == "已被main测试覆盖"] + \
                   [SEED_ID[f"FT{n}"] for n in range(1, 143) if SEED_ID[f"FT{n}"]["state"] == "已被main测试覆盖"]
L.append("- 基线 zero96 中已被测试覆盖 %d 个：%s" % (len(zero_now_covered), "、".join("`%s`" % r["module"] for r in zero_now_covered)))
L.append("- 基线 weak242 中触达≥2 的 %d 个：%s" % (len(weak_now_covered), "、".join("`%s`" % r["module"] for r in weak_now_covered)))
L.append("- 漂移异常：`services.session.workspace_preferences`（基线 weak100 #25）在 v1.6.14 中唯一覆盖测试消失，降为 zero；`learning.visual_practice`、`plugins.transactions`、`runtime.cache_reset` 为 v1.6.14 新增零覆盖模块（不在已发布清单内，供下一轮 harvest 参考）")
L.append("")

with open(os.path.join(HERE, "seed-ledger.md"), "w", encoding="utf-8") as f:
    f.write("\n".join(L) + "\n")

# claimable list
C = []
C.append("# 剩余可领取种子清单（claimable 2026-10-10）")
C.append("")
C.append("口径：三态中「仍可建卡」的种子，按轴与报告内优先序排列；领卡前按 seed-ledger.md 同行复核当日看板（本台账匹配基于 %s 抓取的 %d 张卡）。" % (LEDGER_DATE, len(issues)))
C.append("")
C.append("总计 %d 条可领取。轴分布：%s" % (len(claimable), "，".join(
    "%s=%d" % (ax, sum(1 for s in claimable if SEED_ID[s]["axis"].split(":")[0] == ax))
    for ax in ("E", "D", "C", "F"))))
C.append("")

def claim_rows(section_title, sids, header, rowfmt):
    C.append(section_title)
    C.append("")
    C.append(header)
    C.append(rowfmt)
    for sid in sids:
        r = SEED_ID[sid]
        C.append(rowfmt_join(r))
    C.append("")

def rowfmt_join(r):
    if r["axis"].startswith("E:"):
        return "| %s | #%d | %s | %s |" % (r["seed_id"], r["rank"], esc(r["title"]), esc(r["notes"]) or "-")
    if r["axis"].startswith("D:"):
        return "| %s | %s | %s | %s | %s |" % (r["seed_id"], r["tag"], r["priority"], esc(r["title"] + "：" + r["detail"]), esc(r["notes"]) or "-")
    if r["axis"].startswith("C:"):
        return "| %s | %d | `%s` | %d | %d | %s | %s |" % (r["seed_id"], r["rank"], r["module"], r["loc"], r["fanin"], r["risk"], esc(r["focus"]))
    if r["axis"] == "F:coverage-gaps-zero":
        return "| %s | `%s` | %d | %d | %s |" % (r["seed_id"], r["module"], r["loc"], r["fanin"], esc(r["notes"]) or "-")
    # weak tail
    star = "★AGEN-1315" if r["in_tail23"] else "无焦点"
    focus = ""
    if r["in_tail23"]:
        focus = tail23_by_module[r["module"]].get("focus_full") or tail23_by_module[r["module"]].get("focus", "")
    return "| %s | %d | `%s` | %d | %d | %s | %s |" % (r["seed_id"], r["rank"], r["module"], r["loc"], r["fanin"], star, esc(focus) if focus else "-")

open_e = [s for s in claimable if SEED_ID[s]["axis"].startswith("E:")]
open_d = [s for s in claimable if SEED_ID[s]["axis"].startswith("D:")]
open_c = [s for s in claimable if SEED_ID[s]["axis"].startswith("C:")]
open_fz = [s for s in claimable if SEED_ID[s]["axis"] == "F:coverage-gaps-zero"]
open_ft = [s for s in claimable if SEED_ID[s]["axis"] == "F:coverage-gaps-weak-tail"]

if open_e:
    C.append("## E 轴：错误消息 Top15 残留（%d）" % len(open_e))
    C.append("")
    C.append("| ID | # | 内容 | 备注 |")
    C.append("|---|---|---|---|")
    for sid in open_e:
        C.append(rowfmt_join(SEED_ID[sid]))
    C.append("")
if open_d:
    C.append("## D 轴：通道契约修复卡（%d）" % len(open_d))
    C.append("")
    C.append("| ID | 卡 | 优先 | 内容 | 备注 |")
    C.append("|---|---|---|---|---|")
    for sid in open_d:
        C.append(rowfmt_join(SEED_ID[sid]))
    C.append("")
if open_c:
    C.append("## C 轴：weak100 未建卡（%d，triage 分序）" % len(open_c))
    C.append("")
    C.append("| ID | rank | 模块 | LOC | fanin | 风险 | 建议测试焦点 |")
    C.append("|---|---|---|---:|---:|---|---|")
    for sid in open_c:
        C.append(rowfmt_join(SEED_ID[sid]))
    C.append("")
if open_fz:
    C.append("## F 轴：zero96 未建卡（%d，LOC 降序=基线序）" % len(open_fz))
    C.append("")
    C.append("| ID | 模块 | LOC | fanin | 备注 |")
    C.append("|---|---|---:|---:|---|")
    for sid in open_fz:
        C.append(rowfmt_join(SEED_ID[sid]))
    C.append("")
if open_ft:
    starred = [s for s in open_ft if SEED_ID[s]["in_tail23"]]
    rest = [s for s in open_ft if not SEED_ID[s]["in_tail23"]]
    if starred:
        C.append("## F 轴：weak tail 有焦点种子（%d，AGEN-1315 已给焦点）" % len(starred))
        C.append("")
        C.append("| ID | rank | 模块 | LOC | fanin | 焦点来源 | 焦点 |")
        C.append("|---|---|---|---:|---:|---|---|")
        for sid in starred:
            C.append(rowfmt_join(SEED_ID[sid]))
        C.append("")
    if rest:
        C.append("## F 轴：weak tail 无焦点种子（%d，拆卡前需自审职责）" % len(rest))
        C.append("")
        C.append("| ID | rank | 模块 | LOC | fanin | 焦点 | 备注 |")
        C.append("|---|---|---|---:|---:|---|---|")
        for sid in rest:
            C.append(rowfmt_join(SEED_ID[sid]))
        C.append("")

# partial appendix
C.append("## 附：部分已建卡、残留子项可续卡")
C.append("")
C.append("- E6（供应商响应体透传）：主体已建卡 AGEN-779/1277；残留 `generation_http.py:80` resp.text 拼接在 main 且无修复卡，可续卡")
C.append("- D7（stop 清理补全）：AGEN-493 已覆盖 6 通道吞错收口（未落 main）；feishu/slack/telegram 等资源关闭与取消 await 仍无卡")
C.append("- E13/E14/E15 按残留主项已列入上方可领取清单，其已建卡子项见 seed-ledger.md 轴 E 备注")
C.append("")

with open(os.path.join(HERE, "claimable-seeds.md"), "w", encoding="utf-8") as f:
    f.write("\n".join(C) + "\n")

# machine readable
data = {
    "date": LEDGER_DATE,
    "baseline_commit": BASELINE_COMMIT,
    "fresh_commit": FRESH_COMMIT,
    "board_snapshot": {"issues": len(issues)},
    "totals": {
        "seeds": len(ORDER),
        "carded": len(carded),
        "covered_by_main": len(covered),
        "claimable": len(claimable),
    },
    "per_axis": per_axis_state,
    "axis_A": AXIS_A,
    "seeds": [SEED_ID[sid] for sid in ORDER],
}
with open(os.path.join(HERE, "seeds.json"), "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=1)

print("seeds=%d carded=%d covered=%d claimable=%d" % (len(ORDER), len(carded), len(covered), len(claimable)))
print("per-axis:", json.dumps(per_axis_state, ensure_ascii=False))
sys.exit(0)
