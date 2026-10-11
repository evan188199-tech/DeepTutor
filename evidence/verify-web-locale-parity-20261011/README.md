# verify: v1.6.14 窗口 web locale 键六语言奇偶复核 (AGEN-1807)

- 仓库基线: HKUDS/DeepTutor origin/main = 6cf793bd8 (`release: v1.6.14`)，窗口 v1.6.13..v1.6.14（96 commits）
- 锚点合并: 849ab2871 (#1310 reading workspace panels), 64bc0d8e7 (#1407 workspace journal overview) 均在窗口内
- 只读复核，不改源码

## 结论
- en 窗口新增键 175，变更值键 1，删除键 0；窗口键集合共 176
- 6 语言窗口键缺失合计（不含 en）：63
- 窗口键占位翻译（空值或与 en 完全相同，不含 en）：2
- 全文件级孤儿键（语言有、en 无）：fr=909 pl=16 de=0 uk=16 zh=0

## 文件
- key-matrix.md / key-matrix.csv — 窗口键 × 语言 × 状态矩阵
- missing-keys-by-language.md / .json — 可直接补齐的键名清单（含全文件级缺失/多余/空值）
- full-parity-snapshot.md — v1.6.14 全量奇偶快照
- per-lang-window-diff.md — 各语言窗口内增删改计数

复跑命令: `python3 scripts/gen_locale_parity_evidence.py`（在本 worktree 内）

## 详细结论
1. **fr 是唯一有窗口键缺失的语言**：63 个窗口键缺失（全部在 zh/de 已有翻译，属 fr 滞后，非新特性只写了 en）。
   - 其中含 visualCoverage.* 7 键、reading/learning journal、索引恢复、private MCP origins 等窗口新特性文案。
   - 全文件级 fr vs en：缺失 529、多余 909（多为旧版英文文案键的历史漂移，含 8 个 `_few/_many` 复数键）；窗口外差异属既有欠账，修复卡 fix-web-locales-parity / fix-web-locales-fr-dir-gap 未合入 main，故 main 仍存在缺口。
2. **窗口键占位翻译（低优先级）**：
   - fr `settings.providerServices.filter.imagegen` = `"Images"`（与 en 相同）
   - de `settings.providerServices.filter.videogen` = `"Video"`（与 en 相同）
   - 两者为 Images/Video 这类可保留原文的词，是否补译由人决定。
3. **pl/uk 的 16 个"多余键"为合法复数形式**（`_few`/`_many`，对应 en 的 `_one`/`_other`），非孤儿键，无需处理。
4. **zh 遗留空值键** `"s"` = `""`：v1.6.13 之前就存在（100ae2710 引入），非窗口键，属历史遗留。
5. **kanban.footer（窗口内唯一 en 变更值键）**：6 语言均已同步新译，无欠账。

## 补齐清单优先级
- P1：fr 补 63 个窗口缺失键（见 missing-keys-by-language.md 的 fr 段落）
- P2（可选）：fr/de 各 1 个占位键复核是否补译
- 无需处理：pl/uk 复数键、zh 遗留 `"s"` 键
