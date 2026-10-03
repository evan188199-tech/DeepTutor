# settings 草稿与 apply 链路只读扫描报告

- 日期：2026-10-03
- 仓库：/Users/Shared/DeepTutor（origin = HKUDS/DeepTutor）
- 扫描基线：origin/main `ef2d9e5c3`（= tag v1.6.12，即 issue #1630 报告的版本）
- 方式：独立 worktree + 分支 `scan/settings-draft-apply-20261003`，未改动任何产品代码
- 关联：issue #1630 已有开放 PR #1634（仅新增 `web/tests/settings-unified-draft.spec.tsx` 一个测试用例）。本卡为全量扫描，不与其冲突；#1634 的新增用例已在本地验证（见 §6）。
- 路径均为相对仓库根；行号以 `ef2d9e5c3` 为准。

## 1. 链路总览

草稿信封（`deeptutor/services/config/settings_draft.py:43-44`）：
`{version, updated_at, catalog, extensions}`；`extensions` 为按页面注册键索引的不透明 payload。草稿文件按用户隔离（`settings_draft.py:162-168` → path_service 用户目录）。

- 写入段：
  - `PUT /api/settings/draft`（`deeptutor/api/routers/settings.py:1845-1860`）— 前端 `draftEnvelope()`（`web/features/settings/store/SettingsStore.tsx:1451-1454`）整信封覆盖
  - 预设暂存 `POST /presets/{id}/draft`（`settings.py:1297-1341`，其中 1322-1325 写入 `extensions.tools`）
  - catalog 草稿编辑：`/apply/registry`、`/apply/provider`、`/apply/service`（`settings.py:1683-1826`，只改 catalog 段）
- 消费段：
  - `POST /api/settings/apply`（`settings.py:1869-1900`）— **只消费 catalog**（1885-1890），随后 `draft_service.clear()`（1895）**清空整个信封**
  - `extensions` 的消费完全在前端：Apply 时逐键 PUT 到各归属端点（`SettingsStore.tsx:1756-1762` → `web/lib/settings-extensions.ts:40-88`），发生在 `POST /apply` 之前
  - 仅读 catalog 的辅助消费：`/test-provider`（1910）、模型下载（2160、2191）

即：**服务端对 `extensions` 段不存在任何消费者**，草稿的"应用"语义对 extensions 而言是纯前端约定（发现 F3）。

## 2. extensions 键清单（写入点 → 消费点）

| 键 | 写入点（注册） | apply 消费端点 | 后端门禁 | 风险 |
|---|---|---|---|---|
| `ui` | `SettingsStore.tsx:920`（stageUi 918-925） | `PUT /api/settings/ui`（`settings.py:2083`） | 登录 | 低 |
| `tools` | `ToolsSettingsSection.tsx:86` | `PUT /api/settings/enabled-tools`（`settings.py:2140`） | 登录 | 低 |
| `workspace` | **无写入方**（`WorkspaceSettingsSection.tsx` 直接保存，不走草稿） | `PUT /api/settings/workspace`（`deeptutor/api/routers/workspace.py:281`，挂载 `main.py:690-693`） | 登录 | 低（死映射，F7） |
| `video-learning` | `VideoLearningSettingsSection.tsx:27` | `PUT /api/settings/video-learning`（`video_learning.py:100`，挂载 `main.py:695-699` 带 `_admin`） | admin | 低（页面 adminOnly，`settings-nav.ts:247-256`） |
| `learner-profile` | `LearnerProfileSettingsSection.tsx:26` | `PUT /api/auth/profile/learner-profile`（`auth.py:1449`） | 登录 | 低 |
| `document-parsing` | `DocumentParsingSettingsSection.tsx:74` | `PUT /api/settings/document-parsing`（`settings.py:1344-1346`） | admin | 低（GET 同为 admin，非 admin 无法暂存） |
| `mineru` | `MinerUEngineSettings.tsx:91` | `PUT /api/settings/mineru`（`settings.py:1219-1221`） | admin | 低（同上） |
| `update-checks` | `AboutSettingsSection.tsx:63` | `PUT /api/system/update/settings`（`system.py:250-256`） | **admin** | **中（F5）**：About 页未标 adminOnly，GET 无门禁，非 admin 可暂存、apply 必 403 |
| `chat-starters` | `StartersSettingsSection.tsx:118` | `PUT /api/settings/chat-starters`（`settings.py:1105`） | 登录（无 admin 门禁但写全局） | 低（观察项） |
| `chat-attachments` | `AttachmentsSettingsSection.tsx:145` | `PUT /api/settings/chat-attachments`（`settings.py:1116-1118`） | **admin**（GET 公开，1082-1084） | **中（F5）**：Attachments 页未标 adminOnly，非 admin 可暂存、apply 必 403 |
| `chat-timeout` | `ChatResponseTimeoutSection.tsx:92` | `PUT /api/settings/chat-response-timeout`（`settings.py:2047`） | 登录 | 低 |
| `capabilities` | `CapabilitiesSettingsSection.tsx:176` | `PUT /api/capabilities/settings`（`capabilities_settings.py:34`，`main.py:651-656`） | 登录（写全局 YAML，`capabilities_settings.py:421-428`） | 低（观察项：非 admin 可改全局能力开关） |
| `memory` | `MemorySettingsSection.tsx:98` | `PUT /api/memory/settings`（`memory.py:622`） | 登录（用户域） | 低 |
| `network` | `NetworkSettingsSection.tsx:197` | `PUT /api/settings/network`（`settings.py:1033-1035`） | admin（GET 亦然，1027-1029） | 低（非 admin 加载失败无法暂存） |
| `codex-reasoning` | `CodexOAuthCard.tsx:37` | 逐模型 `POST /providers/openai-codex/models/reasoning-effort`（`settings.py:1002-1006`，`web/lib/codex-oauth.ts:204-214`） | codex OAuth 本人 | 低 |
| `subagent:<kind>` | `SubagentSettingsEditor.tsx:333` | `PUT /api/subagents/settings`（`subagents.py:270-285`，按 backend/字段合并 279-282） | admin | 中（见 §3，页面 adminOnly `settings-nav.ts:307-438`） |
| `guardian:materials:<uid>` | `GuardianSettingsSection.tsx:54` | `PUT /api/multi-user/learners/<uid>/materials`（`multi_user.py:565`） | 监护人域 | 中低（F6：learner 被删后 404 中断整次 apply） |
| `guardian:restrictions:<uid>` | `GuardianSettingsSection.tsx:58` | `PUT /api/multi-user/learners/<uid>/restrictions`（`multi_user.py:656`） | 监护人域 | 中低（同上） |
| （历史键）`document_parsing`、`enabled_tools` | 旧版本页面（改名前） | **已无映射 → apply 抛错**（F2） | — | **高** |

catalog 段：写入 `PUT /draft`、预设、catalog 三编辑端点；消费 `POST /apply`（`settings.py:1885-1890`）+ mask 还原（`settings_draft.py:139-159`）。链路完整，风险低。

## 3. 发现（按风险排序）

### F1【高】`PUT /draft` 对 extensions 是整体覆盖，与服务端预设路径语义不一致
- `SettingsDraftPayload.extensions` 默认 `dict()`（`settings.py:289-294`）；`update_settings_draft`（`settings.py:1845-1860`）经 `merge_draft_secrets`（`settings_draft.py:139-159`，只解析 catalog 密钥）后**原样替换** stored extensions。
- 对比：预设暂存路径明确"caller 省略 extensions 时保留既有"（`settings.py:1311-1315` 注释即为修这类问题而写），PUT /draft 没有同等保护。
- 触发面：任何省略/空 extensions 的 PUT 调用方（第二个标签页、API 直调、旧客户端）都会**静默清空**他人/他页已暂存的草稿——正是"extensions.subagent:* 被清空"这一失败类的服务端入口。
- 前端目前总是发整信封（`SettingsStore.tsx:1451-1454`），故 HEAD 上是潜伏缺陷；跨标签页场景可实测复现（F8）。
- 可拆卡：补测（PUT /draft 省略 extensions 必须保留 stored）+ 修复（与预设路径对齐为合并语义）。

### F2【高】历史键残留草稿会让 Apply 永久卡死（含 `document_parsing`/`enabled_tools` 改名遗留）
- `945335001`（2026-09-23，v1.6.12 内）从 `EXTENSION_ENDPOINTS` 删除旧键 `document_parsing`、`enabled_tools`，仅保留连字符新键。
- 服务端 `SettingsDraftService.load()`（`settings_draft.py:68-83`）不清理未知扩展键 → 改名前保存过的用户草稿永久携带旧键。
- 前端恢复：`SettingsStore.tsx:800-804` 把 stored extensions 全量灌入 pendingRef → Apply 循环对旧键调用 `applyExtensionPayload` → `if (!endpoint) throw new Error("Unknown settings section: …")`（`settings-extensions.ts:61`）。
- flush 循环无逐键容错（`SettingsStore.tsx:1757-1762`）：抛错 → 后续键全部跳过、`POST /apply` 不再执行、草稿不清理 → "未保存更改"提示永不消失（与 #1630 症状同类）。用户唯一出口是 Discard（连带丢弃所有未应用修改）。
- 同类暴露：任何未来被改名/下线的键都会复现此问题（无白名单降级机制）。
- 可拆卡：修复（对未知键跳过并提示/一次性迁移旧键映射）+ 补测（stored draft 含未知键时 Apply 不应卡死）。

### F3【高·架构】服务端 apply 只消费 catalog 即清空整个信封
- `apply_catalog`（`settings.py:1869-1900`）：1885 只取 `catalog`，1895 `draft_service.clear()` 无条件抹掉 `extensions`。
- extensions 的落地完全依赖前端先 flush 再调 `/apply` 的顺序约定（`SettingsStore.tsx:1745-1768`）。任何绕过前端的调用（curl、脚本、第三方客户端，如 #1630 报告者的手工验证）都会"apply 成功 + extensions 静默销毁"。
- 文档字符串（1869-1876）也只声明 catalog 语义，接口契约对 extensions 无保护。
- 即 issue #1630 修复方向 A 的落点：服务端消费（至少 `subagent:*`）或提供显式的 extensions flush 端点，可同时兜底所有前端版本。
- 可拆卡：修复（服务端 subagent/extensions 消费）+ 补测（POST /apply 对含 extensions 草稿的行为用例；当前 `tests/api/test_settings_router.py` 仅有 `/apply/service` 保留 extensions 的用例 1011/1030）。

### F4【中】Apply flush 循环首错即中断，无逐键隔离
- `SettingsStore.tsx:1757-1762`：顺序遍历 pendingRef，任一键 `ext.save()` / `applyExtensionPayload` 抛错即整轮中止（catch 仅弹 toast，1794-1799）。
- 后果：一个失败键（403/404/网络）阻断其后所有键 + catalog 应用 + 草稿清理；已成功键与未处理键混存于草稿，重试幂等（均为 PUT）但无部分应用报告。
- `guardian:*` 键内嵌 learner id（`settings-extensions.ts:57-60`），learner 被删后 404 → 必然触发本条（F6 归并于此）。
- `codex-reasoning` 为逐模型串行 POST（`settings-extensions.ts:45-51`），多模型时中断面更大。
- 可拆卡：修复（逐键 try/catch + 汇总失败键）+ 补测（一键失败不阻断其余键）。

### F5【中】导航可见性与 apply 端点门禁不匹配（非 admin 必卡 Apply）
- `about`（`settings-nav.ts:550` 起，无 adminOnly）可读写 `update-checks`，但 `PUT /api/system/update/settings` 为 `require_admin`（`system.py:250`），而 `GET /api/system/update`（236）无门禁 → 非 admin 能完整暂存、Apply 必 403。
- `attachments`（`settings-nav.ts:281-292`，无 adminOnly）同理：GET 公开（`settings.py:1082-1084`）、PUT admin（1116-1118）。
- 非 admin 触发 F4 中断后草稿保留、提示永不消失。多用户部署必现；单用户 admin 部署不触发。
- 可拆卡：修复（页面标 adminOnly 或 PUT 降权/前端降级提示）+ 补测（非 admin Apply 不被 admin-only 键阻断）。

### F7【低】`workspace` 为死映射
- `EXTENSION_ENDPOINTS.workspace`（`settings-extensions.ts:17`）无任何写入方（`WorkspaceSettingsSection.tsx` 不走草稿）；端点存在（`workspace.py:281`）。仅当旧草稿残留该键时才会被 PUT（schema 可能已漂移）。
- 可拆卡：小修（移除映射或确认保留原因）。

### F8【低】跨标签页 last-write-wins
- pendingRef 仅在 provider 首载时从服务端草稿播种一次（`SettingsStore.tsx:790-824`，`loadedOnce` 872-878）；`draftEnvelope()` 整信封 PUT。B 页在 A 页暂存后 Apply，会以 B 的旧 pendingRef 覆盖（配合 F1 的覆盖语义）。低频，观察即可。

### F9【低·观察】门禁不对称
- 草稿保存 extensions 无需 admin（`settings.py:1846-1848` 只校验 catalog），而多数扩展端点 apply 需 admin；`chat-starters`/`capabilities` 反向（PUT 无 admin 门禁但写全局，`settings.py:1105`、`capabilities_settings.py:34` + `capabilities_settings.py:421-428`）。当前导航掩蔽了大部分组合，记录备查。

### F10【信息】隔离与脱敏
- 草稿按用户隔离（`settings_draft.py:162-168`、`path_service.py:225-236`），extensions 不脱敏但仅回传本人（`settings_draft.py:124-136` 文档化），未发现跨用户泄露路径。

## 4. `subagent:*`（#1630 主体）在 v1.6.12 源码下的专项结论

写入 → 持久化 → 恢复 → 应用 → 落盘各环均在：
1. 暂存 `SubagentSettingsEditor.tsx:333`（`useStagedSettings("subagent:<kind>")`）
2. 信封持久化 `SettingsStore.tsx:1451-1454` + `settings.py:1845-1860`
3. 会话恢复 `SettingsStore.tsx:800-804` + `useStagedSettings.ts:39-59`
4. Apply flush：mounted 走 `ext.save()`，未 mounted 走 `applyExtensionPayload` → `PUT /api/subagents/settings`（`settings-extensions.ts:52-55` → `subagents-api.ts:219-229`）
5. 服务端按 backend/字段合并落盘 `subagent.json`（`subagents.py:276-285`），无相互覆盖

PR #1634 新增用例（restored subagent draft 先 PUT 再 `/apply`）**在 `ef2d9e5c3` 上直接通过**（验证方式见 §6）。#1630 报告者描述的入口页 `space/cli-apps/page-*.js` 在 v1.6.12 源码树中不存在（设置页 agent 页签由 `SettingsPageContent.tsx:202-214,271-272` 挂载）——报告环境疑似运行了更旧的构建，或构建产物与 tag 漂移（无法从源码侧进一步验证）。源码侧残留风险即 F1-F4：任何标签页/API 直调/未知键都会复现"配置被吞、提示不消失"。

## 5. 可拆补测/修复卡汇总

| 卡 | 类型 | 内容 | 对应发现 |
|---|---|---|---|
| X1 | 修复 | 未知/历史扩展键跳过 + 提示（或一次性迁移 `document_parsing`→`document-parsing`、`enabled_tools`→`tools`） | F2 |
| X2 | 修复 | 服务端 apply 消费 `subagent:*`（#1630 方向 A）或显式 extensions flush 端点 | F3 |
| X3 | 修复 | `PUT /draft` extensions 改为与预设路径一致的合并语义 | F1 |
| X4 | 修复 | flush 循环逐键容错 + 失败键汇总 | F4 |
| X5 | 修复 | About/Attachments 页 adminOnly 或对应 PUT 降权 | F5 |
| X6 | 小修 | 移除死映射 `workspace`（或注释保留原因） | F7 |
| T1 | 补测 | 后端：PUT /draft 省略 extensions 保留 stored（现无用例；预设路径已有对应实现注释） | F1 |
| T2 | 补测 | 后端：POST /apply 含 extensions 草稿的行为契约 | F3 |
| T3 | 补测 | 前端：stored draft 含未知键不阻塞其余键与 catalog 应用 | F2/F4 |
| T4 | 补测 | 前端：非 admin 场景 Apply 不被 admin-only 扩展键 403 卡死 | F5 |

## 6. 验证与测试证据

- 测试命令（worktree `web/`，`npm ci` 后）：
  - `npx vitest run tests/settings-unified-draft.spec.tsx tests/subagent-grok-settings.spec.tsx` → **2 files / 13 tests / 13 passed**（HEAD 基线全绿）
  - 将 PR #1634 新增用例应用到临时副本（`tests/scan-tmp-pr1634.spec.tsx`，验证后已删除）→ **1 passed / 0 failed**，即该用例在 `ef2d9e5c3` 上不构成失败复现
- 后端测试覆盖现状：`tests/api/test_settings_router.py`（60 用例）中唯一涉及 extensions 的是 `/apply/service` 保留断言（1011、1030）；`apply_catalog` 与 `PUT /draft` 的 extensions 语义无用例（→ T1/T2）。
- 本卡零代码改动：worktree 仅新增 `evidence/settings-scan-2026-10-03/`（本报告 + SHA256SUMS）；未 checkout/reset/clean 主工作区，未触碰其未提交内容。

## 7. 结论

settings draft 的 catalog 链路完整；`extensions` 段的消费是纯前端约定，服务端存在三个可静默清空/卡死 Apply 的入口（F1-F3），外加门禁错配与无容错循环（F4-F5）。`subagent:*` 在 v1.6.12 源码下主链路完好且 PR #1634 的用例已覆盖；建议按 X1-X6/T1-T4 拆卡补齐后端契约与容错，再评估是否需要 #1630 方向 A 的服务端兜底。
