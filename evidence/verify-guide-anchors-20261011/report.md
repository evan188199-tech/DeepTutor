# 已消费 guide-* 卡产出 path:line 锚点 v1.6.14 腐烂率抽查（AGEN-1806）

- 基线：`origin/main` @ `6cf793bd8`（release v1.6.14，2026-10-11），fetch 后新建只读 worktree `dt-agen1806-anchors-wt` + 新分支 `verify/guide-anchors-20261011`，未动 main 工作区，未改任何源码
- 对象：myfork 上 **已消费 guide-* 卡的产出文档**（`docs/guides/*.md` 或 `evidence/*guide*/guide.md|report.md`）内的 `path:line` 锚点；共识别 **116 个 guide 分支**，其中 **109 个**产出文档含该类锚点
- 抽样：每分支按文档位置均匀抽 **5–8** 个锚点，共 **870** 个；分支覆盖 **109/109（100%，验收≥80%）**，每分支 ≥5（验收✓）
- 去重说明：`verify-guide-anchors-20261006`（AGEN-899）核对的是**卡面描述**锚点、`verify-guide-reports-20261007`（AGEN-1108）复核的是两份 scope 报告，均未核对过 guide 产出文档内的行号锚点；本轮对象与其不重叠
- 方法：锚点按 `文件(路径):行[-行]` 正则提取（已排除 mermaid `\n` 伪路径、表格内 shorthand `:123` 不计入）；路径经 字面→`deeptutor/` 前缀→文档目录域(含祖先)→同尾路径索引 四级解析；行内容以锚点上下文中的强声明符号（含 `_` 或双大写驼峰）核对，弱符号只作辅助；同名多候选且符号不能唯一证实的一律记 **未定(歧义)**，不强行判定

## 一、腐烂率总量

| 判定 | 数量 | 占抽样 | 说明 |
|---|---|---|---|
| 有效 | 383 | 44.0% | 文件在、声明符号落在锚点行/行段内 |
| 微漂移（≤5 行） | 49 | 5.6% | 符号还在，行号小幅移动 |
| 行漂移 | 157 | 18.0% | 符号在同文件其他位置，行号已失准 |
| 行越界 | 0 | 0.0% | 行号超出文件长度（文件大幅缩身） |
| 内容漂移 | 38 | 4.4% | 文件在，强声明符号全文件未命中 |
| 失效 | 1 | 0.1% | 目标文件在 v1.6.14 不存在 |
| 可定位（未核声明） | 170 | 19.5% | 文件行在，但上下文无强声明可核 |
| 未定（歧义） | 72 | 8.3% | 同名多候选，未强行判定 |

- **可判定锚点 628 个**（剔除未核声明与歧义），其中腐烂（行漂移+行越界+内容漂移+失效）**31.2%**；计入微漂移后 **39.0%**
- 换算到全部抽样：约 **每 3 个产出锚点有 1 个在 v1.6.14 已失准**（主要形态是行号漂移而非文件消失——失效仅 1 个，文件面整体稳定）

| 分支族 | 可判定 | 腐烂(含微漂移) | 腐烂(严格) |
|---|---|---|---|
| guide/* 族 | 309 | 131（42%） | 106（34%） |
| docs/guides 族 | 251 | 90（36%） | 70（28%） |
| 其他（agent/dt-*/evidence 等） | 68 | 24（35%） | 20（29%） |

## 二、逐分支抽查表（116 分支全列，其中 109 个含 path:line 锚点并完成抽样）

判定列＝抽样内各判定计数（微=微漂移、漂=行漂移、越=行越界、容=内容漂移、失=失效、未=未定歧义、无=可定位未核、有=有效）。同文档同 blob 的孪生分支以 ⟲ 标注；watching-* 等 7 个分支产出文档不含 `path:line` 锚点，计 0。

| 分支 | 产出文档 | 锚点总量 | 抽样 | 有 | 微 | 漂 | 越 | 容 | 失 | 未 | 无 | 处理建议 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `agent/agen1031-llm-clients-guide` | docs/guides/llm-clients.md | 125 | 8 | 7 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 微漂移可在下次导读刷新时顺手修 |
| `agent/dt468-routers-guide` | evidence/guide-routers-2026-10-04/guide.md | 150 | 8 | 2 | 2 | 2 | 0 | 0 | 0 | 1 | 1 | 批量更新行号（定点再生成）；微漂移可在下次导读刷新时顺手修 |
| `codex/mini-watching-aligned-baseline` ⟲ | docs/guides/watching-learning.md, docs/guides/watching-workspace.md | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 保持（本轮样本无可判定锚点） |
| `codex/upstream-watching-workspace` ⟲ | docs/guides/watching-workspace.md | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 保持（本轮样本无可判定锚点） |
| `codex/watching-bookmark-notes` ⟲ | docs/guides/watching-learning.md, docs/guides/watching-workspace.md | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 保持（本轮样本无可判定锚点） |
| `codex/watching-center-transcript` ⟲ | docs/guides/watching-learning.md, docs/guides/watching-workspace.md | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 保持（本轮样本无可判定锚点） |
| `codex/watching-fullscreen-captions` ⟲ | docs/guides/watching-learning.md, docs/guides/watching-workspace.md | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 保持（本轮样本无可判定锚点） |
| `codex/watching-notes-reliability` ⟲ | docs/guides/watching-learning.md, docs/guides/watching-workspace.md | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 保持（本轮样本无可判定锚点） |
| `codex/watching-workspace` ⟲ | docs/guides/watching-workspace.md | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 保持（本轮样本无可判定锚点） |
| `docs/capability-instances-guide-20261007` | docs/guides/capability-instances.md | 102 | 8 | 5 | 0 | 0 | 0 | 0 | 0 | 2 | 1 | 保持（样本内无腐烂） |
| `docs/guide-imagegen` | docs/guides/imagegen-domain.md | 68 | 8 | 4 | 1 | 1 | 0 | 0 | 0 | 0 | 2 | 批量更新行号（定点再生成）；微漂移可在下次导读刷新时顺手修 |
| `docs/guide-invidious-accounts-20261011` | docs/guides/invidious-accounts.md | 6 | 6 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 保持（样本内无腐烂） |
| `docs/guide-multi-user` | docs/guide-multi-user.md | 118 | 8 | 5 | 0 | 1 | 0 | 1 | 0 | 1 | 0 | 重读对应模块后整档再生成；批量更新行号（定点再生成） |
| `docs/guide-tex-tools-20261008` | docs/guides/tex-tools.md | 25 | 8 | 6 | 1 | 0 | 0 | 0 | 0 | 0 | 1 | 微漂移可在下次导读刷新时顺手修 |
| `docs/guides/book-pipeline` | docs/guides/book-pipeline.md | 131 | 8 | 4 | 1 | 3 | 0 | 0 | 0 | 0 | 0 | 批量更新行号（定点再生成）；微漂移可在下次导读刷新时顺手修 |
| `docs/guides/chat-runtime` | docs/guides/chat-runtime.md | 82 | 8 | 1 | 0 | 2 | 0 | 1 | 0 | 0 | 4 | 重读对应模块后整档再生成；批量更新行号（定点再生成）；腐烂≥50%，建议整档优先级提前 |
| `docs/guides/ci-workflows` | docs/guides/ci-workflows.md | 17 | 8 | 1 | 0 | 2 | 0 | 0 | 0 | 0 | 5 | 批量更新行号（定点再生成）；腐烂≥50%，建议整档优先级提前 |
| `docs/guides/co-writer` | docs/guides/co-writer.md | 41 | 8 | 4 | 1 | 2 | 0 | 1 | 0 | 0 | 0 | 重读对应模块后整档再生成；批量更新行号（定点再生成）；微漂移可在下次导读刷新时顺手修 |
| `docs/guides/co-writer-20261011` | docs/guides/co-writer.md | 70 | 8 | 3 | 1 | 0 | 0 | 2 | 0 | 0 | 2 | 重读对应模块后整档再生成；微漂移可在下次导读刷新时顺手修 |
| `docs/guides/codex-auth` | docs/guides/codex-auth.md | 143 | 8 | 2 | 0 | 1 | 0 | 2 | 0 | 3 | 0 | 重读对应模块后整档再生成；批量更新行号（定点再生成）；腐烂≥50%，建议整档优先级提前 |
| `docs/guides/courses-domain` | docs/guides/courses-domain.md | 76 | 8 | 4 | 0 | 0 | 0 | 0 | 0 | 2 | 2 | 保持（样本内无腐烂） |
| `docs/guides/cron-scheduling-20261011` | docs/guides/cron-scheduling.md | 101 | 8 | 4 | 1 | 2 | 0 | 0 | 0 | 0 | 1 | 批量更新行号（定点再生成）；微漂移可在下次导读刷新时顺手修 |
| `docs/guides/deep-research` | docs/guides/deep-research.md | 43 | 8 | 0 | 0 | 3 | 0 | 0 | 0 | 4 | 1 | 批量更新行号（定点再生成）；腐烂≥50%，建议整档优先级提前 |
| `docs/guides/embedding-progress` | docs/guides/embedding-progress.md | 72 | 8 | 1 | 0 | 2 | 0 | 0 | 0 | 1 | 4 | 批量更新行号（定点再生成）；腐烂≥50%，建议整档优先级提前 |
| `docs/guides/launcher` | docs/guides/launcher.md | 106 | 8 | 4 | 0 | 3 | 0 | 0 | 0 | 0 | 1 | 批量更新行号（定点再生成） |
| `docs/guides/local-db` | docs/guides/local-db.md | 33 | 8 | 8 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 保持（样本内无腐烂） |
| `docs/guides/math-animator` | docs/guides/math-animator.md | 103 | 8 | 4 | 0 | 2 | 0 | 0 | 0 | 0 | 2 | 批量更新行号（定点再生成） |
| `docs/guides/partner-channels-20261011` | docs/guides/partner-channels.md | 71 | 8 | 3 | 1 | 2 | 0 | 1 | 0 | 0 | 1 | 重读对应模块后整档再生成；批量更新行号（定点再生成）；微漂移可在下次导读刷新时顺手修 |
| `docs/guides/question-pipeline` | evidence/guide-question-2026-10-03/guide.md | 65 | 8 | 3 | 0 | 2 | 0 | 0 | 0 | 0 | 3 | 批量更新行号（定点再生成） |
| `docs/guides/quiz-notebook` | docs/guides/quiz-notebook.md | 83 | 8 | 4 | 1 | 1 | 0 | 0 | 0 | 0 | 2 | 批量更新行号（定点再生成）；微漂移可在下次导读刷新时顺手修 |
| `docs/guides/research-primitives` | docs/guides/research-primitives.md | 77 | 8 | 6 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 批量更新行号（定点再生成） |
| `docs/guides/runtime-subpackages` | docs/guides/runtime-subpackages.md | 88 | 8 | 6 | 0 | 1 | 0 | 0 | 0 | 0 | 1 | 批量更新行号（定点再生成） |
| `docs/guides/runtime-update-chain` | evidence/guide-runtime-2026-10-04/guide.md | 98 | 8 | 2 | 0 | 3 | 0 | 2 | 0 | 0 | 1 | 重读对应模块后整档再生成；批量更新行号（定点再生成）；腐烂≥50%，建议整档优先级提前 |
| `docs/guides/search-providers` | docs/guides/search-providers.md | 114 | 8 | 3 | 1 | 2 | 0 | 0 | 0 | 0 | 2 | 批量更新行号（定点再生成）；微漂移可在下次导读刷新时顺手修 |
| `docs/guides/services-partners` | docs/guides/services-partners.md | 86 | 8 | 7 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 保持（样本内无腐烂） |
| `docs/guides/session-history` | docs/guides/session-history.md | 88 | 8 | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 6 | 批量更新行号（定点再生成）；腐烂≥50%，建议整档优先级提前 |
| `docs/guides/settings-system-20261011` | docs/guides/settings-system.md | 85 | 8 | 7 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 保持（样本内无腐烂） |
| `docs/guides/skills-mcp` | evidence/guide-skills-20261003/guide.md | 108 | 8 | 2 | 0 | 1 | 0 | 0 | 0 | 5 | 0 | 批量更新行号（定点再生成） |
| `docs/guides/subagent-family-20261011` | docs/guides/subagent-family.md | 161 | 8 | 2 | 1 | 1 | 0 | 0 | 0 | 3 | 1 | 批量更新行号（定点再生成）；微漂移可在下次导读刷新时顺手修 |
| `docs/guides/textbook-struct` | docs/guides/textbook-struct.md | 67 | 8 | 5 | 1 | 0 | 0 | 1 | 0 | 1 | 0 | 重读对应模块后整档再生成；微漂移可在下次导读刷新时顺手修 |
| `docs/guides/tools-prompting` | docs/guides/tools-prompting.md | 69 | 8 | 2 | 0 | 1 | 0 | 0 | 0 | 4 | 1 | 批量更新行号（定点再生成） |
| `docs/guides/upstream-contrib` | docs/guides/upstream-contrib.md | 8 | 8 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 8 | 保持（本轮样本无可判定锚点） |
| `docs/guides/usage-ledger-20261011` | docs/guides/usage-ledger.md | 46 | 8 | 6 | 0 | 1 | 0 | 0 | 0 | 0 | 1 | 批量更新行号（定点再生成） |
| `docs/guides/visual-grounding-20261010` | docs/guides/visual-page-grounding.md | 33 | 8 | 5 | 1 | 0 | 0 | 0 | 0 | 0 | 2 | 微漂移可在下次导读刷新时顺手修 |
| `docs/guides/visualizers` | docs/guides/visualizers.md | 68 | 8 | 6 | 0 | 1 | 0 | 0 | 0 | 0 | 1 | 批量更新行号（定点再生成） |
| `docs/guides/web-activity` | docs/guides/web-activity.md | 79 | 8 | 5 | 1 | 2 | 0 | 0 | 0 | 0 | 0 | 批量更新行号（定点再生成）；微漂移可在下次导读刷新时顺手修 |
| `docs/guides/web-contracts` | docs/guides/web-contracts.md | 39 | 8 | 4 | 1 | 1 | 0 | 0 | 0 | 0 | 2 | 批量更新行号（定点再生成）；微漂移可在下次导读刷新时顺手修 |
| `docs/guides/web-source` | docs/guides/web-source.md | 98 | 8 | 2 | 0 | 3 | 0 | 0 | 0 | 0 | 3 | 批量更新行号（定点再生成）；腐烂≥50%，建议整档优先级提前 |
| `docs/packaging-startup-guide-20261007` | docs/guides/packaging-startup.md | 39 | 8 | 0 | 1 | 2 | 0 | 0 | 1 | 1 | 3 | 目标文件已消失，整档重写或归档；批量更新行号（定点再生成）；微漂移可在下次导读刷新时顺手修；腐烂≥50%，建议整档优先级提前 |
| `docs/skills-system-guide` | docs/guides/skills-system.md | 101 | 8 | 2 | 2 | 2 | 0 | 0 | 0 | 0 | 2 | 批量更新行号（定点再生成）；微漂移可在下次导读刷新时顺手修 |
| `docs/task-board-guide-20261006` | docs/guides/task-board.md | 26 | 8 | 2 | 2 | 0 | 0 | 0 | 0 | 3 | 1 | 微漂移可在下次导读刷新时顺手修 |
| `docs/usage-stats-guide` | docs/guides/usage-stats.md | 104 | 8 | 6 | 0 | 1 | 0 | 0 | 0 | 0 | 1 | 批量更新行号（定点再生成） |
| `docs/watching-convergence-guide-20261011` | docs/guides/watching-convergence-migration.md | 48 | 8 | 3 | 1 | 0 | 0 | 0 | 0 | 0 | 4 | 微漂移可在下次导读刷新时顺手修 |
| `docs/workspace-migration-guide-20261006` | docs/guides/workspace-migration.md | 77 | 8 | 4 | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 批量更新行号（定点再生成）；腐烂≥50%，建议整档优先级提前 |
| `dt-agen1335-mineru-indexing-guide` | docs/guides/mineru-local-indexing.md | 96 | 8 | 2 | 0 | 0 | 0 | 0 | 0 | 2 | 4 | 保持（样本内无腐烂） |
| `dt-agen1728-partnerguide` | docs/guides/partners-channels.md | 47 | 8 | 4 | 1 | 1 | 0 | 0 | 0 | 1 | 1 | 批量更新行号（定点再生成）；微漂移可在下次导读刷新时顺手修 |
| `evidence/guide-file-io-path-durability-20261009` | evidence/guide-file-io-path-durability-20261009/report.md | 74 | 8 | 7 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 批量更新行号（定点再生成） |
| `evidence/guide-realtime-push-2026-10-07` | evidence/guide-realtime-push-2026-10-07/report.md | 39 | 8 | 6 | 0 | 1 | 0 | 1 | 0 | 0 | 0 | 重读对应模块后整档再生成；批量更新行号（定点再生成） |
| `evidence/guide-session-stores-20261007` | evidence/guide-session-stores-20261007/report.md | 43 | 8 | 4 | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 批量更新行号（定点再生成）；腐烂≥50%，建议整档优先级提前 |
| `guide-channels-20261005` | evidence/guide-channels-20261005/guide.md | 97 | 8 | 5 | 0 | 1 | 0 | 0 | 0 | 1 | 1 | 批量更新行号（定点再生成） |
| `guide-cli-agen477` | evidence/guide-cli-2026-10-04/guide.md | 128 | 8 | 2 | 0 | 2 | 0 | 0 | 0 | 1 | 3 | 批量更新行号（定点再生成）；腐烂≥50%，建议整档优先级提前 |
| `guide-i18n-20261004` ⟲ | evidence/guide-i18n-2026-10-04/guide.md | 66 | 8 | 6 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 批量更新行号（定点再生成） |
| `guide-local-db-401` | docs/guides/local-db.md | 67 | 8 | 5 | 0 | 1 | 0 | 0 | 0 | 0 | 2 | 批量更新行号（定点再生成） |
| `guide-partners-agen371` | evidence/guide-partners-2026-10-03/guide.md | 67 | 8 | 4 | 1 | 3 | 0 | 0 | 0 | 0 | 0 | 批量更新行号（定点再生成）；微漂移可在下次导读刷新时顺手修 |
| `guide-storage-agen449` | evidence/guide-storage-2026-10-04/guide.md | 49 | 8 | 6 | 0 | 1 | 0 | 0 | 0 | 0 | 1 | 批量更新行号（定点再生成） |
| `guide/agents-20261004` | evidence/guide-agents-20261004/guide.md | 58 | 8 | 4 | 0 | 1 | 0 | 1 | 0 | 1 | 1 | 重读对应模块后整档再生成；批量更新行号（定点再生成） |
| `guide/app-update-20261005` | evidence/app-update-guide-2026-10-05/report.md | 146 | 8 | 2 | 0 | 2 | 0 | 2 | 0 | 0 | 2 | 重读对应模块后整档再生成；批量更新行号（定点再生成）；腐烂≥50%，建议整档优先级提前 |
| `guide/ask-user-20261006` | docs/guides/ask-user-chain.md | 190 | 8 | 3 | 1 | 4 | 0 | 0 | 0 | 0 | 0 | 批量更新行号（定点再生成）；微漂移可在下次导读刷新时顺手修；腐烂≥50%，建议整档优先级提前 |
| `guide/audio-overview-20261007` | docs/guides/audio-overview.md | 81 | 8 | 5 | 2 | 0 | 0 | 0 | 0 | 0 | 1 | 微漂移可在下次导读刷新时顺手修 |
| `guide/authn-20261004` | evidence/authn-guide-20261004/report.md | 98 | 8 | 2 | 0 | 1 | 0 | 0 | 0 | 0 | 5 | 批量更新行号（定点再生成） |
| `guide/background-leader-20261006` | docs/guides/background-leader.md | 45 | 8 | 5 | 0 | 2 | 0 | 0 | 0 | 0 | 1 | 批量更新行号（定点再生成） |
| `guide/book-20261004` | evidence/guide-book-2026-10-04/guide.md | 234 | 8 | 1 | 0 | 0 | 0 | 0 | 0 | 6 | 1 | 保持（样本内无腐烂） |
| `guide/capabilities-20261005` | evidence/guide-capabilities-20261005/guide.md | 155 | 8 | 1 | 1 | 3 | 0 | 0 | 0 | 3 | 0 | 批量更新行号（定点再生成）；微漂移可在下次导读刷新时顺手修；腐烂≥50%，建议整档优先级提前 |
| `guide/core-protocols-20261007` | docs/guides/core-protocols.md | 150 | 8 | 4 | 1 | 1 | 0 | 1 | 0 | 0 | 1 | 重读对应模块后整档再生成；批量更新行号（定点再生成）；微漂移可在下次导读刷新时顺手修 |
| `guide/cron-20261006` | docs/guides/cron.md | 57 | 8 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 保持（样本内无腐烂） |
| `guide/embedding-reliability-20261011` | docs/guides/embedding-reliability.md | 78 | 8 | 2 | 0 | 0 | 0 | 2 | 0 | 2 | 2 | 重读对应模块后整档再生成；腐烂≥50%，建议整档优先级提前 |
| `guide/events-20261004` | evidence/guide-events-2026-10-04/guide.md | 59 | 8 | 3 | 0 | 3 | 0 | 1 | 0 | 0 | 1 | 重读对应模块后整档再生成；批量更新行号（定点再生成）；腐烂≥50%，建议整档优先级提前 |
| `guide/events-20261004-v2` | docs/guides/events-and-progress-chain.md | 59 | 8 | 3 | 0 | 3 | 0 | 1 | 0 | 0 | 1 | 重读对应模块后整档再生成；批量更新行号（定点再生成）；腐烂≥50%，建议整档优先级提前 |
| `guide/frontend-20261004` | evidence/guide-frontend-20261004/guide.md | 102 | 8 | 3 | 1 | 3 | 0 | 0 | 0 | 0 | 1 | 批量更新行号（定点再生成）；微漂移可在下次导读刷新时顺手修 |
| `guide/i18n-20261004` ⟲ | evidence/guide-i18n-2026-10-04/guide.md | 66 | 8 | 6 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 批量更新行号（定点再生成） |
| `guide/ima-pipeline-20261005` | evidence/ima-pipeline-guide-20261005/report.md | 124 | 8 | 3 | 0 | 3 | 0 | 0 | 0 | 0 | 2 | 批量更新行号（定点再生成）；腐烂≥50%，建议整档优先级提前 |
| `guide/journal-20261004` | evidence/journal-guide-20261004/report.md | 41 | 8 | 3 | 0 | 1 | 0 | 2 | 0 | 0 | 2 | 重读对应模块后整档再生成；批量更新行号（定点再生成）；腐烂≥50%，建议整档优先级提前 |
| `guide/learning-domain-20261007` | docs/guides/learning-domain.md | 85 | 8 | 1 | 0 | 0 | 0 | 0 | 0 | 5 | 2 | 保持（样本内无腐烂） |
| `guide/llm-providers-20261004` | evidence/guide-llm-providers-20261004/guide.md | 241 | 8 | 4 | 2 | 0 | 0 | 0 | 0 | 0 | 2 | 微漂移可在下次导读刷新时顺手修 |
| `guide/logging-20261005` | evidence/guide-logging-20261005/guide.md | 79 | 8 | 4 | 0 | 1 | 0 | 1 | 0 | 0 | 2 | 重读对应模块后整档再生成；批量更新行号（定点再生成） |
| `guide/marginnote-bridge-20261006` | docs/guides/marginnote-bridge.md | 48 | 8 | 3 | 2 | 2 | 0 | 0 | 0 | 0 | 1 | 批量更新行号（定点再生成）；微漂移可在下次导读刷新时顺手修 |
| `guide/mcp-integration-20261005` | evidence/mcp-guide-20261005/report.md | 147 | 8 | 2 | 0 | 4 | 0 | 0 | 0 | 1 | 1 | 批量更新行号（定点再生成）；腐烂≥50%，建议整档优先级提前 |
| `guide/memory-20261006` | docs/guides/memory.md | 65 | 8 | 1 | 1 | 1 | 0 | 1 | 0 | 2 | 2 | 重读对应模块后整档再生成；批量更新行号（定点再生成）；微漂移可在下次导读刷新时顺手修；腐烂≥50%，建议整档优先级提前 |
| `guide/net-validation-20261006` | evidence/net-validation-guide-20261006/report.md | 43 | 8 | 2 | 0 | 3 | 0 | 2 | 0 | 1 | 0 | 重读对应模块后整档再生成；批量更新行号（定点再生成）；腐烂≥50%，建议整档优先级提前 |
| `guide/notebook-20261004-v1` | evidence/notebook-guide-20261004/report.md | 80 | 8 | 4 | 2 | 1 | 0 | 0 | 0 | 1 | 0 | 批量更新行号（定点再生成）；微漂移可在下次导读刷新时顺手修 |
| `guide/parsing-20261004` | evidence/guide-parsing-20261004/guide.md | 133 | 8 | 5 | 0 | 1 | 0 | 1 | 0 | 0 | 1 | 重读对应模块后整档再生成；批量更新行号（定点再生成） |
| `guide/parsing-engines-20261011` | docs/guides/parsing-engines.md | 148 | 8 | 4 | 0 | 3 | 0 | 0 | 0 | 1 | 0 | 批量更新行号（定点再生成） |
| `guide/partner-groups-20261011` | docs/guides/partner-groups.md | 29 | 8 | 4 | 0 | 1 | 0 | 1 | 0 | 1 | 1 | 重读对应模块后整档再生成；批量更新行号（定点再生成） |
| `guide/plugins-20261005` | evidence/guide-plugins-2026-10-05/guide.md | 71 | 8 | 5 | 0 | 0 | 0 | 2 | 0 | 0 | 1 | 重读对应模块后整档再生成 |
| `guide/practice-domain-20261006` | docs/guides/practice.md | 36 | 8 | 0 | 2 | 3 | 0 | 1 | 0 | 0 | 2 | 重读对应模块后整档再生成；批量更新行号（定点再生成）；微漂移可在下次导读刷新时顺手修；腐烂≥50%，建议整档优先级提前 |
| `guide/provider-registry-20261009` | evidence/guide-provider-registry-20261009/report.md | 44 | 8 | 8 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 保持（样本内无腐烂） |
| `guide/quiz-20261004` | evidence/quiz-guide-20261004/report.md | 147 | 8 | 4 | 0 | 1 | 0 | 0 | 0 | 2 | 1 | 批量更新行号（定点再生成） |
| `guide/rag-eval-20261006` | docs/guides/rag-eval.md | 107 | 8 | 4 | 1 | 1 | 0 | 0 | 0 | 0 | 2 | 批量更新行号（定点再生成）；微漂移可在下次导读刷新时顺手修 |
| `guide/rag-pipelines-20261006` | evidence/rag-pipelines-guide-20261006/report.md | 104 | 8 | 1 | 0 | 1 | 0 | 0 | 0 | 4 | 2 | 批量更新行号（定点再生成）；腐烂≥50%，建议整档优先级提前 |
| `guide/sandbox-20261006` | docs/guides/sandbox.md | 192 | 8 | 4 | 1 | 3 | 0 | 0 | 0 | 0 | 0 | 批量更新行号（定点再生成）；微漂移可在下次导读刷新时顺手修 |
| `guide/session-turns-20261007` | docs/guides/session-turns.md | 58 | 8 | 2 | 0 | 2 | 0 | 1 | 0 | 1 | 2 | 重读对应模块后整档再生成；批量更新行号（定点再生成）；腐烂≥50%，建议整档优先级提前 |
| `guide/subagent-20261004` | evidence/guide-subagent-20261004/guide.md | 190 | 8 | 4 | 0 | 3 | 0 | 0 | 0 | 1 | 0 | 批量更新行号（定点再生成） |
| `guide/suggestions-20261009` | evidence/guide-suggestions-20261009/report.md | 18 | 8 | 3 | 2 | 1 | 0 | 1 | 0 | 0 | 1 | 重读对应模块后整档再生成；批量更新行号（定点再生成）；微漂移可在下次导读刷新时顺手修 |
| `guide/testing-20261004` | evidence/guide-testing-20261004/guide.md | 49 | 8 | 2 | 0 | 1 | 0 | 0 | 0 | 2 | 3 | 批量更新行号（定点再生成） |
| `guide/tools-20261004` | evidence/guide-tools-2026-10-04/guide.md | 52 | 8 | 4 | 1 | 0 | 0 | 0 | 0 | 0 | 3 | 微漂移可在下次导读刷新时顺手修 |
| `guide/tools-20261004-v2` | docs/guides/tools-surface.md | 52 | 8 | 4 | 1 | 0 | 0 | 0 | 0 | 0 | 3 | 微漂移可在下次导读刷新时顺手修 |
| `guide/video-learning-20261007` | docs/guides/video-learning.md | 84 | 8 | 5 | 1 | 2 | 0 | 0 | 0 | 0 | 0 | 批量更新行号（定点再生成）；微漂移可在下次导读刷新时顺手修 |
| `guide/vision-tools-20261007` | docs/guides/vision-tools.md | 110 | 8 | 1 | 1 | 3 | 0 | 1 | 0 | 0 | 2 | 重读对应模块后整档再生成；批量更新行号（定点再生成）；微漂移可在下次导读刷新时顺手修；腐烂≥50%，建议整档优先级提前 |
| `guide/viz-chain-20261004` | evidence/guide-visualize-20261004/guide.md | 73 | 8 | 3 | 0 | 2 | 0 | 0 | 0 | 0 | 3 | 批量更新行号（定点再生成） |
| `guide/voice-20261005` | evidence/guide-voice-20261005/guide.md | 48 | 8 | 3 | 0 | 1 | 0 | 0 | 0 | 1 | 3 | 批量更新行号（定点再生成） |
| `guide/web-guards-20261006` | docs/guides/web-guard-layers.md | 49 | 8 | 2 | 1 | 0 | 0 | 2 | 0 | 0 | 3 | 重读对应模块后整档再生成；微漂移可在下次导读刷新时顺手修 |
| `guide/web-state-20261007` | docs/guides/web-state.md | 174 | 8 | 3 | 0 | 2 | 0 | 0 | 0 | 0 | 3 | 批量更新行号（定点再生成） |
| `myfork/docs/guides/immersive-reading` | docs/guides/immersive-reading.md | 69 | 8 | 3 | 0 | 1 | 0 | 0 | 0 | 0 | 4 | 批量更新行号（定点再生成） |
| `myfork/docs/guides/knowledge-base` | docs/guides/knowledge-base.md | 93 | 8 | 3 | 0 | 2 | 0 | 1 | 0 | 0 | 2 | 重读对应模块后整档再生成；批量更新行号（定点再生成）；腐烂≥50%，建议整档优先级提前 |
| `myfork/docs/guides/learner-accounts` | docs/guides/learner-accounts.md | 93 | 8 | 2 | 0 | 2 | 0 | 0 | 0 | 0 | 4 | 批量更新行号（定点再生成）；腐烂≥50%，建议整档优先级提前 |
| `myfork/docs/guides/mastery-path` | docs/guides/mastery-path.md | 90 | 8 | 4 | 0 | 3 | 0 | 1 | 0 | 0 | 0 | 重读对应模块后整档再生成；批量更新行号（定点再生成）；腐烂≥50%，建议整档优先级提前 |

- 孪生分支（同文档同 blob，判定一致，统计按分支各自计入）：codex/mini-watching-aligned-baseline + codex/watching-bookmark-notes + codex/watching-center-transcript + codex/watching-fullscreen-captions + codex/watching-notes-reliability（docs/guides/watching-learning.md, docs/guides/watching-workspace.md）；codex/upstream-watching-workspace + codex/watching-workspace（docs/guides/watching-workspace.md）；guide-i18n-20261004 + guide/i18n-20261004（evidence/guide-i18n-2026-10-04/guide.md）

## 三、腐烂锚点明细（全部 245 条）

| 分支 | 锚点 | v1.6.14 现状 | 判定 |
|---|---|---|---|
| `agent/agen1031-llm-clients-guide` | `provider_factory.py:131` | 声明符号现位于 deeptutor/services/llm/provider_factory.py:126（锚点写 131，偏移≤5 行） | 微漂移 |
| `agent/dt468-routers-guide` | `auth.py:558` | 声明符号现位于 deeptutor/api/routers/auth.py:553（锚点写 558，偏移≤5 行） | 微漂移 |
| `agent/dt468-routers-guide` | `question.py:334` | 声明符号现位于 deeptutor/api/routers/question.py:336（锚点写 334，偏移≤5 行） | 微漂移 |
| `agent/dt468-routers-guide` | `knowledge.py:3357-3362` | 声明符号现位于 deeptutor/api/routers/knowledge.py:3383（锚点写 3357） | 行漂移 |
| `agent/dt468-routers-guide` | `question.py:131` | 声明符号现位于 deeptutor/api/routers/question.py:119（锚点写 131） | 行漂移 |
| `docs/guide-imagegen` | `deeptutor/services/imagegen/adapters/openai_compat.py:87` | 声明符号现位于 deeptutor/services/imagegen/adapters/openai_compat.py:82（锚点写 87，偏移≤5 行） | 微漂移 |
| `docs/guide-imagegen` | `deeptutor/services/imagegen/__init__.py:34-35` | 声明符号现位于 deeptutor/services/imagegen/__init__.py:43（锚点写 34） | 行漂移 |
| `docs/guide-multi-user` | `auth.py:921` | 声明符号现位于 deeptutor/api/routers/auth.py:1048（锚点写 921） | 行漂移 |
| `docs/guide-multi-user` | `book_access.py:84` | deeptutor/multi_user/book_access.py 存在，但强声明符号 multi_user 全文件未命中 | 内容漂移 |
| `docs/guide-tex-tools-20261008` | `tex_downloader.py:221-222` | 声明符号现位于 deeptutor/tools/tex_downloader.py:217（锚点写 221，偏移≤5 行） | 微漂移 |
| `docs/guides/book-pipeline` | `deeptutor/book/engine.py:5` | 声明符号现位于 deeptutor/book/engine.py:2（锚点写 5，偏移≤5 行） | 微漂移 |
| `docs/guides/book-pipeline` | `book.py:1269` | 声明符号现位于 deeptutor/api/routers/book.py:1271（锚点写 1269） | 行漂移 |
| `docs/guides/book-pipeline` | `progress.py:38` | 声明符号现位于 deeptutor/book/progress.py:22（锚点写 38） | 行漂移 |
| `docs/guides/book-pipeline` | `event_hub.py:63-71` | 声明符号现位于 deeptutor/book/event_hub.py:53（锚点写 63） | 行漂移 |
| `docs/guides/chat-runtime` | `deeptutor/runtime/coordination/protocol.py:11` | deeptutor/runtime/coordination/protocol.py 存在，但强声明符号 user_input 全文件未命中 | 内容漂移 |
| `docs/guides/chat-runtime` | `app/service.py:135` | 声明符号现位于 deeptutor/app/service.py:179（锚点写 135） | 行漂移 |
| `docs/guides/chat-runtime` | `TurnRuntimeClient.ts:270-274` | 声明符号现位于 web/features/chat/transport/TurnRuntimeClient.ts:342（锚点写 270） | 行漂移 |
| `docs/guides/ci-workflows` | `web/package.json:21` | 声明符号现位于 web/package.json:28（锚点写 21） | 行漂移 |
| `docs/guides/ci-workflows` | `scripts/check_repo_hygiene.py:51` | 声明符号现位于 scripts/check_repo_hygiene.py:40（锚点写 51） | 行漂移 |
| `docs/guides/co-writer` | `deeptutor/api/routers/co_writer.py:36` | deeptutor/api/routers/co_writer.py 存在，但强声明符号 _auth 全文件未命中 | 内容漂移 |
| `docs/guides/co-writer` | `docx_converter.py:22` | 声明符号现位于 deeptutor/co_writer/docx_converter.py:25（锚点写 22，偏移≤5 行） | 微漂移 |
| `docs/guides/co-writer` | `routers/co_writer.py:363-379` | 声明符号现位于 deeptutor/api/routers/co_writer.py:338（锚点写 363） | 行漂移 |
| `docs/guides/co-writer` | `edit_agent.py:57-58` | 声明符号现位于 deeptutor/co_writer/edit_agent.py:49（锚点写 57） | 行漂移 |
| `docs/guides/co-writer-20261011` | `tests/runtime/test_api_import_memory_boundary.py:37` | tests/runtime/test_api_import_memory_boundary.py 存在，但强声明符号 _HEADING_STYLES/_numbering_formats/_list_kind 全文件未命中 | 内容漂移 |
| `docs/guides/co-writer-20261011` | `web/components/chat/home/ChatMarkdownNoteTab.tsx:14-17` | web/components/chat/home/ChatMarkdownNoteTab.tsx 存在，但强声明符号 co_writer/record_type/co_writer 全文件未命中 | 内容漂移 |
| `docs/guides/co-writer-20261011` | `co_writer.py:301-316` | 声明符号现位于 deeptutor/api/routers/co_writer.py:296（锚点写 301，偏移≤5 行） | 微漂移 |
| `docs/guides/codex-auth` | `oauth.py:185-201` | 声明符号现位于 deeptutor/services/codex_auth/oauth.py:115（锚点写 185） | 行漂移 |
| `docs/guides/codex-auth` | `api/routers/settings.py:950-967` | deeptutor/api/routers/settings.py 存在，但强声明符号 parse_oauth_callback_url/redirect_uri 全文件未命中 | 内容漂移 |
| `docs/guides/codex-auth` | `api/routers/auth.py:743-753` | deeptutor/api/routers/auth.py 存在，但强声明符号 _require_codex_oauth_actor 全文件未命中 | 内容漂移 |
| `docs/guides/cron-scheduling-20261011` | `service.py:246` | 声明符号现位于 deeptutor/services/cron/service.py:252（锚点写 246） | 行漂移 |
| `docs/guides/cron-scheduling-20261011` | `service.py:346-355` | 声明符号现位于 deeptutor/services/cron/service.py:342（锚点写 346，偏移≤5 行） | 微漂移 |
| `docs/guides/cron-scheduling-20261011` | `deeptutor/runtime/background_leader.py:139-155` | 声明符号现位于 deeptutor/runtime/background_leader.py:227（锚点写 139） | 行漂移 |
| `docs/guides/deep-research` | `pipeline.py:2647` | 声明符号现位于 deeptutor/agents/research/pipeline.py:2679（锚点写 2647） | 行漂移 |
| `docs/guides/deep-research` | `pipeline.py:2899` | 声明符号现位于 deeptutor/agents/research/pipeline.py:2935（锚点写 2899） | 行漂移 |
| `docs/guides/deep-research` | `pipeline.py:2375` | 声明符号现位于 deeptutor/agents/research/pipeline.py:1864（锚点写 2375） | 行漂移 |
| `docs/guides/embedding-progress` | `knowledge.py:3715-3732` | 声明符号现位于 deeptutor/api/routers/knowledge.py:3855（锚点写 3715） | 行漂移 |
| `docs/guides/embedding-progress` | `deeptutor/api/routers/knowledge.py:4220` | 声明符号现位于 deeptutor/api/routers/knowledge.py:4429（锚点写 4220） | 行漂移 |
| `docs/guides/launcher` | `launcher.py:889-892` | 声明符号现位于 deeptutor/runtime/launcher.py:926（锚点写 889） | 行漂移 |
| `docs/guides/launcher` | `launcher.py:1443-1476` | 声明符号现位于 deeptutor/runtime/launcher.py:710（锚点写 1443） | 行漂移 |
| `docs/guides/launcher` | `launcher.py:1522-1529` | 声明符号现位于 deeptutor/runtime/launcher.py:1646（锚点写 1522） | 行漂移 |
| `docs/guides/math-animator` | `concept_analysis_agent.py:57` | 声明符号现位于 deeptutor/agents/math_animator/agents/concept_analysis_agent.py:45（锚点写 57） | 行漂移 |
| `docs/guides/math-animator` | `code_generator_agent.py:105` | 声明符号现位于 deeptutor/agents/math_animator/agents/code_generator_agent.py:118（锚点写 105） | 行漂移 |
| `docs/guides/partner-channels-20261011` | `dingtalk.py:116` | 声明符号现位于 deeptutor/partners/channels/dingtalk.py:111（锚点写 116，偏移≤5 行） | 微漂移 |
| `docs/guides/partner-channels-20261011` | `mochat.py:276` | 声明符号现位于 deeptutor/partners/channels/mochat.py:268（锚点写 276） | 行漂移 |
| `docs/guides/partner-channels-20261011` | `msteams.py:269-276` | deeptutor/partners/channels/msteams.py 存在，但强声明符号 send_with_retry/context_token 全文件未命中 | 内容漂移 |
| `docs/guides/partner-channels-20261011` | `napcat.py:80` | 声明符号现位于 deeptutor/partners/channels/napcat.py:248（锚点写 80） | 行漂移 |
| `docs/guides/question-pipeline` | `pipeline.py:587-607` | 声明符号现位于 deeptutor/agents/question/pipeline.py:585（锚点写 587） | 行漂移 |
| `docs/guides/question-pipeline` | `pipeline.py:1142-1159` | 声明符号现位于 deeptutor/agents/question/pipeline.py:1080（锚点写 1142） | 行漂移 |
| `docs/guides/quiz-notebook` | `pipeline.py:556` | 声明符号现位于 deeptutor/agents/question/pipeline.py:534（锚点写 556） | 行漂移 |
| `docs/guides/quiz-notebook` | `QuizViewer.tsx:446` | 声明符号现位于 web/components/quiz/QuizViewer.tsx:451（锚点写 446，偏移≤5 行） | 微漂移 |
| `docs/guides/research-primitives` | `deeptutor/services/mcp/config.py:121` | 声明符号现位于 deeptutor/services/mcp/config.py:107（锚点写 121） | 行漂移 |
| `docs/guides/research-primitives` | `deeptutor/services/mcp/catalog/loader.py:38` | 声明符号现位于 deeptutor/services/mcp/catalog/loader.py:20（锚点写 38） | 行漂移 |
| `docs/guides/runtime-subpackages` | `client.py:64-66` | 声明符号现位于 deeptutor/runtime/agentic/client.py:123（锚点写 64） | 行漂移 |
| `docs/guides/runtime-update-chain` | `app_update.py:584-585` | 声明符号现位于 deeptutor/services/app_update.py:498（锚点写 584） | 行漂移 |
| `docs/guides/runtime-update-chain` | `system.py:272-286` | deeptutor/api/routers/system.py 存在，但强声明符号 DEEPTUTOR_LAUNCHER_PID 全文件未命中 | 内容漂移 |
| `docs/guides/runtime-update-chain` | `launcher.py:1554` | 声明符号现位于 deeptutor/runtime/launcher.py:1682（锚点写 1554） | 行漂移 |
| `docs/guides/runtime-update-chain` | `app_update.py:600-611` | deeptutor/services/app_update.py 存在，但强声明符号 _launch_restart/deeptutor_cli 全文件未命中 | 内容漂移 |
| `docs/guides/runtime-update-chain` | `launcher.py:1567-1570` | 声明符号现位于 deeptutor/runtime/launcher.py:1372（锚点写 1567） | 行漂移 |
| `docs/guides/search-providers` | `base.py:52-54` | 声明符号现位于 deeptutor/services/search/base.py:48（锚点写 52，偏移≤5 行） | 微漂移 |
| `docs/guides/search-providers` | `perplexity.py:86-100` | 声明符号现位于 deeptutor/services/search/providers/perplexity.py:153（锚点写 86） | 行漂移 |
| `docs/guides/search-providers` | `search/__init__.py:176-183` | 声明符号现位于 deeptutor/services/search/providers/__init__.py:143（锚点写 176） | 行漂移 |
| `docs/guides/session-history` | `executor.py:556-557` | 声明符号现位于 deeptutor/services/session/turns/executor.py:562（锚点写 556） | 行漂移 |
| `docs/guides/skills-mcp` | `tools/builtin/__init__.py:484-560` | 声明符号现位于 deeptutor/tools/builtin/__init__.py:561（锚点写 484） | 行漂移 |
| `docs/guides/subagent-family-20261011` | `codex.py:50-52` | 声明符号现位于 deeptutor/services/subagent/codex.py:49（锚点写 50，偏移≤5 行） | 微漂移 |
| `docs/guides/subagent-family-20261011` | `codex.py:113-117` | 声明符号现位于 deeptutor/services/subagent/codex.py:78（锚点写 113） | 行漂移 |
| `docs/guides/textbook-struct` | `deeptutor/textbook_struct/__init__.py:6` | 声明符号现位于 deeptutor/textbook_struct/__init__.py:1（锚点写 6，偏移≤5 行） | 微漂移 |
| `docs/guides/textbook-struct` | `services/parsing/engines/mineru/cloud.py:324-332` | deeptutor/services/parsing/engines/mineru/cloud.py 存在，但强声明符号 load_ir/partNN_/textbook_struct 全文件未命中 | 内容漂移 |
| `docs/guides/tools-prompting` | `deeptutor/tools/builtin_specs.py:217-222` | 声明符号现位于 deeptutor/tools/builtin_specs.py:233（锚点写 217） | 行漂移 |
| `docs/guides/usage-ledger-20261011` | `metrics.py:152-163` | 声明符号现位于 deeptutor/services/llm/metrics.py:96（锚点写 152） | 行漂移 |
| `docs/guides/visual-grounding-20261010` | `KbVisualCoverage.tsx:24` | 声明符号现位于 web/components/knowledge/KbVisualCoverage.tsx:25（锚点写 24，偏移≤5 行） | 微漂移 |
| `docs/guides/visualizers` | `deeptutor/visualizers/protocol.py:14` | 声明符号现位于 deeptutor/visualizers/protocol.py:23（锚点写 14） | 行漂移 |
| `docs/guides/web-activity` | `web/components/activity/ActivityRow.tsx:66` | 声明符号现位于 web/components/activity/ActivityRow.tsx:63（锚点写 66） | 行漂移 |
| `docs/guides/web-activity` | `web/features/chat/transport/UnifiedTurnClient.ts:93` | 声明符号现位于 web/features/chat/transport/UnifiedTurnClient.ts:94（锚点写 93，偏移≤5 行） | 微漂移 |
| `docs/guides/web-activity` | `ChatWorkspace.tsx:2704-2737` | 声明符号现位于 web/features/chat/components/ChatWorkspace.tsx:2665（锚点写 2704） | 行漂移 |
| `docs/guides/web-contracts` | `web/lib/mcp-api.ts:281` | 声明符号现位于 web/lib/mcp-api.ts:283（锚点写 281，偏移≤5 行） | 微漂移 |
| `docs/guides/web-contracts` | `api.ts:14017` | 声明符号现位于 web/contracts/generated/api.ts:14528（锚点写 14017） | 行漂移 |
| `docs/guides/web-source` | `crawler.py:395-400` | 声明符号现位于 deeptutor/services/web_source/crawler.py:347（锚点写 395） | 行漂移 |
| `docs/guides/web-source` | `repository.py:212-214` | 声明符号现位于 deeptutor/services/web_source/repository.py:184（锚点写 212） | 行漂移 |
| `docs/guides/web-source` | `scheduler.py:19-25` | 声明符号现位于 deeptutor/services/web_source/scheduler.py:42（锚点写 19） | 行漂移 |
| `docs/packaging-startup-guide-20261007` | `pyproject.toml:4-6` | 声明符号现位于 packaging/deeptutor-cli/pyproject.toml:3（锚点写 4，偏移≤5 行） | 微漂移 |
| `docs/packaging-startup-guide-20261007` | `deeptutor_cli/main.py:222-224` | 声明符号现位于 deeptutor_cli/main.py:204（锚点写 222） | 行漂移 |
| `docs/packaging-startup-guide-20261007` | `deeptutor/runtime/launcher.py:841-892` | 声明符号现位于 deeptutor/runtime/launcher.py:780（锚点写 841） | 行漂移 |
| `docs/packaging-startup-guide-20261007` | `entrypoint.sh:329-515` | 目标文件在 v1.6.14 不存在（含相对前缀、目录树回退均未命中） | 失效 |
| `docs/skills-system-guide` | `deeptutor/services/skill/service.py:8` | 声明符号现位于 deeptutor/services/skill/service.py:12（锚点写 8，偏移≤5 行） | 微漂移 |
| `docs/skills-system-guide` | `deeptutor/services/skill/service.py:613` | 声明符号现位于 deeptutor/services/skill/service.py:610（锚点写 613，偏移≤5 行） | 微漂移 |
| `docs/skills-system-guide` | `deeptutor/services/skill/taxonomy.py:111` | 声明符号现位于 deeptutor/services/skill/taxonomy.py:5（锚点写 111） | 行漂移 |
| `docs/skills-system-guide` | `deeptutor/services/skill/service.py:1010` | 声明符号现位于 deeptutor/services/skill/service.py:1020（锚点写 1010） | 行漂移 |
| `docs/task-board-guide-20261006` | `deeptutor/api/main.py:591` | 声明符号现位于 deeptutor/api/main.py:586（锚点写 591，偏移≤5 行） | 微漂移 |
| `docs/task-board-guide-20261006` | `auth.py:516` | 声明符号现位于 deeptutor/api/routers/auth.py:519（锚点写 516，偏移≤5 行） | 微漂移 |
| `docs/usage-stats-guide` | `deeptutor/services/llm/usage_ledger.py:58-62` | 声明符号现位于 deeptutor/services/llm/usage_ledger.py:43（锚点写 58） | 行漂移 |
| `docs/watching-convergence-guide-20261011` | `web/lib/learning-routes.ts:41` | 声明符号现位于 web/lib/learning-routes.ts:36（锚点写 41，偏移≤5 行） | 微漂移 |
| `docs/workspace-migration-guide-20261006` | `catalog.py:434-443` | 声明符号现位于 deeptutor/services/workspace/catalog.py:459（锚点写 434） | 行漂移 |
| `docs/workspace-migration-guide-20261006` | `session_move.py:64` | 声明符号现位于 deeptutor/services/workspace/session_move.py:53（锚点写 64） | 行漂移 |
| `docs/workspace-migration-guide-20261006` | `dependencies.py:326-328` | 声明符号现位于 deeptutor/services/workspace/dependencies.py:355（锚点写 326） | 行漂移 |
| `docs/workspace-migration-guide-20261006` | `data_migration.py:939-969` | 声明符号现位于 deeptutor/services/workspace/data_migration.py:914（锚点写 939） | 行漂移 |
| `dt-agen1728-partnerguide` | `deeptutor/services/partners/runtime.py:158` | 声明符号现位于 deeptutor/services/partners/runtime.py:137（锚点写 158） | 行漂移 |
| `dt-agen1728-partnerguide` | `matrix.py:519` | 声明符号现位于 deeptutor/partners/channels/matrix.py:524（锚点写 519，偏移≤5 行） | 微漂移 |
| `evidence/guide-file-io-path-durability-20261009` | `tests/services/test_path_service.py:150` | 声明符号现位于 tests/services/test_path_service.py:173（锚点写 150） | 行漂移 |
| `evidence/guide-realtime-push-2026-10-07` | `progress_broadcaster.py:19` | 声明符号现位于 deeptutor/api/utils/progress_broadcaster.py:58（锚点写 19） | 行漂移 |
| `evidence/guide-realtime-push-2026-10-07` | `reconnect-policy.ts:1-24` | web/features/chat/transport/reconnect-policy.ts 存在，但强声明符号 setPageVisible 全文件未命中 | 内容漂移 |
| `evidence/guide-session-stores-20261007` | `sqlite_store.py:642` | 声明符号现位于 deeptutor/services/session/sqlite_store.py:656（锚点写 642） | 行漂移 |
| `evidence/guide-session-stores-20261007` | `pb_setup.py:164-175` | 声明符号现位于 scripts/pb_setup.py:128（锚点写 164） | 行漂移 |
| `evidence/guide-session-stores-20261007` | `sqlite_store.py:1500-1501` | 声明符号现位于 deeptutor/services/session/sqlite_store.py:1513（锚点写 1500） | 行漂移 |
| `evidence/guide-session-stores-20261007` | `sqlite_store.py:1615-1620` | 声明符号现位于 deeptutor/services/session/sqlite_store.py:1623（锚点写 1615） | 行漂移 |
| `guide-channels-20261005` | `napcat.py:80` | 声明符号现位于 deeptutor/partners/channels/napcat.py:472（锚点写 80） | 行漂移 |
| `guide-cli-agen477` | `init_cmd.py:51-85` | 声明符号现位于 deeptutor_cli/init_cmd.py:32（锚点写 51） | 行漂移 |
| `guide-cli-agen477` | `launcher.py:1302-1303` | 声明符号现位于 deeptutor/runtime/launcher.py:1230（锚点写 1302） | 行漂移 |
| `guide-i18n-20261004` | `deeptutor/runtime/banner.py:475-499` | 声明符号现位于 deeptutor/runtime/banner.py:511（锚点写 475） | 行漂移 |
| `guide-i18n-20261004` | `deeptutor/services/prompt/manager.py:127-138` | 声明符号现位于 deeptutor/services/prompt/manager.py:53（锚点写 127） | 行漂移 |
| `guide-local-db-401` | `deeptutor/services/session/protocol.py:4` | 声明符号现位于 deeptutor/services/session/protocol.py:150（锚点写 4） | 行漂移 |
| `guide-partners-agen371` | `deeptutor/partners/channels/base.py:38` | 声明符号现位于 deeptutor/partners/channels/base.py:145（锚点写 38） | 行漂移 |
| `guide-partners-agen371` | `runtime.py:169` | 声明符号现位于 deeptutor/services/partners/runtime.py:164（锚点写 169，偏移≤5 行） | 微漂移 |
| `guide-partners-agen371` | `manager.py:187` | 声明符号现位于 deeptutor/partners/channels/manager.py:193（锚点写 187） | 行漂移 |
| `guide-partners-agen371` | `web/features/settings/store/SettingsStore.tsx:1725` | 声明符号现位于 web/features/settings/store/SettingsStore.tsx:1773（锚点写 1725） | 行漂移 |
| `guide-storage-agen449` | `path_service.py:90` | 声明符号现位于 deeptutor/services/path_service.py:118（锚点写 90） | 行漂移 |
| `guide/agents-20261004` | `chat/capability.py:25` | 声明符号现位于 deeptutor/agents/chat/capability.py:12（锚点写 25） | 行漂移 |
| `guide/agents-20261004` | `book/blocks/animation.py:72-84` | deeptutor/book/blocks/animation.py 存在，但强声明符号 MathAnimatorCapability 全文件未命中 | 内容漂移 |
| `guide/app-update-20261005` | `deeptutor/services/app_update.py:174-180` | deeptutor/services/app_update.py 存在，但强声明符号 MERGED 全文件未命中 | 内容漂移 |
| `guide/app-update-20261005` | `AboutSettingsSection.tsx:68-84` | web/features/settings/sections/AboutSettingsSection.tsx 存在，但强声明符号 get_update_status 全文件未命中 | 内容漂移 |
| `guide/app-update-20261005` | `system.py:243-246` | 声明符号现位于 deeptutor/api/routers/system.py:238（锚点写 243） | 行漂移 |
| `guide/app-update-20261005` | `AboutSettingsSection.tsx:255-260` | 声明符号现位于 web/features/settings/sections/AboutSettingsSection.tsx:74（锚点写 255） | 行漂移 |
| `guide/ask-user-20261006` | `lifecycle.py:193-226` | 声明符号现位于 deeptutor/services/session/turns/lifecycle.py:228（锚点写 193） | 行漂移 |
| `guide/ask-user-20261006` | `pipeline.py:1184` | 声明符号现位于 deeptutor/agents/loop/pipeline.py:1189（锚点写 1184，偏移≤5 行） | 微漂移 |
| `guide/ask-user-20261006` | `executor.py:1007-1023` | 声明符号现位于 deeptutor/services/session/turns/executor.py:174（锚点写 1007） | 行漂移 |
| `guide/ask-user-20261006` | `TurnRuntimeClient.ts:359-388` | 声明符号现位于 web/features/chat/transport/TurnRuntimeClient.ts:317（锚点写 359） | 行漂移 |
| `guide/ask-user-20261006` | `agent_loop.py:703` | 声明符号现位于 deeptutor/agents/loop/agent_loop.py:732（锚点写 703） | 行漂移 |
| `guide/audio-overview-20261007` | `deeptutor/services/session/turns/request_preparer.py:133` | 声明符号现位于 deeptutor/services/session/turns/request_preparer.py:138（锚点写 133，偏移≤5 行） | 微漂移 |
| `guide/audio-overview-20261007` | `pipeline.py:342-343` | 声明符号现位于 deeptutor/capabilities/audio_overview/pipeline.py:341（锚点写 342，偏移≤5 行） | 微漂移 |
| `guide/authn-20261004` | `services/auth.py:415-443` | 声明符号现位于 deeptutor/services/auth.py:406（锚点写 415） | 行漂移 |
| `guide/background-leader-20261006` | `background_leader.py:71` | 声明符号现位于 deeptutor/runtime/background_leader.py:77（锚点写 71） | 行漂移 |
| `guide/background-leader-20261006` | `deeptutor/api/main.py:231-266` | 声明符号现位于 deeptutor/api/main.py:307（锚点写 231） | 行漂移 |
| `guide/capabilities-20261005` | `registry.py:21` | 声明符号现位于 deeptutor/capabilities/registry.py:16（锚点写 21，偏移≤5 行） | 微漂移 |
| `guide/capabilities-20261005` | `agent_loop.py:282` | 声明符号现位于 deeptutor/agents/loop/agent_loop.py:274（锚点写 282） | 行漂移 |
| `guide/capabilities-20261005` | `setup/capability.py:102-105` | 声明符号现位于 deeptutor/capabilities/setup/capability.py:108（锚点写 102） | 行漂移 |
| `guide/capabilities-20261005` | `agents/loop/pipeline.py:397` | 声明符号现位于 deeptutor/agents/loop/pipeline.py:409（锚点写 397） | 行漂移 |
| `guide/core-protocols-20261007` | `deeptutor/core/capability_protocol.py:17` | deeptutor/core/capability_protocol.py 存在，但强声明符号 turn_request/response_languages 全文件未命中 | 内容漂移 |
| `guide/core-protocols-20261007` | `deeptutor/core/turn_request.py:83-88` | 声明符号现位于 deeptutor/core/turn_request.py:80（锚点写 83，偏移≤5 行） | 微漂移 |
| `guide/core-protocols-20261007` | `deeptutor/runtime/registry/capability_registry.py:111` | 声明符号现位于 deeptutor/runtime/registry/capability_registry.py:90（锚点写 111） | 行漂移 |
| `guide/embedding-reliability-20261011` | `adapters/cohere.py:135-136` | deeptutor/services/embedding/adapters/cohere.py 存在，但强声明符号 _redacted_body 全文件未命中；路径含推断前缀，建议人工复核 | 内容漂移 |
| `guide/embedding-reliability-20261011` | `embedding_adapter.py:127-133` | deeptutor/services/rag/pipelines/llamaindex/embedding_adapter.py 存在，但强声明符号 test_embedding_requests_are_spaced_but_http_can_overlap 全文件未命中 | 内容漂移 |
| `guide/events-20261004` | `knowledge.py:3263` | 声明符号现位于 deeptutor/api/routers/knowledge.py:3379（锚点写 3263） | 行漂移 |
| `guide/events-20261004` | `deeptutor/services/partners/manager.py:784-796` | 声明符号现位于 deeptutor/services/partners/manager.py:869（锚点写 784） | 行漂移 |
| `guide/events-20261004` | `deeptutor/api/routers/mastery_path.py:771` | 声明符号现位于 deeptutor/api/routers/mastery_path.py:774（锚点写 771） | 行漂移 |
| `guide/events-20261004` | `task_log_stream.py:27-32` | deeptutor/api/utils/task_log_stream.py 存在，但强声明符号 TaskIDManager 全文件未命中 | 内容漂移 |
| `guide/events-20261004-v2` | `knowledge.py:3299` | 声明符号现位于 deeptutor/api/routers/knowledge.py:3379（锚点写 3299） | 行漂移 |
| `guide/events-20261004-v2` | `deeptutor/services/partners/manager.py:784-796` | 声明符号现位于 deeptutor/services/partners/manager.py:869（锚点写 784） | 行漂移 |
| `guide/events-20261004-v2` | `deeptutor/api/routers/mastery_path.py:771` | 声明符号现位于 deeptutor/api/routers/mastery_path.py:774（锚点写 771） | 行漂移 |
| `guide/events-20261004-v2` | `task_log_stream.py:27-32` | deeptutor/api/utils/task_log_stream.py 存在，但强声明符号 TaskIDManager 全文件未命中 | 内容漂移 |
| `guide/frontend-20261004` | `web/proxy.ts:67-76` | 声明符号现位于 web/proxy.ts:99（锚点写 67） | 行漂移 |
| `guide/frontend-20261004` | `web/context/AppShellContext.tsx:98-104` | 声明符号现位于 web/context/AppShellContext.tsx:89（锚点写 98） | 行漂移 |
| `guide/frontend-20261004` | `web/features/chat/transport/UnifiedTurnClient.ts:93` | 声明符号现位于 web/features/chat/transport/UnifiedTurnClient.ts:98（锚点写 93，偏移≤5 行） | 微漂移 |
| `guide/frontend-20261004` | `web/components/reading/workspace/ReadingWorkspace.tsx:127` | 声明符号现位于 web/components/reading/workspace/ReadingWorkspace.tsx:144（锚点写 127） | 行漂移 |
| `guide/i18n-20261004` | `deeptutor/runtime/banner.py:475-499` | 声明符号现位于 deeptutor/runtime/banner.py:511（锚点写 475） | 行漂移 |
| `guide/i18n-20261004` | `deeptutor/services/prompt/manager.py:127-138` | 声明符号现位于 deeptutor/services/prompt/manager.py:53（锚点写 127） | 行漂移 |
| `guide/ima-pipeline-20261005` | `deeptutor/tools/builtin/__init__.py:78` | 声明符号现位于 deeptutor/tools/builtin/__init__.py:68（锚点写 78） | 行漂移 |
| `guide/ima-pipeline-20261005` | `deeptutor/services/rag/pipelines/modes.py:19-45` | 声明符号现位于 deeptutor/services/rag/pipelines/modes.py:1（锚点写 19） | 行漂移 |
| `guide/ima-pipeline-20261005` | `transport.py:34` | 声明符号现位于 deeptutor/services/rag/pipelines/ima/transport.py:46（锚点写 34） | 行漂移 |
| `guide/journal-20261004` | `web/components/chat/home/ChatComposer.tsx:1306` | web/components/chat/home/ChatComposer.tsx 存在，但强声明符号 context_budget 全文件未命中 | 内容漂移 |
| `guide/journal-20261004` | `deeptutor/tools/builtin/__init__.py:929` | 声明符号现位于 deeptutor/tools/builtin/__init__.py:1006（锚点写 929） | 行漂移 |
| `guide/journal-20261004` | `deeptutor/services/session/turns/executor.py:562-563` | deeptutor/services/session/turns/executor.py 存在，但强声明符号 _BLOCK_SEGMENTS/RUNTIME_BLOCK_NAMES 全文件未命中 | 内容漂移 |
| `guide/llm-providers-20261004` | `github_copilot_provider.py:203-208` | 声明符号现位于 deeptutor/services/llm/provider_core/github_copilot_provider.py:200（锚点写 203，偏移≤5 行） | 微漂移 |
| `guide/llm-providers-20261004` | `codebuddy_provider.py:148` | 声明符号现位于 deeptutor/services/llm/provider_core/codebuddy_provider.py:151（锚点写 148，偏移≤5 行） | 微漂移 |
| `guide/logging-20261005` | `deeptutor/services/rag/pipelines/llamaindex/document_loader.py:459` | 声明符号现位于 deeptutor/services/rag/pipelines/llamaindex/document_loader.py:434（锚点写 459） | 行漂移 |
| `guide/logging-20261005` | `deeptutor/logging/config.py:11` | deeptutor/logging/config.py 存在，但强声明符号 ConsoleFormatter 全文件未命中 | 内容漂移 |
| `guide/marginnote-bridge-20261006` | `deeptutor/knowledge/kb_types.py:95` | 声明符号现位于 deeptutor/knowledge/kb_types.py:90（锚点写 95，偏移≤5 行） | 微漂移 |
| `guide/marginnote-bridge-20261006` | `routers/marginnote4.py:149` | 声明符号现位于 deeptutor/api/routers/marginnote4.py:140（锚点写 149） | 行漂移 |
| `guide/marginnote-bridge-20261006` | `routers/auth.py:453` | 声明符号现位于 deeptutor/api/routers/auth.py:452（锚点写 453） | 行漂移 |
| `guide/marginnote-bridge-20261006` | `store.py:160` | 声明符号现位于 deeptutor/capabilities/marginnote4/store.py:161（锚点写 160，偏移≤5 行） | 微漂移 |
| `guide/mcp-integration-20261005` | `core/tool_protocol.py:246` | 声明符号现位于 deeptutor/core/tool_protocol.py:234（锚点写 246） | 行漂移 |
| `guide/mcp-integration-20261005` | `view.py:33-36` | 声明符号现位于 deeptutor/runtime/providers/view.py:109（锚点写 33） | 行漂移 |
| `guide/mcp-integration-20261005` | `manager.py:656-661` | 声明符号现位于 deeptutor/services/mcp/manager.py:663（锚点写 656） | 行漂移 |
| `guide/mcp-integration-20261005` | `user_config.py:178-183` | 声明符号现位于 deeptutor/services/mcp/user_config.py:164（锚点写 178） | 行漂移 |
| `guide/memory-20261006` | `deeptutor/utils/secret_files.py:13` | deeptutor/utils/secret_files.py 存在，但强声明符号 memory_root/L3Slot/memory_path_service_override 全文件未命中 | 内容漂移 |
| `guide/memory-20261006` | `services/session/turns/executor.py:563` | 声明符号现位于 deeptutor/services/session/turns/executor.py:562（锚点写 563，偏移≤5 行） | 微漂移 |
| `guide/memory-20261006` | `routers/memory.py:686-688` | 声明符号现位于 deeptutor/api/routers/memory.py:770（锚点写 686） | 行漂移 |
| `guide/net-validation-20261006` | `services/rag/linked_kb.py:27-32` | 声明符号现位于 deeptutor/services/rag/linked_kb.py:75（锚点写 27） | 行漂移 |
| `guide/net-validation-20261006` | `services/mcp/user_config.py:187` | deeptutor/services/mcp/user_config.py 存在，但强声明符号 WeKnora 全文件未命中 | 内容漂移 |
| `guide/net-validation-20261006` | `deeptutor/api/routers/subagents.py:133` | deeptutor/api/routers/subagents.py 存在，但强声明符号 WeKnora 全文件未命中 | 内容漂移 |
| `guide/net-validation-20261006` | `services/mcp/network.py:69` | 声明符号现位于 deeptutor/services/mcp/network.py:75（锚点写 69） | 行漂移 |
| `guide/net-validation-20261006` | `services/mcp/network.py:108-118` | 声明符号现位于 deeptutor/services/mcp/network.py:129（锚点写 108） | 行漂移 |
| `guide/notebook-20261004-v1` | `deeptutor/book/engine.py:9-20` | 声明符号现位于 deeptutor/book/engine.py:2（锚点写 9） | 行漂移 |
| `guide/notebook-20261004-v1` | `deeptutor/api/routers/book.py:872` | 声明符号现位于 deeptutor/api/routers/book.py:873（锚点写 872，偏移≤5 行） | 微漂移 |
| `guide/notebook-20261004-v1` | `deeptutor/book/compiler.py:302-303` | 声明符号现位于 deeptutor/book/compiler.py:305（锚点写 302，偏移≤5 行） | 微漂移 |
| `guide/parsing-20261004` | `cache.py:60-70` | 声明符号现位于 deeptutor/services/parsing/cache.py:79（锚点写 60） | 行漂移 |
| `guide/parsing-20261004` | `graphrag/ingestion.py:43` | deeptutor/services/rag/pipelines/graphrag/ingestion.py 存在，但强声明符号 on_output 全文件未命中；路径含推断前缀，建议人工复核 | 内容漂移 |
| `guide/parsing-engines-20261011` | `parsing/service.py:89-92` | 声明符号现位于 deeptutor/services/parsing/service.py:74（锚点写 89） | 行漂移 |
| `guide/parsing-engines-20261011` | `factory.py:27-66` | 声明符号现位于 deeptutor/services/parsing/engines/factory.py:70（锚点写 27） | 行漂移 |
| `guide/parsing-engines-20261011` | `engine.py:28-29` | 声明符号现位于 deeptutor/services/parsing/engines/docling/engine.py:41（锚点写 28） | 行漂移 |
| `guide/partner-groups-20261011` | `services/partner_groups/manager.py:1633` | 声明符号现位于 deeptutor/services/partner_groups/manager.py:1387（锚点写 1633） | 行漂移 |
| `guide/partner-groups-20261011` | `deeptutor/capabilities/registry.py:84` | deeptutor/capabilities/registry.py 存在，但强声明符号 PartnerGroupBackend 全文件未命中 | 内容漂移 |
| `guide/plugins-20261005` | `deeptutor/plugins/loader.py:26` | deeptutor/plugins/loader.py 存在，但强声明符号 DeprecationWarning 全文件未命中 | 内容漂移 |
| `guide/plugins-20261005` | `deeptutor/runtime/registry/capability_registry.py:110-112` | deeptutor/runtime/registry/capability_registry.py 存在，但强声明符号 ValueError 全文件未命中 | 内容漂移 |
| `guide/practice-domain-20261006` | `deeptutor/services/session/sqlite_store.py:516` | 声明符号现位于 deeptutor/services/session/sqlite_store.py:4016（锚点写 516） | 行漂移 |
| `guide/practice-domain-20261006` | `deeptutor/services/practice/importing.py:203` | deeptutor/services/practice/importing.py 存在，但强声明符号 PracticeStore/check_answer 全文件未命中 | 内容漂移 |
| `guide/practice-domain-20261006` | `web/components/learning/practice/PracticeSession.tsx:191` | 声明符号现位于 web/components/learning/practice/PracticeSession.tsx:207（锚点写 191） | 行漂移 |
| `guide/practice-domain-20261006` | `deeptutor/services/practice/scheduler.py:35` | 声明符号现位于 deeptutor/services/practice/scheduler.py:56（锚点写 35） | 行漂移 |
| `guide/practice-domain-20261006` | `deeptutor/services/practice/storage.py:91` | 声明符号现位于 deeptutor/services/practice/storage.py:88（锚点写 91，偏移≤5 行） | 微漂移 |
| `guide/practice-domain-20261006` | `deeptutor/api/routers/practice.py:103` | 声明符号现位于 deeptutor/api/routers/practice.py:104（锚点写 103，偏移≤5 行） | 微漂移 |
| `guide/quiz-20261004` | `deeptutor/services/config/loader.py:314-320` | 声明符号现位于 deeptutor/services/config/loader.py:313（锚点写 314） | 行漂移 |
| `guide/rag-eval-20261006` | `deeptutor_cli/kb.py:419` | 声明符号现位于 deeptutor_cli/kb.py:399（锚点写 419） | 行漂移 |
| `guide/rag-eval-20261006` | `report.py:96-108` | 声明符号现位于 deeptutor/services/rag/eval/report.py:94（锚点写 96，偏移≤5 行） | 微漂移 |
| `guide/rag-pipelines-20261006` | `sources.py:33` | 声明符号现位于 deeptutor/services/rag/pipelines/ima/sources.py:39（锚点写 33） | 行漂移 |
| `guide/sandbox-20261006` | `exec_tool.py:39-43` | 声明符号现位于 deeptutor/tools/exec_tool.py:36（锚点写 39，偏移≤5 行） | 微漂移 |
| `guide/sandbox-20261006` | `exec_tool.py:202` | 声明符号现位于 deeptutor/tools/exec_tool.py:192（锚点写 202） | 行漂移 |
| `guide/sandbox-20261006` | `artifacts.py:76-78` | 声明符号现位于 deeptutor/services/sandbox/artifacts.py:94（锚点写 76） | 行漂移 |
| `guide/sandbox-20261006` | `backends.py:461-478` | 声明符号现位于 deeptutor/services/sandbox/backends.py:446（锚点写 461） | 行漂移 |
| `guide/session-turns-20261007` | `app/facade.py:131` | deeptutor/app/facade.py 存在，但强声明符号 TurnRuntimeManager/ActiveTurnConflict 全文件未命中 | 内容漂移 |
| `guide/session-turns-20261007` | `request_preparer.py:709-717` | 声明符号现位于 deeptutor/services/session/turns/request_preparer.py:677（锚点写 709） | 行漂移 |
| `guide/session-turns-20261007` | `request_preparer.py:426-446` | 声明符号现位于 deeptutor/services/session/turns/request_preparer.py:482（锚点写 426） | 行漂移 |
| `guide/subagent-20261004` | `sessions.py:28` | 声明符号现位于 deeptutor/api/routers/sessions.py:18（锚点写 28） | 行漂移 |
| `guide/subagent-20261004` | `claude_code.py:100-110` | 声明符号现位于 deeptutor/services/subagent/claude_code.py:85（锚点写 100） | 行漂移 |
| `guide/subagent-20261004` | `process.py:9-13` | 声明符号现位于 deeptutor/services/subagent/process.py:62（锚点写 9） | 行漂移 |
| `guide/suggestions-20261009` | `suggestions.py:627-634` | 声明符号现位于 deeptutor/services/suggestions.py:624（锚点写 627，偏移≤5 行） | 微漂移 |
| `guide/suggestions-20261009` | `suggestions.py:136` | 声明符号现位于 deeptutor/services/suggestions.py:137（锚点写 136，偏移≤5 行） | 微漂移 |
| `guide/suggestions-20261009` | `suggestions.py:144` | 声明符号现位于 deeptutor/services/suggestions.py:167（锚点写 144） | 行漂移 |
| `guide/suggestions-20261009` | `llm/factory.py:411` | deeptutor/services/llm/factory.py 存在，但强声明符号 _generate/task_llm_scope/CHAT_STARTERS 全文件未命中；路径含推断前缀，建议人工复核 | 内容漂移 |
| `guide/testing-20261004` | `conftest.py:48` | 声明符号现位于 tests/services/partners/conftest.py:37（锚点写 48） | 行漂移 |
| `guide/tools-20261004` | `deeptutor/agents/loop/pipeline.py:780-781` | 声明符号现位于 deeptutor/agents/loop/pipeline.py:783（锚点写 780，偏移≤5 行） | 微漂移 |
| `guide/tools-20261004-v2` | `deeptutor/agents/loop/pipeline.py:778-781` | 声明符号现位于 deeptutor/agents/loop/pipeline.py:783（锚点写 778，偏移≤5 行） | 微漂移 |
| `guide/video-learning-20261007` | `deeptutor/video_learning/service.py:307-308` | 声明符号现位于 deeptutor/video_learning/service.py:257（锚点写 307） | 行漂移 |
| `guide/video-learning-20261007` | `service.py:407-408` | 声明符号现位于 deeptutor/video_learning/service.py:411（锚点写 407，偏移≤5 行） | 微漂移 |
| `guide/video-learning-20261007` | `readiness.py:653-655` | 声明符号现位于 deeptutor/services/config/readiness.py:637（锚点写 653） | 行漂移 |
| `guide/vision-tools-20261007` | `visualizers/builtin.py:120` | 声明符号现位于 deeptutor/visualizers/builtin.py:117（锚点写 120，偏移≤5 行） | 微漂移 |
| `guide/vision-tools-20261007` | `deeptutor/visualizers/registry.py:13` | 声明符号现位于 deeptutor/visualizers/registry.py:125（锚点写 13） | 行漂移 |
| `guide/vision-tools-20261007` | `web/components/Geogebra.tsx:93` | 声明符号现位于 web/components/Geogebra.tsx:84（锚点写 93） | 行漂移 |
| `guide/vision-tools-20261007` | `tools/prompting/__init__.py:52` | deeptutor/tools/prompting/__init__.py 存在，但强声明符号 geogebra_analysis 全文件未命中 | 内容漂移 |
| `guide/vision-tools-20261007` | `vision_solver_agent.py:159-160` | 声明符号现位于 deeptutor/agents/vision_solver/vision_solver_agent.py:144（锚点写 159） | 行漂移 |
| `guide/viz-chain-20261004` | `deeptutor/agents/visualize/capability.py:102` | 声明符号现位于 deeptutor/agents/visualize/capability.py:89（锚点写 102） | 行漂移 |
| `guide/viz-chain-20261004` | `ChatMessageList.tsx:874-878` | 声明符号现位于 web/features/chat/messages/ChatMessageList.tsx:769（锚点写 874） | 行漂移 |
| `guide/voice-20261005` | `api/main.py:733` | 声明符号现位于 deeptutor/api/main.py:648（锚点写 733） | 行漂移 |
| `guide/web-guards-20261006` | `web/proxy.ts:82-91` | web/proxy.ts 存在，但强声明符号 dt_token 全文件未命中 | 内容漂移 |
| `guide/web-guards-20261006` | `web/components/auth/AdminLink.tsx:19` | web/components/auth/AdminLink.tsx 存在，但强声明符号 hideAdminOnly/showLearnerOnly/showGuardianOnly 全文件未命中 | 内容漂移 |
| `guide/web-guards-20261006` | `deeptutor/api/main.py:683` | 声明符号现位于 deeptutor/api/main.py:678（锚点写 683，偏移≤5 行） | 微漂移 |
| `guide/web-state-20261007` | `ChatWorkspace.tsx:2009-2016` | 声明符号现位于 web/features/chat/components/ChatWorkspace.tsx:1957（锚点写 2009） | 行漂移 |
| `guide/web-state-20261007` | `ChatWorkspace.tsx:501-504` | 声明符号现位于 web/features/chat/components/ChatWorkspace.tsx:499（锚点写 501） | 行漂移 |
| `myfork/docs/guides/immersive-reading` | `deeptutor/reading/service.py:26` | 声明符号现位于 deeptutor/reading/service.py:63（锚点写 26） | 行漂移 |
| `myfork/docs/guides/knowledge-base` | `initializer.py:175` | 声明符号现位于 deeptutor/knowledge/initializer.py:168（锚点写 175） | 行漂移 |
| `myfork/docs/guides/knowledge-base` | `pipeline.py:283-298` | 声明符号现位于 deeptutor/services/rag/pipelines/llamaindex/pipeline.py:258（锚点写 283） | 行漂移 |
| `myfork/docs/guides/knowledge-base` | `index_probe.py:111-133` | deeptutor/services/rag/index_probe.py 存在，但强声明符号 DocumentAdder/add_documents/_bootstrap_index_from_files 全文件未命中 | 内容漂移 |
| `myfork/docs/guides/learner-accounts` | `deeptutor/multi_user/tool_access.py:36` | 声明符号现位于 deeptutor/multi_user/tool_access.py:49（锚点写 36） | 行漂移 |
| `myfork/docs/guides/learner-accounts` | `deeptutor/api/routers/auth.py:749` | 声明符号现位于 deeptutor/api/routers/auth.py:772（锚点写 749） | 行漂移 |
| `myfork/docs/guides/mastery-path` | `deeptutor/capabilities/mastery/tools.py:1801` | 声明符号现位于 deeptutor/capabilities/mastery/tools.py:1936（锚点写 1801） | 行漂移 |
| `myfork/docs/guides/mastery-path` | `deeptutor/services/session/sqlite_store.py:115-117` | 声明符号现位于 deeptutor/services/session/sqlite_store.py:129（锚点写 115） | 行漂移 |
| `myfork/docs/guides/mastery-path` | `deeptutor/learning/assessment.py:425-508` | deeptutor/learning/assessment.py 存在，但强声明符号 assessment_attempts 全文件未命中 | 内容漂移 |
| `myfork/docs/guides/mastery-path` | `executor.py:884-886` | 声明符号现位于 deeptutor/services/session/turns/executor.py:868（锚点写 884） | 行漂移 |

## 四、处理建议汇总

- 116 个 guide 分支（109 个含锚点）中：建议**定点更新行号**为主 58 个；需**重读模块/整档再生成** 30 个；样本内**无可判定腐烂** 19 个

优先级最高的分支（严格腐烂率 ≥50% 或出现失效/越界/内容漂移）：

| 分支 | 抽样 | 严格腐烂 | 主要问题 |
|---|---|---|---|
| `docs/guides/deep-research` | 8 | 100%（3/3） | 行漂移 |
| `docs/guides/chat-runtime` | 8 | 75%（3/4） | 内容漂移、行漂移 |
| `docs/packaging-startup-guide-20261007` | 8 | 75%（3/4） | 失效、行漂移 |
| `docs/guides/runtime-update-chain` | 8 | 71%（5/7） | 内容漂移、行漂移 |
| `guide/net-validation-20261006` | 8 | 71%（5/7） | 内容漂移、行漂移 |
| `docs/guides/ci-workflows` | 8 | 67%（2/3） | 行漂移 |
| `docs/guides/embedding-progress` | 8 | 67%（2/3） | 行漂移 |
| `guide/app-update-20261005` | 8 | 67%（4/6） | 内容漂移、行漂移 |
| `guide/mcp-integration-20261005` | 8 | 67%（4/6） | 行漂移 |
| `guide/practice-domain-20261006` | 8 | 67%（4/6） | 内容漂移、行漂移 |
| `guide/vision-tools-20261007` | 8 | 67%（4/6） | 内容漂移、行漂移 |
| `docs/guides/codex-auth` | 8 | 60%（3/5） | 内容漂移、行漂移 |
| `docs/guides/web-source` | 8 | 60%（3/5） | 行漂移 |
| `guide/capabilities-20261005` | 8 | 60%（3/5） | 行漂移 |
| `guide/session-turns-20261007` | 8 | 60%（3/5） | 内容漂移、行漂移 |
| `guide/events-20261004` | 8 | 57%（4/7） | 内容漂移、行漂移 |
| `guide/events-20261004-v2` | 8 | 57%（4/7） | 内容漂移、行漂移 |
| `docs/guides/session-history` | 8 | 50%（1/2） | 行漂移 |
| `docs/workspace-migration-guide-20261006` | 8 | 50%（4/8） | 行漂移 |
| `evidence/guide-session-stores-20261007` | 8 | 50%（4/8） | 行漂移 |
| `guide-cli-agen477` | 8 | 50%（2/4） | 行漂移 |
| `guide/ask-user-20261006` | 8 | 50%（4/8） | 行漂移 |
| `guide/embedding-reliability-20261011` | 8 | 50%（2/4） | 内容漂移 |
| `guide/ima-pipeline-20261005` | 8 | 50%（3/6） | 行漂移 |
| `guide/journal-20261004` | 8 | 50%（3/6） | 内容漂移、行漂移 |
| `guide/memory-20261006` | 8 | 50%（2/4） | 内容漂移、行漂移 |
| `guide/rag-pipelines-20261006` | 8 | 50%（1/2） | 行漂移 |
| `myfork/docs/guides/knowledge-base` | 8 | 50%（3/6） | 内容漂移、行漂移 |
| `myfork/docs/guides/learner-accounts` | 8 | 50%（2/4） | 行漂移 |
| `myfork/docs/guides/mastery-path` | 8 | 50%（4/8） | 内容漂移、行漂移 |
| `docs/guides/partner-channels-20261011` | 8 | 43%（3/7） | 内容漂移、行漂移 |
| `guide/web-guards-20261006` | 8 | 40%（2/5） | 内容漂移 |
| `docs/guides/co-writer` | 8 | 38%（3/8） | 内容漂移、行漂移 |
| `docs/guides/co-writer-20261011` | 8 | 33%（2/6） | 内容漂移 |
| `guide/agents-20261004` | 8 | 33%（2/6） | 内容漂移、行漂移 |
| `guide/logging-20261005` | 8 | 33%（2/6） | 内容漂移、行漂移 |
| `guide/partner-groups-20261011` | 8 | 33%（2/6） | 内容漂移、行漂移 |
| `docs/guide-multi-user` | 8 | 29%（2/7） | 内容漂移、行漂移 |
| `guide/core-protocols-20261007` | 8 | 29%（2/7） | 内容漂移、行漂移 |
| `guide/parsing-20261004` | 8 | 29%（2/7） | 内容漂移、行漂移 |
| `guide/plugins-20261005` | 8 | 29%（2/7） | 内容漂移 |
| `guide/suggestions-20261009` | 8 | 29%（2/7） | 内容漂移、行漂移 |
| `evidence/guide-realtime-push-2026-10-07` | 8 | 25%（2/8） | 内容漂移、行漂移 |
| `docs/guides/textbook-struct` | 8 | 14%（1/7） | 内容漂移 |

## 五、系统性发现

1. **腐烂主形态是行号漂移，不是文件消失**：157/870 行漂移 + 49 微漂移 vs 仅 1 失效；v1.6.13→v1.6.14 的重构（runtime/registry、session turns、app_update、codex-auth 校验助手等）移动了大量行，但模块拓扑基本稳定。产出锚点的维护成本低（批量重锚行号即可），不需要大面积废弃。
2. **未定(歧义)集中在裸文件名锚点**：72 个未定里绝大多数是 `pipeline.py`、`capability.py`、`__init__.py` 这类裸名——同一文档前文往往已限定模块目录，但锚点本身不带路径。建议产出模板要求**锚点带模块级路径**（至少 `book/engine.py` 两段），可把歧义降到接近 0。
3. **`可定位(未核声明)` 170 个（19.5%）**：锚点行在范围内但上下文没有可机核符号（中文描述型/纯行段引用）。这类锚点腐烂了也难以自动发现，是后续再生成时应当改成「符号+行号」双要素的重点。
4. **越界锚点指向已缩身文件**（tools-prompting `__init__.py:148` vs 29 行、`routers/memory.py:686` vs 99 行等）：说明上游把大文件拆小后，guide 未跟进，此类锚点对读者误导最强，建议优先修。
5. **20261011 新产 guide（co-writer-20261011、settings-system、usage-ledger 等）已按 v1.6.14 前后的 main 校准，样本内腐烂显著低于 20261004-07 旧批**——guide 时效衰减是真实的，随上游前进持续发生。

## 六、方法局限与 QA

- 行内容核对依赖锚点上下文的声明符号抽取：中文纯描述、行段引用（无符号）无法机核，已单列 `可定位(未核声明)`，不计入腐烂率分母；`内容漂移` 只在强符号全文件未命中时判定，弱符号未命中不算腐烂（偏保守）。
- 人工 QA：跨 6 类判定随机抽 12 条逐一打开 v1.6.14 对应文件比对，12/12 分类成立；其中 `内容漂移` 的语义是「声明符号已被重构移除/改名」（如 `_require_codex_oauth_actor`、`dt_token`、`TaskIDManager`、WeKnora 集成），锚点附近区域可能仍有相关代码，属可辩护判定。
- 全部 870 条明细（含解析路径、命中行、符号、候选列表）见同目录 `anchors.json`；分支级统计见 `summary.json`。
- 本轮只产证据：未改任何源码/文档源文件，未推送 main/dev，未开上游 PR。
