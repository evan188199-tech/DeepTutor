# 格式 × 方向 × 字段矩阵

行号基于 origin/main @ `6cf793bd8`。标注：✔ 保留/支持；✘ 丢弃/不支持；◐ 部分或有条件。

## A. 格式 × 方向（覆盖面）

| 格式 | 导出（写） | 导入（读） | 往返能力 |
| --- | --- | --- | --- |
| DeepTutor Markdown `.md` | ✔ `buildChatMarkdown` web/lib/chat-export.ts:50-67；`downloadChatMarkdown` :77-91 | ✘ 无 Markdown 适配器（detect.ts:21-35 只认 `.claude`/`.codex` 目录；chatgpt.ts:188,243 只认 conversations.json） | 单向：导出后无法再导入（G1） |
| Claude Code `.jsonl`（目录 `~/.claude/projects/<cwd>/<uuid>.jsonl`） | ✘ | ✔ claude-code.ts:77-134（scan）、:136-173（parse） | 外部→应用，单向 |
| Codex `.jsonl`（`~/.codex/sessions/YYYY/MM/DD/`） | ✘ | ✔ codex.ts:166-207（scan）、:209-251（parse） | 外部→应用，单向 |
| ChatGPT `conversations.json` | ✘ | ✔ chatgpt.ts:188-241（parse）、:243-257（文件入口） | 外部→应用，单向 |
| 来源白名单一致性 | — | web `ImportSource` 三值（types.ts:10）= 后端 `_ALLOWED_SOURCES`（imports.py:33）；归一化 lower（imports.py:65-71） | ✔ 对齐 |

## B. 导入侧：源 × 字段（外部格式 → NormalizedSession）

NormalizedSession 形状定义于 web/lib/chat-import/types.ts:77-85；NormalizedMessage :68-74。

| 字段 | claude_code | codex | chatgpt |
| --- | --- | --- | --- |
| `external_id` | 文件名去 `.jsonl`（claude-code.ts:105） | `session_meta.id`，否则文件名（codex.ts:184） | `id` 或 `conversation_id`，截 256（chatgpt.ts:78,92） |
| `title` | `ai-title` → 头部 64KB 预读 title → 首条派生（claude-code.ts:167；预读 :24,94-107） | 头部 64KB 预读 title → 首条派生；无 ai-title 层（codex.ts:245；预读 :27,176-186） | 导出 title 截 256 → 首条派生 → `"Imported conversation"`（chatgpt.ts:219-222） |
| `source_cwd` | 记录 `cwd` → 否则目录名有损还原 `-`→`/`（claude-code.ts:97-99,38-40） | `session_meta.cwd` → `"(unknown)"`（codex.ts:181,227） | 恒 `""`（chatgpt.ts:223） |
| `created_at`/`updated_at` | 首/末条消息时间戳，缺省回退文件 mtime（claude-code.ts:161-164） | 同左（codex.ts:239-242） | 会话 create/update → 消息时间 → 文件 mtime（chatgpt.ts:211-216,256）；s/ms 自适应 :44-51 |
| `messages[].role` | user/assistant，其余丢弃（claude-code.ts:63-64） | user/assistant（codex.ts:51-54,106-108） | user/assistant（chatgpt.ts:168-169） |
| `messages[].content` | 仅 `text` block，`\n` 连接；tool_use/tool_result/thinking 丢弃（claude-code.ts:53-57）；`<system-reminder>` 剥离（shared.ts:14-18） | 旧层 `event_msg` 整层优先，否则 `response_item` 仅 `input_text`/`output_text`（codex.ts:111-116,126-130,237）；仅 markup 的 harness 注入 turn 丢弃（:88-101,121） | `content.parts` 文本，隐藏类型与 visually-hidden 行丢弃（chatgpt.ts:26-32,153-162,171）；仅取 active 分支（:128-144,206-208） |
| `messages[].created_at` | 记录 ISO→epoch s，0 则省略（claude-code.ts:68,72） | 行时间戳，0 则省略（codex.ts:57-58,122-123） | 消息 `create_time`，0 则省略（chatgpt.ts:174,178） |
| `messages[].metadata` | 图片出现过 → `{had_images:true}`（claude-code.ts:73）；其余无 | ✘ 恒无——图片 parts 静默丢弃无标记（codex.ts:111-116）（G2） | ✘ 恒无——图片/dalle parts 静默丢弃（chatgpt.ts:146-151）（G3） |
| 图片本体 | ✘ 丢弃（仅计数标记） | ✘ 静默 | ✘ 静默 |
| 分支/子代理 | `isSidechain`/`isMeta` 行丢弃（claude-code.ts:62） | `thread_source:"subagent"` 会话整跳（codex.ts:180,238） | 非 active 分支全弃（设计取舍，G10） |
| 多说话人 speaker | ✘ 无此概念 | ✘ | ✘ |
| 空内容消息 | 丢弃（claude-code.ts:67） | 丢弃（codex.ts:55-56,117-118） | 丢弃（chatgpt.ts:172-173） |

## C. 上传封装 ↔ 后端模型（字段奇偶）

client `NormalizedSession`/`NormalizedMessage`（types.ts:68-85，POST body 见 imports-api.ts:30-38）
vs 后端 Pydantic（imports.py:40-71）：

| 字段 | client | backend | 判定 |
| --- | --- | --- | --- |
| `source` | 三值联合 types.ts:10 | 白名单+lower imports.py:33,65-71 | ✔ |
| `agent_id`/`agent_name` | 缺省发 `""`（imports-api.ts:36-37） | 默认 `""`（imports.py:61-62），非空才入库 `import` 元数据（:108-111） | ✔ |
| `external_id` | string | `min_length=1, max_length=256`（imports.py:48）；超限 422 | ✔（chatgpt 已截 256，claude/codex 为 uuid） |
| `title` | string | `""` 默认（imports.py:49）；入库再截 100（sqlite_store.py:2157） | ◐ 双端截断不一致（G4） |
| `source_cwd` | string | `""` 默认（imports.py:50） | ✔ |
| `created_at`/`updated_at` | 必填 number | 必填 float（imports.py:51-52） | ✔ |
| `messages[].role` | `"user"\|"assistant"`（types.ts:69） | `pattern="^(user\|assistant)$"`（imports.py:41） | ✔ |
| `messages[].content` | string | `""` 默认（imports.py:42） | ✔ |
| `messages[].created_at` | 可选 number（types.ts:72） | `float\|None`（imports.py:43） | ✔ |
| `messages[].metadata` | 可选 Record（types.ts:73） | `dict[str,Any]`（imports.py:44） | ✔ |
| 请求上限 | 分批 ≤1000/批（imports-api.ts:53-76） | >1000 sessions→413（imports.py:78-82）；>10000 messages 静默截断（:99-100）（G5） | ◐ |
| 空内容消息 | — | 入库前再过滤一次（imports.py:92） | ✔ 双保险 |
| 幂等 | 声称重导安全（imports-api.ts:48-52） | 按 `imported_<src>_<ext>` id 去重，已存在仅回填 agent 元数据（imports.py:102；sqlite_store.py:134-143,2132-2146） | ✔ |

## D. 持久化 → 读回 → 导出（应用内往返）

| 字段 | 入库（_import_session_sync） | 读回（_serialize_message） | 导出（buildChatMarkdown） |
| --- | --- | --- | --- |
| role | 原样，缺省 `"user"`（sqlite_store.py:2178） | ✔ :2474 | ✔ 标题行；非 user/assistant 一律渲染 `"System"`（chat-export.ts:21-25）（G14） |
| content | 原样 :2179 | ✔ :2475 | ✔ 原样嵌入正文（chat-export.ts:62-63）（G12 结构保真注意项） |
| capability | 恒 `''`（sqlite_store.py:2174）——导入消息无此字段 | ✔ :2476（空） | 有则渲染 ` _(cap)_` 后缀（chat-export.ts:60）；导入会话永远为空 |
| events | 恒 `'[]'`（:2174） | ✔ :2477 | ✘ 不导出 |
| attachments | 恒 `'[]'`（:2174）——导入 payload 无 attachments 字段 | ✔ :2478（空） | 有则仅渲染名称+mime 散文行（chat-export.ts:34-43），无结构（G9） |
| metadata | 存 `msg.metadata`（:2181） | ✔ :2479（`had_images` 等可读回） | ✘ 不导出（G8） |
| created_at | 消息级；0/缺省回退会话 `created_at`（:2182）（G13） | ✔ :2480 | ✘ 不导出（G8） |
| parent_message_id | 导入链式父指针（:2183-2184,2186-2187） | ✔ :2481 | ✘ 分支信息不导出 |
| title | 截 100 或 `"Imported conversation"`（:2157） | 会话级 | `# <title>` 头（chat-export.ts:54,56）；文件名净化 60 字符（:69-75） |
| `import` 元数据（source/external_id/agent_*） | 存 `preferences.import`（imports.py:103-112） | 经 session summary preferences 读回（attribution.ts:19-34；chatgpt 来源不计入 agent 归属 :28） | ✘ 不导出 |
| 导出头部时间 | — | — | 恒当前时间，非会话时间（chat-export.ts:55-56）（G15） |
| 空消息数组 | — | — | `downloadChatMarkdown` 直接 return（chat-export.ts:81） |
