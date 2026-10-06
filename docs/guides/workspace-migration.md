# 工作区迁移子系统导读（workspace migration）

- 基线：origin/main `f07029cfc`（v1.6.13）。所有 `path:line` 以该提交为准，行号会漂移，定位以符号名为准。
- 范围：`deeptutor/services/workspace/` 下的两套迁移——**存储位置迁移**（`migration.py` + `catalog.py`，搬文件夹与登记）与**工作区数据迁移**（`data_migration.py` 系，搬功能数据与会话），以及依赖闭包、损坏源跳过、进度/恢复语义、与 session 存储的衔接。
- 去重说明：本卡只做只读取证。已知在修分支（未进 main，勿重复开卡）：`fix-migration-poll-ui`（UI 轮询吞错，见 §7.1）、`fix-session-migration-swallow`（session schema 迁移吞错，见 §7.2）、`fix-data-migration`（migrate_data 恢复预检/日志可读性，见 §7.3）、`myfork/fix/migration-deps-skip-warnings-158`（依赖闭包损坏源静默跳过，见 §6）。
- 不在范围：session 库自身的 schema 迁移（`services/session/sqlite_store.py` 的建表/改表链）、Learner 体验、KB 上传链路。

## 1. 总览：两套迁移，一套锁

```
存储位置迁移（storage move）   migration.py:35 migrate_locations
  入口：catalog.migrate_workspace / migrate_root ← HTTP /registrations/*/migrate
  对象：整个工作区文件夹（copytree + manifest 校验 + 原子 rename + catalog 事务提交）
  锁：catalog.metadata['migration']（maintenance，catalog.py:416）

工作区数据迁移（data move）    data_migration.py:552 migrate_data
  入口：HTTP /data/preview、/data/migrate、/data/export、/data/operations、recover
  对象：按 feature store（FEATURES 表，data_migration.py:28-48）+ 会话行
  锁：workspace-activity.sqlite3 排他租约（activity.py:12）+ 恢复期刊（_journal_root）
```

两套迁移互斥且都挡普通写入：`assert_available`（catalog.py:396-414）让运行期请求在存储迁移期间报错；`assert_no_pending_recovery`（data_migration.py:906-919）让所有数据写入在存在未恢复期刊时报错，经 `activity.acquire_activity`（activity.py:24-27，非排他读也检查）与 API 层（workspace.py:175-176、261-262）生效。

## 2. 迁移入口

### 2.1 HTTP（`deeptutor/api/routers/workspace.py`）

| 端点 | 位置 | 说明 |
|---|---|---|
| `GET /api/settings/workspace/data/discover` | workspace.py:90-94 | 列 feature store 文件数/字节/错误（data_migration.discover:220-270） |
| `POST .../data/preview` | workspace.py:97-103 | 依赖闭包 + blocker 检查（preview:308-424） |
| `POST .../data/migrate` | workspace.py:106-112 | migrate_data（异步线程跑，`_data_operation`:56-63 转 409） |
| `POST .../data/export` | workspace.py:115-124 | export_data（只读快照 + zip，:502-549） |
| `GET .../data/operations` | workspace.py:127-132 | 读期刊列表（operations:896-903），前端 5s 轮询 |
| `POST .../data/operations/{id}/recover` | workspace.py:135-139 | recover_operation（:922-978） |
| `GET .../data/exports/{id}` | workspace.py:142-154 | 下载 export.zip |
| `POST .../registrations/migrate-root` | workspace.py:201-203 | migrate_root（catalog.py:445-459） |
| `POST .../registrations/{id}/migrate` | workspace.py:206-210 | migrate_workspace（catalog.py:434-443） |

存储迁移外壳 `_migrate_workspaces`（workspace.py:166-198）：`data_activity(exclusive)` + `assert_no_pending_recovery` + `service.maintenance()`，内部先 `get_session_store().list_nonterminal_turns()`（workspace.py:181；sqlite_store.py:1470 / pocketbase_store.py:1412）挡进行中会话，再 `asyncio.shield` 保浏览器断开不弃拷贝（workspace.py:192-196）。学习账号 guardian 管控时全部拒绝（`_assert_migration_access`:80-87）。

### 2.2 服务层与启动

- `ContentWorkspaceService.migrate_workspace/migrate_root`（catalog.py:434-459）：前者搬单个登记工作区（session 行排除），后者搬所有 `follows_root` 且非 session 的工作区并写 `metadata['root']`。
- 启动数据迁移：`container.run_startup_data_migrations`（app/container.py:288-311）对每个本地用户跑 `migrate_legacy_bindings`（session_move.py:53-138）：把旧 `preferences_json.workspace_id` 改名为 `legacy_workspace_id` 并清空（一次性 marker `data-migrations/default-adoption-v1.json`，session_move.py:64），不搬文件。
- 单会话移动：`session_move.move_chat`（session_move.py:19-50）：跨工作区时走 `preview(session_ids={sid})` → 若闭包带出学习数据则拒绝，要求走完整数据迁移（session_move.py:26-30）；否则 `migrate_data(['chat'], session_ids={sid})`。
- KB 单体移动：`kb_move.move_kb`（kb_move.py:326-446）/ `preview_kb_move`（:86-165），见 §5.4。

### 2.3 前端

- 数据迁移页：`web/features/settings/sections/DataMigrationSettingsSection.tsx`（403 行）：discover/preview/migrate/export/recover 按钮（:141 run、:163 recover）、operations 5s 轮询（:108-114）。
- 工作区存储页：`web/features/settings/sections/WorkspaceSettingsSection.tsx`：单工作区迁移表单（:74）、根迁移（:148-151）；API 封装 `web/lib/workspaces-api.ts:117-124 migrateWorkspace`。

## 3. 存储位置迁移流程（文字版）

`migrate_locations`（migration.py:35-104）逐个 move：

1. 预检（:44-58）：source 存在、destination 不存在、互不嵌套、`_assert_allowed_root`（service.py:193-205，admin 豁免）。
2. 拷贝到兄弟暂存目录 `.<name>.migrate-<uuid>`（:59-62，`copytree(symlinks=True)`）。
3. 双向 manifest 校验（:63-66）：`_manifest`（:14-32）对 source/暂存各算一遍 sha256，拷贝期间源变化即抛 "files changed during migration"；特殊文件（fifo 等）抛 "Cannot migrate special file"（:31）。
4. 原子激活：`temporary.rename(destination)`（:68）——同目录 rename，源数据全程不动。
5. 事务提交（:74-99）：单条 `BEGIN IMMEDIATE` 内逐行核对 catalog 中 `path` 未被并发改动（:81-84），再写新 `path`、`follows_root`、追加 `previous_paths`；`new_root` 场景同时写 `metadata['root']`（:95-99）。任一失败 → 全部旧绑定仍有效。
6. 失败清理（:100-103）：删除暂存目录与已激活的 destination，重新抛出。

并发与中断：`maintenance()`（catalog.py:416-432）用 `BEGIN IMMEDIATE` 抢占 `metadata['migration']` 令牌，重复进入报 "Another workspace migration is already running"（:423）；`assert_available`（catalog.py:396-414）在本机进程死亡（`os.kill(pid,0)` → ProcessLookupError）时自动清锁（:400-411），异主机锁则一律拒绝迁移中提示。锁内新运行时上下文/建工作区均被挡（`create_runtime_context` service.py:306 先 `assert_available`；测试 tests/services/workspace/test_chat_workspaces.py:286-296）。

## 4. 数据迁移流程（文字版）

`migrate_data`（data_migration.py:552-708），前置 `data_activity(exclusive)` + `assert_no_pending_recovery`（:557-558）：

1. 附件物化（:559-568）：选 chat/attachments 时 `LocalDiskAttachmentStore.materialize_all_sessions()`。
2. `preview` 重算（:569-571）：依赖闭包（§5）+ blocker 全清才继续，否则原样抛全部 blocker（:570-571）。blocker 源：feature 读取错误（discover 行 error，:331）、共享资源 grants（`_shared_source_blockers`:279-305）、KB 分配（resources.py:204-223 `knowledge_migration_blockers`）、目标归档/同源、活跃 turn（sqlite :343-349 与 pocketbase :352-366 双查）、目标 ID 冲突（:372-388）、目标已含同名 artifact / 非空 feature（:389-403，`_empty_scaffold`:124-142 认定"仅空 schema 库"可覆写）。
3. 建期刊目录 `_journal_root()/<op-id>`（:577-579；runtime_state/data-migrations，:88-91），写 `operation.json`，状态机 `preparing → copying → transferring → committed → completed`（:582/:611/:647/:662/:678），每步 `atomic_write_json` 落盘；`installed_paths` 在创建目标前先记入期刊（:624-632）。
4. 拷贝（:592-646）：`_snapshot`（:145-174）把源快照进期刊——SQLite 走 `backup()`（含 WAL，:158-165）+ `integrity_check`，普通文件 copy2 + 双向 sha256（:167-172）；符号链接直接拒绝（`_files`:94-113）。部分选择（artifact_files）按清单装，整 store 选择先 `rmtree` 目标空壳（:620-623）。
5. URL 重绑（:641-646 → `_rebind_feature_urls`:789-832）：对 json/md/html 文本与 SQLite TEXT 列把本地下载 URL 加/改 `dt_workspace=<target>`（references.py:13-20 `_LOCAL_URL` 覆盖 /files/attachments|outputs|workspace-items/ 与 /api/reading|video-learning/）；presentation manifest 同步改 `data_workspace_id`（:806-809）。
6. 会话转移（:649-661）：pocketbase 走 `_pocketbase_rebind`（:751-786，逐行 update + 回读校验）；本地 SQLite 走 `transfer_sessions`（session_transfer.py:19-140）。
7. 提交后清源（:664-677）：只有过了 committed 才删源 feature（部分选择逐文件删，presentation blobs 保留——可能被未迁移项引用，:671-672），最后 `_clear_store_caches`（:981-988，重置 learning/sqlite_store/file_library 缓存单例）。
8. 导出（`export_data`:502-549）复用同一条快照路径产 zip，不动源。

## 5. 依赖闭包与"搬多少"

`dependency_closure`（dependencies.py:26-86）：不动点迭代，输出 (features, session_ids)。

- 正向：选中 feature 所属会话（MODES 表 :8-12 映射偏好 `workspace_mode`）、后代会话（`parent_session_id` :123）、历史引用（`history_references` :127-131）、各引用键 → feature（:132-145）；book/learning/reading 等专属扫描（:148-207）：book JSON 的 page_chat_sessions/chat_selections（:150-156）、mastery.sqlite3 的 `mastery_path_sessions`/`mastery_topic_sources`（:165-189）、reading `_catalog.sqlite3` 的 `reading_workspace_sessions`（:194-206）、notebook/co-writer/timed_media/courses 目录 JSON 递归收集（:207-216 `_collect_references`:222-259）。
- 反向：普通会话引用了被选 store 或被选会话 → 一并搬（:59-78）。
- 历史快照兜底：`_with_historical_references`（:286-349）从 messages.metadata_json 与 notebook_entries.followup_session_id 挖旧引用（camelCase 别名表 :289-300），pocketbase 走 `_pocketbase_snapshot`（data_migration.py:711-748）。
- 选中任何会话时强制带 `chat/outputs/presentations/attachments`（data_migration.py:322-324）；`presentations` blob 缺失即 blocker（`_selected_artifact_files`:486-497 "A presented file is missing"）。

## 6. 损坏源跳过（main 现状 = 静默跳过）

main 上三处 `except …: continue` 会**静默**丢弃损坏源，闭包随之少搬（session/引用丢失风险）：

| 位置 | 跳过内容 | 行为 |
|---|---|---|
| dependencies.py:104-107 | 损坏 book manifest/inputs JSON | 不加入 books 列表，其会话/引用不进闭包 |
| dependencies.py:212-215 | 损坏 feature 文档（notebook/co-writer/timed_media/courses 的 *.json） | 该文档内引用全部丢弃 |
| dependencies.py:326-328 | 损坏 messages.metadata_json | 历史引用兜底对该会话失效 |

`data_migration.discover`（:241-251）会把单 feature 的 OSError/WorkspaceError 记成 error 行并进 blocker（preview :331），这是"损坏即拦"的主通道；但依赖闭包内部的跳过无任何信号。修复分支 `myfork/fix/migration-deps-skip-warnings-158`（8417007e5/c80580b13）给 `dependency_closure` 加 warnings 列表 + preview `warnings` 字段，**未进 main**，补测/修卡请在该分支基础上续作。

## 7. 进度与恢复语义

### 7.1 数据迁移期刊（权威状态源）

`operation.json` 是唯一进度载体：`operations()`（data_migration.py:896-903）扫目录倒序返回；前端 5s 轮询 `/data/operations` 渲染状态与 Recover 按钮（DataMigrationSettingsSection.tsx:108-114、:383-396）。已知缺口：轮询与首载 `.catch(() => {})` 吞掉全部错误（:113、:136），后端持续失败时 UI 停在旧状态——`fix-migration-poll-ui`（f121764fc）修此，未进 main。

### 7.2 失败/恢复路径清单（data_migration.migrate_data）

| 状态 | 触发 | 自动行为 | 恢复动作 |
|---|---|---|---|
| preparing/copying 失败 | 快照/校验抛错（:682-708） | `_remove_installed`（:843-861，路径必须逐条命中期刊 allowed 集，否则拒删）→ `failed`，源完好 | 无需恢复 |
| transferring 失败 | 会话转移抛错 | `_restore_sessions`（:879-893）：pocketbase 回滚 rebind（target_id=None），sqlite 用期刊备份还原源库；目标库若无备份且是本次新建则整库删除（:889-893）。还原失败 → `recovery_required` | `recover_operation`（:922-978）再走 `_restore_sessions` + `_remove_installed` → `recovered` |
| committed 后失败 | 清源阶段抛错 | 状态 `cleanup_required`，双份保留 | `recover_operation` 的 cleanup 分支（:939-969）：先 `cleanup-check` 复核源未被改动（:947-959，不等则要求人工 reconcile），再删源 → `completed` |
| 阻塞新数据 | 任一期刊处于 pending 集合 | `assert_no_pending_recovery`（:906-919）拒绝写入（activity.py:24-27、workspace.py:175-176/261-262、session_move.py:70） | 打开 Settings → Data migration 执行 Recover |
| 下载/操作 ID 校验 | `recover_operation`/`export_path`（:924/:992）限 32 位 hex | 404/409 | — |

### 7.3 会话库级（衔接 sqlite_store）

session schema 迁移中 `ALTER TABLE sessions DROP COLUMN kind` 吞掉一切 `OperationalError`（services/session/sqlite_store.py:468-471），老 SQLite 的良性失败与"库被锁"这类真失败不可区分——`fix-session-migration-swallow`（4dc65ef43）分类处理，未进 main。另有一串 `fix(migration): block migrations on unreadable operation journals`（b9fdad765→98b732f75）收紧 `operation.json` 不可读时的 migrate_data 行为，也未进 main，与 `fix-data-migration` 去重时一并核对。

## 8. 与 session 存储的衔接

- 数据路径：会话库 `chat_history.db` 由 `PathService.get_chat_history_db`（services/path_service.py:134-135）给出；显式工作区下 `WorkspacePathService`（workspace/context.py:104-143）把 feature 数据切到 `<workspace>/.deeptutor/data`，运行态/设置仍账号级（:126-132）。
- 双后端：`_sessions`（data_migration.py:186-217）合并 sqlite 与 pocketbase 会话（quizzes 等仍留本地库，:213-216）；`_backend()`（:273-276）随 `is_pocketbase_enabled` 切换。
- 行级转移：`transfer_sessions`（session_transfer.py:19-140）单事务 `ATTACH target` + `BEGIN IMMEDIATE`（:32-34）；活跃 turn 拒绝（:38-42）；目标缺列时 `ALTER TABLE ADD COLUMN` 补齐（:69-80，跨 schema 版本保留扩展字段）；逐行回读校验 + 计数校验（:104-117）；转移即删除源行（notebook/assessment 先显式删再删 session，:122-128）；主键冲突整体回滚（:131-135）。偏好内写 `workspace_id`（:89-93）并逐值 rebind URL（:86-88）。
- 运行中保护：存储迁移外壳挡 `list_nonterminal_turns`（workspace.py:181-185）；preview 双查 sqlite/pocketbase 活跃 turn（data_migration.py:343-366）。
- 迁移后缓存：`_clear_store_caches`（data_migration.py:981-988）丢弃已初始化的 sqlite_store/learning/file_library 单例，防止旧路径继续写入。
- 启动衔接：`migrate_legacy_bindings`（session_move.py:53-138）在 `run_startup_data_migrations`（container.py:288-311）中按用户执行，PocketBase 重试靠 `default-adoption-backup.json` 合并去重（session_move.py:77-83）；marker 写入前先 `assert_no_pending_recovery`（:68-70）。

## 9. 关键文件表

| 文件 | 角色 | 关键符号 |
|---|---|---|
| deeptutor/services/workspace/migration.py | 存储位置拷贝/校验/激活 | `migrate_locations`:35，`_manifest`:14 |
| deeptutor/services/workspace/catalog.py | 登记/内建工作区/锁/入口 | `migrate_workspace`:434，`migrate_root`:445，`maintenance`:416，`assert_available`:396，`_catalog_connection`:81 |
| deeptutor/services/workspace/data_migration.py | 数据迁移全流程 | `migrate_data`:552，`preview`:308，`discover`:220，`_snapshot`:145，`recover_operation`:922，`assert_no_pending_recovery`:906，`_journal_root`:88 |
| deeptutor/services/workspace/dependencies.py | 依赖闭包 | `dependency_closure`:26，`_forward_closure`:89，`_with_historical_references`:286 |
| deeptutor/services/workspace/session_transfer.py | 会话行级转移 | `transfer_sessions`:19 |
| deeptutor/services/workspace/session_move.py | 单会话移动 + 启动收编 | `move_chat`:19，`migrate_legacy_bindings`:53 |
| deeptutor/services/workspace/kb_move.py | KB 单体移动 | `move_kb`:326，`preview_kb_move`:86，`_rebase_llamaindex_paths`:233 |
| deeptutor/services/workspace/references.py | 本地 URL 重绑 | `rebind_local_urls`:13 |
| deeptutor/services/workspace/activity.py | 跨进程读写租约 | `acquire_activity`:12，`workspace_writer`:48 |
| deeptutor/services/workspace/context.py | 数据作用域 | `workspace_context`:90，`resolve_workspace_scope`:65，`WorkspacePathService`:104 |
| deeptutor/services/workspace/snapshot.py | 系统工作区只读快照 | `write_snapshot`:121（迁移跟随系统工作区，snapshot.py:1-6 非权威） |
| deeptutor/api/routers/workspace.py | HTTP 入口 | §2.1 表；`_migrate_workspaces`:166 |
| deeptutor/app/container.py | 启动迁移 | `run_startup_data_migrations`:288 |
| web/features/settings/sections/DataMigrationSettingsSection.tsx | 数据迁移 UI | 轮询:108-114，run:141，recover:163 |
| web/features/settings/sections/WorkspaceSettingsSection.tsx | 存储迁移 UI | 单工作区:74，根迁移:148-151 |

## 10. 测试现状与空白

已覆盖（`timeout 900 python -m pytest -q tests/services/workspace tests/multi_user/test_kb_move.py tests/api/test_workspace_router.py tests/app/test_startup_data_migrations.py`）：

- `tests/services/workspace/test_data_migration.py`（18 例，434 行）：消息/分支/问题保全与源备份（:40）、活跃 turn 与冲突目标拒绝（:105）、导出校验和与符号链接排除（:129）、反向依赖（:149）、move_chat（:171）、transferring 崩溃还原双库（:200）、copying 崩溃按期刊清目标（:232）、启动收编（:258/:405）、活动租约互斥（:274）、历史数据保留（:287）、附件根迁移（:313/:338）、空 feature 覆写（:376）、旧请求快照引用（:418）。
- `tests/services/workspace/test_chat_workspaces.py`：根/单工作区迁移保全文件与 URL（:228）、失败迁移保源保绑定（:258，manifest 篡改注入）、迁移期挡新上下文（:286）、系统快照（:298）、skill 服务跟随迁移（:356）。
- `tests/multi_user/test_kb_move.py`（14 例）：字节保全、冲突拒动、发布失败全量回滚（:113）、legacy 别名私有性、MarginNote 阻断（:244）、LlamaIndex 引用与图片（:263）等。
- API 层：`tests/api/test_workspace_router.py:160` 挡活跃 turn 与保绑定。

空白（可拆卡，均标注 main 未覆盖）：

1. **recover_operation 的 committed/cleanup_required 分支零测试**（data_migration.py:939-969）：cleanup-check 复核不等 → "retain both copies and reconcile manually"（:956-959）无任何用例；`cleanup_required` 字符串在 tests/ 下 0 命中。→ 拆卡：注入"提交后清源失败"，验证期刊复核与二次 recover。
2. **依赖闭包损坏源静默跳过无警告**（dependencies.py:104-107、:212-215、:326-328）：损坏 manifest/文档/metadata 时闭包缩水且无信号。→ 与 `myfork/fix/migration-deps-skip-warnings-158` 去重后续作 + 补三处单测。
3. **`_rebind_feature_urls` 的 SQLite TEXT 列重绑分支无直接测试**（data_migration.py:812-832）：现仅 test_data_migration.py:196 一处断言消息 content 重绑（走 transfer_sessions）；reading/video-learning URL、presentation manifest `data_workspace_id`（:806-809）无用例。
4. **`migration.py` 特殊文件/中断窗口**：`_manifest` 的 "Cannot migrate special file"（:31）与 rename 与 catalog 提交之间进程死亡（:68-99）无注入测试；仅 :258 覆盖 manifest 不等分支。
5. **异主机迁移锁**：`assert_available` 只清本机死进程锁、异主机永久拒绝（catalog.py:400-414），无测试锁定残留（如容器主机名变化后）的解锁/告警路径。
6. **`migrate_root` 对 `kind=session`/外部路径工作区的跳过语义**（catalog.py:453-457 只搬 `follows_root`）缺"自定义路径不动"的显式断言（test_chat_workspaces.py:228 间接覆盖一半）。
7. **UI 轮询吞错**（DataMigrationSettingsSection.tsx:113、:136）与 `list_nonterminal_turns` PocketBase 分支在迁移外壳下的行为（workspace.py:181），web 侧无 spec（web/tests 仅有 partner-continuity/chat-workspace-binding 等）。
8. **`session_move.migrate_legacy_bindings` 损坏 preferences_json**：sqlite 分支 `json.loads(raw or "{}")`（session_move.py:118）遇坏行会令整个收编抛异常且不写 marker，启动反复重试——无损坏行用例。

## 11. 快速命令

```bash
timeout 900 python -m pytest -q -p no:cacheprovider \
  tests/services/workspace/test_data_migration.py \
  tests/services/workspace/test_chat_workspaces.py \
  tests/multi_user/test_kb_move.py tests/api/test_workspace_router.py \
  tests/app/test_startup_data_migrations.py
```
