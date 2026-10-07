# 信号与退出路径审计（scan: signal-handlers-20261007）

- 基线：`origin/main` @ `f07029cfc`（v1.6.13，2026-10-07 fetch）
- 范围：`deeptutor/`、`deeptutor_cli/`、`web/scripts/`（Python 为主 + Node dev 包装脚本）
- 方法：AST 静态扫描（`audit_signal_exit.py`）+ 人工抽样核对；不含任何动态运行
- 扫描原始输出：`scan_inventory.tsv`（171 条：proc_wait 136 / sig_send 27 / signal_signal 1 / signal_ignore 1 / add_signal_handler 1 / remove_signal_handler 1 / atexit_register 1 / kbd_interrupt 3）

## 去重声明

- 与 `evidence/subprocess-timeouts-20261005`（超时轴）：本卡只覆盖信号注册、handler 内阻塞、atexit 顺序、终止链回收；超时覆盖率不在本报告展开，仅在条目中交叉引用 timeout 字段。
- 与启动轴扫描卡：无重叠。
- 与 `fix-launcher-terminate` 单点修复卡：上游开放 PR **#1715**（`codex/fix/launcher-terminate-visibility-v3`，"surface launcher termination and port-kill signal failures"）涉及 `launcher.py` 的 `_send_tree_signal`/端口终止失败可见性。本报告条目 5、7 与其邻近但不冲突（本卡只报告，不改代码）；其余条目不在该 PR 范围内。
- 开卡前已查 `gh pr list -R HKUDS/DeepTutor --author @me --state open`：无使用 `scan/signal-handlers-20261007` 分支的开放 PR。

## 分级汇总

| 级别 | 数量 | 条目 |
|---|---|---|
| 高 | 0 | — |
| 中 | 5 | #2 #9 #10 #13 #14 |
| 低 | 7 | #4 #5 #7 #8 #15 #20 #23 |
| 信息/正向 | 9 | #1 #3 #6 #11 #12 #16 #17 #18 #19 #21 #22 |

## 条目明细

### 中

**#2 launcher 信号 handler 内执行 `print`（可阻塞、可抛异常）**
`deeptutor/runtime/launcher.py:1485-1491`（handler 注册于 `launcher.py:1036-1041, 1064`）
`request_shutdown` 在 `signal.signal` 注册的 `_handler` 调用链内同步执行 `_log(_t(...))` → `print(flush=True)`。stdout 为满管道/死读端时 write 阻塞会卡住主线程的信号处理；更窄的路径：stdout 断裂（BrokenPipeError）时异常从 handler 抛回主线程任意字节码位置——若落在 `cleanup()` 内（`_terminate` 的 `_log`，`launcher.py:257` 未包 try），atexit 清理被中断，backend/frontend 可能残留。缓解建议：handler 内只置位 + 记录到预打开的 fd，日志延迟到主循环。

**#9 opencode 常驻服务 atexit 清理无回收、无升级**
`deeptutor/services/subagent/opencode_server.py:197-201`
`_atexit_cleanup` 对每个 handle 只 `terminate()`（SIGTERM），不 `wait()`、不 SIGKILL 升级——与同模块 `shutdown_servers()`（`opencode_server.py:180-194`，terminate → wait(5s) → kill）不对称。若 `<cli> serve` 忽略 SIGTERM，进程在父退出后成为孤儿继续监听 loopback 端口。子进程未 `start_new_session`，与 backend 同组，Ctrl+C 场景尚可连带退出；后台 SIGTERM 场景存在泄漏窗口。

**#10 claude 模型抓取 finally 中无界 `os.waitpid`**
`deeptutor/services/subagent/claude_models.py:221-228`（SIGTERM 于 222，waitpid 于 226）
`_capture_model_screen` 的 finally 先向 pty 写 Esc+Ctrl-C，再 `os.kill(pid, SIGTERM)`，随后 `os.waitpid(pid, 0)` **无超时**。抓取主循环有 `_CAPTURE_TIMEOUT=35s` 界（`claude_models.py:34`），但清理路径没有：CLI 卡死/忽略 SIGTERM 时该线程永久挂起。调用方 `sync_claude_models` 经 `asyncio.to_thread`（`claude_models.py:61-66`）执行，结果 /settings 的模型同步动作永久无响应且占用线程池名额。另 pty `os.write`（212-216）在缓冲区满时同样无界。

**#13 update worker 全程无信号/atexit 覆盖，中断即永久卡 `running`**
`deeptutor/runtime/update_worker.py:103-146`（`main` 于 149-154）
worker 以 `start_new_session=True` 脱离会话运行 pip（`update_worker.py:96`），却未注册任何 signal handler 或 atexit：pip 中途收到 SIGTERM/SIGINT 时默认处置直接终止进程，`except Exception` 捕不到，`mark_failed` 不执行，job 停在 `running`。恢复链不闭合：launcher 只捡起 `pending`（`launcher.py:1233`），`_complete_restarted_update` 只处理 `restarting`（`launcher.py:1272`），无 stale-running 回收逻辑 → 更新状态机死锁，需手工清 store。

**#14 dev.mjs 信号转发导致包装进程在子进程死于信号后不退出（已实证）**
`web/scripts/dev.mjs:63-68`
`process.on(signal, () => child.kill(signal))` 阻止了 Node 默认退出；子进程以信号退出时 `process.kill(process.pid, signal)` 把信号再投给自身，命中的仍是同一个 handler——对已死 child 调 `kill()` 返回 false，无 `process.exit` → 父进程挂起。实证：用同构最小脚本（child 自杀于 SIGINT），父进程 2 秒后仍存活（exit=42 为脚本自保超时）。影响面：仅 `npm run dev` 开发路径（`web/package.json:6`；生产走 standalone `server.js`，`launcher.py:860/882`）。终端里表现为 Ctrl+C 后 `node ./scripts/dev.mjs` 残留。修法参考：转发前 `process.exitCode`/在 exit 回调里 `process.exit`，或对自身重投前移除监听器。

### 低

**#4 `_terminate` SIGKILL 升级后不再 wait**
`deeptutor/runtime/launcher.py:254-268`
`wait(timeout=8)` 超时后发 KILL_SIGNAL 即返回，无后续 `wait()`——POSIX 下 zombie 存活至 launcher 自身退出；Windows 下 `taskkill /F` 后无任何完成确认。影响小（launcher 随即退出），但属于回收链不闭合。

**#5 `_send_tree_signal` Windows 分支在清理路径内同步 spawn `subprocess.run(taskkill)`**
`deeptutor/runtime/launcher.py:236-247`
从 `cleanup()`（finally + atexit，`launcher.py:1502-1516`）可达。atexit 阶段模块拆除已开始，spawn 失败被 try/except 吞掉后子进程可能未被终止且无日志。POSIX 分支 `os.killpg/os.kill` 无此问题。

**#7 `_kill_port_listeners` 只杀监听者 pid，不覆盖其子进程**
`deeptutor/runtime/launcher.py:499-523`（`_send_tree_signal(pid, None, ...)` → `os.kill(pid)`，`launcher.py:251`）
pgid 传 None 走单 pid 信号：占用端口的进程（如 next-server 的 worker 子进程）被杀后其子进程可存活。且以端口探活代替 pid 回收（508-518 轮询），5+3 秒后仍存活仅记日志。交互式路径，触发面窄。

**#8 `_stop_unhealthy_source_frontend` 终止后无 wait**
`deeptutor/runtime/launcher.py:1007-1022`
SIGTERM → 轮询 5s → SIGKILL → 固定 `sleep(0.5)`，无 `wait()`；与 #4 同类，量级更小（启动期一次性）。

**#15 sandbox runner 无 SIGTERM 处置，`server_close` 不保证**
`deeptutor/services/sandbox/runner/server.py:356-370`
只捕获 KeyboardInterrupt；SIGTERM 默认处置直接终止，`finally: server.server_close()` 跳过。`ThreadingHTTPServer` 线程为 daemon，无挂起风险；runner 本就由父方 SIGKILL 回收（`backends.py:453`），实际影响仅为端口/临时文件即刻释放路径不一致。

**#20 mineru 模型下载 cancel() 无升级与回收**
`deeptutor/services/parsing/engines/mineru/models.py:163-172`
`cancel()` 只 `terminate()`，不 wait、不 SIGKILL 升级，依赖 pump 线程读到 EOF；下载器若忽略 SIGTERM，下载状态停在 running 且无二次取消手段（对比同仓库 docling/mineru 解析路径的正确升级链 #18/#19）。

**#23 data_volume fork 探针无界 waitpid**
`deeptutor/services/setup/data_volume.py:186-198`
fork 子进程只做 setgid/setuid/写探针后 `os._exit`，正常情况毫秒级；但 `waitpid(pid, 0)` 无超时，数据卷落在卡死网络文件系统时该 API 线程可无限阻塞。理论风险。

### 信息 / 正向（抽样确认的正确模式）

**#1 launcher 信号注册矩阵** `deeptutor/runtime/launcher.py:1031-1066` — SIGINT/SIGTERM/SIGHUP/SIGBREAK 统一注册为置位 handler，关闭逻辑延迟到主循环/finally 执行（正确的 deferred-shutdown 设计）；Windows detached worker 置 SIGINT=IGN（1043-1047），POSIX detached worker 保留 SIGINT→graceful。
**#3 cleanup 幂等 + 双路径兜底 + 顺序正确** `launcher.py:1502-1516` — `cleanup_started` 标志防重入；finally 与 atexit 双保险；先 web 后 backend 的关闭顺序正确（前端先断可避免后端先退造成前端代理报错）。
**#6 CLI asyncio SIGINT 拦截器** `deeptutor_cli/common.py:264-292` — `add_signal_handler` 回调只 `task.cancel()`（非阻塞），`suspend/resume` 在阻塞式提问前归还默认行为；取消后 `while task.cancelling() > 0: task.uncancel()`（238-244）防取消风暴。Windows 降级为 no-op 有文档。
**#12 `maybe_run` 兜底** `deeptutor_cli/common.py:860-863` — KeyboardInterrupt 打印后返回 None，CLI 不裸栈。
**#16 sandbox 终止树** `deeptutor/services/sandbox/backends.py:446-478` — POSIX 组级 SIGKILL + 失败回退单杀；Windows `taskkill /T /F` + `wait_for(5s)`，由调用方 `_communicate` 的 `process.wait()` 任务回收。
**#17 office 预览超时终止** `deeptutor/services/office_preview.py:129-145` — `killpg(SIGKILL)` 防 soffice.bin 残留 + `communicate()` 回收，全程在 `asyncio.to_thread` 内（`office_preview.py:80`）不堵事件循环。
**#18 docling worker 升级链** `deeptutor/services/parsing/engines/docling/local_worker.py:86-94` — terminate → wait(5) → kill → wait，标准正确。
**#19 mineru 解析 worker 升级链** `deeptutor/services/parsing/engines/mineru/local.py:313-320` — 同上，finally 内保证执行。
**#21 isolated_worker 双路径** `deeptutor/runtime/isolated_worker.py:133-141, 148-157` — 同步路径 kill→communicate；异步路径 terminate→wait(1)→kill→wait；`run_in_isolated_process` 取消时先 join 子进程再抛出（169-172 文档化）。
**#22 subagent process 终止链** `deeptutor/services/subagent/process.py:127-140` — terminate → wait(grace) → kill → wait。
**#24 音频/gh 工具超时回收** `deeptutor/services/voice/audio.py:67-73`、`deeptutor/tools/github_query.py:210-216` — wait_for 超时后 kill → wait 回收完整（单进程粒度，无组杀，二者子进程不派生树，可接受）。

## 抽样核实记录（≥4 条要求，实际 7 条）

| 条目 | 核实方式 | 结论 |
|---|---|---|
| #1/#2/#3 launcher 信号链 | 通读 `launcher.py` 注册、request_shutdown、cleanup、finally/atexit 全路径 | 属实（#2 的 BrokenPipeError 链为静态推演，未动态触发） |
| #10 claude_models waitpid | 通读 `_capture_model_screen` 全函数 + 调用方 `models.py:428-430`/`claude_models.py:61-66` 确认 to_thread 上下文 | 属实 |
| #9 opencode atexit | 通读模块全部 204 行，与 shutdown_servers 对比 | 属实 |
| #13 update worker | 通读全文件 + launcher 侧 `_handoff_pending_update`/`_complete_restarted_update` 状态机核对 | 属实 |
| #14 dev.mjs 挂起 | **动态最小复现**：同构脚本 child 以 SIGINT 自杀，父进程 2s 后仍存活（自保 exit=42） | 属实（已实证） |
| #23 data_volume | 通读 fork 块 | 属实（低危前提成立） |
| #24 audio/github_query | 通读两处 except 块 | 属实 |

## 复跑方式

```bash
python3 evidence/signal-handlers-20261007/audit_signal_exit.py deeptutor deeptutor_cli
# 与 evidence/signal-handlers-20261007/scan_inventory.tsv 逐字节比对
```

同输入两次运行输出已验证逐字节一致（diff 为空）。输出按 (路径, 行号, 类别) 排序，与文件遍历顺序无关。
