# verify: 三份 20261006 报告对最新 main 的结论漂移复核（AGEN-898）

- 复核日期：2026-10-06 · 只读复核，未改产品代码，未重生成对方报告
- 基线对照：三份报告基线 origin/main `f07029cfc`（release v1.6.13）== 最新 origin/main `f07029cfc`（2026-10-06 `git fetch --multiple origin myfork` 后 `git ls-remote origin main` 与本地 ref 一致）
- 结论预览：**仍成立 23 / 已失效 0 / 相对基线新增漂移 0**
- 复核方法：
  1. 新 worktree（分支 `verify/reports-20261006`）@ origin/main `f07029cfc`
  2. `git diff origin/main myfork/scan/<branch> -- ':!evidence'`：openapi-drift / web-api-usage / mypy-adoption 三条产品树 diff 均为空 → 被扫描代码与最新 main 逐字节一致，结论按提交同一性整体承继
  3. 逐条重对报告引用的 path:line 锚点 40+ 处（下表为抽检/全对清单）
  4. 重跑 `python scripts/export_frontend_contracts.py --check`（check 模式只读、不写文件，2.5s）：仍失败，输出 `Frontend contract drift: openapi.json`，`turn-protocol.json` 不在清单——与报告完全一致
  5. 上游在修证据：开放 PR（gh pr list 全量，2026-10-06）中无契约再生成 / 契约门禁 / mypy 配置相关改动

## 一、openapi-drift-20261006（AGEN-837）：7/7 仍成立

| 条目 | 结论 | 依据（新基线锚点重对） |
|---|---|---|
| D1 PositionPayload.percentage 字段漂移 | 仍成立 | `deeptutor/api/routers/reading.py:324`、`web/contracts/generated/api.ts:14017/31888/6624` 逐字一致；`web/components/reading/ReaderPane.tsx:237` 前端 null 适配仍在 |
| D2 PositionInfo.percentage 约束漂移 | 仍成立 | `reading.py:328`（`= 0.0` 无 ge/le）、`api.ts:13997/31859/6619` 一致 |
| D3 list KB docstring 漂移 | 仍成立 | `deeptutor/api/routers/knowledge.py:2776` 与 `api.ts:1718` 一致 |
| D4 health docstring 漂移 | 仍成立 | `knowledge.py:1377` 与 `api.ts:2691` 一致 |
| 结构化错误 14 发出点 / 44 操作 / 0% 覆盖 | 仍成立 | 14 处锚点逐一命中：book.py:61/335/344/1794、space_mcp.py:89/185/201/330/337、space_cli_apps.py:103/149、notebook.py:36、settings.py:586、video_learning.py:120；前端手工解析仍在（web/lib/mcp-api.ts:281、codex-oauth.ts:163、settings-readiness.ts:40） |
| 根因：app→schema 层无门禁 | 仍成立 | `.github/workflows/tests.yml:85`（`npm run check`）与 `tests/api/test_frontend_contract_export.py:71-78`（仅 tmp_path 幂等）锚点一致 |
| 拆卡建议 A-D | 仍成立 | `--check` 重跑仍失败且仅报 openapi.json；建议指向的落点无任何上游动作 |

## 二、web-api-usage-20261006（AGEN-857）：6/6 仍成立

| 条目 | 结论 | 依据 |
|---|---|---|
| F1 rag-pipelines `${provider}/config` vs 6 条字面路由 | 仍成立 | 调用点 `web/features/knowledge/api/client.ts:505/524` 命中；契约仅 6 条字面路由 `api.ts:2917/2961/2985/3009/3057/3104`，无参数化路径 |
| F2 `resource_library=true` 死参数 | 仍成立 | `web/components/knowledge/KnowledgePage.tsx:189`、`client.ts:293`；后端 `knowledge.py:2979`（details 不读 query）、`:2964`（list 别名）一致 |
| F3 `dt_workspace` 契约不可见 | 仍成立 | `web/lib/workspace-scope.ts:8-18` scopedUrl 注入（报告引 :11 系函数体内，精确锚为 :8 定义 / :16-17 注入）；`web/lib/session-api.ts:209` 显式 `qs.set`（报告引 :213 为发起调用行）；契约 0/531 声明不变 |
| F4 `/api/knowledge-bases/list` 故意豁免 | 仍成立 | `client.ts:293` 两分支、`knowledge.py:2964` `include_in_schema=False` 一致 |
| R1-R6 复核清单 | 仍成立 | 抽检 14 处锚点全部命中：notebook-api.ts:166/372/591/628、partners-api.ts:204/535/603、video-learning-api.ts:426、visualizers-api.ts:55、cli-apps-api.ts:231、reading-api.ts:254、skills-api.ts:206、MemorySection.tsx:721、memory-graph.ts:254 |
| 裸 URL 形态 + 4 条拆卡建议 | 仍成立 | `web/lib/usage-statistics.ts:1` 仍为全仓唯一 api.ts import 方（仅取 components 类型） |

## 三、mypy-adoption-20261006（AGEN-856）：10/10 仍成立

| 条目 | 结论 | 依据 |
|---|---|---|
| 核心结论：pre-commit hook 实际检查表面 0 错误 | 仍成立 | 代码树与配置相对基线零变化，按同一性承继；两处配置锚点逐字重对无差异（量化 7 轮未重跑，见下） |
| 宽松面清单 `.pre-commit-config.yaml` | 仍成立 | :110-111 TODO 注记、:112-121 hook、:113 rev v1.13.0、:116 三参数、:117 exclude 正则、:118-121 stubs 逐字一致 |
| 宽松面清单 `pyproject.toml` | 仍成立 | :498-512 放宽开关、:515-517 `tests.*` override、:519-521 `tools.*` override 逐字一致 |
| 七轮量化表（F=97/0 … C=1940/1231） | 承继有效 | 同一 commit + 同一钉版 mypy 1.13.0，量化结果按构造不变，无需重跑 |
| 建议 1：learning/tests 覆盖缺口 | 仍成立 | exclude `^tests/`（:117）与 override `tests.*`（:516）均不匹配 `deeptutor.learning.tests.*`；`deeptutor/learning/tests/test_assessment.py:229` 锚点在 |
| 建议 2：config/readiness.py 19 处 | 仍成立 | `readiness.py:238/243` Optional 判空缺失锚点在 |
| 建议 3：subagent 两文件 29 处 | 仍成立 | `opencode_family.py:265`、`deepseek_harness.py:270` 锚点在 |
| 建议 4：partners 渠道 20 处 | 仍成立 | `matrix.py:175/494`、`telegram.py:539` 锚点在 |
| 建议 5：hub.py / request_preparer.py | 仍成立 | `skill/hub.py:432`、`session/turns/request_preparer.py:488` 锚点在 |
| 建议 6-10：开关翻转 / check_untyped_defs / routers 收编 / stubs 口径 | 仍成立 | :116、:509、:117、knowledge.py:697、agents/base_agent.py:108、tools/question/question_extractor.py:332、tools/builtin/__init__.py:30、capabilities/obsidian/vault.py:22、services/cron/service.py:134 锚点在 |

## 四、汇总

- 三份报告可行动结论合计 **23 条：仍成立 23 / 已失效 0**；相对基线新增漂移 **0**
- D1-D4 未被上游修掉（main 零推进、无相关开放 PR、`--check` 仍失败）；F1/F2 调用点行号零漂移；mypy 宽松面配置零变化
- 两处报告锚点微偏（非 main 漂移，报告自身精度问题，结论不受影响）：workspace-scope.ts 注入点实为 :8-18（报告 :11）、session-api.ts `qs.set` 实为 :209（报告 :213）
- 复核环境：worktree `dt-agen898-verify-wt` @ `f07029cfc`；`--check` 以 check 模式运行不落盘；复核期间仅本分支新增 `evidence/verify-reports-20261006/` 目录
