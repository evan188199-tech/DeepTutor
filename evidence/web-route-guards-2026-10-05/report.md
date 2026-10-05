# web 路由守卫与角色可见性清点报告

- 日期: 2026-10-05
- 基线: origin/main @ `f07029cfc` (release: v1.6.13)。扫描时 origin/dev 与 main 同 commit，无漂移。
- 分支: `scan/web-route-guards-20261005`（只读扫描，未改任何业务代码）
- 范围: `web/app`、`web/features`、`web/components`、`web/lib`、`web/hooks`、`web/shared`、`web/proxy.ts`（Next 中间件）；服务端仅读取守卫实现作为对照基线（`deeptutor/api/routers/auth.py`、`deeptutor/multi_user/`、`deeptutor/api/main.py`），未改动。
- 方法: 静态扫描。① 逐层读取守卫实现（中间件 → 客户端 401/403 处理 → 页面级守卫 → 导航可见性 → 服务端依赖链）；② 脚本 `classify_learner_surface.py` 抓取前端全部 API 字面量（254 个）并按 `_learning_surface_for_path` 的白名单规则逐条分类（learner 允许 78 / 拒绝 176，含人工剔除的误报，明细见 `learner-surface-frontend-calls.json`）；③ 对每个"拒绝"字面量回溯其 UI 页面，核对加载失败分支是报错还是空态。
- 参考教训: #1228（Learner 403 被伪装成空态）、#1222（learning_policy 下发到客户端但无人消费）。

## 总体结论

| 维度 | 结果 |
|---|---|
| 页面级守卫层数 | 4 层：Next 中间件 JWT 门（仅认证）→ `apiFetch` 401 跳登录 → 页面级角色守卫（仅 /admin）→ 能力门控（仅 LLM 能力） |
| 角色可见性模型 | 客户端是"admin / 非 admin + LLM 能力"二元模型；服务端是"learner 面默认拒绝"三值模型（chat/reading 白名单）——**两侧模型不对应，是全部不一致的根因** |
| 不一致项 | 10 项：高 3、中 4、低 3（详见下文） |
| 403 空态伪装 | main (v1.6.13) 上仍存在于 partners、agents、space 计数、memory 总览、chat 首页建议 5 处（#1228 的 /courses 一处已在客户端修复并复核确认） |

## 一、守卫分层模型（逐层，附 path:line）

**L1 Next 中间件（认证门，无角色/面检查）**
- `web/proxy.ts:82-91` — `AUTH_ENABLED` 时校验 `dt_token` cookie（`classifyToken`），无效重定向 `/login` 并保留 `next`；对所有非豁免页面路径生效。
- `web/proxy.ts:67-76` — `/api/*`、`/ws/*` 原样 rewrite 到后端（不重写路径，角色判断完全交给后端）。
- 判定：页面路径层只有"登录/未登录"，learner 与 standard 用户可打开任何页面。

**L2 客户端 401/403 处理**
- `web/shared/api/client.ts:38-46` — `apiFetch` 对 401（且 runtimeAuthEnabled）跳 `/login`；**对 403 无任何全局分支**，原样返回给调用方。
- `web/lib/auth.ts:49-81` — `/api/auth/status` 5 秒缓存，携带 `role`、`preset`、`learning_policy.allowed_surfaces`（auth.ts:21-32 定义了类型）。

**L3 页面级角色守卫（仅 admin 一处）**
- `web/app/(admin)/admin/users/page.tsx:101-108` — `fetchAuthStatus` 后：未认证 → `/login`，非 admin → `/`。整个 `(admin)` 组仅此一页。
- `web/app/(admin)/layout.tsx:1-7` — 布局无任何守卫（纯 div）；守卫依赖页面自身。
- 其余路由组布局 `(workspace)/layout.tsx`、`(utility)/layout.tsx`、`(settings)/layout.tsx` 只挂 `CapabilityGate`（能力门控），无角色/面守卫。

**L4 能力门控（仅 LLM 能力，非角色）**
- `web/lib/capability-routes.ts:19-27` — 路由→能力映射仅 4 条：`/chat`、`/partners`、`/co-writer`、`/learning`（llm）。
- `web/components/access/CapabilityGate.tsx:14-23` + `RequireCapability.tsx:47-58` — 按当前 pathname 锁页面（缺能力显示"Feature locked"说明，不隐藏入口）。
- `web/components/access/CapabilityAccessContext.tsx:58-79` — 探针 `GET /api/settings`：响应含 `catalog` → 视为 admin；否则以 `GET /api/settings/llm-options` 的选项数决定 `hasLlm`。
- 侧边栏锁定：`web/components/sidebar/SidebarNav.tsx:189-190、532`（`entry.requires` 缺能力 → 显示锁样式，仍渲染入口）。

**L5 导航可见性**
- `web/components/sidebar/nav-entries.ts:35-69` — 主导航 7 项 + 设置，无任何角色/面过滤；仅 `requires: 'llm'` 能力标记。
- `web/components/auth/AdminLink.tsx:19` — 管理入口 `!enabled || !isAdmin` 时隐藏（唯一按角色隐藏的导航件）。
- `web/features/settings/navigation/settings-access.ts:22-40` — 设置页可见性：`hideAdminOnly`（enabled 且非 admin）、`showLearnerOnly`（preset=learner）、`showGuardianOnly`（standard/custom）；`settings-nav.ts:88-105` 按标记过滤。

**S 服务端基线（对照用）**
- 认证：`deeptutor/api/routers/auth.py:419-463` `require_auth`（401）。
- 管理员：`auth.py:573-588` `require_admin`（403 "Admin access required"）。
- 学习面：`auth.py:689-703` `require_learning_surface` → `deeptutor/multi_user/learning_access.py:63-70` `assert_learning_surface`：仅当账号带 learning_policy（learner 预设）时生效，路径→面映射在 `auth.py:633-672`（`/api/reading`→reading、`/api/courses`→reading、`/api/books`→books、`/api/chat`/`/api/question`/`/api/sessions`/`/api/task-board`/`/api/mastery-paths`→chat、KB 只读模板→reading、learner 自有设置写→chat），其余一律空面 → 403。
- 默认 learner 授权：`deeptutor/multi_user/grants.py:192-214` `learner_grant`：`allowed_surfaces: ["chat", "reading"]`；管理端写入 `deeptutor/api/routers/multi_user.py:689`。
- 挂载差异：`deeptutor/api/main.py:575` auth 路由公开挂载；`:606-610` `file_preview` 仅 `require_auth`（路由内自查面，`file_preview.py:153-156`）；`:598-786` 其余业务路由统一 `_auth`（`_auth` 定义 main.py:591）；settings 门控组在 main.py:687（公开 ui 读在 683）。WS 路由（`:651-661`、`:772-786`）只在 handler 内认证，无面检查（全仓 `assert_learning_surface` 仅出现在 auth.py 与 file_preview.py）。

## 二、逐路由守卫矩阵

| 路由组 / 页面 | L1 中间件 | L3 页面守卫 | L4 能力门 | 导航可见性 | learner 首屏数据面 | 一致性 |
|---|---|---|---|---|---|---|
| `/login` `/register`（(auth)） | 豁免 | — | — | — | 公开 | ✔ |
| `/admin/users`（(admin)） | JWT | ✔ 非 admin 弹回（users/page.tsx:101-108） | 无 | AdminLink 隐藏（AdminLink.tsx:19） | `/api/auth/users` admin-only 403 | ✔（守卫单点，见 L10） |
| `/chat`、`/chat/[id]`（(workspace)） | JWT | 无 | llm | 永远显示 | `/api/sessions`、`/api/chat` ✔ chat 面 | ✔（但 llm-options 403，见 F6） |
| `/learning`（学习中心首页） | JWT | 无 | llm | 永远显示 | `/api/dashboard/learning-index` ✘ 403 | ✘ F2 |
| `/learning/books` | JWT | 无 | llm | 学习中心第一卡片（surfaces.ts:20-42） | `/api/books` ✘ books 面 | ✘ F1 |
| `/learning/reading` | JWT | 无 | llm | 显示 | `/api/reading`、library materials/reading ✔ | ✔ |
| `/learning/mastery` | JWT | 无 | llm | 显示 | `/api/mastery-paths` ✔ chat 面 | ✔ |
| `/learning/watching` | JWT | 无 | llm | 显示 | `/api/dashboard/learning-library/watching` ✘ | ✘ F3 |
| `/learning/practice` | JWT | 无 | llm | 显示 | `/api/question-notebook/practice` ✔ chat 面 | ✔ |
| `/partners`（+ new/[id]/groups） | JWT | 无 | llm | 永远显示 | `/api/partners` ✘ 403 → 空态 | ✘ F4（=#1228） |
| `/agents` | JWT | 无 | 无（不映射） | 永远显示 | `/api/subagents/*` ✘ 403 → 空态 | ✘ F4 |
| `/space`（skills/mcp/cli-apps/personas/questions） | JWT | 无 | 无 | 永远显示 | `/api/skills/*`、`/api/space/*`、`/api/personas` ✘ → 计数静默消失 | ✘ F4 |
| `/kanban` | JWT | 无 | 无 | 永远显示 | `/api/task-board` ✔ chat 面 | ✔ |
| `/co-writer` | JWT | 无 | llm | 永远显示 | `/api/documents/actions/*` ✘ 403（编辑动作报错） | ✘ F4 弱 |
| `/notebooks` | JWT | 无 | 无 | Space 瓦片进入 | `/api/notebooks` ✘ 403；创建走 banner 报错 | ✘ F4 弱 |
| `/memory`（+graph/l1/l2/l3/resolve） | JWT | 无 | 无 | Space 瓦片进入 | `/api/memory/*` ✘ 403 → 403 body 被当数据渲染 0 | ✘ F4（最重） |
| `/knowledge-bases` | JWT | 无 | 无 | Space 瓦片进入 | 列表/读 ✔（KB 只读白名单）；`embedding-usage`、kiwix/obsidian 连接 ✘ | ✘ F7 部分 |
| `/courses` | JWT | 无 | 无 | Space 瓦片进入 | `/api/courses` ✔ reading 面（#1231 修复在基线内） | ✔（已修，复核确认） |
| `/whisper` | JWT | 无 | 无 | 无导航入口 | `/api/capabilities/registered` ✘；轮次走 `/ws` | △ F9 |
| `/profile`、`/handoff`、`/avatar-preview` | JWT | 无 | 无 | 页脚 | auth 路由公开挂载、handler 内认证 ✔ | ✔ |
| `/settings`（(settings)） | JWT | 无 | llm | SECONDARY_NAV 永远显示 | 多数 section 403，见 F7 | ✘ F7 |
| `/settings/progress` | JWT | 无 | 无 | 设置分类 | `/api/mastery-paths/reading/records` ✔ chat 面 | ✔ |

## 三、不一致清单（分级）

判定依据统一说明：learner 面白名单 = `auth.py:633-672`；默认授权面 = `grants.py:206` `["chat","reading"]`；`assert_learning_surface` 对不在授权面的请求抛 403（`learning_access.py:63-70`）。

### F1（高）默认 learner 授权不含 "books"，而学习中心把 Books 作为第一入口

- 服务端：`/api/books` 映射为 `books` 面（auth.py:642），默认 `allowed_surfaces=["chat","reading"]`（grants.py:206）→ 默认 learner 访问 `/api/books/*`、`/api/dashboard/learning-library/books`（auth.py:643）、`/ws/books` 一律 403。
- 客户端三处按"books 可用"实现：
  - 管理端类型把 `allowed_surfaces` 收窄为 `"chat" | "reading"`，UI 根本无法授予 books：`web/features/multi-user/types.ts:25`、默认值 `web/features/multi-user/components/GrantEditor.tsx:46`；
  - 学习中心 "Ways" 第一张卡即 Books（`web/components/learning/surfaces.ts:20-42`），`/learning/books` 经 `bookApi` 全部走 `/api/books`（`web/lib/book-api.ts:22`）。
- 判定：三侧（服务端面映射、默认授权、管理端 UI）互相矛盾——要么 books 该入默认授权，要么 UI 不该把它作为 learner 首入口。需要产品决策（对应 #1228 maintainer 评论中"逐条加白 vs 显式 learner 面清单"的待决问题）。

### F2（高）学习中心首页 `learning-index` 未入白名单：learner 进 `/learning` 即固定报错

- `web/components/learning/LearningDashboard.tsx:52-57` — 请求 `/api/dashboard/learning-index`，`!response.ok` 抛错 → catch 把四个 kind 全部记为失败 → `LearningErrorState`"部分学习内容加载失败"横幅（:95-105），且 30 秒轮询重复（:75）。
- 服务端白名单只有 `/api/dashboard/learning-library/materials|reading|books`（auth.py:640-643），`learning-index` 不在其中 → learner 固定 403。
- 判定：学习中心是主导航入口（nav-entries.ts:44-49 "Personalized Learning"），learner 打开首页必现错误横幅，属主路径一致性缺陷。子页 reading/mastery/practice 本身可用（各自 API 已白名单），横幅内容与事实不符。

### F3（高）watching 库列表未入白名单：`/learning/watching` 对 learner 固定报错

- `web/lib/learning-library.ts:11-14` — `learningLibrary(kind)` 请求 `/api/dashboard/learning-library/${kind}`，`!ok` 抛错；`web/components/learning/ActivityLibrary.tsx:33-38` catch 后显示 "Could not load learning records." 错误态（有报错，不是空态伪装）。
- 白名单只放行 `materials`、`reading`、`books` 三个 kind（auth.py:640-641），`watching` 缺失。
- 判定：观看是学习中心五入口之一，learner 固定报错；失败模式正确（有显式错误），但入口与授权不匹配。practice 首页走 `/api/question-notebook/practice`（chat 面）不受影响。

### F4（中）403 空态伪装清单（#1228 模式在 main 仍存 5 处）

以下页面把学习面 403 吞掉渲染成"空数据"，全部满足：API 前缀不在白名单 + 前端无 403 分支：

1. `/partners` — `web/app/(workspace)/partners/page.tsx:49-50`：`listPartners().catch(() => [])`、`listPartnerGroups().catch(() => [])` → 渲染"还没有伙伴"空态。与 #1228 第二条评论报告的 Partners 现象逐字吻合，issue 仍 open。
2. `/agents` — `web/components/agents/ConnectedAgents.tsx:55-56`：`detectSubagents().catch(() => [])`、`listSubagentConnections().catch(() => [])` → "暂无智能体"空态。
3. `/space` 瓦片计数 — `web/components/space/SpaceDashboard.tsx:294-299`：每瓦片 `.catch(() => undefined)`"留空即不显示计数"（代码注释自认），learner 看到无计数的空间网格，入口仍可点入并继续 403。
4. `/memory` 总览 — `web/components/memory/MemoryHub.tsx:61-66`：`apiFetch("/api/memory/overview").then(r => r.json())` **没有 `res.ok` 检查**，403 的 JSON 错误体被当作 `OverviewResponse` 渲染成 0/空；L1 计数 `.catch(() => 0)`。全组最重：无任何错误痕迹。
5. `/chat` 首页建议 — `web/components/chat/home/StarterSuggestions.tsx:93-98`：`if (!response.ok) return null` → 建议区静默消失（影响轻：装饰性内容）。
- 对照正面样例（同基线内已修对的）：`/api/courses` 走 `expectJson` 非 2xx 抛 `ApiError`（`web/lib/courses-api.ts:131-150`，#1231 修复，本卡复核确认在基线内）；`ActivityLibrary` 显式错误态。修复应统一到这两个模式。
- 去重：scan-route-contracts 只覆盖路由契约（其报告已记录 courses 客户端修复），空态伪装维度不重叠；上游 #1228 为 partners/courses 具体 case，此处是全量清点。

### F5（中）能力探针端点对 learner 必 403，能力门控永远停在乐观态

- `web/components/access/CapabilityAccessContext.tsx:58-79`：探针 `GET /api/settings`。该端点在面守卫路由组上（main.py:687 挂载 `_auth`；settings.py:892），learner 403 → `if (!res.ok) return;` 提前返回 → `finally` 仅置 `loading=false`，`isAdmin`/`hasLlm` 保持初始乐观值 `true`（:54-55）→ `has()` 恒真（:101-107）。
- 影响：无 llm 授予的 learner 在 `SidebarNav.tsx:189-190`、`RequireCapability.tsx:55` 处永不锁定；后端仍兜底，属 UX 一致性缺陷而非越权。standard 非 admin 用户探针 200（settings.py:892-898 返回非 catalog payload）不受影响。
- 判定：探针端点选择与 learner 现实不匹配；403 早退分支不重置乐观状态是直接原因。

### F6（中）learner 加载不到 grant 过滤后的模型列表 `/api/settings/llm-options`

- 服务端注释明说该端点是为非管理员准备的（settings.py:895-898 "Non-admins never see the catalog … their model choices come from /settings/llm-options (grant-filtered)"），但它挂在面守卫路由组且 `/api/settings/llm-options` 不在白名单 → learner 403。
- 客户端：`web/lib/llm-options.ts:69-72` 非 2xx 抛错 → `web/hooks/useLLMOptions.ts:51-55` 置 `refresh-failed` → 输入框模型选择器静默为空。chat 是 learner 唯一主面，模型列表却是空的。
- 判定：白名单设计意图（非管理员走 grant-filtered 列表）与面默认拒绝自相矛盾。

### F7（中）设置页可见性模型（admin/非 admin）与服务端面模型（learner default-deny）不对应

- `web/features/settings/navigation/settings-access.ts:29-40` 只产出 admin/learner/guardian 三个布尔；`settings-nav.ts:88-105` 仅过滤 `adminOnly` 叶子（video-learning、attachments、agent-* 等，settings-nav.ts:256、301、317-438）。
- 未标 `adminOnly` 且 learner 必 403 的 section（learner 打开设置页后逐一失败）：Network（`/api/settings/network`，settings.py:1031）、Tools（`/api/tools`、`/api/settings/enabled-tools`）、Capabilities（`/api/capabilities/settings`）、起始建议（`/api/settings/chat-starters`，settings.py:1093）、文档解析（`/api/settings/document-parsing`）、Memory（`/api/memory/settings`）、工作区 GET（白名单只放行少量写模板，auth.py:611-629）、关于（`/api/system/status|update/*`）。
- learner 真正可用的仅剩：外观（GET /api/settings/ui 走公开路由 settings.py:2089 + PUT 白名单）、学习进度（`/api/mastery-paths/reading/records`）、学习档案、监护（standard/custom 才显示）。
- 判定：设置页对 learner 呈现大量"可见但必坏"的入口；`hideAdminOnly` 的注释"Admin-owned settings stay hidden … for ordinary users"（settings-access.ts:6）只兑现了一小半。

### F8（低）chat 附件链路对 learner 断裂

- 附件限额：`web/lib/attachment-limits.ts:43` `GET /api/settings/chat-attachments`（settings.py:1086，面外）→ 403 → 代码自述"Defaults apply until the fetch resolves"，403 后永久用默认值，无提示。
- 附件下载：`/files/attachments/{session_id}/{attachment_id}/{filename}`（attachments.py:40，`_auth` 挂载 main.py:768-772，不在白名单）→ learner 403；消息内图片/PDF 附件经该 URL 直出（`web/components/chat/preview/previewers/ImagePreview.tsx:9`、`PdfPreview.tsx:10`），learner 端显示破图/加载失败。
- 判定：chat 面本身放行，但配套附件读端点不放行，主学习面内体验不一致。

### F9（低）WS 层无 learning-surface 检查（面检查只覆盖 HTTP）

- WS 路由挂载不带 `_auth`（main.py:651-661、772-786），handler 内只做连接认证（auth.py:547-572 区域）；全仓 `assert_learning_surface` 仅 HTTP 路径使用（auth.py + file_preview.py:153-156）。
- 例：learner 可对 `/ws/books`（其 HTTP 面 403，见 F1）、`/ws/partners/{id}`（无 partner 者由 partner_access 兜底）发起连接握手，行为与 HTTP 面不对称。
- 去重：`/ws` vs `/ws/ws` 路径漂移属 scan-route-contracts F1，不在此重复。

### F10（低）(admin) 路由组守卫是单点，组布局无守卫

- 现状可用：`(admin)` 仅 `admin/users` 一页，页面自检（users/page.tsx:101-108）；中间件只验 JWT（proxy.ts:82-91），learner 直达 `/admin/users` 会被页面弹回。
- 结构风险：`web/app/(admin)/layout.tsx:1-7` 无守卫，后续新增 admin 页面若忘记页面级检查即裸奔；API 侧 `/api/auth/users` 有 `require_admin` 兜底（数据不泄露），风险限于页面骨架暴露。
- 判定：建议把角色守卫上收到 `(admin)/layout.tsx`（客户端组件包装），与 `(workspace)` 组挂 `CapabilityGate` 的模式对齐。

## 四、去重对照

| 来源 | 关系 |
|---|---|
| scan-route-contracts（evidence/route-contracts-2026-10-04） | 不同 lane（契约 vs 守卫/可见性）。其 F1（/ws 路径漂移）、F2（空挂载）、F3（locale 文案）不重复报告；其"issue #1228 客户端已修复"结论经本卡复核仍成立（courses-api.ts:131-150 在 f07029cfc）。 |
| test-permission-matrix（后端） | 本卡只消费其守卫实现作为服务端事实基线（auth.py / learning_access.py / grants.py），未重复后端矩阵工作；F1-F10 均为客户端可见性/一致性发现。 |
| 上游 #1228（open） | F4 的 partners 项与 #1228 第二条评论吻合；本卡补齐 main 基线全量清单。 |
| 上游 #1222（open） | "policy reaches the client but nothing reads it"——F1/F2/F3/F5/F6/F7 是该论断在 v1.6.13 的逐点证实与定位。 |
| 上游 PR | 无与本卡发现重叠的 open PR（learner 相关 open PR 仅 mastery/role 白名单方向：#1279、#1572 等）。 |

## 五、局限性

- 静态扫描：未启动服务、未以真实 learner 会话实测 403（遵守只读边界）；403 行为由服务端守卫实现与路由挂载静态推导，关键路径（books 面、learning-index、llm-options、/files/attachments）均给出双侧代码证据。
- 前端 API 字面量抓取依赖字符串/模板字面量；变量拼接后再 fetch 的调用点可能遗漏（与 scan-route-contracts 同一局限）。
- 面白名单的模板级规则（KB 只读、learner 设置写）按方法+模板匹配，脚本对 GET 类字面量标注为条件允许，已在明细 JSON 中单独标注，未计入"拒绝"。

## 六、可拆卡片建议

1. 修复卡（高优）：learner 授权面与学习中心入口对齐——books 入默认授权或 UI 隐藏 books/watching 入口（F1/F3）；需先在 #1228 产品方向（显式 learner 面清单 vs 继续加白）上做决策。
2. 修复卡（高优）：`/api/dashboard/learning-index`、`/api/dashboard/learning-library/watching` 入白名单，或学习中心首页按 `learning_policy.allowed_surfaces` 折叠入口（F2，顺带回应 #1222 的"客户端消费 policy"）。
3. 修复卡（中优）：403 空态伪装统一修复——partners/agents/space/memory/suggestions 五处补 403 分支（对齐 courses `expectJson` / ActivityLibrary 错误态模式），补一条"403 不渲染空态"的契约测试（F4）。
4. 修复卡（中优）：CapabilityAccessContext 探针改造——改用 learner 可达端点（如授权 llm-options 或改读 `/api/auth/status.learning_policy`），403 早退分支重置乐观态（F5）；同一张卡可带上 llm-options 白名单化（F6）。
5. 修复卡（中优）：设置页导航按面模型过滤——为 learner 隐藏白名单外 section 或按 `allowed_surfaces` 动态渲染（F7）。
6. 修复卡（低优）：chat 附件链路 learner 白名单化（`/files/attachments` 读 + `chat-attachments` 限额）（F8）。
7. 结构卡（低优）：`(admin)/layout.tsx` 上收角色守卫；WS 面检查策略写入开发者文档（F9/F10）。
