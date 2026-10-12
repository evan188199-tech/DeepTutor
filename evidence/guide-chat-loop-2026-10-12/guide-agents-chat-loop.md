# agents/chat 循环层内部导读：think_stream / dsml_tool_calls / context_budget

> 范围声明：本文只深入 **chat 循环层**（`deeptutor/agents/chat` 薄绑定 + `deeptutor/agents/loop` 引擎 +
> `deeptutor/runtime/agentic` 共享流原语）的三个子面。agents 顶层总览见 guide-agents 卡；三个面的
> 行为细节以测试为准：`tests/agents/chat/test_agent_loop.py`（think 流）、`test_dsml_tool_calls.py`、
> `test_context_budget.py`。本文持产品代码视角，测试只作协作点引用。
>
> 基线：origin/main @ `6cf793bd868ba5ecbe64722936d4be8fab5a01df`（v1.6.14）。所有 `path:line`
> 均对照该提交核验。

---

## 0. 循环层总览：一个 chat turn 是什么

一个 chat turn = **一轮 agent loop**，跑在一条持续增长的会话消息列表上（`agent_loop.py:1-30`）：

- 每轮 = 一次 LLM 流式调用（`AgentLoop._call_llm`，`deeptutor/agents/loop/agent_loop.py:1037`）。
  文本随生成即流出（`content` 事件），工具调用派发后把 `role=tool` 结果追加回会话（`agent_loop.py:719-728`）。
- 某轮**不**调用工具 ⇒ 该轮文本即最终答案，循环结束（`agent_loop.py:480-481`）。
- 探索轮预算耗尽后进入小额结算阶段（`MAX_SETTLEMENT_ROUNDS = 3`，`agent_loop.py:100`），
  仍失控则强制无工具收尾（`_forced_finish`，`agent_loop.py:837`）。

分层与数据流（自上而下）：

```
ChatCapability.run (agents/chat/capability.py:25)
  └─ AgenticChatPipeline (agents/chat/agentic_pipeline.py:36)   ← chat = 默认绑定，几乎零覆写
       └─ AgenticLoopPipeline (agents/loop/pipeline.py:200)     ← 组装：prompt blocks / 工具面 / 派发
            └─ AgentLoop.run (agents/loop/agent_loop.py:309)
                 └─ _run_loop 轮循环 (agent_loop.py:403)
                      └─ _call_llm 每轮 (agent_loop.py:1037)
                           ├─ think_stream   ← 内容流的"思考/正文"分流
                           ├─ dsml_tool_calls← 内容流里的文本工具调用兜底
                           └─ (轮末) context_budget ← 事后测量本轮真实请求
```

三个面的角色一句话：

| 子面 | 文件 | 一句话职责 |
|---|---|---|
| think_stream | `deeptutor/runtime/agentic/think_stream.py` | 把混在 content 通道里的内联 `<think>` 推理在流式时切到 trace 通道 |
| dsml_tool_calls | `deeptutor/agents/loop/dsml_tool_calls.py` | 把 DeepSeek 文本协议（DSML）工具调用还原成结构化调用并清洗正文 |
| context_budget | `deeptutor/agents/loop/context_budget.py` | 事后测量"最后一次真实请求"的窗口占用，产出 composer 读数 |

---

## 1. 面 1：think_stream 思考流

### 1.1 要解决的问题

推理模型把推理放在两个位置：专用通道（`delta.reasoning_content` / provider 扩展字段），
或**直接写进 content 通道**、用 `<think>`/`<thinking>` 标签包裹（Qwen thinking、DeepSeek-R1
经若干代理、不少本地部署）。第二类若不在流式时切开，下游全错：气泡显示模型私语、持久化
消息带推理、循环的结束判定把推理当答案（`think_stream.py:1-20`）。

### 1.2 机制：InlineThinkFilter 流式状态机

- 两个正则界定进出：`THINK_OPEN_RE` / `THINK_CLOSE_RE`（`think_stream.py:33-34`），大小写不敏感，
  兼容 `<think>` 与 `<thinking>`。
- `InlineThinkFilter.feed(chunk)` 返回 `[(kind, text)]`，kind ∈ `{"content", "thinking"}`
  （`think_stream.py:39-72`）。内部维护 `_in_think` 布尔态，逐段切换。
- **holdback**：块尾疑似标签开头（最近一个 `<` 距尾 ≤ `_TAG_HOLDBACK_CHARS=24` 且未见 `>`）
  时扣住不发，等下一块再判（`think_stream.py:35-36, 61-68`）——避免 `<t` 被当正文漏出。
- `flush()` 在流结束时释放残余（`think_stream.py:74-80`）。未闭合的 `<think>` 全程按
  thinking 处理，永不漏成正文。
- 非流式一次性版本 `split_inline_think(text)`（`think_stream.py:86-93`），供整段收集的执行器用。

### 1.3 数据流（loop 内接线）

在 `_call_llm` 的每个重试尝试里新建过滤器（`agent_loop.py:1171`），content 增量先经 DSML
过滤器、再经 think 过滤器，最后统一进 `_emit_segments`（`agent_loop.py:1385-1394`）：

```
delta.content ─→ dsml_filter.feed ─→ think_filter.feed ─→ _emit_segments
                                                            ├─ kind=thinking → stream.thinking (trace)
                                                            └─ kind=content  → stream.content (读者)
                                                                 （forced_tool_choice 轮: 内容不发）
流末: dsml_tail = dsml_filter.flush() → think_filter.feed → _emit_segments
      再 think_filter.flush()                                  (agent_loop.py:1523-1526)
```

`_emit_segments`（`agent_loop.py:1178-1208`）的路由规则：

- `thinking` 段：计 `reasoning_chars`、触发"仍在推理"进度提示（15s 节流，
  `agent_loop.py:1210-1244`），发 `stream.thinking` 进 trace（`runtime/stream_bus.py:173`）。
  forced-tool 轮同样记录（`agent_loop.py:1182-1194`）。
- `content` 段：进 `visible_text_parts`；正常轮发 `stream.content`
  （`runtime/stream_bus.py:156`）；`forced_tool_choice` 轮的内容是"为了产调用而写"，不发读者
  （`agent_loop.py:1198-1202`）；capability 缓冲轮（`defer_visible_output`）暂扣。

**专用通道的推理不走该过滤器**，直接分路：`delta.reasoning_content`/`delta.reasoning`
（`agent_loop.py:1369-1383`）、provider 扩展 `reasoning_content` 与 native reasoning items
（`agent_loop.py:1328-1364`）、带签名的 `thinking_blocks`（`agent_loop.py:1315-1319`）——
最终都进 `stream.thinking` 与 `LLMCallResult.reasoning_content/thinking_blocks`。

### 1.4 会话回放与答案清洗（协作点）

- **原始文本（含标签）原样回写会话**：`_assistant_round_message` 保留 `result.text`，因为那是
  模型期待看到的转录（`think_stream.py:14-15`；消息构造 `agent_loop.py:224-245`）。
- 面向读者的最终文本用 `_clean` = `clean_thinking_tags`（按 binding/model 清洗，
  `agent_loop.py:398-399`）。
- 只有推理没有行动的轮次会被推一把：`_reasoning_budget_exhausted` 判定
  （`agent_loop.py:126-150`）→ 续写指令或重试（`agent_loop.py:480-567`）；纯推理空收尾有
  `MAX_REASONING_ONLY_RECOVERIES = 2` 次恢复后强制收尾（`agent_loop.py:105, 568-627`）。
- 元数据里 `reasoning_budget_exhausted`/`reasoning_chars` 随 `call_status` 发出
  （`agent_loop.py:1601-1645`）。
- 循环层之外的同款复用：labeled step 执行器用 `post_label_think = InlineThinkFilter()`
  处理标签后正文（`runtime/agentic/labeled_step.py:215`）；`labels.py:20` 的设计说明指向这里。

### 1.5 索引

| 关注点 | 位置 |
|---|---|
| 模块动机与位置选择（为何在 runtime 层） | `deeptutor/runtime/agentic/think_stream.py:1-20` |
| 正则与 holdback 常量 | `deeptutor/runtime/agentic/think_stream.py:33-36` |
| 流式过滤器 | `deeptutor/runtime/agentic/think_stream.py:39-83` |
| 非流式入口 | `deeptutor/runtime/agentic/think_stream.py:86-93` |
| content 增量的双过滤器接线 | `deeptutor/agents/loop/agent_loop.py:1385-1394` |
| 段路由（thinking→trace / content→读者） | `deeptutor/agents/loop/agent_loop.py:1178-1208` |
| 尾部 flush 顺序 | `deeptutor/agents/loop/agent_loop.py:1523-1526` |
| 专用推理通道接线 | `deeptutor/agents/loop/agent_loop.py:1315-1383` |
| 推理进度提示 | `deeptutor/agents/loop/agent_loop.py:1210-1244` |
| 推理-only 恢复上限 | `deeptutor/agents/loop/agent_loop.py:105, 568-627` |
| 其他执行器复用 | `deeptutor/runtime/agentic/labeled_step.py:215` |

---

## 2. 面 2：dsml_tool_calls 工具调用解析

### 2.1 要解决的问题

部分 DeepSeek 部署（尤其本地/自建 OpenAI 兼容端点）不声明原生 function calling，把工具调用
以 DSML 标记写进 assistant **content** 通道（`<｜｜DSML｜｜invoke name="...">` 方言）。
不解析则标记流给用户、工具永不执行（issue #666，`dsml_tool_calls.py:1-23`）。

### 2.2 两个入口

**① 流式抑制：`DSMLStreamFilter`**（`dsml_tool_calls.py:63-143`）

- 增量删除**完整**的 DSML 包络与 invoke 块；调用前/间/后的正文立即放行——一次工具调用不能
  把整轮输出劫持到别的通道（类文档 `dsml_tool_calls.py:63-71`）。
- 状态机：遇到 `tool_calls` 开标签则等闭包络（`_pending_close`，`dsml_tool_calls.py:122-127`）；
  遇 `invoke` 开标签等闭标签（`dsml_tool_calls.py:128-130`）；裸 `<` 无 `>` 时最多等
  `_MAX_PARTIAL_TAG_CHARS = 512` 字符，超限按普通正文逐字放行（`dsml_tool_calls.py:58-60,
  111-119`）。
- `flush()` 释放残余并对完整未包络调用做清洗，**残缺 invoke 原样放出**而不是静默吞掉
  provider 输出（`dsml_tool_calls.py:138-143`）。
- 标签前缀宽松匹配（`<[^>]*?invoke ...>`），特殊 token 的确切字节不重要
  （`dsml_tool_calls.py:20-22`）。信号判定用 `DSML_SIGNAL_RE`，"提到 tool_calls 的散文"
  不误报（`dsml_tool_calls.py:31-37, 207-211`）。

**② 完整解析：`extract_dsml_tool_calls(text, tool_schemas)`**（`dsml_tool_calls.py:235-284`）

- 用 `_INVOKE_RE`/`_PARAM_RE` 抽出 `(name, args)` 列表，产出标准
  `{"id": "dsml_<i>", "name", "arguments": <json str>}`（`dsml_tool_calls.py:255-275`）。
- **schema 感知的类型强制**（`_coerce_param_value`，`dsml_tool_calls.py:173-204`）：DeepSeek
  把所有参数标 `string="true"`，但声明为 array/object 的容器 schema 优先于线缆提示——先尝试
  `json.loads` 并校验类型匹配（`_schema_types` 展开 anyOf/oneOf/allOf 及 items/properties 推导，
  `dsml_tool_calls.py:151-170`）；显式 string 契约保留原文；未标记标量解析失败则保留原串。
- 返回 `(tool_calls, cleaned_text)`；无良构 invoke 时 `cleaned_text is text`，调用方把
  "无调用"当"非 DSML 轮"原样落下（`dsml_tool_calls.py:243-247, 277-278`）。

### 2.3 数据流（loop 内接线）

```
流式中  delta.content ─→ dsml_filter.feed(content) ─→ 可见正文（DSML 块被吞）   (agent_loop.py:1392)
流末    dsml_tail = dsml_filter.flush() ─→ think_filter ─→ _emit_segments      (agent_loop.py:1523-1525)
轮末    text = "".join(text_parts)        （text_parts 存的是未经 DSML 清洗的原始 content）
        dsml_calls, cleaned = extract_dsml_tool_calls(text, self._tool_schema_catalog)
        若有调用: 无原生调用 ⇒ tool_calls = dsml_calls；text = cleaned_text        (agent_loop.py:1543-1552)
之后    正常派发: pipeline._dispatch_tool_calls(tool_calls=…)                    (agent_loop.py:719-725)
```

关键协作点：

- **原生优先，防双发**：即使 provider 同时发了原生 `delta.tool_calls`，也总是解析/清洗标记，
  但有原生调用时采用原生列表（`agent_loop.py:1543-1552`）。原生侧的增量由
  `ToolCallAccumulator` 按线缆协议折叠（id/name 整体赋值、arguments 拼接、扩展保留；
  `runtime/agentic/tool_call_stream.py:1-19, 35`）。
- **schema 目录恒保留**：provider 拒绝原生 `tools` 后续轮退到 DSML 时，解析器仍需声明的参数
  类型 ⇒ 构造时单独存 `self._tool_schema_catalog`（`agent_loop.py:293-296`），轮末解析传入
  （`agent_loop.py:1548`）。
- **forced-tool-choice 兜底**：provider 收了 `tool_choice` 却忽略时，缓冲的整段文本经全新的
  DSML+think 过滤器放出，不让答案丢失（`agent_loop.py:1677-1683`）；ask_user 模式下还会把
  缓冲问题转成本地 ask_user 卡（`agent_loop.py:1554-1583`）。
- 截断警示：写工具调用写到 token 上限的轮次，其调用可能不完整，发出
  `notices.tool_call_truncated`（`agent_loop.py:670-691`）。

### 2.4 索引

| 关注点 | 位置 |
|---|---|
| 模块动机（issue #666）与方言示例 | `deeptutor/agents/loop/dsml_tool_calls.py:1-23` |
| 信号/结构正则、512 上限 | `deeptutor/agents/loop/dsml_tool_calls.py:34-60` |
| 流式过滤器 DSMLStreamFilter | `deeptutor/agents/loop/dsml_tool_calls.py:63-143` |
| 容器 schema 优先的类型强制 | `deeptutor/agents/loop/dsml_tool_calls.py:151-204` |
| 信号判定 | `deeptutor/agents/loop/dsml_tool_calls.py:207-211` |
| 完整解析入口 | `deeptutor/agents/loop/dsml_tool_calls.py:235-284` |
| schema 目录保留 | `deeptutor/agents/loop/agent_loop.py:293-297` |
| 流式接线（feed/flush） | `deeptutor/agents/loop/agent_loop.py:1392, 1523-1525` |
| 轮末解析与原生优先合并 | `deeptutor/agents/loop/agent_loop.py:1543-1552` |
| 原生增量折叠 | `deeptutor/runtime/agentic/tool_call_stream.py:35` 起 |
| forced-tool 兜底释放 | `deeptutor/agents/loop/agent_loop.py:1677-1683` |

---

## 3. 面 3：context_budget 预算

### 3.1 设计立场

给 composer 的"窗口占用"读数。两个硬约束（`context_budget.py:1-12`）：

1. **只测已组装材料**：测的是产生系统提示串的那份 `PromptBlock` 列表、进 call kwargs 的
   tool schemas、最终调用的消息列表——重新推导任何一部分都会让读数与实际发出内容漂移。
2. **永不抛错**：读数是信息性附加物，测量失败返回 `None`，字段整体缺省
   （`build_context_budget`，`context_budget.py:141-170`）。

### 3.2 输入：三份"现场证据"从哪来

- **blocks**：`AgenticLoopPipeline._build_system_prompt` 只调用一次 `assembler.blocks()` 并把
  结果存进 `self._last_prompt_blocks`，随后 `split_for_replay` 分离稳定块/运行时快照、`render`
  出系统提示串（`pipeline.py:436-464`；blocks 组装 `prompt_blocks.py:119-191`；"组装一次、
  渲染同一份"的原则 `prompt_blocks.py:81-97`、`pipeline.py:265-267`）。这样测的就是**发出的
  那份**系统提示，二次 `blocks()` 可能已漂移。
- **request 快照**：每轮 `_call_llm` 在发请求前拍 `LLMRequestSnapshot(messages=浅拷贝列表,
  tool_schemas)`（`agent_loop.py:1119-1134`；快照定义与"浅拷贝"理由 `context_budget.py:57-67`）。
  循环每轮往后追加消息、延迟加载器往后追加 schemas，预算描述的是**某一次请求**而非列表终态。
  forced-finish 轮故意不带 `tools`，此时沿用上一非空 schema 列表（`agent_loop.py:1124-1131`）。
- **deferred 工具面**：`measure_context_budget` 补充已加载延迟工具名集合与未加载数
  （`pipeline.py:1660-1675, 1677-1688`）。

### 3.3 计量：_build 的分段与不变量

`build_context_budget` → `_build`（`context_budget.py:141-238`）把窗口占用切成段：

| 段 key | 来源 |
|---|---|
| `system_prompt` | 稳定块（含 `general`/`runtime_policy`/`loop` 固定前奏 trio）按渲染形态计（`"## name\n"` 头随块走，`_prompt_block_tokens`，`context_budget.py:241-253`）+ 渲染开销（`---` 分隔与语言指令 = 实发 system 串 − 块之和，`_render_overhead`，`context_budget.py:256-278`）|
| 运行时快照块 | 有 `_context_snapshot` 消息时，`RUNTIME_BLOCK_NAMES` 块单列（`context_budget.py:185-194`；快照名集 `prompt_blocks.py:27-40`）|
| 各专名段 | `persona_style`/`memory`/`learning_journal`/`tools`(tool_manifest)/`knowledge_base_note`/`skills`/`sources`/`extended_tools`/`notebooks`/`workspace`/`partner_turn_policy`（映射表 `_BLOCK_SEGMENTS`，`context_budget.py:37-54`）|
| `capability` | 其余具名块（能力 playbook）合并求和（`context_budget.py:36, 250`）|
| `system_tools` / `mcp_tools` | 实发 schemas 按是否在已加载延迟集合中分流（`_tool_schema_tokens`，`context_budget.py:281-293`）|
| `messages` | 会话消息 token − 动态块已计部分，去重防双计（`count_conversation_tokens` 跳过首个 system，`context_budget.py:124-138`；`_message_tokens` 计文本 part、tool_calls 参数与多模态文本——图像不可计，`context_budget.py:296-312`）|

不变量：`used_tokens == sum(segments[].tokens)` **由构造保证**——先排序一次，段与总量都从
同一 ranked 列表派生（`context_budget.py:211-220`）。`free_tokens` 下限 0（`context_budget.py:230`）。

窗口解析 `resolve_window_info`（`context_budget.py:77-105`）：配置值原样采信、**刻意不走**
`resolve_effective_context_window` 的 `MAX_EFFECTIVE_CONTEXT_WINDOW` 钳制（那是给历史规划器
的保守值，`deeptutor/services/llm/context_window.py:9, 188-197`）；读数必须与模型设置页同一
数字。仅回退分支用模型名启发式，并以此置 `window_estimated`。计数器探测
`detect_counter_name`（tiktoken 可用性，`context_budget.py:108-121`）；token 计数函数延迟导入
`count_tokens` 防循环依赖（`context_budget.py:331-336`，实现在
`deeptutor/services/session/context_builder.py:49`）。

### 3.4 数据流（消费侧）

```
pipeline._build_system_prompt ──存──▶ _last_prompt_blocks            (pipeline.py:446-457)
AgentLoop._call_llm 每轮 ──拍──▶ self._last_request (LLMRequestSnapshot) (agent_loop.py:1132-1134)
AgentLoop.run 收尾 ──▶ pipeline.measure_context_budget(_last_request)   (agent_loop.py:385-388)
        └─▶ build_context_budget ─▶ payload["metadata"]["context_budget"]
              ├─ web/hooks/useContextBudget.ts:35-40  composer 芯片读数（window/used_tokens/segments 校验）
              └─ deeptutor/services/session/usage_recovery.py:29-38  从预算元数据恢复历史模型归属
```

与预算面相邻但**不同职责**：`_guard_context_window`（`pipeline.py:1623-1658`）是轮前的防护——
超过 `CONTEXT_WINDOW_GUARD_RATIO` 时就地截短 `role=tool` 结果；`resolve_effective_context_window`
服务的是历史规划。预算读数是轮后的报告，两者不共享钳制逻辑是刻意的。

### 3.5 索引

| 关注点 | 位置 |
|---|---|
| 设计立场（只测已组装材料 / 永不抛错） | `deeptutor/agents/loop/context_budget.py:1-12, 141-170` |
| 段映射表与 capability 汇总 | `deeptutor/agents/loop/context_budget.py:37-54` |
| 快照 dataclass（浅拷贝理由） | `deeptutor/agents/loop/context_budget.py:57-67` |
| 窗口解析（不钳制） | `deeptutor/agents/loop/context_budget.py:77-105` |
| 计数器探测 / 延迟导入 | `deeptutor/agents/loop/context_budget.py:108-121, 331-336` |
| 消息计数（跳 system、防双计） | `deeptutor/agents/loop/context_budget.py:124-138, 296-312` |
| 分段构造与 used==sum 不变量 | `deeptutor/agents/loop/context_budget.py:173-238` |
| 渲染开销 / 工具 schema 分流 | `deeptutor/agents/loop/context_budget.py:256-293` |
| blocks 组装一次并留存 | `deeptutor/agents/loop/pipeline.py:265-267, 436-464` |
| 快照拍摄与 forced-finish 沿用 | `deeptutor/agents/loop/agent_loop.py:1119-1134` |
| 挂载到结果 payload | `deeptutor/agents/loop/agent_loop.py:385-388` |
| 测量入口（pipeline 侧） | `deeptutor/agents/loop/pipeline.py:1660-1688` |
| 前置防护（不同职责） | `deeptutor/agents/loop/pipeline.py:1623-1658` |
| 前端消费 | `web/hooks/useContextBudget.ts:35-40` |
| 会话恢复消费 | `deeptutor/services/session/usage_recovery.py:29-38` |

---

## 4. 三个面在一轮内的交汇顺序

`_call_llm` 单轮内的时间线（`agent_loop.py:1037-1710`）：

1. 组装请求 kwargs、拍 `LLMRequestSnapshot`（预算面，`agent_loop.py:1119-1134`）。
2. 进入重试循环（0.5s/1.5s，仅"尚无任何输出"时可重试；`agent_loop.py:110-111, 1436-1461`）。
3. 逐 chunk：`usage` → `finish_reason` → provider 扩展（ask_user 预览、签名 thinking 块、
   native reasoning）→ `delta.reasoning_content`（think 面：专用通道）→ `delta.content`
   （**先 dsml_filter 后 think_filter**，`agent_loop.py:1392-1394`）→ `delta.tool_calls`
   （ToolCallAccumulator，原生调用面）。
4. 流末：`dsml_filter.flush()` → `think_filter.feed(dsml_tail)` → `think_filter.flush()`
   （顺序保证尾部标记也被正确分流，`agent_loop.py:1523-1526`）。
5. 轮末：`extract_dsml_tool_calls(text, catalog)` 解析 + 清洗，与原生调用合并
   （`agent_loop.py:1543-1552`）；统计元数据与 `call_status`（`agent_loop.py:1619-1691`）。
6. 回到 `_run_loop`：有调用 → 派发并把 assistant+tool 消息追加进会话（`agent_loop.py:705-728`）；
   `ask_user` 暂停等回复（`agent_loop.py:731-743`）；上下文检查点折叠（`agent_loop.py:745-749,
   801-819`）；无调用 → 收尾判定（截断续写 / 推理-only 恢复 / capability 重定向 / 正常 finish）。

预算读数则在**整个 turn 结束后**由 `AgentLoop.run` 一次性测量最后一轮快照
（`agent_loop.py:385-388`）。

## 5. 修改时的不变量清单

- **think**：原始文本（含标签）必须原样回会话；`thinking` 永不进 `content` 事件；holdback
  常量与"未闭合 think 全按推理"的语义是防漏字的底线（`think_stream.py:35-36`；测试镜像
  `tests/agents/chat/test_agent_loop.py:646-651`）。
- **dsml**：残缺 invoke 必须 `flush` 原样放出；无良构调用时 `cleaned is text`；容器 schema
  优先于 `string="true"`；原生调用存在时不得双派发（`dsml_tool_calls.py:138-143, 197-204,
  243-247`；`agent_loop.py:1549-1552`）。
- **budget**：只能测"最后一次真实请求"的现场材料；快照消息列表必须浅拷贝；`build_context_budget`
  对外契约是不抛错；窗口读数不参与规划钳制（`context_budget.py:8-11, 57-67, 83-95`）。

## 6. 核验记录

- 基线提交：origin/main `6cf793bd868ba5ecbe64722936d4be8fab5a01df`（release: v1.6.14）。
- 本文所有 `path:line` 在该提交的干净 worktree 中逐条以 `rg`/`sed` 核对锚点内容后写入；
  核验脚本输出见同目录 `anchor-verification.txt`。
- 关联单元测试在该提交上运行（venv `/Users/Shared/DeepTutor/.venv`，`pytest -p no:cacheprovider`，
  每条命令限时 900s）：
  - `tests/agents/chat/test_dsml_tool_calls.py` + `tests/agents/chat/test_context_budget.py`：
    **35 通过**；
  - `tests/agents/chat/test_agent_loop.py`：**101 通过，1 失败** ——
    `test_cold_start_stalled_provider_settles_with_bounded_retries[partial_stream]`（#1421 传输重试
    用例，内含 1 秒 `asyncio.wait_for` 真实墙钟预算）。该失败与本卡三个子面无关，且在更早的
    固定检出（`9955a4122`，v1.6.14 后的 evidence 分支点）上同样复现，判定为本机环境的既有
    时序限制，非当前 HEAD 回归；其余与本导读相关的用例全部通过。
  - 环境前置：两个全管线用例依赖 workspace 根目录存在；全新 `DEEPTUTOR_HOME` 下预创建
    `<home>/data/user/workspace` 后即为绿（应用正常启动时由 bootstrap 创建，测试裸跑不含该步骤）。
  - 完整输出见同目录 `test-run.txt`。
