# DeepTutor partners 通道架构导读（17 通道矩阵）

- 基线：origin/main @ `6cf793bd8`（v1.6.14）。
- 范围：`deeptutor/partners/` 通道层全部——生命周期、`channels/` 下 17 个通道、公共层（base/manager/registry/lark_http）与 partners 级 helpers；标注各通道已知薄弱点，供修卡定位。
- 所有锚点形如 `path:line`，相对仓库根；`channels/` 内文件简写为文件名。
- 去重：guide-multi-user（账号域）不在此重复；各通道 test/fix 卡是单通道轴，本卡是横向导读。

## 1. 这一层是什么：一条消息的往返

```
平台(SDK/WS/HTTP) → 通道接收循环 → BaseChannel._handle_message → MessageBus.inbound
   ↑                                                    ↓
   │                                              PartnerRunner（deeptutor/services/partners/runtime.py:158）
   │                                                    ↓
ChannelManager 出站调度器 ← MessageBus.outbound ← 回复 OutboundMessage
   └→ 过滤/合并/去重 → send_with_retry → deliver_outbound → channel.send/send_delta
```

- 通道只做三件事：把平台消息翻译成 `InboundMessage` 投进 bus；把 `OutboundMessage` 翻译回平台 API；维护连接与状态上报（`set_setup_state`，base.py:74）。业务与账号隔离都不在通道里。
- 核心契约：`BaseChannel`（channels/base.py:38）——`start/stop/send` 抽象（:138/:150/:155，send 必须 raise 才能触发 manager 重试，:162-165）；可选 `send_delta`（:167）+ `supports_streaming`（:182，需覆写 + `streaming` 配置）；`is_allowed` 空=全拒、`"*"`=全放（:193）；`_handle_message`（:203）做门禁后打 `_wants_stream`（:235-239）入 bus。

## 2. 通道生命周期（onboarding → start → 收/发 → typing → stop）

- **onboarding**：交互式接入走 `ChannelOnboardingManager`（deeptutor/services/partners/channel_onboarding.py:140，start/status/cancel/apply :157/:177/:192/:200），目前只覆盖 feishu（:336）与 wecom（:383）；weixin 走 QR 专线 `deeptutor/services/partners/weixin_onboarding.py`（消费 channels/weixin_qr.py 协议库）。其余通道手填 config；`default_config()` 钩子供插件自动填充（base.py:253）。
- **构造**：每个 Partner 一个 `ChannelManager`（deeptutor/services/partners/manager.py:936-944）；`constructing_for` ContextVar（base.py:19/:22）让 `__init__` 内就能解析 partner 隔离的 media/state 目录（base.py:99/:109，config/paths.py）。
- **start**：`start_all`（channels/manager.py:343）先起出站 dispatcher，再逐通道 `_start_channel`（:301）：setup 状态机 connecting→running/action_required/error（:302-341），`_running` 在首个 await 前同步置位即视为监听存活（:310-317）。
- **收**：平台事件 → 通道接收循环 → `_handle_message`（base.py:203）allow 门禁 → bus；`session_key` 覆写支持线程级会话（base.py:210/:223，deeptutor/partners/bus/events.py:27）。
- **发**：`bus.publish_outbound` 盖 `_enqueued_at`（deeptutor/partners/bus/queue.py:29-38）→ dispatcher 1s 超时轮询（channels/manager.py:409-461）→ progress/tool_hint 开关过滤（:429-433）→ 流 delta 合并（:46-100，:438-440）→ 重复回复指纹抑制（:382-407）→ `send_with_retry` 1/2/4s 退避（:23/:155-190）→ `deliver_outbound` 三分支：delta/end、`_streamed` 终局确认失败则补发普通 send（base.py:264-276）。
- **typing**：六种风格——telegram chat_action 循环（telegram.py:1102/:1114）、discord POST typing（discord.py:494）、matrix room_typing keepalive（matrix.py:519/:532）、zulip set_typing_status（zulip.py:815/:824，仅 DM）、weixin 票据制 sendtyping（weixin.py:787/:918/:1090）、feishu 表情+可撤回"思考中"（feishu.py:831/:1344）；slack 用 :eyes: 表情替代（slack.py:237）；其余 10 通道无 typing。
- **stop**：`stop_all`（channels/manager.py:358-373）先停 dispatcher 再逐个 `channel.stop()` 并置 disconnected。已知的"停不干净"：weixin 取消从未赋值的 `_poll_task`（weixin.py:394）、会话暂停 sleep 最长 3600s（:432）、msteams 每请求阻塞桥接线程最长 15s（msteams.py:203）、email 无法中断 in-flight IMAP fetch（email.py:156）。

## 3. 公共层

- **base.py**（276 行）：契约见 §1；另有构造期 owner 注入（:19）、setup_state 发布（:74-97，永不带凭据）、partner 隔离目录（:99-122）、Groq 语音转写（:124-135）、流/终局统一投递（:264-276）。
- **channels/manager.py**（512 行）：发现+enabled 过滤+allow_from 空拒启动（`_init_channels` :222-281，import 失败标 unavailable :244-250）；出站管线（合并/去重/重试）与 setup 状态机见 §2；流合并与 progress 合并是模块级函数（:46/:103），partner 路由器复用同一份。
- **channels/registry.py**（97 行）：pkgutil 零导入扫描（:27-35，`_INTERNAL` 排除 base/manager/registry :14）；`load_channel_class` 取模块里第一个 BaseChannel 子类（:38-47）；"能 import 但没通道"抛 `NotAChannelModule`（:17-24）——lark_http.py 与 weixin_qr.py 由此静默跳过（:86-87）；entry_points 外部插件（:50-61），内置优先防 shadow（:64/:92-95）；依赖缺失进 `errors` 而非静默（:73-90）。
- **channels/lark_http.py**（79 行）：把 lark-oapi 同步传输的 `requests.request` 换成线程本地 Session keep-alive（:48/:59），调用耗时 ~2.0s→~0.55s；仅 feishu 使用（feishu.py:504/:509）。风险：monkey-patch SDK 内部，版本耦合靠 isinstance 守（:73-74），进程级全局态（:34-36）。
- **deeptutor/partners/helpers.py**（117 行）：图片 MIME 魔数探测（:8）、`safe_filename`（:36）、`split_message` 按行/空格断句（:42）、markdown 表格降级为"标签行"（:77-117，Slack 风格纯文本通道用）。
- **deeptutor/partners/network.py**（101 行）：通道媒体 URL 专用 SSRF 防护 `validate_url_target`（:59-101），比 MCP 层更严（全私网段拒绝，:1-8）；loopback 白名单只认字面 localhost/127/::1（:45-56）。
- **deeptutor/partners/transcription.py**（61 行）：Groq Whisper 转写，60s 超时（:52），失败返回空串。
- **bus/**：`InboundMessage`/`OutboundMessage`（deeptutor/partners/bus/events.py:11/:33；session_key 属性 :27-29）；`MessageBus` 双 asyncio.Queue（deeptutor/partners/bus/queue.py:9-19）+ 非阻塞 `try_consume_outbound`（:44-53，供合并窥探）。
- **config/**：`DeliveryOverrides`（send_progress/send_tool_hints，config/schema.py:15）与 `StreamingSupport`（:28，仅 feishu/telegram/discord 继承）；`manager._resolve_bool_override` 兼容 camelCase（channels/manager.py:283-299）。

## 4. 17 通道矩阵（入口 / 契约 / 薄弱点）

### telegram — telegram.py
- 入口：`TelegramChannel`（:274）；start/stop/send/send_delta（:332/:423/:455/:624）；python-telegram-bot 长轮询（:14 模块期导入，:414 start_polling）。
- 契约：typing 4s 循环（:1102/:1114）；媒体收发完整（下载 :843、发送 :486、相册缓冲 :1039）；topic 会话键（:803）；复合 id allow-list（:313）；配置含代理/群策略/流式间隔（:253-271）。
- 薄弱点：草稿流失败 `except: pass`（:581）；`send_delta` 裸 `int(chat_id)`（:631）；typing 循环一错即死（:1122）；依赖非官方 `bot.send_message_draft`（:569）；`_stream_bufs` 缺 end 泄漏（:697）；线程表 FIFO 1000 可能踢掉活跃 topic（:978）。

### discord — discord.py
- 入口：`DiscordChannel`（:48）；start/stop/send/send_delta（:71/:106/:122/:186）；原生 websockets 网关，无 discord.py（:91 连接，:327 事件循环）。
- 契约：typing 8s POST（:494）；媒体出 20MB `_send_file`（:281）、入 :446；intents 硬编码 37377（:44）；无会话键覆写（:459）。
- 薄弱点：无 RESUME，op7/op9 重 IDENTIFY，5s 断窗丢事件（:361-368/:104）；不校验心跳 ACK，死连接不感知（:394-402）；三处重复限速重试（:169/:259/:303）；媒体失败降级文本，manager 无从重试（:144-148）。

### slack — slack.py
- 入口：`SlackChannel`（:51）；start/stop/send（:70/:131/:141）；Socket Mode（:93-96 建 client，:110 30s 连接超时）；无 send_delta。
- 契约：无 typing，用 :eyes: 表情替代（:237）；媒体仅出（files_upload_v2 :165），入站附件完全不支持（:251-263）；双策略 allow-list `_is_allowed`（:267，DM 用 dm.allow_from、频道用 group_allow_from）；thread 会话键（:248）；message+app_mention 双投递去重（:204）。
- 薄弱点：顶层 `allow_from` 是死字段，与 base 契约背离（:45 vs :267）；`auth_test` 失败仅 warn，mention 策略下静默哑火（:105/:286）；先 ACK 后处理，失败 Slack 不补投（:185/:264）；上传失败吞掉（:172）。

### zulip — zulip.py
- 入口：`ZulipChannel`（:64）；start/stop/send（:102/:164/:184）；事件队列长轮询跑在守护线程（:156 线程，:234 循环，:487 run_coroutine_threadsafe 桥接）；zulip SDK 懒导入（:118）。
- 契约：typing 仅 DM（:815/:824）；媒体出走 executor（:762/:772）、入下载 :559/:645；复合 id allow-list（:90）；stream 会话键（:516）；mention 判定含文本回退（:521）。
- 薄弱点：async 里同步调 get_profile 与 set_typing_status 阻塞事件循环（:134/:838）；`_call_with_retry` 全异常重试+time.sleep（:216-232）；`_recipient_map` 无界增长（:483）；桥接 future 不检查（:489-499）；去重 deque 5000 溢出依赖 cursor 兜底（:406-415）。

### matrix — matrix.py
- 入口：`MatrixChannel`（:204）；start/stop/send（:235/:277/:458）；nio sync_forever 长轮询（:562）；E2EE 可选探测（:37-45）。
- 契约：typing keepalive 最完整（:519/:532）；媒体出带加密与限额协商（:394/:369）、入带解密与大小预检（:692/:713/:735）；group_policy open/mention/allowlist（:199，默认 open）；线程上下文走 metadata（:622）。
- 薄弱点：typing 异常静默吞（:529）；sync 失败无日志死循环 sleep(2)（:565）；媒体同步写盘最长 20MB 阻塞（:770）；无声明 size 时先全量下载再检查（:751/:755）；allowed 发送者邀即自动进房无上限（:568）；多处 broad except 无日志（:428/:454/:378）。

### mattermost — mattermost.py
- 入口：`MattermostChannel`（:64）；start/stop/send（:115/:170/:372）；WS 事件流（:149 连接，:230 循环）；httpx+websockets 模块期导入（:24/:27）。
- 契约：无 typing；媒体出 `_upload_file`（:423）、入 `_download_file`（:346，50MB 上限 :39）；线程会话键 `channel:reply_root`（:292）；mention 门 + 文本回退（:311/:325）；verify_ssl 可关（:61）。
- 薄弱点：50MB 全量缓冲后同步写盘（:358/:364）；`verify_ssl=False` 即 CERT_NONE，可被 MITM（:192）；mention 子串扫描会被引文里的 @username 误触发（:325）；固定 5s 重连无退避（:45/:168）；identity 获取失败每 5s 永久重试（:143）。

### msteams — msteams.py
- 入口：`MSTeamsChannel`（:107）；start/stop/send（:145/:247/:261）；内置 ThreadingHTTPServer webhook（:228 起，do_POST :180-223，run_coroutine_threadsafe 桥接 :199）。
- 契约：无 typing/媒体/流式（文本 only :287）；入站 Bot Framework JWT 校验（:483-523，JWKS 缓存 :541）+出站 client-credentials OAuth（:824-847）+trusted serviceUrl 白名单（:676）+fcntl 引用持久化（:650）；allow-list 双检（:346 + base）。
- 薄弱点：处理失败仍回 200，活动丢失永不重试（:216-223）；Content-Length 无上限，未鉴权内存 DoS 面（:187）；`validate_inbound_auth` 可配关（:166）；事件循环内阻塞 flock+fsync（:657/:783）；token 缓存 check-then-set 无锁（:824）；Windows 无 fcntl 退化为 last-writer-wins（:29）。

### email — email.py
- 入口：`EmailChannel`（:55）；start/stop/send（:98/:154/:158）；IMAP 轮询（:125-152，fetch 经 to_thread :127）；纯标准库（imaplib/smtplib :11/:13）。
- 契约：无 typing/媒体（附件显式跳过 :425）；consent 配置门（:100）；allow-list 仅靠 base 门禁，轮询本身抓全部未读（:304）；In-Reply-To/References 线程头（:197）；SMTP STARTTLS 默认上下文（:240）。
- 薄弱点：IMAP 无 socket 超时，服务端挂起即轮询静默停摆（:294/:296）；单条消息异常中断整批（:145-150）；非 SSL IMAP 明文密码（:296）；去重纯内存，`mark_seen=False` 重启重放（:363）；发件人/主题原文拼接进模型输入（:338）。

### mochat — mochat.py
- 入口：`MochatChannel`（:276）；start/stop/send（:319/:347/:374）；Socket.IO 主路（:478-493）+HTTP 长轮询兜底（:696/:715）；python-socketio 可选（:21-34）。
- 契约：无 typing/媒体（媒体引用折进正文 :380）；claw_token 双载体（HTTP 头 :1035 + socket auth :504）；session 游标持久化（:992）；群回复延迟缓冲（:830）；self-message 抑制（:792）。
- 薄弱点：send 全吞异常（:409），manager 重试失效；面板路无持久游标，重启重放 watch_limit 条（:307/:719）；0.5s 防抖+同步写盘（:981/:1009）；关停丢弃缓冲中的延迟回复（:355/:919）；`_target_locks` 无界（:315）；socketio/msgpack 缺失静默降级（:431）。

### dingtalk — dingtalk.py
- 入口：`DingTalkChannel`（:116）；start/stop/send（:152/:213/:498）；Stream Mode WS（:181-186，重连循环 :191-203）；dingtalk-stream 模块期 try 导入（:21-38）。
- 契约：无 typing；媒体下载（:272）与上传（:314，token 走 URL query :324）；唯一手动管 token 的通道——`_get_access_token` 缓存+60s 提前刷新（:225/:246）；群/单聊 chat_id 前缀区分（:385/:535）。
- 薄弱点：send 全程不 raise（:500/:402），manager 重试失效；token 刷新无锁可竞态（:227）；handler 解析失败仍 ACK OK（:101）；client_secret 明文（:112）；AsyncClient 无显式超时（:175）。

### wecom — wecom.py
- 入口：`WecomChannel`（:39）；start/stop/send（:67/:124/:365）；SDK WSClient 长连（:94-100，SDK 内无限重连 1s 间隔）；wecom_aibot_sdk 懒导入（:88）。
- 契约：无 typing（reply_stream 一次性流式回复当 UX，:391）；媒体仅入（:331，SDK AES 下载 :345），且路径折进正文 `[Image: …]`（:254/:280）出站媒体不支持；`_chat_frames` LRU 1000 存回复路由（:65/:307）；token 全托管给 SDK。
- 薄弱点：frame 淘汰/重启后 send 静默丢回复（:382-385，与 docstring :368 矛盾）；SDK 错凭据 1s 紧密死循环（:97）；同步写盘（:357）；secret 明文（:25）；媒体路径混入文本易与用户内容混淆（:316 传 media=None）。

### weixin — weixin.py
- 入口：`WeixinChannel`（:136）；start/stop/send/send_delta（:343/:390/:943/:1078，delta 仅缓冲工具提示）；iLink HTTP 长轮询（:366-388，getupdates :444，游标持久化 :472）；纯 httpx（:27）。
- 契约：typing 票据制+5s keepalive（:787/:918/:1090）；媒体收发完整且 AES-ECB 加解密（入 :688/:759、出 :1180/:1223）；context_token 60s 提前刷新（:829）；errcode -14 会话暂停（:407）；QR 登录拆到 weixin_qr.py。
- 薄弱点：token/票据/context_token 明文写 account.json（:239/:518/:881）；stop() 取消从未赋值的 `_poll_task` 是 no-op（:394），暂停 sleep 最长 3600s 拖住停止（:432）；事件循环内同步文件 IO（:205/:245/:776）；`hash()` 文件名跨重启漂移（:770）；无 context_token 时工具提示直接丢（:906）。

### weixin_qr — weixin_qr.py（协议库，非通道）
- 入口：无 BaseChannel 子类，registry 判 `NotAChannelModule` 跳过（registry.py:86；测试确认 tests/services/partners/test_weixin_channel.py:127）；供 deeptutor/services/partners/weixin_onboarding.py:34 消费。
- 契约：QR 生成/单次轮询/状态判定三分（fetch_qr_code :140、poll_qr_code :162、interpret_status :101）；`scaned_but_redirect` 换 host 续轮（:127）；qr_headers 故意不带 Authorization（:74）。
- 薄弱点：payload 里明文 bot_token（:118）；`normalize_host` 原样接受 http://，可被降级（:96）；无总时限，靠调用方超时（:108）。

### napcat — napcat.py
- 入口：`NapcatChannel`（:60）；start/stop/send（:88/:167/:445）；OneBot v11 WS（:119-165，帧分发 :199）；websockets+aiohttp（:24/:21）。
- 契约：无 typing；仅图片——出 `base64://` 或 URL 引用（:477），入带 SSRF 防护+重定向拒绝+流式字节上限（:533/:554/:564）；access_token Bearer（:120）；echo/response 与事件双路分发（:209/:223）。
- 薄弱点：默认 `ws://` 明文传 token（:48）；群回复随机概率不可复现（:379）；handler 异常仅 done-callback 记录，失败不上抛（:236）；2000 去重 deque 溢出重放旧 id（:80）；握手期帧已当事件处理（:159）。

### qq — qq.py
- 入口：`QQChannel`（:65）；start/stop/send（:85/:128/:138）；qq-botpy WS 网关（:15-24 try 导入，handlers :30-52，`client.start` :117）；token 全在 SDK 内。
- 契约：无 typing/媒体/流式，纯文本/markdown（:150/:180）；allow-list 走 base（:196）；chat_type 靠内存缓存区 c2c/group（:83/:160）。
- 薄弱点：client 缺失时 send 静默返回，与自身 docstring（:141）及 base 契约（base.py:162）矛盾（:143）；重连无退避上限，坏凭据 5s 死循环（:112）；重启后 chat_type 默认 c2c 误路由（:160）；secret 明文（:60）；`_chat_type_cache` 无界（:83）。

### whatsapp — whatsapp.py
- 入口：`WhatsAppChannel`（:27）；start/stop/send（:50/:96/:106）；连本地 Node 桥（baileys，:31 文档）WS（:75 监听）；websockets 懒导入（:52）。
- 契约：无 typing；媒体仅入且由桥下载（:159），send 纯文本（:116）；QR 事件→`set_setup_state` 出码（:200）；bridge_token 作为首条 WS 消息鉴权（:66）；pn/LID 双身份并存（:131）。
- 薄弱点：无消息签名校验，未配 token 时可达桥的对端即可注入消息（:66 无强制）；断线时 send 仅 log 不 raise（:112，与 docstring :108 矛盾）；`ws.send` 无超时（:117）；固定 5s 重连（:94）；连接后状态误标 connecting（:72）。

### feishu — feishu.py（2459 行，通道里最重）
- 入口：`FeishuChannel`（:396）；start/stop/send/send_delta/consume_stream_delivery（:480/:638/:2115/:1615/:466）；lark-oapi WS 长连跑在专属线程+私有 loop（:553-611），CARD 帧经 monkey-patch 进分发（:32/:41-74）；SDK 懒导入（:501）。
- 契约：typing 双机制（working 表情 + 可撤回"思考中"，:831/:1344）；媒体收发最全（入 :1164/:1194/:1231，出 :1103/:1130，分发 :2265）；卡片流式+终局确认抑制普通重发（:1615/:466）；encrypt_key/verification_token 交 SDK 校验（:530）；card 回调复检 allow-list（:2027）；lark_http keep-alive（:504）。
- 薄弱点：所有 SDK 调用 run_in_executor 无超时，挂起即占死池线程（:841/:1248/:1641/:2254）；send 吞一切异常，manager 重试失效（:2322，违背 base.py:162）；`_stream_bufs` 缺 end 泄漏（:1635）；card 帧 `do_without_validation`（:60）；app_secret/encrypt_key 明文（:315）；入站媒体同步写盘（:1267）。

## 5. 横向共性问题（修卡切入点索引）

1. **raise-on-failure 契约形同虚设**：feishu:2322、dingtalk:500、wecom:382、qq:143、whatsapp:112、mochat:409 全吞异常 → `send_with_retry`（channels/manager.py:155）对这六家永不生效；真正生效的是 telegram/napcat/matrix/weixin。
2. **流缓冲泄漏**：telegram:697、discord:215、feishu:1635 的 `_stream_bufs` 无 TTL，`_stream_end` 丢失即泄漏；建议在 manager 或 base 层统一加过期清理。
3. **事件循环内阻塞**：zulip:134/:838、msteams:657/:783、matrix:770、mattermost:364、wecom:357、weixin:205/:776 —— 修复模式参考 dingtalk.py:307（asyncio.to_thread）与 zulip.py:772（executor）。
4. **重连策略不统一**：固定 5s 无 jitter（discord:104、mattermost:168、qq:126、whatsapp:94）、zulip 用阻塞 time.sleep（:229）、wecom 在 SDK 内 1s 死循环（:97）；可收敛为共享退避工具。
5. **去重/游标内存态**：email:363、napcat:80、qq:83、whatsapp:139、mochat:307 重启即丢导致重放；feishu:442、wecom:62、weixin:472 已有持久化可参考。
6. **allow-list 语义四派**：base（base.py:193）、复合 id（telegram:313、zulip:90）、双策略自定义且顶层字段失效（slack:45 vs :267）、group_policy+概率（napcat:368、mochat:265）；修权限类卡先确认走的是哪派。
7. **明文凭据落盘是常态**：全部通道 config/state 明文（feishu:315、dingtalk:112、wecom:25、weixin:239、msteams:75、matrix:192 等）；`repr=False` 只是显示遮蔽；相关既有防线见 tests/services/partners/test_channel_secrets.py。
8. **收发公共面**：改重试→manager.py:155；改流合并→manager.py:46；改去重→manager.py:382；改发现/插件→registry.py:27；typing 参考实现 matrix.py:532；SSRF 参考 deeptutor/partners/network.py:59；分段 helpers.py:42。

## 6. 测试覆盖对照

- `tests/services/partners/`：公共面齐全——manager（test_channel_manager）、流式（test_channel_streaming）、投递（test_partner_outbound_delivery）、setup 状态（test_channel_setup_status）、onboarding（test_channel_onboarding、test_weixin_onboarding）、迁移（test_channel_state_migration）。
- 单通道测试：telegram（3 个文件）、feishu（7 个）、zulip、mattermost、msteams、napcat、wecom、weixin、whatsapp。
- 无专属测试：**slack、discord、matrix、email、dingtalk、qq、mochat** 七家——改这些通道目前只能靠公共面回归兜底，修卡时建议先补最小回环测试。
- `tests/partners/`：helpers 纯函数 4 个文件（分段/表格/MIME 无关，均为 markdown 表格与文件名）。
