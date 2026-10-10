# DeepTutor `web_source` 网页源同步子系统导读

- 基线：origin/main @ `6cf793bd8`（v1.6.14）。
- 范围：`deeptutor/services/web_source/` 全部 11 个文件（约 3.3k 行）+ 三个外部接驳面（KB metadata、API/CLI 入口、Reading 快照落库）+ 测试覆盖对照。
- 所有锚点形如 `path:line`，相对仓库根；行号为该基线的可抽样复核位置。
- 与既有导读的关系：`docs/guides/tools-surface.md` 讲工具面（`web_fetch` 的 SSRF 守卫在彼处），`docs/guides/events-and-progress-chain.md` 讲事件链；本篇是该子系统首份专述。

## 1. 这一层是什么：一条"抓取→差分→落库→索引"流水线

```
注册源(metadata.json) → 抓取(crawler+robots+html_extractor) → 差分(page_hashes)
   → 写 raw/*.md → 删页重建/增量索引(add_documents) → 回写 metadata + SQLite(job/配对)
   → 前台经 API 读取状态与导航/配对；Reading 另走单页快照(ingestion+snapshot_assets)
```

两层同步语义并存，读代码时先分清：

- **按需单次同步** `sync_source()`（`deeptutor/services/web_source/sync.py:98`）：API `sync-web` 与 CLI `kb sync` 直接调，一次爬取一次落库，无队列。
- **常驻调度同步** `WebSourceSyncScheduler`（`deeptutor/services/web_source/scheduler.py:50`）：15s 一轮的 asyncio 循环，把每个账户的启用源排进 SQLite 队列，带租约/恢复/退避。

## 2. 模块地图

| 模块 | 行数 | 职责 | 核心入口 |
|---|---|---|---|
| `crawler.py` | 681 | 异步 BFS 文档站爬虫 + 共享"爬取-差分-写盘"管线 | `crawl_docs_site:347`、`crawl_and_diff:563`、`CrawlDiff:533` |
| `html_extractor.py` | 643 | 正文提取为 markdown、侧边栏导航、标题、语言/hreflang | `extract_article_markdown:320`、`extract_navigation:138`、`extract_page_language_and_alternates:584` |
| `repository.py` | 632 | SQLite（WAL）持久化同步 job 与双语配对 | `SQLiteWebSourceSyncRepository:112` |
| `scheduler.py` | 336 | 常驻调度循环、租约、取消、退避 | `WebSourceSyncScheduler:50`、`_run_job:189` |
| `bilingual.py` | 255 | hreflang + URL 语言模式的双语页配对 | `detect_bilingual_pairings:129` |
| `sync.py` | 253 | 单源同步编排（爬→差分→删→索引→回写） | `sync_source:98`、`WebSyncResult:28` |
| `robots.py` | 182 | robots.txt 解析/许可 + 每主机限速 | `parse_robots_txt:70`、`CrawlAccess:113` |
| `snapshot_assets.py` | 171 | 快照外链图片本地化（Reading 用） | `localize_snapshot_images:44`、`fetch_snapshot_image:90` |
| `navigation.py` | 72 | 扁平导航 → 树形 manifest | `flat_to_tree:14`、`build_navigation_manifest:55` |
| `markdown.py` | 28 | 剥离旧版爬虫来源注释 | `strip_leading_snapshot_provenance:13` |
| `__init__.py` | 1 | 空包标记 | — |

外部依赖锚点：SSRF 守卫与读取上限复用 `deeptutor/tools/web_fetch.py`（`_is_disallowed_host:177`、`MAX_RESPONSE_BYTES:39`=4MB、`DEFAULT_MAX_CHARS:38`=50k）；索引写入 `deeptutor/knowledge/add_documents.py`（`add_documents:604`、`remove_raw_document:141`）；源注册与状态回写 `deeptutor/knowledge/manager.py`（`add_web_source:2328`、`update_web_source_state:2399`、`get_all_web_sources:2434`）。

## 3. 数据流：从注册到检索

1. **注册**：`POST /knowledge-bases/{kb}/web-source`（`deeptutor/api/routers/knowledge.py:5023`）或 CLI `kb add-web-source`（`deeptutor_cli/kb.py:520`）→ `add_web_source`（`manager.py:2328`）写入 `metadata.json` 的 `web_sources[]`：`id`=URL md5 前 8 位（`manager.py:2346`）、`max_depth/max_pages`（1..5 / 1..200，`crawler.py:47-48` 校验上限）、`sync_interval_hours` 默认 24。注册后即向调度器补一条 pending job（`knowledge.py:5030-5033`）。
2. **抓取**：`crawl_docs_site`（`crawler.py:347`）先过 robots 闸门（`crawler.py:416-423`，不可用即整体失败、fail-closed），随后批量 BFS（批大小=并发 8，`crawler.py:49,412`），每跳重定向都重做 SSRF + robots 校验（`crawler.py:213-221`）。爬取范围锚定种子 URL 的目录前缀（`crawler.py:395-400`）。
3. **正文提取**：`_process_page`（`crawler.py:283`）调 `extract_article_markdown`，失败退回 `web_fetch._extract_readable`（`crawler.py:313-315`）；正文 sha256 作 `content_hash`（`crawler.py:316`），超 50k 截断（`crawler.py:324-325`）。
4. **差分**：`crawl_and_diff`（`crawler.py:563`）以 `_source_filename`（`crawler.py:170`，`_web/<源url哈希16>/路径.md`）为键，对 `source["page_hashes"]` 算 added/updated/unchanged/removed（`crawler.py:623-640`）；unchanged 但磁盘文件缺失时强制重落（`crawler.py:630-636`）。
5. **落库**：新/改页写 `raw/_web/<ns>/**.md`，写前剥旧版来源注释（`crawler.py:644-652` + `markdown.py:13`）；删除页先 `remove_raw_document` 再全量重建索引（多数量提供商不支持按文档删向量，`sync.py:133-160`、`_rebuild_index_after_removal:77`）；仅改动时走增量 `add_documents`（`sync.py:161-169`）。
6. **状态回写**：成功才推进 `page_hashes` 与 `last_sync_status`（`sync.py:180-190`）；导航 manifest 与配对一并进 metadata。配对另以当前用户身份尽力写入 SQLite（`sync.py:192-205`）。
7. **消费面**：`GET .../web-sources` 返回含 `navigation`/`bilingual_pairings` 的源列表（模型定义 `knowledge.py:4911-4927`）；Reading 网页导入是独立单页快照路径（见 §6）。

## 4. 同步状态机（SQLite job）

表 `web_source_sync_jobs`，主键 `(owner_id, kb_name, source_id)`（`repository.py:132-146`）；库文件 `SYSTEM_ROOT/web-source-sync.sqlite`（`scheduler.py:36-39`）。

```
            claim(条件: pending/interrupted/error/cancelled 或 running+租约过期)
pending ────────────────────────────────▶ running
  ▲                                        │ mark_success(下轮=now+interval, attempt=0) ──▶ pending
  │ retry(error/interrupted/cancelled→pending, attempt=0)        │ mark_failure(下轮=min(interval,1h×(attempt+1)), attempt+1) ──▶ error
  │                                        │ mark_interrupted(下轮=now) ──▶ interrupted
  │                                        │ mark_cancelled ──▶ cancelled
  └──────────────┬─────────────────────────┘
stale running（他人 runner 且租约过期）─ recover_interrupted ─▶ interrupted
```

- 转移实现：`claim:297`（`BEGIN IMMEDIATE` + 状态复核，`repository.py:307-346`）、`mark_success:387`、`mark_failure:400`（错误截 2000 字符 `:413`）、`mark_interrupted:419`、`mark_cancelled:430`、`retry:509`、`recover_interrupted:252`。
- 所有关锁更新带三重护栏 `state='running' AND runner_id=? AND lease_until_ms>now`（`repository.py:381`）——过期持有者覆写不了新认领（测试 `tests/services/web_source/test_sync_scheduler.py:162`）。
- 到期队列：`due_jobs` 只取 `pending/interrupted/error` 且 `next_run_at_ms<=now`（`repository.py:283-295`）。

**调度循环**（`scheduler.py:108-116`，周期 `WEB_SYNC_CHECK_SECONDS=15`）：

1. `_synchronize_sources:146`：按 owner 枚举全部 KB 的启用源（`enabled` 与 `auto_sync_enabled` 都要真，`scheduler.py:161`），`reconcile_sources` 增删 job 行——只删"本轮扫描成功"的 owner 的消失源（`repository.py:212-214`，防误删）。
2. `recover_interrupted:252`：回收上次进程留下的 running。
3. `_start_due_jobs:178`：并发上限 2（`scheduler.py:25`），逐个起 `_run_job`。
4. `_run_job:189`：认领 → 声明租约（60s，每 20s 续，`scheduler.py:23-24,232-234,271-279`；续租失败即取消持有任务）→ 同步前后各查一次 `cancel_requested`（`scheduler.py:236-250`）→ 按结果 `mark_success/_mark_failure`；`CancelledError` 区分"人为取消"与"中断"（`scheduler.py:256-262`）。
5. 取消入口：`request_cancel:295`（pending 直接置 cancelled，running 置标记位并 cancel 任务，`repository.py:461-483`）；手动重试 `retry:304`。
6. 生命周期：API 启停时挂载（`deeptutor/api/main.py:215-227`）；进程级单例 `get_web_source_sync_scheduler:312`。

## 5. 失败路径清单（改错误处理前先对照）

| # | 失败点 | 位置 | 行为 |
|---|---|---|---|
| F1 | 爬取抛异常/零页面/robots 不可用或禁爬 | `sync.py:124-131`、`crawler.py:416-423,598-602` | `ok=False`，`_record_sync_failure` 写 `last_sync_status=error`，**不推进 hashes** |
| F2 | 页面文件名越界（含旧 metadata 遗留穿越路径） | `sync.py:139-141`、`crawler.py:649` | 记 removal_errors，整体失败 |
| F3 | 删除页失败 | `sync.py:152-155` | 整体失败，不做索引 |
| F4 | 索引失败 | `sync.py:170-174` | 失败且保留旧 hashes（下轮按 updated 重试），测试 `tests/services/test_web_source_sync.py:206` |
| F5 | 删页后重建：raw 已空 / 重建零文档 | `sync.py:88,94` | RuntimeError → F4 同路 |
| F6 | metadata 写失败状态本身失败 | `sync.py:73-74` | 仅日志，同步结果不变 |
| F7 | 配对写 SQLite 失败 | `sync.py:204-205` | 静默降级（debug 日志），metadata 仍有 |
| F8 | 认领后源清单里找不到该源 | `scheduler.py:210-215` | `mark_interrupted` 保持可重试 |
| F9 | 网络瞬态 429/5xx | `crawler.py:189-190,248-258` | 指数退避重试 2 次，仍败则该页放弃（不失败整体） |
| F10 | 调度轮内任意异常 | `scheduler.py:114-115` | 记日志，下一轮继续（循环不死） |
| F11 | 配额退避 | `scheduler.py:281-293` | `min(interval, 1h×(attempt+1))`，快速前几退、最多 interval |

## 6. 双语配对、导航与快照落库

**双语配对**（`bilingual.py:129`）两遍扫描：

1. hreflang 交替链接（可信度高，`bilingual.py:147-190`）：语言取 hreflang → 页面 `lang` → URL 前缀，缺省分别兜底 `en`（`:151`）与 `zh`（`:163`）；配对方向 en 优先，否则 URL 字典序（`:167-178`）。
2. URL 语言词干分组（`bilingual.py:192-243`）：`/zh/docs/intro` 与 `/docs/zh/intro` 均能提出语言与词干（`extract_url_language_and_stem:100`）；无前缀页默认 `en`（`:209-212`）。
3. `pairing_id`=sha256("src::tgt")前 16 位去重（`:180`），结果确定性排序（`:246`）；仅收录受支持语对（`is_supported_pair:90`，未列出但含 en/zh 的对也放行 `:97`）。
4. 持久化双写：metadata.json（`sync.py:189`）+ SQLite 原子替换（`repository.py:539`）；API 暴露 `GET .../web-source/{id}/pairings`（`knowledge.py:5070`）。删源时随 job 一起删（`repository.py:222-228,500-507`）。

**导航**：侧边栏 XPath 候选按框架优先（Docusaurus/MkDocs/GitBook/Sphinx/通用，`html_extractor.py:95-115`），逐个试、取到 ≥2 链接即收（`:204-215`）；爬虫只在前两层页提取并保留最大集合（`crawler.py:319,463-467`），全无则按 URL 推断（`crawler.py:476-478`、`_infer_navigation:491`）。`flat_to_tree` 按 depth 压栈成树（`navigation.py:14`），manifest 存 `{kind, nodes}`（`navigation.py:55`）。

**快照落库（Reading 单页导入，与 KB 同步并行的一条链）**：

- `_process_web`（`deeptutor/reading/ingestion.py:252`）：抓取 → 剥来源注释（`:257`）→ `localize_snapshot_images` 把外链图片换成本地 API URL（`:258`）→ 按标题分节入库。
- 图片守卫：最多 24 张、单张 8MB、只收 PNG/JPEG/GIF/WEBP 魔数（`snapshot_assets.py:26-27,138-156`），逐跳 SSRF 校验（`:103-109`）；失败热链替换为占位文案（`:79-85`）。
- 资产经鉴权路由供给：`GET /materials/{id}/assets/{name}`（`deeptutor/api/routers/reading.py:1328`），响应前再做一次 MIME 嗅探（`:1339-1342`）。

## 7. 扩展点（加功能时找这些缝）

- **新站点框架适配**：`html_extractor.py` 三个表——内容候选 `_CONTENT_XPATHS:37`、chrome 词表 `_CHROME_NAME_PARTS:54`、侧边栏 `_SIDEBAR_XPATHS:95`；打分器 `_content_score:270` 是唯一排序逻辑。
- **新语言/语对**：`bilingual.py:15-66` 两张表（`_CANONICAL_LANGUAGES`、`SUPPORTED_LANGUAGE_PAIRS`）。
- **同步节奏/并发**：`scheduler.py:19-25` 常量组；API 入参钳制在 `WebSourceScheduleUpdate`（`knowledge.py:4930-4933`）与 `normalize_sync_interval:42` 双保险。
- **索引后端差异**：删页重建 vs 增量索引的分叉在 `sync.py:157-169`；要接支持按文档删除的提供商，改 `_rebuild_index_after_removal` 即可。
- **调度恢复语义**：全部 SQL 集中在 `repository.py`，job 状态机换存储只动这一个类。

## 8. 已知坑

1. **unchanged 判定不校验磁盘内容**：哈希比对是"远端新哈希 vs 记录旧哈希"（`crawler.py:623-636`），本地文件被截断/损坏但记录未变时，只要文件存在就当 unchanged——坏文件会一直留在 raw/索引里，直到远端内容变化。
2. **raw 写盘非原子**：`dest.write_text`（`crawler.py:651`）不是 metadata 用的 `atomic_write_json`；中途崩溃留下半截文件，与坑 1 叠加后不会被下一轮自愈。
3. **配对语言启发式可造假配对**：无语言前缀默认 `en`（`bilingual.py:209-212`）、hreflang 目标缺语言默认 `zh`（`:163`）——日文站无前缀页会被配成 en↔ja。
4. **导航"取最大集合"**（`crawler.py:463-467`）：浅层页面若带超大右侧 TOC 且被侧边栏选择器误中，会盖过真侧边栏（提取器用"≥2 链接 + 选择器顺序"缓解，`html_extractor.py:204-215`）。
5. **调度器每 15s 全量枚举**：`_synchronize_sources` 每 tick 按 owner 逐个建 manager 扫全部 KB metadata（`scheduler.py:146-176`），账户/KB 多时是 O(账户×KB) 的周期开销。
6. **CLI 同步的配对归属**：`sync.py:192-205` 用 `get_current_user()`（无上下文时回落 local-admin，`deeptutor/multi_user/context.py:22-23`）写 SQLite 配对；CLI `kb sync` 不设用户上下文，多用户部署下配对会记到 local-admin 名下而非 KB 属主（metadata.json 内不受影响）。
7. **robots fail-closed**：robots.txt 5xx/429/网络错都视为"不可用"→ 整站拒爬（`robots.py:160-166`、`crawler.py:418-420`）；但 404/4xx 视为"无限制"（`robots.py:162-163`）。敌意 crawl-delay 上限 60s（`robots.py:26,101`）。

## 9. 测试入口索引（本基线全绿：73 passed）

| 文件 | 用例数 | 覆盖 |
|---|---|---|
| `tests/services/test_web_source_sync.py`（541 行） | 26 | 链接规范化、文件名防穿越、私网重定向拦截、首同步/无变化/爬取失败记录/索引失败保 hashes、跨源同名页隔离、删页重建、导航提取/树/manifest/持久化、配对持久化 |
| `tests/services/web_source/test_sync_scheduler.py`（233 行） | 10 | repo 建行/对账/恢复/取消/重试、租约保留与过期互斥、成功排下轮、取消不被记成功、手动/停用源忽略、扫描失败保 job、长同步续租 |
| `tests/services/web_source/test_bilingual_pairing.py`（232 行） | 9 | 语言归一/语对判定/URL 词干/hreflang 提取、两种配对探测、repo CRUD、删源清理、非 web KB 隔离 |
| `tests/api/test_web_source_schedule_api.py`（156 行） | 3 | 计划默认/更新/删源清理、interval 越界拒绝、配对 API |
| `tests/knowledge/test_web_source_metadata.py`（99 行） | 6 | 注册持久/幂等/越界拒绝、删源、状态回写、跨 KB 枚举 |
| `tests/services/web_source/test_markdown.py`（58 行） | 3 | 来源注释剥离、相对链接/图片绝对化、安全图片本地化 |
| `tests/services/test_crawler_robots.py`（176 行） | 7 | robots 解析/合并/通配/转义、禁爬跳过+并发限速、缺 robots 语义、重定向按目标域取策略、robots 重定向禁私网、单次抓取+最低限速、超长 delay 忽略 |
| `tests/services/test_crawler_scope.py`（112 行） | 3 | 种子目录/根/子目录三种爬取范围 |
| `tests/reading/test_ingestion.py` | — | 网页导入图片本地化与旧修订保留（`:74`） |

复跑命令（仓库根，项目 venv）：

```bash
python -m pytest -q -p no:cacheprovider \
  tests/services/test_web_source_sync.py tests/services/web_source/ \
  tests/api/test_web_source_schedule_api.py tests/knowledge/test_web_source_metadata.py \
  tests/services/test_crawler_robots.py tests/services/test_crawler_scope.py
```

**覆盖空白（补测卡可直接引用）**：

1. `POST .../sync-web` 手动同步端点（`knowledge.py:5168`）无任何测试（tests 全树 grep 无引用）。
2. `fetch_snapshot_image` 守卫分支零直测：重定向逐跳校验、8MB 超限拒收（`snapshot_assets.py:138-144` 返回空字节）、魔数嗅探失败——现测试全走注入 fetcher（`test_markdown.py:41`、`tests/reading/test_ingestion.py:74`）。
3. `_rebuild_index_after_removal` 两个 RuntimeError 分支（`sync.py:88,94`）无直测（现测试 mock 掉重建）。
4. 续租失败 → 取消在跑任务的分支（`scheduler.py:277-279`）未测（只测了续租成功路径 `test_sync_scheduler.py:202`）。
5. `extract_article_markdown` 的内容根打分与 chrome 剥除（`html_extractor.py:270-310`）无表驱动直测，仅被导航测试间接覆盖。
6. 爬虫 `max_pages` 批中断边界（`crawler.py:424-433`）与 CLI 同步路径（`deeptutor_cli/kb.py:603`）均无测试。
