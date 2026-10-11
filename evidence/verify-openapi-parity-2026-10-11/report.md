# contracts schema 与后端路由漂移复核（AGEN-1795）

- 日期：2026-10-11
- 基线：`origin/main` @ `6cf793bd8`（release: v1.6.14），专用 worktree `.wt-agen1795-openapi-parity`，分支 `verify/contracts-openapi-drift`
- 结论先行：**功能层面不过期**（端点与字段与后端完全一致，前端类型契约是新的）；**文本层面在 fastapi≥0.130.0 环境下会漂移**（11 个上传模型的 UploadFile 渲染差异，仅影响注释，不影响 TypeScript 类型）。`generated/api.ts` 相对已提交 schema 是最新的（可字节级复现）。

## 1. 方法

按 `web/contracts/README.md` 的双层流水线复跑并逐层对比，全程只读已提交产物：

1. 后端→schema：`python scripts/export_frontend_contracts.py`（`--check` 模式 + 输出到临时目录 `--output-dir`，不触碰仓库文件）。
2. schema→generated：`node web/scripts/generate-contracts.mjs --check`，并用相同 openapi-typescript 参数 + prettier 在临时目录复现生成内容做字节级 diff。
3. 端点级与字段级结构化对比：解析两份 openapi.json，比较 paths×methods 的 operationId/summary/tags/params/requestBody/responses，以及 components.schemas 的属性、required、enum 等结构。
4. 路由覆盖审计：核对 `deeptutor/api/routers/` 46 个模块与 `deeptutor/api/main.py` 的 import/include_router。

复核环境：主仓 venv（fastapi 0.141.1、pydantic 2.13.4、starlette 0.52.1、python-multipart 0.0.32）；依赖下限 `requirements/server.txt` 与 `pyproject.toml` 均为 `fastapi>=0.100.0`（未钉版本）。

## 2. 端点级 diff（committed schema vs 新导出）

- 双方各 **674** 个 HTTP 操作；新增 **0**、缺失 **0**、签名变更 **0**（operationId、summary、tags、参数、requestBody schema、响应码逐一相等）。
- 路由覆盖审计：46 个 router 模块中 45 个定义路由且全部在 `main.py` import 并 `include_router`（共 54 处挂载）；唯一未挂载的 `_partners_channel_schema.py` 是无路由的内部 schema 模块。**不存在"写了路由但没进契约"的缺失端点**。
- 说明：WebSocket 路由（`/ws/...`）不在 OpenAPI paths 范围内，属设计使然，前端走 `turn-protocol` 契约；`schema/turn-protocol.json` 与新导出**字节一致**。

## 3. 字段级 diff（components.schemas）

- 不变 schema **342** 个；新增 **0**、删除 **0**、变更 **11** 个。
- 11 处变更是**同一机械模式**：multipart 上传模型中的 `UploadFile` 字段，committed 为 `{"type":"string","format":"binary"}`，新导出为 `{"type":"string","contentMediaType":"application/octet-stream"}`（逐条清单见同目录 `drift` 证据与 `openapi-committed-vs-fresh.diff`，共 102 行 diff、24 个变更行）。
- 受影响的 11 个 body 模型对应 11 个上传端点：`/api/auth/profile/avatar`(PUT)、`/api/auth/users/import`、`/api/documents/import/docx`、`/api/file-preview/pdf`、`/api/knowledge-bases`、`/api/knowledge-bases/{kb_name}/upload`、`/api/question-notebook/practice/import/preview`、`/api/reading/materials`、`/api/visualizers/import`、`/api/voice/stt`、`/files/library/`（均 multipart/form-data）。
- 除此之外**没有任何字段增删、类型变更、required 变更或 enum 变更**。

## 4. 根因：FastAPI 版本渲染行为，而非后端路由变化

- FastAPI **0.130.0** 起，`UploadFile.__get_pydantic_json_schema__`（`fastapi/datastructures.py`）返回 `contentMediaType: application/octet-stream`，不再输出 `format: binary`（0.129.x 及更早无此覆盖，走旧渲染）。已按 tag 逐版本核对源码。
- 本机新导出（fastapi 0.141.1）即新渲染；已提交产物是旧渲染 → `export --check` 在依赖较新的环境必然报漂移（实测 exit 1，`Frontend contract drift: openapi.json`）。
- 历史翻烙饼证据：`da856ad67`（release: v1.6.9）与 `7885daa98`（2026-10-08，feat(plugins) #1307）两次提交都把 schema 里的 `contentMediaType` 行改回 `format: binary`——即不同贡献者本地 fastapi 版本跨 0.130.0 边界，各自再生成导致产物来回翻转。依赖下限 `>=0.100.0` 未钉版本是根因。

## 5. generated/api.ts 是否过期

- 相对**已提交 schema**：不过期。`generate-contracts.mjs --check` exit 0；且在临时目录以相同参数复现生成，与 `web/contracts/generated/api.ts` **字节一致**。
- 相对**新导出 schema**（即相对后端）：也只有注释级差异——重生成后的 api.ts 与现文件 diff 共 58 行，全部是 `Format: binary` JSDoc 注释块的收窄；**剔除注释/空行后两文件 diff 为空，TypeScript 类型层面零变化**（file/files 字段两种渲染都生成 `string`）。
- `generated/turn-protocol.ts`：对应 JSON 无漂移，同样最新。

## 6. 过期结论与 CI 缺口

**当前 schema 是否过期：**
- 按功能（端点、字段、前端类型）：**不过期**。后端 674 个端点与契约完全对齐，无任何路由/模型漂移。
- 按文本（当前依赖环境下重跑导出）：**会漂移**——11 个上传模型的 `UploadFile` 渲染会被改写，但只影响 schema 文本与 api.ts 注释，无类型/行为影响。

**CI 缺口（复核发现）**：`web/contracts/README.md` 称"CI 在后端契约测试中运行 `export_frontend_contracts.py --check`"，但 `tests/api/test_frontend_contract_export.py` 只断言临时目录的确定性，`.github/workflows/` 无任何工作流调用该脚本——**后端→schema 层没有 CI 门禁**（schema→generated 层有：web `npm run check` → `contracts:check`）。这正是 binary/contentMediaType 翻转能反复进 main 的原因。

## 7. 建议再生成时机

1. **无功能紧迫性**：现在不重生成也不影响任何前端类型或行为。
2. **推荐捆绑执行**，避免一次纯翻转提交：
   - 与下一次真实后端契约变更（新增/修改路由）同批 `export + generate`；或
   - 与 fastapi 版本钉死/升级（建议钉 `fastapi>=0.130.0` 或直接钉当前解析版本）同批执行，让新渲染成为唯一规范态，杜绝再翻转；或
   - 在给 CI 接入 `export_frontend_contracts.py --check` 门禁之前先重生成一次，否则门禁在新依赖环境会立即红。
3. 根治建议：钉住 fastapi 下限 + 在后端测试任务中补上 `python scripts/export_frontend_contracts.py --check`，使 README 声称的门禁真实存在。

## 8. 证据文件

- `openapi-committed-vs-fresh.diff` — schema 原始 unified diff（102 行）
- `api-regen-type-parity.txt` — 两层 check/复现/类型层比对全过程记录（含命令、数字、FastAPI 边界与历史翻转证据）
- `SHA256SUMS` — 本目录校验和

未改动任何源码或 `web/contracts/` 下产物；本分支仅新增本 evidence 目录。
