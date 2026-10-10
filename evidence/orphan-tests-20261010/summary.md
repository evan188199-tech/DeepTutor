# 孤儿测试三态清点（有效 / 目标漂移 / 建议删除或改名）

- 基线：`origin/main` @ `6cf793bd868ba5ecbe64722936d4be8fab5a01df`（v1.6.14, 2026-10-08）
- 扫描分支：`scan/orphan-tests-20261010`（新 worktree，未触碰主 checkout）
- 扫描范围：pytest `testpaths` 全集 = `tests/`（756 个 test 文件）+ `deeptutor/learning/tests/`（24 个）= **780 个测试文件**
- 只读扫描：未修改任何产品/测试代码，本分支仅新增 `evidence/` 下 6 个文件

## 结论：三态计数

| 判定 | 文件数 | 说明 |
|---|---|---|
| 仍有效 | **780** | 全部本地 import 可解析、无激活的长期 skip |
| 目标漂移 | **0** | 无「文件可收集但用例级目标已失效」情形 |
| 建议删除或改名 | **0** | 无收集期 import 失效文件 |

**origin/main 在孤儿测试轴上健康：没有需要删除或改名的孤儿测试。**

## 覆盖度与依据（均可复算）

1. **import 轴（文件级，收集期失效）**：780 个文件共 3,732 条 deeptutor 本地 import 语句（163 条 `import deeptutor.*` + 3,569 条 `from deeptutor.* import …`），逐条对照 HEAD 文件树解析；5,424 个 `from … import <符号>` 符号逐一在被导入模块的顶层定义/再导出/子模块中定位，**0 条失效**。另覆盖测试树内部交叉导入 `from tests.… import …`：21 条语句 / 29 个符号，全部可解析。解析器已支持 PEP 420 命名空间包（`deeptutor/utils/`、`deeptutor/api/utils/`、`deeptutor/utils/network/` 无 `__init__.py`，import 合法）。
2. **用例级 patch 目标轴**：`patch("deeptutor.…")` / `monkeypatch.setattr("…")` 字符串目标经 AST 扫描，并用独立正则抽取交叉复核（268 个唯一目标），**全部可解析**，无指向已删除/改名符号的失效 patch。
3. **长期 skip 轴**（详见 `signals.tsv`，152+26 行全量清单）：
   - `importorskip` 152 处：仅 3 处针对本地模块（`tests/api/test_notebook_api_contract.py:20`、`tests/book/test_cross_module_call_contracts.py:76,85`），目标模块均存在 = 休眠守卫，非激活孤儿；其余 149 处为第三方可选依赖（pymupdf、bcrypt、fastapi 等）。
   - `skipif` 26 处：全部为环境条件（`os.name`/`sys.platform` 平台守卫、`find_spec("lightrag")` 可选 SDK、`getenv` 显式 opt-in、`FastAPI is None` 轻量环境回退），**无 statically-true 条件、无 legacy/removed 类原因**。
   - 无条件 `@pytest.mark.skip`：0；模块级 `pytest.skip(allow_module_level=True)`：0；`unittest.skip`：0。
4. **交叉验证（运行时独立复核）**：对全树执行 `python3 -m pytest --collect-only -q --continue-on-collection-errors -p no:cacheprovider`（裸解释器，无第三方依赖）：收集 2,861 用例 / 481 个模块收集错误，错误**全部**为第三方包缺失（httpx 262、fastapi 105、pydantic_settings 21…），`No module named 'deeptutor…'` 出现 **0 次** —— 与静态结论一致：不存在本地目标失效。

## 判定标准

见 `criteria.md`；复算命令：`python3 scan_orphan_tests.py <repo-root> out.json`（需 Python 3.10+，仅标准库）。

## 去重声明

本卡只覆盖孤儿测试轴（目标模块删除/改名/合并导致的 import 失效、长期 skip、patch 目标失效）。不覆盖：src 侧死代码（scan-dead-code 轴）、测试隔离/运行时/pytest markers（scan-test-isolation / scan-test-runtime / scan-pytest-markers 轴）。

## 边界观察（非本轴，仅记录不处理）

- `deeptutor/services/config/test_runner.py` 是产品代码（config 服务运行时模块），命名易与测试混淆；位于 `testpaths` 之外不会被 pytest 收集，无实际影响。
- `tests/book/test_cross_module_call_contracts.py` 等 3 处本地 `importorskip` 是「模块被删即静默跳过」的模式，当前休眠；若未来模块删除，会转化为隐性孤儿，建议后续 axis 关注。

git 侧佐证：历史上共删除过 47 个测试 .py 路径（最近 `8986c3158` 2026-10-08 删除 `tests/video_learning/test_capability.py`），现存测试对任一已删路径的引用为 0（全量 import 解析 0 失效，含 `tests.*` 交叉导入）。

## 交付物清单

| 文件 | 内容 |
|---|---|
| `summary.md` | 本摘要 |
| `criteria.md` | 三态判定标准与方法 |
| `files.csv` | 780 行逐文件判定（file, verdict, broken_cases, drift_signals, notes） |
| `signals.tsv` | 全量 skip / 本地 importorskip 清单（178 行，orphan_relevant 全部为 no） |
| `scan_orphan_tests.py` | 扫描脚本（标准库实现，可复算） |
| `SHA256SUMS` | 以上文件的 SHA-256 校验 |
