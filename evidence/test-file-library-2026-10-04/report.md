# DT-22 · file_library `_delete_file` 失败路径回归测试

- **基线**: HKUDS/DeepTutor `origin/main` @ `ef2d9e5c3c99fd073742c5aadc2bb9584b1e503b`（v1.6.12；与 `origin/dev` 同点）
- **日期**: 2026-10-04（UTC）
- **分支**: `agent/dt22-file-library-deletion-tests`（推送至 `myfork`）
- **对象**: `deeptutor/services/storage/file_library.py:205` `_delete_file` 父目录遍历循环的宽 `except Exception: pass`（DT-22 HIGH，见 `agent/dt22-todo-scan` evidence §7）
- **改动范围**: 仅新增 `tests/services/storage/test_file_library_deletion.py`（6 个用例）；**未修改任何产品代码**（`git diff origin/main` 为空）

## 1. 结论（PASS）

新增 6 个用例全部通过；模块行覆盖率 84% → 87%，DT-22 指向的 203-206 行（父目录清理循环 + 吞异常）及 196-197 行（unlink 失败告警）由未覆盖转为覆盖。

## 2. 覆盖的三类失败分支（验收项 1）

| 分支 | 用例 | 锁定的现状 |
| --- | --- | --- |
| 删除成功 | `test_delete_file_removes_target_and_empty_parent_dirs`、`test_delete_file_keeps_nonempty_parent_dirs` | 文件删除成功；空父目录逐级清理至 root 为止（root 保留）；仍有其他文件的父目录不清理 |
| 目标缺失 | `test_delete_file_missing_target_is_silent_noop`、`test_hard_delete_succeeds_when_disk_file_already_missing` | 磁盘文件不存在时为静默 no-op，不报错、不落盘；硬删除流程在磁盘文件已丢失时仍完成 DB 行清理（列表与磁盘一致的前提路径） |
| 父目录遍历异常 | `test_delete_file_parent_traversal_exception_is_swallowed` | 遍历清理父目录时抛异常被 `except Exception: pass` 吞掉：文件本身仍被删除，剩余清理中途终止（空目录残留），调用方无感知（DT-22 HIGH 现状锁定） |
| （附加）unlink 失败 | `test_delete_file_unlink_failure_only_logs_warning` | `unlink` 抛 OSError 仅记 warning：文件留在磁盘、DB 行仍可被硬删除——即 DT-22 所述"列表与磁盘可能不一致"窗口的现状固化 |

父目录遍历异常与 unlink 失败通过 `monkeypatch` 定向注入 `pathlib.Path.iterdir` / `Path.unlink`（仅对测试内路径生效），不依赖 chmod，跨平台确定性。

## 3. 测试命令与数字（验收项 2）

环境：`/Users/Shared/DeepTutor/.venv`（Python 3.13.13，pytest 9.1.1，pytest-cov 7.1.0），工作目录为 worktree `dt-agen432-wt`。

```
.venv/bin/python -m pytest tests/services/storage/ \
  --cov=deeptutor.services.storage.file_library --cov-report=term-missing -q
```

| 运行 | 用例 | 结果 | file_library.py 覆盖 | 未覆盖行 |
| --- | --- | --- | --- | --- |
| 前（仅存量 tests/services/storage/test_file_library.py） | 26 | 全部通过 | 84%（Miss 32） | 62-66, 70-75, 153-154, 186-189, **196-197, 203-206**, 266-278, 359, 398, 426 |
| 后（存量 + 新增 test_file_library_deletion.py） | 32 | 全部通过 | 87%（Miss 26） | 62-66, 70-75, 153-154, 186-189, 266-278, 359, 398, 426 |

仅新增文件运行：`pytest tests/services/storage/test_file_library_deletion.py -v` → 6 passed。

仍未覆盖的行（本次不涉及，属迁移/写入竞态/搜索空查询等路径）：`_current_schema_version` 异常兜底、`_run_migrations`、重复活跃行导致建索引失败的 warning、`_write_file` 临时文件清理兜底、`IntegrityError` 竞态回收、`_restore_file_sync` 无行返回、`_search_files_sync` 空查询、`resolve_path` 文件缺失返回 None。

## 4. 验收项 3 — 产品代码零改动

- `git diff origin/main --stat` 为空；`git status` 仅新增 `tests/services/storage/test_file_library_deletion.py` 与本证据目录。
- 主仓库 `/Users/Shared/DeepTutor` 的 main 工作区未 checkout/reset/clean，未触碰其未提交内容。

## 5. PR 草稿（供人决定是否向上游提交；本卡不开 PR）

- **标题**: `test(storage): lock FileLibraryStore disk-deletion failure paths`
- **目标分支**: `dev`（按 CONTRIBUTING；`origin/main` 与 `origin/dev` 当前同点，无冲突）
- **描述要点**:
  - 背景：DT-22 静默异常扫描（HIGH：`deeptutor/services/storage/file_library.py:205` `_delete_file` 父目录清理循环 `except Exception: pass`）。
  - 内容：新增 `tests/services/storage/test_file_library_deletion.py`，6 个用例锁定删除成功/目标缺失/父目录遍历异常（附 unlink 失败仅告警、磁盘文件已丢失时硬删除仍完成）的现状；模块覆盖率 84%→87%。
  - 明确不含产品代码改动；如后续要改为"上报/重试"删除错误，需同步更新这批锁定测试。

## 6. 附件校验

见同目录 `SHA256SUMS`。
