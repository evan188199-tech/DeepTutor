# web-zero-deep-20261009 — Capabilities/Tools 设置区块补测说明

## 范围与来源

零覆盖清单取自 `myfork` 分支 `scan/web-test-gaps-20261007` 的
`web/evidence/web-test-gaps-20261007/summary.json`（`zero` 列表共 368 项，
`zero-entries.json` 摘录本卡涉及的两条）。基线为 origin/main `6cf793bd8`
（release v1.6.14），只新增测试与证据文件，未改动任何产品代码。

| 组件 | 行数 | 新测试文件 |
| --- | --- | --- |
| `features/settings/sections/CapabilitiesSettingsSection.tsx` | 642 | `tests/settings/capabilities-tools-sections.smoke.spec.tsx` |
| `features/settings/sections/ToolsSettingsSection.tsx` | 594 | 同上（第二组用例） |

去重说明：设置 store 已由 `tests/settings/settings-store.test.ts` 覆盖，本卡只测
这两个区块组件本身；`lib/tool-availability.ts` 的开关有效性判定经组件渲染路径
间接覆盖，不重复单测。两个用例组共用一套「真实 SettingsProvider + 有状态 mock
后端」harness（PUT 会改写 mock 后端状态，GET 返回最新状态），保存/回滚分支走
`applyCatalog()` / `discardDraft()` 的真实代码路径。

## 文件名适配

卡面写的 `web/tests/settings/capabilities-tools-sections.smoke.test.tsx` 在本仓库
不会被执行：`vitest.config.mts` 的 include 只有 `tests/**/*.spec.ts(x)`。按仓库既有
约定落为 `web/tests/settings/capabilities-tools-sections.smoke.spec.tsx`（同日
`test/web-sidebar-activity-20261009` 卡相同处理）。可立一张小改进卡：统一渲染
测试后缀或扩展 vitest include，避免 `.test.tsx` 被静默忽略。

## 覆盖点清单

CapabilitiesSettingsSection（能力参数页）：

1. 加载渲染：Chat / Solve / Question / Research / Math animator / Visualize /
   Co-writer 七个分组齐全，25 个数值行按服务端值渲染，tool summarizer 开关
   初始为开；加载阶段不产生任何 PUT
2. 网络失败：错误框（标题 + 原始错误信息）替代整页，无输入行；Retry 恢复正常渲染
3. HTTP 失败与非法 payload 分支区分：HTTP 500 文案 → Retry 后返回 `{}`
   触发 unexpected payload 文案 → 再 Retry 后正常渲染（重试链覆盖三分支）
4. 编辑暂存与保存成功：改 temperature、关 summarizer 开关 → `hasUnsavedChanges`
   且零 PUT；Apply 恰好 PUT 一次，body 为编辑后的完整 DTO
   （`chat.temperature=1.5`、`tool_summarizer.enabled=false`）；保存后
   `draftState=clean`，且 Apply 后 revision bump 触发的重取不再回滚已保存值
5. 保存失败与回滚：PUT 500 → toast `Could not apply`、编辑值保留待重试、
   PUT 恰好一次；Discard → revision bump → 重取 → 服务端值恢复、
   `hasUnsavedChanges=false`

ToolsSettingsSection（工具开关页）：

6. 分桶渲染：Experience Enhancement / Built-in Tools / Deep Solve · Capability
   Tools 三段；开关四态：On（开）、Off（关）、Coming soon（禁用）、
   Not configured（禁用）；不可用文案与 Open settings 链接；rag 与
   solve_plan 渲染为 "Always on" note（role=note，无 switch）；锁定开关
   点击不产生任何暂存
7. 行展开：aria-expanded 切换，展开后 When to use / Input format / Guideline /
   Parameters 与参数行可见，收起后消失
8. 搜索过滤：命中项保留、其余消失；无命中显示 No tools match 空态；
   Clear 按钮恢复全量
9. 开关暂存与保存成功：点击 Off 开关 → 双 On、`hasUnsavedChanges`、零 PUT；
   Apply 恰好 PUT 一次 `/api/settings/enabled-tools`，body 为排序后的
   `{enabled_tools:["imagegen","web_search"]}`；Apply 后重取保持开启态
10. 保存失败与回滚：PUT 500 → toast、关闭态保留待重试；Discard → 重取
    `/api/tools` → 服务端状态恢复（On/Off 各归其位）
11. `/api/tools` 加载失败：错误框 + 不渲染任何分区与开关

## 观察与发现

- `vision_solver` 在 `isValidCapabilitiesDTO` 校验中必填，但组件没有对应编辑
  分区，其取值不渲染在任何行（fixture 值 0.6/2560 无处显示）。若产品预期
  "视觉解题参数可调"，可立修复卡补 UI；若为有意省略，可从 DTO 必填校验中
  放宽。未按缺陷立卡，供决策。
- Capabilities 页 `ToggleRow` 未设置 `aria-label`（Tools 页 `ToolToggle` 有），
  开关无法通过无障碍名称定位，读屏只能落到行标题。可立无障碍小改进卡。
- 除文件名适配外，保存成功/失败/回滚各分支行为均符合预期，未发现需立修复卡
  的功能缺陷。

## 验证命令与结果

- `npx vitest run tests/settings/capabilities-tools-sections.smoke.spec.tsx`
  → 11 passed（连续 3 次全绿，无 flake）
- `npx vitest run`（全量回归）→ 147 files / 664 tests passed
- `npm run typecheck` → 通过
- `npx eslint tests/settings/capabilities-tools-sections.smoke.spec.tsx` → 无告警

## 复现环境说明

工作分支基于 origin/main `6cf793bd8` 新建 worktree；`web/node_modules` 以符号
链接指向主检出的安装产物（仅本地执行用，不入库）。测试命令均在 web/ 目录下
执行，单次限时 900s 内完成。
