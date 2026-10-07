## 附录 A：全量命中清单（data.json 摘要视图）

### A.1 P1 except 处理器（105 条）

| # | 位置 | 函数 | 类别 | 复抛 | 吞掉 | 所在 finally |
| - | ---- | ---- | ---- | ---- | ---- | ---- |
| A1 | `agents/loop/agent_loop.py:1357` | `_call_llm` | except-cancelled | 是 | 否 | 否 |
| A2 | `api/routers/book.py:1514` | `close` | except-cancelled | 否 | 是 | 否 |
| A3 | `api/routers/question.py:334` | `websocket_mimic_generate` | except-cancelled | 否 | 是 | 是 |
| A4 | `api/routers/question.py:564` | `websocket_question_generate` | except-cancelled | 否 | 是 | 否 |
| A5 | `api/routers/unified_ws.py:137` | `stop_subscription` | except-cancelled | 否 | 是 | 否 |
| A6 | `api/routers/unified_ws.py:145` | `_forward` | except-cancelled | 是 | 否 | 否 |
| A7 | `api/routers/unified_ws.py:164` | `_forward` | except-cancelled | 是 | 否 | 否 |
| A8 | `book/blocks/base.py:150` | `generate` | except-cancelled | 是 | 否 | 否 |
| A9 | `book/engine.py:1420` | `_ensure_worker` | except-baseexception | 是 | 否 | 否 |
| A10 | `book/engine.py:1477` | `_worker_loop_active` | except-cancelled | 是 | 否 | 否 |
| A11 | `events/event_bus.py:139` | `_process_events` | except-cancelled | 否 | 是 | 否 |
| A12 | `events/event_bus.py:182` | `stop` | except-cancelled | 否 | 是 | 否 |
| A13 | `partners/channels/discord.py:94` | `start` | except-cancelled | 否 | 是 | 否 |
| A14 | `partners/channels/discord.py:504` | `typing_loop` | except-cancelled | 否 | 是 | 否 |
| A15 | `partners/channels/feishu.py:589` | `run_ws` | except-cancelled | 否 | 是 | 否 |
| A16 | `partners/channels/manager.py:172` | `send_with_retry` | except-cancelled | 是 | 否 | 否 |
| A17 | `partners/channels/manager.py:189` | `send_with_retry` | except-cancelled | 是 | 否 | 否 |
| A18 | `partners/channels/manager.py:330` | `_start_channel` | except-cancelled | 是 | 否 | 否 |
| A19 | `partners/channels/manager.py:458` | `_dispatch_outbound` | except-cancelled | 否 | 是 | 否 |
| A20 | `partners/channels/matrix.py:289` | `stop` | except-cancelled | 否 | 是 | 否 |
| A21 | `partners/channels/matrix.py:293` | `stop` | except-cancelled | 否 | 是 | 否 |
| A22 | `partners/channels/matrix.py:544` | `loop` | except-cancelled | 否 | 是 | 否 |
| A23 | `partners/channels/matrix.py:554` | `_stop_typing_keepalive` | except-cancelled | 否 | 是 | 否 |
| A24 | `partners/channels/matrix.py:563` | `_sync_loop` | except-cancelled | 否 | 是 | 否 |
| A25 | `partners/channels/mattermost.py:155` | `start` | except-cancelled | 否 | 是 | 否 |
| A26 | `partners/channels/mochat.py:709` | `_session_watch_worker` | except-cancelled | 否 | 是 | 否 |
| A27 | `partners/channels/mochat.py:742` | `_panel_poll_worker` | except-cancelled | 否 | 是 | 否 |
| A28 | `partners/channels/napcat.py:108` | `start` | except-cancelled | 是 | 否 | 否 |
| A29 | `partners/channels/napcat.py:236` | `_done` | except-cancelled | 否 | 是 | 否 |
| A30 | `partners/channels/telegram.py:1108` | `_typing_loop` | except-cancelled | 否 | 是 | 否 |
| A31 | `partners/channels/whatsapp.py:81` | `start` | except-cancelled | 否 | 是 | 否 |
| A32 | `partners/channels/zulip.py:847` | `_typing_loop` | except-cancelled | 否 | 是 | 否 |
| A33 | `reading/catalog_store.py:249` | `_remove_content_id_unique_constraint` | except-baseexception | 是 | 否 | 否 |
| A34 | `reading/store.py:1167` | `staged_delete` | except-baseexception | 是 | 否 | 否 |
| A35 | `runtime/background_leader.py:104` | `_run` | except-cancelled | 是 | 否 | 否 |
| A36 | `runtime/background_leader.py:147` | `_heartbeat_loop` | except-cancelled | 是 | 否 | 否 |
| A37 | `runtime/background_leader.py:205` | `_start_services` | except-cancelled | 是 | 否 | 否 |
| A38 | `runtime/isolated_worker.py:198` | `run_in_isolated_process` | except-cancelled | 是 | 否 | 否 |
| A39 | `runtime/worker_process.py:31` | `_execute` | except-baseexception | 否 | 是 | 否 |
| A40 | `runtime/worker_process.py:59` | `main` | except-baseexception | 否 | 是 | 否 |
| A41 | `services/base_sync.py:87` | `stop` | except-cancelled | 否 | 是 | 否 |
| A42 | `services/codebuddy_auth.py:170` | `_wait_for_login` | except-cancelled | 否 | 是 | 否 |
| A43 | `services/codex_auth/oauth.py:248` | `wait` | except-cancelled | 是 | 否 | 否 |
| A44 | `services/codex_auth/service.py:651` | `_run_login` | except-cancelled | 否 | 是 | 否 |
| A45 | `services/cron/service.py:327` | `stop` | except-cancelled | 否 | 是 | 否 |
| A46 | `services/cron/service.py:335` | `_loop` | except-cancelled | 是 | 否 | 否 |
| A47 | `services/llm/metrics.py:207` | `measure_provider_call` | except-baseexception | 是 | 否 | 否 |
| A48 | `services/llm/metrics.py:236` | `__anext__` | except-baseexception | 是 | 否 | 否 |
| A49 | `services/llm/metrics.py:272` | `measured_create` | except-baseexception | 是 | 否 | 否 |
| A50 | `services/llm/provider_core/base.py:384` | `_call_with_retry` | except-cancelled | 是 | 否 | 否 |
| A51 | `services/llm/provider_core/codebuddy_provider.py:115` | `_owner_loop` | except-baseexception | 否 | 是 | 是 |
| A52 | `services/llm/provider_core/codebuddy_provider.py:107` | `_owner_loop` | except-baseexception | 是 | 否 | 否 |
| A53 | `services/llm/provider_core/codebuddy_provider.py:104` | `_owner_loop` | except-baseexception | 否 | 是 | 否 |
| A54 | `services/llm/provider_core/codebuddy_provider.py:297` | `_run_session` | except-baseexception | 是 | 否 | 否 |
| A55 | `services/llm/provider_core/codebuddy_provider.py:359` | `aclose` | except-cancelled | 否 | 是 | 否 |
| A56 | `services/mcp/manager.py:463` | `call_tool` | except-cancelled | 是 | 否 | 否 |
| A57 | `services/mcp/manager.py:503` | `_call_watching_connection` | except-baseexception | 是 | 否 | 否 |
| A58 | `services/mcp/manager.py:528` | `_abandon` | except-cancelled | 是 | 否 | 否 |
| A59 | `services/memory/consolidator/runs.py:278` | `_drive` | except-cancelled | 否 | 是 | 否 |
| A60 | `services/parsing/engines/docling/local_worker.py:76` | `parse_local` | except-baseexception | 是 | 否 | 否 |
| A61 | `services/parsing/engines/mineru/local.py:284` | `parse_document_with_mineru_result` | except-baseexception | 是 | 否 | 否 |
| A62 | `services/partner_groups/manager.py:783` | `approve_invocation` | except-cancelled | 是 | 否 | 否 |
| A63 | `services/partner_groups/manager.py:895` | `run` | except-cancelled | 是 | 否 | 否 |
| A64 | `services/partner_groups/manager.py:950` | `run` | except-cancelled | 是 | 否 | 否 |
| A65 | `services/partner_groups/manager.py:1009` | `run` | except-cancelled | 是 | 否 | 否 |
| A66 | `services/partner_groups/manager.py:1071` | `run` | except-cancelled | 是 | 否 | 否 |
| A67 | `services/partner_groups/manager.py:1323` | `_run_partner_reply` | except-cancelled | 是 | 否 | 否 |
| A68 | `services/partners/manager.py:889` | `_outbound_router` | except-cancelled | 否 | 是 | 否 |
| A69 | `services/partners/manager.py:881` | `_outbound_router` | except-cancelled | 是 | 否 | 否 |
| A70 | `services/partners/manager.py:914` | `stop_partner` | except-cancelled | 否 | 是 | 否 |
| A71 | `services/partners/manager.py:1020` | `_teardown_channel_listeners` | except-cancelled | 否 | 是 | 否 |
| A72 | `services/partners/manager.py:1387` | `_drive_web_turn` | except-cancelled | 是 | 否 | 否 |
| A73 | `services/partners/runtime.py:169` | `run` | except-cancelled | 是 | 否 | 否 |
| A74 | `services/rag/pipelines/lightrag/ingress.py:297` | `freeze_document` | except-baseexception | 是 | 否 | 否 |
| A75 | `services/rag/pipelines/lightrag/pipeline.py:315` | `job` | except-baseexception | 是 | 否 | 否 |
| A76 | `services/rag/pipelines/lightrag/pipeline.py:360` | `job` | except-baseexception | 是 | 否 | 是 |
| A77 | `services/rag/pipelines/lightrag/pipeline.py:345` | `job` | except-baseexception | 是 | 否 | 否 |
| A78 | `services/rag/pipelines/lightrag/pipeline.py:351` | `job` | except-baseexception | 否 | 是 | 否 |
| A79 | `services/rag/pipelines/lightrag/pipeline.py:412` | `_publish_new_version` | except-baseexception | 是 | 否 | 否 |
| A80 | `services/rag/pipelines/lightrag/pipeline.py:469` | `_initialize_owned` | except-cancelled | 是 | 否 | 否 |
| A81 | `services/rag/pipelines/lightrag/worker.py:144` | `run` | except-baseexception | 是 | 否 | 否 |
| A82 | `services/rag/pipelines/lightrag/worker.py:154` | `run` | except-cancelled | 是 | 否 | 否 |
| A83 | `services/rag/pipelines/lightrag/worker.py:195` | `run_bound_job` | except-baseexception | 否 | 是 | 否 |
| A84 | `services/rag/pipelines/lightrag/worker.py:207` | `submit` | except-baseexception | 否 | 是 | 否 |
| A85 | `services/rag/pipelines/lightrag/worker.py:218` | `run_in_worker_loop` | except-cancelled | 是 | 否 | 否 |
| A86 | `services/rag/pipelines/lightrag/worker.py:227` | `run_in_worker_loop` | except-cancelled | 否 | 是 | 否 |
| A87 | `services/rag/pipelines/lightrag/worker.py:242` | `run_in_worker_loop` | except-cancelled | 否 | 是 | 否 |
| A88 | `services/rag/pipelines/lightrag/worker.py:250` | `run_in_worker_loop` | except-baseexception | 否 | 是 | 否 |
| A89 | `services/rag/pipelines/llamaindex/pipeline.py:135` | `_run_with_stall_guard` | except-baseexception | 是 | 否 | 否 |
| A90 | `services/search/providers/doubao.py:98` | `search` | except-baseexception | 是 | 否 | 否 |
| A91 | `services/search/providers/perplexity.py:75` | `search` | except-baseexception | 是 | 否 | 否 |
| A92 | `services/session/turns/executor.py:1220` | `_run_turn` | except-cancelled | 是 | 否 | 否 |
| A93 | `services/session/turns/lifecycle.py:295` | `_coordinate_execution` | except-cancelled | 是 | 否 | 否 |
| A94 | `services/session/turns/lifecycle.py:321` | `cancel_turn` | except-cancelled | 否 | 是 | 否 |
| A95 | `services/session/turns/request_preparer.py:803` | `start_turn` | except-baseexception | 是 | 否 | 否 |
| A96 | `services/subagent/opencode_family.py:170` | `consult` | except-cancelled | 是 | 否 | 否 |
| A97 | `services/subagent/opencode_family.py:163` | `consult` | except-cancelled | 是 | 否 | 否 |
| A98 | `services/subagent/partner.py:182` | `consult` | except-cancelled | 是 | 否 | 否 |
| A99 | `services/subagent/partner_group.py:110` | `consult` | except-cancelled | 是 | 否 | 否 |
| A100 | `services/voice/audio.py:69` | `normalize_wav` | except-cancelled | 是 | 否 | 否 |
| A101 | `services/web_source/scheduler.py:99` | `stop` | except-cancelled | 否 | 是 | 否 |
| A102 | `services/web_source/scheduler.py:256` | `_run_job` | except-cancelled | 是 | 否 | 否 |
| A103 | `services/workspace/activity.py:33` | `acquire_activity` | except-baseexception | 是 | 否 | 否 |
| A104 | `services/workspace/kb_move.py:417` | `move_kb` | except-baseexception | 是 | 否 | 否 |
| A105 | `utils/secret_files.py:45` | `write_secret_text` | except-baseexception | 是 | 否 | 否 |

### A.2 P2 contextlib.suppress(CancelledError)（17 条）

| # | 位置 | 函数 |
| - | ---- | ---- |
| B1 | `agents/loop/agent_loop.py:1225` | `_stop_reasoning_progress_task` |
| B2 | `api/routers/mastery_path.py:816` | `stop_forwarding` |
| B3 | `partners/channels/manager.py:332` | `_start_channel` |
| B4 | `partners/channels/manager.py:364` | `stop_all` |
| B5 | `partners/channels/weixin.py:1071` | `send` |
| B6 | `partners/channels/weixin.py:1129` | `_stop_typing` |
| B7 | `runtime/background_leader.py:62` | `close` |
| B8 | `runtime/background_leader.py:136` | `_stop_heartbeat` |
| B9 | `runtime/background_leader.py:177` | `_while_leader` |
| B10 | `runtime/background_leader.py:180` | `_while_leader` |
| B11 | `runtime/background_leader.py:170` | `_while_leader` |
| B12 | `runtime/orchestrator.py:199` | `handle` |
| B13 | `services/cli_apps/provider.py:389` | `_with_heartbeat` |
| B14 | `services/llm/factory.py:722` | `stream` |
| B15 | `services/session/turns/executor.py:1412` | `_run_turn` |
| B16 | `services/subagent/partner.py:144` | `consult` |
| B17 | `services/subagent/partner.py:185` | `consult` |

### A.3 P3 手动锁 acquire（5 条）

| # | 位置 | 函数 | 摘录 |
| - | ---- | ---- | ---- |
| C1 | `runtime/isolated_worker.py:178` | `run_in_isolated_process` | _WORKER_SLOTS.acquire(blocking=False) |
| C2 | `services/embedding/client.py:68` | `_hold_spacing_lock` | lock.acquire(blocking=False) |
| C3 | `services/llm/traffic_control.py:88` | `__aenter__` | self._semaphore.acquire() |
| C4 | `services/sandbox/quota.py:74` | `acquire` | sem.acquire() |
| C5 | `services/sandbox/service.py:125` | `run` | self._quota.acquire(user_id) |

### A.4 P4 wait_for/wait/timeout（93 条，含 tests 4 条）

| # | 位置 | 函数 | 形态 |
| - | ---- | ---- | ---- |
| D1 | `agents/math_animator/retry_manager.py:144` | `render_with_retries` | asyncio-wait_for |
| D2 | `agents/math_animator/retry_manager.py:70` | `render_with_retries` | asyncio-wait_for |
| D3 | `agents/math_animator/retry_manager.py:111` | `render_with_retries` | asyncio-wait_for |
| D4 | `api/routers/knowledge.py:4449` | `websocket_progress` | asyncio-wait_for |
| D5 | `api/routers/partners.py:1734` | `_partner_chat_stream` | asyncio-wait_for |
| D6 | `api/routers/partners.py:1975` | `_handle_channel_activity` | asyncio-wait |
| D7 | `api/routers/partners.py:1989` | `partner_chat_ws` | asyncio-wait |
| D8 | `api/routers/quiz_judge.py:433` | `websocket_quiz_judge` | asyncio-timeout |
| D9 | `api/routers/reading_extensions.py:257` | `run_extension_action` | asyncio-timeout |
| D10 | `api/routers/space_mcp.py:110` | `list_servers` | asyncio-wait_for |
| D11 | `api/utils/task_log_stream.py:262` | `stream` | asyncio-wait_for |
| D12 | `book/engine.py:1257` | `compile_page` | asyncio-wait |
| D13 | `book/engine.py:1448` | `_worker_loop_active` | asyncio-wait_for |
| D14 | `capabilities/mastery/tools.py:397` | `_sync_mastery_attempt_to_question_bank` | asyncio-wait_for |
| D15 | `capabilities/mastery/tools.py:447` | `_sync_qualitative_to_question_bank` | asyncio-wait_for |
| D16 | `capabilities/reading/figure_view.py:160` | `execute` | asyncio-wait_for |
| D17 | `events/event_bus.py:112` | `_process_events` | asyncio-wait_for |
| D18 | `events/event_bus.py:158` | `flush` | asyncio-wait_for |
| D19 | `events/event_bus.py:172` | `stop` | asyncio-wait_for |
| D20 | `learning/tests/test_event_hub.py:16` | `test_topic_hub_wakes_an_event_loop_from_a_worker_thread` | asyncio-wait_for |
| D21 | `learning/tests/test_event_hub.py:35` | `test_topic_hub_isolated_by_path_and_unsubscribes_cleanly` | asyncio-wait_for |
| D22 | `learning/tests/test_event_hub.py:49` | `test_topic_hub_isolated_by_workspace_scope` | asyncio-wait_for |
| D23 | `learning/tests/test_event_hub.py:66` | `test_topic_hub_coalesces_slow_subscriber_to_latest_signal` | asyncio-wait_for |
| D24 | `learning/topic_naming.py:147` | `suggest_topic_name` | asyncio-wait_for |
| D25 | `partners/channels/manager.py:422` | `_dispatch_outbound` | asyncio-wait_for |
| D26 | `partners/channels/matrix.py:286` | `stop` | asyncio-wait_for |
| D27 | `partners/channels/napcat.py:145` | `_run_once` | asyncio-wait_for |
| D28 | `partners/channels/napcat.py:512` | `_call_action` | asyncio-wait_for |
| D29 | `partners/channels/slack.py:110` | `start` | asyncio-wait_for |
| D30 | `reading/captions.py:100` | `_caption_one` | asyncio-wait_for |
| D31 | `runtime/agentic/labeled_step.py:511` | `run_labeled_step` | asyncio-wait_for |
| D32 | `runtime/agentic/tool_dispatch.py:725` | `_execute_with_policy` | asyncio-wait_for |
| D33 | `runtime/background_leader.py:94` | `_run` | asyncio-wait_for |
| D34 | `runtime/background_leader.py:165` | `_while_leader` | asyncio-wait |
| D35 | `runtime/isolated_worker.py:154` | `_stop_async_process` | asyncio-wait_for |
| D36 | `runtime/isolated_worker.py:192` | `run_in_isolated_process` | asyncio-wait_for |
| D37 | `runtime/providers/view.py:202` | `_owned_tools` | asyncio-wait_for |
| D38 | `runtime/stream_bus.py:337` | `wait_for_input` | asyncio-wait_for |
| D39 | `services/chat_hints.py:248` | `_call_llm` | asyncio-wait_for |
| D40 | `services/codex_auth/client_version.py:30` | `latest_client_version` | asyncio-timeout |
| D41 | `services/codex_auth/oauth.py:126` | `handle` | asyncio-wait_for |
| D42 | `services/codex_auth/oauth.py:235` | `wait` | asyncio-wait_for |
| D43 | `services/config/readiness.py:833` | `_selected_remote_parser_reachable` | asyncio-wait_for |
| D44 | `services/config/readiness.py:842` | `_selected_remote_parser_reachable` | asyncio-wait_for |
| D45 | `services/config/readiness.py:871` | `_redis_reachable` | asyncio-wait_for |
| D46 | `services/config/readiness.py:865` | `_redis_reachable` | asyncio-wait_for |
| D47 | `services/config/settings_spec.py:536` | `_probe_llm` | asyncio-wait_for |
| D48 | `services/config/settings_spec.py:606` | `_probe_embedding` | asyncio-wait_for |
| D49 | `services/cron/executor.py:70` | `_maybe_send_desktop_notification` | asyncio-wait_for |
| D50 | `services/cron/service.py:342` | `_loop` | asyncio-wait_for |
| D51 | `services/llm/factory.py:668` | `stream` | asyncio-wait_for |
| D52 | `services/llm/provider_core/anthropic_provider.py:578` | `chat_stream` | asyncio-wait_for |
| D53 | `services/llm/provider_core/anthropic_provider.py:596` | `chat_stream` | asyncio-wait_for |
| D54 | `services/llm/provider_core/azure_openai_provider.py:222` | `chat_stream` | asyncio-wait_for |
| D55 | `services/llm/provider_core/openai_compat_provider.py:1131` | `chat_stream` | asyncio-wait_for |
| D56 | `services/llm/provider_core/openai_compat_provider.py:1223` | `chat_stream` | asyncio-wait_for |
| D57 | `services/llm/traffic_control.py:88` | `__aenter__` | asyncio-wait_for |
| D58 | `services/mastery_hints.py:330` | `_generate` | asyncio-wait_for |
| D59 | `services/mcp/manager.py:500` | `_call_watching_connection` | asyncio-wait |
| D60 | `services/mcp/manager.py:547` | `_call_once` | asyncio-wait_for |
| D61 | `services/mcp/manager.py:642` | `_connect` | asyncio-wait_for |
| D62 | `services/mcp/manager.py:853` | `_disconnect` | asyncio-wait_for |
| D63 | `services/mcp/manager.py:925` | `probe_server` | asyncio-wait_for |
| D64 | `services/mcp/oauth.py:398` | `begin_authorization` | asyncio-wait_for |
| D65 | `services/partners/manager.py:913` | `stop_partner` | asyncio-wait_for |
| D66 | `services/partners/manager.py:1019` | `_teardown_channel_listeners` | asyncio-wait_for |
| D67 | `services/rag/pipelines/lightrag/worker.py:226` | `run_in_worker_loop` | asyncio-wait |
| D68 | `services/rag/pipelines/lightrag/worker.py:241` | `run_in_worker_loop` | asyncio-wait |
| D69 | `services/rag/pipelines/llamaindex/document_loader.py:362` | `_describe_one` | asyncio-wait_for |
| D70 | `services/rag/pipelines/llamaindex/document_loader.py:439` | `_describe_group` | asyncio-wait_for |
| D71 | `services/rag/pipelines/llamaindex/pipeline.py:148` | `_run_with_stall_guard` | asyncio-wait |
| D72 | `services/reading_hints.py:422` | `_call_llm` | asyncio-wait_for |
| D73 | `services/sandbox/backends.py:474` | `_terminate_process_tree` | asyncio-wait_for |
| D74 | `services/sandbox/backends.py:500` | `_communicate` | asyncio-wait_for |
| D75 | `services/sandbox/backends.py:490` | `_communicate` | asyncio-wait_for |
| D76 | `services/session/turns/lifecycle.py:93` | `close` | asyncio-wait |
| D77 | `services/session/turns/lifecycle.py:446` | `subscribe_turn` | asyncio-wait_for |
| D78 | `services/session/turns/title_service.py:122` | `_maybe_generate_session_title` | asyncio-wait_for |
| D79 | `services/settings/provider_probe.py:108` | `probe_search_provider` | asyncio-wait_for |
| D80 | `services/subagent/models.py:299` | `_list_cli_models` | asyncio-wait_for |
| D81 | `services/subagent/opencode_family.py:393` | `_wait_attached` | asyncio-wait |
| D82 | `services/subagent/opencode_server.py:189` | `shutdown_servers` | asyncio-wait_for |
| D83 | `services/subagent/process.py:131` | `_terminate` | asyncio-wait_for |
| D84 | `services/subagent/process.py:175` | `probe_version` | asyncio-wait_for |
| D85 | `services/suggestions.py:563` | `_generate` | asyncio-wait_for |
| D86 | `services/suggestions.py:658` | `_bounded_generation` | asyncio-wait_for |
| D87 | `services/voice/adapters/volcengine.py:88` | `synthesize` | asyncio-timeout |
| D88 | `services/voice/audio.py:68` | `normalize_wav` | asyncio-wait_for |
| D89 | `services/voice/base.py:77` | `synthesize_with_timeout` | asyncio-timeout |
| D90 | `tools/builtin/__init__.py:754` | `execute` | asyncio-wait_for |
| D91 | `tools/github_query.py:212` | `_default_command_runner` | asyncio-wait_for |
| D92 | `tools/paper_search_tool.py:99` | `search_papers` | asyncio-wait_for |
| D93 | `tools/paper_search_tool.py:85` | `search_papers` | asyncio-wait_for |

### A.5 P5 asyncio.shield（19 条）

| # | 位置 | 函数 |
| - | ---- | ---- |
| E1 | `api/routers/reading_extensions.py:265` | `run_extension_action` |
| E2 | `api/routers/workspace.py:61` | `_data_operation` |
| E3 | `api/routers/workspace.py:196` | `_migrate_workspaces` |
| E4 | `book/engine.py:1266` | `compile_page` |
| E5 | `capabilities/mastery/capability.py:109` | `run` |
| E6 | `partners/channels/matrix.py:287` | `stop` |
| E7 | `runtime/isolated_worker.py:199` | `run_in_isolated_process` |
| E8 | `services/codex_auth/oauth.py:235` | `wait` |
| E9 | `services/partners/manager.py:913` | `stop_partner` |
| E10 | `services/partners/manager.py:1019` | `_teardown_channel_listeners` |
| E11 | `services/rag/pipelines/lightrag/worker.py:217` | `run_in_worker_loop` |
| E12 | `services/session/turns/executor.py:206` | `_wait_for_user_reply` |
| E13 | `services/session/turns/executor.py:1395` | `_run_turn` |
| E14 | `services/session/turns/executor.py:1261` | `_run_turn` |
| E15 | `services/session/turns/executor.py:1287` | `_run_turn` |
| E16 | `services/subagent/opencode_family.py:167` | `consult` |
| E17 | `services/subagent/partner.py:146` | `consult` |
| E18 | `services/suggestions.py:629` | `refresh_suggestions` |
| E19 | `services/suggestions.py:645` | `refresh_suggestions` |
