# 缺口清单（逐条附 path:line）

行号基于 origin/main @ `6cf793bd8`。严重度：H=数据丢失/不一致，M=行为差异，L=信息类。
安全相关条目只做中性描述，不含复现步骤与利用向量。

## G1 [H·设计] Markdown 导出无对应导入适配器，导出↔导入不成环
- 导出唯一格式是 Markdown：web/lib/chat-export.ts:50-67,77-91。
- 导入只认三种外部源：web/lib/chat-import/detect.ts:21-35（`.claude`/`.codex` 目录）、
  web/lib/chat-import/chatgpt.ts:188,243（conversations.json）。
- 后端白名单同三源：deeptutor/api/routers/imports.py:33。
- 后果：DeepTutor 导出的 `.md` 无法回流；导出内容一旦离开应用，时间戳、metadata、
  分支结构全部不可恢复（与 G8/G9 叠加）。

## G2 [H] codex 图片 turn 静默丢弃，无 `had_images` 标记，与 claude_code 不对齐
- codex `response_item` 仅取 `input_text`/`output_text`：web/lib/chat-import/codex.ts:111-116。
- claude_code 对图片计数并写 `metadata:{had_images:true}`：web/lib/chat-import/claude-code.ts:53-57,73。
- 后果：同一张含图对话，claude_code 导入可读回图片痕迹，codex 导入完全无感。

## G3 [H] chatgpt 图片/dalle parts 静默丢弃，无 metadata 标记
- `partText` 只取字符串 `text`/`content`：web/lib/chat-import/chatgpt.ts:146-151。
- 消息级 metadata 恒不设置：chatgpt.ts:164-180。
- 后果：与 G2 同类；chatgpt 源的图片参与度在导入后零痕迹。

## G4 [M] title 截断上限双端不一致（256 vs 100）
- client 侧 chatgpt 标题截 256：web/lib/chat-import/chatgpt.ts:92,219-220。
- 后端入库再截 100：deeptutor/services/session/sqlite_store.py:2157。
- 后果：101–256 字符的标题被二次截断，用户可见标题与导入预览/源标题不一致。

## G5 [H] 单会话 >10000 条消息静默截断，结果无任何标记
- 上限定义：deeptutor/api/routers/imports.py:36-37；截断执行 :99-100；逐会话结果结构
  `{"external_id", "imported", reason?}`（:95-97,125-127,134）不含截断信息。
- 对比：sessions >1000 会显式 413（:78-82），行为不对称。
- 后果：长会话导入"成功"但尾部永久丢失，无 reason 可查。

## G6 [M·有界] claude 目录名有损还原可碰撞
- `-`→`/` 单向还原：web/lib/chat-import/claude-code.ts:36-40。
- 缓解：仅当头部 64KB 内无任何记录携带 `cwd` 时才使用（:97-99）；且同组会话统一
  groupCwd（:120-121）。
- 后果：极端情况下（全部记录无 cwd 的目录）项目归组可能错并，属已知有损回退。

## G7 [M] codex 混合分层文件整层二选一
- 旧层 `event_msg` 存在即整层采用，`response_item` 全弃：
  web/lib/chat-import/codex.ts:126-130,237。
- 后果：同一 rollout 文件若既有旧层又有新层追加消息，新层消息丢失。

## G8 [H] 导出丢弃 metadata 与逐条时间戳
- `ExportableMessage` 仅 role/content/speaker/capability/attachments：
  web/lib/chat-export.ts:12-19；builder 未消费其余字段 :57-65。
- `had_images`、消息级 `created_at` 在读回端均可用（sqlite_store.py:2479-2480），
  但导出端无承载位。

## G9 [M] 附件导出为纯散文；导入会话附件恒空
- 导出渲染 `_Attachments:_ `name`（mime）`：web/lib/chat-export.ts:34-43，无结构化字段。
- 导入链路 payload 无 attachments 概念（types.ts:68-74；imports.py:40-44），
  入库恒 `'[]'`（sqlite_store.py:2174）。
- 后果：附件信息跨导出/导入均为不可逆文本。

## G10 [L·设计] chatgpt 仅取 active 分支
- current_node 优先，缺省取最新叶子，兄弟分支全弃：
  web/lib/chat-import/chatgpt.ts:105-126,128-144,206-208。
- claude_code 的 `isSidechain` 子代理分支同样全弃（claude-code.ts:62）。
- 属有意取舍，但矩阵上"分支"维度三源均为 ✘，导出端亦无分支概念。

## G11 [M] scan 预读标题与全量解析标题可漂移
- claude：scan 仅读头部 64KB（claude-code.ts:24,94-102），`ai-title` 记录落在 64KB 之外时
  列表标题与导入后标题不同（parse 全量读 :151-152,167）。
- codex 同构：codex.ts:27,176-186 vs :245。
- 后果：选择列表与最终会话标题不一致的用户困惑。

## G12 [L·保真] 导出正文原样嵌入，Markdown 结构可能重叠
- 正文 `msg.content` 原样拼入（chat-export.ts:62-65）；仅 speaker 标题做了单行净化
  （:28-31）。正文若含 `## `/`---` 等结构串，会与导出文档自身的标题/分隔线视觉混叠，
  属格式保真注意项（本地文件下载，无注入面；不留利用细节）。

## G13 [L] 消息时间戳缺省回退会话时间
- 三源客户端在 0/缺失时直接省略 `created_at`：claude-code.ts:72、codex.ts:58,123、
  chatgpt.ts:178。
- 入库回退会话 `created_at`：sqlite_store.py:2182。
- 后果：无时间戳的消息获得会话级时间，逐条时间线可能与源不完全一致。

## G14 [L] 非 user/assistant 角色在导出统一渲染为 "System"
- roleHeading 兜底：web/lib/chat-export.ts:21-25；partners 导出侧还先过滤只剩
  user/assistant/system（web/app/(workspace)/partners/[partnerId]/page.tsx:314-322）。
- 后果：tool/event 等角色区分在导出中塌缩。

## G15 [L] 导出头部时间为导出时刻而非会话时间
- `_Exported: <now>_`：web/lib/chat-export.ts:55-56；会话真实 `created_at/updated_at`
  不进入导出文档。

## G16 [L] chatgpt 导入会话不参与 agent 归属
- `readImportMeta` 只认 claude_code/codex：web/lib/chat-import/attribution.ts:28。
- 后端 agent 元数据本身与来源无关（imports.py:108-111），但 UI 归属层排除了 chatgpt。
- 现状一致（chatgpt 导入入口 imports-api.ts 也未传 agent），列为矩阵事实。
