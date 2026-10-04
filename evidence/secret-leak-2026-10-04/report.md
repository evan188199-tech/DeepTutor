# 敏感信息泄漏扫描报告（secret-leak-2026-10-04）

- 扫描基线：`origin/main` @ `ef2d9e5c3`（release v1.6.12），只读扫描，未改任何代码
- 扫描范围：`deeptutor/`（Python 后端）、`deeptutor_cli/`、`web/`（Next.js 前端）、`packages/`
- 方法：ripgrep 模式扫描 token/secret/api_key/authorization/password/credential 与 `print`/`logger.*` 的组合、`{e}`/`str(e)` 直拼日志与 `HTTPException(detail=str(e))` 直拼响应、前端 `console.log` 敏感词、前端内部 ID 直显（历史样本 #1647 模式）、硬编码密钥模式
- 等级定义：**外发** = 可到达浏览器/客户端响应；**仅日志** = 只落服务端日志；**低** = 泄漏内容有限或面向管理端

## 一、命中清单

### A. 外发（客户端可见）

| # | 位置 | 泄漏内容 | 等级 | 说明 |
|---|------|----------|------|------|
| A1 | `deeptutor/agents/research/pipeline.py:742`、`:743`、`:752-753` | 原始异常文本 `{type(exc).__name__}: {exc}` 经 `stream.content` 以 `⚠ ` 前缀直接显示在聊天 UI | 外发·中 | LLM/embedding 上游错误的 URL、响应体片段会直接呈现给终端用户；`error_message` 同时经 `stream.error` 进事件流 |
| A2 | `deeptutor/api/routers/settings.py:1977-1980` | `HTTPException(502, detail=f"Provider request failed: {exc}")`，`exc` 来自 `fetch_llm_models` 上游请求 | 外发·低 | key 走 header（`provider_probe.py:154`）不在异常里，但上游错误原文与内部 base_url 会透传到设置页 |
| A3 | `deeptutor/api/routers/knowledge.py:2913` | `error_msg = f"Error getting assigned KB '{resource.name}': {exc}"` 写入 KB 列表响应的 `metadata.last_error` / `error` 字段 | 外发·低 | 内部异常原文进入 Learner 可见的 KB 列表 |
| A4 | `deeptutor/api/routers/mcp_settings.py:73`、`:96` | `HTTPException(400, detail=str(exc))` | 外发·低 | MCP 配置读写异常原文返回客户端 |
| A5 | 全仓模式：`deeptutor/api` 下 `detail=str(e)` 类直拼共 **250 处**（knowledge.py 61、book.py 22、skills.py 21、partners.py 21、co_writer.py 16、partner_groups.py 15、notebook.py 12 等） | 异常原文进入 HTTP 响应 | 外发·低 | 绝大多数包裹本地配置/校验错误（内容受控），但该模式对"包裹上游 provider/HTTP 异常"的调用点会透传内部信息；属于系统性风险面，建议按调用点逐一改为白名单消息 |

### B. 仅日志

| # | 位置 | 泄漏内容 | 等级 | 说明 |
|---|------|----------|------|------|
| B1 | `deeptutor/services/embedding/adapters/base.py:113-126` | `EmbeddingProviderError.__str__` 拼接 `url=` 与 500 字符 `body=` 片段 | 仅日志·中 | 该放大器使 A 类调用点 `str(e)` 时同时带出 URL 与响应体；与 gemini 适配器的 `_redacted_body`/`safe_url`（`gemini.py:293`、`:330`）形成对照——上游错误体未脱敏 |
| B2 | `deeptutor/services/embedding/adapters/openai_compatible.py:276`、`:287`、`:291`、`:303`、`:328` | 原始响应体 `body_text`（截 2000 字符）直接 `logger.error`，并原样放入 `EmbeddingProviderError(body=...)` | 仅日志·中 | 与 B1 叠加后可能进入下游 `str(e)` 链路 |
| B3 | `deeptutor/services/embedding/adapters/openai_sdk.py:85-92` | `exc.response.text` 原样放入错误体 | 仅日志·中 | 同 B2 |
| B4 | `deeptutor/services/embedding/adapters/cohere.py:136` | `logger.error(f"HTTP {response.status_code} response body: {response.text}")` 全量响应体未脱敏 | 仅日志·低-中 | provider 4xx 响应体通常含账号/配额信息，偶尔回显请求参数 |
| B5 | `deeptutor/services/embedding/adapters/jina.py:122` | 同 B4 | 仅日志·低-中 | 同上 |
| B6 | `deeptutor/partners/channels/dingtalk.py:249` | `logger.error("Failed to get DingTalk access token: {}", e)` 记录 access_token 获取异常对象 | 仅日志·低 | 钉钉错误响应偶尔回显 appkey/参数 |
| B7 | `deeptutor/multi_user/identity.py:512` | `logger.warning("Failed to load/create auth secret at %s: %s", SECRET_FILE, exc)` 记录鉴权密钥文件绝对路径 | 仅日志·低 | 路径披露，不含密钥值本身 |
| B8 | `deeptutor/services/pocketbase_client.py:160` | `logger.debug(f"PocketBase token validation failed: {exc}")` | 仅日志·低 | debug 级；校验异常一般不含 token 值，但无脱敏兜底 |

### C. 前端内部资源 ID 直显（#1647 历史样本同类模式）

| # | 位置 | 泄漏内容 | 等级 | 说明 |
|---|------|----------|------|------|
| C1 | `web/components/chat/home/SessionActivityPanel.tsx:220-223` | 会话无标题时 fallback 直接以内部 session id 作为 title、`id.slice(0, 8)` 作为 subtitle 展示 | 低（外发 UI） | 与 #1647「聊天标签直显内部 ID」同型：内部 ID 出现在 Learner 界面 |
| C2 | `web/app/(workspace)/whisper/page.tsx:319` | 顶栏展示 `dtSessionId.slice(0, 8)` 内部会话 ID | 低（外发 UI） | 同型；仅 8 位截断，但仍是内部标识直显 |
| C3 | `web/components/whisper/WhisperRoomChip.tsx:29` | 完整 `roomId` 直显并附复制按钮 | 低（外发 UI·设计使然） | 房间 ID 用于双人入座分享复制，属功能需要；建议确认房间 ID 不承担鉴权语义 |
| C4 | `web/features/knowledge/components/engines/EngineDetail.tsx:529`、`:629` | `{p.id}`、`{indexType.id}` 直显 | 低（管理端） | 管理端展示引擎内部 ID，风险有限，建议标注为调试用途 |

## 二、误报清单（排除及理由）

| 位置 | 排除理由 |
|------|----------|
| `deeptutor/api/routers/system.py:482`、`deeptutor/services/config/provider_runtime.py:911` 等 6 处 `"sk-no-key-required"` | 字面占位符，非真实密钥 |
| `deeptutor/api/routers/auth.py:787/807/850` 等登录日志 | 仅记录用户名与角色，无 token 值 |
| `deeptutor/api/routers/knowledge.py:1459-1765` 各 config 端点、`deeptutor/services/config/settings_draft.py:124 redact_draft`、`settings.py` 的 `CATALOG_SECRET_MASK` 回填机制 | 刻意的脱敏设计：UI 只见掩码与布尔态，服务端还原真实 key；本次扫描未发现旁路 |
| `deeptutor/services/mcp/secrets.py:164`、`mcp/manager.py:598`、`mcp/oauth.py:175` | 仅记文件路径/服务名，无凭据值 |
| `deeptutor/multi_user/identity.py:132-134` | 记录密钥文件路径而非密钥值（与 B7 同源，B7 只保留"失败+异常对象"一条） |
| `deeptutor/partners/channels/telegram.py:273`、`slack.py:73`、`discord.py:74`、`wecom.py:78`、`qq.py:96`、`zulip.py:104`、`dingtalk.py:237` | "not configured" 类提示，不含值 |
| `web/scripts/i18n_audit.mjs:200` | 构建工具打印翻译 key，非运行时凭据 |
| 全仓未发现：前端 `console.log` 打印 token/密钥、硬编码真实密钥（16+ 位字面量模式）、token 拼入 URL query、`Authorization` 头入日志 | — |

## 三、整改建议（按优先级）

1. **P1 · 收敛外发面**：A1（`pipeline.py:742-753`）将 `visible_message` 改为受控文案（错误码 + 引导语），原始异常只进 `stream.error` 的服务端日志；A2/A3/A4 同理——客户端响应改白名单消息，`exc` 原文仅 `logger.exception`。
2. **P1 · 对齐脱敏基线**：把 gemini 适配器已有的 `_redacted_body`/`_redacted_url`（`gemini.py:117`、`:293`）提取为 `deeptutor/services/embedding/adapters` 共享工具，应用到 openai_compatible / openai_sdk / cohere / jina（B2-B5），并让 `EmbeddingProviderError.__str__`（B1）对 `url`/`body` 默认走脱敏。
3. **P2 · 前端内部 ID 兜底**：C1/C2 无标题场景改为中性占位（如 "未命名会话"），避免内部 session id 直显；C3 确认 roomId 无鉴权语义后可保留。
4. **P2 · 系统性收口 `detail=str(e)`**：250 处无需一次改完，优先审计其中包裹"上游 HTTP/provider 调用"的子集（可按 `probe|fetch|connect|request` 关键词定位），本地校验类可保留受控消息。
5. **P3 · 日志脱敏兜底**：在 `deeptutor/logging/formatters.py` 的 formatter/filter 层增加一次性正则脱敏（`sk-[A-Za-z0-9]{16,}`、`Bearer xxx`），为 B6-B8 类残余风险兜底。

## 四、验收对照

1. 每项命中均附 `path:line` 与泄漏等级 ✅
2. 误报单独列出并给排除理由 ✅
3. 全程未修改任何业务代码（本目录为本卡的证据产物分支） ✅
