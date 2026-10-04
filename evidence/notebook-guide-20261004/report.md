# 笔记本域导读：书籍（Book）章节生成 → 知识卡片 → 导出

- 基线：`origin/main` @ `f07029cfc`（release v1.6.13），分支 `guide/notebook-20261004-v1`
- 场景依据：[HKUDS/DeepTutor#655](https://github.com/HKUDS/DeepTutor/issues/655)（"书籍生成时章节生成知识点，token 用完后每个章节都只生成了部分"）
- 本文为纯读代码导读，不改任何行为；所有引用格式为 `path:line`（相对仓库根）。

## 1. 术语映射与域总览

#655 里的用户词汇与代码实体的对应关系：

| #655 用词 | Book 域实体 | 定义位置 |
| --- | --- | --- |
| 书籍生成 | BookEngine 五阶段流水线 | `deeptutor/book/engine.py:9-20` |
| 章节 | `Chapter`（脊柱节点）→ 确认后变成 `Page` 壳 | `deeptutor/book/models.py:229`、`deeptutor/book/models.py:450` |
| 知识点 | 章级 `learning_objectives`（≤6 条）＋页内 `Block`（text/section/quiz/flash_cards 等知识卡片） | `deeptutor/book/models.py:236`、`deeptutor/book/models.py:413` |
| 生成了部分 | `PageStatus.PARTIAL`（部分块成功）/ `PageStatus.ERROR` | `deeptutor/book/models.py:42-48` |

整条链路（Stage 0→5）：

```mermaid
title=BookEngine 五阶段链路
flowchart TD
    A["Stage 1 创建+提案<br/>POST /books → create_book<br/>engine.py:467 + IdeationAgent"] --> B["Stage 2 确认提案<br/>confirm_proposal engine.py:560<br/>探索 source_explorer → 脊柱 spine_synthesizer"]
    B --> C["Stage 2.5 Overview 注入<br/>_ensure_overview_chapter engine.py:705<br/>（确定性渲染，无 LLM）"]
    C --> D["Stage 3 确认脊柱<br/>confirm_spine engine.py:894<br/>每章一个 PENDING 页壳 + 入队"]
    D --> E["Stage 3-4 后台串行编译<br/>_worker_loop engine.py:1431<br/>每页: 规划→逐块生成→逐块落盘"]
    E --> F["聚合状态<br/>compiler.py:455 READY/PARTIAL/ERROR<br/>断路器 engine.py:106 连续2次系统性失败→PAUSED"]
    F --> G["Stage 5 阅读与导出<br/>Markdown 导出 book.py:1269<br/>学习摘录→MarginNote book.py:614"]
```

## 2. 关键文件索引

| 文件 | 职责 |
| --- | --- |
| `deeptutor/book/engine.py`（2182 行） | 顶层编排：生命周期、每书运行时（队列+worker+in-flight 表）、断路器、恢复 |
| `deeptutor/book/compiler.py`（474 行） | 单页编译：规划→逐块生成（重试）→逐块落盘→页状态聚合 |
| `deeptutor/book/models.py` | 全部持久化模型与三套状态枚举 |
| `deeptutor/book/storage.py` | 磁盘布局（每书目录+每页一个 json，原子写） |
| `deeptutor/book/agents/spine_synthesizer.py` | Stage 2 章节（脊柱）生成：draft→critique→revise |
| `deeptutor/book/agents/source_explorer.py` | Stage 2 前置：多查询并行检索，产出 ExplorationReport |
| `deeptutor/book/agents/page_planner.py` | 每页块规划（SectionArchitect，LLM 优先+静态模板兜底） |
| `deeptutor/book/blocks/*.py` | 各类知识卡片生成器；`base.py:38` 失败分类 |
| `deeptutor/book/export.py` | 整书 Markdown 文本投影 |
| `deeptutor/api/routers/book.py`（1828 行） | 全部 REST/WS 端点 |
| `deeptutor/book/event_hub.py` + `streaming.py` | 每书长驻事件总线与阶段/事件名 |
| `deeptutor/book/estimate.py` | 生成成本估算依据（`/books/estimate-basis`） |
| `deeptutor/book/learning_overlay.py` | 共享书的每读者态（进度/摘录/页聊） |

磁盘布局（`deeptutor/book/storage.py:7-20`）：`data/user/workspace/book/book_{id}/` 下 `manifest.json`、`spine.json`、`inputs.json`、`progress.json`、`learning_captures.json`、`log.md`、`pages/{page_id}.json`。

## 3. 章节与知识点生成编排

### 3.1 Stage 1：创建与提案（一次性，单章不涉及）

- REST：`POST /books` → `deeptutor/api/routers/book.py:810`；语言解析 `deeptutor/book/language.py`。
- `create_book`：`deeptutor/book/engine.py:467`。捕获四源输入（`build_book_inputs`，`deeptutor/book/inputs.py`）→ `IdeationAgent` 单次 LLM 调用出 `BookProposal`（`deeptutor/book/agents/ideation_agent.py:46`，强制 JSON，`_coerce_proposal` `:85`）。
- 落盘 `Book`(status=DRAFT) + inputs + progress：`deeptutor/book/engine.py:512-538`；发 `proposal_ready` 事件 `:540`。

### 3.2 Stage 2：探索 + 脊柱（章节与知识点目标在此一次生成）

- REST：`POST /books/confirm-proposal` → `deeptutor/api/routers/book.py:841` → `confirm_proposal` `deeptutor/book/engine.py:560`。
- 子阶段 1 探索：`SourceExplorer.explore`（`deeptutor/book/agents/source_explorer.py`）多查询并行检索 KB/笔记本/聊天/题库，结果存 `exploration.json`（`deeptutor/book/storage.py:215`）供后续阶段复用，不再重复打 RAG。探索失败不阻断（降级为仅凭提案建脊柱）：`deeptutor/book/engine.py:625-648`。
- 子阶段 2 脊柱合成：`SpineSynthesizer.synthesize` `deeptutor/book/agents/spine_synthesizer.py:119`。
  - **全部章节是一次 LLM 调用整本产出**（draft `:185` → critique `:208` → revise `:233`，默认 `max_rounds=2` `:98`）。
  - 截断防护：`_call_json` 收集整流后检查 `StreamOutcome.truncated`，截断返回空串触发重试（`deeptutor/book/agents/spine_synthesizer.py:268-285`）；重试策略在 `json_with_reasoning_retry`（`deeptutor/services/llm/structured_retry.py:86`，推理模型"只想不答"时降 thinking 重问，对应 #1316）。相关上游修复：`7f6c16ef0`（截断结构化响应重试）、`5ac8e2c9d`（可达 token 预算+饿死计划重试）。
  - 物化与校验：`_materialise` `:305`；`_coerce_chapters` `:422` **逐条丢弃坏章节**（无标题/重复 `:429-433`，objectives 截到 6 条 `:439`）；全部解析失败时退化成单章占位 `:317-329`。概念图去环 `:633`、拓扑排序定章节顺序 `:689`、覆盖兜底 `:738`。
- 落盘：`spine_ready` 事件（含完整 spine）`deeptutor/book/engine.py:690-700`，状态 `SPINE_READY` `:680`。

### 3.3 Stage 2.5：Overview 章（确定性，不烧 token）

- `_ensure_overview_chapter` 幂等注入首章 `deeptutor/book/engine.py:705`；`_materialize_overview_page` 确定性构建 intro/概念图/章节索引三个 READY 块 `:753-875`，保护读者手改块 `:850-865`。

### 3.4 Stage 3：确认脊柱 → 页面壳 + 入队

- REST：`POST /books/confirm-spine`（`auto_compile` 参数）→ `deeptutor/api/routers/book.py:872` → `confirm_spine` `deeptutor/book/engine.py:894`。
- 每章建一个 `PageStatus.PENDING` 页壳并持久化：`:936-946`；编辑后重确认会把改名/改序同步回已有页 `:947-961`。
- 书转 `COMPILING`，记 `compile_started_at`，可选 `lazy_compile` 标记（读者打开哪章建哪章）：`:972-984`；`auto_compile=true` 时全部入队 `:992-993` → `_enqueue_pending_pages` `:1356-1377`（跳过 READY，去重，起 worker）。

### 3.5 Stage 3-4：单页编译 = 该章知识卡片的逐块生成

- 入口合并：`compile_page` `deeptutor/book/engine.py:1213-1266`。读者打开页、后台 worker 轮到、强制重生成三路并 发同一页时经 in-flight 表合并为一次运行（`_BookRuntime.in_flight` `:288`）；force 会等在跑的这轮结束再干净重来 `:1250-1257`；`asyncio.shield` 防调用方取消杀掉编译 `:1259-1266`。
- 编译主体：`BookCompiler.compile_page` `deeptutor/book/compiler.py:152`。
  1. 规划（若无块）：`_plan_if_needed` `:402-450`，页先置 `PLANNING` 落盘；`SectionArchitect.plan_blocks_async` `deeptutor/book/agents/page_planner.py:317`（LLM 优先，`max_tokens=1200` `:343`；失败/空回退静态模板 `:348-354`；保证至少一个 SECTION 块否则丢正文 `:395-404`）。
  2. 页置 `GENERATING` 落盘 `:189-191`。
  3. 逐块生成：默认串行（`block_concurrency=1` `:108-113`，顺序即流式顺序 `:220-227`）；**每块完成即整页落盘**（`persist_after_each_block=True` `:115`，写盘点 `:302-303`）——这是"中断只损失当前块"的关键。
  4. 块重试：`_generate_with_retry` `:320-346`（默认额外 1 次，2s 指数退避 `:121-130`；只重试分类为 retryable 的失败）。
  5. 失败分类：`deeptutor/book/blocks/base.py:38-66`（json_parse/empty_response/timeout/rate_limit/provider_error 等），其中 `rate_limit|provider_error|timeout` 视为"账号级系统性失败"（`deeptutor/book/compiler.py:50`）。
  6. 页状态聚合：`_finalize_page_status` `:455-471`：全 READY→`READY`；全失败→`ERROR`；混合→`PARTIAL`（错误数写进 `page.error`）。
  7. 成功块附加衔接段（bridge text）`:295-298`、`:350-398`。
- token/进度事件全程经每书长驻总线：阶段名 `deeptutor/book/streaming.py:20-31`，`book_event` 事件封装 `:94-118`，总线 `deeptutor/book/event_hub.py`；前端订阅走 WS `/books`（`deeptutor/api/routers/book.py:1519`）。

## 4. 部分失败时的状态（对照 #655 的核心）

三套状态机（`deeptutor/book/models.py:29-55`）：

- `BookStatus`：draft / spine_ready / compiling / **paused**（断路器或用户暂停，已生成内容完整保留）/ ready / error / archived。
- `PageStatus`：pending / planning / generating / ready / **partial** / error。
- `BlockStatus`：pending / generating / ready / error / hidden。

失败→暂停（断路器）：

- 判定"这页的失败是不是账号级"：`systemic_failure_reason` `deeptutor/book/compiler.py:70-95`（过半失败块属于系统性类别才算）。
- worker 循环 `deeptutor/book/engine.py:1431-1513`：`BookPausedError` 时把在途页复位 PENDING 退出 `:1479-1489`；普通异常记页 ERROR 并喂断路器 `:1490-1507`。
- `CONSECUTIVE_PAGE_FAILURE_LIMIT = 2` `:106`（"半成品是废墟"的动机注释 `:101-105`）；计数与触发 `:1517-1534`；`_pause_compilation` 置 `PAUSED`、写 `pause_reason/pause_kind=provider`、清队列但**不动磁盘** `:1536-1564`。
- 有任何一页产出即清零计数（"供应商还活着"）：`:1524-1526`。

恢复路径（三条，全部保留已有内容）：

| 路径 | 入口 | 行为 |
| --- | --- | --- |
| 用户续跑 | `POST /books/resume` `deeptutor/api/routers/book.py:1397` → `resume_book` `deeptutor/book/engine.py:1076` | 在途态页复位 PENDING `:1103-1107`，只重排 `_UNFINISHED_PAGE_STATUSES`（pending/planning/generating/error）`:113-120`，READY 原样保留 `:1091-1092` |
| 打开书自动续跑 | `maybe_resume_on_open` `:1132-1170`（`GET /books/{id}` 时触发 `deeptutor/api/routers/book.py:750-753` | 只救 `COMPILING` 且无活 worker 的书；**故意不自动恢复 PAUSED** `:1140-1143`，`lazy_compile` 书也不整本入队 `:1148-1151` |
| 整本重建 | `rebuild_book` `:1172-1209` | 删全部页保留脊柱，重新走 confirm_spine |

诊断面：`generation_summary` `:1740-1798`（把"排队中的尾段"与"失败"分开计数，避免健康书误报 `:1769-1781`）、`generation_overview` `:1720`（`working`/`interrupted` 区分"在编译"与"说在编译但没人干" `:1731-1735`）、`is_worker_live` `:1699`。前端横幅 `web/app/(workspace)/learning/books/components/BookPausedBanner.tsx`、侧栏每章状态 `BookSidebar.tsx:21-51`（partial 显示为 "Partial"）。

PARTIAL 页的边界语义：`PARTIAL` **不在** `_UNFINISHED_PAGE_STATUSES`（`deeptutor/book/engine.py:109-120`），resume 不会自动重排它（防止反复烧同样的失败调用）；但读者点开该页时前端会触发 `compilePage`（`web/app/(workspace)/learning/books/BooksRoute.tsx:676-691`），编译器逐块跳过已 READY 块只补失败块（`deeptutor/book/compiler.py:222-227`）。UI 侧只能逐页 force 重生成（`BooksRoute.tsx:1130`、`:1191`）。

## 5. 导出链路与格式

### 5.1 整书 Markdown 导出

- REST：`GET /books/{book_id}/export` `deeptutor/api/routers/book.py:1269-1287`，附件名 `export_filename`（`deeptutor/book/export.py:65-68`，文件名安全化）。
- 渲染：`render_book_markdown` `deeptutor/book/export.py:271-302`：H1 书名 → 来源/章数元信息 → 按 `(order, created_at)` 排序逐章 H2 + 学习目标列表 → 逐块投影。
- 每块文本投影 `render_block` `:222-268`：
  - **只有 `READY` 块导出**（`:224`）——PARTIAL/ERROR 块静默消失。
  - 各类型：section（intro/小节/要点）`:80-105`；quiz（含 `<details>` 折叠答案）`:108-130`；flash_cards（Markdown 表）`:133-144`；timeline `:147-160`；code `:163-172`；figure/interactive/animation 降级为描述+代码/视频链接，彻底无文本时输出"已省略"占位 `:175-197`；deep_dive `:200-219`。
  - 全章无可用块时输出"本章尚未生成"占位 `:297-300`。
  - 结构性标签双语（en/zh）`:30-57`。
- 格式即单个自包含 `.md`（`text/markdown; charset=utf-8`），无 PDF/EPUB 管线（文件头注释 `:1-15` 说明靠外部工具转换）。

### 5.2 学习摘录 → MarginNote（MN4）

- 摘录 CRUD：`GET/POST /books/{id}/learning-captures`、`PATCH .../{capture_id}` `deeptutor/api/routers/book.py:614-725`；按 content_hash 去重 `:512-526`。
- 状态机：`LearningCaptureStatus` `deeptutor/book/models.py:296-314`（captured→drafted→pending_confirmation→approved→delivered→imported，rejected 终态）；合法转换表 `deeptutor/api/routers/book.py:460-475`（PATCH 强制校验 `:696-704`，版本号自增 `:722`）。
- 存储：共享书走每读者 overlay `data/user/workspace/book_learning/book_{id}/learning_captures.json`（`deeptutor/book/learning_overlay.py:36-116`）。
- 边界：`delivered`/`imported` 两态与转换已定义，但 book 路由内没有直接写 MN4 的端点；MN4 导入是独立能力 `deeptutor/capabilities/marginnote4/`，前端面板把"确认的高亮导出到 MarginNote"作为产品话术（`web/app/(workspace)/learning/books/components/LearningCapturePanel.tsx:178`）。

### 5.3 生成成本估算（确认脊柱前给读者预期）

- `GET /books/estimate-basis` `deeptutor/api/routers/book.py:562` → `chapter_basis` `deeptutor/book/estimate.py:31-60`：按 SectionArchitect 模板给出每内容类型的块数/字数/秒数（Overview 章确定性渲染计为 0 成本 `:57-59`）。

## 6. #655 痛点对照：现状边界

#655："章节生成知识点时能不能一个一个章节来生成；token 用完后每个章节都只生成了部分。"

**已经解决的 部分**（当前 main）：

1. 章与章已经是"一个一个来"：每书单 worker 串行消费队列（`deeptutor/book/engine.py:1431-1476`；块也默认串行 `deeptutor/book/compiler.py:108-113`），不存在多章并发生成抢 token。
2. 半截不会扩散：块级粒度落盘（`deeptutor/book/compiler.py:302-303`），中断最多损失"当前章的当前块"；其余章要么 READY 要么还是 PENDING 整章。
3. token 用完会刹车而不是磨完剩余章：连续 2 次系统性失败即 PAUSED（`deeptutor/book/engine.py:106`、`:1529-1544`），剩余章保持 PENDING；配额恢复后 `resume` 只补缺（`:1076-1130`）。
4. 脊柱阶段截断有防护：截断流拒绝解析并重试（`deeptutor/book/agents/spine_synthesizer.py:268-295`）。

**边界仍在的地方**（#655 若复现，从这几处看）：

1. **章节+知识点目标仍是"整本一次 LLM 调用"**：`SpineSynthesizer._draft` 一次出全部章节（`deeptutor/book/agents/spine_synthesizer.py:185-206`）。截断重试仍失败时，`_coerce_chapters` 逐条丢弃坏条目（`:429-433`），最坏退化成单章占位书（`:317-329`）——用户会看到"章节数远少于预期"且无法从断点续生脊柱，只能整本重来（`rebuild_book` 只重页不重脊柱；重提案要再走 Stage 1/2）。没有"已确认章保留、只补生成缺失章"的脊柱级断点续传。
2. **PARTIAL 页默认是终态**：不进 `_UNFINISHED_PAGE_STATUSES`（`deeptutor/book/engine.py:109-120`），resume 不重排；恢复依赖读者逐页点开或逐页 force（`web/app/(workspace)/learning/books/BooksRoute.tsx:1130`），没有"一键把全部 PARTIAL/ERROR 页排回队列"的批量入口（`resume` 只收 `_UNFINISHED` 集合，`deeptutor/book/engine.py:1109`）。
3. **失败原因不直接呈现为"token 不足"**：分类器把 `rate_limit`/`timeout`/`provider_error` 归为系统性（`deeptutor/book/compiler.py:50`），`pause_reason` 只带首条原始报错（`:92-95`）；配额耗尽（429/quota）与瞬时故障对用户是同一句话，没有"额度剩余/预计需要多少"的对照（`estimate.py` 只给时间/字数估计，不含 token 预算）。
4. **并发入口仍可能"打开即生成"**：`handleSelectPage` 对非 ready/generating 的页直接触发 compile（`BooksRoute.tsx:676-691`）——有 in-flight 合并防重（`deeptutor/book/engine.py:1213-1266`），不会双跑，但意味着读者翻旧书也可能意外开始生成；唯一的全局开关是 `lazy_compile`（`deeptutor/book/engine.py:978`，由 confirm-spine 的 `auto_compile=false` 打开，`deeptutor/api/routers/book.py:238`、`:894`）。
5. **同名痛点在 Mastery 路线域也存在**：`deeptutor/learning/topic_generation.py:527-582` `generate_topic_draft` 同样是**一次 `complete()` 调用生成全部模块（章节）+ 每模块知识点列表**；截断/坏 JSON 时 `parse_json_response` 失败整稿丢弃（`:551-556`）或由 `materialize_modules`（`:308-455`）丢弃坏模块。#655 截图若来自学习路线向导，修复应落在这里而不是 Book 域。

## 7. up-655 修复卡可参考的落点

按投入产出排序：

1. **批量恢复入口（小，收益直接）**：让 `resume_book`（`deeptutor/book/engine.py:1076`）把 `PageStatus.PARTIAL` 一并纳入待重排集合，或新增 `retry_failed` 端点复用 `_enqueue_pending_pages`（`:1356`，队列本身已支持非 READY 页，worker 只跳过 READY `:1470`）。前端在 `generation_summary.retryable_pages`（`:1782-1792`）旁加一个批量按钮即可。
2. **脊柱断点续传（中）**：`SpineSynthesizer` 改为按批次/按章增量生成（先目录后逐章细化），`_materialise`（`deeptutor/book/agents/spine_synthesizer.py:305`）合并已有章（`materialize_modules` 的既有 id 保留机制 `deeptutor/learning/topic_generation.py:318-333` 是现成参照）。
3. **额度语义（小）**：`_classify_failure`（`deeptutor/book/blocks/base.py:38`）单列 `quota/insufficient` 类别；`_pause_compilation`（`deeptutor/book/engine.py:1536`）把它写进 `pause_kind`，前端 `BookPausedBanner` 区分"等额度"与"等修复"。
4. **若 #655 指学习路线域**：把 `generate_topic_draft`（`deeptutor/learning/topic_generation.py:527`）拆成"先出模块清单，再逐模块补知识点"的两段式，每模块单独落盘草稿；复用 `ExplorationReport` 式的中间持久化模式（`deeptutor/book/storage.py:215`）。
5. **导出补全（可选）**：`render_block` 对非 READY 块输出显式占位（当前直接跳过，`deeptutor/book/export.py:224`），让导出物也能暴露"哪章没生成完"，与 UI 状态对齐。

## 附：本报告验证方式

- 逐条 `path:line` 均在基线 `f07029cfc` 上核对；未运行任何服务/守护进程。
- 相关既有测试：`tests/agents/notebook/`、`deeptutor/learning/tests/`、`tests/api/test_book_*.py`（`grep -r "book" tests/api --include="test_*.py" -l`）。
