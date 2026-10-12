# docs/ 代码引用锚点腐烂抽查报告（AGEN-1837）

- 核对基线：`origin/main @ 6cf793bd8`（release v1.6.14，2026-10-12 worktree `/Users/Shared/DeepTutor/.wt-agen1837-docsanchors`）
- 文档自decl基线：`fe003ddce`（2026-10-04，v1.6.12，两份 guide 头部声明）
- 生成时间：2026-10-12 02:30 UTC

## 结论

| 状态 | 数量 | 占比 |
| --- | --- | --- |
| 有效（valid，行内容与基线逐字一致或符号在位） | 240 | 70.6% |
| 漂移（drifted，内容仍在但行号已移动） | 97 | 28.5% |
| 失效（dead，内容/符号已不存在） | 3 | 0.9% |
| **腐烂率（漂移+失效）** | **100** | **29.4%** |

- 锚点全量抽取：340 个（覆盖 docs/ 全部 5 个 markdown；INDEXING_RECOVERY.md 与 SCIENTIFIC_RESEARCH.md 为纯散文+API/符号引用，无 path:line 锚点）
- 验证深度：内容级比对（基线行内容 vs 当前行内容 + 邻域评分重定位 + 符号定义搜索），337/340（99%）为内容/符号级验证，满足并超出 ≥60% 抽样验收线（实际为全量验证）
- 基线交叉核验：100 个非有效锚点在 `fe003ddce` 基线全部为 ok-at-baseline —— **两份 guide 撰写当时全部准确，腐烂全部发生在基线之后（v1.6.12 → v1.6.14 演进）**，无撰写期错误

## 分文档统计

| 文档 | 有效 | 漂移 | 失效 |
| --- | --- | --- | --- |
| `docs/INDEXING_RECOVERY.md` | 4 | 0 | 0 |
| `docs/SCIENTIFIC_RESEARCH.md` | 4 | 0 | 0 |
| `docs/guides/events-and-progress-chain.md` | 90 | 29 | 2 |
| `docs/guides/tools-surface.md` | 136 | 68 | 1 |
| `docs/plugin-platform-rfc.md` | 6 | 0 | 0 |

## 失效锚点（3 条）及现状

| # | 文档 | 原锚点 | 原含义 | 现状 |
| --- | --- | --- | --- | --- |
| 1 | events guide §7 | `knowledge.py:4387` | websocket_progress 时间戳解析吞错点 | 该行内容已不存在：整个 handler 区块重写并整体后移（`websocket_progress` 现 `knowledge.py:4429`），freshness 判定现约 `knowledge.py:4551-4563`；原文档列的吞错写法已不在，需按新代码重写该条 |
| 2 | events guide §7 | `knowledge.py:4433` | 时间戳解析吞错点（第二处） | 同上，内容已不存在；建议按 `knowledge.py:4551-4563` 一带重核 |
| 3 | tools guide §2 | `tool_composition.py:262` | 常开工具 5 件套（write_memory/web_fetch/github/ask_user/cron） | 该行已改为 7 件多行元组：新增 `learning_status`、`learning_update`，现状 `deeptutor/agents/_shared/tool_composition.py:262-271` |

## 漂移集中区（可按文件批量更新行号）

| 文件 | 漂移锚点数 | 典型位移 |
| --- | --- | --- |
| `deeptutor/tools/builtin/__init__.py` | 36 | 工具类区块整体 +77（KbFilesTool 227→304、AskUserTool 1493→1570、CronTool 1789→1866、USER_TOGGLEABLE 1907→1984、CONFIGURABLE 1932→2009） |
| `deeptutor/api/routers/knowledge.py` | 26 | websocket_progress 区块整体 +173（4256→4429）；SSE 路由 3299→3379；emit 边界 1059/1110/3961/3990→1066/1117/4042/4079；run_reindex_task 3718→3798 |
| `deeptutor/agents/_shared/tool_composition.py` | 13 | +3~+12（compose_enabled_tools 170→174、user_has_* +12、_finalize 268→280） |
| `deeptutor/runtime/registry/tool_registry.py` | 7 | +2~+24（get 96→119、execute 151→174、get_tool_registry 170→194） |
| `deeptutor/tools/builtin_specs.py` | 6 | BUILTIN_TOOL_NAMES 207→223、TOOL_ALIASES 217→233、LazyBuiltinToolTypes 228→244、capabilities 段 96-204→111-219 |
| `deeptutor/agents/loop/pipeline.py` | 5 | +5~+8（_augment_tool_kwargs 1323→1328、_cron_owner 注入 1366→1374） |
| `deeptutor/services/partners/manager.py` | 2 | 逐条见 CSV |
| `deeptutor/api/routers/mastery_path.py` | 1 | 逐条见 CSV |
| `deeptutor/capabilities/registry.py` | 1 | 逐条见 CSV |

跨文件迁移 1 条：`PARTNER_BUILTIN_TOOL_NAMES` 已从 `builtin/__init__.py:208` 迁至 `deeptutor/tools/builtin_specs.py:224`（partner_memory.py:26 处的同名定义仍有效）。

## 修复建议

1. `docs/guides/events-and-progress-chain.md`：§3.1 决策树/吞错点、§6 防护表、§7 薄弱点的 knowledge.py 系锚点按 +173 区块位移整体更新（逐条新行号已写入 CSV `current_ref` 列）；§7 第 2 条（时间戳解析吞错）按 `knowledge.py:4551-4563` 一带重写；WS 锚点建议核对 `mastery_path.py:791`（`@ws_router.websocket("/mastery-paths")`）
2. `docs/guides/tools-surface.md`：§4.1/§4.2 工具卡与 §5 挂载类别表的 builtin/__init__.py 系锚点按 +77 位移更新；§5 `PARTNER_BUILTIN_TOOL_NAMES:208` 改指 `builtin_specs.py:224`；§2 常开集合补 `learning_status`/`learning_update` 并更新 `:262` 锚点
3. `docs/INDEXING_RECOVERY.md`、`docs/SCIENTIFIC_RESEARCH.md`、`docs/plugin-platform-rfc.md`：无 path:line 锚点，14 个符号/路由/文件存在性引用全部有效，无需修复
4. 建议两份 guide 头部在基线行追加复核戳（如 `anchors re-checked @ 6cf793bd8 2026-10-12`），后续再腐烂可快速定位增量

## 方法与可复现性

- 抽取：正则全量提取 `path:line`、短名 `file:line`、相对 `:N`（上下文文件解析）与 `` `Symbol:N` ``（仓库级定义解析），另含 3 个正则盲区补录与 14 个散文层存在性锚点
- 判定：以"基线行内容 vs 当前行内容"逐行比对为唯一地面真值；内容移动按邻域评分（±2 行一致性）重定位；符号锚点另做 def/class/常量定义搜索；不修改任何仓库文件
- 工具：`verify_anchors.py`（本目录）；明细：`anchor_inventory.csv`（340 行 × 状态/基线状态/现状 path:line/备注）；汇总：`summary.json`
- 上游去重：`myfork` 无 `verify-guide-anchors-*` 分支、无同轴 evidence 分支（`agen485/docs-drift-scan` 为内容漂移轴），无撞车
