# Python 日志使用一致性清点（scan-logging-consistency-2026-10-07）

- 基线：`origin/main @ f07029cfcf2c8dfccdb671cdfc343db8334f5741`（release: v1.6.13）。文内 `path:line` 均为该提交下的实测行号（相对仓库根目录）。
- 性质：只读清点，未修改任何产品代码，产物只进本证据目录。
- 扫描范围：`deeptutor/`、`deeptutor_cli/`、`scripts/` 的非测试生产代码（`-g '!**/test_*'`）。
- 目标：logger 命名约定、级别与语义匹配、print 残留、关键路径日志缺上下文字段，四个轴的发现清单与修复拆卡建议。

## 0. 结论与计数

共 **18 项 / 132 处**（站点计数；结构性发现按 1 处计）：

| 类别 | 项数 | 站点数 | 概述 |
| --- | --- | --- | --- |
| A print 残留（库代码） | 6 | 38 | 被 API/agent 进程调用的函数里用 `print` 报错/报进度，绕过 logging 管道（stdout 污染、JSONL/任务流不可见） |
| B 级别与语义不匹配 | 8 | 17 | 失败/降级记 `info`、尽力而为清理记 `exception` 等，与 guide-logging §1.3 惯例不符 |
| C logger 命名 | 1 | 1 | agent 实例 logger 用字面动态名，脱离"模块路径即 logger 名"约定 |
| D 关键路径缺上下文字段 | 2 | 11 | 通道收发错误日志普遍缺 channel/连接/消息 id；`bind_log_context` 全仓仅 3 处绑定 |
| E log-and-rethrow 双重上报 | 1 | 65 | `except` 内 `error/exception` 后原样 `raise`，同一错误在 JSONL 双行+HTTP 500 重复暴露 |

级别分布实测（与 guide-logging §1.3 基本一致）：`warning` 624 / `info` 324 / `debug` 265 / `error` 235 / `exception` 134，`critical` 0。根 logger 直接调用（`logging.info(...)` 等模块级函数）在生产代码中为 0 处，该子项无问题。

## 1. 判定依据（约定出处）

1. **命名**：约定 `logging.getLogger(__name__)`（guide-logging §1.2：非测试 290/308 遵循）。字面名例外仅 6 类：`deeptutor.access`、`deeptutor.ProgressTracker`、`deeptutor.stats.*`、`uvicorn.error`、`nio`、`llama_index*`。本卡复核全部 18 处非 `__name__` 的 `getLogger` 调用，其余均为基础设施桥接（`task_log_stream.py:326`、`process_stream.py:131`、`rag/service.py:249`、`loguru_bridge.py:18`、`configure.py:44/77` 等），按名转发/装配属合法用法，不算发现。
2. **级别**：guide-logging §1.3 惯例——`debug`=尽力而为清理/断连/可选通知；`warning`=降级/回退/状态写失败；`error/exception`=任务失败不可恢复。断连、客户端主动断开不算错误。
3. **print 判据**：函数会被服务端进程（API router、agent、后台任务）调用 → 必须 logger；仅 `__main__`/`scripts/`/CLI 渲染路径到达 → print 是 UX，不算残留。
4. **上下文**：`bind_log_context`（`deeptutor/logging/context.py:29`）提供 7 个结构化字段，任务流按 `task_id` 过滤（`process_stream.py:91-93`）；未绑定处靠消息内嵌标识符补偿。

## 2. 发现清单

### A. print 残留（38 处）

| # | 位置 | 判定依据 | 建议 | 级 |
| --- | --- | --- | --- | --- |
| A1 | `deeptutor/services/parsing/engines/mineru/local.py:145,:149-154,:159,:163,:168,:175-176,:194-196,:211,:248-249,:256,:261,:290,:292,:296,:302`（24 处，均在 `parse_document_with_mineru_result`，:114-:336 内）及 `:372`（`parse_pdf_with_mineru` 内） | `deeptutor/services/parsing/engines/mineru/backend.py:232` 在服务端解析引擎里调用 `parse_document_with_mineru_result`，`deeptutor/tools/question/__init__.py:16` 引入 `parse_pdf_with_mineru`——全部 print 直接写服务进程 stdout；安装缺失/格式不支持等错误用户在 web 端不可见 | 函数内改 `logger.warning/error`（含 source_file、engine 上下文），CLI 展示留给 `main()`（:383，其 :413/:416 不动） | P1 |
| A2 | `deeptutor/agents/research/utils/citation_manager.py:174,:217,:331,:381,:530`（5 处） | `research/pipeline.py:61` 在服务端 research 流程引入 `CitationManager`；加载/保存/新增/解析失败只打 stdout，任务流与 JSONL 均无记录 | `logger.warning`（带 citation_id/文件路径），同文件 :433 的 except 站点归 guide-logging Top10 #7，不重复列 | P1 |
| A3 | `deeptutor/agents/research/data_structures.py:554` | `research/pipeline.py:55` 服务端引入；队列进度**状态写失败**仅 `print`（P4 状态写，guide 定级 warning 以上） | `logger.warning`（带 queue/文件路径）；按 guide §3 P4 收口 | P1 |
| A4 | `deeptutor/services/prompt/manager.py:121,:124` | PromptManager 为服务端共享单例（`base_agent.py:138` 调 `get_prompt_manager().load_prompts`）；prompt 文件加载失败仅 print，agent 静默用回退 prompt | `logger.warning`（带 module_name/agent_name/prompt_file） | P2 |
| A5 | `deeptutor/tools/tex_downloader.py:82,:171` | `tools/__init__.py:14-15` 导出，agent 可调用；:82 下载进度 print；:171 tar 解包时越界成员被跳过仅 print——防御性安全事件无日志可查（描述仅限现象，不展开利用方式） | :82 `logger.debug`；:171 `logger.warning`（含 member 名与目标目录）；:251-256 在 `__main__` 演示段不动 | P2 |
| A6 | `deeptutor/knowledge/manager.py:1815,:1816,:1819` | 位于库方法 `delete_knowledge_base(name, confirm=False)`（:1771 起），该方法也被 API 路径调用（`subagents.py:163` confirm=True 路径不受影响）；confirm=False 的确认 UX 用 print | 确认交互上移到 CLI 层，库方法改返回结构化结果或 `logger.warning` | P3 |

### B. 级别与语义不匹配（17 处）

| # | 位置 | 判定依据 | 建议 | 级 |
| --- | --- | --- | --- | --- |
| B1 | `deeptutor/utils/document_extractor.py:459,:487,:522,:551,:579` | 5 处"rich 解析失败→回退 raw OOXML"记 `info`；guide §1.3：回退/降级类应为 `warning` | 批量升 `warning`（保留 `%s` 参数风格） | P2 |
| B2 | `deeptutor/utils/document_extractor.py:1287,:1375` | 嵌入图片提取失败与整篇文档提取失败记 `info`；失败应 `warning` 起步 | `warning`，:1375 视调用方失败面可升 `error` | P2 |
| B3 | `deeptutor/capabilities/course_study/capability.py:501`、`deeptutor/capabilities/reading/capability.py:425` | capability **状态预检失败**记 `info`+`exc_info`；guide §1.3：状态类失败 `warning` 以上 | `warning` | P2 |
| B4 | `deeptutor/services/session/attachment_parsing.py:74` | 配置解析器失败→回退，记 `info`；降级类应 `warning` | `warning`（带 filename/parser 名） | P3 |
| B5 | `deeptutor/tools/zotero_search.py:91` | 搜索请求失败只记异常类名于 `info`，用户拿空结果无诊断线索 | `warning` 或收窄异常类型后 `debug`+计数 | P3 |
| B6 | `deeptutor/runtime/registry/scoped_registry.py:153` | 策略性拒绝（unauthorised provider tool）记 `info`；拒绝/拒绝计数应可观测 | `warning` | P3 |
| B7 | `deeptutor/api/routers/sessions.py:508,:512,:516` | 删除会话后三段尽力而为清理统一 `logger.exception`；guide §1.3：状态 detach（:508,:516）`warning` 足矣，文件清理（:512）应 `debug`；全 `exception` 级造成删除成功但日志报错级噪音 | :508/:516 `warning`、:512 `debug`；宽泛 except 本身归 broadexcept 轴（AGEN-370/944），不重复列 | P3 |
| B8 | `deeptutor/api/routers/subagents.py:165`、`deeptutor/services/rag/pipelines/lightrag/pipeline.py:363` | :165 断开失败记 `error` 且消息缺连接名（且下一行已 raise 500，属 E 类双报）；:363 中止期清理失败记 `exception`，按 P1 收尾语义 `debug` 即可（中止本身另有 error 上下文） | :165 `error` 补 `name` 字段；:363 降 `debug` | P3 |

### C. logger 命名（1 处）

| # | 位置 | 判定依据 | 建议 | 级 |
| --- | --- | --- | --- | --- |
| C1 | `deeptutor/agents/base_agent.py:132-133` | `self.logger = logging.getLogger(f"deeptutor.{logger_name}")`，名字为 `{Module}.{AgentName}` 字面拼接，不在 guide §1.2 的 6 类字面例外内；同一模块的日志被拆到按 agent 命名的 logger，破坏"模块路径即 logger 名"的级别控制与过滤前提（名字集合有界，无泄漏风险） | 改 `logging.getLogger(__name__)` + 消息/上下文带 agent_name；或把该命名模式登记进 guide §1.2 例外表 | P3 |

### D. 关键路径缺上下文字段（11 处）

| # | 位置 | 判定依据 | 建议 | 级 |
| --- | --- | --- | --- | --- |
| D1 | 通道收发错误批量：`deeptutor/partners/channels/msteams.py:300`（"MSTeams send failed"）、`weixin.py:780`（下载媒体）、`:1065`（发送失败）、`qq.py:203`（消息处理失败）、`wecom.py:348`（媒体下载失败）、`slack.py:148`、`feishu.py:2118`、`qq.py:144`、`wecom.py:371,:378`（"client not initialized" 类） | 发送/下载失败与客户端未初始化的日志均无 channel 类型、连接名、对端 id 或消息 id；多连接/多通道部署时无法定位是哪条连接。`bind_log_context` 在这些路径未绑定（见 D2） | 各站点补 `%s` 字段（connection/chat_id/message_id 至少其一）；"client not initialized" 类补 channel 名 | P2 |
| D2 | 结构性：`bind_log_context` 全仓仅 3 处绑定——`deeptutor/api/utils/task_log_stream.py:355`、`deeptutor/api/routers/question.py:276,:457` | HTTP 路由、通道收发、LLM provider 调用、解析管线均无 request/session/turn 绑定，这些路径的 `error` 日志只剩消息内嵌参数；任务流按 `task_id` 过滤（process_stream.py:91-93）的能力覆盖不到上述路径 | 拆一张"路由中间件绑定 request_id/session_id"的收口卡；通道 send 路径绑定 connection 上下文；属机制卡，非逐点修 | P2 |

### E. log-and-rethrow 双重上报（65 处）

| # | 位置（代表） | 判定依据 | 建议 | 级 |
| --- | --- | --- | --- | --- |
| E1 | 计 65 处 `except` 内 `logger.error/exception(...)` 后紧跟 `raise`（同 exc 或转 HTTPException）。代表文件：`api/routers/knowledge.py`、`api/routers/book.py`、`api/routers/settings.py`、`api/routers/partners.py`、`api/routers/subagents.py`、`api/routers/reading_extensions.py`、`services/search/providers/{jina,serper,tavily}.py`、`tools/vision/image_utils.py` | 同一异常先写 error 行再上抛，JSONL 双行、SSE 任务流与 HTTP 500 双通道重复暴露；且其中多数 `raise HTTPException(detail=str(exc))` 属 AGEN-519 blanket-500 域 | 约定"要么记日志要么上抛"：转 HTTPException 处降为 `debug`（保留内部留痕）或只 raise 由全局 handler 统一记；批量收口卡处理，明细见 SHA256SUMS 同目录后续可加清单 | P3 |

## 3. 分级汇总与拆卡建议

- **P1（3 张卡）**：A1 mineru 服务路径 print 批量改 logger；A2+A3 research 流程 print 批量（citation_manager 5 处 + data_structures.py:554 状态写）；—— 三处可并一张"库代码 print 收口 P1 批次"卡。
- **P2（5 张卡）**：A4 prompt 加载失败；A5 tex_downloader :171 安全事件留痕；B1+B2 document_extractor 级别批次（7 处一卡）；B3 状态预检 info→warning；D1 通道日志补上下文批量；D2 路由绑定 request 上下文机制卡。
- **P3（并 2 张卡）**：单点级别修正（B4-B8、C1、A6）一卡；E1 log-and-rethrow 批量约定一卡（与 AGEN-519 coded 文案方案协同）。

## 4. 去重核对

1. **guide-logging §4 已修批次索引**：本清单与索引内全部站点（knowledge.py:3988/4389/4438/4516/4522/4527、manager.py:615/2215、launcher.py:146-158/641/790/946/1256、update_worker.py:144、settings.py:521/2268、graphrag/provider.py:118、progress_tracker.py:103-105、document_images.py:556、file_library.py:204、citation_manager.py:**433**、book.py:1514、telegram.py:573-581、embedding/client.py、lightrag/engine.py、document_loader.py:459、codebuddy_provider、codex_auth/service.py:872/882、memory/snapshot/adapters.py、notebook/service.py、docx_converter.py、data_migration.py、tool_options.py:97、file_io.py、channels/manager.py 外发超时）**无交叠**。本卡涉及 citation_manager.py 时仅取 print 残留行（:174 等 5 处），:433 归 guide Top10 #7。
2. **scan-console-noise（web console 轴）**：该轴为 `web/` 的 `console.*`，与本 Python 轴无交集。
3. **broadexcept 轴（AGEN-370 / AGEN-944 漂移）**：本卡不重复列任何宽泛 except 站点；B7/B8/E1 仅对已识别站点的**日志级别与双报行为**作判定，吞错属性仍归该轴。

## 5. 边界与防误报记录（不算发现）

- `deeptutor/services/llm/__init__.py:35`、`deeptutor/tools/reason.py:16`、`deeptutor/runtime/stream_bus.py:17` 的 print 均为 docstring 示例。
- CLI 入口 UX 不算残留：`deeptutor/knowledge/manager.py:2488-2548`（`__main__` 子命令渲染）、`deeptutor/api/contracts/export.py:102,:105`（`main()` 内，:109 有 guard）、`tools/tex_chunker.py`、`tools/rag_tool.py`、`tools/paper_search_tool.py`、`tools/question/question_extractor.py`、`mineru/local.py:413,:416`（`main()`）。
- `deeptutor/reading/refresh.py:140,:165,:181`：`refresh_materials` 仅被 `scripts/reading_refresh_figures.py:38` 调用，print 为该维护 CLI 的 UX；若未来被 API 复用需转为 logger（已记为注意项）。
- `deeptutor/services/parsing/engines/docling/local_worker.py:153,:155`：隔离子进程脚本（`__main__` 协议），stderr 输出是子进程通信约定。
- `deeptutor_cli/`：入口 `main.py:29` 已接 `configure_logging()`，CLI 渲染用 print 符合 UX 约定；`scripts/` 属工具脚本，print 为惯例，不做逐行清点。

## 6. 复核命令

```bash
git rev-parse origin/main        # 期望 f07029cfcf2c8dfccdb671cdfc343db8334f5741
# print 残留（本卡 A 类来源，人工剔除 docstring/CLI 后即 §2.A）
rg -n '^\s*print\(' deeptutor --type py -g '!**/test_*'
# 非 __name__ 的 getLogger（本卡 C 类来源）
rg -n 'getLogger\(' deeptutor deeptutor_cli --type py -g '!**/test_*' | rg -v 'getLogger\(__name__\)'
# info 级失败/回退（本卡 B 类来源）
rg -n '\.info\(' deeptutor --type py -g '!**/test_*' | rg -i 'fail|error|invalid|reject|denied|refus|cannot|unable|exception|abort|corrupt|missing'
# log-and-rethrow（本卡 E 类来源，65 处）
rg -U -l '\.(error|exception)\([^\n]*\)\n(\s*)raise ' deeptutor --type py -g '!**/test_*'
# bind_log_context 覆盖（本卡 D2 依据）
rg -n 'bind_log_context' deeptutor --type py -g '!**/test_*'
shasum -a 256 -c evidence/scan-logging-consistency-20261007/SHA256SUMS
```

## 7. 验收对照

1. **每条附 path:line 与判定依据** — ✅ §2 各条均给 path:line（v1.6.13 实测）与约定出处（§1）。
2. **与 guide-logging 已修批次索引去重** — ✅ §4 逐项核对，无交叠；相邻轴均只引用不展开。
3. **不改任何代码** — ✅ 仅新增本证据目录两个文件。
