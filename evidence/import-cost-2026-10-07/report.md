# 启动 import 开销与延迟加载机会清点（import-cost scan）

- 日期：2026-10-07
- 基线：HKUDS/DeepTutor `origin/main` @ `f07029cfcf2c`（release: v1.6.13）
- 方法：纯静态 AST 分析（`scan_import_cost.py`，仅标准库），不导入、不执行任何产品代码；全程只读
- 轴范围（与兄弟卡去重）：本卡只覆盖 **依赖深度 / 重依赖顶层 import 位置 / 函数内 lazy import 分布**。
  循环轴归 scan-import-cycles，启动顺序与单例轴归 scan-startup-order，文件大小轴归 scan-hotspots，
  均不在本报告展开。
- 边语义：`graph` 只含模块级（含模块级 try/if 守卫）import，即 import 时真实执行的边；
  函数体内 import 记入 `lazy_edges`，不参与启动可达性计算。

## 1. 入口 import 图总览

| 入口 | 说明 | 启动可达模块数 | 最大 import 深度 | 启动即加载的重/中依赖（顶层 import 文件数） |
|---|---|---|---|---|
| `deeptutor_cli.main` | console script `deeptutor` | 170 | 8 | typer(16), pydantic(15), rich(11), httpx(9), yaml(3) |
| `deeptutor.__main__` / `deeptutor_cli.__main__` | `python -m deeptutor` | 171 | 9 | 同上（叠加 CLI 一层） |
| `deeptutor.api.main` | FastAPI app 模块 | 454 | 8 | pydantic(56), fastapi(49), httpx(31), yaml(10), aiohttp(1), jinja2(1), uvicorn(1) |
| `deeptutor.api.run_server` | uvicorn 启动器 | 1 | 1 | uvicorn(1)（其余全部在 `main()` 内 lazy import） |
| `deeptutor.api.contracts.export` | console script | 4 | 3 | pydantic(3) |
| `scripts.start_web` | 手动 web 启动器 | 8 | 3 | httpx(1), rich(1) |

结论：**重量级原生依赖（llama_index / lightrag / docling / faiss / PyMuPDF / pandas / numpy /
PIL / sentence_transformers / anthropic / openai）均不出现在任何入口的启动可达集里**，
现有 lazy import 纪律良好。启动开销集中在：CLI 的 typer/rich/pydantic/httpx，
API 的 pydantic/fastapi/httpx 全量 router 聚合。

## 2. 重依赖登记（全仓静态计数，按文件去重）

| 包 | 顶层 import 文件 | 函数内 lazy 文件 | 守卫 import | 启动可达（任一入口） |
|---|---|---|---|---|
| fastapi | 50 | 0 | 0 | api.main（核心栈）；CLI 启动不可达 |
| pydantic | 86 | 0 | 0 | CLI(15) + api.main(56) |
| httpx | 68 | 5 | 1 | CLI(9) + api.main(31) |
| requests | 16 | 0 | 0 | 0（均非启动路径） |
| typer / rich | 17 / 12 | 0 / 1 | 0 | CLI 全量（CLI 框架本身，不列为问题） |
| yaml | 15 | 4 | 0 | CLI(3) + api.main(10) |
| openai | 6 | 1 | 0 | 0 |
| aiohttp | 6 | 0 | 0 | api.main(1) |
| llama_index | 6 | 2 | 0 | 0（全部限 RAG pipeline，factory 已按需 lazy） |
| lightrag | 1 | 4 | 1 | 0 |
| docling | 0 | 5+1 本地壳 | 0 | 0（真实 docling import 已在函数内） |
| faiss / PyMuPDF(fitz) / pandas / PIL / sentence_transformers / anthropic | 0 | 各 1–7 | 0 | 0 |
| numpy | 1 | 1 | 0 | 0（仅 `rag/pipelines/llamaindex/vector_store.py`，启动不可达） |
| jinja2 | 1 | 0 | 0 | api.main(1) |
| uvicorn | 1 | 1 | 0 | api.main / run_server（服务端必需） |

## 3. 可延迟加载清单（建议条目）

### A 级：CLI 启动路径（收益高、改动小）

**A1. `deeptutor_cli/init_wizard.py:19` — httpx 顶层 import，拖累所有 CLI 命令**
现状：`import httpx` 位于模块顶层；实际使用仅在 4 个方法内（`deeptutor_cli/init_wizard.py:644`、`:767`、`:891`、`:951` 的 `httpx.Client(...)`）。
建议：移入使用处函数体。收益：每次 CLI 调用少加载 httpx 全家（约 9 个启动可达文件依赖 httpx，本文件是唯一 CLI 启动关键项）。

**A2. `deeptutor_cli/main.py:19-33` — 15 个命令模块全部顶层 `register`，导致命令子树整棵启动**
现状：CLI 启动即 import notebook/book/kb/partner 等全部命令模块。典型链条：
`deeptutor_cli/notebook.py:10-11`：
```python
from deeptutor.app import DeepTutorApp
from deeptutor.services.notebook.service import NotebookCorruptedError
```
→ `deeptutor/services/llm/__init__.py:55-102` 顶层 re-export 整个 LLM 子系统（client/factory/multimodal/…）→ `deeptutor/config/settings.py`（pydantic）。
即运行 `deeptutor --help` 也会加载 LLM 配置栈。
建议：命令模块内把服务层 import 下沉到命令函数体（typer 注册只需函数名，不需服务层）。定性收益：CLI 启动 170 模块可显著收缩（预计降至 100 以下），pydantic(15) 链条大部分消失。

### B 级：API 启动路径（中等收益）

**B1. `deeptutor/services/voice/adapters/dashscope.py:13` — aiohttp 顶层 import**
现状：`import aiohttp` 顶层；API 启动链 `deeptutor.api.main → api/routers/reading_extensions → services/voice → services/voice/adapters → dashscope`。
建议：移入请求方法。收益：API 启动少加载 aiohttp（该入口唯一 aiohttp 文件）。

**B2. `deeptutor/services/search/consolidation.py:13` — jinja2 顶层 import**
现状：`from jinja2 import BaseLoader, Environment` 顶层；经 api.main 路由树启动即加载。
建议：移入模板渲染函数。收益：API 启动少加载 jinja2。

**B3.（结构性观察，大改慎动）`deeptutor/api/main.py:524-631` — 约 40 个 router 顶层聚合**
API 启动 454 模块、pydantic(56)/httpx(31) 主要由全量 router 聚合驱动。FastAPI 惰性挂载重构收益最大但改动面广，单独立项，不建议顺手做。

### C 级：分层卫生（非启动关键，随手修）

**C1. 服务层模块顶层依赖 fastapi.HTTPException**
`deeptutor/multi_user/skill_access.py:7`、`deeptutor/multi_user/partner_access.py:28`、`deeptutor/multi_user/knowledge_access.py:9`、`deeptutor/services/workspace/knowledge.py:11`（例：`from fastapi import HTTPException`，`skill_access.py:74` `raise HTTPException(status_code=403, ...)`）。
服务层被 CLI 侧 `deeptutor_cli/partner → services/partners/workspace → multi_user/skill_access` 引用（当前为 lazy 边，未进 CLI 启动集）。建议改领域异常，防止未来被顶层引用后把 fastapi 拖进 CLI。

**C2. `deeptutor/services/rag/pipelines/lightrag/parser.py:9` — 全仓唯一 lightrag 顶层 import**
现状：`from lightrag.parser.base import BaseParser`。已确认所有入口启动均不可达，保持现状即可；如未来被 `__init__` 聚合会破坏隔离，登记在案。

**C3. 产品树内嵌测试模块**
`deeptutor/learning/tests/test_api_endpoints.py:7-8` 顶层 `from fastapi import FastAPI` / `from fastapi.testclient import TestClient`。启动不可达，但随包发布；建议迁出产品包或改 `TYPE_CHECKING`/延迟。

### 已达标（无需动作，登记备查）

- `deeptutor/services/rag/factory.py`：对 llamaindex/lightrag 等 pipeline 全部函数内 lazy import，`deeptutor kb` 命令不会启动 llama_index。
- `deeptutor/api/run_server.py`：除 uvicorn 外全部在 `main()` 内 import，启动器本身零负担。
- openai SDK：6 个顶层文件均不在任何入口启动可达集。
- docling：`services/parsing/engines/formats.py:5` 仅引本地壳，真实 `docling` import 已 lazy（5 处）。

## 4. 附带观察（归兄弟卡，不在本卡展开）

- import 即副作用：`deeptutor_cli/main.py:28-29`（`set_mode` + `configure_logging`）、
  `deeptutor/api/main.py:20-22`（写运行时配置文件 + 导出环境变量）。属启动顺序/单例轴（scan-startup-order）。

## 5. 复现

```bash
cd <repo 工作区根>   # 本分支（agen1004-import-cost-20261007）
python3 evidence/import-cost-2026-10-07/scan_import_cost.py \
  --repo . --out evidence/import-cost-2026-10-07/import_cost.json
# 输出与本目录 import_cost.json 一致；共索引 1066 个第一方模块
```

产物：`import_cost.json`（全量依赖图 + 逐入口重依赖 + lazy/guarded 明细）、
`scan_import_cost.py`（复现脚本）、`SHA256SUMS`。
