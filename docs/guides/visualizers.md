# 可视化类型服务面导读（visualizers：registry/store/protocol/tool）

- 基线：origin/main `6cf793bd8`（v1.6.14）。所有 `path:line` 相对仓库根，行号随演进漂移，以符号名为准。
- 范围：`deeptutor/visualizers/**`——可视化类型的注册面、每用户持久化、消息协议、提交工具、内建清单，以及与 chat loop / API 管理面的衔接点。
- 去重：能力侧编排（`deeptutor/agents/visualize/**`：分析/生成/审查阶段、manim 子管线、请求契约、前端面板）见 guide-visualize 卡；math_animator 渲染管线见 `docs/guides/math-animator.md`；前端画布消费只在 §10/§11 作引用，不展开。

## 1. 这是什么

一个"可视化类型" = 声明式 agent 契约（manifest + prompt + 校验器）+ 画布渲染器。用户包是纯声明的 zip（`visualizer.json` + html/js/css），不能带 Python、不能注册后端代码（`deeptutor/visualizers/README.md:3-12,45-48`）；iframe 渲染器跑在无网络沙箱里，宿主与渲染器之间只有三条版本化消息：render / resize / prompt（`README.md:50-75`）。核心与内置可选类型不走 zip：manifest 由 `builtin.py` 硬声明，trusted validator 跑在宿主侧（`README.md:77-79`）。

## 2. 模块地图

| 角色 | 文件 | 关键符号 / 说明 |
| --- | --- | --- |
| 契约层 | `deeptutor/visualizers/protocol.py:14` | 三个 metadata 键（`:14-16`）、限额（`:19-20`）、`VisualizerManifest`(:23)、`VisualizationEnvelope`(:112)、`VisualizerPlugin`(:127) |
| 持久化 | `deeptutor/visualizers/store.py:38` | `VisualizerStore`：状态文件 + 用户包目录 + zip 安全导入；"拥有可变层，registry 合成保持只读"（`:39`） |
| 注册面 | `deeptutor/visualizers/registry.py:13` | `VisualizerRegistry`：core+bundled+user 三层合成；`get_visualizer_registry()`(:149) 每次调用新建实例（每用户，禁止进程单例 `:150-151`） |
| 内建清单 | `deeptutor/visualizers/builtin.py:156,318` | `core_visualizers()` 7 个 + `bundled_visualizers()` 1 个；三个 validator 工厂（`:20,:60,:105`） |
| 提交工具 | `deeptutor/visualizers/tool.py:22` | `SubmitVisualizationTool`——"从 chat loop 进入画布协议的唯一提交点"（`:23`） |
| loop 衔接 | `deeptutor/visualizers/loop_capability.py:18` | `VisualizationLoopCapability`：激活判定、协议 prompt、kwargs 注入、输出丢弃策略 |
| 公共出口 | `deeptutor/visualizers/__init__.py:3-20` | 只导出 protocol + registry 符号；store/builtin/tool/loop_capability 由宿主按模块路径直接引 |

宿主衔接点：

| 衔接 | 位置 | 说明 |
| --- | --- | --- |
| loop 注册 | `deeptutor/capabilities/registry.py:87-89` | `LoopCapabilitySpec("visualization_generation", …)`；按 `is_active` 过滤 `:218-219` |
| loop 消费 | `deeptutor/agents/loop/pipeline.py:803,816,836,848,879,904,928,958,1435` | 各 hook 在共享 loop 管线的调用点（§9） |
| 工具注册 | `deeptutor/tools/builtin_specs.py:99`；`deeptutor/tools/builtin/__init__.py:2044` | `submit_visualization` 懒加载映射 |
| 能力侧调用方 | `deeptutor/agents/visualize/capability.py:22-28,106,168-170,198` | 置/清 metadata 键、读 envelope（细节归 guide-visualize） |
| API 管理面 | `deeptutor/api/routers/visualizers.py:39-144`；挂载 `deeptutor/api/main.py:747-752` | `/api/visualizers`（带鉴权） |
| readiness | `deeptutor/services/config/readiness.py:541,892,992-995` | `visualizer_rows(public_catalog(), manim_available)` 健康行 |
| 前端画布 | `web/components/visualize/VisualizationViewer.tsx:212-221,246-253,448,496`；`web/features/chat/messages/ChatMessageList.tsx:135-136,767,1092-1093` | envelope 消费与 iframe 消息（引用） |

## 3. 依赖方向

- 分层自底向上：`protocol`（只依赖 pydantic/jsonschema，零内部依赖）← `registry`（+ `store`、`builtin`）← {`tool`、`loop_capability`、api router、`agents/visualize`、readiness}。`store`/`builtin` 不被 registry 之外的宿主直接使用（router 经 registry 间接触达）。
- 反向引用只有两处、且都是受控的：`builtin.py:8` 顶层 import `tools/vision/ggb_validator`（tools 层，无环）；`builtin.py:22-24,62-64` 在 validator 函数体内**懒加载** `agents/visualize/utils.validate_visualization`——因为 `agents/visualize/capability.py:22-28` 顶层反向 import 本包，顶层互引会成环。
- 结论：修 visualizers 内部不会波及 agents；改 `protocol.py` 的模型/键名则会波及 §2 两个表里的全部行。

## 4. protocol.py — 契约层

- 三个 context.metadata 键（`protocol.py:14-16`）：`_visualizer_mode`（激活 loop capability）、`_visualizer_result`（提交后的 envelope）、`_requested_visualizer`（用户固定类型，否则 auto）。
- 限额：payload ≤ 200k 字符（`:19`），manifest 内嵌 schema ≤ 32k（`:20`），id 正则 `^[a-z][a-z0-9_.-]{1,63}$`（`:18`）。
- `VisualizerManifest`（`:23-85`）：`extra="forbid"` 拒绝未知字段（`:26`）；`render_target ∈ native|iframe|artifact`（`:35`）；`payload_kind ∈ text|json`（`:39`）；`agentic/core/default_installed/priority`（`:43-46`）。校验器：id 规范化（`:48-54`）、`renderer_entry` 必须是安全相对路径（禁绝对路径与 `..`，`:56-65`）、`_renderer_contract`（`:67-85`）——native 必填 `native_renderer`、iframe 必填 `renderer_entry`（`:69-72`），schema 大小上限（`:73-74`），拒绝远程 `$ref/$dynamicRef`（`:75-80`，递归实现 `:194-208`），schema 自检（`:81-84`）。
- `VisualizationEnvelope`（`:112-121`）：`schema_version="deeptutor.visualization/v1"`（`:115`）+ renderer/payload/presentation/interaction/fallback，是前端画布唯一认的结果形状。
- `VisualizerPlugin`（`:127-171`）：manifest + origin（core/bundled/user，`:132`）+ 可选 trusted validator。`validate_payload`（`:136-166`）：空/超长直接拒（`:139-141`）；有 trusted validator 则完全交给它（`:142-143`）；默认路径 = JSON 解析 + manifest schema 校验并带 `$` 路径报错（`:144-164`）；text 直通（`:166`）。
- `manifest_public_dict`（`:174-191`）：对外目录视图——去掉大段的 `prompt`（`:181-182`），补 origin/installed/enabled/uninstallable（`:183-190`）。

## 5. store.py — 每用户持久化与安全导入

- 两个落点都经 PathService 按当前用户解析（`store.py:47-51`）：包目录 `<user_root>/visualizers/`、状态文件 settings 目录的 `visualizers.json`。
- 状态就是三个 id 列表（`:53-62`）：`installed`（bundled 的显式安装集）、`disabled`、`uninstalled`（bundled 显式卸载集）；写入走 tmp + replace 原子替换并排序去重（`:64-76`）。
- 写接口：`set_enabled`（`:78-86`）、`set_bundled_installed`（`:88-104`，装/卸/禁三集合联动搬移）。
- 发现：`user_packages`（`:106-126`）扫目录下带 `visualizer.json` 的子目录；坏包静默跳过（`:121-124`，注释说明 API 安装时已严格校验，这里是崩溃恢复路径）。
- `install_archive`（`:128-171`）是导入安全的主战场：zip ≤25MB（`:13,:135-136`）、解压目标先落临时目录（`:137-139`）、包根定位（`:209-216`，根或单层子目录）、manifest 校验（`:141-149`）、`_validate_imported_manifest`（`:150,:192-207`：**强制清零 core/default_installed**——安装策略归宿主，`:194-198`；仅允许 iframe 目标 `:199-202`；`renderer_entry` 必须是包内存在的 .html `:203-207`）、id 不得与宿主保留冲突（`:151-152`）、目标目录必须落在 root 内（`:153-155`）、已存在即拒（`:156-157`）、staging 目录 + 原子 rename（`:158-169`）、装完默认启用（`:170`）。
- `_extract_archive`（`:218-251`）逐条防线：绝对路径/`..` 拒（`:233-234`）、`__MACOSX` 与点文件跳过（`:235-236`）、后缀白名单 `_ALLOWED_SUFFIXES`（`:18-31,:237-238`）、单条 ≤10MB（`:14,:239-240`）、解压比 >100 判压缩炸弹（`:17,:241-242`）、累计 ≤25MB（`:243-245`）、落点 resolve 后再验包含关系（`:246-248`）、条数 ≤200（`:16,:227-228`）。
- `uninstall_user`（`:173-183`）删目录并清理状态；`asset_path`（`:185-190`）resolve 后验证仍在包内，供 API 静态资产路由用。

## 6. registry.py — 三层目录合成

- `reload()`（`:21-50`）是唯一合成点：core 全部进目录且视为已装（`:29-31`）→ bundled 进目录，按"显式 installed 或 default_installed 且不在 uninstalled"决定安装（`:32-37`）→ user 包补位，id 冲突时宿主让位规则是 `setdefault`/跳过（`:38-46`）；`enabled = installed − disabled`（`:50`）。
- 读接口：`catalog()` 按 priority 升序（`:52-53`）、`installed(include_disabled=False)`（`:55-57`）、`agentic()`（`:59-60`）、`get(require_enabled=True)`（`:62-70`）、`public_catalog()`（`:72-80`）。
- 写接口统一"store 落盘 + reload"：`set_enabled`（`:82-87`）、`install_bundled`（`:89-94`，仅 origin=bundled）、`uninstall`（`:96-106`，core 不可卸只能禁 `:100-101`）、`install_archive`（`:108-117`，`reserved_ids` 传现有目录防覆盖 `:111`）。
- `asset_path` 只对 user 包开放（`:119-123`）。
- `prompt_catalog(requested)`（`:125-146`）：把 agentic 类型的 manifest 渲染成注入 system prompt 的目录文本——每块含 id/名称/Use for/payload 格式 + schema JSON + Rules（`:132-145`）；requested ≠ auto 时单选且该类型必须 agentic（`:127-131`）。注意 core 里两个 manim 类型 `agentic=False`，不进这份目录。
- `get_visualizer_registry()`（`:149-152`）：**每次调用新建**，注释明说 per-user 路径决定不能做进程单例——补测时不要引入缓存。

## 7. builtin.py — 内建与可选类型清单

| id | origin | render_target / renderer | priority | agentic | validator |
| --- | --- | --- | --- | --- | --- |
| `geogebra` | bundled | native / geogebra | 5（默认不装 `:334`） | ✓ | `_geogebra_validator` |
| `svg` | core | native / svg | 10 | ✓ | `_text_validator("svg")` |
| `mermaid` | core | native / mermaid | 20 | ✓ | `_text_validator("mermaid")` |
| `mindmap` | core | native / mermaid | 25 | ✓ | `_text_validator("mindmap")` |
| `chartjs` | core | native / chartjs | 30 | ✓ | `_json_visualization_validator("chartjs")` |
| `html` | core | native / html | 40 | ✓ | `_text_validator("html")` |
| `manim_video` | core | **artifact** / math_animator | 200 | ✗ | 无 |
| `manim_image` | core | **artifact** / math_animator | 210 | ✗ | 无 |

- validator 链：text/json validator 先委托 `agents/visualize/utils.validate_visualization`（`builtin.py:22-24,62-64`；定义 `deeptutor/agents/visualize/utils.py:112`）做基础校验，再叠类型特定规则——svg 必须带 `<title>/<desc>` 可访问性元素（`:27-34`）；html 必须完整文档 + viewport + 学习者控件 + reset + label（`:35-54`）；chartjs 校验 type 白名单与 datasets 结构（`:71-99`）；geogebra 独立走 `tools/vision/ggb_validator.validate_ggbscript`（`:120`；定义 `deeptutor/tools/vision/ggb_validator.py:342`），命令数 2–100、app_name 白名单、view 四边界必填且合法（`:112-145`），返回归一化后的 payload（`:146-153`）。
- 每个类型 prompt = 共享 `_GENERAL`（`:12-17`，"生成可视化本身而不是解说"）+ 类型专属规则；geogebra 的 prompt 最长（`:336-361`）。
- 两个 manim 条目（`:280-314`）是"占位目录项"：`render_target="artifact"`、`agentic=False`，不进 prompt_catalog、`SubmitVisualizationTool` 也会拒绝（`tool.py:90-96`）；实际渲染走能力侧专用子管线（见 guide-math-animator）。

## 8. tool.py — 唯一提交点

- `SubmitVisualizationTool.execute`（`tool.py:64-145`）流程：从注入 kwargs 取 `_visualize_context`/`_visualizer_registry`（`:65-70`，缺 context 直接失败）；用户固定类型与提交 id 不一致即打回重做（`:73-89`）；类型必须已装且 agentic，否则列出可用集合（`:90-96`）；`validate_payload` 失败返回带 `validation_error` 的失败 ToolResult 引导模型修复（`:98-107`）；iframe 类型拼 `entry_url=/api/visualizers/{id}/assets/{renderer_entry}`（`:109-113`）；组装 envelope（`:114-133`，interaction 仅 iframe 带 `prompt/resize` `:129-131`，非 svg 填 `fallback={"renderer":"svg"}` `:132`）；**提交 = 写 `context.metadata[_visualizer_result]`**（`:134`）。
- 模型可见参数只有 visualizer/payload/title/description/alt_text（`:33-61`）；私有注入参数由 loop capability 提供（§9），模型不可伪造。
- 注册面：懒加载 spec `deeptutor/tools/builtin_specs.py:99` 与名称映射 `deeptutor/tools/builtin/__init__.py:2044`；`VISUALIZER_TOOL_TYPES`（`:148`）只是导出面，宿主不直接消费。

## 9. loop_capability.py — chat loop 衔接

`VisualizationLoopCapability` 挂在共享 chat loop 上（`deeptutor/capabilities/protocol.py:38` `LoopExtension` 协议；注册 `deeptutor/capabilities/registry.py:87-89`），各 hook 与宿主调用点：

| hook | 本包 | 宿主调用点 | 行为 |
| --- | --- | --- | --- |
| `owned_tools` | `loop_capability.py:20` | `pipeline.py:816-821` | 把 `submit_visualization` 加进本轮工具面 |
| `buffers_visible_output=True` | `:21-25` | `pipeline.py:958-982`、`agent_loop.py:447` | 每轮都是协议工作、正文必被丢弃，故缓冲不流式 |
| `is_active` | `:27-28` | `pipeline.py:803-804`→`registry.py:218-219` | 看 `_visualizer_mode` |
| `system_block` | `:30-77` | `pipeline.py:836-846` | zh/en 双语协议 preamble（提交后不重复正文、失败要修复不降级 `:50-52,:68-70`）+ `prompt_catalog(requested)`，合成 `PromptBlock("visualization_protocol")`（`:77`） |
| `augment_kwargs` | `:79-93` | `pipeline.py:1435` | 仅对 `submit_visualization` 注入 context/registry/requested 三个私有 kwargs（`:88-92`） |
| `pre_loop_seed` | `:95-97` | `agent_loop.py:319` | `[Visualization mode: requested_type=…]` |
| `finish_instruction` | `:99-107` | `agent_loop.py:628,849` | 未提交时催交/修复；已提交返回空放行 |
| `tool_round_output_policy` | `:109-116` | `agent_loop.py:692` | 恒 `"discard"`——工具轮正文无条件丢弃 |
| `final_text_override` | `:118-122` | `agent_loop.py:640` | 已提交则正文置空，画布 payload 就是交付物 |

## 10. API 管理面

router 挂载在 `/api/visualizers`（`deeptutor/api/main.py:749-753`，鉴权依赖）。`deeptutor/api/routers/visualizers.py`：

- `GET /list`（`:39-45`）→ `public_catalog()`，schema `deeptutor.visualizer-catalog/v1`。
- `POST /bundled/{id}/install`（`:48-56`）、`POST /{id}/enable|disable`（`:59-76`）、`DELETE /{id}`（`:79-86`）；`VisualizerStoreError` → 404/409/400 映射（`:30-36`）。
- `POST /import`（`:89-126`）：上传 ≤25MB（`:17,:106-110`）→ 临时文件 → `registry.install_archive` → 回显 public manifest。
- `GET /{id}/assets/{path}`（`:129-144`）：经 `registry.asset_path` 防穿越；响应带严格 CSP（`:18-27`，`connect-src 'none'`、`frame-ancestors 'self'`）、CORP same-origin、nosniff、私有短缓存（`:139-143`）——iframe 渲染器在此约束下加载。
- readiness 侧：`visualizer_rows`（`deeptutor/services/config/readiness.py:541`）在 `:992-995` 用 `public_catalog()` + manim 可用性生成健康行。

## 11. 端到端数据流

**通用 chat-loop 路径**（svg/mermaid/mindmap/chartjs/html/geogebra）：

1. 请求带 render_mode 进入 `VisualizeCapability.run`（`deeptutor/agents/visualize/capability.py:102`）；analyzing 阶段校验固定类型已装且启用（`:106-110`）。能力侧阶段编排详见 guide-visualize。
2. 非 manim 分支：置 `_visualizer_mode=True`、`_requested_visualizer=render_mode`、清旧 result（`:168-170`）；内置工具收敛为只读安全集 `_VISUALIZE_SAFE_BUILTINS`（`:77-87,:171-176`）；起 `AgenticChatPipeline(max_rounds=5)`（`:188-196`）。
3. loop 内：`is_active` 命中 → `system_block` 注入协议 + 类型目录（`pipeline.py:836-846` ← `loop_capability.py:30-77`）；`submit_visualization` 进工具面（`pipeline.py:816` ← `builtin_specs.py:99`）。
4. 模型生成 payload 调 `submit_visualization` → `augment_kwargs` 注入依赖（`pipeline.py:1435` ← `loop_capability.py:79-93`）→ `execute` 校验并提交 envelope（`tool.py:64-145`）；校验失败信息回流，模型下一轮按具体错误修复。
5. 轮间正文恒被丢弃（`agent_loop.py:692`）；提交成功后正文置空（`agent_loop.py:640`）；整轮无提交则 `finish_instruction` 催交（`agent_loop.py:628`），最终由能力侧抛 no_payload 诊断（`capability.py:198-206,247-`）。
6. 能力侧读 envelope（`capability.py:198-204`），payload 序列化成 ```lang 代码块推流（`:211-218`），合并 legacy `response/code/analysis/review` 字段后 `emit_capability_result`（`:239`；共享实现 `deeptutor/agents/_shared/capability_result.py:21`）。
7. 前端：ChatMessageList 取 visualizeResult → `VisualizationViewer`（`ChatMessageList.tsx:135-136,767,1092-1093`）；按 `renderer.native_renderer/render_type` 分发（`VisualizationViewer.tsx:448,496`）；iframe 渲染器从 `/api/visualizers/{id}/assets/…` 加载（CSP 见 §10），与宿主互发 render/resize/prompt 消息（`README.md:50-75`；实现 `VisualizationViewer.tsx:212-221,246-253`）。

**manim 分支**：render_mode ∈ {`manim_video`,`manim_image`} 时在 `:123-137` 直接转 `_run_manim_path`（`:270`，镜像 `MathAnimatorCapability.run`），与类型注册面只共享 §7 两个目录条目；管线细节见 `docs/guides/math-animator.md`。

**生命周期流**（管理面）：设置页 `GET /api/visualizers/list` → `POST /import`（zip → store.install_archive → reload → 回显）；bundled 安装/卸载/启停都是"store 落盘 + registry.reload"；重启后 `state()` 从 `visualizers.json` 重建整张目录（`registry.py:21-50` ← `store.py:53-62`）。

## 12. 测试锚点

- `tests/visualizers/test_registry_and_tool.py:10-13`：registry 合成/启停/卸载、store 状态文件、tool 校验与 envelope 提交（`:20` 注入隔离的 store 路径；`:202` 断言 `context.metadata[_visualizer_result]`）。
- `tests/visualizers/test_ggb_validator.py:9`：bundled geogebra validator。
- `tests/api/test_visualizers_router.py:15-28`：router 以注入的 registry 替身覆盖 list/生命周期/资产路由。
- `tests/runtime/test_lazy_builtin_catalogs.py:50`：loop capability 懒加载目录一致性。
- 补测取数建议：改校验行为（`protocol.py`/`builtin.py`）跑 `tests/visualizers` + `tests/api/test_visualizers_router.py`；改 store 导入安全（`store.py`）重点覆盖 `install_archive` 的拒绝分支；改 loop 衔接（`loop_capability.py`）对照 `tests/runtime` 与 `tests/visualizers/test_registry_and_tool.py` 的 tool 用例。
