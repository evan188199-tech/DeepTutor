# Immersive Reading 代码导读

> 基线：origin/main @ `ef2d9e5c3`（v1.6.12）。所有引用为 `path:line`，相对仓库根。
> 范围：EPUB / Markdown / PDF（文件上传）为主，兼顾 URL/视频导入共用同一套数据面。

## 一、模块定位

Immersive Reading = **阅读引擎**（`deeptutor/reading/`，纯 Python、无 I/O 依赖chat/HTTP）+ **能力壳**（`deeptutor/capabilities/reading/`，把阅读工具挂上 agentic chat loop）+ **REST 面**（`deeptutor/api/routers/reading*.py`）+ **前端工作台**（`web/components/reading/`）。
核心抽象是 **locator**：文件被一次性切成编号 **unit**（1-indexed；PDF=页、EPUB=章、MD=标题段、其他=≈一屏节），之后所有读写/引用/标注都按 locator 寻址（`deeptutor/reading/__init__.py:4-8`）。模型说"第 12 页"，阅读器就能翻到第 12 页，双方无需知道文件格式。

分层（自底向上，只依赖上层列表项）：`models` → `extract`（唯一认识格式的模块）→ `search` → `store`（原子写、标注）→ `service`（组合层）→ `export`（`deeptutor/reading/__init__.py:15-24`）。

## 二、入口

| 入口 | 位置 |
| --- | --- |
| REST 挂载 `/api/reading` | `deeptutor/api/main.py:644`；扩展动作挂载 `deeptutor/api/main.py:646` |
| 上传文件 | `POST /api/reading/materials` → `upload_material` `deeptutor/api/routers/reading.py:1031`（流式写盘+限额 413） |
| URL 导入 | `POST /api/reading/library/import-urls` `deeptutor/api/routers/reading.py:537` → `ReadingIngestionService` `deeptutor/reading/ingestion.py:151` |
| 能力注册 | `deeptutor/runtime/bootstrap/builtin_capabilities.py:44` → `ImmersiveReadingCapability` `deeptutor/capabilities/reading/mode.py:42`（`cli_aliases=["reading","read"]`，`deeptutor/capabilities/reading/mode.py:51`） |
| 回合接线 | WS 回合 payload 带 `reading_material_id`：客户端 `web/lib/reading-turn-state.ts:153`；服务端解析 `deeptutor/services/session/turns/request_preparer.py:326`、规范化 `deeptutor/services/session/_turn_runtime_shared.py:603` |
| 前端路由 | 阅读库 `web/app/(workspace)/learning/reading/page.tsx:7` → 工作台 `web/components/reading/workspace/ReadingWorkspace.tsx:127` |

## 三、数据流

### 3.1 摄入（一次切分，永久寻址）

```
上传/URL → 临时文件 → extract_material() 按格式切 unit → ReadingStore.ingest 原子落盘
        → catalog 登记（content_id ↔ material_id）→ ready
```

- 分发与各格式分支：`deeptutor/reading/extract.py:131`（PDF `:145` PyMuPDF 每物理页一 unit；EPUB `:147` 按 spine 顺序 `extract_epub_spine` `deeptutor/utils/document_extractor.py:922`；MD `:156` 按标题切 `split_markdown_by_headings` `deeptutor/reading/extract.py:429`；其余一律定长 section，目标 2800 字符 `:54`、硬顶 4200 `:57`，`_extract_sections` `:359`）。
- **material_id = 原始字节内容哈希**（`deeptutor/reading/store.py:283`），同内容重传直接复用（幂等，`deeptutor/reading/store.py:291-299`）；同内容第二份拷贝走 catalog `reuse=false` 路径，字节共用、标注/进度独立（`deeptutor/api/routers/reading.py:1083-1095`）。
- EPUB 先经 `normalize_epub_archive` 修复归档（`deeptutor/reading/store.py:273-281`）；旧版导入的 EPUB 升级时若已有标注会抛 `ReadingUpgradeConflict`（`deeptutor/reading/store.py:300`）。
- URL/媒体：先建 catalog 行（queued）再异步处理到 ready/failed，API 立即返回可轮询（`deeptutor/reading/ingestion.py:5-7`）；source_kind 判定 youtube/bilibili/web `deeptutor/reading/ingestion.py:183-199`，YouTube 流程 `:295`、B 站 `:348`。
- 目录/工作区/会话归属 `ReadingCatalogStore`（`deeptutor/reading/catalog_store.py:54`），`SourceKind` 枚举 `deeptutor/reading/catalog_models.py:16`。

### 3.2 阅读回合（chat loop 就是阅读器）

```
前端选材料 → WS payload.reading_material_id → context.metadata[MATERIAL_ID_KEY]
→ ReadingCapability 激活 → 注入 playbook/facts → locate 预检 → 模型调阅读工具 → reader_action 驱动 UI
```

- **mode vs loop capability 的分工**：mode（用户在 composer 选的）只标记回合并跑 `AgenticChatPipeline`（`deeptutor/capabilities/reading/mode.py:24-60`）；真正挂工具/注入 prompt 的是 loop capability `ReadingCapability`（`deeptutor/capabilities/reading/capability.py:112`）。`is_active` 在"有材料打开"或"仅选了 mode"时都激活——后者让 prompt 明说阅读器为空，防止模型凭记忆编造页码（`deeptutor/capabilities/reading/capability.py:118-130`）。
- 服务端绑定：`augment_kwargs` 把 material/workspace id 注入工具 kwargs，模型永远不传材料 id（`deeptutor/capabilities/reading/capability.py:323-345`）；守卫在 `_ReadingToolBase`（`deeptutor/capabilities/reading/_tool_base.py:24-66`）。
- Prompt 三件套：system playbook+材料事实 `system_block`（`deeptutor/capabilities/reading/capability.py:135`）；viewport 种子 `pre_loop_seed`（`:354`，含当前页/选区/插图计数）；**locate 预检**——无 LLM、`asyncio.to_thread` 本地检索用户问题命中的 locator（`pre_loop` `:404-432`，`_locate` `:439`）。
- 工具族 `READING_TOOL_NAMES`（`deeptutor/capabilities/reading/tools.py:38`）：取证据 `material_outline` `:171` / `search_material` `:199` / `read_material` `:311`；驱动阅读器 `reader_goto` `:405` / `reader_annotate` `:491`。locator 语法 `"12"/"12-14"/"3,12,17"` 由 `parse_locators` 统一解析（`deeptutor/reading/service.py:63`），单次 read 最多 24 个 locator（`deeptutor/reading/service.py:26`）。
- **UI 副作用通道**：工具把 `reader_action` 放进 `ToolResult.metadata`，随 `tool_result` 事件转发给前端，无新流通道（`deeptutor/capabilities/reading/tools.py:29-30`；goto `:618`、annotate `:577`、switch_tab `:166`）。
- 标注不对称原则：高亮只在引文真实命中处绘制；**落库标注**必须通过引文校验，否则拒绝（`deeptutor/capabilities/reading/tools.py:17-27`）。校验器 `verify_quote`（`deeptutor/reading/service.py:155`，由 `locate_quote` `deeptutor/reading/search.py:126` 支撑）。

### 3.3 前端渲染

- `ReaderPane` 按材料类型分流：EPUB → `EpubDocumentView`（`web/components/reading/EpubDocumentView.tsx:162`）、PDF → `PdfDocumentView`（`web/components/reading/PdfDocumentView.tsx:69`；只有 PDF 有"忠实原始视图"，`RAW_VIEW_EXTENSIONS` `deeptutor/reading/extract.py:67`）、文本 unit → `TextUnitView`（`web/components/reading/TextUnitView.tsx:86`）；媒体源走 `MediaReadingStage`/YouTube/B 站播放器（`web/components/reading/workspace/`）。
- REST 侧渲染/定位配套：原文 `GET /materials/{id}/raw`（`deeptutor/api/routers/reading.py:1288`）、EPUB 渲染包 `:1294`、单 unit 文本 `:1240`、进度 `:1392-1403`、标注 `:1382/:1473`、导出 `:1498`。

## 四、关键文件表

| 文件 | 行数 | 职责 |
| --- | --- | --- |
| `deeptutor/reading/extract.py` | 579 | 文件→units，唯一格式感知层 |
| `deeptutor/reading/store.py` | 1516 | 每材料目录、原子 staging 写、标注/W3C selector、进度 |
| `deeptutor/reading/service.py` | 252 | 组合层：read/search/outline/quote 校验、locator 解析 |
| `deeptutor/reading/search.py` | 239 | locator 寻址的纯检索（`search_units` `:90`、`locate_quote` `:126`） |
| `deeptutor/reading/models.py` | 523 | 数据类与错误，无 I/O |
| `deeptutor/reading/catalog_store.py` | 1092 | 工作区/标签页/会话/材料目录（SQLite） |
| `deeptutor/reading/ingestion.py` | 1189 | URL/媒体统一摄入状态机 |
| `deeptutor/reading/extensions.py` | 198 | 扩展协议+注册表+熔断（`extensions.py:84,109,178`） |
| `deeptutor/reading/quiz.py` / `translation.py` / `vocabulary.py` | 139/133/131 | 三个内置 grounding 扩展（共享 `_grounding.py`） |
| `deeptutor/reading/export.py` | 259 | 导出 PDF/Markdown（`export_material` `:59`） |
| `deeptutor/reading/page_render.py` | 98 | 矢量页渲染缓存探测（配合 locate 种子） |
| `deeptutor/reading/refresh.py` | 185 | 旧材料批量重提取（串行有意为之，`:16-18`） |
| `deeptutor/reading/epub_bilingual.py` | 248 | EPUB 双语配对（`create_epub_pairing` `:174`） |
| `deeptutor/capabilities/reading/capability.py` | 497 | loop 集成：prompt/种子/预检/kwargs 注入 |
| `deeptutor/capabilities/reading/tools.py` | 680 | 8 个阅读工具 |
| `deeptutor/api/routers/reading.py` | 1559 | 全部 REST（51 个路由） |
| `deeptutor/api/routers/reading_extensions.py` | 414 | 扩展动作鉴权转发、120s 超时（`:34`） |
| `web/components/reading/ReaderPane.tsx` | 1343 | 阅读面板分流与视图状态 |
| `web/lib/reading-turn-state.ts` | — | 回合携带 material/revision（`:153-155`） |

## 五、扩展点

1. **新文件格式**：在 `extract_material` 加一个分支（`deeptutor/reading/extract.py:145-160`）；若浏览器能忠实渲染，同时把它加进 `RAW_VIEW_EXTENSIONS`（`:67`）。EPUB 章级切分即可作为新分支补上而不动任何消费者（设计说明 `deeptutor/reading/extract.py:27-35`）。
2. **新阅读扩展（quiz 式动作）**：实现 `ReadingExtension` 协议（`deeptutor/reading/extensions.py:84`），经 entry-point 组注册，`ReadingExtensionRegistry` 提供并发去重+超时熔断（`:130-152`）；HTTP 面自动可用（`deeptutor/api/routers/reading_extensions.py:145`）。
3. **新 reader_action**：工具在 `ToolResult.metadata` 加 `reader_action` 键（约定见 `deeptutor/capabilities/reading/tools.py:29`），前端在 `web/components/reading/ReadingActionsProvider.tsx` 消费。
4. **新媒体源**：`SourceKind` 加枚举（`deeptutor/reading/catalog_models.py:16`）+ `ingestion.py` 分类分支（`:183-199`）+ 前端播放组件。
5. **双语阅读**：`epub-pairings` REST（`deeptutor/api/routers/reading.py:1131-1155`）。

## 六、已知坑

- **locator 语义随格式变化**：同一数字在 PDF 是页、EPUB 是章、MD 是标题段。跨格式写死"页"会错（`deeptutor/reading/__init__.py:4-8`）。EPUB 重建书后 spine 变化会整体重排 locator——升级冲突保护见 `deeptutor/reading/store.py:300`。
- **EPUB 无忠实原文视图**：非 PDF 材料只能读抽取文本；TOC 锚点/位置标注是上游在修的活跃 bug（#1673，PR #1686 open）。
- **MD 少于 2 个标题时退化为平铺 section 且无 outline**（`deeptutor/reading/extract.py:446-449`，测试 `tests/reading/test_engine.py:216-226`）；短 .md 只有一个 unit，表现为"单页"——上游 #1641 报告 fresh .md 单页问题（open）。
- **同字节=同 material_id**：换文件名重传不会产生新材料；需要独立副本必须 `reuse=false`（`deeptutor/api/routers/reading.py:1083-1095`）。
- **模型不能自选材料**：id 由服务端注入（`deeptutor/capabilities/reading/capability.py:323`），新工具若绕过 `_ReadingToolBase` 守卫会丢绑定（`deeptutor/capabilities/reading/_tool_base.py:24`）。
- **选区是 untrusted 文本**：进 prompt 前转义+截断 2000 字符（`deeptutor/services/session/_turn_runtime_shared.py:599`、`deeptutor/capabilities/reading/capability.py:395-399`），扩展 payload 另限 10k（`deeptutor/api/routers/reading_extensions.py:54`）。
- **扩展超时=进程级熔断**：一次超时后该扩展在本进程内被跳过（`deeptutor/reading/extensions.py:138-142`、超时值 `deeptutor/api/routers/reading_extensions.py:35`）；改超时先想清楚这是故意的。
- **多用户访问闸**：所有模型侧读取都过 `learning_material_allowed`（`deeptutor/capabilities/reading/capability.py:366,443`），新工具/预检路径漏掉它会越权。
- **refresh 串行是有意的**（每材料锁+整目录 staging，并行只会抢磁盘，`deeptutor/reading/refresh.py:11`）。
- **immersive_watching 正在并入本模块**：上游 #1378 / draft PR #1384，改动会波及 `SourceKind` 与前端工作台。

## 七、测试与覆盖空白

**后端**（本次实跑）：`pytest tests/reading` → **402 passed, 0 failed（4.88s，origin/main @ ef2d9e5c3，用 `/Users/Shared/DeepTutor/.venv` 解释器）**。25 个测试文件 / 325 个测试函数，主力：

| 测试 | 覆盖 |
| --- | --- |
| `tests/reading/test_engine.py`（65 个） | extract/store/search/service/export 全链路（MD 标题切分 `:184`、EPUB 升级 `:441-480`、W3C selector `:597`、PDF 导出 `:960-997`） |
| `tests/reading/test_capability.py`（46）/ `test_workspace_tools.py` / `test_turn_wiring.py` / `test_mode_registration.py` | 能力激活、kwargs 绑定、WS 接线、注册 |
| `tests/reading/test_router.py`（43） | 上传限额 413 `:121`、raw Range `:508`、标注往返 `:540-709`、导出 `:725-783`、catalog 重复检查 `:825` |
| `tests/reading/test_ingestion.py`（28） | URL/媒体状态机、revision 迁移重锚 `:128` |
| 其余 20 个 | 扩展（quiz/翻译/词汇/熔断）、双语配对、页渲染、朗读、引用、grounding |

**前端**：`web/tests/` 下 reading/epub/pdf 相关 **31 个文件** = 11 个 vitest spec（`web/vitest.config.mts:19` 只收 `tests/**/*.spec.ts(x)`）+ 20 个 node 断言测试（`npm run test:node`，`web/scripts/run-node-tests.mjs`）+ Playwright 审计（`web/tests/epub-reader.audit.ts`、`web/tests/e2e/reading-{citation-material,location-history,w3c-annotations}.audit.ts`）。本次未在 worktree 内跑（无 node_modules）；命令为 `cd web && npm run test:unit` / `npm run test:node`。

**覆盖空白**（后续修复卡可优先补）：

1. `deeptutor/reading/refresh.py` 完全无测试（仅 `scripts/reading_refresh_figures.py` CLI 引用）——重提取丢标注/进度属高危路径。
2. `deeptutor/reading/export.py` 边角：非 PDF 导出、非 ASCII 书脊/书名已测（`tests/reading/test_router.py:774`），但 EPUB→Markdown 导出与配对材料导出无 case。
3. `deeptutor/reading/catalog_store.py` 仅 9 个测试（`tests/reading/test_catalog_store.py`），工作区并发写/迁移路径薄弱。
4. EPUB 章级 outline 的回归面：spine 变化后 locator 重排只有升级冲突测试（`tests/reading/test_engine.py:441-480`），无"章内容漂移后标注重锚"专项（对比 MD/revision 已有 `tests/reading/test_ingestion.py:128`）。
5. 前端 `EpubDocumentView` 的 locator↔视图同步只有 Playwright 审计（需起服务），vitest 单测缺位。

## 八、相关上游（开工前先看）

- Bug：#1641（fresh .md 单页）、#1673（EPUB TOC 锚点，PR #1686 open）
- 演进：#1378→PR #1384（watching 并入 reading）、#916（移动端双语 UX）、#1654（朗读）、#1656（quiz 星奖励）
- 本导读不改任何代码；修复卡请基于本文 locator 语义与"引擎/能力壳/REST/前端"四层边界落子。
