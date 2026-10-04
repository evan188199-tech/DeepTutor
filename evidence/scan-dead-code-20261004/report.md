# 死代码与未使用导出扫描报告（AGEN-548）

- 扫描基线：`f07029cfc (origin/dev == origin/main, release v1.6.13)`（origin/dev 与 origin/main 同点）
- 方法：自建 AST 导入图交叉引用（Python，含相对导入/桶导出/PEP 562 lazy `__getattr__` 重导出链解析）+ TS/TSX import-export 图分析（含 barrel/`export *`/动态 import 解析）+ 全仓 token 交叉核对 + 抽样 rg 人工复核。
- 判定：**生产代码零引用** 才入选；仅测试/脚本引用、包 `__all__` 重导出、lazy barrel 重导出均保留为候选并单独标注。
- 排除的动态引用区（防误报）：pyproject `[project.scripts]`/`[project.entry-points]`；`deeptutor/partners/channels/*`（pkgutil.iter_modules 自动加载）；`markitdown/converters/*`（同上）；`Dockerfile.runner` COPY 的 `sandbox/runner/server.py`；字符串形式 `module:Attr` 引用（注册表/spec/lazy map，共 472 条）；TS 侧 Next.js App Router 约定文件（page/layout/route/...）。

## 总计

| 类别 | 数量 | 行数(估) |
|---|---|---|
| Python 未使用模块（含包内死簇） | 26 | 3733 |
| Python 模块级未引用符号 | 65 | 461 |
| Python 遗留兼容 shim 簇 | 5 | ~104 |
| TS 未使用文件 | 11 | 1191 |
| TS 未消费导出（named export） | 1188 | ~22078 |
| 不可达分支（`if False:`/`if (false)` 模式） | 0 | 0 |

## Top 10（按删除收益排序）

| # | 目标 | 类型 | 行数 | 依据 |
|---|---|---|---|---|
| 1 | `components/settings/ConnectionsEditor.tsx` | ts-file | 763 | 全仓零引用 |
| 2 | `features/knowledge/api/client.ts` | ts-export-group | 699 | 40 个未消费导出（其中 40 个测试/脚本也不引用），估 699 行 |
| 3 | `lib/learning-api.ts` | ts-export-group | 675 | 28 个未消费导出（其中 28 个测试/脚本也不引用），估 675 行 |
| 4 | `lib/notebook-api.ts` | ts-export-group | 454 | 12 个未消费导出（其中 12 个测试/脚本也不引用），估 454 行 |
| 5 | `lib/reading-api.ts` | ts-export-group | 447 | 15 个未消费导出（其中 14 个测试/脚本也不引用），估 447 行 |
| 6 | `deeptutor.tools.vision.coord_transform` | py-module | 436 | prod 引用 0；test 0 个文件导入 |
| 7 | `lib/knowledge-helpers.ts` | ts-export-group | 408 | 10 个未消费导出（其中 8 个测试/脚本也不引用），估 408 行 |
| 8 | `lib/mcp-api.ts` | ts-export-group | 348 | 8 个未消费导出（其中 4 个测试/脚本也不引用），估 348 行 |
| 9 | `lib/partners-api.ts` | ts-export-group | 345 | 13 个未消费导出（其中 13 个测试/脚本也不引用），估 345 行 |
| 10 | `deeptutor.tools.tex_chunker` | py-module | 341 | prod 引用 0；test 0 个文件导入 |

## A. Python 未使用模块（整文件候选）

生产代码（含 scripts、web）零导入。`textbook_struct`、`tools/vision`、`services/llm/{registry,telemetry,provider_registry}`、`agents/research/utils/{token_tracker,json_utils}` 为级联死簇（仅被同簇或包 `__init__` 重导出）。

| 模块 | 行数 | 残余引用 |
|---|---|---|
| `deeptutor.tools.vision.coord_transform` | 436 | — |
| `deeptutor.tools.tex_chunker` | 341 | — |
| `deeptutor.tools.file_tools` | 291 | test×1 |
| `deeptutor.agents.research.utils.token_tracker` | 281 | test×1 |
| `deeptutor.textbook_struct.chapter_rebuild` | 273 | test×1 |
| `deeptutor.tools.tex_downloader` | 256 | — |
| `deeptutor.tools.vision.block_parser` | 251 | — |
| `deeptutor.capabilities.registry` | 240 | test×4 |
| `deeptutor.tools.vision.image_utils` | 210 | — |
| `deeptutor.book.agents.spine_agent` | 189 | — |
| `deeptutor.reading.refresh` | 185 | script |
| `deeptutor.textbook_struct.page_headers` | 100 | test×1 |
| `deeptutor.agents.research.utils.json_utils` | 94 | test×1 |
| `deeptutor.utils.network.circuit_breaker` | 88 | test×1 |
| `deeptutor.logging.adapters.llamaindex` | 74 | — |
| `deeptutor.services.llm.registry` | 71 | — |
| `deeptutor.services.cli_apps.vendor.build_snapshot` | 65 | — |
| `deeptutor.core.errors` | 57 | test×1 |
| `deeptutor.services.llm.telemetry` | 46 | — |
| `deeptutor.tools.mastery_tool` | 45 | test×3 |
| `deeptutor.services.rag.pipelines.base` | 41 | — |
| `deeptutor.textbook_struct.column_blacklist` | 41 | — |
| `deeptutor.tools.solve_tool` | 22 | — |
| `deeptutor.textbook_struct` | 20 | test×1 |
| `deeptutor.logging.adapters` | 13 | — |
| `deeptutor.services.llm.provider_registry` | 3 | — |

## B. Python 模块级未引用符号

共 65 项，461 行。调用图依据：AST 导入图全仓解析后 0 个生产引用点；`name_elsewhere` 列为同名 token 出现的其他文件数（>0 需人工确认是否动态使用）。

| 符号 | 位置 | 行数 | 依据/风险 |
|---|---|---|---|
| `get_command_help` | `deeptutor/tools/vision/ggb_validator.py:383` | 29 | 包__all__重导出; 同名token×1文件 |
| `parse_action` | `deeptutor/services/memory/consolidator/parse.py:42` | 24 | 零引用 |
| `load_config_with_main_async` | `deeptutor/services/config/loader.py:129` | 20 | 零引用 |
| `latest_ts` | `deeptutor/services/memory/trace.py:135` | 19 | 零引用 |
| `safe_json_loads` | `deeptutor/utils/json_parser.py:184` | 18 | 仅测试(1); 包__all__重导出; 同名token×2文件 |
| `_make_user_record` | `deeptutor/services/auth.py:107` | 18 | 零引用 |
| `_filter_banned` | `deeptutor/services/memory/consolidator/guards.py:87` | 18 | 仅测试(1); 包__all__重导出; 同名token×1文件 |
| `initialize_environment` | `deeptutor/services/llm/config.py:177` | 14 | 仅测试(1) |
| `iter_by_ids` | `deeptutor/services/memory/trace.py:115` | 14 | 零引用 |
| `storage_dir_for_signature` | `deeptutor/services/rag/index_versioning.py:292` | 13 | 零引用 |
| `assert_skill_allowed` | `deeptutor/multi_user/skill_access.py:63` | 12 | 仅测试(1) |
| `missing_required_args` | `deeptutor/runtime/agentic/tool_arg_guard.py:139` | 12 | 仅测试(1) |
| `_PHASE1_TYPES` | `deeptutor/book/agents/page_planner.py:59` | 12 | 零引用 |
| `load_plugin_capability` | `deeptutor/plugins/loader.py:47` | 11 | 仅测试(1); 包__all__重导出; 同名token×2文件 |
| `_coerce_dict` | `deeptutor/services/llm/provider_core/openai_compat_provider.py:121` | 11 | 零引用 |
| `initialize_rag` | `deeptutor/tools/rag_tool.py:54` | 10 | 零引用 |
| `ToolEventSink` | `deeptutor/core/tool_protocol.py:173` | 9 | 零引用 |
| `test_allocate_bytes` | `deeptutor/runtime/worker_tasks.py:45` | 9 | 零引用 |
| `UISettings` | `deeptutor/api/routers/settings.py:174` | 9 | 零引用 |
| `check_container_data_volume` | `deeptutor/services/setup/data_volume.py:145` | 9 | 仅测试(1) |
| `_extract_persist_user_message` | `deeptutor/services/session/_turn_runtime_shared.py:1329` | 9 | 零引用 |
| `_extract_regenerate_flag` | `deeptutor/services/session/_turn_runtime_shared.py:1340` | 9 | 零引用 |
| `delete_rag` | `deeptutor/tools/rag_tool.py:66` | 8 | 零引用 |
| `ensure_dirs` | `deeptutor/services/memory/paths.py:97` | 8 | 仅测试(1); 同名token×1文件 |
| `_build_navigation_manifest` | `deeptutor/services/web_source/sync.py:238` | 8 | 仅测试(1) |
| `_parse_modules` | `deeptutor/capabilities/mastery/tools.py:2700` | 7 | 仅测试(1); 同名token×1文件 |
| `_PROTOCOL_ANSWER_NOW` | `deeptutor/agents/research/pipeline.py:210` | 7 | 零引用 |
| `_PROTOCOL_NOTE` | `deeptutor/agents/research/pipeline.py:220` | 7 | 零引用 |
| `_run_migrations` | `deeptutor/services/storage/file_library.py:69` | 7 | 零引用 |
| `read_version_meta` | `deeptutor/services/rag/index_versioning.py:258` | 6 | 零引用 |
| `prune_index_cache` | `deeptutor/services/rag/pipelines/llamaindex/storage.py:285` | 6 | 仅测试(1) |
| `_flat_to_tree` | `deeptutor/services/web_source/sync.py:248` | 6 | 仅测试(1) |
| `_next_step_payload` | `deeptutor/api/routers/mastery_path.py:380` | 5 | 零引用 |
| `resolve_runtime_skill` | `deeptutor/services/skill/runtime.py:78` | 5 | 零引用 |
| `_url_to_filename` | `deeptutor/services/web_source/sync.py:49` | 5 | 零引用 |
| `get_enabled_optional_tools` | `deeptutor/api/routers/settings.py:117` | 4 | 仅测试(2); 同名token×4文件 |
| `RemoveRecordRequest` | `deeptutor/api/routers/notebook.py:86` | 4 | 零引用 |
| `replace_ui_settings` | `deeptutor/services/settings/interface_settings.py:287` | 4 | 零引用 |
| `clear_index_cache` | `deeptutor/services/rag/pipelines/llamaindex/storage.py:279` | 4 | 仅测试(3) |
| `get_stats` | `deeptutor/co_writer/edit_agent.py:397` | 3 | 同名token×1文件 |
| `reset_stats` | `deeptutor/co_writer/edit_agent.py:402` | 3 | 同名token×1文件 |
| `_clear_store_cache` | `deeptutor/capabilities/marginnote4/tools.py:53` | 3 | 仅测试(1) |
| `reset_session_handoff_store_for_tests` | `deeptutor/multi_user/session_handoff.py:474` | 3 | 零引用 |
| `discover_plugins` | `deeptutor/plugins/loader.py:42` | 3 | 仅测试(1); 包__all__重导出; 同名token×3文件 |
| `agentic_client_pool_size` | `deeptutor/runtime/agentic/client.py:297` | 3 | 仅测试(1) |
| `timestamp` | `deeptutor/partners/helpers.py:27` | 3 | 同名token×95文件 |
| `reset_attachment_store` | `deeptutor/services/storage/attachment_store.py:323` | 3 | 仅测试(2) |
| `reset_channel_onboarding_manager_for_tests` | `deeptutor/services/partners/channel_onboarding.py:550` | 3 | 零引用 |
| `print_path_result` | `deeptutor_cli/common.py:899` | 2 | 零引用 |
| `ensure_user_workspace` | `deeptutor/multi_user/paths.py:109` | 2 | 零引用 |
| `public_grant` | `deeptutor/multi_user/grants.py:387` | 2 | 零引用 |
| `dumps_json` | `deeptutor/app/facade.py:280` | 2 | 零引用 |
| `is_cli` | `deeptutor/runtime/mode.py:42` | 2 | 包__all__重导出; 同名token×1文件 |
| `get_global_log_level` | `deeptutor/logging/config.py:48` | 2 | 包__all__重导出; 同名token×1文件 |
| `_identity` | `deeptutor/services/settings/registry_edit.py:13` | 2 | 零引用 |
| `MAX_BOOK_CHARS` | `deeptutor/learning/topic_materials.py:44` | 1 | 零引用 |
| `_TYPES_WITH_OPTIONS` | `deeptutor/agents/question/pipeline.py:169` | 1 | 零引用 |
| `_PHASE1_SUBSTITUTES` | `deeptutor/book/agents/page_planner.py:158` | 1 | 零引用 |
| `PROJECT_ROOT` | `deeptutor/services/llm/config.py:63` | 1 | 包__all__重导出; 同名token×20文件 |
| `_ULID_LEN` | `deeptutor/services/memory/ids.py:21` | 1 | 零引用 |
| `SUPPORTED_SURFACES` | `deeptutor/services/memory/snapshot/adapters.py:622` | 1 | 零引用 |
| `CODEX_UPSTREAM_COMMIT` | `deeptutor/services/codex_auth/constants.py:3` | 1 | 零引用 |
| `WEB_SYNC_INTERVAL_HOURS` | `deeptutor/services/web_source/sync.py:25` | 1 | 同名token×1文件 |
| `_HASH_PREFIX` | `deeptutor/services/parsing/cache.py:34` | 1 | 零引用 |
| `_INTERRUPTED_TURN_ERROR` | `deeptutor/services/session/_turn_runtime_shared.py:334` | 1 | 零引用 |

## C. 遗留兼容 shim / 弃用转发

| 目标 | 行数 | 依据 | 风险 |
|---|---|---|---|
| `deeptutor/tools/mastery_tool.py` | 47 | docstring: 'Compatibility exports ... keeps the historical import path stable'; prod refs: 0 (rg 'tools.mastery_tool' -> only deeptutor/learning/tests/*) | 外部用户/插件可能按旧路径导入；删除需同步改 3 个测试文件 |
| `deeptutor/tools/solve_tool.py` | 26 | docstring: 'Compatibility exports for solve loop-plugin tools'; prod refs: 0 | 同上，外部用户风险 |
| `deeptutor/services/llm/provider_registry.py` | 1 | 'Compatibility re-export for the shared provider registry' -> star-import deeptutor.services.provider_registry; prod refs: 0 | 对外公开包路径 |
| `deeptutor/services/llm/cloud_provider.py::complete/stream/_warn_deprecated` | 30 | DeprecationWarning 前转 factory.complete/stream；rg 全仓无调用方（tests 只用 fetch_models） | 文档声明供 out-of-tree callers；属公开 API |
| `deeptutor/services/llm/local_provider.py（deprecat 标记）` | 0 | 同 cloud_provider 模式 | 同上 |

## D. TS 未使用文件

| 文件 | 行数 | 引用 |
|---|---|---|
| `web/components/settings/ConnectionsEditor.tsx` | 763 | 零引用 |
| `web/components/workspaces/WorkspaceChatGroups.tsx` | 232 | test |
| `web/components/settings/TaskModelsEditor.tsx` | 101 | 零引用 |
| `web/components/workspaces/WorkspaceSwitcher.tsx` | 70 | 零引用 |
| `web/lib/route-params.ts` | 9 | test |
| `web/i18n/index.ts` | 5 | 零引用 |
| `web/features/chat/components/turn/index.ts` | 3 | test |
| `web/features/knowledge/components/engines/GraphRagForm.tsx` | 2 | 零引用 |
| `web/features/knowledge/components/engines/ImaForm.tsx` | 2 | 零引用 |
| `web/features/knowledge/components/engines/LightRagForm.tsx` | 2 | 零引用 |
| `web/features/knowledge/components/engines/LlamaIndexForm.tsx` | 2 | 零引用 |

## E. TS 未消费导出（按文件分组）

共 1188 个导出符号（named export/类型），估 ~22078 行。完整逐项清单见 `ts_unused_exports.json`（含行号与引用分类）。

| 文件 | 未消费导出数 | 估行数 |
|---|---|---|
| `web/features/knowledge/api/client.ts` | 40 | ~699 |
| `web/lib/learning-api.ts` | 28 | ~675 |
| `web/lib/notebook-api.ts` | 12 | ~454 |
| `web/lib/reading-api.ts` | 15 | ~447 |
| `web/lib/knowledge-helpers.ts` | 10 | ~408 |
| `web/lib/mcp-api.ts` | 8 | ~348 |
| `web/lib/partners-api.ts` | 13 | ~345 |
| `web/features/settings/store/SettingsStore.tsx` | 8 | ~300 |
| `web/lib/memory-graph.ts` | 11 | ~290 |
| `web/lib/doc-attachments.ts` | 6 | ~231 |
| `web/features/chat/ChatStateAdapter.tsx` | 5 | ~220 |
| `web/lib/reading-quote-locator.ts` | 5 | ~220 |
| `web/lib/reading-workspace-api.ts` | 4 | ~214 |
| `web/lib/reading-citations.ts` | 6 | ~204 |
| `web/lib/skills-api.ts` | 7 | ~199 |
| `web/lib/book-types.ts` | 7 | ~195 |
| `web/lib/session-api.ts` | 5 | ~181 |
| `web/lib/codex-oauth.ts` | 3 | ~180 |
| `web/hooks/useMasteryPathActivity.ts` | 7 | ~172 |
| `web/features/settings/navigation/settings-nav.ts` | 5 | ~171 |
| `web/context/QuizFollowupContext.tsx` | 6 | ~167 |
| `web/lib/visualize-types.ts` | 8 | ~166 |
| `web/features/capabilities/presentation.tsx` | 5 | ~163 |
| `web/components/settings/shared.tsx` | 4 | ~155 |
| `web/lib/reading-w3c-annotations.ts` | 4 | ~149 |
| `web/features/capabilities/model.ts` | 5 | ~146 |
| `web/features/chat/trace/memory.ts` | 5 | ~145 |
| `web/lib/reading-selection.ts` | 4 | ~144 |
| `web/shared/storage/store.ts` | 5 | ~143 |
| `web/lib/mastery-ws.ts` | 8 | ~139 |
| `web/lib/subagents-api.ts` | 4 | ~139 |
| `web/lib/app-update.ts` | 3 | ~137 |
| `web/lib/video-learning-api.ts` | 4 | ~136 |
| `web/lib/settings-readiness.ts` | 6 | ~135 |
| `web/lib/reading-location-history.ts` | 4 | ~133 |
| `web/hooks/useTopicSourceLibrary.ts` | 4 | ~131 |
| `web/lib/cli-apps-api.ts` | 5 | ~131 |
| `web/lib/mastery-question.ts` | 3 | ~128 |
| `web/lib/book-progress.ts` | 4 | ~126 |
| `web/features/knowledge/components/engines/EngineDetail.tsx` | 4 | ~124 |
| `web/lib/reading-turn-state.ts` | 4 | ~124 |
| `web/lib/chat-markdown-note.ts` | 4 | ~121 |
| `web/lib/course-handoff.ts` | 2 | ~120 |
| `web/lib/failed-submissions.ts` | 2 | ~120 |
| `web/lib/mcp-store.ts` | 4 | ~120 |
| `web/lib/partner-groups-api.ts` | 2 | ~120 |
| `web/lib/quiz-types.ts` | 2 | ~120 |
| `web/lib/theme.ts` | 4 | ~119 |
| `web/shared/api/client.ts` | 3 | ~118 |
| `web/features/co-writer/model/editor-state.ts` | 8 | ~116 |
| `web/lib/selection-tutor.ts` | 4 | ~115 |
| `web/lib/video-learning-marks.ts` | 6 | ~114 |
| `web/lib/admin-api.ts` | 3 | ~107 |
| `web/lib/mastery-handoff.ts` | 2 | ~107 |
| `web/lib/learning-dashboard.ts` | 4 | ~102 |
| `web/lib/reading-passage-prompts.ts` | 3 | ~99 |
| `web/lib/courses-api.ts` | 3 | ~98 |
| `web/components/space/question-bank/useQuestionBank.ts` | 3 | ~97 |
| `web/lib/book-activity.ts` | 5 | ~97 |
| `web/lib/mcp-tool-groups.ts` | 4 | ~95 |
| `web/components/chat/home/AskUserOptions.tsx` | 5 | ~94 |
| `web/lib/message-branches.ts` | 2 | ~94 |
| `web/lib/trace-tools.ts` | 5 | ~94 |
| `web/components/common/code-block-themes.ts` | 2 | ~90 |
| `web/lib/model-settings.ts` | 4 | ~90 |
| `web/components/chat/home/ComposerInput.tsx` | 5 | ~89 |
| `web/lib/reading-display-preferences.ts` | 4 | ~89 |
| `web/components/notebook/useNotebookLibrary.ts` | 2 | ~88 |
| `web/lib/chat-export.ts` | 3 | ~87 |
| `web/components/memory/useMemoryRun.ts` | 4 | ~86 |
| `web/lib/quiz-judge.ts` | 3 | ~86 |
| `web/lib/code-languages.ts` | 2 | ~85 |
| `web/hooks/useSmoothStreamText.ts` | 2 | ~84 |
| `web/lib/sidebar-entries.ts` | 4 | ~84 |
| `web/lib/personas-api.ts` | 5 | ~83 |
| `web/components/reading/EpubDocumentView.tsx` | 2 | ~82 |
| `web/lib/provider-registry.ts` | 2 | ~82 |
| `web/lib/proxy-policy.ts` | 3 | ~82 |
| `web/lib/reading-outline.ts` | 4 | ~82 |
| `web/features/co-writer/storage/drafts.ts` | 7 | ~78 |
| `web/lib/sidebar-layout.ts` | 5 | ~78 |
| `web/lib/chat-import/attribution.ts` | 2 | ~77 |
| `web/lib/deep-research-report.ts` | 2 | ~77 |
| `web/lib/think-segments.ts` | 4 | ~77 |
| `web/lib/partner-session.ts` | 3 | ~76 |
| `web/lib/ima-connection.ts` | 2 | ~74 |
| `web/lib/reconnecting-websocket.ts` | 3 | ~73 |
| `web/lib/research-types.ts` | 2 | ~72 |
| `web/components/partners/schema-form.tsx` | 2 | ~71 |
| `web/hooks/useDragSort.ts` | 2 | ~70 |
| `web/lib/epub-page-turn.ts` | 3 | ~70 |
| `web/components/sidebar/nav-entries.ts` | 2 | ~69 |
| `web/hooks/useDevice.ts` | 3 | ~69 |
| `web/lib/book-ws-operation.ts` | 2 | ~69 |
| `web/features/chat/messages/usage-summary.ts` | 2 | ~67 |
| `web/lib/imports-api.ts` | 2 | ~67 |
| `web/hooks/useKnowledgeProgress.ts` | 2 | ~66 |
| `web/shared/ui/Button.tsx` | 4 | ~66 |
| `web/components/chat/home/ContextBudgetChip.tsx` | 3 | ~64 |
| `web/components/knowledge/LightRagRoleModelsEditor.tsx` | 3 | ~64 |
| `web/components/memory/MemorySection.tsx` | 3 | ~64 |
| `web/components/partners/FaceEditor.tsx` | 3 | ~64 |
| `web/lib/space-items.ts` | 2 | ~64 |
| `web/components/Geogebra.tsx` | 2 | ~62 |
| `web/components/chat/home/CapabilityConfigCard.tsx` | 2 | ~62 |
| `web/components/partners/group/mentions.ts` | 2 | ~62 |
| `web/components/settings/SubagentSettingsEditor.tsx` | 2 | ~62 |
| `web/lib/math-animator-types.ts` | 2 | ~62 |
| `web/lib/reading-reader-action.ts` | 2 | ~62 |
| `web/components/chat/home/ContextReferenceTree.tsx` | 1 | ~60 |
| `web/components/chat/home/SessionViewerPanel.tsx` | 1 | ~60 |
| `web/components/chat/preview/previewerFor.ts` | 1 | ~60 |
| `web/components/chat/preview/previewers/useTextSource.ts` | 1 | ~60 |
| `web/components/common/InlineFileCard.tsx` | 1 | ~60 |
| `web/components/courses/CourseScope.tsx` | 1 | ~60 |
| `web/components/knowledge/IndexingModelSelector.tsx` | 3 | ~60 |
| `web/components/mcp/surface.ts` | 1 | ~60 |
| `web/components/partners/group/useGroupSession.ts` | 1 | ~60 |
| `web/components/quiz/QuizConfigPanel.tsx` | 1 | ~60 |
| `web/components/reading/AnnotationLayer.tsx` | 1 | ~60 |
| `web/components/reading/AnnotationList.tsx` | 1 | ~60 |
| `web/components/reading/AnnotationPopover.tsx` | 1 | ~60 |
| `web/components/reading/PdfDocumentView.tsx` | 1 | ~60 |
| `web/components/reading/PdfPage.tsx` | 1 | ~60 |
| `web/components/reading/ReaderPane.tsx` | 1 | ~60 |
| `web/components/reading/TextUnitView.tsx` | 1 | ~60 |
| `web/components/reading/library/AddMaterialsDialog.tsx` | 1 | ~60 |
| `web/components/reading/workspace/MediaReadingStage.tsx` | 1 | ~60 |
| `web/components/reading/workspace/SourceNavigator.tsx` | 1 | ~60 |
| `web/components/reading/workspace/WorkspaceMenu.tsx` | 1 | ~60 |
| `web/components/reading/workspace/dialogs.tsx` | 1 | ~60 |
| `web/components/research/ResearchConfigPanel.tsx` | 1 | ~60 |
| `web/components/settings/ModelCards.tsx` | 1 | ~60 |
| `web/components/sidebar/SessionAvatar.tsx` | 1 | ~60 |
| `web/components/space/learning/route-draft.ts` | 1 | ~60 |
| `web/components/visualize/VisualizeConfigPanel.tsx` | 1 | ~60 |
| `web/components/watching/WatchingMarksPanel.tsx` | 1 | ~60 |
| `web/context/ReadingContext.tsx` | 1 | ~60 |
| `web/context/app-shell-storage.ts` | 1 | ~60 |
| `web/features/chat/trace/selectors.ts` | 1 | ~60 |
| `web/features/runtime-status/RuntimeHealthCard.tsx` | 1 | ~60 |
| `web/features/runtime-status/TurnCoordinationSettings.tsx` | 1 | ~60 |
| `web/features/settings/navigation/settings-pages.ts` | 1 | ~60 |
| `web/hooks/useAuthStatus.ts` | 1 | ~60 |
| `web/hooks/useVoiceRecorder.ts` | 1 | ~60 |
| `web/lib/attachment-limits.ts` | 1 | ~60 |
| `web/lib/auth.ts` | 1 | ~60 |
| `web/lib/book-api.ts` | 1 | ~60 |
| `web/lib/chat-idle-recovery.ts` | 1 | ~60 |
| `web/lib/latex.ts` | 1 | ~60 |
| `web/lib/markdown-display.ts` | 1 | ~60 |
| `web/lib/mastery-mode.ts` | 1 | ~60 |
| `web/lib/practice-api.ts` | 1 | ~60 |
| `web/lib/profile-api.ts` | 1 | ~60 |
| `web/lib/reading-inline-markdown.tsx` | 1 | ~60 |
| `web/lib/reasoning-effort.ts` | 1 | ~60 |
| `web/lib/session-activity.ts` | 1 | ~60 |
| `web/lib/session-archive.ts` | 1 | ~60 |
| `web/lib/streaming-upload-proxy.ts` | 1 | ~60 |
| `web/lib/workspace-drafts.ts` | 1 | ~60 |
| `web/lib/youtube-iframe-api.ts` | 1 | ~60 |
| `web/shared/auth/return-url.ts` | 1 | ~60 |
| `web/shared/ui/Dialog.tsx` | 1 | ~60 |
| `web/shared/ui/Field.tsx` | 1 | ~60 |
| `web/shared/ui/Tooltip.tsx` | 1 | ~60 |
| `web/context/GeogebraTabContext.tsx` | 1 | ~59 |
| `web/features/multi-user/types.ts` | 2 | ~57 |
| `web/lib/tool-availability.ts` | 2 | ~56 |
| `web/components/chat/preview/previewers/useBinarySource.ts` | 1 | ~55 |
| `web/features/chat/controllers/pending-attachments.ts` | 2 | ~55 |
| `web/lib/settings-extensions.ts` | 2 | ~54 |
| `web/lib/partner-chat-draft.ts` | 1 | ~53 |
| `web/hooks/use-card-submission.ts` | 2 | ~52 |
| `web/lib/message-content.ts` | 2 | ~51 |
| `web/shared/ui/IconButton.tsx` | 1 | ~51 |
| `web/shared/ui/InlineAlert.tsx` | 1 | ~51 |
| `web/features/settings/navigation/settings-scroll.ts` | 3 | ~50 |
| `web/app/(workspace)/learning/books/components/blocks/ConceptGraphBlock.tsx` | 3 | ~49 |
| `web/lib/backend-forward.ts` | 1 | ~49 |
| `web/lib/conversation-notebook-save.ts` | 1 | ~49 |
| `web/lib/pdfjs-loader.ts` | 2 | ~49 |
| `web/lib/reading-age-presentation.ts` | 1 | ~49 |
| `web/lib/quiz-question-type.ts` | 1 | ~48 |
| `web/lib/llm-options-state.ts` | 3 | ~47 |
| `web/components/access/RequireCapability.tsx` | 1 | ~46 |
| `web/shared/storage/schema.ts` | 2 | ~46 |
| `web/lib/model-catalog-types.ts` | 1 | ~45 |
| `web/lib/resource-reuse.ts` | 1 | ~45 |
| `web/lib/tool-event.ts` | 1 | ~45 |
| `web/app/(workspace)/learning/books/components/BookGenerationActivity.tsx` | 3 | ~43 |
| `web/shared/ui/EmptyState.tsx` | 1 | ~43 |
| `web/app/(workspace)/learning/books/components/PageReader.tsx` | 3 | ~42 |
| `web/components/common/PickerShell.tsx` | 3 | ~42 |
| `web/components/settings/codex-profile.ts` | 1 | ~42 |
| `web/features/co-writer/hooks/useSynchronizedScroll.ts` | 1 | ~42 |
| `web/lib/notifications.ts` | 1 | ~42 |
| `web/app/(workspace)/learning/books/components/BookChatPanel.tsx` | 3 | ~41 |
| `web/app/(workspace)/learning/books/components/BookHealthBanner.tsx` | 3 | ~41 |
| `web/lib/composer-keyboard.ts` | 2 | ~41 |
| `web/lib/latex-commands.ts` | 1 | ~39 |
| `web/lib/guardian-api.ts` | 2 | ~38 |
| `web/components/settings/search-providers.ts` | 1 | ~36 |
| `web/features/chat/components/turn/ProtocolMismatchNotice.tsx` | 1 | ~35 |
| `web/hooks/useContextBudget.ts` | 1 | ~35 |
| `web/shared/ui/StatusChip.tsx` | 1 | ~35 |
| `web/components/agents/agent-icons.tsx` | 2 | ~34 |
| `web/lib/tools-settings.ts` | 1 | ~34 |
| `web/lib/watching-citations.ts` | 1 | ~34 |
| `web/lib/watching-turn-state.ts` | 1 | ~34 |
| `web/lib/reading-media-citations.ts` | 1 | ~32 |
| `web/lib/chat-import/agent-store.ts` | 1 | ~31 |
| `web/lib/avatar.ts` | 1 | ~30 |
| `web/lib/capability-routes.ts` | 1 | ~30 |
| `web/lib/learning-records-api.ts` | 2 | ~30 |
| `web/app/(workspace)/learning/books/components/blocks/FigureBlock.tsx` | 3 | ~29 |
| `web/features/chat/controllers/useChatRouteSession.ts` | 2 | ~29 |
| `web/lib/book-references.ts` | 1 | ~28 |
| `web/lib/transcript-search.ts` | 1 | ~28 |
| `web/app/(workspace)/learning/books/components/BookCreator.tsx` | 3 | ~26 |
| `web/components/space/ScopePicker.tsx` | 3 | ~26 |
| `web/lib/session-load.ts` | 1 | ~26 |
| `web/app/(workspace)/learning/books/components/blocks/BlockRenderer.tsx` | 3 | ~25 |
| `web/lib/question-bank-answers.ts` | 1 | ~25 |
| `web/lib/knowledge-engine-group.ts` | 1 | ~24 |
| `web/lib/chat-launch-intent.ts` | 1 | ~23 |
| `web/lib/use-auto-sized-textarea.ts` | 1 | ~23 |
| `web/app/(workspace)/learning/books/components/blocks/AnimationBlock.tsx` | 3 | ~22 |
| `web/components/settings/WorkspaceShell.tsx` | 1 | ~22 |
| `web/components/space/SpaceDashboard.tsx` | 4 | ~22 |
| `web/features/chat/transport/socket.ts` | 1 | ~22 |
| `web/lib/kb-name.ts` | 2 | ~22 |
| `web/lib/graphrag-model-compatibility.ts` | 1 | ~21 |
| `web/app/(workspace)/learning/books/components/SpineEditor.tsx` | 3 | ~19 |
| `web/app/(workspace)/learning/books/components/blocks/UserNoteBlock.tsx` | 3 | ~19 |
| `web/app/(workspace)/learning/books/components/blocks/PlaceholderBlock.tsx` | 3 | ~18 |
| `web/app/(workspace)/learning/books/components/BookPausedBanner.tsx` | 3 | ~17 |
| `web/app/(workspace)/learning/books/components/blocks/BlockBodyEditor.tsx` | 3 | ~17 |
| `web/app/(workspace)/learning/books/components/BookSidebar.tsx` | 3 | ~16 |
| `web/app/(workspace)/learning/books/components/blocks/SectionBlock.tsx` | 3 | ~16 |
| `web/app/(workspace)/learning/books/components/BookLibrary.tsx` | 3 | ~15 |
| `web/components/mcp/KeyValueEditor.tsx` | 3 | ~15 |
| `web/components/memory/MemoryWorkbench.tsx` | 3 | ~15 |
| `web/shared/storage/keys.ts` | 2 | ~15 |
| `web/app/(workspace)/learning/books/components/PageOutlineNav.tsx` | 3 | ~13 |
| `web/app/(workspace)/learning/books/components/blocks/QuizBlock.tsx` | 3 | ~13 |
| `web/lib/settings-presets.ts` | 1 | ~13 |
| `web/features/capabilities/useCapabilityCatalog.ts` | 1 | ~12 |
| `web/app/(workspace)/learning/books/components/blocks/DeepDiveBlock.tsx` | 3 | ~11 |
| `web/lib/reading-video-sources.ts` | 1 | ~11 |
| `web/components/space/ChatHistorySection.tsx` | 3 | ~10 |
| `web/components/memory/MemoryL1Workbench.tsx` | 3 | ~9 |
| `web/app/(workspace)/learning/books/components/blocks/CalloutBlock.tsx` | 3 | ~8 |
| `web/app/(workspace)/learning/books/components/blocks/CodeBlock.tsx` | 3 | ~8 |
| `web/app/(workspace)/learning/books/components/blocks/FlashCardsBlock.tsx` | 3 | ~8 |
| `web/app/(workspace)/learning/books/components/blocks/InteractiveBlock.tsx` | 3 | ~8 |
| `web/app/(workspace)/learning/books/components/blocks/TimelineBlock.tsx` | 3 | ~8 |
| `web/features/co-writer/components/CoWriterWorkspace.tsx` | 3 | ~8 |
| `web/lib/datetime.ts` | 1 | ~8 |
| `web/lib/co-writer-events.ts` | 1 | ~7 |
| `web/app/(utility)/notebooks/NotebooksRoute.tsx` | 2 | ~4 |
| `web/app/(workspace)/learning/books/BooksRoute.tsx` | 2 | ~4 |
| `web/app/(workspace)/learning/books/components/LearningCapturePanel.tsx` | 2 | ~4 |
| `web/components/SessionList.tsx` | 2 | ~4 |
| `web/components/ThemeScript.tsx` | 2 | ~4 |
| `web/components/access/CapabilityGate.tsx` | 2 | ~4 |
| `web/components/agents/AgentsHub.tsx` | 2 | ~4 |
| `web/components/agents/ConnectedAgents.tsx` | 2 | ~4 |
| `web/components/chat/BookReferencePicker.tsx` | 2 | ~4 |
| `web/components/chat/HistorySessionPicker.tsx` | 2 | ~4 |
| `web/components/chat/MemoryPicker.tsx` | 2 | ~4 |
| `web/components/chat/MyAgentsPicker.tsx` | 2 | ~4 |
| `web/components/chat/PersonaPicker.tsx` | 2 | ~4 |
| `web/components/chat/QuestionBankPicker.tsx` | 2 | ~4 |
| `web/components/chat/ReadingReferencePicker.tsx` | 2 | ~4 |
| `web/components/chat/home/AgentSelector.tsx` | 2 | ~4 |
| `web/components/chat/home/AttachmentProcessingStatus.tsx` | 2 | ~4 |
| `web/components/chat/home/ChatMarkdownNoteTab.tsx` | 2 | ~4 |
| `web/components/chat/home/ComposerResources.tsx` | 2 | ~4 |
| `web/components/chat/home/ConsultationTabBody.tsx` | 2 | ~4 |
| `web/components/chat/home/KnowledgeSelector.tsx` | 2 | ~4 |
| `web/components/chat/home/ModelSelector.tsx` | 2 | ~4 |
| `web/components/chat/home/PartnerGroupSelector.tsx` | 2 | ~4 |
| `web/components/chat/home/PartnerSelector.tsx` | 2 | ~4 |
| `web/components/chat/home/PersonaSelector.tsx` | 2 | ~4 |
| `web/components/chat/home/ResourceSelector.tsx` | 2 | ~4 |
| `web/components/chat/home/SelectedResources.tsx` | 2 | ~4 |
| `web/components/chat/home/SessionLoadingView.tsx` | 2 | ~4 |
| `web/components/chat/home/StarterSuggestions.tsx` | 2 | ~4 |
| `web/components/chat/home/SubagentRunTranscript.tsx` | 2 | ~4 |
| `web/components/chat/home/SubagentTabBody.tsx` | 2 | ~4 |
| `web/components/chat/home/ToolbarLabel.tsx` | 2 | ~4 |
| `web/components/chat/preview/FilePreviewDrawer.tsx` | 2 | ~4 |
| `web/components/chat/preview/previewers/DocxPreview.tsx` | 2 | ~4 |
| `web/components/chat/preview/previewers/FallbackPreview.tsx` | 2 | ~4 |
| `web/components/chat/preview/previewers/ImagePreview.tsx` | 2 | ~4 |
| `web/components/chat/preview/previewers/MarkdownPreview.tsx` | 2 | ~4 |
| `web/components/chat/preview/previewers/OfficePdfPreview.tsx` | 2 | ~4 |
| `web/components/chat/preview/previewers/OfficeTextPreview.tsx` | 2 | ~4 |
| `web/components/chat/preview/previewers/PdfPreview.tsx` | 2 | ~4 |
| `web/components/chat/preview/previewers/SvgPreview.tsx` | 2 | ~4 |
| `web/components/chat/preview/previewers/TextPreview.tsx` | 2 | ~4 |
| `web/components/chat/preview/previewers/XlsxPreview.tsx` | 2 | ~4 |
| `web/components/cli-apps/CliAppsSection.tsx` | 2 | ~4 |
| `web/components/common/BrandIcon.tsx` | 2 | ~4 |
| `web/components/common/GeogebraOpenCTA.tsx` | 2 | ~4 |
| `web/components/common/InlineMarkdown.tsx` | 2 | ~4 |
| `web/components/common/MarkdownRenderer.tsx` | 2 | ~4 |
| `web/components/common/McpToolGroups.tsx` | 2 | ~4 |
| `web/components/common/Modal.tsx` | 2 | ~4 |
| `web/components/common/ModelThinkingCard.tsx` | 2 | ~4 |
| `web/components/common/MotionProvider.tsx` | 2 | ~4 |
| `web/components/common/PickerHeader.tsx` | 2 | ~4 |
| `web/components/common/ProcessLogs.tsx` | 2 | ~4 |
| `web/components/common/ProviderIcon.tsx` | 2 | ~4 |
| `web/components/common/RichCodeBlock.tsx` | 2 | ~4 |
| `web/components/common/RichInlineMarkdown.tsx` | 2 | ~4 |
| `web/components/common/RichMarkdownRenderer.tsx` | 2 | ~4 |
| `web/components/common/SimpleMarkdownRenderer.tsx` | 2 | ~4 |
| `web/components/common/ToastViewport.tsx` | 2 | ~4 |
| `web/components/courses/CourseConventions.tsx` | 2 | ~4 |
| `web/components/courses/CourseDialog.tsx` | 2 | ~4 |
| `web/components/courses/CourseNextStep.tsx` | 2 | ~4 |
| `web/components/courses/CourseProgress.tsx` | 2 | ~4 |
| `web/components/courses/CourseResources.tsx` | 2 | ~4 |
| `web/components/courses/CourseSyllabus.tsx` | 2 | ~4 |
| `web/components/courses/CoursesShelf.tsx` | 2 | ~4 |
| `web/components/courses/OrganizedSessionList.tsx` | 2 | ~4 |
| `web/components/knowledge/ConnectKiwixModal.tsx` | 2 | ~4 |
| `web/components/knowledge/CreateKbModal.tsx` | 2 | ~4 |
| `web/components/knowledge/EmbeddingModelSelector.tsx` | 2 | ~4 |
| `web/components/knowledge/FileDropZone.tsx` | 2 | ~4 |
| `web/components/knowledge/ImaConnectionFields.tsx` | 2 | ~4 |
| `web/components/knowledge/KbDocumentList.tsx` | 2 | ~4 |
| `web/components/knowledge/KbDocumentsSection.tsx` | 2 | ~4 |
| `web/components/knowledge/KbFilePreview.tsx` | 2 | ~4 |
| `web/components/knowledge/KbFilesTab.tsx` | 2 | ~4 |
| `web/components/knowledge/KbGitHubSourcesSection.tsx` | 2 | ~4 |
| `web/components/knowledge/KbIndexFailureBanner.tsx` | 2 | ~4 |
| `web/components/knowledge/KbIndexVersionsSection.tsx` | 2 | ~4 |
| `web/components/knowledge/KbKiwixArticlesSection.tsx` | 2 | ~4 |
| `web/components/knowledge/KbLinkedFoldersSection.tsx` | 2 | ~4 |
| `web/components/knowledge/KbMarginNoteDevicesSection.tsx` | 2 | ~4 |
| `web/components/knowledge/KbSettingsSection.tsx` | 2 | ~4 |
| `web/components/knowledge/KbStatusBadge.tsx` | 2 | ~4 |
| `web/components/knowledge/KbTaskLogs.tsx` | 2 | ~4 |
| `web/components/knowledge/KbUpdateHistory.tsx` | 2 | ~4 |
| `web/components/knowledge/KbWebSourcesSection.tsx` | 2 | ~4 |
| `web/components/knowledge/KnowledgeBaseDetail.tsx` | 2 | ~4 |
| `web/components/knowledge/KnowledgeEngineIcon.tsx` | 2 | ~4 |
| `web/components/knowledge/KnowledgeHome.tsx` | 2 | ~4 |
| `web/components/knowledge/KnowledgePage.tsx` | 2 | ~4 |
| `web/components/knowledge/LightRagEmbeddingWarning.tsx` | 2 | ~4 |
| `web/components/knowledge/LightRagIndexingProvenance.tsx` | 2 | ~4 |
| `web/components/knowledge/LinkFolderModal.tsx` | 2 | ~4 |
| `web/components/knowledge/PageIndexSettingsModal.tsx` | 2 | ~4 |
| `web/components/layout/AppShell.tsx` | 2 | ~4 |
| `web/components/math-animator/MathAnimatorViewer.tsx` | 2 | ~4 |
| `web/components/mcp/McpAdminRegistry.tsx` | 2 | ~4 |
| `web/components/mcp/McpCatalogBrowser.tsx` | 2 | ~4 |
| `web/components/mcp/McpDeploymentList.tsx` | 2 | ~4 |
| `web/components/mcp/McpServerForm.tsx` | 2 | ~4 |
| `web/components/mcp/McpServerList.tsx` | 2 | ~4 |
| `web/components/mcp/McpServerRow.tsx` | 2 | ~4 |
| `web/components/mcp/McpStatusBadge.tsx` | 2 | ~4 |
| `web/components/mcp/McpToolList.tsx` | 2 | ~4 |
| `web/components/memory/MemoryArchivedBanner.tsx` | 2 | ~4 |
| `web/components/memory/MemoryGraph.tsx` | 2 | ~4 |
| `web/components/memory/MemoryHub.tsx` | 2 | ~4 |
| `web/components/memory/MemoryRunPanel.tsx` | 2 | ~4 |
| `web/components/notebook/NotebookConsole.tsx` | 2 | ~4 |
| `web/components/notebook/NotebookRecordActions.tsx` | 2 | ~4 |
| `web/components/notebook/NotebookRecordPicker.tsx` | 2 | ~4 |
| `web/components/notebook/NotebookRecordRow.tsx` | 2 | ~4 |
| `web/components/notebook/NotebookSelector.tsx` | 2 | ~4 |
| `web/components/notebook/SaveToNotebookModal.tsx` | 2 | ~4 |
| `web/components/partners/AssetPicker.tsx` | 2 | ~4 |
| `web/components/partners/ChannelIcon.tsx` | 2 | ~4 |
| `web/components/partners/ChannelOnboardingPanel.tsx` | 2 | ~4 |
| `web/components/partners/ChannelRuntimeStatus.tsx` | 2 | ~4 |
| `web/components/partners/PartnerArchives.tsx` | 2 | ~4 |
| `web/components/partners/PartnerAvatar.tsx` | 2 | ~4 |
| `web/components/partners/PartnerChannels.tsx` | 2 | ~4 |
| `web/components/partners/PartnerChat.tsx` | 2 | ~4 |
| `web/components/partners/PartnerConfigure.tsx` | 2 | ~4 |
| `web/components/partners/PartnerLinkModal.tsx` | 2 | ~4 |
| `web/components/partners/PartnerModelPicker.tsx` | 2 | ~4 |
| `web/components/partners/PartnerModelSelect.tsx` | 2 | ~4 |
| `web/components/partners/PartnerWorkspacePicker.tsx` | 2 | ~4 |
| `web/components/partners/SoulEditor.tsx` | 2 | ~4 |
| `web/components/partners/SoulPicker.tsx` | 2 | ~4 |
| `web/components/partners/ToolPicker.tsx` | 2 | ~4 |
| `web/components/partners/WeixinQrLogin.tsx` | 2 | ~4 |
| `web/components/partners/group/DiscussionModePicker.tsx` | 2 | ~4 |
| `web/components/partners/group/GroupComposer.tsx` | 2 | ~4 |
| `web/components/partners/group/GroupEmptyState.tsx` | 2 | ~4 |
| `web/components/partners/group/GroupRound.tsx` | 2 | ~4 |
| `web/components/partners/group/GroupSessionPicker.tsx` | 2 | ~4 |
| `web/components/partners/group/GroupSidePanel.tsx` | 2 | ~4 |
| `web/components/partners/group/InvocationCard.tsx` | 2 | ~4 |
| `web/components/partners/group/PartnerGroupChat.tsx` | 2 | ~4 |
| `web/components/partners/group/PartnerSeat.tsx` | 2 | ~4 |
| `web/components/partners/group/RoundSummaryAction.tsx` | 2 | ~4 |
| `web/components/quiz/QuizFollowupTabBody.tsx` | 2 | ~4 |
| `web/components/quiz/QuizViewer.tsx` | 2 | ~4 |
| `web/components/research/ResearchOutlineEditor.tsx` | 2 | ~4 |
| `web/components/settings/ChatResponseTimeoutSection.tsx` | 2 | ~4 |
| `web/components/settings/EmbeddingModelUsage.tsx` | 2 | ~4 |
| `web/components/settings/MemoryUsageItem.tsx` | 2 | ~4 |
| `web/components/settings/SettingsMain.tsx` | 2 | ~4 |
| `web/components/settings/SettingsNav.tsx` | 2 | ~4 |
| `web/components/settings/SettingsOverview.tsx` | 2 | ~4 |
| `web/components/settings/SettingsPageContent.tsx` | 2 | ~4 |
| `web/components/settings/SettingsPresetsPanel.tsx` | 2 | ~4 |
| `web/components/settings/SettingsReadinessPanel.tsx` | 2 | ~4 |
| `web/components/settings/SettingsReturnTracker.tsx` | 2 | ~4 |
| `web/components/settings/SettingsRuntimePage.tsx` | 2 | ~4 |
| `web/components/settings/SettingsStatusPanel.tsx` | 2 | ~4 |
| `web/components/sidebar/UtilitySidebar.tsx` | 2 | ~4 |
| `web/components/sidebar/WorkspaceSidebar.tsx` | 2 | ~4 |
| `web/components/space/ArchivedConversations.tsx` | 2 | ~4 |
| `web/components/space/EduHubImportModal.tsx` | 2 | ~4 |
| `web/components/space/ImportWizard.tsx` | 2 | ~4 |
| `web/components/space/McpStoreSection.tsx` | 2 | ~4 |
| `web/components/space/MyAgentsSection.tsx` | 2 | ~4 |
| `web/components/space/PersonasSection.tsx` | 2 | ~4 |
| `web/components/space/ScopeEditorModal.tsx` | 2 | ~4 |
| `web/components/space/SkillsSection.tsx` | 2 | ~4 |
| `web/components/space/SpaceMain.tsx` | 2 | ~4 |
| `web/components/space/SpaceSectionHeader.tsx` | 2 | ~4 |
| `web/components/space/question-bank/BankScopeRail.tsx` | 2 | ~4 |
| `web/components/space/question-bank/BankSelectionBar.tsx` | 2 | ~4 |
| `web/components/space/question-bank/BankToolbar.tsx` | 2 | ~4 |
| `web/components/space/question-bank/CategoryManager.tsx` | 2 | ~4 |
| `web/components/space/question-bank/CategoryMenu.tsx` | 2 | ~4 |
| `web/components/space/question-bank/QuestionBankSection.tsx` | 2 | ~4 |
| `web/components/space/question-bank/QuestionCard.tsx` | 2 | ~4 |
| `web/components/visualize/VisualizationViewer.tsx` | 2 | ~4 |
| `web/components/whisper/WhisperComposer.tsx` | 2 | ~4 |
| `web/components/whisper/WhisperMessageList.tsx` | 2 | ~4 |
| `web/components/whisper/WhisperRoomChip.tsx` | 2 | ~4 |
| `web/features/chat/components/ChatWorkspace.tsx` | 2 | ~4 |
| `web/features/chat/trace/ActivityOrb.tsx` | 2 | ~4 |
| `web/features/settings/components/UsageActivity.tsx` | 2 | ~4 |
| `web/features/settings/sections/AboutSettingsSection.tsx` | 2 | ~4 |
| `web/features/settings/sections/AppearanceSettingsSection.tsx` | 2 | ~4 |
| `web/features/settings/sections/ArchivedChatsSettingsSection.tsx` | 2 | ~4 |
| `web/features/settings/sections/AttachmentsSettingsSection.tsx` | 2 | ~4 |
| `web/features/settings/sections/CapabilitiesSettingsSection.tsx` | 2 | ~4 |
| `web/features/settings/sections/DataMigrationSettingsSection.tsx` | 2 | ~4 |
| `web/features/settings/sections/DocumentParsingSettingsSection.tsx` | 2 | ~4 |
| `web/features/settings/sections/GuardianSettingsSection.tsx` | 2 | ~4 |
| `web/features/settings/sections/LearnerProfileSettingsSection.tsx` | 2 | ~4 |
| `web/features/settings/sections/MemorySettingsSection.tsx` | 2 | ~4 |
| `web/features/settings/sections/NetworkSettingsSection.tsx` | 2 | ~4 |
| `web/features/settings/sections/StartersSettingsSection.tsx` | 2 | ~4 |
| `web/features/settings/sections/ToolsSettingsSection.tsx` | 2 | ~4 |
| `web/features/settings/sections/UsageSettingsSection.tsx` | 2 | ~4 |
| `web/features/settings/sections/VideoLearningSettingsSection.tsx` | 2 | ~4 |
| `web/features/settings/sections/WorkspaceSettingsSection.tsx` | 2 | ~4 |
| `web/features/settings/sections/models/ConnectionsSettingsSection.tsx` | 2 | ~4 |
| `web/features/settings/sections/models/EmbeddingSettingsSection.tsx` | 2 | ~4 |
| `web/features/settings/sections/models/ImageSettingsSection.tsx` | 2 | ~4 |
| `web/features/settings/sections/models/LlmSettingsSection.tsx` | 2 | ~4 |
| `web/features/settings/sections/models/MultimodalSettingsSection.tsx` | 2 | ~4 |
| `web/features/settings/sections/models/SearchSettingsSection.tsx` | 2 | ~4 |
| `web/features/settings/sections/models/SttSettingsSection.tsx` | 2 | ~4 |
| `web/features/settings/sections/models/TaskModelsSettingsSection.tsx` | 2 | ~4 |
| `web/features/settings/sections/models/TtsSettingsSection.tsx` | 2 | ~4 |
| `web/features/settings/sections/models/VideoSettingsSection.tsx` | 2 | ~4 |
| `web/features/settings/sections/models/VoiceSettingsSection.tsx` | 2 | ~4 |
| `web/lib/skill-slug.ts` | 2 | ~4 |
| `web/shared/api/errors.ts` | 1 | ~4 |
| `web/shared/ui/TooltipLayer.tsx` | 2 | ~4 |
| `web/components/chat/home/StandaloneComposer.tsx` | 1 | ~3 |
| `web/components/Mermaid.tsx` | 1 | ~2 |
| `web/components/chat/home/LazySessionViewerPanel.tsx` | 1 | ~2 |
| `web/components/chat/home/MasteryQuestionCard.tsx` | 1 | ~2 |
| `web/components/settings/TaskModelsWorkspace.tsx` | 1 | ~2 |
| `web/hooks/useKnowledgeBases.ts` | 1 | ~2 |
| `web/hooks/useKnowledgeHistory.ts` | 1 | ~2 |
| `web/lib/book-errors.ts` | 1 | ~2 |

## F. 不可达分支

模式搜索（`if False:`、`while False:`、`if (false)`、`&& false`）在两侧生产代码均无命中；未发现常量条件死分支。`TYPE_CHECKING`/`version_info` 守卫均属正常可选依赖回退，未列为死代码。

## G. 误报风险与动态引用区（拆卡时必读）

1. **字符串注册表**：`deeptutor` 内 472 条 `module:Attr`/模块路径字符串（BUILTIN_LOOP_CAPABILITY_SPECS、`_LAZY_CLASS_EXPORTS`、capability_registry、配置文件）已并入引用集；新增动态加载时需复查。
2. **PEP 562 lazy barrel**：`deeptutor/runtime/agentic/__init__.py`、`deeptutor/tools/__init__.py`、`deeptutor/tools/builtin/__init__.py`、`deeptutor/services/config/__init__.py` 等按名懒加载子模块——删除这些包内符号要同步清 lazy map 与 `__all__`。
3. **iter_modules 自动加载**：`deeptutor/partners/channels/*`、`deeptutor/services/parsing/engines/markitdown/converters/*` 整目录动态发现，本报告已整体排除。
4. **Docker 引用**：`Dockerfile.runner` 直接 COPY `sandbox/runner/server.py`，已排除。
5. **对外 API**：`deeptutor` 是 PyPI 包，`services/llm/cloud_provider.complete/stream`、`tools/mastery_tool`、`tools/solve_tool`、`services/llm/provider_registry` 明示服务 out-of-tree 调用方，删除属公开 API 破坏，需版本策略配合。
6. **仅测试引用**项删除时要同步删测试；`deeptutor/learning/tests/`（包内测试目录）中的引用已按测试归类。
7. TS 侧 `name_elsewhere`>0 的符号（同名 token 出现在其他文件）在 JSON 附录中可查，需人工区分注释/文档提及与真实动态使用。

## 复现

```
git fetch --multiple origin myfork
git worktree add -b agent/agen548-deadcode-scan <path> origin/dev   # f07029cfc
python3 analyze_py.py <wt>   # AST 交叉引用 + 模块可达性
python3 analyze_ts.py <wt>/web  # import/export 图
rg -w '<symbol>' — 逐项人工复核抽样
```
分析脚本未入库（临时目录），判定逻辑如上所述可重建。
