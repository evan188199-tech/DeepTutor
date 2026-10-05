# test-config-manager-20261005 摘要

任务：为 `deeptutor/utils/config_manager.py` 补测试（AGEN-639 储备卡）。

## 结论

PASS — 聚焦 pytest 全部通过，未改动任何产品代码（仅新增测试）。

- 分支：`test/config-manager-atomic-20261005`（基于 `origin/main` @ `f07029cfc`，即 release: v1.6.13）
- 测试命令（在 worktree 根目录执行）：

```
python -m pytest -q -p no:cacheprovider tests/core/test_config_manager.py
```

- 环境：macOS (darwin)，Python 3.13.13（仓库自带 `.venv`），pytest 9.1.1，PyYAML 6.0.3
- 结果：**9 passed**（原 2 项 + 新增 7 项），耗时约 0.24s，未超时（命令以 900s 硬时限包裹执行）

## 新增覆盖

1. `test_save_config_success_leaves_no_tmp_residue` — 成功保存后设置目录内无 `main.yaml.*` 临时残留（mkstemp 前缀文件被清理）。
2. `test_save_config_replace_failure_keeps_previous_file` — `os.replace` 失败时旧配置文件保持不变（原子性），临时文件仍被清理、无残留。
3. `test_save_config_tmp_remove_failure_swallowed_leaves_residue` — 显式断言 DT-22 MEDIUM（config_manager.py:96）：当 `os.remove` 本身抛 OSError 时，`except OSError: pass` 吞掉清理失败，暂存临时文件会残留在设置目录中；旧配置不受影响。测试结束时清理了该残留。
4. `test_load_config_corrupted_file_raises_and_recovers` — 损坏的 YAML 内容使 `load_config` 抛出 `yaml.YAMLError`（当前行为为显式报错、无静默兜底），恢复合法内容后可正常加载。
5. `test_load_config_empty_file_falls_back_to_empty_dict` — 空文件经 `or {}` 兜底返回空字典。
6. `test_concurrent_saves_merge_without_overwriting_each_other` — 8 线程经 Barrier 同时各自保存独立键，锁内读-合并-写保证最终文件包含全部 8 个键且磁盘内容与重载一致、无残留（无丢失更新）。
7. `test_default_values_merge_across_partial_saves` — 默认值合并：两次部分保存分别替换嵌套键与新增键，兄弟键保留。

## 去重说明

- 上游开放 PR 中无任何涉及 `tests/core/test_config_manager.py` 或 `deeptutor/utils/config_manager.py` 的 PR。
- 与开放 PR `myfork/fix/atomic-write-fsync-warning`（仅触及 `deeptutor/services/file_io.py`、`tests/services/test_file_io.py`）不重叠。
- 原有 `tests/core/test_config_manager.py` 未覆盖残留清理、损坏读、并发写与默认值合并；本次为增量补充，未修改已有用例。

## 变更文件

- `tests/core/test_config_manager.py`（+146 行，仅新增测试与辅助函数，含 ruff check / format 通过）

## SHA256SUMS

见同目录 `SHA256SUMS`。
