# 上游近期合并模块回归抽测（AGEN-1112）

- 日期：2026-10-07
- 基线：`origin/dev` = `3b672dac89da9e83c7e0997911abd91f85c0f2f0`（dev tip，新 worktree + 新分支，主 checkout 全程未动）
- 基线说明：任务卡写 origin/main，但 PR 1706（`50a3ba4e`）仅存在于 dev（origin/main=`f07029cf` 不含它，main 为 dev 祖先，dev 领先 78 个提交）。为满足"5 个 PR 每个触及模块都有结论"，改用 dev tip；dev tip 包含全部 5 个被审计合并。
- 审计对象（全部 MERGED into dev）：1635 双语 source pairing、1645 timestamped watching marks、1670 mineru 本地失败原因、1706 KB 状态/进度/目录同步失败可见化、1387 audio overview pipeline。
- 方法：每模块跑既有聚焦测试子集，`python -m pytest -q -p no:cacheprovider`，perl alarm 限时 900s；不改任何代码。

## 模块 × 测试 × 结果 × 缺口

| PR | 模块 | 测试子集 | 结果 | 缺口/备注 |
|---|---|---|---|---|
| 1635 | web_source 双语配对 | tests/services/web_source/test_bilingual_pairing.py、tests/services/test_web_source_sync.py、tests/api/test_web_source_schedule_api.py | 38 passed | crawler.py（CrawledPage/CrawlDiff/crawl_and_diff 双语字段，约 78 行）仅经 sync/bilingual 测试间接覆盖；前端 KbWebSourcesSection.tsx、features/knowledge/api/* 无单测；web-source-bilingual-pairing.spec.tsx 为 playwright 用例，本环境未执行 |
| 1645 | video_learning watching marks | tests/video_learning/test_marks.py、tests/video_learning/test_service.py | 37 passed | 后端覆盖充分（marks CRUD/隔离/建议 + service 23 用例）；WatchingMarksPanel.tsx、WatchingPane.tsx 无组件单测（仅 playwright specs）；video-learning-marks.test.ts（vitest）因 web/node_modules 未安装未执行 |
| 1670 | parsing/mineru 本地失败 | tests/services/parsing/test_mineru_local_failures.py、tests/tools/test_mineru.py | 42 passed | 无明显缺口；test_mineru_normalization/slicer/engines、test_runtime_settings 提供周边覆盖 |
| 1706 | knowledge KB 状态/进度/目录同步 | tests/api/test_knowledge_progress_ws.py、tests/api/test_knowledge_router.py、tests/knowledge/test_linked_folder_sync.py、tests/knowledge/test_manager_update_kb_status_failures.py、tests/services/test_codebuddy_credentials.py | 153 passed | 覆盖充分。附带确认：#1699 针对的 codebuddy 凭据 fixture 过期问题已被 1706 内提交 409f75c22（fixture 过期改相对时间）修复，dev tip 实测通过 |
| 1387 | capabilities/audio_overview | tests/capabilities/test_audio_overview.py、tests/core/test_capabilities_runtime.py | 15 passed | retrieve/generate_script/publish 链路已有 fake 级覆盖；深度 pipeline 覆盖由专职卡 test-audio-overview-pipeline 跟进（去重，本卡不重做） |

## 计数

- 模块结论：通过 5 / 失败 0 / 无直接测试 0
- 测试合计：285 passed，0 failed（各模块均远低于 900s 限时，最长 4.5s）
- 抽测方式：仅既有测试子集，无新增/修改测试

## 补测候选

1. web_source crawler 双语 diff 单测：1635 对 crawler.py 的 CrawlDiff/crawl_and_diff 改动建议补 crawler 级直接断言（当前靠 sync 测试间接触达）。
2. web KbWebSourcesSection.tsx 与 features/knowledge/api client 层单测（1635 前端面无 unit test）。
3. WatchingMarksPanel.tsx / WatchingPane.tsx 组件单测（1645 前端面无 unit test）。
4. web 层测试执行基建：worktree 场景无 web/node_modules，vitest 子集（video-learning-marks.test.ts、knowledge-progress.test.ts 等）无法快跑；建议单独安排一次 web vitest 抽测。
5. audio_overview 深度 pipeline 覆盖：已有专职卡跟进（去重标注，无需新卡）。

## 环境与执行注意（复跑者必读）

- 本机无 `timeout`/`gtimeout`，用 `perl -e 'alarm shift; exec @ARGV' 900 <cmd>` 限时（alarm 跨 exec 保留）。
- 运行时设置目录 data/user/settings 为 gitignored：从主 checkout 只读拷贝必要配置；**不要拷贝 auth.json** —— 拷入会使 test_knowledge_router 中 5 个用例进入鉴权态返回 401（预期 422/200），产生假阴性；本卡已复现并排除，见 test-runs.md。
- tests/services/test_codebuddy_credentials.py 在 dev tip 全绿；上游若有失败属旧基线问题，已由 #1699/409f75c2 处理。
