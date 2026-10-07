# 提示词模板占位符 × 调用点静态对照报告

- 仓库基线：`origin/main` @ `f07029cfcf2c8dfccdb671cdfc343db8334f5741`（release: v1.6.13，2026-10-07 fetch）
- 分支：`scan/prompt-template-vars-20261007`（新 worktree，未触碰 main 工作区，未改任何代码）
- 工具：`evidence/scan_tool.py`（模板占位符提取 + AST 调用点盘点）、`evidence/pair_tool.py`（配对与漂移分类）；中间数据 `evidence/scan_raw.json`、`evidence/pairings.json`（含 201 条配对表全量）
- 校验：`SHA256SUMS`

## 一、口径与方法

- **模板全集**：`deeptutor/**/prompts/**` 下全部 `*.yaml`/`*.md`，共 **119 个文件**（zh/en 双份成对计入）。其中 **101 个含 `{var}` 占位符**；`tools/prompting/hints/`、web 前端、`.py` 内联模板字符串不在本卡范围（见"边界"）。
- **占位符提取**：对 YAML 逐字符串、对 MD 全文用 `string.Formatter().parse`，天然跳过 `{{`/`}}` 转义，字段名需匹配标识符（含 `.attr`/`[idx]`），其余归入"非标识符花括号"。
- **调用点盘点**：AST 解析 `deeptutor/**/*.py`（除测试），识别 `load_prompts(...)`/`load_book_prompts(...)`/`get_prompt(...)`/`get_book_prompt(...)`/`prompt_text(...)`/`_t(...)`/`.format(...)`/`.replace("{var}", ...)`，接收者经 ≤3 步赋值回溯解析到模板键路径；配对表人工建立并在抽样中逐条回读源码复核。
- **三类漂移定义**：
  - 缺参 MISSING_PARAM：模板占位符 ⊄ 调用点实参（运行时 `KeyError`）；
  - 多参 EXTRA_PARAM：调用点实参 ⊄ 模板占位符（`str.format` 静默忽略，真实漂移）；
  - 命名漂移 NAMING_DRIFT：多参名与同对缺参名相似度 ≥0.75（改名残留）。
  另设观测类：PLACEHOLDER_WITHOUT_PAIRING（占位符无任何调用点）、ORPHAN_TEMPLATE（整文件无调用点）、ZH_EN_DIVERGENCE（同一键 zh/en 占位符集合不一致）。

## 二、总体统计

| 指标 | 数值 |
| --- | --- |
| 模板文件 / 含占位符文件 | 119 / 101 |
| 配对条目（模板键 × 调用点） | 201（zh/en 两侧共 402 次比对） |
| 缺参 MISSING_PARAM | **0** |
| 多参 EXTRA_PARAM | **3 组**（zh/en 各计一次共 6 条） |
| 命名漂移 NAMING_DRIFT | **0** |
| 占位符无调用点 PLACEHOLDER_WITHOUT_PAIRING | **3 组**（zh/en 共 6 条） |
| 孤儿模板包 ORPHAN_TEMPLATE | **4 个包 / 8 个文件** |
| zh/en 同键占位符分歧 ZH_EN_DIVERGENCE | **0** |

结论：运行时会炸的缺参为 0；实际漂移集中在"多参冗余"与"死模板/死占位符"，均为低风险清理项，适合拆修复卡。

## 三、三类清单

### 1. 多参 EXTRA_PARAM（3 组，两侧 path:line）

| # | 模板（zh/en 同构） | 调用点 | 模板占位符 | 调用点多传 |
| - | --- | --- | --- | --- |
| E1 | `deeptutor/services/memory/consolidator/prompts/{zh,en}/audit_l2.yaml` `system` | `deeptutor/services/memory/consolidator/modes/audit.py:175` | surface, today, user_label | `focus` |
| E2 | `.../consolidator/prompts/{zh,en}/audit_l3.yaml` `system` | `deeptutor/services/memory/consolidator/modes/audit.py:316` | slot, today, user_label | `focus` |
| E3 | `.../consolidator/prompts/{zh,en}/update_l3.yaml` `system` | `deeptutor/services/memory/consolidator/modes/update.py:459` | focus, sections, today, user_label | `slot` |

修复方向：模板 `system` 文案补 `{focus}`/`{slot}`（信息已备好，现被丢弃），或删调用点实参。二选一需产品判断，故只列不改。

### 2. 占位符无调用点 PLACEHOLDER_WITHOUT_PAIRING（3 组）

`deeptutor/learning/prompts/{zh,en}.yaml`（经 `learning/prompts.py` 的 `prompt_text(language, path)` 读取）：

| # | 键路径 | 占位符 | 现状 |
| - | --- | --- | --- |
| P1 | `explain.user` | `knowledge_point` | 仅被死常量 `EXPLAIN_USER`（`learning/prompts.py:122`）引用，全仓无 importer、无 `.format` |
| P2 | `feynman.user` | `knowledge_point` | 同上（`learning/prompts.py:124`，`FEYNMAN_USER` 无 importer） |
| P3 | `practice.user` | `knowledge_points` | 同上（`learning/prompts.py:126`，`PRACTICE_USER` 无 importer） |

同包 `diagnostic.*`/`error_diagnosis.*`/`review.*`/`notebook.system` 亦为死常量（占位符已清空或仅含 JSON 示例），可与 P1-P3 一并清理。

### 3. 命名漂移 NAMING_DRIFT

0 条。多参名与缺参名相似度均 <0.75，未发现"改名残留"型漂移。

## 四、孤儿模板包（4 包 / 8 文件，含占位符但无任何加载点）

| # | 文件 | 键与占位符 | 备注 |
| - | --- | --- | --- |
| O1 | `deeptutor/agents/chat/prompts/{zh,en}/chat_agent.yaml` | `context_template{context}`、`history_format{history}`、`user_template{message}` | chat 现用 `agentic_chat.yaml`（`agents/loop/pipeline.py:211` 默认 `prompt_agent="agentic_chat"`）；全仓无 `agent_name="chat_agent"` |
| O2 | `deeptutor/agents/question/prompts/{zh,en}/idea_agent.yaml` | `generate_ideas.user{topic}` | question 管线改用 `pipeline.yaml` 的 `_t` 体系；无加载点 |
| O3 | `deeptutor/co_writer/prompts/{zh,en}/narrator_agent.yaml` | `extract_key_points_user{content}`、`generate_script_system_template{length_instruction,style_prompt}` 等 | `agent_name="narrator_agent"` 无实例化点 |
| O4 | `deeptutor/services/memory/prompts/{zh,en}.yaml` | `system_l2/l3{today,user_label}`、`user_l2{changes,entities,existing,focus,kb_queries,sections,...}` | 被 `consolidator/prompts/*` 取代，`services/memory` 下无任何 loader 指向该目录 |

（另：`consolidator/prompts/{zh,en}/_meta.yaml` 无占位符，仅作 focus/sections 元数据被 `_runtime.py:load_focus_meta` 读取，正常引用。）

## 五、信息级观测（不计漂移）

1. **非标识符花括号（JSON 示例）**：14 个文件的 system/playbook/instructions 类键含未转义 `{ "x": ... }` JSON 示例（如 `book/prompts/*/spine_agent.yaml` `system`、`mastery_loop.yaml` `playbook`）。这些键全部以**原文传递/replace 渲染**，不经 `str.format`，无运行时风险；若未来改为 `.format` 渲染会直接 `ValueError`，修复卡应顺带加双花括号转义或测试护栏。
2. `book/page_planner.yaml` `architect_system` 用 `.replace("{block_catalog}", catalog)`（`book/agents/page_planner.py:262`）注入，键内 JSON 示例安全。
3. `capabilities/explore_context` `loop.user_template` 只含 `{question,mode,manifest}`，而单遍 `user_template` 另含 `{sources}`（`explorer.py:196` vs `:449`）——**两侧各自匹配，无缺参**，是有意的双模板结构。
4. `agents/visualize/agents/analysis_agent.py:66-73` 动态 `format_kwargs`：fixed 模式多传 `render_type`，figure/auto 模式不传——与三个 `user_template*` 键的占位符逐一比对**均匹配**。
5. `chat` 能力覆盖键：`solve/setup/ima/marginnote4/obsidian/mastery.system` 经 `_prompt_text(prompts, ("x","system"))` 从合并包读取（`agentic_chat.yaml` 顶层键，mastery 经 `_merge_prompt_packs` 覆盖），缺失时回落到各能力 `system.md` 原文，链路成立。
6. `ima/marginnote4/obsidian` 的 `system.md` 占位符（`{kb_names}/{library_name}/{vault_name}`）均由 `.replace()` 注入（`capability.py:61/52/52`），匹配。

## 六、Top10（按修复价值排序）

1. E1 `audit_l2.yaml system` ← `audit.py:175` 多传 `focus`
2. E2 `audit_l3.yaml system` ← `audit.py:316` 多传 `focus`
3. E3 `update_l3.yaml system` ← `update.py:459` 多传 `slot`
4. P1 `learning/prompts/*.yaml explain.user{knowledge_point}` 死占位符
5. P2 `feynman.user{knowledge_point}` 死占位符
6. P3 `practice.user{knowledge_points}` 死占位符
7. O4 `services/memory/prompts/{zh,en}.yaml` 整包孤儿（最大一个，被 consolidator 取代）
8. O3 `co_writer narrator_agent.yaml` 孤儿包
9. O1 `agents/chat/chat_agent.yaml` 孤儿包
10. O2 `agents/question/idea_agent.yaml` 孤儿包

## 七、抽样人工复核（≥10 条，方法：回读两侧源文件）

| # | 配对 | 复核内容 | 结果 |
| - | --- | --- | --- |
| S1 | `course_study.yaml` `course_facts` ← `course_study/capability.py:408` | 初配误写键名 `facts_template`，回读 yaml（实际键 `course_facts`）+ 代码后修正 | 已修正 |
| S2 | `audit_l2.yaml system` ← `audit.py:175` | 回读 yaml system 串与 format kwargs | 确认 EXTRA(focus) |
| S3 | `audit_l3.yaml system` ← `audit.py:316` | 同上 | 确认 EXTRA(focus) |
| S4 | `update_l3.yaml system` ← `update.py:459` | 同上 | 确认 EXTRA(slot) |
| S5 | `update_l2.yaml user` ← `update.py:245` | 7 项 kwargs 与占位符逐一比对 | 匹配 |
| S6 | `explore_context.yaml` `loop.user_template`/`user_template` ← `explorer.py:186/196/449` | 两侧读取，确认 sources 差异为有意设计 | 匹配 |
| S7 | `reading.yaml material_facts` ← `reading/capability.py:217-221` | 4 项 kwargs 比对 | 匹配 |
| S8 | `co_writer/edit_agent.yaml` ← `edit_agent.py:163-191,335-339` | 5 键 6 次 format（含 default 兜底串），kwargs 比对 | 匹配 |
| S9 | `math_animator code_generator_agent.yaml` ← `agents/.../code_generator_agent.py:75-120` | generate/retry 4 键与 2 次 format | 匹配 |
| S10 | `visualize analysis_agent.yaml` ← `agents/.../analysis_agent.py:53-73` | 6 键 × 3 分支动态 kwargs | 匹配 |
| S11 | StatusI18n 状态包（`visualize.yaml`/`math_animator.yaml`/`deep_question.yaml`/`audio_overview.yaml` `status.*`）← 各 capability `i18n.t(...)` 调用（`capability.py:56-348` 等 19 处） | 逐处回读 first-arg 键名与 kwargs | 匹配 |
| S12 | `chat agentic_chat.yaml` `notices.tool_error`/`loop_error_finish` ← `loop/pipeline.py:1112,1151`、`runtime/agentic/tool_dispatch.py:88-95`、`agents/loop/agent_loop.py:827-831` | 经 factory 间接配对，回读 KEY 常量与 kwargs | 匹配 |

复核中发现的唯一误报（S1 键名）已修正；其余抽样全部与工具结论一致。

## 八、边界与去重说明

- 与 `test-prompt-templates` 卡（运行时替换/缺省/转义行为测试轴）互补：本卡只做静态两侧对照，未运行任何渲染。
- 与 `scan-capability-prompts` 卡（能力提示词面/i18n）去重：本卡不评文案质量，只对变量集合。
- `.py` 内联模板（如 `api/main.py:64` `CONFIG_DRIFT_ERROR_TEMPLATE`）、`services/i18n` 通用消息目录、`tools/prompting/hints`（无占位符）、web 端不在本卡全集。
- 未改任何代码；未启动服务；仓库 main 工作区未动。
