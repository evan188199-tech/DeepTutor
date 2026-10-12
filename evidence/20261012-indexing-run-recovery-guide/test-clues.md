# 补测线索：机制合同级测试候选

基线 `origin/main @ 6cf793bd8`。与 crash-window 报告的 `test-candidates.md`
（崩溃窗口轴）不重叠：本文只列"恢复机制对外合同"的测试候选，
每条给出路径、断言要点与现状（已有覆盖 / 缺口）。

## 0. 现有覆盖盘点（绿基线）

| 测试 | 锁定的合同 |
| --- | --- |
| `tests/knowledge/test_indexing_run.py:26` `test_retry_retains_source_identity_and_verified_parse_receipt` | 重试保留源身份与已验证解析收据 |
| `:48` `test_cancel_is_owned_by_task_and_preserves_newer_worker` | 取消按 task_id 归属，不误伤新 worker |
| `:61` `test_live_owner_cannot_be_replaced_and_corrupt_journal_survives` | 活主人不可被顶替（flock）；损坏 journal 原样保留 |
| `:75` `test_restart_projection_is_read_only_and_retains_completed_sources` | `interrupted` 投影只读、completed 不动 |
| `:94` `test_changed_source_cannot_be_published` | 源文件中途被改 → 发布被拒 |
| `:106` `test_incomplete_version_is_not_queryable_and_previous_version_survives` | 未过探针的版本不可检索，旧版本存活 |
| `:121` `test_failure_details_redact_quoted_credentials` | 错误文本脱敏 |
| `:128` `test_real_persisted_index_reloads_and_missing_vectors_fail` | 持久化索引重载、缺向量 fail-closed |
| `:146` `test_readiness_is_local_and_cancel_requires_writable_owned_task` | 就绪本地判定；取消要求可写且归属匹配 |
| `tests/api/test_knowledge_progress_ws.py:55` `test_orphaned_live_progress_becomes_retryable_error` | 重启孤儿任务 → `knowledge_task_interrupted` retryable |
| `tests/api/test_knowledge_router.py:2082,:2122,:3142` | retry 端点：error 态门槛、非 error 409、LightRAG 需确认 |
| `web/tests/kb-indexing-run.spec.tsx:13,:23,:31` | 面板读 durable 结果、取消归属、只读库无取消按钮 |

## 1. 候选 C1：`GET /indexing-run` 只读合同（API 级，缺口）

- 路径：`knowledge.py:4326-4332` → `visible_run`（`indexing_run.py:133-162`）。
- 断言要点：
  1. 连续两次 GET 返回体逐字段相等，且 journal 文件 mtime/内容不变（投影不落盘）；
  2. journal 里伪造死 PID（`state=running`、`pid` 指向不存在进程）后 GET 返回
     `state=interrupted`、在途文档为 `unknown`、原文档 completed 保留；
  3. 无 journal 时返回 `{"run": null}` 而非 404/500。
- 现状：仅单元级（`test_indexing_run.py:75`）与前端组件级覆盖，无 API 级测试。

## 2. 候选 C2：取消端点 API 合同（缺口）

- 路径：`knowledge.py:4335-4345` → `request_cancel`（`indexing_run.py:440-447`）。
- 断言要点：
  1. task_id 与 journal 不匹配 → 409，且不产生 `.indexing-cancel.json`；
  2. 对终态 run（`completed`）取消 → 409；
  3. 匹配的 running run → 200 + `cancel_requested: true`，journal 本身不变，
     标记文件落盘；
  4. 取消后 worker 侧下一次 `check()` 抛 `IndexingCancelled`（可并入 3 的后续断言）。
- 现状：归属语义有单元覆盖（`test_indexing_run.py:48`），路由层 409/200 分支无测试。

## 3. 候选 C3：reindex 对 previous run 的两个分支（缺口）

- 路径：`knowledge.py:4119-4130`。
- 断言要点：
  1. journal `state=running` 且主人活着（占住 flock）→ reindex 409，文案
     "An indexing worker still owns this knowledge base."；
  2. journal `state=interrupted`（死 PID 投影）→ reindex 放行且进入强制重建
     路径（`force_reindex=True`）；
  3. `partial/failed/cancelled` 各态同样触发 `force_reindex`（参数化覆盖）。
- 现状：未见针对这两个分支的 API 测试。

## 4. 候选 C4：`partial`/`completed` 判定规则（服务级，缺口）

- 路径：`rag/service.py:119-122`。
- 断言要点：发布成功后（探针 ready + usable_version 已置），任一文档仍为
  `failed/unknown/pending/parsing` → `run.finish("partial", version=…)`；全部
  `completed/excluded` → `completed`。可用假 pipeline 控制每文档状态参数化验证
  两种终态与 `usable_version` 均被写入 journal。
- 现状：单元文件未覆盖该服务层分流（现有 `partial` 命中只是无关 docstore 文本）。

## 5. 候选 C5：收据记账只数 `completed`（缺口）

- 路径：`knowledge.py:1026-1032`（创建初始化任务）、`initializer.py:110-118`
  （初始化收据写 metadata）。
- 断言要点：一轮含 1 个失败文档的 llamaindex 初始化后，
  `metadata.json` 的 `last_indexed_count` == journal 中 `completed` 数（不含
  failed/unknown），`indexing_state` == journal 终态（如 `partial`）。
- 现状：`test_knowledge_router.py:3204` 覆盖"空 KB 上传-重试"主流程，
  未断言失败文档下的计数语义。

## 6. 候选 C6：finish 后文档收尾 unknown（单元级补强，低成本）

- 路径：`indexing_run.py:416-418`。
- 断言要点：`finish("failed")` 后 journal 中 `parsed`（已解析未嵌入）文档也被
  收敛为 `unknown`——"parsed 但没发布"与"解析中"一样不可观测。
- 现状：`test_restart_projection_is_read_only…` 覆盖投影侧 unknown，终局
  `finish()` 收敛路径无直接断言。

## 优先级建议

C3（reindex 分支）> C2（取消路由）> C1（只读合同）> C4 > C5 > C6。
C1-C3 是使用者实际踩到的恢复入口，目前 API 层完全无回归保护；
C4-C6 是合同细节补强。
