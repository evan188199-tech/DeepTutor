# verify: 六份 20261007 扫描报告对最新 main 的结论漂移复核（AGEN-1091）

- 复核日期：2026-10-07 · 只读复核，未改产品代码，未重生成对方报告
- 基线对照：六份报告基线 origin/main `f07029cfcf2c8dfccdb671cdfc343db8334f5741`（release v1.6.13）== 最新 origin/main `f07029cfcf`（2026-10-07 `git fetch --multiple origin myfork` 后 `git ls-remote origin main` 逐字一致，main 零推进）
- 结论预览：**仍成立 55 / 已失效 0 / 相对基线新增漂移 0**
- 复核方法：
  1. 新 worktree（分支 `verify/scan-20261007-reports`）@ origin/main `f07029cfcf`；主工作区零触碰
  2. 六份报告基线与最新 main 为同一 commit，产品树按提交同一性整体承继；再逐条重对报告 path:line 锚点 55+ 处确认报告本身与代码相符
  3. openapi-quality 按口径只做计数级复核：重跑对方扫描器（只读）比对全部分级计数
  4. scripts-inventory 重跑引用 rg（CI/文档/运行时轴）；web-timers 全量 23 锚点回读
  5. 上游动作检查：开放 PR（gh pr list --author @me，2026-10-07）4 条均与本批扫描轴无关；main 无推进

## 一、regex-risk-20261007（AGEN-1001）：19/19 仍成立

分级口径复核：`grade_counts = low 1125 / review 66 / medium 19 / high 0`（合计 1210，与报告一致）。19 条 medium 锚点逐条回读，行号与模式全部命中：

| # | 锚点 | 结论 | 依据 |
|---|---|---|---|
| 1-4 | `agents/loop/dsml_tool_calls.py:83/211/255/261` | 仍成立 | `_INVOKE_RE`/`DSML_SIGNAL_RE`/`_PARAM_RE` 于 :39/:34/:43 定义，模式与报告逐字一致；:83 在循环内 `finditer` 全量重扫仍在 |
| 5 | `agents/research/utils/json_utils.py:25` | 仍成立 | `re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)` 逐字在行 |
| 6 | `agents/_shared/json_output.py:18` | 仍成立 | `<think\b[^>]*>.*?</think>` 在行（`re.match` + DOTALL） |
| 7 | `agents/_shared/json_output.py:30` | 仍成立 | `re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)` 在行 |
| 8 | `agents/question/pipeline.py:1390` | 仍成立 | `re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)` 在行 |
| 9 | `agents/vision_solver/vision_solver_agent.py:157` | 仍成立 | 同 5 形态在行 |
| 10-12 | `services/skill/service.py:352/951`、`services/skill/hub.py:917` | 仍成立 | `_FRONTMATTER_RE`（service.py:63 / hub.py:891 定义）`^---\s*\n(.*?)\n---` 与报告一致；:352/:951/:917 为调用行 |
| 13-14 | `services/web_source/html_extractor.py:333/347` | 仍成立 | `<title[^>]*>(.*?)</title>`、`\s*[|｜]\s*[^|]+$` 两行逐字在 |
| 15-16 | `services/web_source/markdown.py:7/22` | 仍成立 | `_LEADING_SOURCE_COMMENT`（:7-10 多行定义）模式一致；:22 `fullmatch` 在 |
| 17-18 | `web/components/space/SkillsSection.tsx:73`、`PersonasSection.tsx:58` | 仍成立 | `md.match(/^---\s*\n[\s\S]*?\n---\s*\n?/)` 在行 |
| 19 | `web/lib/deep-research-report.ts:53` | 仍成立 | `replace(/^(# [^\r\n]*?)(?=##\s+\d+\.\s*)/, ...)` 在行 |

## 二、unicode-normalize-20261007（AGEN-1002）：H/M 5/5 仍成立（L1/L2 顺带核对一致）

| 条目 | 结论 | 依据（新基线锚点重对） |
|---|---|---|
| H1 raw/ NFC/NFD 混写 | 仍成立 | `knowledge.py:379` `_sanitize_path_segment` 仅删坏字符不归一（:381）；:3038 `_resolve_kb_raw_file_or_404` 精确字节路径（:3055 return）；入口 NFC 仍只在 `document_validator.py:97` |
| H2 PageIndex manifest 键原文 | 仍成立 | `pipeline.py:202` `upsert_doc(manifest, path.name, ...)`；:273 全名→basename 两次精确查找；`storage.py:95-103` `docs[file_name]` 直写 |
| H3 课程名 casefold 查重 | 仍成立 | `courses.py:324-325` `name.casefold()` 相等判重，无 NFC |
| M1 搜索链路无 NFC | 仍成立 | `mcp/catalog/loader.py:114/141/168`、`session/pocketbase_store.py:679`、`reading_hints.py:335` 全在；B 表第 3 行 `chat_hints.py:183-184` `\w` 剔除+casefold 也在 |
| M2 前后端折叠/排序口径不一 | 仍成立 | `knowledge.py:3075` `str(p).lower()` 排序、`courses.py:331` `casefold` 键、`KbDocumentList.tsx:99/104` `toLowerCase().localeCompare` 全在；C/D 表其余「中」行（`partners/commands.py:293/298/362/368`、`partner_groups/manager.py:1538/1540/1630`）逐行命中 |
| L1/L2（顺带） | 一致 | `knowledge.py:893-898` URL 精确集合匹配；`co_writer.py:736-744` `_docx_download_filename` 无归一 |

## 三、signal-handlers-20261007：5M+7L 12/12 仍成立

| 条目 | 结论 | 依据 |
|---|---|---|
| M#2 launcher handler 内 print | 仍成立 | handler 注册 `launcher.py:1036-1041,1064`；`request_shutdown` :1485-1491 内同步 `_log(...)`→print 链仍在（:1491） |
| M#9 opencode atexit 不回收 | 仍成立 | `opencode_server.py:197-201` `_atexit_cleanup` 只 `_terminate_sync`（:171-176 仅 `terminate()`，无 wait/kill）；对比 `shutdown_servers` :180-194 有 wait(5s)+kill |
| M#10 claude 无界 waitpid | 仍成立 | `claude_models.py:222` SIGTERM、:226 `os.waitpid(pid, 0)` 无超时；`_CAPTURE_TIMEOUT` 于 :34 注释边界 |
| M#13 update worker 无信号覆盖 | 仍成立 | `update_worker.py` 全文件 signal/atexit 计数 **0**；:96 `start_new_session=True`；`except Exception` :134 / `mark_failed` :138 捕不到 SIGTERM；`launcher.py:1233`（只捡 pending）、:1272（只处理 restarting） |
| M#14 dev.mjs 包装进程挂起 | 仍成立 | `web/scripts/dev.mjs:63-68` `process.on(signal, () => child.kill(signal))` + exit 回调 `process.kill(process.pid, signal)` 逐行在 |
| L#4 `_terminate` KILL 后不 wait | 仍成立 | `launcher.py:254-268`（:263 wait(8) → :266 KILL → 无后续 wait） |
| L#5 Windows 分支 spawn taskkill | 仍成立 | `launcher.py:236-247`（:240 `subprocess.run` 在清理路径可达） |
| L#7 端口只杀监听者 | 仍成立 | `launcher.py:499-523` `_send_tree_signal(pid, None, ...)`（:504/:513 pgid=None→:251 单 pid kill；:507-518 轮询 5+3s） |
| L#8 不健康前端无 wait | 仍成立 | `launcher.py:1007-1022`（:1022 仅 `sleep(0.5)`） |
| L#15 sandbox runner 无 SIGTERM | 仍成立 | `sandbox/runner/server.py:356-370` 只捕 KeyboardInterrupt（:367）；`backends.py:453` `killpg(SIGKILL)` 兜底在 |
| L#20 mineru cancel 无升级 | 仍成立 | `mineru/models.py:163-172`（:166 仅 `terminate()`，无 wait/kill） |
| L#23 fork 探针无界 waitpid | 仍成立 | `data_volume.py:186-198`（`waitpid(pid, 0)` 于 :195，无超时） |

## 四、openapi-quality-20261007（AGEN-1000）：计数级复核全对，仍成立（1/1）

- 重跑 `scan_openapi_quality.py`（只读，输出落本卡临时目录，未写入对方 evidence）：**全部计数与报告一致** —— HTTP 路由 637 / WS 9；`missing_response_model` 332H/105M/140L；`undocumented_4xx` 17H/233M；`undocumented_5xx` 105L；`envelope_drift` 6M；`optionality_drift` 4M；`pagination_present` 23 info / `pagination_structure` 6M / `pagination_validation` 14M；分级合计 **349H / 368M / 245L / 23 info**；`response_model` 声明 60；未文档化 4xx 路由 250；全 routers `responses=` 仅 1 处（`settings.py:2174`，audio content，非 4xx 文档化）
- D/C 段抽样逐条属实：auth 登录包封漂移（`auth.py:817-818` 禁用分支 `{ok,message}` vs :838-840 正常分支 5 键；401 经 `HTTP_401_UNAUTHORIZED` 于 :454/:462/:829，无 responses=）；settings 角色分支（:895-898 非 admin 仅 `{ui}`，:905 admin 另有键）；system 受限分支（`system.py:418` `{available: False}`）；`Form(None)` 注解（`knowledge.py:3316-3317` `str`/`list[str]` 裸注解）；裸分页（`memory.py:681`、`dashboard.py:21`）；sessions 无 total 包封（:135 `return {"sessions": sessions}`，报告引 :117-133 为处理体内区间，实际 return 行 :135 —— 精度注记，结论不变）；skills.py:280-297 404/403/409 裸 raise；Top15 锚点抽 4 处（courses.py:96、knowledge.py:3122/3311、reading_extensions.py:195/363）全命中

## 五、web-timers-20261007（AGEN-978）：medium 13/13 仍成立

- findings.json 23 条锚点全量回读：14 条 timer 类（WT-0003~0019）**逐条 setTimeout 命中锚行**；9 条 listener 类锚行均为 `addEventListener`，与报告 low 分级一致
- 报告最终口径 medium 13（WT-0004 复核降级 low，其锚点 `ToastViewport.tsx:25` `window.setTimeout` 仍在，模式存在但分级为 low 合理）；13 条 medium 锚点全部命中：PartnerChat.tsx:734/767、ReaderPane.tsx:696、MediaReadingStage.tsx:433、EpubDocumentView.tsx:623、FilePreviewDrawer.tsx:156、CourseConventions.tsx:49、KbFilePreview.tsx:201、PartnerLinkModal.tsx:75、PartnerSeat.tsx:74、WhisperRoomChip.tsx:19、ReadingComposer.tsx:113、ReadingWorkspace.tsx:327（报告表 WT-0018 行号 :327 与 findings 一致）

## 六、scripts-inventory-20261007：候选清理 5/5 仍成立

- `scripts/` 仍为 18 个文件；五个候选逐一重跑引用 rg（排除 evidence/ 与脚本自身）：
  1. `_cli_kit.py` — 现行引用仅 `tests/scripts/test_cli_kit.py:11`；历史 `ver1-2-4.md:23`（描述的功能与现 31 行文件不符的漂移仍在）
  2. `export_discord_history.py` — 仅 `tests/scripts/test_export_discord_history.py:14`
  3. `start_backend.bat` / 4. `start_frontend.bat` — 现行零引用；仅历史 `ver1-4-5.md:63`
  5. `update.py` — 仅 `tests/scripts/test_update.py:10`；`consolidator/__init__.py:26` 的 "update.py" 假阳性描述属实（指包内 modes/update.py）；`test_app_update.py:233` 为 app_update.py 假阳性，与报告口径一致
- 观察项复核一致：`web/contracts/README.md:13` 表述偏差、fr locale 残留均未变（未逐行复验 fr 行，属报告观察项非清理候选）

## 七、汇总

- 六份报告可行动结论合计 **55 条：仍成立 55 / 已失效 0**；相对基线新增漂移 **0**
- 根因：报告基线 `f07029cfcf` 至今仍是 origin/main HEAD，产品树零推进，结论按提交同一性 + 锚点重对整体承继
- 报告精度注记（非 main 漂移，不影响结论）：sessions 列表 return 实际行 :135（报告区间 :117-133）；skill/hub.py `_FRONTMATTER_RE` 定义 :891、调用锚 :917 正确；web-timers WT-0015 文件名 ReaderPane（报告表与 findings 一致）
- 复核环境：worktree `dt-agen1091-verify-wt` @ `f07029cfcf`，分支 `verify/scan-20261007-reports`；openapi 计数复核以对方脚本 check 模式运行不落盘到对方 evidence；复核期间仅本分支新增 `evidence/verify-scan-20261007/` 目录
