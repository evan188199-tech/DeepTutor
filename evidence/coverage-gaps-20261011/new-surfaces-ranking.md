# v1.6.14 新增零覆盖/弱覆盖面排名与建议卡型（AGEN-1804，2026-10-11）

数据来源：本轮 `summary.json`（origin/main @ `6cf793bd8`）与 v1.6.13 旧版对照。排序：零覆盖按 LOC×fanin 风险；弱覆盖新面按"模块规模 × fanin ÷ 现有测试数"排序。

## 1. 新增零覆盖面（4 个，含 1 个覆盖回归）

| # | 模块 | LOC | fanin | 性质 | 风险依据 | 建议卡型 |
|---|---|---|---|---|---|---|
| 1 | `learning/visual_practice.py` | 250 | 3 | 全新模块零覆盖 | 视觉练习生成逻辑（新学习面），fanin 3 表示已被 3 处引用却无任何测试 | **test**: visual_practice 生成与降级分支补测（表驱动：素材缺失/格式异常/正常路径） |
| 2 | `services/session/workspace_preferences.py` | 50 | **6** | 覆盖回归（1→0） | fanin 6 的小文件高杠杆，旧测试对应在 v1.6.14 演进中丢失 | **regression-restore**: 恢复 workspace_preferences 覆盖（先查 v1.6.13 对应测试去向，是小卡） |
| 3 | `runtime/cache_reset.py` | 63 | 1 | 全新模块零覆盖 | 运行时缓存重置语义，误清/漏清影响面广但文件小 | **test**: cache_reset 重置边界小卡（可与既有 runtime 缓存测试合并提交） |
| 4 | `plugins/transactions.py` | 50 | 2 | 全新模块零覆盖 | 插件事务记录，与 plugins.distribution(弱) 同批落地 | **test**: transactions 行为补测（建议与 #6 distribution 增强卡同卡提交） |

## 2. 全新且弱覆盖（仅 1 个测试文件）的新面（按优先级）

| # | 模块 | LOC | fanin | 现测试 | 风险依据 | 建议卡型 |
|---|---|---|---|---|---|---|
| 1 | `knowledge/indexing_run.py` | 447 | **7** | 1 | 全新面中 fanin 最高（7 处引用），索引运行状态机单测试文件对应远不够 | **strengthen**: indexing_run 状态迁移与失败恢复分支增强（扩展现有 test_indexing_run.py，勿新开平行文件） |
| 2 | `services/research/primitives.py` | 488 | 1 | 1 | 研究基元新面，488 LOC 仅 1 测试文件 | **strengthen**: primitives 纯函数表驱动增强（输入归一化/边界值） |
| 3 | `services/rag/source_visuals.py` | 424 | 低 | 1 | RAG 视觉溯源新面，与 visual_coverage(165)/visual_assets(3 测试) 同族 | **strengthen**: source_visuals 与 visual_coverage 合并增强卡（参照 test_source_visual_grounding.py 扩展） |
| 4 | `api/routers/plugins.py` | 416 | 1 | 1 | 插件路由契约面，416 LOC 单测试文件 | **contract**: plugins 路由 CRUD/4xx 契约增强（扩展现有 test_plugins_router.py） |
| 5 | `plugins/distribution.py` | 209 | 1 | 1 | 与 transactions 同批 | **strengthen**: distribution 分发规则增强（可与 transactions 同卡） |
| 6 | `tools/learning_journal_tools.py` | 173 | 低 | 1 | learning_journal 面的工具入口层 | 观察：store/models 已有 9/6 个测试，工具层暂够用，随 learning_journal 面迭代再补 |
| 7 | `services/llm/image_replay.py` | 89 | 低 | 1 | 小文件 | 观察：暂不拆卡 |
| 8 | `api/routers/learning_journal.py` | 18 | 低 | 1 | 薄路由壳，store 层测试已间接覆盖 | 观察：暂不拆卡 |

## 3. 结论摘要

- v1.6.14 的新增面整体"带着测试落地"（12 个全新非 init 模块中 8 个有直接测试），learning_journal 服务层覆盖健康，**不是**缺口。
- 真正的新缺口集中在 4 个零覆盖小面（§1）+ indexing_run 的 fanin/测试比失衡（§2#1）。
- 最高性价比三张卡：① workspace_preferences 覆盖恢复（regression-restore，小）；② visual_practice 补测（test）；③ indexing_run 增强（strengthen，fanin 7）。
- 建议卡型说明：`test`=新补测卡；`strengthen`=扩展既有测试文件；`contract`=路由契约测试；`regression-restore`=恢复丢失的覆盖。全部卡只增测试，不动产品代码。
