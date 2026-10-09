# web zero 深位补测：QuizConfigPanel

日期：2026-10-09
目标文件：`web/components/quiz/QuizConfigPanel.tsx`（767 行）
来源：myfork 分支 `scan/web-test-gaps-20261007` 的 `web/evidence/web-test-gaps-20261007/summary.json`
zero 清单（`zero` 共 368 项，含 `components/quiz/QuizConfigPanel.tsx`；`totals` 886 源文件 / 445 covered / 368 zero）。

## 交付

- 测试：`web/tests/quiz/quiz-config-panel.smoke.spec.tsx`，16 个用例，全部通过。
- 基线：`origin/main` @ `6cf793bd8`（release: v1.6.14），独立 worktree + 新分支
  `test/web-quiz-config-panel-20261009`，未触碰 `/Users/Shared/DeepTutor` 主工作区。
- 产品代码零改动：`git status` 仅新增上述测试文件与本证据目录。

### 文件名说明

卡面建议 `quiz-config-panel.smoke.test.tsx`，但仓库 vitest include 仅匹配
`tests/**/*.spec.ts(x)`（`web/vitest.config.mts`），`.test.tsx` 不会被
`npm run test:unit` 收集；按同目录既有约定改用 `quiz-config-panel.smoke.spec.tsx`
（对齐 `tests/quiz/QuizViewer.smoke.spec.tsx`）。

## 覆盖点清单

配置项渲染
1. 裸表单分支（`collapsed` 缺省）：无 Settings 头，Custom 模式高亮，Count=3 /
   Difficulty=auto（含 Auto/Easy/Medium/Hard 选项）/ Type 触发器显示 Auto，
   少于 2 类时不渲染 Type Mix 比例条。
2. mimic 分支：Count 等自定义字段消失，出现 Upload PDF（无文件虚线态）、
   Parsed Dir（空）、Max=10。
3. 折叠分支：`collapsed=true` 隐藏表单体，显示 Settings 头与
   `summarizeQuizConfig` 摘要（Custom · 3 questions · Auto · 2 types）；
   `collapsed=false` 相反。

校验失败
4. Count 输入 0 / 空串 → 回夹到最小值 1（`Math.max(1, Number||1)`）。
5. mimic Max 输入 0 → 回夹到 1。
6. 选拟类型数超过 num_questions 时自动抬总量并均分（1 → 选 3 类 → total=3、
   每类 1）。
7. 选择降到 1 类 / Auto 清空时，`per_type_counts` 被清空（rebalance effect）。
8. drop 非 PDF 文件被忽略（onUploadPdf 不触发、无 onChange）；drop PDF 被接受
   并清空 paper_path。

提交回调（组件为受控面板，对外回调即 onChange / onUploadPdf / onToggleCollapsed）
9. 模式切 mimic → onChange 载荷 `{mode:"mimic"}`。
10. Difficulty 选择 → onChange 载荷 `{difficulty:"hard"}`。
11. 文件 input 选择 PDF → `onUploadPdf(file)` 且 onChange 清 `paper_path`。
12. 已上传 PDF chip 的 Remove PDF → `onUploadPdf(null)`。
13. 手输 Parsed Dir → 先 `onUploadPdf(null)` 再 onChange 更新 `paper_path`。
14. portal 类型多选：开合（aria-expanded）、逐类勾选 → `question_types` 追加、
    Auto 行清空选择、Escape 关菜单。
15. 2 类时 rebalance 产出 `{choice:2, concept:1}`（余数落首类），Type Mix 与
    `3/3` 总数、图例计数渲染。

默认值分支
16. 已有 counts 且总和等于 total 时，挂载后不触发任何 rebalance 写回
    （保持用户输入，`onChange` 零调用）。

## 命令与数字

```
npx vitest run tests/quiz/quiz-config-panel.smoke.spec.tsx
  → Test Files 1 passed (1) / Tests 16 passed (16)
npx vitest run                       # 全量回归
  → Test Files 147 passed (147) / Tests 669 passed (669)
npm run typecheck                    # 通过，无输出
npx eslint tests/quiz/quiz-config-panel.smoke.spec.tsx   # 通过，无输出
```

## mock 说明

该组件为纯受控 UI，不直接发起网络请求；测试以受控 harness（React state +
`vi.fn` 回调）模拟外部边界（onChange / onUploadPdf / onToggleCollapsed），
与"mock API"验收口径一致。

## 观察项（可立修复卡，非阻塞）

- `num_questions`/`max_questions` 仅在代码里夹下限 1；`min`/`max` HTML 属性
  （50/100）不拦截手输超界值，超界值会直接进入提交载荷。如需硬上限应在
  `update` 内夹取或提交前校验。
- 比例条拖拽（pointer 手势）未纳入 smoke（jsdom 指针捕获受限），夹取逻辑
  （两侧不低于 1）仅由 effect 路径间接覆盖。
