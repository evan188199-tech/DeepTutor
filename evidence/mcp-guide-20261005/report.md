# DeepTutor `services/mcp/` 集成导读（发现 / 鉴权边界 / 工具衔接）

- 基线：origin/main @ `f07029cfc`（v1.6.13）。只读导读，未改任何产品代码。
- 范围：`deeptutor/services/mcp/` 全部 11 个文件 + 三个消费面（`api/routers/mcp_settings.py`、`api/routers/space_mcp.py`、`runtime/providers/view.py`）+ 与 chat 工具注册链的衔接点。
- 所有锚点形如 `path:line`，相对仓库根；省略统一前缀 `deeptutor/`。
- 行文约定：本导读是功能与边界说明，不包含任何漏洞利用细节。

## 0. 去重声明（与 guide-tools / guide-subagent 的关系）

| 已有导读 | 覆盖面 | 与本卡的重叠 |
|---|---|---|
| `evidence/guide-tools-2026-10-04/guide.md`（基线 `ef2d9e5c3`） | `deeptutor/tools/` 内建工具面：四段注册链（协议 → builtin 目录 → 进程 ToolRegistry → per-turn compose）、能力选择点 | **不同面**。MCP 是外部 provider，不是内建工具。重叠仅在共享接缝：`BaseTool.deferred`（`core/tool_protocol.py:246`）、`DeferredToolLoader`（`runtime/registry/deferred_tools.py:116`）、`ScopedToolRegistry`（`runtime/registry/scoped_registry.py:40`）。本导读在 §6 只写 MCP 一侧如何接进这条链，链本身的细节看 guide-tools §1 |
| `evidence/guide-subagent-20261004/guide.md`（基线 `f07029cfc`） | `deeptutor/services/subagent/`：把 agent CLI/Partner 当可咨询对象 | **不同面**。subagent 是 provider kind `cli`/partner 通道，MCP 是 kind `mcp`。两者的授权策略被刻意分开（`runtime/providers/authorize.py:1-15`），互不引用；本导读 §5.4 只在授权对比处提到它 |

即：读"工具是什么、内建工具怎么挂"看 guide-tools；读"咨询别的 agent"看 guide-subagent；读"外部 MCP 服务器怎么接、怎么鉴权、怎么变成模型可调用的工具"看本卡。

## 1. 这一层是什么

`services/mcp/` 是 MCP（Model Context Protocol）客户端集成层：把部署级和用户级配置的 MCP 服务器连起来，把它们的工具包成 chat `BaseTool` 适配器（`services/mcp/manager.py:105`），走渐进披露（deferred）进入每一轮。

三个一次读懂的设计决定：

1. **一个 server 形状，两个 store**（`services/mcp/config.py:5-11`）。部署级 `settings/mcp.json`（管理员写）与用户级 `data/system/user-mcp/<owner>.json`（每账号自己的）共用 `MCPServerConfig`（`config.py:31`），但存储位置、传输限制、网络策略完全不同。
2. **连接任务绑定**（`manager.py:8-27`）。MCP SDK 的 anyio cancel scope 是 task 绑定的，所以每台服务器有专属"连接任务"（`_run_server`，`manager.py:672`）端到端持有 `AsyncExitStack`；主循环只在 `(owner, server)` 键上等待结果。
3. **凭证永不进 config**（`services/mcp/secrets.py:8-16`）。配置里只存 `${secret:<server>/<field>}` 引用（`secrets.py:37`），连接时在内存解析；值落在 exec 沙箱永不挂载的 `data/system` secrets 树下（`multi_user/paths.owner_secrets_dir`）。

## 2. 模块地图

| 文件 | 行数 | 角色 | 关键入口 |
|---|---|---|---|
| `services/mcp/__init__.py` | 32 | 门面导出 | 全部公共 API（`:19-32`） |
| `services/mcp/config.py` | 161 | 部署级配置模型与持久化 | `MCPServerConfig:31`、`MCPConfig:100`、`load_mcp_config:119`、`save_mcp_config:133`（原子写+fsync）、`mcp_config_path:115` |
| `services/mcp/manager.py` | 1031 | 连接管理器 + 工具适配器（本层核心） | `MCPConnectionManager:235`、`MCPToolAdapter:105`、`call_tool:423`、`ensure_scope:296`、`probe_server:893`、`wrapped_tool_name:100`、`get_mcp_manager:1017` |
| `services/mcp/user_config.py` | 233 | 用户级配置存储与自服务校验 | `load_user_mcp_config:80`（含拒绝清单）、`save_user_server:121`、`assert_name_available:149`、`MAX_SERVERS_PER_OWNER:44` |
| `services/mcp/secrets.py` | 192 | 静态凭证引用存储与解析 | `SECRET_REFERENCE_RE:37`、`store_secrets:67`、`resolve_references:96`、`resolve_url_references:131` |
| `services/mcp/oauth.py` | 438 | OAuth 2.1（SDK 之上的三件事） | `AuthorizationRequired:64`、`OwnerTokenStorage:154`、`build_auth:256`、`begin_authorization:329`、`complete_authorization:404`、`oauth_redirect_uri:218` |
| `services/mcp/network.py` | 121 | 远程服务器 URL 校验（双策略 SSRF 守卫） | `validate_mcp_url:69`、`validate_mcp_url_async:108`、被屏蔽网段表 `:31-47` |
| `services/mcp/session_state.py` | 59 | 会话内已加载 deferred 工具的持久化 | `load_loaded_tools:28`、`record_loaded_tools:45`；文件 `loaded_tools.json`（`:20`） |
| `services/mcp/catalog/models.py` | 332 | 目录条目数据模型与安装合成 | `McpCatalogEntry:142`、`CredentialField:106`、`build_server_config:238`、`normalize_transport:88` |
| `services/mcp/catalog/loader.py` | 249 | 内置目录（离线 JSON）加载/搜索/分页 | `load_catalog:57`（lru_cache）、`search_catalog:127`、`category_counts:100` |
| `services/mcp/catalog/vendor/curated.json` | — | 内置精选目录，45 个条目 | 数据文件，随发布走 |

依赖方向：`config` ← `user_config`/`catalog.models` ← `manager` ← API 路由与 provider 层；`secrets`/`oauth`/`network` 被 `manager` 与路由两侧使用；`session_state` 被 `runtime/registry/deferred_tools.py:197` 反向使用。`mcp` 包是可选依赖，全部 import 延迟到函数内（`manager.py:545,682,757-760`；缺包路径有专门测试 `tests/services/mcp/test_missing_mcp_dependency.py`）。

## 3. 调用图

### 3.1 连接生命周期（每台服务器一个任务）

```
配置写入（admin PUT /api/settings/mcp 或用户 PUT /api/space/mcp/servers/{name}）
  → save_mcp_config (config.py:133) / save_user_server (user_config.py:121)
  → manager.reload (manager.py:278) / reload_scope (manager.py:319)
  → _sync_to_config (manager.py:604)   按 connection_signature 差分
      ↓ 新增/变更
  → _connect (manager.py:623)          建 _ServerConnection + 连接任务
      → _run_server (manager.py:672)   连接任务：AsyncExitStack 全程持有
          → _open_transport (manager.py:749)   选 stdio/sse/streamableHttp
              → _materialize (manager.py:729)  解析 ${secret:...}（仅内存）
              → 用户级先过 validate_mcp_url_async(strict=True) (manager.py:787-791)
              → cfg.auth=="oauth" 时 build_auth (manager.py:800-808)
          → ClientSession.initialize + list_tools (manager.py:688-690)
          → 按enabled_tools/disabled_tools 过滤成 adapters (manager.py:691-705)
          → ready.set_result → _register_adapters (manager.py:867)
      ↓ 失败
  → _mark_failed (manager.py:664)      指数退避 30s→300s 重试 (manager.py:68-69)
  → _needs_authorization → status="needs_auth"（不进退避，等人点授权）(manager.py:656-661)
```

读取/重建入口：`ensure_started`（部署级，`manager.py:262`，懒启动）、`ensure_scope`（用户级，`manager.py:296`，每轮调用并做空闲驱逐 `_evict_cold_scopes:338`：TTL 900s、上限 64 个 owner scope，`manager.py:75-76`）、`_retry_failed:367`（退避到期重连）。

### 3.2 每轮聊天：MCP 工具如何进入模型

```
AgenticLoopPipeline._compose（agents/loop/pipeline.py:613）
  → build_tool_view (runtime/providers/view.py:70)   契约：永不抛异常（view.py:9-12）
      → manager.ensure_started / ensure_scope（3s 上限，view.py:33-36,196-206）
      → shared_pool = base_registry.deferred_tools()  （进程表里的部署级 adapters）
      → owned_pool  = manager.ensure_scope(owner)     （仅本轮 overlay）
      → authorize_mcp_tools (runtime/providers/authorize.py:26)  授权过滤
      → workspace 绑定再过滤 deployment:/account:（view.py:138-150）
      → ScopedToolRegistry(overlay=owned_pool+…) (view.py:157-165; scoped_registry.py:40)
      → DeferredToolLoader + render_deferred_tools_manifest（一行/工具进系统提示）
  → 系统提示出现 "### MCP server: <provider_id>" 分组（runtime/registry/deferred_tools.py:107）
  → 模型调用 load_tools → DeferredToolLoader.load (deferred_tools.py:171)
      → schema 追加进本轮 tool_schemas（run_agentic_loop 每轮重读）
      → record_loaded_tools 持久化到会话（session_state.py:45）
  → 模型调用 mcp_<server>_<tool>
      → dispatcher → MCPToolAdapter.execute (manager.py:153)
          → manager.call_tool (manager.py:423)
              → _call_watching_connection (manager.py:474)  盯住连接任务，死了立刻报真因
              → session.call_tool (+progress_callback) (manager.py:547-557)
          → 文本块拼接返回；进度通知经 event_sink 发 tool_progress 事件 (manager.py:176-213)
```

### 3.3 OAuth 授权流（唯一交互入口在路由）

```
UI 点"授权" → POST /api/space/mcp/servers/{name}/authorize (api/routers/space_mcp.py:169)
  → oauth.begin_authorization (services/mcp/oauth.py:329)
      → forget 旧授权 (:348) → 后台任务 _drive (:371) 触发 SDK 流
      → SDK 要 redirect → _redirect 记 URL 并以 state 入 _PENDING (:353-366)
      → 返回 authorize_url 给前端
浏览器 → GET /api/space/mcp/oauth/callback?code&state (space_mcp.py:208)
  → complete_authorization(state, code) (oauth.py:404)  state 不匹配即 False
  → SDK 换 token → OwnerTokenStorage.set_tokens 落盘 (oauth.py:178)
后台连接路径（无人在场）→ refusing_handlers 抛 AuthorizationRequired (oauth.py:284-299)
  → manager 把状态标成 needs_auth (manager.py:656-661)
```

## 4. 配置项表

### 4.1 `MCPServerConfig`（`services/mcp/config.py:31-65`，两级 store 共用）

| 字段 | 默认 | 说明 |
|---|---|---|
| `type` | 自动推断 | `command`⇒stdio；`url` 以 `/sse` 结尾⇒sse；其余 url⇒streamableHttp（`resolved_type:72`） |
| `command`/`args`/`env`/`cwd` | 空 | stdio 专用；**用户级一律拒绝**（`user_config.py:178-183`） |
| `url`/`headers` | 空 | http 传输专用；headers 可携带静态凭证 |
| `tool_timeout` | 30 | 单次工具调用超时，1–600s（`config.py:48`） |
| `enabled_tools` | `["*"]` | 白名单，匹配原名或包装名（`tool_allowed:92`） |
| `disabled_tools` | `[]` | 黑名单，后于白名单应用（"除 X 之外全开"） |
| `enabled` | `true` | 关掉即断连且不发布工具（`manager.py:606`） |
| `auth` | `""` | `"oauth"` 为显式选择，不做 401 猜测（`config.py:54-59`） |
| `catalog_entry` | `""` | 安装来源记录（provenance），不计入连接指纹（`connection_signature:81`） |

服务器名必须匹配 `^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$`（`config.py:26`）。

### 4.2 存储位置

| 内容 | 位置 | 写入方 |
|---|---|---|
| 部署级服务器 | `<admin settings>/mcp.json`（`config.py:115-116`） | 仅 admin 路由（`/api/settings/mcp`，`mcp_settings.py:34`） |
| 用户级服务器 | `data/system/user-mcp/<owner>.json`（`user_config.py:70-77`；目录 0700） | 仅本人（owner 由服务端解析，`space_mcp.py:17-18`） |
| 静态凭证 | `<owner secrets>/private/mcp/<server>.json`（`secrets.py:39,59-64`；0600） | `store_secrets:67`（合并写，空串删除字段） |
| OAuth token+注册 | `<owner secrets>/private/mcp-oauth/<server>.json`（`oauth.py:54,89-99`） | `OwnerTokenStorage`（SDK 自动调用） |
| 会话已加载工具 | `<session workspace>/loaded_tools.json`（`session_state.py:20-25`） | `DeferredToolLoader._persist` |

### 4.3 常量与环境变量

| 项 | 值 | 位置 |
|---|---|---|
| `_CONNECT_TIMEOUT_S` | 15s | `manager.py:52` |
| 重连退避 | 30s 起、×2、上限 300s | `manager.py:68-69` |
| owner scope 上限 / 空闲 TTL | 64 / 900s | `manager.py:75-76` |
| 用户级服务器数上限 | 8/账号 | `user_config.py:44` |
| 用户级保留名前缀 | `mcp_`、`cli_`（防工具名伪造） | `user_config.py:49` |
| OAuth 回调路径 | `/api/space/mcp/oauth/callback` | `oauth.py:207` |
| `DEEPTUTOR_PUBLIC_URL` | 覆盖 redirect URI 基址（反代场景）；缺省取请求 origin，再缺省 `http://localhost:3782` | `oauth.py:212-232` |
| OAuth 流超时 | 600s（`FLOW_TIMEOUT_S`） | `oauth.py:326` |
| OAuth 客户端标识 | `DeepTutor` / `https://deeptutor.info` | `oauth.py:60-61` |
| 目录分页 | 默认 24、上限 100 | `catalog/loader.py:40-41` |
| 目录条目 | 45 个（curated.json），请求路径零网络 | `catalog/loader.py:1-15` |

### 4.4 凭证进配置的四条通道（目录安装时）

`CredentialField.target = (kind, name)`（`catalog/models.py:112`）：`env`（stdio）、`header`（远程）、`url_param`（远程，存进 url 查询串的 `${secret:...}` 引用保持字面量不编码，`models.py:296-312`）、`arg`（stdio）。通道必须匹配传输（`models.py:202-209`）；带装饰的值（如 `Bearer {value}`）在**存凭证时**由 `value_template.render` 应用（`models.py:120,133`），因为连接期解析器只认整值引用（`secrets.py:108-110`）。

## 5. 鉴权与边界（双 store、双策略）

### 5.1 网络策略（`services/mcp/network.py`）

- **部署级**（管理员配置，`strict=False`）：只挡链路本地/云元数据段（169.254.0.0/16、fe80::/10）和 0.0.0.0/8（`network.py:31-35`）——自托管部署合法地连 localhost/LAN MCP。
- **用户级**（`strict=True`）：额外禁 loopback、私网四段、CGNAT/Tailscale 段（100.64.0.0/10）与 v6 ULA（`network.py:39-47`）——请求由持有全部 provider key 的应用进程发出，用户给的 URL 不能把它指进内网（`network.py:14-19`）。
- **连接时重校验**（`manager.py:784-791`）：DNS 可在保存后变化，保存时一次校验不算数；`validate_mcp_url_async` 用 `asyncio.to_thread` 避免阻塞解析（`network.py:108-118`）。
- **重定向**：用户级 `follow_redirects=False`（`manager.py:792`），部署级跟随。

### 5.2 stdio 与命令执行

stdio = 在宿主机以应用用户身份跑命令，永远 admin-only：用户级读入即拒绝并计入 `rejected` 清单（`user_config.py:178-183` + `load_user_mcp_config:101-118`），目录里 stdio 条目 `self_service` 强制 false（`catalog/models.py:196-200`），`_open_transport` 再挡一层（`manager.py:772-774`）。

### 5.3 凭证处理

- 引用形式 `${secret:<server>/<field>}` 只匹配**整值**（`secrets.py:37,108-110`），部分匹配不做（无可辩护边界）；URL 查询值是唯一例外，有专门入口（`resolve_url_references:131`）。
- 解析只发生在 `_materialize`（`manager.py:729-746`）：产物只在打开传输的瞬间存在，不持久化、不进日志、不进 API 返回。
- 错误信息里的 URL 统一脱敏（host 保留、userinfo/query 打码，`manager.py:958-986`），因为它会同时出现在设置页和给模型的工具结果里。
- reload 差分指纹混入解析后凭证的 SHA-256（`_signature:571-602`），轮转密钥后无需重启即可触发重连；只存摘要不存原值。
- `GET /servers` 只返回"哪些字段已配置"（`space_mcp.py:117-119`、`secrets.configured_fields:87`），永不回显值；保存时按**位置**而非客户端标签把 headers/env 字面值搬进 secret store（`_extract_credentials`，`space_mcp.py:402-457`）。

### 5.4 工具级授权链（fail-closed）

1. **grant**：非 admin 的 `grant.mcp_tools` 缺省即空集（fail-closed），`None`（不限）保留给 admin（`multi_user/tool_access.py:55-69`）。
2. **per-turn 合成**：`authorize_mcp_tools`（`runtime/providers/authorize.py:26-56`）——部署级服务器按工具名白名单，用户自配服务器按**所有权**直接放行（admin grant 不该管到用户自己的服务器）；partner 回合由其自身 `mcp_tools` 配置把关（`api/utils/tool_options.py:87-119` 负责把 kind=mcp 的行写进 grant 编辑器）。CLI 应用走独立 grant 字段，两策略不合并（`authorize.py:1-15`，guide-subagent 面）。
3. **workspace 绑定**：workspace 可再以 `deployment:<name>` / `account:<name>` 收窄（`view.py:138-150`；目录生成在 `services/workspace/resources.py:137-150`）。
4. **派发时强制**：以上都只过滤了 manifest；真正的门在 `ScopedToolRegistry.execute`——模型编造/text-protocol 兜底合成的未授权 provider 名在这里被拒（`runtime/registry/scoped_registry.py:9-21`）。
5. **名字防碰撞**：用户服务器名禁用 `mcp_`/`cli_` 前缀（防伪造他 provider 的工具名，`user_config.py:46-49,172-176`）；与部署级同名直接拒绝而不是遮蔽（`assert_name_available:149-161`），因为进程注册表是 last-writer-wins，遮蔽=别人调到你的服务器。用户级工具**永不进进程注册表**，只走本轮 overlay（`manager.py:861-890`、`view.py:157-165`）。

### 5.5 OAuth 边界

- token 与 client 注册按 `(owner, server)` 隔离存储，注册不跨账号共享（`oauth.py:27-31`）。
- 后台重连**永不**弹 consent：非交互 redirect/callback handler 立即抛 `AuthorizationRequired`（`oauth.py:284-299`），状态转 `needs_auth`（区别于 `error`，不进退避、UI 给"授权"按钮）。
- 回调只认 SDK 生成的 `state`（`_PENDING` 表，`oauth.py:318-323,404-414`）；未知 state 完成不了任何流。回调页是自关 HTML，`html.escape` 转义（`space_mcp.py:237-252`）。
- 删除服务器时同步删 config + secrets + OAuth 授权（`space_mcp.py:157-166`），不留无主 refresh token。

## 6. 与 chat 工具注册链的衔接（对照 guide-tools 四段链）

MCP 适配器是标准 `BaseTool`（`manager.py:105-151`），从第三段（进程注册表）与第四段（per-turn compose）之间插入：

| 链段（guide-tools §1） | MCP 侧的行为 |
|---|---|
| 协议 `BaseTool` | `MCPToolAdapter`：`deferred=True`、`provider_kind="mcp"`（`manager.py:108-110`）；`provider_identity` 返回 `("mcp", server_name)`（`core/tool_protocol.py:270`，适配器经 `owner/provider_id` 属性提供） |
| 目录/进程注册表 | 部署级 adapters 在连接成功时 `registry.register()`（`manager.py:867-880`）；断连时对称注销（`:882-890`）。用户级不走这段，只活在 `ScopedToolRegistry` overlay |
| per-turn compose | guide-tools 描述的 `compose_enabled_tools` 管**内建**工具；MCP 由 `build_tool_view`（`view.py:70`）单独装配，管线挂接点在 `agents/loop/pipeline.py:613-628`（回合第一个 await，契约不抛） |
| 渐进披露 | manifest 按 provider 分组渲染（`deferred_tools.py:97-113`），`load_tools` 拉全 schema；已加载集合按会话持久化（`session_state.py`），下一轮直接带 schema |
| 服务端参数缝（guide-tools §2） | MCP 无服务端注入参数；`event_sink` 是唯一的反向通道（进度事件，`manager.py:153-166`） |
| Settings/授权 UI | `tool_options.py:87-119` 把 kind=mcp 的工具列进 `mcp_tools`（grant 编辑器数据源）；admin 设置页走 `/api/settings/mcp` |

## 7. 常见故障模式

| 症状 | 根因与定位 |
|---|---|
| 工具返回 `(MCP server 'x' is not connected)` | 没连上/没启用；`call_tool:434-436`。查 `status()` 行（`manager.py:392-413`）里的 `error` 字段 |
| 连接 15s 超时 | `_CONNECT_TIMEOUT_S`（`manager.py:52,648-650`）；之后按退避在后续轮次重试（`:367-388`），不会死到重启 |
| 状态 `needs_auth` 而非 `error` | OAuth 服务器等人在场授权（`manager.py:656-661`、`oauth.py:284-299`）；UI 应给授权按钮而不是重试 |
| 错误只显示 "ExceptionGroup: unhandled errors in a TaskGroup" | 不应再出现：`describe_connect_failure`（`manager.py:933-955`）展开到叶子异常（401/DNS 等），深度限 5（`:1002-1011`） |
| 换了 API key 但服务器还用旧 key | 密文引用未触发重连——由 `_signature` 摘要差分解决（`manager.py:571-602`）；若仍复现，检查是否走了异常分支回退到 base 签名（`:595-599`） |
| 用户保存的 server 在列表里消失/带 reason | `load_user_mcp_config` 拒绝清单：stdio、超 8 个、非法名（`user_config.py:101-118`）；`GET /servers` 的 `rejected` 字段会带原因 |
| 保存 URL 被拒 "must be reachable on the public internet" | strict 网络策略（`network.py:93-105`）；域名解析到私网/保留段即拒，连接前还会再验一次 |
| 回合第一个 token 变慢 | `ensure_scope` 上限 3s（`view.py:33-36,196-206`）；列表页预热上限 5s（`space_mcp.py:62-65`）。慢服务器只丢它自己的工具，不挂回合 |
| 调用中连接断开报 "connection failed during the call" | 连接任务先死：watcher 机制（`manager.py:474-515`）放弃调用并报告真实原因，而不是等满 tool_timeout |
| 瞬时传输错误偶发后成功 | `BrokenPipeError/ConnectionResetError` 恰好重试一次（`manager.py:94-97,444-460`） |
| `load_tools` 报 unknown | 名字不在授权集（`deferred_tools.py:184-185`）；grant/workspace/allowlist 任一层都可能收窄了池子 |
| 长任务看不到进度 | 服务端没传 `event_sink` 时不向服务器请求进度（`manager.py:551-556`）；进度渲染永不抛异常（`:176-213`） |
| catalog 页打不开/条目缺失 | 单条手编坏的 JSON 只跳过该条（`catalog/loader.py:70-83`），不会拖垮整店；请求路径零网络（`:1-15`） |

## 8. 测试覆盖对照

| 被测面 | 测试 |
|---|---|
| 配置模型/持久化 | `tests/services/mcp/test_mcp_config.py`（14 例） |
| 连接管理器 scope/reload | `tests/services/mcp/test_manager_scopes.py`（10 例） |
| 调用失败/断连/超时/重试 | `tests/services/mcp/test_call_failures.py`（11 例） |
| 进度上报 | `tests/services/mcp/test_progress_reporting.py`（18 例） |
| secrets 引用 | `tests/services/mcp/test_secrets.py`（16 例） |
| OAuth | `tests/services/mcp/test_oauth.py`（20 例） |
| 用户级配置校验 | `tests/services/mcp/test_user_config.py`（13 例） |
| catalog | `tests/services/mcp/test_catalog.py`（50 例） |
| 缺 `mcp` 包降级 | `tests/services/mcp/test_missing_mcp_dependency.py`（1 例） |
| API 面 | `tests/api/test_mcp_settings_auth.py`、`tests/api/test_space_mcp.py` |
| provider 合成/授权 | `tests/runtime/providers/test_view.py`、`tests/runtime/registry/test_deferred_tools.py` |

覆盖缺口（可拆卡验证）：`_evict_cold_scopes` 的 TTL/容量驱逐（`manager.py:338-365`）与 `_retry_failed` 的退避节奏（`manager.py:367-388`）在现有测试里无直接用例（全 tests/ 检索无 `evict|retry_at|retry_delay|backoff` 命中）。

## 9. 可拆卡条目

按"一张卡一个可验证交付"拆，均已确认当前主干未实现：

1. **MCP scope 驱逐与退避的回归测试**（纯测试卡）：为 `_evict_cold_scopes`（TTL 900s、上限 64、keep 例外）和 `_mark_failed`/`_retry_failed` 退避序列（30→60→…→300 封顶）补确定性测试。验收：`timeout 900 python -m pytest -q tests/services/mcp/test_manager_scopes.py` 全绿且新增用例可独立复现驱逐/退避。
2. **目录 registry tier 同步**（功能卡）：`CatalogTier` 已含 `"registry"`（`catalog/models.py:43`）但 `catalog/loader.py` 只读内置 `curated.json`，无任何上游 registry 拉取路径。拆卡：设计离线快照 + 显式刷新的 registry 同步，保持"请求路径零网络"不变（`loader.py:1-15` 是现行约束）。
3. **per-tool 开关的管理 UI/审计**：`enabled_tools/disabled_tools` 字段与 `tool_allowed`（`config.py:92-97`）已支持按工具黑/白名单，但 admin 路由只有整服务器增删改（`mcp_settings.py:81-118`）。拆卡：设置页暴露 per-tool 勾选并写入现有字段（无 schema 变更）。
4. **`mcp_tools` grant 编辑器的 provider 分组**：`tool_options.py:102-118` 已返回 `kind/provider_id/server`（legacy 别名），可拆一张前端卡：按 `provider_id` 分组展示 + 移除 `server` 别名依赖（注释标明待客户端切换后删除）。
5. **OAuth 授权状态运维口**：`oauth_state`（`oauth.py:146-151`）只在 `GET /servers` 里按服务器暴露；可拆卡给 admin 一个跨账号"哪些服务器待授权"汇总（只读 presence，不含 token），支撑部署巡检。
6. **wrapped 名冲突的可观测性**：`wrapped_tool_name`（`manager.py:100-102`）把非法字符折叠成 `_`，两台名含不同非法字符的服务器理论上可折叠出同名工具（如 `a-b` vs `a.b`）。低概率但可拆一张小卡：注册时检测折叠后撞名并在 `status()` 里标 warning（用户级已被 `assert_name_available` 与 reserved 前缀挡住大半）。

## 10. 快速上手指引（新接手读代码的顺序）

1. `services/mcp/config.py` → 两个 store 共用的 server 形状；
2. `services/mcp/manager.py` 文件头注释（`:1-27`）→ 生命周期模型，再读 `_run_server`/`_open_transport`/`call_tool` 三条主线；
3. `runtime/providers/view.py` → 每轮怎么合成；
4. `runtime/registry/deferred_tools.py` + `session_state.py` → 渐进披露与会话记忆；
5. `api/routers/space_mcp.py` / `mcp_settings.py` → 两个 API 面（对应前端两个 store）;
6. 需要深挖再进 `oauth.py`/`secrets.py`/`network.py` 三个边界模块。
