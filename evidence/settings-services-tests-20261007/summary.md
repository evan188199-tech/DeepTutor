# settings-services-tests-20261007 摘要

任务：为 `deeptutor/services/settings/`（6 文件）补单元测试：设置读写往返、草稿合并、并发写保护（AGEN-1041 储备卡，真空 #14）。

## 结论

PASS — 聚焦 pytest 全部通过，未改动任何产品代码（仅新增测试文件）。

- 分支：`test/settings-services-20261007`（基于 `origin/main` @ `f07029cfc`，即 release: v1.6.13）
- 测试命令（在 worktree 根目录执行，以 900s 硬时限包裹）：

```
python -m pytest -q -p no:cacheprovider \
  tests/services/test_interface_settings_store.py \
  tests/services/test_settings_edit_merge.py
```

- 环境：macOS (darwin)，Python 3.13.13（仓库共享 `.venv`），pytest 9.1.1
- 结果：**30 passed**，约 0.5s（30 = 新增 18 + 新增 12，见下），未超时
- 回归验证：连同相邻既有套件（starter_settings、provider_edit、provider_registry_workflow、ui_language_scoping、settings_router、setup_capability）一起跑：**197 passed**，约 2.4s
- ruff check / ruff format --check 均通过

## 新增文件与场景

### `tests/services/test_interface_settings_store.py`（18 项）

覆盖 `interface_settings.py`：

1. 读写往返：无文件时返回默认；`set_ui_setting` → `get_ui_settings` 往返一致；`update_ui_settings` 合并保留兄弟键；`replace_ui_settings` 整体重置旧字段。
2. 裸存储合并语义：更新只写进"裸存储"映射，不把当日默认值物化成用户显式选择（写回 defaults 视图会冻结默认值的文档不变量）。
3. 损坏/非 dict 文件读取回退默认（`get_ui_settings` 永不抛）。
4. `resolve_languages`：遗留文件只有 `language` 时 `response_language` 继承；未知/空白回退。
5. `sanitize_enabled_tools`：非 list 返回全部可切换工具；去重、丢弃未知名与非字符串、保持顺序。
6. `atomic_update`：损坏/非 dict 文件被替换；自动建缺失父目录；返回值与磁盘一致；`mutate` 抛异常时旧文件原样保留且无临时残留；成功写无 `.interface.json.*.tmp` 残留且带尾换行；`_settings_lock` 同路径同锁、异路径异锁。
7. 并发写保护：12 线程 × 25 次经 `update_ui_settings`/`atomic_update` 并发写同一文件，全部 12 个键落盘、值无丢失更新、全程合法 JSON、无临时残留。

### `tests/services/test_settings_edit_merge.py`（12 项）

覆盖 `provider_edit.py` 与 `registry_edit.py`（草稿合并的校验分支）：

1. `merge_provider_edit`：profile ID 必填（空/None/非字符串均拒）；新 profile 追加且不动激活位；激活必须指向真实存在的 model（缺失或无 `model` 字段均拒）；激活写入 active IDs，task 服务激活同时置 `mode="profiles"`。
2. `merge_registry_edit`：provider 改名为空白必拒；`managed_by` 连接不可从注册表删除（指引去认证设置），且失败不改动 catalog；未知 kind 拒绝；首次编辑 `connection_id` 自动创建命名连接、再次编辑原位更新；`kind=default` 提升激活 profile/model；search 模型删除时带 `provider_ref` 的 profile 整体移除、无 `provider_ref` 的翻成 `provider_only`；LLM 模型删除后 `_select_remaining` 回落到剩余候选（空壳自由 profile 保留但不参与激活）。

## 去重说明

- 开工前已查上游：`gh pr list -R HKUDS/DeepTutor --state open` 中无任何触及 settings 的 PR；`--author @me` 开放 PR 4 个分支均与 settings 无关，未复用其分支名。
- 已有测试不重复：`tests/services/test_starter_settings.py`（starter 往返/钳制）、`tests/api/test_settings_router.py`（router 层 UI 持久化、router+capability 12 线程并发）、`tests/services/test_provider_edit.py`（provider 编辑含 stored_draft 草稿密钥恢复）、`tests/services/test_provider_registry_workflow.py`（registry 工作流多数校验分支）、`tests/multi_user/test_ui_language_scoping.py`（按用户作用域）。本次为增量补充：`atomic_update` 原语级原子性/锁语义/并发、裸存储合并不变量、以及 provider/registry 编辑未覆盖的校验分支。

## 变更文件

- `tests/services/test_interface_settings_store.py`（新增，仅测试）
- `tests/services/test_settings_edit_merge.py`（新增，仅测试）
- 产品代码零改动（`git status` 仅含上述两个新文件与本 evidence 目录）

## SHA256SUMS

见同目录 `SHA256SUMS`。
