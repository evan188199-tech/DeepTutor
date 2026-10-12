# 导读：keypool 密钥池机制（deeptutor/services/keypool.py）

基线：`origin/main` @ `6cf793bd8`（v1.6.14），分支 `guide/keypool-20261012`。
本文只读分析，不改任何源码。所有结论附 `path:line` 锚点（相对仓库根）。
去重说明：provider 轴见 guide-llm-providers 卡，单测实现见 `tests/services/test_keypool.py`（本文只引用不重复）。

## 一、数据结构

模块只有两个导出物：`KeyPool`（轮换器）与 `primary_api_key`（单钥归约），见 `deeptutor/services/keypool.py:81`。

**KeyPool 内部状态**（构造于 `deeptutor/services/keypool.py:12-20`）：

- `_keys: list[str]`：配置顺序保留、逐项 strip、丢弃空串（:13）；全空则抛 `ValueError`（:14-15）。**不去重**：同一 key 重复出现会占多个轮换槽位，但 strike/冷却状态按 key 字符串共享（`_strikes`/`_cooldown_until` 是以 key 为键的 dict，:18-19），即重复 key 轮换权重翻倍、惩罚状态合一。
- `_cooldown_s`：冷却秒数，默认 60，`max(0, ...)` 钳制（:16）。
- `_next_index`：round-robin 游标（:17）。
- `_strikes: dict[str, int]`、`_cooldown_until: dict[str, float]`：每 key 的 429 计数与冷却截止时刻（:18-19）。
- `_lock: Lock`：`next()` 与 `mark_429()` 全程持锁，线程安全（:20、:39、:55）。
- 时间源用 `monotonic()`（:6、:40、:60），不受系统改时钟影响；冷却截止是绝对时刻而非剩余秒。

**primary_api_key**（`deeptutor/services/keypool.py:63-78`）：把 `str | list[str] | None` 归约为"第一个 key 或 None"；`""`、`[]`、`[""]` 一律返回 `None`（:77-78）。语义是"给不可轮换的边界统一取第一个 key"，注释明示若把 list 直接塞进 Authorization 头会渲染成 `"['sk-a', 'sk-b']"` 产生不可诊断的 401（:66-71）。

**池的定位**：`next()` 的文档字符串明确"池只负责摊负载，不是熔断器"，全冷却时宁可交出最快恢复的 key 也不拒绝服务，由调用方在重试预算耗尽后重抛真实 429（`deeptutor/services/keypool.py:29-37`）。

## 二、轮换语义（谁在建池、每请求怎么取 key）

四个独立建池点，池**不跨 provider / 不跨进程共享**，各自实例各自计数：

1. **Agentic runtime**：`config.api_key` 为 list 时，先按 key 一一构建 SDK client 字典，再包成 `_KeyRotatingClient(KeyPool(keys), clients)`（`deeptutor/runtime/agentic/client.py:133-143`）。每个 key 一个独立 `AsyncOpenAI` 实例，轮换 = 换 client。非 list 路径取 `primary_api_key`（:306、:340）。
2. **LLM provider core**：`OpenAICompatProvider.__init__` 归一化 keys 后建池（`deeptutor/services/llm/provider_core/openai_compat_provider.py:182-186`）。与 agentic 路径不同：这里**只有一个**底层 `AsyncOpenAI` client（用 primary key 构造，:211-219），轮换通过每次请求注入 `Authorization: Bearer <key>` 覆盖头实现（`_create_with_key_rotation`，:236-239）。占位 key 检查只看 primary key（:199-206）。反例守卫：github_copilot 禁止传占位 key，否则池会用占位符覆盖 Authorization（`deeptutor/services/llm/provider_core/github_copilot_provider.py:41-45`）。
3. **Embedding 适配器基类**：config 的 `api_key` 归一化后建池，`self.api_key` 取第一把（`deeptutor/services/embedding/adapters/base.py:159-163`）。子类 `OpenAICompatibleEmbeddingAdapter._auth_api_key()` 每次调 `pool.next()`，本地占位哨兵 `sk-no-key-required` 归空（`deeptutor/services/embedding/adapters/openai_compatible.py:56-61`）；鉴权头按有无 `api_version` 选 `api-key`（Azure）或 `Bearer`（:63-67），每次 `embed()` 开头取一次 key（:174-176）。
4. **MinerU cloud**：每次 parse 调用新建池 `KeyPool(config.api_keys)`（`deeptutor/services/parsing/engines/mineru/cloud.py:89`，凭据校验路径同理 :492），HTTP 层 `_request_json` 每次请求现取 key 拼头（:539-544）。

**next() 取钥算法**（`deeptutor/services/keypool.py:39-51`）：从 `_next_index` 起顺时针找第一个不在冷却期的 key（:41-45）；交出的 key 若刚过冷却期，顺手清零冷却标记与 strikes（:46-48）；推进游标（:49）；全冷却时兜底返回"冷却截止最早"的 key（:51），不推进游标。

**primary_api_key 的消费方**（单钥边界统一归约）：LLMConfig（`deeptutor/services/llm/config.py:77、:157、:207`）、工厂（`deeptutor/services/llm/factory.py:92`）、provider runtime（`deeptutor/services/config/provider_runtime.py:796`）、上下文窗口探测（`deeptutor/services/config/context_window_detection.py:134`）、三个 book block（`deeptutor/book/blocks/animation.py:85`、`figure.py:76`、`interactive.py:75`）、设置连通性测试（`deeptutor/api/routers/settings.py:1960-1962`）。

## 三、失败切换语义（429 计分、冷却、重试预算）

**计分与冷却**（`deeptutor/services/keypool.py:53-60`）：`mark_429` 对未知 key 直接忽略（:56-57）；第 1 次 429 只计数不冷却，第 2 次起冷却 `monotonic() + _cooldown_s`（:58-60）。**strikes 无时间衰减**：只有在 key 冷却期满被 `next()` 再次交出时才清零（:46-48），两次 429 相隔任意久仍会累计触发冷却。

**调用方重试预算**：三处循环统一 `attempts = max(2, len(pool))`，预算耗尽后重抛**真实 429** 而非哨兵错误：

- Agentic：`_KeyRotatingCompletions.create`（`deeptutor/runtime/agentic/client.py:190-205`）：非 429 立即上抛（:200-201）；429 计分后换钥重试（:202-204）；末次上抛（:203-204）；理论兜底 `RuntimeError`（:205）。
- Provider core：`_create_with_key_rotation`（`deeptutor/services/llm/provider_core/openai_compat_provider.py:230-249`）：无池直调（:231-232）；429 计分、末次上抛、否则换钥（:243-248）。调用点覆盖 responses 非流式/重试与流式（:610、:619、:1038、:1051、:1198、:1209）。
- MinerU：`_request_json`（`deeptutor/services/parsing/engines/mineru/cloud.py:531-559`）：429 计分后**无 sleep 立即换钥**（:550-553）；非 429 HTTP 错误转 `MinerUError` 上抛（:554）；预算耗尽抛"rotation exhausted"（:559）。HTTP 200 但业务码非 0 仍判失败（`_check_code`，:570-578）。
- Embedding 是唯一带**等待窗口**的路径（`deeptutor/services/embedding/adapters/openai_compatible.py:243-273`）：429 计分后最多 8 轮限流重试，每轮 sleep `max(Retry-After, 60)` 秒（:250-255），随后重新取钥换头（:257-263）；8 轮仍 429 抛 `EmbeddingProviderError(status=429)`（:265-273）。尝试槽位 `1 + max(_MAX_RETRIES=5, 10)` 显式大于限流轮数，防止 429 的 continue 耗尽循环后 `UnboundLocalError`（:231-235 注释）。
- 非流式 embedding 的网络级重试另算（`deeptutor/services/embedding/adapters/openai_compatible.py:341` 附近，`_MAX_RETRIES` :147），与限流轮数正交。

**一处注释与实现漂移**：embedding 重试分支捕获 `_auth_api_key()` 的 `RuntimeError` 并等 65 秒（`deeptutor/services/embedding/adapters/openai_compatible.py:256-262`，注释称"池内 key 全在冷却……仍取不到才认输"），但现行 `KeyPool.next()` 全冷却时返回最快恢复 key 而不抛错（`deeptutor/services/keypool.py:29-37、:51`），该分支按现实现不可达，属历史版本残留。

## 四、可照做 / 可拆测试的语义清单（验收 ≥3 条）

1. **两击冷却 + 复活清零**：对 2-key 池 `mark_429(k)` 一次不改变 `next()` 的轮换次序；同一 key 累计第二次 `mark_429` 后冷却 60s；冷却期满后 `next()` 重新交出该 key 且 strikes 归零。锚点 `deeptutor/services/keypool.py:44-48、:53-60`（既有覆盖 `tests/services/test_keypool.py:21-36`）。
2. **strikes 不随时间衰减**：key 在两次 429 之间被正常使用任意次，strike 不清零；只有"冷却期满后再被交出"这一条路径清零。锚点 `deeptutor/services/keypool.py:46-48`。可拆测试：t=0 记一击 → 大量成功轮换 → t=1h 再记一击 → 断言进入冷却。
3. **全冷却降级不拒服**：所有 key 冷却中，`next()` 返回冷却截止最早者且不抛错；单 key 池冷却期内继续供钥。锚点 `deeptutor/services/keypool.py:51`、`tests/services/test_keypool.py:39-82`。可拆测试：两 key 分别在 t=0/t=10 进入冷却，t=20 取钥断言返回 t=0 那把。
4. **重试预算 = max(2, N) 且重抛真 429**：N-key 池全部 429 时，任一调用方恰好发起 `max(2, N)` 次上游请求，最终向外抛最后一次真实 429（非 `RuntimeError` 哨兵）。锚点 `deeptutor/runtime/agentic/client.py:190-205`、`deeptutor/services/llm/provider_core/openai_compat_provider.py:230-249`、`deeptutor/services/parsing/engines/mineru/cloud.py:531-559`。
5. **非 429 快速失败**：任何非 429 异常（401/400/网络）立即中止轮换上抛，不消耗后续 key。锚点 `deeptutor/runtime/agentic/client.py:200-201`、`deeptutor/services/llm/provider_core/openai_compat_provider.py:243-244`、`deeptutor/services/parsing/engines/mineru/cloud.py:554`。
6. **embedding 限流窗口**：单次 `embed()` 对持续 429 恰好重试 8 轮后抛 `EmbeddingProviderError(status=429)`，每轮至少等 60 秒且优先采用 `Retry-After`；每轮重新取钥。锚点 `deeptutor/services/embedding/adapters/openai_compatible.py:243-273`。
7. **重复 key 语义**：配置重复 key 时轮换槽位重复（权重翻倍）但 strikes/冷却状态共享；`len(pool)` 计重复。锚点 `deeptutor/services/keypool.py:13、:18-19、:22-24`。可拆测试：`KeyPool(["k","k"])` 断言 `len==2`，一次 `mark_429("k")` 后两槽位同受冷却影响。

## 附：边界与已知边界外

- 池为进程内对象，无跨进程/跨 worker 协调；多 worker 同时打同一 provider 时各池独立计数（建池点见第二节 1-4）。
- 冷却只认 HTTP 429；401/403 无效 key 不会被打入冷却，会原样上抛由上层处理（各调用方非 429 快速失败路径）。
- `primary_api_key` 是唯一"列表→单钥"归约出口，新增消费方应复用它而非自行取 `api_key[0]`（理由见 `deeptutor/services/keypool.py:66-75`）。
