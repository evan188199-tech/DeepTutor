# deeptutor/services/subagent/ 代码导读

基线：origin/main `f07029cfc`（v1.6.13）。所有 `path:line` 以该提交为准。
本文只读导读，不涉及任何行为改动；行号为模块内行号，文件路径省略统一前缀 `deeptutor/`。

---

## 0. 这一层是什么

`services/subagent/` 是"子代理驱动层"：把用户本机已安装的 agent CLI（Claude Code、Codex、Grok CLI、Antigravity CLI、Kimi CLI、opencode、MiMo Code、Hermes Agent、OpenClaw、DeepSeek Harness）以及远程网关 / 进程内 Partner，当作 DeepTutor 聊天回合的可咨询对象（`services/subagent/__init__.py:1`）。

该层刻意不知道聊天循环、KB 和 HTTP——这些通过 consult 工具与 API 路由接入（`services/subagent/__init__.py:10-11`）。核心抽象只有一个：`SubagentBackend.detect()` + `SubagentBackend.consult()`（`services/subagent/base.py:34-60`）。

## 1. 模块地图（25 个 py 文件全覆盖）

### 1.1 契约与配置（叶子，被所有人依赖，不反向依赖后端）

| 文件 | 角色 | 入口 |
|---|---|---|
| `services/subagent/types.py` | 跨边界值类型，零内部依赖（`types.py:1-7`） | `SubagentEvent` `types.py:38`、`ConsultResult` `types.py:59`、`DetectResult` `types.py:75`；7 个事件通道 `EVENT_TEXT…EVENT_ERROR` `types.py:17-23` |
| `services/subagent/config.py` | `data/user/settings/subagent.json` 读写 + consult 预算 + 每后端权限开关（`config.py:1-17`） | `BackendConfig` `config.py:38`、`SubagentSettings` `config.py:87`、`load/save_subagent_settings` `config.py:189/202`、`get_consult_budget` `config.py:208` |
| `services/subagent/base.py` | 后端抽象契约 | `OnEvent` 协程回调类型 `base.py:19`（必须 await，保证背压）；`SubagentBackend.detect/consult` `base.py:34-60`；类标志 `kind/display_name/cli_command/local_cli/detectable` `base.py:25-32` |
| `services/subagent/process.py` | 唯一的流式子进程原语（`process.py:1-14`） | `stream_process_lines` `process.py:62`、`probe_version` `process.py:156`、`resolve_cli_command` `process.py:30`、`not_found_detail` `process.py:143`、`truncate_field/compact_field` `process.py:188/196` |
| `services/subagent/sessions.py` | 跨回合会话 id 登记表（`sessions.py:1-12`） | `session_key` `sessions.py:28`、`get_session` `sessions.py:55`、`remember_session` `sessions.py:63`、`forget_connection` `sessions.py:72` |
| `services/subagent/images.py` | 把聊天图片附件落盘成 CLI 可摄取的文件 | `materialize_images` `images.py:32`（仅内联 base64 或本地 AttachmentStore，外部 URL 一律不抓取 `images.py:6-8`） |

依赖方向：`types` ← `base/config` ← 各后端 ← `registry`；`process` 独立于上述（只依赖标准库），被所有 CLI 后端与 `models` 依赖；`sessions/images` 只依赖 `path_service`/`storage`（延迟导入），供 capability 层与工具调用。

### 1.2 注册与装配

| 文件 | 角色 | 入口 |
|---|---|---|
| `services/subagent/registry.py` | "唯一知道有哪些子代理的地方"（`registry.py:1-2`） | `_BACKENDS` 字典 `registry.py:29-44`（11 个实例）；`list_backend_kinds` `registry.py:47`；`get_backend` `registry.py:52`；`detect_all` `registry.py:64`（`asyncio.gather` 并发探测，异常归一为不可用 `registry.py:67-83`） |
| `services/subagent/__init__.py` | 包门面 | 导出契约 + 配置 + `get_backend/detect_all` + `HermesRemoteBackend` + `PARTNER_BACKEND_KIND` `__init__.py:37-57` |

**装配要点**：注册表只装 11 个单例（claude_code、codex、grok、antigravity、kimi、opencode、mimo、hermes、hermes_remote、openclaw、deepseek_harness）。`PartnerBackend`/`PartnerGroupBackend` **不在**注册表里，由工具层按 kind 现场实例化（`capabilities/subagent/tools.py:107-114`）；`detect` 参与面由 `local_cli`/`detectable` 过滤（`registry.py:56-61`）：hermes_remote `local_cli=False, detectable=True`（`hermes_remote.py:50-51`），partner `local_cli=False` 且 `detect()` 恒不可用（`partner.py:59-70`）。

### 1.3 模型目录（/settings 同步源）

| 文件 | 角色 |
|---|---|
| `services/subagent/models.py` | 每后端一个 options provider：`_PROVIDERS` `models.py:398-410`；`list_backend_options` 并发拉全量 `models.py:413`；`sync_backend_options` 是 /settings "同步"按钮入口 `models.py:419-435`。Claude Code 用 `claude_models` 缓存 + 精选别名兜底 `models.py:52-58,156-179`；Codex 读 `$CODEX_HOME/models_cache.json` + `config.toml` 顶层默认模型 `models.py:138-153,182-224`；opencode 家族解析 `<cli> models` 输出（仅取含 `/` 的 slug 行）`models.py:286-314`；Grok/Kimi/Antigravity 无机器可读目录，自由文本 `models.py:234-283`。 |
| `services/subagent/claude_models.py` | 通过 pty 抓取 Claude Code `/model` TUI 来同步模型目录（详见 §3）。 |

### 1.4 CLI 后端（每个吃透一个 CLI 的 headless 协议）

| 文件 | kind / CLI | 流协议 | 会话续接 |
|---|---|---|---|
| `services/subagent/claude_code.py` | `claude_code` / `claude` | `claude -p --output-format stream-json --verbose --include-partial-messages`（`claude_code.py:100-110`），NDJSON 事件流 | `--resume <session_id>` `claude_code.py:115-116`，id 取自事件的 `session_id` 字段 `claude_code.py:189-191` |
| `services/subagent/codex.py` | `codex` / `codex` | `codex exec --json`（JSONL；schema 仍在演化，未知 item 降级为 log，不丢弃 `codex.py:9-13`） | `codex exec resume <id>` `codex.py:89-91` |
| `services/subagent/grok.py` | `grok` / `grok` | `--output-format streaming-json`；`detect` 额外校验 `--help` 含全套 flag，防止同名异装二进制误判 `grok.py:66-78` | `--resume` `grok.py:109-110`；`--no-memory` 防止跨聊天串记忆 `grok.py:99-100` |
| `services/subagent/kimi.py` | `kimi` / `kimi` | `--print --output-format stream-json`，按 `role` 分行（`kimi.py:3-8`） | **自己铸造 uuid**：不存在的 `--session id` 会以该 id 建会话，因此永不解析输出 `kimi.py:18-20,134-137` |
| `services/subagent/antigravity.py` | `antigravity` / `agy` | `-p --output-format stream-json`，事件以 `event` 字段命名、载荷在同名字段（`antigravity.py:9-19`）；空流显式报错并指向上游 antigravity-cli#76 `antigravity.py:84-87,236-239` | `--conversation <id>` `antigravity.py:172-173`，id 在每个事件里都取 `antigravity.py:253-258` |
| `services/subagent/openclaw.py` | `openclaw` / `openclaw` | `agent --json --timeout 0`：stdout 只留最终 Gateway JSON，无流式过程（`openclaw.py:3-6`） | `--session-key dt-<uuid>` 自铸 `openclaw.py:93-94` |
| `services/subagent/deepseek_harness.py` | `deepseek_harness` / `dsh` | 双路径：装了 Python SDK 走线程内 SDK 事件（优先，可续会话）；否则 `dsh --profile headless`（一问一进程、不可续）`deepseek_harness.py:1-7,69-92` | SDK 路径 `session_id=deeptutor-<uuid>` `deepseek_harness.py:177`；headless 恒 `session_id=None` `deepseek_harness.py:105` |
| `services/subagent/hermes.py` | `hermes` / `hermes` | `chat --quiet --query`：stdout 只有最终答案，stderr 尾部 `session_id: <id>`（`hermes.py:1-8`，正则 `hermes.py:34`） | `--resume` `hermes.py:65-66` |
| `services/subagent/opencode_family.py` | `opencode`/`mimo` | 不走子进程 JSON，而走本地 HTTP 服务器 + SSE 总线（详见 §4） | 服务器磁盘存储按 workdir 键控，跨进程存活 `opencode_family.py:15-17` |

共同骨架（除 opencode 家族）：`detect` → `probe_version`；`consult` → `_build_command`（拼 flag，见各自 `_build_command`：`claude_code.py:81`、`codex.py:81`、`grok.py:89`、`kimi.py:90`、`antigravity.py:144`、`openclaw.py:50`、`hermes.py:52`、`deepseek_harness.py:59`）→ `stream_process_lines` 逐行 → `_handle_event` 映射到 7 通道 → 累积 `ConsultResult.final_text`。工具行渲染共用"最显著参数"套路（`_TOOL_PRIMARY_ARGS`：`claude_code.py:53-63`、`kimi.py:63-72`、`antigravity.py:91-100`、`opencode_family.py:72-82`）。

### 1.5 远程 / 进程内后端

| 文件 | 角色 |
|---|---|
| `services/subagent/hermes_remote.py` | 远程 Hermes 网关 `/v1/runs` 驱动：`detect` 先校验配置与 env 密钥名再探测 `/v1/capabilities` 能力契约（5 项必须为 true，`hermes_remote.py:33-41,70-99`）；`consult` 提交 run → 流式消费 SSE → idle 超时（`idle_timeout_seconds`，默认 600s）主动 stop `hermes_remote.py:210-221`；取消时 shield 内补发 stop `hermes_remote.py:226-229,283-291`；**所有 emit 前做密钥脱敏** `hermes_remote.py:133-147,302-318`。注入 `CONSULT_ORIGIN_INSTRUCTION` 防止问题被路由回 DeepTutor `hermes_remote.py:27-30`。 |
| `services/subagent/hermes_remote_client.py` | 该网关的小型 HTTP/SSE 客户端：`validate_base_url` 拒绝带凭据/query/fragment 的 URL `hermes_remote_client.py:52-70`；`stream_events` 解析 data-only SSE，心跳注释行转成内部 `gateway.keepalive` 事件供 watchdog 重置 `hermes_remote_client.py:134-139`；会话历史只留 user/assistant 文本、截尾 40 条 `hermes_remote_client.py:105-121`。异常类型：`HermesRemoteHTTPError`（状态码）/`HermesRemoteProtocolError`（code 字符串）`hermes_remote_client.py:17-31`。 |
| `services/subagent/hermes_remote_events.py` | 网关生命周期 → DeepTutor 通道映射：`message.delta` 累积最终答案（merge_id 恒 `hermes_remote:final`）、`approval.request` 按 `auto_approve` 回 once/deny（失败即停 run）`hermes_remote_events.py:77-91`、`tool.started/completed` 共享 merge id、`reasoning.available`、终端事件 `run.completed/failed/cancelled`。 |
| `services/subagent/partner.py` | 进程内 Partner 后端：经 partner manager 的 web turn 咨询，`session_id` 就是 partner 会话键（首 consult 铸 `dt-<hex>`）`partner.py:112-115`；consult 前重查访问授权 `partner.py:87-95`；先等完用户在侧边栏未完成的 follow-up 再开本轮 `partner.py:141-148`；事件映射 `_to_subagent_events`：CONTENT/THINKING 按 call_id 增量累积，**并行工具的 call 先暂存、随其 result 相邻补发** `partner.py:253-267,280-283`。 |
| `services/subagent/partner_group.py` | 伙伴组桥接：`start_live_turn` + 审批感知的 consultation 窗口轮询（每 0.25s），空闲/讨论状态以 15s 节流 log 上报 `partner_group.py:43-88`；最终文本 = 全体公开消息拼接 + 追问决定清单 `partner_group.py:93-102`；取消时连带取消组内仍在跑的追问任务 `partner_group.py:110-116`。 |

## 2. 关键数据流

### 2.1 聊天回合里的 consult 主链

```
聊天循环
  └─ SubagentCapability.is_active / system_block / augment_kwargs   capabilities/subagent/capability.py:38,46,65
       · 注入 _subagent spec（kind/cwd/budget/config/state/images/session_key）
       · 首轮 consult 从跨回合登记表播种 session_id               capability.py:101-104
  └─ ConsultSubagentTool.execute                                   capabilities/subagent/tools.py:78
       · 预算闸门：state.count >= budget 直接拒绝并要求作答        tools.py:94-102
       · 取后端：partner_group/partner 现场实例化，否则 get_backend tools.py:107-116
       · 图片落盘（forward_images 开启时）                        tools.py:229-249 + images.py:32
       · backend.consult(question, on_event=…)                    tools.py:167
            └─ 事件 → event_sink("subagent_event", …)             tools.py:126-155
                 merge_id 以 consult 轮次为前缀命名空间化          tools.py:149-151
       · 成功后 remember_session（跨回合续接 + 侧边栏共享）        tools.py:186-199 + sessions.py:63
```

预算解析：类型化 per-turn 覆盖 → 设置默认；partner_group 恒为 1（`capability.py:166-180`）；上限 `CONSULT_BUDGET_MAX=12`（`config.py:32-34`）。循环轮数自动留 `budget+2` 余量（`capability.py:29,60`）。

### 2.2 侧边栏直聊（与 consult 共享同一活动会话）

`POST /api/.../subagents/connections/{name}/message`（`api/routers/subagents.py:178-261`）：`get_session` 取回同一 session id → `backend.consult` → NDJSON 逐行输出（merge_id 加 `side:` 前缀 `subagents.py:243`）→ 结束后 `remember_session`。断开连接时 `forget_connection` 清登记（`subagents.py:168-170`）。

### 2.3 探测与设置

- `GET .../subagents/detect` → `detect_all()`（`subagents.py:57-61`、`registry.py:64`）。
- `GET .../subagents/backends/options` → `list_backend_options()`（`subagents.py:64-70`、`models.py:413`）。
- `POST .../subagents/backends/{kind}/sync` → `sync_backend_options(kind)`（`subagents.py:73-88`、`models.py:419`）：claude_code 走 pty 抓取；opencode/mimo 重跑 `models --refresh`；其余仅重读。
- `PUT .../subagents/settings`（admin）合并保存每后端配置（`subagents.py:270-285`）。

连接以 `type: subagent` 的指针 KB 存储，复用 KB 选择/持久化路径，不做任何索引（`subagents.py:1-8`）。

## 3. claude_models：模型目录与 `_capture_model_screen`

Claude Code 没有机器可读的模型列表——`/model` 只存在于交互 TUI 里。同步流程（`claude_models.py`）：

1. `sync_claude_models` `claude_models.py:69-90`：把阻塞抓取丢进 `asyncio.to_thread`；任何失败返回 `([], "")`，旧缓存原样保留。
2. `_capture_model_screen` `claude_models.py:141-229`（POSIX-only，`pyte` 缺失即放弃 `claude_models.py:148-155`）：
   - `pty.fork` 出子进程，`TERM/COLUMNS/LINES=200x60`、`os.chdir` 到临时目录后 `os.execvp("claude", …)` `claude_models.py:159-169`；
   - 父进程 `select` 轮询 fd（总超时 35s `claude_models.py:36`），把字节喂给 pyte 内存终端仿真器，渲染整屏文本 `claude_models.py:175-184`；
   - 三段式驱动，全部靠压缩后的整屏文本匹配（`packed`）：
     ① 看到 "trust this folder" → 回车接受工作区信任 `claude_models.py:187-192`；
     ② composer 就绪（"for shortcuts"/"try edit"/`try"`）→ 敲 `/model` + 回车 `claude_models.py:194-204`；
     ③ 出现 "select model" 后再等 1.2s 画面稳定即快照 `claude_models.py:206-209`；
   - `finally`：Esc + 两次 Ctrl-C、关 fd、SIGTERM、waitpid、删临时目录 `claude_models.py:211-229`。
3. `_parse_model_screen` `claude_models.py:100-138`：从 "select model" 行开始，按编号行正则 `_ROW_RE` `claude_models.py:40` 逐行解析；剥掉选中标记 `✔✓●◉※` `claude_models.py:41,122`；丢弃 disabled/unavailable 行 `claude_models.py:125-126`、recommended/default 行（CLI 默认即 UI 的空选项）`claude_models.py:127-128`；名称归一为 `opus|sonnet|haiku`，含 "1M context" 加 `[1m]` 后缀，去重 `claude_models.py:129-135`。
4. 结果写 `data/user/settings/claude_models_cache.json`（`_write_cache` `claude_models.py:93-97`）；读取方 `load_cached_claude_models` `claude_models.py:48-66`（纯读，不触发抓取）；缓存缺失时 `models._claude_options` 退回精选别名 `models.py:52-58,163-164`。

## 4. opencode 家族：serve+SSE 与 `_swallow`

**架构**：MiMo Code 是 opencode 的源级 fork（同服务器 API、同总线事件），共用 `OpencodeFamilyBackend`（`opencode_family.py:85`），子类只声明 kind/cli/env 前缀/basic-auth 用户（`opencode_family.py:374-387`）。

- **服务器托管** `opencode_server.py`：`acquire_server` 按 `(cli_command, cwd)` 键控，惰性 spawn、跨 consult/回合复用（`opencode_server.py:72-96`）；loopback + 每次随机密码经 `<PREFIX>_SERVER_PASSWORD/_USERNAME` 注入 `opencode_server.py:99-120`；空闲 15 分钟 TTL（按 acquire 时机收割）`opencode_server.py:39,160-168`；atexit 兜底 `opencode_server.py:197-201`；会话存 CLI 自己的磁盘，server 重生后会话仍在 `opencode_server.py:17-18`。
- **一次 consult 的时序** `opencode_family.py:105-194`：`acquire_server` → 建/续 session（`POST /session` `opencode_family.py:196-203`）→ 先挂 SSE 监听再发消息（`_wait_attached` 保证不丢首事件，15s 上限 `opencode_family.py:390-404`）→ **阻塞的 `POST /session/{id}/message` 的返回本身就是回合终点**，其响应 parts 是权威答案 `opencode_family.py:161-169` → 兜底：无最终文本时用总线累积的 text parts 拼接 `opencode_family.py:183-190`。HTTP 读超时为 None（无超时等待语义）`opencode_family.py:68-70`。
- **事件映射** `_handle_bus_event` `opencode_family.py:252-302`：`message.part.updated`（权威累积文本，覆盖 deltas）、`message.part.delta`（token 级打字，merge_id `txt|rsn:<partID>`）、`permission.asked`（按 `auto_approve` 回 once/reject，并记 log `opencode_family.py:350-371`）、`session.error`；tool part 按 state 三态渲染 running/completed/error `opencode_family.py:324-346`。
- **`_swallow` 语义** `opencode_family.py:407-411`：await 一个 awaitable 并吞掉**一切**异常，注释标注 best-effort abort。唯一调用点是 consult 里捕获 `CancelledError` 的分支 `opencode_family.py:163-168`：用户中止回合时，向 `/session/{id}/abort` 发 best-effort 停止——外层 `asyncio.shield` 防止补发的 abort 自己又被取消，`_swallow` 则保证"agent 已死/网络失败"这类噪声不干扰取消路径（异常反正要 re-raise）。同族 best-effort 辅助还有 hermes_remote 的 `_stop_client`/`_stop_after_cancel`（`hermes_remote.py:292-296,283-291`）与 mapper 的 `_stop`（`hermes_remote_events.py:118-122`）。
- 图片以 `file` part（data URL + 真实 mime）随 prompt 体发送，绕开 CLI flag 的 mime 嗅探限制 `opencode_family.py:436-447`。

## 5. 共用原语细节（process.py）

- `stream_process_lines` `process.py:62-121`：stdout/stderr 各一个 pump task 汇入共享 queue，按到达顺序交错产出 `(channel, line)`；**末项恒为 `("exit", "<returncode>")`**。刻意无超时——只有子代理自己退出才结束流（产品契约 `process.py:9-13`）；`finally` 里 `_terminate` 先 terminate 再 5s 后 kill，取消不会留孤儿进程 `process.py:124-140`。
- `resolve_cli_command` `process.py:30-52`：`shutil.which` 全路径解析，专治 Windows 上 npm `.cmd/.ps1` shim 被 `CreateProcess` 无视的问题。
- `probe_version` `process.py:156-180`：带 8s 超时的 `--version` 探测（探测挂起=探测失败，与 consult 的无超时语义刻意不同）。
- `truncate_field`/`compact_field` `process.py:188-202`：4000 字符单行上限（`MAX_FIELD_CHARS` `process.py:185`）。

## 6. 扩展点

1. **新增本地 CLI 后端**：写一个 `SubagentBackend` 子类（实现 `detect`/`_build_command`/`_handle_event`）→ 在 `registry._BACKENDS` 追加实例（`registry.py:29-44`）→ 如需 /settings 模型目录，在 `models._PROVIDERS` 加 provider（`models.py:398-410`）。API/UI 均经注册表自动发现。
2. **新增远程后端**：`local_cli=False, detectable=True`（参照 `hermes_remote.py:50-51`）；`detect` 返回结构化 detail code。
3. **Partner 族**：不进注册表；在 `tools.py:107-114` 按 kind 现场实例化；`subagents.py:123` 拒绝通过连接 API 创建 partner 连接。
4. **模型目录来源**：能枚举就给 provider（Codex 缓存 / opencode `models`）；不能就 `models=[], allow_custom_model=True`（Grok/Kimi，`models.py:255-283`）。

## 7. 测试覆盖与相邻文件

- 后端行为/事件映射：`tests/services/test_subagent_backends.py`（claude_code、codex、grok、kimi、opencode、openclaw、deepseek、hermes、partner、`_parse_model_screen`、opencode_server 等）。
- 单独成套：`tests/services/test_antigravity_backend.py`、`tests/services/test_grok_backend.py`、`tests/services/test_hermes_remote_backend.py`、`tests/services/test_hermes_remote_backend_lifecycle.py`。
- 上层：`tests/capabilities/test_subagent_capability.py`（预算/播种）、`tests/api/test_subagents_router.py`、`tests/api/test_partners_router.py`。
- 相邻模块（本层依赖其反向接口，不在本导读范围）：`deeptutor/capabilities/subagent/{binding,capability,tools}.py`、`deeptutor/api/routers/subagents.py`、`deeptutor/api/routers/partners.py:650`（侧边栏 partner 直聊同样读写 sessions 登记表）。

## 8. 速查：常见修复入口

| 症状 | 先看 |
|---|---|
| 某后端探测失败但 CLI 在 PATH 上 | `probe_version` + 该后端 `detect`（grok 有 flag 白名单校验 `grok.py:66-78`；Windows shim 看 `resolve_cli_command` `process.py:30`） |
| 答案没打字/打字重复 | merge_id 累积逻辑：claude `stream_event` `claude_code.py:252-289`；codex `.updated` `codex.py:185-198`；opencode delta/updated 双写 `opencode_family.py:264-321` |
| 会话不续接/串会话 | `sessions.py` 登记 + capability 播种 `capability.py:101-104` + 各后端 `_build_command` 的 resume flag；kimi/openclaw 自铸 id |
| 回合挂死/进程残留 | consult 均为无条件等待；检查 `_terminate` `process.py:124` 与 opencode_server TTL `opencode_server.py:160`；opencode 家族中止路径 `opencode_family.py:163-168` |
| Claude Code 模型目录为空/过期 | `claude_models` 抓取失败链路（§3），缓存 `claude_models_cache.json`；POSIX/pyte 前置条件 `claude_models.py:148-155` |
| 密钥出现在侧边栏流里 | hermes_remote 脱敏管线 `hermes_remote.py:133-147,302-318`（emit 前替换） |
