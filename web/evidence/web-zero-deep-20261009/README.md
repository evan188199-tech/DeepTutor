# web-zero-deep-20261009 — MyAgents 区块与选择器补测

## 范围

针对 `scan/web-test-gaps-20261007` summary.json zero 清单中的两个文件补充
回归保护（零回归保护深位补测），产品代码零改动：

- `web/components/space/MyAgentsSection.tsx`（695 行，导入会话区块）
- `web/components/chat/MyAgentsPicker.tsx`（685 行，聊天引用选择器）

去重说明：`test-chat-workspace` 卡已覆盖 `ChatWorkspace`；本卡只测上述两个
MyAgents 组件。

## 产物

- `web/tests/chat/my-agents.smoke.spec.tsx`（18 个用例）
- 本说明文件

### 与卡面文件名的偏差

卡面产物名为 `my-agents.smoke.test.tsx`；仓库 vitest 配置
（`web/vitest.config.mts`）的 include 仅匹配 `tests/**/*.spec.ts(x)`，
`.test.tsx` 不会被收集执行。为满足"Vitest 通过"验收项，文件按仓库既有
惯例命名为 `my-agents.smoke.spec.tsx`（同目录 `ChatWorkspace.smoke.spec.tsx`、
`StandaloneComposer.smoke.spec.tsx` 一致）。

## 覆盖点清单

MyAgentsSection（space 区块）：

1. 空态渲染（"No agents yet"、唯一 Import 入口）并从空态打开导入向导，
   完成后触发 force 重载。
2. 真实归因分组渲染：agent 卡（来源/范围/会话数/未同步时间）与
   `ungrouped:codex` 兜底卡；默认选中第一张卡驱动会话列表。
3. 会话路由回调（setActiveSessionId + router.push）与搜索过滤
   （标题/最后消息、无命中清空）。
4. 会话删除确认分支：confirm 拒绝 → 不删除；confirm 接受 → 调
   deleteSession 并从列表移除。
5. 会话重命名回调（updateSessionTitle + 重载）。
6. agent 卡菜单：重命名（trim、Enter 提交 saveAgent、Escape 取消不保存）。
7. agent 卡菜单：Edit scope 打开 ScopeEditorModal（携带 agent 与 owned 数）。
8. agent 卡菜单：删除 agent（confirm 接受 → deleteAgent + 级联删除其会话 + 重载）。
9. 刷新失败分支（handle 权限被拒 → 失败提示，不触发扫描）。
10. 刷新成功链路：ensureReadPermission → scanDirectory → filterRefsByScope
    → parseSessions → importChatHistory → saveAgent(lastSyncAt 更新) →
    重载（force=true）→ "Added N new conversations" 提示。

MyAgentsPicker（聊天引用选择器）：

11. 加载失败恢复：列表接口 reject → 空文案 + 无 chips + Apply 禁用。
12. 分组与 chips：agent chip（含计数）、ungrouped 来源 chip；Claude Code
    按项目分组、Codex 按本地日分组（折叠/展开）；chip 过滤切换只保留
    归属行。
13. 搜索过滤：命中标题或最后消息、搜索时自动展开全部组、无命中空文案。
14. 选择分支：单行勾选/取消、组级 TriCheck 全选、Clear 清空、Apply 按钮禁用态。
15. 确认回调（onApply）：按选中 id 映射标题（后端哨兵 "New conversation"
    映射为本地化 "New chat"）、调用后 onClose；重开后瞬态选择被重置。
16. 预览链路：getSession 拉取消息、system 消息过滤、预览内 Select/Selected
    切换、Back 返回列表。
17. 预览失败分支：getSession reject → "no readable messages" 文案。
18. 关闭态不发起任何请求。

## 实现方式

- 只 mock API 边界（`@/lib/imports-api`、`@/lib/session-api`、
  `@/lib/chat-import/agent-store`、`@/lib/chat-import` 的文件系统函数）与
  重组件叶子（`SessionList`、`ImportWizard`、`ScopeEditorModal`、
  `PickerShell`）。
- 分组/归因逻辑（`readImportMeta`、`assignSessionsToAgents`、
  `filterRefsByScope`）与 i18n、时间/标题工具全部走真实实现。
- jsdom 环境，遵循仓库既有 rendered setup（`tests/setup/rendered.ts`）。

## 运行与结果

```bash
cd web && npx vitest run tests/chat/my-agents.smoke.spec.tsx
# Test Files 1 passed, Tests 18 passed

cd web && npx vitest run
# Test Files 147 passed, Tests 671 passed（含本文件，无回归）

npx eslint tests/chat/my-agents.smoke.spec.tsx   # 0 findings
npx tsc --noEmit -p tsconfig.json                # exit 0
```

## 发现的缺陷

未发现需要立修复卡的功能缺陷。一条低置信度观察（不立卡）：
`MyAgentsPicker` 的 agent chip 由相邻 inline span 组成（名称 + 计数），
jsdom 的可访问名计算会将两者拼接为无空格文本（如 "Refactor crew2"）；
真实浏览器的表现可能不同，若需要可另行用浏览器辅助功能树核实。

## 复测说明

基线：origin/main `6cf793bd8`（release: v1.6.14）。测试命令均需在 `web/`
目录执行；测试不依赖网络与 IndexedDB（agent-store 已在边界 mock）。
