# services/llm 非 provider_core 客户端面导读（guide-llm-clients）

- 基线：`origin/main @ f07029cfc`（v1.6.13）。文内 `path:line` 均为该基线、相对仓库根目录；行号用 `文件:行` 形式。
- **范围与边界**：本文只覆盖 `deeptutor/services/llm/` 下 provider_core 之外的 29 个文件，以及它们与 provider_core、调用方之间的衔接。provider_core（各 SDK 后端类 `openai_compat`/`anthropic`/`azure_openai`/`openai_codex`/`github_copilot`/`codebuddy` 及 `openai_responses/`）的内部细节归 guide-llm-providers，本文仅在衔接处引用其入口（`deeptutor/services/llm/provider_core/base.py:73` 的 `LLMProvider`、`:439` `chat_with_retry`、`:488` `chat_stream_with_retry`）。
- 一句话：本目录是"装配与策略层"——把 Settings 里的模型配置解析成 `LLMConfig`，按共享注册表挑出后端，织入能力门控/多模态/推理参数，再交给 provider_core 执行；错误、用量、诊断都在这一层归一化。

## 0. 全景与关键文件表

| 文件 | 角色 | 一句话 |
| --- | --- | --- |
| `__init__.py` | 门面 | 汇出 complete/stream/config/异常；`cloud_provider`/`local_provider` 走 `__getattr__` 惰性导入（`__init__.py:177-185`） |
| `factory.py` | 主入口 | `complete`/`stream`/`fetch_models`/presets；配置解析+重试+能力门控+错误映射的装配点 |
| `provider_factory.py` | 后端装配 | 按 backend 构建一个 provider_core 实例；每事件循环 2 槽 LRU 池 |
| `client.py` | 遗留类门面 | `LLMClient` 包装 factory；单例 `get_llm_client`；reset 时连带清 provider/agentic 池 |
| `config.py` | 配置 | `LLMConfig` 数据类 + `get_llm_config()`（resolver → 缓存 → ContextVar 作用域覆盖） |
| `capabilities.py` | 能力 | provider/model/目录三级能力表 + 运行时负缓存；`supports_*` 谓词 |
| `context_window.py` | 上下文窗口 | 已知窗口表 + 降级启发式，供 agent 循环做历史规划 |
| `error_mapping.py` | 错误映射 | 任意 SDK 异常 → 统一 `LLMError` 体系 |
| `exceptions.py` | 异常 | `LLMError` 层级；retryable 标记在 `LLMProviderTransportError`/`LLMReasoningBudgetExhausted` |
| `request_compat.py` | 错误分类器 | 判"参数不被支持/传输可重试"的谓词，供重试与优雅降级路径共用 |
| `structured_retry.py` | 结构化重试 | 推理模型吃光预算返回空 JSON 时，降 reasoning effort 重试一次 |
| `reasoning_params.py` | 推理参数 | 按厂商/模型家族拼 `reasoning_effort`/`extra_body` 思考开关 |
| `multimodal.py` | 多模态 | Stage-1 乐观注入图片；Stage-2 失败降级为文本占位 |
| `openai_http_client.py` | SDK 传输 | AsyncOpenAI 构造 kwargs：会话亲和头、OpenRouter 署名、TLS 校验开关 |
| `traffic_control.py` | 限流原语 | 并发信号量 + 令牌桶；当前仅作为 `LLMConfig` 字段类型存在（见 §7 空白） |
| `metrics.py` | 用量观测 | CallMeasurement/MeasuredStream/instrument_client，回合级 token 统计 |
| `usage_frame.py` | 用量归一 | 三种 usage 载荷形状 → 规范三元组 + 缓存/推理明细 |
| `usage_ledger.py` | 用量台账 | 每用户 sqlite（`usage.sqlite3`），只存数字与标识符 |
| `usage_estimation.py` | 用量兜底 | provider 不报 usage 时按 chars/3.5 + 每图 1024 估算 |
| `request_cache.py` | 诊断 | 请求前缀指纹（整条消息哈希），做 KV 缓存命中诊断；不含内容明文 |
| `telemetry.py` | 日志装饰器 | `track_llm_call`：debug 级调用日志 |
| `types.py` | 流结束类型 | `StreamOutcome`/`TRUNCATED_FINISH_REASONS`；`TutorResponse`/`TutorStreamChunk` |
| `utils.py` | 工具 | 本地服务器判定、URL 清洗、thinking 标签清理、响应内容抽取、auth 头 |
| `cloud_provider.py` | 模型发现(云) | 只做 `GET /models`；complete/stream 是弃用 shim |
| `local_provider.py` | 模型发现(本地) | Ollama `/api/tags` + OpenAI `/models`；complete/stream 弃用 shim |
| `registry.py` | 类注册表 | 独立的 provider 类装饰器注册表（通用能力，非路由主链） |
| `provider_registry.py` | 兼容 shim | 3 行：`from deeptutor.services.provider_registry import *`（`provider_registry.py:3`） |
| `image_description.py` | 图片描述选型 | 文档解析的图片描述模型选择 + 隔离 client |
| `image_caption_batch.py` | 批量图注 | ID 校验批注 + 二分切分；`image_caption_cache.py` 做工作区级缓存 |

## 1. 客户端装配与调用链

一次 `complete()` 的完整路径（同步 `stream()` 同理，见下）：

1. **入口**：Agent 层 `deeptutor/agents/base_agent.py:28-29` 导入 `complete`/`stream`（`__init__.py:89-99` 再导出自 factory），`:462`/`:634` 调用。
2. **配置解析**：`factory.complete`（`factory.py:411`）→ `_resolve_call_config`（`factory.py:157`）：显式传了 model+key+endpoint/binding 时构造独立 `LLMConfig`（且经 `_matching_current_config` `factory.py:129` 判定与当前全局配置一致时保留 profile 级 extra_headers/reasoning_effort）；否则从 `get_llm_config()` 复制并按参数覆盖。供应商名由 `_resolve_provider_spec`（`factory.py:81`）决定：显式 binding → 网关（key/base_url 反查）→ 按模型反查 → 本地端口启发式 → 兜底 openai；全部查自共享注册表 `deeptutor/services/provider_registry.py`（PROVIDERS/find_by_name/find_gateway/effective_backend）。
3. **后端实例**：`get_runtime_provider(config)`（`provider_factory.py:144`）以 13 元组为键（loop+provider+model+key 指纹+URL+headers+wire_api+采样参数，`provider_factory.py:29-45`）做**每事件循环** 2 槽 LRU 池（`provider_factory.py:17`）；无运行中 loop 时不缓存。`_build_runtime_provider`（`provider_factory.py:48`）按 `effective_backend` 挑 provider_core 类；openai profile 带 api_version 会升级为 azure_openai（`provider_factory.py:58-62`）。`complete_with_config`（`factory.py:458`）则走 `build_isolated_provider`（`provider_factory.py:131`，不污染进程环境，用后 `aclose`，`factory.py:515-516`）。
4. **请求整形**：`_build_messages`（`factory.py:268`）拼 system+user；`_apply_inline_image_data`（`factory.py:295`）把裸 `image_data` 参数转成多模态附件走 `multimodal.prepare_multimodal_messages`（`multimodal.py:122`）；`_sanitize_call_kwargs`（`factory.py:317`）剥掉路由参数、按能力表丢弃 `response_format`；重试延迟表 `_build_retry_delays`（`factory.py:66`，指数上限 120s，默认值来自 settings.retry，`factory.py:31-33`）。
5. **进入 provider_core（衔接点，细节归 guide-llm-providers）**：`provider.chat_with_retry(...)`（`factory.py:387-394`）；异常一律 `map_error(exc, provider=...)` 再抛（`factory.py:395-396`）；`finish_reason=="error"` 的响应也走 `map_error`（`factory.py:398-401`）。reasoning_content 与 content 相同的"网关复制推理"去重（`factory.py:405-408`）。
6. **流式**：`factory.stream`（`factory.py:519`）在 provider 回调与调用方之间放一个 asyncio 队列：reasoning 增量包 `<think>…</think>` 控制符（`factory.py:588-607`、`:36`）；首块直发、后续按 `stream_coalesce_chars`(64)/`stream_coalesce_seconds`(0.04) 合帧（`factory.py:654-717`、`:34-35`）；结束时把 `finish_reason`+usage 写入可选的 `StreamOutcome`（`factory.py:622-624`；类型在 `types.py:23`，截断判定 `types.py:14-19`）；无正文时补发 `response.content`（`factory.py:632-639`）；错误经 `map_error` 后以异常形式抛出（`factory.py:640-648`）。
7. **模型列表**：`fetch_models`（`factory.py:726`）三分支：codebuddy 专用（→provider_core/codebuddy_models）、本地（`local_provider.py:22`，Ollama `/api/tags` 优先）、云（`cloud_provider.py:65`）。设置页的 provider 预设也由共享注册表生成（`factory.py:747-778`，`API_PROVIDER_PRESETS`/`LOCAL_PROVIDER_PRESETS`）。

**横切衔接**：`reset_llm_client()`（`client.py:230`）在 Settings 重载时同步清 provider 池（`provider_factory.py:182`）与 agentic 客户端池（`client.py:240-244`）。agentic 运行时（`deeptutor/runtime/agentic/client.py:241,247,259`）用 `metrics.instrument_client` 给自建 SDK client 套同一套计量。

## 2. 能力（capabilities.py）

- 三张静态表：`PROVIDER_CAPABILITIES` 按 binding（`capabilities.py:27`，含 openai/anthropic/codebuddy/volcengine/moonshot/本地四件套等 20+ 项）；`DEFAULT_CAPABILITIES` 兜底未知 provider（`capabilities.py:260`）；`MODEL_OVERRIDES` 按模型前缀（`capabilities.py:274`，最长前缀优先，见 `_static_capability` `capabilities.py:453-486`；`models/` 前缀归一 `capabilities.py:469`）。
- 第四级、最高优先级：用户在 Settings>Models 的逐模型覆盖。`set_catalog_capability_overrides`（`capabilities.py:372`）整体替换内存表，字段映射 `CATALOG_CAPABILITY_FIELDS`（`capabilities.py:363`，tools/vision/json_output → supports_*）；查询入口 `catalog_capability_override`（`capabilities.py:393`）。`get_capability` 的完整优先序：目录覆盖 → 模型前缀 → binding → 默认 → default 参数（`capabilities.py:422-450`）。
- 两个**运行时负缓存**（进程内 set，重启清零）：某 (binding,model) 实测拒绝 `response_format` 后 `disable_response_format_at_runtime`（`capabilities.py:498`）让它永久跳过；拒绝强制 tool_choice 后 `disable_forced_tool_choice_at_runtime`（`capabilities.py:527`）。写入点在 provider_core 的重试路径（衔接：`provider_core/openai_compat_provider.py:663,1047`）。
- 常用谓词：`supports_response_format/streaming/tools/vision/vision_url`、`system_in_messages`、`has_thinking_tags`、`requires_api_version`（`capabilities.py:544-665`）；强制温度 `get_effective_temperature`（`capabilities.py:668`，gpt-5/o1/o3 锁 1.0，`capabilities.py:319-327`）；会话型 binding 集合 `SESSION_SCOPED_BINDINGS`（`capabilities.py:697`，目前仅 codebuddy）。
- 设置页"Auto 显示"用 `effective_capabilities`（`capabilities.py:411`）。

## 3. 配置（config.py + openai_http_client.py）

- `LLMConfig` 数据类（`config.py:110-131`）：model/api_key(可列表=key 池，`get_api_key` 取主键 `config.py:151-157`)/base_url/effective_url/binding/provider_name/provider_mode/api_version/extra_headers/wire_api/api_format/reasoning_effort/context_window/max_tokens/temperature/max_concurrency/requests_per_minute/traffic_controller。
- `__post_init__`（`config.py:133-145`）保证 `api_format`（用户可见协议选择）与 `wire_api`（OpenAI 端点）互相推导一致。
- 解析链：`get_llm_config()`（`config.py:235`）→ ①当前 async 上下文的 `set_scoped_llm_config`（ContextVar，`config.py:161-174`；book 引擎与模型选型任务用，`deeptutor/book/engine.py`、`deeptutor/services/model_selection/runtime.py`）→ ②进程级缓存 `_LLM_CONFIG_CACHE`（`clear_llm_config_cache` `config.py:270`，`reload_config` `config.py:277`）→ ③`resolve_llm_runtime_config()`（services/config 的运行时适配器）包成 LLMConfig（`config.py:193-232`，含占位 key 校验）。模块导入时提前同步 OPENAI_* 环境变量（`config.py:90-107`）。
- 新旧 token 参数：`uses_max_completion_tokens`（`config.py:283`，o 系列/gpt-4o/gpt-5+ 用 `max_completion_tokens`）与 `get_token_limit_kwargs`（`config.py:316`）。
- OpenAI SDK 客户端构造 kwargs 统一在 `openai_sdk_client_kwargs`（`openai_http_client.py:117-158`）：`x-session-affinity` 随机头、OpenRouter 署名头（`openai_http_client.py:23`）、TLS 校验开关（`DISABLE_SSL_VERIFY`，prod 环境直接拒绝 `openai_http_client.py:32-46`；失效 CA 路径自动清除 `openai_http_client.py:61-84`）。

## 4. 上下文窗口（context_window.py）

- 解析优先序 `resolve_effective_context_window`（`context_window.py:188-201`）：显式配置 `context_window`（上限 1,000,000，`context_window.py:9`）→ `KNOWN_CONTEXT_WINDOWS` 精确表（`context_window.py:34-140`，models.dev 快照；支持 `ns/name` 与日期后缀剥离，`context_window.py:143-153`）→ 大窗口家族标记（`context_window.py:11-28`，含 grok，注释里点名 agent 循环裁切事故）→ 兜底 65,536 / 16,384（`context_window.py:10,8`）。
- 消费方：agent 循环历史预算 `deeptutor/agents/loop/context_budget.py:102`、`deeptutor/agents/loop/pipeline.py:88`、会话上下文构建 `deeptutor/services/session/context_builder.py`。`LLMConfig.context_window` 字段即由目录解析填入（`config.py:231`）。

## 5. 错误映射与重试分类（error_mapping.py / exceptions.py / request_compat.py / structured_retry.py）

- 异常层级（`exceptions.py`）：`LLMError:11` → `LLMConfigError:32`、`LLMProviderError:38`（→ 可重试的 `LLMReasoningBudgetExhausted:44`、`LLMProviderTransportError:55`、`LLMCircuitBreakerError:66`）、`LLMAPIError:72`（→ `LLMTimeoutError:98`/`LLMRateLimitError:111`(带 retry_after)/`LLMAuthenticationError:124`/`LLMModelNotFoundError:135`）、`LLMParseError:148`；映射别名 `ProviderQuotaExceededError:161`、`ProviderContextWindowError:165`。
- `map_error`（`error_mapping.py:148-175`）：已是 `LLMError` 的原样返回（只补 provider 字段，`error_mapping.py:159-162`）；先看 status_code 401/429（`:165-169`）；再过规则表 `_GLOBAL_RULES`（`:122-145`：超时、SDK 认证/限流类名（按 `__mro__` 名字匹配免导入 SDK，`:49-56`）、消息含 rate limit/429/quota、context length）；最后兜底 `LLMAPIError`。限流错误保留服务端 Retry-After（数字或 HTTP-date，`error_mapping.py:59-110`）。
- `request_compat.py` 是"参数级优雅降级"的判别器：`is_stream_options_unsupported:61`、`is_response_format_unsupported:78`、`is_forced_tool_choice_unsupported:103`、`is_tool_schema_unsupported:135`（刻意不匹配裸 "tool" 字样，#708）、`is_image_input_unsupported:184`、`is_transient_transport_error:203`（沿 `__cause__` 链找 httpx/httpcore/openai 传输错误）。消费方：agent 循环（`deeptutor/agents/loop/agent_loop.py`）、agentic 步骤（`deeptutor/runtime/agentic/labeled_step.py`）、provider_core 重试（衔接）。`logged_error_text`（`:31`）把日志里的错误体截到 2000 字符再落盘。
- 结构化输出兜底：`payload_with_reasoning_retry`（`structured_retry.py:49-83`）——推理模型把 `max_tokens` 花在思考上导致空/截断 JSON 时，以 `RETRY_REASONING_EFFORT="low"`（`reasoning_params.py:11`）重试一次；"可用"判据由调用方注入（`json_payload_is_usable` `structured_retry.py:40`）。Book 各阶段的统一出口（模块 docstring `structured_retry.py:1-29`）。
- 推理参数拼装 `build_openai_compatible_reasoning_kwargs`（`reasoning_params.py:138-224`）：厂商思考开关风格表（`:23-31`）、默认关思考的家族（`:40-49`，gemini-3/gemini-2.5-pro 只能 "minimal"）、OpenRouter 走 extra_body（`:196-199`）；由 provider_core openai_compat 调用（衔接 `provider_core/openai_compat_provider.py:450`）。

## 6. 多模态与图片描述链（multimodal.py / image_*.py）

- Stage-1 乐观注入：`prepare_multimodal_messages`（`multimodal.py:122-178`）不看 supports_vision，永远先注入（修 Doubao/VolcEngine 丢图 bug，`multimodal.py:130-137`）；本地附件 URL（`/files/attachments/...`）无条件解析成 base64（`multimodal.py:227-229`、`:86-119`），外部 URL 不抓取（`multimodal.py:90-92`）。仅 Anthropic 式绑定与 `vision_url_supported=False` 的 provider 强制 base64（`multimodal.py:169`）。
- Stage-2 失败降级：请求带图失败后，`should_degrade_to_text`（`multimodal.py:341-357`）=确有图块 且 `supports_vision` 为假 → 用 `strip_image_parts`（副本，`:301`）或 `strip_image_parts_inplace`（原地，`:322`）换文本占位重试；已知视觉模型保留原图让真实错误浮出。
- 文档图片描述：`get_image_description_client`（`image_description.py:42-46`）按解析设置选型，`resolve_image_description_config` 校验必须支持 vision（`:15-20`）；隔离 client 覆写 `complete` 走 `complete_with_config` 保住完整 profile（`:23-39`）。
- 批量图注：`ImageCaptionBatcher`（`image_caption_batch.py:56`）单图直调、多图发 ID 校验 JSON 批（指令 `:18-23`，解码校验 `:30-53`）；只对"结构化响应坏/上下文超限"二分切分（`:123-128`），认证/限流失败置 `halted` 停掉本任务后续批（`:129-134`）；SDK 重试与图片回退关闭，N 图至多 2N-1 次调用（`:56-64`）。`image_caption_cache.py` 以"完整配置身份+请求身份（图字节 SHA-256，不含图原文/密钥/URL）"为键做工作区级缓存（`image_caption_cache.py:46-73`），单图 `complete_image_caption:97`、批 `complete_image_caption_batch:156`；消费方 `deeptutor/reading/captions.py` 与 `deeptutor/services/rag/pipelines/llamaindex/document_loader.py`。

## 7. 观测、记账与诊断（metrics.py / usage_*.py / request_cache.py / telemetry.py）

- 回合记账：`current_usage`/`measurement_active` ContextVar（`metrics.py:69-71`）；`CallMeasurement`（`metrics.py:74`）记录 TTFT/生成时长/字符数，provider 未报 usage 时按 `usage_estimation.estimate_prompt_tokens`（`usage_estimation.py:15-45`，图片块每块 1024 token 估算、不解码图片）+ chars/3.5 兜底（`metrics.py:127-140`）。接入点：provider_core 每次尝试经 `measure_provider_call`（`metrics.py:183`，衔接 `provider_core/base.py:349-360`）；agentic 自建 SDK client 经 `instrument_client`/`MeasuredStream`（`metrics.py:258,214`，衔接 `runtime/agentic/client.py:241`）。
- usage 归一：`usage_frame.usage_mapping/token_counts/usage_breakdown`（`usage_frame.py:27,49,80`）统一 dict/pydantic/裸对象三种形状与 chat/responses 两套字段名，处理 Anthropic 缓存计数补回（`usage_frame.py:149-155`）。
- 持久台账：`usage_ledger.record_call`（`usage_ledger.py:43-73`）写每用户 `usage.sqlite3`（WAL，仅数字与标识符，路径 `usage_ledger.py:37-40`）；读取/合并 `usage_records:76`/`merge_records:110`/`combined_usage_records:141`（call_id 去重防台账/快照重叠）；API 侧消费 `deeptutor/api/routers/settings.py`。
- 诊断与杂项：`request_cache.fingerprint_request/compare_requests`（`request_cache.py:22,44`）给 agent 循环做连续请求公共前缀诊断（消费 `deeptutor/agents/loop/agent_loop.py`）；`telemetry.track_llm_call`（`telemetry.py:19`）是 debug 日志装饰器；`traffic_control.TrafficController`（`traffic_control.py:13`，信号量+令牌桶）目前只作为 `LLMConfig.traffic_controller` 的字段类型被引用（`config.py:131`），生产代码无实例化点。

## 8. 现有测试与覆盖空白

测试目录 `tests/services/llm/`（provider_core 后端的测试亦在此目录，归 guide-llm-providers 复盘）。与本文范围直接对应的：`test_factory_provider_exec.py`(15)、`test_client.py`(9)、`test_config_module.py`(10)、`test_capabilities.py`(17)、`test_capabilities_catalog_overrides.py`(5)、`test_model_overrides.py`(9)、`test_context_window.py`(3)、`test_error_mapping.py`(8)、`test_request_compat.py`、`test_structured_retry.py`(8)、`test_reasoning_params.py`(11)、`test_multimodal.py`(11)、`test_openai_http_client.py`(6)、`test_ssl_env_sanitizer.py`(7)、`test_cloud_provider.py`(5)、`test_local_provider.py`(3)、`test_metrics.py`(5)、`test_usage_frame.py`(12)、`test_usage_ledger.py`(7)、`test_usage_estimation.py`(6)、`test_request_cache.py`(3)、`test_image_caption_batch.py`(11)、`test_image_caption_cache.py`(15)、`test_image_description_selection.py`(6)、`test_traffic_control.py`(1)、`test_telemetry.py`(2)、`test_registry.py`(1)、`test_utils.py`(15)、`test_unreachable_endpoint_hint.py`(4)、`test_key_rotation.py`(1)、`test_public_exports.py`(1)。基线实测：`pytest tests/services/llm --ignore=tests/services/llm/test_llm_live.py` → **573 passed, 9.97s**。

覆盖空白（均指本文范围内文件，按风险排序）：

1. `factory.stream` 的队列/合帧/`<think>` 包裹/`StreamOutcome` 回填（`factory.py:519-723`）无直接单测——仅 `tests/book/test_reasoning_output_cap.py` 与 `tests/agents/math_animator/test_utils.py` 间接触到 StreamOutcome；`stream_coalesce_*` 参数、错误以异常抛出的路径（`factory.py:640-648,705-708`）未覆盖。
2. `types.py` 的 `TutorResponse`/`TutorStreamChunk`（`types.py:42,60`）无任何测试引用（生产代码也未使用，疑似预留模型）。
3. `exceptions.py` 无专属测试文件，仅经 `test_error_mapping.py` 间接覆盖；`LLMReasoningBudgetExhausted`/`LLMProviderTransportError` 的 retryable 语义无断言。
4. `traffic_control.TrafficController` 仅 1 个测试且无生产实例化点（`config.py:131` 只是类型引用）——要么接线要么明确其为预留原语。
5. `provider_registry.py`（3 行 shim）、`telemetry.py`、`registry.py` 覆盖极薄（0-2 个测试）。
6. `client.py` 的 `complete_sync` 事件循环内拒绝分支（`client.py:183-186`）、`reset_llm_client` 连带清 agentic 池（`client.py:240-244`）未见断言。
7. `utils.build_chat_url`/`build_completion_url`/`extract_response_content`（`utils.py:205,228,266`）生产代码无调用方（仅 `__init__` 再导出），属于对外兼容面，测试有但价值待定。

## 9. 验证记录

- 全部结论基于 `origin/main @ f07029cfc`（v1.6.13）只读复核；本文不改任何代码。
- 测试：`pytest -q tests/services/llm --ignore=tests/services/llm/test_llm_live.py`（pytest 9.1.1）→ 573 passed / 0 failed。
