# 三态判定标准与方法

## 扫描对象

pytest `testpaths`（`pyproject.toml [tool.pytest.ini_options]`）下全部 `test_*.py`：
`tests/**/*.py`（756）与 `deeptutor/learning/tests/*.py`（24），合计 780 个文件。
`*_test.py` 命名在仓库中不存在（`find` 验证为 0）。

## 三态定义

| 判定 | 条件（对每个文件） | 建议处置 |
|---|---|---|
| 仍有效 valid | 所有 deeptutor 本地 import（含相对 import）在 HEAD 树可解析（模块存在且 `from M import n` 的 n 可在 M 顶层定义/再导出/子模块定位）；且无激活的长期 skip 信号 | 无 |
| 目标漂移 drift | 文件可正常收集（import 全部解析），但存在激活的孤儿信号：a) `importorskip` 的目标是**不存在**的本地模块（模块被删后整文件静默跳过）；b) statically-true 的 `skipif`/`pytestmark skip`；c) 无条件 skip 装饰器/模块级 skip 且原因指向已变更目标；d) `patch("…")`/`monkeypatch.setattr("…")` 字符串目标解析失败（运行期才报错） | 改指向新符号或解除守卫 |
| 建议删除或改名 broken | 收集期即失败：至少一条本地 import 的目标模块或符号在 HEAD 不存在（且未被 conftest/本文件 `sys.modules` 桩注入覆盖）或文件有语法错误 | 符号已迁址→改 import 路径；无迁址→删除文件 |

判定优先级：broken > drift > valid。

## 解析规则要点

- 模块存在 = `<pkg>/<name>.py`、`<pkg>/<name>/__init__.py` 或 PEP 420 命名空间目录（含至少一个直系 `.py`，仓库中 `deeptutor/utils/`、`deeptutor/api/utils/`、`deeptutor/utils/network/` 属此类）。
- 符号解析 = 被导入模块顶层 def/class/赋值/import 别名/条件块内定义/`__getattr__` 模块级兜底，或对包而言的子模块名。
- `sys.modules` 桩注入（本文件或任一 `tests/**/conftest.py`）可豁免对应失效判定（当前树中无任何桩注入，`grep sys.modules` 验证）。
- patch 目标解析 = 取最长可解析模块前缀，余段 head 须为该模块顶层名或（包时）子模块，或原文含该词（覆盖类方法/嵌套定义）。`patch.object(对象引用, …)` 与 `patch.dict` 无法静态解析，不在判定范围。
- skip 静态性：条件为字面 `True`/`1`/`not False` 记 statically-true；`os.name`/`sys.platform`/`find_spec`/`getenv`/`is None`/`hasattr` 记环境条件（非孤儿）。

## 交叉验证方法（与静态扫描独立）

1. `python3 -m pytest --collect-only -q --continue-on-collection-errors -p no:cacheprovider`：
   收集错误中 `No module named 'deeptutor…'` 计数为 0（481 个错误均为裸环境缺第三方包，与目标失效无关，缺包分布：httpx 262 / fastapi 105 / pydantic_settings 21 / defusedxml 21 / loguru 13 …）。
2. patch 目标独立复核：正则抽取 `(?:patch|setattr)\(\s*["'](deeptutor|tests)\.…` 全树字符串目标（268 个唯一值），逐一重放解析，0 失败。
3. skip 清单独立复核：`grep -rn 'importorskip|mark.skipif|mark.skip(' tests/ deeptutor/learning/tests/` 与 `signals.tsv` 行数一致（152 / 26 / 0）。

## 复算命令

```bash
# 静态扫描（仅标准库，Python 3.10+）
python3 evidence/orphan-tests-20261010/scan_orphan_tests.py <repo-root> /tmp/out.json
# 输出 {"total": 780, "valid": 780, "drift": 0, "broken": 0}

# 运行时交叉验证
python3 -m pytest --collect-only -q --continue-on-collection-errors -p no:cacheprovider 2>&1 \
  | grep -c "No module named 'deeptutor"   # 期望 0
```

git 侧佐证：历史上有 47 个测试 .py 路径被删除（最近一次 `8986c3158` 2026-10-08 删除 `tests/video_learning/test_capability.py`）；现存 780 个测试文件对已删路径的引用为 0（本卡 import 全量解析为 0 失效，含 `tests.*` 交叉导入 21 条语句 / 29 个符号）。所有判定均给出 import 路径级依据（`files.csv` / `signals.tsv`）。
