# LLM provider_core 生命周期导读

> 范围：`deeptutor/services/llm/provider_core/` 全部模块。只讲结构与语义；凭据的具体内容与获取方式不在本文范围内。
> 基线：`origin/main` @ f07029cfc（v1.6.13）。所有行号以该提交为准。
> 本文不改任何代码。

## 1. 模块地图与依赖方向

`provider_core` 是 services 层的 provider 运行时：一个抽象基类 + 7 个 provider 实现 + 1 个 Responses API 共享子包。

| 文件 | 行数 | 角色 |
| --- | --- | --- |
| `__init__.py` | 52 | 门面：base 类型即时导出，7 个 provider 类惰性导出 |
| `base.py` | 538 | `LLMProvider` ABC、`LLMResponse`/`ToolCallRequest`/`GenerationSettings`、重试策略、通用 `aclose` |
| `openai_compat_provider.py` | 1279 | 所有 OpenAI 兼容端点的统一实现（OpenAI/DeepSeek/Gemini/网关/本地等） |
| `anthropic_provider.py` | 610 | Anthropic Messages API 原生实现 |
| `azure_openai_provider.py` | 249 | Azure OpenAI，仅走 Responses API |
| `openai_codex_provider.py` | 246 | Codex OAuth + Responses SSE，每次请求新建 httpx 客户端 |
| `github_copilot_provider.py` | 234 | 继承 compat，叠加 Copilot token 刷新 |
| `codebuddy_provider.py` | 839 | CodeBuddy Agent SDK 适配器：有状态 CLI 会话池 + 专属 owner 任务 |
| `codebuddy_http_provider.py` | 258 | CodeBuddy 纯 HTTP 传输（继承 compat），含 `build_codebuddy_provider` 传输选择器 |
| `codebuddy_models.py` | 36 | CodeBuddy 模型目录查询 |
| `openai_responses/`（`__init__.py` 35 + `converters.py` 200 + `parsing.py` 666） | 901 | Chat Completions ↔ Responses API 的转换与 SSE/SDK 流解析 |

依赖方向（`provider_core` 内部只允许指向 `base` 与 `openai_responses`）：

- 全部实现 → `base.py`（如 `codebuddy_provider.py:19-23`、`anthropic_provider.py:18`）。
- `openai_compat_provider.py` / `azure_openai_provider.py` / `openai_codex_provider.py` → `openai_responses` 共享子包（`openai_compat_provider.py:32-40`、`azure_openai_provider.py:16-23`、`openai_codex_provider.py:19-24`）。
- `codebuddy_http_provider.py` 继承 `OpenAICompatProvider`（`codebuddy_http_provider.py:27,47`）；`github_copilot_provider.py` 同理（`github_copilot_provider.py:13,24`）。
- `codebuddy_models.py` 反向调用 `codebuddy_provider.fetch_codebuddy_models` 作为 CLI 兜底（`codebuddy_models.py:21-31`）。

外部依赖在 §7 汇总；装配入口在 §2。

## 2. 装配路径：从配置到 provider 实例

调用方从不直接 `import` 具体 provider 类，而是经过两级工厂：

**第一级：LLMConfig 解析（`services/llm/config.py`）**
`get_llm_config()`（`deeptutor/services/llm/config.py:235-252`）返回带缓存的 `LLMConfig`（`config.py:111` 起），底层来自 `resolve_llm_runtime_config()`（`config.py:193-253`），数据源头是用户设置与模型目录（见 §7 settings/catalog 耦合）。

**第二级：provider 构造（`services/llm/provider_factory.py`）**
`_build_runtime_provider()`（`provider_factory.py:48-128`）按 `effective_backend(spec, api_format)` 的返回值分派：

- `openai_codex` → `OpenAICodexProvider`（`provider_factory.py:64-69`）
- `github_copilot` → `GitHubCopilotProvider`（`provider_factory.py:70-78`）
- `codebuddy` → `build_codebuddy_provider()`（HTTP 优先，SDK 兜底，`provider_factory.py:79-88` → `codebuddy_http_provider.py:217-248`）
- `azure_openai` → `AzureOpenAIProvider`；openai profile 带 `api_version` 会被改判为 azure（`provider_factory.py:58-62,89-98`）
- `anthropic` → `AnthropicProvider`（`provider_factory.py:99-108`）
- 其余 → `OpenAICompatProvider`（`provider_factory.py:109-121`）

构造完成后统一注入 `GenerationSettings`（temperature/max_tokens/reasoning_effort，`provider_factory.py:123-127`）。所有导入都是函数内延迟导入，只有选中的 backend 才会加载对应 SDK（`provider_factory.py:53`）。

**实例缓存：事件循环本地的 provider 池（`provider_factory.py:17-19,144-170`）**
`get_runtime_provider()` 以 `(loop, provider_name, provider_mode, model, api_key 指纹, url, api_version, headers, wire_api, api_format, temperature, max_tokens, reasoning_effort)` 为键做 LRU 缓存，池上限 `_PROVIDER_POOL_MAXSIZE = 2`（`provider_factory.py:17,29-45,157-170`）。api_key 只以 SHA256 前 16 位指纹参与缓存键，明文不落键（`provider_factory.py:22-26`）。不在事件循环内时直接现建不缓存（`provider_factory.py:152-155`）。池淘汰的旧 provider 通过 `_schedule_close()` 异步关闭（`provider_factory.py:136-141,167-169`）。

**隔离实例**：`build_isolated_provider()`（`provider_factory.py:131-133`）跳过池并禁用环境变量写入（`configure_env=False`），供 `factory.complete_with_config` 一次性使用后关闭（`factory.py:497,515-516`）。

**门面惰性导出（`provider_core/__init__.py`）**
base 的 4 个类型即时导出（`__init__.py:8`），7 个 provider 类走 `_LAZY_TYPES` + 模块级 `__getattr__`，首次访问才 import 对应模块并缓存到 `globals()`（`__init__.py:34-52`）。

**上层门面（`services/llm/factory.py`，非 provider_core 但决定装配语义）**
`_resolve_call_config()`（`factory.py:157-254`）把显式实参与当前配置合并；`_resolve_provider_spec()`（`factory.py:81-111`）依次尝试 `find_by_name` → `find_gateway` → `find_by_model` → 本地服务探测 → openai 兜底。公开入口 `complete()` / `stream()`（`factory.py:411-455,519-723`）都是"解析配置 → `get_runtime_provider` → `chat_with_retry` / `chat_stream_with_retry`"的固定管线；`stream()` 额外把内容/推理增量汇入队列并按 `stream_coalesce_*` 合帧（`factory.py:583-723`）。

## 3. base.py：契约、重试与通用关闭

**数据契约**

- `ToolCallRequest`（`base.py:17-43`）：工具调用请求，`to_openai_tool_call()` 序列化回 OpenAI 形态。
- `LLMResponse`（`base.py:46-61`）：统一响应。`content`/`tool_calls`/`finish_reason`（`"stop"|"tool_calls"|"length"|"error"|...`）/`usage`/`reasoning_content`/`thinking_blocks`/`provider_specific_fields`。约定：`finish_reason="error"` 时 `content` 是人类可读的错误描述。
- `GenerationSettings`（`base.py:64-70`）：不可变默认生成参数，由工厂注入（`provider_factory.py:123-127`）。

**`LLMProvider` 抽象（`base.py:73` 起）**

- 抽象方法只有两个：`chat()`（`base.py:242-254`）与 `get_default_model()`（`base.py:536-538`）；`chat_stream()` 有兜底实现——整段调用 `chat()` 后一次性回调 content/reasoning（`base.py:256-284`）。
- `_SENTINEL` 参数占位（`base.py:107`）让 `chat_with_retry` 能区分"没传"与"传了 None"，从而回落到 `self.generation`（`base.py:439-472,505-518`），并对 str/bool 型参数做容错收敛（`base.py:110-133,459-472`）。

**瞬态错误识别与重试（`base.py:76-106,286-332,334-437`）**

- `_TRANSIENT_ERROR_MARKERS`（`base.py:77-89`）+ 可重试 HTTP 状态码集合 {408,429,500,502,503,504}（`base.py:90`）。
- `_is_transient_error()` 先看异常携带的状态码（`_status_code_from_exception`，`base.py:287-301`），再从错误文本解析显式状态字段/状态行（`_HTTP_STATUS_PATTERNS`，`base.py:91-106,304-314`），TimeoutError/ConnectionError 直接算瞬态（`base.py:316-332`）。
- `_call_with_retry()`（`base.py:334-437`）是唯一重试引擎：每次尝试包一层 `measure_provider_call` 做指标（`base.py:349-364`，实现在 `services/llm/metrics.py:183`）；异常被规范化为 `finish_reason="error"` 的响应再统一分类（`base.py:384-392`）；瞬态错误按 `(1,2,4)` 秒退避重试（`base.py:76,426-437`）；非瞬态且消息带图片时执行一次"去图重试"（Stage-2 vision fallback，仅当调用方未声明该模型具备视觉能力，`base.py:397-424`，`allow_image_fallback` 由工厂按 `supports_vision` 决定，`factory.py:380-384`）。`asyncio.CancelledError` 永远直接上抛（`base.py:384-385`）。
- `chat_with_retry` / `chat_stream_with_retry` 是调用方实际使用的入口（`base.py:439-486,488-534`）。

**通用 `aclose()`（`base.py:140-155`）**
按鸭子类型关闭 `self._client`：取 `_client` 属性，优先 `aclose` 后 `close`，同步/异步返回都兼容；没有 `_client` 的 provider（如 Codex）是廉价 no-op。这是 §6 关闭路径清单的最后一跳。

**请求净化（`base.py:157-226`）**
`_sanitize_empty_content()` 把空字符串内容替换为 `"(empty)"`（assistant+tool_calls 时置 `None`），过滤列表 content 里的空 text 分片（`base.py:157-202`）——这些形态会导致若干 provider 报 400。`_sanitize_request_messages()` 按 provider 白名单键裁剪消息（`base.py:214-226`）；`_tool_cache_marker_indices()` 从尾部每 5 个工具取 1 个做 cache 标记（`base.py:204-212`）。

## 4. 各 provider 的结构与生命周期

### 4.1 OpenAICompatProvider（`openai_compat_provider.py`）

连接：`__init__` 持有一个 `AsyncOpenAI` 客户端，SDK 重试归零、TLS 配置由 `openai_sdk_client_kwargs` 统一处理（`openai_compat_provider.py:211-219`，`services/llm/openai_http_client.py:117-161`）。多 key 时构造 `KeyPool` 做轮换：请求头注入 `Authorization`，429 记 strike 换下一把，预算 `max(2, len(pool))` 次（`openai_compat_provider.py:182-186,230-249`，`services/keypool.py:9-49`）。`configure_env=True` 且 spec 声明 env_key 时同步环境变量（`openai_compat_provider.py:193-194,251-266`）。

一次 `chat()`（`openai_compat_provider.py:988-1081`）的分支顺序：

1. `_should_use_responses_api()` 决定走 Responses 还是 Chat Completions（`openai_compat_provider.py:464-492`）：`wire_api` 显式指定 > 原生 web search > 仅 openai / github_copilot spec 且直连 api.openai.com > 推理模型（gpt-5/o1/o3/o4 或带 reasoning_effort）> Responses 熔断器放行。
2. Responses 路径：`_build_responses_body` 复用 `openai_responses.converters`（`openai_compat_provider.py:717-761`）；`_create_responses_with_status_retry` 对 400/422 的 `input[i].status` 拒绝自动剥离后重试一次（`openai_compat_provider.py:601-619`）。失败时 `_should_fallback_from_responses_error`（400/404/422 + 端点不支持标记，`openai_compat_provider.py:621-659`）触发熔断计数并回落 Chat Completions；连续 2 次失败熔断 300 秒，成功即复位（`openai_compat_provider.py:74-75,494-505,526-536`）。
3. Chat Completions 路径：`_build_kwargs` 组装请求（消息净化、prompt cache 标记、`model_overrides_for` 覆盖、推理参数；`openai_compat_provider.py:408-462`）；`response_format` 被拒时记录运行时禁用并重试一次（`openai_compat_provider.py:1042-1055`，`services/llm/capabilities.py`）。
4. 顶层错误兜底：forced tool_choice 被拒 → 放宽为 `"required"` 重试一次（`openai_compat_provider.py:695-715,1056-1069`）；工具参数 JSON 格式错误 → 改走流式重试（`openai_compat_provider.py:969-986,1070-1080`）；其余进 `_handle_error` 返回 error 响应（`openai_compat_provider.py:952-963`）。

`chat_stream()`（`openai_compat_provider.py:1083-1276`）：同样的 Responses/Chat 二选一；流读取统一带 90 秒 idle 超时（`openai_compat_provider.py:1110,1127-1136,1221-1228`），超时返回 error 响应（`openai_compat_provider.py:1252-1256`）。Chat 流实时回调 content/reasoning/tool-args 增量（`on_tool_args_delta` 由 `_accumulate_streamed_tool_call` 维护累积缓冲，`openai_compat_provider.py:91-118,1219-1250`），最终响应仍由收齐的 chunks 经 `_parse_chunks` 权威解析（`openai_compat_provider.py:870-950`）。

响应解析语义（`_parse`，`openai_compat_provider.py:811-868`）：跨 choices 收集 tool_calls；`reasoning_content`/`reasoning` 字段识别为私有推理；content 与推理完全相同时丢弃 content（防网关把 trace 当答案，`openai_compat_provider.py:850-858`）。工具调用 id 统一收敛为 9 位（`_normalize_tool_call_id`，`openai_compat_provider.py:315-321,372-392`），历史回放时把 `_provider_response_state` 里的 reasoning_content 还原到 assistant 消息（`openai_compat_provider.py:339-362`）。

关闭：无自定义 `aclose`，继承 `base.py:140-155` 关闭 `self._client`（AsyncOpenAI）。

### 4.2 AnthropicProvider（`anthropic_provider.py`）

连接：`__init__` 构造 `AsyncAnthropic`（SDK 重试归零），并把误填的 `/v1` 后缀剥掉避免 `/v1/v1/messages`（`anthropic_provider.py:53-72`）。

请求构造 `_build_kwargs`（`anthropic_provider.py:374-442`）：OpenAI 消息转 Anthropic 形态（system 抽离、tool 结果并入 user 块、相邻同角色合并，`anthropic_provider.py:101-145,255-272`）；assistant 回放签名过的 thinking blocks（消息本体或 `_provider_response_state` 兜底，`anthropic_provider.py:160-177`）；prompt cache 按"system + 末条消息 + 工具"预算 4 个断点（`anthropic_provider.py:320-368`）；thinking 按模型家族二分：effort-based 家族用 `{"type":"adaptive"}`，老家族用 `enabled+budget_tokens` 并抬高 `max_tokens`，`none/minimal/minimum` 一律完全省略 thinking 参数（`anthropic_provider.py:26-30,396-431`，家族清单来自 catalog `ANTHROPIC_EFFORT_BASED_FAMILIES`，`anthropic_provider.py:19`）。

执行：`chat()` 直接 `messages.create`（`anthropic_provider.py:511-538`）；`chat_stream()` 用 `messages.stream`，逐事件分发 `text_delta`/`thinking_delta`（而不是只吐文本的 `text_stream`），同样 90 秒 idle 超时（`anthropic_provider.py:540-607`）。响应解析把 `tool_use`→`finish_reason="tool_calls"`、缓存命中拆进 usage（`anthropic_provider.py:448-505`）。

关闭：继承 `base.py:140-155` 关闭 `AsyncAnthropic`。

### 4.3 AzureOpenAIProvider（`azure_openai_provider.py`）

连接：`normalize_azure_base_url()` 把门户式端点（`/deployments/<name>/chat/completions`、`?api-version=`）收敛为 `/openai/v1/` 面（`azure_openai_provider.py:25-66`）；鉴权走 `api-key` 头而非 Bearer，附带 `x-session-affinity`（`azure_openai_provider.py:91-112`）；仅 `preview` 版本转发为 query（`azure_openai_provider.py:97-103`）。

执行：仅 Responses API。`_build_body`（`azure_openai_provider.py:124-153`）与 compat 的 Responses 体同构；`chat()` 非流式 `parse_response_output`（`azure_openai_provider.py:163-187`）；`chat_stream()` 用 `_timed_stream` 包 90 秒 idle 超时后 `consume_sdk_stream`（`azure_openai_provider.py:189-246`）。

关闭：继承 `base.py:140-155` 关闭 AsyncOpenAI。

### 4.4 OpenAICodexProvider（`openai_codex_provider.py`）

无自有 SDK 客户端：`__init__` 只存默认模型（`openai_codex_provider.py:39-42`）；每次调用经 `get_codex_oauth_service()` 取 token、过 `inference_guard()` 与运行时画像校验，再以固定 Responses URL 发请求（`openai_codex_provider.py:43-44,76-89`，耦合 `services/codex_auth`）。传输是每次请求新建的 `httpx.AsyncClient`（60 秒总超时，`openai_codex_provider.py:202-224`）。HTTP 401 时触发 OAuth 服务端会话续期后按语义提示重试（`openai_codex_provider.py:90-107`）；瞬态传输错误被包装成不含 URL/响应体的 `LLMProviderTransportError` 以便上层重试（`openai_codex_provider.py:123-128`，判定在 `services/llm/request_compat.py`）。`max_tokens/temperature` 被显式忽略（`openai_codex_provider.py:148,164`）；`prompt_cache_key` 取 system 前缀哈希（`openai_codex_provider.py:227-236`）。

关闭：无 `_client`，`aclose` 是 no-op（`base.py:147-149`）。

### 4.5 GitHubCopilotProvider（`github_copilot_provider.py`）

继承 compat，叠加 token 生命周期：`_ensure_api_key()` 优先沿用现成 access token，过期（含 60 秒偏移）才走 `_try_existing_local_auth`（`github_copilot_provider.py:21,104-111`）；请求遇到 `AuthenticationError` 时用存储的 GitHub token 换新 Copilot token（记录 `expires_at` 或 `refresh_in`）并重放一次请求（`github_copilot_provider.py:68-102,152-178`）。`chat`/`chat_stream` 都经 `_chat_impl` 收口（`github_copilot_provider.py:113-178`）；刻意不声明 `on_tool_args_delta`，运行时按签名探测决定是否下发该回调（`github_copilot_provider.py:203-208`，探测端 `runtime/agentic/client.py:437-455`）。

关闭：继承 `base.py:140-155`。

### 4.6 CodeBuddyHTTPProvider 与传输选择（`codebuddy_http_provider.py`）

`CodeBuddyHTTPProvider` 同样继承 compat：`__init__` 解析本地登录态得到 api_base 与附加头（显式 key → `X-API-Key`；登录态 → `X-User-Id`）（`codebuddy_http_provider.py:50-78`，凭据结构由 `services/codebuddy_credentials` 提供——只依赖其接口，不涉及内容）。每次请求前 `_ensure_auth()` 检查过期并刷新，必要时改写客户端 base_url（`codebuddy_http_provider.py:87-105`）；`AuthenticationError` 时从磁盘重载凭据再重放一次（`codebuddy_http_provider.py:136-149`）。`chat_stream` 刻意不声明 `on_tool_args_delta`（`codebuddy_http_provider.py:173-178`）；`deeptutor_session_id` 在这里被剥掉（会话亲和仅 SDK 传输使用，`codebuddy_http_provider.py:120-121`）。

`build_codebuddy_provider()`（`codebuddy_http_provider.py:217-248`）是传输选择器：`DEEPTUTOR_CODEBUDDY_BACKEND=http|sdk` 可强制，否则"HTTP 可认证则 HTTP，无 SDK 也 HTTP"，都不满足才回 Agent SDK。

关闭：继承 `base.py:140-155` 关闭 AsyncOpenAI；无 CLI 子进程常驻。

### 4.7 CodeBuddyProvider：SDK 会话池与 owner 任务（`codebuddy_provider.py`）

这是 provider_core 里唯一有常驻子进程与跨任务状态的生命周期，重点展开。

**为什么需要 owner 任务**：CodeBuddy Agent SDK 在 `connect()` 时进入 anyio cancel scope / TaskGroup，必须在**同一个 asyncio 任务**里退出。而 DeepTutor 的聊天流每次都在新任务里消费（`runtime/agentic/client.py:486-529` 的 `_ProviderOpenAIStream` 在 `__aiter__` 时 `asyncio.create_task(self._run())`，`client.py:514-516`）。因此 `_CodeBuddySession` 用一个专属 owner 任务串行处理 connect/query/receive/disconnect（`codebuddy_provider.py:40-48`）。

**会话结构 `_CodeBuddySession`（`codebuddy_provider.py:40-145`）**

- `start()` 创建 owner 任务并等待 `ready` future（`codebuddy_provider.py:58-75`）。
- `_owner_loop()`（`codebuddy_provider.py:77-116`）是会话的一生：
  1. 构造 SDK client，在临时注入 API key 环境的上下文里 `connect()`（`codebuddy_provider.py:84-87`，环境变量互斥锁 `_API_KEY_ENV_LOCK` 保护，`codebuddy_provider.py:27,766-780`）。
  2. `ready` 置位后进入 `while True`：从 `_ops` 队列取 turn；`None` 哨兵 → 跳出循环（`codebuddy_provider.py:89-94`）。
  3. 每个 turn：`client.query(prompt)` → `_consume_messages(client.receive_response(), ...)`（流式增量回调 + 工具调用截断 + 错误结果识别，`codebuddy_provider.py:96-103,524-565`）；结果/异常写入 turn 的 future（`codebuddy_provider.py:102-106`）。
  4. `finally` 里无条件 `client.disconnect()`（吞异常）（`codebuddy_provider.py:111-116`）；连接前的异常经 `ready` 传回 `start()` 调用方（`codebuddy_provider.py:107-110`）。
- `run_turn()` 校验 owner 存活，投递 `_SessionTurn` 并 await future（`codebuddy_provider.py:118-130`）——外部任务与 owner 任务的唯一交汇点。
- `close()`（`codebuddy_provider.py:132-145`）：置空 `self._owner`，投递 `None` 哨兵（队列 put 失败则 cancel owner），然后 `await owner` 回收；owner 内部 `finally` 完成 disconnect。哨兵路径保证 cancel scope 在原任务退出。

**provider 层 `CodeBuddyProvider`（`codebuddy_provider.py:148-367`）**

- 状态：`_sessions: OrderedDict[session_id, _CodeBuddySession]` + `asyncio.Lock`；池上限 `_SESSION_POOL_MAXSIZE = 4`（`codebuddy_provider.py:28,165-166`）。
- 入口 `chat()`/`chat_stream()` 都剥出 `deeptutor_session_id` 后进 `_run_codebuddy()`（`codebuddy_provider.py:168-213`）：有 session_id 且 SDK 可用 → 有状态会话；否则一次性 `sdk.query()` 流（`_run_one_shot`，`codebuddy_provider.py:250-273`，`finally` 里 `stream.aclose()`）。所有异常收敛为 `finish_reason="error"` 的友好响应（`codebuddy_provider.py:247-248,749-763`）。
- 会话获取 `_get_session()`（`codebuddy_provider.py:301-344`）：签名 = (model, reasoning_effort, tools) 的 JSON（`_session_signature`，`codebuddy_provider.py:495-505`）。签名相同且 owner 存活 → LRU 命中 `move_to_end`；否则淘汰旧会话、新建 `_CodeBuddySession.start()`；超容量按 LRU 逐出。`finally` 里统一 close 被淘汰者。
- 单轮执行 `_run_session()`（`codebuddy_provider.py:275-299`）：`session.lock` 串行；`_incremental_prompt` 只发送相对上轮的新增消息（上轮 assistant 回复与 `last_response` 相同时去重，`codebuddy_provider.py:508-521`）；每轮结束把全量消息 deepcopy 进会话。任何 `BaseException` → `_drop_session()`（从池中移除并 close，`codebuddy_provider.py:346-350`）后上抛——坏会话不回池。
- `aclose()`（`codebuddy_provider.py:352-364`）：锁内快照并清空池，逐个 `session.close()`；`CancelledError` 被 `task.uncancel()` 吸收，其余异常吞掉——关闭过程不因单个会话失败而中断。
- SDK 选项 `_build_options()`（`codebuddy_provider.py:394-444`）：`max_turns=1` + `permission_mode="plan"` 是沙箱边界，snake/camel 两种拼写都试，SDK 两者都不收就直接抛错而不是裸跑（`codebuddy_provider.py:415-444`）；工具经进程内 MCP server 暴露，tool 执行权仍在 DeepTutor 调度器（`codebuddy_provider.py:447-492`）。
- `fetch_codebuddy_models()`（`codebuddy_provider.py:783-832`）：一次性 CLI 子进程探测模型目录（Windows/POSIX 分支的进程标志，`codebuddy_provider.py:801-824`）。

### 4.8 codebuddy_models.py：目录查询的降级链

`fetch_codebuddy_models()`（`codebuddy_models.py:15-33`）：先读凭据服务缓存的目录 → 装了 SDK 再用 4.7 的 CLI 探测兜底（失败吞掉）→ 最终回落 `FALLBACK_MODEL_CATALOG`。`factory.fetch_models()` 对 codebuddy binding 走这里，其余走 cloud/local 探测（`factory.py:726-744`）。

### 4.9 openai_responses 子包：转换与解析

**converters.py**（`openai_responses/converters.py`）

- `convert_messages()`（`converters.py:16-79`）：Chat 消息 → Responses input items。system 抽为 `instructions`；assistant 优先回放 `_provider_response_state.responses_output_items` 原生条目（无状态时合成 `message` + `function_call`）；tool 结果 → `function_call_output`。
- `convert_tools()`（`converters.py:102-134`）：函数 schema 转换；`native_web_search=True` 时把 `web_search` 函数声明为 provider 原生 `{"type":"web_search"}` 工具。
- `convert_tool_choice()`（`converters.py:137-160`）：嵌套 `{"type":"function","function":{"name":...}}` 拍平为 Responses 的顶层 `name` 形态。
- `split_tool_call_id()`（`converters.py:163-170`）：拆 `call_id|item_id` 复合 id（Responses 流的关联键，见下）。
- `adapt_chat_kwargs_to_responses()`（`converters.py:173-200`）：`max_tokens`/`max_completion_tokens` → `max_output_tokens`，防止 SDK 在请求发出前 TypeError。

**parsing.py**（`openai_responses/parsing.py`）

- 终态映射 `FINISH_REASON_MAP` / `map_finish_reason()`（`parsing.py:17-22,87-103`）：`completed→stop`、`incomplete→length`（`content_filter` 例外）、`failed/cancelled→error`。
- `_ToolCallBuffers`（`parsing.py:126-197`）：流中按 `call_id` 或 `item_id` 双别名关联函数调用；占位 `fc_0` 只作回显回退、绝不注册为查找键，防止下一个未带 id 的调用错配到前一个调用的参数（`parsing.py:143-166`）。
- 工具参数解析 `_parse_tool_arguments()`（`parsing.py:222-268`）：严格 JSON → `json_repair` → 兜底 `{"raw": ...}`；`_looks_truncated()` 按"末字符是否闭合"区分截断（警告级）与普通语法破损（debug 级）（`parsing.py:200-219`）。
- 两个消费者：`consume_sse()`（裸 httpx SSE，`parsing.py:325-453`）与 `consume_sdk_stream()`（OpenAI SDK 事件流，`parsing.py:549-666`），事件分派表一致：`output_item.added` 注册 buffer、`output_text.delta` 推内容、`function_call_arguments.delta/done` 累积/定稿参数（`.delta` 同时喂 `on_tool_args_delta` 实时预览）、`output_item.done` 产出 `ToolCallRequest`（id 为 `call_id|item_id` 复合形态，`parsing.py:294-305`）、`response.completed/incomplete` 收终态与 usage、`error`/`response.failed` 抛错。SDK 消费者额外收集 `reasoning_*_delta` 与可回放 output items（`_REPLAYABLE_OUTPUT_ITEM_TYPES`，`parsing.py:35-40,607-615`）。
- 非流式 `parse_response_output()`（`parsing.py:456-546`）：把 Response 对象拆成 content/tool_calls/reasoning/usage，web_search 条目保真进 `provider_specific_fields.native_output_items` 而不是伪造第二轮工具调用（`parsing.py:498-504,526-538`）。

## 5. 会话生命周期图

一次带 `deeptutor_session_id` 的 CodeBuddy SDK 会话（4.7 的核心路径）：

```mermaid
title="CodeBuddy SDK 会话生命周期"
sequenceDiagram
    participant AG as Agent 循环<br/>(agents/loop/agent_loop.py:1053)
    participant CP as CodeBuddyProvider<br/>(codebuddy_provider.py:148)
    participant SS as _CodeBuddySession<br/>(codebuddy_provider.py:40)
    participant OW as owner 任务<br/>_owner_loop (…:77)
    participant SDK as CodeBuddy SDK client

    AG->>CP: chat_stream(messages, deeptutor_session_id)
    CP->>CP: _get_session：签名命中→LRU 复用<br/>否则淘汰旧会话并 start()（…:301-344）
    CP->>SS: _CodeBuddySession.start()
    SS->>OW: create_task(_owner_loop)
    OW->>SDK: connect()（临时注入 API key 环境，…:84-87）
    OW-->>SS: ready.set_result()
    SS-->>CP: session 就绪
    CP->>SS: run_turn(prompt)（经 session.lock，…:118-130）
    SS->>OW: _ops.put(_SessionTurn)
    OW->>SDK: query(prompt) → receive_response()
    OW->>OW: _consume_messages：增量回调/工具截断/错误识别（…:524-565）
    OW-->>SS: future.set_result(LLMResponse)
    SS-->>CP: 响应；全量消息 deepcopy 存会话（…:290-296）
    CP-->>AG: LLMResponse

    Note over CP,OW: 异常路径：任意 BaseException → _drop_session()<br/>移出池 + session.close()（…:297-299,346-350）

    AG->>CP: aclose()（进程关停/池回收）
    CP->>SS: 逐个 session.close()：_ops.put(None)（…:132-145,352-364）
    SS->>OW: 哨兵退出 while 循环（…:91-94）
    OW->>SDK: finally: disconnect()（…:111-116）
    OW-->>SS: owner 任务结束
```

无状态的 compat/anthropic/azure 路径则简单得多：`get_runtime_provider` 缓存命中即复用客户端，`chat(_stream)_with_retry` → `_call_with_retry` 循环 → 返回；连接释放只发生在 §6 的四个触发点。

## 6. 关闭路径清单

| # | 触发点 | 调用链 | 最终动作 |
| --- | --- | --- | --- |
| 1 | API 进程关停 | `api/main.py:376-378` → `close_runtime_provider_pool()`（`provider_factory.py:173-179`） | 清空池，`asyncio.gather` 并发 `aclose()` 每个 provider，异常不传播 |
| 2 | 设置/目录热更新 | `reset_llm_client()`（`services/llm/client.py:230-239`）→ `reset_runtime_provider_pool()`（`provider_factory.py:182-197`） | 同步上下文里清池；在事件循环内用 `_schedule_close` 延后关闭，无循环则 `asyncio.run` 兜底 |
| 3 | 池 LRU 淘汰 | `get_runtime_provider()`（`provider_factory.py:167-169`）→ `_schedule_close()`（`provider_factory.py:136-141`） | `loop.create_task` 后台 `aclose`，抑制异常；池上限 2 |
| 4 | 一次性隔离实例 | `complete_with_config()`（`factory.py:497,515-516`） | `finally: await provider.aclose()` |
| 5 | agentic 适配器关闭 | `_ProviderOpenAIAdapter.close()`（`runtime/agentic/client.py:404-407`）与 `_ProviderOpenAIStream.close()`（`runtime/agentic/client.py:531`） | 鸭子探测 `aclose`/`close` 后调用；池复位经 `reset_agentic_client_pool`（`client.py:280`，由 `client.py:240-243` 触发） |
| 6 | 通用 SDK 客户端释放 | `LLMProvider.aclose()`（`base.py:140-155`） | 有 `_client` 则 `aclose`/`close`；OpenAICompat/Anthropic/Azure/Copilot/CodeBuddyHTTP 都由这一跳收尾；Codex 无 `_client`，no-op |
| 7 | CodeBuddy 会话池整体关闭 | `CodeBuddyProvider.aclose()`（`codebuddy_provider.py:352-364`） | 锁内快照清池 → 逐个 `session.close()`；CancelledError 吞并 `uncancel()` |
| 8 | 单个 CodeBuddy 会话关闭 | `_CodeBuddySession.close()`（`codebuddy_provider.py:132-145`） | `None` 哨兵入 `_ops` → owner 退出循环 → owner `finally: client.disconnect()`（`codebuddy_provider.py:111-116`）；put 失败退化为 `owner.cancel()` |
| 9 | CodeBuddy 坏会话淘汰 | `_run_session` 异常 → `_drop_session()`（`codebuddy_provider.py:297-299,346-350`） | 从池移除 + `session.close()`，坏会话不回池 |
| 10 | CodeBuddy 签名变更/陈旧会话 | `_get_session()`（`codebuddy_provider.py:313-325,342-344`） | 旧会话移出池，`finally` 中 close（owner 已死也会走此路径） |
| 11 | 一次性 SDK 流关闭 | `_run_one_shot()`（`codebuddy_provider.py:268-273`） | `finally: stream.aclose()` |

不变量：所有关闭入口最终都收敛到 `LLMProvider.aclose()`；CodeBuddy 的 disconnect 保证发生在创建连接的 owner 任务里（`codebuddy_provider.py:41-48` 的约束），哨兵优先于 cancel。

## 7. 耦合点：settings 与 catalog（provider_registry）

**settings 侧（用户配置与运行时开关）**

- `factory.py:11,31-33`：模块加载期读取 `settings.retry.*` 作为默认重试参数（`deeptutor/config/settings.py:20,29`）——这是 provider_core 之外的装配常量来源。
- `LLMConfig` 解析链：`get_llm_config()`（`services/llm/config.py:235-252`）→ `resolve_llm_runtime_config()`；配置数据源头是用户设置与模型目录（`services/llm/config.py:1-6` 文件头）。provider_factory 的缓存键直接消费这些字段（`provider_factory.py:29-45`）。
- TLS 开关：`openai_http_client.disable_ssl_verify_enabled()` 读系统设置 `disable_ssl_verify`（`services/llm/openai_http_client.py:32-34`）；被 `OpenAICompatProvider.__init__`（`openai_compat_provider.py:211-219`）、Azure（`azure_openai_provider.py:111`）与 Codex（`openai_codex_provider.py:87`）间接消费。
- 环境变量注入：`OpenAICompatProvider._setup_env`（`openai_compat_provider.py:251-266`）按 spec 的 `env_key/env_extras` 写进程环境，`configure_env=False`（隔离实例）时跳过；CodeBuddy SDK 路径用互斥锁临时注入/还原 `CODEBUDDY_API_KEY` 环境变量（`codebuddy_provider.py:27,766-780`）。
- `DEEPTUTOR_CODEBUDDY_BACKEND` 环境变量选择 CodeBuddy 传输（`codebuddy_http_provider.py:229`）。

**catalog 侧（provider_registry，即"Settings > Catalog"背后的静态目录）**

- 装配：`provider_factory.py:15,56-57` 用 `find_by_name` + `effective_backend` 决定 backend；`factory.py:13-20,81-111` 用 `find_by_name/find_gateway/find_by_model/canonical_provider_name` 解析 spec，`factory.py:747-785` 由 `PROVIDERS` 生成前端预设。
- 请求构造：`OpenAICompatProvider` 用 `model_overrides_for()`（模型级参数覆盖，None 表示删除该参数）与 `normalize_wire_api()`（`openai_compat_provider.py:49,191,441-447,745-749`，实现在 `services/provider_registry.py:677,806`）；`spec.strip_model_prefix` / `spec.supports_max_completion_tokens` / `spec.supports_prompt_caching` / `spec.supports_stream_options` / `spec.native_web_search_models` / `spec.env_key` / `spec.default_api_base` 等字段被各 provider 消费（`openai_compat_provider.py:421-439,425-426,728-729,1195-1196,507-524,251-261`）。
- Anthropic thinking 家族：`ANTHROPIC_EFFORT_BASED_FAMILIES`（`anthropic_provider.py:19,402-404`）。
- CodeBuddy / Copilot spec：`codebuddy_http_provider.py:28,73`、`github_copilot_provider.py:14,44` 的 `find_by_name`。
- 能力判定联动：`services/llm/capabilities.py` 的 `supports_vision` 决定 `allow_image_fallback` 默认值（`factory.py:380-384`）、`supports_response_format` 剥除不支持的 `response_format`（`factory.py:342-344`）、`SESSION_SCOPED_BINDINGS = {"codebuddy"}` 与 `threads_session_id()`（`capabilities.py:697-702`）决定是否随请求携带 `deeptutor_session_id`（调用方 `agents/loop/agent_loop.py:1053`、`capabilities/explore_context/explorer.py:336-337`）。

**其他 services 耦合（简列）**：`services/keypool.py`（多 key 轮换，`openai_compat_provider.py:23,186`）、`services/llm/metrics.py`（`measure_provider_call`，`base.py:349`）、`services/llm/multimodal.py`（图片剥离 fallback，`base.py:350-354`）、`services/session/provider_response_state.py`（跨轮回放的响应状态契约：`anthropic_provider.py:20-22`、`openai_compat_provider.py:50-52`、`openai_responses/converters.py:9-11`）、`services/codebuddy_credentials.py`（CodeBuddy HTTP 登录态接口与目录缓存，`codebuddy_http_provider.py:19-25`、`codebuddy_models.py:12`）、`services/codex_auth`（Codex OAuth 服务，`openai_codex_provider.py:13-15`）、`services/llm/usage_frame.py`（usage 归一，`openai_compat_provider.py:48`、`openai_responses/parsing.py:15`）、`services/llm/reasoning_params.py` / `request_compat.py`（`openai_compat_provider.py:41-47`）、`services/llm/exceptions.py`（`LLMConfigError`/`LLMProviderTransportError`，`openai_compat_provider.py:29`、`openai_codex_provider.py:16`）。

## 8. 阅读路线建议

1. 先读 `base.py` 的契约与重试（§3），它是所有响应形态词汇表的出处。
2. 再读装配（§2）：`provider_factory.py` 全文仅 212 行，是理解"哪个请求用哪个 provider 实例"的最短路径。
3. 主线实现读 `openai_compat_provider.py` 的 `chat`/`chat_stream` 分支结构（§4.1），再按需看 `openai_responses` 两个消费者的事件分派表（§4.9）。
4. 最后读 `codebuddy_provider.py` 的 `_CodeBuddySession`（§4.7）——它是唯一涉及跨任务生命周期约束的模块，也是 `_owner_loop`/`close`/`aclose` 语义的完整样本。
