# asyncio 取消路径卫生扫描（AGEN-1024）

- **基线**: `origin/main` @ `f07029cfcf2c8dfccdb671cdfc343db8334f5741`（v1.6.13，2026-10-07 fetch），独立只读 worktree，未改任何产品代码
- **范围**: `deeptutor/` 全部 Python 文件（1029 个，0 解析失败）的 asyncio 取消路径：裸/宽 except 吞 `CancelledError`、取消后资源不清理（锁/子进程/连接/订阅/状态机）、`wait_for`/`wait`/`asyncio.timeout` 超时后的状态残留
- **方法**: `scan_cancel_hygiene.py` 纯 AST 扫描（P1 except 处理器含复抛检测、P2 suppress 参数、P3 手动锁 acquire、P4 等待点、P5 shield），共 **239** 条原始命中，全部逐条人工读源复核归类；明细见 `data.json`，全量清单见 `appendix.md`
- **上游对照**: 开工前 `gh pr list -R HKUDS/DeepTutor --author @me --state open`（30 条分支）与全仓 open PR 检索 "cancel"/"CancelledError"，无相关在途实现；本卡为扫描证据卡，**不开 PR**
- **产物**: `data.json`（239 条命中）、`appendix.md`（全量清单）、`scan_cancel_hygiene.py`（可复现脚本）、`SHA256SUMS`

## 1. 结论（PASS）

- 命中 **239** 条（P1 except 105 / P2 suppress 17 / P3 手动锁 5 / P4 等待点 93 / P5 shield 19），人工复核后：**高危/残留级 8 组、中危 9 组、低危·惯用法约 180 条（归并为 6 类惯用法）、正面范本 15 处**。
- **最显著的阴性结果：全仓 `except:` 裸捕获为 0**（唯一 grep 命中是 docstring 文本）；105 个 P1 处理器里 62 个正确复抛（cleanup-then-raise 是全仓主流写法）。`except Exception` 在 Python 3.8+ 不捕 `CancelledError`，故未被计入命中——代码库整体对"取消不可吞"的纪律明显好于一般水平。
- 真正的存量风险集中在四处：**TrafficController 令牌等待期间被取消会永久漏掉并发槽**（可致整 provider 饿死）、**CodeBuddy owner-loop 把 CancelledError 转写进 future 后继续运行**（取消被吃 + 责任错标）、**CodeBuddy 登录任务被取消后状态机停在 waiting**、**mcp `_disconnect` 被取消时连接任务不被取消且状态不落盘**。
- 逐条复核含 15 处正面范本（见 §6），修复卡可直接以仓内写法为模板，不必引入新依赖。

## 2. 高危项（可致状态残留/死锁，单独列出）

| # | 位置 | 问题 | 后果与建议 |
| --- | --- | --- | --- |
| H1 | `deeptutor/services/llm/traffic_control.py:88`（守卫在 :97-101） | `__aenter__` 先 `wait_for(_semaphore.acquire())` 拿并发槽，再 `_wait_for_token()`（:61-79 在锁外 `await asyncio.sleep(wait_time)` 退避）。守卫 `except Exception: release(); raise` 捕不到 `CancelledError`（BaseException）——在令牌退避睡眠中被取消（如客户端断开取消 handler）时**信号量槽永不归还**；`__aenter__` 未完成，`__aexit__` 不会执行 | 每次此类取消永久少一个 `max_concurrency` 槽，累积后所有请求 `acquisition_timeout` 报错，该 provider 整体饿死（死锁级）。建议：`except BaseException: self._semaphore.release(); raise`，或把令牌等待挪进槽内用 `try/finally` 包住 |
| H2 | `deeptutor/services/llm/provider_core/codebuddy_provider.py:104-105`（连带 :115-116） | owner-loop 内层 `except BaseException` 把异常（含任务自身的 `CancelledError`）`set_exception` 进 turn future 后**不 re-raise、继续下一轮循环**：被 cancel 的 owner 任务吞掉取消继续服务；同时 waiter（`run_turn` :128 的 `await future`）收到一个**不是自己取消**的 `CancelledError`，上层会把 SDK 故障错标成"回合被取消" | 取消语义失效 + 状态错标。建议：内层只捕 `Exception`（SDK 故障转 future），`CancelledError` 单独 `raise`；:115 `except BaseException: pass`（disconnect）同样收窄为 `Exception` 并记 debug 日志 |
| H3 | `deeptutor/services/codebuddy_auth.py:167-171`（对照 :52-59 置位） | `_wait_for_login` 的 `except asyncio.CancelledError: return` **不清理状态**：`start_login` 置的 `_operation_state="waiting"`、`_flow`、`_task` 全部残留；Exception 分支（:173-180）反而有完整清理。任务被外部取消后（服务停机/重建 flow），UI 状态机永远停在"等待登录" | 状态残留。建议：cancel 分支与 Exception 分支同样在 `self._lock` 内清 `_flow/_task` 并把 `operation_state` 置 `"cancelled"`（参照同仓 `services/codex_auth/service.py:651-653` 的正确写法） |
| H4 | `deeptutor/services/memory/consolidator/runs.py:278-296` | `_drive` 的取消分支正确落 `run.status="cancelled"`，但 `finally` 内三步清理（emit run_ended → `_active.pop` → 唤醒 waiters）是**顺序裸 await**：第二次取消落在 finally 的第一个 `await self._emit` 上时，`_active.pop((layer,key))` 被跳过 | 该 (layer,key) 槽位被永久占用，后续同组巩固 run 全部被拒（组级卡死）。建议：finally 内每步各自包 `try/suppress(Exception)`（参照 `executor.py:1255-1300` 的"每步独立 suppress"写法） |
| H5 | `deeptutor/services/mcp/manager.py:846-857` | `_disconnect` 用 `except (asyncio.TimeoutError, Exception)` 收编超时后 `conn.task.cancel()`——但元组不含 `CancelledError`：若调用方在等待断开时自身被取消，`conn.task` **不会被 cancel**、`conn.status="disabled"` 与 adapters 清理不落盘（`_unregister_adapters` 在等待前已做，注册表无残留） | 连接任务残留运行 + 状态陈旧。建议：外层再套 `try/finally`，finally 里保证 `cancel()` 与状态写入，取消异常继续向上抛 |
| H6 | `deeptutor/services/partners/manager.py:913-916`（同型 :1019-1022） | `stop_partner` 对每个任务 `wait_for(shield(task), 5.0)`，超时后 `except (CancelledError, TimeoutError): pass` **放弃等待即宣告 stopped**、`del self._partners[partner_id]`：超过 5s 优雅期的渠道任务仍在后台收发，而运行状态已发布为 stopped | "僵尸渠道"状态残留（账实不符）。建议：超时后保留对 task 的 done-callback 记录（日志告警），或把发布 stopped 推迟到全部任务确认结束后 |
| H7 | `deeptutor/services/rag/pipelines/lightrag/worker.py:238-251` | `run_in_worker_loop` 优雅期（默认 grace）过后进入 `while not worker.done(): await wait({worker})` **无超时兜底等待**，且循环内再次被取消也只重复 cancel bridge 后继续等 | 若 worker 线程 loop 彻底卡死（不响应 cancel），owner 任务永久挂起且不可再取消（死锁）。注释表明是"宁可挂起也不留脏锁"的取舍；建议至少加二级硬上限（如 grace×10）后放弃并降级报错，或提供 manager 级强制重建 worker loop 的出口 |
| H8 | `deeptutor/services/llm/provider_core/azure_openai_provider.py:222-236`、`openai_compat_provider.py:1131`、`:1223` | 空闲超时用 `wait_for(stream_iter.__anext__(), 90)`，超时路径**没有显式关闭 SDK stream**（对照 anthropic_provider.py:568 用 `async with messages.stream(...)` 确保关闭） | 超时后底层 HTTP 响应/连接悬挂到 GC，高频超时下耗尽连接池（资源残留）。建议：三条路径补 `finally: await stream.close()`（或改 async-with），openai SDK 的 `AsyncStream` 支持 `close()` |

## 3. 中危（有残留面，但影响有界）

| # | 位置 | 问题 |
| --- | --- | --- |
| M1 | `deeptutor/api/routers/book.py:1514` | `except (asyncio.CancelledError, Exception): pass` 收尾转发任务：吞掉 close 调用者自身的并发取消，且把转发任务的真实异常一并静默（无日志）。建议改为 `task.cancelling()` 判别 + 异常分支记日志 |
| M2 | `deeptutor/services/llm/provider_core/codebuddy_provider.py:356-366` | `aclose()` 用 `uncancel()` 吞取消以清完所有 session——多会话清理的合理取舍，但调用方的取消被完全吃掉且无日志；建议完成后按 `cancelling()>0` 补 `raise` |
| M3 | `deeptutor/runtime/agentic/tool_dispatch.py:725-737` | 工具调用 `wait_for(timeout)` 超时后按重试策略**重新执行同一工具**：非幂等工具（写文件、发消息）存在"第一次已部分生效→取消→重放"的双重执行面。建议对非幂等工具禁用超时重试或要求工具实现幂等键 |
| M4 | `deeptutor/api/routers/question.py:334`、`:564` | WS 生成端点 finally 内 `pusher_task.cancel(); await` 后 `except CancelledError: pass`——惯用法，但同时把端点任务自身的并发取消一并吞掉；同 M1 建议判别后复抛 |
| M5 | `deeptutor/services/rag/pipelines/lightrag/worker.py:195,207` | `run_bound_job`/`submit` 以 `finished.set_exception(exc)` 吞掉一切异常——concurrent.futures 边界的标准写法（异常经 future 传递），但若 owner 侧永不 `worker.result()`（取消提前退出时 :250 已兜底取结果 ✓），仅提示此为边界设计，无需改动 |
| M6 | `deeptutor/partners/channels/manager.py:332,364`、`partners/channels/weixin.py:1071,1129` | 渠道启动/停止与发送路径 `suppress(CancelledError)`：发送被取消即静默丢消息（无回执无日志）；建议至少 debug 日志记录被取消的发送 |
| M7 | `deeptutor/services/partners/manager.py:881-894` | `_outbound_router` 被取消时 `return`（不 re-raise）：任务以"正常完成"收场，`task.cancelled()` 为 False，监控/收尾语义失真；建议复抛 |
| M8 | `deeptutor/services/codex_auth/oauth.py:126` | 回调 handler `wait_for(readuntil, 2)` 超时→404 兜底 ✓，但 handler 挂在 server 上，登录窗口整体超时由 `wait()` :235 统一关服清理 ✓——仅提示双超时并存（低）；保留在此供修复 H8 时一并核对 |
| M9 | `deeptutor/services/rag/pipelines/llamaindex/pipeline.py:135-148` | stall-guard 的 `wait({worker_task})` 模式与 H7 同型（`asyncio.wait` 无超时），但其 job 在 executor 线程且有 `progress_live.clear()`/`_release_index_worker` 兜底（:135 前），风险低于 H7；建议同样加二级上限 |

## 4. 低危 / 惯用法归并（约 180 条，全清单见 appendix.md）

以下 6 类为仓内普遍惯用法，单条不改也不致残留，列出供后续统一收敛时参考：

1. **自取消后 `except CancelledError: pass/await` 收尾**（约 45 条）：`base_sync.py:87`、`web_source/scheduler.py:99`、`cron/service.py:327`、`event_bus.py:182`、`background_leader.py:62,136`、`matrix.py:293,554`、`telegram.py:1108`、`zulip.py:847`、`discord.py:504`、`whatsapp.py:81`、`mattermost.py:155`、`napcat.py:108,236`、`unified_ws.py:137`、`book.py:1514`（另见 M1）等。统一风险：同时刻调用者自身被取消会被吞；**仓内已有两处正确范本**（`mcp/manager.py:505-510` 与 `subagent/partner.py:150-152` 的 `task.cancelling()>0 → raise`），收敛时照抄即可。
2. **worker 循环 `except CancelledError: break`**（约 25 条）：`event_bus.py:139`、`discord.py:94`、`feishu.py:589`（线程内自有 loop）、`manager.py:458`、`matrix.py:563`、`mochat.py:709,742`、`msteams`/`slack` 同型。停机循环标准写法，取消后循环退出、资源由 finally/管理器收尾，未发现残留。
3. **`suppress(CancelledError)` 心跳/打字指示**（P2 全部 17 条 + `cli_apps/provider.py:389`）：无状态周期任务，取消即静默退出符合语义。
4. **`except BaseException: cleanup; raise`**（25 条 ✓ 正确）：`metrics.py:207,236,272`、`lightrag/ingress.py:297`、`pipeline.py:315,345,360,412`、`llamaindex/pipeline.py:135`、`kb_move.py:417`、`secret_files.py:45`、`workspace/activity.py:33`、`session/turns/request_preparer.py:803`、`mineru/local.py:284` 等——cleanup 后一律复抛，**这是全仓的主流正确模式**。另 `worker_process.py:31,59` 为子进程 pickle 边界（异常经 IPC 信封回传），属设计内吞掉。
5. **P3 手动锁 5 条全部安全**：`isolated_worker.py:178`（finally release ✓）、`embedding/client.py:68`（acquire 轮询与 try 之间无 await，finally release ✓）、`traffic_control.py:88`（槽获取本身经 wait_for，信号量取消安全；泄漏点在令牌等待，见 H1）、`sandbox/quota.py:74`+`service.py:125`（Lease 上下文管理器，acquire 成功后到 return 无 await 窗口 ✓）。
6. **P4 无残留的等待点（约 70 条）**：超时→降级/报错且无共享状态写入的典型：`suggestions.py:563`（单飞+done_callback 清理 ✓✓）、`title_service.py:122`（降级标题 ✓）、`quiz_judge.py:433`（`asyncio.timeout` 作用域 ✓）、`retry_manager.py:70,111,144`（超时转 RenderError 进重试 ✓）、`probes/readiness/settings_spec/provider_probe`（探测降级 ✓）、`subagent/process.py:131,175`（超时即 terminate→kill ✓）、`sandbox/backends.py:474-500`（取消捕获任务+杀进程树 ✓）、`isolated_worker.py:192-199`（超时杀子进程、取消经 shield 杀完再复抛 ✓✓）、`lifecycle.py:446`（超时对账持久层 ✓✓）、`stream_bus.py:337`（finally 摘除监听 ✓）、`mcp/manager.py:547` 等。`deeptutor/learning/tests/` 内 4 条 `wait_for` 为测试代码，不进修复建议。

## 5. 与其他扫描轴去重

- **锁轴（scan-lock-usage / AGEN-665）**：本卡 P3 只判"取消路径是否释放"，5 条全部安全；该卡的"全局锁+长 IO 串行化"（CodeBuddy env-key 锁、embedding spacing 锁等）不在此重复。交叉点：`embedding/client.py` spacing 锁在本卡确认**取消安全**（可作该卡 H4 修复时的回归项）；`traffic_control` 信号量该卡未列（属取消轴新发现）。
- **阻塞轴（scan-async-blocking / AGEN-998，同基线 f07029cfc）**：loop 阻塞不属本卡；交叉确认 `msteams.py:255`/`zulip.py:180` 的 stop 路径 thread-join 属该卡，本卡不评。其"15 条正确卸载"结论与本卡对 `isolated_worker` 的正面结论互为印证。
- **未 await 轴（scan-void-promises / agent/dt22-void-promise-scan）**：fire-and-forget 任务本身不评；本卡只在 `napcat.py:236`（done-callback 取结果）与其轴相交，该处取消吞掉属边界正确写法。
- **信号轴（scan-signal-handlers / AGEN-980）**：无交集（本卡不含 signal 处理）。
- **测试时序**：`learning/tests/test_event_hub.py:16,35,49,66` 的 `wait_for` 按测试代码排除。

## 6. 正面范本（修复卡直接参照，勿引入新模式）

| 位置 | 模式 |
| --- | --- |
| `services/mcp/manager.py:503-510` | `except CancelledError:` 内用 `current_task().cancelling()>0` 区分"子任务取消 vs 自身取消"后复抛 |
| `services/subagent/partner.py:144-152,163-171` | suppress+shield 等既有回合后按 `cancelling()` 复抛；取消时回收 live 任务再 `raise` |
| `services/subagent/opencode_family.py:163-175` | 取消时 shield 发出 abort 请求（保护收尾写）后 `raise`，finally 回收监听任务 |
| `services/subagent/partner_group.py:110-116` | 取消时遍历取消所有在飞 turn 任务再 `raise` |
| `runtime/isolated_worker.py:170-205` | 取消→shield 杀子进程→复抛；超时→杀进程→转域异常；槽位 finally 释放 |
| `services/codex_auth/service.py:651-653`、`oauth.py:235-252` | 取消→落 `login_cancelled` 状态；外部取消转换错误码、真取消复抛 |
| `services/session/turns/executor.py:206-215,1255-1300` | 终态持久化逐步独立 shield+suppress，注释写明"留 running 会被误判孤儿" |
| `services/session/turns/lifecycle.py:85-100,295,321` | 停机先哨兵后限额 drain 再 cancel；心跳/取消等待后正确复抛/收尾 |
| `book/engine.py:1257-1272`（compile_page） | shield + 身份键 in_flight 释放，注释解释"不让单个断开的 WS 杀掉共享编译" |
| `book/engine.py:1444-1460`（_worker_loop_active） | 空闲超时双重校验后自清 worker/runtime 注册并触发内存回收 |
| `book/blocks/base.py:150-151`、`agents/loop/agent_loop.py:1357-1367` | CancelledError 先于 Exception 处理并 `raise`；取消时保留部分产出再复抛 |
| `api/routers/workspace.py:61-67,196-199` | shield+done_callback：断连不弃拷贝、迟到异常必被取回 |
| `services/llm/factory.py:722-729` | 生成器 finally 取消上游生产任务并 suppress 等待 |
| `services/cron/service.py:327-329` | 循环内 `except CancelledError: raise` 先于 `except Exception` |
| `runtime/background_leader.py:160-183` | FIRST_COMPLETED 竞争，输者取消+suppress 回收，finally 兜底 |

## 7. 人工复核记录（抽样 24 处，误报 1）

| 抽样 | 复核结论 |
| --- | --- |
| traffic_control `__aenter__` 完整读源（:61-135） | 确认槽泄漏路径真实（H1）：`_wait_for_token` 锁外 sleep 可被取消且守卫捕不到 |
| codebuddy_provider `_owner_loop`/`close`/`aclose` 完整读源 | 确认 H2：owner 靠 `ops.put(None)` 哨兵停止，直接 cancel 被内层吞掉；waiter 收到错源 CancelledError |
| codebuddy_auth `start_login`/`_wait_for_login`/`cancel_login` 对照读源 | 确认 H3：外部 cancel 路径无状态清理；显式 cancel_login（:68-71）反而有清理 |
| consolidator `_drive` + `_emit` 完整读源 | 确认 H4：finally 三步裸 await，二次取消跳过 `_active.pop` |
| mcp `_disconnect`/`_call_watching_connection` 读源 | H5 成立；同文件 :503-510 为正确范本（同一作者两种写法并存） |
| lightrag worker 全函数读源 | H7 的无界等待成立但注释明示取舍；:250 的 `BaseException: pass` 是"取回异常防 warning"再 `raise`，**非吞掉**（初判误报，已纠正） |
| isolated_worker / subagent process / sandbox backends 读源 | 三处子进程取消清理全部正确，列为范本 |
| executor / lifecycle / orchestrator / partner_group 读源 | 取消终态落盘链完整， fencing token 防竞态，列为范本 |
| event_bus / unified_ws / knowledge ws / mochat / telegram / discord 读源 | 均为惯用法类，无残留 |
| suggestions 单飞 + `_bounded_generation` 读源 | done_callback 拥有清理权，无残留（范本） |
| 误报 1 条 | `lightrag/worker.py:250` 初扫判"吞 BaseException"，读源确认其后紧跟 `raise`，非吞掉 |

## 8. 方法限制

- 静态 AST 无调用图：`except CancelledError` 处理器内**经 helper 间接复抛**（如包一层函数）会判为 swallow——逐条读源已覆盖全部 43 个 swallow 命中，不存在此形态。
- P4 只标记等待点本身，"超时分支是否写共享状态"靠人工读源归类（93 条全部过目）；后续若做修复卡，建议以 §2/§3 清单为准而非静态类别。
- `task.cancelling()` 为 3.11+ API；仓库 `pyproject` 若仍需支持 3.10，收敛惯用法时需提供兼容写法（`current_task().uncancel()` 配合计数）。
- 嵌套函数内的处理器按所在最近函数记名；lambda 内不含 try 语法，无遗漏面。

## 9. 复现

```bash
# 基线 f07029cfc（v1.6.13）；仓库根目录：
python3 evidence/cancel-hygiene-20261007/scan_cancel_hygiene.py deeptutor /tmp/out.json
# stdout 输出 summary（files/hits/by_pattern/by_kind），全量命中写入第二参数路径
```

## 10. PR 草稿（不开 PR，仅备案）

本卡为只读扫描，无代码改动，无可开 PR。若人决定将 §2 高危项拆修复卡，建议首拆 H1（traffic_control，一处 4 行改动 + 回归测试）与 H3（codebuddy_auth 状态清理，对照 codex_auth 范本），两者相互独立、风险最低。
