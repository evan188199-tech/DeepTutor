#!/usr/bin/env python3
"""Final freshness verdicts for all 59 up-* cards, cross-checked against cached API data."""
import hashlib
import json
import os
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
a = json.load(open(os.path.join(HERE, "analysis.json")))
by_key = {c["key"]: c for c in a["cards"]}
CONSUMED = set(open("/Users/xzh/services/ai-development/multica-board-agent/glm-reserve/reserve/backlog/deeptour.consumed").read().split())
TODAY = "2026-10-05"

# key -> (verdict, reason)
# verdicts: 可用 / 已过时 / 需改派
V = {
 # ---- 已过时：上游已关闭或修复已合并进 dev ----
 "up-1691": ("已过时", "issue #1691 已关闭(completed)；修复 PR #1692 已合并(dev, 2026-10-04)"),
 "up-1390": ("已过时", "issue #1390 仍开放但 PR #1394 已合并(dev, 2026-09-23)，正文含 Closes #1390（PR 合入 dev≠默认分支，issue 未自动关闭）"),
 "up-1336": ("已过时", "issue #1336 仍开放但 PR #1339 已合并(dev, 2026-09-23)，正文含 Closes #1336"),
 "up-1244": ("已过时", "issue #1244 仍开放但 PR #1341 已合并(dev, 2026-09-19)，标题即「record wrong questions (#1244)」，与卡面意图一致（正文无 closing 关键字，建议人工抽查覆盖度）"),
 "up-1256": ("已过时", "issue #1256 仍开放但 PR #1350 已合并(dev, 2026-09-10)，正文含 Closes #1256"),
 "up-1254": ("已过时", "issue #1254 仍开放但 PR #1351 已合并(dev, 2026-09-10)，正文含 Closes #1254"),
 "up-1476": ("已过时", "issue #1476 仍开放但首切片 PR #1477 已合并(dev, 2026-09-23)，正文含 Closes #1476；后续切片需基于新基线重立卡"),
 "up-1296": ("已过时", "issue #1296 仍开放但 PR #1317 已合并(dev, 2026-09-23)，正文含 Closes #1296"),
 "up-1329": ("已过时", "issue #1329 仍开放但 PR #1330 已合并(dev, 2026-09-23)，正文含 Closes #1329"),
 "up-1326": ("已过时", "issue #1326 仍开放但 PR #1372 已合并(dev, 2026-09-23)，正文含 Closes #1326"),
 "up-1405": ("已过时", "issue #1405 仍开放但 PR #1408 已合并(dev, 2026-09-23)，正文含 Closes #1405"),
 "up-1109": ("已过时", "issue #1109(提案) 仍开放但 PR #1368 已合并(dev, 2026-09-23)，正文含 Closes #1109"),
 "up-971": ("已过时", "issue #971(提案) 仍开放但收尾 PR #1376 已合并(dev, 2026-09-23)，正文含 Closes #971（另有 #972/#974 早前合并）；残余边界需重立卡"),
 "up-429": ("已过时", "issue #429 仍开放但 PR #843 已合并(dev, 2026-08-16)，正文含 Closes #429"),
 "up-1676": ("已过时", "复核对象 PR #1682 已合并(dev, 2026-10-04)，跟踪 issue #1676 已关闭(completed)"),
 "up-1630": ("已过时", "复核对象 PR #1634 已合并(dev, 2026-10-04)；如有后续可关注后继 PR #1745（开放，base=main）"),
 "up-1614": ("已过时", "复核对象 PR #1619 已合并(dev, 2026-10-04)，跟踪 issue #1614 已关闭(completed)"),
 "up-1613": ("已过时", "复核对象 PR #1625 已合并(dev, 2026-10-04)，跟踪 issue #1613 已关闭(completed)"),
 "up-1222": ("已过时", "比较复核前提已消失：#1652 已合并(dev, 2026-10-04)，#1225 已关闭未合并(2026-10-04)；跟踪 issue #1222 为长期跟踪、有意保持开放"),
 "up-1678": ("已过时", "issue #1678 已关闭(completed)；修复 PR #1683 已合并(dev, 2026-10-04)"),
 "up-1647": ("已过时", "issue #1647 已关闭(completed)；修复 PR #1666 已合并(dev, 2026-10-04)"),
 "up-1646": ("已过时", "issue #1646 已关闭(completed)；修复 PR #1685 已合并(dev, 2026-10-04)"),
 "up-1624": ("已过时", "issue #1624 已关闭(completed)；修复 PR #1626 已合并(dev, 2026-10-04)（另一相关 PR #1642 已关闭未合并）"),
 "up-1673": ("已过时", "issue #1673 已关闭(completed)；修复 PR #1686 已合并(dev, 2026-10-04)"),
 "up-1623": ("已过时", "issue #1623 已关闭(completed)；修复 PR #1627 已合并(dev, 2026-10-04)"),
 "up-1648": ("已过时", "issue #1648 已关闭(completed)；修复 PR #1668 已合并(dev, 2026-10-04)"),
 # ---- 需改派：上游问题仍在，但卡面指向的对象已失效，需改写卡面 ----
 "up-1215": ("需改派", "复核对象 PR #1216 已关闭未合并(2026-10-04)，跟踪 issue #1215 仍开放；存在后继 PR #1219（开放，base=dev）可改指"),
 "up-1419": ("需改派", "复核对象 PR #1420 已关闭未合并(2026-10-04)，跟踪 issue #1419 仍开放；需重新定位草稿或放弃"),
 "up-1389": ("需改派", "回收站主体已由 PR #1398(2026-09-13) 与 #1615(2026-10-04) 合并落地，但 issue #1389 关闭后又重开，仍有残留问题；卡面需按重开后范围改写"),
 # ---- 可用：原样可执行 ----
 "up-1410": ("可用", "issue #1410 仍开放，无已合并修复；交叉引用中出现的开放 PR #1723 仅在描述里提及 #1410，并非其实现"),
 "up-1610": ("可用", "issue #1610 仍开放，无关联 PR，无合并修复"),
 "up-575":  ("可用", "issue #575 仍开放，无关联 PR，无合并修复（注：myfork 已有分支 glm-reserve/up-575 在途）"),
 "up-440":  ("可用", "issue #440 仍开放，无关联 PR，无合并修复（注：myfork 已有分支 glm-reserve/up-440 在途）"),
 "up-1447": ("可用", "issue #1447 仍开放；切片 PR #1472 已合并(2026-09-23)、#1237 已关闭未合并，剩余切片仍可执行"),
 "up-451":  ("可用", "issue #451 仍开放；在途开放 PR #1221(base=dev) 与 #1724(我方分支, base=main)，开工前需协调避免重复"),
 "up-1209": ("可用", "issue #1209(提案) 仍开放，无关联 PR，无合并修复"),
 "up-1303": ("可用", "issue #1303(提案) 仍开放，无关联 PR，无合并修复"),
 "up-932":  ("可用", "issue #932(提案) 仍开放；前次 PR #1061 已关闭未合并(2026-10-04)，可重新执行"),
 "up-916":  ("可用", "issue #916(提案) 仍开放；部分切片 PR #1464 已合并(2026-09-23)，剩余切片在途开放 PR #1734(我方分支)"),
 "up-860":  ("可用", "issue #860(提案) 仍开放，无关联 PR，无合并修复"),
 "up-961":  ("可用", "issue #961(提案) 仍开放，无关联 PR，无合并修复"),
 "up-1307": ("可用", "issue #1307(提案) 仍开放；前次 PR #1309 已关闭未合并(2026-10-04)，可重新执行"),
 "up-403":  ("可用", "issue #403 仍开放，无关联 PR，无合并修复"),
 "up-1611": ("可用", "issue #1611 仍开放，无关联 PR，无合并修复"),
 "up-655":  ("可用", "issue #655 仍开放，无关联 PR，无合并修复（注：myfork 已有分支 glm-reserve/up-655 在途）"),
 "up-684":  ("可用", "issue #684 仍开放，无关联 PR，无合并修复"),
 "up-1236": ("可用", "issue #1236(提案) 仍开放；前次 PR #1237 已关闭未合并(2026-10-04)，可重新执行"),
 "up-1629": ("可用", "issue #1629 仍开放，无关联 PR，无合并修复"),
 "up-1779": ("可用", "issue #1779 仍开放（2026-10 新增），无关联 PR，无合并修复"),
 "up-1641": ("可用", "issue #1641 仍开放，无关联 PR，无合并修复"),
 "up-1481": ("可用", "验证卡：修复 PR #1488 已合并(dev, 2026-09-23)，「是否真正闭环」的验证仍待执行；issue #1481 仍开放"),
 "up-1478": ("可用", "验证卡：修复 PR #1480 已合并(dev, 2026-09-23)，验证仍待执行；issue #1478 仍开放"),
 "up-1359": ("可用", "验证卡：修复链 PR #1373(2026-09-23)/#1413(2026-09-13) 已合并，验证仍待执行；issue #1359 仍开放"),
 "up-1228": ("可用", "验证卡：修复 PR #1231 已合并(dev, 2026-09-07)，验证仍待执行；issue #1228 仍开放"),
 "up-1223": ("可用", "验证卡：修复链 PR #1266/#1333/#1443 均已合并(dev)，验证仍待执行；issue #1223 仍开放"),
 "up-1421": ("可用", "验证卡：修复 PR #1436 已合并(dev, 2026-09-13)，验证仍待执行；issue #1421 仍开放"),
 "up-1220": ("可用", "复核卡：目标 PR #1221 仍开放；#1694 已合并(dev, 2026-10-04)，复核范围缩减至 #1221（#1694 可作对照）"),
 "up-1176": ("可用", "复核卡：目标 PR #1270 仍开放（另 #1345 已合并 2026-09-23 可作对照）；issue #1176 仍开放"),
 "up-1696": ("可用", "复核卡：目标 PR #1698 仍开放（我方分支，base=dev）；issue #1696 已关闭(completed)"),
}

# ---- cross-check verdicts against cached evidence ----
errors = []
for c in a["cards"]:
    k = c["key"]
    if k not in V:
        errors.append(f"{k}: no verdict")
        continue
    verdict, reason = V[k]
    prim = c["primary"]
    n = prim["number"]
    # assertions on primary state claims embedded in reasons
    def has_merged(prnum):
        p = None
        path = os.path.join(HERE, "cache", f"repos_HKUDS_DeepTutor_pulls_{prnum}.json")
        if os.path.exists(path):
            p = json.load(open(path))
        return bool(p and p.get("merged"))
    def merged_at(prnum):
        path = os.path.join(HERE, "cache", f"repos_HKUDS_DeepTutor_pulls_{prnum}.json")
        return (json.load(open(path)).get("merged_at") or "")[:10] if os.path.exists(path) else "?"
    import re
    for m in re.finditer(r"PR #(\d+) 已合并\(dev, (\d{4}-\d{2}-\d{2})\)", reason):
        pr, dt = int(m.group(1)), m.group(2)
        if not has_merged(pr): errors.append(f"{k}: PR #{pr} not merged per cache")
        elif merged_at(pr) != dt: errors.append(f"{k}: PR #{pr} merged_at {merged_at(pr)} != cited {dt}")
    if "已关闭(completed)" in reason and prim.get("state") != "closed":
        if f"issue #{n} 已关闭" in reason or "跟踪 issue" in reason or "issue #" in reason:
            if prim.get("state") != "closed":
                errors.append(f"{k}: claims issue closed but state={prim.get('state')}")
    if reason.startswith("issue") and "仍开放" in reason.split("；")[0] and prim.get("state") != "open":
        errors.append(f"{k}: claims issue open but state={prim.get('state')}")

assert len(V) == 59, f"verdict count {len(V)} != 59"
assert not errors, "EVIDENCE MISMATCH:\n" + "\n".join(errors)

# ---- counts ----
order = {"可用": 0, "需改派": 1, "已过时": 2}
cards_sorted = sorted(a["cards"], key=lambda c: (order[V[c["key"]][0]], c["file"], c["line"]))
counts = {"可用": 0, "需改派": 0, "已过时": 0}
by_file = {}
for c in a["cards"]:
    v = V[c["key"]][0]
    counts[v] += 1
    by_file.setdefault(c["file"], {"可用": 0, "需改派": 0, "已过时": 0, "total": 0})
    by_file[c["file"]][v] += 1
    by_file[c["file"]]["total"] += 1

# ---- report ----
L = []
L.append(f"# 储备池 up-* 卡上游新鲜度复核报告（{TODAY}）")
L.append("")
L.append("## 汇总")
L.append("")
L.append(f"- 核对范围：backlog 三份 jsonl（`deeptour.0priority.jsonl` / `deeptour.auto.jsonl` / `deeptour.jsonl`）中全部 up-* 卡，共 **59 张**，100% 逐张核对。")
L.append(f"- 数据源：api.github.com `repos/HKUDS/DeepTutor`（issues、pulls、issues/timeline），只读查询，缓存快照见 `analysis-snapshot.json`。")
L.append(f"- 判定结果：**可用 {counts['可用']} 张 / 需改派 {counts['需改派']} 张 / 已过时 {counts['已过时']} 张**。")
L.append("")
L.append("| 文件 | up-* 卡数 | 可用 | 需改派 | 已过时 |")
L.append("|---|---|---|---|---|")
for fn in ["deeptour.0priority.jsonl", "deeptour.auto.jsonl", "deeptour.jsonl"]:
    d = by_file.get(fn)
    if not d:
        L.append(f"| `{fn}` | 0（无 up-* 卡） | - | - | - |")
    else:
        L.append(f"| `{fn}` | {d['total']} | {d['可用']} | {d['需改派']} | {d['已过时']} |")
L.append("")
L.append("下一轮 harvest 建议剔除 **26 张已过时卡**；**3 张需改派**（改写卡面后保留）；**30 张可用**原样保留。")
L.append("")
L.append("## 方法说明")
L.append("")
L.append("- 每张卡解析标题/描述中的上游编号（含全角括号 `（#N）` 形式），主编号取标题尾部 `#N`。")
L.append("- 对每个主编号拉取 issue 状态、timeline 交叉引用 PR；对每张关联/引用 PR 拉取合并状态与正文。")
L.append("- 关键发现：DeepTutor 上游 PR 一律合入 `dev`，而仓库默认分支是 `main`，GitHub 不会自动关闭关联 issue —— 因此 **「issue 仍开放」不等于「未被修复」**。凡 PR 已合并且正文含 `Closes/Fixes #N`（或 PR 标题与卡面意图一致）即判「已过时」；仅在 issue 被显式关闭/重开等场景另行标注。")
L.append("- 与 verify-reserve-rebase（分支可合入性）为两个正交维度，本报告不涉及分支合入性判定。")
L.append("- 全程未修改 backlog 文件、未在上游发表任何评论。")
L.append("")
for verdict in ["已过时", "需改派", "可用"]:
    L.append(f"## {verdict}（{counts[verdict]} 张）")
    L.append("")
    if verdict == "已过时":
        L.append("| 卡 | 位置 | 类型 | 上游 issue 状态 | 关联 PR（引用号·状态） | 原因 |")
        L.append("|---|---|---|---|---|---|")
    elif verdict == "需改派":
        L.append("| 卡 | 位置 | 类型 | 上游 issue 状态 | 关联 PR（引用号·状态） | 改派方向 |")
        L.append("|---|---|---|---|---|---|")
    else:
        L.append("| 卡 | 位置 | 类型 | 上游 issue 状态 | 关联 PR（引用号·状态） | 备注 |")
        L.append("|---|---|---|---|---|---|")
    for c in cards_sorted:
        if V[c["key"]][0] != verdict:
            continue
        k = c["key"]
        reason = V[k][1]
        prim = c["primary"]
        kind = {"fix": "fix", "review": "review", "verify": "verify"}.get(c["kind"], c["kind"])
        if prim["kind"] == "issue":
            st = f"#{prim['number']} open"
            if prim.get("state_reason") == "reopened" or k == "up-1389":
                st += "(重开后仍开放)"
            if prim.get("closed_at") is None and prim.get("state") == "open":
                pass
        else:
            st = f"#{prim['number']} {prim['state']}"
        if prim.get("state") == "closed":
            st = f"#{prim['number']} closed({prim.get('state_reason')})"
        prparts = []
        seen = set()
        for n2, p in sorted(c["pr_states"].items(), key=lambda kv: int(kv[0])):
            seen.add(int(n2))
            s = "merged" if p["merged"] else ("closed" if p["state"] == "closed" else p["state"])
            prparts.append(f"#{n2} {s}")
        for r in c["xref_prs"]:
            if r["number"] in seen:
                continue
            p = a["xref_prs"].get(str(r["number"]), {})
            if not p:
                continue
            s = "merged" if p.get("merged") else p.get("state", "?")
            if s != "missing": prparts.append(f"#{r['number']} {s}")
        consumed = "；consumed" if k in CONSUMED else ""
        loc = f"`{c['file']}:{c['line']}`"
        L.append(f"| `{k}` | {loc} | {kind} | {st} | {'、'.join(prparts) or '无'} | {reason}{consumed} |")
    L.append("")

L.append("## 附注")
L.append("")
L.append(f"- consumed 交叠：`up-1646` / `up-1647` / `up-1678` 已列入 `deeptour.consumed`，但仍残留在 `deeptour.jsonl` 第 1–3 行 —— 本次已判「已过时」，建议 harvest 时一并清除该残留行。")
L.append("- `deeptour.0priority.jsonl`（11 行）不含任何 up-* 卡，全部为内部 fix/test/bundle 卡，不在本次核对范围。")
L.append("- 可用卡中的在途提示：`up-451`（开放 PR #1221 / #1724）、`up-916`（开放 PR #1734）、`up-1410`（无在途实现 PR）、`up-575` / `up-440` / `up-655`（myfork 已有在途分支）—— 这些卡判定仍为可用，但开工前需与在途工作去重。")
L.append("- 「需改派」3 张的上游 issue 本身仍有效（#1215 / #1419 / #1389），建议改写卡面指向新的对象（如 #1219 后继 PR、#1389 重开后的残留问题）而非直接剔除。")
L.append("")
L.append(f"---\n生成时间：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}；核对脚本随附于本目录 `scripts/`，API 原始响应缓存未入库（可按 snapshot 中的引用号重新拉取复核）。")

report = "\n".join(L) + "\n"
outdir = os.path.join(HERE, "out")
os.makedirs(outdir, exist_ok=True)
open(os.path.join(outdir, "report.md"), "w").write(report)

# machine-readable snapshot
snap = {
    "date": TODAY,
    "repo": "HKUDS/DeepTutor",
    "scope": "all up-* cards in backlog jsonl files",
    "totals": counts,
    "by_file": by_file,
    "cards": [
        {
            "key": c["key"], "file": c["file"], "line": c["line"], "title": c["title"],
            "primary_issue": c["primary"]["number"],
            "issue_state": c["primary"].get("state"),
            "issue_state_reason": c["primary"].get("state_reason"),
            "referenced_prs": sorted({int(n) for n in c["pr_states"]} | {r["number"] for r in c["xref_prs"]}),
            "pr_states": {str(n): {"state": p["state"], "merged": p.get("merged"), "merged_at": p.get("merged_at")}
                          for n, p in {**c["pr_states"], **a["xref_prs"]}.items()
                          if int(n) in sorted({int(n2) for n2 in c["pr_states"]} | {r["number"] for r in c["xref_prs"]})},
            "verdict": V[c["key"]][0],
            "reason": V[c["key"]][1],
            "consumed": c["key"] in CONSUMED,
        } for c in cards_sorted
    ],
}
json.dump(snap, open(os.path.join(outdir, "analysis-snapshot.json"), "w"), ensure_ascii=False, indent=1)

# scripts + checksums
import shutil
os.makedirs(os.path.join(outdir, "scripts"), exist_ok=True)
for s in ["extract_cards.py", "fetch_upstream.py", "analyze.py", "classify.py"]:
    shutil.copy(os.path.join(HERE, s), os.path.join(outdir, "scripts", s))
lines = []
for name in ["report.md", "analysis-snapshot.json", "scripts/extract_cards.py", "scripts/fetch_upstream.py", "scripts/analyze.py", "scripts/classify.py"]:
    h = hashlib.sha256(open(os.path.join(outdir, name), "rb").read()).hexdigest()
    lines.append(f"{h}  {name}")
open(os.path.join(outdir, "SHA256SUMS"), "w").write("\n".join(lines) + "\n")

print("counts:", counts)
print("by_file:", json.dumps(by_file, ensure_ascii=False))
print("all evidence assertions passed")
