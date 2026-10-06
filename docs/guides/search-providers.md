# DeepTutor `services/search/providers` 搜索供应商导读

- 基线：origin/main @ `f07029cfc`（v1.6.13）。
- 范围：`deeptutor/services/search/` 下的 providers 注册与 14 个供应商实现，以及它们共同依赖的 `base.py` / `types.py` / 上层 `web_search()` 编排。
- 所有锚点形如 `path:line`，相对仓库根；本导读不改任何代码。
- 边界：LLM 供应商（`deeptutor/services/llm/`）是另一子系统，见 guide-llm-providers 卡；本文只在 `doubao.py:88` / `perplexity.py:66` 的用量计量处与其交界。

## 1. 模块地图

```
deeptutor/services/config/provider_runtime.py:87   SEARCH_PROVIDERS 规格表（唯一事实源）
        │ stamp 元数据（display_name / requires_api_key / supports_answer）
        ▼
deeptutor/services/search/providers/__init__.py:27 register_provider 装饰器 → _PROVIDERS:20 进程注册表
        │ import 副作用注册（__init__.py:170-207）
        ▼
deeptutor/services/search/base.py:20   BaseSearchProvider 抽象基类（凭证、proxy、search() 契约）
        │ 每个实现一个文件，统一返回
        ▼
deeptutor/services/search/types.py:48  WebSearchResponse（+ Citation:13 / SearchResult:32）
        │
        ▼
deeptutor/services/search/__init__.py:131  web_search() 编排：凭证解析 → 降级链 → 源过滤 → 归并
        │
        ├─ deeptutor/services/search/source_filter.py   引用安全过滤（独立导读范围，略）
        └─ deeptutor/services/search/consolidation.py:138 AnswerConsolidator（SERP→答案）

上层入口：deeptutor/tools/web_search.py（纯 re-export）；Settings 探活 deeptutor/services/settings/provider_probe.py
```

分层一句话：**规格表决定"有哪些供应商"，注册表决定"类能不能被实例化"，基类决定"实例怎么拿凭证"，`web_search()` 决定"一次查询怎么降级、怎么合成答案"。**

## 2. 公共契约

### 2.1 基类 `BaseSearchProvider`（`deeptutor/services/search/base.py:20`）

- 类属性面：`name/display_name/description/requires_api_key/supports_answer/BASE_URL/API_KEY_ENV_VARS`（base.py:26-33）。除 `API_KEY_ENV_VARS` 是遗留展示元数据外，其余由注册器从规格表盖戳（providers/__init__.py:51-53）。
- 凭证解析：`__init__` 里 `api_key` 缺省时走 `_get_api_key()`（base.py:48-55），**按供应商名**去 Settings > Catalog 的 search profile 找（`search_provider_credentials`，config/provider_runtime.py:1409-1430），不会借活跃 profile 的别家 key。缺 key 且 `requires_api_key` 时抛 `ValueError`（base.py:52-54）。
- 抽象方法：`search(query, **kwargs) -> WebSearchResponse`（base.py:61）。`is_available()`（base.py:74）只检查 key 存在，不发网络请求。
- `self.proxy` 来自构造 kwargs（base.py:58），所有 HTTP 供应商在请求前组装 `proxies={"http":…, "https":…}`（如 zhipu.py:90-91）。

### 2.2 `search()` 的统一入参约定

约定（由测试锁死，tests/services/search/test_search_providers.py:1-7）：每个供应商接受 `query, max_results, timeout, **kwargs`，并必须：

1. **尊重 `max_results`**——哪怕 API 参数名不同（映射见 §3 表"上限参数"列）；
2. **尊重 `proxy`**——组装 requests proxies；
3. **客户端钳制结果数**——API 无 count 参数或上限不同的，在本侧截断（duckduckgo.py:29、searxng.py:73、aliyun_iqs.py:111、jina.py:93-94、serply.py:86）；
4. **接受 `base_url` 覆盖**——自托管网关可不改类直达（zhipu.py:72、firecrawl.py:66、bocha.py:63、doubao.py:71、qianfan.py:70、aliyun_iqs.py:89、serply.py:71；searxng 是必填参数本身，searxng.py:48-49）。

### 2.3 响应归一化（`types.py`）

- `WebSearchResponse`（types.py:48）：`answer` 字段只有 `supports_answer=True` 的供应商填写，SERP 供应商一律空串、由归并器补答案。
- `Citation`（types.py:13）与 `SearchResult`（types.py:32）字段一一平行；每个供应商在循环里同时构建两份列表（如 zhipu.py:99-131）。`Citation.content/icon/website/web_anchor` 等富字段源于 Qianfan 的原生响应（qianfan.py:10-12）。
- `metadata["finish_reason"]` 全部给 `"stop"`（doubao 用 Ark 的 status，doubao.py:179）；`usage` 仅三家有值：firecrawl 记 credits（firecrawl.py:134）、jina 记 tokens（jina.py:144-156）、doubao/perplexity 记 LLM token（doubao.py:174-178、perplexity.py:86-100）。
- `to_dict()`（types.py:61）输出带 `response.content/role` 的向后兼容外形，是 `web_search()` 的最终返回形状。

## 3. 供应商差异表

规格（label / 凭证 / fallback / answer）以 `config/provider_runtime.py:87-119` 为准；下表行序即该表插入序（= Settings 下拉序）。

| 供应商 | 实现（类行） | HTTP | 上限参数（钳制） | timeout 默认 | 自写答案 | 关键差异 |
|---|---|---|---|---|---|---|
| duckduckgo | duckduckgo.py:14 | ddgs 库 | 内部 1-10（:29） | 20s | 否 | 零配置；软降级终点（provider_runtime.py:122） |
| brave | brave.py:16 | GET | `count` 1-10（:34） | 20s | 否 | 最瘦 SERP，`age` 进 date（:55） |
| tavily | tavily.py:27 | POST | `max_results` 1-20 | 60s | **是** | `include_answer=True` 默认开（:40）；score 透传（:122） |
| jina | jina.py:30 | GET 路径传 query | 无 API 参数，客户端截断（:93-94） | 60s | 否 | `enrich` 开关控制全文+图片头（:68-75）；usage 汇总 tokens（:144-156） |
| searxng | searxng.py:34 | GET | 客户端 1-10（:73） | 20s | 否 | 唯一 `base_url` 必填（:48）；URL 校验 `_validate_base_url`（:20）；JSON schema 校验 `SearxngResponseError`（:16） |
| perplexity | perplexity.py:22 | 三方 SDK | —（不可控） | **无 timeout 参数**（:46-52） | **是** | 懒加载客户端（:32-44）；唯一走 SDK 而非裸 requests 的 |
| serper | serper.py:34 | POST | `num`（max_results 优先覆盖，:72-73） | 30s | 否 | search/scholar 双模式（:43）；answerBox/knowledgeGraph 进 metadata（:174-194）；scholar 富字段进 attributes（:133-148） |
| serply | serply.py:38 | GET 路径传 query | `num` 1-100 + 客户端截断（:72,86） | 30s | 否 | search/news/scholar 三垂直，各自响应壳（`_result_rows`，:167-174）；news 去 HTML 标签（:135） |
| firecrawl | firecrawl.py:27 | POST | `limit` 1-100（:69） | 60s | 否 | `scrape=True` 才抓全文 markdown（:79-80）；API 侧 timeout 收敛到 <300s（:73）；success 标志即错误（:94-95） |
| doubao | doubao.py:32 | POST（Ark Responses） | `tools[0].limit`（:75） | 60s | **是** | 搜索是模型工具不是端点（文件头 :4-8）；`sources` 含头条/抖音（:26）；citation 从 `url_citation` 注解抽取并按 URL 去重（:112-134）；CallMeasurement 计量（:88-108） |
| bocha | bocha.py:26 | POST | `count` 1-50（:68） | 30s | 否 | 200 内 `code` 非 0/200 即错误（:83-84）；`summary` 长摘 要进 content（:95） |
| zhipu | zhipu.py:29 | POST | `count` 1-50（:77） | 30s | 否 | query 硬截 70 字（:25,74）；engine/recency 白名单校验（:22-23,64-71） |
| qianfan | qianfan.py:34 | POST | `top_k` 1-50（:75） | 30s | 否 | query 硬截 72 字（:28,72）；保留原生 citation id（:125-126）；200 内 `code` 校验（:98-99） |
| aliyun_iqs | aliyun_iqs.py:42 | GET | 固定页 10，客户端截断（:28,111） | 30s | 否 | X-API-Key 头（:102）；epoch ms 转 ISO 日期（:31-38）；rerank 开关（:57） |

其他横切差异：

- **方法与编码**：GET-路径编码型（jina.py:78-79、serply.py:81-82）vs GET-params 型（brave.py:34、searxng.py:51-54、aliyun_iqs.py:90-98）vs POST-json 型（其余）。IQS 的布尔要手动转小写字符串（aliyun_iqs.py:94-97）。
- **参数白名单校验**（HTTP 前抛 ValueError）：zhipu（engine/recency）、firecrawl（category）、bocha（freshness，日期区间放行 :58-62）、qianfan（recency）、aliyun_iqs（time_range/industry）、serply（mode）、doubao（sources）。serper/tavily/jina/brave/duckduckgo/searxng 不校验。
- **"200 里藏错误"**：bocha `code`（:83）、qianfan `code`（:98）、doubao `error`（:96）、firecrawl `success`（:94）四种口径各写各的，无共享工具函数。

## 4. 超时 / 重试 / 异常策略

- **超时**：每个供应商 `timeout` 参数直接传给 requests（或拼进 Firecrawl payload，firecrawl.py:71-73）。默认值三档：20s（duckduckgo/brave/searxng）、30s（五个中国系 + serper/serply）、60s（firecrawl/tavily/jina/doubao）。**perplexity 没有任何超时旋钮**（perplexity.py:46-52，透传三方 SDK）。
- **重试**：供应商内部**零重试**——一次 HTTP 失败即抛。重试语义全部上移到 `web_search()` 的降级链：`[所选供应商, *search_fallback_candidates(), duckduckgo]`（search/__init__.py:197-227）；候选来自用户配置的其他 search profile（config/provider_runtime.py:1447-1474），逐个尝试、失败记录进 `failures`。全链失败抛 `Exception("web search failed: …")`（search/__init__.py:226-227）。
- **凭证缺失误礼**：`soft_fallback=True` 的供应商缺凭证静默换 duckduckgo（search/__init__.py:176-183；规格表注释 provider_runtime.py:65-72）；付费/中国系 `soft_fallback=False`，缺凭证直接 raise——配置过的付费供应商不许背后变 DuckDuckGo。
- **异常类型**：多数供应商抛裸 `Exception(f"{X} API error: {status} - {text}")`（zhipu.py:94、firecrawl.py:91、brave.py:40、bocha.py:79、qianfan.py:92、aliyun_iqs.py:108、jina.py:88、tavily.py:99、doubao.py:94）。例外三处：serper 有专属 `SerperAPIError`（serper.py:27）；searxng 用 `requests.HTTPError`（:61）+ `SearxngResponseError(ValueError)`（:16）；参数校验一律 `ValueError`。**对降级链来说都是 Exception，类型不影响行为**——降级只靠 `except Exception`（search/__init__.py:213）。
- **计量**：只有答案型供应商接 `CallMeasurement`（doubao.py:88-108 失败也要 `finish(status="failed")`；perplexity.py:66-78）。SERP 供应商不计入 LLM 用量账本。

## 5. Provider 注册与新增供应商步骤

### 5.1 注册机制

1. **规格表是唯一事实源**：`SEARCH_PROVIDERS`（config/provider_runtime.py:87-119），`SearchProviderSpec`（:55-83）携带 `label/requires_api_key/requires_base_url/soft_fallback/supports_answer`。插入序即 UI 序。
2. **装饰器盖戳**：`@register_provider("name")`（providers/__init__.py:27-57）把类名小写、从规格表抄 display_name 等元数据进 `_PROVIDERS`；**规格表里没有的名字不进注册表**——类保持可 import 但 `get_provider` 拒绝（:48-50,75-83）。
3. **废弃名处理**：`DEPRECATED_SEARCH_PROVIDERS = {exa, baidu, openrouter}`（provider_runtime.py:125）经 `_DEPRECATED_UNSUPPORTED`（providers/__init__.py:21-24）在 `get_provider`/`web_search` 双层拦截并给出可用列表（providers/__init__.py:76-83、search/__init__.py:86-98）。
4. **启动期注册**：`_register_builtin_providers()`（providers/__init__.py:170-207）import 全部模块触发装饰器；新文件必须同时加进 import 列表和 `_ = (…)` 元组。
5. **下游自动跟随**：Settings 下拉、连接字段表单、探活按钮全部从规格表派生（provider_runtime.py:73-76；探活 services/settings/provider_probe.py，路由 api/routers/settings.py:1929,1965）；`get_providers_info()`（providers/__init__.py:113-147）同时输出 deprecated 条目给前端。

### 5.2 新增供应商检查单（可按序拆卡执行）

1. 建文件 `deeptutor/services/search/providers/<name>.py`：类继承 `BaseSearchProvider`，`@register_provider("<name>")`，`search()` 遵守 §2.2 四条（max_results 映射 + 钳制、proxy、base_url 覆盖、timeout 参数）。
2. 规格表加一行（provider_runtime.py:87-119）：中系/付费供应商务必 `soft_fallback=False`（理由见 §4）；会自己写答案才 `supports_answer=True`。
3. `_register_builtin_providers` 加 import + 元组项（providers/__init__.py:172-204）。
4. `API_KEY_ENV_VARS` 按该厂商惯例填（真实凭证只看 search profile，此元数据仅展示）。
5. 若是 SERP 型且响应有富结构（knowledge graph 等），才考虑给 `PROVIDER_TEMPLATES` 加模板（consolidation.py:29；现仅 serper/jina/serper_scholar 三条，其余走 `_format_simple_results` 兜底 consolidation.py:347）。
6. 测试：加进 `_NEW_PROVIDERS` 参数表（tests/services/search/test_search_providers.py:142-151）自动获得共享旋钮×3 的用例；响应壳特殊的往 `_EMPTY_BODY`（:126-134）补 key，并写一条专属映射测试（参考 doubao:215 / qianfan:274 / aliyun_iqs:310 / bocha:345 / serply:423-495）。
7. 有 `requires_base_url` 的（自托管类）确认 Settings 无默认 base_url 注入（api/routers/settings.py:652 注释）。

## 6. 测试空白清单（可拆卡条目）

现有覆盖（tests/services/search/）：

- `test_search_providers.py`（19 用例）：serper×2、tavily+brave×1、jina×1、规格元数据×1、六家"新供应商"参数化×3（max_results/proxy、元数据、base_url）、doubao×2、qianfan×1、aliyun_iqs×1、bocha×1、serply×5。
- `test_web_search_runtime.py`（26 用例）：降级链、凭证隔离、none/deprecated、源过滤、归并编排（provider 级语义不在此列）。
- `tests/tools/test_web_search.py`：注册表层（list/get_provider、deprecated 拒绝、duckduckgo 免 key 实例化 :116）。
- `tests/services/test_provider_probe.py`：searxng 探活错误口径（:18-96）。

空白与薄弱（每条可独立拆一张补测卡）：

1. **duckduckgo（零专属）**：`count` 1-10 钳制（duckduckgo.py:29）、`ddgs` 行映射、proxy 透传无任何单测；仅作为降级终点被运行时测试路过。
2. **searxng provider 级（零专属）**：`_validate_base_url` 合法/非法路径（searxng.py:20-30）、`SearxngResponseError` 两条抛出路径（:66-70）、`max_results` 钳制（:73）未被 provider 单测触及（运行时只测 happy path，test_web_search_runtime.py:179）。
3. **perplexity（全空）**：懒加载 client、ImportError 文案（perplexity.py:36-42）、usage/cost 组装（:86-100）、citations 与 search_results 按 URL 对齐（:119-138）零覆盖；缺 timeout 旋钮本身也值得一张行为确认卡。
4. **zhipu（仅参数化×3）**：70 字截断（zhipu.py:74）、engine/recency ValueError（:64-71）、`request_id` 进 metadata（:141）无专属断言。
5. **firecrawl（仅参数化×3）**：`scrapeOptions` 仅在 scrape=True 时出现（:79-80）、category 白名单（:61-65）、`success:false` 200 错误（:94-95）、API 侧 timeout 收敛公式（:73）无专属断言。
6. **tavily（1 条共享）**：`days/include_domains/exclude_domains` 条件字段（tavily.py:81-86）、`score/raw_content` 透传（:121-122）无断言；`supports_answer=True` 跳过归并的行为只在运行时面间接覆盖。
7. **brave/serper 响应映射**：brave 的 `age→date`（brave.py:55）与 serper 的 scholar attributes（serper.py:133-148）、answerBox→answer（:196-203）无断言。
8. **consolidation（零专属文件）**：`PROVIDER_TEMPLATES` 渲染、`_format_simple_results` 兜底（consolidation.py:347）、LLM 合成路径（:294）只有运行时集成面间接覆盖（test_web_search_runtime.py:373,422）；模板回归无金样本。
9. **"200 藏错误"四口径**：仅 bocha 有专属测试（:345）；qianfan `code`、doubao `error`、firecrawl `success` 三条姊妹路径未见独立断言（doubao 的在 :215 用例内附带）。

## 7. 阅读路径建议

- 只想知道"怎么选供应商"：读 §3 表 + config/provider_runtime.py:87-119。
- 要接新供应商：§2.2 → §5.2 检查单 → 照抄 zhipu.py（最规整的 POST 型）或 aliyun_iqs.py（GET 型 + 客户端钳制样例）。
- 要查"为什么没走我配的引擎"：search/__init__.py:171-227（软降级 + 运行时降级链）→ `metadata["search_fallback"]`（:219-223）。
