# web/ 前端定时器与监听器泄漏静态清点报告（AGEN-978）

- 扫描对象：HKUDS/DeepTutor `origin/main` @ `f07029cfc`（release: v1.6.13），只读 worktree（`dt-agen978-timers-wt`）
- 扫描时间：2026-10-07（UTC）
- 扫描器：`scripts/scan_web_timers.py`（纯标准库，read-only，可复跑、同输入逐字节一致）
- 覆盖：`web/**/*.ts`、`web/**/*.tsx` 共 **1219** 个文件（排除 node_modules/.next/vendor/generated/locales/public 等）
- 原始条目：**23 条** = medium 14 / low 9 / high 0；人工复核后调整 1 条降级，**复核口径分布：medium 13 / low 10 / high 0**
- 基线面：24 处 `setInterval`、117 处 `setTimeout`、222 处 `addEventListener`、712 处 `useEffect`

## 轴线与去重边界

本卡只管「web 前端定时器与监听器泄漏」轴：

| 规则 | 含义 | 级别 |
| --- | --- | --- |
| timeout-in-effect-no-cleanup | useEffect 内的 setTimeout：无清理返回，或清理不 clearTimeout（含"清理写错位置"变体） | medium |
| post-unmount-state-update | 组件内 fire-and-forget setTimeout 回调更新 state，且无 mounted/cancelled 守卫 | medium |
| listener-no-removal | addEventListener 无同事件 removeEventListener（DOM 全局对象在组件上下文为高危档） | med/low |
| interval-dropped-handle / interval-never-cleared | setInterval 句柄丢弃或全文件无 clearInterval 路径 | high/medium |
| listener-wrapper-no-removal | 订阅 helper 不返回取消函数 | low |
| effect-subscription-no-cleanup | useEffect 注册订阅但无任何清理返回（伞形，锚点已单独上报时去重） | high |

去重（不在本卡范围，扫描器按此边界不产出）：后端 session/句柄/子进程泄漏（AGEN-964 `scan_resource_leaks.py`，纯 Python 轴）、React hooks 规则轴（deps/顺序类）、死代码轴。与 AGEN-964 的唯一交集是"句柄管理"概念，但文件域不重叠（本卡仅 `web/`，其卡仅 `deeptutor/**` + `tests/**`）。

## 结果总览

- `interval-dropped-handle` / `interval-never-cleared`：**0 条**。全文件 24 处 setInterval 全部存在 clear 路径（抽 5 处阴性复核，见下文），该子轴在本 commit 干净。
- `timeout-in-effect-no-cleanup`：7 条（全部人工核实属实）。
- `post-unmount-state-update`：7 条（全部人工核实属实；其中 2 条为 0ms 下一帧重置，影响可忽略但模式成立）。
- `listener-no-removal`：9 条（全部 low：一次性脚本单例 / rendition 文档生命周期 / EventSource 容器关闭兜底，均附注记）。
- 无 high：`web/` 对 window/document 级监听的清理纪律整体很好（222 add / 199 remove，组件内成对出现是主流）。

## MEDIUM（14 条，全部人工核实；锚点即文件:行）

| ID | 位置 | 问题 | 修复建议 |
| --- | --- | --- | --- |
| WT-0007 | `web/components/partners/PartnerChat.tsx:734` | WS `attach_busy` 重连重试 `setTimeout(2s)` 挂在大连接 effect 作用域内；effect 清理关闭了 socket、摘除了 focus/online/visibilitychange 监听，但未清理悬挂的重试 timer；卸载后回调经 ref 守卫仍可能触发 `tryAttach()` 重开连接 | 句柄存入 retryTimersRef（该组件 :1809 已有同款 Set 模式）并在清理 `forEach clearTimeout` |
| WT-0008 | `web/components/partners/PartnerChat.tsx:767` | 同上，`attach_idle` 历史回拉 `.catch()` 分支的重试 timer | 同上 |
| WT-0015 | `web/components/reading/ReaderPane.tsx:696` | 自动跳转 120ms timer 的 `clearTimeout` 写在 `onTurnEnd` 事件监听函数的 return 里——事件监听的返回值会被丢弃，这段清理永远不会执行；timer 跨卸载存活并触发 `navigateCitation` | 把 timer 句柄提升到 effect 作用域，在 effect 清理中 clearTimeout |
| WT-0016 | `web/components/reading/workspace/MediaReadingStage.tsx:433` | 同族问题：turn-end 后 120ms 执行 DOM 查询 + `seek()` + `notifyLocator()`（触发 state），timer 无清理；监听器本身有成对摘除 | 同上：句柄提升 + effect 清理 clearTimeout |
| WT-0014 | `web/components/reading/EpubDocumentView.tsx:623` | 高亮自动移除 `setTimeout(2200)` 所在 effect 无清理返回；仅 ref 操作且有 `?.` 守卫，影响小但模式成立 | 句柄保存 + 清理返回中 clearTimeout |
| WT-0004 | `web/components/common/ToastViewport.tsx:25` | 每条 toast 的移除 timer 未清理（代码注释已声明有意为之；订阅有取消函数）。人工复核降级为 low | 可选：toast id → timer 的 Map，卸载时统一 clear |
| WT-0003 | `web/components/chat/preview/FilePreviewDrawer.tsx:156` | 复制成功态 1.5s 重置 timer：无句柄、无守卫，卸载后 setState | 组件级 copiedTimer ref，卸载 clear |
| WT-0005 | `web/components/courses/CourseConventions.tsx:49` | 同上（justSaved 2s 重置） | 同上 |
| WT-0006 | `web/components/knowledge/KbFilePreview.tsx:201` | 同上（copied 1.5s 重置） | 同上 |
| WT-0009 | `web/components/partners/PartnerLinkModal.tsx:75` | 同上（copied 2s 重置） | 同上 |
| WT-0010 | `web/components/partners/group/PartnerSeat.tsx:74` | 同上（copied 1.6s 重置） | 同上 |
| WT-0019 | `web/components/whisper/WhisperRoomChip.tsx:19` | 同上（copied 1.5s 重置） | 同上 |
| WT-0017 | `web/components/reading/workspace/ReadingComposer.tsx:113` | 0ms `setTimeout` 下一帧重置 `readingViewport.selection`：无句柄无守卫；影响可忽略（下一帧即执行）但属同模式 | 可选：改 `requestAnimationFrame` + 卸载取消，或忽略 |
| WT-0018 | `web/components/reading/workspace/ReadingWorkspace.tsx:327` | 同上（0ms 重置） | 同上 |

> 复核注记：WT-0004 已在 `web-timers-review.json` 记录降级（medium→low）；WT-0017/0018 保留 medium（模式属实）但在修复优先级上可排最后。

## LOW（9 条，生命周期注记型，不构成立即风险）

| 模式 | 数量 | 锚点 | 注记 |
| --- | --- | --- | --- |
| 一次性 `<script>` 单例的 load/error 监听 | 2 | `web/components/Geogebra.tsx:60`、`web/components/Geogebra.tsx:61` | 模块级单例、至多触发一次、随页面销毁；建议保持现状或改 `once: true` |
| epub rendition 文档上的 touch/click 手势监听 | 3 | `web/components/reading/EpubDocumentView.tsx:372`、`:383`、`:403` | 生命周期由 `rendition.destroy()` 兜底；重载内容时会重复注册，建议注册前先摘除或改用容器级委托 |
| EventSource 事件监听无 removeEventListener | 4 | `web/hooks/useKnowledgeProgress.ts:306`、`:331`、`:364`、`:391` | source 由 `sourcesRef` 容器管理并在卸载路径 `close()`（:118/:130），监听随对象销毁；条目仅作清单留存 |

## 人工核实记录（全量 + 阴性抽样）

- **阳性全量**：23/23 条逐条回读锚点代码核实属实（判定与注记见 `web-timers-review.json`），其中 1 条按证据降级（WT-0004）。
- **阴性复核 10 项**（扫描器正确保持沉默）：
  1. `web/hooks/useKnowledgeBases.ts:187` interval 有清理 ✓
  2. `web/app/(workspace)/whisper/page.tsx:150` poll/giveUp/retry 三类 timer 全清理 ✓
  3. `web/features/settings/sections/DataMigrationSettingsSection.tsx:108` alive 旗标 + clearInterval ✓
  4. `web/components/partners/group/PartnerGroupChat.tsx:104` ✓
  5. `web/components/settings/MinerUEngineSettings.tsx:187`（清理在 :215）✓
  6. `web/app/(workspace)/partners/[partnerId]/page.tsx:175` 三元条件 interval + 双监听成对摘除 ✓
  7. `web/components/partners/PartnerChat.tsx:905` focus/online/visibilitychange 全摘除 ✓
  8. `web/hooks/use-linger-expand.ts:46` ref 句柄 + 卸载 clear（初版误报，规则修正后排除）✓
  9. `web/shared/ui/Tooltip.tsx:78` 同上（初版误报，已排除）✓
  10. `web/lib/youtube-iframe-api.ts:64` `{ once: true }` 自摘除（初版误报，已排除）✓

## 复跑与确定性

```bash
# 在仓库根（本分支）执行；--rev/--subject 显式固定基线以获得逐字节一致的输出
python3 scripts/scan_web_timers.py --root . \
  --rev f07029cfcf2c8dfccdb671cdfc343db8334f5741 \
  --subject "release: v1.6.13" \
  --json evidence/web-timers-findings.json
```

- 本次交付的 JSON 即以该命令生成（扫描时 HEAD=f07029cfc）。同输入两次运行 diff 为空（已验证）。
- 结果排序稳定：`(file, line, rule, col)`；ID 按 `WT-%04d` 顺序编号。

## 扫描器局限（已注记）

1. 正则 + 括号配对的浅解析：字符串/注释已掩码消除误报，但 JS 正则字面量未识别（可能造成个别文件括号失衡 → 退化为漏报，不会误报）。
2. 句柄清理判定是文件级 identifier 匹配：同名句柄跨函数复用时可能互掩（全量 medium 复核已覆盖此风险，未发现实际漏报）。
3. 清理函数经由包装器间接 clear（如 `return stopFn;`）仅支持单层解析。
4. 未做数据流分析：`timerRef` 类句柄"有 clear 调用"不等于"clear 一定在卸载路径上"；这类条目靠人工复核把关。

## 交付物

- `scripts/scan_web_timers.py` — 扫描器（纯标准库）
- `evidence/web-timers-findings.json` — 机器可读全量条目（23 条）
- `evidence/web-timers-review.json` — 人工复核判定 + 阴性对照记录
- `evidence/SHA256SUMS` — 校验和
