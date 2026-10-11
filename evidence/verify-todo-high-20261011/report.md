# DT-22 HIGH 吞错条目 · v1.6.14 现状复核（18 条）

- **复核对象**: myfork 分支 `agent/dt22-todo-scan` 的 `evidence/todo-scan-2026-10-03/report.md` §2/§7 中 18 条 HIGH Python 静默异常处理器（原始基线 `origin/main @ ef2d9e5c3c…`，v1.6.12）
- **复核基线**: `origin/main @ 6cf793bd868ba5ecbe64722936d4be8fab5a01df`（release tag v1.6.14），2026-10-11 fetch
- **方式**: 只读复核。对 10 个目标文件以 Python `ast` 重扫全部静默处理器（`except` 且体为单条 `pass`/`continue`，脚本见本目录 `scan_py_swallow.py`，全量输出 `main_handlers_6cf793bd8.jsonl`，共 43 条），按「函数名 + try 体首行」签名逐条重定位；并用 `git log/diff f07029cfc..6cf793bd8` 核对修复来源与行号漂移。**未修改任何源码，未评论上游，未开上游 PR。**
- **去重边界**: 上一轮复核 `evidence/verify-todo-high-20261003/`（分支 `agent/agen1109-verify-todo-high`，基线 v1.6.13 `f07029cfc`）已完成 18/18 "仍在"结论；本卡只覆盖 v1.6.13→v1.6.14 增量与 18 条最新现状，不重做全量扫描、不复核 MEDIUM/LOW。

## 1. 结论

| 现状 | 条数 |
| --- | --- |
| 已修复（处理器改为记日志 / 显式抛出） | 14 |
| 仍在（含行号漂移） | 4 |
| 代码移位（函数或文件迁移） | 0 |

- v1.6.13→v1.6.14 窗口内，4 个上游 PR 修复了 18 条中的 14 条：#1612（`e79e1b0ad`，重建索引链路）、#1706（`50a3ba4e4`，KB 状态/进度 WS/文件夹同步）、#1704（`3a192f6a5`，launcher/update-worker）、#1703（`cc373762e`，embedding/图片进度）与 #1707（`080251045`，五个服务的吞错记日志，含 question.py）。
- 剩余 4 条仍在：#7（question stdout write）、#15（snapshot `_iso`）、#16（GraphRAG provider 解析）、#18（`file_library._delete_file`）；上游当前无对应开放 PR（已核对全部 open PR，无命中）。
- 另发现 2 处同函数/同模式残留（非 18 条原项，但属同批修复范围，见 §3 残留清单）。

## 2. 逐项状态表（18/18）

| # | v1.6.12 位置 | 现状 | v1.6.14 path:line | 所在函数 | 修复来源 / 说明 | 关联 fix-* 卡（台账状态） |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | knowledge.py:3952 | 已修复 | deeptutor/api/routers/knowledge.py:3942（`except Exception: raise`）、:3958（`raise RuntimeError(...) from progress_err`） | run_reindex_task | 上游 #1612（e79e1b0ad）：失败告警与终态持久化失败改为显式抛出，进入任务日志 | AGEN-134（done，已落地） |
| 2 | knowledge.py:4353 | 已修复 | deeptutor/api/routers/knowledge.py:4411-4424（`_progress_age_seconds` 助手，:4424 `logger.warning` 后返回 None） | websocket_progress | 上游 #1706（50a3ba4e4）：时间戳解析收进助手并记日志 | AGEN-135（in_review，修复已由 #1706 覆盖）；相邻 AGEN-795（in_review） |
| 3 | knowledge.py:4402 | 已修复 | 同上（同一助手 `_progress_age_seconds`） | websocket_progress | 同上 | 同 #2 |
| 4 | knowledge.py:4480 | 已修复 | deeptutor/api/routers/knowledge.py:4692-4695（`except Exception as send_error: logger.debug(...)`） | websocket_progress | 上游 #1706：错误帧发送失败记 debug 日志 | AGEN-135（同上） |
| 5 | knowledge.py:4486 | 已修复 | deeptutor/api/routers/knowledge.py:4700-4703（`close_error → logger.debug`） | websocket_progress | 同上 | AGEN-135（同上） |
| 6 | knowledge.py:4491 | 已修复 | deeptutor/api/routers/knowledge.py:4707-4709（`reset_error → logger.warning`） | websocket_progress | 同上 | AGEN-135（同上） |
| 7 | question.py:131 | **仍在** | deeptutor/api/routers/question.py:131-132 | write | 无改动（`except Exception: pass` 原样保留）；上游无对应开放 PR | 无 fix 卡（test 卡 AGEN-433/AGEN-355 已消费）→ **建议补一张 fix 卡** |
| 8 | question.py:323 | 已修复 | deeptutor/api/routers/question.py:321-326（窄类型 `logger.debug` + 宽 `except Exception: logger.warning(..., exc_info=True)`） | websocket_mimic_generate | 上游 #1707（080251045）；旧 MEDIUM 邻项（:305-306，`except (RuntimeError, WebSocketDisconnect): pass`）未动，评级 LOW-MEDIUM | 无 fix 卡（test 卡已消费；myfork 候选分支 `agent/dt22-fix-question-ws` 未落地） |
| 9 | manager.py:567 | 已修复 | deeptutor/knowledge/manager.py:615-619（`except Exception as exc: logger.warning("Failed to refresh embedding/index metadata...")`） | update_kb_status | 上游 #1706 | AGEN-136（in_review，修复已由 #1706 覆盖） |
| 10 | manager.py:2130 | 已修复 | deeptutor/knowledge/manager.py:2224-2231（`except Exception as exc: logger.warning("Failed to record sync state...")`） | update_folder_sync_state | 上游 #1706 | AGEN-137（done，已落地） |
| 11 | launcher.py:1252 | 已修复 | deeptutor/runtime/launcher.py:1373-1377（`except Exception as mark_exc: _log("Launcher handoff failed ... could not record failure")`） | _handoff_pending_update | 上游 #1704（3a192f6a5） | AGEN-138（done，已落地） |
| 12 | update_worker.py:144 | 已修复（同函数留 1 处残留） | deeptutor/runtime/update_worker.py:157-162（`store.load()` 失败 → `_log_aborted_recovery` + `return 1`）；**残留**：同函数 :171-176 仍有 `except Exception: pass`（包裹 `mark_failed` + 重启拉起） | run_update_worker | 上游 #1704 修复了 load 分支；mark_failed/重启分支的吞错未在 #1704 范围内 | AGEN-139（done，load 部分已落地）；残留对应 AGEN-1079（in_review，**仍未落地**） |
| 13 | embedding/client.py:204 | 已修复 | deeptutor/services/embedding/client.py:204-213（`except Exception as exc: logger.warning(..., exc_info=True)`） | embed | 上游 #1703（cc373762e） | AGEN-140（done，已落地） |
| 14 | embedding/client.py:279 | 已修复 | deeptutor/services/embedding/client.py:281-290（同上模式） | embed_contents | 同上（行号 +2 漂移） | AGEN-140（同卡第二处） |
| 15 | adapters.py:51 | **仍在**（+5 行漂移） | deeptutor/services/memory/snapshot/adapters.py:56-57（同函数姊妹条 `except Exception: pass` 现位于 :60-61） | _iso | #1707 改的是 adapters.py 其他位置（新增 `_iter_chat_db`，本身带日志），`_iso` 两处 pass 原样保留；上游无对应开放 PR | AGEN-799（in_review，**仍未落地**） |
| 16 | graphrag/provider.py:119 | **仍在** | deeptutor/services/rag/pipelines/graphrag/provider.py:119-121 | resolve_persisted_completion_provider | 文件在 v1.6.13→v1.6.14 窗口无改动；带注释 "Old settings remain usable…"，处理体仍为 `pass`；上游无对应开放 PR | AGEN-283（in_review，**仍未落地**） |
| 17 | document_loader.py:403 | 已修复（批处理路径留 1 处残留） | deeptutor/services/rag/pipelines/llamaindex/document_loader.py:434-438（`_describe_one` 回调失败 → `logger.warning`）；**残留**：批处理分支 `_describe_group` :493-494 仍为 `except Exception: pass` | _describe_one | 上游 #1703 修复 `_describe_one`；`_describe_group` 为 v1.6.13 新增 HIGH，不在 #1703 范围 | AGEN-141（done，`_describe_one` 部分已落地）；残留对应 AGEN-924（in_review，**仍未落地**） |
| 18 | file_library.py:205 | **仍在** | deeptutor/services/storage/file_library.py:205-206 | _delete_file | 文件在窗口内无改动；上游无对应开放 PR | AGEN-922（in_review，**仍未落地**） |

## 3. 剩余修复清单（建议）

按优先级（均为 `except Exception: pass` → 记日志/窄化，修复模式与 #1703/#1704/#1706/#1707 一致）：

1. **AGEN-1079 残留**（`deeptutor/runtime/update_worker.py:171-176`）：`run_update_worker` 恢复分支 `mark_failed`/重启拉起失败仍整体吞掉；该函数 load 分支已由 #1704 修复，剩余分支建议同模式补 `_log_aborted_recovery` 或 `_log`。卡已在台账（in_review），建议推进落地。
2. **AGEN-924 残留**（`deeptutor/services/rag/pipelines/llamaindex/document_loader.py:493-494`）：`_describe_group` 进度回调吞错；`_describe_one` 已由 #1703 修复为 `logger.warning`，批处理分支建议同模式对齐。卡已在台账（in_review）。
3. **AGEN-283**（`graphrag/provider.py:119-121`）：宽 `except Exception: pass` 包裹配置目录读取，解析失败静默回退 deepseek 推断。卡已在台账（in_review）。
4. **AGEN-799**（`adapters.py:56-57`，姊妹条 :60-61）：`_iso` 两条宽 `pass`，坏时间戳静默返回原串/空串。卡已在台账（in_review）。
5. **AGEN-922**（`file_library.py:205-206`）：`_delete_file` 目录清理失败吞错。卡已在台账（in_review）。
6. **无卡缺口**（question.py:131-132，`write` 内 stdout 写失败 `pass`）：台账中无对应 fix 卡（仅 test 卡 AGEN-433/AGEN-355）；`websocket_mimic_generate` 的同类问题已由 #1707 修复，此处建议**新开一张 fix 卡**（同模式 `logger.debug/warning`）。

## 4. 与 fix-* 台账对账

- 18 条 → 台账映射无遗漏：14 条已修复条目分别对应 AGEN-134/135/136/137/138/139/140/141（其中 AGEN-135、AGEN-136 卡面仍为 in_review，但其修复内容已被上游 #1706 以等价实现合入，建议人工复核后关闭）；4 条仍在条目对应 AGEN-283/799/922 及 1 条无卡缺口（question.py:131，见 §3.6）。
- 2 处同批残留（update_worker :171、`_describe_group` :493）均有台账卡（AGEN-1079/AGEN-924），无新增无主条目。
- 上述 5 张 in_review 卡对应分支均未出现在上游 open PR 列表中，v1.6.14 未包含其改动，与 §2 "仍在"结论一致。

## 5. 复现

```bash
git -C /Users/Shared/DeepTutor fetch --multiple origin myfork
git -C /Users/Shared/DeepTutor worktree add .wt-verify -b tmp-verify 6cf793bd8
cd .wt-verify && python3 ../evidence/verify-todo-high-20261011/scan_py_swallow.py \
  deeptutor/api/routers/knowledge.py deeptutor/api/routers/question.py \
  deeptutor/knowledge/manager.py deeptutor/runtime/launcher.py \
  deeptutor/runtime/update_worker.py deeptutor/services/embedding/client.py \
  deeptutor/services/memory/snapshot/adapters.py \
  deeptutor/services/rag/pipelines/graphrag/provider.py \
  deeptutor/services/rag/pipelines/llamaindex/document_loader.py \
  deeptutor/services/storage/file_library.py
# 输出与本目录 main_handlers_6cf793bd8.jsonl 一致（43 条），
# 按「函数名 + try 体首行」与 todo-scan-2026-10-03 报告 §7 的 18 条 HIGH 签名比对即得 §2。
git -C /Users/Shared/DeepTutor worktree remove .wt-verify
```

修复来源核对：

```bash
git log --oneline f07029cfc..6cf793bd8 -- deeptutor/api/routers/knowledge.py   # e79e1b0ad #1612 / 50a3ba4e4 #1706
git show --stat 50a3ba4e4 3a192f6a5 cc373762e 080251045                         # 四个吞错修复 PR 的文件范围
```
