# AGEN-1777 日志与 turn_events 敏感载荷写点清点（中性清单）

- 基线：origin/main @ `6cf793bd868ba5ecbe64722936d4be8fab5a01df`（v1.6.14）
- 方法：AST 静态扫描 + 人工复核，只读，未运行任何服务，未修改源码
- 范围：`deeptutor/logging/`、`deeptutor/services/`、`deeptutor/api/`、`deeptutor/agents/`（另覆盖 turn_events 生产者所在的 `partners/`、`app/`）
- 落盘路径确认：`deeptutor/logging/configure.py:65-80` 默认开启文件 sink（RotatingFileHandler，`data/user/logs/deeptutor.jsonl`，JsonlFormatter 序列化完整 message + exception 文本）；`deeptutor/logging/formatters.py:29-39`

## 分类与建议级别定义

| 类别 | 含义 |
| --- | --- |
| 凭据/密钥-候选 | 插值表达式可能携带密钥、令牌、账号口令或含凭据的 URL |
| 用户内容-候选 | 插值表达式可能携带用户消息、查询、回答、学习者数据等明文 |
| 内网地址-候选 | 插值表达式可能携带内部主机名/IP/端点 |
| 异常文本载体 | `{exc}` / `exc_info` 原文落盘，异常消息可间接携带上述任意一类 |
| turn-events 用户内容 | turn_events `content` / `metadata_json` 持久化的用户内容生产点 |
| turn-events 异常/错误文本 | 持久化错误文本的生产点 |

建议级别：高 = 建议直接脱敏/截断后写日志；中 = 建议加集中式清洗或按需收敛（配置、级别、开关）；低 = 建议复核确认即可。

## 汇总数字

- 扫描日志调用总数：884（services/api/agents/logging 四域，195 个文件）
- 机器初筛候选：310 行；人工复核后高信号清单见 `log-write-points.md`（28 行）与 `turn-events-write-points.md`（12 组）
- 异常文本载体：270 处，分布 87 个文件（逐行清单见 `machine-scan-full.csv`，类别 `exc`）
- 凭据/密钥类直接插值：0 处确认（所有 `*_tokens` 命中均为 token 计数，已排除）
- 文件：`log-write-points.md`、`turn-events-write-points.md`、`machine-scan-full.csv`

## 文件清单

1. `log-write-points.md` — 日志调用面高信号写点（仅 文件:行 / 类别 / 级别 / 建议 / 中性依据）
2. `turn-events-write-points.md` — turn_events 持久化点与元数据生产点
3. `machine-scan-full.csv` — 全量机器初筛行（含 270 行异常载体逐行坐标），列：file,line,domain,level,category,basis,kind

本清单为静态候选清点，不含任何运行时样本值、载荷或复现步骤；确认与修复由人决定。
