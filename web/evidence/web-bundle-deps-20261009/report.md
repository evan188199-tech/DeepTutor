# web/package.json 依赖清点与冗余扫描报告

- 基线: origin/main `6cf793bd868ba5ecbe64722936d4be8fab5a01df` (v1.6.14)，只读扫描
- 日期: 2026-10-09；manifest: `web/package.json`（27 dependencies + 21 devDependencies = 48 项）
- 方法: 对 1323 个源文件做字面量 import/require/动态导入扫描（排除 node_modules/.next/lockfile），叠加无引号配置键复核（postcss/tailwind/webpack alias）与逐文件人工核验；未发现计算式动态导入，静态扫描视为完备。lockfile 仅用于取 resolved 版本，不计为使用证据。
- 与既有卡去重: 本卡只清点依赖（源码死代码见 scan-web-dead-code，后端 Python 依赖见 scan-deps-drift）。
- 复算: `inventory.json` 含每项的引用桶（app-src/tests/scripts/config）、样例锚点、lockfile 版本与分类；按 method_notes 可重放。

## 结论一览

- 48/48 项均在 package-lock 解析成功，无缺失。
- 2 项依赖在源码中零引用，可直接移除（1 项上游已停维护）。
- 1 项依赖放错段（仅测试使用，应在 devDependencies）。
- 1 项依赖仅作为 mermaid 传递依赖被消费，直接声明未加说明。
- 3 个幽灵依赖（源码/脚本/测试 import 了未声明的包，靠 hoist 侥幸工作）。
- 2 项体积/维护风险点（1 项 bundle 体积、1 项上游 3 年未发版）。
- 2 项低风险备注 + 1 项工具链重叠备注。
- 正面确认：全部重型库均为动态导入（mermaid、pdfjs-dist、exceljs、docx-preview、epubjs、chart.js、@recogito/text-annotator），不在首屏 bundle。

## 发现清单（每条含 package.json 锚点与风险分级）

### F1 · high · react-chartjs-2 未使用，建议移除
- 锚点: `web/package.json:53`（`^5.3.1`，lock 5.3.1）
- 证据: 全仓零 import；图表功能直接 `import("chart.js/auto")`（`components/visualize/VisualizationViewer.tsx:62`，测试 mock `tests/visualize/VisualizationViewer.spec.tsx:36`）。react-chartjs-2 是 chart.js 的 React 包装层，本仓未采用。
- 建议: 从 dependencies 移除。无代码改动即可验证（lockfile 重算不引入该包）。

### F2 · high · html2canvas 未使用且上游停维护，建议移除
- 锚点: `web/package.json:44`（`^1.4.1`）
- 证据: 除 manifest 与 lockfile 外全仓零引用。上游 latest 仍为 1.4.1（npm view 2026-10-09 查询），长期维护停滞。
- 建议: 移除；若未来需要 DOM 截图再评估活跃替代品（如 html-to-image 类）。

### F3 · medium · jspdf 放错段（仅测试使用）
- 锚点: `web/package.json:46`（dependencies；lock 4.2.1）
- 证据: 唯一 import 在 `tests/e2e/pdf-reading-resize.audit.ts:2`（audit 项目内生成 PDF fixture）。产品代码零引用。
- 建议: 移到 devDependencies；不影响产物 bundle（本就未被 app 代码引用），纯依赖卫生与安装体积。

### F4 · medium · cytoscape 仅作为传递依赖被消费
- 锚点: `web/package.json:39`（`^3.33.1`）
- 证据: 源码零 import；仅在 `next.config.js:179-196` 作为 mermaid 的 cytoscape 依赖做 CJS alias（webpack + turbopack 两处）。直接声明的作用是保证 alias 解析路径 `node_modules/cytoscape/dist/cytoscape.cjs.js` 存在。
- 建议: 二选一：保留声明但在 next.config.js 注释处补一句"为何直接声明"；或删除声明、依赖 mermaid 的 hoisted 副本（npm 下可行，换包管理器有风险）。维持现状但补文档是最低成本选项。

### F5 · medium · 幽灵依赖 prettier
- 锚点: `scripts/generate-contracts.mjs:8`（`import { format } from "prettier"`）
- 证据: prettier 不在 package.json；现由 json-schema-to-typescript 的传递依赖（prettier 3.9.6，lockfile `node_modules/prettier`，dev:true）hoist 后侥幸解析。jstt 一旦调整依赖，`npm run contracts:generate/check:fast` 即断。
- 建议: 显式加入 devDependencies（或在脚本内改用自带的格式化路径）。

### F6 · low · 幽灵依赖 playwright
- 锚点: `scripts/probe-right-edge.mjs:1`（`import { chromium } from "playwright"`）
- 证据: 未声明；靠 `@playwright/test` 1.57.0 传递 hoist 解析。该脚本未接入任何 npm script（疑似临时探针）。
- 建议: 若保留脚本则显式声明 playwright（或改用 playwright-core）；否则随脚本一并清理。

### F7 · low · 幽灵依赖 jszip
- 锚点: `tests/epub-reader.audit.ts:2`（`import JSZip from "jszip"`）
- 证据: 未声明；靠 epubjs 传递依赖 jszip ^3.7.1 hoist 解析。
- 建议: 加入 devDependencies（测试显式依赖应自声明，避免上游换打包方式后失效）。

### F8 · medium · react-syntax-highlighter 根导入拉全量 Prism
- 锚点: `web/package.json:57`；`components/common/RichCodeBlock.tsx:3`（`import { Prism as SyntaxHighlighter } from "react-syntax-highlighter"`）
- 证据: 根入口导入 = 全量 Prism 语言集进入异步 chunk。组件已被懒加载（`components/common/RichMarkdownRenderer.tsx:52` next/dynamic；`components/chat/preview/previewers/TextPreview.tsx:10` React.lazy），不在首屏，但 chunk 体积显著偏大。上游维护正常（16.1.2，2026-10 更新），非停更风险。
- 建议: 改用 `react-syntax-highlighter/dist/esm/prism-light`（PrismLight）+ 按 `lib/code-languages.ts` 白名单 registerLanguage，可大幅缩减该异步 chunk。属代码改动，超出本卡范围，仅记录。

### F9 · medium · epubjs 上游 3 年未发版（维护风险）
- 锚点: `web/package.json:41`（`^0.3.93`，lock 0.3.93）
- 证据: npm view 显示 latest 0.3.93、modified 2023-09-26。EPUB 阅读是 Learner 核心功能（`components/reading/EpubDocumentView.tsx:417` 动态导入）。仓库已带 `@xmldom/xmldom ^0.9.12` override（`web/package.json:64-68`）修补其依赖链，正是依赖老化的症状。
- 建议: 列入观察清单；评估 epub.js 替代/自维护 fork 前先保持现状。本卡不动代码。

### F10 · low · docx-preview 0.x caret 钉在 0.3.x
- 锚点: `web/package.json:40`（`^0.3.7`）
- 证据: 0.x 的 caret 语义只允许 0.3.x；上游已有 0.4.1（2026-09 发布）。lock 0.3.7。
- 建议: 择期评估 0.4.x 升级（0.x minor 可能含破坏性变更，需回归 DocxPreview）。

### F11 · low · markdown 双解析路径（重叠备注）
- 锚点: `web/package.json:48`；`components/common/InlineFileCard.tsx:4`
- 证据: 仓内已有 react-markdown/remark 全家桶（react-markdown、remark-gfm、remark-math、rehype-katex、rehype-raw），InlineFileCard 又直接用底层 `mdast-util-from-markdown` 解析一次（提取链接预览）。mdast-util-from-markdown 本就是 remark 栈的底层件，体积小，属同栈轻度重叠。
- 建议: 保留；若 InlineFileCard 后续调整可考虑收敛到单一解析路径。

### F12 · info · 两套 schema→TS 代码生成工具并存
- 锚点: `web/package.json:84-85`；`scripts/generate-contracts.mjs:16-45`
- 证据: openapi-typescript 生成 `contracts/generated/api.ts`（输入 openapi.json），json-schema-to-typescript 生成 `turn-protocol.ts`（输入 JSON Schema）。输入格式不同，当前为互补关系，非重复。
- 建议: 仅在 schema 格式统一时再收敛为单工具。

## 正面确认（无需动作）

- 重型库全部动态导入：mermaid（`components/Mermaid.tsx:43`）、pdfjs-dist legacy（`lib/pdfjs-loader.ts:39`）、exceljs（`components/chat/preview/previewers/XlsxPreview.tsx:44`）、docx-preview（`DocxPreview.tsx:77`）、epubjs（`EpubDocumentView.tsx:417`）、chart.js（`VisualizationViewer.tsx:62`）、@recogito/text-annotator（`components/reading/TextUnitView.tsx:276`）。
- `@testing-library/dom` 是 @testing-library/react v16 的必需 peer，保留正确。
- `autoprefixer`/`tailwindcss`/`postcss` 经 postcss.config.js + tailwind.config.js（无引号键）与 Next 构建链生效；`dependency-cruiser` 经 `depcruise` CLI 在 `scripts.architecture:check` 使用。
- `clsx`+`tailwind-merge` 为标准 cn() 组合（`shared/ui/styles.ts`）；`simple-icons` 仅构建期消费（`scripts/build-brand-icons.mts` → `lib/brand-icons.generated.ts`）。
- `@types/react-syntax-highlighter` 必需（该包不带类型）；其余 @types/* 由 tsconfig 隐式消费。
- 未发现 moment/dayjs、axios、多图标库等常见重复引入；HTTP 一律走原生 fetch。

## 汇总数字

| 类别 | 数量 |
| --- | --- |
| 声明依赖（dep+devDep） | 48（27+21），lockfile 解析 48/48 |
| 扫描文件 | 1323 |
| 发现（F1-F12） | 12：high 2 · medium 5 · low 4 · info 1 |
| 其中声明依赖问题 | 8（F1-F4、F8-F11） |
| 幽灵依赖（未声明） | 3（F5-F7） |
| 建议直接移除 | 2（react-chartjs-2、html2canvas） |

## 边界与声明

- 本卡为只读清点：未安装依赖、未构建、未改动任何产品/测试代码；evidence 目录为唯一新增内容。
- 版本新鲜度依据 2026-10-09 `npm view`（只读元数据查询，非安装）。
- 高危点中最可执行的是 F1/F2（零引用移除）与 F5（幽灵 prettier 显式化）。
