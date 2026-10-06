# 时序/时区/顺序敏感测试全量清点（flaky 风险清单）

- 扫描基线：`origin/main` @ `f07029cfcf2c8dfccdb671cdfc343db8334f5741`（v1.6.13，2026-10-06 fetch）
- 扫描面：`tests/`（705 个 `test_*.py`）+ 包内 `deeptutor/learning/tests/`（23 个）+ `deeptutor/services/config/test_runner.py`，共 729 个测试文件（含 conftest/helper 合计 776 个 .py，与扫描器输出一致）；只读，不改任何代码。
- 方法可复现：`python3 evidence/flaky-tests-20261006/scan_categories.py`（纯标准库，类别口径见脚本内正则）。
- 已知先例对齐：`fix-tz-flaky`（tests/agents/chat/test_runtime_context.py 3 例 TZ 失败，已由开放 PR #1732/#1733 锁定，本次复现成功，见 §5）。
- 去重：scan-datetime-naive 卡覆盖产品代码 naive datetime；本卡只扫测试面，产品侧仅在判断测试断言是否与之"成对一致"时引用。

## 1. 类别命中总量（口径 = scan_categories.py）

| 类别 | 命中行数 | 摘要 |
| --- | --- | --- |
| A 阻塞 sleep（time.sleep） | 16 | 多为有界轮询/制造并发窗口，3 处固定等待有风险 |
| B asyncio.sleep 非零延迟 | 157 行中 75 行为 sleep(0) 确定性让步，31 行 ≤0.04s 小步进，其余 ~51 行含哨兵任务(sleep(60/100/3600))与固定延迟竞速 | 固定延迟后断言的 ~15 处为风险集中区 |
| C 真实时钟（time.time/monotonic/perf_counter） | 104 | 多数是"造数据/相对加减"，少数是 elapsed 上限断言 |
| D datetime.now/fromtimestamp | 16 | 绝大多数为相对运算（安全），2 组需关注 |
| E alarm/setitimer/SIGALRM/threading.Timer | 0 | 无 |
| F TZ 相关（TZ env/tzset/localtime/astimezone） | astimezone 仅个别；无 TZ env 操作 | 已知 3 例 TZ 失败来自"冻结 aware 时钟 + astimezone"组合 |
| G 集合/字典顺序断言 | 候选 10 处，逐一核验后 0 例真隐患 | 见 §4 |
| H 随机性 | 20 处全部已播种（random.Random(seed) 或 patch random.random） | 无隐患 |

## 2. 高风险：固定延迟后断言（真正竞速）

### C1 tests/services/partners/test_zulip_channel.py —— 9 处
- 位置：535、554、567、571、590、609、628、648、671（模式一致：`ch._on_message(msg)` 投递到事件循环 → `await asyncio.sleep(0.1)` → `assert_awaited_once()/assert_not_awaited()`）。
- 触发条件：消息处理链路（含 mock bus）在 CI 高负载下 >100ms 才完成，断言先于副作用执行 → 失败；`assert_not_awaited` 变体则可能掩盖慢处理（100ms 后仍未过滤成功时反而"通过"）。
- 建议：改为有界轮询（如 `for _ in range(200): if bus.publish_inbound.await_count: break; await asyncio.sleep(0.005)`），负向断言在轮询窗口结束后再做；文件内 `asyncio.sleep(100)` 哨兵任务（707、728、1045）无风险。

### C2 tests/runtime/test_background_leader.py —— 真实时钟租约竞速
- 位置：48-56、90-99（`lease_ttl_seconds=0.08, renew=0.02, election=0.01` + `asyncio.sleep(0.05)` 后断言 `len(running)==1`、交接后集合、命令恰好处理一次）；121-127（slow_start 场景 `asyncio.wait_for(started,0.1)` + `sleep(0.08)` 后抢租约）。
- 触发条件：任一协程被调度延迟超过 50ms（与 20ms 续租周期同量级），选举/交接停在中间态 → 断言失败；或 leader 转移未完成时命令被旧 leader 处理 → `handled` 序列断言失败。
- 建议：给 MemoryCoordinator/BackgroundLeaderSupervisor 注入可控时钟（或把周期参数放大 + 条件轮询直到状态收敛，上限放宽到 2-5s）；断言"最终一致"而非"固定延时后恰为此态"。

### C3 tests/services/session/test_turn_runtime_subscribe.py:233
- 位置：`asyncio.create_task(_collect())` 后固定 `await asyncio.sleep(0.04)`，随后断言订阅已挂上、`events==[]`、更新状态后收到的恰为 `["done"]`。
- 触发条件：订阅注册 >40ms 时 `update_turn_status("completed")` 先于订阅生效 → `wait_for(task,1)` 收不到 done 或事件缺失。
- 建议：同文件 168-173 已有正确范式（`for _ in range(200): if execution.subscribers: break`），照抄即可。

### C4 tests/runtime/coordination/test_journal_recovery.py:58、87
- 位置：`publish_event(...)` 后固定 `await asyncio.sleep(0.02)` 再触发 recovery，断言"未落盘事件被恢复/重试"。
- 触发条件：flush 延迟 >20ms 时事件已持久化，走另一分支 → 断言的是"另一条路径"，测试语义漂移甚至失败。
- 建议：提供确定性 flush 钩子（或注入 pending-queue 状态），不用真实时间窗口区分分支。

### C5 tests/services/cron/test_cron_repository.py:21-37
- 位置：持锁线程 `time.sleep(0.3)`，主线程断言 `waited >= 0.2`（下限断言）。
- 触发条件：主线程在 `entered.wait(2)` 返回后被调度延迟 >0.3s，锁已释放，`waited≈0` → 失败。
- 建议：断言"曾发生阻塞"（如先记录 acquired 事件顺序），不做真实时间下限；或下限放宽至 0 并补充"持有期间获取必失败"的行为断言。

## 3. 中风险：真实时钟上限断言（elapsed 上界）

| 位置 | 断言 | 触发条件 | 建议 |
| --- | --- | --- | --- |
| tests/services/search/test_web_search_runtime.py:888-894 | 批量 deadline 0.05s 后总耗时 `< 0.15` | 线程池饥饿使取消返回 >3× | 上界放宽（≥1s）或改为"deadline 生效"行为断言 |
| tests/services/mcp/test_missing_mcp_dependency.py:76 | `elapsed < _PATCHED_TIMEOUT_S / 2` | 事件循环调度使连接清理耗时超过半预算 | 比例放宽或注入时钟 |
| tests/services/rag/test_llamaindex_image_description.py:163、275 | `< 2.0`、`< 0.8`（超时 0.2/0.1，余量 4-5×） | 多批超时叠加 + 慢 CI | 保留但放宽；或断言"fast 项全部保留且未等 slow 的全时长" |
| tests/services/rag/test_llamaindex_pipeline_stall.py:76、278、298 | `< 10`（宽裕） | 基本安全 | 无需修 |
| tests/services/rag/test_llamaindex_pipeline_stall.py:90-91、118-119、199-200 | 每 0.05s 报进度 vs stall_timeout 0.3（6×） | 单次进度间隔被调度拉大 → 误判 stall → 失败 | 提高 ratio（如 interval/timeout ≥ 10×）或注入时钟 |
| tests/services/test_suggestions.py:765-772 | fake collect `time.sleep(0.05)`（阻塞事件循环）+ 结尾固定 `await asyncio.sleep(0.06)` 兜底 | 后台刷新任务存活跨测试 → 污染下一用例 | 保存任务句柄显式 await/cancel；sleep 换 `asyncio.to_thread` 模拟 |
| tests/services/skill/test_skill_login.py:36-41 | `_await_url` 轮询上限 200×0.02=4s | 慢机上 worker >4s 未产出 URL | 上限提高 + 事件驱动 |
| tests/services/cli_apps/test_provider.py:443-463 | 故障任务 0.05s 后抛出，主流程固定观察窗 `asyncio.run(asyncio.sleep(0.10))` 后断言无泄漏 | 断言为"缺失型"，晚抛不致失败但验证窗不可靠 | 显式 join 故障任务后断言 |
| tests/api/test_upload_off_event_loop.py:81-82 | 0.05s 窗口内 tick 任务必须前进 | 极端调度饥饿 | 低风险，暂不修 |

正面范式（无需修，作为修卡时的模板）：tests/services/llm/test_metrics.py:49（monkeypatch perf_counter）、tests/services/test_singleflight_cache.py:14-19（now 注入）、tests/services/test_suggestions.py:391/414/491-496（TTL 相对运算 + monotonic 节流）、tests/app/test_multiworker_turn_application.py:87-92 与 tests/app/test_waiting_turn_recovery.py:199-206（有界轮询 100×）、tests/tools/test_mineru_models.py:106-113（deadline 轮询）、tests/services/session/test_turn_repository.py:25-28（子进程屏障 15s 上限）、tests/cli/test_chat_terminal.py:47-55（PTY 10s deadline）、tests/utils/test_circuit_breaker.py:47（patch time.time——可用但属全局补丁，建议改注入）。

## 4. 时区 / datetime（测试面）

### C6 tests/agents/chat/test_runtime_context.py —— 已锁定（开放 PR #1732/#1733），本次复现成功
- 位置：31（`FIXED_NOW = datetime(2026, 8, 17, 12, tzinfo=timezone(timedelta(hours=8)))`）× 产品侧 `deeptutor/agents/loop/prompt_blocks.py:245`（`datetime.now().astimezone()`）。
- 失败条件：冻结 aware +08:00 时刻，`.astimezone()` 转到 UTC-9 以西主机 → 日期渲染成 2026-08-16 → 3 例断言失败（test_default_injects_real_current_date_en/zh、test_yaml_template_substitutes_placeholder）。
- 修法（PR v2 已实现）：FIXED_NOW 改 naive，使 `astimezone()` 仅附加本地区域不换算日期；或 pin TZ。main 上仍未合入，合并前 UTC-9 以西机器必红。

### C7 其余 datetime 命中（多为安全相对运算）
| 位置 | 说明 | 风险 |
| --- | --- | --- |
| tests/services/llm/test_usage_ledger.py:34、58、66、75 | `year=datetime.now(timezone.utc).year` 与刚写入的记录比对；仅在 UTC 跨年瞬间（12-31 23:59:59.x）失败 | 极低；建议 year 从记录时间戳推导 |
| tests/api/test_linked_folder_routes.py:272、311 | 测试与产品（deeptutor/api/routers/knowledge.py:1190）都用 naive `fromtimestamp(mtime)`，两端同主机时区一致 | 低；两处须保持成对一致，任一侧改 aware 即错位 |
| tests/services/cron/test_cron_tool.py:90 | `datetime.now().astimezone()+1h` 仅验证 job 创建，不断言时间戳；夏令时跳变时 +1h 可能落在不存在时刻 | 低 |
| tests/knowledge/test_manager_list.py:79、tests/api/test_task_id_manager.py:18、tests/services/memory/test_recall.py:17、tests/multi_user/test_guardians.py:376、tests/services/embedding/test_retry_after.py:71/114、tests/services/partners/test_channel_links.py:83、tests/video_learning/test_invidious_account.py:487、deeptutor/learning/tests/*（time.time 相对加减） | 相对时间构造/过期数据，无墙钟耦合 | 安全 |
| deeptutor/learning/tests/test_storage.py:377-383 | `sleep(0.01)` 后断言 `updated_at >= old`（含等号，容忍同精度） | 低 |
| tests/services/memory/test_ids.py:20-25 | ULID 前缀 `<=` 比较，仅时钟回拨才失败 | 低 |

## 5. 集合/字典顺序 —— 未发现真隐患（核验记录）

- `resolve_mentions().targets/unknown_mentions`（tests/services/partner_groups/test_manager.py:84-100、160、242、480）：底层是 `member_ids: list[str]`（deeptutor/services/partner_groups/manager.py:1215-1236 构造 tuple），顺序确定。
- `list(subject.values)`（test_singleflight_cache.py:33）、`list(loaded)`（test_state_and_paths.py:126/136）、`list(manager.channels)`（test_channel_manager.py:36）、`list(index)`（deeptutor/learning/tests/test_topic_materials.py:164）、`list(channel._working_reactions)`（test_feishu_reply_delivery.py:271）：均为 dict 插入序，确定。
- 402 处 `json.dumps` 无 sort_keys 的用法中，断言均为 `not in` 子串或 round-trip 相等，与键序无关。
- PYTHONHASHSEED 敏感点：无 set 直接迭代输出断言。

## 6. 抽样运行（限时、只读）

宿主无 GNU timeout，用 `perl -e 'alarm N; exec @ARGV'` 限时，pytest 加 `-p no:cacheprovider`（不写缓存，仓库零改动）：

| 命令 | 结果 |
| --- | --- |
| `TZ=Pacific/Honolulu … pytest -q tests/agents/chat/test_runtime_context.py`（alarm 300） | **3 failed / 2 passed**（复现 C6：en/zh/yaml 模板 3 例日期断言得 2026-08-16） |
| `TZ=UTC …` 同上 | 5 passed |
| `TZ=America/New_York …` 同上 | 5 passed（冻结时刻 +08:00 正午恰落在当地零点，边界幸运通过——说明该失败随主机时区"间歇出现"，正是 flaky 本质） |
| `pytest -q tests/services/memory/test_ids.py tests/utils/test_circuit_breaker.py tests/services/test_singleflight_cache.py`（alarm 600） | 22 passed |

## 7. 修复卡候选（按优先级）

1. zulip 频道测试去固定 sleep（9 例，1 文件，机械改动）——事件/计数轮询替换。
2. background_leader 真实时钟竞速（3 用例）——注入时钟或收敛轮询，参数放大。
3. turn_runtime_subscribe:233 固定 0.04s → 复用同文件有界轮询（1 行级改动）。
4. journal_recovery flush 窗口确定性化（2 处）。
5. cron_repository 锁阻塞断言改行为序（1 处）。
6. elapsed 上界族放宽：web_search_runtime:894、missing_mcp_dependency:76、llamaindex_image_description:163/275（4 处，纯常数调整）。
7. pipeline_stall 进度/超时比例放大（3 处循环）。
8. suggestions 后台任务显式收尾（1 处）。
9. usage_ledger 年份从数据推导（4 处，防御跨年）。
10. （已锁定，待人决策）runtime_context TZ：PR #1732/#1733 择一合入。

## 8. 边界说明

- 未改动任何产品或测试代码；抽样仅运行只读测试（见 §6），无服务器/守护进程/后台进程残留。
- upstream 无同名/同主题开放 PR（已检索 flaky/timezone/timing/tz 关键词，仅 #1732/#1733 为本项先例）。
