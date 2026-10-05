# web/ 前端代码导读（chat / reading / knowledge / settings）

基线：HKUDS/DeepTutor `origin/main` @ `f07029cfc`（release v1.6.13）。本文所有 `path:line` 均相对仓库根目录、对应该提交，可按 `path` 直接跳转、按 `line` 定位。本文只读导读，不修改任何代码。

技术栈：Next.js 16（App Router，middleware 已更名为 `proxy.ts`）+ React 19 + TypeScript + Tailwind + i18next；无 Redux/Zustand，状态全部由 React Context + useReducer + 专项 hooks 承担（`web/package.json:23-45`）。

---

## 1. 总览：目录结构与架构对照表

```
web/
├── app/                  # Next App Router：路由与路由组（薄壳，页面逻辑下沉）
│   ├── layout.tsx        # 根布局：全局 Provider 栈
│   ├── (workspace)/      # 主工作区：chat / learning(reading/books/mastery/watching) / co-writer / partners
│   ├── (utility)/        # 工具页：knowledge-bases / space / memory / courses / notebooks ...
│   ├── (settings)/       # 设置：/settings 与 /settings/[section]
│   ├── (auth)/           # login / register
│   ├── (admin)/          # 管理员用户管理
│   └── api/              # 少量 BFF 路由（仅 multipart 透传，见 §6.2）
├── features/             # 领域模块：chat / co-writer / knowledge / settings / runtime-status / multi-user / capabilities
│   └── <f>/{api,components,controllers,model,store,transport,selectors}/
├── components/           # 页面级组件（按域分目录）：reading / knowledge / settings / sidebar / layout / chat ...
├── context/              # 跨页 React Context：AppShell / Reading / Watching / QuizFollowup / GeogebraTab
├── hooks/                # 通用数据/交互 hooks（useKnowledgeBases、useComposerResources ...）
├── lib/                  # 无 UI 依赖的纯逻辑：*-api.ts 客户端、路由常量、缓存、通知等
├── shared/               # 最底层公共件：api/client、ui/、storage/（依赖方向受 depcruise 约束）
├── contracts/            # 后端契约：schema/（源）→ generated/（openapi-typescript 产物）
├── i18n/ + locales/      # i18next 初始化与 en/zh/fr/de/uk/pl 文案包
├── proxy.ts              # Next 16 middleware：/api、/ws、/files 改写 + 登录门
├── next.config.js        # 环境装配、redirect、standalone 输出
├── scripts/              # dev/build/契约生成/i18n 校验/测试跑批的 node 包装
└── tests/                # .test.ts（node harness）+ .spec.tsx（vitest+jsdom）+ e2e/*.audit.ts（playwright）
```

架构分层与强约束（`web/.dependency-cruiser.cjs:3-40`，`npm run architecture:check` 强制）：

| 层 | 允许依赖 | 禁止 | 规则名 |
| --- | --- | --- | --- |
| `contracts/` | 仅自身 | 依赖其他任何层 | `contracts-are-leaves` |
| `shared/` | 自身、lib、hooks | app/components/context/features | `shared-does-not-depend-up` |
| `lib/` | shared/hooks/lib | app/components/context（不得引 UI） | `lib-does-not-depend-on-ui` |
| `features/*/model|store|transport` | lib/shared/contracts | app/components/context（不得渲染） | `feature-domain-does-not-render` |
| 任意层 | — | import 任何 `**/page.tsx` | `no-route-page-imports` |
| 全局 | — | 循环依赖 | `no-circular` |

---

## 2. 应用入口与路由

### 2.1 根布局与全局 Provider 栈

- 根布局 `web/app/layout.tsx:38-67`：`<html>` → `ThemeScript`（首帧防闪烁，`web/app/layout.tsx:50-52`）→ body 内依次挂 `AppShellProvider`（`web/app/layout.tsx:57`）、`SettingsReturnTracker`（`:58`）、`WorkspaceNavigation`（顶部导航，`:59`）、`MotionProvider`（`:60`）、`I18nClientBridge`（包住 children，`:61`）、`ToastViewport`（`:63`）。
- `AppShellProvider` 定义在 `web/context/AppShellContext.tsx:77`，对外值接口见 `web/context/AppShellContext.tsx:57-73`（theme / language / activeSessionId / sidebarCollapsed / codeBlock 三项），消费入口 `useAppShell()` 在 `web/context/AppShellContext.tsx:355-361`。

### 2.2 路由组（Route Groups）与壳

| 路由组 | 壳（layout） | 内容 |
| --- | --- | --- |
| `(workspace)` | `web/app/(workspace)/layout.tsx:16-35` | CapabilityAccessProvider → WorkspaceRuntimeBoundary → ChatRuntimeProvider → ReadingProvider → WatchingProvider → AppShell(WorkspaceSidebar) → CapabilityGate |
| `(utility)` | `web/app/(utility)/layout.tsx:9-18` | CapabilityAccessProvider → AppShell(UtilitySidebar) → CapabilityGate |
| `(settings)` | `web/app/(settings)/settings/layout.tsx:10-24` | SettingsProvider → SettingsAccessProvider → UiSettingsProvider → ModelCatalogProvider → SettingsDraftProvider → SettingsMain |
| `(auth)` | `web/app/(auth)/layout.tsx` | login/register，无工作区壳 |
| `(admin)` | `web/app/(admin)/layout.tsx` | 管理员页 |

路由重定向集中在 `web/next.config.js:144-160`：`/` → `/chat`（`:151`）、旧 `/mastery|books|reading|watching` 路径 301 到 `/learning/...`（`:152-158`）；`web/app/(workspace)/page.tsx:8-10` 只作兜底 redirect。

### 2.3 请求级入口：proxy（原 middleware）

- 入口函数 `web/proxy.ts:51`；配置与 matcher `web/proxy.ts:94-108`（matcher 排除 `_next`、favicon 与 knowledge-bases multipart 路由，`:106-108`）。
- 三段职责：
  1. Codex OAuth 回调改写 `web/proxy.ts:54-58`；
  2. 后端路径改写 `/api/*`、`/ws*`、`/files/*` → FastAPI（判定 `web/lib/proxy-policy.ts:29-40`，执行 `web/proxy.ts:67-76`）；
  3. 多用户登录门（默认关）：`web/proxy.ts:82-91`，豁免清单 `web/lib/proxy-policy.ts:53-66`，cookie `dt_token`（`web/lib/proxy-policy.ts:11`）的"无签名预检"分类器 `classifyToken`（`web/lib/proxy-policy.ts:70`，真实校验在后端）。
- 后端地址解析链：`web/lib/backend-runtime-config.ts:11-26`（`DEEPTUTOR_API_BASE_URL` → `BACKEND_PORT` 重建 loopback → `NEXT_PUBLIC_API_BASE` → `http://127.0.0.1:8001`）；转发头清洗（剥离 hop-by-hop 与伪造 forwarded 头，回写 `x-deeptutor-frontend-host`）见 `web/lib/backend-forward.ts:19-49`。

---

## 3. 状态管理

无全局状态库，按作用域分四层：

| 作用域 | 载体 | 定义/入口 |
| --- | --- | --- |
| 全应用壳（主题/语言/侧栏/代码块偏好/activeSession） | `AppShellContext` | Provider `web/context/AppShellContext.tsx:77`，接口 `:57-73` |
| 工作区会话运行时（chat 状态机） | `ChatStateAdapter`（useReducer） | state 形状 `web/features/chat/ChatStateAdapter.tsx:173`，动作接口 `:1492`，Provider `:1790`（`useReducer` 于 `:1795`），消费 `useChatStateAdapter()` `:3703` |
| 设置域（模型目录/ui settings/草稿） | settings store | `SettingsProvider` `web/features/settings/store/SettingsStore.tsx:626`，`useSettings()` `:616`，UiSettings 类型 `:89`，持久化 `persistUiSettingsPatch` `:150` |
| 页面域（阅读/观看/测验追问等） | 专项 Context | `ReadingProvider` `web/context/ReadingContext.tsx:91`（`useReading` `:263`）、`WatchingProvider` `web/context/WatchingContext.tsx:49`（`useWatching` `:208`），另有 `context/QuizFollowupContext.tsx`、`context/GeogebraTabContext.tsx` |

要点：

1. **单一运行时约束**：`ChatRuntimeProvider` 禁止嵌套，保证一条路由子树只有一个 turn 运行时（`web/features/chat/ChatRuntimeProvider.tsx:9-22`），挂载点在工作区 layout（`web/app/(workspace)/layout.tsx:20`）。
2. **SSR 水合纪律**：偏好类 state 先用与 SSR 一致的默认值，mount 后从 localStorage 水合（`web/context/AppShellContext.tsx:98-104`）；语言额外做一次 `/api/settings/ui` 兜底拉取（`:106-182`，1.5s 超时 `:136-139`）。
3. **跨标签同步**：偏好通过 `storage` 事件 + 自定义 window 事件双通道同步（`web/context/AppShellContext.tsx:190-272`），存储键集中在 `web/context/app-shell-storage.ts`。
4. **工作区多租户参数**：所有 URL 经 `scopedUrl` 注入 `dt_workspace` 查询参数（`web/lib/workspace-scope.ts:8-19`）；切工作区走 `selectWorkspace`（`:30-55`，会等待 `deeptutor:before-workspace-switch` 事件排空后再导航）。
5. **数据 hooks**：跨页复用的拉取逻辑在 `web/hooks/`，例如 `useKnowledgeBases()`（`web/hooks/useKnowledgeBases.ts:60`）、`useSetupSync`、`useChatWorkspaces` 等。

---

## 4. API 客户端与错误呈现

### 4.1 统一 HTTP 客户端

核心在 `web/shared/api/client.ts`（旧入口 `web/lib/api.ts:5-6` 只是兼容再导出，已标注 deprecated）：

- URL 造器 `apiUrl`/`wsUrl`（`web/shared/api/client.ts:12-18`）：统一走 `scopedUrl` 注入工作区参数。
- `apiFetch`（`web/shared/api/client.ts:28-49`）：`credentials: "include"`；401 且启用登录时自动跳 `/login?next=...`（`:38-46`），返回 URL 计算在 `web/shared/auth/return-url.ts`。
- 错误归一化 `normalizedHttpError`（`web/shared/api/client.ts:74-109`）：提取 `error_code`/`detail.message`/`correlation_id`，默认重试判定 408/429/5xx（`:91-95`）。
- 三个对外原语：`requestJson<T>`（`:150-166`，非 JSON 响应抛 `invalid_response`）、`requestVoid`（`:168-173`）、`requestBlob`（`:175-203`）；网络层异常统一包成 `ApiError`（`performRequest` `:121-148`）。
- 错误类型 `AppError`/`ApiError`：`web/shared/api/errors.ts:8-15` 与 `:17-41`（`code/message/retryable/scope/correlationId/status`），守卫 `isApiError` `:43-45`；`scope` 枚举 turn/session/runtime/settings/network（`:1-6`）。
- 遗留直连帮手 `asJsonOrThrow`（`web/shared/api/client.ts:212-224`）：只抛 FastAPI `detail` 字符串，新代码优先用三原语。

### 4.2 类型契约（前端不手写后端类型）

- 源：`web/contracts/schema/openapi.json`（由后端 `deeptutor/api/contracts/export.py` 导出）与 `turn-protocol.json`。
- 生成：`npm run contracts:generate`（`web/scripts/generate-contracts.mjs:11-46`，openapi-typescript + json-schema-to-typescript），产物 `web/contracts/generated/api.ts`、`web/contracts/generated/turn-protocol.ts`；漂移检查 `npm run contracts:check` 已并入 `check:fast`（`web/package.json:19`）。

### 4.3 领域 API 模块的组织

- 会话/消息：`web/lib/session-api.ts`（如 `listSessions` `:199`、`getSession` `:298`、`updateSessionTitle` `:334`），配合缓存 `web/lib/client-cache.ts` 与变更广播 `web/lib/session-events.ts`。
- 知识库：集中在 `web/features/knowledge/api/`（`client.ts` 主文件 1898 行，内部再包一层按页面注入 `resource_library=true` 的 `apiUrl`，`web/features/knowledge/api/client.ts:12-18`；分文件 catalog/engines/files/folders/sources）。
- 其余域各自 `web/lib/<domain>-api.ts`（learning、notebook、partners、subagents、tasks 等，全目录见 §9）。

### 4.4 实时通道（turn WebSocket）

- `UnifiedTurnClient`（`web/features/chat/transport/UnifiedTurnClient.ts:93`）：`connect` `:123`、`send` `:127`、`sendAwaitingAck` `:132`、`disconnect` `:136`；把运行时事件映射为 `StreamEvent`（`:40-83`）。
- `TurnRuntimeClient`（`web/features/chat/transport/TurnRuntimeClient.ts:94`）：重连、命令 ACK 超时、resume 游标、乱序缓冲，默认 `url: scopedUrl("/ws")`（`:133`）；socket 抽象 `web/features/chat/transport/socket.ts:20`，退避策略 `web/features/chat/transport/reconnect-policy.ts:5-30`。

### 4.5 错误呈现链路

| 场景 | 机制 | 位置 |
| --- | --- | --- |
| 一次性操作反馈 | `notify(message, {tone})` 发布，`ToastViewport` 订阅渲染 | 发布 `web/lib/notifications.ts:30`/`:51`；视口 `web/components/common/ToastViewport.tsx:18`（挂载于 `web/app/layout.tsx:63`） |
| 表单/面板内常驻错误 | `InlineAlert` | `web/shared/ui/InlineAlert.tsx:26` |
| 会话列表加载失败等页面级 | 各域组件消费 `ApiError` 的 `code/retryable` 决定重试按钮 | 例：`web/lib/reading-failure.ts`、`web/lib/book-errors.ts` |
| turn 协议不匹配 | `ProtocolMismatchNotice` | `web/features/chat/components/turn/ProtocolMismatchNotice.tsx` |
| 契约漂移 | CI 阶段直接失败 | `npm run contracts:check`（`web/package.json:18`） |

---

## 5. 主要页面组件分层

四个代表域的调用链（路由 → 页面壳 → 组件 → 数据层）：

### 5.1 chat

1. 路由：`web/app/(workspace)/chat/page.tsx:3-5` 与 `web/app/(workspace)/chat/[sessionId]/page.tsx`（各 5 行薄壳）。
2. 组件：`ChatWorkspace`（`web/features/chat/components/ChatWorkspace.tsx:262`）——从 `useChatRouteSession`（`web/features/chat/controllers/useChatRouteSession.ts:24`）取路由 sessionId，从 `useChatStateAdapter` 取完整会话状态与动作（`sendMessage/regenerateLastMessage/editMessage/switchBranch/...`，`web/features/chat/components/ChatWorkspace.tsx:278` 起的解构块）。
3. 子层：`features/chat/{controllers,transport,messages,trace,selectors,model}/`（目录见 §9）；状态机与运行时见 §3。
4. 会话列表侧栏：`web/components/SessionList.tsx`，条目分组逻辑 `buildSidebarEntries`（`web/lib/sidebar-entries.ts:140`）。

### 5.2 reading（learning/reading）

1. 路由：`web/app/(workspace)/learning/reading/[workspaceId]/page.tsx:3-5`（另有 sessions/folders/materials 兄弟路由）。
2. 组件：`ReadingWorkspacePage`（`web/components/reading/workspace/ReadingWorkspace.tsx:127`）。
3. 状态：`ReadingProvider` 挂在工作区 layout（`web/app/(workspace)/layout.tsx:24`），跨 chat↔reading 导航不卸载（layout 注释 `:21-23`）。
4. 数据/逻辑：`web/lib/reading-*.ts` 约 20 个模块（API `reading-workspace-api.ts`、选区 `reading-selection.ts`、标注 `reading-w3c-annotations.ts`、引用 `reading-citations.ts` 等）；学习域路由常量集中在 `web/lib/learning-routes.ts:6-12`。

### 5.3 knowledge

1. 路由：`web/app/(utility)/knowledge-bases/page.tsx:6-16`（Suspense 包裹）与 `[kbName]/page.tsx`。
2. 组件：`KnowledgePage`（`web/components/knowledge/KnowledgePage.tsx:50`）。
3. 数据：`web/features/knowledge/api/client.ts` + 同目录分文件；hook `useKnowledgeBases`（`web/hooks/useKnowledgeBases.ts:60`）。
4. 大文件上传不走 proxy（见 §6.2 matcher 豁免），由 App Router 透传路由承担：`web/app/api/knowledge-bases/route.ts:6-12` → `forwardBackendUpload`（`web/lib/streaming-upload-proxy.ts:53`）。

### 5.4 settings

1. 路由：hub `web/app/(settings)/settings/page.tsx:9-28`（客户端把旧 hash 书签解析到新路由，`legacySettingsDestination` 在 `web/features/settings/navigation/settings-pages.ts:158`）；分区页 `web/app/(settings)/settings/[section]/page.tsx:5-10`。
2. 组件：`SettingsMain`（`web/components/settings/SettingsMain.tsx:16`）、分区渲染 `SettingsPageContent`（`web/components/settings/SettingsPageContent.tsx:216`）；具体分区实现在 `web/features/settings/sections/`（30+ 个 *SettingsSection.tsx）。
3. 状态：四层 Provider（§2.2 表格）；页面注册表 `SETTINGS_PAGE_GROUPS`（`web/features/settings/navigation/settings-pages.ts:13`）、可见性过滤 `visibleSettingsPages`（`:122`）；能力门 `web/features/settings/navigation/SettingsAccessProvider.tsx`。
4. 能力门控数据源：`ROUTE_CAPABILITIES`（`web/lib/capability-routes.ts:17-23`）——侧栏置灰与路由级 `CapabilityGate`（`web/components/access/CapabilityGate.tsx:14`）共用这一份映射，`capabilityForPath`（`web/lib/capability-routes.ts:34`）做段边界匹配。

---

## 6. 构建与代理配置

### 6.1 环境与构建

- **环境装配在 next.config.js 完成**（`web/next.config.js:47-76`）：读 `data/user/settings/system.json`、`auth.json` 作为前端事实源，合成 `NEXT_PUBLIC_API_BASE`（优先级 `:58-64`）与 `NEXT_PUBLIC_AUTH_ENABLED`（`:66-73`）；版本号从 `deeptutor/__version__.py` 正则提取（`:81-91`）。
- 产物：`output: "standalone"`（`web/next.config.js:116`），输出根固定 `:122`；distDir 可用 `DEEPTUTOR_NEXT_DIST_DIR` 分离 dev/prod 缓存（`:98`）。
- 开发服务器包装 `web/scripts/dev.mjs`：给 Next 渲染 worker 设 V8 堆顶（`HEAP_CEILING_MB` `:30`，注入 NODE_OPTIONS 后 `:55` spawn `next dev`），信号透传防孤儿进程（`:63-69`）。
- 构建包装 `web/scripts/build.mjs`：构建前快照 Next 会改写的生成文件（`generatedPaths` `:27`，`snapshot` `:32`/`restoreAll` `:40`），结束后恢复（`:121`）；并用进程级 tsconfig 隔离生产构建（`prepareBuildTsconfig` `:44`，配合 `web/next.config.js:102-104`）。
- 路径别名 `@/* → web/*`（`web/tsconfig.json:21-23`）；Turbopack/Webpack 双轨兼容配置（`web/next.config.js:177-200`，含 en locale 精简 loader `:187-191`）。
- 本机局域网联调：`allowedDevOrigins` 自动探测本机 IPv4（`web/next.config.js:35-45` 与 `:174`），否则手机访问会出现"SSR 有内容但无交互"。

### 6.2 代理（proxy.ts）

- 改写目标与来源见 §2.3；超时/体积预算在 `web/next.config.js:128-133`（`proxyTimeout` 30 分钟、`proxyClientMaxBodySize` 210MB，供 `proxy.ts` 克隆请求体用）。
- **multipart 豁免**：knowledge-bases 创建/上传请求被 matcher 排除（`web/proxy.ts:106-108`），由 `web/app/api/knowledge-bases/route.ts:6-12` 这类 route handler 流式透传，避免 Next 进入 middleware 就克隆整个 body。
- 转发头卫生：剥离 `x-forwarded-*` 等不可信头、保留 WebSocket upgrade（`web/lib/backend-forward.ts:19-49`，豁免表 `:3-17`）。

### 6.3 质量闸门（单卡验收命令）

`npm run check:fast`（`web/package.json:19`）= `contracts:check`（契约漂移，`:18`）→ `architecture:check`（depcruise 分层，`:27`）→ `typecheck`（`:13`）→ `test:node`（纯 node 测试，`:14`）→ `test:unit`（vitest+jsdom，`:15`，只跑 `tests/**/*.spec.ts(x)`，配置 `web/vitest.config.mts:13-20`）→ `lint`（`:12`）→ `i18n:check`（parity+audit，`:26`）。完整 `npm run check` 再加 `build` 与路由体积预算 `perf:check`（`web/package.json:21`）。浏览器审计/e2e 用 playwright（`web/package.json:28`，`testDir: web/tests`，`web/playwright.config.ts:10-20`）。

---

## 7. 新增一个页面需要改哪些文件（清单）

以在工作区加 `/my-page` 为例，按顺序：

| # | 文件/动作 | 说明 |
| --- | --- | --- |
| 1 | `web/app/(workspace)/my-page/page.tsx`（新建） | 路由薄壳：`import` 页面组件并默认导出（范式见 `web/app/(workspace)/chat/page.tsx:3-5`）。选路由组即选壳：带侧栏用 `(workspace)`，工具页用 `(utility)`，设置页用 `(settings)` |
| 2 | `web/components/<domain>/MyPage.tsx`（或 `web/features/<feature>/components/`） | 页面实体。注意 depcruise 规则 `no-route-page-imports`（`web/.dependency-cruiser.cjs:37-41`）：任何文件不得 import `page.tsx`，逻辑必须放进组件 |
| 3 | `web/lib/capability-routes.ts:17-23` | 仅当页面依赖 LLM：往 `ROUTE_CAPABILITIES` 加 `{prefix: "/my-page", capability: "llm"}`，侧栏与 CapabilityGate 自动生效（读取方 `web/lib/capability-routes.ts:34`） |
| 4 | `web/components/sidebar/WorkspaceSidebar.tsx:37`（或 `UtilitySidebar.tsx`） | 加导航入口；工作区跳转一律走 `web/lib/learning-routes.ts` 风格的路由构造函数，勿手拼 URL |
| 5 | `web/lib/my-domain-api.ts`（新建） | API 客户端函数（见 §8），不要在组件里裸 `fetch` |
| 6 | `web/locales/{en,zh,fr,de,uk,pl}/app.json` | 六个语言包都加 key；`npm run i18n:check`（`web/package.json:26`）会卡 parity/审计 |
| 7 | `web/tests/my-page.test.ts` 或 `.spec.tsx` | 纯逻辑用 `.test.ts`（node harness），渲染交互用 `.spec.tsx`（vitest+jsdom，include 见 `web/vitest.config.mts:19`）；e2e 放 `web/tests/e2e/` |
| 8 | 如需新 Context | 放 `web/context/`，并在对应路由组 layout 挂 Provider（范式 `web/app/(workspace)/layout.tsx:16-35`） |
| 9 | 验证 | `cd web && npm run check:fast`（`web/package.json:19`） |

## 8. 接一个新 API 需要改哪些文件（清单）

| # | 文件/动作 | 说明 |
| --- | --- | --- |
| 1 | 后端导出 OpenAPI → `web/contracts/schema/openapi.json` | 导出器 `deeptutor/api/contracts/export.py`；随后 `npm run contracts:generate` 重新生成 `web/contracts/generated/api.ts`（`web/scripts/generate-contracts.mjs:11-46`），类型从这里 import，不手写 |
| 2 | `web/lib/<domain>-api.ts`（或 `web/features/<feature>/api/`） | 用 `requestJson/requestVoid/requestBlob`（`web/shared/api/client.ts:150/168/175`）+ `apiUrl`（`:12`）；从 `@/shared/api/client` import，勿用已废弃的 `web/lib/api.ts:5-6` |
| 3 | 错误处理 | 调用侧 `catch (e)` 判 `isApiError`（`web/shared/api/errors.ts:43`），按 `e.retryable/e.code` 决定 UI，呈现用 `notify()`（`web/lib/notifications.ts:30`）或 `InlineAlert`（`web/shared/ui/InlineAlert.tsx:26`） |
| 4 | `web/lib/proxy-policy.ts:29-40` | 仅当后端新增 `/api`、`/ws`、`/files` 之外的前缀：扩 `isBackendPath`，否则请求不会改写到 FastAPI |
| 5 | 大文件上传 | 新建 `web/app/api/<path>/route.ts` 调 `forwardBackendUpload`（`web/lib/streaming-upload-proxy.ts:53`），并把该路径加进 `web/proxy.ts:106-108` matcher 豁免，避免 proxy 克隆 body |
| 6 | WebSocket | 复用 `UnifiedTurnClient`/`TurnRuntimeClient`（`web/features/chat/transport/UnifiedTurnClient.ts:93`），新端点参考其 `scopedUrl("/ws")` 默认值（`TurnRuntimeClient.ts:133`） |
| 7 | 缓存与失效 | 列表类数据用 `web/lib/client-cache.ts` 的 `withClientCache`/`invalidateClientCache`（用法见 `web/lib/session-api.ts:210`） |
| 8 | 验证 | `npm run contracts:check && npm run check:fast` |

---

## 9. 目录与公共接口速查

**公共 API（最常用导出）**

| 模块 | 导出 | 位置 |
| --- | --- | --- |
| `web/shared/api/client.ts` | `apiUrl` `wsUrl` `apiFetch` `requestJson` `requestVoid` `requestBlob` `asJsonOrThrow` `parseAuthEnabled` | `:12 :16 :28 :150 :168 :175 :212 :20` |
| `web/shared/api/errors.ts` | `AppError` `ApiError` `isApiError` | `:8 :17 :43` |
| `web/context/AppShellContext.tsx` | `AppShellProvider` `useAppShell` | `:77 :355` |
| `web/features/chat` | `ChatRuntimeProvider` `ChatStateAdapterProvider` `useChatStateAdapter` `hydrateMessageAttachments` | `ChatRuntimeProvider.tsx:9`、`ChatStateAdapter.tsx:1790 :3703 :1585` |
| `web/features/chat/transport` | `UnifiedTurnClient` `TurnRuntimeClient` `browserSocketFactory` `reconnectDelay` `shouldReconnect` | `UnifiedTurnClient.ts:93`、`TurnRuntimeClient.ts:94`、`socket.ts:20`、`reconnect-policy.ts:5 :17` |
| `web/features/settings/store` | `SettingsProvider` `useSettings` `UiSettingsProvider` `ModelCatalogProvider` `SettingsDraftProvider` | `index.ts:1-8` |
| `web/context/ReadingContext.tsx` / `WatchingContext.tsx` | `ReadingProvider`/`useReading`、`WatchingProvider`/`useWatching` | `:91 :263` / `:49 :208` |
| `web/lib/workspace-scope.ts` | `activeWorkspaceId` `scopedUrl` `selectWorkspace` `navigateTask` `registerWorkspaceNavigator` | `:2 :8 :30 :57 :25` |
| `web/lib/notifications.ts` | `notify` `subscribeNotifications` | `:30 :51` |
| `web/lib/capability-routes.ts` | `ROUTE_CAPABILITIES` `capabilityForPath` | `:17 :34` |
| `web/lib/learning-routes.ts` | `LEARNING_HUB` `BOOKS_HOME` `MASTERY_HOME` `READING_HOME` `WATCHING_HOME` + route 构造器 | `:6-12 :16-62` |
| `web/lib/session-api.ts` | `listSessions` `getSession` `updateSessionTitle` `getMessageTrace` 等 | `:199 :298 :334 :367` |
| `web/components/layout/AppShell.tsx` | `AppShell`（默认导出）`useSidebarDrawer` | `:50 :24` |
| `web/components/common/ToastViewport.tsx` | `ToastViewport`（默认导出） | `:18` |
| `web/shared/ui/` | Button/Dialog/EmptyState/Field/IconButton/InlineAlert/Skeleton/StatusChip/Tooltip | 目录桶导出 `web/shared/ui/index.ts` |

**lib/ 全量域客户端（新增 API 前先查重）**：account-role, admin-api, admin-users, book-api, chat-export, chat-import/, cli-apps-api, client-cache, co-writer-api, courses-api, guardian-api, imports-api, learning-api, learning-records-api, mcp-api, notebook-api, partners-api, partner-groups-api, personas-api, practice-api, profile-api, reading-api, reading-workspace-api, session-api, session-handoff-api, skills-api, subagents-api, task-board-api, video-learning-api, visualizers-api, workspaces-api（均在 `web/lib/` 下）。

**测试布局**：`web/tests/*.test.ts`（node，`npm run test:node`）、`web/tests/*.spec.tsx`（vitest，`npm run test:unit`）、`web/tests/e2e/*.audit.ts`（playwright `ui-audit` 项目，`npm run audit`）、fixtures/setup 在 `web/tests/fixtures`、`web/tests/setup/`。

---

## 10. 导读自身验证

- 本导读逐条 `path:line` 均在基线 `f07029cfc` 的检出上用 grep/sed 复核过行号。
- 未修改任何代码：除新增 `evidence/guide-frontend-20261004/` 外 `git status` 干净。
- 不适用运行测试（纯文档任务）；分层规则等结论以 `npm run architecture:check`、`npm run contracts:check` 的配置文件为证（引用见 §1、§6.3）。
