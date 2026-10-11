# scan: web 显式 `any` 与 `@ts-ignore`/`@ts-expect-error` 残留清点

基线：`origin/main` @ `6cf793bd8`（release: v1.6.14），只清点，未改任何源码。

## 结论摘要

| 族 | 数量 | 说明 |
| --- | --- | --- |
| `: any`（annot-any） | 115 | 原始 117，剔除 2 处英文散文误报 |
| `as any`（as-any） | 21 | |
| `@ts-ignore` | 0 | 全树干净 |
| `@ts-expect-error` | 1 | 仅 tests/settings/settings-store.test.ts:423（SSR 模拟，带原因注释） |
| 合计（primary） | **137** | 分布在 13 个文件、3 个顶层目录 |
| 辅助位（aux：泛型/`Array<any>`/`ComponentType<any>`/`Promise<any>`） | 8 | 次要信号，单独列出 |

与 grep 独立交叉验证一致：`:\s*any\b` 原始 117、`as any` 21、`@ts-ignore` 0、`@ts-expect-error` 1。

## 成因分类（启发式，逐条 reason 见 inventory.json）

| 成因 | 数量 | 占比 | 内容 |
| --- | --- | --- | --- |
| 第三方集成（react-markdown） | 100 | 73% | 两个 Markdown 渲染器 + RichInlineMarkdown 的 `components` 覆盖映射，全部写成 `({ node, ...props }: any)` 模式 |
| 边界层 | 36 | 26% | 全部在 `tests/`：global stub（`(global.window as any)`）、私有成员访问（`(settingsContext as any).sync…`）、不完整 fixture（`} as any`）、宽松事件/局部变量（`event: any`、`let stored: any`） |
| 临时绕过（app 内） | 1 | 1% | `app/(workspace)/learning/books/components/LearningCapturePanel.tsx:25` 的 i18n 插值参数 `values?: any` |

vendor/ 目录无命中；`types/*.d.ts` 无命中；`@ts-ignore` 全树为 0。catch 块轴的异常处理扫描此前已单独完成，本清单与其不重叠。

## 分布

按文件（primary）：

| 文件 | 数量 | 成因 |
| --- | --- | --- |
| components/common/RichMarkdownRenderer.tsx | 51 | react-markdown components 映射 |
| components/common/SimpleMarkdownRenderer.tsx | 46 | 同上 |
| tests/settings-context-ui-sync.test.ts | 8 | 私有访问 + stub |
| tests/e2e/settings-navigation.audit.ts | 7 | 宽松局部变量 |
| tests/settings-context-boolean-hydration.test.ts | 7 | localStorage stub |
| tests/app-shell-storage-code-block.test.ts | 4 | event stub |
| tests/code-block-themes.test.ts | 4 | fixture 补形 |
| components/common/RichInlineMarkdown.tsx | 3 | 插件数组 + `COMPONENTS as any` |
| tests/model-settings-workflow.spec.tsx | 3 | mock fixture |
| app/(workspace)/learning/books/components/LearningCapturePanel.tsx | 1 | i18n 插值参数 |
| tests/settings/settings-store.test.ts | 1 | `@ts-expect-error`（唯一一处） |
| tests/settings-unified-draft.spec.tsx | 1 | `let stored: any` |
| tests/subagent-settings-apply.spec.tsx | 1 | `let stored: any` |

按目录：components 100、tests 36、app 1。

## Top 收紧目标排序

1. **components/common/RichMarkdownRenderer.tsx（51 + 辅助 4）** — 单文件收益最大。react-markdown 已是 v10（导出 `Components` / `ExtraProps` 类型），把映射键组件参数从 `any` 换成 `Components['p']` 等 + `ExtraProps`（`node?: Element`）即可整体消除；文件内 `sourceLineAttr(node: any)`、`lineAttr`、`Record<string, React.ComponentType<any>>`、插件 `Array<any>` 同批收口。
2. **components/common/SimpleMarkdownRenderer.tsx（46 + 辅助 2）** — 与 1 同构。两文件建议抽一个共享的 typed markdown-components 模块，一次定型、两处复用，避免下次新增标签又回到 `any`。
3. **components/common/RichInlineMarkdown.tsx（3）** — `remarkPlugins/rehypePlugins: any[]` 换 `PluggableList`，`components={COMPONENTS as any}` 随目标 1 的共享类型一并消失。
4. **tests/settings-context-ui-sync.test.ts（8）/ settings-context-boolean-hydration.test.ts（7）** — 私有成员访问类 `as any` 可通过导出（或 `@visibleForTesting`）收口；localStorage stub 可提一个 typed 测试工具。属边界层，风险低，优先级次之。
5. **app/(workspace)/learning/books/components/LearningCapturePanel.tsx:25（1）** — `values?: any` 改 `Record<string, unknown>`；顺手项。

## 渐进收紧路线建议

现状缺口不在编译器（tsconfig 已 `strict: true`，含 noImplicitAny），而在 lint 侧：`eslint.config.mjs` 未启用 `@typescript-eslint/no-explicit-any`，新增 `any` 当前无任何门禁。建议：

1. **第一步（低风险）**：`eslint.config.mjs` 对 `app/**`、`features/**`、`lib/**`、`shared/**` 开 `@typescript-eslint/no-explicit-any: "warn"`。按本清单，该范围现存量仅 1 处（LearningCapturePanel），先修掉再开，立即全绿。
2. **第二步**：上述范围升为 `"error"`，renderers/tests 暂不在范围内（待 3/4）。
3. **第三步**：完成 Top1–3 的 react-markdown 类型化（`Components` + `ExtraProps` + `PluggableList`，抽共享模块），把 `components/**` 纳入 error 范围。
4. **第四步（可选）**：tests 纳入 warn（现 36 处，多为 stub，允许按文件 `/* eslint-disable */` 收敛或逐个typed 化）。
5. **抑制注释策略**：`@ts-ignore` 保持 0（可加 eslint `@typescript-eslint/ban-ts-comment` 防回潮）；`@ts-expect-error` 允许但必须带原因注释（现存唯一一处已符合）。

相关背景：`as unknown as`（不在本次范围）共 75 处（tests 26、components 6、features 5、lib 2、shared 1、contracts 1 等），收紧 `any` 后它是下一个自然轴线，建议另卡处理。

## 方法与可复现

- 范围：`web/tsconfig.json` include 全集（app/components/context/contracts/features/hooks/i18n/lib/shared/scripts/tests/types + proxy.ts）+ 根配置 + vendor/（eslint 覆盖但不在 tsc include，单独口径）。
- 匹配：`: any`（含 `?: any`、`: any[]`）、`as any`、`@ts-ignore`、`@ts-expect-error`；辅助位捕获 `(<,=X` 前置的 `any`（泛型/默认类型）。
- 精度过滤：`any` 后紧跟字母判为英文散文丢弃（本次剔除 2 处，如字符串文案 `": any bad ref"`、注释 "any option value"）；ts 指令行不过滤。
- 成因判定：vendor / d.ts / react-markdown 文件的 components-键模式 / tests-scripts-contracts-proxy 目录 / 行级第三方-边界标记 / 其余 app 绕过；逐条带 reason。
- 复现：`python3 scan_ts_any_residue.py`（只读扫描，输出 inventory.json / summary.json）。

## 文件

- `inventory.json` — 137 条 primary + 8 条 aux 逐条明细（文件:行 / 族 / 成因 / 依据 / 片段）
- `summary.json` — 按族 / 成因 / 目录 / 文件聚合
- `scan_ts_any_residue.py` — 扫描脚本（只读）
- `SHA256SUMS` — 本目录文件校验和
