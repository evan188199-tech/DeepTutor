# web console.error / console.warn 三态清点（遗留轴）

- 日期：2026-10-13
- 基线：`origin/main` @ `6cf793bd8`（release v1.6.14），独立 worktree，只读静态扫描，未改动任何源码
- 口径：`web/**/*.{ts,tsx,js,jsx,mjs,mts,cts,cjs}`（排除 `node_modules`/`.next`）
- 基准对齐：`scan/print-console-residue-20261011`（AGEN-1787）报告 §3 记录的 `console.error(38) / console.warn(7)`。复现口径为**带调用括号**的 `console\.(error|warn)\(`：38 + 7 = **45 处**，与基准一致；若放宽为裸词（`\b` 无括号）则另有 1 处标识符引用（`web/tests/setup/rendered.ts:73`），合计 46 命中 / 45 行（`web/lib/iframe-html.ts:22` 一行同时含 error 与 warn 两个匹配）。

## 1. 汇总（三态）

| 三态 | 数量（按匹配） | 生产可达 | 说明 |
| --- | --- | --- | --- |
| 合理保留（错误上报/边界兜底） | 36 | 14 处可达 / 22 处不可达 | 产品代码 14 处均为 console 与用户可见反馈（toast/错误态/dispatch failed）或带明确设计注释的兜底并存；22 处为 `web/scripts/` CLI/CI 工具的设计输出通道 |
| 疑似调试残留 | 7 | 全部可达 | 与 AGEN-520「吞错替代品」同集：console 是失败路径**唯一**处理，终端用户在 production 看不到 console；严格说是"生产不可见的错误上报残留"而非开发期 print 式调试 |
| 误报 | 3 | 2 处间接 / 1 处不可达 | 字符串字面量内联脚本 ×2（`web/lib/iframe-html.ts:22` 一行 error+warn）、标识符引用 ×1（`web/tests/setup/rendered.ts:73`） |

合计 46 匹配 / 45 行。error 38（22 scripts + 15 产品调用 + 1 字符串内联）、warn 7（6 产品调用 + 1 字符串内联）。

## 2. 去重结论

- **vs AGEN-1787（print / console.log·debug 轴，同基线 6cf793bd8）**：方法轴不相交（log/debug vs error/warn），`file:line` 级零重叠。其 web 侧 17 处（scripts 工具 + JSDoc 注释示例）与本清单无共同行。
- **vs AGEN-520（`scan/console-noise-20261004`，v1.6.13 旧 web console 轴）**：本卡 45 处中 44 处被其覆盖（其口径 39 error 命中 + 6 warn 命中），增量核对结果：
  - **唯一新增**：`web/components/chat/home/ChatComposer.tsx:565`（warn，workspace 草稿恢复失败兜底，带设计注释）→ 合理保留。
  - **行漂移 7 处**（同调用、仅行号移动，已按现上下文复核判定不变）：`ChatStateAdapter.tsx` 2261→2254、2412→2405、3582→3579、3620→3617；`ChatWorkspace.tsx` 917→882；`SettingsStore.tsx` 832→841、845→854。
  - 其余 37 处 `file:line` 完全一致，判定沿用并抽样复核。

## 3. 疑似调试残留（7 处，可拆修复卡）

| # | 位置 | 失败后果（一句） | 建议批次 |
| --- | --- | --- | --- |
| 1 | `web/components/sidebar/WorkspaceSidebar.tsx:78` | 会话列表加载失败仅留日志，骨架消失后侧栏假空，与"无会话"不可区分 | 批次1 |
| 2 | `web/components/sidebar/UtilitySidebar.tsx:65` | 同 #1（同构代码） | 批次1（与 #1 一卡） |
| 3 | `web/components/notebook/useNotebookSelection.ts:49` | 笔记本列表失败 `setNotebooks([])` 假空，选择器静默失效 | 批次2 |
| 4 | `web/components/notebook/useNotebookSelection.ts:79` | 记录展开失败仅留日志，内容区空白无提示 | 批次2（与 #3 一卡） |
| 5 | `web/features/chat/ChatStateAdapter.tsx:3617` | 删除 turn 失败仅留日志（dispatch 仅成功后执行），删除表现为"点了没反应" | 批次3 |
| 6 | `web/app/(workspace)/learning/books/BooksRoute.tsx:244` | hydratePage 失败页面停留旧内容，用户误以为已最新 | 批次4 |
| 7 | `web/components/quiz/QuizViewer.tsx:458` | 测验成绩上报失败仅留日志+隐式 signature 重置，成绩可能未存且用户不知 | 批次5 |

统一修复方向：**保留 console，补用户可见反馈**（toast / 行内错误态 / 重试入口），与 AGEN-520 §4 结论一致，v1.6.14 未变。

## 4. 可拆修复卡批次建议（5 张，全部 web 前端小卡）

| 批次 | 卡内容 | 涉及 | 优先级建议 |
| --- | --- | --- | --- |
| 批次1 | 会话侧栏加载失败错误态 + 重试入口 | WorkspaceSidebar:78 + UtilitySidebar:65（同构一次修） | P2 |
| 批次2 | 笔记本选择器 loadError 态 + 重试 | useNotebookSelection:49,79 | P2 |
| 批次3 | 删除 turn 失败 toast | ChatStateAdapter:3617 | P2 |
| 批次4 | hydratePage 失败行内提示（同文件 notify 模式现成） | BooksRoute:244 | P3 |
| 批次5 | 测验成绩保存失败提示 + 重试入口 | QuizViewer:458 | P3 |

## 5. 合理保留依据（摘要）

- **scripts/CLI（22 处）**：`i18n_parity`(10)、`i18n_audit`(6)、`build`、`typecheck`、`build-brand-icons`、`generate-contracts`、`route_budgets`、`run-node-tests`——均为 package.json scripts 挂载的独立 Node CLI/CI 工具（`i18n:parity`/`i18n:audit`/`perf:check`/`contracts:*` 等），stderr 是其设计输出通道；已核 app/features/components/lib 侧无任何 `import` 指向 `web/scripts/`，不进产物 bundle → 生产不可达。
- **产品错误上报 + 用户可见反馈并存（8 处 error）**：`BooksRoute.tsx:184/476/663/785`（notify toast）；`SettingsStore.tsx:841/854`（setSettingsError → 错误 UI + 解除 loading gate）；`ChatStateAdapter.tsx:2254`（dispatch STREAM_END failed + i18n 用户文案）；`ChatWorkspace.tsx:882`（内联 Rename failed + 重聚焦）。
- **边界兜底（6 处 warn）**：`Geogebra.tsx:173/177`（失败命令收集进 setCommandErrors 供 UI 展示）；`GeogebraTabContext.tsx:57`（查看器未挂载时设计内 no-op，带注释）；`ChatStateAdapter.tsx:2405`（trace 面板 best-effort，AbortError 已排除）；`:3579`（分支选择 fire-and-forget，本地 state 为真相源，带注释）；`ChatComposer.tsx:565`（草稿恢复失败保留原草稿，带注释）。

## 6. 误报排除（3 处）

| 位置 | 原因 |
| --- | --- |
| `web/lib/iframe-html.ts:22`（error） | 命中在 `KATEX_INIT_SCRIPT` 字符串字面量内：沙箱 iframe 内联脚本的 KaTeX 渲染 catch 兜底，非 TS 源码调用点；该内联脚本自身为设计内降级 |
| `web/lib/iframe-html.ts:22`（warn） | 同一行字符串内联脚本的 KaTeX 加载超时提示，同上 |
| `web/tests/setup/rendered.ts:73` | `const originalConsoleError = console.error` 为标识符引用（测试 spy），无调用括号；测试基建不进产物 |

## 7. 复现

```bash
# 计数复现（口径对齐 AGEN-1787 基准 38/7）
rg -o "console\.error\(" web -g '*.{ts,tsx,js,jsx,mjs,mts,cts,cjs}' --glob '!node_modules' --glob '!.next' | wc -l   # 38
rg -o "console\.warn\("  web -g '*.{ts,tsx,js,jsx,mjs,mts,cts,cjs}' --glob '!node_modules' --glob '!.next' | wc -l   # 7
rg -n  "console\.(error|warn)\b" web -g '*.{ts,tsx,js,jsx,mjs,mts,cts,cjs}' --glob '!node_modules' --glob '!.next' | wc -l  # 45 行

# 全量校验（扫描计数 + 逐行定位 + 三态合计，只读）
python3 evidence/web-console-warn-20261013/verify_console_error_warn.py   # RESULT: PASS
```

## 文件清单

1. `triage.csv` — 46 行逐条明细（match_id/file/line/method/三态/子型/生产可达/依据/修复批次/先前覆盖来源与行号）
2. `verify_console_error_warn.py` — 复现与校验脚本（只读）
3. `SHA256SUMS` — 本目录校验和

本清单为静态候选清点，不含任何运行时样本值；确认与修复由人决定。
