# 前端 Vitest coverage 摘要

命令：`vitest run --coverage --coverage.reporter=text --coverage.reporter=json-summary --coverage.reporter=json --coverage.include='app/**|components/**|features/**|hooks/**|lib/**|context/**|shared/**'`（完整命令见 ../README.md）

## 总计 (app/components/features/hooks/lib/context/shared，排除 *.d.ts)
- statements: **28.11%** (13453/47855)
- branches: **25.53%** (10407/40749)
- functions: **23.62%** (2948/12478)
- lines: **29.24%** (12421/42474)

- 统计文件数: 856；其中 **0% 覆盖文件 397 个，共 19814 条语句完全未被测试触碰**。

## Top 20 按缺失语句数
| 模块 | 缺失语句 | 总语句 | 语句覆盖 |
|---|---:|---:|---:|
| `web/features/chat/components/ChatWorkspace.tsx` | 1074 | 1074 | 0.0% |
| `web/features/co-writer/components/CoWriterWorkspace.tsx` | 692 | 888 | 22.1% |
| `web/components/chat/home/StandaloneComposer.tsx` | 395 | 395 | 0.0% |
| `web/components/settings/ServiceConfigEditor.tsx` | 370 | 370 | 0.0% |
| `web/components/quiz/QuizViewer.tsx` | 366 | 366 | 0.0% |
| `web/features/settings/store/SettingsStore.tsx` | 354 | 740 | 52.2% |
| `web/features/chat/ChatStateAdapter.tsx` | 352 | 1002 | 64.9% |
| `web/components/watching/WatchingPane.tsx` | 350 | 350 | 0.0% |
| `web/app/(workspace)/learning/books/BooksRoute.tsx` | 343 | 551 | 37.7% |
| `web/components/chat/home/SessionViewerPanel.tsx` | 339 | 339 | 0.0% |
| `web/components/memory/MemorySection.tsx` | 324 | 324 | 0.0% |
| `web/lib/memory-graph.ts` | 314 | 314 | 0.0% |
| `web/features/chat/trace/TracePresentation.tsx` | 304 | 554 | 45.1% |
| `web/features/knowledge/api/client.ts` | 304 | 353 | 13.9% |
| `web/features/knowledge/components/engines/EngineDetail.tsx` | 301 | 377 | 20.1% |
| `web/components/chat/home/ChatComposer.tsx` | 295 | 295 | 0.0% |
| `web/components/partners/PartnerChat.tsx` | 254 | 525 | 51.6% |
| `web/app/(workspace)/partners/[partnerId]/page.tsx` | 254 | 254 | 0.0% |
| `web/components/memory/MemoryGraph.tsx` | 237 | 237 | 0.0% |
| `web/components/visualize/VisualizationViewer.tsx` | 232 | 236 | 1.7% |

注：Vitest(coverage-v8) 的 include 已显式列出源码目录，未被任何测试 import 的文件也以 0% 计入。逐行明细见 coverage-final.json.gz（HTML 树为可再生资产，未入库）。
