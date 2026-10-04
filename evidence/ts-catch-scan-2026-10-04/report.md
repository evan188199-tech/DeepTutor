# AGEN-421 · web/ 空 catch 与 no-op `.catch` 三型分型扫描报告

- **扫描对象**: HKUDS/DeepTutor `origin/main` @ `ef2d9e5c3c99fd073742c5aadc2bb9584b1e503b`（v1.6.12），worktree `dt-agen421-scan-wt`，分支 `agent/agen421-ts-catch-scan`
- **扫描日期**: 2026-10-04（UTC）
- **方式**: 只读静态扫描（Python 正则 + ripgrep 复核 + 逐条人工上下文分型）。**未修改任何产品代码，产物只进本证据目录。**
- **范围**: `web/**/*.{ts,tsx,js,jsx,mjs}`（排除 `node_modules`、`.next`）。`deeptutor_web/` 为打包产物，不在 DT-22 口径内，未纳入。

## 1. 结论（PASS）

| 分型 | 数量 | 说明 |
| --- | --- | --- |
| 应上报（report） | 5 | 失败影响用户数据/核心操作，需用户可见反馈 |
| 应降级（degrade） | 15 | 失败被容忍但必须显式落兜底/错误态并留痕 |
| 尽力而为语义（best_effort） | 21 | 吞错即设计意图，保留，补注释/调试日志 |
| **合计** | **41** | — |

严重度分布：HIGH 2、MEDIUM 10、LOW 29。明细（含逐条 reason/consequence/fix）见 `ts_catch_classified.json`（权威数据）。

## 2. 与 DT-22 口径的核对（40 → 41）

DT-22 报告口径：空 `catch {}` **3** 处 + no-op `.catch(() => {})` **37** 处 = **40** 条。本扫描：

- 空 `catch {}`：**3** 处，与 DT-22 完全一致（`web/next.config.js:89`、`web/lib/iframe-html.ts:103`、`web/lib/iframe-html.ts:121`）。
- no-op `.catch`：单行 rg 口径复现 **37** 条，与 DT-22 完全一致；另以**多行模式**补齐 **1** 条 DT-22 单行口径漏计的 `web/components/watching/WatchingPane.tsx:108`（其 handler `() => undefined` 位于下一行；该条在 DT-22 附录 B 中有人工评级 LOW，但未计入"37"）。故实际 **38** 条，合计 **41** 条。
- `void` 前缀 fire-and-forget（DT-22 附录 B 中 `courses/[courseId]/page.tsx:414`、`ChatStateAdapter.tsx:3217` 两条无 `.catch` 的裸 void 调用）已由 scan-void-promises 卡认领，**本卡未纳入**，无重复。
- **验收口径**：DT-22 报告口径全部 40 条均已覆盖并逐条分型；另多 1 条为口径补齐（41 = 40 + 1）。

## 3. 分型标准

- **应上报**：失败影响用户数据或核心操作结果 → `console.error` + 用户可见反馈（toast/错误态/埋点）。
- **应降级**：失败被容忍但当前零留痕、无显式兜底语义 → `console.warn` + 显式兜底（错误态/空态/重试入口）。
- **尽力而为语义**：吞错即设计意图（进度续播兜底、跨域 postMessage、构建期探测、测试代码、错误已另有上报的恢复动作）→ 保留吞错，补注释/`console.debug`。

## 4. Top 10（一句失败后果 + 修复建议）

| # | 位置 | 分型/严重度 | 失败后果（一句） | 修复建议 |
| --- | --- | --- | --- | --- |
| 1 | `web/components/partners/PartnerConfigure.tsx:164` | report/HIGH | 工具选项加载失败被吞后勾选集建立在空集上，保存配置会静默清空伙伴已授权的工具。 | 工具区显示加载失败+重试，options 未加载前禁止保存并在 save 前校验。 |
| 2 | `web/components/chat/home/ChatComposer.tsx:545` | report/HIGH | 草稿恢复（含附件）失败被吞，用户上一次输入无声丢失。 | `console.error` + "草稿未能恢复"轻提示。 |
| 3 | `web/context/QuizFollowupContext.tsx:280` | report/MEDIUM | `followup_session_id` 回写失败被吞，测验追问与会话关联永久丢失。 | **上游已有修复 PR #1701（open），修复卡应改为复核该 PR，勿重复实现。** |
| 4 | `web/components/reading/library/MaterialLibrary.tsx:482` | report/MEDIUM | 用户显式点击 Retry 后的失败被吞且状态未复位，按钮表现为无响应。 | 行内"重试失败"提示 + `console.error`，保持 failed 态可再次重试。 |
| 5 | `web/components/reading/library/ReadingLibrary.tsx:512` | report/MEDIUM | 同上，显式重试失败无任何结果反馈（仅 retrying 态有复位）。 | 同 #4。 |
| 6 | `web/components/partners/PartnerConfigure.tsx:136` | degrade/MEDIUM | 伙伴资产列表加载失败静默为空，配置页呈现"无资产"假象。 | 置 assetsError 态 + 面板重试；`console.warn`。 |
| 7 | `web/components/chat/home/ConsultationTabBody.tsx:153` | degrade/MEDIUM | 会话身份解析失败后组件永远停留在 Pending 态，用户误以为仍在加载。 | 失败渲染"无法加载咨询"错误态 + 重试。 |
| 8 | `web/components/chat/home/StandaloneComposer.tsx:615` | degrade/MEDIUM | subagent 预算加载失败静默为 null，与"未选 agent"语义混同，本次会话 agent 咨询静默失效。 | 区分"未配置"与"加载失败"两个状态，warn + 重试。 |
| 9 | `web/features/chat/components/ChatWorkspace.tsx:1887` | degrade/MEDIUM | 同 #8 同型（同一 API、同一失败后果）。 | 同 #8，两处应一并修。 |
| 10 | `web/components/reading/library/AddMaterialsDialog.tsx:714` | degrade/MEDIUM | 资料列表加载失败后仅清 loading，对话框以空列表冒充"没有资料"。 | 空态文案区分"没有资料"与"加载失败" + 重试。 |

## 5. 全量分型清单（41 条）

| 位置 | 分型 | 严重度 | 理由（摘要） |
| --- | --- | --- | --- |
| `web/app/(utility)/courses/[courseId]/page.tsx:70` | 尽力而为 | LOW | Promise.all 内有显式注释：单子系统不可用不拖垮整页，null 由 tile 渲染空态 |
| `web/app/(workspace)/partners/new/page.tsx:113` | 应降级 | MEDIUM | 新建伙伴页工具选项失败静默空表单；后果：新建伙伴可能缺少预期工具授权 |
| `web/components/chat/BookReferencePicker.tsx:106` | 应降级 | LOW | 书籍详情失败仅清 loading，空态与加载失败不可分 |
| `web/components/chat/home/ChatComposer.tsx:545` | 应上报 | HIGH | 草稿恢复失败用户输入丢失（Top10 #2） |
| `web/components/chat/home/ChatComposer.tsx:658` | 应降级 | LOW | 发送后清草稿写失败，旧草稿下次复活；可 warn + stale 标记 |
| `web/components/chat/home/ConsultationTabBody.tsx:153` | 应降级 | MEDIUM | 失败后恒 Pending（Top10 #7） |
| `web/components/chat/home/SessionActivityPanel.tsx:87` | 应降级 | LOW | 会话标题解析失败回退原始 ID，静默 |
| `web/components/chat/home/SessionActivityPanel.tsx:103` | 应降级 | LOW | 笔记本标题解析失败同上 |
| `web/components/chat/home/SessionActivityPanel.tsx:120` | 应降级 | LOW | 书籍标题解析失败同上 |
| `web/components/chat/home/StandaloneComposer.tsx:615` | 应降级 | MEDIUM | 预算失败混同"未选 agent"（Top10 #8） |
| `web/components/knowledge/KnowledgePage.tsx:198` | 尽力而为 | LOW | KB id 归一化失败仅跳过升级，已有按名称匹配兜底 |
| `web/components/partners/PartnerComposer.tsx:143` | 应降级 | LOW | 斜杠命令列表失败静默空调色板 |
| `web/components/partners/PartnerConfigure.tsx:136` | 应降级 | MEDIUM | 资产假空（Top10 #6） |
| `web/components/partners/PartnerConfigure.tsx:164` | 应上报 | HIGH | 保存可静默清空工具配置（Top10 #1） |
| `web/components/reading/EpubDocumentView.tsx:411` | 尽力而为 | LOW | 阅读位置读取失败回退从头开，符合"阅读必须继续"设计（DT-22 §3 #1673/#1688 佐证） |
| `web/components/reading/ReadingActionsProvider.tsx:80` | 尽力而为 | LOW | profile 失败回退默认 age mode，失败方向安全 |
| `web/components/reading/ReadingExtensionBar.tsx:121` | 尽力而为 | LOW | 同上 |
| `web/components/reading/library/AddMaterialsDialog.tsx:714` | 应降级 | MEDIUM | 资料库假空（Top10 #10） |
| `web/components/reading/library/MaterialLibrary.tsx:482` | 应上报 | MEDIUM | 显式重试无反馈（Top10 #4） |
| `web/components/reading/library/ReadingLibrary.tsx:512` | 应上报 | MEDIUM | 显式重试无反馈（Top10 #5） |
| `web/components/reading/workspace/MediaReadingStage.tsx:142` | 尽力而为 | LOW | 浏览器全屏 API 尽力而为，状态由 fullscreenchange 事件兜底 |
| `web/components/reading/workspace/MediaReadingStage.tsx:240` | 尽力而为 | LOW | 媒体进度后台写，符合"不因进度写失败中断"设计 |
| `web/components/reading/workspace/MediaReadingStage.tsx:328` | 尽力而为 | LOW | 媒体进度读取失败回退默认起点 |
| `web/components/reading/workspace/useReadingWorkspace.ts:453` | 应降级 | LOW | 会话列表失败侧栏静默空 |
| `web/components/watching/WatchingBrowser.tsx:279` | 尽力而为 | LOW | 发生在错误态 onRetry 内，主错误仍可见；吞错仅为避免 unhandled rejection |
| `web/components/watching/WatchingPane.tsx:108` | 尽力而为 | LOW | 视频进度写 best-effort；本条为多行口径补齐（DT-22 "37"漏计） |
| `web/context/QuizFollowupContext.tsx:280` | 应上报 | MEDIUM | followup 回写丢失（Top10 #3，上游 PR #1701） |
| `web/features/chat/components/ChatWorkspace.tsx:1887` | 应降级 | MEDIUM | 同 StandaloneComposer:615（Top10 #9） |
| `web/features/settings/sections/ArchivedChatsSettingsSection.tsx:113` | 尽力而为 | LOW | 位于 catch 内，主错误已经 setError 上报，列表刷新属恢复动作 |
| `web/features/settings/sections/DataMigrationSettingsSection.tsx:113` | 应降级 | MEDIUM | 迁移 /operations 轮询失败静默，进度面板停更 |
| `web/features/settings/sections/DataMigrationSettingsSection.tsx:136` | 应降级 | LOW | 相邻 /discover 失败有 setError，本条没有，操作列表可能串位 |
| `web/hooks/useVoiceRecorder.ts:76` | 尽力而为 | LOW | 错误体解析失败回退通用文案，错误本身仍上抛 |
| `web/lib/attachment-limits.ts:46` | 尽力而为 | LOW | 解析失败经 NaN 回退 DEFAULT_ATTACHMENT_LIMITS，显式默认兜底 |
| `web/lib/courses-api.ts:132` | 尽力而为 | LOW | null 仅用于错误详情提取后必抛 ApiError；边界：2xx+非法 body 返回 null as T（可另开收紧卡） |
| `web/lib/guardian-api.ts:57` | 尽力而为 | LOW | 同 courses-api.ts:132 模式与边界 |
| `web/lib/iframe-html.ts:103` | 尽力而为 | LOW | 跨域/沙箱 iframe postMessage 同步抛错为预期环境差异 |
| `web/lib/iframe-html.ts:121` | 尽力而为 | LOW | 同上（高度上报） |
| `web/next.config.js:89` | 尽力而为 | LOW | 构建期版本探测回退空串，上方已有完整注释 |
| `web/tests/chat-reply-language.spec.tsx:56` | 尽力而为 | LOW | 测试代码 |
| `web/tests/chat-reply-language.spec.tsx:57` | 尽力而为 | LOW | 测试代码 |
| `web/tests/e2e/settings-navigation.audit.ts:557` | 尽力而为 | LOW | 测试竞态下 route.fulfill 抛错属预期 |

## 6. 与上游的关系

- 上游（HKUDS/DeepTutor）当前无追踪"web 吞错清理/分型"的开放 issue 或 PR（已检索）。
- 唯一已有关联：**PR #1701（open）"fix(web): surface quiz follow-up session-id writeback failures"** 直接触及 `QuizFollowupContext.tsx:280` 这一条 → 该条修复应走复核 #1701，不重复开卡。
- 本卡**不向上游开 PR**；分型清单可直接拆修复卡（应上报 5 条 ≈ 3 张卡：工具配置保护、草稿恢复反馈、显式重试反馈×2 合一；#280 复核 #1701）。

## 7. 复现命令

```bash
# 单行口径（与 DT-22 §6 完全一致，复现 3 + 37）
rg -n --no-heading -U 'catch\s*(\([^)]*\))?\s*\{\s*\}' web -g '*.{ts,tsx,js,jsx,mjs}' -g '!node_modules/**'
rg -n --no-heading '\.catch\(\(\)\s*=>\s*(\{\}|undefined|null|void 0)\)' web -g '*.{ts,tsx,js,jsx,mjs}' -g '!node_modules/**'
# 多行口径（补齐 WatchingPane.tsx:108，共 3 + 38）
rg -n --no-heading -U '\.catch\(\s*\(\s*\)\s*=>\s*(\{|\}|undefined|null|void\s+0)\s*\)?' web -g '*.{ts,tsx,js,jsx,mjs}' -g '!node_modules/**'
# 全量明细与分型
python3 evidence/ts-catch-scan-2026-10-04/scan_ts_catch.py > /tmp/details.json
```

## 8. 产物

- `scan_ts_catch.py` — 只读扫描脚本（模式、口径、上下文提取）
- `ts_catch_details.json` — 41 条原始命中（含上下文、所在函数、语句）
- `classifications.json` — 分型表（三型定义 + 41 条归属/理由/后果/修复）
- `ts_catch_classified.json` — 合并后的权威明细（每条 action/severity/reason/consequence/fix）

---
*报告由只读扫描生成（agent/agen421-ts-catch-scan @ myfork）。分型争议以 `ts_catch_classified.json` 的 reason 字段与源码现场为准。*
