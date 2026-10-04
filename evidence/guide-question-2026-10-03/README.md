# evidence/guide-question-2026-10-03

为 `guide.md`（deep_question 链路导读）的编写过程与事实核查记录。

## 输入

- 基线：`origin/main` @ `ef2d9e5c3`（release: v1.6.12），新 worktree `dt-agen448-wt`，分支 `docs/guides/question-pipeline`。
- 通读文件：
  - `deeptutor/agents/question/pipeline.py`（2309 行，全文；重点：`run`/`_run_inner`、`_explore`/`_plan`/`_parse_plan`、`_quiz_one`/`_repair_quiz_payload`、`_summarize_tool_result`、`_render_exploration_trace`、`_parse_quiz_payload`/`_normalize_quiz_payload`/`_collect_quiz_issues`/`_payload_to_qa_pair`、`_force_finish`、`_build_result_payload`、`_BaseLoopHost`/`_ExploreLoopHost`/`_QuizLoopHost`）
  - `deeptutor/api/routers/question.py`（578 行，全文；StdoutInterceptor Tee、log_pusher、/mimic 与 /generate 帧协议）
  - `deeptutor/agents/question/coordinator.py`（242 行，全文，兼容外壳与流转发）
  - `deeptutor/agents/question/capability.py`（472 行，全文，三条入口分发）
  - `deeptutor/agents/question/mimic_source.py`、`history.py`、`request_config.py`、`__init__.py`（全文）
  - `deeptutor/tools/question/exam_mimic.py`（70 行）、`deeptutor/agents/_shared/capability_result.py`（51 行）
  - `deeptutor/agents/question/prompts/en/pipeline.yaml`（结构与小节行号）
- 佐证材料：分支 `audit/coverage-gaps-20261003` 的 `evidence/coverage-2026-10-02/backend/coverage.json.gz`（解出 pipeline.py 283 缺失/65.6%、question.py 225 缺失/30.8% 的逐行缺失清单）与 `top15-gaps.md` §15；`tests/agents/question/test_pipeline.py`（1368 行）、`tests/api/test_question_router.py`（154 行）的既有覆盖盘点；测试卡分支 `test/question-tee-stdout-write-20261003`（+`-v2`）、`test/question-mimic-ws-error-paths-20261004` 的 diff 清单。
- 上游查重：`gh pr list --repo HKUDS/DeepTutor --state all --search "question"` 检索，无出题链路导读/产物契约文档类 PR（命中的均为题库/判分/掌握度功能 PR，无重叠）。

## 关键论断的核查命令与结果

均在 worktree 根目录（基线 ef2d9e5c3）执行：

1. "helper 双定义，第二组生效"：
   `rg -n "^def _normalize_type_list|^def _normalize_per_type_counts|^def _format_allowed_types|^def _format_per_type_counts" deeptutor/agents/question/pipeline.py` → 各自两处（:187/:249、:208/:267、:235/:295、:241/:302）；coverage.json 缺失行含第一组全部函数体（:194-246），`run()` :488-489 调用的是 :249/:267 版本。
2. "custom 模式测试以 mock 驱动主干，`_explore`/`_quiz_one` 方法体零覆盖"：
   `tests/agents/question/test_pipeline.py:148`（`monkeypatch.setattr(pipeline, "_explore", AsyncMock(...))`）、`:165`（`_quiz_one`）；coverage 缺失 :645-703、:876-967。
3. "覆盖数字与逐行缺失"：
   `git show audit/coverage-gaps-20261003:evidence/coverage-2026-10-02/backend/coverage.json.gz` 解包后按文件提取 summary 与 missing_lines（pipeline.py: covered 540 / 823，question.py: covered 100 / 325）。
4. "契约字段名 `concentration`"：
   `pipeline.py:1962`（`"concentration": qa.topic`）；`rg -n "concentration" web/lib/quiz-types.ts` → :53/:66/:107。
5. "router 挂载前缀"：
   `deeptutor/api/main.py:603`（/api/question）、`:630`（/ws/questions）。
6. "FINISH JSON 契约区段"：
   `rg -n "FINISH JSON schema" deeptutor/agents/question/prompts/en/pipeline.yaml` → :217；schema 与硬规则至 :238。
7. "测试卡分支内容"：
   `git diff --stat origin/main test/question-tee-stdout-write-20261003-v2` → 仅新增 `tests/api/test_question_tee_write.py`（290 行，4 例）；`git diff --stat origin/main test/question-mimic-ws-error-paths-20261004` → `tests/api/test_question_router.py` +270 行（6 例）。

## 产物清单

- `evidence/guide-question-2026-10-03/guide.md`（169 行）：三条入口 → 一个执行核的链路视图、阶段图（mermaid）与阶段表、产物字段契约（模板/归一/envelope/事件）、Router Tee 与 WS 帧协议、失败模式地图、已知坑 6 条、未测分支与测试卡对应表 15 项、延伸阅读。纯新增文档，未触碰任何产品代码（`git diff --stat` 应仅含本目录两个新文件）。
