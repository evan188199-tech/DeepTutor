# scan: 检索索引/rerank 配置面盘点（AGEN-1856，#304 配套前置）

- 基线：HKUDS/DeepTutor `origin/main` @ `6cf793bd868ba5ecbe64722936d4be8fab5a01df`（v1.6.14，2026-10-12 fetch）
- 范围：向量索引类型（FAISS flat/HNSW）与 rerank 相关配置项的「定义 / 透传 / 消费」三方对照
- 视角声明（去重）：本卡只做**配置接线视角**。行为视角归 test-llamaindex-rerank；LightRAG 参数轴归 scan-lightrag-params；embedding 并发归 scan-embedding-concurrency。
- 结论速览：索引类型 4 项 + rerank 2 项全部已端到端接线（#1044/#1045 已合并入 main）；发现死代码路径 1 处、未触发缓存清理 1 处、缺失/缺口 5 项，逐条附 path:line 见下文。产品代码零改动。

## 1. 配置矩阵（LlamaIndex 引擎）

消费链路总览：

```
Web EngineDetail.tsx ──PUT /api/knowledge-bases/rag-pipelines/llamaindex/config──▶ knowledge.py
  → RuntimeSettingsService.save_llamaindex/_normalize_llamaindex (runtime_settings.py)
  → load_llamaindex_settings（含 env 覆盖，仅 retrieval_profile）
  → llamaindex/config.py（retrieval_config_from_settings / vector_index_config_from_settings）
  → 消费点：
      索引构建：ingestion.py → vector_store.py:_new_faiss_index（仅全量构建时生效）
      查询：pipeline.py → storage.py → retrievers.py:retrieve_nodes → rerank.py:rerank_nodes
```

### A. 向量索引类型

| # | 配置项 | 默认 | 定义（持久化层） | 定义（管道层） | 透传（API） | 透传（Web） | 实际消费 | 生效时机 | 状态 |
|---|--------|------|------------------|----------------|-------------|-------------|----------|----------|------|
| 1 | `vector_index_type` | `flat` | `runtime_settings.py:315-319,329`（枚举）、`988-990,1008`（校验/归一） | `pipelines/llamaindex/config.py:12-14,58,77-82,135` | `api/routers/knowledge.py:1573-1591`（Update 模型）、`1593-1630`（GET/PUT） | `web/features/knowledge/api/client.ts:107`、`EngineDetail.tsx:456,615-620`、locales en/zh `app.json`「Vector index」 | `vector_store.py:188-199`（`_new_faiss_index` 分支），由 `config.py:128-139` → `ingestion.py:102-104` 注入 | 仅**下一次全量重建**（`ingestion.py:91-110`；增量插入走既有索引 `ingestion.py:115-118`） | 已接线 |
| 2 | `hnsw_m` | 32（夹 4..64） | `runtime_settings.py:330,1009` | `config.py:59,136` | `knowledge.py:1583` | `client.ts:108`、`EngineDetail.tsx:457,646-649`（HNSW graph degree） | `vector_store.py:191-195`（`IndexHNSWFlat` 第 2 参） | 同上（build-time） | 已接线 |
| 3 | `hnsw_ef_construction` | 200（夹 16..512） | `runtime_settings.py:331,1010-1012` | `config.py:60,137` | `knowledge.py:1584` | `client.ts:109`、`EngineDetail.tsx:458,653-656` | `vector_store.py:196` | 同上（build-time） | 已接线 |
| 4 | `hnsw_ef_search` | 64（夹 1..512） | `runtime_settings.py:332,1013` | `config.py:61,138` | `knowledge.py:1585` | `client.ts:110`、`EngineDetail.tsx:459,660-663` | `vector_store.py:197`（build 时写入并随 `faiss_write_index` 持久化） | 同上（build-time）；查询期 `load_index`（`vector_store.py:249-274`）**不重读设置**，efSearch 取持久化值 | 已接线（注意：改值对既有索引无效果） |

### B. rerank

| # | 配置项 | 默认 | 定义（持久化层） | 定义（管道层） | 透传（API） | 透传（Web） | 实际消费 | 生效时机 | 状态 |
|---|--------|------|------------------|----------------|-------------|-------------|----------|----------|------|
| 5 | `reranker_model` | `""`（空=关闭） | `runtime_settings.py:327,1006`（截断 200） | `config.py:38,72-74,123`（`normalize_reranker_model`） | `knowledge.py:1580` | `client.ts:103`、`EngineDetail.tsx:454,589-591`、locale 提示「Requires the optional rag-rerank extra」 | `retrievers.py:210-218` → `rerank.py:84-127`（CrossEncoder，LRU 缓存上限 2，`rerank.py:15-17,33-65`） | 下次查询 | 已接线（依赖可选 extra `pyproject.toml:272` + `requirements/rag-rerank.txt`；缺包/加载失败降级为一阶段排序，`rerank.py:45-58`） |
| 6 | `rerank_top_k` | 50（夹 1..100） | `runtime_settings.py:328,1007` | `config.py:39,46-51,124`（`rerank_candidate_top_k`，未配置模型时返回请求值） | `knowledge.py:1581` | `client.ts:105`、`EngineDetail.tsx:455,595-598`（Rerank candidates） | `retrievers.py:202`（一阶段候选扩容）→ `rerank.py:97,116`（截断） | 下次查询 | 已接线 |

### C. 关联上游项（rerank 候选链依赖，一并核对）

| # | 配置项 | 状态 | 消费点 |
|---|--------|------|--------|
| 7 | `retrieval_profile`（vector/hybrid） | 已接线；env 覆盖 `DEEPTUTOR_RAG_RETRIEVAL_PROFILE` / `RAG_RETRIEVAL_PROFILE` 唯一生效路径在持久化层 `runtime_settings.py:973-982` | `retrievers.py:160,176`（分支）、降级信号 `effective_retrieval_profile` `retrievers.py:67-76` → `knowledge.py:1602-1608` |
| 8 | `top_k` | 已接线 | `pipeline.py:324`（`kwargs.get("top_k") or default_top_k()`，`config.py:142-147`）→ `storage.py:288-290` |

## 2. 死配置 / 缺失清单（逐条 path:line）

**死配置（已定义、无产品消费）**

- D1 `retrieval_config_from_env()`（`pipelines/llamaindex/config.py:85-97`）：产品代码零调用，唯一调用方是测试 `tests/services/rag/test_llamaindex_storage_layout.py:254`。同名 env 变量的实际生效路径是 `runtime_settings.py:973-982` → `retrieval_config_from_settings`（`config.py:107-125`）。该工厂与真实路径重复，属死代码路径（`__all__` 导出于 `config.py:196`）。
- D2 `clear_reranker_cache()`（`pipelines/llamaindex/rerank.py:20-23`）：docstring 写「used by tests and settings changes」，但设置保存链路（`knowledge.py:1619-1630` PUT → `runtime_settings` save）无任何调用点，仅测试调用（`tests/services/rag/test_llamaindex_rerank.py:16-19`）。后果：切换 reranker_model 后旧模型对象滞留进程内 LRU（上限 2，`rerank.py:17`），不影响正确性（缓存按模型名键控），仅内存驻留。

**缺失 / 缺口**

- M1 env 覆盖通道缺失（**有意设计**，`runtime_settings.py:974` 注释明示仅 retrieval_profile 有历史 env 通道）：`reranker_model`、`rerank_top_k`、`vector_index_type`、`hnsw_m/ef_construction/ef_search` 均无 env 通道。
- M2 索引类型/参数变更无 per-KB `needs_reindex` 联动：PUT config 仅存盘（`knowledge.py:1619-1630`）；`needs_reindex` 状态仅在 embedding 变更（HTTP 409 引导）与 rag_provider 变更路径设置（`knowledge.py:2093-2119`）。切换 hnsw 后既有 KB 继续用旧索引服务，UI 只有全局静态提示「Applies on the next full re-index」（`EngineDetail.tsx:610-613`）。
- M3 rerank 无「effective」信号：profile 有配置值 vs 实际值对照（`retrievers.py:67-76`、GET 返回 `effective_retrieval_profile`，`knowledge.py:1602-1608`）；而 sentence-transformers 缺失或模型加载失败时 rerank 静默降级，仅 WARNING 日志（`rerank.py:45-58`），API/Web 无法感知「配置了 rerank 但未生效」。
- M4 `fusion_num_queries` 有消费（`retrievers.py:186`）但有意不可调：数据类字段存在（`config.py:37`），设置层显式不暴露（`runtime_settings.py:309-311`、`config.py:111-113`）。非死配置，标注避免误判。
- M5 其他 RAG 引擎（graphrag / lightrag / weknora / ima / kiwix / pageindex）无索引类型与 rerank 配置面：全库 grep 确认 FAISS 构造与 `rerank_nodes` 仅被 llamaindex 管道消费（`vector_store.py:188-199` 唯一 `IndexFlatIP/IndexHNSWFlat` 构造点）。LightRAG 轴不在本卡展开（归 scan-lightrag-params）。
- M6 #304 issue 正文引用的 affected files 已不存在：`deeptutor/services/rag/components/indexers/vector.py`、`deeptutor/services/rag/pipeline.py`、`components/retrievers/dense.py` 在 main 基线上均已移除；实现实际落点为 `deeptutor/services/rag/pipelines/llamaindex/`。issue 文件清单过时。

## 3. 上游 #1044/#1045 复核结论（中文审查）

上游 issue #304 已有两条**已合并** PR（均包含于本基线 `origin/main`）：

- #1044 `feat(rag): add opt-in HNSW vector indexes (#304)`，merge commit `8c9a0687d`（2026-08-31）
- #1045 `feat(rag): add optional cross-encoder reranking (#304)`，merge commit `9e3ef6dc3`（2026-08-31）

审查结论：

1. 与诉求一致且向后兼容：HNSW 为 opt-in（默认 `flat`，`runtime_settings.py:329`；`normalize_vector_index_type` 兜底回 flat，`config.py:77-82`）；rerank 默认空模型关闭（`rerank_top_k` 仅在配置模型后参与候选扩容，`config.py:46-51`）。
2. 配置三层（持久化 settings / REST API / Web UI）齐全，校验夹值一致：API/Web 的 min/max（如 hnsw_m 4..64、rerank_top_k 1..100）与 `_normalize_llamaindex` 夹值一致（`runtime_settings.py:1007-1013`）。
3. 实现落点与 issue 正文不同（M6），issue 文件清单需以本矩阵为准。
4. #304 issue 目前仍为 OPEN（上游未随合并关闭）。
5. 若「up-304 切片一」计划自行实现 HNSW/rerank，则该范围**上游已交付**，切片应改为补缺口（M2 的 per-KB 重建联动、M3 的 rerank effective 信号、D2 的设置变更缓存清理），避免重复实现。

## 4. 取证命令（均在基线 worktree 执行）

```
git -C /Users/Shared/DeepTutor fetch origin main
git -C /Users/Shared/DeepTutor worktree add <wt> -b scan-retrieval-config-parity-1856 origin/main
rg -n "index_type|hnsw|ef_construction|ef_search|IndexFlat|IndexHNSW" deeptutor --type py
rg -n "reranker_model|rerank_top_k|rerank_nodes|retrieve_nodes|clear_reranker_cache|retrieval_config_from_env" deeptutor tests --type py
rg -n "reranker_model|rerank_top_k|vector_index_type|hnsw" web/features/knowledge web/locales
gh issue view 304 / gh pr view 1044 / gh pr view 1045 -R HKUDS/DeepTutor
```
