# 跨扫描报告种子台账（seed-ledger 2026-10-10）

- 基线：已发布清单 @ `origin/main f07029cfc`（v1.6.13）；
- 现势复核：`origin/main 6cf793bd8`（v1.6.14，本卡 fetch 于 2026-10-10，独立 worktree 新分支，只读）
- 三态口径：**已建卡**=看板存在指向该种子的非取消卡（依据=卡 key）；**已被main测试覆盖**=fresh 复扫中该模块触达数达到阈值（zero≥1 / weak≥2，依据=测试路径）；**仍可建卡**=两者皆无
- 汇总：种子 **372** 条 = 已建卡 219 + 已被main测试覆盖 22 + 仍可建卡 131
- 去重边界：weak100 三态沿用 AGEN-1154 triage（本卡不重排）；weak242 tail 的 23 个 fanin≥2 种子沿用 AGEN-1315；card→模块覆盖漂移方向见 AGEN-1316

## 轴汇总

| 轴 | 报告 | 种子 | 已建卡 | 已被main测试覆盖 | 仍可建卡 |
|---|---|---:|---:|---:|---:|
| B | evidence/cli-zero-triage-20261009（CLI 零测试 6 模块） | 6 | 6 | 0 | 0 |
| C | scan/weak-top100-triage-20261008（weak100 triage） | 100 | 80 | 8 | 12 |
| D | scan/channel-contracts-20261005（通道契约修复卡 A–M） | 13 | 4 | 0 | 9 |
| E | scan/error-messages-20261004（Top15 修复） | 15 | 12 | 0 | 3 |
| F | scan/coverage-gaps-20261007（zero96 + weak242 模块清单） | 238 | 117 | 14 | 107 |
| A | scan/todo-sweep-20261009 | 0（2 噪音，不建卡） | - | - | - |

## 轴 A：todo-sweep-20261009

内联 TODO/FIXME 清点：命中 2 处均为陈旧 docstring 噪音，报告结论 0 种子。

## 轴 B：cli-zero-triage-20261009（6 种子）

| ID | path | 三态 | 依据/卡 | 备注 |
|---|---|---|---|---|
| B1 | `deeptutor_cli/notebook.py` | 已建卡 | card AGEN-1368 |  |
| B2 | `deeptutor_cli/partner.py` | 已建卡 | card AGEN-1369 |  |
| B3 | `deeptutor_cli/session_cmd.py` | 已建卡 | card AGEN-1370 |  |
| B4 | `deeptutor_cli/_tool_result.py` | 已建卡 | card AGEN-1371 |  |
| B5 | `deeptutor_cli/book.py` | 已建卡 | card AGEN-1372 |  |
| B6 | `deeptutor_cli/memory.py` | 已建卡 | card AGEN-1373 |  |

## 轴 C：weak-triage-20261008 top100（100 种子，triage 分序）

| ID | rank | 模块 | LOC | fanin | score | 风险 | 三态 | 依据/卡 | 备注 |
|---|---|---|---:|---:|---:|---|---|---|---|
| C1 | 1 | `utils.json_parser` | 201 | 15 | 154 | 高 | 已建卡 | card AGEN-1276 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1276 |
| C2 | 2 | `services.rag.provider_binding` | 70 | 13 | 146 | 高 | 已建卡 | card AGEN-824 |  |
| C3 | 3 | `services.llm.structured_retry` | 111 | 11 | 127 | 高 | 已建卡 | card AGEN-1249 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1249 |
| C4 | 4 | `services.keypool` | 81 | 12 | 121 | 高 | 已建卡 | card AGEN-675 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-675 |
| C5 | 5 | `services.generation_http` | 94 | 11 | 111 | 高 | 已建卡 | card AGEN-1010 |  |
| C6 | 6 | `multi_user.tool_access` | 113 | 9 | 107 | 高 | 已建卡 | card AGEN-1250 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1250 |
| C7 | 7 | `learning.pending` | 283 | 8 | 100 | 高 | 已建卡 | card AGEN-793 |  |
| C8 | 8 | `utils.secret_files` | 48 | 10 | 100 | 高 | 已建卡 | card AGEN-1283 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1283 |
| C9 | 9 | `services.workspace.resources` | 223 | 8 | 99 | 高 | 已建卡 | card AGEN-1278 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1278 |
| C10 | 10 | `learning.assessment` | 557 | 6 | 85 | 高 | 已建卡 | card AGEN-1050 |  |
| C11 | 11 | `services.prompt.lookup` | 25 | 8 | 80 | 高 | 已建卡 | card AGEN-1284 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1284 |
| C12 | 12 | `services.llm.types` | 86 | 6 | 76 | 高 | 已建卡 | card AGEN-1249 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1249 |
| C13 | 13 | `services.parsing.engines.mineru.formats` | 46 | 6 | 75 | 高 | 已建卡 | card AGEN-1318 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1318 |
| C14 | 14 | `utils.document_validator` | 206 | 7 | 74 | 高 | 已被main测试覆盖 | tests/api/test_knowledge_upload_guards.py, tests/utils/test_document_validator.py |  |
| C15 | 15 | `runtime.coordination.protocol` | 74 | 4 | 71 | 高 | 已建卡 | card AGEN-1285 |  |
| C16 | 16 | `multi_user.personal_models` | 165 | 5 | 68 | 高 | 已建卡 | card AGEN-1281 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1281 |
| C17 | 17 | `services.rag.kb_paths` | 50 | 5 | 66 | 高 | 已建卡 | card AGEN-1253 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1253 |
| C18 | 18 | `book.agents.page_planner` | 427 | 4 | 63 | 中 | 已建卡 | card AGEN-966 |  |
| C19 | 19 | `runtime.agentic.labels` | 173 | 3 | 63 | 高 | 仍可建卡 | 报告种子（deeptutor/runtime/agentic/labels.py） |  |
| C20 | 20 | `services.rag.visual_assets` | 386 | 4 | 62 | 中 | 已被main测试覆盖 | tests/agents/chat/test_agent_loop.py, tests/services/rag/test_source_visual_grounding.py, tests/services/rag/test_visual_assets.py（共 4 个） |  |
| C21 | 21 | `runtime.agentic.tool_call_stream` | 110 | 3 | 62 | 高 | 已建卡 | card AGEN-1251 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1251 |
| C22 | 22 | `api.contracts.turn_protocol` | 309 | 4 | 61 | 中 | 已建卡 | card AGEN-1147 |  |
| C23 | 23 | `runtime.memory_reclaim` | 73 | 3 | 61 | 高 | 已建卡 | card AGEN-1252 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1252 |
| C24 | 24 | `services.session.organization` | 59 | 6 | 61 | 高 | 已建卡 | card AGEN-1280 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1280 |
| C25 | 25 | `services.session.workspace_preferences` | 55 | 6 | 61 | 高 | 仍可建卡 | 报告种子（deeptutor/services/session/workspace_preferences.py） | 漂移：v1.6.14 中唯一覆盖测试已消失（weak→zero） |
| C26 | 26 | `api.routers.co_writer` | 874 | 2 | 60 | 高 | 已被main测试覆盖 | tests/api/routers/test_co_writer_contract.py, tests/api/test_co_writer.py |  |
| C27 | 27 | `api.routers.question_notebook` | 595 | 2 | 60 | 高 | 已建卡 | card AGEN-838 |  |
| C28 | 28 | `agents.math_animator.request_config` | 38 | 6 | 60 | 高 | 已建卡 | card AGEN-1304 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1304 |
| C29 | 29 | `services.memory.consolidator.modes.merge` | 227 | 4 | 59 | 中 | 已建卡 | card AGEN-1302 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1302 |
| C30 | 30 | `learning.objective_relations` | 181 | 4 | 58 | 中 | 已建卡 | card AGEN-1133 |  |
| C31 | 31 | `services.embedding.validation` | 128 | 4 | 57 | 中 | 已建卡 | card AGEN-1282 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1282 |
| C32 | 32 | `services.llm.provider_core.codebuddy_provider` | 839 | 3 | 55 | 中 | 已建卡 | card AGEN-926 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-926 |
| C33 | 33 | `services.memory.consolidator.line_doc` | 482 | 3 | 54 | 中 | 已建卡 | card AGEN-1141 |  |
| C34 | 34 | `runtime.isolated_worker` | 215 | 2 | 54 | 高 | 已建卡 | card AGEN-1252 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1252 |
| C35 | 35 | `tools.vision.ggb_validator` | 411 | 3 | 53 | 中 | 已建卡 | card AGEN-977 |  |
| C36 | 36 | `tools.ask_user` | 383 | 3 | 52 | 中 | 已建卡 | card AGEN-94、card AGEN-99、card AGEN-349 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-94,AGEN-99,AGEN-349 |
| C37 | 37 | `services.mcp.network` | 121 | 5 | 52 | 高 | 已被main测试覆盖 | tests/services/mcp/test_mcp_config.py, tests/services/research/test_mcp_boundaries.py |  |
| C38 | 38 | `runtime.providers.authorize` | 59 | 2 | 51 | 高 | 已建卡 | card AGEN-1308 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1308 |
| C39 | 39 | `api.routers.partner_groups` | 534 | 1 | 50 | 高 | 已建卡 | card AGEN-763 |  |
| C40 | 40 | `services.parsing.engines._install` | 287 | 3 | 50 | 中 | 已建卡 | card AGEN-915 |  |
| C41 | 41 | `services.llm.provider_core.codebuddy_http_provider` | 258 | 3 | 50 | 中 | 仍可建卡 | 报告种子（deeptutor/services/llm/provider_core/codebuddy_http_provider.py） |  |
| C42 | 42 | `api.routers.space_mcp` | 460 | 1 | 49 | 高 | 已建卡 | card AGEN-780、card AGEN-864 |  |
| C43 | 43 | `services.rag.eval.matching` | 218 | 3 | 49 | 中 | 已建卡 | card AGEN-912 |  |
| C44 | 44 | `services.parsing.engines.tika.formats` | 217 | 3 | 49 | 中 | 仍可建卡 | 报告种子（deeptutor/services/parsing/engines/tika/formats.py） |  |
| C45 | 45 | `services.llm.error_mapping` | 175 | 3 | 48 | 中 | 已建卡 | card AGEN-1036 |  |
| C46 | 46 | `learning.event_hub` | 140 | 3 | 47 | 中 | 仍可建卡 | 报告种子（deeptutor/learning/event_hub.py） |  |
| C47 | 47 | `services.parsing.engines.markitdown.formats` | 102 | 3 | 47 | 中 | 仍可建卡 | 报告种子（deeptutor/services/parsing/engines/markitdown/formats.py） |  |
| C48 | 48 | `api.routers.skills` | 315 | 1 | 46 | 高 | 已建卡 | card AGEN-1319 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1319 |
| C49 | 49 | `services.workspace.navigation` | 81 | 3 | 46 | 中 | 仍可建卡 | 报告种子（deeptutor/services/workspace/navigation.py） |  |
| C50 | 50 | `multi_user.skill_access` | 74 | 3 | 46 | 中 | 已建卡 | card AGEN-1250 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1250 |
| C51 | 51 | `tools.mastery_nav` | 500 | 2 | 45 | 中 | 已建卡 | card AGEN-973 |  |
| C52 | 52 | `api.routers.subagents` | 288 | 1 | 45 | 高 | 已建卡 | card AGEN-1300 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1300 |
| C53 | 53 | `multi_user.learner_profile` | 49 | 3 | 45 | 中 | 已建卡 | card AGEN-1286 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1286 |
| C54 | 54 | `services.rag.pipelines.modes` | 48 | 3 | 45 | 中 | 已建卡 | card AGEN-1253 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1253 |
| C55 | 55 | `api.utils.http_headers` | 27 | 3 | 45 | 中 | 已建卡 | card AGEN-1320 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1320 |
| C56 | 56 | `capabilities.audio_overview.request_config` | 18 | 3 | 45 | 中 | 已建卡 | card AGEN-1321 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1321 |
| C57 | 57 | `services.voice.adapters.openai_compat` | 477 | 2 | 44 | 中 | 已建卡 | card AGEN-1056 |  |
| C58 | 58 | `runtime.background_leader` | 227 | 1 | 44 | 高 | 已建卡 | card AGEN-863 |  |
| C59 | 59 | `api.routers.space_cli_apps` | 222 | 1 | 44 | 高 | 已建卡 | card AGEN-833、card AGEN-864 |  |
| C60 | 60 | `events.event_bus` | 205 | 4 | 44 | 中 | 已建卡 | card AGEN-549 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-549 |
| C61 | 61 | `api.routers.file_preview` | 205 | 1 | 44 | 高 | 已建卡 | card AGEN-764 |  |
| C62 | 62 | `services.memory.consolidator.runs` | 405 | 2 | 43 | 中 | 仍可建卡 | 报告种子（deeptutor/services/memory/consolidator/runs.py） |  |
| C63 | 63 | `runtime.agentic.tool_arg_guard` | 195 | 1 | 43 | 高 | 已建卡 | card AGEN-1251 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1251 |
| C64 | 64 | `api.routers.file_library` | 169 | 1 | 43 | 高 | 已建卡 | card AGEN-432、card AGEN-457、card AGEN-802、card AGEN-922、card AGEN-1322、card AGEN-1361 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-432,AGEN-457,AGEN-802,AGEN-922,AGEN-1322,AGEN-1361 |
| C65 | 65 | `api.routers.personas` | 154 | 1 | 43 | 高 | 已建卡 | card AGEN-1168 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1168 |
| C66 | 66 | `api.utils.task_log_stream` | 362 | 2 | 42 | 中 | 已建卡 | card AGEN-1093 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1093 |
| C67 | 67 | `video_learning.invidious_account` | 360 | 2 | 42 | 中 | 已建卡 | card AGEN-806 |  |
| C68 | 68 | `api.routers.imports` | 146 | 1 | 42 | 高 | 已建卡 | card AGEN-1301 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1301 |
| C69 | 69 | `api.routers.visualizers` | 144 | 1 | 42 | 高 | 已建卡 | card AGEN-959、card AGEN-1226、card AGEN-1323 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-959,AGEN-1226,AGEN-1323 |
| C70 | 70 | `api.routers.mcp_settings` | 133 | 1 | 42 | 高 | 已建卡 | card AGEN-832 |  |
| C71 | 71 | `reading._grounding` | 115 | 4 | 42 | 中 | 已建卡 | card AGEN-1297 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1297 |
| C72 | 72 | `services.config.lightrag_roles` | 111 | 4 | 42 | 中 | 已建卡 | card AGEN-1298 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1298 |
| C73 | 73 | `services.subagent.deepseek_harness` | 347 | 2 | 41 | 中 | 已建卡 | card AGEN-1143 |  |
| C74 | 74 | `services.subagent.antigravity` | 313 | 2 | 41 | 中 | 已建卡 | card AGEN-1180、card AGEN-1324 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1180,AGEN-1324 |
| C75 | 75 | `runtime.coordination.journal` | 97 | 1 | 41 | 高 | 已被main测试覆盖 | tests/agents/chat/test_learning_journal_injection.py, tests/api/test_learning_journal.py, tests/runtime/coordination/test_journal_recovery.py（共 4 个） |  |
| C76 | 76 | `runtime.capability_routing` | 88 | 1 | 41 | 高 | 已建卡 | card AGEN-1299 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1299 |
| C77 | 77 | `api.routers.attachments` | 79 | 1 | 41 | 高 | 已建卡 | card AGEN-1264、card AGEN-1325 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1264,AGEN-1325 |
| C78 | 78 | `services.rag.pipelines.llamaindex.vector_store` | 288 | 2 | 40 | 中 | 仍可建卡 | 报告种子（deeptutor/services/rag/pipelines/llamaindex/vector_store.py） |  |
| C79 | 79 | `services.rag.pipelines.lightrag.block_policy` | 266 | 2 | 40 | 中 | 已建卡 | card AGEN-1307 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1307 |
| C80 | 80 | `api.routers.task_board` | 28 | 1 | 40 | 高 | 仍可建卡 | 报告种子（deeptutor/api/routers/task_board.py） | 仅相关卡（guide/docs/scan/review，不构成领取去重）：AGEN-859 |
| C81 | 81 | `services.rag.eval.dataset` | 244 | 2 | 39 | 中 | 已建卡 | card AGEN-912 |  |
| C82 | 82 | `services.rag.linked_kb` | 237 | 2 | 39 | 中 | 仍可建卡 | 报告种子（deeptutor/services/rag/linked_kb.py） | 仅相关卡（guide/docs/scan/review，不构成领取去重）：AGEN-941 |
| C83 | 83 | `services.memory.consolidator.modes.dedup` | 228 | 2 | 39 | 中 | 已建卡 | card AGEN-1327 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1327 |
| C84 | 84 | `partners.channels.weixin_qr` | 202 | 2 | 39 | 中 | 已建卡 | card AGEN-1313 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1313 |
| C85 | 85 | `multi_user.book_access` | 200 | 2 | 39 | 中 | 已建卡 | card AGEN-828 |  |
| C86 | 86 | `services.memory.consolidator.meta` | 194 | 2 | 38 | 中 | 已被main测试覆盖 | tests/services/memory/test_meta_settings.py, tests/services/rag/test_lightrag_workspace_meta.py |  |
| C87 | 87 | `services.subagent.hermes_remote_client` | 180 | 2 | 38 | 中 | 已建卡 | card AGEN-1329 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1329 |
| C88 | 88 | `learning.topic_naming` | 166 | 2 | 38 | 中 | 已建卡 | card AGEN-1135 |  |
| C89 | 89 | `services.workspace.session_move` | 138 | 2 | 37 | 中 | 仍可建卡 | 报告种子（deeptutor/services/workspace/session_move.py） |  |
| C90 | 90 | `services.parsing.engines.docling.formats` | 137 | 2 | 37 | 中 | 已建卡 | card AGEN-1330 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1330 |
| C91 | 91 | `book.blocks.figure` | 135 | 2 | 37 | 中 | 已建卡 | card AGEN-1331 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1331 |
| C92 | 92 | `book.blocks.concept_graph` | 132 | 2 | 37 | 中 | 已建卡 | card AGEN-1309 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1309 |
| C93 | 93 | `services.memory.consolidator.chunker` | 131 | 2 | 37 | 中 | 已建卡 | card AGEN-1332 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1332 |
| C94 | 94 | `api.utils.tool_options` | 122 | 2 | 37 | 中 | 已建卡 | card AGEN-274、card AGEN-405 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-274,AGEN-405 |
| C95 | 95 | `api.utils.task_id_manager` | 120 | 2 | 37 | 中 | 已被main测试覆盖 | tests/api/test_knowledge_upload_guards.py, tests/api/test_task_id_manager.py |  |
| C96 | 96 | `tools.reason` | 119 | 2 | 37 | 中 | 已建卡 | card AGEN-849 |  |
| C97 | 97 | `book.agents.ideation_agent` | 111 | 2 | 37 | 中 | 已被main测试覆盖 | tests/book/test_engine_stage_transitions.py, tests/book/test_reasoning_output_cap.py |  |
| C98 | 98 | `capabilities.reading.media_notes` | 92 | 2 | 36 | 中 | 已建卡 | card AGEN-1310 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1310 |
| C99 | 99 | `learning.grading` | 64 | 2 | 36 | 中 | 已建卡 | card AGEN-1035 |  |
| C100 | 100 | `services.parsing.engines.pymupdf4llm.formats` | 60 | 2 | 36 | 中 | 已建卡 | card AGEN-1333 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1333 |

## 轴 D：channel-contracts-20261005 修复卡种子 A–M（13 种子）

| ID | 卡 | 优先 | 内容 | 三态 | 依据/卡 | 备注 |
|---|---|---|---|---|---|---|
| D1 | A | P0 | feishu send 抛错语义：feishu.py:2322-2323 send 吞一切，manager 重试失效 | 仍可建卡 | 报告种子（报告锚点即依据） | AGEN-262 为卡片正文/视频域，非 send 契约 |
| D2 | B | P0 | mochat send 抛错语义：mochat.py:409-410 吞一切；需同步改 test_send_failure_does_not_raise | 仍可建卡 | 报告种子（报告锚点即依据） | AGEN-690/694 为解析/生命周期测试卡，不含 send 契约修复 |
| D3 | C | P0+P1 | dingtalk 投递与资源：send 失败 raise + client 超时 + stop 关闭 SDK StreamClient | 仍可建卡 | 报告种子（报告锚点即依据） | AGEN-735 为解析/签名测试卡，不含本修复 |
| D4 | D | P0 | zulip send API 错误抛出：zulip.py:749-750/783-785 改 raise，修正注释矛盾 | 已建卡 | card AGEN-821 |  |
| D5 | E | P1 | BaseChannel 双重启动防护：base 层收敛 16 通道二次 start 泄漏 | 已建卡 | card AGEN-1131 |  |
| D6 | F | P0 | weixin stop 守卫与死字段：未 start 过不 _save_state；删 _poll_task 死字段 | 已建卡 | card AGEN-820 | 修复未落 main（6cf793bd8 weixin.py stop 仍无条件 _save_state） |
| D7 | G | P1 | stop 清理补全：feishu lark Client/流缓冲、slack web client、telegram/mochat/dingtalk/discord/zulip 取消 await | 仍可建卡 | 报告种子（报告锚点即依据） | AGEN-493 仅吞错收口（且未落 main），本卡范围为其遗留 |
| D8 | H | P0 | discord send_delta _stream_id 键控：discord.py:68/199-222 违反 base.py:178 | 已建卡 | card AGEN-821、card AGEN-954 |  |
| D9 | I | P1 | 事件循环阻塞治理：zulip 鉴权/deregister+join、msteams shutdown/join、weixin 媒体加密移出循环 | 仍可建卡 | 报告种子（报告锚点即依据） | AGEN-998 为全仓 async 阻塞扫描轴、AGEN-861 为 zulip 测试侧，均非本修复 |
| D10 | J | P2 | 入站幂等补齐：msteams/discord/slack/dingtalk 入站去重缺口 | 仍可建卡 | 报告种子（报告锚点即依据） | AGEN-493 是 stop 幂等，非入站幂等 |
| D11 | K | P1 | qq/wecom 易失状态：qq 路由缓存未命中兜底发错 API；wecom frame 缺失静默丢 | 仍可建卡 | 报告种子（报告锚点即依据） | AGEN-736/1051 为解析/收发测试卡，不含本修复 |
| D12 | L | P2 | 发送超时归一：slack/wecom/qq/whatsapp/feishu/dingtalk 发送路径补超时 | 仍可建卡 | 报告种子（报告锚点即依据） | AGEN-578 为 HTTP 客户端超时扫描轴 |
| D13 | M | P2 | not-running 契约文档化：base.py 注明未运行时 send 预期行为并统一 16 通道 | 仍可建卡 | 报告种子（报告锚点即依据） |  |

## 轴 E：error-messages-20261004 Top15（15 种子）

| ID | # | 内容 | 三态 | 依据/卡 | 备注 |
|---|---|---|---|---|---|
| E1 | 1 | knowledge.py:1403 health 响应带 traceback + str(e) | 已建卡 | card AGEN-783 | 修复未落 main（6cf793bd8 knowledge.py:1410 仍含 traceback.format_exc()） |
| E2 | 2 | blanket except→500 detail=str(e) ×62（book/co_writer/knowledge/notebook） | 已建卡 | card AGEN-827、card AGEN-902、card AGEN-903、card AGEN-781 | 四卡合计覆盖报告点名文件；未落 main（同文件 blanket-500 仍 20/18/60/12 处）；模块种子另见 C26 |
| E3 | 3 | web client.ts messageFromBody 原样透出后端 detail（~250 调用点） | 已建卡 | card AGEN-1279 | 另见 AGEN-880（web detail.code 解析层）；未落 main |
| E4 | 4 | session/turns/executor.py:1349 聊天流错误事件 content=str(exc) | 已建卡 | card AGEN-785 | 未落 main（executor.py:1368 仍 content=str(exc)） |
| E5 | 5 | partners/runtime.py 伙伴回复失败带异常类名 | 已建卡 | card AGEN-784 |  |
| E6 | 6 | 供应商 resp.text[:400] 拼进异常透传（voice/search/embedding 等 10+ 处） | 已建卡 | card AGEN-779、card AGEN-1277 | 部分残留：generation_http.py:80 resp.text 仍在 main 且无修复卡 |
| E7 | 7 | format_exception_message 白名单/脱敏/截断收敛 | 已建卡 | card AGEN-774 | 未落 main（error_utils.py 仍为 pass-through） |
| E8 | 8 | pydantic ValidationError 全文回显（book/mastery_path） | 已建卡 | card AGEN-825 |  |
| E9 | 9 | llm/error_mapping.py:170 供应商 SDK 原文进用户流 | 已建卡 | card AGEN-823 | 未落 main（error_mapping 仍 str(exc) 直传） |
| E10 | 10 | api/routers/notebook.py ×12 blanket-500 | 已建卡 | card AGEN-781 | 未落 main |
| E11 | 11 | reading_extensions PermissionError str → 403 带服务端路径 | 已建卡 | card AGEN-907 |  |
| E12 | 12 | practice/question 路径/key 泄漏与供应商原文下发 | 已建卡 | card AGEN-786 |  |
| E13 | 13 | LANG-MIX：后端 routers 不走 t()、web 硬编码文案绕过 locale | 仍可建卡 | 报告种子（报告锚点即依据） | 残留主项：后端 routers t() 收敛无卡；已建卡子项 AGEN-905（web 9 文件）/AGEN-904（fr/pl/uk 键）/AGEN-1366（co_writer 中文 detail） |
| E14 | 14 | NO-CODE：~597 处纯文本 detail 无机器可读 code | 仍可建卡 | 报告种子（报告锚点即依据） | 残留主项：系统性 code 信封无卡；子集 AGEN-1364（sessions.py 27 处）、web 侧 AGEN-880 |
| E15 | 15 | INCONSISTENT：not_found 15+ 种写法、网络失败/限流话术分裂 | 仍可建卡 | 报告种子（报告锚点即依据） | 残留主项：后端 not_found 模板统一无卡；web 侧 AGEN-910、跨文件话术 AGEN-1361 |

## 轴 F：coverage-gaps zero/weak 清单

### FZ zero96（基线 zero_top200 全量 96）

| ID | 模块 | path | LOC | fanin | 三态 | 依据/卡 | 备注 |
|---|---|---|---:|---:|---|---|---|
| FZ1 | `services.session.turns.executor` | `deeptutor/services/session/turns/executor.py` | 1422 | 1 | 已建卡 | card AGEN-686 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-686 |
| FZ2 | `partners.channels.mochat` | `deeptutor/partners/channels/mochat.py` | 1075 | 0 | 已建卡 | card AGEN-690、card AGEN-792 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-690,AGEN-792 |
| FZ3 | `services.session.turns.request_preparer` | `deeptutor/services/session/turns/request_preparer.py` | 1067 | 1 | 已建卡 | card AGEN-687 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-687 |
| FZ4 | `services.voice.speech_text` | `deeptutor/services/voice/speech_text.py` | 825 | 1 | 已建卡 | card AGEN-691 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-691 |
| FZ5 | `partners.channels.dingtalk` | `deeptutor/partners/channels/dingtalk.py` | 548 | 0 | 已建卡 | card AGEN-735 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-735 |
| FZ6 | `tools.vision.coord_transform` | `deeptutor/tools/vision/coord_transform.py` | 436 | 1 | 已建卡 | card AGEN-746 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-746 |
| FZ7 | `tools.question.question_extractor` | `deeptutor/tools/question/question_extractor.py` | 413 | 2 | 已建卡 | card AGEN-757 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-757 |
| FZ8 | `agents.notebook.analysis_agent` | `deeptutor/agents/notebook/analysis_agent.py` | 380 | 1 | 已建卡 | card AGEN-927 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-927 |
| FZ9 | `services.mastery_hints` | `deeptutor/services/mastery_hints.py` | 380 | 1 | 已建卡 | card AGEN-504、card AGEN-523 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-504,AGEN-523 |
| FZ10 | `services.session.turns.learning_adapter` | `deeptutor/services/session/turns/learning_adapter.py` | 371 | 1 | 已建卡 | card AGEN-755 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-755 |
| FZ11 | `book.blocks.section` | `deeptutor/book/blocks/section.py` | 369 | 1 | 已建卡 | card AGEN-756、card AGEN-1188、card AGEN-1248 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-756,AGEN-1188,AGEN-1248 |
| FZ12 | `tools.tex_chunker` | `deeptutor/tools/tex_chunker.py` | 341 | 0 | 已被main测试覆盖 | tests/tools/test_tex_tools.py |  |
| FZ13 | `tools.knowledge_frontier` | `deeptutor/tools/knowledge_frontier.py` | 321 | 1 | 已建卡 | card AGEN-812 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-812 |
| FZ14 | `services.memory.consolidator.modes._runtime` | `deeptutor/services/memory/consolidator/modes/_runtime.py` | 319 | 4 | 仍可建卡 | 报告种子（deeptutor/services/memory/consolidator/modes/_runtime.py） |  |
| FZ15 | `tools.tex_downloader` | `deeptutor/tools/tex_downloader.py` | 256 | 0 | 已被main测试覆盖 | tests/tools/test_tex_tools.py |  |
| FZ16 | `tools.vision.block_parser` | `deeptutor/tools/vision/block_parser.py` | 251 | 1 | 已建卡 | card AGEN-844 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-844 |
| FZ17 | `services.llm.provider_core.github_copilot_provider` | `deeptutor/services/llm/provider_core/github_copilot_provider.py` | 234 | 2 | 已被main测试覆盖 | tests/cli/test_init_wizard_probe.py, tests/cli/test_provider_cli.py, tests/services/llm/test_github_copilot_provider.py |  |
| FZ18 | `tools.vision.image_utils` | `deeptutor/tools/vision/image_utils.py` | 210 | 1 | 已建卡 | card AGEN-512 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-512 |
| FZ19 | `tools.paper_search_tool` | `deeptutor/tools/paper_search_tool.py` | 207 | 2 | 已建卡 | card AGEN-511 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-511 |
| FZ20 | `partners.channels.qq` | `deeptutor/partners/channels/qq.py` | 203 | 0 | 仍可建卡 | 报告种子（deeptutor/partners/channels/qq.py） |  |
| FZ21 | `services.pocketbase_client` | `deeptutor/services/pocketbase_client.py` | 196 | 7 | 已建卡 | card AGEN-696 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-696 |
| FZ22 | `book.agents.spine_agent` | `deeptutor/book/agents/spine_agent.py` | 189 | 1 | 已建卡 | card AGEN-966 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-966 |
| FZ23 | `services.session.turns.title_service` | `deeptutor/services/session/turns/title_service.py` | 161 | 1 | 已被main测试覆盖 | tests/app/test_turn_application_service.py |  |
| FZ24 | `agents.math_animator.visual_review` | `deeptutor/agents/math_animator/visual_review.py` | 154 | 1 | 已建卡 | card AGEN-851 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-851 |
| FZ25 | `agents.research.mode_strategy` | `deeptutor/agents/research/mode_strategy.py` | 147 | 1 | 已建卡 | card AGEN-957 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-957 |
| FZ26 | `services.llm.cloud_provider` | `deeptutor/services/llm/cloud_provider.py` | 144 | 2 | 已被main测试覆盖 | tests/api/test_github_copilot_models.py |  |
| FZ27 | `book.blocks._rag_helpers` | `deeptutor/book/blocks/_rag_helpers.py` | 142 | 2 | 仍可建卡 | 报告种子（deeptutor/book/blocks/_rag_helpers.py） |  |
| FZ28 | `services.search.providers.zhipu` | `deeptutor/services/search/providers/zhipu.py` | 142 | 0 | 仍可建卡 | 报告种子（deeptutor/services/search/providers/zhipu.py） |  |
| FZ29 | `logging.process_stream` | `deeptutor/logging/process_stream.py` | 137 | 2 | 已建卡 | card AGEN-938 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-938 |
| FZ30 | `services.search.providers.firecrawl` | `deeptutor/services/search/providers/firecrawl.py` | 136 | 0 | 仍可建卡 | 报告种子（deeptutor/services/search/providers/firecrawl.py） |  |
| FZ31 | `book.learning_overlay` | `deeptutor/book/learning_overlay.py` | 134 | 1 | 已建卡 | card AGEN-853 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-853 |
| FZ32 | `services.session.ask_user_trace` | `deeptutor/services/session/ask_user_trace.py` | 133 | 3 | 已建卡 | card AGEN-936 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-936 |
| FZ33 | `book.blocks.animation` | `deeptutor/book/blocks/animation.py` | 133 | 2 | 仍可建卡 | 报告种子（deeptutor/book/blocks/animation.py） |  |
| FZ34 | `agents._shared.tool_runtime` | `deeptutor/agents/_shared/tool_runtime.py` | 131 | 3 | 已建卡 | card AGEN-846 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-846 |
| FZ35 | `services.memory.consolidator.modes._shims` | `deeptutor/services/memory/consolidator/modes/_shims.py` | 129 | 2 | 已建卡 | card AGEN-1073 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1073 |
| FZ36 | `services.subagent.hermes_remote_events` | `deeptutor/services/subagent/hermes_remote_events.py` | 125 | 1 | 已建卡 | card AGEN-933 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-933 |
| FZ37 | `visualizers.loop_capability` | `deeptutor/visualizers/loop_capability.py` | 125 | 0 | 已建卡 | card AGEN-959 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-959 |
| FZ38 | `services.rag.pipelines.ima.transport` | `deeptutor/services/rag/pipelines/ima/transport.py` | 122 | 2 | 已建卡 | card AGEN-932 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-932 |
| FZ39 | `learning.question_card` | `deeptutor/learning/question_card.py` | 118 | 1 | 已建卡 | card AGEN-961 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-961 |
| FZ40 | `runtime.coordination.types` | `deeptutor/runtime/coordination/types.py` | 116 | 6 | 已建卡 | card AGEN-969 |  |
| FZ41 | `book.blocks.interactive` | `deeptutor/book/blocks/interactive.py` | 113 | 2 | 仍可建卡 | 报告种子（deeptutor/book/blocks/interactive.py） |  |
| FZ42 | `services.base_sync` | `deeptutor/services/base_sync.py` | 105 | 1 | 已被main测试覆盖 | tests/services/test_github_source_unchanged_sync.py |  |
| FZ43 | `runtime.capability_catalog` | `deeptutor/runtime/capability_catalog.py` | 104 | 4 | 已建卡 | card AGEN-958 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-958 |
| FZ44 | `tools.brainstorm` | `deeptutor/tools/brainstorm.py` | 104 | 1 | 已建卡 | card AGEN-849 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-849 |
| FZ45 | `services.search.providers.searxng` | `deeptutor/services/search/providers/searxng.py` | 104 | 1 | 仍可建卡 | 报告种子（deeptutor/services/search/providers/searxng.py） |  |
| FZ46 | `services.session.usage_recovery` | `deeptutor/services/session/usage_recovery.py` | 104 | 1 | 已建卡 | card AGEN-841 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-841 |
| FZ47 | `i18n.metadata_i18n` | `deeptutor/i18n/metadata_i18n.py` | 103 | 4 | 已建卡 | card AGEN-852 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-852 |
| FZ48 | `partners.network` | `deeptutor/partners/network.py` | 101 | 1 | 已建卡 | card AGEN-855 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-855 |
| FZ49 | `agents.math_animator.agents.visual_review_agent` | `deeptutor/agents/math_animator/agents/visual_review_agent.py` | 100 | 1 | 仍可建卡 | 报告种子（deeptutor/agents/math_animator/agents/visual_review_agent.py） |  |
| FZ50 | `runtime.agentic.think_stream` | `deeptutor/runtime/agentic/think_stream.py` | 93 | 2 | 已建卡 | card AGEN-935 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-935 |
| FZ51 | `capabilities.reading._tool_base` | `deeptutor/capabilities/reading/_tool_base.py` | 86 | 2 | 仍可建卡 | 报告种子（deeptutor/capabilities/reading/_tool_base.py） |  |
| FZ52 | `utils.error_utils` | `deeptutor/utils/error_utils.py` | 81 | 3 | 已建卡 | card AGEN-774 |  |
| FZ53 | `agents.visualize.agents.review_agent` | `deeptutor/agents/visualize/agents/review_agent.py` | 75 | 1 | 仍可建卡 | 报告种子（deeptutor/agents/visualize/agents/review_agent.py） |  |
| FZ54 | `book.blocks.flash_cards` | `deeptutor/book/blocks/flash_cards.py` | 74 | 2 | 仍可建卡 | 报告种子（deeptutor/book/blocks/flash_cards.py） |  |
| FZ55 | `api.utils.progress_broadcaster` | `deeptutor/api/utils/progress_broadcaster.py` | 73 | 2 | 已被main测试覆盖 | tests/api/test_knowledge_progress_ws.py |  |
| FZ56 | `book.blocks.deep_dive` | `deeptutor/book/blocks/deep_dive.py` | 70 | 2 | 仍可建卡 | 报告种子（deeptutor/book/blocks/deep_dive.py） |  |
| FZ57 | `tools.question.exam_mimic` | `deeptutor/tools/question/exam_mimic.py` | 70 | 1 | 已建卡 | card AGEN-1137 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1137 |
| FZ58 | `services.memory.snapshot.diff` | `deeptutor/services/memory/snapshot/diff.py` | 67 | 1 | 已建卡 | card AGEN-1054 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1054 |
| FZ59 | `services.practice.analytics` | `deeptutor/services/practice/analytics.py` | 67 | 1 | 仍可建卡 | 报告种子（deeptutor/services/practice/analytics.py） |  |
| FZ60 | `book.blocks.timeline` | `deeptutor/book/blocks/timeline.py` | 66 | 2 | 仍可建卡 | 报告种子（deeptutor/book/blocks/timeline.py） |  |
| FZ61 | `tools.web_search` | `deeptutor/tools/web_search.py` | 65 | 2 | 已建卡 | card AGEN-1353 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1353 |
| FZ62 | `runtime.worker_process` | `deeptutor/runtime/worker_process.py` | 65 | 0 | 已建卡 | card AGEN-945 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-945 |
| FZ63 | `services.cli_apps.vendor.build_snapshot` | `deeptutor/services/cli_apps/vendor/build_snapshot.py` | 65 | 0 | 已建卡 | card AGEN-1070 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1070 |
| FZ64 | `services.search.providers.duckduckgo` | `deeptutor/services/search/providers/duckduckgo.py` | 65 | 0 | 仍可建卡 | 报告种子（deeptutor/services/search/providers/duckduckgo.py） |  |
| FZ65 | `book.blocks.callout` | `deeptutor/book/blocks/callout.py` | 64 | 2 | 仍可建卡 | 报告种子（deeptutor/book/blocks/callout.py） |  |
| FZ66 | `book.estimate` | `deeptutor/book/estimate.py` | 62 | 1 | 已建卡 | card AGEN-1059 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1059 |
| FZ67 | `partners.transcription` | `deeptutor/partners/transcription.py` | 61 | 1 | 已建卡 | card AGEN-1057 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1057 |
| FZ68 | `i18n.status_i18n` | `deeptutor/i18n/status_i18n.py` | 60 | 1 | 已建卡 | card AGEN-852 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-852 |
| FZ69 | `agents._shared.workspace_prompt` | `deeptutor/agents/_shared/workspace_prompt.py` | 59 | 3 | 已建卡 | card AGEN-1075 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1075 |
| FZ70 | `services.mcp.session_state` | `deeptutor/services/mcp/session_state.py` | 59 | 2 | 仍可建卡 | 报告种子（deeptutor/services/mcp/session_state.py） |  |
| FZ71 | `api.routers.agent_config` | `deeptutor/api/routers/agent_config.py` | 59 | 1 | 已建卡 | card AGEN-908 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-908 |
| FZ72 | `services.rag.pipelines.llamaindex.errors` | `deeptutor/services/rag/pipelines/llamaindex/errors.py` | 59 | 1 | 仍可建卡 | 报告种子（deeptutor/services/rag/pipelines/llamaindex/errors.py） |  |
| FZ73 | `runtime.worker_tasks` | `deeptutor/runtime/worker_tasks.py` | 56 | 0 | 仍可建卡 | 报告种子（deeptutor/runtime/worker_tasks.py） |  |
| FZ74 | `services.config.origins` | `deeptutor/services/config/origins.py` | 55 | 3 | 已建卡 | card AGEN-970 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-970 |
| FZ75 | `agents._shared.capability_result` | `deeptutor/agents/_shared/capability_result.py` | 51 | 7 | 已建卡 | card AGEN-846 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-846 |
| FZ76 | `services.embedding.request_options` | `deeptutor/services/embedding/request_options.py` | 46 | 4 | 已建卡 | card AGEN-971 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-971 |
| FZ77 | `knowledge.progress_events` | `deeptutor/knowledge/progress_events.py` | 45 | 2 | 仍可建卡 | 报告种子（deeptutor/knowledge/progress_events.py） |  |
| FZ78 | `runtime.turn_engine` | `deeptutor/runtime/turn_engine.py` | 41 | 5 | 已建卡 | card AGEN-969 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-969 |
| FZ79 | `textbook_struct.column_blacklist` | `deeptutor/textbook_struct/column_blacklist.py` | 41 | 2 | 已建卡 | card AGEN-906 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-906 |
| FZ80 | `services.parsing.engines._versions` | `deeptutor/services/parsing/engines/_versions.py` | 38 | 12 | 已建卡 | card AGEN-906 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-906 |
| FZ81 | `api.routers.capabilities_settings` | `deeptutor/api/routers/capabilities_settings.py` | 38 | 1 | 已建卡 | card AGEN-1353 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1353 |
| FZ82 | `services.llm.provider_core.codebuddy_models` | `deeptutor/services/llm/provider_core/codebuddy_models.py` | 36 | 1 | 已建卡 | card AGEN-1077 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1077 |
| FZ83 | `services.partners.model_runtime` | `deeptutor/services/partners/model_runtime.py` | 36 | 1 | 已建卡 | card AGEN-1069 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1069 |
| FZ84 | `services.parsing.engines.formats` | `deeptutor/services/parsing/engines/formats.py` | 29 | 1 | 仍可建卡 | 报告种子（deeptutor/services/parsing/engines/formats.py） |  |
| FZ85 | `core.response_languages` | `deeptutor/core/response_languages.py` | 28 | 2 | 仍可建卡 | 报告种子（deeptutor/core/response_languages.py） |  |
| FZ86 | `book.blocks.user_note` | `deeptutor/book/blocks/user_note.py` | 26 | 2 | 仍可建卡 | 报告种子（deeptutor/book/blocks/user_note.py） |  |
| FZ87 | `tools.solve_tool` | `deeptutor/tools/solve_tool.py` | 22 | 0 | 已建卡 | card AGEN-849 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-849 |
| FZ88 | `services.session.turns.context_assembler` | `deeptutor/services/session/turns/context_assembler.py` | 20 | 1 | 仍可建卡 | 报告种子（deeptutor/services/session/turns/context_assembler.py） |  |
| FZ89 | `services.config.image_description` | `deeptutor/services/config/image_description.py` | 18 | 2 | 已建卡 | card AGEN-970、card AGEN-1063 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-970,AGEN-1063 |
| FZ90 | `book.blocks._language` | `deeptutor/book/blocks/_language.py` | 15 | 3 | 已建卡 | card AGEN-1083 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1083 |
| FZ91 | `agents.notebook._text` | `deeptutor/agents/notebook/_text.py` | 14 | 2 | 仍可建卡 | 报告种子（deeptutor/agents/notebook/_text.py） |  |
| FZ92 | `__version__` | `deeptutor/__version__.py` | 11 | 2 | 仍可建卡 | 报告种子（deeptutor/__version__.py） |  |
| FZ93 | `response_languages` | `deeptutor/response_languages.py` | 8 | 2 | 仍可建卡 | 报告种子（deeptutor/response_languages.py） |  |
| FZ94 | `book.errors` | `deeptutor/book/errors.py` | 8 | 2 | 仍可建卡 | 报告种子（deeptutor/book/errors.py） |  |
| FZ95 | `__main__` | `deeptutor/__main__.py` | 6 | 0 | 仍可建卡 | 报告种子（deeptutor/__main__.py） |  |
| FZ96 | `services.llm.provider_registry` | `deeptutor/services/llm/provider_registry.py` | 3 | 0 | 仍可建卡 | 报告种子（deeptutor/services/llm/provider_registry.py） | 仅相关卡（guide/docs/scan/review，不构成领取去重）：AGEN-1265 |

### FT weak242 tail（top100 之外 142）

AGEN-1315 已为 tail 中 fanin≥2 的 23 个种子给出测试焦点（下表 ★）；其余 119 个（fanin≤1 为主）任何报告未给焦点，拆卡前需自审职责。

| ID | rank | 模块 | path | LOC | fanin | ★ | 三态 | 依据/卡 | 备注 |
|---|---|---|---|---:|---:|---|---|---|---|
| FT1 | 101 | `services.parsing.engines.liteparse.formats` | `deeptutor/services/parsing/engines/liteparse/formats.py` | 58 | 2 | ★ | 仍可建卡 | 报告种子（deeptutor/services/parsing/engines/liteparse/formats.py） |  |
| FT2 | 102 | `co_writer.docx_converter` | `deeptutor/co_writer/docx_converter.py` | 667 | 1 |  | 已被main测试覆盖 | tests/api/routers/test_co_writer_contract.py, tests/api/test_co_writer.py |  |
| FT3 | 103 | `services.search.source_filter` | `deeptutor/services/search/source_filter.py` | 582 | 1 |  | 已建卡 | card AGEN-974 |  |
| FT4 | 104 | `tools.question_bank` | `deeptutor/tools/question_bank.py` | 536 | 1 |  | 已建卡 | card AGEN-972 |  |
| FT5 | 105 | `services.subagent.opencode_family` | `deeptutor/services/subagent/opencode_family.py` | 508 | 1 |  | 已建卡 | card AGEN-1339 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1339 |
| FT6 | 106 | `tools.write_note` | `deeptutor/tools/write_note.py` | 492 | 1 |  | 已建卡 | card AGEN-1094 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1094 |
| FT7 | 107 | `services.memory.consolidator.modes.audit` | `deeptutor/services/memory/consolidator/modes/audit.py` | 484 | 1 |  | 已建卡 | card AGEN-782 |  |
| FT8 | 108 | `services.embedding.adapters.gemini` | `deeptutor/services/embedding/adapters/gemini.py` | 462 | 1 |  | 已建卡 | card AGEN-913 |  |
| FT9 | 109 | `reading.epub_bilingual` | `deeptutor/reading/epub_bilingual.py` | 248 | 3 | ★ | 已被main测试覆盖 | tests/reading/test_epub_bilingual.py, tests/reading/test_epub_bilingual_units.py |  |
| FT10 | 110 | `services.workspace.kb_move` | `deeptutor/services/workspace/kb_move.py` | 446 | 1 |  | 已建卡 | card AGEN-976 |  |
| FT11 | 111 | `co_writer.edit_agent` | `deeptutor/co_writer/edit_agent.py` | 409 | 1 |  | 已被main测试覆盖 | tests/api/routers/test_co_writer_contract.py, tests/api/test_co_writer.py |  |
| FT12 | 112 | `runtime.update_worker` | `deeptutor/runtime/update_worker.py` | 158 | 0 |  | 已建卡 | card AGEN-139、card AGEN-215 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-139,AGEN-215 |
| FT13 | 113 | `services.rag.pipelines.llamaindex.exercise_lookup` | `deeptutor/services/rag/pipelines/llamaindex/exercise_lookup.py` | 373 | 1 |  | 仍可建卡 | 报告种子（deeptutor/services/rag/pipelines/llamaindex/exercise_lookup.py） |  |
| FT14 | 114 | `services.search.consolidation` | `deeptutor/services/search/consolidation.py` | 372 | 1 |  | 已建卡 | card AGEN-1052 |  |
| FT15 | 115 | `services.subagent.claude_code` | `deeptutor/services/subagent/claude_code.py` | 364 | 1 |  | 已建卡 | card AGEN-1142 |  |
| FT16 | 116 | `services.workspace.dependencies` | `deeptutor/services/workspace/dependencies.py` | 349 | 1 |  | 已建卡 | card AGEN-1144、card AGEN-158、card AGEN-256 |  |
| FT17 | 117 | `capabilities.obsidian.vault` | `deeptutor/capabilities/obsidian/vault.py` | 324 | 1 |  | 已建卡 | card AGEN-807 |  |
| FT18 | 118 | `services.rag.pipelines.lightrag.sidecar` | `deeptutor/services/rag/pipelines/lightrag/sidecar.py` | 320 | 1 |  | 已建卡 | card AGEN-811 |  |
| FT19 | 119 | `services.singleflight_cache` | `deeptutor/services/singleflight_cache.py` | 78 | 3 | ★ | 已建卡 | card AGEN-671 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-671 |
| FT20 | 120 | `capabilities.setup.jobs` | `deeptutor/capabilities/setup/jobs.py` | 280 | 1 |  | 仍可建卡 | 报告种子（deeptutor/capabilities/setup/jobs.py） |  |
| FT21 | 121 | `services.subagent.kimi` | `deeptutor/services/subagent/kimi.py` | 268 | 1 |  | 已建卡 | card AGEN-1180 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1180 |
| FT22 | 122 | `services.subagent.grok` | `deeptutor/services/subagent/grok.py` | 252 | 1 |  | 已建卡 | card AGEN-1180 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1180 |
| FT23 | 123 | `services.rag.pipelines.graphrag.completion_adapter` | `deeptutor/services/rag/pipelines/graphrag/completion_adapter.py` | 251 | 1 |  | 已建卡 | card AGEN-1345 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1345 |
| FT24 | 124 | `knowledge.naming` | `deeptutor/knowledge/naming.py` | 40 | 3 | ★ | 仍可建卡 | 报告种子（deeptutor/knowledge/naming.py） |  |
| FT25 | 125 | `core.assessment` | `deeptutor/core/assessment.py` | 15 | 3 | ★ | 已被main测试覆盖 | tests/api/test_notebook_api_contract.py, tests/api/test_practice.py |  |
| FT26 | 126 | `capabilities.setup.apply` | `deeptutor/capabilities/setup/apply.py` | 249 | 1 |  | 已建卡 | card AGEN-1346 |  |
| FT27 | 127 | `services.embedding.adapters.dashscope_native` | `deeptutor/services/embedding/adapters/dashscope_native.py` | 242 | 1 |  | 已建卡 | card AGEN-913 |  |
| FT28 | 128 | `services.subagent.claude_models` | `deeptutor/services/subagent/claude_models.py` | 238 | 1 |  | 已建卡 | card AGEN-1180 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1180 |
| FT29 | 129 | `tools.github_query` | `deeptutor/tools/github_query.py` | 229 | 1 |  | 已建卡 | card AGEN-1348 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1348 |
| FT30 | 130 | `tools.list_notebook` | `deeptutor/tools/list_notebook.py` | 211 | 1 |  | 已建卡 | card AGEN-1349 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1349 |
| FT31 | 131 | `services.voice.adapters.volcengine` | `deeptutor/services/voice/adapters/volcengine.py` | 207 | 1 |  | 已建卡 | card AGEN-916 |  |
| FT32 | 132 | `services.subagent.opencode_server` | `deeptutor/services/subagent/opencode_server.py` | 204 | 1 |  | 已建卡 | card AGEN-845 |  |
| FT33 | 133 | `services.subagent.openclaw` | `deeptutor/services/subagent/openclaw.py` | 197 | 1 |  | 仍可建卡 | 报告种子（deeptutor/services/subagent/openclaw.py） |  |
| FT34 | 134 | `capabilities.reading.figure_view` | `deeptutor/capabilities/reading/figure_view.py` | 180 | 1 |  | 仍可建卡 | 报告种子（deeptutor/capabilities/reading/figure_view.py） |  |
| FT35 | 135 | `video_learning.invidious_account_storage` | `deeptutor/video_learning/invidious_account_storage.py` | 177 | 1 |  | 仍可建卡 | 报告种子（deeptutor/video_learning/invidious_account_storage.py） |  |
| FT36 | 136 | `services.parsing.engines.docling.local_worker` | `deeptutor/services/parsing/engines/docling/local_worker.py` | 163 | 1 |  | 已建卡 | card AGEN-848 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-848 |
| FT37 | 137 | `tools.cron_tool` | `deeptutor/tools/cron_tool.py` | 142 | 1 |  | 仍可建卡 | 报告种子（deeptutor/tools/cron_tool.py） |  |
| FT38 | 138 | `services.workspace.session_transfer` | `deeptutor/services/workspace/session_transfer.py` | 140 | 1 |  | 已建卡 | card AGEN-831 |  |
| FT39 | 139 | `services.rag.pipelines.lightrag.cache_reuse` | `deeptutor/services/rag/pipelines/lightrag/cache_reuse.py` | 137 | 1 |  | 仍可建卡 | 报告种子（deeptutor/services/rag/pipelines/lightrag/cache_reuse.py） |  |
| FT40 | 140 | `tools.zotero_search` | `deeptutor/tools/zotero_search.py` | 136 | 1 |  | 仍可建卡 | 报告种子（deeptutor/tools/zotero_search.py） |  |
| FT41 | 141 | `services.llm.image_caption_batch` | `deeptutor/services/llm/image_caption_batch.py` | 135 | 1 |  | 仍可建卡 | 报告种子（deeptutor/services/llm/image_caption_batch.py） |  |
| FT42 | 142 | `services.rag.pipelines.llamaindex.rerank` | `deeptutor/services/rag/pipelines/llamaindex/rerank.py` | 130 | 1 |  | 仍可建卡 | 报告种子（deeptutor/services/rag/pipelines/llamaindex/rerank.py） |  |
| FT43 | 143 | `services.llm.traffic_control` | `deeptutor/services/llm/traffic_control.py` | 125 | 1 |  | 已建卡 | card AGEN-1115 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1115 |
| FT44 | 144 | `services.subagent.partner_group` | `deeptutor/services/subagent/partner_group.py` | 118 | 1 |  | 仍可建卡 | 报告种子（deeptutor/services/subagent/partner_group.py） |  |
| FT45 | 145 | `services.llm.local_provider` | `deeptutor/services/llm/local_provider.py` | 117 | 1 |  | 已被main测试覆盖 | tests/api/test_github_copilot_models.py, tests/services/llm/test_local_provider.py |  |
| FT46 | 146 | `book.overview_copy` | `deeptutor/book/overview_copy.py` | 104 | 1 |  | 仍可建卡 | 报告种子（deeptutor/book/overview_copy.py） |  |
| FT47 | 147 | `services.memory.consolidator.guards` | `deeptutor/services/memory/consolidator/guards.py` | 104 | 1 |  | 已被main测试覆盖 | tests/api/test_knowledge_upload_guards.py, tests/test_release_workflow_guards.py |  |
| FT48 | 148 | `agents.loop.context_budget` | `deeptutor/agents/loop/context_budget.py` | 346 | 2 |  | 已建卡 | card AGEN-1053 |  |
| FT49 | 149 | `api.run_server` | `deeptutor/api/run_server.py` | 98 | 1 |  | 已建卡 | card AGEN-1060 |  |
| FT50 | 150 | `services.imagegen.adapters.openai_compat` | `deeptutor/services/imagegen/adapters/openai_compat.py` | 98 | 1 |  | 仍可建卡 | 报告种子（deeptutor/services/imagegen/adapters/openai_compat.py） |  |
| FT51 | 151 | `services.parsing.engines.mineru.checkpoints` | `deeptutor/services/parsing/engines/mineru/checkpoints.py` | 98 | 1 |  | 仍可建卡 | 报告种子（deeptutor/services/parsing/engines/mineru/checkpoints.py） |  |
| FT52 | 152 | `services.voice.adapters.minimax` | `deeptutor/services/voice/adapters/minimax.py` | 91 | 1 |  | 仍可建卡 | 报告种子（deeptutor/services/voice/adapters/minimax.py） |  |
| FT53 | 153 | `video_learning.invidious_account_client` | `deeptutor/video_learning/invidious_account_client.py` | 85 | 1 |  | 仍可建卡 | 报告种子（deeptutor/video_learning/invidious_account_client.py） |  |
| FT54 | 154 | `services.rag.smart_retriever` | `deeptutor/services/rag/smart_retriever.py` | 81 | 1 |  | 仍可建卡 | 报告种子（deeptutor/services/rag/smart_retriever.py） |  |
| FT55 | 155 | `partners.channels.lark_http` | `deeptutor/partners/channels/lark_http.py` | 79 | 1 |  | 已建卡 | card AGEN-736 |  |
| FT56 | 156 | `services.llm.request_cache` | `deeptutor/services/llm/request_cache.py` | 73 | 1 |  | 仍可建卡 | 报告种子（deeptutor/services/llm/request_cache.py） |  |
| FT57 | 157 | `services.rag.pipelines.graphrag.pandas_compat` | `deeptutor/services/rag/pipelines/graphrag/pandas_compat.py` | 68 | 1 |  | 仍可建卡 | 报告种子（deeptutor/services/rag/pipelines/graphrag/pandas_compat.py） |  |
| FT58 | 158 | `services.voice.adapters.mimo` | `deeptutor/services/voice/adapters/mimo.py` | 67 | 1 |  | 已建卡 | card AGEN-816 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-816 |
| FT59 | 159 | `partners.channels.msteams` | `deeptutor/partners/channels/msteams.py` | 847 | 0 |  | 已建卡 | card AGEN-741、card AGEN-947、card AGEN-767 |  |
| FT60 | 160 | `partners.channels.matrix` | `deeptutor/partners/channels/matrix.py` | 842 | 0 |  | 已建卡 | card AGEN-743、card AGEN-821 |  |
| FT61 | 161 | `partners.channels.napcat` | `deeptutor/partners/channels/napcat.py` | 594 | 0 |  | 已建卡 | card AGEN-742、card AGEN-947、card AGEN-592、card AGEN-602 |  |
| FT62 | 162 | `services.session.legacy_migration` | `deeptutor/services/session/legacy_migration.py` | 291 | 2 | ★ | 已建卡 | card AGEN-1341 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1341 |
| FT63 | 163 | `utils.bibtex_converter` | `deeptutor/utils/bibtex_converter.py` | 287 | 2 | ★ | 已建卡 | card AGEN-1178 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1178 |
| FT64 | 164 | `textbook_struct.chapter_rebuild` | `deeptutor/textbook_struct/chapter_rebuild.py` | 273 | 2 | ★ | 仍可建卡 | 报告种子（deeptutor/textbook_struct/chapter_rebuild.py） |  |
| FT65 | 165 | `services.llm.usage_estimation` | `deeptutor/services/llm/usage_estimation.py` | 45 | 1 |  | 仍可建卡 | 报告种子（deeptutor/services/llm/usage_estimation.py） |  |
| FT66 | 166 | `partners.channels.email` | `deeptutor/partners/channels/email.py` | 470 | 0 |  | 已建卡 | card AGEN-645 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-645 |
| FT67 | 167 | `agents.vision_solver.vision_solver_agent` | `deeptutor/agents/vision_solver/vision_solver_agent.py` | 205 | 2 | ★ | 仍可建卡 | 报告种子（deeptutor/agents/vision_solver/vision_solver_agent.py） |  |
| FT68 | 168 | `logging.stats.llm_stats` | `deeptutor/logging/stats/llm_stats.py` | 200 | 2 | ★ | 已建卡 | card AGEN-1352 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1352 |
| FT69 | 169 | `services.setup.data_volume` | `deeptutor/services/setup/data_volume.py` | 197 | 2 | ★ | 仍可建卡 | 报告种子（deeptutor/services/setup/data_volume.py） |  |
| FT70 | 170 | `reading.knowledge_capture` | `deeptutor/reading/knowledge_capture.py` | 177 | 2 | ★ | 仍可建卡 | 报告种子（deeptutor/reading/knowledge_capture.py） |  |
| FT71 | 171 | `services.session.event_preview` | `deeptutor/services/session/event_preview.py` | 154 | 2 | ★ | 仍可建卡 | 报告种子（deeptutor/services/session/event_preview.py） |  |
| FT72 | 172 | `partners.channels.wecom` | `deeptutor/partners/channels/wecom.py` | 398 | 0 |  | 已建卡 | card AGEN-1051 |  |
| FT73 | 173 | `services.partners.runtime_status` | `deeptutor/services/partners/runtime_status.py` | 132 | 2 | ★ | 仍可建卡 | 报告种子（deeptutor/services/partners/runtime_status.py） |  |
| FT74 | 174 | `utils.config_manager` | `deeptutor/utils/config_manager.py` | 129 | 2 | ★ | 已建卡 | card AGEN-639 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-639 |
| FT75 | 175 | `textbook_struct.page_headers` | `deeptutor/textbook_struct/page_headers.py` | 100 | 2 | ★ | 仍可建卡 | 报告种子（deeptutor/textbook_struct/page_headers.py） |  |
| FT76 | 176 | `tools.partner_memory` | `deeptutor/tools/partner_memory.py` | 315 | 0 |  | 已建卡 | card AGEN-1145 |  |
| FT77 | 177 | `tools.media_gen_tool` | `deeptutor/tools/media_gen_tool.py` | 308 | 0 |  | 已建卡 | card AGEN-1086 |  |
| FT78 | 178 | `services.settings.starter_settings` | `deeptutor/services/settings/starter_settings.py` | 82 | 2 | ★ | 仍可建卡 | 报告种子（deeptutor/services/settings/starter_settings.py） |  |
| FT79 | 179 | `agents._shared.json_output` | `deeptutor/agents/_shared/json_output.py` | 76 | 2 | ★ | 仍可建卡 | 报告种子（deeptutor/agents/_shared/json_output.py） |  |
| FT80 | 180 | `services.github_source.sync_service` | `deeptutor/services/github_source/sync_service.py` | 72 | 2 |  | 已建卡 | card AGEN-1011 |  |
| FT81 | 181 | `services.web_source.navigation` | `deeptutor/services/web_source/navigation.py` | 72 | 2 | ★ | 仍可建卡 | 报告种子（deeptutor/services/web_source/navigation.py） |  |
| FT82 | 182 | `logging.formatters` | `deeptutor/logging/formatters.py` | 54 | 2 | ★ | 仍可建卡 | 报告种子（deeptutor/logging/formatters.py） |  |
| FT83 | 183 | `services.config.readiness` | `deeptutor/services/config/readiness.py` | 1038 | 1 |  | 已建卡 | card AGEN-787 |  |
| FT84 | 184 | `services.reading_hints` | `deeptutor/services/reading_hints.py` | 503 | 1 |  | 已建卡 | card AGEN-745 |  |
| FT85 | 185 | `tools.file_tools` | `deeptutor/tools/file_tools.py` | 291 | 0 |  | 已建卡 | card AGEN-1340 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1340 |
| FT86 | 186 | `services.partners.workspace_binding` | `deeptutor/services/partners/workspace_binding.py` | 48 | 2 | ★ | 仍可建卡 | 报告种子（deeptutor/services/partners/workspace_binding.py） |  |
| FT87 | 187 | `services.practice.answers` | `deeptutor/services/practice/answers.py` | 44 | 2 | ★ | 仍可建卡 | 报告种子（deeptutor/services/practice/answers.py） |  |
| FT88 | 188 | `utils.text_display` | `deeptutor/utils/text_display.py` | 31 | 2 | ★ | 仍可建卡 | 报告种子（deeptutor/utils/text_display.py） |  |
| FT89 | 189 | `services.search.providers.serper` | `deeptutor/services/search/providers/serper.py` | 215 | 0 |  | 已建卡 | card AGEN-1177 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1177 |
| FT90 | 190 | `partners.channels.whatsapp` | `deeptutor/partners/channels/whatsapp.py` | 210 | 0 |  | 已建卡 | card AGEN-1350 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1350 |
| FT91 | 191 | `services.search.providers.serply` | `deeptutor/services/search/providers/serply.py` | 174 | 0 |  | 仍可建卡 | 报告种子（deeptutor/services/search/providers/serply.py） |  |
| FT92 | 192 | `services.search.providers.aliyun_iqs` | `deeptutor/services/search/providers/aliyun_iqs.py` | 163 | 0 |  | 仍可建卡 | 报告种子（deeptutor/services/search/providers/aliyun_iqs.py） |  |
| FT93 | 193 | `services.search.providers.tavily` | `deeptutor/services/search/providers/tavily.py` | 162 | 0 |  | 仍可建卡 | 报告种子（deeptutor/services/search/providers/tavily.py） |  |
| FT94 | 194 | `services.search.providers.perplexity` | `deeptutor/services/search/providers/perplexity.py` | 157 | 0 |  | 仍可建卡 | 报告种子（deeptutor/services/search/providers/perplexity.py） |  |
| FT95 | 195 | `services.search.providers.qianfan` | `deeptutor/services/search/providers/qianfan.py` | 149 | 0 |  | 仍可建卡 | 报告种子（deeptutor/services/search/providers/qianfan.py） |  |
| FT96 | 196 | `services.search.providers.bocha` | `deeptutor/services/search/providers/bocha.py` | 132 | 0 |  | 仍可建卡 | 报告种子（deeptutor/services/search/providers/bocha.py） |  |
| FT97 | 197 | `services.partners.weixin_onboarding` | `deeptutor/services/partners/weixin_onboarding.py` | 324 | 1 |  | 已建卡 | card AGEN-808 |  |
| FT98 | 198 | `services.chat_hints` | `deeptutor/services/chat_hints.py` | 309 | 1 |  | 已建卡 | card AGEN-993 |  |
| FT99 | 199 | `services.rag.pipelines.lightrag.parser` | `deeptutor/services/rag/pipelines/lightrag/parser.py` | 99 | 0 |  | 仍可建卡 | 报告种子（deeptutor/services/rag/pipelines/lightrag/parser.py） |  |
| FT100 | 200 | `services.search.providers.brave` | `deeptutor/services/search/providers/brave.py` | 77 | 0 |  | 仍可建卡 | 报告种子（deeptutor/services/search/providers/brave.py） |  |
| FT101 | 201 | `agents.loop.dsml_tool_calls` | `deeptutor/agents/loop/dsml_tool_calls.py` | 292 | 1 |  | 仍可建卡 | 报告种子（deeptutor/agents/loop/dsml_tool_calls.py） |  |
| FT102 | 202 | `agents.research.utils.token_tracker` | `deeptutor/agents/research/utils/token_tracker.py` | 281 | 1 |  | 已建卡 | card AGEN-1343 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1343 |
| FT103 | 203 | `app.facade` | `deeptutor/app/facade.py` | 281 | 1 |  | 已建卡 | card AGEN-1342 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1342 |
| FT104 | 204 | `agents.math_animator.agents.code_generator_agent` | `deeptutor/agents/math_animator/agents/code_generator_agent.py` | 261 | 1 |  | 仍可建卡 | 报告种子（deeptutor/agents/math_animator/agents/code_generator_agent.py） |  |
| FT105 | 205 | `services.llm.telemetry` | `deeptutor/services/llm/telemetry.py` | 46 | 0 |  | 仍可建卡 | 报告种子（deeptutor/services/llm/telemetry.py） |  |
| FT106 | 206 | `services.codebuddy_auth` | `deeptutor/services/codebuddy_auth.py` | 239 | 1 |  | 已建卡 | card AGEN-931 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-931 |
| FT107 | 207 | `services.settings.registry_edit` | `deeptutor/services/settings/registry_edit.py` | 224 | 1 |  | 仍可建卡 | 报告种子（deeptutor/services/settings/registry_edit.py） |  |
| FT108 | 208 | `services.practice.importing` | `deeptutor/services/practice/importing.py` | 212 | 1 |  | 仍可建卡 | 报告种子（deeptutor/services/practice/importing.py） |  |
| FT109 | 209 | `utils.archive_extractor` | `deeptutor/utils/archive_extractor.py` | 200 | 1 |  | 已建卡 | card AGEN-1351 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1351 |
| FT110 | 210 | `services.cron.executor` | `deeptutor/services/cron/executor.py` | 198 | 1 |  | 仍可建卡 | 报告种子（deeptutor/services/cron/executor.py） |  |
| FT111 | 211 | `services.office_preview` | `deeptutor/services/office_preview.py` | 198 | 1 |  | 已建卡 | card AGEN-790 |  |
| FT112 | 212 | `agents.loop.ask_user_drafts` | `deeptutor/agents/loop/ask_user_drafts.py` | 193 | 1 |  | 仍可建卡 | 报告种子（deeptutor/agents/loop/ask_user_drafts.py） |  |
| FT113 | 213 | `services.videogen.adapters.async_task` | `deeptutor/services/videogen/adapters/async_task.py` | 182 | 1 |  | 仍可建卡 | 报告种子（deeptutor/services/videogen/adapters/async_task.py） |  |
| FT114 | 214 | `agents.math_animator.retry_manager` | `deeptutor/agents/math_animator/retry_manager.py` | 160 | 1 |  | 仍可建卡 | 报告种子（deeptutor/agents/math_animator/retry_manager.py） |  |
| FT115 | 215 | `services.session.attachment_parsing` | `deeptutor/services/session/attachment_parsing.py` | 158 | 1 |  | 仍可建卡 | 报告种子（deeptutor/services/session/attachment_parsing.py） |  |
| FT116 | 216 | `services.config.settings_presets` | `deeptutor/services/config/settings_presets.py` | 135 | 1 |  | 仍可建卡 | 报告种子（deeptutor/services/config/settings_presets.py） |  |
| FT117 | 217 | `services.partners.channel_state_migration` | `deeptutor/services/partners/channel_state_migration.py` | 127 | 1 |  | 仍可建卡 | 报告种子（deeptutor/services/partners/channel_state_migration.py） |  |
| FT118 | 218 | `agents.notebook.summarize_agent` | `deeptutor/agents/notebook/summarize_agent.py` | 120 | 1 |  | 仍可建卡 | 报告种子（deeptutor/agents/notebook/summarize_agent.py） |  |
| FT119 | 219 | `agents.question.agents.followup_agent` | `deeptutor/agents/question/agents/followup_agent.py` | 118 | 1 |  | 仍可建卡 | 报告种子（deeptutor/agents/question/agents/followup_agent.py） |  |
| FT120 | 220 | `agents.visualize.agents.code_generator_agent` | `deeptutor/agents/visualize/agents/code_generator_agent.py` | 117 | 1 |  | 仍可建卡 | 报告种子（deeptutor/agents/visualize/agents/code_generator_agent.py） |  |
| FT121 | 221 | `agents.math_animator.agents.concept_analysis_agent` | `deeptutor/agents/math_animator/agents/concept_analysis_agent.py` | 97 | 1 |  | 仍可建卡 | 报告种子（deeptutor/agents/math_animator/agents/concept_analysis_agent.py） |  |
| FT122 | 222 | `agents.research.utils.json_utils` | `deeptutor/agents/research/utils/json_utils.py` | 94 | 1 |  | 仍可建卡 | 报告种子（deeptutor/agents/research/utils/json_utils.py） |  |
| FT123 | 223 | `logging.configure` | `deeptutor/logging/configure.py` | 81 | 1 |  | 仍可建卡 | 报告种子（deeptutor/logging/configure.py） |  |
| FT124 | 224 | `agents.math_animator.agents.summary_agent` | `deeptutor/agents/math_animator/agents/summary_agent.py` | 78 | 1 |  | 仍可建卡 | 报告种子（deeptutor/agents/math_animator/agents/summary_agent.py） |  |
| FT125 | 225 | `services.sandbox.quota` | `deeptutor/services/sandbox/quota.py` | 78 | 1 |  | 仍可建卡 | 报告种子（deeptutor/services/sandbox/quota.py） |  |
| FT126 | 226 | `agents.question.request_config` | `deeptutor/agents/question/request_config.py` | 77 | 1 |  | 仍可建卡 | 报告种子（deeptutor/agents/question/request_config.py） |  |
| FT127 | 227 | `agents.math_animator.agents.concept_design_agent` | `deeptutor/agents/math_animator/agents/concept_design_agent.py` | 76 | 1 |  | 仍可建卡 | 报告种子（deeptutor/agents/math_animator/agents/concept_design_agent.py） |  |
| FT128 | 228 | `services.settings.provider_edit` | `deeptutor/services/settings/provider_edit.py` | 60 | 1 |  | 仍可建卡 | 报告种子（deeptutor/services/settings/provider_edit.py） |  |
| FT129 | 229 | `services.codex_auth.client_version` | `deeptutor/services/codex_auth/client_version.py` | 55 | 1 |  | 仍可建卡 | 报告种子（deeptutor/services/codex_auth/client_version.py） |  |
| FT130 | 230 | `services.doctor` | `deeptutor/services/doctor.py` | 571 | 0 |  | 已建卡 | card AGEN-914 |  |
| FT131 | 231 | `agents.math_animator.duration_utils` | `deeptutor/agents/math_animator/duration_utils.py` | 36 | 1 |  | 仍可建卡 | 报告种子（deeptutor/agents/math_animator/duration_utils.py） |  |
| FT132 | 232 | `logging.loguru_bridge` | `deeptutor/logging/loguru_bridge.py` | 28 | 1 |  | 仍可建卡 | 报告种子（deeptutor/logging/loguru_bridge.py） |  |
| FT133 | 233 | `services.session.turns.resource_reuse` | `deeptutor/services/session/turns/resource_reuse.py` | 18 | 1 |  | 仍可建卡 | 报告种子（deeptutor/services/session/turns/resource_reuse.py） |  |
| FT134 | 234 | `services.skill.taxonomy` | `deeptutor/services/skill/taxonomy.py` | 314 | 0 |  | 已建卡 | card AGEN-813 |  |
| FT135 | 235 | `agents.question.coordinator` | `deeptutor/agents/question/coordinator.py` | 242 | 0 |  | 仍可建卡 | 报告种子（deeptutor/agents/question/coordinator.py） |  |
| FT136 | 236 | `reading.refresh` | `deeptutor/reading/refresh.py` | 185 | 0 |  | 已建卡 | card AGEN-1372 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-1372 |
| FT137 | 237 | `reading.translation` | `deeptutor/reading/translation.py` | 133 | 0 |  | 已被main测试覆盖 | tests/plugins/test_registry_gating.py, tests/reading/test_translation.py |  |
| FT138 | 238 | `reading.vocabulary` | `deeptutor/reading/vocabulary.py` | 131 | 0 |  | 仍可建卡 | 报告种子（deeptutor/reading/vocabulary.py） |  |
| FT139 | 239 | `reading.study_guidance` | `deeptutor/reading/study_guidance.py` | 103 | 0 |  | 仍可建卡 | 报告种子（deeptutor/reading/study_guidance.py） |  |
| FT140 | 240 | `utils.network.circuit_breaker` | `deeptutor/utils/network/circuit_breaker.py` | 88 | 0 |  | 仍可建卡 | 报告种子（deeptutor/utils/network/circuit_breaker.py） |  |
| FT141 | 241 | `core.errors` | `deeptutor/core/errors.py` | 57 | 0 |  | 仍可建卡 | 报告种子（deeptutor/core/errors.py） |  |
| FT142 | 242 | `reading.read_aloud` | `deeptutor/reading/read_aloud.py` | 33 | 0 |  | 已建卡 | card AGEN-361 | 本卡新增匹配卡（不在 triage DONE 映射内）：AGEN-361 |

## 附：v1.6.13→v1.6.14 覆盖漂移（对已发布清单的影响）

- 基线 zero96 中已被测试覆盖 7 个：`tools.tex_chunker`、`tools.tex_downloader`、`services.llm.provider_core.github_copilot_provider`、`services.session.turns.title_service`、`services.llm.cloud_provider`、`services.base_sync`、`api.utils.progress_broadcaster`
- 基线 weak242 中触达≥2 的 15 个：`utils.document_validator`、`services.rag.visual_assets`、`api.routers.co_writer`、`services.mcp.network`、`runtime.coordination.journal`、`services.memory.consolidator.meta`、`api.utils.task_id_manager`、`book.agents.ideation_agent`、`co_writer.docx_converter`、`reading.epub_bilingual`、`co_writer.edit_agent`、`core.assessment`、`services.llm.local_provider`、`services.memory.consolidator.guards`、`reading.translation`
- 漂移异常：`services.session.workspace_preferences`（基线 weak100 #25）在 v1.6.14 中唯一覆盖测试消失，降为 zero；`learning.visual_practice`、`plugins.transactions`、`runtime.cache_reset` 为 v1.6.14 新增零覆盖模块（不在已发布清单内，供下一轮 harvest 参考）

