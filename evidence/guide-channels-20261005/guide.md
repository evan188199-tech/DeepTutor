# partners 通道层代码导读（feishu / telegram / napcat / zulip / matrix / mochat / qq / email）

- 基线：`origin/main` @ `f07029cfc`（release v1.6.13），只读分析，未改任何代码。
- 范围：`deeptutor/partners/channels/` 的公共接口、生命周期、八个指定通道的连接模型与消息进出路径、stop/logout 语义，以及新增通道清单。
- 文中引用一律为 `path:line`（相对仓库根目录）。

## 1. 分层总览

通道层自上而下分四层，职责边界清晰：

| 层 | 位置 | 职责 |
|---|---|---|
| Partner 生命周期 | `deeptutor/services/partners/manager.py:894`（stop_partner）、`:955`（reload_channels） | 创建/销毁 `ChannelManager`，管理 `partner:{id}:ch:*` 任务 |
| 调度层 | `deeptutor/partners/channels/manager.py:193`（ChannelManager） | 按配置实例化通道、启动监听、串行派发 outbound（重试/去重/合并） |
| 通道实现 | `deeptutor/partners/channels/base.py:38`（BaseChannel）+ 各 `*.py` | 平台连接、收发消息、媒体下载/上传 |
| 消息总线 | `deeptutor/partners/bus/queue.py:9`（MessageBus）、`deeptutor/partners/bus/events.py:10,32` | 两条 `asyncio.Queue`（inbound/outbound）解耦通道与 PartnerRunner |

一个 Partner 一个 `MessageBus` 与一个 `ChannelManager`（`deeptutor/services/partners/manager.py:723-733`）；启动时为 runner、outbound 路由和每个通道各建一个 task，通道 task 命名为 `partner:{partner_id}:ch:{channel}`（`deeptutor/services/partners/manager.py:737-748`）。

## 2. 公共接口（BaseChannel）

`deeptutor/partners/channels/base.py:38` 定义的抽象基类是所有通道的唯一契约：

- 类属性：`name` / `display_name`（`base.py:46-47`）、`send_progress` / `send_tool_hints`（投递开关，由 manager 从配置解析后写入，`base.py:49-52`）、`partner_id`（`base.py:53`）。
- 构造：`__init__(config, bus)` 记录 config/bus、置 `_running=False`，并从 ContextVar `constructing_for` 读取归属 partner（`base.py:55-72`；ContextVar 定义 `base.py:14-29`）。这样通道在 `__init__` 里就能解析 per-partner 路径，而无需把 partner_id 传入每个子类签名。
- 抽象方法：
  - `start()`：长驻监听，连接平台并把入站消息转给 `_handle_message`（`base.py:137-147`）。
  - `stop()`：清理资源（`base.py:149-152`）。
   - `send(msg)`：投递一条 `OutboundMessage`；**契约是失败必须 raise**，由 manager 统一重试（`base.py:162-163`）。
- 可选覆写：
  - `send_delta(chat_id, delta, metadata)`：流式增量投递（`base.py:167-180`）；`supports_streaming` 在「配置开了 streaming 且子类真的覆写了 send_delta」时为真（`base.py:182-191`）。
  - `default_config()`：onboarding 默认配置（`base.py:253-256`）。
- 通用能力：
  - `is_allowed(sender_id)`：allowlist 校验；空列表拒绝所有人，`"*"` 放行所有人（`base.py:193-201`）。
  - `_handle_message(...)`：入站统一入口——先 ACL（`:225-232`），再按需注入 `_wants_stream`（`:235-239`），构造 `InboundMessage` 发布到 bus（`:241-251`）。**任何通道不得绕过它直接 publish。**
  - `media_dir()` / `state_dir()`：per-partner 隔离的媒体与状态目录；独立构造（插件/测试）回退 legacy 路径（`base.py:99-122`）。
  - `transcribe_audio()`：语音转写（Groq），失败返回空串（`base.py:124-135`）。
  - `set_setup_state()` / `setup_state` / `setup_revision`：向 WebUI 发布非敏感的连接状态（`base.py:74-97`）。
- 出站投递契约 `deliver_outbound()`（`base.py:264-276`）：按 metadata 分派 `_stream_delta`/`_stream_end` → `send_delta`；`_streamed` 且通道未能确认最终卡片送达（`consume_stream_delivery` 返回 False）时补一次普通 `send`；否则走 `send`。

配置模型（`deeptutor/partners/config/schema.py`）：`Base` 同时接受 camelCase/snake_case（`:9-12`）；`DeliveryOverrides` 提供 `send_progress`/`send_tool_hints`（`:15-25`）；`StreamingSupport` 提供 `streaming`（`:28-37`）；`ChannelsConfig` 是 extra=allow 的容器，每个通道在自身 `__init__` 里用各自的 Config 模型解析 dict（`:40-50`；例如 `telegram.py:298-302`）。

## 3. 生命周期

### 3.1 发现与实例化

- 注册表不手工登记通道：`discover_channel_names()` 用 pkgutil 扫包（排除 `base/manager/registry`，`deeptutor/partners/channels/registry.py:14,27-35`），`load_channel_class()` import 模块并取第一个 `BaseChannel` 子类（`registry.py:38-47`）。
- 模块 import 失败（典型为缺可选依赖）记入 errors，UI 可见（`registry.py:73-97`）；模块能 import 但没有通道子类则视为 helper，直接跳过（`NotAChannelModule`，`registry.py:17-24,86-87`）。
- 外部插件经 entry_points `group="deeptutor.partners.channels"` 注册，内置同名优先（`registry.py:50-70`）。
- `ChannelManager._init_channels`（`deeptutor/partners/channels/manager.py:222-281`）遍历配置里 `enabled: true` 的 section，在 `constructing_for(partner_id)` 上下文里实例化（`:252-254`），解析投递开关（`:258-263`），`allow_from` 为空则拒绝启用并标 `action_required`（`:264-273`），构造异常记 `error`（`:276-281`）。

### 3.2 启动

- `start_all()` 先起 outbound 派发 task，再为每个通道建 `_start_channel` task 并 gather（`manager.py:343-356`）。Partner 正常启动也走同一条路（`deeptutor/services/partners/manager.py:743-748`）。
- `_start_channel`（`manager.py:301-341`）：置 `connecting` → `create_task(channel.start())` → 若通道未发布更细状态则标 `running` → `await start_task`（start 返回即监听循环退出）→ 异常时置 `error` 并复位 `_running`。

### 3.3 Outbound 派发

`_dispatch_outbound`（`manager.py:409-459`）是唯一出口，单循环串行处理：

1. 1s 超时轮询 bus（`:422`）；未知通道丢弃并告警（`:424-427`）。
2. 进度类消息按通道开关过滤（`_progress` + `_tool_hint`，`:429-433`）。
3. 连续 `_stream_delta`（同 channel+chat_id+`_stream_id`）合并为一帧，减少编辑类 API 调用（`coalesce_stream_deltas`，`manager.py:46-100`，调用点 `:438-440`）。
4. 非流式消息做重复抑制：以 `origin_message_id`/`message_id` + 内容指纹（sha1）判重（`:382-407`）。
5. `send_with_retry` 指数退避重试（1s/2s/4s，次数取 `channels.send_max_retries`，`manager.py:23,155-190,471-480`）；`CancelledError` 直接上抛保证优雅停机。

Partner 级路由（进程内 Web/多 partner 场景）复用同一套合并语义（`deeptutor/services/partners/manager.py:774,796` 调用 `coalesce_progress_messages`，定义在 `deeptutor/partners/channels/manager.py:103-152`）。

### 3.4 停止

- `ChannelManager.stop_all()`（`manager.py:358-373`）：先取消派发 task，再逐个 `await channel.stop()`，成功后置 `disconnected`；单个通道 stop 抛异常只记日志，不影响其余通道。
- Partner 停止：先 cancel 所有 `partner:{id}:*` task（含通道监听）再 `channel_manager.stop_all()`（`deeptutor/services/partners/manager.py:894-922`）。
- 通道热重载 `reload_channels`：只取消 `partner:{id}:ch:*` 前缀的监听 task（`_teardown_channel_listeners`，`deeptutor/services/partners/manager.py:1007-1033`），runner/router 不动；随后重建 `ChannelManager` 并重启各通道 task（`:955-1005`）。**这就是「stop 必须幂等、不能泄漏监听」的根因**：reload 会反复调用同一通道类的 stop/start。

## 4. 通道对照表

| 模块 | name / display | 入站连接模型 | 出站 API | 群聊策略 | 入站去重 | 流式 | 关键 stop 资源 |
|---|---|---|---|---|---|---|---|
| `feishu.py` | feishu / Feishu | lark-oapi WebSocket 长连接（独立线程+独立 loop） | REST（send/reply/cardkit） | `open`/`mention`（`feishu.py:322`） | OrderedDict 1000 条（`feishu.py:442,2341-2348`） | CardKit 流式卡片（`feishu.py:1615`） | WS 线程+SDK 任务取消（`:638-675`） |
| `telegram.py` | telegram / Telegram | python-telegram-bot 长轮询 | Bot API（send/edit） | `open`/`mention` + per-chat 覆盖（`telegram.py:261-265`） | 依赖 drop_pending_updates + 群策略 | 消息原地编辑（`telegram.py:624`） | updater/app 停止三段式（`:423-441`） |
| `napcat.py` | napcat / QQ (NapCat) | OneBot v11 WebSocket 客户端 | WS action `send_msg` | `mention`/`open`/概率 p + 按群覆盖（`napcat.py:41,54,368-379`） | deque 2000（`napcat.py:80`） | 无（无 send_delta） | WS+HTTP client+后台任务（`:167-187`） |
| `zulip.py` | zulip / Zulip | 官方 SDK event queue，**独立守护线程**轮询 get_events | REST messages/user_uploads | `mention`/`open`（`zulip.py:59`） | `_max_message_id` + deque 5000（`zulip.py:83-84,406-415`） | 无 | 注销事件队列+join 线程（`:164-182`） |
| `matrix.py` | matrix / Matrix | matrix-nio `sync_forever` 长轮询（asyncio task） | room_send + upload（可选 E2EE） | `open`/`mention`/`allowlist`（`matrix.py:199`） | 依赖 sync token/store | 无 | `stop_sync_forever`+宽限期+close（`:277-296`） |
| `mochat.py` | mochat / Mochat | Socket.IO 订阅，断线降级 HTTP watch/poll worker | HTTP `sessions/send`/`panels/send` | panel 群可要求 mention（`mochat.py:189-195,809-818`） | per-target seen 集合 2000（`mochat.py:36,844-853`） | 无 | socket/HTTP/游标落盘/worker（`:347-372`） |
| `qq.py` | qq / QQ | qq-botpy WebSocket（官方机器人） | Bot API group/c2c post | C2C+群 @ 消息（SDK intents） | deque 1000（`qq.py:81`） | 无 | `client.close()`（`:128-136`） |
| `email.py` | email / Email | IMAP UNSEEN 轮询（`asyncio.to_thread`，默认 30s） | SMTP | 不适用（以发件人为 chat） | `\Seen` 标记 + UID 集合上限 10 万（`email.py:95-96,321-370`） | 无 | 无长连接——stop 仅置位（`:154-156`）；IMAP 会话每次轮询即开即关（`:374-378`） |

目录内其余通道（本次不展开，模型同上表套路）：dingtalk/discord/mattermost/msteams/slack/wecom/weixin/weixin_qr/whatsapp/lark_http（feishu 的 HTTP keep-alive 补丁，`lark_http.py:24`）。

## 5. 各通道要点

### 5.1 feishu（`deeptutor/partners/channels/feishu.py`）

- 连接：`start()` 检查 SDK 与 app 凭据（`:482-499`），安装 HTTP keep-alive 传输（`:509-513`），构造 `lark.Client`（发消息）与事件分发器（`register_p2_im_message_receive_v1` 等，`:530-548`）。WS 客户端被 `_card_aware_ws_client` 子类化以补上 SDK 丢弃 CARD 帧的问题（`:32-76,553-566`）。
- 线程模型：WS 跑在**独立线程 + 独立 event loop**（SDK 的模块级 loop 会被 patch，`:573-611`），回调 `_on_message_sync` 用 `run_coroutine_threadsafe` 切回主 loop（`:2325-2331`）。
- 入站路径：去重（`:2341-2348`）→ 跳过 bot（`:2350-2352`）→ 群聊 mention 策略（`:694-698,2359-2361`）→ ACL（`:2362-2363`）→ 按 msg_type 解析文本/富文本/媒体并下载到 `media_dir`（`:2374-2404,1231-1271`；语音自动转写 `:2399-2402`）→ 给源消息加 👍 反应作为「收到」回执（`:2429,831-855`）→ `_handle_message`（`:2433-2443`）。群聊 `chat_id=oc_*`，私聊 `chat_id=open_id`（`:2432,1273-1276`）。
- 出站路径：`send()`（`:2115-2323`）先处理「思考中」提示（`:2128-2133,1283-1359`）与 `/model` 选择器卡片（`:2135-2246`）；媒体按扩展名上传 image/file（`:2265-2294,1103-1162`）；文本按复杂度选 text/post/interactive 卡片三种格式（`_detect_msg_format`，`:1004-1040,2296-2317`），多 markdown 表格自动拆多卡（`:905-933`）。群聊默认串成 thread（`reply_in_thread`，`:329-335,1278-1281`）。
- 流式：`send_delta` 用 CardKit 流式卡片——首个 delta 建卡并带首段文本（`:1469-1542,1723-1738`），按 1s 节流更新（`:415,1759-1765`），`_stream_end` 时末次更新后关闭 `streaming_mode`（`:1578-1613,1634-1676`）；建卡连败 3 次自动降级为普通卡片投递（`:417,1749-1758`）。最终是否真送达由 `_confirmed_streams` 记录，供 `deliver_outbound` 的 `consume_stream_delivery` 抑制重复的普通 final（`:460-472`，配合 `base.py:269-274`）。

### 5.2 telegram（`deeptutor/partners/channels/telegram.py`）

- 连接：长轮询，无公网需求。发送与轮询各用独立 HTTP 连接池，避免 getUpdates 饿死发送（`:352-371`）。注册 /start、/help 与消息 handler（`:376-392`），启动后注册命令菜单并进入 `start_polling`（`:397-417`），`start()` 尾部以 1s 心跳保活（`:420-421`）。
- 入站路径：`_on_message`（`:981-1070`）→ 群聊按 `open/mention/topics_only` 策略过滤（`:934-969`）→ 文本+caption+媒体下载（`:1009-1015,843-895`）→ 引用消息上下文与被引媒体（`:1018-1029`）→ 媒体组（album）0.6s 聚合为一轮（`:1039-1057,1072-1088`）→ `_handle_message`。sender_id 形如 `id|username` 供 allowlist 双匹配（`:313-330,797-801`）。论坛话题派生独立 session key（`:804-809`）。
- 出站路径：`send()`（`:455-527`）先停 typing，媒体按类型分发（`:486-516`），文本按 4000 字符切分（`:522`）；final 走「模拟流式」draft 后落定（`:557-583`）。HTML 渲染失败回退纯文本，纯文本失败才 raise 交给 manager 重试（`:529-555`）。内部对 TimedOut/RetryAfter 再做一层退避（`:585-618`）。
- 流式：`send_delta` 首个 delta 发消息、后续按 `stream_edit_interval`（默认 0.6s）原地编辑（`:38,720-739`）；超长缓冲拆页续流（`:741-775`）；`_stream_end` 编辑定稿并补发溢出块（`:634-695`）。缓冲按 `_stream_id` 键控（`:697-705`）。

### 5.3 napcat（`deeptutor/partners/channels/napcat.py`，OneBot v11 / 个人 QQ）

- 连接：`websockets` 客户端连 NapCat WS（`ws://127.0.0.1:3001` 默认，`napcat.py:48`）；启动即 `aiohttp` 会话 + 指数退避重连（5s→10s→30s 常驻，`:88-117`）。每轮连接先用 `get_login_info` echo 校验身份再进入分发循环（`:119-165`）。
- 入站路径：`_dispatch_frame` 区分 action 响应（echo 匹配 pending future）与事件（`:199-227`）；message 事件解析 OneBot segments（text/image/at/reply/face，`:309-366`），图片经 `validate_url_target` 校验后限流下载（`:527-594`）；群聊按 mention/回复/概率策略决定是否应答（`:368-379`），群消息合成 `昵称: 内容` 上下文，chat_id 为 `group:{id}` / `private:{id}`（`:270-291`）；新成员入群可作为事件转发（`:395-426`）。
- 出站路径：`send()` 未连接直接 raise（让 manager 重试，`:445-449`）；本地图片转 base64 跨机可用（`:477-494`）；发送动作 `send_msg` 走 echo/future 匹配的 `_call_action`（`:496-521`），成功的 message_id 记入 `_bot_outbound_ids` 供「回复我」判定（`:472-475`）。

### 5.4 zulip（`deeptutor/partners/channels/zulip.py`）

- 连接：官方 SDK 同步客户端；`start()` 建 client、`get_profile` 验证（`:118-152`），按 `subscribe_streams` 自动订阅（支持 `*` 全量，`:285-326`），然后起**守护线程** `_run_listener`（`:156-159`），主协程只做心跳（`:161-162`）。
- 入站路径：线程内注册事件队列（`:375-395`）→ `get_events` 长轮询（`:243-277`）→ 队列过期（`BAD_EVENT_QUEUE_ID`）自动重注册（`:259-262`）→ `_on_message`（`:417-499`）：跳过自己（`:397-404`）、去重（`:406-415`）、stream 消息按 mention 策略过滤（`:447-460`，flag 缺失时按 `@**Bot**` 文本兜底，`:521-557`），chat_id 为 `stream:{name}:{topic}` 或 `pm:{user_id}`（`:443-464`），`/user_uploads/` 附件下载到本地（`:559-580,645-677`），最后 `run_coroutine_threadsafe` 切回主 loop 进 `_handle_message`（`:487-499`）。
- 出站路径：`send()`（`:184-202`）先上传媒体（`user_uploads`，`:762-790`），文本做 LaTeX→Zulip math 转换（`:679-704`）并按 10000 字符切分（`:41,201-202`）；发送经 executor + `_call_with_retry`（`:216-232,734-750`）。回复目标（stream/topic/private 收件人）从入站时缓存的 `_recipient_map` 恢复（`:204-214,483`）。

### 5.5 matrix（`deeptutor/partners/channels/matrix.py`）

- 连接：matrix-nio `AsyncClient`，凭据来自配置（access_token/user_id/device_id），加密 store 放 `state_dir()`（`:246-259`）；`_sync_loop` task 跑 `sync_forever`（`:559-566`）。E2EE 可选，缺依赖时显式报错（`:239-244`）。
- 入站路径：事件回调 `RoomMessageText` / 媒体 / 邀请（`:493-502`）；`_should_process_message` 做 ACL + 直聊/群策略（`:589-602`）；媒体事件下载（可解密）落地并附 marker（`:735-784,810-842`），语音自动转写（`:818-823`）；thread 事件把 root event id 写进 metadata（`:615-628`）→ `_handle_message`（`:800-805,833-839`）。
- 出站路径：`send()`（`:458-491`）把附件逐个上传（尊重本地+服务端上传上限，`:369-392,394-456`），文本经 markdown→nh3 净化 HTML 的双 body 发送（`:130-162`）；thread 回复经 `m.relates_to` 还原（`:630-645`）。typing 用 20s keepalive 循环维持（`:53-55,532-557`）。

### 5.6 mochat（`deeptutor/partners/channels/mochat.py`）

- 连接：Socket.IO（msgpack 可选）订阅 `claw.session.events` / `claw.panel.events` 及一组 `notify:chat.*`（`:430-524`）；未装 socketio 或连接失败降级为 HTTP watch/poll worker（session 长轮询 watch、panel 周期 poll，`:671-746`）；另有周期 `_refresh_loop` 做 `*` 通配的会话/面板发现（`:588-603`）。
- 入站路径：watch payload 统一进 `_handle_watch_payload`（游标推进与冷会话过滤，`:750-782`）→ `_process_inbound_event`（`:784-840`）：跳过自己/ACL/消息去重 → panel 群可要求 mention（`:809-818`）→ `non-mention` 模式下未 @ 的消息延迟聚合（默认 120s 或被 mention 立即冲刷，`:267-268,830-838,855-888`）→ `_dispatch_entries` 合成 buffered body 进 `_handle_message`（`:890-917`）。session 游标防抖落盘到 `state_dir()/session_cursors.json`（`:296,981-1023`）。
- 出站路径：`send()`（`:374-410`）按 chat_id 前缀（`session_` vs panel/`group:`/`channel:`/`panel:`）解析目标（`:135-151`），统一走 `_api_send`（`/api/claw/sessions/send` 或 `/api/claw/groups/panels/send`，`:1053-1068`）。注意：mochat 的 `send()` **吞掉发送异常只记日志**（`:409-410`），与「send 失败必须 raise」的基类契约不一致，manager 的重试对它无效。

### 5.7 qq（`deeptutor/partners/channels/qq.py`，官方机器人 botpy）

- 连接：`botpy` Client（WebSocket intents：C2C/群 @/私信，`:30-52`）；`start()` 校验 app_id/secret 后进入 `_run_bot` 自动重连循环（每 5s，`:85-126`）。
- 入站路径：`_on_message`（`:172-203`）按 message_id 去重（deque 1000）→ 群聊取 `group_openid`+`member_openid`，C2C 取作者 id（`:184-194`），chat 类型写 `_chat_type_cache` 供出站选择 API → `_handle_message`。
- 出站路径：`send()`（`:138-170`）带 `msg_seq` 递增防平台去重，按缓存类型走 `post_group_message` / `post_c2c_message`，支持 markdown 开关。

### 5.8 email（`deeptutor/partners/channels/email.py`）

- 连接：无长连接。`start()` 先过 `consent_granted` 同意门槛（`:100-109`）与必填校验（`:111-119`），然后 30s（可配）轮询 IMAP；IMAP 会话在 `asyncio.to_thread` 里每次即开即关（`:125-152,281-380`）。
- 入站路径：`UNSEEN` 搜索 + `BODY.PEEK` 拉取（`:249-253,312`）→ 解析 From/Subject/正文（html 降级为文本，`:418-463`）→ `\Seen` 标记为主去重、UID 集合兜底且上限 10 万（`:95-96,321-370,372-373`）→ 每封邮件 `sender=chat_id` 进 `_handle_message`（`:139-144`）。另有历史区间拉取 `fetch_messages_between_dates` 供摘要任务（`:255-279`）。
- 出站路径：`send()`（`:158-206`）经 SMTP（STARTTLS/SSL 可配，`:228-244`）回复；受 `auto_reply_enabled` 与 `force_send` 元数据控制（`:174-180`），带 `In-Reply-To`/`References` 线程头（`:197-200`），失败 raise 交 manager 重试（`:202-206`）。

## 6. stop/logout 语义汇总（现状 vs pr/channels-idempotent-close）

现状（main）各通道 stop 的资源与方式：

| 通道 | stop 行号 | 释放的资源 | 备注 |
|---|---|---|---|
| feishu | `feishu.py:638-675` | `_running=False` → 线程内取消 SDK 全部任务并关闭 WS 连接（`_shutdown_ws_client`，`:291-308`；`_request_ws_shutdown` 跨线程投递，`:621-636`）→ join 线程（3s 超时）→ 清理 reaction/model-picker 任务与缓存 | SDK 无 stop()，只能取消任务让 `start()` 返回；失败路径大多仅 debug 日志 |
| telegram | `telegram.py:423-441` | 取消 typing/媒体组任务 → `updater.stop()` → `app.stop()` → `app.shutdown()` | 三段式，无吞异常 |
| napcat | `napcat.py:167-187` | 关 WS、关 aiohttp、`_fail_pending` 使挂起 action 立刻失败、cancel 后台任务 | 关闭失败被静默吞掉 |
| zulip | `zulip.py:164-182` | 停 typing → `deregister(queue_id)` → join 监听线程（5s） | deregister 失败被静默吞掉 |
| matrix | `matrix.py:277-296` | 停 typing（不清指示）→ `stop_sync_forever()` → 宽限期等待 sync task（默认 2s，超时 cancel）→ `client.close()` | 宽限期可配 `sync_stop_grace_seconds`（`:196`） |
| mochat | `mochat.py:347-372` | cancel refresh/降级 worker/延迟计时器 → `socket.disconnect()` → 游标落盘 → `http.aclose()` | disconnect/aclose 失败被静默吞掉 |
| qq | `qq.py:128-136` | `_running=False` → `client.close()` | 失败被静默吞掉 |
| email | `email.py:154-156` | 仅置位；轮询循环自然退出；IMAP `logout` 在每轮 finally 里（`:374-378`） | logout 失败被静默吞掉 |

上游侧统一兜底：`ChannelManager.stop_all` 逐通道 try/except（`manager.py:367-373`），Partner 停止/重载也各自兜底（`deeptutor/services/partners/manager.py:919,1026`）。因此单个通道 stop 抛错不会阻断整体停机，但**失败细节常被 `except Exception: pass` 吞掉**，难以排查。

待落地分支 `myfork/pr/channels-idempotent-close`（commit `9ed551c71`，"fix(partners): log channel stop/logout failures instead of swallowing them"）正是针对这一点：在 `deeptutor/partners/helpers.py` 新增 `close_quietly` / `aclose_quietly`（永不抛出、失败记 warning、返回成功标志），应用到 email 的 IMAP logout、matrix typing 失败日志、mochat 的 socket/HTTP 关闭、napcat 的 WS/HTTP 关闭、qq 的 `client.close()`、zulip 的队列注销，并汇总 stop 阶段的清理失败（如 `napcat.py` stop 末尾聚合 warning）；配套测试 `tests/services/partners/test_channel_stop_logging.py`。复核时对照本节表格逐通道确认「每个 close 调用点都有标签化日志 + 汇总告警」即可。

## 7. 新增一个通道需要实现什么

1. **新建模块** `deeptutor/partners/channels/<name>.py`，模块名即通道名（配置键、`msg.channel`、目录名都用它；`registry.py:27-47` 扫包取第一个 `BaseChannel` 子类）。若只是辅助模块（如 `lark_http.py`），保证模块内没有 `BaseChannel` 子类即可被自动忽略（`registry.py:17-24`）。
2. **Config 模型**：定义 `<Name>Config(DeliveryOverrides)`（需要流式再加 `StreamingSupport`），继承 `Base` 获得 camelCase 兼容（`schema.py:9-37`）；实现 `default_config()` 供 onboarding（`base.py:253-256`，参考 `qq.py:71-73`）。在 `__init__` 里把 dict 配置 validate 成模型（参考 `telegram.py:298-302`）。
3. **实现三个抽象方法**（`base.py:137-165`）：
   - `start()`：先做依赖检查（try-import 置 `*_AVAILABLE`，如 `qq.py:15-24`；缺失时 `set_setup_state("unavailable")`，`qq.py:87-93`）与必填字段检查（`set_setup_state("action_required")`，`qq.py:95-104`），再置 `self._running = True` 并进入长驻监听。断线重连自旋（`napcat.py:103-117`）或平台 SDK 自带重连均可。
   - `stop()`：**幂等**、best-effort——逐个关闭连接/任务/线程，任何一步失败都不阻断后续清理（reload 会反复 stop/start，见 §3.4）。建议直接采用 `close_quietly`/`aclose_quietly` 模式（`pr/channels-idempotent-close` 的 `helpers.py`）。
   - `send(msg)`：投递失败**必须 raise**（`base.py:162-163`），manager 才能统一重试（`manager.py:155-190`）。反例警示：`mochat.py:409-410` 吞异常导致无重试。
4. **入站必须走 `_handle_message`**（`base.py:203-251`）：自行完成平台级去重（参考 `feishu.py:442,2341-2348` 的 OrderedDict 或 deque 方案）、群聊策略与 ACL 之前的内容解析；不要绕过 `is_allowed`（空 `allow_from` 通道会被拒绝启用，`manager.py:264-273`）。
5. **媒体与状态**：下载到 `self.media_dir()`、凭据/游标存 `self.state_dir()`（`base.py:99-122`），不要自拼路径——这是 per-partner 隔离的保证。上传媒体时评估大小上限与重试语义（参考 `matrix.py:386-392`、`napcat.py:537-575`）。
6. **可选：流式**：覆写 `send_delta` 并把 config 挂上 `StreamingSupport.streaming`（`base.py:167-191`）；缓冲按 `_stream_id` 键控（`telegram.py:697-705`），`_stream_end` 后落定最终文案；若实现了「确认最终送达」，提供 `consume_stream_delivery`（`base.py:269-274`、`feishu.py:466-472`）。
7. **状态上报**：连接各阶段调用 `set_setup_state`（`connecting/connected/running/error/action_required`，`base.py:74-87`），UI 经 `ChannelManager.get_status` 读取（`manager.py:485-504`）。
8. **不做的**：不要在模块级连接网络或读写文件（构造只是解析 config）；不要在 `_handle_message` 之前做重活（会阻塞平台回调线程——参考 zulip 线程→loop 的 `run_coroutine_threadsafe` 模式，`zulip.py:487-499`）；不要假设只有一个 Partner 实例。
9. **外部插件通道**（不发 PR 时）：entry_points `group="deeptutor.partners.channels"` 注册即可被同一 manager 加载，但无法覆盖内置同名通道（`registry.py:50-70`）。

## 8. 相关测试入口

- 通道层通用：`tests/services/partners/test_channel_manager.py`、`test_channel_streaming.py`、`test_channel_setup_status.py`、`test_channel_secrets.py`、`test_channel_onboarding.py`。
- 单通道：`test_telegram_channel.py`、`test_napcat_channel.py`、`test_zulip_channel.py`、`test_feishu_*.py`（域初始化/最终投递/模型选择器/流式韧性/思考提示/WS 卡片回调）、`test_mattermost_channel.py`、`test_msteams_channel.py`、`test_wecom_channel.py`、`test_weixin_channel.py`。
- 出站契约：`test_partner_outbound_delivery.py`（重试/合并/去重语义锁）。
- 待落地分支新增：`tests/services/partners/test_channel_stop_logging.py`（stop/logout 失败可观测性）。

运行方式（限时）：`timeout 900 python -m pytest -q -p no:cacheprovider tests/services/partners/test_channel_manager.py`
