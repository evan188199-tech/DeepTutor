# scan: 前端 API 调用面 vs 生成契约漂移清点（AGEN-857）

- 基线：`origin/main` @ `f07029cfcf2c8dfccdb671cdfc343db8334f5741`（release: v1.6.13，2026-10-04 21:35 +0800），只读对照，未改任何业务代码
- 契约侧：`web/contracts/schema/openapi.json`（531 paths）与 `web/contracts/generated/api.ts`（路径键集合与 schema 完全一致，diff = 0）
- 扫描脚本：`scan_web_api_usage.py`（stdlib-only，可复现，重复运行 SHA256 一致）；机器结果：`usage.json`

## 复现

```bash
python3 evidence/web-api-usage-20261006/scan_web_api_usage.py \
  --repo web --outdir <输出目录> --ref f07029cfcf2c8dfccdb671cdfc343db8334f5741
```

## 口径（AST-lite：平衡括号 + JS 字符串/模板字面量 tokenizer，正则联动）

1. **调用点**：`web/**/*.{ts,tsx}`（排除 `node_modules/.next/contracts/coverage/dist`；`contracts/` 即契约本身）共 1233 个文件；包装器 `apiFetch / requestJson / requestVoid / requestBlob / asJsonOrThrow / fetch`（无 axios/XHR）；另盘 `new WebSocket / new EventSource`。
2. **URL 解析**：字面量与模板字面量（`${...}` 归一为 `{}` 标记并保留表达式）；`apiUrl/wsUrl/scopedUrl` 包裹递归解包；**模块级字符串常量与跨文件 import 常量解析**（如 `BASE="/api/reading"`、`EXTENSION_ENDPOINTS`）；三元字面量分支各计一点。
3. **匹配顺序**：as-is（URL 字面段↔契约字面段，契约 `{param}` 接受任意段）→ dynamic-final-segment（末段恰为 `{}` 的有界枚举，如 `${mode}` ∈ move|copy）→ suffix-stripped（末段以 `{}` 结尾的条件查询拼接 `...${qs ? '?x' : ''}`）→ final-dropped；字面段落进契约 `{param}` 记 `param-shadow` 待复核。方法从调用窗提取（`method:` 字面量；三元方法如 `action === "status" ? "GET" : "POST"` 记为方法未知，按方法并集查参）。
4. **查询参数**：字面 `?a=`、插值字面量内 `[?&]n=`、`URLSearchParams` 变量按**函数窗口**联动（变量名跨函数复用，文件级并集会误报）。
5. **白名单/豁免**：`dt_workspace`（`scopedUrl()` 对所有后端 URL 注入，见发现 F3）；测试 mock 文件的动态 URL。

## 覆盖统计

| 类别 | 数量 |
|---|---|
| 调用点合计 | 455 |
| 后端 HTTP 调用点（已分类） | 379 |
| 后端-不可判定（插值未解析，见 R4） | 12 |
| 动态 URL（变量/表达式，静态不可判定） | 51 |
| 非后端路径（/turn 等，全部为 tests/ mock） | 9 |
| 外部绝对 URL（tests/ 本地端口） | 4 |
| WebSocket / SSE 调用点 | 8 |
| **确认漂移：端点** | **2（同一模式，GET+PUT）** |
| 确认漂移：方法 | 0 |
| 确认漂移：查询参数名 | 0 |

抽样验证：18 个随机 "ok" 调用点逐一对照契约，18/18 存在且方法吻合。

## F1 · 确认漂移：`rag-pipelines/${provider}/config` 模式 vs 字面量路由（2 点）

- 调用侧：`web/features/knowledge/api/client.ts:505`（GET）、`client.ts:524`（PUT），URL 模板 `/api/knowledge-bases/rag-pipelines/${provider}/config`
- 契约侧：无 `/api/knowledge-bases/rag-pipelines/{provider}/config` 参数化路径；契约（及后端 `deeptutor/api/routers/knowledge.py:1479-1709`）只有 6 条字面路由：`graphrag`(api.ts:2917)、`ima`(2961)、`lightrag-server`(2985)、`lightrag`(3009)、`llamaindex`(3057)、`pageindex`(3104) 的 `/config`（各 get+put）
- 影响：运行时对已知 provider 正常（各字面路由命中），但前端把后端枚举参数化了——provider 取值超出枚举即 404，且 OpenAPI 类型层完全看不到这组调用；新增 provider 需要同步改前端
- 建议（可拆卡）：后端补一条 `/rag-pipelines/{provider}/config` 参数化路由（或前端改用按 provider 的字面量常量联合），二选一，随后重新生成契约

## F2 · 死参数：`resource_library=true`（2 个调用点）

- `web/components/knowledge/KnowledgePage.tsx:189` → `GET /api/knowledge-bases/{kb_name}?resource_library=true`：契约该端点声明 0 个查询参数；后端 `get_knowledge_base_details`（knowledge.py:2979）不读任何 query → 参数被 FastAPI 静默丢弃
- `web/features/knowledge/api/client.ts:293`（三元两分支）→ `GET /api/knowledge-bases/list?resource_library=true`：后端 `list_knowledge_bases_proxy_alias`（knowledge.py:2964，`include_in_schema=False` 的代理安全别名）同样不读该参数
- 建议（可拆卡）：删除两处死参数；若原意是“资源库视图过滤”，需要先在后端补参数并重新生成契约

## F3 · 横切：`dt_workspace` 对契约不可见

- `web/lib/workspace-scope.ts:11`（`scopedUrl`）给**所有**后端 URL 注入 `dt_workspace`；`web/lib/session-api.ts:213` 还显式 `qs.set("dt_workspace", ...)`
- 契约侧：0/531 条路径声明 `dt_workspace`；`GET /api/sessions` 声明的是 `workspace_id`
- 前端侧结论：调用点与契约之间不存在可类型化的作用域通道；`dt_workspace` 是否被后端逐路由接受属于 scan-openapi-drift（契约↔后端路由轴）的交叉项，本卡仅记录

## F4 · `/api/knowledge-bases/list`：故意排除的契约外调用（非缺陷）

- 调用侧 `client.ts:293` 两个分支；契约无此路径；后端 knowledge.py:2964 `include_in_schema=False`（注释写明：集合 URL 被前端流式 multipart create 占用，浏览器列表请求走此别名）
- 结论：调用正确、排除有文档；仅建议在 `web/contracts/README.md` 登记该豁免，避免后续扫描重复报痒

## 复核清单（静态不可完全判定，非漂移）

- **R1 param-shadow（6）**：字面段命中契约参数位。`client.ts:293×2`（见 F4）；`components/memory/MemorySection.tsx:721` `/api/memory/trace/kb`→`{surface}`；`lib/memory-graph.ts:254,265` `L2/L3`→`{layer}`；`lib/partners-api.ts:204`（include_secrets 条件后缀）→`{partner_id}`。均为合法取值的可能性高，建议人工过目
- **R2 dynamic-final-segment（4）**：末段为运行期枚举，契约存在对应字面路由：`notebook-api.ts:166`（move|copy，POST 已声明）、`partners-api.ts:603`（archive|branch|delete|resume，POST 已声明）、`video-learning-api.ts:426`（status|authorize|disconnect）、`visualizers-api.ts:55`（enable|disable，POST 已声明）
- **R3 suffix-stripped（9）**：条件查询拼接，剥离后全部命中契约（含参检查通过）：`knowledge/client.ts:1457`、`cli-apps-api.ts:231`、`notebook-api.ts:372,591,602,628`、`partners-api.ts:535`、`reading-api.ts:254`、`skills-api.ts:206`
- **R4 backend-indeterminate（12）**：基址为函数参数（`mcp-api.ts` 9 点，`basePath` ∈ `MCP_ADMIN_BASE_PATH=/api/settings/mcp` 或 `MCP_SPACE_BASE_PATH=/api/space/mcp`，两族路由契约均在）或 `${BASE}${path}` 直拼（`book-api.ts:60`、`codebuddy-auth.ts:17`、`DataMigrationSettingsSection.tsx:59`、`reading-workspace-api.ts:126`；其调用方字面 path 如 `/status`、`/discover` 均在契约内）
- **R5 动态 URL（51）**：变量/表达式入参，静态不可判；含 `EXTENSION_ENDPOINTS`、`PAGEINDEX/IMA/LLAMAINDEX_CONFIG_PATH` 常量等（常量本身可解析，函数内二次拼接归入此类）
- **R6 WS/SSE（8）**：OpenAPI 不含 WS 路由，不在本卡 drift 口径：`features/chat/transport/socket.ts:21`、`lib/quiz-judge.ts:40`（/ws/questions/judge）、`hooks/useKnowledgeProgress.ts:173`（/ws/knowledge-bases/{}/progress）与 `:296`、`features/settings/store/SettingsStore.tsx:1994`、`lib/book-api.ts:42`、`lib/use-book-stream.ts:49`、`lib/reconnecting-websocket.ts:70`（通用封装）

## 裸 URL / 契约类型使用

- `web/contracts/generated/api.ts` 仅被 **1** 个文件 import（`lib/usage-statistics.ts`，且只取 `components` 类型）；无 openapi-fetch/createClient 之类类型化客户端
- 即 379 个后端调用点 100% 为“裸 URL + 手写响应类型”形态。这不是逐条缺陷，而是形态结论：契约 regenerated 后前端无编译期保护，漂移只能靠本类扫描发现

## 可拆卡建议

1. **fix(web)**: 清理 `resource_library` 死参数（KnowledgePage.tsx:189、knowledge/api/client.ts:293）——小卡，低风险
2. **fix(web/api 或 backend)**: `rag-pipelines/${provider}/config` 参数化 vs 字面路由对齐（F1）——需后端定方向后重生成契约
3. **chore(contracts)**: `web/contracts/README.md` 登记 `include_in_schema=False` 豁免清单（当前 1 条：/api/knowledge-bases/list），并在契约 README 说明 `dt_workspace` 由 scopedUrl 注入、契约层不可见（F3/F4）
4. **chore(web)**（可选）: 为 `mcp-api.ts` 的 `basePath` 参数改传模块常量并加字面量类型联合，使 R4 的 9 个调用点静态可判

## 去重对照

- scan-openapi-drift（契约↔后端路由轴）：F3 的后端侧、F4 的豁免登记与该卡交叉，本卡只给调用面证据
- scan-route-contracts（后端清单）：无重叠；scan-web-route-guards（页面守卫）：无重叠。本卡为前端调用面专卡

## 局限

- 三元方法（`method: cond ? "GET" : "POST"`）按方法未知处理，参数检查退化为方法并集（偏宽，不漏报）
- 请求/响应 **body 字段漂移不在口径内**（需类型级分析），如需可另开卡
- 插值常量跨文件再导出（re-export 链）只解析一层；函数参数基址不跨文件解析（R4 已列人工清单）
