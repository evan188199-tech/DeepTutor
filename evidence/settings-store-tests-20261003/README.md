# settings store 持久化与归一化补测证据（2026-10-03）

卡：AGEN-148（test: 前端设置 store 持久化与归一化补测）
基线：`origin/main` @ `ef2d9e5c3`（release: v1.6.12），与 coverage-2026-10-02 审计基线一致。
分支：`myfork/test/settings-store-20261003`（worktree：`/Users/Shared/DeepTutor-worktrees/agen148-settings-store`）

## 交付物

- `web/tests/settings/settings-store.test.ts` — 27 个 node:test 用例，覆盖审计缺口 12（`web/features/settings/store/SettingsStore.tsx` 354 缺失 / 52.2%）。

## 覆盖范围（对应验收 1、2）

1. **patch 后本地存储与 store 同步**（`syncLoadedCodeBlockSettingsToAppShell` / `persistUiSettingsPatch`）：
   - 合法 patch 后三个 code-block 值（theme / 行号 / 换行）写入 app-shell localStorage，返回值与存储读回一致，raw key 持有规范化的字符串值；
   - 每次写入广播 `CODE_BLOCK_SETTINGS_EVENT`（3 次，detail 字段逐一断言）；
   - 后端值覆盖本地陈旧值（预置旧 localStorage，断言后端值胜出并落盘）；
   - `persistUiSettingsPatch` 请求形状：`PUT /api/settings/ui?dt_workspace=`、`Content-Type: application/json`、body 与 patch 逐字段相等（单字段与 6 字段全量各一例）；
   - fetcher 抛错时原样向上传播（`assert.rejects`），不吞错。
2. **非法值归一化不抛错**：
   - 空 patch → 默认值（oneDark / false / false）；
   - theme 为 `null` / `undefined` / `""` / 纯空白 → 默认主题；合法主题两侧空白被 trim；
   - 开关 `"True"` / `"TRUE"` 大小写不敏感识别为 true；显式布尔 `false` 保持 false（绝不被翻转为 true）；
   - 垃圾值矩阵（`undefined`/`null`/`0`/`1`/`"false"`/`"False"`/`"yes"`/`"on"`/`"1"`/`{}`/`[]`）全部归一化为 false 且不抛错；
   - `String()` 强转后为 `"true"` 的值（`["true"]`、覆写 `toString` 的对象）按现状契约归一化为 true（行为已用专门用例锁定）；
   - 全垃圾 patch 后「规范化值 = 落盘值 = 读回值」三方一致（存储永不与 store 脱节）；
   - `window` 缺失（SSR）时 sync 是无害 no-op 而非崩溃。
3. **常量与纯函数完整性**：
   - `TOUR_STEPS`：7 步、字段齐全、路由唯一且全部位于 `/settings/` 下、顺序锁定（status→appearance→network→llm→knowledge→starters→memory）；
   - `RESPONSE_LANGUAGE_OPTIONS`：15 项、值唯一且都通过 `isResponseLanguage`、label 非空、`en` 居首；
   - `defaultCatalog`：8 个 service bucket 形状正确、每次调用返回全新实例（变异隔离）；
   - `cloneCatalog` 深拷贝隔离（克隆上的嵌套变异不回渗源对象）；
   - `voiceService` / `generationService` 真值表；
   - `getActiveProfile` / `getActiveModel` 活跃选中→首个兜底→null 兜底链、search 无 model；
   - `serviceConfigured`（llm 需要 model id、search 需要 provider）；
   - `currentDiagnosticsResult` 仅匹配当前 profile/model（含 search 的 null modelId 匹配、陈旧结果判 null）；
   - `serviceReadiness` 四态矩阵（not_configured / untested / passed / failed，陈旧失败不判 failed）；
   - `servicePendingApply` 逐 service 比较（改动只污染目标 bucket）。

夹具：`makeCatalog()`（llm 双模型 + search provider 的最小 Catalog）、`recordingFetcher()`（请求捕获）、可重置的 `window`/localStorage/sessionStorage/dispatchEvent mock（与 `tests/settings-context-ui-sync.test.ts` 同一模式）。

## 文件名说明（`.test.ts` 而非卡面 `.test.tsx`）

`tsconfig.node-tests.json` 的 include 只有 `tests/**/*.ts`（无 tsx），vitest 只收 `tests/**/*.spec.ts(x)` —— `.test.tsx` 在两个运行器下都不会被执行。本文件只测 store 的导出函数（无 JSX 渲染），走 `test:node`（tsc 编译 + node:test + 手工 window mock），与同目录既有设置测试（`settings-context-ui-sync.test.ts`、`settings-context-boolean-hydration.test.ts`）约定一致。

## 运行结果（跑通：PASS）

命令（在 `web/` 下）：

```
npm run test:node
```

数字：

- 本测试文件单独跑：`node -r ./scripts/register-node-test-aliases.cjs --test dist/node-tests/tests/settings/settings-store.test.js` → **27 tests / 27 pass / 0 fail**
- 全量 node 套件（含本文件）：**1261 tests / 1261 pass / 0 fail**（基线 1234 + 新增 27，无回归）
- `npm run typecheck` → 通过
- `npx eslint tests/settings/settings-store.test.ts` → 0 问题
- `npx prettier --check tests/settings/settings-store.test.ts` → 通过

## 说明与备注

- 27 例在当前 `origin/main` 上全部通过：未发现存量缺陷，无待修复缺口；本测试集的价值是把持久化/归一化契约钉死为回归网，任何破坏「patch 后存储同步」或「非法值归一化抛错」的改动会直接红。
- 产品代码零改动（验收 3）：`git diff origin/main --stat` 仅含测试文件 + 本证据目录。
- 两个行为按现状锁定并注释说明（如需改变属产品决策，不属于修复卡）：①开关归一化只认布尔 `true` 或字符串 `"true"`（大小写不敏感），数字 `1`、`"yes"`、`"on"` 一律视为 false；②空 patch 会把开关强制写为 `false`（后端缺字段时覆盖本地 true 的语义与既有「后端值胜出」测试一致）。
- Provider 组件主体（React 渲染路径）未在 node:test 覆盖：需要 jsdom/React Testing Library（vitest `.spec.tsx` 通道），超出本卡验收范围；纯导出函数已全分支断言。
