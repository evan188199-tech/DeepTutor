# RAG service 检索静默降级路径补测说明

日期：2026-10-04　·　卡：AGEN-482（glm-reserve/deeptutor/test-rag-degrade）

## 背景

DT-22 §3（`evidence/todo-scan-2026-10-03/report.md`）将 `deeptutor/services/rag/service.py`
`search` 内的 L1 记忆 trace 块（`except Exception: pass`，报告定位 :183，MEDIUM）列为
静默降级点，对应上游 #1678（Chat history search fails — existing text cannot be
matched）的怀疑方向：搜索/召回链路的静默降级可能掩盖检索失败的真实原因。

本卡只补测试锁定现状，**不改任何产品代码**。

## 交付物

- `tests/services/rag/test_service_degrade.py`（新增，唯一代码改动）
- 本目录（说明 + 校验和）

## 三分支与现状锁定

| 分支 | 测试 | 现状行为（测试断言） | 与 #1678 症状的对应 |
| --- | --- | --- | --- |
| 检索异常（pipeline 抛错） | `test_search_pipeline_exception_propagates_unchanged` | 异常原样透传给调用方，不被吞、不转空结果 | 该分支本身是"响亮"的，不是掩盖来源；锁定为对照基线 |
| 检索异常（pipeline 返回 error_type） | `test_search_pipeline_error_result_is_preserved_and_reported` | `error_type`/`needs_reindex` 保留，且发出 `call_state=error` 状态事件 | 错误结果不被降级成成功，调用方可见 |
| 遥测失败（event_sink 抛错） | `test_search_telemetry_failure_propagates_and_masks_retrieval`（before/after 两阶段） | 异常透传；after 阶段 pipeline 已成功返回结果仍被丢弃 | 遥测故障与真实检索失败对调用方不可区分，即 #1678"查不到"却看不到原因的形态 |
| 记忆读取失败（import 断 / store 不可用 / emit 失败） | `test_search_memory_failure_is_silently_swallow` 系（3 参数化） | 全部被 `except Exception: pass` 吞掉，结果正常返回，trace 丢失对调用方不可见 | 报告 MEDIUM 定位的本体：trace 丢失不可观测，削弱事后定位检索问题能力 |
| （基线）健康路径 trace 内容 | `test_search_emits_l1_query_trace_on_success` | 记录 surface=kb / kind=query / payload(query, kb_name, answer_chars) | 明确"被静默丢掉的是什么"，便于后续修复评审 |

另含 `test_search_healthy_path_emits_expected_status_sequence` 锁定 3 条 status 事件序列，
作为遥测分支的对照。

## 复现命令与结果

```bash
python -m pytest -q -p no:cacheprovider tests/services/rag/test_service_degrade.py
# 9 passed in 0.20s（基线 origin/main ef2d9e5c3, v1.6.12）
```

- lint：`ruff check` / `ruff format --check` 通过。
- 邻近既有测试 `test_rag_pipelines.py` 同跑通过；`test_embedding_binding.py` 有 6 个
  失败为环境性失败（worktree 缺 gitignore 的 `data/user/settings/main.yaml` 运行时配置），
  在干净 origin/main 上同样复现，与本测试文件无关。
- 分支：`test/rag-degrade-20261004`（基于 origin/main ef2d9e5c3），仅新增上述文件，
  `git status` 确认无产品代码改动。

## 后续建议（非本卡范围）

遥测与记忆两分支行为不对称（遥测响亮到会丢弃已成功的检索结果、记忆静默到 trace 丢失
不可见）。若要针对 #1678 做产品修复，可评估：遥测失败降级为"发出失败事件后继续返回
结果"，记忆失败至少 warning 级日志。应由人决定是否立项。
