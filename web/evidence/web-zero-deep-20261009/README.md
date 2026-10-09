# web-zero-deep-20261009 — SkillsSection / CliAppsSection zero 深位补测

对应卡：AGEN-1190（web Skills/CliApps 区块渲染分支补测）。
来源清单：`myfork/scan/web-test-gaps-20261007` 的 `web/evidence/web-test-gaps-20261007/summary.json`
（zero 项 `components/space/SkillsSection.tsx` 1038 loc、`components/cli-apps/CliAppsSection.tsx` 1026 loc，
basis 均为 "no test file references this path or basename"）。

## 交付

- 新增测试：`web/tests/space/skills-cli-sections.smoke.spec.tsx`（27 个用例）。
- 基线：`origin/main` @ `6cf793bd8`（v1.6.14），新 worktree + 新分支
  `test/web-skills-cli-sections-20261009`，产品代码零改动（`git status` 仅新增测试与证据）。

## 文件名说明（与卡面唯一偏差）

卡面写的 `skills-cli-sections.smoke.test.tsx` 后缀为 `.test.tsx`，但
`web/vitest.config.mts` 的 include 只匹配 `tests/**/*.spec.ts(x)`，`.test.tsx`
永远不会被 `npm run test:unit` 执行；仓库内组件 smoke 测试的既有命名也是
`.smoke.spec.tsx`（如 `tests/chat/ChatWorkspace.smoke.spec.tsx`）。因此按
`.spec.tsx` 落盘，保证测试真实进入 vitest 运行。

## 覆盖点（mock API 层，不动产品代码）

SkillsSection（12 例）：

1. 列表渲染：标题/计数 meta、source 徽章（Built-in）、只读卡无编辑删除、描述与
   "No description."、未打标 chip。
2. 空态 + 空态入口打开新建编辑器（默认正文 "# My Skill"）。
3. 标签筛选（按 tag / Untagged / 无匹配的 "No skills match this filter."）。
4. 只读详情 viewer：frontmatter 剥离渲染、只读徽章、无编辑按钮、遮罩点击关闭。
5. 详情请求失败的 viewer 内错误展示。
6. 新建校验链：空名 "Name is required" → 超长名非法 → 输入自动 slug 化 →
   保存成功调用 `createSkill` 并重载列表。
7. 新建失败：编辑器保留并展示错误。
8. 编辑流：`getSkill` 预填、改名保存时 `updateSkill` 带 `rename_to`、成功关窗。
9. 删除流：确认弹窗带 "Used by workspaces" 占用信息；拒绝不调用 `deleteSkill`，
   接受后调用并重载。
10. 标签管理器：新建（规范化小写）、重命名（Enter 提交）、删除（确认后调用）。
11. 编辑器内标签：切换既有 chip、输入新 tag 自动 `createSkillTag` 并随保存持久化。
12. 列表加载失败：错误横幅展示原始 message。

CliAppsSection（15 例）：

1. 已装列表：开关（granted 才有）、"N available to you" 计数、trust chip
   （Pinned / Third-party, unpinned）、未授权锁定说明、安装日期与 pin 截断。
2. 初始加载失败横幅。
3. 管理员空态文案 + "Browse the store" 切换到 Store。
4. 非管理员空态文案分支。
5. `access.exec_denied` 警告横幅。
6. 启停开关：点击调用 `setCliAppEnabled(id, false)`，回包 state 驱动开关与计数更新。
7. 启停失败：错误横幅、开关保持。
8. 卸载：确认拒绝不调用；确认后调用 `uninstallCliApp` 并回到空态。
9. Store 分页：首屏 entries + "2 of 3 apps"、Load more 以 cursor 追加、
   分类 chip（带计数）触发 category 过滤、"Include unavailable" 触发
   `installableOnly: false`。
10. 搜索输入防抖（250ms）后带 `q` 查询。
11. Store 空态 "Nothing matches"。
12. 条目详情：requires/notes/安装目标/未 pin 警告/工具名 `cli_<id>`、Website/Source
    外链；安装失败展示错误与安装日志；重试成功后转 "Reinstall"、Installed 徽章、
    计数联动。
13. 非管理员：Store 顶部说明横幅 + 详情只读说明、无安装按钮。
14. `installable: false` 条目："Not installable here." + unsupported_reason。
15. `adminKnown` 未定（auth loading）：安装区块整体不渲染。

## 运行与结果

```bash
cd web
npx vitest run tests/space/skills-cli-sections.smoke.spec.tsx   # 27 passed
npm run test:unit                                               # 147 files / 680 tests passed
npm run typecheck                                               # 通过
npx eslint tests/space/skills-cli-sections.smoke.spec.tsx      # 无告警
```

- 单文件用例清单见 `test-cases.txt`。
- 全量 vitest（含本文件）无回归；未改任何产品代码。

## 缺陷观察

本轮 27 例全部通过，未发现可直接立修复卡的功能缺陷。两处值得注意的既有行为
（非缺陷，仅记录）：

1. SkillsSection 编辑器新建 tag 只做 trim+lowercase，不压缩空格
   （"Fresh Tag" → "fresh tag"），与名称 slug 化规则不同；与后端标签语义一致即
   可，不阻断。
2. CliAppsSection 安装成功后，EntryDetail 内上一次失败的错误横幅会保留到下一次
   install 尝试（`install()` 才会清空 error）。属可感知的轻微 UX 瑕疵，不阻断，
   如需可另开体验修复卡。
