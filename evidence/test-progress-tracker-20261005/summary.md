# test: ProgressTracker 通知降级与进度落盘补测（AGEN-635）

日期：2026-10-05
基线：origin/main @ f07029cfc（release: v1.6.13）
分支：`test/progress-tracker-degrade-20261005`（推送至 myfork）
范围：仅新增测试文件，不改产品代码。

## 结论（PASS）

- 新增 `tests/knowledge/test_progress_tracker_degradation.py`，6 条测试全部通过。
- 连同既有 `tests/knowledge/test_progress_tracker.py` 共 11 passed。
- `tests/knowledge/` 全目录回归：166 passed（`test_linked_folder_sync.py` 因缺外部配置无法收集，为 main 上的既有问题，与本卡无关，已 --ignore）。
- ruff check 新文件：All checks passed。

## 测试命令

macOS 环境无 GNU timeout，用 perl alarm 等价限时 900s（语义相同，超时杀进程）：

```
perl -e 'alarm 900; exec @ARGV' \
  /Users/Shared/DeepTutor/.venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/knowledge/test_progress_tracker_degradation.py tests/knowledge/test_progress_tracker.py
```

结果：11 passed in 0.50s（完整输出见 pytest-final.log）。

## 测试点与 DT-22 风险对应（report.md §7/§3）

| 测试 | DT-22 风险点 | 断言类型 |
| --- | --- | --- |
| test_notify_without_running_loop_degrades_and_calls_callbacks | MEDIUM progress_tracker.py:103（get_running_loop RuntimeError 被吞） | 降级不抛出；无 loop 时不调度广播；回调仍收到 payload |
| test_notify_with_missing_broadcast_module_degrades_and_calls_callbacks | MEDIUM progress_tracker.py:105（ImportError 分支） | 降级不抛出；广播模块缺失时回调仍收到 payload |
| test_notify_with_failing_broadcast_degrades_and_calls_callbacks | MEDIUM progress_tracker.py:105（§3 #1612 广播静默失败） | 降级不抛出；广播任务在 loop 内失败（gather 确认 RuntimeError），_notify 正常返回且回调已送达 |
| test_update_snapshot_survives_out_of_order_timestamps | #1612「进度不真实」主题（knowledge.py:3952 HIGH 喂给本 tracker） | 进度文件仍正确更新：乱序（后写携带更早时间戳）时整快照覆盖、无合并残留、读取可解析 |
| test_get_progress_tolerates_corrupt_snapshot_and_malformed_timestamp | #1612「进度不真实」主题（快照读取路径） | 损坏 JSON 回退 kb_config 不抛出；异常 timestamp 原样返回不抛出 |
| test_update_persists_snapshot_even_when_a_callback_raises | progress_tracker.py:103/105 同链路回调降级 | 降级不抛出 × 进度文件仍正确更新：单回调抛错不影响落盘与其余回调 |

## 去重说明

- `myfork/fix/reindex-progress-notify`：只改 `deeptutor/api/routers/knowledge.py` 与 `tests/api/test_knowledge_router.py`（router 层 reindex 错误进度写），与本文件零重叠。
- `test/websocket-progress-error-paths-20261004`：只改 `tests/api/test_knowledge_progress_ws.py`（websocket 层），与本文件零重叠。
- `fix/progress-notify-broadcast-warning`（未进 main 的修复分支）：在 `tests/knowledge/test_progress_tracker.py` 断言「广播失败告警一次」——那是修复后行为，在 main 上会失败。本文件断言的是 main 的既有契约「降级不抛出 + 回调/落盘不受影响」，在 main 与该修复分支上均应成立，互不重复。

## 文件清单与 SHA256

见同目录 SHA256SUMS。
