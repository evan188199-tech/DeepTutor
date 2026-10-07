# audio_overview 能力导读（KB 双声播客）

覆盖 `deeptutor/capabilities/audio_overview/`（capability.py 133 行 + pipeline.py 513 行 + request_config.py 18 行）的注册、请求契约、执行链、管线阶段、provider 依赖与失败路径。面向修卡/补测卡定位，全部结论附 `path:line`（基于 origin/main @ f07029cfc，v1.6.13）。

分工边界：capability 框架全景见 `docs/guides/capability-instances.md`（§7 是本文的 10 行摘要）；TTS/朗读运行时见 `evidence/guide-voice-20261005/guide.md`；补测工作在 `test/audio-overview-pipeline-20261007` 分支进行。

## 1. 入口与注册

- 类：`AudioOverviewCapability(TurnCapability)`，`deeptutor/capabilities/audio_overview/capability.py:21`。不是 chat loop 扩展，是用户显式选择的独立流水线能力。
- 注册：类路径 `deeptutor/runtime/bootstrap/builtin_capabilities.py:47`；spec（stages/tools_used/CLI 别名/config_defaults）`builtin_capabilities.py:240-256`。
- CLI 别名：`audio-overview`、`overview`（`builtin_capabilities.py:247`），由 `AppFacade.resolve_capability` 消费（`deeptutor/app/facade.py:82-91`，别名循环 :86-89）。
- manifest：`capability.py:22-36`——四阶段 `["retrieving","script_writing","voice_generation","publishing"]`（:25）、`tools_used=["rag"]`（:26）、`request_schema=get_capability_request_schema("audio_overview")`（:28）、`config_defaults`（:29-35）。
- 请求契约：`CAPABILITY_CONFIG_MODELS["audio_overview"] = AudioOverviewRequestConfig`（`deeptutor/runtime/request_contracts.py:155`）；校验器由 :183-193 的循环统一生成；JSON Schema 由 `get_capability_request_schema`（:208-209）导出。`AudioOverviewRequestConfig`（`request_config.py:8-15`）`extra="forbid"`（:9），字段边界：topic ≤500、target_minutes 1–15、host/expert_voice 1–64 字符或 None、max_context_chunks 1–12。
- 目录里没有 prompts/ 子目录；提示词在共享层 `deeptutor/capabilities/prompts/{en,zh}/audio_overview.yaml`（system/instructions/status 四键），经 `PromptManager.load_prompts("capabilities","audio_overview",…)` 加载（`deeptutor/services/prompt/manager.py:58-89`，NON_AGENT_MODULES 映射 :43-51）。

## 2. 函数级调用链（一次成功回合）

```
CLI/Web 请求 capability="audio-overview"
→ AppFacade.start_turn                     app/facade.py:131（resolve_capability :82 别名→audio_overview）
→ TurnRequestPreparer.start_turn           deeptutor/services/session/turns/request_preparer.py:133（类定义 :82）
→ Executor 组装 UnifiedContext             deeptutor/services/session/turns/executor.py:898-901
  （active_capability=payload["capability"] :898，config_overrides=request_config :901）
→ Orchestrator.handle                      deeptutor/runtime/orchestrator.py:81
→ CapabilityRegistry.get("audio_overview") deeptutor/runtime/registry/capability_registry.py:140-143（catalog.create("turn")）
→ capability.run(context, bus)             deeptutor/runtime/orchestrator.py:141
→ AudioOverviewCapability.run              deeptutor/capabilities/audio_overview/capability.py:38
   ① retrieving   :76  → Pipeline.retrieve   pipeline.py:339 → rag_search tools/rag_tool.py:15 → normalize_rag_result pipeline.py:250
   ② script_writing :92 → Pipeline.generate_script pipeline.py:356 → LLM complete :396 → parse_script pipeline.py:199
   ③ voice_generation :100 → Pipeline.publish pipeline.py:399 → synthesize_speech×N services/voice/__init__.py:33 → _render_audio pipeline.py:110 → 写盘 :446-457 → _publish_workspace_items :474
   ④ publishing   :108 → stream.sources(workspace_items) capability.py:109-114
→ emit_capability_result                   deeptutor/agents/_shared/capability_result.py:21（stream.result :48）
→ 前端 stream_turn 订阅                    app/facade.py:154-162；SOURCES 事件 → GeneratedFiles 渲染（见 §5）
```

失败时 orchestrator 捕获异常并 `bus.error(..., metadata={"turn_terminal": True, "status":"failed"})`（`orchestrator.py:144-167`），错误码/retryable 从异常属性透传（:149-158）。

## 3. 管线四阶段与数据流

`run()`（`capability.py:38-130`）按 manifest 顺序推进，每阶段是 `stream.stage(...)` 上下文：

1. **守门与装配**（进入阶段前）：无知识库即抛用户可读错误（`capability.py:41-45`）；`AudioOverviewRequestConfig.model_validate(context.config_overrides)`（:47）；topic 取值：请求 topic 与 user_message 不同才用 topic，否则用 user_message 或默认 "Knowledge base overview"（:48-51）；无 workspace 即抛错（:53-57）；加载提示词并构造 pipeline（:59-73）；turn_id 取 metadata/session/uuid（:75）。
2. **retrieving**：query = `topic + " audio overview"`，截断 1000 字符（`pipeline.py:342-343`）；`top_k=max_context_chunks`（:352）；结果经 `normalize_rag_result` 归一（:354）。产出 `RetrievedContext`（answer 截 16000 字符 + SourceCitation 列表，source_id 形如 S1…，`pipeline.py:250-273`）。命中引用即发 RAG sources 事件（`capability.py:82-90`）。
3. **script_writing**：把 citation 块（每条 title/locator/snippet 截 2000 字符）+ 语言标签 + 目标时长拼进 prompt（`pipeline.py:377-395`）；LLM 一次调用（:396）；`parse_script` 严格校验：必须是 JSON 对象（:202-204）、`AudioOverviewScript` Pydantic 校验（:205-212）、引用 ID 必须都在 citation_ids 内否则抛错（:214-217）、host/expert 严格交替且去重 source_ids（:40-50）。段数 2–80，单段 ≤4000 字符（:30, :38）。
4. **voice_generation**：懒加载 `synthesize_speech`（:410-414）；声音解析——注入了 speech_func（测试/嵌入）时缺省 "host"/"expert" 占位（:432-434），真实 TTS 路径经 `resolve_tts_runtime_config` + `voice_model_options` 取缺省声音，且 host/expert 必须不同，否则用户可读报错（:418-431）；逐段串行合成 `(bytes, content_type)`（:436-444）。
5. **产物落盘**：stem = `turn_id-audio-overview` 经 `_safe_stem` 清洗（:446, :276-278）；全 WAV 时 `wave` 直拼帧输出 `.wav`（:110-125），否则 ffmpeg 统一重采样 24kHz 单声道 s16le 再编 MP3（:127-196）；转写 Markdown 写入（`_transcript` :281-308，zh 标签 主持人/专家 :282-289）；OSError 统一包成 `AudioOverviewError`（:456-457）。
6. **publishing + 结果**：workspace 条目经 `get_content_workspace_service().publish`（`pipeline.py:474-501`，无 workspace_id/logical_dir 时静默跳过 :481-482）；`emit_capability_result` 携带 response=转写全文、title、citations、segments、audio/transcript 文件名与 workspace_items（`capability.py:116-130`）。

## 4. Provider 依赖表

| 依赖 | 注入点/懒加载 | 锚点 |
| --- | --- | --- |
| RAG 检索 | `retrieve` 缺省时 import `deeptutor.tools.rag_tool.rag_search` | pipeline.py:344-348；rag_tool.py:15-22（多用户路由 resolve_for_rag rag_tool.py:36-40） |
| LLM 脚本 | `generate_script` 缺省时 `llm_factory.complete_with_config(get_llm_config(), …)` | pipeline.py:363-375 |
| TTS 合成 | `publish` 缺省时 `deeptutor.services.voice.synthesize_speech(text, voice=…, response_format="mp3")`，返回 `(bytes, content_type)` | pipeline.py:410-414；voice/__init__.py:33-47 |
| 声音目录 | `resolve_tts_runtime_config` + `voice_model_options(...).get("voices")` | pipeline.py:418-427 |
| PCM 解码参数 | `_parse_pcm_content_type`（PCM 流的采样率/声道提示） | pipeline.py:134-139；services/voice/audio.py:83 |
| ffmpeg 二进制 | 仅非全 WAV 拼接时经 subprocess 调用，缺失抛用户可读错误 | pipeline.py:140-167, :192-193 |
| Workspace 服务 | `_publish_workspace_items` 内 `get_content_workspace_service()` | pipeline.py:483-501 |
| 提示词 | `get_prompt_manager().load_prompts("capabilities","audio_overview",language)` | capability.py:59-65；manager.py:58-89 |
| i18n 状态文案 | `StatusI18n(self.name, context.language, module="capabilities")` | capability.py:40（missing_kb :44、missing_workspace :56） |

三个 provider（rag/complete/speech）都有构造参数注入点（`pipeline.py:89-91` 类型别名、:330-332），测试即靠 fake 注入跑通全链。

## 5. 前端入口

前端没有 audio_overview 专属组件，全走通用能力通道：

- 能力清单：`AppFacade.get_capability_contracts`（`app/facade.py:94-102`）→ `CapabilityRegistry.get_manifests`（`deeptutor/runtime/registry/capability_registry.py:148-163`，request_schema 直接由 config_model 的 `model_json_schema(mode="validation")` 生成 :158），composer/CLI 据此展示与传参。
- 流式产物：SOURCES 事件（rag 引用 + workspace_item 卡片）经 `web/features/chat/ChatStateAdapter.tsx:266`（MessageAttachment.workspace_item_id）进入消息附件；`mergeGeneratedFiles` 合并持久附件与流式产物去重（`web/components/common/InlineFileCard.tsx:113-128`）；`GeneratedFiles` 渲染音频/转写为可打开卡片（`web/features/chat/messages/ChatMessageList.tsx:515-545`，key 取 workspace_item_id :529）。
- 结果正文：payload.response（转写 Markdown）作为 assistant 消息持久化/渲染；executor 把 generated_attachments 落到消息行（`deeptutor/services/session/turns/executor.py:1095-1140` 区段）。

## 6. 关键文件表

| 文件 | 行数 | 职责 |
| --- | --- | --- |
| `deeptutor/capabilities/audio_overview/capability.py` | 133 | TurnCapability 入口：守门、装配、四阶段编排、结果发射 |
| `deeptutor/capabilities/audio_overview/pipeline.py` | 513 | 数据模型、RAG 归一、脚本解析、TTS 合成、音频封装、workspace 发布 |
| `deeptutor/capabilities/audio_overview/request_config.py` | 18 | 请求契约（Pydantic，extra=forbid） |
| `deeptutor/runtime/bootstrap/builtin_capabilities.py` | — | :47 类注册、:240-256 spec |
| `deeptutor/runtime/request_contracts.py` | — | :155 契约映射、:183-197 校验器/Schema、:208 getter |
| `deeptutor/capabilities/prompts/{en,zh}/audio_overview.yaml` | — | system/instructions/status 提示与 i18n 文案 |
| `deeptutor/runtime/orchestrator.py` | — | :141 能力执行、:144-167 失败→turn_terminal 事件 |
| `web/components/common/InlineFileCard.tsx` | — | :113-128 流式产物合并（前端渲染入口） |

## 7. 失败路径

| 触发 | 位置 | 用户可见结果 |
| --- | --- | --- |
| 未附加知识库 | capability.py:41-45 | AudioOverviewError(missing_kb) |
| 无可写 workspace | capability.py:53-57；pipeline.py:407-408 | AudioOverviewError(missing_workspace) |
| RAG error_type/needs_reindex | pipeline.py:251-255 | "RAG retrieval failed: <原因前 500 字>" |
| RAG 空内容（无 answer 且无引用） | pipeline.py:270-272 | "The knowledge base returned no usable content." |
| LLM 输出非 JSON/校验失败/未知引用 | pipeline.py:202-217 | AudioOverviewError（含 pydantic 明细或段号） |
| 声音未配置或 host=expert（真实 TTS） | pipeline.py:428-431 | "Configure distinct host and expert voices…" |
| 语音返回空音频 | pipeline.py:112-113 | "The speech provider returned empty audio." |
| ffmpeg 缺失/解码失败/编码失败 | pipeline.py:192-193, :162-165, :194-195 | 用户可读 AudioOverviewError |
| 产物写盘 OSError | pipeline.py:456-457 | "Could not write audio overview artifacts…" |
| 未知能力名（别名打错） | orchestrator.py:84-99 | bus.error("Unknown capability …") + DONE(failed) |

以上异常统一由 orchestrator 转成 `turn_terminal` 错误事件并 DONE(status=failed)（`orchestrator.py:144-167`）；turn 状态由 executor 收敛（`executor.py:1138` `_resolve_turn_outcome`）。

## 8. 测试现状与覆盖空白

现有（origin/main）：

- `tests/capabilities/test_audio_overview.py`，7 个用例——注册+契约一致性 :34-49；缺 KB 报错 :52-56；parse_script 交替/去重/未知引用 :59-100；normalize_rag_result 截断与 title 提取 :103-121；全链 happy path（fake RAG/LLM/TTS，断言 query 文本、双声音、WAV 帧数、workspace 发布路径）:124-243；capability 级 SOURCES 事件两次发射 :246-324；MP3 remux :327-361（无 ffmpeg 跳过 :328-329）。
- `tests/core/test_capabilities_runtime.py:68-84` 断言注册表覆盖集合含 audio_overview。

覆盖空白（补测卡可直接认领）：

1. 真实 TTS 声音解析分支（pipeline.py:418-431：缺省解析、distinct 校验抛错）无测试——现测全部显式传双声音（test :227）。
2. ffmpeg 三条失败路径（:162-165、:192-193、:194-195）无单测；MP3 remux 在无 ffmpeg 环境直接跳过。
3. normalize_rag_result 两道失败门（:251-255、:270-272）未覆盖。
4. request_config 边界（target_minutes 1–15、max_context_chunks 1–12、extra=forbid、topic ≤500）无显式校验测试。
5. retrieve 的 query 截断（:342-343）与 RAG 异常传播未测。
6. missing_workspace（capability.py:53-57）与写盘 OSError（pipeline.py:456-457）未测；`_publish_workspace_items` 无 workspace_id 的 no-op（:481-482）仅被隐式经过。
7. CLI 别名解析（audio-overview/overview → facade.py:82-91）无测试。
8. zh 语言转写标签（`_transcript` :282-289）未断言。

## 9. 已知坑

1. **空提示词静默降级**：找不到 yaml 时 PromptManager 只 print warning 并返回 `{}`（`manager.py:124-125`），`capability.py:68-69` 用 `or ""` 吞掉——system/instruction 为空仍会调 LLM，产出质量崩但无错误事件。改 prompt 目录结构时最容易踩。
2. **topic 语义**：`capability.py:48-51` 只有请求 topic ≠ user_message 时才生效；CLI 用户把主题写进消息体时 topic 字段形同虚设。
3. **脚本无重试**：`generate_script` 单次调用（pipeline.py:396-397），首段非 host（:40-50 交替校验）或引用越界即整回合失败；段数 2–80、每段 ≤4000 字符（:30, :38）。
4. **TTS 串行**：逐段顺序合成（:436-444），24 段 ≈ 24 次串行请求；中途无 checkpoint，取消即全弃。
5. **文件名清洗**：`_safe_stem`（:276-278）把非 `[A-Za-z0-9._-]` 全变连字符，中文 turn_id 产物名退化为纯连字符串。
6. **ffmpeg 条件依赖**：全 WAV 走 wave 快路径（:115-125），一旦混入 PCM/MP3 就需要系统 ffmpeg（:127-196）——容器镜像裁剪 ffmpeg 时播客能力才暴露缺失。
7. **workspace 静默跳过**：workspace_id/logical_dir 为空时 `_publish_workspace_items` 返回 `[]`（:481-482），产物只在磁盘不在工作区列表，前端不会出现卡片。
8. **usage 快照**：`emit_capability_result` 未传 usage 参数（capability.py:116-130），费用统计依赖 `current_usage` contextvar 兜底（`capability_result.py:43-47`）。
