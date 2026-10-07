# scan: web API 客户端 ↔ 后端路由实况对照（AGEN-1107）

- 卡：AGEN-1107 · 扫描日期：2026-10-07 · 基线：`origin/main` @ `f07029cfcf2c8dfccdb671cdfc343db8334f5741`（release v1.6.13，2026-10-04），只读对照，未改任何代码、未启动任何服务
- 结论预览：**PASS（零硬漂移）**。web/ 全部 469 个 HTTP 调用点与后端 644 条 REST 路由（532 个唯一 path，含 1 条 `include_in_schema=False` 隐藏别名）逐一对照：**不存在路由 0、方法不一致 0、查询参数名不一致 0、字面 JSON body 键不一致 0**。软漂移共 8 条（2 条枚举路由耦合 + 4 条良性参数遮蔽提示 + 2 条死查询参数），另附 278 条"后端有、静态未见 web 调用"的路由清单（inventory，非缺陷，其中 97 条已被证实走动态拼接 URL）。
- 去重边界：本卡 = **客户端调用点 × 后端路由实况**（绕过生成契约，直接对 `deeptutor/api` 实时路由表，因此能看到契约里没有的隐藏路由）。各轴归属：后端路由↔契约 = scan-route-contracts（AGEN-818/同前缀卡）；契约↔实时 schema = scan-openapi-drift（AGEN-837）；前端调用面↔生成契约 = scan-web-api-usage（AGEN-857）；导读 = guide-web-contracts。本卡与其零重叠结论互相印证：AGEN-857 的 F1/F2 在本卡分别复现为 B3a/B4，计数一致。
- 扫描脚本：`scan_web_client_parity.py`（stdlib + 仓库 .venv 的 fastapi；两次运行输出逐字节一致）。机器结果：`parity.json`。

## 复现

```bash
cd /Users/Shared/DeepTutor && .venv/bin/python \
  evidence/web-client-parity-20261007/scan_web_client_parity.py \
  --repo-root <本仓库根> --outdir <输出目录> \
  --ref f07029cfcf2c8dfccdb671cdfc343db8334f5741
```

（进程内 `import deeptutor.api.main` 遍历 `app.routes`，不启动服务器；运行时副作用仅限 `$HOME` 下的默认 settings 文件。）

## 口径（验收 1 · 方法）

前端侧沿用 evidence/web-api-usage-20261006 验证过的 AST-lite 提取器（平衡括号 + JS 字符串/模板字面量 tokenizer）：

1. **调用点**：`web/**/*.{ts,tsx}`（排除 `node_modules/.next/contracts/coverage/dist/tests/e2e`，`contracts/` 即生成物）共 67 个文件含后端调用；包装器 `apiFetch / requestJson / requestVoid / requestBlob / asJsonOrThrow / asJson / fetch`，另盘 `new WebSocket / new EventSource`。`asJson(...)`/`asJsonOrThrow(fetch(...))` 内层 fetch 会向下解包到真实 URL。
2. **URL 解析**：字面量与模板字面量（`${...}` → `{}` 标记并保留表达式）；`apiUrl/wsUrl/scopedUrl` 递归解包；模块级字符串常量跨文件 import 解析（如 `BASE="/api/reading"`、`CLI_APPS_BASE_PATH`）；三元字面量各计一点。
3. **body 键提取**：调用 span 内 `body:` / `body: JSON.stringify({...})` 的对象字面量取 depth-1 键——只在键位（`{` 或 `,` 之后）识别，`{ server_url: serverUrl }` 的值标识符不会被误记为键（扫描器内建了对应回归：值标识符、`null`、`false`、`...spread` 均不计）。
4. **后端路由表（本卡核心差异点）**：进程内遍历 FastAPI `app.routes`，对每个 `_IncludedRouter` 取 `include_context.prefix + original_router.routes`，得到**实况全量路由**：method/path、`include_in_schema`、dependant 的 query/path 参数名与类型、Pydantic body model 字段名与类型、endpoint 源码 file:line。共 644 REST 路由 / 532 唯一 path / 9 WS 路由；比生成契约多的 1 条即隐藏别名 `GET /api/knowledge-bases/list`（knowledge.py:2963，代理安全别名）。
5. **匹配顺序**：as-is（URL 字面段 ↔ 后端字面段，后端 `{param}` 吸收任意段；URL 字面段落进 `{param}` 记 param-shadow）→ dynamic-segment-enumeration（恰一个非末位 `{}`，后端该位全为字面路由 → 枚举耦合 B3a）→ dynamic-final-segment（末位为 `{}`，后端多一段字面或 `{param}`）→ suffix-stripped（末段 `...${qs ? '?x' : ''}` 去尾再配）→ final-dropped。方法未知（如 `action === "status" ? "GET" : "POST"`）时按候选路由方法并集查参。
6. **漂移分级**：A1 路由不存在 / A2 方法未声明（硬漂移）；B1 查询参数名后端未声明 / B2 body 键不在 body model（硬漂移）；B3a 枚举路由耦合（后端把枚举展开成字面路由、前端自行参数化，取值越界即 404）；B3b 参数遮蔽提示（URL 字面值被 `{param}` 吸收，运行时经枚举校验，良性）；B4 死查询参数（路由声明 0 个 query，参数被 FastAPI 静默丢弃）；C1 静态未见 web 调用的路由（C1a = 落在动态拼接 URL 常量伞下；C1b = 静态完全找不到调用者）。

## 覆盖统计

| 类别 | 数量 |
|---|---|
| 调用点合计 | 469 |
| 后端调用点（已分类） | 379（POST 124 / PUT 38 / DELETE 36 / PATCH 12 / 其余 169 处未写 method 即 fetch 默认 GET）|
| 动态 URL（变量/表达式，静态不可判定） | 78 |
| 后端-不可判定（`${BASE}${path}` 常量拼接，见 C1a） | 12 |
| WebSocket / SSE 调用点 | 8（后端 WS 路由 9 条，inventory 已核对样例）|
| **确认硬漂移：路由 / 方法 / 查询参数 / body 键** | **0 / 0 / 0 / 0** |
| 软漂移：B3a 枚举路由耦合 | 2（同一模式 GET+PUT）|
| 提示：B3b 参数遮蔽 | 4 |
| 软漂移：B4 死查询参数 | 2 |
| C1 静态未见调用的后端路由 | 278（C1a 97 + C1b 181；非缺陷清单）|
| body 键可验证调用点 | 97，其中 95 条命中 Pydantic model 全部通过，2 条 body 为 dict 无法静态验证 |

## 漂移条目（每条附两侧 path:line，验收 2）

### B3a-1/2 · 枚举路由耦合：`rag-pipelines/${provider}/config`（2 点）

- 调用侧：`web/features/knowledge/api/client.ts:505`（`getEngineConfig`，GET）、`client.ts:524`（`updateEngineConfig`，PUT），URL 模板 `/api/knowledge-bases/rag-pipelines/${provider}/config`
- 后端侧：无 `/rag-pipelines/{provider}/config` 参数化路由；只有 12 条字面路由（6 provider × GET/PUT）：`pageindex`（knowledge.py:1479/1489）、`ima`（:1532/1542）、`llamaindex`（:1586/1598）、`graphrag`（:1626/1638）、`lightrag`（:1689/1709）、`lightrag-server`（:1774/1784）
- 影响：对已知 provider 正常；provider 取值超出枚举即 404，且新增 provider 必须同步改前端。与 AGEN-857 F1 同源（该卡在契约轴观察到同一事实；本卡证实契约外后端实况同样没有参数化路由）
- 建议（可拆卡）：后端补 `/rag-pipelines/{provider}/config` 参数化路由（入口处校验 provider 枚举），或前端改用按 provider 的字面量常量联合。二选一后重新生成契约

### B4-1/2 · 死查询参数：`resource_library=true`（2 点）

- 调用侧：`web/components/knowledge/KnowledgePage.tsx:189` → `GET /api/knowledge-bases/{kb_name}?resource_library=true`；`web/features/knowledge/api/client.ts:293` → `GET /api/knowledge-bases/list?resource_library=true`
- 后端侧：`get_knowledge_base_details(kb_name: str)`（knowledge.py:2978）不读任何 query；`list_knowledge_bases_proxy_alias()`（knowledge.py:2963，`include_in_schema=False` 的代理安全别名）同样不读任何 query → 参数被 FastAPI 静默丢弃
- 与 AGEN-857 F2 同一结论，本卡在其上补充了隐藏别名侧的后端实况证据
- 建议（可拆卡）：删除两处死参数；若原意是"资源库视图过滤"，先在后端补参数并重新生成契约

### B3b · 参数遮蔽提示（4 点，良性，不需修卡）

| 调用侧 | 后端侧 | 说明 |
|---|---|---|
| `web/components/memory/MemorySection.tsx:721` `GET /api/memory/trace/kb?limit=200` | `get_trace(surface, limit=200, offset=0)` memory.py:680 | `kb` 是 `{surface}` 的合法枚举值（`_validate_surface` 404 兜底），limit 已声明 |
| `web/lib/memory-graph.ts:254` `GET /api/memory/doc/L2/{key}` | `get_doc(layer, key)` memory.py:140 | `L2` 是 `{layer}` 合法枚举值（`_validate_layer`）|
| `web/lib/memory-graph.ts:265` `GET /api/memory/doc/L3/{slot}` | 同上 | 同上 |
| `web/lib/partners-api.ts:204` `GET /api/partners/${id}?include_secrets=true` | `get_partner(partner_id, include_secrets: bool = Query(False, ...))` partners.py:951 | include_secrets 已声明，参数无漂移；仅 URL 字面值被 `{partner_id}` 吸收的提示 |

## C1 · 静态未见 web 调用的后端路由（278 条 = 97 C1a + 181 C1b）

性质：**inventory，不是缺陷清单**。后端三入口（CLI / WebSocket / Python SDK）共享同一路由面，其中相当一部分天然只被 CLI/SDK 消费。两类构成：

- **C1a（97 条，已被证实的动态拼接盲区）**：调用 URL 由模块常量拼接，如 `web/lib/reading-workspace-api.ts:5` `const BASE = "/api/reading"` + `` apiFetch(apiUrl(`${BASE}${path}`)) ``（:126）、`web/lib/session-activity.ts:19` `OUTPUTS_URL_PREFIX = "/files/outputs/"`、`web/lib/cli-apps-api.ts` 的 `CLI_APPS_BASE_PATH`。落在 `/api/reading`、`/api/space/cli-apps`、`/files/outputs`、`/api/knowledge-bases` 等伞下的路由无法静态判定具体命中项。
- **C1b（181 条，静态完全找不到调用者）**：主体为 book.py（33，内容面走 `/ws/books`）、settings.py（33）、workspace.py（23）、multi_user.py（13）、mastery_path.py（13）、partners.py（10）、file_library.py（8）、practice.py（8）、space_mcp.py（8）、partner_groups.py（8）等。已知反例（证明 C1b 仍偏保守）：`/api/books/{book_id}/spine`（book.py:776）实际被 `web/hooks/useTopicSourceLibrary.ts:380` 经应用级包装器 `sourceRequest()`（:475）调用——应用级包装器不在标准 fetch 包装器集合内，静态不可见。

给拆卡的用法：修契约卡不应从 C1 直接动手；需要"哪些后端能力 web 还没接"的产品盘点时，以 C1b 的 book/settings/workspace/multi_user 四块为起点人工确认。

## 抽样人工复核（验收 3 · 15 条，含全部 8 条软漂移）

| # | 调用侧 | 后端侧（实况） | 方法 | 结论 |
|---|---|---|---|---|
| 1 | `lib/notebook-api.ts:166` `POST .../actions/${mode}`（move\|copy），body `{target_notebook_id}` | notebook.py:428 `copy_record` + :444 `move_record`，body=MoveRecordRequest.target_notebook_id | POST | ✓ 两字面路由均存在，body 键一致 |
| 2 | `lib/partners-api.ts:603` `POST /{id}/sessions/${action}`（archive\|resume\|delete）| partners.py:1418/1442/1473 三字面路由，SessionKeyBody.session_key | POST | ✓ |
| 3 | `lib/video-learning-api.ts:426` `account/${action}`，`status?GET:POST` | video_learning.py:199 GET status / :149 POST authorize / :204 POST disconnect | GET/POST | ✓ 三分支齐全，方法三元按并集通过 |
| 4 | `features/knowledge/api/client.ts:1457` `GET {kb}/reindex-config?embedding_model=...` | knowledge.py:3993 `get_reindex_config(kb_name, embedding_model)` | GET | ✓ 参数名逐一对应（suffix-stripped 变体正确解析）|
| 5 | `lib/cli-apps-api.ts:231` `GET ${CLI_APPS_BASE_PATH}/catalog?q&category&installable_only&cursor&limit` | space_cli_apps.py:109 `get_catalog` 五个 query 参数 | GET | ✓ 五参数逐一对应（跨文件 import 常量解析）|
| 6 | `components/knowledge/KnowledgePage.tsx:189` `GET {kb}?resource_library=true` | knowledge.py:2978 handler 签名无 query | GET | ✗→B4 死参数证实 |
| 7 | `features/knowledge/api/client.ts:293` `GET /list?resource_library=true` | knowledge.py:2963 隐藏别名无 query | GET | ✗→B4 死参数证实 |
| 8 | `features/knowledge/api/client.ts:505` `GET rag-pipelines/${provider}/config` | knowledge.py:1479-1784 共 12 条字面路由，无参数化 | GET | ✗→B3a 证实 |
| 9 | `features/knowledge/api/client.ts:524` `PUT rag-pipelines/${provider}/config` | 同上（PUT 列 :1489…:1784）| PUT | ✗→B3a 证实 |
| 10 | `components/memory/MemorySection.tsx:721` `GET trace/kb?limit=200` | memory.py:680 `{surface}` 枚举 + limit | GET | ✓ B3b 良性 |
| 11 | `lib/memory-graph.ts:254,265` `GET doc/L2|L3/${key}` | memory.py:140 `{layer}/{key}` + `_validate_layer` | GET | ✓ B3b 良性 |
| 12 | `lib/partners-api.ts:204` `GET ${id}?include_secrets=true` | partners.py:951 `include_secrets: bool = Query(False, ...)` | GET | ✓ |
| 13 | `features/knowledge/api/client.ts:828` `POST probe-kiwix {server_url, zim_name}` | knowledge.py:2567 `KiwixConnectionRequest(server_url, zim_name)`，handler :2593 | POST | ✓ body 键与 model 一致 |
| 14 | `lib/quiz-judge.ts:40` `WS /ws/questions/judge` | quiz_judge.py:226 `websocket_quiz_judge` | WS | ✓ inventory 样例 |
| 15 | `hooks/useKnowledgeProgress.ts:173` `WS /ws/knowledge-bases/{kb}/progress` | knowledge.py:4255 `websocket_progress` | WS | ✓ inventory 样例 |

15/15 与扫描器结论一致（其中 4 条软漂移由人工证实，11 条 ok/良性证实）。抽样方法：全部 8 条软漂移 100% 人工复核 + 按 URL 形态分层随机抽 ok 调用点（字面 GET、动态末段、suffix-stripped、body model、WS 各≥2）。

## 可拆卡条目（供契约修复卡拆分）

1. **B3a**（1 卡即可）：`rag-pipelines/{provider}/config` 参数化路由 or 前端字面量联合二选一；涉及 knowledge.py:1479-1784 与 features/knowledge/api/client.ts:505/524；改后须重跑契约同步。
2. **B4**（1 卡）：删除 KnowledgePage.tsx:189 与 client.ts:293 的 `resource_library=true`；若要保留语义先在后端补 query 参数。
3. （可选，非漂移）settings.py 33 条、book.py 33 条 REST 面的 web 接入盘点，以 C1b 清单为底稿（见 parity.json `C1_backend_routes_uncalled`，含每条 file:line）。

## 明确不在本卡范围

- 请求/响应**类型级**漂移（契约轴的 D1/D2 已由 scan-openapi-drift 覆盖：reading PositionPayload `number|null` 等）；本卡 body 校验仅到键名级。
- 78 个动态 URL 调用点与 12 个 `${BASE}${path}` 拼接点的逐点展开（静态不可判定；伞下路由已进 C1a）。
- WS 消息协议对照（unified_ws 事件面），仅 inventory。
