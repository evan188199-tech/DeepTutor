# Mastery Path 模块代码导读

> 基于 `origin/main` v1.6.12（`ef2d9e5c3`）。所有 `path:line` 均可在该提交直接定位。
> Mastery Path（精通之路）= 以"一个 agent loop 就是导师"为核心的引导式学习：大纲 → 学习 → 复习，
> 配有按题型硬性把关的精通门槛（mastery gate）与间隔复习。

## 1. 模块地图

| 层 | 位置 | 职责 |
|---|---|---|
| TurnCapability | `deeptutor/capabilities/mastery/capability.py:57` | 把回合路由进 `mastery_path` 能力（manifest `:58-67`，CLI 别名 `mastery`） |
| LoopCapability | `deeptutor/capabilities/mastery/loop.py:174` | 注入导师协议：工具挂载、结尾约束、卡片判分种子 |
| Pipeline | `deeptutor/capabilities/mastery/pipeline.py:57` | 复用 chat 引擎，仅换 prompt（`prompt_module="mastery"` `:64`） |
| 领域服务 | `deeptutor/learning/service.py:266` | 大纲/测验/复习的全部领域操作 |
| 存储层 | `deeptutor/learning/storage.py:348` | `LearningStore`：SQLite 单写者 + 乐观版本号 |
| REST | `deeptutor/api/routers/mastery_path.py` | 挂载于 `/api/mastery-paths`（`deeptutor/api/main.py:615-620`） |
| WS | `deeptutor/api/routers/mastery_path.py:771` | `/ws/mastery-paths` 主题事件流；回合走统一 `/ws`（`deeptutor/api/routers/unified_ws.py:43`） |
| 前端 | `web/components/space/learning/`、`web/hooks/useMastery*.ts`、`web/lib/mastery-*.ts` | 学习工作台与主题仪表盘 |

## 2. 状态机

### 2.1 会话模式（outline / study / review）
- 三个模式定义于 `deeptutor/capabilities/mastery/mode.py:46-50`，缺省 `STUDY`（`:57`，历史会话不回填）。
- 工具按模式准入：`TOOL_MODES`（`mode.py:71-80`，`mastery_build`/`mastery_revise` 仅 outline；quiz/grade/skip/repair/defer/assess 需 study+review）；判定入口 `tool_is_allowed`（`mode.py:112-118`）、`admission_error`（`:121-138`，study 需已有大纲，review 不查到期）。
- 改模式的三个入口：`mastery_mode` 工具（`deeptutor/capabilities/mastery/tools.py:1801`，经 `_bind_active_mode` `deeptutor/capabilities/mastery/loop.py:498-512` 持久化）；学习者 REST 按钮 `PUT /topics/{path_id}/sessions/{session_id}/mode`（`deeptutor/api/routers/mastery_path.py:721-755`）；每次回合开始由 `enforced_mode` 解析并写入偏好（`deeptutor/services/session/turns/request_preparer.py:413-425`、`:648-655`）。
- 前端镜像：`web/lib/mastery-mode.ts:17-31`（`MASTERY_MODES`、`normalizeMasteryMode`），模式切换 UI 在 `web/components/space/learning/MasteryStudy.tsx:492-516`。

### 2.2 测验交互生命周期（quiz interaction）
- 状态枚举 `InteractionStatus`：`REGISTERED → AWAITING_INPUT → ANSWERED → GRADED | ABANDONED`（`deeptutor/learning/models.py:294-307`；终态保留以支持幂等重试，`:297-301` 注释）。
- 迁移点全在 `deeptutor/learning/service.py`：注册 `:696` → 等待作答 `:746-747` → 已作答 `:788-792`（含可读选项修复 `:803-826`）→ 已判分 `:940`（幂等重放 `:870-871`）；放弃走 `abandon_active_question`（`:1275-1305`）。
- 出题工具 `mastery_quiz`：注册题目（`deeptutor/capabilities/mastery/tools.py:945`）、置 `AWAITING_INPUT`（`:962-968`）、`end_turn()`（`:978-984`）。
- **回合不停车**：出卡即结束回合（`final_text_override` 返回 `""`，`deeptutor/capabilities/mastery/loop.py:376-407`，docstring 解释了为何弃用 `ask_user` 停车）；作答是下一条消息，运行时在导师首 token 前先判分（`deeptutor/services/session/turns/executor.py:790-797` → `deeptutor/services/session/turns/learning_adapter.py:117-210`）。

### 2.3 聊天回合状态（turn status）
- `queued/running/waiting_input` 为活动态，`completed/failed/cancelled` 为终态（`deeptutor/services/session/sqlite_store.py:115-117`）；CAS 迁移 `transition_turn`（`:1494`）。
- `waiting_input` 仅由 `ask_user` 停车进入（`deeptutor/services/session/turns/executor.py:186-193`，恢复 `:200-217`）；mastery quiz 卡不再触发。
- 活动回合判定（含 `waiting_input`）：`get_active_turn`/`list_active_turns`（`sqlite_store.py:1370-1409`）；状态枚举另见 `deeptutor/api/contracts/turn_protocol.py:16-22`。

### 2.4 知识点与循环游标
- 知识点状态 `mastered | learning | new`：`deeptutor/learning/policy.py:122-129`；门槛类型/阈值 `gate_kind`/`gate_threshold`（`:208`/`:74`）。
- 循环游标 `NextStep`（`policy.py:143-194`）优先级 `answer_pending → review → probe/teach/practice/assess → complete`（`:225-231`）。

### 2.5 路径租约（path lease）
- 同一路径同一时刻只允许一个"变更型"回合：`MasteryPathLease`（`deeptutor/learning/models.py:342-350`）；获取 `deeptutor/learning/storage.py:1889`（冲突抛 `PathLeaseConflictError` `:97`）、按回合释放 `:1938`。
- Web 端由 request_preparer 获取（`request_preparer.py:718-738`，冲突映射 `mastery_path_busy` 在 `learning_adapter.py:335-339`）；CLI/SDK 由能力自持（`deeptutor/capabilities/mastery/capability.py:86-109`）。管理面用 `"__path_api__"` 租约串行化 REST 变更（`deeptutor/api/routers/mastery_path.py:132-163`）。

## 3. 后端：回合如何流动

1. **绑定与预处理**：`request_preparer.py` 解析路径绑定（`:372-397`，`deeptutor/capabilities/mastery/capability.py:42-54` 的 `resolve_mastery_path_id`）、会话模式（`:413-425`）、获取租约并预提交卡片答案（`:718-738`）。
2. **执行**：`executor.py:141` `_run_turn` —— 组装 `UnifiedContext` 元数据 `mastery_path_id/mastery_mode/mastery_session_mode/mastery_card_grade/...`（`:935-947`）；卡片答案先判分（`:790-797`）或跳过（`:798-806`）；引擎跑完发布路径/模式变更事件（`:1044-1058`），`finally` 释放租约（`:1377-1389`）。
3. **导师协议注入**：`MasteryLoopCapability.augment_kwargs`（`loop.py:239-297`）服务端注入 `_mastery_path_id/_session_mode/_session_id`，把 `read_source` 重映射到 `mastery_topic_source_index`（`:251-257`）；`finish_instruction`（`:299-374`）拒绝"没留下可作答内容"的收尾；`pre_loop_seed`（`:409-477`）把运行时判分结果作为种子喂给导师。
4. **Prompt**：`MasteryPromptAssembler.foundation_blocks`（`pipeline.py:45-54`）换装 tutor 块；文案在 `deeptutor/capabilities/mastery/prompts/en/mastery_loop.yaml:30-127`（`loop.system` 定义"出题即收尾"轮次语义，中文镜像在 `prompts/zh/`）。
5. **KB 接入**：`MasteryLoopPipeline.run` 把主题 KB 并入 `context.knowledge_bases` 并在 `learning_source_access` 下运行（`pipeline.py:81-91`）。

### 3.1 十四个导师工具
注册表 `MASTERY_TOOL_NAMES`（`deeptutor/capabilities/mastery/tools.py:92-107`），类型映射 `MASTERY_TOOL_TYPES`（`:2678-2693`）；挂载经由 loop 能力的 `owned_tools`（`loop.py:197`）由引擎应用（`deeptutor/agents/loop/pipeline.py:811-815`）。实现（类 → execute）：`mastery_status` `:672/:688`、`mastery_quiz` `:775/:892`、`mastery_grade` `:1035/:1068`、`mastery_skip_question` `:1364/:1381`、`mastery_repair_question` `:1412/:1453`、`mastery_defer_objective` `:1529/:1558`、`mastery_assess` `:1257/:1291`、`mastery_build` `:1597/:1703`、`mastery_mode` `:1755/:1801`、`mastery_profile` `:1849/:1928`、`mastery_revise` `:1983/:2086`、`mastery_paths` `:2179/:2195`、`mastery_switch` `:2220/:2246`、`mastery_leave` `:2283/:2300`。
- 选择题数据契约（label/body/判分/持久化文本四种形态）：`deeptutor/capabilities/mastery/choices.py:73-257`；核心字母数学在 `deeptutor/learning/pending.py:26-28`（`positional_label`）。
- 导航类工具（`mastery_topics/sessions/open_session/new_session`）是共享的上下文门控工具：`deeptutor/tools/mastery_nav.py:56-61`、注册 `deeptutor/tools/builtin_specs.py:87-95`、挂载门 `deeptutor/agents/_shared/tool_composition.py:159-167`。

### 3.2 REST API 速查（`deeptutor/api/routers/mastery_path.py`）
- 主题：`GET /topics` `:439`、`GET /topics/index` `:451`、`POST /topics/draft` `:489`（LLM 草拟大纲）、`POST /topics` `:526`、`GET /topics/{id}` `:585`、`PUT /topics/{id}/map` `:630`、复习设置 `:591`/`:600`、目标覆盖 `:671`、提问提示 `GET /topics/{id}/ask-hint` `:758`（→ `deeptutor/services/mastery_hints.py:357-377`）。
- 会话：`GET /topics/{id}/sessions` `:700`、模式切换 `PUT .../sessions/{sid}/mode` `:721`。
- 旧版聚合（`/progress/*`）：`:886-1249`（含 `DELETE /progress/{book_id}` `:1114`、重置 `POST .../redo` `:1143`）。
- 关键辅助：`_exclusive_path_mutation`（`:132-163`，管理租约 + 409）、`_cancel_active_learning_turn`（`:101-130`）。

### 3.3 WebSocket
- 回合通道：统一 `/ws`（`deeptutor/api/routers/unified_ws.py:43`），`start_turn` `:220-238`、订阅 `:140-157`、取消 `:288-303`、`ask_user` 回复 `:305-326`。
- 主题事件流：`/ws/mastery-paths`（`deeptutor/api/routers/mastery_path.py:771-883`）：客户端带 `after_revision` 订阅（`:830-848`），先 `store.list_events` 重放（`:864-868`）再经 `MasteryTopicEventHub` 转发（`deeptutor/learning/event_hub.py:55`、发布 `:124`）；屏幕信号（绑定/释放/删除）绕过版本过滤（`:49`、`:815`）。

## 4. 前端组件

### 4.1 路由与页面（`web/app/(workspace)/learning/mastery/`）
- `page.tsx:34-121` 主题总览（`TopicAtlas` + 创建向导）；`[pathId]/page.tsx:60` 起为主题仪表盘（outline/board 切换 `:527-563`、outline 滚动盒 `:566`、`ReviewTrail` `:594-618`）；`[pathId]/sessions/page.tsx:17-21` 草稿学习路由；`[pathId]/sessions/[sessionId]/page.tsx:7-17` 既有会话学习页。

### 4.2 学习工作台 `MasteryStudy.tsx`
- 组装：chat 适配器（`web/components/space/learning/MasteryStudy.tsx:176-188`）+ 会话解析 `useMasteryStudySession`（`:190-202`）；待发提示消费 `:292`、`:323-334`；开场自动发送 `useMasteryOpening`（`:478-487`，实现 `web/hooks/useMasteryOpening.ts:34-53`）。
- 作答/跳过：`answerMasteryQuestion` `:418-437`、`skipMasteryQuestion` `:441-465`（以 `masteryAnswer`/`masterySkip` 元数据发送）；`startFromPrompt` `:467-476`；掌握庆祝的状态 diff `:370-400`。
- 布局：左大纲轨 `:635-647`（`StudyOutline` 无高度上限，`web/components/space/learning/StudyOutline.tsx:101`）、转录滚动容器 `:650-816`、`MasteryComposer` `:830-837`。
- `MasteryComposer.tsx`：钉住 capability（`:64-72`）、`awaitingUserReply`（`:83-85`）、卡片作答路由 `:87-126`。

### 4.3 Chat 内集成卡片
- 测验卡 `MasteryQuestionCard.tsx`：选项行 `:41-93`（字母标记 `:79-86`）、提交 `:150-156`（把所选 **label 字母** 作为文本 `{text, answers:[{questionId,text}]}`）、判分样式 `:181-190`。接入点 `web/features/chat/messages/ChatMessageList.tsx:798-826`（渲染）、`:2032-2039`（全对话判分/跳过收集）。
- 交接卡 `MasteryHandoffCard.tsx`：解析 `mastery_handoff` 工具结果（`web/lib/mastery-handoff.ts:73-136`），点击携带开场白跳转（`go()` `:113-119`）。
- 发送链路：`web/features/chat/components/ChatWorkspace.tsx:2140-2160` → `start-turn`（`web/features/chat/model/start-turn.ts:43`）→ 统一 `/ws`。

### 4.4 Hooks 与 lib
- `useMasteryStudySession.ts`：路由→（主题, 会话）状态机 `:152-236`；草稿会话建好后 URL 重写 `:238-266`。
- `useMasteryPathActivity.ts`：WS 推送 + REST 对账（`reconcile` `:164-192`、socket 装配 `:195-234`），无定时轮询。
- WS 协议 `web/lib/mastery-ws.ts`：`MASTERY_WS_PATH` `:8`、订阅载荷 `:40-49`、`MasteryTopicSocket` `:96-154`（断线保 cursor 重连）。
- API 客户端 `web/lib/learning-api.ts`：V2 段 `:411` 起（`masteryJson` `:575`、`fetchMasteryTopic` `:650`、`setMasterySessionMode` `:677`、建题 `:708`）；V1 事件流 `fetchProgressEvents` `:217`。
- 会话归属 `web/lib/mastery-session.ts:27-32`（`workspace_mode === "mastery_path"` + `mastery_path_id`）。

## 5. 锁与持久化

### 5.1 工作区活动锁（activity lock）
- 跨进程 SQLite 事务锁：`acquire_activity()` 打开 `workspace-activity.sqlite3` 并 `BEGIN [EXCLUSIVE]`，争用抛 "Workspace data is busy"（`deeptutor/services/workspace/activity.py:12-36`）；`workspace_writer` 装饰器把整个调用包进锁（`:48-64`）。
- 回合持有两把：回合启动时打开的句柄，随任务 done-callback 释放（`deeptutor/services/session/turns/request_preparer.py:797-806`）；`_run_turn` 本体整体 `@workspace_writer`（`executor.py:140-141`）。**`ask_user` 停车期间两把都持续持有**。

### 5.2 路径租约
- 持久表 `mastery_path_leases`（`deeptutor/learning/storage.py:482`）；获取/冲突/按回合释放见 §2.5；被取代回合的接管与释放 `learning_adapter.py:41-72`、`:307-339`。

### 5.3 存储（SQLite 表）
- `LearningStore`（`deeptutor/learning/storage.py:348`，建表 `:390-524`）：`mastery_paths` `:407`（state_json + revision 乐观校验，`save` `:1002`，冲突抛 `LearningConflictError` `:84`）、`mastery_path_sessions` `:419`（`bind_session` `:1652`）、`mastery_interactions` `:429`（持久问答日志）、`mastery_events` `:447`（`emit` `:134`，供 WS 增量重放）、`mastery_learning_evidence` `:460`、`mastery_topic_meta/sources` `:489`/`:500`。
- 聊天侧（`deeptutor/services/session/sqlite_store.py`）：`sessions` `:276`、`messages` `:286`、`turns` `:313`（FK 级联 `:313-315`）、`turn_events` `:336`；偏好写 `update_session_preferences` `:2922`（`mastery_path_id`/`mastery_session_mode` 的落点）。
- 题库旁路：判分结果 upsert 到 `assessment_attempts`（`deeptutor/learning/assessment.py:425-508` → `sqlite_store.py:3339`，建表 `:399-421`）。

## 6. 相关上游 issue 的代码位置

### #1646 删除会话可遗留持有活动锁的孤儿回合（OPEN，关联 PR #1685）
- 删除入口 `DELETE /{session_id}`：`deeptutor/api/routers/sessions.py:460-493` —— 先对每个目标 `list_active_turns` + `runtime.cancel_turn`（`:481-488`），再删行（`:489-492`）并 `detach_session` 清理路径租约/绑定（`:496-508` → `deeptutor/learning/storage.py:1810-1866`）。
- 缺口在运行时取消 `TurnLifecycle.cancel_turn`（`deeptutor/services/session/turns/lifecycle.py:305-323`）：无在执行例时，有 coordinator 直接 `return False`（`:309-310`）；无 coordinator 时仅终结 `status == "running"` 的行（`:311-315`）——**`waiting_input` 行不处理**。该回合进程仍持有 §5.1 两把锁，后续独占操作报 busy。
- 对照：应用层取消已能处理 `waiting_input` 并回收无主回合（`deeptutor/app/service.py:260-281`、`_reclaim_unowned_active_turn` `:313` 起），但删除路由走的是较弱的运行时取消。
- 相关守卫（非删除路径）：`_release_superseded_lease` 接管时取消持租约的停车回合（`learning_adapter.py:41-72`）；重启恢复把 WAITING_INPUT 扫成 FAILED（`deeptutor/runtime/coordination/recovery.py:50-95`）。

### #1624 测验答案字母触发无上下文 KB 检索（OPEN，关联 PR #1642/#1626）
- 前端把所选**字母**当消息文本发送：`MasteryQuestionCard.tsx:133-135`、`:213-217`（`setPicked(option.label)`）、提交 `:150-156`；两处发送面 `MasteryStudy.tsx:418-437`、`ChatWorkspace.tsx:2140-2160`。
- 后端把原文当 `user_message`：`executor.py:884-886`；随后 **KB 预播种**用 `context.user_message` 直接当查询：`deeptutor/agents/loop/pipeline.py:1450-1488`（`query = (context.user_message or "").strip()` `:1458`，`_seed_search_one_kb` `:1490-1523` 用 `rag` 工具检索 `:1507-1512`），播种在循环前执行（`deeptutor/agents/loop/agent_loop.py:291`），拼进用户消息（`deeptutor/agents/loop/prompt_blocks.py:272-280`）。
- 答案虽在循环前已判分（`executor.py:790-797`）并作为导师种子（`loop.py:409-477`），但播种路径**不识别** `mastery_answer`/`mastery_card_grade` —— 即"检索查询只有一个字母"的成因。字母由后端生成：`deeptutor/learning/pending.py:26-28`、`deeptutor/capabilities/mastery/choices.py:152-157`。
- 相反方向的既有守卫：mastery 回合把主题材料挡在 `explore_context` 预检之外（`executor.py:760-784`）。

### #1566 复习条目多时"精通大纲"过矮（CLOSED，关联测试 PR #1636）
- 复习计划面板整体被 `lg:max-h-[min(30vh,260px)]` 硬封顶：`web/components/space/learning/ReviewTrail.tsx:48`；内部滚动列表 `:99`，条目另截断到 5 条（`:43`，展开按钮 `:142-150`）。
- 与大纲抢高度的布局：`[pathId]/page.tsx` 固定高双栏 `:483`、左列 `lg:h-full` `:522`、大纲滚动盒仅 `lg:min-h-[260px] lg:flex-1` `:566`，`ReviewTrail` 挂同一列 `:594-618`——条目多时大纲被压到下限附近。
- 旁邻约束：`LearnerProfileCard.tsx:42`（`lg:max-h-[46%]`）。学习页大纲轨无此问题（`MasteryStudy.tsx:635-647`）。

## 7. 建议阅读顺序

`deeptutor/capabilities/mastery/capability.py` → `loop.py`（协议）→ `pipeline.py`（复用引擎）→
`deeptutor/learning/models.py` + `policy.py`（领域模型）→ `service.py`（操作）→ `storage.py`（持久化）→
`mastery_path.py` 路由 → 前端自 `[pathId]/page.tsx` 与 `MasteryStudy.tsx` 入手。
