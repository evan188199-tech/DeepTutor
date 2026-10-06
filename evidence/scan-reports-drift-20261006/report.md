# 八份 20261004/05 扫描报告相对最新 main 的结论复核（只读，未改任何代码）

- 卡：AGEN-819 · 复核日期：2026-10-06 · 基线（复核对象）：origin/main `f07029cfc`（release v1.6.13）
- 复核基线：`git fetch origin` 后 `ls-remote` 确认上游 main HEAD 仍为 `f07029cfcf2c8dfccdb671cdfc343db8334f5741`，与八份报告的扫描基线**完全相同**（上游 main 自 2026-10-04 21:35 v1.6.13 后零移动）。
- 结论预览：**PASS** —— 八份报告的 HIGH/MEDIUM 条目在最新 main 上**全部仍成立**，无任何条目被后续合并修复（main 无新 commit，引用的 15 个上游 PR 全部仍 open）。两份带扫描脚本的报告（datetime-naive、lock-usage）重跑脚本输出与原证据**完全一致**（datetime 逐字节一致；lock 1005 锁构造 + 314 临界区 canonical 一致）。**一处实质性修正**：coverage-gaps 的扫描器存在哈希种子非确定性，其"零测试"总量与 Top15 中 8 个条目的前提不成立（详见 §5）。另记录 1 个新上游变数：PR #1783 与 lock-usage H4、web-route-guards F5/F6/F7 重叠（open，未合并）。
- 去重：datetime 报告中标注 DT-22 的条目（L1#1/#2、L2#2/#3、knowledge.py:1193 视角）归 `verify-dt22-drift`（DT-22 专卡），本卡只确认引用行号在基线上仍有效，不重复展开。

## 0. 全局核对

| 检查项 | 结果 |
|---|---|
| 上游 main 是否前移 | 否（`ls-remote origin main` = `f07029cfc`，与扫描基线同 commit）→ 不存在"已被合并 PR 修复"的条目 |
| 引用上游 PR 状态 | #1751、#620、#1749–#1778 全部仍 OPEN（无一合并）|
| 引用上游 issue 状态 | #1779（lock H4）、#1228、#1222（web-guards）仍 OPEN |
| 新增重叠上游 PR | **#1783**（2026-10-05 open）"fix: embedding concurrency, local Lemonade, reading fences, and learner nav"：声称 Fixes #1779 + #1222，触及 `services/embedding/client.py`、`api/routers/auth.py`、`web/components/sidebar/{SidebarNav.tsx,nav-entries.ts}`、`web/hooks/useAuthStatus.ts` —— 与 lock-usage H4、web-route-guards F5/F6/F7 直接重叠，尚未合并；相关修复卡领取前须先看其走向 |
| 锚点抽查 | 114 个 path:line 锚点（覆盖八份报告全部 HIGH/MEDIUM）逐一比对：全部命中（其中 8 处报告行号有 1–6 行的引用偏差，见各报告小节"行号修正"）|

## 1. datetime-naive-20261005 —— 仍成立（零漂移）

验证方式：从 `myfork/scan/datetime-naive-20261005` 取 `scan_datetime.py` 对本基线重跑，输出与原证据 `datetime_scan.json` **规范化后完全一致**（347 调用点 / 97 文件 / 1 处混用比较点 knowledge.py:4387）。

| 条目 | 分级 | 状态 | 现行位置 |
|---|---|---|---|
| L1#1 knowledge.py 进度年龄比较吞 TypeError | HIGH | 仍成立（DT-22 专卡）| `deeptutor/api/routers/knowledge.py:4387` |
| L1#2 第二处进度新鲜度比较 | HIGH | 仍成立（DT-22 专卡）| `knowledge.py:4433`（比较点 :4435）|
| L1#3 `_entry_updated_after` 只捕 ValueError | MEDIUM | 仍成立 | `deeptutor/knowledge/manager.py:104`（cutoff :690）|
| L1#4 linked-folder mtime naive/naive 跨时区误判 | MEDIUM | 仍成立 | `manager.py:2145-2146`（:2139/:2213-2215、`knowledge.py:1190`）|
| L1#5 base_sync staleness naive 按 UTC 解读 | MEDIUM-LOW | 仍成立 | `deeptutor/services/base_sync.py:32`（写方 `web_source/sync.py:46`、`github_source/sync.py:35` 一致）|
| L2#1 mochat 剥 Z 写 / 本地读 | HIGH | 仍成立 | `deeptutor/partners/channels/mochat.py:118`、`:1013`（读 `:222`）|
| L2#2 snapshot `_iso` 字符串透传 | MEDIUM | 仍成立（DT-22 专卡）| `deeptutor/services/memory/snapshot/adapters.py:49`（数值分支 :56 无险）|
| L2#3 pocketbase `_to_float` naive→epoch | MEDIUM-LOW | 仍成立（DT-22 专卡）| `deeptutor/services/session/pocketbase_store.py:98` |
| L3#1 naive 本地时间入库写点群（判定链根因）| MEDIUM | 仍成立 | knowledge.py 8 写点、task_id_manager.py:60/:78、manager.py 7 写点、add_documents.py:497/:569、initializer.py:105 全部原位 |

修复卡建议（卡①–⑦）维持原优先级；上游无 datetime/时区相关 open PR。

## 2. lock-usage-20261005 —— 仍成立（零漂移）＋1 个上游变数

验证方式：`scan_locks.py`/`scan_regions.py` 重跑，与原 `raw-ast.json`（1005 条锁构造）和 `lock-regions.json`（314 临界区 / 230 interesting）**canonical 一致**（仅扫描器对 `dict.get` 标签与同体内调用顺序存在非确定性噪声，文件/行号/锁名全同）。

| 条目 | 分级 | 状态 | 抽查锚点（全部命中）|
|---|---|---|---|
| H1 codebuddy 全局 env-key 锁跨流式 turn | HIGH | 仍成立 | `provider_core/codebuddy_provider.py:27`（锁定义）、`:771`（async with）、`:267`（锁内 sdk.query）、`:166` |
| H2 progress_broadcaster 全局锁 + 逐个 send_json | HIGH | 仍成立 | `api/utils/progress_broadcaster.py:19`、`:58` |
| H3 channel_onboarding 全局锁 + 外呼 | HIGH | 仍成立 | `services/partners/channel_onboarding.py:155`、`:172` |
| H4 embedding 全局 spacing 锁 `[up-1779]` | HIGH | 仍成立；**#1779 仍 open，但新 PR #1783（open）声称修复**（batch_delay=0 跳锁）| `services/embedding/client.py:44-59`（双检）、`:61-73`（50ms 轮询获取 :68-69）、`:156-160`（锁内 sleep :158 + embed :160）|
| M1 sqlite_store 单锁全串行 | MED | 仍成立 | `services/session/sqlite_store.py:1100-1102` |
| M2 事件循环线程同步 I/O + 全局锁（11 组链）| MED | 仍成立 | courses.py:329、catalog_store.py:63、video_learning/service.py（flock 实际 **:392**，报告写 :390，+2）、identity.py:35 等全命中 |
| M3 codebuddy_auth 锁内探测/子进程 | MED | 仍成立 | `services/codebuddy_auth.py:13`、`:31-37` |
| M4 opencode_server 池锁跨 spawn | MED | 仍成立 | `services/subagent/opencode_server.py:69`、`:68-96` |
| M5 mcp/manager SHARED_OWNER 锁跨全量连接 | MED | 仍成立 | `services/mcp/manager.py:270-276`（:280-283 reload）|
| M6 单飞类锁内网络（codex_auth/app_update/sandbox）| MED-LOW | 仍成立 | `services/codex_auth/service.py:722-742` 区段命中 |

处置建议：H4 相关修复评审必须与 #1783 合并节奏协调（#1783 未覆盖其指出的轮询获取与锁内 sleep 两点是否一并处理，待其合并后复核）；H1/H2/H3、M1–M6 无上游动作，可照原拆卡领取。

## 3. atomic-write-20261005 —— 仍成立（修复载体 PR 未合并）

| 条目 | 分级 | 状态 | 现行位置/说明 |
|---|---|---|---|
| H1 file_io 吞 fsync（约 48 文件引用）| HIGH | 仍成立；修复载体 **PR #1751 仍 open 未合并** | `services/file_io.py:53-55`、`:78-80`（`except OSError: pass` 原位）|
| H2 rename 后无目录 fsync（系统性）| HIGH | 仍成立（复跑 `O_DIRECTORY\|dirfd` 全仓 0 命中）| 代表点 `utils/config_manager.py:88`、`settings_draft.py:104`、`model_catalog.py:313`、`mcp/config.py:149` 全原位 |
| M1 attachment_store 无 fsync + 固定名 tmp | MED | 仍成立 | `services/storage/attachment_store.py:179-190` |
| M2 file_library 同模式 | MED | 仍成立 | `services/storage/file_library.py:175-189`（报告 :176-187，范围 ±2）|
| M3 worker_process 无 fsync 无 finally | MED | 仍成立 | `runtime/worker_process.py:53-58`（write :56 / replace :57）|
| M4 memory snapshot save_state 三缺 | MED | 仍成立 | `services/memory/snapshot/store.py:62-71`（write :70 / replace :71）|
| M5 tex_downloader 失败路径残留 | MED | 仍成立 | `tools/tex_downloader.py:87`（mkdtemp）、:131-135（两分支直接 return）|
| M6 mineru attempt 目录无回收 | MED | 仍成立 | `services/parsing/engines/mineru/local.py:200`、`:321-330` |
| M7 reading store 目录交换无 fsync | MED | 仍成立 | `reading/store.py:426-436` 等四处原位 |

注：全仓 `os.replace` 现数 40（报告 41，±1，属统计口径差）；`detail=str(` 类计数不受影响。#620（kb-config atomic store）仍 open。修复卡建议（fix-atomic-fsync-extend / residue / unique-tmp / dir-fsync / mineru-gc）维持。

## 4. error-messages-20261004 —— 仍成立

Top15 逐条锚点复核（全部命中；行号引用偏差 2 处）：

| 条目 | 状态 | 现行位置 |
|---|---|---|
| T1 `/knowledge-bases/health` 泄漏 traceback | 仍成立 | `api/routers/knowledge.py:1403`（`"traceback": traceback.format_exc()` 逐字在）|
| T2 62 处 blanket-500 `str(e)` | 仍成立 | book.py:834、co_writer.py:546 等原位；全 routers `detail=str(` 现 249 处，与报告一致 |
| T3 client.ts 原样透传 detail | 仍成立 | `web/shared/api/client.ts:217`（`String(body.detail)`）、`:38-46` |
| T4 聊天流 `content=str(exc)` | 仍成立 | `services/session/turns/executor.py:1349` |
| T5 runtime.py 类名进用户回复 | 仍成立 | `services/partners/runtime.py:623`（→ :417）|
| T6 供应商 body 拼异常 | 仍成立 | `services/generation_http.py:81-85`（报告 :82，-1）；voice/search providers 原位 |
| T7 `format_exception_message` 不脱敏 | 仍成立 | `utils/error_utils.py:46` |
| T8 pydantic ValidationError 全文 | 仍成立 | book.py:857（"Invalid proposal: {exc}" 逐字）、:888；mastery_path.py:80 |
| T9 `LLMAPIError(str(exc))` | 仍成立 | `services/llm/error_mapping.py:174`（报告 :170，+4）|
| T10 notebook ×12 blanket-500 | 仍成立 | :206/:223/:248/:272/:303/:327/:362/:397/:425/:441/:457/:477 全原位 |
| T11 PermissionError 路径 → 403 | 仍成立 | `reading_extensions.py:157` 等 4 处 |
| T12 practice/question 路径泄漏 | 仍成立 | practice.py:338、question.py:320（format_exception_message WS 下发）|
| T13 LANG-MIX（tool-availability 硬编码中文等）| 仍成立 | `web/lib/tool-availability.ts:26` 起 5 处中文逐字在 |
| T14/T15 NO-CODE / not_found 话术分裂 | 仍成立（系统性）| auth.py:828 "Incorrect email or password" vs :846 "Incorrect username or password" 两套文案原位 |

无上游修复 PR；三条单点收敛建议（error_utils 脱敏、全局 handler、client.ts 映射层）维持。

## 5. coverage-gaps-20261005 —— 总体成立，但发现**扫描器非确定性**，Top15 前提 8/15 需修正

这是本次复核唯一的实质性修正，分三点：

**5.1 稳定部分**：总量 1029 模块 / 751 测试文件 / 874 非 init 模块复跑一致；§4 断言强度抽样（napcat/msteams 中位 1 断言、两位数零断言用例）不依赖该扫描器，仍成立。

**5.2 扫描器缺陷（新发现）**：`scan_coverage_gaps.py` 的 T2 匹配含 `" ".join(set)` 子串路径与 set 迭代，受 `PYTHONHASHSEED` 影响：同 seed 两次运行完全一致，异 seed 约 **58 个模块**的 covered 分类翻转（实测 seed0 vs seed1）。原报告的"零测试 141 / 弱测试 235"是单次种子抽签值（本机 seed0 重跑得 140/229），不能作为稳定事实引用。

**5.3 Top15 逐条 ground-truth 重验**（绕开原扫描器，对全部 751 个测试文件做确定性 AST 精确 import 匹配，基线同一 commit）：

| # | 模块 | 报告判定 | 重验结论 |
|---|---|---|---|
| 1 | session/turns/executor.py | 零测试 | **成立**（0 直连测试）|
| 2 | session/turns/request_preparer.py | 零测试 | **成立**（0）|
| 3 | partners/channels/mochat.py | 零测试 | **成立**（0）|
| 4 | services/voice/speech_text.py | 零测试 | **成立**（0）|
| 5 | api/routers/question_notebook.py | 路由契约零测试 | **前提不成立**：`tests/api/test_practice.py` 直连（1）|
| 6 | api/routers/reading_extensions.py | 路由零测试 | **前提不成立**：7 个直连测试（如 `tests/api/test_learning_policy_http.py`）|
| 7 | api/routers/space_mcp.py | 路由零测试 | **前提不成立**：`tests/api/test_space_mcp.py` 专测存在 |
| 8 | partners/channels/dingtalk.py | 零测试 | **成立**（0）|
| 9 | memory/consolidator/modes/audit（+dedup/_runtime "三 mode 全零"）| 零测试 | **前提不成立**：`tests/services/memory/test_modes.py` 同时直连 audit/dedup/update 三 mode |
| 10 | multi_user/model_access.py | 零测试 | **前提不成立**：3 个直连测试（`test_capability_access.py:8` 等）|
| 11 | services/pocketbase_client.py | 零测试 | **成立**（0；与 PR #1773 覆盖的 pocketbase_store 确为不同文件）|
| 12 | services/rag/embedding_binding.py | 零测试 | **前提不成立**：2 个直连测试（`test_embedding_binding.py` 等）|
| 13 | services/reading_hints.py | 零直测 | **前提不成立**：`tests/reading/test_reading_hints.py:9` 直连 |
| 14 | api/routers/video_learning.py | 路由零测试 | **前提不成立**：4 个直连测试（`test_http_scope.py` 等）|
| 15 | tools/vision/coord_transform.py | 零测试 | **成立**（0）|

处置建议：① #1/#2/#3/#4/#8/#11/#15 七张补测卡可按原样领取；② #5/#6/#7/#9/#10/#12/#13/#14 八张须改写为"断言强度增强 / 失败分支契约补齐"（存在测试 ≠ 分支覆盖，原报告自己的口径注记也支持这一改法），不应再以"零测试"立项；③ 领卡前先把 `scan_coverage_gaps.py` 改为确定性实现（消除 set 迭代/子串拼接匹配）重新生成 coverage_raw/summary。

## 6. channel-contracts-20261005 —— 仍成立

P0/P1 锚点逐条复核（全部命中）：

| 条目 | 分级 | 状态 | 抽查锚点 |
|---|---|---|---|
| P0-1 send 永不抛 → manager 重试失效（feishu/mochat/dingtalk/zulip）| P0 | 仍成立 | feishu.py:2322-2323、mochat.py:409-410、dingtalk.py:498-517（token 静默 return :501-502、文本结果忽略 :505）、zulip.py:749-750 与 :783-785（仅 logger.error）、:194 注释"Raise on delivery failure"与实现矛盾（逐字在）|
| P0-2 weixin stop 未启动也覆写 account.json | P0 | 仍成立 | weixin.py:401 无条件 `_save_state()`（→:235-245）|
| P0-3 discord send_delta 仅按 chat_id 键控 | P0 | 仍成立 | discord.py:68、`:199-222`；契约 `base.py:178`（`_stream_id`）与 `:162-164`（send 抛错要求）原位 |
| P1-4 16/16 无双重启动防护 | P1 | 仍成立（结构性）| — |
| P1-5 stop 清理缺口 | P1 | 仍成立 | feishu.py:509（keep-alive 安装点）、`:522-529`（client 构建，无 close）；slack.py:92（AsyncWebClient）；dingtalk.py:194（`await self._client.start()` 无界）|
| P1-7 事件循环阻塞 | P1 | 仍成立 | zulip.py:134（同步鉴权 `_call_with_retry(get_profile)`）、msteams.py:247-258（shutdown/join，报告 :251-255 ±2）、weixin.py:944-945（not-running raise，佐证 P2-11）|
| P1-8 qq/wecom 易失状态 | P1 | 仍成立 | qq.py:160（c2c 兜底）、wecom.py:382-385（frame 缺失静默丢）|
| 去重前提 | — | 复现确认 | `myfork/pr/channels-idempotent-close` @ `9ed551c71` 与 `myfork/test/mochat-channel-20261005` @ `a47de7561` 均仍在、**均未进 main**（napcat/qq 无 `aclose_quietly`）→ 报告中"AGEN-493 已覆盖"的条目在 main 上原始"吞"仍存在，其修复卡依赖 493 先落地 |

上游无相关 open PR；卡 A–M 维持。

## 7. env-config-drift-20261005 —— 仍成立（2 处行号修正）

| 条目 | 分级 | 状态 | 现行位置 |
|---|---|---|---|
| A：settings.py docstring 默认值与 Field 不一致 | 高（文档漂移）| 仍成立 | docstring 实际 **:6-7**（报告 :8-9，-2）；Field 实际 **:21-22**（报告 :23-24，-2）：docstring `default: 3 / 1.0` vs `Field(default=8 / 5.0)` 逐字确认 |
| B1′：MINERU_×9 + TIKA 未文档化 | 高 | 仍成立 | `services/config/runtime_settings.py:926-942`（926/928/930/932/934/936/938/940/942 逐键命中）、`:1211`（TIKA_SERVER_URL）|
| B1 用户面 50 键（抽样）| 中 | 仍成立 | init_wizard.py:148/155/162/169/176/183/190/200/207/214/221/228、codebuddy_provider.py:26、launch_settings.py:94（UI_LANGUAGE）、runtime_settings.py:869-879/915-919 抽样全命中 |
| B2 运维面 55 键（抽样）| 中 | 仍成立 | runtime_settings.py:725（AUTH_COOKIE_SECURE）、data_volume.py:149（PUID）等命中 |
| C：三组命名/别名漂移 | 中 | 仍成立 | runtime_settings.py:850（PUBLIC_API_BASE）、`:863`（DEEPTUTOR_BACKEND_WORKERS 双读）、`:727+:887`（鉴权三名）|

七张 docs/refactor 拆卡建议维持。

## 8. web-route-guards-20261005 —— 仍成立 ＋1 个上游变数（PR #1783）

F1–F7 全部锚点复核（逐条命中；2 处行号修正）：

| 条目 | 分级 | 状态 | 现行位置 |
|---|---|---|---|
| F1 默认 learner 授权无 books，UI 却作首入口 | 高 | 仍成立 | `multi_user/grants.py:206`（`["chat","reading"]` 逐字，无 books）、`auth.py:641-642`（/api/books→books 面）、`web/features/multi-user/types.ts:25` + `GrantEditor.tsx:46`（二元面逐字）、`surfaces.ts:25-26`（LEARNING_SURFACES 首卡 books；报告 :20-42，±5）|
| F2 learning-index 未入白名单 | 高 | 仍成立 | `LearningDashboard.tsx:52-57`（:54 `!response.ok` throw、:57 catch 全记失败）+ :76（30s 轮询）；`auth.py:638-640` 白名单仅 materials/reading/books |
| F3 watching 未入白名单 | 高 | 仍成立 | `learning-library.ts:11-13`（throw）、`ActivityLibrary.tsx:37`（显式错误态，非伪装）|
| F4 403 空态伪装 5 处 | 中 | 仍成立（逐处）| partners/page.tsx:49-50、ConnectedAgents.tsx:55、SpaceDashboard.tsx:296-298（注释自认）、MemoryHub.tsx:62（overview 无 res.ok 检查）+ :68 catch→0、StarterSuggestions.tsx:97（`!response.ok → null`）|
| F5 能力探针 403 早退保持乐观态 | 中 | 仍成立 | `CapabilityAccessContext.tsx:54-55`（useState(true)×2）、`:61-62`（fetch /api/settings + `if (!res.ok) return;`）|
| F6 llm-options 白名单缺失 | 中 | 仍成立 | `settings.py:896-898`（"Non-admins never see the catalog … grant-filtered" 注释逐字在，端点仍挂面守卫组 main.py:688）；`llm-options.ts:63-64` throw（报告 :69-72，-6）|
| F7 设置页可见性模型不对应 | 中 | 仍成立 | `settings-access.ts:22-40`（hideAdminOnly/learnerOnly 原位）；main.py:575 auth 公开、:606-610 file_preview、:688 settings 挂 `_auth`、:767-772 attachments 挂 `_auth` |

上游变数：**PR #1783（open）声称 Fixes #1222**——按 `learning_policy.allowed_surfaces` 隐藏 sidebar 入口（改 SidebarNav/nav-entries/useAuthStatus）并把 `/api/settings/llm-options` 映射进 chat 面。若合并：F5/F6 大部分缓解、F7 导航可见性部分缓解；但 **F1（books 默认授权）、F2（learning-index 白名单）、F3（watching）、F4（五处空态伪装；#1783 文件清单不含 partners/page.tsx、SpaceDashboard、MemoryHub、StarterSuggestions）不在其范围**。修卡领取前先确认 #1783 走向，避免撞车。

## 9. 复核方法与命令

```
# 基线确认
git -C /Users/Shared/DeepTutor fetch origin main && git ls-remote origin main   # = f07029cfc（与扫描基线同）
git -C /Users/Shared/DeepTutor worktree add dt-agen819-drift-wt -b scan/reports-drift-20261006 f07029cfc

# 脚本级复跑（datetime / lock / coverage）
python3 scan_datetime.py <worktree>/deeptutor        # 与原 datetime_scan.json 规范化后完全一致
python3 scan_locks.py && python3 scan_regions.py     # 1005 锁构造 / 314 临界区 / 230 interesting，canonical 一致
PYTHONHASHSEED=<s> python3 scan_coverage_gaps.py     # 同 seed 稳定、异 seed ~58 模块翻转 → 扫描器非确定性（§5.2）

# 上游状态
gh pr list -R HKUDS/DeepTutor --author @me --state open   # 本卡分支不在其中；#1751/#620/#1749-1778 全 open
gh pr view 1783 -R HKUDS/DeepTutor                        # 新增重叠 PR（embedding 并发 + learner nav）

# 锚点抽查：114 个 path:line（覆盖八报告全部 HIGH/MEDIUM）逐行正则比对，全部命中（8 处 ±1~6 行引用偏差已在上文标注）
```

## 10. 边界遵守

- 全程只读：未改任何产品代码；本分支仅新增本 evidence 目录。
- 未启动服务器/守护进程；扫描脚本均为前台短时运行；本运行无遗留子进程。
- 未向上游开 PR、未评论 issue/PR；未推送 main/dev 或任何已被开放 PR 使用的分支。
