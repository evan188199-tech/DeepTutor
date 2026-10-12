# 端点 × 能力矩阵（learner 学习进度/记录面）

基线 `origin/main @ 6cf793bd8`。行格式：`METHOD path — path:line`（行号为路由装饰器所在行）。
账号隔离：以下路由均挂在 `dependencies=[require_learning_surface]` 栈下（`deeptutor/api/main.py:577-797`），存储路径经 `get_path_service()` 按当前账号 workspace 解析，即**文件级 per-account 隔离**。

## A. 阅读 Reading

| 端点 | 位置 | 能力 | 存储 |
|---|---|---|---|
| GET `/api/reading/materials/{id}/position` | deeptutor/api/routers/reading.py:1399 | 单材料上次视口（locator/percentage/anchor） | ReadingStore position 文件 |
| PUT `/api/reading/materials/{id}/position` | deeptutor/api/routers/reading.py:1410 | 保存视口并双写学习记录 `reading_progress`（locator+percentage+furthest） | mastery.sqlite3 `reading_progress`（deeptutor/learning/storage.py:515,1317-1350） |
| POST `/api/reading/materials/{id}/extensions/{ext}/actions/{action}` | deeptutor/api/routers/reading_extensions.py:195 | 阅读扩展行为 → 追加 `reading_activities` | mastery.sqlite3 `reading_activities`（storage.py:526,1370-1412） |
| POST `/api/reading/materials/{id}/extensions/quiz/answers` | deeptutor/api/routers/reading_extensions.py:363 | 阅读小测提交 + 星星奖励 upsert | session store quiz reward 表（reading_extensions.py:478-494） |
| GET `/api/reading/materials/{id}/quiz/rewards` | deeptutor/api/routers/reading_extensions.py:484 | 单材料奖励列表（无跨材料聚合） | 同上 |
| GET `/api/mastery-paths/reading/records` | deeptutor/api/routers/mastery_path.py:498 | **阅读进度+活动聚合**：全部 progress + 最近 200 条 activity（store 内 clamp 1..500，storage.py:1422）；无查询参数 | mastery.sqlite3 |

## B. 主题掌握 Mastery

| 端点 | 位置 | 能力 |
|---|---|---|
| GET `/api/mastery-paths/progress` | deeptutor/api/routers/mastery_path.py:906 | 全部路径进度列表 |
| GET `/api/mastery-paths/progress/{book_id}` | mastery_path.py:912 | 单路径聚合快照（含 pending_question 脱敏） |
| GET `/api/mastery-paths/progress/{book_id}/map` | mastery_path.py:927 | 仪表盘视图：gate 决定的下一步 + 全目标状态图（new/learning/mastered） |
| GET `/api/mastery-paths/progress/{book_id}/board` | mastery_path.py:946 | 学习看板：卡片 + next_review_at + 网格位置 |
| GET `/api/mastery-paths/progress/{book_id}/objectives/{kp_id}` | mastery_path.py:999 | 单目标证据报告：attempts/schedule/evidence（脱敏） |
| GET `/api/mastery-paths/progress/{book_id}/events` | mastery_path.py:1034 | 域事件增量拉取（after_revision），可做增量同步 |
| GET `/api/mastery-paths/progress/{book_id}/sessions` | mastery_path.py:1053 | 路径关联会话 |
| GET/PUT `/api/mastery-paths/topics/{path_id}/review-settings` | mastery_path.py:608 / 617 | 复习设置（desired_retention，SRS） |
| GET `/api/mastery-paths/topics` / `topics/index` | mastery_path.py:456 / 468 | 主题清单 / 轻量索引 |
| WS `/ws/mastery-paths/{path_id}` | mastery_path.py ws_router（main.py:634-638） | 事件实时推送（subscribed+forward） |

存储：`<workspace>/learning/mastery_v2/mastery.sqlite3`（deeptutor/learning/storage.py:351,360-370），11 张表（mastery_paths/events/interactions/learning_evidence/topic_meta/topic_sources/reading_progress/reading_activities 等，storage.py:407-526）；legacy 单 path JSON 懒迁移（storage.py:9）。

## C. 练习复习 Practice

| 端点 | 位置 | 能力 |
|---|---|---|
| GET `/api/question-notebook/practice/summary` | deeptutor/api/routers/practice.py:103 | total/mistakes/due/overdue/reviewed_today/next_due_at；`all_workspaces` 跨工作区聚合（practice.py:105-126） |
| GET `.../practice/queue` | practice.py:135 | 到期队列（limit≤100，course/category 过滤，all_workspaces） |
| GET `.../practice/analytics` | practice.py:184 | 按日+按来源统计，days 仅 {7,30,90}（practice.py:188-190） |
| GET `.../practice/questions/{entry_id}` / POST `check` / `review` | practice.py:229 / 236 / 243 | 单题状态、判答、SRS 复习（乐观锁 version + request_id 幂等） |
| GET `/api/question-notebook/stats` | deeptutor/api/routers/question_notebook.py:526 | 题库计数（course 范围） |

存储：session store sqlite 的 `practice_review_state`（含 per-question `streak` 字段）、`practice_review_events`、`practice_imports`（deeptutor/services/practice/storage.py:30-58）；capture 由 notebook_entries 触发器驱动（storage.py:59-88）。

## D. 书籍 Book

| 端点 | 位置 | 能力 |
|---|---|---|
| POST `/api/books/progress/visit` | deeptutor/api/routers/book.py:1250 | 记录页访问（续读位置） |
| POST `/api/books/progress/bookmark` | deeptutor/api/routers/book.py:1260 | 切换书签 |
| GET `/api/books`（列表，含 reading.percent） | book.py list_books（dashboard.py:88 引用） | 列表带阅读百分比，前端拼装进度 |

存储：`<book_root>/<book_id>/progress.json`（deeptutor/book/storage.py:235,298；deeptutor/services/path_service.py:424），per-book 单文件，无跨书聚合端点。
注意：`web/lib/book-progress.ts` 是书籍**生成管线**进度（ideation→…→compilation），与阅读进度无关。

## E. 观看 Video

| 端点 | 位置 | 能力 |
|---|---|---|
| GET `/api/video-learning/materials/{id}` | deeptutor/api/routers/video_learning.py:226 | 材料详情含 `learning.last_position` |
| PUT `/api/video-learning/materials/{id}/progress` | video_learning.py:242 | 仅存 last_position（clamp 到已知时长，video_learning.py:245-257） |
| GET `.../marks` / `marks/{mark_id}` / `notes` / `notes.md` | video_learning.py:318 / 327 / 260 / 268 | 标记与笔记 |

存储：`<workspace>` timed_media 特性目录下 per-material JSON（deeptutor/video_learning/service.py:307-322,641-645,680）。无观看历史聚合端点。

## F. 学习日志 Learning journal

| 端点 | 位置 | 能力 |
|---|---|---|
| GET `/api/learning-journal` | deeptutor/api/routers/learning_journal.py:10 | 只读全量快照：journal.to_dict() + 全部 records 倒序 + 注入切片（deeptutor/services/learning_journal/store.py:126-131）；无分页/过滤参数 |

存储：单文件 `journal.json`（store.py:64-65；path_service.py:306-307），原子写（store.py:300-321）。

## G. 聚合面 Aggregation

| 端点 | 位置 | 能力 |
|---|---|---|
| GET `/api/dashboard/recent` | deeptutor/api/routers/dashboard.py:20 | 最近会话动态（session store） |
| GET `/api/dashboard/learning-index` | dashboard.py:79 | **唯一跨面入口**：books/mastery/reading/watching 四类索引，跨工作区（read_workspace_indexes）；只返回条目清单，无进度数值聚合 |
| GET `/api/dashboard/learning-library/{kind}` | dashboard.py:160 | 账号级库发现（books/mastery/reading/materials/practice/watching） |
| GET `/api/dashboard/source-library/{kind}` | dashboard.py:120 | 源库（notebooks/chats/drafts/knowledge/books/practice） |
| GET `/api/courses/{course_id}/state` | deeptutor/api/routers/courses.py:189 | 课程范围聚合：sessions 计数+recent、题库 total/wrong/weak_categories（deeptutor/services/courses_state.py:272-313）、书页数、mastery 阶段（courses_state.py:88,115-135） |

## H. 记录写入（quiz/notebook）

| 端点 | 位置 | 能力 |
|---|---|---|
| POST `/api/sessions/{id}/quiz-results` | deeptutor/api/routers/sessions.py:696 | quiz 结果写为聊天消息文本 + notebook entries upsert（sessions.py:708-720），非结构化进度记录 |
| GET `/api/notebooks/statistics` | deeptutor/api/routers/notebook.py:209 | 笔记本统计 |
| notebook records CRUD | notebook.py:330-460 | 摘录记录管理 |

## 前端消费面（web/lib）

- `learning-records-api.ts:28` → GET `/api/mastery-paths/reading/records`
- `learning-dashboard.ts:30-46` → learning-index + 各列表端点拼进度数值
- `learning-journal-api.ts:13` → GET `/api/learning-journal`
- `practice-api.ts:63-64` → practice 路由（带 workspace scope）
- `mastery-*.ts` / `video-learning-api.ts` / `reading-workspace-api.ts` → 各自面
