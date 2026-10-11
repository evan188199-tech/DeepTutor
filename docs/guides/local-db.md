# DeepTutor 数据持久化导读：默认存储、可配置面与外部数据库边界

- 基线：origin/main @ `6cf793bd8`（v1.6.14）。
- 缘起：HKUDS/DeepTutor#401「能否配置个人本地化的数据库」。
- 定位：只陈述现行代码的存储事实与配置面，不承诺未实现能力；锚点 `path:line` 相对仓库根，可在基线 commit 逐条复核。
- 不覆盖：事件链路（`docs/guides/events-and-progress-chain.md`）、工具面（`docs/guides/tools-surface.md`）。

## 1. 先说结论：三档边界

| 诉求 | 结论 |
| --- | --- |
| 数据放哪里、整体搬家/备份 | 已支持：一棵 `data/` 树，`DEEPTUTOR_HOME` 换根 |
| 自建检索后端（lightrag-server/WeKnora/IMA/kiwix/PageIndex） | 已支持：知识库按 provider 外接 |
| 自建嵌入端点（OpenAI 兼容） | 已支持：model catalog 配 base_url |
| 聊天记录等存到外部 PocketBase | 已支持，但当前仅单用户语义 |
| 多 worker 部署的运行时协调 | 已支持：Redis 后端（仅协调态，非业务数据） |
| PostgreSQL/MySQL 等关系库作业务存储 | 不支持：无驱动、无存储实现、无连接串配置 |
| 向量索引放外部向量库（pgvector/Milvus 等） | 需开发：仅本地 FAISS/JSON 文件，seam 预留 |
| PocketBase 模式下的多用户 | 需开发：缺 role 字段与 user_id 过滤 |
| 只搬某个子库（如仅会话库） | 需开发：无 per-file 配置面 |

## 2. 默认存储面：一棵 `<runtime-home>/data` 树

### 2.1 运行时根怎么定

- 环境变量 `DEEPTUTOR_HOME`：`deeptutor/runtime/home.py:8`；解析优先级为 显式参数 > `DEEPTUTOR_HOME` > 当前工作目录（`deeptutor/runtime/home.py:28-43`）。
- 数据根恒等于 `<home>/data`（`deeptutor/runtime/home.py:46-49`）。
- 防误配：runtime home 不得落在代码仓库自带的 `data/` 或 `data/user` 内部，否则启动即报错（`deeptutor/runtime/home.py:12-25`）——"搬家"必须搬到树外的新根。
- 首次启动初始化 `data/user/` 目录树（`deeptutor/services/setup/init.py:145-165`）；端口等部署项存 `data/user/settings/system.json`（`deeptutor/services/setup/init.py:263`）。

### 2.2 目录布局（多用户部署全景）

声明见 `deeptutor/multi_user/paths.py:3-14`；单用户部署只有 `data/user/` 一个工作区：

```
data/
├── user/               # 管理员（单用户）工作区：settings/、logs/、workspace/、chat_history.db、.runtime/
├── users/<uid>/        # 多用户时每个非管理员一个同构工作区 deeptutor/multi_user/paths.py:36-39,102-106
├── partners/<id>/      # 合作方（合成用户）工作区 deeptutor/partners/config/paths.py:21-27
├── system/             # 部署级状态：auth/、grants/、audit/、indexes/、user-secrets/ deeptutor/multi_user/paths.py:38,128-137
├── knowledge_bases/    # 知识库索引 + kb_config.json deeptutor/services/path_service.py:121-122
├── parse_cache/        # 文档解析共享缓存（内容寻址） deeptutor/services/path_service.py:124-132
├── memory/             # 三层记忆 L1/L2/L3 deeptutor/services/memory/paths.py:5-10
├── learning_journal/   # 学习日志 journal.json deeptutor/services/path_service.py:302-307
└── pocketbase/         # 仅启用 PocketBase 的 compose 部署 docker-compose.yml:56-64
```

`PathService` 是唯一路径权威（`deeptutor/services/path_service.py:64-90`）：默认根 `data/`；多用户时以 `data/users/<uid>/` 为根实例化，workspace 子树内的 `.runtime/`、`settings/`、`workspace/` 等相对布局保持同构（`deeptutor/services/path_service.py:2-24`）。

### 2.3 本地 SQLite 文件清单（业务数据的默认落点）

| 文件（相对各 scope 根） | 内容 | 锚点 |
| --- | --- | --- |
| `<root>/user/chat_history.db` | 会话/消息/回合 | `deeptutor/services/path_service.py:134-135`、`deeptutor/services/session/sqlite_store.py:268-273` |
| `<user_root>/usage.sqlite3` | LLM 用量台账 | `deeptutor/services/llm/usage_ledger.py:38-40` |
| `<user_root>/workspace/task-board/cards.sqlite` | 任务看板 | `deeptutor/services/task_board.py:432` |
| `<user_root>/workspace/library/library.db` | 文件库索引 | `deeptutor/services/storage/file_library.py:43,470-472` |
| `data/system/web-source-sync.sqlite` | 网页源同步调度 | `deeptutor/services/web_source/scheduler.py:35-39` |
| `data/partners/_runtime/status.sqlite3` | 合作方渠道状态 | `deeptutor/services/partners/runtime_status.py:18` |

驱动面只有标准库 `sqlite3` 与 `aiosqlite`（`pyproject.toml:35`）；pyproject/requirements 中不存在 postgres/mysql/mongo 客户端。

账号与授权不走 SQLite：`data/system/auth/users.json` + `auth_secret`（`deeptutor/multi_user/identity.py:37-40`），grants/audit 为 `data/system/` 下的文件（`deeptutor/multi_user/paths.py:128-131`）。

### 2.4 知识库索引

- 目录 `<workspace_root>/knowledge_bases/<kb_name>`，注册表 `kb_config.json`（`deeptutor/services/config/knowledge_base_config.py:21`）。
- 默认 `llamaindex` 管线：新索引持久化为本地 FAISS 二进制文件，未装可选依赖时退回 SimpleVectorStore JSON，两种格式并存且互不破坏（`deeptutor/services/rag/pipelines/llamaindex/vector_store.py:14-23`）。
- "linked KB" 可指向用户已有的外部索引目录原位读取，不复制不重索引（`deeptutor/services/rag/kb_paths.py:3-6`）。

## 3. 现行可配置项

| 配置 | 作用 | 锚点 |
| --- | --- | --- |
| `DEEPTUTOR_HOME` | 整棵数据树换根 | `deeptutor/runtime/home.py:28-49` |
| `DEEPTUTOR_WORKSPACE_ROOT` / `DEEPTUTOR_WORKSPACE_ALLOWED_ROOTS` | 内容工作区外置到任意目录并约束可绑定根 | `deeptutor/services/workspace/service.py:29-31,97-108` |
| `data/user/settings/*.json`（system / auth / integrations / document parsing 等） | 运行时设置，文件与 UI 双通道 | `deeptutor/services/config/runtime_settings.py:504-581`、`deeptutor/services/config/runtime_settings.py:1360-1366`、`deeptutor/services/path_service.py:225-241` |
| `integrations.pocketbase_url`（+ port/admin_email/admin_password） | 启用 PocketBase 会话存储 | `deeptutor/services/config/runtime_settings.py:93-97` |
| `integrations.turn_coordination.backend/redis_url`（env 覆写 `DEEPTUTOR_TURN_COORDINATION_BACKEND` / `DEEPTUTOR_REDIS_URL`） | 运行时协调后端 memory→redis | `deeptutor/runtime/coordination/settings.py:12-21,24-38`、`deeptutor/services/config/runtime_settings.py:915-917` |
| 嵌入端点（model catalog profile 的 base_url/api_key） | 可指向自建 OpenAI 兼容嵌入服务 | `deeptutor/services/embedding/config.py:1,88-95` |
| Docker：`./data:/app/data`、`DEEPTUTOR_WORKSPACE_HOST`、`PUID/PGID` | 数据卷映射与属主 | `docker-compose.yml:88-98`、`deeptutor/services/setup/data_volume.py:51-79` |

粒度注意：`DEEPTUTOR_HOME` 搬的是**整棵树**；没有"只把会话库/向量索引指到别处"的 per-file 配置项。

## 4. 外部库接入现状

### 4.1 会话存储：SQLite（默认）/ PocketBase（可选外部库）

- 选择点在 `get_session_store()`（`deeptutor/services/session/__init__.py:15-34`）：`integrations.pocketbase_url` 非空 → `PocketBaseSessionStore`；否则本地 `SQLiteSessionStore`。两者实现同一 `SessionStoreProtocol`（`deeptutor/services/session/protocol.py:4`）。
- PocketBase 是唯一内置的外部"数据库"后端，承载 sessions/messages/turns 集合（`deeptutor/services/session/pocketbase_store.py:1-12`）；客户端仅在配置了 URL 时初始化（`deeptutor/services/pocketbase_client.py:2-4,42-43`）。
- compose 提供开箱 sidecar：设置 `integrations.pocketbase_url=http://pocketbase:8090` 激活，留空走 SQLite 回退（`docker-compose.yml:45-50`）。
- 两条边界（官方注释原文归纳）：PocketBase 模式当前**仅单用户**——users 集合默认无 role 字段（登录一律解析为 `role="user"`），且 sessions/messages/turns 查询不按 user_id 过滤（`deeptutor/multi_user/__init__.py:9-17`）；同时 system 状态（账号/授权/审计）仍在本盘 `data/system/`，不经 PocketBase。

### 4.2 知识库检索：本地引擎 + 外部服务

provider 一览（`deeptutor/services/rag/factory.py:6-24`）：`llamaindex`（默认，本地）、`pageindex`（云）、`pageindex-oss`（本地库）、`graphrag`（本地，可选依赖）、`lightrag`（本地，可选依赖）、`lightrag-server`、`ima`、`weknora`、`kiwix`。其中 `lightrag-server`/`ima`/`weknora`/`kiwix` 是"连接指针"型：文档与索引留在用户自己的外部部署里，DeepTutor 只存指针并经 HTTP/OpenAPI 检索（`deeptutor/services/rag/factory.py:14-24`）。

### 4.3 运行时协调：memory（默认）/ Redis

- `integrations.turn_coordination.backend = redis` + `redis_url` 切换，默认 `memory`（进程内）（`deeptutor/runtime/coordination/settings.py:12-21,24-38`）。
- Redis 只放租约/命令/事件流等协调态；compose 侧 AOF 仅用于 sidecar 重启续流，业务数据仍在 SQLite/PocketBase（`docker-compose.yml:26-36`）。

## 5. 三档清单（#401 的直接答案）

### 已支持（现在就能配）

1. 数据整体外置/搬家/备份：`DEEPTUTOR_HOME` 指向任意空目录，数据树随之落到 `<home>/data`（`deeptutor/runtime/home.py:28-49`）；备份即停机复制整棵 `data/`（`deeptutor/multi_user/paths.py:3-4`）。
2. 自建检索后端：lightrag-server / WeKnora / IMA / kiwix / PageIndex，按 KB 选择 provider（`deeptutor/services/rag/factory.py:6-24`）。
3. 自建嵌入端点：model catalog 内配 base_url（含 OpenAI 兼容自建服务）（`deeptutor/services/embedding/config.py:88-95`）。
4. 会话存储外置到 PocketBase（单用户语义）（`deeptutor/services/session/__init__.py:15-34`）。
5. Redis 运行时协调（多 worker）（`deeptutor/runtime/coordination/settings.py:24-38`）。
6. 内容工作区放独立目录/挂载点（`deeptutor/services/workspace/service.py:29-31`）。

### 需开发（有 seam、无实现）

1. 关系库（含 PostgreSQL）会话存储：需按 `SessionStoreProtocol` 新写一个后端并引入驱动（`deeptutor/services/session/protocol.py:4`）。
2. 外部向量库：llamaindex 管线的 vector store seam 注释明示可替换实现，但目前仅本地 FAISS/JSON 两条路（`deeptutor/services/rag/pipelines/llamaindex/vector_store.py:14-23`）；pgvector/Milvus 等需自行开发。
3. PocketBase 多用户化：users 集合补 role 字段、查询按 user_id 过滤（`deeptutor/multi_user/__init__.py:13-17` 列明的缺口）。
4. 子库级存储重定位：per-file 路径覆写无配置面（路径全部由 `PathService` 从 runtime home 派生，`deeptutor/services/path_service.py:85-90`）。

### 不支持（当前代码路径不存在）

1. 用 PostgreSQL/MySQL/MongoDB 存任何业务数据：无驱动依赖、无连接串配置项（依赖面仅 sqlite/aiosqlite/redis，`pyproject.toml:35`）。
2. 把单个 SQLite 文件单独挂到网络盘/NFS 而其余数据留在本地：无 per-file 覆写机制；要外置请整树 `DEEPTUTOR_HOME` 一起搬。
3. 不配 PocketBase 也不改代码时，把会话历史指向任意第三方 HTTP API：会话存储后端是编译期二选一，无通用"存储 URL"开关（`deeptutor/services/session/__init__.py:15-34`）。

## 6. 迁移与备份操作要点

1. 备份：停机后复制整棵 `data/`；SQLite 文件避免热拷贝（WAL 未落盘）。
2. 搬家：设 `DEEPTUTOR_HOME=/new/home` 后启动，数据树落在 `/new/home/data`；不得指向仓库内 `data/`（`deeptutor/runtime/home.py:12-25`）。
3. 容器：保持 `./data:/app/data` 卷映射；workspace 可经 `DEEPTUTOR_WORKSPACE_HOST` 独立挂载（`docker-compose.yml:88-98`）；NAS/Unraid 属主用 `PUID/PGID`（`deeptutor/services/setup/data_volume.py:51-79`）。
4. 知识库单独迁移参考 `docs-for-user/KNOWLEDGE_MIGRATION.md`；容器化部署参考 `docs-for-user/CONTAINERIZATION.md`。
