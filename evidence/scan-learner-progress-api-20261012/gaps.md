# 缺口清单（对照"个人学习进度视图"聚合需求，上游 #1130）

每条附 `path:line`。严重度：高=视图直接缺数据源；中=有数据但需新聚合；低=体验/一致性。

## 高

1. **无跨面统一进度聚合端点（含数值）**
   `GET /api/dashboard/learning-index` 只返回四类条目清单，无进度百分比/计数/最近活跃字段（deeptutor/api/routers/dashboard.py:79-117）。前端进度数值由 4 个不同端点拼装：book `reading.percent`、mastery `map.counts.mastered/total`、reading 靠 workspace 列表、watching 靠会话过滤（web/lib/learning-dashboard.ts:30-46）。要做"个人进度视图"，需要一个新的后端聚合端点返回 per-surface 进度指标，否则继续前端拼装。

2. **无学习时长记录**
   全仓无 time_spent / study_time / duration 累计字段（rg `streak|xp|badge|study_time|time_spent|learning_time` 于 deeptutor/ 与 web/lib/ 仅命中无关项）。阅读只存 locator/percentage（deeptutor/api/routers/reading.py:1410-1445），视频只存 last_position（deeptutor/api/routers/video_learning.py:242-257），mastery 事件只有时间戳（deeptutor/learning/storage.py:447）。进度视图无法呈现"今天学了多久"。

3. **无每日 streak / XP / 徽章体系**
   `practice_review_state.streak` 是单题 SRS 连续答对计数，非每日学习 streak（deeptutor/services/practice/storage.py:30-42）；无任何每日活跃/积分/徽章表或端点。星星奖励仅存在于阅读小测单材料维度（deeptutor/api/routers/reading_extensions.py:478-494），无跨材料合计端点。

## 中

4. **`/reading/records` 聚合端点无查询参数**
   handler 无任何参数（deeptutor/api/routers/mastery_path.py:497-503），activity 条数在 store 内固定 clamp 1..500、默认 200（deeptutor/learning/storage.py:1419,1422）。不可分页、不可按 material/时间/类型过滤；进度页数据量增长后无法增量拉取。

5. **观看面无历史聚合**
   视频进度是 per-material JSON 的 `learning.last_position`（deeptutor/video_learning/service.py:641-645,680；store root service.py:307-322）。dashboard 的 watching 分类用会话快照按 capability 过滤，不反映观看进度（deeptutor/api/routers/dashboard.py:103-117）。无法回答"看过哪些视频、各自看到哪"。

6. **书籍进度 per-book 文件，无聚合读**
   `load_progress(book_id)` 只能单取（deeptutor/book/storage.py:298-300）；跨书进度只能靠 `list_books` 内嵌的 reading 字段间接获得，无 `GET /books/progress` 列表端点（deeptutor/api/routers/book.py:1250,1260 仅 POST 写入）。

7. **学习日志单文件全量返回**
   `journal.json` 单文件（deeptutor/services/learning_journal/store.py:64-65）；`overview()` 返回全部 records + 注入切片，无分页/日期过滤（store.py:126-131）；router 仅一个 GET（deeptutor/api/routers/learning_journal.py:10-18）。日志变长后响应体无界。

8. **quiz 结果非结构化**
   POST `/api/sessions/{id}/quiz-results` 把答案格式化为聊天消息文本写入，仅顺带 upsert notebook entries（deeptutor/api/routers/sessions.py:696-721，格式化 `sessions.py:_format_quiz_results_message`）。无 quiz 得分/正确率表；题库 stats（deeptutor/api/routers/question_notebook.py:526-533）只能部分替代，且不带 quiz 维度。

9. **阅读位置双写非原子，失败静默**
   PUT position 先写 ReadingStore，再 `asyncio.to_thread` 写 LearningStore.reading_progress，失败仅 `logger.exception` 继续 200（deeptutor/api/routers/reading.py:1428-1445）。两表面（reading position 与 learning records）可静默漂移，无对账/修复端点。

10. **跨工作区聚合覆盖不均**
    practice 三端点有 `all_workspaces`（deeptutor/api/routers/practice.py:103-126,135-182,184-241）；dashboard 用 read_workspace_indexes（deeptutor/api/routers/dashboard.py:96-116）；而 `GET /api/mastery-paths/reading/records` 与 mastery progress 家族均无跨工作区参数（deeptutor/api/routers/mastery_path.py:497,905-906），只反映当前 workspace。

## 低

11. **practice analytics 时间粒度受限**
    days 仅接受 {7,30,90} 否则 422（deeptutor/api/routers/practice.py:188-190），粒度固定按日（deeptutor/services/practice/storage.py analytics 查询）。无周/月/小时视图，无自定义区间。

12. **进度无导出端点**
    仅练习模板导入与笔记本导出（deeptutor/api/routers/practice.py:327 import/preview；deeptutor/api/routers/notebook.py:460 notebooks export）。学习进度/记录本身无 CSV/JSON 全量导出。

## 可直接支撑进度视图的现成能力（选型依据）

- mastery `/progress/{book_id}/map` 与 `/board`：已是"单主题进度"完整投影（状态+下次复习+网格），可直接复用其 `learning_policy.map_summary`（deeptutor/api/routers/mastery_path.py:927-997）。
- practice `/summary` + `/analytics`：已是标准计数聚合，含时区处理与跨工作区模式，可作为新聚合端点的形状参照（deeptutor/api/routers/practice.py:103-241）。
- mastery `/progress/{book_id}/events`（after_revision 增量，deeptutor/api/routers/mastery_path.py:1034-1051）+ `/ws` 推送：若进度视图要实时刷新，增量协议已存在。
- `read_workspace_indexes`（deeptutor/services/workspace/navigation.py）：跨工作区读的既有工具，dashboard 已验证可用。
