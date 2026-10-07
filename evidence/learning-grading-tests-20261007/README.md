# learning/grading 判分单元测试补齐

- 基线：origin/main @ f07029cfc（release v1.6.13），新 worktree + 新分支 `test/learning-grading-20261007`
- 日期：2026-10-07
- 结论：PASS

## 交付

- 新增 `deeptutor/learning/tests/test_grading_validation.py`，38 个用例，只增不改，未触碰任何产品代码。
- 既有 `test_grading.py`（24 用例）未改动，作为回归基线一起跑。

## 场景分组（38 例）

| 分组 | 用例数 | 覆盖点 |
| --- | --- | --- |
| 输入校验（异常路径） | 11 | user_answer / expected_answer / classify_error 传入 None、int、float、list 时在 `str.strip` 处快速失败（AttributeError） |
| 默认题型 | 2 | 不传 question_type 时按 short 判分；question_type 传非字符串（None/123）时落回 False 不抛异常 |
| choice 归一化 | 5 | 内部空格两侧移除、大小写+空白组合、仅移除空格不移除标点（`A,B`≠`AB`）、制表符不移除、非 ASCII 答案 |
| short 相似度边界 | 7 | 阈值下界（gravy/gravity≈0.833 为 False）与上界（gravty/gravity≈0.923 为 True）、尾字符删除≈0.889 通过、expected 恰 30 字符仍启用模糊、31 字符起关闭模糊、31 字符精确匹配仍通过、比较前先做 strip+lower 归一化 |
| open 关键词阈值 | 11 | 覆盖率恰 0.6（5 选 3）通过、0.4 不通过、2/3 通过、1/3 与 1/2 不通过、关键词顺序无关、大小写不敏感、expected 只有分隔符时无关键词判 False、关键词互为子串分别计数、重复关键词成组计数 |
| classify_error 边界 | 2 | 全角空格等 Unicode 空白答案判 METACOGNITIVE、纯标点答案判 APPLICATION_ERROR |

## 命令与数字

```bash
timeout 900 python -m pytest -q -p no:cacheprovider \
  deeptutor/learning/tests/test_grading_validation.py \
  deeptutor/learning/tests/test_grading.py
# 62 passed in 0.11s   （24 存量 + 38 新增）

timeout 900 python -m pytest -q -p no:cacheprovider deeptutor/learning/tests
# 648 passed in 5.24s  （learning 全目录回归）

python -m ruff check deeptutor/learning/tests/test_grading_validation.py
# All checks passed!（ruff format --check 亦通过）
```

注：宿主机为 macOS，无 coreutils `timeout`，实际执行用 `perl -e 'alarm 900; exec @ARGV'` 等效限时。Python 环境：`/Users/Shared/DeepTutor/.venv`（pytest 9.1.1）。

## 与上游开放 PR #1279 的关系

PR #1279（mastery learner evidence）重写了 `grade_answer` 的 short 分支：删除 SequenceMatcher 模糊匹配，改为 Decimal 数值相等，并新增 `short_answer` 题型。本文件的 `TestShortFuzzyBoundaries` 钉住的是 origin/main 当前契约；若 #1279 合并，该组 7 例需按新算法同步调整（choice/open/classify/输入校验各分组不受影响，#1279 对这些分支无改动）。

## 边界确认

- `git diff --stat`：仅新增测试文件与本 evidence 目录，无产品代码改动。
- 测试进程均已退出，无后台残留。
