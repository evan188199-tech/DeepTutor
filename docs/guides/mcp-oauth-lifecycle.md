# MCP OAuth 授权流生命周期导读（`services/mcp/oauth.py`）

- 基线：origin/main @ `6cf793bd8`（v1.6.14），行号以该基线为准。
- 范围：`deeptutor/services/mcp/oauth.py` 全文件；接点 `deeptutor/api/routers/space_mcp.py`（authorize/callback 路由）与 `deeptutor/services/mcp/manager.py`（非交互连接路径）；覆盖对照 `tests/services/mcp/test_oauth.py`。
- 用途：供“`_PENDING` 待定流回收”修复卡直接引用；锚点形如 `path:line`，相对仓库根。
- 结论速览：交互式授权流 = 模块级 `_PENDING[state]` 字典 + 每流一个 `asyncio.Future`。begin 阶段有 30s 兜底；**consent 等待阶段没有任何超时**——`FLOW_TIMEOUT_S` 已声明并导出但从未被施加，用户放弃或重复 begin 都会泄漏驱动 task 与 `_PENDING` 条目（§4、§7，即待回收修复的对象）。

## 1. 模块分层与角色

| 层 | 位置 | 职责 |
|---|---|---|
| 存储层 | `deeptutor/services/mcp/oauth.py:89`（`_store_path`）`/102`（`_read`）`/119`（`_write`）`/133`（`forget`）`/146`（`oauth_state`） | 每 `(owner, server)` 一个 0600 JSON，落在 owner secrets 树 `private/mcp-oauth/`（`:54`），在 exec 沙箱挂载之外；原子写（tmp + `os.replace`，`:121-128`）；文件损坏按“未授权”处理（`:111-115`）；服务器名做文件名，白名单正则 `_SAFE_NAME_RE`（`:57`，校验在 `:92-93`） |
| SDK 适配层 | `deeptutor/services/mcp/oauth.py:154`（`OwnerTokenStorage`）`/235`（`client_metadata`）`/256`（`build_auth`） | 把 token/注册读写交给 `mcp.client.auth.OAuthClientProvider`（SDK 负责发现、动态注册、PKCE、刷新）；`build_auth` 不传 handlers 即非交互形态（`:267-281`） |
| 非交互护栏 | `deeptutor/services/mcp/oauth.py:284-299`（`refusing_handlers`）`/64-74`（`AuthorizationRequired`） | 后台重连永远不开 consent：SDK 一要求重定向就抛 `AuthorizationRequired`，由 manager 归类为 `needs_auth` |
| 交互流 | `deeptutor/services/mcp/oauth.py:305-420` | 本导读主体：`_PendingFlow`（`:305-315`）、`_PENDING`（`:323`）、`begin_authorization`（`:329-401`）、`complete_authorization`（`:404-414`）、`_state_from`（`:417-420`） |

## 2. 状态图

```mermaid
flowchart TD
    idle["无流"] -->|POST /servers/{name}/authorize<br/>space_mcp.py:169| begin["begin_authorization<br/>forget 旧授权 oauth.py:348<br/>_drive 探测 POST :386"]
    begin -->|"30s 内 SDK 产出 authorize_url 且带 state<br/>oauth.py:353-366, 398"| pending["pending：_PENDING[state]<br/>task 阻塞在 flow.result :369<br/>浏览器跳 consent"]
    begin -->|"探测异常 :388-390 / 无 state :358-363 /<br/>30s 超时 :397-401 → task.cancel() :400"| dead["流失败，路由回 400<br/>space_mcp.py:196-204<br/>finally 清扫 _PENDING :391-394"]
    pending -->|“GET /oauth/callback?code&state<br/>state 命中 → complete_authorization<br/>space_mcp.py:208-226, oauth.py:404-414”| completing["SDK 用 code 换 token<br/>写入 store（OwnerTokenStorage :178-181）"]
    completing -->|"_drive 的 POST 返回 → task 正常结束<br/>finally 清扫（空）:391-394"| done["已授权：连接此后由 manager<br/>非交互路径使用存储 token"]
    pending -->|“用户放弃，永不回调”| leaked["泄漏：task 永挂 flow.result（:369）<br/>_PENDING 条目永驻（:323）<br/>无 reaper，FLOW_TIMEOUT_S 未生效 :326"]
    pending -->|“同一 server 再次 begin”| second["第二条流并存（各自 state）<br/>旧 grant 已被 forget（:348）"]
```

## 3. `_PENDING` 生命周期

### 3.1 begin（`deeptutor/services/mcp/oauth.py:329-401`）

1. 先 `forget(owner, server)`（`:348`）丢弃旧 token 与旧 client 注册——重授权意味着旧 grant 不要了，注册也不得复用（docstring `:342-345`、`forget` 语义 `:133-143`）。副作用：**第二次 begin 会立刻作废第一次流产出的 grant**。
2. 建 `url_ready` future 与 `_PendingFlow`（`:350-351`；字段 `:305-315`：`result` 由回调路由 resolve，`authorize_url`、`task`）。
3. 起 `_drive` task（`:396`）：构造非交互 client 后用**交互 handlers** 调 SDK（`:377-384`），`POST server_url` 触发 SDK 走“无 token → 发现 → 注册 → 拼 authorize URL”链（`:386-387`，注释 `:372-374`）。
4. SDK 调 `_redirect(authorize_url)`（`:353-366`）：从 URL query 里抠出 `state`（`_state_from`，`:417-420`）——`state` 是 SDK 生成的唯一回执凭证，回调只认它（键控理由 `:318-322`：按调用方供给的任何值匹配都会让一个人的 redirect 完成另一个人的 consent）。URL 无 `state` → 给 `url_ready` 置异常且**不**入 `_PENDING`（`:358-363`）；正常则 `_PENDING[state] = flow` 并 resolve `url_ready`（`:364-366`）。
5. `begin_authorization` 只等 `url_ready`，超时 30s（`:398`）；任何失败路径都会 `flow.task.cancel()` 后 re-raise（`:397-401`）。
6. SDK 调 `_callback()`（`:368-369`）即 `await flow.result`——**这里就是全流程唯一没有超时的挂点**。

### 3.2 consent 等待（pending 态）

浏览器停留在第三方 consent 页期间：`_drive` task 阻塞在 `await flow.result`（`:369`）；`_PENDING[state]` 持有 flow。此态**没有任何清理者**：`_drive` 的 `finally` 清扫（`:391-394`）要等 task 结束才会跑，而 task 在等 `flow.result`。

### 3.3 complete（`deeptutor/services/mcp/oauth.py:404-414`）

- `complete_authorization(state, code)`：`pop` 后对**已完成** future 返回 `False`（`:411`，天然防重放——测试 `tests/services/mcp/test_oauth.py:168-179`）；未知 `state` 返回 `False`（`:410-412`，测试 `:163-165`）。
- 成功则 `set_result((code, state))`（`:413`），SDK 在 `_drive` 内用 code 换 token，经 `OwnerTokenStorage.set_tokens` 落盘（`:178-181`），原 POST 重试后 `_drive` 正常结束，`finally` 清扫（此时条目已被 complete 弹掉，空转）。
- 交互流**不**驱动 manager 连接：授权完成后由 UI 轮询 `list_servers` 的 warm-up（`space_mcp.py:108-112`）触发 `ensure_scope` → 非交互 `_connect` 用存储 token 连上（`manager.py:841-850`）。

### 3.4 条目清除路径汇总（修复卡关心的全部出口）

| 出口 | 锚点 | 覆盖哪些情形 |
|---|---|---|
| complete pop | `deeptutor/services/mcp/oauth.py:410` | 回调正常/重放 |
| `_drive` finally 清扫本 flow 的条目 | `deeptutor/services/mcp/oauth.py:391-394` | 探测异常、30s 超时取消、正常结束 |
| `forget` | `deeptutor/services/mcp/oauth.py:133-143`（begin 前置 `:348`；删服务器路由 `space_mcp.py:164`） | 磁盘 grant + 注册 |
| ——缺失—— | 无 | **放弃 consent、重复 begin 的失败方、任何 pending 态超时**：条目与 task 永驻 |

## 4. 超时语义现状（修复卡核心）

- `FLOW_TIMEOUT_S = 600.0`（`deeptutor/services/mcp/oauth.py:326`，注释即意图：“consent 永远开着 = 泄漏 task + 泄漏条目”）**已导出（`:426`）但全仓库无任何施加点**（grep 仅命中定义与 `__all__`；`video_learning/invidious_account.py:28` 是同名无关常量）。
- 现状三段超时各管一段：begin 等 URL 30s（`:398`）；`_drive` 内 httpx client timeout 30s（`:386`，只约束探测请求本身）；`await flow.result`（`:369`）**无限期**。
- 后果：pending 态没有 reaper——放弃 consent 或重复 begin 的失败方都永久滞留（背景：myfork `scan/mutable-defaults-20261011` 的 REPORT 风险中项第 1 条，即 `_PENDING`（`oauth.py:323`）跨请求滞留，仅作线索）。
- 最小修复面（供修复卡评估，非本卡范围）：给 `_callback` 的 `await flow.result` 施加 `FLOW_TIMEOUT_S`（或等价 watchdog）。取消该 future 会让 SDK 内的 await 抛出、沿 `client.post` 传播退出 `_drive`，`finally` 清扫随之执行（`:368-394` 的既有 unwind 路径），无需额外清理代码；注意 `_drive` 的 `except Exception`（`:388`）不会吞 `CancelledError`（Python ≥3.8 语义），路径是干净的。

## 5. 回调校验（`deeptutor/api/routers/space_mcp.py:208-226`）

- 四分支：provider 回传 `error` → 失败页（`:220-221`）；缺 `code`/`state` → 失败页（`:222-223`）；`complete_authorization` 返回 False（未知/已消费 state）→ “未知回调”失败页（`:224-225`）；成功 → 自关页（`:226`）。返回自包含 HTML 而非 JSON——看页面的是刚点完 Approve 的人（`:212-218`）；`_callback_page` 全部 `html.escape`（`:240,250-251`），成功 200 / 失败 400（`:252`）。
- **没有 owner 绑定**：路由未鉴权，`complete_authorization` 也不查 owner——唯一能力凭证就是 `state` 值本身（高熵、只出现在发起者浏览器收到的 redirect URL 里；键控理由见 `oauth.py:318-322`）。修复卡若给 flow 补 owner 字段（`_PendingFlow.owner_id` 已存在，`oauth.py:309`），须注意 complete 的调用方是匿名回调，不能直接拿 `current_owner_id()` 对比。
- 起流路由 `authorize_server`（`space_mcp.py:169-205`）：404 未配置（`:180-181`）；非 oauth 服务器 400（`:182-186`）；begin 抛任何异常 → 400 `mcp.oauth_start_failed`，文案经 `describe_connect_failure` 展平 ExceptionGroup 并脱敏 URL（`:196-204`；`manager.py:977-999,1011-1030`）；redirect_uri 取“浏览 origin”（`_request_origin` 认 `x-forwarded-proto/host`，`:229-234`），被 `DEEPTUTOR_PUBLIC_URL` 覆盖，再退默认 `localhost:3782`（`oauth.py:218-232`，`CALLBACK_PATH :207`）。注册与 redirect URI 绑定，改 URI 即作废旧注册，`forget` 成对清理（`oauth.py:227-229`）。

## 6. 接点：mcp manager 与网络校验层

- **非交互路径**（`manager.py:836-850`）：`cfg.auth == "oauth"`（字面量定义 `config.py:61`）→ `build_auth` 不带 handlers，consent 请求被拒 → `_connect` 捕获后 `_needs_authorization` 展平 ExceptionGroup 识别 `AuthorizationRequired`（`manager.py:658-669,1033-1055`；测试 `test_oauth.py:233-240`）→ 状态置 `needs_auth`（状态枚举 `manager.py:224`，`status()` 输出 `:392-413`）。**顺序细节**：`_mark_failed`（`:671-677`）先置 `error` 并排了退避，`needs_auth` 只是覆盖 status——因此重试过滤 `status == "error"`（`manager.py:383`）恰好把 needs_auth 排除在外（注释 `:663-668`：不让人工等待被退避循环反复踩）。修复卡改重试逻辑时勿破坏此耦合。
- **网络校验层**（`services/mcp/network.py:75-126` `validate_mcp_url`，async 包装 `:129`）：连接路径在 `_open_transport` 入口校验 URL（`manager.py:805-809`），且每请求经 `network_guard` event hook 重校验/重查私网审批（`:811-832`）；保存时也校验（`user_config.py:186-193`）。**交互 begin 的探测 POST 走裸 `httpx.AsyncClient`（`oauth.py:386`），没有 event hooks、不重跑校验**——只受保存时校验兜底。该请求 URL 来自已保存 config，风险低，但“begin 路径不经过 network_guard”是事实差异，修复卡不要假设两层等价。
- **transport 优先级**：sse 工厂 `auth=oauth_auth or auth`（`manager.py:866-867`，OAuth 覆盖静态凭证）；streamableHttp 直接 `auth=oauth_auth`（`:883`）。follow_redirects 仅非 self-service 为 True（`:834`）。
- **状态面**：`list_servers` 回 `oauth:{name:{required,authorized}}` 只报存在性不回 token（`space_mcp.py:120-126`；`oauth_state :146-151` 永不返回 token）；`remove_server` 级联 `oauth.forget`（`:164`），防止 grant 比配置活得久。

## 7. 已知坑（按修复优先级）

1. **pending 态无 reaper**（§3.4 缺失行）：放弃 consent / 重复 begin 的失败方 → task 永挂 `oauth.py:369`、条目永驻 `:323`；`FLOW_TIMEOUT_S`（`:326`）是死常量。重复 begin 语义上有竞争：两次 begin 各建各的 state 并存（`_PENDING` 无 (owner,server) 去重），且第二次的 `forget`（`:348`）先作废第一次的磁盘 grant——两条流都可能拿到 code，后完成者覆盖存储 token。
2. **complete 无 owner/origin 校验**（§5）：state 即唯一凭证；当前靠 state 熵与不经意泄露保护，修复卡加超时后同时缩小了窗口，但 owner 绑定仍是开放项。
3. **begin 探测绕过 network_guard**（§6）：两层校验不等价，改动 begin 路径时注意。
4. **非交互连接也会产出注册**：`manager.py:849` 用无参 `oauth_redirect_uri()`（默认/ENV），交互 begin 用浏览 origin（`space_mcp.py:194`）；两者注册不同 URI，靠 begin 的 `forget`（`oauth.py:348`）清掉旧注册避免错配——若修复卡改 begin 的 forget 时机，注意此处。

## 8. 可测分支清单（均在当前代码可直接构造）

| # | 分支 | 期望 | 锚点 |
|---|---|---|---|
| T1 | begin：authorize URL 缺 `state` | `url_ready` 置异常、不入 `_PENDING`、begin 抛错、task 被取消 | `oauth.py:357-363,397-401` |
| T2 | begin：探测 POST 网络异常 | 异常进 `url_ready`（`:388-390`），begin 抛错，finally 清扫无残留 | `oauth.py:388-394` |
| T3 | begin：30s 内未产出 URL | `TimeoutError`，`flow.task` 已取消 | `oauth.py:398-401` |
| T4 | begin 成功 | 返回 authorize_url，`_PENDING[state]` 在，`authorize_url` 已记 | `oauth.py:353-366,398` |
| T5 | complete：未知 state / 已消费 state | `False`，无副作用 | `oauth.py:410-412` |
| T6 | complete：命中 | `True`，waiter 收到 `(code, state)` | `oauth.py:413` |
| T7 | 放弃 consent（**待修复**） | 修复后：`FLOW_TIMEOUT_S` 内 task 退出、条目被清扫 | `oauth.py:326,369,391-394` |
| T8 | 同 server 重复 begin | 修复后：旧流被回收；当前：两条并存且旧 grant 已 forget | `oauth.py:348,364` |
| T9 | callback 路由四分支 | error / 缺参 / 未知 state / 成功，页面 200|400 | `space_mcp.py:220-226,252` |
| T10 | authorize 路由：404 / 非 oauth 400 / 起流失败 400 / 成功回 URL | 见各锚点 | `space_mcp.py:180-205` |
| T11 | redirect_uri 优先级：ENV > origin > 默认 | 三段各一测（已有 ENV/origin 两测，默认值分支未测） | `oauth.py:230-232` |
| T12 | `_needs_authorization` 对 `needs_auth` 不进重试 | `manager.py:383` 过滤（现状无直接测试） | `manager.py:658-669,383` |
| T13 | `oauth_state`：无 token / 无 access_token / 正常 | unauthorized / unauthorized / authorized+scope | `oauth.py:148-151` |
| T14 | 不安全服务器名：store 抛错、forget 静默 | `ValueError` / no-op | `oauth.py:92-93,140-143` |
| T15 | 损坏存储文件 | 读作未授权 | `oauth.py:111-115` |

## 9. 现有测试与覆盖空白

**已有**（`tests/services/mcp/test_oauth.py`，15 用例）：存储位置/权限/跨账号隔离 `:46,:60,:68,:76`；不安全名 `:82-87`；state 只报存在性 `:89-97`；损坏文件 `:99-105`；token+注册同文件与刷新不扰注册 `:108-132`；forget 连注册一起删 `:135-153,:156-157`；complete 未知/重放/送达 `:163-195`；非交互拒绝与 `AuthorizationRequired` `:201-230`；`_needs_authorization` 组展平 `:233-240`；redirect URI origin/ENV/单注册 `:246-272`。路由面另有非 OAuth 的 20 个用例（`tests/api/test_space_mcp.py`）。

**空白**（与 §8 对应）：

1. `begin_authorization` 整体无测试：T1-T4 全部缺失（含 30s 超时、无 state、探测异常、清扫）。
2. T7/T8（放弃与重复 begin）无测试——正是修复卡要新增的回归面。
3. authorize / callback 两条路由零测试：T9、T10 全缺（含 `_request_origin` 代理头 `space_mcp.py:229-234`、`mcp.oauth_start_failed` 文案、`remove_server` 级联 forget `:164`）。
4. `FLOW_TIMEOUT_S` 默认分支（无 ENV 无 origin → `localhost:3782`，`oauth.py:231`）未测。
5. manager 侧 “needs_auth 不重试” 的行为链（T12）只有分类函数测试，无状态机级测试。
