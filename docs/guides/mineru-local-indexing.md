# 本地 MinerU 索引子进程生命周期导读（guide-mineru-indexing-2026-10-09）

- 基线：`origin/main @ 6cf793bd8`（v1.6.14）。行号锚均为该基线下的 `path:line`，相对仓库根目录。
- 背景与用途：上游 #1903（Windows CLI 终止后索引可能挂起；其源码检视结论仅作线索）。本文以当前代码为准，供修复卡直接引用；覆盖本地 MinerU 子进程的拉起、日志消费、idle/总时长看门狗、进程树清理、缓存与发布。

## 0. 全景：一次本地解析经过谁

```mermaid
flowchart LR
    subgraph 调用方
        KB["KB 索引管线<br/>rag/service.py:84-92<br/>async with IndexingRun"]
        QG["问题生成<br/>mimic_source.py:111"]
    end
    PS["ParseService.parse<br/>service.py:104-130"]
    ENG["MinerUParser.parse<br/>engine.py:72-84"]
    BK["parse_document_to_workdir<br/>backend.py:72-104"]
    LOC["_parse_local<br/>backend.py:188-270"]
    SUB["parse_document_with_mineru_result<br/>local.py:119（Popen :224）"]
    CACHE["内容寻址缓存<br/>cache.py:48-101"]
    JR["IndexingRun 日志<br/>indexing_run.py:165"]
    KB --> PS --> ENG --> BK --> LOC --> SUB
    PS -.phase/document/check.-> JR
    SUB -.watchdog 轮询 run.check.-> JR
    PS -.lookup/reserve/manifest.-> CACHE
```

- KB 索引路径绑定 `IndexingRun`（`rag/service.py:87-92`），因此 `current_run()` 非空——**只有这条路径有看门狗**（见 §2 阶段 3）。
- 问题生成路径（`mimic_source.py:111`）与直接 CLI（`local.py:433-467`）不在 `IndexingRun` 内，无 idle/总时长/取消保护。
- 云模式在 `backend.py:96-102` 分流（`cloud.py` + `checkpoints.py`），本文不展开。

## 1. 入口表

| 入口 | 位置 | 说明 |
| --- | --- | --- |
| RAG 索引（LightRAG） | `rag/pipelines/lightrag/pipeline.py:131-145` | 经 `ParseService.parse` |
| RAG 索引（LlamaIndex） | `rag/pipelines/llamaindex/document_loader.py:138-140, 216-219` | 同上，可选 `engine=` |
| 问题生成 | `agents/question/mimic_source.py:111` | 带 `on_output` 进度回调 |
| 运行态/取消 API | `api/routers/knowledge.py:4329-4340`（run/cancel）、`:4117-4119`（重启前检查） | 读 journal、写取消标记 |
| 直连 CLI | `local.py:433-467` `main()` | `python -m` 调试用 |

## 2. 数据流：本地分支六个阶段

### 阶段 0 — 解析前 gate（子进程尚未拉起）

- 格式校验：`local.py:171-185`；支持集 `formats.py:13-27`（PDF/图片/Office），旧 `magic-pdf` 只收 PDF（`local.py:179-185`、`backend.py:214-224`），版本下限 3.4.5（`formats.py:9`）。
- CLI 定位：优先配置的 `local_cli_path`，否则 PATH 探测（`backend.py:134-158` `local_cli_probe`，无子进程开销；`backend.py:199-212` 在 `_parse_local` 里选边）。
- 就绪门（"不静默下载模型"）：`engine.py:69-70` → `readiness.py:79-118`；模型存在性检测 fail-closed（`readiness.py:45-76`），未就绪直接 `ParserError`（`service.py:209-211`）。

### 阶段 1 — 拉起

- 输出目录：调用方传入的 `output_base` 即 ParseService 的签名 workdir（`backend.py:93-94`、`service.py:213`）；每次解析在其下建一次性 attempt 目录 `.mineru-attempt-*` 并写 `state.json: running`（`local.py:203-209`）。
- 子进程：`local.py:216-233`——argv 固定 `[mineru, -p, src, -o, tmp]`（:217），`stdout=PIPE, stderr=STDOUT` 合流、`text=True` 通用换行（:224-233），env 用 `{**os.environ, **extra_env}` 合并（:232）。**未设 `start_new_session`/`process_group`/任何 Job Object**——后续所有终止都只作用于这个直接子进程。
- env 注入点：模型下载源/镜像（`models.py:60-72`）与 Windows 渲染线程串行化 `MINERU_PDF_RENDER_THREADS=1`（`models.py:75-86`），仅本地分支拼装（`backend.py:228-231`）。

### 阶段 2 — 日志消费

- 读循环：`local.py:269-284`。非空行才处理（:270-272）；**每读一行刷新活动时钟 `activity[0]`（:273）**；滚动 tail 40 行（:234）供失败摘要。
- 进度上报：`on_output` 每 0.5s 最多一次、单行截 300 字符（`local.py:27-28`、:275-280）；回调抛异常则静默停用回调、解析继续（:281-284）。
- 上游接线：`service.py:113-117` 把行写进 journal 的 `phase(activity=...)`，并转发调用方回调。

### 阶段 3 — 看门狗（仅当 `current_run()` 非空，`local.py:236-240`）

- 守护线程每 0.25s 一拍（`local.py:244`），做三类判定：
  1. `run.check()` 抛 `IndexingCancelled`（journal 换主或收到取消标记，`indexing_run.py:344-354`）→ 记 `CANCELLED`（`local.py:246-248`）；
  2. `run.check()` 抛 `OSError` → 记 `EXCEPTION`（`local.py:249-250`）；
  3. idle > 600s 或总时长 > 7200s → 记 `TIMEOUT`（常量 `local.py:28-29`，判定 :251-255）。
- 命中后终止：`terminate()` → `wait(3)` → 超时 `kill()`，**只对直接子进程**（`local.py:256-264`）。
- 取消链路：API `knowledge.py:4337-4340` → `request_cancel` 写 `.indexing-cancel.json`（`indexing_run.py:440-447`）→ 看门狗下一拍感知。
- `interrupted` 列表只在读循环**退出后**被消费（`local.py:285-293`，取 `interrupted[0]`）；循环本身不检查它。

### 阶段 4 — 收尾与产物校验

- 读循环到 EOF 后 `process.wait()` 并置 `process_finished=True`（`local.py:285-286`）。
- 失败分类：`interrupted` 优先（:288-293）→ 非零退出带 tail（:294-301）→ 输出目录为空 `NO_ARTIFACTS`（:305-313）→ `load_ir` 解出空 markdown/无 blocks 也是 `NO_ARTIFACTS`（:315-323；`load_ir` 见 `cache.py:162-189`）。
- 兜底异常 → `EXCEPTION`（`local.py:348-357`）。原因码枚举与文案映射：`local.py:44-59`、`backend.py:37-69`。

### 阶段 5 — 进程树清理（finally）与发布

- finally 顺序（`local.py:358-384`）：停看门狗并 join(4)（:359-361）→ 若子进程未确认退出，`terminate`/`wait(3)`/`kill`（**仍是直接子进程**，:362-369）→ 成功则删 attempt 目录（:370-371）→ 失败则把 `state.json` 改写为 `incomplete+reason`（:372-384）。失败时 attempt 目录连同 partial 产物**永久保留**（全库无读取方、无 GC，见 §5-6）。
- 发布（单次解析层）：备份换名 `<base>/<stem>`，改名失败回滚备份（`local.py:325-337`）；`backend.py:258-270` 返回最终 workdir。
- 发布（缓存层）：`service.py:216-230`——解析成功后 `load_ir` 校验非空（:217-221），最后一步原子写 `manifest.json` 盖章（:222-230；`cache.py:83-90`）；缓存目录布局 `parse_cache/<hash[:2]>/<source_hash>/<signature>/`（`cache.py:7-12, 48-49`）；命中与无效命中处理 `service.py:184-207`。解析抛异常时整个签名目录改名保留 `.<sig>.failed-<uuid>`（`service.py:240-242` → `cache.py:93-101`）。

## 3. 关键文件表

| 文件 | 职责 | 生命周期角色 |
| --- | --- | --- |
| `deeptutor/services/parsing/engines/mineru/local.py` | 本地 CLI 子进程全程 | 拉起/日志/看门狗/清理/发布（本文主体） |
| `.../mineru/backend.py` | 本地/云分流、CLI 探测、错误文案 | 入口编排 :72-104、:188-270 |
| `.../mineru/engine.py` | `Parser` 协议适配 + 缓存签名 | 签名 :39-67、就绪 :69-70 |
| `.../mineru/readiness.py` | 模型就绪 fail-closed 门 | 阶段 0 |
| `.../mineru/models.py` | 模型下载管理器（独立子进程） | `ModelDownloadManager` :89-211，其 `cancel` 同样只 terminate 直接子进程 :156-169 |
| `.../mineru/config.py` | 设置读取 → `MinerUConfig` | `resolve_mineru_config` :106-132 |
| `.../mineru/formats.py` | 支持格式/版本下限 | 阶段 0 校验 |
| `deeptutor/services/parsing/service.py` | 缓存感知的 ParseService | 缓存命中/盖章/失败改名 :180-242 |
| `deeptutor/services/parsing/cache.py` | 内容寻址缓存 + IR 加载 | `reserve/cleanup_failed/write_manifest/load_ir` |
| `deeptutor/knowledge/indexing_run.py` | journal、租约、取消、崩溃投影 | `IndexingRun` :165、`check` :344-354、`visible_run` :133-162、`request_cancel` :440-447 |
| `deeptutor/services/rag/service.py` | KB 任务入口，绑定 `IndexingRun` | :84-92 |
| `deeptutor/services/file_io.py` | 原子 JSON 写（journal/state/manifest 共用） | `atomic_write_json` `file_io.py:72` |

## 4. 扩展点

1. **失败原因枚举**：加 `LocalParseReason` 成员（`local.py:44-59`）需同步 `backend.py:37-69` 文案映射与 `local.py:46-49` 的对齐约定注释，否则 `backend.py:241-243` 直接 KeyError。
2. **进度回调**：`on_output`（`local.py:122, 275-284`）与 `extra_env`（`local.py:124, 232`）是子进程可观测性/环境控制的两个稳定注入口。
3. **CLI 定位策略**：`local_cli_path` 配置优先、PATH 兜底（`backend.py:134-158, 199-212`）；模型下载器同规则（`models.py:40-57`）。
4. **缓存键**：签名输入集中在 `engine.py:39-67`（模式、模型版本、语言、公式/表格/OCR 开关），改签名即自然失效旧缓存（`service.py:180-184`）。
5. **引擎无关层**：`ParseService` 的 fallback 链 `text_only→markitdown→tika`（`service.py:43-71`），MinerU 特有逻辑不应下沉到这一层。

## 5. 已知坑（对照 #1903 与当前代码事实）

1. **静默=空闲**：活动时钟只由"读到非空行"刷新（`local.py:273`），而 idle 判定只看该时钟（:251-252）——安静但存活的推理阶段会被误杀；反之刷屏卡死进程会一直续命。600/7200 为硬编码模块常量（:28-29），无设置项。
2. **超时语义不区分**：idle 与 total 命中都归并成同一个 `TIMEOUT`（:251-255 → :288-293），调用方无从分辨"无输出超时"还是"总时长到顶"。
3. **终止只打直接子进程**：两处终止（看门狗 `local.py:256-264`、finally :362-369）都对 `Popen` 句柄 `terminate/kill`，且拉起时未设进程组/Job Object（:224-233）——Windows 上 launcher/worker 树会留下孙进程。模型下载管理器的 `cancel` 是同一模式（`models.py:156-169`）。
4. **EOF 挂起面**：读循环 `local.py:269` 阻塞到管道 EOF 才返回；`interrupted` 与 deadline 都不在循环内消费。孙进程继承 stdout 句柄时：看门狗即使杀掉 launcher（已死，:258-261 变成 no-op），主线程仍卡在 :269，`wait()`（:285）与 finally（:358）都不再执行——这正是 #1903 第 2 点描述的挂起路径。
5. **看门狗覆盖不全**：仅 `IndexingRun` 上下文启动（`local.py:236-240`，绑定点 `rag/service.py:87-92`、`indexing_run.py:203, 283-284`）；问题生成（`mimic_source.py:111`）与 CLI 路径无任何超时/取消保护。
6. **attempt 目录只写不收**：`state.json` 全库仅 3 处引用且全是写（`local.py:208-209, 374-381`），`.mineru-attempt-*`（:205）无读取方、无 GC；失败改名 `.failed-*`（`cache.py:97`）同样只增不减。中断后重试是整篇重跑（`backend.py:250-252`）。
7. **本地路径没有 slice checkpoint**：`local.py:291` 的 "completed checkpoints" 文案实际指内容寻址缓存里已完成的整篇解析；分片检查点 `SliceCheckpoint` 只在云分支使用（`cloud.py:190-236`、`checkpoints.py:24-97`）。
8. **stale 默认值**：`local.py:187-190` 注释称 "project root"，实际解析结果是 `deeptutor/services`（`Path(__file__).parent×4`），默认输出会落 `deeptutor/services/reference_papers`；生产路径恒传 workdir（`backend.py:104, 234-236`），仅直连 CLI 会踩到。
9. **已有未合入修复线**：myfork 已存在 `fix/mineru-local-watchdog-tree-cleanup`（28a18ca6e，针对 #1903）与 `verify/1903-lifecycle-claims-20261009`，截至 2026-10-09 上游无对应开放 PR（`gh pr list` 核查过）。修复卡动手前先复核这两条线，避免重复实现。

## 6. 现有测试与覆盖空白

已有覆盖：

| 测试 | 覆盖点 |
| --- | --- |
| `tests/services/parsing/test_mineru_local_failures.py`（330 行） | 9 个 reason 码分类（:65-159）、detail 截断（:161-166）、失败保留 attempt 与前次输出（:168-217）、读循环中断→停子进程+保留 partial（:220-255，经 `KeyboardInterrupt` 走 finally :362-369 的 terminate 成功支）、backend 错误映射（:263-312）、bool 兼容（:314-330）。子进程全部用 `FakeProcess`（:36-57）模拟 |
| `tests/services/parsing/test_cache.py`、`test_parse_service.py` | 缓存命中、manifest 盖章、失败改名（`reserve/cleanup_failed/lookup`） |
| `tests/knowledge/test_indexing_run.py` | journal 租约、按 task 取消、崩溃投影 `visible_run`、失败脱敏 |
| `tests/tools/test_mineru_models.py` | 模型下载管理器状态机 |
| `tests/services/parsing/test_engines.py` | readiness 门（含 `mineru_readiness`） |

覆盖空白与可测分支（修复卡验收可直接对着标）：

1. **idle 超时支**（`local.py:251-252`）：无测试。测法：monkeypatch `_LOCAL_PARSE_IDLE_TIMEOUT_SECONDS`（:28）为小值 + 真子进程静默 sleep；**必须先绑定 `IndexingRun`（`_CURRENT`，`indexing_run.py:30`）或 `IndexingRun.__enter__`，否则 :240 直接跳过看门狗**。
2. **total 超时支**（`local.py:252-253`）：无测试；同上，patch `_LOCAL_PARSE_TIMEOUT_SECONDS`（:29）。
3. **取消支**（:246-248）：journal 级有测试，watchdog 级没有。测法：`request_cancel` 写标记（`indexing_run.py:440-447`）后断言 `CANCELLED` 与子进程被停。
4. **`OSError→EXCEPTION` 支**（:249-250）：无测试；fake `run.check` 抛 `OSError` 即可。
5. **kill 升级支**（:260-261 与 :367-369）：无测试；现有 fake 只有成功的 `terminate`（test_mineru_local_failures.py:237-242）。测法：`terminate` 后让 `wait(timeout)` 抛 `TimeoutExpired`。
6. **孙进程存活/树清理**：无代码亦无测试——#1903 焦点，属新能力；测法可用真实孙进程夹具（继承 stdout 后存活）断言父循环退出行为，对照 #1903 作者给出的 controlled fixture 思路。
7. **on_output 限流与断回调**（:275-284）：无直接测试；fake 多行输出 + 抛异常回调即可覆盖。
8. **interrupted 消费顺序**（:288-293，取首个原因）：无测试；同时注入 cancel+timeout 断言确定性。
