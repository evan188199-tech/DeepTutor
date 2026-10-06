# SQLite 查询计划与索引缺口清点（EXPLAIN QUERY PLAN）

- 源码版本: `f07029cfcf2c8dfccdb671cdfc343db8334f5741`（origin/main，read-only 扫描）
- SQLite 版本: 3.50.4 / Python 3.13.13
- 轴线: 读路径与查询计划（与 scan-persistence 写入/原子性轴、fix-storage-write-fsync 写路径轴去重，不重复覆盖）

## 口径（方法）

1. **访问点提取**：AST 静态解析 `deeptutor/` 全部生产代码（排除 tests），
   抓取 `execute` / `executemany` / `executescript` 调用中的 SQL 字面量、
   f-string（插值规范化为 `?`）、字符串拼接与 join；`executescript` 按完整语句切分。
2. **schema 重建**：优先用各模块真实 store 构造器在临时目录/内存库中初始化
   （含全部 migration 与 trigger），失败时回退为源码 DDL 静态重放；
   再合并为一张 union 规划库（同名同构去重，冲突记录在 collisions.json）。
3. **计划采集**：对全部 read/write 访问点执行 `EXPLAIN QUERY PLAN`
   （参数占位符不绑定，不影响结构化计划）；不连任何真实数据库。
4. **缺口判定**：裸 `SCAN`（不带 USING INDEX/COVERING INDEX）= 全表扫描；
   `SCAN … USING INDEX` = 索引序扫描（过滤列不在索引内，降级为 low）；
   `USING TEMP B-TREE` = 大结果排序/分组；结合 WHERE 存在性与表规模分级（high/medium/low/info）。

## 覆盖统计

- 扫描文件数: 1004；SQL 调用点: 654；
  SQL 语句: 711；无法静态提取: 14
- 访问点合计: 725 = 计划成功 426
  + 计划失败 21 + 非查询/DDL/PRAGMA 跳过 264
- schema 模块: 13；表: 46；
  索引: 42；触发器: 3；视图: 0

### Schema 模块明细

| 模块 | 重建方式 | 表 | 索引 | 触发器 |
| --- | --- | --- | --- | --- |
| `services/session/sqlite_store.py` | import:SQLiteSessionStore(db_path=tmp) | 13 | 19 | 3 |
| `services/practice/storage.py` | covered-by:services/session/sqlite_store.py | 0 | 0 | 0 |
| `learning/storage.py` | import:LearningStore(root=tmp) | 11 | 9 | 0 |
| `reading/catalog_store.py` | import:ReadingCatalogStore(root=tmp) | 6 | 4 | 0 |
| `capabilities/marginnote4/store.py` | import:MarginNoteStore(db_path=tmp) | 4 | 3 | 0 |
| `services/cron/repository.py` | import:SQLiteCronRepository(path=tmp) | 2 | 1 | 0 |
| `services/web_source/repository.py` | import:SQLiteWebSourceSyncRepository(path=tmp) | 2 | 2 | 0 |
| `services/storage/file_library.py` | import:FileLibraryStore(db_path=tmp, root=tmp) | 1 | 2 | 0 |
| `services/task_board.py` | import:TaskBoardStore._connect(path=tmp) | 1 | 0 | 0 |
| `services/llm/usage_ledger.py` | import:usage_ledger.record_call(path=tmp) | 1 | 1 | 0 |
| `services/partners/runtime_status.py` | import:PartnerRuntimeStatusRepository(path=tmp) | 1 | 0 | 0 |
| `multi_user/session_handoff.py` | import:SessionHandoffStore._initialize(db_path=tmp) | 2 | 1 | 0 |
| `services/workspace/catalog.py` | static:workspace/catalog.py inline DDL | 2 | 0 | 0 |

## 缺口清单

1. **[HIGH]** `deeptutor/learning/storage.py:544`（read，表: mastery_topic_meta, mastery_paths，函数 `_ensure_initialized`）
   - SQL: `SELECT path_id, created_at, updated_at FROM mastery_paths WHERE path_id NOT IN (SELECT path_id FROM mastery_topic_meta)`
   - 计划: SCAN mastery_paths
   - 标记: full-scan-with-filter
   - 建议: 过滤列无可用索引导致全表扫描：补 (过滤列[, 排序列]) 索引，或确认表规模恒小/调用频率极低后接受；表 mastery_paths 现有索引: 无
2. **[HIGH]** `deeptutor/learning/storage.py:633`（write，表: mastery_path_sessions，函数 `_converge_single_membership`）
   - SQL: `DELETE FROM mastery_path_sessions WHERE rowid NOT IN ( SELECT rowid FROM ( SELECT rowid, ROW_NUMBER() OVER ( PARTITION BY session_id ORDER BY last_seen_at DESC…`
   - 计划: SCAN mastery_path_sessions
   - 计划: SCAN mastery_path_sessions USING INDEX idx_mastery_sessions_membership
   - 标记: full-scan-with-filter, index-scan-filter-not-covered
   - 建议: 过滤列无可用索引导致全表扫描：补 (过滤列[, 排序列]) 索引，或确认表规模恒小/调用频率极低后接受；表 mastery_path_sessions 现有索引: idx_mastery_sessions_session, idx_mastery_sessions_membership
3. **[HIGH]** `deeptutor/learning/storage.py:1834`（read，表: mastery_paths，函数 `detach_session`）
   - SQL: `SELECT path_id, state_json FROM mastery_paths WHERE owner_session_id = ? OR (owner_session_id = '' AND path_id = ?)`
   - 计划: SCAN mastery_paths
   - 标记: full-scan-with-filter
   - 建议: 过滤列无可用索引导致全表扫描：补 (过滤列[, 排序列]) 索引，或确认表规模恒小/调用频率极低后接受；表 mastery_paths 现有索引: 无
4. **[HIGH]** `deeptutor/multi_user/session_handoff.py:230`（write，表: handoff_records，函数 `_cleanup`）
   - SQL: `DELETE FROM handoff_records WHERE expires_at + ? < ?`
   - 计划: SCAN handoff_records
   - 标记: full-scan-with-filter
   - 建议: 过滤列无可用索引导致全表扫描：补 (过滤列[, 排序列]) 索引，或确认表规模恒小/调用频率极低后接受；表 handoff_records 现有索引: handoff_expiry_idx
5. **[HIGH]** `deeptutor/services/practice/storage.py:93`（write，表: practice_review_state, notebook_entries，函数 `initialize_practice`）
   - SQL: `INSERT OR IGNORE INTO practice_review_state(entry_id, first_wrong_at, due_at) SELECT id, created_at, created_at + 86400 FROM notebook_entries WHERE is_correct …`
   - 计划: SCAN notebook_entries
   - 标记: full-scan-with-filter
   - 建议: 过滤列无可用索引导致全表扫描：补 (过滤列[, 排序列]) 索引，或确认表规模恒小/调用频率极低后接受；表 notebook_entries 现有索引: idx_notebook_entries_session, idx_notebook_entries_bookmarked, idx_notebook_entries_review, idx_notebook_entries_linkage, idx_notebook_entries_origin
6. **[HIGH]** `deeptutor/services/session/sqlite_store.py:586`（write，表: messages, metadata, turns，函数 `_migrate_turn_runtime_columns`）（迁移/一次性路径）
   - SQL: `UPDATE turns SET assistant_message_id = ( SELECT m.id FROM messages AS m, json_each(m.events_json) AS event WHERE m.session_id = turns.session_id AND m.role = …`
   - 计划: SCAN turns
   - 计划: SCAN event VIRTUAL TABLE INDEX 1:
   - 标记: full-scan-with-filter
   - 建议: 过滤列无可用索引导致全表扫描：补 (过滤列[, 排序列]) 索引，或确认表规模恒小/调用频率极低后接受；表 turns 现有索引: idx_turns_session_updated, idx_turns_session_status, idx_turns_assistant_message, idx_turns_one_active_session
7. **[HIGH]** `deeptutor/services/session/sqlite_store.py:3428`（read，表: assessment_attempts，函数 `_list_assessment_attempts_sync`）
   - SQL: `SELECT assessment_json FROM assessment_attempts WHERE {?} ORDER BY occurred_at, rowid`
   - 计划: SCAN assessment_attempts
   - 标记: full-scan-with-filter
   - 建议: 过滤列无可用索引导致全表扫描：补 (过滤列[, 排序列]) 索引，或确认表规模恒小/调用频率极低后接受；表 assessment_attempts 现有索引: idx_assessment_attempts_session_time, idx_assessment_attempts_linkage, idx_assessment_attempts_origin_time, idx_assessment_attempts_pending_link
8. **[HIGH]** `deeptutor/services/web_source/repository.py:256`（write，表: web_source_sync_jobs，函数 `recover_interrupted`）
   - SQL: `UPDATE web_source_sync_jobs SET state='interrupted', error='Synchronization was interrupted by a restart', runner_id='', lease_until_ms=NULL, next_run_at_ms=?,…`
   - 计划: SCAN web_source_sync_jobs
   - 标记: full-scan-with-filter
   - 建议: 过滤列无可用索引导致全表扫描：补 (过滤列[, 排序列]) 索引，或确认表规模恒小/调用频率极低后接受；表 web_source_sync_jobs 现有索引: idx_web_source_sync_due
9. **[MEDIUM]** `deeptutor/capabilities/marginnote4/store.py:420`（read，表: mn4_objects，函数 `search`）
   - SQL: `SELECT * FROM mn4_objects WHERE (LOWER(title) LIKE ? OR LOWER(content) LIKE ? OR LOWER(COALESCE(excerpt, '')) LIKE ? OR LOWER(COALESCE(document_title, '')) LIK…`
   - 计划: SCAN mn4_objects
   - 标记: full-scan-with-filter
   - 建议: 含 LIKE 过滤的全表扫描：前置通配 LIKE 无法用 B-tree 索引；如成为热点考虑 FTS5 虚表或应用层倒排，否则接受扫描
10. **[MEDIUM]** `deeptutor/capabilities/marginnote4/store.py:446`（read，表: mn4_objects，函数 `list_objects`）
   - SQL: `SELECT * FROM mn4_objects WHERE (LOWER(title) LIKE ? OR LOWER(content) LIKE ? OR LOWER(COALESCE(excerpt, '')) LIKE ? OR LOWER(COALESCE(document_title, '')) LIK…`
   - 计划: SCAN mn4_objects
   - 标记: full-scan-with-filter
   - 建议: 含 LIKE 过滤的全表扫描：前置通配 LIKE 无法用 B-tree 索引；如成为热点考虑 FTS5 虚表或应用层倒排，否则接受扫描
11. **[MEDIUM]** `deeptutor/capabilities/marginnote4/store.py:461`（read，表: mn4_objects，函数 `list_documents`）
   - SQL: `SELECT * FROM mn4_objects WHERE (LOWER(title) LIKE ? OR LOWER(content) LIKE ? OR LOWER(COALESCE(excerpt, '')) LIKE ? OR LOWER(COALESCE(document_title, '')) LIK…`
   - 计划: SCAN mn4_objects
   - 标记: full-scan-with-filter
   - 建议: 含 LIKE 过滤的全表扫描：前置通配 LIKE 无法用 B-tree 索引；如成为热点考虑 FTS5 虚表或应用层倒排，否则接受扫描
12. **[MEDIUM]** `deeptutor/capabilities/marginnote4/store.py:478`（read，表: mn4_objects，函数 `linked_objects`）
   - SQL: `SELECT object_id FROM mn4_objects WHERE links LIKE ?`
   - 计划: SCAN mn4_objects
   - 标记: full-scan-with-filter
   - 建议: 含 LIKE 过滤的全表扫描：前置通配 LIKE 无法用 B-tree 索引；如成为热点考虑 FTS5 虚表或应用层倒排，否则接受扫描
13. **[MEDIUM]** `deeptutor/capabilities/marginnote4/store.py:499`（read，表: mn4_objects，函数 `collect_tags`）
   - SQL: `SELECT * FROM mn4_objects WHERE (LOWER(title) LIKE ? OR LOWER(content) LIKE ? OR LOWER(COALESCE(excerpt, '')) LIKE ? OR LOWER(COALESCE(document_title, '')) LIK…`
   - 计划: SCAN mn4_objects
   - 标记: full-scan-with-filter
   - 建议: 含 LIKE 过滤的全表扫描：前置通配 LIKE 无法用 B-tree 索引；如成为热点考虑 FTS5 虚表或应用层倒排，否则接受扫描
14. **[MEDIUM]** `deeptutor/learning/storage.py:573`（read，表: mastery_paths，函数 `_ensure_initialized`）
   - SQL: `SELECT path_id, state_json, revision FROM mastery_paths`
   - 计划: SCAN mastery_paths
   - 标记: full-scan-large-table
   - 建议: 大表无过滤全扫：若为有意的全量读取可接受，否则补过滤/索引
15. **[MEDIUM]** `deeptutor/learning/storage.py:1550`（read，表: mastery_topic_meta, mastery_paths，函数 `list_topic_snapshots`）
   - SQL: `SELECT p.* FROM mastery_paths p JOIN mastery_topic_meta m ON m.path_id = p.path_id WHERE m.status = ? ORDER BY p.updated_at DESC`
   - 计划: SCAN m
   - 标记: full-scan-with-filter
   - 建议: 过滤列无可用索引导致全表扫描：补 (过滤列[, 排序列]) 索引，或确认表规模恒小/调用频率极低后接受；表 mastery_topic_meta 现有索引: 无
16. **[MEDIUM]** `deeptutor/learning/storage.py:1561`（read，表: mastery_topic_meta，函数 `list_topic_snapshots`）
   - SQL: `SELECT * FROM mastery_topic_meta WHERE status = ?`
   - 计划: SCAN mastery_topic_meta
   - 标记: full-scan-with-filter
   - 建议: 过滤列无可用索引导致全表扫描：补 (过滤列[, 排序列]) 索引，或确认表规模恒小/调用频率极低后接受；表 mastery_topic_meta 现有索引: 无
17. **[MEDIUM]** `deeptutor/learning/storage.py:1593`（read，表: mastery_interactions, mastery_topic_meta，函数 `list_topic_snapshots`）
   - SQL: `SELECT i.* FROM mastery_interactions i JOIN mastery_topic_meta m ON m.path_id = i.path_id WHERE m.status = ? AND i.status IN ({?})`
   - 计划: SCAN i
   - 标记: full-scan-with-filter
   - 建议: 过滤列无可用索引导致全表扫描：补 (过滤列[, 排序列]) 索引，或确认表规模恒小/调用频率极低后接受；表 mastery_interactions 现有索引: idx_mastery_interactions_path, uq_mastery_one_active_interaction
18. **[MEDIUM]** `deeptutor/learning/storage.py:1645`（read，表: mastery_topic_meta，函数 `has_active_topics`）
   - SQL: `SELECT 1 FROM mastery_topic_meta WHERE status = 'active' LIMIT 1`
   - 计划: SCAN mastery_topic_meta
   - 标记: full-scan-with-filter
   - 建议: 过滤列无可用索引导致全表扫描：补 (过滤列[, 排序列]) 索引，或确认表规模恒小/调用频率极低后接受；表 mastery_topic_meta 现有索引: 无
19. **[MEDIUM]** `deeptutor/learning/storage.py:1842`（write，表: mastery_path_leases，函数 `detach_session`）
   - SQL: `DELETE FROM mastery_path_leases WHERE session_id = ?`
   - 计划: SCAN mastery_path_leases
   - 标记: full-scan-with-filter
   - 建议: 过滤列无可用索引导致全表扫描：补 (过滤列[, 排序列]) 索引，或确认表规模恒小/调用频率极低后接受；表 mastery_path_leases 现有索引: 无
20. **[MEDIUM]** `deeptutor/multi_user/session_handoff.py:234`（write，表: handoff_rate_limits，函数 `_cleanup`）
   - SQL: `DELETE FROM handoff_rate_limits WHERE window_start + 3600 < ?`
   - 计划: SCAN handoff_rate_limits
   - 标记: full-scan-with-filter
   - 建议: 过滤列无可用索引导致全表扫描：补 (过滤列[, 排序列]) 索引，或确认表规模恒小/调用频率极低后接受；表 handoff_rate_limits 现有索引: 无
21. **[MEDIUM]** `deeptutor/reading/catalog_store.py:213`（write，表: reading_materials，函数 `_remove_content_id_unique_constraint`）
   - SQL: `INSERT INTO reading_materials_new ( material_id, content_id, filename, title, source_kind, source_url, mime, render_mode, cover_url, duration_seconds, status, …`
   - 计划: SCAN reading_materials
   - 标记: full-scan-large-table
   - 建议: 大表无过滤全扫：若为有意的全量读取可接受，否则补过滤/索引
22. **[MEDIUM]** `deeptutor/services/cron/repository.py:190`（read，表: cron_jobs，函数 `list_payloads`）
   - SQL: `SELECT payload FROM cron_jobs ORDER BY COALESCE(next_run_at_ms, 0), id`
   - 计划: SCAN cron_jobs
   - 标记: full-scan-large-table
   - 建议: 大表无过滤全扫：若为有意的全量读取可接受，否则补过滤/索引
23. **[MEDIUM]** `deeptutor/services/memory/snapshot/adapters.py:466`（read，表: notebook_entries，函数 `read_quiz_entities`）
   - SQL: `SELECT id, session_id, turn_id, question_id, question, question_type, options_json, correct_answer, explanation, difficulty, user_answer, is_correct, bookmarke…`
   - 计划: SCAN notebook_entries
   - 标记: full-scan-large-table
   - 建议: 大表无过滤全扫：若为有意的全量读取可接受，否则补过滤/索引
24. **[MEDIUM]** `deeptutor/services/practice/storage.py:330`（write，表: practice_imports，函数 `stage_import`）
   - SQL: `DELETE FROM practice_imports WHERE created_at < ? AND result_json IS NULL`
   - 计划: SCAN practice_imports
   - 标记: full-scan-with-filter
   - 建议: 过滤列无可用索引导致全表扫描：补 (过滤列[, 排序列]) 索引，或确认表规模恒小/调用频率极低后接受；表 practice_imports 现有索引: 无
25. **[MEDIUM]** `deeptutor/services/session/sqlite_store.py:682`（write，表: notebook_entries，函数 `_migrate_notebook_entries_add_turn_id`）（迁移/一次性路径）
   - SQL: `INSERT INTO notebook_entries_new ( id, session_id, turn_id, question_id, question, question_type, options_json, correct_answer, explanation, difficulty, user_a…`
   - 计划: SCAN notebook_entries
   - 标记: full-scan-large-table
   - 建议: 大表无过滤全扫：若为有意的全量读取可接受，否则补过滤/索引
26. **[MEDIUM]** `deeptutor/services/session/sqlite_store.py:1047`（write，表: assessment_attempts，函数 `_migrate_assessment_attempt_origins`）（迁移/一次性路径）
   - SQL: `INSERT INTO assessment_attempts_new ( attempt_id, notebook_entry_id, session_id, origin_type, origin_ref, turn_id, question_id, source, assessment_type, result…`
   - 计划: SCAN assessment_attempts
   - 标记: full-scan-large-table
   - 建议: 大表无过滤全扫：若为有意的全量读取可接受，否则补过滤/索引
27. **[MEDIUM]** `deeptutor/services/session/sqlite_store.py:2512`（read，表: turn_events, messages, turns，函数 `read`）
   - SQL: `SELECT m.id, m.session_id, m.created_at, m.events_json, m.metadata_json AS message_metadata, t.id AS turn_id, e.type, e.metadata_json FROM messages AS m LEFT J…`
   - 计划: SCAN m
   - 标记: full-scan-with-filter
   - 建议: 过滤列无可用索引导致全表扫描：补 (过滤列[, 排序列]) 索引，或确认表规模恒小/调用频率极低后接受；表 turn_events 现有索引: idx_turn_events_turn_seq
28. **[MEDIUM]** `deeptutor/services/session/sqlite_store.py:2798`（read，表: sessions, messages, turns，函数 `_search_sessions_sync`）
   - SQL: `WITH matched_sessions AS ( SELECT s.* FROM sessions s WHERE {?} ORDER BY s.updated_at DESC, s.id ASC LIMIT ? OFFSET ? ), best_messages AS ( SELECT m.session_id…`
   - 计划: SCAN s USING INDEX idx_sessions_updated_at
   - 计划: SCAN m
   - 计划: SCAN s
   - 标记: full-scan-with-filter, index-scan-filter-not-covered
   - 建议: 过滤列无可用索引导致全表扫描：补 (过滤列[, 排序列]) 索引，或确认表规模恒小/调用频率极低后接受；表 sessions 现有索引: idx_sessions_updated_at
29. **[MEDIUM]** `deeptutor/services/session/sqlite_store.py:4408`（read，表: notebook_categories，函数 `_find_category_by_name_sync`）
   - SQL: `SELECT id, name, created_at FROM notebook_categories WHERE name = ? COLLATE NOCASE ORDER BY id LIMIT 1`
   - 计划: SCAN notebook_categories
   - 标记: full-scan-with-filter
   - 建议: 过滤列无可用索引导致全表扫描：补 (过滤列[, 排序列]) 索引，或确认表规模恒小/调用频率极低后接受；表 notebook_categories 现有索引: 无
30. **[MEDIUM]** `deeptutor/services/workspace/catalog.py:116`（read，表: workspaces，函数 `_save_registration`）
   - SQL: `SELECT payload FROM workspaces WHERE id = ? OR (json_extract(payload, '$.owner_id') = ? AND json_extract(payload, '$.path') = ?)`
   - 计划: SCAN workspaces
   - 标记: full-scan-with-filter
   - 建议: 过滤列无可用索引导致全表扫描：补 (过滤列[, 排序列]) 索引，或确认表规模恒小/调用频率极低后接受；表 workspaces 现有索引: 无
31. **[MEDIUM]** `deeptutor/services/workspace/data_migration.py:449`（read，表: turns，函数 `_selected_artifact_files`）
   - SQL: `SELECT id,session_id FROM turns`
   - 计划: SCAN turns
   - 标记: full-scan-large-table
   - 建议: 大表无过滤全扫：若为有意的全量读取可接受，否则补过滤/索引
32. **[MEDIUM]** `deeptutor/services/workspace/data_migration.py:871`（write，表: sessions，函数 `_prune_session_snapshot`）
   - SQL: `DELETE FROM sessions WHERE id NOT IN (SELECT id FROM retained_sessions)`
   - 计划: SCAN sessions
   - 标记: full-scan-with-filter
   - 建议: 过滤列无可用索引导致全表扫描：补 (过滤列[, 排序列]) 索引，或确认表规模恒小/调用频率极低后接受；表 sessions 现有索引: idx_sessions_updated_at
33. **[MEDIUM]** `deeptutor/services/workspace/data_migration.py:872`（write，表: notebook_entry_categories, notebook_categories，函数 `_prune_session_snapshot`）
   - SQL: `DELETE FROM notebook_categories WHERE id NOT IN (SELECT category_id FROM notebook_entry_categories)`
   - 计划: SCAN notebook_categories
   - 计划: SCAN notebook_entry_categories
   - 标记: full-scan-with-filter
   - 建议: 过滤列无可用索引导致全表扫描：补 (过滤列[, 排序列]) 索引，或确认表规模恒小/调用频率极低后接受；表 notebook_entry_categories 现有索引: 无
34. **[MEDIUM]** `deeptutor/services/workspace/dependencies.py:323`（read，表: messages，函数 `_with_historical_references`）
   - SQL: `SELECT session_id,metadata_json FROM messages`
   - 计划: SCAN messages
   - 标记: full-scan-large-table
   - 建议: 大表无过滤全扫：若为有意的全量读取可接受，否则补过滤/索引
35. **[MEDIUM]** `deeptutor/services/workspace/dependencies.py:329`（read，表: notebook_entries，函数 `_with_historical_references`）
   - SQL: `SELECT session_id,followup_session_id FROM notebook_entries`
   - 计划: SCAN notebook_entries
   - 标记: full-scan-large-table
   - 建议: 大表无过滤全扫：若为有意的全量读取可接受，否则补过滤/索引
36. **[LOW]** `deeptutor/capabilities/marginnote4/store.py:513`（read，表: mn4_objects，函数 `count`）
   - SQL: `SELECT COUNT(*) AS n FROM mn4_objects WHERE device_id = ?`
   - 计划: SCAN mn4_objects USING COVERING INDEX sqlite_autoindex_mn4_objects_1
   - 标记: covering-index-scan
   - 建议: 全量扫描覆盖索引：如结果集大，考虑收紧过滤或投影
37. **[LOW]** `deeptutor/learning/storage.py:1567`（read，表: mastery_topic_sources, mastery_topic_meta，函数 `list_topic_snapshots`）
   - SQL: `SELECT s.* FROM mastery_topic_sources s JOIN mastery_topic_meta m ON m.path_id = s.path_id WHERE m.status = ? ORDER BY s.path_id, s.position ASC, s.created_at …`
   - 计划: SCAN s USING INDEX idx_mastery_topic_sources_path
   - 标记: index-scan-filter-not-covered
   - 建议: 沿索引序扫描后再过滤：过滤列不在该索引内；若结果集大，把过滤列并入索引或改用过滤列索引
38. **[LOW]** `deeptutor/learning/storage.py:1579`（read，表: mastery_path_sessions, mastery_topic_meta，函数 `list_topic_snapshots`）
   - SQL: `SELECT b.path_id, COUNT(*) AS session_count FROM mastery_path_sessions b JOIN mastery_topic_meta m ON m.path_id = b.path_id WHERE m.status = ? GROUP BY b.path_…`
   - 计划: SCAN b USING COVERING INDEX sqlite_autoindex_mastery_path_sessions_1
   - 标记: covering-index-scan
   - 建议: 全量扫描覆盖索引：如结果集大，考虑收紧过滤或投影
39. **[LOW]** `deeptutor/reading/catalog_store.py:79`（write，表: reading_schema，函数 `_initialize`）
   - SQL: `INSERT INTO reading_schema(version) SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM reading_schema);`
   - 计划: SCAN reading_schema
   - 标记: full-scan-with-filter
   - 建议: 过滤列无可用索引导致全表扫描：补 (过滤列[, 排序列]) 索引，或确认表规模恒小/调用频率极低后接受；表 reading_schema 现有索引: 无
40. **[LOW]** `deeptutor/reading/catalog_store.py:381`（read，表: reading_materials，函数 `find_ready_material_by_filename`）
   - SQL: `SELECT * FROM reading_materials WHERE filename = ? COLLATE NOCASE AND status = 'ready' ORDER BY updated_at DESC, material_id`
   - 计划: SCAN reading_materials USING INDEX idx_reading_materials_updated
   - 标记: index-scan-filter-not-covered
   - 建议: 沿索引序扫描后再过滤：过滤列不在该索引内；若结果集大，把过滤列并入索引或改用过滤列索引
41. **[LOW]** `deeptutor/reading/catalog_store.py:445`（read，表: reading_workspace_materials, reading_workspaces，函数 `collections_for_materials`）
   - SQL: `SELECT wm.material_id, w.workspace_id, w.title FROM reading_workspace_materials wm JOIN reading_workspaces w USING (workspace_id) WHERE wm.material_id IN ({?})…`
   - 计划: SCAN wm USING COVERING INDEX sqlite_autoindex_reading_workspace_materials_1
   - 标记: covering-index-scan
   - 建议: 全量扫描覆盖索引：如结果集大，考虑收紧过滤或投影
42. **[LOW]** `deeptutor/services/memory/snapshot/adapters.py:542`（read，表: messages，函数 `probe_chat_entities`）
   - SQL: `SELECT session_id, id FROM ( SELECT session_id, id, ROW_NUMBER() OVER ( PARTITION BY session_id ORDER BY created_at DESC, id DESC ) AS rn FROM messages) WHERE …`
   - 计划: SCAN messages USING COVERING INDEX idx_messages_session_created
   - 标记: covering-index-scan
   - 建议: 全量扫描覆盖索引：如结果集大，考虑收紧过滤或投影
43. **[LOW]** `deeptutor/services/practice/storage.py:134`（read，表: practice_review_state, notebook_entries, sessions，函数 `overview`）
   - SQL: `SELECT COUNT(*) AS total, COALESCE(SUM(r.is_mistake = 1), 0) AS mistakes, COALESCE(SUM({?} <= ?), 0) AS due, COALESCE(SUM({?} <= ?), 0) AS overdue, MIN({?}) AS…`
   - 计划: SCAN n USING COVERING INDEX idx_notebook_entries_session
   - 标记: covering-index-scan
   - 建议: 全量扫描覆盖索引：如结果集大，考虑收紧过滤或投影
44. **[LOW]** `deeptutor/services/practice/storage.py:146`（read，表: practice_review_events, notebook_entries, sessions，函数 `overview`）
   - SQL: `SELECT COUNT(DISTINCT e.entry_id) FROM practice_review_events e JOIN notebook_entries n ON n.id = e.entry_id LEFT JOIN sessions s ON s.id = n.session_id WHERE …`
   - 计划: SCAN e USING COVERING INDEX idx_practice_history
   - 标记: covering-index-scan
   - 建议: 全量扫描覆盖索引：如结果集大，考虑收紧过滤或投影
45. **[LOW]** `deeptutor/services/practice/storage.py:186`（read，表: practice_review_state, notebook_entries, sessions，函数 `queue`）
   - SQL: `SELECT n.id FROM notebook_entries n LEFT JOIN sessions s ON s.id=n.session_id LEFT JOIN practice_review_state r ON r.entry_id=n.id WHERE {?} <= ? AND {?} ORDER…`
   - 计划: SCAN n USING COVERING INDEX idx_notebook_entries_session
   - 标记: covering-index-scan
   - 建议: 全量扫描覆盖索引：如结果集大，考虑收紧过滤或投影
46. **[LOW]** `deeptutor/services/session/sqlite_store.py:610`（read，表: turns，函数 `_migrate_turn_runtime_columns`）（迁移/一次性路径）
   - SQL: `SELECT id, session_id FROM turns WHERE status IN ('queued', 'running', 'waiting_input') ORDER BY session_id, updated_at DESC, id DESC`
   - 计划: SCAN turns USING INDEX idx_turns_one_active_session
   - 标记: index-scan-filter-not-covered
   - 建议: 沿索引序扫描后再过滤：过滤列不在该索引内；若结果集大，把过滤列并入索引或改用过滤列索引
47. **[LOW]** `deeptutor/services/session/sqlite_store.py:1457`（read，表: turn_events, turns，函数 `_list_nonterminal_turns_sync`）
   - SQL: `SELECT t.*, COALESCE((SELECT MAX(seq) FROM turn_events te WHERE te.turn_id = t.id), 0) AS last_seq FROM turns t WHERE t.status IN ('queued', 'running', 'waitin…`
   - 计划: SCAN t USING INDEX idx_turns_one_active_session
   - 标记: index-scan-filter-not-covered
   - 建议: 沿索引序扫描后再过滤：过滤列不在该索引内；若结果集大，把过滤列并入索引或改用过滤列索引
48. **[LOW]** `deeptutor/services/session/sqlite_store.py:2793`（read，表: sessions，函数 `_search_sessions_sync`）
   - SQL: `SELECT COUNT(*) FROM sessions s WHERE {?}`
   - 计划: SCAN s USING COVERING INDEX idx_sessions_updated_at
   - 标记: covering-index-scan
   - 建议: 全量扫描覆盖索引：如结果集大，考虑收紧过滤或投影
49. **[LOW]** `deeptutor/services/session/sqlite_store.py:3402`（read，表: assessment_attempts，函数 `_pending_linked_assessments_sync`）
   - SQL: `SELECT assessment_json FROM assessment_attempts WHERE linked_applied = 0 AND mastery_path_id != '' AND knowledge_point_id != '' AND source != 'mastery_path' AN…`
   - 计划: SCAN assessment_attempts USING INDEX idx_assessment_attempts_pending_link
   - 标记: index-scan-filter-not-covered
   - 建议: 沿索引序扫描后再过滤：过滤列不在该索引内；若结果集大，把过滤列并入索引或改用过滤列索引
50. **[LOW]** `deeptutor/services/session/sqlite_store.py:4042`（read，表: notebook_entries，函数 `_list_question_bank_materials_sync`）
   - SQL: `SELECT source, material_id, COALESCE(NULLIF(MAX(material_title), ''), material_id, 'Unnamed material') AS material_title, COUNT(*) AS entry_count, COALESCE(SUM…`
   - 计划: SCAN notebook_entries USING INDEX idx_notebook_entries_review
   - 标记: index-scan-filter-not-covered
   - 建议: 沿索引序扫描后再过滤：过滤列不在该索引内；若结果集大，把过滤列并入索引或改用过滤列索引
51. **[LOW]** `deeptutor/services/session/sqlite_store.py:4219`（read，表: notebook_categories，函数 `_name_taken`）
   - SQL: `SELECT id FROM notebook_categories WHERE name = ? COLLATE NOCASE`
   - 计划: SCAN notebook_categories USING COVERING INDEX sqlite_autoindex_notebook_categories_1
   - 标记: covering-index-scan
   - 建议: 全量扫描覆盖索引：如结果集大，考虑收紧过滤或投影
52. **[LOW]** `deeptutor/services/workspace/data_migration.py:346`（read，表: turns，函数 `preview`）
   - SQL: `SELECT 1 FROM turns WHERE status IN ('queued','running','waiting_input') LIMIT 1`
   - 计划: SCAN turns USING COVERING INDEX idx_turns_session_status
   - 标记: covering-index-scan
   - 建议: 全量扫描覆盖索引：如结果集大，考虑收紧过滤或投影

## Top 缺口

1. `deeptutor/learning/storage.py:544`（`_ensure_initialized`） — full-scan-with-filter（表: mastery_topic_meta, mastery_paths）
2. `deeptutor/learning/storage.py:633`（`_converge_single_membership`） — full-scan-with-filter, index-scan-filter-not-covered（表: mastery_path_sessions）
3. `deeptutor/learning/storage.py:1834`（`detach_session`） — full-scan-with-filter（表: mastery_paths）
4. `deeptutor/multi_user/session_handoff.py:230`（`_cleanup`） — full-scan-with-filter（表: handoff_records）
5. `deeptutor/services/practice/storage.py:93`（`initialize_practice`） — full-scan-with-filter（表: practice_review_state, notebook_entries）
6. `deeptutor/services/session/sqlite_store.py:586`（`_migrate_turn_runtime_columns`） — full-scan-with-filter（表: messages, metadata, turns）
7. `deeptutor/services/session/sqlite_store.py:3428`（`_list_assessment_attempts_sync`） — full-scan-with-filter（表: assessment_attempts）
8. `deeptutor/services/web_source/repository.py:256`（`recover_interrupted`） — full-scan-with-filter（表: web_source_sync_jobs）

### 标记说明

| 标记 | 含义 | 默认级别 |
| --- | --- | --- |
| full-scan-with-filter | 裸全表扫描且带 WHERE 过滤（缺索引） | 大表 high / 小表 medium |
| full-scan-large-table | 大表无过滤全扫 | medium |
| temp-btree-order-by | ORDER BY 走临时 B-tree（大结果排序） | 大表 high / 其余 medium |
| temp-btree-group-by | GROUP BY 走临时 B-tree | medium |
| index-scan-filter-not-covered | 沿索引序扫描后再过滤（非堆扫） | low |
| covering-index-scan | 全量扫覆盖索引 | low/info |
| scan-subquery-materialize / catalog-probe / index-scan / full-scan / multi-index-or | 信息项 | info |

注：函数名以 `_migrate` 开头的访问点位于 schema 迁移路径，通常一次性执行，
清点中仍列出但优先级可下调。

## 去重边界

- `scan-persistence`：写持久化/原子性轴（WAL、fsync、事务边界）— 本卡不覆盖。
- `test-sqlite-store`：单模块行为测试 — 本卡为跨模块只读清点。
- `fix-storage-write-fsync`：写路径修复 — 本卡不改代码。
- 本卡输出仅为查询计划与索引缺口清单，不含任何 schema 变更。

## 复现

```bash
python3 evidence/scan-sql-query-plans-20261006/scripts/scan_sql_query_plans.py \
  --repo . --commit <sha> \
  --out evidence/scan-sql-query-plans-20261006
shasum -a 256 -c evidence/scan-sql-query-plans-20261006/SHA256SUMS
```

重跑输出逐字节一致（同一 checkout、同一 SQLite 版本下哈希自证）；报告与数据不含时间戳。
