# utils 单元测试补齐 — 2026-10-07（AGEN-1039）

## 结论

PASS。`deeptutor/utils/` 全部 11 个源文件（10 个 `.py` + `network/circuit_breaker.py`）现在都有直接用例；scoped 套件 171 passed，0 failed。

## 背景与现状核对

卡片输入称 utils 为测试真空。实测 origin/main（f07029cfc，v1.6.13）已有 9 个文件的直接用例（`tests/utils/` 8 个 + `network/circuit_breaker` 1 个），`config_manager` 由 `tests/core/test_config_manager.py` 覆盖，`error_utils` 为 0% 覆盖的真实缺口。本次按缺口补齐，不重复造已有用例。

## 变更（仅测试，无产品代码）

1. 新增 `tests/utils/test_error_utils.py`（21 用例）：
   - `_find_json_block`：无花括号/空串、裸 JSON、嵌套 JSON、字符串内花括号不干扰计数、字符串内转义引号、未闭合 JSON、孤立 `{`。
   - `format_exception_message`：OpenAI 风格 `error.message/type/code` 全字段按序拼接、仅 message、error 为字符串、无 error 键、空 error 对象、坏 JSON、未闭合 JSON、空对象 `{}`、JSON 夹在自然语言中。
2. 扩展 `tests/utils/test_text_display.py`（3 → 6 用例）：纯 ASCII 密集转义串保持原样（89% 行覆盖中此前未覆盖的分支）、正文夹带中文转义串原位解码、同文本多段独立 run。
3. 扩展 `tests/core/test_config_manager.py`（2 → 7 用例）：配置文件缺失时 load 返回 `{}`、单例复用与 `reset_for_tests` 后更换实例、save 自动创建缺失 settings 目录、`validate_required_env` 缺失 LLM 键报告（默认端口不报缺）、os.replace 失败不留半写文件。

## 覆盖率变化（pytest-cov，仅统计 deeptutor/utils）

| 文件 | 前 | 后 |
| --- | --- | --- |
| error_utils.py | 0% | 100% |
| config_manager.py | 86% | 98% |
| text_display.py | 83% | 89% |
| 其余 8 文件 | 不变 | 不变 |

## 命令与数字

环境：`/Users/Shared/DeepTutor/.venv`（Python 3.13.13，pytest 9.1.1）。macOS 无 `timeout` 命令，改用执行框架的 900s 超时上限，语义等价。

- 基线：`python -m pytest tests/utils tests/core/test_config_manager.py -q -p no:cacheprovider` → 142 passed（改动前）
- 改动后同命令 → **171 passed**（+29）
- 覆盖率：同命令加 `--cov=deeptutor/utils --cov-report=term`
- lint：`ruff check` 与 `ruff format --check` 对 3 个改动测试文件均通过

## 验收对照

1. 11 文件中至少 8 个有直接用例 → **11/11**（含本次补上的 error_utils）
2. timeout 900 python -m pytest 全绿 → 171 passed / 0 failed（约 2s）
3. 不改任何产品代码 → `git status` 仅 3 个测试文件

## 撞车检查

`gh pr list -R HKUDS/DeepTutor --state open` 中无 utils 测试类 PR；#688（fix(utils): strip edge whitespace in upload filenames）为单函数产品修复，与本分支无交集。
