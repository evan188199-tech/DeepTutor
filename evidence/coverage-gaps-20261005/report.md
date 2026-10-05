# 零测试/弱测试模块清点与补测优先级（只读扫描，未改任何代码）

- 日期：2026-10-05
- 仓库基线：origin/main @ `f07029cfc`（release: v1.6.13）
- 方式：新 worktree `dt-agen662-covgap-wt`、新分支 `scan/coverage-gaps-20261005`，全程只读 + 静态 AST 分析；仅抽样运行 3 个单测试文件，全部限时（macOS 无 `timeout`，用 `perl -e 'alarm shift; exec @ARGV' <秒>` 等效包装）。
- 说明：任务提到的「DT-22 报告 §7」位于另一工作区看板，本运行不可达（与 evidence/review-pr-1670 复核遇到的限制相同）。风险维度以下列本地证据替代：① scan-error-msg-20261004 报告的吞错热点；② broad-except-scan-2026-10-04 报告；③ 结构性代理指标（LOC、内部反向依赖 fanin）；④ 现有 test-* 卡与开放 PR 的已知覆盖。

## 1. 统计口径（可复现）

对象：`deeptutor/` 下全部 `.py` 文件视为"模块"（`__init__.py` 单独归类）；`tests/` 下全部 `.py` 视为测试文件；`deeptutor/` 包内自带的 test 文件（`deeptutor/learning/tests/` 23 个 + `deeptutor/services/config/test_book_agent_params.py` 1 个，共 24 个）按测试文件计，不计入模块。

对应规则（两级，任一命中即计"有测试"）：
- **T1 路径对应**：测试文件名（去扩展名、按 `_` 切词）包含模块文件名主干，如 `test_config_manager.py` ↔ `core/config_manager.py`。
- **T2 导入对应**：AST 解析测试文件全部 `import` / `from ... import`（含相对导入，tests 包根解析），凡引用 `deeptutor.<模块.完整路径>` 即对应。
- 包 `__init__` 模块：任一测试导入其包前缀即计覆盖。

风险代理指标：
- **fanin**：`deeptutor/` 内部静态反向依赖数（含相对导入解析），代表被多少其他模块引用（改动波及面）。
- **风险类**：按路径/名称判定（会话核心/并发、渠道协议解析、路由契约、持久化、访问控制、RAG、纯函数），并结合两份历史扫描报告点名的文件。

复现命令（仓库根，任何机器，仅标准库）：

```bash
python3 evidence/coverage-gaps-20261005/scan_coverage_gaps.py    # 生成 coverage_raw.json
python3 evidence/coverage-gaps-20261005/aggregate.py             # 生成 summary.json
python3 evidence/coverage-gaps-20261005/assertion_sample.py      # 生成 assertion_sample.json
shasum -a 256 evidence/coverage-gaps-20261005/* > /dev/null      # 校验 SHA256SUMS
```

抽样运行（复现测试文件可运行性，均为只读跑测试）：

```bash
perl -e 'alarm shift; exec @ARGV' 300 .venv/bin/python -m pytest -q -p no:cacheprovider tests/services/config/test_readiness.py   # 13 passed in 0.54s
perl -e 'alarm shift; exec @ARGV' 300 .venv/bin/python -m pytest -q -p no:cacheprovider tests/core/test_config_manager.py         # 2 passed in 0.24s
perl -e 'alarm shift; exec @ARGV' 300 .venv/bin/python -m pytest -q -p no:cacheprovider tests/services/test_voice.py              # 68 passed in 0.40s
```

## 2. 总量与分包子包覆盖

总量：`deeptutor/` 非入口模块 874 个（不含 24 个包内测试文件）；`tests/` 测试文件 751 个 + 包内 24 个 = 775 个。

- **零测试模块（无任何 T1/T2/包内测试对应，不含 `__init__.py`）：141 个（16.1%）**
- **弱测试模块（恰好 1 个测试文件对应）：235 个**
- 文件级有测试对应的非 init 模块：733 个（83.9%）——注意此口径只代表"存在对应测试文件"，不代表分支覆盖。

| 子包 | 非 init 模块 | 有测试 | 零测试 | 零测试 LOC |
|---|---|---|---|---|
| services | 439 | 448* | 54 | 11584 |
| api | 53 | 40 | 16 | 3893 |
| tools | 31 | 22 | 14 | 2815 |
| partners | 28 | 26 | 6 | 2067 |
| book | 39 | 27 | 15 | 1668 |
| agents | 54 | 58* | 9 | 1111 |
| capabilities | 57 | 69* | 3 | 1046 |
| multi_user | 19 | 16 | 4 | 668 |
| video_learning | 6 | 5 | 2 | 445 |
| runtime | 45 | 45 | 6 | 475 |
| 其余（app/config/core/events/i18n/knowledge/learning/logging/plugins/reading/co_writer/textbook_struct/utils/visualizers/response_languages/__main__/__version__） | — | — | 26 | 1518 |

\* 有测试计数含 `__init__` 被包级导入的条目，故个别子包"有测试"可大于非 init 数；精确逐模块清单见 `coverage_raw.json`（每模块的 `t1`/`t2`/`intree_tests`/`covered` 字段）。

要点：
- `services/` 零测试 LOC 最大（11.6k，占全部零测试 LOC 的 44%），集中在 `session/turns/`、`voice/`、`memory/consolidator/modes/`、`rag/`。
- `learning/` 的 24 个包内测试（mastery 系）覆盖了包内大部分模块，但它们只测 mastery 流；`learning/assessment.py`（557 LOC，fanin 6）仅被这组包内测试间接对应，属弱对应。
- `api/` 16 个零测试模块里 9 个是路由（contract 型，补测成本低、收益高）。
- `partners/` 渠道文件普遍很大且零测试/弱断言并存（见 §4 抽样）。

## 3. 补测优先级 Top15

排序依据：零测试(2 分)/弱测试(1 分) × 风险类权重 + LOC 规模 + fanin 波及面 + 历史扫描报告点名 + 未被现有卡/PR 覆盖（去重后）。已有覆盖动作的条目不进 Top15（见 §5 去重表）。

| # | 模块 | LOC | fanin | 风险类 / 依据 | 建议卡（可拆） |
|---|---|---|---|---|---|
| 1 | `services/session/turns/executor.py` | 1422 | 1 | 会话执行核心，取消/持久化/流式交织；AGEN-605 仅覆盖取消窄路径 | test: turn executor 状态机分支（正常流/中断/异常清理） |
| 2 | `services/session/turns/request_preparer.py` | 1067 | 1 | 会话请求组装，prompt/工具定义拼装，回归影响所有对话 | test: request_preparer 组装契约（消息裁剪、工具注入边界） |
| 3 | `partners/channels/mochat.py` | 1075 | 0 | 渠道协议解析/回调，零测试 | test: mochat 消息解析与回调契约（参照 telegram PR #1776 样式） |
| 4 | `services/voice/speech_text.py` | 825 | 1 | 语音↔文本网络 IO，失败路径多 | test: speech_text 转写/合成失败与超时分支 |
| 5 | `api/routers/question_notebook.py` | 595 | 2 | 路由契约零测试，contract 型低成本高收益 | test: question_notebook 路由 CRUD/4xx 契约 |
| 6 | `api/routers/reading_extensions.py` | 498 | 1 | 路由零测试；scan-error-msg 报告 5 处吞错发现，回归风险有实据 | test: reading_extensions 路由失败可见性回归 |
| 7 | `api/routers/space_mcp.py` | 460 | 1 | 路由零测试；scan-error-msg 报告 4 处发现 | test: space_mcp 路由契约（MCP 转发失败分支） |
| 8 | `partners/channels/dingtalk.py` | 548 | 0 | 渠道协议零测试 | test: dingtalk 消息解析与签名校验中性回归 |
| 9 | `services/memory/consolidator/modes/audit.py`（+`dedup.py` 228、`_runtime.py` 319，三个 mode 全零测试） | 484 | 1/2/4 | 记忆整合三模式，一张卡可覆盖三兄弟 | test: consolidator modes 行为表驱动测试（audit/dedup/_runtime） |
| 10 | `multi_user/model_access.py` | 206 | **10** | 访问控制，fanin 全场最高档；小文件高杠杆 | test: model_access 白名单/降级边界（与 AGEN-565 路由级矩阵互补，见 §5） |
| 11 | `services/pocketbase_client.py` | 196 | 7 | 共享持久化客户端 fanin 7；PR #1773 只覆盖 `session/pocketbase_store.py`，本模块仍零测试（不同文件） | test: pocketbase_client 错误分支与重试语义 |
| 12 | `services/rag/embedding_binding.py` | 331 | 7 | RAG 绑定，fanin 7；邻接 `lightrag/indexing_policy.py`(696) 仅 1 个测试文件 | test: embedding_binding 版本/绑定失败分支 |
| 13 | `services/reading_hints.py` | 503 | 1 | 学习提示生成零直测；AGEN-637 是引用解析（邻接不重叠） | test: reading_hints 提示组装与降级 |
| 14 | `api/routers/video_learning.py` | 571 | 1 | 路由零测试；scan-error-msg 3 处发现；视频学习线已拆「学习体验」项目，建议跨项目派卡 | test: video_learning 路由契约（建议在 DeepTutor·学习体验 项目执行） |
| 15 | `tools/vision/coord_transform.py` | 436 | 1 | 纯函数坐标变换，零测试，确定性输入易测，性价比最高 | test: coord_transform 纯函数表驱动用例 |

备选观察名单（第 16-25 位，弱测试大文件，暂不拆卡）：`api/routers/mastery_path.py`(1288，仅 learning 包内测试)、`partners/channels/msteams.py`(847)、`partners/channels/matrix.py`(842)、`partners/channels/napcat.py`(594)、`services/config/readiness.py`(1038)、`services/courses_state.py`(421)、`co_writer/edit_agent.py`(409)、`tools/question/question_extractor.py`(413)、`services/session/turns/learning_adapter.py`(371)、`book/blocks/section.py`(369)。

## 4. 断言强度抽样（静态 AST，不跑全量）

抽样 15 个（模块, 覆盖测试文件）对，含 3 个近期补测卡产物作对照。完整数据：`assertion_sample.json`。

| 模块 | 测试函数 | 断言数 | 中位断言/用例 | 零断言用例 | 判定 |
|---|---|---|---|---|---|
| partners.channels.napcat | 61 | 104 | **1** | **13** | 弱：冒烟为主 |
| partners.channels.msteams | 47 | 92 | **1** | **11** | 弱：冒烟为主 |
| services.config.readiness | 13 | 47 | 4 | 0 | 中等 |
| api.routers.co_writer | 33 | 77 | 2 | 2 | 中等偏弱 |
| services.llm.provider_core.codebuddy_provider | 10 | 45 | 4 | 0 | 中等 |
| services.session.turns.lifecycle | 13 | 48 | 3 | 1 | 中等 |
| services.voice.adapters.openai_compat | 48 | 146 | 3 | 5 | 中等 |
| multi_user.device_credentials | 7 | 81 | 11 | 0 | 强 |
| services.search.source_filter | 26 | 104 | 4 | 3 | 中等 |
| learning 包内 test_mastery_tools → api.routers.mastery_path | 70 | 284 | 3 | 0 | 强（但只护 mastery 流） |
| 对照：session.sqlite_store（AGEN-634 产物） | 37 | 148 | 4 | 2 | 强 |
| 对照：events.event_bus（经 orchestrator 间接） | 17 | 42 | 2 | 0 | 中等 |
| 对照：core.config_manager | 2 | 6 | 5 | 0 | 小而强 |

结论：**渠道类（napcat/msteams）是"有测试但弱断言"的典型**——中位每用例 1 个断言、两位数零断言用例，只验"不抛异常"，不验语义。后续补测卡对渠道类应明确"断言消息语义与签名校验行为"，而非仅 smoke。近期 AGEN 系卡（sqlite_store 对照组）质量明显更高，可作为新卡模板。

## 5. 与现有 test-* 卡 / 开放 PR 去重

已存在覆盖动作、**不进 Top15** 的相关条目：

| 模块 | 已有覆盖 | 状态 |
|---|---|---|
| services/mastery_hints.py | AGEN-523 test: mastery_hints 提示组装补测 | in_review |
| tools/tex_chunker.py、tools/tex_downloader.py | AGEN-439 test: tex 工具链补测 | in_review |
| partners/channels/napcat.py（帧解析/自识别） | AGEN-592 | in_review；但 §4 显示断言仍弱，可作增强卡 |
| partners/channels/telegram 等价物 | PR #1776 telegram message parsing | open |
| quiz-judge 路由 | PR #1774 | open |
| services/session/pocketbase_store.py | PR #1773 | open；注意 ≠ `services/pocketbase_client.py`（后者进 Top15 #11） |
| memory workbench 路由 | PR #1771 / #1772 | open |
| web memory-graph 纯函数 | PR #1770 | open |
| launcher 生命周期 | PR #1769 | open |
| co-writer 路由契约 | PR #1768 | open；`co_writer/edit_agent.py` 仍零测试（备选名单） |
| ChatWorkspace 前端 smoke | PR #1767 | open |
| VisualizationViewer 前端 | PR #1749 | open |
| QuizViewer 前端 | PR #1775 | open |
| spine synthesizer | PR #1750 | open |
| markdown 显示安全 | PR #1778 | open |
| services/session/turns 取消路径 | AGEN-605 | in_review；executor 其余分支仍零测试（Top15 #1 标注窄覆盖） |
| 多用户路由级权限矩阵 | AGEN-565 | in_review；`multi_user/model_access.py` 为服务级模型门控，与其互补不重叠（Top15 #10） |
| 阅读引用解析降级 | AGEN-637 | in_review；与 `services/reading_hints.py` 邻接不重叠（Top15 #13） |
| LightRAG worker 异常可见性 / 缓存继承 | AGEN-607 / AGEN-638 | in_review；`rag/embedding_binding.py` 不在其范围（Top15 #12） |

## 6. 边界遵守

- 未修改任何产品代码；新增文件全部位于 `evidence/coverage-gaps-20261005/`。
- 未运行全量 pytest；仅 3 个单测试文件抽样运行，`perl alarm` 限时，均通过。
- 未启动服务器/守护进程；本运行无遗留子进程。
- 推送前已核对 `gh pr list -R HKUDS/DeepTutor --author @me --state open` 的 30 个分支与 `main`/`dev`，本卡分支 `scan/coverage-gaps-20261005` 不在其中。

## 7. 附带文件

- `coverage_raw.json`：全部 1029 个模块文件（含 `__init__` 与 24 个包内测试条目，聚合脚本已剔除后者）× 775 测试文件逐项对应明细（t1/t2/covered），聚合后非 init 模块 874 个。
- `summary.json`：子包聚合、零测试 Top200、弱测试 Top100、fanin Top50。
- `assertion_sample.json`：§4 抽样原始数据。
- `scan_coverage_gaps.py` / `aggregate.py` / `assertion_sample.py`：复现脚本（纯标准库）。
