# print / console 调试残留清点（中性清单）

- 日期：2026-10-11
- 基线：`origin/main` @ `6cf793bd8`（release v1.6.14）
- 性质：只读静态扫描，未改动任何源码、未运行任何服务
- 范围：`deeptutor/`（Python `print` 遗留）与 `web/`（`console.log` / `console.debug` 残留）
  - `web/` 排除项按卡面执行：有意保留的 dev 工具与 logger 封装内部；实际未发现 web 侧 logger 封装文件，排除项为空集
  - `console.debug` 命中 0 处；`console.error`(38) / `console.warn`(7) 不在本卡范围，仅记录计数
  - `deeptutor_web/`、`tests/`、`scripts/` 不在本卡范围

## 1. 方法

1. ripgrep 全量提取 `print(`（`deeptutor/`，22 文件 140 行）与 `console.(log|debug)`（`web/`，7 文件 17 行）。
2. AST 精确分类（脚本与原始输出见 `machine-classify.json`）：区分模块级 / `__main__` 守卫 / 函数内，并用同文件调用图判定 "main-only"（仅被 `__main__` 或 main-only 函数调用）与 "prod-path"。
3. 跨文件调用人工核查：对同文件判定为 main-only 的符号做全仓引用检查，确认是否有生产路径可达（本卡发现 2 处此类修正，见 §3）。
4. 人工复核每条命中的上下文（是否 docstring 示例、属性调用、CLI 交互分支、子进程协议输出等）。

## 2. 去重结论

与既有两轴机器清单做 `file:line` 级与文件级比对：

- 异常体轴（`evidence/log-exception-bodies-2026-10-10/scan_hits.json`，132 命中）：**零重叠**
- 敏感载荷轴（`evidence/agen-1777-logscan/machine-scan-full.csv`，310 行）：**零重叠**

两轴均针对 `logger.*` 日志调用且限定在特定域；本卡清点的 `print` / `console.*` 写点与其无任何共同行。补充说明：本清单中携带异常文本的 `print`（如 `{e}` 插值）与异常体轴同型，但机制与坐标均不重叠，已在明细中逐行标注 "无重叠"。

## 3. 汇总数字

| 侧 | 类别 | 数量 | 建议级别 |
| --- | --- | --- | --- |
| python | 疑似调试-生产路径可达 | 34 | P2（计划内整改：迁移 logger / 加静默参数） |
| python | 疑似调试-低影响 | 6 | P3（顺带整改：当前无生产调用方） |
| python | 合理保留（CLI/演示/终端UX/子进程协议/维护脚本） | 94 | 无需处理（P3-观察） |
| python | 误报排除（docstring 示例 5 + 属性调用 1） | 6 | 排除 |
| web | 合理保留（dev 工具脚本 16 + 注释示例 1） | 17 | 无需处理 |

`print` 总命中 140 = 34 + 6 + 94 + 6；`console.log` 17 + `console.debug` 0。

## 4. 疑似调试项（建议处理，共 40 处）

### P2 — 生产路径可达（34 处）

| 位置 | 数量 | 说明与建议 |
| --- | --- | --- |
| `deeptutor/tools/question/question_extractor.py` | 26 | 模块整体是 CLI 工具形态，但入口 `extract_questions_from_paper`（:321）被生产 agent 路径 `deeptutor/agents/question/mimic_source.py:117` 在回退分支调用（无 questions JSON 时），其内部 `load_parsed_paper` / `extract_questions_with_llm` / `save_questions_json` 的全部 `print`（进度、警告、错误与统计）会落到服务进程 stdout，其中 :337 为无条件打印。建议：入口加 quiet/logger 参数或整体迁移 `logger`。 |
| `deeptutor/agents/research/utils/citation_manager.py` | 5 | `CitationManager` 各方法（加载/保存/新增/解析失败）失败时 `print("⚠️ Failed to ...")`；研究 agent 生产管线（`pipeline.py`）使用该类。建议：迁移 `logger.warning`。 |
| `deeptutor/services/prompt/manager.py` | 2 | `PromptManager._load_with_fallback`（:121,:124）prompt 文件加载失败/缺失时 `print("Warning: ...")`；`base_agent` 生产加载 prompt 路径。建议：迁移 `logger.warning`。 |
| `deeptutor/agents/research/data_structures.py` | 1 | `DynamicTopicQueue._auto_save`（:554）保存队列进度失败时 `print`，研究管线生产路径。建议：迁移 `logger.warning`。 |

### P3 — 疑似但当前无生产调用方（6 处）

| 位置 | 数量 | 说明与建议 |
| --- | --- | --- |
| `deeptutor/tools/tex_chunker.py` | 5 | `TexChunker` 方法内进度/截断提示 `print`（:64,:84,:115,:116,:163）；该类当前仅被测试与 `tools/__init__` 懒导出引用，未见生产调用。建议：顺带迁移 `logger` 或加 quiet 参数。 |
| `deeptutor/tools/tex_downloader.py` | 1 | `safe_members` 内嵌函数对 tar 可疑成员跳过时的 `print`（:171），处于 `download_arxiv_source` 工具流程内；当前仅测试引用。建议：顺带迁移 `logger`（中性提示即可）。 |

## 5. 合理保留依据（摘要）

- **CLI 命令行输出（83 处）**：`knowledge/manager.py`（26 main + 3 交互确认分支）、`mineru/local.py`（27，独立解析 CLI）、`export.py`（2，契约检查脚本）、`paper_search_tool.py`（9）、`rag_tool.py`（6）、`tex_chunker.py`（4）、`tex_downloader.py`（6）均为 `__main__`/CLI 演示或命令行 UX。其中 `delete_knowledge_base` 的确认 `print`（:1824,:1825,:1828）仅在 `confirm=False` 分支触发，生产调用方（`api/routers/knowledge.py:3335`、`api/routers/subagents.py:163`）均传 `confirm=True`。
- **终端 UX / 子进程（8 处）**：`launcher.py`（4，交互式启动器日志与端口交互提示）、`update_worker.py`（1，更新 worker 在日志文件不可写时的 stderr 兜底）、`docling/local_worker.py`（2，隔离 Docling 子进程 stdout/stderr 协议输出）。
- **维护脚本（3 处）**：`reading/refresh.py` 仅被 `scripts/reading_refresh_figures.py` 调用，控制台进度/失败汇总。
- **vendored dev 脚本（1 处）**：`cli_apps/vendor/build_snapshot.py` 模块级输出。
- **web（17 处）**：`web/scripts/`（i18n 审计/巡检、route budgets、右缘探针、契约生成、图标构建）为有意保留的开发与 CI 工具；`web/lib/latex-commands.ts:14` 为 JSDoc 注释内的再生命令示例，非执行代码。

## 6. 误报排除（6 处）

| 位置 | 原因 |
| --- | --- |
| `deeptutor/runtime/banner.py:567` | `target.print(...)` 为对象方法调用（富文本 console），非内建 `print` |
| `deeptutor/runtime/stream_bus.py:17` | 模块 docstring 用法示例 |
| `deeptutor/tools/reason.py:16` | 模块 docstring 用法示例 |
| `deeptutor/services/llm/__init__.py:35` | 模块 docstring 用法示例 |
| `deeptutor/services/auth.py:11` | 模块 docstring 快速上手示例 |
| `deeptutor/agents/loop/dsml_tool_calls.py:11` | docstring 中的标记语言示例文本 |

## 文件清单

1. `detail.csv` — 全量明细（side/file/line/reachability/enclosing/context/dedup/suggestion/level/snippet，157 行）
2. `machine-classify.json` — AST 分类原始输出（含逐行函数归属与误报行）
3. `SHA256SUMS` — 本目录校验和

本清单为静态候选清点，不含任何运行时样本值；确认与修复由人决定。
