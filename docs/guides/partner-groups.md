# DeepTutor partners 群聊域（Partner Groups）导读

- 基线：origin/main @ `6cf793bd8`（v1.6.14）。锚点 `path:line` 相对仓库根，行号随演进漂移，以符号名为准。
- 范围：群聊全链路——后端轮次编排（`deeptutor/services/partner_groups/` + 群入口 `api/routers/partner_groups.py`）与前端座位/提及（`web/components/partners/group/`）；含群会话存储、群草稿与导出。
- **去重边界**：单 Partner 生命周期归 guide-services-partners（其 §2 已有 partner_groups 模块地图）；通道矩阵归 guide-partners-channels / guide-partner-channels。本文不重复模块清单，只写群聊运行时契约：轮次调度、帧协议、座位排序、存储布局与预算。

## 1. 一轮群聊的时序

```
用户消息(REST 或 WS) → PartnerGroupManager.send_message
  ├─ _member_snapshot 冻结成员+别名 → resolve_mentions 定发言座位集合
  ├─ user_message 落盘转录 → render 公开上下文(名册+历史+白板)
  ├─ discussion_mode.run(respond, mode_emit)   ← 调度差异全在 modes.py
  │     └─ respond(partner_id) → _run_partner_reply
  │           └─ PartnerManager.send_group_message（persist=False 的私有轮）
  │                 └─ PartnerRunner.process_message（复用产品聊天 TurnEngine）
  └─ mode_emit: partner_message 帧到达时才把该座位落盘 → GroupTurnResult + done
```

- 编排器无状态单例（`services/partner_groups/manager.py:1633`），进程内只持调度态：`_consultations/_live_turns/_completed_turns`（`manager.py:133-137`）；持久数据每次经请求上下文的用户目录解析（`manager.py:1619-1622` 注释）。
- 群轮不建 agent 循环：`services/partners/manager.py:1204` `send_group_message` 以 `channel="web_group"` 发 `InboundMessage`（`:1233-1241`），`PartnerTurnOptions(persist=False, allow_commands=False, capture_events=False, shared_context=public_context)`（`:1264-1274`）——伙伴私有会话历史不被群轮污染；群可见结果只有最终文本 + events + `tool_metadata.partner_invocation` 提案（`:1250-1257`）。

## 2. 后端轮次调度

### 2.1 同步轮 `send_message`（`manager.py:388`）

- 座位确定：显式 `mentions` 参数优先，为 `None` 才解析正文 `@token`（`:1207-1212`，正则 `:43`）；别名表 = id+name 双 casefold（`_member_snapshot` `:1522-1541`）；`@all/所有人/全部`→全员（`:1217`）；未知 token 收进 `unknown_mentions` 作提示不失败（`:1218-1224`）；全部未命中回退 @all 语义（`:1235-1236`）。
- 转录落盘时机：用户消息立即 append（`:428`）；伙伴消息只在 `mode_emit` 收到 `partner_message` 帧时才 append（`:466-473`）——`pending_messages` 保证"先有结果再上墙"。
- 单座位失败折叠为 `error=True` 的 GroupMessage，不拖垮全场（`_run_partner_reply` `:1325-1337`）；`allow_invoke_other`/`extra_context`/`instruction` 由模式逐座位注入。

### 2.2 Live 轮与断线重放（`LiveGroupTurn` `manager.py:78`）

- 帧进缓冲 + 订阅者队列；缓冲 ≤512 帧（`:41,:98`），`done/error/cancelled` 置终态（`:100`）；`subscribe()` 先重放历史再挂队列（`:105-111`）——刷新页面即完整重放。
- 四种入口都走"幂等重用"：`start_live_turn :857`（同 content+mentions 才复用，否则拒绝双轮 `:874-877`）、`start_live_invocation :911`、`start_live_retry :970`、`start_live_summary :1030`；键 = `(owner, group, session, operation)`（`_live_key :1152`）。
- 终局归档：done callback 把轮移入 `_completed_turns` LRU ≤64（`_track_live_turn :1165,:1192`）；取消先于协程处理器时同步补 cancelled 帧（`:1180-1188`）。`subscribe_live_turns :1098` 返回全部 active，否则最新一条 completed 作重放。
- `cancel_live_turn :1108` 取 started_at 最新的未完任务；message 操作补写 `round_stopped` 系统标记，让"已停止"在刷新后仍在（`:1135-1147`）。

### 2.3 WS 帧协议（`api/routers/partner_groups.py:338`）

- 下行帧 8 种：`user_message / partner_started / partner_trace / partner_message / invocation_updated / done / cancelled / error`（emit 调用点见 manager；前端联合类型 `useGroupSession.ts:79-93` 一一对应）。`partner_trace` 是 owner 可见、speaker-scoped 的私有推理（过滤 DONE/SESSION `manager.py:1272-1273`），**永不落盘、不进公共上下文、不给 peer**（WS docstring `:340-344`）。
- 上行 action：`attach :420`（幂等重挂重放）、`create_invocation :424`、`approve_invocation :438`、`reject_invocation :448`、`retry_partner :460`、`summarize_round :471`、`cancel :482`、`consultation_activity :408`；其余按消息 schema 校验 `:501-516`。
- 帧推送在独立 task（`:517-519`），接收循环在伙伴运行中仍可审批/取消。鉴权 `ws_require_auth :349`，组不存在 close 4404（`:355`）。

### 2.4 续作三兄弟与审批链

- `retry_partner :564`：只允许失败座位（`_require_retry_target :1340,:1362-1363`）；对着原公开快照重跑，`transcript.replace` 原位换行且保 `event_id`（`:613` → `store.py:183-211`）。
- `summarize_round :491`：`_require_summary_round :1366` 校验成员资格、轮存在、轮已完（`:1380-1389`）；排除 `round_summary/round_stopped`（`:1393`）；三段式指令 Consensus/Disagreements/Recommendation（`:45-50`）；`allow_invoke_other=False`（`:545`）。
- 审批链：伙伴侧 `partner_invocation` 元数据只是提案；`_create_invocation :1396` 在编排信任边界再校验（requester/target 都须在成员内、不得相同、question ≤2000 字 `:1439-1459`）。`approve_invocation :631`：transition 允许 `{pending, approved}` 以支持进程重启恢复（`:652-655`）；问题以 `invocation_question` 气泡公开（`:674-688`）；被点名者的回答可再提案，但**每跳都要用户显式批准**（`:751-753`）。持久状态机 CAS 见 §4。

### 2.5 发言模式调度差异（`modes.py`）

| 模式 | 调度 | 关键契约 |
| --- | --- | --- |
| `panel_parallel` `:63` | `asyncio.gather` 并行（`:80`） | 各座位同快照独立作答，私有中间过程不共享 |
| `sequential` `:83` | 按 `group.member_ids` 顺序串行（`:100-102`） | 每座位注入"本轮已发言" `extra_context` + 不重复指令（`:92,:106-110`） |
| `debate` `:116` | 开篇并行→交锋并行（`:146,:173`） | targets<2 跳过交锋（`:154-155`）；交锋 `allow_invoke_other=False`、kind=`debate_rebuttal`（`:167,:169`） |

- 注册表 `discussion_mode_registry`（`:181-184`）可插拔；`DiscussionMode` 协议 `:33`，`respond` 闭包协议 `GroupResponder :14`。

### 2.6 公共上下文组装（什么进 prompt）

- `_render_public_context :1543` = 成员名册（name+@id+description）+ "此前公开转录" + "用户策展白板"；转录渲染有硬预算（§4.1）。
- 逐座位叠加：`_append_round_context :57`（heading `:44`）注入模式生成的本轮前文；`_append_partner_instruction :64` 用 `<upcoming_partner_turn_requirement>` 标签（`:70`）把 instruction 限定到该成员下一轮。

## 3. 座位 / 提及（前端 `web/components/partners/group/`）

### 3.1 rounds + seats 模型（`useGroupSession.ts`）

- 转录按"轮次 + 固定座位"建模而非平铺消息列表（模块 docstring `:3-14`）：并行 panel 的 N 个回答读作一轮；每个发言块从"思考中"到"已回答"是同一个 DOM 节点（`PartnerSeat.tsx:27-38`），长 panel 不跳版。
- 帧消费：`user_message` 用后端解析好的 `mentions` 预建全部座位（`:180-191`）；`partner_started` 在无 user 消息时创建 followup 轮（`:196-213`）；`partner_trace` 乐观累积正文，retraction 到达时按事件重算（`growBody :104-111`，与产品聊天同一套 `lib/stream` 规则）；`partner_message` 移除 live 座位（`:244-249`）；`invocation_updated` 对用户发起的 askPeer 自动批准（`autoRunRef :134,:252-271`——用户就是批准人）。
- 历史先落地再 `attach`，让挂载前已开跑的轮重放进来（`:160-164`）；线程切换以 `sessionKey` 声明式退役 live 轮（`:120-122`）。

### 3.2 排序契约：座位序跟成员表，不跟到达序

- `seatRank :400-403`：按 `group.member_ids` 稳定排序（到达序只是 asyncio 调度噪声）。
- `passRank :415-424`：`round_summary`=2、`debate_rebuttal`=1、普通=0；live 座位无消息，按该发言人已落地条数推 pass——debate 同一发言人出现两轮时不会被交错（A 开篇、A 交锋、B 开篇…）。
- followup 轮保持时序（问→答顺序即语义），只有 panel 轮做座位排序（`:430-431`）。

### 3.3 提及双端协议（`mentions.ts` + `resolve_mentions`）

- 前端 composer 自己把 @token 解析成 partner ids **显式发送**，不让后端重解析散文（`mentions.ts:3-9`）：带空格的显示名靠对名册做最长别名贪心扩展（`:68-77`）；未知 token 是 composer 里的黄色提示而非 422（`:78`，UI `GroupComposer.tsx:162-168`）。
- `completeMention :119` 插入显示名（用户读的是名字），ids 随消息显式附上。后端对 `mentions=null` 仍保正则兜底（§2.1）；三值语义在 `GroupComposer.tsx:108-112`：`everyone→[]`、有 targets 发 ids、否则 `null` 交后端解析。
- composer 契约：轮运行中 textarea 永不禁用（可预写下问，`GroupComposer.tsx:26-33`）；@ 列表打开时 Enter 归列表（`:218-227`）；引用发言前置为 markdown 引用、正文截 400 字（`:104-107`）。

### 3.4 群草稿：composer 草稿态 + 咨询静默窗

- composer `onDraftChange` 上报"有无草稿"（`GroupComposer.tsx:61-63`）；`PartnerGroupChat.tsx:87-106` 节流 200ms 转发交互、2s 心跳只续租不算活跃。
- 后端 `consultation.py`：输入静默 `IDLE_SECONDS=10`（`:7`）+ 草稿租约 `DRAFT_LEASE_SECONDS=6`（`:8`）；`remaining(busy, revision) :28` 在 busy/有人在打字/revision 变化时重置静默起点（`:33-37`）。消费方是 home-chat 咨询桥（§4.3），普通群聊页面不逐字触发。

## 4. 存储与导出

### 4.1 目录布局（`store.py`，全部用户隔离 + 原子写 + per-path 锁 `:29-32`）

```
<用户根>/partner_groups/<group_id>/          group_id 白名单 ^[a-z0-9][a-z0-9_-]{0,79}$（:21）
  config.json                                PartnerGroupStore :54；list 跨目录扫描在此过滤 owner（:61-70）
  sessions/<key>.jsonl                       GroupTranscriptStore :123；key 清洗 ≤120（:303-306）；append-only
  invocations/<hex32>.json                   PartnerInvocationStore :309；transition 是 allowed 集合 CAS（:355-384）
  shared/whiteboard.jsonl                    WhiteboardMemory（memory.py:72）；pin 去重、unpin 写墓碑行
```

- 转录预算：`PUBLIC_TRANSCRIPT_MAX_MESSAGES=40 / MAX_CHARS=16_000`（`store.py:25-26`）；`render()` 最新一条保底、旧消息倒序纳入直到上限（`:229-243`）；`render_before_turn :213` 供 retry/summary 复现原快照。
- 白板：append-only + 墓碑（`memory.py:110-127,:176`）；v1 行（自动复制时代）留盘但排除（`:155-159`）；注入 prompt 上限 80 条/16k（`:134`）。
- 会话列表摘要取首条 user 消息前 40 字为题（`store.py:245-279`）；空文件 key 不可逆，只认本进程创建的（`:260-265`）。

### 4.2 导出管线（前端）

- 页头 Download（`web/app/(workspace)/partners/groups/[groupId]/page.tsx:60-63`）只导出**已落盘**消息：`PartnerGroupChat.tsx:80-85` 把 settled transcript 上提，线程加载中清空防串线程。
- 适配器 `web/lib/partner-group-export.ts:11-24`：`partner→assistant` 并保留各伙伴显示名（panel 讨论离开应用仍可归因），过滤 `round_stopped` 标记；交给共享导出器 `downloadChatMarkdown`。
- 会话 key 是**每浏览器** localStorage：`deeptutor:partner-group:{gid}:session`（`web/lib/partner-groups-api.ts:198-206`，新建 `:251-255`）；会话 CRUD 走 REST `:216-239`。

### 4.3 home-chat 咨询桥与转录引用

- `deeptutor/services/subagent/partner_group.py:13` `PartnerGroupBackend.consult`：home chat 咨询一个群——`mentions=全员` 开轮（`:36-41`），0.25s 轮询 `remaining`（`:88`），busy=任一 live 任务或 pending/approved invocation（`:51-53`），revision=事件 id+审批状态元组（`:54-57`）；归零封快照（`:66-68`），返回**全部公开转录+审批决定**、私有推理不入（`:93-102`）；父轮取消级联杀 live 任务（`:110-116`）。capability 注册在 `deeptutor/capabilities/registry.py:84`。
- 反向：`referenced_transcript`（`manager.py:354`）把群转录作为 home-chat 引用源，带双语免责 header 与 16k 预算（`:369-386`）。

## 5. 关键不变量（改代码前先对照）

1. 公开转录只有 user/partner 两类消息；`partner_trace` 永不落盘、不进任何 prompt、不跨座位可见。
2. 群轮内伙伴私有轮 `persist=False`——群历史与伙伴单聊历史互不污染（`services/partners/manager.py:1264-1274`）。
3. 伙伴消息"先出结果再上墙"：`partner_message` 帧驱动落盘（`manager.py:466-473`）。
4. 提案≠执行：跨伙伴提问每跳都要显式批准，重启后 approved 可恢复（`:652-655`）。
5. 同会话 live 轮互斥：content+mentions 不同即拒绝重入（`:874-877`）；删除会话前检查无在跑轮（`:344-346`）。
6. 转录渲染 40 条/16k 是绝对上限、最新一条保底；座位排序前端按成员表+passRank，后端不改语义。
7. 失败座位可 retry 且保 `event_id`；总结要求轮完整且未在跑。

## 6. 验证面

- 后端：`tests/services/partner_groups/test_manager.py`（1417 行）、`test_consultation_idle.py`、`tests/api/test_partner_groups_router.py`（650 行）、`tests/capabilities/test_partner_group_capability.py`。
- 前端：`web/tests/partner-group-export.test.ts`、`web/tests/partner-group-export-session.spec.tsx`。
