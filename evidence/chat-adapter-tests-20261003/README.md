# ChatStateAdapter 流式状态适配补测 — 证据（AGEN-288）

日期：2026-10-03 · 基线：HKUDS/DeepTutor `origin/main` @ `ef2d9e5c3`（release v1.6.12）

## 产物

- 测试文件：`web/tests/chat/ChatStateAdapter.streaming.spec.tsx`（本分支新增，14 例）
- 分支：`myfork/test/chat-state-adapter-streaming-20261003`（推送到 myfork，未向上游开 PR）
- 运行日志：`vitest-run.log`

## 与卡片命名偏差说明

卡片产物名为 `web/tests/chat/ChatStateAdapter.streaming.test.tsx`。该后缀在仓库中
**不会被任何测试运行器拾取**：vitest 只匹配 `tests/**/*.spec.ts(x)`
（`web/vitest.config.mts`），node 测试只编译 `tests/**/*.ts`（`web/tsconfig.node-tests.json`）。
为了"修复卡可直接领取"（验收 2），按仓库既有约定改用 vitest 规格文件命名
`ChatStateAdapter.streaming.spec.tsx`（jsdom + @testing-library/react，与
`tests/ask-user-terminal-turn.spec.tsx` 同一模式）。内容与卡片要求一致。

## 覆盖点（对照验收 1）

流式事件注入的状态迁移（mock UnifiedTurnClient 逐事件注入）：

1. 完整一轮：用户气泡 → STREAM_START 占位 → content 增量累积 → stage_start/stage_end
   映射 currentStage → done 携带持久化 id 时 RECONCILE_TURN 换乐观 id + SETTLE_MESSAGE_TRACE；
2. 同 turn_id+seq 重放事件去重（isSameTurnEvent），文本与事件列表均不重复；
3. 撤回轮（`answer_visible:false` 的 call_status 标记）把已流出的文本从答案中移除
   （recomputeAnswerContent），后续最终轮文本正常追加；
4. `session` 事件把 draft 会话绑定到服务端 session id，后续事件仍落入同一会话；
5. done 后的宽限窗口：5s 侧边栏标题刷新 bump、15s 才断开 socket（fake timers 断言）。

错误路径（错误横幅的数据面）：

6. `error` + `turn_terminal` 事件 → 会话失败态、退出 running 状态表、部分答案保留、无误报 toast；
7. 流式中途掉线（onClose）→ 失败态 + 在尾行追加 turn_terminal 的合成 error 事件
   （UI 错误横幅渲染的数据源）+ "Connection lost…" 错误 toast；
8. 挂起 ask_user 卡片时掉线 → 不失败、不弹 toast（轮次仍在等用户输入）。

重连恢复路径：

9. start_turn 发送的重试阶梯（200ms 间隔）：连上后恰好送达一次 start_turn；
10. 重试 10 次仍连不上 → 失败态、空占位被丢弃、用户行标记 `failedSubmission`
    （#1594 语义）+ "Couldn't reach the server…" toast；
11. 流式静默超时（默认 180s）→ 看门狗按 lastSeq 发 `resume_from` 续订（含 session
    事件自身的 seq 计入 lastSeq 的语义锁定），touch 后不重复续订；
12. 挂起 ask_user 的静默轮次不续订；
13. 加载 running 会话（活跃 turn 新鲜）→ 自动发 `subscribe_turn`（after_seq:0）续订；
14. 本地已在流式的会话，revalidate 快照直接丢弃，不覆盖本地流、不重订。

## 验证数字

- 目标文件：`npx vitest run tests/chat/ChatStateAdapter.streaming.spec.tsx` → **14 passed / 0 failed**
- 全量单元套件（同 commit 同工作树）：`npx vitest run` → **114 files / 485 tests 全部通过**
- `npm run typecheck` → 0 错误（tsconfig include 含 tests/**/*.tsx）
- `npx eslint tests/chat/ChatStateAdapter.streaming.spec.tsx` → 0 问题
- 未改任何产品代码：`git status` 仅新增 `web/tests/chat/` 与本证据目录。

## 给修复卡 / 后续领取人

- 直接跑：`cd web && npx vitest run tests/chat/ChatStateAdapter.streaming.spec.tsx`
- mock 面只有三处：`UnifiedTurnClient`（事件注入/掉线/不可达开关）、`@/lib/session-api`
  （getSession 夹具）、`@/lib/notifications`（toast 断言）；其余（stream、idle-recovery、
  trace/memory 等）全部走真实实现，改这些模块若破坏契约会在此套件直接暴露。
- 注意：主工作区 `/Users/Shared/DeepTutor`（本地 main `2a4c4c5f1`）含未推送的
  ChatStateAdapter 重构（narration 语义等），本套件锁定的是 **origin/main（`ef2d9e5c3`）**
  的撤回（retraction）语义；本地 main 落地后需同步更新第 3 例。

## 上游检查

未发现与 ChatStateAdapter 补测相关的上游 PR/issue。相邻活动：issue #1648（ask_user
在 WS 重连期间提交失败）与其 PR #1668 属产品修复线，与本测试卡不冲突；本套件第 8/12 例
恰好锁定了"挂起 ask_user 不因掉线失败"的状态语义，可供其复核参考。
