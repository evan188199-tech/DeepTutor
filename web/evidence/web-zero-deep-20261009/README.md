# web-zero-deep-20261009 — SidebarNav 与 SessionActivityPanel 补测说明

## 范围与来源

零覆盖清单取自 `myfork` 分支 `scan/web-test-gaps-20261007` 的
`web/evidence/web-test-gaps-20261007/summary.json`（`zero` 列表共 368 项，
`zero-entries.json` 摘录本卡涉及的两条）。基线为 origin/main `6cf793bd8`
（release v1.6.14），只新增测试与证据文件，未改动任何产品代码。

| 组件 | 行数 | 新测试文件 |
| --- | --- | --- |
| `components/sidebar/SidebarNav.tsx`（含 `SidebarHome`） | 720 | `tests/sidebar/sidebar-activity.smoke.spec.tsx` |
| `components/chat/home/SessionActivityPanel.tsx`（`ActivityBody`） | 571 | 同上（第二组用例） |

重叠说明：`lib/session-activity.ts` 的数据折算已由 `tests/session-activity.test.ts`
覆盖（node 套件），本卡只在用例 27 通过面板的 re-export 验证装配关系，不重复断言折算规则；
状态展示面导读卡（guide-web-activity）关注使用方式，重叠处以引用为准。

## 文件名适配

卡面写的 `web/tests/sidebar/sidebar-activity.smoke.test.tsx` 在本仓库不会被执行：
`vitest.config.mts` 的 include 只有 `tests/**/*.spec.ts(x)`，node 套件
（`tsconfig.node-tests.json`）只编译 `tests/**/*.ts`。按仓库既有约定落为
`web/tests/sidebar/sidebar-activity.smoke.spec.tsx`。可立一张小改进卡：统一渲染测试后缀或扩展 vitest include，避免 `.test.tsx` 被静默忽略。

## 覆盖点清单

SidebarNav（展开态 + 图标栏 + SidebarHome）：

1. 出厂布局渲染：可见 4 行 + More 组计数徽标（aria-expanded、计数 aria-hidden 状态切换）
2. 高亮分支：精确路径与子路径（`startsWith(href + "/")`）都点亮 accent，非激活行不着色
3. More 展开/收起：折进行显现、计数徽标隐藏、`deeptutor.sidebar.moreExpanded` 持久化且重挂载后恢复
4. 行菜单 "Move to More"：折入后布局写回 localStorage（order 保持、collapsed 追加）、计数变 3、菜单关闭
5. 行菜单 "Move out of More"：回到保存位置、组清空后 More 组整体消失、菜单关闭
6. "Reset sidebar order"：仅 customized 时出现，点击后恢复出厂 order/collapsed
7. 菜单关闭分支：Escape 与外部按下（mousedown）都关闭
8. 能力锁：缺 `llm` 能力的行渲染为 `aria-disabled` 非链接 + 锁提示 aria-label，Arrange 按钮保留
9. 学习策略可见性：`allowedSurfaces` 过滤模块行（无 surfaces 的条目隐藏），More 组随之消失
10. 键盘重排（Alt+ArrowDown）：顺序持久化、首行易主
11. 图标栏（collapsed rail）：仅图标行、More 溢出按钮（aria-haspopup/aria-expanded）、portal 菜单含折进项、菜单项走 `onNavigate`、二次点击关闭
12. 无折进项时隐藏溢出按钮；栏内锁定行渲染
13. `SidebarHome`：默认高亮 + `onHomeClick`；策略无 `chat` 面时返回 null；能力锁定；collapsed 变体

SessionActivityPanel / ActivityBody：

14. 空态：仅引导文案，无分区卡
15. 空态 + `configSection`：引导消失、配置区保留
16. 工具与知识库分区：名称、`×N` 计数映射
17. Space 六类子分区（会话/书/笔记本/题库/人格/记忆）：分类链接 href、计数、未打开时不发标题请求、id 原样显示 + `slice(0,8)` 副标题、页数插值、`Question #n`
18. 打开时懒加载标题：`listSessions(200)`、`listNotebooks`、`bookApi.list` 各调一次，标题替换 id
19. 标题接口失败：回退原始 id，不崩溃（错误被吞掉的约定行为）
20. 生成文件与上传附件分区分离；点击行回调 `onOpenAttachment` 且参数正确；生成文件显示大小（`TXT · 2.0 KB`）与磁盘路径 tooltip（sr-only 文本）；无文件名回退 `untitled`
21. 面板 re-export 的 `buildSessionActivity` 能从消息流（tool_call、requestSnapshot、generated 附件）折出完整活动并渲染

## 观察与发现

- Rail 溢出菜单中 `href === "/chat"` 走 `onHomeClick` 的分支（`SidebarNav.tsx:279-282`）经公共 API 不可达：模块列表构造时剔除 `/chat`，存储布局里的 `/chat` 也会被 `resolveNavLayout` 的 prune 丢弃，折叠组永远不含 `/chat`。属防御性代码，未立缺陷。
- 折叠组在 DOM 中保持挂载（grid 0fr 收起动画），关闭态由 `aria-hidden`/`inert` 屏蔽；用例同时用 DOM 查询与无障碍树断言两种口径覆盖，行为符合设计，非缺陷。
- 除文件名适配外未发现需立修复卡的缺陷。

## 验证命令与结果

- `npx vitest run tests/sidebar/sidebar-activity.smoke.spec.tsx` → 28 passed
- `npx vitest run`（全量回归）→ 147 files / 681 tests passed
- `npm run typecheck` → 通过
- `npx eslint tests/sidebar/sidebar-activity.smoke.spec.tsx` → 无告警
