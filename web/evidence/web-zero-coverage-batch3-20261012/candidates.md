# web 零覆盖组件补测第 3 批 — 候选清单（AGEN-1845）

- 日期：2026-10-12；基线：`origin/main` @ `6cf793bd868ba5ecbe64722936d4be8fab5a01df`（release v1.6.14）
- 分支：`test/web-zero-coverage-batch3-20261012`（新 worktree 产出，未动主检出）
- 线索源：`myfork/scan/web-zero-triage-20261008`（AGEN-1181），本批按最新 origin/main 全量重算

## 一、重算口径（可复算）

1. 枚举 `web/components/**/*.tsx`（排除 `index.tsx` barrel），共 359 个。
2. 以组件文件名（去扩展名）在 `web/tests/**` 全文匹配；任一命中即视为已覆盖。批后余 **162 个零覆盖**（较 triage 期 201 下降，来自既有 test-web-* 卡合入 main）。
3. 批 1 已覆盖 4 个（在 `myfork/test/web-zero-coverage-batch1`，尚未合入 main，需人工排除）：
   `components/chat/space/ChatSpaceMenu.tsx`、`components/notebook/NotebookSelector.tsx`、`components/tasks/TaskColorPicker.tsx`、`components/chat/home/MasteryHandoffCard.tsx`。
4. 在飞分支去重（本机 myfork 未合分支，均不与本次所选 8 个重叠）：
   - `test/web-partner-channels-ui-20261012` → PartnerChannels、ChannelIcon
   - `test/web-route-draft-learning-20261012` → ModuleOutline、RouteDraftEditor
   - `test/web-sidebar-activity-20261009` → SidebarNav、SessionActivityPanel
   - `test/web-kb-doclist-20261009` → KbDocumentList
   - `test/web-mcp-catalog-browser-20261009` → McpCatalogBrowser
   - `test/web-knowledge-history-progress-20261009` → useKnowledgeHistory（hook）
   - `test/web-use-mcp-servers-20261009` → useMcpServers（hook）
5. 全量机器可读清单：`zero-coverage-20261012.json`（162 项 + ≤150 LOC 子集 78 项）。

## 二、本批所选 8 个（均 ≤150 LOC，渲染 + 交互/边界）

| 组件 | LOC | 新 spec | 覆盖要点 |
| --- | --- | --- | --- |
| `components/auth/LogoutButton.tsx` | 49 | `tests/components/auth/logout-button.spec.tsx` | enabled=false 渲染 null；collapsed/展开两变体；点击 → 先 `logout()` 后 `router.replace('/login')`（顺序断言）；pending 时不提前跳转 |
| `components/knowledge/KbIndexFailureBanner.tsx` | 50 | `tests/components/knowledge/kb-index-failure-banner.spec.tsx` | 健康/非 error 态渲染 null；自定义 message、无 message 兜底文案、statistics 兜底；embedding/completion 配置类错误 → 对应 settings 锚点链接；非配置错误无链接；action 插槽 |
| `components/chat/home/PartnerSelector.tsx` | 74 | `tests/components/chat/partner-selector.spec.tsx` | loading/error/空三态；aria-pressed 唯一选中；点选回传精确 id；None → `onSelect(null)`；/partners 链接 |
| `components/common/ProcessLogs.tsx` | 97 | `tests/components/common/process-logs.spec.tsx` | 空闲无输出渲染 null；executing 空输出占位文案；标题默认/覆盖；计数徽标；行号三位补零（textContent 精确 "  1"）；details 折叠/展开；贴底跟随与滚离不跟随（scrollTo 调用计数） |
| `components/space/question-bank/BankSelectionBar.tsx` | 95 | `tests/components/question-bank/bank-selection-bar.spec.tsx` | count=0 渲染 null；全选按钮仅部分选中时出现；Remove tag 仅 category scope；清空选择回调；CategoryMenu 选既有 tag 回传 id；新建即归档（trim 后入参）；失败保持菜单打开 |
| `components/reading/workspace/ReadAloudButton.tsx` | 116 | `tests/components/reading/read-aloud-buttons.spec.tsx` | 无 provider / 非 default 年龄模式渲染 null（ReadAloudButton 与 PageToolButtons 均验）；朗读开始走 `run(entry)`（key 精确 `read_aloud:read`）、speaking 时点停 `stopSpeaking`；busy 禁用；PageToolButtons 过滤 read_aloud 与 needsSelection；onQuiz 回调；busy 仅禁用对应扩展 |
| `components/knowledge/ConnectKiwixModal.tsx` | 117 | `tests/components/knowledge/connect-kiwix-modal.spec.tsx` | Connect 三字段齐前禁用；Browse 带 trim 参数、空目录提示、失败 alert；目录选择回填 ZIM；probe 成功显示 Ready 标题、失败 alert；改字段清验证；连接成功 onClose、失败留在弹窗、busy 全按钮禁用 |
| `components/workspaces/WorkspaceSwitcher.tsx` | 69 | `tests/components/workspaces/workspace-switcher.spec.tsx` | 选项顺序与 Default 头位；archived 仅在激活时保留；非 ready 禁用；激活项不在列表 → Workspace unavailable；legacy `workspace` 参数回退；切换回传精确 id；加载失败 alert；草稿保存失败窗口事件 → alert；管理链接 |

合计 8 个 spec、70 条用例，全部离线（网络/路由/hook 均模块级 mock），无 snapshot 断言，断言均为精确文本/精确回调参数/调用次数。

## 三、验证

- `npm run test:unit`（vitest run，900s 限时）：154 个测试文件 / 723 用例全绿，含新增 8 文件 / 70 用例
- `npm run typecheck`：通过
- 产品代码零改动：本分支仅新增 `web/tests/**` 与本 evidence 目录

## 四、顺延建议（下一批 ≤150 LOC 余量仍足）

≤150 LOC 零覆盖余 70 个（78 − 本批 8），高价值候选：`components/settings/TaskModelsEditor.tsx`(100)、`components/partners/SoulEditor.tsx`(101)、`components/common/ToastViewport.tsx`(80)、`components/knowledge/KbKiwixArticlesSection.tsx`(90)、`components/mcp/McpServerList.tsx`(127)、`components/chat/home/SelectedResources.tsx`(132)、`components/settings/ChatResponseTimeoutSection.tsx`(136)、`components/space/learning/EditTopicRouteDialog.tsx`(144)。
