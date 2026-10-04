# web 性能预算现状扫描（只读盘点，未改任何代码）

- 日期：2026-10-04
- 仓库基线：origin/main @ `f07029cfc`（release: v1.6.13）
- 方式：新 worktree `dt-agen540-scan-wt`、新分支 `scan/perf-budget-20261004`，全部命令只读 + 本地构建；构建/检查均带时限（perl alarm 包装，等效 Linux `timeout`）。

## 1. 构建结果（如实记录）

| 项 | 值 | 复跑命令（在 `web/` 下） |
|---|---|---|
| `npm ci` | 成功，945 包 / 8s | `perl -e 'alarm shift; exec @ARGV' 1200 npm ci --no-audit --no-fund`（Linux 用 `timeout 1200 npm ci`） |
| `npm run build`（webpack 强制，见 `scripts/build.mjs:104`） | 成功，退出码 0，约 50s | `perl -e 'alarm shift; exec @ARGV' 1800 npm run build` |
| `npm run perf:check` | 成功，退出码 0，9 项全 OK（详见 §3） | `npm run build && perl -e 'alarm shift; exec @ARGV' 600 npm run perf:check` |

无超时、无失败；`perf:check` 内部启动的 `next start` 由脚本 finally 自杀，本机遗留的 next-server（PID 6303，2026-09-28 起）是机器上常驻 DeepTutor 实例，与本扫描无关。

## 2. 既有预算/检查脚本与阈值

唯一性能预算脚本：`web/scripts/route_budgets.mjs`
- 接线：`package.json` → `perf:check`、`build:perf`、完整门禁 `check`（= check:fast + build + perf:check）。`.github/workflows` 未单独引用（本仓库无该 workflow）。
- 测法：起生产 `next start`（随机端口，20s 就绪超时），拉各路由 HTML，累计 `<script src>` 引用的 `static/*.js` 原始体积；排除 framework + root app shell（用 /login 交叉求交/差集识别）。
- 阈值定义在 `ROUTE_TARGETS`（`route_budgets.mjs:12-30`）与 `ROOT_SHELL_BUDGET_KB=390`（`:32`）：

| 路由 | 预算 KB |
|---|---|
| /chat、/chat/[sessionId] | 1020 |
| /settings | 840 |
| /knowledge-bases | 550 |
| /co-writer | 320 |
| /co-writer/[docId] | 515 |
| /learning/reading/[workspaceId]/sessions/[sessionId] | 1160（v1.6.10 依赖升级上调过） |
| /learning/mastery/[pathId]/sessions/[sessionId] | 980 |
| root-app-shell | 390 |

复跑阈值清单：`sed -n '12,33p' web/scripts/route_budgets.mjs`

## 3. 实测 vs 预算差距（按利用率降序；复跑命令见 §1 perf:check）

原始输出：`perf-check-output.txt`

| # | 路由 | 实测 | 预算 | 余量 | 利用率 |
|---|---|---|---|---|---|
| 1 | /learning/reading/…/sessions/[sessionId] | 1155KB | 1160KB | **5KB** | 99.6% |
| 2 | /chat | 1008KB | 1020KB | **12KB** | 98.8% |
| 3 | /chat/[sessionId] | 1008KB | 1020KB | **12KB** | 98.8% |
| 4 | /learning/mastery/…/sessions/[sessionId] | 927KB | 980KB | 53KB | 94.6% |
| 5 | /co-writer | 273KB | 320KB | 47KB | 85.3% |
| 6 | root-app-shell | 274KB | 390KB | 116KB | 70.3% |
| 7 | /co-writer/[docId] | 378KB | 515KB | 137KB | 73.4% |
| 8 | /knowledge-bases | 330KB | 550KB | 220KB | 60.0% |
| 9 | /settings | 116KB | 840KB | 724KB | 13.8% |

全部 OK，无 FAIL。风险集中在 #1–#4：reading 会话页仅 5KB 余量（0.4%），一次普通依赖升级即会击穿；/chat 两路由 12KB 余量。

## 4. 构建产物体积

复跑：`cd web && du -sh .next .next/static .next/standalone .next/server`

| 目录 | 体积 |
|---|---|
| .next 合计 | 1.2G |
| .next/static（浏览器资产） | 17M |
| .next/standalone（自包含服务端） | 95M |
| .next/server | 21M |

最大静态 chunk Top 10。复跑：`find web/.next/static/chunks -name "*.js" -exec stat -f "%z %N" {} \; | sort -rn | head -10`

| chunk | 体积 |
|---|---|
| 6edf0643.3b7388bff92393ec.js | 910KB（=exceljs 懒加载包，见 §5） |
| 4353.65cb4bd5f5c758f9.js | 602KB |
| 7763.30a93b092022ba01.js | 532KB |
| 51fb665c.d90340c085d1102d.js | 473KB |
| 8863.5ad3fa8e336d2c48.js | 461KB |
| 8067.b338d059b25c93f3.js | 456KB |
| d2c0ed46.d4c3ca2b75dcc505.js | 419KB |
| 7495.7185470af4649c40.js | 401KB |
| 9068.4dd6359ec3256e83.js | 399KB |
| 329.621bcd78a5957472.js | 351KB |

## 5. 路由级 code-split 现状

**已动态分包（懒加载，不进首屏）**。复跑：
`node -e 'const rl=require("./web/.next/react-loadable-manifest.json");const fs=require("fs"),p=require("path");const s=f=>{try{return fs.statSync(p.join("web/.next",f)).size}catch{return 0}};Object.entries(rl).map(([m,i])=>[m.replace(/^.*node_modules\//,""),(i.files||[]).reduce((t,f)=>t+s(f),0)]).sort((a,b)=>b[1]-a[1]).slice(0,15).forEach(([m,b])=>console.log(Math.round(b/1024)+"KB  "+m))'`

| 边界（引入文件 → 库） | 懒加载体积 |
|---|---|
| components/Mermaid.tsx:43 → mermaid | 核心 1032KB + 15+ 个图表类型子 chunk（628/500/497/495/483…KB，合计约 6MB+，按需加载） |
| components/chat/preview/previewers/XlsxPreview.tsx:44 → exceljs | 910KB |
| components/chat/preview/previewers/TextPreview.tsx | 795KB |
| components/common/RichMarkdownRenderer.tsx:52 `dynamic()` → RichCodeBlock（react-syntax-highlighter） | 778KB |
| lib/pdfjs-loader.ts:39 → pdfjs-dist/legacy | 495KB |
| i18n/init.ts → 各语言 app.json（uk/fr/pl/de…） | 每语言 400–532KB，按语言懒加载 |
| features/settings/sections/AppearanceSettingsSection.tsx | 623KB |
| components/chat/preview/previewers/DocxPreview.tsx:77 → docx-preview、components/reading/EpubDocumentView.tsx:417 → epubjs、components/visualize/VisualizationViewer.tsx:62 → chart.js/auto、components/reading/TextUnitView.tsx:276 → @recogito/text-annotator | 均为 `await import()` 懒加载 |
| `next/dynamic` 使用面 | 20+ 文件（`rg -c "next/dynamic" app components features context lib -g '*.ts' -g '*.tsx'`） |

**重依赖引入方式**：源码中无 `import … from "mermaid|exceljs|pdfjs-dist|jspdf|docx-preview|epubjs|html2canvas|chart.js|cytoscape"` 的静态引入；katex 仅 CSS 静态引入（`RichInlineMarkdown.tsx:3`、`RichMarkdownRenderer.tsx:8`），JS 走 `import("rehype-katex")`。

**首屏重路由的构成（急加载长尾）**。复跑（以 /chat 为例；reading 会话页同理，路径见 §3）：
`grep -ao 'static/chunks/[a-zA-Z0-9_.-]*\.js' 'web/.next/server/app/(workspace)/chat/page_client-reference-manifest.js' | sort -u`

| 路由 | client-reference 引用 | 说明 |
|---|---|---|
| /chat | 1244KB / 35 chunk | Top5：9915(193KB)、8046(125KB)、8272(124KB, remark/mdast markdown 管线)、7601(120KB)、5454(110KB) — 均为自研 app chunk，非单一巨型 vendor |
| reading 会话页 | 1446KB / 44 chunk | 与 /chat 共享 Top chunk，另加 8240(153KB, 阅读器代码) |

注：manifest 口径含 framework/shell chunk，故略高于 perf:check 的实测口径（排除 framework 185KB + root shell 274KB 后即 §3 数字）。

## 6. 依赖声明清理候选（仅声明未用，不影响包体）

复跑：`for d in jspdf html2canvas cytoscape; do printf "%s: " $d; rg -l "$d" web --hidden -g '!node_modules' -g '!.next' -g '!package-lock.json' | tr '\n' ' '; echo; done`

| 依赖 | 源码引用 |
|---|---|
| html2canvas | 无（仅 package.json） |
| cytoscape | 无（仅 next.config.js alias 兼容层） |
| jspdf | 仅 tests/e2e/pdf-reading-resize.audit.ts |

## 7. 差距结论 Top 5（不做优化，仅记录）

1. reading 会话页余量 5KB（99.6%）— 任何依赖升级都会破线，与脚本注释"v1.6.10 曾上调至 1160"相互印证。
2. /chat 余量 12KB（98.8%）。
3. /chat/[sessionId] 余量 12KB（98.8%）。
4. mastery 会话页余量 53KB（94.6%）。
5. /co-writer 余量 47KB（85.3%）。

方向性观察（留给后续优化卡）：/chat、reading 的首屏重量是自研代码长尾（几十个 100–200KB app chunk）+ markdown 渲染管线，而非单个大 vendor；mermaid/exceljs/语法高亮/pdfjs/语言包已全部懒加载，静态引入面干净。
