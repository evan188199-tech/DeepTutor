# HTTP 客户端资源与超时扫描报告

- 日期：2026-10-04
- 基线：HKUDS/DeepTutor `origin/main` @ `f07029cfc`（release: v1.6.13）
- 范围：后端 Python 生产代码中 `httpx` / `aiohttp` / `requests` 全部使用点（约 90 个文件）；`tests/` 不在风险清单范围
- 方法：全量文件逐个审读 + 逐条在源码复核（path:line 均已核对）
- 本报告只记录问题与建议，未改动任何代码

## 结论速览

- 高风险：0 项
- 中风险：11 项（集中在：RAG 检索热路径每次请求新建客户端、skill hub 客户端泄漏、MCP 授权流超时常量未生效、两处超时过短/过长失衡、两处重试等待无上限）
- 低风险：22 项（以"每次调用新建客户端"的连接池漂移与 `trust_env` / TLS 策略不一致为主）
- 整体评价：代码纪律较好——绝大多数 client 走 `async with`、重试有上限、未见裸 `requests.*` 无 timeout、未见无上界 `while True`。主要系统性问题是"每调用新建客户端"模式在检索热路径反复出现，以及少量策略漂移。

风险等级说明：高=会稳定造成资源泄漏/挂死/明显故障；中=热路径性能损耗、可控条件下的长时间阻塞或失败；低=低频路径、一次性脚本或策略一致性问题。

## 中风险发现（11 项）

| # | 位置 | 类别 | 问题 | 建议修法 |
|---|------|------|------|----------|
| M1 | `deeptutor/services/skill/hub.py:285` | 未关闭 client | `ClawHubProvider.__init__` 创建 `httpx.Client(timeout, follow_redirects)`，类上无任何 `close()`；`get_hub_provider()`（hub.py:711）每次操作新建 provider，每次 hub 搜索/详情/发布都泄漏一个 client 直到 GC | 给 provider 增加 `close()`/上下文管理器；调用侧在 `finally` 中关闭，或复用单例 provider |
| M2 | `deeptutor/services/mcp/oauth.py:326` | 无上界等待 | `FLOW_TIMEOUT_S = 600.0` 定义并导出但从未被引用；`begin_authorization` 的 `flow.task`（:396 起）阻塞在 `await flow.result`（:369），consent 页永不确认时任务与 `_PENDING` 条目永久泄漏 | 用 `asyncio.wait_for(..., FLOW_TIMEOUT_S)` 包住 flow 生命周期，超时取消 `flow.task` 并清理 `_PENDING` |
| M3 | `deeptutor/services/llm/provider_core/openai_codex_provider.py:209` | 连接池漂移 | `_request_codex` 每次对话新建 `httpx.AsyncClient(timeout=60.0, verify=verify)`，热路径每轮支付完整 TCP+TLS 建连 | 服务级持有共享 `AsyncClient`，关停时统一 `aclose()` |
| M4 | `deeptutor/services/rag/pipelines/ima/transport.py:67`（另 :83） | 连接池漂移 | `post`/`post_sync` 每次调用新建 `httpx.AsyncClient`/`httpx.Client`；IMA 检索热路径（单次搜索最多 3 页）零连接复用 | 在 `ImaTransport` 上惰性持有长生命周期 client 并提供 `aclose()`；保留注入 `transport` 供测试 |
| M5 | `deeptutor/services/rag/pipelines/lightrag_server/client.py:55` | 连接池漂移 | `_open()` 每次调用新建 client；`query_context` 每轮 chat 都重建连接 | client 实例持有持久 client + `aclose()`，或在调用侧用显式 `async with client:` 会话作用域 |
| M6 | `deeptutor/services/rag/pipelines/weknora/client.py:38` | 连接池漂移 | `_open()` 每请求新建 client；`search()` 热路径每次重建连接与请求头 | 同 M5；`_request_json` 内的逐请求 SSRF 校验保留不动 |
| M7 | `deeptutor/services/subagent/opencode_family.py:70`（阻塞点 :161） | 缺失超时 | `_HTTP_TIMEOUT = Timeout(connect=10, read=None, write=60, pool=10)`；阻塞式 `POST /session/{sid}/message` 无任何整体期限，CLI server 卡死会永久挂起整个 consult 及其 SSE 监听（注释表明是有意为之，但缺兜底） | 保留流式 read 不限时的语义，但对外层 POST 包 `asyncio.wait_for(..., max_turn_seconds)` 兜底 |
| M8 | `deeptutor/services/embedding/adapters/openai_compatible.py:255` | 重试无上限 | 429 等待取 `max(retry_after or 0.0, 60)`，对 `Retry-After` 无封顶——网关回 `Retry-After: 86400` 会使单次 embed 挂 24h（最多 8 轮） | 睡前钳制 `min(retry_after, 120)` |
| M9 | `deeptutor/partners/channels/dingtalk.py:175` | 超时过短 | `httpx.AsyncClient()` 未传 `timeout`，落入 httpx 默认 5s，作用于 token 刷新（:241）、媒体下载（:283）、媒体上传（:329）、发送（:400）；多 MB 媒体收发经常超过 5s | client 级显式 `httpx.Timeout(30, connect=10)`；媒体收发按请求放宽 read/write 到 60–120s |
| M10 | `deeptutor/services/voice/adapters/dashscope.py:264` | 超时过短 | `aiohttp.ClientTimeout(total=config.request_timeout)`（默认 120s）覆盖整个 WebSocket 识别会话（上传+全部结果），音频处理超约 2 分钟即失败，且无外层补偿 | `total=None` + `sock_read` 空闲超时，或按音频时长缩放预算 |
| M11 | `deeptutor/services/github_source/client.py:83`（另 :96） | 连接池漂移 | `_request_json`/`_request_bytes` 每次 API 调用新建 client；`sync.py:291`/`:338` 对 tree 条目循环调用 `download_file`，一次仓库同步逐文件拆建 TLS 池 | `GitHubClient` 实例持有共享 client（`__init__` 创建、同步任务作用域内 `aclose()`），或按同步任务注入共享 client（参照 `crawler.py` 的 `client_factory` 模式） |

## 低风险发现（22 项）

| # | 位置 | 类别 | 问题 | 建议修法 |
|---|------|------|------|----------|
| L1 | `deeptutor/services/codex_auth/service.py:458` | 未关闭 client | 默认构造路径 `self._owned_http = httpx.AsyncClient(timeout=30)`，类内无任何 close 方法 | 增加 `aclose()` 关闭 `_owned_http`，在关停/测试 teardown 调用 |
| L2 | `deeptutor/services/codex_auth/service.py:1289` | 连接池漂移 | `get_codex_oauth_service()` 按 owner key 建实例且各持 `httpx.AsyncClient`，实例表（:1169/:1298）永不淘汰也不关闭（对比 MCP manager 的 `_MAX_OWNER_SCOPES = 64` 上限，mcp/manager.py:75） | 实例表加上限（LRU+关闭淘汰）或跨实例共享一个 client |
| L3 | `deeptutor/services/partners/channel_onboarding.py:425`（另 :478） | 连接池漂移 | 每次状态轮询（每 3–5s/会话）新建 client，逐次 TCP+TLS | manager/session 级复用一个 client（保留 15s timeout） |
| L4 | `deeptutor/services/partners/weixin_onboarding.py:186`（另 :256） | 连接池漂移 | `poll_login` 每次轮询新建 client（浏览器秒级轮询） | 每个 `_Attempt` 持有一个 client，过期/`forget` 时关闭 |
| L5 | `deeptutor/api/routers/video_learning.py:465` | 连接池漂移 | 每个流请求另建 client 做元数据查询，seek 热路径翻倍 clientchurn（`:494` `_open_upstream` 的每请求 client 因生命周期须跨流，属合理） | 模块级共享元数据 client（带 `limits=`） |
| L6 | `deeptutor/partners/channels/napcat.py:101` | 连接池漂移 | `aiohttp.ClientSession` 默认 `trust_env=False`，httpx 系 channel 均走代理环境变量，napcat 图片下载绕过 HTTP_PROXY | 传 `trust_env=True` 对齐 |
| L7 | `deeptutor/services/rag/pipelines/kiwix/client.py:226`（另 :231） | 连接池漂移 | `_client()` 每次公开调用新建池（probe/search/read_article 各自重连）；且 `trust_env=False` 是全集唯一 outlier | client 实例持有并 `aclose()`；`trust_env` 策略二选一统一 |
| L8 | `deeptutor/services/rag/pipelines/ima/media.py:93` | 连接池漂移 | 每次媒体下载新建 client | 若 M4 落地，复用 transport 的持久 client |
| L9 | `deeptutor/services/sandbox/backends.py:115` | 连接池漂移 | 每次 sandbox exec 新建 `AsyncClient`（loopback sidecar，TLS 成本小但逐命令重连） | 按 base_url 在 backend 上缓存一个 client |
| L10 | `deeptutor/tools/zotero_search.py:38` | 连接池漂移 | 默认工厂每次 `search()` 新建 client（工厂可注入，测试已覆盖） | 实例持有一个 client |
| L11 | `deeptutor/services/pocketbase_client.py:141` | 连接池漂移 | `validate_pb_token` 缓存未命中时新建 PocketBase SDK client（自带 HTTP 池），每 token 每 60s TTL 一次，处于每请求鉴权路径 | 复用 `get_pb_client()` 单例，仅换 auth token |
| L12 | `deeptutor/services/embedding/adapters/cohere.py:130`、`jina.py:116`、`ollama.py:63`、`gemini.py:305`、`openai_compatible.py:237` | 连接池漂移 | 各 adapter 每次 `embed()`（gemini 为每次重试）新建 client，批量索引热路径连接零复用（`limits=`/`trust_env` 各家一致，TLS 走中央开关） | adapter 持有长生命周期 client + `aclose()` 生命周期钩子，或小型共享 client 缓存 |
| L13 | `deeptutor/services/embedding/adapters/gemini.py:315` | 重试无上限 | 429 等待 `max(Retry-After, backoff)` 无封顶（次数封顶 6，但单轮可睡任意久） | 睡前钳制 `retry_after` 上限 |
| L14 | `deeptutor/services/videogen/adapters/async_task.py:59`（另 :77）、`dashscope.py:65`（另 :85） | 连接池漂移 | `generate()` 串行新建两个 client（提交/轮询下载），每次渲染双份 TCP+TLS | 一次 generate 生命周期共享一个 client（`imagegen/dashscope.py:42` 已是此模式） |
| L15 | `deeptutor/services/llm/local_provider.py:49` | 连接池漂移 | `aiohttp.ClientSession(timeout=timeout)` 未传 `trust_env`（默认 False），兄弟发现路径均显式 `trust_env=True`（cloud_provider.py:94、provider_probe.py:204、context_window_detection.py:143），代理环境变量只对云端生效 | 传 `trust_env=True` 或统一 session 工厂 |
| L16 | `deeptutor/services/config/context_window_detection.py:138` | 连接池漂移 | 内联 `aiohttp.TCPConnector(ssl=False)`，未复用 `_get_aiohttp_connector()`（cloud_provider.py:31），未来 connector 策略会漂移（prod 禁用守卫仍生效） | 复用中央 `_get_aiohttp_connector()` |
| L17 | `deeptutor/services/llm/provider_core/github_copilot_provider.py:76` | 连接池漂移 | token 交换每次新建 client 且显式 `trust_env=True`，与 Codex 路径（openai_codex_provider.py:87）不同，未走中央 `disable_ssl_verify_enabled()` | 低频可接受；补 `verify=not disable_ssl_verify_enabled()` 保持一致 |
| L18 | `deeptutor/services/settings/provider_probe.py:90`（兜底 :108） | 缺失超时 | `probe_search_provider` 用 `wait_for(25)` 兜 `asyncio.to_thread`，但线程不可取消；底层 requests 搜索调用自身无 timeout，被放弃的线程可能永久悬挂累积 | 给 requests 调用显式 timeout，`wait_for` 仅作兜底 |
| L19 | `deeptutor/partners/channels/lark_http.py:43` | 未关闭 client | per-thread `requests.Session` 存 `threading.local`，无任何关闭钩子（受线程数约束，socket 存活至进程退出） | 长驻池线程下可接受；补 `atexit`/channel-stop 关闭或在代码注释明示 |
| L20 | `deeptutor/services/web_source/snapshot_assets.py:102` | 连接池漂移 | `fetch_snapshot_image` 每图新建 client，`localize_snapshot_images`（:56–67）最多 24 张图 → 单次快照最多 24 次 client 实例化（信号量只限并发不限churn） | 在 `localize_snapshot_images` 建一个 client 传入各 fetch，最后统一关闭 |
| L21 | `deeptutor/services/parsing/engines/mineru/cloud.py:553` | 重试无上限 | 429 时仅轮换 key 立即 `continue`，无 sleep——全局限流时把重试预算瞬间烧完 | `continue` 前加小退避（如 `1 * attempt` 秒） |
| L22 | `deeptutor/services/imagegen/adapters/*`、`videogen/adapters/*`、`voice/adapters/*`（httpx 调用点） | TLS 策略漂移 | 这些 adapter 均不传 `verify=`，系统级 `DISABLE_SSL_VERIFY`（embedding/llm 已支持）对媒体生成静默失效；未发现绕过中央 helper 的裸 `verify=False`（无安全违规，属策略不一致） | 经 `generation_http.py`/`openai_http_client.py` 增加共享 builder 贯通该开关（需产品决策） |

## 已核实为合理、不建议改动

- `services/parsing/engines/docling/remote.py:106`、`tika/remote.py:102`、`mineru/cloud.py:50/:428/:507`：300s 超时对应服务端大文档转换/上传下载，属真实长任务。
- `services/search/providers/*` 12 个 provider 统一使用一次性 `requests.get/post(timeout=20–60)`：无连接复用但全仓一致，属既有约定而非漂移；均有显式 timeout。
- `tools/web_fetch.py:106`、`web_source/crawler.py:415`、`video_learning/*`、`partners/transcription.py`、`hermes_remote*`、`app_update.py`、`codebuddy_credentials.py`、`scripts/export_discord_history.py` 等：client 均在 `async with`/显式 close 生命周期内，重试有界或带 deadline。
- 轮询型 `while True`（imagegen/videogen 任务轮询、mineru 轮询、napcat/weixin 重连）均有 deadline 或运行标志位约束。

## 可拆修复卡建议

| 建议卡 | 覆盖项 | 说明 |
|--------|--------|------|
| 卡 A：RAG 检索客户端生命周期统一 | M4、M5、M6、L7、L8 | 一个模式（持久 client + `aclose()`）统一修复 5 处，收益最大 |
| 卡 B：Skill Hub provider 泄漏 | M1 | 独立小卡：`close()` + 调用侧 finally |
| 卡 C：MCP 授权流 deadline | M2 | 独立小卡：启用既有 `FLOW_TIMEOUT_S` |
| 卡 D：Codex OAuth 服务 client 生命周期 | L1、L2 | `aclose()` + 实例表上限 |
| 卡 E：opencode consult 兜底超时 | M7 | 需与产品确认兜底时长（read=None 是既定契约） |
| 卡 F：重试等待钳制与 429 退避 | M8、L13、L21 | 三处小改动可合并一卡 |
| 卡 G：DingTalk channel 超时显式化 | M9 | 独立小卡 |
| 卡 H：DashScope STT 会话超时拆分 | M10 | `total=None` + 空闲超时，需真机回归 |
| 卡 I：热路径 client 复用（散点） | M3、M11、L3、L4、L5、L14、L20 | 模式相同，可按模块再拆 |
| 卡 J：代理/TLS 策略统一（需产品决策） | L6、L15、L16、L17、L22（含 L7 的 trust_env 半项） | 决定 `trust_env` 与 `DISABLE_SSL_VERIFY` 的统一语义后再动手 |

## 验收对照

1. 每项附 `path:line` 与风险等级：见上两表（行号基于 `f07029cfc`）。
2. 可拆修复卡条目：见"可拆修复卡建议"。
3. 未改任何代码：本分支仅新增 `evidence/http-clients-scan-20261004/` 下本报告与 SHA256SUMS。

## 覆盖清单

生产代码审读文件（tests/ 除外）：`services/search/providers/`（12）、`services/web_source/`（3）、`services/github_source/client.py`、`tools/web_fetch.py`、`services/embedding/adapters/`（5）、`services/imagegen/adapters/`（3）、`services/videogen/adapters/`（2）、`services/voice/adapters/`（5）+ `voice/base.py`、`services/llm/`（cloud_provider、local_provider、request_compat、openai_http_client、provider_core/3）、`services/codex_auth/`（4）、`services/mcp/`（2）、`services/settings/provider_probe.py`、`services/config/`（2）、`services/skill/hub.py`、`partners/channels/`（11）、`partners/transcription.py`、`services/partners/`（2）、`api/routers/video_learning.py`、`video_learning/`（2）、`reading/ingestion.py`、`services/rag/pipelines/`（ima 4 + kiwix + lightrag_server + weknora）、`services/parsing/engines/`（3）、`services/pocketbase_client.py`、`services/sandbox/backends.py`、`services/subagent/`（5）、`services/app_update.py`、`services/codebuddy_credentials.py`、`tools/tex_downloader.py`、`tools/vision/image_utils.py`、`tools/zotero_search.py`、`deeptutor_cli/init_wizard.py`、`scripts/export_discord_history.py`，以及上下文文件 `services/generation_http.py`。
