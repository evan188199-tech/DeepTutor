# test: LightRAG 索引缓存继承版本解析补测（AGEN-638）

## 结论

PASS — 聚焦 pytest 8 passed（4 既有 + 4 新增），未改产品代码。

## 范围

为 `deeptutor/services/rag/pipelines/lightrag/cache_reuse.py` 的
`inherit_index_cache` 补充三类此前未覆盖的场景（对应 DT-22 报告 §7
MEDIUM :100 的版本目录名解析缺口）：

1. 脏 `version-*` 目录名（`version-junk`、`version-`、`version-2-beta`）
   解析失败时被 `continue` 跳过：不崩溃、不参与继承，有效旧版本仍正常继承。
2. 多版本目录：同内容键时最新合格捐赠版本胜出；版本号 ≥ 目标版本的
   目录（`version-4` vs 目标 `version-3`）被忽略。
3. 无旧版本/目标目录缺失：无可继承捐赠时返回 False 且不写目标缓存；
   目标根目录缺失且无捐赠时为 no-op，不创建任何目录。

## 变更

- `tests/services/rag/test_lightrag_cache_reuse.py`（+63 行，仅测试）
  - `test_dirty_version_directory_names_are_skipped`
  - `test_newest_eligible_donor_wins_and_newer_versions_are_ignored`
  - `test_donor_versions_without_usable_cache_leave_target_untouched`
  - `test_missing_target_root_without_donors_is_a_noop`

## 去重核对

- 上游开放 PR（HKUDS/DeepTutor，2026-10-05 查询）无 cache_reuse /
  inherit_index_cache 相关改动，无撞车。
- `inherit_index_cache` 仅由 `tests/services/rag/test_lightrag_cache_reuse.py`
  覆盖；`test_lightrag_worker.py` 与 rag-degrade 相关测试不涉及版本目录
  解析，无重复。

## 验证

环境：macOS，Python 3.13.13（/Users/Shared/DeepTutor/.venv），
worktree 基于 origin/main f07029cfc（release: v1.6.13）。

```text
python -m pytest -q -p no:cacheprovider tests/services/rag/test_lightrag_cache_reuse.py
# 8 passed in 0.27s
python -m pytest -q -p no:cacheprovider \
  tests/services/rag/test_lightrag_cache_reuse.py \
  tests/services/rag/test_lightrag_worker.py \
  tests/services/rag/test_index_versioning.py
# 20 passed in 0.33s
ruff check / ruff format --check：通过
scripts/check_repo_hygiene.py：通过
```

测试命令均带 900s 时限。完整输出见 `pytest.log`。
