# 数学动画子系统导读（math_animator 管线与视觉复核）

- 基线：origin/main `f07029cfc`（v1.6.13）。所有 `path:line` 相对仓库根，行号随演进漂移，以符号名为准。
- 范围：`deeptutor/agents/math_animator/**` 及其三个调用方（capability 注册、visualize manim 路径、book 动画块）与前端查看器。
- 去重：agents 总体框架（BaseAgent/loop/_shared/注册机制）见 guide-agents 卡；本文只展开 math_animator 子系统内部与它对 `_shared`/BaseAgent 的具体用法。
- 上游在途 PR（写卡时开放，读代码时注意撞车）：#1680（旁白配音，改 pipeline/agents）、#1219（空结构化 JSON 重试，主分支已有等价实现 `code_generator_agent.py:147`）、#1553（截断预算提升，主分支已有 `utils.py:102`）。

## 1. 模块地图

| 角色 | 文件 | 关键符号 / 说明 |
| --- | --- | --- |
| 能力入口 | `deeptutor/agents/math_animator/capability.py:19` | `MathAnimatorCapability`，manifest 定义 `:20-39`（六 stages、`cli_aliases=["animate"]`、config 默认值） |
| 编排器 | `deeptutor/agents/math_animator/pipeline.py:26` | `MathAnimatorPipeline`；`enable_visual_review` 默认 `False`（`pipeline.py:35`） |
| 概念分析 agent | `deeptutor/agents/math_animator/agents/concept_analysis_agent.py:14` | `ConceptAnalysisAgent`，产 `ConceptAnalysis` |
| 概念设计 agent | `deeptutor/agents/math_animator/agents/concept_design_agent.py:14` | `ConceptDesignAgent`，产 `SceneDesign` |
| 代码生成/修复 agent | `deeptutor/agents/math_animator/agents/code_generator_agent.py:31` | `CodeGeneratorAgent.generate`(:66) / `.repair`(:105)，自持一层"模型成功但无可用品"重试（`:147-237`） |
| 总结 agent | `deeptutor/agents/math_animator/agents/summary_agent.py:14` | `SummaryAgent`，渲染已成功时空总结也放行（`:76-78`） |
| 视觉复核 agent | `deeptutor/agents/math_animator/agents/visual_review_agent.py:16` | `VisualReviewAgent`，产 `VisualReviewResult` |
| 视觉复核服务 | `deeptutor/agents/math_animator/visual_review.py:17` | `VisualReviewService`：视频抽帧/图片收集成附件 |
| 渲染服务 | `deeptutor/agents/math_animator/renderer.py:35` | `ManimRenderService`：subprocess 调 `python -m manim` |
| 重试管理 | `deeptutor/agents/math_animator/retry_manager.py:21` | `CodeRetryManager`：render→repair 循环，max_retries=4（`:30`） |
| 数据模型 | `deeptutor/agents/math_animator/models.py` | 全部 pydantic 模型（`ConceptAnalysis` :8、`RenderResult` :74 等） |
| 请求配置 | `deeptutor/agents/math_animator/request_config.py:10` | `MathAnimatorRequestConfig`（video/image × low/medium/high × style_hint，extra=forbid） |
| 时长解析 | `deeptutor/agents/math_animator/duration_utils.py:17` | `parse_target_duration_seconds`，取全部候选的最大值（`:36`） |
| 工具函数 | `deeptutor/agents/math_animator/utils.py` | 修复提示 `:29`、失败分类 `:64`、预算升级 `:102`、JSON 提取再导出 `:121` |
| Prompt 包 | `deeptutor/agents/math_animator/prompts/{en,zh}/` | 5 个 agent 各一份 YAML + `math_animator.yaml` 状态文案；en/zh 行数基本对齐（zh code_generator 96 行 vs en 95 行） |
| 注册点 | `deeptutor/runtime/bootstrap/builtin_capabilities.py:41,119-140` | 类路径映射与 manifest 声明 |
| 请求契约 | `deeptutor/runtime/request_contracts.py:150,161` | 校验器与模型登记 |
| 设置默认 | `deeptutor/services/config/capabilities_settings.py:50,64` | `("plugins","math_animator")`；默认 `{"temperature":0.2,"max_tokens":16834}` |
| 前端查看器 | `web/components/math-animator/MathAnimatorViewer.tsx:9` | 消费 `result.artifacts`/`result.code`（`:18-23,:129-136`），由 `web/features/chat/messages/ChatMessageList.tsx` 与 `web/components/visualize/VisualizationViewer.tsx` 分发 |

## 2. 数据流：六阶段生成管线

capability 路径（`capability.py:41` `run()`）逐 stage 包 `stream.stage`，依次调 pipeline 的分步方法；`book/blocks/animation.py:96` 则直接调 `pipeline.run()`（`pipeline.py:259`，内置 timings 统计 `:268-315`）。

1. **concept_analysis**（`capability.py:85-92` → `pipeline.py:93` → `concept_analysis_agent.py:31`）：带历史上下文与附件（统计图片引用数 `concept_analysis_agent.py:57`）；prompt 缺失时 reload 一次 PromptManager（`:43-55`，修 worker 早启动缓存空值的旧坑）；经 `json_with_reasoning_retry` 解析并强校验 `learning_goal`（`:92-96`）。
2. **concept_design**（`capability.py:95-101` → `concept_design_agent.py:31`）：analysis JSON 注入模板，强校验 `scene_outline`（`:74-75`）。
3. **code_generation**（`capability.py:104-116` → `pipeline.py:123-144`）：先从用户输入+style_hint 解析目标时长（`duration_utils.py:17`，"秒/分"正则 `:7-14`），传入 generate 模板的 `duration_requirement`（`code_generator_agent.py:80-90`）。
4. **code_retry**（`capability.py:150-172` → `pipeline.py:146-214`）：渲染+复核+修复都算进这个 stage，见 §3。
5. **summary**（`capability.py:175-185` → `summary_agent.py:31`）：把 analysis/design/render 全文喂给模型；空总结不回滚渲染结果（`summary_agent.py:76-78`）；正文经 `stream.content` 推给前端（`capability.py:184`）。
6. **render_output**（`capability.py:187-211`）：统计 artifacts 数、推 `workspace_items` sources（`:204-211`），`timings["render_output"]=0.0`（`:203`）。

最终结果统一经 `emit_capability_result` 发出（`capability.py:213-238`；共享实现 `deeptutor/agents/_shared/capability_result.py:21`，附 `cost_summary`/`usage_summary` `:35-47`）。payload 含 response/summary/code/artifacts/workspace_items/timings/render(含 visual_review)/analysis/design（`:215-235`）。

产物落地有两条路：

- 无 workspace 时：`renderer.py:245-269` `_build_artifact` 用 path_service 拼 `/files/outputs/<rel>` URL（`:261`）。
- 有 workspace 时：`pipeline.py:216-240` `_publish_workspace_artifacts` 把最终文件快照进统一呈现层：`binding_by_id`（`deeptutor/services/workspace/service.py:167`）→ `service.publish(binding, rows)`（`service.py:610`）→ 回填 `artifact.url` 与 `workspace_items`（`pipeline.py:236-240`）。

## 3. 渲染与重试（code_retry 内部）

`pipeline.run_render`（`pipeline.py:146`）组装三个部件：

- **ManimRenderService**（`renderer.py:35`）：目录布局 `base_dir/{source,artifacts,media,meta}`（`:53-58`）；video 模式存 `scene.py`、image 模式存 `scene_image.py`（`:62`）。video 走 `_render_video`（`:82`）提取 Scene 类名（正则 `:22`，实现 `:238-243`）；image 模式强制代码只含 `### YON_IMAGE_n_START/END ###` 锚块（正则 `:18-21`；残留代码直接报错 `:102-104`），逐块 `-s` 截末帧（`:115-120`）。
- manim 以 `subprocess.Popen` 运行（`:170-174`），配 reader 线程 + asyncio.Queue 保实时输出（`:176-204`）——注释明说是为了 Windows SelectorEventLoop 不支持 asyncio 子进程（`:166-169`）。非零退出时拼 stdout+stderr 截断成修复错误（`:205-217`，`trim_error_message` `utils.py:17`）。
- 找产物文件排除 `partial_movie_files`、按 mtime 取最新（`:224-236`）。

- **CodeRetryManager**（`retry_manager.py:21`）：循环 `max_retries+1` 次（`:53`）。每次 render 成功后若启用复核则跑 review_callback（120s 超时 `:32,:70-77`）；复核不过→把 review 摘要拼成 RetryAttempt（`:88-103`）再调 repair（180s 超时 `:31,:110-119`）。render 抛 `ManimRenderError` 时同样 repair（`:129-155`）；"缺 latex"被视为不可重试的环境错误直接抛出（`:12-18,:130-134`）。重试耗尽时：复核路径返回当前最优结果并带告警状态（`:79-87`），渲染错误路径直接 raise（`:135-136`）。
- **repair 回调**（`pipeline.py:198-205`）→ `CodeGeneratorAgent.repair`（`code_generator_agent.py:105`）。修复提示增强在 `utils.py:29-61`：2D 点当 3D 用的 hint（`:34-47`）、MathTex/Tex 缺 latex 的 hint（`:49-56`）。

**复核链（visual review）**：`pipeline.py:171-190` 当 `enable_visual_review` 为真时构造 `VisualReviewService`（`visual_review.py:17`）：image 模式直接收集 artifacts（`:37-44`）；video 模式 ffprobe 探时长（`:96-123`）、取 15%/50%/85% 三帧（`:125-135`）、ffmpeg 抽帧到 `review/`（`:59-94`）、base64 转 Attachment（`:137-146`）→ `VisualReviewAgent.process`（`visual_review_agent.py:33`）：无附件或模型不支持视觉都直接放行（`:42-55`，`supports_vision` 定义 `deeptutor/services/llm/capabilities.py:626`），否则带帧图调 LLM 要求 JSON（`:76-93`），`extract_json_object` 解析（`:95-97`；实现 `deeptutor/agents/_shared/json_output.py:10`）。

**已知坑：复核链在 main 上是死代码**。`enable_visual_review` 唯一读取点是 `pipeline.py:35,40,171`，而三个调用方都不传：capability（`capability.py:59-68`）、visualize（`deeptutor/agents/visualize/capability.py:312-321`）、book（`deeptutor/book/blocks/animation.py:84-92`）。链路完整但永远关闭，也没有任何设置开关。

## 4. 与 _shared / BaseAgent 运行时的对接

- 五个 agent 全部继承 `BaseAgent`（`deeptutor/agents/base_agent.py:33`）；参数来自统一配置 `get_agent_params(module_name)`（`base_agent.py:96-97`，math_animator 默认值在 `capabilities_settings.py:64`）。`max_tokens`/`max_retries` 读取 `:190-199`。
- LLM 调用统一走 `stream_llm`（`base_agent.py:519`），带 `response_format={"type":"json_object"}`、stage 名与 trace 元数据；trace 回调桥接在 `capability.py:240-320`（`llm_call` 事件→progress/thinking/error 三态，`:251-318`）。
- 结构化输出三条防线：
  1. analysis/design/summary 用共享 `json_with_reasoning_retry`（`deeptutor/services/llm/structured_retry.py:86`）；
  2. code 生成自持重试 `_request_generated_code`（`code_generator_agent.py:147-237`）：区分截断/空响应/坏 JSON（`utils.py:64-99`），截断后预算按 1.5^n 增长、封顶 2×（`utils.py:102-114`），并降低 reasoning effort 重试（`:189`，`_retry_instruction` `:239-258`）；最终失败抛 `GeneratedCodeOutputError`（`:27,:234-237`）；
  3. 渲染失败由 CodeRetryManager 兜底。
- 能力注册与请求校验：manifest 双写（`capability.py:20-39` 与 `builtin_capabilities.py:119-140`，改 stages/config_defaults 时两处要同步）；请求配置进 `CAPABILITY_CONFIG_VALIDATORS`/`CAPABILITY_CONFIG_MODELS`（`request_contracts.py:150,161`）；设置面板路径 `("plugins","math_animator")`（`capabilities_settings.py:50`，`config/loader.py:248`）。
- `deeptutor/agents/math_animator/__init__.py:18-23` 用模块级 `__getattr__` 懒加载 `MathAnimatorPipeline`，避免 import 即拉起渲染依赖。
- manim 是可选依赖：capability 入口探测后报安装指引（`capability.py:42-47`）；声明在 `pyproject.toml:246-248`（`deeptutor[math-animator]`）与 `requirements/math-animator.txt`（系统前置：latex、ffmpeg、cairo/cmake）。

## 5. 扩展点与复用方

- **visualize 能力复用**：`deeptutor/agents/visualize/capability.py:270` `_run_manim_path` 镜像 capability 流程（注释 `:282-284`），把 render_type 映射成 output_mode（`:303`），前端以 `render_type` 分发到同一个 `MathAnimatorViewer`。改 math_animator 的 stages/回调签名时这里是联动点。
- **book 动画块复用**：`deeptutor/book/blocks/animation.py:72-103` 直接 `pipeline.run()`，不传 trace_callback/workspace 目录（`:84-92`），产物只走 artifacts URL 路径；失败包装成 `GenerationFailure`（`:104-107`）。
- **新增复核/渲染开关**：合理做法是在 `MathAnimatorRequestConfig`（`request_config.py:10-15`）或 capability config_defaults（`capability.py:34-38` + `builtin_capabilities.py:134-138`）加字段，由两个调用方透传给 `MathAnimatorPipeline(enable_visual_review=...)`；目前这个参数无人使用。
- **状态文案**：新增 i18n 进度词时改 `prompts/{en,zh}/math_animator.yaml`，消费点 `StatusI18n(self.name, ..., module="math_animator")`（`capability.py:57`）与 `_build_trace_bridge` 的 fallback（`:305-309`）。
- **渲染质量**：`QUALITY_FLAG_MAP` 只认 low/medium/high（`renderer.py:24-28`），未知值回落 `-qm`（`:143`）。

## 6. 已知坑清单

1. **复核链休眠**（见 §3 末）：要启用需同时改调用方与配置面，否则 `VisualReviewAgent`/`VisualReviewService` 及 retry_manager 的 review 分支（`retry_manager.py:64-125`）永远走不到。
2. **max_tokens 默认值疑似笔误**：`capabilities_settings.py:64` 写 `16834`（非常见的 16384）。截断时预算升级按该基数 2× 封顶（`utils.py:102-114`），放大了笔误影响；且 `describe_unusable_output` 会引导用户去 Settings 手动调（`utils.py:93-96`）。
3. **子进程方式不一致**：manim 用 Popen+线程（`renderer.py:166-174`，Windows 兼容），而 ffmpeg/ffprobe 用 `asyncio.create_subprocess_exec`（`visual_review.py:83,107`）——Windows 上复核抽帧可能踩回同一个 SelectorEventLoop 限制。
4. **image 模式锚块契约严格**：代码含任何锚块之外的残留即报错（`renderer.py:102-104`），依赖 generate/retry prompt 对锚块格式的约束；prompt 漂移会触发无意义的重试轮。
5. **产物按 mtime 取最新**（`renderer.py:224-236`）：media_dir 按 turn 隔离，但 image 多块共用同一目录，若后一块渲染失败前目录里已有旧图，错误分支前可能短暂取到上一块的文件（仅在异常路径拼错误信息时相关）。
6. **渲染成功后 publish 可能翻车**：`_publish_workspace_artifacts` 在 render 成功后同步执行（`pipeline.py:213`），`publish` 对缺失文件/空列表抛 `WorkspaceError`（`workspace/service.py:617-621`），会让整 turn 以错误收场——尽管视频已经渲染好了。
7. **latex 缺失检测靠英文报错串**（`retry_manager.py:12-18`）：本地化 OSError 或不同措辞会绕过短路，白白跑满 4 轮重试。
8. **时长解析取最大候选**（`duration_utils.py:36`）："10 秒或 2 分钟"会按 120s 生成节奏。
9. **timings 双轨**：capability 用自己的 per-stage 计时（`capability.py:92-203`），`pipeline.run()` 内部另有一套（`pipeline.py:268-315`），两处 stage 名一致但只 book 路径用到后者；改 stage 集合时三处（manifest、capability、pipeline.run）要同步。

## 7. 测试现状与空白（可拆卡条目）

现有测试（`tests/agents/math_animator/`，7 文件 24 用例；另 `tests/core/test_math_animator_capability.py:32` 1 个 capability 冒烟，FakePipeline 替身）：

| 被测文件 | 测试 | 覆盖点 |
| --- | --- | --- |
| `code_generator_agent.py` | `test_code_generator_agent.py`（5 例） | 空输出/纯推理重试、最终失败、截断预算升级、降 reasoning、坏 JSON 如实上报 |
| `structured_retry` 接入 | `test_reasoning_retry.py`（3 例） | analysis 重试、两次空响应拒绝、空总结保渲染 |
| `retry_manager.py` | `test_retry_manager.py`（4 例） | 状态回调+恢复、repair 超时、复核失败重试、复核耗尽返最优 |
| `renderer.py` | `test_renderer_error.py`（1 例） | 源文件消失时仍保留 stderr |
| `request_config.py` | `test_request_config.py`（2 例） | 默认值、未知字段拒绝 |
| `duration_utils.py` | `test_duration_ms_not_minute.py`（2 例） | ms 不算分钟、秒/分解析 |
| `utils.py` | `test_utils.py`（7 例） | 修复 hint、latex hint、JSON 提取、预算封顶、三失败分类 |

零测试/弱测试位置与可拆卡建议：

1. **`visual_review.py` + `agents/visual_review_agent.py` 零测试**（抽帧时间戳选择 `:125-135`、vision 短路 `:42-55`、JSON 校验）：同批卡 test-math-visual-review（分支 `test/math-visual-review-20261006`）正补这块，落地后以该卡结论为准。
2. **`renderer.py` 仅 1 例错误路径**：可拆卡覆盖 Scene 类名提取（`:238-243`）、YON_IMAGE 契约（锚块缺失/残留报错 `:95-104`）、`_find_rendered_file` 排除 partial_movie_files（`:224-236`）、`_build_artifact` 的 workspace/URL 双分支（`:245-269`）。均为纯逻辑或可 tmp_path 化，无需真跑 manim。
3. **`pipeline.py` 无直接单测**：`run()` 编排与 timings（`:259-323`）、`_publish_workspace_artifacts`（`:216-240`，含 publish 抛错即翻车整 turn 的坑 §6.6）可拆卡。
4. **`capability.py` 仅 1 例 happy path**：可拆卡补 manim 缺失报错（`:42-47`）、trace bridge 三态（`:240-320`）、workspace_items sources 发射（`:204-211`）。
5. **复核链启用卡**：加配置开关并让三个调用方透传，配套 e2e（dormant 状态本身可用"全仓库无 `enable_visual_review=True`"断言锁住，防回归性误启用）。
6. **小修卡**：`capabilities_settings.py:64` 的 `16834`→`16384`；`retry_manager.py:12-18` 的 latex 检测改为不依赖英文措辞（如检测 stderr 含 "latex" 可执行名 + FileNotFoundError 类型）。
