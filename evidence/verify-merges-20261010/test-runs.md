# 测试运行记录（AGEN-1569，v1.6.14 窗口）

全部命令在 worktree `dt-agen1569-verify-wt`（= origin/main 6cf793bd8）内、以
`perl -e 'alarm shift; exec @ARGV' 900 <cmd>` 限时执行；解释器 `/Users/Shared/DeepTutor/.venv/bin/python`。
web 命令在 `web/` 子目录执行（node_modules 为指向主 checkout 的符号链接）。

## Python 子集

| # | 命令（pytest -q -p no:cacheprovider 之后的部分） | 结果 |
|---|---|---|
| 1 | tests/services/memory/test_snapshot_workspace_aggregation.py | 11 passed in 0.51s |
| 2 | tests/services/session/test_sqlite_store.py | 49 passed in 0.95s |
| 3 | tests/services/rag/test_visual_assets.py tests/services/rag/test_source_visual_grounding.py tests/services/rag/test_llamaindex_pipeline_stall.py | 47 passed, 2 skipped in 38.67s |
| 4 | tests/knowledge/test_indexing_run.py tests/services/rag/test_llamaindex_storage_layout.py tests/services/rag/test_embedding_binding.py tests/services/rag/test_rag_pipelines.py | 61 passed in 2.24s |
| 5 | deeptutor/learning/tests/test_visual_learning_workflow.py tests/agents/chat/test_agent_loop.py | 1 failed, 115 passed（首次 51.43s；环境修复后复跑 46.00s，失败项不变） |
| 6 | tests/agents/chat/test_agent_loop.py::test_cold_start_stalled_provider_settles_with_bounded_retries | 1 failed, 2 passed（复跑 3 次一致） |
| 7 | tests/services/learning_journal/test_store.py tests/api/test_learning_journal.py tests/tools/test_learning_journal_tools.py tests/agents/chat/test_learning_journal_injection.py tests/agents/chat/test_context_budget.py tests/api/test_unified_ws_turn_runtime.py | 初跑 2 failed, 59 passed（缺 data/user/workspace）；补拷后 61 passed in 3.15s |
| 8 | tests/plugins/ tests/api/test_plugins_router.py tests/test_packaging_metadata.py | 121 passed in 40.33s |
| 9 | tests/services/research/ tests/services/mcp/test_catalog.py | 98 passed in 0.74s |
| 10 | tests/video_learning/test_reading_migration.py tests/video_learning/test_turn_wiring.py tests/video_learning/test_invidious_account.py tests/video_learning/test_marks.py tests/api/test_session_watching_migration.py tests/core/test_capabilities_runtime.py | 61 passed in 2.50s |
| 11 | tests/services/parsing/test_mineru_local_failures.py tests/tools/test_mineru.py | 42 passed in 0.52s |
| 12 | tests/services/mcp/ | 176 passed in 2.08s |
| 13 | tests/services/memory/test_snapshot_adapters.py tests/services/workspace/test_content_workspace.py | 35 passed in 0.70s |

Python 合计：877 passed / 1 failed / 2 skipped。

## 唯一失败项

- 用例：tests/agents/chat/test_agent_loop.py::test_cold_start_stalled_provider_settles_with_bounded_retries[partial_stream]
- 断言：tests/agents/chat/test_agent_loop.py:2434 — `sum(e.metadata.get("error_code") == "provider_transport" for e in events) >= 1` 实得 0
- 稳定性：单跑、全文件跑、多次复跑均稳定失败；connect/stream 两参数通过
- 探针（detached 临时 worktree，均已移除）：
  - 081c9e6d9（#1421，该测试引入提交）：1 failed, 2 passed —— 出生即红
  - 2350ea2db^（#1611 第二提交之前）：1 failed, 2 passed —— 早于审计项改动
  - 结论：与 11 项审计对象无因果，归因 #1421 自带偏差

## 环境性失败排除记录

- tests/agents/chat/test_context_budget.py 两用例（turn_result_carries_the_context_budget、forced_finish_still_reports_the_tools_the_turn_carried）初跑报
  `WorkspaceError: The selected workspace folder does not exist.`（deeptutor/services/workspace/service.py:210，经 pipeline.py:401 默认工作区绑定）
- v1.6.13 基线探针（f07029cfc，同一环境）：同样 2 failed, 16 passed —— 证明环境性
- 根因：worktree 缺 `data/user/workspace`（默认绑定根目录）；补拷后 61 全绿

## Web 子集

| # | 命令（cwd=web/） | 结果 |
|---|---|---|
| 14 | ./node_modules/.bin/vitest run tests/settings-unified-draft.spec.tsx tests/chat-failed-submission-recovery.spec.tsx | 2 files, 47 passed in 2.89s |
| 15 | node ./scripts/run-node-tests.mjs | # pass 1303 / # fail 0（全量 *.test.ts 编译集，1.43s） |
| 16 | ./node_modules/.bin/vitest run <14 个窗口相关 spec>（mcp-private-origin、kb-indexing-run、kb-visual-coverage、mastery-question-card、learning-journal-panel、watching-browser、media-reading-stage、invidious-account-feedback、chat-branch-navigator、chat/ChatWorkspace.smoke、integration/ask-user-trace-continuity、integration/chat-messages、integration/mastery-teaching、learning-dashboard） | 14 files, 63 passed in 3.22s |

未执行：Playwright `.audit.ts` / e2e 面（需浏览器与应用运行时）。

## 去重说明

- v1.6.13 窗口卡（AGEN-1112）已覆盖的模块（web_source 双语、video_learning marks、mineru 本地失败、KB 状态/进度/目录同步、audio_overview）未重跑；
  仅 #1612 触及 parsing 引擎文件，补跑 mineru 既有子集一次（#11，42 passed）。
- 单模块补测卡（如 audio_overview pipeline）只汇总不重做。
