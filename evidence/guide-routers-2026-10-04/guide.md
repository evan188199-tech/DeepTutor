# DeepTutor · deeptutor/api/routers 路由全景导读（AGEN-468）

- 基线：HKUDS/DeepTutor `origin/main` @ `ef2d9e5c3`（v1.6.12），只读导读，未修改任何产品代码。
- 行号均对照 `ef2d9e5c3`，与 `myfork:agent/dt22-todo-scan` 的 `evidence/todo-scan-2026-10-03/report.md` §7（同一 commit）可直接互查。
- 覆盖：`deeptutor/api/routers/` 全部 44 个文件（42 个含路由定义 + `__init__.py` + `_partners_channel_schema.py`）。
- 挂载总装在 `deeptutor/api/main.py`（下称 main.py），`include_router` 全表 main.py:574-788。

## 1. 一图速览

- 三种门：`_auth = [Depends(require_learning_surface)]`（main.py:591，内含 `require_auth`）、`_admin = [Depends(require_admin)]`（main.py:595）、无门公开路由。
- WebSocket 一律不挂 HTTP 依赖（`require_learning_surface` 需要 Request，WS scope 给不出，main.py:627-629 注释），改为 handler 内先 `ws_require_auth` 再 `accept`。
- 数据流主线：上传/重建索引路由（HTTP）→ BackgroundTasks 后台任务 → ProgressTracker 落盘快照 + TaskStreamManager 事件流 → WS/SSE 消费端。

## 2. 路由清单与挂载前缀

### 2.1 公开路由（无鉴权门）

| 前缀 | router | 位置 |
| --- | --- | --- |
| `/api/auth` | auth.router（登录/注册/状态，公开是刻意的） | main.py:575 |
| `/files/outputs` | outputs.router | main.py:576 |
| `/files/workspace-items` | workspace.files_router | main.py:577-581 |
| `/api/settings`（仅 public_router） | 登录页需先读 UI 语言，先挂抢占路径 | main.py:678-686 |
| `/api/marginnote4` | marginnote4.router；配对/管理路由在路由内挂 `_auth`，sync/heartbeat 用设备 token | main.py:774-780 |
| `/health/live` `/health/ready` | 直接定义在 app | main.py:796-804 |
| `/ws` 系全部 | 见 §4，handler 内自鉴权 | main.py:630-636,643,761-766,784,788 |

### 2.2 `_auth` 门（require_learning_surface → require_auth）

| 前缀 | 文件（router 定义） | 挂载位置 |
| --- | --- | --- |
| `/api/multi-user` | multi_user.py | main.py:597-602 |
| `/api/question` | question.router（仅壳，HTTP 路由 0 条） | main.py:603 |
| `/api`（`/api/knowledge-bases*` 全家） | knowledge.py:80 条 HTTP 路由 | main.py:604 |
| `/api/imports` | imports.py | main.py:611 |
| `/api/dashboard` | dashboard.py | main.py:612-614 |
| `/api/mastery-paths` | mastery_path.py | main.py:615-620 |
| `/files/library` | file_library.py | main.py:621-626 |
| `/api`（documents/notebooks/books/personas） | co_writer.py / notebook.py / book.py / personas.py | main.py:637,638,642,730 |
| `/api/task-board` | task_board.py | main.py:639-641 |
| `/api/reading`（×2） | reading.py + reading_extensions.py | main.py:644-650 |
| `/api/memory` | memory.py | main.py:651 |
| `/api/capabilities`（×2） | capabilities_settings.py + capabilities.py | main.py:652-663 |
| `/api/sessions` `/api/courses` | sessions.py / courses.py | main.py:664-665 |
| `/api/question-notebook`（+/practice） | question_notebook.py / practice.py | main.py:666-677 |
| `/api/settings`（正式 router）/`workspace`/`mcp` | settings.py / workspace.py / mcp_settings.py | main.py:687-693,700-705 |
| `/api/space/mcp` `/api/space/cli-apps` | space_mcp.py / space_cli_apps.py（管理面路由内自挂 admin） | main.py:706-725 |
| `/api/skills` `/api/subagents` `/api/tools` `/api/system` `/api/voice` | skills.py / subagents.py / tools.py / system.py / voice.py | main.py:726-733 |
| `/api/video-learning` `/api/visualizers` `/api/agent-config` | video_learning.py / visualizers.py / agent_config.py | main.py:734-748 |
| `/api/partners` `/api/partner-groups` `/files/attachments` | partners.py / partner_groups.py / attachments.py | main.py:754-772 |

### 2.3 特殊门

- `_admin`：`/api/settings/video-learning`（main.py:694-699）；路由内自挂 `Depends(require_admin)`：lightrag 写配置 knowledge.py:1698、weknora 探测/连接 knowledge.py:2407,2427、kiwix knowledge.py:2565,2582,2595。
- 仅 `require_auth`（无 learner surface 二级门）：`/api/file-preview`（main.py:605-610）。
- 每条路由自声明 use/manage 权限：partners（main.py:749-754，见 `multi_user.partner_access`）。

## 3. 公共鉴权依赖：current_user / reset_current_user 模式

- ContextVar 核心 `deeptutor/multi_user/context.py:11-27`：`set_current_user` 返回 Token，`reset_current_user(token)` 复位（context.py:14-19）；`get_current_user()` 未认证时回退 `local_admin_user()`（context.py:23）——单机模式全靠这个回退。
- HTTP 门 `require_auth`（auth.py:419-469）：token 取 `Authorization: Bearer` 或 `dt_token` cookie（`_extract_token` auth.py:389-390）；`AUTH_ENABLED=false` 时装本地 admin 并放行（auth.py:446-449）；否则缺 token/无效 token 均 401 + `WWW-Authenticate`（auth.py:452-457,460-465）。
- 为什么必须 `async def`：sync 依赖被丢进 worker 线程、上下文是拷贝，`ContextVar.set` 随线程返回丢弃——这是 #481「静默落到 admin 工作区」的根因（auth.py:438-444 注释）。
- 唯一装填点 `_install_current_user`（auth.py:398-416）：payload→CurrentUser 单一出口；不变量「每个已认证入口必须先调它」（auth.py:411-413）。
- workspace 作用域 `_install_request_workspace`（auth.py:472-525）：`x-deeptutor-workspace` 头 / `dt_workspace` 查询参数，两者冲突 400（auth.py:480-481）；归档工作区拒绝写操作 404（auth.py:511-516）；管理路径（/api/settings、/api/auth、/api/multi-user）不接外部 scope 且自带活动租约（auth.py:499-523）。
- 二级门 `require_learning_surface`（auth.py:641-645）：按路径把请求归类 reading/chat surface（映射表 auth.py:610-638），learner 受限账号默认拒绝；KB 只读白名单 auth.py:597-607。
- `require_admin`（auth.py:573-594）：非 admin 403；AUTH_ENABLED=false 视为 admin。
- WS 版 `ws_require_auth`（auth.py:535-569）：必须在 `accept` **之前**调用；token 取查询参数 `token` 或 cookie（auth.py:558）；无效 close(4001)，workspace 失败 close(4004)；返回 `ws_auth_failed` 哨兵（auth.py:528-532），调用方看到哨兵直接 return。
- 配对纪律：HTTP 端请求结束上下文自动回收，可忽略 Token；WS 端连接活得比依赖解析任务久，**必须**在 `finally` 里 `reset_current_user(user_token)`（auth.py:545-554 docstring 样板）。
- 后台任务再绑定：`run_upload_processing_task` 若 `owner` 与当前不同，`set_current_user(owner)` 后递归自调、`finally` 复位（knowledge.py:1137-1152）；`run_reindex_task` 同构（knowledge.py:3699-3713）；workspace 侧用 `workspace_context` + `library_request` 再绑定（knowledge.py:1154-1172,3715-3732）。

## 4. WebSocket 路由生命周期（连接 → 任务 → 清理样板）

9 个端点：

| 端点（完整路径） | handler | 挂载 |
| --- | --- | --- |
| `/ws/questions/mimic` | question.py:49 | main.py:630 |
| `/ws/questions/generate` | question.py:359 | main.py:630 |
| `/ws/knowledge-bases/{kb_name}/progress` | knowledge.py:4219 | main.py:631 |
| `/ws/mastery-paths` | mastery_path.py:771 | main.py:632-636 |
| `/ws/books` | book.py:1519 | main.py:643 |
| `/ws/partners/{partner_id}` | partners.py:1764 | main.py:761 |
| `/ws/partner-groups/{group_id}` | partner_groups.py:338 | main.py:762-766 |
| `/ws`（统一会话/任务流） | unified_ws.py:43 | main.py:784 |
| `/ws/questions/judge` | quiz_judge.py:226 | main.py:788（prefix /ws） |

标准样板 5 步（`quiz_judge.py:263-267`、`knowledge.py:4225-4229`）：

1. `user_token = await ws_require_auth(ws)`；失败（`ws_auth_failed`）直接 return——连接从未 accept，升级被拒。
2. `await ws.accept()`。
3. 任务段：订阅广播 / 推流 / 流式生成。
4. `except WebSocketDisconnect: 正常收尾`；`except Exception` 尽力发一帧 error 再收尾。
5. `finally`：断开订阅/`broadcaster.disconnect` + `ws.close()` + `reset_current_user(user_token)`。

三种任务模型：

- **广播订阅型**（进度）：`ProgressBroadcaster.get_instance().connect(key, ws)`（knowledge.py:4231-4245），主循环 `asyncio.wait_for(receive_text, 1.0)` 当心跳，超时则拉 ProgressTracker 快照比对 timestamp 推增量（knowledge.py:4410-4429）。重连语义：带 `task_id` 重连时终态快照必重放（knowledge.py:4262-4266），进程重启后的孤儿任务转成可重试错误 `knowledge_task_interrupted`（knowledge.py:4268-4311）。
- **多订阅管理型**（unified_ws）：`subscription_tasks: dict`，`stop_subscription` 取消并 `await` 吞 CancelledError（unified_ws.py:130-138）；`safe_send` 用 `closed` 标志一次失败后全静默（unified_ws.py:65-73）。
- **流式生成型**（question/quiz_judge/partners/book）：`log_queue` + `pusher_task` 把工作线程日志经 `loop.call_soon_threadsafe` 推回前端（question.py:97-113）；`StdoutInterceptor` tee stdout（先写终端再剥 ANSI 进队列，question.py:119-158）；`safe_send` 返回 bool（quiz_judge.py:269-274）。

清理段注意：`finally` 里 `close()`/`reset_current_user` 常被 `except Exception: pass` 包裹（knowledge.py:4484-4492、quiz_judge.py:282-304 等）——索引见 §6；`except CancelledError: pass` 属取消语义的有意写法（question.py:334,564、unified_ws.py:137、book.py:1514 附近 await task）。

## 5. 上传/进度类路由数据流（knowledge.py 主轴）

上传 `POST /api/knowledge-bases/{kb_name}/upload`（knowledge.py:3275）：

1. 门与校验：`_writable_kb` 解析可写 KB（knowledge.py:3297）；KB 锁定创建时引擎，传参不一致 400（knowledge.py:3310-3317）；embedding 绑定 missing/changed/unconfigured 一律 409（knowledge.py:3323-3328）；批校验 + 冻结索引快照（knowledge.py:3331-3344）。
2. 落盘：`_save_uploaded_files_off_loop` 把整段阻塞写放 worker 线程（knowledge.py:548-559，调用 knowledge.py:3345-3351）→ `_save_uploaded_files`（knowledge.py:416-545）：`DocumentValidator.validate_upload_safety` 前置校验（knowledge.py:444-448）；目录上传保留相对路径、`dest_subdir` 归位批次（knowledge.py:451-468，#866）；zip 解包按成员注册（knowledge.py:470-488）；边写边限大小（knowledge.py:494-507）；PocketBase 镜像 best-effort 只 debug 级（knowledge.py:516-525）；单文件失败删半成品并 400（knowledge.py:526-535），整批失败回滚全部（knowledge.py:536-543）。
3. 任务登记：`_build_unique_task_id` + `ensure_task`（knowledge.py:3352-3353）；`_mark_kb_queued_for_processing` 先把 KB 标成排队（knowledge.py:3357-3362）。
4. 后台处理：`BackgroundTasks.add_task(run_upload_processing_task)`（knowledge.py:3364-3374）→ knowledge.py:1113-1262：owner/workspace 再绑定（§3）；staging 走 `asyncio.to_thread`（async 后台任务其实跑在事件循环上，会卡住全部请求——#777，knowledge.py:1212-1222）；`DocumentAdder` 增量入库；`capture_task_logs` 收任务日志（knowledge.py:1182）。
5. 进度双轨：ProgressTracker 落盘快照（knowledge.py:1179-1180；stages 更新 knowledge.py:1196-1230）+ `get_task_stream_manager()` 事件流（`emit_complete`/`emit_failed`，knowledge.py:1254-1256,3954）。
6. 消费端：`/ws/knowledge-bases/{kb}/progress`（§4 广播订阅型）与 unified_ws 的 task 订阅；两边共享 task_id/终态元数据，保证刷新/重连能收敛到终态。

重建索引 `POST /api/knowledge-bases/{kb_name}/reindex`（knowledge.py:3973）→ `run_reindex_task`（knowledge.py:3682-3954）：模型快照随任务走、成功才发布新绑定，失败保留旧索引与版本（knowledge.py:3695-3697）；失败路径写任务 error + 进度 error + emit_failed（knowledge.py:3941-3954）；已发布后的收尾异常按完成记账（knowledge.py:3930-3940）。

失败模式小结：上传侧静默点集中在回滚 unlink（knowledge.py:530,541）与链接文件夹 mtime 快照（knowledge.py:1189-1194）；进度侧集中在广播/关闭/重置三连吞（AGEN-135 已认领，见 §6）。

## 6. 吞错位置与修复/测试卡索引（routers 内）

### 6.1 已认领（修复卡在途，均 in_review）

| 位置 | 说明 | 级别 | 认领卡 |
| --- | --- | --- | --- |
| knowledge.py:3952 | `run_reindex_task` 失败告警本身被吞（HIGH） | HIGH | AGEN-268 合集 → AGEN-301 分支 `pr/knowledge-surface-swallowed-failures-v2`（diff 实测覆盖 3952/4353/4402/4480/4486/4491 + manager.py `update_kb_status`，附 tests/api/test_knowledge_progress_ws.py） |
| knowledge.py:4353/4402/4480/4486/4491 | `websocket_progress` 时间解析、error 帧、close、reset 五连吞 | HIGH | AGEN-135（同上合集分支） |
| quiz_judge.py:284/289/298/303/390/395/454/459 | `websocket_quiz_judge` teardown 八处 pass | MEDIUM | AGEN-280（幂等清理重构） |
| settings.py:518 | `load_ui_settings` 文件损坏即静默回默认 | MEDIUM | AGEN-154 修复 + AGEN-420 补测 |

### 6.2 测试卡已认领、修复卡未开

| 位置 | 说明 | 级别 | 测试卡 |
| --- | --- | --- | --- |
| question.py:131/146/153 | `StdoutInterceptor` tee 终端/队列/flush 三处吞 | HIGH | AGEN-355、AGEN-433（返工 AGEN-459）；修复卡未开 |
| question.py:306/336/343/349/355、385/438/505/577 | 两个生成 WS 的清理段吞错（334/564 的 CancelledError 除外，有意） | MEDIUM | 同上 |

### 6.3 未认领（截至 2026-10-04 检索，未找到对应修复卡）

- MEDIUM：partners.py:546/553（`_load_persona_markdown` 静默降级）、partners.py:2019（chat ws reset 吞）、partner_groups.py:530（group ws reset 吞）、memory.py:703（`clear_trace` unlink continue）、settings.py:2247（tour_status 缓存读吞）、reading.py:518（URL 解析 continue，注释标明有意）、workspace.py:322（resolve continue）、knowledge.py:530/541（回滚 unlink OSError pass）、knowledge.py:1189-1194（mtime 快照 OSError pass）。
- LOW（多为回退/遍历跳过语义，可接受）：knowledge.py:3048、settings.py:1187/2336、book.py:1514/1812、multi_user.py:172、auth.py:121、personas.py:91/102、skills.py:205、unified_ws.py:137。

### 6.4 卡片状态速查（2026-10-04）

- 修复 in_review：AGEN-135、AGEN-136（manager.py，非 routers）、AGEN-154、AGEN-155（progress_tracker，非 routers）、AGEN-280。
- 合集分支已备 in_review：AGEN-268（→AGEN-301 知识库面）、AGEN-302（runtime 面）、AGEN-304（RAG 面）；对应 myfork `pr/*` 分支已被开放 PR 占用，勿再推送。
- 测试 in_review：AGEN-354（KB 进度 WS 错误路径）、AGEN-355/433/459（question tee/ws）、AGEN-420（settings 回退）、AGEN-441/475（learning records 鉴权依赖契约测试）。

## 7. 复核入口

- 挂载总表：`rg -n 'include_router' deeptutor/api/main.py`
- WS 样板一览：`rg -n 'ws_require_auth' deeptutor/api/routers/`
- 吞错复扫脚本：`myfork:agent/dt22-todo-scan` → `evidence/todo-scan-2026-10-03/scan_py_swallow.py`
- 上游关联 issue：#1612（进度真实性，本目录多处置换相关）、#1678（搜索降级）；上游无「吞错清理」类开放 PR/issue 撞车（DT-22 §3 已检索）。
