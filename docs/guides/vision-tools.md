# tools/vision 视觉工具面导读（块解析 / 坐标变换 / 图片工具 / GGB 校验）

- 基线: origin/main @ `f07029cfc`（release v1.6.13）。所有 `path:line` 在该 commit 逐一核对存在；行号随演进漂移，以符号名为准。
- 范围: `deeptutor/tools/vision/**` 四个模块（block_parser / coord_transform / image_utils / ggb_validator）及其调用面：`visualize` 的 GeoGebra visualizer、`geogebra_analysis` 工具（chat + deep_solve）、前端 ggbscript 渲染链。
- 去重（边界声明）: visualize 能力整体管线与 Mermaid/SVG/Chart.js 渲染链路见 guide-visualize 卡；math_animator 六阶段动画管线见 `docs/guides/math-animator.md`；本文只在与视觉工具衔接处引用它们。test-vision-* 系列测试卡（block-parser / coord-transform / image-utils / ggb-validator 四条分支）见 §6。
- 上游在途 PR（写卡时开放，读代码时注意撞车）: #687（`vision_solver_agent._extract_json` 改 `json.JSONDecodeError` 场景下用 `raw_decode` 容错解析，只动 `vision_solver_agent.py` 与其测试）；guide #1716/#1717 是 docs 卡不撞代码。

## 0. 一分钟总览

四个模块是一套"图片 → GeoGebra 图形"的视觉工具箱，但**现状调用热度极不均衡**：

| 模块 | 职责 | 当前生产调用方 |
|---|---|---|
| `ggb_validator.py` | 逐行校验/修复 LLM 生成的 GeoGebra 命令 | **唯一有活跃生产调用**：`visualizers/builtin.py:120`（geogebra visualizer 校验器）＋ block_parser 内部 `:93,184,225` |
| `block_parser.py` | 从 LLM 输出中解析 ```ggbscript[id;title]``` 围栏块（全量 + 流式两套） | 后端无调用（仅 `__init__.py` 导出）；**围栏格式的前端消费方存在**（§4.2），解析逻辑在前端独立实现 |
| `coord_transform.py` | BBox 像素坐标 ↔ GeoGebra 数学坐标互转 + 元素批量转换 | 无调用（仅导出）；入参形状对齐已下线的 BBox 阶段输出（§5.1） |
| `image_utils.py` | 图片 URL 下载 / base64 互转 / MIME 判定 | 无调用（仅导出）；旧 REST 路由已删，工具路径由 turn 附件直接注入 base64 |

关键认知：**这是一套"半休眠"的工具面**。`geogebra_analysis` 工具在 v1.4.6 前后从四阶段流水线（BBox → Analysis → GGBScript → Reflection）坍缩成单次视觉调用＋一次门控修复（`vision_solver_agent.py:1-9` 模块注释），coord_transform/image_utils 随之失去调用方；ggb_validator 因 visualize 的 geogebra visualizer 而持续活跃。改动前三件事：① 想动 `validate_ggbscript` 的输出格式，先看 §3.1（visualizer 校验契约）和 §4.2（前端围栏解析）两处下游；② 想复用 image_utils/coord_transform，先读 §5.2 的平行实现清单；③ 短超时常量 `240s` 被 research 流水线引用为基准（`agents/research/pipeline.py:435-439`），别随意下调。

## 1. 模块地图

| 角色 | 文件 | 关键符号 / 说明 |
| --- | --- | --- |
| 门面导出 | `deeptutor/tools/vision/__init__.py:3-41` | 四模块全部符号经 `__all__` 导出（`:43-79`）；仓库内除自身外只有 `visualizers/builtin.py:8` 一处 import |
| GGB 校验 | `deeptutor/tools/vision/ggb_validator.py:291` | `validate_command`（单行）；全脚本入口 `validate_ggbscript` `:342`；修复规则表 `COMMANDS_WITH_BRACKETS` `:23`、`COMMON_MISTAKES` `:92`；Text 命令专项 `validate_text_command` `:238` |
| 块解析 | `deeptutor/tools/vision/block_parser.py:47` | 全量解析 `parse_ggb_blocks`；流式状态机 `StreamingBlockParser` `:109`（feed `:121` / flush `:212`）；围栏正则 `BLOCK_START_PATTERN` `:39-42` |
| 坐标变换 | `deeptutor/tools/vision/coord_transform.py:68` | `bbox_to_ggb`（Y 轴翻转 `:97`）；逆向 `ggb_to_bbox` `:102`；批量转换 `convert_bbox_elements_to_ggb` `:133`；坐标系推荐 `suggest_coord_system` `:329`；默认域 `DEFAULT_GGB_COORD` `:65` |
| 图片工具 | `deeptutor/tools/vision/image_utils.py:61` | `fetch_image_from_url`（httpx，30s 超时 `:24`，10MB 上限 `:21`）；`resolve_image_input` `:171`（base64 优先、URL 兜底）；`ImageError` `:27` |
| 工具包装 | `deeptutor/tools/builtin/__init__.py:687` | `GeoGebraAnalysisTool`（`geogebra_analysis`），单例包装 `VisionSolverAgent`；240s 上限 `:693`；附件注入与归一化 `:739-740` |
| 视觉 agent | `deeptutor/agents/vision_solver/vision_solver_agent.py:19` | `VisionSolverAgent.process` `:48`（单次调用＋门控修复 `:66-72`）；围栏拼装 `format_ggb_block` `:82-92`；JSON 提取 `_extract_json` `:144-171` |
| visualizer 校验器 | `deeptutor/visualizers/builtin.py:105` | `_geogebra_validator`：JSON envelope 校验 + `validate_ggbscript` `:120`；geogebra 插件声明 `:273-341`（prompt `:312-337`，validator 挂载 `:340`） |
| 提交工具 | `deeptutor/visualizers/tool.py:22` | `SubmitVisualizationTool.execute` `:64-145`，校验入口 `:98`，envelope 组装 `:114-133` |
| visualizer 注册 | `deeptutor/visualizers/registry.py:13` | core/bundled/user 三源合并 `reload` `:21-50`；`get` `:62`；prompt 目录 `prompt_catalog` `:125-146`；每请求实例 `get_visualizer_registry` `:149-152`（注释 `:150-151`：进程单例会跨用户泄漏） |
| 可视化循环钩子 | `deeptutor/visualizers/loop_capability.py:18` | `VisualizationLoopCapability`：协议 system block `:30-77`；给 submit_visualization 注入 registry/context `:79-93`；无提交时催缴 `:99-107` |
| 能力入口 | `deeptutor/agents/visualize/capability.py:89` | manim 分流 `:123-136`（`_MANIM_RENDER_TYPES` `:71`）；agentic 模式置位 `:168-170`；envelope 落地 `:198-218` |
| chat 挂载 | `deeptutor/agents/loop/pipeline.py:1409-1425` | 从 turn 附件取首图注入 `image_base64`；schema 剥离 `:1031-1035`（LLM 不许自报图片参数） |
| 能力注册 | `deeptutor/runtime/bootstrap/builtin_capabilities.py:64,93` | chat 与 deep_solve 的 `tools_used` 都含 `geogebra_analysis` |
| 就绪度 | `deeptutor/services/config/readiness.py:194` | `geogebra_analysis` 依赖 `visualizer.geogebra` 行（`visualizer_rows` `:541-588`） |
| 前端围栏解析 | `web/components/common/RichMarkdownRenderer.tsx:460-481` | `ggbscript` 围栏 → CTA 卡（正则 `:466`，动态 import `:57-58`） |
| 前端 CTA | `web/components/common/GeogebraOpenCTA.tsx:27` | 无 payloadId 时按脚本内容哈希生成 id `:39-46`；点击 `openTab` `:48-51` |
| 标签页上下文 | `web/context/GeogebraTabContext.tsx:41` | Provider/handler ref 桥 `:41-80`；`useGeogebraTabOpener` `:87-89`（无 Provider 返回 null → CTA 禁用） |
| 桥接挂载 | `web/features/chat/components/ChatWorkspace.tsx:2423-2425` | `GeogebraTabBridge` `:2975-2990`；阅读/掌握页复用 `web/components/chat/home/ChatViewerBridges.tsx:10-31`（挂载点 `ReadingCompanion.tsx:522`、`MasteryStudy.tsx:879`） |
| 侧栏查看器 | `web/components/chat/home/SessionViewerPanel.tsx:530-561` | `openGeogebraTab`（同 id 刷新脚本）；Tab 体 `GeogebraTabBody` `:1350-1361` |
| GGB 渲染器 | `web/components/Geogebra.tsx:93` | deployggb.js 单例加载 `:37-79`；`parseGgbCommands` `:84-89`（剥 `#` 注释）；applet 装配 `:134-187`；`setCoordSystem` `:159-167`；evalCommand 循环 `:169-183` |
| 画布查看器 | `web/components/visualize/VisualizationViewer.tsx:461-485` | envelope 路径的 geogebra 分支（payload JSON 优先，script 兜底）；envelope 还原 `web/lib/visualize-types.ts:150-199` |

## 2. 四模块内部

### 2.1 ggb_validator —— 活跃的命令修复器

处理单位是"一行命令"（GeoGebra 无 `#` 注释、参数用方括号）。`validate_command`（`ggb_validator.py:291-339`）按序跑五步：

1. 空行放行 `:302-304`；`#` 注释行整行删除并告警 `:306-310`。
2. `fix_common_mistakes` `:313-315`：`COMMON_MISTAKES` 三条正则（`Point({x, y})` → `(x, y)` `:94`、`log(10, x)` → `lg(x)` `:96`、剥 `#` 注释 `:98`）。
3. `fix_brackets` `:317-320`：`COMMANDS_WITH_BRACKETS` 67 个命令名（`:23-89`，几何/变换/样式/SetCoordSystem 等）的 `Cmd(...)` → `Cmd[...]`，由 `PAREN_TO_BRACKET_PATTERN` `:102-105` 驱动（`re.IGNORECASE`，参数内允许一层嵌套括号）。
4. `validate_equation_format` `:322-324`：二次曲线含分数系数只告警不修改（`:165-169`）。
5. `validate_text_command` `:326-330`：Text 命令专项（见下）。

`is_valid` 语义注意 `:332-337`：有 errors 置 False，**发生任何修复也置 False**——"valid"意为"原文即正确"，不是"修复后可用"。

Text 专项（`validate_text_command` `:238-288`）是历史上踩坑最多的地方（#1324 系缺陷的修复面）：参数切分用 `_split_command_args` `:174-202`（尊重引号与嵌套括号的深度计数）；三参形态 `Text[str, x, y]` 且 x/y 均为显式标量表达式时合并成点参 `:269-275`；第二参已是点而第三参是标量则报错并给出正确签名 `:276-281`；大写开头的裸标识符按 GeoGebra 点约定不参与合并（`_is_scalar_argument` `:227-228`，`Text["label", P, Q]` 不误伤）；5 参或 >6 参报错 `:283-286`；字符串内 `$` LaTeX 定界符不平衡报错 `:266-267`。上游 PR #1717 之前还有 "Accept valid GeoGebra Text alignment forms"（`317675eb8`）与 "repair GeoGebra Text coordinates"（`eefc3ee15`）两次 landed 修复，改这里的测试是 `tests/visualizers/test_ggb_validator.py`。

全脚本入口 `validate_ggbscript` `:342-380`：逐行调 `validate_command`，警告/错误带 `Line N:` 前缀聚合；空行原样保留，修复行保留原缩进 `:374-377`，被删的注释行直接跳过。返回 `(fixed_script, warnings, errors)` 三元组——block_parser 与 visualizer 校验器消费的都是它。

### 2.2 block_parser —— 两种消费形态的围栏解析

围栏头格式：` ```ggbscript[page-id;title]` 或 ` ```geogebra[...]`，`BLOCK_START_PATTERN` `block_parser.py:39-42`（`re.IGNORECASE`，title 可省略默认 "Untitled" `:78`）；围栏尾 `BLOCK_END_PATTERN` `:44`。

- 全量形态 `parse_ggb_blocks` `:47-106`：扫描 → 前置文本进 `text_segments`、块内容经 `validate_ggbscript` 修复后进 `ggb_blocks`（`:92-104`）；`GGBBlock.original_content` 只在发生修复时记录原文（`:100`）。未闭合的块把剩余文本全收进块 `:84-87`。
- 流式形态 `StreamingBlockParser` `:109-251`：三态状态机（`idle/await_block/in_block`，`:117`）。feed `:121-210` 的细节：idle 态发现尾部疑似围栏头但不足 50 字符时滞留 buffer 等下一个 chunk（`:157-167`，防把半个围栏头当正文发出去）；in_block 态没等到闭合就 break 等数据 `:206-208`。flush `:212-251`：流结束时未闭合的块也按块产出（`:220-242`），残余 buffer 按文本产出。事件是 `{"type": "text"|"ggb_block", ...}` dict，字段与 `GGBBlock` 对齐。

现状（§0 已述）：main 上无后端调用方。它定义的 `[page_id;title]` 围栏头约定由 `VisionSolverAgent.format_ggb_block`（`vision_solver_agent.py:92`）持续产出，前端 `RichMarkdownRenderer.tsx:466` 用自己的正则解析同一个格式——后端这份解析器目前是"规范的参考实现"。

### 2.3 coord_transform —— 像素域与数学域的桥梁

两套坐标系约定见模块 docstring `coord_transform.py:1-14`：BBox 原点左上、Y 向下；GeoGebra 原点居中、Y 向上。默认数学域 `DEFAULT_GGB_COORD = [-10,10]×[-8,8]` `:65`。

- `bbox_to_ggb` `:68-99`：归一化到 [0,1] 后线性映射，X 直映射 `:94`，Y 取 `y_max - norm_y * height` 完成翻转 `:97`。`ggb_to_bbox` `:102-130` 是精确逆变换。
- `convert_bbox_elements_to_ggb` `:133-228`：批量处理 BBox 输出 dict（`image_dimensions` + `elements`），对每元素按字段名分别转换：`position` `:164-172`、线段 `start/end` `:175-193`、多边形 `vertices` `:196-206`、圆 `center` + `radius` `:209-223`（半径按 X 向比例缩放 `:222-223`）。转换结果以 `ggb_*` 前缀字段并排写入，不破坏原像素字段。
- `suggest_coord_system` `:329-406`：收集全部坐标点求包围盒，按图像宽高比推荐含 20% padding 的居中坐标系（`:386-406`）；空输入回落默认域 `:374-375`。
- 几何谓词与格式化：`validate_point_in_bounds` `:231-263`（tolerance 0.1）、`calculate_distance` `:266`、`calculate_midpoint` `:271`、`is_perpendicular` `:276-295`（点积阈值 0.01）、`is_parallel` `:298-326`（归一化叉积；零向量退化返回 False `:321-322`）、`format_ggb_point` `:409-426`、`format_set_coord_system` `:429-436`。

入参形状（`image_dimensions`/`elements`/`position`/`start`/`end`/`vertices`/`center`）正是旧 BBox 阶段的输出模型（`vision_solver` 旧版 `models.py` 的 `BBoxOutput`，坍缩前见 commit `c15e22a4b`）；单次调用方案不再产出该结构，此模块随之休眠。

### 2.4 image_utils —— URL 到 base64 的窄管道

常量：支持 MIME 白名单 `SUPPORTED_IMAGE_TYPES` `image_utils.py:12-18`（jpeg/jpg/png/gif/webp）、10MB 上限 `:21`、30s 请求超时 `:24`。

- `fetch_image_from_url` `:61-110`：先 `is_valid_image_url`（http/https + netloc，`:33-46`）拦截，再 httpx 下载（follow_redirects `:79`）；Content-Type 缺失或 `application/octet-stream` 时按 URL 扩展名推断 `:87-88`（`guess_image_type_from_url` `:113-134`，未知扩展默认 JPEG）；非白名单 MIME `:90-91` 与超限 `:94-99` 抛 `ImageError`；HTTP 状态错误/超时/网络错误分别转译 `:105-110`。
- `url_to_base64` `:155-168` = fetch + `image_bytes_to_base64`（`:137-152`，产出 `data:image/...;base64,...`）。
- `resolve_image_input` `:171-210`：统一入口——base64 优先且必须是合法 data URI（`:194-200`），否则下载 URL，两者皆无返回 None。

现状：旧 `vision_solver` REST 路由（commit `bb01d13d8` 的 `src/api/routers/vision_solver.py:62,185`）是历史调用方，该路由已删。现行工具路径不需要它：chat 循环从 turn 附件直接取 base64（`agents/loop/pipeline.py:1409-1425`），`GeoGebraAnalysisTool` 再做一次无 `data:` 前缀时的 PNG 兜底包装（`tools/builtin/__init__.py:739-740`）。

## 3. 调用方全景

### 3.1 visualize 的 GeoGebra visualizer（ggb_validator 的活跃调用方）

geogebra 是 `bundled_visualizers()` 里唯一的 bundled 插件（`visualizers/builtin.py:273-341`）：`payload_kind="json"`、`agentic` 默认 True、`default_installed=False`（`:310`，需在设置里手动安装）。

链路：`VisualizeCapability.run`（`agents/visualize/capability.py:102`）非 manim 分支 → 置 `VISUALIZE_MODE_KEY`/`REQUESTED_VISUALIZER_KEY` `:168-170` → 复用 `AgenticChatPipeline` `:188-197` → `VisualizationLoopCapability` 注入协议 block 与工具参数（`loop_capability.py:30-77,79-93`）→ LLM 调 `submit_visualization` → `SubmitVisualizationTool.execute`（`tool.py:64`）→ `plugin.validate_payload` `:98` → 对 geogebra 即 `_geogebra_validator`（`builtin.py:105-153`）：

1. JSON 解析 `:107-111`；`commands` 必须是数组 `:112-114`；清洗后 2~100 条 `:115-119`。
2. **核心委托** `:120`：`validate_ggbscript` 修复命令；有 errors 或修复后不足 2 条 → 拒绝 `:122-123`。
3. `app_name` 白名单 geometry/graphing/3d/classic `:124-126`；`view` 四界必填且 min<max `:127-145`。
4. 产出规范化 dict（`app_name/commands/view/validation_warnings` `:146-153`），作为 envelope 的 `payload.data` 提交（`tool.py:114-134`）。

校验失败时错误文本回给 LLM 修复重提（`tool.py:100-107`）；五轮耗尽仍无 envelope 则 `capability.py:198-208` 报错。成功后 `:214-218` 以 `language_tag`（geogebra 为 `json`，`builtin.py:308`）围栏把 payload 发进正文，envelope 整体进 `emit_capability_result`。

前端消费两条路都到 `web/components/Geogebra.tsx`：画布路径 `VisualizationViewer.tsx:461-485`（envelope.payload.data 直接作 `payload` prop）；正文围栏路径则只对 `ggbscript` 语言生效（geogebra envelope 的 `json` 围栏不会被 RichMarkdownRenderer 特殊处理，展示为代码块）。

### 3.2 geogebra_analysis 工具（chat + deep_solve 的图片理解入口）

用户可开关工具（`USER_TOGGLEABLE_TOOL_NAMES`，`tools/builtin/__init__.py:1907-1916`），chat 与 deep_solve 两个能力的 `tools_used` 都声明了它（`builtin_capabilities.py:64,93`）。定义 `GeoGebraAnalysisTool`（`tools/builtin/__init__.py:687-818`）：

- LLM 可见参数只有 `question`（`image_base64` 从 schema 剥除，`agents/loop/pipeline.py:1031-1035`），真实图片由服务端注入：chat 循环取附件首图并补 `data:` 前缀 `:1409-1425`；工具内对无前缀的裸 base64 再兜底一次 `:739-740`。
- 执行 `:719-777`：构造 `VisionSolverAgent`（LLM 配置经 `get_llm_config`）→ `asyncio.wait_for` 240s 上限 `:754-760`（`_VISION_ANALYSIS_TIMEOUT_S` `:693`；超时给"重试或改文字描述"的降级文案 `:761-773`）。
- `VisionSolverAgent.process`（`vision_solver_agent.py:48-80`）：单次视觉调用 `_analyze` `:96-115`（prompt 模板 `agents/vision_solver/prompts/geogebra.md`，占位符替换 `:103`）→ `_coerce_commands` 归一 `:186-205` → 空命令才触发一次 repair 重试 `:66-72`（修复 prompt 追加 `:104-108`）。JSON 提取 `_extract_json` `:144-171` 容忍 `<think>` 前导、fenced/bare JSON、前后缀杂质与尾逗号（`<think>` 剥离 `:156`，fenced 优先取最后一个 `:157-158`，尾逗号兜底 `:171`；上游 #687 想在此换 `raw_decode`，复核时注意）。
- 结果回填 `:778-818`：`final_ggb_commands` 经 `format_ggb_block`（`vision_solver_agent.py:82-92`）拼回 ` ```ggbscript[main;题目图形]` 围栏，与约束/关系摘要一起构成 ToolResult.content `:803-809`；metadata 带命令数与 `image_is_reference`。

工具提示词（`tools/prompting/hints/{zh,en}/geogebra_analysis.yaml`，加载器 `tools/prompting/__init__.py:52`，mixin `tools/builtin/__init__.py:26`）要求模型把围栏块**原样复制**进最终回答——这是 §4.2 前端渲染的前提。提示词研究流水线把 240s 值当作自己的工具超时基准（`agents/research/pipeline.py:435-439` 注释明说对齐 geogebra_analysis）。

### 3.3 math_animator：相邻面，非依赖方

visualize 能力按 `render_mode` 分流（`agents/visualize/capability.py:123-136`）：`manim_video/manim_image` 走 `_run_manim_path`（math_animator 子系统），其余（含 geogebra）走 §3.1 的 agentic 路径。两个 manim visualizer 的 manifest 也注册在同一个 registry（`visualizers/builtin.py:257-290`，`native_renderer="math_animator"`、`agentic=False`、`render_target="artifact"`）。**math_animator 不 import tools/vision**：它的视觉复核（抽帧 + VisualReviewAgent）用自带的 Attachment/base64 通道。把 tools/vision 的能力接进 math_animator 复核链属于新扩展（§7.3）。

### 3.4 题目渲染与批改：相邻但不经过 tools/vision

- 题目生成（`deep_question`，`agents/question/pipeline.py:484-504,630-669`）把图片附件直接塞进多模态 LLM 消息（`:1818-1826`），不产 ggbscript，也不用 image_utils。
- 批改（quiz judge，`api/routers/quiz_judge.py:227` WS `/questions/judge`）自己实现了等价物：附件 URL → AttachmentStore 路径解析 → base64 data URI（`_build_multimodal_user_content` `:162-210`），扩展名 → MIME 映射 `_guess_image_mime` `:213-223` 与 `guess_image_type_from_url`（`image_utils.py:113-134`）语义平行。
- 这两处是 image_utils 最自然的未来复用点（§7.4）；当前它们与 tools/vision 零耦合，追踪视觉行为时不要在这两个文件里找本工具面的符号。

## 4. 端到端数据流

### 4.1 visualize 固定 geogebra 类型（生成 → 校验 → 画布）

```
用户: visualize "……" --config render_mode=geogebra
  → VisualizeCapability.run            agents/visualize/capability.py:102   （安装检查 :115-120）
  → 置 VISUALIZE_MODE_KEY               :168-170
  → AgenticChatPipeline（chat 引擎）    :188-197
  → VisualizationLoopCapability         visualizers/loop_capability.py:30    （协议块：prompt 目录来自 registry.prompt_catalog :125）
  → LLM: submit_visualization(payload=JSON)
      → SubmitVisualizationTool.execute visualizers/tool.py:64
      → _geogebra_validator             visualizers/builtin.py:105
      → validate_ggbscript              tools/vision/ggb_validator.py:342   （逐行修复：括号/Point/log/Text）
      ← 失败: 错误回给 LLM 重提（tool.py:100-107，最多 5 轮 capability.py:190）
      ← 成功: envelope.payload.data = {app_name, commands, view}
  → 正文发 ```json 围栏 + envelope 入结果  capability.py:214-239
  → 前端 VisualizationViewer            web/components/visualize/VisualizationViewer.tsx:461-485
  → Geogebra 组件                        web/components/Geogebra.tsx:134-187  （setCoordSystem :159-167 → evalCommand 逐条 :169-183）
```

### 4.2 chat 带图提问（附件 → 视觉分析 → 围栏 → 侧栏画布）

```
用户消息 + 图片附件（chat 或 deep_solve 能力）
  → chat 循环注入附件首图                agents/loop/pipeline.py:1409-1425   （schema 剥除 image_base64 :1031-1035）
  → LLM: geogebra_analysis(question)
      → GeoGebraAnalysisTool.execute    tools/builtin/__init__.py:719        （data: 前缀兜底 :739-740；240s 上限 :754）
      → VisionSolverAgent.process       agents/vision_solver/vision_solver_agent.py:48
      → _analyze → stream_llm(视觉)     :96-141                              （空命令 → 一次 repair :66-72）
      → format_ggb_block                :82-92                               （```ggbscript[main;题目图形]）
  ← ToolResult.content 含围栏            tools/builtin/__init__.py:803-818
  → LLM 把围栏原样复制进回答            hints/{zh,en}/geogebra_analysis.yaml guideline
  → RichMarkdownRenderer               web/components/common/RichMarkdownRenderer.tsx:460-481  （围栏 → CTA 卡）
  → GeogebraOpenCTA 点击                web/components/common/GeogebraOpenCTA.tsx:48-51
  → GeogebraTabContext                  web/context/GeogebraTabContext.tsx:49-61
  → 桥接 → openGeogebraTab              ChatWorkspace.tsx:2975-2990（阅读/掌握页经 ChatViewerBridges.tsx:27-30）
  → SessionViewerPanel 标签页           web/components/chat/home/SessionViewerPanel.tsx:530-561,1350-1361
  → Geogebra 组件 evalCommand           web/components/Geogebra.tsx:84-89,169-183
```

两条流的"最后一公里"是同一个组件（`Geogebra.tsx`），但入参形态不同：envelope 路径是结构化 `payload`（含 `view` 坐标系），围栏路径是裸 `script` 文本（无 `view`，`parseGgbCommands` 剥注释后逐条执行）。

## 5. 已知坑清单

1. **三模块休眠**：block_parser / coord_transform / image_utils 在 main 上零生产调用（§0）。删改它们不会破坏现有功能，但会破坏 `__init__.py:43-79` 的导出面与 §6 在途测试卡的合并基础；反过来，"修复"它们的 bug 不改变任何用户可见行为。
2. **工具提示词漂移**：`hints/{zh,en}/geogebra_analysis.yaml` 仍写"4 阶段流水线 / 四次 LLM 调用 / 15-30 秒"，与 `vision_solver_agent.py:1-9` 的单次调用+门控修复现状不符——影响模型对工具耗时的预期与用户沟通话术，属文档债而非功能债。
3. **240s 超时被跨模块引用**：`agents/research/pipeline.py:435-439` 把 geogebra_analysis 的 240s 当作自己 tool_timeout 的对齐基准。调整 `_VISION_ANALYSIS_TIMEOUT_S`（`tools/builtin/__init__.py:693`）时要同步检查该注释与新默认值是否还自洽。
4. **`validate_ggbscript` 不传错误给 block_parser 的调用方**：`block_parser.py:93,184,225` 只取 `(fixed, warnings)` 丢弃 `errors`（`errors` 变量未被消费）——含致命错误的块（如 Text 签名非法）在解析层"静默通过"，errors 只在 visualizer 路径（`builtin.py:122-123`）被拦截。新增围栏消费方时别误以为解析过 = 校验过。
5. **geogebra visualizer 默认不安装**（`builtin.py:310` `default_installed=False`）＋ readiness 依赖行（`readiness.py:194`）：用户报"visualize 出不了几何图"时先查设置页安装态，再查 LLM 是否从未拿到 submit_visualization schema（本地推理服务默认无原生工具时 `capability.py:155-166` 只发警告不中断）。
6. **两条前端渲染路径能力不对齐**：envelope 路径支持 `view`（`Geogebra.tsx:159-167` setCoordSystem）与逐条失败收集（`:168-183` 失败命令红条提示 `:223-242`）；围栏路径无 `view`，坐标系取 GeoGebra 默认——同一道题两条路画出来的窗口可能不同。图片理解卡若要带坐标系，应考虑让 `format_ggb_block` 升级为 payload JSON 而非裸围栏。
7. **`geogebra_analysis` 单图限制**：chat 循环只注入附件首图（`pipeline.py:1410-1417` 的 `next(...)`），多图题只看第一张；工具定义参数也只收一张（`tools/builtin/__init__.py:709-716`）。
8. **`_extract_json` 的启发式边界**：`vision_solver_agent.py:159-160` 无差别剥 `//` 与 `/* */`，会把含 URL（`https://`）的合法 JSON 值削坏；`find("{")`/`rfind("}")` 截取假设整个回答只有一个 JSON 对象。上游 #687 换 `raw_decode` 可解一部分，复核时以 `tests/agents/vision_solver/` 用例为准。
9. **registry 每请求重建**：`get_visualizer_registry`（`registry.py:149-152`）每次 new（跨用户隔离设计），意味着 `SubmitVisualizationTool` 每次执行都重扫 catalog；`VisualizationLoopCapability.augment_kwargs`（`loop_capability.py:89`）注入的 registry 与执行时 `:70` 的兜底可能不是同一实例——目前只读无碍，若加进程内有状态缓存需先统一实例。

## 6. 测试现状与空白（衔接 test-vision-* 测试卡）

main 现状（基线 `f07029cfc`）：

- `tests/visualizers/test_ggb_validator.py`（163 行）：Text 命令修复/拒绝表驱动（`:12-60` 等）+ bundled visualizer 校验器整体行为；与 `tests/visualizers/test_registry_and_tool.py` 一起覆盖 §3.1。
- `tests/agents/vision_solver/test_vision_solver_agent.py`（101 行）：`_extract_json` 的 fenced/拒绝无 JSON/`verbose` kwarg 回归（`:51-73`）；即 §3.2 的 agent 层。

在途测试分支（本卡去重对象，均为新增文件、未合入 main，合并时按文件落位）：

| 分支 | 新增测试 | 规模 |
|---|---|---|
| `test/vision-block-parser-20261006` | `tests/tools/vision/test_block_parser.py` | 354 行 |
| `test/vision-coord-transform-20261005` | `tests/tools/test_coord_transform_edges.py` | 310 行 |
| `test/vision-image-utils-20261004` | `tests/tools/test_vision_image_utils.py` | 409 行 |
| `test/ggb-validator-20261007` | 扩充 `tests/visualizers/test_ggb_validator.py` | +253 行 |

空白（可拆卡）：`format_ggb_block` 与前端正则（`RichMarkdownRenderer.tsx:466`）之间的围栏头契约没有共享测试；`_geogebra_validator` 对 `view` 边界值（min≥max、非数值）已有断言但 `app_name` 白名单外的路径未覆盖；image_utils 的 `guess_image_type_from_url` 与 quiz_judge `_guess_image_mime`（`quiz_judge.py:213-223`）的映射不一致（前者含子串误判风险，如 `.png` 出现在 query 串）无任何测试守护。

## 7. 扩展新视觉工具的步骤

### 7.1 给 tools/vision 增加一个新模块（如 svg_utils、plot_extractor）

1. 实现 `deeptutor/tools/vision/<name>.py`，错误继承 `ImageError` 同款模式（自定义 Exception + 明确的转译边界，参照 `image_utils.py:27-30,105-110`）。
2. 在 `deeptutor/tools/vision/__init__.py` 补 import 与 `__all__`（两处，`:3-41` 与 `:43-79`）。
3. 若供 LLM 工具消费：在 `tools/builtin/__init__.py` 写 `BaseTool` 包装（参数里不要让 LLM 自带大数据——参照 `:1031-1035` 的 schema 剥离 + 服务端注入），类映射加进 `tools/builtin_specs.py` 的 `BUILTIN_TOOL_SPEC` 元组（`geogebra_analysis` 位于 `:70`），并按需加入 `USER_TOGGLEABLE_TOOL_NAMES`（`tools/builtin/__init__.py:1907`）。
4. 提示词 hints：`tools/prompting/hints/{zh,en}/<tool>.yaml`（六字段，参照现有 geogebra_analysis 两份；加载免代码）。
5. 能力挂载：chat 加 `builtin_capabilities.py:58-67`；deep_solve 加 `:87-95`；就绪度标签与依赖映射加 `readiness.py:145-153,194`。
6. 测试落位：跟 test-vision-* 分支的约定，放 `tests/tools/`（单元）或 `tests/visualizers/`（visualizer 集成）。

### 7.2 给 visualize 增加一个新 visualizer 类型（推荐路径）

 bundled 类型在 `visualizers/builtin.py::bundled_visualizers()` 加 `VisualizerPlugin`（manifest 七要素 + `validator`；geogebra 是唯一 JSON payload 样板 `:273-341`）。若 payload 需要命令修复，走 `validate_ggbscript` 委托并保留 `validation_warnings` 透出（`:146-153`）。前端：`VisualizationViewer.tsx:442-493` 加渲染分支，`visualize-types.ts:166-173` 的 `inferredRenderer` 白名单补 id，`web/components/Geogebra.tsx` 同款组件按需新建。这类改动不需要碰 tools/vision。

### 7.3 把休眠模块接入现役链路（复活 coord_transform / block_parser）

最有价值的两个接口点：① `format_ggb_block`（`vision_solver_agent.py:82-92`）产出前，用 `parse_ggb_blocks` 自校验产出（现在后端发出围栏后无人再验）；若让 vision_solver 同时返回 `view`（对 `suggest_coord_system` 的输出调 `format_set_coord_system` 生成 SetCoordSystem 行），即可把 §5.6 的两条路径对齐。② quiz_judge（`quiz_judge.py:162-223`）与 chat 附件注入（`pipeline.py:1409-1425`）换成 `resolve_image_input` 统一入口，消掉 §6 所列的双实现。做这两件事前先合并在途 test 分支，锁住现有行为。

### 7.4 验证清单

`timeout 900 python -m pytest -q -p no:cacheprovider tests/visualizers/test_ggb_validator.py tests/agents/vision_solver/ tests/visualizers/` 为最小回归集；改前端围栏/渲染链时补跑 `web/tests/`（`lazy-session-viewer-panel.spec.tsx`、`visualize-types.test.ts` 与 ggb 相关用例）。
