# LightRAG 参数配置面三分类清点（对照上游 #640，只读）

- 基线：`origin/main` @ `f07029cfc`（release: v1.6.13），分支 `scan/lightrag-params-20261005`
- 扫描范围（只读，不改任何代码）：
  - `deeptutor/services/rag/pipelines/lightrag/`（worker / cache_reuse / engine / pipeline / config / roles / indexing_policy / ingress / parser / sidecar / block_policy / storage / write_lock）
  - `deeptutor/services/rag/pipelines/lightrag_server/`（config / client / pipeline / probe）
  - 装配处：`deeptutor/knowledge/manager.py`、`deeptutor/services/rag/pipelines/modes.py`、`deeptutor/services/config/runtime_settings.py`、`deeptutor/api/routers/knowledge.py`、前端 `web/features/knowledge/components/engines/EngineDetail.tsx`、`web/components/knowledge/LightRagRoleModelsEditor.tsx`
- 上游 #640（[Feature Request]: Specify parameters of LightRAG system，OPEN）诉求：① 查询/抽取 LLM 可指定；② 文件处理并发优化参数；③ fallback 模型；④ 出于安全原因可把 LLM 请求限制在单一 provider。**只读对照，未实现，未动其关联 PR。**
- 上游已有已合并 PR 覆盖了 #640 的一部分：#877（并发+抽取旋钮）、#1070（专属模型选择）、#1171/#1174（索引模型固定）、#1265（四角色模型）、#1494（llm_timeout 可调）、#1281（原生 embedding 兼容）。当前开放 PR（#1759/#1760 meta 警告、#1703 日志吞错）与本清单无范围重叠，未触碰。

## 分类口径

- **A 已可配置**：存在 settings 键或 per-KB 字段，且有 API/UI 入口可改。
- **B 硬编码**：取值写死在模块常量或调用点，无任何入口。
- **C 有默认无入口**：运行时会消费某个默认值（DeepTutor 默认或 pinned SDK 默认），但没有任何入口可改。

---

## A. 已可配置（native 引擎 `lightrag/`）

| # | 参数 | 位置（读取/消费） | 当前取值与来源 | 入口 |
|---|------|------------------|----------------|------|
| A1 | 查询模式 `search_mode`（per-KB） | `lightrag/config.py:42-43`（SUPPORTED_MODES/DEFAULT_MODE="hybrid"）、`config.py:149-156`、`modes.py:19-44`、消费 `engine.py:480-485` | per-KB `kb_config.json` → `defaults.provider_modes` → 默认 `hybrid` | KB 设置 UI/API |
| A2 | 查询 `top_k` | `lightrag/config.py:159-170` → `engine.py:480-485`（QueryParam） | settings `top_k`，默认 60，clamp 1–200（`runtime_settings.py:1060`，默认定义 `:363`） | 引擎设置 UI（`EngineDetail.tsx:1120`）、API（`knowledge.py:1657`） |
| A3 | 查询 `response_type` | 同上路径 | settings，默认 "Multiple Paragraphs"（`runtime_settings.py:364`，截断 80 字符 `:1027-1031`） | UI（`EngineDetail.tsx:1126`）、API（`knowledge.py:1658`） |
| A4 | 查询/keyword 角色 LLM（含 reasoning_effort） | `roles.py:110-132`、`lightrag/config.py:199-253` | v2：`role_models.query/keyword`（base 继承或显式模型）；legacy：`llm_profile_id/llm_model_id` → 目录 active 模型兜底 | 角色编辑器（`LightRagRoleModelsEditor.tsx`）、API（`knowledge.py:1656`） |
| A5 | 抽取（indexing）LLM + VLM 选择（create/rebuild 时冻结） | `indexing_policy.py:306-359`（freeze_roles）、消费 `engine.py:224-279` | `role_models.base/extract/vlm`；单模型 legacy 请求兼容；fingerprint 固化进 meta.json | 建/重建 KB 表单 + 角色编辑器；上游 #1070/#1171/#1174/#1265 |
| A6 | 角色并发 `max_async`（extract/keyword/query/vlm 各自） | `lightrag_roles.py:35`（1–32，默认 4）、legacy 回退 `roles.py:96-107`（读 `llm_model_max_async`） | 角色级显式值，否则 legacy 默认 4 | 角色编辑器（`LightRagRoleModelsEditor.tsx:336`） |
| A7 | 角色超时 `timeout`（秒） | `lightrag_roles.py:36`（1–3600，默认 240）、legacy 固定 240（`roles.py:104`） | 角色级显式值，否则 240 | 角色编辑器（`LightRagRoleModelsEditor.tsx:344-350`） |
| A8 | `entity_extract_max_gleaning` | `lightrag/config.py:184-196` → `engine.py:277`（构造器） | settings，默认 1，clamp 0–5（`runtime_settings.py:1068-1070`） | UI（`EngineDetail.tsx:1155`）、API（`knowledge.py:1661`）；上游 #877 |
| A9 | `llm_timeout` → SDK `default_llm_timeout` | `lightrag/config.py:193` → `engine.py:277` | settings，默认 240，clamp 60–3600（`runtime_settings.py:1071`；SDK 以 2x 作为执行上限，注释 `:368-369`） | UI（`EngineDetail.tsx:1161`）；上游 #1494 |
| A10 | 解析池并发 `max_concurrent_files` → `max_parallel_parse_native` | `lightrag/config.py:173-181` → `engine.py:276` | settings，默认 1，clamp 1–16（`runtime_settings.py:1062-1064`）；预解析本身仍串行（`pipeline.py:137-146`） | UI（`EngineDetail.tsx:1147`）、API（`knowledge.py:1659`） |
| A11 | Embedding 模型与维度 | `lightrag/config.py:390-434`（build_embedding_func，dim 必须非 0 `:402-407`）；索引期冻结 `indexing_policy.py:569-595`，写入 meta 并做兼容校验（`pipeline.py:632,525`） | Settings → Catalog 的 active embedding（查询期 `pipeline.py:631`）；索引期用冻结快照 | Embedding 设置 + per-KB 绑定；上游 #1281 |
| A12 | LightRAG Server 引擎连接（per-KB `server_url`/`api_key`） | `lightrag_server/config.py:45-58`、装配 `knowledge/manager.py:983-1033` | per-KB 字段；账号级默认 `server_url/api_key`（`runtime_settings.py:378-382`）作为建连起点 | 连接 KB 表单 + 引擎页（API `knowledge.py:1761-1799`） |

## B. 硬编码

| # | 参数 | 位置 | 当前取值 | 说明 |
|---|------|------|----------|------|
| B1 | **分块策略与 chunk_token_size** | `ingress.py:258-262`（chunk_options 写入 manifest），消费 `engine.py:297-299` | 有结构 blocks → `{"paragraph_semantic": {"chunk_token_size": 1200}}`；纯文本 → `{"fixed_token": {}}`（SDK 默认几何） | 无 per-KB/settings 入口；改动需重建索引。#640 未点名但属同一配置面 |
| B2 | LLM 适配层重试策略 | `lightrag/config.py:51-54` | 3 次尝试、延迟 (1.0, 2.0)s、Retry-After 封顶 60s、可重试状态码 {408,429,500,502,503,504,529} | 模块常量；provider 内部重试被刻意置 0（`config.py:301,363`）防两层相乘 |
| B3 | worker loop 取消宽限 | `worker.py:27`（`DEFAULT_WORKER_CANCEL_GRACE_SECONDS = 10.0`），调用点 `pipeline.py:368,651` 用默认值 | 10.0s | 参数存在但调用点均不传 |
| B4 | 索引对账轮询/无进展超时 | `pipeline.py:102-103` | poll 0.2s；600s 无状态变化按未完成返回 | 实例属性，无入口 |
| B5 | 队列关停超时 | `engine.py:347`（`timeout=5.0`） | 5.0s | finalize 时对角色队列/embedding/rerank 关停 |
| B6 | QueryParam 固定字段 | `engine.py:480-485` | `stream=False`、`include_references=True` | mode 走 A1；其余字段进 SDK 默认 |
| B7 | Server 引擎 HTTP 超时 | `lightrag_server/client.py:42-43` | 60.0s（构造参数，调用方未传） | |
| B8 | Server 引擎仅取上下文 | `lightrag_server/client.py:91` | `only_need_context=True` | 设计契约：答案生成归 DeepTutor，服务器只做检索 |
| B9 | SDK 版本钉死 | `engine.py:31-32` | `lightrag-hku==1.5.7` 精确匹配（`engine.py:49-54` 校验） | |
| B10 | 构造器固定项 | `engine.py:274-275` | `auto_manage_storages_states=False`；`vlm_process_enable` 由启用 VLM 的文档推导 | 非调优项，列出备查 |
| B11 | embedding `max_token_size` 兜底 | `lightrag/config.py:46,429` | embedding 配置 `max_tokens` 缺失时回退 8192 | 兜底值硬编码 |
| B12 | legacy 角色回退超时 | `roles.py:104` | v1（无 role_models）时四角色 timeout 一律 240 | 只能靠切 v2 role_models 绕开 |

## C. 有默认无入口

| # | 参数 | 位置 | 默认来源 | 缺口 |
|---|------|------|----------|------|
| C1 | `fixed_token` 分块几何（chunk_token_size/overlap） | SDK 1.5.7 默认（DeepTutor 侧 `ingress.py:261` 传 `{}`） | pinned SDK 常量（与 B1 的 1200 数值巧合一致） | 无任何 DeepTutor 入口 |
| C2 | QueryParam 其余 SDK 字段（`user_prompt`、`max_token_for_text_unit/entity/relation`、`keyword_extraction`、`chunk_top_k` 等） | `engine.py:480-485` 只显式传 mode/top_k/response_type | SDK QueryParam 默认 | 无入口；#640 未明确要求，列储备 |
| C3 | settings 读取失败的静默回退 | `lightrag/config.py:169-170,180-181,195-196`（`except Exception: return {}`） | 回退到 SDK 默认而非 settings 默认（如 top_k 用 SDK 值） | 行为差异未被文档化，也无告警入口 |
| C4 | fallback 模型链（#640 明确诉求） | `lightrag/config.py:246-252`（query 解析失败时回退 active 目录模型） | 隐式单级回退，不可配置、无声明 | 无用户入口；需卡：显式 per-role fallback 选择 |
| C5 | 单 provider 限制（#640 安全诉求） | 选择校验 `roles.py:43-68`、`indexing_policy.py:274-303` 均走 `apply_allowed_llm_selection`（multi_user 全局访问过滤） | 只有全局目录权限过滤，无 per-engine「仅允许 provider X」锁 | 无入口；需卡 |
| C6 | VLM 启用推导 | `pipeline.py:147-148,311`（按文档含图 + 快照 vision_available 推导 enable_vlm） | 非独立旋钮 | 想强制开/关 VLM 需重建索引或换模型，无直接入口 |
| C7 | worker loop 线程模型 | `worker.py:34-57` | 进程级单 loop、daemon 线程 | 非调优项；列出说明并发上限来源（A6） |

## 可拆卡条目（建议）

1. **[feat] LightRAG 分块参数入口**（B1/C1）：在索引快照或 per-KB 配置暴露 chunk 策略与 `chunk_token_size`；写入 `ingress.py` chunk_options，改动要求重建索引（manifest/缓存身份已含 chunk_options，风险可控）。对应 #640 精神（索引几何可配）。
2. **[feat] per-role fallback 模型链**（C4）：`lightrag_roles.LightRagRoleModels` 增加 fallback 选择字段，`roles.resolve_selection`/`config.resolve_lightrag_query_llm_config` 按链回退并保留访问校验与缓存身份切换处理。对应 #640 第③点。
3. **[feat] LightRAG 单 provider 锁**（C5）：引擎设置增加 provider allow-list，在 `roles.resolve_selection` 与 `indexing_policy._freeze_role` 强制。对应 #640 第④点。
4. **[chore] 运行时观测/容错旋钮**（B3/B4/B5/B7）：取消宽限、对账 poll/无进展超时、server HTTP 超时收编为 settings 或至少常量集中 + 文档化。
5. **[docs] 静默回退行为说明**（C3）：`*_from_settings` 的 `except: return {}` 改为 warning 日志或在文档注明 SDK 默认兜底。
6. **[feat] legacy v1 角色超时可配**（B12）：v1 设置下 timeout 固定 240，评估是否允许 v1 读取时给 per-role 默认或提示迁移 v2。

## 去重标注（与既有 fix/test/scan 卡）

- `test/lightrag-cache-reuse-20261005`（d527b95e0）：覆盖 `cache_reuse.py` 版本解析与 donor 选择。本扫描确认该文件无可调参数（`_CACHE_FILE`/`_INDEX_TYPES` 为内容类型过滤常量），**无参数卡重叠**。
- `test/lightrag-worker-loop-20261005`（50b79ad31）与 `-v2`（6ee03161a，fix: worker 失败竞态上报）：B3 若成卡，必须基于 v2 分支续作（v2 改动了 worker 失败上报路径）。
- `fix-kb-mode-resolve`：本地与 myfork 均未找到该分支（`git branch -a` + `ls-remote` + log 检索无果）；search_mode 解析已在 main（`modes.py:19-44`），**视为已落地/分支不存在**，A1 无需新卡。
- `scan-persistence`（docs/persistence-scan-20261004，b130ee082，ref #612）：持久层扫描，涉及存储后端选型；本扫描只覆盖参数面，存储后端在 DeepTutor 侧非用户参数（SDK 管理），**不重叠**。
- 上游 #640 关联已合并 PR（#877/#1070/#1171/#1174/#1265/#1494/#1281）：本清单 A 类即其落点；开放 PR #1759/#1760、#1703 与参数面无关，未触碰。**无在途 PR 声明剩余范围（B/C 类），拆卡不撞车。**

## 验证方式（只读，未改代码）

```bash
git -C /Users/Shared/DeepTutor fetch origin main
git -C /Users/Shared/DeepTutor worktree list | grep agen680
git -C /Users/Shared/DeepTutor/dt-agen680-scan-wt rev-parse HEAD   # f07029cfc...
# 行号核对示例：
sed -n '51,54p' deeptutor/services/rag/pipelines/lightrag/config.py     # B2
sed -n '256,262p' deeptutor/services/rag/pipelines/lightrag/ingress.py  # B1
sed -n '361,373p' deeptutor/services/config/runtime_settings.py         # A 类默认值
```

统计：A 类 12 项、B 类 12 项、C 类 7 项；可拆卡建议 6 条（其中 3 条直接对应 #640 未满足诉求：fallback 链、单 provider 锁，及作为索引几何的分块入口）。
