# 上游 v1.6.14 窗口合并模块回归抽测（AGEN-1569）

- 日期：2026-10-10/11
- 基线：`origin/main` = `6cf793bd8`（release: v1.6.14，即窗口终点；fetch 后新 worktree + 新分支 `evidence/verify-merges-20261010`，主 checkout `/Users/Shared/DeepTutor` 全程未动，只读拷贝运行时配置）
- 窗口范围：`f07029cfc`（release: v1.6.13）→ `6cf793bd8`（release: v1.6.14）
- 审计对象：任务卡列出的 11 项。其中 1629/1307/1612/1611/1610/1407/1378/1799/1802 为上游 **issue 号**（squash 合入 main 的提交以 issue 号标注），1789/1798 为 PR 号；对应窗口提交：
  - #1629 → `1e7eef0e9`（research primitives + 私有 MCP origins）
  - #1307 → `7885daa98`（plugins 受管生命周期 + runtime gates）
  - #1612 → `e79e1b0ad`（长文档索引可恢复）
  - #1611 → `2350ea2db` + `2ccd8a75f`（mastery 视觉练习 + agent loop 源图投递）
  - #1610 → `de64a9aa0` + `30022c769`（exact source visual / PDF page grounding + 视觉覆盖懒加载）
  - #1407 → `64bc0d8e7`（workspace journal overview）
  - #1378 → `8986c3158`（Watching 收敛 + legacy 迁移）
  - PR 1789 → `fdebb2761`（parked ask_user 跨删除/重载存活）
  - PR 1798 → `510fe3a74`（MinerU 云 API 幻影未保存更改；纯 web）
  - #1799 → `5b2b99fab`（PR 1800，account 级 L1 跨 workspace 聚合）
  - #1802 → `b0521ac3f`（移除 corpus manifest 16MB 上限，索引前发布 figures）
- 方法：每模块跑既有聚焦测试子集，`python -m pytest -q -p no:cacheprovider`，perl alarm 限时 900s；web 侧跑 vitest 组件子集与 `run-node-tests.mjs` 全量 node 测试；不改任何代码。
- 去重：v1.6.13 窗口卡（AGEN-1112，`myfork/evidence/verify-recent-merges-tests-2026-10-07`）已覆盖 web_source 双语、video_learning marks、mineru 本地失败、KB 状态/进度/目录同步、audio_overview，本卡不重跑；仅因 #1612 触及 parsing 引擎文件补跑一次 mineru 既有子集（42 passed）。单模块补测卡（audio_overview pipeline 等）只汇总不重做。

## 模块 × 测试 × 结果 × 缺口

| 项 | 模块 | 测试子集 | 结果 | 缺口/备注 |
|---|---|---|---|---|
| #1629 | research primitives + MCP 私有 origins | tests/services/research/（primitives、mcp_boundaries）、tests/services/mcp/（9 文件全量 176）；web mcp-private-origin.spec.tsx、mcp-server-config.test.ts（node 集） | 通过（py 274 passed；web vitest/node 均 pass） | agents/research/{pipeline,capability}.py 无直接单测，靠 services 层与 registry 测试间接触达；mcp/network.py 仅经 manager/oauth 用例间接覆盖 |
| #1307 | plugins 平台 | tests/plugins/（12 文件）、tests/api/test_plugins_router.py、tests/test_packaging_metadata.py | 通过（121 passed） | 覆盖充分；reading/extensions.py、api/main.py 装配线仅间接触达 |
| #1612 | knowledge 长文档索引可恢复 | tests/knowledge/test_indexing_run.py、tests/services/rag/{llamaindex_storage_layout,embedding_binding,rag_pipelines}.py；另补 mineru 子集（1612 触及 parsing 引擎） | 通过（61 + 42 passed；web kb-indexing-run.spec.tsx pass） | services/rag/index_probe.py、index_versioning.py 无直接单测，经 pipeline 测试间接覆盖 |
| #1611 | mastery 视觉练习 + agent loop 源图 | deeptutor/learning/tests/test_visual_learning_workflow.py、tests/agents/chat/test_agent_loop.py；tests/services/rag/test_visual_assets.py；web mastery-question-card.spec.tsx | **失败 1**（115 passed） | 失败项见下节；web MasteryStudy.tsx / ObjectiveDetail.tsx 无组件单测 |
| #1610 | exact source visual / PDF grounding | tests/services/rag/{source_visual_grounding,visual_assets}.py、test_llamaindex_pipeline_stall.py；web kb-visual-coverage.spec.tsx | 通过（47 passed, 2 skipped，三文件共享运行） | 2 skipped 为 mineru 环境相关跳过项；KbFilesTab.tsx 无组件单测 |
| #1407 | workspace journal overview | tests/services/learning_journal/test_store.py、tests/api/test_learning_journal.py、tests/tools/test_learning_journal_tools.py、tests/agents/chat/{learning_journal_injection,context_budget}.py、tests/api/test_unified_ws_turn_runtime.py；web learning-journal-panel.spec.tsx | 通过（61 passed） | 覆盖充分；LearningJournalPanel 组件已有单测 |
| #1378 | Watching 收敛 + legacy 迁移 | tests/video_learning/{reading_migration,turn_wiring,invidious_account,marks}.py、tests/api/test_session_watching_migration.py、tests/core/test_capabilities_runtime.py；web watching-browser/media-reading-stage/invidious-account-feedback/chat-branch-navigator/ChatWorkspace.smoke/integration×3/learning-dashboard specs（63 passed 集） | 通过（61 passed） | 8986c3158 同一合并删除了 tests/video_learning/test_capability.py 且无同名替代（覆盖并入 migration/turn_wiring/session 迁移）；web WatchingPane.tsx / WatchingPlayer.tsx / WatchingWorkspace.tsx 无组件单测；watching-workspace.spec.tsx 被该合并移除 |
| PR 1789 | parked ask_user 跨删除/重载 | tests/services/session/test_sqlite_store.py；web chat-failed-submission-recovery.spec.tsx、chat-idle-recovery.test.ts（node 集） | 通过（49 passed） | 覆盖充分（store + 恢复 UI 双侧） |
| PR 1798 | MinerU 云设置幻影脏状态 | web settings-unified-draft.spec.tsx（vitest） | 通过（47 passed，两文件集） | 纯 web 改动，无后端面 |
| #1799 | memory L1 跨 workspace 聚合 | tests/services/memory/{snapshot_workspace_aggregation,snapshot_adapters}.py、tests/services/workspace/test_content_workspace.py | 通过（46 passed） | 覆盖充分（adapters + catalog 双侧） |
| #1802 | corpus manifest 上限移除 | tests/services/rag/{visual_assets,llamaindex_pipeline_stall}.py | 通过（47 passed 共享运行） | 覆盖充分 |

## 失败项（唯一）

`tests/agents/chat/test_agent_loop.py::test_cold_start_stalled_provider_settles_with_bounded_retries[partial_stream]`

- 断言位置：tests/agents/chat/test_agent_loop.py:2434（期望 bus 事件中 `error_code == "provider_transport"` 的事件数 ≥ 1，实得 0）
- 复跑 3 次均稳定失败（其余两个参数 connect/stream 通过）；非 flaky
- 归因：该测试由窗口内提交 `081c9e6d9`（#1421 bound cold-start stream waits）引入，且在其引入提交即失败（ detached worktree 实测 081c9e6d9 与 2350ea2db^ 两点均复现）；与本次审计 11 项的改动无因果，属窗口内 #1421 自带的测试/实现偏差

## 计数

- 模块结论：通过 10 / 失败 1 / 无直接测试 0（失败项为 #1611 触及文件内的窗口内既有失败，归因 #1421）
- Python：877 passed，1 failed，2 skipped（9 个子集，均远低于 900s 限时）
- Web vitest：110 passed（16 个 spec 文件）；Web node 测试：1303 pass / 0 fail（全量 *.test.ts 编译集）
- Playwright `.audit.ts` / e2e 面未执行（需浏览器与应用运行时，同 v1.6.13 卡口径）

## 补测候选

1. #1421 cold-start bounded-retries `[partial_stream]` 出生即红：建议上游澄清 partial_stream 路径是否应发 `provider_transport` 事件（修测试断言或修 `agent_loop` 事件发射）。
2. #1629 agents/research/{pipeline,capability}.py 直测缺口：primitives/registry 已覆盖，agent 编排面建议补 fake 级单测。
3. #1611 前端 MasteryStudy.tsx / ObjectiveDetail.tsx 无组件单测（mastery-question-card 已覆盖卡片面）。
4. #1378 前端 WatchingPane/WatchingPlayer/WatchingWorkspace 无组件单测，且 watching-workspace.spec.tsx 被合并移除无替代（延续 v1.6.13 卡 WatchingPane 缺口）。
5. #1612 services/rag/{index_probe,index_versioning}.py 无直接单测，建议补 probe/versioning 契约测试。
6. web Playwright `.audit.ts`/e2e 抽测基建（延续 v1.6.13 卡建议，本卡不重做）。

## 环境与执行注意（复跑者必读）

- 本机无 `timeout`/`gtimeout`，用 `perl -e 'alarm shift; exec @ARGV' 900 <cmd>` 限时。
- 解释器用主 checkout 的 `/Users/Shared/DeepTutor/.venv/bin/python`（Python 3.13.13 + pytest 9.1.1）；在 worktree 内运行时 cwd 优先级保证导入的是 worktree 代码（已验证 `deeptutor.__file__`）。
- 运行时数据只读拷贝三处：`data/user/settings`（**不含 auth.json**，拷入会引入假阴性，同 v1.6.13 卡结论）、`data/user/workspaces`、`data/user/workspace`。缺 `data/user/workspace` 时 `test_context_budget.py` 中 2 个用例因默认工作区绑定目录不存在而 `WorkspaceError` 失败——已在 v1.6.13 基线（f07029cfc）以相同环境复现，属环境性而非窗口回归；拷齐后 61 全绿。
- web 测试：worktree 无 `web/node_modules`，符号链接主 checkout 的 node_modules（只读使用）后 vitest 4.1.11 与 `node scripts/run-node-tests.mjs` 均可运行；`*.test.ts` 走 node 编译集，`*.spec.tsx` 走 vitest（include 见 web/vitest.config.mts）。
- 复跑探针用 detached 临时 worktree（081c9e6d9 / 2350ea2db^ / f07029cfc 三点），已全部移除。
