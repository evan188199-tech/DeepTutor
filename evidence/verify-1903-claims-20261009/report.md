# verify: #1903 看门狗/进程树断言对最新 main 复核

- 日期：2026-10-09
- 复核对象：HKUDS/DeepTutor `origin/main` = `6cf793bd868ba5ecbe64722936d4be8fab5a01df`（release: v1.6.14）
- 说明：该提交正是 #1903 自述的审查基线（v1.6.14 / dev tip `6cf793bd`），即"最新 main"与 issue 审查的代码完全一致，因此不存在"已变"空间，复核结果直接对 issue 静态断言成立性负责。
- 方法：纯静态复核（读文件 + `rg` 全仓检索），未启动任何子进程/服务，未修改任何产品代码。工作区为 fetch 后新建 worktree + 新分支（只读使用）。

## 三态总表

| # | 断言（#1903） | 判定 | 证据（path:line） |
|---|---------------|------|--------------------|
| 1 | 看门狗空闲限额 600s、总时长限额 7200s | 成立 | `deeptutor/services/parsing/engines/mineru/local.py:28`（`_LOCAL_PARSE_IDLE_TIMEOUT_SECONDS = 600`）、`:29`（`_LOCAL_PARSE_TIMEOUT_SECONDS = 7200`）、`:251-254`（两值同时参与到期判断） |
| 2 | 活动时钟仅由消费到的非空 stdout/stderr 行刷新 | 成立 | `local.py:227`（`stderr=subprocess.STDOUT` 合流）、`:269`（`for raw_line in process.stdout`）、`:270-273`（空行 `continue`，仅非空行写 `activity[0] = time.monotonic()`）；`activity` 全文件仅 `:239`（初始化）与 `:273`（行刷新）两处写点，无解析里程碑等其它刷新来源 |
| 3 | 任一限额到期即 terminate 子进程 | 成立（限受管路径） | `local.py:255-264`（`interrupted.append(TIMEOUT)` 后 `process.terminate()` → `wait(timeout=3)` → 升级 `process.kill()`）；补充：看门狗仅在 `current_run()` 非空时武装（`:240, :266-267`），脱离 indexing run 的裸调用（如 CLI `main()`）无看门狗、两限额均不生效——与 issue "managed watchdog" 措辞一致，判成立并记偏差条目 A |
| 4 | 以普通 `subprocess.Popen` 启动 CLI | 成立 | `local.py:224-233`；未传 `creationflags`/`start_new_session`/`preexec_fn`，全仓 `rg "creationflags|start_new_session|preexec_fn"` 0 命中 |
| 5 | watchdog/最终清理只对直接子进程 terminate/kill | 成立 | watchdog：`local.py:258, :261`；finally 清理：`local.py:363-369`；全部作用于同一个 `process`（`:224` 的直接子进程），无任何树遍历 |
| 6 | 无 Windows Job Object 或等价后代回收 | 成立 | 全仓 `rg "JobObject|AssignProcessToJobObject|win32job|CREATE_BREAKAWAY|taskkill|killpg"` 0 命中；psutil 仅用于 stale-owner PID 身份校验（`deeptutor/knowledge/indexing_run.py:140, :240`）与内存探测（`deeptutor/runtime/memory_probe.py`），均不杀后代进程，且不在本路径上 |
| 7 | 后代继承 stdout 句柄可使读循环到不了 EOF | 成立（静态结构成立） | `local.py:226-227`（PIPE 合流单管道）、`:269-285`（读循环阻塞至 EOF，`process.wait()` 在循环之后）；`:258/:261/:365/:368` 只杀直接子进程，后代持有的写端句柄不会被回收；主线程若阻塞在读循环，`finally`（`:358-384`）不执行，watchdog 杀掉直接子进程也无法解开阻塞。静态结构与 #1903 描述一致，未运行复现（与 issue 同证据级别） |

统计：成立 7 / 不成立 0 / 已变 0。

## 偏差与补充条目

- A（对断言 3 的范围限定）：600s/7200s 限额与 terminate 行为只在受管 indexing run 内生效（`local.py:240` 判空后不建看门狗线程）。#1903 用词为 "managed watchdog"，与实现一致，不构成反驳。
- B（对断言 2 的澄清）：`_ON_OUTPUT_MIN_INTERVAL = 0.5`（`local.py:27`）只限流 `on_output` 回调（`:275-280`），不影响 `activity[0]` 刷新——空闲时钟确实逐非空行刷新，#1903 描述准确。
- C（对断言 7 的边界）：POSIX 上 `terminate()` 同样只作用于直接子进程（未 `start_new_session`，无 `killpg`），故"后代存活拖住读循环"的结构性风险不限于 Windows；Windows 下句柄继承语义使其更必然（子进程默认继承管道写端）。
- D：同包 `models.py:166`（模型下载）与 docling `_install.py:174`、`local_worker.py:88-92` 呈相同"只杀直接子进程"模式，与本卡断言无关，仅供 up-1903 修复时参考面更宽。

## 复核命令记录

- `git -C /Users/Shared/DeepTutor fetch --multiple origin myfork --prune`，`origin/main` → `6cf793bd868ba5ecbe64722936d4be8fab5a01df`
- `git worktree add <wt> -b verify/1903-lifecycle-claims-20261009 origin/main`
- 逐条人工读 `deeptutor/services/parsing/engines/mineru/local.py`（471 行全文）
- `rg -n "CREATE_NEW_PROCESS_GROUP|CREATE_BREAKAWAY|JobObject|job_object|AssignProcessToJobObject|pywin32|win32api|win32job|taskkill|killpg|start_new_session|preexec_fn|creationflags|psutil" --type py` → 仅 psutil 两处非清理用途（见断言 6）
- `rg -n "\.terminate\(\)|\.kill\(\)" --type py deeptutor/` → 本路径仅 `local.py:258/261/365/368`

## 结论

#1903 的全部静态断言在最新 `origin/main`（= 其审查基线 `6cf793bd`）上成立，可直接作为 up-1903 修复任务的输入；修复应覆盖偏差条目 A（裸路径无看门狗）与 C（POSIX 同构问题）。
