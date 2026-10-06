# deeptutor_cli 退出码与 stdout/stderr 约定清点报告

- 日期：2026-10-06
- 分支：`scan/cli-exit-codes-20261006`（基于 origin/main @ f07029cfc "release: v1.6.13"）
- 只读扫描 + 沙箱动态验证：未改任何产品代码；动态验证仅用无副作用命令，CWD 与 `DEEPTUTOR_HOME` 均指向 /tmp 沙箱，不启动服务器、不联网（`doctor` 未加 `--online`，services/doctor.py:376 注明离线）。
- 去重：命令面/参数/help 文案一致性由 scan-cli-surface（分支 `agent/agen663-cli-surface`，evidence/cli-surface-20261004/report.md）覆盖，本报告不重复其 N1-N7/H1-H4 条目，仅在交叉处引用（X1-X7 逐条复核并标注复核结果）。
- 判定分级：✔ 一致 ｜ ⚠ 不一致 ｜ ✗ 缺陷。动态结论标注 `[dyn]`，其余为静态结论。

## 0. 运行环境

- typer 0.26.8 / click 8.4.2（`/Users/Shared/DeepTutor/.venv`；pyproject.toml:35 只约束 `typer>=0.9.0`，click 版本未钉）。
- 动态用例 14 个：`data/cases.tsv`（逐用例 exit / stdout / stderr 字节数）；原始捕获在 `data/results/`；脚本在 `scripts/`。

## 1. 全量命令退出码表（静态，path:line 可复核）

约定现状基线：**失败=1（typer.Exit code=1）、用法错=2（typer/click UsageError，框架自动）、取消=0 或 1 或 130（三口径并存）**。全部 55 条命令（6 顶层 + 15 组）逐条如下；"错误通道"指失败消息写往的流。

### 顶层（main.py）

| 命令 | 成功 | 失败 | 用法错 | 取消 | 错误通道 | 锚点 |
|---|---|---|---|---|---|---|
| run | 0 | 1（多数为未捕获异常→traceback） | 2 | Ctrl-C→0 | stdout（+traceback 走 stderr） | main.py:81-124；common.py:97,109,121,857-862 |
| start | 0 | 1（无捕获，launcher 异常→traceback） | 2 | — | stdout | main.py:127-149 |
| stop | 0 | 1 | 2 | — | stdout | main.py:159-160 |
| serve | 常驻 | 1 缺依赖 | 2；**2=--reload 与 workers>1 冲突**（唯一产品态 2） | — | stdout | main.py:185-203 |
| doctor | 0 全过 | 1 必检失败 | 2 | — | stdout（print_json） | doctor.py:62-75 |
| init | 0 保存 | 1 拒绝保存 | 2 | **130** Ctrl-C/Abort；拒绝保存也是 1 | stdout | init_cmd.py:524-538 |

### partner（partner.py）

| 命令 | 成功 | 失败 | 备注 | 锚点 |
|---|---|---|---|---|
| list | 0 | — | | partner.py:17-45 |
| start | 0 | 1（`typer.Exit(1)` 位置参数风格） | | partner.py:58-60 |
| stop | 0 | **0（not running 幂等）** | "目标不存在"口径 A | partner.py:70-74 |
| create | 0 | 1 | | partner.py:101-103 |

### chat（chat.py:44，callback；`session open` 复用同一 REPL，session_cmd.py:36）

| 场景 | 退出码 | 锚点 |
|---|---|---|
| /quit、EOF、prompt 处 Ctrl-C | 0 | chat.py:140-142,201-202 |
| --session 不存在 | 1 | chat.py:104-105 |
| --config-json / --notebook-ref 非法 | 2（干净 usage 错误）`[dyn]` | chat.py:66-70,369 |

### kb（kb.py，15 条；错误一律 stdout，全部 exit 1 除非注明）

| 命令 | 成功 | 失败 | 备注 | 锚点 |
|---|---|---|---|---|
| list | 0 | — | 空列表也是 0；json 走 print_json | kb.py:144-197 |
| info | 0 | 1 | | kb.py:203-208 |
| set-default | 0 | 1 | | kb.py:214-219 |
| create | 0 | 1（名字非法/重名/无文档/初始化失败） | | kb.py:230-264 |
| connect-kiwix | 0 | 1 | 联网命令，动态跳过 | kb.py:276-285 |
| add | 0 | 1 | | kb.py:295-328 |
| delete | 0 | 1 | 拒绝确认→`typer.Abort`→**1**（"Aborted."走 stderr） | kb.py:336-351 |
| search | 0 | 1 | | kb.py:364-408 |
| eval | 0 | 1 | 写报告失败：**唯一 stderr 错误**；写成功提示也走 **stderr** | kb.py:109-118 |
| add-github-source | 0 | 1 | 联网，动态跳过 | kb.py:496-505 |
| remove-github-source | 0 | **0（source 不存在）** | 口径 B：黄字提示 | kb.py:514-518 |
| add-web-source | 0 | 1 | | kb.py:529-538 |
| remove-web-source | 0 | **0（source 不存在）** | 口径 B | kb.py:547-551 |
| list-sources | 0 | — | | kb.py:553-600 |
| sync | 0 | **永远 0** | 无源 0（:612-614）；逐源失败打红字后 continue，全失败仍 0（:619-652） | kb.py:602-652 |

### skill / skills 双别名（skill.py，8 条）

| 命令 | 成功 | 失败 | 取消/无操作 | 锚点 |
|---|---|---|---|---|
| search | 0 | 1 HubError | | skill.py:87-91 |
| install | 0 | 1（重名/导入失败） | | skill.py:157-164 |
| login | 0 | 1 | | skill.py:208-240 |
| logout | 0（无令牌也 0） | — | 口径 B | skill.py:252-256 |
| publish | 0 发布 | 1 预检/缺 track/无令牌/发布失败 | **拒绝确认→0**（"已取消"） | skill.py:307-379（取消 :339-341） |
| update | 0 | 1 非 tty/无令牌/hub 不支持/失败 | 无技能→0；单版本→0；同版本→0；拒绝→**0** | skill.py:411-537（:435,463,468,474,521） |
| list | 0 | — | | skill.py:539-557 |
| remove | 0 | 1（不存在/只读） | 口径 A | skill.py:571-578 |

### memory（memory.py）

| 命令 | 成功 | 失败 | 锚点 |
|---|---|---|---|
| show | 0 | 1（`typer.Exit(1)` 位置参数） | memory.py:53-56 |
| clear | 0 | 1；拒绝确认→Abort→1 | memory.py:72-79 |

### plugin（plugin.py）/ config（config_cmd.py）

| 命令 | 成功 | 失败 | 锚点 |
|---|---|---|---|
| plugin list | 0 | — | plugin.py:20-40 |
| plugin info | 0 | 1 | plugin.py:80-81 |
| config show | 0 | main.yaml 读取失败被吞，仍 0 | config_cmd.py:63-66 |

### session（session_cmd.py）

| 命令 | 成功 | 失败 | 备注 | 锚点 |
|---|---|---|---|---|
| list | 0 | — | | session_cmd.py:54-57 |
| show | 0 | 1 | **json 用 `console.print(json.dumps)`（markup 可吞内容）** | session_cmd.py:60-68 `[dyn:1]` |
| open | 同 chat | 同 chat | | session_cmd.py:31-36 |
| delete | 0 | 1 | | session_cmd.py:86-92 |
| rename | 0 | 1 | | session_cmd.py:95-101 |

### notebook（notebook.py）

| 命令 | 成功 | 失败 | 备注 | 锚点 |
|---|---|---|---|---|
| list | 0 | — | | notebook.py:17-21 |
| create | 0 | 异常→traceback | **json 用 console.print（markup 可吞）** | notebook.py:23-31 |
| show | 0 | 1（损坏/不存在） | json 用 console.print（markup 可吞） | notebook.py:33-50 |
| remove-record | 0 | 1 | | notebook.py:61-76 |
| add-md | 0 | 1 文件缺失；文件不可读→未捕获 OSError→traceback；notebook 不存在→未捕获 | | notebook.py:88-110（read_text :95 在 try 外） |
| replace-md | 0 | 1 文件缺失/记录不存在；不可读→traceback | | notebook.py:112-131（read_text :124） |

### provider（provider_cmd.py）

| 命令 | 成功 | 失败 | 取消 | 锚点 |
|---|---|---|---|---|
| login openai-codex | 0 | 1（未完成/鉴权失败） | **130**（CancelledError） | provider_cmd.py:71-82 |
| login github-copilot | 0 | 1（缺 openai 包/校验失败，含网络错误） | — | provider_cmd.py:85-109 |
| login codebuddy | 0 | 1 | — | provider_cmd.py:112-165 |
| 未知 provider | — | — | 2（BadParameter）`[dyn]` | provider_cmd.py:37-39 |

### book（book.py）/ workspace（workspace_cmd.py）

| 命令 | 成功 | 失败 | 备注 | 锚点 |
|---|---|---|---|---|
| book list | 0 | — | | book.py:17-35 |
| book health | 0 | — | **book 不存在仍 0**，只给 JSON `missing:true` | book.py:37-47；deeptutor/book/engine.py:1671-1678 |
| book refresh-fingerprints | 0 | 1 不存在 | 与 health 同输入不同口径 | book.py:58-60 |
| workspace show | 0 | — | | workspace_cmd.py:11-19 |
| workspace set | 0 | 2（WorkspaceError→BadParameter） | "失败=2"特例 | workspace_cmd.py:21-30 |
| workspace reset | 0 | 2 | 同上 | workspace_cmd.py:32-41 |

### 框架层（typer/click）

| 场景 | 退出码 | 流 | 锚点 |
|---|---|---|---|
| 未知命令/未知子命令/缺参数/非法选项值 | 2 | stderr `[dyn]` | click UsageError；实测 bogus_cmd/kb_bogus_sub/doctor_fmt_bogus |
| `--help` | 0 | stdout `[dyn]` | |
| 裸 `deeptutor`（no_args_is_help） | **2**（click≥8.2 NoArgsIsHelpError=UsageError 子类；click<8.2 为 0，随版本漂移） | **stdout** `[dyn]` | click core.py:1304-1305, exceptions.py:332-339 |
| 裸命令组（如 `kb`） | 2 "Missing command." | **stderr** `[dyn]` | 实测 kb_bare |

## 2. 动态验证结果 `[dyn]`（沙箱）

| 用例 | exit | stdout | stderr | 结论 |
|---|---|---|---|---|
| `--help` | 0 | 3123B | 0 | ✔ |
| 裸 `deeptutor` | 2 | 3122B（help 全文） | 0 | ⚠ exit=2 且 help 走 stdout，与 `--help`=0 不一致；脚本无法区分"看帮助"与"用错" |
| `bogus-cmd` | 2 | 0 | 659B | ✔ 用法错→2/stderr |
| `kb`（裸组） | 2 | 0 | 665B | ✔ 但与裸顶层 app 的流相反（stderr vs stdout） |
| `kb bogus-sub` | 2 | 0 | 665B | ✔ |
| `kb list --format json` | 0 | 3B `[]` | 0 | ✔ 空库 json 干净 |
| `memory show bogus` | 1 | 149B | 0 | ✗ 错误在 stdout |
| `plugin info bogus` | 1 | 19B | 0 | ✗ 错误在 stdout |
| `provider login bogus` | 2 | 0 | 765B | ✔ |
| `doctor --format bogus` | 2 | 0 | 664B | ✔（doctor 是唯一校验 --format 取值的命令，cli-surface N3） |
| `chat --config-json "{bad"` | 2 | 0 | 754B | ✔ 干净 usage 错误 |
| `run chat hi --config-json "{bad"` | 1 | 0 | **7820B rich traceback** | ✗ 同一解析错误，chat 干净 2、run traceback 1（复核 cli-surface X2 成立） |
| `session show bogus-id` | 1 | 36B | 0 | ✗ 错误在 stdout |
| `doctor --format json` | 1 | 1179B | 0 | ✔（沙箱无 LLM 配置，必检失败→1，与 doctor.py:74-75 一致；本次输出为纯 JSON，无日志混入） |

原始数据：`data/results/*.{code,out,err}`、汇总 `data/cases.tsv`。

## 3. `--json` 污染分析

### 3.1 日志默认进 stdout（结构性风险）✗

- CLI 入口 import 时即 `configure_logging()`（deeptutor_cli/main.py:29）。
- `console_output` 默认 True（deeptutor/logging/config.py:12），处理器挂 **sys.stdout**（deeptutor/logging/configure.py:55）；loguru 桥接后同样进 stdlib→stdout（loguru_bridge.py:16-27）。
- 动态证明 `scripts/pollution_probe.py`（结果 `data/probe_stdout_log_pollution.out`）：任一库代码 `logging.warning(...)` 的日志行与命令数据同流混排：
  ```
  WARNING deeptutor.test - POLLUTION-PROBE log line on stdout
  {} JSON-DATA-MARKER
  ```
- 影响面：`run --format json`（NDJSON，common.py:185-200）、`kb list/search/eval --format json`、`doctor --format json`、`book health`、`kb info` 等 stdout-JSON 契约，一旦任何路径触发日志记录即被污染。本次实测的 doctor/kb list 未触发日志，属"潜伏缺陷"：干净与否取决于库代码恰好打不打日志，对脚本不可预期。
- 另两处 stdout 噪声源：`maybe_run` 捕获 Ctrl-C 打 "Interrupted."（common.py:861，会混入 run --format json 的 NDJSON 流）；中断回合同样（common.py:261）。

### 3.2 JSON 被 Rich markup 吞字符 ✗ `[dyn]`

`console.print(json.dumps(...))`（默认 markup=True）会静默删除 `[...]`、`[/]` 序列。Rich 层实测（`scripts/markup_probe.py`，输出 `data/markup_probe.txt`）：

- 输入 `{"title": "quiz [review] draft", "note": "x[/]y", "ok": true}`
- `console.print` 输出 → `{"title": "quiz  draft", "note": "xy", "ok": true}`（**数据损坏**）
- `console.print_json` 输出 → 原样保留 ✔

受影响发射点（静态）：
| 命令 | 锚点 |
|---|---|
| `notebook create` | notebook.py:31 |
| `notebook show --format json` | notebook.py:50 |
| `session show --format json` | session_cmd.py:68 |

安全的 JSON 发射点：`console.print_json`（kb 全部、doctor.py:71、book.py:47,61、config_cmd.py:68、plugin.py:56,64）与 `run --format json`（common.py:195-200 显式 `markup=False, highlight=False, soft_wrap=True`）。

### 3.3 --format 覆盖面（引用 cli-surface N2/N3，不展开）

`--format` 仅 run/kb list/kb search/kb eval/doctor/notebook show/session show 有；doctor 是唯一校验取值的命令。

## 4. stdout/stderr 分工现状

- **全包错误几乎全走 stdout**：共享 `console = Console()`（common.py:24，默认 stdout）；另有 5 个模块各自实例化 Console（config_cmd.py:13、kb.py:28、memory.py:17、partner.py:13、plugin.py:16；init_cmd.py:428 向导内再建 1 个）——统一改 stderr 时容易漏改。`[dyn]` 三个 not-found 用例全部实测 stdout。
- **唯一 stderr 用例**：kb.py:116（eval 报告写盘失败）、kb.py:118（写盘成功提示）。做法正确（信息性提示与数据分流），但与全包其余成功提示（stdout）不一致。
- 框架层用法错误（usage/Aborted）走 stderr `[dyn]`，与产品层错误（stdout）形成同一进程两种分工。
- 后果：`deeptutor kb info x 1>/dev/null` 时错误被吞、`2>/dev/null` 时照常显示（假成功表象）；所有 stdout-JSON 命令的错误与数据同管道混流。

## 5. 不一致清单（新增编号 C*；cli-surface X1-X7 复核标注）

| # | 位置 | 判定 | 问题 |
|---|---|---|---|
| C1 | common.py:24 及 5 个模块级 Console | ✗ | 错误系统性走 stdout；仅 kb.py:116 例外。复核 cli-surface §5 成立，本报告补齐逐命令映射与动态证据 |
| C2 | deeptutor/logging/configure.py:55 + config.py:12；common.py:261,861 | ✗ | 日志/中断提示默认进 stdout，与全部 stdout-JSON 契约冲突（动态证明机制成立，实测样本未触发属潜伏态） |
| C3 | notebook.py:31,50；session_cmd.py:68 | ✗ | JSON 经 `console.print`（markup 开）发射，`[...]`/`[/]` 内容被静默吞掉（Rich 层动态证明） |
| C4 | init_cmd.py:526,538；provider_cmd.py:79；skill.py:339-341,474,521；kb.py:339；memory.py:79；common.py:857-862 | ⚠ | 取消语义四口径：init 拒绝保存=1、init Ctrl-C=130、provider codex 取消=130、skill 拒绝确认=0、kb/memory 拒绝确认=Abort→1、run/chat Ctrl-C=0 |
| C5 | main.py:200-203 | ⚠ | `serve` 把"--reload 与 workers>1 冲突"定为 exit 2，与框架用法错 2 撞码，脚本无法区分"参数拼错"与"参数组合非法" |
| C6 | kb.py:514-518,547-551；partner.py:70-74；skill.py:252-256；book.py:37-47 + engine.py:1676-1677 | ⚠ | "目标不存在"口径 B（幂等 0 / JSON missing 标记）vs 口径 A（1）：kb remove-*-source、partner stop、skill logout、book health 为 0；kb info/search/add、session show/delete/rename、skill remove、plugin info、book refresh-fingerprints、memory show 为 1。复核 cli-surface X4 成立并补 book health 证据 |
| C7 | kb.py:619-652 | ⚠ | `kb sync` 逐源失败仅打红字，永远 exit 0。复核 cli-surface X6 成立 |
| C8 | main.py:111-124（run）；notebook.py:95,124；init_cmd.py:449-460 | ✗ | 未捕获异常→traceback（exit 1）：run 的 --config-json/--config/--notebook-ref 解析（动态实证 7820B traceback，chat 同输入=干净 2，复核 X2/X1 成立）；notebook add-md/replace-md 文件不可读（新增）；init 端口非数字（复核 X5 成立） |
| C9 | pyproject.toml:35（typer>=0.9.0 未钉 click）；click core.py:1304, exceptions.py:332-339 | ⚠ | 裸 `deeptutor` 退出码随 click 版本漂移（<8.2 为 0，≥8.2 为 2 `[dyn]` 实测 2）；且 help 流向 stdout（顶层）vs stderr（命令组）不对称 |
| C10 | memory.py:56,74；partner.py:60,103 | ⚠ | `typer.Exit(1)` 位置参数风格（纯风格项，cli-surface N6 已列，此处仅登记引用） |
| C11 | kb.py:118 | ⚠ | 唯一的 stderr 成功提示（eval 报告写盘），方向正确但孤立 |
| C12 | config_cmd.py:63-66 | ⚠ | config show 吞 main.yaml 读取异常仍 exit 0，降级信息无失败信号 |

## 6. 收敛建议

1. **错误通道统一**（修 C1）：common.py 提供 `err_console = Console(file=sys.stderr)`，产品层失败/警告一律走它；5 个模块级 Console 收敛为共享的 stdout/err 两实例。保持 kb.py:116 现状，把 C11 的"成功但含副作用提示"（如 eval 报告路径）也标准化到 stderr。
2. **退出码契约成文**（修 C4/C5/C6）：约定 0=成功（幂等 not-found 须注释声明）、1=运行失败、2=仅限用法错、130=中断。`maybe_run` 对 KeyboardInterrupt 改 exit 130；确认拒绝统一一个口径（建议 0，与 skill 一致，废除 Abort 撞 1）；`serve` 冲突改 exit 1 或专用码；README 增加"Exit codes"节。
3. **JSON 纯净性**（修 C2/C3）：`--format json` 激活时强制 `console_output=False` 或把日志控制台流改挂 stderr（CLI 模式下）；notebook.py:31,50、session_cmd.py:68 改 `console.print_json`；run 的 NDJSON 已安全，保持。
4. **消灭 traceback 类失败**（修 C8）：run 的三个解析函数包成 `typer.BadParameter`（对齐 chat.py:66-70 写法）；notebook 两个 read_text 加 try→`typer.Exit(code=1)` 带红字。
5. **kb sync 反映结果**（修 C7）：收集逐源结果，任一失败 exit 1（或 `--fail-fast`），结束时打印汇总行。
6. **钉住框架行为**（修 C9）：`typer`/`click` 版本下限钉到实测过的组合（click>=8.2 语义），或在 main.py 捕获 `NoArgsIsHelpError` 显式 `ctx.exit(0)`，避免裸 app 退出码随依赖升级漂移。
7. **可测性**：现有 tests/cli 仅断言 0/1（36 处 0、8 处 1）；建议补 2/130 断言与"错误必须出现在 stderr"的管道断言，防回退。

## 7. 复现

```bash
cd <沙箱CWD>
DEEPTUTOR_HOME=$PWD/home PYTHONPATH=<worktree> bash scripts/run_cases.sh   # 14 用例 → data/results/
DEEPTUTOR_HOME=$PWD/home PYTHONPATH=<worktree> python scripts/pollution_probe.py
python scripts/markup_probe.py
sha256sum -c SHA256SUMS
```

环境：typer 0.26.8 / click 8.4.2 / Python 3.13（.venv）。退出码行为对 click 版本敏感处已在 C9 标注。
