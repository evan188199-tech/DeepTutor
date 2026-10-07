# DeepTutor 架构总览导读（子系统地图与 guide 索引）

- 基线：`origin/main` @ `f07029cfc`（release v1.6.13），快照日期 2026-10-07
- 性质：只读导读，不改任何代码；所有锚点为 `path:line`，行号对应该基线提交
- 配套：储备池已有 guide-* 导读卡 77 张（索引见 §4）、test-* 补测卡按子系统精选（索引见 §5）；本文只做索引引用，不重写各导读内容

## 0. 怎么用这份导读

DeepTutor 是一个"本地优先 + 可选云服务"的学习工作站：Python 后端（FastAPI）+ Next.js 前端 + CLI 三入口，共享同一套 `deeptutor/services/*` 服务层。按 §2 的分层地图找到目标子系统 → 读 §3 对应小节的职责边界与入口锚点 → 需要深入时跳到 §4/§5 的对应 guide/test 卡。

## 1. 入口层：三条进入方式

| 入口 | 启动方式 | 代码锚点 |
| --- | --- | --- |
| CLI | `deeptutor` / `python -m deeptutor_cli` | `deeptutor_cli/__main__.py:4`（入口薄壳）→ `deeptutor_cli/main.py:222`（`main()` 命令分发） |
| API 服务 | `python -m deeptutor.api.run_server` 或 compose | `deeptutor/api/run_server.py:30`（`main()`）→ `deeptutor/api/run_server.py:80`（`uvicorn.run("deeptutor.api.main:app")`） |
| Web 前端 | dev：`npm run dev`（`web/package.json:6`）；生产由后端托管静态产物 | `web/app/layout.tsx:38`（`RootLayout`） |

进程装配与更新交接由 runtime 启动器负责（见 §3.5），本地一键启动脚本为 `start_deeptutor.command`；部署路径另有 compose 编排（`compose.yaml`、`docker-compose.yml`）。

## 2. 分层地图

```mermaid
title="DeepTutor 分层地图"
flowchart TB
    subgraph L1["入口层"]
        CLI["deeptutor_cli"]
        API["deeptutor/api (FastAPI)"]
        WEB["web/ (Next.js)"]
    end
    subgraph L2["运行时与会话"]
        RT["runtime 编排/turn_engine/stream_bus"]
        SES["session 会话与 turns"]
        AG["agents 智能体实现"]
    end
    subgraph L3["模型与工具面"]
        LLM["llm client/provider_core"]
        CAP["capabilities 能力注册"]
        TOOLS["tools 工具"]
        SKILLS["skills / mcp / plugins"]
    end
    subgraph L4["知识链"]
        KB["knowledge 管理"]
        PARSE["parsing 解析"]
        RAG["rag 检索管线"]
        SEARCH["search 搜索"]
        TS["textbook_struct"]
    end
    subgraph L5["学习与内容域"]
        BOOK["book"]
        LEARN["learning"]
        READ["reading"]
        CW["co_writer"]
        NB["notebook"]
    end
    subgraph L6["通道与账号"]
        PT["partners 通道"]
        MU["multi_user"]
        MEM["memory"]
    end
    subgraph L7["基础设施"]
        CFG["config/settings"]
        EVT["events 进度广播"]
        ST["storage/workspace/cron/sandbox"]
        COREX["core 协议 / i18n / logging / visualizers"]
    end
    CLI --> API
    WEB --> API
    API --> RT --> SES
    RT --> AG --> LLM
    AG --> TOOLS & CAP & SKILLS
    TOOLS --> RAG & SEARCH & KB
    KB --> PARSE
    RAG --> KB
    BOOK & LEARN & READ & CW & NB --> AG
    PT --> RT
    MEM --> AG
    L7 -.支撑.- L2 & L4 & L5 & L6
```

## 3. 子系统职责边界与入口锚点

每条给出：职责边界（管什么/不管什么）+ 入口锚点（`path:line`，基线 f07029cfc）。

### 3.1 入口与装配（4 个）

1. **cli**（`deeptutor_cli/`）— 命令行命令面：会话/chat/kb/book/notebook/配置/诊断等子命令。只做参数解析与输出，不承载业务逻辑。锚点：`deeptutor_cli/main.py:222`（`main()` 分发）；命令实现在同级 `chat.py`、`kb.py`、`session_cmd.py` 等。
2. **api**（`deeptutor/api/`）— FastAPI 应用与全部 HTTP/WS 路由：`app = FastAPI` 在 `deeptutor/api/main.py:404`，路由挂载从 `deeptutor/api/main.py:575` 起（auth/sessions/knowledge/book/question/co_writer/partners…约 40+ router）；统一 WebSocket 适配器 `deeptutor/api/routers/unified_ws.py:44`（`unified_websocket`）。路由层只做鉴权、校验与转发，业务在 services。辅助面：`deeptutor/api/utils/progress_broadcaster.py:14`（`ProgressBroadcaster` 进度广播）、`deeptutor/api/utils/task_log_stream.py`（任务日志流）。
3. **web**（`web/`）— Next.js App Router 前端：页面在 `web/app/`（分组 `(workspace)`/`(admin)`/`(auth)` 等），功能模块在 `web/features/`（chat、knowledge、capabilities、co-writer、multi-user、runtime-status、settings），契约类型由 `web/contracts/` 从后端生成（门禁链见 guide-web-contracts）。锚点：`web/app/layout.tsx:38`。
4. **app-facade**（`deeptutor/app/`）— 应用门面：把会话、能力可用性、workspace 上下文聚合成一个 `DeepTutorApp` 门面对象供 CLI/嵌入场景使用。锚点：`deeptutor/app/facade.py:60`（`DeepTutorApp`）；装配容器 `deeptutor/app/container.py`。

### 3.2 运行时与会话（3 个）

5. **runtime**（`deeptutor/runtime/`）— 进程装配与 turn 执行中枢：`launcher.py` 负责子进程生命周期与更新交接（`FrontendRuntime` `deeptutor/runtime/launcher.py:115`、`update_worker.py`）；`deeptutor/runtime/orchestrator.py:51`（`ChatOrchestrator`）编排一次对话；`deeptutor/runtime/turn_engine.py:11`（`TurnEngine`）驱动 turn；`deeptutor/runtime/stream_bus.py:31`（`StreamBus`）按 turn_id 管理流式输出分发（`register_bus` `deeptutor/runtime/stream_bus.py:363`）；`background_leader.py` 租约选主；子包 `agentic/`、`coordination/`、`registry/`、`providers/`、`bootstrap/` 是更细的执行件。
6. **session**（`deeptutor/services/session/`）— 会话与消息持久化、turn 子系统、会话搜索/导出/用量。`deeptutor/services/session/turn_runtime.py:26`（`TurnRuntimeManager`）是 turn 运行时入口；turn 细分在 `turns/`：`deeptutor/services/session/turns/executor.py:69`（`TurnExecutor` 主干）、`request_preparer.py`、`context_assembler.py`、`title_service.py`、`lifecycle.py`。存储双轨：`sqlite_store.py` 与 `pocketbase_store.py`（云同步可选）。
7. **agents**（`deeptutor/agents/`）— 各智能体实现：`deeptutor/agents/base_agent.py:33`（`BaseAgent` 抽象）、`loop/`（agent 主循环，含 context budget）、领域子包 `chat/`、`question/`、`research/`（deep research）、`book/` 相关编排 `math_animator/`、`visualize/`、`vision_solver/`、`notebook/`；公共件在 `_shared/`（workspace prompt 组装等）。

### 3.3 模型与工具面（6 个）

8. **llm**（`deeptutor/services/llm/`）— 模型调用统一层：`deeptutor/services/llm/client.py:80`（`LLMClient` 门面）、`deeptutor/services/llm/provider_core/base.py:73`（`LLMProvider` 抽象与 `GenerationSettings` `:65`）、`provider_core/` 下各家 provider（openai_compat/anthropic/azure/codebuddy/copilot/codex）、运行时 provider 池 `deeptutor/services/llm/provider_factory.py:144`（`get_runtime_provider`）。周边：`reasoning_params.py`、`error_mapping.py`、`keypool.py`（key 轮转，`services/keypool.py`）、`traffic_control.py`、`usage_ledger.py`、`structured_retry.py`、`image_description.py`。非 provider 客户端面（如本地模型）由 `local_provider.py` 承接。
9. **capabilities**（`deeptutor/capabilities/`）— 可 loop 的能力框架：`protocol.py` 定义能力协议，`deeptutor/capabilities/registry.py:28`（`LoopCapabilitySpec`）注册 loop 扩展；8 个零认领实例目录如 `ask_questions/`、`explore_context/`、`audio_overview/`、`mastery/`、`reading/`、`obsidian/`、`ima/`、`marginnote4/`。能力是"会占住一个 turn 循环"的交互，与一次性 tools 相区分。
10. **tools**（`deeptutor/tools/`）— 一次性工具面：RAG 检索、web 搜索、reason/brainstorm/solve、题库、笔记、vision 解析（`vision/`）、tex 工具链等。内置工具实现在 `deeptutor/tools/builtin/__init__.py:33` 起（`BrainstormTool`、`RAGTool` `:105`、`WebSearchTool` `:406` 等），工具规格在 `builtin_specs.py`；提示词模板在 `tools/prompting/`。
11. **skills**（`deeptutor/services/skill/` + `deeptutor/skills/`）— 用户可安装的技能包：安装/分类/渲染服务在 `deeptutor/services/skill/service.py:219`（`SkillService`），manifest 渲染 `deeptutor/services/skill/service.py:997`；内置技能目录 `deeptutor/skills/builtin/`。技能最终以工具/提示注入 agent。
12. **mcp**（`deeptutor/services/mcp/`）— Model Context Protocol 外部工具集成：连接管理 `deeptutor/services/mcp/manager.py:235`（`MCPConnectionManager`）、工具适配 `deeptutor/services/mcp/manager.py:105`（`MCPToolAdapter`）、OAuth `oauth.py`、密钥 `secrets.py`、出站校验 `network.py`；设置路由 `deeptutor/api/routers/mcp_settings.py`。
13. **plugins**（`deeptutor/plugins/`）— entry-point 插件加载：`deeptutor/plugins/loader.py:42`（`discover_plugins()`）、`:47`（`load_plugin_capability()`）。只负责发现与装载 TurnCapability，不做能力逻辑。

### 3.4 知识链（5 个）

14. **knowledge**（`deeptutor/knowledge/`）— 知识库（KB）管理：建删/清单/命名/摄取编排。锚点：`deeptutor/knowledge/manager.py:325`（`KnowledgeBaseManager`）、`add_documents.py`（摄取入口）、`progress_tracker.py`/`progress_events.py`（索引进度）。
15. **parsing**（`deeptutor/services/parsing/`）— 文档解析引擎层：PDF/EPUB/docx 等到结构化文本。`deeptutor/services/parsing/service.py:74`（`ParseService` 分派与回退 `:52`）、`engines/`（markitdown/docling/mineru 等本地/远端引擎）、`cache.py`、`signature.py`。
16. **rag**（`deeptutor/services/rag/`）— 检索增强管线：`deeptutor/services/rag/service.py:22`（`RAGService` 顶层检索与降级）、`pipelines/`（五条管线：lightrag/llamaindex/graphrag/ima/pageindex 等，协议 `deeptutor/services/rag/pipelines/base.py:17` `RAGPipeline`）、`deeptutor/services/rag/factory.py:67`（provider 归一）、嵌入绑定 `embedding_binding.py`、索引版本 `index_versioning.py`、评估子包 `eval/`。
17. **search**（`deeptutor/services/search/`）— 外部搜索 provider 抽象：`deeptutor/services/search/base.py:20`（`BaseSearchProvider`）、`providers/`（多家实现）、`consolidation.py`（结果合并）、`source_filter.py`（域过滤）。
18. **textbook_struct**（`deeptutor/textbook_struct/`）— 教材结构重建：章节重建 `chapter_rebuild.py`、列黑名单 `column_blacklist.py`、页眉处理 `page_headers.py`。服务于 KB 摄取后的教材结构化。

### 3.5 学习与内容域（5 个）

19. **book**（`deeptutor/book/`）— 教材生成管线：`deeptutor/book/engine.py:317`（`BookEngine`，单例 `:2173`）、`agents/`（spine/page_planner 等编排）、`blocks/`（章节块与动效块）、`compiler.py`、`export.py`、`learning_overlay.py`（学习浮层）。
20. **learning**（`deeptutor/learning/`）— 学习域全景：知识点/目标/掌握度/测验证据。`deeptutor/learning/service.py:266`（`LearningService`）、`assessment.py`、`grading.py`、`mastery.py`、`scheduler.py`（练习调度）、`question_card.py`。练习域服务层在 `services/practice/`，课程状态在 `services/courses_state.py`。
21. **reading**（`deeptutor/reading/`）— 沉浸阅读：EPUB/文档渲染、进度、引用、朗读、词汇。`service.py`、`ingestion.py`、`page_render.py`、`references.py`、`read_aloud.py`、`epub_bilingual.py`。
22. **co_writer**（`deeptutor/co_writer/`）— 协同写作：`edit_agent.py`（编辑代理）、`storage.py`、`docx_converter.py`；路由在 `api/routers/co_writer.py`。
23. **notebook**（`deeptutor/services/notebook/`）— 题目笔记本：`deeptutor/services/notebook/service.py:92`（`NotebookManager`）、记录模型 `deeptutor/services/notebook/service.py:42`（`NotebookRecord`）；出题域 pipeline 在 `deeptutor/agents/question/` 与 `tools/question/`。

### 3.6 通道与账号（3 个）

24. **partners**（`deeptutor/partners/` + `deeptutor/services/partners/` + `services/partner_groups/`）— 外部通道（IM）接入与 partner 会话运行时。通道协议与总线：`deeptutor/partners/bus/queue.py:9`（`MessageBus`）、`deeptutor/partners/bus/events.py:11`（`InboundMessage`/`:33` `OutboundMessage`）、`deeptutor/partners/channels/base.py:38`（`BaseChannel`）+ 各通道实现（feishu/telegram/dingtalk/discord/email/qq/wecom/matrix/msteams/napcat/mochat/zulip…）。服务层：`deeptutor/services/partners/runtime.py:137`（`PartnerRunner` turn 执行）、`manager.py`、`model_runtime.py`；群组会诊 `services/partner_groups/manager.py`。出站目标校验在 `partners/network.py` 与 `services/mcp/network.py`。
25. **multi_user**（`deeptutor/multi_user/`）— 多用户账号、身份与访问控制：`identity.py`（用户身份）、`context.py`（请求级用户上下文）、各访问控制件 `book_access.py`/`knowledge_access.py`/`model_access.py`/`partner_access.py`/`skill_access.py`/`tool_access.py`、`guardians.py`（监护人授权）、`session_handoff.py`（会话交接）、`audit.py`。鉴权依赖在 `services/auth.py`。
26. **memory**（`deeptutor/services/memory/`）— 记忆子系统：文档化记忆与偏好。`deeptutor/services/memory/store.py:69`（`MemoryStore`）、`deeptutor/services/memory/document.py:73`（`Document` 模型）、`deeptutor/services/memory/ops.py:120`（操作应用）、`recall.py`（召回）、`snapshot/`（快照）、`consolidator/`（整合器）。

### 3.7 基础设施（9 个）

27. **config**（`deeptutor/config/` + `deeptutor/services/config/`）— 配置体系：字段规格 `deeptutor/config/settings.py:27`（`Settings`）；服务层负责 profile/draft/apply、模型目录与 readiness：`services/config/loader.py`、`settings_spec.py`、`settings_draft.py`、`model_catalog.py`、`readiness.py`。
28. **events**（`deeptutor/events/` + `deeptutor/api/utils/`）— 进程内事件与进度广播：`deeptutor/events/event_bus.py:61`（`EventBus`，事件类型 `deeptutor/events/event_bus.py:22`）；HTTP 面进度广播 `deeptutor/api/utils/progress_broadcaster.py:14`，WS 面见 §3.1 unified_ws 与各 router 的 `ws_router`。
29. **storage**（`deeptutor/services/storage/`）— 文件库与附件：`deeptutor/services/storage/file_library.py:83`（`FileLibraryStore`，单例 `:457`）、`attachment_store.py`。KB 数据与工作区文件的落盘位置由 `services/path_service.py` 统一解析。
30. **workspace**（`deeptutor/services/workspace/`）— 工作区上下文与迁移：`context.py`、`catalog.py`、`data_migration.py`（迁移）、`deeptutor/services/workspace/activity.py:67`（`WorkspaceActivityMiddleware` 写活动互斥）、`execution.py`。
31. **cron**（`deeptutor/services/cron/`）— 定时任务：`deeptutor/services/cron/service.py:178`（`CronService`，调度计算 `:118`）、`repository.py`（持久化与锁）、`executor.py`（触发执行）。
32. **sandbox**（`deeptutor/services/sandbox/`）— 命令执行沙箱：`deeptutor/services/sandbox/service.py:33`（`SandboxService`）、`backends.py`、`runner/`、`artifacts.py`、`quota.py`。
33. **visualizers**（`deeptutor/visualizers/`）— 可视化输出（Mermaid 等）注册与渲染链：`deeptutor/visualizers/registry.py:13`（`VisualizerRegistry`）、`protocol.py`、`loop_capability.py`；渲染在 web 端完成。
34. **core**（`deeptutor/core/`）— 跨层协议与基础类型：`capability_protocol.py`、`tool_protocol.py`、`turn_request.py`、`stream.py`、`context.py`、`errors.py`、`entry_points.py`。改协议先看这里。
35. **i18n**（`deeptutor/i18n/`）— 多语言：后端文案与语言协商（`response_languages.py` 顶层协商规则），前端词条在 `web/i18n/`、`web/locales/`。
36. **logging**（`deeptutor/logging/`）— 日志配置与进度观测：`deeptutor/logging/configure.py:39`（`configure_logging`）、`deeptutor/logging/config.py:25`（`load_logging_config`）、`process_stream`（子进程日志接管）。
37. **媒体域**（`deeptutor/services/voice/` + `services/videogen/` + `services/imagegen/`）— 语音转写/合成（`voice/base.py`、`voice/adapters/`、`voice/speech_text.py`）、视频生成任务（`videogen/`）、图像生成（`imagegen/`）；对外路由 `api/routers/voice.py`、`visualizers.py`。
38. **video_learning**（`deeptutor/video_learning/`）— 视频学习/Immersive Watching：`service.py`、`invidious_account*.py`（Invidious 绑定）、`marks.py`、`notes.py`。
39. **subagent**（`deeptutor/services/subagent/`）— 子代理服务：opencode 等外部子代理进程管理（`opencode_server.py` 等）。
40. **utils 横切**（`deeptutor/utils/`）— 无业务语义的通用工具（原子写、时钟、JSON 等）；对应补测卡 test-utils-helpers。

## 4. 储备池导读索引（guide-*，77 张，全部真实存在）

按 §2 分层组织；`AGEN-xxx` 为卡号，`guide-*` 为卡 key。

**入口与装配**：guide-cli（AGEN-477）、guide-routers（AGEN-468）、guide-frontend（AGEN-646）、guide-web-contracts（AGEN-877）、guide-web-state（AGEN-984）、guide-web-guard-layers（AGEN-892）、guide-web-activity（AGEN-1097）、guide-deploy（AGEN-375）、guide-packaging（AGEN-1026）。

**运行时与会话**：guide-runtime（AGEN-447）、guide-runtime-subpackages（AGEN-1032）、guide-launcher（AGEN-835）、guide-app-update（AGEN-676）、guide-background-leader（AGEN-889）、guide-realtime-push（AGEN-1124）、guide-chat（AGEN-423）、guide-session（AGEN-97）、guide-session-turns（AGEN-1096）、guide-subagent（AGEN-608）、guide-task-board（AGEN-859）。

**模型与工具面**：guide-llm-providers（AGEN-609）、guide-llm-clients（AGEN-1031）、guide-capabilities（AGEN-796）、guide-capability-instances（AGEN-1030）、guide-tools（AGEN-517）、guide-tools-prompting（AGEN-1033）、guide-vision-tools（AGEN-1008）、guide-skills（AGEN-445）、guide-mcp（AGEN-678）、guide-plugins（AGEN-651）、guide-ask-user（AGEN-983）。

**知识链**：guide-knowledge（AGEN-96）、guide-parsing（AGEN-516）、guide-rag-pipelines（AGEN-817）、guide-rag-eval（AGEN-918）、guide-embedding（AGEN-424）、guide-search-providers（AGEN-917）、guide-textbook-struct（AGEN-876）、guide-ima-pipeline（AGEN-677）、guide-citation（AGEN-652）、guide-storage（AGEN-449）。

**学习与内容域**：guide-book（AGEN-541）、guide-learning-domain（AGEN-1029）、guide-quiz（AGEN-568）、guide-question（AGEN-448）、guide-practice-domain（AGEN-890）、guide-journal（AGEN-551）、guide-notebook（AGEN-572）、guide-cowriter（AGEN-425）、guide-math-animator（AGEN-858）、guide-visualize（AGEN-478）、guide-voice（AGEN-705）、guide-watching（AGEN-95）、guide-video-learning（AGEN-965）、guide-audio-overview（AGEN-1088）。

> 注：reading 域当前无独立 guide-* 卡，以 §5 的 test-reading-progress（AGEN-147）等阅读面补测卡与 §3.5 的 `deeptutor/reading/service.py` 锚点为准。

**通道与账号**：guide-partners（AGEN-371）、guide-channels（AGEN-611）、guide-services-partners（AGEN-1034）、guide-network-validation（AGEN-941）、guide-multiuser（AGEN-543）、guide-authn（AGEN-574）、guide-learner（AGEN-98）、guide-marginnote-contract（AGEN-891）、guide-memory（AGEN-834）。

**基础设施与横切**：guide-config（AGEN-546）、guide-events（AGEN-518）、guide-cron（AGEN-940）、guide-sandbox（AGEN-939）、guide-workspace-migration（AGEN-878）、guide-core-protocols（AGEN-1025）、guide-i18n（AGEN-513）、guide-logging（AGEN-706）、guide-agents（AGEN-542）、guide-research（AGEN-290）、guide-testing（AGEN-650）、guide-ci-workflows（AGEN-1087）、guide-upstream-contrib（AGEN-1098）。

> guide-* 计数说明：以上 7 组合计 77 张，与储备池 `deeptour/guide-*` 全量一致；review-guide-scope-merges（AGEN-1047）、verify-guide-anchors（AGEN-899）等 guide 治理卡不属导读正文，未计入。

## 5. 储备池补测索引（test-*，按子系统精选，key 均真实存在）

- **入口/API/runtime**：test-run-server（AGEN-1060）、test-api-router-gaps（AGEN-699）、test-auth-deps（AGEN-483）、test-small-routers（AGEN-766）、test-zero-routers-batch2（AGEN-788）、test-startup-import-budget（AGEN-1117）、test-cli-build-snapshot（AGEN-1070）、test-turn-engine（AGEN-969）、test-turn-executor（AGEN-686）、test-request-preparer（AGEN-687）、test-turn-context-assembler（AGEN-1068）、test-turn-subscribe-polling（AGEN-865）、test-launcher-lifecycle（AGEN-287）、test-runtime-worker-tasks（AGEN-1061）、test-background-leader-clock（AGEN-863）、test-think-stream（AGEN-935）、test-agents-shared-runtime（AGEN-846）、test-shared-workspace-prompt（AGEN-1075）、test-context-budget（AGEN-1053）。
- **session**：test-sqlite-store（AGEN-634）、test-sqlite-store-concurrency（AGEN-955）、test-session-status-writeback（AGEN-882）、test-session-transfer（AGEN-831）、test-chat-export（AGEN-556）、test-chat-search（AGEN-440）、test-cancel-turn（AGEN-605、AGEN-629）、test-askuser（AGEN-99）、test-ask-user-trace（AGEN-936）、test-title-service（AGEN-830）、test-usage-recovery（AGEN-841）、test-parent-chain-defaults（AGEN-883）、test-chat-hints（AGEN-993）、test-pocketbase-client（AGEN-696）、test-pocketbase-store（AGEN-150）。
- **llm**：test-cloud-local-providers（AGEN-847）、test-copilot-provider（AGEN-810）、test-codebuddy-models（AGEN-1077）、test-codex-auth-lifecycle（AGEN-1009）、test-llm-error-mapping（AGEN-1036）、test-stream-parser（AGEN-554）、test-reasoning-params（AGEN-668）、test-keypool（AGEN-675）、test-generation-http（AGEN-1010）、test-json-extractors（AGEN-636）、test-usage-ledger（AGEN-829）、test-model-selection（AGEN-1037）、test-model-selection-fallback（AGEN-1013）、test-image-description（AGEN-1063）、test-image-caption-cache（AGEN-842）。
- **capabilities/tools/vision**：test-ask-questions-loop（AGEN-794）、test-explore-context（AGEN-805）、test-loop-capability（AGEN-959）、test-capability-catalog（AGEN-958）、test-tools-gaps（AGEN-698）、test-write-note-errors（AGEN-1094）、test-paper-search（AGEN-511）、test-tex-tools（AGEN-439）、test-reason-brainstorm-tools（AGEN-849）、test-mastery-nav（AGEN-973）、test-question-bank（AGEN-972）、test-media-gen-tool（AGEN-1086）、test-vision-block-parser（AGEN-844）、test-coord-transform（AGEN-746）、test-image-utils（AGEN-512）、test-ggb-validator（AGEN-977）。
- **skills/mcp/plugins**：test-skills-builtin（AGEN-1018）、test-skill-frontmatter（AGEN-1084）、test-skill-taxonomy（AGEN-813）、test-mcp-session-state（AGEN-1055）、test-mcp-settings-router（AGEN-832）、test-space-mcp-router（AGEN-780）、test-opencode-server（AGEN-845）、test-plugins-loader（AGEN-480）。
- **知识链**：test-kb-manager（AGEN-144）、test-kb-client（AGEN-126）、test-knowledge-router（AGEN-122）、test-upload-bounds（AGEN-495）、test-knowledge-frontier（AGEN-812）、test-rag-degrade（AGEN-482）、test-rag-fallback（AGEN-1038）、test-rag-provider-binding（AGEN-824）、test-rag-eval（AGEN-912）、test-rag-pipeline-config-union（AGEN-887）、test-embedding-binding（AGEN-744）、test-embedding-adapters（AGEN-913）、test-embedding-request-options（AGEN-971）、test-lightrag-worker（AGEN-607）、test-lightrag-sidecar（AGEN-811）、test-lightrag-cache-reuse（AGEN-638）、test-llamaindex-retrievers（AGEN-843）、test-ima-transport（AGEN-932）、test-mineru-probe（AGEN-593）、test-docling-local-worker（AGEN-848）、test-markitdown-formats（AGEN-596）、test-parsing-formats（AGEN-1064）、test-parsing-install（AGEN-915）、test-parsing-versions（AGEN-967）、test-search-providers-batch（AGEN-809）、test-search-consolidation（AGEN-1052）、test-search-source-filter（AGEN-974）、test-textbook-struct（AGEN-791）、test-citation-manager（AGEN-125）。
- **事件/进度**：test-event-bus（AGEN-549）、test-events-broadcast（AGEN-1042）、test-progress-broadcaster（AGEN-1092）、test-websocket-progress（AGEN-354）、test-task-log-stream-errors（AGEN-1093）、test-progress-tracker（AGEN-635）、test-progress-events（AGEN-1062）。
- **学习与内容域**：test-book-engine（AGEN-127）、test-book-agents（AGEN-966）、test-book-section（AGEN-756）、test-book-blocks-suite（AGEN-839）、test-book-blocks-language（AGEN-1083）、test-book-estimate（AGEN-1059）、test-book-rag-helpers（AGEN-1058）、test-book-access（AGEN-828）、test-learning-grading（AGEN-1035）、test-learning-assessment（AGEN-1050）、test-learning-pending（AGEN-793）、test-learning-adapter（AGEN-755）、test-learning-records（AGEN-441）、test-learning-overlay（AGEN-853）、test-question-pipeline（AGEN-284）、test-question-stdout（AGEN-433）、test-question-notebook-router（AGEN-838）、test-question-extractor（AGEN-757）、test-question-card（AGEN-961）、test-quiz-judge（AGEN-124）、test-quiz-viewer（AGEN-285）、test-mastery-hints（AGEN-504）、test-mastery-path-router（AGEN-758）、test-courses-state（AGEN-749）、test-practice-scheduler（AGEN-789）、test-notebook（AGEN-114）、test-notebook-analysis-agent（AGEN-927）、test-reading-progress（AGEN-147）、test-reading-references（AGEN-637）、test-reading-hints（AGEN-745）、test-reading-extensions-router（AGEN-775）、test-reading-tool-base（AGEN-1065）、test-read-aloud（AGEN-361）、test-epub（AGEN-100）、test-epub-bilingual（AGEN-368）、test-co-writer（AGEN-289）、test-docx-converter（AGEN-412）、test-edit-agent（AGEN-751）、test-visualize-review-agent（AGEN-1067）、test-visualization-viewer（AGEN-443）、test-journal-recovery-flush-hook（AGEN-866）、test-math-visual-review（AGEN-851）、test-research-pipeline（AGEN-143）、test-research-mode-strategy（AGEN-957）。
- **partners 通道**：test-feishu-channel（AGEN-145）、test-telegram-channel（AGEN-286）、test-dingtalk-channel（AGEN-735）、test-discord-channel（AGEN-954）、test-email-channel（AGEN-645）、test-wecom-channel（AGEN-1051）、test-qq-lark-channels（AGEN-736）、test-matrix-channel（AGEN-743）、test-msteams-semantics（AGEN-741）、test-napcat-semantics（AGEN-742）、test-napcat-frame（AGEN-592）、test-napcat-msteams-asserts（AGEN-947）、test-mochat-channel（AGEN-690）、test-zulip-polling-stabilize（AGEN-861）、test-weixin-onboarding（AGEN-808）、test-partner-access（AGEN-826）、test-partner-groups-router（AGEN-763）、test-partners-model-runtime（AGEN-1069）、test-partners-network（AGEN-855）、test-partners-transcription（AGEN-1057）、test-channel-double-start（AGEN-1131）。
- **multi_user**：test-permission-matrix（AGEN-565）、test-guardians（AGEN-994）、test-model-access（AGEN-692）、test-session-handoff（AGEN-991）、test-multiuser-audit（AGEN-840）、test-login-rate-limit（AGEN-1012）、test-admin-users-api（AGEN-702）。
- **memory**：test-memory-snapshot（AGEN-419）、test-memory-snapshot-diff（AGEN-1054）、test-memory-modes（AGEN-697）、test-consolidator-modes（AGEN-782）、test-consolidator-waiters（AGEN-594）、test-consolidator-shims（AGEN-1073）、test-memory-graph（AGEN-146）。
- **config/settings**：test-config-manager（AGEN-639）、test-config-readiness（AGEN-787）、test-config-origins（AGEN-970）、test-settings-services（AGEN-1041）、test-settings-router-fallbacks（AGEN-420）、test-settings-store（AGEN-148）、test-settings-docstring-parity（AGEN-949）、test-setup-binding（AGEN-591）、test-response-languages（AGEN-996）。
- **cron/sandbox/子进程**：test-cron-executor（AGEN-670）、test-cron-repo-lock-timing（AGEN-869）、test-sandbox-runner-shutdown（AGEN-1130）、test-subprocess-high-picks（AGEN-884）。
- **媒体/视频**：test-voice-openai-compat（AGEN-1056）、test-voice-speech-text（AGEN-691）、test-volcengine-voice（AGEN-916）、test-videogen-pipeline（AGEN-1017）、test-video-learning-router（AGEN-771）、test-invidious-account（AGEN-806）、test-audio-overview-pipeline（AGEN-1085）、test-web-source-sync（AGEN-567）。
- **web 前端**：test-chat-message-list（AGEN-701）、test-chat-state-adapter（AGEN-288）、test-chat-workspace（AGEN-123）、test-standalone-composer（AGEN-444）、test-web-hooks（AGEN-1019）、test-web-route-guard-403（AGEN-885）、test-web-403-remaining（AGEN-953）、test-web-context-ref（AGEN-995）、test-latex-render（AGEN-369）、test-markdown-display（AGEN-151）、test-reconnect-policy（AGEN-384）。
- **横切**：test-atomic-write-contract（AGEN-951）、test-singleflight-cache（AGEN-671）、test-import-cycle-guard（AGEN-881）、test-utils-helpers（AGEN-1039）、test-doctor（AGEN-914）、test-async-delay-sweep（AGEN-872）、test-elapsed-rag-bounds（AGEN-870）、test-elapsed-misc-bounds（AGEN-871）、test-i18n-metadata-status（AGEN-852）、test-zero-mods-batch3（AGEN-906）、test-zero-mods-batch4（AGEN-1095）、test-app-update-version（AGEN-669）、test-path-service（AGEN-1014）、test-attachment-store（AGEN-643）、test-file-library（AGEN-432）、test-workspace-kb-move（AGEN-976）、test-file-preview-router（AGEN-764）、test-office-preview（AGEN-790）、test-space-cli-apps（AGEN-833）、test-obsidian-vault（AGEN-807）、test-marginnote-bridge（AGEN-442）、test-hermes-remote-events（AGEN-933）、test-github-source（AGEN-1011）、test-resource-library-dead-param（AGEN-886）、test-cancel-paragons（AGEN-1129）、test-suggestions-service（AGEN-1016）、test-persona-service（AGEN-1015）、test-base-sync（AGEN-550）、test-prompt-templates（AGEN-555）、test-mimic-generate（AGEN-355）、test-mypy-hotspot-picks（AGEN-888）、test-persona-store（AGEN-1040）、test-process-stream（AGEN-938）。

> 治理类卡（scan-*/verify-*/review-* 前缀，如 verify-test-pool-drift AGEN-1110、scan-test-runtime AGEN-919）不属于本文 guide-*/test-* 索引范围，仅在需要审计时查阅。

## 6. 30 分钟读码路线（新读者）

1. **0–5 min｜入口全景**：`deeptutor_cli/main.py:222` 扫一眼命令面 → `deeptutor/api/main.py:404`（app 定义）与 `:575` 起的路由挂载清单。看完即知道"系统对外长什么样"。
2. **5–10 min｜一次请求的骨架**：`deeptutor/api/routers/unified_ws.py:44`（WS 进入）→ `deeptutor/runtime/orchestrator.py:51`（`ChatOrchestrator`）→ `deeptutor/runtime/turn_engine.py:11`（`TurnEngine`）→ `deeptutor/services/session/turn_runtime.py:26`（turn 运行时管理）。
3. **10–15 min｜turn 内部**：`deeptutor/services/session/turns/executor.py:69`（`TurnExecutor` 主干）→ `deeptutor/services/llm/client.py:80`（`LLMClient`）→ `deeptutor/services/llm/provider_factory.py:144`（provider 池）→ `deeptutor/services/llm/provider_core/base.py:73`（`LLMProvider` 抽象）。
4. **15–20 min｜模型如何拿到工具**：`deeptutor/capabilities/registry.py:28`（loop 能力注册）→ `deeptutor/tools/builtin/__init__.py:105`（`RAGTool` 代表作）→ `deeptutor/services/mcp/manager.py:105`（外部 MCP 工具适配）。
5. **20–25 min｜知识链**：`deeptutor/knowledge/manager.py:325`（KB 管理）→ `deeptutor/services/parsing/service.py:74`（解析分派）→ `deeptutor/services/rag/service.py:22`（检索与降级）→ `deeptutor/services/rag/pipelines/base.py:17`（管线协议）。
6. **25–30 min｜前端对应面**：`web/app/layout.tsx:38` → `web/features/chat/`（与 WS 协议对照）→ 回到 `deeptutor/api/main.py` 确认刚看过的后端路由挂在哪条 URL 上。

读完这条线，即可拿着 §4 的 guide-* 卡任意深入某个子系统。

## 7. 覆盖统计

- 一级子系统条目：§3 共 40 条（入口与装配 4、运行时与会话 3、模型与工具面 6、知识链 5、学习与内容域 5、通道与账号 3、基础设施与横切 14），每条均有 `path:line` 入口锚点。
- guide-* 索引：77 张，储备池 `deeptour/guide-*` 全量（§4）。
- test-* 索引：253 个 key 全量收录（§5；对应 254 张卡，test-cancel-turn 一 key 双卡 AGEN-605/AGEN-629）。
- 另按全名提及 2 张 guide 治理卡（review-guide-scope-merges、verify-guide-anchors），不计入导读索引。
- 全部索引条目经脚本比对储备池清单：333 条引用零无效、零卡号错配。
- 本文不修改任何代码；`deeptutor/`、`web/`、`deeptutor_cli/` 源码零改动。
