# scan: web 内存缓存层清点（client-cache 及使用点）

- 卡片: AGEN-1273
- 日期: 2026-10-09
- 基线: `origin/main` @ `6cf793bd868ba5ecbe64722936d4be8fab5a01df`（release: v1.6.14）
- 范围: `web/lib/client-cache.ts`（内存缓存层）及其全部使用点。只读清点，未改任何产品/测试代码。
- 去重说明: localStorage 持久化轴归 `scan-web-storage-schema`，本卡仅覆盖内存缓存层。
- 配套明细: `inventory.json`（20 个读点 + 24 个失效点 + 30 个 knowledge 变更级联点，全部带 file:line，可用下文命令复算）。

## 1. 机制摘要（web/lib/client-cache.ts，共 69 行）

- 存储: 模块级 `Map<string, CacheEntry>`（:9）。条目二态：在途 `promise` 或已落值 `data + expiresAt`。
- 键规约: `<module>:<resource>[:<params>]`，读取前无条件追加 `:workspace=<activeWorkspaceId()>`（:28）。`activeWorkspaceId()` 取当前 URL 的 `dt_workspace ?? workspace`（web/lib/workspace-scope.ts:2-6），与 `scopedUrl` 往请求 URL 注入的 `dt_workspace` 同源，键与请求的工作区一致。
- TTL: 默认 30s（:21），惰性过期——只在读取时判断（:31），过期条目不主动清除。
- 在途合并: 命中在途 promise 直接复用（:34-36）；`force=true` 绕过命中但仍以新 promise 覆写条目（:39-58）。
- 防脏写回: promise 结算时校验 `clientCache.get(key)?.promise === promise`（:42, :51），被失效/被取代的在途请求不会把旧数据写回——有回归测试 `web/tests/workspace-navigation.spec.tsx:58-65`。
- SSR 旁路: `typeof window === "undefined"` 时直接调 loader（:23-25）。
- 失效语义: `invalidateClientCache(prefix)` 按 `startsWith` 前缀删除（:63-68）；Map 迭代中删除是 JS 规范允许的，无问题。

## 2. 键空间与 TTL 总表

| 前缀/键 | 读点 | TTL | 写侧失效 |
| --- | --- | --- | --- |
| `capabilities:catalog` | capabilities/api.ts:12 | 300s | 无（仅 TTL/force） |
| `knowledge:*`（list/providers/upload-policy/pageindex/ima/llamaindex/graphrag/files） | knowledge/api/client.ts 8 处 | 15s（config/files）/ 30s（list 等） | `invalidateKnowledgeCaches()`（client.ts:369-370），30 个变更点级联；KbDocumentList.tsx:134 定向 `files:` |
| `courses:list / state:<id> / candidates` | courses-api.ts:175/277/298 | 15s / 10s / 30s | 7 个写函数各删 `courses:`（:205,231,240,257,270,325,343） |
| `sessions:<limit>:<offset>:<scope>[:workspace:<id>]` | session-api.ts:210 | 15s | 标题/回复语言/组织/删除（:350,368,410,420） |
| `imported-sessions:<limit>:<offset>` | imports-api.ts:87 | 15s | 导入成功（:44） |
| `llm-options:list` | llm-options.ts:49 | 30s | SettingsStore 4 处 + CodexOAuthCard.tsx:141 |
| `personas:list` | personas-api.ts:53 | 30s | 增删改（:94,111,123 → :127） |
| `skills:list:<skill_workspace>` / `skills:tags` | skills-api.ts:68/298 | 30s | 7 个写函数（:141,255,276,292,318,335,347 → :351） |
| `subagents:settings` | subagents-api.ts:206 | 30s | 更新设置（:228） |
| `workspaces:list` | workspaces-api.ts:56 | 15s | save/migrate/move（:78,131,191，均同时删 `knowledge:`） |

跨模块同键覆写: 十个模块前缀两两不重叠，未发现同键覆写风险。唯一的跨模块删除是 workspace 变更时连带清 `knowledge:`（workspaces-api.ts:79/132/192），属有意设计（KB 作用域依赖 workspace 注册）。

## 3. 发现（按风险分级）

### F1 [中] `capabilities:catalog` 无任何写侧失效（capabilities/api.ts:12，TTL 300s）
全 `web/` 无一处对 capabilities 前缀调用 `invalidateClientCache`；唯一消费者 `useCapabilityCatalog.ts:32` 从不传 `force`。后端能力/工具注册表变化（设置开关、MCP 变更、重启）后，目录最长陈旧 5 分钟，且用户无刷新入口（非 force 调用方会一直命中）。无正确性错误，但陈旧窗口在所有键中最长。

### F2 [中] knowledge 列表键与 URL 的一致性依赖双重间接（client.ts:291 + client.ts:6-13）
`knowledge:list:<library|workspace>` 的键由 `options?.library || inKnowledgeLibrary()` 推导，而请求 URL 的 `resource_library=true` 由两处独立注入：显式三元（:292-295）与本地 `apiUrl` 包装器按当前路由补参（:6-13）。四种组合（路由×选项）当前推演全部一致，无实际脏读；但正确性靠包装器副作用兜底——任何绕过该包装器的重构（如直用 `baseApiUrl`）都会让同一键 `knowledge:list:library` 装进两种不同 URL 的响应，形成跨调用脏读。skills 模块同构（skills-api.ts:5-11 的 `skill_workspace` 注入），同一风险面。

### F3 [低] 失效粒度不对称：过宽与冗余
- `knowledge:` 级联过宽：任一配置 PUT（pageindex/ima/llamaindex/graphrag/retrieval-mode 等全部 30 个变更点）连带清掉所有 KB 文件列表与全部引擎配置，均为有意但代价偏大的全清。
- KbDocumentList.tsx:134 的 `knowledge:files:<kbName>` 前缀会连带命中同名前缀的其他 KB（如 `kb1` 波及 `kb1-backup`），方向是过失效（安全），且与 `listKnowledgeBaseFiles(name, {force})` 的 force 语义重复。

### F4 [低] TTL 窗口内的跨域陈旧（无级联失效）
- 导入会话后仅清 `imported-sessions:`（imports-api.ts:44），不清 `sessions:`——新导入的会话要等 listSessions 的 15s TTL 自然过期才出现在列表。
- 会话组织变更只清 `sessions:`（session-api.ts:410），不清 `courses:state:*`——课程页聚合数据靠 10s TTL 兜底。
均为有界陈旧（≤15s），非正确性缺陷。

### F5 [低] loader 契约:解析为 `undefined` 的值永不缓存
`data !== undefined` 作为命中判据（client-cache.ts:31），且结算后条目不再携带 promise（:43-46 整体覆写），若某 loader 合法返回 `undefined`，该键每次调用都会重新请求。当前 20 个 loader 全部返回数组/对象，属潜在契约约束而非现存缺陷。

### F6 [低] 内存无上限（惰性过期）
条目只在前缀删除或同键覆写时移除；按 (limit, offset, workspace, courseId, kbName) 组合的长会话 SPA 页签会缓慢累积。无 LRU/容量上限。

### 备注（非缺陷，供后续维护）
- 键的双重工作区分段：listSessions 显式带 `:workspace:<id>` 段（session-api.ts:222）又叠加自动后缀（client-cache.ts:28），冗余但一致。
- 防脏写回（:42/:51）与回归测试（workspace-navigation.spec.tsx:58-65）是本层最关键的正确性保障，改动时须保持。
- 键内嵌原始参数（kbName/courseId）未编码，读取为精确匹配、失效为 startsWith，只会过失效不会欠失效。

## 4. 复算命令

```bash
rg -n "withClientCache" web -g '!node_modules'     # 读点（含 import 行）
rg -n "invalidateClientCache\(" web -g '!node_modules'
rg -n "invalidateKnowledgeCaches\(\)" web/features/knowledge/api/client.ts   # 30 个级联点
```

产物: `report.md`、`inventory.json`、`SHA256SUMS`（对前两者）。
