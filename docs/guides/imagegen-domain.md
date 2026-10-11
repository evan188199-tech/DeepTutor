# DeepTutor `services/imagegen` 图像生成域导读

- 基线：origin/main @ `6cf793bd8`（v1.6.14）。
- 范围：`deeptutor/services/imagegen/` 的 base/config 适配器契约、三个 adapters 的家族差异、调用方接线与配置面。
- 明确不展开（避免与其它导读重复）：工具注册链与每轮挂载见 `docs/guides/tools-surface.md` §2/§3；进度与 trace 事件链见 `docs/guides/events-and-progress-chain.md`；LLM/embedding 等 provider 体系本身不属于本文，本文只从 imagegen 读侧引用 `provider_runtime` 的解析机制。
- 所有锚点形如 `path:line`，相对仓库根。

## 1. 这一层是什么：一张图

```
模型目录(Settings) ──resolve_imagegen_runtime_config──▶ ImagegenConfig
  provider_runtime.py:1317                                config.py:17
                                                              │
  IMAGEGEN_ADAPTERS[config.adapter]  ◀── get_imagegen_adapter ┘
    adapters/__init__.py:16                     adapters/__init__.py:25
                                                              │
        ┌─────────────────────┬──────────────────────┐         │
  openai_compat          chat_completions          dashscope   │
  images/generations     chat/completions+modalities  submit+poll
                                                              ▼
                                              list[tuple[bytes, str]]
```

包内共 5 个文件：`base.py`（抽象契约）、`config.py`（运行时配置）、`__init__.py`（公共 facade `generate_image`）、`adapters/__init__.py`（注册表）、`adapters/{openai_compat,chat_completions,dashscope}.py`（三种 HTTP 形态）。设计取向：**每个 provider 家族一个适配器，而不是每个 provider 一个类**——同一家族的供应商只换 `base_url + api_key + model`（`deeptutor/services/imagegen/config.py:2-8` 模块注释，镜像 `TTSConfig` 的做法）。

## 2. 契约层：`BaseImagegenAdapter` 与 `ImagegenConfig`

**抽象契约** `deeptutor/services/imagegen/base.py:10`：只有一个抽象方法 `generate(prompt, config, *, n=1)`（`deeptutor/services/imagegen/base.py:13-21`），返回 `list[tuple[bytes, str]]`——`(图片字节, content_type)`，content_type 是 best-effort（通常 `image/png`）。**适配器必须把远端各种形态（b64、URL、data URI、轮询任务）都消化成内存字节**，调用方永远拿不到会过期的 provider URL。

**运行时配置** `ImagegenConfig`（`deeptutor/services/imagegen/config.py:17`，`@dataclass(slots=True)`）逐字段：

| 字段 | 默认 | 说明 |
|---|---|---|
| `model` | 必填 | 解析后的模型 id，空则解析层直接抛错 |
| `provider_name` | `"openai"` | 目录里的 provider 键（诊断/日志用） |
| `adapter` | `"openai_compat"` | 注册表键，决定 HTTP 形态 |
| `auth_style` | `AUTH_BEARER` | `bearer` 或 `api_key_header`（Azure），见 `deeptutor/services/generation_http.py:20-21` |
| `api_key` / `base_url` / `api_version` / `extra_headers` | 空 | 端点四件套；`base_url` 为空时适配器直接抛 `GenerationProviderError` |
| `size` / `quality` / `style` / `response_format` | `""` | 生成旋钮，空串=不进请求体，交给 provider 默认（`deeptutor/services/imagegen/config.py:29-34`） |
| `request_timeout` | `120` | 单次 HTTP 墙钟（图像生成慢，给得宽） |
| `poll_interval` / `poll_timeout` | `2.0` / `300` | 仅 dashscope 异步轮询使用 |

约定：**Config 是"已解析"的值对象**——不含 provider 目录逻辑，目录→Config 的翻译全部在解析层（§5）。

## 3. adapters 家族差异

三个适配器都无状态、可作单例复用；差异全在"一次 HTTP 交互的形状"：

| | `openai_compat` | `chat_completions` | `dashscope` |
|---|---|---|---|
| 端点 | `POST {base}/images/generations` | `POST {base}/chat/completions` | `POST {base}/services/aigc/text2image/image-synthesis`（`deeptutor/services/imagegen/adapters/dashscope.py:26`）+ `GET {base}/tasks/{id}` |
| 协议 | OpenAI Images API | OpenRouter 风格 chat 图像输出 | DashScope 原生异步任务 |
| 同步/异步 | 同步 | 同步 | 异步：submit→poll→download（`_poll`，`deeptutor/services/imagegen/adapters/dashscope.py:96`） |
| 图像来源 | `data[].b64_json` 优先，`data[].url` 兜底下载 | 消息内 `images[].image_url.url`（多为 data URI），content parts 兜底 | 任务结果 `output.results[].url` |
| 覆盖供应商 | OpenAI、火山 Ark Seedream、SiliconFlow、Azure、自定义网关 | OpenRouter（Flux/Gemini image）、`custom_chat` | 阿里云 DashScope（wanx） |

**`OpenAICompatImagegenAdapter`**（`deeptutor/services/imagegen/adapters/openai_compat.py:30`）
- 组装 JSON：`model/prompt/n` 必带，`size/quality/style/response_format` 仅在非空时带上（`deeptutor/services/imagegen/adapters/openai_compat.py:44-52`）；`n` 钳到 `max(1, n)`。
- `_extract_items`（`deeptutor/services/imagegen/adapters/openai_compat.py:71`）强制要求 `data` 数组存在且非空，否则抛 provider 错误。
- `_materialize`（`deeptutor/services/imagegen/adapters/openai_compat.py:79`）：`b64_json` → `decode_base64_media`（`deeptutor/services/imagegen/adapters/openai_compat.py:84`）；`url` → 用同一个 `httpx.AsyncClient` 下载（`deeptutor/services/imagegen/adapters/openai_compat.py:87`），content-type 非 `image/*` 时强制归一为 `image/png`。

**`ChatCompletionsImagegenAdapter`**（`deeptutor/services/imagegen/adapters/chat_completions.py:35`）
- 先发 `modalities: ["image","text"]`；若网关 404 且报文提到 modalit*，降级重发 `modalities: ["image"]`——最后一次响应才是要报的错误（`deeptutor/services/imagegen/adapters/chat_completions.py:61-67`）。
- `_extract_sources`（`deeptutor/services/imagegen/adapters/chat_completions.py:82`）扫 `choices[].message.images[]`，再兜底扫 `message.content` 数组里的 `image_url` parts（只收 `data:image`/`http` 开头，`deeptutor/services/imagegen/adapters/chat_completions.py:95-103`）。
- `_materialize`（`deeptutor/services/imagegen/adapters/chat_completions.py:108`）解析 data URI：从 `header` 提取 content-type，非 `image/*` 直接判错（`deeptutor/services/imagegen/adapters/chat_completions.py:113-116`）；http URL 走下载。
- 没抽到图时报错文案会提示检查模型 output modalities（`deeptutor/services/imagegen/adapters/chat_completions.py:74-78`）——这是排障第一入口。

**`DashScopeImagegenAdapter`**（`deeptutor/services/imagegen/adapters/dashscope.py:29`）
- 提交路径必须是 `services/aigc/text2image/image-synthesis`（`deeptutor/services/imagegen/adapters/dashscope.py:23-26` 注释：去掉 `text2image` 段会落到通用异步路由，所有模型都回 400）。
- 请求头固定加 `X-DashScope-Async: enable`（`deeptutor/services/imagegen/adapters/dashscope.py:60`）；`size` 归一为小写并把 `x` 换成 `*`（`deeptutor/services/imagegen/adapters/dashscope.py:69`）。
- `_task_id`（`deeptutor/services/imagegen/adapters/dashscope.py:86`）+ `_raise_dashscope_error`（`deeptutor/services/imagegen/adapters/dashscope.py:78`，凡 `code` 非空或 `success` 为 False 即抛）；`_poll`（`deeptutor/services/imagegen/adapters/dashscope.py:96`）按 `poll_interval` 轮询，终态集 `succeeded/success` 成功、`failed/canceled/cancelled/expired/unknown` 失败（`deeptutor/services/imagegen/adapters/dashscope.py:115-123`），超过 `poll_timeout` 抛带最后状态的超时（`deeptutor/services/imagegen/adapters/dashscope.py:124-128`）。

## 4. 注册表：加一个供应商要动哪里

`IMAGEGEN_ADAPTERS`（`deeptutor/services/imagegen/adapters/__init__.py:16-22`）是键→单例的字典；`get_imagegen_adapter`（`deeptutor/services/imagegen/adapters/__init__.py:25-29`）对空名回落 `openai_compat`，未知键抛 `GenerationProviderError`。**新增供应商的常规路径不是写适配器**：

1. 网关兼容 OpenAI Images API → 在 `IMAGEGEN_PROVIDERS`（§5）加一个条目，复用 `openai_compat`；
2. 走 chat modalities → 条目里 `adapter="chat_completions"`；
3. 真是新的 HTTP 形态（如另一个异步任务协议）→ 才写第 4 个适配器文件并在 `IMAGEGEN_ADAPTERS` 注册（注释即此意，`deeptutor/services/imagegen/adapters/__init__.py:3-6`）。

注意 `adapters/__init__.py` 的 `__all__` 只导出 `DashScopeImagegenAdapter`，直接 import 另两个类请走各自模块。

## 5. 配置面：provider 目录与解析链

**provider 目录** `IMAGEGEN_PROVIDERS`（`deeptutor/services/config/provider_runtime.py:485-537`）：8 个条目（dashscope、openai、volcengine、siliconflow、openrouter、azure_openai、custom、custom_chat），每条是 `GenerationProviderSpec`（`deeptutor/services/config/provider_runtime.py:464`：label、default_api_base、adapter、auth_style、default_model、is_local）。键→适配器的映射：仅 `dashscope→dashscope`、`openrouter/custom_chat→chat_completions`，其余全落默认 `openai_compat`。别名归一在 `GENERATION_PROVIDER_ALIASES`（`deeptutor/services/config/provider_runtime.py:559`）+ `_canonical_generation_provider`（`deeptutor/services/config/provider_runtime.py:573`）。

**解析链** `resolve_imagegen_runtime_config(catalog=None, *, service=None)`（`deeptutor/services/config/provider_runtime.py:1317-1355`）：
1. `_load_catalog` + `_active_profile_and_model(…, "imagegen")` 取激活 profile/model；
2. model 无 `model` 字符串 → `ValueError`，文案指向 Settings > Media Generation > Image Generation（`deeptutor/services/config/provider_runtime.py:1327-1331`）——这是"未配置"的规范错误，工具层靠捕获它回失败文案；
3. profile 的 `binding` 归一成 provider 键，`base_url/api_key/api_version/extra_headers` 缺省回落 spec；本地 provider 无 key 时填占位 `sk-no-key-required`（`deeptutor/services/config/provider_runtime.py:1339-1340`）；
4. `size/quality/style/response_format` 取自 **model 条目**（非 profile），model 条目的默认空值在目录加载时补齐（`deeptutor/services/config/model_catalog.py:558-563`）。

**Settings UI 面**（同一目录驱动三处）：
- provider 下拉数据：`deeptutor/api/routers/settings.py:725-733`（排序后的 value/label/base_url/default_model）与 `deeptutor/api/routers/settings.py:804`（原始 spec 表）。
- `imagegen` 是 `SERVICE_NAMES`/`CONNECTABLE_SERVICES` 成员（`deeptutor/services/config/model_catalog.py:151,161`）——配置、连接继承、草稿提升等目录机制对它与 llm/tts 完全同构，机制细节不在本文展开。
- 能力探测：`deeptutor/services/settings/provider_probe.py:68` 按厂商 metadata（outputs 含 `image` / kinds 含 `IG`）判定某 host 支持 imagegen，`deeptutor/services/settings/provider_probe.py:83` 归出 `generation` 大类。

## 6. 调用方接线

公共 facade 只有一个：`generate_image(prompt, *, catalog=None, size=None, quality=None, style=None, n=1)`（`deeptutor/services/imagegen/__init__.py:17-44`）。它做四件事：trim prompt（空抛错，`deeptutor/services/imagegen/__init__.py:34-35`）→ 解析 Config（`catalog` 参数允许调用方注入目录快照，默认读全局服务）→ 用本次调用的 `size/quality/style` 覆盖目录默认（`deeptutor/services/imagegen/__init__.py:37-42`）→ `get_imagegen_adapter` 派发。全部调用方：

| 调用方 | 位置 | 用法 |
|---|---|---|
| 聊天工具 `ImagegenTool` | `deeptutor/tools/media_gen_tool.py:135`，执行体 `deeptutor/tools/media_gen_tool.py:176-206` | `prompt/size/n`（n 钳 1-4），字节写入工作区后以 artifacts 返回；工具注册、开关与挂载门禁见 `docs/guides/tools-surface.md`（`drop_unconfigured_generation_tools` 在 `deeptutor/agents/_shared/tool_runtime.py:20`，无激活模型时整个工具被摘除） |
| 设置页"测试" | `deeptutor/services/config/test_runner.py:568` `_test_imagegen`（分发 `deeptutor/services/config/test_runner.py:137-138`） | 注入 UI 当前目录快照 `catalog=catalog`，生成一张测试图并以 base64 回显 |
| 设置页"预览" | `deeptutor/services/settings/service_preview.py:120-124` | 白名单校验在 `deeptutor/services/settings/service_preview.py:32`；同样注入目录快照 |
| 前端 trace | `deeptutor/agents/loop/pipeline.py:1461` | `imagegen/videogen` 工具调用渲染为 `call_kind="media_generation"`（事件链细节见 `docs/guides/events-and-progress-chain.md`） |

产品侧配套：就绪检查把 `imagegen` 标为 "Image generation"（`deeptutor/services/config/readiness.py:142,153,195`）；工具产物落盘目录约定见 `deeptutor/services/path_service.py:200`（`<task>/media/`）。

## 7. 共享 HTTP 基建

三个适配器零私有 HTTP 工具，全部复用 `deeptutor/services/generation_http.py`：`build_auth_headers`（`deeptutor/services/generation_http.py:44`，bearer/`api-key` 头二选一）、`join_api_path`（`deeptutor/services/generation_http.py:57`，base+路径拼接并处理斜杠）、`decode_base64_media`（`deeptutor/services/generation_http.py:28`，统一 b64 解码报错）、`raise_for_provider`（`deeptutor/services/generation_http.py:76`，非 2xx 统一翻成 `GenerationProviderError`）。错误约定：**域内一切失败都抛 `GenerationProviderError`，"未配置"抛 `ValueError`**——两层错误类型是调用方分支的依据（见 `deeptutor/tools/media_gen_tool.py:189-197`）。

## 8. 测试与延伸阅读

- `tests/services/imagegen/test_chat_completions_modalities.py`：chat 适配器的 modalities 降级与图像抽取。
- `tests/services/test_media_gen.py`：工具层（含 `ImagegenTool().execute` 主路径与参数钳制）。
- 相关导读：`docs/guides/tools-surface.md`（工具面全景）、`docs/guides/events-and-progress-chain.md`（进度事件）。`videogen` 是姊妹域（`deeptutor/services/videogen/`，异步任务为主），本文不覆盖。
