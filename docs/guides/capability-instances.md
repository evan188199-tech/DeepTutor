# 能力实例目录速览：capabilities 下 8 个零认领实例（guide-capability-instances）

- 基线：`origin/main @ f07029cfc`（v1.6.13）。文内 `path:line` 均为该基线、相对仓库根目录。
- 范围与边界：本文只覆盖 `deeptutor/capabilities/` 下 8 个实例目录（obsidian、course_study、explore_context、setup、partner_authoring、partner_group、audio_overview、solve）。框架面（`protocol.py` 的 LoopExtension 协议全貌、`registry.py` 的注册表与插件发现、capability catalog、chat pipeline 装配细节）不在本文展开——仅在"注册与装配"一节给出实例插入点的最小索引。
- 8 个目录分两类：6 个是 chat loop 扩展（LoopExtension，随每轮对话按 `is_active` 挂载）；2 个以 TurnCapability 形态作为用户可选能力入口（audio_overview、solve；course_study 兼有两半，见下文）。

## 0. 全景

| 实例 | 类型 | 激活条件（一句话） | 自有工具 |
| --- | --- | --- | --- |
| obsidian | Loop 扩展（KnowledgeCapability，独占回合） | 选中知识库是已连接 Obsidian vault | 9 个 obsidian_* |
| course_study | 模式（TurnCapability）+ Loop 扩展 | composer 模式 = course_study 且回合绑定了 course_id | 4 个 course_* |
| explore_context | Loop 扩展（纯 pre_loop） | 回合带任何可读附件源（source_index 非空） | 无（read_source 只活在 pre-pass 内） |
| setup | Loop 扩展（增量式） | 回合命中安装配置信号（显式提问/首次对话 intro） | 4 个 setup 工具 |
| partner_authoring | Loop 扩展（增量式） | 用户显式选择，或消息命中创建 Partner 关键词门 | propose_partner |
| partner_group | Loop 扩展（增量式） | 回合 metadata 带 partner_group 群组信息 | invoke_other |
| audio_overview | TurnCapability（流水线） | 用户选择该能力且已附加知识库 | rag（工具清单声明） |
| solve | TurnCapability + Loop 扩展 | 用户选择 deep_solve 能力 | solve_plan / solve_finish_step / solve_replan + 内置组合 |

## 1. obsidian — 活动库上的智能体检索与写作

- 职责：选中知识库是 Obsidian vault 时，模型直接在 vault 的 Markdown 上导航与编辑，而非消费扁平化的检索块。作为 `KnowledgeCapability` 子类它独占回合：chat 内置工具全部退场，只剩 9 个 obsidian 工具 + `ask_user` 底座。
- 入口：`deeptutor/capabilities/obsidian/capability.py:25`（`ObsidianCapability`）；激活判定 `capability.py:31-32` → `binding.py:22`（`vault_for_turn`）。
- 关键机制：vault 根路径由服务端注入 `_vault_path`，模型永远不能自报路径（`capability.py:54-69`）；vault 知识库从 `rag` 面排除，避免与普通 KB 混读（`capability.py:34-38`，issue #650）；系统提示按语言加载并替换 `{vault_name}`（`capability.py:40-52`）。
- 依赖：`binding.py`（vault 绑定解析）、`vault.py:1-15`（唯一知道 Obsidian 磁盘约定的纯文件系统层：frontmatter/wikilink/忽略 `.obsidian` 等，`vault.py:25`；写入只增不删）。
- 文件锚点：工具名清单 `tools.py:30-40`（search/read/list/backlinks/links/tags/create_note/append/set_property）；提示词 `prompts/{en,zh}/system.md`；注册位 `deeptutor/capabilities/registry.py:56`。

## 2. course_study — 课程学习编排（模式 + 循环扩展两半）

- 职责：把普通 chat loop 变成课程编排器——感知课程状态、检查单个资源、维护课程容器、以封闭集合的 `course_handoff` 交还推荐。它不直接教学，只推荐下一步学什么。
- 入口（模式半）：`deeptutor/capabilities/course_study/mode.py:1-17`（`CourseStudyCapability`，TurnCapability：只归一化 metadata 并启动 `AgenticChatPipeline`）；注册 `deeptutor/runtime/bootstrap/builtin_capabilities.py:45`（spec `:211`）。
- 入口（循环半）：`deeptutor/capabilities/course_study/capability.py:380`（`CourseStudyLoopCapability`）；注册 `registry.py:70-73`。
- 关键机制：双重激活 `capability.py:386-387`——模式必须是 course_study **且** 回合解析出 course_id（`capability.py:77-79`），防止残留 course_id 的普通聊天泄漏课程工具；`pre_loop` 钩子拉一次课程聚合并压成 ≤3200 字符的确定性摘要（`capability.py:42`、`:483-522`），学习者约定/代理笔记分别限 900/500 字符随摘要每轮直达（`capability.py:51-52`、`:180-221`）；`course_handoff` 所在轮的散文按 "publish" 策略 rescued 并据此终止回合（`capability.py:422-465`、`:467-477`）。
- 依赖：`services/courses_state.build_course_state`（`capability.py:496-499` 惰性导入）、reading 目录/进度存储（`capability.py:258-300`）。
- 文件锚点：工具名 `tools.py:21-26`（course_overview/course_material/course_edit/course_handoff）；playbook 提示 `prompts/{en,zh}/course_study.yaml`（`:57-74` 加载）。

## 3. explore_context — 附件源的客观预读 pre-pass

- 职责：回答循环第一次 LLM 调用**之前**，用代理式只读调查读懂本回合附件源（文档/笔记记录/书章节/题库条目/被引用的会话历史），产出第三人称调查文本注入 user-message seed。动机：防止模型把"理解用户与另一个 AI 的对话记录"与"回答用户"在同一上下文里混淆（语音串味），并兜底弱模型从不主动调 read_source 的问题。
- 入口：`deeptutor/capabilities/explore_context/capability.py:82`（`ExploreContextCapability`）；注册 `registry.py:78-81`。
- 关键机制：无自有工具、无系统块（`capability.py:88`、`:93-103`），全部通过可选 `pre_loop` 钩子工作（`capability.py:118-141`）；`read_source` 只挂在 pre-pass 自己的工具循环里，回答循环不再挂载（`explorer.py:9-13`、`:402-403`）；代理循环上限 5 轮（`explorer.py:65`），无原生工具调用的提供方走单遍 fallback（`explorer.py:15-23`）；前端 "Exploring your context…" 状态按 `EXPLORE_STAGE`（`explorer.py:59`）取键。
- 依赖：`runtime.agentic` 工具分发、`services.llm`（均惰性导入避免循环依赖，`capability.py:127-132`）；每阶段 token 预算读 agents.yaml 的 `capabilities.explore_context`（`explorer.py:68-75`）。
- 文件锚点：激活判定 `capability.py:68-79`（source_index 非空）；调查入口 `explorer.py:140`（`investigate`）；提示词 `prompts/{en,zh}/explore_context.yaml`。

## 4. setup — DeepTutor 配置自己的安装

- 职责：让用户在对话中检查并修改应用自身配置（"换中文/换更好的 PDF 解析器"）。刻意是**增量式**普通 LoopExtension 而非独占能力——配置对话恰恰需要 KB、web 搜索等日常工具面（`deeptutor/capabilities/setup/capability.py:1-19`）。
- 入口：`deeptutor/capabilities/setup/capability.py:39`（`SetupCapability`）；激活由客观信号决定而非模型自判：`binding.py:242`（`is_setup_turn`）、原因分类 `binding.py:211`（`setup_activation`，含首次对话的 "intro"）。
- 关键机制：系统块附带当前安装缺口清单（`capability.py:61-66`，缺口扫描 `binding.py:46-65`、缓存 `:141`），intro 轮只点名一个最重要缺口且只给一次机会（`capability.py:68-82`、一次性标记 `binding.py:187-201`）；工具无服务端注入 kwargs——按 key 寻址、按调用者身份定 scope（`capability.py:85-95`）。
- 依赖：`access.py`（谁能改哪一 scope：personal 落调用者自己的 settings 文件）；`apply.py`（顺序即正确性：先解析行→查权限→查合法值→对**候选**配置跑 probe→最后才写盘）；`jobs.py`（解析引擎安装/权重拉取等长任务，单次工具调用内跟随日志到完成，经事件流转发进度）。
- 文件锚点：工具名 `tools.py:37-42`（inspect_setup/apply_setting/request_credential/run_setup_job；涉密服务的路由表 `:46`）；提示词 `prompts/{en,zh}/system.md`；注册位 `registry.py:82`。

## 5. partner_authoring — 把请求变成可评审的 Partner 草稿

- 职责：在普通聊天里识别"建一个 Partner"的请求，产出一份**仅供评审、不自动启动**的 Partner 档案草稿。
- 入口：`deeptutor/capabilities/partner_authoring/capability.py:18`（`PartnerAuthoringCapability`）；注册 `registry.py:83-86`。
- 关键机制：触发分级 `binding.py:58-90`——`explicit`（用户在 composer 选了该能力）与 `heuristic`（关键词门命中，属猜测），启发式带引号内忽略、否定从句忽略、疑问句忽略、非 Partner 目标忽略四重守卫；提示词按触发级别二选一（`capability.py:36-38`：explicit→system.md，heuristic→heuristic.md）；`finish_instruction` 在显式请求但无草稿时强制补一次 `propose_partner`，而启发式命中**从不**丢弃已写好的回答（`capability.py:55-68`，#1587：猜测不配删除回复）；`propose_partner` 注入 `_partner_authoring_context`（`capability.py:41-48`）。
- 依赖：Partner 服务的评审卡片流在 Home/产品侧，本目录只到草稿为止。
- 文件锚点：工具 `tools.py:11`（唯一工具 propose_partner，"绝不自行创建或启动"，`tools.py:14-22`）；提示词 `prompts/{en,zh}/{system,heuristic}.md`。

## 6. partner_group — Partner 群里的公开答案协议

- 职责：强制 Partner 群组回合的公开答案协议：先规范化正式答案，再（仅当群组允许时）给一次私有协作决策轮——是否邀请另一个 Partner 作答，且全程一跳（invoked 回答不得再发起新邀请）。
- 入口：`deeptutor/capabilities/partner_group/capability.py:18`（`PartnerGroupCapability`）；注册 `registry.py:87-90`。
- 关键机制：激活 = 回合 metadata 带 `partner_group` 字典（`capability.py:35-37`）；`buffers_visible_output=True`（`capability.py:33`）——公开答案先缓冲、清理尾部对同伴的散文式请求（`finish_instruction`，`capability.py:79` 起），私有决策轮后由 `final_text_override` 重发干净版（`capability.py:169`），避免用户看到将被编辑的文字或答案出现两次；决策轮只有两个合法动作：恰好一次 `invoke_other`（一个合规 peer + 独立问题）或字面 `NO_INVOKE`（`capability.py:98-105`）；与 invoke_other 同轮写出的散文按 publish 策略抢救（`capability.py:122`）；系统块附群成员名册与协作提案模板（`capability.py:39-63`）。
- 依赖：工具本身**只记录、永不执行**跨 Partner 调用（`tools.py:1`），执行由群组编排侧完成，工具是防二跳的最后闸门（`tools.py:14` 起）。
- 文件锚点：工具名 `tools.py:11`（`invoke_other`）；注入 `_partner_group_context`（`capability.py:65-73`）；提示词 `prompts/{en,zh}/{system,invoke_other}.md`。

## 7. audio_overview — 知识库双声播客（TurnCapability 流水线）

- 职责：从选中的知识库生成一段有引用支撑的双人语音概览 + 转写稿，走固定四阶段流水线，不是 chat loop 扩展。
- 入口：`deeptutor/capabilities/audio_overview/capability.py:21`（`AudioOverviewCapability(TurnCapability)`）；注册 `builtin_capabilities.py:47`（spec `:240`，含 CLI 别名 audio-overview/overview 与 config_defaults）；`run()` 在 `capability.py:38-130`。
- 关键机制：必须有知识库，否则用户可读报错（`capability.py:41-45`）；请求参数经 Pydantic 严格校验（`request_config.py:8-19`：topic ≤500、target_minutes 1–15、host/expert 声音、max_context_chunks 1–12，extra=forbid）；四阶段流式推进 `retrieving → script_writing → voice_generation → publishing`（`capability.py:76`、`:92`、`:100`、`:108`），每阶段发 sources/进度事件；最终经 `emit_capability_result` 产出转写、标题、引用、音频/转写文件名与 workspace 条目（`capability.py:116-130`）。
- 依赖：`AudioOverviewPipeline`（`pipeline.py:311`：`retrieve :339` / `generate_script :356` / `publish :399`，含音频封装与 workspace 产物落盘）、prompt manager 的 capabilities/audio_overview 提示、runtime workspace 输出目录。
- 文件锚点：manifest（阶段、tools_used、config_defaults）`capability.py:22-36`。

## 8. solve — Deep Solve（聊天循环即求解器）

- 职责：多步问题求解。没有 bespoke 流水线——chat 代理循环本身就是求解器；本目录提供确定性"脊椎"：先提交计划、每步完成门、有界重规划，推理仍由模型用共享内置工具完成（`deeptutor/capabilities/solve/capability.py:1-17` 的设计公理）。
- 入口（TurnCapability 半）：`capability.py:64`（`DeepSolveCapability`，manifest 名 `deep_solve`）；注册 `builtin_capabilities.py:38`（spec `:81`，CLI 别名 solve）；`run()` 打 `solve_mode` 标记、解析会话 id（`capability.py:48-61`）、读 solve 设置并启动 `AgenticChatPipeline`（`capability.py:74-93`）。
- 入口（Loop 扩展半）：`solve/loop.py:22`（`SolveLoopCapability`）；注册 `registry.py:55`；激活 `loop.py:34`，系统块注入求解 playbook（`loop.py:37`），复用完整 chat 工具面（web_search/reason/geogebra 等按用户开关挂载）再叠加三个 solve 工具。
- 关键机制：`SolveSession` 是单回合进程内状态（`session.py:39`：计划、每步 done 门、重规划预算，默认 2 次 `session.py:26`，步骤上限 12 `session.py:27`；有界字典防泄漏，会话 id 由管线服务端注入 `_solve_session_id`，模型不可自报）；`solve_finish_step` 发 `_context_checkpoint` 把已完成步骤的工具噪音折成一行摘要。
- 文件锚点：工具名与语义 `tools.py:15`（solve_plan/solve_finish_step/solve_replan）；会话存取 `session.py:83`（`get_session`）；提示词 `prompts/{en,zh}/system.md`。

## 9. 实例注册与装配机制（仅插入点索引）

两类实例、两条注册路径，实例目录本身都不自注册——注册表集中在框架层，实例只提供类：

1. **Loop 扩展（obsidian、course_study 循环半、explore_context、setup、partner_authoring、partner_group、solve 循环半）**
   - 每个实例是一个满足 `LoopExtension` 协议（`deeptutor/capabilities/protocol.py:38`：name/owned_tools/is_active/system_block/augment_kwargs/pre_loop_seed，可选 pre_loop、finish_instruction、tool_round_output_policy、final_text_override 等 getattr 缺省钩子）的类。
   - 内置清单：`registry.py:49-95` 的 `BUILTIN_LOOP_CAPABILITY_SPECS`（免导入描述符，`registry.py:27-46`；name 与类 `name` 不一致即抛 drift 错误，`registry.py:38-42`）。8 实例对应行：solve `:55`、obsidian `:56`、course_study `:70-73`、explore_context `:78-81`、setup `:82`、partner_authoring `:83-86`、partner_group `:87-90`。
   - 每回合装配：`registry.py:196`（`all_loop_capabilities`）逐个实例化并登记进 capability catalog（kind="loop_extension"，`registry.py:184-193`），`registry.py:210`（`active_loop_capabilities`）按 `is_active` 过滤；chat 管线在 `deeptutor/agents/loop/pipeline.py:798-799` 取活跃集合，并在 `:814-859` 折入工具挂载、系统块与 pre_loop 钩子。外部插件经 entry point 组 `deeptutor.extensions` 加入（`registry.py:21`、发现逻辑 `:152-181`）。
   - 独占语义：继承 `KnowledgeCapability`（`protocol.py:130`，`exclusive_tools=True`）即接管回合——8 实例中仅 obsidian。
2. **TurnCapability（audio_overview；solve 与 course_study 的模式半）**
   - 用户在 composer/CLI 可选的能力入口，清单同样是免导入描述符：`builtin_capabilities.py:36-48`（`BUILTIN_CAPABILITY_CLASSES`）+ `:50` 起的 `BUILTIN_CAPABILITY_SPECS`（manifest：阶段、tools_used、CLI 别名、config_defaults）。8 实例对应行：deep_solve `:38`/`:81`、course_study `:45`/`:211`、audio_overview `:47`/`:240`。
   - 运行时经 capability catalog 以 kind="turn" 创建（`deeptutor/runtime/registry/capability_registry.py:141`），由 CLI/API 按用户选择调度；其 `run(context, stream)` 自带阶段事件协议。
   - 模式 + 循环扩展的组合形态：course_study 与 solve 都是"TurnCapability 归一化 metadata 并启动 AgenticChatPipeline，Loop 扩展按该标记激活并叠加工具/提示"。模式半放行普通 chat 工具（保持调查能力），循环半收紧产品角色边界——两者职责分离是这两个目录最核心的读法。
3. 包出口：`deeptutor/capabilities/__init__.py:17-43` 对 registry 名称做惰性转发，chat loop 只 import 本包的协议与注册面，特性细节全部留在各子包内。
