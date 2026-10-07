# async 路径阻塞调用全仓清点（AGEN-998）

- **基线**: `origin/main` @ `f07029cfcf2c8dfccdb671cdfc343db8334f5741`（v1.6.13，2026-10-07 fetch），独立只读 worktree，未改任何产品代码
- **范围**: `deeptutor/` 全部 `async def`（AST 级，含方法、嵌套 async def、以及嵌套同步 def 的降权视图）；`deeptutor_cli/`、`scripts/` 不在本卡范围
- **方法**: `scan_async_blocking.py` 纯 AST 扫描（import 别名归一 + 构造标签跟踪 + offload 豁免 + 锁轴去重），逐条带 `path:line` 与代码摘录
- **产物**: `data.json`（180 条命中明细 + 覆盖率 + 去重数据）、`scan_async_blocking.py`（可复现脚本）、`SHA256SUMS`
- **上游对照**: 开工前 `gh pr list -R HKUDS/DeepTutor --author @me --state open` 共 30 条，无 async-blocking 相关分支；本卡为扫描证据卡，**不开 PR**

## 1. 结论（PASS）

- 扫描 **1029** 个 Python 文件（**0** 解析失败），覆盖 **2788** 个 `async def`，命中 **180** 个阻塞点（按 file:line+类别合并后），分布在 **90** 个文件。
- 分级：**高 1 / 中 87 / 低 92**；其中 **15 条**是嵌套同步 def 且确认为 `to_thread`/线程目标的"已正确卸载"命中（保留计数、降权标注）。
- **最显著的阴性结果：同步 HTTP（requests/httpx 同步 API/urlopen/http.client）在 async 函数内为 0 命中**——全仓同步 HTTP 都收敛在同步 helper 里再经 `asyncio.to_thread` 卸载（16 个文件 import requests，无一在 async 体内直调）。sqlite3 同步驱动在 async 路径同样 0 命中。
- 真正的存量风险集中在三类：**async 路由器线程上的文件 IO**（65 中危，含 `shutil.move/rmtree`、媒体字节读写）、**deepcopy 族**（13 处，量级依赖）、**线程原语 join/wait 进 async**（2 处 stop 路径）。
- 人工复核 **13** 条抽样（覆盖 7 个类别），**0 误报**；2 条量级需要运营数据确认（见 §7 标注）。

## 2. 命中分级与 Top 清单

### 2.1 高危（1 条）

| # | 位置 | 判定 |
| --- | --- | --- |
| H001 | `deeptutor/agents/math_animator/renderer.py:203` | `ManimRenderService._run_manim`（async）内 `process.wait()`：subprocess.Popen（:170 创建，代码注释明示为 Windows 兼容而弃用 asyncio 子进程）阻塞等待 Manim 渲染退出。缓解因素：两个 reader 线程先抽干 stdout/stderr 管道，`wait()` 时进程通常已在退出边缘，实际阻塞为毫秒级~秒级；但语义上仍是 loop 线程阻塞等待子进程。**建议**：改 `await asyncio.create_subprocess_exec`（配 `loop.run_in_executor` 的 `process.wait()` 兜底），或最低成本 `await asyncio.to_thread(process.wait)`。同函数 :170 `Popen` 创建为 low（fork/exec 一次性开销）。 |

### 2.2 中危 Top（按主题归组，全部 87 条见 data.json）

**A. 主 loop（uvicorn）上的文件 IO — `api/routers/*` 21 条（另 tools/ 8 条）**

| 位置 | 说明 |
| --- | --- |
| `deeptutor/api/routers/knowledge.py:3155` | async 路由内 `shutil.move(str(src), str(dest))`：移动 KB 资产文件（可能是大二进制），目录跨 rename 边界时退化为拷贝，阻塞主 loop 且期间所有请求排队 |
| `deeptutor/api/routers/reading.py:1114` | async 路由 finally 内 `shutil.rmtree(tmp_dir)`：递归删除媒体临时目录（读入管线可能 GB 级），删大目录期间主 loop 停摆 |
| `deeptutor/api/routers/co_writer.py:637`、`knowledge.py:3851,3876`、`question.py:214`、`visualizers.py:103` | async 路由内建 `open()` 同步读 JSON/文件（小文件、低频，亚毫秒~毫秒级） |
| `deeptutor/api/routers/memory.py:115,590`、`settings.py:2262,2298,2306`、`quiz_judge.py:200`、`reading.py:1341` | `read_text/read_bytes/write_text` 缓存/配置读写，小文件为主，量级随内容增长 |
| `deeptutor/tools/file_tools.py:82,126,161,181` | `ReadFileTool/WriteFileTool/EditFileTool.execute`（async）整文件读写，工具读的教材文件可达 MB 级 |

**B. deepcopy 族 — 13 条（量级依赖，需逐个确认）**

`api/routers/multi_user.py:674,680`、`api/routers/settings.py:1320,1321,1810,1811,1834`、`services/llm/provider_core/codebuddy_provider.py:293`（`deepcopy(messages)`，会话消息列表，长会话时可观）、`services/rag/pipelines/lightrag/pipeline.py:294,424,509,631`（`deepcopy(get_embedding_config())`，小 dict，4 处重复调用可提取）、`services/voice/preview.py:38`。小 dict 的 deepcopy 是微秒级可忽略；风险点在 `messages`/`catalog` 随会话与配置规模线性放大。

**C. 渠道媒体/游标文件读写 — `partners/channels/*` 14 条**

`discord.py:305,448`（20MB 附件 `write_bytes(resp.content)` 落盘在 loop 上）、`feishu.py:1267`、`matrix.py:708,770`、`mattermost.py:364,437`、`mochat.py:996,1009`（会话游标 JSON 读写，高频小 IO）、`telegram.py:501`、`wecom.py:357`、`weixin.py:776,1199`、`zulip.py:773`。渠道 loop 被 `write_bytes(read_bytes())` 卡住时，该渠道所有收发消息排队。

**D. 线程原语进 async — 2 条**

`partners/channels/msteams.py:255`（`self._server_thread.join(timeout=2)` 在 async `stop()`）、`zulip.py:180`（同型，timeout=5）：停止渠道时 loop 线程最长自锁 2~5 秒，期间该进程所有请求无响应。低频路径（stop），但属最典型的"join 进 async"反模式。

**E. 其余中危**

`agents/math_animator/renderer.py:64,83,91,110,123,212`（场景代码 `write_text/read_text` + 成品视频 `read_bytes/write_bytes`，视频文件 MB 级）、`services/rag/file_routing.py:296,303`、`services/memory/*`（5 条）、`services/web_source/crawler.py:651`、`services/voice/*`（4 条）、`services/github_source/sync.py:292,340`、`services/subagent/models.py:191`、`services/memory/consolidator/*`（2 条）、`capabilities/audio_overview/pipeline.py:455`、`capabilities/subagent/tools.py:184`（`shutil.rmtree` 工作区）、`learning/tests/test_topic_coverage.py:204`（测试代码，去重标注见 §6）。

### 2.3 低危（92 条，data.json 全量）

- `cpu_loop` 74 条：async 函数内嵌套循环/轻度序列化调用（`json.dumps/loads`、`re.findall` 等）。其中 70 条**无 await 让出点**的纯计算循环（单轮数据量小时无风险）、4 条**循环内含 await**（可让出，仅在大单轮计算时才饥饿）。
- `file_sync` 17 条 low：`stat/exists/glob/mkdir/unlink` 等廉价 syscall。
- `subprocess_sync` 1 条 low：`renderer.py:170` Popen 创建。
- 15 条 offloaded 命中（低危标注）：`reading/ingestion.py` ffmpeg 族（`to_thread(run)` 卸载 ✓）、`services/rag/pipelines/graphrag/engine.py:133`（`to_thread(_runner)`，worker 线程自有 loop，注释完备 ✓）、`partners/channels/feishu.py:598,604`（`run_ws` 为 `Thread(target=run_ws)` 目标，专用线程 ✓）、`services/session/pocketbase_store.py` 4 条循环（全部 `to_thread(_do/_search/read)` 卸载 ✓）。这些是**范本**而非问题。

## 3. 风险分级口径

| 级别 | 判定 | 数量 |
| --- | --- | --- |
| 高 | loop 线程阻塞等待无界外部进程/嵌套 loop 死锁风险 | 1 |
| 中 | loop 线程同步网络/子进程/线程 join/线程原语；或文件 IO/deepcopy/CPU 循环（无 await 让出 + 重调用或 MB 级数据面） | 87 |
| 低 | 廉价 syscall、含 await 让出点的循环、轻量序列化、已正确卸载的嵌套 def | 92 |

## 4. fan-in 影响面（按 loop 归属聚合"未卸载"命中 165 条）

| loop 归属 | 命中 | 饥饿时受影响面 |
| --- | --- | --- |
| **主 uvicorn loop**（`api/routers/*` 为主） | 40 | **最大**：所有 HTTP/WebSocket 会话、所有用户。`shutil.move/rmtree` 与 MB 级 `read_bytes` 在此执行时全站请求排队；SSE/WS 心跳超时风险 |
| 渠道收发路径（`partners/channels/*`） | 28 | 单渠道全部会话的消息收发（含 webhook 回执）；mochat 游标读写高频，卡顿即消息延迟 |
| services 后台（memory/voice/web_source/github_source/subagent 等） | 37 | 对应后台任务组（索引、巩固、语音合成），与主 loop 共线时同样全站受累；独立线程池场景仅本组任务延迟 |
| RAG 管线（`services/rag/*`） | 14 | 索引/检索请求；lightrag pipeline 若在主 loop 执行，索引期间检索全部停摆 |
| agents / capabilities / book / tools | 26 | 单次学习会话/生成任务的交互延迟 |
| tests（`learning/tests`） | 3 | 仅测试时序，交 scan-flaky-tests 轴 |

结构性结论：本仓的阻塞面**不在 HTTP 客户端**（已全部异步化或 to_thread 化），而在**文件系统与序列化**——恰好是 `to_thread` 改造成本最低的一类；主 loop 上的 40 条是修复收益最高的扇入面。

## 5. 改造建议（to_thread / 进程池）

1. **文件 IO（65+ 中危主力）**：统一走仓内既有惯例——嵌套同步 def + `await asyncio.to_thread(fn)`（范本：`services/session/pocketbase_store.py` 全文件、`reading/ingestion.py:1037`）。热点小 IO（mochat 游标）可换 aiofiles；一次性启动读可保留并注释豁免。
2. **线程原语**：`thread.join(timeout)` → `await asyncio.to_thread(t.join, timeout)`，或重构为 `asyncio.Event` + `loop.call_soon_threadsafe` 唤醒；`queue.Queue.get` → `asyncio.Queue`（仓内 `math_animator/renderer.py` 已是正确范本）。
3. **子进程**：`process.wait()` → `await asyncio.to_thread(process.wait)`（最小改动）或 `asyncio.create_subprocess_exec`（注意 renderer 注释里的 Windows SelectorEventLoop 限制，跨平台需 ProactorEventLoop 路径）。
4. **CPU 密集（重循环/大 deepcopy/hash 大对象/PDF·图像解析）**：`loop.run_in_executor(process_pool, fn)` 或 `anyio.to_process.run_sync`；`deepcopy(get_embedding_config())` 4 连发建议改为构造一次快照复用。仓内 CPU 大头（Manim 渲染、ffmpeg）已在子进程，无需进程池新增。
5. **不建议动**：15 条已卸载命中保持现状；低危 syscall 类不值得引入异步复杂度，建议仅在触发真实卡顿时按 §2 分组批量改。

## 6. 与其他扫描轴去重

- **锁轴（scan-lock-usage / AGEN-665，同一提交 f07029cfc）**：`lock.acquire` 等锁原语不进本卡命中表，单独记 `lock_axis_overlap`（本次 1 条）供交叉引用；"锁内 I/O"问题归该卡，本卡只判"是否在 loop 线程上阻塞"。
- **超时轴（scan-http-clients / AGEN-578）**：本卡 http_sync 0 命中，无重叠；若后续修复卡涉及 HTTP，超时配置以该卡为准（data.json 的 http 命中已带此标注位）。
- **测试时序轴（scan-flaky-tests）**：`deeptutor/learning/tests/` 内 3 条命中带标注，按测试代码解读，不进修复建议。
- **fire-and-forget 轴（scan-async-tasks / AGEN-453，基线 ef2d9e5c）**：正交。补充一点交叉观察：create_task 出去的协程若含本卡中危命中，会在**共享 loop 上**放大该卡"任务死亡无感知"的后果（loop 卡住 → 心跳/超时语义失真）。

## 7. 人工复核记录（13 条抽样，0 误报）

| 抽样 | 类别 | 复核结论 |
| --- | --- | --- |
| `partners/channels/feishu.py:598,604` | sleep / nested loop | 真实 API，但 `run_ws` 是 `Thread(target=run_ws)` 目标（:607），专用线程不饿 loop → 已降权标注 ✓ |
| `reading/ingestion.py:1015,1067,1090` | subprocess | ffmpeg 族，嵌套 `run` 经 `to_thread` 卸载（:1037,1118）→ 已降权标注 ✓ |
| `services/rag/pipelines/graphrag/engine.py:133` | nested loop | `to_thread(_runner)`，worker 线程自有 loop，注释明示为 #695 规避 → 合规 ✓ |
| `agents/math_animator/renderer.py:203` | subprocess.wait | 真实阻塞（缓解：管道已 EOF，实际短暂）→ 保持高危、注明缓解 ✓ |
| `partners/channels/msteams.py:255` / `zulip.py:180` | thread join | 真实：stop 路径 loop 自锁 2~5s ✓ |
| `api/routers/multi_user.py:674` | deepcopy | 真实 API；grant dict 小，量级可忽略（heuristic 标注如实）✓ |
| `services/web_source/snapshot_assets.py:70` | cpu loop | 真实：无 await 循环内 sha256 整图字节，量级随素材数×大小 ✓ |
| `agents/math_animator/renderer.py:64,83,91` | file IO | 真实：场景代码与成品视频（MB 级）同步读写 ✓ |
| `partners/channels/discord.py:305,448` | file IO | 真实：20MB 附件 open/落盘在 loop ✓ |
| `api/routers/knowledge.py:3155` | shutil.move | 真实：KB 资产移动在主 loop ✓ |
| `api/routers/reading.py:1114` | shutil.rmtree | 真实：媒体临时目录递归删在主 loop ✓ |
| `api/routers/co_writer.py:637` | open | 真实：工具调用 JSON 同步读 ✓ |
| `services/session/pocketbase_store.py:459,663,684,1059` | cpu loop | 全部 `to_thread` 卸载 → 已降权标注 ✓（范本） |

量级待运营数据确认 2 处：`codebuddy_provider.py:293`（`deepcopy(messages)` 随会话长度）、`snapshot_assets.py:70`（随素材体积）。

## 8. 方法限制

- 词法作用域扫描，无调用图：**同步 helper（内含阻塞调用）被 async 直接调用**不在命中内（本仓惯例是 to_thread 卸载，风险低但非零，可作为后续调用图扫描卡）。
- 嵌套 def 仅下探一层（sync def 内再嵌 sync def 不单独展开）。
- 泛化文件方法（44 条）按方法名匹配，接收者类型未跟踪——已用"await 过的跳过"规避自定义异步包装类误报，抽样未见误报。
- offload 识别基于 `Thread(target=)/to_thread/submit/run_in_executor` 引用；嵌套 def 若**既被卸载又被同步直调**，当前按卸载降权（静态无法区分调用点），修复卡落地时应逐个确认。

## 9. 复现

```bash
# 基线 f07029cfc（v1.6.13）；在仓库根目录：
python3 evidence/async-blocking-20261007/scan_async_blocking.py deeptutor \
  --out evidence/async-blocking-20261007/data.json
# stdout 摘要（files/parse_errors/async_defs/hits/by_risk/by_cat），明细在 data.json
# 单文件复算（如 feishu）：把根目录参数换成具体路径即可
```

## 10. PR 草稿（不开 PR，仅备案）

扫描证据分支 `scan/async-blocking-20261007`（推送到 myfork），纯 evidence/ 增量，不含产品代码改动，无需向上游开 PR。若后续按 §2A/§2D 拆修复卡，建议标题：`fix: move blocking file IO and thread joins off the event loop (routers & channels)`，正文引用本报告 §2/§4/§5。
