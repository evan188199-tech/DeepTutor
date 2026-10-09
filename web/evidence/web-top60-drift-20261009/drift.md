# web Top60 建卡目标文件漂移复核（AGEN-1317）

- 日期：2026-10-09；只读复核，不改任何产品/测试代码；不重复 web-zero 已标 DONE 的 13 项结论，仅做增量漂移核对。
- 输入：`myfork` 分支 `scan/web-zero-triage-20261008` 的 `web/evidence/web-zero-triage-20261008/triage.md`（Top60 + 顺延 ReadingLibrary/KbDocumentList/EduHubImportModal，共 63 path）。

## 一、结论：零漂移

- 最新 `origin/main` HEAD = `6cf793bd8`（release v1.6.14），**与 triage 信号基线 commit 完全相同**；`git ls-remote origin refs/heads/main` 远端复核一致（fetch 后双确认）。
- 63/63 path 全部存在于最新 origin/main；60 项 Top60 的 `wc -l` 与 triage 表逐条一致（60/60 yes）；顺延 3 项 triage 未列 loc，实测 ReadingLibrary.tsx=623、KbDocumentList.tsx=597、EduHubImportModal.tsx=587。
- 删除 0、改名 0、大改 0。**待建卡建议无需更新**：全部建卡目标路径有效，harvest 不会拆到失效路径。

## 二、方法

1. `/Users/Shared/DeepTutor` 内 `git fetch origin main && git fetch myfork`；`git ls-remote origin refs/heads/main` 确认远端 main=6cf793bd8。
2. 新 worktree + 新分支：`git worktree add -b verify/web-top60-drift-20261009 /Users/Shared/dt-agen1317-drift-wt origin/main`；不动 main 工作区。
3. 逐 path：`test -f` 存在性 + `wc -l` 与 triage loc 对账；若缺失则回查 `git log --diff-filter=D` 删除点与 `git ls-tree` 同名候选（本批未触发）。

## 三、逐 path 状态（63 项）

| # | path | triage loc | DONE | 状态 | main loc | loc 一致 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `lib/memory-graph.ts` | 762 | ★ | exists | 762 | yes |
| 2 | `components/partners/group/useGroupSession.ts` | 574 |  | exists | 574 | yes |
| 3 | `components/memory/useMemoryRun.ts` | 471 |  | exists | 471 | yes |
| 4 | `lib/code-languages.ts` | 180 | ★ | exists | 180 | yes |
| 5 | `lib/latex-commands.ts` | 172 | ★ | exists | 172 | yes |
| 6 | `hooks/useDragSort.ts` | 404 | ★ | exists | 404 | yes |
| 7 | `lib/personas-api.ts` | 128 | ★ | exists | 128 | yes |
| 8 | `lib/research-types.ts` | 125 | ★ | exists | 125 | yes |
| 9 | `hooks/useMcpServers.ts` | 248 |  | exists | 248 | yes |
| 10 | `lib/visualizers-api.ts` | 78 |  | exists | 78 | yes |
| 11 | `lib/space-items.ts` | 75 |  | exists | 75 | yes |
| 12 | `components/notebook/useNotebookSelection.ts` | 170 |  | exists | 170 | yes |
| 13 | `hooks/useKnowledgeHistory.ts` | 149 |  | exists | 149 | yes |
| 14 | `components/reading/workspace/useLearningMode.ts` | 143 |  | exists | 143 | yes |
| 15 | `lib/book-references.ts` | 62 |  | exists | 62 | yes |
| 16 | `lib/relative-time.ts` | 59 |  | exists | 59 | yes |
| 17 | `lib/tool-event.ts` | 56 |  | exists | 56 | yes |
| 18 | `hooks/useVoiceRecorder.ts` | 119 |  | exists | 119 | yes |
| 19 | `hooks/useSidebarResize.ts` | 116 |  | exists | 116 | yes |
| 20 | `lib/session-handoff-api.ts` | 51 |  | exists | 51 | yes |
| 21 | `lib/quiz-judge.ts` | 157 | ★ | exists | 157 | yes |
| 22 | `lib/picker-origin.ts` | 48 |  | exists | 48 | yes |
| 23 | `hooks/useSetupSync.ts` | 93 |  | exists | 93 | yes |
| 24 | `lib/session-unread.ts` | 92 | ★ | exists | 92 | yes |
| 25 | `lib/notebook-selection-types.ts` | 40 |  | exists | 40 | yes |
| 26 | `lib/random-uuid.ts` | 40 |  | exists | 40 | yes |
| 27 | `hooks/useModalDialog.ts` | 86 |  | exists | 86 | yes |
| 28 | `components/chat/preview/previewers/useTextSource.ts` | 80 |  | exists | 80 | yes |
| 29 | `components/reading/reading-actions-context.ts` | 80 |  | exists | 80 | yes |
| 30 | `lib/tools-settings.ts` | 35 |  | exists | 35 | yes |
| 31 | `hooks/use-linger-expand.ts` | 77 |  | exists | 77 | yes |
| 32 | `hooks/useVoiceMathSpeak.ts` | 74 |  | exists | 74 | yes |
| 33 | `lib/book-errors.ts` | 32 |  | exists | 32 | yes |
| 34 | `lib/datetime.ts` | 32 |  | exists | 32 | yes |
| 35 | `lib/kb-name.ts` | 32 |  | exists | 32 | yes |
| 36 | `components/reading/workspace-menu-context.ts` | 66 |  | exists | 66 | yes |
| 37 | `components/memory/MemorySection.tsx` | 1547 | ★ | exists | 1547 | yes |
| 38 | `components/chat/preview/previewers/useBinarySource.ts` | 64 |  | exists | 64 | yes |
| 39 | `components/common/markdown-renderer-core.ts` | 60 |  | exists | 60 | yes |
| 40 | `hooks/useCollapsiblePanel.ts` | 60 |  | exists | 60 | yes |
| 41 | `lib/youtube-iframe-api.ts` | 80 | ★ | exists | 80 | yes |
| 42 | `lib/settings-presets.ts` | 25 |  | exists | 25 | yes |
| 43 | `hooks/use-card-submission.ts` | 54 |  | exists | 54 | yes |
| 44 | `lib/workspace-drafts.ts` | 72 |  | exists | 72 | yes |
| 45 | `hooks/useResearchOutlineContinuation.ts` | 52 |  | exists | 52 | yes |
| 46 | `components/space/SkillsSection.tsx` | 1038 |  | exists | 1038 | yes |
| 47 | `components/cli-apps/CliAppsSection.tsx` | 1025 |  | exists | 1025 | yes |
| 48 | `components/memory/MemoryGraph.tsx` | 992 | ★ | exists | 992 | yes |
| 49 | `components/memory/MemoryRunPanel.tsx` | 952 | ★ | exists | 952 | yes |
| 50 | `lib/reading-media-time.ts` | 18 |  | exists | 18 | yes |
| 51 | `components/quiz/QuizConfigPanel.tsx` | 767 |  | exists | 767 | yes |
| 52 | `components/settings/ConnectionsEditor.tsx` | 762 |  | exists | 762 | yes |
| 53 | `components/mcp/McpCatalogBrowser.tsx` | 760 |  | exists | 760 | yes |
| 54 | `components/reading/library/MaterialLibrary.tsx` | 744 |  | exists | 744 | yes |
| 55 | `components/sidebar/SidebarNav.tsx` | 720 |  | exists | 720 | yes |
| 56 | `lib/floating-menu.ts` | 51 |  | exists | 51 | yes |
| 57 | `components/space/MyAgentsSection.tsx` | 696 |  | exists | 696 | yes |
| 58 | `components/chat/MyAgentsPicker.tsx` | 685 |  | exists | 685 | yes |
| 59 | `lib/use-auto-sized-textarea.ts` | 37 |  | exists | 37 | yes |
| 60 | `components/visualize/VisualizationViewer.tsx` | 677 | ★ | exists | 677 | yes |
| 61 | `components/reading/library/ReadingLibrary.tsx` | - |  | exists | 623 | - |
| 62 | `components/knowledge/KbDocumentList.tsx` | - |  | exists | 597 | - |
| 63 | `components/space/EduHubImportModal.tsx` | - |  | exists | 587 | - |

## 四、计数

- exists 63 / missing 0 / 改名 0 / 大改 0；loc 一致 60、不一致 0。
- DONE（web-zero 已标，本卡不重复结论，仅核对存在性）13；新种子 50。
- 局限：origin/main 与基线同 commit，commit 级漂移恒为零；本复核仍逐条实测存在性与行数，排除基线口径误差。

产物：`drift.md`（本文件）、`drift.json`（机器可读逐项状态）、`SHA256SUMS`。
