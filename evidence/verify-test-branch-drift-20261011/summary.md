# verify-test-branch-drift 复核结论（20261011）

- 基线 `origin/main` `6cf793bd8`（v1.6.14）；fetch origin+myfork 后实测 `origin/main` == `origin/dev` == `6cf793bd8`
- 口径对齐 `evidence/verify-channel-fix-branches-20261011/summary.md`：逐分支与 main diff，`git cherry` 复证
- 范围：`refs/remotes/myfork/` 测试类分支共 548 个——`test/*`、`web/tests/*`、`tests/*`、`codex/test/*`、`myfork/test/*`、`agent/agen*`，及名称以 `test-` 开头或含 `-tests` 者；去重排除 verify-channel-fix-branches 已覆盖的 `agent/agen1497-inbound-dedup`、`agent/agen1499-send-timeouts`
- 判定：以各分支与 main 的 merge-base 为起点取分支自身改动；新增(A)文件按 blob 全等判吸收，修改(M)文件按行级判吸收（main 含其全部新增行且不含被删行）；`evidence/`、`AGENTS.md` 等内部 meta 单列不计入判定。全程只读，未 checkout/reset/clean 任何既有工作区与分支
- 汇总：**landed 28 / no-op 11 / drift 8 / missing 501**；全量逐分支结论与 diff 统计见同目录 `branches.tsv`（548 行）

## landed（28，测试内容已在 main，可关账）

  `agent/book-engine-stage-tests`、`agent/book-engine-stage-tests-pr`（仅 meta 残留）、`agent/dt22-file-library-deletion-tests-v2`
  `codex/test/multiworker-reply-subscription`、`codex/test/partners-auth-isolation`、`fix/tz-stable-runtime-context-tests-v2`
  `myfork/test/co-writer-contract-20261003`（仅 meta 残留）、`myfork/test/memory-graph-20261003`（仅 meta 残留）、`myfork/test/memory-graph-20261003-pr`（仅 meta 残留）
  `myfork/test/memory-router-contract-20261003`、`myfork/test/memory-router-contract-20261003-pr`（仅 meta 残留）、`myfork/test/pocketbase-store-fallbacks-20261003`（仅 meta 残留）
  `myfork/test/pocketbase-store-fallbacks-20261003-pr`（仅 meta 残留）、`myfork/test/quiz-viewer-smoke-20261003`（仅 meta 残留）、`myfork/test/settings-store-20261003`（仅 meta 残留）
  `test/epub-bilingual-unit-20261004`、`test/learning-records-access-20261004`、`test/notebook-api-contract-20261003-pr`（仅 meta 残留）
  `test/question-mimic-ws-error-paths-20261004`、`test/reading-progress-api-contract`（仅 meta 残留）、`test/reading-progress-api-contract-pr`（仅 meta 残留）
  `test/settings-store-20261003-pr`（仅 meta 残留）、`test/standalone-composer-smoke-20261004`（仅 meta 残留）、`test/subagent-settings-apply-1630`
  `test/tex-tools-20261004`（仅 meta 残留）、`test/tex-tools-20261004-v2`、`test/visualization-viewer-20261004`（仅 meta 残留）
  `tests/spine-synthesizer-20261003-pr`（仅 meta 残留）

（meta 残留 = 仅 `evidence/` 等内部文件未随行进 main，属预期，不构成续放项）

## no-op（11，分支树与 merge-base 相同，无可续放内容，建议清理）

  `agent/agen1109-verify-todo-high`、`agent/agen370-broad-except-scan`、`agent/agen421-ts-catch-scan`
  `agent/agen453-async-task-scan`、`agent/agen548-deadcode-scan`、`agent/agen663-cli-surface`
  `agent/agen666-dt22-drift-scan`、`codex/test/subagent-settings-draft`、`scan/flaky-tests-20261006`
  `scan/orphan-tests-20261010`、`test/mastery-review-trail-scroll-cap`

## drift（8，部分吸收；剩余部分需 rebase 后重放）

| 分支 | 头 | 吸收/总 | 部分 | 缺失 | 未吸收要点 |
|---|---|---|---|---|---|
| `myfork/test/quiz-judge-unit-20261003` | `8aaf28d9f` | 1/2 | 1 | 0 | tests/api/routers/test_quiz_judge_unit.py |
| `myfork/test/quiz-judge-unit-20261003-pr` | `6d972d608` | 1/2 | 1 | 0 | tests/api/routers/test_quiz_judge_unit.py |
| `myfork/test/telegram-message-parsing-20261003` | `7b5274279` | 1/2 | 1 | 0 | deeptutor/partners/channels/telegram.py |
| `test/login-rate-limit-20261007` | `d76bc66e3` | 1/135 | 81 | 53 | CONTRIBUTING.md；Dockerfile… |
| `test/question-tee-stdout-write-20261003` | `b27d2b686` | 1/2 | 0 | 1 | tests/api/routers/test_question_tee_write.py |
| `test/telegram-message-parsing-20261003-v2` | `7b5274279` | 1/2 | 1 | 0 | deeptutor/partners/channels/telegram.py |
| `test/upload-bounds-20261004-v2` | `cd7a18e63` | 6/7 | 1 | 0 | tests/api/test_knowledge_upload_guards.py |
| `test/watching-migration-review-20261010` | `2d619dc8c` | 16/66 | 31 | 19 | README.md；deeptutor/api/routers/sessions.py… |

## missing（501，测试/产品内容全不在 main，均为续放候选；逐分支 diff 统计见 `branches.tsv`）

- `web/tests/*`：22 个，全数未落
  `web/tests/chat-home-selectors-20261010`、`web/tests/guardian/structure-20261009`
  `web/tests/hooks/card-submission-setup-sync-20261009`、`web/tests/i18n/i18n-provider.spec.tsx`
  `web/tests/learning-practice-review-20261010`、`web/tests/lib/book-refs-errors`
  `web/tests/lib/session-handoff-uuid`、`web/tests/lib/tool-event-settings`
  `web/tests/lib/workspace-drafts-presets-20261009`、`web/tests/misc-hooks-textarea-selection`
  `web/tests/notebook-selection-knowledge-history-20261009`、`web/tests/partner-pickers-20261010`
  `web/tests/partners-schema-form-20261009`、`web/tests/reading/workspace-hooks-20261009`
  `web/tests/research-outline-mdcore-20261009`、`web/tests/settings/usage-components`
  `web/tests/sidebar-resize-hooks-20261009`、`web/tests/topic-source-library-20261009`
  `web/tests/use-consultation-reference-20261009`、`web/tests/use-runtime-status-split-pane-20261009`
  `web/tests/voice/hooks-20261009`、`web/tests/watching-marks-panel-20261010`
- `agent/*`：17 个
  `agent/agen1031-llm-clients-guide`、`agent/agen1189-memory-graph-panel-tests`
  `agent/agen350-1359-verify`、`agent/agen412-docx-converter-edge-tests`
  `agent/agen539-upload-residue-cleanup`、`agent/agen720-docx-style-run-fallback`
  `agent/agen724-reading-ref-failures`、`agent/agen728-dt22-skill-read-error`
  `agent/agen909-broadexcept-narrow`、`agent/agen922-file-library-delete-fix`
  `agent/agen926-codebuddy-close`、`agent/agen928-swallow-log-batch`
  `agent/agen931-codebuddy-auth-cancel`、`agent/dt22-file-library-deletion-tests`
  `agent/dt419-snapshot-iso-tests`、`agent/dt605-turn-cancel-tests`
  `agent/dt605-turn-cancel-tests-v2`
- `test/*`：438 个，主题聚类：web 53、learning 11、rag 11、book 10、consolidator 10、question 8、reading 8、cli 7、search 7、session 7、lightrag 6、mastery 6；其余 177 簇（含单名簇）共 294 项（明细见 `branches.tsv`）
- 其余 24 个（`myfork/test/*`、`tests/*`、`codex/test/*`、顶层散支）：
  `agen-1296-web-preview-tests`、`agen-1562-ima-evidence-status-tests`
  `agen1084-skill-frontmatter-tests`、`agen1304-math-animator-reqcfg-tests`
  `agen1384-data-volume-tests`、`agen1552-migjournal-tests`
  `agen1624-zotero-search-tests`、`codex/test/mastery-study-contexts`
  `fix/tz-stable-runtime-context-tests`、`myfork/test/chat-state-adapter-streaming-20261003`
  `myfork/test/chat-workspace-smoke-20261003`、`myfork/test/chat-workspace-smoke-20261003-pr`
  `myfork/test/citation-manager-payloads-20261003`、`myfork/test/citation-manager-payloads-20261003-pr`
  `myfork/test/feishu-message-parsing-20261003`、`myfork/test/kb-manager-crud-edges-20261003`
  `myfork/test/launcher-lifecycle-20261003`、`myfork/test/question-pipeline-contract`
  `myfork/test/reading-regression-20261003`、`refactor/relocate-product-tree-tests-20261007`
  `test-turn-context-assembler`、`test-visualize-review-agent`
  `tests/runtime/isolated-worker-memory-reclaim`、`tests/spine-synthesizer-20261003`

## 续放清单

1. drift 8 支优先：测试主体已在 main，仅剩未吸收补口（见上表），rebase 后小步重放
2. missing 501 支按既有 `rework-test-branch-*` 单分支续放卡口径逐支推进；本卡点名集优先：`web/tests/*` 22 支与 `agent/*` 17 支
3. no-op 11 支无续放价值，建议直接清理分支

## 复核命令（全部只读）

```bash
git -C /Users/Shared/DeepTutor fetch --multiple origin myfork
git -C /Users/Shared/DeepTutor rev-parse origin/main origin/dev            # == 6cf793bd8
git -C /Users/Shared/DeepTutor merge-base origin/main myfork/<分支>         # 起点
git -C /Users/Shared/DeepTutor diff --name-status -M <起点> myfork/<分支>   # 分支自身改动
git -C /Users/Shared/DeepTutor diff -U0 <起点> myfork/<分支> -- <M文件>     # 行级吸收判定输入
git -C /Users/Shared/DeepTutor cherry origin/main myfork/<分支>             # patch-id 复证
```

（`<分支>` 取 myfork 分支名；M 文件以 main 当前文件行集比对新增/删除行；未运行任何测试，未动任何运行中服务。）
