# 出题 → 题库链路导读（capability_routing → quiz 生成 → Question Notebook → assessment）

面向上游 #575（聊天出题不入题库）执行者。行号基于 `main` @ 6cf793bd8（v1.6.14）。
结论均附 `path:line`，阅读前先记住一句话：**服务端只负责"生成并广播"，题库入库的触发权在浏览器**。

## 1. 入口

| 入口 | 触发方式 | 落点 |
| --- | --- | --- |
| 聊天自动路由 | 系统设置 `capability_routing_enabled`（默认 **False**，`deeptutor/services/config/runtime_settings.py:40`）或单轮 `auto_route`（`deeptutor/services/session/turns/request_preparer.py:166-174`） | `route_explicit_quiz_request`（`deeptutor/runtime/capability_routing.py:49`） |
| 手动选择动作 | 前端 capability 下拉选 `deep_question` | 同一 `start_turn` 流程，跳过路由 |
| CLI | alias `quiz`（`deeptutor/runtime/bootstrap/builtin_capabilities.py:105`） | 同一 capability |
| REST 任务 API | `/api/question/*`（挂载 `deeptutor/api/main.py:605`） | `deeptutor/api/routers/question.py` |
| 阅读工作区 "Quiz me" | Reading 扩展 | `ReadingQuizExtension`（`deeptutor/reading/quiz.py:81` 起） |
| 书本 Focus-check | 书页 quiz block | 复用 `QuestionPipeline`（`deeptutor/book/blocks/quiz.py:43-63`） |

路由规则要点（`deeptutor/runtime/capability_routing.py`）：

- 只匹配"生成/创建 … 题组"句式（:37-44）；"quiz me" 这类互动请求**故意留在 chat**（:33-36 注释）。
- 非 `chat` capability 不路由（:70-71）；workspace 内的会话永不路由（:72-73）。
- 命中后 capability 改写为 `deep_question`（`request_preparer.py:331-339`），路由元数据写入 session 事件（:866-867），并按 manifest 裁剪工具表（:593-606）。
- capability → 类的注册：`deeptutor/runtime/bootstrap/builtin_capabilities.py:39,98-107` → `DeepQuestionCapability`。

## 2. 数据流

### 2.1 生成（deep_question）

`DeepQuestionCapability.run`（`deeptutor/agents/question/capability.py:39`）三分支：

1. **followup**（对既有题目的追问，:74-108）：`FollowupAgent` 单次调用，不走题库写入。
2. **custom**（:124-167）：`QuestionPipeline.run` —— explore（`pipeline.py:556`）→ plan（:573）→ 逐题生成（:585-607，每题经 `_emit_quiz_question` :1290-1316 以 `content` 事件 + `call_kind="quiz_question_emitted"` 广播）。
3. **mimic**（:169-353）：MinerU 解析试卷出模板，跳过 explore/plan，其余同 pipeline。

终局：`_build_result_payload`（`pipeline.py:1320-1379`）→ `emit_capability_result`（:613，仅 `stream.result`，实现在 `deeptutor/agents/_shared/capability_result.py:30-40`）。**整条生成链路没有任何落库调用。**

出题历史来自题库表而非消息（`deeptutor/agents/question/history.py:14` 明示 source of truth 是 `POST /sessions/{id}/quiz-results` 写入的 `notebook_entries`）：`load_session_quiz_history`（`history.py:34`）。

followup 上下文由 turn 执行器注入 metadata（`deeptutor/services/session/turns/executor.py:950`）。

### 2.2 前端渲染与入库（唯一入库路径）

- 仅 `msg.capability === "deep_question"` 的消息才挂 `QuizViewer`（`web/features/chat/messages/ChatMessageList.tsx:743-751`，判断在 :744）；渲染点 :1094-1121。
- 流式题目从 `quiz_question_emitted` 事件抽取（`web/lib/quiz-types.ts:132-158`）；result 事件抽取 :190-208；turn_id 提取 :175-184，**无 turn_id 的 legacy 题卡本地渲染、不读写题库**（:171-173 注释）。
- 入库时机（`web/components/quiz/QuizViewer.tsx`）：
  - **每题提交答案时** `upsertSingleQuestion` → `upsertNotebookEntry`（:473-536，upsert 调用 :489-502）；触发点 `handleSubmit`（:538-543）。`sessionId`/`turnId` 缺失时**静默 return**（:479）。
  - **全部题目答完时** `recordQuizResults`（:442-471，门槛 :446 `completedCount !== total` 即 return）→ `POST /api/sessions/{id}/quiz-results`（`web/lib/session-api.ts:424`）。
- 服务端（`deeptutor/api/routers/sessions.py:696-727`）：追加一条 `[Quiz Performance]` 用户消息（:705-710）+ `upsert_notebook_entries`（:713-716，失败仅 warning :717-720）。
- 单题手动 upsert HTTP：`POST /api/question-notebook/entries/upsert`（`deeptutor/api/routers/question_notebook.py:275-321`；前端封装 `web/lib/notebook-api.ts:462-497`）。

### 2.3 存储

- 表 `notebook_entries`：`deeptutor/services/session/sqlite_store.py:375-413`；业务唯一键 `UNIQUE(origin_type, origin_ref, turn_id, question_id)`（:412）。
- 不可变尝试日志 `assessment_attempts`：:421-443。
- 写入实现：`upsert_notebook_entries`（:3185 起）、`record_assessment`（:3405）、按 origin 查找 `find_notebook_entry_by_origin`（:4311）。
- 路由挂载：`/api/question-notebook`（`deeptutor/api/main.py:675-679`）。

### 2.4 assessment 判定

共享枚举（`deeptutor/core/assessment.py:5-10`）：source ∈ `deep_question|mastery_path|immersive_reading|book|partner_chat|import`。

统一适配器 `record_assessment`（`deeptutor/learning/assessment.py:426-509`）：身份校验（:186-200）、result/is_correct 归一（:50-73、:245-263）、投影题库行 `to_notebook_item`（:390-423）、写 attempt 日志并把带 objective 链接的证据回写 mastery 复习调度（:441-502、:301-387）。

各来源判定方式：

| 来源 | 判定方 | 落库点 |
| --- | --- | --- |
| deep_question | **客户端** `isAnswerCorrect` + AI judge WS（`deeptutor/api/routers/quiz_judge.py:226-227`；前端 `web/lib/quiz-judge.ts:40`） | `QuizViewer.tsx:501` 提交 is_correct → upsert/quiz-results |
| mastery_path | 服务端 tutor 工具判分 | `_sync_mastery_attempt_to_question_bank`（`deeptutor/capabilities/mastery/tools.py:341-408`，record :401；调用点 :1321、:1660）、qualitative :411-458 |
| immersive_reading | 服务端 `selected_index == correct_choice_index`（`deeptutor/api/routers/reading_extensions.py:413-421`） | `submit_quiz_answers`（:363-459，record :435）；题目先存 `reading_quiz_pending`（:350-360） |
| book | 服务端复核 `_verified_choice_grade`（`deeptutor/api/routers/book.py:1139-1140`） | `/api/books/quiz-attempt`（:1102-1199，record :1173） |
| partner_chat | partner 会话 agent 显式记录 | `question_bank` 工具 `_record`（`deeptutor/tools/question_bank.py:404-467`，origin=`external_import` :424-435） |

题库消费侧：练习/错题复习走 `/api/question-notebook/practice/*`（`deeptutor/api/routers/practice.py:103-261`，挂载 `main.py:681-683`）；agent 查询走 `question_bank` 工具（`question_bank.py:470` 起）。

## 3. 关键文件表

| 文件 | 职责 |
| --- | --- |
| `deeptutor/runtime/capability_routing.py` | chat→deep_question 规则路由 |
| `deeptutor/services/session/turns/request_preparer.py` | turn 准入、路由调用、config 校验 |
| `deeptutor/agents/question/capability.py` | deep_question capability（custom/mimic/followup 分派） |
| `deeptutor/agents/question/pipeline.py` | explore→plan→逐题生成与事件广播 |
| `deeptutor/agents/question/history.py` | 从题库表读会话出题历史 |
| `deeptutor/api/routers/question.py` | 出题任务状态/结果 API（`/api/question`） |
| `deeptutor/api/routers/sessions.py:696` | `POST /{id}/quiz-results`（前端批量上报） |
| `deeptutor/api/routers/question_notebook.py` | 题库 CRUD/upsert/分类/统计 |
| `deeptutor/services/session/sqlite_store.py:375` | `notebook_entries`/`assessment_attempts` schema 与实现 |
| `deeptutor/learning/assessment.py` | 判定记录统一适配器（投影+attempt+证据回写） |
| `deeptutor/core/assessment.py` | source/origin/result 枚举 |
| `deeptutor/capabilities/mastery/tools.py:341` | mastery 判分同步题库 |
| `deeptutor/api/routers/reading_extensions.py:363` | 阅读测验判分入库 |
| `deeptutor/api/routers/book.py:1102` | 书本 focus-check 入库 |
| `deeptutor/tools/question_bank.py` | agent 查询/记录题库工具 |
| `deeptutor/api/routers/quiz_judge.py:226` | AI 判分 WebSocket `/ws/questions/judge` |
| `deeptutor/api/routers/practice.py` | 练习/复习 API（读题库） |
| `web/features/chat/messages/ChatMessageList.tsx:743` | 题目事件抽取与 QuizViewer 挂载条件 |
| `web/components/quiz/QuizViewer.tsx` | 答题、判分展示、**触发入库** |
| `web/lib/quiz-types.ts` | 事件→QuizQuestion 解析、turn_id 提取 |
| `web/lib/notebook-api.ts` | 题库 HTTP 客户端 |
| `web/lib/practice-api.ts:2` | 练习 API 客户端 |
| `web/components/space/question-bank/useQuestionBank.ts:149` | 题库列表页数据源 |

## 4. 扩展点

1. **聊天出题入库（#575 主诉）**：生成端最自然的挂点是 `QuestionPipeline` 结果 envelope（`pipeline.py:609-614`）或 `DeepQuestionCapability.run` 收尾处服务端 upsert；聊天（capability=chat）手写题目则需要在 turn 结束处新增提取器——目前两条路都不存在。
2. **路由规则**：加句式进 `_QUIZ_PATTERNS`（`capability_routing.py:37-44`）；默认开关在 `runtime_settings.py:40`，注意 workspace 不路由的护栏（:72-73）是有意设计。
3. **新题型**：pipeline `QuizType`（`pipeline.py:156`）+ 归一化 :187/:208；前端题型归一在 `web/lib/quiz-types.ts`。
4. **新 assessment source**：枚举 `core/assessment.py:5-7`；注意 `AssessmentRecord._normalize_source` 对未知值**静默回落 `deep_question`**（`learning/assessment.py:115-119`）。
5. **题目追问**：`buildQuizFollowupConfig`（`web/lib/quiz-types.ts:217-247`）→ executor metadata（`executor.py:950`）→ `FollowupAgent`（`capability.py:74-108`）；回写 `followup_session_id` 走 `PATCH /entries/{id}`（`question_notebook.py:451-460`；前端 `web/context/QuizFollowupContext.tsx:268`）。
6. **独立录入**：`external_import` origin 已支持无会话条目（`question_notebook.py:191-203` 校验；partner `_record` 即用此通道）。

## 5. 已知坑

1. **路由默认关**：`capability_routing_enabled=False`（`runtime_settings.py:40`），且 workspace 内永不路由（`capability_routing.py:72-73`）——"quiz me" 落回 chat 后即进入坑 2。
2. **chat 里的题目永远不入库**：QuizViewer 只在 `capability==="deep_question"` 时挂载（`ChatMessageList.tsx:744`）；chat 文本没有任何题目提取/入库代码。
3. **deep_question 出题本身也不入库**：pipeline 只广播（`pipeline.py:609-614`）；入库完全靠学习者答题动作（`QuizViewer.tsx:538-543`）——不出题失败，是"没人作答就没记录"。
4. **未答/未全答不写库**：单题 upsert 只在 submit 时调用；批量 `recordQuizResults` 要求全部答完（`QuizViewer.tsx:446`）。
5. **静默失败**：`sessionId/turnId` 缺失直接 return（`QuizViewer.tsx:479`）；upsert 异常 `catch {}`（:531-533）；服务端 upsert 失败仅 warning（`sessions.py:717-720`）。三者叠加时用户无感知。
6. **legacy 题卡本地化**：无 turn_id 的事件流使题卡不读写题库（`quiz-types.ts:171-184`）。
7. **出题历史失忆连锁**：`load_session_quiz_history` 只信题库表（`history.py:14`）——上面任何断点吞掉写入，后续出题的去重/补弱也会失效。
8. **书本 quiz block 无会话落库**：复用 pipeline 但 `session_id=f"book-{book_id}"` 且流到 book bus（`book/blocks/quiz.py:53,63`），不走 quiz-results 端点。
9. **source 静默回落**：未知 source 被归一成 `deep_question`（`learning/assessment.py:115-119`），统计口径可能被悄悄污染。

## 6. 「出题结果未持久化」可疑断点清单（对应 #575）

按发生顺序排查：

1. 路由未启用或命中 workspace 护栏 → 请求停在 chat → 断点 2/坑 1（`capability_routing.py:70-73`、`runtime_settings.py:40`）。
2. 消息 capability 非 `deep_question` → QuizViewer 不挂载 → 没有任何写库方（`ChatMessageList.tsx:744`）。
3. QuizViewer 挂载但 `sessionId`/`turnId` 为空 → upsert 静默跳过（`QuizViewer.tsx:479`；turn_id 提取失败见 `quiz-types.ts:175-184`）。
4. 学习者未提交答案 / 未答完 → 无 upsert、无 quiz-results（`QuizViewer.tsx:446,538-543`）。
5. upsert 请求失败被吞（`QuizViewer.tsx:531-533`）或服务端失败仅告警（`sessions.py:717-720`）。
6. 写入成功但唯一键 `(origin_type, origin_ref, turn_id, question_id)` 冲突被去重误判（`sqlite_store.py:412`；question_id 为位置编号 `q_1..q_N`，见 `quiz-types.ts:163-165` 注释）。

## 7. 测试清单与覆盖空白

后端（`timeout 900 python -m pytest -q -p no:cacheprovider <路径>`）：

- 路由：`tests/runtime/test_request_contracts_subagent.py:37-91`（规则 + workspace 负例）、`tests/services/session/test_capability_routing.py`（默认关 :99、单轮开启 :115/:146、模式保持 :176/:219）。
- 生成：`tests/agents/question/test_pipeline.py`、`test_mimic_source.py`、`test_language_prompts.py`。
- 出题 API：`tests/api/test_question_router.py`。
- 题库 HTTP/存储：`tests/api/test_notebook_router.py`、`test_main_notebook_router.py`、`test_notebook_api_contract.py`、`test_question_bank_api.py`、`tests/services/test_notebook_service.py`、`tests/cli/test_notebook_cli.py`。
- 判定：`deeptutor/learning/tests/test_assessment.py`（归一/去重/链接回写）、`tests/api/test_book_quiz_attempt_notebook.py`、`tests/api/test_reading_quiz_answers.py`、`tests/api/test_quiz_judge_unit.py`。
- 工具/来源：`tests/tools/test_question_bank_tool.py`、`test_list_notebook.py`、`tests/reading/test_quiz.py`、`tests/book/test_quiz_extraction.py`。

前端（vitest/playwright，`web/tests/`）：

- `quiz/QuizViewer.smoke.spec.tsx`（提交后 upsert 断言 :250 附近；未提交不写库 :300-303）。
- `quiz-turn-id.test.ts`、`quiz-followup-writeback.spec.tsx`、`reading-quiz-persistence.spec.tsx`、`question-bank-*.test.ts|spec.tsx`、`mastery-question-card.spec.tsx`、`conversation-notebook-save.test.ts`。

覆盖空白（执行 #575 时需要补的回归面）：

1. **chat capability 出题如何入库——无任何测试，因为路径不存在**（坑 2）；这是 #575 的直接缺口。
2. "已生成未作答的题目应否在题库可见" 无测试（坑 3/4）；现有 smoke 只覆盖"提交即写"。
3. upsert 静默失败（`QuizViewer.tsx:531-533`）与 quiz-results 服务端失败（`sessions.py:717-720`）无断言可观测性的测试。
4. quiz-results 端点仅 `tests/api/test_notebook_router.py` 间接触及，缺"全部答完才上报"的端到端用例。
5. `q_1..q_N` 位置编号跨 quiz 撞唯一键的去重语义（`sqlite_store.py:412`）缺回归测试。
