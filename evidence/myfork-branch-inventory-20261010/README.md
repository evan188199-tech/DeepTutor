# myfork 远端分支合入状态台账（AGEN-1363）

生成时间: 2026-10-10 (UTC)。数据源: `/Users/Shared/DeepTutor`，执行 `git fetch --multiple origin myfork` 后只读分析 `refs/remotes/myfork/*`（排除 `myfork/HEAD` 符号引用）。本卡未删除、未修改、未强推任何既有分支。

## 判定方法（可复算）

对每个远端分支 B，相对 `origin/main`（1158 个分支共用同一基线 `6cf793bd868ba5ecbe64722936d4be8fab5a01df`）逐条计算：

1. `tip = git rev-parse B`
2. `merge_base = git merge-base origin/main B`
3. `behind, ahead = git rev-list --left-right --count origin/main...B`
4. `git cherry origin/main B`：`+N` = main 中无等价补丁的独有提交数，`-N` = 已有等价补丁的提交数
5. `git merge-base --is-ancestor B origin/main`

### 状态判定规则

| 状态 | 条件 |
| --- | --- |
| 已合入 merged | tip 是 origin/main 祖先，**或** cherry `+` 数为 0（全部补丁在 main 中有等价物，如 squash 合并） |
| 过期 stale | 有独有补丁（`+`>0）且最后提交早于 30 天（以 committer date 计，基准 2026-10-10） |
| 独有 unique | 有独有补丁（`+`>0）且最后提交在 30 天内 |

### 分级（结合分支名前缀）

| 分级 | 对应状态 | 含义 |
| --- | --- | --- |
| 可归档 archive | merged | 内容已全部进入 origin/main，远端分支可安全归档/删除（本卡未删，仅建议） |
| 需确认 confirm | stale | 含独有提交但长期未动，需人确认是否还有价值 |
| 保留 keep | unique | 30 天内有活动的独有工作，保留 |

前缀列取分支名首个路径段（`codex/archive/stash` 保留三段），用于观察命名分布。

## 汇总

- 总分支数: **1158**
- 已合入 merged: **102** → 可归档 archive: **102**
- 过期 stale: **147** → 需确认 confirm: **147**
- 独有 unique: **909** → 保留 keep: **909**
- 校验: 102 + 147 + 909 = 1158（与明细行数一致）

### 前缀 × 分级分布（粗粒度，首个路径段）

| 前缀 | 可归档 | 需确认 | 保留 | 小计 |
| --- | ---: | ---: | ---: | ---: |
| ag1382 | 0 | 0 | 1 | 1 |
| agen | 0 | 0 | 5 | 5 |
| agen1004 | 0 | 0 | 1 | 1 |
| agen1084 | 0 | 0 | 1 | 1 |
| agen1126 | 0 | 0 | 1 | 1 |
| agen1134 | 0 | 0 | 1 | 1 |
| agen1293 | 0 | 0 | 1 | 1 |
| agen1301 | 0 | 0 | 1 | 1 |
| agen1304 | 0 | 0 | 1 | 1 |
| agen1359 | 0 | 0 | 1 | 1 |
| agen351 | 0 | 0 | 1 | 1 |
| agen485 | 0 | 0 | 1 | 1 |
| agen553 | 0 | 0 | 1 | 1 |
| agent | 1 | 0 | 42 | 43 |
| archive | 1 | 4 | 0 | 5 |
| audit | 0 | 0 | 2 | 2 |
| backup | 0 | 3 | 0 | 3 |
| chore | 0 | 0 | 1 | 1 |
| codex | 77 | 137 | 48 | 262 |
| course-loop | 0 | 1 | 0 | 1 |
| docs | 0 | 0 | 33 | 33 |
| dt | 0 | 0 | 6 | 6 |
| evidence | 0 | 0 | 10 | 10 |
| feat | 2 | 0 | 9 | 11 |
| fix | 7 | 0 | 123 | 130 |
| followup | 1 | 0 | 3 | 4 |
| glm | 0 | 0 | 2 | 2 |
| glm-reserve | 0 | 0 | 4 | 4 |
| guide | 2 | 0 | 47 | 49 |
| main | 0 | 0 | 1 | 1 |
| myfork | 4 | 0 | 59 | 63 |
| pr | 2 | 0 | 23 | 25 |
| pr-assets | 0 | 1 | 0 | 1 |
| refactor | 0 | 0 | 2 | 2 |
| review | 0 | 0 | 4 | 4 |
| scan | 0 | 0 | 85 | 85 |
| test | 5 | 0 | 351 | 356 |
| tests | 0 | 0 | 3 | 3 |
| verify | 0 | 0 | 15 | 15 |
| web | 0 | 0 | 18 | 18 |
| web-evidence | 0 | 0 | 1 | 1 |
| workspace | 0 | 1 | 0 | 1 |

## 特殊情形

- `verify/1902-evidence-reuse-20261009` 与 origin/main 无共同祖先（`git merge-base` 返回空），按 cherry 全部为 `+`、最后提交 0 天 → 独有/保留。
- 39 个分支 tip 非祖先但 cherry `+` 数为 0：补丁已等价进入 main（常见于 squash/cherry-pick 合并），按已合入计。
- 明细中 `merge_base`/`ahead`/`behind` 为空的行即上述无共同祖先分支。

## 文件

- `branches.tsv` — 全量台账（每分支一行：tip、日期、merge_base、ahead/behind、cherry ±、判定）
- `archive-can-archive.md` — 可归档清单（102）
- `confirm-needs-review.md` — 需确认清单（147）
- `keep-retained.md` — 保留清单（909）
- `SHA256SUMS` — 以上文件校验和（SHA256SUMS 自身除外）

## 复算命令示例

```sh
git -C /Users/Shared/DeepTutor fetch --multiple origin myfork
B=myfork/<分支名>
git rev-parse "$B"
git merge-base origin/main "$B"
git rev-list --left-right --count origin/main..."$B"
git cherry origin/main "$B"
git merge-base --is-ancestor "$B" origin/main && echo ancestor
```
