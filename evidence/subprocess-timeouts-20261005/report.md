# 子进程调用超时/回收缺口静态清点（deeptutor/ 全量）

- 基线：origin/main `f07029cfc`（release v1.6.13），只读新 worktree，未改任何产品代码。
- 范围：`deeptutor/` 下全部 `subprocess.run|Popen|check_output|check_call|call|getoutput|getstatusoutput` 与 `asyncio.create_subprocess_exec|create_subprocess_shell` 调用点。
- 结果：**47 个真实 spawn 点，27 个文件**（另有 1 处 grep 命中为 docstring，见口径说明）。
- 风险分级口径：
  - **HIGH**：核心用户请求/解析路径，无 timeout 且无 kill 路径，挂死即永久占用请求或后台线程。
  - **MEDIUM**：缺 timeout 或超时后不 kill（进程/管道泄漏），影响面为辅助请求、探测或一次后台任务。
  - **LOW**：短时工具调用缺 timeout，或长时任务已有部分保护仅缺升级/兜底。
  - **OK**：timeout+kill 齐备，或为有托管生命周期的常驻进程（设计如此），仅备注。
- 三类风险标注：`缺timeout` / `缺kill` / `stdout无界`（capture 进内存且无上限；由 timeout 界定或行式消费有界的注明"有界"）。

## 口径复现

### grep 口径（47 个 spawn 点）

```bash
rg -n "subprocess\.(run|Popen|check_output|check_call|call|getoutput|getstatusoutput)\(|create_subprocess_(exec|shell)\(" deeptutor --type py
# 共 48 行命中，其中 deeptutor/services/cli_apps/provider.py:356 是 docstring 引用，非调用点 → 47 个真实 spawn 点。
```

### AST 口径（交叉验证）

```bash
python3 evidence/subprocess-timeouts-20261005/audit_subprocess_ast.py deeptutor
# 遍历 deeptutor/**/*.py 的 ast.Call，匹配 subprocess.<fn> 与 asyncio.create_subprocess_*，
# 输出 path:line + 是否带 timeout= / capture 标志，用于与上表逐一比对。
# 注意：AST 的 timeout 列只看 spawn 调用自身的 timeout= 形参；Popen/create_subprocess 本就不接受
# timeout（超时在 communicate(timeout=)/wait_for 上实现），因此 async/Popen 行显示 timeout=absent
# 不代表缺口，最终判定以本报告逐条 wait-path 分析为准。两种口径命中集合一致（47 = 47）。
```

### 文件级排除说明

首次宽口径 `rg -l "subprocess|Popen|check_output|create_subprocess"` 命中 45 个文件，其中 12 个经核查仅为注释/配置/类型引用，无 spawn 点：
`agents/visualize/capability.py`、`api/routers/settings.py`、`api/run_server.py`、`capabilities/setup/jobs.py`、`services/config/{runtime_settings,settings_profile,settings_spec}.py`、`services/cli_apps/provider.py`、`services/llm/provider_core/codebuddy_models.py`、`services/sandbox/{config,service}.py`、`services/workspace/execution.py`。

### 去重

- 与 scan-async-tasks（async 任务轴）、scan-void-promises（JS 轴）、scan-lock-usage（锁轴）无重叠：本卡只覆盖子进程 spawn/等待/回收。
- fix-lightrag-worker-loop 为 LightRAG worker 个例，deeptutor/ 内 LightRAG 相关文件无 subprocess 调用点，无重叠。
- 相邻发现（超出本卡口径，仅记录）：`services/subagent/claude_models.py:167` 的 `os.execvp` 发生在 fork 出的 PTY 子进程内做重 exec，不属于本轴统计对象。

## 风险清单

### HIGH（4）——核心路径无 timeout、无 kill，挂死即永久占用

| # | 位置 | 调用 | 缺失项 | 说明与建议修复卡 |
|---|------|------|--------|------------------|
| H1 | `deeptutor/agents/math_animator/renderer.py:170` | `Popen`（manim 渲染，线程泵 stdout/stderr） | 缺timeout、缺kill、stdout无界(`stdout_lines`/`stderr_lines` 全量累积) | manim 挂起时 `queue.get()` 循环与 `process.wait()` 永久阻塞，渲染请求永不返回。修复卡：整次渲染加 wall-clock 上限 + 超时 kill 进程组 + 截断输出缓存。 |
| H2 | `deeptutor/services/parsing/engines/docling/local_worker.py:52` | `Popen`（Docling 隔离 worker，行式读 stdout） | 缺timeout、缺kill(仅异常路径可达) | `for raw_line in process.stdout` 阻塞时永不抛异常，`_stop_worker` 的 kill 分支不可达。内存有界（`deque(maxlen)`）。修复卡：加解析级超时看门狗（计时器读超时→terminate→kill）。 |
| H3 | `deeptutor/services/parsing/engines/mineru/local.py:216` | `Popen`（MinerU 解析主路径，行式读 stdout） | 缺timeout、缺kill(仅异常路径可达) | 同 H2 模式：子进程无输出挂起时阻塞在 stdout 迭代，`finally` 的 terminate/kill 只在异常时执行。tail 有界（`deque(maxlen=40)`）。修复卡：同 H2，解析总超时 + 看门狗 kill。 |
| H4 | `deeptutor/capabilities/audio_overview/pipeline.py:140` | `subprocess.run`（ffmpeg 解码为 raw PCM） | 缺timeout、kill 由 run() 兜底但无上限、**stdout无界** | `capture_output=True` 且 stdout 为原始 PCM（`-f s16le pipe:1`）：音频时长无上限 → 内存随时长线性膨胀（1 小时 ≈170MB）；且无 timeout，ffmpeg 挂起时任务永久卡住。修复卡：stdout 落盘临时文件（或加 `-t`/分段上限）+ run(timeout=…)。 |

### MEDIUM（8）——缺 timeout 或超时后不回收

| # | 位置 | 调用 | 缺失项 | 说明与建议修复卡 |
|---|------|------|--------|------------------|
| M1 | `deeptutor/services/llm/provider_core/codebuddy_provider.py:817` | `create_subprocess_exec` + 裸 `await process.communicate()` | 缺timeout、缺kill、stdout无界(有 timeout 即可界定) | CodeBuddy 模型目录探测（settings/工厂 `fetch_models` 链路，上游 `codebuddy_models.py`、`llm/factory.py:735` 均无外层 wait_for）。CLI 挂起 → 请求永久挂起。修复卡：`asyncio.wait_for(communicate(), T)` + 超时 kill。 |
| M2 | `deeptutor/agents/math_animator/visual_review.py:83` | `create_subprocess_exec`（ffprobe 抽帧） | 缺timeout、缺kill | 裸 `await process.communicate()`；属 manim 渲染请求路径。修复卡：wait_for + kill（同 M1 模式）。 |
| M3 | `deeptutor/agents/math_animator/visual_review.py:107` | `create_subprocess_exec`（ffprobe 时长探测） | 缺timeout、缺kill | 同 M2。 |
| M4 | `deeptutor/services/voice/adapters/dashscope.py:288` | `create_subprocess_exec`（ffmpeg 转码用户上传音频） | 缺timeout、缺kill | 裸 `await process.communicate()`；对比 `voice/audio.py:45` 已有 wait_for(60)+kill，此处分叉未同步。修复卡：对齐 audio.py 的 wait_for+kill 模式。 |
| M5 | `deeptutor/services/parsing/engines/mineru/local.py:85` | `subprocess.run`（`mineru --version` 探测） | 缺timeout、stdout无界(有界即可) | 探测挂在解析入口；run() 无 timeout 时不 kill。修复卡：`timeout=10`（参考 `mineru/backend.py:170` 已带 timeout 参数）。 |
| M6 | `deeptutor/services/parsing/engines/mineru/local.py:99` | `subprocess.run`（`magic-pdf --version` 探测） | 缺timeout、stdout无界(有界即可) | 同 M5。 |
| M7 | `deeptutor/capabilities/audio_overview/pipeline.py:167` | `subprocess.run`（ffmpeg 编码 mp3） | 缺timeout | 输出落盘、stdout 量小；挂起时任务卡死。修复卡：加 timeout。 |
| M8 | `deeptutor/services/subagent/models.py:293` | `create_subprocess_exec`（CLI list-models） | 缺kill(超时路径)、stdout无界(由 20/60s 界定) | `wait_for` 超时后直接 `return []`，不 kill 进程：CLI 进程与管道泄漏，超时频繁时累积。修复卡：超时分支补 kill+wait（参考 `subagent/process.py:124 _terminate`）。 |

### LOW（7）——局部缺口或兜底升级缺失

| # | 位置 | 调用 | 缺失项 | 说明 |
|---|------|------|--------|------|
| L1 | `deeptutor/services/cron/executor.py:57` | `create_subprocess_exec`（osascript 通知） | 缺kill(wait_for 超时后) | `wait_for(…, timeout=5)` 超时被宽 `except Exception` 吞掉，进程不 kill；正常秒回，泄漏概率低。 |
| L2 | `deeptutor/runtime/launcher.py:240` | `subprocess.run`（taskkill 树信号转发，Win） | 缺timeout | stop 路径上的工具调用；taskkill 挂起会卡停机流程。 |
| L3 | `deeptutor/runtime/launcher.py:705` | `subprocess.run`（npm install/action，前台 CLI） | 缺timeout | 输出继承终端、用户可 Ctrl-C；挂起表现为 start 卡住。 |
| L4 | `deeptutor/runtime/launcher.py:801` | `subprocess.run`（npm run build，前台 CLI） | 缺timeout | 同 L3。 |
| L5 | `deeptutor/runtime/update_worker.py:68` | `subprocess.run`（pip 安装，更新 worker 内） | 缺timeout | 输出写 log 文件（磁盘）；pip 挂起无看门狗，更新交接状态永久 running。 |
| L6 | `deeptutor/services/parsing/engines/_install.py:197` | `Popen`（后台 pip/模型安装） | cancel 仅 terminate，无 kill 升级/无 wait | 行式消费 + `_MAX_LINES` 截断，内存有界；SIGTERM 不退的子进程会滞留。修复卡：cancel 升级 terminate→wait(5)→kill。 |
| L7 | `deeptutor/services/parsing/engines/mineru/models.py:123` | `Popen`（后台模型下载） | cancel 仅 terminate，无 kill 升级/无 wait | 同 L6（`models.py:155 cancel`）。 |

### OK（28）——timeout/kill 齐备或常驻托管设计

| 位置 | 要点 |
|------|------|
| `deeptutor/runtime/isolated_worker.py:130` | 同步 Popen：`communicate(timeout)` → kill → 复读管道，模范实现。 |
| `deeptutor/runtime/isolated_worker.py:185` | 异步：`wait_for` + `_stop_async_process`，CancelledError 下 `shield` 停进程，模范实现。 |
| `deeptutor/runtime/launcher.py:343` / `:371` / `:401` / `:972` | lsof/netstat/tasklist/ps，timeout=2–5s。stdout 由 timeout 界定（理论无界，实际极小）。 |
| `deeptutor/services/office_preview.py:110` | Popen soffice：`communicate(timeout)` → `killpg(SIGKILL)`，处理了 soffice.bin 进程组。 |
| `deeptutor/services/voice/audio.py:45` | wait_for(60s) → kill → wait。 |
| `deeptutor/services/subagent/process.py:76` | 常驻 agent 流：`finally` `_terminate`（terminate→wait 优雅期→kill）；生命周期随消费方断开。stdout 行式消费有界。 |
| `deeptutor/services/subagent/process.py:164` | 探测：wait_for + `_terminate`。 |
| `deeptutor/services/subagent/opencode_server.py:108` | 常驻 serve：ready 超时 → terminate；TTL reaper + atexit 兜底（`_terminate_sync`/`:192` kill 升级）。 |
| `deeptutor/services/cli_apps/installer.py:259` | timeout + TimeoutExpired 显式转 124；备注：无树 kill（pip 直启子进程，风险低）。 |
| `deeptutor/services/skill/hub.py:629` | `timeout=_FETCH_CMD_TIMEOUT`；stdout 由 timeout 界定。 |
| `deeptutor/reading/ingestion.py:1015` / `:1067` / `:1090` | timeout=3600/120/120；stdout 由 timeout 界定。 |
| `deeptutor/services/parsing/engines/mineru/backend.py:170` | timeout 参数化传入。 |
| `deeptutor/tools/github_query.py:206` | wait_for → kill → wait；stdout/stderr 由 timeout 界定。 |
| `deeptutor/services/sandbox/backends.py:253` / `:365` / `:374` / `:387` / `:464` | `_communicate`：`_capture_limited` 有界采样 + wait_for + `_terminate_process_tree`（taskkill 兜底 kill）。 |
| `deeptutor/services/sandbox/runner/server.py:233` | timeout 传入；备注：shell=True 为该 runner 契约、超时 kill 的是 shell 直子进程（孙进程在沙箱内，容器边界兜底）；capture 由 timeout 界定。 |
| `deeptutor/runtime/launcher.py:317` | 常驻托管服务进程：行式泵 stdout（有界）、`_terminate`/树信号停机；无 timeout 为设计。 |
| `deeptutor/runtime/launcher.py:1133`、`deeptutor/services/app_update.py:651`、`deeptutor/runtime/update_worker.py:98` | 分离式（detached）启动：stdout→log 文件、`start_new_session`/DETACHED_PROCESS，设计即不等待。 |

## 可拆修复卡（按收益排序）

1. **卡 A（HIGH，manim 渲染链）**：`renderer.py` 渲染总超时 + 进程组 kill + 输出缓存截断；顺带修 `visual_review.py:83,107`（wait_for+kill）。同一模式一次改完。
2. **卡 B（HIGH，解析 worker 超时看门狗）**：`docling/local_worker.py` 与 `mineru/local.py:216` 增加解析级超时（可读 settings），超时走既有 terminate→kill 路径；同时补 `mineru/local.py:85,99` 版本探测 timeout=10。
3. **卡 C（HIGH，audio_overview 内存/超时）**：`pipeline.py:140` raw PCM stdout 改落盘或加时长上限，`pipeline.py:140,167` 加 timeout。
4. **卡 D（MEDIUM，超时后泄漏三处）**：`codebuddy_provider.py:817`、`dashscope.py:288` 补 wait_for+kill（各 ≤10 行）；`subagent/models.py:293` 超时分支补 kill。
5. **卡 E（LOW，cancel 升级）**：`_install.py` 与 `mineru/models.py` 的 cancel() 统一升级为 terminate→wait(5)→kill；`cron/executor.py:57` 超时分支补 kill；`launcher.py:240` taskkill 加 timeout。
6. **卡 F（LOW，CLI 装构建超时）**：`launcher.py:705,801` 与 `update_worker.py:68` 加长上限 timeout（如 1800s），超时给出可读错误；属体验加固。

## 验收对照

1. 覆盖全部调用点：47/47（grep 48 命中 − 1 docstring；AST 脚本可复跑比对，27 个文件）。
2. 每条目含 path:line 与缺失项标注（缺timeout/缺kill/stdout无界）。
3. 只读：本分支仅含 `evidence/` 交付物，未改任何产品代码。
