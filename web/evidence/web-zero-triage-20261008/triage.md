# web 零测试模块 triage 为前端补测种子（AGEN-1181）

- 日期：2026-10-08；卡：AGEN-1181；只读 triage，不改任何产品/测试代码
- 输入：`myfork` 分支 `scan/web-test-gaps-20261007` 的 `web/evidence/web-test-gaps-20261007/summary.json`（本目录快照 `input_summary.json`，字节一致）
- 信号基线：`/Users/Shared/DeepTutor` `origin/main` @ `6cf793bd868ba5ecbe64722936d4be8fab5a01df`（release v1.6.14），只读

## 一、输入与对账

- 池：summary.json 中 `zero` 且 category ∈ {components, hooks, lib} = **248**（components 201 + hooks 16 + lib 31）。
- 卡面引 report.md 的 205/16/33（=254）是该报告早稿口径；summary.json 为权威输入，差 6 条来自 barrel 升级（zero→weak）后的重算。本 triage 以 summary.json 为准。
- 其中 1 条在信号基线已不存在：`components/watching/WatchingPlayer.tsx`（已删/改名，计 missing，不参与排序）。
- 去重：后端轴 `scan-weak-top100-triage` 仅覆盖 `deeptutor/`，与本 web 轴无重叠。

## 二、排序口径（可复算）

`score = log10(loc + 10) × factor`，按 `(-score, path)` 字典序排序，取前 60。
`loc` 取信号基线（origin/main HEAD）原始行数，与 scan 口径一致。

factor 按静态信号判定（源码先剥离注释再匹配；`import type` 不算 react 运行时耦合）：

| 信号 | 判定 | factor |
| --- | --- | --- |
| pure-logic | .ts 且无 server/browser/fetch/react 耦合 | 1.00 |
| hook/react | 文件名 `useXxx`/`use-xxx`，或（非 type-only）import react | 0.85 |
| browser/fetch | 使用 window/document/localStorage/WebSocket/fetch 等运行时 API | 0.80 |
| component-logic | .tsx 含 JSX 且有 state/handler 信号或 loc≥60 | 0.50 |
| component-presentational | .tsx 含 JSX、无 state/handler 且 loc<60 | 0.50 |
| barrel | index 文件且无自有逻辑 | 0.30 |
| server-bound | 引用 node 内建/next/server/`use server` | 0.30 |

建议映射（确定性规则，harvest 拆卡时可按模块实际职责复核）：
pure-logic→单测（纯函数/表映射）；hook/react→单测（renderHook：状态机+清理）；browser/fetch→单测（jsdom mock）；component-logic→渲染测（testing-library：状态与交互分支）；component-presentational loc<30→放弃、30–59→移交 e2e；server-bound→移交 e2e/集成；barrel→放弃（覆盖随成员模块）。

复算命令（在本分支检出内）：

```bash
cd web && python3 evidence/web-zero-triage-20261008/triage_score.py \
  --web-root . --summary evidence/web-zero-triage-20261008/input_summary.json \
  --out /tmp/top60.json --limit 60   # 同输入字节级一致
```

## 三、去重（本批已建卡 → DONE + key）

| 模块 | key |
| --- | --- |
| hooks/useDragSort.ts | AGEN-1156 |
| lib/code-languages.ts | AGEN-1165 |
| lib/latex-commands.ts | AGEN-1166 |
| lib/quiz-judge.ts | AGEN-1167 |
| lib/personas-api.ts | AGEN-1168 |
| lib/research-types.ts | AGEN-1169 |
| lib/session-unread.ts | AGEN-1170 |
| lib/youtube-iframe-api.ts | AGEN-1173 |
| components/memory/MemoryGraph.tsx、MemoryRunPanel.tsx | AGEN-1189 |
| components/memory/MemorySection.tsx、MemoryWorkbench.tsx | AGEN-1188 |

- 另：`context/QuizFollowupContext.tsx` 已建卡 AGEN-1157（context 类，不在本 248 池内，仅备注）。
- 信号基线新增覆盖 2 项，也标 DONE：`lib/memory-graph.ts`（tests/lib/memory-graph.test.ts，行为引用）、`components/visualize/VisualizationViewer.tsx`（tests/visualize/VisualizationViewer.spec.tsx）。
- 仅有 `vi.mock` 桩接或类型引用的不算已覆盖（保留为种子，13 项带 stub 注记），如 `lib/tools-settings.ts`、`lib/workspace-drafts.ts`、`components/quiz/QuizConfigPanel.tsx`。
- AGEN-1189 去重行提及 "test-memory-graph（lib 纯函数）"：lib 侧现已有基线测试覆盖，无需再单独建卡。

## 四、Top60（★=DONE，非新种子）

| # | path | loc | 信号 | score | 建议 |
| --- | --- | --- | --- | --- | --- |
| 1 | `lib/memory-graph.ts` | 762 | pure-logic | 2.888 | ★ DONE - origin/main 已覆盖（行为引用：tests/lib/memory-graph.test.ts） |
| 2 | `components/partners/group/useGroupSession.ts` | 574 | hook/react | 2.351 | 单测（renderHook：状态机 + 清理语义） |
| 3 | `components/memory/useMemoryRun.ts` | 471 | hook/react | 2.280 | 单测（renderHook：状态机 + 清理语义） |
| 4 | `lib/code-languages.ts` | 180 | pure-logic | 2.279 | ★ DONE - 已建卡 AGEN-1165 |
| 5 | `lib/latex-commands.ts` | 172 | pure-logic | 2.260 | ★ DONE - 已建卡 AGEN-1166 |
| 6 | `hooks/useDragSort.ts` | 404 | hook/react | 2.224 | ★ DONE - 已建卡 AGEN-1156 |
| 7 | `lib/personas-api.ts` | 128 | pure-logic | 2.140 | ★ DONE - 已建卡 AGEN-1168 |
| 8 | `lib/research-types.ts` | 125 | pure-logic | 2.130 | ★ DONE - 已建卡 AGEN-1169 |
| 9 | `hooks/useMcpServers.ts` | 248 | hook/react | 2.050 | 单测（renderHook：状态机 + 清理语义） |
| 10 | `lib/visualizers-api.ts` | 78 | pure-logic | 1.944 | 单测（纯函数/表映射，直接断言） |
| 11 | `lib/space-items.ts` | 75 | pure-logic | 1.929 | 单测（纯函数/表映射，直接断言） |
| 12 | `components/notebook/useNotebookSelection.ts` | 170 | hook/react | 1.917 | 单测（renderHook：状态机 + 清理语义） |
| 13 | `hooks/useKnowledgeHistory.ts` | 149 | hook/react | 1.871 | 单测（renderHook：状态机 + 清理语义） |
| 14 | `components/reading/workspace/useLearningMode.ts` | 143 | hook/react | 1.857 | 单测（renderHook：状态机 + 清理语义） |
| 15 | `lib/book-references.ts` | 62 | pure-logic | 1.857 | 单测（纯函数/表映射，直接断言） |
| 16 | `lib/relative-time.ts` | 59 | pure-logic | 1.839 | 单测（纯函数/表映射，直接断言） |
| 17 | `lib/tool-event.ts` | 56 | pure-logic | 1.820 | 单测（纯函数/表映射，直接断言） |
| 18 | `hooks/useVoiceRecorder.ts` | 119 | hook/react | 1.794 | 单测（renderHook：状态机 + 清理语义） |
| 19 | `hooks/useSidebarResize.ts` | 116 | hook/react | 1.785 | 单测（renderHook：状态机 + 清理语义） |
| 20 | `lib/session-handoff-api.ts` | 51 | pure-logic | 1.785 | 单测（纯函数/表映射，直接断言） |
| 21 | `lib/quiz-judge.ts` | 157 | browser/fetch | 1.778 | ★ DONE - 已建卡 AGEN-1167；注意：现有引用均为 vi.mock 桩 |
| 22 | `lib/picker-origin.ts` | 48 | pure-logic | 1.763 | 单测（纯函数/表映射，直接断言） |
| 23 | `hooks/useSetupSync.ts` | 93 | hook/react | 1.711 | 单测（renderHook：状态机 + 清理语义） |
| 24 | `lib/session-unread.ts` | 92 | hook/react | 1.707 | ★ DONE - 已建卡 AGEN-1170 |
| 25 | `lib/notebook-selection-types.ts` | 40 | pure-logic | 1.699 | 单测（纯函数/表映射，直接断言） |
| 26 | `lib/random-uuid.ts` | 40 | pure-logic | 1.699 | 单测（纯函数/表映射，直接断言） |
| 27 | `hooks/useModalDialog.ts` | 86 | hook/react | 1.685 | 单测（renderHook：状态机 + 清理语义） |
| 28 | `components/chat/preview/previewers/useTextSource.ts` | 80 | hook/react | 1.661 | 单测（renderHook：状态机 + 清理语义） |
| 29 | `components/reading/reading-actions-context.ts` | 80 | hook/react | 1.661 | 单测（renderHook：状态机 + 清理语义） |
| 30 | `lib/tools-settings.ts` | 35 | pure-logic | 1.653 | 单测（纯函数/表映射，直接断言）；注意：现有引用均为 vi.mock 桩 |
| 31 | `hooks/use-linger-expand.ts` | 77 | hook/react | 1.649 | 单测（renderHook：状态机 + 清理语义） |
| 32 | `hooks/useVoiceMathSpeak.ts` | 74 | hook/react | 1.636 | 单测（renderHook：状态机 + 清理语义） |
| 33 | `lib/book-errors.ts` | 32 | pure-logic | 1.623 | 单测（纯函数/表映射，直接断言） |
| 34 | `lib/datetime.ts` | 32 | pure-logic | 1.623 | 单测（纯函数/表映射，直接断言） |
| 35 | `lib/kb-name.ts` | 32 | pure-logic | 1.623 | 单测（纯函数/表映射，直接断言） |
| 36 | `components/reading/workspace-menu-context.ts` | 66 | hook/react | 1.599 | 单测（renderHook：状态机 + 清理语义） |
| 37 | `components/memory/MemorySection.tsx` | 1547 | component-logic | 1.596 | ★ DONE - 已建卡 AGEN-1188 |
| 38 | `components/chat/preview/previewers/useBinarySource.ts` | 64 | hook/react | 1.589 | 单测（renderHook：状态机 + 清理语义） |
| 39 | `components/common/markdown-renderer-core.ts` | 60 | hook/react | 1.568 | 单测（renderHook：状态机 + 清理语义） |
| 40 | `hooks/useCollapsiblePanel.ts` | 60 | hook/react | 1.568 | 单测（renderHook：状态机 + 清理语义） |
| 41 | `lib/youtube-iframe-api.ts` | 80 | browser/fetch | 1.563 | ★ DONE - 已建卡 AGEN-1173 |
| 42 | `lib/settings-presets.ts` | 25 | pure-logic | 1.544 | 单测（纯函数/表映射，直接断言） |
| 43 | `hooks/use-card-submission.ts` | 54 | hook/react | 1.535 | 单测（renderHook：状态机 + 清理语义） |
| 44 | `lib/workspace-drafts.ts` | 72 | browser/fetch | 1.531 | 单测（jsdom mock 浏览器/fetch 依赖）；注意：现有引用均为 vi.mock 桩 |
| 45 | `hooks/useResearchOutlineContinuation.ts` | 52 | hook/react | 1.524 | 单测（renderHook：状态机 + 清理语义） |
| 46 | `components/space/SkillsSection.tsx` | 1038 | component-logic | 1.510 | 渲染测（testing-library：状态与交互分支） |
| 47 | `components/cli-apps/CliAppsSection.tsx` | 1025 | component-logic | 1.507 | 渲染测（testing-library：状态与交互分支） |
| 48 | `components/memory/MemoryGraph.tsx` | 992 | component-logic | 1.500 | ★ DONE - 已建卡 AGEN-1189 |
| 49 | `components/memory/MemoryRunPanel.tsx` | 952 | component-logic | 1.492 | ★ DONE - 已建卡 AGEN-1189 |
| 50 | `lib/reading-media-time.ts` | 18 | pure-logic | 1.447 | 单测（纯函数/表映射，直接断言） |
| 51 | `components/quiz/QuizConfigPanel.tsx` | 767 | component-logic | 1.445 | 渲染测（testing-library：状态与交互分支）；注意：现有引用均为 vi.mock 桩 |
| 52 | `components/settings/ConnectionsEditor.tsx` | 762 | component-logic | 1.444 | 渲染测（testing-library：状态与交互分支） |
| 53 | `components/mcp/McpCatalogBrowser.tsx` | 760 | component-logic | 1.443 | 渲染测（testing-library：状态与交互分支） |
| 54 | `components/reading/library/MaterialLibrary.tsx` | 744 | component-logic | 1.439 | 渲染测（testing-library：状态与交互分支） |
| 55 | `components/sidebar/SidebarNav.tsx` | 720 | component-logic | 1.432 | 渲染测（testing-library：状态与交互分支） |
| 56 | `lib/floating-menu.ts` | 51 | browser/fetch | 1.428 | 单测（jsdom mock 浏览器/fetch 依赖） |
| 57 | `components/space/MyAgentsSection.tsx` | 696 | component-logic | 1.424 | 渲染测（testing-library：状态与交互分支） |
| 58 | `components/chat/MyAgentsPicker.tsx` | 685 | component-logic | 1.421 | 渲染测（testing-library：状态与交互分支） |
| 59 | `lib/use-auto-sized-textarea.ts` | 37 | hook/react | 1.421 | 单测（renderHook：状态机 + 清理语义） |
| 60 | `components/visualize/VisualizationViewer.tsx` | 677 | component-logic | 1.418 | ★ DONE - origin/main 已覆盖（行为引用：tests/visualize/VisualizationViewer.spec.tsx） |

## 五、计数与分布

- 池 248（1 missing）→ 评分 247；**Top60 中 DONE 13（已建卡 11 + 基线已覆盖 2），新种子 47**（单测 38 / 渲染测 9）。
- Top60 信号分布：pure-logic 20、hook/react 23、browser/fetch 4、component-logic 13。
- 未入 Top60 的 187 项：按第二节默认建议批量处理（lib/hooks 类默认单测、纯展示组件默认放弃/移交 e2e），全量带分与建议见 `triage_top60.json`（247 行全排序）。
- 排名 61 起为顺延位：61 仍是 DONE（`components/memory/MemoryWorkbench.tsx`，AGEN-1188）；跳过 DONE 后的新种子顺延前 3：`components/reading/library/ReadingLibrary.tsx`、`components/knowledge/KbDocumentList.tsx`、`components/space/EduHubImportModal.tsx`。

## 六、局限

1. 静态信号为启发式：注释剥离对字符串内 `//` 的近似、行内 `{ type X }` 内联 type import 未单独识别；个别标签（如 react 耦合但实为纯函数的 `components/common/markdown-renderer-core.ts`）可能偏保守。
2. `vi.mock` 桩接判定按行匹配，无法识别跨行 `vi.mock(` 调用外的间接 mock 场景。
3. 建议为拆卡方向（单测/渲染测/移交 e2e/放弃），harvest 时应按模块实际职责与依赖可注入性复核后再拆。
4. 本卡为静态 triage，未运行任何测试套件；不改任何产品/测试代码。

产物：`triage.md`（本文件）、`triage_top60.json`（全 247 项机器可读排序）、`triage_score.py`（评分与去重脚本）、`input_summary.json`（输入快照）、`SHA256SUMS`。
