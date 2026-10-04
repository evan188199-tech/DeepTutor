# Python fire-and-forget 异步任务扫描报告（AGEN-453）

- **扫描对象**: `origin/main` @ `ef2d9e5c3c99fd073742c5aadc2bb9584b1e503b`（v1.6.12，只读 worktree，与 AGEN-370 broad-except 扫描同一提交，行号零偏移）
- **扫描日期**: 2026-10-04（UTC）
- **扫描范围**: `deeptutor/`、`deeptutor_cli/`、`scripts/`（排除 tests）；AST 级识别 `asyncio.create_task` / `asyncio.ensure_future` / `<loop>.create_task` / `threading.Thread(target=...)`
- **产物**: `scan_async_tasks.py`（扫描脚本）、`refine_async_tasks.py`（存储/await 精化）、`py_async_tasks.json`（96 条明细）、`SHA256SUMS`
- **上游关联 PR**: 开工前已检索 HKUDS/DeepTutor 开放 PR/issue，无与 Python fire-and-forget / create_task 相关的 PR；本卡不开 PR，修复卡草稿见 §6

## 1. 结论（PASS）

- 3 个目录共扫描 1023 个 Python 文件（0 解析失败），命中 **96** 处：`create_task/ensure_future` 94 处、`Thread(target=)` 2 处；全部位于 `deeptutor/`，`deeptutor_cli/` 与 `scripts/` 零命中。
- 逐条人工复核后分级：**高危 3 组（4 处）**、**中危 11 处**、**低危 21 处**、**合规 60 处**（已 await、内部捕获或存储+回调完备）。
- 主要风险不是"引用未保存导致 GC"（大多数调用点已存入 dict/set/attr），而是 **done-callback 只做清理、不取回/不记录异常**：任务死亡后调用方与日志均无感知，仅靠 GC 时的 "Task exception was never retrieved" 兜底。
- 与 AGEN-370（scan-broad-excepts）按 `file:line` 交叉核对：直接重叠 2 组（`progress_tracker.py:102↔105`、`book.py:1500↔1514`），已在 §5 标注去重；另 6 处同文件 ≤30 行相邻条目属不同关注点，不去重。

## 2. 高危（消息/数据丢失或悬挂，建议独立修复卡）

| # | 位置 | 丢错/丢取消判定 | 失败后果 |
| --- | --- | --- | --- |
| H1 | `deeptutor/partners/channels/telegram.py:978` | task 存入 `_media_group_tasks`（引用安全）但 `_flush_media_group` 无任何 try/except | `sleep(0.6)` 后先 `pop` 缓冲（:998）再 `_handle_message`；后者抛错（网络/限流）时整组媒体消息**已出缓冲、未投递**，永久丢失；task 异常无 done-callback 取回，仅 GC 时告警 |
| H2 | `deeptutor/partners/channels/mochat.py:863` | task 存入 `DelayState.timer`（引用安全）；`_delay_flush_after → _flush_delayed_entries → _dispatch_entries → _handle_message` 全链无异常捕获 | 定时 flush 失败 = 延迟缓冲的整批消息丢失 + 异常无取回；与 H1 同型（缓冲型投递无兜底） |
| H3 | `deeptutor/agents/math_animator/renderer.py:188-189` | `Thread(...).start()` 裸调用，引用即弃，无法 join | `_reader` 无 try：读流 OSError（管道早断）→ 线程死、`_SENTINEL` 永不投递 → 消费端 `queue.get()` **永久挂起**，渲染卡死；线程异常只打 stderr |

## 3. 中危（异常静默 / 任务泄漏 / 死亡无感知）

| # | 位置 | 丢错/丢取消判定 |
| --- | --- | --- |
| M1 | `deeptutor/knowledge/progress_tracker.py:102` | 裸 `loop.create_task(broadcast_progress(...))`：无引用（GC 风险）、无 done-callback；:105 的 `except` 只覆盖同步段，**管不到任务内部异常** → 进度广播失败无痕。【与 AGEN-370 :105 去重，见 §5】 |
| M2 | `deeptutor/api/main.py:276` | done-callback 取回异常后**静默丢弃**（:281-283 仅取不记）→ `CRON_RELOAD` 提交失败 = cron 配置变更永不生效、无日志 |
| M3 | `deeptutor/services/web_source/scheduler.py:185` | done-callback 仅 `pop`；`_run_job` 内部只处理 `CancelledError`（:256），`sync_source`/`repo` 抛 OSError 类异常 → 任务死亡无日志，job 停留 claimed 直到租约过期 |
| M4 | `deeptutor/events/event_bus.py:150` | `_processor_task` 无 done-callback；handler 级异常已记日志（:130-136），但循环体自身崩溃（如 `task_done()` ValueError）→ EventBus `_running` 仍为 True、**假 running 无重启无告警** |
| M5 | `deeptutor/api/routers/question.py:113` | mimic 端点 `pusher_task` 在 finally（:310-314）**只关 interceptor 不 cancel** → 每请求泄漏一个挂在 `queue.get()` 的任务；发送失败 `except: break`（:109-110）静默停推。对照 :453 端点 finally（:560-565）已正确 cancel |
| M6 | `deeptutor/partners/channels/dingtalk.py:87` | done-callback 仅 `_background_tasks.discard`；task 异步执行，:101 外层 try 捕不到 → `_on_message` 抛错 = 消息未回复且无日志 |
| M7 | `deeptutor/services/partners/runtime.py:158` | done-callback 仅 `discard`；`_handle_inbound` 内部 catch Exception（:210-214），但其后投递/活动流代码（:215+）无保护 → 失败静默 |
| M8 | `deeptutor/services/llm/provider_core/codebuddy_provider.py:70` | `_owner_loop` 外层 `except BaseException: ready.set_exception; raise`（:107-110）→ task 异常**永不取回**；owner 死后新 turn 挂在 `_ops.get()` 无 resolver → 请求悬挂 |
| M9 | `deeptutor/services/partners/manager.py:720,721,730,903` | runner/router/channel tasks 仅 append 到 `instance.tasks`，运行期死亡无任何 done-callback → partner `_running` 状态不翻转（假活）；异常滞留到 stop（:818-825 仅捕 Cancelled/Timeout，其余异常会从 stop 冒出）或 GC |
| M10 | `deeptutor/book/engine.py:1419` | worker done-callback 仅 `activity.close()` 不取回异常；:1413 `done()` guard 保证下次 enqueue 重建，但死亡瞬间**无日志**、编译静默中断 |
| M11 | `deeptutor/partners/channels/mochat.py:986` | `_save_cursor_debounced` 无 catch：`_save_session_cursors()` 抛错 → 游标持久化失败无痕，重连后 resume 位置漂移（引用安全，降级为中低） |

## 4. 低危（best-effort 语义 / 合规模式，建议补日志或统一回调）

| 位置 | 说明 |
| --- | --- |
| `deeptutor/runtime/agentic/client.py:231`、`deeptutor/services/llm/provider_factory.py:141` | 裸 `create_task(_close())`，内部 `suppress(Exception)`；仅剩任务 GC 窗口风险（挂起期间可被回收），建议存引用 |
| `deeptutor/runtime/agentic/client.py:517` | `_task` attr 保存；流泵异常未取回，消费端靠 queue 终止，建议 done-callback |
| `deeptutor/logging/process_stream.py:90` | 裸 `ensure_future` 投递日志行；emit 失败即丢行无痕（#1435 同族路径），best-effort 定性 |
| `deeptutor/services/rag/pipelines/lightrag/worker.py:206` | 异常经 `finished` future 正确传导（合规），但 task 对象异常未取回 → 可能产生 "never retrieved" GC 噪音 |
| `deeptutor/partners/channels/feishu.py:668,688` | `expire`/`retry` 仅 finally 无 catch：`_finish_reaction`/`_delete_reaction` 抛错 → 无痕，reaction 残留 |
| `deeptutor/partners/channels/matrix.py:275,547` | `_sync_loop` 静默 `except: sleep(2)` 无日志，断连重试不可见；typing loop 有 Cancelled 处理 |
| `deeptutor/partners/channels/discord.py:404,511` | heartbeat 有 warning+break 但 break 后通道仍报 running；typing 有 debug+return，均 best-effort |
| `deeptutor/partners/channels/telegram.py:1016`、`zulip.py:817`、`weixin.py:1117` | typing/keepalive 内部捕获或 `suppress`，失败=指示器消失，UI best-effort |
| `deeptutor/api/routers/partner_groups.py:385` | `forget()` 取回异常后静默丢弃；推流目标已断开属 best-effort，建议 debug |
| `deeptutor/services/base_sync.py:78`、`deeptutor/services/cron/service.py:318`、`deeptutor/services/web_source/scheduler.py:90`、`deeptutor/runtime/background_leader.py:55,127`、`deeptutor/partners/channels/mochat.py:343`、`deeptutor/partners/channels/mochat.py:678,684` | supervisor 循环内部 `logger.exception` + 继续（合规）；仅非 Exception 死亡静默，通用建议补 done-callback 兜底 |
| `deeptutor/services/session/turns/request_preparer.py:802,808` | done-callback 只关 activity；`_run_turn` 内部 :1306 已 catch Exception，仅 BaseException 路径未取回 |
| `deeptutor/api/routers/partners.py:1730,1850` | finally `cancel()` 不 await（CancelledError 不产生警告）；`_drain` 经 `_safe_send` 吞错属设计 |
| `deeptutor/api/routers/question.py:453` | cancel/await 正确（:560-565）；仅余 :449-450 静默 break 一处 |

## 5. 与 scan-broad-excepts（AGEN-370）去重

逐条 `file:line` 对比 `evidence/broad-except-scan-2026-10-04/classification.json`（121 条，同一提交 ef2d9e5c3）：

- **直接重叠 2 组（去重合并，不再单开修复卡）**：
  1. `deeptutor/knowledge/progress_tracker.py:102` ↔ AGEN-370 `progress_tracker.py:105`（`(ImportError, Exception)` 元组）— 同在 `_notify` 函数、同关注点（进度广播吞错）。注意：:105 的 except **覆盖不到** :102 创建的任务（异步执行），两半需在**同一张修复卡**里一起修（持引用 + done-callback + 收窄元组）。
  2. `deeptutor/api/routers/book.py:1500` ↔ AGEN-370 `book.py:1514`（`except (asyncio.CancelledError, Exception)`）— 同一 close() 路径：_forward 任务异常最终被 :1514 宽元组吞掉。合并为一张卡：收窄元组 + 在关闭路径补 debug 日志。
- **同文件 ≤30 行相邻但不同关注点（不去重）**：`question.py:113↔131`、`question.py:453↔438`、`matrix.py:547↔529`、`mochat.py:343↔360`、`codebuddy_auth.py:59↔79`、`opencode_family.py:392↔410` — AGEN-370 条目均为 except 块宽窄问题，与本次的任务生命周期问题正交。
- 其余 94−8=86 处与 AGEN-370 无空间相邻条目，零重叠。

## 6. 可拆修复卡条目（草稿，按收益排序）

1. **缓冲型消息投递兜底**（H1+H2）：`telegram.py:_flush_media_group`、`mochat.py:_delay_flush_after` 链路包 try/except；失败时 error 日志 + 尽量回滚缓冲或重试一次。
2. **math_animator 读取线程加固**（H3）：`_reader` 包 try/finally（finally 兜底投 sentinel）、保存 Thread 引用并在收尾 join(timeout)。
3. **统一 `observe(task)` helper**（M2/M3/M6/M7/M10 + §4 supervisor 族）：done-callback 里 `exc_info` 级别记录 + 状态翻转；一次落地 5+ 处。
4. **progress 广播任务**（M1，合并 AGEN-370 :105）：持引用 + done-callback + 收窄元组。
5. **EventBus 处理器循环自监控**（M4）：done-callback 记录循环级崩溃并复位 `_running`/重启。
6. **question mimic pusher 生命周期**（M5）：finally cancel + await；两处 `except: break` 补 debug 日志。
7. **codebuddy owner loop 存活可观测**（M8）：死亡时日志 + 后续 turn future 立即 fail 而非悬挂。
8. **partner instance.tasks 假活治理**（M9）：done-callback 记录 + 翻转 runtime 状态；stop 路径收窄 except。
9. **mochat cursor 持久化失败留痕**（M11）：warning 即可。

## 7. 复现

```bash
cd <DeepTutor worktree @ ef2d9e5c>
python3 evidence/async-tasks-2026-10-04/scan_async_tasks.py . --out /tmp/scan.json
python3 evidence/async-tasks-2026-10-04/refine_async_tasks.py . /tmp/scan.json
# 期望：files=1023 hits=96 parse_errors=0
cd evidence/async-tasks-2026-10-04 && sha256sum -c SHA256SUMS
```

## 8. 验收对照

1. **每项附 path:line 与丢错/丢取消风险判定** — ✅ 96 条全部入表（§2-§4 + `py_async_tasks.json` 全量明细含源码行）。
2. **与 scan-broad-excepts 条目去重并标注** — ✅ 2 组直接重叠已在 §5 标注合并，6 处相邻标注不去重理由。
3. **不改任何代码** — ✅ 仅新增 `evidence/async-tasks-2026-10-04/`，未触碰任何源码文件；主工作区 main 未 checkout/reset/clean。
