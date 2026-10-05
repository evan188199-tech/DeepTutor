# evidence: consolidator 等待者契约测试（test_consolidator_waiters）

- 日期: 2026-10-05
- 卡片: AGEN-594（test: memory consolidator 等待者清理回归）
- 分支: `test/consolidator-waiters-20261005`（基于 origin/main `f07029cfc`，v1.6.13）
- 产物: `tests/services/memory/test_consolidator_waiters.py`（新增，8 个测试）
- 来源证据: `agent/dt22-todo-scan` 分支 `evidence/todo-scan-2026-10-03/report.md` §7
  - `deeptutor/services/memory/consolidator/runs.py:256` | ValueError | pass | `wait_for_events` | `run._waiters.remove(waiter)`

## 范围

只针对 `RunManager.wait_for_events`（runs.py，基线 :239 起）及其等待者注册表
`Run._waiters` 的等待-唤醒契约。未改任何产品代码。

## 基线探测结论（先于写测试的实验验证）

在基线（origin/main f07029cfc）上用探针脚本实测四个场景：

| 探测场景 | 结果 |
| --- | --- |
| 阻塞中的 waiter 被 task.cancel() | `run._waiters` 清空，无泄漏（finally 的 remove 正常执行） |
| 两个并发 waiter 被同一次 emit 唤醒 | 各唤醒一次、各返回一次，注册表清空 |
| 静默完成（runner 不再发事件）后唤醒 | 即时返回，不挂起 |
| 阻塞期间事件环回绕（_MAX_EVENTS_PER_RUN=3） | **复现缺陷**：cursor 之后的 seq 1..3 被静默丢弃，waiter 只拿到保留尾部 [4,5,6] |

结论：`except ValueError: pass` 在当前代码里是**潜在隐患**而非活跃缺陷——
今天没有任何外部路径会替 waiter 移除注册表项，所有正常退出路径（事件唤醒、
静默完成唤醒、取消）都能把注册表清干净。因此该行的主要风险是：一旦未来
引入清理/驱逐路径或重复移除，静默吞掉 ValueError 会掩盖注册表不一致
（泄漏 / 失去唤醒）。本测试集把每条退出路径的"注册表必须清空、唤醒必须
恰好一次"锁成回归网，供修复卡在收紧该行时直接使用。

## 顺带发现（超出本卡范围，已按 xfail(strict) 固定）

`test_ring_wrap_while_blocked_does_not_drop_missed_events`：waiter 阻塞期间
事件环回绕会把 cursor 与保留头部之间的事件**静默丢弃**（基线实测丢失
seq 1..3）。这违反 `wait_for_events` docstring 的重放契约（"replay
everything it missed"），SSE 生产者会无感知地跳号。已用
`@pytest.mark.xfail(strict=True)` 固定：当前失败（套件保持绿），修复后
XPASS 会报错，提示把该测试转为正式回归。该缺陷与 runs.py:256 的吞异常
属于不同根因，修复卡可自行决定处理顺序。

## 测试清单与结果

命令（限时）:

```
timeout 900 .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/services/memory/test_consolidator_waiters.py
```

结果: **7 passed, 1 xfailed in ~0.75s**（基线）。

| # | 测试 | 覆盖场景 | 基线结果 |
| --- | --- | --- | --- |
| 1 | test_waiter_removed_once_after_wake_by_event | 重复移除/注册表卫生 | PASS |
| 2 | test_two_waiters_wake_once_each_on_single_emit | 重复移除/多 waiter 各恰好一次 | PASS |
| 3 | test_repeated_cancel_of_waiter_does_not_leak_registry | 重复移除/取消路径 5 轮无泄漏 | PASS |
| 4 | test_duplicate_emit_coalesces_to_single_wake_and_single_removal | 重复唤醒合并为一次恢复 | PASS |
| 5 | test_blocked_waiter_wakes_on_new_event_with_cursor_semantics | 事件到达后唤醒 + cursor 语义 | PASS |
| 6 | test_quiet_run_completion_returns_promptly_without_hang | 无事件完成即时返回（wait_for 限时防挂起） | PASS |
| 7 | test_done_run_returns_immediately_empty_for_future_cursor | 终态 + 空 cursor 即时返回、since<0 归一 | PASS |
| 8 | test_ring_wrap_while_blocked_does_not_drop_missed_events | 回绕静默丢事件（新发现） | XFAIL(strict) |

相邻既有测试 `tests/services/memory/test_runs.py` 复跑: 8 passed，无相互影响。
lint: `ruff check` / `ruff format --check` 通过。

## 修复卡领取指引

修复 `runs.py:255-256` 的吞异常时，本套件锁定的不变量：

1. 每条退出路径（事件唤醒、终态唤醒、task 取消）返回后 `run._waiters`
   必须为空——waiter 移除恰好一次。
2. 多次 emit 合并成一次恢复；每个 waiter 恰好恢复一次、拿到全部错过事件。
3. 静默完成与终态空 cursor 都必须即时返回，不允许挂起（测试用
   `asyncio.wait_for` 限时，破坏契约时以 TimeoutError 失败）。
4. 若修复改为严格移除（去掉 try/except），必须保证没有外部路径能提前
   移除注册表项，否则 #1–#4 会以超时或断言失败暴露。
5. `xfail(strict)` 的回绕测试独立于吞异常根因：修好回绕后该测试会
   XPASS 报错，应转为正式用例；若决定回绕按 best-effort 处理，请在
   修复卡里明确记录并调整该测试的契约断言。
