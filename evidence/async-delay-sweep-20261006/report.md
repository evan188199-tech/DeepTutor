# asyncio.sleep 非 sleep(0) 延迟收尾复核（测试面）

- 基线：`origin/main` @ `f07029cfcf2c8dfccdb671cdfc343db8334f5741`（v1.6.13）
- 方法可复现：`python3 evidence/async-delay-sweep-20261006/scan_categories.py`；`before.txt` / `after.txt` 为改造前后全量 B 类（`B_async_pacing_nonzero`）命中。
- 口径沿用 `evidence/flaky-tests-20261006/report.md` §1.B：非 sleep(0) 延迟 79 处（B 类命中），其中 ≤0.04s 小步进/有界轮询 31 处，其余为哨兵任务与固定延迟；已立卡文件（zulip 频道、background_leader、turn_runtime_subscribe、journal_recovery、cron_repository、elapsed-rag、elapsed-misc 覆盖的文件）不在本次范围。

## 1. 改造前后命中数对照

| 指标 | 改造前 | 改造后 |
| --- | --- | --- |
| B 类命中行总数 | 79 | 79（polling 步进仍按行计数，非风险口径） |
| 未立卡文件中"固定延迟后断言" | 1 | 0 |
| 哨兵任务未清理（跨用例泄漏） | 0 | 0 |

唯一改造点：`tests/services/web_source/test_sync_scheduler.py` 的 `test_scheduler_renews_lease_during_a_long_sync` —— 原 `await asyncio.sleep(0.25)` 固定等待后断言 `state == "running"`，改为有界轮询（5s deadline × 0.01s 步进，条件为 `state == "running"`），before.txt:225 行的 0.25s 固定延迟在 after.txt 中变为轮询步进 0.01s。

## 2. 哨兵任务无跨用例泄漏（逐一核验）

| 位置 | 机制 | 结论 |
| --- | --- | --- |
| tests/book/test_compile_scheduling.py:270 | pause_book 取消任务，测试断言 `task.cancelled()` | 无泄漏 |
| tests/capabilities/test_setup_capability.py:567 | probe 自身 `wait_for(deadline)` 取消（0.2s） | 无泄漏 |
| tests/core/test_labeled_step_finish_usage.py:56 | `_USAGE_TRAILER_GRACE_TIMEOUT_S=0.01` 包裹取消 | 无泄漏 |
| tests/services/codex_auth/test_client_version.py:157 | 总 deadline 取消，测试断言 `stream.closed` | 无泄漏 |
| tests/services/mcp/test_call_failures.py:209 | 被 cancel 的 turn 连带取消，测试断言 `inflight == []`，`conn.task` 显式 cancel | 无泄漏 |
| tests/services/memory/test_runs.py:68 | cancel 后显式 `await _task` | 无泄漏 |
| tests/services/partners/test_channel_secrets.py:155、199 | `finally: sentinel.cancel(); await sentinel` | 无泄漏 |
| tests/services/partners/test_feishu_stream_resilience.py:126 | 断言 `pytest.raises(CancelledError): await parked` | 无泄漏 |

## 3. 其余非立卡命中核验（无需改造）

- 有界轮询（范式正确）：tests/app/test_multiworker_turn_application.py、test_multiworker_turn_reply_after_queue_drop.py、test_waiting_turn_recovery.py、tests/services/codex_auth/test_service.py、tests/services/cron/test_cron_service.py、tests/services/partner_groups/test_manager.py、tests/services/partners/test_feishu_model_picker.py、tests/services/rag/test_llamaindex_document_loader.py、tests/services/sandbox/test_sandbox.py、tests/services/rag/test_lightrag_worker.py:26/38。
- 慢于超时的 stall 模式（确定性：stall > timeout）：tests/agents/math_animator/test_retry_manager.py（0.05 vs 0.01）、tests/core/agentic/test_tool_dispatch_events.py（0.05/0.02 vs 0.01/0.001）、tests/reading/test_extension_router.py（1 vs 0.01，超时即取消）。
- 并发窗口（断言方向安全，`== 1` 只能因产品缺陷翻转）：tests/services/embedding/test_client_runtime.py:104、test_channel_secrets.py:168。
- 确定性让步/结果注入：test_singleflight_cache.py:71、test_lightrag_worker.py:69/82。
- 真实时钟但单调性保证（sleep ≥ 2×TTL ⇒ 必然过期）：tests/runtime/coordination/test_memory_coordinator.py:118。
- 取消语义验证（无时序断言）：tests/runtime/test_isolated_worker.py:46、tests/services/test_voice.py:782。

## 4. 验证

- `ruff check` / `ruff format --check` 通过（触及文件）。
- `timeout 900 python -m pytest -q -p no:cacheprovider tests/services/web_source/test_sync_scheduler.py`：10 passed，连续 3 次（0.80s / 0.63s / 0.50s）。
- 未改产品代码；无服务器/守护进程/后台进程残留。
