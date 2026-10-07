# runtime 子包导读（agentic / coordination / registry / providers / bootstrap）

- 基线：origin/main `f07029cfc`（v1.6.13）。所有 `path:line` 均基于该基线，行号会随演进漂移，以符号名为准。
- 范围：`deeptutor/runtime/` 下五个子包共 32 个文件——agentic（11）、coordination（8）、registry（5）、providers（6）、bootstrap（2，含空 `__init__.py`）。
- 边界声明：`launcher.py`（启动/端口/前端构建）、`update_worker.py`（更新执行器）、`background_leader.py`（后台领导者租约）归既有三张卡，本文只在"交接点"一节引用它们的对外接口，不展开内部实现。
- 佐证文件 `evidence/guide-scope-20261007/report.md` 在本地仓库与 myfork 各分支均未找到，本卡范围以卡面描述为准。

## 0. 五个子包的分层关系

```
bootstrap ──声明──▶ registry.capability_registry ──装配──▶ orchestrator/TurnEngine（卡外）
registry.tool_registry ◀──执行── agentic.tool_dispatch
providers.view ──组装──▶ registry.scoped_registry + registry.deferred_tools
agentic.loop/labeled_step ◀──读/写── registry.deferred_tools（live tool_schemas）
coordination ◀──被引用── app/container、services/session/turns/*（进程外卡）
```

- `agentic` 自述分层：labels→client→usage→labeled_step→tool_dispatch→loop（`deeptutor/runtime/agentic/__init__.py:7-20`），全部经 `__getattr__` 懒导出（`deeptutor/runtime/agentic/__init__.py:74-80`）；registry 同样懒导出（`deeptutor/runtime/registry/__init__.py:7-29`）。
- `providers` 刻意位于 registry 之下且 `view` 不做包级 re-export，避免 registry↔providers 循环导入（`deeptutor/runtime/providers/__init__.py:11-26`）。
- 导入分层有守卫测试：`tests/runtime/test_import_layering.py`、`tests/runtime/test_api_import_memory_boundary.py`。

## 1. agentic：工具分发与流式思考

### 1.1 标签协议（labels / labeled_step）

- 协议约定：每轮回复第一行是双反引号包裹的 `LABEL`，其后是正文；标签集由调用方声明（research 用 `(THINK, TOOL, APPEND, FINISH)`，报告子相用单终态标签；chat 已改走原生 tool calling，不再是调用方，`deeptutor/runtime/agentic/labels.py:9-21`）。
- 流式探测 `classify_label`：容忍一/三反引号变体与裸标签回退，前缀窗口 64 字符（`LABEL_PROBE_MAX_CHARS`，`deeptutor/runtime/agentic/labels.py:29`；解析主逻辑 `labels.py:45-106`）。
- 流结束后再读一次 `recover_finished_label`，接受未闭合/超宽围栏（`deeptutor/runtime/agentic/labels.py:109-149`）；`find_inline_labels` 只把"行首+分隔符"形态算作协议违规，正文里的提及不算（`labels.py:152-173`）。
- 单轮执行 `run_labeled_step`（`deeptutor/runtime/agentic/labeled_step.py:139-665`）是全包最重的函数，职责：
  - 标签前状态机：reasoning 模型把 `<think>...</think>` 内联在标签之前时，流入推理子迹并继续探针（`labeled_step.py:75-86` 正则；`_ingest_pre_label` `378-444`）；
  - 请求降级重试：`stream_options`/tool schema/图片输入三类不被支持时自动重试（`_create_response_stream`，`labeled_step.py:452-492`）；
  - `reasoning_content` 流入同一推理子迹并全程累积，供下一轮回放（`labeled_step.py:556-573`、`218`）；
  - 收尾：流结束时解析残标签（`595-615`），usage 只记一次（`record_streamed_usage`，`621-626`），关闭子迹（`628-637`），`clean_thinking_tags` 清洗返回文本（`639-644`）；
  - `LabeledStepResult.reasoning_only` 区分"纯思考无答案"与"真的什么都没说"（`labeled_step.py:124-136`，`659-664`）——quiz 计划步曾把空串读成零题（#1318）。
- 内联 `<think>` 拆分器 `InlineThinkFilter` 独立于 labeled_step，供 agent_loop 等其他执行器复用（`deeptutor/runtime/agentic/think_stream.py:39-83`；跨包使用点 `deeptutor/agents/loop/agent_loop.py:50,1138,1627`）；持有最多 24 字符尾部等跨 chunk 的闭合标签（`think_stream.py:36`）。

### 1.2 流式 tool-call 累积（tool_call_stream）

- 三条铁律：`id`/`name` 整体到达只赋值不追加；`arguments` 是分片必须拼接；provider 扩展（Gemini `extra_content` 思考签名）整体保留（`deeptutor/runtime/agentic/tool_call_stream.py:6-12`）。历史上"追加 id"曾把 id 涨到 47241 字符致死 #937（`tool_call_stream.py:14-20`）。
- `ToolCallAccumulator.collected()` 为缺 id 的调用生成位置回退 id（`tool_call_stream.py:91-109`）；services 层的 `openai_compat_provider._accum_tc` 是平行实现，未合并以免扩大影响面（`tool_call_stream.py:22-25`）。

### 1.3 客户端与补全参数（client）

- `LLMClientConfig`（`deeptutor/runtime/agentic/client.py:69-98`）在 `__post_init__` 里让 `api_format` 与 `wire_api` 永不冲突。
- `build_openai_client` 返回事件循环内缓存的有界客户端池（maxsize=2，`client.py:64-66`；主逻辑 `234-269`；关闭/复位 `272-294`）——连接池复用避免每轮新建 socket 高水位。
- 分派顺序（`_build_openai_client`，`client.py:123-182`）：Responses API 走 `OpenAICompatProvider` 适配（`147-159`）→ 原生后端适配器（anthropic/openai_codex/github_copilot/codebuddy，映射表 `361-366`，分派 `369-394`）→ 普通 `AsyncOpenAI`/`AsyncAzureOpenAI`（`175-182`）。api_key 传列表时自动装 429 轮换客户端（`185-214`）。
- `_ProviderOpenAIAdapter` 把原生 provider 伪装回 OpenAI chat-completions 形状（`client.py:397-464`）；流式包装 `_ProviderOpenAIStream` 把 provider 的 `finish_reason=="error"` 还原成异常而不是当正文流出（`_raise_for_error_response`，`535-566`），并把 Anthropic 签名 thinking blocks 放回最终 chunk（`627-635`）。
- `can_use_native_tool_calling` 的解析序：用户在设置里声明的模型能力 > 原生后端 > 本地/黑名单绑定直接否 > 显式 supports_tools > 云端 openai_compat 默认可（`client.py:751-786`；黑名单 `52-54`）。
- `build_completion_kwargs` 合成 temperature+token 上限+推理档位，模型内建覆盖最后生效，None 值删参（`client.py:699-726`）。

### 1.4 并行工具分发（tool_dispatch / tool_arg_guard）

- 入口 `dispatch_tool_calls`（`deeptutor/runtime/agentic/tool_dispatch.py:122-354`）。每条 assistant 消息的并行预算 `MAX_PARALLEL_TOOL_CALLS=15`（`tool_dispatch.py:48`），超限的调用补 stub role=tool 消息保证下一次 API 调用的配对完整（`341-353`）。
- 一轮内三个有序阶段（`tool_dispatch.py:288-325`）：①rebinding 工具串行（两把即交接不是竞争）→ ②普通工具并发 → ③pause 工具（`ask_user`/`workspace_export`，`PAUSE_LAST_TOOLS` `55`）重新绑定参数后最后跑——它们的展示内容依赖本轮已提交的状态。pause 工具豁免超时与重试（`234-238,260-261`）。
- 同批去重：同名同参短路为 stub；pause 工具更严——批内第二个 pause 一律视为重复（`_detect_duplicate_calls` `357-389`，stub 文案 `392-421`）。
- 参数前置校验在 tool_arg_guard：required 且无默认值的参数缺失/为空时拒绝分发，role=tool 正文直接告诉模型缺什么（`deeptutor/runtime/agentic/tool_arg_guard.py:66-136`，文案 `153-195`；动机 #779/#1101 见模块 docstring `1-25`）。dispatcher 侧的接线与"空参数拒绝"trace 状态在 `_reject_if_args_missing`（`tool_dispatch.py:424-504`）。
- `execute_tool_call`（`tool_dispatch.py:647-826`）是单工具直调入口：超时+重试包在 `_execute_with_policy`（`721-750`）；终态用 `call_state` 的 progress 而非流 ERROR——ERROR 会让 partner 轮整体重跑并重复执行有副作用工具（`783-812` 注释）；`result.success=False` 被读成 error 终态（`766-772`）。
- 结果聚合 `_collect_outcome`（`829-926`）：第一个 terminate、第一个 pause 各自生效且互斥；敏感参数与 `_` 前缀服务端参数不出现在 trace（`190-199`，敏感名收集 `633-644`）；模型可见图片消息限 2 张（`886-897`）。
- 每工具子迹的 call_id 在分发前分配（`_build_per_tool_trace_meta`，`568-615`）；别名与默认参数在服务端增强前解析（`_resolve_tool_request`，`542-565`）。

### 1.5 迭代调度（loop）与消息/用量

- `LabelProtocol` 四个正交集合：allowed/terminal/intermediate/final + tool_label（`deeptutor/runtime/agentic/loop.py:42-67`）；"intermediate 且 final"表示"流式给用户但不停轮"（chat 的 PAUSE，`loop.py:49-58,379-386`）。
- 能力差异全部进 `LoopHost` 协议（`loop.py:82-173`）：上下文窗裁剪、迭代迹、工具分发、pause 恢复、终态校验、`force_finalize`（迭代预算耗尽后的自救，`423-430`）、可选 `before_iteration`/`on_intermediate` 钩子（`136-173`）。循环本体不认识任何能力。
- 主循环 `run_agentic_loop`（`loop.py:209-439`）：违规分类（无标签/多标签/带工具的错标签，`442-464`）→ 重试提示+修复消息（草稿截断 500 字符保留进历史，`486-513`）→ 终态验收 → 工具轮（把 reasoning/thinking_blocks 带回 assistant 消息，`341-353`）→ pause/terminate 处理（`366-376`）。
- 请求局部图片永不入持久历史，只临时插到对应 tool 消息后（`loop.py:247-252,176-206`）。
- 消息构造：`assistant_message_with_tool_calls` 回放 reasoning（DeepSeek #1058）与签名 thinking_blocks，并透传 Gemini `extra_content`（`deeptutor/runtime/agentic/messages.py:8-55`）；`assistant_message` 同理（`58-76`）。
- `UsageTracker` 双路记账：provider usage 帧（`add_from_response`）与 chars/3.5 估算回退（`add_estimated`），`summary()` 用定价表算 `total_cost_usd`（`deeptutor/runtime/agentic/usage.py:13-98`）；BaseAgent 适配入口 `add_usage`（`51-78`）。
- 消费方：chat 流水线直调 `dispatch_tool_calls` 并组装 provider 视图（`deeptutor/agents/loop/pipeline.py:70,613,1115-1131`）；research/question 流水线与 PageIndex 推理使用 `run_agentic_loop`（`deeptutor/agents/research/pipeline.py`、`deeptutor/agents/question/pipeline.py`、`deeptutor/services/rag/pipelines/pageindex/reasoning.py`）。

## 2. coordination：进程无关的轮协调

- 端口协议 `RuntimeCoordinator`（`deeptutor/runtime/coordination/protocol.py:10-71`）：turn 租约 acquire/renew/release、事件 publish/read、命令 submit/read、后台命令（带 leader 租约校验的 ack）、leader 租约、health/close。值对象集中在 `types.py`：`TurnLease` 含 fencing_token（`deeptutor/runtime/coordination/types.py:44-50`）、`LeaderLease`（`53-57`）、状态/失败码/命令枚举（`12-41`）。
- 单进程实现 `MemoryCoordinator`：asyncio.Lock 保护，fencing token 单调递增（`deeptutor/runtime/coordination/memory.py:19,45`）；同会话同时只允许一个活跃轮（`39-56`）；事件按 seq 幂等，冲突即抛（`107-125`）；后台命令游标 `acknowledge_background_command` 可选校验 leader 租约（`200-214`）。
- 多 worker 实现 `RedisCoordinator`（`deeptutor/runtime/coordination/redis.py:186-558`）：全部关键操作是 Lua 脚本（脚本区 `16-179`）——租约获取原子检查会话占用并 INCR fence（`_ACQUIRE_TURN_LUA` `16-40`），事件发布处理请求 seq 的幂等/冲突（`_PUBLISH_EVENT_LUA` `84-112`），命令提交用 SET NX 去重（`_SUBMIT_COMMAND_LUA` `114-123`）。Redis 异常一律包成 `CoordinationUnavailableError`（`12-13`），如 `acquire_turn` `218-242`。
- `TurnEventJournal`（`deeptutor/runtime/coordination/journal.py:15-89`）：先发布到共享流再批量落库（batch=25/0.25s，`21-23`）；落库失败回滚缓冲（`52-61`）；`flush_terminal` 保证终态迁移前共享流事件全部持久（`65-77`）；`replay` 合并 durable+live 并检测冲突（`79-89`）。当前仅测试接线（`tests/runtime/coordination/test_journal_recovery.py:8`）。
- `TurnRecoveryService`（`deeptutor/runtime/coordination/recovery.py:15-101`）：leader 专属，扫描过期轮、发布 WORKER_LOST 的 error+done 事件并转移 FAILED（`55-101`）；找不到仓库的 turn 不 ack，留给后续 scope 认领（`32-39` 注释）。实际接线在 `deeptutor/app/container.py:139-187`（`recover_once`，逐用户/workspace 构建 recovery，`181-185`）。
- 装配与校验 `CoordinationSettings`（`deeptutor/runtime/coordination/settings.py:17-78`）：`backend_workers>1 必须 redis`、redis 必须给 url、TTL≥10s 且 renew<TTL（`49-67`）；`create_runtime_coordinator` 建后先 health 检查（`81-96`）。`runtime_report` 不泄露 Redis URL（`69-78`）。

## 3. registry：工具与能力注册表

- `ToolRegistry`（`deeptutor/runtime/registry/tool_registry.py:26-164`）：进程级单例（`get_tool_registry`，`170-176`）。内置工具按需实例化——`load_builtins` 只登记 import 便宜的 spec 描述符（`55-57`），`get` 未命中时才 `spec.create()`（`59-73`）。别名与默认参数经 `TOOL_ALIASES` 合并（`75-94`）；`execute` 的 name 是 positional-only，避免与名为 `name` 的工具参数撞车（`151-164`）。
- `CapabilityRegistry` 是 CapabilityCatalog 之上的 turn 兼容门面，每次 `get` 都新建实例（`deeptutor/runtime/registry/capability_registry.py:57-64,140-142`）。内置能力从 bootstrap 的 class_path 懒加载（`84-100`）；插件走 entry-point 组 `deeptutor.extensions`（`26,102-116`），旧 `deeptutor.plugins` 组带弃用告警兼容（`118-138`）。
- `ScopedToolRegistry`（`deeptutor/runtime/registry/scoped_registry.py:40-172`）：每轮的读穿视图——overlay（用户自有 MCP/CLI/资源工具）优先于进程注册表；与共享工具撞名的 overlay 条目直接丢弃（`62-71`）。**关键设计：授权放在 execute 而非 manifest**——模型可以凭空调制工具名，只有分发必经的 `execute` 才是真闸（模块 docstring `1-20`；实现 `129-150`，拒绝返回中性 ToolResult `152-154`）。
- `DeferredToolLoader` + `render_deferred_tools_manifest`（`deeptutor/runtime/registry/deferred_tools.py`）：渐进披露——deferred 工具（MCP 默认）只在系统提示里占一行清单，模型调 `load_tools` 后 schema 追加进 live 列表，循环每轮重读即生效（模块 docstring `1-16`；`bind_live_schemas`/`load` `149-193`）。加载白名单在 loader 处再验一次，模型不能靠猜名字加载越权工具（`134-139,184`）；已加载名单按会话持久化（`195-201`）。

## 4. providers：外部工具提供者的授权与装配

- `Allowlist`（`deeptutor/runtime/providers/allowlist.py:23-63`）：把"无限制"建模成显式状态（names=None），`narrow`/`widen` 对无限制侧全纯——修复了裸集合运算里 `(base or set()) | extra` 把无限制静默收缩成 extra 的错误方向（模块 docstring `1-15`）。
- `ToolScope`（`deeptutor/runtime/providers/scope.py:16-39`）：每轮的纯输入记录——owner_id（所有者身份，非"当前用户"）、workspace_mcp（None 继承/空禁用）、is_partner、caller_whitelist、exclusive_capability。
- `authorize_mcp_tools`（`deeptutor/runtime/providers/authorize.py:26-56`）：MCP 按工具名授权。partner 轮只看自己的配置过滤器、不隐式回退无限制；自有服务器按所有权授权（`owned_names` widen）；排他知识能力直接清空（`44-45`）。故意每 kind 一个函数而非统一策略接口（docstring `1-15`）。
- `providers.text`（`deeptutor/runtime/providers/text.py`）：第三方文本进提示词前的唯一清洗点——清单行压成单行、去控制/零宽/BiDi 字符、180 字符封顶（`28,40-57`）；CLI 用法文档保形清洗、6000 字符封顶（`34,60-83`）。
- `build_tool_view`（`deeptutor/runtime/providers/view.py:70-93`）是每轮的组装缝：**契约是不抛异常**——provider 挂了就降级为"本轮无外部工具"（`89-93`）。装配流程（`_build`，`96-185`）：启动共享 MCP manager → 收集 shared/owned/cli/overlay 四池（`111-117`）→ 授权+narrow/widen（`121-150`）→ 过滤出 pool → 建 ScopedToolRegistry（overlay 只进本轮视图，`157-165`）→ 建 loader（预载已加载+资源授权名，`171-179`）→ 渲染清单（排他能力抑制，`180-184`）。自有服务器连接限时 3 秒（`36,196-216`）——这是首轮流事件前唯一的第三方网络等待。

## 5. bootstrap：内置能力引导

- 整个包只有两个声明式表：`BUILTIN_CAPABILITY_CLASSES`（名字→class_path，`deeptutor/runtime/bootstrap/builtin_capabilities.py:35-48`）与 `BUILTIN_CAPABILITY_SPECS`（名字→class_path+manifest，`51-257`），manifest 携带 stages/tools_used/cli_aliases/config_defaults（构造器 `16-32`）。
- 设计动机是"import-free 描述符"（`builtin_capabilities.py:1`）：import 本包不触发任何能力模块导入，实例化推迟到 `CapabilityRegistry.load_builtins` 注册的工厂（`deeptutor/runtime/registry/capability_registry.py:90-99`）真正被 `get` 调用时。
- 消费链：`deeptutor/app/container.py:89-93`（容器启动时 load_builtins+load_plugins）→ `TurnEngine`（`container.py:93`）→ 路由到能力实例；request schema 由 `CAPABILITY_CONFIG_MODELS` 对齐（`capability_registry.py:73,98`）。

## 6. 与 launcher 的交接点

launcher（`docs/guides/launcher` 卡）只负责把进程拉起来；五个子包都在 uvicorn 后端进程内生效，交接发生在 `deeptutor.api.main:app` 启动序列：

1. launcher 以 `uvicorn deeptutor.api.main:app` 拉起后端（`deeptutor/runtime/launcher.py:1446-1447`），workers 数来自 system.json。
2. API 首次请求容器时 `get_application_container()` → `ApplicationContainer.build()`（`deeptutor/app/container.py:339-343,104-120`）：按 `CoordinationSettings.from_runtime_settings` 选 Memory/Redis 协调器——这是 coordination 子包进入服务期的时刻；`start()` 健康检查失败拒绝启动（`122-128`）。
3. 容器同时装配 registry 子包（capability registry + TurnEngine，`container.py:89-95`）并构造 `TurnApplicationService`（`96-100`）。
4. API 层把 `application_container.coordinator` 交给 `BackgroundLeaderSupervisor`（`deeptutor/api/main.py:289-306`）——background_leader 卡的入口；leadership 租约与后台命令消费都在 coordination 协议之上（`deeptutor/runtime/background_leader.py:10,25`）。
5. 轮执行链在 turns 服务内使用租约：acquire（`deeptutor/services/session/turns/request_preparer.py:555`）、renew（`deeptutor/services/session/turns/lifecycle.py:285`）、事件发布（`lifecycle.py:666`）、release（`deeptutor/services/session/turns/executor.py:1416`）。
6. `deeptutor doctor` 用 `create_runtime_coordinator` 做协调体检（`deeptutor/services/doctor.py:478-489`）。
7. chat 轮内，agentic 与 registry/providers 在 `deeptutor/agents/loop/pipeline.py` 汇合：`build_tool_view` 组装本轮工具面（`pipeline.py:613`），`dispatch_tool_calls` 执行（`pipeline.py:1115-1131`）。

## 7. 阅读路线建议

- 只想懂"一轮 chat 怎么跑"：`app/container.py:104-120` → `agents/loop/pipeline.py:613,1115` → `agentic/loop.py:209` → `agentic/tool_dispatch.py:122` → `agentic/labeled_step.py:139`。
- 只想懂"多 worker 怎么不打架"：`coordination/settings.py:17` → `coordination/redis.py:16-179`（Lua）→ `services/session/turns/lifecycle.py:285` → `coordination/recovery.py:25`。
- 只想懂"模型为什么看不到某工具"：`providers/view.py:70` → `providers/authorize.py:26` → `registry/scoped_registry.py:129` → `registry/deferred_tools.py:171`。
- 测试入口：`tests/core/agentic/`（tool_dispatch/think）与 `tests/core/test_labeled_step_*.py`、`tests/runtime/coordination/`、`tests/runtime/registry/`、`tests/runtime/providers/`。
