# background_leader 租约与选主机制导读

- 基线：origin/main @ `f07029cfc`（v1.6.13）。
- 范围：`deeptutor/runtime/background_leader.py` + `deeptutor/runtime/coordination/`（选主/租约部分）+ 接线点 `deeptutor/api/main.py`。
- 锚点均为 `path:line`，相对仓库根，行号在基线 commit 上逐一核对。

## 1. 一句话与全景

`BackgroundLeaderSupervisor` 用"共享存储里的过期租约"保证：多个后端进程里**只有一个**运行进程级单例后台服务（partners / cron / GitHub 同步 / web source 同步），并独占地消费后台命令流。

```
每个 worker 进程一个 supervisor（deeptutor/runtime/background_leader.py:22）
   │ acquire_leader（抢不到就每 election_interval 重试，:79）
   ▼
LeaderLease{owner_id, fencing_token, expires_at}（deeptutor/runtime/coordination/types.py:53）
   │ 心跳：每 renew_interval（默认 10s）续期（background_leader.py:139-155）
   ├─ 拥有服务：start_callbacks 四件套（deeptutor/api/main.py:294-299）
   ├─ 消费命令：_drain_background_commands（background_leader.py:183）
   └─ 周期恢复：recovery_callback（background_leader.py:90-92）
   │ 续期失败 / 异常 / close()
   ▼
_lose_leadership：停服务 → 停心跳 → release（background_leader.py:113-123）
```

租约协议是 `RuntimeCoordinator` 的三个方法（`deeptutor/runtime/coordination/protocol.py:61-65`），两种实现同语义：`MemoryCoordinator`（单进程，`deeptutor/runtime/coordination/memory.py:216`）与 `RedisCoordinator`（多 worker，Lua 原子脚本，`deeptutor/runtime/coordination/redis.py:496`）。

## 2. 选主路径

- 候选者身份：`worker_id = hostname:pid:uuid8`（`deeptutor/app/container.py:119`），每进程唯一。
- 主循环 `_run`（`background_leader.py:71`）在 `lease is None` 时调 `acquire_leader(worker_id)`（:77）。
- 获胜条件 = "没有未过期租约"：
  - memory：`_active(self._leader)` 为假即可夺（`memory.py:216-222`）。
  - redis：Lua 中 `EXISTS && PTTL>0 → nil`；否则 DEL 过期键、`INCR fence:leader`、HSET+PEXPIRE（`redis.py:125-140`）。
- 抢不到：睡 `election_interval_seconds`（默认 1s，:34）再试（:79）。
- 抢到：启动心跳（:81）→ 依次启动服务（:82；partners/cron/GitHub/web source，`deeptutor/api/main.py:183-228`）。

## 3. 续期路径（心跳）

- 独立心跳任务每 `renew_interval_seconds`（默认 10s）醒一次（`background_leader.py:139-141`），调 `renew_leader(lease)`（:146）。
- 续期是 CAS：校验 owner 与 `fencing_token` 未变且未过期（`memory.py:224-232`；`redis.py:142-155`），命中才 PEXPIRE 续 TTL。
- 任何异常或返回 `None`（过期/被夺）→ 置 `_leadership_lost` 事件并退出心跳（:152-154）；异常只记日志、不重试（:149-151）。
- 主循环跑每个操作都用 `_while_leader` 与该事件赛跑（FIRST_COMPLETED，:157-181），事件一置位立即取消当前操作（含服务启动中：`_start_services` 先计数再 await，:196-211）。

## 4. 失效路径

三条触发线：
1. **续期失败**：心跳置位 `_leadership_lost`（§3）。
2. **主循环自检**：每轮 `wait_for(_leadership_lost.wait(), timeout=min(election, renew/2))`（:93-100）；置位即抛 `_LeadershipLost`（:85-86、:101）。
3. **任意异常**：catch-all 记日志 → 失位流程 → 睡 1s 再参选（:108-111）。

失位处理 `_lose_leadership`（:113-123）：**先停服务**（:116，注释 :114——必须赶在下任接手前）、停心跳（:117）、尽力 `release_leader`（:118-121，失败无妨：TTL 到期自清）、清事件、**游标重置 "0-0"**（:123）。优雅 `close()`（:57-69）额外取消主循环并释放租约（:66-69）。

## 5. 故障切换路径

- **崩溃切换**（无 release）：旧租约靠 TTL 自灭；延迟 ≈ 剩余 TTL（≤`lease_ttl_seconds`，默认 30s，`coordination/settings.py:23`）+ 一个选举轮询。新 leader 从零启动服务。
- **命令流不丢、不重放已 ack**：读游标持久化在 coordinator——redis 存 `commands:background_cursor`（`redis.py:451-452`），memory 存进程内游标并与调用方游标取 max（`memory.py:193`）；失位时 supervisor 本地游标重置（`background_leader.py:123`），新 leader 从持久化游标续读。
- **半执行命令会重放**：执行成功但 ack 前失位 → cursor 未推进 → 新 leader 重读同一条 → `control_callback` 必须幂等（`deeptutor/api/main.py:231-266` 的四类命令可重入）。
- **ack 带租约校验**：旧 leader 无法推进游标——redis Lua 校验 owner+fencing（`redis.py:166-179`），memory 校验当前 `_leader` 活跃且匹配（`memory.py:200-214`）；校验失败使 `_drain` 抛 `_LeadershipLost`（`background_leader.py:190-193`）。
- **主动停机**：`close()` 立即 release，继任者一个选举周期内接手（`tests/runtime/test_background_leader.py:12`）。

## 6. 与定时任务（cron）/ partner 的交接

- **cron 归 leader 独占运行**：`_start_cron`/`_stop_cron` 在回调清单里（`deeptutor/api/main.py:195-204`）。
- **cron 配置变更走命令流**：任意 worker 上的 `change_notifier` 以 `submit_background_command(CRON_RELOAD)` 投递（`main.py:275-285`），leader 消费并 `reload()`（`main.py:233-236`）。
- **partner 生命周期在多 worker 下转交 leader**：`deeptutor/api/routers/partners.py:148-152`——单 worker 或本机是 leader 则本地执行；否则提交 `PARTNER_START/STOP/RELOAD` 并轮询共享 runtime status 至多 20s（:159-161）。分派实现见 `main.py:246-266`。
- **leader 兼职 turn 恢复**：`recovery_callback=container.recover_once`（`main.py:306`；`deeptutor/app/container.py:139`），每 `recovery_interval_seconds`（默认 10s）扫过期 turn，把死 worker 的 turn 标 `WORKER_LOST` 失败（`deeptutor/runtime/coordination/recovery.py:25-43`）。

## 7. 时钟语义（对齐 test-background-leader-clock 稳定化思路）

- **租约过期判断用墙钟**：memory `expires_at = time.time()+ttl`（`memory.py:32-37`）；redis 用 **Redis 服务端 TIME**（`redis.py:135-136、151-152`），不受应用机时钟跳变影响——多 worker 部署优先 redis。
- **调度节奏用单调钟**：supervisor 只用 `loop.time()` 定拍（`background_leader.py:72、89`），心跳是 `asyncio.sleep`（:141），系统时间回拨不会提前续期。
- **正确性不靠时钟精度，靠 fencing**：旧 leader 多活时，其 renew/release/ack 均被 token CAS 拒绝；但"服务停干净没"只有旧进程自己知道，最坏重叠一个 TTL。
- **测试稳定化思路**（本卡不执行）：用构造参数缩短 TTL/间隔而非真 sleep（`tests/runtime/test_background_leader.py:13` 用 0.08s TTL），断言用有界等待。

## 8. 常见误读

1. **"leader 负责跑 turn"** — 否。它只管进程级单例后台服务与命令流；turn 并发由独立的 `TurnLease` 控制（`protocol.py:14-26`）。
2. **"leader 挂了立刻切换"** — 崩溃切换要等 TTL 过期（默认最长 ~30s）；只有主动 close 立即让位。
3. **"续期失败会重试"** — 不会。一次 renew 异常/被拒即失位（`background_leader.py:149-154`），服务全停；Redis 瞬时抖动 = 一个可见的服务重启窗口，这是 fail-fast 设计。
4. **"fencing_token 每 leader 独立编号"** — per-coordinator 全局递增（`memory.py:220`、`redis.py:134`），旧 lease 不可续用。
5. **"命令可能执行两次"** — 已 ack 的不会（游标持久化）；执行后未 ack 的会重放 → handler 必须幂等。
6. **"memory 后端也能多进程"** — 配置层拒绝：`backend_workers>1` 必须 redis（`coordination/settings.py:54-57`）。
7. **"TTL 随意调小"** — 下限 10s 且 `renew_interval < lease_ttl` 是硬校验（`settings.py:62-67`）；TTL 越小，一次 renew 抖动越容易丢主。

## 9. 测试对照

`tests/runtime/test_background_leader.py`（MemoryCoordinator 驱动）：`:12` 双 supervisor 互斥与接管；`:63` 命令只跑一次且 leader 转移后续读；`:107` 慢启动不丢租约。
