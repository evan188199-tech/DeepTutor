# 后端路由守卫矩阵清点报告（鉴权依赖 × multi_user 能力面）

- 扫描日期：2026-10-07；基线：origin/main @ f07029cfcf2c（只读静态 AST 分析，未改产品代码）
- 扫描范围：`deeptutor/api/main.py`（52 个 `include_router` + 3 个 app 级路由）与 `deeptutor/api/routers/` 全部 42 个含路由模块
- 路由条目总数：**653**（HTTP 644 + WebSocket 9）；与 routers 目录路由装饰器计数（650）按模块逐一核对一致
- 面归类依据：`deeptutor/api/routers/auth.py` 的 `_learning_surface_for_path`（12 条前缀映射、8 条 KB 只读模板、7 条 settings 写模板）与 `deeptutor/multi_user/grants.py` 的 `LEARNING_SURFACES = {books, chat, reading}`
- 守卫分级：include 级守卫组（`_auth`=require_learning_surface / `_admin`=require_admin / `Depends(require_auth)`）、router 级 `APIRouter(dependencies=…)`、路由级 `dependencies=…`、签名级 `Depends(守卫)`、处理器内标记（`ws_require_auth` / `assert_learning_surface` / `_auth_device` 设备令牌）

## 总分布

| 维度 | 计数 |
|---|---|
| scope | api 628 · files 13 · ws 9 · app 3 |
| 有效守卫 | learning-surface 564 · admin 46 · auth-only 28 · device-token 2 · public 13 |
| 能力面 | reading 74 · chat 77 · books 33 · (none) 469 |

守卫 × 面交叉：

| 守卫 \ 面 | reading | chat | books | (none) |
|---|---|---|---|---|
| learning-surface | 74 | 77 | 33 | 380 |
| admin | 0 | 0 | 0 | 46 |
| auth-only | 0 | 0 | 0 | 28 |
| device-token | 0 | 0 | 0 | 2 |
| public | 0 | 0 | 0 | 13 |

## 标记汇总：NO_GUARD 13 · SURFACE_NO_SURFACE_GUARD 0 · ADMIN_OVER_DECLARED_SURFACE 0 · WS_NO_SURFACE_ENFORCEMENT 9

## 覆盖校验

- 全部 42 个含路由模块均被 `main.py` include（modules_never_included=∅，includes_missing_router=∅）
- 每条路由均有守卫归类与面归类两个维度取值（面可为 `(none)`，表示不在学习面映射内、经 `require_learning_surface` 对学习账号默认拒绝）
- routers 目录出现的依赖守卫仅 4 类：`require_auth` / `require_admin` / `require_learning_surface` / `usable_partner`·`manageable_partner`（伙伴资源权），均已纳入分级

## 条目清单（仅条目与 path:line）

### 1. 无守卫（NO_GUARD，13 条，均为代码注释声明的公共入口）

- POST `/api/auth/device-login` — deeptutor/api/routers/auth.py:877 — auth-bootstrap (documented public)
- GET `/api/auth/is_first_user` — deeptutor/api/routers/auth.py:1200 — auth-bootstrap (documented public)
- POST `/api/auth/login` — deeptutor/api/routers/auth.py:814 — auth-bootstrap (documented public)
- POST `/api/auth/logout` — deeptutor/api/routers/auth.py:1112 — auth-bootstrap (documented public)
- GET `/api/auth/openai-codex/callback` — deeptutor/api/routers/auth.py:730 — auth-bootstrap (documented public)
- POST `/api/auth/register` — deeptutor/api/routers/auth.py:1123 — auth-bootstrap (documented public)
- POST `/api/auth/session-handoff/complete` — deeptutor/api/routers/auth.py:1019 — auth-bootstrap (documented public)
- POST `/api/auth/session-handoff/exchange` — deeptutor/api/routers/auth.py:985 — auth-bootstrap (documented public)
- GET `/api/auth/status` — deeptutor/api/routers/auth.py:759 — auth-bootstrap (documented public)
- GET `/api/settings/ui` — deeptutor/api/routers/settings.py:2089 — public-ui-settings (documented public)
- GET `/` — deeptutor/api/main.py:791 — app-root-health
- GET `/health/live` — deeptutor/api/main.py:796 — app-root-health
- GET `/health/ready` — deeptutor/api/main.py:801 — app-root-health

### 2. 声明面但缺面守卫（SURFACE_NO_SURFACE_GUARD，0 条）

- 无：所有归到 reading / chat / books 面的 184 条 HTTP 路由的守卫链都含 `require_learning_surface`。

### 3. 面前缀下 admin 收紧（ADMIN_OVER_DECLARED_SURFACE，0 条）

- 无。

### 4. WebSocket 端点无面守卫（WS_NO_SURFACE_ENFORCEMENT，9 条，信息级：`/ws/*` 不在 `_learning_surface_for_path` 映射内，处理器内仅 `ws_require_auth`）

- WEBSOCKET `/ws/books` — deeptutor/api/routers/book.py:1519
- WEBSOCKET `/ws/knowledge-bases/{kb_name}/progress` — deeptutor/api/routers/knowledge.py:4255
- WEBSOCKET `/ws/mastery-paths` — deeptutor/api/routers/mastery_path.py:788
- WEBSOCKET `/ws/partner-groups/{group_id}` — deeptutor/api/routers/partner_groups.py:338
- WEBSOCKET `/ws/partners/{partner_id}` — deeptutor/api/routers/partners.py:1764
- WEBSOCKET `/ws/questions/generate` — deeptutor/api/routers/question.py:359
- WEBSOCKET `/ws/questions/mimic` — deeptutor/api/routers/question.py:49
- WEBSOCKET `/ws/questions/judge` — deeptutor/api/routers/quiz_judge.py:226
- WEBSOCKET `/ws` — deeptutor/api/routers/unified_ws.py:43

### 5. auth-only 守卫的 HTTP 条目（19 条）

- GET `/api/auth/avatar/{user_id}` — deeptutor/api/routers/auth.py:1353
- POST `/api/auth/device/heartbeat` — deeptutor/api/routers/auth.py:1080
- GET `/api/auth/profile` — deeptutor/api/routers/auth.py:1241
- PUT `/api/auth/profile` — deeptutor/api/routers/auth.py:1260
- DELETE `/api/auth/profile/avatar` — deeptutor/api/routers/auth.py:1339
- PUT `/api/auth/profile/avatar` — deeptutor/api/routers/auth.py:1281
- GET `/api/auth/profile/learner-profile` — deeptutor/api/routers/auth.py:1488
- PUT `/api/auth/profile/learner-profile` — deeptutor/api/routers/auth.py:1496
- POST `/api/auth/session-handoff` — deeptutor/api/routers/auth.py:908
- GET `/api/file-preview/pdf` — deeptutor/api/routers/file_preview.py:186
- POST `/api/file-preview/pdf` — deeptutor/api/routers/file_preview.py:194
- GET `/api/marginnote4/devices` — deeptutor/api/routers/marginnote4.py:177
- DELETE `/api/marginnote4/devices/{device_id}` — deeptutor/api/routers/marginnote4.py:194
- POST `/api/marginnote4/pair` — deeptutor/api/routers/marginnote4.py:149
- GET `/api/marginnote4/status` — deeptutor/api/routers/marginnote4.py:203
- GET `/files/outputs/{output_path:path}` — deeptutor/api/routers/outputs.py:75
- HEAD `/files/outputs/{output_path:path}` — deeptutor/api/routers/outputs.py:76
- GET `/files/workspace-items/{workspace_id}/{workspace_item_id}` — deeptutor/api/routers/workspace.py:327
- HEAD `/files/workspace-items/{workspace_id}/{workspace_item_id}` — deeptutor/api/routers/workspace.py:328

### 6. admin 守卫条目（46 条；分布：auth 11 · knowledge 6 · mcp_settings 5 · multi_user 11 · partners 3 · space_cli_apps 2 · subagents 1 · system 4 · video_learning 3；逐条见 CSV）

### 7. 设备令牌守卫（device-token，2 条）

- POST `/api/marginnote4/heartbeat` — deeptutor/api/routers/marginnote4.py:267
- POST `/api/marginnote4/sync` — deeptutor/api/routers/marginnote4.py:217

## 复现

```bash
python3 evidence/auth-matrix-2026-10-07/scan_auth_matrix.py   # 重新生成 auth_matrix.csv 与计数
```

