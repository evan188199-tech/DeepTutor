# 全仓资源泄漏静态清点报告（AGEN-964）

- 扫描对象：HKUDS/DeepTutor `origin/main` @ `f07029cfc`（release: v1.6.13），只读 worktree
- 扫描时间：2026-10-07（UTC），seed = `20261006`
- 扫描器：`scripts/scan_resource_leaks.py`（纯标准库 ast，read-only，可复跑）
- 覆盖：1819 个 `.py` 文件全部解析，0 个语法跳过
- 结果：**52 条** = high 4 / medium 2 / low 46（产品代码 35 条，tests/scripts 17 条）

## 轴线与去重边界

本卡只管「资源未释放」轴：

| 规则 | 含义 | 级别 |
| --- | --- | --- |
| R7 subprocess-handle-dropped | Popen/create_subprocess 返回值被丢弃，之后无法 wait/terminate | high |
| R2 client-attr-no-close | aiohttp ClientSession / httpx Client 绑定到 self.<attr>，全模块无 close/aclose 路径 | high |
| R6 subprocess-not-reaped | 子进程句柄保存了但 scope 内无 wait/communicate/poll/kill | medium |
| R8 executor-no-shutdown | ThreadPool/ProcessExecutor 无 with/shutdown（模块级降为 medium） | med/high |
| R1 client-local-no-close | 局部 client 无 close/async-with 管理 | medium |
| R9 ownership-transferred-verify | 所有权转移（return/lambda 工厂/存入其他对象/传给回收 helper/推导式），需确认接收方释放 | low |

去重（不在本卡范围）：asyncio 任务生命周期（scan-async-tasks 轴）、子进程超时处理（scan-subprocess-timeouts 轴）、tempfile 清理（scan-tempfile-hygiene 轴）。扫描器按此边界实现，不产生这三类条目。

## HIGH（4 条，全部人工核实属实）

| ID | 位置 | 问题 | 修复建议 |
| --- | --- | --- | --- |
| RL-0005 | `deeptutor/runtime/update_worker.py:98` | `_launch_restart` 中 `subprocess.Popen(command, stdout=log, **kwargs)` 返回值被完全丢弃（fire-and-forget），失败无从感知，Popen 对象被 GC 时会触发 ResourceWarning | 保存返回值并至少 `p.wait(timeout=…)` 一次（或登记到管理器），失败写入 job 状态 |
| RL-0007 | `deeptutor/services/app_update.py:651` | `launch_update_worker` 同模式：Popen 返回值丢弃，仅写日志文件 | 同上 |
| RL-0008 | `deeptutor/services/codex_auth/service.py:458` | `CodexOAuthService._owned_http = httpx.AsyncClient(timeout=30)`：自建 client 全模块无任何 `close()/aclose()` 调用；服务实例若反复创建，连接池泄漏 | 补 `async def aclose()` 关闭 `_owned_http` 并接入服务关停路径；或改由调用方注入并声明所有权 |
| RL-0028 | `deeptutor/services/skill/hub.py:285` | `ClawHubProvider._client = client or httpx.Client(...)`：`or` 分支自建的 client 从不 close（仅 get/post） | 同上：宿主类补 close/上下文管理器协议 |

## MEDIUM（2 条，全部人工核实属实）

| ID | 位置 | 问题 | 修复建议 |
| --- | --- | --- | --- |
| RL-0004 | `deeptutor/runtime/launcher.py:1133` | `_launch_detached` 保存了 Popen 但只读 `.pid`，scope 内无 wait/poll（有意 detach；父进程随即退出，僵尸风险低，但句柄管理缺失） | 记录 pid 后可显式 `process.poll()` 一次或在文档注明 detach 契约 |
| RL-0027 | `deeptutor/services/search/source_filter.py:95` | 模块级 `_web_risk_executor = ThreadPoolExecutor(max_workers=8)` 只有 `.submit()`，无显式 shutdown（解释器退出时由 concurrent.futures 的 atexit 兜底 join） | 提供 `shutdown(wait=False, cancel_futures=True)` 关停钩子，接入应用退出流程 |

## LOW（46 条，按模式归组；抽样核实见下节）

| 模式 | 数量 | 代表锚点 |
| --- | --- | --- |
| httpx client 经 lambda/return 工厂转移所有权 | 18 | `deeptutor/services/app_update.py:335`、`deeptutor/services/mcp/manager.py:818`、`deeptutor/services/rag/pipelines/weknora/client.py:38` |
| sqlite3 连接经 `_connect()` 工厂 return 转移 | 6 | `deeptutor/multi_user/session_handoff.py:193`、`deeptutor/services/cron/repository.py:107`、`deeptutor/services/task_board.py:72` |
| 子进程交给回收/托管 helper（`_communicate`、`ServerHandle`、`ManagedProcess` 等） | 8 | `deeptutor/services/sandbox/backends.py:253`、`deeptutor/services/subagent/opencode_server.py:108`、`deeptutor/runtime/launcher.py:317` |
| client 存入其他对象（SDK kwargs、服务单例、注册表） | 4 | `deeptutor/services/llm/openai_http_client.py:153`、`deeptutor/services/codex_auth/service.py:1289`、`deeptutor/reading/extensions.py:159` |
| 推导式/集合内批量创建（测试并发进程组等） | 2 | `tests/services/session/test_turn_repository.py:98` |
| 其余测试内 MockTransport 工厂 | 8 | `tests/services/test_app_update.py:44` 等 |

完整清单见 `resource-leaks-findings.json`（含每条 detail 与 suggestion）。

## 人工核实记录（seed=20261006 抽样 + 全量 high/medium 复核）

抽样器从 high+medium 池抽取 6 条（即全部 high/medium，另抽查 8 条 low，共 14 条；另做 5 处阴性复核）：

| ID | 级别 | 核实结论 |
| --- | --- | --- |
| RL-0004 | medium | 属实：仅用 `.pid`，无 wait/poll；detach 模式为有意设计，风险注记已写入条目 |
| RL-0005 | high | 属实：返回值丢弃，确认 fire-and-forget |
| RL-0007 | high | 属实：同上模式 |
| RL-0008 | high | 属实：`rg _owned_http` 全文件无 close/aclose，确为泄漏 |
| RL-0027 | medium | 属实：仅 `.submit()`，无 shutdown 路径 |
| RL-0028 | high | 属实：`self._client` 仅 get/post，无 close |
| RL-0001 | low | 属实：`_connect()` 工厂 return，所有权在调用方 |
| RL-0002 | low | 属实：executor 存入 `self._executors`，`close()` 有统一 shutdown（已妥善管理，评 low 合理） |
| RL-0003 | low | 属实：交由 `ManagedProcess` + 流式线程托管 |
| RL-0009 | low | 属实：client 以 kwarg 注入服务单例，进程生命周期共享 |
| RL-0014 | low | 属实：存入 OpenAI SDK `kwargs["http_client"]`，由 SDK 管理 |
| RL-0029 | low | 属实：存入 `ServerHandle`，有 `_terminate_sync` 回收路径 |
| RL-0043 | low | 属实：测试内 8 个子进程，finally 中 kill+wait（已妥善管理） |
| 阴性×5 | — | `hermes_remote_client.py:44`（`__aenter__/__aexit__` 管理）、`msteams.py:174`（`aclose`）、`weixin.py:358`（`aclose`）、`napcat.py:101`（`await close`）、`app_update.py:335` 工厂（`async with factory()`）均被正确排除或降级，无误报 |

## 确定性与复跑

```bash
# 同 seed 复跑：findings 字节级一致（仅 meta.generated_at 为墙钟时间）
python3 scripts/scan_resource_leaks.py --root . --out evidence --seed 20261006
# 换 seed：findings 不变，仅 manual_sample_ids 抽样变化
python3 scripts/scan_resource_leaks.py --root . --out /tmp/ev2 --seed 99
```

已验证：同 seed 两次运行输出 diff 为空（除时间戳行）；换 seed 后 findings 数组完全一致、抽样 ID 变化。排序键 `(path, line, col, rule, symbol)`，ID 按序分配，无随机遍历。

## Top 修复建议（按收益排序）

1. **关闭两个"自建不关"的 client**（RL-0008、RL-0028）：都是 `or` 自建分支缺 close。给宿主类补 `aclose()`/`close()` 并接入关停路径，改动小、消掉 2 条 high。
2. **补齐 update/launcher 的 Popen 句柄**（RL-0005、RL-0007、RL-0004）：`_launch_restart`/`launch_update_worker` 保存返回值并 wait 一次，顺带把子进程失败写入 job 状态，升级运维可观测性。
3. **模块级 executor 关停钩子**（RL-0027）：仿照 `deeptutor/reading/extensions.py:168` 的 `close()` 模式，提供 shutdown 并注册到应用退出。
4. **low 条目不急**：绝大多数是工厂/托管转移的"确认接收方"项，建议在 code review 时顺手核对，不单独立卡。

## 已知局限

- 静态分析不追踪跨函数/跨模块数据流：工厂返回的资源按 R9-low 标注"确认接收方"，不做跨文件验证。
- lambda 工厂体内的资源构造不产生绑定（不可静态追踪调用点管理方式）。
- `getattr()`/动态属性名、walrus 表达式不在识别范围。
