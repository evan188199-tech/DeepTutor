# Knowledge Base 摄取与检索模块代码导读

> 基于 `origin/main` v1.6.12（`ef2d9e5c3`），含 #1481（PR #1488）与 #1478（PR #1480）修复后的现状。所有 `path:line` 均可在该提交直接定位。

## 1. 模块地图

| 层 | 位置 | 职责 |
|---|---|---|
| REST 入口 | `deeptutor/api/routers/knowledge.py:3391`（创建）、`:3275`（上传）、`:3973`（重建索引） | KB 生命周期 HTTP API，后台任务在此注册 |
| 后台任务 | `deeptutor/api/routers/knowledge.py:974`（初始化）、`:1113`（上传处理）、`:3682`（重建） | FastAPI BackgroundTasks 真正干活的地方 |
| 领域层 | `deeptutor/knowledge/manager.py:318`、`initializer.py:35`、`add_documents.py:172` | 目录/状态管理、首次索引、增量索引 |
| 服务层 | `deeptutor/services/rag/service.py:22` | `RAGService`：按 KB 绑定引擎路由到 pipeline |
| 探针/版本 | `deeptutor/services/rag/index_probe.py:40`、`index_versioning.py:212` | 索引就绪判定、embedding 签名多版本 |
| LlamaIndex 管线 | `deeptutor/services/rag/pipelines/llamaindex/pipeline.py:164` | 默认引擎的索引/检索编排（含 stall guard） |
| 检索工具 | `deeptutor/tools/rag_tool.py:15` | chat agent 的 `rag_search` 工具（`deeptutor/tools/builtin_specs.py:221` 注册） |

其他引擎（graphrag / lightrag / pageindex / ima / kiwix / weknora / lightrag-server）在 `deeptutor/services/rag/pipelines/` 下同构接入；连接型 KB（Obsidian、IMA、外部 LightRAG server 等）只存指针不落索引，类型见 `deeptutor/knowledge/kb_types.py:10` 起（`lightrag_server` `:21-26`、`ima` `:27-33`）。

## 2. 磁盘布局与权威状态

- KB 根目录 `data/knowledge_bases/<name>/`，创建时只建 `raw/` 与 `metadata.json`（`deeptutor/knowledge/initializer.py:123-144`）。
- `kb_config.json` 是权威状态：status/progress/rag_provider/embedding 绑定都在这里（`deeptutor/knowledge/manager.py:336` 加载、`:455` `update_kb_status`、`:1371` `get_info` 读取并推导有效状态，活跃任务未到终态时抑制 `needs_reindex`，`manager.py:1422-1425`）。
- 索引版本：flat 布局 `<kb>/version-N/`，每个版本带 `meta.json`（embedding 签名 + ready 标记，`deeptutor/services/rag/index_versioning.py:307-321`）；旧式嵌套/根目录布局仍可读，新写一律收敛到 flat（`index_versioning.py:212-234`、`:344-351`）。
- 去重记录：`metadata.json` 的 `file_hashes`，键是相对 `raw/` 的 POSIX 路径（`deeptutor/knowledge/add_documents.py:111-122`）——索引与删除必须共用这一规则，否则删除后的哈希残留会让重加同路径文件被误判为已索引。

## 3. 数据流

### 3.1 创建（POST /knowledge-bases）
1. 校验名称/工作区/LightRAG 写所有权（`knowledge.py:3420-3446`），无文件时走快速路径：直接记 `ready`，不建任何索引（`knowledge.py:3613-3642`）——这就是空 KB 的来源（web/GitHub 来源、后续上传）。
2. 有文件时：先写 `initializing` 状态（`knowledge.py:3555-3586`），保存文件到 `raw/`（`knowledge.py:3644-3646`），再注册后台任务 `run_initialization_task`（`knowledge.py:3658-3663`）。
3. 初始化任务 → `KnowledgeBaseInitializer.process_documents`：收集 `raw/` 支持文件（`initializer.py:175`，经 `deeptutor/services/rag/file_routing.py:386`），空目录直接报错（`initializer.py:177-183`），然后 `RAGService.initialize`（`initializer.py:238-245`）→ LlamaIndex `pipeline.initialize`。

### 3.2 上传（POST /knowledge-bases/{kb}/upload）
1. KB 锁定创建引擎：请求 provider 与绑定不一致即 400（`knowledge.py:3307-3317`）；embedding 绑定缺失/变更即 409（`knowledge.py:3323-3328`）。
2. 文件落盘走线程池，避免阻塞事件循环（`knowledge.py:3345-3351`）；zip 只作容器，成员再校验（`knowledge.py:3340-3344`）。
3. 后台 `run_upload_processing_task`：`DocumentAdder` 构造（`knowledge.py:1204-1210`）→ 暂存 `add_documents` 在线程执行（`knowledge.py:1217-1222`，`add_documents.py:294-355`：内容哈希去重 `:322-324`、已在 `raw/` 的就地索引 `:331-333`、同名不同内容改名共存 `:276-292,:340-348`）→ 逐文件 `RAGService.add_documents`（`add_documents.py:357-423`，哈希记录也进线程 `:391`）→ 失败显式记入 `DocumentIndexResult`（`:45-83`），不再靠"无异常即成功"。
4. LightRAG 走整批持有写所有权的批量路径（`add_documents.py:425-477`）；索引已发布但记账失败时不把 KB 打成 error（`knowledge.py:1296-1298`、`:1348-1360`）。

### 3.3 重建索引（POST /{kb}/reindex）
- embedding 签名匹配且探针判定有效时直接 noop（`knowledge.py:4086-4100`，有效性=`provider ready`+向量维度校验，`:945-973`）；空 KB 换 embedding 模型只更新绑定（`knowledge.py:4042-4059`）。
- `run_reindex_task` 重建后按**实际进入索引的文件**重放 `file_hashes`（`knowledge.py:3775-3789`、`:3910`、`:3823-3824`），畸形文件不会污染去重记录。

### 3.4 检索（chat → rag_search）
1. `rag_search` 解析多用户可见性（`deeptutor/tools/rag_tool.py:36-43`）→ `RAGService.search`（`service.py:85`）。
2. PageIndex 家族拒绝向量检索，要求走其工具（`service.py:96-108`）；其余按 `_resolve_provider`（`:56-60`，`deeptutor/services/rag/provider_binding.py:45`）路由。
3. LlamaIndex 读路径：按当前 embedding 签名选版本（`pipeline.py:279-281` → `index_versioning.py:266-281,:324-341`），无匹配索引返回 `needs_reindex` 提示而不是报错（`pipeline.py:283-298`）；检索在线程执行 `storage.retrieve_nodes`（`pipeline.py:303-309` → `storage.py:293`），索引加载带 2 槽 LRU 缓存（`storage.py:213-216`，key 含 mtime 与凭据指纹 `:229-255`）。
4. 混合检索：BM25 + QueryFusion（`pipelines/llamaindex/retrievers.py:55,:143`，小语料 clamp 防崩 `:55-60`），可选 rerank（`retrievers.py:175` → `rerank.py`）；默认 hybrid profile（`pipelines/llamaindex/config.py:9-11,:69`）。
5. 上层聚合：`SmartRetriever` 多查询并发 + 汇总（`deeptutor/services/rag/smart_retriever.py:18-47`，入口 `service.py:286-300`）。

## 4. #1481 / #1478 修复后的现状

- **#1481（空 KB 首次上传 bootstrap，PR #1488 已合并）**：`DocumentAdder` 构造时若无任何 `version-N` 目录且引擎为 llamaindex/lightrag，视为"从零建索引"放行（`add_documents.py:220-238`）；管线 `add_documents` 无已有索引时新建首个版本（`pipeline.py:422-435`）；CLI 便捷函数还有 `_bootstrap_index_from_files` 兜底（`add_documents.py:519-601,:642-652`）。PR 描述中的 "No index version exists yet." 文案在后续重构中已被探针失败摘要取代（`index_probe.py:111-133`）。破坏性版本目录仍拒绝、走 reindex（`add_documents.py:231-237`）。
- **#1478（卡死的 LlamaIndex worker 泄漏进度，PR #1480 已合并）**：现行实现已从 PR 时的 owner 槽位方案演化为：`_run_with_stall_guard` 用 `progress_live` Event 门控 heartbeat（`pipeline.py:115-124`），run 结束/失败即 `clear()`（`:158-159`），管线 finally 清全局回调槽（`:266-267,:448-449`）；批次进度实际经 ContextVar 随 `copy_context()` 进入 worker 线程（`pipeline.py:134`、`embedding_adapter.py:100-121,:155-166`），全局 `Settings.embed_model` 单槽（`embedding_adapter.py:96-98,:222`）只作兜底，因此并发 run 不再互相覆盖心跳。同 KB 同时只允许一个索引 worker（`pipeline.py:44-86`），busy 时拒绝而非静默排队。
- 两个修复都有回归测试：`tests/services/rag/test_llamaindex_pipeline_stall.py:314-425`（泄漏抑制、并发隔离）、`tests/api/test_knowledge_router.py:1079`（空 KB bootstrap 上传）、`:3132`（空 KB 索引-重试-追加全流程）。

## 5. 关键文件表

| 文件 | 职责 |
|---|---|
| `deeptutor/api/routers/knowledge.py` | 全部 KB REST 路由与三个后台任务（约 5k 行，最大单文件） |
| `deeptutor/knowledge/manager.py:318` | kb_config.json 权威状态、目录布局、连接型 KB 注册、删除 |
| `deeptutor/knowledge/initializer.py:35` | 创建期目录/元数据/首次索引 |
| `deeptutor/knowledge/add_documents.py:172` | 增量上传：暂存、去重、结构化失败结果、bootstrap |
| `deeptutor/services/rag/service.py:22` | 引擎路由 + 事件封装 + 检索归一化 |
| `deeptutor/services/rag/index_probe.py` | 各引擎索引"真就绪"探针（LlamaIndex 看 docstore/index_store，`:136-175`） |
| `deeptutor/services/rag/index_versioning.py` | 签名多版本布局与读写解析 |
| `deeptutor/services/rag/pipelines/llamaindex/pipeline.py` | 默认引擎编排：stall guard、worker 互斥、签名读写 |
| `deeptutor/services/rag/pipelines/llamaindex/storage.py` | 建索引/插文档/缓存/失败目录清理 |
| `deeptutor/services/rag/pipelines/llamaindex/embedding_adapter.py` | DeepTutor embedding → LlamaIndex 适配 + 批次进度 |
| `deeptutor/services/rag/pipelines/llamaindex/document_loader.py:73` | 多格式解析与视觉资产候选 |
| `deeptutor/tools/rag_tool.py:15` | agent 侧检索工具 |

## 6. 扩展点

- **新引擎**：在 `deeptutor/services/rag/pipelines/` 增加实现 `initialize/add_documents/search(/delete)` 的 pipeline，注册进 `factory.py`（provider 常量 `:37-41`，`KNOWN_PROVIDERS` `:49`），并在 `index_probe.py:40` 加对应探针分支——上传/重建的就绪判断完全依赖探针。
- **新文档格式**：`deeptutor/services/rag/file_routing.py:43` 的 `FileTypeRouter`（扩展名 `:333`、收集 `:386`）+ `pipelines/llamaindex/document_loader.py`。
- **新 KB 形态（外部指针型）**：参照 `kb_types.py` 中 `lightrag_server`/`ima` 的"只存连接信息、检索时 offload"模式（`kb_types.py:21-33`），manager 里加 `register_*`（如 `manager.py:931`）。
- **检索策略**：`pipelines/llamaindex/config.py` 的 vector/hybrid profile 与 top_k；rerank 挂在 `pipelines/llamaindex/rerank.py`。
- **进度/事件**：`deeptutor/knowledge/progress_tracker.py` + `progress_events.py`，管线经 progress_callback 上报（`initializer.py:199-215`）。

## 7. 已知坑与残余风险

1. **卡死的 worker 无法被中断**：stall guard 抛 `IndexingStallError` 后，同步 embedding 线程仍在跑（`pipeline.py:107-110`）；同 KB 重试被 `_ensure_index_worker_available` 拒绝（`:61-65`），错误信息明确要求等待或重启 DeepTutor（`:54-58`）。这是 #1478 修复的已知边界，真实黑洞 embedding 端点场景无法自动化验证（PR #1480 亦承认）。
2. **空 KB 的 `initialize` 拒绝空 `raw/`**：`initializer.py:177-183` 直接抛错；空 KB 的首批索引只能走 `add_documents` 的 bootstrap 路径或 web/GitHub sync 的 `initialize`（`deeptutor/services/web_source/sync.py:88`，有文件时才成立）。不要伪造空索引目录。
3. **legacy `rag_storage/` KB 必须先 reindex** 才能增量上传（`add_documents.py:211-218`），否则构造即抛错。
4. **`file_hashes` 键规则耦合**：索引与删除共用 `_raw_hash_key`（`add_documents.py:111-122`）；任何绕过 `remove_raw_document`（`:141-169`）直接删文件的做法都会留脏哈希，导致后续同路径重加被静默跳过。
5. **并发模型依赖 ContextVar**：multi-user 场景 embedding 配置经 `scoped_embedding_config` + `_operation_adapter` ContextVar 隔离（`embedding_adapter.py:196-225`）；绕过 scope 的旧式调用共享全局 `Settings.embed_model` 单例（`:222`），混用时需谨慎。
6. **索引缓存仅 2 槽**（`storage.py:215`）：同进程交替查询超过 2 个 KB 会反复全量重载索引，属设计权衡。
7. **`_matching_index_is_valid` 只做静态校验**（探针 + 向量维度，`knowledge.py:945-973`），不校验索引与 `raw/` 内容的一致性；`raw/` 被外部改动后需手动 reindex。
8. **删除文件不动向量**：`remove_raw_document` 只删文件与哈希记录，残留向量由下一次 reindex 清除（`add_documents.py:141-153` docstring 明示）。

## 8. 测试现状与覆盖空白

现有测试（本仓库可直接运行）：
- `tests/api/test_knowledge_router.py`（94 个测试函数、参数化后 124 例）：创建/上传/重建/空 KB bootstrap/重试/权限等路由级行为。
- `tests/api/test_knowledge_zip_upload.py`（4）、`tests/api/test_knowledge_progress_ws.py`（进度 WS）。
- `tests/knowledge/`（20 个文件）：manager 状态与删除、manifest、naming、DocumentAdder provider 行为（16 例）、linked folder 同步、GitHub/web 来源元数据。
- `tests/services/rag/`（44 个文件）：llamaindex 15 个（stall 13 例、embedding 失败/角色、FAISS、ingestion、索引缓存上限、rerank、storage layout、document loader）、`test_index_probe.py`（10 例）、`test_index_versioning.py`、`test_preflight.py`、`test_file_routing.py`、`test_pipeline_integration.py`，以及 graphrag/lightrag/ima/kiwix/pageindex/weknora 各自管线测试。

覆盖空白（写导读时核对过）：
1. `SmartRetriever` 仅 2 例且 mock 掉了 `_aggregate`（`tests/services/rag/test_rag_pipelines.py:287-325`）；`_generate_queries`/`_aggregate` 的 LLM 路径与异常兜底（`smart_retriever.py:49-81`）无直接测试。
2. `run_reindex_task` 的哈希重放逻辑（`knowledge.py:3775-3910`）只有间接覆盖（删除/重加流程 `tests/api/test_knowledge_router.py:1804,:3193`），没有"畸形文件被跳过后哈希不重放"的针对性用例。
3. 跨引擎并发（同一 KB 上传与 reindex 竞争 worker 槽 `pipeline.py:61-86`）无并发测试；stall 相关测试均用假 embedding。
4. 索引缓存失效只测了 mtime 维度（`test_llamaindex_index_cache_bounds.py`），凭据轮换维度（`storage.py:250-255`）未单独覆盖。
5. PR #1480 自列的未验证项：真实卡死 embedding provider 下"超时→重试→进度不再串台"的端到端场景（需真机 Ollama）。

## 9. 快速验证命令

```bash
# CI 同款最小运行时配置（见 .github/workflows/tests.yml:272-281）后：
pytest -q tests/services/rag/test_llamaindex_pipeline_stall.py tests/services/rag/test_index_probe.py
# 本机 v1.6.12：24 passed
pytest -q tests/api/test_knowledge_router.py -k "empty or bootstrap"
# 本机 v1.6.12：8 passed, 116 deselected
```
