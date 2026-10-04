# guide: 测验域导读（出题→判分→追问→进度）

- 基线：`origin/main` @ `f07029cfc`（release v1.6.13），worktree 分支 `guide/quiz-20261004`
- 性质：研究型导读，未改任何代码；全部 `path:line` 均以该 commit 为准
- 范围：出题入口、题目结构、判分（含 #1691 历史缺陷）、追问处理、结果写回学习记录；标注易错点与测试空白

---

## 1. 链路总览（文字版）

```
┌─ 出题入口（3 条活路 + 1 条死路）──────────────────────────────┐
│ A. 自定义出题（主链，测验 UI）                                 │
│   QuizConfigPanel 表单 → buildQuizWSConfig(web/lib/quiz-types.ts:300)
│   → WS start_turn capability="deep_question" (ChatWorkspace.tsx:1624)
│   → request_preparer.py:293 校验 config（request_contracts.py:51-66）
│   → DeepQuestionCapability.run (agents/question/capability.py:39-181)
│   → QuestionPipeline._run_inner (pipeline.py:515-614)
│       Phase1 _explore(:619) → Phase2 _plan(:708) → Phase3 _quiz_one(:876)×N
│       （每题含一次 _repair_quiz_payload(:969) 修复机会）
│ B. 仿卷出题：mimic 模式（capability.py:183-353，MinerU 解析 → templates_override）
│ C. 纯聊自动路由：capability_routing.py:37-85（仅 requested=chat 时正则命中 quiz 意图）
│ D. 遗留 WS 路由 /ws/questions/generate（api/routers/question.py:359-578）
│    —— 已损坏：调用 coordinator.generate_from_topic 时传 preference=/question_type=，
│       与 coordinator.py:66-74 签名不符，运行时 TypeError        │
└──────────────────────────────────────────────────────────────┘
        │ 产出 QuizPair（pipeline.py:346-361）
        ▼
┌─ 题目结构 ────────────────────────────────────────────────────┐
│ 后端 QuizPair（question/question_type/correct_answer/options/  │
│ explanation/topic/difficulty/metadata.issues）                 │
│   ↔ 线上 dict _qa_pair_to_dict(:1952-1963)（topic 键仍叫 concentration）
│   ↔ 前端 QuizQuestion（web/lib/quiz-types.ts:45-55）           │
│ 无 pydantic 校验模型；校验是手写的 _normalize_quiz_payload(:1406)│
│ + _collect_quiz_issues(:1450)；修不好的题以"[Generation failed]" │
│ 兜底出卷（:1495-1497）                                         │
└──────────────────────────────────────────────────────────────┘
        ▼
┌─ 判分（5 条互相独立的链，语义/信任边界各不相同）───────────────┐
│ 1) QuizViewer 纯前端判分 isAnswerCorrect(QuizViewer.tsx:172-189)│
│    → is_correct 上送（:501）→ POST /api/sessions/{id}/quiz-    │
│      results (sessions.py:572-603) 与 notebook upsert 均信任之  │
│ 2) AI Judge WS /ws/questions/judge (quiz_judge.py:226-227)     │
│    仅建议性文本反馈，不落分，correct_answer 由客户端自带        │
│ 3) 精通之道 mastery_quiz/mastery_grade：服务端确定判分          │
│    出题 _shuffle_choice_options(tools.py:290-314)（#1692，修 #1691）│
│    → PendingQuestion 注册 (learning/service.py:640-719)        │
│    → 答案先落库 (learning_adapter.py:74-115) → 导师首 token 前  │
│      确定判分 (executor.py:796-812 → learning_adapter.py:117-210)│
│ 4) 阅读 Focus-Check：服务端判 selected_index                   │
│    (reading_extensions.py:363-481)，但答案键随题下发            │
│    (reading/quiz.py:131)，且无 shuffle                          │
│ 5) 书本 Focus-Check：前端判分 (QuizBlock.tsx:171-198)，服务端    │
│    存 is_correct；_verified_choice_grade(book.py:185-206) 只影响 │
│    mastery 关联，不改已存判定                                   │
└──────────────────────────────────────────────────────────────┘
        ▼
┌─ 追问（quiz 卡片内的追问聊天）────────────────────────────────┐
│ QuizViewer.handleOpenFollowup(:735-771) → QuizFollowupContext   │
│ .openFollowupTab(:552-556) → FollowupChatComposer 首发组装       │
│ buildQuizFollowupConfig(quiz-types.ts:217-247，含题干/正确答案/ │
│ 用户答案/is_correct/ai_judgment/图片) → WS start_turn，          │
│ capability="chat" (QuizFollowupContext.tsx:452-468)             │
│ → 服务端新会话 (request_preparer.py:174 ensure_session)         │
│ → executor.py:532-545 注入一次性 system 上下文                   │
│   (_turn_runtime_shared.py:1351-1470)                           │
│ → session 事件触发回写 followup_session_id                       │
│   (QuizFollowupContext.tsx:280-285，静默 catch，PR #1701 在途)   │
│ 注：FollowupAgent(followup_agent.py:15-118) 只在 deep_question  │
│ 能力 + question_followup_context 元数据路径可达                  │
│ (capability.py:74-108)，quiz UI 追问走的不是它                   │
└──────────────────────────────────────────────────────────────┘
        ▼
┌─ 结果写回学习记录 ────────────────────────────────────────────┐
│ 三个面（mastery / book / reading）汇合同一接缝：                 │
│ record_assessment (learning/assessment.py:425-508)              │
│ → SQLiteSessionStore.record_assessment (sqlite_store.py:3246-   │
│   3365)：BEGIN IMMEDIATE；attempt_id 幂等去重；assessment_      │
│   attempts 不可变追加；notebook_entries 只留最新投影             │
│ → 跨面保留 _apply_linked_retention(assessment.py:300-386)：     │
│   迟到事件按 evidence 顺序重放(:352-362)，重启对账 reconcile_    │
│   linked_assessments(:511-537)                                  │
│ → mastery 聚合（mastery.sqlite3）：_apply_grade(service.py:509-  │
│   575) → QuizAttempt 追加 + ErrorRecord 生命周期(:403-455) +    │
│   LearningEvidence(:577-605) + compute_mastery(mastery.py:24-37)│
│   + SRS 调度(scheduler.py:231,398)，BEGIN IMMEDIATE + 修订号 CAS │
│   (storage.py:1092-1206)                                        │
│ 前端读侧：web/lib/learning-records-api.ts:27-31                  │
│   GET /api/mastery-paths/reading/records (mastery_path.py:498-503)│
└──────────────────────────────────────────────────────────────┘
```

---

## 2. 环节详解

### 2.1 出题入口

| 环节 | 位置 |
|---|---|
| 表单与 per-type 配平 | `web/components/quiz/QuizConfigPanel.tsx:67-100,124-152` |
| WS config 组装（含 count 有效性前端守卫） | `web/lib/quiz-types.ts:300-325`（守卫 `:313-317`；默认值 `:34-43`） |
| 触发点 | `web/features/chat/components/ChatWorkspace.tsx:683,1981`；`web/components/chat/home/StandaloneComposer.tsx:687,732,825` |
| 能力注册/清单 | `deeptutor/runtime/bootstrap/builtin_capabilities.py:39,99-108`；`deeptutor/agents/question/capability.py:29-37` |
| 纯聊自动路由（quiz 意图正则） | `deeptutor/runtime/capability_routing.py:37-44,49-85` |
| 后端准入与 config 校验 | `deeptutor/services/session/turns/request_preparer.py:256-275,293-304`；契约 `deeptutor/runtime/request_contracts.py:51-66`（`extra="forbid"`，num_questions 1–50，max_questions 1–100） |
| 自定义模式运行 | `deeptutor/agents/question/capability.py:124-167`（空题守卫 `:54-63`；历史回灌 `history.py:34-100`） |
| mimic 模式 | `deeptutor/agents/question/capability.py:183-353`（PDF 上传 `:248-295`；错误兜底 `:347-353`） |
| 遗留路由（死路） | `deeptutor/api/routers/question.py:49-356`（mimic 仍可用）、`:359-578`（generate，见易错点 E2） |

Pipeline 内部：阶段常量 `pipeline.py:95-97`；默认预算 `:139-153` + `deeptutor/services/config/loader.py:314-320`；温度硬编码 0.4 `:439`；prompt 装载 `:441-452`（`prompts/en/pipeline.yaml`：explore `:37-120`、summarizer `:129-144`、plan `:149-188`、quiz_step `:193-265`、repair `:270-293`；zh 副本 336 行 vs en 356 行，无一致性断言）。

### 2.2 题目结构

| 项 | 位置 |
|---|---|
| `QuizPair` 数据类 | `deeptutor/agents/question/pipeline.py:346-361` |
| 类型枚举与选择键 | `pipeline.py:156-168`（choice/concept/fill_in_blank/short_answer/written/coding）、`:171` `_CHOICE_KEYS=("A","B","C","D")` |
| 归一化与问题收集 | `pipeline.py:1406-1448`（normalize）、`:1450-1486`（issue 码：`missing_question`、`choice_options_must_be_a_to_d` 等） |
| 一次性修复 | `pipeline.py:969-1040`（repair，二次 reasoning 重试 `:1013-1039`） |
| 失败兜底出卷 | `pipeline.py:1495-1497`（`"[Generation failed] <topic>"`） |
| 前端类型与解析 | `web/lib/quiz-types.ts:45-55`（`QuizQuestion`）、`:98-116`（从 qa_pair 构建）、`:132-158`（流式抽取，按 `call_kind==="quiz_question_emitted"` 去重）、`:190-208`（result 抽取） |
| 渲染消费 | `web/features/chat/messages/ChatMessageList.tsx:741-758` → `web/components/quiz/QuizViewer.tsx` |
| 笔记本存储（题目落地） | `deeptutor/api/routers/question_notebook.py:275-321`（upsert）、`:351-403`（list）、`:406-439`（lookup）、`:442-482`（get/patch/delete）；store `deeptutor/services/session/sqlite_store.py:3091-3181`（ON CONFLICT(origin_type,origin_ref,turn_id,question_id)） |
| 题库工具（agent 侧） | `deeptutor/tools/question_bank.py`（record `:404-467`，content-hash question_id `:367-372`） |

### 2.3 判分（含 #1691 历史）

#1691（上游 issue，已关闭）："精通之道"选择题答案全部是 A。修复为 PR #1692：`_shuffle_choice_options`（`deeptutor/capabilities/mastery/tools.py:290-314`，调用点 `:947`）——在服务端校验/去回显之后对选项做 OS 种子 shuffle，label 按新位置重发，`expected` 答案跟随题身迁移，注册与判分始终比较同一表示；回归测试 `tests/capabilities/test_mastery_choice_shuffle.py:96-136`。

| 判分面 | 位置 | 信任边界 |
|---|---|---|
| QuizViewer（独立测验） | `web/lib/quiz-judge.ts` + `QuizViewer.tsx:172-189,501` → `deeptutor/api/routers/sessions.py:572-603`、`question_notebook.py:158-203` | 客户端判分，服务端全信 `is_correct` |
| AI Judge WS | `deeptutor/api/routers/quiz_judge.py:226-227,263`（鉴权 `ws_require_auth`） | 仅建议性反馈，不落分 |
| 精通之道 | `tools.py:1099-1285`（grade 工具）→ `learning/grading.py:13-49`（choice=strip+lower+去空格相等）→ `service.py:832-983`（幂等事务） | 服务端确定判分，fail-closed |
| 阅读 Focus-Check | `deeptutor/api/routers/reading_extensions.py:363-481`（整批校验先行 `:387-401`） | 服务端判 `selected_index`；但答案键随题下发（`reading/quiz.py:131`） |
| 书本 Focus-Check | `QuizBlock.tsx:171-198`（前端）→ `deeptutor/api/routers/book.py:1102-1218`；`_verified_choice_grade` `:185-206` | 服务端存前端 `is_correct`；复核仅影响 mastery 关联 |

判分语义细节：mastery 选择题为 strip+lower+去空格全等（`grading.py:13-49`），无全角/半角与 LaTeX 归一化；不可读的选择提交按"拒判"处理而非记错（`tools.py:457-473`）；无法解析答案时 fail-closed 记错（`grading.py` 无键即 wrong）。

### 2.4 追问处理

| 环节 | 位置 |
|---|---|
| 打开追问页签 | `QuizViewer.tsx:735-771`（携带 `notebookEntryId`/`followupSessionId`）→ `QuizFollowupContext.tsx:552-556` → `SessionViewerPanel.tsx:437-469` |
| 历史水合 | `QuizFollowupTabBody.tsx:91-124`（失败静默 `:110-112`） |
| 首发组装（题目上下文打包） | `FollowupChatComposer.tsx:60-140`（`isFirstSend` `:52`）→ `web/lib/quiz-types.ts:217-247` |
| 发送/会话管理 | `QuizFollowupContext.tsx:388-497`（`capability:"chat"` `:452`；`followup_question_context` 顶层外发 `:460-468`） |
| 服务端会话创建 | `deeptutor/services/session/turns/request_preparer.py:174`（session_id 为空即建新会话） |
| 上下文注入（一次性 system 消息） | `deeptutor/services/session/turns/executor.py:532-545,930`；提取 `deeptutor/services/session/_turn_runtime_shared.py:1105-1152`；渲染 `:1351-1470` |
| session-id 回写（当前态） | `QuizFollowupContext.tsx:280-285` —— `updateNotebookEntry(...).catch(() => {})`，静默吞掉 PATCH 失败；`persistFollowupSessionId` 在本分支不存在（PR #1701 未合入） |
| 回写链路后端 | `web/lib/notebook-api.ts:432-450` → `question_notebook.py:451-460`（`followup_session_id` 在 `:97` 更新白名单）→ `sqlite_store.py:4167-4196,394,698` |
| 回读闭环 | `QuizViewer.tsx:258-274`（lookup 无 turnId 即放弃 `:263`） |
| deep_question 路径的 FollowupAgent | `deeptutor/agents/question/agents/followup_agent.py:15-118`；进入条件 `capability.py:74-108`（quiz UI 不走此路） |

### 2.5 结果写回学习记录

| 环节 | 位置 |
|---|---|
| 接缝：`record_assessment` | `deeptutor/learning/assessment.py:425-508`（结果冲突消解 `:244-262`；可信关联 `:280-291`） |
| 不可变尝试账本 + 最新投影 | `deeptutor/services/session/sqlite_store.py:3246-3365`（attempt_id 去重+冲突检测 `:3266-3295`；immuatable insert `:3325-3349`） |
| 跨面保留（book/reading → mastery） | `assessment.py:300-386`（迟到事件按序重放 `:352-362`；重启对账 `:511-537`） |
| mastery 主链落库 | `learning/service.py:832-983`（`grade_interaction`）→ `_apply_grade` `:509-575`：QuizAttempt+ErrorRecord `:403-455`、LearningEvidence `:577-605`、mastery 重算 `:457-468` → `learning/mastery.py:24-37`、SRS `learning/scheduler.py:231,398` |
| 事务与并发 | `learning/storage.py:1092-1206`（BEGIN IMMEDIATE `:1109` + 修订号 CAS `:1140-1162`；投影入事务 `:679-754`）；路径租约 `:1889` + `learning_adapter.py:307-339` |
| mastery → 题库尽力同步 | `tools.py:341-405`（失败仅告警 `:396-404`；`mastery_grade` 重放修复 `:1188-1221`） |
| 书本面写回 | `deeptutor/api/routers/book.py:1102-1218`（先存进度 `:1135-1136`，后写笔记本 `:1137-1217`；幂等由 `book/progress.py:70-107` submission_id 保证） |
| 阅读面写回 | `reading_extensions.py:363-479`（整批校验 `:387-401`；星星奖励 `:470-479`） |
| 记录模型 | `deeptutor/learning/models.py:119-134`（QuizAttempt，含 voided）、`:145-157`（ErrorRecord）、`:160-183`（LearningEvidence）、`:243-291`（PendingQuestion）、`:532-582`（LearningProgress 聚合） |
| 结果后策略 | `deeptutor/learning/policy.py:36-46,82-90,225-326`（量化门 0.9；quiz 正确性永远打不开 CONCEPT/DESIGN 定性门） |
| 多用户边界 | `deeptutor/multi_user/learning_access.py:34-60,63-87`；`reading_extensions.py:366-367`；面映射 `deeptutor/api/routers/auth.py:646-647` |

---

## 3. 易错点清单（可拆修复卡 ✂）

| # | 问题 | 位置 | 说明 | 可拆卡 |
|---|---|---|---|---|
| E1 | 出题 pipeline 无答案位置 shuffle | `pipeline.py:1406-1448`（归一化原样保留模型给的键）、`prompts/en/pipeline.yaml:229`（仅要求选项形似，未约束正确项分布） | #1691 同款风险在自定义出题链完全存活；mastery 已修（#1692），此处未修。修不好时静默全 A | ✂ 修复卡：pipeline 出题后对 choice 题做服务端 shuffle（对齐 `_shuffle_choice_options` 模式）或约束 prompt+分布检查（issue 码可复用 `_collect_quiz_issues`） |
| E2 | 遗留路由 `/ws/questions/generate` 已损坏 | `api/routers/question.py:487-493` vs `coordinator.py:66-74` | 传入 `preference=`/`question_type=`，签名不符 → 运行时 TypeError；且 `tests/api/test_question_router.py:123-149` 只测 mimic，从未覆盖 | ✂ 修复卡：对齐签名或移除死路由 |
| E3 | pipeline.py 重复定义 4 个辅助函数 | `:187/:249`、`:208/:267`、`:235/:295`、`:241/:302` | 后一组静默遮蔽前一组，两组渲染文案不同（"auto" vs "any (planner picks…)"）；改前一组是死代码 | ✂ 修复卡：删重，保留一组 |
| E4 | 追写 session-id 静默失败 | `QuizFollowupContext.tsx:280-285`（`.catch(() => {})`） | PATCH 失败后 entry 永远缺 `followup_session_id`，追问线程刷新即孤儿。**PR #1701 已在途**（persistFollowupSessionId+重试+可见报错），待合 | ✂ 复核/跟催 #1701；合后补本面回归 |
| E5 | entryId 为空时回写整体跳过 | `QuizFollowupContext.tsx:281` + `QuizViewer.tsx:263` | 答案未落库（无 turnId）时先开追问 → 会话建了但永不回链，静默丢失 | ✂ 修复卡：延迟回链或 lookup 重试 |
| E6 | 水合与首发竞态 → 双会话 | `QuizFollowupTabBody.tsx:91-124`（异步）vs `FollowupChatComposer.tsx:52`（同步 isFirstSend） | 水合进行中发送 → session_id:null → 服务端第二个会话，旧历史被丢弃 | ✂ 修复卡：发送前等待水合完成/加 guard |
| E7 | 客户端可信判分面过大 | `QuizViewer.tsx:501`、`sessions.py:585-596`、`question_notebook.py:166`（options 任意 dict） | `is_correct` 由浏览器决定直接入库；错题本/掌握度被客户端 verdict 污染 | ✂ 修复卡：服务端按 correct_answer 复核（可参照 `_verified_choice_grade` 思路），至少对 choice 题 |
| E8 | 阅读 quiz 答案键随题下发且无 shuffle | `reading/quiz.py:131`（payload 含 `correct_choice_index`） | F12 可见答案；且与 #1691 同款"正确项位置偏置"风险 | ✂ 修复卡：下发前去答案 + shuffle（需同步改判分取键方式） |
| E9 | mastery→题库同步失败静默 | `tools.py:396-404,446-454`（宽 except + 5s wait_for） | 已持久化的 mastery 尝试可能永久缺失于错题本；靠 grade 重放补救（`:1188-1221`）但无测试证明该补救 | ✂ 补测卡：首同步失败→重放成功的端到端用例 |
| E10 | 书本 Focus-Check 部分更新 | `book.py:1135-1136`（先存进度）→ `:1208-1217`（笔记本失败 500） | 进度已存、写回失败返回 500；幂等靠前端复用 submission_id（`BooksRoute.tsx:878-882`），该复用逻辑无测试 | ✂ 补测卡 |
| E11 | `per_type_counts` 总和校验仅在前端 | `web/lib/quiz-types.ts:313-317` vs `request_contracts.py:61-64`、`pipeline.py:808-871`（_parse_plan 不查分布） | 直连 WS 可传不合分布的 config；后端自由发挥 | ✂ 补测/修复卡 |
| E12 | 语言包无 parity 断言 | `prompts/en/pipeline.yaml`(356 行) vs `prompts/zh/pipeline.yaml`(336 行) | zh 缺段静默回退 en，出题行为随语言漂移 | ✂ 补测卡：键集合 parity 测试 |
| E13 | 追问无取消 + 线程键碰撞 | `FollowupChatComposer.tsx:142-146`（no-op）、`QuizViewer.tsx:134-136`（裸 question_id 键） | 多 viewer 实例同 id 共享线程态 | ✂ 修复卡（低优） |

## 4. 测试空白清单（可拆补测卡 ✂）

| # | 空白 | 证据 | 建议 |
|---|---|---|---|
| T1 | 出题 pipeline 自定义模式无全链测试 | `tests/agents/question/test_pipeline.py` 只有 mimic 全链（`:678`）与单元片；explore→plan→quiz 存根链路无用例 | ✂ 补测卡 |
| T2 | 答案位置分布无测试 | 对照 `tests/capabilities/test_mastery_choice_shuffle.py`；`tests/agents/question/` 无任何分布断言 | ✂ 与 E1 修复卡同行 |
| T3 | `/ws/questions/generate` 无测试 | `tests/api/test_question_router.py:123-149` 仅 mimic | ✂ 与 E2 修复卡同行 |
| T4 | 追问前端上下文/控制器零测试 | `web/tests/` 仅源码正则挂载断言（`reading-v2-surface.test.ts:99` 等）；回写静默 catch、水合、sendMessage 载荷、E5/E6 全无覆盖 | ✂ 补测卡（E4 合入后最有价值） |
| T5 | notebook PATCH `followup_session_id` 无路由测试 | `tests/api/` 零匹配（store 层有 `test_sqlite_store.py:709-715`） | ✂ 补测卡 |
| T6 | AI Judge WS 无行为测试 | `tests/` 无 `quiz_judge` 用例（鉴权/payload/错误路径均未测） | ✂ 补测卡 |
| T7 | `grade_answer` 无全角/LaTeX 归一化覆盖 | `deeptutor/learning/tests/test_grading.py` 未含全角字符/`$...$` 变体 | ✂ 补测卡 |
| T8 | 书本 quiz-attempt verdict 篡改无回归 | `tests/api/test_book_quiz_attempt_notebook.py` 测判分矩阵与幂等，但 `is_correct=false, actual=correct` 的错配 verdict 无用例 | ✂ 补测卡（E7 相关） |
| T9 | `learning_adapter` 答案先落库承诺仅间接断言 | `_commit_mastery_card_answer`（`learning_adapter.py:74-115`）、`_release_superseded_lease`（`:41-72`）无直接单测 | ✂ 补测卡 |
| T10 | `_sync_qualitative_to_question_bank` 无测试 | `tools.py:407-454`；`tests/capabilities/test_mastery_capability.py:416-433` 只测 quiz 同步 | ✂ 补测卡 |
| T11 | `LearningConflictError` 与 `grade_and_record` 竞态无覆盖 | `service.py:470-507`（save+CAS 非事务路径）仅 storage 单元片 | ✂ 补测卡 |
| T12 | `BooksRoute.handleQuizAttempt` submission_id 复用无前端测试 | `BooksRoute.tsx:878-882` | ✂ 补测卡 |

覆盖良好（无需拆卡）：notebook 路由（`test_notebook_router.py`，18 例）、题库工具（`test_question_bank_tool.py`，15 例）、mastery 引擎工具（`test_mastery_tools.py`，70 例）、assessment 迟到重试/对账（`test_assessment.py:318,373-450`）、书本写回（`test_book_quiz_attempt_notebook.py`）、追问一次性上下文注入（`test_unified_ws_turn_runtime.py:813-919`）、mastery 状态完整性（`test_mastery_state_integrity.py`）。

## 5. 关联在途工作

- **PR #1701**（open，目标 dev）：`fix(web): surface quiz follow-up session-id writeback failures` —— 正对 E4；本导读已核实其前提在本分支成立（`QuizFollowupContext.tsx:284` 静默 catch 仍在，`persistFollowupSessionId` 不存在）。合并后 E4 关闭，T4 的价值上升。
- **#1691 / #1692**：mastery 面 shuffle 已修已测；本导读确认自定义出题链（E1）与阅读面（E8）仍暴露同类风险。
- 判分链详细测绘已另发于本卡评论（2026-10-04 21:34 UTC，"QUIZ JUDGING/SCORING CHAIN 已完整测绘"），与本报告第 2.3 节一致。
