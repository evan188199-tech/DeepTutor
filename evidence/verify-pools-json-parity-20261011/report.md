# pools.json 与 backlog 卡池漂移复核（2026-10-11）

- 复核对象（只读）：`/Users/xzh/services/ai-development/multica-board-agent/glm-reserve/reserve`
- 口径：与 `multica_board_agent/reserve.py` 加载语义一致（首现 key 生效；executor 须在池 agents 内；
  `backlog/<pool>.consumed` 为核销台账）。

## 汇总

| 项 | 数值 |
|---|---|
| 声明池 | deeptour（共 1 个） |
| backlog 文件 | 4 个：deeptour.0priority.jsonl, deeptour.auto.jsonl, deeptour.consumed, deeptour.jsonl |
| 候选数据行 | 1076 |
| 唯一键 | 1076 |
| 重复键 | 0 个 key，多余出现 0 行 |
| 无法加载行 | 0 |
| 游离文件（无池声明） | 0 |
| executor 未声明（被静默过滤） | 0 键 |
| 声明缺失项 | 0 |

双向守恒校验：唯一键 1076 + 重复多余 0 + 非法行 0 = 1076，== 数据行 1076（通过）。

## 分类一：jsonl 有而 pools 无

- 无：全部文件均归属于声明池（`deeptour.jsonl`、`deeptour.*.jsonl`、`deeptour.consumed`）。

- 无：全部唯一键的 executor ∈ {GLM 5.3, GLM 5.3 Flash}。

- 无。

## 分类二：pools 声明而文件缺失

- 无：池 `deeptour` 的基础文件 `deeptour.jsonl`、harvest 追加目标 `deeptour.auto.jsonl`、
  核销台账 `deeptour.consumed` 均存在；`capacity`/`harvest.executor` 均已声明在 agents 内。

## 分类三：重复键

- 无：全部键唯一（同文件与跨文件均无重复）。

## 补充交叉引用（不计入三类，细节归属其他轴）

- consumed∩jsonl 残留键：5 个（deeptour.consumed: guide-mastery, guide-reading, up-1646, up-1647, up-1678）——深入核对归属 verify-claims-ledger（键一致性轴）。
- after 依赖指向不存在键：0 个。
- executor 分布：GLM 5.3×289、GLM 5.3 Flash×787。
- 修正建议汇总：三类漂移均为零，无需修正；唯一需人工留意的是 consumed 残留键（5 个，交由键一致性轴处理）。

## 复现

```bash
python3 evidence/verify-pools-json-parity-20261011/verify_pools_json_parity.py \
  /Users/xzh/services/ai-development/multica-board-agent/glm-reserve/reserve <out_dir>
```

输入快照指纹（SHA256，见 inputs.sha256）：复核时点 pools.json 与 backlog/* 原样，未做任何修改。
