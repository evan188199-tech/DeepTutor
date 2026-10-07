# Learning 域全景导读（deeptutor/learning）

基线：origin/main `f07029cfc`（v1.6.13）。所有 `path:line` 均在该基线逐一核对；本文为纯导读，不改产品代码。

## 边界声明

本包是 Mastery Path 的**引擎层**（模型 / 存储 / 调度 / 判分 / 策略 / 事件）。以下内容归姊妹导读，本文不展开：

- **会话内 quiz 出题与判分工具链**（mastery_quiz / mastery_grade 等）→ guide-quiz（`myfork/guide/quiz-20261004` 分支 `evidence/quiz-guide-20261004/report.md`）。
- **Mastery tutoring 回合流转、锁与前端** → guide-mastery（`myfork/docs/guides/mastery-path` 分支 `docs/guides/mastery-path.md`）。
- **练习域**（`deeptutor/services/practice`，另一套独立调度/存储）→ guide-practice-domain（`myfork/guide/practice-domain-20261006` 分支 `docs/guides/practice.md`）。
- 本文只写本域全景与三者的**衔接面**。

## 0. 子包地图

| 子模块 | 行数 | 职责 |
| --- | --- | --- |
| `models.py` | 614 | Pydantic 聚合与值对象：`KnowledgeType`（`models.py:24`）、`PendingQuestion`（`:243`）、`MasteryInteraction`（`:310`）、`LearningProgress` 主聚合（`:439`） |
| `storage.py` | 2060 | 事务性 SQLite 持久化 + V1 JSON 惰性导入；`LearningStore`（`storage.py:348`） |
| `service.py` | 1915 | 业务编排 `LearningService`（`service.py:266`）：判分流水线、交互生命周期、模块替换、修复 |
| `scheduler.py` | 544 | 间隔重复：`SpacedRepetitionScheduler`（`scheduler.py:127`）、可插拔 `RetentionScheduler` 协议（`:65`） |
| `policy.py` | 515 | 纯决策无 I/O：精通门 `is_mastered`（`policy.py:103`）、下一步 `next_objective`（`:219`）、地图 `map_summary`（`:329`） |
| `grading.py` | 64 | 确定性判分 `grade_answer`（`grading.py:13`）+ 粗错误分类 `classify_error`（`:52`） |
| `mastery.py` | 40 | 精通分公式 `compute_mastery`：新近加权 + 低置信上限（`mastery.py:17`、`:21`、`:24`） |
| `assessment.py` | 557 | 跨面评测统一写回适配器：`record_assessment`（`assessment.py:425`） |
| `event_hub.py` | 140 | 进程内低延迟唤醒（非数据面）：`MasteryTopicEventHub`（`event_hub.py:55`） |
| `migration.py` | 324 | 一次性 workspace V1→V2 迁移：`prepare_mastery_v2_root`（`migration.py:314`） |
| `navigation.py` | 348 | 只读图集浏览（REST + chat 导航工具共用）：`topic_cards`（`navigation.py:87`） |
| `pending.py` | 283 | 待答题的公开投影与选择题标签/答案翻译：`public_pending_question`（`pending.py:245`）、`resolve_choice_submission`（`:139`） |
| `question_card.py` | 118 | 出题卡片形状与判分结果卡：`QUESTION_CARD_KEY`（`question_card.py:38`）、`build_question_card`（`:57`） |
| `identity.py` | 67 | path id 规则唯一入口：`resolve_mastery_path_binding`（`identity.py:42`） |
| `objective_relations.py` | 181 | 目标关系（先修/来源引用）结构与校验：`validate_objective_relations`（`objective_relations.py:72`） |
| `topic_generation.py` | 594 | 主题路线 LLM 生成：`generate_topic_draft`（`topic_generation.py:527`）、`materialize_modules`（`:308`） |
| `topic_materials.py` | 583 | 混合来源素材装载（书/笔记/会话/题库/co-writer）：`build_topic_materials`（`topic_materials.py:417`） |
| `topic_naming.py` | 166 | 目标命名 LLM 小调用，失败回退截断：`suggest_topic_name`（`topic_naming.py:114`） |
| `prompts.py` + `prompts/{en,zh}.yaml` | 156 | 提示词按 UI 语言加载：`get_learning_prompts`（`prompts.py:32`） |

## 1. 判分数据流（域内最核心的一条链）

入口有两类，汇合到同一条流水线：

1. **会话内答题**：`LearningService.grade_interaction`（`service.py:832`）在单个事务内完成——取活跃 `MasteryInteraction`、恢复选择题可读答案（`#1004` 修复，`service.py:877-904`）、调 `_apply_grade`（`:509`）、清 `pending_question` 镜像（`:936-939`）、置 `GRADED` 并发 `attempt.recorded` / `evidence.recorded` / `interaction.graded` 三个事件（`:949-978`）。重试同 `question_id` 幂等回放（`:870-871`）。
2. **直接判分**：`grade_and_record`（`service.py:470`）为非交互路径的同一流水线。

`_apply_grade`（`service.py:509-575`）顺序固定：`grade_answer` 判分（**fail-closed**：无 expected_answer 一律判错，`:525`）→ `record_quiz_attempt` 维护错题簿（`:403`：答错挂 `active/retrying`，答对毕业 `graduated`）→ 追加 `LearningEvidence`（复习重试 quality=0.6，`_record_quiz_evidence` `:577-605`）→ `compute_mastery` 重算精通分（`service.py:457-464`）→ 首次答题初始化 `RepetitionState` 并 `scheduler.schedule_review`（`:566-573`）→ 重建 `review_queue`（`:574`）。质量分与 hints/attempts 的扣减见 `_resolved_quality`（`scheduler.py:505-517`）。

选择题标签/正文/答案归一由 `pending.py` 承担：`parse_options`（`pending.py:79`）、`resolve_choice_submission`（`:139`）、可读性判定 `is_readable_choice_answer`（`:169`，composer 不可读提交的恢复依据）。卡片形状在 `question_card.py`：题卡永不携带 expected_answer/explanation（`question_card.py:63-66`），判分后才由 `build_grade_result`（`:86`）释放答案与解析。

## 2. 调度数据流（间隔重复）

- 类型化冷启动区间 `INTERVAL_SEQUENCES`（`scheduler.py:16-21`）：MEMORY `[0,1,3,7,14,30,60]`、CONCEPT `[3,7,14,30]`、PROCEDURE `[3,7,14]`、DESIGN `[14,28]`。基线是指数遗忘 + 类型先验，**不是 FSRS 拟合**（`RetentionScheduler` 协议注释，`scheduler.py:65-68`）。
- 状态三元组：stability（稳定性天数）、difficulty（0.05–0.95，`schedule_review` 更新 `scheduler.py:283-287`）、retrievability（`retrievability()` `:329-334`）。
- 一次复习转移 `schedule_review`（`scheduler.py:231-327`）：延迟跨面写入只保留审计时间戳、不回退 `last_review_at`（`:243-247`）；**同会话短期重复**（`_SAME_SESSION_DAYS=0.25`，`:46`）只刷新 recall 不乘稳定度、不推迟原复习期限（`:267-278`）；遗忘（quality<0.5）收缩 stability 并记 lapse（`:289-303`）；成功按间隔比/努力度/可学性增稳（`:305-318`）。
- 复习队列由 `build_review_queue`（`scheduler.py:398-432`）全量重建，排序 `review_sort_key`（`:121-124`）：遗忘风险 ↓ → 逾期 ↑ → 类型/错题优先级。风险计算 `forgetting_risk`（`:336-354`：逾期 +错题簿 +lapse 加成）。
- **evidence 是权威**：`replay`（`scheduler.py:475-502`）能从 `LearningEvidence` 列表确定性重建任意 objective 的 `RepetitionState`——`service._recompute_objective_state`（`service.py:1372-1422`）在 void/correct 修复后用它重建，且刻意按 durable append 顺序不按时间戳排序（`#1541`，`service.py:1397-1402`）。
- 目标保留率调整 `set_desired_retention`（`scheduler.py:434-473`）重标定已排间隔，**不算一次评估**（`#1541`）。

## 3. 事件数据流（durable tail + 唤醒 hub 双层）

- **数据面**：事务内 `tx.emit`（`storage.py:134-148`）把事件写入 `mastery_events` 表（schema `storage.py:447-458`，按 `(path_id, revision, id)` 索引）；读回放 `LearningStore.list_events(path_id, after_revision)`（`storage.py:2026-2050`）。事件类型全表见各 emit 调用点（`path.created/saved/renamed/reset`、`topic.created/updated`、`interaction.registered/awaiting_input/answered/graded/abandoned`、`attempt.recorded`、`evidence.recorded`、`mastery.assessed/overridden/override_cleared`、`objective.deferred`、`assessment.voided/corrected` 等）。
- **通知面**：提交成功后 `publish_topic_signal`（`event_hub.py:124-131`）向订阅者发**唤醒提示**。`TopicSubscription` 队列 `maxsize=1`（`event_hub.py:40`），慢订阅者只保留最新信号（`_deliver_latest` `:112-118`）；发布是同步线程安全，让 `asyncio.to_thread` 里的学习事务能唤醒 uvicorn WS 循环（模块 docstring `event_hub.py:1-8`）。
- **消费端**：WS `/ws/mastery-paths`（`deeptutor/api/routers/mastery_path.py:788`）订阅 hub 后从 SQLite 回放事件尾（`:825-842`），revision 游标续传。hub 信号本身**不是数据**，客户端必须回放 SQLite。

## 4. 存储数据流（一个 SQLite，一个聚合，一条 CAS 规则）

- 库文件 `mastery.sqlite3`（`storage.py:351`），WAL 模式，默认路径 = `<workspace>/learning/mastery/`（`storage.py:360-361`，经 V2 迁移 `prepare_mastery_v2_root`）。
- 表结构（`storage.py:403-537`）：`mastery_paths`（state_json+revision，`:407`）、`mastery_path_sessions`（会话成员，`:419`）、`mastery_interactions`（题目生命周期，`:429`）、`mastery_events`、`mastery_learning_evidence`（查询投影表，`:460`）、`mastery_path_leases`（回合租约，`:482`）、`mastery_topic_meta`/`mastery_topic_sources`（`:489`/`:500`）、`reading_progress`/`reading_activities`（`:515`/`:526`）。
- **写路径全部是 `BEGIN IMMEDIATE` + revision CAS**：`save`（`storage.py:1002-1089`，冲突抛 `LearningConflictError` `:1036`）与 `transaction`（`:1091-1206`，谓词更新 `:1140-1162`）。事务提交后按序同步 evidence 投影（`_sync_evidence_projection` `:679-754`：普通追加只写新行，收缩只删尾）。
- **交互生命周期**受状态机约束（`_ALLOWED_INTERACTION_TRANSITIONS` `storage.py:58-77`）+ 部分唯一索引保证每 path 只有一个 active interaction（`:443-445`）；`progress.pending_question` 只是兼容镜像，durable 表是权威。
- **会话绑定**：`bind_session`（`storage.py:1652-1762`）成员互斥（一个会话同时在一条 path 上，唯一索引 `:645-650`），`owns_path` 记录创建者；`detach_session`（`:1810-1866`）删会话时连带删除"无课程的 scratch path"（判定 `_is_scratch_state` `:1789-1808`）。
- **回合租约**：`acquire_path_lease`（`storage.py:1889-1936`，冲突抛 `PathLeaseConflictError`）+ `release_leases_for_turn`（`:1938-1957`，按 turn_id 释放——turn 中途换 path 也不会泄锁）。
- **V1 兼容**：`<path-id>.json` 惰性导入（`import_legacy_json` `storage.py:803-905`，先到先得、损坏隔离 `archive/failed/`）；workspace 级 V1→V2 一次性迁移在 `migration.py`（先归档→复制→清理，`_process_lock` 跨进程串行 `:117`，WAL 先 checkpoint `:56-68`）。

## 5. 策略数据流（纯函数门）

- 双门制：MEMORY/PROCEDURE 走量化门（新近加权正确率 ≥0.9，`QUANTITATIVE_GATE` `policy.py:36-39`）；CONCEPT/DESIGN 走定性门（`mastery_assess` 记录的 boolean，`QUALITATIVE_TYPES` `:44-46`）。
- `is_mastered`（`policy.py:103-111`）= 评估达标 **或** 学习者显式 claim（`learner_mastery_overrides`）；`mastery_source`（`:93-100`）区分 `system/learner` 出身，公开报表必须暴露 provenance。
- `next_objective`（`policy.py:219-326`）优先级：①未答的 posed question（`answer_pending`）→ ②到期复习（跳过 deferred）→ ③第一个未过门目标（已过门即跳过——**门就是游标**，无 stage 计数器）：new 目标按学习者偏好给 `probe/teach`，定性给 `assess`，量化给 `practice` → ④全过门且无到期 = `complete`。
- `map_summary`（`policy.py:329-380`）供每回合 tutor 读取的薄快照；`objective_report`（`:429-495`）才是单目标完整证据链（attempts/explanation/review/errors）。
- 展示口径：`list_progress` 的 `avg_mastery_pct` 是平均分（`service.py:1894`），判断"学完没有"要用 gate 口径的 `list_path_overviews`（`service.py:1823-1862`）。

## 6. 与域外的衔接

- **API**：REST 挂载 `/api/mastery-paths`（`deeptutor/api/main.py:615-620`，router `deeptutor/api/routers/mastery_path.py:42`）+ WS（`:788`）；启动时跨面补账 `reconcile_linked_assessments`（`deeptutor/api/main.py:155-161` → `assessment.py:511`）。
- **能力层**：`deeptutor/capabilities/mastery/{capability,loop,pipeline,tools,choices,binding}.py` 是本域唯一的**写入口消费者**（tutoring 工具）；path id 解析走 `identity.resolve_mastery_path_binding`（capability.py 引用，`identity.py:42`）；`record_learner_profile` 由 `tools.py:1995` 调用。
- **chat 导航工具**：`deeptutor/tools/mastery_nav.py` 只读（无租约/无出题/无 mastery 变更，docstring `:1-20`），与 REST 共用 `navigation.py` 的图集遍历；挂载门 `learner_has_topics`（`navigation.py:41-55`）先探 `default_db_path` 避免给没用过的学习者建库（`storage.py:1622-1635`）。
- **跨面评测写回**：Book Focus-Check / Immersive Reading / 题库等经 `deeptutor/learning/assessment.record_assessment`（`assessment.py:425-508`）统一落 notebook 投影 + 不可变 attempt 日志（session store），带 `mastery_path_id+knowledge_point_id` 且 linkage 可信（`_is_trusted_linkage` `:280-291`）时，经 `_apply_linked_retention`（`:300-386`）把非 Mastery 证据应用到目标 retention（attempt_id 幂等；乱序旧事件按时间戳重放 `:352-362`）。
- **回合运行时**：租约释放挂在 turn 生命周期上（`deeptutor/services/session/turns/learning_adapter.py:22-28` `_release_superseded_lease`）。
- **主题创建链**：`topic_materials`（装载）→ `topic_generation`（生成，模块上限 `topic_generation.py:39-40`，覆盖报告 `:495`）→ `topic_naming`（命名，8s 超时不阻塞 `topic_naming.py:42`）→ `service.create_topic`（`service.py:1160-1204`，一个事务建 topic+sources+route）。

## 7. 已知坑

1. **expected_answer 只存服务侧**：`PendingQuestion` 含答案，对外一律走 `public_pending_question` 投影（`pending.py:245`）；新投影路径漏这层会泄漏答案。
2. **fail-closed 判分**：expected 为空 = 判错（`service.py:525`），不是跳过。
3. **两处重放顺序策略不同**：修复重放按 durable append 序（`service.py:1397-1402`），跨面补账重放按 `(timestamp, evidence_id)` 排序（`assessment.py:352-362`）——改 replay 语义时两处要一起想。
4. **同会话重复练习不增稳不推迟**（`scheduler.py:267-278`）：刷题刷不出复习豁免。
5. **`replace_modules` 清证据绑定**：模块集替换会删掉不属于新 KP 集的全部 mastery/错题/证据状态（`service.py:331-376`）；identity_mode（`semantic` 全量替换 / `explicit` 定向修订，`service.py:178-244`）选错会丢学习史。
6. **直接改 aggregate 不落库**：所有写必须经 `LearningStore.save/mutate/transaction`（CAS revision 谓词），绕过写入会在下次保存时冲突。
7. **hub 是唤醒不是数据**：丢信号不丢正确性（SQLite 回放兜底），但把 hub 信号当事件流用会丢事件。
8. **`book_id` 校验严格**：拒绝 `/ \ .. :`（`storage.py:384-388`）；外部输入一律先过 `identity.sanitize_mastery_path_id`（`identity.py:17-20`）。
9. **override 只推进路由不改证据**（`policy.py:103-111`）：报表必须带 `mastery_source`，否则 learner claim 会被误读为系统评估。
10. **scratch path 生命周期**：会话创建的无课程 path 会随会话删除（`storage.py:1810-1866`）；往里写课程（modules 带 KP）后才升级为持久课程。

## 8. 测试与覆盖空白

域内测试 `deeptutor/learning/tests/`（23 个文件）：storage 63、mastery_tools 70、api_endpoints 67、mastery_choices 39、scheduler 37、service_replace_merge 33、models 31、policy 26、grading 24、guided_mastery_updates 21、assessment 21、mastery_mode 20、mastery_navigation 19、topic_materials 15、topic_coverage 15、mastery_state_integrity 12、objective_relations 11、mastery_build_shapes 11、v2_migration 8、topic_naming 6、topic_generation 6、prompt_language_fallback 5、event_hub 4（按 test 数）。域外关联：`tests/capabilities/test_mastery_capability.py`、`tests/capabilities/test_mastery_choice_shuffle.py`、`tests/multi_user/test_learning_records_isolation.py`、`tests/services/workspace/test_learning_sources_review.py`、`tests/reading/`。

覆盖空白（可拆补测卡）：

- `identity.py` 整模块无直接测试（仅经 `deeptutor/capabilities/mastery/capability.py` 间接使用）。
- `migration.py` 324 行只有 8 个测试：`_process_lock` 抢锁失败、WAL checkpoint 失败、manifest 完整性路径无直接覆盖。
- `event_hub.py:99-110` 订阅者 loop 已关闭的 `RuntimeError→close` 分支无测试。
- `service.reset_path`（`:1307`）、`abandon_active_question`（`:1275`）、`record_learner_profile`（`:1226`）无域内直接测试（前两者仅 API 路由暴露 `mastery_path.py:1155/:1167`，后者仅能力工具调用 `tools.py:1995`）。
- `topic_generation.generate_topic_draft`（`:527`）LLM 主路径仅 6 个测试；KB inventory 失败回退（`:197`）、来源截断边界（`_MAX_SOURCES` `:40`）无直接覆盖。
- `mastery.compute_mastery` 无独立单测（置信上限 1 次 0.5 / 2 次 0.8 的边界仅被 `test_guided_mastery_updates` 间接触及）。
- `assessment.reconcile_linked_assessments` 的失败计数分支仅 1 个断言（`test_assessment.py:450`）。

## 验证

- `path:line` 均在基线 `f07029cfc` 核对；本文为导读，无行为变更。
- 域内回归：`deeptutor/learning/tests` 全绿（610 passed，命令 `.venv/bin/python -m pytest deeptutor/learning/tests -q -p no:cacheprovider`）。
