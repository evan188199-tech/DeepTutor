# 沙箱子系统导读（services/sandbox：service / backends / runner / artifacts）

- 基线：origin/main `f07029cfc`（v1.6.13）。所有 `path:line` 均基于该基线，行号会随演进漂移，以符号名为准。
- 范围：`deeptutor/services/sandbox` 全模块、其 runner sidecar（`runner/server.py`）、产物收集（`artifacts.py`），以及上游门控/消费方（exec 工具、pipeline 策略门、skill 门、cli_apps）中与沙箱契约相关的部分。
- 去重说明：CLI 应用安装与白名单体系见 cli_apps 自身导读（如有）；workspace 内容服务与 `outputs/` 呈现链见 workspace 相关文档。本文只覆盖"一次不可信命令如何被隔离执行、限额与产物如何回流"。

## 1. 模块地图

| 角色 | 文件 | 关键符号 |
| --- | --- | --- |
| 值类型（零依赖） | `deeptutor/services/sandbox/spec.py:16-30` | `IsolationLevel`（SYSTEM/APPLICATION/OFF，`rank()` `spec.py:29-30`） |
| 请求/结果 | `deeptutor/services/sandbox/spec.py:52-95` | `ExecRequest`（argv 双拼一致性校验 `spec.py:78-87`；`of_argv` `spec.py:89-95`） |
| 结果渲染 | `deeptutor/services/sandbox/spec.py:98-132` | `ExecResult.ok/render`（`spec.py:108-132`） |
| 限额声明 | `deeptutor/services/sandbox/spec.py:33-40` | `ResourceLimits`（timeout 30s / mem 512MB / 输出 1 万字符 / CPU 30s） |
| 配置与后端选择 | `deeptutor/services/sandbox/config.py:66-84` | `build_backend`（runner URL → Linux bwrap → 显式 opt-in subprocess → None） |
| 设置来源 | `deeptutor/services/sandbox/config.py:49-63` | `SandboxSettings.from_env`（4 个 env：`config.py:32-38`） |
| 每用户配额 | `deeptutor/services/sandbox/quota.py:27-75` | `UserExecQuota.acquire`（并发信号量 + 60s 滑动窗口，`quota.py:41-48,60-75`） |
| 服务门面 | `deeptutor/services/sandbox/service.py:33-129` | `SandboxService`（健康探测缓存 `service.py:49-68`；降级 `service.py:70-97`；`run` `service.py:108-129`） |
| 后端基类 | `deeptutor/services/sandbox/backends.py:37-47` | `SandboxBackend`（`level` + `exec` + `health`） |
| runner sidecar 后端 | `deeptutor/services/sandbox/backends.py:74-136` | `RunnerSidecarBackend`（HTTP `/exec` `backends.py:83-127`；`/health` `backends.py:129-136`） |
| bwrap 后端 | `deeptutor/services/sandbox/backends.py:139-283` | `BwrapBackend`（argv 构建 `backends.py:197-248`；探活 `backends.py:267-283`） |
| 受限子进程后端 | `deeptutor/services/sandbox/backends.py:286-401` | `RestrictedSubprocessBackend`（白名单 env `backends.py:315-332`；Win PowerShell `backends.py:334-358`） |
| 进程树终止 | `deeptutor/services/sandbox/backends.py:446-478` | `_terminate_process_tree`（POSIX killpg `backends.py:450-459`；Win taskkill /T /F `backends.py:461-478`） |
| 输出捕获/超时 | `deeptutor/services/sandbox/backends.py:404-443,481-506` | `_capture_limited`（头尾采样）；`_communicate`（超时→杀树，`backends.py:494-501`） |
| runner 服务端 | `deeptutor/services/sandbox/runner/server.py:180-266` | `execute`（唯一真正执行不可信 shell 的函数，`server.py:232-244`） |
| runner HTTP 层 | `deeptutor/services/sandbox/runner/server.py:298-353` | `_Handler`（GET /health、POST /exec、4MB 请求上限 `server.py:78,334-336`） |
| runner rlimit | `deeptutor/services/sandbox/runner/server.py:110-151` | `_build_preexec_fn`（RLIMIT_AS/CPU/NOFILE，`server.py:134-149`） |
| runner workdir 门 | `deeptutor/services/sandbox/runner/server.py:157-177` | `_workdir_violation`（realpath 白名单） |
| 产物发现 | `deeptutor/services/sandbox/artifacts.py:18-38` | `_visible_files`（跳过隐藏/符号链接） |
| 产物快照 | `deeptutor/services/sandbox/artifacts.py:73-97` | `snapshot_public_artifact_files`（执行前签名） |
| 产物收集 | `deeptutor/services/sandbox/artifacts.py:121-193` | `collect_public_artifact_batch`（delta + outputs/ 门 + URL 铸造 `artifacts.py:154-177`） |
| exec 工具 | `deeptutor/tools/exec_tool.py:36-383` | `ExecTool`（拒绝清单 `exec_tool.py:19-30,193-195`；源码/ shell 双路径 `exec_tool.py:192-298`） |
| 运行时注入 | `deeptutor/agents/_shared/tool_runtime.py:44-105` | `bind_workspace_tool_runtime`（`_sandbox_*` 私有 kwargs `tool_runtime.py:63-101`） |
| 策略门 | `deeptutor/agents/loop/pipeline.py:695-722` | `_exec_allowed`（SYSTEM 全员 / APPLICATION 管理员 / OFF 关闭） |
| 每用户覆写 | `deeptutor/multi_user/tool_access.py:89-93` | `exec_override`（grant 三态 `multi_user/grants.py:98-107`） |
| skill 门 | `deeptutor/services/skill/service.py:205-216` | `_sandbox_available`（`requires.sandbox`，fail closed） |
| cli 消费方 | `deeptutor/services/cli_apps/runner.py:46-89` | `run_app`（argv-only 调用 `runner.py:76-84`） |
| 部署 | `docker-compose.yml:138-200` | `sandbox-runner` 服务（只读根 fs、cap_drop ALL、pids/mem 限额 `docker-compose.yml:186-197`）；`Dockerfile.runner` |

## 2. 分层职责

- **spec（L0）**：纯值类型，无后端依赖，供后端与 skill/exec 层共同引用（`spec.py:1-6`）。`ExecRequest` 用 `__post_init__` 强制 `command == shlex.join(argv)`（`spec.py:83-87`），使"argv 精确执行 + shell 字符串兼容旧 runner"的滚动部署契约不可能被调用方写歪。
- **backends（L1）**：每个隔离机制一个类，`level` 自报强度。共同契约：`exec` 不因命令失败抛异常，只把"沙箱信封级"失败放进 `ExecResult.error`（`backends.py:42-43`；runner 侧同约定 `server.py:39-40,183-185`）。
- **quota（L1）**：进程内每用户并发信号量 + 60 秒滑动窗口（`quota.py:1-14`）。单容器部署够用；多副本需换共享存储（`quota.py:11-12` 注释自认）。
- **service（L2）**：唯一门面。持有选定后端、缓存一次性健康探测、bwrap→subprocess 降级、配额与每用户覆写兜底（`service.py:3-13`）。全局单例 `get_sandbox_service`/`reset_sandbox_service`（`service.py:132-145`）。
- **runner/server（L1'，独立容器）**：标准库 HTTP 服务，主应用永不亲自执行不可信 shell（`server.py:1-7`）；容器本身已去权（non-root、cap_drop ALL、只读根 fs，`server.py:11-14` 与 `docker-compose.yml:186-197`），进程内再加 rlimit 二道防线（`server.py:110-151`）。
- **artifacts（横切）**：与执行解耦的产物发现/收集，供 exec 工具、cli_apps、media_gen 共用（`artifacts.py:100-118`；消费方 `deeptutor/tools/media_gen_tool.py:103`）。

## 3. 执行链路（一次 exec 的时序）

1. **模型调用 exec 工具**：`ExecTool.execute` 分流 shell/源码（`exec_tool.py:182-190`）。shell 先过 `_DENY_PATTERNS` 黑名单（`exec_tool.py:19-30,193-195`）；源码语言落到 `main.py/main.c/main.cpp` 模板（`exec_tool.py:39-43`）。
2. **服务端注入私有 kwargs**：`bind_workspace_tool_runtime` 为 `exec`/cli 工具注入 `_sandbox_user_id/_sandbox_workdir/_sandbox_mounts/_sandbox_env/_workspace_id`（`tool_runtime.py:63-101`）。workdir 固定在 turn 输出目录的 `exec/` 子目录，内部状态藏于 `.deeptutor/execution`（`tool_runtime.py:73-82`）——"在哪跑"由 pipeline 决定，工具不能自选（`cli_apps/provider.py:209-213` 注释）。工作目录是否可写由 compose 的卷布局保证（runner 只挂 `outputs/` 可写，`docker-compose.yml:172-180`）。
3. **门控（装配期）**：`_exec_allowed` 按有效隔离级别放行——SYSTEM 对所有人（除非 grant 显式 `exec_enabled=False`），APPLICATION 仅管理员/partner，OFF 直接关闭；门自身异常时 fail closed（`pipeline.py:703-722`）。skill 的 `requires.sandbox` 走同步探测 `exec_capability_available`（`skill/service.py:205-216`；`service.py:148-158`）。
4. **门控（执行期兜底）**：`SandboxService.run` 内再查一次 `exec_override()`，防绕过 pipeline 的直连路径（`service.py:114-123`）；该检查异常时记 warning 并**继续放行**（fail-open，见 §6 N1）。
5. **健康与降级**：`_ensure_healthy` 首次探测后永久缓存（`service.py:52-57`）。bwrap 不健康且 `DEEPTUTOR_SANDBOX_ALLOW_SUBPROCESS=1` 时降级为受限子进程；runner 不健康**绝不**降级到进程内执行（`service.py:70-97`，测试锚点 `tests/services/sandbox/test_sandbox.py:391-402`）。
6. **配额**：`quota.acquire` 先查并发（信号量打满即拒）再记速率（`quota.py:60-75`）；超限转成 `ExecResult(error=...)`（`service.py:124-127`）。lease 必须用 `async with` 释放（`quota.py:50-58,63-67`）。
7. **后端执行**（三选一，`config.py:75-84`）：
   - **RunnerSidecarBackend**：POST JSON 到 `<runner>/exec`，HTTP 超时=命令超时+15s 让 runner 回报干净超时（`backends.py:108-113`）；`httpx.HTTPError` → `error="runner unavailable: ..."`（`backends.py:119-120`）。
   - **BwrapBackend**：组装 bwrap argv——`--die-with-parent --unshare-all`、只读挂系统目录、只挂请求 mounts 与当前 venv/base Python 运行时根（`backends.py:197-248`）；argv 请求直接 exec 无 shell，shell 请求走 `/bin/sh -c`（`backends.py:243-247`）。
   - **RestrictedSubprocessBackend**：白名单 env + 请求 env（`backends.py:315-332`）；POSIX 用 `/bin/sh`，Win 强制 PowerShell UTF-8（`backends.py:373-394`）。
8. **超时与进程树**：本地后端经 `_communicate`——三任务并发收流+等退出，超时则取消任务、`_terminate_process_tree`（POSIX 先 `killpg` 整组、失败退回单杀；Win 用 `taskkill /T /F`），结果 `timed_out=True, exit_code=124`（`backends.py:481-506,446-478`）。runner 侧由 `subprocess.run(timeout=)` 超时，回传已捕获的部分输出（`server.py:245-255`）。
9. **产物回流**：执行前 `_execute_shell/_execute_source` 已对 workdir 做签名快照（`exec_tool.py:202,245`）；执行后 `_render_result` 用 `collect_public_artifact_batch(changed_since=快照)` 收集 delta（`exec_tool.py:317-326`）。收集器逐文件过双门：workspace 模式要求 `outputs/` 前缀（`artifacts.py:157-165`），路径服务模式要求 `is_public_output_path` + 相对 public 根（`artifacts.py:166-177`）。产物进 metadata 与 sources，同时 `render_artifacts_for_tool` 生成带呈现状态的模型可见文本（`artifacts.py:196-235`；`exec_tool.py:340-347`）。

**argv 双拼契约**：请求同时带 `command`（shell 串）与 `argv`（向量），runner 端 `argv or command` + `shell=not argv`（`server.py:233-237`）；旧镜像忽略未知字段回退 shell 串，两个方向的滚动部署都保持"正确执行"而非"错误执行"（`spec.py:60-67`、`backends.py:84-88`、`server.py:42-48`）。cli_apps 是唯一"程序固定、参数来自模型"的路径，因此**只**用 `of_argv`（`cli_apps/runner.py:1-12,76-84`）。

## 4. 资源限制与产物链

**限额三层**：
1. 请求级 `ResourceLimits`（默认 30s/512MB/1 万字符/CPU 30s，`spec.py:33-40`）。exec 工具把模型给的 timeout 钳到 [1,300]s（`exec_tool.py:32-33,172-180`）；cli_apps 默认 120s 上限 600s（`cli_apps/runner.py:24-25,92-99`）。
2. runner 进程级 rlimit：`RLIMIT_AS`（虚内存，JVM 类运行时可能误伤，仅二级防线）、`RLIMIT_CPU`、`RLIMIT_NOFILE=4096`，fork 后 exec 前生效（`server.py:110-151`）；调用缺省时回落到与 spec 相同的默认（`server.py:82-85,225-228`）。
3. 容器级 cgroup：compose `pids_limit: 256`、`mem_limit: 1g` 是内存权威兜底（`docker-compose.yml:192-197` 注释）；runner 无主机端口映射，仅内网可达（`docker-compose.yml:181-184`）。

输出双端各自截断：本地 `_capture_limited` 字节级头尾采样（`backends.py:404-443`）；runner `_truncate_head_tail` 字符级（`server.py:97-107`）；模型面再由 `ExecResult.render` 兜底（`spec.py:112-132`）。

**产物链要点**：快照签名=(size, mtime_ns, ctime_ns)（`artifacts.py:92-96`）；`changed_since` 过滤让"本轮新建/修改"才上报（`artifacts.py:154-156`）；隐藏文件与符号链接从发现层就排除（`artifacts.py:30-31`），`.deeptutor` 内部目录因此天然不外泄（`artifacts.py:76-78`）；URL 只在路径服务模式铸造（`/files/outputs/` + quote，`artifacts.py:174-176`），workspace 模式 URL 留空、以 workspace 相对路径呈现（`artifacts.py:162-165`）；`max_files=50` 截断但保留 `total_count` 与 `truncated` 标志（`artifacts.py:61-70,190-193`）。

## 5. 生命周期与失败语义

- **后端选择是静态的**：`build_backend` 只按配置形状选候选（`config.py:66-84`），存活性由首次 `health()` 惰性确认（`config.py:69-72` 注释）。健康结果**永久缓存**：runner 一度不可达后即使恢复，本进程也不会再探测，需 `reset_sandbox_service()`（仅测试/配置重载调用，`service.py:142-145`）。
- **降级矩阵**：bwrap 坏 + 允许 subprocess → 降 APPLICATION 级并继续（`service.py:70-97`）；bwrap 坏 + 不允许 → OFF、`run` 返回健康详情错误（`service.py:112-113`，测试 `test_sandbox.py:374-388`）；runner 坏 → 保持 OFF，不进程内执行（测试 `test_sandbox.py:391-402`）。
- **error vs 命令失败**：`error` 仅表沙箱信封失败（无后端、配额、策略、runner 不可达、spawn 失败、坏请求）；命令非零退出走 `exit_code/stderr`。`ok = 无 error 且未超时`（`spec.py:106-110`）。`ToolResult.success` 还要求 `exit_code == 0`（`exec_tool.py:364-366`）。
- **超时语义不对称**：runner 超时回传已捕获的部分输出（`server.py:245-255`）；本地后端超时丢弃缓冲的 stdout/stderr（任务被 cancel，`backends.py:494-501`），只回 `timed_out`。见 §6 N5。
- **配额是进程内的**：键为 user_id，互不挤占（`quota.py:12-13`）；单例服务存活期内窗口不持久。

## 6. 吞错位置（对照 DT-22 LOW）与新增观察

DT-22 附录 A（分支 `agent/dt22-todo-scan`，report §7）共列 13 条本模块 LOW 条目；**全部在 f07029cfc 基线逐条核实存在且行号一致**（下表行号即基线行号）：

| # | 位置 | 吞掉 | 语义 | 评估 |
| --- | --- | --- | --- | --- |
| D1 | `deeptutor/services/sandbox/artifacts.py:26` | OSError→continue | 目录不可扫描即跳过 | 可接受（尽力发现），无日志 |
| D2 | `deeptutor/services/sandbox/artifacts.py:37` | OSError→continue | 单条目 stat 失败跳过 | 同上 |
| D3 | `deeptutor/services/sandbox/artifacts.py:90` | OSError,ValueError→continue | 快照单文件失败跳过 | 可接受 |
| D4 | `deeptutor/services/sandbox/artifacts.py:152` | OSError,ValueError→continue | 收集单文件失败跳过 | 同上 |
| D5 | `deeptutor/services/sandbox/artifacts.py:160` | ValueError→continue | 文件不在绑定根内跳过 | 安全门语义，正确 |
| D6 | `deeptutor/services/sandbox/artifacts.py:171` | ValueError→continue | 不在 public 根内跳过 | 同上 |
| D7 | `deeptutor/services/sandbox/backends.py:455` | ProcessLookupError,PermissionError→pass | 组杀失败退回单杀 | 正确降级，但无日志 |
| D8 | `deeptutor/services/sandbox/backends.py:515` | UnicodeDecodeError→pass | UTF-8 失败转编码链 | 正确 |
| D9 | `deeptutor/services/sandbox/backends.py:521` | LookupError,UnicodeDecodeError→continue | 编码逐个尝试 | 正确 |
| D10 | `deeptutor/services/sandbox/runner/server.py:136` | ValueError,OSError→pass | RLIMIT_AS 设置失败静默 | **限额失效无感知**（仅 cgroup 兜底） |
| D11 | `deeptutor/services/sandbox/runner/server.py:142` | ValueError,OSError→pass | RLIMIT_CPU 设置失败静默 | 同上（wall-clock 超时仍在） |
| D12 | `deeptutor/services/sandbox/runner/server.py:148` | ValueError,OSError→pass | RLIMIT_NOFILE 失败静默 | 同上 |
| D13 | `deeptutor/services/sandbox/runner/server.py:367` | KeyboardInterrupt→pass | Ctrl-C 正常退出 | 正常（finally 有 server_close） |

DT-22 未覆盖、本导读新增的观察（供修复卡参考，非 DT-22 条目）：

- **N1** `deeptutor/services/sandbox/service.py:122-123`：每用户 exec 策略兜底检查异常时**fail-open**（记 warning 后继续执行）。与 pipeline 门的 fail closed（`pipeline.py:721-722`）方向相反；若 `multi_user.tool_access` 导入损坏，直连路径将失去覆写门。可议：改为 fail closed 或至少记 error 级。
- **N2** `deeptutor/services/sandbox/backends.py:473-474`：Win 路径 `taskkill` 等待超时被 `suppress`，终止结果未验证即返回（仅 Windows）。
- **N3** `deeptutor/services/sandbox/backends.py:499-500`：杀树后 5s 等待退出被 `suppress`，超时则子进程未被 wait（僵尸直至父进程退出）；与 launcher 导读 R1 同型。
- **N4** `deeptutor/services/sandbox/quota.py:71`：读私有属性 `sem._value` 判断并发满，属实现耦合（升级 asyncio 可能静默失效）。
- **N5** `deeptutor/services/sandbox/backends.py:494-501`：本地后端超时丢弃部分输出（对照 runner 保留，`server.py:245-255`）——排障时"本地能看到、容器里看不到"的体验差异来源。

## 7. 测试空白（现有覆盖 → 未测分支）

现有覆盖：后端选择三分支（`tests/services/sandbox/test_sandbox.py:30-56`）、bwrap 挂载矩阵含 uv/conda（`test_sandbox.py:58-163`）、受限子进程超时/截断/杀树（`test_sandbox.py:266-309`）、服务禁用/降级/不降级矩阵（`test_sandbox.py:312-402`）、配额两限（`test_sandbox.py:406-428`）、runner `execute()` 形状/截断/workdir 穿越（`test_sandbox.py:442-490`）、argv 全链 hostile-args 表（`tests/services/sandbox/test_argv_exec.py:30-189`）、exec 工具产物上报（`tests/core/test_builtin_tools.py:58-128`）。

未测/空白（补测卡定位）：

1. **artifacts.py 零直测**：`tests/services/sandbox/` 下无任何针对 `_visible_files` 隐藏/符号链接/扫描失败分支、快照 delta、`outputs/` 门、`max_files` 截断（`total_count`/`truncated`）、`render_artifacts_for_tool` 两种呈现态的单测；仅经 workspace 集成测试间接触达（`tests/services/workspace/test_content_workspace.py`）。**本模块最大空白**。
2. `RunnerSidecarBackend.exec` 的 HTTP 失败路径 `backends.py:119-120`（runner 不可达→error）与非 JSON 响应——无测试（现有 mock 仅覆盖成功响应，`test_argv_exec.py:87-124`）。
3. `BwrapBackend.exec` 的 `FileNotFoundError` 分支 `backends.py:259-260`（bwrap 中途消失）——无测试。
4. `_terminate_process_tree` 组杀失败退回单杀分支 `backends.py:457-458` 与 Win taskkill 路径 `backends.py:461-478`——无测试。
5. `SandboxService.run` 的 `QuotaExceeded→ExecResult(error)` 映射 `service.py:126-127`——配额仅单测，服务层未测。
6. `_try_subprocess_fallback` 中 fallback.health() 抛异常分支 `service.py:83-85`——降级矩阵的三个测例（`test_sandbox.py:357-402`）均未覆盖此分支。
7. runner HTTP 层（`_Handler`）：400 坏 Content-Length `server.py:330-333`、413 超限 `server.py:334-336`、坏 JSON `server.py:337-344`、兜底 crash guard `server.py:346-352`——只测了 `execute()` 纯函数。
8. `ExecTool._DENY_PATTERNS` 拦截（`exec_tool.py:193-195`）与 `_resolve_language` 拒绝（`exec_tool.py:166-170`）——全仓无 `command_blocked` 断言。
9. `main()`（`server.py:356-370`）与 `exec_capability_available`（`service.py:148-158`）——前者需起服务（可不动），后者无断言。

## 8. 扩展点

- **新隔离后端**：继承 `SandboxBackend`（`backends.py:37-47`），声明 `level`，实现 `exec`/`health`（错误进 `ExecResult.error` 不抛）；在 `build_backend` 加选择分支（`config.py:75-84`）；如需用户可配，加 `SandboxSettings` 字段与 env（`config.py:32-63`）。
- **限额/配额调整**：默认限额改 `ResourceLimits`/`server.py:82-89`；配额默认与 env 见 `config.py:35-38,61-62`；多副本部署需把 quota 换共享存储（`quota.py:11-12`）。
- **产物面扩展**：新产物形态只需让文件落在被发现的可见路径下并满足两道门之一（workspace `outputs/` 前缀或 `is_public_output_path`）；`SandboxArtifactBatch` 的 total/truncated 契约要保持（`artifacts.py:61-70`）。
- **runner 协议演进**：保持"command+argv 双拼同时下发、argv 优先"的兼容规则（`backends.py:84-88`、`server.py:42-48`）；新增字段必须容忍旧镜像忽略（未知字段不计较），新增校验走 `_error_result` 只进 `error`（`server.py:287-295`）。
- **策略收紧点**：若要废除 N1 的 fail-open，`service.py:117-123` 是唯一落点；健康缓存若要 TTL 化，`service.py:52-57` 是唯一落点。
