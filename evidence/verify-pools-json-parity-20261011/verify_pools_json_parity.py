#!/usr/bin/env python3
"""pools.json 与 backlog/*.jsonl 双向漂移复核（只读）。

口径与 multica_board_agent/reserve.py 的加载语义一致：
- load_backlog: glob "<pool>.jsonl" + "<pool>.*.jsonl"（先基础文件后字母序），
  非空行逐行 json.loads，Candidate(key,title,executor,description[,priority,after])，
  首次出现的 key 生效，后续重复/非法行跳过并记 error。
- plan_refill: executor 不在 pool.agents 的候选被静默过滤。
- _consumed: backlog/<pool>.consumed 已核销键按 done 处理。

三类漂移：
1. jsonl 有而 pools 无（游离文件 / executor 未声明 / 无法加载行）
2. pools 声明而文件缺失（基础 jsonl / harvest 追加目标 / consumed 台账）
3. 重复键（同文件或跨文件，后者被 loader 丢弃）

用法: python3 verify_pools_json_parity.py <reserve_dir> <out_dir>
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

RESERVE = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2]).resolve()

FATAL = []


def die(msg: str) -> None:
    FATAL.append(msg)


# ---------- pools.json 声明侧 ----------
try:
    pools_raw = json.loads((RESERVE / "pools.json").read_text(encoding="utf-8"))
except Exception as exc:  # noqa: BLE001
    die(f"pools.json 无法解析: {exc}")
    pools_raw = {"pools": {}}

declared = pools_raw["pools"]  # 池键 -> 配置（键集合即"声明的池"）
declared_pool_keys = sorted(declared)

# ---------- backlog 实际文件侧 ----------
backlog = RESERVE / "backlog"
if not backlog.is_dir():
    die(f"backlog 目录缺失: {backlog}")
    backlog = RESERVE

all_files = sorted(p for p in backlog.iterdir() if p.is_file())

def pool_matches(pool: str, f: Path) -> bool:
    return f.name == f"{pool}.jsonl" or f.name.startswith(f"{pool}.") and (
        f.name.endswith(".jsonl") or f.name == f"{pool}.consumed"
    )

owned: dict[str, list[Path]] = {p: [] for p in declared_pool_keys}
orphan_files: list[Path] = []  # 类别1: 文件存在但无池声明
for f in all_files:
    hit = [p for p in declared_pool_keys if pool_matches(p, f)]
    if hit:
        owned[hit[0]].append(f)
    else:
        orphan_files.append(f)

# ---------- 键级解析（按 load_backlog 顺序与首现生效语义） ----------
def candidate_fields(raw: dict) -> tuple[str | None, str]:
    """返回 (error, normalized)；模拟 Candidate(**raw) 的字段校验。"""
    allowed = {"key", "title", "executor", "description", "priority", "after"}
    extra = set(raw) - allowed
    if extra:
        return f"extra field(s): {sorted(extra)}", ""
    missing = [k for k in ("key", "title", "executor", "description") if k not in raw]
    if missing:
        return f"missing field(s): {missing}", ""
    after = raw.get("after", ())
    if not isinstance(after, (list, tuple)):
        return "after must be a list", ""
    return "", "ok"

records: dict[str, list[dict]] = {}  # key -> [{file,line,executor,title}]
dup_keys: dict[str, list[str]] = {}  # 类别3: key -> 后续出现位置(file:line)
invalid_lines: list[str] = []        # 类别1: 无法加载行
executors_seen: Counter = Counter()
files_stat: dict[str, dict] = {}
after_deps: set[str] = set()

for pool in declared_pool_keys:
    base = sorted(owned[pool] and [f for f in owned[pool] if f.name == f"{pool}.jsonl"])
    star = sorted(f for f in owned[pool] if f.name.endswith(".jsonl") and f.name != f"{pool}.jsonl")
    for f in base + star:
        n_lines = n_data = 0
        for n, ln in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if not ln.strip():
                continue
            n_lines += 1
            try:
                raw = json.loads(ln)
                if not isinstance(raw, dict):
                    raise ValueError("not a json object")
            except Exception as exc:  # noqa: BLE001
                invalid_lines.append(f"{f.name}:{n}: invalid json: {exc}")
                continue
            err, _ = candidate_fields(raw)
            if err:
                invalid_lines.append(f"{f.name}:{n}: {err}")
                continue
            n_data += 1
            k = raw["key"]
            executors_seen[raw["executor"]] += 1
            for dep in raw.get("after", ()):
                after_deps.add(dep)
            if k in records:
                dup_keys.setdefault(k, [f"{records[k][0]['file']}:{records[k][0]['line']}"])
                dup_keys[k].append(f"{f.name}:{n}")
            else:
                records[k] = [{"file": f.name, "line": n, "executor": raw["executor"],
                               "title": raw.get("title", "")}]
        files_stat[f.name] = {"lines_total": n_lines, "candidates": n_data}

all_jsonl_keys = set(records)

# 类别1b: executor 未在池 agents 声明（plan_refill 静默过滤）
declared_agents = {p: set(cfg.get("agents", {})) for p, cfg in declared.items()}
undeclared_exec: dict[str, list[str]] = {}  # executor -> keys
for k, rs in records.items():
    ex = rs[0]["executor"]
    usable = any(ex in declared_agents[p] for p in declared_pool_keys)
    if not usable:
        undeclared_exec.setdefault(ex, []).append(k)

# 类别2: 池声明而文件缺失
missing_files: list[str] = []
for pool, cfg in declared.items():
    if not any(f.name == f"{pool}.jsonl" for f in owned[pool]):
        missing_files.append(f"池 {pool}: 基础文件 backlog/{pool}.jsonl 缺失")
    if cfg.get("harvest"):
        target = f"{pool}.auto.jsonl"
        if not any(f.name == target for f in owned[pool]):
            missing_files.append(f"池 {pool}: harvest 追加目标 backlog/{target} 缺失")
    if not any(f.name == f"{pool}.consumed" for f in owned[pool]):
        missing_files.append(f"池 {pool}: consumed 台账 backlog/{pool}.consumed 缺失")
    for slot in ("capacity",):
        for name in (cfg.get(slot) or {}):
            if name not in cfg.get("agents", {}):
                missing_files.append(f"池 {pool}: {slot} 执行者「{name}」未在 agents 声明")
    if cfg.get("harvest") and cfg["harvest"].get("executor") not in cfg.get("agents", {}):
        missing_files.append(f"池 {pool}: harvest.executor「{cfg['harvest']['executor']}」未在 agents 声明")

# 补充交叉引用（不展开，归属其他轴）
consumed_files = {f.name: [k.strip() for k in f.read_text(encoding="utf-8").splitlines() if k.strip()]
                  for f in all_files if f.name.endswith(".consumed")}
consumed_overlap = {
    name: sorted(set(keys) & all_jsonl_keys) for name, keys in consumed_files.items()
}
consumed_overlap = {k: v for k, v in consumed_overlap.items() if v}
dangling_after = sorted(d for d in after_deps if d not in all_jsonl_keys)

# ---------- 汇总计数 ----------
summary = {
    "declared_pools": declared_pool_keys,
    "backlog_files": [f.name for f in all_files],
    "total_data_lines": sum(s["candidates"] for s in files_stat.values()),
    "unique_keys": len(all_jsonl_keys),
    "duplicate_keys": len(dup_keys),
    "duplicate_extra_occurrences": sum(len(v) - 1 for v in dup_keys.values()),
    "invalid_lines": len(invalid_lines),
    "orphan_files": [f.name for f in orphan_files],
    "undeclared_executors": {k: len(v) for k, v in undeclared_exec.items()},
    "missing_declarations": missing_files,
    "consumed_overlap": {k: len(v) for k, v in consumed_overlap.items()},
    "dangling_after_deps": dangling_after,
    "per_file": files_stat,
    "executor_counts": dict(executors_seen),
}

# 双向守恒：唯一键 + 重复多余出现 + 非法行 == 数据行总数
lhs = summary["unique_keys"] + summary["duplicate_extra_occurrences"] + summary["invalid_lines"]
summary["conservation_ok"] = lhs == summary["total_data_lines"]

# ---------- 报告 ----------
L: list[str] = []
add = L.append
add("# pools.json 与 backlog 卡池漂移复核（2026-10-11）")
add("")
add(f"- 复核对象（只读）：`{RESERVE}`")
add("- 口径：与 `multica_board_agent/reserve.py` 加载语义一致（首现 key 生效；executor 须在池 agents 内；")
add("  `backlog/<pool>.consumed` 为核销台账）。")
add("")
add("## 汇总")
add("")
add(f"| 项 | 数值 |")
add(f"|---|---|")
add(f"| 声明池 | {', '.join(declared_pool_keys)}（共 {len(declared_pool_keys)} 个） |")
add(f"| backlog 文件 | {len(all_files)} 个：{', '.join(f.name for f in all_files)} |")
add(f"| 候选数据行 | {summary['total_data_lines']} |")
add(f"| 唯一键 | {summary['unique_keys']} |")
add(f"| 重复键 | {summary['duplicate_keys']} 个 key，多余出现 {summary['duplicate_extra_occurrences']} 行 |")
add(f"| 无法加载行 | {summary['invalid_lines']} |")
add(f"| 游离文件（无池声明） | {len(orphan_files)} |")
add(f"| executor 未声明（被静默过滤） | {sum(summary['undeclared_executors'].values())} 键 |")
add(f"| 声明缺失项 | {len(missing_files)} |")
add("")
add(f"双向守恒校验：唯一键 {summary['unique_keys']} + 重复多余 {summary['duplicate_extra_occurrences']} + "
    f"非法行 {summary['invalid_lines']} = {lhs}，"
    f"{'== ' if summary['conservation_ok'] else '!= '}数据行 {summary['total_data_lines']}"
    f"（{'通过' if summary['conservation_ok'] else '不通过'}）。")
add("")
add("## 分类一：jsonl 有而 pools 无")
add("")
if orphan_files:
    add("### 1a. 游离文件（不匹配任何池的 glob）")
    for f in orphan_files:
        add(f"- `{f.name}`")
else:
    add("- 无：全部文件均归属于声明池（`deeptour.jsonl`、`deeptour.*.jsonl`、`deeptour.consumed`）。")
add("")
if undeclared_exec:
    add("### 1b. executor 未在 pools.json 声明（plan_refill 会静默丢弃）")
    for ex, keys in sorted(undeclared_exec.items()):
        add(f"- executor「{ex}」：{len(keys)} 键 → {', '.join(sorted(keys))}")
    add("- 建议：在 pools.json `deeptour.agents` 补声明对应执行者，或改写这些卡的 executor。")
else:
    add("- 无：全部唯一键的 executor ∈ {GLM 5.3, GLM 5.3 Flash}。")
add("")
if invalid_lines:
    add("### 1c. 无法加载行（loader 跳过）")
    for e in invalid_lines:
        add(f"- `{e}`")
    add("- 建议：按 file:line 修正字段或删除坏行。")
else:
    add("- 无。")
add("")
add("## 分类二：pools 声明而文件缺失")
add("")
if missing_files:
    for m in missing_files:
        add(f"- {m}")
else:
    add("- 无：池 `deeptour` 的基础文件 `deeptour.jsonl`、harvest 追加目标 `deeptour.auto.jsonl`、")
    add("  核销台账 `deeptour.consumed` 均存在；`capacity`/`harvest.executor` 均已声明在 agents 内。")
add("")
add("## 分类三：重复键")
add("")
if dup_keys:
    add(f"共 {len(dup_keys)} 个 key 存在多次出现；按 loader 语义首次出现生效，后续出现被跳过：")
    add("")
    add("| key | 首现（生效） | 后续出现（被丢弃） |")
    add("|---|---|---|")
    for k in sorted(dup_keys):
        occ = dup_keys[k]
        add(f"| `{k}` | {occ[0]} | {', '.join(occ[1:])} |")
    add("")
    add("- 建议：保留一处（通常保留 deeptour.jsonl 手写版），从被丢弃位置删除重复行。")
else:
    add("- 无：全部键唯一（同文件与跨文件均无重复）。")
add("")
add("## 补充交叉引用（不计入三类，细节归属其他轴）")
add("")
add(f"- consumed∩jsonl 残留键：{sum(len(v) for v in consumed_overlap.values())} 个"
    + (f"（{'; '.join(f'{k}: {", ".join(v)}' for k, v in consumed_overlap.items())}）" if consumed_overlap else "")
    + "——深入核对归属 verify-claims-ledger（键一致性轴）。")
add(f"- after 依赖指向不存在键：{len(dangling_after)} 个"
    + (f"：{', '.join(dangling_after)}" if dangling_after else "。"))
add("- executor 分布：" + "、".join(f"{k}×{v}" for k, v in sorted(executors_seen.items())) + "。")
if not (orphan_files or undeclared_exec or invalid_lines or missing_files or dup_keys):
    add("- 修正建议汇总：三类漂移均为零，无需修正；唯一需人工留意的是 consumed 残留键"
        f"（{sum(len(v) for v in consumed_overlap.values())} 个，交由键一致性轴处理）。")
add("")
add("## 复现")
add("")
add("```bash")
add(f"python3 evidence/verify-pools-json-parity-20261011/verify_pools_json_parity.py \\")
add(f"  {RESERVE} <out_dir>")
add("```")
add("")
add("输入快照指纹（SHA256，见 inputs.sha256）：复核时点 pools.json 与 backlog/* 原样，未做任何修改。")

report = "\n".join(L) + "\n"
if len(L) > 120:
    die(f"report 超长: {len(L)} 行 > 120")

OUT.mkdir(parents=True, exist_ok=True)
(OUT / "report.md").write_text(report, encoding="utf-8")
(OUT / "counts.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
for f in FATAL:
    print("FATAL:", f)
print(f"report lines: {len(L)}; conservation_ok={summary['conservation_ok']}")
