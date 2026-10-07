# 会话持久化双后端导读（sqlite_store / pocketbase_store / 回收站）

- 基线：`origin/main` @ `f07029cfc`（v1.6.13），只读 worktree，未改任何代码。
- 范围：双后端读写路径、降级切换条件、schema 差异、回收站（`deleted_at`）链路；标注写点与状态字段不变式。
- 去重：guide-session（历史/内存轴）、scan-session-schema-drift（漂移清点轴）、test-sqlite-store / test-pocketbase-store（测试轴）各管其轴；本卡只覆盖双后端链路本身。§3 末的漂移点仅记录现象与锚点，不下修复结论。

所有路径相对仓库根；`pb_store` = `deeptutor/services/session/pocketbase_store.py`，`sqlite_store` = `deeptutor/services/session/sqlite_store.py`。

## 0. 后端选择与降级切换条件

- 唯一切换点 `get_session_store()`：`deeptutor/services/session/__init__.py:15-38`。`is_pocketbase_enabled()` 为真 → `PocketBaseSessionStore`（按 `scope.cache_key` 进程内单例，`__init__.py:33-37`）；否则回退 `SQLiteSessionStore`（`sqlite_store.py:4425-4430`，`_instances` 单例字典 `sqlite_store.py:4422`；跨 scope 变体 `get_sqlite_session_store_for` `sqlite_store.py:4433-4443`）。
- 切换条件是**纯配置**：`is_pocketbase_enabled()` 只判 `integrations.pocketbase_url` 非空（`deeptutor/services/pocketbase_client.py:42-44`，settings 组装 `:47-53`）。运行期**没有**"PB 宕机自动回退 SQLite"的逻辑。
- `ping_pocketbase()`（`pocketbase_client.py:164-196`）仅在 FastAPI 启动 lifespan 做一次健康检查（调用点 `deeptutor/api/main.py:316-318`），失败只打 warning（`:190-195`，文案提到 "fall back to SQLite"，实际并不改变 store 选择）。
- PB 已配置但不可用时各方法的失败语义（都不重试）：
  - 吞错返空/False：`list_sessions` → `[]`（`pb_store:618-620`）、`soft_delete` / `restore` / `hard_delete` → `False`（`pb_store:487-491` / `:506-510` / `:529-533`）、`add_message` → `0`（`pb_store:905-907`）、`get_turn_events` → `[]`（`pb_store:1747-1749`）、`update_session_title` → `False`（`pb_store:361-365`）。
  - 不吞错：`create_session` / `begin_turn` / `append_events` 直接抛（连接错误或 `ValueError`，`pb_store:271`、`:1290`、`:1712`）；`get_session` 吞异常返 `None`（`pb_store:279-283`）——读路径"故障表现为会话不存在"。
- 客户端单例：`get_pb_client()` admin 认证一次（`pocketbase_client.py:56-108`；未配置抛 `RuntimeError` `:70-73`，认证失败抛 `:92-97`）。
- 作用域：`StoreScope.cache_key = backend:resource:owner_id`（`deeptutor/services/session/scope.py:10-20`）；PB scope 的 resource 含 `url#workspace=<ws>`（`scope.py:29-36`）；SQLite 以解析后的 `db_path` 为 resource（`scope.py:44-50`）。`_captured_store_context`（`pb_store:50-65`）把外部创建的 store 钉死在创建者 scope，owner 不符直接 `ValueError`（`:60-61`）。
- 另一处同条件的分流：workspace 数据迁移层 `_backend()`（`deeptutor/services/workspace/data_migration.py:273-276`）同样按 `is_pocketbase_enabled()` 选边。

## 1. SQLite 后端读写路径

初始化与迁移：`__init__`（`sqlite_store.py:251-259`）→ `_initialize`（`:277-519`）：`PRAGMA journal_mode = WAL`（`:281`）；DDL：`sessions` / `messages` / `turns` / `turn_events` / `notebook_entries` / `assessment_attempts` / `reading_quiz_*` / `notebook_categories`（`:284-458`）；`deleted_at` 列按需 `ALTER TABLE` 补齐（`:464-465`）；跨进程迁移锁 `_migration_lock`（`:257`）。

写点（均为"同步函数 + `_run` 串行"结构，`_run` = `asyncio.Lock` + `to_thread`，`sqlite_store.py:1100-1102`；`_connect` 每次新连接，`busy_timeout=30000`、`foreign_keys=ON`，`:1105-1120`）：

- `create_session`：INSERT sessions（`sqlite_store.py:1122-1155`，写点 `:1135-1144`），id 形如 `unified_<ms>_<hex>`（`:1128`），preferences 写入 workspace_id（`:1130-1133`）。
- `add_message`：INSERT messages（`:1890-1956`，写点 `:1926-1944`）；`parent_message_id` 未传时自动接链尾、传 `None` 表示根（`:1909-1924`）；随后触碰 `sessions.updated_at`（`:1951-1954`）；返回自增 rowid（`:1956`）。
- `begin_turn`：`BEGIN IMMEDIATE`（`:1295`）→ 会话存在检查（`:1296-1300`）→ 活跃 turn 检查（`:1301-1316`，冲突抛 `ActiveTurnConflict` `:1313`）→ INSERT turns（`:1317-1334`）；并发竞态由部分唯一索引 `idx_turns_one_active_session` 兜底（建索引 `sqlite_store.py:642` 附近），`IntegrityError` 统一转 `ActiveTurnConflict`（`:1335-1338`）。
- `append_events`：单事务批量（`BEGIN IMMEDIATE` `:1582`，批量动机注释 `:1576-1579`）；`fencing_token` 校验（`:1588-1589`）；seq 幂等：同 seq 同内容放行、内容不同抛 `ValueError`（`:1608-1620`）。
- `transition_turn`：`BEGIN IMMEDIATE`（`:1488`）；`expected_status` / `fencing_token` 守卫（`:1494-1499`）；终态不可再迁移（`:1500-1501`）；`state_version + 1`（`:1506`）。
- 其他写点：`update_session_title`（`:1825-1826`，sync `:1800-1823`）、`update_summary`（`:2908-2922`）、`update_session_preferences` 读-合并-写（`:2924-2948`）。

读点：

- `get_session`（`:1247-1248`，sync `:1191-1245`）：`status` / `active_turn_id` / `capability` 由 turns 子查询派生（`:1203-1233`）；SELECT 不含 `deleted_at`。
- `list_sessions`（`:2758-2765` → `_list_sessions_sync` `:2728-2749`）：无 workspace 参数走 `_WHERE_NATIVE`；带参数时叠加 `json_extract(preferences_json,...)` 的 workspace/archived/parent 过滤（`:2736-2742`）。
- `search_sessions`（`:2886-2893`，匹配条件含标题+消息正文的字面 INSTR 搜索 `:2778-2790`）。
- `get_messages`（`:2557`）、`get_messages_for_context`（`:2628`）、`get_session_summaries`（`:2711-2726`）、`get_last_message`（`:2305-2308`）。

## 2. PocketBase 后端读写路径

全部方法走 `@_captured_store_context` + `asyncio.to_thread`，HTTP 直调（模块头设计注释 `pb_store:1-14`）。

写点：

- `create_session`：`sessions.create`（`pb_store:241-272`，payload `:257-267`：`session_id` / `user_id` / `session_created_at` / `session_updated_at` 等显式字段）。
- `add_message`（`:857-907`）：先 `_find_session_record` 校验归属（`:876-877`）→ `messages.create`（`:888`）→ 回写 `sessions.session_updated_at`（`:890-892`）；`parent_message_id` 无列，塞进 `metadata_json._parent_message_id`（常量 `:45-47`，写点 `:871-873`）；返回 PB record id 字符串（`:904`）。
- `begin_turn`（`:1231-1308`）：归属校验（`:1249-1250`）；活跃 turn 检查是**全量拉取后客户端过滤**（`:1252-1266`），无 SQLite 式 `BEGIN IMMEDIATE` 串行化，服务端唯一索引 `idx_turns_one_active_session`（`scripts/pb_setup.py:228-229`）是最后防线，但 `_create` 不捕获索引冲突转 `ActiveTurnConflict`。
- `transition_turn`（`:1431-1485`）：读-改-写非事务（`:1450-1476`）；`expected_status` / `fencing_token` 守卫（`:1459-1462`）；终态守卫（`:1463-1464`）；`state_version + 1`（`:1473`）。
- `append_events`（`:1631-1712`）：`fencing_token` 校验（`:1645-1652`）；全量拉既有 seq 后幂等合并（`:1654-1693`，内容冲突 `ValueError` `:1687-1688`）；content 截断 10000 字符（`:1683` / `:1703`）。注释块标明契约："同步持久化先于终态迁移"（`:1614-1616`）。
- 其他写点：`update_session_title`（`:344-365`）、`update_summary`（`:780-801`）、`update_session_preferences` 读-合并-写（`:803-834`）、`import_legacy_session` 无跨集合事务、失败逆序补偿删除（`:368-446`，补偿 `:432-439`）。

读点：

- `get_session`（`:274-288`）：`_find_session_record(recycled=False)`（`:281`）——回收站中的会话对 `get_session` 不可见。
- `list_sessions`（`:565-620`）：服务端 filter `deleted_at = null`（`:581`）+ 客户端二次防御过滤（`:613-617`，注释 `:610-612` 解释跨版本布尔过滤不可信）。
- `search_sessions`（`:623-670`）：同样服务端 `deleted_at = null`（`:641`）+ 客户端过滤 + 排除 `imported_` 前缀（`:644-650`）。
- `get_messages`（`:1139`）、`get_message_trace`（`:1543-1612`）、`get_turn_events`（`:1714-1753`）、`usage_records`（`:1026`）。

## 3. Schema 差异对照

| 维度 | SQLite（`sqlite_store.py`） | PocketBase（`pb_store` + `scripts/pb_setup.py`） |
| --- | --- | --- |
| 主键 | `sessions.id` TEXT PK（`:284-292`）；`messages` 自增 rowid（`:295`） | PB record `id` + 逻辑键字段 `session_id`（`pb_setup.py:165`），查询按 `session_id`+`user_id` 过滤（`pb_store:140-152`） |
| 级联删除 | FK `ON DELETE CASCADE`（`:296`、`:323`、`:346`），硬删一条 SQL 级联清空 | 无级联：`delete_session` 手动按序删 `turn_events`→`turns`→`messages`→`sessions`（`pb_store:454-465`，注释 `:458`） |
| 时间戳 | `created_at` / `updated_at` REAL 列 | 显式 `session_created_at` / `session_updated_at` / `turn_created_at` / `turn_updated_at` / `msg_created_at` / `event_timestamp` 字段（`pb_setup.py:173-174`、`:216-218`、`:196`、`:253`），读取时回退到 PB 系统字段 `created`/`updated`（`pb_store:310-321`、`:204-206`） |
| 消息树 | `parent_message_id` 整数列 + 索引（`:308`、索引 `:503-506`） | 无列，存于 `metadata_json._parent_message_id`（`pb_store:45-47`，注释"待集合 schema 升级"） |
| 行隔离 | 每用户独立 db 文件（路径服务决定，`sqlite_store.py:251-253`） | 单共享库，`user_id` 字段 + 每查询 filter（`pb_store:104-123` 设计注释）；collection rules 全空是有意的（`pb_setup.py:150-156`） |
| turn 并发 | `BEGIN IMMEDIATE` + 部分唯一索引（`:642`、`:602-608`） | 应用层检查 + PB 侧三个唯一索引（`pb_setup.py:226-231`） |
| 事件内容 | 无截断 | content 截断 10000 字符（`pb_store:1683`） |
| `add_message` 返回 | int rowid（`:1956`） | str record id（`:904`）；protocol 声明 `int | str`（`deeptutor/services/session/protocol.py:199-209`；类型放宽注释 `sqlite_store.py:1723`、`:1967-1969`） |
| schema 演进 | 启动时 ALTER TABLE 自迁移（`:461-480` 等） | `scripts/pb_setup.py` 幂等 sync 只补脚本内声明的字段/索引（`pb_setup.py:73-86`），无运行时迁移 |

**漂移点（现象记录，供 scan-session-schema-drift 轴确认）**：`pb_setup.py` 的 `sessions` 集合 schema 未声明 `deleted_at` 字段（字段列表 `pb_setup.py:164-175` 中没有），而 `pb_store` 全程读写它（写点 `:484` / `:503`、过滤 `:581` / `:641`、迁移 `:223-226`、序列化 `:323-340`、`_find_session_record` 判定 `:150-151`）。`_sync_existing_collection` 不会补声明外的字段（`pb_setup.py:73-86`），因此在未手工加列的部署上，PB 通常会忽略未知字段写入——`soft_delete_session` 可能返回 `True` 但行并未真正进回收站。需要在实际部署的集合上确认是否已手工补列。

## 4. 回收站（deleted_at）链路

**核心不变式**：`deleted_at` 为 NULL ⇔ 活跃会话；非 NULL ⇔ 在回收站。两后端都只用这一个列承载三态（活跃/回收站/物理删除），所有迁移都是带守卫的单条写、以影响行数判成败：

- SQLite 写点：
  - `soft_delete`：`UPDATE sessions SET deleted_at=? WHERE id=? AND deleted_at IS NULL`（`sqlite_store.py:1838-1845`）——重复进站返 False。
  - `restore`：`UPDATE ... SET deleted_at=NULL WHERE id=? AND deleted_at IS NOT NULL`（`:1851-1858`）——只有站内可恢复。
  - `hard_delete`：`DELETE ... WHERE id=? AND deleted_at IS NOT NULL`（`:1863-1870`）——**必须先进回收站才能物理删**（防跳过回收站，`:1873` docstring）。
  - `delete_session`：无守卫直删（`:1828-1836`），靠 FK 级联清 messages/turns/turn_events。
- SQLite 读侧：`list_deleted_sessions` → `WHERE s.deleted_at IS NOT NULL`（`:1876-1888`）；活跃列表与搜索一律排除回收站：`_WHERE_NATIVE` / `_WHERE_IMPORTED`（`:2689-2692`）、搜索条件 `s.deleted_at IS NULL`（`:2780`）。
- PocketBase 写点：
  - `soft_delete`：`_find_session_record(recycled=False)` + `update deleted_at=time.time()`（`pb_store:475-485`）。
  - `restore`：`recycled=True` + `update deleted_at=None`（`:493-504`）。
  - `hard_delete`：`recycled=True` 才删（`:512-527`，docstring `:516-518` 明示与 SQLite 对齐的防御）。
  - `delete_session`：手动级联（`:449-466`）。
- `recycled` 参数是回收站判定的单点：`_find_session_record`（`:125-152`，语义注释 `:134-138`：`False` 要求活跃、`True` 要求在站、`None` 不限）。
- PocketBase 读侧：`list_deleted_sessions` 全量拉取后客户端过滤 + 按 `deleted_at` 倒序（`:536-556`，`:539-541` 注释解释为何不用服务端布尔过滤）；活跃列表/搜索见 §2（`:581` / `:613-617` / `:641` / `:644-650`）。
- 可见性差异：PB 行序列化带 `is_deleted` / `deleted_at` 字段（`pb_store:339-340`）；SQLite 的 `get_session` SELECT 不含 `deleted_at`（`:1194-1233`）——同一 API 契约下该字段仅 PB 返回。
- 遗留语义升级（两后端一致）：启动迁移把"已 deleted"的旧会话改为 `preferences.archived=true` 并清 `deleted_at`——回收站语义收窄为软删，旧删除降级为归档：SQLite `_migrate_workspace_preferences`（`sqlite_store.py:521-547`，注释 `:523-527`）；PB `migrate_workspace_preferences`（`pb_store:189-238`，`deleted_at`→archived 分支 `:223-226`）。
- API 面：`deeptutor/api/routers/sessions.py` 回收站列表 `:289`、永久删除 `:467-510`、恢复 `:520-522`、清空（hard_delete）`:532`。
- 联动：回收站会话的问题库条目同步隐藏——`_NOT_RECYCLED_ENTRY_SQL`（`sqlite_store.py:119-122`）。

## 5. 状态字段不变式清单（含写点锚点）

1. `sessions.deleted_at`：三态迁移仅 soft/restore/hard 三条带守卫写（§4 锚点）；守卫全部下推到 SQL/filter 层；`archived` 与 `deleted_at` 的互斥由迁移收敛（§4 末条）。
2. `turns.status`：活跃集 `{queued,running,waiting_input}`、终态集 `{completed,failed,cancelled}`（`sqlite_store.py:123-125`、`pb_store:42-44`）；终态不可迁移（`sqlite_store.py:1500-1501`、`pb_store:1463-1464`）；单会话单活跃 turn：SQLite 唯一部分索引 + 竞态转 `ActiveTurnConflict`（`sqlite_store.py:1335-1338`），PB 应用层检查（`pb_store:1252-1266`）+ 服务端索引（`pb_setup.py:228-229`）。
3. `turn_events.seq`：`(turn_id, seq)` 唯一（SQLite `UNIQUE` `sqlite_store.py:355`；PB `idx_turn_events_turn_seq` `pb_setup.py:255-257`）；append 幂等：同 seq 同内容放行、异内容 `ValueError`（`sqlite_store.py:1615-1620`、`pb_store:1675-1693`）。
4. `fencing_token` / `state_version`：转移与追加都校验 token（`sqlite_store.py:1496-1499` / `:1588-1589`；`pb_store:1461-1462` / `:1645-1652`）；`state_version` 每次转移 +1（`sqlite_store.py:1506`、`pb_store:1473`）。
5. 持久化契约：DONE 事件发布前必须 flush 全部缓冲事件（`deeptutor/services/session/turns/lifecycle.py:683-687`、`:693-765`；两后端共享该契约的声明 `pb_store:10-13`）。
6. 排序键维护：SQLite `add_message` 触碰 `sessions.updated_at`（`sqlite_store.py:1951-1954`）；PB 对应触碰 `session_updated_at`（`pb_store:890-892`）——两侧列表排序键（`sqlite_store.py:318-319`、`pb_store:580`）。

## 验收对照

1. 双后端读写 / 降级切换 / 回收站链路均有 `path:line` 锚点（§0-§4）。
2. 未改任何代码：本分支只新增 `evidence/guide-session-stores-20261007/` 下文件。
3. 只推本卡新分支：`evidence/guide-session-stores-20261007`（基线 `origin/main` @ `f07029cfc`）。
