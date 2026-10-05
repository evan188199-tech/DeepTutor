# test-reading-references-20261005 — AGEN-637

## 结论

PASS — 新增 7 条降级语义测试全部通过（14 passed 含既有 test_references.py 7 条），
阅读全量回归 422 passed，产品代码零改动。

## 分支 / 提交

- 基线：origin/main @ f07029cfc（v1.6.13，新 worktree `dt-agen637-refdegrade-wt` + 新分支）
- 分支：`test/reading-references-degrade-20261005`
- 未向上游开 PR（按储备卡规则）；PR 草稿见完成评论。

## 覆盖（tests/reading/test_references_degradation.py）

针对 DT-22 §7 MEDIUM（deeptutor/reading/references.py :118 / :135 两处
`except Exception: continue`）锁定降级语义：

1. **manifest 读取失败 → 整个 material 被跳过（:118，部分失败）**：同一调用中
   损坏 material 的引用消失，健康 material 仍正常解析出 source。
2. **全部 manifest 失败 → 返回 [] 且不抛异常（:118，全失败）**。
3. **read_unit 失败 → 仅跳过该 locator（:135，部分失败）**：3 个 locator 中
   损坏 1 个，其余两个照常返回，损坏文本不出现。
4. **全部 locator 失败 → 返回 [] 且不抛异常（:135，全失败）**。
5. **部分失败与"材料不存在"在返回值上不可区分**：两者都退化为 `[]`、无任何
   错误标记字段；正常解析返回 `ResolvedReadingSource` 列表（锁定现状：当前
   实现是静默 fail-closed，未来若增加失败上报需有意识地更新本测试）。
6. **陈旧 revision 走 revisions() 列表失败 → 该引用被跳过（:118 的陈旧修订
   分支）**：同一 material 的当前 revision 引用仍正常解析。
7. **重复 material 行按首次出现合并且有序**：alpha 行 [2]、beta 行 [1]、alpha
   行 [3,1] → 解析顺序为 alpha#2, alpha#3, alpha#1, beta#1——重复行合并进
   首次出现的位置（整组位于 beta 之前），locator 保持到达顺序、从不重排序，
   且 alpha#2 不因重复行而翻倍。

## 与既有测试不重复

- `tests/reading/test_references.py`：覆盖归一化（路径拒绝/locator 去重/上限）、
  客户端文本不可信、单一缺失 material → []、持久化 revision 解析；未覆盖损坏
  元数据的部分/全失败、locator 级跳过、失败与缺失的等价性、跨 material 去重顺序。
- `tests/multi_user/test_learning_reading_turns.py`：覆盖 learner 授权/撤销门控，
  与降级语义正交。
- `tests/reading/test_engine.py` 的书签去重是 engine 层，与引用归一化无关。

## 测试命令与数字

GNU timeout 在本机不可用，用等价的 perl alarm 900s 包裹（实际 0.3–5s 完成）：

```
cd <worktree>
/Users/Shared/DeepTutor/.venv/bin/python -m pytest -v -p no:cacheprovider \
  tests/reading/test_references_degradation.py tests/reading/test_references.py \
  tests/multi_user/test_learning_reading_turns.py tests/services/session/test_source_inventory.py
=> 51 passed
回归邻域：tests/reading/ 全量 => 422 passed
lint：ruff check + ruff format --check => All checks passed
```

## 备注

- `_CorruptStore` 是 duck-typed 代理（对选定调用抛 OSError），不触碰真实存储
  布局，不依赖实现内部路径。
- 产品代码零改动：`git diff origin/main --stat` 仅含新测试文件与 evidence。
