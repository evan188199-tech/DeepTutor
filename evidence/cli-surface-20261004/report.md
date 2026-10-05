# deeptutor_cli 命令面一致性清点报告

- 日期：2026-10-04
- 分支：`agent/agen663-cli-surface`（基于 origin/main @ f07029cfc "release: v1.6.13"）
- 只读扫描：未改任何代码、未启动服务器/守护进程/交互式命令。
- 范围：`deeptutor_cli/` 全部 23 个文件（~5836 行）；对照 `deeptutor/runtime/bootstrap/builtin_capabilities.py`、`deeptutor/app/facade.py`、`deeptutor/services/rag/eval/`、`deeptutor_cli/README.md`、`pyproject.toml`、`packaging/deeptutor-cli/pyproject.toml`。
- 对照基线：卡面 DT-22 报告 §7 的锚点（init_cmd / provider_cmd / skill_login 吞错点）。DT-22 原始报告文件在当前工作区不可得（原工作区已回收），本报告以卡面描述中列出的锚点为对照输入，全部逐一复核。
- 判定分级：✔ 良性/已文档化 ｜ ⚠ 不一致（可拆卡） ｜ ✗ 缺陷（建议尽快修）

## 1. 命令清单（surface table）

入口：`deeptutor = deeptutor_cli.main:main`（pyproject.toml:96，packaging/deeptutor-cli/pyproject.toml:71 双入口一致）。app 名 `deeptutor`，`no_args_is_help=True`（main.py:31-36）。

| 命令组 | 子命令 | 注册位置 |
|---|---|---|
| run | run | main.py:81 |
| start / stop / serve | 各 1 | main.py:127/152/163 |
| doctor | doctor（target 可选 runtime；--online/--format） | doctor.py:43 |
| init | init（--cli/--home） | init_cmd.py:541 |
| partner | list / start / stop / create | partner.py:17/47/62/76 |
| chat | （callback，无子命令，REPL） | chat.py:44 |
| kb | list / info / set-default / create / connect-kiwix / add / delete / search / eval / add-github-source / remove-github-source / add-web-source / remove-web-source / list-sources / sync（15 个） | kb.py:144-652 |
| skill + skills（双别名） | search / install / login / logout / publish / update / list / remove（8 个） | main.py:54-55；skill.py:75-559 |
| memory | show / clear | memory.py:21/63 |
| plugin | list / info | plugin.py:20/42 |
| config | show | config_cmd.py:17 |
| session | list / show / open / delete / rename | session_cmd.py:16-51 |
| notebook | list / create / show / remove-record / add-md / replace-md | notebook.py:17-112 |
| provider | login（openai-codex / github-copilot / codebuddy） | provider_cmd.py:16 |
| book | list / health / refresh-fingerprints | book.py:17/37/49 |
| workspace | show / set / reset | workspace_cmd.py:11/21/32 |

合计 6 个顶层单命令 + 15 个命令组、约 57 条命令。

## 2. 子命令/参数命名不一致

| # | 位置 | 判定 | 问题 |
|---|---|---|---|
| N1 | deeptutor_cli/main.py:85-88、deeptutor_cli/README.md:56-66 | ⚠ | `run` 的 capability help 只列 7 个；注册表实际 12 个（builtin_capabilities.py:18-31，缺 ask_questions、immersive_reading、course_study、immersive_watching、audio_overview）。别名（solve/quiz/research/animate/viz/ask/read/watch/course/overview，facade.py:78-92 负责解析）两处均未提及 |
| N2 | notebook.py:36、session_cmd.py:26 vs main.py:104、kb.py:146/358/434、doctor.py:54-59 | ⚠ | `--format` 在 run/kb/doctor 有 `-f` 缩写，notebook show / session show 没有 |
| N3 | doctor.py:62-63 vs main.py:104、kb.py:146、notebook.py:36、session_cmd.py:26 | ⚠ | `--format` 取值只在 doctor 校验；其余命令拼错值静默按 rich 输出 |
| N4 | partner.py:78-80 vs skill.py:127-129 | ⚠ | `--name` 语义漂移：partner create 里是"显示名"（ID 是位置参数），skill install 里是"本地重命名" |
| N5 | kb.py:333、memory.py:69 vs skill.py:130-132 | ⚠ | `--force` 缩写 `-f` 有无不一致（kb/memory 有，skill install 无） |
| N6 | memory.py:56,74 vs 全仓惯例 | ⚠ | `raise typer.Exit(1)` 位置参数，其余均为 `Exit(code=1)`（风格项） |
| N7 | main.py:54-55、skill.py:355/378/418 | ⚠ | `skill`/`skills` 双别名是刻意设计（main.py:55 有注释），但提示文案混用：`deeptutor skills login`（:355,:418）vs `deeptutor skill install`（:378） |

✔ 良性项：provider login 的三种 provider 名支持连字符/下划线归一（provider_cmd.py:27-39）；`stop` 失败 exit 1（main.py:159-160）。

## 3. help 文案一致性

| # | 位置 | 判定 | 问题 |
|---|---|---|---|
| H1 | skill.py:190,194,197,248（help 中文）vs :77,125,541,561（help 英文）；消息混排：:308-316 中文 vs :371 "Publish failed:"、:533 "Update failed:" 英文 vs :431 "获取失败：" 中文 | ⚠ | 同一 `skill` 组内 login/logout/publish/update 全中文、search/install/list/remove 全英文；错误话术中英穿插。skill_prompts.py 全中文硬编码（:61,84,105,148 `locale="zh"` 默认参数，无 i18n 通道） |
| H2 | skill_login.py:26-34（浏览器 HTML）、:126（"登录超时…"） | ⚠ | 技能登录流程的用户可见文案为中文，与包内其余英文文案不一致 |
| H3 | init_wizard.py:415 | ⚠ | 注释引用不存在的 `deeptutor login` 命令（实际只有 `provider login` / `skills login`） |
| H4 | deeptutor_cli/README.md:168-222 | ⚠ | README 漏 5 个命令组（skill/skills、partner、book、workspace、doctor、start/stop）；kb 段缺 8 个较新子命令（connect-kiwix、add/remove-github-source、add/remove-web-source、list-sources、sync、eval）；chat 选项表缺 `--notebook-ref/--history-ref/--config/--config-json`（README.md:127-134 vs chat.py:47-60） |

## 4. 退出码盘点

约定现状：失败=1（多数）、typer 用法错=2（BadParameter）、init 取消=130（init_cmd.py:535-538）、provider login 取消=130（provider_cmd.py:76-79）、skill 交互取消/无操作=0（skill.py:341,435,463,468,474,521）、kb sync 无源=0（kb.py:613-614）。

| # | 位置 | 判定 | 问题 |
|---|---|---|---|
| X1 | deeptutor/app/facade.py:92（raise）→ deeptutor_cli/main.py:107-124 + common.py:857-862 | ✗ | `deeptutor run <未知capability>` 的 ValueError 未被捕获：maybe_run 只接 KeyboardInterrupt，命令未包 BadParameter → 用户看到完整 traceback（exit 1）。应转干净报错 |
| X2 | common.py:121（ValueError）vs chat.py:66-70,369（BadParameter） | ✗ | 同一解析函数两条路径不一致：`run --notebook-ref ""` / `--config foo` 直接 traceback；`chat --notebook-ref ""` 是干净的 usage 错误（exit 2） |
| X3 | init_cmd.py:524-526 vs skill.py:339-341 | ⚠ | 用户拒绝保存：init → exit 1，skill publish → exit 0。取消语义两种口径 |
| X4 | partner.py:70-74 vs partner.py:58-60、skill.py:573-575、kb.py:613-614 | ⚠ | "目标不存在"三种口径：partner stop 幂等 exit 0（与 AGEN-493 服务层幂等收口一致，需文档化）；start 失败 exit 1；skill remove not-found exit 1；kb sync 无源 exit 0 |
| X5 | init_cmd.py:449-460 | ✗ | 端口步骤 `int(typer.prompt(...))` 对非数字输入抛未捕获 ValueError → traceback；向导其余输入均健壮 |
| X6 | kb.py:619-651 | ⚠ | `kb sync` 逐源打印红色错误后 continue，部分/全部失败仍 exit 0，无失败汇总。退出码不反映结果 |
| X7 | common.py:857-862 vs init_cmd.py:535-538、provider_cmd.py:76-79 | ⚠ | SIGINT：run/chat turn 中 Ctrl-C → "Interrupted." + exit 0；init/provider login → exit 130。两种口径并存 |

## 5. 错误输出通道（stderr）

系统性缺口：全包错误几乎全部走 **stdout**。

- 公共 `console = Console()` 默认 stdout（common.py:24）；另有 5 个模块自建独立 Console：config_cmd.py:13、kb.py:28、memory.py:17、partner.py:13、plugin.py:16（init_cmd.py:428 向导内部又建一个）——未来统一改 stderr 时这些实例会漏改。
- 唯一正确用例：kb.py:116,118 `typer.echo(..., err=True)`（eval 报告写盘失败/成功提示进 stderr）。
- provider_cmd.py 的 typer.echo（:47-55,73,81,90-94,107,126-131,141,154-155）与 workspace_cmd.py（:17-19,30,41）默认 stdout。
- 影响：`deeptutor … 2>/dev/null` 时错误照常显示（假成功表象）；`1>/dev/null` 时错误被吞；`--format json` 命令（kb/doctor/notebook/session/run）的错误与 JSON 数据混在同一管道。

## 6. 吞错点清单（含 DT-22 锚点复核）

| # | 位置 | 判定 | 说明 |
|---|---|---|---|
| W1 | init_cmd.py:31-48 | ✗ | DT-22 锚点复核属实：`_reset_runtime_singletons` 三个 `except Exception: pass`（:35-36,:41-42,:47-48）。函数自身 docstring（:25-29）写明失败会"silently write to the wrong place"，但失败时连一行警告都没有 |
| W2 | provider_cmd.py:116 | ⚠ | DT-22 锚点复核：`load_credentials()` 裸调用未包 try——若凭据文件损坏抛非预期异常会 traceback（probe 失败路径本身处理正确：:139-156）。另 :148-151 `webbrowser.open` 失败静默 pass，有前置 URL 打印（:147），✔ 低危 |
| W3 | skill_login.py:120-124 | ✔ | DT-22 锚点复核：browser 打开失败静默 pass 属文档化设计（headless 场景，注释明示；URL 已由 on_url 回调打印，skill.py:228-230）；state nonce 校验失败有 400 响应（:93-97）。未发现实际吞错 |
| W4 | chat.py:93-99 | ⚠ | cron 服务启动失败 `except Exception: cron_service=None` 全静默——REPL 定时任务功能失效无任何提示。建议 warn 一行 |
| W5 | config_cmd.py:63-66 | ⚠ | `config show` 读 main.yaml 失败静默置 `{}`，语言/工具显示为默认值（en/[]），损坏配置不可见。建议 warn |
| W6 | kb.py:41-44 | ✗ | `_collect_documents` 对不存在的显式 `--doc` 路径静默忽略：两条路径给一条拼错时文档悄悄少一条；只有全部无效才报错（kb.py:246,306）。建议对显式路径缺失直接报错或 warn |
| W7 | init_wizard.py:648-650,771-774 | ✔ | /models 拉取失败 warn 后回退内置列表——docstring 明示的降级设计（:622-626,745-752）；probe 失败如实展示（init_cmd.py:181-183,315） |
| W8 | chat.py:186-189 | ✔ | REPL 退出时 cron stop 失败 `suppress(Exception)`——进程即将退出，良性 |
| W9 | common.py:259-260,361-362,689-690 | ✔ | turn 取消/spinner 停止路径的 suppress——中断清理，良性 |
| W10 | memory.py:81-90 | ⚠ | `memory clear all` 只删根目录文件与 trace/L2/L3 三个子目录，其余子目录静默保留却打印 "Cleared all memory."——声明与行为不符 |

已验证非 bug：kb.py:103 `item.metrics.values()[recall_key]`——`QueryMetrics.values()` 是方法（deeptutor/services/rag/eval/metrics.py:152-154），返回 `recall@k` 键名字典，调用正确。

## 7. 与 scan-error-messages（AGEN-519，scan-error-msg-20261004）去重

该报告范围是 routers/services/web，**未覆盖 deeptutor_cli/**。重叠仅 3 处（同一底层消息的 CLI 显示点，均为新增计数）：

| 本报告 | scanerr 对应条目 | 关系 |
|---|---|---|
| notebook.py:44,71 打印 NotebookCorruptedError 原文（含路径） | services RAW-EXC-UPSTREAM 表 services/notebook/service.py:81 | 消息生成点已报；CLI 显示点新增 |
| skill.py:163,371,431,482,533 打印 HubError 原文 | services 表 services/skill/hub.py:534,559,717-720 | 同上 |
| common.py:485 `_on_error` 渲染 turn 错误事件 | Top15 #4（executor.py:1349 `content=str(exc)`） | 事件生成点已报；CLI 渲染点新增（stdout、无脱敏） |

H1（skill 组中英混排）与 scanerr LANG-MIX 簇（routers 不用 `t()`、web 硬编码中文）同类不同层，修复方向可合并，但不重复计数。

## 8. 可拆修复卡清单（建议）

| 卡 | 主题 | 涉及条目 | 建议范围 |
|---|---|---|---|
| 1 | CLI 错误通道统一进 stderr | §5 全部 | common.py 增 `error_console = Console(stderr=True)`，收敛 6 个散装 Console 实例；错误类输出改走 error_console / `typer.echo(err=True)`。验收：stdout 管道下错误仍可在 stderr 看到 |
| 2 | run/chat 参数错误收口 | X1、X2 | `build_turn_request` 的 parse_* ValueError 在 run 路径包 BadParameter；capability 未知名转干净报错。可附中性单测（直接调 parse 函数，无需起服务） |
| 3 | 吞错点可见性补齐 | W1、W4、W5、W6、W10 | 5 处静默失败/静默跳过各加一行 warn；不改行为 |
| 4 | 退出码约定与落地 | X3、X4、X6、X7 | 先写约定（建议：取消=0、目标不存在=按命令语义统一、部分失败=1、SIGINT=130）再改代码；可拆"约定文档"+"代码落地"两张 |
| 5 | skill 系文案统一/i18n | H1、H2、N7 | 与 scanerr LANG-MIX 修复共用 i18n 通道，或先做单语收敛（全英文）作为最小修复 |
| 6 | 文档对齐 | H3、H4、N1 | README 补齐命令组与 kb 子命令、capability 表补全 12 项、修 init_wizard.py:415 陈旧注释；纯 docs 卡 |
| 7 | --format 校验与缩写统一 | N2、N3 | doctor 的校验逻辑推广到 run/kb/notebook/session；`-f` 缩写统一 |

## 覆盖声明

- deeptutor_cli/ 23 文件全部通读（含 __init__.py、_tool_result.py、skill_prompts.py）；每条不一致/吞错条目均带 path:line 与判定。
- 退出码/流通道结论基于静态通读 + grep 全量核对（typer.Exit 71 处、err=True 仅 2 处、except 分布全列）。
- X1/X2 的 traceback 结论为静态证据链（facade.py:92 raise → maybe_run 只捕 KeyboardInterrupt → 命令未包 BadParameter），未做动态复现（避免触发重型初始化）。
- kb.py:103 疑似 bug 已动态核伪（QueryMetrics.values() 为方法）。
