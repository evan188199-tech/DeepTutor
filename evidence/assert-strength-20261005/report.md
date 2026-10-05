# 测试断言强度全量清点（AGEN-773，静态 AST，只读）

- 基线 commit：`f07029cfcf2c8dfccdb671cdfc343db8334f5741`（origin/main，v1.6.13）
- 方法基线：`evidence/coverage-gaps-20261005/assertion_sample.py`（AGEN-662 §4）AST 口径全量扩展
- 模块全集：`deeptutor/` 下 1005 个 .py（排除内嵌 `learning/tests/`）；测试全集：`tests/` + 内嵌 `deeptutor/learning/tests/`，共 774 个文件
- 配对口径：与 `scan_coverage_gaps.py` 相同两级——T1 文件名词干对应、T2 import 对应（`__init__` 模块加包前缀回退）；本卡只统计**有测试对应**的 907 个模块（覆盖存在性归 scan-coverage-gaps 卡）。一处必要修正：基线 T2 的 `" ".join(names)` 子串匹配存在 PYTHONHASHSEED 顺序依赖（已实测同一模块在不同种子下漏配/误配），本卡改为确定性前缀匹配，种子 1/42/7 复跑结果完全一致
- 断言计数主口径 = §4 原口径（测试函数内 `ast.Assert` 语句数），弱断言判定严格按此口径，§4 全部 15 个抽样数字可逐一复现；另附**补充口径**（unittest 风格 `x.assertXxx()` 与 mock 风格 `x.assert_xxx()` 调用），用于识别"形式上零 assert 语句、实有行为断言"的用例，避免误伤
- 弱断言判定（卡面口径，主口径）：**中位断言/用例 ≤ 1** 或 **零断言用例占比 ≥ 20%**
- 复现：`python3 evidence/assert-strength-20261005/assert_strength_scan.py`（stdlib only，只读）

## 1. 总体分布

- 有测试对应的模块：907 / 1005；去重后涉及测试文件 753 个、测试函数 7760 个
- 其中 §4 口径零断言测试函数 462 个（占 6.0%；部分由 mock/unittest 断言覆盖，见 Top20 标注）
- **弱断言模块 130 个**（占已覆盖模块 14.3%），其中可独立拆卡的非 `__init__` 模块 113 个

| 中位断言/用例 | 模块数 |
|---|---|
| 0 | 4 |
| 1 | 84 |
| 2-3 | 728 |
| 4-6 | 85 |
| 7+ | 6 |

## 2. 弱断言热点 Top20

排序：零断言用例数（§4 口径）降序，其次模块行数（越大越值得拆增强卡）。包级 `__init__` 聚合行 17 个（`partners.bus`、`partners.channels`、`services.embedding.adapters`、`services.voice.adapters`、`services.videogen`、`services.imagegen`、`services.imagegen.adapters`、`services.videogen.adapters`、`agents.math_animator`、`agents.math_animator.agents`、`services.parsing.engines.text_only`、`services.rag.pipelines.kiwix`、`agents.vision_solver`、`capabilities.obsidian`、`services.prompt`、`logging.stats`、`agents.notebook`）不占名次、只在完整表内——数值继承自叶子模块。

| # | 模块 | 测试函数 | 断言数 | 中位 | 零断言(占比) | 其中纯mock/ut | raises | 模块LOC | 零断言用例示例（path:line） |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `partners.bus.queue` | 485 | 1014 | 1 | 67 (14%) | 21 | 25 | 63 | tests/services/partners/test_channel_streaming.py:133 `test_api_error_raises_for_manager_retry`；tests/services/partners/test_mattermost_channel.py:310 `test_post_failure_propagates_for_retry` |
| 2 | `api.routers._partners_channel_schema` | 127 | 241 | 1 | 23 (18%) | 10 | 11 | 176 | tests/api/test_partners_channel_schema.py:36 `test_allows_disabled_channel_with_empty_allow_list`；tests/services/partners/test_napcat_channel.py:106 `test_probability_policy_out_of_range_rejected` |
| 3 | `services.rag.pipelines.lightrag.ingress` | 96 | 322 | 3 | 20 (21%) | 20 | 51 | 364 | tests/services/rag/test_lightrag_ingress.py:130 `test_bundle_payload_rejects_a_symlinked_parent`；tests/services/rag/test_lightrag_ingress.py:154 `test_source_and_assets_reject_links` |
| 4 | `utils.document_extractor` | 55 | 100 | 2 | 14 (25%) | 14 | 16 | 1438 | tests/runtime/test_isolated_worker.py:38 `test_worker_timeout_terminates_the_child`；tests/runtime/test_isolated_worker.py:44 `test_worker_cancellation_terminates_the_child` |
| 5 | `partners.channels.zulip` | 111 | 166 | 1 | 14 (13%) | 1 | 1 | 859 | tests/services/partners/test_zulip_channel.py:743 `test_send_no_client_returns_early`；tests/services/partners/test_zulip_channel.py:544 `test_own_message_filtered`（仅 mock/unittest 断言） |
| 6 | `partners.channels.napcat` | 61 | 104 | 1 | 13 (21%) | 5 | 5 | 594 | tests/services/partners/test_napcat_channel.py:106 `test_probability_policy_out_of_range_rejected`；tests/services/partners/test_napcat_channel.py:496 `test_send_raises_when_not_connected` |
| 7 | `services.embedding.adapters.openai_compatible` | 66 | 74 | 1 | 12 (18%) | 12 | 14 | 406 | tests/services/embedding/test_disable_ssl_verify.py:149 `test_disable_ssl_verify_blocked_in_production`；tests/services/embedding/test_extract_embeddings.py:131 `test_non_dict_raises` |
| 8 | `services.rag.pipelines.llamaindex.exercise_lookup` | 12 | 0 | 0 | 12 (100%) | 0 | 0 | 373 | tests/services/rag/test_exercise_lookup.py:22 `test_number_intent_and_exclusions`（仅 mock/unittest 断言）；tests/services/rag/test_exercise_lookup.py:38 `test_join_cross_page_table_and_stop_at_next_problem`（仅 mock/unittest 断言） |
| 9 | `services.session.model_history` | 20 | 28 | 0 | 12 (60%) | 0 | 0 | 187 | tests/services/session/test_image_context_budget.py:60 `test_image_encoding_size_does_not_change_budget`（仅 mock/unittest 断言）；tests/services/session/test_image_context_budget.py:66 `test_reader_three_screenshots_fit_history_budget`（仅 mock/unittest 断言） |
| 10 | `services.rag.pipelines.ima.sources` | 61 | 125 | 1 | 12 (20%) | 12 | 14 | 105 | tests/services/rag/test_ima_pipeline.py:80 `test_incomplete_entry_raises`；tests/services/rag/test_ima_pipeline.py:106 `test_knowledge_base_id_is_never_inherited` |
| 11 | `services.prompt.lookup` | 12 | 0 | 0 | 12 (100%) | 0 | 0 | 25 | tests/services/rag/test_exercise_lookup.py:22 `test_number_intent_and_exclusions`（仅 mock/unittest 断言）；tests/services/rag/test_exercise_lookup.py:38 `test_join_cross_page_table_and_stop_at_next_problem`（仅 mock/unittest 断言） |
| 12 | `partners.channels.msteams` | 47 | 92 | 1 | 11 (23%) | 7 | 7 | 847 | tests/services/partners/test_msteams_channel.py:384 `test_send_without_http_client_raises`；tests/services/partners/test_msteams_channel.py:391 `test_send_without_ref_raises` |
| 13 | `tools.media_gen_tool` | 32 | 99 | 2 | 11 (34%) | 11 | 12 | 308 | tests/services/test_media_gen.py:79 `test_decode_base64_media_rejects_invalid_or_empty_payloads`；tests/services/test_media_gen.py:152 `test_imagegen_adapter_rejects_empty_url_download` |
| 14 | `services.videogen.adapters.dashscope` | 38 | 121 | 2 | 11 (29%) | 11 | 13 | 240 | tests/services/test_media_gen.py:79 `test_decode_base64_media_rejects_invalid_or_empty_payloads`；tests/services/test_media_gen.py:152 `test_imagegen_adapter_rejects_empty_url_download` |
| 15 | `services.videogen.adapters.async_task` | 32 | 99 | 2 | 11 (34%) | 11 | 12 | 182 | tests/services/test_media_gen.py:79 `test_decode_base64_media_rejects_invalid_or_empty_payloads`；tests/services/test_media_gen.py:152 `test_imagegen_adapter_rejects_empty_url_download` |
| 16 | `services.imagegen.adapters.dashscope` | 38 | 121 | 2 | 11 (29%) | 11 | 13 | 146 | tests/services/test_media_gen.py:79 `test_decode_base64_media_rejects_invalid_or_empty_payloads`；tests/services/test_media_gen.py:152 `test_imagegen_adapter_rejects_empty_url_download` |
| 17 | `services.imagegen.adapters.chat_completions` | 34 | 105 | 2 | 11 (32%) | 11 | 12 | 127 | tests/services/test_media_gen.py:79 `test_decode_base64_media_rejects_invalid_or_empty_payloads`；tests/services/test_media_gen.py:152 `test_imagegen_adapter_rejects_empty_url_download` |
| 18 | `services.imagegen.adapters.openai_compat` | 32 | 99 | 2 | 11 (34%) | 11 | 12 | 98 | tests/services/test_media_gen.py:79 `test_decode_base64_media_rejects_invalid_or_empty_payloads`；tests/services/test_media_gen.py:152 `test_imagegen_adapter_rejects_empty_url_download` |
| 19 | `services.generation_http` | 32 | 99 | 2 | 11 (34%) | 11 | 12 | 94 | tests/services/test_media_gen.py:79 `test_decode_base64_media_rejects_invalid_or_empty_payloads`；tests/services/test_media_gen.py:152 `test_imagegen_adapter_rejects_empty_url_download` |
| 20 | `partners.channels.mattermost` | 42 | 64 | 1 | 8 (19%) | 2 | 1 | 450 | tests/services/partners/test_mattermost_channel.py:310 `test_post_failure_propagates_for_retry`；tests/services/partners/test_mattermost_channel.py:318 `test_no_client_is_noop` |

## 3. 其余弱断言模块（21+，完整清单见 CSV）

| 模块 | 测试函数 | 断言数 | 中位 | 零断言(占比) | 模块LOC |
|---|---|---|---|---|---|
| `services.embedding.adapters.base` | 94 | 164 | 1 | 8 (9%) | 196 |
| `services.config.lightrag_roles` | 35 | 114 | 3 | 8 (23%) | 111 |
| `partners.channels.base` | 47 | 63 | 1 | 7 (15%) | 276 |
| `partners.channels.telegram` | 51 | 78 | 1 | 6 (12%) | 1145 |
| `utils.archive_extractor` | 12 | 18 | 2 | 5 (42%) | 200 |
| `services.voice.adapters.mimo` | 5 | 0 | 0 | 5 (100%) | 67 |
| `partners.config.schema` | 36 | 56 | 1 | 5 (14%) | 50 |
| `app.contracts` | 25 | 51 | 2 | 5 (20%) | 25 |
| `services.session._turn_runtime_shared` | 97 | 250 | 1 | 4 (4%) | 1574 |
| `services.rag.pipelines.lightrag.sidecar` | 11 | 50 | 1 | 4 (36%) | 320 |
| `services.embedding.adapters.cohere` | 21 | 23 | 1 | 4 (19%) | 176 |
| `services.embedding.adapters.jina` | 22 | 25 | 1 | 4 (18%) | 161 |
| `services.embedding.adapters.ollama` | 21 | 23 | 1 | 4 (19%) | 145 |
| `multi_user.session_handoff` | 14 | 34 | 2 | 3 (21%) | 476 |
| `services.rag.pipelines.lightrag.worker` | 16 | 26 | 1 | 3 (19%) | 259 |
| `runtime.request_contracts` | 14 | 45 | 3 | 3 (21%) | 233 |
| `services.memory.consolidator.parse` | 24 | 38 | 1 | 3 (12%) | 135 |
| `services.voice.adapters.minimax` | 8 | 27 | 2 | 3 (38%) | 91 |
| `services.file_io` | 11 | 24 | 2 | 3 (27%) | 88 |
| `services.parsing.base` | 33 | 54 | 1 | 3 (9%) | 84 |
| `book.blocks._prompts` | 9 | 12 | 1 | 3 (33%) | 67 |
| `services.parsing.signature` | 19 | 32 | 1 | 3 (16%) | 50 |
| `services.llm.image_description` | 9 | 23 | 2 | 3 (33%) | 46 |
| `services.codebuddy_credentials` | 19 | 34 | 1 | 2 (11%) | 363 |
| `api.contracts.turn_protocol` | 7 | 20 | 2 | 2 (29%) | 309 |
| `services.llm.provider_core.azure_openai_provider` | 29 | 51 | 1 | 2 (7%) | 249 |
| `runtime.isolated_worker` | 7 | 7 | 1 | 2 (29%) | 215 |
| `services.voice.adapters.volcengine` | 10 | 50 | 5 | 2 (20%) | 207 |
| `reading.translation` | 8 | 19 | 2 | 2 (25%) | 133 |
| `reading.vocabulary` | 8 | 19 | 2 | 2 (25%) | 131 |
| `services.mcp.network` | 14 | 20 | 1 | 2 (14%) | 121 |
| `reading.study_guidance` | 9 | 20 | 1 | 2 (22%) | 103 |
| `runtime.capability_routing` | 7 | 20 | 2 | 2 (29%) | 88 |
| `agents._shared.json_output` | 6 | 4 | 1 | 2 (33%) | 76 |
| `services.session.workspace_preferences` | 7 | 13 | 2 | 2 (29%) | 55 |
| `services.llm.utils` | 26 | 45 | 1 | 1 (4%) | 369 |
| `capabilities.obsidian.vault` | 25 | 44 | 1 | 1 (4%) | 324 |
| `agents.math_animator.agents.code_generator_agent` | 5 | 14 | 2 | 1 (20%) | 261 |
| `services.llm.provider_core.codebuddy_http_provider` | 9 | 13 | 1 | 1 (11%) | 258 |
| `agents.vision_solver.vision_solver_agent` | 4 | 6 | 2 | 1 (25%) | 205 |
| `agents.visualize.utils` | 24 | 41 | 1 | 1 (4%) | 191 |
| `services.session.artifact_attachments` | 20 | 66 | 1 | 1 (5%) | 179 |
| `agents.math_animator.retry_manager` | 4 | 22 | 6 | 1 (25%) | 160 |
| `runtime.update_worker` | 3 | 10 | 4 | 1 (33%) | 158 |
| `agents.math_animator.utils` | 22 | 38 | 1 | 1 (5%) | 124 |
| `agents.math_animator.agents.concept_analysis_agent` | 3 | 6 | 2 | 1 (33%) | 97 |
| `api.routers.attachments` | 17 | 26 | 1 | 1 (6%) | 79 |
| `runtime.agentic.messages` | 9 | 13 | 1 | 1 (11%) | 79 |
| `agents.math_animator.agents.summary_agent` | 3 | 6 | 2 | 1 (33%) | 78 |
| `agents.math_animator.agents.concept_design_agent` | 3 | 6 | 2 | 1 (33%) | 76 |
| `multi_user.skill_access` | 4 | 9 | 2 | 1 (25%) | 74 |
| `services.rag.pipelines.graphrag.pandas_compat` | 2 | 2 | 2 | 1 (50%) | 68 |
| `services.session.organization` | 3 | 3 | 1 | 1 (33%) | 59 |
| `knowledge.naming` | 9 | 13 | 1 | 1 (11%) | 40 |
| `agents.math_animator.request_config` | 2 | 3 | 3 | 1 (50%) | 38 |
| `services.rag.file_routing` | 29 | 69 | 1 | 0 (0%) | 401 |
| `services.memory.consolidator.references` | 17 | 33 | 1 | 0 (0%) | 388 |
| `services.subagent.antigravity` | 19 | 35 | 1 | 0 (0%) | 313 |
| `learning.pending` | 39 | 59 | 1 | 0 (0%) | 283 |
| `capabilities.mastery.choices` | 46 | 74 | 1 | 0 (0%) | 273 |
| `textbook_struct.chapter_rebuild` | 11 | 20 | 1 | 0 (0%) | 273 |
| `book.blocks.base` | 19 | 34 | 1 | 0 (0%) | 246 |
| `services.rag.eval.dataset` | 18 | 30 | 1 | 0 (0%) | 244 |
| `services.mcp.user_config` | 34 | 54 | 1 | 0 (0%) | 233 |
| `partners.channels.whatsapp` | 2 | 2 | 1 | 0 (0%) | 210 |
| `utils.document_validator` | 9 | 13 | 1 | 0 (0%) | 206 |
| `utils.json_parser` | 35 | 37 | 1 | 0 (0%) | 201 |
| `logging.stats.llm_stats` | 3 | 3 | 1 | 0 (0%) | 200 |
| `runtime.agentic.tool_arg_guard` | 15 | 34 | 1 | 0 (0%) | 195 |
| `agents.loop.ask_user_drafts` | 7 | 15 | 1 | 0 (0%) | 193 |
| `services.llm.usage_frame` | 17 | 34 | 1 | 0 (0%) | 176 |
| `services.llm.error_mapping` | 8 | 11 | 1 | 0 (0%) | 175 |
| `api.routers.file_library` | 21 | 41 | 1 | 0 (0%) | 169 |
| `learning.topic_naming` | 6 | 11 | 1 | 0 (0%) | 166 |
| `agents.notebook.summarize_agent` | 4 | 5 | 1 | 0 (0%) | 120 |
| `book.blocks.text` | 11 | 19 | 1 | 0 (0%) | 117 |
| `runtime.agentic.tool_call_stream` | 9 | 14 | 1 | 0 (0%) | 110 |
| `textbook_struct.page_headers` | 11 | 20 | 1 | 0 (0%) | 100 |
| `services.rag.pipelines.lightrag.parser` | 35 | 37 | 1 | 0 (0%) | 99 |
| `agents.research.utils.json_utils` | 3 | 3 | 1 | 0 (0%) | 94 |
| `runtime.providers.text` | 9 | 12 | 1 | 0 (0%) | 91 |
| `services.search.base` | 17 | 27 | 1 | 0 (0%) | 89 |
| `utils.network.circuit_breaker` | 11 | 17 | 1 | 0 (0%) | 88 |
| `services.settings.starter_settings` | 5 | 7 | 1 | 0 (0%) | 82 |
| `learning.grading` | 24 | 44 | 1 | 0 (0%) | 64 |
| `services.subagent.base` | 17 | 27 | 1 | 0 (0%) | 63 |
| `runtime.providers.authorize` | 8 | 11 | 1 | 0 (0%) | 59 |
| `utils.secret_files` | 6 | 7 | 1 | 0 (0%) | 48 |
| `services.videogen.base` | 17 | 27 | 1 | 0 (0%) | 42 |
| `services.rag.pipelines.base` | 17 | 27 | 1 | 0 (0%) | 41 |
| `utils.text_display` | 3 | 4 | 1 | 0 (0%) | 31 |
| `services.imagegen.base` | 17 | 27 | 1 | 0 (0%) | 24 |
| `services.workspace.references` | 17 | 33 | 1 | 0 (0%) | 20 |

## 4. 可拆增强卡条目（Top 弱点，均只补断言不改产品代码）

1. **test: queue 断言语义增强** — 现状 485 用例仅 1014 断言（中位 1，零断言 67 个）。目标：为 `deeptutor/partners/bus/queue.py` 对应用例补语义/边界断言（零断言用例如 test_api_error_raises_for_manager_retry；test_post_failure_propagates_for_retry；test_no_client_is_noop），移出弱断言区。 注意：配对含 21 个测试文件（T1 词干同名也会并入），拆卡时先按 T2 import 关系圈定实际覆盖用例。
2. **test: _partners_channel_schema 断言语义增强** — 现状 127 用例仅 241 断言（中位 1，零断言 23 个）。目标：为 `deeptutor/api/routers/_partners_channel_schema.py` 对应用例补语义/边界断言（零断言用例如 test_allows_disabled_channel_with_empty_allow_list；test_probability_policy_out_of_range_rejected；test_send_raises_when_not_connected），移出弱断言区。 注意：配对含 4 个测试文件（T1 词干同名也会并入），拆卡时先按 T2 import 关系圈定实际覆盖用例。
3. **test: ingress 断言语义增强** — 现状 96 用例仅 322 断言（中位 3，零断言 20 个）。目标：为 `deeptutor/services/rag/pipelines/lightrag/ingress.py` 对应用例补语义/边界断言（零断言用例如 test_bundle_payload_rejects_a_symlinked_parent；test_source_and_assets_reject_links；test_same_canonical_basename_is_rejected_before_enqueue），移出弱断言区。 注意：配对含 4 个测试文件（T1 词干同名也会并入），拆卡时先按 T2 import 关系圈定实际覆盖用例。
4. **test: document_extractor 断言语义增强** — 现状 55 用例仅 100 断言（中位 2，零断言 14 个）。目标：为 `deeptutor/utils/document_extractor.py` 对应用例补语义/边界断言（零断言用例如 test_worker_timeout_terminates_the_child；test_worker_cancellation_terminates_the_child；test_archive_normalization_rejects_a_bad_zip），移出弱断言区。
5. **test: zulip 断言语义增强** — 现状 111 用例仅 166 断言（中位 1，零断言 14 个）。目标：为 `deeptutor/partners/channels/zulip.py` 对应用例补语义/边界断言（零断言用例如 test_send_no_client_returns_early；test_own_message_filtered；test_duplicate_message_filtered），移出弱断言区。
6. **test: napcat 断言语义增强** — 现状 61 用例仅 104 断言（中位 1，零断言 13 个）。目标：为 `deeptutor/partners/channels/napcat.py` 对应用例补语义/边界断言（零断言用例如 test_probability_policy_out_of_range_rejected；test_send_raises_when_not_connected；test_send_raises_on_invalid_chat_id），移出弱断言区。
7. **test: openai_compatible 断言语义增强** — 现状 66 用例仅 74 断言（中位 1，零断言 12 个）。目标：为 `deeptutor/services/embedding/adapters/openai_compatible.py` 对应用例补语义/边界断言（零断言用例如 test_disable_ssl_verify_blocked_in_production；test_non_dict_raises；test_error_payload_string），移出弱断言区。 注意：配对含 8 个测试文件（T1 词干同名也会并入），拆卡时先按 T2 import 关系圈定实际覆盖用例。
8. **test: exercise_lookup 断言语义增强** — 现状 12 用例仅 0 断言（中位 0，零断言 12 个）。目标：为 `deeptutor/services/rag/pipelines/llamaindex/exercise_lookup.py` 对应用例补语义/边界断言（零断言用例如 test_number_intent_and_exclusions；test_join_cross_page_table_and_stop_at_next_problem；test_chapter_only_numbers_multiple_questions_and_footer），移出弱断言区。

## 5. 附：完整数据表与口径备注

全部 907 个有对应模块逐行数据（含每个覆盖测试文件的分文件指标）见 `assert_strength_full.csv`（模块级）与 `assert_strength_raw.json`（模块级+分文件+逐用例）。

- 模块级指标 = 该模块全部覆盖测试文件中所有测试函数（主口径）断言数的合并分布（中位沿用基线 `sorted[n//2]` 规则）。
- §4 对照：15 个 §4 抽样文件中 13 个由本配对口径自动命中且数字逐位一致（`asserts` 主口径）。`api.routers.mastery_path` 未自动命中 `deeptutor/learning/tests/test_mastery_tools.py`——该文件为内嵌测试目录，其相对导入按 `tests/` 根解析，无法还原为 `deeptutor.*` 全名，T2 无法命中（该模块经其他测试文件配对，union 72 用例/209 断言）；`core.config_manager` 为 §4 手工对照行（其测试文件经 fixture 间接使用模块，不在 T1/T2 命中范围）。两者均为 §4 手工抽样，不是本口径的回归。
- 已知限制：T1 词干匹配会把同名词干的无关测试并入（如 `queue`），import 配对会把目录级 conftest 并入对应模块；两者均为基线既有口径，未放宽或收紧。
