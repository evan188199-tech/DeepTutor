# 储备池台账三方对账：pools.json × backlog/*.jsonl × deeptour.consumed（2026-10-11）

- 卡：AGEN-1808（`verify: 储备池台账三方对账（pools/backlog/consumed）`）
- 复核对象（只读，未做任何修改）：`/Users/xzh/services/ai-development/multica-board-agent/glm-reserve/reserve/`
- 口径：与 `multica_board_agent/reserve.py` 加载语义一致 —— `load_backlog` 按 `deeptour.jsonl` +
  `deeptour.*.jsonl` 顺序读入、首现 key 生效、非法行跳过并报错；`deeptour.consumed` 逐行核销（任意非空行都是一个 key，
  不支持注释）；`plan_refill` 以看板 marker 为 seen，consumed 伪卡状态为 done，被核销的 key 永不重建。
- 去重边界：本卡不重复上一轮 `verify-pools-json-parity-20261011`（pools↔backlog 结构轴，当日口径 1076 键）
  与 `verify-seed-ledger-drift-20261011`（种子轴）；本卡为三方 key 级对账 + 消费残留深查，数据为当日最新。

## 一、三方对账表（key 级，零遗漏）

| 轴 | 项 | 数值 |
|---|---|---|
| pools.json | 声明池 | deeptour ×1（target 8；agents {GLM 5.3, GLM 5.3 Flash}；capacity 2/3；queue_depth 2） |
| pools.json | 内部一致性（capacity/harvest.executor ⊆ agents、agent id 非空） | 0 问题 |
| pools.json | 加载盲区文件（backlog/ 下不被 glob 覆盖的文件） | 0 个（4 个文件全部被 `deeptour.jsonl` / `deeptour.*.jsonl` / `deeptour.consumed` 覆盖） |
| backlog/*.jsonl | 数据行（非空行） | 1136 = 13（deeptour.jsonl）+ 11（0priority）+ 1112（auto） |
| backlog/*.jsonl | 非法行（JSON/缺字段/多余字段） | 0 |
| backlog/*.jsonl | 唯一 key（首现生效） | 1136 |
| backlog/*.jsonl | 重复 key（同文件/跨文件） | 0 |
| deeptour.consumed | 非空行 / 唯一 key / 重复 | 10 / 10 / 0 |
| 三方集合 | live = backlog − consumed | **1131** |
| 三方集合 | backlog ∩ consumed（已被核销但仍在 backlog 里） | **5**（见漂移清单 D1） |
| 三方集合 | consumed − backlog（核销无台账对应） | **5**（见漂移清单 D2） |

守恒校验：唯一 1136 + 重复多余 0 + 非法 0 = 1136 数据行（通过）；live 1131 + shadowed 5 = 1136（通过）；
consumed 10 = shadowed 5 + dangling 5（通过）。执行器分布（live）：GLM 5.3 ×295、GLM 5.3 Flash ×836。

与上一轮（pools-json-parity，当日 1076 键）对比：`deeptour.auto.jsonl` 1052 → 1112（+60，全部为合法新增行，
无重复无非法），live 供给 1071 → 1131（+60）；三个核销残留 key 数不变。

## 二、漂移清单（逐条）

### D1 · backlog∩consumed 残留 5 条（台账仍列作候选，实际已被核销、永不重建）

| # | key | backlog 位置 | consumed 佐证 | 影响 |
|---|---|---|---|---|
| 1 | up-1678 | deeptour.jsonl:1 | claims.json：issue closed + merged PR #1683 | 惰性：plan_refill 视为 seen(done)，不会建卡 |
| 2 | up-1647 | deeptour.jsonl:2 | claims.json：issue closed + merged PR #1666（另注明 09-29 被认领） | 同上 |
| 3 | up-1646 | deeptour.jsonl:3 | claims.json：issue closed + merged PR #1685 | 同上 |
| 4 | guide-reading | deeptour.jsonl:5 | consumed 核销（非 up-N，无 claims 记录） | 同上 |
| 5 | guide-mastery | deeptour.jsonl:6 | consumed 核销（非 up-N，无 claims 记录） | 同上 |

- 等级：低（不产生错误建卡，但台账供给计数虚高 5；`2 × target` 的 harvest 触发判断按"未见过的候选"计数，
  这 5 条已被 seen 排除，不影响 harvest 判断）。
- 佐证独立性：三个 up-N 的 claims 状态（21:50Z 刷新）与 consumed 核销一致，双向印证。

### D2 · consumed−backlog 悬空核销 5 条（核销台账有、backlog 无对应行）

| # | key | 台账线索 | 评估 |
|---|---|---|---|
| 1 | bundle-tests-backend | 仅 deeptour.consumed:9；auto.jsonl:252 的 `verify-consumed-tests-green` 卡描述引用其分支名 | 预期机制：key 来自已归档看板，consumed 即唯一存续记录 |
| 2 | bundle-tests-frontend | deeptour.consumed:10；同上引用 | 同上 |
| 3 | bundle-logging-storage | deeptour.consumed:7 | 同上 |
| 4 | bundle-logging-runtime | deeptour.consumed:8 | 同上 |
| 5 | rework-AGEN-136 | deeptour.consumed:6 | 同上（rework 轴，AGEN-136 的返工卡） |

- 等级：低。consumed 承担"退役看板交付墓碑"职责（reserve_remote.py `_consumed`），这 5 条是该职责的正常产物，
  非错误；列出仅为满足 key 级零遗漏对账。注意 consumed 文件不支持注释行（任何非空行都会成为 key），
  溯源信息只能放在 evidence，不能写进 consumed 本身。

### 其余维度

- 重复：无（同文件、跨文件、consumed 内部均无）。
- 非法行：无。executor 未声明（会被静默过滤）：无。after 依赖悬空/类型异常：无。
- pools.json 声明缺口：无（与上一轮 parity 结论一致，本轮复核仍为 0）。

## 三、修复建议（可执行，本卡不代执行）

1. **R1（D1，可选清理）**：从 `deeptour.jsonl` 删除 5 条残留行（行 1、2、3、5、6，即 up-1678/up-1647/up-1646/
   guide-reading/guide-mastery），使 backlog 清单与 live 供给一致。删除前无需迁移——consumed 与 claims 已是交付凭证。
   若选择保留，行为安全（加载器使其中性），但需接受供给计数 −5 的口径。
2. **R2（D2，不建议改台账）**：保持 consumed 现状。不要向 consumed 加注释/表头（会被当作 key 解析）；
   若需溯源，把 5 条墓碑 key 的原始卡内容存到 evidence 或 backlog/ 之外的归档路径
   （注意 `deeptour.*.jsonl` 命名会被加载器拾取，归档文件不要用该前缀命名）。
3. **R3（流程加固，可选）**：harvest 卡"只追加 auto.jsonl"的约定工作正常（本轮 60 行新增零缺陷）；建议在
   harvest 描述中补一句"不要重写/整理既有行"，防止未来追加时无意重排导致首现语义变化。
4. pools.json 无需修复。

## 四、复现

```bash
python3 evidence/verify-pools-backlog-consumed-20261011/reconcile_three_way.py \
  /Users/xzh/services/ai-development/multica-board-agent/glm-reserve/reserve <out_dir>
```

- 输入指纹（SHA256）：`inputs.sha256`；机器可读结果：`reconciliation.json`；校验脚本：`reconcile_three_way.py`。
- 复核全程只读 reserve/ 目录，未修改任何台账文件；本分支仅含 evidence 文件，不含产品代码改动，故不开上游 PR。
