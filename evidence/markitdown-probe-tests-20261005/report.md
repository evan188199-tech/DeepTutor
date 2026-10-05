# markitdown 支持格式探测回归测试（AGEN-596）

日期：2026-10-05
基线：origin/main @ f07029cfc（release v1.6.13）
分支：`test/markitdown-formats-probe-20261005`

## 背景

来源：`agent/dt22-todo-scan` 分支 `evidence/todo-scan-2026-10-03/report.md` §7 附录 A 两条 MEDIUM 记录：

- `deeptutor/services/parsing/engines/markitdown/formats.py:76` — 逐个导入 converter 模块时 `except Exception: continue`
- `deeptutor/services/parsing/engines/markitdown/formats.py:82` — 导入 `markitdown.converters` 包本身时 `except Exception: pass`

两处吞掉导入探测失败后，`markitdown_supported_formats()` 仍无条件返回 `MARKITDOWN_0_1_7_FORMATS | discovered`：
包缺失时照样宣称 28 个内置格式全部可解析；单个 converter 模块损坏（如缺可选依赖）时静默跳过，坏安装对外不可见。
该返回值经 `MarkItDownParser.supported_formats()`（engine.py:36）和 `known_parser_formats()`（engines/formats.py:21）
进入上传路由，失真列表会把文件路由给实际必然失败的引擎。

## 锁定的探测契约（测试先行，当前失败）

1. **未探测成功不宣称格式**：`markitdown.converters` 不可导入时返回空 frozenset，而不是 0.1.7 floor。
2. **损坏的 converter 模块可观测**：新增 `markitdown_probe_failures() -> tuple[str, ...]`，
   部分导入失败后记录失败模块名，干净探测后为空；工作模块贡献的扩展与 floor 保留。
3. **完整安装正向对照**：所有 converter 可导入时，发现的扩展并入 floor（含无点号/混合大小写归一化）。

## 交付物

- `tests/services/parsing/test_markitdown_formats.py`（6 个用例，见下）
- 本说明

夹具要点：`markitdown_supported_formats` 是 `lru_cache(maxsize=1)`，autouse 夹具在每个用例前后 `cache_clear()`；
fake 包用真实磁盘文件构建（`tmp_path` 下 `markitdown/converters/*.py`，`syspath_prepend` + sys.modules 清理），
probe 的 `pkgutil.iter_modules` 与子模块导入走真实导入机制；「包缺失」形态用委托式 `import_module` 替身精确拦截
`markitdown*` 名称，其余导入不受影响。

## 测试结果

命令（仓库根，限时）：

```
perl -e 'alarm 900; exec @ARGV' .venv/bin/python -m pytest -q -p no:cacheprovider tests/services/parsing/test_markitdown_formats.py
```

- `test_missing_converters_package_advertises_no_formats` — **FAIL（预期）**：现返回 28 个 floor 格式而非空集
- `test_broken_converter_module_is_recorded_not_swallowed` — **FAIL（预期）**：`markitdown_probe_failures` 不存在（ImportError）
- `test_probe_failures_reset_after_clean_probe` — **FAIL（预期）**：同上
- `test_full_install_discovers_converter_extensions` — PASS（正向对照）
- `test_normalize_extensions_rejects_non_collection_values` — PASS
- `tests/services/parsing/` 全目录：**3 failed（均为上述预期失败）+ 139 passed + 2 skipped**，既有用例零回归
- ruff check / ruff format：通过

## 给修复卡的线索

1. 实现契约 2 需在 `formats.py` 增加模块级可变记录 + `markitdown_probe_failures()` 导出（加入 `__all__`）；
   probe 入口处先清空记录，inner `except` 写入 `module_info.name`。
2. 契约 1 把「包不可导入」改为提前返回 `frozenset()`；lru_cache 行为不变（`_install.py:106-111` 安装后 `cache_clear()` 钩子已存在，无需改）。
3. 注意：契约 1 落地后，`tests/services/parsing/test_engines.py:151` 的
   `MARKITDOWN_0_1_7_FORMATS <= markitdown_supported_formats()` 在未安装 markitdown 的环境下会反转语义
   （floor ⊄ 空集）；本机 venv 已装 markitdown 0.1.4 不受影响，CI 需确认 parse extras 已安装。
4. 夹具可直接复用：fake 包构建与 import_module 拦截都在测试文件内，修复卡无需新增 fixture。
