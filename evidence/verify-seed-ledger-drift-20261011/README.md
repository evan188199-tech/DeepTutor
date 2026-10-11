# seed-ledger drift 复核（AGEN-1686，2026-10-11）

只读复核：把 myfork `evidence/seed-ledger-20261010` 台账的 131 条 claimable 种子与
当前卡池（Multica 看板快照 + glm-reserve 储备池）对表，逐条给出三态结论，并产出
下轮 harvest 可直接取用的 still-claimable 清单。

## 结论速览

| 指标 | 值 |
|---|---|
| 逐条结论 | **131/131** |
| 已建卡 | 114 |
| 主题被覆盖（模块已不在 main） | 0 |
| **仍可领取** | **17**（E=1，D=0，C=0，F=16） |

- main 侧覆盖状态不变：`origin/main` 仍为 `6cf793bd8`（v1.6.14），与台账 fresh
  复扫同一 commit；已逐一 `git cat-file` 确认 131 条涉及模块均仍在 main。
- 漂移主因是**卡池侧**：台账快照（2026-10-10，1370 张）→ 本次快照 1686 张
  （+316）；D 轴 9 条全部有卡（AGEN-1447/1449/1451/1452/1453/1497/1498/1499/1504，
  均 in_review），E13→AGEN-1509、E15→AGEN-1506。
- 台账的标题匹配器对三类措辞不可见（空格形式模块名、描述点名、批量卡 scope），
  本次人工读卡补配 34 个种子的结论（另为 FZ77 补上看板卡证据），共 38 张卡，
  每条理由写在 `seeds-state-20261011.json` 的 `why` 字段。

## 文件

| 文件 | 内容 |
|---|---|
| `drift-conclusions-20261011.md` | 131 条逐条结论（≤200 行）＋复核命令 |
| `still-claimable-20261011.md` | 17 条仍可领取清单（含领取注意事项） |
| `seeds-state-20261011.json` | 机器可读逐条结论与依据卡 |
| `verify_drift.py` | 复核脚本（stdlib；可复跑全部结论） |
| `SHA256SUMS` | 以上产物校验和 |

看板快照 `board-snapshot-20261011.jsonl`（1686 张卡 identifier/title/status）为输入
而非产物，不入分支；脚本缺省路径找不到快照时会经 `multica issue list` 自动重拉。

## 复现

```bash
# 输入（全部只读）
# 1) 台账：git -C /Users/Shared/DeepTutor show myfork/evidence/seed-ledger-20261010:... 
#    或任意 checkout，导出 SEED_LEDGER_DIR 指向 evidence/seed-ledger-20261010/
# 2) 储备池：/Users/xzh/services/ai-development/multica-board-agent/glm-reserve/reserve/backlog/*.jsonl
# 3) main：git -C /Users/Shared/DeepTutor fetch origin

SEED_LEDGER_DIR=<台账目录> python3 evidence/verify-seed-ledger-drift-20261011/verify_drift.py
shasum -a 256 -c evidence/verify-seed-ledger-drift-20261011/SHA256SUMS
git -C /Users/Shared/DeepTutor rev-parse origin/main   # 应为 6cf793bd8…（与台账一致）
```

复跑若快照晚于 2026-10-11，卡池继续前移属预期；以 `drift-conclusions-20261011.md`
表内逐条「依据（卡 状态）」为当日定论。

## 边界遵守

- 纯只读：未改 backlog 池、未改产品代码/测试；本分支仅新增本目录。
- 未运行 pytest、未启动服务/守护进程；无遗留子进程。
- 推送前已核对 `gh pr list -R HKUDS/DeepTutor --author @me --state open` 的开放
  分支与 `main`/`dev`，本卡分支 `evidence/verify-seed-ledger-drift-20261011` 不在其列。
