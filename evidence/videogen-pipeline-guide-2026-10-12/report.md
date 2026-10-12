# 视频生成管线导读：`deeptutor/services/videogen/`

基线：`origin/main` @ `6cf793bd`（release v1.6.14）。只读导读，不改任何源码。
所有结论均给出 `path:line` 锚点（行号基于该提交）。

## 0. 范围与去重

- 本报告只覆盖**视频轴**：`deeptutor/services/videogen/`（base/adapters/config）及其上下游调用面。图像轴（`imagegen`）由 guide-imagegen 卡覆盖；管线测试补充由 test-videogen-pipeline 卡覆盖，本报告只列测试缺口、不落测试代码。
- 阅读顺序建议：`config.py` → `base.py` → `adapters/async_task.py` → `adapters/dashscope.py` → `__init__.py`（facade）→ 工具层 `tools/media_gen_tool.py` → 目录解析 `services/config/provider_runtime.py`。

## 1. 数据流：从一次任务到产物

### 1.1 总览

```
chat LLM ──调用工具──▶ VideogenTool.execute
                          │  校验 prompt，包装 progress(event_sink)
                          ▼
                    generate_video()                      facade, deeptutor/services/videogen/__init__.py:21
                          │  resolve_videogen_runtime_config(catalog)   目录→配置
                          │  get_videogen_adapter(config.adapter)       注册表取适配器
                          ▼
              AsyncTaskVideogenAdapter / DashScopeVideogenAdapter
              submit_task → _poll（deadline 内轮询）→ GET video_url → bytes
                          ▼
                 (video_bytes, content_type)
                          ▼
              _run_dir / _write_media / collect_public_artifacts
                          ▼
              ToolResult(metadata.artifacts) ──▶ 前端按 workspace_present 展示
```

### 1.2 逐层说明

1. **工具层（入口）**：`VideogenTool` 定义于 `deeptutor/tools/media_gen_tool.py:217`，工具名 `videogen`（`deeptutor/tools/media_gen_tool.py:225`），参数只有 `prompt` / `aspect_ratio` / `duration`（`deeptutor/tools/media_gen_tool.py:235-249`）；`resolution` 不在工具层暴露，只能来自目录模型条目或 Settings 预览。
2. **工具层执行**：`execute` 在 `deeptutor/tools/media_gen_tool.py:256`。空 prompt 直接失败（`:261`）；`_progress` 把渲染状态经 `event_sink("tool_log", message)` 发给聊天流（`:267-273`），发不出去只记 debug、绝不中断渲染。随后调 `generate_video(prompt, aspect_ratio=…, duration=…, progress=…)`（`:276-280`）。
3. **配置解析**：`generate_video` 先 `resolve_videogen_runtime_config(catalog=catalog)`（`deeptutor/services/videogen/__init__.py:40`，实现 `deeptutor/services/config/provider_runtime.py:1358`）。取 active profile/model（`provider_runtime.py:1366`，辅助函数 `:755`）；没有激活模型即抛 `ValueError`（`:1369-1372`）。provider 名经 `GENERATION_PROVIDER_ALIASES` 归一后在 `VIDEOGEN_PROVIDERS` 表里定 adapter/auth/default base（`provider_runtime.py:1374-1377`，表 `:537-553`：`dashscope→dashscope 适配器`、`volcengine→async_task`、`custom→async_task`）。生成参数 `aspect_ratio` / `duration` / `resolution` 从目录模型条目读入（`provider_runtime.py:1392-1394`）。
4. **调用级覆盖**：facade 用本次调用的 `aspect_ratio` / `duration` / `resolution` 覆盖目录默认（`deeptutor/services/videogen/__init__.py:41-46`），再经 `get_videogen_adapter(config.adapter)` 选适配器（`:47`，注册表 `deeptutor/services/videogen/adapters/__init__.py:16-26`；空名回退 `async_task`，未知名抛 `GenerationProviderError`）。
5. **配置载体**：`VideogenConfig`（`deeptutor/services/videogen/config.py:15-36`）除生成参数外带轮询预算：`request_timeout=60`（单次 HTTP 上限）、`poll_interval=5.0`、`poll_timeout=600`（整次渲染上限）（`config.py:34-36`）。
6. **async_task 适配器主流程**（`deeptutor/services/videogen/adapters/async_task.py`）：`submit_task` POST `{base}/contents/generations/tasks`（路径常量 `:36`，拼接 `join_api_path`，`deeptutor/services/generation_http.py:57`）并提取任务 id（`:62`；id 提取兼容 `id` / `task_id` / `data.id`，`:144-154`）。`generate` 依次：submit（`:73`）→ 通知 progress（`:74`）→ `_poll` 轮询到终态拿 `video_url`（`:78`，循环体 `:92-121`）→ GET 下载字节（`:80-83`）→ 空文件拒绝（`:86-87`）→ 非 `video/*` content-type 归一为 `video/mp4`（`:88-89`）。
7. **轮询细节**：deadline 用 `time.monotonic() + poll_timeout`（`async_task.py:101`）；成功态集合 `_SUCCESS_STATES={succeeded,success,completed,done}`（`:37`），失败态 `_FAILURE_STATES={failed,error,cancelled,canceled,expired}`（`:38`）；状态名统一 lower 后匹配（`:162`）。每 3 次轮询发一次 progress（`:118-120`）；每次循环 `await asyncio.sleep(poll_interval)`（`:121`）。
8. **dashscope 适配器差异**（`deeptutor/services/videogen/adapters/dashscope.py`）：提交路径 `services/aigc/video-generation/video-synthesis`（`:26`），必须带 `X-DashScope-Async: enable` 头（`:103`）；请求体是结构化 `{model, input.prompt, parameters.size/duration}`（`:109-132`），分辨率按 `_SIZES_BY_TIER`（`:28-44`）与 `_MODEL_TIERS`（`:46-52`）映射成 `宽*高`，部分老模型固定 5 秒（`:53`、`:121-125`）。轮询走 `tasks/{task_id}`（`:200`），状态字段是 `output.task_status`（`:213`），成功但无 URL 直接报错（`:215-218`）。
9. **工具层落盘**：成功后 `_run_dir` 在 `<workspace>/outputs/.../media/` 下开每次调用独立的 `videogen_<uuid12>/` 目录（`deeptutor/tools/media_gen_tool.py:56-83`；真实聊天回合由服务端注入 `_workspace_dir`/`_workspace_id`，见 `deeptutor/agents/_shared/tool_runtime.py:88-96`；直连调用回退 runtime workspace）。`_write_media` 写文件并经 `collect_public_artifacts` 产出公共 artifact 列表（`media_gen_tool.py:85-103`）；`_artifact_result` 组装 ToolResult（`:106-131`）。
10. **保存与展示分离**：artifact 返回时带 `already_presented` 标记（`media_gen_tool.py:106-131`），模型必须再调 `workspace_present` 才能在回复里引用路径——工具描述里明说（`media_gen_tool.py:228-234`）；该契约有测试锁定（`tests/services/test_media_gen.py:672-735`）。
11. **挂载与门控**：chat 管线用 `drop_unconfigured_generation_tools` 把没有激活视频模型的 `videogen` 工具从工具表里摘掉（`deeptutor/agents/_shared/tool_runtime.py:20-40`；调用点 `deeptutor/agents/loop/pipeline.py:783`、`deeptutor/agents/question/pipeline.py:1614`）。前端把该工具的调用渲染为 `call_kind="media_generation"`（`deeptutor/agents/loop/pipeline.py:1460-1466`）。
12. **旁路一：Settings 预览**：`service_preview.py` 对 `videogen` 直接走 `generate_video(text, catalog, progress)`（`deeptutor/services/settings/service_preview.py:127-129`），SSE 超时 600s（`:136`），provider 异常一律折叠成 `{"type":"error","code":"failed"}`，不外泄请求体/签名 URL/凭据（`:140-143`）。
13. **旁路二：Settings 测连**：`ConfigTestRunner._test_videogen`（`deeptutor/services/config/test_runner.py:599-623`）用 `probe_video` 只提交任务拿 task_id、不等待渲染（`deeptutor/services/videogen/__init__.py:51-62`；结果提示"Generation and playback were not verified"，`test_runner.py:147`）。
14. **旁路三：Settings 路由**：`deeptutor/api/routers/settings.py:737-759` 把 `VIDEOGEN_PROVIDERS` 表暴露给前端做服务商选项；`:805` 把同一张表用于凭据预填联动。

## 2. 扩展点（可照做）

1. **新增"任务式"视频服务商（复用轮询机制）**：继承 `AsyncTaskVideogenAdapter`，只覆盖 `_build_submit_payload` / `_extract_task_id` / `_extract_status` 三个静态方法（模块 docstring 明示此意图，`deeptutor/services/videogen/adapters/async_task.py:9-14`；方法本体 `:126-174`），然后在 `VIDEOGEN_ADAPTERS` 注册表加一个键（`deeptutor/services/videogen/adapters/__init__.py:16-19`）。照做示例：某服务商要结构化字段而非 Seedance 的 prompt 后缀命令，就重写 `_build_submit_payload` 返回自己的 JSON 体。
2. **新增 provider 绑定（Settings 目录入口）**：往 `VIDEOGEN_PROVIDERS` 加一条 `GenerationProviderSpec`（label、default_api_base、adapter、default_model，`deeptutor/services/config/provider_runtime.py:466-480` 定义、`:537-553` 视频表），老名字兼容加进 `GENERATION_PROVIDER_ALIASES`（`:555-568`）。之后 `resolve_videogen_runtime_config`（`:1358`）和 Settings 路由（`deeptutor/api/routers/settings.py:737-759`）自动生效，无需改动。
3. **调用级参数覆盖**：`generate_video(..., aspect_ratio/duration/resolution)` 会在目录默认之上做单次覆盖（`deeptutor/services/videogen/__init__.py:41-46`）。工具层目前只透出 `aspect_ratio`/`duration`（`deeptutor/tools/media_gen_tool.py:235-249`）；若要让模型控制 `resolution`，照 `aspect_ratio` 的写法在 ToolDefinition 加参数并在 `execute` 透传即可（这是最小可照做的功能扩展）。
4. **进度回调**：`ProgressFn = Callable[[str], Awaitable[None]]`（`deeptutor/services/videogen/base.py:12`）。接入方只需给 `generate`/`generate_video` 传 async 回调；适配器在 submit 后、下载前、每 3 次轮询各发一条状态（`async_task.py:74,79,118-120`）。工具层的参考实现是"包 event_sink、异常只 debug"（`deeptutor/tools/media_gen_tool.py:267-274`）。
5. **轮询预算调参**：`VideogenConfig` 的 `request_timeout` / `poll_interval` / `poll_timeout`（`deeptutor/services/videogen/config.py:31-36`）目前取 dataclass 默认值，目录解析不填（`provider_runtime.py:1383-1394` 未包含这三个字段）；要在 Settings 暴露"渲染超时"，可在这三个字段上加目录字段透传——改动面仅限 config 与 provider_runtime 两处。

## 3. 失败语义（可拆测试）

统一异常类型是 `GenerationProviderError`（`deeptutor/services/generation_http.py:24-26`）；"未配置"用 `ValueError`。工具层把两类都折叠成 `ToolResult(success=False)` 返还给模型（`deeptutor/tools/media_gen_tool.py:282-286`）。

1. **未配置 / 空 prompt**：无激活视频模型 → `ValueError("No active video-generation model is configured…")`（`deeptutor/services/config/provider_runtime.py:1369-1372`）；空 prompt → `GenerationProviderError`（`deeptutor/services/videogen/__init__.py:37-39`）。工具层 `except ValueError` / `except GenerationProviderError` 分别接住（`media_gen_tool.py:282-286`）。既有测试：`tests/services/test_media_gen.py:557`、`:736`。
2. **传输层错误**：`httpx.HTTPError`（超时、连接失败）在 submit（`async_task.py:63-64`）和 generate/download（`:84-85`）两处包成 `GenerationProviderError`；dashscope 对应 `:71-72`、`:90-91`。HTTP ≥400 由 `raise_for_provider` 抛出，响应体截断到 400 字符进错误消息（`deeptutor/services/generation_http.py:76-83`）。
3. **HTTP 200 协议错误**：响应成功但载荷不合预期——拿不到 task id（`async_task.py:154`、`dashscope.py:190`）、状态载荷非 dict（`:161`、`dashscope.py:161,208,212`）、DashScope 的 `{code, success:false}` 业务错误体（`_raise_dashscope_error`，`dashscope.py:175-179`，在 submit `:186` 与 poll `:209` 两处检查）都会抛 `GenerationProviderError`。既有测试：`tests/services/test_media_gen.py:439`（HTTP 200 quota exceeded）。
4. **任务终态失败**：轮询命中 `_FAILURE_STATES` → `Video task {id} {status}: {error}`（`async_task.py:109-112`）；dashscope 失败集合多含 `unknown`（`dashscope.py:219`），成功却无 `video_url` 单独报错（`:215-218`）。既有测试：`tests/services/test_media_gen.py:333`。
5. **渲染超时**：整次渲染受 `poll_timeout=600` 预算约束，超时消息带最后一次状态（`async_task.py:113-117`、`dashscope.py:222-226`）。注意两个细节：deadline 只在"收到一次成功轮询响应之后"才检查，挂死在单个 GET 上由 `request_timeout=60` 兜底（`config.py:34`）；超时前最后一次 sleep 不受 deadline 影响。**测试缺口：无任何用例覆盖 deadline 分支**——可拆测试：`poll_timeout` 设极小值 + 状态永远 `running`，断言错误消息含 `timed out` 与 last status。
6. **空文件与类型归一**：下载体为空 → `GenerationProviderError`（`async_task.py:86-87`、`dashscope.py:92-93`）；content-type 非 `video/*`（如网关回 `application/octet-stream`）被宽容地归一为 `video/mp4`（`async_task.py:88-89`、`dashscope.py:95-96`）。**测试缺口：content-type 归一无直接单测**——可拆测试：下载响应头 `content-type: application/octet-stream`，断言返回 `("…", "video/mp4")`。
7. **未知适配器名**：`get_videogen_adapter` 对未注册名字抛 `GenerationProviderError("Unsupported videogen adapter…")`，空/None 回退 `async_task`（`deeptutor/services/videogen/adapters/__init__.py:22-26`）。**测试缺口：该函数无直接单测**——可拆测试：`get_videogen_adapter("nope")` 抛错、`get_videogen_adapter("")` 返回 AsyncTask 实例。
8. **进度发射永不致命**：工具层 progress 异常只 debug（`media_gen_tool.py:271-274`）；适配器 `_notify` 在 progress 为 None 时 no-op（`async_task.py:176-179`）。既有测试锁定"progress 必须转发且渲染继续"：`tests/services/test_media_gen.py:672-735`。
9. **错误信息边界**：面向模型/用户的错误消息只含状态与 provider 消息；Settings 预览层进一步把异常折叠成 `code:"failed"`（`service_preview.py:140-143`），测连层只回 task_id（`test_runner.py:616-623`）。

## 4. 既有测试与验证

- 覆盖面：`tests/services/test_media_gen.py` 共 44 个用例（imagegen + videogen + 目录解析 + 工具层），其中 videogen 相关集中在 `:294-495`（payload 形状、submit→poll→download、失败任务、DashScope 尺寸表/固定 5 秒/HTTP200 协议错）、`:531-556`（目录解析选适配器）、`:672-765`（工具层 progress+落盘+展示、probe、facade）。
- 本卡实跑（基线 `6cf793bd`，解释器 `/Users/Shared/DeepTutor/.venv`，导入确认来自本 worktree）：
  `python -m pytest -q -p no:cacheprovider tests/services/test_media_gen.py` → **44 passed in 0.53s**（以 Python `subprocess.run(timeout=900)` 包裹限时，前台等待完成）。
- 可拆测试清单（供 test-videogen-pipeline 卡参考，本卡不落码）：§3.5 轮询 deadline、§3.6 content-type 归一、§3.7 未知适配器、§2.1 自定义子类 provider 冒烟。
