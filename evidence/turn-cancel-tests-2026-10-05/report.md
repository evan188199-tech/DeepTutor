# 会话 turn 取消路径回归测试（turn-cancel-tests）

- 日期：2026-10-05
- 分支：`agent/dt605-turn-cancel-tests`（基于 `origin/main` @ `f07029cfc`，release v1.6.13）
- 证据来源：`agent/dt22-todo-scan` 分支 `evidence/todo-scan-2026-10-03/report.md` §7
  - `MEDIUM | deeptutor/services/session/turns/lifecycle.py:321 | CancelledError | pass | cancel_turn | await execution.task`

## 目的

`TurnLifecycle.cancel_turn` 取消任务后在 `try: await execution.task / except asyncio.CancelledError: pass`
中吞掉取消结果并无条件返回 `True`，调用方无法知道取消是否真正落地（持久行是否终态、
内存执行体是否一致）。本测试集锁定"取消-确认契约"，为后续修复卡提供可直接领取的验收标准。

## 产物

- `tests/services/session/test_turn_cancel.py`（8 个用例，不改任何产品代码）

## 契约与用例映射

| 契约 | 用例 | 基线结果 |
| --- | --- | --- |
| 取消后任务态一致：返回 True 必须意味着持久行终态 | `test_cancel_confirms_terminal_state_when_task_swallows_cancellation` | **FAIL**（行停在 `running`） |
| 取消后任务态一致：内存与持久态收敛（task-less 占位执行体） | `test_cancel_converges_memory_and_durable_state_for_taskless_execution` | **FAIL**（`has_live_execution` 仍为 True） |
| 重复取消幂等：终态行不被破坏 | `test_repeated_cancel_is_idempotent_after_settled_turn` | PASS |
| 重复取消幂等：取消风暴收敛到唯一终态行 | `test_cancel_storm_converges_to_one_terminal_row` | PASS |
| 取消期间新事件不复活：晚到 waiter restore 被状态栅栏拒绝 | `test_late_waiter_restore_and_events_cannot_revive_cancelled_turn` | PASS |
| 回退路径：无执行体时持久 running 行被就地取消 | `test_cancel_fallback_settles_orphaned_running_row` | PASS |
| 协调器在位时不越权改远端行 | `test_cancel_defers_to_coordinator_for_unowned_turn` | PASS |
| 未知 id / 已终态行返回 False 且无写副作用 | `test_cancel_returns_false_for_unknown_or_settled_turns` | PASS |

运行方式（在仓库根目录）：

```
timeout 900 python -m pytest -q -p no:cacheprovider tests/services/session/test_turn_cancel.py
```

基线运行：`2 failed, 6 passed`（详见 `pytest-baseline.txt`）。两个 FAIL 即修复卡的验收用例；
6 个 PASS 是修复不得回退的护栏。

## 夹具说明

任务体镜像 `TurnExecutor._run_turn` 的任务侧契约：协作型任务在取消时执行与
`_transition_execution` 相同的双前驱 CAS（`running`→`waiting_input` 前驱）写入终态并
re-raise，`finally` 中按真实路径注销执行体、给订阅者投递哨兵；吞没型任务（shield 等
第三方代码的病理形态）吸收 `CancelledError` 且不落任何状态。park 场景复刻 `ask_user`
暂停（`waiting_input`），并验证取消期间产生的晚到事件与取消后的晚到 restore 写入。

## 修复线索（供修复卡直接使用）

1. **确认缺口（两个 FAIL 的根因）**：`cancel_turn`（lifecycle.py:316-323）`await
   execution.task` 吞掉 `CancelledError` 后直接 `return True`，不校验持久行状态。
   修复方向：await 之后读回 turn 行，若仍处于 `running`/`waiting_input` 则补一次
   终态写入（复用回退路径的 `update_turn_status(turn_id, "cancelled", "Turn cancelled")`），
   并据此决定返回值。
2. **task-less 占位执行体泄漏（FAIL #2）**：`execution.task is None` 的占位执行体被
   当作"非活跃"走回退路径翻转持久行，但从不从 `_executions` 注销，导致
   `has_live_execution`/`has_live_executions` 永远为 True（阻塞 managed update 预留，
   见 `reserve_managed_update`）。修复方向：回退路径成功后同步注销占位执行体，或对
   占位执行体返回 False。
3. **park 竞态窗口（未固化为用例，人工复现）**：`_wait_for_user_reply` 的 waiter
   `finally` 以 fire-and-forget `asyncio.shield` 写 `waiting_input`→`running`。若该写
   恰好落在 `_transition_execution` 两次 CAS（先 `running` 后 `waiting_input` 前驱）
   之间，两次都会失败，行停留在 `running` —— 与 #1297/#1359 同族。线程池交错使该窗口
   概率性出现，不适合作为确定性用例；修复方向 1 的"await 后确认+补偿写"天然覆盖它。
4. 幂等性当前成立：协作任务取消后执行体被注销、行终态，第二次 `cancel_turn` 走回退
   路径返回 False；修复时不得破坏 `test_repeated_cancel_*` 与
   `test_cancel_storm_*` 两个护栏。

## 边界

- 未修改任何产品代码；仅新增测试与证据文件。
- 未推送 `main`/`dev`，未触碰 `/Users/Shared/DeepTutor` 主工作区未提交内容（新 worktree
  `dt-agen605-wt` 内工作）。
