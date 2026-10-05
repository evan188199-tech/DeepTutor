# DT-22 扫描报告对最新 main 的漂移复核（AGEN-666）

- **基线对照**: 报告基线 `ef2d9e5c`（v1.6.12，DT-22 附录 A 扫描提交）→ 最新 `origin/main` `f07029cf`（v1.6.13），两提交间 330 个文件变更
- **复核日期**: 2026-10-05（UTC）
- **工作副本**: `/Users/Shared/DeepTutor/dt-agen666-wt`（独立 worktree，分支 `agent/agen666-dt22-drift-scan`，基于 `f07029cf`）；主工作区未做任何改动，**未修改任何代码**
- **方法**: 复用 DT-22 原扫描脚本（`scan_py_swallow.py`，AST 级、同口径）在 `f07029cf` 全量重扫，与附录 A 逐条按 `path + 函数名 + try 体首行` 恒等匹配（含函数改名/try 体变更回退规则）；全部 HIGH 与抽样 MEDIUM 再用非 AST 的原文读取独立复核。TS/JS 侧逐条原文核验。

## 1. 结论（PASS）

**DT-22 报告在 v1.6.13 上零修复：395 条（Python 352 + TS/JS 43）全部仍存在；无一条被上游修掉。** 其中 74 条行号漂移（Python 65 + TS 9），漂移均为 ±4~46 行的代码移动，处理器本体（异常类型/函数/try 体语义）未变。

| 附录 | 条目数 | 仍在（同行号） | 仍在（行号漂移） | 已修复 | 新增同类命中 |
| --- | --- | --- | --- | --- | --- |
| A · Python 静默处理器 | 352 | 287 | 65 | 0 | 8（1 HIGH + 7 LOW） |
| B · TS/JS 吞错 | 43 | 34 | 9 | 0 | —（未重扫全量，仅核对本报告条目） |
| 合计 | 395 | 321 | 74 | **0** | 8 |

## 2. 附录 A · HIGH 逐条核对（18/18，100%）

| 原位置 | 现位置 | 状态 | 现函数 | 开放 PR 覆盖 |
| --- | --- | --- | --- | --- |
| `deeptutor/api/routers/knowledge.py:3952` | :3988 | 仍在（漂移） | `run_reindex_task` | #1706 |
| `deeptutor/api/routers/knowledge.py:4353` | :4389 | 仍在（漂移） | `websocket_progress` | #1706 |
| `deeptutor/api/routers/knowledge.py:4402` | :4438 | 仍在（漂移） | `websocket_progress` | #1706 |
| `deeptutor/api/routers/knowledge.py:4480` | :4516 | 仍在（漂移） | `websocket_progress` | #1706 |
| `deeptutor/api/routers/knowledge.py:4486` | :4522 | 仍在（漂移） | `websocket_progress` | #1706 |
| `deeptutor/api/routers/knowledge.py:4491` | :4527 | 仍在（漂移） | `websocket_progress` | #1706 |
| `deeptutor/api/routers/question.py:131` | :131 | 仍在 | `write` | **无** |
| `deeptutor/api/routers/question.py:323` | :323 | 仍在 | `websocket_mimic_generate` | **无** |
| `deeptutor/knowledge/manager.py:567` | :615 | 仍在（漂移） | `update_kb_status` | #1706 |
| `deeptutor/knowledge/manager.py:2130` | :2215 | 仍在（漂移） | `update_folder_sync_state` | #1706 |
| `deeptutor/runtime/launcher.py:1252` | :1256 | 仍在（漂移） | `_handoff_pending_update` | #1704 |
| `deeptutor/runtime/update_worker.py:144` | :144 | 仍在 | `run_update_worker` | #1704 |
| `deeptutor/services/embedding/client.py:204` | :204 | 仍在 | `embed` | #1703 / #1757 |
| `deeptutor/services/embedding/client.py:279` | :279 | 仍在 | `embed_contents` | #1703 / #1757 |
| `deeptutor/services/memory/snapshot/adapters.py:51` | :51 | 仍在 | `_iso` | **无**（#1764/65 只覆盖 read_* 三个 LOW，不含 `_iso`） |
| `deeptutor/services/rag/pipelines/graphrag/provider.py:119` | :119 | 仍在 | `resolve_persisted_completion_provider` | **无** |
| `deeptutor/services/rag/pipelines/llamaindex/document_loader.py:403` | :405 | 仍在（漂移） | `_describe_one` | #1703 / #1758 |
| `deeptutor/services/storage/file_library.py:205` | :205 | 仍在 | `_delete_file` | **无** |

18/18 经独立原文复核（读 `f07029cf` 源文件确认 `except Exception:` + 静默体 + try 体首行在场）。

## 3. 附录 A · MEDIUM 核对（124 条，抽样 62.9%）

- **状态**：91 仍在（同行号）+ 33 行号漂移 + **0 修复**（124/124 脚本级全量比对，无一缺失）。
- **抽样规则**（≥50% 要求）：位于 `ef2d9e5c..f07029cf` 变更文件（330 个）内的 MEDIUM 条目**全检**（32 条）+ 未变更文件条目按附录 A 顺序**每第 2 条抽检**（46 条）= **78/124（62.9%）**。
- **抽样复核结果**：78/78 原文独立复核通过（初扫 5 条因行内注释 `pass  # …` 被脚本误标，人工确认均为静默处理器）。
- 明细见 `drift_status.json`（每条含 `status` / `new_line` / 匹配方式）。

## 4. 附录 A · LOW（210 条）

188 仍在（同行号）+ 22 行号漂移 + 0 修复（脚本级全量比对）。其中 `deeptutor/reading/store.py:930`（`outline`）在 v1.6.13 重构后移至 :923，try 体由内联构造行改为 `OutlineEntry.from_dict(row)`，处理器本体不变，人工确认仍存在。

## 5. 附录 B · TS/JS（43/43 核对）

34 同位置 + 9 行号漂移 + **0 修复**。HIGH + MEDIUM（23 条）100% 原文核验，LOW 20 条亦逐条核验。漂移明细：

| 条目 | 旧 → 新 | 说明 |
| --- | --- | --- |
| `web/app/(utility)/courses/[courseId]/page.tsx:414`（HIGH） | :414 | 未变；`void deleteCourse(...).then(...)` 仍无 `.catch`（#1754 未合并） |
| `web/features/chat/components/ChatWorkspace.tsx:1887` | :1895 | 漂移 |
| `web/features/chat/ChatStateAdapter.tsx:3217` | :3240 | 重试路径 `void sendMessage(...)` 下移 |
| `web/components/reading/library/MaterialLibrary.tsx:482` | :495 | 漂移 |
| `web/context/QuizFollowupContext.tsx:280` | :284 | 漂移 |
| `web/components/reading/EpubDocumentView.tsx:411` | :419 | 漂移 |
| `web/components/reading/ReadingExtensionBar.tsx:121` | :128 | 漂移 |
| `web/components/reading/ReadingActionsProvider.tsx:80` | :81 | 漂移 |
| `web/components/watching/WatchingPane.tsx:108` | :153 | 漂移 |
| `web/tests/chat-reply-language.spec.tsx:57` | :56 | 漂移（测试代码） |

## 6. 新增同类命中（8 条，v1.6.13 引入）

| 风险 | 位置 | 所在函数 | try 体首行 | 说明 |
| --- | --- | --- | --- | --- |
| **HIGH** | `deeptutor/services/rag/pipelines/llamaindex/document_loader.py:459` | `_describe_group` | `image_progress_callback(completed, total)` | v1.6.13 批量重构新增的并行路径，复制了 `_describe_one:405` 同款吞 `image_progress_callback`；**与 #1758 同文件同模式，但 #1758 目前只覆盖老点** |
| LOW | `deeptutor/services/llm/image_caption_cache.py:84` | `_read_caption` | `payload = json.loads(...)` | 新文件 |
| LOW | `deeptutor/services/llm/image_caption_cache.py:144` | `_read_batch_captions` | `payload = json.loads(...)` | 新文件 |
| LOW | `deeptutor/services/rag/pipelines/llamaindex/exercise_lookup.py:260` | `_parse_for` | `meta = json.loads(...)` | 新文件 |
| LOW | `deeptutor/services/rag/pipelines/llamaindex/exercise_lookup.py:305` | `lookup_exercises` | `parsed = _parse_for(...)` | 新文件 |
| LOW | `deeptutor/services/parsing/engines/mineru/checkpoints.py:74` | `load` | symlink/directory 检查 | 新文件 |
| LOW | `deeptutor/services/storage/attachment_store.py:267` | `_materialize_session_sync` | `source_dir.rmdir()` | 清理语义 |
| LOW | `deeptutor/services/parsing/engines/mineru/local.py:332` | `parse_document_with_mineru_result` | 诊断写入 | 注释已说明意图，补日志即可 |

新命中按 DT-22 §5 评分规则定级（脚本实现，规则一致）。

## 7. 去重标注

**与已交付 fix/test 卡（均未合并，开放中）**：

| 开放 PR | 覆盖的本次复核条目 |
| --- | --- |
| #1706 | knowledge.py HIGH ×6、manager.py:567/:2130 |
| #1704 | launcher.py:1252、update_worker.py:144（含 init_cmd 相关 LOW/MEDIUM） |
| #1703 / #1757 | embedding/client.py:204/:279 |
| #1703 / #1758 | document_loader.py:403（不含新命中 :459） |
| #1754 | TS HIGH `courses/[courseId]/page.tsx:414` |
| #1700 / #1755 / #1756 | docx_converter.py MEDIUM（:256/:340/:356） |
| #1751 | file_io.py:55/:80（fsync） |
| #1752 / #1753 | codebuddy_provider.py:553（:115/:144/:363 未覆盖） |
| #1761 / #1762 | workspace/dependencies.py（:105/:214/:327/:345） |
| #1763 | partners/channels/manager.py:294 |
| #1766 | api/utils/tool_options.py:97 |
| #1764 / #1765 | snapshot/adapters.py read_* 三个 LOW（:87/:138/:171，**不含 `_iso`:51/:56**） |

test 类卡（#1749-#1778 中 test/*）仅新增测试，不修复吞错本体，不构成去重。

**与 scan-todo-fresh（AGEN-576 · `scan/todo-fixme-20261004`，同一基线 `f07029cf`）**：TODO 侧结论一致——真实 TODO 仅 `.pre-commit-config.yaml:111` 1 处；DT-22 §4 的 2 处失效 `TODO.md` docstring 引用（`tex_downloader.py:11`、`tex_chunker.py:11`）**仍存在**，去重不重复建卡。

**与 scan-broad-excepts（AGEN-370 · `agent/agen370-broad-except-scan`）**：其 118/118 零漂移结论基于旧基线 `ef2d9e5c`；本次确认这些条目在 `f07029cf` 仍全部在场，其分型建议与 #1700/#1703/#1704/#1706 继续有效（4 个 PR 均开放、未合并）。

## 8. 可拆卡建议

1. **新增 HIGH（document_loader.py:459）**：并入 #1758 的修复范围最合适（同文件同模式）；按推送边界不直接追加提交，建议由人决定在 #1758 补 patch 或拆姊妹卡。
2. **未被任何开放 PR 覆盖的 HIGH ×5**：`question.py:131`、`question.py:323`、`snapshot/adapters.py:51`、`graphrag/provider.py:119`、`file_library.py:205` —— 建议拆一张「残留 HIGH 吞错治理」卡；其中 adapters.py:51 与 graphrag:119 可直接采用 AGEN-370 §2.2 的收窄建议。
3. **新增 LOW ×7**：不单独拆卡，可并入后续「吞错补日志」批次卡。
4. **TODO 侧**：无需新卡（AGEN-576 低优 docs 清理建议已覆盖）。

## 9. 复现命令

```bash
# 在 f07029cf 的 worktree 中重扫（与本报告 §1 同口径）
python3 scan_py_swallow.py > py_silent_handlers_f07029cf.json
# 与 DT-22 附录 A 逐条比对：见 drift_status.json（py[].status / new_line / how）
# 行号漂移量核对
git -C /Users/Shared/DeepTutor diff --name-only ef2d9e5c..f07029cf | wc -l   # 330
```

---
*复核由只读漂移比对生成（agent/agen666-dt22-drift-scan @ myfork，基于 origin/main `f07029cf`）。未修改任何代码。*
