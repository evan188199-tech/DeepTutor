# broad-except 清单（AGEN-370）对最新 main 的漂移与 PR 覆盖复核（AGEN-944）

- **基线对照**: AGEN-370 扫描基线 `ef2d9e5c`（v1.6.12，DT-22 附录 A 同源 118 条宽捕获）→ 最新 `origin/main` `f07029cf`（v1.6.13）。注意：`origin/main` 自 AGEN-666 复核（2026-10-05）以来未前进，仍是 `f07029cf`
- **复核日期**: 2026-10-06（UTC）
- **工作副本**: `/Users/Shared/DeepTutor/dt-agen944-revbw-wt`（独立 worktree，分支 `review/broadexcept-drift-20261006`，基于 `f07029cf`）；主工作区未做任何改动，**未修改任何产品代码**
- **方法**: 复用 AGEN-370 原扫描脚本（`scan_broad_except.py`，AST 级、同口径 `deeptutor`/`deeptutor_cli`/`scripts`/`tests`）在 `f07029cf` 全量重扫；118 条基线逐条按 `path + 函数名 + try 体首行` 恒等匹配（含函数改名/类化、try 体变更的回退规则，与 AGEN-666 同规则）。18 条 HIGH 全部 + 7 条回退匹配条目 + 抽样 12 条 MEDIUM/LOW 均用非 AST 原文读取独立复核（1 条 `pass  # 注释` 形态由脚本误标，人工确认在场）。PR 覆盖按开放 PR 逐个取 diff，hunk 与基线行号（PR 均基于 `ef2d9e5c` 或行号等价旧基）对齐后再读 diff 原文确认「补日志/收窄」语义，非仅按文件名重叠。

## 1. 结论（PASS）

**118/118 条宽捕获在 `f07029cf` 全部存续：93 条同行号 + 25 条行号漂移，0 条消失，main 侧 0 条被修复**（4 个关联 PR 及其它修复 PR 均未合并）。开放 PR 已覆盖 29 条（28 完整 + 1 部分），未覆盖 89 条；其中 HIGH 18 条：13 完整覆盖 + 1 部分覆盖 + **4 条无任何开放 PR 覆盖**。另确认 v1.6.13 新增 1 条同类静默宽捕获（`document_loader.py:459`）。

| 指标 | 数值 |
| --- | --- |
| 基线条目 | 118（HIGH 18 / MEDIUM 87 / LOW 13） |
| 仍在（同行号） | 93 |
| 仍在（行号漂移） | 25 |
| 消失 / main 已修复 | 0 / 0 |
| 开放 PR 完整覆盖 | 28 |
| 开放 PR 部分覆盖 | 1（`update_worker.py:144`） |
| 无 PR 覆盖 | 89 |
| 新增同类命中 | 1 |

## 2. 行号漂移明细（25 条）

处理器本体（异常类型 / try 体 / 静默体）均未变，漂移为代码移动；7 条因 v1.6.13 类化重构函数名变化（如 `get_info` → `KnowledgeBaseManager._get_info`），按 try 体首行回退匹配并逐条原文确认。

| 原位置 | 现位置 | 说明 |
| --- | --- | --- |
| `knowledge.py:3952/4353/4402/4480/4486/4491`（HIGH ×6） | :3988/4389/4438/4516/4522/4527 | WS/进度区域整体下移 |
| `knowledge/manager.py:567`（HIGH） | :615 | `update_kb_status` |
| `knowledge/manager.py:2130`（HIGH） | :2215 | `update_folder_sync_state` |
| `launcher.py:1252`（HIGH） | :1256 | `_handoff_pending_update` |
| `llamaindex/document_loader.py:403`（HIGH） | :405 | 扫描器类化：`_describe_one` → `LlamaIndexDocumentLoader._describe_one`（同文件 :459 另有新命中，见 §6） |
| `reading.py:518` | :525 | |
| `settings.py:518/2247/1187` | :522/2269/1191 | |
| `manager.py:1295` | :1347 | `get_default` → `KnowledgeBaseManager.get_default` |
| `manager.py:1616/1623/1630` | :1701/1708/1715 | `get_info` → `KnowledgeBaseManager._get_info` |
| `telegram.py:519` | :581 | `_send_with_streaming` → `TelegramChannel._send_with_streaming` |
| `launcher.py:502/511/638/787/943` | :505/514/641/790/946 | launcher 区域整体下移 |
| `settings_spec.py:471` | :472 | |

其余 93 条同行号原位存续（含 `question.py:131/323`、`adapters.py:51/56`、`graphrag/provider.py:119`、`file_library.py:205`、`update_worker.py:144`、`client.py:204/279` 等）。逐条状态见 `drift_status.json`（`status` / `new_line` / `how`）。

## 3. 开放 PR 覆盖（逐 PR 读 diff 确认）

AGEN-370 §4 所列 4 个 PR 的覆盖主张**全部复核成立**；另发现 3 个其后开放的修复 PR 追加覆盖 9 条。全部 PR 仍未合并，故 main 侧计入 0 修复。

| PR | 覆盖条目 | 方式（diff 原文确认） |
| --- | --- | --- |
| #1706 knowledge 进度/状态/同步 | 8（knowledge ×6 + manager :567/:2130） | 保留宽捕获按级别补日志（close/send→debug，reset/进度/元数据→warning）；:4353/:4402 额外抽 `_progress_age_seconds()` 收窄到 (TypeError, ValueError) —— 即 AGEN-370 §2.2 建议的收窄方案 |
| #1704 runtime/cli 单例与自更新 | 8（launcher :146/:152/:158/:1252 + init_cmd :35/:41/:47 完整；update_worker :144 部分） | 单例 reset `pass`→`logger.exception/warning`；handoff mark_failed 双错误落 `_log`；update_worker 的 store.load 失败新增 `_log_aborted_recovery` 落盘 + return 1，但**外层 mark_failed/重启失败仍静默**（与 AGEN-370 §2.1 判断一致） |
| #1703 embedding/图片进度 | 3（client :204/:279、document_loader :403→405） | 进度回调 `pass`→`warning + exc_info` |
| #1700 DOCX 表格行 | 1（docx_converter :356） | 失败行保留占位 `(unparseable row)` + warning |
| #1707 services 吞错日志 | 4（question :323、codex_auth :872、codebuddy_provider :553、notebook :153） | question :322 先收窄 (RuntimeError, WebSocketDisconnect)、其余 warning；codex revoke warning（即 AGEN-370 §3 #7 建议）；notebook unreadable warning |
| #1715 launcher 终止可见性 v3 | 4（launcher :260/:267/:502/:511） | 4 处 `except Exception: pass` 改 `_signal_target()` 统一 warning（ESRCH/进程已消失不算失败） |
| #1731 tool-options warning v2 | 1（tool_options :97） | `pass`→按 provider/adapter 标识 warning |

合计 **29/118**（28 完整 + 1 部分），未覆盖 **89**。#1702 / #1746 / #1783 与基线无 hunk 交集；其余开放 feature PR（#1268/#1030/#1029/#1015/#751/#728/#638/#525/#329/#298/#1553/#1175 等）经 removed-broad-except 检查均未触及基线处理器；唯一例外是老 feature PR **#620**（kb-config 原子化，基线更早）会整体重写 `modes.py resolve_kb_mode`（基线 :37），若合并该条将随之重构——因无法与当前基线精确对齐且属陈旧 feature PR，**不计入覆盖**，仅在 `drift_status.json` 加 note。#1277 删除的宽捕获在 `_login_github_copilot`，与基线 `_login_codebuddy:150` 无关。

## 4. 无 PR 覆盖的 HIGH（4 条，建议后续拆卡）

| 位置 | 分型（AGEN-370） | 失败后果 |
| --- | --- | --- |
| `question.py:131`（`StdoutInterceptor.write`） | best_effort | 模拟生成期间 stdout 重定向失败无痕 |
| `snapshot/adapters.py:51`（`_iso`） | 可收窄 | fromisoformat 只抛 ValueError，收窄即可（#1707/#1764 系只覆盖 read_* 三个非宽捕获点） |
| `graphrag/provider.py:119` | best_effort | catalog 解析失败静默回退 legacy provider，可能用错模型且无日志 |
| `file_library.py:205`（`_delete_file`） | 可收窄 | 空目录清理只会抛 OSError，宽捕获掩盖循环内逻辑 bug |

## 5. 与 DT-22 漂移报告（AGEN-666）§7 的一致性

- DT-22 §7 称「118/118 在 `f07029cf` 仍全部在场、分型建议与 #1700/#1703/#1704/#1706 继续有效（4 PR 开放未合并）」——本次独立重扫结论**完全一致**：118/118 存续、0 修复、4 PR 仍开放未合并。无矛盾。
- 覆盖面的增量（非矛盾）：本次新计入 #1707/#1715/#1731 三个其后开放的修复 PR（+9 条覆盖）；AGEN-666 §7 曾列 #1752/#1753 覆盖 `codebuddy_provider.py:553`，两 PR 现已关闭，该条改由 **#1707** 覆盖——覆盖载体变更，结论不变。AGEN-666 §8 的「5 条未覆盖 HIGH」按当前开放 PR 收敛为 **4 条**（question :323 已被 #1707 覆盖）。
- 新增命中亦一致：本次在宽捕获口径下仅 1 条新静默命中（`document_loader.py:459`），即 AGEN-666 §6 的那条新 HIGH；121 → 122 的净增完全由它解释。

## 6. 新增同类命中（1 条）

| 风险 | 位置 | 函数 | try 体首行 | 说明 |
| --- | --- | --- | --- | --- |
| HIGH | `deeptutor/services/rag/pipelines/llamaindex/document_loader.py:459` | `LlamaIndexDocumentLoader._describe_group` | `image_progress_callback(completed, total)` | v1.6.13 批量重构新增的并行路径复制了 :405 同款吞回调；#1703 目前只覆盖老点 :403/:405，**不含此新点** |

## 7. 复现

```bash
cd /Users/Shared/DeepTutor/dt-agen944-revbw-wt   # f07029cf
python3 evidence/review-broadexcept-drift-2026-10-06/scan_broad_except.py . --out /tmp/rescan.json
python3 evidence/review-broadexcept-drift-2026-10-06/relocate_broad_except.py \
  <(git show agent/agen370-broad-except-scan:evidence/broad-except-scan-2026-10-04/appendix_a_baseline.json) \
  /tmp/rescan.json /tmp/relocated.json
sha256sum -c evidence/review-broadexcept-drift-2026-10-06/SHA256SUMS
```

PR 覆盖复核：`gh pr diff 1700/1703/1704/1706/1707/1715/1731 -R HKUDS/DeepTutor`，old 侧 hunk 与基线行号对齐后读原文。

## 8. 验收对照

1. **118 条逐条有状态（存续/漂移/消失/被覆盖）** — ✅ 118/118：93 存续 + 25 漂移 + 0 消失；29 条被开放 PR 覆盖（28+1 部分）、89 条未覆盖，逐条见 `drift_status.json`。
2. **与 DT-22 §7 不矛盾** — ✅ §5 逐点对照，无矛盾；覆盖载体变更处（#1752/#1753→#1707）已说明。
3. **不改产品代码** — ✅ 仅新增本证据目录；主工作区与其它 worktree 未触碰。
