# 运行时启动器生命周期导读（launcher / update_worker / init）

- 基线：origin/main `f07029cfc`（v1.6.13）。所有 `path:line` 均基于该基线，行号会随演进漂移，以符号名为准。
- 范围：`deeptutor start` 的前台/分离启动、端口治理、前端运行时解析与构建标记、更新交接与进程树终止、`deeptutor init` 的 home 切换。
- 去重说明：版本解析与 About 更新入口见 guide-app-update；部署形态（systemd/docker）见 guide-deploy；更新任务状态机与 job store 细节另见 `myfork/docs/guides/runtime-update-chain`（evidence/guide-runtime-2026-10-04/guide.md）。本文只覆盖启动器生命周期本身。

## 1. 参与者与关键文件

| 角色 | 文件 | 关键符号 |
| --- | --- | --- |
| CLI 入口 | `deeptutor_cli/main.py:128-159` | `start` / `stop` 命令，转调 launcher |
| 启动器主体 | `deeptutor/runtime/launcher.py:1278-1588` | `start()` |
| home 解析 | `deeptutor/runtime/home.py:28-43` | `get_runtime_home`（参数 > `DEEPTUTOR_HOME` > cwd） |
| home 校验 | `deeptutor/runtime/home.py:12-25` | `validate_runtime_home`（拒绝 `PACKAGE_ROOT/data` 与 `/data/user` 嵌套） |
| 路径单例 | `deeptutor/services/path_service.py:64-100` | `PathService`（`workspace_root = get_runtime_data_root()`，`path_service.py:81-87`；`reset_instance` `path_service.py:99-100`） |
| 单例复位（launcher 侧） | `deeptutor/runtime/launcher.py:140-159` | `_reset_runtime_singletons` |
| 单例复位（init 侧） | `deeptutor_cli/init_cmd.py:24-48` | 同名副本 |
| 更新交接 | `deeptutor/runtime/launcher.py:1211-1259` | `_handoff_pending_update` |
| 重启完成确认 | `deeptutor/runtime/launcher.py:1262-1275` | `_complete_restarted_update` |
| 独立更新执行器 | `deeptutor/runtime/update_worker.py:103-146` | `run_update_worker` |
| worker 派生 | `deeptutor/services/app_update.py:623-655` | `launch_update_worker` |
| job 持久层 | `deeptutor/services/app_update.py:475-592` | `UpdateJobStore`（`state.json`/`active`/`worker.log`，`app_update.py:478-480`） |
| 前端运行时解析 | `deeptutor/runtime/launcher.py:841-892` | `_resolve_frontend` |
| 源码生产构建 | `deeptutor/runtime/launcher.py:765-816` | `_ensure_source_production_build` |
| 构建指纹 | `deeptutor/runtime/launcher.py:723-762` | `_source_build_fingerprint` |
| 打包前端缓存 | `deeptutor/runtime/launcher.py:613-653` | `_copy_packaged_web_if_needed` |
| dev-server 复用 | `deeptutor/runtime/launcher.py:933-1028` | `_detect_existing_source_frontend` / `_stop_unhealthy_source_frontend` |
| 进程树终止 | `deeptutor/runtime/launcher.py:254-268` | `_terminate`（信号分发 `_send_tree_signal` `launcher.py:233-251`） |
| 分离启动/停止 | `deeptutor/runtime/launcher.py:1080-1150` / `1176-1208` | `_launch_detached` / `stop` |
| init 向导 | `deeptutor_cli/init_cmd.py:412-538` | `run_init`（五步：端口→LLM→Embedding→Search→Review） |

## 2. 启动时序（文字版）

`deeptutor start`（`deeptutor_cli/main.py:128-149`）→ `launcher.start()`：

1. **准备**：放宽控制台编码为 replace（`launcher.py:1285`，实现 `271-291`，防 cp950 等码页把 Next 横幅字符打成致命错 #702）。解析 runtime home：显参 > `DEEPTUTOR_HOME` > cwd（`home.py:40-43`），校验拒绝包内 `data/` 嵌套（`home.py:12-25`），并 `mkdir -p`（`launcher.py:1291`）。
2. **分离分叉**：`--detach` 时写 token 后以 `DETACHED_PROCESS`/`start_new_session` 再拉起一个自己并立即返回（`launcher.py:1296-1298` → `_launch_detached` `1080-1150`）。状态文件 `<home>/data/user/runtime/launcher.json` + 停止哨兵 `launcher.stop`（`launcher.py:75,175-181`）。
3. **单例复位**：把 `DEEPTUTOR_HOME` 写回环境并清空 `PathService`/`RuntimeSettingsService`/`ModelCatalogService` 单例（`launcher.py:1306-1307` → `140-159`），否则单例仍持旧 home 的路径。
4. **设置装载**：`init_user_directories` → `ensure_runtime_settings_files` → `load_launch_settings` 得到端口（`launcher.py:1322-1327`）；`export_runtime_settings_to_env` 生成派生环境（`launcher.py:1326`）。
5. **前端运行时决策**（`_resolve_frontend`，`launcher.py:841-892`）：
   - `deeptutor_web` 包可导入且有 `server.js` → **packaged**：拷入可写缓存 `<home>/data/user/runtime/web/`，比对 `.deeptutor-web-runtime.json` 标记（source+mtime+api_base+auth，`launcher.py:629-641`），不匹配则重拷并替换 `__NEXT_PUBLIC_API_BASE_PLACEHOLDER__`（`launcher.py:647-651,656-680`）。
   - 源码检出有 `web/package.json` → 非 `--dev` 时**source-production**：先 `npm ci/install` 补依赖（`launcher.py:691-710`），再走构建标记检测（见 §4）；`--dev` 时直接 `npm run dev`（`launcher.py:885-887`）。
   - 两者皆无 → `SystemExit`（`launcher.py:889-892`）。
6. **dev-server 复用**：仅 `source` 模式读 `.next/dev/lock` 或 `.next/lock`，取 port/pid/appUrl；pid 已死且端口无监听则视为陈旧锁（`launcher.py:933-962`）。锁指向存活进程但 HTTP 探测失败时，先确认命令行像 Next 再整组 SIGTERM→5s→SIGKILL，并删锁（`launcher.py:1344-1354` → `993-1028`；`_looks_like_next_process` `985-990`）。
7. **端口治理**：loopback 双栈探测占用（`launcher.py:323-332`）；冲突时 TTY 交互二选一（换端口并持久化到 system.json，`launcher.py:458-496`；或 lsof/netstat 找到监听者整组杀掉，`launcher.py:499-568`）；非 TTY（Docker/CI）直接报错退出（`launcher.py:556-558`）。换端口后重导出环境并重建前端运行时（`launcher.py:1364-1379`）。
8. **子进程环境**（`launcher.py:1396-1441`）：注入 `BACKEND_PORT`/`FRONTEND_PORT`/`NEXT_PUBLIC_API_BASE`；`SUPERVISOR_PID_ENV` 与 `LAUNCHER_PID_ENV` 都指 supervisor 自身 pid（`launcher.py:1418-1419`）供 memory_probe 与更新链识别进程树；抹掉 `DEEPTUTOR_NEXT_DIST_DIR` 防止后端继承后在运行中重建 `.next-deeptutor`（`launcher.py:1423-1430`）；`SETTINGS_DERIVED_ENV_KEYS` 标记"哪些 env 是设置文件派生"防后端把 env 当部署覆盖（#1536，`launcher.py:1431-1441`）。子进程 POSIX 侧 `start_new_session=True` 各自成组（`launcher.py:316`），Windows 侧 `CREATE_NEW_PROCESS_GROUP|CREATE_NO_WINDOW`（`launcher.py:310-314`）。
9. **后端拉起**：`uvicorn deeptutor.api.main:app --host 0.0.0.0`， workers 来自 system.json，`--ws-max-size`/`--timeout-keep-alive` 来自设置（`launcher.py:1443-1476`）；轮询 `http://127.0.0.1:<port>/`，超时默认 60s 可用 `DEEPTUTOR_BACKEND_READY_TIMEOUT` 覆盖（`launcher.py:39-58,1519-1529`）；子进程提前退出立即 `RuntimeError`（`launcher.py:585-586`）。
10. **前端拉起/复用等待**：新起 standalone `server.js` 或等待既有 dev server 就绪，超时默认 120s（`launcher.py:1533-1555`）。两者都就绪后调用 `_complete_restarted_update`——只有此刻才把 `restarting` 更新任务标记 `succeeded`（`launcher.py:1558` → `1262-1275`）；分离模式再写 `launcher.json` 的 ready 状态（`launcher.py:1559-1566`）。
11. **监督循环**：每 1s 检查一次待更新交接与子进程存活；有子进程退出则置 `exit_code=1` 触发收尾（`launcher.py:1571-1581`）。SIGINT/SIGTERM/SIGHUP/SIGBREAK 进 `request_shutdown`（`launcher.py:1031-1066,1485-1491`）；`cleanup` 先杀 frontend 再杀 backend，并清分离运行时文件，经 `atexit` 与 `finally` 双保险（`launcher.py:1502-1516,1584-1585`）。

**更新交接（监督循环内触发，`launcher.py:1572` → `1211-1259`）**：读 `state.json`，仅 `pending` 任务继续；systemd 服务内直接 `mark_failed(SYSTEMD_UPDATE_REASON)` 保服务存活（`launcher.py:1237-1242`）；否则 `prepare_handoff` 写入 `restart_home`/校验过的 `restart_argv`（`app_update.py:518-537`；argv 白名单校验 `app_update.py:595-605`），派生脱离进程树的 worker（`launch_update_worker`，`app_update.py:623-655`），随后 launcher 置 shutdown、cleanup 杀掉旧前后端（`launcher.py:1572-1574,1507-1508`）。

**worker 侧（`update_worker.py:103-146`）**：要求 `handoff` 态（`116-117`）→ 等 launcher pid 退出（60s 超时，`56-63`）→ `mark_running` → 只允许执行一条经 `UpdateJob` 校验回环的 `pip install deeptutor==<稳定版>`（`17-40`）→ 成功 `mark_restarting` 并以分离方式重启 `start --home <同一home>`（`43-49,81-100`）。任何异常：终态化（未成功/失败才 mark_failed）并尽力重启恢复应用（`134-145`）。重启后的新 launcher 就绪后在第 10 步把任务标记 `succeeded`（`launcher.py:1558`）。

## 3. 前端构建标记检测（source-production）

- dist 目录固定为 `web/.next-deeptutor`（`SOURCE_PRODUCTION_DIST_DIR`，`launcher.py:63`），与显式 `--dev` 的 `.next` 互不覆盖（`launcher.py:765-779` 注释）。
- 标记文件 `web/.next-deeptutor/.deeptutor-build.json`（`launcher.py:64`），内容只有 `{"fingerprint": ...}`。
- 复用条件：`BUILD_ID` 与 `standalone/server.js` 同时存在，且标记内容等于当前指纹（`launcher.py:785-791`）；命中则只补 static/public 资产（`_prepare_source_standalone`，`launcher.py:819-838`）。
- 指纹输入：3 个构建期 env（`DEEPTUTOR_NEXT_DIST_DIR`/`NEXT_PUBLIC_API_BASE`/`NEXT_PUBLIC_AUTH_ENABLED`）+ `web/` 全树排序遍历哈希（排除 `node_modules`/`dist`/`playwright-report`/`test-results`/`coverage` 与 `.next*` 目录，`launcher.py:65-71,739-746`）+ `deeptutor/__version__.py`（`launcher.py:737-748`）——改后端版本号也会触发前端重建。
- 构建前快照 `next-env.d.ts`/`tsconfig.json`，构建后还原，防 Next 改写弄脏检出或破坏 `--dev` typecheck（`launcher.py:794-807`）。
- 打包安装的对应物是 `.deeptutor-web-runtime.json`（见 §2 第 5 步）；两者都读失败即视为标记无效、走重建/重拷（`launcher.py:786-791,637-642`）。

## 4. 失败模式、吞错与状态残留（风险点 → 可拆修复卡）

| # | 风险 | 位置 | 现象/后果 | 建议卡 |
| --- | --- | --- | --- | --- |
| R1 | `_terminate` SIGKILL 后不 `wait()`，POSIX 留僵尸；`_send_tree_signal` 全吞异常 | `launcher.py:254-268,233-251` | 8s 宽限后强杀的子进程成为僵尸直至 launcher 退出；信号失败无日志 | 修复卡：KILL 后补 `wait()`/`waitpid` 并对 `_send_tree_signal` 记日志 |
| R2 | `_kill_port_listeners` 以 `pgid=None` 只杀监听 pid 本身 | `launcher.py:504,513`（对照 `_send_tree_signal` `248-251`） | 监听者的子进程（如 npm→next 链）存活成孤儿，端口虽释放树仍在 | 修复卡：先 `_get_pgid` 再整组发信号 |
| R3 | 更新任务卡死无恢复：worker 被 SIGKILL 或重启后 launcher 永不就绪时，`state.json` 停在 `handoff`/`running`/`restarting`，`active` 槽不释放 | `update_worker.py:134-146` 只兜住可捕获异常；`launcher.py:1211-1259,1262-1275` 只处理 `pending`/`restarting`；释放仅发生在 `succeeded/failed`（`app_update.py:581-582`） | 后续 `create` 因 `O_CREAT\|O_EXCL` 永远 `UpdateInProgressError`（`app_update.py:499-503`），应用内更新通道被永久锁死，需手删 `data/user/update/active` | 修复卡：launcher 启动时对陈旧中间态做一次性 `mark_failed`（或带 TTL 的恢复）；`active` 记录 pid 并在启动时核对存活 |
| R4 | `_reset_runtime_singletons` 三段 `except Exception: pass` | `launcher.py:142-158`；副本 `init_cmd.py:31-47` | 复位失败被静默吞掉，后续服务单例仍指向旧 home，数据写错工作区且无任何日志 | 修复卡：吞错处至少 `_log` 一行；两份同名函数可合并为共享工具 |
| R5 | 分离状态写盘窗口：Popen 成功到 `_write_detached_state` 之间崩溃 | `launcher.py:1132-1147` | 进程活着但 `launcher.json` 缺失，`stop()` 报 not_running、无法停止 | 低优修复卡：先写 state（pid 占位）再 Popen，或 Popen 后同步 fsync |
| R6 | `stop()` 超时抛 `SystemExit` 且不清 `launcher.stop` 哨兵 | `launcher.py:1200-1208` | 残留哨兵文件；下次分离启动时 `_launch_detached` 会先 unlink（`launcher.py:1095-1096`），影响有限但窗口期内可能误停新实例 | 与 R5 同卡处理 |
| R7 | 监督循环每秒整读 `state.json`；损坏时静默当无任务 | `launcher.py:1571-1572,1229-1232` | 损坏的更新状态被无限忽略，用户无感知（与 R3 叠加） | 并入 R3 卡：加载失败记一次日志 |
| R8 | 指纹每次 start 全树哈希 `web/`，大检出上启动变慢 | `launcher.py:723-762` | 纯性能，无正确性问题；可比较文件 mtime+size 预筛 | 可选优化卡 |
| R9 | `_wait_for_http` 只探 `/`；后端路由化部署或慢初始化依赖超时覆盖 | `launcher.py:1522-1529`（环境变量逃生门 `39-58`，#1435） | 已有逃生门，风险低；注意默认 60s 在 ARM+迁移场景历史上不够 | 无需新卡，文档已有 env 说明 |

## 5. 测试空白

现有覆盖：交接/systemd 拒绝/重启确认（`tests/runtime/test_launcher.py:144-204`）、端口冲突四态（`tests/runtime/test_launcher.py:272-366`）、构建标记复用与刷新（`tests/runtime/test_launcher.py:462-570`）、超时覆盖（`tests/runtime/test_launcher.py:786-828`）、分离启停（`tests/runtime/test_launcher.py:723-784`）、worker 成功/失败/版本校验（`tests/runtime/test_update_worker.py:24-88`）。

空白（对应 §4 编号）：

1. `_terminate` 无直接测试：唯一引用是把它 monkeypatch 掉（`tests/runtime/test_launcher.py:624`）；SIGKILL 升级、僵尸、Windows taskkill 分支均未覆盖（R1）。
2. 卡死任务恢复不存在也无测试：`handoff`/`running` 态 worker 被杀、`restarting` 后新 launcher 永不就绪，均无用例（R3，`tests/services/test_app_update.py` 只测终态迁移）。
3. `_reset_runtime_singletons` 与 `init_cmd.py` 整体无专门测试：`tests/cli/` 只测 `init_wizard` 的 probe 逻辑（`tests/cli/test_init_wizard_probe.py`）；home 切换后单例复位行为未验证（R4）。
4. 分离启动的 state 写盘失败路径未测（R5）；`stop()` 超时分支未测（R6）。
5. `state.json` 损坏时监督循环/交接的行为未测（R7）。

## 6. 修复切入坐标速查

- 更新状态机加恢复逻辑：`deeptutor/services/app_update.py:475-592`（store）+ `deeptutor/runtime/launcher.py:1300` 附近启动早期。
- 进程树终止加固：`deeptutor/runtime/launcher.py:254-268`（`_terminate`）、`233-251`（`_send_tree_signal`）。
- 单例复位共享化：`deeptutor/runtime/launcher.py:140-159` 与 `deeptutor_cli/init_cmd.py:24-48` 去重。
- 前端标记/指纹调整：`deeptutor/runtime/launcher.py:62-71`（常量）、`723-816`（指纹与构建）。
