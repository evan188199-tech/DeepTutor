# guide: deeptutor/app 装配层导读（facade / container / engine / contracts / service）

基线：origin/main `6cf793bd868ba5ecbe64722936d4be8fab5a01df`（v1.6.14）。
本导读只覆盖 **app 装配轴**：进程级依赖如何组装、生命周期如何推进、回合协议在
`deeptutor/app/` 边界上进出什么。运行时轴（orchestrator/lease/CAS 细节）见 guide-runtime，
会话轴（TurnRuntimeManager 内部）见 guide-session-turns，本文只在边界处引用两者。

## 0. 模块构成与公共面

- `deeptutor/app/__init__.py:3-6` 导出 5 个符号：`ApplicationContainer`、`TurnEngine`、
  `DeepTutorApp`/`TurnRequest`、`TurnApplicationService` 与两个工厂函数——CLI/SDK 的唯一入口。
- `deeptutor/app/contracts.py:3-13` 把回合请求契约（`TurnRequest` 等）从
  `deeptutor.core.turn_request` 再导出，Web 契约层直接依赖它
  （`deeptutor/api/contracts/turn_protocol.py:10`）。
- `deeptutor/app/engine.py:3` 是兼容再导出：`TurnEngine` 真身在
  `deeptutor/runtime/turn_engine.py:11-31`，`execute()` 惰性导入 `ChatOrchestrator`
  （`deeptutor/runtime/turn_engine.py:20-25`），避免进程启动期引入 provider/plugin 副作用。
- `deeptutor/app/service.py:1` 写明设计意图：一个应用服务同时供 WebSocket、CLI、Python SDK
  三个适配器使用。

## 1. 生命周期

**构建（同步、惰性单例）**
- `ApplicationContainer.build()`（`deeptutor/app/container.py:104-120`）：
  1) 读系统与集成设置合成 `CoordinationSettings`（container.py:106-108；字段与校验见
     `deeptutor/runtime/coordination/settings.py:18-60`，`backend_workers > 1` 强制要求 redis，
     settings.py:54-56）；
  2) 按 backend 选协调器：redis → `RedisCoordinator`，否则 `MemoryCoordinator`
     （container.py:110-118）；
  3) 生成 worker 身份 `hostname:pid:uuid8`（container.py:119）。
- 进程级单例 `get_application_container()`（container.py:339-343）；`set_application_container()`
  （container.py:346-348）是给测试替换用的注入缝，仓库内无其他调用点（全仓 grep 仅定义处）。

**启动（幂等、带健康门禁）**
- `start()`（container.py:122-129）：`_started` 防重入；先 `coordinator.health()`，后端不可用
  直接抛 `RuntimeConfigurationError` 拒绝启动（container.py:125-128）。
- API 生命周期在 FastAPI `lifespan` 中构建并启动容器，随后跑启动迁移
  （`deeptutor/api/main.py:119-135`：解析/复用 `app.state.application_container` → `start()` →
  `run_startup_data_migrations()`）。
- Web 适配器兜底：路由拿不到 `app.state` 时自行 `get_application_container()` + `start()`
  （`deeptutor/api/routers/unified_ws.py:59-62`、`deeptutor/api/routers/system.py:126-128`）。
- 后台恢复不进 lifespan 主路径：`BackgroundLeaderSupervisor` 把 `container.recover_once`
  作为 leader 侧回调注册（`deeptutor/api/main.py:290-306`，callback 挂载在 306）。
- `recover_once()`（container.py:139-161）遍历本机用户域：admin + 全部本地用户
  （`_local_users`，container.py:189-211，admin 在 197 显式排前、循环内 201 跳过重复 admin），
  逐用户 acquire activity 后进入 `_recover_user_workspaces`（container.py:163-187）；
  每个 scope 的 `TurnRecoveryService` 惰性创建并缓存（container.py:181-184），恢复语义本体在
  `deeptutor/runtime/coordination/recovery.py:15-31`（列出过期租约 → 逐个恢复，`backlog` 记账，
  供 `runtime_report()` 汇总，container.py:328-330）。
- 启动迁移的执行顺序在 `run_startup_data_migrations()`（container.py:288-313）固定为
  legacy_chat（292）→ workspace_preferences（293）→ 逐用户 workspace_data（299-312，
  `migrate_legacy_bindings` 通过 `asyncio.to_thread` 卸载，307）。

**关闭（逆序、可抑制）**
- `close()`（container.py:131-137）：未 `start()` 即 no-op（133）；先
  `runtime_registry.close(drain_timeout_seconds=60)` 并发排空每个 scope 的运行时
  （container.py:134；gather 实现在 62-72），再抑制异常地关协调器（135-136），最后清 `_started`。
- 关闭只由显式调用触发；仓库内 lifespan 关闭路径与容器 close 的配对不在 app/ 内
  （属 api/main.py 生命周期，本文不展开）。

## 2. 组装顺序（依赖图）

`ApplicationContainer.__init__`（container.py:78-102）按固定顺序装配，无循环依赖：

1. `settings` / `coordinator` / `worker_id`（82-84，外部注入或来自 `build()`）；
2. `capability_catalog`（89，进程级目录）→ `CapabilityRegistry`（90）→ `load_builtins()` +
   `load_plugins()`（91-92）；
3. `TurnEngine(capability_registry)`（93，运行时轴入口，持注册表注入 orchestrator，
   `deeptutor/runtime/turn_engine.py:14-25`）；
4. `StoreProvider`（94，定义在 32-34：每次 `get()` 都走 `get_session_store()`，会话轴决定后端）；
5. `RuntimeRegistry(coordinator, worker_id, turn_engine)`（95）：按 store scope 缓存
   `TurnRuntimeManager`，key 是 `store_scope(store).cache_key`
   （container.py:49-60；scope 三元组 backend:resource:owner 定义于
   `deeptutor/services/session/scope.py:9-19`）；`owner_turn_count()` 透传给
   `runtime_report()`（container.py:74-75, 327）；
6. `TurnApplicationService(store_provider, runtime_registry, coordinator)`（96-100）——装配层
   唯一被适配器大量消费的门面服务。

依赖方向严格单向：`app/` → `runtime/coordination` + `runtime/capability_*` +
`services/session`（store 与 TurnRuntimeManager）+ `services/workspace`（上下文/活动锁）。
`app/` 不 import `api/`；`api/` 反向只通过 `get_application_container()` 取依赖
（`deeptutor/api/routers/sessions.py:36-38`、`unified_ws.py:59-63`、`system.py:109-112`、
`mastery_path.py:59-61`）。

**facade 的绑定**：`DeepTutorApp.__init__`（`deeptutor/app/facade.py:63-68`）持有
`container.turns` 与 `container.capability_registry`，自身再带一个 `workspace_id` 与
`_turn_workspaces` 映射（65）。它是 CLI/SDK 面（`deeptutor_cli/chat.py:15`、`common.py:20`、
`session_cmd.py:9`、`notebook.py:10` 等均 `from deeptutor.app import DeepTutorApp`）；Web 适配器
绕过 facade 直接用 `container.turns`，因此 facade 上的 workspace 守卫只在 CLI/SDK 路径生效
（见第 4 节线索 2）。

**双层工作区守卫**：
- facade 层装饰器 `_in_app_workspace`（facade.py:18-48）：进入 `workspace_context` +
  `data_activity()`，并按方法名黑名单拒绝已归档工作区的写操作（23-31）；
- service 层装饰器 `@workspace_writer`（service.py:36/296/319/353；实现在
  `deeptutor/services/workspace/activity.py:48-64`）：归档检查 + `data_activity()`。
两者重复实现同一归档语义，且 service 的 `list/get/rename/delete_session`（517-536）没有
`@workspace_writer`，只靠 facade 包裹。

## 3. 回合协议边界

`TurnApplicationService` 是回合协议在 app/ 边界上的唯一守门人。协议对象只有三类：
`TurnRequest` 载荷（进）、事件流（出，`subscribe_*`）、协调器命令（cancel / reply / input）。

**发起（start_turn，service.py:36-131）**
- 入参兼容 `TurnRequest | dict`，dict 走 `model_validate`（40-43）；
- SDK/CLI 未包 `workspace_context` 时按载荷内 `workspace_id` 递归补包一次（44-51，注释 46-48）；
- 幂等提交：`client_submission_id` + 非 regenerate 时计算身份摘要
  （62-69，sha256，**排除 session_id 与 workspace_id**），`reserve()` 抢占提交槽；若该提交键
  已有非 failed/cancelled 的回合则直接回放 `(session, prior)`（70-78）——丢失首个 ACK 的客户端
  重发不会产生重复用户消息（tests/app/test_turn_application_service.py:90-133 覆盖重启与失败重发）；
- `ActiveTurnConflict` 时先回放同提交键的既有回合（81-87），否则仅当确实回收了无主行才重试
  一次（88-93，`_reclaim_unowned_active_turn`）；
- 成功后写会话偏好并把本回合引用并入持久 `workspace_dependencies`（94-130，去重并入在
  111-130）。

**订阅（subscribe_turn，service.py:179-269）**
- 两段式：先持久重放（`store.get_events`，193-201），再活流尾随
  （`coordinator.read_events`，215-226）；
- DONE 不是终点：`_done_has_tail`（173-177）只对 `completed` 放行尾随，因为回合结束后仍有
  会话标题等 post-turn 元数据发布（长注释 146-168）；
- 尾随窗口的诚实终止信号是租约消失（235-236），30 秒 cap 只是泄漏租约的兜底（169, 237-238）；
  既有重放已 DONE 时还需终端行仍为 running 才继续尾随（202-210）；
- 旧数据兼容：终端行缺 DONE 时合成协议合法的 done 事件（242-267，`synthesized: true`）；
  tests/app/test_turn_application_service.py:216-268 覆盖两条路径。

**命令（cancel / reply / input，service.py:296-381, 496-515）**
- `cancel_turn`（296-317）：仅对 queued/running/waiting_input 有效（300-305）；无租约者直接
  收割（306-312），有租约则提交 `cancel` 命令（313）；重复 `command_id` 视为已接受并回 True，
  让 WS 适配器能确认重试（314-317）；
- `cancel_turn_and_wait`（319-351）：轮询至终端态 + 租约释放（337-342，15s 上限 325，0.05s
  步进 170/345），释放后再让出一个步进避免与 activity 收尾竞态（346-350）；
- `submit_user_reply`（353-381）：无租约的 waiting_input 是僵尸，同步收割后返回 False
  （365-374），有租约才提交 `submit_user_reply` 命令（375-380）；
- `submit_user_input`（496-515）：回合存在且有租约才提交 `user_input` 命令；
- 活跃度判定只认租约不认行龄：`check_active_turn` 把无租约的活跃行标为 `recovering`
  （283-294）；`_reclaim_unowned_active_turn`（383-423）同理——ask_user 停靠回合的
  `updated_at` 会停走，按年龄清扫会误杀真人等待（长注释 383-405；tests/app/
  test_blocked_session_reclaims_itself.py:78-141、test_turn_parked_on_ask_user_is_reclaimable.py
  全文件、test_waiting_turn_recovery.py:94-158 覆盖）。

**收割（_reap_unowned_live_turn，service.py:425-494）**
- 终端写走 CAS：`transition_turn` 带 `expected_status` + `fencing_token`（472-480），落败即让位
  （481-483）；随后追加 error+done 事件（484-488，`worker_lost`）并尽力广播（491-493）；
  语义与 `TurnRecoveryService` 对齐（docstring 432-436）。

**facade 对协议的加工（facade.py:131-199）**
- `start_turn`：dict→TurnRequest（134-135）、能力名解析含别名（82-92）、工作区解析优先级为
  `request.model_fields_set` → `self.workspace_id` → `current_workspace_id()`（140-146），
  并把 turn_id→workspace 记入 `_turn_workspaces`（155）供后续 stream/cancel/reply 复原上下文
  （162-167, 175-179, 194-198）；
- `get_capability_availability` 对 `math_animator` 做 `find_spec("manim")` 探测（115-128），
  其余能力一律 available（129）；
- `regenerate_last_turn` 与会话 CRUD 经 `_in_app_workspace` 包裹（201-233），笔记本 CRUD
  走 `notebooks` 属性 + 同一装饰器（77-80, 235-277）。

**多 worker 语义**：同一提交槽跨 worker 共享、事件尾跨 worker 读取、cancel 由属主消费——
tests/app/test_multiworker_turn_application.py:51-184、test_multiworker_turn_reply_after_queue_drop.py:68
覆盖；`backend_workers > 1` 的前提是 redis 后端（settings.py:54-56）。

## 4. 可拆补测 / 重构线索（≥3）

1. **`DeepTutorApp._turn_workspaces` 只增不减**（facade.py:65 写入 155，读取 163/176/195-196，
   全文件无删除）。长驻宿主（SDK 内嵌服务）中每个新 turn_id 都会永久留一条映射。可补测：
   发起 N 个回合至终态后断言映射有界/随终态清理；重构方向：终态时剔除或改为带容量上限的
   LRU。
2. **rename/delete 会话语义双实现且守卫不对称**：service 的 `rename_session/delete_session/
   list_sessions/get_session`（service.py:517-536）无 `@workspace_writer`，仅靠 facade 的
   `_in_app_workspace`（facade.py:221-228）；而 Web 路由完全绕开 service 直接操作 store
   （`deeptutor/api/routers/sessions.py:445-448` rename、`581-595` delete 还级联子会话，
   service.delete_session 只取消活跃回合、无级联，service.py:529-536）。可补测：同输入下
   service.delete_session 与路由 delete 的终态一致性（级联/附件清理差异）；重构方向：收敛到
   单一所有者。
3. **start_turn 递归补包工作区导致双层 activity**：service.py:49-51 递归调用被
   `@workspace_writer` 包裹的自身，外层 `data_activity()`（activity.py:61）尚未退出时再开一个
   SQLite 读事务句柄（activity.py:12-32, 40-45）。可补测：无外层上下文的 SDK 调用路径断言
   activity 句柄获取次数为 1；重构方向：在进入装饰逻辑前一次性解析 scope，消除递归。
4. **`close()` 的 no-op 门槛可能漏排空**：`ApplicationContainer.close()` 仅在 `_started` 为真时
   排空（container.py:131-137），但 `RuntimeRegistry.get()` 在未 `start()` 时也会惰性创建
   运行时（container.py:49-60），CLI/测试里「构建即用、从未 start、直接 close」的路径不会
   drain。可补测：build → turns 操作 → close（未 start）断言 runtime 收尾仍被调用。
5. **跨模块私有 API**：`_recover_user_workspaces` 调用 `get_content_workspace_service()
   ._catalog()`（container.py:170），依赖他人私有方法，升级易碎。重构方向：工作区服务提供
   公开目录访问器。

## 5. 覆盖与相邻导读去重

- tests/app/ 现有 7 个测试文件聚焦：幂等提交与多 worker（test_turn_application_service.py、
  test_multiworker_*.py）、僵尸回收（test_blocked_session_reclaims_itself.py、
  test_waiting_turn_recovery.py、test_turn_parked_on_ask_user_is_reclaimable.py）、启动迁移
  （test_startup_data_migrations.py）。本文第 4 节线索均不与既测重叠。
- 运行时轴（orchestrator/lease/journal 细节）→ guide-runtime；会话轴
  （TurnRuntimeManager/executor 内部）→ guide-session-turns；facade 专项测试与
  container 回合协议测试为独立卡片（test-app-facade、test-app-container-turn-protocol）。
