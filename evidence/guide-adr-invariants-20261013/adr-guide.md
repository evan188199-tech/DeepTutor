# ADR 导读：决策不变量与实现锚点

- 日期：2026-10-13
- 代码基线：`origin/main` = `6cf793bd8`（release: v1.6.14）。只读新 worktree + 新分支，产品代码零改动。
- 决策文本：`docs/adr/*.md`。注意：该目录已随 `da856ad67`（release: v1.6.9）从上游 main 删除；现以 fork 主线 `myfork/main:docs/adr/` 为准，内容与删除前版本（`da856ad67~1`）完全一致（已逐文件 diff 确认）。
- 核对方式：下表所有 `path:line` 均在基线提交的工作区中逐条 grep/read 核实。
- 姊妹证据：`evidence/adr-code-parity-20261013/`（AGEN-1966，决策 vs 现状偏差核查；本文的「现存偏差」条目均指向该报告）。

## 快速导读

| ADR | 一句话约束 | 核心实现模块 |
| --- | --- | --- |
| 0001 backend-owned browser contracts | 跨进程契约只有一个 owner：后端 Python 模型；浏览器只消费生成产物 | `deeptutor/core`、`deeptutor/app/contracts.py`、`deeptutor/api/contracts/`、`web/contracts/` |
| 0002 unversioned canonical URLs | 路由是产品名词 + 无版本段的 `/api`、`/ws`、`/files`；版本信息住 `info.version`/`protocol_version`/`schema_version` | `deeptutor/api/main.py`、`web/app/`、`web/next.config.js` |
| 0003 idempotent turn commands | 可重试命令带稳定 `command_id`，只有显式 `command_ack` 才算送达 | `deeptutor/api/contracts/turn_protocol.py`、`deeptutor/api/routers/unified_ws.py`、`web/features/chat/transport/TurnRuntimeClient.ts` |
| 0004 invidious account boundaries | 工作流 facade / 私有存储 / 上游 HTTP 三层内向依赖，权限与一次性领取不变量归 storage 所有 | `deeptutor/video_learning/invidious_account*.py` |

## ADR-0001 Backend-Owned Browser Contracts

约束什么：适配层中立的请求值对象定义在 `deeptutor.core`（唯一 owner）；`deeptutor.app.contracts` 只准 re-export；wire-only WebSocket 模型放 `deeptutor.api.contracts`；OpenAPI/WS JSON Schema 必须由运行中的 FastAPI app + canonical 模型渲染生成；重复 operationId 是路由缺陷，导出器必须报错不得静默改名；生成的 JSON/TS 与 canonical Python 漂移时 CI 必须失败。

| # | 不变量 | 实现锚点（@6cf793bd8） | 改哪些代码会破坏 |
| --- | --- | --- | --- |
| A1-1 | 请求值对象唯一 owner 在 `deeptutor.core`（全后端唯一 `class TurnRequest`） | `deeptutor/core/turn_request.py:113` | 把 TurnRequest 搬进 `deeptutor.app`/`deeptutor.api`，或在适配层（如 `deeptutor_web/`）重新定义请求模型 |
| A1-2 | `app.contracts` 仅 re-export，不含新定义 | `deeptutor/app/contracts.py:3`（import 块）、`deeptutor/app/contracts.py:15`（`__all__`） | 在该文件里新增模型/字段定义而非 re-export |
| A1-3 | wire-only WS 模型归 `deeptutor.api.contracts` | `deeptutor/api/contracts/turn_protocol.py:65`（`WireModel`）及各命令/事件模型 | 把 wire 模型并入 core 值对象，或让 core 依赖 wire 层 |
| A1-4 | 产物由运行中 app + canonical 模型渲染（含 canonical 模型并入 components） | `deeptutor/api/contracts/export.py:62-76`（`render_contracts`；`:70` 写入 `x-deeptutor-web-protocol-version`） | 手改 `web/contracts/schema/*.json` 或绕过 `render_contracts` 生成产物 |
| A1-5 | 重复 operationId → 导出器 raise，不静默改名 | `deeptutor/api/contracts/export.py:39`、`:59`（raise） | 删除/绕过 `_assert_unique_operation_ids`；或静默改名重号（掩盖路由缺陷） |
| A1-6 | CLI 入口支持 `--check` 对已提交产物做漂移比对 | `scripts/export_frontend_contracts.py:11-14`；`deeptutor/api/contracts/export.py:94-102` | 移除 check 语义或让 check 恒真 |
| A1-7 | TS 侧漂移门禁：CI `npm run check` → 用已提交 schema JSON 重生成 TS 与 `generated/*.ts` 比对 | `.github/workflows/tests.yml:85`；`web/package.json:18-19`；`web/scripts/generate-contracts.mjs:73-89` | 手改 `web/contracts/generated/api.ts`；从 CI 摘掉 contracts:check |
| A1-8 | 已提交产物（浏览器消费的唯一契约面） | `web/contracts/schema/openapi.json`、`web/contracts/generated/api.ts` | 绕过生成器直接编辑产物 |
| A1-9 | 【已知缺口】Python↔已提交 schema JSON 的 CI 重渲染缺失；`web/contracts/README.md:13` 声称的后端 `--check` 测试实际不存在（pytest 步骤 `.github/workflows/tests.yml:286` 无此断言） | 参见 AGEN-1966 报告 D1 | 在 CI 补 `export_frontend_contracts.py --check` 之前，产物可能随依赖升级静默过期 |

## ADR-0002 Unversioned Canonical URLs Without Compatibility Aliases

约束什么：REST 命名空间就是 `/api/...`，URL 不携带产品/契约版本；主 turn WebSocket 是 `/ws`；可下载产物走 `/files/...`；页面路由用产品名词（`/chat/{sessionId}`、`/settings` 的 fragment 寻址 section）；不无限保留 REST 别名、页面重定向、query 式会话路由 fallback（query 只准表达一次性启动意图，永不承载会话身份）；契约版本住 OpenAPI `info.version`，WS 兼容性住必需的 `protocol_version` 信封，持久化数据自带 `schema_version`。

| # | 不变量 | 实现锚点（@6cf793bd8） | 改哪些代码会破坏 |
| --- | --- | --- | --- |
| A2-1 | 自有 REST 路由全部挂在字面 `/api` 前缀下，无版本段 | `deeptutor/api/main.py:577` 起（各 `include_router(..., prefix="/api...")`）；全仓库 `api/v1` 命中均为外部服务地址（如上游 Invidious：`deeptutor/api/routers/video_learning.py:466`） | 给自有路由加 `/api/v2` 式版本段；把「未来公共版本化」当加后缀实现（ADR 要求新 ADR） |
| A2-2 | 主 turn WebSocket 是 `/ws`（无前缀挂载） | `deeptutor/api/routers/unified_ws.py:43`；`deeptutor/api/main.py:793` | 移动/改名该挂载点，或给它加版本前缀 |
| A2-3 | 可下载产物走 `/files/...` | `deeptutor/api/main.py:578`（/files/outputs）、`:581`（/files/workspace-items）、`:625`（/files/library）、`:778`（/files/attachments） | 把产物迁回 `/api/...` 或新增并行下载路径 |
| A2-4 | 页面路由用产品名词 | `web/app/(workspace)/chat/[sessionId]/page.tsx`；`web/app/(settings)/settings/[section]/page.tsx` | 用版本号/代号重命名页面路由 |
| A2-5 | 版本住 `info.version` / `protocol_version` / `schema_version`，不进 URL | `deeptutor/api/main.py:406`；WS 见 ADR-0003；持久化如 `deeptutor/services/app_update.py:100`、`deeptutor/services/github_copilot_storage.py:56` | 把契约版本塞进路径；去掉持久化数据的 schema_version |
| A2-6 | 【现存偏差，改动前先读】页面 301 兼容重定向与 settings 旧键别名仍在服役；GET query 仍可承载会话选择器 | `web/next.config.js:153-160`；`web/features/settings/navigation/settings-nav.ts:564`；`deeptutor/api/routers/mastery_path.py:778-779` | 新增任何「永久」重定向/别名表会加深偏差；清理前先读 AGEN-1966 D2-D4 的裁量结论 |

## ADR-0003 Explicit Acknowledgement for Idempotent Turn Commands

约束什么：三个可重试变更（`cancel_turn`、`submit_user_reply`、`user_input`）必须携带客户端生成的稳定 `command_id`；服务器发非流内 `command_ack`（ID、命令种类、是否接受、稳定 error_code）；浏览器只在收到匹配 ack 后移除排队命令；流 seq 只确认流持久化、永不确认命令；所有 WS 命令与服务器帧要求 `protocol_version: "2.0"`。

| # | 不变量 | 实现锚点（@6cf793bd8） | 改哪些代码会破坏 |
| --- | --- | --- | --- |
| A3-1 | 可重试命令带稳定 `command_id`（模型层必填） | `deeptutor/api/contracts/turn_protocol.py:108-112`（cancel_turn）、`:127-133`（submit_user_reply）、`:142-147`（user_input） | 新增可重试命令却不带 `command_id`；或把 ID 改成服务器生成 |
| A3-2 | 浏览器维护需 ack 的命令集合并缺省铸造 UUID | `web/features/chat/transport/TurnRuntimeClient.ts:62-66`（`ACKNOWLEDGED_COMMAND_TYPES`）、`:73-84`（prepareCommand 铸造/保留 ID） | 新命令类型不进该集合（静默退化为无幂等投递） |
| A3-3 | 服务器发非流内 `command_ack`（id/kind/accepted/error_code） | `deeptutor/api/contracts/turn_protocol.py:203-211`（`CommandAckEvent`）；`deeptutor/api/routers/unified_ws.py:111-123`（`send_command_ack`）及三处发送点（`:295-325`、`:360-367`） | 去掉 ack 帧；把 accepted/error 语义混入流事件 |
| A3-4 | 浏览器只在匹配 ack 后移除排队命令；流 seq 不清除需 ack 命令 | `TurnRuntimeClient.ts:320`（按 `command_id` 匹配清除）、`:393`（seq 过滤器保留 `requiresAck` 项） | 在 `:390-394` 的过滤器里放行 requiresAck 项（= 退回「任意事件当 ack」的旧缺陷） |
| A3-5 | seq 只确认流持久化（订阅转发与 ack 路径完全分离） | `deeptutor/api/routers/unified_ws.py:142-171`（`subscribe_turn` 转发） | 用 `lastSeq` 清除排队命令 |
| A3-6 | 所有 WS 帧 `protocol_version: "2.0"`（入帧校验、出帧补全） | `deeptutor/api/contracts/turn_protocol.py:12-13`（常量）+ 各模型 `Literal["2.0"]`；`deeptutor/api/routers/unified_ws.py:194-199`（入帧统一校验）、`:70`（出帧统一补全） | 放宽 Literal 或跳过入帧校验 |
| A3-7 | 【已接受语义注记】交互式应答 30s ack 超时 = 移出队列并上抛（不替学习者超时补发，#1648） | `TurnRuntimeClient.ts:227-235` | 按 ADR 字面「修复」此超时路径会引入替学习者补发答案的行为回归（AGEN-1966 O1） |

## ADR-0004 Separate Invidious Account Workflow, Storage, and Transport

约束什么：`invidious_account.py` 只做工作流 facade（校验输入、选 scope、协调验证）；`invidious_account_storage.py` 独占文件系统布局、权限、原子 JSON 发布、过期清理与一次性 pending-flow 领取；`invidious_account_client.py` 独占 bearer 序列化与全部上游 HTTP；依赖严格内向（facade → 两个 adapter，storage 不碰 HTTP/工作流）；video_learning 之外的调用方只用 facade；持久化 JSON 形状、回调生命周期、公开函数与用户可见错误保持不变。

| # | 不变量 | 实现锚点（@6cf793bd8） | 改哪些代码会破坏 |
| --- | --- | --- | --- |
| A4-1 | facade 只依赖两个 adapter，自身无 HTTP、无文件写 | `deeptutor/video_learning/invidious_account.py:19-20`（仅 import `_client`/`_storage`；全文 0 处 httpx/文件写调用） | 在 facade 里直接发请求或写文件 |
| A4-2 | storage 只依赖标准库 + `deeptutor.multi_user.paths`，不引 HTTP/工作流 | `deeptutor/video_learning/invidious_account_storage.py:8-20`（import 块） | 在 storage 里 import httpx 或工作流模块 |
| A4-3 | client 独占 bearer 序列化与全部上游 HTTP | `deeptutor/video_learning/invidious_account_client.py:8`（httpx）、`:17`（`bearer_token`）、`:22`（AsyncClient） | 把上游调用散回 facade/storage |
| A4-4 | 外部调用方只经 facade；传输层测试直接 patch 传输模块 | `deeptutor/api/routers/video_learning.py:24`、`:150-162`；`tests/video_learning/test_invidious_account.py:17-19` | 在 video_learning 之外直接 import storage/client |
| A4-5 | pending-flow 的 state 先 SHA-256、绝不做路径段 | `deeptutor/video_learning/invidious_account_storage.py:53-59`（`flow_path`） | 跳过哈希直接把 state 拼进路径 |
| A4-6 | 存储权限不变量：目录/文件仅属主可访问（0700/0600） | `deeptutor/video_learning/invidious_account_storage.py:33-40`（`asset_dir` chmod）、`:43-49`（`pending_dir` chmod） | 放宽 chmod 或删除建目录时的权限收紧 |
| A4-7 | 原子发布：O_EXCL 临时文件 + fsync + `os.replace` | `deeptutor/video_learning/invidious_account_storage.py:69-85` | 改成直接覆盖写/去掉 fsync 链 |
| A4-8 | 一次性领取：同文件系统 rename claim，跨 worker/重启恰好一次 | `deeptutor/video_learning/invidious_account_storage.py:134-152`（`consume_pending_flow`） | 换成进程内字典/先读后删等非原子领取 |

## 验收对照

1. 覆盖全部 4 篇 ADR：0001/0002/0003/0004 各一节 ✓
2. 每条不变量至少一个实现锚点 path:line：上表 A1-1..A1-9、A2-1..A2-6、A3-1..A3-7、A4-1..A4-8 均含锚点，全部在 `6cf793bd8` 上核实 ✓
3. 产品代码零改动：本分支仅新增 `evidence/guide-adr-invariants-20261013/`（本文件 + SHA256SUMS），见 `git show --stat` ✓
