# up-612 评估报告：用户数据长期持久化 —— SQLite vs PostgreSQL 可行性（只读评估）

- 日期：2026-10-06
- 对应上游 issue：HKUDS/DeepTutor#612（`[Question]: persistence问题，用户数据长期是否考虑数据库方案，如pg`，2026-07-07 创建；2026-10-06 核对仍为 open，无评论、无关联 PR、无 timeline cross-reference）
- 评估基线：origin/main @ `f07029cfc`（release: v1.6.13）
- 性质：只读评估，不改任何产品代码，未接触任何真实数据库

---

## 0. 结论摘要（TL;DR）

1. **#612 问的"要不要上 PG"，在今天不是一个单点决策。** DeepTutor 的用户数据面并不是"一个 chat_history.db"，而是：会话/题库主库（SQLite，约 13 张表）+ 11 个以上互相独立的 SQLite 库（mastery、reading catalog、usage ledger、cron、task board、workspace 注册表等）+ 大量 JSON/JSONL/Markdown 文件布局 + 内容寻址文件树（reading、附件、parse cache）+ FAISS/ LlamaIndex 向量索引。任何"数据库方案"只能覆盖其中结构化部分。
2. **现有"双实现"是事实上的不对称双轨，而非可互换后端。** `SessionStoreProtocol` 只覆盖会话核心；题库/评估/阅读奖励等 **38 个公开方法只存在于 SQLite 后端**，且约 45 个调用点直接绕过协议取 `get_sqlite_session_store()`。即使配置了 PocketBase，题库、练习（practice）、掌握度联动、仪表盘统计仍然落在本地 per-user SQLite 文件里。
3. **短期建议（回应 #612 的最小成本答复）**：维持"SQLite 默认 + PocketBase 可选"的现状，先做 §7 的 SQLite 加固项（收敛直接调用点、统一备份入口、busy/锁可观测性）。当前部署形态（单节点、`./data` 单树备份，docker-compose.yml:88-97）下 PG 的边际收益有限。
4. **中期建议**：若出现多实例水平扩展、多工作进程共享写、或跨设备同账号并发等真实需求，再启动 PG 方案（§6 的三阶段路线），且第一步是**先补协议缺口并冻结 schema 演进**，而不是直接搬数据。
5. PocketBase 路线（§3 方案 B）在并发正确性上弱于现有 SQLite 实现（无跨集合事务、活跃 turn 检查是读-判-写），不建议作为长期收敛目标，但可作为 PG 路线的"协议先行"参照。

---

## 1. 上游问题背景

#612 由用户 xiakj 于 2026-07-07 提出（Related Module: Dashboard），一句话：**"persistence 问题，用户数据长期是否考虑数据库方案，如 pg"**。这是一个开放性架构咨询，不是缺陷报告。核对时点（2026-10-06）：issue 仍 open、0 条评论、无关联 PR（timeline 无 cross-reference；全仓库唯一提及 "612" 的开放 PR #1597 是 partners 关键词猜测修复，无关）。

---

## 2. 现状盘点

### 2.1 后端选择机制

`get_session_store()`（`deeptutor/services/session/__init__.py:15-38`）按配置二选一：

- 配置了 `integrations.pocketbase_url` → `PocketBaseSessionStore`（按 url+scope 缓存实例，`__init__.py:31-37`）；
- 否则 → `SQLiteSessionStore`（默认、零配置，`__init__.py:38`）。

PocketBase 启用判定在 `deeptutor/services/pocketbase_client.py:42-44`；admin 账号来自 integrations 设置（`pocketbase_client.py:47-53`），客户端是**进程级共享的 admin 认证单例**（`pocketbase_client.py:56-108`）。

两后端共同满足 `SessionStoreProtocol`（`deeptutor/services/session/protocol.py:142-249`，257 行，纯结构化 Protocol）。

### 2.2 SQLite 后端（默认路径）

实现：`deeptutor/services/session/sqlite_store.py`（4453 行）。

**库文件与多用户隔离**：库路径来自 `PathService.get_chat_history_db()`（`sqlite_store.py:251-253`），即每用户一个 `<workspace>/user/chat_history.db`（`deeptutor/services/path_service.py:134-135`；用户根目录由 `deeptutor/multi_user/paths.py:36-39,102-106` 决定：admin=`data/`，普通用户=`data/users/<uid>/`，partner=`data/partners/<id>/`）。实例按解析后的绝对路径缓存（`sqlite_store.py:4422-4444`）。**隔离模型 = 文件系统级**：一个用户一个库文件。

**Schema（`sqlite_store.py:282-459` 单脚本建 10 张表 + practice 3 张表）**：

| 表 | 行号 | 要点 |
|---|---|---|
| `sessions` | 284-292 | id TEXT PK（应用生成 `unified_<ms>_<hex>`，`sqlite_store.py:1128`）；preferences/deleted_at 走 JSON 列与软删列（461-465） |
| `messages` | 294-309 | `id INTEGER AUTOINCREMENT`；`events_json/attachments_json/metadata_json` 全 JSON 列；`parent_message_id` 支持编辑分支（304-308） |
| `turns` | 321-336 | v2 并发契约列：owner_id/fencing_token/state_version/failure_code/retryable（562-608 迁移补列） |
| `turn_events` | 344-356 | `UNIQUE(turn_id, seq)`；事件溯源主表 |
| `notebook_entries` | 361-399 | 题库主表，`UNIQUE(origin_type, origin_ref, turn_id, question_id)`（398） |
| `assessment_attempts` | 407-423 | 不可变作答记录，mastery 联动（`linked_applied`） |
| `reading_quiz_pending/rewards` | 431-446 | 阅读测验暂存与星星奖励 |
| `notebook_categories` + 关联表 | 448-458 | 题库分类 |
| practice 三表 + 4 个触发器 | `deeptutor/services/practice/storage.py:30-89` | **与主库同文件**：由主库 schema 初始化时创建（`sqlite_store.py:516-518`），路由层直接拿 `store.db_path` 开 `PracticeStore`（`deeptutor/api/routers/practice.py:232,247,344,363`） |

**写入路径**：

- 所有同步方法经 `_run`：进程内 `asyncio.Lock` 串行化 + `asyncio.to_thread`（`sqlite_store.py:256, 1100-1102`）——单 asyncio 环境内写操作全串行。
- 每次操作新开连接，`timeout=30.0`、`PRAGMA busy_timeout=30000`、`foreign_keys=ON`、WAL（`sqlite_store.py:1104-1120, 281`）。WAL 允许跨进程读写并发（提交批事务时读者不被阻塞）。
- 关键事务：`begin_turn` 用 `BEGIN IMMEDIATE` 把"查活跃 turn + 插入"放进写事务，并靠部分唯一索引兜底竞态（`sqlite_store.py:1292-1338`；索引定义 640-646）；`transition_turn` 带 `expected_status`/fencing_token 乐观校验（1487-1519）；turn 事件批量落盘是一个事务（`_append_turn_events_sync`，1570-1594，注释明确"one transaction for the whole post-stream flush"以避免慢存储上逐事件 fsync）。

**并发限制（如实列出）**：

1. **单文件写多路复用**：同用户所有写入共享一个库文件 + 一个 asyncio.Lock；跨进程时依赖 WAL + busy_timeout(30s)。多 worker 部署写同一用户库时会排队，30 秒超时后报 `database is locked`（无重试包装）。
2. **schema 演进是"启动时自迁移"**：带跨进程 flock 锁（`sqlite_store.py:54-65, 257`），两次表重建迁移（notebook_entries origins 842-993、assessment_attempts 994-1082）用 `PRAGMA foreign_keys=OFF` + `BEGIN IMMEDIATE` + 整表复制。多版本进程混跑时靠锁避免互踩，但**迁移即启动延迟**，大库下更明显。
3. **无网络访问语义**：库在本机磁盘，任何"多实例/远程"部署都必须把 `data/` 树共享给所有进程（NAS 上有已知慢点，见 1576-1579 注释提到的 NAS 转盘分钟级尾延迟）。
4. **全 JSON 列、无服务端全文索引**：搜索是 `LIKE` + 转义（`sqlite_store.py:49-51`）+ Python 侧摘要（`search.py`），无 FTS5 使用。

### 2.3 PocketBase 后端（可选路径）

实现：`deeptutor/services/session/pocketbase_store.py`（1753 行）。设计契约写在文件头：每 turn 少量 HTTP 调用可接受（5-10ms 级），事件在终态提交前 flush（`pocketbase_store.py:4-13`），与 SQLite 共享同一持久性契约（DONE 不与上传任务赛跑、关机不丢 trace 行）。

**集合**：`scripts/pb_setup.py:157-291` 建 5 个集合——`sessions`、`messages`、`turns`（含 one-active-turn-per-session 唯一部分索引，207-237）、`turn_events`（`UNIQUE(turn_id, seq)`，241-263）、`knowledge_bases`（含 `raw_files` 文件字段，单文件 50MB/最多 99 个，267-290）。**RBAC 规则全部为空**，隔离全部在应用层（150-156）。

**隔离模型**：单共享服务器 + 进程级 admin 客户端，**没有文件级隔离**；每行按 `user_id` 过滤（`pocketbase_store.py:104-122`），所有 session 查找都经 `_find_session_record` 做 user_id + workspace 双重过滤（125-152、155-166；workspace 分区用 `preferences_json.workspace_id` 过滤表达式）。id 一律 `_VALID_ID` 白名单校验后才允许内插进 filter 字符串（41、68-71）。

**写入路径**：逐条 REST 调用（create/update/delete），**没有跨集合事务**（`import_legacy_session` 的 docstring 自述"PocketBase has no cross-collection transaction in the Python client"，补偿式 create-then-delete 回滚，`pocketbase_store.py:378-381`）。`add_message` 写消息后再更新会话时间戳（875-896），失败仅 warning 并返回 0（898-907）。

**并发限制（如实列出）**：

1. **活跃 turn 互斥是读-判-写**：先 `get_full_list` 拉 session 全部 turns 过滤活跃，再 create（`pocketbase_store.py:1247-1290`）。虽然 pb_setup 里建了唯一部分索引，但 SDK 路径不捕获唯一冲突转 `ActiveTurnConflict`（对比 SQLite 路径 1335-1338 的 IntegrityError 兜底）——两进程同时 begin 时理论上可产生双活跃行。
2. **transition/link 同样是读后写**（1450-1485、1519-1540），靠 state_version/fencing_token 字段做应用层乐观锁，但"读-判-写"之间无原子性。
3. **id/类型语义与 SQLite 分叉**：消息 id 是 PocketBase 字符串 record id（`add_message` 返回值，898-904），而 SQLite 是 INTEGER 自增；`parent_message_id` 因集合没有该列而塞进 metadata JSON（45-47、872-873）；时间戳 PocketBase 侧是 ISO 字符串需 `_to_float` 归一（92-101）。协议签名用 `int | str` 容忍了这种分叉（`protocol.py:127-137`）。
4. **每次调用是网络往返**：搜索/列表类方法（`search_sessions`、`usage_records` 等）在服务端分页逐页拉全量再在 Python 侧过滤/汇总（1026-1130），数据量大后放大为多次全量扫描。

### 2.4 关键事实：双实现是不对称的（对 #612 最重要的现状证据）

对两文件公开方法做差集（脚本统计，非人工目测）：

- **38 个公开方法只存在于 SQLiteSessionStore**，PocketBase 后端完全没有实现：题库/笔记本全家族（`list_notebook_entries`、`upsert_notebook_entries`、`question_bank_stats`、`list_question_bank_materials`、categories 全家族等）、评估作答（`record_assessment`、`append_assessment_attempt`、`list_assessment_attempts`、`pending_linked_assessments`…）、阅读测验（`put/get_reading_quiz_pending`、`upsert_reading_quiz_reward`、`reading_quiz_reward_totals`…）、`import_session`、`list_imported_sessions`、`get_message_path` 等。
- 反向仅 4 个 PB 私有辅助方法。
- 约 **45 个调用点直接 import `get_sqlite_session_store()` 绕过 `get_session_store()`**，包括：`api/routers/question_notebook.py`（15 处）、`api/routers/practice.py`（8+ 处）、`api/routers/reading_extensions.py`（3 处）、`api/routers/reading.py:462`、`api/routers/dashboard.py:192`、`api/routers/book.py:1144`、`api/routers/imports.py`（2 处）、`api/routers/sessions.py`（3 处直接用 + 其余走协议）、`services/courses_state.py:269`、`services/cron/executor.py:145`、`learning/assessment.py`（2 处）、`learning/topic_materials.py:276`、`book/inputs.py`（2 处）、`capabilities/mastery/tools.py:333`、`tools/question_bank.py:129-134`、`agents/question/history.py:56`、`agents/_shared/tool_composition.py:351`。

**含义**："配置 PocketBase = 数据进中央服务"是个误解。真实行为是：会话/消息/turn 进 PocketBase，而题库、练习状态、掌握度联动、阅读奖励、仪表盘统计仍写本机 per-user SQLite。两套持久化同时存在，长期数据被切在两个介质上。

### 2.5 数据面全景（除主库外的用户数据）

| 数据 | 技术 | 位置（scope） | 证据 |
|---|---|---|---|
| 掌握度/阅读进度 | SQLite `mastery.sqlite3`（10 表） | per-user `<workspace>/learning/mastery/` | `learning/storage.py:351,360-370,404-537` |
| 阅读 catalog | SQLite `_catalog.sqlite3`（6 表） | per-user `workspace/reading/` | `reading/catalog_store.py:57-63,81-163` |
| 阅读内容本体 | 内容寻址文件树（JSON+txt+媒体） | per-user | `reading/store.py:164-191` |
| practice 状态 | SQLite（共享主库文件） | per-user | §2.2 |
| 记忆 | Markdown + JSONL trace | per-user `memory/` | `services/memory/paths.py:48-90,73-74` |
| 附件 | 本地磁盘文件（Protocol 可插拔，S3 为 TODO） | per-workspace `chat/attachments` | `services/storage/attachment_store.py:13-19,21-26,105-124` |
| RAG 向量索引 | FAISS 二进制 / SimpleVectorStore JSON + BM25 | per-user `knowledge_bases/<name>/version-*` | `services/rag/pipelines/llamaindex/vector_store.py:23-25,44-50`；`rag/kb_paths.py:24-34` |
| 笔记本/协写/书引擎 | JSON 文件布局 | per-user `workspace/{notebook,co-writer,book,chat}` | `path_service.py:246-297,381-443` |
| 用户账号 | **JSON 文件 `users.json`**，进程内线程锁读改写 | 共享 `data/system/auth/` | `multi_user/identity.py:30-39,76-89`（30-35 注释自认多 worker 会竞态） |
| 审计 | JSONL | 共享 `data/system/audit/` | `multi_user/audit.py:18-22` |
| 会话接力/网页源同步 | SQLite（共享 system 树） | `data/system/` | `multi_user/session_handoff.py:34,203-216`；`services/web_source/scheduler.py:39` |
| usage 账本 | SQLite `usage.sqlite3` | owner-scope | `services/llm/usage_ledger.py:40` |
| cron 任务 | SQLite `jobs.sqlite3` | admin 共享 | `services/cron/service.py:413-416` |
| task board / workspace 注册表 / 活动流 / 文件库 / MN4 | 各自独立 SQLite | 各 scope | `services/task_board.py:64-72`；`workspace/catalog.py:54`；`workspace/activity.py:15-19`；`storage/file_library.py:100-102`；`capabilities/marginnote4/store.py:13` |
| 前端 | localStorage/IndexedDB（UI 草稿、失败重发） | 浏览器 | `web/shared/storage/store.ts:167-179`；`web/lib/workspace-drafts.ts:16-23` |

### 2.6 部署与备份现状

- docker-compose：PocketBase 是**可选 sidecar**（`ghcr.io/muchobien/pocketbase`，`./data/pocketbase`，docker-compose.yml:45-72）；Redis sidecar 仅做运行时协调，"业务数据留在 SQLite/PocketBase"（26-29）。
- 官方持久化/备份语义：**`./data` 单树挂载即备份单元**（docker-compose.yml:88-97；README.md:429-432；docs-for-user/CONTAINERIZATION.md:59-72,151-153,229-244）。
- PostgreSQL 在仓库中**零足迹**：代码、requirements、Dockerfile、docs 均无（唯一命中是 vendored MCP 目录里对 Neon-Postgres MCP server 的描述文案，`services/mcp/catalog/vendor/curated.json:895-896`）。
- README.md:933：PocketBase 定位是"single-user integration"，除非外接用户存储。
- 测试资产：`tests/services/session/test_sqlite_store.py` 1023 行 / 37 个测试（SQLite 后端）；PocketBase 有隔离与工厂测试（`test_pocketbase_isolation.py`、`test_session_factory.py`），但无 38 个缺口方法的对应面（本来也无实现可测）。

---

## 3. 方案对比

### 方案 A：维持现状（SQLite 默认 + PocketBase 可选）+ 加固

**内容**：不引入新数据库；承认"单节点 + 单 `data/` 树"是当前产品形态；做 §7 加固清单（收敛 45 个绕行调用点、备份入口、锁可观测性、PB 缺口面在文档里如实标注）。

- 收益：零迁移风险、零新运维面；与现有备份语义（拷 `data/` 树）一致；SQLite 路径的并发正确性（唯一索引 + IMMEDIATE 事务）是三案中最强的。
- 成本：多实例/多 worker 共享写的天花板保留（busy_timeout 30s 排队）；题库搜索仍是 LIKE；"长期数据"继续分散在 11+ 库和几十种文件布局里，跨库一致性无保证。
- 适用：桌面/单服务器自托管（当前主流用法）。

### 方案 B：收敛到 PocketBase（把题库等 38 个方法补齐到 PB 后端）

**内容**：补齐 PB 实现、把所有调用点改走 `get_session_store()`，让"中央数据库"= PocketBase（内嵌 SQLite，单进程）。

- 收益：一个已有的一等公民后端；部署仍单二进制 sidecar；多实例部署时数据集中。
- 成本/风险：
  - PB 后端并发语义弱于 SQLite 路径（§2.3：无跨集合事务、活跃 turn/transition 读-判-写、add_message 失败吞异常返回 0）；要补到同等强度需要大量改造，而 PB 的 SDK/过滤语言（数据全在 JSON 列、无服务端 join）会让题库的复杂查询（`question_bank_stats`、mastery 联动）退化为多次全量分页拉取 + Python 汇总（现状 `usage_records` 已是此模式，`pocketbase_store.py:1026-1130`）。
  - 38 个方法 × 网络 RTT 放大；每次 schema 演进要动 `pb_setup.py` 的幂等合并逻辑（`pb_setup.py:80-99`）。
  - 上游自身定位 PB 为单用户集成（README.md:933），账号仍在 `users.json`（§2.5），并未形成真正的多用户中央存储。
- 结论：**不推荐作为长期目标**；它的价值是给方案 C 当"协议先行"的练兵场（先把 38 个缺口从调用点挤回协议）。

### 方案 C：引入 PostgreSQL 作为统一结构化数据平面

**内容**：新增 `PostgresSessionStore`（实现补齐后的完整协议），用 `DATABASE_URL` 类配置选路；结构化用户数据（sessions/messages/turns/turn_events/notebook/assessment/practice/mastery/usage…）逐步归一到 PG；附件、阅读内容树、FAISS 索引仍留文件/对象存储（这些本质是 blob/文件，数据库化无收益）。

- 收益：
  1. **真正的多进程/多实例写并发**：MVCC 取代"WAL + asyncio.Lock + busy_timeout 排队"，多 worker 部署不需要共享 `data/` 树。
  2. **行级多用户隔离**替代"每用户一个库文件 / 每行 user_id 过滤"两种异构模型，账号与数据同域（可顺带解决 `users.json` 的多 worker 竞态，`identity.py:30-35`）。
  3. 服务端约束与迁移框架：部分唯一索引语义等价（活跃 turn 互斥）、JSONB + GIN 索引让 events/metadata 可查询、FTS/`pg_trgm` 取代 LIKE 搜索。
  4. 运维生态：备份/恢复/PITR/监控是成熟件，替代"拷目录"。
- 成本：
  1. 新增常驻服务与连接管理（pool、迁移工具如 Alembic 还是保持自迁移风格需要决策）。
  2. **迁移工程量大**：两套后端、三套语义（int vs str id、epoch REAL vs ISO 时间戳、parent 列 vs metadata JSON）要先统一；38 个缺口方法补齐是前置条件；`practice` 的 4 个 SQLite 触发器要改写为应用层或 PG 触发器。
  3. 桌面/离线用户需要退路（PG 不可达时回落 SQLite），意味着双后端要长期共存、双份测试。
  4. 与"单树备份"的产品承诺冲突：需要重新设计备份文档与工具。
- 适用：托管/多实例 SaaS 化、团队部署、跨设备同步诉求出现之后。

### 对比总表

| 维度 | A 现状+加固 | B 收敛 PB | C 引入 PG |
|---|---|---|---|
| 新增运维组件 | 无 | 无（已有 sidecar） | PG + 连接池 + 备份体系 |
| 多实例水平扩展 | 不支持（共享 `data/` 树 + 文件锁） | 弱（单进程 PB，HTTP 排队） | 强（MVCC 多写者） |
| 并发正确性 | 强（唯一索引 + IMMEDIATE） | 弱（读-判-写、无事务） | 强（等价约束可表达） |
| 38 方法缺口 | 保留（文档化） | 需全补（且查询退化） | 需全补（一次到位） |
| 数据迁移量 | 0 | 中（题库等入 PB） | 大（全结构化面） |
| 搜索/统计能力 | LIKE + Python 汇总 | filter 语言 + 全量分页 | JSONB/FTS/服务端聚合 |
| 备份语义 | 拷 `data/` 树（现成） | PB 数据目录 + 残余文件树 | PG 备份 + 文件/对象存储另行 |
| 与上游产品定位契合度 | 高（local-first） | 中 | 取决于是否走向托管服务 |

---

## 4. PG 方案（C）收益与成本明细

**收益**（按 #612 关心的"用户数据长期"视角）：

1. 长期数据的**单点可信来源**：题库、作答、练习、掌握度同库后，跨表一致性（现在靠 `linked_applied` 标志 + 迁移期修复，`sqlite_store.py:1085-1098`）可由外键/事务承载。
2. **并发模型统一**：删除"文件锁 + flock 迁移锁 + 30s busy 排队"这套为单机 SQLite 设计的机制（`sqlite_store.py:54-65,1112-1115`），多 worker 天然安全。
3. **可查询性**：events_json/metadata_json 转 JSONB + GIN，搜索与统计（`question_bank_stats`、`usage_records`）下推到服务端。
4. 为多用户服务化打底：账号（`users.json`）→ PG 表，审计 JSONL → 表，解锁 README:933 所述"external user store"路线。

**成本**：

1. 工程量：协议补齐 38 方法（两后端各自）+ id/时间戳/parent 语义统一 + 迁移工具（SQLite→PG 的 dump/import，含 WAL 库文件可能正在被写的停写窗口）+ 双后端共存期测试矩阵翻倍。
2. 部署：compose 增加 PG 服务；桌面形态要保留 SQLite 回落；文档与备份承诺重写。
3. 维护：4453 行 SQLite store + 1753 行 PB store 之外新增第三实现；或以 PG 为目标做"协议 v2 + 单实现"的收敛（推荐后者，见 §6）。

---

## 5. 迁移风险清单（若选 C）

1. **双写/切换窗口的数据分叉**：现有 `data/` 树里的 11+ SQLite 库与 PG 并存期间，任何一路写入未同步都会造成长期数据分叉；需要显式只读切换或双向同步工具（仓库目前没有）。
2. **id 语义不兼容**：SQLite INTEGER 自增 vs PB 字符串 id vs 应用生成 `unified_*`/`turn_*`；外键链（notebook_entries.session_id、turns.assistant_message_id）跨库迁移时需一次性映射表。
3. **JSON 列的历史脏数据**：`_json_dumps(default=str)` 会把不可序列化对象降级成 repr 字符串入库（`sqlite_store.py:42-46`）；`_json_loads` 对损坏行返回默认值（94-100）。迁移 importer 必须容忍这些历史行并保真搬运，不能在 PG 侧 JSONB 严格校验时炸掉。
4. **触发器/隐式行为**：practice 的 4 个 SQLite 触发器（`practice/storage.py:61-89`）在迁移后必须等价复刻，否则间隔重复状态悄悄漂移。
5. **per-user 文件树的引用完整性**：reading catalog（SQLite）指向内容寻址文件树；附件 DB 行引用磁盘文件。PG 化只搬 catalog 不搬文件（或反之）会得到"索引在、内容丢"的库。文件/blob 部分需要独立的对象存储迁移轨。
6. **多版本混跑**：现网"启动即自迁移 + flock"的模式在 PG 下变成迁移框架问题（前滚/回滚策略），比现在的一次性锁更需设计。
7. **桌面用户回落路径**：`data/` 单树离线使用是现产品能力，PG 不可达时的降级策略（只读？本地排队？）必须先定义，否则断网即不可用。
8. **PocketBase 存量数据**：已启用 PB 的部署（sessions/messages/turns/turn_events/kb 元数据在 PB 里）迁 PG 需要从 PB REST API 导出（无直连 SQL），并接受 §2.3 的弱一致历史数据（可能存在双活跃 turn 行等）。
9. **回归面**：题库/掌握度/阅读奖励的既有测试大多针对 SQLite 临时库（`tests/` 大量 `SQLiteSessionStore(db_path=tmp_path/...)`），PG 实现需要等价的测试基建（测试库容器或嵌入式 PG），CI 时长上升。

---

## 6. 分阶段建议（若决定走 C）

- **阶段 0（无风险，独立有价值，与 A 共享）**：
  - 把 45 个绕行调用点全部改为 `get_session_store()`，协议缺口在 PB 后端以显式 `NotImplementedError` + 文档呈现——"数据在哪里"从此只有一处真相。
  - 在协议层冻结 id/时间戳/parent 语义（例如全部字符串 id + epoch-float 时间戳 + 一等 parent 列），两后端对齐。
- **阶段 1（PG 后端最小可用）**：实现会话核心四表（sessions/messages/turns/turn_events）的 `PostgresSessionStore`，compose 可选 `postgres` profile；`DATABASE_URL` 存在即选路。迁移工具支持"空库起步 + SQLite 导入"单向。
- **阶段 2（结构化面归一）**：题库/评估/practice/mastery/usage 逐域搬 PG（每域独立开关、独立回滚）；users.json → PG 账号表；审计 JSONL → 表。
- **阶段 3（收敛）**：PB 后端标记 deprecated，SQLite 保留为离线/桌面回落；备份工具统一为"PG dump + 文件树打包"双轨。

每阶段独立可交付、可停在上一点；阶段 0 无论走不走 PG 都建议做。

---

## 7. 替代方案：继续 SQLite 的加固项清单（方案 A 的执行明细）

1. **收敛绕行调用点**（同阶段 0 第一条）：45 处 `get_sqlite_session_store()` 直连改走协议；PB 后端缺口方法显式抛错并写进文档，消除"配了 PB 但题库悄悄落本地"的隐性双写。
2. **备份一等公民化**：提供 `deeptutor backup`/`restore` CLI（对 11+ SQLite 库做 `VACUUM INTO`/`.backup` 热备 + 文件树打包），替代"直接拷目录"（WAL 模式下裸拷贝可能得到不一致快照——`-wal`/`-shm` 文件必须随行）。
3. **完整性巡检**：启动时或定期对各库跑 `PRAGMA integrity_check` + `quick_check`，结果进日志/健康端点。
4. **锁与忙等可观测**：`sqlite3.OperationalError`（database is locked）计数与耗时打点，暴露到 dashboard/日志，让"并发天花板到了"可见而非用户侧超时。
5. **题库搜索升级（可选）**：messages/notebook_entries 建 FTS5 虚表（内容不变、查询下推），或维持 Python 侧摘要但加缓存。
6. **迁移耗时治理**：两次整表重建迁移（`sqlite_store.py:842-1082`）在大库上可能秒级起步；加迁移耗时日志 + 版本号短路（已记录 `reading_schema`/`mastery_schema_migrations` 的做法可推广到主库）。
7. **users.json 多 worker 风险显式化**：文档标注单 worker 假设（`identity.py:30-35` 已有注释），或引入文件锁——这本来就不是 SQLite 主库的问题，但常被并入"持久化"讨论。
8. **PB 路径最小修正**（若保留 PB 选项）：`begin_turn` 捕获 PB 唯一索引冲突转 `ActiveTurnConflict`（与 SQLite 路径 1335-1338 对齐）；`add_message` 失败从"warning + 返回 0"改为可重试错误语义（`pocketbase_store.py:898-907`）。

---

## 8. 建议给 #612 的答复要点（供人决策）

> 当前 DeepTutor 的持久化是"local-first"设计：结构化数据在 per-user SQLite（会话/题库主库 + 若干功能库），内容类数据在内容寻址文件树，可选 PocketBase 只接管会话核心四表。单节点场景下这套设计成立，备份即备份 `data/` 目录。PostgreSQL 在多实例部署、多写并发、服务端搜索/统计、集中账号管理上有真实收益，但引入成本是"补齐协议缺口 + 统一两套语义 + 第三套实现与迁移工具"，建议作为托管/多实例形态的需求出现后的分阶段演进（先收敛调用点，再 PG 化结构化面），短期内以 SQLite 加固与备份工具化为主。

---

## 附：证据与统计口径

- 方法差集统计：对两 store 文件 `rg "^\s+(async )?def "` 提取方法名排序后 `comm` 差集（公开方法，剔除下划线私有与 dataclass 方法 `normalized/to_dict/call/close/pages/summarize` 归入 PB 侧辅助）。
- 绕行调用点统计：`rg "get_sqlite_session_store" deeptutor/` 去重文件级计数（2026-10-06，f07029cfc）。
- 上游核对命令：`gh issue view 612 -R HKUDS/DeepTutor`、`gh api repos/HKUDS/DeepTutor/issues/612/timeline`、`gh pr list --state all --search "612 in:body"`。
- 本评估未运行任何数据库、未启动任何服务；全部证据来自只读代码检索。
