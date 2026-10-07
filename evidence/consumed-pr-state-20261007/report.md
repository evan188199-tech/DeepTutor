# consumed 台账 × 上游 PR 状态一致性复核（2026-10-07）

- 台账：`reserve/backlog/deeptour.consumed`（10 条 key）
- 方法：纯只读。gh 只读查询（`gh pr view` / `gh pr list` / `gh issue view` / `gh api`，快照 2026-10-07）+ 本地文件与本地 git ref 只读；未修改任何台账/储备文件；未推送、未开 PR、未改任何代码。
- 台账完整性：`deeptour.consumed` SHA256 `b076356a…974b7f26e`（复核前后一致）。
- 去重口径：只做 PR 状态轴。本地测试健康轴（verify-consumed-tests-green）、up-* 新鲜度轴（verify-backlog-freshness）、键一致性轴（verify-claims-ledger）不在本卡范围内，仅在引用处标注。

## 一、三类计数（有直接对应上游 PR 的 4 条）

| 分类 | 数量 | 条目 |
| --- | --- | --- |
| 闭环（已合并） | 3 | up-1646、up-1647、up-1678 |
| 仍开放 | 0 | — |
| 已关闭未合并 | 1 | rework-AGEN-136 |

无直接对应上游 PR 的 6 条（guide-mastery、guide-reading、bundle-logging-storage、bundle-logging-runtime、bundle-tests-backend、bundle-tests-frontend）单独列于第三节：其中 2 条（bundle-logging-*）被开放 PR #1703/#1704/#1707 部分覆盖，4 条完全无上游 PR。

## 二、状态对照表（台账 100% 覆盖，10/10）

| # | key | 对应上游 PR（head → base） | PR 状态 | 判定 | 证据（2026-10-07 快照） |
| --- | --- | --- | --- | --- | --- |
| 1 | up-1646 | #1685 `codex/fix/mastery-session-lock` → dev | MERGED（2026-10-04T06:19:37Z） | 闭环 | `gh pr view 1685`；上游 issue #1646 CLOSED/completed；标题含 (#1646) |
| 2 | up-1647 | #1666 `fix/chat-kb-ref-labels` → dev | MERGED（2026-10-04T06:06:25Z） | 闭环 | `gh pr view 1666`；上游 issue #1647 CLOSED/completed |
| 3 | up-1678 | #1683 `codex/fix/chat-history-search` → dev | MERGED（2026-10-04T06:01:26Z） | 闭环 | `gh pr view 1683`；上游 issue #1678 CLOSED/completed；commit `8535d8668` 已确认在 main（verify-consumed-tests-green 2026-10-05 结论引用，本次复核沿用） |
| 4 | rework-AGEN-136 | #1727 `fix/knowledge-surface-swallowed-failures` → main | CLOSED 未合并（createdAt 2026-10-05，closedAt 2026-10-06T05:09:35Z，mergeCommit 为空） | 已关闭未合并 | `gh pr view 1727`；作者关闭留言：“opened by mistake by an automated script and duplicates/supersedes other work”；补充核验：batch-1 开放 PR #1703/#1704/#1707 文件列表均不含 `knowledge.py`；main 与 dev 的 `deeptutor/api/routers/knowledge.py`（各 5037 行）均无 `_progress_age_seconds` 符号 → 修复内容未在任何 PR 落地 |
| 5 | guide-mastery | 无（`gh pr list --head docs/guides/mastery-path` 为空；开放 PR 标题扫描无 mastery 导读） | — | 无上游 PR | myfork 分支 `docs/guides/mastery-path` 存在（head `fcb131a96`，2026-10-02，docs-only） |
| 6 | guide-reading | 无（`--head docs/guides/immersive-reading` 为空） | — | 无上游 PR | myfork 分支 `docs/guides/immersive-reading` 存在（head `787ddd799`，2026-10-02，docs-only） |
| 7 | bundle-logging-storage | 无直接 PR；部分内容在开放 PR #1703（7 files）/ #1707（11 files），覆盖 storage 8 源分支中的 5 条 | OPEN | 未闭环（直接产物分支未建） | `gh pr view 1703/1704/1707`（均 OPEN，head `pr/rag-log-…`/`pr/runtime-log-…`/`pr/services-log-…`，author evan188199-tech）；覆盖计数引自 verify-consumed-tests-green（2026-10-05）结论，本卡未重跑集成 |
| 8 | bundle-logging-runtime | 无直接 PR；部分内容在开放 PR #1704（8 files）/ #1707，覆盖 runtime 7 源分支中的 6 条 | OPEN | 未闭环（直接产物分支未建） | 同上 |
| 9 | bundle-tests-backend | 无（`--head test/backend-coverage-batch-1` 为空） | — | 无上游 PR | 卡已取消、产物分支未建（verify-consumed-tests-green 2026-10-05 结论：按卡定义 cherry-pick 10 源分支到 main 集成 195 passed，但仅临时 worktree，未落分支） |
| 10 | bundle-tests-frontend | 无 | — | 台账幽灵条目 | 无卡、无 ledger 定义、无分支，仅出现在 consumed 清单（verify-consumed-tests-green 2026-10-05 判定 skip） |

## 三、无直接上游 PR 条目说明

- **guide-mastery / guide-reading**：交付物为 docs-only myfork 分支（`docs/guides/mastery-path`、`docs/guides/immersive-reading`），按储备规则“不向上游开 PR，由人决定”。同批 guide 分支已有先例：#1716/#1717 OPEN，#1735/#1777/#1722 CLOSED 未合并——是否提交这两份导读由人决定。
- **bundle-logging-storage / bundle-logging-runtime**：直接产物分支从未建立，内容以“源分支 cherry-pick”形式存在于临时 worktree（已清理）；对应主题已由人工整理的开放 PR #1703/#1704/#1707 承接大部分条目，剩余未覆盖条目见第四节。
- **bundle-tests-backend**：卡已取消，产物分支未建，无 PR，无遗留。
- **bundle-tests-frontend**：consumed 台账中的幽灵条目（无对应卡/分支/定义），属台账质量问题，本卡只读不改，列入跟进。

## 四、需人工跟进清单（按优先级）

1. **rework-AGEN-136（高）**：PR #1727 被作者以“自动化脚本误开”为由关闭，但其中的知识库可观测性修复（AGEN-134/135/136 合集，`update_kb_status` 写失败可见化 + progress WS 吞错治理）**未在任何合并或开放 PR 中覆盖**（main/dev 均无对应符号，batch-1 PR 不含 knowledge.py）。myfork 分支 `fix/knowledge-surface-swallowed-failures` 仍在。→ 由人决定：基于该分支重开 PR，或明确放弃。
2. **bundle-tests-frontend（中）**：consumed 台账幽灵条目，建议人工清理台账或在储备池补一张可定义的卡。
3. **bundle-logging-storage / bundle-logging-runtime（中）**：开放 PR #1703/#1704/#1707 未覆盖的剩余源条目——storage：migration-deps-158、folder-sync-state、quiz-followup-writeback；runtime：sandbox-rlimit-v2。是否补齐由人决定（计数引自 2026-10-05 verify 结论，建议决策前重跑一次 merge-tree 静态检查确认时效）。
4. **guide-mastery / guide-reading（低）**：两份 docs-only 导读仍在 myfork，未开上游 PR；如需提交可参考同批 guide PR 先例。

## 五、复核命令（全部只读）

- `gh pr view 1685|1666|1683|1727 -R HKUDS/DeepTutor --json number,title,state,mergedAt,closedAt,headRefName,baseRefName,mergeCommit,url`
- `gh pr list -R HKUDS/DeepTutor --author evan188199-tech --state all --limit 300`（287 条，逐条按 head/title 关键词匹配 7 个非 up-* key）
- `gh pr list -R HKUDS/DeepTutor --state all --head <branch>`（docs/guides/mastery-path、docs/guides/immersive-reading、fix/knowledge-surface-swallowed-failures、test/backend-coverage-batch-1）
- `gh issue view 1646|1647|1678 -R HKUDS/DeepTutor --json state,stateReason`
- `gh pr view 1703|1704|1707 --json files`；`gh api repos/HKUDS/DeepTutor/contents/deeptutor/api/routers/knowledge.py?ref=main|dev`
- 本地：`git -C /Users/Shared/DeepTutor for-each-ref`（只读）、储备目录文件 SHA256

机读快照见同目录 `snapshot.json`；校验和见 `SHA256SUMS`。
