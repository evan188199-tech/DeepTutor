# 缓存键与失效策略一致性清点报告（AGEN-999）

- 日期：2026-10-07
- 基线：`origin/main @ f07029cfc`（HKUDS/DeepTutor release v1.6.13）
- 分支：`scan/cache-invalidation-20261007`（独立 worktree `dt-agen999-scan-cache-wt`，全程只读，未改任何产品代码）
- 方法：5 个分区并行扫描（LLM 生成 / 知识与 RAG / 技能与提示词 / 前端与生成契约 / 会话与系统杂项），逐项登记五要素（键构成 / 写入点 / 读取点 / 失效条件 / 陈旧漂移风险），并抽样对照现行代码复核。
- 数据：完整结构化清单见同目录 `cache_inventory.json`（每项含 file:line 级定位与置信度）。

## 一、总量与分布

**登记缓存点 102 个**（同族机制已合并，如各渠道消息去重 deque、零散 UI 偏好、提示词缓存组），其中：

| 分区 | 数量 | 说明 |
|---|---|---|
| session_system | 25 | 会话/存储/系统杂项（含 book 生成物、launcher 构建缓存、解析引擎版本等） |
| persistent | 15 | 跨重启磁盘缓存/索引（图片描述、解析缓存、LightRAG/LlamaIndex 索引、模型目录等） |
| rag_inprocess | 13 | 知识库/RAG 进程内缓存 |
| prompt_skill | 13 | 提示词/技能/目录/注册表 |
| frontend | 12 | 前端 localStorage/IndexedDB/内存缓存 |
| llm_client | 10 | LLM 配置/客户端/提示预测缓存（含 singleflight 机制） |
| channels | 7 | 伙伴渠道 token/去重/状态 |
| http_policy | 6 | 服务端 HTTP 缓存策略端点 |
| provider_side | 1 | 供应商侧提示词缓存标记（无本地状态） |

风险分级：**high 10 / medium 27 / low 65**。抽样复核 13 处（验收要求 ≥5），全部与现行代码一致（复核点清单见文末）。

## 二、高风险清单（需补失效保护）

1. **`prompt-manager-cache`**（`deeptutor/services/prompt/manager.py:20,88`）——全局解析后 YAML 提示词包缓存，进程生命周期；`clear_cache`/`reload_prompts` 存在但无生产调用方。**编辑任何 `deeptutor/**/prompts/*.yaml` 后旧提示持续供应直至重启**。同类：`learning-prompts-lru`（`learning/prompts.py:31`，`cache_clear` 全仓无调用）、`memory-consolidator-prompt-cache`（`memory/consolidator/modes/_runtime.py:32`）。
2. **`llm-config-cache` + `llm-client-singleton`**（`services/llm/config.py:160`、`services/llm/client.py:211`）——解析后模型路由（模型/端点/密钥）进程级 memo；仅 API 设置保存路径（`api/routers/settings.py:501`、`settings_spec.py:461-473`）清缓存。**带外修改 `model_catalog.json` 或切换 `DEEPTUTOR_HOME` 后持续路由旧配置直至重启**；`llm-client-singleton` 还是 first-caller-wins，启动期 warmup 可能永久钉错路由。
3. **`capabilities-runtime-negative-caches`**（`services/llm/capabilities.py:495,524`）——`(binding, model)` 负缓存 set（response_format / 强制 tool_choice），**无 TTL、无清除、无设置钩子**；瞬时供应商错误后能力永久静默降级直至重启。同类：`graphrag-capability-cache`（`graphrag/completion_adapter.py:23`）。
4. **`cowriter-local-draft`**（`web/features/co-writer/components/CoWriterWorkspace.tsx:305-309`）——本地草稿载入时**只要与服务器内容不同即覆盖服务器副本**（仅比较 content，无 revision/时间戳对拍）；配合后端 PUT last-write-wins（无 ETag/revision），autosave 失败或多端编辑时陈旧本地缓冲可静默回写覆盖较新正文。**全仓最重生成物漂移路径**。
5. **`kb-file-hashes-manifest` + RAG 版本索引删除缺口**（`knowledge/add_documents.py:111-169`、`rag/index_versioning.py`）——删除文档仅删 raw 文件+hash 记录，**向量/图实体保留至重建**（`remove_raw_document` docstring 明示）；且 raw 文件在 API 之外被手删时 hash 记录残留，同内容重传会被静默跳过索引而索引中并无此文档。
6. **`reading-snapshot-assets`**（`api/routers/reading.py:1328-1354`）——快照图片 `max-age=31536000, immutable`，而 `material_id = sha256(normalize_url)[:16]` **同 URL 重抓复用同 id 同 asset 名**：网页内容变更后重抓，所有曾加载的浏览器按 immutable 供旧图一年。结构性缺陷。
7. **`package-version-lru` → `parse-result-cache` 漂移链**（`parsing/engines/_versions.py:15`、`parsing/cache.py`）——包版本 lru 仅在托管安装路径 clear（`_install.py:105,111`）；**带外 pip/conda 升级引擎后旧 version 串→旧 parse 签名→升级前解析结果被持续复用直至重启**。
8. **`auth-config-import-snapshot`**（`services/auth.py:40-61`）——auth 开关/单用户凭据/JWT 密钥/PB 模式在 import 时快照，**改 `auth.json`/`integrations.json` 不重启不生效**。
9. **`claude-models-file-cache`**（`services/subagent/claude_models.py:32-97`）——`fetched_at` 仅展示不校验，**唯一刷新是设置页手动同步**；Claude Code 升级后模型目录静默漂移。同类外部消费：`~/.codex/models_cache.json`（DeepTutor 只读不校验）、CodeBuddy CLI 本地存储。
10. **`book-page-artifacts` + `book-kb-fingerprints`**（`book/engine.py`、`book/kb_health.py`）——生成的书页为持久生成物，**prompt/模型/代码变更从不自动失效**，仅显式重建；KB 漂移只告警（`has_drift`/`stale_page_ids`）不阻断，客户端忽略旗标即无限期阅读 KB 过期内容。

## 三、中风险摘要（27 项，择要）

- **提示/预测类缓存键缺模型与语言**：`chat-hints`（键=session\0transcript_length）、`reading-hints`、`mastery-hints`（均 30min TTL 有界）、`suggestions-starters`（6h TTL，指纹=SHA-1(language+profile+topics)，**不含模型/提示模板**）。切换模型后旧口吻提示最长存活一个 TTL。
- **永不清理的实例缓存**：`pipeline-instance-cache`（`rag/factory.py:64`，全仓无任何 clear，已删 KB 实例常驻）、`pageindex-cloud-tools/client-cache`（lru 1）、`msteams-conversation-refs`（30 天）等。
- **迁移/切换路径覆盖不全**：`sqlite-session-store-instances`/`file-library-store-instances` 仅被 `_clear_store_caches` 覆盖；`turn-runtime-manager-cache`/`app-runtime-registry`/`path-service-per-scope`/`skill|persona-service-instances` 均不被 launcher `_reset_runtime_singletons` 清除。
- **验证结果类**：`pocketbase-token-cache`（撤销≤60s 窗口，无界 dict）、`msteams-jwks-cache`（密钥滚动≤1h）、`video-provider-cache`（仅空时刷新，过期流 URL 供至播放失败）、`llm-options-swr`（服务器删模型在下次刷新前仍可选）、`visualizer-assets-http`（同 id 重装 5 分钟窗口旧 JS）。
- **`generated-files-no-policy`**：`reading raw/render` 与 `/files/outputs` 无显式 Cache-Control，非 no-store 客户端可启发式缓存旧字节（主 SPA 已 no-store 绕过）。

## 四、良好实践（无需处理）

- **内容寻址派生缓存**：`image-caption-cache`（15 字段模型身份+图片 sha256 入键）、`parse-result-cache`（引擎+版本+参数签名）、`office-preview-disk`、`file-library-download`/`workspace-item-files`（id⇒内容不可变）。
- **fail-closed 索引版本化**：LlamaIndex 按签名选版本无匹配即 `needs_reindex`；LightRAG 搜索/追加均 `EmbeddingMismatchError`；`llamaindex-index-cache` 键含 docstore+向量文件 mtime 与完整 embedding 配置哈希；`lightrag-cache_reuse` 供体须匹配索引策略指纹。
- **TTL 调优样板**：`codex-models-cache`（300s fresh/24h stale-while-error/凭据 generation 失效）是全仓最完整的失效设计。
- **前端**：`fetch(..., {cache:"no-store"})` 全量纪律、`deeptutor:v2:` 版本化存储包装、正确的内容寻址下载端点。

## 五、需补失效保护清单（建议，不改动代码）

1. 提示词缓存（prompt-manager / learning-prompts / memory-consolidator）：加文件 mtime 或内容哈希校验，或接入设置保存/启动重载钩子。
2. `llm-config-cache`/`llm-client-singleton`：参照 `embedding-client-singleton` 的 config 相等性自动轮换，消除 first-caller-wins。
3. `capabilities.py` 两个运行时负缓存：加 TTL，或仅对确定性 4xx（参数不支持）记忆、对瞬时 5xx/超时不记忆。
4. co-writer 本地草稿：载入时以 revision/updatedAt 与服务器对拍，仅当本地较新才覆盖；后端 PUT 增加 revision 条件写。
5. `claude-models-file-cache`：读路径校验 `fetched_at`（如 >24h 标记 stale 并后台重同步）。
6. RAG 删除链路：`remove_raw_document` 时对"已索引"文档设置 KB `needs_reindex` 提示（旗标已存在），并对 `file_hashes` 与索引做对账，防重传跳过。
7. `reading-snapshot-assets`：asset URL 加内容哈希查询参数，或将 immutable 降为短 max-age + ETag。
8. `suggestions-starters` 指纹与三个 hints 缓存键加入模型标识（hints 可顺带加 language）。
9. `video-provider-cache`：对缓存格式加时间上限（如 >1h 强制重解析）。
10. launcher `_reset_runtime_singletons` 补齐 skill/persona/path-service/session runtime 实例字典。

## 六、抽样复核记录（13/≥5，全部一致）

1. `llm/image_caption_cache.py:46-135` — sha256 键构成、原子写、版本校验读取 ✓
2. `services/singleflight_cache.py:36-75` — 惰性 TTL、容量淘汰、in-flight 合并 ✓
3. `services/chat_hints.py:44-75` — 键 `session_id\0transcript_length`、TTL 1800s、limit 256 ✓
4. `services/prompt/manager.py:85-100,218-246` — 缓存键构成、clear/reload 存在未被生产调用 ✓
5. `services/parsing/signature.py:32-46` + `parsing/cache.py:38-45` — 引擎签名与源字节哈希 ✓
6. `services/rag/index_versioning.py:46-64` — EmbeddingSignature 六字段 sha256[:16] ✓
7. `services/llm/capabilities.py:490-545` — 两个运行时负缓存 set、无失效 ✓
8. `services/suggestions.py:64-70,402-409,595-600` — 6h TTL、SHA-1 指纹不含模型、`_is_fresh` 判定 ✓
9. `web/features/co-writer/components/CoWriterWorkspace.tsx:300-312` + `storage/drafts.ts:53-70` — 本地草稿无条件覆盖服务器副本 ✓
10. `services/rag/factory.py:60-64,193-209` — `_PIPELINE_CACHE` 无任何失效调用 ✓
11. `knowledge/add_documents.py:141-169` — 删除文档不动向量、删 hash 记录 ✓
12. `services/llm/config.py:160-174,245-280` — 单全局槽、clear 仅手动接线 ✓
13. `services/llm/client.py:210-246` + `api/routers/settings.py:495-505` — first-caller-wins 单例与设置保存重置链 ✓

## 七、明确排除项（核实为"非缓存"）

`llm/request_cache.py`（KV 命中诊断指纹）、`generation_http.py`（纯 HTTP 管线）、embedding adapters（直通无向量缓存）、imagegen/videogen/voice（无产物缓存）、`knowledge/manifest.py`（每次现读）、`multi_user/grants.py`（权限无缓存，无过期授权窗口）、session 模块 `.cache` 命中（实为 `StoreScope.cache_key` 字符串键）、`web_source/crawler.py`（快照为有意持久化）、courses/practice（每次现读）、i18n（编译期常量）、telegram 等渠道（无 token/file_id 缓存）、`session/provider_response_state.py`（校验过的回放状态持久化）等，共 15 项，详见 JSON `negative_findings`。
