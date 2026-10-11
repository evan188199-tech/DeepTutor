# scan(web): e2e audit 面静态清点与运行前置清单

- 基线: `origin/main` @ `6cf793bd8` (v1.6.14)，只读新 worktree，纯静态扫描，未启动浏览器/服务器/守护进程。
- 范围: `web/tests/e2e/*.audit.ts`（11 个）+ `web/tests/e2e/fixtures/runtime.ts`；边界备注 `web/tests/epub-reader.audit.ts`（不在本卡 glob 内，但与同一 playwright config 关联）。
- 去重: scan-web-test-gaps 卡覆盖 vitest/node 测试缺口轴，本卡只清点 Playwright `.audit.ts` 面，不重合。
- 来源: myfork `evidence/verify-merges-20261010/README.md` 补测候选 #6（"Playwright .audit.ts/e2e 抽测基建"）与 v1.6.13 窗口同类备注（e2e 面连续两个窗口「未执行」）。

## 一、总览表（文件 × 覆盖 × 前置 × 入口）

| # | 文件 (行数) | 覆盖面（路由/交互） | 运行前置 | 本地入口 | CI 入口 |
|---|---|---|---|---|---|
| 1 | book-reader-sequential.audit.ts (213) | `/learning/books/[bookId]/pages/[pageId]`；键盘翻页、章节内滚动↔progress 同步、跨章位置重置 | 浏览器 + app server；API 全 mock；无凭据 | `npm run audit` | web-tests job ✓ |
| 2 | compliance-and-ux.audit.ts (108) | `/` 地标/h1/img alt/链接名/viewport；`/notebooks` 500 反馈 | 浏览器 + app server；仅 notebooks mock，首页不 mock（容忍） | 同上 | 同上 |
| 3 | learning-progress.audit.ts (114) | `/settings/progress`；reading records 契约、移动端无溢出、请求面断言 | 浏览器 + app server；API 全 mock | 同上 | 同上 |
| 4 | multi-worker-turns.audit.ts (168) | 四 worker v2 turn：跨 worker 恢复/取消/追答、owner 丢失、reload 重放、旁观察 | `DEEPTUTOR_MULTI_WORKER_E2E=1` + **外部四 worker 部署**（见四） | `npm run test:e2e:multi-worker` | multi-worker-web job（repo var 门禁，默认关） |
| 5 | pdf-reading-resize.audit.ts (221) | `/learning/reading/[ws]/sessions/[sid]` 160 页 PDF；注解面板开合 + resize 后阅读位置保持 | 浏览器(Chromium) + app server；API 全 mock；jspdf ✓ | `npm run audit` | web-tests ✓ |
| 6 | reading-citation-material.audit.ts (228) | 引用锚 `#dt-material-{id}-rev-4-loc-2`、点击 p.2 重开源 material | 同 5 | 同上 | 同上 |
| 7 | reading-location-history.audit.ts (265) | Back/Forward 跨 material、reload 存续、session 隔离；删除 material 的 404 提示 + More→History | 同 5 + localStorage `dt.reader.history` 预置 | 同上 | 同上 |
| 8 | reading-w3c-annotations.audit.ts (207) | `.r6o-annotation` 高亮渲染/reflow、Annotations tab、companion 收起、ring 激活 | 同 5；`@recogito/text-annotator@4.2.5` ✓ | 同上 | 同上 |
| 9 | release-ui-matrix.audit.ts (102) | 6 路由 × 4 主题 × 2 语言 × 4 视口 = 32 case：溢出/密码填充/密钥泄漏/Tab 焦点/主题类 | 浏览器 + app server；**无 API mock**（容忍失败）；仅 localStorage 注入 | 同上 | 同上 |
| 10 | settings-navigation.audit.ts (627) | 设置 14 用例：deep link、草稿/apply、失败保存、搜索、zh/mobile、受限用户、诊断契约、provider discovery | 浏览器 + app server；API 全 mock（writes 拦截） | 同上 | 同上 |
| 11 | turn-lifecycle.audit.ts (54) | ask-user 作答、断连恢复、composer 停止控制 | `DEEPTUTOR_TURN_E2E_FIXTURE=1` + 外部 turn fixture + app server | `npm run test:e2e:critical` | **无**（CI 不跑 critical-turns） |
| F | fixtures/runtime.ts (194) | MultiWorkerRuntimeFixture（health/reset/arm/act/evidence）+ sendPrompt/assistantActivity 共享助手 | 消费 env：`DEEPTUTOR_MULTI_WORKER_E2E`、`DEEPTUTOR_MULTI_WORKER_CONTROL_URL/PATH`、`NEXT_PUBLIC_API_BASE`/`WEB_BASE_URL` | 被动依赖 | 被动依赖 |

## 二、playwright project ↔ 文件映射（web/playwright.config.ts）

| project | testMatch | 文件 | 本地 script | CI |
|---|---|---|---|---|
| ui-audit | `**/*.audit.ts`（排除 epub/turn-lifecycle/multi-worker） | #1,2,3,5,6,7,8,9,10（9 个） | `npm run audit` / `audit:ui` / `audit:report` | web-tests job：`npm run check`（含 build）→ `npm start` :3000 → `WEB_BASE_URL=… npm run audit` |
| critical-turns | turn-lifecycle.audit.ts | #11 | `npm run test:e2e:critical` | 无 |
| multi-worker-turns-desktop / -mobile | multi-worker-turns.audit.ts | #4 | `npm run test:e2e:multi-worker` | multi-worker-web job，`if: vars.DEEPTUTOR_MULTI_WORKER_E2E_URL != ''` |
| epub-reader-chromium / -webkit | tests/epub-reader.audit.ts | 边界外 | **无 npm script**（仅 `npx playwright test --project=epub-reader-*`） | 无 |

CI 仅 `.github/workflows/tests.yml` 触及 Playwright（chromium `--with-deps`）；webkit 未装 → epub-reader-webkit 即使本地也需自装浏览器。CI `retries=2`（`forbidOnly` 生效）。

## 三、逐文件结论行（覆盖 + 前置 + 可静态评估项）

1. **book-reader-sequential**：路由 ✓ `app/(workspace)/learning/books/[bookId]/pages/[pageId]/page.tsx`；选择器 `chapter-scroll-container`/`chapter-progress` ✓ `PageReader.tsx`；"Collapse chapters" ✓ `BookSidebar.tsx`。mock 含 `127.0.0.1:8001` proxy-origin 重写分支（服务端 proxy 绕过浏览器 mock 的补偿，静态可确认注释与逻辑一致）。可静态评估：mock 路径 ↔ `lib` API 契约一致性。
2. **compliance-and-ux**：`/notebooks` 路由 ✓；`data-test="notebooks-empty"` ✓ `NotebookConsole.tsx:509`；"No notebooks" 文案 ✓ en locale。`main`/`h1`/viewport meta 属运行时 DOM 断言（布局文件静态在，但以渲染结果为准）。首页三用例不 mock API → 无后端时依赖错误边界仍渲染静态 DOM，标注脆弱。
3. **learning-progress**：`/settings/progress` 路由 ✓（`app/(utility)/settings/progress`）；`/api/mastery-paths/reading/records` ✓ `lib/learning-records-api.ts`；退役端点 `/api/v1/learning/records` 源码 0 命中 → 负向断言当前成立。progressbar aria-valuenow 由 mock 数据 0.5 换算，契约可静态读。
4. **multi-worker-turns**：活动面 `[aria-live="polite"]` ✓ `ChatMessageList.tsx:1281`；文案 "DeepTutor Exploring…" ✓ en locale:1658（正则 `Exploring|Reasoning|Planning|Quizzing|Reflecting|responded` 与 locale 键族匹配）；"Stop generating" ✓ `ChatComposer.tsx:884`。**运行前置为仓库外部**（见四）。`sendPrompt` 用 `getByRole("textbox").last()` 弱选择器 → composer 结构变化即漂移（静态标注）。
5. **pdf-reading-resize**：路由 ✓；`.dt-reader-scroll`/`[data-reader-unit]` ✓ `TextUnitView.tsx`/`PdfDocumentView.tsx`/`PdfPage.tsx`；"Expand contents" ✓ `ReadingWorkspace.tsx`；"Annotations" tab ✓ `SourceNavigator.tsx:230`。jspdf ^4.2.0 已声明 ✓。PDF 由 jsPDF 运行时生成，非仓库资产。
6. **reading-citation-material**：路由 ✓；引用锚格式 `dt-material-{id}-revision-{rev}-locator-{n}` 可静态对 `features/chat` 渲染逻辑（契约断言，静态可评估）；"p.2"/"p.1" 文案由 citation 渲染器生成，静态可读。
7. **reading-location-history**：`dt.reader.history.<session>` localStorage 键 ✓ `lib/reading-location-history.ts`；"More" ✓ `WorkspaceMenu.tsx:73-90`；"Back"/"Forward" ✓ `ReaderPane.tsx`；"Expand contents" ✓。404 提示 "Material is no longer available" 来自 mock，与 reader 的 alert 断言配对（运行时确认）。
8. **reading-w3c-annotations**：`data-reader-heading-id` ✓ `TextUnitView.tsx`；`.r6o-annotation`/`article.r6o-annotatable` 由 `@recogito/text-annotator` 运行时注入，静态仅 `globals.css` 样式可核 → 「部分可静态评估」；`toHaveClass(/border-\[var\(--ring\)\]/)` 为样式实现细节断言，重构即漂移（标注）。
9. **release-ui-matrix**：6 路由全部存在 ✓（chat / learning/reading / learning/mastery / settings / knowledge-bases / co-writer）；`deeptutor-theme`/`deeptutor-language` ✓ `lib/theme.ts`、`context/app-shell-storage.ts`；`theme-snow`/`theme-glass`/`dark` ✓ `ThemeScript.tsx`/`globals.css`。泄漏正则（`sk-…`/`Bearer …`）属可静态复检类。`waitForTimeout(250)` 固定等待 ×6 路由 ×32 case → 时长/脆弱点标注。**无 API mock**：CI 无后端运行，依赖页面在 API 失败下仍渲染 body。
10. **settings-navigation**：`[data-settings-page]` ✓ `SettingsPageContent.tsx`；"Settings sections"/"Search settings" ✓ `SettingsNav.tsx`；"Apply changes"/"Save draft" ✓ `SettingsToolbar.tsx`；"Test provider"/"Get model list" ✓ `RegistryControls.tsx`；"Add provider" ✓ `ServiceConfigEditor.tsx`；zh 文案（常规/设置分区/语言模型/模型 ID）✓ zh locale。受限用户用例断言 `/api/settings/chat-attachments` 零请求 —— 请求面断言可静态对权限清单核。
11. **turn-lifecycle**：**"Drop connection" 源码与全部 locales 0 命中 → 选择器漂移，该用例当前静态评估即失败**（critical-turns project 无 CI 入口，属潜伏漂移）。"Stop generating"/"^send$"/"Retry" ✓。ask-user 作答 textbox 的可及名来自 composer placeholder 动态拼接（`ComposerInput.tsx:741`），静态不可完全确认，需运行时复核。
12. **fixtures/runtime.ts**：`assertReady` 硬前置：`/api/system/runtime` 可达 + `worker_count===4` + coordination=redis 且 healthy + fixture health 返回 4 worker。`/api/system/runtime` 后端实现 ✓ `deeptutor/api/routers/system.py:117`（`main.py:741` 挂载 `/api/system`）。

## 四、运行前置清单（汇总）

- **浏览器**：全部需要。ui-audit/critical-turns=Desktop Chrome；multi-worker 另 iPhone 13；epub 另 WebKit。CI 只装 chromium。
- **app 运行时**：全部需要 web server（dev 或 prod build+`npm start`）。CI 用 `npm run check`（内含 build）后 `npm start` 于 127.0.0.1:3000。
- **后端 API**：#1,3,5,6,7,8,10 全 mock，无需后端；#2 首页与 #9 不 mock（设计上容忍失败响应）；#4/#11 需外部确定性 fixture 环境：
  - `/__e2e__/v2-turn-runtime`（health/reset/scenarios/actions/evidence）：**仓库内无任何实现**（python/TS/docs 0 命中），仅有 runtime.ts 消费端 → 依赖仓库外部部署（CI 经 repo var `DEEPTUTOR_MULTI_WORKER_E2E_URL`/`DEEPTUTOR_MULTI_WORKER_CONTROL_URL` 注入，默认 http://127.0.0.1:8001）。
- **凭据/账号**：无。auth 一律 mock `enabled:false, authenticated:true`；受限用户走 mock preset。#4 的外部环境若开 auth 需环境侧处理（fixture 契约未含凭据注入）。
- **env 门禁**：`DEEPTUTOR_TURN_E2E_FIXTURE=1`（#11 文件级 skip）、`DEEPTUTOR_MULTI_WORKER_E2E=1`（#4 文件级 skip）、`WEB_BASE_URL`/`NEXT_PUBLIC_API_BASE`（baseURL，默认 localhost:3000）、`DEEPTUTOR_MULTI_WORKER_CONTROL_URL/PATH`、`PW_SERIAL=1`（串行）。

## 五、静态评估发现（无需运行即可定论）

1. **漂移（高）**：turn-lifecycle.audit.ts:39 "Drop connection" 按钮 — 源码/locales 全 0 命中；该 project 无 CI 入口，属「静态可判失败」项。
2. **缺失（高）**：`/__e2e__/v2-turn-runtime` fixture 仓库内无实现；multi-worker/critical-turns 两面实际不可本地复现，只能指向外部部署。
3. **依赖卫生（中）**：`tests/epub-reader.audit.ts` 直接 `import "jszip"`，未声明于 web/package.json（现靠传递依赖提升 3.10.1 才可解析；clean install 语义脆弱）。
4. **入口缺口（中）**：epub-reader-* 与 critical-turns 无 CI 入口；epub 还缺 npm script；tests.yml 只跑 ui-audit（9 文件）与门禁关闭的 multi-worker。
5. **退役断言（通过）**：`/api/v1/learning/records` 源码 0 命中，learning-progress 的负向断言当前成立；`/api/mastery-paths/reading/records` 已落地 lib/learning-records-api.ts。
6. **弱选择器/固定等待（低，标注）**：`getByRole("textbox").last()`（runtime.ts:183）、`toHaveClass(/border-\[var\(--ring\)\]/)`（w3c audit:206）、`waitForTimeout(250)`（release-ui-matrix:49）。
7. **核对通过**：9 个 ui-audit 文件的全部引用路由与关键选择器（见三）静态核对存在，可作为「audit 面未执行」窗口的基线底表。

## 六、复核命令

```bash
# 基线与文件面
git -C /Users/Shared/DeepTutor fetch --multiple origin myfork
git -C /Users/Shared/DeepTutor worktree add /tmp/dt-audit-check 6cf793bd8
ls /tmp/dt-audit-check/web/tests/e2e/*.audit.ts   # 11 个
wc -l /tmp/dt-audit-check/web/tests/e2e/*.audit.ts

# project 映射与入口
grep -n "testMatch\|testIgnore" /tmp/dt-audit-check/web/playwright.config.ts
grep -n "audit\|playwright" /tmp/dt-audit-check/.github/workflows/tests.yml
grep -n "audit\|e2e" /tmp/dt-audit-check/web/package.json

# 静态选择器抽查（示例）
grep -rn "chapter-scroll-container" /tmp/dt-audit-check/web/app
grep -rn "aria-live" /tmp/dt-audit-check/web/features/chat/messages/ChatMessageList.tsx
grep -rin "drop.connection" /tmp/dt-audit-check/web --include="*.tsx" --include="*.json" | grep -v node_modules | grep -v tests/e2e   # 期望 0 命中
grep -rn "v2-turn-runtime" /tmp/dt-audit-check --include="*.py" --include="*.ts" | grep -v node_modules | grep -v tests/e2e          # 期望仅 runtime.ts
grep -n "jszip" /tmp/dt-audit-check/web/package.json   # 期望无（依赖卫生发现）

# test 收集（不启动浏览器）
cd /tmp/dt-audit-check/web && npx playwright test --list --project=ui-audit
```

## 七、SHA256SUMS

见同目录 `SHA256SUMS`（本 README 与被抽检源文件的清单）。
