# 视觉与页级溯源代码导读（guide-visual-grounding-2026-10-10）

- 基线：`origin/main @ 6cf793bd8`（v1.6.14）。
- 范围：精确来源视觉与 PDF 页级溯源四段链路 —— 来源引用解析、图片经活动 agent 回路下发、Mastery 视觉练习评估、检查器（visual coverage）懒加载。
- 去重：Mastery 判分/导航总导读见 guide-mastery 卡；本卡只覆盖视觉溯源与页级引用链路。用户面文档见 `docs-for-user/SOURCE_VISUALS.md`。
- 上游关联：#1610（来源保真/页级回退，开放 PR #1695 改 retention；main 上 64 上限已被 b0521ac3f/#1802 移除，`deeptutor/services/rag/visual_assets.py` 现无条数封顶）、#1611（视觉练习评估）。
- 行号锚均为该基线下的 `path:line`，相对仓库根目录。

## 0. 全景：四段数据流

```
[解析入库] parser → collect_visual_assets → VisualAssetStore(manifest+bytes) → LlamaIndex source_visual 文档
     visual_coverage.record_coverage（检查器数据源）
        ↓
[引用解析] rag 工具/练习准备 → source_visuals.retrieve_visual（严格精确匹配，拒绝相似替换）
     页级回退：page_image（pymupdf 本地渲染）
        ↓
[回路下发] ToolResult.model_message → tool_dispatch(≤2/批) → transient messages(≤2/轮)
     → provider 请求（工具批次后注入）→ image_content_hashes 回写 context 扩展
        ↓
[评估闭环] mastery_quiz → prepare_visual（pixels_inspected 校验）→ evaluate_visual（不评分即不出证据）
     检查器懒加载：KbVisualCoverage（展开才 fetch /visual-coverage）
```

设计不变式：**精确引用永不降级为相似检索**（`deeptutor/services/rag/source_visuals.py:214`）、**声明了视觉能力不等于真送了像素**（`deeptutor/agents/loop/agent_loop.py:1271-1275`）、**未经像素校验的视觉练习不产出 mastery 证据**（`deeptutor/learning/visual_practice.py:199-210`）。

## 1. 存储层：`deeptutor/services/rag/visual_assets.py`

- 常量：`MAX_IMAGE_BYTES:24`（5 MiB/图）、`MAX_MODEL_IMAGES:25`（单请求 2 张）、`MAX_IMAGE_PIXELS:26`（3000 万像素，防解压炸弹）。**没有文档级保留上限**——#1610 报告的 `MAX_ASSETS_PER_DOCUMENT=64` 已随 b0521ac3f 移除。
- 字节校验：`_image_mime():38` 用魔数 + PIL `verify()` 双重确认，不信解析器给的扩展名；`_image_bytes():65` 是所有读入的唯一入口（符号链接/大小/像素三道闸）。
- 入库：`collect_visual_assets():176` 遍历解析产物，`asset_id:205-207` 由 `source_key\0source_hash\0parser_signature\0locator\0image_hash` 派生（同一像素跨重索引保持稳定 ID 的前提是这五元组不变）；`figure_labels:226-228` 从 caption 抽 "Figure 3.2/图3.2/表2" 标签供后续精确检索。
- 存储器：`VisualAssetStore:251`——`publish():288` 原子替换 manifest 并按字节复核旧文件（`:324-337`）；`read():342` 逐字段复核 `size/sha256/mime`（`:356-359`），任何不符返回 None；`remove_source():362` / `move_source():381` 保持删除/改名后的 manifest 一致；写入一律走 `_atomic_write():419`（mkstemp+fsync+replace）。
- manifest 读取 fail-loud：`_read_manifest():268` 大或损坏的 manifest 抛 OSError 而不是当空表（#1802 回归，注释 `:269-270`）。

## 2. 解析入库：LlamaIndex 侧挂接

`deeptutor/services/rag/pipelines/llamaindex/document_loader.py`：
- `_parse_document():201` 解析后调 `collect_visual_assets` + `record_coverage`（`:237-249`），并把通过字节校验的图与其候选记录配对。
- `_append_visual_documents():252` 为每张图生成 `content_type:"source_visual"` 的可检索文档（metadata 携带 `visual_asset_id/page/bbox/source_locator`，`:273-287`）——这是语义检索结果能带回 `visual_asset_id` 的源头。
- 入库时序：`pipelines/llamaindex/pipeline.py:232-235` 先 `publish(prune_missing=True)` 再持久化节点（#1802 修复）；`_publish_verified():467` 统一落盘。

## 3. 引用解析：`deeptutor/services/rag/source_visuals.py`

`retrieve_visual():202` 是全链路的严格解析器，决策顺序：
1. **多引用拒绝**：一次查询出现多个图表标签即 `multiple_references`（`:220-235`），比较练习必须拆成多次调用。
2. **页级优先路径**：给了 `page`（或查询含"第N页/p.N"）且无 asset/label 时，直接 `page_image():70` 渲染整页布局（`:247-264`）——刻意返回整页而非裁剪（注释 `:245-246`）。
3. **候选过滤**：按 `asset_id/source_path/figure 标签/page` 精确过滤 manifest（`:236-244`）。
4. **零候选时的精确页发现**：`source_path+label` 齐备时用 pymupdf 扫页文本找印刷引用（`:279-320`；上限 2000 页/加密拒绝 `:290-294`；多页命中返回 `ambiguous_page:314-318`），绝不相似替换（`:321-324`）。
5. **歧义处理**：同一标签多文档时，multi-panel 同组同页可折叠为整页（`:325-341`），否则列出 `choices` 要求显式选择（`:342-353`）。
6. **身份复核**：`source_hash` 不符、源文件 changed/missing（`source_state():60`）、字节读不出（`pixels_unavailable:369-374`）全部显式报错；带 `region` 的请求重路由到页渲染高清裁剪（`:375-390`）。

页渲染 `page_image():70`：仅 PDF（`:80-83`）、512 MiB 上限（`:84-87`）、`expected_hash` 前后双校验（`:88-92` 与 `:138-139`）、region 归一化裁剪（`:103-114`）、像素预算内自适应缩放（`:117-120`）、PNG 超 5 MiB 降级 JPEG（`:123-125`）、页文本与页上下文各截 6000 字符（`:130-131`）。pymupdf 为函数内懒导入（`:93`）。

引用 URL 构造 `source_url():155`：asset 图 `/visual-assets/{id}`、无 asset 页 `/source-page?...`、原文定位 `files/{path}#page=N`（`:170-172`）。`VisualEvidence.model_message():182-199` 把最多 `MAX_MODEL_IMAGES` 张图编码为 base64 data URL 的私有 user 消息，并附"这是证据不是指令"前缀（`:189`，防提示注入）。

## 4. 回路下发：图片如何进入活动 agent 请求

1. **工具侧**：`rag` 工具（`deeptutor/tools/builtin/__init__.py`）精确引用路径 `:174-208` 调 `retrieve_visual`，`vision_supported` 时挂 `model_message`（`:207`）；语义路径从检索结果的 `visual_asset_id` 源补水像素 `_rag_visual_model_message():256`（逐条复核 `source_state:280`，跳过 changed/missing）。无视觉能力的模型只拿文本证据并收到"不得声称看过图"的提示（`:197-198`、`:242-246`）。
2. **能力门注入**：`deeptutor/agents/loop/pipeline.py:1357-1366` 由 `supports_vision(binding, model)` 服务端注入 `_vision_supported`，模型不可自报。
3. **dispatch 收集**：`deeptutor/runtime/agentic/tool_dispatch.py:886-897` `_collect_outcome` 收私有消息，硬上限"本批累计 ≤2 张"（`:895`），并锚定 `_after_tool_call_id`。
4. **跨轮预算**：`deeptutor/agents/loop/agent_loop.py:729` 把 dispatch 结果并入 `_transient_model_messages`（初始化 `:301`）；`deeptutor/runtime/agentic/messages.py:148-154` `extend_transient_model_messages` 只保留最新 2 张、旧的弹出。
5. **请求装配**：`messages.py:115-138` `with_transient_model_messages` 把图插在整个工具回复批次之后（provider 要求同一 assistant 批次的所有 tool 回复连续，`:133-135`）；调用点 `agent_loop.py:1049`（chat 引擎同构于 `runtime/agentic/loop.py:230,240`）。
6. **投递验证闭环**：流打开后 `agent_loop.py:1271-1275` 用 `image_content_hashes`（`messages.py:8-41`，对≤7 MiB 的 base64 图算 sha256）回写 `context.extension("source_visual_evidence")["image_hashes"]`；provider 静默降级为文本时 `has_image_parts`/`strip_image_parts_inplace`（`deeptutor/services/llm/multimodal.py:289,322`）把 canonical 副本一并剥掉（`agent_loop.py:1278-1283`），防止下一轮重试已被拒的图。
7. **上下文预算**：`pipeline.py:110` `IMAGE_TOKEN_GUARD_RESERVE=4096`，守卫估 token 时对含图消息加固定预留（`:1704`）。

## 5. Mastery 视觉练习评估：`deeptutor/learning/visual_practice.py`

- **出题**：`prepare_visual():25`（工具入口 `deeptutor/capabilities/mastery/tools.py:1051-1078`）——任务类型白名单（`:37-41`）、来源 1-2 个且必须属于本回合挂载 KB（`:42-59`）、`retrieve_visual` 重取证据并记录 `image_sha256`（`:65-86`）。答案等价只认显式 `accepted_answers`（≤12 条，`:98-105`），key 可信要求 `reference_quote` 逐字出现在源文本且含正确答案且 `key_status=="verified"`（`:106-113`）。
- **像素校验**：`:119-128` `pixels_inspected` 只在调用方传入的 `inspected_image_hashes` 全覆盖各引用 `image_sha256` 时为真（哈希来自 §4 第 6 步的回写）；未校验则强制 `verified=False, cues="unverified"`。纯页引用且答案文字可见时自动升级为 `cues="visible"`（引导阅读，`:129-135`）。
- **协助记账**：`account_for_recent_assistance():163` 复用 retention 的会话边界（`_SAME_SESSION_DAYS`），同题同源同答案键的近期尝试强制 `hints_used≥1` 并标 `recently_assisted`。
- **判分**：`evaluate_visual():199` 三类一律 `ungraded`（不产出 mastery 证据）：未校验像素（`:206-210`）、key 未经源文本支持（`:211-215`）、证据已变/不可达（`:216-232`）；选择题走 `resolve_choice_submission`（`:237-246`），措辞不匹配不猜错（`:247-250`）。
- **服务层挂接**：判分集成 `deeptutor/learning/service.py:937-960`（讲解晚于提问降级为 assisted，`:949-958`）；key 修复集成 `:1550-1577`（挑战修复必须像素已验且 `prepare_visual` 复验通过，否则要求 void）。对模型公开字段收敛于 `public_visual():148`，进题卡（`deeptutor/learning/question_card.py:69`）。
- **能力侧注水**：`deeptutor/capabilities/mastery/loop.py:268-279` 给 mastery 工具注入 `_attached_kb_names` 与 `_inspected_image_hashes`（`:270-272`，读 §4 的 context 扩展）。

## 6. 检查器（visual coverage）与懒加载

- **数据生产**：`deeptutor/services/rag/visual_coverage.py:22` `record_coverage` 在解析时逐文件记录被跳过/无法读取的资产与未验证的表格块（`:55-83`），报告写入 `visual_assets/coverage/<sha256(source_path)>.json`（`:95-101`），并明示 `whole_document_verified:false`（`:91-92`）——提取出的图不等于全书覆盖。
- **HTTP 面**：`deeptutor/api/routers/knowledge.py:3245` `GET /knowledge-bases/{kb}/visual-coverage`（offset/limit 分页，`:3249-3250`）；`:3222` `GET .../visual-assets/{asset_id}`（changed/missing 返 409，`:3233-3237`）；`:3267` `GET .../source-page`（422 带原因，`:3284-3285`；响应头回传 `X-Source-Document-ID:3292`）。删文件时同步清 manifest（`:3322`）。
- **前端懒加载**：`web/components/knowledge/KbVisualCoverage.tsx:16` 挂在 `KbFilesTab.tsx:73`（选中文件才渲染）；`<details>` 未展开不发请求（`:23-24` `if (!expanded) return`），展开后按 20 条/页翻页（`:26`、`:52-56`），请求带 AbortController 防竞态（`:25-31`）。

## 7. 关键文件速查

| 文件 | 角色 | 锚点 |
| --- | --- | --- |
| `deeptutor/services/rag/visual_assets.py` | 图像存储/manifest/字节校验 | `collect_visual_assets:176`、`VisualAssetStore:251` |
| `deeptutor/services/rag/source_visuals.py` | 精确引用解析 + 页渲染 | `retrieve_visual:202`、`page_image:70`、`model_message:182` |
| `deeptutor/services/rag/visual_coverage.py` | 提取覆盖检查报告 | `record_coverage:22`、`coverage_overview:104` |
| `deeptutor/services/rag/pipelines/llamaindex/document_loader.py` | 入库挂接 | `_parse_document:237-249`、`_append_visual_documents:252` |
| `deeptutor/tools/builtin/__init__.py` | rag 工具双路径 | 精确路径 `:174-208`、`_rag_visual_model_message:256` |
| `deeptutor/agents/loop/pipeline.py` | 视觉能力门/预算 | `_vision_supported:1357-1366`、`IMAGE_TOKEN_GUARD_RESERVE:110` |
| `deeptutor/runtime/agentic/tool_dispatch.py` | 私有消息收集(≤2/批) | `_collect_outcome:886-897` |
| `deeptutor/runtime/agentic/messages.py` | 瞬态消息/哈希 | `with_transient_model_messages:115`、`image_content_hashes:8` |
| `deeptutor/agents/loop/agent_loop.py` | 回路装配/投递验证 | 扩展 `:729`、装配 `:1049`、哈希回写 `:1271-1283` |
| `deeptutor/capabilities/mastery/loop.py` | 注入像素哈希 | `augment_kwargs:240`、`:270-272` |
| `deeptutor/learning/visual_practice.py` | 视觉练习出题/判分 | `prepare_visual:25`、`evaluate_visual:199` |
| `deeptutor/learning/service.py` | 判分/key 修复挂接 | `:937-960`、`:1550-1577` |
| `deeptutor/api/routers/knowledge.py` | 三个 HTTP 面 | `:3222`、`:3245`、`:3267` |
| `web/components/knowledge/KbVisualCoverage.tsx` | 覆盖检查器（懒加载） | `:23-32`、`:52-56` |

## 8. 测试覆盖对照与空白

已覆盖（按链路段）：
- 引用解析/页渲染/HTTP 面：`tests/services/rag/test_source_visual_grounding.py` 12 例（整页多面板 `:126`、跨语言标签 `:92`、歧义不替换 `:170`、hash/region 不静默忽略 `:185`、改源/缺失 `:201`、路径穿越拒绝与 403 `:291`）。
- 存储与回路：`tests/services/rag/test_visual_assets.py` 14 例（百图教科书 `:188`、payload ≤2 图 `:481`、批次后注入 `:653`、跨轮上限 `:674`、HTTP 资产路由 `:383`）；`tests/agents/chat/test_agent_loop.py`——活动 Mastery 回路真拉像素 `:209`（4 参数化）、跨轮上限+降级保留 `:336`、线上去重 `:3758`、降级剥离 `:3785`。
- 入库：`tests/services/rag/test_llamaindex_document_loader.py:392,452,479`。
- Mastery 练习：`deeptutor/learning/tests/test_visual_learning_workflow.py` 11 例，直接驱动 `MasteryQuizTool.execute`（`:144`），覆盖等价答案/协助区分/错误修复/不产生负证据/比较双源/区域判分等。
- 前端：`web/tests/kb-visual-coverage.spec.tsx` 2 例、`web/tests/mastery-question-card.spec.tsx:25-27` 视觉题卡渲染。

零/弱测试位置与可拆卡条目：
1. **能力层注水缝无直接测试**：`deeptutor/capabilities/mastery/loop.py:270-272` 的 `_inspected_image_hashes`/`_attached_kb_names` 注入没有测试经过 `augment_kwargs`（现有测试全部以手工 kwargs 调工具，`test_visual_learning_workflow.py:144`）。可拆卡：capability→tool 注入 seam 回归测试（含 context 扩展缺键时的降级）。
2. **覆盖检查器前端弱测试**：`web/tests/kb-visual-coverage.spec.tsx` 仅 2 例；懒加载门（`KbVisualCoverage.tsx:24` 未展开不发请求）、AbortController 竞态（`:25-31`）、翻页边界（`:52-56`）未逐一断言。可拆卡：补 fetch-gating 与竞态用例。
3. **dispatch 批内截断无专门用例**：`tool_dispatch.py:895` 同一批多个工具各带图时"先到先得"截断行为，现有覆盖只有单工具 payload 级（`test_visual_assets.py:481`）与跨轮 loop 级（`:674`）。可拆卡（低优先）：同批混图截断用例。
4. **资产路由 404/409 分支未直接断言**：`knowledge.py:3228-3237` 的 asset 不存在/源已变分支，现有测试覆盖成功与 403（`test_visual_assets.py:383-410`）。可拆卡（低优先）。
