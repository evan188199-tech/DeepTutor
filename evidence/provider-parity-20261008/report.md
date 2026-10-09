# scan: LLM provider 失败路径一致性清点（provider_core）

- 基线：origin/main `6cf793bd8`（v1.6.14），只读清点，不改任何代码
- 范围：`deeptutor/services/llm/provider_core/` 全部 provider 文件 + 说明中点名的 cloud/local（模型发现面）+ 直接决定失败语义的公共层（base / factory / agent_loop / agentic client）
- 方法：逐文件通读 + 与测试文件比对，每条差异附 `path:line`；已有测试覆盖的标注测试名
- 分组：超时 / 限流与重试 / 鉴权失败 / 流中断 / 取消语义 / 能力开关覆盖面

## 0. 覆盖的 provider 文件

| 文件 | 职责 |
| --- | --- |
| `provider_core/base.py` | 公共重试/瞬时错误分类/图片降级 |
| `provider_core/openai_compat_provider.py` | 所有 OpenAI 兼容端点（含 KeyPool、Responses 断路器） |
| `provider_core/github_copilot_provider.py` | Copilot OAuth，继承 compat |
| `provider_core/azure_openai_provider.py` | Azure Responses-only |
| `provider_core/anthropic_provider.py` | Anthropic SDK 直连 |
| `provider_core/codebuddy_provider.py` | CodeBuddy Agent SDK（有状态会话） |
| `provider_core/codebuddy_http_provider.py` | CodeBuddy HTTP（继承 compat） |
| `provider_core/openai_codex_provider.py` | Codex OAuth，httpx 裸 SSE |
| `provider_core/codebuddy_models.py`、`openai_responses/*`、`__init__.py` | 模型目录与 Responses 转换/解析（无独立失败路径） |
| `llm/cloud_provider.py`、`llm/local_provider.py` | 仅模型发现；聊天走 provider_core |

## 1. 超时处理差异

- **T1 流式空闲超时不统一**。compat / Azure / Anthropic 流式均有每 chunk 90s 空闲超时（`openai_compat_provider.py:1110`、`openai_compat_provider.py:1223-1226`；`azure_openai_provider.py:213`、`azure_openai_provider.py:222-224`；`anthropic_provider.py:565`、`anthropic_provider.py:578-581,596-599`），超时统一转“stream stalled for more than 90 seconds”错误响应（`openai_compat_provider.py:1252-1256`、`azure_openai_provider.py:240-244`、`anthropic_provider.py:601-605`）。**CodeBuddy SDK 路径无空闲超时**：`codebuddy_provider.py:535`（会话）与 `codebuddy_provider.py:579`（一次性）直接 `async for`，SDK 卡死则 provider 层永久挂起；只有能力侧 agent_loop 的 90s 包装（`agent_loop.py:116-123`）兜底，factory.stream 直连路径无保护。Codex 用 httpx `timeout=60.0`（`openai_codex_provider.py:209`），read timeout 顺带充当 60s 空闲上限，数值与其他 provider 不一致。
- **T2 非流式 chat 无任何 DeepTutor 侧超时**。compat `chat`（`openai_compat_provider.py:988-1081`）、Anthropic `chat`（`anthropic_provider.py:511-538`）、Azure `chat`（`azure_openai_provider.py:163-187`）都不设超时，仅靠 SDK 默认（约 600s）且 SDK 重试已关闭（`openai_compat_provider.py:217`、`azure_openai_provider.py:110`、`anthropic_provider.py:57`）；而 CodeBuddyHTTP 的 `chat()` 实际内部走流式从而获得 90s 空闲保护（`codebuddy_http_provider.py:124-135`）。同一调用入口在“会不会被 90s 兜底”上行为不同。
- **T3 辅助路径超时缺口**：`fetch_codebuddy_models` 子进程 `await process.communicate()` 无超时（`codebuddy_provider.py:837`），CLI 挂起则永久等待；cloud/local 模型发现有 30s 总超时（`cloud_provider.py:91`、`local_provider.py:47`）。Copilot token 交换/模型拉取 20s（`services/github_copilot_auth.py:65,170,205`）、CodeBuddy 刷新 30s（`services/codebuddy_credentials.py:282`）。

## 2. 限流与重试语义差异

- **R1 三层重试策略并存且口径不同**。base：最多 4 次尝试、退避 (1,2,4)s，按状态码 {408,429,500,502,503,504} + 文本标记分类（`base.py:76-90`、`base.py:334-437`），factory.complete/stream 走这一层（`factory.py:387`、`factory.py:612`）。agent_loop：退避 (0.5,1.5)s，只认 `is_transient_transport_error` 且只在未产出输出时重试（`agent_loop.py:110`、`agent_loop.py:1424-1460`），已产出输出时改为 salvage（`agent_loop.py:455-475`）。同一 provider 失败在两条调用链上的重试次数、退避、可重试集合都不同。
- **R2 结构化重试信号在 base 层丢失**。Codex 把传输类失败 re-raise 为 `LLMProviderTransportError`（`openai_codex_provider.py:123-128`），agent_loop 会重试它；但 base `_is_transient_error` 只认 TimeoutError/ConnectionError 实例与文本标记，不认 `LLMProviderTransportError`/`retryable` 属性（`base.py:316-332`；`exceptions.py:57-64` 的 `retryable=True` 无人读取）——同一次 Codex 网络抖动经 factory.chat_with_retry 时不重试、经 agent_loop 时重试。
- **R3 429 KeyPool 轮换仅 compat 一家**：`_create_with_key_rotation` 在 429 时换 key 重试 `max(2, len(pool))` 次（`openai_compat_provider.py:230-249`），Anthropic/Azure/Codex/Copilot/CodeBuddy 均单凭据无轮换。已有测试：`tests/services/llm/test_key_rotation.py::test_openai_compatible_llm_tries_every_api_key_after_429`。
- **R4 Responses 断路器仅 compat 有**：同一 (model|effort) 连续 2 次失败后 300s 内不再尝试 Responses 端点（`openai_compat_provider.py:74-75`、`openai_compat_provider.py:494-505`、`openai_compat_provider.py:526-536`）；Azure 是 Responses-only 无此保护，失败直接每次打到端点。
- **R5 compat Responses→chat 兜底面不一致**：400/404/422 且报文匹配端点不支持特征时回退 chat.completions（`openai_compat_provider.py:622-659`、`openai_compat_provider.py:1017-1024`）；github_copilot 与 `wire_api=responses` 明确不回退（`openai_compat_provider.py:1018-1021`、`openai_compat_provider.py:1186-1189`；Copilot 端点能力见 `github_copilot_provider.py:99-115`）。Azure 无任何回退。已有测试：`tests/services/llm/test_github_copilot_provider.py::test_responses_only_error_never_falls_back_to_chat`；`tests/services/llm/test_openai_compat_responses_fallback.py`。
- **R6 请求体级自愈重试仅 compat 有**：`input[N].status` unknown_parameter 剥离重试（`openai_compat_provider.py:601-619`）、response_format 被拒后去参重试（`openai_compat_provider.py:1042-1054`、`openai_compat_provider.py:1201-1213`）、forced tool_choice 被拒降级 required 一次（`openai_compat_provider.py:668-715`、`openai_compat_provider.py:1057-1069`、`openai_compat_provider.py:1257-1275`）、工具参数 400 自动转流式（`openai_compat_provider.py:1070-1080`）。Anthropic/Azure/CodeBuddy/Codex 同类 400 一律直接失败。
- **R7 重试回放安全缺口**：base `_call_with_retry` 的图片降级重试（`base.py:397-424`）与 compat 流式 forced-tool_choice 重试（`openai_compat_provider.py:1257-1275`）都没有 agent_loop 那样的“已产出输出不得回放”守卫（对照 `agent_loop.py:1436` `can_retry = not output_emitted ...`）；错误发生在中途时第二次调用会把已发出的 delta 再发一遍。
- **R8 空 choices 处理**：compat 非流式空 choices 返回 error 响应（`openai_compat_provider.py:816`）；流式空流返回 content=None+stop（`openai_compat_provider.py:934-950`）；其余 provider 无对应分支。

## 3. 鉴权失败路径差异

- **A1 Copilot：每请求前主动换发**，60s 提前量、`_refresh_lock` 串行（`github_copilot_provider.py:24`、`github_copilot_provider.py:75-88`）；未登录直接 RuntimeError（`github_copilot_provider.py:61-64`）；无 401 事后恢复，`raise_for_status` 产生的 5xx 文本（含 "server error"）会被 base 标记误判为可重试（`services/github_copilot_auth.py:83,178,219`）。
- **A2 CodeBuddyHTTP：主动刷新 + 一段不可达的 401 重试**。过期凭据请求前刷新（`codebuddy_http_provider.py:87-105`）；但 `_chat_impl` 的 `except AuthenticationError: 重载凭据重试一次`（`codebuddy_http_provider.py:136-149`）是**死代码**——父类 `chat_stream` 把一切 Exception 吞成 error 响应（`openai_compat_provider.py:1252-1276`），AuthenticationError 永远到不了这里。无测试覆盖该分支；已有测试只覆盖主动刷新：`tests/services/llm/test_codebuddy_http_provider.py::test_expired_session_is_refreshed_before_the_request`、`::test_signed_out_provider_reports_how_to_sign_in`。
- **A3 Codex：401 只恢复不重试**。恢复会话后原样 re-raise（`openai_codex_provider.py:90-107`），由外层转成“session was refreshed; retry this request”错误响应（`openai_codex_provider.py:241`），用户手动重试；刷新令牌被拒时 fail-fast（`services/codex_auth/service.py:720-729`）。与其他 provider“要么自动重试要么明确失败”的口径都不同。
- **A4 CodeBuddySDK：API key 靠进程环境变量瞬时替换**，全局锁串行（`codebuddy_provider.py:778-792`）；鉴权失败文案特判（`codebuddy_provider.py:761-768`），不自动重试。
- **A5 Anthropic/Azure：静态 key，无任何恢复路径**（`anthropic_provider.py:57-72`、`azure_openai_provider.py:84-112`）。

## 4. 流中断与错误出口差异

- **S1 SSE error 事件**：Responses 解析统一 raise（`openai_responses/parsing.py:450-451`，SDK 流 `parsing.py:663`），已有测试：`tests/services/llm/test_openai_responses_parsing.py::test_response_failed_raises_the_provider_error`、`::test_sdk_top_level_error_event_raises`、`::test_sdk_failed_terminal_event_is_not_misreported_as_stop`。CodeBuddySDK 的 error result 转错误响应并**丢弃已累积文本**（`codebuddy_provider.py:536-540`）。
- **S2 错误消息前缀不统一**（影响 base 文本分类）：compat/Anthropic “Error: …”或“Error calling LLM: …”（`openai_compat_provider.py:953-963`、`anthropic_provider.py:75-89`）、Azure “Error calling Azure OpenAI: …”（`azure_openai_provider.py:156-161`）、CodeBuddy “Error calling CodeBuddy: …”（`codebuddy_provider.py:761-775`）、Codex “Error calling Codex: …”（`openai_codex_provider.py:113-135`）。provider 上抛结构化状态码时 base 走 `_status_code_from_exception`（`base.py:287-301`），但自拼字符串路径只能靠标记匹配。
- **S3 Codex usage 丢失**：`consume_sse` 只返回 (content, tool_calls, finish_reason)，不回传 usage（`openai_responses/parsing.py:358-363`），Codex 响应无 usage（`openai_codex_provider.py:108-112`）；compat Responses 流走 `consume_sdk_stream` 有 usage（`parsing.py:555`）。Codex 流量在用量/成本账本里恒为 0。
- **S4 工具调用 ID 稳定性**：compat 非流式把 id 换成随机短 id（`openai_compat_provider.py:840`），流式保留累积 id（`openai_compat_provider.py:941`）；Anthropic/Codex 保留 provider id（`anthropic_provider.py:459`）。
- **S5 中断排空仅 CodeBuddy 有**：工具调用后 interrupt 并 drain 残留消息，失败仅告警（`codebuddy_provider.py:552-562`、`codebuddy_provider.py:576-587`）。已有测试：`tests/services/llm/test_codebuddy_provider.py::test_codebuddy_session_drains_interrupt_before_tool_result_round`、`::test_codebuddy_interrupt_failure_after_tool_calls_logs_warning`、`::test_interrupted_drain_logs_error_type_without_exception_body`。

## 5. 取消语义差异

- **C1 统一的部分**：所有 `except Exception` 均不会捕获 CancelledError（Python 3.8+ 为 BaseException），base 重试循环显式 re-raise（`base.py:384-385`）。✅
- **C2 CodeBuddy 会话取消不传播**：`run_turn` 只往队列投递并 await future（`codebuddy_provider.py:121-133`），等待方被取消后 owner task 继续生成到结束，仅结果被丢弃；HTTP 系 provider 取消即断连。`aclose()` 还会 `uncancel()` 吞掉清理期取消（`codebuddy_provider.py:355-367`）。
- **C3 agent_loop 消费侧**：取消时把已积累文本写回 messages 再 raise（`agent_loop.py:1416-1432`），provider 层无对应行为。

## 6. 能力开关覆盖面差异（配置开关）

- **K1 temperature**：compat/Azure/Copilot 按模型名门控（`openai_compat_provider.py:398-406`、`azure_openai_provider.py:114-122`，Copilot 追加 gpt-6-astra：`github_copilot_provider.py:90-97`）；Anthropic thinking 家族强制 1.0 或省略（`anthropic_provider.py:415-431`）；**CodeBuddy 直接丢弃**（`codebuddy_provider.py:183`）、**Codex 直接丢弃**（`openai_codex_provider.py:148`）。
- **K2 max_tokens**：compat 按 spec 切 max_completion_tokens/max_tokens（`openai_compat_provider.py:436-439`）；Azure→max_output_tokens（`azure_openai_provider.py:141`）；CodeBuddy 尽力传入 options（`codebuddy_provider.py:434-436`）；**Codex 完全丢弃**（`openai_codex_provider.py:148`）——无法控输出预算。
- **K3 reasoning**：compat 按 spec 生成（`openai_compat_provider.py:449-456`）；Anthropic enabled/adaptive/off-sentinel 三态（`anthropic_provider.py:396-431`）；Azure effort+preview 门（`azure_openai_provider.py:147-149`）；CodeBuddy adaptive/disabled（`codebuddy_provider.py:626-638`）；Codex 原样透传（`openai_codex_provider.py:71-72`）。
- **K4 on_reasoning_delta**：compat/Azure/Anthropic/Copilot 支持；**CodeBuddySDK 丢弃**（`codebuddy_provider.py:207`）、**Codex 丢弃**（`openai_codex_provider.py:164`）。
- **K5 on_tool_args_delta**：仅 compat 声明（`openai_compat_provider.py:1094-1097`）；Copilot/CodeBuddyHTTP 注释明确不加入（`github_copilot_provider.py:212-217`、`codebuddy_http_provider.py:173-178`）。
- **K6 tool_choice**：compat 有被拒降级（见 R6）；Anthropic thinking 时强制 auto（`anthropic_provider.py:298-314`，已有测试 `tests/services/llm/test_anthropic_provider_fixes.py::test_off_sentinels_leave_tool_choice_to_the_caller`）；CodeBuddy 忽略（`codebuddy_provider.py:183,207`）；Codex/Azure 纯转换（`openai_codex_provider.py:68`、`azure_openai_provider.py:150-152`）。
- **K7 DISABLE_SSL_VERIFY**：OpenAI 系 SDK 客户端与 cloud 模型发现支持且禁 prod（`openai_http_client.py:33-46`、`cloud_provider.py:31-54`）；**local_provider 不支持**（无 connector 分支，`local_provider.py:47-49`）；Codex 支持但语义相反（默认不验证、由设置开启验证，`openai_codex_provider.py:87`）。已有测试：`tests/services/llm/test_codex_disable_ssl_verify.py`、`tests/services/llm/test_ssl_env_sanitizer.py`。
- **K8 会话亲和/传输选择**：CodeBuddy 后端 http/sdk 由 `DEEPTUTOR_CODEBUDDY_BACKEND` 决定（`codebuddy_http_provider.py:217-248`）；SDK 会话池上限 4、签名失配即重建（`codebuddy_provider.py:29-30`、`codebuddy_provider.py:304-347`）。

## 7. 测试覆盖标注汇总

已覆盖：base 瞬时分类（`test_provider_retry_classification.py`）、图片降级（`test_provider_core_image_fallback.py`）、429 轮换（`test_key_rotation.py`）、Copilot 预取/端点路由/不回退（`test_github_copilot_provider.py`）、CodeBuddy 主动刷新/未登录/中断排空（`test_codebuddy_http_provider.py`、`test_codebuddy_provider.py`）、SSE error 事件（`test_openai_responses_parsing.py`）、SSL 开关（`test_codex_disable_ssl_verify.py`）、agentic client 停滞转异常（`tests/core/test_agentic_client_provider_kwargs.py:214-223`）。

未覆盖（与上文差异编号对应）：provider 层 90s 空闲超时与 stall 错误（T1，仅 client 层有测）、非流式无超时（T2）、`fetch_codebuddy_models` 无超时（T3）、Codex 传输异常经 base 不重试（R2）、图片降级/forced-tool 重试的回放安全（R7）、CodeBuddyHTTP 401 死代码分支（A2）、Codex 401 恢复后不自动重试（A3）、CodeBuddy 取消不传播（C2）、Codex usage 丢失（S3）、CodeBuddy/Codex 的 temperature/max_tokens/reasoning 丢弃（K1-K4）。

## 8. 差异 Top5（供修复/补测卡取数）

1. **A2 CodeBuddyHTTP 401 重试死代码**：`codebuddy_http_provider.py:136-149` 依赖父类抛出 AuthenticationError，但 `openai_compat_provider.py:1257-1276` 吞掉一切异常，凭据过期后既不刷新重试也不给登录指引，直接错误响应。
2. **R2/R1 Codex 结构化重试信号跨层丢失**：`openai_codex_provider.py:123-128` raise 的 `LLMProviderTransportError(retryable=True)` 在 base `_is_transient_error`（`base.py:316-332`）下不被识别，factory 链路不重试而 agent_loop 链路重试，同一故障两种命运；建议 base 识别 `retryable` 属性。
3. **T1/T2 CodeBuddySDK 无空闲超时 + 全体非流式无超时**：`codebuddy_provider.py:535,579` 无 90s 兜底（仅 agent_loop 侧有）；`fetch_codebuddy_models` 子进程无超时（`codebuddy_provider.py:837`）。
4. **R7 重试回放安全**：base 图片降级（`base.py:397-424`）与 compat 流式 forced-tool_choice 重试（`openai_compat_provider.py:1257-1275`）缺 `output_emitted` 守卫（对照 `agent_loop.py:1436`），中途失败重放可致 delta 重复下发。
5. **S3 Codex usage 恒缺**：`consume_sse` 不回传 usage（`openai_responses/parsing.py:358-363`），Codex 全链路无用量统计，成本账本对 Codex 失明。

## 9. 建议后续卡

- fix：CodeBuddyHTTP 401 死代码（A2）——在 `_chat_impl` 外层识别错误响应中的鉴权语义，或让 HTTP 子类走不吞异常的底层调用。
- fix：base `_is_transient_error` 识别 `LLMProviderTransportError`/`retryable`（R2）。
- test：provider 层空闲超时参数化测试（compat/azure/anthropic/codebuddy 四路对比）。
- fix：Codex usage 回传（S3）与取消传播（C2）。
