# test: 会话 sqlite_store 初始化与迁移兜底路径补测

- 日期：2026-10-05
- 分支：`test/sqlite-store-init-20261005`（基线 `origin/main` @ f07029cfc，v1.6.13）
- 新增文件：`tests/services/session/test_sqlite_store_init.py`（不改产品代码，`git status` 仅此一个新文件）

## 测试命令与结果

```
perl -e 'alarm shift; exec @ARGV' 900 python -m pytest -q -p no:cacheprovider \
  tests/services/session/test_sqlite_store_init.py
→ 5 passed in 0.23s

合并既有文件回归：
python -m pytest -q -p no:cacheprovider \
  tests/services/session/test_sqlite_store.py tests/services/session/test_sqlite_store_init.py
→ 42 passed in 0.60s

更大范围 tests/services/session/：387 passed, 1 failed
失败为 tests/services/session/test_model_history.py::test_summary_instruction_is_appended_after_original_messages_and_tools，
在未含本次改动的干净 origin/main 工作区同样失败：该测试依赖未入库的运行时配置
data/user/settings/agents.yaml（主检出目录存在、仓库不跟踪），与本次改动无关。
```

- ruff check / ruff format：通过。

## 风险覆盖映射

| 测试 | 风险点 |
| --- | --- |
| test_fresh_db_builds_full_schema_and_reopens_without_loss | 全新库建表：10 张核心表、5 个关键索引、sessions/messages 关键列齐全，journal_mode=wal；二次打开幂等且不丢数据 |
| test_upgrade_adds_columns_backfills_parents_and_drops_kind | 既有库升级：pre-preferences 时代 schema 就地补列（preferences_json/deleted_at/metadata_json/parent_message_id）、线性 parent 链回填、遗留 kind 列清除、旧数据可读 |
| test_initialize_survives_drop_column_failure_and_stays_usable | DT-22（MEDIUM，sqlite_store.py `_initialize` 中 `ALTER TABLE sessions DROP COLUMN kind` 的 OperationalError 被吞）：模拟旧版 SQLite 不支持 DROP COLUMN，初始化不中断、其余迁移照常生效、kind 残留但 store 完全可用（CRUD/分页正常） |
| test_session_crud_roundtrip_and_message_readback | 会话 CRUD 读回：title 归一化、preferences/status 默认值、消息按插入序读回、parent 自动成链、metadata 往返、update/delete 对命中与未命中的返回值 |
| test_list_sessions_pagination_windows_and_recycle_bin | list_sessions limit/offset 分页窗口与 updated_at DESC 排序、回收站会话从分页消失、restore 恢复可见、hard_delete 仅对回收站生效 |

## 去重说明

- `tests/services/session/test_sqlite_store.py`：已有测试覆盖默认库路径、遗留库文件搬移、notebook 列与 workspace 偏好迁移、notebook CRUD、turn 删除重挂、context 事件；未覆盖本文件的 DDL 完整性、列补齐/parent 回填、DDL 失败兜底、list_sessions 分页窗口，两者互补。
- `test-pocketbase-store`（pocketbase_store 失败分支与分页，开放 PR）：不同模块（PocketBase 实现），本文件全部针对 SQLiteSessionStore，无重叠。
- `test-chat-search`（`test_history_search.py`）：覆盖 search_sessions 字面搜索与回收站过滤；本文件不含 search 路径。

## DT-22 兜底路径的判定

`_initialize` 对 `DROP COLUMN kind` 的失败仅静默吞掉：legacy 列会残留（测试断言 `kind` 仍在），但升级流程继续执行、后续读写不受影响。测试用连接代理在 `DROP COLUMN` 语句上抛 `sqlite3.OperationalError` 模拟旧版 SQLite，未改产品代码。
