# LightRAG worker 结果异常可见性 · 失败测试集说明

- 日期：2026-10-05
- 基线：origin/main `f07029cfc`（v1.6.13）
- 分支：`test/lightrag-worker-loop-20261005`
- 来源证据：`agent/dt22-todo-scan` 分支 `evidence/todo-scan-2026-10-03/report.md` §7（Python 静默异常处理器清单）

## 1. 缺陷定位

`deeptutor/services/rag/pipelines/lightrag/worker.py` `run_in_worker_loop`（本基线 :173 起）的
owner 取消处理路径末尾：

```python
try:
    worker.result()
except BaseException:
    pass
raise
```

（`worker.py:249-250`，即卡片所述基线 :250。）

契约冲突：模块 docstring 与函数 docstring 都承诺 "Worker exceptions are re-raised in the
awaiting task" / "The caller's cancellation remains authoritative"。但当 owner 任务取消与
worker 真实失败并发时，`worker.result()` 抛出的真实异常（如索引失败的业务错误）被裸
`except BaseException: pass` 静默丢弃：调用方只见 `CancelledError`，失败原因无任何日志，
索引任务"看起来是被取消"而非"失败了"。

## 2. 测试集与锁定契约

文件：`tests/services/rag/test_lightrag_worker_loop.py`（仅测试，无产品代码改动）。

| 测试 | 锁定契约 | 本基线结果 |
| --- | --- | --- |
| `test_worker_error_reraises_in_awaiting_owner_task` | 无取消并发时，worker 异常原样重抛给调用方 | PASS |
| `test_worker_error_racing_owner_cancel_is_reported` | worker 真实失败撞上 owner 取消：调用方仍收 `CancelledError`（取消权威），但该异常必须经模块 logger 以 ERROR 级上报，不得静默丢弃 | **FAIL（缺陷驱动）** |
| `test_normal_completion_returns_result_and_bridge_targets_owner_loop` | 正常完成路径：返回结果；`OwnerLoopBridge.call` 回调在 owner loop 上执行 | PASS |
| `test_owner_cancel_waits_for_job_cleanup_and_loop_stays_usable` | 调用方的 `CancelledError` 只在 job 清理（finally）确认完成后才出现；进程级 worker loop 之后仍可复用 | PASS |
| `test_owner_cancel_stops_job_at_bridge_boundary_and_runs_cleanup` | 在飞 job 在下一个 `OwnerLoopBridge` 边界协作式停止，清理先于调用方感知取消完成 | PASS |

失败测试的失败方式是断言失败（`assert reports, "worker terminal error was silently
discarded during owner cancel"`），不是错误或超时——即"缺上报"这一缺陷本身。

预期取消豁免：若 worker 终态异常本身是 `CancelledError`（owner 取消传导所致），属预期
路径，不要求上报；测试未对该路径断言日志，修复时上报逻辑应保留该豁免，避免噪音。

## 3. 运行与数字

命令（限时）：

```
perl -e 'alarm 900; exec @ARGV' .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/services/rag/test_lightrag_worker_loop.py
# → 1 failed, 4 passed in 0.50s
```

与既有 `tests/services/rag/test_lightrag_worker.py` 同跑无干扰：

```
perl -e 'alarm 900; exec @ARGV' .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/services/rag/test_lightrag_worker.py tests/services/rag/test_lightrag_worker_loop.py
# → 1 failed, 7 passed in 0.38s
```

环境：Python 3.13.13 / pytest 9.1.1 / pytest-asyncio 1.4.0（仓库 `.venv`）。两次运行结果一致。

## 4. 修复线索（供修复卡领取）

1. 上报位置：`run_in_worker_loop` 取消分支内、`worker.result()` 取值处——worker 终态异常
   非 `CancelledError` 时，用模块 logger（`deeptutor.services.rag.pipelines.lightrag.worker`）
   以 ERROR 级记录（`logger.error(..., exc_info=exc)` 或 `logger.exception`）后再 `raise`。
2. 保持调用方语义不变：仍抛 `CancelledError`，不得改为重抛 worker 异常（取消权威是现有
   设计契约，`test_worker_error_racing_owner_cancel_is_reported` 已按此断言）。
3. 豁免规则：worker 终态为 `asyncio.CancelledError` 时不记 ERROR（可选 DEBUG），避免每次
   取消都产生噪音。
4. 测试兼容性：修复后本测试集应全绿；`test_worker_error_racing_owner_cancel_is_reported`
   兼容 `logger.error(..., exc_info=...)` 与消息内插两种上报形态（`_record_mentions` 同时
   检查格式化消息与异常链）。

## 5. 变更清单

- 新增 `tests/services/rag/test_lightrag_worker_loop.py`（5 个测试）
- 新增本说明 `evidence/lightrag-worker-loop-tests-20261005/report.md`
- 无产品代码改动
