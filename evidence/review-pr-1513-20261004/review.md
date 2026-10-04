# 复核报告：上游已合并 PR #1513「fix(rag): report empty retrieval results」对 #1500 的解决程度

- 复核日期：2026-10-04
- 基线：origin/main @ `ef2d9e5c3`（release v1.6.12），新 worktree + 新分支 `review/agen426-pr1513`
- 复核对象：PR #1513（merge commit `5c1495b3f`，2026-09-23 合入 `dev`；等价 squash 提交 `7dde859ea`）
- 关联 issue：#1500（撰写本报告时仍为 OPEN）
- 方式：纯代码/测试审阅 + 本机跑既有回归，未改任何产品代码

## 0. 结论速览

| #1500 验收诉求 | 仅看 PR #1513 | 看 v1.6.12 整体（含后续跟进提交） |
| --- | --- | --- |
| 空结果可见（无命中不得伪装成"执行完成但无内容"） | **已解决**（限"成功且零命中"场景） | 已解决（三类状态全部显式化） |
| 来源可核对（命中给标题/标识；空/失败不得给假来源） | **部分**（命中路径透传早已存在，但空/失败仍会产生 query-echo 假引用） | 已解决（`69058b48b`、`810487f81` 补齐） |
| 无命中 / 调用失败 / 工具未执行三态明确区分 | **部分**（仅排除 `error_type` 情形，未给失败分支文案与 `success=False`） | 已解决（`69058b48b` 补齐失败文案与 success 语义） |
| 伙伴资料库保存并被会话读取（端到端验证） | **未覆盖**（PR 描述断言"已传播"，但无测试佐证） | 已解决（`81bd72d77`、`a5dea06d6` 端到端用例） |

**总判定：PR #1513 单独看是"部分解决"；#1500 的完整闭环由 5 个引用 #1500 的提交共同完成，至 v1.6.12 整体可判定为"已解决"。** 建议：上游可让报告者在 ≥1.6.11（完整三态区分建议 ≥1.6.12）复测后关闭 #1500。

## 1. PR #1513 改动点清单

diff 共 2 文件、+46/-0 行（见 PR #1513 Files changed；`deeptutor/tools/builtin/__init__.py` 的 `@@ -124,6 +124,11 @@` hunk 与 `tests/core/test_builtin_tools.py` 的 `@@ -330,6 +330,41 @@` hunk）：

1. `deeptutor/tools/builtin/__init__.py` RAGTool.execute：在 `content = result.get("answer") or result.get("content", "")` 之后新增 5 行——当 `content` 为空、且无 `error_type`、且无 `sources` 时，将 `content` 置为显式文案 `No matching content was found in knowledge base '{kb_name}'. The search completed successfully.`
2. `tests/core/test_builtin_tools.py` 新增 2 个回归用例：
   - `test_rag_tool_reports_successful_empty_retrieval`（现 tests/core/test_builtin_tools.py:336）：IMA 返回 `answer="" / content="" / sources=[]` 时工具必须给出上述文案；
   - `test_rag_tool_does_not_disguise_errors_as_empty_results`（现 tests/core/test_builtin_tools.py:358）：带 `error_type` 的返回不得被改写成"无命中"文案。

语义边界：#1513 只处理「检索成功但零命中」这一种情况；`error_type`、`needs_reindex`、有 sources 无 content 等情形被条件显式排除，保持原样。

## 2. #1500 诉求逐条判定

### 诉求 A：空结果可见 —— PR #1513 已解决

- 根因匹配：#1500 报告者使用 1.6.8，现象是伙伴自述"工具执行完成，但没有返回文本内容"。1.6.8 中 IMA 检索成功但零命中时返回 `answer=""`、`content=""`、`sources=[]`（见 v1.6.10 及更早的 `ImaPipeline.search`），RAGTool 原样透传空字符串，模型只看到一条空的 `role=tool` 消息——与用户现象吻合。#1513 的根因判断成立。
- 修复后链路（当前 main）：
  - 工具层：`deeptutor/tools/builtin/__init__.py:153-157` 空 content、无 error、无 sources → 显式 no-match 文案；
  - 传递层：`deeptutor/runtime/agentic/tool_dispatch.py:774-775`（`result_text = result.content`）→ `deeptutor/runtime/agentic/tool_dispatch.py:878-885`（`result_text` 作为 `role=tool` 消息 body 发回模型），文案必然到达模型；
  - 工具抛异常路径同样可见：`deeptutor/runtime/agentic/tool_dispatch.py:783-826` 将异常转为 `Error executing ...` 文本，不再是空消息。
- 回归测试：tests/core/test_builtin_tools.py:336。
- 判定：**已解决**（针对"成功零命中"场景；该场景正是 #1500 描述最可能的情况）。

### 诉求 B：来源可核对 —— PR #1513 部分，整体已解决

- 命中路径的来源透传（`{title, content, source, page, chunk_id, score}` → `_rag_sources` → `ToolResult.sources`）早于 #1513 已存在（源注释标注 issue #694），#1513 未改动——命中时来源本就可核对。
- 但 #1513 遗留两处"假来源/弱来源"：
  1. 空/失败检索时 `_rag_sources` 的 query-echo fallback 仍会产出 `[{type: rag, query, kb_name}]` 假引用——由后续 `69058b48b` 修复：`deeptutor/tools/builtin/__init__.py:80-86` 空/失败/needs_reindex 时不再返回 echo；
  2. IMA「只命中标题、无可读文本」时，v1.6.10 及之前会把仅有标题的条目当 sources 渲染（"来源"无原文可核对）——由 `810487f81` 修复：`deeptutor/services/rag/pipelines/ima/pipeline.py:87-100` 将其归类为 `error_type=content_unavailable` 并给出明确文案，`deeptutor/services/rag/pipelines/ima/pipeline.py:88` 过滤无可读内容的 source（代码注释直接引用 #1500）。
- 端到端来源校验：`tests/services/partners/test_workspace_binding.py:153`（`test_copied_ima_pointer_reaches_partner_rag_with_source`，`81bd72d77`/`a5dea06d6`）用 #1500 原场景（伙伴"熊猫数学伙伴" + IMA 库"宝宝小学" + 查询"三年级乘法"）断言 `result.sources[0]["title"]=="三年级数学教材"`、`chunk_id=="m-1"`，且命中内容进入 `result.content`。
- 判定：**PR #1513 部分；至 v1.6.12 已解决**。

### 诉求 C：无命中 / 调用失败 / 工具未执行三态区分 —— PR #1513 部分，整体已解决

- IMA 失败路径在 #1513 之前就返回 `answer=str(exc)` 且非空（`deeptutor/services/rag/pipelines/ima/pipeline.py:146-154` `_error_result`；`not_configured`:74-75、`retrieval_error`:80-82），模型可见错误文本——#1513 正确地没有把失败伪装成"无命中"。
- 但 #1513 时点失败分支有两个缺口：`answer` 为空字符串的失败结果仍是空 tool 消息；`ToolResult.success` 不随 `error_type` 置 False。`69058b48b` 补齐：`deeptutor/tools/builtin/__init__.py:148-152`（`search failed (error_type)` / `needs reindexing` 文案）与 `deeptutor/tools/builtin/__init__.py:173-179`（`success=not failed`），对应回归 tests/core/test_builtin_tools.py:358、381、405。
- 判定：**PR #1513 部分；至 v1.6.12 已解决**。

### 诉求 D：伙伴资料库保存并被会话读取（端到端验证）—— PR #1513 未覆盖，后续补齐

- PR #1513 描述断言「伙伴 IMA 路径已把连接型知识库条目传播进伙伴上下文」，但 PR 内无伙伴链路测试佐证。
- 后续 `81bd72d77`、`a5dea06d6`（均在 v1.6.12）补上端到端：`provision_assets("ada", knowledge_bases=["宝宝小学"])` 复制进工作区无错误 → `PartnerRunner._list_kb_names()` / turn context `knowledge_bases` 包含该库 → 在伙伴上下文内执行 RAGTool 成功返回内容与来源；`a5dea06d6` 进一步走完整 `process_message` 回合。
- 判定：**PR #1513 未覆盖；至 v1.6.12 已解决**。

## 3. #1500 系列修复全景（origin/main）

| 提交 | 日期 | 内容 | 首次包含的 release（main） |
| --- | --- | --- | --- |
| `7dde859ea`（PR #1513） | 09-18（09-23 合入 dev） | 空命中显式 no-match 文案 + 2 回归 | v1.6.11 |
| `69058b48b` | 09-23 | 空/失败不出 query-echo 假引用；失败/重建索引文案；`success=not failed` | v1.6.11 |
| `810487f81` | 09-27 | IMA 标题命中无可读文本 → `content_unavailable`，不产出不可核对来源 | v1.6.12 |
| `81bd72d77` | 09-27 | 伙伴端到端：复制进工作区 → 伙伴 RAG → 来源校验 | v1.6.12 |
| `a5dea06d6` | 09-27 | 伙伴端到端升级为完整 turn | v1.6.12 |

注意：#1500 报告环境为 1.6.8；main 线 v1.6.9/v1.6.10 均不含 #1513（`git tag --contains` 验证），**用户需升级到 ≥1.6.11（建议 ≥1.6.12）才获得完整修复**。

## 4. 残余风险

1. **no-match/错误文案均为英文**（如 `No matching content was found ...`）：模型通常会用用户语言转述，但若模型直接引用工具原文，中文用户会看到英文提示。低风险、体验类。
2. **可诊断性仍有限**：no-match 文案不含 query/top_k/命中数等上下文，`#1500` 要求的"可诊断提示"只满足状态区分层面；深入排查仍需日志/trace（service.py 已通过 `event_sink` 上报 summary/call_state=error，见 `deeptutor/services/rag/service.py:139-153`）。
3. **空白字符串边界**：`content = result.get("answer") or result.get("content", "")` 只判 falsy；若某 pipeline 返回纯空白 `answer` 且带 `sources`，会绕过 no-match 分支。现有 IMA pipeline 的 `render_context` 会带标题前缀，实际难以触发，属理论边界。
4. **#1500 尚未关闭**：`Fixes #1500` 因合入 dev（非 main 默认分支）未自动关单；且系列修复分散在 5 个提交，建议维护者汇总后在 issue 里回复版本指引（≥1.6.12）再关。
5. **未验证真实 IMA 远端行为**：本复核基于代码与单测（fake client），无法证明腾讯 IMA 线上接口行为；报告者环境的原始日志缺失问题依旧存在，只能靠升级后复测闭环。

## 5. 本机验证（origin/main @ ef2d9e5c3）

- `python -m pytest tests/core/test_builtin_tools.py -q` → **24 passed**（含 336/358/381/405 四个 #1500 相关回归）
- `python -m pytest tests/services/rag/test_ima_pipeline.py -q` → **68 passed**（PR 时为 67，后续有增补）
- `python -m pytest tests/services/partners/test_workspace_binding.py -q` → **7 passed**（含 #1500 端到端两用例）

## 6. 最终判定

- **PR #1513 单独**：部分解决 #1500——修复了"成功零命中不可见"这一最可能根因，但来源假引用、失败文案/success 语义、IMA 标题命中、伙伴端到端验证均未在其范围内。
- **至 v1.6.12 的系列提交整体**：满足 #1500 全部验收诉求（空结果可见、来源可核对、三态区分、伙伴链路端到端验证），判定为已解决；建议上游引导报告者升级 ≥1.6.12 复测后关闭 issue。
