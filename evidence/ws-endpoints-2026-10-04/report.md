# AGEN-618 · WebSocket 端点错误/teardown 路径清点（只读扫描）

基线：origin/main `f07029cfcf2c8dfccdb671cdfc343db8334f5741`（release v1.6.13）。
对照：`agent/dt22-todo-scan` 的 `evidence/todo-scan-2026-10-03/report.md` §7，以及本地/各自 fork 分支
`agent/dt22-fix-question-ws`、`myfork/fix/progress-ws-visible-errors`、`agent/dt22-quizjudge-teardown`
（三者均**未合并**进 main，拆卡时可作为现成实现）。

## 1. 结论（PASS）

- 服务端 WS 端点共 **9 个**（auth.py 的 `ws_require_auth` 为公共前置，非端点）。
- DT-22 §7 已覆盖 question / quiz_judge / knowledge / partner_groups / partners / book / 客户端 channel
  的大部分静默处理器；本报告**逐条标注去重**。
- 新发现（DT-22 未列、修复分支未覆盖）**14 项**：1 项 HIGH（mastery_path 整条链路无错误处理）、
  7 项 MEDIUM、6 项 LOW/模式项。
- 未改任何代码；本分支只包含本报告与校验和。

## 2. 范围与方法

```
# 端点发现
grep -rn '\.websocket(' deeptutor --include='*.py' | grep -v tests
# 错误/teardown 路径逐个通读：send_json/send_text 失败分支、close 时机、
# reset_current_user、后台推送任务（pusher/drain/fanout）的队列投递与异常路径
```

风险分级：HIGH = 断连/错误路径会产生无日志异常、清理被跳过或互相掩盖；
MEDIUM = 静默吞错（无任何日志）但影响限于单连接或单个推送流；
LOW = 有 debug 级日志或影响极小的模式不一致。

## 3. 端点总清单

| # | 端点 | 处理器 | 错误/清理现状 | 主要新发现 |
| --- | --- | --- | --- | --- |
| 1 | `ws /ws` | `unified_ws.py:44` | 结构良好（断连/内部错误有日志与 error frame；finally 停订阅） | safe_send 全静默、reset 未包裹、并发 send 无锁 |
| 2 | `ws /books` | `book.py:1520` | 结构良好（finally 全部有 debug 日志，本项目模板级写法） | fanout._forward 无保护、send 静默、并发 send 无锁 |
| 3 | `ws /mastery-paths` | `mastery_path.py:789` | **缺整个错误处理层** | HIGH：send/forward/stop/reset 四处连环 |
| 4 | `ws /partner-groups/{group_id}` | `partner_groups.py:339` | finally 清理完整但无日志 | send 无包裹、forget 静默取回异常 |
| 5 | `ws /partners/{partner_id}` | `partners.py:1765` | 设计最好（disconnected 事件 + 任务异常集中日志） | close 未包裹 ×2、drain cancel 未 await、reset 静默（DT-22 已列） |
| 6 | `ws /question/mimic` | `question.py:50` | 部分路径有 debug 日志 | log_pusher 静默 break（新）；其余 DT-22 已列 |
| 7 | `ws /question/generate` | `question.py:360` | 同上 | log_pusher 静默 break（新）；finally close 未包裹但被外层兜住 |
| 8 | `ws /questions/judge` | `quiz_judge.py:227` | safe_send 模式正确 | close/reset 静默（DT-22 已列；teardown 分支已修） |
| 9 | `ws /knowledge-bases/{kb}/progress` | `knowledge.py:4256` | 轮询 + 快照重放 | 循环 `except Exception: break` 静默（新）；其余 DT-22 已列 |

公共前置 `auth.py:535 ws_require_auth`：两个 `ws.close(code=…)`（561、568）未包裹；
568 分支先 reset 后 close，顺序正确；561 分支尚无 token，风险仅为无日志异常（LOW）。

出站 ws 客户端（非 API 端点，DT-22 §7 已列，无新发现）：
`deeptutor/partners/channels/napcat.py`（重连/后台任务日志路径健康：108-117、232-239 有 warning）、
`deeptutor/partners/channels/mochat.py`（357-362、512）、
`deeptutor/services/llm/provider_core/codebuddy_provider.py:115`（BaseException，DT-22 已列）。

## 4. 每端点错误/清理路径判定

### 4.1 `unified_ws.py` — `/ws`

| 位置 | 判定 | 说明 |
| --- | --- | --- |
| `unified_ws.py:69-73` | MEDIUM | `safe_send` 捕获所有异常后仅置 `closed=True`，**无任何日志**（对照 knowledge 修复分支至少 `logger.debug`）。发送失败永久无痕。 |
| `unified_ws.py:141-177` | OK | 订阅转发 `_forward` 有 `logger.exception` + error frame，正确。 |
| `unified_ws.py:65-73, 141-177` | MEDIUM | 主循环与多个订阅任务**并发调用 `safe_send`，无发送锁**（对照 mastery_path:800-807、partner_groups:363-367 均有 `send_lock`）。 |
| `unified_ws.py:374-378` | OK | `WebSocketDisconnect` 记 debug；其他异常有 `logger.error` + error frame。 |
| `unified_ws.py:379-384` | MEDIUM | finally 中 `reset_current_user` **未包裹**（对照 book.py:1824-1828、partners.py:2016-2019 的包裹模式）；若抛错将带出清理阶段。 |
| `unified_ws.py:59-62` | LOW | `container.start()` 未包裹，失败时 token 已 install 且无 reset；概率极低。 |

### 4.2 `book.py` — `/books`

| 位置 | 判定 | 说明 |
| --- | --- | --- |
| `book.py:1502-1505` | MEDIUM | `_SocketFanout._forward` 对 `bus.subscribe()` 迭代**无任何保护**：总线异常 → 任务静默死亡（无日志、无 error frame），客户端画面冻结。send 闭包自身吞错，故仅迭代异常会触发。 |
| `book.py:1508-1515` | LOW（DT-22 §7 已列 1514） | `close` 的 `except (asyncio.CancelledError, Exception): pass` 全吞且无日志。 |
| `book.py:1553-1562` | LOW | `send` 吞掉所有异常置 `closed=True`，无日志（同 unified_ws 模式）。 |
| `book.py:1553-1562 + 1500 + 主循环` | MEDIUM | fanout 多任务 + 主循环**并发 send 无锁**。 |
| `book.py:1815-1828` | OK（模板） | finally：fanout.close / creation_bus.close / 包裹的 ws.close（debug 日志）/ 包裹的 reset（debug 日志）。这是其余端点应对齐的写法。 |
| `book.py:1596-1599` | OK | receive_json 非断连异常 → error frame。 |

### 4.3 `mastery_path.py` — `/mastery-paths`（HIGH）

| 位置 | 判定 | 说明 |
| --- | --- | --- |
| `mastery_path.py:805-807` | HIGH | `send` 有锁但**无异常处理**：客户端已断时任何 error/subscribed 帧（851、859、868、891-896）直接抛出。 |
| `mastery_path.py:845-897` | HIGH | 外层 `try:` **只有 finally，没有 except**：send 抛出的异常原样穿透到 Starlette，无日志、无 close frame、客户端异常断开。 |
| `mastery_path.py:820-838` | HIGH | `forward` 任务内 `send` 失败 → 任务带异常死亡，期间无人取回。 |
| `mastery_path.py:809-817` | HIGH | `stop_forwarding` 仅 `suppress(CancelledError)`：await 一个已死亡的 forward 任务会把其异常**在 finally 中重抛**，掩盖真实退出路径。 |
| `mastery_path.py:898-900` | HIGH | finally 中 `reset_current_user` 未包裹（若 stop_forwarding 已抛错则**根本不会执行到**）。 |
| `mastery_path.py:868` | LOW | `int(message.get("after_revision") or 0)` 对垃圾输入抛 ValueError，走同一条无日志路径。 |

小结：该端点断连期间的任何发送失败都会演变为「无日志异常 + 清理不完整 + 掩盖链」。
建议按 quiz_judge teardown 分支同款 `_teardown` 模式整体修复。

### 4.4 `partner_groups.py` — `/{group_id}`

| 位置 | 判定 | 说明 |
| --- | --- | --- |
| `partner_groups.py:363-367` | MEDIUM | `send` 有锁但无包裹：主循环错误帧（384、425、447 等）发送失败 → 异常穿透 411 的 try（**无 except**）→ finally 清理可运行但全程无日志、无 close。 |
| `partner_groups.py:369-378` | MEDIUM | `push_live` 任务内 send 失败 → 任务死亡；`finally` 有 `live.unsubscribe`（好）。 |
| `partner_groups.py:388-391` | LOW | `forget` 回调取回异常后**静默丢弃**，无日志。 |
| `partner_groups.py:520-530` | OK/去重 | push 任务 cancel + `gather(return_exceptions=True)`（好）；`reset_current_user` 包裹 `except Exception: pass` —— DT-22 §7 已列（530 → 现 529），建议补 debug 日志。 |
| `partner_groups.py:352-357` | LOW | 组不存在早退：`ws.close(4404)` 未包裹（accept 前，风险小）。 |

### 4.5 `partners.py` — `/{partner_id}`

| 位置 | 判定 | 说明 |
| --- | --- | --- |
| `partners.py:1801-1806` | OK | `_safe_send` 只捕 `(WebSocketDisconnect, RuntimeError)`；其余异常会沿任务传播，但外层 `asyncio.wait` 收集后 `logger.exception`（2017-2025），**有兜底**。 |
| `partners.py:1793-1798` | LOW | partner 不存在早退：reset 后 `ws.close(4404)` 未包裹。 |
| `partners.py:1814-1816` | LOW-MEDIUM | 启动失败路径：error frame 后 `ws.close(code, reason)` 未包裹；若 close 抛错则直接穿透，此时**没有 finally 兜底**（位于主 try 之前），reset 不执行。 |
| `partners.py:2007-2015` | LOW | drain 任务 cancel 后**未 await**，可能在 handler 返回后仍在发送（竞态残留）。 |
| `partners.py:2016-2019` | 去重 | reset 包裹 `pass` 静默 —— DT-22 §7 已列（2019 → 现 2018）。 |
| `partners.py:1841-1983` | OK | 所有业务错误均经 `_safe_send` 回 error/stale_session/turn_busy 帧；断连即 break。 |

### 4.6 `question.py` — `/mimic` 与 `/generate`

| 位置 | 判定 | 说明 |
| --- | --- | --- |
| `question.py:107-110`（mimic）、`question.py:447-450`（generate） | **MEDIUM（新）** | 两个 `log_pusher` 发送失败 `except Exception: break`：**静默退出推送循环**，队列剩余日志全部丢弃，无日志、无通知。DT-22 §7 未列（非 pass 而是 break，AST 扫描漏过）。客户端表现：日志流无声停止。 |
| `question.py:259-266`（mimic ws_callback） | OK | send 失败 `logger.debug`。 |
| `question.py:436-440`（generate ws_callback） | 去重 | `log_queue.put` except pass —— DT-22 已列 438。 |
| `question.py:298-306`（mimic complete/error） | OK | `(RuntimeError, WebSocketDisconnect)` → debug 日志。 |
| `question.py:321-323` | 去重/已修 | mimic 错误帧 except pass —— DT-22 已列 323；`agent/dt22-fix-question-ws` 已改为 warning 日志 + 捕获收窄（未合并）。 |
| `question.py:325-355`（mimic finally） | 去重 | pusher 清理/队列清空/close/reset 全部静默 pass —— DT-22 已列 334/336/343/349/355。 |
| `question.py:385、505` | OK/去重 | `(RuntimeError, WebSocketDisconnect)` 分支已有 debug；DT-22 已列。 |
| `question.py:566-574`（generate finally close） | LOW | `await websocket.close()` 未包裹；抛错会被外层 `except Exception`（582-584）接住并记日志，但产生误导性错误日志。 |
| `question.py:576-580` | 去重 | reset 包裹 pass —— DT-22 已列 577。 |

### 4.7 `quiz_judge.py` — `/questions/judge`

| 位置 | 判定 | 说明 |
| --- | --- | --- |
| `quiz_judge.py:269-274` | OK | safe_send 捕 `(WebSocketDisconnect, RuntimeError, ConnectionError)` 返回 bool，模式正确。 |
| `quiz_judge.py:280-303、389-395、446-459` | 去重/已修 | 4 组 close/reset 静默 pass —— DT-22 §7 已列（284/289/298/303/390/395/454/459）；`agent/dt22-quizjudge-teardown` 已用幂等 `_teardown` + debug 日志修复（未合并）。 |
| `quiz_judge.py:448-450` | OK | 流式失败 `logger.exception` + safe_send error。 |

### 4.8 `knowledge.py` — `/knowledge-bases/{kb_name}/progress`

| 位置 | 判定 | 说明 |
| --- | --- | --- |
| `knowledge.py:4387-4389`、`4436-4438` | 去重/已修 | 时间戳解析 except pass —— DT-22 已列（4353/4402 → 现 4389/4438）；`myfork/fix/progress-ws-visible-errors` 已用 `_progress_age_seconds` 修复并带 warning（未合并）。 |
| `knowledge.py:4508-4509` | **MEDIUM（新）** | 轮询循环 `except Exception: break` **静默退出**：包含循环内 4462 的 send_json 失败与任何快照读取异常，无任何日志，连接直接消失。DT-22 未列、修复分支未覆盖。 |
| `knowledge.py:4512-4516` | 去重/已修 | 循环外错误 debug + error 帧 except pass —— DT-22 已列 4480；修复分支已改为 debug 日志。 |
| `knowledge.py:4518` | LOW | `broadcaster.disconnect` 未包裹；若抛错则 close/reset 跳过（内部实现当前不会抛，防御性问题）。 |
| `knowledge.py:4521-4527` | 去重/已修 | close/reset 静默 —— DT-22 已列 4486/4491；修复分支已改 debug/warning。 |
| `deeptutor/api/utils/progress_broadcaster.py:56-66` | OK | 广播端 send 失败 debug 日志 + 移除死连接，队列投递路径健康。 |

### 4.9 队列投递基础设施（对照扫描）

| 位置 | 判定 | 说明 |
| --- | --- | --- |
| `deeptutor/learning/event_hub.py:40、113-123` | OK | maxsize=1 latest-wins，publish 有 RuntimeError guard。 |
| `deeptutor/runtime/stream_bus.py:79-81、119` | OK/LOW | emit 有 RuntimeError guard；订阅队列**无界**，慢消费者有内存堆积风险（非错误路径，记录备查）。 |
| `deeptutor/api/utils/task_log_stream.py:276-281` | 去重 | QueueFull 静默丢帧 —— DT-22 §7 已列 279（LOW）。 |
| `deeptutor/api/routers/auth.py:561、568` | LOW | `ws_require_auth` 两个 close 未包裹（见 §3）。 |

## 5. 可拆修复/补测卡条目（新发现，按优先级）

1. **`fix/mastery-ws-teardown`（HIGH）** — mastery_path.py：`send` 包裹异常并置断连标志；外层补 `except WebSocketDisconnect`/`except Exception`（含日志）；`stop_forwarding` 改为吞掉任务任意异常并记日志；finally 的 reset 包裹 + 显式 close。可整体复用 `agent/dt22-quizjudge-teardown` 的幂等 `_teardown` 模式。补测：断连时 send 失败 → 无未取回任务异常、reset 必达。
2. **`fix/ws-send-lock`（MEDIUM）** — unified_ws.py / book.py / partners.py 三处为并发发送引入 `send_lock`（对齐 mastery_path:800、partner_groups:363 的现有模式）。
3. **`fix/ws-silent-send-logging`（MEDIUM，可与 2 合并）** — unified_ws.py:72、book.py:1561 的 send 吞错补 `logger.debug`；partner_groups.py:363-367 主循环 send 包裹 + 日志；partner_groups.py:388-391 `forget` 取回异常时记 debug。
4. **`fix/question-log-pusher-drain`（MEDIUM）** — question.py:107-110、447-450：pusher break 前记日志（并决定丢弃策略：尽力 drain 或上报一条 error 帧）。
5. **`fix/knowledge-progress-loop-logging`（MEDIUM）** — knowledge.py:4508-4509：break 前区分 send 失败与其他异常并记 debug；或并入 progress-ws 修复分支的延伸提交。
6. **`fix/book-fanout-forward-guard`（MEDIUM）** — book.py:1502-1505：`bus.subscribe()` 迭代包 try/except → `logger.exception` + error frame（send 已安全）。
7. **`test/ws-teardown-contracts`（补测）** — 为 9 个端点写统一 teardown 契约测试：客户端断连后各 handler 不产生 "Task exception was never retrieved"、reset 必达、close 恰好一次。
8. **`fix/ws-low-batch`（LOW 批）** — partners.py:1816 与 partner_groups.py:355 的 close 包裹；partners.py:2012 drain cancel 后 await；unified_ws.py:384 reset 包裹；auth.py:561 close 包裹。

## 6. 与 DT-22 / 修复分支去重对照

| DT-22 §7 条目 | 现行号（origin/main） | 状态 |
| --- | --- | --- |
| question.py 131/146/153（interceptor） | 同 | DT-22 已列，未处理 |
| question.py 323（mimic error send） | 321-323 | DT-22 已列；**fix-question-ws 已修**（未合并） |
| question.py 334/336/343/349/355（mimic finally） | 同 | DT-22 已列，未处理 |
| question.py 438（ws_callback queue put） | 436-440 | DT-22 已列，未处理 |
| question.py 577（reset） | 576-580 | DT-22 已列，未处理 |
| quiz_judge.py 284/289/298/303/390/395/454/459 | 同（±1） | DT-22 已列；**quizjudge-teardown 已修**（未合并） |
| knowledge.py 4353/4402 | 4387-4389 / 4436-4438 | DT-22 已列；**fix/progress-ws-visible-errors 已修**（未合并） |
| knowledge.py 4480/4486/4491 | 4512-4516 / 4521-4527 | 同上 |
| partner_groups.py 530（reset） | 527-530 | DT-22 已列，未处理 |
| partners.py 2019（reset） | 2016-2019 | DT-22 已列，未处理 |
| book.py 1514（fanout close 吞错）、1812（WebSocketDisconnect） | 1514 / 1812 | DT-22 已列（LOW），未处理 |
| task_log_stream.py 279（QueueFull） | 同 | DT-22 已列（LOW） |
| napcat/mochat/codebuddy 客户端 stop/disconnect | 同 | DT-22 已列（MEDIUM），无新发现 |

DT-22 §7 未覆盖、本报告新增：mastery_path 全部条目、unified_ws 65-73/384、
question.py 107-110 与 447-450（pusher break）、knowledge.py 4508-4509（循环 break）、
book.py 1502-1505（_forward）、partner_groups.py 363-367/388-391、并发 send 无锁（3 处）、
partners.py 1816/2012、auth.py 561。

## 7. 复现命令

```bash
cd /Users/Shared/DeepTutor/dt-agen618-ws-scan-wt   # 本分支 worktree
grep -rn '\.websocket(' deeptutor --include='*.py' | grep -v tests   # 9 个端点
git log --oneline -1                                                 # f07029cfc release: v1.6.13
shasum -a 256 evidence/ws-endpoints-2026-10-04/report.md            # 对照 SHA256SUMS
```
