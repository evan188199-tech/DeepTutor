# partners/channels 通道类生命周期契约一致性清点

- 日期：2026-10-05
- 基线：origin/main `f07029cfc`（release v1.6.13），worktree 分支 `scan/channel-contracts-20261005`
- 范围：`deeptutor/partners/channels/`（16 个通道类 + base/manager/registry 基础设施，共 ~13.5k 行）
- 性质：只读清点，未改任何产品代码；本文与 SHA256SUMS 为本卡全部新增文件
- 去重输入：AGEN-493（`pr/channels-idempotent-close` @ `9ed551c71`，**尚未合并进 origin/main**）、test-mochat-channel（`test/mochat-channel-20261005` @ `a47de7561`）、partners 导读（`evidence/guide-partners-2026-10-03` @ `e226cdafd`）
- 行号核对：下述全部 path:line 均在基线 commit 上逐条抽查复核（含全部 P0/P1 锚点）

## 1. 基础契约（参照系）

- 抽象面：`base.py:137-165` — `start()` / `stop()` / `send(msg)` 三个抽象方法；`send` 契约明确要求"实现应在投递失败时抛错，便于 manager 统一重试"（`base.py:162-164`）。
- 流式：`base.py:167-180` — `send_delta(chat_id, delta, metadata)` 可选；**要求按 `_stream_id` 而非仅 `chat_id` 键控缓冲**（`base.py:178`）。
- 状态：`base.py:65` `_running` 标志；`manager.py:301-341` 期望通道在首个网络 await 前同步置位（`manager.py:306-310` 注释）。
- 管理端：`manager.py:155-190` `send_with_retry`（默认 3 次，1/2/4s 退避，CancelledError 透传，最终失败记日志吞掉）；`manager.py:358-373` `stop_all` 逐通道调 `stop()`，异常记日志继续；`manager.py:335-341` start 抛错时置 `_running=False` 并报 error 状态。

## 2. 契约矩阵（16 通道全覆盖）

### 2.1 start / stop 生命周期

| 通道（类 @ 行） | start 机制 | `_running=True` 先于首个长 await | start 失败语义 | 双重启动防护 | stop 幂等（重复/未启动安全） | stop 异常语义 | stop 延迟 |
|---|---|---|---|---|---|---|---|
| feishu (`FeishuChannel` feishu.py:396, start:480) | lark WS 长连（SDK 线程+内部重连 feishu.py:573-608） | ✔ feishu.py:517 | 缺 SDK/配置→静默返回（482-499）；WS 错误线程内自旋重试，**永不抛** | ✘ | ✔（627-630,651 空守卫） | 内部守卫式，无整体吞 | join 3s（654-658），线程悬挂仅告警 |
| weixin (`WeixinChannel` weixin.py:136, start:343) | HTTP 长轮询（内联 while :366-388） | ✔ weixin.py:356 | 无 token→静默返回（348-354）；其余异常记日志+退避续跑，**永不抛** | ✘（二次 start 顶掉旧 client :358） | ✘ **未启动时 stop 会覆写 account.json**（:401→:235-245） | 无整体 try；`_save_state` 内部 suppress（:237） | ≤ 单次长轮询 ~45s（:376-377 才检查） |
| telegram (`TelegramChannel` telegram.py:274, start:332) | PTB 长轮询（:414-417） | ✔ telegram.py:345 | 缺 token 静默返回（334-343）；`get_me`（:401）**抛给 manager**，但发生在 `app.start()` 之后，留下半启动状态 | ✘（:372 直接替换 `_app`） | ✔（:436 守卫） | **无任何 try**：首步失败中断后续且抛出（:438-441） | PTB stop 链自身时长 |
| mochat (`MochatChannel` mochat.py:276, start:319) | Socket.IO WS + HTTP 轮询兜底（:442-450,696-746） | ✔ mochat.py:332 | 缺 token 静默返回（321-330）；连接失败**降级为轮询**不抛（340-341,508-515） | ✘（:333 重建 `_http`） | ✔（None 守卫 350-371） | 仅 socket disconnect 吞（360-361） | 任务 gather 有界（354） |
| zulip (`ZulipChannel` zulip.py:64, start:102) | 事件队列长轮询（**专用线程** zulip.py:156-159, :234-283） | ✔ zulip.py:114，**但 :134 同步鉴权+`time.sleep` 退避跑在事件循环上**（:229） | 客户端/鉴权失败→置 error 静默返回（125-142）；线程内自愈重试，**永不抛** | ✘（:156 再起线程） | ✔（:170,:179 守卫） | deregister `try/except: pass`（170-174）；**deregister+join(5) 阻塞事件循环**（170-180） | 长轮询 60s（:61），join(5) 后线程可残留 |
| msteams (`MSTeamsChannel` msteams.py:107, start:145) | 内置 ThreadingHTTPServer webhook（:179,:228） | ✔ msteams.py:175 | 缺依赖/配置静默返回（147-164）；bind 失败**抛**（:228） | ✘（:228 重绑端口） | ✔（250-259 全守卫） | **无 try**：shutdown/join 抛则中断后续（251-259），且阻塞事件循环 | join ≤2s |
| matrix (`MatrixChannel` matrix.py:204, start:235) | nio `sync_forever` 长轮询任务（:275,:562） | ✔ matrix.py:237 | E2EE 依赖缺失 **ImportError 抛**（239-244）；`_sync_loop` 裸 `except: sleep(2)` 无日志（565-566） | ✘（:249 重建 client） | ✔（280-296 守卫） | 超时/取消显式处理（293-294）；`client.close()` 无守卫（:296） | 受 grace timeout 约束（287） |
| napcat (`NapcatChannel` napcat.py:60, start:88) | WebSocket+无限重连（103-117） | ✔ napcat.py:100 | 缺 ws_url 静默返回（89-98）；连接失败自旋重试不抛（110-117） | ✘（:101 顶掉旧 session） | ✔（169-187 守卫） | **双重 `except Exception: pass`**（170-179）→ AGEN-493 已覆盖 | 有界（任务 gather :182-187） |
| dingtalk (`DingTalkChannel` dingtalk.py:116, start:152) | Stream Mode WS（SDK :182,:194） | ✔ dingtalk.py:174 | 缺依赖/配置静默返回（155-172）；`while` 内捕获重试 5s（191-203）；外层异常置 False 返回（205-207），**永不抛** | ✘（:175 顶掉 `_http`） | ✔（:217 守卫） | 无 try：`aclose()` 抛则中断；**SDK client 从不关闭**（213-223） | **无界**：`await self._client.start()`（:194）不受 `_running` 中断 |
| discord (`DiscordChannel` discord.py:48, start:71) | Gateway WS 自实现（:87-104） | ✔ discord.py:84 | 缺 token 静默返回（73-82）；断线自旋重试不抛（96-104） | ✘（:85 顶掉 `_http`） | ✔（109-120 None 守卫） | 无 try：ws/http close 抛则中断（115-120）；typing/heartbeat cancel 不 await（109-114） | close 即刻（网关循环随 close 退出 :332） |
| mattermost (`MattermostChannel` mattermost.py:64, start:115) | v4 WS + REST（:149） | ✔ mattermost.py:128 | 缺配置静默返回（117-126）；WS 错误自旋重试 5s 不抛（157-168） | ✘（:129 顶掉 `_http`） | ✔（:173,:179 守卫） | ws close 异常吞成 warning（174-177） | close 即刻 |
| email (`EmailChannel` email.py:55, start:98) | IMAP 轮询（无 IDLE，:127 to_thread） | ✔ email.py:121 | 守卫静默返回（100-119）；整圈异常记日志续跑（145-150），**永不抛** | ✘（并发双轮询） | ✔（无持久资源） | 无异常路径；IMAP logout 吞（375-378）→ AGEN-493 已覆盖 | **≤ poll_seconds（默认 30s，:48,:152）** |
| slack (`SlackChannel` slack.py:51, start:70) | Socket Mode WS（:93-98） | ✔ slack.py:90 | 缺 token/mode 静默返回（72-88）；connect 超时→自行 stop 后 **raise**（110-123）；auth_test 失败仅告警续跑（105-106） | ✘ | ✔（:134 守卫） | close 异常吞成 warning（137-138） | close 即刻 |
| wecom (`WecomChannel` wecom.py:39, start:67) | WSClient WS（SDK 无限重连 :97-99） | ✔ wecom.py:90 | 缺 SDK/配置静默返回（69-86）；首次 connect 裸 await **可抛**（:118），之后 SDK 自愈 | ✘ | 部分（:127 守卫但 **client 不置 None**，:127-128） | `disconnect()` 无守卫，异常上抛（:128） | SDK 侧重连节奏 |
| qq (`QQChannel` qq.py:65, start:85) | botpy SDK WS（:117） | ✔ qq.py:106 | 缺 SDK/配置静默返回（87-104）；`_run_bot` 捕获一切、5s 重连（112-126），**永不抛** | ✘ | 部分（**client 不置 None**，131-135） | **裸 `except: pass`**（131-135）→ AGEN-493 已覆盖 | ≤5s 重连间隔（:126） |
| whatsapp (`WhatsAppChannel` whatsapp.py:27, start:50) | WS 连 Node 桥（:63） | ✔ whatsapp.py:59 | 桥不可达自旋重试 5s 不抛（83-94） | ✘ | ✔（:102 守卫） | `close()` **无守卫**（102-103）；与 start 循环 `async with` 双重关闭竞态（:63 vs :103） | ≤5s 退避（:94） |

共同点：16/16 均在首个长 await 前同步置位 `_running`（满足 `manager.py:306-310` 假设）；16/16 **均无双重启动防护**；健康时 `start()` 都不返回（`while self._running` 心跳尾）；所有通道 stop 都不做平台侧 logout（仅本地拆除，行为一致）。

### 2.2 send / send_delta 投递契约

| 通道（send @ 行） | 失败语义 | not-running/未初始化 | 内部重试 | 超时 | send_delta（@ 行） |
|---|---|---|---|---|---|
| feishu (2115) | **吞**：`except Exception: logger.error`（2322-2323）；底层一律返回 bool（1444-1446） | 静默 return（2117-2119） | 无 | **无** | 有（1615）：按 `_stream_id` 键控 ✔（454-458）；**永不抛**；3 次建卡失败降级普通卡片（1749-1758）；独有 `consume_stream_delivery`（466-472，`base.py:269-274` 唯一实现方） |
| weixin (943) | **抛** ✔（944-991,1064-1066）；媒体 4xx/非网络错误降级占位文本（1037-1055） | **抛 RuntimeError**（944-945） | 无 | 客户端级（:359） | 名义存在（1078）：仅 `_stream_end` 时 flush 工具提示，**无真实流式**、不读 `_stream_id` |
| telegram (455) | 文本**抛** ✔（550-555）；媒体吞→占位文本（508-516） | 静默 return（457-459,466-469） | 有：`_call_with_retry` 3 次（585-618，叠加 manager 重试） | 池级 30s（352-365） | 有（624）：按 chat_id 键 + `_stream_id` 校验（698-704），效果合规；终帧失败抛（682-683） |
| mochat (374) | **吞**：`except Exception: logger.error`（409-410）；`_post_json` 的 RuntimeError 被吃掉 | 静默 return（376-390） | 无 | 客户端级 30s（:333） | 无 |
| zulip (184) | **API 错误仅记日志不抛**（749-750,783-785）；**注释宣称 raise 与实现相矛盾**（194-195）；仅传输层异常会抛 | 静默 return（185-187） | `_call_with_retry` 3 次（216-232，executor 内） | 端点级 60s（:61,:747） | 无 |
| msteams (261) | **抛** ✔（266-301） | 抛 RuntimeError（266-271） | 无 | 客户端级 30s（:174） | 无 |
| matrix (458) | **半抛**：nio 返回 `RoomSendError` 对象但 send 不检查（:367，仅回调记录 :516-517）；未启动静默 return（460-461）；媒体失败并入占位文本（467-483） | 静默 return（460-461） | 无 | 无显式超时 | 无 |
| napcat (445) | **抛** ✔（446-449 显式注释、513-518）；媒体失败跳过并告警（477-494） | 抛 RuntimeError（446-449） | 无 | 动作级 20s（:35,:512） | 无 |
| dingtalk (498) | **吞**：token 失败静默 return（500-502）；`_send_batch_message` 返回 bool 被忽略（:505,:409-427） | 静默 return（500-502） | 无 | **无**（:175 裸 `httpx.AsyncClient()`） | 无 |
| discord (122) | 文本**抛** ✔（161-162）；媒体吞→占位文本（144-148） | 静默 return（124-126） | 有：`_send_payload`/`_send_file`/`_api_request` 各 3 次+429 退避（263-279,303-325,172-184，叠加 manager 重试） | 30s（:85） | 有（186）：**仅按 chat_id 键控**（:68,:199-222），`_stream_id` 只作错配丢弃 —— 违反 `base.py:178`；不抛（_api_request 异常可传出但 _http 为 None 时静默丢） |
| mattermost (372) | 文本**抛** ✔（:421 raise_for_status 上抛）；媒体吞（448-450） | 静默 return（378-380,393-395） | 无 | 30s（:131） | 无 |
| email (158) | SMTP 失败**抛** ✔（204-206）；守卫类静默 return（160-180） | 静默 return（160-180） | 无 | SMTP 30s（:229） | 无 |
| slack (141) | 文本**抛** ✔（159-163）；媒体吞（165-173） | 静默 return（147-149） | 无 | **无** | 无 |
| wecom (365) | `reply_stream` 失败**抛** ✔（391-396）；**无存储 frame 时静默丢**（382-385；frame LRU 1000 且重启即失，311-312） | 静默 return（370-385） | 无 | **无** | 无 |
| qq (138) | 发送失败**抛** ✔（162-170）；未初始化静默 return（143-145）；**路由缓存未命中按 c2c 兜底发错 API**（:160） | 静默 return（143-145） | 无 | **无** | 无 |
| whatsapp (106) | `ws.send` 失败**抛** ✔（117）；未连接静默丢（112-114） | 静默 return（112-114） | 无 | **无** | 无 |

### 2.3 入站解析与幂等

| 通道 | 解析入口 | 解析错误去向 | 入站去重/幂等 |
|---|---|---|---|
| feishu | SDK 事件分发（533-547）→ `_on_message`（2333） | 整体 catch 记日志丢弃（2445-2446） | message_id OrderedDict 1000（2341-2348）；重启后去重缓存清零（无持久 cursor） |
| weixin | 轮询 `_poll_once`（429-484） | 单条 catch 记日志丢弃（479-483） | `_processed_ids` 1000（507-511）+ **持久化 cursor** `get_updates_buf`（472-475） |
| telegram | PTB handlers（376-392）→ `_on_message`（981） | 静默/`_on_error` 记日志（1113-1115） | `drop_pending_updates`（:416）+ PTB offset；**无逐条 seen-set** |
| mochat | WS 事件 + 轮询兜底（478-493,696-746） | 非 dict 静默跳过（751-773）；worker 异常退避续跑 | 持久化 session cursor（981-1004）+ seen-set 2000（844-853）；面板轮询仅靠 seen-set |
| zulip | 监听线程长轮询（234-283） | 批内 `_on_message` 异常会**丢弃同批剩余事件**（cursor 已前移 :272-275） | event-id cursor（272-275）+ deque 5000（:84,406-415） |
| msteams | HTTP webhook `do_POST`（180-223） | 坏 body→400（190-194）；handler 失败仍回 200（217-223，消息丢失） | **无**（无 activity id 去重，重投会重复处理） |
| matrix | nio sync 回调（795,810） | 回调异常抛回 `_sync_loop` 裸吞无日志（565-566） | 仅 sync-token 持久化（:254,:267-273）；store 加载失败会重放（:271,:273 注释自认） |
| napcat | `_dispatch_frame`（200-206） | 非 JSON debug 丢弃 | `_processed_ids` deque 2000（248-252）；**非 int id 绕过去重**（248-249） |
| dingtalk | SDK 回调 `process`（51） | **异常仍 ACK STATUS_OK** 抑制服务端重试（101-104，刻意） | **无 message-id 去重** |
| discord | `_gateway_loop`（327-337） | 坏 JSON 告警续跑 | **无**；`_seq` 已保存但从不用于 RESUME（344-345），断线窗口消息丢失 |
| mattermost | `_event_loop`（230-245） | posted 坏 JSON **静默 return**（252-255） | **无 post-id 去重**（仅 bot user_id 回声过滤 :265-267） |
| email | IMAP UNSEEN 拉取（281-327） | 单封 continue（313-318） | `\Seen` 标记 + UID seen-set 10 万上限（320-322,363-370） |
| slack | Socket Mode 回调（175-229） | 静默过滤 + 整体 catch 丢弃（250-265） | 仅 mention/message 重叠防重（204-208）；**无 event id 幂等**（重连重投会重复） |
| wecom | SDK 事件分发（155-173,206） | 整体 catch 丢弃（328-329） | msg_id LRU 1000（214-225，含 `chatid_sendertime` 兜底键） |
| qq | botpy 回调（172-203） | 整体 catch 丢弃（202-203） | deque 1000（176-178） |
| whatsapp | 桥 WS 帧（75-79,119） | 坏 JSON 丢弃（121-125） | OrderedDict 1000（138-143）；**无 id 消息绕过**（:138） |

## 3. 不一致分级清单

### P0（破坏投递契约 / 数据丢失）

1. **send() 永不抛错 → manager 重试策略失效**（契约 `base.py:162-164`）：
   - feishu.py:2322-2323（吞一切）；mochat.py:409-410（吞一切）；dingtalk.py:500-518（bool 被忽略）。
   - zulip.py:749-750,:783-785（API 错误仅日志；且 :194-195 注释宣称 raise，与实现矛盾）。
   - 影响：`manager.py:155-190` 的 3 次退避重试对这 4 个通道完全失效，瞬时故障直接丢消息。
   - 关联：`test/mochat-channel-20261005` 的 `test_send_failure_does_not_raise` 把 mochat 现状锁进测试，修复时必须同步改该测试。
2. **weixin stop() 可在未 start 时覆写持久化会话**：weixin.py:401 无条件 `_save_state()`，把 account.json 的 token/cursor 写空（:235-245）→ 凭据与轮询进度丢失，需重新扫码/重放。
3. **discord send_delta 仅按 chat_id 键控**：discord.py:68,:199-222，同 chat 并发流互相覆盖，违反 `base.py:178`；feishu（:454-458）与 telegram（:698-704）已合规可作参照。

### P1（生命周期与资源）

4. **16/16 通道无双重启动防护**：二次 `start()` 在 feishu（重复 WS 线程/Client）、weixin/napcat/discord/dingtalk/mattermost/mochat/msteams（顶掉旧 client 造成泄漏）、telegram（替换 `_app`）、zulip/qq/whatsapp/email（双循环/双线程）各自产生泄漏或竞态。manager 当前只在 `_init_channels` 构造一次、`start_all` 启动一次（manager.py:343-356），属"靠调用方纪律"的隐性契约。
5. **stop 清理缺口**：
   - feishu：lark Client + keep-alive transport 从不关闭（feishu.py:509,:522-529 vs stop :638-675 无 close）；`_stream_bufs`/`_thinking_notices` 不清（:443,:450），中断流的卡片与"思考中"提示残留。
   - slack：`AsyncWebClient` 从不关闭（slack.py:92 vs :131-139）。
   - dingtalk：SDK StreamClient 从不关闭（dingtalk.py:182 vs :213-223）。
   - telegram：stop 无整体守卫，首步失败跳过余下拆除（telegram.py:438-441）；typing/media 任务 cancel 不 await（428-433）。
   - mochat：refresh 任务 cancel 不 await（350-352）。
   - dingtalk/discord/zulip/telegram：任务 cancel 均不 await（dingtalk.py:221-222, discord.py:109-114, zulip.py:167-168, telegram.py:428-433）。
6. **stop 延迟不可控**：dingtalk 无界（`await self._client.start()` 不受 `_running` 中断，dingtalk.py:194）；zulip ≤60s 长轮询 + join(5) 后线程残留（zulip.py:61,:179-180）；email ≤poll 周期 30s（email.py:48,:152）；weixin ≤单次长轮询（weixin.py:376-377）；whatsapp ≤5s 退避（:94）。
7. **事件循环阻塞**：zulip start 同步鉴权+sleep 退避在循环上（zulip.py:134,:229）、stop 的 deregister+join 阻塞循环（:170-180，AGEN-493 只解决"吞"不解决"阻塞"）；msteams stop 的 shutdown/join 阻塞循环（msteams.py:251-255）；weixin 媒体整文件读取+MD5+AES 加密在循环上（weixin.py:1199-1201,:1256）。
8. **首发路由/回执依赖易失状态**：qq 未入站过时按 `c2c` 兜底发错 API（qq.py:160）；wecom 重启后 `_chat_frames` LRU 清空，回复静默丢弃（wecom.py:311-312,:382-385）。

### P2（健壮性打磨）

9. 入站幂等缺口：msteams（无 activity id 去重）、discord（seq 存而不用 :344-345）、slack（无 event id 幂等）、dingtalk（无 message-id 去重）；zulip 批内事件丢失（:272-277）；weixin 兜底键/无 id 绕过（:495-497）、whatsapp 无 id 绕过（:138）、napcat 非 int id 绕过（:248-249）；matrix 重放风险为代码注释自认的已知项（:271,:273）。
10. 发送超时缺失：dingtalk（裸 client :175）、slack/wecom/qq/whatsapp（无超时）、feishu（executor 调用无超时 :2254-2262）。
11. not-running 语义不一：weixin 未初始化时 raise（:944-945），其余 15 通道静默 return（表 2.2"not-running"列）——manager 只会向在册通道派发，实际影响小，但契约应文档化统一。
12. weixin 死字段：`_poll_task` 仅赋 None（:166），stop 里的 cancel 分支永不为真（:394-395），真实轮询循环在 start 协程内。
13. 小项：discord/mattermost 发送路径 sync `open()`（discord.py:305, mattermost.py:437）；`_target_locks` 无上界（mochat.py:757）；`_recipient_map` 无上界（zulip.py:88）；媒体目录无清理策略（napcat.py:588-590, matrix.py:770, weixin.py:775-777）。

## 4. 可拆修复卡条目（建议逐卡独立可验收）

> 每卡独立分支；测试命令限时（`timeout 900 python -m pytest -q -p no:cacheprovider …`）；除卡 E 涉及 base 外均不越出单通道文件。

- **卡 A（P0）feishu send 抛错语义**：`send()` 顶层把投递失败改为 raise（feishu.py:2322-2323），保留 `delivered` 反应清理逻辑；底层 `_send_message_sync` bool 链路透传失败原因。验收：模拟发送失败时 `send_with_retry` 生效（参照 `test_channel_stop_logging` 风格补失败注入测试）。
- **卡 B（P0）mochat send 抛错语义**：mochat.py:409-410 改为记录后 raise；**必须同步更新 `tests/services/partners/test_mochat_channel.py::test_send_failure_does_not_raise`**（该测试在 test/mochat-channel-20261005 分支，先合并测试分支再改，或在本卡一并交付）。
- **卡 C（P0+P1）dingtalk 投递与资源**：send 失败 raise（dingtalk.py:498-518）；`AsyncClient` 补 timeout（:175）；stop 关闭 SDK StreamClient（:213-223）并让 `_running` 可中断 :194 的 await。
- **卡 D（P0）zulip send API 错误抛出**：`_send_text`/`_upload_and_send` 失败改 raise（zulip.py:749-750,:783-785），修正 :194-195 注释与实现一致。
- **卡 E（P1）BaseChannel 双重启动防护**：base 层加 `if self._running: return`（或 per-channel guard），一处收敛 16 通道（base.py:137-147）；验收：连续两次 start 无资源泄漏（以各通道 `_client/_http/_app` 引用计数或任务数断言）。
- **卡 F（P0）weixin stop 守卫与死字段**：未成功 start 过则不 `_save_state`（weixin.py:401）；删除死字段 `_poll_task` 及 :394-395 分支。
- **卡 G（P1）stop 清理补全**：feishu 关闭 lark Client/transport + 清 `_stream_bufs`/`_thinking_notices`（feishu.py:638-675）；slack 关 `_web_client`（:131-139）；telegram 逐步 try + await 任务取消（:427-441）；mochat await refresh 任务（:350-352）；dingtalk/discord/zulip 补 await。
- **卡 H（P0）discord send_delta `_stream_id` 键控**：`_stream_bufs` 键改为 `_stream_id or chat_id`（discord.py:68,:199-222），对齐 feishu `_stream_key`（feishu.py:454-458）。
- **卡 I（P1）事件循环阻塞治理**：zulip start 鉴权与 stop 的 deregister/join 移入 `asyncio.to_thread`（zulip.py:134,:170-180；注意 AGEN-493 的 `aclose_quietly` 不做 offload，合并后仍需本卡）；msteams shutdown/join offload（:251-255）；weixin 媒体加密移入 to_thread（:1199-1256）。
- **卡 J（P2）入站幂等补齐**：msteams activity id 去重；discord seen-set 或 RESUME；slack event id 幂等；dingtalk message-id 去重（dingtalk ACK-OK 语义保留）。
- **卡 K（P1）qq/wecom 易失状态**：qq 路由缓存未命中时显式报错或持久化 chat_type（qq.py:160）；wecom frame 缺失时显式 warning+错误状态而非静默丢（wecom.py:382-385）。
- **卡 L（P2）发送超时归一**：slack/wecom/qq/whatsapp/feishu 发送路径补超时；dingtalk 随卡 C。
- **卡 M（P2）not-running 契约文档化**：base.py:154-165 注明"未运行时 send 的预期行为"，各通道择一（建议统一静默 return + error 状态，因 manager 不会向未启动通道派发）。

## 5. 去重说明

- **AGEN-493**（`pr/channels-idempotent-close` @ `9ed551c71`，尚不在 origin/main）：已修复 napcat stop（ws/http close 吞）、qq stop（close 裸 pass）、zulip stop（deregister 吞）、email 每轮 IMAP logout 吞、mochat stop（socket/http aclose 吞）与 matrix typing 吞——本文第 3 节相应条目标记为已覆盖，**未重复立项**。遗留（493 未覆盖）：① 它只解决"吞异常"，zulip deregister/join、msteams shutdown/join 的**事件循环阻塞**仍在（→ 卡 I）；② telegram/whatsapp/wecom/dingtalk/msteams 的"无守卫 stop 链"不在 493 范围（→ 卡 G）；③ send 契约、双重启动等与 493 无交叠。
- **test-mochat-channel**（`test/mochat-channel-20261005` @ `a47de7561`，591 行测试）：已覆盖 mochat 解析/路由/游标/stop 幂等等；其 `test_send_failure_does_not_raise` 锁定了"send 不抛"现状，与卡 B 冲突，需在该卡中一并修订；除此之外本文 mochat 发现（send 吞 :409-410、refresh 任务不 await :350-352、`_target_locks` 无上界 :757）不与该测试分支重复。
- **partners 导读**（`evidence/guide-partners-2026-10-03/guide.md` @ `e226cdafd`）：为模块级流程导读，不含逐通道生命周期矩阵；本文为其补齐 16 通道契约细节。注意导读基于旧快照，个别行号已漂移（如导读引 `manager.py:247` 的 dispatch 循环，现位于 manager.py:409），以本文行号（基于 f07029cfc）为准。

## 6. 方法与限制

- 全部结论基于静态阅读 + 16 通道逐条行号抽查复核；未运行通道、未连接任何平台、未启动任何服务。
- 未覆盖：`lark_http.py`（feishu webhook 辅助）、`weixin_qr.py`（二维码辅助）、registry 插件入口的第三方通道；`services/partners` 侧 runner 生命周期不在本卡范围。
- 无安全类发现（未涉及注入/越权/密钥暴露类问题；napcat 媒体 URL 已有 `validate_url_target` 校验，napcat.py:481-486）。
