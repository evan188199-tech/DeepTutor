# 本地数据库配置问答（回应上游 issue #401）

> 上游 #401 问「能否配置个人本地化的数据库」，并希望知识库内容跨会话保存。
> 本文按"今天能配什么、怎么配、缺什么"逐条作答，所有结论均附代码锚点。
> 存储架构全景见 guide-storage 分支 `evidence/guide-storage-2026-10-04/guide.md`，
> 会话存储细节见 `evidence/guide-session-stores-20261007/report.md`，本文只谈配置入口。

## Q1：DeepTutor 现在的数据存在哪里？默认就是本地库吗？

是。所有持久化都落在一个本地数据树 `<运行目录>/data` 下，无需任何配置：

- 根目录由 `DEEPTUTOR_HOME` 环境变量或启动时所在目录决定（`deeptutor/runtime/home.py:28-43`），数据根固定为 `<home>/data`（`deeptutor/runtime/home.py:46-49`）。
- 会话/消息/笔记本/测验：SQLite 文件 `data/user/chat_history.db`（`deeptutor/services/path_service.py:134-135`），存储实现 `SQLiteSessionStore`（`deeptutor/services/session/sqlite_store.py:254`）。
- 知识库索引：`data/.../knowledge_bases/<库名>/version-N/` 下的 JSON/GraphML 文件（版本目录 `deeptutor/services/rag/index_versioning.py:1-23`）。
- 记忆：`data/.../memory/` 下 JSONL/Markdown 三层文件（`deeptutor/services/path_service.py:299-300`）。
- 其他 SQLite：用量 `usage.sqlite3`（`deeptutor/services/llm/usage_ledger.py:40`）、掌握度 `mastery.sqlite3`（`deeptutor/learning/storage.py:351`）、阅读目录、任务板、cron 等，路径均由数据树派生。

## Q2：知识库能像阿里云百炼那样跨会话保存吗？

能，且默认就是。知识库索引文件写入 KB 版本目录并长期保留，重建/升级按版本隔离；
会话历史写入本地 SQLite，重启后仍可读。#401 要的"跨会话保存"在今天的主线已是默认行为。

## Q3：想把整个数据库搬到自定义位置（如个人网盘/独立分区）怎么配？

三种方式，任选其一：

1. 环境变量 `DEEPTUTOR_HOME=/path/to/home`——整个 `data` 树随之迁移（`deeptutor/runtime/home.py:8`）。
2. CLI 参数 `--home PATH`：`deeptutor init/config/main` 均支持（`deeptutor_cli/init_cmd.py:624`、`deeptutor_cli/config_cmd.py:33`）。注意 `.env` 不会自动加载，多处入口要保持同一 `DEEPTUTOR_HOME`（`deeptutor_cli/README.md:236`）。
3. Docker：整树 bind mount `./data:/app/data`（`compose.yaml:174`），换宿主机路径即换库位置；工作区可单独用 `DEEPTUTOR_WORKSPACE_HOST` 覆盖（`compose.yaml:177`）。

校验规则：运行目录不允许嵌套在源码 checkout 的 `data/` 内（`deeptutor/runtime/home.py:12-25`）。

## Q4：PocketBase 是什么？能当"个人数据库"开关吗？

PocketBase 是可选的认证+存储 sidecar（独立进程，自身仍是内嵌 SQLite 文件）：

- 开关：`integrations.json` 里 `pocketbase_url`（默认空=关闭，`deeptutor/services/config/runtime_settings.py:91-107`），或环境变量 `POCKETBASE_URL` / `POCKETBASE_PORT` / `POCKETBASE_ADMIN_EMAIL` / `POCKETBASE_ADMIN_PASSWORD`（`deeptutor/services/config/runtime_settings.py:904-913`）。
- 会话后端选择：配置了 URL 即用 `PocketBaseSessionStore`，否则回落零配置的本地 SQLite（`deeptutor/services/session/__init__.py:15-38`）。PocketBase 不可达时启动告警并临时回落 SQLite（`deeptutor/services/pocketbase_client.py:190-195`）。
- 它的数据目录由容器管理：`./data/pocketbase:/pb_data`（`compose.yaml:111-113`，端口 `compose.yaml:103`），改宿主路径即迁移。
- 限制：PocketBase 模式目前仅单用户（`deeptutor/multi_user/__init__.py:9-17`），且只接管会话/认证，不接管知识库索引。部署说明见 `docs-for-user/CONTAINERIZATION.md:445-463`。

## Q5：向量库 / RAG 存储能换成 Milvus、PGVector 之类吗？

不能。RAG 引擎 LightRAG（`lightrag-hku==1.5.7`）在构造时只传 `working_dir` 与 `workspace`，
不传任何 `kv_storage/vector_storage/graph_storage` 参数（`deeptutor/services/rag/pipelines/lightrag/engine.py:279-280`），
因此始终用 SDK 默认的本地文件存储；`working_dir` 就是 KB 的 `version-N` 目录（`deeptutor/services/rag/pipelines/lightrag/storage.py:50-52`），
没有 `LIGHTRAG_WORKING_DIR` 之类的独立环境变量——索引位置永远跟随数据树。

可配置的只是检索/索引行为参数（`lightrag.json`：top_k、并发、超时等，`deeptutor/services/config/runtime_settings.py:361-373`），
或改用外部 LightRAG Server 做检索（`lightrag_server.json` 的 `server_url/api_key`，`deeptutor/services/config/runtime_settings.py:378-382`）。

## Q6：能接外部数据库服务器（Postgres/MySQL）吗？

不能。代码与依赖中没有任何 Postgres/MySQL/psycopg 支持；"类数据库"的外部服务只有三个：
PocketBase（会话/认证）、LightRAG Server（检索）、Redis（仅 turn 协调，`DEEPTUTOR_REDIS_URL`，`deeptutor/services/config/runtime_settings.py:917`）。
三者都经 `integrations.json`/env 配置，Redis AOF 数据同样落在 `./data/redis`（compose 卷内）。

## 配置速查

| 想改什么 | 入口 | 锚点 |
| --- | --- | --- |
| 整个数据树位置 | `DEEPTUTOR_HOME` / `--home` / compose 卷 | `deeptutor/runtime/home.py:8` |
| 会话后端（SQLite↔PocketBase） | `integrations.json` `pocketbase_url` 或 `POCKETBASE_URL` | `deeptutor/services/session/__init__.py:15-38` |
| PocketBase 地址/端口/凭据 | `POCKETBASE_URL` 等 4 个 env 或 JSON | `deeptutor/services/config/runtime_settings.py:904-913` |
| PocketBase 数据目录 | compose bind mount `./data/pocketbase` | `compose.yaml:111-113` |
| RAG 检索参数 | `lightrag.json`（top_k 等） | `deeptutor/services/config/runtime_settings.py:361-373` |
| 外部检索服务 | `lightrag_server.json` `server_url` | `deeptutor/services/config/runtime_settings.py:378-382` |
| turn 协调 Redis | `DEEPTUTOR_REDIS_URL` | `deeptutor/services/config/runtime_settings.py:917` |

## 结论：能配什么 / 缺什么

- 能配：数据树整体搬迁（env/CLI/卷）、会话后端切换到可选 PocketBase sidecar、RAG 参数与外部检索服务。
- 不能配：单个存储的数据库文件路径（全部由数据树派生）、向量库后端（固定本地文件）、外部 SQL 数据库服务器。
- 若 #401 期望的是"外接 Milvus/PGVector/Postgres"级别的后端，属于新功能：需要为 LightRAG 传 storage 参数并为会话存储抽象出数据库驱动，现有代码尚无此入口。
