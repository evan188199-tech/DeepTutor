# ask_user 全链路导读（发起 → 停车 → 恢复 → 续答）

- 基线：origin/main `f07029cfc`（v1.6.13）。所有 `path:line` 均在该基线逐一核对；行号会随演进漂移，以符号名为准。
- 范围：`ask_user` 工具的完整生命周期 —— 模型发起（含流式卡片预览）→ 会话回合停车（`waiting_input` 状态机）→ API 事件下发（WS 协议与命令确认）→ web 卡片渲染 / 重载恢复 / 续答回灌。
- 去重说明：会话历史与内存轴见 guide-session；`ask_user_trace` 观测面（AGEN-936）与 `ask_questions` capability loop 契约（AGEN-794）是相邻但独立的轴，本文只在相关处点到；前端整体状态层见 guide-web-state。
- 热点说明：§7 给出对应上游 #1359、#1788 报告区域的中性代码锚点（只定位、不含任何复现细节）；§8 记录截至 2026-10-07 的上游关联 PR 状态。

## 1. 参与者与关键文件

| 角色 | 文件 | 关键符号 |
| --- | --- | --- |
| 工具 payload 构建/校验 | `deeptutor/tools/ask_user.py:102` | `build_ask_user_payload`（流中预览版 `ask_user.py:160` `build_ask_user_preview`） |
| 工具本体 | `deeptutor/tools/builtin/__init__.py:1493` | `AskUserTool`（`get_definition` `builtin/__init__.py:1507`，`execute` `builtin/__init__.py:1611-1634`；注册名表 `builtin/__init__.py:1948`、导出 `builtin/__init__.py:1987`） |
| 暂停语义 | `deeptutor/core/tool_protocol.py:146-153` | `ToolResult.pause_for_user` |
| 并行派发与暂停聚合 | `deeptutor/runtime/agentic/tool_dispatch.py:122` | `dispatch_tool_calls`（`PAUSE_LAST_TOOLS` `tool_dispatch.py:55`，pause 捕获 `tool_dispatch.py:907-914`） |
| 卡片流式预览发射器 | `deeptutor/agents/loop/ask_user_drafts.py:102` | `AskUserDraftEmitter`（trace 常量 `ask_user_drafts.py:42`） |
| 通用 agentic 循环 | `deeptutor/runtime/agentic/loop.py:209` | `run_agentic_loop`（pause 分支 `loop.py:366-371`） |
| 聊天循环宿主 | `deeptutor/agents/loop/agent_loop.py:703` | pause → 续答分支 |
| 等待/回灌编排 | `deeptutor/agents/loop/pipeline.py:1184` | `_await_user_reply_and_resolve`（hook 分发 `pipeline.py:1155`） |
| 回合执行器（停车队列） | `deeptutor/services/session/turns/executor.py:183` | `_wait_for_user_reply`（队列注册 `executor.py:176-181`，runtime 注入 `executor.py:912`） |
| 回合生命周期/命令消费 | `deeptutor/services/session/turns/lifecycle.py:325` | `submit_user_reply`（`_coordinate_execution` `lifecycle.py:228-299`，终态 CAS 兼容 `lifecycle.py:193-226`） |
| 应用服务入口 | `deeptutor/app/service.py:320` | `submit_user_reply`（`check_active_turn` `app/service.py:249`，僵尸回收 `app/service.py:349-458`） |
| WS 路由 | `deeptutor/api/routers/unified_ws.py:305` | `submit_user_reply` handler（`check_active_turn` `unified_ws.py:260-276`） |
| 线协议契约 | `deeptutor/api/contracts/turn_protocol.py:127` | `SubmitUserReplyCommand`（状态枚举 `turn_protocol.py:16-34`，事件类型 `turn_protocol.py:47-62`，ACK `turn_protocol.py:203-211`） |
| 持久层 CAS | `deeptutor/services/session/sqlite_store.py:1521` | `transition_turn`（活跃回合查询 `sqlite_store.py:1416/1435`） |
| 领导者恢复 | `deeptutor/runtime/coordination/recovery.py:25` | `TurnRecoveryService.recover_once` / `_recover_turn` `recovery.py:45` |
| web 卡片状态机 | `web/lib/ask-user-state.ts:82` | `pendingCards` / `hasPendingAskUser` `ask-user-state.ts:134` |
| web 工具元数据解包 | `web/lib/tool-event.ts:50` | `toolResultPayload` |
| web 卡片组件 | `web/components/chat/home/AskUserOptions.tsx:919` | `AskUserOptions`（payload 提取 `AskUserOptions.tsx:137`，分段 `AskUserOptions.tsx:313`，交互卡 `AskUserOptions.tsx:967`） |
| web 提交编排 | `web/features/chat/ChatStateAdapter.tsx:3115` | `submitUserReply`；composer 旁路 `web/features/chat/components/ChatWorkspace.tsx:1913-1925` |
| web 传输层 | `web/features/chat/transport/TurnRuntimeClient.ts:317` | `command_ack` 处理（`active_turn_info` `TurnRuntimeClient.ts:341`，重连 `TurnRuntimeClient.ts:404-411`） |

## 2. 发起：模型调用 ask_user 与卡片流式预览

1. **工具执行**：模型在 `TOOL` 标签轮次发出 `ask_user` 调用，`AskUserTool.execute`（`builtin/__init__.py:1611`）把参数交给 `build_ask_user_payload`（`tools/ask_user.py:102`）做规范化：1-4 个问题、每题去重/截断选项（`ask_user.py:269-298`）、legacy `{question, options}` 形态包装（`ask_user.py:154-156`）、半写入 options 丢弃（`ask_user.py:217-235`）。成功时返回 `ToolResult(metadata={"ask_user": payload}, pause_for_user=payload)`（`builtin/__init__.py:1625-1634`）——占位 content 会在续答时被替换（`builtin/__init__.py:1626-1631` 注释）。
2. **流式预览**：卡片参数是模型逐 token 写出的 JSON，聊天循环为 `ask_user` 单独挂 `AskUserDraftEmitter`（`agent_loop.py:1115-1128`），在参数增量到达时调用 `observe`（`agent_loop.py:1253-1256`、`agent_loop.py:1348-1352`），轮末 `settle` 补发最终帧（`agent_loop.py:1483-1487`）。发射器节流（≥24 字符且 ≥0.18s，`ask_user_drafts.py:59-63`）并拒绝会"收缩卡片"的中间帧（`ask_user_drafts.py:84-98`），以 `progress` 事件携带 `trace_kind="ask_user_draft"` + `ask_user_draft` payload 下发（`ask_user_drafts.py:160-173`）。预览只是渲染提示，真正执行的调用仍由完整参数走普通路径（`ask_user_drafts.py:22-24`）。
3. **派发与暂停聚合**：`dispatch_tool_calls` 并行执行同轮工具调用；`ask_user` 属于 `PAUSE_LAST_TOOLS`（`tool_dispatch.py:55`），在轮内后置绑定参数（`tool_dispatch.py:305/374/405`），同批重复的 pause 调用折叠为一条（`tool_dispatch.py:164-176`）。结果装配阶段第一个携带 `pause_for_user` 的结果置 `pause/pause_payload/pause_tool_call_id`（`tool_dispatch.py:907-914`），其余工具结果照常随行（`tool_dispatch.py:105-108`）。

## 3. 停车：waiting_input 状态机

1. **循环停车点**：通用循环在 pause 时调用 `host.resolve_pause`（`runtime/agentic/loop.py:366-371`）；聊天宿主对应 `agent_loop.py:703-715`，未恢复则 `LoopOutcome(completed=False)` 结束本次协程但回合任务仍存活。
2. **等待编排**：`pipeline._await_user_reply_and_resolve`（`pipeline.py:1184`）先广播 `on_user_pause` hook（`pipeline.py:1192`，能力协议见 `capabilities/protocol.py:76`，分发实现 `pipeline.py:1155-1182`），然后 `raw_reply = await waiter()`（`pipeline.py:1205`）；无 waiter（如无 runtime 的入口）降级为终止消息（`pipeline.py:1194-1203`）。
3. **回合停车**：waiter 是执行器在启动回合前注册的 `_wait_for_user_reply`（队列创建并登记 `executor.py:176-181`，注入 `TurnRuntimeContext.wait_for_user_reply` `executor.py:912`；字段定义 `deeptutor/core/context.py:54`）。进入等待时先做持久 CAS：`transition_turn(turn_id, "waiting_input", expected_status="running", fencing_token=…)`（`executor.py:186-193`，存储实现 `sqlite_store.py:1521`），失败即租约丢失；成功后在 `reply_queue.get()` 上挂起（`executor.py:199`）。
4. **状态回滚**：`finally` 里用 `asyncio.shield` 把回合 CAS 回 `running`（`executor.py:200-217`），保证后续循环或取消路径的终态写入有合法前驱。终态写入因此同时接受 `running`/`waiting_input` 两个前驱（`lifecycle.py:193-226`，注释点名 #1297/#1359 的锁死形态）。
5. **副作用**：`waiting_input` 与 `queued`/`running` 同属"活跃回合"——`_begin_turn` 据此拒绝同会话新回合（`sqlite_store.py:1357` 起；活跃集合见 `sqlite_store.py:1416-1435`），前端重载时也能从 `active_turns` 读回（§6）。停车期间任务不发事件，因此"是否存活"只能看租约续约，不能看行年龄（`app/service.py:359-364`）。

## 4. 下发与提交：API 事件与 WS 命令

1. **线协议**：状态机常量 `TurnStatus.WAITING_INPUT` / `TurnQueryState.WAITING_INPUT`（`turn_protocol.py:16-34`）；`SubmitUserReplyCommand`（`turn_protocol.py:127-139`，`text` 或 `answers[{questionId,text}]` 至少其一）；回执 `CommandAckEvent`（`turn_protocol.py:203-211`），拒绝码如 `turn_not_waiting_input`。
2. **WS 入口**：`unified_ws.py:305-326` 处理 `submit_user_reply`，转发 `turns.submit_user_reply(...)` 并按结果回 ACK；`check_active_turn`（`unified_ws.py:260-276`）返回 `active_turn_info{turn_id,status,owner_id}`，无租约时报 `recovering`（`app/service.py:249-261`）。REST 侧 `GET /api/sessions/{id}` 附带 `active_turns`（`deeptutor/api/routers/sessions.py:487-491`）。
3. **应用层**：`app/service.py:320-347` 先验证回合存在与租约归属：无租约的 `waiting_input` 行按僵尸同步回收（`app/service.py:331-340` → `_reap_unowned_live_turn` `app/service.py:391-458`，写 `worker_lost` error+done 终态事件）后拒绝；有租约则把 `submit_user_reply` 作为命令提交给协调器（`app/service.py:341-346`），幂等键 `command_id` 随行。
4. **命令消费**：租约持有方的 `_coordinate_execution` 循环读命令（`lifecycle.py:241-244`）：`submit_user_reply` 转投内存队列（`lifecycle.py:249-254` → `lifecycle.py:325-352`，`queue.put` `lifecycle.py:350-352`）；投递失败（waiter 已不存在）且持久态仍是 `waiting_input` 时取消本执行、补终态流（`lifecycle.py:255-277`）。`user_input` 是兄弟通道：投递给 `StreamBus.submit_input`，供能力级 `wait_for_input`（`lifecycle.py:278-283`、`deeptutor/runtime/stream_bus.py:312-348`）——这是 `mastery` 等能力内嵌问答用的另一条机制，不是聊天 `ask_user` 主链。

## 5. 续答：答案回灌与回合继续

1. **回灌**：`raw_reply` 到达后先广播 `on_user_resume` hook（`pipeline.py:1209-1216`），再发一条 `trace_kind="user_reply"`、`ask_user_resolved=true`、`ask_user_tool_call_id` 的 progress 事件（`pipeline.py:1219-1232`）——这是前端把卡片翻到 resolved 态的信号（§6）。`_normalise_user_reply`（`pipeline.py:125`）拆出 `reply_text` 与结构化 `answers`，`_format_user_reply_body`（`pipeline.py:144`）渲染成给模型看的正文，附"继续完成原请求"指令（`pipeline.py:1253-1260`），并整体替换到对应 `role=tool` 消息的 content（`pipeline.py:1263-1266`）。
2. **循环继续**：替换完成后返回 `True`，聊天循环 `continue` 进入下一轮（`agent_loop.py:713-715`），模型以普通工具结果的形式读到答案；回合状态已在 waiter 的 `finally` 里 CAS 回 `running`（`executor.py:205-217`）。
3. **放弃/终止**：`raw_reply is None`（取消或运行时不支持等待）→ `completed=False`（`pipeline.py:1206-1207`、`runtime/agentic/loop.py:368-370`）；`context.interaction.end_loop` 这类中性停止信号跳过后续 LLM 轮（`pipeline.py:1234-1238`）。用户在 composer 按 Stop 则整回合取消（`builtin/__init__.py:1503-1504` 描述的入口）。

## 6. 恢复：重载重建与跨进程恢复

1. **事件持久化**：执行器把本轮所有流事件（含 `tool_result`，其 metadata 内嵌 `tool_metadata.ask_user`）写进 assistant 消息的 `events` 列表并盖内容偏移戳（`executor.py:1007-1023`），这是重载后卡片还在的唯一依据。
2. **前端读回**：`loadSession`（`ChatStateAdapter.tsx:2423`）经 REST 取回消息与 `active_turns`（`sessions.py:487-491`），`activeTurnId` 取自 `active_turns[0]`（`ChatStateAdapter.tsx:2432-2434,2497`）；`resolveLoadedRunStatus` 对陈旧 `running` 做保鲜判断（`ChatStateAdapter.tsx:2455-2466`）。
3. **pending 状态机**：`web/lib/ask-user-state.ts:82-125` 扫描消息事件流——`tool_result` 经 `toolResultPayload(metadata,"ask_user")`（`web/lib/tool-event.ts:50`，注意 payload 嵌在 `tool_metadata` 下）记一张待答卡（以 `tool_call_id` 为键），`progress` 事件带 `ask_user_resolved=true` + `ask_user_tool_call_id` 时按键消除（`ask-user-state.ts:111-121`）。`hasPendingAskUser`（`ask-user-state.ts:134`）回答"回合是否停在等答"。
4. **卡片渲染**：`ChatMessageList` 用 `extractMessageSegments`（`AskUserOptions.tsx:313`）把事件流切成正文与卡片分段，无内联分支时兜底渲染 `AskUserOptions`（`ChatMessageList.tsx:1177`）；组件按 `data.resolved` 在交互/摘要两种形态间切换（`AskUserOptions.tsx:945-961`），交互卡经 `useCardSubmission`（`web/hooks/use-card-submission.ts:25`）管理在途/失败态，提交时一次送出全部题目的 `{text, answers}`（`AskUserOptions.tsx:1044-1059`）。提交失败会把卡片退回可编辑态（`AskUserOptions.tsx:926-931`）。
5. **提交路由**：`submitUserReply`（`ChatStateAdapter.tsx:3115-3163`）只在"流在途或有未答卡 + activeTurnId 存在"时受理（guard `ChatStateAdapter.tsx:3135`），组装 `submit_user_reply` 命令，指纹相同重发复用同一 `command_id`（#1648 幂等，`ChatStateAdapter.tsx:3150-3159`），`awaitAck` 等回执。composer 侧对停车回合的输入先走同一通道，被拒则降级为普通新消息而不是丢弃文本（`ChatWorkspace.tsx:1913-1925`；降级文案常量 `ask-user-state.ts:31`，卡片内失败文案 `ask-user-state.ts:16`）。
6. **传输层兜底**：`TurnRuntimeClient` 按 `command_ack` 兑现在途提交（`TurnRuntimeClient.ts:317-333`），`active_turn_info` 透传（`TurnRuntimeClient.ts:341-345`），断线进入 `recovering` 并按 `resume_from`+seq 续传（`TurnRuntimeClient.ts:300-305,404-411`，缺口缓冲/重放 `TurnRuntimeClient.ts:359-388`）。
7. **完成回合的挂卡守门**：回合完成但仍有未答卡（重放/哨兵竞态）时，保留 `activeTurnId` 让 `submit_user_reply` 仍可送达（`ChatStateAdapter.tsx:1073-1094`）。
8. **后端跨进程恢复**：领导者 `TurnRecoveryService.recover_once` 对租约过期的回合补 error+done 终态并 CAS 失败化（`deeptutor/runtime/coordination/recovery.py:25-104`，`waiting_input` 与 `queued`/`running` 一并按"无租约即死"处理 `recovery.py:49-53`）；请求路径上的同步回收见 §4.3。两者都是 #1297/#1359 报告的"会话被永久占住"的解除机制。

## 7. 热点区域锚点（中性定位）

> 以下锚点只标示上游报告涉及的代码区域，便于评审对照；不含复现步骤或利用说明。

- **#1359 报告区域（聊天通道回合状态自愈）**：
  - 终态 CAS 的合法前驱集合：`lifecycle.py:193-226`（`waiting_input` 参与，注释引 #1297/#1359）。
  - 请求触发的僵尸清理：`app/service.py:349-389`（`_reclaim_unowned_active_turn`，注释引 #1297/#1359）与 `app/service.py:391-458`（`_reap_unowned_live_turn`）。
  - 提交入口的租约/僵尸校验：`app/service.py:331-340`。
- **#1788 报告区域 1（重载后卡片丢失/回答被拒的界面侧）**：会话读回 `ChatStateAdapter.tsx:2423-2497`；提交 guard `ChatStateAdapter.tsx:3135`；通用降级态 `TurnRuntimeClient.ts:404-411`。
- **#1788 报告区域 2（删除消息接口解析归属回合）**：路由 `deeptutor/api/routers/sessions.py:553-569`（`delete_turn_by_message`，409 guard `sessions.py:557-560`）；存储实现 `sqlite_store.py:2138`（`_delete_turn_by_message_sync`），回合解析查询 `sqlite_store.py:2186-2195`（`created_at >=`），运行态判断 `sqlite_store.py:2198`（仅 `== "running"`），async 包装 `sqlite_store.py:2270-2271`。注意回合行先于其 user 行写入（`begin_turn` → `add_message`，`sqlite_store.py:1357/1958`），这是该区域语义的背景事实。

## 8. 上游状态与关联 PR（截至 2026-10-07）

- **#1359**（OPEN）：关联 PR —— #1373（MERGED，waiter 队列丢失后回收回复）、#1413（MERGED，回合消费方停止时取消 capability）、#1363（CLOSED）。主链的自愈面（§4.3、§6.8、`lifecycle.py:193-226`）多来自这两笔已合并修复。
- **#1788**（OPEN）：关联 PR #1789（OPEN，`fix/parked-turn-delete-and-restore`，base `dev`）——同时覆盖 §7 两个区域。
- 另有 #1780（OPEN）：ask_user 卡片内转义 emoji 解码，属卡片文案渲染侧，不改变本链状态机。

## 9. 测试与验证锚点

- 后端：`tests/tools/test_ask_user.py`（payload/预览）、`tests/core/agentic/test_tool_dispatch_pause_ordering.py`（pause 后置与折叠）、`tests/core/agentic/test_tool_dispatch_events.py`、`tests/agents/chat/test_ask_user_drafts.py`（流式预览）、`tests/app/test_turn_parked_on_ask_user_is_reclaimable.py`、`tests/app/test_waiting_turn_recovery.py`、`tests/app/test_blocked_session_reclaims_itself.py`（停车/回收/自愈）、`tests/services/session/test_turn_runtime.py`。
- web：`web/tests/ask-user-state.test.ts`（pending 状态机）、`web/tests/ask-user-card-form.spec.tsx`、`web/tests/ask-user-streaming-card.spec.tsx`（预览→卡片）、`web/tests/ask-user-resume-cursor.spec.tsx`、`web/tests/ask-user-terminal-turn.spec.tsx`、`web/tests/integration/ask-user-trace-continuity.spec.tsx`。

## 10. 函数级调用链（发起 → 停车 → 提交 → 续答，一条可复现主链）

1. `run_agentic_loop`（`runtime/agentic/loop.py:209`）→ TOOL 轮 `dispatch_tools` → `dispatch_tool_calls`（`tool_dispatch.py:122`）→ `AskUserTool.execute`（`builtin/__init__.py:1611`）→ `build_ask_user_payload`（`tools/ask_user.py:102`）→ 返回 `pause_for_user` → pause 捕获（`tool_dispatch.py:907-914`）。
2. `agent_loop.py:703` → `pipeline._await_user_reply_and_resolve`（`pipeline.py:1184`）→ `on_user_pause` hooks（`pipeline.py:1192`）→ `waiter()` 即 `_wait_for_user_reply`（`executor.py:183`）→ `transition_turn(…,"waiting_input")`（`executor.py:186-193` → `sqlite_store.py:1521`）→ `reply_queue.get()`（`executor.py:199`）。
3. web：`AskUserOptions` 提交（`AskUserOptions.tsx:1044-1059`）→ `useCardSubmission`（`use-card-submission.ts:25`）→ `submitUserReply`（`ChatStateAdapter.tsx:3115`）→ WS `submit_user_reply`（`unified_ws.py:305`）→ `app/service.py:320` → 协调器命令 → `_coordinate_execution`（`lifecycle.py:241-244`）→ `TurnLifecycleService.submit_user_reply`（`lifecycle.py:325`）→ `queue.put`（`lifecycle.py:350-352`）。
4. waiter 醒来：`finally` CAS 回 `running`（`executor.py:200-217`）→ 回 `pipeline.py:1208` 起 `_normalise_user_reply` → `user_reply` progress 事件（`pipeline.py:1219-1232`）→ 替换 `role=tool` content（`pipeline.py:1263-1266`）→ `agent_loop.py:715` `continue` → 下一轮 LLM 看到答案继续原请求。
5. 重载恢复支线：REST `active_turns`（`sessions.py:487-491`）→ `loadSession`（`ChatStateAdapter.tsx:2423`）→ 持久化 `events` 里的 `tool_result.metadata.ask_user`（`executor.py:1007-1023`）→ `pendingCards`（`ask-user-state.ts:82`）→ 卡片 pending → composer/卡片提交走第 3 步同一通道。
