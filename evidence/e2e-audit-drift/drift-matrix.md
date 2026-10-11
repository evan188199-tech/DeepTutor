# web e2e audit 与界面漂移复核（静态复核）

- 基线：origin/main `6cf793bd8`（release: v1.6.14）
- 范围：`web/tests/e2e/*.audit.ts` 全部 11 个文件，逐文件核对引用的路由 / 组件 / 选择器 / testid / API 路径与 `web/app`、`web/components` 当前实现是否一致。
- 方法：仅静态对照（组件源码、locale、契约 `web/contracts/generated/api.ts`、`@recogito/text-annotator` 安装产物），未运行浏览器、未启动任何服务。

## 结论

11 个 audit 中 9 个与当前界面一致，无过期项；2 处过期项 + 1 处健壮性建议 + 1 条 e2e 目录之外的相邻发现。

| # | 文件 | 现状 | 主要建议 |
|---|------|------|----------|
| 1 | book-reader-sequential.audit.ts | 一致 | 无 |
| 2 | compliance-and-ux.audit.ts | 一致 | 无 |
| 3 | learning-progress.audit.ts | 一致 | 无 |
| 4 | turn-lifecycle.audit.ts | **1 处过期** | 移除/重写 "drop connection" 场景 |
| 5 | multi-worker-turns.audit.ts | 一致（依赖后端 fixture） | 无 |
| 6 | pdf-reading-resize.audit.ts | 一致 | 无 |
| 7 | reading-citation-material.audit.ts | 一致 | 无 |
| 8 | reading-location-history.audit.ts | 一致 | 无 |
| 9 | reading-w3c-annotations.audit.ts | 一致 | 无 |
| 10 | release-ui-matrix.audit.ts | **1 处漂移** | 默认端口 3300 → 3000 |
| 11 | settings-navigation.audit.ts | 一致 | 无 |

## 过期项明细

### 过期 1：turn-lifecycle.audit.ts:39 — 按钮 "drop connection" 无对应 UI

- 引用目标：`page.getByRole("button", { name: /drop connection/i }).click()`（"recovers without replacing the canonical activity surface" 用例）。
- 现状：全库检索 `drop connection`（组件、locale、全部代码）只命中该 audit 文件自身；`git log -S` 显示该字符串从未在 `web/` 组件代码中出现过。聊天侧当前没有任何"断开连接"用户控件（locale 中仅有 agents/partners 的 "Disconnect"，与 turn 恢复无关）。
- 影响：该文件由 `critical-turns` project 执行且默认被 `DEEPTUTOR_TURN_E2E_FIXTURE` 门禁跳过，属潜伏失败——一旦启用 fixture 跑到该用例即在此步超时。
- 建议二选一：
  1. 参照 `multi-worker-turns.audit.ts` 用 runtime fixture 的 `drop_socket` 动作驱动断线（推荐，UI 面不需要新增控件）；
  2. 若确需 UI 路径，先在聊天连接横幅中实现该按钮再恢复用例。

### 过期 2：release-ui-matrix.audit.ts:3 — 默认 BASE_URL 端口 3300 已漂移

- 引用目标：`const BASE_URL = process.env.WEB_BASE_URL || "http://127.0.0.1:3300"`。
- 现状：`web/playwright.config.ts` 与其余全部 audit 的默认值是 `http://localhost:3000`（`WEB_BASE_URL`/`NEXT_PUBLIC_API_BASE` 回退），CI（`.github/workflows/tests.yml:107`）注入的是 `http://127.0.0.1:3000`；仓库内再无 3300 端口引用（v1.6.3 引入时即如此）。该文件又是 audit 中唯一自带硬编码主机名的。
- 影响：仅本地不带 env 直跑该文件时会打到不存在的端口；CI 不受影响。
- 建议：默认值改为 `http://localhost:3000`，与 playwright.config.ts 同款回退链。

### 相邻发现（超出 e2e 目录，仅记录）

- `web/tests/epub-reader.audit.ts`（由 `epub-reader-chromium/-webkit` project 匹配，不在本卡 e2e 范围）："Source layout" 按钮（约 :65）在组件与 locale 中均不存在；"Open a document to read"、"On this page"、"Document contents" 仍有效。建议后续卡单独复核该文件。

### 健壮性建议（非漂移）

- `turn-lifecycle.audit.ts:24`、`multi-worker-turns.audit.ts:81` 的 `getByRole("textbox", { name: /answer/i })`：AskUserOptions 的自由文本 textarea（`web/components/chat/home/AskUserOptions.tsx:1476`）只有 placeholder、无 `aria-label`，accessible name 依赖浏览器对 placeholder 的回退与后端 fixture 提供的占位文本。建议给该 textarea 加 `aria-label={t("Answer")}`，同时改善无障碍语义。

## 逐文件核对记录

每文件一类条目：引用目标 → 现状锚点（file:line 均为当前 origin/main）。

### 1. book-reader-sequential.audit.ts

| 引用目标 | 现状 | 建议 |
|----------|------|------|
| 路由 `/books/{id}/pages/{pid}` | `next.config.js:144-157` 有 `/books/:path*` → `/learning/books/:path*` 301；页面 `web/app/(workspace)/learning/books/[bookId]/pages/[pageId]/page.tsx` 存在 | 无 |
| testid `chapter-scroll-container` / `chapter-progress` | `PageReader.tsx:553` / `PageReader.tsx:755` | 无 |
| 按钮 "Collapse chapters" | `BookSidebar.tsx:149-152`，默认 `collapsed=false`（:79），进页即可点 | 无 |
| 标题 heading = 章节 title | `PageReader.tsx:470` `<h1>` | 无 |
| API `/api/books`、`/api/books/{id}`、`/api/books/{id}/pages/{pid}`、`/progress/visit`、`/learning-captures` | `web/lib/book-api.ts`（BASE=`/api`，:114/:283/:454）一致 | 无 |

### 2. compliance-and-ux.audit.ts

| 引用目标 | 现状 | 建议 |
|----------|------|------|
| `/` → `<main>` + `<h1>` | `/` 301→`/chat`；`<main>` 在 `AppShell.tsx:102`；空会话欢迎态 `<h1>` 在 `ChatWorkspace.tsx:2510` | 无（h1 仅欢迎态渲染，本用例即空首页，语义一致） |
| `/notebooks` + 失败反馈 | `web/app/(utility)/notebooks/page.tsx`；错误 `role="alert"`（`NotebookConsole.tsx:524/740`）、空态 `data-test="notebooks-empty"`（:509）、`text=No notebooks` 子串命中 "No notebooks yet." | 无 |
| `img` alt / viewport meta | 常规静态检查，无路由/组件依赖 | 无 |

### 3. learning-progress.audit.ts

| 引用目标 | 现状 | 建议 |
|----------|------|------|
| 路由 `/settings/progress` | 静态路由 `web/app/(utility)/settings/progress/page.tsx`（优先于 `(settings)/settings/[section]` 动态段） | 无 |
| heading "Learning progress" | `page.tsx:42` PageHeader（FeaturePage h1/h2，`FeaturePage.tsx:78-83`） | 无 |
| API `/api/mastery-paths/reading/records` | `web/lib/learning-records-api.ts:28`；旧 `/api/v1/learning/records` 全库无引用（断言 `not.toContain` 成立） | 无 |
| 进度条 `aria-valuenow`、活动行 "action · extension_id · Locator N" | `page.tsx:80`（furthest_percentage×100=50）、`page.tsx:104-106` | 无 |

### 4. turn-lifecycle.audit.ts

| 引用目标 | 现状 | 建议 |
|----------|------|------|
| fixtures `./fixtures/runtime`（sendPrompt/assistantActivity） | `web/tests/e2e/fixtures/runtime.ts` 完整导出 | 无 |
| 活动面 `[aria-live="polite"]` + "DeepTutor Exploring/Reasoning/Planning/Quizzing/Reflecting/responded" | `ActivityHeader.tsx:101`；文案构造 `TracePresentation.tsx:1583-1597`（agent 名回退 "DeepTutor"） | 无 |
| "stop generating" / "send" | `ChatComposer.tsx:884` / `:887` | 无 |
| textbox `/answer/i` | `AskUserOptions.tsx:1476` textarea 仅 placeholder，无 aria-label（见健壮性建议） | 加 aria-label |
| 按钮 `/drop connection/i`（:39） | **无任何 UI 对应，过期** | 见过期 1 |
| 门禁/配置 | `DEEPTUTOR_TURN_E2E_FIXTURE` 与 fixtures 一致；playwright.config `testIgnore` 于 ui-audit、独立 `critical-turns` project | 无 |

### 5. multi-worker-turns.audit.ts

| 引用目标 | 现状 | 建议 |
|----------|------|------|
| `multiWorkerFixtureAvailable`、`runtimeFixture`、`DEEPTUTOR_MULTI_WORKER_E2E` | fixtures/runtime.ts 全部存在；门禁一致 | 无 |
| 控制面 `/{DEEPTUTOR_MULTI_WORKER_CONTROL_PATH}`（默认 `/__e2e__/v2-turn-runtime`）与 `/api/system/runtime` | 后者已入契约 `web/contracts/generated/api.ts:9995`；前者为后端 fixture 控制面，需后端按四 worker + Redis 部署（web 侧无漂移） | 无 |
| 按钮 `/stop generating/i`、`/retry/i` | `ChatComposer.tsx:884`；"Retry"（`en/app.json:734`） | 无 |

### 6. pdf-reading-resize.audit.ts

| 引用目标 | 现状 | 建议 |
|----------|------|------|
| 路由 `/learning/reading/{ws}/sessions/{sid}` | `web/app/(workspace)/learning/reading/[workspaceId]/sessions/[sessionId]/page.tsx` | 无 |
| `.dt-reader-scroll`、`[data-reader-unit]` | `TextUnitView.tsx:524/527`、`PdfPage.tsx:180`、`PdfDocumentView.tsx` 多处 | 无 |
| `.textLayer` | `PdfPage.tsx:49-117`（pdfjs-dist ^6.2.108，`copy-pdfjs-assets` 预备） | 无 |
| "Expand contents" 按钮、"Annotations" tab | `ReadingWorkspace.tsx:462-472`；`SourceNavigator.tsx:220/230/551`（role=tab） | 无 |
| 依赖 jspdf | `package.json:46` ^4.2.0 | 无 |

### 7. reading-citation-material.audit.ts

| 引用目标 | 现状 | 建议 |
|----------|------|------|
| 引用链接名 "p.2"、href `#dt-material-{id}-revision-{rev}-locator-{n}` | 构造 `web/lib/reading-citations.ts:38,284`；解析 `:320` | 无 |
| units mock `/api/reading/materials/{id}/units/{n}` | `web/lib/reading-api.ts` BASE=`/api/reading` 一致 | 无 |
| workspace/sessions/materials/supported-formats/extensions/annotations 端点 | 同上，全部存在 | 无 |

### 8. reading-location-history.audit.ts

| 引用目标 | 现状 | 建议 |
|----------|------|------|
| "Back"/"Forward"/"More"/"History" 按钮 | `ReaderPane.tsx:998/1004/1058/1082` | 无 |
| "Expand contents" | `ReadingWorkspace.tsx:462` | 无 |
| "Section N · Unavailable" | `ReaderPane.tsx:1167-1169`（`unitLabel + locator + · Unavailable`） | 无 |
| localStorage `dt.reader.history.{session}` | `web/lib/reading-location-history.ts:5` 前缀一致 | 无 |
| PUT `/api/reading/workspaces/{id}/materials/{mid}/active` | 契约 `web/contracts/generated/api.ts:7269` | 无 |

### 9. reading-w3c-annotations.audit.ts

| 引用目标 | 现状 | 建议 |
|----------|------|------|
| `.r6o-annotation` / `data-annotation` 属性 / `article.r6o-annotatable` | `@recogito/text-annotator@4.2.5`（已核对安装产物：span 渲染 `className="r6o-annotation"` + `dataset.annotation = id`）；样式 `web/app/globals.css:1261-1294` | 无 |
| `[data-reader-heading-id="dt-reader-heading-1-1"]` | `TextUnitView.tsx:694` | 无 |
| "Reading companion" / "Close panels" / "Collapse contents" | `ReadingWorkspace.tsx:557` / `:615` / `:462` | 无 |
| 高亮条目 active ring `border-[var(--ring)]` | `AnnotationList.tsx:126` | 无 |

### 10. release-ui-matrix.audit.ts

| 引用目标 | 现状 | 建议 |
|----------|------|------|
| 6 面 `/chat`、`/learning/reading`、`/learning/mastery`、`/settings`、`/knowledge-bases`、`/co-writer` | 路由全部存在 | 无 |
| localStorage `deeptutor-theme` / `deeptutor-language` | `ThemeScript.tsx:14`、`context/app-shell-storage.ts:74` | 无 |
| html class：snow→`theme-snow`、dark→`dark`、glass→`dark theme-glass`、light→净空 | `ThemeScript.tsx:16-37` 逐一吻合 | 无 |
| 默认 `http://127.0.0.1:3300` | **端口漂移**（config/CI 均为 3000） | 见过期 2 |

### 11. settings-navigation.audit.ts

| 引用目标 | 现状 | 建议 |
|----------|------|------|
| 导航 "Settings sections"、"Search settings" | `SettingsNav.tsx:58/66-67`（`SettingsMain.tsx:72` 移动端同款） | 无 |
| 分区路由 llm/appearance/starters/general/attachments/connections/status/about/embedding | `SettingsPageContent.tsx:193-201` PAGES 注册表全量覆盖；`/settings#llm` 深链归一 `legacySettingsDestination`（`settings-pages.ts:160+`） | 无 |
| 导航链接 "Language models"/"Embedding models"/"Appearance"/"Conversation" | `settings-pages.ts:134/136`；`settings-nav.ts:177`；locale `Appearance`/`Attachments` | 无 |
| 标签 Model ID / Timeout (seconds) / API key / Provider URL / Provider type | `ServiceConfigEditor.tsx:886-890`、`ChatResponseTimeoutSection.tsx:108-120`、`ProvidersWorkspace.tsx:279/314` | 无 |
| 按钮 Save draft / Apply changes / Discard / Back to app / Save draft and return / Keep editing / Test model / Test provider / Get model list / Add provider / Add model / Continue | `SettingsToolbar.tsx:55-83`；locale 4263-4468；`RegistryControls.tsx:219`、`ServiceConfigEditor.tsx:560/774/1285`、`ModelsWorkspace.tsx:198/435` | 无 |
| `data-settings-page` / "This settings page is unavailable." / region "Provider settings" | `SettingsPageContent.tsx:250` / `:240`；`ProvidersWorkspace.tsx:246-247`（section + aria-label → region role） | 无 |
| 设置步骤链接 1/2/3 → /settings/connections、/settings/llm、/settings/status | `SettingsOverview.tsx:101-121` | 无 |
| 端点 settings/draft、/apply、/chat-response-timeout、/chat-starters、/readiness、/system/status、/test-provider、/model-capabilities、/chat-attachments | `SettingsStore.tsx:760/800/1480/1778`、`ChatResponseTimeoutSection.tsx:74`、`settings-extensions.ts:25-27`、`settings-readiness.ts:213`、`SettingsStore.tsx:849`、`RegistryControls.tsx:168`、`ModelCapabilityFields.tsx:59`、`attachment-limits.ts:43` | 无 |
| zh 文案 "设置分区"/"常规" | `zh/app.json:3658/4269` | 无 |
| 备注 | mockSettings 未覆盖 `/api/settings/apply/service|registry|provider`（`SettingsStore.tsx:1510/1570/1655`），主 Apply 流程走 `/api/settings/apply` 已覆盖；按分区保存的新端点若进入被测流程需补 mock | 观察项 |
