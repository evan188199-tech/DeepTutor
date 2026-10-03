# AGEN-291 · web/ `void` fire-and-forget 与 no-op catch 分型扫描报告

- **任务**: 对 DT-22 报告中"约 394 处 `void` 未定性"做只读分型扫描，产出可拆卡清单（接续附录 B）
- **扫描对象**: HKUDS/DeepTutor `origin/main` @ `ef2d9e5c3c99fd073742c5aadc2bb9584b1e503b`（v1.6.12）
- **扫描日期**: 2026-10-03（UTC）
- **方式**: 只读静态扫描（Python 词法掩码 + 正则 + 项目级定义索引 + 一层传递解析 + 人工抽样复核）。**未修改任何产品代码。**
- **范围**: `web/` 全部 `.ts`/`.tsx`（1214 个文件；排除 `node_modules`、`.next` 等构建产物）
- **结论**: **PASS** — 913 条记录全部分型完成，明细见 `void-promises.json`

## 1. 总量与分型

| 类别 | 条目数 | 占比 |
| --- | --- | --- |
| `void` 语句（fire-and-forget） | 742 | 行首 422 + JSX/块内联 320 |
| no-op `.catch(() => {})` | 55 | — |
| 注释型空 catch（仅有注释的 catch 块） | 116 | — |
| **合计** | **913** | — |

### `void` 语句三分类（742 条）

| 分型 | 定义 | 数量 |
| --- | --- | --- |
| **有内部错误处理** handled_internally | 被调函数体内全部 await 位于 try/catch 或链式 `.catch`（full 384），或委托给同文件守卫/包装器（via_helper 17：`guard`×8、`refreshAuthoritative`×3、`run`×2 等），或调用点自带非空 rejection handler | **411** |
| **尽力而为语义** best_effort | 读取类调用（load/refresh/fetch，失败=陈旧数据）、同步函数（无 await/throw，不可能 reject）、浏览器 API（clipboard/fullscreen/play）、动态 import 预取、teardown 类（destroy/abort/cancel）、`set` 开头本地 state setter、无调用表达式惯用法（`void x;` 压制未用变量） | **94** |
| **真吞错** swallow | 两侧均无错误处理：确认级（HIGH）= 同文件被调函数确无 catch 且为变更类操作；疑似级（MEDIUM）= hook/context/prop 提供的被调函数，处理不可见 | **237**（HIGH 22 + MEDIUM 215） |

### no-op catch 与注释型空 catch

- no-op `.catch`（55）：MEDIUM 44（变更调用点）/ LOW 11（只读调用点）
- 注释型空 catch（116）：全部有注释佐证属"有意为之但静默"（如 `// ignore – health is non-critical`、剪贴板降级等），评级 LOW，建议保持现状或加 debug 日志，不拆卡
- 与 DT-22 附录 B 对齐：附录 B 的 37 处 no-op catch 全部包含于本次 55 处（本次额外覆盖 `e => {}`、`{ return; }` 变体）；附录 B 的 3 处空 catch 中 2 处在本范围（`.ts/.tsx`，`web/lib/iframe-html.ts:103/121`），1 处为 `next.config.js`（`.js`，超出本卡 `.ts/.tsx` 范围）

## 2. HIGH（22 条调用点 / 13 个被调函数）——真吞错确认清单

全部经人工读码核实：`try/finally` 无 catch（rejection 穿透 finally 逃逸）或完全无处理。

| 位置 | 被调函数 | 模式 | 失败后果（一句话） |
| --- | --- | --- | --- |
| `web/components/SessionList.tsx:174,176,203,282,284,332` | `commitEdit`（定义 :83） | `await onRename(...)` 无 catch | 重命名会话失败时无任何提示，输入框静默复原，用户以为改名成功 |
| `web/app/(workspace)/learning/books/components/blocks/BlockBodyEditor.tsx:65,86` | `commit`（:40，try/finally 无 catch） | `await onSave(draft)` | 书籍区块编辑内容保存失败静默丢失，`saving` 状态复位后界面看似正常 |
| `web/app/(workspace)/learning/books/components/blocks/UserNoteBlock.tsx:106,125` | `commit`（:53，同上） | `await onSave(draft)` | 用户笔记保存失败静默丢弃，编辑态关闭造成"已保存"错觉 |
| `web/features/chat/components/ChatWorkspace.tsx:2852` | `handleSend`（:1890） | 多个 await 无 catch | 核心聊天发送链路拒绝时消息可能未发出且无失败反馈 |
| `web/app/(utility)/profile/page.tsx:400` | `handleSignOut`（:181） | `await logout()` 无 catch | 登出接口失败则用户滞留已登录界面且不跳转登录页，令牌状态与界面不一致 |
| `web/app/(workspace)/learning/mastery/[pathId]/page.tsx:672` | `handleDelete`（:237，try/finally） | `await deleteProgress(pathId)` | 掌握路径删除失败时仍执行界面跳转，用户误以为已删除 |
| `web/components/courses/CourseResources.tsx:280` | `attach`（:150，try/finally） | `await onAttach(...)` | 课程资料挂载失败静默，列表不出现新资料且无错误提示 |
| `web/components/courses/OrganizedSessionList.tsx:365,369` | `commitEdit`（:269） | `await onRename(...)` 无 catch | 课程会话重命名失败静默 |
| `web/components/settings/ModelsWorkspace.tsx:797` | `remove`（:628） | `await stageRegistry({...delete:true})` | 模型删除请求失败静默，界面已移除而服务端仍在，产生"幽灵模型" |
| `web/components/space/MyAgentsSection.tsx:312` | `commitRename`（:240） | `await saveAgent(...)` 无 catch | 智能体重命名失败静默 |
| `web/components/space/MyAgentsSection.tsx:315` | `removeAgent`（:251） | 删除流程无 catch | 智能体删除失败静默，列表与服务端状态不一致 |
| `web/components/space/question-bank/CategoryManager.tsx:74,83` | `commitRename`（:45） | `await run(() => onRename(...))` 而 `run` 自身无 catch | 题库分类重命名失败静默 |
| `web/components/watching/WatchingPane.tsx:653` | `retryTranscript`（:389） | `await refreshTranscript()` 无 catch | 字幕重试失败无任何信号，用户反复点击无响应 |

### 顺带校正 DT-22 附录 B 的 1 条 HIGH

- `web/app/(utility)/courses/[courseId]/page.tsx:414` `void deleteCourse(...).then(...)`：本次细分为 **MEDIUM**——`.then()` 链无 rejection handler，删除课程失败时 then 回调不执行且产生 unhandled rejection；建议补 `.catch` 并回滚 UI。DT-22 因工具粒度未拆 `.then` 场景而记 HIGH。

## 3. 可拆卡清单（按功能域聚合，建议每卡一次 PR）

| 卡 | 范围 | 条目 | 建议修法 |
| --- | --- | --- | --- |
| A · 会话重命名吞错 | `SessionList.tsx` + `OrganizedSessionList.tsx` 的 `commitEdit` | 8×HIGH | `commitEdit` 内部 try/catch → 复用现有 toast/notice；或调用点 `.catch(setError)` |
| B · 书籍区块/笔记保存吞错 | `BlockBodyEditor.tsx` + `UserNoteBlock.tsx` 的 `commit` | 4×HIGH | try/finally 补 catch → `notify(error)` 并保持编辑态不关闭 |
| C · 核心发送链路 | `ChatWorkspace.tsx` `handleSend` | 1×HIGH | 包裹 try/catch 并走现有失败气泡机制（与发送重试预算对齐） |
| D · 空间管理三类 | `MyAgentsSection`（rename/remove）+ `CategoryManager`（rename） | 4×HIGH | 各自 catch → `notify`；`run` 包装器可顺势内建 catch |
| E · 设置页删除/登出 | `ModelsWorkspace.remove`、`profile/page.tsx handleSignOut`、`mastery handleDelete` | 3×HIGH | catch → 提示并**中止跳转/列表更新**（保证 UI 与服务端一致） |
| F · 课程域 | `CourseResources.attach`（HIGH）+ `courses/[courseId]/page.tsx:414`（MEDIUM then 链） | 2 | `.catch` → toast + 回滚 busy 态 |
| G · 阅读域 hook 返回疑似组 | `ReaderPane`（saveMark/removeMark）、`ReadingWorkspace`（toggle/removeBookmark）、`SourceNavigator` 等 | ~34×MEDIUM | hook 返回值不可见处理 → 逐个追到 `useReadingWorkspace` 等实现确认后补 UI 错误态 |
| H · 设置/聊天/伙伴疑似组 | `features/settings/sections`×14、`components/chat/home`×12、`components/partners`×11 等 | ~60×MEDIUM | 抽样确认后：变更类补 catch+提示；读取类可接受但建议 console.warn |
| （不拆卡） | 注释型空 catch 116 处 + best_effort 94 处 | — | 维持现状；可选在 debug 构建加日志 |

## 4. 方法与判定规则

1. **词法掩码**：字符串/模板/注释/正则字面量替换为等长空白（保留行号），消除 `Promise<void>`、`"void"` 等类型/字面量误报；`void 0`、`void (0)` 排除。
2. **void 语句识别**：语句位置判定（前导 `;{}>)`/箭头体、后随操作数），覆盖行首与 JSX 内联（`() => void x()`、`cond ? void a() : undefined`）。与 `rg '^\s*void\s'` 基线 422 条完全对齐（0 漏 0 多），另捕获内联 320 条。
3. **定义索引**：跨 1214 文件索引 `function`/`const = (async) =>`/`useCallback`/导出对象方法/解构导入/hook 返回对象。
4. **分型判定顺序**：调用点 handler（`.catch`/`.then(a,b)`）→ 同步性（无 await/.then 且无 throw ⇒ 不可能 reject）→ 被调函数体（await 是否全部位于 try 内；`try/finally` 无 catch 记为可逃逸）→ 一层传递解析（同文件守卫/包装器如 `guard()`、`withSourceAction()`、`persist()` 内部有 catch ⇒ 视为已处理）→ 语义动词打分（变更/只读/teardown）→ 不可见提供者（hook/context/prop）降为疑似。
5. **人工复核**：全部 22 条 HIGH、随机抽样 22 条（两轮各 11，12/12 锚定正确）逐一读码核对；Top10 均经人工确认。

## 5. 复现命令

```bash
# 在本分支 evidence/void-promise-scan-2026-10-03/ 下
python3 scan_void_promises.py ../../../web void-promises.json   # 约 4 秒，只读
# 基线对齐检查（应 422/422/0）
rg -n --no-heading '^\s*void\s' ../../../web -g '*.ts' -g '*.tsx' -g '!node_modules/**' | wc -l
```

## 6. 局限性

- 纯静态一层传递解析：被调函数经两层以上包装（如 `a → b → try/catch`）时可能记为 swallow（疑似级，偏保守）；未做 TS 类型解析与跨文件 prop 数据流。
- hook 返回对象的成员方法（如 `bank.toggleBookmark`）只判到"处理不可见"，需拆卡时人工追实现。
- `.js`/`.mjs`（如 `next.config.js`）不在本卡范围（DT-22 覆盖过）。
- 正则掩码对极端正则字面量仍可能个别误判；本次抽样未发现残余影响。

---
*由只读扫描生成（agent/dt22-void-promise-scan @ myfork）。定级争议以 §4 规则与源码现场为准。*
