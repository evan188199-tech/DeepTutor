# scan: web 错误呈现面清点（ErrorBoundary / 静默失败 / 恢复动作）

- 日期：2026-10-06
- 基线：origin/main `f07029cfc`（release v1.6.13），分支 `scan/web-error-boundaries-20261006`
- 方式：只读 AST/正则扫描（3 个脚本），未修改任何产品代码
- 复跑：`bash scripts/run_scan.sh <repo-root>`；两次运行 SHA256 一致（见 SHA256SUMS）

## 1. 口径

| 轴 | 内容 | 数据 |
|---|---|---|
| A 边界覆盖 | Next.js 约定边界（`error.tsx`/`global-error.tsx`）、React 类边界（`componentDidCatch`/`getDerivedStateFromError`）、第三方库（`react-error-boundary`）、路由清单逐一标注覆盖边界、Suspense、全局 window 错误监听 | `datasets/boundaries.json` |
| B 失败呈现 | web/ 下全部 `catch` 块按"用户可见呈现面"分型：toast_error / toast_other / inline_state / banner / rethrow / degrade_default / console_only / silent / unclassified | `datasets/surfacing.json` |
| C 恢复动作 | retry/reload/resend/reconnect 文案或 aria-label、`.retryable` 消费点、专用恢复模块与横幅组件、`window.location.reload` 兜底 | `datasets/recovery.json` |

- 范围：`web/` 下 `.ts/.tsx` 共 1240 个文件（排除 node_modules/.next/coverage/dist；B/C 轴另排除 tests、e2e）。
- 分型优先级：notify(error) > setError 类 state > setToast/Notice > banner > rethrow > 降级默认值 > 纯 console > 空/注释体 > 其他逻辑。
- 去重边界：`silent` 中空体/纯注释条目与 scan-ts-catch 重叠（条目带 `overlap=scan-ts-catch` 标记）；`console_only` 与 scan-console-noise 重叠（`overlap=scan-console-noise`）；路由守卫（scan-web-route-guards）与无障碍（scan-a11y-basics）不在本扫描轴内。本扫描只回答"错误有没有到达用户、出错后能不能恢复"。

## 2. 覆盖统计

- 路由：61 个 `page.tsx`，**61/61 无任何错误边界覆盖**（covered_by_boundary 全空）。
- 边界机制计数：`error.tsx`/`global-error.tsx` = 0；`componentDidCatch`/`getDerivedStateFromError` = 0；`react-error-boundary` 依赖 = 无；`resetErrorBoundary` = 0。
- Suspense：18 个文件共 18 处（loading 兜底，不兜错误）。
- 全局 window `error`/`unhandledrejection` 监听：0（仅 2 处 socket/脚本元素级监听，`web/features/chat/transport/TurnRuntimeClient.ts:165`、`web/components/Geogebra.tsx:61`）。
- catch 块总量：629（889 个文件），分型：inline_state 244、unclassified 206、silent 117、toast_other 24、rethrow 10、toast_error 14、console_only 9、banner 4、degrade_default 1。
- 恢复动作：retry 文案/aria 命中 83 处、55 个文件；`.retryable` 消费 10 个文件；`window.location.reload` 兜底 1 处。

### 面向用户的呈现面矩阵（路由组 × 主要功能区）

| 区域 | 路由数 | retry UI | inline | toastE | silent | consOnly |
|---|---|---|---|---|---|---|
| workspace 组 | 29 | 9 | 18 | 8 | 2 | 1 |
| utility 组 | 26 | 0 | 7 | 0 | 0 | 0 |
| settings 组 | 2 | 10 | 40 | 0 | 14 | 0 |
| admin 组 | 1 | 0 | 5 | 0 | 0 | 0 |
| features/chat | – | 12 | 8 | 3 | 3 | 2 |
| components/knowledge | – | 17 | 46 | 0 | 2 | 0 |
| components/settings | – | 10 | 40 | 0 | 14 | 0 |
| components/reading | – | 7 | 15 | 0 | 9 | 0 |
| components/space | – | 7 | 16 | 2 | 5 | 0 |
| components/watching | – | 5 | 13 | 0 | 6 | 0 |
| components/memory | – | 0 | 1 | 0 | 3 | 0 |
| components/visualize | – | 0 | 4 | 0 | 2 | 0 |
| components/courses | – | 0 | 2 | 0 | 0 | 0 |
| components/mcp | – | 0 | 2 | 0 | 0 | 0 |

## 3. 分型清单（Top 问题，每条附建议）

### P0-1 全应用零错误边界，任何渲染期异常 = 整页白屏

- 证据：`datasets/boundaries.json` → `a1_next_convention_boundaries: []`、`a2_class_boundary_signals: []`、`a3_route_summary.routes_uncovered=61`。
- 影响：生产模式下任意 `page.tsx`/子组件渲染抛错时没有自定义降级 UI（Next.js 默认整页失败），用户无任何提示与出路；也拿不到 `AppError` 已建模的 `retryable` 信息。
- 建议：
  1. 先补 `web/app/global-error.tsx`（最低成本兜底，含"重新加载"按钮）；
  2. 在 `(workspace)/layout.tsx`、`(utility)/layout.tsx` 两个大组各放一个 `error.tsx`（覆盖 55/61 路由），聊天/阅读再按需细化；
  3. 边界文案走 i18n，提供 retry 按钮（复用 C 轴现有 retry 文案习惯）。

### P0-2 无全局 `unhandledrejection`/`window.onerror` 兜底

- 证据：`datasets/boundaries.json` → `a4_global_window_handlers` 仅 2 处非全局监听。
- 影响：漏网异步错误完全不可观测，也无法统一转成 toast。
- 建议：在根 layout 挂一个 `unhandledrejection` 监听，把未处理拒绝以 `notify(t('Unexpected error'), { tone: 'error' })` 呈现（可与 P0-1 一并做）。

### P1-1 toast 系统无恢复动作，error toast 也会自动消失

- 证据：`web/lib/notifications.ts:30`（`notify` 只有 message/tone/durationMs，无 action 回调）、`web/components/common/ToastViewport.tsx:47`（仅 message + 关闭按钮）；error toast 默认 4000ms 自动消失（个别调用延长到 8000–10000ms，如 `web/app/(workspace)/learning/books/BooksRoute.tsx:182`、`web/features/chat/ChatStateAdapter.tsx:1962`）。
- 影响：`AppError.retryable`（`web/shared/api/errors.ts:11`）已建模可重试，但消费点只集中在 chat/knowledge/books 传输层（`datasets/recovery.json` → c2_retryable_consumer_files 共 10 文件），toast 这条最通用的呈现面没有任何"重试"出口。
- 建议：给 `notify()` 增加 `action?: { label, onClick }` 选项，error toast 默认不自动消失（或延长至 ≥10s）；`apiFetch` 包装层在 `retryable=true` 时附带重试 action。

### P1-2 用户可达表面上的"console-only / 静默"失败路径

这 9 处 catch 只写 console，用户侧看到的是空面板/无响应（清单全文见 `datasets/surfacing.json` category=console_only）：

| 位置 | 现象 | 建议 |
|---|---|---|
| `web/components/sidebar/UtilitySidebar.tsx:64` | 会话列表加载失败仅 console.error，侧栏空白 | 失败时展示 inline 重试行 |
| `web/components/sidebar/WorkspaceSidebar.tsx:77` | 同上 | 同上 |
| `web/components/notebook/useNotebookSelection.ts:48` | 笔记本列表失败仅 console + 降级空数组 | 同上 |
| `web/components/notebook/useNotebookSelection.ts:78` | 笔记本记录失败仅 console | 同上 |
| `web/app/(workspace)/learning/books/BooksRoute.tsx:243` | hydratePage 失败仅 console.error | 页内提示 + 重试 |
| `web/components/Geogebra.tsx:175` | evalCommand 失败 push 后仅 console.warn | 渲染失败占位 |

其余 3 处为低风险（chat 传输内部统计）。

### P1-3 恢复动作分布不均：6 个功能区完全没有 retry 入口

retry UI（文案/aria）命中的 55 个文件集中在 chat/knowledge/settings/reading/space/watching；以下区域 0 命中，失败后用户只能靠手动刷新/重新导航：

- admin（`web/app/(admin)/admin/users/page.tsx:93` 仅 inline 文案）
- memory（`web/components/memory/MemorySection.tsx` 等）
- visualize（`web/components/visualize/VisualizationViewer.tsx`）
- courses（`web/components/courses/`）、mcp（`web/components/mcp/McpServerRow.tsx` 仅有重连一类内部重试）
- utility 组整组 26 条路由（profile、session-handoff、co-writer 列表页等）

建议：给"加载类失败"做一个共享的 `<LoadError onRetry>` 小组件，先铺 utility 组与 admin/memory/visualize。

### P2-1 silent catch 共 117 处，绝大多数为带注释的合理 best-effort

抽样核对（全量见 `datasets/surfacing.json`）：localStorage/sessionStorage 不可用、剪贴板权限、流式帧解析、轮询瞬断等都有说明性注释，属可接受模式；其中与 scan-ts-catch 重叠的条目已打标。建议保持现状，但把注释规范（"为什么可吞"）纳入 review checklist。

### P2-2 命名陷阱：`WorkspaceRuntimeBoundary` 不是错误边界

- 证据：`web/components/workspaces/WorkspaceRuntimeBoundary.tsx:17` — 只是按 workspace id remount + 清理 turn state 的生命周期边界，无 `componentDidCatch`。
- 建议：改名（如 `WorkspaceScopeRemounter`）或注释注明，避免被误认为已有兜底。

## 4. 补齐优先级汇总

1. P0 global-error.tsx + 组级 error.tsx（一次小 PR 可完成，立刻消除白屏面）
2. P0 全局 unhandledrejection → notify
3. P1 toast action + error toast 不自动消失
4. P1 侧栏/笔记本等 console-only 失败改 inline + retry
5. P1 utility/admin/memory/visualize/courses 铺共享 LoadError 组件
6. P2 WorkspaceRuntimeBoundary 改名注释；silent catch 注释规范

## 5. 复现

```bash
cd <repo-root>
bash evidence/scan-web-error-boundaries-20261006/scripts/run_scan.sh . \
  evidence/scan-web-error-boundaries-20261006/datasets
shasum -a 256 evidence/scan-web-error-boundaries-20261006/datasets/*.json
# 输出应与 evidence/scan-web-error-boundaries-20261006/SHA256SUMS 一致
```
