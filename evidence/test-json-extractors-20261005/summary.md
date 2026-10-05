# test-json-extractors-20261005 摘要

任务：AGEN-636 — 为 LLM 输出 JSON 提取器补边界测试。
基线：origin/main `f07029cfcf2c8dfccdb671cdfc343db8334f5741`（v1.6.13）。
分支：`test/json-extractors-20261005`，头 commit `edf2afd7e`。
产品代码改动：无（仅新增两个测试文件）。

## 覆盖对象与用例数

| 函数 | 文件 | 参数化用例 |
| --- | --- | --- |
| `extract_json_object` | deeptutor/agents/_shared/json_output.py | 24 通过 + 13 抛 `json.JSONDecodeError` = 37 |
| `_decode_first_json_object` | deeptutor/agents/_shared/json_output.py | 20（含 8 个返回 None） |
| `extract_json_from_text` | deeptutor/agents/research/utils/json_utils.py | 19 通过 + 12 返回 None = 31 |

合计 88 个参数化用例，每函数 ≥15，满足验收第 1 条。

## 测试命令（限时）

```
runlim 900 .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/agents/test_shared_json_output_boundaries.py \
  tests/agents/research/test_json_utils_boundaries.py
```

结果：88 passed in 0.26s（runlim 为 macOS 下无 `timeout` 命令时的等价 900 秒硬限时包装）。

回归合并跑（新文件 + 既有 `test_shared_json_output.py`、`test_extract_json_adjacent.py`）：
117 passed in 0.27s，无相互干扰。

## 锁定的边界行为（与现实现一致）

- 代码围栏：```json/裸 ``` 围栏均可提取；多围栏取第一个；截断围栏视为失败；围栏内数组对 `extract_json_from_text` 是合法结果，对 `extract_json_object` 抛错。
- 前后噪声：prose 前缀/后缀均可；两个对象取第一个；`extract_json_object` 会跳过非 dict 前缀（如 `42 {...}`、`[1,2] then {...}`）。
- 截断/畸形 JSON：截断对象、非法 token（`tr`）、尾逗号、Python 单引号均失败（`extract_json_object` 抛 `No JSON object found`，`extract_json_from_text` 返回 None）；多余闭括号 `{"a":1}}` 容忍并返回对象。
- 嵌套对象：三层嵌套 + 数组内对象完整保留；字符串值内的 `}`、` ```json ` 示例不干扰（完整对象优先）。
- unicode：`\uXXXX` 转义、代理对（emoji）、原文 unicode 均正确解码。
- 其他现行为：`[{"a":1}]` 在 `_shared` 侧解包为 `{"a":1}`；`json_utils` 侧数组优先于后随对象、且标量（`42`、`"str"`）会透传——与 `_shared` 侧行为不同，测试已显式固化供后续对照。

## 文件

- `tests/agents/test_shared_json_output_boundaries.py`
- `tests/agents/research/test_json_utils_boundaries.py`
- `evidence/test-json-extractors-20261005/pytest-boundaries.txt`
- `evidence/test-json-extractors-20261005/pytest-combined-existing.txt`
- `evidence/test-json-extractors-20261005/SHA256SUMS`
