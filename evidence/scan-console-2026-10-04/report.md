# AGEN-520 · web/ console 残留与调试输出三型分型扫描报告

- **扫描对象**: HKUDS/DeepTutor `origin/main` @ `f07029cfcf2c8dfccdb671cdfc343db8334f5741`（v1.6.13），worktree `agen520-console-scan`，分支 `scan/console-noise-20261004`
- **扫描日期**: 2026-10-04
- **方式**: 只读静态扫描（Python 掩码扫描器 `scan_console.py` + ripgrep 交叉复核 + 逐条上下文人工分型）。**未修改任何产品代码，产物只进本证据目录。**
- **范围**: `web/**/*.{ts,tsx,js,jsx,mjs,mts,cts,cjs}`，共 **1258** 个文件（排除 `node_modules`、`.next`；`web/vendor/thinking-orbs` 无 console 调用，已含在扫描面内）。

## 1. 结论（PASS）

| 分型 | 数量 | 占比 | 说明 |
| --- | --- | --- | --- |
| 合理降级日志 | 56 | 88.9% | 含 13 处产品代码失败路径留痕、38 处 CLI 工具输出、1 处测试基建引用、4 处非代码提及（沙箱 iframe 内联脚本 ×2、文档注释示例 ×1、普通注释含 debugger 字样 ×1） |
| 调试残留 | 0 | 0% | **产品代码无 console.log/debug 调试残留；`debugger` 语句 0 处；被注释掉的调试块 0 处** |
| 吞错替代品 | 7 | 11.1% | console.\* 是失败路径的唯一处理，用户无感知（详见 §4 单列清单） |
| **合计** | **63** | 100% | — |

console 调用按方法分布（58 处真实调用）：`error` 37（63.8%）、`log` 16（27.6%）、`warn` 5（8.6%）；`debug/info/table/dir/trace` 等均为 0。**16 处 console.log 全部在 `web/scripts/` CLI 工具内（脚本的设计输出通道）；产品代码 console.log 为 0。**

产品代码口径（剔除 scripts/tests/非代码，20 处调用）：合理降级 13（65%）、吞错替代品 7（35%）、调试残留 0。

明细（逐条 kind/surface/in_catch/分型/严重度/理由/建议）见 `console_classified.json`（权威数据），原始探测数据见 `console_findings.json`。

## 2. 与 ripgrep 交叉复核

- rg 模式 `console\.(log|warn|error|...)\b`（同方法清单）命中 **62** 处 console.\*；本扫描 58 调用 + 3 非代码提及 + 1 标识符引用（`web/tests/setup/rendered.ts:73`，无调用括号的 `console.error` 引用，rg 口径计入）= 62，**一致**。
- rg `\bdebugger\b` 命中 1 处，为 `web/lib/brand-slugs.ts:83` 注释文本（指 LLVM 调试器），非语句；真实 `debugger;` 语句 0 处。

## 3. 分型标准与互补边界

- **合理降级日志**：失败路径留痕且伴随真实兜底——用户可见错误态/toast、显式设计注释、或 console 本身就是该表面的设计输出（CLI 脚本、测试基建、文档示例）。
- **调试残留**：开发期 console.log/debug 载荷、`debugger` 语句、注释掉的调试块。web/ 未发现。
- **吞错替代品**：console.\* 是失败的唯一处理——无用户可见反馈、无错误态、无重试入口，console 替代了真正的错误处理。

**与 scan-ts-catch（AGEN-421，空 catch + no-op `.catch` 分型）互补不重叠**：AGEN-421 覆盖的是"完全静默"的吞错（catch 体为空或 no-op）；本卡覆盖的 7 处吞错替代品全部是**带 console 留痕**的 catch，不在其口径内。AGEN-421 报告对"应上报"型给出的修复方向（console.error + 用户可见反馈）正是本卡 7 处的差距所在——它们已补了日志、缺用户反馈。逐条核对：本卡 63 项与 AGEN-421 的 41 项无任何同位置重复。

## 4. 吞错替代品清单（7 项，全部单列）

| # | 位置 | 严重度 | 失败后果（一句） | 建议 |
| --- | --- | --- | --- | --- |
| 1 | `web/app/(workspace)/learning/books/BooksRoute.tsx:244` | MEDIUM | 编辑/再生成后的 finally 重水化失败仅留日志，页面停留旧内容，用户误以为已是最新。 | 行内 toast「页面刷新失败，请重试」；保留 console.error |
| 2 | `web/features/chat/ChatStateAdapter.tsx:3620` | MEDIUM | 显式删除 turn 失败仅留日志（dispatch 在成功后才执行），删除表现为"点了没反应"。 | notify toast「删除失败，请重试」 |
| 3 | `web/components/quiz/QuizViewer.tsx:458` | MEDIUM | 测验成绩上报失败仅留日志；signature 复位带来隐式重试但用户不可见，成绩可能未保存。 | 完成区显示「成绩保存失败」轻提示 + 重试入口 |
| 4 | `web/components/sidebar/WorkspaceSidebar.tsx:78` | MEDIUM | 会话列表加载失败仅留日志，骨架消失后侧栏假空，与"无会话"不可区分。 | 错误态 + 重试入口 |
| 5 | `web/components/sidebar/UtilitySidebar.tsx:65` | MEDIUM | 同 #4（同构代码）。 | 同 #4，两处一并修 |
| 6 | `web/components/notebook/useNotebookSelection.ts:49` | MEDIUM | 笔记本列表失败后 `setNotebooks([])`，选择器假空，引用选择功能静默失效。 | 暴露 loadError 态供选择器渲染重试 |
| 7 | `web/components/notebook/useNotebookSelection.ts:79` | LOW | 笔记本记录展开失败仅留日志，loading 复位后内容区空白无提示。 | 行内「加载失败」提示 + 重试 |

上游开放 PR 核对（2026-10-04）：未发现覆盖以上 7 处的 open PR（`log-swallowed-failures` 系列均为后端 Python services；web 相关 open PR 主题为草稿恢复、设置测试、followup 回写等，位置不同）。

## 5. 合理降级日志中的产品代码留痕（13 处，抽样说明）

产品代码 13 处合理项的共同形态：**console 与用户可见处理并存**（toast/错误态/dispatch failed 状态）或**带明确设计注释的 best-effort**（分支选择 fire-and-forget 持久化、Geogebra CTA no-op、沙箱 iframe KaTeX 降级）。全部建议保留，无需改动。逐条理由见 `console_classified.json`。

## 6. 验收核对

1. **全量 console.\* 计数与分型比例**: 63 项 = 58 真实调用 + 1 标识符引用 + 3 非代码提及 + 1 注释 debugger 字样；分型 88.9% / 0% / 11.1%（§1）。
2. **吞错替代品单列 Top**: §4 单列 7 项（全部，不足 10 项）。
3. **不改任何代码**: 本分支相对 `origin/main` 仅新增本证据目录（`git diff --stat origin/main` 可核）。

## 7. 复现

```bash
python3 evidence/scan-console-2026-10-04/scan_console.py      # 生成 console_findings.json
python3 evidence/scan-console-2026-10-04/classify_console.py  # 生成 console_classified.json
```
