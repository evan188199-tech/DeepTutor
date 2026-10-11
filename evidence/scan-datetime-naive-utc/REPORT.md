# scan: naive datetime 与 UTC 混用全库清点

- 基线: HKUDS/DeepTutor `origin/main` @ `6cf793bd868ba5ecbe64722936d4be8fab5a01df` (release v1.6.14)
- 方式: 纯静态 grep（ripgrep），只读，不改任何代码；worktree `dt-agen1703-tzscan-wt`
- 交付: 本报告 + `findings_full.tsv`（180 个唯一站点，path:line 逐条）+ `scan_commands.sh`（可复现口径）+ `SHA256SUMS`
- 去重说明: fix-base-sync-staleness-tz、fix-kb-progress-tz、fix-mochat-ts-naive 为已知个案修复卡，本卡为全库清点；对应站点在 §6 标注

## 1. 复现口径（扫描命令）

```bash
# 在基于 origin/main 的 worktree 根目录执行
git fetch origin main && git rev-parse origin/main   # 记录基线 commit
rg -n --no-heading -g '*.py' 'datetime\.now\(\)' deeptutor          # A: naive 构造
rg -n --no-heading -g '*.py' 'datetime\.utcnow\(\)' deeptutor       # A: 已弃用 naive UTC（结果: 0）
rg -n --no-heading -g '*.py' 'datetime\(\s*[0-9]{4}[^)]*\)' deeptutor  # A: naive ctor 复核
rg -n --no-heading -g '*.py' 'fromtimestamp\([^,)]*\)' deeptutor    # A: 本地时区解释
rg -n --no-heading -g '*.py' 'replace\(tzinfo=None\)\.isoformat' deeptutor  # B: naive-UTC 写入
rg -n --no-heading -g '*.py' 'fromisoformat\([^)]*\.replace' deeptutor      # B: aware 解析点
rg -n --no-heading -g '*.py' '(isoformat\(\)|strftime\("%Y[^"]*"\))' deeptutor  # C: 序列化丢时区
rg -n --no-heading -g '*.py' 'datetime\.now\(\)\s*-|fromisoformat\([^)]*\)\s*[<>]' deeptutor  # D: 跨时区比较
# tests/ 路径已剔除；完整脚本见 scan_commands.sh（输出 findings_full.tsv）
```

## 2. 风险分级定义

| 级 | 含义 | 判据 |
|---|---|---|
| HIGH | 已构成 naive/aware 混用边界，或 naive-UTC 写入被按本地时区解析；跨主机/DST 即错 | 比较/解析点人读代码确认 |
| MEDIUM | naive 时间戳持久化（isoformat/strftime 无偏移），单机同口径内自洽，换主机时区或与 aware 端互通即漂移 | 写入侧静态可判 |
| LOW | 仅用于 ID 生成/纯展示字符串（`%Y%m%d_%H%M%S` 等），无时间计算 | 用途静态可判 |

## 3. 总量与分类

- 唯一站点: **180**（HIGH 16 / MEDIUM 142 / LOW 22）
- 分类（一行可属多类，已并站去重）: A naive 构造 103（HIGH 4 / MEDIUM 77 / LOW 22）· B UTC 混用 11（全 HIGH）· C 序列化丢时区 65（全 MEDIUM）· D 跨时区比较 1（HIGH）
- `datetime.utcnow()` 全库 0 处；`datetime.now(timezone.utc)` aware 写入 65 处（口径对照，未计入站点）
- 逐条证据: `findings_full.tsv`（列: category, path, line, snippet, risk）

## 4. 模块分布（唯一站点数）

| 模块 | HIGH | MEDIUM | LOW | 计 | 说明 |
|---|---|---|---|---|---|
| deeptutor/services | 7 | 60 | 7 | 74 | 记忆/会话/搜索/调度，时区敏感面最大 |
| deeptutor/knowledge | 4 | 30 | 0 | 34 | KB 进度/同步/孤儿回收（已知卡集中区） |
| deeptutor/api | 1 | 17 | 5 | 23 | 路由层时间戳/任务元数据 |
| deeptutor/agents | 0 | 11 | 0 | 11 | research 状态持久化 |
| deeptutor/co_writer | 0 | 0 | 7 | 7 | operation_id，仅 ID 用途 |
| deeptutor/multi_user | 0 | 7 | 0 | 7 | 用户侧时间戳 |
| deeptutor/partners | 3 | 1 | 0 | 4 | mochat 通道（已知卡） |
| 其余（book/tools/video_learning/logging/plugins/capabilities/events/learning/reading） | 1 | 15 | 3 | 19 | 分散站点 |

## 5. HIGH 热点（修复候选，全部经人工读码确认）

| # | path:line | 问题 |
|---|---|---|
| 1 | deeptutor/knowledge/manager.py:104 | `fromisoformat(raw) > cutoff`，raw 若带偏移则 aware>naive 抛 TypeError（未捕获），孤儿回收中断 → 建议比较前统一 tz 归一 |
| 2 | deeptutor/knowledge/manager.py:687 | `datetime.now()` naive 作为 grace_cutoff，供 #1 比较 |
| 3 | deeptutor/knowledge/manager.py:2148 | `fromtimestamp(st_mtime)` 无 tz → naive 本地；与存储的 sync 状态字符串比对，换机/DST 即误判未变更【fix-base-sync-staleness-tz】 |
| 4 | deeptutor/knowledge/manager.py:2222 | 同 #3，扫描回填路径 |
| 5 | deeptutor/api/routers/knowledge.py:1197 | 同 #3，linked-folder mtimes 收集 |
| 6 | deeptutor/api/routers/knowledge.py:4422 | `datetime.now() - fromisoformat(progress_ts)`，aware 进度串 → TypeError 被 except 吞掉返回 None，进度年龄判定失效【fix-kb-progress-tz】 |
| 7 | deeptutor/partners/channels/mochat.py:118 | 写 naive-UTC 串（`now(utc).replace(tzinfo=None)`）【fix-mochat-ts-naive】 |
| 8 | deeptutor/partners/channels/mochat.py:222 | 读侧 `fromisoformat(value).timestamp()`：无偏移串按本地时区解释 → 去重/排序窗口偏差 = 主机 UTC 偏移【fix-mochat-ts-naive】 |
| 9 | deeptutor/partners/channels/mochat.py:1013 | 同 #7 |
| 10 | deeptutor/book/storage.py:370 | naive-UTC+`timespec` 写入，读侧若走 naive 解析同 #8 |
| 11 | deeptutor/services/parsing/cache.py:88 | naive-UTC 串手拼 `+"Z"` 补偏移，写读两端约定脆弱 |
| 12 | deeptutor/services/rag/index_versioning.py:320 | 同 #11 |
| 13 | deeptutor/services/rag/pipelines/graphrag/storage.py:110 | 同 #11 |
| 14 | deeptutor/services/rag/pipelines/lightrag/storage.py:295 | 同 #11 |
| 15 | deeptutor/services/rag/pipelines/pageindex/storage.py:77 | 同 #11 |
| 16 | deeptutor/services/session/pocketbase_store.py:98 | `Z→+00:00` 解析正确，但与库内 naive 串共存，双口径并存点 |

MEDIUM 中最大簇: services 搜索 provider `timestamp=now().isoformat()` 17 处（展示/排序）；knowledge 进度/初始化/添加文档 30 处；agents/research 状态 11 处。

## 6. 与已知个案卡的关系

- fix-base-sync-staleness-tz → 热点 #3-#5（linked-folder mtime 比对）
- fix-kb-progress-tz → 热点 #6（进度年龄计算）及 knowledge 模块 MEDIUM 簇
- fix-mochat-ts-naive → 热点 #7-#9（mochat naive-UTC 双口径）
- 本卡新增: 热点 #1-#2（孤儿回收 TypeError 面）、#10-#16（naive-UTC+手动 Z 补丁族）为清点新增候选

## 7. 修复候选清单（按优先级）

1. P0 统一比较边界: manager.py:104/687 与 knowledge.py:4422 —— 解析后 `tzinfo is None` 则 `replace(tzinfo=timezone.utc)`（或约定全部 naive-UTC）再比较，并补 TypeError 捕获
2. P0 mochat 双口径: 写侧去掉 `replace(tzinfo=None)` 改为真 UTC ISO（或读侧统一 `Z/+00:00` 归一）
3. P1 sync mtime: manager.py:2148/2222 与 knowledge.py:1197 改 `fromtimestamp(ts, tz=timezone.utc)`，存量串做一次性迁移或双读兼容
4. P1 naive-UTC+手拼 Z 族（parsing/cache、rag ×4、book/storage）: 统一改 `datetime.now(timezone.utc).isoformat()`，删手拼后缀
5. P2 持久化时间戳 MEDIUM 簇（142 处）按模块渐进替换为 `now(timezone.utc).isoformat()`；存量 naive 串按“读时归一”兼容
6. P3 LOW 22 处（ID/展示）可不动，建议注释标注本地时区语义

## 8. 校验

- 口径可复现: `scan_commands.sh` 全部命令仅含 `rg`/`git` 只读操作
- 本卡未修改任何源码；evidence 目录外无变更（`git status` 仅 evidence/）
