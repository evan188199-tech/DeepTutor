# AGEN-412 · docx_converter 吞错分支特征测试（2026-10-03）

## 范围

`deeptutor/co_writer/docx_converter.py` 三处静默吞错分支（来源：`agent/dt22-todo-scan`
分支 `evidence/todo-scan-2026-10-03/report.md` §7，行号按函数名重定位到 origin/main
`ef2d9e5c3`）：

| 函数 | main 行号 | 吞错方式 | 风险 |
| --- | --- | --- | --- |
| `_style_name` | :252（`except` :256） | `except Exception: pass` → 返回 `""` | 样式缺失时标题/列表级别静默丢失 |
| `_run_to_markdown` | :326（`except` :340） | `run.font.strike` 读取异常被忽略 | 删除线格式静默丢失 |
| `_table_to_markdown` | :351（`except` :356） | `except Exception: continue` | 坏行从输出表格中整行消失 |

## 测试产物

- `tests/co_writer/__init__.py` + `tests/co_writer/test_docx_converter_edges.py`（15 个用例）
- 不改任何产品代码。

## 关键环境事实（python-docx 1.2.0，Python 3.13，实测）

1. **strike 分支可由真实文档触发**：`<w:strike w:val="maybe"/>` 使 `run.font.strike`
   抛 `docx.exceptions.InvalidXmlError`（`Exception` 子类）→ 被吞，输出无 `~~`、无信号。
   合法值 `w:val="true"` 正常输出 `~~text~~`（对照组）。
2. **无名样式在 1.2.0 上有两条静默路径**：删除 styles.xml 中 `Heading1` 定义后，
   `paragraph.style` 不再抛错，而是 python-docx 自行回退到 `Normal`；`_style_name`
   的 `except` 分支因此只能用桩对象锁定（旧版 python-docx 此处抛 KeyError）。
   两条路径最终表现一致：文本保留、`#` 标记消失、无任何信号。
3. **坏单元格/坏行在 1.2.0 上多数已变宽容**：删 `w:tc`、`gridSpan` 溢出、`vMerge`
   错配均不再抛错（删 tc 返回剩余单元格；gridSpan 溢出会重复单元格）。
   `except: continue` 分支只能用桩对象锁定；真实文档路径以正向对照组记录现状。

## 用例清单（15）

`_style_name`（5）：
1. style 属性抛错 → 返回 `""`（CURRENT，桩）
2. `style.name` 抛错 → 返回 `""`（CURRENT，桩）
3. `style is None` → 返回 `""`
4. 正常样式名 → 返回名称（对照）
5. `_paragraph_to_markdown` 组合：样式抛错 → 正文保留、无 `#`（CURRENT）

`_style_name` 真实文档端到端（1）：

6. 删除 Heading1 定义的 docx → `docx_to_markdown` 不抛错、文本保留、标题标记消失（CURRENT）

`_run_to_markdown`（4）：

7. `w:val="maybe"` 真实文档 → 无 `~~`、文本保留、fixture 确认读取确实抛错（CURRENT）
8. `w:val="true"` → 输出 `~~struck text~~`（对照，防止修复后断言翻错方向）
9. 桩 run strike 抛错 + bold → 输出 `**gone**`（CURRENT：吞错后流程继续、加粗生效、无删除线）
10. 公共入口 `docx_to_markdown` + 坏 strike 值 → 不抛错、文本保留、无 `~~`（CURRENT）

`_table_to_markdown`（4）：

11. 好行+坏行混合 → 坏行整行消失、好行组成可解析管道表（CURRENT，桩）
12. 全部行坏 → 返回 `""`（CURRENT：空表与坏表不可区分，桩）
13. 真实文档删 `w:tc` → 1.2.0 宽容返回剩余单元格，行保留并按网格宽度补空（正向对照；
    若未来 python-docx 收紧为抛错，此用例即记录当时的静默丢行行为）
14. 单元格竖线/换行转义对照（夹具健全性）

公共入口组合（1）：

15. 标题+坏 strike 同文档 → 不抛错、输出可检、格式静默降级

## 复现命令与结果

```bash
cd <worktree>   # 分支 agent/agen412-docx-converter-edge-tests（基于 origin/main ef2d9e5c3）
/Users/Shared/DeepTutor/.venv/bin/python -m pytest tests/co_writer/test_docx_converter_edges.py -v
# 15 passed in 0.40s

/Users/Shared/DeepTutor/.venv/bin/python -m pytest tests/api/test_co_writer.py tests/co_writer/ -q
# 49 passed in 1.09s（含既有 34 个用例，无回归）

/Users/Shared/DeepTutor/.venv/bin/python -m ruff check tests/co_writer/
/Users/Shared/DeepTutor/.venv/bin/python -m ruff format --check tests/co_writer/
# 全部通过
```

## 与上游 PR 的关系

- **PR #1700**（open，"fix(co-writer): keep a placeholder row and warn when DOCX
  table row parsing fails"，2026-10-04 开）已覆盖三处之一的 `_table_to_markdown`
  **修复**（占位行 + 警告日志，测试加在 `tests/api/test_co_writer.py`）。本卡是三处
  分支的**现状特征测试**，不改产品代码，与 #1700 互补而非重复；修复卡领取 #1700 后，
  需按其行为翻转本文件中标 CURRENT 的表格断言（坏行 → 占位行 `(unparseable row)`），
  用例 11/12 的翻转点已在 docstring 标明。
- `_style_name` 与 `_run_to_markdown` 两处目前无上游修复 PR（检索 open PR 无命中）。

## 修复卡提示（领取前阅读）

- strike 修复方向：`except` 内降级记录（logger.warning）或按 python-docx 语义把
  非 bool 值视为未加删除线；无论哪种，翻转点是用例 7/9/10 的 CURRENT 断言 + 新增
  "有信号"断言。
- 样式修复方向：`_style_name` 吞错时至少 logger.debug/warning；真实文档的 Normal
  回退路径在 python-docx 内部，产品代码无法拦截，证据见用例 6。
- 表格修复：直接复核 PR #1700。
