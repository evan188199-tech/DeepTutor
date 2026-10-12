# Mastery Path 域导读：会话流 / mastery_hints / mastery_nav / assessment

- 基线 commit：`6cf793bd868ba5ecbe64722936d4be8fab5a01df`（origin/main，release v1.6.14）
- 所有 `path:line` 均在该 commit 上逐一核验（worktree 只读检查，产品代码零改动）。
- 与其他导读卡的边界：本文只深入 Mastery Path（精通路径）域的四个子面；顶层学习域总览见 guide-learning-domain 卡，测试视角见 test-mastery-* 卡。

## 0. 域全景（一句话版）

Mastery Path 的"智能"在 agent loop 的出口（模型决定教什么、怎么问），而"是否允许前进"是一个确定性的引擎调用（`deeptutor/learning` 纯引擎）。能力层（`deeptutor/capabilities/mastery`）把两者接起来：`MasteryPathCapability`（turn 能力）拥有路径租约并跑 tutor 专用 loop pipeline；`MasteryLoopCapability`（loop 扩展）挂载 mastery 工具并守闸门；会话层（`deeptutor/services/session/turns`）负责绑定、租约获取与卡片作答的落库；REST/WS 层（`deeptutor/api/routers/mastery_path.py`）暴露 topic/progress/sessions/ask-hint/实时事件。

## 1. 子面一：会话流（session flow）

### 职责边界
- 解析本回合绑定在哪条 mastery path 上（显式 `mastery_path_id` → 书引用 → 会话私有 scratch path）。
- 为会话型 web 回合获取/释放路径租约（每回合一行租约，per-path 互斥）。
- 把学习者在前端卡片上提交的答案，在 loop 启动**前**落库，使 tutor 第一个 `mastery_status` 就能看到。
- 维持会话偏好（`mastery_path_id`、`mastery_session_mode`），下一次回合自动续接。

### 关键模块 × path:line

| 模块 | 职责 | path:line |
| --- | --- | --- |
| 绑定解析（纯函数） | `sanitize_mastery_path_id` / `MasteryPathBinding` / `resolve_mastery_path_binding` | `deeptutor/learning/identity.py:17`、`:35`、`:42` |
| turn 能力入口 | `MasteryPathCapability.run`：绑会话、拿租约、跑 pipeline；CLI/SDK 直连时自管租约 | `deeptutor/capabilities/mastery/capability.py:57`、`:69`、`:91`、`:97`、`:109` |
| turn 能力注册 | `"mastery_path"` → `MasteryPathCapability` | `deeptutor/runtime/bootstrap/builtin_capabilities.py:43` |
| loop 能力注册 | `"mastery"` → `MasteryLoopCapability` | `deeptutor/capabilities/registry.py:54` |
| 请求准备 | 从 payload/偏好解析 path 与 mode；写回偏好；拿租约；提交卡片答案 | `deeptutor/services/session/turns/request_preparer.py:425`、`:456`、`:708`、`:806`、`:816` |
| 租约/答案适配 | `_acquire_mastery_path_lease` / `_commit_mastery_card_answer` / `_validate_mastery_session_topic` / `_release_superseded_lease`（ask_user 挂起让路的策略） | `deeptutor/services/session/turns/learning_adapter.py:307`、`:74`、`:342`、`:41` |
| 共享判定 | `_mastery_path_id` / `_MASTERY_AGENTIC_ACTIONS` / `_mastery_loop_managed` / `_topic_material_manifest` | `deeptutor/services/session/_turn_runtime_shared.py:434`、`:439`、`:464`、`:469` |
| 回合执行 | 话题材料 manifest + `mastery_topic_source_index`；卡片答案/跳过结果的流事件 | `deeptutor/services/session/turns/executor.py:774`、`:792`、`:804` |
| path 换绑（唯一入口） | `rebind_active_path`（先放旧租约再拿新租约，失败回滚）/ `leave_active_path` / `remember_mode_on_session` | `deeptutor/capabilities/mastery/binding.py:42`、`:91`、`:151` |
| 存储层租约 | `bind_session` / `get_path_lease` / `acquire_path_lease` / `release_leases_for_turn` / `release_path_lease` / `list_events` | `deeptutor/learning/storage.py:1652`、`:1881`、`:1889`、`:1938`、`:1959`、`:2026` |

### 数据流（web 会话一回合）
1. 前端发 turn 请求，带 `mastery_path_id` / `mastery_session_mode` / 可选 `mastery_answer`（字段映射 `request_preparer.py:73-76`）。
2. `request_preparer.py:425-451` 调 `resolve_mastery_path_binding` 解析目标 path；`:456-480` 用 `enforced_mode`（`mode.py:95`）固化本回合 mode；`:708-715` 把 path/mode 写回会话偏好。
3. `request_preparer.py:806-826`：受管回合先 `_acquire_mastery_path_lease`，再把 `mastery_answer` 经 `_commit_mastery_card_answer`（`learning_adapter.py:74`）写入 pending interaction。
4. `MasteryPathCapability.run`（`capability.py:69`）在受管路径下直接跑 `MasteryLoopPipeline`；CLI/SDK 路径自己 `bind_session` + `acquire_path_lease`（`:91-102`），finally 按turn 释放（`:109`）。
5. 中途 `mastery_switch` / `mastery_leave` 经 `binding.rebind_active_path`（`binding.py:42`）换绑；租约始终按 turn id 释放。

## 2. 子面二：mastery_hints（ask-hint）

### 职责边界
- 为学习输入框写"学习者此刻可以问的一个问题"（占位符补全）。只出问题、从不出答案（`_sanitize` 以问号结尾为硬校验）。
- 永不阻塞：同步短超时 + 结果缓存（按 path/kp/对话位置 键控），失败静默回退静态占位符。
- 任务模型额度走 `TaskKind.MASTERY_ASK_HINT`（`deeptutor/services/model_selection/tasks.py:66`、`:90`）。

### 关键模块 × path:line

| 模块 | 职责 | path:line |
| --- | --- | --- |
| 生成服务 | `AskHint` / 缓存与键 / `_load_position`（读同一份 policy）/ `_load_transcript`（尾部 4 轮 + anchor）/ 双语系统提示词 / `_sanitize` / `_generate` / `get_ask_hint` | `deeptutor/services/mastery_hints.py:66`、`:82`、`:91`、`:115`、`:151`、`:201`、`:219`、`:282`、`:308`、`:357` |
| REST 入口 | `GET /api/mastery-paths/topics/{path_id}/ask-hint` | `deeptutor/api/routers/mastery_path.py:778` |
| 模型额度 | `TaskKind.MASTERY_ASK_HINT` 与 spec | `deeptutor/services/model_selection/tasks.py:66`、`:90` |
| 前端拉取 | `learning-api.ts` ask-hint 请求 | `web/lib/learning-api.ts:649` |
| 前端展示 | 学习面板 state 与传入 composer | `web/components/space/learning/MasteryStudy.tsx:356`、`:855`；`web/components/space/learning/MasteryComposer.tsx:154-155` |

### 数据流
`MasteryStudy` → `learning-api.ts:649` → `mastery_path.py:778` → `get_ask_hint`（`mastery_hints.py:357`）→ 缓存命中或 `_generate`（policy 位置 + 会话尾 → LLM → `_sanitize`）→ `hint` 渲染为 composer 占位补全。

## 3. 子面三：mastery_nav（导航）

### 职责边界
- 引擎侧（`deeptutor/learning/navigation.py`）是纯读：topic 卡片、定位、模块解析、会话清单，绝不写。
- 工具侧（`deeptutor/tools/mastery_nav.py`）4 个导航工具（`mastery_topics` / `mastery_sessions` / `mastery_open_session` / `mastery_new_session`）：不拿租约、不动 mastery 状态、不直接跳转——后两个只产出 hand-off 卡片，由学习者点击落地。
- 前端从工具结果 metadata 的 `mastery_handoff` 键读卡片，落到真正的学习页面路由。
- 实时面：`/ws/mastery-paths` 按 topic 推送持久化事件（含 revision 回放），屏幕级信号（`session.bound` 等）即使事件尾为空也转发。

### 关键模块 × path:line

| 模块 | 职责 | path:line |
| --- | --- | --- |
| 导航引擎 | `learner_has_topics` / `topic_cards` / `find_topic` / `resolve_module` / `topic_sessions` / `navigable_session_rows` | `deeptutor/learning/navigation.py:41`、`:87`、`:150`、`:217`、`:254`、`:308` |
| 导航工具 | `HANDOFF_META_KEY` / `MASTERY_NAV_TOOL_NAMES` / `_handoff`（id 先验证再产出）/ 4 个工具类 | `deeptutor/tools/mastery_nav.py:53`、`:56`、`:145`、`:194`、`:206`、`:255`、`:306`、`:405` |
| 工具挂载 | loop 扩展里 nav 工具保持挂载与参数注入 | `deeptutor/capabilities/mastery/loop.py:293` |
| nav 可用性 | chat loop 中 nav 话题可用性判定 | `deeptutor/agents/loop/pipeline.py:758`、`:789` |
| REST 索引 | `GET /topics` / `GET /topics/index` / `GET /topics/{id}/sessions` | `deeptutor/api/routers/mastery_path.py:456`、`:468`、`:720` |
| 实时事件 | `_SCREEN_ONLY_SIGNALS` / WS `/mastery-paths`（订阅、revision 回放、转发） | `deeptutor/api/routers/mastery_path.py:49`、`:791` |
| 事件中枢 | `MasteryTopicEventHub` / `subscribe` / `publish` / `publish_topic_signal` | `deeptutor/learning/event_hub.py:55`、`:65`、`:83`、`:124` |
| 前端 WS | `MASTERY_WS_PATH` / `MasteryTopicSocket` | `web/lib/mastery-ws.ts:8`、`:96`、`:108` |
| 前端活动 hook | `useMasteryPathActivity`（WS + REST 对账、游标合并） | `web/hooks/useMasteryPathActivity.ts:138` |
| hand-off 卡片 | `MasteryHandoffPayload` / `masteryHandoffFrom` / `extractMasteryHandoffs` / `masteryHandoffHref` | `web/lib/mastery-handoff.ts:28`、`:73`、`:121`、`:147` |
| 卡片渲染 | 消息流中的 hand-off 卡片 | `web/features/chat/messages/ChatMessageList.tsx:97`、`:102`、`:860`、`:1191`；`web/components/chat/home/MasteryHandoffCard.tsx` |
| 页面路由 | 路由常量与生成器 | `web/lib/learning-routes.ts:9`、`:21`、`:24`、`:28` |
| 页面文件 | atlas / topic / sessions / session 页 | `web/app/(workspace)/learning/mastery/page.tsx`、`[pathId]/page.tsx`、`[pathId]/sessions/page.tsx`、`[pathId]/sessions/[sessionId]/page.tsx` |

### 数据流
- 会话归属：会话偏好 `workspace_mode=mastery_path` + `mastery_path_id` 双信号 → `masteryPathIdOf`（`web/lib/mastery-session.ts:27`）→ 侧栏归档与点击路由（`sessionRoute`，`:50`）。
- hand-off：模型调 `mastery_open_session`/`mastery_new_session` → `_handoff` 验证 id → metadata `mastery_handoff` → `ChatMessageList` `extractMasteryHandoffs` → 卡片点击 → `masteryHandoffHref` → 学习页。
- 实时：`LearningStore.save`/管理端变更 → `publish_topic_signal` → WS `forward`（revision 尾回放 + 屏幕信号）→ `MasteryTopicSocket` → `useMasteryPathActivity` 合并到 feed。

## 4. 子面四：assessment（评估 / 闸门 / 复习调度）

### 职责边界
- 硬闸门是确定性的：`policy.gate_threshold` / `next_objective` 决定能否前进；模型只决定教与问。
- 题目生命周期：`mastery_quiz` 出题（选项题结束回合）→ 前端卡片作答 → `mastery_grade` 确定性判分 → 引擎更新掌握度与调度；`mastery_assess` 服务 CONCEPT/DESIGN 类定性评估。
- 评估记录（`AssessmentRecord`）双写：进 mastery 引擎 + 异步同步到题库/笔记本（带 linkage 信任检查）。
- 复习调度：FSRS 风格 `SpacedRepetitionScheduler` + `due_reviews`；review 模式不受"到期"门禁。
- 模式门禁：`TOOL_MODES` 把改图工具锁在 outline、考察工具锁在 study/review；`admission_error` 是工具与 REST 共用的唯一拒绝规则。

### 关键模块 × path:line

| 模块 | 职责 | path:line |
| --- | --- | --- |
| 模式与门禁 | `TOOL_MODES` / `normalize_mode` / `enforced_mode` / `tool_is_allowed` / `admission_error` / `wrong_mode_message` | `deeptutor/capabilities/mastery/mode.py:71`、`:84`、`:95`、`:113`、`:122`、`:148` |
| 策略引擎 | `gate_threshold` / `is_assessed_mastered` / `due_reviews` / `NextStep` / `next_objective` / `map_summary` / `objective_report` | `deeptutor/learning/policy.py:74`、`:82`、`:168`、`:180`、`:255`、`:365`、`:465` |
| 领域服务 | `LearningService`：`record_quiz_attempt` / `calculate_mastery` / `register_question` / `record_question_answer` / `grade_interaction` / `repair_question` / `defer_objective` / `record_qualitative` | `deeptutor/learning/service.py:269`、`:409`、`:463`、`:654`、`:776`、`:846`、`:1477`、`:1703`、`:1759` |
| 掌握度/调度 | `compute_mastery` / `SpacedRepetitionScheduler` | `deeptutor/learning/mastery.py:24`；`deeptutor/learning/scheduler.py:127` |
| 判分 | `grade_answer` / `classify_error`；选项归一 `resolve_choice_submission` | `deeptutor/learning/grading.py:13`、`:52`；`deeptutor/learning/pending.py:139` |
| 题卡 | `attempt_number` / `build_question_card` / `build_grade_result` | `deeptutor/learning/question_card.py:45`、`:57`、`:91` |
| 评估记录 | `AssessmentRecord` / `_resolve_result` / `_apply_linkage` / `_apply_linked_retention` / `to_notebook_item` / `record_assessment` / `reconcile_linked_assessments` | `deeptutor/learning/assessment.py:76`、`:245`、`:266`、`:301`、`:390`、`:426`、`:512` |
| 工具层 | `MasteryQuizTool` / `MasteryGradeTool` / `MasteryAssessTool` / `MasterySkipQuestionTool` / `MasteryRepairQuestionTool` / `MasteryDeferObjectiveTool` / `MasteryModeTool`；题库同步 `_sync_mastery_attempt_to_question_bank` / `_sync_qualitative_to_question_bank` | `deeptutor/capabilities/mastery/tools.py:885`、`:1185`、`:1421`、`:1528`、`:1576`、`:1693`、`:1919`、`:344`、`:411` |
| 闸门时机 | `mastery_quiz` 挂 `_end_turn_on_card`、grade 复位；loop 出口 `finish_instruction` / `final_text_override` / `_grade_seed` / `_skip_seed` | `deeptutor/capabilities/mastery/loop.py:261`、`:304`、`:381`、`:494`、`:515` |
| REST 评估面 | review-settings / skip-question / mode 按钮（与工具同一 `admission_error`） | `deeptutor/api/routers/mastery_path.py:608`、`:617`、`:1145`、`:741` |
| LLM 判卷（chat 测验旁路） | WS `/ws/questions/judge` | `deeptutor/api/routers/quiz_judge.py:227`；注册 `deeptutor/api/main.py:797`；前端 `web/lib/quiz-judge.ts:40`；消费 `web/components/quiz/QuizViewer.tsx:43` |

### 数据流（一道选项题的完整闭环）
1. 模型调 `mastery_quiz`（`tools.py:885`）：mode 门禁 → 出题 → `register_question`（`service.py:654`）→ 题卡挂 metadata（`question_card.py:57`）→ `loop.py:261-264` 置 `_end_turn_on_card`，回合在卡片后结束。
2. 学习者在卡片作答 → 前端把 `mastery_answer` 附在下一个 turn 请求上 → `request_preparer.py:816-826` 在 loop 启动前经 `_commit_mastery_card_answer`（`learning_adapter.py:74`）落库 → `record_question_answer`（`service.py:776`）。
3. 模型（新回合）调 `mastery_grade`（`tools.py:1185`）→ `grade_interaction`（`service.py:846`）→ `_apply_grade`（`service.py:515`）→ 调度器更新间隔 → 结果作为 `mastery_grade` 工具事件发回卡片。
4. 旁路同步：`tools.py:401` / `:451` 调 `record_assessment`（`assessment.py:426`），linkage 可信才回写关联 retention（`:301`），并 `to_notebook_item`（`:390`）进笔记本；题库同步 `_sync_mastery_attempt_to_question_bank`（`:344`）。

## 5. 子面 × 模块 × path:line 汇总表（速查）

| 子面 | 后端核心 | API/WS | 前端 |
| --- | --- | --- | --- |
| 会话流 | `learning/identity.py:42`；`capabilities/mastery/capability.py:69`；`capabilities/mastery/binding.py:42`；`services/session/turns/request_preparer.py:425`；`services/session/turns/learning_adapter.py:41` | —（turn 请求本身） | `web/lib/mastery-session.ts:27`；`web/hooks/useMasteryStudySession.ts:38`；`web/components/space/learning/MasteryStudy.tsx:39` |
| mastery_hints | `services/mastery_hints.py:357`；`services/model_selection/tasks.py:66` | `api/routers/mastery_path.py:778` | `web/lib/learning-api.ts:649`；`web/components/space/learning/MasteryComposer.tsx:154` |
| mastery_nav | `learning/navigation.py:87`；`tools/mastery_nav.py:56`；`learning/event_hub.py:55` | `api/routers/mastery_path.py:456`、`:720`、`:791` | `web/lib/mastery-handoff.ts:121`；`web/lib/mastery-ws.ts:96`；`web/hooks/useMasteryPathActivity.ts:138`；`web/lib/learning-routes.ts:9` |
| assessment | `learning/policy.py:255`；`learning/service.py:846`；`learning/scheduler.py:127`；`learning/assessment.py:426`；`capabilities/mastery/mode.py:71`；`capabilities/mastery/tools.py:885` | `api/routers/mastery_path.py:741`、`:1145`；`api/routers/quiz_judge.py:227` | `web/lib/quiz-judge.ts:40`；`web/components/quiz/QuizViewer.tsx:43` |

## 6. 后续修复卡（up-19xx）入口提示

- "换路径失败/卡死"：先看 `binding.py:42`（先放后拿与回滚）与 `storage.py:1889`（租约冲突）；`learning_adapter.py:41` 管 ask_user 挂起时的让路。
- "问题没出现/答案没落库"：链路 `tools.py:885` → `loop.py:261`（结束回合）→ 前端卡片 → `request_preparer.py:816` → `learning_adapter.py:74` → `service.py:776`。
- "占位 hint 泄漏答案"：`mastery_hints.py:282` `_sanitize` 与 `:201`/`:219` 系统提示词。
- "导航卡片点空"：`mastery_nav.py:145` 的 id 验证 → `mastery-handoff.ts:147` href → `learning-routes.ts:21-28`。
- "掌握度/复习日期不对"：`policy.py:74`（闸门阈值）与 `scheduler.py:127`（间隔推进）、`service.py:515`（判分落账）。
- "模式拒绝不一致"：工具侧 `tools.py:610` / `mode.py:122` 必须与 REST `mastery_path.py:765` 用同一条 `admission_error`。
