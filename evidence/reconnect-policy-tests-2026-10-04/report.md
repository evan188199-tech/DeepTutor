# 聊天重连阶梯与提交门控时序补测（AGEN-384）

基线：`origin/main` @ `ef2d9e5c3`（v1.6.12）。分支 `test/reconnect-policy-timing`。
只新增测试与证据，未改任何产品代码。

## 背景契约（上游 #1648 / PR #1668）

- 重连阶梯：`web/features/chat/transport/reconnect-policy.ts` — `reconnectDelay(attempt) = min(8000, 250 * 2**attempt) * jitter(0.8..1.2)`，单级最坏 `8000 × 1.2 = 9600ms`。
- 提交门控：四个复制粘贴的调用点（QuizFollowupContext.tsx:393、ChatStateAdapter.tsx:2245、BookChatPanel.tsx:283、whisper/page.tsx:192）都是 `attempt >= 10` × `setTimeout 200ms` = 2s 预算。
- 缺陷：2s 提交预算 < 单级重连最坏 9.6s；重连落在第 3/4 级（累计 ~3750/7750ms）时 Submit 必然假失败并谎报 "question is no longer active"。

## 交付

- `web/tests/chat/transport/reconnect-policy.test.ts`（node:test，7 个用例，随 `npm run test:node` 运行）
- 测试通过解析四个调用点的门控常量（数值字面量或共享常量名，均可识别）取得真实参数，用 `reconnectDelay` 真函数做时间线模拟，因此：
  - 在当前 main 上按预期 FAIL（锁定缺陷）；
  - PR #1668 式修复（`web/lib/send-retry.ts` 导出 60×200ms 并替换四处门控）落地后自动转绿，已用合成源验证解析器可识别该形态（60×200=12000ms ≥ 9600ms）。修复卡可直接领取。

## 用例清单与 main 上的实际结果

| # | 用例 | 覆盖路径 | main 结果 |
|---|------|----------|-----------|
| 1 | reconnect ladder grows exponentially from 250ms and caps at 8s | 阶梯参数契约（250→8000 封顶） | PASS |
| 2 | reconnect jitter stays within 0.8x..1.2x | 抖动边界，最坏单级 9600ms | PASS |
| 3 | shouldReconnect keeps the ladder alive... | 活跃 turn 持续重连 / 空闲 5 次上限 | PASS |
| 4 | all four submit gates share one retry budget | 四处门控预算一致、无漂移 | PASS |
| 5 | submit gate give-up is bounded and reports a user-facing failure | 等待耗尽报错路径 + 预算有界 | PASS |
| 6 | submit retry budget covers the worst-case reconnect rung | 阶梯/门控参数不匹配即失败 | **FAIL（预期）** |
| 7 | a submit issued mid-reconnect is delivered anywhere on the ladder | 门控在重连窗口内等到连接即放行 | **FAIL（预期）** |

- 全量 `npm run test:node`：1241 tests，1239 pass，2 fail —— 仅上述 #6/#7 两个预期失败，无附带破坏。
- `npm run typecheck` 通过；`eslint tests/chat/transport/reconnect-policy.test.ts` 无告警。

## #7 在 main 上的失败语义（与 #1648 时序表一致）

门控最后一次轮询在 `(10-1)×200 = 1800ms`；阶梯累计重连时刻 250/750/1750/3750/7750ms。
第 3 级（3750ms）与第 4 级（7750ms）超出窗口 → 假失败。修复后（12s 预算）全部放行。

## 复现

```bash
cd web
npm run test:node   # 或单跑: node dist/node-tests/tests/chat/transport/reconnect-policy.test.js
```
（需先 `./node_modules/typescript/bin/tsc -p tsconfig.node-tests.json` 或直接 `npm run test:node`）

## 验收对照

1. 三条覆盖路径齐备：窗口内放行（#7）、等待耗尽报错（#5）、参数不匹配即失败（#6，main 上红）。
2. 断言与夹具齐备（真实常量解析 + 真实 `reconnectDelay` 模拟），修复卡可直接领取：把四处门控预算提到 ≥ 9600ms（如 #1668 的 60×200ms）即全绿。
3. 未改任何产品代码。
