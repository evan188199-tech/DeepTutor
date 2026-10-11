# co_writer 域导读（edit_agent · docx_converter · 路由/存储 · 前端协作面）

- 基线: origin/main @ `6cf793bd8`（release v1.6.14）。所有 `path:line` 在该 commit 逐一核对，相对仓库根目录。
- 定位: 讲清"一段 Markdown 草稿如何被创建、AI 编辑、保存与导出"。供后续修卡/补测卡快速定位改动面。
- 去重声明: 协同写作路由契约的逐端点行为由 test-co-writer 测试卡（`tests/api/routers/test_co_writer_contract.py`）与补测卡承接；docx 转换细节测试归 test-docx-converter；agent 行为测试归 test-edit-agent。guide-* 系列无本域主题。本文只做地图与调用链。

## 0. 一分钟总览

co_writer = "多人可用的 Markdown 协作草稿本 + AI 编辑器"。后端三件套：`deeptutor/co_writer/edit_agent.py`（编辑 agent）、`deeptutor/co_writer/docx_converter.py`（Word 互转）、`deeptutor/co_writer/storage.py`（manifest 文档存储）；HTTP 面在 `deeptutor/api/routers/co_writer.py`（挂载 `deeptutor/api/main.py:639`，prefix `/api`，鉴权 `_auth` 见 `deeptutor/api/main.py:593`）。前端面在 `web/features/co-writer/` + `web/app/(workspace)/co-writer/`。

### 函数级调用链 1：划词 AI 编辑（SSE 流式，最主链路）

1. 用户划词 → `applyReactSelectionEdit`（`web/features/co-writer/components/CoWriterWorkspace.tsx:976`）POST `/api/documents/actions/edit-react/stream`（`:995`；请求体 `selected_text/instruction/mode/tools/kb_name/llm_selection`）。
2. 路由 `edit_text_react_stream`（`deeptutor/api/routers/co_writer.py:565`）先做模型选择鉴权 `_validated_llm_selection`（`:83`，非管理员无授权模型 → 403 `:105-121`）与请求预检 `_prepare_react_edit_request`（`:296`，mode=none 且无指令 → 400）。
3. `_stream_react_edit`（`:480`）建 `StreamBus`（import `:30`），后台 task 跑 `_run_react_edit`（`:331`）。
4. `_selected_edit_agent`（`:136`）：带 `llm_selection` 时每请求新建 `EditAgent` 防并发串配置，否则走单例 `get_edit_agent`（`:56-72`，语言变化重建 + `refresh_config()`）。
5. 工具检索：`_normalize_react_edit_tools`（`:286`）→ `agent.gather_context`（`deeptutor/co_writer/edit_agent.py:249`；rag→`rag_search` `:271`，web→线程池 `web_search` `:302`；PageIndex KB 跳过预取改走读取 agent `:351-358`/`:400-423`）。任一工具失败静默降级为纯编辑（`edit_agent.py:291-293`, `:320-322`）。
6. 组 prompt：`_build_react_edit_prompt`（`:222`，mode 缺省指令 `_default_mode_instruction` `:203`）→ `agent.stream_llm`（`deeptutor/agents/base_agent.py:519`）逐 chunk 推 `event: stream`。
7. 收尾：`_clean_react_edit_output`（`:280`，去 thinking 标签 + 剥代码围栏 `:271`）→ `append_history`（`edit_agent.py:76`，限 200 条/单值 2 万字符 `:45-46`）→ SSE `event: result`（`:514-515`）或 `event: error`（`:512-513`）。
8. 前端 `processSseChunk`（`CoWriterWorkspace.tsx:1024-1067`）→ 草稿快照守卫（`:1073-1079`，编辑期间草稿变了则拒绝套用）→ `replaceSelectedText`（`:1081`）→ 防抖自动保存（`:345-384`，1.5s `:108`）→ PUT `/api/documents/{doc_id}`（`co_writer.py:842`）→ `storage.update_document`（`deeptutor/co_writer/storage.py:195`）。

### 函数级调用链 2：docx 导入（备份链路）

选文件（`web/app/(workspace)/co-writer/page.tsx:89` `importCoWriterDocx`）→ POST `/api/documents/import/docx`（`co_writer.py:758`）→ 扩展名白名单 `:763-773`、分块累计限 20MB `:775-788` → `asyncio.to_thread(docx_to_markdown, ...)`（`:792`）→ 魔数/归档校验（`deeptutor/co_writer/docx_converter.py:113-123`, `:152-180`）→ 解析失败兜底 `extract_text_from_bytes`（`:183-191`）→ `storage.create_document`（`storage.py:162`）。

## 一、HTTP 路由清单（`deeptutor/api/routers/co_writer.py`）

| 端点 | 行 | 说明 |
|---|---|---|
| POST `/api/documents/actions/edit` | `:521` | 全文编辑（rewrite/shorten/expand，`EditRequest` `:164`） |
| POST `/api/documents/actions/edit-react` | `:549` | 划词编辑（非流式，`ReactEditRequest` `:178`） |
| POST `/api/documents/actions/edit-react/stream` | `:564` | 划词编辑 SSE（`text/event-stream`，`:571-575`） |
| POST `/api/documents/actions/automark` | `:578` | AI 自动标注（`AutoMarkRequest` `:193`） |
| GET `/api/documents/history`、`/history/{id}` | `:600`, `:612` | 操作历史（审计用） |
| GET `/api/documents/tool-calls/{id}` | `:629` | 工具调用落盘详情 |
| GET/POST `/api/documents` | `:707`, `:719` | 列表（摘要+preview）/ 新建 |
| POST `/api/documents/import/docx` | `:758` | docx → 新文档 |
| POST `/api/documents/export/docx` | `:809` | markdown → docx 下载（`_docx_download_filename` `:736`、RFC6266 Content-Disposition `:745`） |
| GET/PUT/DELETE `/api/documents/{doc_id}` | `:826`, `:842`, `:860` | 单文档读写删 |

payload 上限：正文 60 万字符、选区 12 万、指令 1 万、docx 20MB（`:157-161`）。doc_id 必须 `^[0-9a-f]{8,32}$`（`:652`, `_validate_doc_id` `:655`）——DELETE 底层是 rmtree，id 不校验会越出 documents 根。

## 二、会话/草稿/导出数据流

**服务端存储**（`deeptutor/co_writer/storage.py`）：每文档一目录 `documents/doc_{id}/manifest.json`（布局 `:7-13`），整文档单文件、原子写 `_atomic_write_json`（`:54-56`，经 `deeptutor/services/file_io.py`）；`create_document` 用 `uuid4().hex[:12]`（`:168`）；`update_document` 在用户未显式命名时让标题跟随首个标题行（`:211-216`）；列表按 `updated_at` 倒序（`:159`）；`delete_document` 直接 `rmtree`（`:221-226`）。存储实例按 workspace_root 缓存（`get_co_writer_storage` `:238-242`），多用户各自隔离。

**客户端草稿缓冲**（`web/features/co-writer/storage/drafts.ts`）：localStorage key `deeptutor.co_writer.draft.v2.{docId}`（`:4`），结构 `{version,docId,content,revision,updatedAt}`（`:9-15`）；载入时优先服务器、本地草稿仅在内容不同时覆盖（`CoWriterWorkspace.tsx:305-309`——页面在防抖落盘前刷新的场景）；每次内容变更 revision+1 写入（`:338-342`），autosave 成功后 `clearDraft`（`:366`），过期回包用 `shouldCommitAutosave` 丢弃（`web/features/co-writer/model/editor-state.ts:115-118`）。旧版无版本前缀 key 自动迁移（`drafts.ts:61-66`）。

**Word 互转**（`deeptutor/co_writer/docx_converter.py`）：`python-docx` 惰性导入（`:90-102`，边界测试 `tests/runtime/test_api_import_memory_boundary.py:37`）。docx→md：样式映射（`_HEADING_STYLES` `:32`）、编号列表识别走 numbering.xml（`_numbering_formats` `:194`/`_list_kind` `:277`）、超链接走 `iter_inner_content`（`:319-335`）、等宽字体段落聚合回代码围栏（`_group_code_blocks` `:408`）、表格坏行降级占位（`:376-381`）。md→docx：行扫描器 `markdown_to_docx`（`:457`），行内标记经转义掩码解析（`_mask_escapes` `:604`/`_add_inline_runs` `:626`），链接生成真实 hyperlink（`_add_hyperlink` `:660`），`\|` 不切列（`_split_table_row` `:574`）。归档防炸包上限见 `:19-24`。

## 三、edit_agent（`deeptutor/co_writer/edit_agent.py`）

- 继承 `BaseAgent`（`deeptutor/agents/base_agent.py:33`）：构造时 `get_agent_params(module_name)` 取 temperature/max_tokens（`base_agent.py:97`），prompts 由 PromptManager 按 `co_writer/edit_agent` 加载（`base_agent.py:137`；映射 `deeptutor/services/prompt/manager.py:33,45`；包体 `deeptutor/co_writer/prompts/{en,zh}/edit_agent.yaml`，含 system/action_template/context_template/user_template/auto_mark_system/auto_mark_user_template）。
- `process`（`:130`）：全文编辑主路径；PageIndex KB 改走 `read_pageindex_with_agent`（`:196-219`），其余 `stream_llm` 聚合（`:221-228`）。每次操作 `append_history`（`:231-243`）+ `save_tool_call` 落盘检索原始结果（`:85-92`）。
- `auto_mark`（`:324`）：`【term】/《statement》` 可读标注；输出含 `data-rough-notation`（HTML 注入味）则整体回退原文（`_readable_automark_output` `:95-99`, `:350`）。
- 历史/工具文件目录全部按当前用户 PathService 解析（`:24-33`），多用户互串。`get_stats/print_stats` 为模块级 token 统计（`:397-409`）。

## 四、前端协作面

- 列表页 `web/app/(workspace)/co-writer/page.tsx`：拉列表 `:51`、新建 `:70`、导入 `:89`、删除 `:106`（`.docx` accept `:177`）；详情路由 `[docId]/page.tsx:14` 渲染 `<CoWriterWorkspace docId=...>`。
- `CoWriterWorkspace.tsx`（2561 行）：服务器载入+本地草稿回放（`:292-334`）、undo/redo 栈（`:269-272`）、全文编辑 `applyEdit`（`:1108`，含快照守卫 `:1133`）、automark（`:1155`）、划词弹层与 SSE trace（`:976-1106`）、KB 下拉（`:403-417`）、模型选择 `useLLMOptions` + `llm_selection`（`:260-285`）。
- 请求生命周期 hooks：`useSelectionEdit.ts:6-20`（AbortController 互斥）、`useDocumentLifecycle.ts:10-21`（卸载/revision 门）、`useSplitPane.ts`、`useSynchronizedScroll.ts`（分栏比例与同步滚动持久化 key 见 `drafts.ts:6-7`）。
- API 客户端 `web/lib/co-writer-api.ts`：CRUD+import/export 全部端点封装（`:31-128`）。
- 跨页刷新：`web/lib/co-writer-events.ts:8` 用 window 事件 `co-writer:changed` 通知侧栏/首页列表。
- 笔记互通：chat 的 Markdown 笔记页签可另存/更新为 co_writer 文档（`web/components/chat/home/ChatMarkdownNoteTab.tsx:14-17,28-29,86`）；保存为 notebook 时 `record_type="co_writer"`（`deeptutor/services/notebook/service.py:36`，路由白名单 `deeptutor/api/routers/notebook.py:73`）。
- 其他消费方：dashboard 草稿库直接复用 `list_documents`（`deeptutor/api/routers/dashboard.py:135`）；学习主题材料按 source_id 读 co_writer 文档（`deeptutor/learning/topic_materials.py:348-350`）；memory 快照统计草稿目录（`deeptutor/services/memory/snapshot/adapters.py:177`）。

## 五、配置项

| 配置 | 位置 | 默认 |
|---|---|---|
| LLM 预算（temperature/max_tokens） | runtime `agents.yaml`（`deeptutor/services/config/loader.py:251`），首次由 `DEFAULT_AGENTS_SETTINGS` 播种 `deeptutor/services/setup/init.py:83` | 0.7 / 4096 |
| 能力实例设置面 | `deeptutor/services/config/capabilities_settings.py:48`（读写映射）、`:62`（内置默认） | 0.6 / 4096 |
| agent UI 元数据 | `deeptutor/api/routers/agent_config.py:27-31`（icon/color/label） | PenTool/amber |
| 回复语言 | `get_response_language`（`deeptutor/services/settings/interface_settings.py:311`），路由侧 `co_writer.py:51-53`；语言变化会重建单例 agent（`:68-69`） | UI 设置 > system.language |
| 请求级模型选择 | `llm_selection` → `activate_llm_selection`/`reset_llm_selection`（`deeptutor/services/model_selection/runtime.py:39,46`；鉴权 `co_writer.py:83-133`） | 单例默认配置 |
| 存储目录 | `deeptutor/services/path_service.py:385-406`（co_writer 根/history/tool_calls/audio/documents/manifest），初始化 mkdir `:511-512` | `data/user/workspace/co-writer/` |
| 上限 | 正文/选区/指令/docx 尺寸 `co_writer.py:157-161`；docx 解压防爆 `docx_converter.py:19-24`；历史 `edit_agent.py:45-46` | 见左 |

## 六、常见故障定位

| 症状 | 先看 |
|---|---|
| 404 Document not found | doc_id 不匹配正则 `co_writer.py:652-658`；前端置 docNotFound `CoWriterWorkspace.tsx:320-321` |
| 导入报 Legacy .doc | 扩展名检查 `co_writer.py:763-773` 与魔数 `docx_converter.py:113-117` 双层拦截 |
| 导入 400 超 20MB/空文件 | 分块累计 `co_writer.py:775-788` |
| "no extractable text"/超 60 万字符 | `docx_converter.py:141-148` |
| "python-docx is not installed" | 惰性导入翻译 `docx_converter.py:98-101` |
| 403 No LLM model is assigned | 非管理员无 `llm_selection` 且无 assigned 模型 `co_writer.py:105-121` |
| 400 请先选中/请输入编辑要求 | `_prepare_react_edit_request` `co_writer.py:301-316` |
| "The draft changed before AI edit finished" | 快照守卫 `CoWriterWorkspace.tsx:1073-1079`（全文 `:1133`）——竞态保护，不是 bug |
| 编辑结果没生效 | RAG/web 检索失败静默降级 `edit_agent.py:291-293,:320-322`；thinking 标签/围栏清洗 `co_writer.py:271-283` |
| automark 输出被丢弃 | HTML 标记守卫 `edit_agent.py:95-99,:350` |
| SSE 只有 stream 无 result | 异步异常转 `event: error` `co_writer.py:499-513`；前端缺 result 报错 `CoWriterWorkspace.tsx:1068-1070` |
| history.json 异常变大 | 上限 200 条、单值 2 万字符截断 `edit_agent.py:45-46,:68-82`；整文件原子重写 `:62-65` |
| 本地草稿"复活"旧内容 | 载入优先级 `CoWriterWorkspace.tsx:305-309`；autosave 失败不清 draft `:366-371` |

## 七、测试现状与补测锚点

- 路由契约：`tests/api/routers/test_co_writer_contract.py`（617 行；CRUD 形状、非法 payload 4xx、导出/导入失败分支，storage/agent 全 stub）。
- 后端单测：`tests/api/test_co_writer.py`（676 行；doc_id 校验、storage CRUD、历史上限、docx 转换往返）。
- 导入内存边界：`tests/runtime/test_api_import_memory_boundary.py:19,37`。
- 前端：`web/tests/co-writer-lazy-notebook.spec.tsx`、`web/tests/co-writer-model-selection.spec.tsx`。
- 补测卡可切入的薄弱面：`gather_context` 的 PageIndex 分支（`edit_agent.py:196-219`）、`_stream_react_edit` 的 error 事件路径（`co_writer.py:499-518`）、`update_document` 标题跟随语义（`storage.py:211-216`）、`_group_code_blocks` 多段落围栏重组（`docx_converter.py:408-435`）。

## 八、边界与注意事项

- 所有结论锚定 `6cf793bd8`；上游 main 演进后行号需复核（参照本文头部基线法）。
- DELETE = rmtree、PUT 无乐观锁：并发编辑同一文档最后写入胜出，前端靠 revision 门丢弃过期回包（`editor-state.ts:115`），服务端不做版本合并。
- docx 归档校验上限（成员数/单成员/总量/压缩比）是防资源耗尽的工程护栏（`docx_converter.py:152-180`），调整需同步 `tests/api/test_co_writer.py` 对应断言。
- 单例 `EditAgent` 依赖 `refresh_config()` 拉新配置（`base_agent.py:208-232`），带 `llm_selection` 的请求必须走 `_selected_edit_agent` 的临时实例路径（`co_writer.py:145-152`），勿在单例上改 api_key/model。
