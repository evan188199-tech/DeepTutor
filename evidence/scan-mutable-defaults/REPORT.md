# 可变默认参数与共享可变缺省全库清点（scan-mutable-defaults）

- 基线: origin/main `6cf793bd8`（v1.6.14），2026-10-11；纯静态只读扫描，未改动任何代码
- 范围: 1899 个 `.py`（`deeptutor/`、`deeptutor_cli/`、`deeptutor_web/`、`tests/`、`scripts/`）；`web/` 为纯前端无 `.py`
- 去重边界: 与 fix-broadexcept-narrow-batch（except 轴）、scan-hardcode-paths（路径轴）无重叠；缓存失效细节归既有 scan/cache-invalidation 卡，本卡仅在涉及处标注

## 方法

- 轴 A（可变默认参数）: AST 遍历全部 FunctionDef/AsyncFunctionDef 的默认值，匹配 `[]` `{}` `set()` 及 `list()/dict()/set()` 空调用；另用 rg 正则独立交叉验证。
- 轴 B（模块级共享可变缺省）: AST 收集模块级 `X = []/{}/set()` 赋值；对每个名字回查就地修改证据（`append/extend/insert/remove/pop/clear/add/update/setdefault/sort/reverse/discard`、下标赋值、`del`、增量赋值）及"用作函数默认值"；跨文件修改全库回查。
- 原始数据: `module-mutables.json`（401 条候选的定义点、类型、修改 site 全量记录）；校验和见 `SHA256SUMS`。

## 轴 A: 可变默认参数 — 0 处

1899 个文件中未发现任何可变默认参数（AST 与 rg 双重确认，含 tests）。无需修复候选。

## 轴 B: 模块级共享可变缺省 — 清点

- 总定义 1076 处；其中 `__all__` 675 处为静态导出表，无就地修改，标注无风险。
- 有效候选 401 处，分类:
  - 函数内就地修改（真共享）: 56 处 → 高 0 / 中 4 / 低 52
  - 仅模块级（构建期）修改: 3 处 → 无风险
  - 用作函数默认值: 1 处（仅 tests）→ 无风险
  - 全库无就地修改证据: 342 处 → 无风险（多为只读配置表）

## 中风险（就地修改 + 跨请求共享 + 受保护但存在滞留/陈旧候选）— 4 处

| 定义点 | 名称(类型) | 就地修改证据 | 风险点 | 修复候选 |
|---|---|---|---|---|
| `deeptutor/services/mcp/oauth.py:323` | `_PENDING` (dict) | begin_authorization@364 写入；@394 pop；complete_authorization@410 pop | 用户放弃 consent 时 flow task 永挂 `flow.result`，条目无 reaper，跨请求滞留 | 对 `flow.result` 施加 FLOW_TIMEOUT_S 兜底或在清理路径统一 sweep |
| `deeptutor/services/pocketbase_client.py:38` | `_TOKEN_CACHE` (dict) | validate_pb_token@156 写入；@131 del | 无锁并发读写（GIL 下单操作原子，最坏重复网络调用）；过期条目仅同一 token 再校验时删除，废弃 token 永久驻留 | 加锁 + 周期性过期清扫 |
| `deeptutor/api/routers/partners.py:111` | `_start_locks` (dict) | _get_start_lock@122 item-assign | mutex 保护但条目永不回收，按 partner 单调增长 | 会话结束/partner 删除时回收条目 |
| `deeptutor/api/routers/partners.py:113` | `_draft_confirm_locks` (dict) | _get_draft_confirm_lock@132 item-assign | 同上，按 (user, draft) 单调增长 | 同上 |

## 高风险 — 0 处

未发现正确性级风险：所有跨请求共享均为显式单例注册表/锁表/带键控缓存/带锁缓存设计。

## 低风险（按设计共享：有键控、TTL、reset 或有界）— 52 处

每条均为进程级共享可变状态，就地修改证据见 site 列；"跨请求共享"成立但属设计意图。

| 定义点 | 名称(类型) | 就地修改证据 | 备注 |
|---|---|---|---|
| deeptutor/book/engine.py:2170 | `_engines` (Dict) | get_book_engine@2178 item-assign | 按设计共享，键控有界 |
| deeptutor/book/event_hub.py:42 | `_buses` (Dict) | get_book_bus@54 item-assign；close_book_bus@68 .pop() | get/close 成对 |
| deeptutor/book/storage.py:385 | `_storages` (Dict) | get_book_storage@391 item-assign | 按设计共享，键控有界 |
| deeptutor/capabilities/course_study/capability.py:54 | `_PROMPT_CACHE` (Dict) | _load_prompts@73 item-assign | 进程内缓存，miss 填充，按键有界 |
| deeptutor/capabilities/explore_context/capability.py:45 | `_PROMPT_CACHE` (Dict) | _load_prompts@64 item-assign | 进程内缓存，miss 填充，按键有界 |
| deeptutor/capabilities/marginnote4/tools.py:50 | `_STORE_CACHE` (Dict) | _store@46 item-assign；_clear_store_cache@55 .clear() | 有 _clear_store_cache |
| deeptutor/capabilities/reading/capability.py:73 | `_PROMPT_CACHE` (Dict) | _load_prompts@92 item-assign | 进程内缓存，miss 填充，按键有界 |
| deeptutor/co_writer/storage.py:235 | `_storages` (Dict) | get_co_writer_storage@241 item-assign | 按设计共享，键控有界 |
| deeptutor/learning/storage.py:51 | `_initialized_db_paths` (set) | _ensure_initialized@590 .add() | 按 db 路径有界；data_migration 有清理 seam |
| deeptutor/multi_user/grants.py:27 | `_GRANT_THREAD_LOCKS` (Dict) | _grant_write_lock@51 .setdefault() | 锁表，按资源数有界 |
| deeptutor/multi_user/paths.py:42 | `_path_services` (Dict) | get_path_service_for_scope@145 item-assign | 按设计共享，键控有界 |
| deeptutor/plugins/runtime.py:439 | `_IMPORTED_GENERATIONS` (Dict) | entry_point_can_load@498 item-assign | 注册表 API |
| deeptutor/runtime/memory_reclaim.py:13 | `_reclaim_tasks` (Dict) | schedule_memory_reclaim@62 item-assign；schedule_memory_reclaim@67 .pop() | 调度注册，完成即 pop |
| deeptutor/runtime/stream_bus.py:360 | `_bus_registry` (Dict) | register_bus@365 item-assign；unregister_bus@370 .pop() | register/unregister 成对 |
| deeptutor/services/cli_apps/installer.py:69 | `_locks` (Dict) | install_app@96 .setdefault()；uninstall_app@115 .setdefault() | 锁表，按资源数有界 |
| deeptutor/services/codex_auth/service.py:1167 | `_SERVICE_INSTANCES` (Dict) | get_codex_oauth_service@1296 item-assign | 进程级单例注册 |
| deeptutor/services/codex_auth/service.py:1168 | `_RELOCATED_SECRET_ROOTS` (set) | _codex_secrets_root@1209 .add() | 按设计共享，键控有界 |
| deeptutor/services/courses.py:237 | `_LOCKS` (Dict) | _lock_for@246 item-assign | 锁表，按资源数有界 |
| deeptutor/services/llm/capabilities.py:360 | `_CATALOG_OVERRIDES` (Dict) | set_catalog_capability_overrides@381 .clear()；set_catalog_capability_overrides@382 .update() | 显式 setter: clear+update |
| deeptutor/services/llm/capabilities.py:487 | `_RUNTIME_DISABLED_RESPONSE_FORMAT` (set) | disable_response_format_at_runtime@501 .add() | 显式 disable 开关 |
| deeptutor/services/llm/capabilities.py:516 | `_RUNTIME_DISABLED_FORCED_TOOL_CHOICE` (set) | disable_forced_tool_choice_at_runtime@523 .add() | 显式 disable 开关 |
| deeptutor/services/llm/openai_http_client.py:50 | `_sanitized_warned` (set) | sanitize_invalid_ssl_env@80 .add() | 去重告警，按 SSL 值有界 |
| deeptutor/services/llm/registry.py:11 | `_provider_registry` (Dict) | register_provider@28 item-assign | 注册表 API |
| deeptutor/services/memory/consolidator/modes/_runtime.py:32 | `_PROMPT_CACHE` (Dict) | load_prompt@49 item-assign | 进程内缓存，miss 填充，按键有界 |
| deeptutor/services/memory/consolidator/modes/_runtime.py:35 | `_META_CACHE` (Dict) | load_focus_meta@61 item-assign | 进程内缓存，miss 填充，按键有界 |
| deeptutor/services/memory/trace.py:24 | `_locks` (Dict) | _lock_for@31 item-assign | 锁表，按资源数有界 |
| deeptutor/services/notebook/service.py:701 | `_instances` (Dict) | get_notebook_manager@708 item-assign | 进程级单例注册 |
| deeptutor/services/partner_groups/memory.py:14 | `_WHITEBOARD_LOCKS` (Dict) | _whiteboard_lock@21 .setdefault() | 锁表，按资源数有界 |
| deeptutor/services/partner_groups/store.py:22 | `_LOCKS` (Dict) | _lock_for@32 .setdefault() | 锁表，按资源数有界 |
| deeptutor/services/partners/drafts.py:23 | `_LOCKS` (Dict) | _lock_for@30 .setdefault() | 锁表，按资源数有界 |
| deeptutor/services/partners/interaction.py:73 | `_STORES` (Dict) | session_store_for@100 item-assign；forget_partner_stores@108 .pop() | 有 forget_partner_stores |
| deeptutor/services/partners/links.py:38 | `_locks` (Dict) | _lock@62 item-assign；forget_partner_links@197 .pop() | 有 forget_partner_links |
| deeptutor/services/partners/weixin_onboarding.py:69 | `_attempts` (Dict) | _prune@80 .pop()；start_login@163 item-assign；forget@315 .pop() | threading.Lock 保护 + TTL prune，有界 |
| deeptutor/services/persona/service.py:342 | `_instances` (Dict) | get_persona_service@358 item-assign | 进程级单例注册 |
| deeptutor/services/rag/factory.py:64 | `_PIPELINE_CACHE` (Dict) | get_pipeline@208 item-assign | 按 (kb_dir, provider) 键控；索引失效轴归 scan/cache-invalidation 卡 |
| deeptutor/services/rag/pipelines/graphrag/completion_adapter.py:23 | `_JSON_OBJECT_CAPABILITIES` (set) | _remember_json_object@42 .add()；clear_capability_cache@69 .clear() | 有 clear_capability_cache |
| deeptutor/services/rag/pipelines/ima/inventory.py:71 | `_CACHE` (Dict) | clear_cache@129 .clear()；_cached@189 .pop()；_store@196 item-assign | 有 clear_cache / miss 填充 |
| deeptutor/services/rag/pipelines/llamaindex/pipeline.py:44 | `_INDEX_WORKERS` (Dict) | _claim_index_worker@76 item-assign；_release_index_worker@86 .pop() | claim/release 成对，完成即 pop |
| deeptutor/services/search/providers/__init__.py:20 | `_PROVIDERS` (Dict) | register_provider@54 item-assign | 注册表 API |
| deeptutor/services/search/source_filter.py:92 | `_web_risk_cache` (Dict) | _cache_web_risk_result@338 .pop()；_cache_web_risk_result@339 item-assign | 锁保护 + TTL + MAX 上限 |
| deeptutor/services/search/source_filter.py:94 | `_web_risk_inflight` (Dict) | _web_risk_rejections@306 item-assign；_cache_web_risk_result@333 .pop() | 锁保护 + MAX_INFLIGHT 上限 + done-callback 回收 |
| deeptutor/services/session/__init__.py:12 | `_pocketbase_store_instances` (Dict) | get_session_store@36 item-assign | 进程级单例注册 |
| deeptutor/services/session/sqlite_store.py:4581 | `_instances` (Dict) | get_sqlite_session_store@4588 item-assign；get_sqlite_session_store_for@4602 item-assign | 按 scope 键控；data_migration 有清理 seam |
| deeptutor/services/session/turn_runtime.py:40 | `_runtime_instances` (Dict) | get_turn_runtime_manager@51 item-assign | 进程级单例注册 |
| deeptutor/services/settings/interface_settings.py:36 | `_LOCKS` (Dict) | _settings_lock@70 item-assign | 锁表，按资源数有界 |
| deeptutor/services/skill/service.py:1026 | `_instances` (Dict) | get_skill_service@1049 item-assign | 进程级单例注册 |
| deeptutor/services/storage/attachment_store.py:279 | `_stores` (Dict) | get_attachment_store@292 item-assign；reset_attachment_store@325 .clear() | 有 reset_attachment_store |
| deeptutor/services/storage/file_library.py:454 | `_instances` (Dict) | get_file_library_store@474 item-assign；reset_file_library_store@480 .clear() | 有 reset_file_library_store |
| deeptutor/services/subagent/opencode_server.py:68 | `_servers` (Dict) | acquire_server@93 .pop()；acquire_server@95 item-assign；_reap_stale@168 .pop() | acquire/reap/shutdown 完整回收 |
| deeptutor/services/suggestions.py:118 | `_inflight` (Dict) | refresh_suggestions@642 item-assign；refresh_suggestions@651 .pop()；_schedule_probe@712 .pop() | asyncio 单循环 + done-callback 清理 |
| deeptutor/services/suggestions.py:121 | `_last_probe` (Dict) | refresh_suggestions@643 item-assign；_schedule_probe@703 item-assign | 按 scope 单调追加，有界 |
| deeptutor/services/suggestions.py:122 | `_failures` (Dict) | _generate_and_cache@616 item-assign；_generate_and_cache@618 .pop()；_bounded_generation@661 item-assign | scope 键控，成功即 pop |

## 无风险条目（修改存在但非运行时共享路径）

| 定义点 | 名称(类型) | 证据 | 说明 |
|---|---|---|---|
| `deeptutor/runtime/request_contracts.py:141` | `CAPABILITY_CONFIG_VALIDATORS` (dict) | @181 .setdefault() | import 期注册表，setdefault 幂等，无风险 |
| `deeptutor/services/cli_apps/vendor/build_snapshot.py:36` | `out` (list) | @41 append；@43 sort | vendor 构建脚本，非运行时，无风险 |
| `deeptutor/services/cli_apps/vendor/build_snapshot.py:44` | `seen` (dict) | @48 item-assign | 同上 |
| `tests/reading/test_router.py:27` | `PAGES` (list) | 用作函数默认值 | 测试辅助数据，非生产路径，无风险 |

## 跨文件修改回查结论

对 401 个候选名做全库回查：命中均为 (a) 测试文件中的重置/monkeypatch，或 (b) 有意的重置 seam（`deeptutor/runtime/cache_reset.py`、`deeptutor/services/workspace/data_migration.py` 的 `_clear_store_caches`）。无越模块写生产状态的旁路。

## 复核命令

- AST 扫描: `python3 scan_mutdef.py <worktree>`（轴 A+轴 B 定义点）；`python3 triage_mutdef.py <worktree> raw.json`（修改证据与默认值用法）
- 交叉验证: `rg -n "def .*(=\s*(\[|\{)|=\s*(list|dict|set)\(\s*\))" --type py`（0 命中）
- 跨文件: rg 对 401 个名字的 `<name>.(append|update|add|...)` 全库回查
