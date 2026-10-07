# imagegen / videogen 接口面扫描报告

- 日期: 2026-10-07
- 基线: origin/main @ f07029cfcf2c8dfccdb671cdfc343db8334f5741（release v1.6.13），只读扫描，未改任何代码
- 范围: `deeptutor/services/imagegen` + `deeptutor/services/videogen`，共 13 文件，全覆盖
- 结论: 两个服务均为「facade + config + adapter registry」三层结构；公开入口 5 个
  （`generate_image` / `generate_video` / `probe_video` + 两个 `get_*_adapter` 注册函数）。
  核心生成路径测试充分；**adapter 注册函数（含未知 adapter 报错路径）与 Settings 探测挂载
  （`_test_imagegen` / `_test_videogen`）、`resolve_videogen_runtime_config` 无 active model
  报错路径无测试覆盖**（详见 §4）。

## 1. 公开入口

| 入口 | 锚点 | 签名 / 返回 | 说明 |
|---|---|---|---|
| `generate_image` | `deeptutor/services/imagegen/__init__.py:17` | `async (prompt, *, catalog=None, size=None, quality=None, style=None, n=1) -> list[tuple[bytes, str]]` | facade：解析 catalog 配置（:36），size/quality/style 覆盖默认值（:37-42），按 `config.adapter` 选 adapter（:43）；空 prompt 抛 `GenerationProviderError`（:35） |
| `ImagegenConfig` | `deeptutor/services/imagegen/config.py:17` | `@dataclass(slots=True)` | 每次调用一份的已解析配置，字段见 §2 |
| `BaseImagegenAdapter` | `deeptutor/services/imagegen/base.py:10` | ABC，抽象方法 `generate(prompt, config, *, n=1)`（:13-21） | 返回 `list[(bytes, content_type)]` |
| `get_imagegen_adapter` | `deeptutor/services/imagegen/adapters/__init__.py:25` | `(name) -> BaseImagegenAdapter` | 无状态单例注册表 `IMAGEGEN_ADAPTERS`（:16-22）：`openai_compat` / `chat_completions` / `dashscope`；未知名抛 `GenerationProviderError`（:28），空名回落 `openai_compat`（:26） |
| `OpenAICompatImagegenAdapter.generate` | `deeptutor/services/imagegen/adapters/openai_compat.py:33` | `POST {base}/images/generations`（:38） | 兼容 `data[].b64_json`（:82-84，偏好）与 `data[].url`（:85-94，下载）；knobs 为空则省略（:45-52） |
| `ChatCompletionsImagegenAdapter.generate` | `deeptutor/services/imagegen/adapters/chat_completions.py:38` | `POST {base}/chat/completions`（:43） | OpenRouter 风格；`modalities:["image","text"]`，404+modalit 字样降级为 `["image"]` 重试（:64-67）；`_extract_sources`（:82）支持 message.images 与 content parts 两种嵌套；data URI 解码（:109-116）/http 下载（:117-124） |
| `DashScopeImagegenAdapter.generate` | `deeptutor/services/imagegen/adapters/dashscope.py:32` | 提交 `services/aigc/text2image/image-synthesis`（:26, :39）→ 轮询 `tasks/{id}`（:103）→ 下载 | `X-DashScope-Async: enable`（:60）；size 规范化 `1024x1024`→`1024*1024`（:69）；`_task_id`（:86）、`_poll`（:96，超时/终态处理 :121-128）、`_materialize`（:132） |
| `generate_video` | `deeptutor/services/videogen/__init__.py:21` | `async (prompt, *, catalog=None, aspect_ratio=None, duration=None, resolution=None, progress=None) -> tuple[bytes, str]` | facade：解析配置（:40），knobs 覆盖（:41-46）；`progress` 回调转发渲染进度（:48） |
| `probe_video` | `deeptutor/services/videogen/__init__.py:51` | `async (prompt, *, catalog=None) -> str` | 只提交任务返回 task id，不做渲染（Settings「Test connection」用） |
| `VideogenConfig` | `deeptutor/services/videogen/config.py:15` | `@dataclass(slots=True)` | 字段见 §2 |
| `BaseVideogenAdapter` | `deeptutor/services/videogen/base.py:15` | ABC：`submit_task`（:18-25）+ `generate`（:27-39）；`ProgressFn = Callable[[str], Awaitable[None]]`（:12） | 任务生命周期 submit → poll → download |
| `get_videogen_adapter` | `deeptutor/services/videogen/adapters/__init__.py:22` | `(name) -> BaseVideogenAdapter` | 注册表 `VIDEOGEN_ADAPTERS`（:16-19）：`async_task` / `dashscope`；未知名抛错（:25），空名回落 `async_task`（:23） |
| `AsyncTaskVideogenAdapter` | `deeptutor/services/videogen/adapters/async_task.py:41` | `submit_task` :52（`POST {base}/contents/generations/tasks`，:36）；`generate` :66（轮询 :92、下载 :80）；`_build_submit_payload` :126（Seedance 惯例：knobs 以 `--ratio/--resolution/--duration` 文本命令追加进 prompt） | 面向子类扩展：provider 差异隔离在 `_build_submit_payload` / `_extract_task_id`（:144）/ `_extract_status`（:157） |
| `DashScopeVideogenAdapter` | `deeptutor/services/videogen/adapters/dashscope.py:56` | `submit_task` :59（`services/aigc/video-generation/video-synthesis`，:26）；`generate` :74；`_payload` :109（结构化 parameters）；`_size` :135（tier×宽高比映射表 :28-52，模型档位校验 :46-52、:168；5 秒固定模型 :53, :121-125）；`_poll` :192 | 输入校验：duration 非 int 报错（:114-120）、resolution 与 aspect_ratio 冲突报错（:147-150） |

## 2. 配置项

### ImagegenConfig（`deeptutor/services/imagegen/config.py:21-38`）

| 字段 | 默认 | 说明 |
|---|---|---|
| `model` | （必填） | 活动 imagegen 模型名 |
| `provider_name` / `adapter` | `"openai"` / `"openai_compat"` | 由 catalog binding 决定；adapter 三选一 |
| `auth_style` / `api_key` / `base_url` / `api_version` / `extra_headers` | `AUTH_BEARER` / `""` / `""` / `None` / `{}` | HTTP/auth 面 |
| `size` / `quality` / `style` / `response_format` | `""` | 空 = 省略字段交 provider 默认（:29-34） |
| `request_timeout` / `poll_interval` / `poll_timeout` | `120` / `2.0` / `300` | 请求/轮询预算（:35-38） |

### VideogenConfig（`deeptutor/services/videogen/config.py:19-36`）

| 字段 | 默认 | 说明 |
|---|---|---|
| `model` | （必填） | 活动 videogen 模型名 |
| `provider_name` / `adapter` | `"volcengine"` / `"async_task"` | binding 决定 |
| `auth_style` / `api_key` / `base_url` / `api_version` / `extra_headers` | 同上 | HTTP/auth 面 |
| `aspect_ratio` / `duration` / `resolution` | `""` | Seedance 走 prompt 命令；DashScope 走结构化参数 |
| `request_timeout` / `poll_interval` / `poll_timeout` | `60` / `5.0` / `600` | 轮询预算（:31-36） |

### 配置解析（catalog → config）

| 解析函数 | 锚点 | 行为 |
|---|---|---|
| `resolve_imagegen_runtime_config` | `deeptutor/services/config/provider_runtime.py:1284` | 无 active model 抛 `ValueError`（:1294-1298）；本地 provider 免 key 填 `sk-no-key-required`（:1306-1307）；从 model 项读 size/quality/style/response_format（:1318-1321） |
| `resolve_videogen_runtime_config` | `deeptutor/services/config/provider_runtime.py:1325` | 同构；从 model 项读 aspect_ratio/duration/resolution（:1359-1361） |
| `IMAGEGEN_PROVIDERS` | `deeptutor/services/config/provider_runtime.py:495` | 8 个 binding：`dashscope`(adapter=dashscope) / `openai` / `volcengine` / `siliconflow` / `openrouter`(adapter=chat_completions) / `azure_openai`(api-key header) / `custom` / `custom_chat` |
| `VIDEOGEN_PROVIDERS` | `deeptutor/services/config/provider_runtime.py:547` | 3 个 binding：`dashscope` / `volcengine`(async_task) / `custom`(async_task) |
| `GENERATION_PROVIDER_ALIASES` | `deeptutor/services/config/provider_runtime.py:569` | `aliyun/bailian→dashscope`、`ark/volces/doubao/seedream/seedance→volcengine`、`azure/aoai→azure_openai` 等；未知 binding 回落 `custom`（:583-588） |

## 3. 工具 / capabilities 挂载点

| 挂载面 | 锚点 | 说明 |
|---|---|---|
| Chat 工具 `ImagegenTool` | `deeptutor/tools/media_gen_tool.py:135`（definition :141，execute :175） | LLM 只给 `prompt`/`size`/`n`（1-4 截断 :186）；生成字节写入 turn workspace 并返回 artifacts（`_run_dir` :56、`_write_media` :85），需再经 `workspace_present` 呈现 |
| Chat 工具 `VideogenTool` | `deeptutor/tools/media_gen_tool.py:217`（definition :223，execute :256） | `progress` 回调经 `event_sink("tool_log", …)` 转发（:267-273），失败不致命中断 |
| 工具注册表 | `deeptutor/tools/builtin_specs.py:85-86`；旧别名映射 `deeptutor/tools/builtin/__init__.py:1957-1958` | `"imagegen" / "videogen"` 两个 builtin spec |
| Pipeline 装配与门控 | `deeptutor/agents/loop/pipeline.py:726`（`_compose_enabled_tools`）、:1323（`_augment_tool_kwargs`） | 用户级 `/settings/tools` 开关 + per-user `enabled_tools`；仅当该服务有 active model 才挂载（`media_gen_tool.py` docstring :10-15） |
| Workspace 注入 | `deeptutor/agents/_shared/tool_runtime.py:15-16`（名称映射）、:105-107（`_workspace_dir` / `_workspace_id`） | 服务端注入；直连 SDK 调用无注入时落 `outputs/chat/direct/media_gen/`（`media_gen_tool.py:70-79`） |
| 前端 trace | `deeptutor/agents/loop/pipeline.py:1453-1459` | `imagegen`/`videogen` → `call_kind="media_generation"` |
| Settings 连接测试 | `deeptutor/services/config/test_runner.py:137-140` → `_test_imagegen` :564（调 `generate_image` :579）、`_test_videogen` :595（调 `probe_video` :612） | Settings UI 的「Test connection」 |
| Readiness 门控 | `deeptutor/services/config/readiness.py:195-196`（`catalog.imagegen` / `catalog.videogen` 依赖）、:153-154（tool 标签） | `tool.imagegen` / `tool.videogen` 状态（unavailable / misconfigured） |
| Settings 服务目录 | `deeptutor/services/config/model_catalog.py:158-159`、:171-172、:544-550 | `services.imagegen` / `services.videogen` 进 Settings catalog；dashscope 默认模型填充 |
| Provider links | `deeptutor/services/config/provider_links.py:101-102` | provider_ref 跨服务翻译用两张 provider 表 |

## 4. 测试现状

测试命令（限时）：`perl -e 'alarm 900; exec @ARGV' .venv/bin/python -m pytest -q -p no:cacheprovider tests/services/test_media_gen.py tests/services/imagegen/test_chat_completions_modalities.py` → **46 passed in 0.57s**（34 个测试函数，3 处 parametrize）。
关联挂载/门控面：`tests/services/config/test_readiness.py` + `tests/api/test_tools_router.py` + `tests/api/test_settings_router.py` + `tests/services/test_provider_registry_workflow.py` + `tests/services/workspace/test_content_workspace.py` → **135 passed in 1.67s**。

| 入口 / 文件 | 覆盖 | 测试锚点 |
|---|---|---|
| `generate_image` facade | ✅ | `tests/services/test_media_gen.py:567`（size 覆盖透传）、:736（空 prompt 报错） |
| `generate_video` facade | ✅ | `tests/services/test_media_gen.py:751` |
| `probe_video` | ✅ | `tests/services/test_media_gen.py:742` |
| `ImagegenConfig` / `VideogenConfig` | ✅（间接） | 经 resolve 与 adapter 测试构造（:497/:506/:531/:538 + 各 adapter 用例） |
| `resolve_imagegen_runtime_config` | ✅ | `tests/services/test_media_gen.py:497`（默认 base）、:506（openrouter→chat adapter）、:538（dashscope）、:557（无 model 报错） |
| `resolve_videogen_runtime_config` | ⚠️ 部分 | `tests/services/test_media_gen.py:531`、:538；**无 active model 的 `ValueError` 路径无测试**（imagegen 有 :557，videogen 没有对应用例） |
| `get_imagegen_adapter` / `IMAGEGEN_ADAPTERS` | ❌ 无覆盖 | 全 tests/ 无引用；未知 adapter 报错路径（`adapters/__init__.py:28`）未测 |
| `get_videogen_adapter` / `VIDEOGEN_ADAPTERS` | ❌ 无覆盖 | 同上 |
| `OpenAICompatImagegenAdapter` | ✅ | `tests/services/test_media_gen.py:122`（b64）、:141（url 下载）、:152（空下载报错）、:190（HTTP 错误） |
| `ChatCompletionsImagegenAdapter` | ✅ | `tests/services/test_media_gen.py:164`（data URI）；`tests/services/imagegen/test_chat_completions_modalities.py:30`（404 降级重试）、:64（双 modality 直达） |
| `DashScopeImagegenAdapter` | ✅ | `tests/services/test_media_gen.py:198`（提交→轮询→下载）、:247（任务失败可诊断）、:271（HTTP200 协议错误） |
| `AsyncTaskVideogenAdapter` | ✅ | `tests/services/test_media_gen.py:294`（Seedance payload 形状）、:310（submit→poll→download）、:333（失败任务报错） |
| `DashScopeVideogenAdapter` | ✅ | `tests/services/test_media_gen.py:343`、:405（具体 size）、:424（不支持档位报错）、:432（非 5 秒 duration 报错）、:439（HTTP200 协议错误） |
| `ImagegenTool` | ✅（monkeypatch facade） | `tests/services/test_media_gen.py:578`（保存→workspace_present）、:634（无注入 workspace 的 public fallback） |
| `VideogenTool` | ✅（monkeypatch facade） | `tests/services/test_media_gen.py:672`（progress 转发 + 呈现） |
| Settings 探测 `_test_imagegen` / `_test_videogen` | ❌ 无覆盖 | `deeptutor/services/config/test_runner.py:564/:595` 无对应测试；tests/ 中 test_runner 相关文件只覆盖 llm/task 探测 |
| `BaseImagegenAdapter` / `BaseVideogenAdapter` | —（抽象） | 无直接测试属预期，经具体 adapter 行使 |

**无测试覆盖的入口汇总**（验收 #2）：
1. `get_imagegen_adapter` / `IMAGEGEN_ADAPTERS`（`deeptutor/services/imagegen/adapters/__init__.py:16-29`），含未知 adapter `GenerationProviderError` 路径
2. `get_videogen_adapter` / `VIDEOGEN_ADAPTERS`（`deeptutor/services/videogen/adapters/__init__.py:16-26`），同上
3. `resolve_videogen_runtime_config` 无 active model 的 `ValueError` 路径（`deeptutor/services/config/provider_runtime.py:1335-1339`）
4. Settings 探测挂载 `_test_imagegen` / `_test_videogen`（`deeptutor/services/config/test_runner.py:564-612`）

## 5. 备注

- 两个 `__init__.py` 的 docstring 声明「chat tool、API router、config test runner」三个消费方；实测 origin/main 上 **API router 无直接调用**（`generate_image`/`generate_video` 仅被 `tools/media_gen_tool.py` 与 `config/test_runner.py` 引用），媒体生成只经 chat 工具面暴露。
- 扫描过程零代码改动；工作区未提交内容未触碰（独立 worktree `dt-agen1046-mediagen-scan-wt`，基于 origin/main 新分支）。
