# Partners 服务层导读（deeptutor/services/partners 与 partner_groups）

- 基线：origin/main `f07029cfc`（v1.6.13）。所有 `path:line` 相对仓库根，行号随演进漂移，以符号名为准。
- 范围：`deeptutor/services/partners/**`（17 文件）+ `deeptutor/services/partner_groups/**`（7 文件），共 24 文件；以及它们与通道层的对接面。
- **边界声明（去重）**：通道层 `deeptutor/partners/bus/` 与 `deeptutor/partners/channels/`（以及 `deeptutor/partners/config/`）归 **guide-partners / guide-channels** 卡；本文只写服务层如何调用它们（§3），不展开任何 IM 实现内部。
- 上游在途：2026-10-07 复查，无改动这两个包的开放 PR（#1565 是 partner 会话漫游 feature、#1155 只修 AGENTS.md 路径）。

## 0. 一句话定位

服务层把"IM 连接的伙伴"落成进程内可运行对象：`services/partners` 负责**单个 Partner 的全生命周期**（配置/启动/会话/工作区/通道接入引导），`services/partner_groups` 负责**多 Partner 群聊编排**（组配置、发言模式、共享白板、跨伙伴调用审批）。两者都不自己实现 agent 循环—— Partner 复用产品聊天的 TurnEngine/ChatOrchestrator（`deeptutor/partners/__init__.py:6-8` 明确声明"no separate partner engine"）。

两层与通道层的职责切分见 `deeptutor/partners/__init__.py:1-9`：通道层 = 聊天平台集成 + 解耦用的消息总线 + 配置 schema；服务层 = agent 运行时（`services/partners/runtime.py:137` 的 `PartnerRunner` 消费总线并驱动 chat 能力）。

## 1. 模块地图 —— services/partners（单 Partner）

| 角色 | 文件 | 关键符号 / 说明 |
| --- | --- | --- |
| 包出口 | `services/partners/__init__.py:5-13` | 导出 `PartnerConfig/PartnerManager/PartnerRunner/PartnerSessionStore/get_partner_manager` 等 11 个符号 |
| 生命周期管理 | `services/partners/manager.py:482` | `PartnerManager`：进程内单例（`:1843` `get_partner_manager`），持有 `_partners` 字典；`start_partner` `:689`、`stop_partner` `:894`（手动停止清 auto_start，进程关停用 `preserve_auto_start=True` 保 intent）、`stop_all` `:1441`、`destroy_partner` `:1445`、`auto_start_partners` `:1425`（由 `api/main.py:188` 启动时调用、`api/main.py:193` 关停时 stop_all） |
| 配置模型 | `services/partners/manager.py:257` | `PartnerConfig` dataclass：`owner_id/workspace_id/channels/llm_selection/backup_llm_selection/enabled_tools/builtin_tools/mcp_tools` 等；`mcp_tools` 默认 `[]`（IM 侧不继承部署级 MCP，`:290-300` 注释了与用户授权相反的极性）；可合并字段白名单 `_MERGEABLE_FIELDS` `:565-581`（auto_start 故意不在内） |
| 运行实例 | `services/partners/manager.py:420` | `PartnerInstance`：config + runner + channel_manager + activity_feed + live_turns；`running` 属性看 tasks 存活（`:438`）；`to_dict` 三态脱敏 `:441-456`（names-only / mask / include_secrets），掩码实现 `mask_channel_secrets` `:150` |
| Web 实时轮次 | `services/partners/manager.py:304` | `LiveTurn`：轮次作为任务挂在实例上，帧进 per-subscriber 队列并缓冲，页面刷新后重连可 replay（`:305-313` docstring）；`start_web_turn` `:1280` 拒绝同 session 并发（文件锁 `_acquire_web_turn_lock` `:79`）；`PartnerActivityFeed` `:355` 按 actor 聚合外部 IM 轮次供 WebUI 订阅回放 |
| 入站消费/轮次执行 | `services/partners/runtime.py:137` | `PartnerRunner`：`run()` `:158` 常驻消费 `bus.consume_inbound()`，每消息一个 task、按 session 串行（`_lock_for` `:292`）；`process_message` `:300` 是所有入口（IM/Web/Group）的公共收敛点 |
| 轮次选项 | `services/partners/runtime.py:74` | `PartnerTurnOptions`：Group 编排注入公开转录、关双party持久化（`persist=False`）等；主模型失败后 backup 选择重试一次在 `_run_turn:399-414` |
| 上下文组装 | `services/partners/runtime.py:682` | `_build_context`：历史取自 session store 或 Group 注入、`agent_identity` 换掉产品身份（`:731`）、`partner_group` 元数据块 `:759-767`；工具门控 `_resolved_enabled_tools` `:837` / `_resolved_builtin_tools` `:860`；IM 投递开关 `_channel_delivery_flag` `:928` |
| 身份/范围 | `services/partners/interaction.py:35,:63` | `actor_for_account`（每轮从账号库重建身份，已删用户→None）、`personal_actor_id`（admin/伙伴自身→legacy 共享域）；`PartnerTurnContext` `:112` + contextvar `partner_turn_context` `:171` 让 memory 等工具读到"当前在和谁说话" |
| 会话持久化 | `services/partners/sessions.py:50` | `PartnerSessionStore`：append-only JSONL，每 session 一文件（`_stem` `:92` 经 `safe_filename` 防路径逃逸）；IM 群/单聊词汇归一 `conversation_scope` `:43`；`model_history` `:362` 按路由取 LLM 历史 |
| 每 actor 会话隔离 | `services/partners/interaction.py:76-103` | `session_sessions_dir`/`session_store_for`：已链接用户各自目录（`get_partner_user_sessions_dir`），未链接流量与 admin 落伙伴共享 `sessions/`；进程级 store 缓存保证写锁唯一（`:96-103`） |
| 账号链接 | `services/partners/links.py:114,:135,:164` | `/link <code>` 机制：`issue_link_code`/`redeem_link_code`/`linked_user_id`；状态存 `data/partners/<id>/channel_links.json`（`_path` `:53`），per-file 锁整文件重写（`:57-60` docstring `:1-10`） |
| IM 命令 | `services/partners/commands.py:77` | `PartnerCommandHandler.dispatch` `:91`：`/help /new /branch /sessions /resume /delete /status /model /history /tool /link`；`looks_like_partner_command` `:72` 快速短路；`runtime.py:319-329` 在进入 LLM 前拦截 |
| 工作区 | `services/partners/workspace.py:70` | `ensure_partner_workspace`（启动即建目录 + 缺省 Soul `manager.py:553-582`）；`read_soul/write_soul` `:101,:112`；资产供应 `provision_assets` `:121`（把 KB/技能/notebook 复制进伙伴工作区，`_copy_knowledge_base` `:180`、`_copy_skill` `:254`、`_copy_notebook` `:264`）；`list_assets/remove_asset` `:329,:375` |
| 工作区绑定 | `services/partners/workspace_binding.py:37` | `partner_content_context`：绑了 owner 的 content workspace 就以 owner 身份 + `data_activity()` 租约进 `workspace_context`（`:44-48`，防生成中途移库）；否则进伙伴私有合成 scope `:41-43`；`validate_partner_workspace` `:28` |
| 数据范围 | `services/partners/scope.py:19,:28,:37` | `partner_user_id`（`partner:<id>` 合成用户）、`partner_scope`、`partner_user`——伙伴私有 RAG/记忆目录的 scope 来源 |
| 模型解析 | `services/partners/model_runtime.py:12,:18` | `normalize_partner_llm_selection` / `resolve_partner_llm_config`（catalog 引用优先，遗留裸 `model` 字符串作 model-only 覆盖 `:31-37`） |
| 运行状态投影 | `services/partners/runtime_status.py:14` | `PartnerRuntimeStatusRepository`：WAL SQLite（`data/partners/_runtime/status.sqlite3`），leader 写、worker 读（`:15` docstring），`_publish_runtime_status`（`manager.py:494`）是唯一写方 |
| 渠道接入引导 | `services/partners/channel_onboarding.py:140` | `ChannelOnboardingManager`：飞书/企微扫码建应用，凭据只存进程内 session、显式 apply 才写配置（`:1-4` docstring）；单例 `:543` |
| 微信扫码登录 | `services/partners/weixin_onboarding.py:139,:171` | `start_login/poll_login`：把终端上的 QR 流程搬进 Web（`#951`），token 不出服务端、尝试短时效过期（`:7-14` docstring） |
| 草稿 | `services/partners/drafts.py:34,:55` | `PartnerDraft/PartnerDraftStore`：chat 引擎产出的伙伴档案草稿，与活配置隔离，用户显式 confirm 才成为真 Partner（`:1-4` docstring） |
| Web 会话连续性 | `services/partners/web_continuity.py:100,:106,:133` | 同账号多浏览器共享"活动会话"偏好；文件锁 `:27` 串行化跨 worker 读改写 |
| 遗留迁移 | `services/partners/manager.py:1488` / `services/partners/channel_state_migration.py:94` | `_migrate_legacy_tutorbot`（TutorBot→Partner）、`rehome_shared_channel_state`（按 channel 共享的通道状态一次性搬迁到 per-partner 目录，只复制不移动 `:21-22`，归属判定两条件 `:14-19`） |

## 2. 模块地图 —— services/partner_groups（群组编排）

| 角色 | 文件 | 关键符号 / 说明 |
| --- | --- | --- |
| 包出口 | `services/partner_groups/__init__.py:5-18` | 导出 `PartnerGroupManager/PartnerGroupConfig/PartnerInvocation/discussion_mode_registry/shared_memory_registry/get_partner_group_manager` |
| 编排器 | `services/partner_groups/manager.py:132` | `PartnerGroupManager`：无状态单例（`:1633` `get_partner_group_manager`，docstring"request context remains the security boundary"）；`__init__` 只持 store + 三个内存 dict（consultation/live/completed turns `:133-137`） |
| 组 CRUD | `services/partner_groups/manager.py:170,:209,:236` | `create_group`（成员校验 + mode/memory 类型校验 `:181-185`，id 冲突加 uuid 后缀 `:186-189`，owner 取当前用户 `:193`）、`update_group`、`delete_group` |
| 群轮次入口 | `services/partner_groups/manager.py:388` | `send_message`：归一 session、`resolve_mentions` `:404`（`:1197` 实现）定发言人集合 → 落用户消息 → 渲染公开上下文 `:431` → 闭包 `respond` `:441` 交给 discussion mode `:475-478` → `mode_emit` `:466` 在 partner_message 帧落 transcript → `GroupTurnResult` |
| 发言模式 | `services/partner_groups/modes.py:63,:83,:116` | `PanelParallelMode`（asyncio.gather 并行独立作答）、`SequentialMode`（按成员顺序接力，注入前文 `extra_context` + 不重复指令）、`DebateMode`（两轮：开篇并行 → 交锋并行；单人时跳过交锋 `:150-155`）；协议 `DiscussionMode` `:33`，注册表 `:181-184`，可插拔 |
| 落座执行 | `services/partner_groups/manager.py:1239` | `_run_partner_reply`：`get_partner_manager()` `:1260` → 懒启动 `:1268-1270` → `send_group_message` `:1286` → 把 `tool_metadata.partner_invocation` 提案转成 invocation 记录 `:1300-1308`；**单成员异常折叠为 error 消息不拖垮全场** `:1325-1337` |
| 跨伙伴调用 | `services/partner_groups/manager.py:267,:631,:835` | `create_invocation`（用户代提）、`approve_invocation`（批准后由被点名的伙伴在其自有轮里作答，`:725` `forward_trace` 转发 trace）、`reject_invocation`；提案仅是 proposal，批准权在编排器（`services/partners/manager.py:1223-1224` docstring 同义） |
| 轮次续作 | `services/partner_groups/manager.py:491,:564` | `summarize_round`（指定成员总结已完成轮，`:507` 校验轮完整性，`allow_invoke_other=False` `:545`）、`retry_partner`（重跑某成员该轮） |
| Web 实时 | `services/partner_groups/manager.py:857-1090` | `start_live_turn/start_live_invocation/start_live_retry/start_live_summary`：后台任务 + `LiveGroupTurn`（`:78`）缓冲帧；`subscribe_live_turn(s)` `:1092,:1098` 断线重连；`cancel_live_turn` `:1108` |
| 咨询窗口 | `services/partner_groups/consultation.py:12` | `ConsultationWindow`：输入法静默 10s（`IDLE_SECONDS :7`）+ 草稿租约 6s（`:8`）决定"用户是否打完字"，群聊不用逐字触发 |
| 持久化 | `services/partner_groups/store.py:54,:123,:309` | `PartnerGroupStore`（config.json，`root` `:56` = 当前用户根下 `partner_groups/`，**list/get/save 全程按 owner 过滤** `:61-74,:105-110`，id 白名单 `:99-102`）；`GroupTranscriptStore`（JSONL 转录 `:123`，`render` `:229` 有字符预算 `render_recent_lines :35`）；`PartnerInvocationStore` `:309` |
| 共享记忆 | `services/partner_groups/memory.py:24,:40,:72` | `GroupSharedMemory` 协议、`SharedMemoryRegistry`（validate 不落盘 `:49-52`）、唯一实现 `WhiteboardMemory`（append-only `shared/whiteboard.jsonl` `:84`，pin 去重 `:86-105`）；注册 `:196-197` |
| 数据模型 | `services/partner_groups/models.py:15,:34,:55,:85` | `PartnerGroupConfig`（member_ids/discussion_mode/shared_memory/version）、`GroupMessage`、`GroupTurnResult`、`PartnerInvocation`（requester/target/question/status） |

## 3. 与通道层（deeptutor/partners）的层间接口

服务层对通道层只有四个依赖点，全部单向（服务层 → 通道层；通道层反向引用服务层的唯一一处是 `partners/channels/telegram.py:28` 取 IM 帮助文案/命令面板）：

1. **消息总线 `MessageBus`**（`partners/bus/queue.py:9`）：每 Partner 一个实例（`manager.py:703-705`）。入站 `InboundMessage`（`partners/bus/events.py:11`，含 `session_key_override` 与可选 `actor`）由通道 listener 推入；服务层 `PartnerRunner.run`（`runtime.py:158`）消费。出站 `OutboundMessage`（`events.py:33`）由 `PartnerManager._outbound_router`（`manager.py:760`）独占消费——它是该伙伴**唯一出站车道**：流式 delta/progress 合并（复用通道层的 `coalesce_stream_deltas/coalesce_progress_messages`，`partners/channels/manager.py:46,:103`）、重试退避（`send_with_retry` `:155`）、慢车道告警、proactive 帧镜像进 activity_feed、再发全局 EventBus `CAPABILITY_COMPLETE`（`manager.py:857-880`）。`ChannelManager.start_all/_dispatch_outbound`（`channels/manager.py:343,:409`）是与 router 平行的旧派发路径，PartnerManager 只按通道调 `_start_channel`（`manager.py:742-749`），不启动它。
2. **`ChannelManager` 构造**：`_build_channel_manager`（`manager.py:929`）把 `config.channels` 包成 `ChannelsConfig`（`partners/config/schema.py`）后建 `ChannelManager`（`channels/manager.py:193`）；热更新走 `reload_channels`（`manager.py:955`）——只摘换 `partner:<id>:ch:*` 任务，runner/router 不动，失败落 `instance.last_reload_error`。通道构造期用 `constructing_for` contextvar 传 partner_id（`partners/channels/base.py:22-31`），通道状态目录 per-partner：`data/partners/<id>/channels/<channel>/`（`partners/config/paths.py:38-40`）。
3. **路径约定**：`partners/config/paths.py:11-17` 锚定 admin 工作区根下的 `data/partners/`（注释说明不能走 contextvar，否则伙伴合成 scope 会递归布局）；`get_partner_dir/get_partner_sessions_dir` 等是服务层数据树的事实来源。
4. **入站/出站数据契约**：`runtime.py:112-134` `_thread_delivery_meta` 把入站消息的 thread/reply 键回填出站；`_identify`（`runtime.py:271`）在入站侧用 `links.linked_user_id` 给已链接发信人挂身份，群聊刻意不归属（`:275-279`）。

## 4. 数据流（一条 IM 消息的一生）

1. 通道 listener → `bus.publish_inbound`（通道层职责）。
2. `PartnerRunner.run` `runtime.py:158` → `_handle_inbound` `:174`：先 `_identify`、镜像 `user_echo` 帧进 activity_feed（WebUI 能看到 IM 侧动静）。
3. `process_message` `:300`：session 锁串行 → 命令拦截 → `_run_turn` `:378`（主模型失败→backup `:399`）→ `_execute_turn` `:420`。
4. `_execute_turn`：`partner_content_context` 定数据域（绑定 workspace 或伙伴私有）→ `activate_llm_selection` → `build_partner_turn_context` + contextvar → `get_turn_engine().execute(context)` `:541` 消费 StreamEvent：CONTENT 聚帧/可选流式下发、TOOL_CALL 出 `⚙ tool(...)` 提示 `:93`、PROGRESS 处理 narration 轮折叠、RESULT 取终文。
5. `process_message` 按 `options.persist` 落 `PartnerSessionStore`（user/assistant 双 append，`runtime.py:342-375`），final 经 `_handle_inbound` `:246-254` 发回出站总线。
6. `_outbound_router`（`manager.py:760`）投递到通道；非 progress 消息镜像 activity_feed + EventBus。

Web 轮次不走总线：`send_message`（`manager.py:1165`）直接构造 `channel="web"` 的 `InboundMessage` 调 `runner.process_message`；`start_web_turn`（`:1280`）版本由 `LiveTurn` 托管使刷新可重连。

## 5. Group 轮次时序

`POST /{group_id}/messages`（`api/routers/partner_groups.py:220`）→ `PartnerGroupManager.send_message`（`manager.py:388`）→ mode.run（如 `PanelParallelMode` gather 全员）→ 每席 `_run_partner_reply` `:1239` → `PartnerManager.send_group_message`（`manager.py:1204`）：构造 `channel="web_group"` 消息，`PartnerTurnOptions(persist=False, allow_commands=False, shared_context=公开快照…)` `:1264-1274`——**每个成员私有推理，公开上下文只有 `_render_public_context`（`partner_groups/manager.py:1543`）渲染的花名册 + 转录 + 白板**。成员答案附带的 `partner_invocation` 工具提案在 `:1300` 转 invocation 记录，等人在 `:631/:835` 审批。

## 6. 关键文件速查（24 文件全列）

**services/partners/**：`manager.py`（生命周期+出站路由+配置）、`runtime.py`（轮次执行）、`sessions.py`（JSONL 会话）、`interaction.py`（身份/contextvar）、`commands.py`（IM 命令）、`links.py`（账号链接）、`scope.py`（合成 scope）、`workspace.py`（工作区/资产）、`workspace_binding.py`（owner 工作区绑定）、`model_runtime.py`（模型选择解析）、`runtime_status.py`（SQLite 运行态）、`channel_onboarding.py`（飞书/企微扫码）、`weixin_onboarding.py`（微信扫码）、`web_continuity.py`（多浏览器活动会话）、`drafts.py`（档案草稿）、`channel_state_migration.py`（通道状态搬迁）、`__init__.py`。
**services/partner_groups/**：`manager.py`（编排）、`modes.py`（发言模式）、`store.py`（组/转录/调用存储）、`memory.py`（白板）、`models.py`、`consultation.py`（静默窗）、`__init__.py`。

## 7. 扩展点与已知坑

1. **新讨论模式**：实现 `DiscussionMode` 协议（`modes.py:33-39`）并 `discussion_mode_registry.register`（`modes.py:181-184`）；群配置仅存字符串名（`models.py:21`），改名即破坏存量组。
2. **新共享记忆**：注册 `WhiteboardMemory` 同型类到 `shared_memory_registry`（`memory.py:196-197`）；`create_group` 先 validate 再落盘（`manager.py:185`）。
3. **新出站行为**：改 `_outbound_router` 而不是通道层（车道唯一）；合并/重试契约以通道层同名为准（`manager.py:773-777` 直接 import 通道层实现）。
4. **坑：出站车道单消费者**——任何旁路直接 `bus.consume_outbound()` 都会抢走 router 的消息（router 用 `try_consume_outbound` 窥探是安全的，`bus/queue.py:44`）。
5. **坑：auto_start 极性**——懒启动 web 聊天时 `save_config` 必须省略 auto_start（`manager.py:752-755`），否则静默改写用户意图；`_MERGEABLE_FIELDS` 也刻意不含它（`manager.py:565`）。
6. **坑：store 缓存与写锁**——`PartnerSessionStore` 按目录进程级缓存（`interaction.py:89-103`），绕开 `session_store_for` 自建实例会失去互斥；同理 `_STORES` 清理只随 `destroy_partner`（`interaction.py:104`）。
7. **坑：Group 成员可用性**——席位执行前双重校验 `cfg` 与 `can_use_partner`（`partner_groups/manager.py:1266`，授权逻辑在 `multi_user/partner_access.py:72`），成员被撤权时该席折叠为 error 消息而非失败整轮。
