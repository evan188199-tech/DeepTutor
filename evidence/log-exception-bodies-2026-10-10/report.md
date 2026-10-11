# SDK 异常体落日志泄漏面扫描报告

- 日期：2026-10-10
- 基线：`origin/main` @ `6cf793bd8`（release v1.6.14）
- 对照基准提交：`d967457e6`（fix(codebuddy): omit SDK exception bodies from warning logs）
- 性质：只读静态扫描，未改动任何代码
- 范围：LLM 提供方（`deeptutor/services/llm/`，含 `provider_core/`）、嵌入（`deeptutor/services/embedding/`）、搜索（`deeptutor/services/search/`，含 `providers/`）、IM 通道（`deeptutor/partners/channels/`）

## 1. 方法与覆盖

双通道互补扫描，人工复核每条命中：

1. AST 精确分析（`ast_log_scan.py`，随本报告附带）：解析函数内 `except ... as X` 绑定，检查日志调用（`logger.debug/info/warning/error/exception/critical`）参数中是否出现异常名本身、`str()/repr()` 包裹、f-string 插值、`%`-style 位置参数、异常属性（`.body/.response/.message/.reason/.stderr` 等）、`exc_info=True`、`logger.exception`，以及一层间接流（异常派生变量再入日志）。
2. ripgrep 兜底：`str(e|exc)`、`repr(e|exc)`、`e.body/e.response/.response.text`、外发 send 类调用拼接异常体等模式。

覆盖统计：100 个 `.py` 文件，445 个日志调用点；AST 原始命中 132 处，人工复核后确认整改项与误报见下文。基准提交的修复模式（日志只保留 `type(exc).__name__`，不携带消息体、不带 `exc_info`）作为判废标准。

风险分级口径：

- **外发**：异常体可到达用户可见面或外部系统（聊天回复、任务日志流/诊断 UI、向上传播的异常消息）。
- **仅日志**：异常体只落入本地/服务日志。
- **低**：内容敏感度低（内部路径、本地状态、debug 级），或仅类型名。

优先级：P1 建议尽快整改；P2 计划内整改；P3 顺带整改/观察。

## 2. 命中清单（整改项）

### P1 — 外发或完整响应体落日志（6 项）

| # | 位置 | 向量 | 风险 | 说明与建议 |
|---|------|------|------|------------|
| 1 | `deeptutor/services/embedding/adapters/cohere.py:136` | 完整响应体 | 仅日志（整响应体） | HTTP≥400 时 `logger.error(f"... response body: {response.text}")` 记录完整响应体；嵌入 API 错误响应可能回显请求文本（知识库片段）。建议：只记状态码 + 参照 gemini 适配器 `_redacted_body` 脱敏截断。 |
| 2 | `deeptutor/services/embedding/adapters/jina.py:122` | 完整响应体 | 仅日志（整响应体） | 同 #1 同型代码。 |
| 3 | `deeptutor/services/embedding/adapters/openai_sdk.py:83-95` | `exc.response.text`（回退 `str(exc)`）写入错误对象 | 外发 | `EmbeddingProviderError.body` 由 `base.py:117-127` 的 `__str__` 拼成 500 字符摘要进入错误消息，再经 #4 落任务日志流；docstring 自述面向"task log streams, UI surfaces"。建议：构造时脱敏（key/URL/回显文本）或仅保留 status。 |
| 4 | `deeptutor/services/embedding/client.py:164-176` | `{exc}` + `traceback.format_exc()` | 外发 | 批量嵌入失败 error 日志带完整异常消息与 traceback，注释自述进入"task log stream / KB diagnostics"；当异常为 `EmbeddingProviderError` 时消息含 #3 的 body 摘要。建议：同基准提交模式，只记 `type(exc).__name__` + 结构化字段（binding/model/batch_index 已在消息里）。 |
| 5 | `deeptutor/services/llm/provider_core/codebuddy_provider.py:761-775`（使用点 `:251`） | `str(exc)` 回退分支 | 外发（用户可见） | `_friendly_error` 白名单只覆盖"Authentication required"与"cancel scope"两类，其余返回 `f"Error calling CodeBuddy: {message}"` 作为 `LLMResponse.content` 直接回给用户。上游 `d967457e6` 仅修复了 warning 日志，未覆盖该用户可见路径。建议：未知类型只回类型名+指引，不拼 SDK 消息。 |
| 6 | `deeptutor/services/search/__init__.py:214-215,227` | `{exc}` 落 error 日志；`failures` 聚合后 `raise Exception("web search failed: " + "; ".join(failures))` | 外发（向上传播） | 各搜索 provider 原始异常体（可含 query、URL、响应体）拼进聚合异常消息向上抛，调用方日志与错误面均可见。建议：failures 只保留 provider 名 + 异常类型名。 |

### P2 — 仅日志，含 provider/SDK 异常体（按域分组）

**LLM 域**

| 位置 | 向量 | 说明与建议 |
|------|------|------------|
| `deeptutor/services/llm/provider_core/openai_compat_provider.py:708-713` | `str(exc)[:200]` | 与基准提交删除的 `_short_exception`（`str(exc)[:200]`）完全同型：forced tool_choice 被拒时落 warning。建议：只记类型名。 |
| `deeptutor/services/llm/telemetry.py:41` | `%s` 直拼 `e` | `track_llm_call` 装饰器内全量异常体落 warning；当前仓库无使用点（潜伏死代码），建议整改或删除。 |
| `deeptutor/services/llm/local_provider.py:82` | `%s` 直拼 `e` | 模型列表拉取失败，异常体含 base_url 等细节。 |
| `deeptutor/services/llm/cloud_provider.py:110` | `%s` 直拼 `e` | 同上。 |
| `deeptutor/services/llm/provider_core/openai_codex_provider.py:131` | `logger.exception` | 有注释说明为有意保留的运营可见性（用户面已脱敏，见 `:127` 仅类型名）；traceback 消息仍含 SDK 异常体。建议：保留决策但确认日志仅本地存储。 |
| `deeptutor/services/llm/multimodal.py:117` | `%s` 直拼 `exc` | 本地附件解析失败，附带记录内部附件 URL。敏感度低-中。 |

**嵌入域**

| 位置 | 向量 | 说明与建议 |
|------|------|------------|
| `deeptutor/services/embedding/adapters/openai_compatible.py:343,350` | f-string `{exc}` | 传输层重试/最终失败日志带 httpx 异常消息（含 URL/host）。建议：类型名 + status。 |
| `deeptutor/services/embedding/adapters/ollama.py:108` | f-string `{e}` | 本地 Ollama HTTP 错误体落 error 日志；本地端点，敏感度中-低。 |
| `deeptutor/services/embedding/client.py:208,284` | `{exc}` + `exc_info=True` | 进度回调失败（内部回调），敏感度低；归入 P3 亦可，此处按仅日志归档。 |

**搜索域**

| 位置 | 向量 | 说明与建议 |
|------|------|------------|
| `deeptutor/services/search/source_filter.py:236` | `%s` 直拼 `exc` | Moderation 请求失败；provider 错误可能回显送审文本（即用户内容）。敏感度中。 |
| `deeptutor/services/search/source_filter.py:325` | `%s` 直拼 `exc` | Web Risk 查询失败，异常体可含 URL。 |
| `deeptutor/services/search/consolidation.py:291` | f-string `{e}` | 模板渲染失败，jinja 异常可含模板/上下文片段。 |
| `deeptutor/services/search/__init__.py:57` | `%s` 直拼 `exc` | 策略加载失败（路径类信息）。低-中。 |

**通道域（IM channels）** — 通用模式为 `logger.error/warning("... {}", e)`（loguru `{}` 插值）与 `logger.exception`；SDK/HTTP 异常体可含访问凭证线索、完整请求 URL、响应体。除单独标注外均为"仅日志、中"，建议统一按基准提交整改为类型名：

| 文件 | 命中行（warning/error/exception/debug） | 备注 |
|------|----------------------------------------|------|
| `feishu.py` | 592, 731, 771, 1127, 1161, 1191, 1445, 1541, 1575, 1612, 1963, 2323, 2446（error/warning）；1228（exception，媒体下载）；70（exception，卡片回调）；308, 606, 1317, 1335（debug） | 上传/下载/流式卡片等面大 |
| `dingtalk.py` | 102, 196, 249, 295, 311, 365, 426, 548（error/warning）；206（exception + 直拼 `e`） | access_token 获取、媒体上传下载 |
| `zulip.py` | 223, 231（重试包装器，覆盖全部 API 调用）、126, 250, 280, 297, 313, 394, 672（warning/error）；845（debug） | 672 附件下载含 URL |
| `weixin.py` | 751, 860, 1364, 1398（warning）；232（`exc_info=True`）；378, 483, 780, 916, 1028, 1039, 1049, 1065（exception）；1101, 1140（debug） | 751 媒体下载 URL；1364/1398 为密钥相邻路径（当前异常消息不含键材料，建议该处避免拼异常，改记原因枚举） |
| `msteams.py` | 191, 205, 218, 602, 610, 817（warning）；300（exception） | 218 活动处理失败可间接携带用户内容相关异常 |
| `mochat.py` | 410, 509, 595, 609, 643, 712, 745, 998, 1023（warning/error） | 另有间接链：`:583` `_socket_call` 返回 `str(e)` 作 ack.message → `:573` error 日志消费 |
| `telegram.py` | 411, 510, 547, 682, 738, 760, 892（warning/error）；665, 1123（debug） | 547 HTML 解析回退路径 |
| `discord.py` | 97, 276, 322, 400, 452（warning/error）；507（debug） | 452 附件下载 |
| `slack.py` | 106, 138, 173, 245；265（exception） | |
| `mattermost.py` | 158, 177, 211, 367, 449；245（exception） | 367 附件下载 |
| `napcat.py` | 111, 239, 438, 578, 592（warning） | 578 图片下载含 URL |
| `wecom.py` | 204, 329, 362（error） | 362 媒体下载 |
| `email.py` | 146, 205（error） | |
| `whatsapp.py` | 79, 86（error/warning） | |
| `qq.py` | 119（warning）；203（exception） | |
| `matrix.py` | 271（exception） | 本地存储加载失败，敏感度低-中 |
| `registry.py` | 60（warning） | 插件加载失败；`:89-90` 另有 ImportError 文本经 `errors` 有意上 UI 做缺依赖诊断（按设计保留，见误报 #8） |

### P3 — 低敏感度（顺带整改）

`deeptutor/services/search/__init__.py:48`（配置加载 debug）、`deeptutor/services/llm/local_provider.py:61`（debug）、`deeptutor/services/embedding/client.py:208,284`（进度回调）、`deeptutor/services/llm/multimodal.py:117`、通道 debug 级：`feishu.py:308,606,1317,1335`、`telegram.py:665,1123`、`discord.py:507`、`slack.py:245`、`zulip.py:845`、`registry.py:90`。内容以内部路径/连接状态为主。

## 3. 传播链（非直接日志点，但决定异常体最终走向）

1. `EmbeddingProviderError.body`（`adapters/base.py:88-127`，`__str__` 拼 500 字符 body 摘要）→ `embedding/client.py:168` 错误日志（P1 #3→#4）。
2. `services/llm/error_mapping.py:43,116,126,131,143,167,175` — `str(exc)` 进入映射后 typed error 消息，作为 LLM 错误统一收敛点随调用链向上（日志/错误面）；本身无日志调用，整改上游日志点后此处影响随之收敛。
3. `partners/channels/mochat.py:583 → 573` — `_socket_call` 把 `str(e)` 放进 `ack.message`，由调用方 error 日志消费（间接流）。

## 4. 误报清单（排除理由）

| # | 位置 | 排除理由 |
|---|------|----------|
| 1 | `provider_core/codebuddy_provider.py:556,583` | 仅 `type(exc).__name__`，即 `d967457e6` 修复后的标准形态（扫描器初版对 `type()` 内层名字误报，修正规则后复核排除） |
| 2 | `deeptutor/services/llm/image_caption_batch.py:134` | 仅类型名（`(%s)` 传 `type(exc).__name__`） |
| 3 | `provider_core/openai_codex_provider.py:127` | 仅类型名，且注释明确不落 URL/body/token（`:131` 的 `logger.exception` 单列为 P2 决策项） |
| 4 | `partners/channels/napcat.py:484,535` | `err` 是 `validate_url_target` 返回的校验原因字符串，非异常体 |
| 5 | `partners/channels/weixin.py:281`、`partners/channels/weixin_qr.py:185` | 仅读取 `err.response.status_code`，未取消息体 |
| 6 | `partners/channels/telegram.py:622` | `str(exc)` 用于"message is not modified"错误分类判断，不落日志 |
| 7 | `services/llm/request_compat.py:36-56` | `error_text()` 提取 provider 错误体仅用于特性探测，函数内无日志调用；同文件 `_truncate_logged`（2000 字符截断）为既有缓解设施（当前仅内部使用、无脱敏） |
| 8 | `partners/channels/registry.py:89-90` | ImportError 文本经 `discover_all_with_errors` 有意上 UI 解释"缺失可选依赖"，内容为模块名；按设计保留 |
| 9 | `services/embedding/adapters/gemini.py` | 已实现 `_redacted_body`（对 key/URL/敏感请求文本脱敏后再进错误对象），为正向参照而非命中 |

另：`deeptutor/services/search/providers/`（serper/zhipu/youcom 等）未发现异常体落日志调用（0 命中）。

## 5. 整改建议（对齐基准提交模式）

1. **统一 helper**：新增共享工具（如 `exc_type_name(exc)` 与脱敏截断函数），provider 与通道统一引用；日志只带 `type(exc).__name__`，细节用结构化字段（provider/model/status_code/binding）表达。
2. **嵌入适配器**：以 `gemini.py` 的 `_redacted_body` 为参照，`cohere/jina` 的整响应体日志与 `openai_sdk` 的 `body=` 传递先脱敏再落错误对象/日志；`client.py:168` 改类型名 + 既有结构化字段。
3. **用户可见路径白名单化**：`codebuddy_provider._friendly_error` 与 `search/__init__.py` failures 聚合，已知模式（认证/取消/限流）给出友好文案，其余只回类型名 + 状态码。
4. **`logger.exception` / `exc_info=True`**：仅保留在明确需要运营可见性且日志仅本地的位置（如 codex:131，已有注释），通道 SDK 常规失败改为类型名。
5. **密钥相邻路径**：`weixin.py:1364/1398` 解析失败不拼异常消息，改记失败原因枚举。
6. **死代码**：`telemetry.track_llm_call` 无使用点，整改或删除。

## 6. 复现

```bash
python3 evidence/log-exception-bodies-2026-10-10/ast_log_scan.py <repo> \
  deeptutor/services/llm deeptutor/services/embedding \
  deeptutor/services/search deeptutor/partners/channels
```

原始 AST 输出见同目录 `scan_hits.json`（132 条）。所有 path:line 以 `origin/main` @ `6cf793bd8` 为准。本报告为静态模式扫描 + 人工复核，不含任何运行时验证、复现步骤或利用描述。
