# C 类：可选依赖被当必宣（core 声明，实际用法是 lazy/受守卫）

判定口径：`pyproject.toml` `[project] dependencies`（必装面）声明的发行包，主范围内所有 import 都是函数/方法内 lazy（无模块顶层无条件 import），其中多数还带 `try/except ImportError` 守卫与显式降级路径 —— 即代码本身按"可选依赖"对待，声明却按"必装"给出。共 15 条：10 条有显式回退或守卫报错，5 条 lazy 无守卫。

| # | 发行包（声明行） | 证据 file:line | 方式 | 缺包行为 |
| --- | --- | --- | --- | --- |
| C1 | `llama-index-retrievers-bm25`（pyproject.toml:60） | `deeptutor/services/rag/pipelines/llamaindex/retrievers.py:30` | lazy，guarded ImportError → None | 回退向量检索；pyproject.toml:57-59 注释自认回退设计 |
| C2 | `faiss-cpu`（pyproject.toml:65-66） | `deeptutor/services/rag/pipelines/llamaindex/vector_store.py:58`（lazy，try/except → None）；`:92`、`:107`（lazy，仅 faiss 后端选中才执行） | lazy，guarded + `faiss_available()` 探测 | 回退 SimpleVectorStore；pyproject.toml:61-63 注释自认 |
| C3 | `llama-index-vector-stores-faiss`（pyproject.toml:64） | `deeptutor/services/rag/pipelines/llamaindex/vector_store.py:59` | lazy，guarded（与 C2 同一 try） | 同 C2 |
| C4 | `psutil`（pyproject.toml:93） | `deeptutor/knowledge/indexing_run.py:24`（模块级 try/except → None）；`deeptutor/runtime/memory_probe.py:85`（lazy try/except → /proc 回退） | guarded | 设置页内存条缺失，应用可用；pyproject.toml:90-92 注释自认 soft |
| C5 | `qrcode`（pyproject.toml:50） | `deeptutor/services/partners/channel_onboarding.py:72`、`deeptutor/services/partners/weixin_onboarding.py:112-113` | lazy，guarded Exception → None | 二维码渲染为链接；docstring 自述 "tolerating an absent qrcode package"（与 pyproject.toml:45-49 "core" 论证相左） |
| C6 | `dashscope`（pyproject.toml:53） | `deeptutor/services/embedding/adapters/dashscope_native.py:105`、`:139` | lazy，guarded ImportError → 带安装提示的 ImportError | 仅选该 embedding 适配器才触发；全仓库无其他 import |
| C7 | `youtube-transcript-api`（pyproject.toml:78；另 video-learning extra:158 重复声明） | `deeptutor/video_learning/service.py:428` | lazy，guarded ImportError → 返回 `dependency_missing` | 字幕学习静默降级 |
| C8 | `pocketbase`（pyproject.toml:85） | `deeptutor/services/pocketbase_client.py:80`、`:139` | lazy，guarded ImportError → RuntimeError | requirements/server.txt 注释："Only used when integrations.pocketbase_url is configured" |
| C9 | `croniter`（pyproject.toml:89） | `deeptutor/services/cron/service.py:134` | lazy，guarded ImportError → ValueError（建议改用 every/at 调度） | cron 调度功能缺失，其余调度可用 |
| C10 | `pyte`（pyproject.toml:39） | `deeptutor/services/subagent/claude_models.py:153` | lazy，guarded | /model TUI 抓取这一条路径受影响 |
| C11 | `anthropic`（pyproject.toml:52） | `deeptutor/services/llm/provider_core/anthropic_provider.py:53` | lazy，无守卫 | 仅构造 Anthropic provider 时 import；未选该 provider 则从不加载 |
| C12 | `pageindex`（pyproject.toml:44） | `deeptutor/services/rag/pipelines/pageindex/client.py:16` | lazy，无守卫 | 仅 pageindex RAG 管线选中时 import |
| C13 | `ddgs`（pyproject.toml:28） | `deeptutor/services/search/providers/duckduckgo.py:27` | lazy，无守卫 | 仅 DuckDuckGo 搜索 provider 选中时 import |
| C14 | `redis`（pyproject.toml:86） | `deeptutor/runtime/coordination/redis.py:206` | lazy，无守卫 | 仅选择 Redis 协调后端时 import |
| C15 | `perplexityai`（pyproject.toml:54） | `deeptutor/services/search/providers/perplexity.py:37` | lazy，guarded（import 名还不匹配，见 A8/B6） | Perplexity 搜索 provider 降级报错 |

## 注记

- `mcp`（pyproject.toml:40-43）：20 处 import 中仅 1 处 top（18 处 lazy），但声明处注释已明确论证"默认聊天/工具面包含可配置 MCP 服务器，故为 core"。属有意为之，不计为漂移。
- `arxiv`（pyproject.toml:70）：`deeptutor/tools/paper_search_tool.py:13` 为顶层无条件 import，与 core 声明一致，不计入。
- C 类核心矛盾：必装面（core dependencies）被大量按可选方式消费 —— 对 C1–C10，即使从必装面移除，应用主路径也能工作（这既是"过度声明"，也是此刻"能跑"的保险）；对 C11–C14，lazy import 只解决启动开销，缺包时对应功能仍会 ImportError，声明面并未给出可选出口（无对应 extra）。
