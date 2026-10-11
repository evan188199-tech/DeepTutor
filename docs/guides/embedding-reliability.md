# services/embedding 可靠性面导读（guide-embedding-reliability）

- 基线：`origin/main @ 6cf793bd8`（v1.6.14）。文内 `path:line` 均为该基线、相对仓库根；行号格式 `文件:行`。
- **范围与边界**：本文只覆盖 `deeptutor/services/embedding/` 及其被 RAG 管道/入口消费的衔接点。LLM 客户端轴（`services/llm/`）归 guide-llm-clients，不重复；各 RAG 管道内部逻辑只写"嵌入调用怎么进去、重试/并发/超时在哪一层生效"。
- 证据来源：`scan/embedding-concurrency-20261011` 与 `scan/log-exception-bodies-20261010` 两份只读报告（P1/P2 仅引用行号，细节见报告原文）。本文全部行号经当前基线逐一复核，个别与报告略有出入，以本文为准。
- 一句话：嵌入层是"每调用新建客户端 + 适配器各自为政"的结构——openai_compat/gemini 有重试，cohere/jina/dashscope/ollama 完全没有；全局只有可选的起步间隔，没有在飞并发上限；脱敏只有 gemini 一家做对了，且错误体还会经统一异常链漏进 client 层日志。

## 1. 适配器 × 可靠性决策矩阵

绑定向适配器的映射见 `deeptutor/services/embedding/client.py:23-36`（`EMBEDDING_PROVIDERS`→`ADAPTER_BACKENDS`，注册表 `deeptutor/services/embedding/adapters/__init__.py:15-23`）。

| 适配器 | 限流 429 重试 | 瞬时错误重试 | 超时 | 在飞并发控制 | 日志脱敏 |
| --- | --- | --- | --- | --- | --- |
| `openai_compatible`（openai/azure/siliconflow/vllm/lemonade/custom…） | 8 轮，`max(Retry-After, 60s)` + KeyPool 轮换（`adapters/openai_compatible.py:243-273`） | transport 5 轮指数 1/2/4/8/16s（`adapters/openai_compatible.py:147-149,334-354`）；`encoding_format` 400 自愈 1 轮（`:277-286`） | 四段超时：connect=10 / read≥60 / write=10 / pool=10（`:224-229`） | 无上限；每请求新建 httpx 客户端（`:237-239`） | ✗：4xx 整响应体落日志（2000 字符截断，`:287`）；transport 异常消息（含 URL/host）进 warning/error（`:344,352`） |
| `gemini`（继承 openai_compat 常量） | 6 轮，`max(Retry-After, 5·2^attempt)`，**无** key 轮换（`adapters/gemini.py:310-333`） | transport 5 轮指数退避（`:365-390`） | 同上四段（`gemini.py:294-299`） | 无上限；每请求新建客户端（`:305-308`） | ✓ 正向参照：`_redacted_body`（`gemini.py:117-143`）+ `_redacted_url`（`:112-115`），body 500 字符封顶（`:338-343,354-359,368-373`） |
| `cohere` | 无（`adapters/cohere.py:130-139`） | 无（同处） | 标量 timeout，作用于 connect/read/write/pool 四相（`:130-132`） | 无上限；每请求新建客户端 | ✗：HTTP≥400 整响应体落 error 日志（`:135-136`） |
| `jina` | 无（`adapters/jina.py:116-125`） | 无（同处） | 标量 timeout（`:116-118`） | 无上限；每请求新建客户端 | ✗：同 cohere 同型（`:121-122`） |
| `ollama` | 无 | 无：`ConnectError`/`TimeoutException` 只翻译成人读错误直抛（`adapters/ollama.py:95-105`），`HTTPError` 记日志后原样抛（`:107-109`） | 标量 timeout，不区分 connect/read（`:63-65`） | 无上限；每请求新建客户端 | ✗（敏感度低，本地端点）：httpx 错误体落 error 日志（`:108`） |
| `dashscope_native`（aliyun） | 无：非 200 一律 `RuntimeError`（含 429），`adapters/dashscope_native.py:168-179` | 无（同处） | **未传超时**：SDK 调用不带 timeout 参数（`:126-132,157-163`），吃 SDK 默认值 | 无上限；`asyncio.to_thread` 占用默认线程池（`:126,157`） | ✗：provider `code/message` 拼进 RuntimeError 上抛（`:175-179`），最终经 client 层落日志（见 §4） |
| `openai_sdk`（遗留） | SDK 内建 `max_retries=2`（指数退避，`adapters/openai_sdk.py:56`） | 同左 | `max(request_timeout, 60)`（`:50,57`） | 无上限；每次 `embed` 新建 + `finally` 关闭（`:44-58,110-114`） | ✗：`exc.response.text`（回退 `str(exc)`）存进错误对象 body（`:83-95`） |

通用事实：`EmbeddingClient.embed` 自身**零重试**，首个失败批次即终止整跑（`deeptutor/services/embedding/client.py:158-176`）；所有适配器共享的 `EmbeddingProviderError` 会把 500 字符 body 摘要拼进异常消息（`adapters/base.py:113-126`）。

## 2. 重试细节与对照

- **有退避的两个正面样例**：openai_compat 的 429 尊重 `Retry-After`、无头保守 60s、8 轮后抛结构化错误（`openai_compatible.py:250-273`）；transport 错误指数退避并覆盖全部 `httpx.TransportError` 子类（`:334-354`）。`_MAX_RETRIES=5`/`_RETRY_BACKOFF=1.0`/`_RATE_LIMIT_BACKOFF=5.0` 三个常量在 `:147-149`。
- **KeyPool 轮换只存在于 openai_compat 路径**：429 时 `mark_429` + 重取 key、池全冷却时再等 65s（`openai_compatible.py:244-263`）；KeyPool 本身两击冷却 60s（`deeptutor/services/keypool.py:12-58`）。gemini 虽继承 `_auth_api_key` 但 429 分支不调 `mark_429`（`gemini.py:310-333`）。
- **LightRAG 适配器重试是好模式但不管嵌入**：`_run_adapter_with_retry` 3 次有界、1s/2s 退避、Retry-After 封顶 60s、可重试状态码 {408,429,500,502,503,504,529}（`deeptutor/services/rag/pipelines/lightrag/config.py:51-54,113-139`），仅挂在 llm（`:313`）与 vision（`:375`）两个 func 上；`build_embedding_func` 的嵌入调用**不经过它**（`:411-425`）。
- **限流预算无全局上限**：openai_compat 8×60s + transport 重试全部发生在单批次内，多 KB 并发时最坏阻塞时长线性叠加，无全局预算（对照 `openai_compatible.py:235` 的注释自述）。
- 已有测试锚点：429/Retry-After 解析 `tests/services/embedding/test_retry_after.py`；批处理/间距/校验 `tests/services/embedding/test_client_runtime.py`。

## 3. 超时细节

- 配置默认值：`request_timeout=60`、`batch_size=10`、`batch_delay=0.0`（`deeptutor/services/embedding/config.py:28-30`；解析与钳制 `deeptutor/services/config/provider_runtime.py:1208-1212,1630-1635`）。
- openai_compat/gemini 用 `httpx.Timeout` 显式分段，read 段 `max(request_timeout, 60)`（`openai_compatible.py:224-229`；`gemini.py:294-299`）；cohere/jina/ollama 把标量直接给 httpx（四相同值）；dashscope 不传超时（`dashscope_native.py:126-132,157-163`）。
- client 层对单批次**无 `wait_for` 包装**（`client.py:159-160`）；超时兜底发生在上层：LlamaIndex 索引走 600s 停滞守卫（`deeptutor/services/rag/pipelines/llamaindex/pipeline.py:41,112`），连接探测走 25s 预算（`deeptutor/services/config/settings_spec.py:503,586-603`；`deeptutor/api/routers/system.py:528` 测试连接入口）。

## 4. 在飞并发与循环复用

- **全局无信号量**：`services/embedding/` 全目录无任何 `Semaphore`；唯一的节流是 `batch_delay>0` 时的起步间隔钟 `_wait_for_request_slot`（`client.py:70-86`），线程级锁只保护时间戳更新、不包住 HTTP 调用（`client.py:42-47,56-68`；#1797 后 batch_delay=0 即完全放行）。
- **loop 复用点**：同步嵌入路径每调用新建并关闭一个事件循环 `_run_in_new_loop`（`deeptutor/services/rag/pipelines/llamaindex/embedding_adapter.py:127-133`），三个同步包装都走它（`:183-193`）；异步查询路径直接 `await client.embed`（`:135-153`）。`embed_sync` 在已有 loop 时开临时线程跑新 loop（`client.py:292-304`）。
- **入口并发上限**：KB re-index 每请求一个后台任务（`deeptutor/api/routers/knowledge.py:4248-4262`），仅 per-KB 409 互斥（`:4117-4127` + `pipeline.py:68-88`），跨 KB 并发不受限；LightRAG 只透传 LLM 侧 `llm_model_max_async`，`embedding_func_max_async`/`embedding_batch_num` 用 SDK 默认（`lightrag/config.py:184-196`）。
- 单例缓存换装竞争已被有意容忍：`get_embedding_client` 配置变化时换新实例、旧调用方持有旧 client 跑完（`client.py:307-318`）。

## 5. 日志脱敏面（嵌入域）

传播链：适配器错误对象（`EmbeddingProviderError.body`，`base.py:88-126`）→ `EmbeddingClient.embed` 的失败日志 `{exc}` + 完整 traceback（`client.py:161-176`，自述进 task log stream / KB diagnostics）→ 任务日志流。所以**即使适配器自身不打 body 日志，body 也会经这一跳落日志**。

| 位置 | 现状 | 对齐方向 |
| --- | --- | --- |
| `adapters/cohere.py:135-136` | HTTP≥400 整响应体落 error 日志 | 参照 `gemini.py:117-143` 的 `_redacted_body` |
| `adapters/jina.py:121-122` | 同上同型 | 同上 |
| `adapters/openai_compatible.py:287` | HTTP≥400 响应体落日志（2000 字符截断），**两份扫描报告的 P1/P2 清单均未列入** | 同上；修 cohere/jina 时应一并处理 |
| `adapters/openai_sdk.py:83-95` | `exc.response.text` 存入 `EmbeddingProviderError.body`，经 `base.py:113-126` 拼 500 字符摘要外发 | 构造时脱敏或只留 status |
| `client.py:161-176` | 失败日志带 `{exc}` + `traceback.format_exc()`；当异常为 `EmbeddingProviderError` 时含上游 body 摘要 | 改记 `type(exc).__name__` + 已有结构化字段（binding/model/batch_index 已在消息里） |
| `adapters/openai_compatible.py:344,352` | transport 异常消息（含 URL/host）进日志 | 类型名 + status |
| `adapters/ollama.py:108` | httpx 错误体落日志（本地端点，敏感度低） | 顺带整改 |
| `client.py:208,284` | 进度回调失败 `{exc}` + `exc_info=True`（内部回调，敏感度低） | P3 级，顺带 |
| `adapters/gemini.py:112-143` | ✓ 正向参照：URL 脱敏 + body 对 key/回显文本脱敏后 500 字符截断 | 作为统一 helper 的蓝本 |

## 6. RAG 管道与入口接入点

| 接入点 | 嵌入来源 | 重试/超时/并发归属 |
| --- | --- | --- |
| LlamaIndex（默认 RAG、多模态图片节点 `deeptutor/services/rag/pipelines/llamaindex/document_loader.py:345`） | `CustomEmbedding` → `EmbeddingClient`（`embedding_adapter.py:63-74`），经 `embedding_config_scope` 按 KB 绑定（`deeptutor/knowledge/manager.py:200-218`；`deeptutor/services/rag/embedding_binding.py:302-330`） | 适配器内重试；600s 停滞守卫（`pipeline.py:41,112`）；per-KB worker 互斥（`:68-88`），跨 KB 无上限 |
| LightRAG | `build_embedding_func` 自建 `EmbeddingClient`（`lightrag/config.py:390-446`），经 `OwnerLoopBridge` 跨 loop 桥接 | **无适配器级重试**（§2）；`llm_model_max_async` 透传但嵌入并发参数不透传（`:184-196`） |
| GraphRAG | **不走 services/embedding**：保留 GraphRAG 库内 LiteLLM 嵌入路径，DeepTutor 只翻译 api_base（`deeptutor/services/rag/pipelines/graphrag/config.py:108-143`）并做传输白名单校验（`:144-163`；设计说明 `:18`） | LiteLLM/GraphRAG 默认值，本文矩阵不适用 |
| IMA | 无本地嵌入（KB 是外部连接指针，`deeptutor/services/rag/pipelines/ima/__init__.py:3`） | 不适用 |
| 连接探测 | `system.py:528` 测试连接、`settings_spec.py:586-603` 冒烟（25s 预算） | 同矩阵，但走钳制后的超时 |

## 7. 修复建议锚点（对应扫描报告补测卡）

1. **E-1 统一重试契约**：给 `cohere.py:130-139`、`jina.py:116-125`、`dashscope_native.py:95-179` 补"429/transport 有界重试 + 退避 + Retry-After"；模式取 `openai_compatible.py:334-354`（transport）与 `lightrag/config.py:113-139`（轻量有界版）。落点 `tests/services/embedding/`（扩展 `test_retry_after.py`；`test_dashscope_adapter.py` 已有打桩框架）。
2. **E-2/E-3 在飞并发上限**：优先做按 endpoint 的 `asyncio.Semaphore`（候选位置 `client.py:88-116` 构造处或 `_wait_for_request_slot` 同层）；LightRAG 侧透传 `embedding_func_max_async`/`embedding_batch_num`（`lightrag/config.py:184-196`）。回归测试断言"多 KB 并发 re-index 时同一 base_url 在飞数 ≤ 上限"。
3. **E-4 ollama 瞬时错误重试**：`ollama.py:95-109` 翻译层前加 1-2 次有界重试；同时分离 connect/read 超时（`:63-65` 改 `httpx.Timeout`）。
4. **E-5 loop 复用**：`embedding_adapter.py:127-133` 改 per-thread 复用（`threading.local`），并发语义断言扩展 `tests/services/embedding/test_client_runtime.py`（现有 `test_embedding_requests_are_spaced_but_http_can_overlap` 是行为基线）。
5. **脱敏整改**：按 §5 表逐行落点；统一 helper 建议 `exc_type_name` + 通用脱敏截断（蓝本 `gemini.py:112-143`），并同修 `base.py:113-126` 的 `__str__` body 拼接与 `client.py:161-176` 的异常日志，否则修了适配器日志 body 仍从异常链漏出。

## 8. 三处最易误读点

1. **"LightRAG 有 `_run_adapter_with_retry`，所以 LightRAG 嵌入也有重试"——错。** 该包装只挂在 `llm_model_func`/`vision_model_func`（`lightrag/config.py:313,375`），`embedding_func` 直接调 `client.embed`（`:411-425`）。LightRAG KB 的嵌入重试完全取决于内层适配器：cohere/jina/dashscope 绑定在 LightRAG 下同样是零重试。
2. **"`_wait_for_request_slot`/间距锁限制了嵌入并发"——错。** 它只是 `batch_delay>0` 时的起步间隔钟，锁只护时间戳更新、不包 HTTP 调用（`client.py:42-86`）；默认 `batch_delay=0.0`（`config.py:30`）时整段直接 return（`:80-81`），在飞并发没有任何上限，多 KB re-index/检索查询会同时打向同一后端。
3. **"cohere/jina 修掉整响应体日志就没事了"——不完整。** 同型代码 `openai_compatible.py:287`（2000 字符截断版）不在两份扫描报告的整改清单里；且任何适配器的 `EmbeddingProviderError` 都会把 body 摘要拼进 `__str__`（`base.py:113-126`）、由 `client.py:161-176` 的失败日志带出——脱敏必须连异常传播链一起改。
