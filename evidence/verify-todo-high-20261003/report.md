# DT-22 HIGH 吞错复核（18 条）· v1.6.13 基线

- **复核对象**: myfork 分支 `agent/dt22-todo-scan` 的 `evidence/todo-scan-2026-10-03/report.md` §2/§7 中 18 条 HIGH Python 静默异常处理器（原基线 `origin/main @ ef2d9e5c3c99…`，v1.6.12）
- **复核基线**: `origin/main @ f07029cfcf2c8dfccdb671cdfc343db8334f5741`（release v1.6.13），2026-10-07 fetch
- **方式**: 只读复核。对 10 个目标文件以 Python `ast` 重扫全部静默处理器（`except` 且体为单条 `pass`/`continue`），按「函数名 + try 体首行」签名逐条重定位；并用 `git diff ef2d9e5c..f07029cfc --stat` 核对行号漂移来源。**未修改任何代码，未评论上游。**
- **去重边界**:
  - 20261007 六报告轴（AGEN-1108 等）：本卡只覆盖 DT-22 20261003 报告的 18 条 HIGH，不复核其他报告。
  - 宽捕获扫描轴（`myfork/agent/agen370-broad-except-scan` 的 `evidence/broad-except-scan-2026-10-04/`，收窄批 AGEN-909）：该轴做宽 `except` 全量扫描与收窄，本卡只做 DT-22 报告 18 条 HIGH 的位置与现状复核，未重做全量扫描。

## 1. 结论

| 现状 | 条数 |
| --- | --- |
| 仍在（含行号漂移） | 18 |
| 已修复（origin/main 上处理器已消失/改为记日志） | 0 |
| 代码移位（函数或文件迁移） | 0 |

- 18/18 的 `except Exception: pass` 处理器在 v1.6.13 上原函数、原文件原样保留；v1.6.12→v1.6.13 窗口内 4 个目标文件有改动（knowledge.py、manager.py、launcher.py、document_loader.py），导致 9 条行号漂移；其余 9 条行号未变。
- 所有 18 条对应的已消费 fix-* 卡均在 myfork 分支（in_review / done），无一进入 origin/main —— 与上述"仍在"结论一致。

## 2. 逐项状态表

| # | v1.6.12 位置 | 现状 | 新 path:line（f07029cfc） | 所在函数 | try 体首行 | 关联已消费 fix-* 卡 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | knowledge.py:3952 | 仍在（+36 行漂移） | deeptutor/api/routers/knowledge.py:3988 | run_reindex_task | ProgressTracker(kb_name, Path(base_dir)).update( | AGEN-134 `fix-reindex-progress`（done；pr-ready AGEN-268 → 合集 AGEN-301） |
| 2 | knowledge.py:4353 | 仍在（+36 行漂移） | deeptutor/api/routers/knowledge.py:4389 | websocket_progress | age = (datetime.now() - datetime.fromisoformat(ts)).total_seconds() | AGEN-135 `fix-progress-ws`（in_review）；相邻 AGEN-795 `fix-kb-progress-tz`（in_review） |
| 3 | knowledge.py:4402 | 仍在（+36 行漂移） | deeptutor/api/routers/knowledge.py:4438 | websocket_progress | progress_time = datetime.fromisoformat(timestamp) | AGEN-135（in_review）；相邻 AGEN-795（in_review） |
| 4 | knowledge.py:4480 | 仍在（+36 行漂移） | deeptutor/api/routers/knowledge.py:4516 | websocket_progress | await websocket.send_json({"type": "error", "message": str(e)}) | AGEN-135（in_review） |
| 5 | knowledge.py:4486 | 仍在（+36 行漂移） | deeptutor/api/routers/knowledge.py:4522 | websocket_progress | await websocket.close() | AGEN-135（in_review） |
| 6 | knowledge.py:4491 | 仍在（+36 行漂移） | deeptutor/api/routers/knowledge.py:4527 | websocket_progress | reset_current_user(user_token) | AGEN-135（in_review） |
| 7 | question.py:131 | 仍在（行号未变） | deeptutor/api/routers/question.py:131 | write | self.original_stdout.write(message) | 无 fix 卡（test 卡 AGEN-433 `test-question-stdout`、AGEN-355 `test-mimic-generate` 已消费） |
| 8 | question.py:323 | 仍在（行号未变） | deeptutor/api/routers/question.py:323 | websocket_mimic_generate | await websocket.send_json({"type": "error", "content": error_msg}) | 无 fix 卡（test 卡 AGEN-355/AGEN-433 已消费；myfork 存在候选分支 `agent/dt22-fix-question-ws`，未对应已消费卡） |
| 9 | manager.py:567 | 仍在（+48 行漂移） | deeptutor/knowledge/manager.py:615 | update_kb_status | from deeptutor.services.rag.embedding_binding import entry_signature | AGEN-136 `fix-kb-status`（in_review；pr-ready AGEN-268 → 合集 AGEN-301） |
| 10 | manager.py:2130 | 仍在（+85 行漂移） | deeptutor/knowledge/manager.py:2215 | update_folder_sync_state | if source_mtimes is not None: | AGEN-137 `fix-folder-sync`（done；pr-ready AGEN-253 → 合集 AGEN-301） |
| 11 | launcher.py:1252 | 仍在（+4 行漂移） | deeptutor/runtime/launcher.py:1256 | _handoff_pending_update | store.mark_failed(job.id, f"Launcher handoff failed: {exc}") | AGEN-138 `fix-launcher-handoff`（done；pr-ready AGEN-221 → 合集 AGEN-302） |
| 12 | update_worker.py:144 | 仍在（行号未变） | deeptutor/runtime/update_worker.py:144 | run_update_worker | current = store.load() | AGEN-139 `fix-update-worker-load`（done；pr-ready AGEN-215 → 合集 AGEN-302）；相邻 AGEN-1079 `fix-update-worker-stale-running`（in_review） |
| 13 | embedding/client.py:204 | 仍在（行号未变） | deeptutor/services/embedding/client.py:204 | embed | progress_callback(i + 1, total_batches) | AGEN-140 `fix-embedding-progress`（done，两处同卡；pr-ready AGEN-261 → 合集 AGEN-304） |
| 14 | embedding/client.py:279 | 仍在（行号未变） | deeptutor/services/embedding/client.py:279 | embed_contents | progress_callback(i + 1, total_batches) | AGEN-140（done，同卡第二处） |
| 15 | memory/snapshot/adapters.py:51 | 仍在（行号未变） | deeptutor/services/memory/snapshot/adapters.py:51 | _iso | datetime.fromisoformat(ts.replace("Z", "+00:00")) | AGEN-799 `fix-snapshot-iso-aware`（in_review）；test 卡 AGEN-419（in_review） |
| 16 | graphrag/provider.py:119 | 仍在（行号未变） | deeptutor/services/rag/pipelines/graphrag/provider.py:119 | resolve_persisted_completion_provider | from deeptutor.services.config import ( | AGEN-283 `fix-graphrag-provider`（in_review） |
| 17 | document_loader.py:403 | 仍在（+2 行漂移） | deeptutor/services/rag/pipelines/llamaindex/document_loader.py:405 | _describe_one | image_progress_callback(completed, total) | AGEN-141 `fix-image-describe-one`（done；pr-ready AGEN-237 → 合集 AGEN-304）；注意 AGEN-924 修复的是 v1.6.13 新增 `_describe_group` HIGH，非本条 |
| 18 | file_library.py:205 | 仍在（行号未变） | deeptutor/services/storage/file_library.py:205 | _delete_file | for parent in target.parents: | AGEN-922 `fix-file-library-delete`（in_review） |

说明：#9 与 #16 的处理器行带注释（`# pragma: no cover - best-effort metadata` / "Old settings remain usable…"），处理体仍为 `pass`，AST 判定不变。

## 3. 行号漂移来源

`git diff ef2d9e5c..f07029cfc --stat`（仅本卡 10 个目标文件）：

```
 deeptutor/api/routers/knowledge.py                 | 92 ++++++++++++++++++++--
 deeptutor/knowledge/manager.py                     | 87 +++++++++++++++++++-
 deeptutor/runtime/launcher.py                      | 12 ++-
 deeptutor/services/rag/pipelines/llamaindex/document_loader.py | 70 ++++++++++++++--
 4 files changed, 243 insertions(+), 18 deletions(-)
```

question.py、update_worker.py、embedding/client.py、memory/snapshot/adapters.py、graphrag/provider.py、file_library.py 在该窗口无改动，行号不变。

## 4. 复现

```bash
git -C /Users/Shared/DeepTutor fetch --multiple origin myfork
git -C /Users/Shared/DeepTutor worktree add .wt-verify -b tmp-verify origin/main
# 对本报告 §2 的 10 个文件跑 AST 静默处理器扫描（except + 单条 pass/continue），
# 按「函数名 + try 体首行」与 agent/dt22-todo-scan 报告 §7 的 18 条 HIGH 签名比对。
```
