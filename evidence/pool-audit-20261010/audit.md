# 候选池 up-* 上游对账审计（2026-10-10）

对 `reserve/backlog/` 目录三个 jsonl（`deeptour.jsonl`、`deeptour.auto.jsonl`、`deeptour.0priority.jsonl`）中全部 `up-<n>` 键，逐个核对 HKUDS/DeepTutor 上游 issue 当前状态与关联 PR，产出三态结论。本次只新增本 evidence 文件，未改动 backlog 与任何代码。

## 口径

- `fixed_by_pr`：该 issue 存在已合并（MERGED）的上游关联 PR（cross-reference / linked timeline），无论 issue 本身是否仍 open —— 即口径样例 #641/#640/#199/#486/#375 的情形。
- `closed`：issue 已 CLOSED（stateReason 均为 COMPLETED）且无已合并关联 PR。9 例均经 REST timeline 复核为维护者直接 commit 推送 main 后关闭（commit 不附属于任何 PR）。
- `still_valid`：issue 仍 OPEN 且无已合并关联 PR（备注列给出是否有 open PR 进行中）。

## 汇总

- 覆盖 `up-*` 键：84（deeptour.jsonl 8 + deeptour.auto.jsonl 76；0priority 无 up-* 键；三文件无重复键）
- fixed_by_pr（已被 PR 修复）：**51**
- closed（已关闭）：**9**
- still_valid（仍有效）：**24**

可修剪建议（人工执行，本次未删任何行）：`fixed_by_pr` 与 `closed` 共计 60 行可移出候选池；其中 up-1646/up-1647/up-1678 同时出现在 deeptour.consumed。

## 查询方法（可复查）

- issue 状态与关联 PR：GraphQL `repository.issue(number) { state stateReason timelineItems(itemTypes: [CROSS_REFERENCED_EVENT, CONNECTED_EVENT]) }`，84 个键按 12 个/请求分 7 批拉取。
- 9 个 closed 例的复核：REST `issues/<n>/timeline`（closed/referenced 事件与 commit_id）+ `commits/<sha>/pulls`（确认 pr_count=0，即直接提交）。
- 数据快照时间：2026-10-10。

## 一、已被 PR 修复（fixed_by_pr）

| key | issue | issue 状态 | 池文件 | 备注 | 证据 |
|-----|-------|-----------|--------|------|------|
| up-429 | #429 | OPEN | deeptour.auto.jsonl | [Feature Request]: add epub support for knowledge base | issue OPEN; merged upstream PR: #843 merged 2026-08-16 |
| up-431 | #431 | OPEN | deeptour.auto.jsonl | [Question]:Cannot process scanned PDF in Knowledge Base - "Skipped empty document" error | issue OPEN; merged upstream PR: #1073 merged 2026-08-29; #1386 merged 2026-09-23 |
| up-440 | #440 | OPEN | deeptour.auto.jsonl | [Question]:Search failed (invalid_embedding_index): RAG index contains invalid embedding vectors | issue OPEN; merged upstream PR: #1702 merged 2026-10-07 |
| up-473 | #473 | OPEN | deeptour.auto.jsonl | [Feature Request]: Chapter map - headlines are cut off | issue OPEN; merged upstream PR: #889 merged 2026-08-16 |
| up-745 | #745 | OPEN | deeptour.auto.jsonl | [Bug]: GraphRAG request configuration diverges from DeepTutor chat and embedding profiles | issue OPEN; merged upstream PR: #747 merged 2026-08-16 |
| up-860 | #860 | OPEN | deeptour.auto.jsonl | feat(reading): complete bilingual EPUB study experience | issue OPEN; merged upstream PR: #979 merged 2026-08-25 |
| up-916 | #916 | OPEN | deeptour.auto.jsonl | feat(reading): improve mobile bilingual immersive reading UX | issue OPEN; merged upstream PR: #1464 merged 2026-09-23; #1734 merged 2026-10-07 |
| up-971 | #971 | OPEN | deeptour.auto.jsonl | feat(reading): finish selector re-anchoring for structured revisions | issue OPEN; merged upstream PR: #972 merged 2026-08-25; #974 merged 2026-08-25; #1376 merged 2026-09-23 |
| up-1109 | #1109 | OPEN | deeptour.auto.jsonl | feat(learner): add account-scoped reading learning records | issue OPEN; merged upstream PR: #1368 merged 2026-09-23 |
| up-1176 | #1176 | CLOSED/COMPLETED | deeptour.auto.jsonl | [Feature Request]: Allow response language other than English and Chinese | issue CLOSED(COMPLETED); merged upstream PR: #1345 merged 2026-09-23 |
| up-1209 | #1209 | OPEN | deeptour.auto.jsonl | Settings: capability readiness overview, cross-setting contradiction checks, and value-free profile export | issue OPEN; merged upstream PR: #1381 merged 2026-09-23; #1383 merged 2026-09-23 |
| up-1220 | #1220 | OPEN | deeptour.auto.jsonl | [Bug]: gpt-5.6-terra model not working | issue OPEN; merged upstream PR: #1401 merged 2026-09-13; #1694 merged 2026-10-04 |
| up-1222 | #1222 | CLOSED/COMPLETED | deeptour.auto.jsonl | [Bug]: Learning accounts — the policy reaches the client but nothing reads it, and CI cannot see the fallout | issue CLOSED(COMPLETED); merged upstream PR: #1323 merged 2026-09-23; #1375 merged 2026-09-23; #1652 merged 2026-10-04; #1783 merged 2026-10-07 \| fork PR (non-upstream): #15 OPEN; #19 OPEN |
| up-1223 | #1223 | OPEN | deeptour.auto.jsonl | [Bug]: PDF uploads in chat dont get easily read in next message in same chat because of tool error | issue OPEN; merged upstream PR: #1266 merged 2026-09-07; #1333 merged 2026-09-10; #1443 merged 2026-09-13 |
| up-1228 | #1228 | OPEN | deeptour.auto.jsonl | Learner accounts get 403 on /api/courses — and the UI masks it as an empty state | issue OPEN; merged upstream PR: #1231 merged 2026-09-07 |
| up-1244 | #1244 | OPEN | deeptour.auto.jsonl | Feature: let Partner conversations record wrong questions into the Question Notebook | issue OPEN; merged upstream PR: #1341 merged 2026-09-19 |
| up-1254 | #1254 | OPEN | deeptour.auto.jsonl | Watching: align active transcript with video captions and center on mobile | issue OPEN; merged upstream PR: #1351 merged 2026-09-10 |
| up-1256 | #1256 | OPEN | deeptour.auto.jsonl | Watching notes: preserve capture timestamps and drafts across async saves | issue OPEN; merged upstream PR: #1350 merged 2026-09-10 |
| up-1296 | #1296 | CLOSED/COMPLETED | deeptour.auto.jsonl | [Feature Request]: Automatically discover the Codex client version for model catalog refresh | issue CLOSED(COMPLETED); merged upstream PR: #1317 merged 2026-09-23 |
| up-1303 | #1303 | CLOSED/COMPLETED | deeptour.auto.jsonl | feat(knowledge): add Zotero integration with BibTeX parsing and library search | issue CLOSED(COMPLETED); merged upstream PR: #1371 merged 2026-09-23 |
| up-1326 | #1326 | CLOSED/COMPLETED | deeptour.auto.jsonl | [Feature Request]: Expose local folder linking and sync controls in the Knowledge Center UI | issue CLOSED(COMPLETED); merged upstream PR: #1372 merged 2026-09-23 |
| up-1329 | #1329 | CLOSED/COMPLETED | deeptour.auto.jsonl | feat(users): add batch import and deletion | issue CLOSED(COMPLETED); merged upstream PR: #1330 merged 2026-09-23 |
| up-1336 | #1336 | CLOSED/COMPLETED | deeptour.auto.jsonl | [Feature Request]:[Notebook/UX] Note "edit" is buried in the ⋮ menu while the pencil at top only renames the notebook | issue CLOSED(COMPLETED); merged upstream PR: #1339 merged 2026-09-23 |
| up-1359 | #1359 | CLOSED/COMPLETED | deeptour.auto.jsonl | [Bug]:主页聊天窗口调用 ask_user 后卡片报错且主对话被锁死 | issue CLOSED(COMPLETED); merged upstream PR: #1373 merged 2026-09-23; #1413 merged 2026-09-13 |
| up-1389 | #1389 | CLOSED/COMPLETED | deeptour.auto.jsonl | [Feature Request]: Recycle Bin | issue CLOSED(COMPLETED); merged upstream PR: #1398 merged 2026-09-13; #1615 merged 2026-10-04 |
| up-1390 | #1390 | CLOSED/COMPLETED | deeptour.auto.jsonl | [Feature Request]: Resend for failed chat requests | issue CLOSED(COMPLETED); merged upstream PR: #1394 merged 2026-09-23 |
| up-1405 | #1405 | CLOSED/COMPLETED | deeptour.auto.jsonl | [Feature Request]: Import ChatGPT conversation exports | issue CLOSED(COMPLETED); merged upstream PR: #1408 merged 2026-09-23 |
| up-1410 | #1410 | CLOSED/COMPLETED | deeptour.auto.jsonl | [Bug]: v1.6.7 Chat history lost inside session | issue CLOSED(COMPLETED); merged upstream PR: #1723 merged 2026-10-07 |
| up-1421 | #1421 | CLOSED/COMPLETED | deeptour.auto.jsonl | [Bug]:v1.6.6第一次使用进入时发的第一句话会卡循环很久，重启后恢复正常 | issue CLOSED(COMPLETED); merged upstream PR: #1436 merged 2026-09-13 |
| up-1447 | #1447 | CLOSED/COMPLETED | deeptour.auto.jsonl | [Feature & Bugfix] Reading Workspace Enhancements: Real-time TOC Tracking, EPUB Formatting Toolbar & Themes, Configurable Single/Two-Page Spread Layout, EPUB Archive Normalization ("Could not load this section"), and Navigation Prefetch Optimization | issue CLOSED(COMPLETED); merged upstream PR: #1455 merged 2026-09-23; #1472 merged 2026-09-23 |
| up-1476 | #1476 | CLOSED/COMPLETED | deeptour.auto.jsonl | feat(learning): persist mastery prerequisites and topic-source links | issue CLOSED(COMPLETED); merged upstream PR: #1477 merged 2026-09-23 |
| up-1478 | #1478 | CLOSED/COMPLETED | deeptour.auto.jsonl | LlamaIndex re-index can leak stale embedding progress after a timeout | issue CLOSED(COMPLETED); merged upstream PR: #1480 merged 2026-09-23 |
| up-1481 | #1481 | CLOSED/COMPLETED | deeptour.auto.jsonl | [Bug]: Creating an empty knowledge base and then uploading documents always fails with "Knowledge base not initialized (llamaindex)" | issue CLOSED(COMPLETED); merged upstream PR: #1488 merged 2026-09-23 |
| up-1613 | #1613 | CLOSED/COMPLETED | deeptour.auto.jsonl | [Bug]:切换到自定义工作区后，子Agent都无法访问 | issue CLOSED(COMPLETED); merged upstream PR: #1625 merged 2026-10-04 |
| up-1614 | #1614 | CLOSED/COMPLETED | deeptour.auto.jsonl | [Bug] 1.6.x renders only the first ~7 rounds of a long chat session, and the assistant loses all later context | issue CLOSED(COMPLETED); merged upstream PR: #1619 merged 2026-10-04 |
| up-1623 | #1623 | CLOSED/COMPLETED | deeptour.jsonl | [Bug]:内部含有回车的数学公式有时无法正常渲染 | issue CLOSED(COMPLETED); merged upstream PR: #1627 merged 2026-10-04 |
| up-1624 | #1624 | CLOSED/COMPLETED | deeptour.jsonl | [Bug]: Mastery Path quiz answers trigger context-free KB retrieval using option letters | issue CLOSED(COMPLETED); merged upstream PR: #1626 merged 2026-10-04 |
| up-1630 | #1630 | CLOSED/COMPLETED | deeptour.auto.jsonl | [Bug]: 伙伴与智能体 CLI 应用的模型/推理强度配置无法保存（settings draft extensions.subagent:* 从未落地） | issue CLOSED(COMPLETED); merged upstream PR: #1634 merged 2026-10-04; #1745 merged 2026-10-07 |
| up-1641 | #1641 | CLOSED/COMPLETED | deeptour.jsonl | [Bug]:Fresh `.md` uploads open as a single page in Immersive Reading (v1.6.12) | issue CLOSED(COMPLETED); merged upstream PR: #1783 merged 2026-10-07 |
| up-1646 | #1646 | CLOSED/COMPLETED | deeptour.jsonl | [Bug]: Deleting a Mastery session can leave an orphaned turn holding the workspace activity lock | issue CLOSED(COMPLETED); merged upstream PR: #1685 merged 2026-10-04 \| also in deeptour.consumed |
| up-1647 | #1647 | CLOSED/COMPLETED | deeptour.jsonl | [Bug]: Chat message knowledge-base labels display internal resource IDs instead of names | issue CLOSED(COMPLETED); merged upstream PR: #1666 merged 2026-10-04 \| also in deeptour.consumed |
| up-1648 | #1648 | CLOSED/COMPLETED | deeptour.jsonl | [Bug]: ask_user Submit during a WebSocket reconnect gives up after 2s (10x200ms) while the reconnect ladder waits up to 8s — and reports a false "question is no longer active" | issue CLOSED(COMPLETED); merged upstream PR: #1668 merged 2026-10-04 |
| up-1673 | #1673 | CLOSED/COMPLETED | deeptour.jsonl | [Bug]: EPUB reader loses TOC heading anchors and mislabels reading positions | issue CLOSED(COMPLETED); merged upstream PR: #1686 merged 2026-10-04 |
| up-1676 | #1676 | CLOSED/COMPLETED | deeptour.auto.jsonl | [Bug]: Tutor selection fails on complex rendered LaTeX | issue CLOSED(COMPLETED); merged upstream PR: #1682 merged 2026-10-04 |
| up-1678 | #1678 | CLOSED/COMPLETED | deeptour.jsonl | [Bug]: v1.6.12 Chat history search fails — existing text cannot be matched | issue CLOSED(COMPLETED); merged upstream PR: #1683 merged 2026-10-04 \| also in deeptour.consumed |
| up-1691 | #1691 | CLOSED/COMPLETED | deeptour.auto.jsonl | [Bug]:在”精通之道“的学习过程中，如果出选择题做测验，答案全部是A | issue CLOSED(COMPLETED); merged upstream PR: #1692 merged 2026-10-04 |
| up-1779 | #1779 | CLOSED/COMPLETED | deeptour.auto.jsonl | [Bug]:EmbeddingClient 的进程级全局锁把所有 embedding 请求串行化，batch_delay=0 时也生效，摧毁并发并导致 LightRAG 索引超时 | issue CLOSED(COMPLETED); merged upstream PR: #1783 merged 2026-10-07 |
| up-1781 | #1781 | CLOSED/COMPLETED | deeptour.auto.jsonl | [Bug]: Multi-turn qualitative repair compounds SRS lapses within minutes | issue CLOSED(COMPLETED); merged upstream PR: #1794 merged 2026-10-07 |
| up-1782 | #1782 | CLOSED/COMPLETED | deeptour.auto.jsonl | [Bug]: Knowledge base (LllamaIndex) initialization fails with "Embedding API key not set. Configure the active profile in Settings > Embedding models." | issue CLOSED(COMPLETED); merged upstream PR: #1783 merged 2026-10-07 |
| up-1784 | #1784 | CLOSED/COMPLETED | deeptour.auto.jsonl | [Bug]: Existing Mastery Path maps with more than 7 objectives in a module cannot be edited | issue CLOSED(COMPLETED); merged upstream PR: #1790 merged 2026-10-07 |
| up-1792 | #1792 | CLOSED/COMPLETED | deeptour.auto.jsonl | [Bug]: Hybrid retrieval silently degrades to vector-only on Python 3.14 — no warning, despite `hybrid` being the default | issue CLOSED(COMPLETED); merged upstream PR: #1801 merged 2026-10-07 |

## 二、已关闭（closed）

| key | issue | issue 状态 | 池文件 | 备注 | 证据 |
|-----|-------|-----------|--------|------|------|
| up-1307 | #1307 | CLOSED/COMPLETED | deeptour.auto.jsonl | feat(plugins): add managed third-party plugin platform | issue CLOSED(COMPLETED) at 2026-10-08T00:50:36Z; no merged upstream PR; closed via direct commit 7885daa on main (commit not attached to any PR) |
| up-1407 | #1407 | CLOSED/COMPLETED | deeptour.auto.jsonl | feat(learning): a read-only journal overview panel for mission and handoff (Part of #740) | issue CLOSED(COMPLETED) at 2026-10-07T19:11:53Z; no merged upstream PR; closed via direct commit 64bc0d8 on main (commit not attached to any PR) |
| up-1419 | #1419 | CLOSED/COMPLETED | deeptour.auto.jsonl | feat(reading): add age-aware action button presentation | issue CLOSED(COMPLETED) at 2026-10-07T15:05:18Z; no merged upstream PR; closed via direct commit 2352059 on main (commit not attached to any PR) |
| up-1610 | #1610 | CLOSED/COMPLETED | deeptour.auto.jsonl | [Bug/Enhancement]: Complete textbook grounding beyond the 64-figure cap: extraction fidelity and reliable retrieval | issue CLOSED(COMPLETED) at 2026-10-07T19:45:04Z; no merged upstream PR; closed via direct commit 30022c7 on main (commit not attached to any PR); open upstream PR still active: #1695 |
| up-1611 | #1611 | CLOSED/COMPLETED | deeptour.auto.jsonl | [Feature Request]: Reliable source-grounded teaching and visual practice with trustworthy assessment and learning progress | issue CLOSED(COMPLETED) at 2026-10-07T21:26:05Z; no merged upstream PR; closed via direct commit 8be71a3 on main (commit not attached to any PR) |
| up-1629 | #1629 | CLOSED/COMPLETED | deeptour.auto.jsonl | [Feature Request]: Native Integration of Scientific Research Primitives (Feynman / arXiv Workflows) | issue CLOSED(COMPLETED) at 2026-10-08T02:06:16Z; no merged upstream PR; closed via direct commit 1e7eef0 on main (commit not attached to any PR) |
| up-1696 | #1696 | CLOSED/COMPLETED | deeptour.auto.jsonl | [Bug]: Windows path separators cause architecture-contracts and internal-route-contract test failures in web/tests | issue CLOSED(COMPLETED) at 2026-10-04T10:22:52Z; no merged upstream PR; closed via direct commit aa498ff on main (commit not attached to any PR); open upstream PR still active: #1698 |
| up-1793 | #1793 | CLOSED/COMPLETED | deeptour.auto.jsonl | [Bug]: IndentationError and NameError in Document Parsing service | issue CLOSED(COMPLETED) at 2026-10-07T17:23:34Z; no merged upstream PR; closed via direct commit d15e35a on main (commit not attached to any PR) |
| up-1795 | #1795 | CLOSED/COMPLETED | deeptour.auto.jsonl | [Bug]: Interrupted shutdown orphans the backend; a non-interactive restart then exits instead of reclaiming it — under launchd this loops forever | issue CLOSED(COMPLETED) at 2026-10-07T15:25:51Z; no merged upstream PR; closed via direct commit 4e7a43b on main (commit not attached to any PR) |

## 三、仍有效（still_valid）

| key | issue | issue 状态 | 池文件 | 备注 | 证据 |
|-----|-------|-----------|--------|------|------|
| up-366 | #366 | OPEN | deeptour.auto.jsonl | [Feature Request]:responsive design for mobile devices | issue OPEN; no upstream linked PR (merged/open none) |
| up-397 | #397 | OPEN | deeptour.auto.jsonl | [RFC]: 关于DeepTutor下一代Memory架构思考 \| Thoughts on DeerTutor's Next-Generation Memory Architecture | issue OPEN; no upstream linked PR (merged/open none) |
| up-403 | #403 | OPEN | deeptour.auto.jsonl | [Feature Request]: Projects — Grouped Workspaces with Persistent Custom Instructions | issue OPEN; no upstream linked PR (merged/open none) |
| up-451 | #451 | OPEN | deeptour.auto.jsonl | [Feature Request]:如何禁用周期性的 LLM 健康检查以避免消耗 token？ | issue OPEN; no upstream linked PR (merged/open none) |
| up-567 | #567 | OPEN | deeptour.auto.jsonl | [Feature Request]: LTI Integration | issue OPEN; no upstream linked PR (merged/open none) |
| up-575 | #575 | OPEN | deeptour.auto.jsonl | [Bug]:一些聊天中显示的问题和出题无法被记录的bug | issue OPEN; no upstream linked PR (merged/open none) |
| up-612 | #612 | OPEN | deeptour.auto.jsonl | [Question]:persistence问题，用户数据长期是否考虑数据库方案，如pg | issue OPEN; no upstream linked PR (merged/open none) |
| up-655 | #655 | OPEN | deeptour.auto.jsonl | 优化建议 | issue OPEN; no upstream linked PR (merged/open none) |
| up-684 | #684 | OPEN | deeptour.auto.jsonl | [Feature Request]: Multi-language integration | issue OPEN; no upstream linked PR (merged/open none) |
| up-932 | #932 | OPEN | deeptour.auto.jsonl | feat(reading): add chapter-scoped character and entity relationship graph | issue OPEN; no upstream linked PR (merged/open none) |
| up-961 | #961 | OPEN | deeptour.auto.jsonl | feat(plugins): add pluggable learning resource providers with lifecycle controls | issue OPEN; no upstream linked PR (merged/open none) |
| up-1158 | #1158 | OPEN | deeptour.auto.jsonl | feat(video-learning): add recent video summaries | issue OPEN; no upstream linked PR (merged/open none) |
| up-1215 | #1215 | OPEN | deeptour.auto.jsonl | fix(ci): restore dev route budgets | issue OPEN; open upstream PR in progress: #1219 https://github.com/HKUDS/DeepTutor/pull/1219 \| fork PR (non-upstream): #15 OPEN |
| up-1236 | #1236 | OPEN | deeptour.auto.jsonl | feat(reading): render EPUBs as responsive book spreads | issue OPEN; no upstream linked PR (merged/open none) |
| up-1238 | #1238 | OPEN | deeptour.auto.jsonl | feat(video-learning): give Immersive Watching a dedicated workspace | issue OPEN; no upstream linked PR (merged/open none) \| fork PR (non-upstream): #15 OPEN |
| up-1246 | #1246 | OPEN | deeptour.auto.jsonl | feat(watching): integrate fullscreen learning and source-timed two-line captions | issue OPEN; no upstream linked PR (merged/open none) |
| up-1901 | #1901 | OPEN | deeptour.auto.jsonl | [Enhancement]: Meaning-based visual and source-dependent assessment beyond answer aliases in Mastery Path | issue OPEN; no upstream linked PR (merged/open none) |
| up-1902 | #1902 | OPEN | deeptour.auto.jsonl | [Enhancement]: Mastery Path lesson preparation that selects the right evidence without slowing every turn | issue OPEN; no upstream linked PR (merged/open none) |
| up-1903 | #1903 | OPEN | deeptour.auto.jsonl | [Critical bug]: Local MinerU indexing can hang after CLI termination on Windows | issue OPEN; no upstream linked PR (merged/open none) |
| up-1907 | #1907 | OPEN | deeptour.auto.jsonl | [Bug]: Usage statistics always shows "Unable to load usage statistics. Retry." | issue OPEN; no upstream linked PR (merged/open none) |
| up-1908 | #1908 | OPEN | deeptour.auto.jsonl | [Feature Request]: Support fully customizable review frequency strategies | issue OPEN; no upstream linked PR (merged/open none) |
| up-1909 | #1909 | OPEN | deeptour.auto.jsonl | [Bug]: History compaction counts repeated images before the request-only deduplication from #1714 | issue OPEN; open upstream PR in progress: #1910 https://github.com/HKUDS/DeepTutor/pull/1910 |
| up-1912 | #1912 | OPEN | deeptour.auto.jsonl | [Bug]: Transient Windows file locks can abort indexing journal safety checks | issue OPEN; no upstream linked PR (merged/open none) |
| up-1914 | #1914 | OPEN | deeptour.auto.jsonl | [Enhancement]: Optimize the retry logic after Manim generation fails | issue OPEN; no upstream linked PR (merged/open none) |

