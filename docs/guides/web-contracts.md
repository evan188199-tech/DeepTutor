# web/contracts 契约生成与门禁链路导读

面向契约类修复/门禁卡的导读：后端 FastAPI app 到前端 TS 类型的双向管线、两道 `--check` 门禁各管什么、盲区在哪、前端哪里在手写解析 `detail.code`。基线：origin/main `f07029cfc`（release v1.6.13）。与漂移扫描报告（myfork 分支 `scan/openapi-drift-20261006` → `evidence/openapi-drift-20261006/report.md`，下称"漂移报告"）的衔接点集中在 §6。

## 1. 双向管线（文字版）

### 方向 A：后端 → schema（Python 拥有契约源）

```text
deeptutor/api/main.py:404   app = FastAPI(...)
        │  路由装配：main.py:575-605+ include_router（41 个 routers 文件）
        ▼
deeptutor/api/contracts/export.py:62   render_contracts()   ← 进程内导入 app，不起服务器
        │  :65  deepcopy(app.openapi())            实时渲染全部 REST 面
        │  :66  _assert_unique_operation_ids()     重复 operationId 直接抛错（:39-59）
        │  :68  把 5 个 turn 协议模型并进 components.schemas
        │  :70  写入 x-deeptutor-web-protocol-version: "2.0"
        ▼
export.py:79   write_contracts(output_dir, check=)
        │  :84  与磁盘现存文件逐字节比较；差异记入 changed
        │  :88-90  非 check 模式才写盘（check 模式只报告）
        ▼
web/contracts/schema/openapi.json        （REST 契约，62,433 行）
web/contracts/schema/turn-protocol.json  （WS 协议契约，来自 export.py:72 TurnProtocolDocument）
```

CLI 入口 `scripts/export_frontend_contracts.py:11` 只是把 `deeptutor.api.contracts.export.main`（export.py:94-106）挂上命令行；`--output-dir` 默认即仓库 `web/contracts/schema`（export.py:23-24），`--check` 时只比较不写，漂移则打印 `Frontend contract drift: <文件>` 并退出码 1（export.py:100-103）。

确定性来源：JSON 统一 `sort_keys + indent=2 + 末尾换行`（export.py:28-29），由 `tests/api/test_frontend_contract_export.py:13-28` 锁定。

### 方向 B：schema → TS 生成

```text
web/contracts/schema/*.json
        ▼
web/scripts/generate-contracts.mjs（在临时目录生成，不直接写盘）
        │  :15-27  openapi-typescript  schema/openapi.json → api.ts
        │           flags: --alphabetize --immutable --root-types
        │  :28-47  json-schema-to-typescript  turn-protocol.json → turn-protocol.ts
        │           flags: --unknownAny --unreachableDefinitions --style.printWidth=100
        │  :63-67  prettier 按 generated/ 下的目标路径格式化
        │  :70-75  与 contracts/generated/ 现存文件逐字节比较
        ▼
web/contracts/generated/api.ts            （40,751 行，REST 类型）
web/contracts/generated/turn-protocol.ts  （672 行，WS 类型，同批产出）
```

npm 入口：`web/package.json:17` `contracts:generate`（写盘）、`:18` `contracts:check`（`--check`，mjs:12 判定、:89 漂移退出 1）。生成失败或漂移时信息打到 stderr（mjs:78 `Generated contract is stale: ...`）。

### 方向 C：校验（两条独立 --check）

- 后端侧：`python scripts/export_frontend_contracts.py --check`——比较"实时 app ↔ 已提交 schema"。当前 CI 没有对真实仓库目录跑这一步（见 §4 盲区）。
- 前端侧：`npm run contracts:check`——比较"已提交 schema ↔ 已提交 generated TS"。CI 在跑（见 §4 门禁链）。

## 2. 关键文件表

| 文件 | 角色 | 关键行 |
|---|---|---|
| `deeptutor/api/main.py` | app 装配，契约最终源头 | :404 `app = FastAPI`；:575-605 `include_router` |
| `deeptutor/api/contracts/export.py` | schema 导出/比较的唯一实现 | :62 render；:79 write/check；:94 CLI main |
| `deeptutor/api/contracts/turn_protocol.py` | turn 协议模型（并入 openapi components） | :255 RuntimeStatus；:272 ErrorEnvelope；:279 TurnProtocolDocument |
| `scripts/export_frontend_contracts.py` | 后端 CLI 包装 | :11 挂接 `export.main` |
| `web/contracts/schema/openapi.json` | REST 契约（api.ts 的来源） | 禁止手改（web/contracts/README.md:3-4） |
| `web/contracts/schema/turn-protocol.json` | WS 协议契约 | 同上 |
| `web/scripts/generate-contracts.mjs` | schema→TS 生成与 --check | :15-47 两个生成器；:75 比较 |
| `web/contracts/generated/api.ts` | REST 类型产物 | 根类型：`paths` :5、`webhooks` :10527、`components` :10528、`$defs` :17138、`operations` :17139 |
| `web/contracts/generated/turn-protocol.ts` | WS 类型产物 | `ClientCommand` 11 命令联合 :8-19 |
| `web/contracts/parse/turn-event.ts` `turn-command.ts` | 手写守卫/窄化，消费生成类型 | turn-event.ts:1-9；turn-command.ts:1-11 |
| `tests/api/test_frontend_contract_export.py` | 后端契约测试 | :13-28 确定性；:47-56 operationId 唯一；:71-79 check 模式（仅 tmp_path） |
| `.github/workflows/tests.yml` | CI 前端门禁所在 | :85 `npm run check`（web-tests job） |
| `web/package.json` | npm scripts 链 | :17/:18 contracts 两脚本；:19 check:fast；:20 check |
| `web/contracts/README.md` | 刷新流程的唯一说明 | :8-11 两步命令；:13-14 对 CI 的描述（部分失真，见 §4） |

## 3. schema→api.ts 生成规则

- 两条独立生成器：REST 用 `openapi-typescript` ^7.13.0，WS 用 `json-schema-to-typescript` ^16.0.0（web/package.json:84-85）；一个 schema 变更可能只牵动其一。
- openapi-typescript 规则：`--alphabetize` 按字母序输出；`--immutable` 全量 `readonly`；`--root-types` 把 `paths` / `operations` / `components` / `webhooks` / `$defs` 提升为根导出（api.ts:5 / :17139 / :10528 / :10527 / :17138）。
- `operations` 类型以路由装饰器的 `operationId` 命名（api.ts:17139 起）；改名/删路由会直接改变 operations 键与 `paths` 结构，前端按名引用处全部受影响。重复 operationId 在导出侧即被拒绝（export.py:39-59），不落入生成物。
- components.schemas → `components`（api.ts:10528 起）；请求/响应体在 `paths` 与 `operations` 里以 `components["schemas"]["…"]` 引用呈现。
- json-schema-to-typescript 规则：`$defs` 内模型展开为命名类型；`ClientCommand` 是 11 个 WS 命令的联合（turn-protocol.ts:8-19），事件侧经 `web/contracts/parse/turn-event.ts:11-16` 的 `STREAM_EVENT_TYPES` 集合做窄化。
- prettier 按 target 文件路径格式化（mjs:63-67）；最终与仓库现存文件**逐字节比较**（mjs:75）——两侧门禁都是文本相等，没有语义比较。
- 前端消费现状：直接 import `contracts/generated/api` 的业务代码目前只有 `web/lib/usage-statistics.ts:1`（取 `components` 类型）；REST 调用大多是手写 fetcher（如 `web/lib/mcp-api.ts:1` 的 `apiFetch/apiUrl`，实际来自 `@/shared/api/client`，经 `web/lib/api.ts:5` 转出）。turn-protocol 侧集成较完整：parse/ 守卫 → `web/features/chat/transport/UnifiedTurnClient.ts`、`TurnRuntimeClient.ts`。

## 4. 门禁链与盲区

### 现有门禁链（schema→TS 层，有效）

```text
CI  .github/workflows/tests.yml:85   npm run check（web-tests job）
  └ web/package.json:20   check = check:fast + build + perf:check
      └ :19  check:fast 第一步 = contracts:check
          └ :18  node ./scripts/generate-contracts.mjs --check
              └ 输入仅已提交的 schema/*.json（mjs:10,:20,:40），与 generated/ 比较
```

### 盲区（app→schema 层，无门禁）

- `contracts:check` 的输入只有**已提交**的 `schema/openapi.json`；它从不触碰 FastAPI app。后端路由一变，schema 不重导出，这条链永远绿。
- 后端侧 `tests/api/test_frontend_contract_export.py` 全部对 `tmp_path` 或纯内存 render 操作：:71-79 的 check 模式测试验证的是"渲染器对临时目录幂等"，与仓库真实 `web/contracts/schema/` 无对比。
- `web/contracts/README.md:13-14` 宣称 "CI runs `python scripts/export_frontend_contracts.py --check`"，但 `.github/workflows/` 下 grep 无该命令——文档描述与 CI 现状不符。
- 结论：**实时 app ↔ 已提交 schema 之间没有任何 CI 比较**。漂移报告 §3 判定这是 D1-D4 漂移进入 main 的根因（#1673/#1711 在同步提交 `e91d9800e` 之后合入，release 提交未重跑导出）。
- 最小修法方向（漂移报告卡 A）：新增后端测试/CI 步骤执行 `write_contracts(真实 schema 目录, check=True)`，或直接在 backend job 跑 `python scripts/export_frontend_contracts.py --check`。脚本能力已齐备（export.py:79-103 + 默认输出目录 export.py:23-24），缺的只是入口。

## 5. `detail.code` 手写解析位点

背景：routers 以 `HTTPException(status_code=4xx, detail={"code": ..., "message": ...})` 发结构化拒绝；FastAPI 不为 HTTPException 生成 schema，因此该错误形状**不在生成契约里**（漂移报告 §2：发出点 14 处 / 8 个 routers 文件，受影响 REST 操作 44 个，契约覆盖 0/44）。代表性发射器：

- `deeptutor/api/routers/book.py:59-62`：`_book_paused_http`，409 + `{"code": "book_paused", ...}`（另有 :335、:344、:1794；:1794 在 WS 处理器内，不属 REST 轴）
- `deeptutor/api/routers/space_mcp.py:88-89`：`_refuse`，400 + `{"code": exc.code, ...}`（另有 :185、:201、:330、:337）

完整发出点清单见漂移报告 §2（space_cli_apps.py :103/:149、notebook.py :36、settings.py :586、video_learning.py :120）。

前端解析位点（本基线共 3 处，均为手写、不经过 generated/api.ts）：

| 位点 | 形态 | 说明 |
|---|---|---|
| `web/lib/mcp-api.ts:281`（契约注释）；解析块 :291-305 | `asJson()` 从错误体 `detail` 提取 `code`/`message` → `McpApiError.code`（类定义 :280-289） | MCP 空间拒绝码的统一消费入口；:1 依赖手写 `apiFetch` |
| `web/lib/codex-oauth.ts:163-164`（函数 :130 起，错误类 :53） | `payload.detail?.code` 提取，缺省回退 `http_<status>` → `CodexOAuthApiError` | Codex OAuth 错误码映射 |
| `web/lib/settings-readiness.ts:40`（`detail_code` 字段）；`fetchSettingsReadiness` :212-216 | 200 快照里的行级 `detail_code` 字段，整个 `SettingsReadinessSnapshot` 为手写 interface | 非错误信封，但同属"形状未进生成类型、前端手写对齐"；读取端 `web/components/settings/SettingsReadinessPanel.tsx:101/:182/:393` |

若后续做错误信封建模（漂移报告卡 C：共享 `{code, message}` 信封模型 + 为 44 个操作补 `responses`），上述 3 处是删除/收敛手写解析的目标位点。

## 6. 与漂移报告的衔接点

- 报告本体：myfork 分支 `scan/openapi-drift-20261006` → `evidence/openapi-drift-20261006/report.md`（§2 结构化错误覆盖、§3 门禁根因）及 `drift.json`、复现脚本 `scan_openapi_drift.py`。
- D1/D2（reading 位置字段）：后端 `deeptutor/api/routers/reading.py:324`（`PositionPayload.percentage` anyOf/null）、`:328`（`PositionInfo.percentage` 丢约束）晚于契约同步合入；契约侧 api.ts:14017 / :13997。修复走"再生成同步"（README.md:8-11 两步），注意 D1 会让 `PositionPayload["percentage"]` 类型变为 `number | null`——前端已先行适配（`web/components/reading/ReaderPane.tsx:237`），无需连带改。
- D3/D4（knowledge docstring）：`deeptutor/api/routers/knowledge.py:2776` / `:1377` vs api.ts:1718 / :2691，描述级，再生成即消。
- 官方检查命令在当前基线必然失败：`python scripts/export_frontend_contracts.py --check` → `Frontend contract drift: openapi.json`（export.py:102）。这是门禁卡落地后应转为"在 CI 内对真实目录运行"的那条命令。
- 责任划分：本导读覆盖契约生成/校验链；路由清单轴归 scan-route-contracts 卡，WS 存储三方对照归 scan-session-schema-drift 卡，Web 总体导读归 guide-frontend 卡。

## 7. 契约类卡片的公共操作约束

- `web/contracts/schema/` 与 `web/contracts/generated/` 禁止手改（README.md:3-4）；唯一合法刷新路径 = README.md:8-11：`python scripts/export_frontend_contracts.py && cd web && npm run contracts:generate`。
- openapi.json 与 api.ts 必须同批刷新、同一提交；单改一侧必然打红另一侧门禁。
- 改 `export.py` 渲染行为需同步 `tests/api/test_frontend_contract_export.py`（确定性断言 :13-28、operationId 断言 :47-56、秘密不外泄断言 :59-68）。
- WS 轴改模型（turn_protocol.py）后，`turn-protocol.json` 与 `turn-protocol.ts` 同批再生成；`contracts/parse/` 守卫（turn-event.ts / turn-command.ts）引用生成类型，事件/命令枚举变更会在此处编译报错，属预期保护。
- 漂移修复类卡片的验证闭环：`python scripts/export_frontend_contracts.py --check`（后端侧）+ `cd web && npm run contracts:check`（前端侧）两条都要绿，才是完整契约同步。
