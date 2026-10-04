# Co-Writer 模块代码导读

> 基于 `origin/main` v1.6.12（`ef2d9e5c3`）。所有 `path:line` 均可在该提交直接定位。
> Co-Writer = Markdown 编辑工作台：导入/导出 DOCX、AI 选区改写（react edit）、自动保存到本地
> manifest。本文覆盖模块地图、docx↔markdown 双向管线、保存/版本链路与失败模式（吞错点 +
> 未测分支），衔接 DT-22 吞错扫描与覆盖率缺口（`routers/co_writer.py` 246 行缺失 / 40.0%）。

## 1. 模块地图

| 层 | 位置 | 职责 |
|---|---|---|
| REST 路由 | `deeptutor/api/routers/co_writer.py:36` | 挂载于 `/api`（`deeptutor/api/main.py:637`，带 `_auth` 依赖）：文档 CRUD、docx 导入/导出、edit/automark/history |
| docx 转换 | `deeptutor/co_writer/docx_converter.py:105`（docx→md）、`:432`（md→docx） | 纯函数互换层；python-docx 懒加载（`:85-97`），import 不拉 OOXML 栈 |
| 存储层 | `deeptutor/co_writer/storage.py:96` | 每文档一个目录 + `manifest.json`，原子写 |
| 编辑代理 | `deeptutor/co_writer/edit_agent.py:102` | `EditAgent(BaseAgent)`：rewrite/shorten/expand、RAG/web 取材、automark、历史审计 |
| 提示词 | `deeptutor/co_writer/prompts/{en,zh}/` | `edit_agent.yaml` / `narrator_agent.yaml`，经 `get_prompt` 按 key 回退内联默认值（`edit_agent.py:163-191`） |
| 路径服务 | `deeptutor/services/path_service.py:378-399` | `get_co_writer_*` 目录约定：`co-writer/documents/doc_{id}/manifest.json`、`history.json`、`tool_calls/` |
| 前端 API | `web/lib/co-writer-api.ts:31-120` | list/create/get/update/delete/import/export 七个封装 |
| 前端工作台 | `web/features/co-writer/components/CoWriterWorkspace.tsx` | 编辑器 + 预览分栏、草稿自动保存（`:289-350`） |
| 前端模型 | `web/features/co-writer/model/editor-state.ts:22-67` | 本地 undo/redo 编辑历史；`:115-119` 自动保存提交闸 |

## 2. 路由层与 API 面

- 单例代理：`get_edit_agent`（`routers/co_writer.py:51-67`）按 `get_response_language` 变化重建 `_edit_agent`（`:43`），每次调用 `refresh_config()` 以拾取 Settings 的 LLM 配置。
- 上限常量（`:72-76`）：文档 60 万字符（与转换器 `_MAX_MARKDOWN_CHARS` 一致，`docx_converter.py:22`）、选区 12 万、指令 1 万、上传 20MB（分块读，`:669-682`）。
- 路由分组：
  - 编辑（LLM）：`POST /documents/actions/edit`（`:424-447`，legacy 全文编辑）、`/edit-react`（`:450-458`，选区编辑）、`/edit-react/stream`（`:461-471`，SSE）、`/automark`（`:474-491`）。
  - 历史/审计：`GET /documents/history`、`/history/{op}`、`/tool-calls/{op}`（`:494-537`）。
  - 文档 CRUD：`GET/POST /documents`、`GET/PUT/DELETE /documents/{doc_id}`（`:601-768`）。
  - DOCX：`POST /documents/import/docx`（`:652-700`）、`POST /documents/export/docx`（`:703-717`）。
- doc_id 校验：`_DOC_ID_RE = ^[0-9a-f]{8,32}$`（`:546`，`_validate_doc_id` `:549-552`）；注释 `:544-545` 点明动机——id 会拼进 `documents/doc_{id}` 路径且 DELETE 走 rmtree，未校验的 id 可目录穿越。
- react edit 管线：`_run_react_edit`（`:243-389`）——校验请求（`:251`）→ 逐个工具取材，每个工具失败都降级为纯编辑（注释 `:256-258`）→ 组 prompt（`:134-180`，mode 缺省指令 `:115-131`）→ PageIndex 走 agent 内读循环，否则 `stream_llm`（`:311-349`）→ 清洗输出（`:183-195`，剥代码围栏 + thinking tags）→ `append_history`（`:363-379`）。SSE 包装在 `_stream_react_edit`（`:392-421`）：后台 task + `StreamBus`，异常转成 `event: error` 帧（`:402-405`），HTTPException 只透传 detail。
- 导出文件名安全化与 RFC 6266/5987 双编码在 `_docx_download_filename`（`:630-636`）与 `_content_disposition`（`:639-649`），非 ASCII 标题走 `filename*`。

## 3. docx↔markdown 管线

### 3.1 导入：`docx_to_markdown`（`docx_converter.py:105-137`）

1. **门禁**：空文件、OLE 魔数（legacy .doc）、非 `PK\x03\x04` 依次拒绝（`:106-117`，魔数 `:16-17`）。
2. **zip 炸弹防护** `_validate_docx_archive`（`:140-168`）：成员数 ≤4096、单成员 ≤20MB、总解压 ≤200MB、压缩比 ≤200（常量 `:18-21`）。
3. **转换**：`_iter_blocks` 按文档体顺序产出段落/表格（`:216-223`），逐块转 markdown（`:226-229`）：
   - 段落：样式名映射标题级别（`_HEADING_STYLES` `:29-38`）、编号列表靠 numbering.xml 的 `(numId, ilvl) → numFmt` 映射（`_numbering_formats` `:182-213`、`_list_kind` `:261-283`，样式名仅在映射缺失时兜底 `:276-282`）；内联内容渲染 runs + 超链接（`_inline_content_to_markdown` `:303-319`，`paragraph.iter_inner_content` 失败回退裸 runs `:307-309`）；run 级等宽字体→行内代码（`_CODE_FONTS` `:25`）、strike/bold/italic 依次加标记（`_run_to_markdown` `:326-348`）。
   - 表格：逐行转单元格文本，`_cell_text` 转义 `\` 与 `|`（`:374-376`），行数取最大宽度补齐后输出管道表（`_table_to_markdown` `:351-371`）。
4. **输出整形**：连续等宽段落重组为围栏代码块（`_group_code_blocks` `:383-410`，单段落保持行内代码）；空结果与超 60 万字符分别报错（`:129-136`）。
5. **降级**：任何非 `DocxConversionError` 异常落入 `_plain_ooxml_fallback`（`:127-128` → `:171-179`），改用通用文档抽取器 `extract_text_from_bytes` 兜底，仍失败才报 `DocxConversionError`。设计取向：宁可给出无格式纯文本，也不让导入失败。

### 3.2 导出：`markdown_to_docx`（`docx_converter.py:432-488`）

- 逐行状态机：围栏代码（`:444-445` → `_append_code_block` `:513-526`，Consolas）、管道表（`:447-452` → `_append_markdown_table` `:529-546`）、标题（`:454-460`）、水平线跳过（`:462-464`）、引用（`:465-468`）、两级缩进列表（`:470-481`，`_list_style` `:496-497`）、普通段落（`:483-484`）。
- 样式缺失兜底：`_append_styled_paragraph` 捕获 `KeyError/ValueError` 后改用 `add_heading`/裸段落（`:500-510`）。
- 行内解析 `_add_inline_runs`（`:601-632`）：先 `_mask_escapes`（`:579-592`）把 `\X` 换成哨兵 `\x00`，正则就不会命中转义字符；链接/代码/粗斜/粗/删/斜依次分支，最后 `_unmask` 还原。表格切分同理只认未转义 `|`（`_UNESCAPED_PIPE_RE` `:77`、`_split_table_row` `:549-563`）。
- 真超链接：`_add_hyperlink` 手工拼 `w:hyperlink` OOXML（`:635-660`），任何失败降级为纯文本 run（`:659-660`）。

### 3.3 往返一致性

- 转义对称：导出时 `_ESCAPE_RE`（`:75`）转义记号字符，导入时 `_unescape_md`（`:566-576`）还原；测试锁定 `5*3`/`a_b_c` 往返（`tests/api/test_co_writer.py:401-406`）与表格 `\|`（`:416-420`）。
- 代码块对称：docx 围栏压平成等宽段落再导入时按"连续 ≥2 段"重组围栏（`docx_converter.py:383-388` docstring 记录了该启发式），测试 `:458-464`。
- 已知不对称：docx→markdown 方向有序列表一律输出 `1.`（numFmt 只用来判 ol/ul，`_list_kind` `:271-275`；输出 `:243-244`），Word 原编号（lowerLetter 等）不保真；反向靠 Word 的 List Number 样式自动重排（`:478-481`）。标题样式 `subtitle` 映射为 H2（`:37`）。

## 4. 保存与版本链路

**后端没有版本表，"版本"由三层各管一段：**

1. **持久层 = 单 manifest**：每文档 `documents/doc_{id}/manifest.json`（`storage.py:7-13`），字段只有 `id/title/content/created_at/updated_at`（`:34-41`）。写路径走 `atomic_write_text`（`storage.py:54-56` → `deeptutor/services/file_io.py:63`），崩溃不会留下半截 JSON；但没有历史版本——每次保存覆盖唯一正文。
2. **前端草稿 = localStorage + 修订号**：`drafts.ts` 以 `deeptutor.co_writer.draft.v2.{docId}` 存 `StoredDraft{version, docId, content, revision, updatedAt}`（`drafts.ts:3-15`），解析失败/字段不符一律视为无草稿（`:31-51`）；v1 旧键读入即迁移并删除（`:61-66`）。
3. **自动保存闸 = revision 对账**：`CoWriterWorkspace.tsx:325` 先写本地草稿，`:338` PUT 后端，仅当 `shouldCommitAutosave(requestRevision, draftRevisionRef.current)`（`editor-state.ts:115-119`，请求期修订号仍最新）成立才 `clearDraft`（`CoWriterWorkspace.tsx:342-350`）——过期请求的落库结果不会误删较新的本地草稿。
- 标题联动：后端在未显式命名时让标题跟随首个标题行（`storage.py:211-216`、`_derive_title` `:70-83`，截断 120 字符）；导入时取文件名 stem（`routers/co_writer.py:693-696`）。
- **编辑历史是审计链，不是版本存储**：`EditAgent.process`/`auto_mark` 与 react edit 都 `append_history`（`edit_agent.py:231-243`、`:353-365`；`routers/co_writer.py:363-379`），整文件重写但有界：≤200 条、单文本 ≤20k 字符（`edit_agent.py:45-46`、`:76-82`），原子保存（`:62-65`）。工具调用原始结果另存 `tool_calls/{op}_{type}.json`（`:85-92`），供 `GET /documents/tool-calls/{op}` 回查。
- 存储单例按 workspace root 缓存（`storage.py:235-242`），多用户下每个用户的 PathService 得到独立实例。

## 5. 失败模式：吞错点与降级行为

DT-22 扫描（`agent/dt22-todo-scan` 分支 `evidence/todo-scan-2026-10-03/report.md` §7 附录 A）在 docx_converter 记了 4 处静默处理器；结合源码逐条给出实际后果：

| 位置 | 现象 | 实际后果（用户视角） | 测试卡 test-docx-converter |
|---|---|---|---|
| `docx_converter.py:256-258` `_style_name` | `except Exception: pass` → 返回 `""` | 样式查询失败=标题/列表/引用判定全部丢失，段落退化为纯文本，无任何信号 | `test_docx_converter_edges.py:111-173`（属性抛错、name 抛错、真实孤儿样式三路特征化） |
| `docx_converter.py:337-341` `_run_to_markdown` | `run.font.strike` 抛错被吞 | 删除线标记静默丢失（粗体/斜体不受影响，代码继续走 `:342-348`） | `:193-232`（非法 strike 值、读取失败、正常对照） |
| `docx_converter.py:354-357` `_table_to_markdown` | 单行 `row.cells` 抛错 `continue` | **整行表格数据静默消失**，无占位行无日志；全部行失败时返回空串（`:360-361`） | `:236-284`（坏行丢弃、全坏返回空、python-docx 1.2.0 宽松行为对照） |
| `docx_converter.py:539-542` `_append_markdown_table` | `table.style = "Table Grid"` 抛 `KeyError/ValueError` 吞掉 | 导出表格无网格线（LOW：内容完好，仅样式缺失） | 未覆盖（见 §6） |
| `docx_converter.py:659-660` `_add_hyperlink` | 关系写入失败吞掉，降级纯文本 | 导出 docx 中链接退化为普通文字 | 未覆盖 |
| `docx_converter.py:307-309` `_inline_content_to_markdown` | `iter_inner_content` 不可用回退裸 runs | 老版 python-docx 下超链接文本保留但 `[]()` 语法丢失 | 未覆盖 |
| `edit_agent.py:57-58` `load_history` | 损坏 history.json → `[]` | 审计链清零重来；注释 `:42-44` 明示 history 定位为调试/审计，非主存储，视为有意设计 | `tests/api/test_co_writer.py:153-159`（已测） |
| `routers/co_writer.py:402-405` `_stream_react_edit` | 任务异常转 SSE `event: error` | 不抛 500，靠前端解析错误帧；无堆栈落日志 | 未覆盖 |

设计上的"降级而非失败"是本模块主基调：导入兜底纯文本（`:127-128`）、取材失败继续纯编辑（`edit_agent.py:291-293`、`:320-322` 与 `routers/co_writer.py:256-258` 注释）、链接降级纯文本。吞错的分歧点在**数据丢失型**（表格行 `:356`、样式 `:256`）与**装饰丢失型**（strike、Table Grid）——前者应可见，后者可接受。

## 6. 覆盖率缺口与未测分支

基线：`audit/coverage-gaps-20261003` 分支 `evidence/coverage-2026-10-02/`（origin/main @ `ef2d9e5c3`，pytest-cov）。现有测试只有 `tests/api/test_co_writer.py`（校验器 + storage CRUD + docx 往返 + import/export 两个端点）。

| 文件 | 覆盖率 | 主要未测区域（行号） |
|---|---|---|
| `deeptutor/api/routers/co_writer.py` | **40.0%**（164/410，缺 246 行——覆盖率报告备选第 20 位） | react edit 全管线含 SSE（`:243-420`）；legacy edit/automark/history/tool-calls 端点（`:424-537`）；文档 CRUD 五端点（`:592-622`、`:723-768`）；import/export 的错误分支：无文件名 `:656`、空体 `:682`、转换失败 400 `:687-688`、未知异常 500 `:689-691`、落库失败 `:698-700`、导出异常 `:707-711`；`_default_mode_instruction`/`_build_react_edit_prompt`/`_prepare_react_edit_request`（`:115-239`） |
| `deeptutor/co_writer/docx_converter.py` | 85.3%（缺 69 行） | 纯文本降级路径 `:125-133`、`:171-179`；zip 防护三处上限 `:155`、`:160`、`:165` 及 BadZip `:143-144`；numbering 读取失败 `:188-189`、`:212-213`、`:299-300`；strike/bold/italic emit `:339-347`；表格行吞错 `:354-357`（见测试卡）；md→docx 水平线/引用 `:462-468`；样式兜底 `:505-509`；Table Grid 吞错 `:539-542`；行内 `***`/`~~` `:617-626`；超链接降级 `:637-640`、`:659-660` |
| `deeptutor/co_writer/storage.py` | 83.8%（缺 24 行） | manifest 损坏读取 `:65-67`；`_derive_title` 空行/兜底分支 `:77`、`:83` 与 `_build_preview` 截断 `:88`、`:93`；更新不存在的文档 `:204`；删除不存在 `:224`；全局 PathService 回退与单例 `:106`、`:239-242` |
| `deeptutor/co_writer/edit_agent.py` | **40.0%**（缺 96 行） | LLM 交互全路径未测：`process` `:146-247`、`gather_context` RAG/web `:262-322`、`auto_mark` `:333-369`、`save_tool_call` `:87-92`、PageIndex 分支 `:196-219` |

测试卡 **test-docx-converter**（分支 `agent/agen412-docx-converter-edge-tests`，`tests/co_writer/test_docx_converter_edges.py`，15 例）用 duck-typing stub 强制 python-docx 抛错，特征化锁定 §5 前三处吞错的**当前**行为；未覆盖 `:539-542`、`:659-660`、`:307-309` 三处。路由侧 246 行缺口暂无对应卡。

## 7. 相关在途工作

- 上游 PR #1700 `pr/docx-table-row-placeholder`（OPEN）：针对 §5 表格行吞错（`docx_converter.py:354-357`），改为保留占位行并告警——若合入，§5 第 3 行与 §6 对应缺口需复核更新。
- 上游 PR #1640 `codex/co-writer-model-selection`（OPEN，关联 issue #661）：为 react edit 增加模型选择，落在 `routers/co_writer.py` 编辑管线（§2）。
- 本导读仅为文档，未改动任何代码。
