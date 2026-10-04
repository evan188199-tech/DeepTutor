# 用户可见错误消息一致性扫描报告

- 日期：2026-10-04
- 分支：`scan/error-messages-20261004`（基于 origin/main @ f07029cfc "release: v1.6.13"）
- 只读扫描，未改任何代码。
- 范围：`deeptutor/api/routers/` 全部 44 个文件、`deeptutor/services/` 用户路径（routers 经 `str(e)` 透传或 WS/SSE 直接下发到用户的异常）、`web/` 错误态（lib 错误提取层、组件错误横幅/toast、locales）。

## 分型定义

| 类型 | 含义 |
|---|---|
| RAW-EXC | 用户可见 detail/message 是裸异常文本（`str(e)`、f-string 内嵌 `{e}`、`error_msg` 等），可能带出内部路径、供应商原始报文、类名 |
| EXC-NAME | 异常类名/repr/堆栈出现在用户可见文本（`{type(exc).__name__}`、pydantic ValidationError 全文、`traceback`） |
| LANG-MIX | 单条消息中英混排；或硬编码中文/英文绕过既有 i18n 通道（后端 `t()`、前端 locale 文件） |
| NO-CODE | HTTPException 只有自由文本 detail，无机器可读错误码（仓库已有 `{"code","message"}` 先例：book.py:61、space_mcp.py:89） |
| INCONSISTENT | 同一错误语义（not_found / conflict / rate-limit / 网络失败等）在不同文件话术、大小写、句号风格不一致 |
| VAGUE | "Failed to X" / "Something went wrong" 等无原因、无下一步指引 |

## 总量

| 层 | 扫描点 | RAW-EXC | EXC-NAME | LANG-MIX | NO-CODE | VAGUE |
|---|---|---|---|---|---|---|
| routers（44 文件） | ~871 处 HTTPException / ~945 处 raise | ~134 处强透传（其中 73 高危：62 处 blanket-500 + 5 处 format_exception_message + 4 pydantic + 2 WS/SSE），另有 ~90 处受控透传 | 10 | 2 显式 + 系统性（15 个文件不用 `t()`） | ~597 处纯文本 detail（占 ~75%） | 18 |
| services（用户路径） | ~880 处 raise | ~60 处上游放大器（路径/供应商报文内嵌进异常消息，被 routers 原样透传） | 15 | 0（raise 站点无中文，全部为刻意的 LLM 提示词） | — | 7 |
| web | ~250 文件 | 253 处 UI 直接渲染 `error.message`/`.detail` + 5 处 lib 级提取器 | — | ~10 条硬编码中文 + ~40 条双语 helper 绕过 locale + 4 条 API client 英文串无任何 locale key | — | ~30 |
| locales | en/zh/de/fr/pl/uk | fr 缺 466 key（含 26 个错误相关），pl/uk 缺 common.json | | | | |

结论：四类问题都存在且量大；最集中的根因有 3 个 —— ① blanket `except Exception → 500 detail=str(e)`；② `format_exception_message()`（deeptutor/utils/error_utils.py）不做脱敏、原样透传供应商报文；③ 前端 `shared/api/client.ts` 把后端 detail 原样塞进 `AppError.message` 供 250+ 调用点直接展示。

## Top 15（按用户影响排序）

| # | 位置 | 类型 | 问题 | 建议话术/修法 |
|---|---|---|---|---|
| 1 | deeptutor/api/routers/knowledge.py:1403 | EXC-NAME（堆栈） | `/knowledge-bases/health` 响应体直接带 `"traceback": traceback.format_exc()` + 裸 str(e)，任何用户可读完整服务端堆栈 | 堆栈只进服务端日志；响应只返回 `{"status":"error","reason":"health_check_failed"}` |
| 2 | book.py:834,864,900,926,952,997,1066,1096,1367,1415,1437,1458 + co_writer.py:546,561,597,609,626,643,716,728,797,806,817,839,857,874 + knowledge.py:1427…4690（共 62 处） | RAW-EXC | blanket `except Exception → 500 detail=str(e)`，供应商 JSON、内部路径、pydantic 文本全量到达用户 | 统一异常处理器：日志记录 exc，返回 `{"code":"internal_error","message":"This action failed. Please retry; contact support if it persists."}`（in-repo 典范：knowledge.py:2723-2729 IMA 段） |
| 3 | web/shared/api/client.ts:59-72,101,217 | RAW-EXC | `messageFromBody` 把后端 detail 原样放入 `AppError.message`，被 ~250 个 UI 调用点直接 toast/横幅展示 | 在此单点做 error_code→`t()` 文案映射（`lib/book-errors.ts` CODE_MESSAGES 已是现成模式），原始 detail 进 console |
| 4 | deeptutor/services/session/turns/executor.py:1349 | RAW-EXC | 聊天流错误事件 `content=str(exc)`：LLMAPIError 携带的供应商 URL、request id 直接进用户对话 | 映射为"AI 服务暂时不可用，请稍后重试（错误码 {code}）"，原始文本只进日志 |
| 5 | deeptutor/services/partners/runtime.py:623→417 | EXC-NAME | 伙伴回复失败时 `f"Sorry, the turn failed: {errors[-1]}"`，其中 errors 元素是 `f"{type(exc).__name__}: {exc}"`，用户看到 "ValueError: …" | "Sorry, the reply failed. Please try again." + 单独 code 字段 |
| 6 | deeptutor/services/generation_http.py:82；services/voice/adapters/dashscope.py:44、openai_compat.py:60-72；services/search/providers/*（serply:84、firecrawl:91、jina:88、doubao:94、zhipu:94、qianfan:92、aliyun_iqs:108、bocha:79） | RAW-EXC | `resp.text[:400]` 供应商响应体拼进异常消息并透传给用户（供应商报错体常含密钥回显/内部地址） | 只保留 HTTP 状态码："Speech synthesis failed (HTTP {code}). Check the provider settings." |
| 7 | deeptutor/utils/error_utils.py:46 `format_exception_message` | RAW-EXC（机制） | 名为 format 实为 pass-through：仅对标准 OpenAI JSON 信封做表面整理，其余原样返回；被 question.py:320、knowledge.py:3423/4171/4220（直接进 500 detail）、quiz_judge.py:450（WS 下发）消费 | 在此函数加白名单/脱敏/长度截断/兜底文案，单点收敛 #2/#6 的泄漏 |
| 8 | book.py:857,888；mastery_path.py:80,89 | EXC-NAME | `f"Invalid proposal: {exc}"` pydantic ValidationError 全文（含内部字段路径）给用户 | "The edited proposal is invalid — check chapter titles and source references." |
| 9 | deeptutor/services/llm/error_mapping.py:170 | RAW-EXC | `LLMAPIError(str(exc))` 供应商 SDK 消息（URL、request id）逐字进入用户流 | "The AI provider returned an error ({code}). Try again." |
| 10 | deeptutor/api/routers/notebook.py:206,223,248,272,303,327,362,397,425,441,457,477 | RAW-EXC | 笔记本全部写路径 ×12 blanket-500 `str(e)` | "The notebook service hit an unexpected error. Please retry." |
| 11 | reading_extensions.py:157,205,369,490 | RAW-EXC | PermissionError str → 403 detail，内含服务端绝对路径 | "You don't have access to this material." |
| 12 | practice.py:338；question.py:197,223,187,320 | RAW-EXC | OSError/KeyError/BadZipFile str → 422（路径/key 泄漏）；WS 端 FileNotFoundError 路径、`format_exception_message(e)` 供应商原文下发 | "That file is not a valid practice import package." / "That attachment could not be loaded." |
| 13 | routers 全体（t() 仅 5 个文件在用：partners/personas/mcp_settings/space_cli_apps/space_mcp） | LANG-MIX | 后端错误消息基本全英文硬编码；中文用户在任何语言下都收到英文错误。反向：web/lib/tool-availability.ts:26,27,40,41,52 硬编码中文（"未配置"/"缺少凭证"/"暂不可用"）对全部语言展示；useTopicSourceLibrary.ts 等 8 文件 ~40 条私有 `(cn,en)` helper 绕过 locale | 后端：把高频 detail 收进 `deeptutor/services/i18n.py` 目录并用 `t()`；前端：进 locale 文件 |
| 14 | routers ~597 处纯文本 detail（如 auth.py:828 "Incorrect email or password" vs :846 "Incorrect username or password"、sessions.py ×9 "Session not found"） | NO-CODE | 无机器可读 code，前端只能整串匹配或裸显；登录失败两种文案 UI 无法区分 | 系统性补 `{"code","message"}`（book.py:61、space_mcp.py:89 已有先例），前端按 code 映射 |
| 15 | not_found 语义：routers+services 合计 15+ 种写法（"Session not found"×12、"reading session not found"、"reading workspace {id!r} not found"、"Notebook not found"、"Record not found"、"Entry not found"、"unknown run_id"、"KB '{x}' not found" vs "Knowledge base '{x}' not found"…）；web 网络失败 4 种话术（"Unable to reach the server" / "Could not reach the server" / t("Couldn't reach the server…")（唯一有翻译）/ command-delivery.ts:3）；限流 5 种句式；句号风格混用（marginnote4 全带句号+位置参数，其余不带） | INCONSISTENT | 同类错误话术分裂，翻译与前端匹配都受影响 | 统一模板：`"{Entity} '{id}' not found."`；网络失败/限流各收敛为一条 key |

## 分层明细

### routers A–K（agent_config…mastery_path，15 文件，~416 HTTPException）

| 文件 | HTTPExc | raise | RAW-EXC | EXC-NAME | LANG-MIX | NO-CODE | VAGUE |
|---|---|---|---|---|---|---|---|
| agent_config.py | 0 | 0 | 0 | 0 | 0 | 0 | 0（注意 :58 `{"error":…}` 配 HTTP 200） |
| attachments.py | 2 | 2 | 0 | 0 | 0 | 2 | 0 |
| auth.py | 63 | 78 | 5（受控） | 0 | 0 | 57 | 2 |
| book.py | 62 | 67 | 23（12 blanket-500 + 1 WS） | 2 | 0 | 29 | 1 |
| capabilities.py | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| capabilities_settings.py | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| co_writer.py | 31 | 33 | 20（14 blanket-500 + 2 SSE） | 0 | 2 | 11 | 0 |
| courses.py | 16 | 16 | 4（受控） | 0 | 0 | 10 | 0 |
| dashboard.py | 4 | 4 | 0 | 0 | 0 | 4 | 0 |
| file_library.py | 7 | 7 | 0 | 0 | 0 | 7 | 0 |
| file_preview.py | 22 | 22 | 5（受控） | 0 | 0 | 17 | 0 |
| imports.py | 2 | 3 | 1（受控） | 0 | 0 | 2 | 0 |
| knowledge.py | ~160 | 176 | 67（36 blanket-500 + 5 fmt-exc） | 0 | 0 | ~68 | 4 |
| marginnote4.py | 5 | 5 | 0 | 0 | 0 | 5 | 1 |
| mastery_path.py | 37 | 38 | 9 | 2 | 0 | 27 | 0 |

高优先级条目（`path:line | 类型 | 证据 | 建议话术`）：

- book.py:834 等 12 处 blanket-500（create/confirm/compile/regenerate/insert/deep-dive/supplement/resume/pause/rebuild）| RAW-EXC | `raise HTTPException(500, detail=str(exc))` | "Something went wrong while updating this book. Please try again."
- book.py:1806 | RAW-EXC | WS `{"type":"error","content": str(exc)}` | "This book action failed. Please reopen the book and retry."
- co_writer.py:546 等 14 处 blanket-500 | RAW-EXC | 同上模式 | "The edit action failed. Please retry; contact support if it keeps failing."
- co_writer.py:500,503 | RAW-EXC | SSE `error_holder["detail"]=str(exc.detail)/str(exc)` | "The AI edit failed before completion. Please retry."
- co_writer.py:303,312 | LANG-MIX | 硬编码中文 detail（"请输入编辑要求…"），language 条件分支而非 `t()` | 进 i18n 目录
- knowledge.py:535,612 | RAW-EXC | `f"Validation failed for file '{x}': {format_exception_message(e)}"` | "File 'x' was rejected: unsupported type or too large."
- knowledge.py:3424,4171,4220 | RAW-EXC | `detail=format_exception_message(e)` 直进 500 | "Re-indexing failed. Check the knowledge base status and try again."
- knowledge.py:2960 | RAW-EXC | `f"Failed to list knowledge bases: {e!s}"` | "Could not load your knowledge bases. Please refresh."
- knowledge.py:2870 | RAW-EXC | `f"Failed to load knowledge bases. Errors: {'; '.join(errors)}"` | "Some knowledge bases could not be loaded."
- knowledge.py:2646 | RAW-EXC | `detail=result.get("answer") or "Kiwix search failed."`（answer 可为上游异常文本） | "Search in this archive failed. Try a different query."
- knowledge.py:2278,2386,2426 | RAW-EXC | `detail=result.error or …`（result.error 为内部异常文本） | "This folder can't be linked: its index is missing or unreadable."
- knowledge.py:2185…2722（13 处）| RAW-EXC | 400 `str(e)`（路径/名称校验 ValueError 带路径） | "That path or name is not allowed on this server."
- auth.py:525,705,1420,1508,1555 | RAW-EXC（受控） | 自定义异常 str 透传（WorkspaceError/PermissionError/ValueError） | 保留语义但建议换结构化 code
- auth.py:828 vs 846 | INCONSISTENT | "Incorrect email or password" vs "Incorrect username or password"（同登录门两套文案，UI 无法区分） | 统一 "Incorrect email or password" + code
- auth.py:57 处 NO-CODE 代表：:453 "Not authenticated"、:461 "Invalid or expired token"、:1272 等 8 处 "User not found"
- file_preview.py:47,51,54 | INCONSISTENT | "Conflicting workspace scopes"（此处无句号，auth.py:481 有句号） | 统一
- file_library.py:102,115,142,156,168 vs :119,145 | INCONSISTENT | "File not found" vs "File not found on disk" | 统一 + code 区分
- courses.py:172 | INCONSISTENT | "Unknown resource kind" 丢值（knowledge 同类消息带值） | `f"Unknown resource kind: {kind}"`
- marginnote4.py 全部 5 处 | INCONSISTENT | 位置参数 `HTTPException(404,"…")` + 全带句号，与其余文件风格相反 | 统一关键字风格
- marginnote4.py:161 | VAGUE+内部术语 | "MN4 device sync is not available … pairing and sync would resolve different workspaces." | "Device sync isn't available for this account yet."
- mastery_path.py:80,89 | EXC-NAME | pydantic `exc.errors()` 全文给用户 | "Module {i} is invalid — check its title and knowledge points."
- dashboard.py:138,155 vs :215 | INCONSISTENT | "Unknown source library" vs "Unknown learning library" | 统一
- 正面典范：knowledge.py:2723-2729（IMA 段：日志记类名、用户拿通用 500 文案）——建议推广为全仓模式。

### routers L–Z（mcp_settings…workspace，29 文件，~455 HTTPException + ~25 WS/SSE）

零用户可见 raise：tools.py、_partners_channel_schema.py（question.py/quiz_judge.py/unified_ws.py 无 raise 但经 WS 发错误）。

| 文件 | HTTPExc | raise | RAW-EXC | EXC-NAME | NO-CODE | VAGUE |
|---|---|---|---|---|---|---|
| mcp_settings.py | 6 | 6 | 2 | 0 | 6 | 0 |
| memory.py | 22 | 22 | 3 | 0 | 22 | 0 |
| multi_user.py | 24 | 32 | 2 | 0 | 24 | 1 |
| notebook.py | 21 | 33 | 13 | 0 | 18 | 0 |
| outputs.py | 2 | 2 | 0 | 0 | 2 | 0 |
| partner_groups.py | 22 | 22 | 9（7 在 WS） | 0 | 22 | 4 |
| partners.py | 75 | 76 | 3 | 5 | ~64 | 1 |
| personas.py | 9 | 9 | 5（受控） | 0 | 9 | 0 |
| practice.py | 13 | 13 | 10（1 强） | 0 | 13 | 0 |
| question.py | 0 | 0 | 4（WS） | 0 | n/a | 0 |
| question_notebook.py | 18 | 21 | 1 | 0 | 18 | 2 |
| quiz_judge.py | 0 | 0 | 1（WS） | 0 | n/a | 0 |
| reading.py | 12 | 73 | 1 强 +~10 受控 | 0 | 15 | 0 |
| reading_extensions.py | 25 | 26 | 6 | 1 | 23 | 0 |
| sessions.py | 27 | 27 | 3（受控） | 0 | 27 | 1 |
| settings.py | 17 | 25 | 3 强 +6 轻 | 0 | 16 | 0 |
| skills.py | 31 | 31 | 4 | 0 | 31 | 0 |
| space_cli_apps.py | 4 | 4 | 0 | 0 | 2 | 0 |
| space_mcp.py | 7 | 9 | 1 | 0 | 2 | 0（典范） |
| subagents.py | 11 | 11 | 3 | 0 | 11 | 0 |
| system.py | 10 | 11 | 2 | 0 | 10 | 0 |
| task_board.py | 1 | 1 | 0 | 0 | 1 | 0 |
| tools.py | 0 | 0 | — | — | — | — |
| unified_ws.py | 0 | 0 | 5（WS，均带 error_code，好） | 0 | — | 0 |
| video_learning.py | 3 | 37 | 0 | 0 | ~40 | 1 |
| visualizers.py | 2 | 8 | 2（受控） | 0 | ~9 | 0 |
| voice.py | 7 | 7 | 5 | 0 | 7 | 0 |
| workspace.py | 11 | 12 | 2 强 +7 受控 | 0 | 11 | 0 |
| _partners_channel_schema.py | 0 | 0 | — | — | — | — |

高优先级条目：

- notebook.py:206…477 ×12 | RAW-EXC | blanket-500 `str(e)` | "The notebook service hit an unexpected error. Please retry."
- notebook.py:179 | RAW-EXC | SSE `{"type":"error","detail":str(exc)}` | "Adding to the notebook failed. Please try again."
- partners.py:1047,1137,1200,1229,1233-1241 | EXC-NAME | `f"…({type(exc).__name__})…"` 类名直达用户 | "Channels were saved but listeners could not restart. Stop and start the partner."
- partners.py:174-178 | RAW-EXC | 把内部 `last_reload_error` 文本嵌进用户 detail | "Channels were saved but a listener failed to restart."
- partners.py:373 | RAW-EXC | `f"{t(...)}: {exc}"` TypeError | "The channel configuration format is invalid."
- partners.py:12+ 处 i18n 绕过（:157,180,212,441,443,839,864,1306,1345,1425,1454,1480）| LANG-MIX | 同文件 `t("api.partner_not_found")` 与裸英文混用 | 统一走 `t()`
- personas.py:140,142,154 | LANG-MIX | create 用 `t()`、update 用裸 str(exc)，同一冲突两种形态 | `t("api.persona_already_exists", name=…)`
- mcp_settings.py:73,96,132 | LANG-MIX | 裸 str 与 `t("mcp.*")` 兄弟消息混用 | 包 `t()`
- reading_extensions.py:157,205,369,490 | RAW-EXC | PermissionError str（含路径）→ 403 | "You don't have access to this material."
- reading_extensions.py:174,461 | RAW-EXC | 通用 Exception str → 400/500 | 见建议话术表
- reading_extensions.py:303 | RAW-EXC | `detail["reason"]` 为裸异常文本 | reason 用枚举值（如 `model_unavailable`）
- question.py:197,223 | RAW-EXC | WS `str(e)` 含 FileNotFoundError/PermissionError 路径 | "That attachment could not be loaded."
- question.py:187 | RAW-EXC | `f"Invalid base64 PDF data: {e}"` | "The uploaded PDF data is corrupt. Re-upload the file."
- question.py:320 | RAW-EXC | `format_exception_message(e)`（供应商原文）经 WS 下发 | "Generation failed. Please try again in a moment."
- quiz_judge.py:281 | RAW-EXC | `f"Invalid request: {exc}"` WS | "That grading request was invalid. Reopen the quiz and retry."
- practice.py:338 | RAW-EXC | OSError/KeyError/BadZipFile str → 422 | "That file is not a valid practice import package."
- question_notebook.py:300 | RAW-EXC+语义 | ValueError → 404（状态码错位，应为 400） | 400 + "This answer could not be added to the notebook."
- workspace.py:63,198 | RAW-EXC | OSError str（errno+路径）经 `_data_operation` | "The files are busy. Close open views and retry."
- memory.py:721 | RAW-EXC | OSError str 500（文件系统路径） | "The trace file could not be deleted. Check folder permissions."
- settings.py:2011,2195,2197 | RAW-EXC | 供应商文本/str 透传 | "Could not reach the model provider. Check the base URL and API key, then retry."
- skills.py:97,111 | RAW-EXC | `f"Tag already exists: {exc}"`（异常文本拼接） | "A tag with this name already exists."
- skills.py:175,195,271 | RAW-EXC | HubError str → 502 | "The skill hub is unreachable right now. Try again later."
- subagents.py:135,144,166 | RAW-EXC | 路径守卫 ValueError（含路径）/ blanket-500 str | "That working directory is not permitted."
- system.py:221,290 | RAW-EXC | VersionCheckError str 503（端点 URL） | "Update check is unavailable right now."
- partner_groups.py:258,261,290,294 | VAGUE | "Retry failed"/"Round summary failed"/"ended without a result" | "The round could not be completed. Please retry."
- sessions.py:499 | VAGUE | "Unable to delete conversation" | "This conversation is busy and can't be deleted. Wait for the active turn to finish."
- video_learning.py:542 | VAGUE | "Upstream video stream failed." | "The video source is not responding. Try another quality."
- 正面典范：unified_ws.py 每条 WS 错误都带 error_code；video_learning.py 类型化错误 + 通用 500 兜底；space_mcp.py:89 `{"code","message"}`。

not_found 话术族谱（L–Z 段）："Session not found"（sessions ×9、partners ×3）、"Parent session not found"、"Session not found in recycle bin"、"reading session not found"（小写）、"reading workspace {id!r} not found"、"material {id!r} not found"、"revision {n} not found"、"Snapshot image not found."、"No such image in this material."、"EPUB pairing not found"、"Bookmark not found" vs "annotation not found"（小写）、"Notebook not found" vs "Record not found" vs "Record or target notebook not found"、"Entry not found"×6、"Category not found"、"Link not found"、"unknown run_id"、"entry not found"、"no trace for that day"、"Partner Group not found"、"Partner Group session not found"、"Whiteboard pin not found"、"Partner draft not found"、"Asset not found"、"No such linked account"、"Output not found"、"File not found"、"Task card not found."、"Tag not found: {tag}"、"Skill not found: {name}"、"No connected subagent named {n!r}."、"Question not found"、"Course not found"、"Reading extension not found."、"Reading session not found."。

### services（用户路径，~880 raise）

RAW-EXC-UPSTREAM 最重 20 处（异常消息内嵌路径/报文，被 routers 原样透传）：

| 站点 | 证据 | 建议 |
|---|---|---|
| services/generation_http.py:82 | `resp.text[:400]` 进异常 | 只留状态码 |
| services/voice/adapters/dashscope.py:44 | 同上 | 同上 |
| services/voice/adapters/openai_compat.py:60-72 | `_provider_error_message` 内嵌 body | 同上 |
| services/voice/adapters/openai_compat.py:244 | `str(exc) or exc.__class__.__name__` | 通用文案 |
| services/search/providers/serply.py:84 | `f"Serply API error: {status} - {resp.text}"` | "Web search failed. Try again." |
| services/search/providers/firecrawl.py:91,95 | 原始 payload | 同上 |
| services/search/providers/jina.py:88 | 同上 | 同上 |
| services/search/providers/doubao.py:94,97 | 同上 | 同上 |
| services/search/providers/{zhipu:94,qianfan:92,aliyun_iqs:108,bocha:79} | 同模式 ×4 | 同上 |
| services/search/__init__.py:227 | 拼接全部供应商原始失败文本 | "Web search is unavailable right now." |
| services/rag/pipelines/lightrag_server/client.py:62,75 | `resp.text[:300]` / `{data!r}` | 只留状态码 |
| services/rag/pipelines/weknora/client.py:74,80 | body preview / `{data!r}` | 同上 |
| services/rag/pipelines/lightrag/ingress.py:68,75,84,131,135,317,326,340 等 13 处 | 服务器绝对路径进异常 | 去路径，留"哪个文件未通过检查" |
| services/notebook/service.py:81 | `f"Notebook {id!r} is unreadable ({path}): {cause}"` → 409 payload | "This notebook's file is damaged and can't be opened." |
| services/rag/pipelines/llamaindex/vector_store.py:163 | `f"No existing FAISS index found at {persist_path}"` | "The index is missing. Re-index this knowledge base." |
| services/llm/error_mapping.py:170 | `LLMAPIError(str(exc))` SDK 原文（URL/request id） | 映射 + code |
| services/llm/provider_core/openai_responses/parsing.py:451,664 | 供应商 event 原文 500 字符 | 截断为 code + 通用文案 |
| services/parsing/service.py:120；parsing/cache.py:78 | 服务器路径 | 去路径 |
| services/skill/hub.py:534,559,717-720 | hub 响应体 + 内部设置键名 | "The skill hub is unreachable (HTTP {code})." |
| services/partners/channel_onboarding.py:251 | `f"Invalid merged channels config: {exc}"` | "The channel configuration is invalid." |

另有 ~35 处路径内嵌 raise（rag/pipelines ingress/sidecar、eval/dataset.py:170-187 等）。

EXC-NAME 全部 15 处：partners/runtime.py:623（→:417 用户回复）、partners/manager.py:1396、:978（docstring 注明"for the UI"）、partners/workspace.py:177、mcp/manager.py:472,460（对比 :949 有 URL 脱敏）、sandbox/backends.py:120,396、sandbox/runner/server.py:258,352、cron/executor.py:101、cron/service.py:374、session/legacy_migration.py:205、rag/eval/runner.py:215、voice/adapters/openai_compat.py:244。

VAGUE 7 处：task_board.py:112,119（裸 KeyError → str 是引号 id）、courses.py:340,388,433 等（CourseNotFoundError str 只有裸 id，成为 404 detail 全文）、session/organization.py:38（裸 LookupError(parent_session_id)）、practice/storage.py:260、memory/store.py:313,316、subagent/hermes_remote_client.py:25-30（机器码当消息）。

INCONSISTENT 五大簇：
1. 会话/伙伴 not found：`Session not found: {id}`（sqlite_store/pocketbase_store）vs `Conversation not found in this workspace.`（request_preparer:173）vs `Partner not found`（weixin_onboarding/channel_onboarding/i18n）。
2. 忙/冲突：`Session already has an active turn: {turn_id}` vs `already has an active or recovering turn` vs `This conversation is already replying. Please wait.`（partners/manager.py:100,1299）vs `mastery_path_busy: path … is already active` vs 裸码 `regenerate_busy`。
3. 限流：`execution rate limit reached ({n}/min)`（sandbox/quota.py:47）vs `too many concurrent executions (max {n})`（:72）vs `Rate limit exceeded`（llm/exceptions.py:116）vs `IMA rate limit reached.`（envelope.py:71）vs `IMA rate limit reached. Try again shortly.`（transport.py:97 —— 同一管道两种）。
4. 超时：`timed out after {t}s`（videogen/imagegen/mineru）vs `stream stalled for more than {t} seconds`（llm 2 家）vs `Audio conversion timed out.` vs `{Provider} TTS connection failed or timed out.` vs 裸 `VoiceProviderTimeout()`。
5. 供应商 HTTP 失败：`…failed with HTTP {code}: {body}` vs `WeKnora returned {code}` vs `…API error: {code} - {text}`（8 家搜索）——`generation_http.raise_for_provider` 已存在但无人复用。

LANG-MIX：0（services raise 站点无中文；所有中文均为刻意 LLM 提示词或 i18n 目录）。

`format_exception_message` 结论：**不脱敏**。仅当消息含可解析 OpenAI 风格 JSON 信封时重排 Message/Type/Code，其余一律原样返回；不截断、不脱 URL/凭据、无兜底。它被 question.py:320,528,571、knowledge.py:533,610,3423,4171,4220、quiz_judge.py:450 用于用户路径，属泄漏放大器；建议在此单点加白名单/脱敏/长度上限/兜底文案。

### web（错误态）

最重 20 处 RAW-EXC-DISPLAY：

| 位置 | 证据 | 建议 |
|---|---|---|
| shared/api/client.ts:217 | `if (body?.detail) detail = String(body.detail)` | code→t() 映射层 |
| shared/api/client.ts:59-72,101 | `messageFromBody` 原样进 `AppError.message`，~250 调用点直接展示 | 同上 |
| lib/auth.ts:106,108,156 | 登录表单裸 detail；"Could not reach the server"/"Login failed" 无 locale key | t() + code |
| app/(workspace)/whisper/page.tsx:93 | 流错误 `event.content ?? "Something went wrong."` 直接作为聊天系统消息 | 映射 code |
| lib/book-errors.ts:28 | 仅映射 3 个 code，其余 fallback `error.message` | 扩 CODE_MESSAGES |
| learning/books/BooksRoute.tsx:257,745,780,923 | 裸文本插进本地化模板 `t('Could not save your edit: {{message}}')` —— 中文 UI 出现中英混排句子 | code 映射 |
| features/knowledge/components/engines/EngineDetail.tsx（15 处）| `err instanceof Error ? err.message : String(err)` | 引擎错误统一 mapper |
| components/knowledge/KnowledgePage.tsx（11 处）| 上传/删除/重建 KB → `setError(err.message)` 横幅 | code 映射 |
| features/chat/components/ChatWorkspace.tsx:316 | `notify(error.message ?? t("Action failed"))` | 分动作文案 |
| components/partners/PartnerChat.tsx:510,989,1009 | 会话加载/分支裸 toast | 本地化兜底优先 |
| components/settings/ServiceConfigEditor.tsx:444 | 供应商测试裸 message toast | "Connection test failed" + 折叠详情 |
| components/settings/CodeBuddyAuthCard.tsx:37,67,78,90 | OAuth 轮询裸 setError | 映射 auth code |
| components/partners/WeixinQrLogin.tsx:57,76 | QR 轮询裸 setError | 本地化 + 重试指引 |
| features/settings/store/SettingsStore.tsx（10 处）| 含 `t("System status unavailable: {{message}}")` 裸插值 | 分段文案，raw 进 console |
| components/cli-apps/CliAppsSection.tsx:1013-1014 | helper 刻意对所有 CLI 错误返回 `error.message` | 映射 CliAppError code |
| components/memory/MemorySection.tsx（8 处）| `setToast(e.message)`；fallback 英文未包 t() | 包 t() + mapper |
| features/co-writer/components/CoWriterWorkspace.tsx（7 处）| 编辑/自动标记裸 toast/横幅 | 同上 |
| components/reading/ReadingExtensionBar.tsx:113,196,506；ReaderPane.tsx:871 | 讲解/翻译裸 `onError(error.message)` | 阅读域文案 |
| features/knowledge/api/client.ts:753,677-684 | `readErrorDetail → String(body.detail)` | code 层 |

其余 RAW-EXC-DISPLAY 合计 ~253 处 UI 站点（components 72 文件、features 16、app 13）+ 4 处 lib 提取器。

NO-ERROR-STATE（用户可感静默失败）3 处：hooks/useConnectedAgentKinds.ts:26（catch 置空缓存）、features/chat/components/ChatWorkspace.tsx:1893-1895（consult 预算静默不设）、hooks/useKnowledgeBases.ts:105（上传策略静默回默认值——上传限额显示可能失真）。另有 7 处属文档化的良性吞错。

LANG-MIX：web/lib/tool-availability.ts:26,27,40,41,52 硬编码中文徽标（"未配置"/"缺少凭证"/"暂不可用"）对全部语言展示（最重）；useTopicSourceLibrary.ts、lib/quiz-types.ts:273、lib/research-types.ts:119、space/EduHubImportModal、SpaceDashboard、ConnectedAgents、SettingsNav、SubagentSettingsEditor 私有 `(cn,en)` helper ~40 条绕过 locale（fr/de/pl/uk 用户看到 en/zh 混杂）；KbWebSourcesSection.tsx:65 硬编码英文且 key 不存在于任何 locale。

VAGUE ~30 处："Something went wrong."×7、"Action failed"×9、"Load failed"×8、"Error"（PartnerChat.tsx:859）、"unknown error"/"stream failed"/"start failed"/"undo failed"（MemoryRunPanel/useMemoryRun）、"Request failed"（client.ts:101）。

LOCALE-GAP：fr 缺 466 key（其中 26 个错误相关，如 `Selected model unavailable`、`readiness.detail.parser_probe_failed`、`readiness.detail.tool_backend_unavailable`、`readiness.detail.connection_test_failed`、`Save failed. Your edits are kept. Try again.`）、909 个陈旧多余 key；pl/uk 缺 common.json 整文件；en/zh/de 齐。另：`shared/api/client.ts` 的 4 条网络错误串与 `lib/auth.ts` 的 2 条在任何 locale 都没有 key（经 ApiError.message 直出，zh/de/fr/pl/uk UI 全英文）；`locales/*/common.json` 未被 i18n/init.ts 加载（37 key 全重复于 app.json），属死镜像。

INCONSISTENT（web）7 簇：网络失败 4 种话术（见 Top15 #15）；"Load failed" vs "Failed to load …"（8 vs 47）；"Save failed" vs "Failed to save …"（13 vs 20）；"Action failed" vs 具体 "Failed to …"；同类失败 toast vs 横幅不一致（KB 用横幅、partners/books/memory 用 toast、co-writer 两者混用）；裸文本插值风格 vs fallback-key 风格；上传策略静默 vs 上传错误裸显。

## 修复路径建议（不属本卡改动范围，仅建议）

1. 单点收敛 #1：`format_exception_message` 加脱敏（URL/凭据/长度截断/白名单 + 兜底文案）。
2. 单点收敛 #2：全局 exception handler 替换 62+ 处 blanket-500 `str(e)`（日志留痕、用户拿 coded 通用文案）。
3. 单点收敛 #3：`shared/api/client.ts` 做 error_code → `t()` 映射层，`book-errors.ts` CODE_MESSAGES 为现成模式。
4. 语义统一：`"{Entity} '{id}' not found."`、限流/超时/网络失败各收敛一条 key；NO-CODE 按模块渐进补 `{"code","message"}`。
5. i18n 补齐：后端高频 detail 进 `services/i18n.py` 目录；web 硬编码中文/双语 helper 进 locale；补 fr 26 个错误 key、pl/uk common.json。

## 扫描命令

```
rg -n 'HTTPException|raise ' deeptutor/api/routers/<file>.py
rg -n 'detail=str\(' deeptutor/api/routers/*.py        # 249 处
rg -n 'detail=\{' deeptutor/api/routers/*.py           # 结构化 code 先例 ~18 处
rg -n 'raise [A-Z][A-Za-z]*Error|raise ValueError|raise RuntimeError' deeptutor/services/<dir>
rg -nP 'raise [^\n]*[\p{Han}]' deeptutor/services/     # 0 处
rg -n 'error\.message|instanceof Error \? ' web --glob '*.ts*'
rg -nP '[\p{Han}]' web --glob '*.tsx' --glob '*.ts' -g '!**/locales/**' -g '!**/tests/**'
# locale key diff：python 逐 key 比对 web/locales/{en,zh,de,fr,pl,uk}/*.json
```

## 覆盖声明

- routers 层 44 文件全部覆盖（含 0 raise 的 tools.py、_partners_channel_schema.py）；~945 处 raise/HTTPException 全部经过分类统计，RAW-EXC/EXC-NAME/LANG-MIX/VAGUE 逐条列出，NO-CODE（~597 处，系统性）给每文件计数 + 代表样本。
- services 用户路径：session/、partners/、rag/、notebook/、practice/、sandbox/、voice/、subagent/、parsing/、llm/、mcp/、memory/、skill/、web_source/、videogen/、task_board.py、persona/、courses.py、courses_state.py、generation_http.py、office_preview.py、search/providers 逐 raise 扫描；keypool/singleflight/embedding 内部等非用户路径跳过。
- web：lib 错误提取层、全部组件目录错误态、hooks、app 路由组、6 locale 全 key diff。
