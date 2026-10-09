# 复核：上游 #1902 的证据复用现状与差距（课前准备 / 选证 / 复用轴）

- 基线：`HKUDS/DeepTutor` `origin/main` = `6cf793bd8`（release v1.6.14，fetch 于 2026-10-09）；只读 worktree，未改任何已跟踪文件。
- 输入：上游 issue #1902 正文与完成标准；#1610（关闭于 `de64a9aa0`，补充 `30022c769`）与 #1611（`2ccd8a75f`、`2350ea2db`）的交付说明。
- 分工：本卡只覆盖「课前准备 / 选证 / 复用」轴。评估边界轴（判定、答案 key 核验、申诉/修复、ungraded 规则）归 scan-visual-practice-assessment 卡与上游 #1901；模块导读细节归 guide-mastery 卡。本文引用 `visual_practice.py` 仅限复用闸门与来源复核语义，不对评估边界下判定。
- 所有 path 均相对仓库根；行号对应该 commit。

## 一、#1610/#1611 三大基础的落地位置（判定：已有）

| 基础 | 判定 | 证据 |
| --- | --- | --- |
| 来源身份 | 已有 | `rag` 工具接受精确来源引用 `source_path` / `asset_id` / `figure` / `page` / `region` / `source_hash`：`deeptutor/tools/builtin/__init__.py:121-157`；命中即走 `retrieve_visual` 精确通道：同文件 `:174-208`。歧义引用要求选择来源/页而不是静默换图：`deeptutor/services/rag/source_visuals.py:255`（ambiguous_source）、`:316-322`（ambiguous_page、no substitute 提示）。`source_hash` 拒绝已变更的来源页引用：`builtin/__init__.py:156`；来源 changed/missing 时不投递像素：`builtin/__init__.py:280-281`。immutable asset id 供后续复检：`builtin/__init__.py:131`；文档化：`docs-for-user/SOURCE_VISUALS.md:41,67` |
| 原图投递 | 已有 | 检索命中的原图以 base64 注入模型消息：`builtin/__init__.py:256-301`；单请求上限 `MAX_MODEL_IMAGES = 2`：`deeptutor/services/rag/visual_assets.py:25`。活跃 AgentLoop 把工具返回的 model_message 挂到工具批次之后的瞬态消息（#1611 的 `2ccd8a75f`）：`deeptutor/agents/loop/agent_loop.py:729`；锚定注入不改动历史：`deeptutor/runtime/agentic/messages.py:115-138`；像素不入持久会话历史：`agent_loop.py:299-302`。纯文本模型收到显式“不能查看像素”提示：`builtin/__init__.py:197-198, 242-246` |
| 已检验材料 | 已有（轮内） | 每次请求后记录实际送达像素的哈希：`agent_loop.py:1271-1275`（`source_visual_evidence.image_hashes = image_content_hashes(kwargs["messages"])`），每轮初始化清零：`agent_loop.py:302`；哈希按轮注入 mastery 工具：`deeptutor/capabilities/mastery/loop.py:268-272`；视觉题引用的 `image_sha256` 必须出现在已检验哈希中才视为已检验：`deeptutor/learning/visual_practice.py:121-128` |

## 二、三轴现状判定

### A. 课前准备（objective preparation）

已有部分：
- 大纲期可声明目标级“准备”数据：`KnowledgePoint` 携带 `prerequisite_ids` / `topic_source_ids` / `required_visual_tasks`：`deeptutor/learning/models.py:88-94`；模块有 `objective` 一句话：`models.py:104-110`；`mastery_build` 可声明这些字段：`deeptutor/capabilities/mastery/tools.py:2794-2817`；`mastery_revise` 改写时保留：`tools.py:2711-2713`。
- 学习者画像作为常备上下文：`models.py:447-493`；每轮 `mastery_status` 快照含 `visual_requirements` 与 `learning_stages`：`tools.py:764-793`；运行时每轮做一次全新状态读取：`capabilities/mastery/loop.py:414-454`。
- 素材清单每轮重建并可按需 `read_source`：`deeptutor/learning/topic_materials.py:535-575`；章节粒度与预算：`topic_materials.py:40-51`；接线：`deeptutor/services/session/_turn_runtime_shared.py:469-501`。

缺失/部分（差距）：
- **G1（缺失）无持久化“备课记录”**：`LearningProgress`（`models.py:540-591`）没有任何字段记录某目标“已选证据、要点/前置、未解决缺口、覆盖范围、讲授/练习序列”；`KnowledgePoint` 只有名称/类型/来源引用/视觉任务（`models.py:80-94`）；`NextStep` 视图不携带准备数据（`deeptutor/learning/policy.py:180-230`）。#1902 第 1 节与 "Suggested direction" 要求的 compact reusable preparation record 不存在。
- **G4（部分）“一次检索 ≠ 全覆盖”无记录**：部分检索不会留下范围/覆盖标记，`mastery_status` 快照亦无（`tools.py:764-793`）；只能依赖会话历史自行记忆。对应 #1902 完成标准 5 前半。
- **G5（缺失）变更后的备课失效/重建**：因为无备课记录（G1），不存在“目标/来源变更使受影响准备失效”的显式状态机；来源变更目前只在投递与复检时被拦截（`builtin/__init__.py:280-281`；`visual_practice.py:228-232`）。

### B. 选证（evidence selection）

已有部分：
- 工具级选择原语齐备：精确引用、跨语言图号解析（`fig/figure/图/圖/table/表`：`source_visuals.py:24`）、稀疏标题/矢量图用整页或区域渲染（`builtin/__init__.py:143,150`）、歧义回吐选择项（`source_visuals.py:255,316-322`）、首次证据不足时给出下一步指引文案（`source_visuals.py:268,322`）。
- 视觉必要性可在大纲层声明（`required_visual_tasks`，`models.py:92-94`）；练习视觉引用限定 1–2 个精确来源、comparison 必须双原图：`visual_practice.py:42-46`；引用词与选择器逐项透传：`visual_practice.py:60-67`。
- playbook 已有“视觉题先 `rag` 检查原图再出题、保留来源身份”的指令：`deeptutor/capabilities/mastery/prompts/en/mastery_loop.yaml:91`（中文对齐 `prompts/zh/mastery_loop.yaml:88`）。

缺失/部分（差距）：
- **G3（部分）缺“按任务比例选证”的策略层**：playbook 对素材只说 "Teach from those rather than from memory"（`en/mastery_loop.yaml:123`），没有区分“普通概念讲解可用既有知识/已检材料 vs 来源特定断言必须检索”，没有 necessary/useful/decorative 分级，也没有“首次证据不足时的有界定向恢复（换更准查询/精确引用/邻页）→ 仍失败则说明局限”的编排指引。#1902 第 2 节要求的按需选择目前完全依赖模型逐轮自行裁量，只有工具原语没有策略层。
- **G6（缺失）准备耗时的 UI 状态**：web 端只有目标证据缺口展示（`web/components/space/learning/ObjectiveDetail.tsx:119-120`），没有备课进行态的简洁状态、取消/重试控件（#1902 第 3 节 UI 期望）。

### C. 复用（reuse）

已有部分：
- 轮内跨 round：最新 2 张源图经瞬态消息保留并参与预算（`runtime/agentic/messages.py:148-154`；`agent_loop.py:729`）；文本章节经 `read_source` 索引轮内可重复读取（`topic_materials.py:84-85`）。
- “缓存/元数据不得暗示像素仍在请求中”的诚实性半边成立：瞬态消息轮级重建（`agent_loop.py:299-302`）、哈希按实际请求重算（`agent_loop.py:1271-1275`）、纯文本降级显式声明（`builtin/__init__.py:197-198, 242-246`）。
- `asset_id` 支持后续按不可变 ID 复检同一图（`builtin/__init__.py:131`）；视觉题把来源身份随 `visual_context` 持久化（`models.py:139,189,276`）。

缺失/部分（差距）：
- **G2（缺失）跨轮次证据复用机制**：像素只在当轮请求内存活（`agent_loop.py:299-302`），新的一轮必须重新 `rag`（`loop.py:419` 明示“每轮全新读取、绝无会话缓存”）；没有“同一目标已检证据自动重投/免检索”的记录与通路，也没有跨轮的已检证据账本（哈希记录是请求级、不落盘复用）。#1902 第 3 节“adequate evidence reusable across explanation, follow-up, and practice for the same objective”的复用半边没有承载机制；现状等于每轮全量重取（有 `asset_id` 时也需模型记得并主动再调）。

## 三、差距条目汇总（供 up-1902 直接取用）

| # | 判定 | 差距 | 对应 #1902 | 关键证据 |
| --- | --- | --- | --- | --- |
| G1 | 缺失 | 无持久化“备课记录”（要点/已选证据/视觉需求/未解决缺口/讲授序列） | §1、Suggested direction | `models.py:540-591`、`models.py:80-94`、`policy.py:180-230` |
| G2 | 缺失 | 跨轮次证据复用机制（像素轮级失效后无自动重投/免检索账本） | §3、完成标准 1、5 | `agent_loop.py:299-302`、`messages.py:148-154`、`loop.py:419` |
| G3 | 部分 | 按任务比例的选证策略层（概念讲解 vs 来源断言；necessary/useful/decorative；有界定向恢复） | §2 | `en/mastery_loop.yaml:91,123` |
| G4 | 部分 | “一次检索 ≠ 全覆盖”无范围/覆盖标记 | §1、完成标准 5 | `tools.py:764-793`（快照无覆盖字段） |
| G5 | 缺失 | 目标/来源变更后备课失效与重建的状态机 | 完成标准 5 | `builtin/__init__.py:280-281`（仅投递侧拦截） |
| G6 | 缺失 | 备课耗时的简洁 UI 状态与取消/重试 | §3（UI 期望） | `ObjectiveDetail.tsx:119-120`（仅证据缺口展示） |

差距条目数：**6**（缺失 4，部分 2；三大基础“来源身份/原图投递/已检验材料”均判定为已有）。

## 四、Top3（建议 up-1902 优先）

1. **G1 备课记录**：在 `LearningProgress` 增加每目标的紧凑准备记录（要点、已选证据引用、视觉需求、未解决缺口、讲授/练习意图），并在 `mastery_status` 视图中回吐——这是 #1902 的核心诉求，也是 G4/G5 的落点。
2. **G2 跨轮复用**：为“同一目标已检证据”建立可复用账本（记录 asset_id/来源哈希与“本轮像素是否在场”），支持自动重投或免检索判定；保持 #1611 的诚实性边界（元数据不得暗示像素在场，`agent_loop.py:1271-1275` 机制可复用）。
3. **G3 选证策略**：在 mastery playbook/编排层补“普通概念讲解可不检索、来源特定断言必须检索、必要/有用/装饰分级、有界定向恢复后明确局限”的规则，替换当前一刀切的 "teach from materials rather than memory"（`en/mastery_loop.yaml:123`）。

## 五、复核方式

- 静态审读 + grep 定位；基线 commit `6cf793bd8`。未运行任何服务/测试（本卡为只读复核，无代码改动）。
- 与 scan-visual-practice-assessment 不重叠：本文未对判定/key 核验/申诉修复/ungraded 规则下任何结论，`visual_practice.py` 的引用仅限复用闸门（`:121-128`）与来源复核语义（`:228-232`）。
