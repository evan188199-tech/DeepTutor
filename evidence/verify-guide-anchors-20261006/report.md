# guide-* 候选卡行号锚点抽检表（AGEN-899，2026-10-06）

- 基线：origin/main `f07029cfc`（release v1.6.13），只读核对，未改产品代码
- 样本：15 / 57 张 guide-* 卡（约 26%，旧卡 7 张 + 新卡 8 张，覆盖储备池首尾）
- 判定口径：
  - **有效** = 锚点在 main 上可唯一定位且内容与卡描述相符
  - **可定位（前缀漂移）** = 卡写的是仓库根相对路径（`services/…`、`routers/…`、`runtime/…`），实际带 `deeptutor/` 前缀，按字面查找落空、按前缀补全可定位
  - **内容漂移** = 路径存在但描述的行为/结构已变化
  - **失效** = 锚点对象在 main 上不存在
- 卡内未发现任何带行号的 `path:line` 字面锚点（行号都是产出导读时才落）；guide-search-providers 卡内 4 处行数声明逐一核对。

## 抽检表（卡 key × 锚点 × 结论）

| 卡 key | 新旧 | 锚点（卡面写法） | main 实际位置 | 结论 |
|---|---|---|---|---|
| guide-question | 旧 | `deeptutor/agents/question/pipeline.py` "两阶段编排" | 存在；实际为 explore→plan→quiz 三阶段（pipeline.py:95-97、556-587） | 内容漂移 |
| guide-question | 旧 | `api/routers/question.py` "Tee 与 WebSocket 出口" | 实际 `deeptutor/api/routers/question.py`（578 行）；`Tee` 全仓 0 命中，仅存在于 myfork 测试分支（b27d2b686 stdout 拦截语境） | 失效 + 前缀漂移 |
| guide-question | 旧 | capability manifest "ideation→generation" | `deeptutor/agents/question/capability.py:33` 仍写 `stages=["ideation","generation"]`，与 pipeline 三阶段并存，易误导 | 内容漂移 |
| guide-storage | 旧 | `deeptutor/services/storage/file_library.py` 增删查 | add_file:212 / get_file:293 / delete_file:307 / list_files:371 | 有效 |
| guide-storage | 旧 | 父目录遍历/清理 | file_library.py:198-203 空 parent 清理链 | 有效 |
| guide-cowriter | 旧 | `routers/co_writer.py`（246 缺失 / 40.0%） | 实际 `deeptutor/api/routers/co_writer.py`（874 行）；覆盖率数字为时点数据，未复核 | 可定位（前缀漂移） |
| guide-cowriter | 旧 | docx_converter 吞错（DT-22 条目） | `deeptutor/co_writer/docx_converter.py` 存在 | 有效 |
| guide-config | 旧 | `deeptutor/config/settings.py` | 存在 | 有效 |
| guide-config | 旧 | `services/config` loader/model_catalog/capabilities_settings | `deeptutor/services/config/{loader,model_catalog,capabilities_settings}.py` 均在 | 可定位（前缀省略） |
| guide-config | 旧 | settings_spec 规格；draft→apply；tests/services/config | `deeptutor/services/config/settings_spec.py`、settings_draft.py（SettingsDraftService）、apply 在 `deeptutor/api/routers/settings.py`；tests/services/config 在 | 有效 |
| guide-i18n | 旧 | `deeptutor/i18n` 键文件结构 | metadata_i18n.py / status_i18n.py 在 | 有效 |
| guide-i18n | 旧 | `services/i18n.py` 语言协商 | 实际 `deeptutor/services/i18n.py`（current_language:113） | 可定位（前缀漂移） |
| guide-i18n | 旧 | web localization 加载 | web/package.json `i18n:check` 脚本在 | 有效 |
| guide-visualize | 旧 | VisualizationViewer（Mermaid 渲染组件） | `web/components/visualize/VisualizationViewer.tsx`（含 mermaid） | 有效 |
| guide-visualize | 旧 | 可视化触发入口 / 失败降级 | web/components/visualize/ 目录齐全（含降级面板） | 有效 |
| guide-runtime | 旧 | launcher `_handoff_pending_update` | `deeptutor/runtime/launcher.py:1211` | 有效 |
| guide-runtime | 旧 | `update_worker.py` 任务状态机 | 实际 `deeptutor/runtime/update_worker.py` 存在，但状态机（JobStatus）与 UpdateJobStore 定义在 `deeptutor/services/app_update.py:38`，update_worker 为消费方 | 内容漂移（位置表述） |
| guide-runtime | 旧 | job store 持久化 | UpdateJobStore 被 update_worker.py:14,113 引用 | 有效 |
| guide-launcher | 新 | `deeptutor/runtime/launcher.py` PathService / `_terminate` / `_handoff_pending_update` | launcher.py:143 / :254 / :1211 三符号全部命中 | 有效 |
| guide-launcher | 新 | `runtime/update_worker.py` | 实际 `deeptutor/runtime/update_worker.py`（158 行） | 可定位（前缀漂移） |
| guide-launcher | 新 | `deeptutor_cli/init_cmd.py` | 存在 | 有效 |
| guide-app-update | 新 | `deeptutor/services/app_update.py` | 存在，状态机完整 | 有效 |
| guide-app-update | 新 | `runtime/update_worker.py`、`runtime/launcher.py` | 均在 `deeptutor/runtime/` 下 | 可定位（前缀漂移 ×2） |
| guide-app-update | 新 | web 设置页版本展示 | `web/lib/version.ts`、`web/lib/app-update.ts` 在 | 有效 |
| guide-task-board | 新 | `services/task_board.py` 数据模型含 DB CHECK | 实际 `deeptutor/services/task_board.py`（CHECK 约束 :79-80） | 可定位（前缀省略）+ 有效 |
| guide-task-board | 新 | `web/app/(workspace)/kanban/` | 存在 | 有效 |
| guide-task-board | 新 | `web/lib/task-board-api.ts` | 存在 | 有效 |
| guide-task-board | 新 | `tests/multi_user/test_task_board.py` | 存在 | 有效 |
| guide-capabilities | 新 | `registry.py`/`protocol.py` | `deeptutor/capabilities/{registry,protocol}.py` 在 | 有效 |
| guide-capabilities | 新 | binding 装配 | `deeptutor/capabilities/setup/binding.py` 在 | 有效 |
| guide-capabilities | 新 | loop | LoopCapabilitySpec（registry.py:28）、LoopExtension（protocol.py:38） | 有效 |
| guide-capabilities | 新 | mode | capabilities 树内无同名代码对象（概念性说法，导读落笔时需落到具体模块） | 未定 |
| guide-capabilities | 新 | prompts/ 目录组织 | `deeptutor/capabilities/prompts/{en,zh}` 在 | 有效 |
| guide-search-providers | 新 | `services/search/providers/` | `deeptutor/services/search/providers/` 在 | 可定位（前缀省略） |
| guide-search-providers | 新 | zhipu 142 行 | zhipu.py = 142 行，精确 | 有效 |
| guide-search-providers | 新 | firecrawl 136 行 | firecrawl.py = 136 行，精确 | 有效 |
| guide-search-providers | 新 | searxng 104 行 | searxng.py = 104 行，精确 | 有效 |
| guide-search-providers | 新 | duckduckgo 65 行 | duckduckgo.py = 65 行，精确 | 有效 |
| guide-web-contracts | 新 | `generate-contracts.mjs` | `web/scripts/generate-contracts.mjs` 在 | 有效 |
| guide-web-contracts | 新 | `export_frontend_contracts.py` | `scripts/export_frontend_contracts.py` 在（wrapper → deeptutor/api/contracts/export.py） | 有效 |
| guide-web-contracts | 新 | contracts:check 门禁 | web/package.json:18 在 | 有效 |
| guide-rag-eval | 新 | `services/rag/eval/` dataset/matching | `deeptutor/services/rag/eval/{dataset,matching}.py` 在（EvalDataset:82） | 可定位（前缀省略）+ 有效 |
| guide-memory | 新 | `services/memory/snapshot/*`（快照与适配器） | `deeptutor/services/memory/snapshot/`（含 adapters.py） | 可定位（前缀省略）+ 有效 |
| guide-memory | 新 | consolidator audit/dedup/_runtime 三模式 | `deeptutor/services/memory/consolidator/modes/{audit,dedup,_runtime}.py` 全部命中 | 有效 |

## 效率统计

- 抽检卡：15 张（旧 7 / 新 8，约占储备池 26%），锚点核对项合计 44 项（上表每行 1 项）
- 仍有效：30（68%）；可定位但需前缀补全：9（20%）；内容漂移：3（7%）；失效：1（2%）；未定：1（2%）
- 路径可在 main 定位（含前缀补全）：43/44（98%）；按卡面字面路径直查可命中：34/44（77%）
- 带行号的字面 `path:line` 锚点：0（guide 卡均把行号留给导读产出时落）；卡内行数声明 4 处全部精确命中
- 抽检用量：全部为本地 grep/find/git 只读操作，无网络调用、无测试进程

## 需重写/修订卡清单（每卡一句修正建议）

1. **guide-question — 建议重写**：`Tee` 锚点在 main 已不存在（仅存在于 myfork 测试分支的 stdout 拦截测试语境），"两阶段 ideation→generation" 与 main 现状 explore→plan→quiz 三阶段不符，建议改写为三阶段编排并删除 Tee 说法（capability.py:33 的 manifest 旧 stages 保留，导读时需点破两者差异）。
2. **guide-runtime — 小修**：任务状态机与 job store 实际定义在 `deeptutor/services/app_update.py`（JobStatus:38、UpdateJobStore），update_worker.py 只是消费方，建议把锚点指向 app_update.py。
3. **guide-cowriter — 小修**：路径补全为 `deeptutor/api/routers/co_writer.py`，docx_converter 指向 `deeptutor/co_writer/docx_converter.py`，覆盖率数字（246 缺失/40.0%）建议加"时点数据"标注。

## 系统性发现与建议

- **前缀省略是系统性现象**：44 个核对项中 9 项（20%）按卡面字面路径直查会落空，全部是漏写 `deeptutor/` 前缀（`services/…`→`deeptutor/services/…` 等）。建议储备卡模板统一写仓库内完整路径，或在导读消费脚本里对缺失前缀做 `deeptutor/` 补全重试；现有仅前缀漂移的卡不需重写。
