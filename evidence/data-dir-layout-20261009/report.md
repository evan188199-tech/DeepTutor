# 运行时数据目录布局契约清点（scan-data-dir-layout）

- 日期：2026-10-09
- 基线：origin/main @ `6cf793bd868ba5ecbe64722936d4be8fab5a01df`（release v1.6.14）
- 运行时 home：`/Users/Shared/DeepTutor`（`start_deeptutor.command` 以 `start --home "$PROJECT_DIR"` 启动）
- 数据根：`<home>/data`（`deeptutor/runtime/home.py:46-49`）
- 方法：以代码写入点为源建立契约，逐一比对实际目录名/文件名；只读名称，未读取任何数据内容；未修改任何代码或运行数据。
- 去重边界：本卡只覆盖"运行时数据目录布局"轴（scan-persistence 覆盖持久化机制，scan-tracked-artifacts 覆盖 git 跟踪产物）。

## 一、代码契约与实际比对（顶层）

锚点缩写：PS=`deeptutor/services/path_service.py`，MUP=`deeptutor/multi_user/paths.py`。

| 目录 | 用途 | 代码锚点 | 实际 | 处置 |
|---|---|---|---|---|
| `data/user/` | 默认单用户根（admin 的 user_data_dir） | PS:88-90,108；config/loader.py:26 | ✔ | 保留 |
| `data/users/<uid>/` | 每个非 admin 用户的工作区（scope root） | MUP:37,102-125 | ✔（u-1 及 7 个 `u_<hex32>`；u-1 命名早于当前 id 风格，观察项） | 保留 |
| `data/partners/<id>/` | 合作伙伴工作区（workspace/sessions/media/channels/users） | `deeptutor/partners/config/paths.py:18,38-89` | ✔（ada；`_souls.yaml`=manager.py:1550；`_runtime/status.sqlite3`=services/partners/runtime_status.py:18） | 保留 |
| `data/system/` | 部署级状态，永不挂入 sandbox runner | MUP:9-11,38,128-137 | ✔ | 保留 |
| `data/system/{auth,grants,audit,indexes,user-secrets}` | 账号/授权/审计/索引/owner 私钥 | MUP:128-137 | ✔ | 保留 |
| `data/system/user-mcp/<owner>.json` | owner 级 MCP 凭据 | `services/mcp/user_config.py:8,40` | ✔ | 保留 |
| `data/system/web-source-sync.sqlite*` | web 源同步任务库 | `services/web_source/scheduler.py:39` | ✔（-wal/-shm 为 SQLite 正常 sidecar） | 保留 |
| `data/system/migrations/` | 一次性迁移账本 | `multi_user/legacy_kids_learner_migration.py:99` | ✔ | 保留 |
| `data/knowledge_bases/` | KB 存储 | `api/routers/knowledge.py:137`；`services/base_sync.py:41` | ✔ | 保留 |
| `data/memory/` | v2 记忆根（trace/L2/L3/backup 分层） | PS:299-300；`services/memory/paths.py:1-10,69-74` | ✔（仅 L3+trace；L2/backup 懒创建，非偏差） | 保留 |
| `data/cron/` | cron 任务 SQLite（jobs.sqlite3 + wal/shm/migration.lock） | `services/cron/service.py:413`；`services/cron/repository.py:30-50` | ✔ | 保留 |
| `data/parse_cache/` | 内容寻址解析缓存 | PS:124-132；`tools/research_tools.py:46` | ✘ 未出现 | 懒创建，非偏差 |
| `data/learning_journal/` | 学习日志 | PS:302-307 | ✘ 未出现 | 懒创建，非偏差 |
| `data/bob_books_sight_words/` | 手工教材源（md+images，KB bob-books-sight-words 的源） | 无 | ✔ | 偏差 #1，用户内容不自动清理 |
| `data/learning_materials/` | 课程材料（inbound_sales_english_starter） | 无路径锚点（代码中仅函数名） | ✔ | 偏差 #2，不自动清理 |
| `data/tmp/` | —（内含整仓构建副本 issue-918-build） | 无 | ✔ | 偏差 #3，**可安全清理** |
| `data/translation/`（tasks.json） | 遗留任务清单 | 无（含 `git log -S` 检索） | ✔ | 偏差 #4，确认后可清理 |

## 二、`data/user/` 一层

| 路径 | 用途 | 代码锚点 | 实际 | 处置 |
|---|---|---|---|---|
| `user/.runtime/` | 活跃 run 私有状态 | PS:228-231 | ✔：workspaces.sqlite3（services/workspace/catalog.py:57）、workspace-activity.sqlite3（services/workspace/activity.py:19）、data-migrations/*adoption*.json（services/workspace/data_migration.py:91） | 保留 |
| `user/runtime/` | launcher 分离运行态 + web 缓存 | `runtime/launcher.py:65,78` | ✔（launcher.json/launcher.log；web/ 懒创建） | 保留 |
| `user/chat_history.db`(+`.migrate.lock`) | 会话库 + 迁移锁 | PS:134-135；`services/session/sqlite_store.py:63` | ✔ | 保留（锁为正常并发残留） |
| `user/logs/` | 运行日志（deeptutor.jsonl） | PS:455-456；`logging/configure.py:66` | ✔ | 保留 |
| `user/settings/` | 设置（json/yaml） | PS:225-226；`services/config/loader.py:26`；`services/config/launch_settings.py:80` | ✔ | 保留 |
| `user/workspace/` | 内容工作区 | PS:222-223 | ✔ | 保留（feature 见三） |
| `user/archive/legacy-chat/` | 会话迁移归档（ledger+pre-migration 快照） | `services/session/legacy_migration.py:48,149,278`；`app/container.py:225` | ✔ | 保留（备份残留约定） |
| `user/marginnote4/` | MarginNote4 库 | `capabilities/marginnote4/store.py:109` | ✔ | 保留 |
| `user/partner_groups/` | 合作组存储 | `services/partner_groups/store.py:57` | ✔ | 保留 |
| `user/usage.sqlite3` | LLM 用量账本 | `services/llm/usage_ledger.py:40` | ✔ | 保留 |
| `user/workspaces/`（ws_*） | 多工作区目录 | `services/workspace/catalog.py:64-65` | ✔ | 保留 |
| `user/update/` | 应用更新暂存 | `services/app_update.py:472` | ✘ | 懒创建，非偏差 |
| `user/cache/office_previews`、`user/visualizers/`、`user/partner_drafts/` | 预览缓存 / 可视化器 / 合作草稿 | `api/routers/file_preview.py:141`；`visualizers/store.py:50`；`services/partners/drafts.py:60` | ✘ | 懒创建，非偏差 |
| `user/data/` | 旧"嵌套 runtime home"残骸（内含旧 user/…、system、knowledge_bases、memory、partners） | 无（现被 `runtime/home.py:12-25` 显式拒绝） | ✔ | 偏差 #5，建议归档后人工清理 |
| `user/backups/nested-runtime/` | 嵌套布局手工备份 | 无 | ✔ | 偏差 #6，按备份策略人工处置 |
| `user/marginnote_sync/`（test-mn-kb.json） | 测试残留 | 无 | ✔ | 偏差 #7，**可安全清理** |
| `user/video_learning/`（remote.db） | 旧版视频学习存储（现行契约= workspace/timed_media + settings/video_learning.yaml） | 无 | ✔ | 偏差 #8，确认后可清理 |
| `user/research/`（*.md + deleted/） | 人工/代理研究笔记（现行研究产出契约= workspace/chat/deep_research/reports） | 无 | ✔ | 偏差 #9，用户内容不自动清理 |

## 三、`data/user/workspace/` feature 层

契约内且实际存在：`chat/{chat,deep_solve,deep_question,deep_research,math_animator,_detached_exec}`（PS:44-51,246-250,499-510）、`book/`（PS:410-450）、`co-writer/{tool_calls,audio,documents}`（PS:385-406,511-512）、`notebook/`（PS:290-297）、`reading/`（`reading/store.py:183`）、`timed_media/`（`video_learning/service.py:312`）、`learning/{mastery,archive}`（`learning/storage.py:360,1634`；`services/workspace/dependencies.py:194`）、`courses/`（`services/courses.py:254`）、`personas/`（`services/persona/service.py:103`）、`skills/`（`services/partners/workspace.py:235-406`）、`suggestions/`（`services/suggestions.py:162`）、`outputs/`（PS:176-181；`services/workspace/service.py:214`）、`immersive_reading/`（session_kind 工作区，`services/session/turns/request_preparer.py:266,719`；能力注册 `capabilities/registry.py:67`）。

| 路径 | 说明 | 处置 |
|---|---|---|
| `workspace/kids_reward_providers/`（stars.json） | 本地功能（kids 星星奖励），origin/main 无代码锚点 | 偏差 #10，功能在用则保留 |
| `workspace/chat/_detached_code_execution/` | 旧契约名（≤v1.6.5 曾存在，现行契约为 `_detached_exec`；HEAD 无锚点） | 偏差 #11，确认后可清理 |

## 四、repo 根部（data/ 之外）

| 路径 | 说明 | 处置 |
|---|---|---|
| `logs/`（api-server.log、web-server.log、rotate-*-tunnel.log） | 启动/隧道重定向日志，无应用代码写入点（launchd/运维层） | 偏差 #12，**可轮转清理** |
| `backups/`（plist 快照、版本升级快照、pre-release 备份等，命名带日期/事件） | 运维手工快照约定，无代码锚点 | 偏差 #13，按日期人工清理 |

## 五、备份残留约定（代码可证）

1. 迁移归档一律落 `archive/` 或 `.runtime/data-migrations/`：`archive/legacy-chat/`（ledger + pre-migration 快照）、mastery 迁移 `archive/`（`learning/migration.py:35`）、memory v1 归档 `memory/backup/<ts>/`（懒创建）。
2. 遗留树迁移不覆盖、残留原地保留并告警（`multi_user/paths.py:48-86`）。
3. 并发残留：`*.migrate.lock` / `*.migration.lock` / SQLite `-wal`/`-shm` 为正常副作用，无需人工清理。
4. 运维层备份（repo 根 `backups/`）纯手工命名约定，代码不管理。

## 六、偏差汇总

共 **13** 项（实际存在但 origin/main 无代码锚点）：

- ✅ 可安全清理（3）：#3 `data/tmp/`、#7 `data/user/marginnote_sync/`、#12 repo 根 `logs/` 内容
- ⚠ 人工确认后处置（6）：#4 `data/translation/`、#5 `data/user/data/`、#6 `data/user/backups/nested-runtime/`、#8 `data/user/video_learning/remote.db`、#11 `workspace/chat/_detached_code_execution/`、#13 repo 根 `backups/` 旧快照
- 🚫 用户/在用内容，不自动清理（4）：#1 `data/bob_books_sight_words/`、#2 `data/learning_materials/`、#9 `data/user/research/`、#10 `workspace/kids_reward_providers/`

反向偏差（代码声明、磁盘缺失）：0 项——`parse_cache`、`learning_journal`、`user/update`、`user/cache`、`user/visualizers`、`user/partner_drafts`、`user/runtime/web`、`memory/L2`、`memory/backup` 均为懒创建路径，属正常。

## 七、验收自查

1. 布局清单均有代码锚点（文件:行），偏差逐条列出 ✔
2. 未修改任何代码与运行数据；仅按名称列举目录/文件，未读取数据内容 ✔
3. 可安全清理目录已在第六节标注 ✔
