# deeptutor_cli 零测试模块 triage（AGEN-1338）

- 基线：`origin/main` @ `6cf793bd8`（v1.6.14，2026-10-09 fetch）
- 范围：`deeptutor_cli/**`，只读扫描，未改任何产品代码
- 产物：本目录（report.md、summary.json、cli_zero_raw.json、cmd_coverage_raw.json、两个可复算脚本、SHA256SUMS）

## 总量

| 指标 | 值 |
| --- | --- |
| 模块数 | 23（6,498 LOC） |
| 零直接测试引用 | 10（其中 2 个为入口垫片） |
| **入选补测种子** | **6** |
| 因已间接覆盖剔除 | 2（config_cmd、workspace_cmd） |

## 口径（全部可复算）

- **零测试（直接引用=0）**：`scan_cli_zero.py` 在 `tests/` 与 `web/tests` 全量扫描模块引用（`import X` / `from X import` / patch 字符串；包内相对导入 `from .X import` 另计）。引用数=0 即零测试。
- **命令覆盖**：`compute_cmd_coverage.py` 对 `tests/` 全部 `.invoke(` 调用做括号配平，提取参数表内的引号字面量；组命令记为已覆盖当且仅当组名出现且命令名出现在其后同一参数表内；根命令（doctor/init）只看命令名。组名与别名（如 `skill`/`skills`）从 `main.py` 的 `add_typer`/`register_*` 接线自动推导。
- **fanin**：仓库非测试源码（`deeptutor/`、`deeptutor_cli/`、`scripts/`）import 该模块的文件数（含包内相对导入）。
- **未覆盖面**：命令模块 = 注册命令数 − 被测调用覆盖的命令数；helper 模块 = 无任何直接测试引用的公共符号数。
- **入选条件**：零直接引用 且 未覆盖面 > 0（垫片 `__init__.py`/`__main__.py` 剔除）。
- **排序口径**：未覆盖面 降序 → LOC 降序 → path 升序。逐项数字见 `summary.json` 与两份 raw JSON，可复算。

## 入选清单（CLI 轴补测种子，6 个）

| # | path | LOC | fanin | 未覆盖面 | 职责 / 建议测试焦点 |
| --- | --- | --- | --- | --- | --- |
| 1 | `deeptutor_cli/notebook.py` | 131 | 1 | 4 命令：list、create、show、remove-record | 笔记本 CRUD 命令组（DeepTutorApp 门面）。焦点：沿用 `tests/cli/test_notebook_cli.py` 的 fake 模式补 list/create；show 的 `NotebookCorruptedError`→exit1、缺失→exit1、`--format json`；remove-record 的 corrupted 与 record 缺失分支。 |
| 2 | `deeptutor_cli/partner.py` | 103 | 1 | 4 命令：list、start、stop、create | IM 伙伴生命周期命令组（partners 服务管理器 + asyncio.run）。焦点：monkeypatch `get_partner_manager`；list 空/非空表格；start/stop 的 `RuntimeError`→exit1 与未运行分支；create 的 `--soul` 写入与 auto_start 失败。 |
| 3 | `deeptutor_cli/session_cmd.py` | 101 | 1 | 4 命令：show、open、delete、rename | 共享会话命令组（异步门面）。焦点：monkeypatch `DeepTutorApp` 异步方法；show 缺失→exit1、`--format json`；delete/rename 失败分支；open 仅断言 `ChatState` 转发进 `_chat_repl`，不进入交互。 |
| 4 | `deeptutor_cli/_tool_result.py` | 166 | 1 | 3 公共符号：ToolResultBuffer、ToolResultEntry、truncate_for_display | 工具输出截断预览与 /show 展开缓冲，纯逻辑无 I/O（docstring 自述可脱离 REPL 测试）。焦点：`truncate_for_display` 的 head_lines<=0、恰好等于、超长单行硬截断与 hidden 计数；Buffer 环形容量与按 id 取回。成本最低的一档。 |
| 5 | `deeptutor_cli/book.py` | 61 | 1 | 3 命令：list、health、refresh-fingerprints | 交互式 Book 命令组（BookEngine）。焦点：monkeypatch `get_book_engine`；list 空库/含 stale 标注；health 的 JSON 结构；refresh-fingerprints 返回 None→exit1。 |
| 6 | `deeptutor_cli/memory.py` | 99 | 1 | 2 命令：show、clear | 轻量记忆查看/清理命令组（services.memory）。焦点：monkeypatch store/paths；show 的 L3/L2/单文档/未知名 exit1 与空文档提示；clear 的无 `--force` 确认 Abort、`--force` 删除、未知目标 exit1。 |

排序依据：notebook/partner/session_cmd 未覆盖面 4（LOC 131>103>101）→ _tool_result/book 未覆盖面 3（LOC 166>61）→ memory 未覆盖面 2。

## 排除与理由

- `deeptutor_cli/config_cmd.py`（167 LOC）：零直接引用，但 apply/providers 被 `tests/cli/test_agent_setup.py`、show 被 `tests/cli/test_config_cli.py` 间接覆盖，未覆盖命令数=0。
- `deeptutor_cli/workspace_cmd.py`（44 LOC）：show/set/reset 全部被 `tests/cli/test_workspace_cli.py` 覆盖，未覆盖命令数=0。
- `__init__.py`/`__main__.py`：入口垫片（7/5 LOC），无可测行为。
- 其余 15 个模块均有直接测试引用（tests/cli/ 19 个文件），属 weak/coverage 轴，不在本零测试清单内。

## 去重结论

- 全状态 issue 检索（notebook cli / partner / memory cli / book cli / tool_result / session_cmd / config_cmd / workspace_cmd / deeptutor_cli 逐词）+ backlog 全量（53 张）核对：**6 个入选模块均未建卡，去重剔除 0 个**。
- 卡面点名的 guide-cli / scan-cli-surface / scan-cli-exit-codes 为清点/导读类，按卡面说明不构成补测去重。
- 相近卡均为服务层/路由层，与本清单目标模块不重叠：AGEN-927（services/notebook analysis_agent）、AGEN-855/826/763/1145（partners 服务层与路由）、AGEN-827/1263（services/book.py 与 web 阅读导航）。

## 与 weak242 / web 两轴的互补性

CLI 轴 6 个入选目标全部为 typer 命令组或纯 helper，测试入口统一为 `typer.testing.CliRunner` + monkeypatch 门面/服务（`tests/cli/` 既有模式），与 weak242 轴（Python 服务/子代理）和 web 轴（vitest 前端）无目标文件重叠。

## 复现

```bash
git fetch --multiple origin myfork
git worktree add -b <branch> <path> origin/main   # 6cf793bd8
python3 evidence/cli-zero-triage-20261009/scan_cli_zero.py . evidence/cli-zero-triage-20261009/cli_zero_raw.json
python3 evidence/cli-zero-triage-20261009/compute_cmd_coverage.py . evidence/cli-zero-triage-20261009/cmd_coverage_raw.json
```
