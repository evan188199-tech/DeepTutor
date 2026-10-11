# 嵌入并发与重试未设防路径扫描（只读）

- 日期：2026-10-11
- 基线：origin/main `6cf793bd8`（release: v1.6.14）
- 对照样本：`259bb43e3`（#1797，间距锁改线程级 + batch_delay=0 不串行）、`45bece1b4`（#1783，同题修复 + 本地 Lemonade）
- 范围：知识库索引、RAG 管道（LlamaIndex / LightRAG / GraphRAG / IMA）、watching/阅读辅助的嵌入/向量化入口
- 方法：只读扫描，不改任何代码。模式：`asyncio.gather`/`TaskGroup` 无 semaphore、retry 无退避、共享 httpx 客户端竞态
- 结论（跑通：PASS）：4 项 MEDIUM、3 项 LOW、1 项 INFO；14 项误报排除；附 5 条可拆补测卡

## 风险分级说明

- HIGH：可预期触发数据损坏 / 服务不可用
- MEDIUM：限流或本地后端过载下整跑失败或明显放大压力，需补测
- LOW：特定条件下的健壮性/性能问题
- INFO：观察项，当前行为可接受

## 命中清单

### M-1 嵌入层无全局/按后端并发上限（本地后端过载放大）
- 位置：
  - `deeptutor/services/embedding/client.py:67-85`（`_wait_for_request_slot` 只做 batch_delay>0 的起步间隔，不限在飞请求数）
  - `deeptutor/api/routers/knowledge.py:4249-4262`（每个 re-index 请求一个 background worker）
  - `deeptutor/api/routers/knowledge.py:4119-4124`（仅 per-KB 409 锁，无全局上限）
  - `deeptutor/services/rag/pipelines/llamaindex/pipeline.py:61-88`（per-KB worker claim，跨 KB 并发不受限）
  - `deeptutor/services/rag/pipelines/lightrag/config.py:185-196`（LightRAG 只透传 `llm_model_max_async`，embedding 并发交 SDK 默认）
- 说明：#1779 修复后 batch_delay=0 时并发被有意放行（正确方向），但适配层没有按 base_url 的信号量；多 KB 同时 re-index、LightRAG 内部并发、检索查询可同时打向同一个本地单进程后端（Lemonade/vLLM/Ollama）。#1783 之后未补显式上限。
- 风险：MEDIUM（本地后端过载、批量索引互相拖慢、无自保）
- 补测建议：在 adapter 层加按 endpoint 的 `asyncio.Semaphore`（可配置），或向 LightRAG 构造参数透传 `embedding_func_max_async`；补一条"多 worker 并发时在飞请求数 ≤ 上限"的回归测试。

### M-2 cohere 适配器完全无重试
- 位置：`deeptutor/services/embedding/adapters/cohere.py:130-139`
- 说明：单发请求，`raise_for_status()` 直抛；429/5xx/瞬时网络错误不重试、无退避。上层 `EmbeddingClient.embed_texts` 首个失败批次即终止整跑（`deeptutor/services/embedding/client.py:158-176`），长索引被一次限流报废。
- 风险：MEDIUM
- 补测建议：注入 429/`httpx.TransportError`，断言带退避重试后成功；对齐 `openai_compatible.py:334-348` 的指数退避模式。

### M-3 jina 适配器完全无重试
- 位置：`deeptutor/services/embedding/adapters/jina.py:116-125`
- 说明：与 M-2 同模式，单发 + `raise_for_status()`；429 无 Retry-After 处理。
- 风险：MEDIUM
- 补测建议：同 M-2，可并入同一契约测试（见补测卡 E-1）。

### M-4 dashscope 原生适配器无重试、无 429 识别
- 位置：`deeptutor/services/embedding/adapters/dashscope_native.py:95-167`（`_embed_multimodal` 101-135、`_embed_text` 137-166、`_raise_on_error` 168-179）
- 说明：SDK 同步调用转 `asyncio.to_thread`，非 200 一律 `RuntimeError`（含 429），无重试无退避；`_run_adapter_with_retry`（LightRAG 侧）只覆盖 LightRAG 路径，普通 KB 索引路径没有兜底。
- 风险：MEDIUM
- 补测建议：对 `TextEmbedding.call` 打桩返回 429/限流码，断言重试行为（补或明确豁免 `tests/services/embedding/test_dashscope_adapter.py`）。

### L-1 ollama 适配器无瞬时错误重试
- 位置：`deeptutor/services/embedding/adapters/ollama.py:62-109`
- 说明：`ConnectError`/`TimeoutException` 只翻译成人读错误直抛，不重试；本地服务在负载抖动（模型加载、内存压力）时一次失败报废整批索引。`timeout=self.request_timeout` 未区分 connect/read 阶段。
- 风险：LOW-MEDIUM（仅本地路径）
- 补测建议：注入一次 ConnectError 后成功的假客户端，断言重试 1-2 次成功；断言 connect/read 超时分离。

### L-2 LightRAG 嵌入并发参数未透传
- 位置：`deeptutor/services/rag/pipelines/lightrag/config.py:185-196`（`constructor_kwargs_from_settings`）
- 说明：只透传 `llm_model_max_async`/`entity_extract_max_gleaning`/`default_llm_timeout`；`embedding_func_max_async`、`embedding_batch_num` 用 lightrag-hku SDK 默认值，与 M-1 叠加时本地后端压力不可调。
- 风险：LOW（SDK 默认 8 仍是有界的，但不受 DeepTutor 设置控制）
- 补测建议：透传设置并加默认值断言测试。

### L-3 LlamaIndex 同步嵌入路径每批新建事件循环
- 位置：`deeptutor/services/rag/pipelines/llamaindex/embedding_adapter.py:127-133, 183-193`
- 说明：`_run_in_new_loop` 每次同步嵌入调用新建并关闭一个 loop；默认 executor 线程池下多线程并发索引时 loop 创建开销放大。非竞态（loop 不共享），属健壮性/性能。
- 风险：LOW
- 补测建议：改为 per-thread 复用 loop（`threading.local`），补并发嵌入吞吐对比测试。

### I-1 openai_compatible 429 重试台阶为固定 ≥60s
- 位置：`deeptutor/services/embedding/adapters/openai_compatible.py:235-273`（8 轮限流重试，`asyncio.sleep(max(retry_after or 0.0, 60))`）
- 说明：Retry-After 优先、无头时保守 60s，8 轮后仍 429 则抛 `EmbeddingProviderError`；transport 错误另有指数退避（334-348）。行为可接受，列为观察项：限流期间 worker 最长阻塞约 8×60s，无全局预算。
- 风险：INFO

## 误报排除（附理由）

| 位置 | 排除理由 |
| --- | --- |
| `deeptutor/reading/captions.py:124` | `asyncio.Semaphore(image_description_limits())`（默认 4、上限 16，`pipelines/llamaindex/config.py:171-180`）+ 每图 `wait_for` 超时 + 异常隔离 |
| `deeptutor/services/rag/pipelines/llamaindex/document_loader.py:447,496` | 同一 semaphore + timeout 保护（380、389、459）；图片描述路径，非嵌入 |
| `deeptutor/services/web_source/snapshot_assets.py:67` | `Semaphore(4)` + `MAX_SNAPSHOT_IMAGES` 截断（60 行） |
| `deeptutor/services/rag/pipelines/ima/pipeline.py:159` | hydration 扇出受 `DEFAULT_HYDRATION_BUDGET=4`（`ima/sources.py:33`）约束，`return_exceptions=True` 隔离 |
| `deeptutor/services/rag/smart_retriever.py:26` | 扇出受 `max_queries=3` 约束（只读检索） |
| `deeptutor/agents/loop/pipeline.py:1496` | `KB_SEED_MAX_KBS=3` 截断（`pipeline.py:102`） |
| `deeptutor/services/reading_hints.py:177` | 恒定 2 路（本地线程读 + 会话读取），无嵌入网络调用 |
| `deeptutor/services/courses_state.py:219,348` | 固定 6 类 loader / 2 任务扇出，非嵌入路径 |
| `deeptutor/services/embedding/adapters/openai_sdk.py`（`_build_client`） | 每次 `embed` 新建 `AsyncOpenAI` + `max_retries=2`（SDK 自带退避），`finally` 关闭，无共享客户端竞态 |
| `deeptutor/services/rag/pipelines/lightrag/config.py:113-137` | `_run_adapter_with_retry`：3 次有界重试、1s/2s 退避、Retry-After 封顶 60s——正是对照基准（259bb43e3/45bece1b4）期望的"好模式"，与 M-2/M-3/M-4 形成反差 |
| `deeptutor/services/keypool.py:26-60` | `next`/`mark_429` 全部持 `threading.Lock` |
| `deeptutor/services/embedding/client.py:44-64` | 259bb43e3 修复后的 `_thread_guard` + 线程级间距锁模式正确（仅保护时间戳更新，不包住 HTTP 调用） |
| `deeptutor/agents/research/pipeline.py:1191` | `max_parallel_topics` 按深度策略 ≤3（`agents/research/request_config.py:201-227`） |
| `deeptutor/api/routers/video_learning.py:465-494`、`deeptutor/reading/ingestion.py:839-845` | 每请求独立 `httpx.AsyncClient`（context manager），无共享客户端竞态 |

未发现嵌入/向量化路径上的共享 httpx 客户端竞态：所有 embedding adapter 均为每调用新建客户端（有连接开销但无竞态）；共享长连接客户端（partners channels 的 `self._http`）不在本卡范围。

## 可拆补测卡条目

1. **E-1（建议优先）** embedding 适配器统一重试契约测试：对 cohere/jina/dashscope_native 注入 429 与 `httpx.TransportError`，断言有界重试 + 退避 + Retry-After 尊重；如判定"无重试"为预期，则在适配器 docstring 明确豁免并记录（对应 M-2/M-3/M-4）。覆盖文件：`tests/services/embedding/`。
2. **E-2** 嵌入在飞并发上限回归测试：先实现 per-endpoint semaphore（或 LightRAG `embedding_func_max_async` 透传），再测"多 KB 并发 re-index 时同一 base_url 在飞请求数 ≤ 上限"（对应 M-1/L-2）。
3. **E-3** LightRAG `embedding_func_max_async`/`embedding_batch_num` 设置透传卡（对应 L-2，可与 E-2 合并）。
4. **E-4** ollama 本地瞬时错误重试 1-2 次的适配器测试（对应 L-1）。
5. **E-5** LlamaIndex 同步嵌入 per-thread loop 复用 + 跨线程间距锁并发语义断言（对应 L-3；现有 `tests/services/embedding/test_client_runtime.py` 可作为落点扩展）。

## 扫描命令备忘

- `grep -rn "asyncio.gather\|TaskGroup\|asyncio.wait(" deeptutor --include=*.py`
- `grep -rn "retry\|backoff\|Semaphore" deeptutor/services/embedding deeptutor/services/rag`
- `grep -rn "httpx.AsyncClient\|aiohttp.ClientSession" deeptutor --include=*.py`
- 基线对照：`git show 259bb43e3 -- deeptutor/services/embedding/client.py`、`git show 45bece1b4 -- deeptutor/services/config/provider_runtime.py`

## 去重说明

上游开放 PR 中未发现与本扫描主题（嵌入并发/重试审计）重叠的实现或 PR；#1797/#1783 已合并入基线，属本次对照样本而非撞车对象。
