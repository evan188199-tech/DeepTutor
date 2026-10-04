# deeptutor_cli 命令面导读（AGEN-477）

基线：origin/main @ `ef2d9e5c3`（v1.6.12）。以下所有 `path:line` 均相对该提交，只读导读，不改产品代码。

## 1. 入口与命令树

- 包入口：`deeptutor = "deeptutor_cli.main:main"`（pyproject.toml:95-96），`main()` 直接调 typer app（deeptutor_cli/main.py:222-227）。
- 导入即生效的副作用：`set_mode(RunMode.CLI)` 与 `configure_logging()` 在模块顶层执行（deeptutor_cli/main.py:28-29）。
- app 定义：`no_args_is_help=True`，无参数时打印帮助（deeptutor_cli/main.py:31-36）。

### 子命令组（Typer 子 app，main.py:38-63）

| 组 | 声明/挂载 | 子命令 | register 位置 |
|---|---|---|---|
| partner | main.py:38,51 | list / start / stop / create | deeptutor_cli/partner.py:17,47,62,76 |
| chat（REPL） | main.py:39,52 | 无子命令，callback 直进 REPL | deeptutor_cli/chat.py:44 |
| kb | main.py:40,53 | list / info / set-default / create / connect-kiwix / add / delete / search / add-github-source / remove-github-source / add-web-source / remove-web-source / list-sources / sync | deeptutor_cli/kb.py:62,117,128,139,185,205,248,271,339,360,373,393,406,455 |
| skill（别名 skills） | main.py:41,54-55 | search / install / login / logout / publish / update / list / remove | deeptutor_cli/skill.py:75,121,187,244,258,381,539,559 |
| memory | main.py:42,56 | show / clear | deeptutor_cli/memory.py:21,63 |
| plugin | main.py:43,57 | list / info | deeptutor_cli/plugin.py:20,42 |
| config | main.py:44,58 | show | deeptutor_cli/config_cmd.py:17 |
| session | main.py:45,59 | list / show / open / delete / rename | deeptutor_cli/session_cmd.py:16,23,31,38,45 |
| notebook | main.py:46,60 | list / create / show / remove-record / add-md / replace-md | deeptutor_cli/notebook.py:17,23,33,61,78,112 |
| provider | main.py:47,61 | login | deeptutor_cli/provider_cmd.py:16 |
| book | main.py:48,62 | list / health / refresh-fingerprints | deeptutor_cli/book.py:17,37,49 |
| workspace | main.py:49,63 | show / set / reset | deeptutor_cli/workspace_cmd.py:11,21,32 |

### 顶层单命令（直接挂 app）

| 命令 | 位置 | 说明 |
|---|---|---|
| `deeptutor run <capability> <message>` | deeptutor_cli/main.py:81-124 | 任意能力单轮执行，`--format rich/json`；延迟导入 `DeepTutorApp`（main.py:107） |
| `deeptutor start` | main.py:127-149 | 后端+前端一起启动，转 `deeptutor.runtime.launcher.start`（main.py:147）；源码安装默认生产模式（main.py:146） |
| `deeptutor stop` | main.py:152-160 | 停 `--detach` 启动的 launcher，失败退出码 1 |
| `deeptutor serve` | main.py:163-219 | 仅 API 后端（uvicorn）；端口默认 `get_backend_port()`（main.py:174-177）；Windows 切 Proactor 事件循环（main.py:182-183） |
| `deeptutor doctor` | deeptutor_cli/doctor.py:43-77 | 就绪诊断；`--online` 真连模型、`target=runtime` 走 v2 诊断；`--format json` 用 `print_json`（doctor.py:73）；不健康退出码 1（doctor.py:76-77） |
| `deeptutor init` | deeptutor_cli/init_cmd.py:541-549 | 设置向导，`--cli` 跳过端口步骤，`--home` 指定工作区根 |

## 2. init / 启动链路

### 2.1 `deeptutor init`（deeptutor_cli/init_cmd.py:412-538）

1. `get_runtime_home(home)` 解析工作区根并 `mkdir`（init_cmd.py:413-414；优先级见 §3）。
2. 写 `DEEPTUTOR_HOME` 环境变量（init_cmd.py:417），随后 `_reset_runtime_singletons()`（init_cmd.py:418）。
3. `init_user_directories(runtime_home)` 建目录（init_cmd.py:424）。
4. 分步向导：CLI 模式 4 步（LLM→Embedding→Search→Review），完整模式 5 步（先 Ports）（init_cmd.py:429-431,441-460）。
5. LLM/Embedding 直接改 model catalog 草稿（`_ensure_model_service` 就地定位或创建默认 profile/model，init_cmd.py:51-85,465-477,486-499）；Search 写 search profile（init_cmd.py:506-510）。
6. Review 确认后一次性保存：`runtime.save_system(system)`（仅完整模式）+ `catalog_service.save(catalog)`（init_cmd.py:528-530）。与 Web Settings 页写同样的文件（模块 docstring，init_cmd.py:3-4）。
7. 重量级交互（provider 菜单、`/models` 实时拉取、连通性探测、复核面板）在 `init_wizard`（init_cmd.py:6-8）。

### 2.2 `_reset_runtime_singletons` 的两份拷贝（fix-init-singletons 交界）

- CLI 侧：init_cmd.py:24-48 —— `PathService.reset_instance()`、`RuntimeSettingsService._instances.clear()`、`ModelCatalogService._instances.clear()`，三段 `except Exception: pass`（init_cmd.py:35-36,40-41,46-47）。
- launcher 侧：deeptutor/runtime/launcher.py:140-160 —— 逻辑相同的一份拷贝，在 `start()` 里 `DEEPTUTOR_HOME` 生效后调用（launcher.py:1301-1302）。
- 目的：换 `--home` 后清掉缓存了旧路径的单例，否则静默写错位置（init_cmd.py:25-30）。
- **交界**：该条目在 DT-22 report 中已被 fix-init-singletons 卡认领，本卡只记录现状，不改这两处；修改时应收敛两份拷贝并让重置失败可见。

### 2.3 `deeptutor start` 时序（launcher.start，deeptutor/runtime/launcher.py:1274 起）

1. `_relax_console_encoding()`（launcher.py:1281）。
2. 解析并校验 runtime home：非法（指向源码 checkout 的 `data` 树）直接 `SystemExit`（launcher.py:1282-1286；deeptutor/runtime/home.py:19-34）。
3. `--detach` 走 `_launch_detached` 后返回（launcher.py:1292-1293）；detached worker 由 `DEEPTUTOR_DETACHED_WORKER=1` + `DEEPTUTOR_DETACHED_TOKEN` 识别（launcher.py:73-74,1296-1297）。
4. 写 `DEEPTUTOR_HOME` 并重置单例（launcher.py:1302-1303，即 §2.2 的第二份拷贝）。
5. `ensure_runtime_settings_files()` / `load_launch_settings()` / `export_runtime_settings_to_env()`（launcher.py:1319-1322）；派生 env 的同步集合记录在 `SETTINGS_DERIVED_ENV_KEYS`（launcher.py:1433-1435，防 Web 端写 system.json 后 env 漂移，见 #1536 注释 launcher.py:1430-1432）。
6. 端口冲突交互：`_suggest_free_port`/`_prompt_port`（launcher.py:416,423），选定后持久化（launcher.py:455）。
7. 后端拉起：`python -m uvicorn deeptutor.api.main:app`，带 `--ws-max-size`、`--timeout-keep-alive`、`--workers` 等（launcher.py:1441-1470）。
8. 前端拉起：优先 packaged `server.js`，否则 standalone 构建（launcher.py:857,879）。
9. 更新交接（update handoff）：两个受管进程都 ready 才 mark update 成功（launcher.py:1259）；`_handoff_pending_update`（launcher.py:1207,1568）；handoff 失败 `store.mark_failed`（launcher.py:1235,1251）。
   - **交界（launcher 卡）**：launcher 生命周期测试 AGEN-287（in_review）与 handoff mark_failed 修复线（AGEN-221，随 AGEN-302/345 复核的 `fix/launcher-handoff-mark-failed-pr`）覆盖 §2.3 第 9 步；本卡不改，只标注链路位置。
10. 对应停止路径：`deeptutor stop` → `launcher.stop(home, timeout=15)`（launcher.py:1172；main.py:157-160）。

### 2.4 `serve` 与 `start` 的关系

- `serve` 只起后端 API，不改 mode 之外的 launcher 逻辑；入口先把 mode 切到 `RunMode.SERVER`（main.py:173），launcher 拉起的 uvicorn 子进程复用同一 app（launcher.py:1444）。
- `--reload` 与 `backend_workers>1` 互斥，冲突退出码 2（main.py:200-203）。

## 3. 配置与环境变量

| 变量 | 作用 | 位置 |
|---|---|---|
| `DEEPTUTOR_HOME` | 工作区根；优先级 `--home` 参数 > 环境变量 > cwd（deeptutor/runtime/home.py:41-56）；init（init_cmd.py:417）与 launcher（launcher.py:1301）都会回写 | home.py:8 |
| `DEEPTUTOR_MODE` | cli/server 模式标记，`set_mode` 会同步 env（deeptutor/runtime/mode.py:33-37）；未显式设置时按 env 推断，默认 cli | mode.py:21-30 |
| `DEEPTUTOR_HUB_TOKEN` / `EDUHUB_TOKEN` | skill hub 令牌（`--token` 之外的 env 回退） | deeptutor_cli/skill.py:34-35 |
| provider API key env | init 向导按 `spec.env_key` 检测已存在的 key（如 `OPENAI_API_KEY`），可复用 | deeptutor_cli/init_wizard.py:567,599 |
| search provider key env | `_search_step` 从 env 检测（`wiz.search_api_key_from_env`） | init_cmd.py:347-352 |
| `DEEPTUTOR_DETACHED_WORKER` / `DEEPTUTOR_DETACHED_TOKEN` | detached launcher 子进程握手 | launcher.py:73-74 |
| `NEXT_PUBLIC_API_BASE(_EXTERNAL)` | 由 runtime settings 导出给前端 | launcher.py:1324-1326 |

配置文件落点：

- settings 目录 = `<home>/data/user/settings`（`PathService.get_settings_dir`，deeptutor/services/path_service.py:225-226）。
- model catalog = `get_settings_file("model_catalog")`（deeptutor/services/config/model_catalog.py:30），init 与 Web 共用同一 `get_model_catalog_service()` 单例。
- 端口/system 设置 = `runtime.save_system(system)`（init_cmd.py:529），launcher 启动时 `load_system_settings()` 读取（launcher.py:1321）。

## 4. 退出码与错误输出约定

退出码（typer.Exit/SystemExit）：

- **0 = 成功**，含"良性 no-op"：kb sync 无可同步源（deeptutor_cli/kb.py:467）、skill publish/update 无变更或用户取消（skill.py:341,435,463-521）。
- **1 = 一般失败**：统一的 `[red]…[/]` 提示 + `Exit(1)` 模式，如资源不存在（kb.py:460-461；plugin.py:80-81）、doctor 不健康（doctor.py:76-77）、stop 无运行实例（main.py:159-160）、serve 缺依赖（main.py:188-192）、init Review 取消（init_cmd.py:524-526）。带原因的底层异常用 `from exc` 链（kb.py:125,136,151 等）。
- **2 = 用法/配置冲突**：serve `--reload` 与多 worker 冲突（main.py:200-203）；`typer.BadParameter` 走 click 默认退出码 2（doctor.py:64,69）。
- **130 = 用户中断**：init 的 `KeyboardInterrupt/typer.Abort`（init_cmd.py:535-538）、provider login 的 Ctrl-C（provider_cmd.py:79）。

错误输出风格：

- 人类可读：rich `Console` + 彩色标记（每个模块自建 `Console()`，如 plugin.py:16；共享的从 common 导入，main.py:14）。
- 机器可读：`--format json` 分支用 `console.print_json`（doctor.py:73；plugin.py:56,64-77）。
- chat REPL 中断不当作错误：`TurnInterrupted` 异常 + `_cancel_interrupted_turn` 补偿（deeptutor_cli/common.py:88,252）。
- 工具结果在 REPL 中截断展示、可回放：`truncate_for_display` / `ToolResultBuffer`（deeptutor_cli/_tool_result.py:13-30）。

## 5. #961/#1307 预留扩展点（plugin list/info）

现状：`plugin list` / `plugin info` 已存在（deeptutor_cli/plugin.py:19-81），读取运行时注册表 `get_tool_registry()` / `get_capability_registry()`（plugin.py:23-27,47-51）；`plugin info` 对能力会输出 manifest（含 `cli_aliases`、stages、tools_used、availability）（plugin.py:59-77）。

上游状态（2026-10-04 查证）：

- #961 "pluggable learning resource providers with lifecycle controls"：OPEN；关联 PR #1377 已 CLOSED 未合并。
- #1307 "managed third-party plugin platform"：OPEN；关联 PR #1309 已 CLOSED 未合并。
- 结论：插件平台（安装/审批/启停/权限清单）尚未落地，CLI 侧命令均未存在。

新命令接入点（给后续实现卡的预留说明）：

1. 一律走 `register(app)` 钩子挂到 `plugin_app`（main.py:70 调用点不变），新子命令加在 plugin.py 的 `register` 内，与 list/info 并列。
2. 保持懒导入：注册表与重量级依赖在命令体内 import（plugin.py:23-24,47-48 的既有模式；同见 main.py:107,147,157）。
3. 未找到/失败沿用红色提示 + `Exit(1)`；详情类输出用 `print_json` 保持机器可读（plugin.py:80-81,56 的既有模式）。
4. 能力清单字段继续以 manifest 为契约（`cli_aliases` 已由 `plugin info` 透出，plugin.py:69），#1307 的信任/权限清单将来应作为 manifest 的超集呈现，而不是另起一套 CLI 查询入口。

## 6. 扩展新命令的步骤（模板）

以最小模块 workspace_cmd.py:10-44 为例：

1. 在 `deeptutor_cli/<topic>.py` 定义 `register(app: typer.Typer)`，内部用 `@app.command("name")`。
2. main.py:38-49 声明子 app 与 help；main.py:51-63 `add_typer`（需要别名时学 skill：main.py:55）；main.py:65-78 调 `register`。
3. 重依赖延迟导入，保持 `deeptutor --help` 秒开（对照 main.py:107,147,157,170-198）。
4. 错误处理按 §4 约定：红字 + `Exit(1)`、用法冲突 2、中断 130、no-op 0。
5. 配置读写走 runtime settings / model catalog 服务单例，不直接写文件；涉及工作区根时用 `get_runtime_home`。
6. 输出：rich 表格给人，`--format json` 给机器。

## 7. 本卡边界声明

- 本卡只新增 `evidence/guide-cli-2026-10-04/guide.md`，未改任何产品代码。
- 与 fix-init-singletons 卡的交界：§2.2（两份 `_reset_runtime_singletons` 拷贝及静默 except）。
- 与 launcher 卡的交界：§2.3 第 9 步（update handoff / mark_failed 链路，AGEN-287 测试、AGEN-221 修复线）。
- 与 #961/#1307 的关系：§5（上游两 PR 均已关闭未合并，插件平台命令尚未存在，接入点如上预留）。
