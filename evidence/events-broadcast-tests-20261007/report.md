# api 层事件广播/进度下发 单元测试

日期：2026-10-07
分支：`test/events-broadcast-20261007`（基于 `origin/main` f07029cfc）
改动范围：仅新增两个测试文件，无任何产品代码改动。

## 覆盖对象

| 模块 | 现状（缺口） | 本组测试 |
| --- | --- | --- |
| `deeptutor/events/event_bus.py`（`api/main.py` 启动/停止的全局 EventBus） | 无直接单测（仅间接引用） | `tests/api/test_event_bus_broadcast.py`（15 例） |
| `deeptutor/api/utils/progress_broadcaster.py`（WS 进度下发扇出） | 仅路由层边缘覆盖（`test_knowledge_progress_ws.py` 测的是 replay 边界） | `tests/api/test_progress_broadcaster_delivery.py`（11 例） |

## 三条主线（对应卡片要求）

1. **事件序列化**
   - `Event.to_dict()`：枚举 type 序列化为字符串值、timestamp 转 ISO、event_id/metadata/tools_used 保留；
   - 载荷 `json.dumps/loads` 往返可用（跨进程/线上传输安全）；
   - type 为普通字符串时的兼容分支；
   - 默认字段（tools_used / event_id）实例间独立；
   - ProgressBroadcaster 帧固定为 `{"type": "progress", "data": ...}` 信封且 JSON 可序列化。

2. **订阅者异常隔离**（含卡面指定断言）
   - EventBus：先订阅的 handler 抛错，后订阅的 handler 仍收到同一事件对象（`test_subscriber_error_does_not_affect_other_subscribers`）；后续事件继续投递；逐 handler 隔离顺序验证；
   - ProgressBroadcaster：一个 socket 发送抛错不影响同频道其他 socket 收到帧，且后续广播不受牵连（`test_failing_subscriber_does_not_affect_other_subscribers`）。

3. **背压/丢弃策略**
   - EventBus：队列无界、慢订阅者阻塞时 `flush` 按超时让路并保留积压事件（不丢弃），解除阻塞后按序排空（`test_flush_times_out_and_retains_pending_events_instead_of_dropping`）；`stop` 先排空再关闭；空闲 `flush` 立即返回；无订阅者事件被消费不入队；
   - ProgressBroadcaster：死连接首次发送失败即从频道剔除（不可再被尝试），频道清空后键被回收；无订阅者广播为 no-op；同 socket 帧序保持发布顺序。

## 命令与数字

```bash
# 新增用例（26 例）
python -m pytest -q -p no:cacheprovider \
  tests/api/test_event_bus_broadcast.py \
  tests/api/test_progress_broadcaster_delivery.py
# → 26 passed in 0.55s（900s 限时内完成）

# tests/api 全目录回归
python -m pytest -q -p no:cacheprovider tests/api
# → 816 passed in 18.76s（含既有 790 例，无回归）

# lint
ruff check <两个新文件> && ruff format --check <两个新文件>
# → All checks passed / 2 files already formatted
```

运行环境：`/Users/Shared/DeepTutor/.venv`（Python 3.13.13，pytest 9.1.1，pytest-asyncio 1.4.0）。
测试全部为进程内单元测试：不启动服务器、无网络、无外部服务依赖。

## 说明

- EventBus 是类级单例且 `ProgressBroadcaster` 持类级连接表与 asyncio.Lock；fixture 在每例前后重置类状态并为锁换新实例，避免跨事件循环绑定与用例间串扰（仅测试侧状态管理，不改产品代码）。
- 卡面「guide-events 仅边缘覆盖、guide-embedding 只到进度回调」所指缺口即上表两个模块的直接单测缺失，本组补齐。
