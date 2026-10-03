# memory-graph 纯函数补测证据（2026-10-03）

卡：AGEN-146（test: 前端 memory-graph 纯函数补测）
基线：`origin/main` @ `ef2d9e5c3`（release: v1.6.12），与 coverage-2026-10-02 审计基线一致。
分支：`myfork/test/memory-graph-20261003`（worktree：`/Users/Shared/DeepTutor-worktrees/agen146-memory-graph`）

## 交付物

- `web/tests/lib/memory-graph.test.ts` — 30 个 node:test 用例，覆盖审计缺口 10（`web/lib/memory-graph.ts` 314 缺失 / 0%）。

## 覆盖范围（对应验收 1）

1. `parseDoc` 空/畸形输入：空串、纯空白、无 bullet 散文、后续 H1 忽略、畸形 bullet 行跳过（非法 marker / 截断注释 / h4）、CRLF 行尾、空 footnote payload、未知 label 存根、legacy bullet 无 footnote 丢弃、多 marker 去重、footnote 后置解析、逗号分隔 legacy refs。
2. `splitRef` 非法 ref：无冒号、空串、前导冒号（surface 空）、尾随冒号（entityId 空）、多冒号保留在 entityId。
3. `buildGraph` 空 slots：全空快照产出 17 个 cluster（3 L3 + 7×2 L1/L2）、7 个隐藏锚点（r=0）、0 边、空 adjacency、空 slice 仍可标注（角度为正）。
4. `buildGraph` 跨 surface 引用：L2(notebook)→L1(chat) strong 边；L3(profile)→`L2:chat:__anchor__` soft 边；L3→具体 `chat:m_xxx` L2 条目 strong 边；重复 surface 引用只画一条 soft 边；非法 ref（纯 surface、未知 surface、不存在实体/条目）不产边不抛错；L1/L2 同 surface 重复 id 去重；自定义布局中心生效；节点唯一性 / 坐标有界 / adjacency 对称 / nodeCluster 一致性。

夹具通过真实 `parseDoc` 生成 L2/L3 文档（与 consolidator 实际 markdown 形状一致），entry ULID 符合 ENTRY_ID 的 Crockford base32 字符集。

## 运行结果（跑通：PASS）

命令（在 `web/` 下）：

```
npm run test:node
```

数字：

- 本测试文件单独跑：`node -r ./scripts/register-node-test-aliases.cjs --test dist/node-tests/tests/lib/memory-graph.test.js` → **30 tests / 30 pass / 0 fail**
- 全量 node 套件（含本文件）：**1264 tests / 1264 pass / 0 fail**（基线 1234 + 新增 30，无回归）
- `npm run typecheck` → 通过
- `npx eslint tests/lib/memory-graph.test.ts` → 0 问题；`npx prettier --check` → 通过

## 说明与备注

- 测试文件用 `.test.ts` 而非审计建议的 `.spec.ts`：本仓库 vitest 只收 `tests/**/*.spec.ts`（jsdom/React 渲染用），纯函数单测走 `test:node`（tsc 编译 + node:test），与 `tests/` 下既有纯函数测试（如 `trace-memory.test.ts`）约定一致。
- `web/lib/memory-graph.ts` 顶部 import `@/lib/api`（仅供 `fetchMemorySnapshot` 使用）；纯函数测试不触碰网络，import 链在 node 环境无副作用（`workspace-scope`/`return-url` 均有 `typeof window` 守卫），无需 mock。
- 本地未产出覆盖率百分比：`@vitest/coverage-v8` 未安装，补装需改 `package.json`（违反"不改产品代码"约束）。测试文件 30 例对三个纯函数为全分支级断言。
- 发现记录（非阻塞）：`parseDoc` 对空 footnote payload（`[^1]:` 无内容）的行为是"丢弃 marker"而非"保留存根"，与 unknown label 存根策略不同但与 legacy 路径一致，测试已按现状断言并注释说明；如需改为存根属产品决策。
- 未改任何产品代码；`git diff ef2d9e5c3..HEAD` 仅含 `web/tests/lib/memory-graph.test.ts` 与本证据目录。
