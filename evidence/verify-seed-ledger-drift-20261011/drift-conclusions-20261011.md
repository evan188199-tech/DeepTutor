# seed-ledger-20261010 可领取种子漂移复核（AGEN-1686，2026-10-11）

- 输入：myfork `evidence/seed-ledger-20261010`（131 条 claimable）＋当日看板快照 1686 张＋储备池 1056 张＋`origin/main 6cf793bd8`（与台账 fresh 复扫同一 commit，main 侧覆盖状态不变）
- 口径：**已建卡**=看板或储备池存在指向该种子的非取消卡（含人工复核补配，依据=卡 key＋描述核对）；**主题被覆盖**=模块已不在 main；**仍可领取**=两者皆无（仅 guide/docs/scan/verify/review 相关卡不去重）
- 汇总：131 = 已建卡 **114** + 主题被覆盖 **0** + 仍可领取 **17**
- 轴分布（仍可领取）：E=1，D=0，C=0，F=16
- 人工复核补配：据此改判 34 个种子（另为 FZ77 补上看板卡证据），共 38 张卡；标题空格形式/描述点名/批量卡 scope，逐条读卡核对，理由见 seeds-state-20261011.json 的 why 字段

| ID | 主题 | 结论 | 依据（卡 状态） | 备注 |
|---|---|---|---|---|
| C19 | `runtime.agentic.labels` | 已建卡 | AGEN-1442(in_review)、test-agentic-labels(储备) | 相关卡：AGEN-1466 |
| C25 | `services.session.workspace_preferences` | 已建卡 | AGEN-1444(in_review)、test-workspace-preferences(储备) | 相关卡：AGEN-1455 |
| C41 | `services.llm.provider_core.codebuddy_http_provider` | 已建卡 | AGEN-1305(done) | 卡已 done；main 未前移（仍 6cf793bd8），产出未合入 main，续卡前先核验原卡产出（AGEN-1305） |
| C44 | `services.parsing.engines.tika.formats` | 已建卡 | AGEN-1448(in_review)、test-tika-formats(储备) | 相关卡：AGEN-1456 |
| C46 | `learning.event_hub` | 已建卡 | AGEN-1450(in_review)、test-learning-event-hub(储备) | 相关卡：AGEN-1464 |
| C47 | `services.parsing.engines.markitdown.formats` | 已建卡 | AGEN-596(done)、AGEN-729(in_review) | 卡已 done；main 未前移（仍 6cf793bd8），产出未合入 main，续卡前先核验原卡产出（AGEN-596） |
| C49 | `services.workspace.navigation` | 已建卡 | AGEN-1489(in_review)、test-workspace-navigation(储备) | 相关卡：AGEN-1524 |
| C62 | `services.memory.consolidator.runs` | 已建卡 | AGEN-1458(in_review)、test-consolidator-runs(储备) | 相关卡：AGEN-1461 |
| C78 | `services.rag.pipelines.llamaindex.vector_store` | 已建卡 | AGEN-1306(in_review) | - |
| C80 | `api.routers.task_board` | 已建卡 | AGEN-1446(in_review)、test-task-board-router(储备) | 相关卡：AGEN-1457,AGEN-859,guide-task-board(储备) |
| C82 | `services.rag.linked_kb` | 已建卡 | AGEN-1475(in_review)、test-rag-linked-kb(储备) | 相关卡：AGEN-1480,AGEN-941,guide-network-validation(储备) |
| C89 | `services.workspace.session_move` | 已建卡 | AGEN-1599(in_review)、test-workspace-session-move(储备) | - |
| D1 | A feishu send 抛错语义 | 已建卡 | AGEN-1447(in_review) | - |
| D2 | B mochat send 抛错语义 | 已建卡 | AGEN-1449(in_review) | - |
| D3 | C dingtalk 投递与资源 | 已建卡 | AGEN-1451(in_review) | - |
| D7 | G stop 清理补全 | 已建卡 | AGEN-1452(in_review) | - |
| D9 | I 事件循环阻塞治理 | 已建卡 | AGEN-1453(in_review) | - |
| D10 | J 入站幂等补齐 | 已建卡 | AGEN-1497(in_review) | - |
| D11 | K qq/wecom 易失状态 | 已建卡 | AGEN-1498(in_review) | - |
| D12 | L 发送超时归一 | 已建卡 | AGEN-1499(in_review) | - |
| D13 | M not-running 契约文档化 | 已建卡 | AGEN-1504(in_review) | - |
| E13 | #13 LANG-MIX：后端 routers 不走 t()、web 硬编码文案绕过 locale | 已建卡 | AGEN-1509(in_review) | - |
| E14 | #14 NO-CODE：~597 处纯文本 detail 无机器可读 code | 仍可领取 | - | 子集卡在案（AGEN-1364 sessions.py、AGEN-880 web 解析层）；主项系统性 code 信封仍无卡 |
| E15 | #15 INCONSISTENT：not_found 15+ 种写法、网络失败/限流话术分裂 | 已建卡 | AGEN-1506(done) | 卡已 done；main 未前移（仍 6cf793bd8），产出未合入 main，续卡前先核验原卡产出（AGEN-1506） |
| FZ14 | `services.memory.consolidator.modes._runtime` | 已建卡 | AGEN-1459(in_review)、test-consolidator-modes-runtime(储备) | 相关卡：AGEN-1463 |
| FZ20 | `partners.channels.qq` | 已建卡 | AGEN-736(in_review) | - |
| FZ27 | `book.blocks._rag_helpers` | 已建卡 | AGEN-1058(in_review) | - |
| FZ28 | `services.search.providers.zhipu` | 已建卡 | AGEN-1476(in_review)、test-search-provider-zhipu(储备) | 相关卡：AGEN-1482 |
| FZ30 | `services.search.providers.firecrawl` | 已建卡 | AGEN-1477(in_review)、test-search-provider-firecrawl(储备) | 相关卡：AGEN-1479 |
| FZ33 | `book.blocks.animation` | 已建卡 | AGEN-1485(in_review)、test-book-block-animation(储备) | 相关卡：AGEN-1526 |
| FZ41 | `book.blocks.interactive` | 已建卡 | AGEN-1653(in_review)、test-book-blocks-batch2(储备) | - |
| FZ45 | `services.search.providers.searxng` | 已建卡 | AGEN-1655(in_review)、test-search-providers-keyless(储备) | - |
| FZ49 | `agents.math_animator.agents.visual_review_agent` | 已建卡 | AGEN-851(in_review) | - |
| FZ51 | `capabilities.reading._tool_base` | 仍可领取 | - | - |
| FZ53 | `agents.visualize.agents.review_agent` | 已建卡 | AGEN-1067(in_review) | - |
| FZ54 | `book.blocks.flash_cards` | 已建卡 | AGEN-1653(in_review)、test-book-blocks-batch2(储备) | - |
| FZ56 | `book.blocks.deep_dive` | 已建卡 | AGEN-1653(in_review)、test-book-blocks-batch2(储备) | - |
| FZ59 | `services.practice.analytics` | 已建卡 | AGEN-1486(in_review)、test-practice-analytics(储备) | 相关卡：AGEN-1525 |
| FZ60 | `book.blocks.timeline` | 已建卡 | AGEN-1653(in_review)、test-book-blocks-batch2(储备) | - |
| FZ64 | `services.search.providers.duckduckgo` | 已建卡 | AGEN-1655(in_review)、test-search-providers-keyless(储备) | - |
| FZ65 | `book.blocks.callout` | 已建卡 | AGEN-1653(in_review)、test-book-blocks-batch2(储备) | - |
| FZ70 | `services.mcp.session_state` | 已建卡 | AGEN-1055(in_review) | - |
| FZ72 | `services.rag.pipelines.llamaindex.errors` | 已建卡 | AGEN-1503(in_progress)、test-llamaindex-errors(储备) | - |
| FZ73 | `runtime.worker_tasks` | 已建卡 | AGEN-1061(in_review) | - |
| FZ77 | `knowledge.progress_events` | 已建卡 | AGEN-1062(in_review)、test-knowledge-initializer(储备) | - |
| FZ84 | `services.parsing.engines.formats` | 已建卡 | AGEN-967(in_review) | - |
| FZ85 | `core.response_languages` | 已建卡 | AGEN-996(in_review)、AGEN-906(in_review) | - |
| FZ86 | `book.blocks.user_note` | 已建卡 | AGEN-1653(in_review)、test-book-blocks-batch2(储备) | - |
| FZ88 | `services.session.turns.context_assembler` | 已建卡 | AGEN-1068(in_review) | - |
| FZ91 | `agents.notebook._text` | 已建卡 | AGEN-1600(in_review)、test-notebook-text-helper(储备) | - |
| FZ92 | `__version__` | 仍可领取 | - | 仅相关卡（不构成领取去重）：verify-citation-version-parity(储备) |
| FZ93 | `response_languages` | 已建卡 | AGEN-996(in_review)、AGEN-906(in_review) | - |
| FZ94 | `book.errors` | 仍可领取 | - | - |
| FZ95 | `__main__` | 仍可领取 | - | - |
| FZ96 | `services.llm.provider_registry` | 仍可领取 | - | 仅相关卡（不构成领取去重）：AGEN-1265,guide-provider-registry(储备) |
| FT1 | `services.parsing.engines.liteparse.formats` | 已建卡 | AGEN-1376(in_review) | - |
| FT13 | `services.rag.pipelines.llamaindex.exercise_lookup` | 已建卡 | AGEN-1490(in_review)、test-exercise-lookup(储备) | 相关卡：AGEN-1521 |
| FT20 | `capabilities.setup.jobs` | 已建卡 | AGEN-1491(in_review)、test-setup-jobs(储备) | 相关卡：AGEN-1523 |
| FT24 | `knowledge.naming` | 已建卡 | AGEN-1377(in_review)、test-knowledge-naming(储备) | 相关卡：AGEN-1427 |
| FT33 | `services.subagent.openclaw` | 已建卡 | AGEN-1623(in_review)、test-subagent-openclaw(储备) | 相关卡：AGEN-1645 |
| FT34 | `capabilities.reading.figure_view` | 已建卡 | AGEN-1492(in_review)、test-figure-view(储备) | 相关卡：AGEN-1520 |
| FT35 | `video_learning.invidious_account_storage` | 仍可领取 | - | AGEN-806 覆盖 invidious_account(.py)+client，storage.py 未含 |
| FT37 | `tools.cron_tool` | 已建卡 | AGEN-1494(in_review)、test-cron-tool(储备) | 相关卡：AGEN-1574,AGEN-1510,guide-cron-scheduling(储备) |
| FT39 | `services.rag.pipelines.lightrag.cache_reuse` | 已建卡 | AGEN-638(in_review) | - |
| FT40 | `tools.zotero_search` | 已建卡 | AGEN-1624(in_review)、test-zotero-search-tool(储备) | - |
| FT41 | `services.llm.image_caption_batch` | 已建卡 | AGEN-1625(in_review)、test-image-caption-batch(储备) | 相关卡：AGEN-1647 |
| FT42 | `services.rag.pipelines.llamaindex.rerank` | 已建卡 | AGEN-1502(in_review)、AGEN-1515(backlog)、AGEN-1514(backlog)、test-llamaindex-rerank(储备) | 相关卡：AGEN-1518 |
| FT44 | `services.subagent.partner_group` | 已建卡 | AGEN-1628(in_review)、test-subagent-partner-group(储备) | - |
| FT46 | `book.overview_copy` | 仍可领取 | - | - |
| FT50 | `services.imagegen.adapters.openai_compat` | 仍可领取 | - | AGEN-1046 为 scan 级，不去重 |
| FT51 | `services.parsing.engines.mineru.checkpoints` | 已建卡 | AGEN-1496(in_review)、test-mineru-checkpoints(储备) | 相关卡：AGEN-1516 |
| FT52 | `services.voice.adapters.minimax` | 已建卡 | AGEN-1638(done)、test-voice-adapter-minimax(储备) | 卡已 done；main 未前移（仍 6cf793bd8），产出未合入 main，续卡前先核验原卡产出（AGEN-1638） |
| FT53 | `video_learning.invidious_account_client` | 已建卡 | AGEN-806(in_review) | - |
| FT54 | `services.rag.smart_retriever` | 已建卡 | AGEN-1508(in_review)、test-rag-smart-retriever(储备) | 相关卡：AGEN-1511 |
| FT56 | `services.llm.request_cache` | 已建卡 | AGEN-1667(in_review)、test-llm-request-cache(储备) | 相关卡：AGEN-1673 |
| FT57 | `services.rag.pipelines.graphrag.pandas_compat` | 已建卡 | AGEN-1636(in_review)、test-graphrag-pandas-compat(储备) | - |
| FT64 | `textbook_struct.chapter_rebuild` | 已建卡 | AGEN-791(in_review) | - |
| FT65 | `services.llm.usage_estimation` | 已建卡 | AGEN-1620(done)、test-llm-usage-batch(储备) | 卡已 done；main 未前移（仍 6cf793bd8），产出未合入 main，续卡前先核验原卡产出（AGEN-1620） |
| FT67 | `agents.vision_solver.vision_solver_agent` | 已建卡 | AGEN-1383(in_review)、test-vision-solver-agent(储备) | 相关卡：AGEN-1389 |
| FT69 | `services.setup.data_volume` | 已建卡 | AGEN-1384(in_review)、test-setup-data-volume(储备) | 相关卡：AGEN-1437 |
| FT70 | `reading.knowledge_capture` | 已建卡 | AGEN-1385(in_review)、test-knowledge-capture(储备) | 相关卡：AGEN-1469 |
| FT71 | `services.session.event_preview` | 已建卡 | AGEN-1428(in_review)、AGEN-1391(in_review)、test-event-preview(储备) | 相关卡：AGEN-1430,AGEN-1426 |
| FT73 | `services.partners.runtime_status` | 已建卡 | AGEN-1392(in_review)、test-partner-runtime-status(储备) | 相关卡：AGEN-1400 |
| FT75 | `textbook_struct.page_headers` | 仍可领取 | - | AGEN-791 称 page_headers 现有测试；领取前 fresh 复扫确认触达数 |
| FT78 | `services.settings.starter_settings` | 已建卡 | AGEN-1394(in_review)、test-starter-settings(储备) | 相关卡：AGEN-1425 |
| FT79 | `agents._shared.json_output` | 已建卡 | AGEN-1680(in_review)、test-json-output-shared(储备) | - |
| FT81 | `services.web_source.navigation` | 已建卡 | AGEN-1396(in_review)、test-websource-navigation(储备) | 相关卡：AGEN-1413 |
| FT82 | `logging.formatters` | 已建卡 | AGEN-1417(in_review)、AGEN-1398(in_review)、test-logging-formatters(储备) | 相关卡：AGEN-1420,AGEN-1408 |
| FT86 | `services.partners.workspace_binding` | 已建卡 | AGEN-1401(in_review)、test-partner-workspace-binding(储备) | 相关卡：AGEN-1405 |
| FT87 | `services.practice.answers` | 已建卡 | AGEN-1418(in_review)、AGEN-1403(in_review)、test-practice-answers(储备) | 相关卡：AGEN-1421,AGEN-1406 |
| FT88 | `utils.text_display` | 已建卡 | AGEN-1404(done)、test-text-display-decode(储备) | 卡已 done；main 未前移（仍 6cf793bd8），产出未合入 main，续卡前先核验原卡产出（AGEN-1404） |
| FT91 | `services.search.providers.serply` | 已建卡 | AGEN-1621(in_review)、test-search-providers-batch2(储备) | 相关卡：AGEN-1641 |
| FT92 | `services.search.providers.aliyun_iqs` | 已建卡 | AGEN-1621(in_review)、test-search-providers-batch2(储备) | 相关卡：AGEN-1641 |
| FT93 | `services.search.providers.tavily` | 已建卡 | AGEN-1622(in_review)、test-search-providers-batch3(储备) | - |
| FT94 | `services.search.providers.perplexity` | 已建卡 | AGEN-1622(in_review)、test-search-providers-batch3(储备) | - |
| FT95 | `services.search.providers.qianfan` | 已建卡 | AGEN-1621(in_review)、test-search-providers-batch2(储备) | 相关卡：AGEN-1641 |
| FT96 | `services.search.providers.bocha` | 已建卡 | AGEN-1621(in_review)、test-search-providers-batch2(储备) | 相关卡：AGEN-1641 |
| FT99 | `services.rag.pipelines.lightrag.parser` | 已建卡 | AGEN-1505(in_review)、AGEN-1512(backlog)、test-lightrag-parser(储备) | 相关卡：AGEN-1513 |
| FT100 | `services.search.providers.brave` | 已建卡 | AGEN-1622(in_review)、test-search-providers-batch3(储备) | - |
| FT101 | `agents.loop.dsml_tool_calls` | 已建卡 | AGEN-1668(in_review)、test-dsml-tool-calls(储备) | 相关卡：AGEN-1675 |
| FT104 | `agents.math_animator.agents.code_generator_agent` | 已建卡 | AGEN-1344(in_review) | - |
| FT105 | `services.llm.telemetry` | 已建卡 | AGEN-1620(done)、test-llm-usage-batch(储备) | 卡已 done；main 未前移（仍 6cf793bd8），产出未合入 main，续卡前先核验原卡产出（AGEN-1620） |
| FT107 | `services.settings.registry_edit` | 已建卡 | AGEN-1656(in_review)、test-settings-edit-batch(储备) | 相关卡：AGEN-1662 |
| FT108 | `services.practice.importing` | 已建卡 | AGEN-1669(in_review)、test-practice-importing(储备) | - |
| FT110 | `services.cron.executor` | 已建卡 | AGEN-670(in_review) | - |
| FT112 | `agents.loop.ask_user_drafts` | 已建卡 | AGEN-1629(in_review)、test-ask-user-drafts(储备) | 相关卡：AGEN-1649 |
| FT113 | `services.videogen.adapters.async_task` | 已建卡 | AGEN-1017(in_review) | - |
| FT114 | `agents.math_animator.retry_manager` | 已建卡 | AGEN-1658(in_review)、test-math-animator-helpers-batch(储备) | 相关卡：AGEN-1672 |
| FT115 | `services.session.attachment_parsing` | 仍可领取 | - | - |
| FT116 | `services.config.settings_presets` | 仍可领取 | - | AGEN-1240 为 web lib settings-presets，非本后端模块 |
| FT117 | `services.partners.channel_state_migration` | 已建卡 | AGEN-1670(in_review)、test-channel-state-migration(储备) | - |
| FT118 | `agents.notebook.summarize_agent` | 已建卡 | AGEN-1639(in_review)、test-notebook-summarize-agent(储备) | 相关卡：AGEN-1657 |
| FT119 | `agents.question.agents.followup_agent` | 已建卡 | AGEN-1540(done)、test-question-followup-agent(储备) | 卡已 done；main 未前移（仍 6cf793bd8），产出未合入 main，续卡前先核验原卡产出（AGEN-1540） |
| FT120 | `agents.visualize.agents.code_generator_agent` | 仍可领取 | - | AGEN-1344 仅 math_animator 同名代理，visualize 侧无卡 |
| FT121 | `agents.math_animator.agents.concept_analysis_agent` | 已建卡 | AGEN-1644(in_review) | - |
| FT122 | `agents.research.utils.json_utils` | 仍可领取 | - | - |
| FT123 | `logging.configure` | 已建卡 | AGEN-1659(in_review)、test-logging-config-batch(储备) | 相关卡：AGEN-1677 |
| FT124 | `agents.math_animator.agents.summary_agent` | 已建卡 | AGEN-1644(in_review) | - |
| FT125 | `services.sandbox.quota` | 已建卡 | AGEN-1630(in_review)、test-sandbox-quota(储备) | 相关卡：AGEN-1642 |
| FT126 | `agents.question.request_config` | 已建卡 | AGEN-1679(in_review)、test-question-request-config(储备) | - |
| FT127 | `agents.math_animator.agents.concept_design_agent` | 已建卡 | AGEN-1644(in_review) | - |
| FT128 | `services.settings.provider_edit` | 已建卡 | AGEN-1656(in_review)、test-settings-edit-batch(储备) | 相关卡：AGEN-1662 |
| FT129 | `services.codex_auth.client_version` | 仍可领取 | - | AGEN-1009 文件清单（oauth/service/storage/catalog）不含 client_version.py |
| FT131 | `agents.math_animator.duration_utils` | 已建卡 | AGEN-1658(in_review)、test-math-animator-helpers-batch(储备) | 相关卡：AGEN-1672 |
| FT132 | `logging.loguru_bridge` | 已建卡 | AGEN-1659(in_review)、test-logging-config-batch(储备) | 相关卡：AGEN-1677 |
| FT133 | `services.session.turns.resource_reuse` | 仍可领取 | - | - |
| FT135 | `agents.question.coordinator` | 已建卡 | AGEN-1634(in_review)、test-question-coordinator(储备) | - |
| FT138 | `reading.vocabulary` | 已建卡 | AGEN-1643(in_review)、test-reading-vocabulary(储备) | - |
| FT139 | `reading.study_guidance` | 仍可领取 | - | - |
| FT140 | `utils.network.circuit_breaker` | 已建卡 | AGEN-1631(in_review)、test-network-circuit-breaker(储备) | - |
| FT141 | `core.errors` | 已建卡 | AGEN-1633(done)、test-core-errors(储备) | 卡已 done；main 未前移（仍 6cf793bd8），产出未合入 main，续卡前先核验原卡产出（AGEN-1633）；相关卡：AGEN-1640 |

## 复核命令

```bash
# 1) 看板快照（约 17 页）
python3 evidence/verify-seed-ledger-drift-20261011/verify_drift.py  # 缺快照时自动经 multica issue list 拉取
# 2) 校验产物
shasum -a 256 -c evidence/verify-seed-ledger-drift-20261011/SHA256SUMS
# 3) main 侧覆盖不变的依据：origin/main 与台账 fresh 扫描为同一 commit
git -C /Users/Shared/DeepTutor rev-parse origin/main   # 6cf793bd868ba…=台账 FRESH_COMMIT
```

