# weak-done-drift 复核结论（20261009）

- 基线 `origin/main` `6cf793bd868b`（v1.6.14）；60 个唯一模块全部复核，逐条见 `status.md`，机读 `modules.json`
- 汇总：**已合入 57 / 仍缺 3 / 文件漂移 0**（合计 60）

## 已合入（57）→ 对应卡可关账

60 个目标文件全部仍在 main 原路径（无改名/删除）。其中 57 个在 main 已有触达测试，harvest 可按已合入关账。
清单：`agents.loop.context_budget`、`api.contracts.turn_protocol`、`api.routers.file_preview`、`api.routers.mcp_settings`、`api.routers.partner_groups`、`api.routers.question_notebook`、`api.routers.space_cli_apps`、`api.routers.space_mcp`、`api.run_server`、`book.agents.page_planner`、`capabilities.obsidian.vault`、`co_writer.edit_agent`、`learning.assessment`、`learning.grading`、`learning.objective_relations`、`learning.pending`、`learning.topic_naming`、`multi_user.book_access`、`partners.channels.lark_http`、`partners.channels.msteams`、`partners.channels.napcat`、`partners.channels.wecom`、`runtime.background_leader`、`services.chat_hints`、`services.config.readiness`、`services.doctor`、`services.embedding.adapters.dashscope_native`、`services.embedding.adapters.gemini`、`services.generation_http`、`services.llm.error_mapping`、`services.llm.local_provider`、`services.memory.consolidator.line_doc`、`services.memory.consolidator.modes.audit`、`services.office_preview`、`services.parsing.engines._install`、`services.partners.weixin_onboarding`、`services.rag.eval.dataset`、`services.rag.eval.matching`、`services.rag.pipelines.lightrag.sidecar`、`services.reading_hints`、`services.search.consolidation`、`services.search.source_filter`、`services.skill.taxonomy`、`services.subagent.claude_code`、`services.subagent.deepseek_harness`、`services.subagent.opencode_server`、`services.voice.adapters.openai_compat`、`services.voice.adapters.volcengine`、`services.workspace.dependencies`、`services.workspace.kb_move`、`services.workspace.session_transfer`、`tools.mastery_nav`、`tools.media_gen_tool`、`tools.partner_memory`、`tools.question_bank`、`tools.vision.ggb_validator`、`video_learning.invidious_account`

## 仍缺（3）→ 建议续卡

目标文件仍在 main，但 main 无有效触达测试（仅有其他测试对其 monkeypatch 打桩）；对应 myfork 测试分支均未合入：
- `partners.channels.matrix`（AGEN-743）— myfork/test/matrix-channel-20261005 未合入
- `services.rag.provider_binding`（AGEN-824）— myfork/test/rag-provider-binding-20261006 未合入
- `tools.reason`（AGEN-849）— myfork/test/reason-brainstorm-tools-20261006 未合入

## 文件漂移（0）

无。60 个索引目标文件在 `6cf793bd868b` 全部仍按原路径存在，无改名/删除/包化（`__init__.py` 化）。

## 附注
- `services.rag.eval.dataset` 经 `deeptutor/services/rag/eval/__init__.py:23` 再导出被 `tests/services/rag/eval/test_eval_dataset.py` 功能覆盖，计已合入
- `services.rag.provider_binding` 的 6 处 main 引用均为 kb_eval_cli / source_partitioning / github_source_unchanged_sync / lightrag_roles / pageindex_tools 测试对 `resolve_bound_provider` 的打桩，非本模块覆盖
- `tools.reason` 的 2 处 main 引用（knowledge_frontier / builtin_tools 测试）均为注入 fake，非本模块覆盖
- 判定方法与全部命中行见 `modules.json`（含每模块命中的测试文件与匹配行）