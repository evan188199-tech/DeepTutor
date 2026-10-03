# pocketbase_store 失败分支补测（覆盖缺口 #13）

基线：`origin/main` @ `ef2d9e5c3`（release: v1.6.12），2026-10-03。
对应审计卡：`evidence/coverage-2026-10-02/top15-gaps.md` 第 13 项
（`deeptutor/services/session/pocketbase_store.py`，225 缺失 / 72.6%，错误分支未测存在静默丢数据风险）。

## 交付物

- `tests/services/session/test_pocketbase_store_fallbacks.py` — 24 例失败测试，仅新增测试文件，零产品代码改动（`git status` 仅一个 untracked 测试文件）。
- 本目录 `coverage-baseline.txt` / `coverage-after.txt` / `pytest-run.txt` — 运行证据。

## 覆盖三臂（与卡片一致，全部 mock 后端）

1. **upsert/写失败降级**：`update_session_title`、`update_summary`、`update_session_preferences`、
   `add_message`、`soft_delete_session`、`restore_session`、`hard_delete_session`、`delete_session`
   在后端抛错时必须返回文档化哨兵值（`False` / `0`）而非抛异常，且失败不得改动已存行；
   后端恢复后重试必须成功。读路径降级：`get_session→None`、`get_messages→[]`、
   `get_last_message→None`、`get_turn_events→[]`、`_get_message_summary→{0,""}`、
   `search_sessions/list_sessions/list_deleted_sessions→[]`。
   事件重试语义：`append_events` 同批重放幂等（单行、保留原时间戳）；同 seq 内容冲突抛
   `ValueError`；过期 fencing token 抛 `RuntimeError`。
2. **字段缺失默认值**：老 schema 裸行（无 title/status/preferences/JSON 列）读回时补
   `New conversation` / `idle` / `""` / `0` / `{}` / `is_deleted=False` / `deleted_at=None`；
   消息缺列补 `events=[]`、`attachments=[]`、`metadata={}`、`created_at=0.0`；
   `_json_loads` / `_to_float` 对 None、空串、坏 JSON、垃圾字符串、ISO 日期串的容错。
3. **列表分页边界**：`list_sessions` limit=0→钳到 1、负 offset→0、offset 超总量→空、
   页内 skip 触发 page+1 补抓且切片与全量一致；`list_deleted_sessions` 按 deleted_at 倒序
   分页切片、超界→空；`search_sessions` offset 超总量仍返回正确 total；软删行在 mock 过滤
   失效时被防御性复检剔除。

## 数字（macOS 本机，`/Users/Shared/DeepTutor/.venv`，Python 3.13.13）

| 运行 | 结果 |
| --- | --- |
| 新文件单独运行 | 24 passed |
| `tests/services/session/` 全目录回归 | 384 passed, 1 failed（既有环境性失败，见下） |
| coverage：仅既有 `test_pocketbase_isolation.py` | 347 缺失 / 57.68% |
| coverage：isolation + 新增 24 例 | **226 缺失 / 72.44%**（-121 行） |

审计基线的 72.6%（225 缺失）来自全量测试套件；本卡两条 PocketBase 专项文件合计已把该模块
拉到几乎相同水平。剩余缺口集中在整块未测功能（`usage_records` 1024-1133、
`import_legacy_session` 384-446、`get_message_trace` 1547-1609、`link_turn_message`
1511-1537、`list_nonterminal_turns` 1410-1425），属独立卡片范围。

## 关键发现（修复卡输入）

`add_message` 先写消息行、后盖会话时间戳：当后者失败时方法按契约返回 `0`（调用方视为失败），
但消息行已持久化 → 出现"调用方不知道的孤儿消息"，重试会造成重复。该风险已由
`test_add_message_touch_failure_orphans_persisted_row` 以当前行为钉住；修复卡实现孤儿清理或
返回真实 id 后需同步更新该断言。

## 环境备注

`tests/services/session/test_model_history.py` 有 1 例既有失败
（`FileNotFoundError: data/user/settings/agents.yaml`）：该文件是未跟踪的运行时配置，
在干净 origin/main worktree 上同样失败，与本卡无关。coverage 工具未入仓库 venv，
本次以 `pip install --target <临时目录>` 安装，共享 venv 未被改动。

## 复现

```bash
cd <worktree>
/Users/Shared/DeepTutor/.venv/bin/python -m pytest tests/services/session/test_pocketbase_store_fallbacks.py -v
PYTHONPATH=<tmp>/pylibs /Users/Shared/DeepTutor/.venv/bin/python -m coverage run \
  --source=deeptutor.services.session.pocketbase_store -m pytest \
  tests/services/session/test_pocketbase_isolation.py tests/services/session/test_pocketbase_store_fallbacks.py
/Users/Shared/DeepTutor/.venv/bin/python -m coverage report --precision=2
```
