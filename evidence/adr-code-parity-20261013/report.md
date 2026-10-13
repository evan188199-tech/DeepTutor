# ADR 决策与当前实现偏差核查（origin/main @ 6cf793bd8, release v1.6.14）

- 日期：2026-10-13
- 核查基线：`origin/main` = `6cf793bd8`（release: v1.6.14），只读新 worktree，未改任何代码。
- ADR 来源：**`docs/adr/` 在当前 main 已不存在**。四篇 ADR 最后存在于 `da856ad67`（"release: v1.6.9"）的父提交 `da856ad67~1`，本核查以该版本内容为决策文本（见「G0」）。
- 方法：逐条提取 ADR 关键断言 → 在当前代码中定位实现/反例（path:line）→ 必要时运行只读校验命令取证。未运行任何服务器/守护进程；唯一执行的命令是 `python scripts/export_frontend_contracts.py --check`（check 模式只读）与一次内存中的 render 对比。

## 结论总览

| 编号 | ADR | 结论 |
| --- | --- | --- |
| G0 | 输入前提 | **偏差**：docs/adr 目录已从 main 删除 |
| ADR-0001 | backend-owned browser contracts | 6 条断言中 5 条符合；**D1 偏差**：CI 契约漂移门禁半缺失 |
| ADR-0002 | unversioned canonical URLs | 符合项多数；**D2/D3/D4 偏差**：页面重定向、settings 别名、query 传 session 身份 |
| ADR-0003 | idempotent turn commands | **符合**（1 条观察 O1） |
| ADR-0004 | invidious account boundaries | **符合** |

## G0 — 输入前提偏差：docs/adr 已被删除

- 现状：`git ls-tree -r origin/main` 无 `docs/adr/`；删除发生在 `da856ad67`（release: v1.6.9），一次删除 4 个文件：`0001-backend-owned-browser-contracts.md`、`0002-unversioned-canonical-urls.md`、`0003-idempotent-turn-commands.md`、`0004-invidious-account-boundaries.md`。
- 影响：决策文本脱离仓库，后续贡献者无从对照（本报告引用的行号均指向当前代码，决策语义以 `da856ad67~1:docs/adr/*.md` 为准）。
- 建议：恢复 ADR 目录，或补一页「ADR 已归档/由何取代」的显式记录；两者都比静默删除好。

## ADR-0001 Backend-Owned Browser Contracts

符合的断言：

1. 适配器中立的请求值对象在 `deeptutor.core`：`deeptutor/core/turn_request.py:113`（全仓库唯一 `class TurnRequest`，`deeptutor_web/` 仅空包）。
2. `deeptutor.app.contracts` 仅 re-export：`deeptutor/app/contracts.py:3-25`。
3. wire-only WebSocket 模型在 `deeptutor.api.contracts`：`deeptutor/api/contracts/turn_protocol.py:69-224`。
4. 契约由 FastAPI app + canonical 模型渲染：`deeptutor/api/contracts/export.py:62-76`（`app.openapi()` + `TurnRequest`/`RuntimeStatus`/`SessionSummary`/`SessionDetail`/`ErrorEnvelope` 合入 components）。
5. 重复 operationId 视为缺陷、导出器必须报错而非静默改名：`deeptutor/api/contracts/export.py:39-59`（`_assert_unique_operation_ids` raise）。

### D1 — 偏差：「CI fails if generated JSON or TypeScript differs from canonical Python」只落地了一半

- 现状链路：
  - TS ↔ 已提交 schema JSON：CI 有检查。`.github/workflows/tests.yml:85` 运行 `npm run check` → `web/package.json` `check:fast` → `contracts:check`；`web/scripts/generate-contracts.mjs:63-89` 只用**已提交的** `web/contracts/schema/*.json` 重新生成 TS 并比对 `web/contracts/generated/*.ts`。
  - Python ↔ 已提交 schema JSON：CI 无任何环节重渲染。`pytest` 步骤（`.github/workflows/tests.yml:286`）只跑到 `tests/api/test_frontend_contract_export.py`，该文件全部使用 `tmp_path`（`tests/api/test_frontend_contract_export.py:18,72,76`），从不针对 `DEFAULT_OUTPUT_DIR`（`web/contracts/schema/`）做漂移断言；`.pre-commit-config.yaml` 亦无相关 hook。
- 文档失实：`web/contracts/README.md:13` 声称 "CI runs `python scripts/export_frontend_contracts.py --check` in backend contract tests" —— 当前 CI 与测试都没有这一步。
- 实证（本次在基线提交上运行）：
  - `python scripts/export_frontend_contracts.py --check` 退出码 1，输出 `Frontend contract drift: openapi.json`。
  - 差异定位：`web/contracts/schema/openapi.json` 中 11 处上传字段的 `format: binary` 与当前依赖渲染出的 `contentMediaType: application/octet-stream` 不一致（涉及 `Body_upload_files_*`、`Body_import_docx_*`、`Body_speech_to_text_*` 等 11 个 schema，逐键 diff 无其他差异）。即：当前已提交产物随依赖版本升级已静默过期，而现有 CI 仍会全绿。
- 建议：
  1. 在 CI 增加一步 `python scripts/export_frontend_contracts.py --check`（或加一个针对 `DEFAULT_OUTPUT_DIR` 的 pytest 断言），与 README 的声明对齐；
  2. 用当前依赖重新生成 `web/contracts/schema/openapi.json` 并提交；
  3. 考虑在生成器中固定/归一化 `format: binary` 的渲染（避免随 pydantic/fastapi 版本漂移）。

## ADR-0002 Unversioned Canonical URLs Without Compatibility Aliases

符合的断言：

1. REST 命名空间为 `/api/...`、URL 不带产品/契约版本：仓库自身路由无 `/api/v1`；grep 命中的 `api/v1` 全部是**外部服务**地址（`deeptutor/partners/channels/discord.py:21`、`deeptutor/video_learning/routers`→上游 Invidious `deeptutor/api/routers/video_learning.py:466`、`deeptutor/services/skill/hub.py:70-71`、`deeptutor/services/config/provider_runtime.py:344-488` 等），不属本决策管辖。
2. 主 turn WebSocket 为 `/ws`：`deeptutor/api/routers/unified_ws.py:43` + `deeptutor/api/main.py:793`（router 无前缀挂载）。
3. 可下载产物走 `/files/...`：`deeptutor/api/main.py:578,581,625,778`（`/files/outputs`、`/files/workspace-items`、`/files/library`、`/files/attachments`）；遗留 `/api/outputs` 无命中。
4. canonical 页面路由用产品名词：`web/app/(workspace)/chat/[sessionId]` 存在；settings 有独立 section 页 `web/app/(settings)/settings/[section]/page.tsx`。
5. 契约版本在 OpenAPI `info.version`：`deeptutor/api/main.py:406`；WS 兼容性走必需的 `protocol_version` 信封（见 ADR-0003）；持久化数据自带 `schema_version`（如 `deeptutor/services/app_update.py`、`deeptutor/services/github_copilot_storage.py`）。

### D2 — 偏差：页面重定向（含 301 permanent）被保留为「兼容层」

- `web/next.config.js:144-161`：注释明言 "Compatibility lives here; every rendered link uses learning-routes.ts."：
  - `{ source: "/", destination: "/chat", permanent: false }`
  - `/mastery/:pathId/study(*/:sessionId)` → `/learning/mastery/...`，`statusCode: 301`
  - `/books|/mastery|/reading|/watching/:path*` → `/learning/...`，`statusCode: 301`
- ADR 决策原文：页面重定向 "are removed in the breaking release rather than retained indefinitely"。这些 redirect（尤其 301 永久缓存）正是被决定移除的对象。
- 建议：要么迁移窗口已过则删除 redirect 表，要么修订 ADR 记录「learning 面改名保留 301」为已被接受的例外。

### D3 — 偏差：settings 旧键名别名与「升级前书签」解析器被保留

- `web/features/settings/navigation/settings-nav.ts:564-577`：`SETTINGS_ALIASES`（11 个旧键 → 新页），注释 "Stable aliases keep existing bookmarks and links from older clients working."。
- `web/features/settings/navigation/settings-pages.ts:158-176`：`legacySettingsDestination(hash, search)` 把旧 fragment/查询迁移到 `/settings/{key}`。
- `web/app/(settings)/settings/page.tsx:8-27`：入口页在客户端解析 pre-upgrade 书签并 `router.replace`。
- 与 ADR「移除页面重定向/别名，不无限保留」直接冲突；且这些别名被标注为 "Stable"（无限期）。
- 建议：与 D2 同类 —— 明确决策：删除并断网旧链接，或修订 ADR 承认永久别名。

### D4 — 偏差（按字面）：query 参数承载 session 身份

ADR 原文："Query parameters may still express one-shot launch intent ... but never session identity."。当前仍存在以 query 传 session 标识的 REST 端点：

- `deeptutor/api/routers/mastery_path.py:779`：`GET /api/mastery-paths/topics/{path_id}/ask-hint` 的 `session_id: str = ""`（query）；前端发送方 `web/lib/learning-api.ts:647`。
- `deeptutor/api/routers/question_notebook.py:408`：`GET /entries/lookup/by-question` 的 `session_id: str = Query(default="")`。
- `deeptutor/api/routers/partner_groups.py:132,194`：`GET /{group_id}/history(…)` 的 `session_key: str = Query("default")`（会话线程键，borderline）。

定性：这些是 GET 资源选择器而非「session 路由 fallback」，是否属于 ADR 意图内需要裁量；但按字面「never session identity」构成偏差。建议：修订 ADR 增加「GET 子资源选择器例外」条款，或将标识移入 path/body。

中性观察（不计偏差）：

- `deeptutor/api/routers/plugins.py:177-181`：plugin 页非斜杠 → 斜杠的 307，是同一现行资源的斜杠归一，非旧路径别名。
- `deeptutor/api/main.py:478-484` 与 `deeptutor/api/routers/video_learning.py:162-174`：OAuth 回调的功能性 303（一次性状态旗标，如 `?account=authorization_login_required`），不承载 session 身份。

## ADR-0003 Explicit Acknowledgement for Idempotent Turn Commands —— 符合

1. 三个可重试变更均带 client 生成的稳定 `command_id`：`deeptutor/api/contracts/turn_protocol.py:108-112`（cancel_turn）、`:127-133`（submit_user_reply）、`:142-147`（user_input）；浏览器侧 `web/features/chat/transport/TurnRuntimeClient.ts:62-86`（`ACKNOWLEDGED_COMMAND_TYPES` 恰为这三个，缺省时 mint UUID）。
2. 服务器发非流内 `command_ack`（id、command kind、accepted、稳定 error_code）：`turn_protocol.py:203-211`；发送点 `deeptutor/api/routers/unified_ws.py:111-123, 288-336, 354-370`。
3. 浏览器仅在匹配 ack 后移除排队命令：`TurnRuntimeClient.ts:317-333`（按 `command_id` 匹配方清除）；流 seq 从不清除需 ack 的命令（`:390-394` 的 filter 保留 `requiresAck` 项）。
4. seq 只确认流持久化：`unified_ws.py` 订阅转发（`:142-171`）与 ack 路径完全分离。
5. 所有 WS 命令与服务器帧要求 `protocol_version: "2.0"`：模型层 `turn_protocol.py:71,78,85,92,99,112,119,133,147,153,158`（每个命令 `Literal["2.0"]`）；服务端对所有入帧统一校验 `unified_ws.py:194-199`；出帧统一补 `protocol_version`（`unified_ws.py:70`）。

### O1 — 观察（不判偏差）：交互式应答的 ack 超时会移除排队命令

- `TurnRuntimeClient.ts:227-235`：`sendAwaitingAck` 路径 30s 未收到 ack 时把命令移出队列并 reject（注释引用 #1648 的产品决策：不得替学习者超时后补发答案）。严格字面「removes a queued mutation only after its matching acknowledgement」被软化；durable `enqueue` 路径（`:242-252`）仍保留至 ack。
- 建议：在 ADR-0003 增补一段「交互式应答 30s ack 超时=投递失败上抛」的已接受语义，避免后续按字面「修复」。

## ADR-0004 Separate Invidious Account Workflow, Storage, and Transport —— 符合

1. 三模块分层与内向依赖：facade `deeptutor/video_learning/invidious_account.py:19-20` 仅引 `_client`/`_storage`；storage 只依赖标准库与 `deeptutor.multi_user.paths`（`invidious_account_storage.py:8-20`），不 import HTTP/工作流；client 拥有全部上游 HTTP 与 bearer 序列化（`invidious_account_client.py:17-26,67-68`）。
2. facade 不触网、不直接写文件（`invidious_account.py` 全文无 `httpx`/文件写调用，`.get(` 命中均为 dict/env 读取）。
3. 外部调用方只经 facade：`deeptutor/api/routers/video_learning.py:152-207`；直接 import storage/client 的只有传输层测试 `tests/video_learning/test_invidious_account.py:18-19`（与 ADR「transport tests patch the transport module directly」一致）。
4. 存储不变量全部在位：state 先 SHA-256、绝不作为路径段（`invidious_account_storage.py:53-59`）；记录 0600、目录 0700、O_EXCL 临时文件 + `os.replace` + fsync 原子发布（`:33-40,69-85`）；跨 worker/重启的一次性领取用同文件系统 rename claim（`consume_pending_flow:134-152`）。

## 附：核查命令

- `git fetch --multiple origin myfork`；worktree 基于 `origin/main`（6cf793bd8）。
- `python scripts/export_frontend_contracts.py --check`（基线提交，退出码 1，见 D1）。
- 内存中 render vs committed 的逐键 diff（结果见 D1；无其他差异）。
- 只读 grep/ls；未运行测试套件、未启动任何服务、未修改任何源代码。
