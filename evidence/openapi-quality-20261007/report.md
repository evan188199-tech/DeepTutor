# OpenAPI schema 质量清点（AGEN-1000）

- 基线: `origin/main` @ `f07029cfc` (v1.6.13)，分支 `scan/openapi-quality-20261007`，全程只读，未改任何产品代码
- 范围: `deeptutor/api/routers/` 全部 44 个非 `__init__` 文件（40 个含 HTTP 路由、3 个纯 WebSocket 模块、1 个辅助 schema），AST 静态扫描
- 去重说明: 本卡与 `scan-openapi-drift`（app→schema 漂移）、`scan-route-contracts`（前后端对照）、`sync-contracts-regen`、`gate-contract-drift` 互补——聚焦 **schema 本身的质量**（响应模型缺失 / 4xx 未文档化 / 分页不一致 / 可选性漂移），不与上述卡的结果重叠

## 覆盖与总览

- HTTP 路由 **637** 条 / 40 个含路由文件，WebSocket 路由 9 条（OpenAPI 本身不收录 WS，仅计数）
- `response_model` 显式声明: **60/637 (9.4%)** — 其余路由在 OpenAPI 中成功响应为空 schema `{}` 或完全不出现
- `responses=` 错误文档声明: **1/637** — 运行时 raise 的 4xx 几乎全部不在 schema 中
- 存在未文档化 4xx raise 的路由: **250** 条

## 问题分级计数

| 类型 | high | medium | low | info |
|---|---|---|---|---|
| D 响应包漂移 | 0 | 6 | 0 | 0 |
| A 响应模型缺失 | 332 | 105 | 140 | 0 |
| D 可选性漂移 | 0 | 4 | 0 | 0 |
| C 分页存在(基线) | 0 | 0 | 0 | 23 |
| C 分页结构(无 total) | 0 | 6 | 0 | 0 |
| C 分页无校验 | 0 | 14 | 0 | 0 |
| B 4xx 未文档化 | 17 | 233 | 0 | 0 |
| B' 5xx 未文档化 | 0 | 0 | 105 | 0 |
| **合计** | 349 | 368 | 245 | 23 |

> 严重度约定: high=契约核心缺陷（返回裸 dict 无任何 schema / 单路由 ≥3 个未文档化 4xx）；medium=单点不一致；low=天然无 schema（流/文件）或 5xx；info=基线统计。

## A. 响应模型缺失

- high 332 条：返回裸 dict 字面量，OpenAPI 成功响应为空 schema。集中区: knowledge(66/81), partners(48/48), auth(26/29), book(33/33), skills(12/12)
- medium 105 条：返回 Response 子类（FileResponse/HTMLResponse/JSONResponse 等，schema 完全缺席）或函数已标注 `-> Model/-> dict` 却未声明 response_model
- low 140 条：StreamingResponse/SSE/文件下载等天然无 JSON schema，可仅补 `responses` 描述

## B. 4xx 错误未文档化

- 250 条路由 raise `HTTPException(4xx)` 但未声明 `responses=`；代码分布: 404×166, 400×95, 409×48, 422×21, 403×9, 413×3, 405×2, 415×1, 401×1, 429×1, 416×1
- 单路由 ≥3 个未文档化 4xx（high）: 17 条，如 `PUT /api/skills/{name}`（404/403/409/400, skills.py:280）、`POST /api/reading/materials/…/extensions/…`（reading_extensions.py:195,363）
- 注: FastAPI 仅自动文档化 422 校验错误；`HTTPException` 一律需要 `responses={...}` 才进 schema

## C. 分页命名与结构

- 参数风格并存: `limit(+offset)` 18 条 / cursor 4 条 / `page(+page_size)` 1 条，无统一约定
- 同名参数默认值/上限漂移: `limit` 默认值有 3/20/24/30/50/60/100/200/500，上限 le=100/200/500/1000 或无上限并存
  - `cursor` default=`0` ×2
  - `cursor` default=`''` ×2
  - `limit` default=`Query(default=50, ge=1, le=200)` ×5
  - `limit` default=`Query(200, ge=1, le=500)` ×3
  - `limit` default=`50` ×2
  - `limit` default=`200` ×2
  - `limit` default=`3` ×1
  - `limit` default=`100` ×1
  - `limit` default=`Query(default=60, ge=1, le=200)` ×1
  - `limit` default=`Query(default=20, ge=1, le=100)` ×1
  - `limit` default=`Query(default=50, ge=1, le=100)` ×1
  - `limit` default=`Query(default=500, ge=1, le=1000)` ×1
  - `limit` default=`24` ×1
  - `limit` default=`30` ×1
  - `page` default=`Query(default=1, ge=1, le=1000)` ×1
- 无校验分页参数（裸默认、无 ge/le）: 14 处，如 dashboard.py:21 `limit: int = 50`、memory.py:681 `limit: int = 200, offset: int = 0`
- 返回裸列表/无 total 包封: 6 条，如 `GET /api/sessions`（sessions.py:117 只回 `{sessions}` 无 total，而同文件 `/search` 回 `sessions+total+limit+offset`，同资源两种包封）

## D. 可选性标注与实际返回漂移

- 包封漂移（同路由不同分支返回不同字段集，OpenAPI 无从表达可选性）: 6 条。典型: `POST /api/auth/login`（auth.py:818，禁用 auth 分支回 `ok+message`，正常分支回 `ok+user_id+username+role+is_admin`）；`GET /api/settings`（settings.py:897，非 admin 仅 `ui`，admin 另有 catalog/providers 等 4 键）；`GET /api/system/memory`（system.py:418，受限分支仅 `available`）
- 参数注解漂移: 4 处 `Form(None)` 裸类型注解，如 knowledge.py:3316-3318 `rag_provider: str = Form(None)`（schema 呈现为必填 string，运行时实际可为 None；`rel_paths: list[str] = Form(None)` 更是类型级矛盾）
- 正向结论: 未发现 `Optional[...]` 无默认值的路由参数；`-> Model` 注解与 dict 返回的冲突未检出（绝大多数路由无返回注解）

## Top 修复清单（按组合评分）

评分 = 2×未文档化 4xx 数 + 响应模型缺失加权（dict=3 / 注解=1）+ 包封/结构漂移。取 Top 15：

| # | 路由 | 位置 | 未文档化 4xx | 返回形态 |
|---|---|---|---|---|
| 1 | `PATCH /api/courses/{course_id}` | `courses.py:96` | 400,404,409 | dict |
| 2 | `POST /api/knowledge-bases/{kb_name}/files/move` | `knowledge.py:3122` | 400,404,409 | dict |
| 3 | `POST /api/knowledge-bases/{kb_name}/upload` | `knowledge.py:3311` | 400,404,409 | dict |
| 4 | `PUT /api/mastery-paths/topics/{path_id}/sessions/{session_id}/mode` | `mastery_path.py:738` | 404,409,422 | dict |
| 5 | `POST /api/partners/{partner_id}/sessions/resume` | `partners.py:1442` | 404,409,422 | dict |
| 6 | `POST /api/partners/{partner_id}/sessions/branch` | `partners.py:1497` | 400,409,422 | dict |
| 7 | `POST /api/reading/materials/{material_id}/extensions/{extension_id}/actions/{action}` | `reading_extensions.py:195` | 400,403,404,422 | -> dict[str, Any] |
| 8 | `POST /api/reading/materials/{material_id}/extensions/quiz/answers` | `reading_extensions.py:363` | 403,404,409,422 | -> dict[str, Any] |
| 9 | `PATCH /api/sessions/{session_id}/organization` | `sessions.py:360` | 400,404,409 | dict |
| 10 | `PUT /api/skills/tags/{tag}` | `skills.py:103` | 400,404,409 | dict |
| 11 | `PUT /api/skills/{name}` | `skills.py:280` | 400,403,404,409 | -> dict[str, object] |
| 12 | `DELETE /api/skills/{name}` | `skills.py:304` | 400,403,404 | dict |
| 13 | `POST /api/books/{book_id}/learning-captures` | `book.py:627` | 400,404 | dict |
| 14 | `PATCH /api/books/{book_id}/learning-captures/{capture_id}` | `book.py:684` | 400,404 | dict |
| 15 | `POST /api/books` | `book.py:810` | 400,403 | dict |

建议优先序: ① 给 Top 15 路由补 `response_model` + `responses=`（一次性消除约 60 个 high/medium）；② 统一分页参数约定（建议 `limit/offset` + `Query(ge/le)` + `items/total` 包封），迁移 `page` 风格与裸默认参数；③ 为 6 条包封漂移路由定义显式响应模型，把角色/功能分支的字段差异显式化；④ 修正 4 处 `Form(None)` 注解。

## 抽样核实（对照现行代码，8 条 ≥ 要求的 5 条）

| 发现 | 位置 | 核实结果 |
|---|---|---|
| 登录包封漂移 + 401 未文档化 | auth.py:817-859 | 属实：`AUTH_ENABLED` 关闭分支回 `{ok,message}`，正常分支回 5 键；两处 `HTTPException(401)` 无 `responses=` |
| 4 个未文档化 4xx | skills.py:280-297 | 属实：404/403/409/400 全部裸 raise，无 `responses=` |
| 分页无 total 包封 | sessions.py:117-133 | 属实：回 `{sessions}` 无 total；分支甚至直接回 service 裸列表；同文件 `/search`（:135-151）回 `sessions+total+limit+offset`，同资源双包封 |
| 角色分支包封漂移 | settings.py:893-910 | 属实：非 admin 仅 `ui`，admin 回 5 键 |
| `Form(None)` 注解漂移 | knowledge.py:3315-3319 | 属实：`str = Form(None)`、`list[str] = Form(None)` |
| 无校验分页参数 | memory.py:680-691 | 属实：`limit: int = 200, offset: int = 0` 裸默认，回 `{surface,events,offset,limit}` 无 total |
| 无校验分页参数 | dashboard.py:20-27 | 属实：`limit: int = 50` 裸默认 |
| 流/文件无 schema（low） | attachments.py:39、auth.py:729 | 属实：FileResponse / HTMLResponse 直接返回 |

## 复现

```bash
python3 evidence/openapi-quality-20261007/scan_openapi_quality.py <repo_root> <out_dir>
# 输出 openapi-quality-data.json：637 条路由逐条记录（含每条 raise 的 status 与返回形态）+ 967 条 findings + aggregates
```

数据明细见 `data/openapi-quality-data.json`；每条 finding 均含 `file:line` 与路由全路径。
