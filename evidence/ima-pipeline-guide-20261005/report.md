# Tencent IMA 知识库管线导读（配置 → 检索 → 工具）与「检索返回空/无来源」断点清单

基线：`origin/main` @ `f07029cfc`（v1.6.13，2026-10-05 fetch）。全程只读，未使用任何真实 IMA 账号或密钥；所有行号以该 commit 为准。

对照声明：上游 issue #1500（1.6.8 / Windows / PyPI，伙伴挂 IMA 库检索无可核对内容与来源）只作现象参照，本卡不实现该 issue、不评论、不动其关联 PR。关联 PR 状态（2026-10-05 查询，只读）：

- #1513 `fix(rag): report empty retrieval results (#1500)` — **已合并**。即 main 上 `deeptutor/tools/builtin/__init__.py:78` docstring 所指的修复：检索"成功但为空"时 rag 工具回显 `No matching content was found …`，且不再用查询回声充当引文（`_rag_sources`，`deeptutor/tools/builtin/__init__.py:80-88`）。
- #873 `修复 IMA 只读连接与原文检索` — **已合并**（现 IMA 模块形态的主要来源）。
- #1261 `fix(partners): register connected KBs instead of copytree-ing a folder that never exists` — **已合并**（伙伴指针库 provisioning 现状来源）。
- 仍开放：#1118（media URL 域名清单调整）、#1649（kb eval）、#728（i18n）。均与本卡无关，未触碰。

---

## 1. 调用图：配置 → provider 选择 → 检索

### 1.1 配置层（凭证与库指针）

IMA 库在 `kb_config.json` 里是一条指针（`type: ima`），不落索引：

- 注册入口：`deeptutor/knowledge/manager.py:1106-1166` `register_ima_kb` — 写 `type: ima`、`rag_provider: ima`、`knowledge_base_id`；`client_id`/`api_key` **仅在该 KB 显式覆盖账号凭证时写入**（`manager.py:1148-1152`），缺省走账号级设置。半对凭证直接拒绝（`manager.py:1128-1129`）。
- 连接 API：`deeptutor/api/routers/knowledge.py:2679-2730` `connect_ima_route` — 服务端先 `probe_knowledge_base` 复核（`deeptutor/services/rag/pipelines/ima/probe.py:47+`），通过才注册；请求未带的凭证不会被拷到 KB 上。
- 凭证两级解析：`deeptutor/services/rag/pipelines/ima/config.py:84-127` — KB 条目自带的 `client_id`/`api_key` 优先（`config.py:96-101`），缺省回退账号级 `settings/ima.json`（`config.py:61-76`，经 `get_runtime_settings_service().load_ima()`）；任一字段仍缺则抛 `ImaNotConfiguredError`（`config.py:111-117`）。
- 账号级设置目录固定解析到 **admin scope**：`deeptutor/services/config/runtime_settings.py:1360-1370` → `deeptutor/multi_user/paths.py:89-91`（`admin_scope()`）。伙伴运行时在同一进程内（`deeptutor/services/partners/manager.py:483-489`），共享该目录。
- IMA 无检索模式旋钮：`deeptutor/services/rag/pipelines/ima/config.py:32-33` `SUPPORTED_MODES = ()`；模式解析只服务 LightRAG/GraphRAG（`deeptutor/services/rag/pipelines/modes.py:19-45`），`rag_naive/rag_hybrid` 别名传入的多余 `mode` kwarg 被 IMA 管线忽略。

### 1.2 provider 选择路径

```
rag 工具调用 (query, kb_name)
  └─ rag_search  deeptutor/tools/rag_tool.py:15-51
       ├─ (无显式 kb_base_dir 时) resolve_for_rag  deeptutor/multi_user/knowledge_access.py:337-346
       │    └─ resolve_kb：按当前用户 scope 解析 base_dir + 可访问性 (404/403)
       └─ RAGService.search  deeptutor/services/rag/service.py:85-192
            ├─ _resolve_provider(kb_name)  service.py:56-60
            │    └─ resolve_bound_provider  deeptutor/services/rag/provider_binding.py:45-63
            │         kb_config.json 的 rag_provider → 旧 metadata.json → 默认 llamaindex
            ├─ PageIndex 库直接改走工具面（service.py:94-108，IMA 不在此列）
            ├─ _get_pipeline → get_pipeline  deeptutor/services/rag/factory.py:193-209
            │    └─ normalize_provider_name（未知值回退 llamaindex，factory.py:67-74）
            │    └─ _build_pipeline（ima 分支 factory.py:165-170 → ImaPipeline，实例按
            │        (kb_base_dir, provider) 缓存 factory.py:63-64,206-209）
            └─ ImaPipeline.search  deeptutor/services/rag/pipelines/ima/pipeline.py:71-108
```

### 1.3 检索管线内部（`deeptutor/services/rag/pipelines/ima/`）

```
ImaPipeline.search  pipeline.py:71-108
  ├─ resolve_kb_config(load_kb_config_entry(...))   pipeline.py:73   ← 断点 P1
  ├─ client.search_knowledge(query, limit=top_k)    pipeline.py:77-82 ← 断点 P2
  │    └─ ImaTransport.post  transport.py:60-74（每次调用新 httpx client，超时 30s transport.py:34）
  │         ├─ HTTP 429 → ImaRateLimitError        transport.py:96-97
  │         └─ unwrap 信封  envelope.py:54-77（retcode/code 双拼写，envelope.py:27-29；
  │              20004/200002 鉴权、20002/110021 限流、110010/100003 可重试，envelope.py:31-39）
  │    └─ 翻页：cursor 分页最多 3 页，凑满 limit/is_end 即停  client.py:60,94-128
  │    └─ parse_knowledge_page  models.py:126-161：文档与文件夹分流（info_list/knowledge_list、
  │         folder_list/folders 双拼写，models.py:118-123）；纯文件夹命中不进 documents ← 断点 P3
  │    └─ _document_from  models.py:263-273：title + highlight_content（无 score/page 字段）
  ├─ documents_to_sources  sources.py:39-59 → {title, content=highlight, source=title, chunk_id=media_id}
  ├─ _hydrate  pipeline.py:110-135 ← 断点 P5
  │    └─ hydration_targets  sources.py:62-86：无片段优先、薄片段(<240字符)次之、预算 4 篇 ← 断点 P6
  │    └─ get_media_content  client.py:178-206 ← 断点 P4/P12
  │         ├─ note 型（media_type=11，client.py:64,340-345）→ notes 模块取正文 client.py:190-193
  │         └─ 文件型 → COS 下载（域名白名单+大小上限，media.py:44-60,84-109；URL 校验 media.py:143-152）
  │         └─ extract_text  media.py:112-140（扩展名判定 media.py:175-179，CPU 解析进线程）
  ├─ 过滤空 content（标题命中≠可引用证据，pipeline.py:86-88 注释点名 #1500）← 断点 P4
  ├─ matched 非空但全空 → content_unavailable  pipeline.py:89-100
  ├─ render_context  sources.py:89-95 → `[i] 标题\n内容` 拼接
  └─ 错误收敛为 {answer=异常文本, content="", sources=[], error_type}  pipeline.py:146-154
```

索引侧不存在：`initialize`/`add_documents` 直接 raise（pipeline.py:158-165），`delete` 只删本地指针（pipeline.py:169-172）。清单/枚举走另一条同步路径：`inventory.read_inventory`（inventory.py:79-123，BFS 遍历 `get_knowledge_list`，预算 8 请求/深度 3/6s 超时/60s 成功缓存/30s 失败缓存，inventory.py:41-58），由 manifest 层消费（`deeptutor/knowledge/manifest.py:85-99`）。

## 2. 伙伴路径与来源字段取用

### 2.1 伙伴拿到 IMA 库（"复制进工作区"）

- 资产配置：`deeptutor/services/partners/workspace.py:121-158` `provision_assets` → `_copy_knowledge_base`（workspace.py:180-221）。指针库无目录可拷，改为 `register_connected_entry` 只拷 `kb_config.json` 行（workspace.py:207-212；`deeptutor/knowledge/manager.py:827-853`，幂等）。
- 不可检索类型显式拒绝（obsidian/subagent/marginnote4，workspace.py:190-205；类型表 `deeptutor/knowledge/kb_types.py:123`）。`ima` 属于 connected 且可检索（`kb_types.py:103-131`）。
- 失败不阻断创建：错误收进 `provisioning.errors`（workspace.py:137-142；`deeptutor/api/routers/partners.py:802-805` 返回报告）← 断点 P8。
- 每回合 KB 选择：`deeptutor/services/partners/runtime.py:888-921` `_list_kb_names` — 私有资产型伙伴直接列伙伴 scope 的 `KnowledgeBaseManager.list_knowledge_bases()`；指针行因 `is_connected_kb` 恒保留不被孤儿清理（`deeptutor/knowledge/manager.py:677-684`）。共享工作区型则走可见性列表并过滤 `supports_rag_retrieval`（runtime.py:899-911）。
- 回合上下文装配：`runtime.py:828` `knowledge_bases=kb_names` → 代理循环 `_selected_kbs`/`_rag_kbs`（`deeptutor/agents/loop/pipeline.py:1746-1758`）→ `rag`/`kb_files`/`knowledge_frontier` 按 `has_kb` 挂载（`deeptutor/agents/_shared/tool_composition.py:48-68`）。

### 2.2 工具与来源字段

rag 结果 `sources[]` 的字段（IMA）：`title`、`content`、`source`、`chunk_id`（=IMA `media_id`）。消费方：

- `rag` 工具：`deeptutor/tools/builtin/__init__.py:124-179` — 空 content 且无 sources 时回显"未命中"（153-157，#1513 修复）；`_rag_sources`（68-102）把 `result["sources"]` 透传为引文并加 `type: rag`/`kb_name`，空/失败结果不再用查询回声顶替（#1500 注记在 76-78）。IMA 来源无 `page`/`score` 字段，研究链路的 CitationManager 用缺省值兜底（`deeptutor/agents/research/utils/citation_manager.py:42-58`）。
- `ima_read` 工具：`deeptutor/capabilities/ima/tools.py:184-231` — 用 `media_id`（即来源的 `chunk_id`）全文取读；依赖 `ima_list` 或检索引文里的 media_id。
- IMA 绑定：`deeptutor/capabilities/ima/binding.py:60-108` — 从回合 KB 选择里取 `type==ima` 的库生成绑定；凭证不进工具参数，调用时 `resolve_client` 现场解析并重查访问权（binding.py:87-108）。
- `kb_files`：走 manifest/`read_inventory`（2.1 节）；IMA 库读不到清单时报告"不可枚举"而非 0 篇（`deeptutor/knowledge/manifest.py:72-100`）。
- `read_source`：只读回合预装的 `source_index`（笔记/书籍/附件等，`deeptutor/tools/builtin/__init__.py:823-897`），与 rag 来源无关——IMA 检索来源不能用它读全文，只能 `ima_read`。

## 3. 「检索返回空 / 无来源」断点清单

每项含位置、触发条件与外部可观察现象。P1-P6 是管线主链，P7-P10 是伙伴/配置面，P11-P12 是边角。

| # | 断点 | 位置 | 触发条件 | 现象 |
|---|------|------|----------|------|
| P1 | 凭证/库 id 不完整 | `deeptutor/services/rag/pipelines/ima/pipeline.py:73-75`；`config.py:96-117`；账号级读取 `config.py:61-76` + `deeptutor/services/config/runtime_settings.py:1360-1370` | KB 行缺 `client_id`/`api_key`/`knowledge_base_id` 任一，且账号级 `settings/ima.json` 缺失、为空或读取异常（`config.py:71-72` 静默吞成空凭证）；半对凭证在注册期已挡（`manager.py:1128-1129`） | `error_type=not_configured`；rag 工具回显 `search failed (not_configured)`，`sources=[]` |
| P2 | IMA 调用失败 | `pipeline.py:77-82`；信封 `envelope.py:63-77`；传输 `transport.py:92-102`；超时 `transport.py:34` | 鉴权拒绝（20004/200002）、限流（20002/110021 或 HTTP 429）、网络错误/30s 超时、非 JSON/非信封响应、未映射业务码 | `error_type=retrieval_error`（或 auth/rate limit 类）；`answer`=异常文本、`sources=[]`、工具 `success=False` |
| P3 | 零命中或全为文件夹命中 | `pipeline.py:84-108`（`matched==[]` 路径）；分流 `models.py:133-147` | IMA `info_list` 为空；或全部命中是文件夹（`media_id` 空被分流进 folders，`models.py:139-143`）；或 3 页翻页后仍不足（`client.py:106-122`） | `content=""` 且 `sources=[]` → rag 工具回显 `No matching content was found …`（`deeptutor/tools/builtin/__init__.py:153-157`，#1513 已合并；1.6.8 无此回显，即 #1500 "执行完成但没有内容"的表象） |
| P4 | 有命中但全文不可读 | 过滤 `pipeline.py:86-100`；取文失败链 `client.py:186-206`（无 url_info/url → None）、`media.py:99-107`（下载失败/超 20MB）、`media.py:143-152`（URL 域名校验拒绝）、`media.py:131-133`+`175-179`（文件名/标题无受支持扩展名 → 不解析）、note 空（`client.py:190-193`） | 命中项全是标题命中且水合后 `content` 仍为空 | `error_type=content_unavailable`、`answer`=引导文案、`sources=[]` |
| P5 | 单项水合失败静默降级 | `pipeline.py:121-135`（异常只记 warning 类名，`pipeline.py:126-133`） | 部分命中媒体拉取异常；设计上保留其余结果 | 仅个别来源退化为标题引用；若其余也全空则坍缩到 P4 |
| P6 | 证据过薄 | `sources.py:29,33`（240 字符阈值、水合预算 4）+ `pipeline.py:84-85` | 命中多为单句高亮且超出 4 篇预算，未水合项以薄片段入上下文 | 上下文只有只言片语；模型可能自述"没有可用内容"——与 #1500 感受吻合但 `sources` 非空（有来源可引） |
| P7 | 伙伴侧 KB 不可达 | `deeptutor/tools/rag_tool.py:36-43`；`deeptutor/multi_user/knowledge_access.py:337-346`（resolve 404/403） | 伙伴 synthetic scope 的 `kb_config.json` 缺该 KB（provision 失败/被移除/名称不一致），或共享工作区选择里 `available=false` | `rag_search` 抛 `ValueError: not accessible`，工具异常结束 |
| P8 | 添加时静默失败 | `deeptutor/services/partners/workspace.py:137-142`；报告透传 `deeptutor/api/routers/partners.py:802-805`；名称冲突 `deeptutor/knowledge/manager.py:840-843` | provision 阶段 resolve/注册失败（如同名冲突），创建整体仍成功 | 伙伴资料库可能不显示该库或显示后检索必败；`provisioning.errors` 有记录——#1500 "添加后显示成功"表象的候选解释之一 |
| P9 | 清单层"0 篇/不可枚举" | `deeptutor/knowledge/manifest.py:72-100`；`inventory.py:41-58,109-123` | `read_inventory` 失败（网络/凭证/6s 超时/8 请求预算耗尽），失败缓存 30s | `kb_files`/知识中心显示不可枚举或低计数；连接型库的正常降级，单独不构成检索失败证据（#1500 亦声明 0 篇不作数） |
| P10 | provider 归一化走错管线 | `deeptutor/services/rag/factory.py:67-74`；`provider_binding.py:45-63` | KB 行缺 `rag_provider` 且无旧 `metadata.json` → 回退 llamaindex；指针库无本地索引 | 检索走 llamaindex 对空目录报错/`needs_reindex`。现注册链路均写 `rag_provider`，风险集中在手工改配置或外部导入的旧数据 |
| P11 | `ima_read` 与管线水合路径差异 | `deeptutor/capabilities/ima/tools.py:212-214`（无 title 候选）vs `pipeline.py:137-144`（带 title） | COS URL 路径无扩展名且 content-type 未映射时，`extract_text` 拿不到可解析文件名 → 返回空 | 仅影响 `ima_read` 工具（报"无可读文本"），rag 检索水合不受影响 |
| P12 | note 型条目空正文 | `client.py:64,340-345`（media_type=11 识别）；`client.py:190-193`；notes 取文 `notes.py:139+` | 命中项是 IMA 笔记且笔记接口返回空/失败 | 进入 P5→P4 链，最终 content_unavailable |

对照 #1500 的读法：该报告版本 1.6.8（2026-09-17）早于 #1513/#873/#1261 合并；其"两次查询、执行完成但无文本"最贴近 P3（当时无空结果回显）与 P4/P6（片段薄、全文取不到），P8 是"添加成功"表象的候选解释。当前 main 上工具层可见性已修复，其余断点是否仍复现需真实账号环境验证——本卡不含该验证。

## 4. 现有测试与覆盖空白

- `tests/services/rag/test_ima_pipeline.py`（55 个）：search/水合/错误映射，覆盖 P2/P4/P5 主链。
- `tests/services/rag/test_ima_client_surface.py`（26 个）：client 方法面与解析（P3 分流在 `models` 解析测试内）。
- `tests/services/rag/test_ima_inventory.py`（20 个）：清单缓存/预算（P9）。
- `tests/core/test_builtin_tools.py`（24 个，含 #1513 两条）：rag 工具空结果回显与引文回退禁用。
- `tests/services/partners/test_partner_workspace.py`（12 个）+ `test_workspace_binding.py`（7 个）：指针库 provision/注册（P8 后半）。

空白（可拆卡方向见 §5）：P1 的"账号级设置异常→空凭证"端到端分支；P10 旧数据无 `rag_provider` 的归一化回退；P11 的 `ima_read` 无扩展名路径；伙伴回合 `_list_kb_names` 私有资产分支对 connected 行的保留（manager 侧有测试，runtime 侧 `_list_kb_names` 无直接测试）。

## 5. 可拆卡条目（建议）

1. `test: ima 管线 not_configured 端到端分支` — 覆盖账号级设置缺失/异常时 `ImaPipeline.search` 返回 `not_configured` 且 rag 工具文案正确（P1）。只读推 myfork 分支，改测试不改产品代码。
2. `fix: ima_read 全文提取补 title 候选` — `capabilities/ima/tools.py:212-214` 传入来源 title 以对齐管线水合路径（P11），含回归测试。
3. `test: 无 rag_provider 旧 KB 行的 provider 回退` — `provider_binding.py:45-63` + `factory.py:67-74`（P10），固化"未知/缺失归回默认"契约。
4. `test: partner runtime _list_kb_names 保留 connected 行` — `deeptutor/services/partners/runtime.py:888-921`（P7/P8 前置），断言指针库不被孤儿清理误删（manager 侧已有，runtime 侧补）。
5. `guide: partner 资产 provisioning 与 kb_config 指针行导读`（可选文档卡）— 扩展本报告 §2，串联 workspace.py 与 manager 注册族。

## 6. 去重标注（验收 3）

- **guide-knowledge**（储备池 `deeptour.auto.jsonl`，"docs: Knowledge Base 摄取与检索模块代码导读"，未建卡）：覆盖上传→初始化→LlamaIndex 索引→检索的默认索引管线，产出 `docs/guides/knowledge-base.md`。与本卡交集仅 provider 选择（`provider_binding.py`/`factory.py`）与 `rag` 工具层（`tools/rag_tool.py`、`tools/builtin/__init__.py`）；本卡只按 IMA 视角记录这两层并注明，不产 LlamaIndex/摄取侧导读，无产物冲突。
- **test-kb-client**（储备池，"test: 前端 KB client 请求契约补测"，未建卡）：对象是 `web/features/knowledge/api/client.ts` 前端数据层契约。与本卡仅在 #1500 现象面（知识中心显示/`rag_provider`/`available` 字段）相邻，代码与产物零重叠。
- 结论：本卡与上述两张卡不构成重复；交集如上标注。板上检索 "IMA/guide/知识库管线" 亦未发现同主题卡。

## 7. 复核结论（卡面规则：上游 issue 已有关联 PR 时）

#1500 的直接关联 PR #1513 已合并入 main（工具层空结果可见性 + 引文回退禁用），另两块 IMA 连接/伙伴指针库修复 #873、#1261 亦已合并——卡面"已有 PR 则改复核"的义务已由本次只读对照覆盖：三者的修复方向与本报告断点清单一致，未发现与 main 现状冲突之处；#1500 剩余疑点（远端检索为何为空）需真实 IMA 账号复测，超出本卡只读边界。未向上游评论或提交任何内容。
