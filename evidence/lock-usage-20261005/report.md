# 锁使用清点：锁内 I/O 与全局锁串行化模式（#1779 同类扫描）

- 基线：`origin/main` @ `f07029cfcf2c8dfccdb671cdfc343db8334f5741`（v1.6.13），取自 2026-10-05 `git fetch origin main`
- 范围：`deeptutor/`（排除 `tests/`、`__pycache__`），只读扫描，未改任何产品代码
- 方法：rg 全量枚举锁构造点 + AST 扫描 314 个 `with`/`async with` 临界区（工具见本目录 `scan_locks.py`、`scan_regions.py`，原始数据 `raw-ast.json`、`lock-regions.json`），对约 40 个热点逐个人工复核上下文
- 规模：**119 处锁构造**（47 `threading.Lock`、35 `asyncio.Lock`、6 `RLock`、2 `BoundedSemaphore`、`asyncio.Semaphore`/`Event`/`Condition` 若干），**314 个临界区**，分布在 41+ 个文件
- 上游对照：HKUDS/DeepTutor issue **#1779**（EmbeddingClient 全局 spacing 锁）。扫描日检查 `gh pr list -R HKUDS/DeepTutor --state all --search "1779"` 为空，**上游尚无关联 PR**，因此按原计划执行清点，无需转复核。
- 去重标注约定：`[up-1779]` = 属于 #1779 修复范围；`[scan-async-tasks?]` = 涉及 task 生命周期、可能与异步任务扫描卡重叠（该卡在 Multica 工作区搜索 "scan-async-tasks"/"async-tasks"/"scan:" 均未命中，截至扫描日未找到，先按主题标注）。

## 风险分级

- **HIGH**：进程级全局锁 + 长 I/O（网络流式响应/子进程/多跳外呼），跨会话、跨用户串行化。
- **MED**：全局或共享锁 + 磁盘 I/O 且被 async 路由在事件循环线程直接调用（阻塞整个 loop）；或全局锁 + 单次网络 I/O 但等待者范围广。
- **LOW / by-design**：per-key 锁快临界区、正确单飞（single-flight）、并发限流信号量、一次性迁移长持锁。
- **范本**：同仓库已有的正确写法，修复卡可直接参照。

---

## HIGH（up-1779 同类：全局锁 + 长 I/O）

### H1. CodeBuddy 全局 env-key 锁跨越整个流式 LLM turn
- `deeptutor/services/llm/provider_core/codebuddy_provider.py:766-780` — `_temporary_codebuddy_api_key` 是 async context manager，`async with _API_KEY_ENV_LOCK:`（:771，**模块级全局 asyncio.Lock**，:27）的临界区就是 `yield`，即整个 `async with` 使用体。
- `deeptutor/services/llm/provider_core/codebuddy_provider.py:263-273` — one-shot 路径在该锁内完成 `sdk.query(...)`（:267）**并消费整个流式响应** `_consume_messages(stream)`（:269，LLM 生成可持续数十秒至分钟）；`deeptutor/services/llm/provider_core/codebuddy_provider.py:86` 同样包住会话调用。
- 影响：进程内所有 CodeBuddy 请求（不同 session、不同用户）完全串行；一个慢 turn 阻塞全部后续请求。env 置换实际只需覆盖 `sdk.query(**kwargs)` 构造那一刻。
- 判定：**HIGH**，#1779 同类且影响面更广（不分 batch_delay，无条件生效）。
- 拆卡 **CARD HIGH-A**：把 `_API_KEY_ENV_LOCK` 临界区收紧到 `sdk.query(...)` 构造（构造完即释放，流式消费移出锁外）；同文件关联项一并处理——`_sessions_lock`（:166，实例全局）持锁跨 `_CodeBuddySession.start`（:313-341，**子进程启动**在锁内 :331），建议 spawn 移出锁、锁内只做注册表操作；`session.lock`（:291-296）持锁跨 `session.run_turn`（:294）属 per-session 状态串行，by design 但需在卡内评估把 `deepcopy`/状态提交与网络等待分离。

### H2. 进度广播全局锁 + WebSocket 发送
- `deeptutor/api/utils/progress_broadcaster.py:19` — 类级全局 `asyncio.Lock`（单例）。
- `deeptutor/api/utils/progress_broadcaster.py:49-69` — `broadcast` 持锁**逐个** `await websocket.send_json(...)`（:58）。慢/半死客户端会让单次 send 长时间挂起，进而阻塞：所有 KB 的进度广播、以及 `connect`/`disconnect`（:30-45）。索引构建的进度事件走此路径，频率高。
- 判定：**HIGH**（全局串行 + 网络 I/O，#1779 同构）。
- 拆卡 **CARD HIGH-B**：锁内快照连接集合，锁外逐个发送；失败连接回锁内清理。参照范本 `llamaindex/storage.py:255-279`（"Load outside the lock"）。

### H3. 渠道扫码 onboarding 全局锁 + 外呼 HTTP
- `deeptutor/services/partners/channel_onboarding.py:160-175` — 全局 `_keys_lock`（:155）持锁跨 `_purge_expired_locked` 与 `_start_session`（:172 → `_start_feishu` :336+ / `_start_wecom`，各含多次出站 HTTP init+二维码生成）。所有 partner/所有渠道的 onboarding 启动互相串行。
- `deeptutor/services/partners/channel_onboarding.py:177-190` — `status()` 持 per-session `session.lock` 跨 `_poll`（:188 → `_poll_feishu` :421+ / `_poll_wecom` :475+，设备码轮询出站 HTTP）。前端轮询放大排队：一次超时的 poll 挂住后续所有 status 请求。
- 判定：**HIGH**（全局锁 + 网络外呼）。
- 拆卡 **CARD HIGH-C**：`_keys_lock` 只护注册表读写；`_start_session`/`_poll` 网络在锁外，session 状态机用小临界区提交结果。

### H4. EmbeddingClient 全局 spacing 锁（即 up-1779 原型）
- `deeptutor/services/embedding/client.py:44-59` — 进程级类属性 `_spacing_lock`（threading.Lock，双检构造，:53）。
- `deeptutor/services/embedding/client.py:61-73` — `_hold_spacing_lock` 用 `lock.acquire(blocking=False)` + `await asyncio.sleep(0.05)` 的**50ms 非阻塞轮询循环**获取锁（:68-69）。
- `deeptutor/services/embedding/client.py:154-160` — 临界区内：限速记账（batch_delay>0 时 `await asyncio.sleep(batch_delay - elapsed)` :158）+ `response = await self.adapter.embed(request)`（:160，**网络请求在锁内**）。
- 判定：**HIGH**；标注 `[up-1779]` —— 此项属于 #1779 修复范围，本卡不重复拆修复卡，仅为修复提供两点补充证据：(a) 轮询获取循环（:68-69）与锁内 sleep（:158）也应一并纳入修复评审；(b) 上游建议方案（batch_delay<=0 跳锁）与本扫描结论一致。同文件多模态路径 `embed_contents()` 未加此锁且无正确性问题（#1779 已指出），佐证非必要。
- 关联：`tests/services/embedding/test_client_runtime.py` 中「同一时刻最多 1 个在飞请求」断言把 bug 编码成契约（#1779 已提），修复时需同步调整（tests 不在本扫描范围，仅标注）。

---

## MED

### M1. SQLite 会话存储单锁全串行
- `deeptutor/services/session/sqlite_store.py:1100-1102` — `_run` 以**每 store 一把 asyncio.Lock** 包住 `asyncio.to_thread(fn)`：进程内所有会话/消息/事件 SQLite 读与写全串行。WAL 已启用（:281）但进程内单锁抵消了并发读收益。
- 判定：**MED**（吞吐瓶颈而非正确性）。
- 拆卡 **CARD MED-A**：读写分离（读走无锁连接池/多线程，写保留单飞），或至少读写两把锁。改动面大，需回归 `tests/services/session/`。

### M2. 事件循环线程上的同步存储 I/O + 全局锁（async 路由直调）
以下调用链均发生在 `async def` 路由/服务内、事件循环线程上：全局 threading 锁 + 同步磁盘 I/O，锁等待与 I/O 都会卡住整个 loop：
- `deeptutor/api/routers/courses.py:70` → `deeptutor/services/courses.py:329/336/352/384/429/461/486/520/534/558/572` — 每次课程 CRUD 全量 `_load`/`_save` JSON 文件，`_LOCKS_GUARD` + per-data RLock（:236-245）。
- `deeptutor/api/routers/reading.py:433-483,486-541,544+,616-649` → `deeptutor/reading/catalog_store.py:78,291,540,564,586,681,694,707,739,782,811,842,894,915,926,935,946,973` — 阅读目录 SQLite 操作，`self._lock`（RLock，:63）+ `conn.execute`，18 个临界区。
- `deeptutor/api/routers/partner_groups.py:81-120` → `deeptutor/services/partner_groups/store.py:23-32`、`deeptutor/services/partner_groups/memory.py:98-130` — 小组/白板 JSON 文件读写 under per-file 全局锁（`path.open` 在锁内）。
- `deeptutor/api/routers/video_learning.py:246-254,340-343,356-359,369-372` → `deeptutor/video_learning/service.py:357-400` — 阻塞式 `fcntl.flock(LOCK_EX)`（:390，**无 NB**）+ JSON 读写；争用时直接挂住 loop 线程。
- `deeptutor/services/settings/interface_settings.py:235-241` — `_settings_lock`（:35）+ `open/json.load/os.replace`。
- `deeptutor/multi_user/identity.py:232,306,325,344,370,393,407,482` — `_USERS_WRITE_LOCK`（:35）+ `_write_users` 全量用户文件写，8 处。
- `deeptutor/services/partners/sessions.py:87,134,152,202,238` — `_write_lock`（:56）+ `write_text/open/path.replace`，5 处。
- `deeptutor/learning/storage.py:397+` — `_schema_lock`（RLock，:50）+ `_connect`/多条 `execute`/`commit`。
- `deeptutor/utils/config_manager.py:56,70` — 锁内 `_read_yaml` / 原子写（`os.replace`/`flush`）。
- `deeptutor/knowledge/manager.py:368,646,1432` — `_catalog_lock` + `_read_and_reconcile_config`（配置重读）/`_list_knowledge_bases`（目录扫描）。
- 判定：**MED**。单文件较小时影响有限，但目录/目录扫描类（catalog、knowledge）随数据量线性变慢，且全部共享「全局锁 + loop 线程同步 I/O」同一模式。
- 拆卡 **CARD MED-C**：统一方案——在 async 入口包 `asyncio.to_thread`（最小改动），或逐步改异步存储层；优先 catalog_store 与 video_learning（后者还有阻塞 flock）。
- 标注：`[scan-async-tasks?]` 若该卡覆盖「事件循环阻塞 I/O」主题，本条与其重叠，领取前先对齐。

### M3. codebuddy_auth 状态探测在实例锁内做网络/子进程
- `deeptutor/services/codebuddy_auth.py:31-37` — `status()` 持 `self._lock`（:13）做 `_probe_locked()`（:125-141）：先 `probe_account`（:154，出站网络探测），未登录再 `_start_sdk_authenticate()`（:129，**子进程启动**）然后 cancel。
- `deeptutor/services/codebuddy_auth.py:39-62` — `start_login()` 同锁内 `_probe_local_login`（:44）+ `_start_sdk_authenticate`（:47）。
- 影响：UI 高频轮询 status；任一探测/启动慢，所有 status/login/cancel 排队。
- 判定：**MED**。拆卡 **CARD MED-B**：探测结果带 TTL 缓存；SDK 探测移出锁，锁内只提交状态。

### M4. opencode/mimocode server 池全局锁 + 子进程 spawn
- `deeptutor/services/subagent/opencode_server.py:68-96` — 模块级全局 `_lock`（:69）持锁跨 `_reap_stale` 与 `_spawn`（:94，子进程启动）。所有 CLI+workdir 组合共享一把锁：一次慢 spawn 阻塞其它组合的**缓存命中快路径**（:85 先抢锁才能命中）。
- 判定：**MED**。建议：per-key 锁 + 全局注册表锁（双锁），spawn 在 per-key 锁内。

### M5. MCP 管理器 SHARED_OWNER 锁 + 全量连接同步
- `deeptutor/services/mcp/manager.py:269-276` — `ensure_started` 持 SHARED_OWNER 锁跨 `_sync_to_config(load_mcp_config())`（连接所有启用的 MCP server，网络）；`reload`（:280-283）同。首个 turn 触发懒启动时，其它并发 turn 在锁上等待全部连接建立完成。
- 判定：**MED**（一次性，但启动窗口内所有 turn 串行等待）。建议：锁内只置标志与注册表，连接在各 server 自身的 per-owner 锁内进行。

### M6. 单飞类：锁内网络 I/O（语义正确，标注复核）
- `deeptutor/services/codex_auth/service.py:722-742,828-838` — `_refresh_lock` 持锁跨 `_refresh_credentials`（网络刷新凭据）——标准 single-flight。
- `deeptutor/services/codex_auth/service.py:698-719` — `_catalog_sync_lock` 持锁跨 `get_token`（可能触发上面整条刷新链）+ `_catalog.get(force=True)`（网络）。
- `deeptutor/services/codex_auth/service.py:867-881` — logout 持 `_catalog_sync_lock` 跨 `self._oauth.revoke`（网络）。
- `deeptutor/services/codex_auth/service.py:481-505` — `start_login` 持 `_operation_lock` 跨 loopback listener 启动（:487）；`cancel_login`（:684-695）持同锁跨 `callback.cancel` + `await asyncio.sleep(0)`（单次让出，非轮询循环）。
- `deeptutor/services/app_update.py:318-331` — 更新检查单飞，锁内 GitHub API HTTP（:342）；TTL 命中路径无锁（:311-316）。
- `deeptutor/services/sandbox/service.py:49-68` — 健康检查单飞，锁内 `backend.health()` + subprocess fallback（:57,67），happy path 短路。
- 判定：**MED-LOW**（等待者都会经历一次完整网络往返；超时/慢上游时放大）。拆卡 **CARD MED-D**（可选）：为这些单飞加获取超时/可取消等待，避免上游挂死拖垮 API。标注 `[up-1779]` 无关（#1779 仅指 embedding 客户端）。

### M7. 文件锁持锁跨整个 partner LLM turn（by design，标注）
- `deeptutor/api/routers/partners.py:1654-1664,1712-1723` — `web_session_idle_lock`（`deeptutor/services/partners/manager.py:1331-1338`，文件锁，`_acquire_web_turn_lock` :79-99 为 **LOCK_NB 非阻塞获取**，争用即 409 快速失败）持锁跨整个 `await mgr.send_message(...)`（LLM turn）。
- 判定：**LOW-MED**。per-session 互斥是语义需要（turn 期间排除会话变更/删除），且获取不阻塞 loop；但注意 session 变更/删除端点在同一把锁上将以 409 拒绝直至 turn 结束（分钟级）。同文件 :199-212（per-partner start 锁）、:849-851（per-draft confirm 锁）同为 per-key 单飞，LOW。
- 同类：`deeptutor/partners/channels/mochat.py:757-782` per-target 锁持锁跨 `_process_inbound_event`（网络回发）；`deeptutor/api/routers/mastery_path.py:800-807`、`deeptutor/api/routers/partner_groups.py:360-367` `send_lock` + `ws.send_json`（组内有序投递）。均 by design，LOW-MED，仅标注不拆卡。

---

## LOW / by-design / 范本

| 位置 | 形态 | 判定 |
| --- | --- | --- |
| `deeptutor/services/web_source/robots.py:119-127,163-165` | per-host 锁内 `asyncio.sleep`（限速）与 per-origin 锁内 robots.txt 拉取 | by-design（限速即目的），LOW |
| `deeptutor/services/llm/traffic_control.py:43-77` | token bucket，`asyncio.sleep` 在锁外（:71-77 注释明确） | **范本** |
| `deeptutor/services/rag/pipelines/llamaindex/storage.py:255-279` | 索引加载在锁外（:262 注释），锁只护 OrderedDict | **范本**（CARD HIGH-B/M2 参照） |
| `deeptutor/services/cli_apps/installer.py:96-105,115-117` | per-app 锁 + `to_thread`；install busy 快速失败；uninstall 等待同锁 | LOW |
| `deeptutor/services/rag/pipelines/lightrag/worker.py:28,37-57` | 全局锁仅保护 worker loop/线程一次性创建（#1578 教训） | LOW |
| `deeptutor/runtime/isolated_worker.py:35`、`deeptutor/services/office_preview.py:39`、`deeptutor/services/sandbox/quota.py:37` | BoundedSemaphore/Semaphore 并发上限 | by-design |
| `deeptutor/services/session/legacy_migration.py:139-140`、`deeptutor/learning/migration.py:198-199`、`deeptutor/services/cron/repository.py:86,114`、`deeptutor/services/session/sqlite_store.py:55-65,257` | 文件锁持锁跨整库迁移/拷贝 | 一次性 by-design，LOW（启动窗口长持锁，标注） |
| `deeptutor/services/session/turn_runtime.py:39-47` | 全局锁内构造 manager（含 SQLite 初始化） | 一次性，LOW |
| `deeptutor/book/engine.py:332,1003-1028,1236-1257,1359-1385,1450-1455` | runtime/global 锁均为短临界区注册表操作（queue 无界，put 不阻塞） | LOW |
| `deeptutor/services/session/turns/lifecycle.py:667-691,695-707`、`executor.py:1398`、`learning_adapter.py:37-41`、`request_preparer.py:797-810` | 持锁仅做注册表/快照，持久化在锁外或 `flush_lock` per-execution 单飞 | LOW；`[scan-async-tasks?]`（turn 生命周期） |
| `deeptutor/services/codebuddy_auth.py:59`、`partners/manager.py:993`、`partners/channels/mochat.py:863`、`book/engine.py:1239`、`session/turns/request_preparer.py:802,808` | 锁内 `create_task`（不等待） | LOW；`[scan-async-tasks?]` |
| `deeptutor/services/parsing/engines/_install.py:190-222`、`mineru/models.py:115-142` | 锁内 `Popen`（快）+ 后台泵线程 | LOW |
| `deeptutor/partners/channels/lark_http.py:36,66-77`、`services/llm/provider_factory.py:158`、`runtime/agentic/client.py:254`、`services/llm/capabilities.py:369/388/402`、`openai_http_client.py:28/49`、`cloud_provider.py:26` | 全局守卫锁 + 单例/池构建 | LOW |
| `deeptutor/utils/network/circuit_breaker.py:25-56`、`runtime/memory_reclaim.py:51-65`、`api/utils/task_id_manager.py`、`task_log_stream.py:48-242`、`agents/research/utils/citation_manager.py:90`、`memory/consolidator/runs.py:128`、`memory/trace.py:30`、`memory/store.py:323`、`learning/event_hub.py:57`、`runtime/coordination/memory.py:18-245`、`journal.py:32` | dict/注册表守卫，快临界区 | LOW |
| `deeptutor/reading/epub_bilingual.py:30`、`services/partners/weixin_onboarding.py:70`、`partners/drafts.py:24-30`、`partners/links.py:39/107`、`partners/web_continuity.py:29,102-158`、`settings/interface_settings.py:69`、`services/config/settings_draft.py:58/86/110`、`model_catalog.py:259/297/319`、`codex_auth/storage.py:115`、`partners/channels/msteams.py:139/793`、`reading/store.py:176/249`、`notebook/service.py:112-123`、`reading/extensions.py:119-168` | 全局/per-key 锁 + 小文件 JSON 读写 | LOW-MED（文件大或高频时会向 M2 恶化；M2 统一治理时可顺带覆盖） |
| `deeptutor/services/session/turns/lifecycle.py:56` 等实例 asyncio.Lock（多处） | 单事件循环内互斥 | INFO |

## 与 up-1779 / scan-async-tasks 去重总表

| 主题 | 归属 | 本报告条目 |
| --- | --- | --- |
| EmbeddingClient spacing 锁（含 50ms 轮询获取、锁内 sleep、锁内 embed） | `[up-1779]` 修复范围 | H4（不拆修复卡，附补充证据） |
| 其余全局锁 + 网络/子进程 I/O | 本卡新拆 HIGH-A/B/C | H1-H3 |
| 事件循环阻塞同步 I/O（async 路由直调存储） | 本卡 MED-C；`[scan-async-tasks?]` 主题可能重叠 | M2 |
| task 生命周期相关锁（lifecycle/executor/request_preparer/create_task 类） | `[scan-async-tasks?]` 标注，本卡判定均 LOW | LOW 表 |

## 可拆修复卡条目汇总

1. **CARD HIGH-A**（codebuddy_provider）：`_API_KEY_ENV_LOCK` 临界区收紧至 `sdk.query` 构造；`_sessions_lock` 内移出 session spawn；评估 `session.lock` 与网络等待分离。验收：并发多 session one-shot 不互等；现有 tests 全绿。
2. **CARD HIGH-B**（progress_broadcaster）：锁内快照、锁外发送、失败回锁清理。验收：慢客户端不影响其它 KB 广播与 connect/disconnect。
3. **CARD HIGH-C**（channel_onboarding）：`_keys_lock` 只护注册表；start/poll 网络移出锁。验收：两个 partner 同时发起 onboarding 互不等待。
4. **CARD MED-A**（sqlite_store）：`_run` 读写分离或连接池化。验收：并发读不被单写阻塞；事务一致性回归通过。
5. **CARD MED-B**（codebuddy_auth）：status 探测 TTL 缓存 + 探测移出锁。验收：慢探测不阻塞 status 轮询。
6. **CARD MED-C**（loop 阻塞 I/O 治理）：M2 清单统一 `to_thread` 或异步化；优先 catalog_store、video_learning（含改 NB flock + 重试或 `to_thread`）。验收：async 路由不再直接做同步文件/SQLite I/O（可用简单 lint/审查清单保障）。
7. **CARD MED-D**（可选，codex_auth/app_update/sandbox 单飞）：加获取超时与可取消等待。
8. **up-1779**：维持上游修复卡，不重复拆；建议评审时覆盖 `_hold_spacing_lock` 轮询获取（client.py:68-69）与锁内 sleep（:158）两点。

## 附：原始数据

- `raw-ast.json` — 全量 AST 锁定义与调用点（`scan_locks.py` 产物）
- `lock-regions.json` — 314 个临界区及体内 await/IO/sleep/spawn 清单（`scan_regions.py` 产物）
- `regions-report.txt` — 230 个非平凡临界区的可读摘要
- `SHA256SUMS` — 本目录全部文件校验和
