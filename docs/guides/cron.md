# cron 定时任务子系统导读（services/cron）

- 基线：origin/main @ `f07029cfc`（v1.6.13）。锚点均为 `path:line`，相对仓库根，行号在基线 commit 上逐一核对。
- 范围：`deeptutor/services/cron/`（service / executor / repository 三层）+ LLM 工具面 `deeptutor/tools/cron_tool.py` + 进程接线 `deeptutor/api/main.py`。
- 相邻导读：多 worker 选主与租约机制见 `docs/guides/background-leader.md`（相邻不同层）。本文只在"谁在跑调度循环"处引用它，不重复租约细节。

## 1. 一句话与全景

内置 cron 服务为 chat 会话与 partner 对话提供定时任务：**任意**后端 worker 都能安全地增删查任务（共享一个 WAL SQLite 库），但只有当选 leader 的进程运行调度循环；到期任务按 owner 分流——chat 任务把回复回写进原会话，partner 任务注入其消息总线并从原 IM 渠道送出。

```
LLM 调用 cron 工具（deeptutor/tools/builtin/__init__.py:1792，always-on 挂载见
deeptutor/agents/_shared/tool_composition.py:262）
  │  owner 由 pipeline 服务端注入，模型无权指定（deeptutor/agents/loop/pipeline.py:1366-1395）
  ▼
run_cron_action（deeptutor/tools/cron_tool.py:76）── add/list/cancel ──▶ CronService
                                                                          │
任意 worker：改库（service.py:232 add_job 等）── change_notifier ──▶ CRON_RELOAD 后台命令
                                                                          │
leader 进程：BackgroundLeaderSupervisor 启动/停止 CronService
（deeptutor/api/main.py:289-312，start_callbacks :294-298 / stop_callbacks :300-305）
                                                                          ▼
                          _loop → _tick → _run_job → executor.execute_job
                          （service.py:331 / :357 / :367，executor.py:16）
```

## 2. 模块地图（三层职责）

| 层 | 文件 | 职责 | 入口 |
| --- | --- | --- | --- |
| service | `deeptutor/services/cron/service.py` | 调度数学（`compute_next_run` :118、`validate_schedule` :151）、进程内任务快照与定时循环、job CRUD | `CronService` :178；进程单例 `get_cron_service` :406（库锚定 admin workspace） |
| executor | `deeptutor/services/cron/executor.py` | 到期任务的实际执行：按 owner 分流 partner / chat 两条路径 | `execute_job` :16（作为 `on_job` 回调注入 service.py:417） |
| repository | `deeptutor/services/cron/repository.py` | 跨进程持久化：WAL SQLite + revision 计数 + 迁移文件锁 | `CronRepository` Protocol :15；`SQLiteCronRepository` :29 |
| 工具面 | `deeptutor/tools/cron_tool.py` | LLM 可用的 schedule/list/cancel 动作，owner 强制来自注入 | `run_cron_action` :76 |
| 接线 | `deeptutor/api/main.py` | 随 leader 生命周期启动/停止；跨进程变更广播 | `_start_cron` :195 / `_stop_cron` :200 / CRON_RELOAD :231-237 |

数据模型（service.py）：`CronSchedule` :39（`at` 一次性 / `every` 间隔 / `cron` 表达式 + IANA tz）、`CronOwner` :50（`key` 属性 :65 生成 `chat:<user>` 或 `partner:<id>` 隔离键）、`CronJobState` :80（`next_run_at_ms`、`last_status`、`run_history` 上限 10 条 :32/:388）、`CronJob` :90。

## 3. 调度数学

- `compute_next_run(schedule, now_ms)`（service.py:118-148）：`at` 过期即 `None`（:120-123）；`every` = now + interval（:125-128）；`cron` 用 `croniter` + `ZoneInfo`，缺包/坏表达式抛 `ValueError`（:140-146）。
- `validate_schedule`（service.py:151-175）：`at` 必须在未来；`every` 最小 30s（:160）；`cron` 校验 tz 与"永不触发"（:163-174）。
- 睡眠时长 `_seconds_until_next_due`（service.py:346-355）：取最近到期时间，夹在 `[0.05s, 60s]`；`_MAX_SLEEP_SECONDS = 60`（service.py:29-31）保证外部直接改库也能在一分钟内被看到。
- 追赶语义：`start()` 时已过期的一次性任务直接删除（service.py:310-314）；`every`/`cron` 任务 `next_run` 停留在过去即"到期"，服务重启后第一拍补跑一次（service.py:305-307 注释）。

## 4. 调度时序图

```mermaid
sequenceDiagram
    autonumber
    participant Tool as cron 工具（任意 worker 进程）
    participant Svc as CronService（进程内单例）
    participant Repo as SQLiteCronRepository
    participant Lead as 当选 leader 进程
    participant Loop as _loop / _tick
    participant Ex as executor

    Tool->>Svc: run_cron_action("schedule") → add_job（service.py:232）
    Svc->>Svc: validate_schedule + compute_next_run
    Svc->>Repo: upsert（BEGIN IMMEDIATE，revision+1，repository.py:195）
    Svc->>Lead: change_notifier 提交 CRON_RELOAD（api/main.py:268-287）
    Lead->>Svc: 消费后台命令 → reload()（api/main.py:231-237，service.py:219）
    Note over Loop: 平时睡 min(下一到期, 60s)，_wake 事件提前唤醒
    Loop->>Repo: _load()：revision 未变则跳过重读（service.py:208-217）
    Loop->>Loop: _tick：所有 next_run_at_ms <= now 的任务逐个执行（service.py:357-365）
    Loop->>Ex: on_job(job) = execute_job（service.py:372，executor.py:16）
    alt owner.kind == "partner"
        Ex->>Ex: partner 未运行 → 返回 ("skipped", ...)（executor.py:83-84）
        Ex->>Ex: 注入 InboundMessage（sender=cron，meta 带 _cron_job_id，executor.py:88-95）
        Ex->>Ex: 未流式则 publish_outbound 回原渠道（executor.py:107-118）
    else owner.kind == "chat"
        Ex->>Ex: admin/user scope → user_context（executor.py:133-144）
        Ex->>Ex: 会话不存在 → ("error", "session no longer exists")（executor.py:146-148）
        Ex->>Ex: turn_engine.execute 流式收集 RESULT/ERROR（executor.py:170-175）
        Ex->>Ex: 回写 user+assistant 两条消息到原会话（executor.py:180-193）
    end
    Ex-->>Loop: (status, error)：ok / error / skipped
    Loop->>Repo: upsert 新 next_run；at/delete_after_run/不再触发则 delete（service.py:390-399）
    Loop->>Lead: _changed() → 再次 CRON_RELOAD 广播（service.py:224-228）
```

leader 收到自己发出的 CRON_RELOAD 会走一轮"强制重读 + 唤醒"（service.py:219-222），即使命令丢失，60s 兜底重查也能收敛。

## 5. 锁与并发边界

四层机制各管一段，互不替代：

1. **谁在跑（leader 租约，模块外）**：`start()`/`stop()` 只被 `BackgroundLeaderSupervisor` 的 start/stop callbacks 调用（api/main.py:294-305），保证同一时刻仅 leader 进程有一个 `_loop`。租约协议见 `docs/guides/background-leader.md`。
2. **迁移文件锁（跨进程，mutex）**：`.jobs.sqlite3.migration.lock` 旁锁文件（repository.py:44-46），`_migration_lock` :48-75 在 Windows 用 `msvcrt.locking`（:60-63）、POSIX 用 `fcntl.flock`（:64-67），且 `fcntl` 懒加载保证 Windows 可导入（回归测试锁定了这一点）。持锁范围只有两处：旧 `jobs.json` 导入 `_prepare_legacy_file` :85-104 与建表 `_initialize` :113-148。**常规读写不持此锁**。
3. **SQLite 写锁（跨进程，序列化写）**：连接固定 WAL + `busy_timeout=30000` + `synchronous=NORMAL`（repository.py:106-111）；所有写路径 `BEGIN IMMEDIATE`（upsert :197、delete :208、delete_owner :230、迁移导入 :140），写完递增 `cron_meta.revision` 单行计数器（:200/:220/:236/:144）。WAL 下读者不被写者阻塞。
4. **进程内快照（revision 校验）**：`_load`（service.py:208-217）先比 revision，没变就不重读；本地改动经 `_changed`（:224-228）同步 revision 视图并 `_wake.set()` 提前唤醒定时器。`_jobs` 字典只在单事件循环线程内变更，无进程内锁。

边界结论：任意 worker 增删查安全（2+3 保证互斥与可见性）；只有 leader 真正执行任务；leader 的内存快照通过 revision 比对 + CRON_RELOAD 命令 + 60s 兜底重查三通道保持新鲜。

## 6. 失败模式与重试语义

**没有重试**。失败被记录而非重放：

| 失败点 | 行为 | 锚点 |
| --- | --- | --- |
| `on_job`（executor）抛异常 | 捕获为 `("error", "Type: msg")`，记日志 | service.py:373-375 |
| executor 内部失败（partner 抛错、无回复、chat 会话丢失） | 返回 `error`/`skipped`，不抛出 | executor.py:99-105、:146-148、:177-178 |
| partner 未运行 | `skipped`，任务照常排下一次 | executor.py:83-84 |
| 单次运行结果 | 写 `last_status/last_error` + `run_history`（上限 10 条） | service.py:377-388 |
| 失败后的排期 | 与成功完全相同：`every`/`cron` 按原周期算下一次——**无退避、无失败计数、无自动停用** | service.py:394-399 |
| 一次性 `at` 任务失败 | 仍被删除（`delete_after_run` 或 `kind=="at"`） | service.py:390-392 |
| 计算不出下一次（如 croniter 返回 None） | 任务删除 | service.py:394-397 |
| `_tick` 本身崩溃 | 记日志，循环继续下一轮 | service.py:337-338 |
| 服务停止中任务被取消 | `stop()` 吞 `CancelledError`（预期路径） | service.py:321-329（:327-328） |
| 等待唤醒超时 | `_loop` 吞 `TimeoutError`（正常的空转唤醒） | service.py:341-344（:343-344） |

也就是说：一个每小时任务失败了，要到下一个整点才会再试；`run_history` 只用于观察（工具面渲染 `last: error`，cron_tool.py:39-44），不驱动任何补偿逻辑。运维上"卡住的定时任务"要靠人看 `list_jobs` 输出或库表，系统不会自动禁用。

## 7. 测试地图与空白

既有覆盖（基线上 `timeout 900 python -m pytest -q -p no:cacheprovider tests/services/cron/` → **34 passed in 1.10s**）：

- `tests/services/cron/test_cron_service.py`：调度数学 `TestComputeNextRun` :59 与 `TestValidateSchedule` :82；任务管理与跨实例可见性 `TestJobManagement` :97（含损坏文件保全 :148、双实例互见 :156、legacy JSON 一次性迁移 :178）；调度循环 `TestSchedulerLoop` :215（到期触发 + 一次性删除 :217，失败记录 error 且存活 :243）。
- `tests/services/cron/test_cron_repository.py`：`TestMigrationLock` :15——加锁/释放 :16、互斥阻塞 :21、`fcntl` 不允许顶层导入 :41（#1183 回归）、msvcrt :45 / fcntl :64 分支。
- `tests/services/cron/test_cron_tool.py`：工具面 `TestCronTool` :35（owner 必须注入 :36、cron 上下文内禁止再排程 :112、动作别名 :70）；挂载与 schema `TestRegistryIntegration` :155；executor 的 partner 路由 `TestExecutorRouting` :171（成功发布 :173、未运行跳过 :239）。

空白（卡面提到的两个名字在 main 上均无对应文件）：

1. **无 test-cron-executor**：`_execute_chat_job`（executor.py:123-195）零覆盖——turn engine 交互、session 缺失、admin/user 两条 scope、空回复 error 均未测。partner 路径仅借道 test_cron_tool.py。
2. **test-cron-repo-lock-timing 名不副实**：现存的互斥测试 `test_mutually_excludes_concurrent_holders`（test_cron_repository.py:21-39）用 `waited >= 0.2` 墙钟下界断言，调度延迟下易抖；改为顺序断言 + 非阻塞 flock 探测的版本在 `myfork/test/cron-repo-lock-order-20261006`，尚未合入。
3. CRON_RELOAD → `reload()` 传播链（service.py:219-222、api/main.py:231-237）无测试。
4. `start()` 丢弃过期一次性任务（service.py:310-314）、60s 兜底唤醒、`_run_job` 三条删除分支（:390-397）无直接断言。
5. 桌面通知分支（executor.py:39-74，仅 darwin）被测试统一 monkeypatch 掉，无独立覆盖。

## 8. DT-22 关联发现

- `deeptutor/services/cron/service.py:327-328`：`except asyncio.CancelledError: pass`（stop 收尾）。
- `deeptutor/services/cron/service.py:343-344`：`except asyncio.TimeoutError: pass`（wake 超时空转）。

两处是有意控制流而非吞错：前者是主动 cancel 后 `await` 任务的必然结果，后者是 `wait_for` 的正常超时出口。若后续整改"裸 pass"，建议改为显式注释或 `contextlib.suppress`，无需改变行为；超时分支若升级 Python 3.11+ 注意 `TimeoutError` 与 `asyncio.TimeoutError` 合并后的兼容性。
