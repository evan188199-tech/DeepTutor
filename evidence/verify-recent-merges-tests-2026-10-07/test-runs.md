# 测试执行记录（逐条）

环境：macOS，Python venv `/Users/Shared/DeepTutor/.venv`（pytest 9.1.1），worktree 基于 `origin/dev` 3b672dac8。
命令模板：`perl -e 'alarm shift; exec @ARGV' 900 python -m pytest -q -p no:cacheprovider <files>`（等价 timeout 900）。

## PR 1635 — web_source 双语配对
命令：`python -m pytest -q -p no:cacheprovider tests/services/web_source/test_bilingual_pairing.py tests/services/test_web_source_sync.py tests/api/test_web_source_schedule_api.py`
结果：`38 passed in 1.85s` — PASS

## PR 1645 — video_learning watching marks
命令：`python -m pytest -q -p no:cacheprovider tests/video_learning/test_marks.py tests/video_learning/test_service.py`
结果：`37 passed in 0.49s` — PASS

## PR 1670 — mineru 本地失败原因
命令：`python -m pytest -q -p no:cacheprovider tests/services/parsing/test_mineru_local_failures.py tests/tools/test_mineru.py`
结果：`42 passed in 0.34s` — PASS

## PR 1706 — KB 状态/进度/目录同步
命令：`python -m pytest -q -p no:cacheprovider tests/api/test_knowledge_progress_ws.py tests/api/test_knowledge_router.py tests/knowledge/test_linked_folder_sync.py tests/knowledge/test_manager_update_kb_status_failures.py tests/services/test_codebuddy_credentials.py`
结果（首次，带真实 auth.json）：`5 failed, 148 passed` — 5 个失败集中在 tests/api/test_knowledge_router.py：
- test_weknora_probe_and_connect_endpoints
- test_connect_weknora_rejects_failed_probe
- test_lightrag_config_endpoint_round_trips_the_indexing_knobs
- test_lightrag_config_validates_dedicated_llm_selection
- test_lightrag_role_settings_validate_before_save
失败形态（样例，test_lightrag_role_settings_validate_before_save，tests/api/test_knowledge_router.py:3118）：
`AssertionError: assert 401 == 422` — 端点返回 401 Unauthorized 而非校验错误；根因是把主 checkout 的真实 auth.json 拷入 worktree，测试以鉴权态运行。非代码回归。
结果（移除 auth.json 后复跑，同命令）：`153 passed in 4.26s` — PASS

## PR 1387 — audio overview
命令：`python -m pytest -q -p no:cacheprovider tests/capabilities/test_audio_overview.py tests/core/test_capabilities_runtime.py`
结果：`15 passed in 0.81s` — PASS
（深度 pipeline 专职卡 test-audio-overview-pipeline 已另行跟进，本卡去重不重做）

## 未执行项
- web/tests/web-source-bilingual-pairing.spec.tsx、watching-browser.spec.tsx、watching-workspace.spec.tsx、knowledge-*.spec.tsx：playwright 用例，需浏览器/构建链，本卡未执行。
- web/tests/video-learning-marks.test.ts 等 vitest 用例：worktree 无 web/node_modules，未执行（见 README 补测候选 4）。
