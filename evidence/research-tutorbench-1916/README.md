# TutorBench 评测工件在库可用性调研（上游 #1916）

基线：origin/main `6cf793bd8`（v1.6.14, 2026-10-08）；核验日 2026-10-11；纯只读调研。
上游 #1916（OPEN，无关联 PR，无评论）问：TutorBench（270 任务 / 90 学习者画像 / 30 知识库）、
学生模拟器、judge 管线是否随仓库发布。结论逐项如下。

## 三态清单

| 工件 | main tip | main 历史 | 任一 release tag | origin/eval tip | eval 历史 |
|---|---|---|---|---|---|
| TutorBench 数据集（数据文件） | 不在库 | 仅论文源 03-09→03-20 | 不在库 | 不在库 | 不在库（从未提交） |
| TutorBench 构建代码 | 不在库 | 仅 2026-03-09 当天 | 不在库 | **在库**（benchmark/data_generation/ + benchmark/prompts/） | 在库 |
| 学生模拟器 | 不在库 | 仅 2026-03-09 当天 | 不在库 | **在库**（benchmark/simulation/） | 在库 |
| Judge 管线 | 不在库 | 仅 2026-03-09 当天 | 不在库 | **部分在库** | 在库（完整） |
| Trace Forest / TraceToolkit | 不在库 | 03-09→03-13 | 不在库 | **在库**（src/personalization/） | 在库 |

判定 1 —— TutorBench 数据集：**不在库（仅论文）**。
270/90/30 数字从未以数据文件入库：全历史无 benchmark/ 或 data/ 下任何 json/jsonl/csv 数据
提交（`benchmark/data/`、`paper/` 一直在 .gitignore）。数字出处是历史中的论文 LaTeX 源
（main 系 commit e11db5001，2026-03-15，paper/sections/experiments.tex:54-55）：
"produces 90 KB-grounded learner profiles overall, which is 270 interactive tasks"；
30 KB = 90 画像 ÷ 每 KB 3 画像（experiments.tex:37）。构建代码不生成固定数据，
输出写到被忽略的 `benchmark/data/bench_pipeline/`（README@a6d5f73db^）。

判定 2 —— 学生模拟器：**不在 main/不随 release 发布；在 origin/eval 分支仍在库**。
`benchmark/simulation/`（student_agent.py、conversation.py、profile_evolver.py、
batch_simulation.py、tools.py 即 TraceToolkit、test_tools.py、USE_TOOL.md）现存于
origin/eval tip（a6d5f73db, 2026-05-07）。main 系仅在 2026-03-09 merge（05f758e56）当天
存在，随即 ee419e832 移除。任何 tag（v0.2.0–v1.6.14，共 88 个）都不含 benchmark/。

判定 3 —— Judge 管线：**不在 main/不随 release 发布；eval tip 部分在库，完整版在 eval 历史**。
2026-05-07 eval 提交 a6d5f73db "Remove private benchmark pipeline artifacts" 删除
6318 行：benchmark/pipeline/（step1_generate_entries / step2_generate_transcripts /
step3_evaluate_transcripts / run_step2_multimodel_then_step3_fixed_judge / check_entries /
eval_summary）、benchmark/human_alignment/（live_judge.py 788 行、review_ui.html、
export/summarize_annotations、plot_alignment）、tests/benchmark/test_human_alignment.py。
eval tip 仍保留：benchmark/evaluation/（evaluator.py、run.py）、benchmark/prompts/
（student_system.yaml、eval_source_faithfulness_turn.yaml 等 14 个 judge/生成 prompt）、
benchmark/iso_solve/（core/judge.py）。完整三步管线仅存于 a6d5f73db^ 及更早的 eval 历史。

## 关键事实

- main/eval 分叉点 ddc0f48e3；benchmark 全系谱只在 eval 线；main 系 2026-03-09 短暂带入
  （05f758e56/f7d4adcc4），src/personalization 03-13（9c18bf070）、paper/ 03-20
  （c15e22a4b）相继移除。main tip 无任何 TutorBench/模拟器/judge/trace-forest 痕迹，
  仅剩与 #1916 无关的 `deeptutor kb eval`（检索 QA 评测，README.md:839）。
- eval tip README.md:116 仍有 "Main results on TutorBench" 残留段落与 table-1.png 引用。
- TraceToolkit 一词只出现在论文源（paper/sections/method.tex@e11db5001）与 eval tip 的
  benchmark/simulation/tools.py、src/personalization/ 中；main 上不存在。

## 复核命令（在 /Users/Shared/DeepTutor 任一只读视图执行）

```
git fetch --multiple origin myfork
git grep -il tutorbench origin/main                      # 空 = main tip 不在
git grep -ilE "student_agent|TraceToolkit" origin/main   # 空
git ls-tree -r --name-only origin/eval -- benchmark/simulation benchmark/data_generation  # 在库清单
git show --stat a6d5f73db                                # 6318 行删除清单
git show e11db5001:paper/sections/experiments.tex | sed -n '50,56p'   # 90 画像/270 任务原文
git log main --full-history --format="%h %ad %s" --date=short -- paper/ benchmark/ src/personalization
for t in $(git tag); do git cat-file -e "$t:benchmark" 2>/dev/null && echo "$t"; done  # 空 = 无 tag 含 benchmark
```

详细检索命令与输出摘录见 `search-commands.md`；文件校验见 `SHA256SUMS`。
