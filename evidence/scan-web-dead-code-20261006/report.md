# web/ 前端死代码只读清点（AGEN-923）

- 基线：`origin/main` @ `f07029cfcf2c8dfccdb671cdfc343db8334f5741`（release: v1.6.13），只读扫描，未改任何产品代码
- 范围：`web/**/*.{ts,tsx}` 共 1237 个文件（生产 871 / 测试 348），Node + TypeScript compiler API（5.9.3）AST 解析
- 脚本：`scan_web_dead_code.mjs`（stdlib-only，除 TS 编译器外零依赖）；报告由 `make_report.mjs` 确定性生成
- 机器数据：`data/*.json`（重跑 SHA256 一致，见「哈希自证」）

## 口径（判定规则）

1. **导入图**：解析全部 static import、`export … from` 具名/通配重导出、动态 `import("…")`（含 next/dynamic、React.lazy 场景）；具名重导出链做传递闭包（迭代上限 20 轮）。`import * as ns` 与 `export * from` 视为「通配消费」——被通配覆盖的导出**不**判死（保守，宁漏勿误）。
2. **消费者分级**：prod（生产代码）/ test（`tests/**`、`*.spec|test.*`）/ script（`scripts/**`）。仅测试或脚本引用的单独标注。
3. **排除项**：Next.js 约定文件（page/layout/route/loading/error/... 及 metadata、GET/POST 等 framework 导出）、`contracts/generated`、`vendor`、`.d.ts`、配置文件（`*.config.*`）。
4. **未用导出**：导出符号无任何 prod 直接导入、无通配覆盖；「高」= 全仓（含测试/脚本）零引用且符号名无其他 token 出现；「中」= 仅测试/脚本引用、或存在同名 token（动态引用风险）、或仅内部使用（只需去掉 export 关键字）。default 导出与 `export default X` 声明名做合并判定。
5. **未挂载组件**：TSX/组件目录中导出的大写组件（function/class，或初始化器含 JSX 的 const）。挂载判定：任意文件以 `<Name` JSX 出现，或经 default 导出链（`export { default } from` / 动态 import）存活。「高」= 零导入零 JSX 零 token；「低」= 有 prod 导入但全仓无 JSX 直接挂载（可能经组件 map 间接渲染，如 `agentGlyph(kind)` → `const G = …; <G/>` 模式，需人工确认）。
6. **未引用工具函数**：导出 `function` 且符号名在全仓其他文件零 token（排除 Next 入口组件与 default 绑定）。
7. **孤儿 locale key**：i18n 为 `keySeparator:false` 单 `app` 命名空间；key 判定 = 全仓（prod+test）字符串字面量精确匹配（覆盖 `labelKey` 式动态取值）；`t(\`前缀.…\`)` 模板提取静态前缀，命中前缀的 key 不判死。精确匹配偏保守，会把少量「纯文案巧合」计为已引用。
8. 字符串 token 交叉核对用于风险标注（`name_elsewhere_n`），不做判活依据。

## 去重（对齐既有扫描轴）

- **scan-dead-code（Python 轴，AGEN-548）**：本卡为 web/ TS/TSX 轴，不重复其 Python 结论。TS 导出轴交叉比对：AGEN-548 数据 @ myfork `agent/agen548-deadcode-scan` @ `5fc16824c525bded9db059ce02f8e2b90c92f8bf`（同基线 commit）。其 TS 未消费导出 1188 条中，与本卡结论**精确命中（同 file::name::line）13 条、同名命中 589 条、本卡新发现 50 条**（新发现主要来自：default 链路解析、内部使用区分、更严的通配豁免）。文件轴：本卡 10 个未用文件中 8 个与其重合（`components/space/learning/CoverageNotice.tsx`、`shared/api/runtime.ts`为新发现/口径差异）。
- **scan-ts-types（AGEN-664，类型轴）**：只覆盖 @ts-ignore/any/as-cast 等类型债，与死代码轴不重叠；本卡 `isType` 未用类型导出（376 条）为其相邻补充。
- **scan-web-api-usage（AGEN-857，API 调用面）**：其 `lib/*-api.ts` 死参数、漂移结论与本卡 `lib/*-api.ts` 未消费导出清点互补；删除 lib/api 客户端函数前应同时对照该卡 F1/F2（`features/knowledge/api/client.ts:505,524`、`client.ts:293` 仍在用）。

## 总计

| 类别 | 数量 | 高置信 | 中置信 | 低置信 |
|---|---|---|---|---|
| A. 未用文件（整文件候选） | 10（1052 行） | 10 | 0 | 0 |
| B. 未消费导出 | 652 | 64 | 588 | 0 |
| C. 未挂载组件（符号） | 38 | 13 | 0 | 25 |
| D. 未引用工具函数 | 94 | 94 | 0 | 0 |
| E. 孤儿 locale key | 5287（另 4 个 common.json 整文件未注册，148 key） | 148（common.json 整文件） | 其余 | 0 |

## Top 项（按删除收益）

| # | 目标 | 类型 | 规模 | 置信度 |
|---|---|---|---|---|
| 1 | `locales/{en,zh,de,fr}/common.json` 整文件（i18n 运行时只注册 `app` 命名空间，common 从未加载） | locale 文件 | 4×37 key | 高 |
| 2 | `lib/learning-api.ts` 未消费导出 28 个 | 导出组 | 见清单 | 混合 |
| 3 | `lib/reading-api.ts` 未消费导出 15 个 | 导出组 | 见清单 | 混合 |
| 4 | `lib/partners-api.ts` 未消费导出 13 个 | 导出组 | 见清单 | 混合 |
| 5 | `lib/notebook-api.ts` 未消费导出 12 个 | 导出组 | 见清单 | 混合 |
| 6 | `components/settings/ConnectionsEditor.tsx` 整文件（0 导入） | 文件 | 763 行 | 高 |
| 7 | 死组件 13 个（零引用零挂载，见 C 表） | 组件 | — | 高 |
| 8 | `lib/memory-graph.ts` 未消费导出 11 个 | 导出组 | 见清单 | 混合 |

## A. 未用文件（整文件候选，置信度：高）

| 文件 | 行数 | 备注 |
|---|---|---|
| `components/settings/ConnectionsEditor.tsx` | 763 |  |
| `components/settings/TaskModelsEditor.tsx` | 101 |  |
| `components/space/learning/CoverageNotice.tsx` | 91 |  |
| `components/workspaces/WorkspaceSwitcher.tsx` | 70 |  |
| `features/knowledge/components/engines/GraphRagForm.tsx` | 2 |  |
| `features/knowledge/components/engines/ImaForm.tsx` | 2 |  |
| `features/knowledge/components/engines/LightRagForm.tsx` | 2 |  |
| `features/knowledge/components/engines/LlamaIndexForm.tsx` | 2 |  |
| `i18n/index.ts` | 5 |  |
| `shared/api/runtime.ts` | 14 |  |

## B. 未消费导出（652 条；完整机器数据 `data/unused_exports.json`）

### B1. 高置信（64 条，生产/测试/脚本零引用，符号可整段删除）

- `components/chat/home/ComposerInput.tsx:141` `shouldOpenSlashPopup`（function）— 高
- `components/chat/home/MasteryQuestionCard.tsx:335` `default`（default）— 高
- `components/knowledge/PageIndexSettingsModal.tsx:183` `PageIndexSettingsModal`（function）— 高
- `components/memory/MemorySection.tsx:264` `MemorySection`（function）— 高
- `components/settings/ConnectionsEditor.tsx:762` `default`（default）— 高
- `components/settings/TaskModelsEditor.tsx:100` `default`（default）— 高
- `components/settings/TaskModelsWorkspace.tsx:285` `default`（default）— 高
- `components/settings/WorkspaceShell.tsx:273` `WorkspaceFieldGroup`（function）— 高
- `components/settings/shared.tsx:88` `formatContextWindowUpdatedAt`（function）— 高
- `components/settings/shared.tsx:111` `activeModelDetail`（function）— 高
- `components/space/learning/CoverageNotice.tsx:22` `CoverageNotice`（function）— 高
- `components/workspaces/WorkspaceSwitcher.tsx:11` `WorkspaceSwitcher`（function）— 高
- `contracts/parse/turn-command.ts:88` `buildSubscribeSession`（function）— 高
- `contracts/parse/turn-command.ts:129` `buildRegenerate`（function）— 高
- `contracts/parse/turn-command.ts:160` `buildUserInput`（function）— 高
- `contracts/parse/turn-command.ts:174` `buildCheckActiveTurn`（function）— 高
- `contracts/parse/turn-command.ts:184` `buildUnsubscribe`（function）— 高
- `features/chat/trace/ActivityOrb.tsx:46` `ChatActivityOrb`（function）— 高
- `features/settings/navigation/settings-nav.ts:107` `visibleSettingsChildren`（function）— 高
- `features/settings/navigation/settings-scroll.ts:5` `SettingsAnchorEvent`（type, type）— 高
- `features/settings/navigation/settings-scroll.ts:8` `requestSettingsSection`（function）— 高
- `features/settings/navigation/settings-scroll.ts:21` `scrollToSettingsSection`（function）— 高
- `hooks/useKnowledgeBases.ts:502` `UseKnowledgeBasesReturn`（type, type）— 高
- `hooks/useKnowledgeHistory.ts:149` `UseKnowledgeHistoryReturn`（type, type）— 高
- `hooks/useTopicSourceLibrary.ts:79` `KnowledgeBaseFiles`（type, type）— 高
- `lib/book-errors.ts:32` `KNOWN_BOOK_ERROR_CODES`（const）— 高
- `lib/book-references.ts:36` `countSelectedBookPages`（function）— 高
- `lib/chat-import/agent-store.ts:139` `getAgent`（function）— 高
- `lib/co-writer-events.ts:23` `subscribeCoWriterChanges`（function）— 高
- `lib/guardian-api.ts:147` `saveGuardianMaterials`（function）— 高
- `lib/guardian-api.ts:170` `saveGuardianRestrictions`（function）— 高
- `lib/knowledge-helpers.ts:318` `isSubagentKb`（const）— 高
- `lib/knowledge-helpers.ts:362` `kbSupportsLinkedFolders`（const）— 高
- `lib/learning-api.ts:45` `fetchProgress`（function）— 高
- `lib/learning-api.ts:51` `initModules`（function）— 高
- `lib/learning-api.ts:162` `fetchMasteryMap`（function）— 高
- `lib/learning-api.ts:337` `fetchAllProgress`（function）— 高
- `lib/learning-api.ts:362` `skipPendingQuestion`（function）— 高
- `lib/learning-api.ts:373` `importFromBook`（function）— 高
- `lib/learning-api.ts:391` `generateModulesFromNotebook`（function）— 高
- `lib/learning-api.ts:694` `generateMasteryTopicDraft`（function）— 高
- `lib/message-branches.ts:246` `latestChildId`（function）— 高
- `lib/message-content.ts:1` `MessageContentItem`（type, type）— 高
- `lib/model-settings.ts:19` `MODEL_SERVICE_LABELS`（const）— 高
- `lib/notebook-api.ts:379` `getNotebookEntry`（function）— 高
- `lib/notebook-api.ts:412` `lookupNotebookEntryByOrigin`（function）— 高
- `lib/partner-groups-api.ts:183` `getPartnerGroupInvocations`（function）— 高
- `lib/pdfjs-loader.ts:30` `PdfPageProxy`（type, type）— 高
- `lib/profile-api.ts:22` `setOwnLearnerProfile`（function）— 高
- `lib/quiz-question-type.ts:67` `isFreeTextQuizQuestion`（function）— 高
- `lib/reading-api.ts:233` `getSupportedFormats`（function）— 高
- `lib/reading-api.ts:269` `deleteMaterial`（function）— 高
- `lib/reading-api.ts:489` `listReadingQuizRewards`（function）— 高
- `lib/reading-quote-locator.ts:239` `segmentTextByQuotes`（function）— 高
- `lib/reading-turn-state.ts:19` `READING_CAPABILITY`（const）— 高
- `lib/reading-workspace-api.ts:324` `createReadingConversation`（function）— 高
- `lib/research-types.ts:34` `normalizeResearchConfig`（function）— 高
- `lib/sidebar-layout.ts:41` `DEFAULT_NAV_LAYOUT`（const）— 高
- `lib/theme.ts:105` `initializeTheme`（function）— 高
- `lib/video-learning-api.ts:378` `saveVideoLearningSettings`（function）— 高
- `lib/video-learning-marks.ts:8` `VIDEO_MARK_KINDS`（const）— 高
- `lib/video-learning-marks.ts:130` `cuesToSegmentLocators`（function）— 高
- `lib/visualize-types.ts:6` `VisualizeRenderType`（type, type）— 高
- `shared/ui/Button.tsx:76` `default`（default）— 高

### B2. 中置信（588 条，需人工复核后处理）

- `app/(workspace)/learning/books/components/BookChatPanel.tsx:66` `BookChatPanelProps`（interface）— 中（内部使用×2（仅去 export））
- `app/(workspace)/learning/books/components/BookCreator.tsx:60` `BookCreatorProps`（interface）— 中（内部使用×2（仅去 export））
- `app/(workspace)/learning/books/components/BookGenerationActivity.tsx:18` `BookGenerationActivityProps`（interface）— 中（内部使用×2（仅去 export））
- `app/(workspace)/learning/books/components/BookHealthBanner.tsx:10` `BookHealthBannerProps`（interface）— 中（内部使用×2（仅去 export））
- `app/(workspace)/learning/books/components/BookLibrary.tsx:71` `BookLibraryProps`（interface）— 中（内部使用×2（仅去 export））
- `app/(workspace)/learning/books/components/BookPausedBanner.tsx:8` `BookPausedBannerProps`（interface）— 中（内部使用×2（仅去 export））
- `app/(workspace)/learning/books/components/BookSidebar.tsx:55` `BookSidebarProps`（interface）— 中（内部使用×2（仅去 export））
- `app/(workspace)/learning/books/components/PageOutlineNav.tsx:90` `PageOutlineNavProps`（interface）— 中（内部使用×2（仅去 export））
- `app/(workspace)/learning/books/components/PageReader.tsx:84` `PageReaderProps`（interface）— 中（内部使用×2（仅去 export））
- `app/(workspace)/learning/books/components/SpineEditor.tsx:105` `SpineEditorProps`（interface）— 中（内部使用×2（仅去 export））
- `app/(workspace)/learning/books/components/blocks/AnimationBlock.tsx:11` `AnimationBlockProps`（interface）— 中（内部使用×2（仅去 export））
- `app/(workspace)/learning/books/components/blocks/BlockBodyEditor.tsx:7` `BlockBodyEditorProps`（interface）— 中（内部使用×2（仅去 export））
- `app/(workspace)/learning/books/components/blocks/BlockRenderer.tsx:64` `BlockRendererProps`（interface）— 中（内部使用×2（仅去 export））
- `app/(workspace)/learning/books/components/blocks/CalloutBlock.tsx:41` `CalloutBlockProps`（interface）— 中（内部使用×2（仅去 export））
- `app/(workspace)/learning/books/components/blocks/CodeBlock.tsx:6` `CodeBlockProps`（interface）— 中（内部使用×2（仅去 export））
- `app/(workspace)/learning/books/components/blocks/ConceptGraphBlock.tsx:12` `ConceptGraphBlockProps`（interface）— 中（内部使用×2（仅去 export））
- `app/(workspace)/learning/books/components/blocks/DeepDiveBlock.tsx:14` `DeepDiveBlockProps`（interface）— 中（内部使用×2（仅去 export））
- `app/(workspace)/learning/books/components/blocks/FigureBlock.tsx:12` `FigureBlockProps`（interface）— 中（内部使用×2（仅去 export））
- `app/(workspace)/learning/books/components/blocks/FlashCardsBlock.tsx:14` `FlashCardsBlockProps`（interface）— 中（内部使用×2（仅去 export））
- `app/(workspace)/learning/books/components/blocks/InteractiveBlock.tsx:9` `InteractiveBlockProps`（interface）— 中（内部使用×2（仅去 export））
- `app/(workspace)/learning/books/components/blocks/PlaceholderBlock.tsx:7` `PlaceholderBlockProps`（interface）— 中（内部使用×2（仅去 export））
- `app/(workspace)/learning/books/components/blocks/QuizBlock.tsx:39` `QuizBlockProps`（interface）— 中（内部使用×2（仅去 export））
- `app/(workspace)/learning/books/components/blocks/SectionBlock.tsx:8` `SectionBlockProps`（interface）— 中（内部使用×2（仅去 export））
- `app/(workspace)/learning/books/components/blocks/TextBlock.tsx:6` `TextBlockProps`（interface）— 中（内部使用×2（仅去 export））
- `app/(workspace)/learning/books/components/blocks/TimelineBlock.tsx:11` `TimelineBlockProps`（interface）— 中（内部使用×2（仅去 export））
- `app/(workspace)/learning/books/components/blocks/UserNoteBlock.tsx:11` `UserNoteBlockProps`（interface）— 中（内部使用×2（仅去 export））
- `components/Geogebra.tsx:15` `GeogebraPayload`（interface）— 中（内部使用×2（仅去 export））
- `components/access/RequireCapability.tsx:15` `LockedFeatureNotice`（function）— 中（内部使用×2（仅去 export））
- `components/agents/agent-icons.tsx:210` `PartnerGlyph`（function）— 中（内部使用×2（仅去 export））
- `components/agents/agent-icons.tsx:225` `AgentGlyph`（type）— 中（内部使用×2（仅去 export））
- `components/chat/home/AskUserOptions.tsx:34` `AskUserOption`（interface）— 中（内部使用×5（仅去 export））
- `components/chat/home/AskUserOptions.tsx:39` `AskUserQuestion`（interface）— 中（仅test引用）
- `components/chat/home/AskUserOptions.tsx:49` `AskUserPayload`（interface）— 中（内部使用×7（仅去 export））
- `components/chat/home/AskUserOptions.tsx:54` `AskUserAnswer`（interface）— 中（内部使用×7（仅去 export））
- `components/chat/home/AskUserOptions.tsx:68` `AskUserCardData`（interface）— 中（仅test引用）
- `components/chat/home/CapabilityConfigCard.tsx:29` `ConfigurableCapability`（type）— 中（内部使用×3（仅去 export））
- `components/chat/home/ComposerInput.tsx:112` `shouldOpenAtPopup`（function）— 中（内部使用×3（仅去 export））
- `components/chat/home/ComposerInput.tsx:117` `stripTrailingAtMention`（function）— 中（内部使用×2（仅去 export））
- `components/chat/home/ComposerInput.tsx:122` `atMentionQuery`（function）— 中（内部使用×3（仅去 export））
- `components/chat/home/ComposerInput.tsx:130` `matchingSlashCommands`（function）— 中（内部使用×3（仅去 export））
- `components/chat/home/ContextBudgetChip.tsx:6` `ContextBudgetSegment`（type）— 中（内部使用×2（仅去 export））
- `components/chat/home/StandaloneComposer.tsx:1048` `StandaloneComposerProps`（reexport-local-type）— 中（内部使用×3（仅去 export））
- `components/chat/preview/previewerFor.ts:13` `PreviewKind`（type）— 中（内部使用×2（仅去 export））
- `components/chat/preview/previewers/useBinarySource.ts:11` `BinarySourceState`（type）— 中（内部使用×3（仅去 export））
- `components/chat/preview/previewers/useTextSource.ts:8` `TextSourceState`（type）— 中（内部使用×3（仅去 export））
- `components/common/InlineFileCard.tsx:49` `extractStreamedArtifacts`（function）— 中（仅test引用）
- `components/common/PickerShell.tsx:60` `PickerShellProps`（interface）— 中（内部使用×2（仅去 export））
- `components/common/code-block-themes.ts:111` `CodeBlockThemeOption`（interface）— 中（内部使用×2（仅去 export））
- `components/common/code-block-themes.ts:183` `DEFAULT_CODE_BLOCK_THEME_ID`（const）— 中（仅test引用）
- `components/courses/CourseScope.tsx:32` `CourseScope`（interface）— 中（内部使用×3（仅去 export））
- `components/knowledge/IndexingModelSelector.tsx:25` `selectionFromLLMOption`（function）— 中（仅test引用）
- `components/knowledge/LightRagRoleModelsEditor.tsx:22` `inheritedRole`（const）— 中（内部使用×5（仅去 export））
- `components/mcp/KeyValueEditor.tsx:13` `isStoredCredential`（function）— 中（仅test引用）
- `components/mcp/surface.ts:41` `McpWriteStyle`（type）— 中（内部使用×2（仅去 export））
- `components/memory/MemoryGraph.tsx:992` `GraphNode`（reexport-local-type）— 中（内部使用×12（仅去 export））
- `components/memory/MemoryGraph.tsx:992` `GraphEdge`（reexport-local-type）— 中（内部使用×4（仅去 export））
- `components/memory/MemoryL1Workbench.tsx:55` `MemoryL1WorkbenchProps`（interface）— 中（内部使用×2（仅去 export））
- `components/memory/MemorySection.tsx:649` `L1ViewProps`（interface）— 中（内部使用×2（仅去 export））
- `components/memory/MemoryWorkbench.tsx:172` `MemoryWorkbenchProps`（interface）— 中（内部使用×2（仅去 export））
- `components/memory/useMemoryRun.ts:12` `RunStatus`（type）— 中（内部使用×4（仅去 export））
- `components/memory/useMemoryRun.ts:14` `RunHandle`（interface）— 中（内部使用×6（仅去 export））
- `components/memory/useMemoryRun.ts:27` `RunEventPayload`（interface）— 中（内部使用×4（仅去 export））
- `components/memory/useMemoryRun.ts:38` `StartArgs`（interface）— 中（内部使用×2（仅去 export））
- `components/notebook/useNotebookLibrary.ts:26` `NotebookLibrary`（interface）— 中（内部使用×2（仅去 export））
- `components/notebook/useNotebookLibrary.ts:54` `NotebookDetailState`（interface）— 中（内部使用×3（仅去 export））
- `components/partners/FaceEditor.tsx:17` `FACE_EMOJIS`（const）— 中（内部使用×2（仅去 export））
- `components/partners/group/GroupRound.tsx:250` `Seat`（reexport-local-type）— 中（内部使用×2（仅去 export））
- `components/partners/group/mentions.ts:19` `ResolvedMentions`（interface）— 中（内部使用×2（仅去 export））
- `components/partners/group/mentions.ts:126` `EVERYONE_TOKENS`（reexport-local）— 中（内部使用×3（仅去 export））
- `components/partners/group/useGroupSession.ts:33` `SeatStatus`（type）— 中（内部使用×2（仅去 export））
- `components/partners/schema-form.tsx:26` `resolveSchemaVariant`（function）— 中（内部使用×3（仅去 export））
- `components/partners/schema-form.tsx:37` `isNullable`（function）— 中（内部使用×3（仅去 export））
- `components/quiz/FollowupChatComposer.tsx:171` `FollowupChatComposerProps`（reexport-local-type）— 中（内部使用×3（仅去 export））
- `components/reading/AnnotationLayer.tsx:20` `AnnotationLayerProps`（interface）— 中（内部使用×2（仅去 export））
- `components/reading/AnnotationList.tsx:22` `AnnotationListProps`（interface）— 中（内部使用×2（仅去 export））
- `components/reading/AnnotationPopover.tsx:20` `AnnotationPopoverProps`（interface）— 中（内部使用×2（仅去 export））
- `components/reading/EpubDocumentView.tsx:145` `EpubDocumentViewProps`（interface）— 中（内部使用×2（仅去 export））
- `components/reading/EpubDocumentView.tsx:167` `EpubDocumentView`（function）— 中（仅test引用）
- `components/reading/PdfDocumentView.tsx:56` `PdfDocumentViewProps`（interface）— 中（仅test引用）
- `components/reading/PdfPage.tsx:9` `PdfPageProps`（interface）— 中（内部使用×2（仅去 export））
- `components/reading/ReaderPane.tsx:107` `ReaderPaneProps`（interface）— 中（内部使用×2（仅去 export））
- `components/reading/TextUnitView.tsx:61` `TextUnitViewProps`（interface）— 中（内部使用×2（仅去 export））
- `components/reading/library/AddMaterialsDialog.tsx:61` `AddMaterialsMode`（type）— 中（内部使用×2（仅去 export））
- `components/reading/workspace/MediaReadingStage.tsx:50` `MediaReadingStage`（function）— 中（仅test引用）
- `components/reading/workspace/SourceNavigator.tsx:574` `WorkspaceOutlineBranch`（function）— 中（内部使用×3（仅去 export））
- `components/reading/workspace/WorkspaceMenu.tsx:15` `WorkspaceMenuSections`（type）— 中（内部使用×4（仅去 export））
- `components/reading/workspace/dialogs.tsx:22` `ModalShell`（function）— 中（内部使用×11（仅去 export））
- `components/settings/ConnectionsEditor.tsx:82` `ConnectionsEditor`（function）— 中（内部使用×2（仅去 export））
- `components/settings/ModelCards.tsx:233` `UseRow`（function）— 中（内部使用×3（仅去 export））
- `components/settings/TaskModelsEditor.tsx:10` `TaskModelsEditor`（function）— 中（内部使用×2（仅去 export））
- `components/settings/codex-profile.ts:8` `CODEX_MANAGED_BY`（const）— 中（仅test引用）
- `components/settings/search-providers.ts:16` `SearchProviderFieldSpec`（type）— 中（内部使用×3（仅去 export））
- `components/settings/shared.tsx:24` `fieldControlClass`（const）— 中（内部使用×3（仅去 export））
- `components/settings/shared.tsx:123` `labelClass`（function）— 中（同名token×4）
- `components/sidebar/SessionAvatar.tsx:146` `SessionKind`（type）— 中（内部使用×4（仅去 export））
- `components/sidebar/nav-entries.ts:16` `NavEntry`（interface）— 中（内部使用×3（仅去 export））
- `components/sidebar/nav-entries.ts:35` `PRIMARY_NAV`（const）— 中（内部使用×4（仅去 export））
- `components/space/ChatHistorySection.tsx:49` `ChatHistorySectionProps`（interface）— 中（内部使用×2（仅去 export））
- `components/space/ScopePicker.tsx:18` `ScopePickerProps`（interface）— 中（内部使用×2（仅去 export））
- `components/space/SpaceDashboard.tsx:254` `visibleGroups`（function）— 中（仅test引用）
- `components/space/SpaceDashboard.tsx:270` `DASHBOARD_GROUPS`（reexport-local）— 中（仅test引用）
- `components/space/learning/route-draft.ts:3` `RouteDraftIssue`（type）— 中（内部使用×3（仅去 export））
- `components/space/question-bank/useQuestionBank.ts:44` `DEFAULT_SCOPE`（const）— 中（内部使用×3（仅去 export））
- `components/space/question-bank/useQuestionBank.ts:58` `buildQuestionBankFilter`（function）— 中（仅test引用）
- `components/space/question-bank/useQuestionBank.ts:81` `QuestionBankController`（interface）— 中（内部使用×2（仅去 export））
- `components/watching/WatchingMarksPanel.tsx:26` `WatchingMarksPanel`（function）— 中（同名token×1）
- `components/workspaces/WorkspaceChatGroups.tsx:209` `WorkspaceChatGroups`（function）— 中（仅test引用）
- `context/GeogebraTabContext.tsx:32` `GeogebraTabController`（interface）— 中（内部使用×4（仅去 export））
- `context/QuizFollowupContext.tsx:45` `FollowupMessage`（interface）— 中（内部使用×2（仅去 export））
- `context/QuizFollowupContext.tsx:57` `FollowupThreadState`（interface）— 中（内部使用×14（仅去 export））
- `context/QuizFollowupContext.tsx:68` `createEmptyThreadState`（function）— 中（内部使用×5（仅去 export））
- `context/QuizFollowupContext.tsx:119` `SendMessageInput`（interface）— 中（内部使用×3（仅去 export））
- `context/QuizFollowupContext.tsx:146` `HydratedFollowupMessage`（interface）— 中（内部使用×3（仅去 export））
- `context/QuizFollowupContext.tsx:152` `QuizFollowupController`（interface）— 中（内部使用×4（仅去 export））
- `context/ReadingContext.tsx:45` `ReadingContextValue`（interface）— 中（内部使用×4（仅去 export））
- `context/app-shell-storage.ts:77` `CHAT_RESPONSE_TIMEOUT_STORAGE_KEY`（const）— 中（内部使用×3（仅去 export））
- `contracts/parse/turn-command.ts:76` `buildSubscribeTurn`（function）— 中（仅test引用）
- `contracts/parse/turn-command.ts:117` `buildCancelTurn`（function）— 中（仅test引用）
- `contracts/parse/turn-command.ts:141` `buildSubmitUserReply`（function）— 中（仅test引用）
- `contracts/parse/turn-event.ts:11` `ParseResult`（type）— 中（内部使用×3（仅去 export））
- `features/capabilities/model.ts:1` `CapabilityManifest`（interface）— 中（内部使用×2（仅去 export））
- `features/capabilities/model.ts:8` `CapabilityConfigSchema`（interface）— 中（内部使用×5（仅去 export））
- `features/capabilities/model.ts:15` `CapabilityFieldSchema`（interface）— 中（内部使用×3（仅去 export））
- `features/capabilities/model.ts:81` `CapabilityConfigResult`（type）— 中（内部使用×2（仅去 export））
- `features/capabilities/model.ts:120` `sanitizeCapabilityConfig`（function）— 中（仅test引用）
- `features/capabilities/presentation.tsx:34` `ToolDef`（interface）— 中（内部使用×2（仅去 export））
- `features/capabilities/presentation.tsx:61` `ChatCapabilityDef`（interface）— 中（内部使用×7（仅去 export））
- `features/capabilities/presentation.tsx:69` `CHAT_CAPABILITIES`（const）— 中（仅test引用）
- `features/capabilities/presentation.tsx:184` `VISIBLE_CHAT_CAPABILITIES`（const）— 中（仅test引用）
- `features/capabilities/presentation.tsx:192` `WORKSPACE_CHAT_CAPABILITIES`（const）— 中（仅test引用）
- `features/capabilities/useCapabilityCatalog.ts:62` `CapabilityFilter`（type）— 中（内部使用×2（仅去 export））
- `features/chat/ChatStateAdapter.tsx:133` `SendMessageOptions`（interface）— 中（内部使用×3（仅去 export））
- `features/chat/ChatStateAdapter.tsx:169` `emptyResourceSelection`（function）— 中（内部使用×4（仅去 export））
- `features/chat/ChatStateAdapter.tsx:173` `ChatState`（interface）— 中（内部使用×4（仅去 export））
- `features/chat/ChatStateAdapter.tsx:312` `ReadingSelectionSnapshot`（interface）— 中（内部使用×4（仅去 export））
- `features/chat/ChatStateAdapter.tsx:1585` `hydrateMessageAttachments`（function）— 中（仅test引用）
- `features/chat/controllers/buildStartTurnInput.ts:126` `legacySendMessageInput`（function）— 中（仅test引用）
- `features/chat/controllers/pending-attachments.ts:17` `AttachmentRejectionReason`（type）— 中（内部使用×2（仅去 export））
- `features/chat/controllers/pending-attachments.ts:22` `AttachmentRejection`（interface）— 中（内部使用×3（仅去 export））
- `features/chat/controllers/useChatRouteSession.ts:6` `routeSessionId`（function）— 中（仅test引用）
- `features/chat/controllers/useChatRouteSession.ts:11` `shouldRevalidateCachedSession`（function）— 中（仅test引用）
- `features/chat/messages/usage-summary.ts:24` `CallUsage`（interface）— 中（内部使用×2（仅去 export））
- `features/chat/messages/usage-summary.ts:31` `combineUsage`（function）— 中（仅test引用）
- `features/chat/model/protocol.ts:25` `ClientCommand`（type）— 中（内部使用×2（仅去 export））
- `features/chat/model/protocol.ts:26` `ServerEvent`（type）— 中（内部使用×2（仅去 export））
- `features/chat/model/protocol.ts:50` `SubscribeTurnMessage`（type）— 中（内部使用×2（仅去 export））
- `features/chat/model/protocol.ts:54` `SubscribeSessionMessage`（type）— 中（内部使用×2（仅去 export））
- `features/chat/model/protocol.ts:58` `ResumeTurnMessage`（type）— 中（内部使用×2（仅去 export））
- `features/chat/model/protocol.ts:62` `UnsubscribeMessage`（type）— 中（内部使用×2（仅去 export））
- `features/chat/model/protocol.ts:66` `CancelTurnMessage`（type）— 中（内部使用×2（仅去 export））
- `features/chat/model/protocol.ts:70` `RegenerateMessage`（type）— 中（内部使用×2（仅去 export））
- `features/chat/model/protocol.ts:74` `SubmitUserReplyMessage`（type）— 中（内部使用×2（仅去 export））
- `features/chat/trace/memory.ts:7` `MAX_PREVIEW_EVENTS`（const）— 中（内部使用×2（仅去 export））
- `features/chat/trace/memory.ts:8` `MAX_PREVIEW_BYTES`（const）— 中（内部使用×2（仅去 export））
- `features/chat/trace/memory.ts:9` `MAX_LEGACY_PAYLOAD_CHARS`（const）— 中（仅test引用）
- `features/chat/trace/memory.ts:236` `TraceSettleAction`（type）— 中（内部使用×2（仅去 export））
- `features/chat/trace/memory.ts:257` `TraceSnapshot`（interface）— 中（内部使用×8（仅去 export））
- `features/chat/trace/selectors.ts:137` `groupHasTraceSubstance`（function）— 中（内部使用×2（仅去 export））
- `features/chat/transport/TurnRuntimeClient.ts:31` `RuntimeScheduler`（interface）— 中（仅test引用）
- `features/chat/transport/TurnRuntimeClient.ts:36` `TurnRuntimeClientOptions`（interface）— 中（内部使用×4（仅去 export））
- `features/chat/transport/socket.ts:1` `SocketMessageEvent`（interface）— 中（内部使用×2（仅去 export））
- `features/co-writer/components/CoWriterWorkspace.tsx:176` `CoWriterWorkspaceProps`（interface）— 中（内部使用×2（仅去 export））
- `features/co-writer/hooks/useSynchronizedScroll.ts:10` `ScrollSyncSource`（type）— 中（内部使用×2（仅去 export））
- `features/co-writer/model/editor-state.ts:1` `EditorHistoryState`（interface）— 中（内部使用×10（仅去 export））
- `features/co-writer/model/editor-state.ts:8` `SelectedTextRange`（interface）— 中（内部使用×2（仅去 export））
- `features/co-writer/model/editor-state.ts:15` `ScrollMarker`（interface）— 中（内部使用×2（仅去 export））
- `features/co-writer/model/editor-state.ts:22` `createEditorHistory`（function）— 中（仅test引用）
- `features/co-writer/model/editor-state.ts:26` `applyEditorEdit`（function）— 中（仅test引用）
- `features/co-writer/model/editor-state.ts:41` `closeEditorEditGroup`（function）— 中（内部使用×3（仅去 export））
- `features/co-writer/model/editor-state.ts:47` `undoEditorEdit`（function）— 中（仅test引用）
- `features/co-writer/model/editor-state.ts:58` `redoEditorEdit`（function）— 中（仅test引用）
- `features/co-writer/storage/drafts.ts:3` `DRAFT_STORAGE_VERSION`（const）— 中（内部使用×4（仅去 export））
- `features/co-writer/storage/drafts.ts:4` `DRAFT_STORAGE_PREFIX`（const）— 中（仅test引用）
- `features/co-writer/storage/drafts.ts:5` `LEGACY_DRAFT_STORAGE_PREFIX`（const）— 中（仅test引用）
- `features/co-writer/storage/drafts.ts:6` `SPLIT_RATIO_KEY`（const）— 中（内部使用×3（仅去 export））
- `features/co-writer/storage/drafts.ts:7` `SYNC_SCROLL_KEY`（const）— 中（内部使用×3（仅去 export））
- `features/co-writer/storage/drafts.ts:9` `StoredDraft`（interface）— 中（内部使用×7（仅去 export））
- `features/co-writer/storage/drafts.ts:17` `KeyValueStorage`（interface）— 中（仅test引用）
- `features/knowledge/components/engines/EngineDetail.tsx:75` `EngineDetailProps`（interface）— 中（内部使用×2（仅去 export））
- `features/knowledge/components/engines/EngineDetail.tsx:1176` `LightRagModelsForm`（function）— 中（仅test引用）
- `features/multi-user/types.ts:33` `ToolOption`（type）— 中（内部使用×2（仅去 export））
- `features/multi-user/types.ts:35` `McpToolOption`（type）— 中（内部使用×2（仅去 export））
- `features/runtime-status/RuntimeHealthCard.tsx:14` `RuntimeHealthCardProps`（interface）— 中（内部使用×2（仅去 export））
- `features/runtime-status/TurnCoordinationSettings.tsx:8` `TurnCoordinationSettingsProps`（interface）— 中（内部使用×2（仅去 export））
- `features/settings/navigation/settings-nav.ts:72` `SettingsCategory`（interface）— 中（内部使用×3（仅去 export））
- `features/settings/navigation/settings-nav.ts:561` `SETTINGS_HUB_HREF`（const）— 中（内部使用×3（仅去 export））
- `features/settings/navigation/settings-nav.ts:564` `SETTINGS_ALIASES`（const）— 中（内部使用×2（仅去 export））
- `features/settings/navigation/settings-nav.ts:637` `storagePathFor`（function）— 中（仅test引用）
- `features/settings/navigation/settings-pages.ts:54` `SETTINGS_PAGE_FAMILIES`（const）— 中（内部使用×2（仅去 export））
- `hooks/use-card-submission.ts:4` `UserReplyPayload`（interface）— 中（内部使用×3（仅去 export））
- `hooks/use-card-submission.ts:10` `SubmitUserReply`（type）— 中（内部使用×2（仅去 export））
- `hooks/useAuthStatus.ts:6` `AuthStatusState`（interface）— 中（内部使用×5（仅去 export））
- `hooks/useContextBudget.ts:27` `readContextBudget`（function）— 中（内部使用×2（仅去 export））
- `hooks/useDevice.ts:19` `DEVICE_BREAKPOINTS`（const）— 中（内部使用×3（仅去 export））
- `hooks/useDevice.ts:26` `DeviceClass`（type）— 中（内部使用×4（仅去 export））
- `hooks/useDevice.ts:28` `DeviceState`（interface）— 中（内部使用×2（仅去 export））
- `hooks/useDragSort.ts:51` `DragSortOptions`（interface）— 中（内部使用×2（仅去 export））
- `hooks/useDragSort.ts:61` `DragItemProps`（interface）— 中（内部使用×3（仅去 export））
- `hooks/useKnowledgeProgress.ts:25` `appendTaskLog`（function）— 中（仅test引用）
- `hooks/useKnowledgeProgress.ts:31` `taskStateAfterProgress`（function）— 中（仅test引用）
- `hooks/useMasteryPathActivity.ts:11` `MasteryConnectionState`（type）— 中（内部使用×3（仅去 export））
- `hooks/useMasteryPathActivity.ts:19` `MasteryPathActivity`（interface）— 中（内部使用×2（仅去 export））
- `hooks/useMasteryPathActivity.ts:31` `ActivityFeed`（interface）— 中（仅test引用）
- `hooks/useMasteryPathActivity.ts:38` `EMPTY_FEED`（const）— 中（仅test引用）
- `hooks/useMasteryPathActivity.ts:58` `mergeEventBatch`（function）— 中（仅test引用）
- `hooks/useMasteryPathActivity.ts:101` `mergeSocketEnvelope`（function）— 中（内部使用×2（仅去 export））
- `hooks/useMasteryPathActivity.ts:123` `latestRevision`（function）— 中（仅test引用）
- `hooks/useSetupSync.ts:93` `AppLanguage`（reexport-local-type）— 中（内部使用×2（仅去 export））
- `hooks/useSmoothStreamText.ts:51` `revealStep`（function）— 中（仅test引用）
- `hooks/useSmoothStreamText.ts:75` `revealGapMs`（function）— 中（仅test引用）
- `hooks/useTopicSourceLibrary.ts:14` `SourceCandidateKind`（type）— 中（内部使用×3（仅去 export））
- `hooks/useTopicSourceLibrary.ts:21` `SourceContainerKind`（type）— 中（内部使用×2（仅去 export））
- `hooks/useTopicSourceLibrary.ts:475` `sourceRequest`（function）— 中（内部使用×5（仅去 export））
- `hooks/useVoiceRecorder.ts:8` `RecorderState`（type）— 中（内部使用×2（仅去 export））
- `lib/admin-api.ts:85` `UserBatchResult`（interface）— 中（内部使用×3（仅去 export））
- `lib/admin-api.ts:100` `UserBatchDeleteResult`（interface）— 中（内部使用×3（仅去 export））
- `lib/admin-api.ts:162` `CreatedUser`（interface）— 中（内部使用×4（仅去 export））
- `lib/app-update.ts:12` `UpdateRelease`（interface）— 中（内部使用×2（仅去 export））
- `lib/app-update.ts:52` `AppUpdateStatusSignal`（interface）— 中（内部使用×3（仅去 export））
- `lib/app-update.ts:122` `setAppUpdateChecks`（function）— 中（仅test引用）
- `lib/attachment-limits.ts:28` `DEFAULT_ATTACHMENT_LIMITS`（const）— 中（内部使用×5（仅去 export））
- `lib/auth.ts:40` `invalidateAuthStatusCache`（function）— 中（仅test引用）
- `lib/avatar.ts:74` `AvatarDescriptor`（type）— 中（内部使用×2（仅去 export））
- `lib/backend-forward.ts:1` `FRONTEND_HOST_HEADER`（const）— 中（内部使用×3（仅去 export））
- `lib/book-activity.ts:40` `Translate`（type）— 中（内部使用×5（仅去 export））
- `lib/book-activity.ts:43` `BookPhase`（type）— 中（内部使用×4（仅去 export））
- `lib/book-activity.ts:51` `BookActivityRow`（interface）— 中（内部使用×6（仅去 export））
- `lib/book-activity.ts:71` `BookActivityBlock`（interface）— 中（内部使用×3（仅去 export））
- `lib/book-activity.ts:77` `BookActivity`（interface）— 中（内部使用×2（仅去 export））
- `lib/book-api.ts:94` `CreateBookPayload`（interface）— 中（内部使用×2（仅去 export））
- `lib/book-progress.ts:26` `StageState`（type）— 中（内部使用×3（仅去 export））
- `lib/book-progress.ts:37` `StageView`（interface）— 中（内部使用×4（仅去 export））
- `lib/book-progress.ts:55` `PageActivity`（interface）— 中（内部使用×7（仅去 export））
- `lib/book-progress.ts:92` `STAGE_ORDER`（const）— 中（内部使用×5（仅去 export））
- `lib/book-types.ts:20` `PageStatus`（type）— 中（内部使用×2（仅去 export））
- `lib/book-types.ts:58` `ConceptNode`（interface）— 中（内部使用×2（仅去 export））
- `lib/book-types.ts:66` `ConceptEdge`（interface）— 中（内部使用×2（仅去 export））
- `lib/book-types.ts:78` `SourceAnchor`（interface）— 中（内部使用×3（仅去 export））
- `lib/book-types.ts:153` `ReadingSummary`（interface）— 中（内部使用×2（仅去 export））
- `lib/book-types.ts:160` `SourceQuality`（interface）— 中（内部使用×2（仅去 export））
- `lib/book-types.ts:170` `GenerationOverview`（interface）— 中（内部使用×3（仅去 export））
- `lib/book-ws-operation.ts:3` `BookSocketLike`（interface）— 中（仅test引用）
- `lib/book-ws-operation.ts:12` `BookSocketOperationOptions`（interface）— 中（内部使用×2（仅去 export））
- `lib/brand-icons.ts:74` `BrandIcon`（reexport-local-type）— 中（内部使用×3（仅去 export））
- `lib/brand-slugs.ts:28` `MCP_BRAND_SLUGS`（const）— 中（仅test引用）
- `lib/brand-slugs.ts:52` `CLI_BRAND_SLUGS`（const）— 中（仅test引用）
- `lib/brand-slugs.ts:118` `referencedSlugs`（function）— 中（仅test引用）
- `lib/capability-routes.ts:19` `ROUTE_CAPABILITIES`（const）— 中（内部使用×2（仅去 export））
- `lib/chat-export.ts:6` `ExportableAttachment`（interface）— 中（内部使用×3（仅去 export））
- `lib/chat-export.ts:45` `BuildChatMarkdownOptions`（interface）— 中（内部使用×3（仅去 export））
- `lib/chat-export.ts:50` `buildChatMarkdown`（function）— 中（仅test引用）
- `lib/chat-idle-recovery.ts:13` `IdleTurnRecoveryDecision`（type）— 中（内部使用×2（仅去 export））
- `lib/chat-import/attribution.ts:13` `SessionImportMeta`（interface）— 中（内部使用×4（仅去 export））
- `lib/chat-import/attribution.ts:47` `scopeContainsSession`（function）— 中（内部使用×2（仅去 export））
- `lib/chat-launch-intent.ts:12` `ChatLaunchIntent`（interface）— 中（内部使用×3（仅去 export））
- `lib/chat-markdown-note.ts:3` `ChatMarkdownNoteInput`（interface）— 中（内部使用×6（仅去 export））
- `lib/chat-markdown-note.ts:8` `SavedChatMarkdownNote`（interface）— 中（仅test引用）
- `lib/chat-markdown-note.ts:14` `ChatMarkdownNoteDraft`（interface）— 中（内部使用×6（仅去 export））
- `lib/chat-markdown-note.ts:115` `ChatMarkdownNoteStore`（interface）— 中（仅test引用）
- `lib/cli-apps-api.ts:4` `CLI_APPS_BASE_PATH`（const）— 中（内部使用×6（仅去 export））
- `lib/cli-apps-api.ts:7` `CliAppTrust`（type）— 中（内部使用×5（仅去 export））
- `lib/cli-apps-api.ts:9` `CliAppRuntime`（type）— 中（内部使用×5（仅去 export））
- `lib/cli-apps-api.ts:35` `CliAppAccess`（interface）— 中（内部使用×2（仅去 export））
- `lib/cli-apps-api.ts:75` `CliCatalogPage`（interface）— 中（内部使用×2（仅去 export））
- `lib/code-languages.ts:21` `CODE_EXT_TO_LANG`（const）— 中（内部使用×3（仅去 export））
- `lib/code-languages.ts:157` `CODE_EXTS`（const）— 中（同名token×1）
- `lib/codex-oauth.ts:51` `CodexRemoteGuidance`（type）— 中（内部使用×2（仅去 export））
- `lib/codex-oauth.ts:130` `requestCodex`（function）— 中（仅test引用）
- `lib/codex-oauth.ts:204` `setCodexReasoningEffort`（function）— 中（仅test引用）
- `lib/composer-keyboard.ts:1` `KeyboardSubmitEventLike`（interface）— 中（仅test引用）
- `lib/composer-keyboard.ts:16` `isImeComposing`（function）— 中（仅test引用）
- `lib/conversation-notebook-save.ts:5` `ConversationNotebookSaveOptions`（interface）— 中（内部使用×2（仅去 export））
- `lib/course-handoff.ts:33` `COURSE_HANDOFF_TARGETS`（const）— 中（内部使用×4（仅去 export））
- `lib/course-handoff.ts:118` `courseHandoffFrom`（function）— 中（仅test引用）
- `lib/courses-api.ts:12` `COURSE_RESOURCE_KINDS`（const）— 中（内部使用×2（仅去 export））
- `lib/courses-api.ts:24` `CourseResource`（interface）— 中（内部使用×5（仅去 export））
- `lib/courses-api.ts:50` `CourseStatus`（type）— 中（内部使用×2（仅去 export））
- `lib/datetime.ts:26` `formatTime`（function）— 中（同名token×2）
- `lib/deep-research-report.ts:3` `DeepResearchFollowupStatus`（type）— 中（内部使用×2（仅去 export））
- `lib/deep-research-report.ts:51` `normalizeDeepResearchReportFormatting`（function）— 中（仅test引用）
- `lib/doc-attachments.ts:27` `OFFICE_EXTS`（const）— 中（内部使用×2（仅去 export））
- `lib/doc-attachments.ts:35` `TEXT_LIKE_EXTS`（const）— 中（内部使用×2（仅去 export））
- `lib/doc-attachments.ts:158` `SUPPORTED_DOC_EXTS`（const）— 中（内部使用×3（仅去 export））
- `lib/doc-attachments.ts:160` `SUPPORTED_DOC_MIMES`（const）— 中（内部使用×3（仅去 export））
- `lib/doc-attachments.ts:218` `FileKind`（type）— 中（内部使用×2（仅去 export））
- `lib/doc-attachments.ts:261` `DocIconSpec`（interface）— 中（内部使用×2（仅去 export））
- `lib/epub-page-turn.ts:3` `EPUB_PAGE_TURN_MIN_DRAG_PX`（const）— 中（内部使用×2（仅去 export））
- `lib/epub-page-turn.ts:4` `EPUB_PAGE_TURN_HORIZONTAL_RATIO`（const）— 中（内部使用×2（仅去 export））
- `lib/epub-page-turn.ts:48` `hrefKey`（function）— 中（仅test引用）
- `lib/failed-submissions.ts:7` `FailedSubmissionSnapshot`（type）— 中（内部使用×3（仅去 export））
- `lib/failed-submissions.ts:326` `readFailedSubmission`（function）— 中（仅test引用）
- `lib/graphrag-model-compatibility.ts:3` `GraphRagCandidateGate`（interface）— 中（内部使用×2（仅去 export））
- `lib/iframe-html.ts:32` `injectKaTeX`（function）— 中（内部使用×2（仅去 export））
- `lib/iframe-html.ts:76` `sanitizeIframeHtml`（function）— 中（内部使用×2（仅去 export））
- `lib/ima-connection.ts:4` `ImaLookupStatus`（type）— 中（内部使用×2（仅去 export））
- `lib/ima-connection.ts:18` `ImaManualVerification`（interface）— 中（内部使用×3（仅去 export））
- `lib/imports-api.ts:7` `ImportSessionOutcome`（interface）— 中（内部使用×2（仅去 export））
- `lib/imports-api.ts:14` `ImportResult`（interface）— 中（内部使用×5（仅去 export））
- `lib/kb-name.ts:12` `KB_NAME_FORBIDDEN_CHARS`（const）— 中（内部使用×2（仅去 export））
- `lib/kb-name.ts:14` `KB_NAME_MAX_LENGTH`（const）— 中（内部使用×2（仅去 export））
- `lib/knowledge-engine-group.ts:1` `KnowledgeEngineGroup`（type）— 中（内部使用×2（仅去 export））
- `lib/knowledge-helpers.ts:3` `KnowledgeUploadPolicy`（interface）— 中（内部使用×5（仅去 export））
- `lib/knowledge-helpers.ts:85` `KnowledgeIndexFailure`（interface）— 中（内部使用×2（仅去 export））
- `lib/knowledge-helpers.ts:131` `LightRagVersionDisplayState`（type）— 中（内部使用×2（仅去 export））
- `lib/knowledge-helpers.ts:240` `ValidatedSelectionFile`（interface）— 中（内部使用×3（仅去 export））
- `lib/knowledge-helpers.ts:264` `getFileExtension`（const）— 中（仅test引用）
- `lib/knowledge-helpers.ts:307` `MARGINNOTE4_KB_TYPE`（const）— 中（内部使用×3（仅去 export））
- `lib/knowledge-helpers.ts:331` `KB_DETAIL_SECTIONS`（const）— 中（内部使用×3（仅去 export））
- `lib/knowledge-helpers.ts:454` `kbIsUploadable`（const）— 中（仅test引用）
- `lib/latex-commands.ts:135` `KATEX_COMMANDS`（const）— 中（内部使用×3（仅去 export））
- `lib/latex.ts:49` `convertLatexDelimiters`（function）— 中（仅test引用）
- `lib/learning-api.ts:22` `LearningKnowledgePoint`（interface）— 中（内部使用×2（仅去 export））
- `lib/learning-api.ts:28` `LearningModule`（interface）— 中（内部使用×2（仅去 export））
- `lib/learning-api.ts:36` `ProgressDetail`（interface）— 中（内部使用×3（仅去 export））
- `lib/learning-api.ts:82` `MapModule`（interface）— 中（内部使用×2（仅去 export））
- `lib/learning-api.ts:97` `MasteryMap`（interface）— 中（内部使用×4（仅去 export））
- `lib/learning-api.ts:106` `NextStep`（interface）— 中（内部使用×3（仅去 export））
- `lib/learning-api.ts:123` `MasteryMapResult`（interface）— 中（内部使用×3（仅去 export））
- `lib/learning-api.ts:133` `BoardCard`（interface）— 中（内部使用×3（仅去 export））
- `lib/learning-api.ts:235` `ObjectiveAttempt`（interface）— 中（内部使用×2（仅去 export））
- `lib/learning-api.ts:244` `ObjectiveReview`（interface）— 中（内部使用×2（仅去 export））
- `lib/learning-api.ts:258` `LearningEvidence`（interface）— 中（内部使用×2（仅去 export））
- `lib/learning-api.ts:273` `ObjectiveErrorRecord`（interface）— 中（内部使用×2（仅去 export））
- `lib/learning-api.ts:322` `ProgressSummary`（interface）— 中（内部使用×2（仅去 export））
- `lib/learning-api.ts:332` `ProgressListResult`（interface）— 中（内部使用×2（仅去 export））
- `lib/learning-api.ts:425` `TopicSource`（interface）— 中（内部使用×2（仅去 export））
- `lib/learning-api.ts:448` `TopicMetadata`（interface）— 中（内部使用×2（仅去 export））
- `lib/learning-api.ts:478` `MasteryReviewSettings`（interface）— 中（内部使用×2（仅去 export））
- `lib/learning-api.ts:500` `TopicCoverageGap`（interface）— 中（内部使用×2（仅去 export））
- `lib/learning-api.ts:530` `GenerateTopicInput`（interface）— 中（内部使用×3（仅去 export））
- `lib/learning-api.ts:594` `fetchMasteryTopics`（function）— 中（同名token×1）
- `lib/learning-dashboard.ts:10` `Located`（type）— 中（内部使用×4（仅去 export））
- `lib/learning-dashboard.ts:17` `LearningActivity`（interface）— 中（内部使用×5（仅去 export））
- `lib/learning-dashboard.ts:26` `isWatchingSession`（function）— 中（仅test引用）
- `lib/learning-dashboard.ts:80` `learningSurfaceStats`（function）— 中（仅test引用）
- `lib/learning-records-api.ts:3` `ReadingProgressRecord`（interface）— 中（内部使用×2（仅去 export））
- `lib/learning-records-api.ts:12` `ReadingActivityRecord`（interface）— 中（内部使用×2（仅去 export））
- `lib/llm-options-state.ts:4` `LLMOptionsStatus`（type）— 中（内部使用×2（仅去 export））
- `lib/llm-options-state.ts:6` `LLMOptionsState`（interface）— 中（仅test引用）
- `lib/llm-options-state.ts:12` `LLMOptionsAction`（type）— 中（内部使用×2（仅去 export））
- `lib/markdown-display.ts:494` `citationHrefForId`（function）— 中（内部使用×3（仅去 export））
- `lib/mastery-handoff.ts:26` `MasteryHandoffKind`（type）— 中（内部使用×3（仅去 export））
- `lib/mastery-handoff.ts:73` `masteryHandoffFrom`（function）— 中（仅test引用）
- `lib/mastery-mode.ts:22` `DEFAULT_MASTERY_MODE`（const）— 中（仅test引用）
- `lib/mastery-question.ts:25` `MASTERY_QUESTION_KEY`（const）— 中（内部使用×3（仅去 export））
- `lib/mastery-question.ts:33` `MasteryQuestionOption`（interface）— 中（内部使用×2（仅去 export））
- `lib/mastery-question.ts:139` `collectMasteryQuestions`（function）— 中（内部使用×2（仅去 export））
- `lib/mastery-ws.ts:8` `MASTERY_WS_PATH`（const）— 中（内部使用×2（仅去 export））
- `lib/mastery-ws.ts:10` `MasterySubscribedMessage`（interface）— 中（内部使用×4（仅去 export））
- `lib/mastery-ws.ts:17` `MasteryTopicEventMessage`（interface）— 中（内部使用×4（仅去 export））
- `lib/mastery-ws.ts:26` `MasterySocketErrorMessage`（interface）— 中（内部使用×2（仅去 export））
- `lib/mastery-ws.ts:31` `MasterySocketMessage`（type）— 中（内部使用×2（仅去 export））
- `lib/mastery-ws.ts:40` `masterySubscribePayload`（function）— 中（仅test引用）
- `lib/mastery-ws.ts:51` `parseMasterySocketMessage`（function）— 中（仅test引用）
- `lib/mastery-ws.ts:87` `MasteryTopicSocketHandlers`（interface）— 中（内部使用×2（仅去 export））
- `lib/math-animator-types.ts:1` `MathAnimatorOutputMode`（type）— 中（内部使用×2（仅去 export））
- `lib/math-animator-types.ts:3` `MathAnimatorArtifact`（interface）— 中（内部使用×3（仅去 export））
- `lib/mcp-api.ts:60` `McpSettings`（interface）— 中（内部使用×3（仅去 export））
- `lib/mcp-api.ts:72` `McpRejectedServer`（interface）— 中（内部使用×2（仅去 export））
- `lib/mcp-api.ts:131` `MCP_SERVER_NAME_RE`（const）— 中（内部使用×2（仅去 export））
- `lib/mcp-api.ts:157` `linesToArray`（function）— 中（仅test引用）
- `lib/mcp-api.ts:176` `pairsToDict`（function）— 中（仅test引用）
- `lib/mcp-api.ts:228` `McpServerFormDraft`（interface）— 中（仅test引用）
- `lib/mcp-api.ts:350` `normalizeServerConfig`（function）— 中（仅test引用）
- `lib/mcp-api.ts:653` `McpCatalogQuery`（interface）— 中（内部使用×2（仅去 export））
- `lib/mcp-store.ts:25` `MCP_CATALOG_CATEGORIES`（const）— 中（内部使用×3（仅去 export））
- `lib/mcp-store.ts:41` `McpCategoryChip`（interface）— 中（内部使用×2（仅去 export））
- `lib/mcp-store.ts:78` `mcpRefusalKey`（function）— 中（仅test引用）
- `lib/mcp-store.ts:216` `catalogInitials`（function）— 中（仅test引用）
- `lib/mcp-tool-groups.ts:22` `ProviderToolGroup`（interface）— 中（内部使用×4（仅去 export））
- `lib/mcp-tool-groups.ts:29` `GroupSelection`（type）— 中（内部使用×3（仅去 export））
- `lib/mcp-tool-groups.ts:34` `providerGroupId`（function）— 中（仅test引用）
- `lib/mcp-tool-groups.ts:72` `groupSelection`（function）— 中（仅test引用）
- `lib/memory-graph.ts:7` `Surface`（type）— 中（内部使用×13（仅去 export））
- `lib/memory-graph.ts:16` `SURFACES`（const）— 中（内部使用×14（仅去 export））
- `lib/memory-graph.ts:26` `L3Slot`（type）— 中（内部使用×8（仅去 export））
- `lib/memory-graph.ts:27` `L3_SLOTS`（const）— 中（内部使用×8（仅去 export））
- `lib/memory-graph.ts:31` `L1Entity`（interface）— 中（内部使用×7（仅去 export））
- `lib/memory-graph.ts:38` `ParsedEntry`（interface）— 中（内部使用×7（仅去 export））
- `lib/memory-graph.ts:47` `ParsedDoc`（interface）— 中（内部使用×8（仅去 export））
- `lib/memory-graph.ts:126` `parseDoc`（function）— 中（内部使用×3（仅去 export））
- `lib/memory-graph.ts:219` `splitRef`（function）— 中（内部使用×3（仅去 export））
- `lib/memory-graph.ts:235` `RawMemorySnapshot`（interface）— 中（内部使用×3（仅去 export））
- `lib/memory-graph.ts:288` `LayoutOptions`（interface）— 中（内部使用×3（仅去 export））
- `lib/message-branches.ts:86` `VisiblePathResult`（interface）— 中（内部使用×2（仅去 export））
- `lib/message-content.ts:10` `RawMessageContent`（type）— 中（内部使用×2（仅去 export））
- `lib/model-catalog-types.ts:220` `VoiceChoice`（type）— 中（内部使用×3（仅去 export））
- `lib/model-settings.ts:10` `MODEL_SERVICES`（const）— 中（内部使用×2（仅去 export））
- `lib/model-settings.ts:30` `ProviderGroup`（type）— 中（内部使用×3（仅去 export））
- `lib/model-settings.ts:40` `providerGroups`（function）— 中（仅test引用）
- `lib/notebook-api.ts:13` `NotebookRecordType`（type）— 中（内部使用×2（仅去 export））
- `lib/notebook-api.ts:48` `NotebookDetail`（interface）— 中（内部使用×3（仅去 export））
- `lib/notebook-api.ts:193` `NotebookAnswerImage`（interface）— 中（内部使用×2（仅去 export））
- `lib/notebook-api.ts:265` `QuestionOriginType`（type）— 中（内部使用×4（仅去 export））
- `lib/notebook-api.ts:270` `AssessmentType`（type）— 中（内部使用×4（仅去 export））
- `lib/notebook-api.ts:272` `AssessmentResult`（type）— 中（内部使用×4（仅去 export））
- `lib/notebook-api.ts:288` `NotebookEntryListResponse`（interface）— 中（内部使用×3（仅去 export））
- `lib/notebook-api.ts:311` `NotebookEntryFilter`（interface）— 中（内部使用×2（仅去 export））
- `lib/notebook-api.ts:452` `NotebookAnswerImageUpload`（interface）— 中（内部使用×2（仅去 export））
- `lib/notebook-api.ts:539` `BulkCategoryResult`（interface）— 中（内部使用×3（仅去 export））
- `lib/notifications.ts:16` `NotificationTone`（type）— 中（内部使用×3（仅去 export））
- `lib/partner-chat-draft.ts:3` `PartnerDraftSnapshot`（interface）— 中（内部使用×3（仅去 export））
- `lib/partner-groups-api.ts:81` `CreatePartnerGroupPayload`（interface）— 中（内部使用×3（仅去 export））
- `lib/partner-session.ts:18` `readPartnerSessionKey`（function）— 中（内部使用×2（仅去 export））
- `lib/partner-session.ts:29` `readLegacyPartnerSessionKey`（function）— 中（内部使用×2（仅去 export））
- `lib/partner-session.ts:66` `loadPartnerSessionKey`（function）— 中（仅test引用）
- `lib/partners-api.ts:52` `ProvisioningReport`（interface）— 中（内部使用×3（仅去 export））
- `lib/partners-api.ts:57` `SoulTemplate`（interface）— 中（内部使用×3（仅去 export））
- `lib/partners-api.ts:68` `ToolOption`（interface）— 中（内部使用×4（仅去 export））
- `lib/partners-api.ts:73` `McpToolOption`（interface）— 中（内部使用×2（仅去 export））
- `lib/partners-api.ts:108` `PartnerWebContinuity`（interface）— 中（内部使用×4（仅去 export））
- `lib/partners-api.ts:125` `PartnerHistoryPage`（interface）— 中（内部使用×2（仅去 export））
- `lib/partners-api.ts:145` `CreatePartnerPayload`（interface）— 中（内部使用×3（仅去 export））
- `lib/partners-api.ts:169` `ConfirmPartnerDraftPayload`（interface）— 中（内部使用×2（仅去 export））
- `lib/partners-api.ts:378` `ChannelSchemaEntry`（interface）— 中（内部使用×2（仅去 export））
- `lib/partners-api.ts:394` `PartnerChannelRuntimeSetup`（interface）— 中（内部使用×2（仅去 export））
- `lib/partners-api.ts:407` `PartnerChannelRuntimeResponse`（interface）— 中（内部使用×2（仅去 export））
- `lib/partners-api.ts:426` `PartnerChannelOnboardingStatus`（type）— 中（内部使用×2（仅去 export））
- `lib/partners-api.ts:525` `getPartnerHistory`（function）— 中（同名token×1）
- `lib/pdfjs-loader.ts:28` `Pdfjs`（type）— 中（内部使用×4（仅去 export））
- `lib/personas-api.ts:7` `PersonaSource`（type）— 中（内部使用×3（仅去 export））
- `lib/personas-api.ts:16` `PersonaDetail`（interface）— 中（内部使用×2（仅去 export））
- `lib/personas-api.ts:20` `CreatePersonaPayload`（interface）— 中（内部使用×2（仅去 export））
- `lib/personas-api.ts:26` `UpdatePersonaPayload`（interface）— 中（内部使用×2（仅去 export））
- `lib/personas-api.ts:126` `invalidatePersonasCache`（function）— 中（内部使用×4（仅去 export））
- `lib/provider-registry.ts:100` `modelProviderRef`（function）— 中（内部使用×3（仅去 export））
- `lib/provider-registry.ts:122` `RegistryModelRow`（type）— 中（内部使用×3（仅去 export））
- `lib/proxy-policy.ts:10` `HANDOFF_PATH`（const）— 中（仅test引用）
- `lib/proxy-policy.ts:12` `CODEX_CALLBACK_PATH`（const）— 中（仅test引用）
- `lib/proxy-policy.ts:64` `TokenState`（type）— 中（内部使用×2（仅去 export））
- `lib/question-bank-answers.ts:2` `foldedAnswer`（function）— 中（内部使用×4（仅去 export））
- `lib/quiz-judge.ts:3` `QuizJudgeImage`（interface）— 中（内部使用×2（仅去 export））
- `lib/quiz-judge.ts:12` `QuizJudgeRequest`（interface）— 中（内部使用×2（仅去 export））
- `lib/quiz-judge.ts:29` `QuizJudgeHandlers`（interface）— 中（内部使用×2（仅去 export））
- `lib/quiz-types.ts:57` `QuizFollowupContext`（interface）— 中（内部使用×2（仅去 export））
- `lib/quiz-types.ts:210` `QuizFollowupExtras`（interface）— 中（内部使用×2（仅去 export））
- `lib/reading-age-presentation.ts:34` `PRIMARY_READING_ACTIONS`（const）— 中（内部使用×2（仅去 export））
- `lib/reading-api.ts:12` `AnnotationKind`（type）— 中（内部使用×3（仅去 export））
- `lib/reading-api.ts:13` `ExportFormat`（type）— 中（内部使用×2（仅去 export））
- `lib/reading-api.ts:14` `RenderMode`（type）— 中（内部使用×2（仅去 export））
- `lib/reading-api.ts:15` `ContentFormat`（type）— 中（内部使用×2（仅去 export））
- `lib/reading-api.ts:142` `ReadingPosition`（interface）— 中（内部使用×7（仅去 export））
- `lib/reading-api.ts:149` `parseReadingPosition`（function）— 中（仅test引用）
- `lib/reading-api.ts:182` `SupportedFormats`（interface）— 中（内部使用×2（仅去 export））
- `lib/reading-api.ts:188` `ReadingExtensionAction`（interface）— 中（内部使用×2（仅去 export））
- `lib/reading-api.ts:321` `ReadingTranscript`（interface）— 中（内部使用×2（仅去 export））
- `lib/reading-api.ts:423` `ReadingQuizAnswer`（interface）— 中（内部使用×2（仅去 export））
- `lib/reading-api.ts:428` `ReadingQuizAnswerVerdict`（interface）— 中（内部使用×3（仅去 export））
- `lib/reading-api.ts:639` `filenameFromDisposition`（function）— 中（内部使用×2（仅去 export））
- `lib/reading-citations.ts:26` `LocatorCitation`（interface）— 中（内部使用×4（仅去 export））
- `lib/reading-citations.ts:37` `LOCATOR_HREF_PREFIX`（const）— 中（仅test引用）
- `lib/reading-citations.ts:45` `ReadingCitationTarget`（interface）— 中（内部使用×2（仅去 export））
- `lib/reading-citations.ts:191` `findLocatorCitations`（function）— 中（仅test引用）
- `lib/reading-citations.ts:291` `locatorFromHref`（function）— 中（仅test引用）
- `lib/reading-citations.ts:383` `locatorLabel`（function）— 中（仅test引用）
- `lib/reading-display-preferences.ts:19` `MAX_LINE_WIDTH`（const）— 中（仅test引用）
- `lib/reading-display-preferences.ts:20` `READER_PREFS_KEY`（const）— 中（内部使用×3（仅去 export））
- `lib/reading-display-preferences.ts:40` `normaliseReaderDisplayPreferences`（function）— 中（仅test引用）
- `lib/reading-display-preferences.ts:91` `ReaderDisplayShortcut`（type）— 中（内部使用×2（仅去 export））
- `lib/reading-inline-markdown.tsx:63` `InlineMarkdown`（function）— 中（仅test引用）
- `lib/reading-location-history.ts:4` `READING_HISTORY_LIMIT`（const）— 中（仅test引用）
- `lib/reading-location-history.ts:7` `ReadingLocationSource`（interface）— 中（内部使用×2（仅去 export））
- `lib/reading-location-history.ts:138` `parseReadingHistory`（function）— 中（仅test引用）
- `lib/reading-location-history.ts:177` `readingHistoryStorageKey`（function）— 中（仅test引用）
- `lib/reading-media-citations.ts:3` `MEDIA_TIME_HREF_PREFIX`（const）— 中（仅test引用）
- `lib/reading-media-controller.ts:21` `YouTubePlayerLike`（reexport-local-type）— 中（内部使用×3（仅去 export））
- `lib/reading-outline.ts:18` `ReaderDisplayLine`（interface）— 中（内部使用×2（仅去 export））
- `lib/reading-outline.ts:26` `headingAnchor`（function）— 中（内部使用×3（仅去 export））
- `lib/reading-outline.ts:32` `readerHeadingLine`（function）— 中（内部使用×3（仅去 export））
- `lib/reading-outline.ts:40` `EpubHeadingElement`（interface）— 中（内部使用×2（仅去 export））
- `lib/reading-passage-prompts.ts:18` `PassagePromptKey`（type）— 中（内部使用×2（仅去 export））
- `lib/reading-passage-prompts.ts:20` `PassagePrompt`（interface）— 中（内部使用×2（仅去 export））
- `lib/reading-passage-prompts.ts:65` `translationTarget`（function）— 中（仅test引用）
- `lib/reading-quote-locator.ts:20` `QuotePosition`（interface）— 中（内部使用×5（仅去 export））
- `lib/reading-quote-locator.ts:27` `QuoteRange`（interface）— 中（内部使用×5（仅去 export））
- `lib/reading-quote-locator.ts:150` `findQuoteRange`（function）— 中（仅test引用）
- `lib/reading-quote-locator.ts:289` `collectTextNodes`（function）— 中（内部使用×2（仅去 export））
- `lib/reading-reader-action.ts:58` `readerActionFrom`（function）— 中（仅test引用）
- `lib/reading-reader-action.ts:116` `resetReaderActionTracking`（function）— 中（仅test引用）
- `lib/reading-selection.ts:20` `Box`（interface）— 中（内部使用×6（仅去 export））
- `lib/reading-selection.ts:27` `NormalisedRect`（type）— 中（内部使用×5（仅去 export））
- `lib/reading-selection.ts:45` `mergeRectsByLine`（function）— 中（仅test引用）
- `lib/reading-selection.ts:104` `unionRect`（function）— 中（仅test引用）
- `lib/reading-turn-state.ts:22` `ReadingTurnState`（interface）— 中（内部使用×3（仅去 export））
- `lib/reading-turn-state.ts:111` `getReadingTurnState`（function）— 中（仅test引用）
- `lib/reading-turn-state.ts:20` `READING_WORKSPACE_MODE`（reexport-local）— 中（仅test引用）
- `lib/reading-video-sources.ts:116` `parseMediaTimestamp`（function）— 中（仅test引用）
- `lib/reading-w3c-annotations.ts:3` `W3CTextAnnotation`（interface）— 中（内部使用×2（仅去 export））
- `lib/reading-w3c-annotations.ts:18` `RecogitoTextAnnotation`（interface）— 中（内部使用×2（仅去 export））
- `lib/reading-w3c-annotations.ts:37` `resolveTextSelectors`（function）— 中（仅test引用）
- `lib/reading-w3c-annotations.ts:92` `toW3CTextAnnotation`（function）— 中（仅test引用）
- `lib/reading-workspace-api.ts:14` `ReadingIngestionStatus`（type）— 中（内部使用×2（仅去 export））
- `lib/reading-workspace-api.ts:48` `ReadingMaterialCollection`（interface）— 中（内部使用×5（仅去 export））
- `lib/reading-workspace-api.ts:201` `listReadingWorkspaces`（function）— 中（同名token×1）
- `lib/reasoning-effort.ts:1` `ReasoningEffortOption`（type）— 中（内部使用×5（仅去 export））
- `lib/reconnecting-websocket.ts:8` `reconnectDelayMs`（function）— 中（仅test引用）
- `lib/reconnecting-websocket.ts:16` `RetryScheduler`（interface）— 中（内部使用×4（仅去 export））
- `lib/reconnecting-websocket.ts:21` `ReconnectingWebSocketHandlers`（interface）— 中（内部使用×2（仅去 export））
- `lib/research-types.ts:22` `ResearchConfigValidationResult`（interface）— 中（内部使用×2（仅去 export））
- `lib/resource-reuse.ts:1` `RESOURCE_KINDS`（const）— 中（内部使用×2（仅去 export））
- `lib/route-params.ts:1` `firstParam`（function）— 中（仅test引用）
- `lib/selection-tutor.ts:24` `normalizeSourceMessageText`（function）— 中（内部使用×2（仅去 export））
- `lib/selection-tutor.ts:63` `wrapLatexSource`（function）— 中（仅test引用）
- `lib/selection-tutor.ts:70` `extractTexAnnotation`（function）— 中（内部使用×4（仅去 export））
- `lib/selection-tutor.ts:79` `extractTexAnnotationFromHtml`（function）— 中（仅test引用）
- `lib/session-api.ts:52` `MessageTraceMetadata`（interface）— 中（内部使用×2（仅去 export））
- `lib/session-api.ts:77` `SessionPreferences`（interface）— 中（仅test引用）
- `lib/session-api.ts:140` `SessionSearchPage`（interface）— 中（内部使用×3（仅去 export））
- `lib/session-api.ts:147` `ActiveTurnSummary`（interface）— 中（内部使用×2（仅去 export））
- `lib/session-api.ts:176` `QuizResultItem`（interface）— 中（内部使用×2（仅去 export））
- `lib/session-archive.ts:40` `ArchiveInput`（interface）— 中（内部使用×2（仅去 export））
- `lib/session-load.ts:13` `LoadOutcome`（interface）— 中（内部使用×2（仅去 export））
- `lib/settings-extensions.ts:33` `ExtensionKey`（type）— 中（内部使用×2（仅去 export））
- `lib/settings-extensions.ts:35` `isExtensionKey`（function）— 中（内部使用×2（仅去 export））
- `lib/settings-presets.ts:14` `SettingsPresetsPayload`（interface）— 中（内部使用×3（仅去 export））
- `lib/settings-readiness.ts:4` `READINESS_STATES`（const）— 中（仅test引用）
- `lib/settings-readiness.ts:15` `USABLE_READINESS_STATES`（const）— 中（内部使用×2（仅去 export））
- `lib/settings-readiness.ts:27` `READINESS_SEVERITIES`（const）— 中（内部使用×2（仅去 export））
- `lib/settings-readiness.ts:49` `SettingsReadinessNotice`（interface）— 中（内部使用×2（仅去 export））
- `lib/settings-readiness.ts:69` `READINESS_SECTION_ORDER`（const）— 中（仅test引用）
- `lib/settings-readiness.ts:79` `summarizeReadinessRows`（function）— 中（仅test引用）
- `lib/sidebar-entries.ts:29` `SidebarGroupKind`（type）— 中（内部使用×3（仅去 export））
- `lib/sidebar-entries.ts:31` `SidebarSessionEntry`（interface）— 中（内部使用×2（仅去 export））
- `lib/sidebar-entries.ts:51` `SidebarEntry`（type）— 中（内部使用×3（仅去 export））
- `lib/sidebar-entries.ts:53` `SidebarEntriesInput`（interface）— 中（内部使用×2（仅去 export））
- `lib/sidebar-layout.ts:25` `ResolvedNavLayout`（interface）— 中（内部使用×2（仅去 export））
- `lib/sidebar-layout.ts:37` `NAV_LAYOUT_STORAGE_KEY`（const）— 中（内部使用×3（仅去 export））
- `lib/sidebar-layout.ts:38` `SESSION_ORDER_STORAGE_KEY`（const）— 中（内部使用×3（仅去 export））
- `lib/sidebar-layout.ts:39` `COLLAPSED_GROUPS_STORAGE_KEY`（const）— 中（内部使用×3（仅去 export））
- `lib/skill-slug.ts:1` `SKILL_NAME_PATTERN`（const）— 中（仅test引用）
- `lib/skill-slug.ts:2` `SKILL_NAME_RE`（const）— 中（内部使用×2（仅去 export））
- `lib/skills-api.ts:18` `SkillSource`（type）— 中（内部使用×3（仅去 export））
- `lib/skills-api.ts:28` `SkillDetail`（interface）— 中（内部使用×2（仅去 export））
- `lib/skills-api.ts:32` `CreateSkillPayload`（interface）— 中（内部使用×2（仅去 export））
- `lib/skills-api.ts:39` `UpdateSkillPayload`（interface）— 中（内部使用×2（仅去 export））
- `lib/skills-api.ts:114` `InstalledSkill`（interface）— 中（内部使用×2（仅去 export））
- `lib/skills-api.ts:168` `HubCatalog`（interface）— 中（内部使用×2（仅去 export））
- `lib/skills-api.ts:350` `invalidateSkillsCache`（function）— 中（内部使用×8（仅去 export））
- `lib/space-items.ts:13` `SpaceItemKey`（type）— 中（内部使用×2（仅去 export））
- `lib/space-items.ts:23` `SpaceItem`（interface）— 中（内部使用×2（仅去 export））
- `lib/streaming-upload-proxy.ts:29` `UploadProxyDependencies`（interface）— 中（内部使用×2（仅去 export））
- `lib/subagents-api.ts:71` `SubagentModelOption`（interface）— 中（内部使用×2（仅去 export））
- `lib/subagents-api.ts:141` `SubagentSettings`（interface）— 中（内部使用×7（仅去 export））
- `lib/subagents-api.ts:147` `SubagentStreamLine`（interface）— 中（内部使用×5（仅去 export））
- `lib/subagents-api.ts:219` `updateSubagentSettings`（function）— 中（同名token×1）
- `lib/theme.ts:10` `THEME_STORAGE_KEY`（const）— 中（内部使用×3（仅去 export））
- `lib/theme.ts:58` `saveThemeToStorage`（function）— 中（内部使用×3（仅去 export））
- `lib/theme.ts:85` `applyThemeToDocument`（function）— 中（内部使用×4（仅去 export））
- `lib/think-segments.ts:26` `TextSegment`（interface）— 中（内部使用×2（仅去 export））
- `lib/think-segments.ts:31` `ThinkSegment`（interface）— 中（内部使用×2（仅去 export））
- `lib/think-segments.ts:38` `ContentSegment`（type）— 中（内部使用×3（仅去 export））
- `lib/think-segments.ts:130` `hasModelThinking`（function）— 中（仅test引用）
- `lib/tool-availability.ts:3` `ToolAvailabilityLanguage`（type）— 中（内部使用×2（仅去 export））
- `lib/tool-availability.ts:5` `ToolAvailabilityCopy`（type）— 中（内部使用×2（仅去 export））
- `lib/tool-event.ts:13` `MetadataRecord`（type）— 中（内部使用×5（仅去 export））
- `lib/tools-settings.ts:3` `ToolSettingsResponse`（interface）— 中（内部使用×2（仅去 export））
- `lib/trace-tools.ts:25` `mcpToolLabel`（function）— 中（仅test引用）
- `lib/trace-tools.ts:38` `cliArgvLabel`（function）— 中（仅test引用）
- `lib/trace-tools.ts:49` `clipLabel`（function）— 中（仅test引用）
- `lib/trace-tools.ts:63` `ProviderGlyph`（type）— 中（内部使用×2（仅去 export））
- `lib/trace-tools.ts:66` `ProviderRow`（type）— 中（内部使用×2（仅去 export））
- `lib/transcript-search.ts:1` `SearchableTranscriptCue`（type）— 中（内部使用×2（仅去 export））
- `lib/turn-reconcile.ts:17` `ReconcilableMessage`（interface）— 中（仅test引用）
- `lib/turn-reconcile.ts:24` `TurnPersistedIds`（interface）— 中（内部使用×2（仅去 export））
- `lib/turn-reconcile.ts:33` `ReconcileResult`（interface）— 中（内部使用×3（仅去 export））
- `lib/use-auto-sized-textarea.ts:16` `AutoSizedTextareaOptions`（interface）— 中（内部使用×2（仅去 export））
- `lib/video-learning-api.ts:64` `VideoMarkAuthor`（type）— 中（内部使用×3（仅去 export））
- `lib/video-learning-api.ts:65` `VideoMarkSource`（type）— 中（内部使用×2（仅去 export））
- `lib/video-learning-api.ts:419` `InvidiousCatalog`（interface）— 中（内部使用×2（仅去 export））
- `lib/video-learning-marks.ts:16` `uniqueSortedIndexes`（function）— 中（内部使用×3（仅去 export））
- `lib/video-learning-marks.ts:22` `rangeFromCues`（function）— 中（仅test引用）
- `lib/video-learning-marks.ts:40` `locatorsForRange`（function）— 中（仅test引用）
- `lib/video-learning-marks.ts:118` `formatMarkTime`（function）— 中（内部使用×4（仅去 export））
- `lib/visualize-types.ts:5` `VisualizeManimRenderType`（type）— 中（内部使用×3（仅去 export））
- `lib/visualize-types.ts:7` `VisualizeRenderMode`（type）— 中（内部使用×2（仅去 export））
- `lib/visualize-types.ts:42` `isManimRenderType`（function）— 中（内部使用×4（仅去 export））
- `lib/visualize-types.ts:62` `VisualizerRendererRef`（interface）— 中（内部使用×3（仅去 export））
- `lib/visualize-types.ts:70` `VisualizationPayload`（interface）— 中（内部使用×2（仅去 export））
- `lib/visualize-types.ts:75` `VisualizationPresentation`（interface）— 中（内部使用×2（仅去 export））
- `lib/visualize-types.ts:109` `VisualizeManimResult`（interface）— 中（内部使用×3（仅去 export））
- `lib/watching-citations.ts:3` `VIDEO_TIME_HREF_PREFIX`（const）— 中（内部使用×4（仅去 export））
- `lib/watching-turn-state.ts:1` `WATCHING_CAPABILITY`（const）— 中（内部使用×2（仅去 export））
- `lib/workspace-drafts.ts:4` `WorkspaceDraft`（type）— 中（内部使用×3（仅去 export））
- `lib/youtube-iframe-api.ts:3` `YouTubeNamespace`（interface）— 中（内部使用×5（仅去 export））
- `proxy.ts:51` `proxy`（function）— 中（同名token×8）
- `proxy.ts:94` `config`（const）— 中（仅test引用）
- `shared/api/runtime.ts:5` `fetchRuntimeStatus`（function）— 中（同名token×2）
- `shared/auth/return-url.ts:3` `BrowserLocationParts`（interface）— 中（内部使用×2（仅去 export））

### B3. 按文件聚合（未消费导出数 Top 15）

| 文件 | 未消费导出 | 其中高置信 |
|---|---|---|
| `lib/learning-api.ts` | 28 | 8 |
| `lib/reading-api.ts` | 15 | 3 |
| `lib/partners-api.ts` | 13 | 0 |
| `lib/notebook-api.ts` | 12 | 2 |
| `lib/memory-graph.ts` | 11 | 0 |
| `lib/knowledge-helpers.ts` | 10 | 2 |
| `features/chat/model/protocol.ts` | 9 | 0 |
| `contracts/parse/turn-command.ts` | 8 | 5 |
| `features/co-writer/model/editor-state.ts` | 8 | 0 |
| `lib/mastery-ws.ts` | 8 | 0 |
| `lib/mcp-api.ts` | 8 | 0 |
| `lib/visualize-types.ts` | 8 | 1 |
| `features/co-writer/storage/drafts.ts` | 7 | 0 |
| `hooks/useMasteryPathActivity.ts` | 7 | 0 |
| `lib/book-types.ts` | 7 | 0 |

## C. 未挂载组件（38 个符号；完整数据 `data/components.json`）

| 位置 | 组件 | 导入(prod/test) | JSX挂载文件数 | 置信度 |
|---|---|---|---|---|
| `components/access/RequireCapability.tsx:15` | `LockedFeatureNotice` | 0/0 | 0 | 高 |
| `components/agents/agent-icons.tsx:20` | `ClaudeGlyph` | 1/0 | 0 | 低 |
| `components/agents/agent-icons.tsx:38` | `CodexGlyph` | 1/0 | 0 | 低 |
| `components/agents/agent-icons.tsx:77` | `GrokGlyph` | 1/0 | 0 | 低 |
| `components/agents/agent-icons.tsx:98` | `GeminiGlyph` | 1/0 | 0 | 低 |
| `components/agents/agent-icons.tsx:132` | `KimiGlyph` | 1/0 | 0 | 低 |
| `components/agents/agent-icons.tsx:138` | `OpencodeGlyph` | 1/0 | 0 | 低 |
| `components/agents/agent-icons.tsx:148` | `MimoGlyph` | 1/0 | 0 | 低 |
| `components/agents/agent-icons.tsx:182` | `HermesGlyph` | 1/0 | 0 | 低 |
| `components/agents/agent-icons.tsx:188` | `OpenClawGlyph` | 1/0 | 0 | 低 |
| `components/agents/agent-icons.tsx:198` | `DeepSeekGlyph` | 1/0 | 0 | 低 |
| `components/agents/agent-icons.tsx:210` | `PartnerGlyph` | 0/0 | 0 | 高 |
| `components/knowledge/PageIndexSettingsModal.tsx:183` | `PageIndexSettingsModal` | 0/0 | 0 | 高 |
| `components/memory/MemorySection.tsx:264` | `MemorySection` | 0/0 | 0 | 高 |
| `components/reading/workspace/SourceNavigator.tsx:574` | `WorkspaceOutlineBranch` | 0/0 | 0 | 高 |
| `components/reading/workspace/dialogs.tsx:22` | `ModalShell` | 0/0 | 0 | 高 |
| `components/settings/ConnectionsEditor.tsx:82` | `ConnectionsEditor` | 0/0 | 0 | 高 |
| `components/settings/ModelCards.tsx:233` | `UseRow` | 0/0 | 0 | 高 |
| `components/settings/TaskModelsEditor.tsx:10` | `TaskModelsEditor` | 0/0 | 0 | 高 |
| `components/settings/WorkspaceShell.tsx:273` | `WorkspaceFieldGroup` | 0/0 | 0 | 高 |
| `components/space/learning/CoverageNotice.tsx:22` | `CoverageNotice` | 0/0 | 0 | 高 |
| `components/workspaces/WorkspaceSwitcher.tsx:11` | `WorkspaceSwitcher` | 0/0 | 0 | 高 |
| `features/chat/messages/ChatMessageList.tsx:510` | `GeneratedFileCards` | 1/0 | 0 | 低 |
| `features/chat/messages/ChatMessageList.tsx:636` | `AssistantMessage` | 1/0 | 0 | 低 |
| `features/chat/messages/ChatMessageList.tsx:1196` | `RoughActionButton` | 1/0 | 0 | 低 |
| `features/chat/messages/ChatMessageList.tsx:1230` | `CopyActionButton` | 1/0 | 0 | 低 |
| `features/chat/trace/ActivityOrb.tsx:46` | `ChatActivityOrb` | 0/0 | 0 | 高 |
| `features/chat/trace/TracePresentation.tsx:1200` | `CallTracePanel` | 1/0 | 0 | 低 |
| `features/chat/trace/TracePresentation.tsx:1680` | `NestedTraceFlow` | 2/0 | 0 | 低 |
| `features/chat/trace/TracePresentation.tsx:1951` | `ResearchStagePanel` | 1/0 | 0 | 低 |
| `features/chat/trace/memory.ts:276` | `TraceCache` | 1/1 | 0 | 低 |
| `features/chat/transport/TurnRuntimeClient.ts:94` | `TurnRuntimeClient` | 1/1 | 0 | 低 |
| `features/chat/transport/UnifiedTurnClient.ts:93` | `UnifiedTurnClient` | 4/1 | 0 | 低 |
| `features/chat/transport/command-delivery.ts:5` | `CommandDeliveryError` | 1/1 | 0 | 低 |
| `features/knowledge/components/engines/EngineDetail.tsx:399` | `LlamaIndexForm` | 1/0 | 0 | 低 |
| `features/knowledge/components/engines/EngineDetail.tsx:742` | `ImaForm` | 1/0 | 0 | 低 |
| `features/knowledge/components/engines/EngineDetail.tsx:1007` | `GraphRagForm` | 1/0 | 0 | 低 |
| `features/runtime-status/model.ts:35` | `UnsafeRuntimePayloadError` | 1/1 | 0 | 低 |

低置信项说明：有 prod 导入但全仓无直接 JSX 挂载，典型如 `ClaudeGlyph`（组件 map 间接渲染模式），删除前必须人工确认间接引用。

## D. 未引用工具函数（94 个，置信度：高）

- `components/access/RequireCapability.tsx:15` `LockedFeatureNotice` — 高
- `components/agents/agent-icons.tsx:210` `PartnerGlyph` — 高
- `components/chat/home/ComposerInput.tsx:112` `shouldOpenAtPopup` — 高
- `components/chat/home/ComposerInput.tsx:117` `stripTrailingAtMention` — 高
- `components/chat/home/ComposerInput.tsx:122` `atMentionQuery` — 高
- `components/chat/home/ComposerInput.tsx:130` `matchingSlashCommands` — 高
- `components/chat/home/ComposerInput.tsx:141` `shouldOpenSlashPopup` — 高
- `components/partners/schema-form.tsx:26` `resolveSchemaVariant` — 高
- `components/partners/schema-form.tsx:37` `isNullable` — 高
- `components/reading/workspace/SourceNavigator.tsx:574` `WorkspaceOutlineBranch` — 高
- `components/reading/workspace/dialogs.tsx:22` `ModalShell` — 高
- `components/settings/ModelCards.tsx:233` `UseRow` — 高
- `components/settings/WorkspaceShell.tsx:273` `WorkspaceFieldGroup` — 高
- `components/settings/shared.tsx:88` `formatContextWindowUpdatedAt` — 高
- `components/settings/shared.tsx:111` `activeModelDetail` — 高
- `components/space/learning/CoverageNotice.tsx:22` `CoverageNotice` — 高
- `components/workspaces/WorkspaceSwitcher.tsx:11` `WorkspaceSwitcher` — 高
- `context/QuizFollowupContext.tsx:68` `createEmptyThreadState` — 高
- `contracts/parse/turn-command.ts:88` `buildSubscribeSession` — 高
- `contracts/parse/turn-command.ts:129` `buildRegenerate` — 高
- `contracts/parse/turn-command.ts:160` `buildUserInput` — 高
- `contracts/parse/turn-command.ts:174` `buildCheckActiveTurn` — 高
- `contracts/parse/turn-command.ts:184` `buildUnsubscribe` — 高
- `features/chat/ChatStateAdapter.tsx:169` `emptyResourceSelection` — 高
- `features/chat/trace/selectors.ts:137` `groupHasTraceSubstance` — 高
- `features/co-writer/model/editor-state.ts:41` `closeEditorEditGroup` — 高
- `features/settings/navigation/settings-nav.ts:107` `visibleSettingsChildren` — 高
- `features/settings/navigation/settings-scroll.ts:8` `requestSettingsSection` — 高
- `features/settings/navigation/settings-scroll.ts:21` `scrollToSettingsSection` — 高
- `features/settings/store/SettingsStore.tsx:279` `cloneCatalog` — 高
- `features/settings/store/SettingsStore.tsx:284` `voiceService` — 高
- `features/settings/store/SettingsStore.tsx:289` `generationService` — 高
- `features/settings/store/SettingsStore.tsx:360` `serviceConfigured` — 高
- `features/settings/store/SettingsStore.tsx:385` `serviceReadiness` — 高
- `features/settings/store/SettingsStore.tsx:401` `servicePendingApply` — 高
- `hooks/useContextBudget.ts:27` `readContextBudget` — 高
- `hooks/useMasteryPathActivity.ts:101` `mergeSocketEnvelope` — 高
- `hooks/useTopicSourceLibrary.ts:475` `sourceRequest` — 高
- `lib/book-references.ts:36` `countSelectedBookPages` — 高
- `lib/chat-import/agent-store.ts:139` `getAgent` — 高
- `lib/chat-import/attribution.ts:47` `scopeContainsSession` — 高
- `lib/co-writer-events.ts:23` `subscribeCoWriterChanges` — 高
- `lib/guardian-api.ts:147` `saveGuardianMaterials` — 高
- `lib/guardian-api.ts:170` `saveGuardianRestrictions` — 高
- `lib/iframe-html.ts:32` `injectKaTeX` — 高
- `lib/iframe-html.ts:76` `sanitizeIframeHtml` — 高
- `lib/learning-api.ts:45` `fetchProgress` — 高
- `lib/learning-api.ts:51` `initModules` — 高
- `lib/learning-api.ts:162` `fetchMasteryMap` — 高
- `lib/learning-api.ts:337` `fetchAllProgress` — 高
- `lib/learning-api.ts:362` `skipPendingQuestion` — 高
- `lib/learning-api.ts:373` `importFromBook` — 高
- `lib/learning-api.ts:391` `generateModulesFromNotebook` — 高
- `lib/learning-api.ts:694` `generateMasteryTopicDraft` — 高
- `lib/markdown-display.ts:494` `citationHrefForId` — 高
- `lib/mastery-question.ts:139` `collectMasteryQuestions` — 高
- `lib/memory-graph.ts:126` `parseDoc` — 高
- `lib/memory-graph.ts:219` `splitRef` — 高
- `lib/message-branches.ts:246` `latestChildId` — 高
- `lib/notebook-api.ts:379` `getNotebookEntry` — 高
- `lib/notebook-api.ts:412` `lookupNotebookEntryByOrigin` — 高
- `lib/partner-groups-api.ts:183` `getPartnerGroupInvocations` — 高
- `lib/partner-session.ts:18` `readPartnerSessionKey` — 高
- `lib/partner-session.ts:29` `readLegacyPartnerSessionKey` — 高
- `lib/personas-api.ts:126` `invalidatePersonasCache` — 高
- `lib/profile-api.ts:22` `setOwnLearnerProfile` — 高
- `lib/provider-registry.ts:100` `modelProviderRef` — 高
- `lib/question-bank-answers.ts:2` `foldedAnswer` — 高
- `lib/quiz-question-type.ts:67` `isFreeTextQuizQuestion` — 高
- `lib/reading-api.ts:233` `getSupportedFormats` — 高
- `lib/reading-api.ts:269` `deleteMaterial` — 高
- `lib/reading-api.ts:489` `listReadingQuizRewards` — 高
- `lib/reading-api.ts:639` `filenameFromDisposition` — 高
- `lib/reading-outline.ts:26` `headingAnchor` — 高
- `lib/reading-outline.ts:32` `readerHeadingLine` — 高
- `lib/reading-quote-locator.ts:239` `segmentTextByQuotes` — 高
- `lib/reading-quote-locator.ts:289` `collectTextNodes` — 高
- `lib/reading-workspace-api.ts:324` `createReadingConversation` — 高
- `lib/research-types.ts:34` `normalizeResearchConfig` — 高
- `lib/selection-tutor.ts:24` `normalizeSourceMessageText` — 高
- `lib/selection-tutor.ts:70` `extractTexAnnotation` — 高
- `lib/settings-extensions.ts:35` `isExtensionKey` — 高
- `lib/skills-api.ts:350` `invalidateSkillsCache` — 高
- `lib/theme.ts:58` `saveThemeToStorage` — 高
- `lib/theme.ts:85` `applyThemeToDocument` — 高
- `lib/theme.ts:105` `initializeTheme` — 高
- `lib/video-learning-api.ts:378` `saveVideoLearningSettings` — 高
- `lib/video-learning-marks.ts:16` `uniqueSortedIndexes` — 高
- `lib/video-learning-marks.ts:118` `formatMarkTime` — 高
- `lib/video-learning-marks.ts:130` `cuesToSegmentLocators` — 高
- `lib/visualize-types.ts:42` `isManimRenderType` — 高
- `shared/api/errors.ts:43` `isApiError` — 高
- `shared/storage/keys.ts:22` `dynamicStorageKey` — 高
- `shared/storage/store.ts:167` `createBrowserStorageStore` — 高

## E. 孤儿 locale key

i18n 运行时（`web/i18n/init.ts`）只注册 `app` 命名空间：`en/app.json` 静态导入 + zh/fr/de/uk/pl 动态导入。`common.json` 在任何语言下**均未注册**（仅 `tests/workspace-i18n.spec.ts:3` 导入过 zh/common.json）。

| 文件 | key 总数 | 孤儿 key | en 缺失(漂移) | 运行时注册 | 置信度 |
|---|---|---|---|---|---|
| `locales/de/app.json` | 5332 | 754 | 0 | 是 | 中 |
| `locales/de/common.json` | 37 | 5 | 0 | **否** | 高（整文件未注册） |
| `locales/en/app.json` | 5332 | 754 | 0 | 是 | 中 |
| `locales/en/common.json` | 37 | 5 | 0 | **否** | 高（整文件未注册） |
| `locales/fr/app.json` | 5775 | 1465 | 909 | 是 | 中 |
| `locales/fr/common.json` | 37 | 5 | 0 | **否** | 高（整文件未注册） |
| `locales/pl/app.json` | 5348 | 770 | 16 | 是 | 中 |
| `locales/uk/app.json` | 5348 | 770 | 16 | 是 | 中 |
| `locales/zh/app.json` | 5332 | 754 | 0 | 是 | 中 |
| `locales/zh/common.json` | 37 | 5 | 0 | **否** | 高（整文件未注册） |

- 高置信：4 个 `common.json`（共 148 key，含 `common.loading/cancel/close` 等）运行时不可达，整文件可删（测试引用需同步调整）。
- 中置信：各语言 `app.json` 孤儿 key（en/zh/de 754、fr 1465、uk/pl 770）。示例（en）：`Generating`、`Welcome to DeepTutor`、`guidedLearning.*`（约 120 条）、`settingsTour.*`（8 条）、`contextBudget.note.deferredTools_*`。完整 key 清单见 `data/locale_orphans.json`。
- 漂移：`fr/app.json` 比 en 多 909 个 key（en 无此 key，属死翻译）。
- 动态前缀豁免：`contextBudget.segment.`, `mcp.category.`, `mcp.tier.`, `settings.presets.cost.`, `settings.presets.prerequisite.` 等 11 个 `t(\`前缀.…\`)` 模板前缀覆盖到的 key 不判死。

## 复现与哈希自证

```bash
# 基线 f07029cfcf2c8dfccdb671cdfc343db8334f5741
node evidence/scan-web-dead-code-20261006/scan_web_dead_code.mjs --web web --out <输出目录>
node evidence/scan-web-dead-code-20261006/make_report.mjs evidence/scan-web-dead-code-20261006
```

- 同工作区连续两次运行输出 **byte 级一致**（`diff -r` 为空），SHA256 见 `SHA256SUMS`（data/*.json 七个文件哈希与重跑完全相等）。
- TS 编译器路径可用 `--ts` 覆盖（默认主工作区 `web/node_modules/typescript`，只读 require，不写该目录）。

## 风险与误报边界

1. 通配/命名空间导入按「消费全部」豁免——真实死代码可能被掩盖（宁漏勿误）。
2. 字符串精确匹配会把「纯文案与 key 同文」计为已引用；`t()` 拼接 key 只覆盖检测到的模板前缀。
3. 组件 map 间接渲染（`agentGlyph` 模式）使「有导入无 JSX」项只能给低置信。
4. 本卡为只读清点，**不含任何删除动作**；删除建议按置信度拆后续卡，lib/api 客户端删除前对照 AGEN-857 结论。

