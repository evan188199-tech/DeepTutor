# scan: 测试真实网络触达风险清点（mock-network-guard）

- 任务卡：AGEN-1005
- 基线：HKUDS/DeepTutor `origin/main` @ `f07029cfc`（release: v1.6.13）
- 方法：AST 静态扫描（网络 API 调用 / SDK 方法调用 / 网络型子进程）+ monkeypatch 目标提取 + 模块级交叉引用 + 人工静态核实；全程未执行任何测试、未发起任何外呼。
- 去重边界：不覆盖 scan-test-isolation（tmp/env 全局态）、scan-flaky-tests（时序）、scan-subprocess-timeouts（子进程超时）；环境变量仅在“触发真实外呼分支”时纳入。

## 总体结论

**默认 `pytest` 运行路径下未发现必然触达外网的测试**（HIGH = 0）。仓库主流 mock 习惯健康：构造期注入 `httpx.MockTransport`（测试侧 45 处）、`SimpleNamespace` 假 SDK client（11 处 `.create`）、getter/工厂替换。风险集中在三类**脆弱不变量**（MEDIUM = 3），以及若干 loopback 真实 socket 与环境门控项（LOW = 6）。仓库当前**没有任何禁网守护**（无 pytest-socket、无 autouse socket 拦截、addopts 未过滤 integration marker），上述不变量一旦被未来改动破坏，失败模式是“真实外呼”而非显式报错。

## 覆盖口径与计数

| 口径 | 数量 |
| --- | --- |
| 测试侧网络 API 触点（AST 调用级） | 61 处 / 25 个文件 |
| 其中 httpx 客户端构造 | 45 处（全部带 MockTransport 或注入 transport） |
| 其中 SDK `.create` 类调用 | 11 处（全部 SimpleNamespace 假 client 或 MockTransport http_client） |
| 其中 stdlib `urlopen` 直接调用 | 3 处（全部 loopback，见 V1/V2） |
| 其中网络型子进程 | 1 处（本地 `git show`，非收集文件） |
| import/collection 期（模块级、conftest）触点 | 0 处 |
| 产品侧含网络 I/O 的函数 | 179 个 / 100 个模块（明细见数据 JSON） |
| in-package 测试（deeptutor/learning/tests 等） | 已覆盖，AST 无裸网络调用 |

数据明细：`network-touchpoints.json`（meta / counts / verified_findings / test_side_calls / product_network_functions，均含 path:line）。

## 分级风险清单

### MEDIUM（脆弱不变量，破坏后产生真实外呼）

- **M1 渠道 start() 依赖“先校验后连接”** — `tests/services/partners/test_channel_setup_status.py:32,50` 对 Discord/Mattermost/Slack/Telegram/Zulip 以真实 `await channel.start()` 断言无凭据时进入 `action_required`。已核实产品端 `deeptutor/partners/channels/discord.py:84-92` 在连接循环前先行 `return`；一旦校验顺序被改动（或新渠道把连接前置），这些用例将发起真实 gateway/API 外呼，且无 socket 层兜底。
- **M2 库符号替换型 mock** — `tests/services/test_provider_probe.py:29`（全局替换 `requests.get`）、`tests/services/test_voice.py:85,109-110,537`（类级替换 `httpx.AsyncClient.post/get`）、`tests/services/search/test_search_providers.py:98`（替换 provider 模块级 `requests` 对象）。产品迁移 HTTP 库或改用 `requests.Session` 即静默失效。
- **M3 产品符号边界 patch** — `tests/agents/chat/test_context_budget.py:427,508`（`_build_openai_client`）、`tests/services/test_web_source_sync.py:128` 等（`crawl_docs_site`）、`tests/services/config/test_context_window_detection.py:40`（`_detect_from_models_endpoint`）。符号重命名/内联后走真实路径。

### LOW

- **L1 loopback 真实 HTTP（urllib 全栈）** — `tests/runtime/test_launcher.py:44-70`（自建 127.0.0.1 ThreadingHTTPServer，验证 loopback 健康检查绕过代理；代理经 `getproxies` 注入）；`tests/services/skill/test_skill_login.py:68,80`（对 `run_login` 自建回调服务器真实请求；已核实 `deeptutor_cli/skill_login.py` 全文不外呼 hub.test）。不触外网，但与未来“一刀切禁 socket”守护冲突，需 loopback 豁免。
- **L2 环境门控外呼测试（自带 skip 守护）** — `tests/runtime/coordination/test_redis_integration.py:16-24`、`test_redis_stress.py:22-24`（`DEEPTUTOR_TEST_REDIS_URL` 未配置即 skip）、`tests/services/rag/test_pipeline_integration.py:414-424`。注意 `pyproject.toml` addopts 未做 `-m "not integration"`，安全完全依赖逐测自守。
- **L3 环境密钥隔离（已具备）** — `tests/conftest.py:93-115` autouse 删除 `CODEBUDDY_API_KEY/BASE_URL/INTERNET_ENVIRONMENT` 等；`:224-264` 替换 `resolve_llm_runtime_config` 防读本机真实 LLM 配置；`:286-305` `_restore_env` 兜底。这是仓库现有最好的“环境触发外呼”防线，新增集成分支须沿用。
- **L4 验证先行型用例** — `tests/services/test_codebuddy_credentials.py:113-117` 调用 `refresh_credentials` 依赖 `can_refresh()` 在 httpx 之前抛错（已核实 `deeptutor/services/codebuddy_credentials.py:279-286` 校验在请求前）。与 M1 同型的隐含约定。
- **L5 非收集的“伪测试”文件** — `tests/fixtures/lightrag_bridge/extract_legacy_example.py:20`（本地 `git show`，无网络，不收集）；`deeptutor/services/config/test_runner.py` 是产品代码（应用内连通性运行器，会真实调用 LLM），因 testpaths 限定未被收集——未来若扩大 testpaths 需先排除/改造。
- **L6 安全的构造期注入主流（正面项）** — `tests/core/test_agentic_messages.py:104-105`（`AsyncOpenAI(http_client=MockTransport)`）、`tests/services/llm/test_metrics.py:69`、`tests/services/llm/test_usage_estimation.py:139`、`tests/runtime/test_update_worker.py:24-27`（注入 command_runner/restart_launcher）、`tests/cli/test_doctor_cli.py:66,74`（注入 online_probe）、`tests/services/skill/test_skill_hub.py:259`、`tests/services/test_hermes_remote_backend_lifecycle.py:52`（MockTransport 注入）等。

## 抽样静态核实记录（≥5 条）

上述 M1-M3、L1-L6 全部经人工读码核实，关键证据（path:line）：

1. `deeptutor/partners/channels/discord.py:84-92` — start() 缺 token 先 return，连接循环其后（M1）。
2. `deeptutor_cli/skill_login.py:70-131` — run_login 仅含 loopback server，无对外 urlopen（L1）。
3. `deeptutor/services/codebuddy_credentials.py:279-286` — `can_refresh()` 先于 httpx 调用（L4）。
4. `tests/services/test_provider_probe.py:29` / `tests/services/test_voice.py:85` — 库符号替换现状（M2）。
5. `tests/runtime/coordination/test_redis_integration.py:16-18` — 空 URL 即 skip（L2）。
6. `pyproject.toml [tool.pytest.ini_options]` — testpaths 限定 `tests` 与 `deeptutor/learning/tests`；addopts 无 `-m` 过滤（L2/L5 依据）。
7. `tests/core/test_agentic_messages.py:104-105` — MockTransport 注入（L6）。

## 禁网守护建议清单

- **G1 全局 socket 兜底（首选）**：引入 `pytest-socket` 或在 `tests/conftest.py` 增加 autouse fixture 把 `socket.socket`/`create_connection` 替换为显式 raise，并以 marker（如 `@pytest.mark.loopback`）为 V1/V2 两个 loopback 用例开白名单。收益：M1/M2/M3 的失效模式从“真实外呼”变为“显式测试失败”。
- **G2 统一 mock 习惯**：新测试一律走构造期注入（`transport=httpx.MockTransport`、client_factory 参数、getter 替换），评审时对“替换 `requests.*` / `httpx.AsyncClient.*` 库符号”的新增保持警惕（M2 存量可渐进迁移）。
- **G3 marker 策略显式化**：在 addopts 增加 `-m "not integration and not redis_integration"` 或在贡献指引中强制 integration 用例自带 skip 守护（当前 L2 即此模式，但未成文）。
- **G4 渠道 start() 契约固化**：给 M1 用例补“start() 在校验前不得创建 socket”的断言（配合 G1 即自动获得），防止新渠道破坏先验。
- **G5 环境变量外呼分支清单化**：沿用 `tests/conftest.py:93-115` 模式，为未来新增的 env 触发集成（如新的 `*_API_KEY` 分支）补 autouse 隔离，并在 PR 模板中列出自查项。

## 与其他 scan 卡的边界

- tmp/env 全局态污染（不含外呼语义）归 scan-test-isolation；时序/等待归 scan-flaky-tests；子进程超时与僵尸进程归 scan-subprocess-timeouts。本卡 env 部分仅限“env 触发真实外呼分支”（L2/L3），子进程部分仅限“子进程命令本身联网”（tests/fixtures 脚本一处，非收集）。
