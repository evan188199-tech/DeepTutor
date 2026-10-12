# myfork scan/verify 证据报告对最新 main 漂移复核（AGEN-1858，2026-10-12）

- 复核基线：`origin/main` @ `6cf793bd868ba5ecbe64722936d4be8fab5a01df`（release: v1.6.14），2026-10-12 两次 fetch（开工时与收笔前）均无前移；GitHub API `commits/main` 亦为同一 commit，`v1.6.14` 仍为 Latest release。
- 性质：只读复核。所有被抽样报告经 `git show myfork/<branch>:<evidence path>` 读取原件，未 checkout/reset/clean 任何既有工作区与分支，未修改任何台账与报告原件；本 worktree 为新建（基线 origin/main + 新分支 `verify/reports-drift-20261012`）。
- 去重：上一轮 `verify-reports-20261011`、`verify-scan-reports-drift` 覆盖的是更早窗口与其各自抽样集；本轮只抽 **20261010–20261012 产出批次**（时间窗推进），两类报告均覆盖，与上两轮抽样对象不重复。
- 关键前提：**全部 14 份抽样报告的基线 commit 与当前 origin/main 相同（6cf793bd8）**，main 侧零漂移，因此无报告因 main 前进而失效；复核重点转为"报告结论在当前 main 上逐项复现"与"报告内已登记的漂移项在 main 上是否仍未修复"。

## 一、报告 × 结论状态表（14 份：scan 8 + verify 6）

| # | 类型 | 报告（分支 → evidence 目录） | 分支头 | 报告基线 | 复核结论 | 抽查要点（均复现） |
|---|---|---|---|---|---|---|
| 1 | scan | `scan/src-fixed-delays-20261010` → `evidence/fixed-delays-2026-10-09/` | `116392e89` | `6cf793bd8` | **仍有效** | `deeptutor/agents/loop/agent_loop.py:1241` `await asyncio.sleep(15.0)`；`deeptutor/agents/math_animator/retry_manager.py:70` `asyncio.wait_for(` — 与 `fixed_delays.csv` 首行抽核一致 |
| 2 | scan | `scan/secret-defaults-20261011` → `evidence/scan-secret-defaults/` | `ad4bed0eb` | `6cf793bd8` | **仍有效** | H1：`docker-compose.yml:55,85-86` 三处端口映射仍无 loopback 前缀；M1：`deeptutor/api/main.py:95` `allow_origin_regex = None if auth_settings["enabled"] else r"https?://.*"`；M3：`deeptutor/services/partners/web_continuity.py:94` 仍为裸 `write_text`；L2：`deeptutor/services/config/runtime_settings.py:83` `"enabled": False` |
| 3 | scan | `scan/mutable-defaults-20261011` → `evidence/scan-mutable-defaults/` | `c5ffef39b` | `6cf793bd8` | **仍有效** | 轴 A 复扫仍 0 命中（rg 于 `deeptutor/`、`deeptutor_cli/`、`scripts/`）；轴 B 4 处中风险定义点逐行在位：`deeptutor/services/mcp/oauth.py:323` `_PENDING`、`deeptutor/services/pocketbase_client.py:38` `_TOKEN_CACHE`、`deeptutor/api/routers/partners.py:111` `_start_locks`、`:113` `_draft_confirm_locks` |
| 4 | scan | `scan/network-timeouts-20261011` → `evidence/scan-network-timeouts/` | `e24414e29` | `6cf793bd8` | **仍有效** | 唯一"弱"项 #20 仍成立：`deeptutor/services/subagent/opencode_family.py:69-70` 注释与 `_HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=None, write=60.0, pool=10.0)`、`:161` POST 无单呼 timeout；`deeptutor/services/search/providers/serper.py:93` requests.post + `:50` 默认 30s |
| 5 | scan | `scan/session-sqlite-growth-20261011` → `evidence/session-sqlite-growth-20261011/` | `38052a510` | `6cf793bd8` | **仍有效** | `deeptutor/services/session/sqlite_store.py` 仍为 **4612 行**（与报告声明一致）；resend 重指向区入口 `:1179` `def _reserve_submission_sync(` 在位 |
| 6 | scan | `scan/print-console-residue-20261011` → `evidence/agen-1787-print-console-scan/` | `01dfc654b` | `6cf793bd8` | **仍有效** | `deeptutor/tools/question/question_extractor.py` 仍精确 **26 处 `print(`**；生产回退调用链 `deeptutor/agents/question/mimic_source.py:117` `extract_questions_from_paper(` 在位 |
| 7 | scan | `scan/hardcode-paths-20261011` → `evidence/scan-hardcode-paths/` | `cbccd6d69` | `6cf793bd8` | **仍有效** | P0 #1：`deeptutor/knowledge/manager.py:328` `base_dir="./data/knowledge_bases"` 默认值仍在；#2：`deeptutor/knowledge/add_documents.py:39` `DEFAULT_BASE_DIR` 同字面量；P2 #6：`deeptutor/services/setup/init.py:47` `"allowed_roots": ["./data/user"]` 仍为 cwd 相对 |
| 8 | scan | `scan/web-locale-keys-20261011` → `evidence/scan-web-locale-keys/` | `66919d8bc` | `6cf793bd8` | **仍有效** | fr 缺失键抽查：`Add a note for this segment`（使用点 `web/components/knowledge/KbIndexingRun.tsx`）en 有/fr 无；`Learning journal`（LearningJournalPanel.tsx 轴）同样 en 有/fr 无；`web/locales/fr/app.json` 仍缺 |
| 9 | verify | `verify/guide-anchors-20261011` → `evidence/verify-guide-anchors-20261011/` | `3ed8e5e18` | `6cf793bd8` | **仍有效** | 全报告唯一"失效"项复现：`entrypoint.sh` 在当前 main 根目录不存在（worktree 实测 no such file） |
| 10 | verify | `evidence/verify-readme-assets-20261011` → `evidence/readme-refs-20261011/` | `e6a9cafce` | `6cf793bd8` | **仍有效** | `assets/figs/web-1.4.6+/home/00-overview.png` 在位；README.md 中 `web-1.4.6+` 引用仍 19 行（=报告 19 distinct targets 口径），outdated-dir 引用未被清理 |
| 11 | verify | `evidence/verify-web-locale-parity-20261011` → `evidence/verify-web-locale-parity-20261011/` | `766fef07e` | `6cf793bd8` | **仍有效** | fr 占位键仍在：`web/locales/fr/app.json:5879` `"settings.providerServices.filter.imagegen": "Images"`（与 en 相同）；fr 窗口缺失轴与 #8 报告交叉一致 |
| 12 | verify | `evidence/verify-seeds-fresh-20261011` → `evidence/verify-seeds-fresh-20261011/` | `d3b8e2ec4` | `6cf793bd8` | **仍有效** | 看板侧抽查 4 张领取卡：AGEN-1767（FT46）、AGEN-1770（FT75）、AGEN-1776（FT129）、AGEN-1780（FZ95）当日仍为 **in_review**，与报告"已被建卡、in_review"结论一致，无回退 |
| 13 | verify | `evidence/verify-docs-anchors-20261012` → `evidence/`（anchor_report.md 等） | `c184ccda3` | `6cf793bd8` | **仍有效** | 失效锚点"现状"逐字复现：`deeptutor/agents/_shared/tool_composition.py:262-271` 常开元组现含 `learning_status`/`learning_update` 共 7 件；`deeptutor/api/routers/knowledge.py:4429` `async def websocket_progress(...)` 与报告登记的 +173 位移一致 |
| 14 | verify | `evidence/verify-v1614-metadata-parity-20261012` → `evidence/verify-v1614-metadata-parity-20261012/` | `dfe607d4b` | `6cf793bd8` | **仍有效** | `deeptutor/__version__.py:9` = `1.6.14`；CITATION.cff 仍 0 处 `version:/date-released:/doi:`（其登记的唯一漂移项在 main 上仍未修复）；`compose.yaml:138` 仍 `ghcr.io/hkuds/deeptutor:latest`；上游 v1.6.14 仍为 Latest release |

## 二、结论汇总

- **仍有效 14 / 漂移 0 / 失效 0**（相对当前 origin/main `6cf793bd8`）。
- 零漂移的成因是结构性的：本轮抽样批次全部锚定 `6cf793bd8`（v1.6.14），且 2026-10-12 当日 origin/main 未前进——即报告窗口与对照窗口重合。下轮若 main 前进（v1.6.15+），本表即为漂移检测的零点基线。
- 报告**内部已登记的待修漂移项在 main 上仍未修复**（维持原状而非新增漂移）：
  - `CITATION.cff` 缺 `version`/`date-released`（verify-v1614-metadata-parity 登记项）
  - `docker-compose.yml:55,85-86` 端口映射无 loopback 前缀（scan-secret-defaults H1）
  - `deeptutor/services/subagent/opencode_family.py:70` read=None 弱超时（scan-network-timeouts #20）
  - `deeptutor/knowledge/manager.py:328` 等 7 处 cwd 相对默认路径（scan-hardcode-paths 迁移候选）
  - `web/locales/fr/app.json` 仍缺 59 使用键 / 63 窗口键（scan-web-locale-keys、verify-web-locale-parity 交叉一致）
- verify-seeds-fresh 的看板依赖结论经 4 卡抽查未见回退（仍 in_review）；看板属外部状态，其时效以当日查询为准。

## 三、方法与复跑

- 报告原件读取：`git show myfork/<branch>:<evidence path>`（只读）；对照基线为本地新建 worktree（origin/main `6cf793bd8` + 分支 `verify/reports-drift-20261012`）。
- 抽查口径：每份报告抽 1–4 条核心结论（高频 path:line 或可计数断言），在对照 worktree 以 `sed -n` / `grep -c` 复现；计数类断言（4612 行、26 处 print、19 引用、0 字段）全部精确复现。
- 外部状态：GitHub API `commits/main`、`releases`（v1.6.14 Latest）；看板 4 卡状态经平台查询。
- 本目录仅新增 `summary.md` 与 `SHA256SUMS`，校验和：`shasum -a 256 summary.md > SHA256SUMS`（自校验见文件内首行）。
