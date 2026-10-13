# 语音 provider 提供面与适配器实现面的漂移矩阵（2026-10-13）

- 基线：HKUDS/DeepTutor `origin/main` @ `6cf793bd8`（v1.6.14），只读扫描，未改任何代码。
- 方法：静态读取 provider 注册表与两处前端可见性判定，并用只读 import 将 `PROVIDERS` × `TTS_PROVIDERS` × `STT_PROVIDERS` 做了交叉计算（矩阵数值直接来自代码中的表，非人工抄写）。
- 去重：上游 issue #1951（Gemini 单点，OPEN，尚无关联 PR）。本卡只做全量矩阵，不复述其复现细节，也不实现修复。

## 1. 结论摘要

"可见但不可用"不止 Gemini 一例。按漂移成因分四类：

| 类别 | 覆盖的连接类型 | 成因 |
|---|---|---|
| D1 无适配器、回退 custom 后必然失败 | gemini、anthropic、custom_anthropic、minimax_anthropic、deepseek、zhipu、moonshot、mistral、stepfun、qianfan、nvidia_nim、edenai、aihubmix、novita、atlascloud、unifically、cheaperinference、api_route、requesty、futureinfra、opper、y_api、byteplus、byteplus_coding_plan、volcengine_coding_plan、openai_codex、github_copilot、codebuddy、ollama、lm_studio、llama_cpp、lemonade、ovms（共 33 个） | 语音绑定不在语音 provider 表里，解析回退为 `custom`（OpenAI 兼容 `POST {base}/audio/speech`），而这些连接的默认 base URL 都不是 OpenAI 兼容音频端点 |
| D2 名称错位 + 凭据域错配 | volcengine（LLM Ark 连接） | 语音表键是 `volcengine_speech`，LLM 注册表键是 `volcengine`；UI 判定不认（不支持组），运行时别名却把 Ark 连接悄悄重路由到语音适配器（需要 Speech API key，Ark key 无效） |
| D3 TTS 有、STT 无 | minimax、xiaomi_mimo | 两家只在 `TTS_PROVIDERS` 有条目；STT 下拉不列出，勾选"Not on record"后回退 custom 也无可用的转写端点 |
| D4 兜底勾选框放大暴露面 | 全部未声明连接（含 OAuth 与本地 runtime） | 语音"添加模型"面板的 custom 勾选框把所有未声明来源一次性放进下拉，语音服务并无"未知但能工作"的路径，等于批量展示必然失败的入口 |

核心矛盾：同一个连接名有三套匹配语义——UI 可见性用精确名匹配（`_connection_targets`、`providerServiceSupport`），运行时解析却带别名（`_canonical_voice_provider`），前两者不认识后者认识的别名（`volcengine`），于是出现"UI 显示不支持、运行时却换了个凭据域继续跑"的行为。

## 2. 语音入口的五个界面 + 一条解析链

| # | 界面 | 数据来源 | 代码位点 |
|---|---|---|---|
| S1 | 添加连接面板的 voice 筛选 chip | `GET /api/settings` 的 `connection_targets`（每个 LLM provider 挂了哪些服务） | `deeptutor/api/routers/settings.py:781-845`（`_connection_targets`），`web/components/settings/AddProviderPanel.tsx:93-94` |
| S2 | 连接详情的 "Voice" 快捷入口 | `providerServiceSupport(source, 'tts'/'stt')` | `web/components/settings/ProvidersWorkspace.tsx:405-416` |
| S3 | 语音页"添加模型"的 provider 下拉（支持组 / Not on record 组） | `providerServiceSupport` + custom 勾选框 | `web/components/settings/ModelsWorkspace.tsx:116-121, 427-433, 474-480`，分组渲染 `:375-401` |
| S4 | 连接列表"添加 provider"的选项与语音 chip | 全部服务表（llm∪tts∪stt∪…）并集 | `web/components/settings/ProvidersWorkspace.tsx:90-100` |
| S5 | 语音 profile 编辑器的 provider 下拉 | `GET /api/settings` 的 `providers.tts/stt`（即两张语音表原样） | `deeptutor/api/routers/settings.py:607-759`（tts 列表 `:698-711`，stt `:712-724`，入口 `:919-920`），`web/components/settings/ServiceConfigEditor.tsx:1561-1641` |
| R1 | 运行时绑定解析 | `_canonical_voice_provider`（别名 + custom 兜底） | `deeptutor/services/config/provider_runtime.py:457-460`，TTS `:1240-1242`，STT `:1294-1296`，别名表 `:445-454` |

UI 判定链（S2/S3 共用，`web/lib/provider-registry.ts:167-180`）：以下任一成立才进"支持组"——
1. `connection_targets` 里该 vendor 声明了该服务（`_match_service_provider` 精确键匹配，`deeptutor/api/routers/settings.py:762-778`；`VoiceProviderSpec` 没有 `keywords` 字段，`deeptutor/services/config/provider_runtime.py:299-318`，所以语音表实际只能精确匹配）；
2. `providers.tts/stt` 下拉里存在同名条目；
3. 该连接本身就是该服务（语音连接不适用）；
4. discovery 元数据检出该能力（`deeptutor/services/settings/provider_probe.py:62-63, 74-85`，模型元数据带 audio 输出/`TTS` 能力位才算）。

否则只能在勾选 custom 后从"Not on record — verify with the model test"组选（`ModelsWorkspace.tsx:433`；`managed_by` 托管连接被排除，`:120`）。

运行时解析链（R1）：绑定名 → 小写/连字符归一 → 别名表（`volcengine/doubao→volcengine_speech`、`aliyun/bailian→dashscope`、`azure/aoai→azure_openai`、`openai_compatible→custom`、`lmstudio→vllm`）→ 不在表内一律回退 `custom`；`custom` 的 TTS 适配器就是 `POST {base}/audio/speech`（`deeptutor/services/voice/adapters/openai_compat.py:113-118`，无 URL 时报 "No endpoint URL configured for TTS."）。

适配器全集：`deeptutor/services/voice/adapters/__init__.py:24-38`。TTS 六个（`mimo_tts/minimax/volcengine/openai_compat/openrouter_tts/dashscope`），STT 三个（`volcengine/openai_compat/dashscope`）。该文件头注释（`:3-9`）明确写着 "add bespoke providers (DashScope native, ElevenLabs, **Gemini**, Deepgram) by registering new keys here" —— Gemini 是已知缺口而非疏漏被遗忘。

## 3. 全量矩阵

"语音 chip"= S1/S4 是否把该 vendor 标为支持语音；"添加模型下拉"= S3 中的位置。可见性数值由实际表交叉计算得出（脚本见 §6）。

### 3a. 有具名适配器、UI 也在"支持组"（可用，9 + custom）

| 连接类型 | OAuth | 语音 chip | 添加模型下拉 | TTS 解析（适配器/默认 base） | STT 解析 | 预期结果 | 建议 |
|---|---|---|---|---|---|---|---|
| openai | 否 | ✓ | 支持组 | `openai_compat` / api.openai.com/v1 | `openai_compat` | 可用 | 维持 |
| openrouter | 否 | ✓ | 支持组 | `openrouter_tts`（/audio/speech 失败后回退 chat audio 输出） | `openai_compat`（base64-JSON） | 可用 | 维持；这也是 #1951 里的现行绕行方案 |
| groq | 否 | ✓ | 支持组 | `openai_compat` / api.groq.com/openai/v1 | `openai_compat` | 可用 | 维持 |
| siliconflow | 否 | ✓ | 支持组 | `openai_compat` / api.siliconflow.cn/v1 | `openai_compat` | 可用 | 维持 |
| azure_openai | 否 | ✓ | 支持组 | `openai_compat`（api-key 头），base 留空须自填 | 同左 | 可用（须填 base_url + 部署名） | 维持 |
| vllm | 否 | ✓ | 支持组 | `openai_compat` / localhost:8000/v1 | `openai_compat` | 可用（部署需提供 /v1/audio/* 路由） | 维持 |
| dashscope | 否 | ✓ | 支持组 | `dashscope` 原生适配器 / dashscope.aliyuncs.com/api/v1 | `dashscope`（Paraformer WebSocket，仅接受 `paraformer-realtime-*`，见 `provider_runtime.py:395-403` 注释） | 可用 | 维持 |
| minimax | 否 | ✓ | 支持组 | `minimax` 原生适配器 / api.minimax.io/v1 | **无 STT 条目** → 回退 custom | TTS 可用；STT 回 D3 | STT 侧隐藏或补适配器 |
| xiaomi_mimo | 否 | ✓ | 支持组 | `mimo_tts` / api.xiaomimimo.com/v1 | **无 STT 条目** → 回退 custom | TTS 可用；STT 回 D3 | STT 侧隐藏或补适配器 |
| custom（Custom/OpenAI API 连接） | 否 | ✓ | 支持组 | `openai_compat`，端点由用户给出 | `openai_compat` | 可用（前提是端点真的兼容） | 维持 |

语音专属连接（无 LLM 角色）：`volcengine_speech` 连接在 S4 的并集选项里可添加，`providers.tts/stt` 有同名条目 → 进支持组，`providerAdapter` 取 `exact.value` 命中 `volcengine_speech`（`web/lib/provider-registry.ts:181-201`），原生 TTS/STT 适配器齐备（`deeptutor/services/voice/adapters/__init__.py:24-38`）。可用，但注意 `_connection_targets` 只遍历 LLM 注册表（`settings.py:809`），语音专属 vendor 在 S1 永远没有 target 行，全靠表名兜住。

### 3b. D1 类：UI 仍可见（勾选后）但解析到 custom、默认配置必然失败（33 个）

统一证据：绑定不在语音表 → `provider_runtime.py:457-460` 回退 `custom` → `openai_compat.py:113-118` 拼 `{base}/audio/speech`；这些 vendor 的连接默认 base（各自注册表条目，`deeptutor/services/provider_registry.py:194-650`）没有任何一个指向 OpenAI 兼容音频端点。UI 侧：S1 无语音 chip（`_match_service_provider` 精确键不中），S3 落"Not on record"组（`provider-registry.ts:167-180` 三条已知路径全不中）。

| 连接类型 | 位置 | 预期 TTS/STT 结果 | 建议 |
|---|---|---|---|
| gemini | provider_registry.py:464-471 | 失败（上游 #1951 已实测 502/404；Gemini TTS 只走原生 generateContent，无适配器） | 补原生适配器（#1951 首选方案），单独开卡；未修前按下行隐藏 |
| anthropic（backend=anthropic） | :400-413 | 失败（Messages 协议无音频合成路由，适配器层无 anthropic 语音实现） | 隐藏 |
| custom_anthropic / minimax_anthropic（legacy） | :202-210, :529-537 | 失败（同上；legacy 条目仅存量目录可见，ServiceConfigEditor 下拉已过滤 legacy，`ServiceConfigEditor.tsx:1615-1620`） | 隐藏 |
| deepseek、zhipu、moonshot、mistral、stepfun、qianfan、nvidia_nim | :453-463, :472-480, :490-512, :538-553, :546-553, :642-649, :622-633 | 无具名适配器；回退 custom 后能否工作取决于 vendor 默认 base 是否提供 /audio/speech（本仓库无任何适配证据），默认配置不应承诺可用 | 隐藏；vendor 真提供 OpenAI 兼容音频路由时让用户走 custom 连接 |
| edenai、aihubmix、novita、atlascloud、unifically、cheaperinference、api_route、requesty、futureinfra、opper、y_api（网关） | :232-353 | 网关是否代理 /audio/speech 因家而异；DeepTutor 只给 openrouter 一等 TTS 适配器，其余网关全部裸回退 custom，无任何按网关的提示 | 网关统一按"仅 LLM"对待语音入口，或在 UI 标注需网关支持 |
| byteplus、byteplus_coding_plan、volcengine_coding_plan | :376-398, :365-375 | Ark 兼容 chat 端点，无 /audio/speech（火山语音在 openspeech.bytedance.com 另一域另一协议）；coding plan 亦无 | 隐藏 |
| openai_codex、github_copilot、codebuddy | :423-452 | OAuth，`_connection_targets` 直接跳过（`settings.py:811-813`）；后端均为聊天协议，无音频路由 | 隐藏（custom 勾选框路径也应挡住 OAuth 连接） |
| ollama、lm_studio、llama_cpp、lemonade、ovms（本地） | :562-620 | 本地推理服务均无 /audio/speech 路由 → 404；只有 vLLM 有且已具名 | 隐藏；用户确有本地 TTS 服务时用 custom 连接指过去 |

### 3c. D2 类：名称错位 + 凭据域错配（1 个，最隐蔽）

| 连接类型 | UI 表现 | 运行时行为 | 建议 |
|---|---|---|---|
| volcengine（Ark LLM 连接） | S1/S3 均判不支持（表键 `volcengine_speech` ≠ `volcengine`，且 `VoiceProviderSpec` 无 keywords 可供匹配，`provider_runtime.py:299-318`） | 勾选后可选中；`_canonical_voice_provider` 别名 `volcengine→volcengine_speech`（`provider_runtime.py:446`）把它接到火山语音适配器，而该适配器要 Speech API key，Ark key 认证必失败；UI 仅在模型字段处有一句 key 提示（`web/components/settings/VoiceModelFields.tsx:161-164`） | 三选一：给 `_connection_targets` 补显式映射让 UI 与别名一致；或在语音服务屏蔽 Ark 连接；至少把别名重路由改为"仅当连接确有 Speech 凭据" |

同族小问题：别名表里 `"lmstudio": "vllm"`（`provider_runtime.py:453`）永远匹配不上——归一化只把 `-` 换 `_`，LLM 注册表键是 `lm_studio`，别名键却是无下划线的 `lmstudio`，成了死别名。

### 3d. D4 类：兜底勾选框放大暴露面

`ModelsWorkspace.tsx:433`：勾选 custom 复选框后 `visible` 放行**所有**未声明来源（仅 `managed_by` 托管连接除外，`:120`），包括 OAuth（codebuddy 等）和本地 runtime。LLM 页这样做有道理（OpenAI 兼容网关五花八门，测一下就知道了）；语音没有"未知但能工作"的空间——协议只有 OpenAI 兼容与四个原生适配器，不在表内即必败。建议语音服务（tts/stt）不提供该勾选框，或把"Not on record"组在语音页替换为一句"此连接类型暂不支持语音"。

## 4. 与 UI 可见性的交叉验证口径

- S1/S4 的 voice chip 数据（`connection_targets`）与 S3 支持组（`providerServiceSupport`）口径一致（都精确匹配），因此不会出现"chip 有、下拉没有"的错位；错位发生在"下拉支持组 vs 运行时别名"（D2）和"勾选后可见 vs 必败"（D1/D3/D4）。
- discovery 元数据路径（`provider_probe.py:62-63`）目前只对模型元数据里带 audio 输出位/`TTS` 能力位的 vendor 生效；一旦某网关在 /models 元数据里带上 `output_modalities: ["audio"]`，其连接会直接进 S3 支持组——而适配器面并不随之变化。这是把"模型能力"当"协议能力"的第二个漂移源，建议 `providerServiceSupport` 对 tts/stt 只信任前两条路径 + 具名适配器表。

## 5. 建议汇总（按性价比排序，均未实施）

1. 语音添加模型面板按 `connection_targets`/语音表收紧（去掉 custom 勾选框在 tts/stt 的放行）——一行过滤即可消除 D1/D3/D4 的绝大部分暴露面。
2. 处理 `volcengine` 别名错配（D2）：UI 与运行时择一对齐。
3. gemini 原生 TTS 适配器 → 上游 #1951（单独开卡，本卡不实现）。
4. 修正 `lmstudio` 死别名或删除。
5. 长期：`providerServiceSupport` 对语音只信具名适配器表，不把模型能力元数据当协议能力。

## 6. 复核方式

矩阵中的可见性/解析列由以下只读脚本对 `6cf793bd8` 的实际表计算（对每行输出：LLM 绑定名 → TTS/STT 精确匹配键、解析键、适配器、默认 base），与本报告 §3a/§3b/§3c 逐行对应：

```python
# 只读：加载表并复算 _match_service_provider 与 _canonical_voice_provider
from deeptutor.services.config.provider_runtime import (
    TTS_PROVIDERS, STT_PROVIDERS, _canonical_voice_provider)
from deeptutor.services.provider_registry import PROVIDERS

def match(name, table):
    if name in table:
        return name
    for n, spec in table.items():          # VoiceProviderSpec 无 keywords，循环恒不中
        if name in getattr(spec, "keywords", ()):
            return n
    return None

for spec in PROVIDERS:
    tk, sk = match(spec.name, TTS_PROVIDERS), match(spec.name, STT_PROVIDERS)
    tres = tk or _canonical_voice_provider(spec.name, TTS_PROVIDERS)
    sres = sk or _canonical_voice_provider(spec.name, STT_PROVIDERS)
    print(spec.name, spec.is_oauth,
          "tts:", tk or "->", tres, TTS_PROVIDERS[tres].adapter or "openai_compat",
          "| stt:", sk or "->", sres, STT_PROVIDERS[sres].adapter or "openai_compat")
```

预期输出的关键行：`gemini … tts: -> custom openai_compat`（D1）、`volcengine … tts: -> volcengine volcengine`（D2：精确匹配 miss 但别名命中）、`minimax … tts: minimax minimax | stt: -> custom openai_compat`（D3）。
