# 定时任务注册点清点扫描：deeptutor/services/cron/

- 扫描日期：2026-10-09
- 代码基线：origin/main `6cf793bd868ba5ecbe64722936d4be8fab5a01df`（release: v1.6.14）
- 范围：只读清点 `deeptutor/services/cron/`（service / executor / repository）全部任务注册点，含产品代码中的注册/消费调用点；不改任何产品/测试代码。
- 去重说明：本卡只覆盖 cron 注册轴；`test-cron-executor`（执行器单测）、`scan-async-tasks`（异步任务轴）、`guide-cron`（历史导读）不在本卡范围。
- 复算方式：见文末"复算命令"，`jobs.json` 为结构化清单，`SHA256SUMS` 为校验和。

## 1. 任务清单（注册点全量）

### 1.1 注册机制本体（services/cron 包内）

| # | 注册点 | 锚点 | 说明 |
|---|--------|------|------|
| R1 | `CronService.add_job` | `deeptutor/services/cron/service.py:232` | 唯一入库注册入口：校验调度（:242）→ 计算 next_run（:257）→ 写内存快照（:258）→ `repository.upsert`（:259）→ `_changed()` 唤醒调度循环（:260） |
| R2 | 单例工厂 `get_cron_service` | `deeptutor/services/cron/service.py:406-419` | 进程级单例；存储锚定管理员工作区 `<admin>/cron/jobs.sqlite3`（:413-416，legacy `jobs.json` :417）；`on_job=execute_job`（:418） |
| R3 | 反序列化注册 `CronJob.from_dict` | `deeptutor/services/cron/service.py:101-115` | 每次快照重载时把 SQLite payload 还原为内存任务（`_load` :208-217，revision 失效判定） |
| R4 | legacy JSON 导入 | `deeptutor/services/cron/repository.py:85-104`（读取）+ `:113-148`（初始化导入） | 首次打开旧 `jobs.json` 时在迁移锁下导入 SQLite 并归档原文件，保留任务 id 与 state |
| R5 | 存储模式 | `deeptutor/services/cron/repository.py:115-137` | `cron_jobs(id, owner_key, next_run_at_ms, payload, updated_at_ms)` + `cron_meta` 单行 revision 计数器；owner 索引 :127 |

无硬编码/默认任务：任务集合完全由运行期通过 `cron` 工具创建（全仓仅一处 `add_job` 调用，见 R6）。

### 1.2 产品代码注册/消费调用点

| # | 调用点 | 锚点 | 说明 |
|---|--------|------|------|
| R6 | 工具实现 `run_cron_action` → `service.add_job` | `deeptutor/tools/cron_tool.py:120`（schedule 分支 :106-137） | 全仓唯一 `add_job` 调用；调度参数组装 `_build_schedule` :59-73；owner 来自管道注入 `_cron_owner`（:77-83），模型不可指定 |
| R7 | `CronTool` 工具类（tool name `cron`） | `deeptutor/tools/builtin/__init__.py:1866-1960` | 定义 :1866；execute 委托 :1956-1960；内置工具注册表 `deeptutor/tools/builtin_specs.py:69` |
| R8 | owner 注入与防嵌套 | `deeptutor/agents/loop/pipeline.py:1374-1410` | partner 轮 owner :1384-1394；chat 轮 owner :1396-1410；`_cron_in_context`（:1379-1381）禁止在定时任务执行中再排新任务 |
| R9 | 工具常驻挂载 | `deeptutor/agents/_shared/tool_composition.py:268-277` | `cron` 属 always-on 工具（chat 与 partner 合成路径均挂载） |
| R10 | 生命周期接线 | `deeptutor/api/main.py:195-203, 271-286, 289-305` | `_start_cron`/`_stop_cron` 交给 `BackgroundLeaderSupervisor`（仅租约持有者启动调度器，跨进程重叠防护）；change_notifier 经 `CRON_RELOAD` 后台命令（:233-236, :273-284）让 leader 即时重载 |
| R11 | 注销路径（partner 销毁） | `deeptutor/services/partners/manager.py:1446-1456` | `destroy_partner` → `remove_owner_jobs(f"partner:{id}")`（service.py:288-297） |
| R12 | 主动注销 | `deeptutor/services/cron/service.py:274-286`（cancel_job）/ `tools/cron_tool.py:98-104` | cancel 带 owner_key 作用域校验 |

## 2. 周期/时区表达式

- 三种调度（`service.py:40-47`）：`at`（epoch ms 一次性）、`every`（固定间隔秒，最小 30s，校验 `service.py:159-162`）、`cron`（5 段 croniter 表达式 + 可选 IANA tz）。
- `compute_next_run`（`service.py:118-148`）：
  - `at`：固定 epoch ms，过期即 `None`（:120-123）。
  - `every`：`now + interval`（:125-128）——每次执行后以"当前时刻"重锚，存在相位漂移（见风险 T2/M3）。
  - `cron`：croniter 基于带 tz 的 datetime 取下一触发点（:130-139）；**tz 缺省时回退服务器本地时区**（:136）。缺 `croniter` 包抛 ValueError（:140-144）。
- 工具面参数（`tools/builtin/__init__.py:1877-1953` / `cron_tool.py:59-73`）：`at`/`every_seconds`/`cron_expr` 三选一（`cron_tool.py:63-68`）；`tz` 可选 IANA（`cron_tool.py:73`）；naive ISO 时间按服务器本地时区解释（`cron_tool.py:54-56`）。
- 校验 `validate_schedule`（`service.py:151-175`）：`at` 必须在未来（:154-157）；`every` ≥30s（:159-162）；`cron` tz 经 `ZoneInfo` 校验（:163-170）、表达式必须可触发（:171-173）。

## 3. 错过触发（missed trigger）行为

| 场景 | 行为 | 锚点 |
|------|------|------|
| 停机期间过期的一次性 `at` 任务 | 启动时**静默删除，不补跑** | `service.py:311-314` |
| 停机期间过期的 `every`/`cron` 任务 | next_run 留在过去即视为 due，启动后**立即补跑一次**（N 次错过折叠为 1 次） | `service.py:304-307, 360-365`；补跑后从 now 重锚 `service.py:394` |
| 外部进程改库 | leader 快照经 revision 失效检测重载；调度循环最长 60s 兜底醒来（`_MAX_SLEEP_SECONDS` :31），或 `CRON_RELOAD` 即时唤醒 | `service.py:208-217, 331-344, 346-355`；`api/main.py:233-236` |
| 错过记录 | 无：run_history 只记录实际执行（最多 10 条 :32），停机错过不落任何痕迹 | `service.py:380-388` |

## 4. 重叠执行（overlap）行为

| 层 | 机制 | 锚点 |
|----|------|------|
| 跨进程 | 仅租约持有 leader 启动调度器（`_start_cron` 挂在 `BackgroundLeaderSupervisor.start_callbacks`）；租约丢失即停服 | `api/main.py:291-305`；`deeptutor/runtime/background_leader.py:66-80`（acquire/renew） |
| 进程内 | `CronService` 模块单例；`_tick` 顺序 `await` 逐个执行到期任务——**同一任务不会自重叠，但长任务阻塞全部其他任务**（队头阻塞，无超时） | `service.py:403-419, 357-365, 367-400` |
| 执行器 | partner 轮（`executor.py:77-120`）与 chat 轮（:123-195）均为完整 LLM turn，无超时包裹；失败仅记 status/error | `executor.py:98, 170, 373-375` |
| 状态落库时机 | 任务执行完成后才写回 state/next_run（:377-399）——执行中崩溃/被取消时，磁盘上 next_run 仍是过去值，failover 后会被新 leader 再次触发（at-least-once） | `service.py:377-399` |

## 5. 仓库锁使用（repository locks）

| 锁 | 范围 | 锚点 |
|----|------|------|
| 迁移/初始化锁 `.{db}.migration.lock` | fcntl.flock（POSIX）/ msvcrt.locking（Windows），独占；保护 legacy JSON→SQLite 迁移与建表 | `repository.py:44-75, 86, 114` |
| SQLite 写锁 | WAL（`journal_mode=WAL`）、`busy_timeout=30000`、`synchronous=NORMAL`；所有写路径 `BEGIN IMMEDIATE` + 提交/回滚 | `repository.py:106-111, 195-204, 206-226, 228-242` |
| revision 一致性 | cron_meta 单行计数器，每次写 +1；`_load` 以 revision 判定快照失效 | `repository.py:131-137, 183-186`；`service.py:208-217` |
| in-process | `_jobs` 字典无锁，依赖单事件循环线程内同步访问；worker 进程只写库，leader 靠 revision 感知 | `service.py:199, 224-229` |
| owner 作用域删除 | delete/delete_owner 带 owner_key 条件，与 `CronOwner.key` 格式一致 | `repository.py:206-242`；`service.py:65-69` |

## 6. 风险标注（时区 / 重叠 / 错过触发三类）

| ID | 类别 | 风险 | 锚点 | 严重度 |
|----|------|------|------|--------|
| T1 | 时区 | `cron` 任务未显式传 `tz` 时按**服务器本地时区**计算触发点；服务器迁移/时区变更会整体漂移触发时间 | `service.py:136`（回退）、`cron_tool.py:73`（tz 可选） | 中 |
| T2 | 时区 | naive `at` 时间按服务器本地时区解释（`parsed.astimezone()`），跨时区部署语义不一致 | `cron_tool.py:54-56` | 低 |
| O1 | 重叠 | **leader failover 窗口重复执行**：任务执行中 state 未落库，租约切换后新 leader 会再次触发同一 job（at-least-once，投递可能重复：聊天消息/IM 出站） | `service.py:377-399`（完成后才写回）、`api/main.py:300-305` | 中 |
| O2 | 重叠 | 队头阻塞：单 leader 串行执行、无任务级超时；一个挂起的 turn 冻结全部后续任务 | `service.py:357-365`、`executor.py:98, 170` | 中 |
| M1 | 错过触发 | 停机错过的一次性 `at` 任务被**静默删除**，无任何记录或通知 | `service.py:311-314` | 中 |
| M2 | 错过触发 | N 次错过折叠为 1 次补跑（catch-up 语义未在工具描述中说明，用户可能预期逐次补跑） | `service.py:304-307, 394` | 低 |
| M3 | 错过触发 | `every` 任务每次执行后从 now 重锚：长执行/停机会整体平移相位（间隔漂移） | `service.py:125-128, 394` | 低 |
| M4 | 错过触发 | 错过不落 run_history（历史只含实际执行），排障时无法区分"未到点"与"错过了" | `service.py:380-388` | 低 |

## 7. 复算命令

```bash
# 基线
git -C /Users/Shared/DeepTutor fetch origin main
git -C /Users/Shared/DeepTutor worktree add <wt> -b <branch> origin/main   # 6cf793bd8

# 注册点定位
rg -n "add_job" deeptutor/                       # 仅 tools/cron_tool.py:120 + 定义
rg -n "get_cron_service|from deeptutor.services.cron" deeptutor/
rg -n "CronService\(|SQLiteCronRepository\(" deeptutor/
rg -n "run_cron_action|_cron_owner|_cron_in_context" deeptutor/
rg -n "remove_owner_jobs" deeptutor/

# 本清单结构化数据
cat evidence/cron-registry-20261009/jobs.json
shasum -a 256 -c evidence/cron-registry-20261009/SHA256SUMS
```

## 8. 结论

- 任务注册链路单一且清晰：`cron` 工具（R6-R9）→ `add_job`（R1）→ SQLite（R5），leader-only 调度（R10），partner 销毁联动注销（R11）；无隐藏注册点。
- 风险集中在三类：时区回退（T1）、failover at-least-once 重复投递（O1）、队头阻塞无超时（O2）、一次性任务静默丢弃（M1）。均为行为语义问题，无安全问题。
