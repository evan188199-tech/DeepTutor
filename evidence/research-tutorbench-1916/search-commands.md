# 检索命令记录（TutorBench #1916 调研）

执行环境：/Users/Shared/DeepTutor（只读），worktree /private/tmp/DeepTutor-agen1691-tutorbench
基线 commit：origin/main 6cf793bd8 "release: v1.6.14"；核验日 2026-10-11。
以下每条命令后附关键输出（截选）。

## 1. main tip 树内检索（全部为空 = 不在库）

```
git grep -in "tutorbench" origin/main --            # 无输出
git grep -inE "TraceToolkit|trace_?toolkit" origin/main --   # 无输出
git grep -inE "TraceForest|trace_?forest" origin/main --     # 无输出
git grep -ilE "iso_solve|human_alignment" origin/main --     # 无输出
git ls-tree --name-only origin/main -- benchmark data        # 无输出
git grep -ilE "simulator|tutorbench" origin/main -- docs/    # 无输出
git grep -icE "trace ?forest" origin/main --                 # 无输出
```

arXiv 号仅在元数据出现：

```
git grep -in "2604.26962" origin/main --
→ origin/main:CITATION.cff:37、README.md:35/231、assets/README/README_{AR,CN,ES,FR,...}.md
```

main tip 唯一相近物是无关的检索评测：README.md:839 `deeptutor kb eval`（Recall@k 等纯函数指标）。

## 2. 全历史 pickaxe（--all 含 eval 与全部 tag）

```
git log --all -i -S "TutorBench" --format="%H %ad %s" --date=short
→ a6d5f73db 2026-05-07 Remove private benchmark pipeline artifacts   （删除点，eval）
→ 29795b7f 2026-05-05 run live LLM judge for alignment plots          （eval）
→ 3393ac10 2026-05-05 update                                          （eval）
→ ced6f0d9 2026-04-11 docs: clean up                                  （eval）
→ 58f21db0 2026-04-11 update eval report                              （eval）
→ c15e22a4 2026-03-20 chore: stable fix, add tutorbot                 （main 系，删 paper/）
→ e11db500 2026-03-15 fix: improv cli                                 （main 系）
→ 05f758e5 2026-03-09 Selective merge eval branch ...                  （main 系，带入）
git log --all -S "TraceToolkit" / -S "TraceForest"   → 同一批提交族（830a1393b 2026-02-20 起最早）
```

## 3. a6d5f73db 删除清单（--stat 截选，共 19 文件 / +6 −6318）

```
benchmark/README.md                                          |  51 -
benchmark/human_alignment/USAGE.md                           | 336 -
benchmark/human_alignment/live_judge.py                      | 788 -
benchmark/human_alignment/review_ui.html                     | 872 -
benchmark/human_alignment/{export,summarize}_annotations.py  | 367/420 -
benchmark/human_alignment/{common,plot_alignment}.py         |  98/277 -
benchmark/pipeline/check_entries.py                          | 710 -
benchmark/pipeline/eval_summary.py                           | 385 -
benchmark/pipeline/run_step2_multimodel_then_step3_fixed_judge.py | 190 -
benchmark/pipeline/step1_generate_entries.py                 | 357 -
benchmark/pipeline/step2_generate_transcripts.py             | 610 -
benchmark/pipeline/step3_evaluate_transcripts.py             | 438 -
tests/benchmark/test_human_alignment.py                      | 299 -
同时 .gitignore 增加 benchmark/pipeline/、benchmark/human_alignment/、tests/benchmark/test_human_alignment.py
（上下文可见既有忽略项 benchmark/data/、paper/、benchmark/iso_solve/report_trace/）
```

## 4. eval tip（= a6d5f73db）仍在库的工件

```
git ls-tree -r --name-only origin/eval -- benchmark/ src/personalization
→ benchmark/data_generation/{init_kbs_and_profiles,profile_generator,task_generator,
   gap_generator,scope_generator,pipeline,batch_profiles,content_loader,llm_utils}.py
→ benchmark/evaluation/{evaluator,run,request_eval}.py
→ benchmark/iso_solve/（core/judge.py 等）
→ benchmark/prompts/（student_system.yaml、generate_{profile,task,gaps}*.yaml、
   eval_{turn,dialog,teaching_quality_turn,source_faithfulness_turn,gap_tracking_turn}.yaml，共14个）
→ benchmark/simulation/{student_agent,conversation,profile_evolver,batch_simulation,tools,test_tools}.py
   + USE_TOOL.md   （tools.py 含 TraceToolkit；USE_TOOL.md 描述 solve→generate→answer 学生工作流）
→ benchmark/tools/{check_kbs,fix_kb_config,fix_image_paths_in_kb}.py
→ src/personalization/{memory,memory_reader}.py + agents/{reflection,summary,weakness}_agent.py
→ origin/eval:README.md:116 "Table 1 — Main results on TutorBench"（残留段落）
```

## 5. 数据文件从未入库

```
git log --all --diff-filter=A --name-only --format="" \
  -- "benchmark/*.json" "benchmark/*.jsonl" "benchmark/*.csv" "**/benchmark/**/*.json"
→ 无输出
git ls-tree --name-only origin/eval -- data/   → data/README.md（仅此一个文件）
```

## 6. 数字出处（论文源，仅存于 main 历史 e11db5001，2026-03-15）

```
git show e11db5001:paper/sections/experiments.tex | sed -n '54,55p'
→ interactive tasks per profile via rejection sampling. In our current release, this
   produces 90 KB-grounded learner profiles overall, which is 270 interactive tasks.
git show e11db5001:paper/sections/experiments.tex | sed -n '37p'
→ Each KB instantiates three learner profiles---beginner, intermediate, and advanced---...
（90 ÷ 3 = 30 KB；intro.tex:32 早期草稿写 "100 profiles"，与 experiments 的 90 不一致）
```

## 7. main 系短暂在库窗口与谱系

```
git merge-base main origin/eval              → ddc0f48e3（分叉点）
git log main --full-history -- paper/ benchmark/ src/personalization
→ 05f758e5/f7d4adcc4 2026-03-09 带入；ee419e832 2026-03-09 删 benchmark；
  9c18bf070 2026-03-13 删 src/personalization；c15e22a4b 2026-03-20 删 paper/（18 文件 985 行）
git merge-base --is-ancestor a6d5f73db origin/main → NO（删除只发生在 eval 线）
```

## 8. tag 全量核查（88 个 tag，v0.2.0–v1.6.14）

```
for t in $(git tag --sort=creatordate); do git cat-file -e "$t:benchmark" 2>/dev/null && echo "$t"; done
→ 无输出（无任何 tag 含 benchmark/）
同法核查 "$t:paper" → 无输出
git merge-base --is-ancestor a6d5f73db v1.4.0|v1.5.0|v1.6.14|v1.3.0|v1.1.0 → 全部 no
（29795b7f 对 v1.0.0-beta.1–v1.3.0 亦全部 no）
```

## 9. 模拟器/judge 语义确认

```
git show a6d5f73db^:benchmark/pipeline/step2_generate_transcripts.py | grep -inE "simulat|student"
→ _simulate_profile_backend、--max-turns "Max student turns per session (default: 30)"
git show a6d5f73db^:benchmark/pipeline/step3_evaluate_transcripts.py | grep -inE "judge|scores"
→ faithfulness/personalization/applicability/vividness/logical_depth 评分聚合
git show a6d5f73db^:README.md | sed -n '143p'
→ "A student simulator is initialized from a TutorBench entry (profile, gaps, task); ..."
git show a6d5f73db^:benchmark/human_alignment/USAGE.md | sed -n '3p'
→ 盲法成对偏好人类对齐实验，10 个 TutorBench metrics，Step 3 LLM-as-judge 对比
```
