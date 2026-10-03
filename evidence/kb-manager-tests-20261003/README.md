# KB manager CRUD 边界补测证据（AGEN-144）

基线：`origin/main` @ `ef2d9e5c3`（release: v1.6.12），对齐
`audit/coverage-gaps-20261003` 分支 `evidence/coverage-2026-10-02/top15-gaps.md` 缺口 8
（`deeptutor/knowledge/manager.py`：329 缺失 / 73.7%）。

## 产物

- `tests/knowledge/test_manager_crud_edges.py` — 15 个用例，仅测 manager 层（路由层不在本卡范围）。
- 无任何产品代码改动（`git diff ef2d9e5c3 --stat` 仅新增测试与证据文件）。

## 运行命令与结果

```bash
# 仓库 worktree 根目录，Python 3.13 venv
python -m pytest tests/knowledge/test_manager_crud_edges.py -v
# → 13 passed, 2 failed（失败即修复卡契约，见下）

python -m pytest tests/knowledge --ignore=tests/knowledge/test_linked_folder_sync.py -q
# → 2 failed, 171 passed（除两处预期失败外全绿，无回归）
```

环境备注：`test_linked_folder_sync.py` 在纯 worktree 下收集失败
（缺 `data/user/settings/main.yaml`，主仓库 checkout 才有），与本次改动无关，
为 origin/main 既有环境依赖，故上方命令将其排除。

## 覆盖收敛（coverage.py 实测，`--include` 仅 manager.py）

| 度量 | 数值 |
| --- | --- |
| audit 全量基线缺失行 | 329（73.7%） |
| tests/knowledge 范围、无新文件 | 514 缺失（58.9%） |
| tests/knowledge 范围、含新文件 | 478 缺失（61.8%），套件内 +36 行 |
| 相对全量基线净收敛 | 16 行（329 → ≤313），全量基线中原本仍缺失的行 |

新覆盖的基线缺口行：106-107（`_provider_from_version_entry` signature 回退）、345（空
kb_config.json）、590（`get_kb_status` 未注册）、762（注册目录缺失）、1260-1268
（`set_default` 未找到即抛错 + 中心化写入）、1324-1326（`get_metadata` 空默认）、1404
（`get_info` 无名无默认抛错）、1704（删除未注册 KB 抛错）。

## 两处预期失败（修复卡契约）

1. `test_delete_default_kb_clears_centralized_default`
   现状：`delete_knowledge_base` 从不通知 `KnowledgeBaseConfigService`，
   `defaults.default_kb` 继续指向已删除的 KB（实测 `get_default_kb() == "alpha"`）。
   `manager.get_default()` 仅靠成员资格回退自愈，直接消费
   `get_default_kb()` 的调用方拿到的仍是已删除名称。
   预期：删除后持久化默认值为 `None` 或其余在列 KB，不得保留被删名称。

2. `test_register_duplicate_name_preserves_existing_metadata`
   现状：`register_knowledge_base` 对已存在名称整条替换为
   `{"path", "description"}`，实测 `entry["status"]` 直接 KeyError，
   `created_at` / `rag_provider` 一并丢失。`register_connected_entry`
   已确立"注册幂等、不动既有条目"的先例，CLI 重复执行 create 不应把 ready KB
   降级为无状态条目。
   预期：描述可刷新，但既有运行元数据（status / created_at / rag_provider）必须保留。

## 修复卡可直接领取的输入

- 失败点：`manager.py:1777-1779`（删除后的 legacy default 分支为死代码，
  `_load_config` 已在读取时剥除单数 `default` 键，修复应改走 config service）；
  `manager.py:767`（register 直接整条覆盖）。
- 复现命令见上，失败断言即验收标准。
