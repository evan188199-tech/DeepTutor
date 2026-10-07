# RFC #397「下一代 Memory 架构」对照现行实现评审

| 项 | 值 |
| --- | --- |
| 评审对象 | 上游 issue [HKUDS/DeepTutor#397](https://github.com/HKUDS/DeepTutor/issues/397)（含 3 条评论，2026-04-26 创建，OPEN，无关联 PR） |
| 代码基线 | `origin/main` @ `f07029cfc`（release: v1.6.13，2026-10-04） |
| 评审范围 | `deeptutor/services/memory/`、`deeptutor/learning/`、`deeptutor/core/context.py`、相关 API/工具/前端入口 |
| 评审方式 | RFC 逐条 ↔ 现行代码对照，全部锚点为 `path:line` 实测核对 |

**结论速览**：RFC 对"缺什么"的诊断约一半成立——概念级学习状态、遗忘管理、错误记录**已经**在 `deeptutor/learning/` 中以相当完整的形态存在，但它们是"Mastery Path 内的路线状态"，与 `deeptutor/services/memory/` 的三层记忆系统**并行且互不相通**。真正要做的是打通与聚合，而不是新建六层。逐条结论见 §2、§3；八项建议中 2 项采纳（保留现状）、5 项改造、1 项搁置。

---

## 1. 现状速览：两套并行的状态系统

### 1.1 三层记忆子系统（`deeptutor/services/memory/`）

目录布局 `trace/ L2/ L3/ backup/`（`deeptutor/services/memory/paths.py:3-8`），七个 surface：`chat / notebook / quiz / kb / book / partner / cowriter`，四个 L3 槽：`recent / profile / scope / preferences`（`paths.py:48-60`）。

- **L1 事件**：`TraceEvent{id, ts, surface, kind, payload, session_id, turn_id}`（`trace.py:36-63`），append-only JSONL、永不抛错（`trace.py:66-79`）。**实际发射点只有 3 处**：chat 偏好声明（`tools/builtin/__init__.py:984`）、partner 偏好声明（`tools/partner_memory.py:196`）、kb 查询（`services/rag/service.py:173`）。
- **L1 快照（snapshot）**：每 surface 一个只读 adapter（`snapshot/adapters.py:64,127,158,295,348,408,457`，统一入口 `adapters.py:590-622`）。notebook 实体带完整记录内容（标题/用户问题/摘要/输出，`adapters.py:64-126`）；quiz 实体只有题面/答案/对错/书签，**不携带知识点关联**（SELECT 列清单 `adapters.py:457-516`）。
- **L2/L3 文档**：带脚注引用的 markdown，`Entry{id, section, text, refs}`（`document.py:64-78`），条目即"结论 + 证据引用"；原子 ops 校验后整体应用、单条 ≤240 字符（`ops.py:18,23-46`）。
- **整合器（consolidator）**：update/audit/dedup/merge 四模式（`consolidator/__init__.py:6-27`）；update 按 meta id-set 差分增量、分块调 LLM、引用池校验后追加（`consolidator/modes/update.py:1-21`）。**由记忆工作台手动触发**（runs API `deeptutor/api/routers/memory.py:308-410`），无定时任务。
- **注入 chat**：L3 四文档拼接（`store.py:94-103`），但**仅当客户端在本 turn 显式传 `memory_references` 时注入**（`services/session/turns/executor.py:296,563`；判定逻辑 `services/session/_turn_runtime_shared.py:409-425`），最终作为 prompt block（`agents/loop/prompt_blocks.py:163-164`）。`read_memory` 工具读同一份拼接（`tools/builtin/__init__.py:897-916`）。
- **用户可见可改**：工作台 API 提供总览/条目溯源/文档读写/条目删除/重置/整合运行/撤销（`deeptutor/api/routers/memory.py:84,95,140-170,308-410`）；前端页面 `web/app/(utility)/memory/`（l1/l2/l3/graph）；"graph"是**跨层引用图**（节点=条目/实体，边=脚注引用，`web/lib/memory-graph.ts:1-5`），不是知识依赖图。
- **历史迁移**：v1→v2（`store.py:331-357`）、tutorbot→partner surface 改名（`store.py:360-426`）。

### 1.2 学习状态子系统（`deeptutor/learning/`）与统一测评管线

- **聚合根 `LearningProgress`**（`learning/models.py:532-582`，per Mastery Path 一份，SQLite CAS 事务存储 `learning/storage.py:1-14`）：`mastery_levels`（每知识点 0..1 float，`:550`）、`qualitative_mastery`（CONCEPT/DESIGN 定性门，`:554`）、`quiz_attempts`（`:556`）、`error_records`（`:557`）、`learning_evidence`（`:560`）、`desired_retention`（0.7–0.99，`:563`）、`repetition_states`（`:564`）、`review_queue`（`:565`）、`learner_mastery_overrides`（`:569`）、`deferred_objectives`（`:572`）。
- **知识依赖**：`KnowledgePoint.prerequisite_ids`（`models.py:80-92`，前置关系在 `:88`）。
- **错误记录**：`ErrorRecord` 四类 `error_type`（structural/deviation/application/metacognitive，枚举 `models.py:36-45`、字段 `models.py:145-157`），含 `self_attribution`、`ai_confirmation`、`retry_history`、生命周期 `active/retrying/review/graduated`（`:156`）——**题目粒度**，无跨题聚合的"错误模式"实体。
- **遗忘管理**：`RepetitionState{difficulty, stability, retrievability, desired_retention, next_review_at, lapse_count…}`（`models.py:186-207`），FSRS 风格调度器含按知识类型的间隔序列（`learning/scheduler.py:16-20`）、默认目标保持率 0.9（`:37`）、证据重放（`#1541` 同会话短间隔不算新一次提取）。另有 `ReviewTask`（`models.py:210-222`）。
- **统一测评管线**：六种来源 `deep_question / mastery_path / immersive_reading / book / partner_chat / import`（`core/assessment.py:4-7`），统一入口 `record_assessment`（`learning/assessment.py:425`），跨面证据经显式 linkage 幂等地更新保持率状态（`learning/assessment.py:265-277,300-386`），且仅信任已保存 path 的真实目标（`:280-291`）。
- **学习者输入**：一次性 intake 的 `LearnerProfile`（`models.py:439-485`）、声明式覆盖 `LearnerMasteryOverride`（`:419-426`，不伪造证据）、`DeferredObjective`（`:429-435`）。
- **事件与实时**：`MasteryEvent` 持久事件尾（`models.py:327-339`）+ 低延迟唤醒 hub（`learning/event_hub.py:1-9`）。
- **对外只读出口**：Mastery 会话内的 `mastery_status`（`policy.py:329` 的 `map_summary`，含每知识点 status/mastery/来源/override 备注）；普通 chat 的四个只读导航工具 `mastery_topics/sessions/open/new`（`tools/mastery_nav.py:1-12`，明确"never writes"）。
- **平行的第二套复习调度**：practice 模块自带 SM-2 冷启动策略（`services/practice/scheduler.py:1-4,30`），与 `learning/scheduler.py` 互不共享状态。

### 1.3 关键结构性事实

1. **两套系统零桥接**：`deeptutor/learning/` 不 import `services.memory`，反之亦然（全库检索无交叉引用；`learning/service.py:1768` 的 `record_qualitative_in_memory` 是"内存中(in-memory)应用"之意，不写记忆子系统）。学习状态不会进入 L1/L2/L3；记忆内容不会进入 `LearningProgress`。
2. **chat 默认两样都看不见**：L3 注入是客户端 opt-in（§1.1）；学习状态只在 Mastery 会话/导航工具中出现。
3. **RFC 所列模块中 Deep Solve、Research、Reading 不在七个 memory surface 之内**（权威清单 `paths.py:48-56`）；Deep Solve 的计划状态在会话内存中（`capabilities/solve/capability.py:10`）。

---

## 2. RFC §2 四个"核心问题"诊断核对

| # | RFC 诊断 | 核对结果 | 现状锚点 |
| --- | --- | --- | --- |
| P1 | 缺少概念级学习状态 | **部分成立**：per-path 概念状态已有（量化 float + 定性 bool + 证据），缺的是跨 path 全局视图与"识别/回忆/应用/迁移/解释"五维细分 | `learning/models.py:550,554`；无五维字段 |
| P2 | 缺少错误模式记忆 | **部分成立**：错误有类型、归因、重试与生命周期，但停在单题粒度，无跨题聚合的模式实体 | `learning/models.py:145-157` |
| P3 | 缺少跨模块学习事件沉淀 | **大部分成立**：quiz/reading/book/partner_chat 六源已入统一测评管线并联动保持率，但 Notebook/KB 只进记忆快照、Deep Solve/Research/Reading 不进 trace，两套管线互不相通 | `core/assessment.py:4-7`；`learning/assessment.py:425`；发射点仅 3 处（§1.1）；`paths.py:48-56` |
| P4 | 缺少可解释可修正的 memory | **记忆侧基本不成立**：脚注引用可溯源（`deeptutor/api/routers/memory.py:95`，trace 反查 `trace.py:115-128`）、可改可删可重置（`deeptutor/api/routers/memory.py:140-170`）；**学习侧半成立**：有声明式覆盖/延期（`models.py:419-435`），但证据无用户侧"重新测试/删除"入口 | 同左 |

---

## 3. RFC §3 目标逐条评审（G1–G8）

### G1 统一所有学习行为的记录方式 —— **改造**（低成本，优先做）

- 现状：L1 有两种"记录方式"——事件 trace（3 个发射点）与快照 entity（7 surface）；学习证据是第三种（`LearningEvidence`，六源）。三者 schema 各异：`TraceEvent.payload`（`trace.py:36-63`）、`Entity{label,content,metadata}`（`snapshot/entity.py:20-27`）、`LearningEvidence`（`models.py:160-183`）。
- 可行性：高。最务实的起点是**扩展 L1 发射点**：Deep Solve 提示请求次数、Reading 动作（已有 `ReadingActivityRecord`，`models.py:509-520`）、Research 产出落为 trace 事件，schema 沿用 `TraceEvent` 即可。
- 成本：低–中（每 surface 一个发射点 + 对应 snapshot adapter，模式已有）。风险：trace 只追加（`trace.py:66-79`），量增长靠 update 差分消化（`update.py:1-21`），需注意预算（`settings.py:63-70`）。
- 注意：不必先统一三套 schema——`LearningEvidence` 的 `source/session_id/turn_id` 字段已与 trace 语义对齐，做"事件 ID 互通"（RFC 作者评论里的 evidence citation）比做大一统 schema 便宜。

### G2 建立概念级学习状态 —— **改造**（高成本，分阶段）

- 现状：`mastery_levels` 是单一 0..1 float（`models.py:550`）+ 定性 bool 门（`:554`）；概念本体是 per-path 的 `KnowledgePoint`（`:80-92`）。RFC 的五维（识别/回忆/应用/迁移/解释）无处安放。
- 可行性：中。**不建议**按 RFC 新建一个全局 Learner State 层：概念归一是硬问题——同一条"贝叶斯公式"在不同 path 里是不同 `kp.id`，无全局概念 ID。可行路径是先建**跨 path 概念索引**（规范化名称/别名 → 各 path 的 kp 与证据集合），五维评分以 `assessment_type` 维度扩展（`core/assessment.py:8-10` 已有 quiz/focus_check/qualitative/review 四类）渐进引入，且应从已有 `quality/hints_used/confidence/response_time`（`models.py:177-181`）推导，而非全靠 LLM 新评估。
- 成本：高。风险：LLM 自动五维评分的成本与噪声；索引的一致性维护。

### G3 记录长期错误模式 —— **改造**（中成本）

- 现状：`ErrorRecord` 有 `error_type` 四分类、`self_attribution`、`ai_confirmation`、重试史与毕业状态（`models.py:145-157`），但一条记录对应一道题；RFC 举例的"条件概率方向混淆 × 4 次"这种**模式级聚合**不存在。
- 可行性：较高。在现有字段之上加一层聚合（按 error_type + 归因文本聚类，或由 tutor 在 error_diagnosis 阶段（`LearningStage.ERROR_DIAGNOSIS`，`models.py:61-72`）产出模式条目并回链 `question_id`/`evidence_id`）。证据引用机制可直接复用。
- 成本：中。风险：归因文本聚类的准确性；模式误判会放大（一条错误模式影响后续所有教学决策）。

### G4 支持复习和遗忘管理 —— **搁置（已存在，无需新建）**

- 现状：`RepetitionState` 含 `difficulty/stability/retrievability/desired_retention`（`models.py:186-207`），调度器带按知识类型的间隔序列与目标保持率（`scheduler.py:16-20,37`）、证据重放（`#1541`），跨面证据联动（`learning/assessment.py:300-386`），到点复习队列 `review_queue`（`models.py:565`）。RFC 该项要求已被满足且超出。
- 唯一行动点：**收敛双调度器**——practice 模块另有一套 SM-2（`services/practice/scheduler.py:1-4`），与 learning 调度并行存在漂移风险（同一学习者在两处得到不一致的复习节奏）。
- 成本：收敛为低–中；不改则为 0。

### G5 让 TutorBot 能根据用户状态调整教学方式 —— **改造**（中成本）

- 现状：Partner（TutorBot 前身，见 `store.py:360-426` 迁移）有完整的私有记忆：split 模型（关系记忆 per 指派用户 + 属主 L3 只读，`tools/partner_memory.py:1-14`），专用三工具 `partner_read/partner_memorize/partner_search`（`:26-32`）。但 partner 工具**读不到学习状态**；学习状态只在 Mastery 会话内（`policy.py:329`）与普通 chat 的只读导航（`tools/mastery_nav.py:1-12`）可见。
- 可行性：较高。给 `partner_read` 或 mastery_nav 增加一个只读的"学习者状态摘要"块（数据源 `map_summary`，`policy.py:329`）即可迈出第一步；沿用 navigation 的"never writes"原则可复用安全论证。
- 成本：低（只读摘要）→ 中（状态驱动教学策略）。风险：状态误读导致教学方式误调整；建议摘要附 override/deferred 标记（`models.py:419-435`）以免覆盖学习者声明。

### G6 让 Notebook、Quiz、Book、Deep Solve 都能反哺 memory —— **改造**（中成本）

- 现状分三类：
  - **Quiz**：答题已通过统一管线持久化并可联动保持率（`learning/assessment.py:425,300-386`）；错题进题库（`tools/question_bank.py:432,449`）。
  - **Notebook / Book**：作为 L1 快照源进入记忆整合（`adapters.py:64-126,158`），即"内容可被摘要"，但不产生学习证据。
  - **Deep Solve / Research**：两者皆不在 surface 清单（`paths.py:48-56`）与发射点内，完全不落记忆。
- 可行性：高。与 G1 同一工程：补发射点/adapter。RFC 四问中"读过的章节影响下一次 Quiz"已有部分基础——Book focus-check 属六源之一（`core/assessment.py:5`）；Notebook 笔记影响讲解则要等 §4.5 的 artifact→evidence 通道。
- 成本：中。风险：低（均为增量）。

### G7 让用户能查看、纠正、删除系统记忆 —— **采纳（保留现状），补学习侧**

- 现状：记忆侧完备——查看（`deeptutor/api/routers/memory.py:84,140`）、溯源（`:95`）、编辑/删除/重置（`:151-170`）、整合预览→应用两步流（`store.py:166-193`）与撤销（`deeptutor/api/routers/memory.py:373`）。学习侧有声明式覆盖与延期（`models.py:419-435`），但 `learning_evidence`/`error_records` 无用户侧删除或"重新测试"入口。
- 建议：补学习侧的 evidence 视图与 void 语义（`QuizAttempt.voided/void_reason` 已有先例，`models.py:131-134`）。
- 成本：低–中。

### G8 为后续学习插件提供统一 memory 基础 —— **搁置（前置条件未满足）**

- 现状：插件面已有 per-turn 可变状态容器 `UnifiedContext.extension_state`（`core/context.py:150-156`）与 Skills 系统；但"统一 memory 基础"恰恰依赖 G1/G2 的打通——目前连产品内部的两套状态系统都未互通，先对外承诺统一基础会固化当前裂缝。关联 issue #380（学习体验插件 SDK）同理应排在其后。
- 结论：搁置，待 G1/G2 落地后重评。

---

## 4. RFC §4 六层建议逐条评审

### 4.1 Profile Memory —— **采纳（保留）**

已有三处承载：L3 `profile` 槽（`paths.py:57`）、chat 偏好写入 `write_preference`（幂等去重，`store.py:195-258`）、Mastery intake 的 `LearnerProfile`（`models.py:439-485`）。RFC 也明言"可以继续保留"。遗留小问题：三处画像无合并视图——可在 L3 整合 prompt（`consolidator/prompts/*/update_l3.yaml`）侧重时消化，不动架构。

### 4.2 Summary Memory —— **采纳（保留）**

L3 `recent` 槽 + 七个 L2 surface 即是（`paths.py:48-60`）；跨 surface 的"最近在做什么"另有 stamps-only 的 `recall.recent`（`recall.py:142-186`），其"只读元数据不动内容"的约束值得在新层沿用。

### 4.3 Learner State Memory —— **改造**（核心，见 G2）

RFC 称之为"新增的核心层"。核对结论：**数据模型已存在**（`LearningProgress` 全量字段，`models.py:532-582`），缺的是（a）跨 path 全局化与概念归一；（b）五维认知细分；（c）对 chat/TutorBot 的可见性（见 G5）。建议以"索引 + 投影"方式演进——保持 per-path 聚合根为唯一写入点（SQLite CAS，`storage.py:1-14`），新建只读的全局概念索引，避免第二写入点带来的并发与一致性问题。

### 4.4 Misconception Memory —— **改造**（见 G3）

在 `ErrorRecord` 之上聚合，不另立存储层。模式条目应携带 RFC 要求的四要素（模式、次数、最近出现、关联概念）+ 证据引用（回链 `question_id`/`evidence_id`），其中证据引用机制与 L2 脚注（`document.py:64-78`）同构。

### 4.5 Artifact Memory —— **改造**（方向正确，落地分两步）

"Artifact 不只是文件，而是学习证据"的判断与现行 `LearningEvidence` 的设计哲学一致（`models.py:160-167`："Trusted linked assessments may originate in another learning surface"）。已验证可行的通道：quiz 实体进 L1 快照（`adapters.py:457-516`）、notebook 全文进 L1（`adapters.py:64-126`）、Reading 笔记回送 notebook（`reading/knowledge_capture.py:87`）并可作 mastery 来源（`:126`）。缺失的是**内容→状态**的通道：notebook 用户理解目前不产生证据，需要一条"笔记声明 → 定性评估（`record_qualitative_for_path`，`learning/service.py:1705`）"的受控入口，防止把未评估的自述当成掌握。

### 4.6 TutorBot Private Memory —— **采纳（保留）**

Partner split 记忆模型（`tools/partner_memory.py:1-14,26-32`）+ L2 `partner` surface（`paths.py:54`）即此层。RFC 三个示例（数学/写作/研究 TutorBot）属同一机制的多个 partner 实例，无需新代码。

---

## 5. 对作者评论区修订（合并 4.2/4.3/4.4 为单一 Graph）的评审 —— **改造（分阶段）**

作者在评论中提出：Layer 2/3/4 合并为一个图，节点含认知维度评分、错误模式、证据引用（指向原始事件 ID），边为知识依赖（前置/关联），掌握不足时自动上溯前置定位卡点。核对：

- **边已存在（但尚不生效）**：`KnowledgePoint.prerequisite_ids`（`models.py:88`）即前置边；但关系当前只是结构元数据——"They do not gate learning or retrieval yet"（`deeptutor/learning/objective_relations.py:1-3`），即 RFC 的"掌握不足时自动上溯前置定位卡点"**没有实现**，这是修订方案里真正的新增量。路由层既有的只是绕开 override/deferred 目标（`models.py:566-572` 注释）。
- **证据引用已存在**（两套）：L2 条目脚注 → trace 事件（`document.py:64-78` + `trace.py:115-128`）；学习侧 `evidence_id` → `LearningEvidence`（`models.py:170`）。合并图的"指向原始事件 ID"应选择与 trace ID 互通（呼应 G1）。
- **主要障碍**：①概念归一（§G2）——全局图的节点需要全局概念 ID；②现有引用图前端（`web/lib/memory-graph.ts:1-5`）是引文图，渲染知识依赖图需新视图；③一次性合并三层等于重写整合器与工作台，回归面大。
- **建议路径**：Phase 1 跨 path 概念索引（含 prerequisite 边的并集投影）→ Phase 2 错误模式聚合挂上节点 → Phase 3 才考虑单一持久图存储。每步独立可交付、可回滚。

## 6. 与 issue #380（学习体验插件 SDK）的关系

#380 要在"真实学习者行为"之上建插件 SDK 与 Knowledge Garden 可视化，其数据面诉求（学习事件、learner-state 模型）与本 RFC 的 G1/G2/G8 完全重叠。两卡应共享 §5 的分阶段底座，插件 SDK（G8）排在索引/聚合之后，避免插件直接耦合 per-path 内部结构。

---

## 7. 总结

### 结论一览

| RFC 提议点 | 结论 | 一句话理由 |
| --- | --- | --- |
| G1 统一学习事件记录 | 改造 | 三种记录并存；先补发射点与 ID 互通，不急大一统 schema |
| G2 概念级学习状态 | 改造 | per-path 已有；缺全局概念归一与五维，走"索引+投影" |
| G3 长期错误模式 | 改造 | ErrorRecord 之上做模式聚合，复用证据引用 |
| G4 复习与遗忘管理 | 搁置 | FSRS 式实现已超出 RFC 要求；仅需收敛 practice 的平行 SM-2 |
| G5 TutorBot 按状态调整 | 改造 | partner 记忆已有；补只读状态摘要即可起步 |
| G6 多模块反哺 memory | 改造 | Quiz 已通；Notebook/Book 半通；Deep Solve/Research 缺席 |
| G7 用户查看/纠正/删除 | 采纳 | 记忆侧完备；补学习侧 evidence 视图与 void |
| G8 插件统一 memory 基础 | 搁置 | 前置（G1/G2）未满足，先行会固化裂缝 |
| 4.1 Profile | 采纳 | 三处承载，保留 |
| 4.2 Summary | 采纳 | L2/L3+recall 已覆盖 |
| 4.3 Learner State | 改造 | 见 G2 |
| 4.4 Misconception | 改造 | 见 G3 |
| 4.5 Artifact | 改造 | 分两步：先进 L1，再建受控的 artifact→evidence 通道 |
| 4.6 TutorBot Private | 采纳 | partner split 模型即此层 |
| 评论修订：合并为单一 Graph | 改造 | 边与证据引用已存在；概念归一是硬前置，分三阶段演进 |

### 核心结论（5 条）

1. **RFC 的诊断只对一半**：概念级状态、错误记录、遗忘管理已在 `deeptutor/learning/` 实现（`models.py:532-582`），真正的缺口是它与 `services/memory/` 三层系统**零桥接**、且对普通 chat/TutorBot 不可见——问题是"打通"，不是"新建六层"。
2. **最高性价比的第一步是 G1**：把 Deep Solve/Research/Reading 补进 L1 发射点（现仅 3 处），并让 trace ID 与 `evidence_id` 互通；这同时是合并 Graph 方案"证据引用指向原始事件"的前置。
3. **全局 Learner State 的真正难点是概念归一**（同一知识点在不同 path 是不同 `kp.id`），建议只读索引 + 保持 per-path 单一写入点（`storage.py:1-14` 的 CAS 语义不被破坏）。
4. **遗忘管理无需任何新工作**（G4 搁置），但应消除 practice 模块与 learning 模块的双调度器漂移（`services/practice/scheduler.py:1-4` vs `learning/scheduler.py`）。
5. **作者评论区的"单一 Graph"方向可行但应分三阶段**：概念索引 → 错误模式挂载 → 持久图；前置边已作为结构元数据存在（`prerequisite_ids`）但尚不参与路由（`objective_relations.py:1-3`），"自动上溯卡点"是真正需要新建的能力，两套证据引用机制也都已在位，缺的只是归一层。

### 风险清单

- 概念归一错误会把不同知识点的证据混算，直接影响复习节奏——索引层必须可整体重建、可禁用。
- LLM 自动五维评分的噪声与成本（G2/4.3）；应从既有 `quality/hints_used/response_time`（`models.py:177-181`）推导优先。
- 错误模式聚合误判会被教学循环放大（G3）；模式条目需保留反例证据与用户纠错入口（呼应 G7）。
- 双调度器漂移（G4）；artifact→evidence 通道若不加评估门控，未验证的自述会污染掌握度（4.5）。

---

## 附录 A：锚点速查表

| 主题 | 锚点 |
| --- | --- |
| surface / L3 槽定义 | `deeptutor/services/memory/paths.py:48-60` |
| 记忆目录布局 | `deeptutor/services/memory/paths.py:3-8` |
| L1 事件模型 | `deeptutor/services/memory/trace.py:36-63` |
| trace 发射点 ×3 | `deeptutor/tools/builtin/__init__.py:984`、`deeptutor/tools/partner_memory.py:196`、`deeptutor/services/rag/service.py:173` |
| 快照 adapters | `deeptutor/services/memory/snapshot/adapters.py:64-622` |
| quiz 实体（无 kp 关联） | `deeptutor/services/memory/snapshot/adapters.py:457-516` |
| L2/L3 文档模型（脚注引用） | `deeptutor/services/memory/document.py:64-78` |
| 原子 ops | `deeptutor/services/memory/ops.py:18,23-46` |
| 整合器四模式 | `deeptutor/services/memory/consolidator/__init__.py:6-27` |
| update 算法 | `deeptutor/services/memory/consolidator/modes/update.py:1-21` |
| 记忆设置 | `deeptutor/services/memory/settings.py:63` |
| 工作台 API | `deeptutor/api/routers/memory.py:84-410` |
| L3 注入 opt-in | `deeptutor/services/session/turns/executor.py:296,563`、`deeptutor/services/session/_turn_runtime_shared.py:409-425` |
| prompt 注入 | `deeptutor/agents/loop/prompt_blocks.py:163-164` |
| read_memory / write_preference | `deeptutor/tools/builtin/__init__.py:897-916`、`deeptutor/services/memory/store.py:195-258` |
| partner 记忆 split 模型 | `deeptutor/tools/partner_memory.py:1-14,26-32` |
| LearningProgress 聚合 | `deeptutor/learning/models.py:532-582` |
| 知识点 + 前置边 | `deeptutor/learning/models.py:80-92` |
| ErrorRecord | `deeptutor/learning/models.py:145-157` |
| LearningEvidence | `deeptutor/learning/models.py:160-183` |
| RepetitionState / 调度 | `deeptutor/learning/models.py:186-207`、`deeptutor/learning/scheduler.py:16-37` |
| 统一测评管线 | `deeptutor/core/assessment.py:4-12`、`deeptutor/learning/assessment.py:265-386,425` |
| 跨面证据联动保持率 | `deeptutor/learning/assessment.py:300-386` |
| 学习存储（SQLite CAS） | `deeptutor/learning/storage.py:1-14` |
| 学习者覆盖 / 延期 | `deeptutor/learning/models.py:419-435` |
| Mastery 状态摘要 | `deeptutor/learning/policy.py:329` |
| chat 只读导航 | `deeptutor/tools/mastery_nav.py:1-12` |
| practice 平行 SM-2 | `deeptutor/services/practice/scheduler.py:1-4,30` |
| 记忆引用图（非知识图） | `web/lib/memory-graph.ts:1-5` |
| UnifiedContext 扩展位 | `deeptutor/core/context.py:150-156` |
