# 前端生成契约与后端路由漂移清点（api.ts vs routers）

- 卡：AGEN-837 · 扫描日期：2026-10-06 · 基线：origin/main `f07029cfc`（release v1.6.13）
- 结论预览：**PASS**（只读扫描，未改任何代码、未重新生成契约）。路径/方法面完全同步（531 路径 / 643 操作，缺失 0、多余 0、方法不一致 0）；但仓库自带的 `export_frontend_contracts.py --check` 在 main 上**失败**（"Frontend contract drift: openapi.json"），实质漂移共 **4 条**（2 条字段/类型级、2 条仅描述级），源头是 #1673 与 #1711 在契约同步提交 `e91d9800e` 之后合入、release 提交 `f07029cfc` 未重跑同步。`{"code","message"}` 结构化错误在生成契约中的覆盖度为 **0/44（0%）**——实际发出点 14 处、分布在 8 个 routers 文件，远多于先前报告所称的 2 处先例。根因：**没有任何 CI 门禁比较"app 实时 schema ↔ 仓库内已提交 schema"**。
- 去重：后端路由清单本身归 scan-route-contracts，存储三方对照归 scan-session-schema-drift；本卡只做前后端契约轴。
- 环境：仓库 `.venv`（Python 3.13，pydantic 2.13.4 / fastapi 0.141.1）实时渲染结果与已提交 schema 除下列 4 条外**逐字节一致**，排除依赖版本差异假阳性。

## 0. 覆盖范围（验收 1）

| 项 | 数值 |
|---|---|
| 实时渲染（app.openapi() 经 `render_contracts()` 管道）| 531 paths / 643 HTTP 操作 |
| 生成契约 `web/contracts/schema/openapi.json`（api.ts 的来源）| 531 paths / 643 HTTP 操作 |
| 操作回溯到 routers 装饰器 | **643/643（0 未解析）**，41 个 routers 文件 + `main.py`（`/health/live`、`/health/ready` 两条 app 级路由）|
| 无 HTTP 操作的 routers 文件 | `question.py`、`quiz_judge.py`、`tools.py`（后两者实际为 WS/混合装载方式不同）、`unified_ws.py`（纯 WS）|

方法可复现：`python evidence/openapi-drift-20261006/scan_openapi_drift.py --repo-root <repo> --out-dir evidence/openapi-drift-20261006`（进程内导入 app，不启动服务器；两次运行输出逐字节一致）。

## 1. 漂移条目（每条附两侧 path:line，验收 2）

| # | 级别 | 后端（现行 main） | 契约（web/contracts，api.ts 同源）| 差异 |
|---|---|---|---|---|
| D1 | 字段级 | `deeptutor/api/routers/reading.py:324`（`PositionPayload.percentage: float \| None = Field(default=None, ge=0.0, le=1.0)`，改自 #1673 `8ccca47ba`）；使用点 `reading.py:1410`（`PUT /api/reading/materials/{material_id}/position` 请求体）| `web/contracts/schema/openapi.json` components.PositionPayload；api.ts:14017（schema 定义）、api.ts:31888（请求体引用）、api.ts:6624（操作声明行）| 契约为 `number`（default 0.0，min 0 max 1）；实际为 **number \| null（anyOf），无 default**。TS 层类型从 `number` 变为 `number \| null`——前端代码已先行手写适配（`web/components/reading/ReaderPane.tsx:237` 自标 `percentage: number \| null`），生成契约滞后 |
| D2 | 约束级 | `deeptutor/api/routers/reading.py:328`（`PositionInfo.percentage: float = 0.0`，#1673 丢失 ge/le）；影响 `reading.py:1399`（GET position 响应）与 `reading.py:1410`（PUT）| api.ts:13997（PositionInfo schema）、api.ts:31859（GET 响应引用）、api.ts:6619/6624 | 契约 `number` min 0 max 1；实际 `number` **无 min/max**。TS 类型不变（仍 `number`），属校验语义漂移：后端不再保证 0–1 区间 |
| D3 | 描述级 | `deeptutor/api/routers/knowledge.py:2776`（`GET /api/knowledge-bases` docstring，#1711 `4d7b080fb`）| api.ts:1718 | 契约 "List all available knowledge bases with their details." vs 实际 "Disk probes must not block the async worker or its other requests (#1711)."。无行为影响 |
| D4 | 描述级 | `deeptutor/api/routers/knowledge.py:1377`（`GET /api/knowledge-bases/health` docstring，#1711）| api.ts:2691 | "Health check endpoint" vs "Count registered KBs without constructing/probing the catalog (#1711)."。无行为影响 |

补充事实：
- `web/contracts/generated/api.ts`（40,751 行）与 `web/contracts/schema/openapi.json` 同步于 `e91d9800e`（2026-10-04，"chore(contracts): sync browser APIs after PR integration"），两者内部一致；漂移发生在同步之后的同日合入。
- `turn-protocol.json` **无漂移**（`--check` 仅报告 openapi.json）。
- 方法级/path 级：0 缺失、0 多余、0 方法不一致——契约路由面完整。

## 2. `{"code","message"}` 结构化错误在生成契约中的覆盖度

| 统计 | 数值 |
|---|---|
| 发出点（routers 源码行，`detail={...code...message...}` 字典）| **14 处**，8 个文件：book.py×4（:61、:335、:344、:1794）、space_mcp.py×5（:89、:185、:201、:330、:337）、space_cli_apps.py×2（:103、:149）、notebook.py×1（:36）、settings.py×1（:586）、video_learning.py×1（:120）。先前错误报告所称"仅 book.py:61、space_mcp.py:89 两处先例"**显著低估** |
| 受影响 REST 操作（去重）| **44 个**（book 内容变更类 15、notebook 12、codex oauth/settings 7、book_paused 6、space mcp/cli 6、video notes 5，有交集；归属明细见 drift.json `structured_errors.rows`）|
| 契约中记载该错误形状的操作 | **0/44（0%）**。实时 schema 与生成契约中这 44 个操作的 responses 均只有 `200` + `422`（FastAPI 不为 HTTPException 生成文档）|
| 前端现状 | 手工解析 `detail.code` 绕过契约：`web/lib/mcp-api.ts:281`（注释明言 "Backend refusal code (`detail.code`)"）、`web/lib/codex-oauth.ts:163`、`web/lib/settings-readiness.ts:40` |
| 例外 | `book.py:1794` 在 WS 处理器内发 `{code,message}`，不属 REST 契约轴（归 turn-protocol 管）|

## 3. 根因：契约门禁存在盲区

- CI `tests.yml:85` 跑 `npm run check` → `contracts:check` → `web/scripts/generate-contracts.mjs --check`，但它**只从已提交的 `schema/openapi.json` 重生成 TS 比对**，管的是 schema→TS 层，永远发现不了 app→schema 层的漂移。
- 后端测试 `tests/api/test_frontend_contract_export.py:74` 的 check 模式测试仅对 **tmp_path** 验证渲染器幂等，未与仓库内已提交的 `web/contracts/schema/` 比对。
- 因此 app→schema 层**无任何门禁**，#1673/#1711 漂移直达 main。`--check` 脚本本身（`scripts/export_frontend_contracts.py --check`）具备检测能力（默认输出目录即仓库 schema 目录），只是没有入口在 CI 里对真实仓库目录运行。

## 4. 可拆卡建议

1. **卡 A（门禁，最小改动、优先）**：新增后端测试/CI 步骤，对仓库真实目录执行 `write_contracts(REPO/web/contracts/schema, check=True)`（或直接在 backend CI job 跑 `python scripts/export_frontend_contracts.py --check`）。落地后本卡 4 条漂移及未来同类漂移全部被 CI 拦截。
2. **卡 B（再生成同步）**：按 `web/contracts/README.md` 流程 `python scripts/export_frontend_contracts.py && cd web && npm run contracts:generate`，消除 D1–D4；注意 D1 会让 api.ts 的 `PositionPayload["percentage"]` 类型变化，前端无需改动（已按 null 适配）。
3. **卡 C（结构化错误建模）**：定义共享错误信封模型（`{code, message, ...}` 包在 `detail` 下），为 44 个操作（按文件分批：book.py 15、notebook.py 12、settings.py 7、space_mcp/space_cli_apps 6、video_learning.py 5）补 `responses={4xx: {"model": ...}}`，使生成契约如实记载错误形状，前端可删手写 `detail.code` 解析。
4. **卡 D（复查 #1673 意图，可与 B 合并）**：确认 `PositionInfo.percentage` 丢失 ge/le 是 #1673 有意为之还是顺手丢失；若无意，恢复约束再走卡 B。

## 5. 复现与产物

```bash
# 官方漂移检查（本基线必然失败，输出 "Frontend contract drift: openapi.json"）
python scripts/export_frontend_contracts.py --check

# 本卡扫描（只读；两次运行逐字节一致）
python evidence/openapi-drift-20261006/scan_openapi_drift.py \
  --repo-root <repo> --out-dir evidence/openapi-drift-20261006
```

- `drift.json`：机器可读全量结果（path/method 面差异、response/request 字段差异、schema 级 canonical diff、44 操作归属明细、覆盖率）。
- `scan_openapi_drift.py`：复现脚本（进程内 `render_contracts()`，不写任何契约文件）。
- `SHA256SUMS`：本目录全部文件校验和。
