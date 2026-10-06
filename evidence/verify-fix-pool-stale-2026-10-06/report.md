# fix-\* 储备卡对最新 main 的失效抽检（AGEN-901）

- **抽检日期**: 2026-10-06
- **对照基线**: `origin/main` @ `f07029cf`（release v1.6.13，即当前 main tip；`v1.6.13..origin/main` 为 0 commit）
- **样本来源**: `glm-reserve/reserve/backlog/`（`deeptour.auto.jsonl`）fix-\* 卡 12 张 = DT-22 吞错系列全部 8 张 + blanket-500 系列全部 4 张
- **方法**: 独立 worktree `dt-agen901-verifypool-wt`（分支 `verify/fix-pool-stale-20261006`，基于 `f07029cf`）；逐卡按描述定位缺陷点，读 `f07029cf` 原文核对吞错模式是否在场、行为是否已变；对判定"已修复"的卡再用 `git log -L` / `git show v1.6.12:` 追溯修复提交。主工作区只读，未修改任何产品代码。
- **交叉参照**: AGEN-666 漂移复核（`myfork/agent/agen666-dt22-drift-scan`，同基线 f07029cf）。其结论为 DT-22 附录 395 条"处理器本体"机械在场、零删除；本抽检为卡级语义判定，两者不矛盾（处理器在场 ≠ 卡面描述的缺陷仍成立）。

## 1. 结论（PASS）

**12 张抽检卡：仍有效 10 张、失效 2 张、移位 0 张。** 失效 2 张均为确凿：1 张卡面所报缺陷行为不存在（误报），1 张已被上游合并修复。行号漂移普遍很小（最大 +16 行），无文件/函数级移位；blanket-500 四张卡行号与卡面完全一致、计数一致。

## 2. 抽检表

| # | 卡 key | 缺陷点（卡面位置 → 实测） | 结论 | 依据 |
| --- | --- | --- | --- | --- |
| 1 | fix-lightrag-worker-loop | `lightrag/worker.py` `run_in_worker_loop` 报 :250 → 实测 :249-252 | **失效（误报）** | 该 `except BaseException: pass` 紧跟 `raise`（worker.py:252），仅用于取回终态异常抑制 "never retrieved" 告警；任务异常经 `finished.set_exception(exc)`（:195）在等待方重抛，docstring 明示 "Worker exceptions are re-raised"。v1.6.12 同构。所指"索引失败上层按成功处理"不成立 |
| 2 | fix-session-migration-swallow | `session/sqlite_store.py` `_initialize` 报 :454 → 实测 :467-473（漂移 +16） | **仍有效（收窄）** | 上游 #1398（9b066b5f9）加 `if "kind" in columns` 守卫，"列已不存在"不再进 except；残留 `except OperationalError: pass` 仅限老 SQLite 无 DROP COLUMN 支持（已注释）与真失败（仍静默）。卡面"区分两种 OperationalError"核心诉求已半落地，剩余范围=真失败留痕 |
| 3 | fix-kb-mode-resolve | `rag/pipelines/modes.py` `resolve_kb_mode` 报 :37 → 实测 :37-38 | 仍有效 | `except Exception: pass` 原样在场，无日志、无告警，配置损坏静默回退默认管线 |
| 4 | fix-docx-converter-style-fallback | `co_writer/docx_converter.py` 报 :256/:340/:356 → 实测 :256-257/:340-341/:356-357 | 仍有效 | `_style_name`、`_run_to_markdown`（删除线）、`_table_to_markdown`（行吞掉）三处吞错原样。注意：:356 表行项有开放 PR #1700（占位行+告警，未合并），:256/:340 无覆盖 |
| 5 | fix-reading-refs-fallback | `reading/references.py` `resolve_reading_sources` 报 :118/:135 → 实测 :118-120/:135-137 | 仍有效 | 两处 `except Exception: continue` 原样在场，无失败项计数、无日志 |
| 6 | fix-reading-duplicate-check | `api/routers/reading.py` `duplicate_check` 报 :518（函数 :486）→ 实测函数 :486、吞错 :518-521 | 仍有效 | `except Exception: continue` 原样在场（注释声明 malformed URL 语义），仍无日志、响应无"部分未校验"标注 |
| 7 | fix-skill-tool-read-fallback | `tools/builtin/__init__.py` 报 :1711 → 实测 :1711（`continue` 在场） | **已修复** | 行为已变：`SkillFileNotFoundError` → 显式 `ToolResult(success=False)` 并列出技能内文件（:1712-1727）；`SkillNotFoundError: continue` 落到循环外兜底 `(skill not found …)` `success=False`（:1729-1735）。修复提交 #1349（2cefc62a7，2026-09-10）+ #1347/#1370（9ad83d063）。卡面"看似成功的残缺结果"不再可能 |
| 8 | fix-markitdown-format-detect | `parsing/engines/markitdown/formats.py` 报 :76/:82（函数 :62）→ 实测函数 :62、吞错 :87-88/:97-98 | 仍有效（收窄） | 吞错原样、无日志；但返回值已并入 `MARKITDOWN_0_1_7_FORMATS` 底集（:100），"集合为空"已不可能，剩余缺陷=静默+可能过时。卡面验收需按此收窄 |
| 9 | fix-notebook-blanket-500 | `api/routers/notebook.py` 12 处 blanket-500 `str(e)` | 仍有效 | 实测 12 处，行号 :206,223,248,272,303,327,362,397,425,441,457,477 与卡面完全一致，零漂移 |
| 10 | fix-book-blanket-500 | `api/routers/book.py` 12 处 blanket-500 `str(exc)` | 仍有效 | 实测 12 处，行号 :834,864,900,926,952,997,1066,1096,1367,1415,1437,1458 与卡面完全一致（另有 :1216 非 str 透传的 500，不在卡面范围） |
| 11 | fix-knowledge-blanket-500 | `api/routers/knowledge.py` 约 36 处 → 实测 36 处 | 仍有效 | 单行 `raise HTTPException(status_code=500, detail=str(...)` 精确计数 36，区间 :1427–4690，与卡面"约 36 处"一致。注意：开放 PR #1706 同文件（KB status/progress/folder-sync 吞错，非本卡范围），合并后本卡行号将漂移 |
| 12 | fix-cowriter-blanket-500 | `api/routers/co_writer.py` 14 处 blanket-500 | 仍有效 | 实测 14 处，行号 :546,561,597,609,626,643,716,728,797,806,817,839,857,874 与卡面逐行一致，零漂移 |

## 3. 统计

- 抽检 12/12（DT-22 系 8/8 全覆盖、blanket-500 系 4/4 全覆盖）
- **失效 2 张（16.7%）**：fix-lightrag-worker-loop（误报）、fix-skill-tool-read-fallback（#1349/#1370 已修）
- **仍有效 10 张（83.3%）**，其中收窄 2 张：fix-session-migration-swallow（守卫已落地）、fix-markitdown-format-detect（底集已兜底）
- **移位 0 张**；行号漂移仅 fix-session-migration-swallow（+16），其余 ≤3 行或零漂移

## 4. 建议下架清单（确凿，2 张 ≤5）

1. **fix-lightrag-worker-loop** — 所指 `except BaseException: pass` 后紧跟 `raise`，任务异常已向调用方传播；卡面"索引失败按成功处理"的前提在 v1.6.12 与 f07029cf 均不成立。继续派工会造成对无缺陷代码的"修复"。
2. **fix-skill-tool-read-fallback** — #1349 + #1347/#1370 已合并：缺失文件返回显式 `success=False` 并列出可用文件，缺失技能返回显式 not-found 结果；卡面失败模式已消除。

（fix-session-migration-swallow 未列入：核心歧义已由 #1398 守卫解决，但"真失败留痕"仍缺，建议改卡缩范围后保留，而非下架。）

## 5. 开放 PR 重叠提示（防重复派工）

| 开放 PR | 与抽检卡的关系 |
| --- | --- |
| #1700（docx_converter.py，未合并） | 覆盖 fix-docx-converter-style-fallback 的 :356 表行项；:256/:340 仍无覆盖。派工前先确认该 PR 进展 |
| #1706（api/routers/knowledge.py，未合并） | 与 fix-knowledge-blanket-500 同文件不同缺陷；合并后本卡 36 处行号全部漂移，届时以函数名定位 |

## 6. 复核命令（可复跑）

```bash
cd /Users/Shared/DeepTutor/dt-agen901-verifypool-wt   # 分支 verify/fix-pool-stale-20261006 @ f07029cf
git rev-parse HEAD                                    # f07029cfcf2c8dfccdb671cdfc343db8334f5741
grep -n "except Exception" deeptutor/services/rag/pipelines/modes.py | head -2          # 卡3 :37
sed -n '249,252p' deeptutor/services/rag/pipelines/lightrag/worker.py                   # 卡1 pass+raise
sed -n '467,473p' deeptutor/services/session/sqlite_store.py                            # 卡2 守卫
grep -c "raise HTTPException(status_code=500, detail=str(" deeptutor/api/routers/knowledge.py   # 卡11 = 36
grep -c "raise HTTPException(status_code=500, detail=str(" deeptutor/api/routers/notebook.py    # 卡9 = 12
grep -c "raise HTTPException(status_code=500, detail=str(" deeptutor/api/routers/book.py        # 卡10 = 12(另:1216)
grep -c "raise HTTPException(status_code=500, detail=str(" deeptutor/api/routers/co_writer.py   # 卡12 = 14
git log --oneline -L1700,1725:deeptutor/tools/builtin/__init__.py | grep -E '^[0-9a-f]{7,}' | head -3  # 卡7 修复提交
```

- 本次为纯只读抽检：无测试运行、无产品代码改动、无服务/守护进程启动。
