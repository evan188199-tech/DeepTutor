# 依赖声明与实际 import 漂移扫描报告

- 日期：2026-10-04
- 基线：origin/main @ `f07029cfc`（release: v1.6.13），在新 worktree 只读扫描，未改任何代码、未联网安装依赖
- 方法：AST 解析全部 Python import（含 try/except ImportError、`with suppress(ImportError)`、TYPE_CHECKING、函数级 lazy、`importlib.import_module/find_spec` 动态目标）；正则提取 web/ 全部 `import/require/import()` 包引用；解析 pyproject.toml、requirements/*.txt、packaging/deeptutor-cli/pyproject.toml、web/package.json、web/package-lock.json 做四方比对
- 结论供人工决定增删，本卡不改依赖

## 覆盖面

| 侧 | 输入 | 规模 |
| --- | --- | --- |
| Python | deeptutor/ deeptutor_cli/ deeptutor_web/ scripts/ tests/ | 1818 个 .py（0 解析错误），约 22k 条 import 记录，176 个非相对顶级模块名 |
| Python 清单 | pyproject.toml（core 53 项 + 19 个 extras）、requirements/ 9 个镜像文件、packaging/deeptutor-cli（44 项） | 全部解析 |
| Web | web/ 下 ts/tsx/js/mjs | 691 个文件含外部 import，去重 38 个外部包 |
| Web 清单 | web/package.json（22 deps + 21 devDeps）、package-lock.json v3 | 全部解析 |

---

## 一、未声明却 import（Python，14 项）

按风险排序；"传递自"表示当前只靠某声明包的传递依赖才可解析，属直接 import 未声明。

| # | 包（import 名） | 用点（import 链证据） | 状态 | 备注 |
| --- | --- | --- | --- | --- |
| 1 | `deepseek_harness` | `deeptutor/services/subagent/deepseek_harness.py:202`（函数内）；上游探针 `deeptutor/services/subagent/models.py:248`（`find_spec("deepseek_harness")`） | lazy + find_spec 门控 | **重点**：任何清单/extra 都没有它，用户无法经本项目的 pip 依赖获得；建议新增 optional extra 或文档化外部安装 |
| 2 | `lxml` | `deeptutor/services/web_source/html_extractor.py:150、326、595`（函数内，import 在 try 之外） | lazy，无 guard | **重点**：web 抓取路径触发即 ImportError；没有任何核心依赖链保证 lxml 存在 |
| 3 | `Crypto`（pycryptodome） | `deeptutor/partners/channels/weixin.py:1374、1406`（`with suppress(ImportError)`） | 有 fallback（降级到 cryptography，再缺则告警返原文） | 未声明；注释自认 pycryptodome 是维护版首选 |
| 4 | `cryptography` | `deeptutor/partners/channels/weixin.py:1380、1413`（try/except ImportError） | 有 fallback | 直接 import，但只作为 python-jose[cryptography] / PyJWT[crypto] 的传递依赖存在 |
| 5 | `starlette` | `deeptutor/api/routers/video_learning.py:13`（模块顶，路由启动即加载）；另有 11 个 tests/api、tests/video_learning 文件 | eager，无 guard | 传递自 fastapi；fastapi 今日必然带入，风险低但属直接依赖传递依赖 |
| 6 | `anyio` | `deeptutor/services/subagent/hermes_remote.py:9`（模块顶）；加载链 `deeptutor/services/subagent/__init__.py:28` 无条件 | eager，无 guard | 传递自 httpx→httpcore |
| 7 | `fsspec` | `deeptutor/services/rag/pipelines/llamaindex/vector_store.py:35`（模块顶 `from fsspec.implementations.local import ...`） | eager，无 guard | 传递自 llama-index-core；默认 RAG 向量库路径 |
| 8 | `pandas` | `deeptutor/services/rag/pipelines/graphrag/storage.py:72`（函数内，try/except 全包裹） | 有 fallback | 传递自 graphrag extra |
| 9 | `pyarrow` | `deeptutor/services/rag/pipelines/graphrag/pandas_compat.py:49-50` | guarded | 传递自 graphrag/lightrag-hku |
| 10 | `graphrag_llm` | `deeptutor/services/rag/pipelines/graphrag/completion_adapter.py:116、196、245`、`engine.py:148-174、256`（函数内） | lazy，无局部 guard | 依赖 `find_spec("graphrag")` 的上游探针；包本身未声明（假定随 graphrag dist 提供，离线无法验证，建议 `pip show graphrag` 复核） |
| 11 | `graphrag_storage` | `engine.py:381-382`（函数内） | 同上 | 同上 |
| 12 | `graphrag_cache` | `tests/services/rag/test_graphrag_pipeline.py:785`（函数内） | lazy | 仅测试；同上 |
| 13 | `httpcore` | `tests/services/llm/test_openai_codex_oauth_provider.py:6`（模块顶） | eager | 传递自 httpx；仅测试 |
| 14 | `packaging` | `scripts/install_extras.py:66`（函数内） | lazy | 事实标准库（setuptools 提供）；建议列入 dev extra |

## 二、声明未用（Python）

**候选可删/待确认（代码 0 import）**：

| 包 | 声明位置 | 证据 | 建议 |
| --- | --- | --- | --- |
| `aiosqlite` | core | 全仓 grep 仅 pyproject 命中 | 重点确认：疑似历史遗留（旧异步存储层）；确认后可从 core 移除 |
| `tenacity` | core | 全仓 0 引用 | 传递消费方可能需要（如 lightrag-hku）；建议 `pip show` 确认后决定移除或改为传递自然带入 |
| `prompt-toolkit` | core | 全仓 0 引用 | CLI 交互已走 typer/rich；疑似遗留 |
| `nest-asyncio` | core | 仅注释提到 `graphrag_llm` 内部用 `nest_asyncio2`（不同包） | 疑似遗留；确认 graphrag 链路后可移除 |
| `pdfplumber` | core | 代码不 import；用于 `deeptutor/skills/builtin/pdf/SKILL.md` playbook 与 Dockerfile.runner sidecar | 保留（模型生成代码的运行时），建议加注释说明 |
| `docling-slim` | parse-docling extra | 经 `docling` 包使用（`services/parsing/engines/_install.py`） | 保留（format backends 载体） |

**工具/传输类，非"未用"**（无 import 属预期）：bandit、safety、pre-commit、import-linter（CI/dev 工具）；python-multipart、uvicorn（FastAPI 运行时钩子）；python-socks、socksio、websocket-client、msgpack（SDK 传输层，由各 SDK 消费）。

## 三、可选依赖缺 fallback 的导入点

**判定为"缺 fallback"的导入点（4 处，全部同时见第一节）**：

1. `fsspec` — `deeptutor/services/rag/pipelines/llamaindex/vector_store.py:35`：eager、模块顶、核心 RAG 路径，无任何 guard；建议 try/except + 降级 SimpleVectorStore 或显式声明。
2. `lxml` — `deeptutor/services/web_source/html_extractor.py:150、326、595`：lazy 但 import 在 try 外，抓取路径触发即崩；建议 guard 或声明。
3. `starlette` — `deeptutor/api/routers/video_learning.py:13`：eager、路由启动即加载；建议改用 `fastapi.responses.BackgroundTask` 等价物或显式声明 starlette。
4. `anyio` — `deeptutor/services/subagent/hermes_remote.py:9`：eager、subagent 包 `__init__` 无条件加载链；建议 lazy 化或声明。

**判定为"已有 fallback / 设计如此"（无需处理）**：

| 组 | 机制 | 证据 |
| --- | --- | --- |
| partner channels（telegram、slack、dingtalk、qq-botpy、msteams(PyJWT)、feishu/lark-oapi、wecom、zulip、mochat/socketio）模块顶 SDK import 无局部 guard | 设计如此：`deeptutor/partners/channels/registry.py` `discover_all_with_errors()` 逐模块 import，ImportError 记入 UI | registry.py:14-26 注释与 manager.py:222-245 |
| parse 引擎（markitdown、docling、pymupdf4llm、liteparse） | `find_spec` 可用性探针 + lazy import | 动态 import 记录见 raw/py_imports.json |
| graphrag、lightrag-hku | `find_spec("graphrag")` x1、`find_spec/import_module("lightrag")` x5 探针 | 同上 |
| sentence-transformers（rag-rerank） | 调用方 try/except ImportError → 告警并回退 embedding-only | `llamaindex/rerank.py:43-56` |
| codebuddy-agent-sdk | 4/4 import 点 guarded | `services/codebuddy_auth.py:213` 等 |
| matrix-nio/mistune/nh3/msgpack/python-socketio | 17/17、guarded（try/except ImportError） | `channels/matrix.py:13-39`、`channels/mochat.py:22-30` |
| qrcode、psutil、croniter、dashscope、youtube-transcript-api、pocketbase、perplexityai、oauth-cli-kit、wecom-aibot-sdk、lark_oapi | lazy import + 清晰 ImportError 提示（部分有 find_spec 探针） | 各文件，见 raw 数据 |

## 四、版本约束与实际用法漂移

1. **requirements/cli.txt vs pyproject `cli` extra**：`oauth-cli-kit` 镜像多了 `; python_version >= "3.11"` 标记（pyproject 无）。语义等价（requires-python 已 >=3.11），纯文本漂移，二选一抹平。
2. **youtube-transcript-api 下限不一致（pyproject 内部）**：core `>=1.2.0,<2.0.0` vs `video-learning` extra `>=1.0.0,<2.0.0`。extra 下限比 core 宽松；同装时 union 生效 1.2.0，但声明口径不一，建议统一。
3. **aiohttp（pyproject 内部，备注）**：core `>=3.9.4` vs partners `>=3.10.0,<4.0.0`（napcat 媒体下载需要）。属有意收紧，pip union 后无冲突；仅备注 core 安装与 partners 安装行为不同。
4. **Dockerfile.runner 12 项 pip 安装全部无版本约束**：`numpy` 在 pyproject 有 `>=1.24.0,<3.0.0` 上限而 runner 无上限（可能装入 numpy 3.x，与主程序约束漂移）；`pandas`、`lxml` 任何清单均未声明（仅 runner 注释称与 SKILL.md playbook 对齐）。建议 runner 同步 pyproject 口径或加注释说明独立基线。
5. **CI/运行时版本一致性（无漂移）**：`.github/workflows/tests.yml` 矩阵 3.11–3.14 与 `requires-python = ">=3.11,<3.15"` 一致；CI node 22 与 Dockerfile `node:22-slim` 一致；web/package.json 43 项声明在 package-lock.json 的解析版本全部满足声明范围（0 漂移）；`epubjs` override `@xmldom/xmldom ^0.9.12` → lock 0.9.12 满足。

## 五、Web 侧清单

**未声明却 import（3 项）**：

| 包 | 用点 | 现状 |
| --- | --- | --- |
| `jszip` | `web/tests/epub-reader.audit.ts:2` `import JSZip from "jszip"`（静态） | **重点**：仅经 epubjs 传递可用；epubjs 一旦换打包即断，建议显式 devDependencies |
| `playwright`（裸包） | `web/scripts/probe-right-edge.mjs:1` `import { chromium } from "playwright"` | 仅 `@playwright/test` 声明（其依赖带入 playwright）；脚本路径脆弱 |
| `prettier` | `web/scripts/generate-contracts.mjs:6` `import { format } from "prettier"` | 仅经 json-schema-to-typescript 传递可用；建议显式 devDependencies |

**声明未用（运行时 deps 3 项候选；devDeps 均为工具类，非未用）**：

| 包 | 类型 | 证据 | 建议 |
| --- | --- | --- | --- |
| `react-chartjs-2` ^5.3.1 | dependencies | 代码直接 import `chart.js`（`components/visualize/VisualizationViewer.tsx`、`lib/latex.ts` 等），全仓无 react-chartjs-2 import | 重点确认：包装层疑似弃用，确认后可移除或回归包装层用法 |
| `html2canvas` ^1.4.1 | dependencies | 全仓 0 引用 | 确认后可移除 |
| `cytoscape` ^3.33.1 | dependencies | 无业务 import；`next.config.js:177-198` 仅为 mermaid 的传递依赖做 CJS 别名固定 | 保留（构建别名 + 传递依赖固定），建议加注释 |

devDeps 无 import 但在用（非未用）：@types/*（ambient）、autoprefixer/postcss/tailwindcss（构建配置）、eslint 系（lint 脚本）、jsdom（vitest 配置）、json-schema-to-typescript/openapi-typescript（contracts 脚本）、dependency-cruiser（architecture:check）、@testing-library/dom（testing-library/react 的 peer）。

**可选依赖缺 fallback（web）**：无 optionalDependencies/peerDependencies；动态 `import()` 的包均在声明内 → 0 项。

**版本漂移（web）**：0 项（见第四节第 5 条）。

---

## 汇总计数

| 类别 | Python | Web |
| --- | --- | --- |
| 未声明却 import | 14 | 3 |
| 声明未用（候选，排除工具/传输类） | 6（其中 4 项疑似可删：aiosqlite、tenacity、prompt-toolkit、nest-asyncio） | 3（其中 2 项疑似可删：react-chartjs-2、html2canvas） |
| 可选依赖缺 fallback 导入点 | 4 处（fsspec、lxml、starlette、anyio） | 0 |
| 版本约束漂移 | 4 项（oauth-cli-kit 镜像标记、youtube-transcript-api 下限、aiohttp 双口径备注、Dockerfile.runner 无约束） | 0 |

原始数据：`raw/py_imports.json`、`raw/web_imports.json`、`raw/analysis.json`、`raw/web_analysis.json`；复扫命令：`python3 evidence/scan-deps-20261004/scripts/py_imports.py . && python3 evidence/scan-deps-20261004/scripts/web_imports.py . && python3 evidence/scan-deps-20261004/scripts/compare.py . && python3 evidence/scan-deps-20261004/scripts/web_compare.py .`
