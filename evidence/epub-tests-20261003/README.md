# 回归夹具与失败测试说明（epub-tests-20261003）

对应卡片：AGEN-100（test: EPUB 目录锚点与分页回归夹具）。基线：`origin/main` @ `ef2d9e5c3`（v1.6.12）。分支：`myfork/test/reading-regression-20261003`。

## 结论先行

开工前上游核查发现：两个已知缺陷均已有关联修复 PR（均开放），按卡片规则转入复核 + 补齐仍未覆盖的回归面：

| 缺陷场景 | 上游 | 关联修复 PR | 本卡动作 |
| --- | --- | --- | --- |
| EPUB TOC 锚点丢失 + 阅读位置标注错误 | #1673 | PR #1686（open，后端提取/存储/迁移 + 前端导航/侧栏/页头，含自带测试） | 复核 PR #1686（76 个引擎测试全过） |
| 多标题 .md 分页失效（单页症状） | #1641 | 根因类 PR #1637（open，CommonMark 式围栏闭合，含提取层测试） | 复核 PR #1637（46 个 ingestion 测试全过）+ 补 #1641 报告路径（本地 .md 上传→store）的回归测试 |

## 本分支新增（仅测试与夹具，未改任何产品代码）

- `tests/fixtures/reading/issue1641_nested_fence.md` — ```` 长围栏包裹 ``` 示例、内含 `# 注释`（#1637 场景 1）
- `tests/fixtures/reading/issue1641_pseudo_fence.md` — 行首 ```` ```inline``` text ```` 伪围栏（#1637 场景 3）
- `tests/fixtures/reading/issue1641_flat_fallback.md` — 单标题长文（#1641 维护者问题：兜底路径空 outline）
- `tests/reading/test_md_pagination_regression.py` — 3 个测试，全部走 `ReadingStore.ingest`（即 #1641 报告的本地 .md 上传路径）

## 当前在 origin/main 上的预期结果

| 测试 | 结果 | 对应缺陷 |
| --- | --- | --- |
| `test_nested_longer_fence_keeps_example_comments_out_of_outline` | FAIL（`Install dependencies` 泄漏为 outline 行） | #1637 场景 1 / #1641 |
| `test_pseudo_fence_line_with_backticks_keeps_later_headings` | FAIL（`Beta` 及之后标题被吞） | #1637 场景 3 / #1641 |
| `test_flat_fallback_stores_synthesised_outline_rows` | PASS（store 在 outline 为空时按单元合成行，store.py `ingest` 的 `synthesise_outline` 兜底） | #1641 维护者问题：兜底路径不会持久化空 outline，单页症状只能来自标题被吞路径 |

命令与数字：

```
.venv/bin/python -m pytest tests/reading/test_md_pagination_regression.py -q
→ 2 failed, 1 passed

.venv/bin/python -m pytest tests/reading/ -q
→ 2 failed, 403 passed（2 failed 均为上述预期失败，无其他回归）
```

## 修复卡领取指引

- 围栏两例在 PR #1637 合入后应转绿（#1637 已在提取层修复并自带测试；本分支补的是 store 层集成回归，二者互补不重复）。
- `test_flat_fallback_*` 为常绿护栏，钉住 #1641 中维护者提问的答案。
- EPUB 侧（#1673）无需新增失败测试：PR #1686 覆盖锚点提取/存储/迁移/导航与侧栏、页头位置标注，并自带后端与前端测试。

## 复核记录（PR 测试实跑）

- PR #1686：`pytest tests/reading/test_engine.py` → 76 passed
- PR #1637：`pytest tests/reading/test_ingestion.py` → 46 passed
- origin/main 同两组文件基线：116 passed
