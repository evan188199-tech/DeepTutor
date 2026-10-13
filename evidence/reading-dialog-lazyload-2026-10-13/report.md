# reading workspace 对话框懒加载契约覆盖面扫描

- 基线：`origin/main` @ `6cf793bd8`（release: v1.6.14，只读 worktree，无任何代码改动）
- 范围：`web/components/reading/**`（根目录 11 个组件 + `workspace/` 18 个 + `library/` 10 个）及其全部路由入口（`web/app/(workspace)/learning/reading/**`、`learning/watching/[sessionId]`）
- 说明：卡面所写 `web/features/reading` 在当前主干不存在；reading 组件实际位于 `web/components/reading`，`web/features/` 下仅 chat/knowledge/settings 等域。

## 契约定义（两级判定）

- **chunk 级**：组件经 `next/dynamic`（`ssr:false`）或运行时 `import()` 引入，代码拆出首屏路由 bundle；
- **挂载级**：仅在打开时条件渲染（`{open && <C/>}`），而非常驻树内用 `open` prop 控制。

两条同时满足 = 合规；chunk 静态 import 或常驻挂载记为偏差位点。

## 总览

| # | 组件/面板 | 加载方式 | 判定 | 位点 |
|---|---|---|---|---|
| 1 | ConversationLinkDialog | dynamic + 条件挂载 | 合规 | ReadingWorkspace.tsx:89-92, 816-844 |
| 2 | NotebookCaptureDialog | dynamic + 条件挂载 | 合规 | ReadingWorkspace.tsx:93-96, 846-855 |
| 3 | OrganizedNotesDialog | dynamic + 条件挂载 | 合规 | ReadingWorkspace.tsx:97-100, 857-862 |
| 4 | WorkspaceConfirmDialog | dynamic + 条件挂载 | 合规 | ReadingWorkspace.tsx:101-104, 760-774 |
| 5 | WorkspaceValueDialog（重命名/精通路径 ×2） | dynamic + 条件挂载 | 合规 | ReadingWorkspace.tsx:105-108, 776-788, 790-802 |
| 6 | MediaReadingStage（媒体重面板） | dynamic + 条件挂载 | 合规 | ReadingWorkspace.tsx:110-120, 694-708 |
| 7 | AddMaterialsDialog（workspace 内） | dynamic + 条件挂载 | 合规 | ReadingWorkspace.tsx:121-134, 804-814 |
| 8 | AddMaterialsDialog（folder 页） | 静态 import + 条件挂载 | **偏差 D1** | ReadingFolder.tsx:40, 326-336 |
| 9 | AddMaterialsDialog（materials 页） | 静态 import + 条件挂载 | **偏差 D2** | MaterialLibrary.tsx:39, 261-269 |
| 10 | FolderDialog（library 首页/folder 页） | 静态 import + 条件挂载 | 偏差 D7（轻量） | ReadingLibrary.tsx:46, 296-317; ReadingFolder.tsx:41, 337-347 |
| 11 | ReadingCompanion → ChatMessageList 等聊天链 | 静态 import（挂载条件 ✓） | **偏差 D3** | ReadingWorkspace.tsx:78; ReadingCompanion.tsx:34-39, 63-64 |
| 12 | SaveToNotebookModal | dynamic 但常驻挂载（open prop） | **偏差 D4** | ReadingCompanion.tsx:71-74, 504-509 |
| 13 | SessionViewerPanel | 静态 import + 常驻挂载 | **偏差 D5** | ReadingCompanion.tsx:36-38, 514-521 |
| 14 | SourceNavigator（内容导航重面板） | 静态 import + 常驻挂载（CSS 隐藏） | 偏差 D6 | ReadingWorkspace.tsx:618-668; SourceNavigator.tsx:213-216 |
| 15 | EpubDocumentView | dynamic + 条件挂载；epubjs 运行时 import | 合规 | ReaderPane.tsx:81-84, 1228-1246; EpubDocumentView.tsx:417 |
| 16 | PdfDocumentView（+PdfPage/AnnotationLayer） | 组件壳静态 import；pdf.js ~1.5MB 经 loader 运行时懒加载 | 偏差 D8（壳级，低） | ReaderPane.tsx:44-48, 1247-1260; lib/pdfjs-loader.ts:35-52 |
| 17 | TextUnitView | 静态 import + 按渲染模式条件挂载 | 合规（核心 reader 面） | ReaderPane.tsx:58, 1261-1280 |
| 18 | AnnotationList | 静态 import + 条件挂载 | 合规 | ReaderPane.tsx:41, 1283-1296; SourceNavigator.tsx:253-259 |
| 19 | AnnotationPopover | 静态 import + 条件挂载 | 合规 | ReaderPane.tsx:42, 1302-1316 |
| 20 | ReadingExtensionBar | 静态 import + 条件挂载 | 合规 | ReaderPane.tsx:49, 1197-1206 |
| 21 | AssignDialog / DeleteMaterialDialog / DeleteCollectionDialog | 文件内定义 + 条件挂载 | 合规（轻量，备注） | MaterialLibrary.tsx:261-289, 540, 674; ReadingLibrary.tsx:319-328, 558 |
| 22 | WorkspaceMenu / FolderTile 菜单 / companion 问题跳转弹层 | open state 条件渲染 | 合规 | WorkspaceMenu.tsx; ReadingLibrary.tsx:419-454; ReadingCompanion.tsx:368-394 |
| 23 | LegacyWatchingSession（watching 迁移页） | 路由静态 import，26 行 | 合规 | watching/[sessionId]/page.tsx:1 |

## 偏差位点明细与建议

### D1（高）folder 页首屏携带完整 AddMaterials 对话框链
- 位点：`web/components/reading/library/ReadingFolder.tsx:40`
- `AddMaterialsDialog`（780 行）静态 import，其内部又静态引入 `WatchingBrowser`（392 行，`AddMaterialsDialog.tsx:23`）及上传/Invidious 链路；全部进入 `learning/reading/folders/[folderId]` 首屏 chunk。挂载本身是条件的（ReadingFolder.tsx:326-336），仅 chunk 级偏差。
- 建议：改为 `dynamic(() => import("./AddMaterialsDialog").then(m => m.AddMaterialsDialog), { ssr: false, loading: … })`，对齐 `ReadingWorkspace.tsx:121-134` 的既有写法。

### D2（高）materials 页首屏同上
- 位点：`web/components/reading/library/MaterialLibrary.tsx:39`；条件挂载 `MaterialLibrary.tsx:261-269`（mode=upload）。
- 建议同 D1；两页共用同一条 dynamic 包装即可。

### D3（高）reading workspace 路由常驻打包聊天渲染全链
- 位点：`web/components/reading/workspace/ReadingWorkspace.tsx:78`（静态引入 ReadingCompanion）→ `ReadingCompanion.tsx:34`（ChatMessageList，2432 行）、`:35`（SessionActivityPanel 构建器，571 行）、`:36-38`（SessionViewerPanel，1381 行）、`:39`（ChatViewerBridges）、`:63-64`（ReadingComposer → StandaloneComposer 1048 行）。
- companion 打开是条件的（`ReadingWorkspace.tsx:745-757`），挂载级合规；但只要进入阅读 workspace，上述聊天消息渲染/追踪/附件链路就随路由 chunk 下载，学习者全程不开 companion 时纯属闲置。
- 建议：把 `ReadingCompanion` 在 `ReadingWorkspace.tsx:78` 改为 `dynamic(..., { ssr:false, loading: 骨架 })`，条件渲染保持不变即自动触发懒加载；改动最小、无需动 companion 内部。

### D4（中）SaveToNotebookModal 常驻挂载
- 位点：`web/components/reading/workspace/ReadingCompanion.tsx:504-509`
- 已 dynamic 拆 chunk（`:71-74`），但以 `open={showSaveModal}` 常驻挂载：companion 一挂载就拉取并执行该 710 行模态（`next/dynamic` 在首次渲染时即触发 import），而非点「保存到笔记本」时。
- 建议：`{showSaveModal && <SaveToNotebookModal … onClose={() => setShowSaveModal(false)} />}`，去掉 `open` prop 依赖（与 workspace 五对话框的挂载级契约一致）。

### D5（中）SessionViewerPanel 常驻挂载
- 位点：`web/components/reading/workspace/ReadingCompanion.tsx:514-521`
- 静态 import + 常驻挂载（`open={viewerOpen}`）；关闭时面板仍留在树内（`SessionViewerPanel.tsx:679` 以 `open && entered` 控制可见性），1381 行组件及其 previewer/quiz/geogebra 上下文持续存活。
- 建议：条件挂载，或在面板内部 `if (!open) return null`（保留 ref/bridges 需求时用前者并同步 ChatViewerBridges 的挂载条件）。

### D6（低-中）SourceNavigator 常驻挂载、CSS 隐藏
- 位点：`web/components/reading/workspace/ReadingWorkspace.tsx:618-668`（始终渲染）+ `SourceNavigator.tsx:213-216`（关闭时仅 `hidden` class）。
- 681 行、轻依赖（无重组件），但关闭状态下搜索过滤、材料树、书签映射仍随每次渲染执行。
- 建议：内部 `if (!open) return null` 或外层条件挂载；工作量小，行为差异点是关闭时丢失内部滚动/搜索草稿状态（现版本关闭后状态本就在，收紧前需确认产品预期）。

### D7（低）FolderDialog 静态打包
- 位点：`ReadingLibrary.tsx:46`（296-317 条件挂载）、`ReadingFolder.tsx:41`（337-347 条件挂载）。
- 仅 210 行、无重组件；收益有限，统一契约时顺带处理即可。

### D8（低）PdfDocumentView 组件壳与 EPUB 处理不一致
- 位点：`ReaderPane.tsx:44-48` 静态 import vs `:81-84` EpubDocumentView dynamic。
- pdf.js 重库（~1.5MB）已经 `lib/pdfjs-loader.ts:35-52` 运行时懒加载，偏差残留仅为 PdfDocumentView/PdfPage/AnnotationLayer 组件壳（约 860 行源码）进入 reader chunk。reader 本身是路由核心面，属可接受项；如追求一致可将壳也 dynamic 化。
- 同类观察：TextUnitView 静态引入 `RichMarkdownRenderer`（其 math/html/mermaid 插件均已懒加载，`RichMarkdownRenderer.tsx:146-158, 432`），文本/EPUB/PDF 三视图只有 EPUB 走了 dynamic。

### 备注
- `MaterialLibrary.tsx:540,674` 与 `ReadingLibrary.tsx:558` 的对话框为文件内定义，天然与页面同 chunk；均轻量且条件挂载，符合挂载级契约，可不处理。
- `ReaderPane.tsx:37` 的 ReaderPane 本体、`WorkspaceChrome`、`ReadAloudButton` 为工作台骨架件，静态属预期。
- 未发现 reading 组件被 chat/其他页面静态反向引入（全仓 grep 仅 reading/watching 路由与测试引用），不存在跨域传染。

## 结论

- 覆盖：`web/components/reading` 全部 39 个文件 × 4 个 reading 路由 + watching 迁移页；对话框/重面板 23 项全部判定（上表）。
- workspace 会话页（`[workspaceId]`）的对话框契约已基本达标（5 对话框 + 媒体面板 + 添加素材均 dynamic + 条件挂载）。
- 剩余偏差 8 处：chunk 级 4 处（D1/D2/D3/D8）、挂载级 4 处（D4/D5/D6/D7，其中 D7 兼 chunk 级）。优先级 D1=D2=D3 > D4=D5 > D6 > D7=D8。
- 本次为只读扫描：未修改任何源码，未启动服务，未产生测试进程。
