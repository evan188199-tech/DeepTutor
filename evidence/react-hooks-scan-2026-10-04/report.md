# 前端 React Hooks 依赖与陈旧闭包扫描报告

- 日期：2026-10-04
- 基线：HKUDS/DeepTutor `origin/main` @ `f07029cfc`（release: v1.6.13）
- 范围：`web/` 下 `app components features hooks context lib shared proxy.ts`（排除 vendor/、tests/、`*.test.*`、`*.spec.*`、`__tests__`、contracts/generated/）
- 方法：eslint-plugin-react-hooks 7.0.1 全量 lint + 四组人工启发式扫描（定时器、DOM 监听/Observer、非 DOM 订阅与流、陈旧闭包与依赖churn），全部命中逐条读源码核实
- 本卡不改任何产品代码；本报告与 SHA256SUMS 为唯一产物

## 结论

代码整体 hooks 纪律很好：24 处 setInterval 全部在 cleanup 清除；211 处 addEventListener 均有配对移除（含 capture 配对）；10/5/1 处 Resize/Mutation/IntersectionObserver 均 disconnect；rAF 循环均取消；WS/SSE/订阅家族清理完整；未发现任何依赖数组里放内联新建引用的写法；异步竞态普遍有 token/abort/generation 防护。lint 仅 1 条 `react-hooks/exhaustive-deps` 命中。

真正的问题集中在一条链上：**阅读工作区轮询 effect 的依赖里放了每次都会换新身份的 `workspace` 对象**，导致指数退避被结构性击穿、并级联放大到文档重开与 EPUB 跳页。共 1 高、3 中、10 低、1 条信息级。

## 风险清单

严重度：高=持续错误行为/资源泄漏；中=常见场景下的浪费或用户可见异常；低=边界场景或影响轻微。

### H1｜高·轮询退避失效 + 卸载后无限轮询

- 位置：`web/components/reading/workspace/useReadingWorkspace.ts:145-170`（轮询 effect），根因在 `:78-86` 的 `refresh`
- 触发条件：
  1. 任一 tab 处于 `processing`/`queued` 时，`tick → refresh() → setWorkspace(新对象)`（`:82`）令依赖 `[refresh, workspace]`（`:170`）每轮换新身份 → effect 拆掉重建、`attempt` 归零 → 退避永远停在第一步，约 2.5s 一次平打，注释里“避免 wedged 源打爆 API”的机制失效；
  2. 卸载时若有 `refresh()` 在途：cleanup 只清掉当时的 pending timer，`.finally` 里 `timer = window.setTimeout(tick, …)`（`:166-168`）无 cancelled 防护，会重新排程 → 卸载后 `tick` 继续跑，`refresh()` 无条件 `setWorkspace`/`setConversations`（`:82-83`），定时链永不停止。
- 建议修法：effect 内 `let cancelled = false`，cleanup 置 true；重排程改 `if (!cancelled) timer = …`；依赖只留 `[refresh]`，"是否仍有 processing" 改由 ref/refresh 返回值驱动。仓库内正确范例：`components/settings/MemoryUsageItem.tsx:81-115`、`components/partners/ChannelRuntimeStatus.tsx:25-50`。
- 拆卡：可拆“修复+回归测试”卡（vitest hook 单测：模拟卸载后 refresh 迟到，断言不再排程、不再 setState）。

### M1｜中·轮询期间已打开文档被反复重新拉取

- 位置：`web/components/reading/workspace/useReadingWorkspace.ts:126-143`；放大点 `web/context/ReadingContext.tsx:105-141`
- 触发条件：阅读 A 文档（status=ready）时另一 tab 在 processing → H1 每 ~2.5s 刷新 `workspace` → `activeTab`（依赖 `[workspace]`，`:118-125`）及 `activeTab?.material` 每轮都是新对象 → effect 重跑，无条件 `openMaterial(active.material_id)` → `setLoading(true)` + `getMaterial` + `listAnnotations` 全部重打，阅读区每 2.5s 转一次 spinner。`openMaterial` 的 token 只防交错，不去重同 id。
- 建议修法：依赖改原语键 `` `${activeTab?.material.material_id}:${active?.status}` ``，或 effect 内用 ref 记录上次已打开 id，相同则跳过。
- 拆卡：可与 H1 同卡修复（同一文件同一条链），或独立小卡。

### M2｜中·EPUB 跳页 effect 受数组身份驱动 + 无并发 token

- 位置：`web/components/reading/EpubDocumentView.tsx:602-630`（依赖数组在 `:630`）
- 触发条件：
  1. `unitRefs` 是 `material.unit_refs`（ReaderPane 传入）。H1/M1 链每次轮询重开材料 → `setMaterial(新对象)` → `unitRefs` 新数组身份而 `jump` 未变 → `rendition.display(target)` 无用户动作地反复执行，阅读器闪跳、选区丢失；
  2. 快速连续两次跳页时，两条 `display() → section.load() → find → highlight` 链无 token 交错，旧链后完成会把读者带回旧目标并残留一个高亮。
- 建议修法：依赖原语化（`jump?.locator`、`jump?.quote`、`unitRefs.length`）；`then` 续体入口校验 `const token = ++jumpTokenRef.current`，不等则放弃。
- 拆卡：可拆独立“EPUB 跳页 token + 依赖原语化”修复卡。

### M3｜中·追问连接重试链可在卸载后创建永不停止的重连 socket

- 位置：`web/context/QuizFollowupContext.tsx:398-412`（重试链）、`:354-380`（`ensureRunner`）、`:242-248`（卸载清理）
- 触发条件：socket 未连上时提交追问 → `send` 走 `window.setTimeout` 重试链（无句柄、无取消）→ 期间 provider 卸载，cleanup 已 disconnect 并清空 `runnersRef` → 下一跳重进 `ensureRunner`，map 里没有记录 → 新建 `UnifiedTurnClient` 并 `connect()`；该 client 带自动重连策略（`features/chat/transport/TurnRuntimeClient.ts:416-425`），cleanup 已跑过，无人再 `stop()` → 常驻泄漏的重连 socket。
- 建议修法：`mountedRef` 在每次重试跳与 `ensureRunner` 入口检查，卸载即 `resolve(false)` 并终止链；或把重试句柄登记到 ref，卸载时统一清。
- 拆卡：可拆独立修复卡。

### L1｜低·隐藏页暂停被在途请求打破

- 位置：`web/components/settings/MemoryUsageItem.tsx:81-115`（重排程在 `:100-101`）
- 触发条件：`poll()` 在途时页面转隐藏 → `onVisibility` 清掉 pending timer → 在途请求完成后 `if (!cancelled) timer = setTimeout(poll, POLL_MS)` 未查 `document.hidden`，隐藏态轮询悄然恢复，与 `:97-99` 注释意图相反。
- 建议修法：重排程加 `&& !document.hidden`。

### L2｜低·固定间隔轮询无在途保护，慢响应时请求堆积

- 位置（同型四处）：
  - `web/components/settings/MinerUEngineSettings.tsx:186-216`（1s）
  - `web/features/settings/sections/DocumentParsingSettingsSection.tsx:1071-1109`（cursor 协议）
  - `web/components/partners/ChannelOnboardingPanel.tsx:90-107`（`poll_interval_seconds`）
  - `web/features/settings/sections/DataMigrationSettingsSection.tsx:107-120`（5s）
- 触发条件：后端延迟超过 tick 周期 → `setInterval(async …)` 上一拍未返回、下一照发，请求并发堆积、响应乱序（前两处 cursor 协议可防状态错乱，防不了堆积）。卸载清理本身都正确。
- 建议修法：改成“完成后自排程”的 setTimeout 链（MemoryUsageItem/ChannelRuntimeStatus 模式）或加 in-flight 标志。
- 拆卡：可拆一张“轮询模式统一”小卡。

### L3｜低·事件回调里把“清理函数”写成了 handler 返回值（永不执行）

- 位置：`web/components/reading/ReaderPane.tsx:695-712`
- 触发条件：`onTurnEnd` 内 120ms `setTimeout` 后接 `navigateCitation`；清理写成了 `return () => clearTimeout(timer)`——DOM 事件监听器忽略返回值，该清理永不运行；卸载/依赖变化后 timer 仍会触发，对已卸载组件做导航。
- 建议修法：`let timer` 提升到 effect 作用域，在 effect cleanup 中清除。

### L4｜低·拖拽手势监听器仅在 pointerup 移除

- 位置：`web/components/reading/workspace/ReadingWorkspace.tsx:396-406`；`web/components/chat/home/SessionViewerPanel.tsx:325-344`
- 触发条件：`pointerdown` 回调里注册 window 级 `pointermove`/`pointerup`，仅在 `onUp` 移除；拖拽中途组件卸载，两个监听器滞留到下一次全局 pointerup，期间对已卸载组件 `setCompanionWidth`/调整状态。
- 建议修法：参照 `hooks/useDragSort.ts:238-264` 的 `teardownRef` + 卸载 effect 模式。

### L5｜低·4s 错误提示定时器未随卸载清理

- 位置：`web/features/chat/components/ChatWorkspace.tsx:1523-1532`；`web/components/chat/home/StandaloneComposer.tsx:449-456`；`web/components/partners/PartnerComposer.tsx:177-184`
- 触发条件：附件错误提示展示后 4s 内离开页面 → `setTimeout(() => setAttachmentError(null), 4000)` 在卸载后触发。影响轻微（React 18+ 静默忽略），但属同一未清理家族。
- 建议修法：卸载 effect 中 `clearTimeout(timerRef.current)`。

### L6｜低·toast 自动消失定时器未随卸载清理

- 位置：`web/components/common/ToastViewport.tsx:22-34`
- 触发条件：viewport 卸载时仍在展示期的 toast，其隐藏 `setTimeout` 照常触发（代码注释自知）。影响轻微。
- 建议修法：订阅回调把句柄收进 `Set`，卸载统一清；或维持现状并保留注释。

### L7｜低·无依赖 effect 每次渲染重建 ResizeObserver

- 位置：`web/components/settings/WorkspaceShell.tsx:73-82`（`useScrollEdges`）
- 触发条件：effect 无依赖数组 → 每次渲染 disconnect + 重建 observer 并重 observe 全部子元素。`measure` 有 identity 保持的 setState（`:63-69`），故无死循环、无泄漏，仅为无谓churn；若未来有人加 early-return 会静默断观测。
- 建议修法：补 `[]`（`measure` 为 useCallback 稳定引用）。

### L8｜低·渲染期间写 ref.current

- 位置：`web/hooks/useVoiceRecorder.ts:21-22`；`web/components/partners/AssetPicker.tsx:100-101`
- 触发条件：并发渲染/StrictMode 下被丢弃的 render 也会把当次值写进 ref，可能泄漏过期的回调/状态。当前两处调用方传入的值实际不变，故暂无症状。
- 建议修法：移入无依赖 `useEffect` 镜像（同 `hooks/useDragSort.ts:86-93` 注释里的自家约定）。

### L9｜低·管理员用户页 bootstrap 随语言切换重跑且无防护

- 位置：`web/app/(admin)/admin/users/page.tsx:100-113`
- 触发条件：effect 依赖 `[router, load]`，`load` 依赖 `[t]`；中途切换 UI 语言 → auth 检查 + 列表拉取重跑，两个在途 `listUsers()` 可乱序返回，旧列表覆盖新列表。场景受限（admin 页、切语言低频）。
- 建议修法：续体加 mounted/generation 防护。

### L10｜低·exhaustive-deps 的错误“修复”示范与唯一 lint 命中

- 位置：`web/features/co-writer/components/CoWriterWorkspace.tsx:338-342` 与 `:345-384`
- 触发条件：`:342` 把稳定 ref `isUnmountedRef` 塞进了依赖数组（无效 dep，坏示范，规则一视同仁地会继续要求其他 effect 照抄）；`:384` 是全库唯一 `react-hooks/exhaustive-deps` 命中，同样是自定义 hook 返回的 ref 被要求入 deps——对延迟回调读“最新值”的场景，加 ref 入 deps 是错的。
- 建议修法：`:342` 移除该 dep；`:384` 用一行 `eslint-disable-next-line` 加理由注释。

### INFO｜信息级·SSE 永久失败时无限自动重连（by-design）

- 位置：`web/hooks/useKnowledgeProgress.ts:438-442`
- 说明：任务流端点永久失败（如任务被清理后 404）时 EventSource 自动重连不止，依赖并行 WS 侧的终态或 `closeAll()` 收口；现有 identity 防护使无重复处理，不判为缺陷。可选改进：连续 N 次 SSE 错误后放弃、仅靠 WS。

## 覆盖与验证说明

- lint：eslint（config 同 CI 门禁）全量跑，`react-hooks/*` 仅 1 条命中（见 L10）；i18n 警告等非本扫描范围。
- 定时器：24 处 setInterval 逐点核对（23 处 CLEAN，L2 的四处为堆积问题、清理本身正确）；51 处 requestAnimationFrame 全部核对，自排程链均正确取消。
- 监听/Observer：211 处 addEventListener 与 193 处 removeEventListener 逐文件配对核对（含 capture 配对），16 处 Observer 全部 disconnect；上述 L3/L4 之外无泄漏。
- 订阅与流：`.subscribe`、12 个订阅提供方模块及消费方、2 处 EventSource、6 处 WebSocket 及 ReconnectingWebSocket/TurnRuntimeClient/runBookSocketOperation/use-book-stream/mastery-ws 全链核对，卸载与重连收口完整（M3 为 React 侧重试链缺口）。
- 依赖churn：1,898 处 useEffect/useCallback/useMemo 未见内联新建引用入 deps；21 处空依赖监听/订阅 effect 均只读 ref/事件载荷；异步加载普遍有 mounted/abort/token/generation 防护。
- 本扫描不含服务端（Python）代码与 `web/tests`。

## 拆卡建议

| 建议卡 | 内容 | 关联条目 |
| --- | --- | --- |
| fix/reading-workspace-poll | H1+M1 同文件同链修复 + hook 回归测试（卸载后不再排程/不再 setState；退避真实递增） | H1, M1 |
| fix/epub-jump-token | 跳页 token + 依赖原语化 | M2 |
| fix/quiz-followup-unmount-socket | 重试链卸载防护 | M3 |
| chore/hooks-low-batch | L1/L3/L4/L5/L6/L7/L8/L9 各自 ≤10 行小改，可一张卡分点验收 | L1, L3-L9 |
| chore/poll-inflight-guard | 四处固定间隔轮询改为自排程链 | L2 |
| chore/cowriter-deps-cleanup | 移除 :342 无效 dep + :384 disable 注释 | L10 |
