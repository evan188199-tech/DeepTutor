# Web 权限守卫分层导读（五层与 learner 面）

- 基线: origin/main @ `f07029cfc`（v1.6.13）。所有 `path:line` 均在该 commit 核对存在。
- 定位: 导读，不是审计。讲清五层各自"管什么/不管什么"、learner 白名单面如何叠加、以及两端模型不对应为何产生 10 项不一致。
- 证据来源: `evidence/web-route-guards-2026-10-05/report.md`（分支 `scan/web-route-guards-20261005`）；教训参考上游 #1228（403 被伪装成空态）、#1222（learning_policy 下发到客户端但无人消费）。

## 0. 一分钟总览

| 层 | 锚点 | 判定依据 | 管什么 | 不管什么 |
|---|---|---|---|---|
| L1 中间件 | `web/proxy.ts:82-91` | `dt_token` cookie 有效性 | 页面"登录/未登录" | 角色、learner 面、能力 |
| L2 apiFetch 401 | `web/shared/api/client.ts:38-46` | HTTP 401 | 会话过期跳 `/login` | 403（原样交回调用方） |
| L3 页面守卫 | `web/app/(admin)/admin/users/page.tsx:100-112` | `auth.status.role` | 仅 `/admin/users` 一页 | 其余全部页面 |
| L4 能力门控 | `web/components/access/CapabilityGate.tsx:14-23` | `/api/settings` 探针 | llm 能力锁页 | 角色、learner 面 |
| L5 导航可见性 | `web/components/sidebar/nav-entries.ts:35-69` | role + llm 标记 | 入口显隐/锁样式 | 数据访问（纯展示层） |
| S 服务端兜底 | `deeptutor/api/routers/auth.py:689-703` | JWT + role + `allowed_surfaces` | 数据级 401/403 | 前端体验 |

关键认知: L1–L5 没有一层理解"learner 面"。客户端模型是 **admin / 非 admin + llm 能力** 的二元模型；服务端模型是 **`allowed_surfaces` 默认拒绝** 的面模型。两侧不对应是全部 10 项不一致的根因。

## 一、L1 中间件认证门（`web/proxy.ts`）

- 管: `AUTH_ENABLED` 时对所有非豁免**页面**路径校验 `dt_token`（`classifyToken`），无效重定向 `/login` 并保留 `next`（`web/proxy.ts:82-91`）。
- 不管: `/api/*`、`/ws/*` 原样 rewrite 到后端、不判角色（`web/proxy.ts:67-76`）；登录后的"你是谁"完全不在本层——learner 与 standard 可打开任何页面路径。
- 记法: L1 只回答"有没有票"，不回答"能进哪个厅"。

## 二、L2 客户端 401 处理（`web/shared/api/client.ts`）

- 管: `apiFetch` 对 401（且 runtimeAuthEnabled）整页跳 `/login`（`web/shared/api/client.ts:38-46`）。
- 不管: **403 无任何全局分支**，原样返回调用方——报错、空态还是吞掉，全看各调用方自觉（这是 #1228 空态伪装的土壤）。
- 身份来源: `/api/auth/status` 有 5 秒缓存（`web/lib/auth.ts:49-81`），payload 携带 `role`、`preset`、`learning_policy.allowed_surfaces`（`web/lib/auth.ts:21-32`）。policy 到了客户端，但全仓只有 `/admin/users` 消费 `role`，无人消费 `allowed_surfaces`（#1222 论断）。

## 三、L3 页面级角色守卫（仅一处）

- 管: `(admin)/admin/users` 一页自检：未认证 → `/login`，非 admin → `/`（`web/app/(admin)/admin/users/page.tsx:100-112`）。
- 不管: `(admin)/layout.tsx:1-7` 是纯 div 无守卫，组内新增页面若忘记自检即裸奔（风险项 F10）；`(workspace)`、`(utility)`、`(settings)` 布局只挂 `CapabilityGate`，无角色/面守卫。
- 记法: 角色守卫是"页面自选动作"，不是组级契约。

## 四、L4 能力门控（llm，非角色）

- 管: 路由→能力映射仅 4 条 `/chat`、`/partners`、`/co-writer`、`/learning`（`web/lib/capability-routes.ts:19-27`）；`CapabilityGate` 按 pathname 锁页，缺能力渲染"Feature locked"而非隐藏入口（`web/components/access/CapabilityGate.tsx:14-23`、`web/components/access/RequireCapability.tsx:47-58`）。
- 判据链: 探针 `GET /api/settings`——响应含 `catalog` 视为 admin；否则按 `/api/settings/llm-options` 选项数定 `hasLlm`（`web/components/access/CapabilityAccessContext.tsx:58-79`）。
- 不管: `has()` 只回答"有没有 llm"（`web/components/access/CapabilityAccessContext.tsx:101-108`）。两个坑: ① 初始乐观态 `isAdmin/hasLlm = true`（`web/components/access/CapabilityAccessContext.tsx:52-55`），探针 403 时 `if (!res.ok) return` 早退、乐观态永不重置 → learner 永不锁（F5）；② 探针端点本身不在 learner 白名单，403 是 learner 的常态而非异常。
- 记法: L4 是"模型能力门"，不是"人员权限门"。

## 五、L5 导航可见性（装饰层）

- 管: 主导航 7 项 + 设置，无角色/面过滤，仅 `requires: 'llm'` 标记（`web/components/sidebar/nav-entries.ts:35-69`）；缺能力 = 锁样式，入口仍渲染（`web/components/sidebar/SidebarNav.tsx:188-191`、`:532`）。`AdminLink` 是唯一按角色隐藏的入口（`web/components/auth/AdminLink.tsx:19`）。设置页用 `hideAdminOnly / showLearnerOnly / showGuardianOnly` 三布尔过滤（`web/features/settings/navigation/settings-access.ts:22-40`），实际只过滤标了 `adminOnly` 的叶子（`web/features/settings/navigation/settings-nav.ts:88-105`）。
- 不管: 隐藏 ≠ 无权限，显示 ≠ 可访问。learner 打开设置页会看到大量"可见但必 403"的 section（F7）。
- 记法: L5 只决定"看得见什么"，永远不构成安全边界。

## 六、S 服务端基线与 learner 面叠加

- 依赖链: `require_auth` 401（`deeptutor/api/routers/auth.py:419-465`）→ `require_admin` 403（`deeptutor/api/routers/auth.py:573-593`）→ `require_learning_surface`（`deeptutor/api/routers/auth.py:689-703`）→ `assert_learning_surface`（`deeptutor/multi_user/learning_access.py:63-70`）。
- 生效条件: 仅当账号带 `learning_policy`（learner 预设）才启用；面不在 `allowed_surfaces` 即 403。默认授权 `["chat", "reading"]`（`deeptutor/multi_user/grants.py:206`）。standard/custom 无 policy，面检查直接放行。
- 路径→面映射: `deeptutor/api/routers/auth.py:633-672`——`/api/reading`、`/api/courses`、materials/reading 库→reading；`/api/books`、books 库→books；`/api/chat`、`/api/question*`、`/api/sessions`、`/api/task-board`、`/api/mastery-paths`→chat；KB 只读模板→reading；learner 自有设置写模板→chat；**其余一律空面 → 默认拒绝**。
- 挂载差异（`deeptutor/api/main.py`）: auth 路由公开（`deeptutor/api/main.py:575`）；`file_preview` 仅 `require_auth`（`deeptutor/api/main.py:606-610`）；其余业务路由统一 `_auth = require_learning_surface`（`deeptutor/api/main.py:591`、`:597-786`）；settings 的 ui 读公开（`deeptutor/api/main.py:683`）、门控组 `deeptutor/api/main.py:687`；WS 不走依赖、handler 内认证、无面检查（`deeptutor/api/main.py:782-787`）。
- 叠加方式: L1–L5 放行页面 → 页面发 API → S 按面 403 → 最终体验取决于该调用方的错误分支（显式报错 / 空态 / 静默吞掉）。

## 七、根因: 两端模型不对应 → 10 项不一致

一句话: **前端从不读 `learning_policy.allowed_surfaces`，服务端默认拒绝；于是每个"L1–L5 放行 × S 拒绝"的组合都落成一处不一致**。#1228 是现象（403 渲染成空态），#1222 是机制（policy 已下发但无人消费），F1–F10 是 v1.6.13 的逐点定位。

| # | 级别 | 一句话 | 首要锚点 |
|---|---|---|---|
| F1 | 高 | 默认授权不含 books，学习中心却把 Books 作为第一入口，三侧互相矛盾（需产品决策） | `deeptutor/multi_user/grants.py:206` vs `web/components/learning/surfaces.ts:20-42` |
| F2 | 高 | `learning-index` 不在白名单，learner 进 `/learning` 固定报错横幅 | `web/components/learning/LearningDashboard.tsx:52-57` |
| F3 | 高 | `watching` 库列表不在白名单，`/learning/watching` 固定报错 | `web/lib/learning-library.ts:11-14` |
| F4 | 中 | 403 空态伪装 5 处: partners、agents、space 计数、memory 总览（无 `res.ok` 检查，最重）、chat 建议 | `web/app/(workspace)/partners/page.tsx:49-50`、`web/components/memory/MemoryHub.tsx:61-66` |
| F5 | 中 | 能力探针对 learner 必 403，乐观态永不重置，门控恒开 | `web/components/access/CapabilityAccessContext.tsx:52-55`、`:63` |
| F6 | 中 | 为非管理员设计的 `llm-options` 不在白名单，learner 模型列表空 | `deeptutor/api/routers/settings.py:892-898` |
| F7 | 中 | 设置页 admin/非 admin 模型 ≠ 服务端面模型，大量"可见但必坏"入口 | `web/features/settings/navigation/settings-access.ts:22-40` |
| F8 | 低 | chat 附件限额与 `/files/attachments` 读不在白名单，learner 附件断链 | `deeptutor/api/routers/attachments.py:40` |
| F9 | 低 | WS 层无面检查，与 HTTP 面不对称 | `deeptutor/api/main.py:782-787` |
| F10 | 低 | `(admin)` 组布局无守卫，角色检查是页面单点 | `web/app/(admin)/layout.tsx:1-7` |

正面样例（修复对齐目标，同在基线内）: `/api/courses` 走 `expectJson` 非 2xx 抛 `ApiError`（`web/lib/courses-api.ts:131-150`，#1231）；`ActivityLibrary` 有显式错误态。

## 八、谁能看到什么（速查表）

| 身份 | 可打开的页面 | 主导航/入口 | 数据面（S 层实际放行） |
|---|---|---|---|
| 未登录 | 仅豁免页，其余被 L1 弹到 `/login` | — | 仅公开 auth 路由（`deeptutor/api/main.py:575`） |
| admin | 全部 | 全部 7 项 + AdminLink + 全部设置；无锁 | 全部数据；`require_admin` 组内接口也过 |
| standard/custom | 除 `/admin/users`（弹回）外全部 | 7 项全显示；无 AdminLink；guardian 设置可见；llm 项按真实授予可锁 | 面检查不生效（无 policy），数据访问接近 admin |
| learner（默认） | 除 `/admin/users`（弹回）外**全部可打开** | 7 项全显示；llm 项因 F5 永不锁；设置页大量入口可见 | 仅 `chat`/`reading` 面 + KB 只读 + 自有设置写；books、watching、learning-index、llm-options、设置多数 section、附件 → 403 |

读表要点: "可打开"是 L1 给的，"可见"是 L5 给的，"数据面"是 S 给的——三列不一致的每一格就是一个 F 项。

## 九、按意图的阅读路径

- 改前端一致性: 从 L2 的"403 无全局分支"入手，统一到 `expectJson`/显式错误态模式（`web/lib/courses-api.ts:131-150`），并补"403 不渲染空态"契约测试。
- 改授权模型: 从 `deeptutor/multi_user/grants.py:192-214` 与 `deeptutor/api/routers/auth.py:633-672` 白名单入手；先在 #1228 决定"逐条加白 vs 显式 learner 面清单"方向。
- 让前端消费 policy: `/api/auth/status` 已带 `learning_policy.allowed_surfaces`（`web/lib/auth.ts:21-32`），可用于折叠入口/过滤设置页（F1/F2/F5/F7 一并回应 #1222）。
- 新增 admin 页面: 把角色守卫上收到 `(admin)/layout.tsx`（F10），别依赖页面自觉。
- 加新 WS 能力: 记住 WS 只有认证没有面检查（F9），敏感操作需在 handler 内自查。
