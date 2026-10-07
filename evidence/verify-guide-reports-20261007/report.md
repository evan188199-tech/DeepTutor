# 复核：20261007 两份导读类报告结论（AGEN-1108）

- 复核对象：`evidence/guide-scope-20261007/`（AGEN-1007）、`evidence/review-guide-scope-merges-20261007/`（AGEN-1047），两份均只读
- 新基线：HKUDS/DeepTutor `origin/main` @ `f07029cfc`（v1.6.13，2026-10-04）——**与两报告原基线相同，上游未前进**
- 复核方式：`git fetch origin main` 后新建 worktree `verify/guide-reports-20261007` @ `f07029cfc`，只读 `git ls-tree`/`grep`/文件计数；台账 `glm-reserve/reserve/backlog/` 只读比对。未动 main 工作区，未改产品代码，未重生成对方报告
- 结论计数：逐条 **111 项 → 仍成立 98 / 已失效 13**。全部 13 项失效均源于台账演进（报告后新增 13 张 guide 卡），非 origin/main 代码演进

## 零、基线核验

| 项 | 结论 | 依据 |
| --- | --- | --- |
| R1/R2 基线 commit | 仍成立 | `git rev-parse origin/main` = `f07029cfcf2c8dfccdb671cdfc343db8334f5741`，即两报告记录的同一 commit |
| R1 基线差异备注（根目录 DEVELOPMENT_WORKFLOW.md、LOCAL_FEATURES.md 不在 origin/main；CONTAINERIZATION.md 在 docs-for-user/） | 仍成立 | 两文件在 worktree 根缺失；`docs-for-user/CONTAINERIZATION.md` 存在（12 文件） |
| R1 基线差异备注（本地 main 与 origin 分叉，origin 领先 736） | 仍成立 | `git rev-list main..origin/main --count` = 736（数字未变） |

## 一、报告一 guide-scope-20261007（AGEN-1007）逐条

### 1.1 基线与总量（3 条）

| # | 条目 | 结论 | 依据 |
| --- | --- | --- | --- |
| R1-1 | 总量表（guide-* 卡 67 / 模块键 102 / 簇 66 / 实质对 51 / 零声明对 41 / watch 137 / 真空 22） | **已失效（快照过时）** | 台账现为 **80 行 guide**（开放 78 + consumed 2）：报告后新增 13 卡、0 删除；绝对计数为 03:30 台账快照。注：51 对重叠对既有卡的判定本身仍成立（67 卡 title 67/67 未变、consumed 仍仅 mastery/reading），失效的是"当前总量" |
| R1-2 | 方法（67 卡全聚类含 consumed 2） | 仍成立 | claims.json `baseline.commit=f07029cfc`、`cards=67`；复核口径一致 |
| R1-3 | 未改台账声明 | 仍成立 | backlog 目录 mtime 与内容复核：仅新增行，67 张既有卡 title 无一变化 |

### 1.2 A 组实质重叠对（26 条，全部仍成立）

依据：各对涉及路径在现行 origin/main（=f07029cfc，同基线）全部存在；涉及卡均未被 consumed/删除，且关键去重声明文本逐一复核未变（guide-launcher→guide-app-update 单方声明仍在；guide-runtime 零声明仍在；guide-chat 对 ask-user 零声明仍在；guide-memory「只覆盖 memory」单方声明仍在；guide-session 仍含 Memory 且零声明）。

| # | 对 | 结论 | 依据 path（均核在） |
| --- | --- | --- | --- |
| R1-4 | app-update↔launcher | 仍成立 | deeptutor/runtime/launcher.py、deeptutor/services/app_update.py |
| R1-5 | app-update↔runtime | 仍成立 | 同上 + deeptutor/runtime/update_worker.py |
| R1-6 | launcher↔runtime | 仍成立 | deeptutor/runtime/launcher.py:1211/_terminate:254；update_worker.py:103 |
| R1-7 | cli↔launcher | 仍成立 | deeptutor_cli/ 存在 |
| R1-8 | ask-user↔chat | 仍成立 | deeptutor/tools/ask_user.py；services/session/sqlite_store.py:123、pocketbase_store.py:42 |
| R1-9 | ask-user↔session | 仍成立 | services/session/ask_user_trace.py（29 处 ask_user）、turns/executor.py |
| R1-10 | memory↔session | 仍成立 | services/memory/snapshot 5 文件、consolidator 27 文件 |
| R1-11 | chat↔session | 仍成立 | services/session/turns/ 存在 |
| R1-12 | session↔workspace-migration | 仍成立 | services/workspace/ 18 文件 |
| R1-13 | citation↔research | 仍成立 | agents/research/utils/citation_manager.py:83-84/:102/:106 |
| R1-14 | embedding↔logging | 仍成立 | knowledge/progress_tracker.py:71 |
| R1-15 | embedding↔knowledge | 仍成立 | knowledge/progress_tracker.py 存在 |
| R1-16 | mcp↔skills | 仍成立 | services/mcp/ 存在；network.py:69 validate_mcp_url |
| R1-17 | mcp↔network-validation | 仍成立 | services/mcp/network.py:69 validate_mcp_url |
| R1-18 | network-validation↔skills | 仍成立 | 同上 |
| R1-19 | learner↔multiuser | 仍成立 | multi_user/ 20 文件（identity/learner_profile/guardians/learning_access/book_access） |
| R1-20 | network-validation↔partners | 仍成立 | partners/network.py:59 validate_url_target |
| R1-21 | frontend↔web-state | 仍成立 | web/lib/api.ts、web/context/ 存在 |
| R1-22 | frontend↔web-contracts | 仍成立 | web/contracts/ 存在 |
| R1-23 | frontend↔web-guard-layers | 仍成立 | web/app/ 存在 |
| R1-24 | web-contracts↔web-guard-layers | 仍成立 | web/lib/api.ts |
| R1-25 | ask-user↔tools | 仍成立 | deeptutor/tools/ask_user.py |
| R1-26 | tools↔vision-tools | 仍成立 | deeptutor/tools/vision/ 存在 |
| R1-27 | ima-pipeline↔rag-pipelines | 仍成立 | services/rag/pipelines/ima/ 存在 |
| R1-28 | channels↔partners | 仍成立 | deeptutor/partners/channels/ 存在 |
| R1-29 | deploy↔packaging | 仍成立 | compose.yaml、docker-compose.dev.yml、Dockerfile、Dockerfile.runner、MANIFEST.in 均在 |

### 1.3 A 组 watch 牵连对（11 条，全部仍成立）

| # | 对 | 结论 | 依据 |
| --- | --- | --- | --- |
| R1-30~40 | quiz↔mastery、authn↔multiuser、embedding↔events、events↔logging、knowledge↔rag-pipelines、embedding↔rag-pipelines、ima-pipeline↔knowledge、video-learning↔watching、learner↔web-guard-layers、skills↔tools、config↔partners | 全部仍成立 | 各对卡片均在台账且 title 未变；quiz/mastery 卡仍互零声明（复核描述原文）；guide-logging 仍单方声明 guide-events 并保留「进度上报链路（ProgressTracker/WebSocket）」认领；相关路径 knowledge/progress_tracker.py:71、capabilities/mastery/tools.py:95、events/event_bus.py 等均核在 |

### 1.4 B 组全景↔专卡对（25 条，全部仍成立）

| # | 对 | 结论 | 依据 path（均核在） |
| --- | --- | --- | --- |
| R1-41 | agents↔citation | 仍成立 | deeptutor/agents/research/utils/citation_manager.py |
| R1-42 | agents↔notebook | 仍成立 | deeptutor/agents/notebook（8 文件） |
| R1-43 | agents↔question | 仍成立 | deeptutor/agents/question（17 文件） |
| R1-44 | agents↔research | 仍成立 | deeptutor/agents/research（11 文件） |
| R1-45 | capabilities↔marginnote-contract | 仍成立 | deeptutor/capabilities/marginnote4 |
| R1-46 | capabilities↔watching | 仍成立 | deeptutor/capabilities/watching |
| R1-47 | chat↔cowriter | 仍成立 | deeptutor/api/routers/co_writer.py |
| R1-48 | chat↔marginnote-contract | 仍成立 | deeptutor/api/routers/marginnote4.py |
| R1-49 | chat↔question | 仍成立 | deeptutor/api/routers/question.py |
| R1-50 | chat↔quiz | 仍成立 | deeptutor/api/routers/quiz_judge.py:227 |
| R1-51 | chat↔routers | 仍成立 | deeptutor/api/routers（45 文件）；unified_ws.py:44 |
| R1-52 | chat↔tools | 仍成立 | deeptutor/tools/ask_user.py |
| R1-53 | cowriter↔routers | 仍成立 | deeptutor/api/routers/co_writer.py |
| R1-54 | frontend↔i18n | 仍成立 | web/i18n 5 文件、web/locales 10 文件 |
| R1-55 | frontend↔task-board | 仍成立 | web/app/(workspace)/kanban、web/lib/task-board-api.ts |
| R1-56 | frontend↔testing | 仍成立 | web/tests 350 文件 |
| R1-57 | frontend↔visualize | 仍成立 | web/components/visualize |
| R1-58 | frontend↔watching | 仍成立 | web/components/watching |
| R1-59 | knowledge↔logging | 仍成立 | deeptutor/knowledge/progress_tracker.py |
| R1-60 | marginnote-contract↔routers | 仍成立 | deeptutor/api/routers/marginnote4.py |
| R1-61 | question↔routers | 仍成立 | deeptutor/api/routers/question.py |
| R1-62 | quiz↔routers | 仍成立 | deeptutor/api/routers/quiz_judge.py |
| R1-63 | task-board↔web-guard-layers | 仍成立 | web/app/(workspace)/kanban |
| R1-64 | agents↔math-animator | 仍成立 | deeptutor/agents/math_animator 存在；卡面显式去重 guide-agents 的声明仍在（台账复核） |
| R1-65 | capabilities↔mastery | 仍成立 | deeptutor/capabilities/mastery、services/session/turns 存在 |

### 1.5 真空清单（22 条 + 弱覆盖 2 条：16 仍成立 / 6 已失效）

失效原因统一为：**对应真空已按报告建议开卡认领（台账新增）**，repo 侧文件面均未变化。

| # | 真空域 | 结论 | 依据 |
| --- | --- | --- | --- |
| R1-66 | deeptutor/learning（46 文件） | **已失效（已开 guide-learning-domain）** | 台账新增行 guide-learning-domain；worktree deeptutor/learning 仍 46 文件 |
| R1-67 | services/llm 非 provider_core（约 30） | **已失效（已开 guide-llm-clients）** | 台账新增行 guide-llm-clients；顶层 30 + provider_core 13 不变 |
| R1-68 | capabilities 实例 ×8 零认领 | **已失效（已开 guide-capability-instances + guide-audio-overview）** | 16 实例目录/102 文件不变；台账新增两行 |
| R1-69 | runtime 子包（agentic/coordination/registry/providers/bootstrap） | **已失效（已开 guide-runtime-subpackages）** | 子包实测 11+8+5+6+2=32 文件（报告"约 30"吻合）；台账新增行 |
| R1-70 | tools/prompting（55 文件） | **已失效（已开 guide-tools-prompting）** | 实测 55 不变；台账新增行 |
| R1-71 | services/partners + partner_groups（24） | **已失效（已开 guide-services-partners）** | 实测 17+7=24 不变；台账新增行 |
| R1-72 | services/codex_auth（8） | 仍成立 | 8 文件不变；无新卡认领 |
| R1-73 | services/github_source + web_source（15） | 仍成立 | 4+11=15 不变；无新卡 |
| R1-74 | services/imagegen + videogen（13） | 仍成立 | 7+6=13 不变；无新卡 |
| R1-75 | services/persona（5） | 仍成立 | 5 不变；无新卡 |
| R1-76 | services/prompt + skill + setup（13） | 仍成立 | 4+6+3=13 不变；guide-skills 仍认 deeptutor/skills |
| R1-77 | services/cli_apps（10） | 仍成立 | 10 不变；无新卡 |
| R1-78 | services/model_selection（5） | 仍成立 | 5 不变；无新卡 |
| R1-79 | services/settings（6） | 仍成立 | 6 不变；无新卡 |
| R1-80 | services/search 非 providers（5） | 仍成立 | 顶层 5 不变；无新卡 |
| R1-81 | services/rag 顶层（14） | 仍成立 | 14 不变；无新卡 |
| R1-82 | deeptutor/utils（11） | 仍成立 | 11 不变；无新卡 |
| R1-83 | deeptutor/app（6） | 仍成立 | 6 不变；无新卡 |
| R1-84 | deeptutor/visualizers（8） | 仍成立 | 8 不变；无新卡 |
| R1-85 | core/assessment.py + response_languages.py（2） | 仍成立 | 两文件均存在；core-protocols 卡仍未点名 |
| R1-86 | scripts/（18） | 仍成立 | 18 不变；无新卡 |
| R1-87 | docs-for-user/（12） | 仍成立 | 12 不变；无新卡 |
| R1-88 | 弱覆盖 services/workspace | 仍成立 | 18 文件；仍仅边缘提及 |
| R1-89 | 弱覆盖 agents/vision_solver | 仍成立 | 3 文件；仍仅 guide-agents 全景覆盖 |

### 1.6 边界修订建议（14 条：8 仍成立 / 6 已失效）

| # | 建议 | 结论 | 依据 |
| --- | --- | --- | --- |
| R1-90 | 合并 launcher 三件套 | 仍成立（未执行） | 三卡均在、重叠前提未变（见 R1-4~6） |
| R1-91 | 合并 ask-user 轴 | 仍成立（未执行） | guide-ask-user/guide-chat 均在；chat 仍零声明 |
| R1-92 | 合并 memory↔session | 仍成立（未执行） | 两卡均在；session 仍认领 Memory |
| R1-93 | 划界 全景卡族 | 仍成立（未执行） | 六张全景卡 + guard-layers 卡面仍零去重声明 |
| R1-94 | 划界 citation↔research | 仍成立（未执行） | 两卡 core 认领不变 |
| R1-95 | 划界 quiz↔mastery | 仍成立（未执行） | 两卡互零声明复核仍在 |
| R1-96 | 划界 learner↔multiuser | 仍成立（未执行） | multiuser 卡仍含监护人/学习者措辞，learner 卡零声明 |
| R1-97 | 划界 进度三角 | 仍成立（未执行） | logging 卡仍认领「进度上报链路（ProgressTracker/WebSocket）」，仅对 events 单方声明 |
| R1-98 | 新增 guide-learning-domain | **已失效（已落地）** | 台账已存在同名卡 |
| R1-99 | 新增 guide-capability-instances | **已失效（已落地）** | 同上 |
| R1-100 | 新增 guide-llm-clients | **已失效（已落地）** | 同上 |
| R1-101 | 新增 guide-runtime-subpackages | **已失效（已落地）** | 同上 |
| R1-102 | 新增 guide-tools-prompting | **已失效（已落地）** | 同上 |
| R1-103 | 新增 guide-services-partners | **已失效（已落地）** | 同上 |

## 二、报告二 review-guide-scope-merges-20261007（AGEN-1047）逐组

核验基线与原报告相同（f07029cfc 未动），全部行锚点逐一复测命中；8 组结论 **8 仍成立 / 0 已失效**。原"4 同意 + 4 同意（带修改）+ 0 驳回"的汇总维持。

| # | 组 | 结论 | 行锚点复测（path:line 实测） |
| --- | --- | --- | --- |
| R2-1 | 合并 launcher 三件套 → 同意 | 仍成立 | launcher.py `_handoff_pending_update`:1211（调用点:1572）、`_terminate`:254；update_worker.py `run_update_worker`:103；app_update.py VersionCheckResult:76、UpdateJob:88。guide-runtime 零声明、guide-launcher 单方声明均复核仍在 → 三卡重叠前提不变 |
| R2-2 | 合并 ask-user 轴 → 同意（chat 降引用） | 仍成立 | tools/ask_user.py 在；sqlite_store.py:123、pocketbase_store.py:42 `waiting_input`；ask_user_trace.py（29 处 ask_user）、turns/executor.py 引用 ask_user。chat 卡仍 core 认领 ask_user 且零声明 |
| R2-3 | 合并 memory↔session → 同意 | 仍成立 | snapshot 5 文件、consolidator 27 文件不变；memory 卡「只覆盖 memory」声明仍在；session 卡仍含 Memory 零声明 → 仅需 session 卡删字的前提不变 |
| R2-4 | 划界 全景卡族 → 同意（计数修正） | 仍成立 | api/routers 45、agents/notebook 8、question 17、research 11、web/i18n 5、locales 10、web/tests 350 全中；kanban 与 task-board-api.ts 在；unified_ws.py:44 `unified_websocket`、quiz_judge.py:227 WS 复测命中；claims.json 复核 routers core 专卡确为 4（co_writer/marginnote4/question/quiz_judge）+ edge 含 practice → 修改点仍准确 |
| R2-5 | 划界 citation↔research → 同意 | 仍成立 | citation_manager.py:83 `PLAN-XX format`、:84 `CIT-X-XX format`、:102 `return f"PLAN-…"`、:106 CIT-X-XX 格式；章节切分与文件结构吻合 |
| R2-6 | 划界 quiz↔mastery → 同意（写回归 learning） | 仍成立 | quiz_judge.py:227；capabilities/mastery/tools.py:95 MASTERY_TOOL_NAMES 注册 `mastery_quiz`、:121 `_new_service()`→LearningService；learning/grading.py:13 `grade_answer`、:52 `classify_error`；learning/service.py:357 `quiz_attempts` 写回落点。修改点不变；原文"待 guide-learning-domain"注记中的域卡现已落地（guide-learning-domain 已开卡），结论反而更强 |
| R2-7 | 划界 learner↔multiuser → 同意（双边各让） | 仍成立 | multi_user/ 20 文件；identity.py:44 `new_user_id`、:101/:119/:205 `_write_users`、:106/:186 `_migrate_legacy_users`；learner_profile/guardians/learning_access/book_access 均在。multiuser 卡文仍含监护人授权措辞、learner 卡仍零声明 → 双边各让的前提不变 |
| R2-8 | 划界 进度三角 → 同意（logging 同步删认领） | 仍成立 | knowledge/progress_tracker.py:71 `class ProgressTracker`；events/event_bus.py 在；deeptutor/logging 11 文件（config/formatters/context/llm_stats 面）。logging 卡仍写「进度上报链路（ProgressTracker/WebSocket）」且仅对 events 单方去重 → 同步删认领的修改点仍必要 |

## 三、失效清单汇总（13 项）

| 项 | 原因 |
| --- | --- |
| R1-1 总量表 | 台账快照过时（67 → 80 行 guide，新增 13 卡） |
| R1-66~71 真空 #1~#6 | 对应域已开卡认领（learning-domain / llm-clients / capability-instances+audio-overview / runtime-subpackages / tools-prompting / services-partners） |
| R1-98~103 新增建议 6 条 | 全部已落地开卡 |

报告后台账另新增 guide-ci-workflows、guide-realtime-push、guide-session-stores、guide-session-turns、guide-web-activity、guide-upstream-contrib 六卡（非本报告建议产物，属其他轴）；对 A/B 组既有重叠对结论无影响（既有 67 卡卡面未变）。

## 验收对照

1. 两报告条目逐条给结论与依据 path:line：报告一 103 条（R1-1~R1-103）+ 报告二 8 条（R2-1~R2-8）= 111 条；计数 **仍成立 98 / 已失效 13**。
2. 只读：仅 fetch + 新 worktree 检出 f07029cfc；未改产品代码，未重生成对方报告，台账零写入。
3. 只推本卡新分支：`verify/guide-reports-20261007`（evidence/verify-guide-reports-20261007/）。
