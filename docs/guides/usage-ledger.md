# DeepTutor `usage_ledger` 用量记账域导读

- 基线：origin/main @ `6cf793bd8`（v1.6.14）。
- 范围：`deeptutor/services/llm/usage_ledger.py` 的记录/聚合/持久化契约，写入与读取两条链路，与 usage 统计、配额判断的接点，常见误用点；测试锚点 `tests/services/llm/test_usage_ledger.py`（7 例）。
- 去重：Usage 面板（设置 → Usage）的前端展示、`aggregate_usage` 的年度分桶细节、会话事件通道（DONE `usage_summary` 快照/替换语义）属 guide-usage-stats 轴，本文只在接点处给指针，不展开。
- 所有锚点形如 `path:line`，相对仓库根目录。

## 1. 域定位：独立于会话的持久记账

`usage_ledger` 是"每个账号一份"的 SQLite 账本，路径 `<user_root>/usage.sqlite3`（`deeptutor/services/llm/usage_ledger.py:37-40`）。模块头声明了隐私契约：只存标识符、时间戳和数值测量，提示词、响应、凭据、端点 URL 永不入库（`usage_ledger.py:1-5`）。它与对话存储完全解耦——删除会话不会删掉已入账的消耗（`tests/services/llm/test_usage_ledger.py:72-78`）。

路径解析链：`ledger_path()` → `get_owner_path_service().get_user_root()`（`deeptutor/multi_user/paths.py:200-219`；owner 语义见其 docstring——partner 是合成用户，owner 归属的资产指向 human owner）→ `PathService.get_user_root()` 返回 `<workspace_root>/user`（`deeptutor/services/path_service.py:91,118`）；workspace_root 按运行时 home 解析，优先级为显式参数 > `DEEPTUTOR_HOME` 环境变量 > CWD（`deeptutor/runtime/home.py:28-42`；admin 本地单用户即 `<CWD>/data/user`，`deeptutor/multi_user/paths.py:1-14`）。关键推论：**账本归属在调用触发时由 owner ContextVar 决定，且必须在首个 `await` 之前解析**——见 §2.2。

## 2. 写入线：CallMeasurement → record_call

写入只有一条路：`CallMeasurement.finish()` → `record_call()`（`deeptutor/services/llm/metrics.py:167-178` → `usage_ledger.py:43-73`）。

1. **计量点（谁创建 meter）**——三条传输边界都会挂上 `CallMeasurement`：
   - provider 基类重试包装 `_call_with_retry` → `measure_provider_call`（`deeptutor/services/llm/provider_core/base.py:348-365`）；
   - 原生 OpenAI client 包装 `instrument_client`（`deeptutor/runtime/agentic/client.py:241-259`，实现在 `metrics.py:258-279`）；
   - 非 LLM-SDK 传输自建 meter：perplexity / doubao 搜索直接 `CallMeasurement(...)` 构造（`deeptutor/services/search/providers/perplexity.py:66-72`、`deeptutor/services/search/providers/doubao.py:88-90`），所以搜索消耗同样入账，靠 `provider` 字段区分。
   `measurement_active` ContextVar 保证嵌套计量（provider 层已包、client 层再包）不重复计数（`metrics.py:70-71`）。
2. **owner 与回合归属在构造期捕获**：`CallMeasurement.__init__` 在任何 `await` 之前解析 `ledger_path()` 并读取 `current_usage` 收集器（`metrics.py:74-97`）；`finish()` 把收集器的 `session_id/turn_id/source` 落进行（`metrics.py:175-177`）。收集器由 orchestrator 在回合开始时绑定（`deeptutor/runtime/orchestrator.py:133-137`）；无回合的后台调用（`factory.complete/stream` 直连）三字段为空串（`test_factory_records_background_completion_and_stream_without_turn`）。
3. **单次调用记录**：`finish()` 组装 record（`metrics.py:144-164`）——tokens 三元组、cache/reasoning 细分、时延（ttft/generation/tokens_per_second/cache_hit_rate）、`status`（completed/failed/interrupted）、`estimated`。API 未报 usage 时按字符估算（≈chars/3.5，`metrics.py:127-140`；估算器 `deeptutor/services/llm/usage_estimation.py:1-7`）；三种 usage payload 形状的归一化集中在 `deeptutor/services/llm/usage_frame.py:1-15`。
4. **持久化契约**（`record_call`，`usage_ledger.py:43-73`）：
   - 目录与文件先收敛为私有权限（`ensure_private_directory/file`，`usage_ledger.py:52-56`）；
   - `journal_mode=WAL` + `CREATE TABLE IF NOT EXISTS` + `started_at` 索引（`usage_ledger.py:57-62`）；
   - `INSERT OR IGNORE` 以 `call_id`（uuid4 hex）为主键，同 id 重放安全（`usage_ledger.py:63-73`）；
   - 落库前按白名单 `_CALL_FIELDS`（`usage_ledger.py:15-34`）过滤字段（`usage_ledger.py:71`），且 `json.dumps(..., allow_nan=False)` 拒绝 NaN/Inf。
5. **失败语义**：写账本失败只 `logger.exception`，调用本身照常返回（`metrics.py:179-180`）。账本允许有洞——这是"尽力记账"而非"事务账本"，读取端因此必须有合并兜底（§3）。

## 3. 读取线：usage_records → combined_usage_records

- **区间读** `usage_records(start, end)`（`usage_ledger.py:76-107`）：以只读 URI（`mode=ro`）打开（`:84`），文件或表缺失返回 `[]`（`:80-81,85-86`）；每行经 `TurnUsage.summary()` 重塑成与会话历史同构的 record（`created_at/session_id/turn_id/activity_id/source/summaries`，`:93-107`），下游聚合因此无需区分来源。
- **合并读** `combined_usage_records(history, start, end)`（`usage_ledger.py:141-172`）：把会话历史与账本按 `call_id` 去重——先按 500/批查哪些历史 call 已入账（`:162-171`，占位符拼接带 `# nosec B608` 注记），`merge_records` 只保留"历史独有"调用再拼上账本记录（`:110-138`，契约 docstring `:116`）。这兜住 §2.5 的"账本有洞"：写入失败的那次调用还能从会话快照找回；反之已入账的调用不会因历史也在而被数两次。
- **跨年归属**：账本日期是权威——12 月 31 日发起、1 月 1 日结束的调用留在 2025 的桶里（`usage_ledger.py:146-156`；测试 `test_cross_year_calls_keep_their_original_date_without_snapshot_duplicates:155-177`）。
- **当前唯一消费方**：`GET /api/settings/usage`（`deeptutor/api/routers/settings.py:2415-2453`）遍历 workspace 收历史记录（`:2437-2449`）→ 线程池里跑 `combined_usage_records`（`:2450-2452`）→ `aggregate_usage`（`deeptutor/services/session/usage_statistics.py:160`），输出 `UsageStatistics`（`usage_statistics.py:43-53`）。

## 4. 接点一：与 usage 统计的分界

- 账本是"原始行"层，usage 统计是"聚合"层；两者以 `combined_usage_records` 的输出 record 形状为唯一接缝（§3 第一条）。改这个形状（新增字段、动 `summaries` 结构）必须同时过 `aggregate_usage` 和会话历史通道（后者属 guide-usage-stats 轴）。
- 双通道去重的单点在 `merge_records`（含 `persisted_ids` 参数）：谁缺谁补、如何防双算，语义全部收敛在这一个函数。不要在别处再写一份 call_id 去重。

## 5. 接点二：与配额判断的关系——没有接点，这本身就是结论

账本是被动记账，不做任何闸门：没有代码在调用前读账本来决定"还能不能用"。仓库里的配额相关机制均与账本无关：

- provider 侧配额/限流是**错误分类**：消息含 `rate limit / 429 / quota` 归入 `LLMRateLimitError`（`deeptutor/services/llm/error_mapping.py:137-140`），别名 `ProviderQuotaExceededError`（`deeptutor/services/llm/exceptions.py:161-162`）；
- 本地并发/RPM 保护是 `TrafficController`，内存态计数，与账本无关（`deeptutor/services/llm/traffic_control.py:13-30`）。

误用点：想做"用量超限即拒绝"时，不要把 `usage_records` 当闸门用——它面向面板查询（`timeout=5`、只读、无锁），且账本允许有洞（§2.5）；配额执行需要单独的同步预算组件，账本只做事后对账。

## 6. 常见误用点

1. **往 call dict 塞敏感内容**：白名单在落库前剥掉（`usage_ledger.py:71`），且测试断言库文件原始字节不含 prompt/answer（`tests/services/llm/test_usage_ledger.py:40-42`）。新字段要入账本必须显式加进 `_CALL_FIELDS`，否则静默丢弃。
2. **手动构造 record 带 NaN**：`allow_nan=False` 会让整次写入抛错、再被 §2.5 的 catch 吞成静默数据洞。可空测量一律用 `None`（`metrics.py:152-163` 的守卫是范本）。
3. **绕开 `record_call` 写第二路**：写路径唯一。`record_call(path, ...)` 的显式 `path` 参数供测试注入，业务代码一律走 `ledger_path()`。
4. **读侧拿读写连接**：读路径是 `mode=ro` URI（`usage_ledger.py:84`）；直接 `sqlite3.connect(path)` 可写会绕过 `ensure_private_file` 的权限收敛。
5. **自造 call_id**：主键冲突在 `INSERT OR IGNORE` 下是静默丢行（无异常、无计数）。call_id 一律 `uuid4().hex`（`metrics.py:78`）。
6. **把估算值当精确值**：`estimated=True` 的行 tokens 是 chars/3.5 估算；消费端按 `call_details[].estimated` 区分，聚合层有 `estimated_calls` 单列（`usage_statistics.py:27`）。
7. **破坏测试隔离**：autouse fixture `_isolate_usage_ledger` 把 `ledger_path` 打到 tmp_path（`tests/conftest.py:306-312`，"Mocked model calls must never enter the developer's real usage totals"）。它生效依赖 `metrics.py` 在调用点惰性 `from .usage_ledger import ledger_path`（`metrics.py:82`，`record_call` 同理 `:168`）——若改成模块级 import，monkeypatch 失效，mock 调用会写进开发者真实账本，且所有账本测试悄悄共享一份库。

## 7. 测试锚点（tests/services/llm/test_usage_ledger.py，基线 7 passed ≈0.5s）

| 用例（行） | 钉住的契约 |
| --- | --- |
| `test_factory_records_background_completion_and_stream_without_turn:25` | 无回合后台调用（complete+stream）各记一行；账本字节不含 prompt/answer；空归属在聚合层 `sessions==0` |
| `test_ledger_and_saved_turn_merge_once_with_partial_write_recovery:46` | 双 `finish()` 只计一次；账本/历史按 call_id 合并；账本写失败的调用从历史找回；删会话不删消耗 |
| `test_owner_is_captured_before_async_work_and_nested_calls_count_once:82` | owner 在 await 前捕获；并发双用户互不串账；嵌套 instrumentation 不重复计数 |
| `test_interrupted_provider_call_is_recorded_and_propagates:119` | `CancelledError` → 行状态 `interrupted`，异常继续上抛 |
| `test_perplexity_search_records_its_separate_llm_transport:134` | 搜索传输入账，`provider=perplexity` |
| `test_cross_year_calls_keep_their_original_date_without_snapshot_duplicates:155` | 跨年调用归账本原始日期，历史快照不重复计数 |
| `test_doubao_search_records_response_api_tokens:180` | Responses API 的 `input_tokens/output_tokens` 形状归一化入账 |

复跑：`python -m pytest -q -p no:cacheprovider tests/services/llm/test_usage_ledger.py`
