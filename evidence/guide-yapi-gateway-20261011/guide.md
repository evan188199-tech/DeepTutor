# Y-API 网关接入面导读（运维者视角）

> 范围：Y-API 作为 OpenAI 兼容网关在 DeepTutor 的接入面——配置项、鉴权头、模型映射、失败回退与设置界面开关。Y-API 的凭据获取、计费与模型清单以网关方文档为准，本文不覆盖。
> 基线：`origin/main` @ 6cf793bd8（v1.6.14，#1791 已合入）。所有 `path:line` 以该提交为准。
> 本文不改任何代码与文档源文件；证据目录只新增本文件与 SHA256SUMS。

## 0. 去重说明

- `guide-llm-providers-20261004`（evidence/guide-llm-providers-20261004/guide.md）讲的是 provider_core 全家族的生命周期与装配机制，是"总览"。本文不重复其内部机制，只讲 Y-API 这一行网关在接入面上的可操作事实，机制处直接引用总览结论。
- `guide-embedding` 系列讲 embedding 供应商。Y-API 只注册在 LLM 侧：`EMBEDDING_PROVIDERS`（`deeptutor/services/config/provider_runtime.py:167`）中没有 `y_api`，embedding 服务不能选 Y-API。

## 1. 结构：Y-API 在接入面的位置

#1791 的全部产品代码是 `provider_registry.py` 里的一条 `ProviderSpec`（`deeptutor/services/provider_registry.py:343-353`）加两条别名（`provider_registry.py:159-160`）；其余接入能力全部由既有网关机制派生。Y-API 没有专属 provider 类、专属路由或专属环境变量读取点（全仓库 `Y_API_KEY` 只出现在 spec 的 `env_key` 字段）。

```
设置界面下拉（settings.py:620-651, 由 PROVIDERS 派生）
        │  binding = "y_api"
        ▼
resolve_llm_runtime_config（provider_runtime.py:835-944）
  ├─ 显式 binding 优先（provider_runtime.py:793-806）
  ├─ base_url 含 "y-api" 时网关探测兜底（find_gateway, provider_registry.py:851-865）
  └─ base_url 为空 → default_api_base_for(api_format)（provider_runtime.py:921-922）
        ▼
provider_factory._build_runtime_provider（provider_factory.py:55-135）
  ├─ api_format ∈ {auto, openai_chat, openai_responses} → OpenAICompatProvider（provider_factory.py:116-128）
  └─ api_format = "anthropic" → AnthropicProvider（effective_backend 改判, provider_registry.py:751-762;
                                              provider_factory.py:106-115）
        ▼
Agentic 运行时同构路径（runtime/agentic/client.py:144-146, 302-312）
```

与相邻网关行的差异只有两点：`api_base_by_format` 声明了 Anthropic Messages 端点（`provider_registry.py:352`，MiniMax 同款做法，见 `provider_registry.py:526`）；`detect_by_base_keyword="y-api"` 让手填 base_url 的 profile 自动归到 Y-API（`provider_registry.py:350,863-864`）。

## 2. 配置项逐项说明

### 2.1 ProviderSpec 字段（代码侧，不可由用户改）

| 字段 | 值 | 位置 | 取值说明 |
| --- | --- | --- | --- |
| `name` | `y_api` | provider_registry.py:344 | 规范名，catalog `binding`/`provider` 字段应写它；后端据此路由 |
| `keywords` | `("y_api","y-api","yapi")` | provider_registry.py:345 | 供 `find_by_model` 匹配模型名关键词；但网关条目被 `find_by_model` 跳过（provider_registry.py:772），实际主要靠 `find_by_name`/别名命中 |
| `env_key` | `Y_API_KEY` | provider_registry.py:346 | profile 的 key 会被同步到该环境变量（见 §4.4）；**没有反向读取**：catalog 解析不消费 `Y_API_KEY` 环境变量，key 必须写在 profile 里 |
| `display_name` | `Y-API` | provider_registry.py:347 | 下拉与状态显示名（settings.py:629 经 `s.label`） |
| `backend` | `openai_compat` | provider_registry.py:348 | 默认走 OpenAI SDK；`api_format="anthropic"` 时被 `effective_backend` 改判为 `anthropic`（provider_registry.py:760-761） |
| `is_gateway` | `True` | provider_registry.py:349 | `mode="gateway"`（provider_registry.py:77-78）；参与网关探测与"池内已配置网关优先"回退（provider_runtime.py:817-822） |
| `detect_by_base_keyword` | `y-api` | provider_registry.py:350 | base_url 子串匹配（provider_registry.py:863-864）；`binding=openai` + base 含 `y-api` 会被改判为 y_api（provider_runtime.py:799-802） |
| `default_api_base` | `https://api.y-api.bestvirtualgoods.com/v1` | provider_registry.py:351 | OpenAI 系协议的默认端点（`/v1` 结尾，含 `/chat/completions`、`/models`） |
| `api_base_by_format` | `(("anthropic", "https://api.y-api.bestvirtualgoods.com"),)` | provider_registry.py:352 | Anthropic Messages 端点为**根地址**（SDK 自己追加 `/v1/messages`）；`default_api_base_for` 按格式取值（provider_registry.py:121-123） |
| `strip_model_prefix` | 默认 `False` | provider_registry.py:42 | 模型 id 原样透传，不剥 `vendor/model` 前缀 |
| `legacy_of` | 未设置 | provider_registry.py:69 | 非遗留条目，下拉状态 `supported`（settings.py:646） |

派生行为（由上表决定，运维需知晓）：

- `api_formats`：OpenAI 三格式 + `anthropic`——因为 `api_base_by_format` 声明了 anthropic（provider_registry.py:97-115，判定在 113-114）。UI 的协议选择器据此出现。
- `default_api_format`：`auto`（provider_registry.py:118-119）。
- `supports_wire_api_selection`：`True`（backend=openai_compat 且非 OAuth，provider_registry.py:88-90），profile 可显式选 `wire_api`。
- 原生工具：`y_api` 在"已注册云 openai_compat 网关启用原生 tools"名单里（tests/core/test_agentic_client_provider_kwargs.py:601）。

### 2.2 别名

- 后端：`"y-api" → y_api`、`"yapi" → y_api`（provider_registry.py:159-160）；`canonical_provider_name` 做 strip + snake 化后查表（provider_registry.py:164-172）。手写 profile 文件里 `binding: "Y-API"` / `"yapi"` 都能解析。
- 前端展示层同名镜像：web/lib/provider-branding.ts:67-69。仅影响显示，不影响解析。

### 2.3 Profile（catalog 侧，用户可配）

| 字段 | Y-API 取值 | 说明 |
| --- | --- | --- |
| `binding` | `y_api`（或别名） | 显式指定优先级最高（provider_runtime.py:793-806）；留空时靠 base_url 探测（§4.1） |
| `base_url` | 留空 = 按协议取默认；openai 系填 `.../v1` 结尾；anthropic 填根地址 | 留空时运行时按 `default_api_base_for(api_format)` 回填（provider_runtime.py:921-922）；设置界面切换协议时按 `base_urls[api_format]` 预填（web/components/settings/ProvidersWorkspace.tsx:108-110，映射来自 settings.py:638-642） |
| `api_key` | 网关签发的 key | 必填（网关无"无密钥"豁免，见 §4.4）；支持逗号分隔多 key 走轮换（§4.3） |
| `api_format` | `auto`（默认）/ `openai_chat` / `openai_responses` / `anthropic` | 决定 wire 协议与端点（§4.2）；写入非本供应商支持的值会被钳回（provider_registry.py:710-727） |
| `wire_api` | 仅旧字段；已被 `api_format` 取代 | 旧 profile 用 `api_format_from_legacy` 折算（provider_runtime.py:907-908，provider_registry.py:730-743） |
| `extra_headers` | JSON 对象，一般留空 | 透传为 SDK default_headers / probe 追加头（provider_factory.py:113,123；provider_probe.py:236）；值必须全是字符串（settings.py:1969-1970） |
| `api_version` | 留空 | 仅 Azure 语义，Y-API 不消费 |

## 3. 模型映射

- 模型 id 原样发往网关：`strip_model_prefix=False`（§2.1），`deepseek/deepseek-v4-flash` 这类带厂商前缀的 id 是网关侧的目录名，DeepTutor 不改写（tests/services/config/test_provider_runtime.py:458-487 断言 `resolved.model` 逐字透传）。
- 供应商识别不按模型名走：`find_by_model` 跳过网关条目（provider_registry.py:772），所以即使模型 id 含 `deepseek`，只要 binding/base 指向 y_api，就仍由 y_api 承接；但模型自身的厂商约束仍生效——`model_overrides_for` 会按模型 id 查它的"原生厂商 spec"（provider_registry.py:816-848），例如 kimi 家族模型经 y_api 调用也会被去掉显式 temperature。
- `/models` 发现：设置界面"获取模型"与"测试连接"都会向 `<base>/models` 发 GET（provider_probe.py:105，先剥掉 `/chat/completions` 等误粘后缀，provider_probe.py:219-233）；鉴权头按协议切换（§4.2）。Y-API 需要在网关侧开放 OpenAI 风格 `/v1/models`。
- 上下文窗口探测的鉴权头用的是 `build_auth_headers(key, binding)`（deeptutor/services/config/context_window_detection.py:134），binding=`y_api` 不在 anthropic 分支 → Bearer（deeptutor/services/llm/utils.py:342-349）。若 profile 用 anthropic 协议，该探测头与推理头不一致，属已知差异，见错配 #7。

## 4. 鉴权、协议与失败回退

### 4.1 供应商怎么被定成 y_api

`_choose_resolved_provider`（provider_runtime.py:785-832）顺序：显式 binding →（binding=openai 且探测命中网关时让位给网关，799-802）→ base_url/key 网关探测（794-798）→ 模型名（808-810）→ 本地地址（812-815）→ 池内已配置的网关/本地/标准供应商（817-830）→ openai 兜底（832）。服务层工厂 `_resolve_provider_spec` 同序（deeptutor/services/llm/factory.py:81-111）。运维含义：**base_url 里含 `y-api` 子串的任何 profile 都会被算进 Y-API**，包括你想配成 generic openai 的场景。

### 4.2 鉴权头（按 api_format 二选一）

- OpenAI 系（auto/openai_chat/openai_responses）：`Authorization: Bearer <key>`。由 AsyncOpenAI SDK 注入；多 key 轮换时逐请求覆写该头（deeptutor/services/llm/provider_core/openai_compat_provider.py:237-239）。
- anthropic：`x-api-key: <key>` + `anthropic-version` 头，由 AsyncAnthropic SDK 注入（deeptutor/services/llm/provider_core/anthropic_provider.py:57-59），`extra_headers` 并入 default_headers（anthropic_provider.py:70-71）。
- `/models` 探测同规则：`_auth_binding` 按 `effective_backend` 判定，anthropic 格式一律 x-api-key（deeptutor/services/llm/cloud_provider.py:57-62 → provider_probe.py:234 → utils.py:343-345）。
- base_url 规整：anthropic 侧末尾 `/v1` 会被剥掉再交给 SDK 追加路径（anthropic_provider.py:60-69）；openai 系不做任何规整，**必须自带 `/v1`**。

### 4.3 失败回退（运维可观察的三层）

1. **瞬态重试**：HTTP {408,429,500,502,503,504} 与错误文本命中瞬态标记时按 1/2/4 秒退避重试（deeptutor/services/llm/provider_core/base.py:76,90,317-332）。401/403/404 属非瞬态，**不重试、立即报错**。
2. **多 key 轮换**：api_key 为列表时构造 KeyPool，仅在 429 时记 strike 换下一把，预算 max(2, len(pool)) 次（openai_compat_provider.py:186,230-249；deeptutor/services/keypool.py:9-53）。401 不会换 key。
3. **Responses → Chat 回落**：`api_format=openai_responses` 时，端点 400/404/422 连续 2 次失败熔断 300 秒、期间直接走 Chat Completions（openai_compat_provider.py:74-75,494-536）。Y-API 默认 `auto` 不走此路径；只有显式选了 `openai_responses` 才可能触发。

无模型级自动 fallback 链：Y-API 上的模型失败不会自动切别的供应商，重试耗尽后错误原样上抛（base.py:384-437）。

### 4.4 环境变量同步

provider 构造时（configure_env=True，池内实例默认开）把 profile 的主 key 写入 `Y_API_KEY`：网关模式是**覆写**（openai_compat_provider.py:257-258），非网关才是 setdefault（259-260）。`build_isolated_provider` 与 agentic 一次性调用不写环境变量（provider_factory.py:138-140）。运维含义：进程内 `Y_API_KEY` 环境变量会被活跃 profile 的 key 覆盖，不要依赖它做长期配置。

## 5. 设置界面开关（web）

- 下拉项：`GET /settings` 的 provider choices 中 `llm[]` 含 `{value:"y_api", label:"Y-API", base_url, auth_mode:"api_key", api_formats:[auto,openai_chat,openai_responses,anthropic], base_urls:{...v1, anthropic:根}, status:"supported"}`（deeptutor/api/routers/settings.py:607-651；断言 tests/api/test_settings_router.py:708-712）。
- 协议选择器：LLM 服务的 profile 编辑页在 `api_formats` 非空时渲染协议切换（web/components/settings/ProvidersWorkspace.tsx:332-333）；切协议即改 `base_urls[api_format]` 预填的 base_url（ProvidersWorkspace.tsx:108-110；类型 web/lib/model-catalog-types.ts:259,261）。
- 高级项：`api_version` 与 `extra_headers (JSON)`（ProvidersWorkspace.tsx:340-355）；Y-API 的 api_version 留空。
- 测试连接：`POST /settings/test-provider` 按"草稿优先"解析掩码 key 后探测（settings.py:1940-1985），UI 入口把当前 api_format 一并传入（ProvidersWorkspace.tsx:366-372）。探测只验证 `/models` 可达与 recognized listing，不等于推理/计费可用（provider_probe.py:200-205）。
- 品牌图标：`y_api` 无认证品牌资产，走通用占位图标（web/lib/provider-branding.ts:4-65 无 y_api 条目；web/tests/provider-branding.spec.ts:22-23），属预期而非缺陷。
- 保存/生效：编辑先进草稿，`POST /settings/apply` 才落到运行时（settings.py:1906-1937）；改完 key 后 provider 池按缓存键（含 key 指纹）自动换代（provider_factory.py:22-52,151-177）。

## 6. 运维接入清单（5 分钟路径）

1. 设置 → 供应商 → 添加 → 选 "Y-API"；key 粘贴；base_url 留空（或 `https://api.y-api.bestvirtualgoods.com/v1`）。
2. 协议保持 `auto`；仅当要用 Claude 家族走 Messages 端点时切 `anthropic`（base_url 会自动换成根地址）。
3. 点"测试连接"：期望 recognized `/models` 列表。401 → key 错/未生效；404 → base_url 路径错（见错配 #1/#6）。
4. "获取模型"拉清单，选模型保存 → 应用（apply）。
5. 冒烟：发起一次对话；若走 anthropic 协议失败，先核对网关侧是否开通 Messages 端点（错配 #3）。

## 7. 常见错配清单（症状 + 定位步骤）

**#1 openai 系协议下 base_url 丢了 `/v1`**
症状：对话报 404，URL 形如 `https://api.y-api.bestvirtualgoods.com/chat/completions`；"测试连接"同样 404。
定位：查 profile `base_url` 是否为根地址。openai 系不做路径规整（§4.2），必须 `/v1` 结尾；恢复方法：清空 base_url 让默认值回填（provider_runtime.py:921-922），或手填完整 `/v1` 地址。

**#2 key 未配 / 占位符未还原**
症状：对话报 401/403（非瞬态，不重试，§4.3-1）；日志可见请求以 `no-key` 发出（openai_compat_provider.py:213）。与 openai 不同，y_api 不会在构造期抛"未配置"错误（openai_compat_provider.py:201-210 仅对 provider_name=="openai" 生效），问题只在调用期暴露。
定位：设置页 key 框是否为掩码；`POST /settings/test-provider` 若返回 "Saved credentials were not found"（settings.py:1971-1978）说明草稿里只有掩码没有真 key，重新输入并 apply。

**#3 切了 `anthropic` 协议但网关侧没开通 Messages 端点 / key 无对应权限**
症状：404 `<host>/v1/messages` 或 401（此时鉴权头已是 x-api-key 而非 Bearer，§4.2）。
定位：先在 `auto` 协议下探测确认 key 有效；再单独探测 anthropic 格式（test-provider 会按格式切头，cloud_provider.py:57-62）。若网关未开 Messages，回到 openai 系协议 + 网关的 OpenAI 模型 id。

**#4 把推理端点当 base_url（粘成 `.../v1/chat/completions`）**
症状："测试连接"竟然通过（probe 会剥掉 `/chat/completions` 后缀再探 `/models`，provider_probe.py:219-233），但真实对话 404 `<base>/chat/completions/chat/completions`。
定位：对比 profile base_url 与 §2.1 默认值；规则：base_url 一律填到 `/v1` 为止，不含动作路径。

**#5 `binding: openai` + base_url 含 `y-api`，以为在走通用 OpenAI**
症状：运行时 `provider_name=y_api, mode=gateway`（provider_runtime.py:799-802 的改判），行为与预期 openai 直连不同：base_url 为空时端点被回填成 Y-API 默认地址，环境变量写的是 `Y_API_KEY` 而非 `OPENAI_API_KEY`（§4.4）。
定位：看 `resolve_llm_runtime_config` 输出（或状态接口）的 provider_name/provider_mode；确认这是预期改判而非 bug；要直连就换一个不含 `y-api` 的中转地址或显式 binding。

**#6 `extra_headers` JSON 非法或塞入非字符串值**
症状：test-provider 直接 400 "Invalid extra headers JSON." / "Extra headers must contain text values."（settings.py:1963-1970），保存流程卡在探测。
定位：高级设置里检查 JSON；只放字符串键值。无特殊需要请清空——Y-API 靠标准鉴权头即可。

**#7 多 key 列表里第一把 key 失效（401）**
症状：持续 401，轮换不发生（KeyPool 只在 429 时换，§4.3-2）。
定位：把 key 列表拆开逐把探测；确认失效 key 是被网关吊销（401）还是限流（429——后者会自动轮换）。

**#8 旧 profile 只有 `wire_api: responses` 且网关不支持 /responses**
症状：前两次请求 404/400 后自动恢复走 Chat Completions；日志出现 responses 熔断（§4.3-3）。
定位：这是设计内回落（openai_compat_provider.py:494-536）；要消除告警就把 `api_format` 显式设为 `openai_chat`。

## 8. 验证

只读运行了 #1791 自带的回归用例（venv: /Users/Shared/DeepTutor/.venv，Python 3.13.13，工作树 guide/yapi-gateway-20261011 @ 6cf793bd8）：

```
pytest -q -p no:cacheprovider \
  tests/services/config/test_provider_runtime.py::test_llm_y_api_binding_uses_default_openai_compatible_endpoint \
  tests/services/config/test_provider_runtime.py::test_llm_y_api_base_url_detection_preserves_openai_binding_compatibility \
  tests/api/test_settings_router.py::test_llm_provider_choices_include_y_api \
  tests/core/test_agentic_client_provider_kwargs.py::test_registered_cloud_openai_compat_providers_enable_native_tools
→ 4 passed
```

未启动任何服务器/守护进程；未改动任何源文件。
