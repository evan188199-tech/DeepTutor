# deps-transitive-declare 2026-10-11（A 类显式声明 + extra 草案）

- 基线：origin/main `6cf793bd868ba5ecbe64722936d4be8fab5a01df`（v1.6.14），新 worktree 新分支。
- 输入：`evidence/scan-python-deps-drift/01-undeclared-imports.md`（A 类）、`03-optional-as-required.md`（C 类）。
- 改动文件：`pyproject.toml`、`requirements/cli.txt`、`requirements/server.txt`、`packaging/deeptutor-cli/pyproject.toml`。

## 逐条结论（A 类）

| 项 | import 根 | 结论 | 落点 |
| --- | --- | --- | --- |
| A1 | anyio（hermes_remote.py:9，顶层无守卫） | 显式声明 `anyio>=4.0.0` | 主 pyproject core deps + requirements/cli.txt + packaging/deeptutor-cli |
| A2 | starlette（api/routers/video_learning.py:13，顶层无守卫） | 显式声明 `starlette>=0.27.0`（对齐 fastapi>=0.100 下限） | 主 pyproject core deps + requirements/server.txt |
| A3 | fsspec（llamaindex/vector_store.py:35，顶层无守卫） | 显式声明 `fsspec>=2023.5.0`（对齐 llama-index-core 下限） | 主 pyproject core deps + requirements/cli.txt + packaging/deeptutor-cli |
| A4 | lxml（web_source/html_extractor.py:150/326/595，lazy 无守卫） | 显式声明 `lxml>=4.9.0`；此前经 python-docx/ddgs/arxiv 传递满足，安装集不变 | 主 pyproject core deps + requirements/cli.txt + packaging/deeptutor-cli |
| A7 | deepseek_harness（deepseek_harness.py:202 lazy、:248 find_spec 探测） | 单列 extra：`deepseek-harness = ["deepseek-harness>=0.3.0,<0.4.0"]`，跟踪当前 0.3.x 系列 | 主 pyproject extras |
| A9 | pandas（graphrag/storage.py:72，lazy 有守卫） | 显式声明进 `graphrag` extra（`pandas>=2.0.0`，带 `python_version < '3.14'` 标记，随 graphrag） | 主 pyproject graphrag extra |
| A10 | pyarrow（graphrag/pandas_compat.py:49-50，lazy 有守卫） | 显式声明进 `graphrag` extra（`pyarrow>=14.0.0`，同标记） | 主 pyproject graphrag extra |
| A5/A6 | Crypto/cryptography（weixin/msteams） | 不在本卡（`fix-deps-crypto-declare` 轴） | — |
| A8 | perplexity（import 名错位） | 不在本卡（`fix-deps-perplexity-import` 轴） | — |

四项核心声明（anyio/starlette/fsspec/lxml）均为本就经传递安装的包，显式声明不改变解析后的安装集；版本下限均不高于既有传递链实际解析版本。

## C11–C14 extra 出口草案

- 代码均为 lazy 无守卫 import（anthropic_provider.py:53、pageindex/client.py:16、duckduckgo.py:27、coordination/redis.py:206），缺包时对应功能 ImportError，声明面此前无可选出口。
- 新增 extras：`anthropic`、`pageindex`、`ddgs`、`redis`，版本范围与 core 声明逐字一致。
- core 必装面不动（从 core 移除属上游打包决策，本卡不做）；这些 extras 今天是默认安装之上的加法 no-op，为将来 core 瘦身预留出口。

## 验证（可复现）

环境：python 3.13.13 全新 venv（`python -m venv`）。

```bash
python -m venv /tmp/venv-check && /tmp/venv-check/bin/python -m pip install -e <worktree>   # 3m08s
/tmp/venv-check/bin/python -m pip check            # -> No broken requirements found. (exit 0)
/tmp/venv-check/bin/python -m pip install --dry-run "deeptutor[anthropic]" "deeptutor[pageindex]" "deeptutor[ddgs]" "deeptutor[redis]"   # exit 0, 0.5s
/tmp/venv-check/bin/python -m pip install --dry-run "deeptutor[graphrag]"                # exit 0, 24s（pandas/pyarrow 随 extra 一并解析）
/tmp/venv-check/bin/python -m pip install "deepseek-harness>=0.3.0,<0.4.0" && /tmp/venv-check/bin/python -c "from deepseek_harness import DeepSeekHarness"   # 0.3.1 import OK
/tmp/venv-check/bin/python -m pip check            # 装完 deepseek-harness 后复跑，仍 No broken requirements found.
/tmp/venv-check/bin/python -m pip install --dry-run --no-deps packaging/deeptutor-cli    # exit 0（CLI 发行版带新声明可构建）
```

安装后元数据核对（importlib.metadata）：

- core Requires-Dist 新增：`anyio>=4.0.0`、`fsspec>=2023.5.0`、`lxml>=4.9.0`、`starlette>=0.27.0`；实装 anyio 4.15.1 / starlette 1.7.0 / fsspec 2026.9.0 / lxml 6.1.3。
- `pandas`/`pyarrow` 不在 core（仅 `extra == "graphrag"` 且 `python_version < "3.14"`），必装面无感。
- Provides-Extra 含 `deepseek-harness`、`anthropic`、`pageindex`、`ddgs`、`redis`。

## import 面证据（复现命令，分支内执行）

```bash
grep -n "^import anyio" deeptutor/services/subagent/hermes_remote.py                    # :9
grep -n "from starlette" deeptutor/api/routers/video_learning.py                        # :13
grep -n "from fsspec" deeptutor/services/rag/pipelines/llamaindex/vector_store.py       # :35
grep -cn "from lxml import html" deeptutor/services/web_source/html_extractor.py        # 3 处（:150/:326/:595）
grep -n "import pandas" deeptutor/services/rag/pipelines/graphrag/storage.py            # :72（try 内）
grep -n "import pyarrow" deeptutor/services/rag/pipelines/graphrag/pandas_compat.py     # :49（try 内）
grep -n "deepseek_harness" deeptutor/services/subagent/deepseek_harness.py              # :44/:202/:248
grep -n "from anthropic" deeptutor/services/llm/provider_core/anthropic_provider.py     # :53
grep -n "from pageindex" deeptutor/services/rag/pipelines/pageindex/client.py           # :16
grep -n "from ddgs" deeptutor/services/search/providers/duckduckgo.py                   # :27
grep -n "from redis.asyncio" deeptutor/runtime/coordination/redis.py                    # :206
```

## C1–C10 必装面零改动证明

```bash
git diff -- pyproject.toml requirements/ packaging/ | grep -E "^[+-]" | grep -vE "^(\+\+\+|---)" | grep -icE "bm25|faiss|psutil|qrcode|dashscope|youtube-transcript|pocketbase|croniter|pyte|perplexityai"
# -> 0
```

C11–C14 的 core 声明行同样零改动（只增 extras，不删 core）。
