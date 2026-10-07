# guide-scope claims.json 强度标注抽样复核报告（AGEN-1048，2026-10-07）

- 基线：HKUDS/DeepTutor `origin/main` @ `f07029cfc`（release v1.6.13；与 claims.json 自报基线一致，fetch 后未移动），全程只读
- 对象：`evidence/guide-scope-20261007/claims.json`（AGEN-1007 产物）中 67 张 guide 卡的认领强度标注（core/edge，kind=explicit/inferred）
- 输入：claims.json + 台账原文 `glm-reserve/reserve/backlog/`（deeptour.jsonl / deeptour.auto.jsonl / deeptour.0priority.jsonl，只读；未改台账）

## 抽样设计

- 67 卡中 19 卡仅 1–2 条认领，为满足"每张 ≥3 条认领被复核"：**认领数 ≥4 的卡全部纳入（6 张，普查）+ 3 认领卡随机抽 10 张（seed=1048）**，合计 16/67 张（24%），认领 56 条，每张 ≥3 条
- 样本（16）：guide-agents、guide-app-update、guide-ask-user、guide-book、guide-chat、guide-cli、guide-cowriter、guide-embedding、guide-events、guide-i18n、guide-logging、guide-network-validation、guide-task-board、guide-web-contracts、guide-web-guard-layers、guide-web-state
- 16 张卡的 src 行号与现行台账逐一比对全部对位（deeptour.auto.jsonl 未发生行移位）

## 判定口径

1. **路径核验**：canonical 路径（文件或目录）在 f07029cfc 文件树存在
2. **引文核验**：quote 与卡面原文逐字比对（省略号切分容差）；重切/重排=语义等价但非逐字；inferred 认领的 quote 含报告归位注记属口径设计
3. **强度判定**：core=卡的产物/目标明确指向该模块；edge=调用面/落点/衔接的附带提及（沿 AGEN-1007 自报口径，逐条回放卡面原文判"标对方向没有"）
4. **kind 判定**：explicit=模块可由卡面文字直接识别（含拼写/域词归位）；inferred=卡面未写该路径、由报告按仓库结构归位

## 抽检表（56 条逐条）

| 卡 | # | canonical 路径 | 强度 | kind | main | 引文 | 判定 | 依据 |
|---|---|---|---|---|---|---|---|---|
| guide-agents | 0 | `deeptutor/agents` | core | explicit | 在 | 逐字 | 符合 | 卡面目标句直指该目录，core=卡的产物对象 |
| guide-agents | 1 | `deeptutor/capabilities` | edge | explicit | 在 | 逐字 | 符合 | 输入节"相关：…capabilities 注册点"为附带提及，edge 恰当 |
| guide-agents | 2 | `tests/agents` | edge | explicit | 在 | 逐字 | 符合 | 输入节"相关"行测试面，edge 恰当 |
| guide-app-update | 0 | `deeptutor/services/app_update.py` | core | explicit | 在 | 逐字 | 符合 | 目标句三件套之首，状态机 JobStatus/UpdateJobStore 所在 |
| guide-app-update | 1 | `deeptutor/runtime/update_worker.py` | core | explicit | 在 | 重切/重排 | 符合(注) ▲ | 卡面为三路径并列共用"更新交接点"，逐路径复切语义等价 |
| guide-app-update | 2 | `deeptutor/runtime/launcher.py` | core | explicit | 在 | 重切/重排 | 符合(注) ▲ | 同上重切 |
| guide-app-update | 3 | `web/app/(settings)` | edge | explicit | 在 | 逐字 | 符合(注) ▲ | 卡面写"web 设置页版本展示"未写字面路径，路径为报告归位（域词 explicit 口径边缘）；落点 edge 恰当 |
| guide-ask-user | 0 | `deeptutor/tools/ask_user.py` | core | explicit | 在 | 逐字 | 符合 | tools/ask_user.py 发起段，全链路主线首环 |
| guide-ask-user | 1 | `deeptutor/services/session` | core | explicit | 在 | 逐字 | 符合 | waiting_input 状态机确证在 services/session（sqlite_store/pocketbase_store/turns/lifecycle） |
| guide-ask-user | 2 | `deeptutor/api/routers` | edge | explicit | 在 | 逐字 | 符合 | 链路第3段"API 事件下发"=下发落点；与 guide-chat 同模块构成 core×edge watch，与 CSV 一致 |
| guide-ask-user | 3 | `web/components/chat` | edge | explicit | 在 | 逐字 | 符合 | 链路第4段 web 渲染=前端落点 |
| guide-book | 0 | `deeptutor/book` | core | explicit | 在 | 逐字 | 符合 | 卡面目标句直指 deeptutor/book |
| guide-book | 1 | `tests/book` | edge | explicit | 在 | 逐字 | 符合(注) ▲ | edge 恰当；但引文计数漂移：卡面"26 个文件" vs main 27 |
| guide-book | 2 | `deeptutor/capabilities` | edge | explicit | 在 | 逐字 | 符合 | 输入节"capabilities 中 book 调用点"=附带衔接，edge 恰当 |
| guide-chat | 0 | `deeptutor/services/session/turns` | core | explicit | 在 | 逐字 | 符合 | turn 生命周期确证在 turns/lifecycle.py、executor.py；卡面已声明持久化轴去重给 guide-session |
| guide-chat | 1 | `deeptutor/api/routers` | core | explicit | 在 | 逐字 | 符合 | WS 传输与重连为列明主题2，api/routers 为承载面，core 恰当 |
| guide-chat | 2 | `deeptutor/tools/ask_user.py` | core | explicit | 在 | 逐字 | 符合 | ask_user 交互为列明主题3，core 恰当 |
| guide-chat | 3 | `web/components/chat` | edge | explicit | 在 | 逐字 | 符合 | 长会话渲染边界=前端落点，edge 恰当 |
| guide-chat | 4 | `deeptutor/agents/chat` | edge | inferred | 在 | inferred注记 | 符合(注) ▲ | 卡面未写路径，报告归位 deeptutor/agents/chat（agentic_pipeline/capability 在）；quote 含报告注记"（agents/chat 面）"属 inferred 口径设计；标题"Agent 运行时"若按 loop 编排理解可议 core，但目标四主题不含 loop，edge 恰当 |
| guide-cli | 0 | `deeptutor_cli` | core | explicit | 在 | 逐字 | 符合 | 目标句直指 deeptutor_cli |
| guide-cli | 1 | `deeptutor/runtime/launcher.py` | edge | explicit | 在 | 逐字 | 符合 | "init_cmd 与 runtime/launcher 关系"=衔接提及 |
| guide-cli | 2 | `deeptutor/services/config` | edge | explicit | 在 | 逐字 | 符合(注) ▲ | 卡面写"配置与环境变量"域词，路径为归位（域词 explicit 口径边缘）；CLI 配置面对比 guide-config 的体系卡，edge 恰当 |
| guide-cowriter | 0 | `deeptutor/co_writer` | core | explicit | 在 | 逐字 | 符合 | Co-Writer=deeptutor/co_writer 拼写归位，模块可识别 |
| guide-cowriter | 1 | `deeptutor/co_writer/docx_converter.py` | core | explicit | 在 | 逐字 | 符合 | docx 转换为列明子区 |
| guide-cowriter | 2 | `deeptutor/api/routers/co_writer.py` | core | explicit | 在 | 逐字 | 符合(注) ▲ | "路由"为列明子区；引文含覆盖率时点数字 246/40.0%，未按 main 复核（时点数据） |
| guide-embedding | 0 | `deeptutor/services/embedding` | core | explicit | 在 | 逐字 | 符合 | embedding client 为链路主线首环 |
| guide-embedding | 1 | `deeptutor/knowledge/progress_tracker.py` | core | explicit | 在 | 逐字 | 符合 | ProgressTracker 所在文件，进度链路主线 |
| guide-embedding | 2 | `deeptutor/api/routers` | edge | explicit | 在 | 逐字 | 符合 | 进度 WebSocket=下发落点，edge 恰当 |
| guide-events | 0 | `deeptutor/events` | core | explicit | 在 | 逐字 | 符合 | deeptutor/events/event_bus.py 在，事件总线为卡面主线 |
| guide-events | 1 | `deeptutor/api/routers` | edge | explicit | 在 | 逐字 | 符合 | WS 广播=广播落点，edge 恰当 |
| guide-events | 2 | `web/components/activity` | edge | explicit | 在 | 逐字 | 符合 | web/components/activity 在，前端衔接落点 |
| guide-i18n | 0 | `deeptutor/i18n` | core | explicit | 在 | 逐字 | 符合 | 后端 i18n 链路主线 |
| guide-i18n | 1 | `deeptutor/services/i18n.py` | core | explicit | 在 | 逐字 | 符合 | services/i18n.py 语言协商，主线 |
| guide-i18n | 2 | `web/i18n` | core | explicit | 在 | 逐字 | 符合 | web/i18n 为 Provider/Bridge/init 代码（I18nProvider 等），web 侧是验收明标"两套"之一，core 恰当 |
| guide-i18n | 3 | `web/locales` | edge | explicit | 在 | 逐字 | 符合 | web/locales 为键文件数据目录（de/en/fr/pl/uk），数据落点 edge 恰当 |
| guide-logging | 0 | `deeptutor/logging` | core | explicit | 在 | 逐字 | 符合 | deeptutor/logging 包（config/configure/formatters）在，日志约定主线 |
| guide-logging | 1 | `deeptutor/knowledge/progress_tracker.py` | core | explicit | 在 | 逐字 | 符合 | ProgressTracker 所在文件，进度观测主线 |
| guide-logging | 2 | `deeptutor/api/routers` | edge | explicit | 在 | 逐字 | 符合 | WebSocket=观测落点，edge 恰当 |
| guide-network-validation | 0 | `deeptutor/partners/network.py` | core | explicit | 在 | 逐字 | 符合 | validate_url_target 在 partners/network.py:59，三层之一 |
| guide-network-validation | 1 | `deeptutor/services/mcp/network.py` | core | explicit | 在 | 逐字 | 符合 | validate_mcp_url 在 services/mcp/network.py:69，三层之二 |
| guide-network-validation | 2 | `deeptutor/services/rag/linked_kb.py` | core | explicit | 在 | 逐字 | 符合 | allowed_link_roots 在 services/rag/linked_kb.py:75，三层之三；三层均为卡的直接对象，core 恰当 |
| guide-task-board | 0 | `deeptutor/services/task_board.py` | core | explicit | 在 | 逐字 | 符合 | 目标句直指 services/task_board.py |
| guide-task-board | 1 | `web/app/(workspace)/kanban` | core | explicit | 在 | 逐字 | 符合 | web 看板 kanban/page.tsx 在，列明对象 |
| guide-task-board | 2 | `web/lib/task-board-api.ts` | core | explicit | 在 | 逐字 | 符合 | web/lib/task-board-api.ts 在，列明对象 |
| guide-web-contracts | 0 | `web/contracts` | core | explicit | 在 | 逐字 | 符合 | web/contracts 为卡面直接对象 |
| guide-web-contracts | 1 | `web/scripts` | core | explicit | 在 | 逐字 | 符合 | web/scripts/generate-contracts.mjs 在，双向管线前端半区 |
| guide-web-contracts | 2 | `scripts/export_frontend_contracts.py` | core | explicit | 在 | 逐字 | 符合 | scripts/export_frontend_contracts.py 在，后端半区 |
| guide-web-contracts | 3 | `deeptutor/api/contracts` | core | inferred | 在 | inferred注记 | 符合(注) ▲ | 卡面未写路径；归位 deeptutor/api/contracts（export.py 即 schema 导出层）准确，quote 含注记属 inferred 口径设计 |
| guide-web-contracts | 4 | `web/lib/api.ts` | core | explicit | 在 | 逐字 | 符合(注) ▲ | detail.code 解析位点清单为列明产物，core 恰当；但见分歧1：web/lib/api.ts 为 deprecated shim，手写位点散在 mcp-api.ts:281、context/AppShellContext 等调用侧 |
| guide-web-guard-layers | 0 | `web/lib/api.ts` | core | explicit | 在 | 逐字 | 符合(注) ▲ | apiFetch 层 core 恰当；但见分歧1：apiFetch 实现在 web/shared/api/client.ts:28，web/lib/api.ts 仅为 6 行 deprecated 转出 |
| guide-web-guard-layers | 1 | `web/app` | core | explicit | 在 | 重切/重排 | 符合(注) ▲ | 词组均在卡面（五层句重排选摘）；页面守卫/导航可见性落在 web/app；五层之首"中间件认证门"实际在 web/proxy.ts+lib/proxy-policy.ts（web/app 之外，见分歧3） |
| guide-web-guard-layers | 2 | `deeptutor/multi_user` | edge | explicit | 在 | 逐字 | 符合 | learner 白名单面=叠加面，edge 恰当（与 guide-learner 构成 watch） |
| guide-web-state | 0 | `web/context` | core | explicit | 在 | 逐字 | 符合 | context 为状态组织三件套之首 |
| guide-web-state | 1 | `web/features` | core | explicit | 在 | 逐字 | 符合(注) ▲ | features/ 下 chat/co-writer/knowledge 等状态流确证；卡面"课程"状态流无 features/ 顶层目录，具体文件需导读时定位 |
| guide-web-state | 2 | `web/hooks` | core | explicit | 在 | 逐字 | 符合 | hooks 为三件套之一 |
| guide-web-state | 3 | `web/lib/api.ts` | edge | explicit | 在 | 逐字 | 符合(注) ▲ | 错误信封衔接=edge 恰当；实现现居 web/shared/api/errors.ts（ApiError:17），web/lib/api.ts 为 shim（见分歧1） |

## 统计

- 路径存在性：**56/56** 在 origin/main f07029cfc 可定位（0 失效）
- 引文忠实度：逐字 51；重切/重排 3（语义等价）；inferred 注记 2（口径设计内）
- 强度判定：**56/56 无方向性错误**（core 38 / edge 18；复核全部维持原标注）
- kind 判定：explicit 54 / inferred 2，无 inferred 误标；"域词/符号归位"记 explicit 共 7 条属口径边缘（见建议4）
- 共享模块跨卡一致性：web/lib/api.ts ×3（core/core/edge）、deeptutor/api/routers ×4（core/edge/edge/edge）、tools/ask_user.py ×2（core/core）、ProgressTracker ×2（core/core）——差异均能由各卡自身意图解释，口径自洽
- 全程本地 git/grep/ls 只读操作，无网络测试、无测试进程、未改产品代码与台账

## 分歧项汇总（修正建议，均不直接改台账）

1. **▲ web/lib/api.ts 已成 6 行 deprecated 转出 shim（本卡最主要发现）**：`web/lib/api.ts:1-6` 仅 `export * from "@/shared/api/client"` + `@/shared/api/errors`（注释标明 feature-client 迁移 Task 24 后移除）。样本内 3 条认领 canonical 键停在 shim：guide-web-guard-layers[0]（apiFetch 实现在 `web/shared/api/client.ts:28`）、guide-web-contracts[4]（detail.code 手写位点散在 `web/lib/mcp-api.ts:281`、`web/context/AppShellContext.tsx` 等调用侧，api.ts 内 0 命中）、guide-web-state[3]（错误信封在 `web/shared/api/errors.ts` ApiError:17）。建议：3 条认领补 canonical 注记或改键至 web/shared/api/*；overlap_matrix 中 web-contracts↔web-guard-layers 的 SUB 模块键同步更新；后续 guide-frontend 卡若认领 api.ts 同样处理。
2. **▲ guide-book[1] 引文计数漂移**：卡面/引文"tests/book 26 个文件" vs main 27（全为 test_*.py）。建议导读消费时按现行树更新计数；台账不改。
3. **"中间件认证门"锚点在 web/app 之外**：guide-web-guard-layers[1] 引文含五层之首，但 Next 16 的 proxy 约定使其落在 `web/proxy.ts` + `web/lib/proxy-policy.ts`（LOGIN_PATH/COOKIE_NAME/classifyToken/isAuthExempt），web/app 只承载页面守卫与导航可见性两层。建议导读落笔拆锚，或该认领加注。
4. **"域词/符号归位"建议加 canonical 标记**：7 条认领卡面只写域词/符号（"web 设置页""配置与环境变量""Co-Writer""routers/co_writer.py"无前缀、"apiFetch 401""detail.code""API 错误信封"），报告归位准确但与字面路径认领混同记 explicit。建议 claims 模板加 `canonical=true` 注记，消费侧可按需复核归位。
5. **inferred 认领的 quote 字段混入报告注记**：guide-chat[4] "（agents/chat 面）"、guide-web-contracts[3] "（schema 层）"。建议拆字段（quote_card / rationale_report），避免下游把注记当卡面原文引用。
6. **引文重切 3 处**（guide-app-update[1][2] 系列共述句逐路径复切、guide-web-guard-layers[1] 五层词组重排）：语义等价无歧义，建议模板要求逐字引用或标 [recut]。
7. **呈现小疵**：AGEN-1007 report.md A组 ask-user↔chat 行证据列引用了 watch 行（deeptutor/api/routers）引文；该对 SUB 证据实际在 services/session/turns（containment）与 tools/ask_user.py 两行（与 overlap_matrix.csv 一致，不影响实质对计数）。
8. **覆盖率数字为时点数据**：guide-cowriter[2] "246 缺失 / 40.0%" 未按 main 复核，沿用 verify-guide-anchors-20261006 结论：消费时加时点标注。

## 验收对照

1. ≥15 张、每张 ≥3 条：16 张、56 条，每张 3–5 条 ✓
2. 分歧项给修正建议、不改台账：8 条建议见上，台账文件零改动 ✓
3. 全程只读：main 工作区未动；本报告仅写入新 worktree 新分支 ✓

## 附：产物

- `report.md`（本文件）
- `SHA256SUMS`
