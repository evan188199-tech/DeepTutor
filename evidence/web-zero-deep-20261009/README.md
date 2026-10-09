# web-zero-deep-20261009 — McpCatalogBrowser 补测

## 背景

- 来源：myfork 分支 `scan/web-test-gaps-20261007` 的
  `web/evidence/web-test-gaps-20261007/summary.json` zero 清单第 181 项
  `components/mcp/McpCatalogBrowser.tsx`（760 行，零测试引用）。
- 本卡在 `web/tests/mcp/mcp-catalog-browser.smoke.spec.tsx` 为该组件补上
  回归保护，**未改动任何产品代码**（`git diff origin/main` 只含本测试与本说明）。

## 与既有卡的去重

- `test-space-mcp-router` / `test-mcp-settings-router`：后端路由契约，不覆盖本组件。
- `guide-mcp`：导读文档。
- 本卡只测 `McpCatalogBrowser.tsx` 组件本身；API 全部 mock
  （`getMcpCatalog` / `installMcpCatalogEntry` / `testSpaceMcpServer`），
  `mcp-store.ts` 的纯逻辑（`describeMcpError`、`appendCatalogPage`、
  `missingRequiredFields` 等）用真实实现参与断言。

## 文件名说明

卡面写的 `mcp-catalog-browser.smoke.test.tsx` 不会被任何测试管线收集：
vitest（`web/vitest.config.mts`）只匹配 `tests/**/*.spec.tsx`，
node 测试管线（`tsconfig.node-tests.json`）只编译 `tests/**/*.ts`。
故实际落盘为 `mcp-catalog-browser.smoke.spec.tsx`（保留 smoke 标记），
位于 `npx vitest run` 的收集范围内。

## 覆盖点（16 用例，全部通过）

目录加载：
1. 首页拉取参数（basePath=/api/space/mcp，q/category/tier 空，limit=12）、
   卡片渲染、`{{shown}} of {{total}}` 计数、类别 chip 计数、无 cursor 时不出现 Load more。
2. 请求在途时渲染加载指示（spinner），不渲染卡片。
3. 请求失败渲染错误横幅（describeMcpError 的 Error message 分支）。
4. 空目录 + 无过滤条件 → "The store is empty" 文案。
5. 搜索无匹配 + 过滤条件生效 → "No services match this filter." 文案（两种空态互斥）。

搜索过滤：
6. 输入不逐键请求；250ms 防抖后以 trim 后的 q 重新拉取。
7. 类别 chip 与档位 chip 触发带 category/tier 的重新拉取；档位 chip 再点一次清除。

分页：
8. Load more 带 cursor 请求、按 id 去重合并两页、计数更新、cursor 耗尽后按钮消失。

已安装标记：
9. 按 `catalog_entry` 溯源判定已安装；无溯源的历史安装按 entry id 名判定；未安装不显示标记。
10. servers 列表尚未加载（null）时回退目录页自带的 `installed_as`。

详情展开：
11. 点卡片进详情（标题/文档链接/Install 按钮），Back 返回网格。
12. 必填凭据未填时 Install 禁用并提示 "Fill in {{fields}} to continue"；密钥字段渲染为 password 输入；填齐后可安装。

安装入口分支：
13. 安装成功：以所选名称 + 剔除空白可选值后的 secrets 调 install API；
    向父级回传 McpStoreState；随后自动用返回的 config 探测连接并显示
    "Connected — {{count}} tools detected"。
14. 安装失败：显示错误、不回传父级、不触发探测。
15. atCapacity 时新安装被禁用并显示额度提示。
16. atCapacity 时对已安装条目仍允许：名称框预填已安装名、Test connection 可用
    （失败显示 "Connection failed."）、Reinstall 以同名替换提交（secrets 为空对象）。

## 运行与结果

```
cd web
npx vitest run tests/mcp/mcp-catalog-browser.smoke.spec.tsx
#   Test Files  1 passed (1)
#   Tests       16 passed (16)

npx vitest run            # 全量单元测试，确认无相互影响
#   Test Files  147 passed (147)
#   Tests       669 passed (669)

npx tsc --noEmit -p tsconfig.json      # 退出码 0
npx eslint tests/mcp/mcp-catalog-browser.smoke.spec.tsx   # 无告警
npx prettier --check tests/mcp/mcp-catalog-browser.smoke.spec.tsx  # 通过
```

## 观察（非缺陷，不阻塞）

- 详情页的 "Install as" 与凭据字段 `<label>` 未通过 htmlFor/嵌套与对应
  `<input>` 关联（McpCatalogBrowser.tsx:584-593、595-619），屏幕阅读器读不到
  字段名；测试因此用 placeholder 定位输入框。如需改进可立一张可访问性小卡。
