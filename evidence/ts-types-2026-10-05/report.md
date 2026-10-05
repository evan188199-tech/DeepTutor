# AGEN-664 · web/ TS 类型债务热点扫描报告

- **扫描对象**: HKUDS/DeepTutor `origin/main` @ `f07029cfcf2c8dfccdb671cdfc343db8334f5741 (origin/main, v1.6.13)`，worktree `dt-agen664-tstypes-wt`，分支 `scan/ts-types-20261005`
- **扫描日期**: 2026-10-05（UTC）
- **方式**: 只读静态扫描，TypeScript 5.9.3 编译器 API 解析 AST（`AnyKeyword` / `NonNullExpression` / `AsExpression` / `TypeAssertionExpression`）+ 注释行正则（`@ts-ignore` / `@ts-expect-error` / `@ts-nocheck`）。**未修改任何产品代码，产物只进本证据目录。**
- **范围**: `web/**/*.{ts,tsx}`（排除 `node_modules`、`.next`），共 1237 个文件；`contracts/generated/**`（openapi/json-schema 生成物）、`vendor/**`（thinking-orbs）、`tests/**` 与 `*.spec/test`、`*.d.ts` 单列不计入热点。附带核查 `*.{js,jsx,mjs}` 中的抑制指令。

## 1. 结论（PASS）

| 类别 | 全量（ts/tsx） | 产品代码（排除 generated/vendor/test/d.ts） | 备注 |
| --- | --- | --- | --- |
| `@ts-ignore` | 0 | 0 | 无 |
| `@ts-expect-error` | 0 | 0 | 无 |
| `@ts-nocheck` | 0 | 0 | 无（js/jsx/mjs 中亦为 0） |
| 显式 `any` | 145 | 108（6.3%） | 其中测试文件占 37 |
| 非空断言 `!` | 133 | 66 | — |
| `as` 强转 | 1433 | 1004 | 含 `as const` 122 处安全惯例 |
| `as any` | 23 | 1 | — |
| `as unknown as X` 双跳 | 287 | 35 | 最危险的一类 |
| 尖括号断言 `<T>x` | 0 | 0 | 无 |

**一句话结论**: web/ 无任何抑制指令债务（0 条 @ts-ignore/@ts-expect-error），tsconfig 开启 `strict: true`；类型债集中在**断言与 any**——产品代码 1178 项（as 1004 + any 108 + nonnull 66），其中可拆出约 6 张修复卡（见 §9）。`eslint.config.mjs` 未启用 `@typescript-eslint/no-explicit-any` 等规则，是债务累积的机制性缺口。

## 2. 目录聚类（产品代码，三级目录 Top 15）

| 目录 | any | nonnull | as | 合计 |
| --- | --- | --- | --- | --- |
| `web/components/common` | 106 | 0 | 22 | 128 |
| `web/features/settings` | 0 | 2 | 98 | 100 |
| `web/features/chat` | 0 | 1 | 86 | 87 |
| `web/components/chat` | 0 | 12 | 53 | 65 |
| `web/components/memory` | 0 | 0 | 58 | 58 |
| `web/app/(workspace)` | 1 | 3 | 46 | 50 |
| `web/components/reading` | 0 | 4 | 46 | 50 |
| `web/features/knowledge` | 0 | 1 | 47 | 48 |
| `web/components/partners` | 0 | 5 | 25 | 30 |
| `web/components/settings` | 0 | 3 | 27 | 30 |
| `web/features/multi-user` | 0 | 1 | 20 | 21 |
| `web/lib/mcp-api.ts` | 0 | 0 | 21 | 21 |
| `web/lib/chat-import` | 0 | 2 | 15 | 17 |
| `web/lib/memory-graph.ts` | 0 | 6 | 11 | 17 |
| `web/components/sidebar` | 0 | 2 | 14 | 16 |

## 3. 文件热点 Top 20（产品代码）

| # | 文件 | 项数 | 构成 | 与 scan-ts-catch 同文件 |
| --- | --- | --- | --- | --- |
| 1 | `web/components/common/RichMarkdownRenderer.tsx` | 59 | any:55, as:4 | — |
| 2 | `web/components/common/SimpleMarkdownRenderer.tsx` | 48 | any:48 | — |
| 3 | `web/features/knowledge/api/client.ts` | 47 | as:47 | — |
| 4 | `web/components/chat/home/AskUserOptions.tsx` | 26 | as:26 | — |
| 5 | `web/features/chat/ChatStateAdapter.tsx` | 23 | as:23 | — |
| 6 | `web/features/settings/navigation/settings-nav.ts` | 22 | as:22 | — |
| 7 | `web/lib/mcp-api.ts` | 21 | as:21 | — |
| 8 | `web/features/settings/store/SettingsStore.tsx` | 20 | as:20 | — |
| 9 | `web/lib/memory-graph.ts` | 17 | as:11, nonnull:6 | — |
| 10 | `web/components/memory/MemorySection.tsx` | 14 | as:14 | — |
| 11 | `web/lib/reading-api.ts` | 13 | as:13 | — |
| 12 | `web/components/reading/library/AddMaterialsDialog.tsx` | 12 | as:9, nonnull:3 | 是 |
| 13 | `web/contracts/parse/turn-event.ts` | 12 | as:12 | — |
| 14 | `web/features/chat/messages/ChatMessageList.tsx` | 12 | as:12 | — |
| 15 | `web/components/memory/useMemoryRun.ts` | 11 | as:11 | — |
| 16 | `web/features/co-writer/components/CoWriterWorkspace.tsx` | 11 | as:11 | — |
| 17 | `web/lib/book-progress.ts` | 11 | as:11 | — |
| 18 | `web/lib/cli-apps-api.ts` | 11 | as:11 | — |
| 19 | `web/components/memory/MemoryGraph.tsx` | 10 | as:10 | — |
| 20 | `web/hooks/useKnowledgeProgress.ts` | 10 | as:10 | — |

## 4. 显式 any 全量清单（产品代码 108 项）

| 位置 | 代码行 |
| --- | --- |
| `web/app/(workspace)/learning/books/components/LearningCapturePanel.tsx:25` | `t: (key: string, values?: any) => string,` |
| `web/components/common/RichInlineMarkdown.tsx:70` | `const remarkPlugins: any[] = [remarkGfm];` |
| `web/components/common/RichInlineMarkdown.tsx:72` | `const rehypePlugins: any[] = plugins.rehypeKatex ? [plugins.rehypeKatex] : [];` |
| `web/components/common/RichInlineMarkdown.tsx:78` | `components={COMPONENTS as any}` |
| `web/components/common/RichMarkdownRenderer.tsx:68` | `function sourceLineAttr(node: any): { "data-source-line"?: number } {` |
| `web/components/common/RichMarkdownRenderer.tsx:186` | `const traceComponents: Record<string, React.ComponentType<any>> = {` |
| `web/components/common/RichMarkdownRenderer.tsx:187` | `p: ({ node, ...props }: any) => (` |
| `web/components/common/RichMarkdownRenderer.tsx:190` | `h1: ({ node, children }: any) => (` |
| `web/components/common/RichMarkdownRenderer.tsx:193` | `h2: ({ node, children }: any) => (` |
| `web/components/common/RichMarkdownRenderer.tsx:196` | `h3: ({ node, children }: any) => (` |
| `web/components/common/RichMarkdownRenderer.tsx:199` | `h4: ({ node, children }: any) => (` |
| `web/components/common/RichMarkdownRenderer.tsx:202` | `h5: ({ node, children }: any) => (` |
| `web/components/common/RichMarkdownRenderer.tsx:205` | `h6: ({ node, children }: any) => (` |
| `web/components/common/RichMarkdownRenderer.tsx:208` | `strong: ({ node, children }: any) => (` |
| `web/components/common/RichMarkdownRenderer.tsx:213` | `em: ({ node, children }: any) => <em className="italic">{children}</em>,` |
| `web/components/common/RichMarkdownRenderer.tsx:214` | `a: ({ node, children }: any) => (` |
| `web/components/common/RichMarkdownRenderer.tsx:217` | `blockquote: ({ node, children }: any) => (` |
| `web/components/common/RichMarkdownRenderer.tsx:222` | `pre: ({ children }: any) => <>{children}</>,` |
| `web/components/common/RichMarkdownRenderer.tsx:223` | `code: ({ node, children }: any) => (` |
| `web/components/common/RichMarkdownRenderer.tsx:230` | `ul: ({ node, ...props }: any) => (` |
| `web/components/common/RichMarkdownRenderer.tsx:233` | `ol: ({ node, ...props }: any) => (` |
| `web/components/common/RichMarkdownRenderer.tsx:236` | `li: ({ node, ...props }: any) => <li className="my-0.5 pl-0" {...props} />,` |
| `web/components/common/RichMarkdownRenderer.tsx:237` | `table: ({ node, children, ...props }: any) =>` |
| `web/components/common/RichMarkdownRenderer.tsx:245` | `thead: ({ node, ...props }: any) => (` |
| `web/components/common/RichMarkdownRenderer.tsx:248` | `th: ({ node, ...props }: any) => (` |
| `web/components/common/RichMarkdownRenderer.tsx:254` | `tbody: ({ node, ...props }: any) => <tbody {...props} />,` |
| `web/components/common/RichMarkdownRenderer.tsx:255` | `td: ({ node, ...props }: any) => (` |
| `web/components/common/RichMarkdownRenderer.tsx:261` | `tr: ({ node, ...props }: any) => <tr {...props} />,` |
| `web/components/common/RichMarkdownRenderer.tsx:262` | `input: ({ node, type, ...props }: any) =>` |
| `web/components/common/RichMarkdownRenderer.tsx:277` | `details: ({ node, children }: any) =>` |
| `web/components/common/RichMarkdownRenderer.tsx:279` | `summary: ({ node, children }: any) =>` |
| `web/components/common/RichMarkdownRenderer.tsx:283` | `const lineAttr = (node: any) =>` |
| `web/components/common/RichMarkdownRenderer.tsx:287` | `h1: ({ node, children, className: headingClassName, ...props }: any) => {` |
| `web/components/common/RichMarkdownRenderer.tsx:302` | `h2: ({ node, children, className: headingClassName, ...props }: any) => {` |
| `web/components/common/RichMarkdownRenderer.tsx:317` | `h3: ({ node, children, className: headingClassName, ...props }: any) => {` |
| `web/components/common/RichMarkdownRenderer.tsx:332` | `h4: ({ node, children, className: headingClassName, ...props }: any) => {` |
| `web/components/common/RichMarkdownRenderer.tsx:347` | `h5: ({ node, children, className: headingClassName, ...props }: any) => {` |
| `web/components/common/RichMarkdownRenderer.tsx:362` | `h6: ({ node, children, className: headingClassName, ...props }: any) => {` |
| `web/components/common/RichMarkdownRenderer.tsx:379` | `const normalComponents: Record<string, React.ComponentType<any>> = {` |
| `web/components/common/RichMarkdownRenderer.tsx:381` | `p: ({ node, ...props }: any) => <p {...lineAttr(node)} {...props} />,` |
| `web/components/common/RichMarkdownRenderer.tsx:382` | `ul: ({ node, ...props }: any) => <ul {...lineAttr(node)} {...props} />,` |
| `web/components/common/RichMarkdownRenderer.tsx:383` | `ol: ({ node, ...props }: any) => <ol {...lineAttr(node)} {...props} />,` |
| `web/components/common/RichMarkdownRenderer.tsx:384` | `table: ({ node, children, ...props }: any) =>` |
| `web/components/common/RichMarkdownRenderer.tsx:398` | `thead: ({ node, ...props }: any) => (` |
| `web/components/common/RichMarkdownRenderer.tsx:401` | `th: ({ node, ...props }: any) => (` |
| `web/components/common/RichMarkdownRenderer.tsx:407` | `tbody: ({ node, ...props }: any) => (` |
| `web/components/common/RichMarkdownRenderer.tsx:413` | `td: ({ node, ...props }: any) => (` |
| `web/components/common/RichMarkdownRenderer.tsx:419` | `tr: ({ node, ...props }: any) => (` |
| `web/components/common/RichMarkdownRenderer.tsx:422` | `pre: ({ children }: any) => <>{children}</>,` |
| `web/components/common/RichMarkdownRenderer.tsx:423` | `code: ({ node, className: blockClassName, children, ...props }: any) => {` |
| `web/components/common/RichMarkdownRenderer.tsx:525` | `a: ({ node, href, children, title, ...props }: any) => {` |
| `web/components/common/RichMarkdownRenderer.tsx:603` | `img: ({ node, src, alt, ...props }: any) => {` |
| `web/components/common/RichMarkdownRenderer.tsx:627` | `blockquote: ({ node, ...props }: any) => (` |
| `web/components/common/RichMarkdownRenderer.tsx:634` | `hr: ({ node, ...props }: any) => (` |
| `web/components/common/RichMarkdownRenderer.tsx:641` | `input: ({ node, type, checked, ...props }: any) =>` |
| `web/components/common/RichMarkdownRenderer.tsx:657` | `details: ({ node, children, ...props }: any) =>` |
| `web/components/common/RichMarkdownRenderer.tsx:666` | `summary: ({ node, children, ...props }: any) =>` |
| `web/components/common/RichMarkdownRenderer.tsx:704` | `const p: Array<any> = [remarkGfm];` |
| `web/components/common/RichMarkdownRenderer.tsx:711` | `const p: Array<any> = [];` |
| `web/components/common/SimpleMarkdownRenderer.tsx:48` | `const traceComponents: Record<string, React.ComponentType<any>> = {` |
| `web/components/common/SimpleMarkdownRenderer.tsx:49` | `p: ({ node, ...props }: any) => (` |
| `web/components/common/SimpleMarkdownRenderer.tsx:52` | `h1: ({ node, children }: any) => (` |
| `web/components/common/SimpleMarkdownRenderer.tsx:55` | `h2: ({ node, children }: any) => (` |
| `web/components/common/SimpleMarkdownRenderer.tsx:58` | `h3: ({ node, children }: any) => (` |
| `web/components/common/SimpleMarkdownRenderer.tsx:61` | `h4: ({ node, children }: any) => (` |
| `web/components/common/SimpleMarkdownRenderer.tsx:64` | `h5: ({ node, children }: any) => (` |
| `web/components/common/SimpleMarkdownRenderer.tsx:67` | `h6: ({ node, children }: any) => (` |
| `web/components/common/SimpleMarkdownRenderer.tsx:70` | `strong: ({ node, children }: any) => (` |
| `web/components/common/SimpleMarkdownRenderer.tsx:75` | `em: ({ node, children }: any) => <em className="italic">{children}</em>,` |
| `web/components/common/SimpleMarkdownRenderer.tsx:76` | `a: ({ node, children }: any) => (` |
| `web/components/common/SimpleMarkdownRenderer.tsx:79` | `blockquote: ({ node, children }: any) => (` |
| `web/components/common/SimpleMarkdownRenderer.tsx:84` | `pre: ({ children }: any) => <>{children}</>,` |
| `web/components/common/SimpleMarkdownRenderer.tsx:85` | `code: ({ node, children }: any) => (` |
| `web/components/common/SimpleMarkdownRenderer.tsx:92` | `ul: ({ node, ...props }: any) => (` |
| `web/components/common/SimpleMarkdownRenderer.tsx:95` | `ol: ({ node, ...props }: any) => (` |
| `web/components/common/SimpleMarkdownRenderer.tsx:98` | `li: ({ node, ...props }: any) => <li className="my-0.5 pl-0" {...props} />,` |
| `web/components/common/SimpleMarkdownRenderer.tsx:99` | `table: ({ node, children, ...props }: any) =>` |
| `web/components/common/SimpleMarkdownRenderer.tsx:107` | `thead: ({ node, ...props }: any) => (` |
| `web/components/common/SimpleMarkdownRenderer.tsx:110` | `th: ({ node, ...props }: any) => (` |
| `web/components/common/SimpleMarkdownRenderer.tsx:116` | `tbody: ({ node, ...props }: any) => <tbody {...props} />,` |
| `web/components/common/SimpleMarkdownRenderer.tsx:117` | `td: ({ node, ...props }: any) => (` |
| `web/components/common/SimpleMarkdownRenderer.tsx:123` | `tr: ({ node, ...props }: any) => <tr {...props} />,` |
| `web/components/common/SimpleMarkdownRenderer.tsx:124` | `input: ({ node, type, ...props }: any) =>` |
| `web/components/common/SimpleMarkdownRenderer.tsx:139` | `details: ({ node, children }: any) =>` |
| `web/components/common/SimpleMarkdownRenderer.tsx:141` | `summary: ({ node, children }: any) =>` |
| `web/components/common/SimpleMarkdownRenderer.tsx:146` | `h1: ({ node, children, className: headingClassName, ...props }: any) => {` |
| `web/components/common/SimpleMarkdownRenderer.tsx:160` | `h2: ({ node, children, className: headingClassName, ...props }: any) => {` |
| `web/components/common/SimpleMarkdownRenderer.tsx:174` | `h3: ({ node, children, className: headingClassName, ...props }: any) => {` |
| `web/components/common/SimpleMarkdownRenderer.tsx:188` | `h4: ({ node, children, className: headingClassName, ...props }: any) => {` |
| `web/components/common/SimpleMarkdownRenderer.tsx:202` | `h5: ({ node, children, className: headingClassName, ...props }: any) => {` |
| `web/components/common/SimpleMarkdownRenderer.tsx:216` | `h6: ({ node, children, className: headingClassName, ...props }: any) => {` |
| `web/components/common/SimpleMarkdownRenderer.tsx:232` | `const normalComponents: Record<string, React.ComponentType<any>> = {` |
| `web/components/common/SimpleMarkdownRenderer.tsx:234` | `table: ({ node, children, ...props }: any) =>` |
| `web/components/common/SimpleMarkdownRenderer.tsx:247` | `thead: ({ node, ...props }: any) => (` |
| `web/components/common/SimpleMarkdownRenderer.tsx:250` | `th: ({ node, ...props }: any) => (` |
| `web/components/common/SimpleMarkdownRenderer.tsx:256` | `tbody: ({ node, ...props }: any) => (` |
| `web/components/common/SimpleMarkdownRenderer.tsx:262` | `td: ({ node, ...props }: any) => (` |
| `web/components/common/SimpleMarkdownRenderer.tsx:268` | `tr: ({ node, ...props }: any) => (` |
| `web/components/common/SimpleMarkdownRenderer.tsx:271` | `pre: ({ children }: any) => <>{children}</>,` |
| `web/components/common/SimpleMarkdownRenderer.tsx:272` | `code: ({ node, children, ...props }: any) => {` |
| `web/components/common/SimpleMarkdownRenderer.tsx:302` | `a: ({ node, href, children, title, ...props }: any) => {` |
| `web/components/common/SimpleMarkdownRenderer.tsx:380` | `img: ({ node, src, alt, ...props }: any) => {` |
| `web/components/common/SimpleMarkdownRenderer.tsx:402` | `blockquote: ({ node, ...props }: any) => (` |
| `web/components/common/SimpleMarkdownRenderer.tsx:408` | `hr: ({ node, ...props }: any) => (` |
| `web/components/common/SimpleMarkdownRenderer.tsx:411` | `input: ({ node, type, checked, ...props }: any) =>` |
| `web/components/common/SimpleMarkdownRenderer.tsx:427` | `details: ({ node, children, ...props }: any) =>` |
| `web/components/common/SimpleMarkdownRenderer.tsx:436` | `summary: ({ node, children, ...props }: any) =>` |
| `web/shared/api/client.ts:212` | `export async function asJsonOrThrow(response: Response): Promise<any> {` |

## 5. 非空断言全量清单（产品代码 66 项，59 行；×N = 同行多处/嵌套断言链各计一次）

| 位置 | 代码行 |
| --- | --- |
| `web/app/(workspace)/learning/books/components/BookGenerationActivity.tsx:268` | `onOpenPage(row.pageId!);` |
| `web/app/(workspace)/learning/books/components/BookGenerationActivity.tsx:276` | `onOpenPage(row.pageId!);` |
| `web/app/(workspace)/learning/books/components/BookHealthBanner.tsx:288` | `onClick={() => onRecompile(kbDrift.stale_page_ids![0])}` |
| `web/components/chat/HistorySessionPicker.tsx:417` | `{selectedIds.includes(activeId!) && (` |
| `web/components/chat/ReadingReferencePicker.tsx:186` | `activeMaterial!.material_id,` |
| `web/components/chat/ReadingReferencePicker.tsx:187` | `materialRevision(activeMaterial!),` |
| `web/components/chat/home/CapabilityConfigCard.tsx:94` | `{validationErrors!.map((err, i) => (` |
| `web/components/chat/home/ChatComposer.tsx:536` | `const bytes = Uint8Array.from(atob(item.base64!), (char) =>` |
| `web/components/chat/home/ChatComposer.tsx:728` | `...(selectedPartner ? [{ key: "partner-current", icon: UserRound, kind: t("Ask partner"), ` |
| `web/components/chat/home/ChatComposer.tsx:729` | `...(selectedPartnerGroup ? [{ key: "partner-group-current", icon: Users, kind: t("Organize` |
| `web/components/chat/home/ChatComposer.tsx:731`（×2） | `...(resourceSelection?.skills \|\| []).map((id): ContextTreeItem=>({key:\`skill-${id}\`,ic` |
| `web/components/chat/home/ChatComposer.tsx:732`（×2） | `...(resourceSelection?.mcp \|\| []).map((id): ContextTreeItem=>({key:\`mcp-${id}\`,icon:Pl` |
| `web/components/chat/space/ChatSpaceMenu.tsx:179` | `return SPACE_ITEMS.find((it) => it.key === key)!;` |
| `web/components/courses/OrganizedSessionList.tsx:693` | `onClick={() => onNewWorkspaceChat(entry.workspaceId!)}><Plus size={13} /></button>` |
| `web/components/knowledge/KbDocumentList.tsx:322` | `const file = node.file!;` |
| `web/components/learning/surfaces.ts:109` | `LEARNING_SURFACES.find(surface => surface.kind === kind)!` |
| `web/components/notebook/NotebookConsole.tsx:636` | `currentNotebookId={selected!.id}` |
| `web/components/partners/group/GroupRound.tsx:222`（×2） | `onApprove(seat.message!.invocation!.invocation_id)` |
| `web/components/partners/group/GroupRound.tsx:225`（×2） | `onReject(seat.message!.invocation!.invocation_id)` |
| `web/components/partners/group/mentions.ts:74` | `const id = aliases.get(spanned)!;` |
| `web/components/quiz/QuizViewer.tsx:977` | `{Object.entries(q.options!).map(([key, text]) => {` |
| `web/components/reading/PdfDocumentView.tsx:222` | `locator: page.dataset.readerUnit!,` |
| `web/components/reading/library/AddMaterialsDialog.tsx:176` | `filename: item.file!.name,` |
| `web/components/reading/library/AddMaterialsDialog.tsx:177` | `size_bytes: item.file!.size,` |
| `web/components/reading/library/AddMaterialsDialog.tsx:178` | `content_id: await readingContentId(item.file!),` |
| `web/components/settings/ConnectionsEditor.tsx:670` | `const spec = target.services[service]!;` |
| `web/components/settings/TaskModelsWorkspace.tsx:206`（×2） | `{row.model!.name \|\| row.model!.model} ·{" "}` |
| `web/components/sidebar/SidebarNav.tsx:530` | `const entry = NAV_BY_HREF.get("/chat")!;` |
| `web/components/sidebar/WorkspaceSidebar.tsx:215` | `navigateTask(sessionRoute({ ...sessions.find(row => row.session_id === sessionId)!,` |
| `web/components/space/learning/TopicWizardSteps.tsx:157` | `const group = groups.find(group => group.key === tab)!` |
| `web/components/space/learning/TopicWizardSteps.tsx:209` | `event.currentTarget.parentElement!.querySelectorAll<HTMLButtonElement>(` |
| `web/components/visualize/VisualizationViewer.tsx:160` | `const wrapper = \`<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" c` |
| `web/components/workspaces/WorkspaceChatGroups.tsx:169` | `onOrganize={async (id, patch) => { await props.onOrganize!(id, patch); await refresh(); }}` |
| `web/features/chat/messages/usage-summary.ts:83` | `if (value \|\| pending) turns.push(value \|\| pending!)` |
| `web/features/co-writer/model/editor-state.ts:100` | `const last = sorted.at(-1)!;` |
| `web/features/knowledge/components/engines/EngineDetail.tsx:1594` | `{entry!.options.map((o) => (` |
| `web/features/multi-user/components/GrantEditor.tsx:726` | `checked={grant.enabled_tools!.includes(tool.name)}` |
| `web/features/settings/navigation/settings-pages.ts:55`（×2） | `SETTINGS_CATEGORIES.find(category => category.key === 'agents')!.children!.map(leaf => lea` |
| `web/lib/book-activity.ts:338` | `? live!.planned.map((type, position) => ({` |
| `web/lib/book-activity.ts:342` | `position < (live!.done ?? 0)` |
| `web/lib/book-activity.ts:344` | `: type === live!.current` |
| `web/lib/chat-import/agent-store.ts:97` | `migrate(request.result, request.transaction!, event.oldVersion);` |
| `web/lib/chat-import/index.ts:42` | `root = await window.showDirectoryPicker!({` |
| `web/lib/markdown-display.ts:707` | `const candidates = openers.get(marker)!;` |
| `web/lib/markdown-display.ts:711` | `leftOpener: candidates.pop()!,` |
| `web/lib/memory-graph.ts:483` | `const cluster = l3ClusterMap.get(slot)!;` |
| `web/lib/memory-graph.ts:513` | `const cluster = l2ClusterMap.get(surf)!;` |
| `web/lib/memory-graph.ts:542` | `const cluster = l1ClusterMap.get(surf)!;` |
| `web/lib/memory-graph.ts:575` | `adjacency.get(e.source)!.push(e.target);` |
| `web/lib/memory-graph.ts:576` | `adjacency.get(e.target)!.push(e.source);` |
| `web/lib/memory-graph.ts:601` | `const cluster = l2ClusterMap.get(surf)!;` |
| `web/lib/message-branches.ts:200` | `siblingIds: children.map(c => c.id!).filter(id => id !== undefined),` |
| `web/lib/model-settings.ts:204` | `JSON.stringify(next.connections![connectionIndex]) ===` |
| `web/lib/model-settings.ts:207` | `next.connections![connectionIndex] = structuredClone(savedConnection);` |
| `web/lib/provider-registry.ts:264` | `(c) => c.id !== edit.ref!.connection_id,` |
| `web/lib/provider-registry.ts:269` | `].profiles.filter((p) => p.id !== edit.ref!.profile_id);` |
| `web/lib/provider-registry.ts:340` | `catalog.connections = catalog.connections?.filter((p) => p.id !== edit.ref!.connection_id)` |
| `web/lib/provider-registry.ts:343` | `bucket.profiles = bucket.profiles.filter((p) => p.id !== edit.ref!.profile_id);` |
| `web/lib/sidebar-layout.ts:219`（×2） | `.sort((left, right) => rank.get(keyOf(left))! - rank.get(keyOf(right))!);` |

## 6. as 强转（产品代码 1004 项）

### 6.1 模式分布

| 模式 | 数量 | 风险 |
| --- | --- | --- |
| 其他具名/结构类型 | 592 | 中 |
| as const（安全惯例） | 122 | 低 |
| Record<string, unknown> 族（DOM/事件细节兜底） | 121 | 中（宽类型兜底，运行时仍有 shape 风险） |
| DOM 类型断言 | 69 | 中（运行时 shape 依赖） |
| `as unknown`（双跳断言内跳） | 35 | 高（绕过全部检查） |
| 事件 detail 收窄 | 34 | 中低 |
| 基础类型断言 | 30 | 低中 |
| `as any` | 1 | 高 |

### 6.2 `as unknown as X` 双跳断言全量清单（35 项）

| 位置 | 代码行 |
| --- | --- |
| `web/components/chat/preview/previewers/XlsxPreview.tsx:46` | `(mod as unknown as { default?: typeof mod }).default ?? mod;` |
| `web/components/common/InlineFileCard.tsx:347` | `const tree = fromMarkdown(content) as unknown as Record<string, unknown>;` |
| `web/components/reading/EpubDocumentView.tsx:424` | `const createBook = module.default as unknown as (` |
| `web/components/reading/PdfPage.tsx:97` | `await (renderTask as unknown as { promise: Promise<void> }).promise;` |
| `web/components/reading/PdfPage.tsx:117` | `textLayer = layer as unknown as { cancel: () => void };` |
| `web/components/reading/ReaderPane.tsx:661` | `const incoming = detail.annotation as unknown as AnnotationItem;` |
| `web/contracts/parse/turn-event.ts:60` | `return { ok: true, value: JSON.parse(raw) as unknown };` |
| `web/contracts/parse/turn-event.ts:109` | `return { ok: true, value: event as unknown as PongEvent };` |
| `web/contracts/parse/turn-event.ts:132` | `return { ok: true, value: event as unknown as CommandAckEvent };` |
| `web/contracts/parse/turn-event.ts:148` | `return { ok: true, value: event as unknown as ProtocolErrorEvent };` |
| `web/contracts/parse/turn-event.ts:172` | `return { ok: true, value: event as unknown as ActiveTurnInfo };` |
| `web/features/chat/ChatStateAdapter.tsx:1884` | `normalizeMessageContent(message.content as unknown).trim() !== "" \|\|` |
| `web/features/chat/ChatStateAdapter.tsx:1889` | `const raw = normalizeMessageContent(message.content as unknown);` |
| `web/features/chat/messages/ChatMessageList.tsx:1659` | `icon: (agentGlyph(agentKind) ?? Bot) as unknown as LucideIcon,` |
| `web/features/chat/transport/TurnRuntimeClient.ts:77` | `const record = command as unknown as Record<string, unknown>;` |
| `web/features/chat/transport/UnifiedTurnClient.ts:41` | `const raw = event as unknown as Record<string, unknown>;` |
| `web/features/chat/transport/socket.ts:21` | `return new WebSocket(url) as unknown as TurnSocket;` |
| `web/features/settings/navigation/settings-nav.ts:315` | `icon: ClaudeGlyph as unknown as LucideIcon,` |
| `web/features/settings/navigation/settings-nav.ts:327` | `icon: CodexGlyph as unknown as LucideIcon,` |
| `web/features/settings/navigation/settings-nav.ts:339` | `icon: GrokGlyph as unknown as LucideIcon,` |
| `web/features/settings/navigation/settings-nav.ts:352` | `icon: GeminiGlyph as unknown as LucideIcon,` |
| `web/features/settings/navigation/settings-nav.ts:364` | `icon: KimiGlyph as unknown as LucideIcon,` |
| `web/features/settings/navigation/settings-nav.ts:376` | `icon: OpencodeGlyph as unknown as LucideIcon,` |
| `web/features/settings/navigation/settings-nav.ts:388` | `icon: MimoGlyph as unknown as LucideIcon,` |
| `web/features/settings/navigation/settings-nav.ts:400` | `icon: HermesGlyph as unknown as LucideIcon,` |
| `web/features/settings/navigation/settings-nav.ts:412` | `icon: HermesGlyph as unknown as LucideIcon,` |
| `web/features/settings/navigation/settings-nav.ts:424` | `icon: OpenClawGlyph as unknown as LucideIcon,` |
| `web/features/settings/navigation/settings-nav.ts:436` | `icon: DeepSeekGlyph as unknown as LucideIcon,` |
| `web/lib/chat-import/chatgpt.ts:249` | `payload = JSON.parse(await file.text()) as unknown;` |
| `web/lib/mastery-ws.ts:57` | `value = JSON.parse(data) as unknown;` |
| `web/lib/mastery-ws.ts:76` | `return message as unknown as MasterySubscribedMessage;` |
| `web/lib/mastery-ws.ts:84` | `return message as unknown as MasteryTopicEventMessage;` |
| `web/lib/reading-api.ts:166` | `return position as unknown as ReadingPosition;` |
| `web/shared/api/client.ts:115` | `return JSON.parse(text) as unknown;` |
| `web/shared/storage/store.ts:177` | `window as unknown as StorageEventTargetLike,` |

### 6.3 `as any`（产品代码 1 项）

- `web/components/common/RichInlineMarkdown.tsx:78` — `components={COMPONENTS as any}`

### 6.4 其余 as 强转

完整逐条清单（1004 项，含类型文本与代码行）见 `ts_types_details.json` 的 `findings`（过滤 `kind=="as"` 且产品代码标记）；热点集中在 §3 Top20 文件。

## 7. 与 scan-ts-catch（AGEN-421）去重

AGEN-421 清单口径为 **catch 吞错**（41 项，@ `ef2d9e5c3` / v1.6.12；本扫描基线 v1.6.13）。逐条比对：

- **同行精确重叠 2 项**（同 file:line 同时是吞错点与类型债点，修复卡应合并处理、避免两卡改一行）:
  1. `web/hooks/useVoiceRecorder.ts:76` — AGEN-421 尽力而为/LOW（错误体解析吞错）；本卡 as 强转（`resp.json().catch(() => null) as { detail?: string } | null`）。
  2. `web/lib/attachment-limits.ts:46` — AGEN-421 尽力而为/LOW（解析失败回退默认值）；本卡 as 强转（同模式）。
- **跨行同文件重叠 18 个文件**（吞错修复与类型债修复可能触碰相邻代码，拆卡时在描述里互相引用）：`ChatComposer.tsx`、`StandaloneComposer.tsx`、`PartnerConfigure.tsx`、`EpubDocumentView.tsx`、`ReadingExtensionBar.tsx`、`AddMaterialsDialog.tsx`、`MediaReadingStage.tsx`、`useReadingWorkspace.ts`、`WatchingBrowser.tsx`、`WatchingPane.tsx`、`QuizFollowupContext.tsx`、`ChatWorkspace.tsx`、`ArchivedChatsSettingsSection.tsx`、`DataMigrationSettingsSection.tsx`、`useVoiceRecorder.ts`、`attachment-limits.ts`、`courses-api.ts`、`guardian-api.ts`。
- **边界函数交叉引用（AGEN-421 明确建议另开收紧卡）**: `courses-api.ts:136,149`（`expectJson<T>` 内 `payload as { detail?: unknown }` 与 `return payload as T`）、`guardian-api.ts:59`（`return data as T`）——2xx 且 body 非法时以 `as T` 直接返回未校验 JSON，属类型债与吞错的同源问题，纳入本卡 §9 卡 F。
- 其余类型债与 AGEN-421 的 41 项 catch 清单无重叠，无重复认领。

## 8. 热点成因备注

- `components/common` 三个 markdown 渲染器（Rich 59 + Simple 48 + Inline 9 ≈ 116 项）几乎独占 `any` 类债务（108/108 中的 ~106），根因是 react-markdown `Components` 映射与 remark/rehype 插件数组未类型化。
- `features/settings/navigation/settings-nav.ts` 一个文件含 12 处 `as unknown as`（:315–:436 连续区段），是导航项动态组装的绕检查模式。
- `contracts/generated/` 生成物 0 项债务；`vendor/thinking-orbs` 仅 6 项（本地已放宽 lint，维持现状合理）。

## 9. 可拆修复卡条目（建议）

| 卡 | 范围 | 代表位置（path:line） | 验收口径 |
| --- | --- | --- | --- |
| A·markdown 渲染器类型化 | `components/common/RichMarkdownRenderer.tsx`、`SimpleMarkdownRenderer.tsx`、`RichInlineMarkdown.tsx` | Rich:68,186,187; Simple:同理; Inline:70,72,78 | 引入 `mdast`/`hast` 类型与 react-markdown `Components` 泛型，消除 ~106 项 any 与 `COMPONENTS as any`；渲染快照/用例不变 |
| B·knowledge API client 收敛 | `features/knowledge/api/client.ts`（47 项） | 对齐 `web/contracts/generated/api.ts` 的 paths 类型，删除宽 Record 兜底 | client 返回类型全部来自生成物；`as` 数 ≤ 个位数且逐条注释 |
| C·settings-nav 双跳消除 | `features/settings/navigation/settings-nav.ts`（12 处 as unknown，:315–:436）+ `SettingsStore.tsx`（20 项） | settings-nav.ts:315,327,339,…,436 | 导航项用判别联合建模，删双跳；tsc strict 通过 |
| D·chat 流事件解析收窄 | `features/chat/ChatStateAdapter.tsx`（23）、`components/chat/home/AskUserOptions.tsx`（26）、`contracts/parse/turn-event.ts`（12）、`features/chat/transport/*` | ChatStateAdapter.tsx:1884,1889; AskUserOptions.tsx:热点行见 §3; turn-event.ts:60,109,132 | 解析函数返回 discriminated union + 运行时守卫；替换 `as unknown as` |
| E·非空断言分域清理 | 产品代码 66 项：`components/chat` 12、`lib/memory-graph.ts` 6、`partners` 5、`components/settings` 3、`app/(workspace)` 3、`components/reading` 4 等 | 见 §5 全量清单 | 逐条替换为显式判空/默认值；行为不变（vitest 现有用例回归） |
| F·lib API `as T` 边界收紧（与 AGEN-421 联动） | `lib/courses-api.ts:136,149`、`lib/guardian-api.ts:59`、`shared/api/client.ts:115`、`lib/reading-api.ts:166`、`lib/mastery-ws.ts:57,76,84` | 见 §7 交叉引用 | 校验（zod/手写守卫）后再返回；非法 body 走显式错误路径而非 `as T` |
| G·防新增闸门（可选） | `web/eslint.config.mjs` | 追加 `@typescript-eslint/no-explicit-any: warn`、`@typescript-eslint/no-unnecessary-type-assertion` | 先 warn 观察，Top 文件清零后升 error；不改运行时行为 |

## 10. 复现命令

```bash
node evidence/ts-types-2026-10-05/scan_ts_types.mjs   # 只读，AST 口径，输出本目录 JSON
# 交叉复核（口径不同，数量为参考）:
rg -n ':\s*any\b|as any\b|<any>' web -g '*.{ts,tsx}' -g '!node_modules' -g '!.next' | wc -l
rg -n '@ts-(ignore|expect-error|nocheck)' web -g '!node_modules' -g '!.next'
```

## 11. 产物

- `scan_ts_types.mjs` — 只读扫描脚本（TS 编译器 API）
- `ts_types_details.json` — 全部 1711 项命中（含 path:line、类型文本、代码行、test/generated/vendor 标记、去重标记）
- `ts_types_summary.json` — 汇总（总表、目录聚类、Top 文件、去重结果）

---
*报告由只读扫描生成（scan/ts-types-20261005 @ myfork）。争议以 `ts_types_details.json` 与源码现场为准。本卡不向上游开 PR。*
