# 已消费导读卡结论漂移复核（guide-mastery / guide-reading，2026-10-07）

- 复核对象：`docs/guides/mastery-path.md`（@ `fcb131a96`）、`docs/guides/immersive-reading.md`（@ `787ddd799`），两份导读均声明基线 `origin/main` @ `ef2d9e5c3`（v1.6.12）。
- 新基线：`origin/main` @ `f07029cfc`（release v1.6.13，`ef2d9e5c3..f07029cfc` 共 330 个文件变更）。
- 方式：全程只读复核。仅新增本 evidence 目录与新分支；未改动两份导读文件，未重生成对方报告，未 checkout/reset/clean 既有工作区。
- 去重说明：
  - verify-consumed-tests-green（consumed-tests-20261005，测试健康轴）：本卡仅因 reading 导读自带"402 passed"计数结论而复跑 `tests/reading`（新基线 415 passed），未复制其逐卡测试矩阵。
  - verify-consumed-pr-state（verify/consumed-pr-state-20261007，PR 状态轴）：上游 issue/PR 开合状态归该卡，本卡只给代码面证据，不复核 PR 状态。
  - verify-guide-anchors（AGEN-899，verify-guide-anchors-20261006，锚点抽检轴）：其样本为 15 张 guide-* 候选卡、44 个卡面路径/行数声明，且明确记录"卡内无带行号的 path:line 字面锚点（行号是产出导读时才落）"；本卡样本是两份已产出导读内的 219 个 `path:line` 锚点，**样本不重叠**。

## 三态计数

**锚点级（219 个 path:line 锚点，覆盖两份导读全部锚点）**

| 报告 | 仍成立（行号未动） | 漂移（行号移动、原文逐字保留） | 失效 |
|---|---|---|---|
| guide-mastery | 17 | 98 | 0 |
| guide-reading | 79 | 25 | 0 |

- 123 个漂移锚点全部为**纯行号平移**（+1～+69，多数 +6～+31），旧行原文在新文件逐字命中，无一处对象被删改（`anchors.json` 逐条明细）。
- 另有 1 处区间内措辞更新：`deeptutor/capabilities/mastery/prompts/en/mastery_loop.yaml:95`（导读锚 `:30-127` 区间内，playbook 增加"选项下发前洗牌"一句），锚点块本身仍定位。

**结论级（逐报告主要结论 19 项）**

| 报告 | 仍成立 | 漂移（本体成立、数字/行号过期） | 失效（被 v1.6.13 推翻） |
|---|---|---|---|
| guide-mastery | 8 | 0 | 2（§6 #1646、§6 #1624） |
| guide-reading | 5 | 2（§四 文件表行数、§七 测试计数） | 1（§六 EPUB TOC 锚点坑，部分：锚点修复已落地） |

- 合计：复核 18 项 = 仍成立 13 / 漂移 2 / 失效 3；另 reading §八上游状态 1 项归 verify-consumed-pr-state 轴，本卡不复核。

## 关键发现（新基线 path:line）

1. **mastery §6 #1646 结论失效（已修）**：导读称"删除路由走较弱的运行时取消，`waiting_input` 行不处理 → 孤儿回合持锁"。v1.6.13 中 `deeptutor/api/routers/sessions.py:486-497` 删除路由改走应用层 `cancel_turn_and_wait`（失败即 409）；`deeptutor/app/service.py:262-283` `cancel_turn` 状态集纳入 `waiting_input` 并新增 `_reap_unowned_live_turn`（`app/service.py:391`）回收无主回合；`deeptutor/api/routers/mastery_path.py:107-149` `_cancel_active_learning_turn` 同步改造。`deeptutor/services/session/turns/lifecycle.py` 本身未变（弱运行时取消仍在），但删除/管理路径已不依赖它。
2. **mastery §6 #1624 结论失效（已修）**：导读称"答案字母触发无上下文 KB 检索（播种路径不识别 mastery_answer）"。v1.6.13 新增 `MasteryLoopCapability.skip_kb_seed`（`deeptutor/capabilities/mastery/loop.py:428-447`）与 `AgenticLoopPipeline._capability_skips_kb_seed`（`deeptutor/agents/loop/pipeline.py:851-874`），并在 KB 预播种入口短路（`pipeline.py:1484-1485`）；`executor.py:953-956` 新增 `mastery_card_answered` 元数据（"'A' is an answer, not something to search"）。
3. **reading §六 EPUB TOC 锚点坑部分失效**：导读称"TOC 锚点/位置标注是上游在修的活跃 bug（#1673，PR #1686 open）"。v1.6.13 已落地 publisher anchors：`OutlineEntry.source_href/source_anchor`（`deeptutor/reading/models.py:139-140,148-166`）、存量 outline 自动升级 `_upgrade_epub_outline`（`deeptutor/reading/store.py:943-996`）、spine 锚点解析（`deeptutor/utils/document_extractor.py:949` 起）。"EPUB 无忠实原文视图"半句仍成立。
4. **reading §七 测试计数漂移**：导读"402 passed, 0 failed（ef2d9e5c3）"→ 新基线 `pytest tests/reading` = **415 passed, 0 failed（5.61s）**；"25 个测试文件（26 含 conftest）"不变。
5. **reading §四 文件表行数漂移（6/20）**：extract.py 579→598、store.py 1516→1566、models.py 523→538、routers/reading.py 1559→1570（路由数 51→51 不变）、reading_extensions.py 414→498、ReaderPane.tsx 1343→1380。其余 14 个文件行数精确不变。
6. **新增漂移面（导读未覆盖，非推翻）**：
   - mastery：选择题选项下发前洗牌 `_shuffle_choice_options`（`deeptutor/capabilities/mastery/tools.py:290-316`，#1691）+ prompt yaml 同步措辞；sqlite_store turn 命令 outbox/幂等 ACK 扩展（`deeptutor/services/session/sqlite_store.py` +184 行，`transition_turn` 1494→1521 等）。
   - reading：read-aloud TTS 端点落地（`deeptutor/api/routers/reading_extensions.py:41-95` 一带，#1654 演进项开始落地；web 新增 `use-read-aloud-speech.ts`）；MD fence 解析修复（info string / 长 fence，`extract.py:455-482`）；`_turn_runtime_shared.py:1199-1262` 选区新增 LaTeX body 等价 grounding（"选区 untrusted"结论不受影响）。

## 逐条明细

- mastery 逐结论：`mastery-memo.md`
- reading 逐结论：`reading-memo.md`
- 锚点逐条机读明细：`anchors.json`
- tests/reading 复跑输出：`pytest-reading.txt`

## 只读声明

本次运行未改动两份导读文件、未重生成对方报告、未 checkout/reset/clean 既有工作区、未启动任何服务或后台进程（pytest 为前台限时跑批，已退出）；唯一写入为本 evidence 目录与本卡新分支 `verify/consumed-guides-drift-20261007`。
