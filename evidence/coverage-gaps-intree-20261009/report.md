# scan: coverage-gaps 扫描器纳入 intree 测试并重算 zero/weak 清单（AGEN-1209）

- 日期：2026-10-09
- 仓库基线：origin/main @ `6cf793bd8`（release: v1.6.14），独立 worktree，未改任何产品/测试代码（仅本 evidence 目录）
- 输入：myfork `scan/coverage-gaps-det-20261006`（AGEN-873 修正版扫描器，与 `scan/coverage-gaps-20261007` 目录版字节相同）；`scan/learning-intree-collect-20261009` evidence/learning-intree-20261009/report.md（根因 :24/:78 测试宇宙只含根 tests/）
- 环境：/Users/Shared/DeepTutor/.venv（Python 3.13.13），扫描器/聚合器仅标准库；全部命令以 900s 时限包装执行

## 1. 最小修复内容（仅扫描器与聚合器）

`scan_coverage_gaps.py`（相对 AGEN-873 版的 diff）：

1. 测试宇宙扩为「根 `tests/` + 包内 `deeptutor/**/test_*.py`」：24 个 `deeptutor/learning/tests/test_*.py` 全部并入；另有 1 个包内测试文件 `deeptutor/services/config/test_runner.py` 一并并入——它本就是 aggregate 既有"包内 test 按测试计"口径的一部分（AGEN-662 报告同口径计 24=23+1），并入后 `n_tests` 与 `totals.intree_tests` 同源（同一 basename 判据），不重不漏。卡片点名的 24 个 learning intree 文件 100% 在宇宙内（`raw.n_intree_tests=25`，learning 24 + 包内 1）。
2. 包内测试文件的相对导入按各自包根解析（learning intree 24 个全部绝对导入，不受影响；`test_runner.py` 用相对导入，按 learning-intree-20261009 修复建议第 2 条以自身包根解析，避免其覆盖被漏算）。根 `tests/` 的相对导入解析分支保持原样未动。
3. raw 新增 `n_root_tests` / `n_intree_tests` / `intree_test_files` 字段，输出路径改写至本目录；确定性（排序迭代）逻辑不变。
4. 溯源字段由 `root_commit`（扫描时 HEAD，分支 tip 提交后复跑必漂移）改为 `deeptutor_tree`（`git rev-parse HEAD:deeptutor` 子树对象名，当前值 `f05ae923…`，与基线 6cf793bd8 的产品树完全一致）；evidence-only 提交不改产品树，故分支 tip 上复跑输出字节稳定。aggregate 的 summary 同步该字段。

`aggregate.py`：

1. zero/weak 判定改为纯消费扩展后的 `covered`/`n_cover`（去掉旧的 `and not m["intree_tests"]` 与 `n_cover + len(intree_tests)` 混合口径），弱清单 `tests` 字段如实列出覆盖测试文件（含 intree 路径）。
2. `totals.tests` 直接取 raw `n_tests`（已含 intree），`intree_tests` 单列保留；`intree_test_modules` 清单保留不变（25 项）。

## 2. 同基线 commit 前后对比（6cf793bd8，仅测试宇宙不同）

| 指标 | 修复前（同 commit 复跑旧版） | 修复后 | 变化 |
|---|---|---|---|
| 测试宇宙 | 803（根）+ 25（aggregate 事后补） | 828 = 803 + 25（扫描器内同源） | 同源化 |
| zero_noninit | 93 | 93 | 不变（旧版 zero 判定已按 intree 导入修正，无零覆盖误报可清） |
| weak_single_test（全量） | 240 | **236** | -4 |
| weak_top100 中 `tests: []` 条目 | **3** | **0** | 误报"无测试"全部清除 |
| zero_top200 集合 | 93 项 | 93 项 | 完全一致（真实缺口一个没少） |

### 误报清除明细

卡片点名 3 个"误报无测试"模块，weak 条目 `tests` 字段由 `[]` 修正为真实覆盖测试（与 learning-intree-20261009 映射复核逐条一致）：

| 模块 | 修复后覆盖测试 |
|---|---|
| `deeptutor/learning/assessment.py` | `deeptutor/learning/tests/test_assessment.py` |
| `deeptutor/tools/mastery_nav.py` | `deeptutor/learning/tests/test_mastery_navigation.py` |
| `deeptutor/learning/pending.py` | `deeptutor/learning/tests/test_mastery_choices.py` |

另有 4 个假弱模块因 intree T1 词干匹配计入后 `n_cover` 由 1→2，退出弱清单：`knowledge.naming`、`services.memory.consolidator.modes.merge`、`services.web_source.navigation`、`services.workspace.navigation`（各由 1 个 intree + 1 个根测试共同覆盖）。合计弱清单误报修正 **7** 个（3 个"无测试"误报 + 4 个假弱）。

### 真实缺口（不受影响的存量 + 窗口上浮）

- zero_top200 集合前后完全一致（93 项，如 `services.session.turns.executor`、`partners.channels.mochat` 等），无新增、无误删——零覆盖清单本身就是真实缺口。
- weak_top100 窗口：假弱条目清除后，`services.office_preview`（198 LOC，fanin 1，此前被挤出前 100）上浮进入窗口；真实弱清单头部为 `services.config.readiness`（1038 LOC）、`services.llm.provider_core.codebuddy_provider`（851）、`partners.channels.msteams`（847）等，供后续拆补测卡。

## 3. 验收核对

1. ✅ intree 24 文件全部进入测试宇宙（`raw.n_intree_tests=25`，其中 learning 24；`intree_test_files` 逐一在列）
2. ✅ 分支 tip 上复跑输出字节级一致：scan+aggregate 复跑两次（第二次含 `PYTHONHASHSEED=random`），`coverage_raw.json`/`summary.json` SHA256 前后一致（`shasum -a 256 -c` 全 OK）；溯源字段 `deeptutor_tree` 与基线产品树一致，复跑不随 HEAD 漂移
3. ✅ `git status` 仅新增本 evidence 目录，未改任何产品/测试代码

## 4. 复现命令（仓库根，仅标准库）

```bash
python3 evidence/coverage-gaps-intree-20261009/scan_coverage_gaps.py   # 生成 coverage_raw.json
python3 evidence/coverage-gaps-intree-20261009/aggregate.py            # 生成 summary.json
shasum -a 256 -c evidence/coverage-gaps-intree-20261009/SHA256SUMS     # 校验
```

## 5. 证据文件

- `scan_coverage_gaps.py` / `aggregate.py` —— 改后扫描器与聚合器
- `coverage_raw.json` —— 修正版逐模块 T1/T2/covered（含 intree 宇宙与 `n_intree_tests`/`intree_test_files`，溯源字段 `deeptutor_tree`）
- `summary.json` —— 修正版 zero/weak 清单（weak 条目 `tests` 如实列出 intree 路径）
- `SHA256SUMS` —— 本目录（除自身）SHA256
