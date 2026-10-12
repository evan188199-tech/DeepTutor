# learning/visual_practice 生成与降级分支补测摘要（coverage-gaps-20261011 §1#1）

- 基线：origin/main = `6cf793bd8`（v1.6.14 release）
- 测试文件：`deeptutor/learning/tests/test_visual_practice_preparation.py`（表驱动，18 例）
- 边界引用：`evidence`（只读）— visual-practice-scan-20261009/report.md 评估边界清单（A/B/C 条目），本卡只引用不重做
- 范围外（去重）：`evaluate_visual`（语义评估，上游 #1901 实现卡负责）、`account_for_recent_assistance`（辅助传播，既有 workflow 测试覆盖）、choices 数据形状（test_mastery_choices.py）

## 用例 × 分支对应表

### A. 生成主路径与降级（test_prepare_visual_paths，8 例）

| 用例 | 覆盖分支 | 边界条目 | 断言要点 |
|---|---|---|---|
| verified-identification-key | 主路径：引用→归一化→quote 验证→verified key | C1/C6/C11 | key=verified、cues=none、resolved source 字段齐全（asset_id/page/source_hash/image_sha256/URL）、aliases 去重且 canonical 居首、public_visual 不泄漏 reference_answer |
| unverified-when-pixels-not-inspected | 降级：投喂像素缺失 → key 降级 unverified、cues 强制 unverified | C7（fail-closed 投喂） | pixels_inspected=False、hints_used=1 |
| visible-cues-when-page-text-reveals-answer | 降级：页面文本暴露答案 → cues 强制 visible | C9 | 无 asset_id 且 page 存在且答案可见文本 → cues=visible |
| declared-inspection-trusted-when-no-hashes | 分支：无 hash 列表时信任声明布尔（True 臂） | C8 | key 保持 verified |
| declared-uninspected-downgrades-key | 分支：声明布尔 False → 同投喂缺失降级 | C8 | key=unverified、cues=unverified |
| choice-option-body-becomes-reference | 分支：options 映射臂（label→body） | A4/C11 | reference_answer=选项体、aliases 以选项体居首 |
| non-ascii-answer-matches-quote | 分支：非 ASCII 答案 containment 匹配 | C11/C13 | 动脉别名经归一化后 quote 验证通过 |
| empty-reference-answer-cannot-verify | 降级：空 reference answer → 无法 verified（fail-closed） | C11 | key=unverified、空串居首 aliases |

### B. 素材缺失 / 格式异常拒绝（test_prepare_visual_rejects，10 例）

| 用例 | 覆盖分支 | 边界条目 | 期望错误信息片段 |
|---|---|---|---|
| unsupported-task | 格式异常：task 白名单越界 | C1 | "Visual tasks support" |
| sources-not-a-list | 格式异常：sources 非列表 | C2 | "Select one or two exact source figures" |
| comparison-needs-two-sources | 格式异常：comparison 单源 | C2 | "requires both original sources" |
| source-not-an-object | 格式异常：source 非对象 | C2 | "Each visual source must be an object" |
| kb-outside-attached-set | 素材/上下文异常：KB 不在话题附着集 | C3 | "attached to this topic/turn" |
| kb-not-accessible | 素材缺失：KB 不可访问 | C4 | "not accessible" |
| retrieval-error | 素材缺失：retrieve_visual 返回错误 | C5 | "Cannot establish original visual evidence" |
| retrieval-no-images | 素材缺失：检索无图 | C5 | "Cannot establish original visual evidence" |
| too-many-accepted-answers | 格式异常：accepted_answers 超 12 条 | A2 | "at most 12" |
| unsupported-answer-cues | 格式异常：answer_cues 白名单越界 | C10 | "answer_cues must be none, visible or unverified" |

## 验证记录

| 步骤 | 命令 | 结果 |
|---|---|---|
| 变异后（先失败） | `pytest -q -p no:cacheprovider deeptutor/learning/tests/test_visual_practice_preparation.py`（临时对产品模块做两处未提交变异：task 白名单旁路、未投喂降级旁路，验证后即还原，未进入提交） | 3 failed / 15 passed（恰为被变异分支对应的 3 例） |
| 还原后（后通过） | 同上 | 18 passed |
| 覆盖率 | 同上 + `--cov=deeptutor.learning.visual_practice --cov-report=term-missing` | 106 stmts，62%→64%；未覆盖行仅 165-196（account_for_recent_assistance）与 201-247（evaluate_visual），均为本卡范围外 |
| Lint | `ruff check deeptutor/learning/tests/test_visual_practice_preparation.py` | All checks passed |
