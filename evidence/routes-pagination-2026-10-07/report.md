# 后端列表路由分页/限量一致性清点（AGEN-1127）

- 基线: HKUDS/DeepTutor `origin/main` @ `f07029cfc`（release v1.6.13），只读 worktree 静态清点
- 范围: `deeptutor/api/routers/` 全部 44 个路由文件；前端取用方式核对 `web/`
- 轴: 分页/限量（与 scan-route-contracts 契约漂移轴、scan-sql-query-plans 索引轴去重，不重叠）
- 矩阵: 见同目录 `matrix.csv`（157 行列表型路由，含 method/path/file:line/分页/限量/总量/前端取用/风险分级）

## 总量结论

| 指标 | 数值 |
|---|---|
| 列表型路由（返回数组负载，含 POST 检索） | 157 |
| 无界（unbounded：无分页参数、无服务端限量、无 total，随用户数据增长） | **80** |
| 其中高风险（大负载/全量聚合/前端 fetch-all） | 9 |
| 正确分页（limit-offset / cursor / page，含合理默认与上限） | 18 |
| 仅硬限量（服务端固定 cap） | 7 |
| 请求侧限量（输入列表 capped） | 5 |
| 配置/注册表类静态列表（天然有界） | 29 |
| 变更回显类列表（action-result） | 18 |

做得好的部分：`/api/sessions`、`/api/sessions/search`、`/api/question-notebook/entries`（limit-offset+total+le 上限）、`/api/space/mcp/catalog` 与 `/api/space/cli-apps/catalog`（cursor+total，前端 Load-more 闭环）、`/api/partners/{id}/history/page`（before-cursor+total）、`/api/knowledge-bases/list-ima`（cursor+MAX_PAGE_LIMIT）是全仓分页范本。

## 无界端点 Top 清单（高频/大负载优先）

1. `deeptutor/api/routers/knowledge.py:3058` — `GET /api/knowledge-bases/{kb}/files`：`sorted(raw_dir.rglob("*"))` 递归走整个知识库目录后全量返回；前端 fetch-all。
2. `deeptutor/api/routers/courses.py:189` — `GET /api/courses/{course_id}/state`：一次聚合 resources/sessions/question_bank/syllabus/mastery/reading 六类集合，全量返回。
3. `deeptutor/api/routers/sessions.py:293` — `GET /api/sessions/{session_id}`：整段会话全部 messages 单包返回，无窗口。
4. `deeptutor/api/routers/book.py:742` — `GET /api/books/{book_id}`：整本书 pages（含 blocks）全量返回。
5. `deeptutor/api/routers/mastery_path.py:456` — `GET /api/mastery-paths/topics`：每个 topic 连带完整 maps+reviews 快照。
6. `deeptutor/api/routers/mastery_path.py:1031` — `GET /api/mastery-paths/progress/{book_id}/events`：`after_revision` 游标无窗口/无 cap/无 has_more，首次同步返回全部事件历史。
7. `deeptutor/api/routers/reading.py:1389` — `GET /api/reading/materials/{id}/annotations`：随阅读行为持续增长的标注全量返回。
8. `deeptutor/api/routers/auth.py:1465` — `GET /api/auth/users`：管理端用户列表全量 fetch-all，无分页。
9. `deeptutor/api/routers/dashboard.py:160` — `GET /api/dashboard/learning-library/{kind}`：服务端内部循环 `list_notebook_entries(limit=200)` 翻页直到取完再整包返回——内部做了分页、对外却无界。

其余 71 条无界条目见 `matrix.csv`（risk_class=unbounded），多为中低增速集合（devices、tags、runs、catalogs 等）与前端未接线的包装端点（unused-frontend）。

## 前后端口径不一致条目

1. `/api/sessions`（sessions.py:118）：服务端默认 50/上限 200、无 total；前端 `session-api.ts:199,230` 以 pageSize=200 循环翻页，只能靠"短页"判断终止，无法显示进度。
2. `/api/mastery-paths/reading/records`（mastery_path.py:498）：activities 在服务层静默 clamp（默认 200、内部上限 500），参数不对外暴露；前端按 fetch-all 使用，>200 条即静默截断。
3. `/api/partners/{id}/history`（partners.py:1352）vs `/history/page`（partners.py:1375）：同一资源两套口径——旧 limit-offset（默认 100、无上限）已无前端调用方，实际使用 before-cursor 版本；旧端点成遗留双轨。
4. `/api/partner-groups/{id}/history|whiteboard|invocations`（partner_groups.py:129/163/19）：默认 200、上限 500、无 total；前端调用一律不传 limit，转录超 200 条即静默截断且无感知。
5. `/api/skills/hub/catalog`（skills.py:153）：`limit: int = 50` 无 ge/le 校验直接转发外部 hub；前端传 100——客户端可传任意大值。
6. `/api/dashboard/recent`（dashboard.py:20）：`limit: int = 50` 裸参数无 Query 校验，负值会产生负切片；当前仅生成契约引用（unused-frontend）。
7. `/files/library`（file_library.py:54）与 `/files/library/search`（file_library.py:85）：后端已提供 limit-offset 分页/检索，前端零调用——分页能力与前端脱节。
8. `GET /api/knowledge-bases`（knowledge.py:2776）与 `GET /api/knowledge-bases/list`（knowledge.py:2963）：同一列表双路由，均为 fetch-all。
9. `/api/multi-user/users`（multi_user.py:926）与 `/api/auth/users`（auth.py:1465）：两套用户列表，前者仅存在于生成契约，无调用方。
10. `/api/memory/trace/{surface}`（memory.py:680）：默认 200/上限 1000 但无 total/has_more；前端固定 limit=200，无法感知截断。
11. `/api/question-notebook/practice/queue`（practice.py:135）：服务端默认 20 窗口、上限 100、无 total；前端不传 limit，隐式拿到 20 条窗口。
12. `GET /api/partners/recent`（partners.py:664）：`limit: int = 3` 无校验；管理器侧 `activity[:limit]`，负值行为未定义（unused-frontend）。

## 方法与去重说明

- 判定口径：handler 返回数组（裸数组或包在响应键下）即"列表型"；POST 检索/导入类同样纳入。websocket 路由、单对象路由、纯变更路由不计入列表型。
- `risk_class` 语义：`paginated-ok`=有分页参数且默认值/上限合理；`capped`=无分页但服务端固定限量；`request-bounded`=输入列表封顶；`static`=配置/注册表枚举（天然有界）；`mutation-echo`=动作结果的回显列表；`unbounded`=无分页参数、无服务端限量、无 total 且随数据增长。
- 前端取用：对每条路由在 `web/` 检索调用点并归类（fetch-all / limit=N / paginated-loop / unused-frontend），取前 1-2 个调用点人工确认。
- 与既有卡去重：本卡只看分页/限量轴；响应契约字段漂移归 scan-route-contracts/scan-openapi-drift，SQL 执行计划与索引归 scan-sql-query-plans。
- 未发现上游与本卡同轴的开放 issue/PR（`gh search "pagination"` 空结果）。
- 本卡为纯静态清点：未改任何产品代码，未运行服务，无上游 PR。
