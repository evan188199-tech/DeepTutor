# B 类：声明未用（声明存在，零 import 证据）

判定口径：声明面（`pyproject.toml` + `requirements/*.txt`）列出的发行包，在主范围与参考范围（AST 三类 import + 常量串动态导入 + grep 复核）均无 import 证据。共 9 条硬命中 + 2 条注记。

## Core（`[project] dependencies`，pyproject.toml）

| # | 发行包（声明行） | 证据 | 说明 |
| --- | --- | --- | --- |
| B1 | `nest_asyncio`（pyproject.toml:29；requirements/cli.txt） | AST + `rg` 全范围 0 命中 | 代码从不 import；若为 notebook/嵌入式运行兜底，建议加注释说明，否则可移除 |
| B2 | `tenacity`（pyproject.toml:30；requirements/cli.txt） | 0 命中 | 仅作为 llama-index 等的传递依赖被消费 |
| B3 | `prompt_toolkit`（pyproject.toml:38；requirements/cli.txt） | 0 命中 | 交互式 TUI 相关，代码无任何引用（终端抓取用的是 `pyte`，见 C10） |
| B4 | `pdfplumber`（pyproject.toml:75；requirements/cli.txt） | 0 import；唯一命中 `tests/test_packaging_metadata.py:197`（断言声明字符串本身） | 文档解析已走 pymupdf/docling/markitdown/liteparse 引擎 |
| B5 | `oauth-cli-kit`（pyproject.toml:55；requirements/cli.txt） | 主范围 0 import；`tests/services/llm/test_openai_codex_oauth_provider.py:297-301` 断言 provider 源码不 import 它；`tests/cli/test_provider_cli.py:79` 断言命令表不含它 | 测试明确固化了"不再使用"的现状 |
| B6 | `perplexityai`（pyproject.toml:54） | 0 命中其规范 import 名 `perplexityai`（仅报错文案提及） | 与 A8 成对：代码 import 的是 `perplexity`，声明的发行包 `perplexityai` 的规范模块名并不匹配 |

## Partners（`[project.optional-dependencies].partners`，requirements/partners.txt）

| # | 发行包（声明行） | 证据 | 说明 |
| --- | --- | --- | --- |
| B7 | `python-socks`（pyproject.toml:193；requirements/partners.txt） | 0 import | 仅在 `python-telegram-bot[socks]` 启用 socks 代理时被传递消费 |
| B8 | `socksio`（pyproject.toml:194；requirements/partners.txt） | 0 import | aiohttp socks 支持的传递消费 |
| B9 | `websocket-client`（pyproject.toml:195；requirements/partners.txt） | 0 import（根 `websocket` 全范围零命中） | napcat 通道实际使用异步库 `websockets`（`deeptutor/partners/channels/napcat.py:24-25`），声明注记里说的正是 async websockets；同步版 websocket-client 无人使用 |

## 注记（非删除候选）

- `python-multipart`（pyproject.toml:82）：代码 0 直接 import，但 FastAPI 处理 multipart 表单/`UploadFile` 在运行时必需（`deeptutor/api/routers/knowledge.py`、`deeptutor/api/routers/file_library.py`、`deeptutor/partners/channels/email.py`、`deeptutor/partners/channels/discord.py`、`deeptutor/services/skill/hub.py`、`deeptutor/services/voice/adapters/openai_compat.py`、`deeptutor/services/voice/config.py`）。属"框架消费型"依赖，建议保留并加注释，而非移除。
- dev 工具 `pre-commit`/`safety`/`bandit`/`import-linter`（pyproject.toml:279-282）：CLI 工具，按设计无 Python import，零命中属预期，不计漂移。
