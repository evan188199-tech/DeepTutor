# 扫描证据 SHA256 完整性抽样复核（只读，未改动任何被核证据）

- 日期：2026-10-07
- 仓库：/Users/Shared/DeepTutor（fetch `origin` + `myfork` 后复核；`--prune`）
- 方法：全程只读——用 `git cat-file blob <branch>:<path>` 逐文件取 blob 字节，本地 `hashlib.sha256` 复算，与各分支 `evidence/*/SHA256SUMS` 逐条比对；另比对"清单条目 ↔ 分支树内实际文件"双向差集；再抽查报告内汇总数字与机器可读汇总（summary.json / findings.json / *classified.json / stats.json / cases.tsv / scan_inventory.tsv / 原始 .code 文件）的一致性。未 checkout 任何被核分支，未修改任何 evidence 文件。
- 复现：`python3 evidence/evidence-integrity-20261007/recompute.py > recompute_result.json`（原始逐文件结果见同目录 `recompute_result.json`）。

## 1. 抽样范围（8 个分支，跨 2026-10-03 ~ 2026-10-07 五个日期）

| 分支（myfork/scan/*） | evidence 目录 | 清单复算文件数 | 哈希一致 | 清单外文件 | 清单缺失文件 |
|---|---|---|---|---|---|
| a11y-basics-20261005 | a11y-basics-20261005 | 5 | 5/5 | 0 | 0 |
| coverage-gaps-20261005 | coverage-gaps-20261005 | 7 | 7/7 | 0 | 0 |
| cli-exit-codes-20261006 | scan-cli-exit-codes-20261006 | 50 | 50/50 | 0 | 0 |
| win-compat-20261004 | scan-win-compat-20261004 | 11 | 11/11 | 0 | 0 |
| mypy-adoption-20261006 | mypy-adoption-20261006 | 22 | 22/22 | 0 | 0 |
| web-error-boundaries-20261006 | scan-web-error-boundaries-20261006 | 8 | 8/8 | 0 | 0 |
| signal-handlers-20261007 | signal-handlers-20261007 | 3 | 3/3 | 0 | 0 |
| settings-draft-apply-20261003 | settings-scan-2026-10-03 | 1 | 1/1 | 0 | 0 |
| **合计** | | **107** | **107/107** | **0** | **0** |

说明：清单本身（SHA256SUMS）不自校验，按惯例不计入复算数；`cli-exit-codes` 的清单使用 `./` 相对路径前缀，复算脚本已做归一化后比对（该分支清单条目与树内文件一一对应）。

## 2. 哈希复算结论

- 复算文件：107 个，全部与清单记录一致（107/107）。
- 未发现任何一个"复算哈希 ≠ 清单哈希"的文件；未发现清单有而树中缺失、或树中有而清单遗漏的 evidence 文件。
- 结论：被抽样的 8 个分支的 evidence 工件自落库以来未被改动（哈希层面完整）。

## 3. 报告汇总数字抽查（报告 ↔ 机器可读汇总）

| 分支 | 抽查项 | 报告值 | 数据文件值 | 结论 |
|---|---|---|---|---|
| coverage-gaps-20261005 | report.md ↔ summary.json totals | 非入口模块 874 / 测试文件 775（751+24）/ 零测试 141 / 弱测试 235 / 包内测试 24 | noninit=874 / tests=775 / zero_noninit=141 / weak_single_test=235 / intree_tests=24 | 一致 |
| a11y-basics-20261005 | report.md ↔ findings.json + a11y_classified.json | 扫描文件 1253；A2 185 处/84 文件；A3 confirmed 19 处；B1×4；A4×3；非问题 6 处 | files_scanned=1253；A2=185（去重文件 84）；A3 tier=confirmed=19；B1=4；A4=3；triage=non-issue=6 | 一致 |
| cli-exit-codes-20261006 | report.md ↔ cases.tsv ↔ 原始捕获 | 动态用例 14 个；逐用例 exit/字节数 | cases.tsv 14 行；14/14 行与 capture/results/*.code、*.stdout、*.err 的实际 exit 与字节数逐条一致 | 一致 |
| mypy-adoption-20261006 | report.md ↔ stats.json | run A 总错 489 / 表面 321；run G 表面 262 | A_baseline 489/321；G_hookenv_strict_optional surface=262 | 一致 |
| **signal-handlers-20261007** | **report.md:6 ↔ scan_inventory.tsv** | **"171 条：proc_wait 136 / sig_send 27 / …"** | **数据行 170 条：proc_wait 135 / sig_send 27 / signal_signal 1 / signal_ignore 1 / add_signal_handler 1 / remove_signal_handler 1 / atexit_register 1 / kbd_interrupt 3** | **不一致（总数与 proc_wait 均恰好多 1）** |
| win-compat-20261004 | 无机器可读汇总（raw txt + report） | — | 哈希已全部复算一致 | 不适用 |
| web-error-boundaries-20261006 | 无机器可读汇总 | — | 哈希已全部复算一致 | 不适用 |
| settings-draft-apply-20261003 | 无机器可读汇总（仅 report） | — | 哈希已全部复算一致 | 不适用 |

## 4. 不一致清单（共 1 条）

| # | 位置 | 描述 |
|---|---|---|
| 1 | `myfork/scan/signal-handlers-20261007` → `evidence/signal-handlers-20261007/report.md` 第 6 行 | 报告称 `scan_inventory.tsv` 共 171 条、proc_wait 136 条；实际数据行 170 条、proc_wait 135 条。两者均恰好多 1，符合"汇总数字按旧版/全行数（含表头）口径写成、数据文件随后重生成"的模式；其余分类计数（27/1/1/1/1/1/3）与实际一致。文件本身哈希完整（SHA256SUMS 复算通过），属报告文字与数据的口径性偏差，不影响证据未被篡改的结论，但引用该报告"171 条"数字的下游需按 170 条修正。 |

## 5. 结论

- 抽样 8 个分支（≥4）、复算 107 个文件（≥40），全部给出一致/不一致结论。
- 工件完整性：107/107 哈希一致，清单与实际文件双向零差集——证据未被意外改动。
- 汇总数字抽查：6 个可抽查点中 5 个一致；1 处文字偏差（signal-handlers 总数 171 vs 实际 170），已在 §4 定位。
- 本复核只读，未修改任何 evidence 文件与既有分支；本目录（evidence/evidence-integrity-20261007/）为本次复核新增产物。
