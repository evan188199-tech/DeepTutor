# still-claimable 存疑种子 fresh 复扫（AGEN-1793，2026-10-11）

只读复扫：把 myfork `evidence/verify-seed-ledger-drift-20261011/still-claimable-20261011.md`
（AGEN-1686 产物，17 条）中带存疑备注的种子对当日最新 origin/main 与当日看板重扫，
逐条给出「仍可领取 / 已被触达（含已建卡）」结论，并给出与基线的 diff。

## 结论速览

| 指标 | 值 |
|---|---|
| 复扫对象 | 备注种子 **9** 条（E14、FZ92、FZ96、FT35、FT50、FT75、FT116、FT120、FT129）＋其余 8 条顺带复扫 |
| origin/main | `6cf793bd8`（v1.6.14）——**与基线 fresh 复扫同一 commit**，main 侧零漂移 |
| 看板 | 1795 张（基线快照 1686 → **+109**，漂移全部来自卡池侧） |
| 备注种子结论 | 仍可领取 **4**（E14、FZ92、FZ96、FT35）；已被建卡 **5**（FT50、FT75、FT116、FT120、FT129） |
| 全 17 条结论 | 仍可领取 **7**（＋FZ51、FZ94、FT115）；已被建卡 **10** |

主要漂移：基线快照后看板新拆了 **10 张 test 级领取卡**（AGEN-1767/1768/1770/1773/1774/
1776/1778/1779/1780 + AGEN-1671/1689），全部 in_review，标题逐条点名 FT46/FT50/FT75/
FT116/FT122/FT129/FT133/FT139/FZ95 及 visualize/code_generator_agent 路径。**still-claimable
清单当日过时近六成，下轮 harvest 必须以本清单为准。**

## 备注种子逐条结论

| ID | 结论 | fresh 复扫依据（LOC/fanin/触达） | 备注/存疑处理 |
|---|---|---|---|
| E14 | **仍可领取**（主项） | 错误消息轴无单模块指标；看板重扫无主项领取卡 | 子集卡 AGEN-1364（sessions.py 27 处）、AGEN-880（web 解析层）均 in_review 不变；AGEN-814 为词干命中（sessions.deleted_at schema fix，卡面核对非本主题） |
| FZ92 | **仍可领取** | `__version__` LOC 11，触达 0（零阈值 1 未达） | **fanin 2→3 漂移**：v1.6.14 新增 `plugins/registry.py` 导入（现 registry/banner/app_update 三处），覆盖状态不变；AGEN-1716（=基线 note 的 citation-version-parity 卡）verify 级 done，不去重 |
| FZ96 | **仍可领取** | LOC 3，fanin 0，触达 0——全部与基线一致 | AGEN-1265 guide 级 done，不去重（基线同判，再次确认） |
| FT35 | **仍可领取** | LOC 177，fanin 1，触达 1（`tests/video_learning/test_invidious_account.py`）<弱阈值 2 | AGEN-806 卡面重读：范围 invidious_account.py(360行)+client(85行)，**确认不含 storage.py**，基线备注成立 |
| FT50 | **已被建卡** | LOC 98，fanin 1，触达 1<2（覆盖本身不去重） | **AGEN-1768**（test 级，标题点名 FT50，in_review）；AGEN-1693（embedding openai_compatible）、AGEN-1056（voice openai_compat）为同词干异包 FP，不算 |
| FT75 | **已被建卡** | LOC 100，fanin 2；**触达数 fresh 复扫=1**（`tests/textbook_struct/test_page_headers.py` 直连导入 page_headers 符号），低于弱阈值 2——基线存疑解除：AGEN-791 所称"现有测试"即此 1 条，覆盖本身不构成去重 | **AGEN-1770**（test 级，标题点名 FT75，in_review）领取；AGEN-791 卡面焦点为 chapter_rebuild/列黑名单，不含 page_headers 补测；AGEN-1315 scan 级 done |
| FT116 | **已被建卡** | LOC 135，fanin 1，触达 1<2 | **AGEN-1773**（test 级，标题点名 FT116，in_review）；AGEN-1240 标题确认为 web lib settings-presets，非本后端模块（基线同判） |
| FT120 | **已被建卡** | LOC 117，fanin 1，触达 1<2 | **AGEN-1671 + rework AGEN-1689**（test 级，标题点名 visualize/code_generator_agent 路径，in_review）领取；AGEN-1344 为 math_animator 同名异包（基线同判） |
| FT129 | **已被建卡** | LOC 55，fanin 1，触达 1<2 | **AGEN-1776**（test 级，标题点名 FT129，in_review）；AGEN-1009 卡面重读：文件清单 oauth/service/storage/catalog，**确认不含 client_version.py** |

## 其余 8 条顺带复扫（防 harvest 撞车）

| ID | 结论 | 依据 |
|---|---|---|
| FZ51 | 仍可领取 | LOC 86，fanin 2，触达 0；看板无领取级卡 |
| FZ94 | 仍可领取 | LOC 8，fanin 2，触达 0；看板无领取级卡 |
| FZ95 | 已被建卡 | **AGEN-1780**（test 级，点名 FZ95，in_review） |
| FT46 | 已被建卡 | **AGEN-1767**（test 级，点名 FT46，in_review） |
| FT115 | 仍可领取 | LOC 158，fanin 1，触达 1<2；看板无领取级卡 |
| FT122 | 已被建卡 | **AGEN-1774**（test 级，点名 FT122，in_review） |
| FT133 | 已被建卡 | **AGEN-1778**（test 级，点名 FT133，in_review） |
| FT139 | 已被建卡 | **AGEN-1779**（test 级，点名 FT139，in_review） |

## 与基线的 diff 结论

1. **main 侧零漂移**：origin/main 仍为 `6cf793bd8`（v1.6.14），与基线 fresh 复扫同一
   commit；9 条备注种子所在模块逐一 `git cat-file` 确认在位，LOC 全部一致。
2. **指标漂移仅 1 处**：FZ92 `__version__` fanin 2→3（v1.6.14 新增 plugins/registry.py
   导入）；触达数全部与基线一致（6 条 weak 均为 1，4 条 zero 均为 0），无一越过阈值
   （zero≥1、weak≥2）——**覆盖口径下 17 条在基线时点的「仍可领取」判定全部复现成立**。
3. **卡池侧大漂移**：基线快照 1686 → 1795（+109）。still-claimable 17 条中 **10 条已
   被新拆 test 级卡领取**（全部 in_review，无一 cancelled/done 落库），判断「已被触达」
   以领取级卡在板为准（与基线「已建卡」口径一致）；test/rework 卡在 in_review 即构成
   领取，防止重复建卡。
4. **存疑备注全部关闭**：FT75 触达数已确认（1<2，AGEN-791 所称现有测试不构成去重，
   实际领取卡为 AGEN-1770）；FZ92/FZ96 相关卡均为 guide/scan/verify/review 级，
   确认不构成去重；FT35/FT129 相关卡文件清单经卡面重读确认不含目标模块。
5. **下轮 harvest 可直接取用**（7 条）：E14、FZ92、FZ96、FT35、FZ51、FZ94、FT115；
   其中 FZ92 领取时可顺带覆盖 fanin 漂移（registry/banner/app_update 三调用方）。

## 口径说明（与基线一致）

- **LOC**：模块文件行数（`wc -l` 等价，逐条与基线一致）。
- **fanin**：逐字移植 `scan/weak-top100-triage-20261008` triage.py 的 AST import
  fan-in（仅统计 deeptutor 包内导入方；`from X import n` 同记 X 与 X.n）。
- **触达数**：tests/ 与包内 in-tree test 文件的 AST import 引用扫描（`import` 与
  `from` 两种形式，含 from-符号展开）；与基线 coverage-run 口径在本 commit 上结果
  一致（8 条模块种子逐条相等）。阈值沿用基线：zero≥1、weak≥2。
- **已建卡**：看板存在指向该种子的非取消领取级卡（test/fix/补测/refactor/chore/
  rework/pr-ready 前缀，或标题点名 seed ID/模块路径）；guide/docs/scan/verify/review
  前缀为相关级，只进备注不构成去重。同词干异包命中经逐卡读题人工排除（FP 清单见
  `seeds-fresh-state-20261011.json` 的 `manual_fp`）。

## 文件

| 文件 | 内容 |
|---|---|
| `fresh-rescan-20261011.md` | 本报告（fresh 复扫清单＋与基线 diff） |
| `seeds-fresh-state-20261011.json` | 机器可读逐条结论（指标、drift、卡匹配、人工 FP/确认标注） |
| `verify_seeds_fresh.py` | 复扫脚本（stdlib；可复跑全部指标与匹配） |
| `SHA256SUMS` | 产物校验和 |

看板快照 `board-snapshot-fresh.jsonl`（1795 张 identifier/title/status）为输入而非
产物，不入分支；脚本缺省路径找不到快照时会经 `multica issue list` 自动重拉。

## 复现

```bash
# 输入（全部只读）：/Users/Shared/DeepTutor 已 fetch origin/myfork
git -C /Users/Shared/DeepTutor worktree add /tmp/dt-agen1793-wt \
  -b evidence/verify-seeds-fresh-20261011 origin/main
DT_WT=/tmp/dt-agen1793-wt python3 evidence/verify-seeds-fresh-20261011/verify_seeds_fresh.py
shasum -a 256 -c evidence/verify-seeds-fresh-20261011/SHA256SUMS
git -C /Users/Shared/DeepTutor rev-parse origin/main   # 6cf793bd8…（与基线一致）
```

复跑若看板晚于 2026-10-11，卡池继续前移属预期；以本报告表内「卡 状态」为当日定论。

## 边界遵守

- 纯只读复扫：未改产品代码/测试，未跑 pytest，未启动服务/守护进程，无遗留子进程；
  本分支仅新增本目录。
- 推送前已核对 `gh pr list -R HKUDS/DeepTutor --author @me --state open` 的 4 个开放
  分支与 `main`/`dev`，本卡分支 `evidence/verify-seeds-fresh-20261011` 不在其列。
- 本卡为证据卡，不开上游 PR。
