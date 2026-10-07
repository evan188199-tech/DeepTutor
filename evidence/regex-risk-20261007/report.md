# 正则复杂度与回溯风险性能清点（AGEN-1001）

- 仓库基线：`HKUDS/DeepTutor` `origin/main` @ `f07029cfc`（release: v1.6.13）
- 分支：`scan/regex-risk-20261007`（只读清点，未改任何产品代码）
- 日期：2026-10-07
- 结论：**PASS** —— 全仓 1210 个正则调用点静态清点完成；**无高危**，19 个中危（超时风险为大型输入上的二次方级回扫/累积，均非灾难性指数回溯），66 个动态模式待人工核对（已抽样归入低危），其余低危。

## 范围与去重边界

- 只做**性能与稳定性**轴的静态评估；不包含任何利用性描述。
- 与其他卡去重：`scan-error-messages`（错误话术轴）、`test-search-source-filter`（`services/search/source_filter.py` 单点行为验证）不在本卡范围；本卡仅把相关调用点纳入清点计数。

## 覆盖与总体数字

| 维度 | 数量 |
|---|---|
| Python `re.*` 调用 + 编译对象方法调用 | 824 |
| Web（TS/TSX/JS/MJS 正则字面量 + `new RegExp`） | 386 |
| 合计调用点 | **1210**（每条含 `path:line`，见 `regex_callsites.json`） |

分级分布：low 1125 / medium 19 / high 0 / review 66。
输入上界估计（按变量名与模块路径启发）：large 299 / small 213 / tiny 177 / unknown 521；热路径（每请求/每消息执行）标记见 JSON `hot_path` 字段。

## 方法

1. `regex_inventory.py`：Python 用 AST 抽取 `re.<op>` 调用与已编译 `re.Pattern` 的方法调用（含模块/函数作用域的 `re.compile` 赋值跟踪）；Web 用轻量词法器抽取正则字面量与 `new RegExp("...")`（跳过字符串/注释/模板串，排除 JSX 闭合标签误报）。
2. `regex_risk_analyze.py`：对每条模式解析出结构树，检测四类签名：嵌套无界量词、交替分支首集合重叠、相邻无界量词重叠、惰性任意字符扫描；再结合输入上界与热路径启发式给出初分级。
3. 隔离计时探针：对有结构性签名的 28 条模式，在独立子进程（Python `re` 25 条、node/V8 2 条，另有 1 条复用）内用**按模式字符集合成**的输入（`a`×n、`ab` 交替、混空格、换行族，n 递增至 20000）实测；超时/超线性自动标记。探针协议经负样本校验：`(a+)+$`、`(x+x+)+y`、`(\w+\s?)*$`、`(a*)*b` 均被正确判为 catastrophic，良性模式 `a{1,2}` 保持线性。
4. 人工复核 11 条（≥5 要求）：9 条维持、2 条下调，记录见 `regex_risk_data.json` 的 `manual_review`。

## 分级口径

- **high**：探针确认指数级/超时，或结构性灾难签名 + 大型不可信输入（本轮为 0）。
- **medium**：大型热路径输入上的二次方级最坏情形（惰性扫描失败回扫、流式累积重扫），或探针确认超线性。全部 19 条属此类，均非指数级。
- **low**：无签名、或签名存在但探针实测线性至 n=20000、或输入有界。
- **review**：模式为动态构造或静态不可恢复，无法机判（66 条，已抽样核对均为低危形态）。

## Medium 清单（19 条，含建议）

| # | 位置 | 模式要点 | 原因 | 建议 |
|---|---|---|---|---|
| 1 | `deeptutor/agents/loop/dsml_tool_calls.py:83` | DSML invoke 标签 finditer | 流式缓冲无闭合时逐 chunk 全量重扫，整流 O(n²) | 给 pending 块加长度上限（对齐 `_MAX_PARTIAL_TAG_CHARS` 思路），超限原样释放 |
| 2 | `deeptutor/agents/loop/dsml_tool_calls.py:255` | 同上（finditer） | 同上 | 同上 |
| 3 | `deeptutor/agents/loop/dsml_tool_calls.py:261` | parameter 标签 finditer | 同上 | 同上 |
| 4 | `deeptutor/agents/loop/dsml_tool_calls.py:211` | DSML 检测 search | 大型流文本上的惰性类扫描 | 同上（缓冲上限后自然消除） |
| 5 | `deeptutor/agents/research/utils/json_utils.py:25` | ```` ```(?:json)?\s*([\s\S]*?)\s*``` ```` | 模型输出无闭合围栏时回扫 | 扫描长度设上限或失败即返回 |
| 6 | `deeptutor/agents/_shared/json_output.py:18` | `<think...>.*?</think>` | 无闭合 think 块时回扫 | 同上 |
| 7 | `deeptutor/agents/_shared/json_output.py:30` | json 围栏 findall | 同 5 | 同 5 |
| 8 | `deeptutor/agents/question/pipeline.py:1390` | `(.*?)` 围栏 | 同 5 | 同 5 |
| 9 | `deeptutor/agents/vision_solver/vision_solver_agent.py:157` | json 围栏 findall | 同 5 | 同 5 |
| 10 | `deeptutor/services/skill/service.py:352` | `^---\s*\n(.*?)\n---` | 技能 markdown（KB 级）缺闭合围栏时多趟扫描 | 仅对前 8KB 做 frontmatter 匹配 |
| 11 | `deeptutor/services/skill/service.py:951` | 同上 | 同上 | 同上 |
| 12 | `deeptutor/services/skill/hub.py:917` | 同上 | 同上 | 同上 |
| 13 | `deeptutor/services/web_source/html_extractor.py:333` | `<title[^>]*>(.*?)</title>` | 远程 HTML 大输入回扫 | 影响有限；可先截取头部窗口再匹配 |
| 14 | `deeptutor/services/web_source/html_extractor.py:347` | `\s*[|｜]\s*[^|]+$` | 探针在 n=16000 实测超线性；输入为远程页面 `<title>` | 对 title 先截断（如 500 字符）再做后缀剥离 |
| 15 | `deeptutor/services/web_source/markdown.py:7` | `^<!--\s*source:...` | 惰性类扫描，绑定大输入路径 | 输入为单行注释头，风险低；可忽略或限窗 |
| 16 | `deeptutor/services/web_source/markdown.py:22` | 同上（fullmatch） | 同上 | 同上 |
| 17 | `web/components/space/SkillsSection.tsx:73` | frontmatter `[\s\S]*?` | 前端大 markdown 渲染路径 | 同 10 |
| 18 | `web/components/space/PersonasSection.tsx:58` | 同上 | 同上 | 同上 |
| 19 | `web/lib/deep-research-report.ts:53` | `^(# [^\r\n]*?)(?=##...)` | 报告全文惰性扫描 | 匹配前截取标题区（如首个 `##` 前） |

共性建议（不改变行为的中性护栏）：
1. 对不可信/远程/模型输出类输入，进入重正则前统一做长度截断（如 64KB 窗口）。
2. 流式累积场景（`dsml_tool_calls.py` 的 `feed`）给未闭合块设上限，防止 O(n²) 累积。
3. 「无闭合时全量回扫」型模式可改为「失败即放弃」或限定搜索窗口。
4. Python `re` 无原子组/占有量词；对确有嵌套量词且输入不可信的场景，可改为手写扫描或分段处理。

## Review 桶处置（66 条）

- 63 条动态模式：其中 `re.escape(...)` 拼接的关键字匹配（`reading/vocabulary`、`mastery/choices`、`runtime/agentic/labels`、`voice/speech_text` 等约 30 条）为安全字面量形态；常量片段 join（`speech_text`、`ggb_validator`、`memory/document`）有界且无嵌套量词；`robots.py:60` 已用 `fnmatch.translate` 显式规避星号爆炸（代码注释自证）；其余为版本号/配置类小模式或测试文件，均按低危计。`services/search/source_filter.py` 两条仅计数，行为轴归 `test-search-source-filter` 卡。
- 3 条 web 测试文件里的词法恢复不完整模式（`web/tests/`，冷路径）：不影响生产路径。

## 人工复核记录（11 条，要求 ≥5）

逐条核对实际代码上下文（输入来源、执行频率、既有护栏），结论写入 `regex_risk_data.json` `manual_review` 字段：

1. `html_extractor.py:347` medium → **维持**（探针超线性；输入为远程 title，通常很小但无上限）。
2. `dsml_tool_calls.py:83` medium → **维持**，并定位到具体累积路径：未闭合信封使 `_pending_close.search` 逐 chunk 全量重扫。
3. `skill/service.py:352` medium → **维持**（建议级）。
4. `json_utils.py:25` medium → **维持**（建议级）。
5. `feishu.py:858` low → **维持**（探针线性至 n=20000，行锚定结构）。
6. `web/lib/chat-outline.ts:78` low → **维持**（node 探针线性；m 标志逐行）。
7. `robots.py:60` review → **下调 low**（fnmatch.translate 已规避）。
8. `crawler.py:92` low → **维持**（探针线性）。
9. `llm/utils.py:189` low → **维持**（惰性 + 反向引用，典型线性）。
10. `docx_converter.py:61` low → **维持**（探针线性；逐行 match）。
11. `ggb_validator.py:102` review → **下调 low**（常量命令表 join + 不相交类的括号配对组）。

## 局限

- 计时探针使用合成输入，不能穷尽真实对抗输入；结论为工程级风险评估而非穷举证明。
- Web 侧仅 2 条做了 node 实测，其余为静态结构分级；JS 引擎（irregexp）行为与 Python `re` 有差异。
- 动态模式（66 条）无法完全静态验证，已抽样核对为低危形态。
- TSX 词法器为近似实现，个别测试文件模式恢复不完整（已归入 review，不影响生产代码覆盖）。

## 复现步骤

```bash
cd <worktree>   # 分支 scan/regex-risk-20261007，基线 f07029cfc
python3 evidence/regex-risk-20261007/regex_inventory.py . evidence/regex-risk-20261007/regex_callsites.json
PROBE_BUDGET=140 python3 evidence/regex-risk-20261007/regex_risk_analyze.py . \
  evidence/regex-risk-20261007/regex_callsites.json evidence/regex-risk-20261007/regex_risk_data.json
shasum -a 256 evidence/regex-risk-20261007/*   # 校验见 SHA256SUMS
```

两脚本均只读仓库文件；计时探针在独立子进程运行且有墙钟超时，不会遗留进程。

## 产物与校验

- `regex_callsites.json` —— 1210 条调用点全量清单（path:line、op、pattern、input_src、flags）
- `regex_risk_data.json` —— 分级、签名、探针实测、输入上界、人工复核记录
- `regex_inventory.py` / `regex_risk_analyze.py` —— 复现脚本
- `SHA256SUMS` —— 以上文件校验和

## PR 草稿（不向上游提交，由人决定）

- **标题**：`docs(evidence): regex complexity & backtracking risk inventory (read-only)`
- **说明**：本分支只新增 `evidence/regex-risk-20261007/`（报告 + 数据 + 复现脚本 + 校验和），不含产品代码改动。核心结论：1210 个调用点、0 高危、19 个中危（建议加输入长度护栏与流式缓冲上限）、66 个动态模式待人工核对。
