# DeepTutor `deeptutor/book` 模块导读（教材管线全景）

- 基线：`origin/main` @ `f07029cfc`（release: v1.6.13），分支 `guide/book-20261004`
- 范围：`deeptutor/book/**`（25 个产品文件，约 10.7k 行）+ `tests/book`（26 个测试文件 + `__init__.py`）+ 外部调用点
- 阅读对象：需要改 Book Engine / 排查生成失败 / 新增 block 类型的工程师

---

## 1. 一句话架构

Book Engine 是与 `ChatOrchestrator` 平行的独立运行时（`deeptutor/book/engine.py:5`），把用户输入（意图、聊天、笔记本、知识库、题库）编译成"活书"：**提案 → 脊柱 → 页壳 → 逐块生成**，每本书一条长生命周期事件流，后台队列逐页编译、失败熔断、可暂停续跑。

```
inputs.py ─→ IdeationAgent ─→ BookProposal        (Stage 1, 用户确认)
                                │ confirm_proposal
                                ├─→ SourceExplorer ─→ ExplorationReport   (Stage 2 预备)
                                ├─→ SpineSynthesizer ─→ Spine + ConceptGraph (Stage 2, 用户确认)
                                │ confirm_spine
                                ├─→ 注入 Overview 章 + 页壳                (Stage 3)
                                └─→ 后台队列 ─→ BookCompiler
                                        ├─ SectionArchitect (规划 block 序列)
                                        └─ BlockGenerator×N (逐块生成)     (Stage 4)
                                                  ↓
                        event_hub 每书一条 StreamBus ─→ WS /books 推送
                                                  ↓
              progress.py / kb_health.py / export.py / context.py (Stage 5+ 消费)
```

---

## 2. 模块地图

| 文件 | 行数 | 职责 | 关键锚 |
|---|---|---|---|
| `deeptutor/book/engine.py` | 2182 | 总编排器：生命周期、后台队列、熔断、块级 CRUD | `BookEngine` engine.py:317 |
| `deeptutor/book/compiler.py` | 474 | 单页编译管线：规划→逐块生成→状态聚合 | `BookCompiler` compiler.py:133 |
| `deeptutor/book/models.py` | 580 | 全部 Pydantic 持久化模型与枚举 | `Block` models.py:413 |
| `deeptutor/book/storage.py` | 395 | 磁盘布局 + 原子写 + id 防穿越 | `BookStorage` storage.py:98 |
| `deeptutor/book/event_hub.py` | 78 | 每书一条长生命周期事件总线 | `get_book_bus` event_hub.py:45 |
| `deeptutor/book/streaming.py` | 134 | BookStream 封装 + 阶段名常量 + book_event 协议 | streaming.py:21-30 |
| `deeptutor/book/inputs.py` | 402 | 四源输入融合成 IdeationContext | `build_book_inputs` inputs.py:312 |
| `deeptutor/book/context.py` | 432 | 书页 → 聊天上下文序列化（@book 引用） | `build_book_context` context.py:91 |
| `deeptutor/book/estimate.py` | 62 | 每章成本基数（blocks/words/seconds） | `chapter_basis` estimate.py:30 |
| `deeptutor/book/export.py` | 305 | 整书 Markdown 导出 | `render_book_markdown` export.py:271 |
| `deeptutor/book/kb_health.py` | 506 | KB 指纹 + 漂移检测 + log.md 健康扫描 | `detect_kb_drift` kb_health.py:177 |
| `deeptutor/book/progress.py` | 151 | 阅读进度/答题/薄弱章统计 | `record_attempt` progress.py:70 |
| `deeptutor/book/language.py` | 102 | 书籍语言解析（显式/文字系统） | `resolve_book_language` language.py:81 |
| `deeptutor/book/overview_copy.py` | 104 | Overview 章多语言文案 | `overview_copy` overview_copy.py:80 |
| `deeptutor/book/learning_overlay.py` | 134 | 多用户共享书的 overlay 持久化 | `BookLearningOverlay` learning_overlay.py:36 |
| `deeptutor/book/errors.py` | 6 | `BookPausedError` | errors.py:4 |
| `deeptutor/book/blocks/base.py` | 246 | 生成器基类、注册表、失败分类 | `BlockGenerator` blocks/base.py:130 |
| `deeptutor/book/blocks/section.py` | 369 | 长文 SECTION 两遍生成（outline→fill） | `SectionGenerator` blocks/section.py:70 |
| `deeptutor/book/blocks/_llm_writer.py` | 203 | 块生成共用 LLM 封装（llm_text/llm_json） | blocks/_llm_writer.py:31 |
| `deeptutor/book/blocks/_rag_helpers.py` | 142 | 可选 RAG 检索（缓存优先，live 兜底） | `optional_rag_lookup` blocks/_rag_helpers.py:47 |
| `deeptutor/book/blocks/_prompts.py` | — | YAML 提示词加载（`prompts/{en,zh}/`） | blocks/_prompts.py:17 |
| `deeptutor/book/agents/ideation_agent.py` | 111 | Stage 1 提案 agent | agents/ideation_agent.py:21 |
| `deeptutor/book/agents/source_explorer.py` | 760 | Stage 2 预备：多查询并行源扫描 | `explore` agents/source_explorer.py:187 |
| `deeptutor/book/agents/spine_synthesizer.py` | 816 | Stage 2：draft→critique→revise 脊柱合成 | agents/spine_synthesizer.py:83 |
| `deeptutor/book/agents/spine_agent.py` | 189 | 旧版单发脊柱 agent（保留兼容） | agents/spine_agent.py:27 |
| `deeptutor/book/agents/page_planner.py` | 427 | SectionArchitect 规划器 + 静态模板 | agents/page_planner.py:290 |

其余块生成器（`blocks/text|callout|quiz|figure|code|timeline|flash_cards|interactive|animation|deep_dive|concept_graph|user_note.py`）各 100-135 行，模式一致：继承 `BlockGenerator`，`_generate` 返回 `(payload, anchors, metadata)`。

---

## 3. 关键入口

- **API 路由**：`deeptutor/api/routers/book.py`（1828 行）。REST 全量端点 + `@ws_router.websocket("/books")` routers/book.py:1519。单例注入 routers/book.py:50。
- **引擎单例**：`get_book_engine()` engine.py:2173 —— 按 `PathService.workspace_root` 分键缓存（多用户各自一个引擎实例），内部再按 workspace 缓存 `get_book_storage()` storage.py:388。
- **对外门面**：`deeptutor/book/__init__.py` 用 `__getattr__` 懒导出模型与引擎（`book/__init__.py:30`），避免导入即拉起整个 LLM 栈。
- **外部消费点**（chat / 学习侧）：
  - 聊天回合执行器解析 `book_references`：`deeptutor/services/session/turns/executor.py:241,293`（调 `build_book_context`）
  - 会话源清单：`deeptutor/services/session/source_inventory.py:824`
  - 学习主题材料（按章装载）：`deeptutor/learning/topic_materials.py:101,108`
  - 课程状态联动：`deeptutor/services/courses_state.py:54`
  - 多用户访问/overlay：`deeptutor/multi_user/book_access.py:8-10`

引擎公共 API（`BookEngine`）一览：`create_book` engine.py:467 / `confirm_proposal` engine.py:560 / `confirm_spine` engine.py:894 / `compile_page` engine.py:1213 / `pause_book` engine.py:1030 / `resume_book` engine.py:1076 / `maybe_resume_on_open` engine.py:1132 / `rebuild_book` engine.py:1172 / `delete_book` engine.py:397 / 块级 `regenerate_block` engine.py:1596、`insert_block` engine.py:1800、`update_block` engine.py:1870、`delete_block` engine.py:1916、`move_block` engine.py:1931、`change_block_type` engine.py:1951 / `create_deep_dive_subpage` engine.py:1986 / `supplement_for_weakness` engine.py:2108 / 诊断 `generation_summary` engine.py:1740、`is_worker_live` engine.py:1699、`kb_drift_report` engine.py:1671。

---

## 4. 生命周期主链路（engine → compiler → blocks）

### Stage 1 提案（create_book, engine.py:467）

1. `resolve_book_language`（language.py:81）定语言；
2. `build_book_inputs`（inputs.py:312）把意图/选材/聊天选段/笔记本/KB/题库 快照为 `BookInputs`（models.py:176）并渲染 `IdeationContext`（inputs.py:37，`render()` inputs.py:50 拼 6 节提示块）；
3. `IdeationAgent.process`（ideation_agent.py:46）一次 JSON LLM 调用 → `BookProposal`；`_coerce_proposal`（ideation_agent.py:85）把章数夹到 [2,8]、标题 120 字符；
4. 落盘 DRAFT 书 + 基线 KB 指纹（engine.py:530，防首次健康检查误报"新增"）+ `proposal_ready` 事件。

装饰器：`@workspace_writer`（活动标记）+ `@_with_book_sources`（engine.py:299，进入 `learning_source_access` 上下文，让 KB 读权限按书校验）。

### Stage 2 脊柱（confirm_proposal, engine.py:560）

两个子阶段，各自嵌套 `bstream.stage(...)`：

- **exploration**（engine.py:591）：`SourceExplorer.explore`（见 §8.2）产出 `ExplorationReport`（models.py:386）并持久化 `exploration.json`（storage.py:218）；失败不阻塞——书 metadata 记 `exploration_failed/error`，脊柱仅凭提案生成（engine.py:625-648），并发 `exploration_failed` 事件。`_source_quality_summary`（engine.py:171）把覆盖情况写进 `metadata.source_quality` 供管理视图。
- **synthesis**（engine.py:670）：`SpineSynthesizer.synthesize`（见 §8.3）产出 `Spine`（含 `ConceptGraph`），书转 `SPINE_READY`，发 `spine_ready`。每轮 draft/critique 通过 `on_round` 回调发 `spine_round` 摘要事件（engine.py:653-668）。

### Stage 2.5/3 确认脊柱（confirm_spine, engine.py:894）

1. `_prune_concept_graph`（engine.py:143）：删除章节后同步剪掉悬空概念节点/边（概念图建后不重建，删除章节必须确定性修剪）；
2. `_ensure_overview_chapter`（engine.py:705）：幂等注入 Overview 章到 order 0——以**身份**（`content_type == OVERVIEW` 或 `__pydantic_extra__["auto_overview"]`，engine.py:250）而非位置判重，重复时去重并重新编号；
3. 为每章建 `Page` 壳（`PENDING`），已有页同步 order/title/content_type（engine.py:947-961，否则重排章节在阅读端不可见）；
4. `_materialize_overview_page`（engine.py:753）：Overview 页**确定性**构建三个块（intro 文本 + `CONCEPT_GRAPH` mermaid 块 + 章节索引），零 LLM；读者手改块（`edited_by_user`）与笔记在整体替换时保留（engine.py:855-872）；发 `overview_ready`；
5. 书转 `COMPILING`，`metadata.compile_started_at` 记本轮起点（engine.py:983，阅读端时钟以它为准、可重载）；`lazy_compile`（auto_compile=False）时不排队，章随打开而编译；
6. `_enqueue_pending_pages`（engine.py:1356）入队未完成页并 `_ensure_worker`（engine.py:1409）启动后台 worker。

### Stage 4 后台编译与单页编译

- **worker 循环** `_worker_loop_active`（engine.py:1431）：先 `set_scoped_llm_config(None)`（engine.py:1445，后台任务继承入队请求的 scoped 模型配置会把全书钉死在某次请求的模型上——必须清除）；队列空转 2s 后 runtime 退休并调度内存回收（engine.py:1448-1459）；每项经 `compile_page` 合并入口（不走编译器直连，engine.py:1475）。
- **合并入口** `compile_page`（engine.py:1213）：`in_flight[page_id]` 表是"该页是否在编"唯一事实源；普通请求 join 在跑任务，`force` 等在跑的结束后再起干净一遍（engine.py:1235-1257）；`asyncio.shield` 保护：某个 awaiter 断连（WS 关闭）不会取消其他人依赖的编译（engine.py:1259-1266）。真正要停只有 `_halt_compilation`/`delete_book` 直接 cancel。
- **单页编译** `_compile_page_now`（engine.py:1280）：PAUSED 校验（`BookPausedError`）；READY 且非 force 直接返回；**Overview 页走确定性重建而非 LLM 编译器**（engine.py:1304-1310）；force 时 `_reset_page_for_force_compile`（engine.py:435）重置生成产物但保留 `USER_NOTE` 与 `edited_by_user` 块；随后委托 `BookCompiler.compile_page`。
- **BookCompiler.compile_page**（compiler.py:152）：
  1. `page_compile_started` 事件；懒加载 `exploration.json`（后台 worker 无请求级传参，compiler.py:173-177）；
  2. `_plan_if_needed`（compiler.py:402）：无 blocks 才规划——页转 `PLANNING`，读 `book.metadata.block_types` 白名单（compiler.py:424-426，经 `_parse_allowed_block_types` compiler.py:53 容错解析），`SectionArchitect.plan_blocks_async` 产出 block 壳，发 `page_planning`/`page_planned`；
  3. 页转 `GENERATING`；`BlockContext` 工厂注入 language/KB/rag_enabled/exploration（compiler.py:193-202）；`block_concurrency`（默认 1，串行保流式顺序；>1 时按规划序推导 prev 指针后 gather，compiler.py:220-236）；
  4. 每个 block：`_generate_block`（compiler.py:265）发 `block_started` → 查注册表拿生成器 → `_generate_with_retry`（compiler.py:320：仅当失败 metadata 标 `retryable` 才退避重试一次，2s 起指数翻倍）→ READY 则 `attach_bridge_text`（compiler.py:350：metadata 的 `transition_in` 提示生成衔接段写入 `payload.bridge_text`）→ 每块落盘（`persist_after_each_block`，崩溃只丢当前块）→ 发 `block_ready`/`block_error`；
  5. `_finalize_page_status`（compiler.py:455）：全 READY→READY；全错→ERROR；部分→PARTIAL；发 `page_compiled`。
- **收尾**：每页结束 `_maybe_finalize_book`（engine.py:1566）：所有页脱离未完成态（`_UNFINISHED_PAGE_STATUSES` = PENDING/PLANNING/GENERATING/ERROR，engine.py:113；**PARTIAL 刻意不在内**——重排只会重花模型钱而不改变结果，回到完成的路径是 force 重建）→ 书 READY + `book_ready` 事件。

### 熔断 / 暂停 / 恢复

- **熔断**：worker 每页经 `_record_page_outcome`（engine.py:1517）喂 breaker：`systemic_failure_reason`（compiler.py:70）判定"系统性失败"——错误块过半属于 `rate_limit/provider_error/timeout`（`SYSTEMIC_FAILURE_KINDS` compiler.py:50）；连续 2 次（`CONSECUTIVE_PAGE_FAILURE_LIMIT` engine.py:106）触发 `_pause_compilation`（engine.py:1536）：书 PAUSED（`pause_kind="provider"`）、halt、`compilation_paused` 事件。设计动机（engine.py:101-105）：未生成的页是资产，半生成的页是垃圾。
- **用户暂停** `pause_book`（engine.py:1030）：先写 manifest 再取消在跑任务（进程被杀也不会被下次启动的 auto-resume 复活）；在途页重置 PENDING。
- **恢复** `resume_book`（engine.py:1076）：把 PLANNING/GENERATING 挂起页重置 PENDING 后重排未完成页；`maybe_resume_on_open`（engine.py:1132）在读者打开书时自动续跑——但**不**动 PAUSED（原因未清除）、不动 lazy_compile、判活性用 worker/in_flight 而非队列深度（engine.py:1153-1162，防"有队列无工人"的假活）。
- **重建** `rebuild_book`（engine.py:1172）：保提案/脊柱，删全部页重走 confirm_spine。

---

## 5. blocks 类型与校验

### 类型清单（`BlockType` models.py:59）

- Phase 1：`TEXT` / `CALLOUT` / `QUIZ` / `USER_NOTE`
- Phase 2 视觉族：`FIGURE`(svg/chartjs/mermaid) / `INTERACTIVE`(html) / `ANIMATION`(video) / `CODE` / `TIMELINE` / `FLASH_CARDS`
- Phase 3：`DEEP_DIVE`
- v2：`SECTION`（多子节长文）/ `CONCEPT_GRAPH`（Overview 图）
- Guided Learning 预留：`DIAGNOSTIC` / `PRETEST` / `RETRIEVAL_PRACTICE` / `ERROR_DIAGNOSIS` / `MODULE_TEST` / `PROGRESS_DASHBOARD`（models.py:78-83，无注册生成器）

状态机：`BlockStatus`（PENDING→GENERATING→READY/ERROR，外加 HIDDEN，models.py:51）；页级 `PageStatus`（models.py:42，含 PARTIAL）；书级 `BookStatus`（models.py:29，含 PAUSED）。

### 注册表与生成器契约

- `get_block_registry()`（blocks/base.py:197）惰性建全局注册表，13 个生成器在 `_build_default_registry`（blocks/base.py:204）注册；生成器无状态、按 `block_type` 查找。
- `BlockGenerator.generate`（blocks/base.py:135）是唯一公共入口：置 GENERATING → 调子类 `_generate` 返回 `(payload, anchors, metadata)` → 成功置 READY 并清掉历史 failure 标记；`GenerationFailure`/其他异常统一置 ERROR 并写 `metadata.failure = {kind, message, retryable, source}`（blocks/base.py:69）。**生成器不抛异常给编译器**，失败是数据不是控制流。
- 失败分类 `_classify_failure`（blocks/base.py:38）：子串匹配但**顺序有讲究**——provider 的 `invalid_request_error` 必须先于 prompt_leak 判（否则 DeepSeek 回放 reasoning_content 的报错会被永久判为不可重试）；`"prompt"` 子串被刻意移除（会误中 `prompt_tokens`）。可重试类：json_parse/empty_response/timeout/rate_limit/provider_error/generator_error；不可重试类：prompt_leak。
- `BlockContext`（blocks/base.py:89）：携带 book/chapter/page/block + language + KB + `rag_enabled` + `exploration`；`relevant_chunks()`（blocks/base.py:108）用关键词重叠加权在缓存的 exploration 块里做免 LLM 检索。

### 参数与校验链

- 规划侧收敛：LLM 规划只接受 `PLANNABLE_BLOCK_TYPES`（page_planner.py:229）10 类；未知类型/被 allowed 过滤的项逐条丢弃（page_planner.py:357-372）；`_build_block`（page_planner.py:166）是**所有计划（模板或 LLM）唯一漏斗**：弹 `transition_in` 进 metadata、注入章标题/摘要/目标/锚、按 `depth_scale` 缩放 `target_words`（下限 120，page_planner.py:178-180）。
- 覆盖保证：LLM 计划若没有任何 SECTION 强制在头部补一个（page_planner.py:395-404），防止整章散文静默丢失。
- 用户白名单：`book.metadata.block_types` 经路由 `_normalize_block_types`/`_persist_requested_block_types`（routers/book.py:380,395）持久化，规划期过滤，SECTION 永远放行。
- 深度缩放：`BookDepth`（brief 0.5 / standard 1.0 / deep 1.6，models.py:100）；`_coerce_depth`（engine.py:263）容错 API 传参。
- 字数预算：SECTION 子节 token 上限随 target_words 缩放（`_subsection_token_budget` blocks/section.py:37，CJK 宽松比 3.0，上限 8000）。

### 块级编辑语义

- 可就地编辑仅限散文块：`_EDITABLE_BLOCK_TYPES` = TEXT/USER_NOTE/CALLOUT（engine.py:128）——结构化 payload（quiz 题、figure 源）用文本框编辑只会破坏结构，走 regenerate。
- `update_block`（engine.py:1870）打 `edited_by_user` 标记；`_body_key`（engine.py:131）处理 TEXT 块 `body`/`content` 历史不一致（生成器写 body、Overview 确定性块写 content）。
- Overview 页整体重建时的用户内容保留：engine.py:855-872。

---

## 6. event_hub 事件面

### 所有权模型（event_hub.py:1-29）

书的工件是书不是请求：`confirm_spine` 返回后编译还要跑几分钟，请求级 bus 在路由 finally 里关闭会让 `StreamBus.emit()` 静默 no-op。所以：生产者只 `get_book_bus(book_id)` 拿/建总线（event_hub.py:45，无 await、无竞态）；消费者（WS）自由订阅离开；**总线只在删书时关闭一次**（`close_book_bus` event_hub:63，engine.delete_book engine.py:407）。重连恢复靠 `StreamBus(max_history=400, assign_seq=True)`（`BOOK_EVENT_HISTORY_LIMIT` event_hub.py:40）回放尾部 + seq 续传。REST 与 WS 发布到同一条总线：REST 编译的书 WS 照样能看到。

### 阶段与事件协议

- 阶段名常量（streaming.py:21-30）：`ideation / exploration / synthesis / critique / overview / spine / page_plan / compilation / block / interaction`。
- `BookStream`（streaming.py:33）封装 stage/progress/content/result/error，`source` 固定 `"book_engine"`（streaming.py:17）。
- 领域事件统一走 `book_event(kind, data, stage)`（streaming.py:94）：以 `StreamEventType.PROGRESS` 发出，`content=kind`、`metadata={kind, **data}`，前端按 `metadata.kind` 分派。

事件清单（发射点）：

| kind | 发射点 | stage |
|---|---|---|
| `proposal_ready` | engine.py:540 | ideation |
| `exploration_ready` / `exploration_failed` | engine.py:614 / 644 | exploration |
| `spine_round`（draft/critique/revise 摘要） | engine.py:666 | synthesis/critique |
| `spine_ready` | engine.py:690 | spine |
| `overview_ready` | engine.py:879 | overview |
| `compilation_paused`（熔断或手动） | engine.py:1560 / 1069 | compilation |
| `book_ready` | engine.py:1587 | compilation |
| `page_compile_started` / `page_compiled` | compiler.py:165 / 248 | compilation |
| `page_planning` / `page_planned` | compiler.py:417 / 442 | page_plan |
| `block_started` / `block_ready` / `block_error` | compiler.py:277 / 305 | block |

### 消费端

- WS `/books`（routers/book.py:1519）：订阅指定书（可带 `after_seq` 续传，转发器 routers/book.py:1491-1508），REST 动作产生的总线事件同样推给 WS 观察者。
- 前端时间线消费 `spine_round`（章数/问题数/verdict 摘要，不推全量 payload，engine.py:655）。

---

## 7. estimate 预算

- `chapter_basis(depth)`（estimate.py:30）：**直接从 SectionArchitect 的 `_TEMPLATES_V2`（page_planner.py:73）推导**每 content_type 的 `{blocks, words, seconds}`——数字与实际生成同源，不会漂移；prose 块 45s、支撑块 15s（estimate.py:24-25）；Overview 章确定性渲染，如实报告 0 words / 0 seconds（estimate.py:58）。
- 暴露为 REST `GET /books/estimate-basis?depth=`（routers/book.py:562-573）。返回按 content_type 的基数而非总额——脊柱编辑器增删/改型章节时前端本地即可保持估算鲜活，无需每敲一次键回一趟服务端。
- 深度通过 `depth_scale`（models.py:107）作用到 `target_words`，brief=0.5×、deep=1.6×。

---

## 8. agents 子步编排

### 8.1 IdeationAgent（Stage 1，ideation_agent.py:21）

单次 JSON LLM（`json_with_reasoning_retry`，期望键 `title`——标题是提案无法重建的唯一字段，用它区分"只有思考没有答案"，ideation_agent.py:76）；语言指令在 system prompt 追加（`language_directive`）。产出夹取：章数 [2,8]、目标≤6 条等（ideation_agent.py:85-100）。

### 8.2 SourceExplorer（Stage 2 预备，source_explorer.py:148）

五步流水（`explore` source_explorer.py:187）：

1. **查询设计**（`_design_queries` :253）：LLM 出 4-8 条多样查询；**刻意不加语言指令**（:259-264）——查询匹配文档而非给人看，钉死书的语言会在源是别种语言时饿死检索；失败落 `_DEFAULT_QUERIES`（:112）。
2. **KB 分流**（`partition_knowledge_bases` :351）：不可检索 KB（Obsidian vault、MN4 库、connected subagent——无本地索引）显式列为"未扫"写进 notes，而非看起来像"无相关内容"；其余（含 linked/lightrag_server/ima）正常扫。
3. **并行检索**（`_retrieve_kb_chunks` :382）：PageIndex KB 走 `read_pageindex_with_agent` 证据简报（:524）；传统 KB 走 `rag_search`，**查询主序**配对（KB 主序裁剪会饿死队尾 KB，:494）、上限 `MAX_RETRIEVAL_CALLS=48`（:55）、信号量 `RETRIEVAL_CONCURRENCY=6` 防 ~100 并发provider 洪峰（:54,510）；RAG 有答无源时合成为 `synthesised` 块（:474-488）。
4. **非 KB 源**（`_collect_non_kb_chunks` :581）：选材文本、笔记本记录（≤24）、聊天快照（近 24 条、≥20 字符）。
5. **综合**（`_summarise` :671）：LLM 蒸馏 summary + candidate_concepts + notes。输入切片用 `_balanced_slice`（:58）**按源内排序再轮转**——不同引擎的 score 不可比，全局排序会让一个 KB 的数字挤掉所有其他源。

报告去重裁剪到 96 块（:665），持久化 `exploration.json`，后续所有阶段（脊柱/规划/块生成）复用而不重打 RAG（models.py:386-394 的设计说明）。

### 8.3 SpineSynthesizer（Stage 2，spine_synthesizer.py:83）

- 多轮 **draft → critique → revise**（`synthesize` :119，默认 2 轮）；critique 返回 `verdict=ok` 或无 issues 则提前停；LLM 失败返回上一个有效草稿/最小兜底，流水线永不阻塞。
- `_materialise`（:305）确定性别后处理：
  1. `_remove_cycles`（:633）：DFS 找环，删 rationale 最短的 `depends_on` 边（置信度代理），安全阀 20 次；
  2. `_topological_sort`（:689）：按 `covers` 映射 + 概念依赖对章做 Kahn 拓扑序，并列时保原始顺序（作者意图），成环则整体放弃保序；
  3. `_ensure_full_coverage`（:738）：无章覆盖的概念按 Jaccard 相似度挂到最相关章；
  4. `_build_chapter_map`（:528）：把概念图**折叠成章级思维导图**（节点=章，边来自概念依赖提升 + 显式 prerequisites 标题匹配），多根时加虚拟书名根——Overview 页渲染的就是这张图。
- 收敛器全部防御式：标题去重截断、`content_type` 非法回 THEORY、LLM 声称 OVERVIEW 被拒绝（引擎保留该类型，:463-465）、`covers` 只认真实存在的概念 id。
- 旧 `SpineAgent`（spine_agent.py:27）是单发版本，仅为兼容保留，引擎已不调用。

### 8.4 SectionArchitect（Stage 3，page_planner.py:290）

两层：LLM 层（`plan_blocks_async` :317，`llm_json` 带思考降档重试，#1316）尽力而为；静态层（`plan_blocks` :306，`_TEMPLATES_V2` 按 ContentType 的 5 套模板）永远可用作兜底。模板里 SECTION 承载章级散文（带 target_words），支撑块带 `transition_in` 由编译器生成衔接段。`PagePlanner`（:415）是 llm_enabled=False 的兼容别名。

---

## 9. 数据流转与存储布局

### 磁盘布局（storage.py:7-20）

```
data/user/workspace/book/book_{book_id}/
├── manifest.json     # Book 元数据（状态、KB 指纹、stale 页）
├── spine.json        # Spine + ConceptGraph
├── exploration.json  # SourceExplorer 报告（块生成复用）
├── inputs.json       # 创建时的 BookInputs 不可变快照
├── progress.json     # 阅读进度/答题
├── learning_captures.json
├── log.md            # 追加式操作日志（append_log storage.py:367）
├── pages/{page_id}.json
└── assets/
```

### 可靠性要点

- 全部写经 `_atomic_write_json`（storage.py:54）→ `atomic_write_text`，每块生成后即落盘（compiler.py:302）。
- **同步存储 + 单进程事件循环 = 串行化**是读改写助手（如 `upsert_learning_capture` storage.py:286）安全的根基；注释明确警告：一旦挪去线程池或多 worker 必须先加真锁（storage.py:100-112）。
- id 防穿越：`_safe_book_id`/`_safe_page_id`（storage.py:62,75）对请求体 id 白名单校验 `[A-Za-z0-9_-]`，`../bk_1` 之类直接拒绝而非静默清洗（否则会别名到真实书目录）。
- 引擎/存储/总线三个单例都按 workspace_root 分键（engine.py:2170-2179 / storage.py:385-392 / event_hub.py:42），多用户互不串。

### 进度与学习捕获

- `Progress`（models.py:497）记录访问页/书签/答题；`record_attempt`（progress.py:70）写 `QuizAttempt`（`is_correct=None` 表示"看过答案未判分"，不折算成错，models.py:490-492），重算分数与薄弱章（progress.py:49,54）。
- `LearningCapture`（models.py:317）是阅读端划选批注，状态机 CAPTURED→…→IMPORTED/REJECTED（models.py:296-314），服务于 MarginNote 4 回写审阅流。

---

## 10. 与知识库 / 导出的衔接

### RAG（生成期）

- 块级检索统一走 `optional_rag_lookup`（blocks/_rag_helpers.py:47）：先 `ctx.exlevant_chunks`（缓存 exploration，免费确定），空了才对 `ctx.primary_kb` 打一次 live `rag_search`；失败静默——RAG 对所有生成器都是增强不是依赖。SECTION 生成即此模式（blocks/section.py:86-89）。
- 引擎入口的 KB 权限由 `@_with_book_sources`（engine.py:299）包住（`learning_source_access`）。

### KB 漂移（生成后）

- `kb_health.py` 无副作用：`fingerprint_kb_documents`（:111）按 KB `raw/` 逐文件 sha256，`digest_documents`（:80）按路径序折叠成单指纹（改路径=漂移，因为答的是"这库变没变"）；`FINGERPRINT_SCHEME`（:70）升级时 `detect_kb_drift`（:177）重新基线而不是误标全 stale。
- 基线采集时机：创建书时（engine.py:526-532）+ 首个 READY 页后懒刷新（engine.py:1341-1349）；`refresh_book_fingerprints`（:326）手动重基线，`mark_drift_on_book`（:377）算 drift 并把引用了变更文件的页写进 `Book.stale_page_ids`（靠 `kb_document_fingerprints` 逐文档哈希精确定位，models.py:540-547）。REST：`GET /books/{id}/health`（routers/book.py:1290）、`POST /books/{id}/refresh-fingerprints`（:1316）。`scan_log_health`（:453）扫 log.md 统计复发性失败。

### 聊天/学习侧引用（消费期）

- `context.build_book_context`（context.py:91）：`@book` 引用与阅读侧栏共用；按块类型投影成紧凑文本（`_payload_for_type` context.py:214 的 12 类分支），三级字符预算（总 32k / 页 12k / 块 4k，context.py:21-23），剥 `<think>` 标签（context.py:25），HIDDEN 块、空块、`code/html/svg/artifact` 键被排除（:381）；丢失的书/页只进 warnings 不报错。调用点：turns/executor.py:293、source_inventory.py:824、learning/topic_materials.py:108（按章粒度装载，标题材料预算与聊天页预算对齐）。

### Markdown 导出

- `export.py`：每类块有文本投影（`render_block` export.py:222）；纯视觉块（视频/交互）降级为"描述+指针"而非静默丢弃（`_render_visual` export.py:175）；结构标签双语（`_LABELS` export.py:30——中文书不能导出英文脚手架）；`GET /books/{id}/export` 下载（routers/book.py:1269-1284，文件名 `export_filename` export.py:65）。

---

## 11. 常见排查点

| 症状 | 根因与入口 |
|---|---|
| 书卡在 COMPILING 但没进度 | 区分"在编"与"被遗弃"只看 runtime 表：`is_worker_live`（engine.py:1699）是唯一诚实答案，manifest 状态跨进程存活会撒谎。进程重启后靠 `maybe_resume_on_open`（engine.py:1132）在读者打开时自愈 |
| 书自动 PAUSED | 熔断触发：连续 2 页系统性失败（engine.py:106,1536），`metadata.pause_reason` 带 `kind: message`；`pause_kind="provider"` vs `"user"`。补 quota 后 `POST /books/resume` |
| 页是 PARTIAL，重开不补 | 设计如此：PARTIAL 不在 `_UNFINISHED_PAGE_STATUSES`（engine.py:109-112），重回完成只能 force 重建单页 |
| 页永远 PLANNING/GENERATING | 以前崩溃会钉死；现 `_mark_page_error`（engine.py:1387）+ resume 前重置（engine.py:1102-1107）双保险。仍异常先查 `log.md` 的 `compile_error` |
| WS 看不到后台事件 | 事件只发到 `get_book_bus` 的书级总线；请求级 `StreamBus()` 只在 create_book 显式传入时使用（engine.py:484）。重连要带 `after_seq`，历史回放上限 400 |
| 某章全是错误块 | 看 `block.metadata.failure.kind`（分类 blocks/base.py:38）与 `generation_summary.failure_categories`（engine.py:1740）；`missing_dependency` 类（动画族常见）装可选依赖即可，重试无用 |
| 整本输出语言错 | 语言解析 `resolve_book_language`（language.py:81）；所有 LLM 出口统一追加语言指令：agents 用 `language_directive`，块生成在 `llm_text` 单点（blocks/_llm_writer.py:50-51）；检索查询**不加**（source_explorer.py:259）是有意为之 |
| 重生成把我的笔记删了 | 不会：`_reset_page_for_force_compile` 保留 USER_NOTE 与 `edited_by_user`（engine.py:435-458）；但 `regenerate_block` 单块重生成会清该块的 edited 标记（机器内容重新覆盖，engine.py:1652-1655） |
| 删章后概念图还有旧节点 | 应已被 `_prune_concept_graph`（engine.py:143）剪掉；若复现查 confirm_spine 入口是否绕过（edited_spine 直接传入也走该函数，engine.py:920） |
| KB 变更后书不提示过期 | 检查 `kb_fingerprints` 是否为空（空则首 READY 页后才建基线，engine.py:1341）；`GET /books/{id}/health` 现算漂移 |
| 书 id 带特殊字符 404/400 | `BookStorage` 的 id 白名单直接 ValueError（storage.py:62-79），路由层转 404/400 |
| 后台编译用了错误的模型 | worker 启动时清 scoped 配置（engine.py:1443-1445）；若复现，检查是否有绕过 `_worker_loop` 的直接 create_task |

---

## 12. 测试地图（tests/book，26 文件）

| 测试文件 | 覆盖 |
|---|---|
| `test_compile_scheduling.py` | 队列/worker/合并/熔断（§4 Stage 4） |
| `test_worker_context.py` | worker 上下文隔离（scoped LLM 清除） |
| `test_runtime_reclaim.py` | runtime 退休 + 内存回收 |
| `test_engine_controls.py` | pause/resume/rebuild/force/编辑语义 |
| `test_engine_language.py` | 语言决策 |
| `test_block_type_controls.py` | allowed block types 白名单 |
| `test_code_block_validation.py` | CODE 块校验 |
| `test_visual_block_prompts.py` | 视觉族提示词 |
| `test_quiz_extraction.py` | QUIZ 提取 |
| `test_llm_writer.py` | llm_text/llm_json 解析与重试 |
| `test_reasoning_output_cap.py` | 截断/思考预算（#1316 系列） |
| `test_concept_graph.py` | 章级思维导图/剪枝 |
| `test_overview_chapter.py` / `test_overview_copy.py` | Overview 注入与文案 |
| `test_source_exploration_budget.py` | 检索并发/上限/均衡切片 |
| `test_source_partitioning.py` | KB 可达性分流 |
| `test_spine_synthesizer_llm_call.py` | draft/critique/revise LLM 契约 |
| `test_context.py` | 聊天上下文序列化 |
| `test_event_hub.py` | 总线生命周期/回放 |
| `test_export.py` | Markdown 导出 |
| `test_kb_health_drift.py` | 指纹/漂移 |
| `test_learning_capture_storage.py` | 捕获存储 |
| `test_progress.py` | 进度/答题 |
| `test_editing.py` | 块编辑 |
| `test_reader_content_isolation.py` | 读者内容隔离（多用户） |
| `test_cross_module_call_contracts.py` | 与外部模块的调用契约 |
| `test_language.py` | 语言探测 |

跑法（储备卡模板）：`timeout 900 python -m pytest -q -p no:cacheprovider tests/book`。

---

## 13. 建议阅读顺序

1. `models.py`（词汇表）→ 2. `engine.py` 头注释 + `confirm_spine` + `compile_page`（骨架）→ 3. `compiler.py`（管线）→ 4. `blocks/base.py` + `blocks/section.py`（生成器范式）→ 5. `event_hub.py` + `streaming.py`（可观测性）→ 6. `agents/source_explorer.py` + `agents/spine_synthesizer.py`（最重的两个 agent）→ 7. 按需：`kb_health.py` / `context.py` / `export.py` / `storage.py`。
