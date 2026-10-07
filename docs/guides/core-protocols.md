# DeepTutor `core` 协议层导读

- 基线：origin/main @ `f07029cfc`（v1.6.13）。
- 范围：`deeptutor/core/` 的 8 个协议模块（capability_protocol、tool_protocol、context、trace、stream、errors、turn_request、entry_points）+ 2 个伴生常量模块（response_languages、assessment），以及上层（agents / services / api / CLI / web）如何消费这些协议。
- 分工去重：工具面全景见 `docs/guides/tools-surface.md`（guide-tools，tools 轴）；capabilities 服务轴与 agents 轴见各自的 guide-* 导读。本文只讲协议层本身：类型契约、相互调用关系、跨层消费点，不重复展开具体工具/能力的业务。
- 所有锚点形如 `path:line`，相对仓库根，逐一对照 origin/main（f07029cfc）现行代码复核。

## 1. 这一层是什么：三条契约线

`core` 是全仓最底层、零产品逻辑的一层。模块间依赖极轻：只有 `capability_protocol` 依赖 `context` + `stream`（`deeptutor/core/capability_protocol.py:17`、`deeptutor/core/capability_protocol.py:18`），`turn_request` 依赖 pydantic 和 `response_languages`（`deeptutor/core/turn_request.py:8`、`deeptutor/core/turn_request.py:10`），其余模块不依赖任何内部代码。按"话语权"分三条线读：

```
输入线   TurnRequest(wire 契约) ──► UnifiedContext(运行时上下文) ──► capability.run()
输出线   StreamEvent(事件) + trace metadata(渲染约定) + CapabilityOutput(终点产物)
扩展线   BaseTool/ToolLookup(Level 1 插槽) · TurnCapability/CapabilityManifest(Level 2 插槽)
         · load_entry_point_group(第三方发现) · errors(基类保留层)
```

| 模块 | 核心定义 | 上层主要消费者 |
|---|---|---|
| `stream.py` | `StreamEventType:17`、`StreamEvent:38` | runtime/stream_bus、会话执行器、CLI/web 渲染 |
| `context.py` | `UnifiedContext:86`（+5 个子对象） | 会话执行器（组装）、orchestrator、每个 capability |
| `tool_protocol.py` | `BaseTool:220`、`ToolLookup:184`、`ToolResult:130` | ToolRegistry、工具派发器、所有工具实现 |
| `capability_protocol.py` | `TurnCapability:42`、`CapabilityManifest:30`、`StreamBusProtocol:21` | CapabilityRegistry、builtin 目录、12 个回合能力 |
| `turn_request.py` | `TurnRequest:113`（pydantic, extra=forbid） | TurnApplicationService、WS/CLI/SDK 适配器、StartTurnCommand |
| `trace.py` | `ANSWER_BEARING_CALL_KINDS:17`、三个 metadata 构造器 | agent loop、工具派发器、web stream 客户端（双拷贝） |
| `errors.py` | `DeepTutorError:10` 基类层级 | 仅契约测试（实际错误分类已分层下沉，见 §2.7） |
| `entry_points.py` | `load_entry_point_group:27` | 能力/插件/阅读扩展四处注册表 |
| `response_languages.py`（伴生） | `SUPPORTED_RESPONSE_LANGUAGES:3` | turn_request 校验、会话偏好 |
| `assessment.py`（伴生） | 题目来源/类型/结果 Literal 集 `deeptutor/core/assessment.py:5` | 出题/持久化/HTTP 三方共享枚举 |

## 2. 每个模块一卡

### 2.1 `stream.py` —— 事件的形状

- `StreamEventType:17`（`deeptutor/core/stream.py:17`）共 15 种事件类型（`deeptutor/core/stream.py:20-34`）：阶段（`stage_start/end`）、内容（`thinking/observation/content`）、工具（`tool_call/tool_result`）、结果（`progress/sources/result`）、控制（`error/session/session_meta/done/wait_for_input`）。
- `StreamEvent:38`（`deeptutor/core/stream.py:38`）带 `source`/`stage` 定位生产者、`session_id`/`turn_id`/`seq` 定位回合内顺序（`deeptutor/core/stream.py:56-58`）、`timestamp:59`。`to_dict():61` 是唯一的序列化出口——持久化与 WS 下发都走它。
- 消费侧：`deeptutor/runtime/stream_bus.py:31` `StreamBus` 是唯一的标准生产端（`emit:62`、`subscribe:79`、`stage:129`、便捷方法 `content:156` / `tool_call:207` / `tool_result:225` / `progress:243` / `sources:265` / `error:295` / `wait_for_input:312`）；会话执行器逐条消费并持久化（`deeptutor/services/session/turns/executor.py:1001-1015`）。

### 2.2 `context.py` —— 回合的形状

`UnifiedContext:86`（`deeptutor/core/context.py:86`）是"一个用户回合所需的全部输入"，字段分四组：

- **用户可见输入**（`deeptutor/core/context.py:129-143`）：`session_id/user_message/conversation_history`、`enabled_tools`（**`None` = 未指定，`[]` = 显式全关**，`deeptutor/core/context.py:94-96`）、`allowed_builtin_tools`（内建白名单门，partners 用它拒绝内建工具，`deeptutor/core/context.py:97-101`）、`active_capability`、`knowledge_bases`、`attachments`、`config_overrides`、`language`，以及四段预注入文本 `memory_context/persona_context/sidebar_context/skills_manifest/source_manifest`。
- **运行时私货** `TurnRuntimeContext:50`（`deeptutor/core/context.py:50`）：不可序列化——`wait_for_user_reply:54`（ask_user 暂停-恢复回调）、`model_history/model_turn:58-59`（私有模型历史）、`workspace:65`（`WorkspaceRuntimeContext:35`，frozen；**物理路径绝不进模型消息/持久化/公开 URL**，`deeptutor/core/context.py:38-39`）。
- **可变交互态** `InteractionState:69`（`end_loop:72`、`user_answers:73`）与**终点产物** `CapabilityOutput:77`（`agent_output:80`、`event_metadata:81`、`answer_published:82`）。
- **扩展态** `extension_state:147` + `extension(namespace):150`（空名拒绝）；`metadata:148` 只放可序列化兼容数据，新的可变扩展状态必须走 `extension_state`（`deeptutor/core/context.py:125-126`）。
- `Attachment:17`（`deeptutor/core/context.py:17`）：`id:27` 稳定标识兼 AttachmentStore 目录段，`extracted_text:31` 是 office 文件的纯文本渲染（前端"LLM 看到了什么"）。

### 2.3 `tool_protocol.py` —— Level 1 插槽

- `ToolParameter:17`：`to_schema():45` 出 JSON-Schema 属性；**`items:36` 对 `type="array"` 必填**——strict provider（Gemini/Anthropic）缺它报 400，缺省兜底 `{"type":"string"}`（`deeptutor/core/tool_protocol.py:22-27`、`deeptutor/core/tool_protocol.py:50-51`）；`sensitive:43` 让参数值不进 trace 事件（见 §3.2）。
- `ToolDefinition:56`：OpenAI function-calling schema（`to_openai_schema():71`）；`raw_parameters:69` 整段 JSON-Schema 直通且优先于 `parameters`——MCP/CLI 适配工具的任意上游 schema 不做有损重编码。
- `ToolResult:130`（`deeptutor/core/tool_protocol.py:130`）是工具与循环的返回契约：`content:159` 给模型、`sources:160` 给引用、`metadata:161` 兼作结构化 UI 通道（如 `ask_user.options`）、`success:162` 显式失败、`terminate_turn:163` 结束回合（保留字段）、`pause_for_user:164` 暂停回合等用户回复（`ask_user` 专用，见 §3.2）、`model_message:167` **仅进模型上下文的私有附件，绝不入 stream/引用/持久化**（`deeptutor/core/tool_protocol.py:154-156`、`165-167`）。
- `ToolLookup:184` 是注册表的只读协议面（`execute:217`）；派发器只依赖这个协议，于是 ScopedToolRegistry（`deeptutor/runtime/registry/scoped_registry.py:40`，多用户外部工具 overlay）可以合法顶替进程注册表。`ToolEventSink:173` 是工具内部进度回调协议。
- `BaseTool:220`：实现 `get_definition():249` + `execute():254` 即为一个工具（文件内含最小模板 `deeptutor/core/tool_protocol.py:232-243`）；`deferred:246` 标记渐进披露（schema 不进首轮，模型用 `load_tools` 拉全）；`get_prompt_hints():258` 默认从 definition 派生，可覆写接提示层。
- `provider_identity():270`：给外部 provider 工具返回 `(kind, provider_id)`（`"mcp"`/`"cli"`），供 deferred 清单分组与 trace 标注"哪个 MCP server 在跑"，避免前端解析 `mcp_<server>_<tool>` 猜错（`deeptutor/core/tool_protocol.py:276-284`）。

### 2.4 `capability_protocol.py` —— Level 2 插槽

- `CapabilityManifest:30`（`deeptutor/core/capability_protocol.py:30`）：`stages:35`（UI 阶段名）、`tools_used:36`（声明性，非挂载授权）、`cli_aliases:37`、`request_schema:38`（per-capability config schema，通常从 `get_capability_request_schema` 取，见 `deeptutor/agents/chat/capability.py:21`）、`config_defaults:39`。
- `TurnCapability:42`：抽象方法只有一个——`run(context, stream):67`；`name:72`/`stages:76` 都从 manifest 派生。多阶段管线在 `run` 里用 `stream.stage()` 上下文管理器包住（docstring 示例 `deeptutor/core/capability_protocol.py:48-62`；实际用例 `deeptutor/agents/research/pipeline.py:585`）。
- `StreamBusProtocol:21`（`deeptutor/core/capability_protocol.py:21`）是能力对输出面的最小要求：`emit:24` + `stage:26`。运行时实际传入的都是 `deeptutor/runtime/stream_bus.py:31` `StreamBus`；协议面存在的意义是让能力实现不依赖具体 bus。
- 兼容垫片：`BaseCapability` 经 `__getattr__:80`（`deeptutor/core/capability_protocol.py:80-89`）与包级 `__getattr__`（`deeptutor/core/__init__.py:36-41`）双重转发到 `TurnCapability`，发 DeprecationWarning，v3 移除。

### 2.5 `turn_request.py` —— wire 契约

- `TurnRequest:113`（`deeptutor/core/turn_request.py:113`）是三个入口（CLI/WS/SDK）共用的回合输入模型，`extra="forbid":121`——多传键直接校验失败。关键字段：`content:123`、`client_submission_id:127`（浏览器生成的因果标识，重试区分自己那行）、`capability:128`、`tools:130`、`reply_language_override:135`、`config:136`（**只含能力选项**；runtime 专属键有独立字段，`deeptutor/core/turn_request.py:177-196`：`persist_user_message`、`regenerate`、`capability_once`、`auto_route` 等）。
- 引用类值对象（`deeptutor/core/turn_request.py:45` 起，至 `MasteryCardSkip:96`）：`NotebookReference:45`、`BookReference:52`、`ReadingReference:59`（含 `revision` 乐观锁 `ge=1`）、`ReadingViewport:67`、`TimedMediaViewport:74`、`MasteryCardAnswer:80` / `MasteryCardSkip:96`（mastery 卡片跨回合作答/跳过，让 runtime 在模型首 token 前就绑定问答对，`deeptutor/core/turn_request.py:83-88`）。
- 遗留翻译：`_LEGACY_RUNTIME_CONFIG_KEYS:12` + `model_validator(mode="before"):203`——老客户端塞在 `config` 里的 runtime 键被搬到位并告警，一个大版本内兼容（`deeptutor/core/turn_request.py:203-229`）。`reply_language_override` 校验委托伴生模块（`field_validator:198` → `response_languages.validate_reply_language_override`）。
- `to_payload():231` 用 `exclude_unset=True` 保留"省略 vs 显式 null"的语义——下游 preparer 依赖它区分继承与重置。
- 上层：`deeptutor/app/contracts.py:3` 全量 re-export；`deeptutor/api/contracts/turn_protocol.py:10` 引入并派生 `StartTurnCommand:69`（加 `type`/`protocol_version` 信封）；构造点见 §3.1。

### 2.6 `trace.py` —— 渲染约定

- trace 不是一个对象而是一组 metadata 约定：`build_trace_metadata:25`（新卡片）、`derive_trace_metadata:55`（继承改写）、`merge_trace_metadata:84`（合并）、`new_call_id:20`（`call-<10hex>` 卡片 id）。
- **全仓最重要的双拷贝契约**：`ANSWER_BEARING_CALL_KINDS:17`（`deeptutor/core/trace.py:17`，`frozenset({"llm_final_response", "agent_loop_round"})`）。后端用 `call_kind` 标注 content 事件（`deeptutor/agents/loop/agent_loop.py:416`、`deeptutor/agents/loop/agent_loop.py:850`），web 客户端用同名单 `shouldAppendEventContent` 决定哪些 content 拼进消息正文（`web/lib/stream.ts:16`）；`tests/core/test_answer_call_kinds.py` 把两份拷贝锁在一起。注释写明失败模式：加了写正文的 call_kind 不同步这份名单，正文会流式打出然后从消息里消失，而 trace 里看不见（`deeptutor/core/trace.py:8-17`）。
- 消费侧第三站：会话执行器按 `call_id` 把流式 content 段钉到持久化偏移上（`deeptutor/services/session/turns/executor.py:1022` 一带的 `_stamp_content_offset`），重载后的排版与直播一致。

### 2.7 `errors.py` —— 保留的基类层级（现状：近休眠）

- 层级：`DeepTutorError:10`（`message` + `details` dict）→ `ConfigurationError:24` / `ValidationError:30` / `ServiceError:36` → `LLMServiceError:42` → `LLMContextError:48`；`EnvironmentConfigError:54` 挂在 Configuration 下。
- 诚实现状：origin/main 上**唯一 importer 是契约测试** `tests/core/test_context.py:8`。实际错误分类已按层下沉：LLM 错误分类学在 `deeptutor/services/llm/exceptions.py:11`（`LLMError` → `LLMAPIError:72` → `ProviderContextWindowError:165`）；coordination 配置错误用本地 `RuntimeConfigurationError(ValueError)`（`deeptutor/runtime/coordination/settings.py:13`）；回合失败语义走**异常属性**——orchestrator 兜底时读 `error_code/retryable/partial_response` 塞进 DONE metadata（`deeptutor/runtime/orchestrator.py:149-160`）。读代码时不要按这个文件找错误路径；新增错误类型优先放所属层的 errors 模块。

### 2.8 `entry_points.py` —— 第三方发现

- `load_entry_point_group(group, coerce):27`（`deeptutor/core/entry_points.py:27`）：读 entry-point group → 逐个 `ep.load()` → 交给调用方的 `coerce(name, obj)` 决定收不收 → **单个插件导入/裁决抛异常只 warn 跳过，不拖垮同组其他插件**（`deeptutor/core/entry_points.py:48-56`）。模块 docstring 明说保证边界：第三方代码在 import 期执行，这里只保证"一个坏插件不炸全家"（`deeptutor/core/entry_points.py:10-12`）。
- 四个消费点：回合能力注册表 `deeptutor/runtime/registry/capability_registry.py:116`（canonical group `deeptutor.extensions` + 一版遗留 fallback）；chat-loop 能力注册表 `deeptutor/capabilities/registry.py:173-174`（`deeptutor.extensions` + `deeptutor.loop_capabilities`，组常量 `deeptutor/capabilities/registry.py:21-22`）；旧版插件清单 `deeptutor/plugins/loader.py:44`；阅读扩展 `deeptutor/reading/extensions.py:114`。

### 2.9 伴生模块

- `response_languages.py`：`SUPPORTED_RESPONSE_LANGUAGES:3`（15 种语言）+ `validate_reply_language_override:22`；被 `deeptutor/core/turn_request.py:10` 的 field_validator 消费，同一名单也服务会话偏好层。
- `assessment.py`：题目来源/出处/类型/结果四组 Literal（`deeptutor/core/assessment.py:5-14`）+ frozenset 便于运行时校验；出题能力、持久化、HTTP API 三方共用同一枚举，不各自造字符串。

## 3. 跨层调用链

### 3.1 链 A：一个回合从键盘到持久化（输入线全程）

```
CLI ───────── deeptutor_cli/chat.py:173        TurnRequest(content=…, capability=…, …)
WS  ── StartTurnCommand(unified_ws.py:214) ──► api/routers/unified_ws.py:222  turns.start_turn(msg 去信封)
SDK ───────── deeptutor/app/facade.py:131      DeepTutorApp.start_turn → :148 turns.start_turn
        │
        ▼
deeptutor/app/service.py:35   TurnApplicationService.start_turn(payload)
  ├─ :38-39  TurnRequest.model_validate(...) → .to_payload()      # core 契约第一次把关
  └─ :52     runtime.start_turn(payload)                          # TurnRuntimeManager
        ▼
deeptutor/services/session/turn_runtime.py:26  TurnRuntimeManager（Preparer+ContextAssembler+Executor+… 组合）
  └─ deeptutor/services/session/turns/request_preparer.py:147-149  二次 model_validate + to_payload（去 type 键、补 language）
     └─ request_preparer.py:802  asyncio.create_task(self._run_turn(execution))
        ▼
deeptutor/services/session/turns/executor.py:141  _run_turn
  ├─ :180-194 建 per-turn reply_queue + _wait_for_user_reply（ask_user 暂停-恢复的运行时半边）
  ├─ :890      UnifiedContext(...)                                # core 输入契约在这里诞生
  ├─ :908      TurnRuntimeContext(wait_for_user_reply=…, workspace=…, model_history=…)
  └─ :1001     async for event in self.turn_engine.execute(context)
        ▼
deeptutor/runtime/turn_engine.py:17  TurnEngine.execute → ChatOrchestrator
        ▼
deeptutor/runtime/orchestrator.py:61  ChatOrchestrator.handle(context)
  ├─ :96-97   cap_name = context.active_capability or "chat"；registry.get()
  ├─ :141     await capability.run(context, bus)                  # core 扩展契约被消费（capability_protocol.py:67）
  ├─ :149-160 异常兜底读 error_code/retryable/partial_response → bus.error
  ├─ :185-186 bus.subscribe() + create_task(_run)                 # 事件扇出给执行器
  └─ :168-173 _run 的 finally 里发 DONE（status + usage_summary）
        ▼
executor.py:1001-1015  逐事件持久化（_publish_live_event :80、assistant_events、DONE 缓冲）
  └─ 终点产物：capability 写 context.capability_output（deeptutor/agents/loop/agent_loop.py:618-622）
     → orchestrator._publish_completion :204 读出（completion_event_fields :28-47）
     → 全局 EventBus CAPABILITY_COMPLETE
```

要点：`TurnRequest` 被**三次**校验（app/service.py:38、request_preparer.py:147、StartTurnCommand 的 pydantic 层），`UnifiedContext` 只组装一次；执行器是 StreamEvent 的持久化面，orchestrator 是扇出面，两者靠 `subscribe()` 解耦。

### 3.2 链 B：一次工具调用的协议旅程（扩展线 × 输出线）

```
chat loop 决定调工具
  └─ deeptutor/agents/loop/pipeline.py:1088  AgenticLoopPipeline._execute_tool_call
     └─ :1096 import execute_tool_call → :1532 调用
        ▼
deeptutor/runtime/agentic/tool_dispatch.py:647  execute_tool_call(...)
  ├─ :726  registry.execute(tool_name, event_sink=…, **args)
  │          # 参数类型是 ToolLookup 协议（core/tool_protocol.py:217），ScopedToolRegistry 可顶替
  │          # → ToolRegistry.execute（runtime/registry/tool_registry.py:151）
  │          #   → BaseTool.execute（core/tool_protocol.py:254）→ ToolResult（core/tool_protocol.py:130）
  ├─ :669-690 工具内部进度经 _event_sink → stream.progress + derive_trace_metadata（子 trace）
  ├─ :194-197 TOOL_CALL 事件的 args 先剥 `_` 前缀私参 + sensitive 参数
  │            （_sensitive_arg_names :633-644 回读 definition.parameters 的 sensitive:43；
  │             典型用例：quiz 的 expected_answer 不给看题人开小灶）
  ├─ :780    结果 dict 带 pause_for_user / terminate_turn
  └─ :907-914 pause_request 进 DispatchOutcome.pause_payload
        ▼
deeptutor/agents/loop/pipeline.py:1184  _await_user_reply_and_resolve
  ├─ :1193  waiter = context.runtime.wait_for_user_reply        # TurnRuntimeContext:54
  │          （链 A 里 executor.py:180-194 建的队列；不可用时降级为终结最终响应）
  ├─ :1195  raw_reply = await waiter()                          # 回合挂起，状态转 waiting_input
  │          （StreamBus.wait_for_input → StreamEventType.WAIT_FOR_INPUT，runtime/stream_bus.py:312-328，core/stream.py:34）
  └─ 回复文本/结构化 answers 格式化后回灌模型消息体，同一轮循环继续
```

要点：`pause_for_user`（core 契约）→ `DispatchOutcome`（runtime）→ `TurnRuntimeContext.wait_for_user_reply`（core 回调）→ executor 队列（services）→ WS 送达用户，四层各持一半契约。`sensitive` 脱敏是纯协议层声明、派发层执行，工具实现自身不用管展示。

### 3.3 链 C：能力/插件的发现与装配（扩展线的注册面）

```
进程启动
  ├─ CapabilityRegistry.load_builtins（runtime/registry/capability_registry.py:84）
  │    └─ BUILTIN_CAPABILITY_SPECS（runtime/bootstrap/builtin_capabilities.py:51）
  │       # "name → module:Class" 字符串目录，零导入注册；get 时才 import（capability_registry.py:140）
  ├─ CapabilityRegistry.load_plugins（capability_registry.py:86）
  │    └─ load_entry_point_group("deeptutor.extensions", _accept)   # core/entry_points.py:27；调用点 capability_registry.py:116
  │       # 第三方 entry point 返回 TurnCapability 类/工厂/实例 → 收编；重名拒收（`deeptutor/runtime/registry/capability_registry.py:111`）
  └─ chat-loop 侧同理：deeptutor/capabilities/registry.py:173-174（LoopCapabilitySpec:28 目录，BUILTIN_LOOP_CAPABILITY_SPECS:49）
        ▼
回合开始：orchestrator.py:97  registry.get(cap_name) → catalog.create → TurnCapability 实例
  └─ orchestrator.py:141  capability.run(context, bus)
```

要点：目录（builtin 字符串表）与发现（entry_points）两条路都汇到同一个 `CapabilityCatalog`；core 只提供目录协议（`CapabilityManifest`）与发现原语（`load_entry_point_group`），归拢逻辑在 runtime 层。

## 4. 上层消费定位（agents / services / api）

- **agents**：每个能力实现 `TurnCapability.run`（`deeptutor/agents/chat/capability.py:12`、`deeptutor/agents/research/capability.py:37`），共享管线在 `deeptutor/agents/loop/pipeline.py`（工具派发 :1088、暂停恢复 :1184、每轮组合经 `compose_enabled_tools` `deeptutor/agents/_shared/tool_composition.py:170`）；终点统一走 `emit_capability_result`（`deeptutor/agents/_shared/capability_result.py:21`，`deeptutor/agents/loop/agent_loop.py:363` 调用）。
- **services**：会话层是 `UnifiedContext` 的组装者与 `StreamEvent` 的持久化者（executor.py:890 / :1001）；`TurnRequest` 的规范化在 preparer（request_preparer.py:147）；LLM 错误分类学在 `deeptutor/services/llm/exceptions.py:11`（core/errors 不承载）。
- **api**：WS 信封模型 `StartTurnCommand(TurnRequest)`（`deeptutor/api/contracts/turn_protocol.py:69`），命令进 `TurnApplicationService`（unified_ws.py:222）；事件出站复用 `StreamEvent.to_dict()` 的字段名（小写 `type`/`stage`）。
- **web**（仓库内 `web/`）：消费同一事件流；`ANSWER_BEARING_CALL_KINDS` 的客户端双拷贝在 `web/lib/stream.ts:16`。
- **CLI**：`TurnRequest` 直接构造（deeptutor_cli/chat.py:173），经 SDK facade 进同一应用服务。

## 5. 新增一种 capability（回合型）：五步

1. **实现类**：`TurnCapability` 子类，给 `manifest`、实现 `run(context, stream)`（模板见 `deeptutor/core/capability_protocol.py:48-62`；实例 `deeptutor/agents/research/capability.py:37`）。多阶段用 `async with stream.stage("…", source=manifest.name)`（`deeptutor/runtime/stream_bus.py:129`）。
2. **注册目录**：`deeptutor/runtime/bootstrap/builtin_capabilities.py` 的 `BUILTIN_CAPABILITY_CLASSES:35` 加 class path，`BUILTIN_CAPABILITY_SPECS:51` 加 manifest 副本（名称与类内 manifest 必须一致，懒加载实例才不会漂移）。
3. **请求配置**：在 `deeptutor/runtime/request_contracts.py` 的 `CAPABILITY_CONFIG_MODELS:154` 注册 pydantic 配置模型——schema 自动生成（:191-192）并经 `get_capability_request_schema:208` 进 manifest 的 `request_schema`；运行时注册表也用它兜底 config_model（capability_registry.py:73）。
4. **（可选）chat-loop 型**：如果能力是"聊天循环 + 自有工具"而非独立管线，改走 `deeptutor/capabilities/registry.py:49` 的 `BUILTIN_LOOP_CAPABILITY_SPECS` 目录（`LoopCapabilitySpec:28`） + `LoopExtension.owned_tools`（`deeptutor/capabilities/protocol.py:104`），由共享 loop 承载。
5. **文案与别名**：阶段/提示 i18n 放 `deeptutor/capabilities/prompts/{en,zh}/<name>.yaml`；CLI 别名写 manifest 的 `cli_aliases`。测试放 `tests/core/`（协议契约）与 `tests/agents/`（行为）。

## 6. 新增一种 tool：五步

1. **实现类**：`BaseTool` 子类，`get_definition()` + `execute()`（模板 `deeptutor/core/tool_protocol.py:232-243`）。实现放 `deeptutor/tools/builtin/`（参照现役工具）或独立模块。
2. **注册目录**：`deeptutor/tools/builtin_specs.py` 的 `BUILTIN_TOOL_SPECS:46` 加一行 `BuiltinToolSpec(name, "module:Class")`——同样零导入，懒加载时校验类名不漂移；需要别名加 `TOOL_ALIASES:217`。
3. **选择暴露面（三选一）**：用户开关 → `USER_TOGGLEABLE_TOOL_NAMES`（`deeptutor/tools/builtin/__init__.py:1907`）；上下文条件挂载 → `deeptutor/agents/_shared/tool_composition.py:47` `_CONDITIONAL_MOUNT_FLAGS`（探测函数一律 fail-closed）+ `ToolMountFlags:143`；能力自有 → 所在能力的 `owned_tools`（`deeptutor/capabilities/protocol.py:104`）。改完跑 `compose_enabled_tools` 相关测试确认组合面。
4. **schema 纪律**：`type="array"` 参数显式给 `items`（否则 Gemini 400，`deeptutor/core/tool_protocol.py:22-27`）；任意 JSON-Schema 用 `raw_parameters:69` 直通；值不能给用户看的参数标 `sensitive:43`（派发层自动从 trace 剥除，§3.2）。
5. **测试**：工具行为在 `tests/tools/`，协议契约（schema 生成、sensitive 剥除）在 `tests/core/`。

## 7. 契约注意与常见坑

- `enabled_tools` 的 `None` 与 `[]` 语义不同（未指定 vs 全关），组装侧别把 None 归一成空表（`deeptutor/core/context.py:94-96`）。
- 别往 `TurnRequest.config` 塞 runtime 键：`extra="forbid"` 会拒收，runtime 选项有显式字段；老键走 `_LEGACY_RUNTIME_CONFIG_KEYS` 翻译并告警（`deeptutor/core/turn_request.py:12-24`、`:121`、`:203`）。
- `WorkspaceRuntimeContext` 的物理路径只活在内存里，进模型消息/持久化/URL 都是 bug（`deeptutor/core/context.py:38-39`）；`ToolResult.model_message` 同理（`deeptutor/core/tool_protocol.py:154-156`）。
- 加会写用户正文的 `call_kind` 必须三处同步：core 名单（`deeptutor/core/trace.py:17`）、web 名单（`web/lib/stream.ts:16`）、守门测试（`tests/core/test_answer_call_kinds.py`）——漏了就是"流式显示后正文消失"的静默故障。
- 新错误类型别再加进 `core/errors.py`（近休眠，§2.7）；放所属层，回合级失败语义用异常属性 `error_code/retryable/partial_response`（`deeptutor/runtime/orchestrator.py:149-160`）。
- 兼容名 `BaseCapability` 已 deprecated，别在新代码里用（`deeptutor/core/capability_protocol.py:80-89`）。
- 能力签名可以只依赖 `StreamBusProtocol`（emit+stage），但需要便捷方法（progress/tool_call/…）时直接注解 `StreamBus` 也可——运行时传入的总是后者。

## 8. 热点锚点速查

| 场景 | 锚点 |
|---|---|
| 回合输入契约 | `deeptutor/core/turn_request.py:113`；校验 `deeptutor/app/service.py:38`、`deeptutor/services/session/turns/request_preparer.py:147` |
| WS 信封 | `deeptutor/api/contracts/turn_protocol.py:69`；分发 `deeptutor/api/routers/unified_ws.py:222` |
| 上下文组装 | `deeptutor/services/session/turns/executor.py:890` |
| 回合路由与执行 | `deeptutor/runtime/turn_engine.py:17` → `deeptutor/runtime/orchestrator.py:61`（run :141） |
| 事件扇出/持久化 | `deeptutor/runtime/stream_bus.py:31`；`deeptutor/services/session/turns/executor.py:1001` |
| 能力终点产物 | `deeptutor/agents/_shared/capability_result.py:21`；`deeptutor/runtime/orchestrator.py:204` |
| 工具派发 | `deeptutor/runtime/agentic/tool_dispatch.py:647`（registry.execute :726；sensitive :633） |
| ask_user 暂停恢复 | `deeptutor/core/tool_protocol.py:164`；`deeptutor/agents/loop/pipeline.py:1184`；队列 `deeptutor/services/session/turns/executor.py:180` |
| 能力注册 | `deeptutor/runtime/registry/capability_registry.py:84`（插件 :86/:116）；目录 `deeptutor/runtime/bootstrap/builtin_capabilities.py:51` |
| 答案正文名单 | `deeptutor/core/trace.py:17` ↔ `web/lib/stream.ts:16`；守门 `tests/core/test_answer_call_kinds.py` |
| 错误兜底语义 | `deeptutor/runtime/orchestrator.py:149-160`；LLM 分类 `deeptutor/services/llm/exceptions.py:11` |
