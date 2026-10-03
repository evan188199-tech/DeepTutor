# deep_question 出题 pipeline 产物契约补测说明（AGEN-284）

基线：`origin/main` @ `ef2d9e5c3`（release: v1.6.12），2026-10-03。
对应缺口：覆盖率报告 Top 15 第 15 项 — `deeptutor/agents/question/pipeline.py`（283 缺失 / 65.6%）。
上游核查：HKUDS/DeepTutor 无关联的 pipeline 产物契约测试 PR（question 相关 PR 为判分/修复类 fix，无重叠）。

## 产物

- 测试集：`tests/agents/question/test_pipeline_output_contract.py`（6 个用例，全绿回归锁）
- 本说明目录：`evidence/question-pipeline-tests-2026-10-03/`
- 分支：`myfork/test/question-pipeline-contract`

## 契约覆盖点

1. **两阶段产物字段契约（端到端，mock LLM）**：`exploring → planning → quizzing` 阶段顺序；
   规划阶段产物 — 规划器漏发 `question_id` 时 pipeline 补齐规范 `q_N` 序列、topic/type/difficulty
   透传、超集类型回退 `short_answer`、`ideas` 别名可接受（防 prompt 改名静默清空题单）；
   生成阶段产物 — FINISH JSON → `QuizPair`，choice 答案文本归一为选项键、concept「对」归一
   `true/false`、非 choice 选项剥离；结果信封恰好 `response / summary / mode` 三键，summary
   九字段（`success/source/requested/template_count/completed/failed/templates/results/analysis`），
   旧版渲染键 `concentration`（= topic）保留；逐题 `quiz_question_emitted` 卡片 metadata
   （call_kind / trace_role / question_index / total_questions / qa_pair）。
2. **空知识点输入边界**：探索为空（空 FINISH、无消息）时，plan prompt 携带显式
   `(no exploration trace` 空轨迹标记而非空字符串；规划零模板 → RuntimeError + 可见错误事件 +
   ⚠ 气泡 + 不发 capability result + 不进 quiz 循环（#1318 形状）。
3. **生成失败错误事件（mock LLM）**：FINISH 不可解析 → 恰好一轮 FINISH-only 协议修复
   （prompt 含 issues 与 topic），修复失败 → 两条 warning 进度事件 + `[Generation failed]
   {topic}` 占位 + `correct_answer/explanation="N/A"` + issues 落 `metadata` + 信封
   `failed=1/completed=0/success=False`，结果事件与题目卡片仍发出（#1508 形状）。

## Mock 策略（单元级 mock LLM）

在 `deeptutor.runtime.agentic` 原语层打桩，编排代码全真运行、无网络访问：

- `run_agentic_loop` → `_FakeLoop`：exploring 返回 FINISH 前言（可空），quizzing 逐题吐 canned
  FINISH JSON。
- `run_labeled_step` → `_FakeLabeledStep`：按 `allowed_labels` 区分 PLAN 与 FINISH-only 修复，
  返回 canned 应答并记录调用 kwargs（断言 prompt 内容用）。
- `emit_capability_result` → 捕获信封 payload 与 source；`build_openai_client` /
  `_prepare_pageindex_tools` 打桩；流侧用鸭子类型 `_RecordingBus` 记录 stage/content/progress/error。
- 构造期补丁沿用同目录 `test_pipeline.py` 约定（`get_llm_config` → 测试 LLMConfig）。

## 运行命令与结果

```bash
PYTHONPATH=<worktree> .venv/bin/python -m pytest tests/agents/question/test_pipeline_output_contract.py -q
# 6 passed in 1.07s

PYTHONPATH=<worktree> .venv/bin/python -m pytest tests/agents/question/ -q
# 59 passed in 0.86s（无回归）
```

## 覆盖率数字（coverage 7.16.2，`--source=deeptutor/agents/question`）

| 口径 | pipeline.py 语句覆盖 |
| --- | --- |
| 既有测试（不含本集，基线） | 530/823 = 64.4%（缺 293） |
| 加入本契约测试后 | 608/823 = 73.9%（缺 215，+78 条语句，约 +9.5pp） |

## 结论

- **跑通：PASS**。当前 `origin/main` 的实现满足上述产物契约，6 个用例全部通过，定位为**绿色
  回归锁**：改 prompt（如重命名规划字段、改 FINISH schema、动空轨迹标记）或改编排（阶段顺序、
  信封字段、修复轮数）会被此集拦下。
- 未修改任何产品代码；仅新增 1 个测试文件 + 本说明目录。
