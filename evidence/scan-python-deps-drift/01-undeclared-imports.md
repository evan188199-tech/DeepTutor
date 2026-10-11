# A 类：未声明依赖（代码实际 import，任何声明层都没有）

判定口径：import 根（含动态导入）出现在主范围 `deeptutor/`+`deeptutor_cli/`，但未出现在 `pyproject.toml` 任何 `dependencies`/`extras`，也未出现在 `requirements/*.txt`。共 10 条。

| # | import 根（对应发行包） | 证据 file:line | 方式 | 守卫/回退 | 说明 |
| --- | --- | --- | --- | --- | --- |
| A1 | `anyio` | `deeptutor/services/subagent/hermes_remote.py:9` | top，无守卫 | 无 | 模块顶层直接 import；仅作为 httpx/fastapi/mcp 的传递依赖偶然可用 |
| A2 | `starlette` | `deeptutor/api/routers/video_learning.py:13` | top，无守卫 | 无 | `from starlette.background import ...`；fastapi 的传递依赖 |
| A3 | `fsspec` | `deeptutor/services/rag/pipelines/llamaindex/vector_store.py:35` | top，无守卫 | 无 | `from fsspec.implementations.local import LocalFileSystem`；llama-index 的传递依赖 |
| A4 | `lxml` | `deeptutor/services/web_source/html_extractor.py:150`、`:326`、`:595` | lazy，无守卫 | 无 | HTML 解析路径；传递依赖（llama-index 等） |
| A5 | `Crypto`（pycryptodome） | `deeptutor/partners/channels/weixin.py:1374`、`:1406` | lazy，`suppress(ImportError)` | 回退 `cryptography` | weixin 通道媒体 AES；pycryptodome 未在任何声明层出现 |
| A6 | `cryptography` | `deeptutor/partners/channels/weixin.py:1380`、`:1413`（lazy，guarded 回退告警）；`deeptutor/partners/channels/msteams.py:45`（`find_spec` 动态探测） | lazy/dynamic | A5 缺失时的回退 | 直接 import，但仅经 `python-jose[cryptography]`/`PyJWT[crypto]` extras 传递可用，无直接声明 |
| A7 | `deepseek_harness` | `deeptutor/services/subagent/deepseek_harness.py:202`（lazy）、`:248`（`importlib.util.find_spec` 探测） | lazy/dynamic | `_sdk_available()` 探测 + `except Exception` 兜底 | 可选外部 SDK（DSH_HOME），完全未声明；属"未声明的软依赖" |
| A8 | `perplexity` | `deeptutor/services/search/providers/perplexity.py:37` | lazy，guarded ImportError | 报错提示用户安装 `perplexityai` | import 名与声明的 `perplexityai`（pyproject.toml:54）不一致：声明装的是 `perplexityai`，代码 import 的是 `perplexity`，二者不可互换，存在失效风险（与 B6 成对） |
| A9 | `pandas` | `deeptutor/services/rag/pipelines/graphrag/storage.py:72` | lazy，guarded | 无 | 仅 graphrag 引擎路径；传递依赖（graphrag extra） |
| A10 | `pyarrow` | `deeptutor/services/rag/pipelines/graphrag/pandas_compat.py:49`、`:50` | lazy，guarded | 无 | 仅 graphrag 引擎路径；传递依赖（graphrag extra） |

参考范围补充（不计入主表）：`httpcore` 仅出现在 `tests/`（如 `tests/.../test_*.py` 顶层 import），主范围零命中。

## 建议方向（仅记录，不在本卡改动）

- A1–A4、A9、A10：要么显式声明（若视为直接依赖），要么改为经由已有声明面（fastapi/llama-index/graphrag）的公开入口间接使用；至少在声明处加注释说明"经传递依赖满足"。
- A5/A6：weixin/msteams 的 crypto 双回退目前靠 extras 传递兜底，若这两个通道在最小安装下可用性重要，应显式声明其一。
- A7：若 deepseek_harness 是受支持的可选后端，建议单列 extra；否则归入文档说明。
- A8：import 名与发行名对齐（二选一修正），避免声明与使用各说各话。
