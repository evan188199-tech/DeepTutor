# deeptutor/partners 模块导读（通道 / 总线 / 配置）

> 基线：origin/main @ `ef2d9e5c3`（v1.6.12，2026-10-03 fetch）。所有行号锚点对应该提交。
> 本导读只读代码，不修改任何产品代码。

## 1. 模块地图

`deeptutor/partners/` 是 IM 通道接入层（自 nanobot 移植改造），只负责"收消息 / 发消息"；大脑（chat agent loop）和配置管理在服务层 `deeptutor/services/partners/`。

```
deeptutor/partners/
├── bus/                  消息总线（进程内 asyncio 队列对）
│   ├── events.py         InboundMessage / OutboundMessage 数据类
│   └── queue.py          MessageBus：inbound + outbound 两条 asyncio.Queue
├── channels/             通道实现（17 个平台 + 公共骨架）
│   ├── base.py           BaseChannel 抽象基类 + deliver_outbound 投递契约
│   ├── manager.py        ChannelManager：通道生命周期 + 出站路由/重试/去重/流式合并
│   ├── registry.py       pkgutil 扫描 + entry_points 插件发现
│   ├── telegram.py       Telegram（long polling）
│   ├── feishu.py         飞书/Lark（WebSocket 长连接）
│   └── discord.py / slack.py / email.py / wecom.py / weixin.py / qq.py / …
├── config/
│   ├── schema.py         ChannelsConfig / DeliveryOverrides / StreamingSupport（Pydantic）
│   └── paths.py          data/partners/ 数据树布局（per-partner 隔离）
├── helpers.py            split_message 分片、Markdown 表格转行、safe_filename 等
├── network.py            SSRF 防护 validate_url_target（比 MCP 层更严，封全部内网段）
└── transcription.py      GroqTranscriptionProvider（Whisper-large-v3 语音转写）

配套服务层（partners 的"宿主"，不属于本包但必须一起看）：
deeptutor/services/partners/
├── manager.py            PartnerManager：Partner 实例编排、PartnerConfig、装配 bus+runner+channels
├── runtime.py            PartnerRunner：消费 inbound、跑 agent loop、发布 outbound
├── model_runtime.py      per-partner LLM 选择解析（resolve_llm_config_for_selection）
├── commands.py           运行时斜杠命令（含 /model 切换模型）
└── drafts.py / sessions.py / interaction.py / …
```

关键入口文件速查：

| 入口 | 位置 | 作用 |
|---|---|---|
| 通道基类 | `deeptutor/partners/channels/base.py:38` | start/stop/send 抽象、`_handle_message` 准入 |
| 通道发现 | `deeptutor/partners/channels/registry.py:73` | 内置 pkgutil 扫描 + `deeptutor.partners.channels` entry_points 插件，内置优先 |
| 出站路由 | `deeptutor/partners/channels/manager.py:247` | `_dispatch_outbound` 循环 |
| Partner 装配 | `deeptutor/services/partners/manager.py:680-734` | bus → runner → channel_manager 三件套 + 任务编排 |
| 消费循环 | `deeptutor/services/partners/runtime.py:153` | `PartnerRunner.run()` |

## 2. 消息流转（收发全路径）

### 2.1 收（channel → bus）

1. 平台 SDK 回调/轮询进入各通道的 `_on_message`（如 Telegram `deeptutor/partners/channels/telegram.py:903`、飞书 `deeptutor/partners/channels/feishu.py:2020`）。
2. 通道做平台侧过滤与解析：群聊 @ 提及判定、allowlist、媒体下载、语音转写、（Telegram）media group 聚合 / reply 上下文 / 话题 session_key。
3. 统一调用 `BaseChannel._handle_message`（`deeptutor/partners/channels/base.py:203`）：
   - `is_allowed` 准入（`base.py:193`）：allowFrom 为空 → 全部拒绝；`"*"` → 全放行；
   - 若通道支持流式且开启 `send_progress`，给 metadata 打 `_wants_stream`（`base.py:235-239`）；
   - 组装 `InboundMessage`（`bus/events.py:11`，session_key 默认 `channel:chat_id`，可被话题级 override 覆盖，`events.py:27-29`）并 `bus.publish_inbound`（`base.py:251`）。

### 2.2 处理（bus → PartnerRunner → agent loop）

- `PartnerRunner.run()`（`deeptutor/services/partners/runtime.py:153`）阻塞消费 `bus.consume_inbound()`，每条消息起独立 task（`runtime.py:158`），按 session 加锁串行（`runtime.py:148` `_session_locks`）。
- `_handle_inbound`（`runtime.py:169`）先镜像 user_echo/activity 帧到 WebUI 活动流（`_emit_channel_activity`，`runtime.py:251`），再进入 `process_message`（chat agent loop，异常兜底为致歉文案 `runtime.py:210-214`）。
- 过程中的三类出站（`runtime.py`）：
  - 进度/工具提示：`_publish_hint`（`runtime.py:1081`，metadata `_progress` / `_tool_hint`）；
  - 流式片段：`_publish_stream_delta`（`runtime.py:1091`，`_stream_delta` + `_stream_id`）与 `_publish_stream_end`（`runtime.py:1107`，`_stream_end`，可选 `_stream_final`）；
  - 最终回复：`_handle_inbound` 末尾 `bus.publish_outbound`（`runtime.py:242`）。

### 2.3 发（bus → channel）

1. 出站路由双实现：
   - WebUI 侧 `PartnerManager._outbound_router`（任务名 `partner:{id}:router`，装配于 `services/partners/manager.py:721`）；
   - IM 侧 `ChannelManager._dispatch_outbound`（`deeptutor/partners/channels/manager.py:247`），`start_all` 时启动（`manager.py:187`）。
2. `ChannelManager` 出站管道（`manager.py:255-292`）依次做：
   - `_progress` 帧按每通道开关过滤：工具提示看 `send_tool_hints`、普通进度看 `send_progress`（`manager.py:267-271`）；
   - 连续 `_stream_delta` 合并（`_coalesce_stream_deltas`，`manager.py:304`，按 `(channel, chat_id, _stream_id)` 同段拼接，遇非同类消息即断）；
   - 精确重复抑制（`_should_suppress_outbound`，`manager.py:220`，按 origin message id + 内容 SHA1 指纹）；
   - 指数退避重试 `_send_with_retry`（`manager.py:353`，延迟 1s/2s/4s，次数 `ChannelsConfig.send_max_retries` 默认 3，`config/schema.py:50`）。
3. 统一投递契约 `deliver_outbound`（`base.py:264`）：`_stream_delta/_stream_end` → `send_delta`；`_streamed` 且通道确认未送达 → 回退普通 `send`；否则 `send`。实现抛异常即触发上层重试。
4. 状态回传：各通道通过 `set_setup_state`（`base.py:74`）发布连接/错误状态（不带凭据），`ChannelManager.get_status`（`manager.py:389`）汇总给 WebUI。

一句话总结：**channel `_on_message` → `_handle_message` → inbound 队列 → PartnerRunner（agent loop）→ outbound 队列 → `_dispatch_outbound`（过滤/合并/去重/重试）→ `deliver_outbound` → `send`/`send_delta`**。

## 3. 模型与推理强度配置链路（settings draft `extensions.subagent:*`）

这条链路涉及"伙伴与智能体 → CLI 应用"设置页（Claude Code / Codex / opencode / grok 等 consult 后端）的 **per-app `model` / `effort`**。上游 issue #1630 报告该配置"存不上"，背景如下。

### 3.1 链路各站（当前 origin/main 状态）

1. **UI 暂存**：`web/components/settings/SubagentSettingsEditor.tsx:324`（编辑器），`:333` 用 `useStagedSettings("subagent:<kind>", …)` 把修改注册进全局 settings store 的扩展段（`web/features/settings/store/useStagedSettings.ts:13`）。每个 CLI 应用页签对应 `web/components/settings/SettingsPageContent.tsx:202-214` 的 `AGENTS` 映射（`agent-opencode` → kind `opencode` 等）。
2. **草稿信封**：`deeptutor/services/config/settings_draft.py:43` 定义信封 `{version, updated_at, catalog, extensions}`；`extensions` 按"页面注册 key"存不透明 payload（设计意图见文件头注释 `settings_draft.py:1-23`）。落盘为 per-user 的 `settings_draft.json`（`save()` `settings_draft.py:85`，`clear()` `:109`）。`subagent:opencode` 就出现在 `extensions["subagent:opencode"]`。
3. **应用（关键补偿点）**：前端 `applyCatalog`（`web/features/settings/store/SettingsStore.tsx:1725`）先 `PUT /api/settings/draft` 把屏上状态落到服务端（`:1745`），随后**逐个 extension** 处理（`:1757-1762`）：页面仍挂载且 dirty 走其 `save()`，否则走 `applyExtensionPayload`。`web/lib/settings-extensions.ts:52-56` 对 `subagent:*` key 的分支——把 payload 转成 `PUT /api/subagents/settings` 的 `backends: {<kind>: payload}`。**这一步是 `extensions` 段唯一的消费出口；服务端 `POST /api/settings/apply` 本身不消费 extensions**（见 3.3）。
4. **API 合入**：`deeptutor/api/routers/subagents.py:270` `update_settings`（admin 门禁），`backends` 按 kind、按字段合并（`:276-282`），不会互相覆盖。
5. **持久层**：`deeptutor/services/subagent/config.py:202` `save_subagent_settings` → `data/user/settings/subagent.json`；读取 `load_subagent_settings`（`:189`），坏文件回退默认值。`BackendConfig.model / .effort`（`config.py:44-45`，空 = 用后端自身默认），另有 permission_mode/sandbox/approval/extra_args 等运行开关（`:54-77`）。
6. **运行时消费**（配置真正生效处）：
   - Claude Code：`deeptutor/services/subagent/claude_code.py:119-122` → `--model` / `--effort`；
   - Grok CLI：`deeptutor/services/subagent/grok.py:103-106` → `--model` / `--reasoning-effort`；
   - Hermes remote：`deeptutor/services/subagent/hermes_remote.py:193-196` → 请求体 `model` / `model_options.reasoning_effort`；
   - Codex：`-m` / `-c model_reasoning_effort`（注释锚 `services/subagent/config.py:42-43`）。

生命周期一句话：**页签编辑 → `extensions["subagent:<kind>"]` 进 settings_draft.json → 前端 Apply 循环转 `PUT /api/subagents/settings` → 按 kind 字段级合并进 subagent.json → 各 CLI runner 启动 consult 时读取**。

### 3.2 伙伴（Partner）侧的模型选择（对照链路）

IM 伙伴本体不走 subagent.json：`PartnerConfig.llm_selection / model / backup_llm_selection`（`deeptutor/services/partners/manager.py:254-257`），解析在 `deeptutor/services/partners/model_runtime.py`（`resolve_llm_config_for_selection`，model-only 覆盖叠加系统默认 provider），运行时可用 `/model` 命令切换（`deeptutor/services/partners/commands.py`）。#1630 的"伙伴与智能体 CLI 应用"特指前者（consult 后端），两者不要混淆。

### 3.3 #1630 背景、现状与排查点

- **报告**（v1.6.12，仍 OPEN）：Settings → 伙伴与智能体 → CLI 应用页改 model/effort → 应用更改 → 配置丢失。其根因分析：`POST /api/settings/apply`（`deeptutor/api/routers/settings.py:1869`）确实**只处理 catalog 段**且 `:1895` 无条件 `draft_service.clear()` 清空整个草稿——`extensions` 段在服务端路径上从未被消费；能持久化后端配置的接口只有 `PUT /api/subagents/settings`。
- **源码现状**：前端 `subagent:*` 桥接分支自 v1.6.9（commit `da856ad67`，2026-09-21）即存在，早于报告版本 v1.6.12；origin/main 与 v1.6.12 tag 一致，其后无修复提交。即：**补偿机制在源码里，但 issue 仍 OPEN**——是前端桥接在某些路径未触发（如 mounted/dirty 判定、`pendingRef` 空、apply 循环中途抛错中断），还是报告环境差异，需要在本地实例实测二分。
- **关联 PR 检查**：上游无针对 #1630 的修复 PR（#1272 ACP client、#1360 Grok connector、#1208 Hermes remote 均为后端连接器，不是本 bug）。
- **排查路径**：改完点应用后依次看 ① `data/user/settings/settings_draft.json` 的 `extensions` 是否写入；② 浏览器 Network 里 Apply 时是否发出 `PUT /api/subagents/settings`（body `backends`）；③ `data/user/settings/subagent.json` 的 `backends.<kind>.model/effort` 是否落盘；④ `GET /api/subagents/settings` 是否回读成功。断在哪一站即问题所在。

## 4. Telegram / 飞书通道接入点

### 4.1 Telegram（`deeptutor/partners/channels/telegram.py`，1067 行）

- 配置模型 `TelegramConfig`（`:195`，继承 `DeliveryOverrides`/`StreamingSupport`，token/proxy/连接池/`reply_to_message` 等）。
- **收**：`start()`（`:270`）long polling；双 HTTPX 连接池隔离轮询与发送（`:287-303`，防止 getUpdates 饿死发送）；handlers 注册 `:314-330`（/start、/help + 文本/图片/语音/文档）。`_on_message`（`:903`）：
  - 群组仅响应 @bot（`:917` `_is_group_message_for_bot`）；
  - 媒体下载 + reply 引用上下文回填（`:931-951`）；
  - **media group 聚合**：同组消息缓冲 2s 合并为一轮（`:961-979`，`_flush_media_group` `:994`）；
  - 话题线程 → `session_key` override（`_derive_topic_session_key` `:742`），同一论坛话题各自成会话；
  - 收尾统一走 `_handle_message`（`:985`）。语音经 `transcribe_audio`（`base.py:124`，Groq Whisper）转写。
- **发**：`send()`（`:393`）：先按 media 类型分发 send_photo/voice/audio/document（`:424-448`）；文本按 `TELEGRAM_MAX_MESSAGE_LEN` 分片（`split_message`，`helpers.py:42`，优先换行断开）；最终回复用 `_send_with_streaming`（`:495`，草稿模拟打字机后固化），进度帧走 `_send_text`（`:467`）。topic 回帖参数 `message_thread_id` 从缓存恢复（`:409-414`）。
- **流式**：`send_delta`（`:562`）原地编辑同一条消息；超长溢出转新消息（`_flush_stream_overflow` `:679`）。

### 4.2 飞书 / Lark（`deeptutor/partners/channels/feishu.py`，2146 行）

- 配置模型 `FeishuConfig`（`:291`，app_id/app_secret/encrypt_key/verification_token/domain=feishu|lark/react_emoji 等）。
- **收**：`start()`（`:406`）用 lark-oapi **WebSocket 长连接**（无需公网回调）：
  - 事件注册 `:445-462`：`p2_im_message_receive_v1`（必）+ reaction/message_read/p2p_chat_entered/card_action（可选，SDK 版本兼容经 `_register_optional_event` `:401`）；
  - `_card_aware_ws_client`（`:32-40`）修补 SDK 丢弃 CARD 帧的问题，让卡片按钮回调可达；
  - WS 跑在**独立线程 + 独立事件循环**（`:483-514`，规避 SDK 模块级 loop 与主循环冲突），断线 5s 重连；
  - `_on_message`（`:2020`）：message_id 去重环形缓存（`:2028-2035`）→ 跳过 bot → 群聊须 @bot（`:2046`）→ allowlist（`:2049`）→ 按 msg_type 解析（text/post/image/audio/file/media/interactive/share_*，`:2061-2107`），audio 下载后转写（`:2086-2089`）→ 加 👍 reaction 回执（`:2116`，仅当消息能到达 runner）→ `_handle_message`（`:2120`；**群聊 chat_id 用群 id，P2P 用 sender open_id**，`:2119`）。
- **发**：`send()`（`:1809`）：按内容自动选 post/卡片/markdown（`_detect_msg_format` `:877`），Markdown 表格转卡片元素并按限制拆分（`_build_card_elements` `:761` / `_split_elements_by_table_limit` `:778`），图片/文件先上传拿 key（`:975`/`:1002`）。
- **流式**：`send_delta`（`:1348`）走**可更新卡片**：`_create_streaming_card_sync`（`:1226`）建卡 → `_stream_update_text_sync`（`:1277`）按 sequence 刷文本 → `_close_streaming_mode_sync`（`:1311`）收尾；`consume_stream_delivery`（`:392`）向 `deliver_outbound` 回报流式终稿是否已送达（未送达则回退普通 send，`base.py:269-274`）。
- **互动彩蛋**：卡片按钮选模型（`_queue_model_choice` `:1660`、`_on_card_action_sync` `:1685`，模型选择器卡片 `_model_picker_card` `:1528`）——飞书端可不动键盘切 `/model`。

## 5. 常见排查点

| 症状 | 先看哪里 |
|---|---|
| 通道压根没启动 | `manager.py:60-119`：config 段 `enabled` 是否为 true；`allowFrom` 为空会被跳过（`:102-111`，setup 状态 `action_required`） |
| 私聊无响应（群聊正常） | `base.py:193-201`：allowFrom 空 → 一律拒绝；`"*"` 放行；sender_id 需精确匹配 |
| 通道在 UI 显示 unavailable | `registry.py:88-90`：可选依赖（如 lark-oapi）未安装，import 错误被记录并在 `get_status` 暴露 |
| 回复发不出/发两次 | 重试 3 次失败（`manager.py:353-384`）；重复回复被 `_should_suppress_outbound` 抑制（`:220`），误抑制查 origin_message_id 指纹 |
| 流式不生效 | `send_progress` 关闭时回退缓冲投递（`base.py:235-239`）；通道未实现 `send_delta` 或 `streaming` 未开（`base.py:182-191`） |
| 两个 Partner 互相串 token | 通道状态目录按 `data/partners/<id>/channels/<name>` 隔离（`base.py:109-122`、`config/paths.py:57-63`），共享旧目录可查 `_rehome_shared_channel_state` |
| 媒体 URL 拒绝下载 | `network.py:59` `validate_url_target`：外部 IM URL 一律禁内网/环回（`:17-28` 封禁段），防 SSRF |
| 语音没转写 | `base.py:124-135`：`transcription_api_key` 未注入（manager init 时赋值 `manager.py:93`）或 Groq 调用失败静默返回空串 |
| CLI 应用 model/effort 存不上（#1630） | 按 §3.3 四步定位：settings_draft.json extensions → PUT /api/subagents/settings → subagent.json backends → GET 回读 |
| 出站卡死看不到日志 | `_dispatch_outbound` 1s 轮询超时循环（`manager.py:260`），查 `Unknown channel` 警告——出站 channel 名必须与已启用通道 name 一致 |

## 6. 验证

```bash
# 通道公共工具层测试（本 worktree，使用 /Users/Shared/DeepTutor/.venv）
python -m pytest tests/partners -q
# → 12 passed in 0.45s

# subagent 设置链路 API 测试（§3 链路的服务端）
python -m pytest tests/api/test_subagents_router.py -q
# → 12 passed in 0.41s
```

前端桥接分支的既有用例：`web/tests/subagent-grok-settings.spec.tsx`（断言暂存 payload 形如 `subagent:grok`）、`web/tests/settings-unified-draft.spec.tsx`。
