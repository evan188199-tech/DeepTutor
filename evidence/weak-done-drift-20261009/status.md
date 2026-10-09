# weak242 已建卡 DONE 索引覆盖漂移复核（20261009）

## 输入与口径
- 基线：`origin/main` = `6cf793bd868b`（v1.6.14，2026-10-08）；新 worktree + 新分支，只读复核，未改产品代码
- 索引来源：myfork `scan/weak-top100-triage-20261008` → `evidence/weak-triage-20261008/triage.md` 文末「已建卡索引（weak242 内全部 DONE）」，去重后 60 个唯一模块（AGEN-947 与 AGEN-741/742 重复，不重复计）
- 判定：模块文件在 main 是否存在（改名/删除=文件漂移）；main 内 `tests/**` 与 `deeptutor/**/tests/test_*.py` 是否有触达（import / patch 全名 / 文件名）。人工复核剔除「仅被其他子系统测试 monkeypatch 打桩」的假触达；包 `__init__` 再导出间接触达按已触达计（已注明）

## 逐模块状态（60）

| # | 模块 | 卡 | 文件@main | 触达测试（main） | 状态 | 备注 |
|---|------|----|-----------|------------------|------|------|
| 1 | `agents.loop.context_budget` | AGEN-1053 | 在 | tests/agents/chat/test_context_budget.py | 已合入 |  |
| 2 | `api.contracts.turn_protocol` | AGEN-1147 | 在 | tests/runtime/test_request_contracts_subagent.py | 已合入 |  |
| 3 | `api.routers.file_preview` | AGEN-764 | 在 | tests/api/test_file_preview.py | 已合入 |  |
| 4 | `api.routers.mcp_settings` | AGEN-832 | 在 | tests/api/test_mcp_settings_auth.py | 已合入 |  |
| 5 | `api.routers.partner_groups` | AGEN-763 | 在 | tests/api/test_partner_groups_router.py | 已合入 |  |
| 6 | `api.routers.question_notebook` | AGEN-838 | 在 | tests/api/test_notebook_api_contract.py<br>tests/api/test_notebook_router.py<br>tests/api/test_practice.py<br>tests/api/test_question_bank_api.py | 已合入 |  |
| 7 | `api.routers.space_cli_apps` | AGEN-833 | 在 | tests/api/test_space_cli_apps.py | 已合入 |  |
| 8 | `api.routers.space_mcp` | AGEN-780 | 在 | tests/api/test_space_mcp.py | 已合入 |  |
| 9 | `api.run_server` | AGEN-1060 | 在 | tests/runtime/test_run_server_memory_mode.py<br>tests/runtime/test_uvicorn_launch_flags.py | 已合入 |  |
| 10 | `book.agents.page_planner` | AGEN-966 | 在 | tests/book/test_block_type_controls.py<br>tests/runtime/test_api_import_memory_boundary.py | 已合入 |  |
| 11 | `capabilities.obsidian.vault` | AGEN-807 | 在 | tests/capabilities/test_obsidian_capability.py | 已合入 |  |
| 12 | `co_writer.edit_agent` | AGEN-751 | 在 | tests/api/routers/test_co_writer_contract.py<br>tests/api/test_co_writer.py<br>tests/runtime/test_api_import_memory_boundary.py | 已合入 |  |
| 13 | `learning.assessment` | AGEN-1050 | 在 | deeptutor/learning/tests/test_assessment.py | 已合入 |  |
| 14 | `learning.grading` | AGEN-1035 | 在 | deeptutor/learning/tests/test_grading.py | 已合入 |  |
| 15 | `learning.objective_relations` | AGEN-1133 | 在 | deeptutor/learning/tests/test_objective_relations.py | 已合入 |  |
| 16 | `learning.pending` | AGEN-793 | 在 | deeptutor/learning/tests/test_mastery_choices.py | 已合入 |  |
| 17 | `learning.topic_naming` | AGEN-1135 | 在 | deeptutor/learning/tests/test_topic_naming.py | 已合入 |  |
| 18 | `multi_user.book_access` | AGEN-828 | 在 | tests/multi_user/test_book_permission.py | 已合入 |  |
| 19 | `partners.channels.lark_http` | AGEN-736 | 在 | tests/services/partners/test_lark_keep_alive.py | 已合入 |  |
| 20 | `partners.channels.matrix` | AGEN-743 | 在 | — | 仍缺 | myfork/test/matrix-channel-20261005 未合入 |
| 21 | `partners.channels.msteams` | AGEN-741/AGEN-947 | 在 | tests/services/partners/test_msteams_channel.py | 已合入 |  |
| 22 | `partners.channels.napcat` | AGEN-742/AGEN-947 | 在 | tests/services/partners/test_napcat_channel.py | 已合入 |  |
| 23 | `partners.channels.wecom` | AGEN-1051 | 在 | tests/services/partners/test_wecom_channel.py | 已合入 |  |
| 24 | `runtime.background_leader` | AGEN-863 | 在 | tests/runtime/test_background_leader.py | 已合入 |  |
| 25 | `services.chat_hints` | AGEN-993 | 在 | tests/services/test_chat_hints.py | 已合入 |  |
| 26 | `services.config.readiness` | AGEN-787 | 在 | tests/services/config/test_readiness.py | 已合入 |  |
| 27 | `services.doctor` | AGEN-914 | 在 | tests/cli/test_doctor_cli.py | 已合入 |  |
| 28 | `services.embedding.adapters.dashscope_native` | AGEN-913 | 在 | tests/services/embedding/test_dashscope_adapter.py | 已合入 |  |
| 29 | `services.embedding.adapters.gemini` | AGEN-913 | 在 | tests/services/embedding/test_gemini_adapter.py | 已合入 |  |
| 30 | `services.generation_http` | AGEN-1010 | 在 | tests/services/test_media_gen.py | 已合入 |  |
| 31 | `services.llm.error_mapping` | AGEN-1036 | 在 | tests/services/llm/test_error_mapping.py | 已合入 |  |
| 32 | `services.llm.local_provider` | AGEN-847 | 在 | tests/api/test_github_copilot_models.py<br>tests/services/llm/test_local_provider.py | 已合入 |  |
| 33 | `services.memory.consolidator.line_doc` | AGEN-1141 | 在 | tests/services/memory/test_line_doc.py | 已合入 |  |
| 34 | `services.memory.consolidator.modes.audit` | AGEN-782 | 在 | tests/services/memory/test_modes.py | 已合入 |  |
| 35 | `services.office_preview` | AGEN-790 | 在 | tests/api/test_file_preview.py | 已合入 |  |
| 36 | `services.parsing.engines._install` | AGEN-915 | 在 | tests/services/parsing/test_engines.py | 已合入 |  |
| 37 | `services.partners.weixin_onboarding` | AGEN-808 | 在 | tests/services/partners/test_weixin_onboarding.py | 已合入 |  |
| 38 | `services.rag.eval.dataset` | AGEN-912 | 在 | tests/services/rag/eval/test_eval_dataset.py（经包 __init__ 再导出） | 已合入 |  |
| 39 | `services.rag.eval.matching` | AGEN-912 | 在 | tests/services/rag/eval/test_eval_matching.py | 已合入 |  |
| 40 | `services.rag.pipelines.lightrag.sidecar` | AGEN-811 | 在 | tests/services/rag/test_lightrag_ingress.py | 已合入 |  |
| 41 | `services.rag.provider_binding` | AGEN-824 | 在 | tests/book/test_source_partitioning.py<br>tests/cli/test_kb_eval_cli.py<br>tests/services/rag/test_lightrag_roles.py<br>tests/services/rag/test_pageindex_tools.py<br>…共5个 | 仍缺 | myfork/test/rag-provider-binding-20261006 未合入 |
| 42 | `services.reading_hints` | AGEN-745 | 在 | tests/reading/test_reading_hints.py | 已合入 |  |
| 43 | `services.search.consolidation` | AGEN-1052 | 在 | tests/services/search/test_search_providers.py | 已合入 |  |
| 44 | `services.search.source_filter` | AGEN-974 | 在 | tests/services/search/test_web_search_runtime.py | 已合入 |  |
| 45 | `services.skill.taxonomy` | AGEN-813 | 在 | tests/services/skill/test_skill_publish_flow.py | 已合入 |  |
| 46 | `services.subagent.claude_code` | AGEN-1142 | 在 | tests/services/test_subagent_backends.py | 已合入 |  |
| 47 | `services.subagent.deepseek_harness` | AGEN-1143 | 在 | tests/services/test_subagent_backends.py | 已合入 |  |
| 48 | `services.subagent.opencode_server` | AGEN-845 | 在 | tests/services/test_subagent_backends.py | 已合入 |  |
| 49 | `services.voice.adapters.openai_compat` | AGEN-1056 | 在 | tests/services/test_voice.py | 已合入 |  |
| 50 | `services.voice.adapters.volcengine` | AGEN-916 | 在 | tests/services/test_volcengine_voice.py | 已合入 |  |
| 51 | `services.workspace.dependencies` | AGEN-1144 | 在 | tests/services/workspace/test_data_migration.py | 已合入 |  |
| 52 | `services.workspace.kb_move` | AGEN-976 | 在 | tests/multi_user/test_kb_move.py | 已合入 |  |
| 53 | `services.workspace.session_transfer` | AGEN-831 | 在 | tests/services/workspace/test_data_migration.py | 已合入 |  |
| 54 | `tools.mastery_nav` | AGEN-973 | 在 | deeptutor/learning/tests/test_mastery_navigation.py | 已合入 |  |
| 55 | `tools.media_gen_tool` | AGEN-1086 | 在 | tests/services/test_media_gen.py | 已合入 |  |
| 56 | `tools.partner_memory` | AGEN-1145 | 在 | tests/services/partners/test_partner_memory_tools.py | 已合入 |  |
| 57 | `tools.question_bank` | AGEN-972 | 在 | tests/tools/test_question_bank_tool.py | 已合入 |  |
| 58 | `tools.reason` | AGEN-849 | 在 | tests/core/test_builtin_tools.py<br>tests/tools/test_knowledge_frontier_tool.py | 仍缺 | myfork/test/reason-brainstorm-tools-20261006 未合入 |
| 59 | `tools.vision.ggb_validator` | AGEN-977 | 在 | tests/visualizers/test_ggb_validator.py | 已合入 |  |
| 60 | `video_learning.invidious_account` | AGEN-806 | 在 | tests/video_learning/test_invidious_account.py | 已合入 |  |
