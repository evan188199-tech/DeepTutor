# 重试/退避/超时参数一致性扫描报告

- 日期：2026-10-06
- 基线：HKUDS/DeepTutor `origin/main` @ `f07029cfc`（release: v1.6.13）
- 范围：LLM provider（services/llm + runtime/agentic）、搜索 provider（services/search/providers）、通道网络层（partners/channels）、KB 检索代理（services/rag/pipelines 客户端 + web KB 代理）的重试次数、退避曲线、超时缺省
- 方法：固定探针脚本 `scripts/collect_retry_params.py` 逐条提取 `path:line × 参数值`（96 条，见 `data/retry-params.json`），全部人工复核过上下文；`tests/` 不在范围
- 去重声明：超时**资源/连接池**轴见 scan-http-clients（`evidence/http-clients-scan-20261004/report.md`，同基线 f07029cfc），本报告只在交叉处引用（M8/M9/L13/L18/L21），不重复展开；子进程超时轴属 scan-subprocess-timeouts，零重叠。本报告独有的轴：重试次数、退避曲线、重试叠加放大、硬编码 vs 配置化。
- 本报告只记录问题与建议，未改动任何产品代码。

## 结论速览

- 三分类清单：同类调用参数漂移 8 项（A）、硬编码 vs 配置化混用 5 项（B）、外层×内层叠加放大 8 项（C）
- Top 风险 5 项，最高优先是 agentic 原生路径 SDK 重试未归零（C1）与数学动画 code-gen 81 次请求放大（C2）
- 值得肯定的一致性：三个 SDK 型 provider（openai-compat/azure/anthropic）SDK 重试都显式归零、由 provider 外层统一拥有重试；流式空转守卫三处同为 90s；`structured_retry` 是结构化调用的唯一重试缝；搜索 provider 全家零应用层重试（一致约定）

风险等级说明：高=会稳定造成额度烧穿/小时级挂起/限流风暴；中=可控条件下的长时间阻塞或非预期放大；低=策略不一致、可维护性问题。

## 参数对照表（模块 path:line × 参数值）

行号均已对准 `f07029cfc`，可由 `scripts/collect_retry_params.py` 复现（全部 96 探针退出码 0）。

### 1. LLM provider

| 位置 | 参数 | 值 | 说明 |
|---|---|---|---|
| `deeptutor/config/settings.py:20` | `LLMRetryConfig.max_retries` | **8** | 全局 LLM 外层重试次数（配置化，env `LLM_RETRY__MAX_RETRIES`） |
| `deeptutor/config/settings.py:21` | `base_delay` | **5.0s** | 退避基数 |
| `deeptutor/config/settings.py:5` | docstring 缺省 | "default: 3"（delay 1.0） | **文档漂移**：实际 8/5.0 |
| `deeptutor/services/llm/factory.py:31-33` | DEFAULT_* | 取自 settings | 工厂唯一入口 |
| `deeptutor/services/llm/factory.py:76-77` | 退避曲线 | `base*2**attempt`，封顶 **120s** | 封顶硬编码；默认曲线 5→10→20→40→80→120→120→120，9 次尝试最坏纯等待 **515s** |
| `deeptutor/services/llm/provider_core/base.py:76` | `_CHAT_RETRY_DELAYS` | **(1, 2, 4)** | `retry_delays=None` 时的硬编码兜底曲线（生产路径未触发，潜在分叉） |
| `deeptutor/services/llm/provider_core/base.py:90` | 可重试状态码 | {408,429,500,502,503,504} | 全 provider 共享 |
| `deeptutor/services/llm/provider_core/base.py:426-437` | 重试循环 | 顺序取 delays，`asyncio.sleep(delay)` | 不读 `Retry-After`；错误分类用状态码+文本标记 |
| `deeptutor/services/llm/provider_core/openai_compat_provider.py:217` | SDK `sdk_max_retries` | **0** | SDK 重试归零（好） |
| `deeptutor/services/llm/provider_core/azure_openai_provider.py:110` | SDK `max_retries` | **0** | 同上 |
| `deeptutor/services/llm/provider_core/anthropic_provider.py:57` | SDK `max_retries` | **0** | 同上 |
| `deeptutor/runtime/agentic/client.py:127` | `sdk_max_retries` 默认 | **None** | 未传 → AsyncOpenAI SDK 默认 **2** 次内层重试（见 C1） |
| `deeptutor/runtime/agentic/client.py:139` | key 池分支 | `sdk_max_retries=0` | 同文件内两分支预算不一致 |
| `deeptutor/runtime/agentic/client.py:166`（注释） | 承诺 | "SDK retry budget … cannot drift" | 与 :127 实际行为相悖 |
| `openai_compat_provider.py:1110` / `azure_openai_provider.py:213` / `anthropic_provider.py:565` | 流式空转守卫 | **90s** | 三处一致，超时归类 retryable |
| `openai_compat_provider.py:234` | key 轮换 | `max(2, len(pool))` 次，仅 429，无 sleep | 次数硬编码规则 |
| `deeptutor/services/llm/structured_retry.py:55` | 结构化降级重试 | **1 次**（低 reasoning effort） | 单一重试缝，包在 factory 之外 |
| `deeptutor/services/llm/traffic_control.py:74` | 本地限流等待 | token bucket，sleep 后重入 | 不计重试次数，挂在每次尝试前 |
| `deeptutor/agents/base_agent.py:206` | agent `max_retries` | `agent_config.get("max_retries", settings.retry.max_retries)` | 默认又回落到 8 |
| `mastery_hints.py:336` / `chat_hints.py:254` / `reading_hints.py:428` / `doctor.py:359` | 显式禁用 | `max_retries=0` | 轻量路径正确归零（好） |

### 2. 搜索 provider

| 位置 | 参数 | 值 |
|---|---|---|
| `brave.py:27`、`searxng.py:45`、`duckduckgo.py:24` | requests timeout | **20s** |
| `bocha.py:39`、`aliyun_iqs.py:58`、`zhipu.py:43`、`serper.py:50`、`serply.py:50`、`qianfan.py:48` | requests timeout | **30s** |
| `tavily.py:46`、`jina.py:42`、`firecrawl.py:41`、`doubao.py:46` | requests timeout | **60s** |
| `perplexity.py:74` | 走 perplexity SDK `chat.completions.create` | **无显式 timeout、无显式 retry**（SDK 隐式缺省，全集唯一 outlier） |
| 14 家全部 | 应用层重试 | **0 次**（无 retry 循环、无退避）——一致约定 |
| `tools/paper_search_tool.py:19,21,97-104` | arXiv | timeout 30s + 429 时 **1 次**重试、延迟 3s |

超时 20/30/60 三档本身已被 scan-http-clients 判为"既有约定而非漂移"，此处仅引用；retry 轴的结论是：搜索面无重试叠加风险，唯一例外是 perplexity 的 SDK 隐式行为不可见。

### 3. 通道网络层

| 位置 | 参数 | 值 |
|---|---|---|
| `manager.py:23,159` | 外层发送重试 | `(1, 2, 4)` × **3 次**（所有 channel 共用外层） |
| `telegram.py:36-37` | 内层发送重试 | **3 次** × 0.5s 指数（0.5/1/2），处理 flood/timeout |
| `telegram.py:355-363` | HTTP 超时 | connect 30 / read 30 / pool 15 |
| `discord.py:172,263,303` | 内层重试 | `_api_request`/`_send_payload`/`_send_file` 各 **3 次**（rate-limit 读 `retry_after`，兜底 1s） |
| `discord.py:85` | HTTP 超时 | 30s |
| `dingtalk.py:175` | HTTP 超时 | **未传**（httpx 默认 5s，引 scan-http-clients M9）；无重试 |
| `napcat.py:34-35,103` | 超时/重连退避 | 下载 total 60s、action 20s；重连 `(5,10,30∞)` |
| `mattermost.py:45` / `qq.py:126` / `discord.py:104` / `whatsapp.py:94` / `feishu.py:598` | WS 重连退避 | 5s / 5s / 5s / 5s / 5s（定值） |
| `matrix.py:566` / `slack.py:129` | 重连退避 | 2s / 1s（定值） |
| `wecom.py:98` | 重连次数 | **-1（无限）** |
| `slack.py:23` / `msteams.py:174` / `mochat.py:333` / `mattermost.py:131` | HTTP 超时 | 30s |
| `zulip.py:61` | HTTP 超时 | **60s**（config 可调） |
| `email.py:229` | SMTP/IMAP 超时 | 30s |
| `mochat.py:254-259` | socket_connect 10s / watch 25s / retry_delay 0.5s / max_retry 0 | **config schema 可配置**（全集唯一配置化通道） |
| `feishu.py:416,422-423` | 卡片流创建重试间隔 3s；reaction 删除 `(0.15,0.5)`；reaction 迟到 `(0,5,30,120)` | 硬编码 |
| `lark_http.py:39-51` | 传输 | per-thread `requests.Session`，timeout 由调用点自传（引 L19） |

### 4. KB 检索代理

| 位置 | 参数 | 值 |
|---|---|---|
| `services/rag/pipelines/lightrag_server/client.py:42` | timeout | **60s**，无重试 |
| `services/rag/pipelines/weknora/client.py:30` | timeout | **60s**，无重试 |
| `services/rag/pipelines/ima/transport.py:34` | DEFAULT_TIMEOUT | **30s**，无重试 |
| `services/rag/pipelines/kiwix/client.py:229` | `httpx.Timeout(10.0)` | **10s**，无重试 |
| `web/proxy.ts`、`web/app/api/knowledge-bases/*`（Next 侧 KB 代理） | 超时/重试 | **无任何策略**（fetch 透传） |

同类 KB HTTP 检索超时 60/60/30/10 四档漂移；KB 面完全没有应用层重试（检索失败直接向上抛，由 RAG 降级路径接管）。连接池轴见 scan-http-clients M4/M5/M6/L7，不重复。

### 5. Embedding（LLM 家族旁路，重试轴强相关）

| 位置 | 参数 | 值 |
|---|---|---|
| `embedding/adapters/openai_compatible.py:147-148` | `_MAX_RETRIES`/`_RETRY_BACKOFF` | **5 次** / **1.0s** 指数 |
| `openai_compatible.py:235` | 实际循环 | `range(1 + max(5, 10))` = **至少 11 次尝试**（429 continue 也烧 attempt，注释自认） |
| `openai_compatible.py:255` | 429 等待 | `max(retry_after or 0, 60)`——**下限 60s 且无上限**（引 M8） |
| `openai_compatible.py:342` | 普通失败退避 | `1.0*2**attempt` |
| `embedding/adapters/openai_sdk.py:56` | SDK `max_retries` | **2**（无自带循环） |
| `embedding/adapters/gemini.py:315` | 429 等待无上限（引 L13）；`parsing/engines/mineru/cloud.py:537-552` 429 轮换 key 无 sleep（引 L21） | 交叉引用，不展开 |

## 三分类清单

### A. 同类调用参数漂移

| # | 位置 | 漂移内容 | 等级 |
|---|---|---|---|
| A1 | `provider_core/base.py:76` vs `factory.py:31-33,76-77` | 同为"LLM 调用外层重试"，兜底曲线 (1,2,4)/3 次与配置曲线 5s 指数/8 次/封顶 120s 并存；生产路径目前全走工厂，但 None 兜底是公共 API 语义，一旦新调用点省参会静默拿到另一条曲线 | 中 |
| A2 | `config/settings.py:5-7` vs `:20-21` | docstring 缺省 3 次/1.0s 与实际 8 次/5.0s 不符，调参者会被误导 | 低 |
| A3 | `embedding/adapters/openai_compatible.py` vs `openai_sdk.py` | 同为 OpenAI 兼容 embedding：前者自带 6~11 次重试+429 强制 ≥60s，后者纯 SDK 2 次。同类失败两种重试语义 | 中 |
| A4 | 通道 WS 重连退避 | napcat (5,10,30∞)、wecom 无限、discord/qq/whatsapp/feishu/mattermost 5s、matrix 2s、slack 1s——七种策略三个数量级（定值/阶梯/无限） | 低 |
| A5 | 通道 HTTP 超时 | telegram 30/30/15、napcat 60/20、zulip 60、discord/msteams/mochat/mattermost/slack 30、email 30、dingtalk 缺省 5s（M9）；同类"发消息"从 5s 到 60s | 中 |
| A6 | KB 检索 client 超时 | lightrag 60 / weknora 60 / ima 30 / kiwix 10，同类检索四档 | 低 |
| A7 | 搜索 provider 超时 | 20/30/60 三档（scan-http-clients 已判为既有约定，仅登记）；perplexity 走 SDK 无显式 timeout 是真 outlier | 低 |
| A8 | `runtime/agentic/client.py:127,139` | 同一构造函数内单 key 分支 SDK 重试=SDK 默认 2、key 池分支=0；与 :166 "不漂移"注释相悖 | 中 |

### B. 硬编码 vs 配置化混用

| # | 位置 | 混用内容 | 等级 |
|---|---|---|---|
| B1 | LLM 重试面 | 重试次数/基数走 `settings.retry`（env 可配），但封顶 120s（factory.py:77）、兜底曲线 (1,2,4)（base.py:76）、流式空转 90s×3（三 provider）、key 轮换规则（openai_compat_provider.py:234）全部硬编码——调 env 只能改半条曲线 | 中 |
| B2 | 通道发送重试 | mochat 全套参数走 config schema（mochat.py:254-259），其余全部通道模块级常量硬编码（manager.py:23、telegram.py:36-37、discord.py:172 等）；同类"发送重试"一个可配置其余写死 | 中 |
| B3 | 搜索 provider | timeout 是构造参数但默认值 20/30/60 硬编码在各自类；重试次数无配置面（=0） | 低 |
| B4 | KB 检索 client | timeout 构造参数带硬编码默认（60/60/30/10），无重试配置；Next KB 代理（web/proxy.ts）零策略 | 低 |
| B5 | 上层 pipeline 重试 | research 报告步 3 次（pipeline.py:263 常量）、question 修复 2 次（:147 常量）、book block 1 次（compiler.py:121 Options 可配）、math animator 渲染 4 次（pipeline.py:194 调用处硬编码，retry_manager.py:37 默认同为 4）、code-gen 结构化重试走 BaseAgent settings 默认 8——五种上层重试两种来源 | 中 |

### C. 外层×内层叠加放大

最坏尝试数 = 各层乘积（均假设持续瞬时失败/429）：

| # | 链路 | 叠乘 | 最坏请求次数 / 纯等待 | 等级 |
|---|---|---|---|---|
| C1 | **agentic 原生路径**（research 报告步等）：`client.py:127` SDK 默认 2 次 × pipeline 外层 3 次（`agents/research/pipeline.py:263,1905`） | 3×(1+2) | **9 次/步**；SDK 内层还有自己的指数退避。修复只需显式传 `sdk_max_retries=0`（与其他三层 provider 对齐） | **高** |
| C2 | **数学动画 code-gen**：结构化 attempts=9（`code_generator_agent.py:171-173`，settings 默认 8+1）× factory stream 9 次 = 81；再 × CodeRetryManager 渲染 5 次（`pipeline.py:194`，每次 repair 又是整条 BaseAgent 链） | 9×9×(1+4·k) | **单次代码生成最多 81 次 LLM 请求**，叠加修复循环可上数百；429 风暴时烧穿额度 | **高** |
| C3 | **Embedding openai_compatible**：≥11 次循环 × 每次 429 强制 ≥60s 且无上限（`openai_compatible.py:235,255`，引 M8） | 11×(≥60s) | 全局限流时单批挂 **小时级**；与 gemini(L13)、mineru(L21) 同族，scan-http-clients 卡 F 建议合并修 | **高** |
| C4 | **Book 编译 block**：block 层 1+1 次（`book/compiler.py:121,328-341`，2s 指数）× generator 内 factory 9 次 | 2×9 | 每 block 最多 **18 次**；整本数百 block 时间歇性限流被放大 18 倍 | 中 |
| C5 | **Question finalization**：修复 2 次（`agents/question/pipeline.py:147,1532`）× factory 9 | 2×9 | 18 次 | 中 |
| C6 | **Telegram 发送**：manager 3×(1+2+4s) × telegram 内层 3×(0.5+1+2s)（`manager.py:23,159`、`telegram.py:36-37,585-615`） | 3×3 | **9 次请求**，等待 ≤9s+flood wait | 低 |
| C7 | **Discord 发送**：manager 3 × 内层 3（`discord.py:172,263,303`） | 3×3 | 9 次 | 低 |
| C8 | **结构化降级缝**：`structured_retry.py:55` 的 +1 次包在 factory 之外，凡结构化调用 9→**18 次**；与 C2/C4/C5 复合 | +1× | 设计如此（单一缝、可接受），但需与 C2 修一起评估总量 | 低 |

正面确认（不算问题）：services 主链 SDK 重试已归零，key 轮换只对 429 且无 sleep，重试不读 `Retry-After`（语义靠 5s 指数兜）；`structured_retry` 明确要求调用方不得自建同类重试。

## Top 风险（建议优先处理）

1. **C1 agentic SDK 重试未归零**（`runtime/agentic/client.py:127`）：一行修复、消除与注释/其他 provider 的真实漂移；修后 C1 变为 3 次/步。
2. **C2 code-gen 81 次放大**（`agents/base_agent.py:206` 默认继承 settings 8 + `code_generator_agent.py` 又按次数循环）：建议该 agent 显式 `max_retries` 收敛到 1~2，或把 settings 默认 8 降档（8×5s 指数对交互式场景过于激进，一次失败要等 515s 才放弃）。
3. **C3 embedding 429 无上限等待**：与 scan-http-clients 卡 F（M8/L13/L21）合并修：`min(retry_after, 120)` + 循环下限从 10 回归 `_MAX_RETRIES`。
4. **A5+B2 通道超时/重试策略统一**：dingtalk 显式超时（卡 G）+ 发送重试曲线收敛到 manager 单点（channel 内层只处理平台专属错误如 Discord rate-limit、Telegram flood）。
5. **A2 settings 文档漂移**：改 docstring 或把默认改回与文档一致——成本最低、防误调。

## 建议修复卡

| 建议卡 | 覆盖项 | 说明 |
|---|---|---|
| 卡 R1：agentic SDK 重试预算归零 | C1、A8 | `client.py` 单 key 分支传 `sdk_max_retries=0`，测试断言 SDK 构造参数 |
| 卡 R2：settings.retry 默认与文档校准 | A1、A2、B1 | docstring 对齐 8/5.0；评估默认 8 是否降档；封顶 120s 进配置 |
| 卡 R3：embedding 重试收敛（并卡 F） | C3、A3 | 与 scan-http-clients 卡 F 合并：`retry_after` 封顶 + 循环次数下限回归 |
| 卡 R4：上层 pipeline 重试预算梳理 | C2、C4、C5、B5 | math animator 结构化重试显式收敛；book/question 上层重试改可配 |
| 卡 R5：通道发送重试单点化 | C6、C7、A4、A5、B2、B4 | manager 拥有通用重试；channel 内层限平台专属错误；KB/搜索超时档位归一 |

## 复现方式

```bash
cd <repo> && git checkout f07029cfc
python3 evidence/scan-retry-backoff-20261006/scripts/collect_retry_params.py . \
  > evidence/scan-retry-backoff-20261006/data/retry-params.json   # 96 条，exit 0
shasum -a 256 -c evidence/scan-retry-backoff-20261006/SHA256SUMS
```

## 验收对照

1. 参数对照表（path:line × 值）与叠加放大点清单：见上两节（C1–C8）。
2. 脚本可复现：96/96 探针命中、退出码 0；数据与报告哈希自证（SHA256SUMS）。
3. 未改产品代码：本分支仅新增 `evidence/scan-retry-backoff-20261006/`。
