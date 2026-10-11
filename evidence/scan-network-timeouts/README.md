# 网络外呼 timeout/重试参数一致性清点（scan-network-timeouts）

- 基线: origin/main `6cf793bd868ba5ecbe64722936d4be8fab5a01df`（release v1.6.14）
- 日期: 2026-10-11
- 方式: 静态清点（只读代码，未改代码、未发起真实外呼）
- 范围: requests / httpx / SDK 外呼点三类问题 —— timeout 缺失、重试缺失或无界、超时值离群；覆盖 search / subagent / web_source / 同步（source sync）/ 存储客户端面

## 三态口径

- **有界**: 显式 timeout（模块常量、参数默认值或 httpx.Timeout 分档），重试存在时有明确次数/退避上限，或设计上单次调用无需重试。
- **弱**: timeout 或重试部分有界 —— 有意 `read=None`/无 wall-clock 但缺独立兜底、重试无尝试上限、connect 未从整体 timeout 拆分等。
- **缺失**: 外呼点完全无 timeout 且无外层超时包裹（本次未发现该类点）。

## 去重边界（只引用不复述）

- LLM provider 失败路径（`deeptutor/services/llm/*`、generation_http 等外呼的失败/重试语义）→ 由 `scan-provider-failure-parity` 卡覆盖，本表不再清点。
- embedding 并发（`deeptutor/services/embedding/adapters/*` 的并发与失败路径）→ 由 `scan-embedding-concurrency` 卡覆盖，本表不再清点。
- 其余非卡面外呼点（vision / imagegen / voice / videogen / mcp / parsing / partners 渠道等）不在本卡范围内，仅文末"边界外顺带观察"记录 4 处，不做完整清点。

## 三态表

### search 面（services/search + 搜索工具）

| # | 外呼点 path:line | 库/SDK | timeout 取值 | 重试策略 | 三态 | 备注 |
|---|---|---|---|---|---|---|
| 1 | `deeptutor/services/search/providers/serper.py:93` | requests.post | 默认 30s（:50） | 无 HTTP 重试；provider 级 failover 兜底（#14） | 有界 | |
| 2 | `deeptutor/services/search/providers/searxng.py:58` | requests.get | 默认 20s（:45） | 同上 | 有界 | timeout 离群低端 |
| 3 | `deeptutor/services/search/providers/brave.py:38` | requests.get | 默认 20s（:27） | 同上 | 有界 | 离群低端 |
| 4 | `deeptutor/services/search/providers/duckduckgo.py:30` | ddgs SDK（DDGS） | 默认 20s（:24） | 无；failover 兜底 | 有界 | |
| 5 | `deeptutor/services/search/providers/qianfan.py:90` | requests.post | 默认 30s（:48） | 无；failover 兜底 | 有界 | |
| 6 | `deeptutor/services/search/providers/firecrawl.py:89` | requests.post | 默认 60s（:41）；body 内 `timeout` 取 `min(timeout*1000-1000, 300000)`（:73） | 无；failover 兜底 | 有界 | 离群高端（60s，注释声明对齐远端上限） |
| 7 | `deeptutor/services/search/providers/tavily.py:91` | requests.post | 默认 60s（:46） | 无；failover 兜底 | 有界 | 离群高端 |
| 8 | `deeptutor/services/search/providers/serply.py:82` | requests.get | 默认 30s（:50） | 无；failover 兜底 | 有界 | |
| 9 | `deeptutor/services/search/providers/doubao.py:92` | requests.post | 默认 60s（:46，注释声明有意高于 SERP 族） | 无；failover 兜底 | 有界 | 离群高端（有意） |
| 10 | `deeptutor/services/search/providers/aliyun_iqs.py:106` | requests.get | 默认 30s（:58） | 无；failover 兜底 | 有界 | |
| 11 | `deeptutor/services/search/providers/jina.py:84` | requests.get | 默认 60s（:42）；`X-Timeout` 头同步给远端（:71） | 无；failover 兜底 | 有界 | 离群高端 |
| 12 | `deeptutor/services/search/providers/bocha.py:77` | requests.post | 默认 30s（:39） | 无；failover 兜底 | 有界 | |
| 13 | `deeptutor/services/search/providers/zhipu.py:92` | requests.post | 默认 30s（:43） | 无；failover 兜底 | 有界 | |
| 14 | `deeptutor/services/search/__init__.py:201-230` | 编排层 | 逐 provider 继承各自 timeout | failover 遍历 `attempts` 有界列表，逐个 try/except | 有界 | 最坏情况串行等待 = Σ(各候选 timeout) |
| 15 | `deeptutor/tools/paper_search_tool.py:87`（`_REQUEST_TIMEOUT_S=30` :19） | arxiv SDK + asyncio.wait_for | 30s | 429 时单次重试（:99-106），延迟 3s（`_RETRY_DELAY_S=3.0` :21）后重试一次 | 有界 | |
| 16 | `deeptutor/tools/zotero_search.py:38-40`（`Timeout(15.0, connect=5.0)` :18） | httpx.AsyncClient | 15s / connect 5s | 无 | 有界 | |

### subagent 面（services/subagent）

| # | 外呼点 path:line | 库/SDK | timeout 取值 | 重试策略 | 三态 | 备注 |
|---|---|---|---|---|---|---|
| 17 | `deeptutor/services/subagent/hermes_remote_client.py:86,:101`（常量 :13 `_REQUEST_TIMEOUT`） | httpx.AsyncClient | connect=10 / read=30 / write=30 / pool=10 | 无自动重试；失败上抛由 backend 归类 | 有界 | |
| 18 | `deeptutor/services/subagent/hermes_remote_client.py:123-128`（:14 `_STREAM_TIMEOUT` read=None） | httpx 流式 | connect=10 / read=None（流式）/ write=30 / pool=10 | 无 | 有界 | 逐事件 idle 兜底见 #19 |
| 19 | `deeptutor/services/subagent/hermes_remote.py:212-219` | anyio.fail_after | `idle_timeout_seconds` 默认 600（`config.py:83`），clamp 1..86400（`config.py:168`） | 超时后主动 stop run（:216-219） | 有界 | |
| 20 | `deeptutor/services/subagent/opencode_family.py:161`（client :144-145，常量 :70） | httpx.AsyncClient | connect=10 / **read=None** / write=60 / pool=10；POST message 无单呼 timeout、无外层 wall-clock | 无 | **弱** | :69 注释声明产品契约"无read超时"；仅回合取消（abort :166 timeout=5s）可中断，远端静默挂起时 consult 无限等待 |
| 21 | `deeptutor/services/subagent/opencode_family.py:166,:366,:95,:395` | httpx / asyncio.wait | abort 5s；permission 回执 10s（:366）；CLI 探测 15s（:65,:95）；attach 等待 15s（:66,:395） | 无 | 有界 | |
| 22 | `deeptutor/services/subagent/opencode_server.py:139,:146` | httpx.AsyncClient | client 未显式传 timeout（httpx 默认 5s 兜底）；探测 GET 显式 2s（:146） | 就绪轮询 `while True` 受 `_READY_TIMEOUT_SECONDS=30s` deadline 约束（:41,:138-151） | 有界 | :139 标注：依赖 httpx 默认值，实际每次调用均显式覆盖 |
| 23 | `deeptutor/services/subagent/process.py:131,:156-175` | asyncio.wait_for | 终止宽限 5s（:131）；`probe_version` 默认 8s（:156，opencode 族覆盖 15s） | 无 | 有界 | |
| 24 | `deeptutor/services/subagent/process.py:9`（consult 等待） | 本地 CLI 进程 | **无 timeout**（:9 注释声明产品契约） | 无 | **弱** | 有意契约（对齐 #20 read=None），但与 hermes 的 idle_timeout 机制不一致：本地后端无任何 wall-clock/心跳兜底 |

### web_source 面（tools/web_fetch + services/web_source）

| # | 外呼点 path:line | 库/SDK | timeout 取值 | 重试策略 | 三态 | 备注 |
|---|---|---|---|---|---|---|
| 25 | `deeptutor/tools/web_fetch.py:125`（client :169-171，`DEFAULT_TIMEOUT_S=15.0` :40） | httpx.AsyncClient | 15s，max_redirects=5 | 无重试；手工重定向循环 `range(MAX_REDIRECTS+1)` | 有界 | 单次抓取语义 |
| 26 | `deeptutor/services/web_source/crawler.py:403-406`（timeout 复用 #25 的 15s） | httpx.AsyncClient | 15s，max_redirects=5 | `_MAX_RETRIES=2`（:189），指数退避 0.5s/1s，状态码 {429,500,502,503,504}（:188,:248-277） | 有界 | |
| 27 | `deeptutor/services/web_source/robots.py:134-170` | httpx（复用 #26 client） | 继承 client 15s | 重定向跳数 `range(6)` 有界；5xx/429 直接判不可用，不重试 | 有界 | |
| 28 | `deeptutor/services/web_source/snapshot_assets.py:93,:102,:134-135` | httpx.AsyncClient | `DEFAULT_TIMEOUT_S` 15s，max_redirects=5 | 无 | 有界 | 单图 8MB 上限、24 张上限 |
| 29 | `deeptutor/services/web_source/sync.py` | 无直接外呼 | — | — | n/a | 全部经由 #26 crawler，边界随之 |
| 30 | `deeptutor/services/web_source/scheduler.py:286-290` | 调度层 | 单次执行受 #26 约束 | 失败按 `attempt+1` 退避重排（封顶 sync interval），**attempt 无上限**，直到取消/成功 | **弱** | 有意持续重试；坏源无"最大尝试后转 error 态"出口 |

### 同步面（github source sync）

| # | 外呼点 path:line | 库/SDK | timeout 取值 | 重试策略 | 三态 | 备注 |
|---|---|---|---|---|---|---|
| 31 | `deeptutor/services/github_source/client.py:83,:96`（`DEFAULT_TIMEOUT_S=30.0` :21） | httpx.AsyncClient | 30s | 无 HTTP 重试；单文件 2MB 上限 | 有界 | |
| 32 | `deeptutor/services/github_source/sync_service.py:46-60` | 编排层 | 逐请求 30s | 周期同步（check_interval 3600s + SYNC_INTERVAL_HOURS 陈旧判定），异常记录状态后由下一周期自然重试 | 有界 | 重试=固定周期，无无界循环 |

### 存储客户端面

| # | 外呼点 path:line | 库/SDK | timeout 取值 | 重试策略 | 三态 | 备注 |
|---|---|---|---|---|---|---|
| 33 | `deeptutor/services/pocketbase_client.py:180`（`ping_pocketbase` :164） | httpx.AsyncClient | 5.0s | 无重试，失败降级告警并回退 SQLite | 有界 | 探针口径与 readiness（1.5~3s）不一致，见离群观察 |
| 34 | `deeptutor/services/storage/attachment_store.py`、`file_library.py:116` | 本地文件 / sqlite3 | sqlite busy timeout 30s（:116） | — | n/a | 无网络外呼 |

**汇总: 有界 29 / 弱 3（#20、#24、#30）/ 缺失 0 / n-a 2（#29、#34），共 34 个清点行。**

## 超时值离群观察

1. search 族 20s（searxng/brave/duckduckgo）vs 30s（6 家）vs 60s（firecrawl/tavily/doubao/jina）并存，无共享常量与覆盖区间约束；failover 链最坏串行等待可达 Σ(全部候选 timeout)。
2. subagent 本地/远程 opencode 族无 read/wall-clock（有意契约），而 hermes_remote 有 `idle_timeout_seconds` 机制 —— 同一面内两套语义。
3. 存储探针: pocketbase ping 5s，`services/config/readiness.py` 的 mineru 2s、docling 2s（wait_for 3s）、redis 1.5s —— 探活超时口径不统一。
4. `services/github_copilot_auth.py:65` `httpx.Timeout(20.0, connect=20.0)`：connect 与整体相同，connect 预算未拆分（边界外顺带记录）。

## 修复候选（≤10）

1. `opencode_family.py`（#20）: 为 `POST /session/{sid}/message` 与 SSE 监听增加可配置 wall-clock 上限（语义对齐 hermes `idle_timeout_seconds`），或将"仅回合取消可中断"契约写入配置默认值与监控告警点。
2. `process.py`（#24）: CLI consult 等待增加可选 wall-clock/心跳超时（默认关闭保持现契约），防止 CLI 挂起拖死会话线程。
3. `services/web_source/scheduler.py`（#30）: 为 sync 任务增加最大尝试次数（如 N 次失败后转显式 error 态，仅手动 `retry()` 或编辑可复位），避免坏源无限占用调度。
4. search providers: 引入共享默认 timeout 常量与允许覆盖区间（如 30s 基线，慢引擎显式声明例外），收敛 20/30/60 离散值。
5. search providers: 在 requests Adapter 层加有界重试（如 `Retry(total=1, status_forcelist=[429,500,502,503,504], backoff_factor=0.5)`），减少瞬时抖动直接触发 provider failover。
6. 存储探针口径统一: pocketbase ping 与 readiness 探针超时取同一档（2~5s），并在常量处注明探针语义差异。
7. `github_copilot_auth.py`: connect 从整体 timeout 拆分（如 `Timeout(20.0, connect=5.0)`）。
8. search 工具层: 把 provider `timeout` 参数接入统一配置读取（当前工具层调用不传 timeout，只能吃各 provider 默认值，用户无法调节）。

## 边界外顺带观察（非本卡范围，仅记录不深挖）

- `deeptutor/services/github_copilot_auth.py:65,:73-74,:169-170,:204-205`: Timeout(20, connect=20) ×3 处 — 弱（connect 未拆分）。
- `deeptutor/tools/vision/image_utils.py:23,:79`: REQUEST_TIMEOUT 显式，follow_redirects=True — 有界。
- `deeptutor/tools/tex_downloader.py:83`: requests.get timeout=30，无重试 — 有界。
- `deeptutor/services/research/primitives.py:112,:118`: Timeout(30, connect=10) + asyncio.timeout(45) + 重定向跳数≤4 + 字节预算 — 有界。
