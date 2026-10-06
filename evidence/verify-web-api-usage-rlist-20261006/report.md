# verify: web-api-usage-20261006 复核清单人工过目（AGEN-900）

- 复核对象：`myfork/scan/web-api-usage-20261006`（commit `a07b2c9f`）报告的 R1–R4 全部 31 条 + R5/R6 抽样
- 基线：`origin/main` @ `f07029cfcf2c8dfccdb671cdfc343db8334f5741`（与扫描基线一致，v1.6.13）
- 对照物：`web/contracts/schema/openapi.json`（531 paths）、后端 `deeptutor/api/routers/*`、前端调用点源码
- 结论口径：**合法取值**（运行期取值/路由在契约与后端均成立）、**真漂移**（调用与契约/后端实质不符）、**误报**（扫描器分类错误）
- 只读复核：未改任何产品代码

## 总结

| 类别 | 条数 | 合法取值 | 真漂移 | 误报 |
|---|---|---|---|---|
| R1 param-shadow | 6 | 6 | 0 | 0 |
| R2 dynamic-final-segment | 4 | 4 | 0 | 0 |
| R3 suffix-stripped | 9 | 9 | 0 | 0 |
| R4 backend-indeterminate | 12 | 12 | 0 | 0 |
| **R1–R4 小计** | **31** | **31** | **0** | **0** |
| R5 动态 URL（抽样 14） | 51 中抽 14 | 12 | 0 | 1（注释误报）+1 组（tests 非生产） |
| R6 WS/SSE（全查 8/8） | 8 | 8 | 0 | 0 |

**真漂移清单：无新增。** 已确认漂移仍为原报告 F1（`rag-pipelines/${provider}/config` 参数化 vs 字面路由，2 点）与 F2（`resource_library=true` 死参数，2 点），二者不在 R1–R4 清单内，本卡不重复展开，修复方向见文末。

## R1 param-shadow（6/6 合法取值）

| # | 位置 | 结论 | 依据 |
|---|---|---|---|
| 1 | `web/features/knowledge/api/client.ts:293`（分支1 `?resource_library=true`） | 合法取值 | 后端有字面路由 `GET /knowledge-bases/list`（`deeptutor/api/routers/knowledge.py:2963-2970`，`include_in_schema=False`，docstring 说明为代理安全别名）。契约侧匹配到 `{kb_name}` 是扫描器参数宽容匹配副产品，非真 shadow。附带：`resource_library=true` 为死参数（后端不读、契约 0 查询参数声明）＝原报告 F2，路径本身合法 |
| 2 | `web/features/knowledge/api/client.ts:293`（分支2 无参） | 合法取值 | 同上，同一后端字面路由 |
| 3 | `web/components/memory/MemorySection.tsx:721` | 合法取值 | 后端 `GET /trace/{surface}`（`memory.py:680`）`surface: str` 接受 `"kb"`；契约 `GET /api/memory/trace/{surface}` 声明 `limit`/`offset` 查询参数，传 `limit=200` 合法 |
| 4 | `web/lib/memory-graph.ts:254` | 合法取值 | 后端 `_validate_layer` 仅接受 `{"L2","L3"}`（`memory.py:69-72`），字面段 `L2` 是 `{layer}` 的合法枚举值；key 段为运行期 surface 变量，与 `{key}` 参数位吻合 |
| 5 | `web/lib/memory-graph.ts:265` | 合法取值 | 同上，`L3` 合法 |
| 6 | `web/lib/partners-api.ts:204` | 合法取值 | 路径段为动态插值（`encodeURIComponent(partnerId)`）非字面 shadow；契约 `GET /api/partners/{partner_id}` 声明 `include_secrets` 查询参数，后端 `partners.py:954` `include_secrets: bool = Query(...)` 存在且受 `manageable` 门控 |

## R2 dynamic-final-segment（4/4 合法取值）

| # | 位置 | 结论 | 依据 |
|---|---|---|---|
| 1 | `web/lib/notebook-api.ts:166` | 合法取值 | `mode` 为 TS 字面量联合 `"move"\|"copy"`；契约 `/api/notebooks/{notebook_id}/records/{record_id}/actions/copy` 与 `/actions/move` 均 POST 声明，两分支全覆盖 |
| 2 | `web/lib/partners-api.ts:603` | 合法取值 | 代码类型为 `"archive"\|"resume"\|"delete"`（报告写 4 值偏宽，`branch` 不在前端联合里；契约 archive/branch/delete/resume 4 条均 POST，无论取哪个值都命中）。方法 POST 吻合 |
| 3 | `web/lib/video-learning-api.ts:426` | 合法取值 | `action ∈ status\|authorize\|disconnect`，方法三元 `status→GET`、其余 `POST`；契约 status=GET、authorize=POST、disconnect=POST，逐值方法吻合 |
| 4 | `web/lib/visualizers-api.ts:55` | 合法取值 | `enabled ? "enable" : "disable"` POST；契约 `/api/visualizers/{visualizer_id}/enable`、`/disable` 均 POST |

## R3 suffix-stripped（9/9 合法取值；条件查询参数逐一对照契约声明）

| # | 位置 | 结论 | 依据 |
|---|---|---|---|
| 1 | `web/features/knowledge/api/client.ts:1457` | 合法取值 | `embedding_model` 在契约 `GET /api/knowledge-bases/{kb_name}/reindex-config` 查询参数声明内 |
| 2 | `web/lib/cli-apps-api.ts:231` | 合法取值 | `q`/`category`/`installable_only`/`cursor`/`limit` 全部在契约 `GET /api/space/cli-apps/catalog` 声明内 |
| 3 | `web/lib/notebook-api.ts:372` | 合法取值 | 代码可设 19 个参数（mistakes_only/category_id/uncategorized/bookmarked/is_correct/source/material_id/section_id/assessment_type/result/mastery_path_id/knowledge_point_id/resolved/score_trend/search/sort/limit/offset/course_id）与契约 `GET /api/question-notebook/entries` 声明的 19 个查询参数一一同名 |
| 4 | `web/lib/notebook-api.ts:591` | 合法取值 | `course_id` 在契约 `GET /api/question-notebook/stats` 声明内 |
| 5 | `web/lib/notebook-api.ts:602` | 合法取值 | `course_id` 在契约 `GET /api/question-notebook/materials` 声明内 |
| 6 | `web/lib/notebook-api.ts:628` | 合法取值 | `course_id` 在契约 `GET /api/question-notebook/categories` 声明内 |
| 7 | `web/lib/partners-api.ts:535` | 合法取值 | `session_key`/`session_id`/`limit` 全部在契约 `GET /api/partners/{partner_id}/history` 声明内 |
| 8 | `web/lib/reading-api.ts:254` | 合法取值 | POST 分支 `?reuse=false`；契约 `POST /api/reading/materials` 声明 `reuse` 查询参数（GET 无参，方法区分正确） |
| 9 | `web/lib/skills-api.ts:206` | 合法取值 | `hub`/`q`/`limit` 全部在契约 `GET /api/skills/hub/catalog` 声明内 |

## R4 backend-indeterminate（12/12 合法取值）

### mcp-api.ts 9 点：基址运行期可解析，两族路由分派不交叉

`basePath` 只有两个取值，均为模块常量（`web/lib/mcp-api.ts:107,110`）：`MCP_ADMIN_BASE_PATH=/api/settings/mcp`、`MCP_SPACE_BASE_PATH=/api/space/mcp`。调用方 `web/components/mcp/surface.ts` 仅两个 surface：`ADMIN_MCP_SURFACE`（`writes:"registry"`）与 `SPACE_MCP_SURFACE`（`writes:"per-server"`），所有 9 个调用点经 surface 分派：

| 调用点 | URL | admin 族（mcp_settings.py，契约在） | space 族（space_mcp.py，契约在） |
|---|---|---|---|
| mcp-api.ts:506 `POST {basePath}/test` | testMcpServer | `POST /api/settings/mcp/test` ✓（admin 实际走到） | space 族无（space 走 `testSpaceMcpServer`，不到此函数） |
| mcp-api.ts:526 `GET {basePath}/servers` | getSpaceMcpState | admin 族无 | `GET /api/space/mcp/servers` ✓（仅 per-server 分支调用，surface.ts:94） |
| mcp-api.ts:546 `PUT {basePath}/servers/{name}` | putSpaceMcpServer | admin 族有 `PUT /servers/{name}` | `PUT /api/space/mcp/servers/{name}` ✓（仅 per-server 分支，surface.ts:121） |
| mcp-api.ts:561 `DELETE {basePath}/servers/{name}` | deleteSpaceMcpServer | 两族均有 ✓ | ✓（仅 per-server 分支，surface.ts:125） |
| mcp-api.ts:578 `POST {basePath}/servers/{name}/authorize` | authorizeSpaceMcpServer | admin 族无 | `POST /api/space/mcp/servers/{name}/authorize` ✓（`mcp.authorize` 仅 McpStoreSection（space）接线） |
| mcp-api.ts:592 `POST {basePath}/servers/{name}/test` | testSpaceMcpServer | admin 族无 | ✓（仅 per-server 分支，surface.ts:148 / McpCatalogBrowser.tsx:476） |
| mcp-api.ts:716 `GET {basePath}/catalog` | getMcpCatalog | admin 族无 | `GET /api/space/mcp/catalog` ✓（McpCatalogBrowser 仅被 McpStoreSection 使用，传 `SPACE_MCP_SURFACE`） |
| mcp-api.ts:743 `POST {basePath}/catalog/{id}/install` | installMcpCatalogEntry | admin 族无 | ✓ 同上 |
| （附）getMcpSettings/updateMcpSettings（:479/:493，属 R4 语境） | GET/PUT base | `GET/PUT /api/settings/mcp` ✓（registry 分支） | space 族无（space 不走 base 读写） |

结论：**合法取值**。后端 `mcp_settings.py`（5 条路由）与 `space_mcp.py`（9 条路由）与契约两族一致；每条调用在运行期绑定唯一基址，且接线只在自己 surface 的路由族内。注意：两族路由不对称（admin 无 servers 列表/authorize/catalog，space 无 base GET/PUT 与 /test），当前无活漂移，但若未来调换 surface 的 `writes` 模式或给 admin 接 catalog 组件会踩空——建议给 `McpSurface.basePath` 加字面量联合类型约束（原报告可拆卡建议 4 的延伸）。

### 其余 4 点

| # | 位置 | 结论 | 依据 |
|---|---|---|---|
| 10 | `web/lib/book-api.ts:60` | 合法取值 | `BASE="/api"`（book-api.ts:22）；全部 15 个调用方字面 path 在契约且方法吻合：`/books` GET（list 无 init→默认 GET）、`/books/confirm-spine|insert-block|update-block|progress/visit|progress/bookmark|delete-block|move-block|deep-dive|quiz-attempt|supplement|page-chat-session|resume|pause|rebuild` 均 POST ✓ |
| 11 | `web/lib/codebuddy-auth.ts:17` | 合法取值 | `BASE="/api/settings/providers/codebuddy/auth"`（:16）；`/status` GET、`/start`/`/cancel`/`/logout` POST，4 条均契约声明 |
| 12 | `web/features/settings/sections/DataMigrationSettingsSection.tsx:59` | 合法取值 | `endpoint="/api/settings/workspace/data"`（:36）；调用方 `/operations` GET、`/discover` GET（`source_workspace_id` 契约声明）、`/preview`/`/migrate`/`/export` POST（action 联合 `'preview'\|'migrate'\|'export'`）、`/operations/{id}/recover` POST，全部在契约 |
| 13 | `web/lib/reading-workspace-api.ts:126` | 合法取值 | `BASE="/api/reading"`（:5）；调用方字面 path 全在契约：`/library/materials` GET、`/library/duplicate-check` POST、`/materials/{id}` DELETE、`/materials/{id}/retry` POST、`/workspaces` GET+POST、`/workspaces/{id}` GET/DELETE、`/workspaces/index` GET、`/workspaces/{id}/materials` POST、`/materials/{mid}/active` PUT、`/{mid}` DELETE、`/sessions` GET+POST、`/sessions/{sid}/links` POST、`/links/{tsid}` DELETE、`/ask-hint` GET（`session_id`/`locator`/`selection` 契约声明）、`/notes/organize` POST、`/workspaces/{id}/notebook` POST；另 :476 直拼 `/api/mastery-paths/progress/{book}/generate-from-reading` POST ✓（部分经 `scopedUrl` 包裹＝F3 `dt_workspace` 注入，口径外） |

## R5 动态 URL（51 条中抽样 14 条）

| # | 位置 | 结论 | 依据 |
|---|---|---|---|
| 1 | `components/chat/preview/FilePreviewDrawer.tsx:176-177` | 合法（口径外） | `previewUrl` 为 `data:`/`blob:` 内联或附件资产流，非契约 REST 路径断言对象 |
| 2 | `components/knowledge/KbDocumentList.tsx:32` | **误报** | 该行是接口 doc 注释（"…forces a re-fetch…"）；全文件无 `fetch(` 调用，扫描器正则把注释词当调用点 |
| 3 | `components/reading/EpubDocumentView.tsx:418` | 合法取值 | `renderMaterialUrl` = `/api/reading/materials/{id}/render`（reading-api.ts:504-506），契约 `GET …/render` ✓ |
| 4 | `features/knowledge/api/client.ts:382` | 合法取值 | `PAGEINDEX_CONFIG_PATH = "/api/knowledge-bases/rag-pipelines/pageindex/config"`（:373-374），契约字面路由 GET/PUT ✓（即 F1 建议的字面量方案现成样例） |
| 5 | `features/settings/sections/AttachmentsSettingsSection.tsx:64`（及 :117 PUT） | 合法取值 | `EXTENSION_ENDPOINTS["chat-attachments"]="/api/settings/chat-attachments"`（settings-extensions.ts:29），契约 GET/PUT ✓ |
| 6 | `features/settings/sections/CapabilitiesSettingsSection.tsx:101`（及 :155 PUT） | 合法取值 | `EXTENSION_ENDPOINTS.capabilities="/api/capabilities/settings"`，契约 GET/PUT ✓ |
| 7 | `features/settings/sections/MemorySettingsSection.tsx:48`（及 :86 PUT） | 合法取值 | `EXTENSION_ENDPOINTS.memory="/api/memory/settings"`，契约 GET/PUT ✓ |
| 8 | `lib/guardian-api.ts:56` | 合法取值 | 调用方字面 path：`/api/multi-user/me/guardianships` GET、`/api/multi-user/guardians` GET+POST、`/api/multi-user/learners/{id}/guardian-report` GET、`…/materials` GET、`…/restrictions` PUT——契约全部存在（learner 参数名为 `{learner_user_id}`） |
| 9 | `lib/task-board-api.ts:22` | 合法取值 | `endpoint="/api/task-board"`（:19）；`GET /api/task-board`、`POST /cards`、`PATCH /cards/{card_id}`（updateTaskCard 用 PATCH，契约有 PATCH）全 ✓ |
| 10 | `lib/practice-api.ts:63` | 合法取值 | `ROOT="/api/question-notebook/practice"`（:5）；调用方 `/summary`、`/queue`、`/questions/{id}` GET、`/questions/{id}/check` POST、`/questions/{id}/review` POST、`/import/preview`、`/import/commit` POST、`/analytics` GET 全在契约 ✓ |
| 11 | `lib/learning-api.ts:580` | 合法取值 | `masteryJson` 调用方：`/api/mastery-paths/topics` GET、`/topics/index` GET、`/topics/{id}/ask-hint` GET、`/topics/{id}/sessions` GET，契约全 ✓ |
| 12 | `lib/workspaces-api.ts:49` | 合法取值 | `endpoint="/api/settings/workspace/registrations"`（:45），契约 GET/POST ✓ |
| 13 | `lib/settings-extensions.ts`（EXTENSION_ENDPOINTS 表，覆盖 Attachments/Capabilities/Memory/Starters 等 8 个 R5 点） | 合法取值 | 14 个常量端点逐一对照契约全部存在且方法匹配（`update-checks`、`chat-timeout` 仅 PUT，与前端只用 PUT 一致；其余 GET+PUT）；guardian 分支正则产物 `/api/multi-user/learners/{id}/(materials\|restrictions)` 亦在契约 |
| 14 | `tests/*.spec.tsx` 7 点（image-description-model/kb-embedding-binding/model-settings-store/model-settings-workflow/provider-registry-workflow/settings-unified-draft/voice-settings） | 非生产调用 | 测试 mock/本地端口 fetch，不属漂移口径（原报告白名单口径一致） |

抽样覆盖率：51 条中抽 14 条（≥8 达标），其中 1 条误报（#2）、1 组非生产（#14）、12 条合法取值。

## R6 WS/SSE（8/8 全查，非抽样）

| # | 位置 | 结论 | 依据 |
|---|---|---|---|
| 1 | `features/chat/transport/socket.ts:21` | 口径外（WS） | 通用 `browserSocketFactory(url)`，url 由 chat transport 传入；OpenAPI 不含 WS 路由 |
| 2 | `lib/quiz-judge.ts:40` | 口径外（WS） | `/ws/questions/judge`；后端 `main.py:630` 挂载 `question.ws_router prefix="/ws/questions"` ✓ |
| 3 | `hooks/useKnowledgeProgress.ts:173` | 口径外（WS） | `/ws/knowledge-bases/{name}/progress`；`main.py:631` `knowledge.ws_router prefix="/ws"` ✓ |
| 4 | `hooks/useKnowledgeProgress.ts:296` | 口径外（SSE，且契约内可判） | EventSource → `GET /api/knowledge-bases/tasks/{task_id}/stream`；**契约已声明该 GET 路径**（比报告口径更进一步：此点非"不可判"，实为契约内合法） |
| 5 | `features/settings/store/SettingsStore.tsx:1994` | 口径外（SSE，且契约内可判） | EventSource → `GET /api/settings/tests/{service}/{run_id}/events`；**契约已声明** ✓ |
| 6 | `lib/book-api.ts:42` | 口径外（WS） | `BOOK_WS_PATH="/ws/books"`（:23）；`main.py:643` `book.ws_router prefix="/ws"` ✓ |
| 7 | `lib/use-book-stream.ts:49` | 口径外（WS） | 同 `BOOK_WS_PATH="/ws/books"`（:8）✓ |
| 8 | `lib/reconnecting-websocket.ts:70` | 口径外（WS） | 通用重连封装，url 入参 |

结论：8/8 非漂移。其中 2 个 SSE 点（#4/#5）虽然走 EventSource，但 URL 是 `/api/` 路径且契约已声明——后续扫描可把它们从"WS/SSE 口径外"挪回契约比对口径。

## 对原报告的两处口径修正

1. R2 第 2 条 `partners-api.ts:603`：报告写枚举为 `archive|branch|delete|resume` 四值，实际 TS 联合只有 `archive|resume|delete` 三值（`branch` 路由存在但前端未用）；不影响结论。
2. R6 第 4/5 条：两个 EventSource 点的 URL 是契约内已声明的 `/api/` GET 路径，并非完全"静态不可判"。

## 真漂移与修复方向（不实施）

本轮未发现新增真漂移。原报告已确认项的修复方向（供拆卡参考）：

- **F1** `rag-pipelines/${provider}/config`（client.ts:505/524，2 点）：后端补参数化路由 `/rag-pipelines/{provider}/config`（或前端改用按 provider 的字面量常量联合，样例即 client.ts:373 的 `PAGEINDEX_CONFIG_PATH`），二选一后重新生成契约。
- **F2** `resource_library=true` 死参数（KnowledgePage.tsx:189、client.ts:293，2 点）：删除两处死参数；若原意是资源库视图过滤，先在后端补参数并重生成契约。
- **F3** `dt_workspace` 契约不可见：横向项，属 scan-openapi-drift（契约↔后端）交叉轴，本卡仅维持原记录。

## 复核方法与可复现性

- 逐条打开 `origin/main @ f07029cfc` 工作树中的调用点源码，对照 `web/contracts/schema/openapi.json`（同一 commit）的路径/方法/查询参数声明，并抽查后端 router 源码（knowledge.py、memory.py、partners.py、mcp_settings.py、space_mcp.py、main.py）。
- 扫描器机器结果取自 `myfork/scan/web-api-usage-20261006` 的 `usage.json`（backend_call_sites / backend_indeterminate_sites / dynamic_url_sites / websocket_sites 四个数组）。
- 本复核只读：未修改任何产品代码；本分支仅含本 evidence 文件。
