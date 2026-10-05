# AGEN-745 — test: reading_hints 提示组装与降级补测

- 分支：`test/reading-hints-20261005`（基于 origin/main `f07029cfc`，v1.6.13）
- 范围：仅 `tests/reading/test_reading_hints.py`（+377 行），无产品代码改动
- 去重确认：AGEN-637（`tests/reading/test_references_degradation.py`，引用解析）不重叠；mastery-hints 分支未新增本文件用例；上游无 reading_hints 相关开放 PR/issue

## 新增用例（14 个函数 / 20 个用例，全绿）

组装成功：
- `test_render_assembles_selection_unit_and_transcript`（zh/en 分节、选中文段、位置文本、对话说话人、空对话占位）
- `test_locator_bucket_groups_positions_into_cache_key`（位置分桶 1-5/6-10、缓存键维度）
- `test_collect_merges_material_and_transcript`（合并素材+对话、选中文段清洗与 2000 截断）
- `test_material_last_answer_prefers_latest_assistant_turn`

输入异常：
- `test_sanitize_normalizes_wrapped_questions`（引号/符号剥离、围栏拒绝、双问号、多句前缀、多行）
- `test_sanitize_enforces_language_length_limits`（en 110 / zh 44 边界，4 用例）
- `test_load_transcript_filters_roles_and_tails`（角色过滤、四轮截断）
- `test_load_transcript_drops_blank_and_overlong_turns`（空白轮丢弃、700 字符截断）

降级分支：
- `test_load_transcript_degrades_without_session_data`（空 session 不触库、store 异常、session 缺失）
- `test_get_ask_hint_collect_failure_returns_empty_material`（素材收集异常 → 空 dict）
- `test_get_ask_hint_missing_material_skips_llm`（无素材不调 LLM）
- `test_get_ask_hint_selection_bypasses_cache_and_degrades`（选中文段绕过缓存、坏输出仍返回结构化空提示）
- `test_generate_filters_repeats_of_last_answer`（复述上一轮回答被过滤，en/zh 各 2 用例）
- `test_response_language_failure_falls_back_to_english`（语言设置异常回落 en）

## 测试命令（限时 900s）

```
python -m pytest -q -p no:cacheprovider tests/reading/test_reading_hints.py   # 24 passed
python -m pytest -q -p no:cacheprovider tests/reading/                        # 435 passed（无回归）
python -m ruff check tests/reading/test_reading_hints.py                      # All checks passed
python -m ruff format tests/reading/test_reading_hints.py                     # 已格式化
```
