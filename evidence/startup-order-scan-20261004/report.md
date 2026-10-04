# 启动/关闭顺序与单例初始化扫描报告

- 卡片：AGEN-590（chore: 启动/关闭顺序与单例初始化扫描）
- 基线：HKUDS/DeepTutor `origin/main` @ `f07029cfc`（release: v1.6.13）
- 扫描日期：2026-10-04
- 性质：只读扫描，未修改任何代码。以下行号均基于 `f07029cfc`。

## 1. 扫描范围与方法

覆盖三条进程链路：

1. **launcher 进程**（`deeptutor_cli` → `deeptutor.runtime.launcher.start`）：信号处理、子进程树管理、atexit 清理。
2. **backend 进程**（uvicorn → `deeptutor.api.main:app`）：模块导入副作用、FastAPI lifespan、BackgroundLeaderSupervisor、各单例服务。
3. **子进程/子服务**：partners 频道线程、MCP stdio 服务器、opencode server、sandbox/codebuddy 子进程、cron/source-sync 任务。

方法：以 `deeptutor/api/main.py`、`deeptutor/runtime/launcher.py`、`deeptutor/app/container.py` 为入口，沿 import 图与生命周期调用链追踪；全局检索 `lifespan`、`signal`、`atexit`、`start_new_session`、`threading.Thread`、`asyncio.create_task`、模块级 `get_*/load_*` 单例与快照。

## 2. 初始化顺序图（文字版）

### 2.1 launcher 进程（`deeptutor runtime launcher start`）

```
python -m deeptutor start
└─ deeptutor_cli.main: cmd start (deeptutor_cli/main.py:128-149)
   └─ launcher.start() (deeptutor/runtime/launcher.py:1278)
      ├─ _relax_console_encoding (launcher.py:1285 → 271)
      ├─ get_runtime_home / validate (1286-1291)
      ├─ [detach] _launch_detached → 独立进程 (1296-1298, 1080)
      ├─ os.environ[DEEPTUTOR_HOME_ENV] (1306)
      ├─ _reset_runtime_singletons: PathService/RuntimeSettingsService/ModelCatalogService (1307 → 140-159)
      ├─ init_user_directories + ensure_runtime_settings_files + load_launch_settings (1322-1324)
      ├─ export_runtime_settings_to_env(overwrite=True) (1326)
      ├─ 端口冲突解决：交互改端口 或 kill 占用者 (1358-1363 → 526-568, 499-523)
      ├─ _install_signal_handlers(SIGINT/SIGTERM/SIGHUP/SIGBREAK → 置位标志) (1512-1515 → 1031-1066)
      ├─ atexit.register(cleanup) (1516)
      ├─ spawn backend (uvicorn deeptutor.api.main:app, --workers N) (1520)
      ├─ _wait_for_http(backend /, 默认 60s, env 可调) (1522-1529)
      ├─ spawn frontend（复用已存在的 Next dev 或新建）(1533-1555)
      ├─ _mark_detached_ready / 打开浏览器 (1558-1569)
      └─ 监控循环：stop 文件 / 子进程退出 / 待更新 handoff (1571-1581)
         finally/atexit: cleanup() → _terminate(web) → _terminate(backend)
         （SIGTERM → 等 8s → SIGKILL，按进程组）(1502-1510, 254-268)
```

### 2.2 backend 进程（uvicorn worker）

```
import deeptutor.api.main        ←—— 导入期副作用（见风险 R1-R3）
├─ ensure_runtime_settings_files() (main.py:20)
├─ export_runtime_settings_to_env(overwrite=True) (main.py:21)
├─ configure_logging() + uvicorn.error 过滤器 (main.py:22,36)
├─ app = FastAPI(lifespan=lifespan) (main.py:404-413)
├─ init_user_directories()（含兜底 except）(main.py:514-522)
└─ 各 router 模块 import（部分在模块级读 YAML：R3）

lifespan startup (main.py:105-341)
├─ app.state.ready=False
├─ validate_tool_consistency()  ←—— 失败即启动中止（尚无资源需回收）(115)
├─ get_application_container() 单例构建（含 capability 内建+插件加载）(120-126, container.py:89-93,336-348)
├─ container.start()：coordination.health() 不通过则拒绝启动 (126, container.py:122-129)
├─ install_progress_ports(broadcast, emit) (127-134)
├─ run_startup_data_migrations()（legacy chat / workspace 偏好 / 绑定；每个 worker 都执行，内部串行化）(135, legacy_migration.py:136)
├─ reconcile_linked_assessments（可失败，仅告警）(155-162)
├─ get_llm_client() 初始化（可失败，仅告警）(164-172)
├─ get_event_bus().start()（可失败，仅告警）(174-181)
├─ cron change_notifier 接线（可失败，仅告警）(268-287)
├─ BackgroundLeaderSupervisor.start()：asyncio 任务竞选 leader lease (289-312, background_leader.py:53-55,71-111)
│  └─ [仅 leader] 依序 _start_partners → _start_cron → _start_github_sync → _start_web_source_sync
│     （部分启动失败时按计数逆序调用对应 stop，background_leader.py:196-224）
├─ ping_pocketbase（可失败，仅告警）(314-320)
├─ memory v1/v2/partner 迁移（可失败，仅告警）(322-339)
└─ app.state.ready=True → yield

lifespan shutdown (main.py:344-399)
├─ ready=False；install_progress_ports(None, None)  ←—— 先摘广播端口 (345-348)
├─ background_supervisor.close()：停 4 项服务（逆序）+ 释放 leader lease (350-354, background_leader.py:57-69)
├─ application_container.close()：runtime_registry 逐 scope drain(≤60s) → coordinator.close (356-360, container.py:131-137)
├─ get_mcp_manager().shutdown()：所有 owner 的 stdio/remote 连接 (362-371, mcp/manager.py:284-290)
├─ close_runtime_provider_pool() / close_agentic_client_pool() (373-389)
└─ event_bus.stop()：队列 join ≤10s → 取消 processor (391-399, event_bus.py:167-185)
```

### 2.3 进程内常驻单例（backend）

| 单例 | 创建时机 | 释放路径 |
| --- | --- | --- |
| `PathService`（默认实例 + 按 scope 缓存） | 首次 `get_path_service()`；scope 缓存 `multi_user/paths.py:145-181` | 无显式释放；launcher 重置仅覆盖默认实例 |
| `RuntimeSettingsService` / `ModelCatalogService` `_instances` | 首次 `get_instance`（runtime_settings.py:472-502, model_catalog.py:255-267） | 仅 launcher `_reset_runtime_singletons` 清空 |
| `ApplicationContainer` `_default_container` | lifespan 首次调用（container.py:336-348） | lifespan shutdown `container.close()` |
| `EventBus`（`__new__` 单例 + 模块全局） | lifespan 或首次 `publish()` 自启（event_bus.py:69-89,101-106,197-205） | lifespan shutdown `stop()` |
| `PartnerManager` 模块全局 | 首次 `get_partner_manager`（partners/manager.py:1838-1847） | leader stop_callbacks → `stop_all` |
| `CronService` / `GitHubSourceSyncService` / `WebSourceSyncScheduler` | leader 启动时（cron/service.py:301-329, github_source/sync_service.py:65-72, web_source/scheduler.py:309-324） | leader stop_callbacks |
| SQLite 会话存储 `_instances`（按 db 路径缓存） | 首次按当前 user scope 解析（sqlite_store.py:4425-4444, session/__init__.py:14-33） | 仅 TurnLifecycle.close 关闭其经手 store（lifecycle.py:104-108） |
| `MCPManager` / `ProgressBroadcaster` / `KnowledgeTaskStreamManager` | 首次 get（mcp/manager.py, progress_broadcaster.py:14-26, task_log_stream.py:34-52） | MCP 有 shutdown；后两者为纯内存，随进程退出 |
| opencode server 池 | 首次 acquire（subagent/opencode_server.py） | 常规退出靠 atexit（197-201）；SIGKILL 时无清理 |
| LLM provider 池 / agentic 客户端池 | 首次使用（provider_factory.py:19-21, agentic/client.py:66） | lifespan shutdown 显式 close |
| 导入期即构造的实例 | 见 R4 | 无 |

## 3. 风险清单

严重度：高 = 可致进程级残留/泄漏；中 = 功能/可观测性受损；低 = 边缘场景或已有兜底。每条附触发条件；「拆卡」= 建议拆独立修复卡。

### R1（高，拆卡）lifespan 启动段异常会整体跳过 shutdown，已启动资源泄漏

- 位置：`deeptutor/api/main.py:104-342`（`@asynccontextmanager` 语义）；未捕获异常点：`validate_tool_consistency`（115）、`get_application_container`/`container.start`（120-126）、`install_progress_ports`（131-134）、`run_startup_data_migrations`（135）、`background_supervisor.start()`（312）。
- 触发条件：`container.start()` 成功后任一未捕获异常（如数据迁移抛错、supervisor.start() 抛错）→ asynccontextmanager 的 yield 前半段抛出，yield 之后的 shutdown 段（344-399）完全不执行：container 未 close、已启动的 partner/cron/sync 不停止、EventBus 不 stop，uvicorn 直接退出进程。`BackgroundLeaderSupervisor` 只对自身部分启动有补偿（background_leader.py:196-211），container 层没有对应补偿。
- 影响：多 worker 部署下重启时旧 worker 可能遗留 leader lease 过期等待、SQLite/Redis 连接未释放；opencode/MCP 等子进程依赖的 atexit（opencode_server.py:197）在 SIGKILL/异常退出链上同样不可靠。
- 建议：将 startup 段包入 try/except，失败时按 shutdown 序调用同一套清理后再 raise；或改用 Starlette `on_startup/on_shutdown` 注册表逐项登记。
- 拆卡：是（独立修复卡，含「启动失败也走清理」回归测试）。

### R2（高，拆卡）launcher 对 backend 的宽限期（8s）小于 backend 优雅关闭的真实预算（60s+）

- 位置：`deeptutor/runtime/launcher.py:254-268`（`_terminate`：SIGTERM → wait 8s → SIGKILL 进程组）；对照 `deeptutor/app/container.py:131-137`（drain_timeout 60s）、`deeptutor/services/session/turns/lifecycle.py:71-115`（活跃 turn drain）、`deeptutor/events/event_bus.py:167-185`（stop join 10s）、MCP/partner 停止耗时。
- 触发条件：launcher 收到 SIGINT/SIGTERM（或 stop 文件/更新 handoff）时 backend 正在执行长 turn → uvicorn 开始优雅关闭 → launcher 8s 后 SIGKILL：turn 被硬切断（依赖下次启动 TurnRecoveryService 恢复，container.py:139-161）；opencode 子进程的 atexit 不执行（opencode_server.py:197-201）→ 孤儿进程；以 `start_new_session=True` 脱离进程组的 sandbox/codebuddy 子进程（sandbox/backends.py:257,371,384,393；llm/provider_core/codebuddy_provider.py:808-812；office_preview.py:125）不会被 launcher 的 killpg 波及 → 若其自身超时清理未及运行则残留。
- 备注：代码已有 `has_live_executions()`（lifecycle.py:120-130）供更新链路判断在飞 turn，但 launcher 停止路径未使用。
- 建议：launcher 宽限期改为可配置并默认 ≥ drain 预算（或先轮询 `/health/ready`+容器状态再决定升级 SIGKILL）。
- 拆卡：是。

### R3（中，拆卡）导入期副作用集中在 `deeptutor.api.main` 与 router 模块，形成导入顺序依赖

- 位置：
  - `deeptutor/api/main.py:20-22`：import 即写运行时设置文件、以 `overwrite=True` 导出环境变量、重配 logging；
  - `deeptutor/api/main.py:524-526`：注释明言「Some router modules load YAML settings at import time」，实际模块级读取点：`deeptutor/api/routers/co_writer.py:44`、`knowledge.py:113`、`quiz_judge.py:24`、`question.py:26`、`deeptutor/api/routers/auth.py:105`（`load_auth_settings()` 快照）；
  - `deeptutor/services/auth.py:40-41`：`_AUTH_SETTINGS`/`_INTEGRATIONS_SETTINGS` 导入期快照，进程内不再刷新；
  - `deeptutor/api/run_server.py:17-27`：import 即设 Windows 事件循环策略、`PYTHONUNBUFFERED`、reconfigure stdout/stderr。
- 触发条件：任何先于 `ensure_runtime_settings_files()` 导入上述模块的路径（测试、工具脚本、`python -c "import deeptutor.api.main"`）会隐式创建默认设置文件或读到默认值；运行中修改 auth/路由 YAML 后必须重启进程才生效（快照语义）。`overwrite=True` 的环境导出会覆盖调用方预先设置的 OPENAI_*/端口类变量。
- 建议：把 main.py 顶层副作用收进 lifespan 或显式 `bootstrap()`；router 模块级配置改为函数内懒加载；`overwrite` 默认改为只补缺。
- 拆卡：是（可拆成「main 导入去副作用」「router YAML 懒加载」两卡）。

### R4（中，可拆卡）模块导入期即构造服务实例 / 读取运行根目录

- 位置：`deeptutor/services/config/launch_settings.py:13`、`deeptutor/services/config/loader.py:20`（`PROJECT_ROOT = get_runtime_home()` 导入期固化）；导入期实例：`deeptutor/services/partner_groups/manager.py:1622`、`partner_groups/modes.py:181`、`partner_groups/memory.py:196`、`deeptutor/services/workspace/service.py:801`、`deeptutor/services/app_update.py:654`、`deeptutor/services/notebook/service.py:709`、`deeptutor/runtime/isolated_worker.py:34`。
- 触发条件：先 import 后设置 `DEEPTUTOR_HOME` 的嵌入/CLI 用法得到过期 `PROJECT_ROOT`；launcher 的 `_reset_runtime_singletons`（launcher.py:140-159）只重置 PathService/RuntimeSettingsService/ModelCatalogService 三处，不清 `multi_user/paths.py` 的 `_path_services` scope 缓存与 `sqlite_store.py:4425` 的 `_instances`，也不覆盖上述模块全局。主链路（backend 为独立新进程）不受影响，属嵌入用法风险。
- 拆卡：是（低优先）。

### R5（中，拆卡）shutdown 一开始即摘除进度广播端口，排水期事件静默丢失

- 位置：`deeptutor/api/main.py:348`（`install_progress_ports(broadcast=None, emit_task_event=None)` 位于最前）；端口实现 `deeptutor/knowledge/progress_events.py:21-38`（None 时静默 no-op）。
- 触发条件：优雅关闭期间 `container.close()` 排水活跃 turn（最长 60s）、partner 停止、cron 收尾时发出的进度/任务事件全部无声丢弃，前端在关闭窗口内看不到任何状态变化。
- 建议：把摘端口移到 container.close 之后（或提供 `drain_only` 模式），保留排空期间的可见性。
- 拆卡：是（小卡）。

### R6（中，拆卡）`publish()` 会把已 stop 的 EventBus 重新拉起

- 位置：`deeptutor/events/event_bus.py:101-106`（`publish` 发现 `_running=False` 即 `await self.start()`）。
- 触发条件：shutdown 序后半段（或关闭窗口内存活的杂散后台任务，如 partner_groups 的 live task、cron 重叠 tick）在 `event_bus.stop()` 之后再次 publish → bus 以新 processor task 复活，随后事件循环被 uvicorn 关闭 → 「Task was destroyed but it is pending」类噪音或事件丢失。
- 建议：增加 `stopping` 状态使 stop 后 publish 直接丢弃并记 debug 日志。
- 拆卡：是（小卡）。

### R7（低，可拆卡）leader 停止回调对异常完全静默

- 位置：`deeptutor/runtime/background_leader.py:219-224`（`_stop_started_services` 对每个 stop 回调 `contextlib.suppress(Exception)`，无日志）。
- 触发条件：leadership 丢失/进程关闭时某个 partner 或 sync 服务 stop 抛错/挂起被吞 → 日志无痕迹；新 leader 接管后可能对同一 channel 重复启动。
- 建议：suppress 改为 `except Exception: logger.exception(...)`。
- 拆卡：是（一行级小卡，可与 R6 合并）。

### R8（低）多 worker 下 lifespan 每实例全量执行；已用租约与串行化兜底

- 位置：launcher 以 `--workers N` 启动（launcher.py:1474-1475）；迁移串行化说明 `deeptutor/services/session/legacy_migration.py:136`；后台服务由 leader lease 收敛（background_leader.py:71-111）。
- 触发条件：`backend_workers>1` 时每个 worker 都跑 `run_startup_data_migrations`（main.py:135）并各自构建 container/插件注册表；非 leader worker 的 partner/cron/sync 依赖 lease 不启动。行为正确但启动耗时随 worker 数线性放大；migration 文件锁等待失败时会成为 R1 的异常入口。
- 结论：设计已覆盖，不拆卡；作为 R1 修复时的测试场景保留。

### R9（低）异常退出时的状态残留盘点（多数已有恢复设计）

- launcher 分离态文件：`data/user/runtime/launcher.json` / `launcher.stop` 在 SIGKILL 后残留，但下次 `start`/`stop` 以 pid 存活检查+token 校验自愈（launcher.py:1091-1096, 1188-1195, 1201-1207）。
- turn 中断残留：由 `TurnRecoveryService.recover_once` 周期恢复（container.py:139-161，leader 每 recovery_interval 执行）。
- workspace 活动 SQLite 租约：异常退出后由 SQLite 回滚日志机制自动恢复（workspace/activity.py:12-36）。
- partner 频道线程为 daemon 线程（partners/channels/feishu.py:610、zulip.py:156、msteams.py:229）：SIGKILL 时随进程消亡，若恰在写频道状态文件（cursor/session）可能留下半写文件；写入路径普遍走 atomic write（如 launcher 侧 `atomic_write_json`），风险有限。
- SQLite 会话存储缓存 `_instances`（sqlite_store.py:4425-4431）中未经 runtime 关闭的连接靠 GC/进程退出释放：功能无损，句柄关闭时机不确定。
- 结论：不拆卡；R2 落地后残留窗口显著收窄。

### R10（低）关闭顺序中 MCP/LLM 池先于 EventBus 停止

- 位置：`deeptutor/api/main.py:350-399`（顺序：supervisor → container → MCP → provider 池 → agentic 池 → EventBus）。
- 触发条件：container 排水期间工具仍可能经 MCP/LLM 发请求（此时连接尚在，合理）；EventBus 最后停止保证容器排水期事件可处理。当前顺序自洽；仅当 R1（启动失败路径）发生时该顺序无从执行，回到 R1。
- 结论：不拆卡，记录为设计依据。

## 4. 可拆修复卡汇总

| 建议卡 | 对应风险 | 粗估规模 |
| --- | --- | --- |
| lifespan 启动失败也执行清理序列 | R1 | 中（含回归测试） |
| launcher 停止宽限期可配置并与 drain 预算对齐 | R2 | 中 |
| `deeptutor.api.main` 导入去副作用（bootstrap 化） | R3 | 中 |
| router/服务模块级配置读取懒加载 | R3/R4 | 中 |
| shutdown 保留排水期进度广播 | R5 | 小 |
| EventBus stop 后拒绝复活 | R6（可并入 R7） | 小 |
| leader stop 回调异常记日志 | R7 | 小 |

## 5. 验收对照

1. 每项风险均附 `path:line` 与触发条件 — 见第 3 节。
2. 可拆修复卡条目已逐条标注「拆卡：是/可」并汇总于第 4 节。
3. 未修改任何代码；本分支仅新增 `evidence/startup-order-scan-20261004/` 下报告与校验和。
