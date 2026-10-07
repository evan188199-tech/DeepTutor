# web 前端测试空白静态清点（scan/web-test-gaps）

- 日期：2026-10-07
- 基线：`origin/main` @ `f07029cfcf2c8dfccdb671cdfc343db8334f5741`（release: v1.6.13）
- 分支：`scan/web-test-gaps-20261007`（新 worktree，未触碰 main 工作区）
- 范围：`web/`，排除 `node_modules` / `dist` / `.next` / `vendor` / `contracts/generated` / `*.d.ts` / `tests/setup`
- 方法：纯静态文件级映射，不运行任何测试套件；不修改任何产品与测试代码

## 一、测试体系（静态事实）

| 运行器 | 命令 | 文件规则 | 出处 |
| --- | --- | --- | --- |
| vitest（jsdom 单测） | `npm run test:unit` | `tests/**/*.spec.ts(x)` | `web/vitest.config.mts:19` |
| node 测试 | `npm run test:node` | `tests/**/*.test.ts`（tsc 编译后 `node --test`） | `web/scripts/run-node-tests.mjs`、`tsconfig.node-tests.json` |
| playwright（e2e/audit） | `npm run audit`、`test:e2e:*` | `tests/**/*.audit.ts` | `web/playwright.config.ts` |

测试语料共 346 个文件：node 210、vitest 123、playwright 13。全部位于 `web/tests/`。

## 二、映射与分级规则（可复跑、同输入同结果）

对每个源码文件：

1. **path 引用**：任一测试文件文本包含其 web 根相对 POSIX 路径（去扩展名，兼容 `@/...`、`../...` 与动态 import）；`index.ts(x)` 按所在目录路径匹配。
2. **basename 引用**：词边界匹配文件名（通用名 `index/page/layout/route/...` 跳过，避免误报）。
3. **meta 测试**（结构性检查、读源码文本而非行为验证，引用不计入 covered）：`architecture-contracts`、`no-page-module-imports`、`no-unified-chat-context`、`no-v1-chat-surface`、`internal-route-contract`、`generated-contracts`、`design-token-parity`、`tooling-config`、`i18n-audit`、`i18n-placeholders`。`route-params.test.ts` 行为性导入 `../lib/route-params`，不列入 meta。
4. **barrel 传递**：零引用且 actionable 的文件，若被同目录树最近的 covered `index.ts(x)` barrel 再导出，升为 weak（标注“仅经 barrel 间接可达”）。

分级：
- **covered**（445）：至少一个非 meta 的 vitest/node 测试按路径引用；
- **weak**（73）：有引用但无非 meta 单测路径引用（仅 playwright audit、仅 meta、仅 basename、或仅 barrel 间接可达）；
- **zero**（368）：任何测试文件均无引用且无 covered barrel 传递。

## 三、总量

| 状态 | 数量 | 说明 |
| --- | --- | --- |
| covered | 445 | 50.2% |
| weak | 73 | 8.2% |
| zero | 368 | 41.5% |
| 源码文件 | 886 | 12 个目录 + 根级 |
| actionable（可补测的 zero+weak） | 435 | 排除 config/eslint/types 等工具文件 |

按目录分布（covered / weak / zero）：

| 目录 | covered | weak | zero |
| --- | --- | --- | --- |
| app | 27 | 0 | 81 |
| components | 151 | 24 | 205 |
| context | 4 | 0 | 2 |
| contracts | 2 | 0 | 0 |
| features | 57 | 19 | 26 |
| hooks | 20 | 0 | 16 |
| i18n | 3 | 2 | 2 |
| lib | 164 | 7 | 33 |
| scripts | 4 | 2 | 6 |
| shared | 10 | 12 | 3 |

`app/` 81 个 zero 基本是 Next.js 页面/布局/路由壳，主要依赖 e2e 与集成测试路径，静态单测价值低；`lib/` 33 个 zero 与 `hooks/` 16 个 zero 是逻辑密集、最值得补测的部分。

## 四、Top10 候选（zero，按“逻辑密度 × 可单测性”排序）

| # | 文件 | 行数 | 判定依据 |
| --- | --- | --- | --- |
| 1 | `lib/memory-graph.ts` | 762 | 无任何测试引用（grep 复核 0 命中）；最大无测模块 |
| 2 | `lib/code-languages.ts` | 180 | 无任何测试引用；语言映射纯逻辑，易测 |
| 3 | `lib/latex-commands.ts` | 172 | 无任何测试引用；命令表/转换纯逻辑 |
| 4 | `context/QuizFollowupContext.tsx` | 647 | 无任何测试引用；大型 context 状态机 |
| 5 | `lib/quiz-judge.ts` | 157 | 无任何测试引用；判分逻辑 |
| 6 | `lib/personas-api.ts` | 128 | 无任何测试引用；API 客户端 |
| 7 | `lib/research-types.ts` | 125 | 无任何测试引用；类型/守卫逻辑 |
| 8 | `hooks/useDragSort.ts` | 404 | 无任何测试引用；最大无测 hook |
| 9 | `lib/session-unread.ts` | 92 | 无任何测试引用；未读状态计算 |
| 10 | `lib/youtube-iframe-api.ts` | 80 | 无任何测试引用；播放器封装 |

weak 侧值得关注的还有：`lib/chat-import/claude-code.ts`（173L，仅经 covered barrel 间接可达，单测断言只覆盖 chatgpt/codex 路径）、`shared/ui/*` 原语（仅 basename 或 barrel 提及，缺直接路径引用的行为测试）、`features/multi-user/api.ts` 等仅被大量 basename 提及。

## 五、去重说明

- coverage-gaps 系列仅覆盖 backend `deeptutor/`，本卡为 `web/` 前端静态轴，无重叠；
- scan-flaky-tests、scan-test-isolation 是运行时轴（需运行测试），本卡不运行测试，互补无重叠；
- 本卡未开上游 PR（纯清点证据，非上游贡献物），分支仅推 `myfork`。

## 六、局限

1. 静态映射 ≠ 运行时覆盖率：covered 只代表“测试文件按路径引用过”，不代表分支覆盖充分；weak/zero 是补测候选的下界方向。
2. barrel 间接可达只查最近一层 `index.ts(x)`；更深的传递导入仍可能判 zero（保守方向，宁可多报）。
3. basename 匹配可能把“测试里碰巧提到同名词”算作 weak 引用（只影响 weak，不影响 zero/covered 判定）。
4. meta 测试清单为人工指定的结构性检查集合，已逐个核对导入方式（见第二节）。

## 七、复跑

```bash
cd <worktree>/web
python3 evidence/web-test-gaps-20261007/scan_web_test_gaps.py
# 输出 evidence/web-test-gaps-20261007/summary.json，同输入字节级一致
```

产物：`summary.json`（zero/weak 全量清单 + basis + Top10）、本报告、`SHA256SUMS`、扫描脚本。无任何产品/测试代码改动。
