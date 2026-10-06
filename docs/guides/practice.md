# Practice 练习域导读（调度 / 导入 / 统计）

基线：origin/main `f07029cfc`（v1.6.13）。所有 `path:line` 均在该基线核对存在；本文不改产品代码。

## 0. 全景数据流（存储 → 服务 → 路由 → 前端）

- 存储：练习三张表建在用户 notebook 所在 SQLite——`practice_review_state` / `practice_review_events` / `practice_imports`，随 session 库迁移完成后初始化（`deeptutor/services/session/sqlite_store.py:516` → `deeptutor/services/practice/storage.py:25`）。
- 服务：`PracticeStore`（`deeptutor/services/practice/storage.py:100`）加三个纯模块——调度 `scheduler.schedule`（`deeptutor/services/practice/scheduler.py:30`）、导入解析 `importing.preview`（`deeptutor/services/practice/importing.py:203`）、统计 `analytics.analytics`（`deeptutor/services/practice/analytics.py:10`）；判分 `answers.check_answer`（`deeptutor/services/practice/answers.py:9`）。
- 路由：`deeptutor/api/routers/practice.py`，挂载于 `/api/question-notebook/practice`（`deeptutor/api/main.py:673`）。
- 前端：API 封装 ROOT=`/api/question-notebook/practice`（`web/lib/practice-api.ts:5`）；页面 `web/app/(workspace)/learning/practice/page.tsx:2` 渲染 `PracticePage`（`web/components/learning/practice/PracticePage.tsx`），下辖 ReviewHome / PracticeSession / PracticeImport / PracticeInsights。

答题小流程：`PracticeSession.rate`（`web/components/learning/practice/PracticeSession.tsx:191`）→ POST `/questions/{id}/review`（`deeptutor/api/routers/practice.py:243`）→ `PracticeStore.review`（`deeptutor/services/practice/storage.py:226`）→ `schedule` 算新 due_at → 写 state + events。

## 1. 练习调度（间隔 / 到期）

要点：

- SM-2 风格冷启动策略、非 FSRS 拟合；review 事件全量留痕便于未来回放（`deeptutor/services/practice/scheduler.py:1`）。
- 四档评级调整 interval/ease（`deeptutor/services/practice/scheduler.py:35`–47）：again 记 10 分钟（10/1440 天，`:36`）并记 lapse；good 首次跳 3 天、之后乘 ease；easy 再乘 1.3（`:43`–46）。间隔上限 365 天（`:50`），`due_at = now + interval*86400`（`:56`）。
- “今天”按学习者时区取日界，DST 安全（`day_bounds`，`deeptutor/services/practice/scheduler.py:17`）；时区非法在路由层转 422（`deeptutor/api/routers/practice.py:86`）。
- 到期判定不只看 `r.due_at`：`_DUE_AT_SQL` 对“已解决/答对且从未复习”的条目取 `updated_at+3 天`，否则回退 `due_at`/`created_at`（`deeptutor/services/practice/storage.py:16`–18）。
- 队列按到期升序、默认 20 条（`deeptutor/services/practice/storage.py:171`；路由 `deeptutor/api/routers/practice.py:135`）。
- 并发与一致性：review 用 `BEGIN IMMEDIATE` + request_id 幂等（重复请求回放原 outcome，payload 不一致报冲突，`deeptutor/services/practice/storage.py:238`–253）+ version 乐观锁（`:264`–268）；客观题在事务内重判，答错却评 good/easy 直接 422（`:269`–274）。
- 触发器维护：题干/选项/答案被编辑时 version+1 使旧会话失效（`deeptutor/services/practice/storage.py:69`）；答错自动入队与重置由 `practice_capture_insert`/`practice_capture_update` 完成（`:61`、`:76`）；again 评级把 resolved 置 0（`:308`）。

到期循环：答错（notebook `is_correct=0`）→ 触发器入队 due=+1 天 → summary/queue 捞到期题 → check 判分（`deeptutor/api/routers/practice.py:237`）→ review 评级 → schedule 产出新间隔 → events 留痕。

## 2. 题目导入来源

三条来源：① 学习者上传文件（CSV/TSV/XLSX/JSON）；② 会话/深问产生的错题，`notebook_entries.is_correct=0` 被触发器自动捕获（见 §1）；③ 建库时历史错题一次性回填迁移（`deeptutor/services/practice/storage.py:91`）。

文件导入要点：

- 限额：≤5MB、≤500 题、单格 ≤2 万字符、≤64 列（`deeptutor/services/practice/importing.py:13`–16）；xlsx 另限解压 30MB、部件 ≤2000、禁止公式（`:87`–108）。
- 解析：JSON 须为对象数组（`:61`）；CSV/TSV 嗅探分隔符、编码 UTF-8 失败回退 GB18030（`:68`–76）；表头非空且唯一（`:117`–120）。
- 中英文字段别名（`:17`–26）与题型归一到 single_choice/multi_choice/true_false/fill_blank/short_answer（`:27`–47、`:150`–153）。
- 规范化：判断题答案收敛 T/F（`:154`）；选择题答案键校验、排序去重（`:161`–175）；tags ≤20 条、每条 ≤100 字符（`:176`–180）。
- `question_id` 为内容哈希 `import:<sha256>`，重复导入幂等（`:191`–199）。

三段式流程：preview 逐行收集行级错误（`deeptutor/api/routers/practice.py:327`）→ 无错误才 stage_import 落 `practice_imports` 发 token，超 1 天未提交作废（`deeptutor/services/practice/storage.py:325`、`:359`）→ commit_import 单事务 `INSERT OR IGNORE` 写入 notebook_entries（origin_type=`external_import`，`:348`–396）；target=mistakes 时同步初始化复习状态（`:403`–413），tags 落 notebook_categories（`:414`）。

前端：`web/components/learning/practice/PracticeImport.tsx:39` 预览 → `:53` 提交 → `:109` 模板下载（模板生成在 `deeptutor/api/routers/practice.py:263`）。

关联储备卡落点：test-practice-scheduler 对准 §1（scheduler.py / storage.py.review）；fix-practice-import-errors 对准 §2 的解析报错与路由 422 映射（`deeptutor/api/routers/practice.py:334`–338）。

## 3. 统计口径

- 总览 summary：total/mistakes/due/overdue/next_due_at 一条 SQL 汇总（`deeptutor/services/practice/storage.py:127`）；`reviewed_today` 按 day_bounds 统计当天 events 去重条目数（`:146`–153）。
- 趋势 analytics：窗口仅 7/30/90 天（`deeptutor/services/practice/analytics.py:13`）；按学习者时区逐日分桶（自定义 SQLite 函数 practice_day，`:25`–27）。三个口径独立统计（`:29`–41）：questions 按 `n.created_at`；mistakes 按 `r.first_wrong_at` 且“成员关系是历史性的”——解决错题不抹掉首次做错日期（`:28`）；reviews 按 `e.reviewed_at`。
- 来源归因按 `n.source`，空值记为 deep_question（`:44`–47）；输出 daily/sources/totals（`:58`–66）。
- 跨工作区：`all_workspaces` 时路由对每个工作区各查一遍再求和、next_due_at 取 min（`deeptutor/api/routers/practice.py:103`–125）；趋势合并 daily/sources/totals（`:191`–216）；队列合并后按 due 排序截断（`:143`–159）。
- 前端消费：PracticePage 拉 summary/queue（`web/components/learning/practice/PracticePage.tsx:49`、`:85`），PracticeInsights 拉 analytics（`web/components/learning/practice/PracticeInsights.tsx:59`）；无 course/question 参数时进入 ReviewHome 全局回顾（`PracticePage.tsx:22`；`web/components/learning/practice/ReviewHome.tsx:37`、`:65`）。

## 验证与关联

- 行号均在基线 `f07029cfc` 逐一核对；本文为导读，不含行为变更。
- 回归参考：`tests/api/test_practice.py`（路由契约与导入边界）。
