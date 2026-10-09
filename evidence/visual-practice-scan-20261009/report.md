# visual_practice 评估边界清单（upstream #1901 前置对照）

- 基线：origin/main = `6cf793bd8`（v1.6.14 release），分支 `scan/visual-practice-assessment-20261009`
- 上游诉求：HKUDS/DeepTutor#1901（Meaning-based visual and source-dependent assessment beyond answer aliases）
- 方法：只读静态扫描 `deeptutor/learning/visual_practice.py` 及其 mastery 判分上下游调用面；未改任何产品代码
- 去重引用（不重复展开）：
  - choices 形状测试：`deeptutor/learning/tests/test_mastery_choices.py`（25 例，覆盖 parse_options / label intent / 选项体识别，choices 数据形状不在本清单展开）
  - 模块导读：`docs/guides/tools-surface.md:57,58,109,116,125`（mastery 工具面总览）
- 行号均相对 commit `6cf793bd8`。三态：已支持 / 部分 / 缺失。

## A. 别名 / choices 快路径

| # | 结论 | 位置 | 状态 |
|---|------|------|------|
| A1 | 答案归一化：NFKC + casefold + 空白压缩 + 去句末标点，别名匹配是归一化后的**精确集合命中**，无模糊相似度 | `deeptutor/learning/visual_practice.py:11-13`, `233-236` | 已支持 |
| A2 | accepted_answers 上限 12 条、单条 200 字符、去重；canonical 答案恒在首位 | `deeptutor/learning/visual_practice.py:98-105` | 已支持 |
| A3 | 别名来源是模型在 mastery_quiz 调用时声明的「verified equivalents」（含跨语言译法），工具契约文案要求 source-grounded canonical 术语；平台侧只做长度/数量约束，**无语义或来源二次校验** | `deeptutor/capabilities/mastery/tools.py:909`, `98-105`（v_p 同上） | 部分 |
| A4 | choices 快路径：alias 未命中且 `question_type=="choice"` 时走可读性判定 → 单选解析 → 与 expected 比对出 correct/incorrect | `deeptutor/learning/visual_practice.py:237-246` | 已支持 |
| A5 | 歧义/多解/提问式作答解析为「不可读」而非错答（#1004 门），caller 必须按 unreadable 处理 | `deeptutor/learning/pending.py:139-166`, `169-211` | 已支持 |
| A6 | 非 choices 且非别名的自由表述一律 ungraded，明确「不按表面相似度推断错答」——这正是 #1901 §2 要求语义评测的位置，现状只有确定性两分支 | `deeptutor/learning/visual_practice.py:247-249` | 缺失（语义评测） |
| A7 | 非 visual 普通题仍走关键词重叠（open: ≥0.6 命中即对）/ 相似度（short ≤30 字符 ratio≥0.85）；#1901 §2 明言关键词重叠不足以判对 | `deeptutor/learning/grading.py:13-50` | 部分 |
| A8 | challenge/correct 修复：重跑 prepare_visual 重建别名，要求 pixels 已投喂且 key 重验为 verified，否则拒绝授予（不奖励挑战本身） | `deeptutor/learning/service.py:1550-1577` | 已支持 |

## B. ungraded / 澄清路径

| # | 结论 | 位置 | 状态 |
|---|------|------|------|
| B1 | 像素未投喂 → ungraded，诊断文案明确「不降低 mastery」 | `deeptutor/learning/visual_practice.py:206-210` | 已支持 |
| B2 | key 未独立验证（key_status≠verified 或无 sources）→ ungraded | `deeptutor/learning/visual_practice.py:211-215` | 已支持 |
| B3 | 判分时逐源重新 retrieve_visual，源失效/不可访问 → ungraded（评估问题≠学习者错误） | `deeptutor/learning/visual_practice.py:216-232` | 已支持 |
| B4 | ungraded 在 service 层映射为 `is_correct=None`、**跳过 _apply_grade**，不写 QuizAttempt，事件用 `practice.ungraded` 区分 | `deeptutor/learning/service.py:962-976`, `1002-1009` | 已支持 |
| B5 | mastery 只统计 `not voided and independent` 的尝试；无 expected 答案 fail-closed 记错 | `deeptutor/learning/service.py:463-470`, `496-497`, `532` | 已支持 |
| B6 | 辅助下答对：evidence.quality 封顶 0.6，hints_used 写入 evidence | `deeptutor/learning/service.py:571-575` | 已支持 |
| B7 | 近期辅助检测：同源同页同任务、引用相同、4 天会话窗内（`_SAME_SESSION_DAYS`）→ 强制 hints_used≥1 + recently_assisted | `deeptutor/learning/visual_practice.py:163-196`, `167` | 已支持 |
| B8 | `recently_assisted` 标记只在 visual_practice.py:194 产出，**全仓库无下游消费者**；实际传播量只有 hints_used（service.py:554,573 与 interaction.result independent） | `deeptutor/learning/visual_practice.py:194`；消费点 `service.py:554,573,997` | 部分 |
| B9 | 出题后才讲解（explained_objectives 时间戳晚于出题）→ 强制 assisted + teaching_after_question | `deeptutor/learning/service.py:952-958` | 已支持 |
| B10 | ungraded 的「聚焦澄清」无内置机制：仅把 diagnosis 字符串透传给 tutor（interaction.result），下一步动作完全靠模型自律 | `deeptutor/learning/visual_practice.py:247-249`（diagnosis 文案）， `deeptutor/learning/service.py:991-999` | 部分 |
| B11 | ungraded 不触碰 learning_evidence 分支 | `deeptutor/learning/service.py:1011` | 已支持 |

## C. 图片来源校验点

| # | 结论 | 位置 | 状态 |
|---|------|------|------|
| C1 | 任务白名单：identification / relationship / table_graph / comparison，越界即拒 | `deeptutor/learning/visual_practice.py:37-41` | 已支持 |
| C2 | 源引用 1–2 个；comparison 必须 2 源；每源必须是对象 | `deeptutor/learning/visual_practice.py:42-46,50-51` | 已支持 |
| C3 | KB 归属校验：必须在话题/回合 attached_kbs 内 | `deeptutor/learning/visual_practice.py:52-56` | 已支持 |
| C4 | KB 可访问性校验（resolve_for_rag） | `deeptutor/learning/visual_practice.py:57-59` | 已支持 |
| C5 | 原图检索 retrieve_visual 失败/无图 → 直接拒绝出题（准备期） | `deeptutor/learning/visual_practice.py:65-69` | 已支持 |
| C6 | 投喂像素哈希记录：`image_sha256` = 检索所得原始字节摘要 | `deeptutor/learning/visual_practice.py:81` | 已支持 |
| C7 | 像素投喂真实性：agent loop 用**实际发送消息**的 image_content_hashes 回填（非模型声明），mastery 工具路径恒传 `_inspected_image_hashes`（空列表即 fail-closed 不投喂） | `deeptutor/agents/loop/agent_loop.py:1273-1275`, `deeptutor/capabilities/mastery/loop.py:270-271`, `deeptutor/capabilities/mastery/tools.py:1067` | 已支持 |
| C8 | inspected 判定的 bool 声明回退：`inspected_image_hashes=None` 时信任 request 的 pixels_inspected 布尔；仓内唯一该路径是 challenge 修复（先在 1554-1558 显式要求 pixels_inspected 才放行），非 mastery 工具路径不经过此分支 | `deeptutor/learning/visual_practice.py:121-128`, `deeptutor/learning/service.py:1554-1558,1560` | 部分 |
| C9 | 页面文本直接暴露答案 → 强制 cues=visible（引导阅读，即便调用方声称 none） | `deeptutor/learning/visual_practice.py:82-85,119-135` | 已支持 |
| C10 | cues 白名单 none/visible/unverified；mask 声明要求独立验证区域 | `deeptutor/learning/visual_practice.py:114-118` | 已支持 |
| C11 | reference_quote 验证：引用须逐字出现在源文本（词边界、非模糊子串）+ 引用含 canonical 答案 + key_status==verified 三条同时成立 | `deeptutor/learning/visual_practice.py:16-22,94-113` | 已支持 |
| C12 | 源上下文拼装（caption/context/text/page_context/table_html/notes）仅用于 quote 验证；**没有**「该 label/panel/数值确实属于所展示证据、问题从图中可答」的可答性/归属验证点，也没有保留本题评估要素（required ideas/relations/acceptable variations/contradictions）的结构化评估参考 | `deeptutor/learning/visual_practice.py:60-67,88-93` | 缺失 |
| C13 | source_text 与 quote 先剥离 HTML 标签再归一化，避免标签干扰匹配 | `deeptutor/learning/visual_practice.py:106-107` | 已支持 |
| C14 | 每次判分确定性完成，零额外 LLM 调用（符合 #1901 §2「简单答案保持廉价」；语义评测侧因此空缺） | `deeptutor/learning/visual_practice.py:233-249` | 部分 |
| C15 | 视觉上下文公开面：public_visual 只回传 task/sources/answer_cues/key_status/hints_used/pixels_inspected，不泄漏 reference_answer | `deeptutor/learning/visual_practice.py:148-160`, `deeptutor/learning/question_card.py:69,86-87` | 已支持 |

## 对照 #1901 的三个最大缺口

1. **语义评测整体缺失（§2）**：`visual_practice.py:247-249` 的 fallback 把所有非别名、非 choices 的自由解释归为 ungraded；无「正确转述/部分正确/带特定误解的错误/不可靠评估」四态区分，跨语言等价完全依赖模型预声明 aliases（`tools.py:909`），无判分期语义兜底。这是 up-1901 实现卡的主体。
2. **评估参考与问题可答性验证缺失（§1）**：`visual_practice.py:94-113` 只验证「引用文本 ∈ 源文本 + 答案 ∈ 引用」，#1901 明言这不足以证明每个 generated alias / 视觉答案 key 语义有效；缺「label/panel/结构归属所展示证据」与「required ideas/relations 结构化评估参考」两个校验点（`visual_practice.py:60-67,88-93`）。
3. **澄清/证据修复机制仅提示词侧自律（§3）**：ungraded 只透传 diagnosis 文案（`service.py:991-999`），无内置聚焦澄清或证据修复流程；且 `recently_assisted` 标记无下游消费者（`visual_practice.py:194`），学习状态区分实际只靠 hints_used 一条传播链（`service.py:554,573`）——「评估系统故障 ≠ 学习者错误」在存储层成立（B4/B11），在交互层缺主动澄清闭环。

## 既有测试对照（引用，不重复）

- `deeptutor/learning/tests/test_visual_learning_workflow.py:253`（歧义/未验证/源变更 → 无负向 mastery）、`:212`（受支持错答判错 + 故障修复移除影响）、`:386`（出题后讲解记辅助）、`:408`（声明 vision 但无投喂像素 → guided）、`:313`（relationship/table/comparison 双源）
- `deeptutor/learning/tests/test_mastery_choices.py`：choices 数据形状 25 例（去重目标，本卡不复述）

## 统计

- 边界条目：A 8 + B 11 + C 15 = **34 条**（已支持 26 / 部分 6 / 缺失 2）
