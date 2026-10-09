# scan: deeptutor/learning intree 测试收集面核查（AGEN-1182）

- 日期：2026-10-09
- 基线：origin/main @ 6cf793bd8（release: v1.6.14），独立 worktree，只读核查，未改任何代码
- 环境：/Users/Shared/DeepTutor/.venv（Python 3.13.13，pytest 9.1.1，pytest-asyncio 1.4.0）；已在 00 号证据确认 `import deeptutor` 解析到本 worktree，非主 checkout
- 对象：`deeptutor/learning/tests/` 共 24 个 test_*.py（intree 测试）

## 结论：已收集（收集面无缺口）

根 pytest 配置与 CI 都会真实收集并运行这 24 个文件；coverage-gaps 报告把它们计为零覆盖的根因不在 pytest/CI 收集面，而在 coverage-gaps 扫描器自身的测试宇宙只含根 `tests/`（见下）。

## 配置面（静态证据）

1. `pyproject.toml:480` `[tool.pytest.ini_options]` → `testpaths = ["tests", "deeptutor/learning/tests"]`；`pythonpath = ["."]`，`--import-mode=importlib`
2. `.github/workflows/tests.yml:286`（python-tests job）→ `pytest -q tests deeptutor/learning/tests`，并设 `PYTHONPATH: ${{ github.workspace }}`
3. 无根级 pytest.ini/setup.cfg/tox.ini；`tests/conftest.py` 存在，`deeptutor/learning/tests/` 下无 conftest（不构成收集障碍）
4. 该两处自 2026-06-11（da1061910 / 46093e5e2）即已包含 learning intree 路径，非近期新增

## 实测收集（pytest --collect-only，全部入档）

| # | 命令 | 结果 |
|---|------|------|
| 01 | `pytest --collect-only -q`（无参数 → testpaths） | 10205 collected；其中 `deeptutor/learning/tests/` 638 条、`tests/` 9567 条；0 收集错误 |
| 02 | `pytest --collect-only -q deeptutor/learning/tests` | 638 collected |
| 03 | `pytest -q --collect-only tests deeptutor/learning/tests`（CI 等价参数） | 10205 collected；其中 learning 638 条 |
| 04 | 02 的收集清单按文件去重 vs 磁盘 | 24/24 文件全部进入收集清单，集合完全一致 |

## 实测运行（PASS/FAIL）

| # | 命令 | 结果 |
|---|------|------|
| 05 | `pytest -q deeptutor/learning/tests` | **638 passed, 0 failed**（5 warnings，5.30s，exit 0） |

（以上命令均以 900s 时限包装执行，实际远未触顶；未启动任何服务。）

## coverage-gaps 零覆盖的根因（本卡查明的机制）

`evidence/coverage-gaps-20261007/scan_coverage_gaps.py`（AGEN-662/873 系列）：

- 第 24 行 `TESTS = os.path.join(ROOT, "tests")`、第 78 行 `tests = [p for p in py_files(TESTS)]` —— T1（文件名对应）/ T2（AST 导入对应）映射的测试宇宙只有根 `tests/`，`deeptutor/**/tests/` 的 intree 测试文件完全不在其中。
- `aggregate.py` 已在 `totals` 里单列 `intree_tests: 24` 并输出 `intree_test_modules` 清单，但模块级 `tests` 字段与 `zero_top200` / `weak_top100` 判定未把 intree 测试算进去。

实测影响（用与扫描器相同的 T2 精确点号匹配，把 24 个 intree 文件补进映射后）：

| 被误报模块 | 报告位置 | 扫描器 tests | intree 实际覆盖 |
|---|---|---|---|
| `deeptutor/learning/assessment.py`（557 LOC, fanin 6） | weak_top100 `"tests": []` | 0 | `test_assessment.py` |
| `deeptutor/tools/mastery_nav.py`（500 LOC, fanin 2） | weak_top100 `"tests": []` | 0 | `test_mastery_navigation.py` |
| `deeptutor/learning/pending.py`（283 LOC, fanin 8） | weak_top100 `"tests": []` | 0 | `test_mastery_choices.py` |

`deeptutor/learning/question_card.py`（zero_top200）intree importers 为空，属真实缺口，不受本机制影响。

## 最小修复建议（不改代码，供后续卡参考）

1. 在 `scan_coverage_gaps.py` 把 intree 测试并入测试宇宙：收集根 `tests/` 之外，再按 `deeptutor/*/tests/test_*.py`（含嵌套，`deeptutor/**/tests/test_*.py`）追加到 `tests` 列表；`n_tests` 与 `totals.intree_tests` 保持同源。
2. learning intree 测试经实测 100% 使用绝对 `deeptutor.*` 导入（0 个相对导入，见 06 号证据），T2 精确点号匹配逻辑无需任何改动，仅需扩列表即生效；`test_imports` 的相对导入分支可暂不为 intree 扩展，但需注意 intree 文件若日后使用相对导入，现有 `os.path.relpath(dirname, TESTS)` 解析会得出错误包名，届时再按各自包根解析。
3. `aggregate.py` 的 zero/weak 判定改为消费扩展后的 `covered` 字段即可，单列的 `intree_test_modules` 保留不变。

## 去重说明

不覆盖 guide-ci-workflows / guide-testing 范围；与 scan-pytest-markers、scan-test-isolation、scan-conftest-dup、scan-test-runtime 无重叠（本卡只回答"收集与运行是否发生"及零覆盖根因归属）。

## 证据文件

- 00-import-resolution.txt —— import deeptutor 解析到本 worktree 的确认
- 01-collect-default-testpaths.txt —— 默认收集全量输出（10205）
- 02-collect-learning-explicit.txt —— 显式 learning 目录收集（638）
- 03-collect-ci-args.txt —— CI 等价参数收集（10205/638）
- 04-collected-files.txt —— 收集清单文件去重（24）
- 05-run-learning.txt —— 实跑 638 passed / 0 failed
- 06-intree-imports.txt —— intree 测试导入风格统计（绝对导入，0 相对导入）
- 07-covgap-mapping-check.txt —— coverage-gaps 映射缺口复核输出（3 个误报模块）
