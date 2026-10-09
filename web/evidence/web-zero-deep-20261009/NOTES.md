# web-zero-deep-20261009 — MemorySection / MemoryWorkbench 补测说明

## 来源

- 上游扫描证据：`web/evidence/web-test-gaps-20261007/summary.json` zero 清单第 193/194 项
  - `components/memory/MemorySection.tsx`（1547 行，component-logic，triage 分 1.596）
  - `components/memory/MemoryWorkbench.tsx`（639 行，component-logic）
- triage 证据：`web/evidence/web-zero-triage-20261008/triage.md` 将两项指派到本卡（AGEN-1188）。
- 去重边界：`lib/memory-graph.ts` 纯函数已由 `tests/lib/memory-graph.test.ts` 覆盖（另一卡），
  本卡只测 web 组件层，不重复。

## 产物

- `web/tests/memory/memory-section.smoke.spec.tsx`（22 个用例，jsdom + @testing-library/react，
  全部网络访问经 mock 的 `@/lib/api`，不触网、不启动服务器）。

### 文件名说明

卡面原写 `web/tests/memory/memory-section.smoke.test.tsx`。仓库 vitest 配置
（`web/vitest.config.mts`）的 include 只匹配 `tests/**/*.spec.ts(x)`；`.test.ts` 走
`npm run test:node`（tsc 编译 + node:test，无 jsdom，跑不了组件）。仓库现无任何
`.test.tsx`。为让测试真实被执行（验收要求 Vitest 通过），按仓库既有约定命名为
`memory-section.smoke.spec.tsx`，语义与卡面一致。

## 覆盖点清单

MemorySection（默认 L2 tab）：

1. 加载态：overview 未返回时显示 spinner，返回后显示 "Pick a document" 空态。
2. overview 请求失败 → 头部 toast 显示错误信息。
3. L1/L2/L3 TabStrip 渲染 + 默认 L2 文档列表 + 未选中空态。
4. overview 空 docs → 列表空态。
5. 选中 L2 文档 → GET doc → Markdown 渲染（entity ref 被 linkify）；Edit → textarea 回填 →
   修改 → Save → PUT `/api/memory/doc/L2/chat`（断言 URL/method/body）→ "Saved" toast →
   退出编辑 → 视图更新；overview 回源。
6. Update → POST `.../update` SSE 流解析：进度面板 "Update progress" 逐阶段渲染
   （stage/count），流结束后自动 GET doc + overview、面板清除（用可控的 hold/close 流验证）。
7. L3 preferences 文档：Update 按钮隐藏、显示偏好写入引导文案、Edit 可用。
8. L2 文档内 entity ref 链接点击 → 跳 L1 tab、surface 跟随、focusRef 生效
   （"Clear focus" 按钮、行高亮 scrollIntoView、行深链 href `/chat/sess-42`、
   pending "new" 徽标、"N pending" 提示）。
9. L1 surface pill 切换（notebook → chat）+ Snapshot/Changes 模式切换
   （pending 分组头、已提交行）+ Refresh 回调（POST refresh → "Refreshed: N changes" toast）。
10. Queries 模式仅 kb surface 可见；kb trace 查询列表渲染（kb_name + query）。
11. snapshot/changes 各自的空态文案。
12. v1 归档 banner：显示 → Dismiss → 跨重挂载保持隐藏（localStorage 持久化）。
13. `forcedTab` 锁定 TabStrip（不渲染）、`hideHeader` 跳过 SpaceSectionHeader、
    forcedTab 下 banner 不渲染。

MemoryWorkbench（L2/L3 hub）：

14. L2 导航栏、面包屑 "L2 · Per-surface summaries"、LayerSwitcher 链接
    （/memory/l1、/memory/l3）、MemoryRunPanel 收到 docKey。
15. `initialKey`（L3/scope）→ GET 对应 doc；面包屑 + 导航高亮。
16. 导航选择 → `router.replace("/memory/l2/<key>")` + 重新加载 doc/lines + RunPanel 更新。
17. Rendered / Line numbers 视图切换（行号、行文本）。
18. lines 为空时的行视图空态。
19. Edit raw → textarea 回填 → Cancel 丢弃（渲染视图恢复、无 PUT）→ 再次编辑 →
    Save PUT（断言 URL/method/body）→ "Saved" toast。
20. `prepareDocForRender` L2 回归断言：`<!--m_ULID-->` 注入 anchor span、
    `[^n]: chat:sess-42` → `/memory/l1?ref=...` 链接、`[^n]: m_ULID` → 同文档 `#m_ULID` 锚。
21. `prepareDocForRender` L3 回归断言：bare surface → `/memory/l2/<surface>`、
    `m_ULID` → `/memory/resolve?id=...`、非白名单词不 linkify。
22. `initialFocus` 深链 → 渲染后 scrollIntoView({block:"center"}) 定位并高亮。

## 运行方式与结果

```
cd web
npx vitest run tests/memory/memory-section.smoke.spec.tsx
# Test Files 1 passed, Tests 22 passed (约 4s；连续 3 次运行均稳定通过)
npx vitest run          # 全量回归：147 files / 675 tests 全部通过
npx eslint tests/memory/memory-section.smoke.spec.tsx   # 0 问题
npx tsc --noEmit -p tsconfig.json                        # 0 错误
```

## 观察到的行为（非缺陷，供后续参考）

- `linkifyEntityRefs` 的实体 id 字符类包含 `.`，句尾标点会被并入链接文本与锚点
  （如 `chat:sess-42.`）。组件源码注释表明 id 部分是有意宽松的，当前表现为外观问题，
  不影响本卡断言（测试夹具已绕开句尾紧邻标点的写法）。
- `runUpdate` 的 SSE 面板在流结束后立即被 `loadDoc` 清空：瞬时流用户看不到进度面板。
  本卡用 hold/close 流验证了面板渲染路径本身正常；是否需要"完成后保留"属产品决策。

## 边界确认

- 产品代码零改动（`git status` 仅新增测试与证据文件）。
- 未 merge、未部署、未改运行中的服务；工作在独立 worktree + 新分支
  `test/web-memory-section-smoke-20261009`（基于 origin/main v1.6.14，6cf793bd8）。
