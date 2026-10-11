# 弱覆盖 top100 复triage：v1.6.13 → v1.6.14 差异表（AGEN-1804，2026-10-11）

- 旧基线：origin/main @ `f07029cfc`（v1.6.13），证据 = myfork 分支 `scan/coverage-gaps-det-20261006` 的 `evidence/coverage-gaps-20261005/summary.json`（确定性重生成版，AGEN-873 修复后口径）。
- 新基线：origin/main @ `6cf793bd8`（release: v1.6.14），worktree `dt-agen1804-wt`，只读扫描；本目录 `coverage_raw.json` / `summary.json` / `scan_coverage_gaps.py` / `aggregate.py` 为本轮产物。产品代码与测试零改动（分支只涉及 `evidence/coverage-gaps-20261011/`）。
- 口径不变：T1 路径对应 + T2 精确点分导入对应（确定性，PYTHONHASHSEED 无关）；weak = 恰好 1 个覆盖测试文件（tests/ + 包内）；zero = 无任何对应。

## 1. 总量对照

| 指标 | v1.6.13（旧） | v1.6.14（新） | 变化 |
|---|---|---|---|
| 模块文件（raw 含 init 与包内测试） | 1005 | 1055 | +50 |
| 测试文件（tests/ + 包内） | 775 | 803 | +28 |
| 非 init 模块 | 874 | 911 | +37 |
| zero_noninit | 96 | 93 | −3 |
| weak_single_test | 242 | 240 | −2 |

结论：v1.6.14 新增 37 个非 init 模块的同时，零覆盖与弱覆盖净量双降，整体覆盖面在改善；但新增面内部结构分化（见 §3 与 `new-surfaces-ranking.md`）。

## 2. weak_top100 三类差异（移除 / 新增 / 位移）

### 2.1 移除（6 个，全部因覆盖改善，非代码删除）

| 旧 # | 模块 | LOC（旧） | 移除原因 | 现覆盖测试 |
|---|---|---|---|---|
| 2 | api.routers.co_writer | 874 | 1 → 2 个测试 | tests/api/routers/test_co_writer_contract.py、tests/api/test_co_writer.py |
| 6 | co_writer.docx_converter | 667 | 1 → 2 | 同上（契约测试连带） |
| 27 | co_writer.edit_agent | 409 | 1 → 2 | 同上 |
| 30 | services.rag.visual_assets | 386 | 1 → 3 | test_agent_loop.py、test_source_visual_grounding.py、test_visual_assets.py |
| 69 | reading.epub_bilingual | 248 | 1 → 2 | tests/reading/test_epub_bilingual.py、test_epub_bilingual_units.py |
| 91 | utils.document_validator | 206 | 1 → 2 | test_knowledge_upload_guards.py、tests/utils/test_document_validator.py |

co-writer 三件套（路由/转换器/edit_agent）由同一张契约测试卡连带清出，曾列旧榜 #2/#6/#27，是本轮榜单头部最大的移除来源。

### 2.2 新增（6 个，3 类来源）

| 新 # | 模块 | LOC | fanin | 来源 | 现覆盖 |
|---|---|---|---|---|---|
| 16 | services.research.primitives | 488 | 1 | v1.6.14 全新模块 | 仅 tests/services/research/test_primitives.py |
| 23 | knowledge.indexing_run | 447 | **7** | v1.6.14 全新模块 | 仅 tests/knowledge/test_indexing_run.py |
| 26 | api.routers.plugins | 416 | 1 | v1.6.14 全新模块 | 仅 tests/api/test_plugins_router.py |
| 39 | tools.tex_chunker | 341 | 0 | 零→弱（补测落地） | tests/tools/test_tex_tools.py |
| 66 | tools.tex_downloader | 256 | 0 | 零→弱（补测落地） | 同上 |
| 90 | plugins.distribution | 209 | 1 | v1.6.14 全新模块 | 仅 tests/plugins/test_distribution.py |

4 个全新模块自带 1 个测试文件入榜（属"搭车测试"，单文件对应整模块）；tex 双件从零覆盖名单移入弱覆盖名单（对应 AGEN-439 一线补测卡的落地）。

### 2.3 位移（25 个共现模块排名变动，最大 |Δ|=7）

头部前 12 名对照（全表逐模块见两版 summary.json）：

| 新 # | 旧 # | 模块 | LOC 旧→新 | fanin |
|---|---|---|---|---|
| 1 | 1 | services.config.readiness | 1038→1038 | 1 |
| 2 | 5 | services.llm.provider_core.codebuddy_provider | 839→851 | 3 |
| 3 | 3 | partners.channels.msteams | 847→847 | 0 |
| 4 | 4 | partners.channels.matrix | 842→842 | 0 |
| 5 | 7 | api.routers.question_notebook | 595→595 | 2 |
| 6 | 8 | partners.channels.napcat | 594→594 | 0 |
| 7 | 9 | services.search.source_filter | 582→582 | 1 |
| 8 | 10 | services.doctor | 571→571 | 0 |
| 9 | 11 | learning.assessment | 557→558 | 6 |
| 10 | 12 | tools.question_bank | 536→536 | 1 |
| 11 | 13 | api.routers.partner_groups | 534→534 | 1 |
| 12 | 14 | services.subagent.opencode_family | 508→508 | 1 |

显著位移：

- `services.llm.provider_core.codebuddy_provider` #5→**#2**：文件 839→851 LOC 继续增长，叠加 co_writer(#2) 移出榜单后上浮；仍是弱覆盖大文件。
- `services.workspace.dependencies` #37→**#30**（Δ=−7，全场最大位移）：LOC 349→**390**（+41），文件在长大但仍只有 1 个测试文件，建议关注。
- 其余 23 个模块位移在 ±2 以内，属榜单头部移除后的自然挤位，无状态变化。

## 3. 零覆盖名单变动（96 → 93）

移出 7 个（补测落地）：

| 模块 | 现覆盖 |
|---|---|
| tools.tex_chunker / tools.tex_downloader | tests/tools/test_tex_tools.py |
| services.llm.provider_core.github_copilot_provider | 3 个测试（含专测 test_github_copilot_provider.py） |
| services.session.turns.title_service | tests/app/test_turn_application_service.py |
| services.llm.cloud_provider | tests/api/test_github_copilot_models.py |
| services.base_sync | tests/services/test_github_source_unchanged_sync.py |
| api.utils.progress_broadcaster | tests/api/test_knowledge_progress_ws.py |

移入 4 个（详见 `new-surfaces-ranking.md`）：

| 模块 | LOC | fanin | 来源 |
|---|---|---|---|
| learning.visual_practice | 250 | 3 | v1.6.14 全新模块，零覆盖 |
| runtime.cache_reset | 63 | 1 | v1.6.14 全新模块，零覆盖 |
| services.session.workspace_preferences | 50 | 6 | 覆盖回归（1 → 0） |
| plugins.transactions | 50 | 2 | v1.6.14 全新模块，零覆盖 |

## 4. 新增面核对（卡面点名的 learning_journal / indexing_run）

- `services.learning_journal.*`（v1.6.14 全新子包）：store(368 LOC) 9 个覆盖测试、models(143) 6 个，**不属覆盖缺口**；薄弱点仅在入口层 `api.routers.learning_journal`(18 LOC, 1 测试) 与 `tools.learning_journal_tools`(173 LOC, 1 测试)。
- `knowledge.indexing_run`(447 LOC)：全新模块且 **fanin=7（新面中最高）**，仅 1 个测试文件对应，是本轮最值得补强的新面（建议见 ranking 文件）。
- `runtime.coordination.journal`(97 LOC)：非新增，覆盖反而在改善（1 → 4 个测试）。

## 5. 复现命令（仓库根，仅标准库）

```bash
python3 evidence/coverage-gaps-20261011/scan_coverage_gaps.py   # 生成 coverage_raw.json
python3 evidence/coverage-gaps-20261011/aggregate.py            # 生成 summary.json
shasum -a 256 evidence/coverage-gaps-20261011/*                 # 校验 SHA256SUMS
```

## 6. 边界遵守

- 未修改任何产品代码；新增文件全部位于 `evidence/coverage-gaps-20261011/`。
- 未运行任何 pytest（本卡验收要求"不跑全量测试套"，本扫描为纯静态 AST，无测试执行需求）。
- 未启动服务器/守护进程；本运行无遗留子进程。
- 推送前已核对 `gh pr list -R HKUDS/DeepTutor --author @me --state open` 的 4 个分支与 `main`/`dev`，本卡分支 `scan/coverage-gaps-20261011` 不在其中。
