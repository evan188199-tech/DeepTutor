# DeepTutor 持久化层现状扫描与 PostgreSQL 方案评估

回应上游 issue：HKUDS/DeepTutor#612「persistence问题，用户数据长期是否考虑数据库方案，如pg」
基线：`origin/main` @ `f07029cfcf2c8dfccdb671cdfc343db8334f5741`（v1.6.13）
日期：2026-10-04 · 性质：只读评估，未改任何代码 · 所有引用均为仓库相对路径 `path:line`

---

## 1. 结论先行

**建议：不迁 PostgreSQL；把工程投入放在统一 schema 版本管理、无界增长治理和一致性备份上。仅当部署形态升级为"多实例共享数据/托管多租户服务"时，再按本报告 §5.3 的分阶段路径引入 PG。**

理由概述：DeepTutor 当前的持久化主体是 4 个按用户/按域拆分的 SQLite 库 + 大量内容寻址文件树，配合单容器 Docker 部署。这一形态与 SQLite 的能力区间高度匹配：每用户一个 `chat_history.db` 天然规避了写并发热点（`deeptutor/multi_user/paths.py:102-125`），WAL + 30s busy timeout 已覆盖常见并发（`deeptutor/services/session/sqlite_store.py:1112-1115`）。真正的长期风险不是"SQLite 不够用"，而是 schema 版本管理不统一、多处无界增长、多进程锁纪律不一致、以及跨库备份没有一致快照点。这些风险迁 PG 并不能自动解决（turn_events 换成 PG 表照样无 TTL），反而会引入新的运维面。

---

## 2. 存储面清单（每项含 path:line）

### 2.1 聊天会话主库（核心用户数据）

- 引擎：SQLite WAL（`deeptutor/services/session/sqlite_store.py:281`，连接参数 `:1112-1115`）。
- 路径：`<data/user>/chat_history.db`（`deeptutor/services/path_service.py:134-135`）；每用户独立 DB 文件（`deeptutor/multi_user/paths.py:102-125`）。
- 表：`sessions`/`messages`/`turns`/`turn_events`（`deeptutor/services/session/sqlite_store.py:284-356`）、`notebook_entries` 及分类（`:361-458`）、`assessment_attempts`（`:407-429`）、阅读测验待答与星星奖励 `reading_quiz_pending`/`reading_quiz_rewards`（`:431-446`）、练习题库由 `deeptutor/services/practice/storage.py:25` 注入。
- 后端选择：默认 SQLite；配置 PocketBase 后切换（`deeptutor/services/session/__init__.py:15-38`，协议双实现 `deeptutor/services/session/protocol.py:143-249`）。
- 风险：schema 升级是 `__init__` 内联 ALTER/整表重建、无 schema 版本表（对比学习库的 `mastery_schema_migrations`，`deeptutor/learning/storage.py:477-480`）；大迁移在启动路径上执行（`sqlite_store.py:843-992, 995-1082`）；`turn_events` 只在单轮内清理、无全局 TTL（`:2235-2237`）；回收站行保留到手动硬删（`:1838-1888`）。

### 2.2 PocketBase 会话后端（可选）

- 集合：`sessions`/`messages`/`turns`/`turn_events`（`deeptutor/services/session/pocketbase_store.py:140,200,254,352`；建集合脚本 `scripts/pb_setup.py:157-297`）。
- 配置：`integrations.pocketbase_url/_admin_email/_admin_password`，默认值 `deeptutor/services/config/runtime_settings.py:93-97`，env 覆盖 `:904-913`，凭据明文落 `settings/integrations.json`（`:549-551`）。
- 隔离：全部查询按 `user_id` 过滤（`pocketbase_store.py:104-122`）；工作区用 `preferences_json.workspace_id` 分区（`:155-166`）。API 规则按设计留空、隔离完全依赖应用层（`scripts/pb_setup.py:156,176,198` 的自注）——部署上不得把 PB 端口暴露到应用之外。
- 风险：无 schema 升级机制，靠读时归一化（`pocketbase_store.py:332-335`）；无跨集合事务，导入靠补偿删除（`:367-382`）；每次会话查询 `get_full_list` 全表扫（`:140-144`）；消息父子关系藏在 JSON metadata `_parent_message_id`（`:45-47, 871-873`）。

### 2.3 学习模块 Mastery Path

- 引擎：工作区级 SQLite WAL（`deeptutor/learning/storage.py:405, 653-664`）。
- 路径：`<workspace>/learning/mastery/mastery.sqlite3`（`:351, 358-361`）。
- 表：`mastery_paths`/`mastery_path_sessions`/`mastery_interactions`/`mastery_events`/`mastery_learning_evidence`/`mastery_schema_migrations`/`mastery_path_leases`/`mastery_topic_meta`/`mastery_topic_sources`（`:407-507`），另含阅读进度 `reading_progress`/`reading_activities`（`:515-536`，写入口 `:1291, 1370`）。
- 迁移：V1→V2 单向目录迁移带进程 flock、WAL checkpoint、原子复制、SHA-256 manifest、V1 归档（`deeptutor/learning/migration.py:174-311`）；首个具名迁移 `learning_evidence_projection_v1`（`storage.py:565-598`）。
- 风险：`mastery_events` 随修订无界增长、无压缩；阅读进度寄居在学习库（跨模块耦合，影响备份切分）；首次建表的锁是进程内线程锁（`:50-51, 390-404`），多 worker 首启可能竞态 executescript。

### 2.4 阅读模块

- 内容库：内容寻址目录树 + 逐状态 JSON，原子写 + 线程级可重入锁（`deeptutor/reading/store.py:61, 176-177, 241-249`）；布局 `manifest/outline/units/raw/media/annotations/positions/bookmarks/revisions`（`:66-83`）。
- 目录库：SQLite `_catalog.sqlite3`，无 WAL、30s timeout（`deeptutor/reading/catalog_store.py:54-75`）；表 `reading_materials`/`reading_workspaces`/`reading_workspace_materials`/`reading_workspace_sessions`/`reading_session_links`（`:85-162`）；版本管理是单行 `reading_schema` 表（`:81-83, 192`）。
- 风险：锁是线程级——多进程（多 uvicorn worker）下注释/书签的读-改-写会丢更新（原子改名只防损坏不防丢失）；注释/书签每次整文件重写（`store.py:73-75, 1315-1319`）；共享内容目录按 hash 复用，删除材料不删共享字节（`:1182-1200`）。阅读测验星星却存在聊天库（§2.1），一个功能横跨三个存储。

### 2.5 知识库 / RAG

- 注册表：`kb_config.json` 单文件读-改-写、原子保存（`deeptutor/knowledge/manager.py:333, 462-470`），根目录 `<workspace>/knowledge_bases`（`deeptutor/services/path_service.py:121-122`）。
- 索引：按嵌入签名分 `version-N/` 目录，内含 LlamaIndex `docstore.json`/`index_store.json`/`default__vector_store.json` 等（`deeptutor/services/rag/index_versioning.py:1-64`）；FAISS 二进制索引自定义字节写入（`deeptutor/services/rag/pipelines/llamaindex/vector_store.py:80-97`）；LightRAG 在每 KB `working_dir` 写 KV/向量/图（`deeptutor/services/rag/pipelines/lightrag/storage.py:50-56`）。
- 镜像：KB 元数据尽力同步到 PocketBase `knowledge_bases` 集合（`manager.py:474-500`），源文件镜像上传（`deeptutor/api/routers/knowledge.py:427-437, 645-662`）；文件注册表仍是事实源（`manager.py:485-499`）。
- 风险：`kb_config.json` 并发 RMW 可能互丢条目（stat 缓存只能检测 `:346-363`）；FAISS 直接 `open(...,"wb")` 非原子（`vector_store.py:95-97`），仅靠"写进新 version 目录"缓解；废弃 version 目录无 GC；linked-KB 的 `external_path` 指针指向备份范围之外（`deeptutor/services/rag/kb_paths.py:24-47`）。

### 2.6 文件库 / 上传 / 附件 / 解析缓存

- 文件库：字节 `workspace/library/files/<uuid>`，元数据 SQLite（sha256/mime/软删），含内容去重（`deeptutor/services/storage/file_library.py:5-7, 129-160`）。
- 聊天附件：`chat/attachments/<session>/<id>_<name>`，URL 记在会话库（`deeptutor/services/storage/attachment_store.py:21-49, 105-130`）。
- KB 原始上传：`<kb>/raw/` 带路径净化与大小上限（`deeptutor/api/routers/knowledge.py:329-342, 379-414, 416-545`）。
- 解析缓存：内容寻址 `parse_cache/<hash2>/<source_hash>/<sig>/`，可随时重建、无 DB（`deeptutor/services/path_service.py:124-132`；`deeptutor/services/parsing/cache.py:8, 48-49`）。

### 2.7 多用户注册表 / 授权 / 审计

- 用户：`data/system/auth/users.json` + `auth_secret`（`deeptutor/multi_user/identity.py:36-40`）；写锁是**线程锁**，代码自注"多 worker 部署仍会竞态，需依赖外部用户存储（如 PocketBase）"（`:26-34`）——这是全部存储面中唯一被源码明确承认的多进程数据正确性缺口。
- 授权：每用户一 JSON `data/system/grants/<uid>.json`，thread+flock 双锁（`deeptutor/multi_user/grants.py:20, 48-51, 156-158`）。
- 审计：追加式 `data/system/audit/usage.jsonl`，无轮转无上限（`deeptutor/multi_user/audit.py:20-33`）。
- 机密：`data/system/user-secrets/<owner>/` chmod 700（`deeptutor/multi_user/paths.py:217-256`）；Invidious 账号凭据同域（`deeptutor/video_learning/invidious_account_storage.py:33-58`）。

### 2.8 记忆系统 / Partner 会话 / 日志

- 记忆三层：`memory/{trace/<surface>/<date>.jsonl, L2/, L3/, backup/<ts>/}`（`deeptutor/services/memory/paths.py:3-94`）；L1 trace 按日追加、仅手动清理端点（`deeptutor/api/routers/memory.py:695-722`）；快照差异 `changes.jsonl` 追加式（`deeptutor/services/memory/snapshot/store.py:9, 36`）。
- Partner 会话：`data/partners/<id>/sessions/*.jsonl` 逐会话追加、归档不删盘（`deeptutor/services/partners/sessions.py:59, 389-396`）；群白板 `shared/whiteboard.jsonl` 追加式（`deeptutor/services/partner_groups/memory.py:37, 82`）。
- 应用日志：RotatingFileHandler 10MB×5（`deeptutor/logging/configure.py:63-71`）——有界，正面样本。

### 2.9 容器卷映射

- 生产：`./data:/app/data`（"一棵树挂载、一棵树备份"，`docker-compose.yml:88-98`）+ 工作区独立卷 `:88-98`；Redis AOF `./data/redis:/data` 仅协调用（`:34-36`）；PB `./data/pocketbase:/pb_data`（`:62-64`）；沙箱 runner 只读工作区、仅 `outputs/` 可写、不见 `data/system|users`（`:167-175`）。
- 预构建镜像 compose 注释里保留了历史教训：曾因部分挂载导致 `data/system`、`data/users`、`data/partners` 重建即丢（`docker-compose.ghcr.yml:69-75`）。
- dev override 把 PB 挂到旧路径 `/pb/pb_data`，与基线 `/pb_data` 不一致（`docker-compose.dev.yml:15` vs `docker-compose.yml:57-62`）。

---

## 3. 备份与迁移现状

**备份机制（全部为迁移时快照，无周期性备份）：**

- 账户数据导出/迁移 + 恢复：按 feature 清单打包 `export.zip` 到 `.runtime/data-migrations/<op>/`，迁移前快照留账户私有恢复目录，支持 `recover_operation`（`deeptutor/services/workspace/data_migration.py:28-48, 145-176, 502-546, 922+`；API `deeptutor/api/routers/workspace.py:92-145`）。feature 清单覆盖 chat/learning/reading/knowledge_bases 等 19 类（`data_migration.py:28-48`）。
- 零散快照：KB 清理前整目录复制备份（`deeptutor/knowledge/manager.py:1890-1953`）、记忆 v1 归档（`deeptutor/services/memory/store.py:333-357`）、聊天 v1 JSON 归档（`deeptutor/services/session/legacy_migration.py:169-173`）、Mastery V1 归档（`deeptutor/learning/migration.py:28-35`）、工作区搬迁 copy-verify-activate（`deeptutor/services/workspace/migration.py:36+`）。
- **没有**周期性/一致性全量备份工具；顶层 `backups/` 目录不被任何代码引用（仅文档示例 `docs-for-user/workspace-isolation-implementation.md:88`）。唯一一致性强的是 SQLite backup API 的单库快照（`data_migration.py:145-176`），但**跨库无共同快照点**：chat DB、mastery DB、catalog DB、KB 树各按各的时刻打包。
- 迁移编排：启动时统一走 `deeptutor/app/container.py:288-307`；已登记迁移含 multi-user 树搬迁（`deeptutor/multi_user/paths.py:48-86`）、聊天 v1→SQLite、记忆 markdown→三层、Mastery V1→V2、partner 频道状态迁移（`deeptutor/services/partners/channel_state_migration.py:1-26`）、遗留工作区绑定（`deeptutor/services/workspace/session_move.py`）。
- 无迁移路径的存储：`parse_cache`（按设计可重建）、`workspace/library` 新目录库、`chat/attachments`、`data/cli-apps`、PocketBase 集合（无 schema 升级钩子）。

**本机部署实测（聚合口径，私有部署样本）**：`data/` 共 1.5G；其中最大项是 `data/tmp/issue-918-build` ≈1.1G（历史构建残留，非代码管理的路径）；`chat_history.db` ≈9MB；`knowledge_bases` ≈150MB；单用户工作区 5–17MB；audit jsonl 目前仅 4.9KB。说明：当前规模下 SQLite 完全够用，风险是结构性的（增长无界、快照不一致），不是容量性的。

---

## 4. 风险分级

| 级别 | 风险 | 证据 | 迁 PG 是否缓解 |
|---|---|---|---|
| 高 | `users.json` 多进程写竞态（注册/提权） | `deeptutor/multi_user/identity.py:26-34`（源码自注） | 部分（PG 行锁可解，但单机部署改锁纪律即可） |
| 高 | 跨库备份无一致快照点；无周期备份工具 | §3；`data_migration.py:145-176`（仅单库） | 否（PG 也要 pg_dump 编排） |
| 高 | 无界增长：`turn_events`、`usage.jsonl`、memory trace、partner jsonl、KB 废弃 version、`.runtime/data-migrations` zip | `sqlite_store.py:2235-2237`；`multi_user/audit.py:20-33`；`memory/paths.py:73-74`；`partners/sessions.py:389-396`；`manager.py:1938-1945`；`data_migration.py:896-904` | 否（换存储不换策略，照样无 TTL） |
| 中 | 三种 schema 版本习惯并存（内联 ALTER / 具名迁移表 / 单行版本表），PB 无版本 | `sqlite_store.py:461-518`；`learning/storage.py:477-480`；`catalog_store.py:81-83,192`；`pocketbase_store.py:332-335` | 是（PG 生态迁移工具成熟，但统一抽象后 SQLite 也可用） |
| 中 | chat 单库承载多域（会话+测验星星+练习+事件流），启动期大迁移 | `sqlite_store.py:284-458, 843-1082` | 部分（拆域到不同库/服务更相关） |
| 中 | 线程锁 vs flock 混用：reading 状态、users.json 在多 worker 下丢更新 | `reading/store.py:176-177`；`identity.py:26-34` | 是（单 PG 实例天然串行化），但单机形态修锁即可 |
| 中 | 非原子写：FAISS 索引、`subagent_sessions.json` | `vector_store.py:95-97`；`subagent/sessions.py:49-52` | 部分（索引文件本就不适合入库） |
| 中 | PB 模式无事务、无 schema 升级、凭据明文、集合隔离全靠应用层 | `pocketbase_store.py:332-382`；`runtime_settings.py:549-551`；`scripts/pb_setup.py:156-198` | 是（PG 后端可一并解决） |
| 低 | `kb_config.json` 并发 RMW 丢条目（有检测无预防） | `manager.py:346-363, 462-470` | 是，但量小影响有限 |
| 低 | dev compose PB 挂载路径漂移 | `docker-compose.dev.yml:15` | 否 |

---

## 5. PostgreSQL 引入评估

### 5.1 收益

1. 单实例多 worker/多副本部署下的真并发与跨进程事务（users 注册、grant、KB 注册表 RMW 全部消失为行级并发）。
2. 成熟的 schema 迁移工具链（Alembic 等），统一三种版本习惯。
3. 跨用户全局查询/运营报表/审计检索成为可能（当前 per-user DB 文件物理隔离，跨用户统计要扫文件）。
4. pgvector 可选替代 FAISS 文件索引，索引与元数据同库同事务。
5. 备份可用单一 `pg_dump` 获得一致快照点。

### 5.2 成本

1. 部署面翻倍：每个 Docker 部署多一个有状态服务（现有 compose 已有 Redis + PocketBase 两个 sidecar，`docker-compose.yml:34-64`），家庭/教育用户的"一棵 data 树"备份模型被打破。
2. 连接模型改造：当前全部 store 是进程内直连文件，需引入连接池与异步驱动；`deeptutor/services/session/protocol.py:143-249` 的会话协议是现成的接口层，但 learning/reading/catalog/registry 没有协议层，全部要写 PG 实现。
3. RAG 索引迁移是大头：FAISS 字节文件与 LightRAG 工作目录（KV/向量/图）各有自有格式，迁 pgvector/LGRAPH 等于重写两条 ingestion/pipeline（`deeptutor/services/rag/pipelines/llamaindex/vector_store.py:80-97`、`lightrag/storage.py:50-56`），且嵌入签名版本化逻辑要在 PG 重建。
4. 二进制/文件数据（附件、KB raw、生成产物、parse_cache）本就不该进 PG——仍需对象存储或文件树，PG 只解决元数据一半。
5. 数据迁移工程：三库 + JSON 树 + PocketBase 双后端并存现状，迁移工具本身就是一个项目；还要处理 per-user DB 文件 → 单库多租户的行级隔离（当前按文件隔离的授权模型要重写为 WHERE user_id，与现有 PB 后端同款风险）。

### 5.3 建议路径（分阶段、有前置条件）

**阶段 0（现在做，不引入 PG，收益/成本比最高）：**
1. 统一 schema 版本：把 `chat_history.db` 的内联 ALTER 改造为具名迁移表（照抄 `mastery_schema_migrations` 模式），PB 后端补版本标记。
2. 无界增长治理：`turn_events`/`usage.jsonl`/memory trace 按 TTL 或尺寸归档；`data_migration.py` 完成态 op 加保留策略；KB 废弃 version 目录 GC。
3. 锁纪律：`users.json` 与 reading 状态写路径补 flock（仓库内已有现成模式 `grants.py:48-51`、`sqlite_store.py:54-65`）。
4. 一键一致性备份：新增 `deeptutor backup` 命令——SQLite backup API 快照全部库 + 文件树 tar + manifest（学习库迁移里已有 manifest 先例 `learning/migration.py:279-298`），这一步做完，"长期用户数据安全"的核心问题基本闭环。

**阶段 1（出现真实触发条件时）：** 以现有 PocketBase 后端同款模式（`session/__init__.py:15-38` 的后端选择器）新增 PG store，先迁会话/消息/turns（有协议层、风险最低），用户注册表随迁。触发条件（满足其一）：
- 单机部署出现多 worker/多副本（compose scale > 1 或 K8s）；
- 单用户 `chat_history.db` 或写入吞吐触达 SQLite 实际瓶颈（写入队列化明显、busy timeout 频发）；
- 需要跨用户运营报表/审计检索的产品化需求。

**阶段 2（可选、独立决策）：** pgvector 替代 FAISS。仅在阶段 1 完成且 KB 规模/查询延迟有实测压力时评估，不要与阶段 1 绑定。

**明确不建议迁 PG 的部分（永久或长期）：**
- `parse_cache/`：内容寻址、可重建、零一致性要求（`deeptutor/services/parsing/cache.py:8`）。
- 附件/生成产物/KB raw 二进制：适合对象存储或维持文件树，进 PG 只增加 TOAST 膨胀。
- Redis AOF：仅协调流，非用户数据（`deeptutor/runtime/coordination/redis.py:91-121` 已有保留策略）。

### 5.4 前置条件清单（任一 PG 动工前必须满足）

1. 阶段 0 的四项全部落地（尤其统一 schema 版本与备份命令——它们是迁移的安全网）。
2. 会话协议层（`session/protocol.py`）被确认为所有 store 的统一抽象，learning/reading 补齐协议。
3. 明确双后端支持政策：SQLite 保持默认零配置路径，PG 为 opt-in（照 PocketBase 后端先例），否则上游用户升级成本不可接受。
4. 行级多租户隔离方案评审（当前文件隔离的授权模型需要整体改写为查询级过滤）。
5. 迁移工具与回滚演练：per-user DB 文件 → 单库的批量导入器 + 实测回滚。

---

## 6. 验收对照

1. 每项存储面附 path:line — 见 §2（2.1–2.9）与 §4 表格。
2. 结论给出明确建议与前置条件 — 见 §1 与 §5.4。
3. 不改任何代码 — 本分支仅新增 `evidence/persistence-scan-20261004/` 下的报告与校验文件，`git diff origin/main --stat` 可验证。
