# weak_single_test top100 补测种子 triage（20261008）

## 输入与边界
- 扫描证据：`evidence/coverage-gaps-20261007/{coverage_raw,summary}.json`（myfork `scan/coverage-gaps-20261007`，root_commit `f07029cf` = v1.6.13），只读
- weak 定义（复现 aggregate.py）：非 `__init__`、非 `test_*` 模块，`tests/` 触达数 + in-tree（`deeptutor/**/tests/test_*`）触达数 == 1，共 242 个
- 本卡只做 triage：不改任何产品代码/测试；`⚠` = 该文件在 `f07029cf..origin/main`（6cf793bd，v1.6.14）间有改动，拆卡前需在 origin/main 复核职责

## 排序口径（可复算）
- 复算：`python3 triage.py <临时目录>`，脚本内断言 fanin/weak_top100/zero_top200 与 summary.json 完全一致后才输出
- `score = fanin×10 + min(LOC,500)÷50（整除） + bonus×15`；并列按 LOC↓、fanin↓、模块名字典序
- `fanin` = 包内静态 import 反向依赖模块数（与 summary.json 同一口径，含其 importer 拼写特性）
- `bonus`：2=用户面路由/启动/runtime 核心（`api/routers/*`、`api.run_server`、`services.config.readiness`、`runtime.*`）；1=管线/交付面（partners、llm、rag、embedding、parsing、voice、imagegen、tools、workspace、memory、search、subagent、multi_user、learning、co_writer、book、capabilities、video_learning、api.*）；0=其他
- `风险`：高=fanin≥5 或 bonus=2；中=fanin 2-4 或 LOC≥300 或 bonus=1；低=其余

## 去重口径
- DONE 映射：2026-10-08 人工核对项目卡（`test:` 前缀卡标题/描述与模块 path、dotted 名、目录片段、词干逐一匹配并复核描述目标文件），weak242 内已建卡 60 个（top100 内 28 个）
- 建卡但已不属 weak242 的 3 个模块：`capabilities.mastery.choices`(AGEN-1151)、`learning.topic_generation`(AGEN-1139)、`learning.topic_materials`(AGEN-1140)——已被 in-tree 测试触达（触发数=2）
- AGEN-1064/967 的目标是 `services/parsing/engines/formats.py`（顶层分派，zero 表）；各引擎子目录 `formats.py`（markitdown/docling/…）不在其范围，本表仍列为待拆

## top100
| # | 模块 | path | LOC | fanin | score | 风险 | 建议测试焦点 | 状态 |
|---|------|------|----:|------:|------:|------|--------------|------|
| 1 | `utils.json_parser` | `deeptutor/utils/json_parser.py` | 201 | 15 | 154 | 高 | 「Robust JSON parsing utilities with」覆盖 parse_json_response/safe_json_loads 契约与边界＋异常/降级分支 | TODO |
| 2 | `services.rag.provider_binding` | `deeptutor/services/rag/provider_binding.py` | 70 | 13 | 146 | 高 | 「Resolve a knowledge base's bound RAG」覆盖 load_kb_config_entry/load_metadata_provider/resolve_bound_provider 契约与边界＋异常/降级分支 | DONE(AGEN-824) |
| 3 | `services.llm.structured_retry` | `deeptutor/services/llm/structured_retry.py` | 111 | 11 | 127 | 高 | 「One retry for a structured call a reasoning」覆盖 json_payload_is_usable/payload_with_reasoning_retry/json_with_reasoning_retry 契约与边界＋超时/限流/畸形响应分支 | TODO |
| 4 | `services.keypool` | `deeptutor/services/keypool.py` | 81 | 12 | 121 | 高 | 「Thread-safe round-robin API key rotation」覆盖 KeyPool/primary_api_key 契约与边界＋异常/降级分支 | TODO |
| 5 | `services.generation_http` | `deeptutor/services/generation_http.py` | 94 | 11 | 111 | 高 | 「Shared HTTP plumbing for media-generation」覆盖 GenerationProviderError/decode_base64_media/build_auth_headers/join_api_path 契约与边界＋异常/降级分支 | DONE(AGEN-1010) |
| 6 | `multi_user.tool_access` | `deeptutor/multi_user/tool_access.py` | 113 | 9 | 107 | 高 | 「Per-user tool and exec access resolution」覆盖 allowed_optional_tools/allowed_mcp_tools/allowed_cli_apps/exec_override 契约与边界＋异常/降级分支 | TODO |
| 7 | `learning.pending` | `deeptutor/learning/pending.py` | 283 | 8 | 100 | 高 | 「Public, stable views of pending mastery」覆盖 positional_label/option_label_intent/canonical_labels/parse_options 契约与边界＋异常/降级分支 | DONE(AGEN-793) |
| 8 | `utils.secret_files` | `deeptutor/utils/secret_files.py` | 48 | 10 | 100 | 高 | 「Helpers for writing files that hold secrets.」覆盖 ensure_private_directory/ensure_private_file/write_secret_text 契约与边界＋异常/降级分支 | TODO |
| 9 | `services.workspace.resources` | `deeptutor/services/workspace/resources.py` | 223 | 8 | 99 | 高 | 「Workspace resource selections. Missing/null」覆盖 WorkspaceResources/turn_resource_selection/current_resources/validate_resources 契约与边界＋异常/降级分支 | TODO |
| 10 | `learning.assessment` | `deeptutor/learning/assessment.py` | 557 | 6 | 85 | 高 | 「Unified assessment adapter for the Question」覆盖 RecordAssessmentError/AssessmentOutcome/result_to_is_correct/is_correct_to_result 契约与边界＋异常/降级分支 | DONE(AGEN-1050) |
| 11 | `services.prompt.lookup` | `deeptutor/services/prompt/lookup.py` | 25 | 8 | 80 | 高 | 「Reading one string out of a loaded prompt」覆盖 prompt_text 契约与边界＋异常/降级分支 | TODO |
| 12 | `services.llm.types` | `deeptutor/services/llm/types.py` | 86 | 6 | 76 | 高 | 「Shared LLM response data models.」覆盖 finish_was_truncated/StreamOutcome/TutorResponse/TutorStreamChunk 契约与边界＋超时/限流/畸形响应分支 | TODO |
| 13 | `services.parsing.engines.mineru.formats` | `deeptutor/services/parsing/engines/mineru/formats.py` | 46 | 6 | 75 | 高 | 「Input formats supported by the current」覆盖 mineru_version_is_current 契约与边界＋异常/降级分支 | TODO |
| 14 | `utils.document_validator` | `deeptutor/utils/document_validator.py` | 206 | 7 | 74 | 高 | 「Document Validator - Validation utilities」覆盖 DocumentValidator 契约与边界＋异常/降级分支 | TODO |
| 15 | `runtime.coordination.protocol` | `deeptutor/runtime/coordination/protocol.py` | 74 | 4 | 71 | 高 | 「Port used by the application layer for」覆盖 RuntimeCoordinator 契约与边界＋启动/装配失败路径 | TODO |
| 16 | `multi_user.personal_models` | `deeptutor/multi_user/personal_models.py` | 165 | 5 | 68 | 高 | 「Owner-bound LLM profiles an ordinary user」覆盖 owner_catalog_service/personal_llm_rows/merge_personal_llm_profiles 契约与边界＋异常/降级分支 | TODO |
| 17 | `services.rag.kb_paths` | `deeptutor/services/rag/kb_paths.py` | 50 | 5 | 66 | 高 | 「Resolve the on-disk directory backing a」覆盖 resolve_kb_dir 契约与边界＋异常/降级分支 | TODO |
| 18 | `book.agents.page_planner` | `deeptutor/book/agents/page_planner.py` | 427 | 4 | 63 | 中 | 「Section Architect (formerly PagePlanner)」覆盖 SectionArchitect/PagePlanner 契约与边界＋异常/降级分支 | DONE(AGEN-966) |
| 19 | `runtime.agentic.labels` | `deeptutor/runtime/agentic/labels.py` | 173 | 3 | 63 | 高 | 「Protocol-label parsing for streaming LLM」覆盖 strip_label_probe_prefix/classify_label/recover_finished_label/find_inline_labels 契约与边界＋启动/装配失败路径 | TODO |
| 20 | `services.rag.visual_assets` | `deeptutor/services/rag/visual_assets.py` | 386 | 4 | 62 | 中 | 「Verified, parser-independent source images」覆盖 source_key_for/VisualAssetCandidate/collect_visual_assets/VisualAssetStore 契约与边界＋异常/降级分支 | TODO⚠ |
| 21 | `runtime.agentic.tool_call_stream` | `deeptutor/runtime/agentic/tool_call_stream.py` | 110 | 3 | 62 | 高 | 「Accumulate OpenAI-compatible streaming」覆盖 ToolCallAccumulator 契约与边界＋启动/装配失败路径 | TODO |
| 22 | `api.contracts.turn_protocol` | `deeptutor/api/contracts/turn_protocol.py` | 309 | 4 | 61 | 中 | 「Canonical v2 wire models for the browser」覆盖 TurnStatus/TurnQueryState/TurnFailureCode/StreamEventType 契约与边界＋异常/降级分支 | DONE(AGEN-1147) |
| 23 | `runtime.memory_reclaim` | `deeptutor/runtime/memory_reclaim.py` | 73 | 3 | 61 | 高 | 「Best-effort memory reclamation after」覆盖 release_unused_memory/schedule_memory_reclaim 契约与边界＋启动/装配失败路径 | TODO |
| 24 | `services.session.organization` | `deeptutor/services/session/organization.py` | 59 | 6 | 61 | 高 | 「Integrity helpers for session organization」覆盖 list_all_sessions_snapshot/validate_parent_assignment 契约与边界＋异常/降级分支 | TODO |
| 25 | `services.session.workspace_preferences` | `deeptutor/services/session/workspace_preferences.py` | 55 | 6 | 61 | 高 | 「Canonical workspace ownership stored on」覆盖 upgrade_workspace_preferences 契约与边界＋异常/降级分支 | TODO⚠ |
| 26 | `api.routers.co_writer` | `deeptutor/api/routers/co_writer.py` | 874 | 2 | 60 | 高 | 覆盖 get_edit_agent/LLMSelectionPayload/EditRequest/EditResponse 契约与边界＋失败/4xx 分支 | TODO |
| 27 | `api.routers.question_notebook` | `deeptutor/api/routers/question_notebook.py` | 595 | 2 | 60 | 高 | 「Question Notebook API — persists quiz」覆盖 AnswerImageItem/CategoryItem/NotebookEntryItem/NotebookEntryListResponse 契约与边界＋失败/4xx 分支 | DONE(AGEN-838) |
| 28 | `agents.math_animator.request_config` | `deeptutor/agents/math_animator/request_config.py` | 38 | 6 | 60 | 高 | 「Validated request config for the math」覆盖 MathAnimatorRequestConfig/validate_math_animator_request_config 契约与边界＋异常/降级分支 | TODO |
| 29 | `services.memory.consolidator.modes.merge` | `deeptutor/services/memory/consolidator/modes/merge.py` | 227 | 4 | 59 | 中 | 「Merge mode — consolidate footnote」覆盖 MergeResult/run_merge 契约与边界＋异常/降级分支 | TODO |
| 30 | `learning.objective_relations` | `deeptutor/learning/objective_relations.py` | 181 | 4 | 58 | 中 | 「Validation and request-reference handling」覆盖 ObjectiveRelationError/RelationRefs/normalize_refs/source_ref_map 契约与边界＋异常/降级分支 | DONE(AGEN-1133) |
| 31 | `services.embedding.validation` | `deeptutor/services/embedding/validation.py` | 128 | 4 | 57 | 中 | 「Validation helpers for embedding vectors.」覆盖 validate_embedding_batch 契约与边界＋超时/限流/畸形响应分支 | TODO |
| 32 | `services.llm.provider_core.codebuddy_provider` | `deeptutor/services/llm/provider_core/codebuddy_provider.py` | 839 | 3 | 55 | 中 | 「CodeBuddy Agent SDK provider.」覆盖 CodeBuddyProvider/fetch_codebuddy_models 契约与边界＋超时/限流/畸形响应分支 | TODO⚠ |
| 33 | `services.memory.consolidator.line_doc` | `deeptutor/services/memory/consolidator/line_doc.py` | 482 | 3 | 54 | 中 | 「Line-numbered view of a memory document +」覆盖 Line/LineView/ReplaceLineOp/DeleteLinesOp 契约与边界＋异常/降级分支 | DONE(AGEN-1141) |
| 34 | `runtime.isolated_worker` | `deeptutor/runtime/isolated_worker.py` | 215 | 2 | 54 | 高 | 「Run memory-heavy, importable functions in」覆盖 IsolatedWorkerError/IsolatedWorkerTimeout/IsolatedWorkerCrashed/run_in_isolated_process_sync 契约与边界＋启动/装配失败路径 | TODO |
| 35 | `tools.vision.ggb_validator` | `deeptutor/tools/vision/ggb_validator.py` | 411 | 3 | 53 | 中 | 「GeoGebra command validator and fixer.」覆盖 ValidationResult/fix_brackets/fix_common_mistakes/validate_equation_format 契约与边界＋异常/降级分支 | DONE(AGEN-977) |
| 36 | `tools.ask_user` | `deeptutor/tools/ask_user.py` | 383 | 3 | 52 | 中 | 「Build the payload for the ``ask_user`` tool.」覆盖 AskUserOption/AskUserQuestion/AskUserPayload/build_ask_user_payload 契约与边界＋异常/降级分支 | TODO |
| 37 | `services.mcp.network` | `deeptutor/services/mcp/network.py` | 121 | 5 | 52 | 高 | 「Network guards for remote MCP servers (SSRF」覆盖 validate_mcp_url/validate_mcp_url_async 契约与边界＋异常/降级分支 | TODO⚠ |
| 38 | `runtime.providers.authorize` | `deeptutor/runtime/providers/authorize.py` | 59 | 2 | 51 | 高 | 「Per-kind authorisation for」覆盖 authorize_mcp_tools 契约与边界＋启动/装配失败路径 | TODO |
| 39 | `api.routers.partner_groups` | `deeptutor/api/routers/partner_groups.py` | 534 | 1 | 50 | 高 | 「CRUD and live discussion API for」覆盖 CreatePartnerGroupRequest/UpdatePartnerGroupRequest/PartnerGroupMessageRequest/PartnerInvocationActionRequest 契约与边界＋失败/4xx 分支 | DONE(AGEN-763) |
| 40 | `services.parsing.engines._install` | `deeptutor/services/parsing/engines/_install.py` | 287 | 3 | 50 | 中 | 「One-click background jobs for optional」覆盖 installable_engines/model_downloadable_engines/resolve_model_downloader/BackgroundJobManager 契约与边界＋异常/降级分支 | DONE(AGEN-915) |
| 41 | `services.llm.provider_core.codebuddy_http_provider` | `deeptutor/services/llm/provider_core/codebuddy_http_provider.py` | 258 | 3 | 50 | 中 | 「CodeBuddy provider that talks to the cloud」覆盖 normalize_api_key/CodeBuddyHTTPProvider/codebuddy_http_available/sdk_installed 契约与边界＋超时/限流/畸形响应分支 | TODO |
| 42 | `api.routers.space_mcp` | `deeptutor/api/routers/space_mcp.py` | 460 | 1 | 49 | 高 | 「Per-user MCP API」覆盖 ServerPayload/InstallPayload/list_servers/upsert_server 契约与边界＋失败/4xx 分支 | DONE(AGEN-780) |
| 43 | `services.rag.eval.matching` | `deeptutor/services/rag/eval/matching.py` | 218 | 3 | 49 | 中 | 「Gold-passage matching for retrieval」覆盖 normalize_text/tokenize/source_text/MatchPolicy 契约与边界＋异常/降级分支 | DONE(AGEN-912) |
| 44 | `services.parsing.engines.tika.formats` | `deeptutor/services/parsing/engines/tika/formats.py` | 217 | 3 | 49 | 中 | 「Apache Tika 4 input-format routing hints.」覆盖 tika_version_is_current 契约与边界＋异常/降级分支 | TODO |
| 45 | `services.llm.error_mapping` | `deeptutor/services/llm/error_mapping.py` | 175 | 3 | 48 | 中 | 「Error Mapping - Map provider-specific」覆盖 MappingRule/parse_retry_after_seconds/retry_after_seconds/map_error 契约与边界＋超时/限流/畸形响应分支 | DONE(AGEN-1036) |
| 46 | `learning.event_hub` | `deeptutor/learning/event_hub.py` | 140 | 3 | 47 | 中 | 「Low-latency wake-up channel for durable」覆盖 TopicSignal/TopicSubscription/MasteryTopicEventHub/publish_topic_signal 契约与边界＋异常/降级分支 | TODO |
| 47 | `services.parsing.engines.markitdown.formats` | `deeptutor/services/parsing/engines/markitdown/formats.py` | 102 | 3 | 47 | 中 | 「MarkItDown version and built-in」覆盖 markitdown_supported_formats/installed_markitdown_version/markitdown_version_is_current 契约与边界＋异常/降级分支 | TODO |
| 48 | `api.routers.skills` | `deeptutor/api/routers/skills.py` | 315 | 1 | 46 | 高 | 「Skills API Router」覆盖 get_skill_service/CreateSkillRequest/UpdateSkillRequest/InstallSkillRequest 契约与边界＋失败/4xx 分支 | TODO |
| 49 | `services.workspace.navigation` | `deeptutor/services/workspace/navigation.py` | 81 | 3 | 46 | 中 | 「Account navigation across content stores」覆盖 read_workspace_indexes/session_index 契约与边界＋异常/降级分支 | TODO |
| 50 | `multi_user.skill_access` | `deeptutor/multi_user/skill_access.py` | 74 | 3 | 46 | 中 | 「Skill visibility guards for non-admin users.」覆盖 assigned_skill_ids/assigned_skill_infos/assigned_skill_detail/assert_skill_allowed 契约与边界＋异常/降级分支 | TODO |
| 51 | `tools.mastery_nav` | `deeptutor/tools/mastery_nav.py` | 500 | 2 | 45 | 中 | 「Navigating the learner's mastery topics」覆盖 MasteryTopicsTool/MasterySessionsTool/MasteryOpenSessionTool/MasteryNewSessionTool 契约与边界＋异常/降级分支 | DONE(AGEN-973) |
| 52 | `api.routers.subagents` | `deeptutor/api/routers/subagents.py` | 288 | 1 | 45 | 高 | 「Subagent connections API.」覆盖 ConnectSubagentRequest/SubagentSettingsPayload/SubagentMessageRequest/detect_subagents 契约与边界＋失败/4xx 分支 | TODO |
| 53 | `multi_user.learner_profile` | `deeptutor/multi_user/learner_profile.py` | 49 | 3 | 45 | 中 | 「Validated, account-scoped learner profile」覆盖 normalize_profile/prompt_block 契约与边界＋异常/降级分支 | TODO |
| 54 | `services.rag.pipelines.modes` | `deeptutor/services/rag/pipelines/modes.py` | 48 | 3 | 45 | 中 | 「Shared retrieval-mode resolution for」覆盖 resolve_kb_mode 契约与边界＋异常/降级分支 | TODO |
| 55 | `api.utils.http_headers` | `deeptutor/api/utils/http_headers.py` | 27 | 3 | 45 | 中 | 「Shared HTTP header builders.」覆盖 content_disposition 契约与边界＋异常/降级分支 | TODO |
| 56 | `capabilities.audio_overview.request_config` | `deeptutor/capabilities/audio_overview/request_config.py` | 18 | 3 | 45 | 中 | 「Validated request config for the KB audio」覆盖 AudioOverviewRequestConfig 契约与边界＋异常/降级分支 | TODO |
| 57 | `services.voice.adapters.openai_compat` | `deeptutor/services/voice/adapters/openai_compat.py` | 477 | 2 | 44 | 中 | 「OpenAI-compatible HTTP adapters for TTS and」覆盖 OpenAICompatTTSAdapter/OpenRouterTTSAdapter/OpenAICompatSTTAdapter 契约与边界＋超时/限流/畸形响应分支 | DONE(AGEN-1056) |
| 58 | `runtime.background_leader` | `deeptutor/runtime/background_leader.py` | 227 | 1 | 44 | 高 | 「Lease-controlled singleton ownership of」覆盖 BackgroundLeaderSupervisor 契约与边界＋启动/装配失败路径 | DONE(AGEN-863) |
| 59 | `api.routers.space_cli_apps` | `deeptutor/api/routers/space_cli_apps.py` | 222 | 1 | 44 | 高 | 「CLI apps API」覆盖 EnabledPayload/list_apps/set_enabled/get_catalog 契约与边界＋失败/4xx 分支 | DONE(AGEN-833) |
| 60 | `events.event_bus` | `deeptutor/events/event_bus.py` | 205 | 4 | 44 | 中 | 「Event Bus」覆盖 EventType/Event/EventBus/get_event_bus 契约与边界＋异常/降级分支 | TODO |
| 61 | `api.routers.file_preview` | `deeptutor/api/routers/file_preview.py` | 205 | 1 | 44 | 高 | 「Authenticated, same-origin Office document」覆盖 preview_office_source/preview_office_upload 契约与边界＋失败/4xx 分支 | DONE(AGEN-764) |
| 62 | `services.memory.consolidator.runs` | `deeptutor/services/memory/consolidator/runs.py` | 405 | 2 | 43 | 中 | 「Persistent, cancellable consolidator runs.」覆盖 RunEvent/UndoCheckpoint/Run/RunBusyError 契约与边界＋异常/降级分支 | TODO |
| 63 | `runtime.agentic.tool_arg_guard` | `deeptutor/runtime/agentic/tool_arg_guard.py` | 195 | 1 | 43 | 高 | 「Pre-dispatch validation of model-authored」覆盖 RequiredArg/required_args/unsatisfied_required_args/missing_required_args 契约与边界＋启动/装配失败路径 | TODO |
| 64 | `api.routers.file_library` | `deeptutor/api/routers/file_library.py` | 169 | 1 | 43 | 高 | 「HTTP endpoints for the Persistent File」覆盖 list_library_files/add_library_file/search_library_files/get_library_file 契约与边界＋失败/4xx 分支 | TODO |
| 65 | `api.routers.personas` | `deeptutor/api/routers/personas.py` | 154 | 1 | 43 | 高 | 「Personas API Router」覆盖 CreatePersonaRequest/UpdatePersonaRequest/list_personas/get_persona 契约与边界＋失败/4xx 分支 | TODO |
| 66 | `api.utils.task_log_stream` | `deeptutor/api/utils/task_log_stream.py` | 362 | 2 | 42 | 中 | 覆盖 KnowledgeTaskStreamManager/capture_task_logs/get_task_stream_manager 契约与边界＋异常/降级分支 | TODO |
| 67 | `video_learning.invidious_account` | `deeptutor/video_learning/invidious_account.py` | 360 | 2 | 42 | 中 | 「Secure per-owner Invidious account」覆盖 invidious_redirect_uri/begin_invidious_account_authorization/complete_invidious_account_authorization/invidious_account_status 契约与边界＋异常/降级分支 | DONE(AGEN-806) |
| 68 | `api.routers.imports` | `deeptutor/api/routers/imports.py` | 146 | 1 | 42 | 高 | 「Import chat histories from ChatGPT exports」覆盖 ImportedMessage/ImportedSession/ChatHistoryImportRequest/import_chat_history 契约与边界＋失败/4xx 分支 | TODO |
| 69 | `api.routers.visualizers` | `deeptutor/api/routers/visualizers.py` | 144 | 1 | 42 | 高 | 「Per-user visualizer catalog, lifecycle and」覆盖 list_visualizers/install_bundled/enable_visualizer/disable_visualizer 契约与边界＋失败/4xx 分支 | TODO |
| 70 | `api.routers.mcp_settings` | `deeptutor/api/routers/mcp_settings.py` | 133 | 1 | 42 | 高 | 「MCP Settings API Router」覆盖 MCPSettingsPayload/get_mcp_settings/update_mcp_settings/upsert_mcp_server 契约与边界＋失败/4xx 分支 | DONE(AGEN-832) |
| 71 | `reading._grounding` | `deeptutor/reading/_grounding.py` | 115 | 4 | 42 | 中 | 「Shared text-window helpers for」覆盖 normalized_with_map/selection_range/evidence_key/grounding_context 契约与边界＋异常/降级分支 | TODO |
| 72 | `services.config.lightrag_roles` | `deeptutor/services/config/lightrag_roles.py` | 111 | 4 | 42 | 中 | 「Credential-free configuration contracts for」覆盖 LightRagModelSelection/LightRagRoleModel/LightRagVisionModel/LightRagRoleModels 契约与边界＋异常/降级分支 | TODO |
| 73 | `services.subagent.deepseek_harness` | `deeptutor/services/subagent/deepseek_harness.py` | 347 | 2 | 41 | 中 | 「DeepSeek Harness backend with SDK streaming」覆盖 DeepSeekHarnessBackend 契约与边界＋异常/降级分支 | DONE(AGEN-1143) |
| 74 | `services.subagent.antigravity` | `deeptutor/services/subagent/antigravity.py` | 313 | 2 | 41 | 中 | 「Antigravity CLI backend — drive the local」覆盖 AntigravityBackend 契约与边界＋异常/降级分支 | TODO |
| 75 | `runtime.coordination.journal` | `deeptutor/runtime/coordination/journal.py` | 97 | 1 | 41 | 高 | 「Canonical live-event publication, batching」覆盖 TurnEventJournal 契约与边界＋启动/装配失败路径 | TODO |
| 76 | `runtime.capability_routing` | `deeptutor/runtime/capability_routing.py` | 88 | 1 | 41 | 高 | 「Pre-execution capability routing for」覆盖 CapabilityRoute/route_explicit_quiz_request 契约与边界＋启动/装配失败路径 | TODO |
| 77 | `api.routers.attachments` | `deeptutor/api/routers/attachments.py` | 79 | 1 | 41 | 高 | 「HTTP endpoint for chat attachment downloads」覆盖 get_attachment 契约与边界＋失败/4xx 分支 | TODO |
| 78 | `services.rag.pipelines.llamaindex.vector_store` | `deeptutor/services/rag/pipelines/llamaindex/vector_store.py` | 288 | 2 | 40 | 中 | 「Vector-store backend selection for the」覆盖 faiss_available/faiss_write_index/faiss_read_index/new_faiss_storage_context 契约与边界＋异常/降级分支 | TODO |
| 79 | `services.rag.pipelines.lightrag.block_policy` | `deeptutor/services/rag/pipelines/lightrag/block_policy.py` | 266 | 2 | 40 | 中 | 「Versioned MinerU block policy for LightRAG」覆盖 BlockPolicyDecision/prepare_content_list/write_decision_ledger/write_attempt_ledger 契约与边界＋异常/降级分支 | TODO |
| 80 | `api.routers.task_board` | `deeptutor/api/routers/task_board.py` | 28 | 1 | 40 | 高 | 「Authenticated task board endpoints using」覆盖 get_board/create_card/update_card 契约与边界＋失败/4xx 分支 | TODO⚠ |
| 81 | `services.rag.eval.dataset` | `deeptutor/services/rag/eval/dataset.py` | 244 | 2 | 39 | 中 | 「QA-set schema for knowledge-base retrieval」覆盖 EvalDatasetError/EvalCase/EvalDataset/load_dataset 契约与边界＋异常/降级分支 | DONE(AGEN-912) |
| 82 | `services.rag.linked_kb` | `deeptutor/services/rag/linked_kb.py` | 237 | 2 | 39 | 中 | 「Probe an external folder before mounting it」覆盖 EmbeddingCompat/ProbeResult/provider_is_linkable/allowed_link_roots 契约与边界＋异常/降级分支 | TODO |
| 83 | `services.memory.consolidator.modes.dedup` | `deeptutor/services/memory/consolidator/modes/dedup.py` | 228 | 2 | 39 | 中 | 「Dedup mode — iterative line-level merge /」覆盖 DedupResult/run_dedup 契约与边界＋异常/降级分支 | TODO |
| 84 | `partners.channels.weixin_qr` | `deeptutor/partners/channels/weixin_qr.py` | 202 | 2 | 39 | 中 | 「The personal-WeChat QR login exchange, with」覆盖 QrCode/QrOutcome/qr_headers/normalize_host 契约与边界＋超时/限流/畸形响应分支 | TODO |
| 85 | `multi_user.book_access` | `deeptutor/multi_user/book_access.py` | 200 | 2 | 39 | 中 | 「One access resolver for personal and」覆盖 ResolvedBook/can_create_book/resolve_book/accessible_books 契约与边界＋异常/降级分支 | DONE(AGEN-828) |
| 86 | `services.memory.consolidator.meta` | `deeptutor/services/memory/consolidator/meta.py` | 194 | 2 | 38 | 中 | 「Per-doc consolidator metadata」覆盖 L2Meta/l2_meta_path/load_l2_meta/save_l2_meta 契约与边界＋异常/降级分支 | TODO |
| 87 | `services.subagent.hermes_remote_client` | `deeptutor/services/subagent/hermes_remote_client.py` | 180 | 2 | 38 | 中 | 「Small authenticated HTTP/SSE client for a」覆盖 HermesRemoteHTTPError/HermesRemoteProtocolError/HermesRemoteClient 契约与边界＋异常/降级分支 | TODO |
| 88 | `learning.topic_naming` | `deeptutor/learning/topic_naming.py` | 166 | 2 | 38 | 中 | 「Name a mastery goal from what the learner」覆盖 suggest_topic_name 契约与边界＋异常/降级分支 | DONE(AGEN-1135) |
| 89 | `services.workspace.session_move` | `deeptutor/services/workspace/session_move.py` | 138 | 2 | 37 | 中 | 「Move conversations with the same verified」覆盖 move_chat/migrate_legacy_bindings 契约与边界＋异常/降级分支 | TODO⚠ |
| 90 | `services.parsing.engines.docling.formats` | `deeptutor/services/parsing/engines/docling/formats.py` | 137 | 2 | 37 | 中 | 「Docling version and input-format」覆盖 docling_supported_formats/installed_docling_version/docling_version_is_current 契约与边界＋异常/降级分支 | TODO |
| 91 | `book.blocks.figure` | `deeptutor/book/blocks/figure.py` | 135 | 2 | 37 | 中 | 「Figure block – static visual figure (svg /」覆盖 FigureGenerator 契约与边界＋异常/降级分支 | TODO |
| 92 | `book.blocks.concept_graph` | `deeptutor/book/blocks/concept_graph.py` | 132 | 2 | 37 | 中 | 「Concept-graph block — deterministically」覆盖 render_mermaid/ConceptGraphGenerator 契约与边界＋异常/降级分支 | TODO |
| 93 | `services.memory.consolidator.chunker` | `deeptutor/services/memory/consolidator/chunker.py` | 131 | 2 | 37 | 中 | 「Character-based chunking with boundary」覆盖 ChunkSpan/chunk_with_boundary 契约与边界＋异常/降级分支 | TODO |
| 94 | `api.utils.tool_options` | `deeptutor/api/utils/tool_options.py` | 122 | 2 | 37 | 中 | 「Configurable-tool surface shared by the」覆盖 build_tool_options 契约与边界＋异常/降级分支 | TODO⚠ |
| 95 | `api.utils.task_id_manager` | `deeptutor/api/utils/task_id_manager.py` | 120 | 2 | 37 | 中 | 「Task ID Manager - Assigns unique IDs to」覆盖 TaskIDManager 契约与边界＋异常/降级分支 | TODO |
| 96 | `tools.reason` | `deeptutor/tools/reason.py` | 119 | 2 | 37 | 中 | 「Reason tool — stateless LLM deep-reasoning」覆盖 reason 契约与边界＋异常/降级分支 | DONE(AGEN-849) |
| 97 | `book.agents.ideation_agent` | `deeptutor/book/agents/ideation_agent.py` | 111 | 2 | 37 | 中 | 「IdeationAgent」覆盖 IdeationAgent 契约与边界＋异常/降级分支 | TODO |
| 98 | `capabilities.reading.media_notes` | `deeptutor/capabilities/reading/media_notes.py` | 92 | 2 | 36 | 中 | 「Render the embedded-image note that」覆盖 render_media_note 契约与边界＋异常/降级分支 | TODO |
| 99 | `learning.grading` | `deeptutor/learning/grading.py` | 64 | 2 | 36 | 中 | 「Deterministic answer grading + coarse error」覆盖 grade_answer/classify_error 契约与边界＋异常/降级分支 | DONE(AGEN-1035) |
| 100 | `services.parsing.engines.pymupdf4llm.formats` | `deeptutor/services/parsing/engines/pymupdf4llm/formats.py` | 60 | 2 | 36 | 中 | 「PyMuPDF4LLM version floor and」覆盖 installed_pymupdf4llm_version/pymupdf4llm_version_is_current 契约与边界＋异常/降级分支 | TODO |

## 已建卡索引（weak242 内全部 DONE）
- AGEN-1010: `services.generation_http`
- AGEN-1035: `learning.grading`
- AGEN-1036: `services.llm.error_mapping`
- AGEN-1050: `learning.assessment`
- AGEN-1051: `partners.channels.wecom`
- AGEN-1052: `services.search.consolidation`
- AGEN-1053: `agents.loop.context_budget`
- AGEN-1056: `services.voice.adapters.openai_compat`
- AGEN-1060: `api.run_server`
- AGEN-1086: `tools.media_gen_tool`
- AGEN-1133: `learning.objective_relations`
- AGEN-1135: `learning.topic_naming`
- AGEN-1141: `services.memory.consolidator.line_doc`
- AGEN-1142: `services.subagent.claude_code`
- AGEN-1143: `services.subagent.deepseek_harness`
- AGEN-1144: `services.workspace.dependencies`
- AGEN-1145: `tools.partner_memory`
- AGEN-1147: `api.contracts.turn_protocol`
- AGEN-736: `partners.channels.lark_http`
- AGEN-741: `partners.channels.msteams`
- AGEN-742: `partners.channels.napcat`
- AGEN-743: `partners.channels.matrix`
- AGEN-745: `services.reading_hints`
- AGEN-751: `co_writer.edit_agent`
- AGEN-763: `api.routers.partner_groups`
- AGEN-764: `api.routers.file_preview`
- AGEN-780: `api.routers.space_mcp`
- AGEN-782: `services.memory.consolidator.modes.audit`
- AGEN-787: `services.config.readiness`
- AGEN-790: `services.office_preview`
- AGEN-793: `learning.pending`
- AGEN-806: `video_learning.invidious_account`
- AGEN-807: `capabilities.obsidian.vault`
- AGEN-808: `services.partners.weixin_onboarding`
- AGEN-811: `services.rag.pipelines.lightrag.sidecar`
- AGEN-813: `services.skill.taxonomy`
- AGEN-824: `services.rag.provider_binding`
- AGEN-828: `multi_user.book_access`
- AGEN-831: `services.workspace.session_transfer`
- AGEN-832: `api.routers.mcp_settings`
- AGEN-833: `api.routers.space_cli_apps`
- AGEN-838: `api.routers.question_notebook`
- AGEN-845: `services.subagent.opencode_server`
- AGEN-847: `services.llm.local_provider`
- AGEN-849: `tools.reason`
- AGEN-863: `runtime.background_leader`
- AGEN-912: `services.rag.eval.matching`, `services.rag.eval.dataset`
- AGEN-913: `services.embedding.adapters.gemini`, `services.embedding.adapters.dashscope_native`
- AGEN-914: `services.doctor`
- AGEN-915: `services.parsing.engines._install`
- AGEN-916: `services.voice.adapters.volcengine`
- AGEN-947: `partners.channels.msteams`, `partners.channels.napcat`
- AGEN-966: `book.agents.page_planner`
- AGEN-972: `tools.question_bank`
- AGEN-973: `tools.mastery_nav`
- AGEN-974: `services.search.source_filter`
- AGEN-976: `services.workspace.kb_move`
- AGEN-977: `tools.vision.ggb_validator`
- AGEN-993: `services.chat_hints`

## 附注
- 焦点文本 = 模块 docstring 首行 + 顶层公开 def/class（≤4 个）自动生成，按 bonus 类别追加失败分支轴；拆卡时按需细化
- top100 中 ⚠ 漂移 9 个；计数：高 45 / 中 55 / 低 0
