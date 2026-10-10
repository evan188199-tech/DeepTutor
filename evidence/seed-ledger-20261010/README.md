# seed-ledger 2026-10-10 — 跨扫描报告种子台账与剩余可领取清单

AGEN-1365 产物。只读汇总：把六份近期扫描报告发布的可执行种子合并为一本三态台账
（已建卡 / 已被 main 测试覆盖 / 仍可建卡），并输出下一轮 harvest 的可领取清单。

## 结论速览

| 指标 | 值 |
|---|---|
| 种子总数（去重后） | **372** |
| 已建卡 | 219 |
| 已被 main 测试覆盖（v1.6.14 复扫） | 22 |
| **仍可建卡** | **131** |

轴分布：B（CLI 零测试）6 = 卡6/覆盖0/可领0；C（weak100）100 = 卡80/覆盖8/可领12；
D（通道契约 A–M）13 = 卡4/覆盖0/可领9；E（错误消息 Top15）15 = 卡12/覆盖0/可领3；
F（zero96 + weak242 tail142）238 = 卡117/覆盖14/可领107；A（todo-sweep）0 种子。

## 输入与出处（inputs/ 全部只读）

| 文件 | 出处 |
|---|---|
| `baseline-summary-f07029cf.json` | myfork `scan/coverage-gaps-20261007` `evidence/coverage-gaps-20261007/summary.json`（AGEN-982，基线 v1.6.13 `f07029cf`，zero96/weak100/fanin50） |
| `baseline-weak242-rows.json` | myfork `scan/weak-top100-triage-20261008` 的 `triage.py` 在本机复算输出 rows.json（AGEN-1154 逻辑，断言 weak242/top100/zero200 与上表 summary 一致；内含 2026-10-08 人工 DONE60 映射） |
| `rerun-main-6cf793bd8-coverage.json` | 用同一 scan/aggregate 脚本对 `origin/main 6cf793bd8`（v1.6.14，2026-10-10 fetch）重扫后的种子级蒸馏（338 模块 × 触达测试路径） |
| `rerun-main-6cf793bd8-cli.json` / `-cmdcov.json` | myfork `evidence/cli-zero-triage-20261009` 的 `scan_cli_zero.py` + `compute_cmd_coverage.py` 对 v1.6.14 重跑输出 |
| `tail-triage-23.json` | myfork `scan/weak-tail-triage-20261009` `triage_tail.json`（AGEN-1315，weak242 tail fanin≥2 的 23 种子） |
| `backlog-keys-20261010.jsonl` | Multica 看板快照：全状态 1370 张卡的 identifier/title/status（2026-10-10 抓取，去重依据） |

## 三态口径

- **已建卡**：看板存在指向该种子的非取消卡。依据 = 卡 key。
- **已被 main 测试覆盖**：v1.6.14 复扫中模块触达数达阈值（基线 zero≥1、基线 weak≥2；CLI 轴 test_refs>0）。依据 = 覆盖测试路径。
- **仍可建卡**：两者皆无。依据 = 报告锚点（模块 path / 报告条目）。

## 匹配与人工复核方法（可复算）

`build_ledger.py`（stdlib）读 inputs/ 产出 seed-ledger.md / claimable-seeds.md / seeds.json：

1. 卡匹配按优先级：标题含模块 path 片段（≥2 段 slash 形式）→ dotted 形式（≥2 段）→
   词干匹配（全种子集唯一词干、len≥4、不在停用词表；扩展 token 仅在跨分隔符且 token
   不是其他种子词干时接受，如 `build_tool_options` 接受、`ask_user_trace`/`reasoning` 拒绝；
   `stem/更深末段` 归属更深模块）。
2. 卡按标题首词分级：test/fix/补测/refactor/chore/rework/pr-ready 为**领取级**；
   guide/docs/scan/verify/review 为**相关级**（只进备注，不构成领取去重——与 CLI 报告
   "guide/scan 卡不构成补测去重" 同一口径）。
3. cancelled 卡不算已建卡；done 卡落在仍零/弱覆盖的模块上时备注"领卡前核验原卡产出"。
4. 人工覆盖（标题不含模块名但目标明确）：C15←AGEN-1285、FZ40←AGEN-969、FZ52←AGEN-774、
   FT80←AGEN-1011（AGEN-1315 去重结论）、FT26←AGEN-1346。
5. 全部 auto 匹配经人工逐条复核（165 张不同卡片标题逐一过目），FP 修正后定格。

## 去重边界（卡面指定）

- weak100 三态沿用 AGEN-1154（`scan/weak-top100-triage-20261008`）的 triage 与 DONE 映射，本卡不重排；
- weak242 tail 中 fanin≥2 的 23 个种子沿用 AGEN-1315（`scan/weak-tail-triage-20261009`）的清单与焦点，本卡只更新三态；
- card→模块覆盖漂移方向归 AGEN-1316（`verify: weak242 已建卡 60 模块覆盖漂移复核`），本卡为跨报告汇总方向；
- 卡面点名的 verify-test-pool-drift 在本看板未检索到同名卡，以 AGEN-1316 为最近似在板轴。

## v1.6.13→v1.6.14 覆盖漂移要点

- 基线 zero96 中 7 个已被测试覆盖：`api.utils.progress_broadcaster`、`services.base_sync`、
  `services.llm.cloud_provider`、`services.llm.provider_core.github_copilot_provider`、
  `services.session.turns.title_service`、`tools.tex_chunker`、`tools.tex_downloader`；
- 基线 weak242 中 15 个触达≥2（含 weak100 的 8 个，清单见 seed-ledger.md 附录）；
- 漂移异常：`services.session.workspace_preferences`（weak100 #25）唯一覆盖测试在 v1.6.14 消失，降为 zero；
- 新增零覆盖模块（v1.6.14 新文件，不在已发布清单）：`learning.visual_practice`、
  `plugins.transactions`、`runtime.cache_reset`、`services.session.workspace_preferences`。

## 已知限制

- 卡匹配基于卡标题（1370 张的 title/status），未逐张读描述；wording 特殊的卡可能漏配，
  领卡前应按 claimable 行的模块名做当日看板复核。
- done 状态卡的产出是否落库以 fresh 复扫为准，卡片状态本身不代表 main 覆盖状态。
- D/E 轴为修复型种子，"已被 main 测试覆盖"仅对测试型种子定义；修复卡是否落 main 以
  复核注释中的代码签名抽查为准（抽查于 2026-10-10，均未落）。

## 复现

```bash
# 1. 基线 weak242 全排序（triage.py 内建断言与 summary.json 一致）
git show myfork/scan/weak-top100-triage-20261008:evidence/weak-triage-20261008/triage.py > /tmp/triage.py
python3 /tmp/triage.py <临时目录>   # 需邻位放置 coverage-gaps-20261007 的 raw+summary

# 2. v1.6.14 复扫（worktree 根执行）
python3 evidence/coverage-gaps-20261007/scan_coverage_gaps.py   # 脚本取 self 相对路径，需置于 <root>/x/y/ 下运行
python3 evidence/coverage-gaps-20261007/aggregate.py

# 3. CLI 轴复跑
python3 evidence/cli-zero-triage-20261009/scan_cli_zero.py <root> out.json
python3 evidence/cli-zero-triage-20261009/compute_cmd_coverage.py <root> out.json

# 4. 台账重建
python3 evidence/seed-ledger-20261010/build_ledger.py
shasum -a 256 -c evidence/seed-ledger-20261010/SHA256SUMS
```

## 边界遵守

- 只读：未改任何产品代码/测试；本分支仅新增 `evidence/seed-ledger-20261010/`。
- 未运行 pytest、未启动任何服务/守护进程；无遗留子进程。
- 推送前已核对 `gh pr list -R HKUDS/DeepTutor --author @me --state open` 的 4 个分支与
  `main`/`dev`，本卡分支 `evidence/seed-ledger-20261010` 不在其中。
