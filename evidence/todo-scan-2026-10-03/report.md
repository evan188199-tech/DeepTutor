# DT-22 · TODO/FIXME 与吞错扫描报告

- **扫描对象**: HKUDS/DeepTutor `origin/main` @ `ef2d9e5c3c99fd073742c5aadc2bb9584b1e503b`（v1.6.12）
- **扫描日期**: 2026-10-03（UTC）
- **方式**: 只读静态扫描（Python `ast` 遍历 + ripgrep 模式匹配 + 人工抽样复核）。**未修改任何代码。**
- **范围**: `deeptutor/`、`deeptutor_cli/`、`scripts/`、`tests/`（Python）；`web/`（TS/TSX/JS）。已排除 `deeptutor_web/`（打包产物）、`node_modules`、`.next`、构建产物。

## 1. 结论（PASS）

| 类别 | HIGH | MEDIUM | LOW | 合计 |
| --- | --- | --- | --- | --- |
| Python 静默异常处理器（`except …: pass/continue`） | 18 | 124 | 210 | 352 |
| TS/JS 吞错（空 catch / no-op `.catch` / 无兜底 floating promise） | 1 | 22 | 20 | 43 |

- **TODO/FIXME**: 全仓库源代码中 `TODO`/`FIXME`/`XXX`/`HACK` 标记为 **0 条**；仅 2 处 docstring 引用已不存在的 `TODO.md`（见 §4）。
- **裸 `except:`**: **0 条**（ripgrep 唯一命中为 docstring 文本，见 `deeptutor/capabilities/mastery/choices.py:20`，误报）。
- Python 侧共发现 **352** 个静默异常处理器（`pass` × 214，`continue` × 138），其中宽泛捕获（`except Exception/BaseException`）**118** 个。
- TS/JS 侧：空 `catch {}` 3 处、no-op `.catch(() => {})` 37 处、`void` 前缀 fire-and-forget 约 394 处（后者需数据流分析才能定性，本报告仅列出人工复核后的代表性条目，见 §3/附录 B）。

## 2. Top 风险（HIGH，人工复核摘要）

- `deeptutor/api/routers/knowledge.py:3952` — `run_reindex_task` 内 `except Exception: pass`；try 体首行：`ProgressTracker(kb_name, Path(base_dir)).update(`
- `deeptutor/api/routers/knowledge.py:4353` — `websocket_progress` 内 `except Exception: pass`；try 体首行：`age = (datetime.now() - datetime.fromisoformat(ts)).total_seconds()`
- `deeptutor/api/routers/knowledge.py:4402` — `websocket_progress` 内 `except Exception: pass`；try 体首行：`progress_time = datetime.fromisoformat(timestamp)`
- `deeptutor/api/routers/knowledge.py:4480` — `websocket_progress` 内 `except Exception: pass`；try 体首行：`await websocket.send_json({"type": "error", "message": str(e)})`
- `deeptutor/api/routers/knowledge.py:4486` — `websocket_progress` 内 `except Exception: pass`；try 体首行：`await websocket.close()`
- `deeptutor/api/routers/knowledge.py:4491` — `websocket_progress` 内 `except Exception: pass`；try 体首行：`reset_current_user(user_token)`
- `deeptutor/api/routers/question.py:131` — `write` 内 `except Exception: pass`；try 体首行：`self.original_stdout.write(message)`
- `deeptutor/api/routers/question.py:323` — `websocket_mimic_generate` 内 `except Exception: pass`；try 体首行：`await websocket.send_json({"type": "error", "content": error_msg})`
- `deeptutor/knowledge/manager.py:567` — `update_kb_status` 内 `except Exception: pass`；try 体首行：`from deeptutor.services.rag.embedding_binding import entry_signature`
- `deeptutor/knowledge/manager.py:2130` — `update_folder_sync_state` 内 `except Exception: pass`；try 体首行：`if source_mtimes is not None:`
- `deeptutor/runtime/launcher.py:1252` — `_handoff_pending_update` 内 `except Exception: pass`；try 体首行：`store.mark_failed(job.id, f"Launcher handoff failed: {exc}")`
- `deeptutor/runtime/update_worker.py:144` — `run_update_worker` 内 `except Exception: pass`；try 体首行：`current = store.load()`
- `deeptutor/services/embedding/client.py:204` — `embed` 内 `except Exception: pass`；try 体首行：`progress_callback(i + 1, total_batches)`
- `deeptutor/services/embedding/client.py:279` — `embed_contents` 内 `except Exception: pass`；try 体首行：`progress_callback(i + 1, total_batches)`
- `deeptutor/services/memory/snapshot/adapters.py:51` — `_iso` 内 `except Exception: pass`；try 体首行：`datetime.fromisoformat(ts.replace("Z", "+00:00"))`
- `deeptutor/services/rag/pipelines/graphrag/provider.py:119` — `resolve_persisted_completion_provider` 内 `except Exception: pass`；try 体首行：`from deeptutor.services.config import (`
- `deeptutor/services/rag/pipelines/llamaindex/document_loader.py:403` — `_describe_one` 内 `except Exception: pass`；try 体首行：`image_progress_callback(completed, total)`
- `deeptutor/services/storage/file_library.py:205` — `_delete_file` 内 `except Exception: pass`；try 体首行：`for parent in target.parents:`

## 3. 与已开上游 issue 的对应关系

> 说明：上游（HKUDS/DeepTutor）当前**没有**直接追踪"TODO/吞错清理"类工作的开放 issue 或 PR（已检索 open issues ×100 与 open PRs ×100，无对应项；本卡不向上游开 PR）。以下为发现项与现有开放 issue 的**可能关联**（供人工判断，非因果结论）：

| 上游 issue | 关联发现 | 证据 |
| --- | --- | --- |
| #1612（Reliable long-document indexing：truthful progress & safe recovery） | 索引/重建进度链路上的静默吞错会直接造成"进度不真实" | `deeptutor/api/routers/knowledge.py:3952`（`run_reindex_task` 中**失败告警本身**也被 `except Exception: pass` 包裹）；`deeptutor/knowledge/progress_tracker.py:105`（进度广播静默失败）；`deeptutor/api/routers/knowledge.py:4480/4486/4491`（进度 WebSocket 收发静默失败）；`deeptutor/knowledge/manager.py:567`（`update_kb_status` 静默失败 → KB 状态可能失真） |
| #1678（Chat history search fails — existing text cannot be matched） | 搜索/召回链路的静默降级可能掩盖检索失败的真实原因 | `deeptutor/services/rag/service.py:183`（`search` 附近遥测/记忆读取静默失败）；会话存储侧多为窄类型吞错（`deeptutor/services/partners/sessions.py:260,325` 等，风险 LOW） |
| #1673 / #1688（EPUB/PDF 阅读位置） | 阅读位置持久化采用静默兜底，属**有意设计**（有注释佐证），非缺陷 | `web/components/reading/EpubDocumentView.tsx:297` 附近 `.catch` 带注释"Reading must continue when a background progress write fails"（未计入风险项） |

## 4. TODO/FIXME 清单

源代码中无 `TODO:`/`FIXME:` 注释。仅：

- deeptutor/tools/tex_downloader.py:11 — docstring 引用 `TODO.md` 规范（仓库根目录无此文件，引用已失效）
- deeptutor/tools/tex_chunker.py:11 — 同上

## 5. 风险评级标准（确定性规则，可复核）

对每个静默处理器计分：

- 异常类型：裸 `except` +4；`except Exception/BaseException` +2；具体异常类型 +0
- 处理体：`pass` 且不在循环内 +1（整段操作不可见失败）；`continue`（循环内跳过单项）+0
- 上下文命中关键动词（`save|write|persist|commit|insert|update|delete|remove|unlink|upload|exec|subprocess|progress|reindex|notify|broadcast|publish|dispatch|send_json|task_stream|replace(`，作用于函数名 + try 体首行）+2
- 上下文命中尽力而为/清理语义（`cleanup|temp|best_effort|probe|teardown|shutdown|dispose|legacy|archive|chmod|stat(|optional|fallback|decode|parse`）−2
- `tests/` 下一律 LOW

**HIGH ≥ 4 分；MEDIUM 2–3 分；LOW ≤ 1 分。** TS/JS 侧条目为人工评级（数量少，逐条给出理由）。

## 6. 复现命令

```bash
# TODO/FIXME / 裸 except / 空 catch / no-op .catch
rg -n '\b(TODO|FIXME)\b' deeptutor deeptutor_cli web scripts tests -g '!node_modules/**' -g '!*.md'
rg -n --no-heading 'except\s*:' deeptutor deeptutor_cli scripts tests --type py
rg -n --no-heading -U 'catch\s*(\([^)]*\))?\s*\{\s*\}' web -g '*.{ts,tsx,js,jsx,mjs}' -g '!node_modules/**'
rg -n '\.catch\(\(\)\s*=>\s*(\{\}|undefined|null|void 0)\)' web -g '*.{ts,tsx,js,jsx,mjs}' -g '!node_modules/**'
# Python AST 静默处理器（本报告附录 A 数据源）
python3 scan_py_swallow.py   # 见附带 py_silent_handlers.json
```

## 7. 附录 A：Python 静默异常处理器全量清单（按风险排序）

| 风险 | 位置 | 异常类型 | 处理体 | 所在函数 | try 体首行 |
| --- | --- | --- | --- | --- | --- |
| HIGH | `deeptutor/api/routers/knowledge.py:3952` | Exception | pass | `run_reindex_task` | ProgressTracker(kb_name, Path(base_dir)).update( |
| HIGH | `deeptutor/api/routers/knowledge.py:4353` | Exception | pass | `websocket_progress` | age = (datetime.now() - datetime.fromisoformat(ts)).total_seconds() |
| HIGH | `deeptutor/api/routers/knowledge.py:4402` | Exception | pass | `websocket_progress` | progress_time = datetime.fromisoformat(timestamp) |
| HIGH | `deeptutor/api/routers/knowledge.py:4480` | Exception | pass | `websocket_progress` | await websocket.send_json({"type": "error", "message": str(e)}) |
| HIGH | `deeptutor/api/routers/knowledge.py:4486` | Exception | pass | `websocket_progress` | await websocket.close() |
| HIGH | `deeptutor/api/routers/knowledge.py:4491` | Exception | pass | `websocket_progress` | reset_current_user(user_token) |
| HIGH | `deeptutor/api/routers/question.py:131` | Exception | pass | `write` | self.original_stdout.write(message) |
| HIGH | `deeptutor/api/routers/question.py:323` | Exception | pass | `websocket_mimic_generate` | await websocket.send_json({"type": "error", "content": error_msg}) |
| HIGH | `deeptutor/knowledge/manager.py:567` | Exception | pass | `update_kb_status` | from deeptutor.services.rag.embedding_binding import entry_signature |
| HIGH | `deeptutor/knowledge/manager.py:2130` | Exception | pass | `update_folder_sync_state` | if source_mtimes is not None: |
| HIGH | `deeptutor/runtime/launcher.py:1252` | Exception | pass | `_handoff_pending_update` | store.mark_failed(job.id, f"Launcher handoff failed: {exc}") |
| HIGH | `deeptutor/runtime/update_worker.py:144` | Exception | pass | `run_update_worker` | current = store.load() |
| HIGH | `deeptutor/services/embedding/client.py:204` | Exception | pass | `embed` | progress_callback(i + 1, total_batches) |
| HIGH | `deeptutor/services/embedding/client.py:279` | Exception | pass | `embed_contents` | progress_callback(i + 1, total_batches) |
| HIGH | `deeptutor/services/memory/snapshot/adapters.py:51` | Exception | pass | `_iso` | datetime.fromisoformat(ts.replace("Z", "+00:00")) |
| HIGH | `deeptutor/services/rag/pipelines/graphrag/provider.py:119` | Exception | pass | `resolve_persisted_completion_provider` | from deeptutor.services.config import ( |
| HIGH | `deeptutor/services/rag/pipelines/llamaindex/document_loader.py:403` | Exception | pass | `_describe_one` | image_progress_callback(completed, total) |
| HIGH | `deeptutor/services/storage/file_library.py:205` | Exception | pass | `_delete_file` | for parent in target.parents: |
| MEDIUM | `deeptutor/agents/base_agent.py:333` | Exception | pass | `_track_tokens` | self.token_tracker.add_usage( |
| MEDIUM | `deeptutor/agents/research/utils/citation_manager.py:186` | ValueError | pass | `_restore_counters_from_citations` | num = int(citation_id.replace("PLAN-", "")) |
| MEDIUM | `deeptutor/agents/research/utils/citation_manager.py:199` | ValueError, IndexError | pass | `_restore_counters_from_citations` | parts = citation_id.replace("CIT-", "").split("-") |
| MEDIUM | `deeptutor/api/routers/knowledge.py:530` | OSError | pass | `_save_uploaded_files` | os.unlink(file_path) |
| MEDIUM | `deeptutor/api/routers/knowledge.py:541` | OSError | pass | `_save_uploaded_files` | os.unlink(written_path) |
| MEDIUM | `deeptutor/api/routers/knowledge.py:1193` | OSError | pass | `run_upload_processing_task` | source_mtimes[source_path] = datetime.fromtimestamp( |
| MEDIUM | `deeptutor/api/routers/memory.py:703` | OSError | continue | `clear_trace` | path.unlink() |
| MEDIUM | `deeptutor/api/routers/partner_groups.py:530` | Exception | pass | `partner_group_ws` | reset_current_user(user_token) |
| MEDIUM | `deeptutor/api/routers/partners.py:546` | Exception | pass | `_load_persona_markdown` | detail = get_persona_service().get_detail(name) |
| MEDIUM | `deeptutor/api/routers/partners.py:553` | Exception | pass | `_load_persona_markdown` | admin_service = PersonaService( |
| MEDIUM | `deeptutor/api/routers/partners.py:2019` | Exception | pass | `partner_chat_ws` | reset_current_user(user_token) |
| MEDIUM | `deeptutor/api/routers/question.py:146` | ?, RuntimeError | pass | `write` | event = ProcessLogEvent( |
| MEDIUM | `deeptutor/api/routers/question.py:153` | Exception | pass | `flush` | self.original_stdout.flush() |
| MEDIUM | `deeptutor/api/routers/question.py:306` | RuntimeError, WebSocketDisconnect | pass | `websocket_mimic_generate` | await websocket.send_json({"type": "error", "content": error_msg}) |
| MEDIUM | `deeptutor/api/routers/question.py:336` | Exception | pass | `websocket_mimic_generate` | pusher_task.cancel() |
| MEDIUM | `deeptutor/api/routers/question.py:343` | Exception | pass | `websocket_mimic_generate` | while not log_queue.empty(): |
| MEDIUM | `deeptutor/api/routers/question.py:349` | Exception | pass | `websocket_mimic_generate` | await websocket.close() |
| MEDIUM | `deeptutor/api/routers/question.py:355` | Exception | pass | `websocket_mimic_generate` | reset_current_user(user_token) |
| MEDIUM | `deeptutor/api/routers/question.py:385` | RuntimeError, WebSocketDisconnect | pass | `websocket_question_generate` | await websocket.send_json({"type": "error", "content": "Requirement is required"}) |
| MEDIUM | `deeptutor/api/routers/question.py:438` | Exception | pass | `ws_callback` | await log_queue.put(data) |
| MEDIUM | `deeptutor/api/routers/question.py:505` | RuntimeError, WebSocketDisconnect | pass | `websocket_question_generate` | await websocket.send_json( |
| MEDIUM | `deeptutor/api/routers/question.py:577` | Exception | pass | `websocket_question_generate` | reset_current_user(user_token) |
| MEDIUM | `deeptutor/api/routers/quiz_judge.py:284` | Exception | pass | `websocket_quiz_judge` | await websocket.close() |
| MEDIUM | `deeptutor/api/routers/quiz_judge.py:289` | Exception | pass | `websocket_quiz_judge` | reset_current_user(user_token) |
| MEDIUM | `deeptutor/api/routers/quiz_judge.py:298` | Exception | pass | `websocket_quiz_judge` | await websocket.close() |
| MEDIUM | `deeptutor/api/routers/quiz_judge.py:303` | Exception | pass | `websocket_quiz_judge` | reset_current_user(user_token) |
| MEDIUM | `deeptutor/api/routers/quiz_judge.py:390` | Exception | pass | `websocket_quiz_judge` | await websocket.close() |
| MEDIUM | `deeptutor/api/routers/quiz_judge.py:395` | Exception | pass | `websocket_quiz_judge` | reset_current_user(user_token) |
| MEDIUM | `deeptutor/api/routers/quiz_judge.py:454` | Exception | pass | `websocket_quiz_judge` | await websocket.close() |
| MEDIUM | `deeptutor/api/routers/quiz_judge.py:459` | Exception | pass | `websocket_quiz_judge` | reset_current_user(user_token) |
| MEDIUM | `deeptutor/api/routers/reading.py:518` | Exception | continue | `duplicate_check` | material_id = url_material_id(url) |
| MEDIUM | `deeptutor/api/routers/settings.py:518` | Exception | pass | `load_ui_settings` | with open(settings_file, encoding="utf-8") as handle: |
| MEDIUM | `deeptutor/api/routers/settings.py:2247` | Exception | pass | `tour_status` | cache = json.loads(tour_cache.read_text(encoding="utf-8")) |
| MEDIUM | `deeptutor/api/routers/workspace.py:322` | WorkspaceError | continue | `_resolve_partner_item` | return get_content_workspace_service().resolve_published_item( |
| MEDIUM | `deeptutor/api/utils/tool_options.py:97` | Exception | continue | `build_tool_options` | definition = tool.get_definition() |
| MEDIUM | `deeptutor/capabilities/course_study/capability.py:291` | Exception | continue | `_durable_reading_position` | workspace = catalog.get_workspace(workspace_id) |
| MEDIUM | `deeptutor/capabilities/setup/apply.py:115` | Exception | continue | `_neighbour_values` | out[other.key] = (other.label, other.read()) |
| MEDIUM | `deeptutor/capabilities/setup/binding.py:135` | Exception | pass | `setup_gaps` | parsing = specs.get("document_parsing.engine") |
| MEDIUM | `deeptutor/capabilities/setup/binding.py:207` | Exception | pass | `mark_intro_shown` | from deeptutor.services.settings.interface_settings import set_ui_setting |
| MEDIUM | `deeptutor/co_writer/docx_converter.py:256` | Exception | pass | `_style_name` | if paragraph.style is not None and paragraph.style.name: |
| MEDIUM | `deeptutor/co_writer/docx_converter.py:340` | Exception | pass | `_run_to_markdown` | if run.font.strike: |
| MEDIUM | `deeptutor/co_writer/docx_converter.py:356` | Exception | continue | `_table_to_markdown` | cells = [_cell_text(cell) for cell in row.cells] |
| MEDIUM | `deeptutor/knowledge/manager.py:214` | ValueError | pass | `_reconcile_embedding_flags` | published = bound_graph_storage_root(kb_dir, provider, published) |
| MEDIUM | `deeptutor/knowledge/manager.py:1295` | Exception | pass | `get_default` | from deeptutor.services.config import get_kb_config_service |
| MEDIUM | `deeptutor/knowledge/manager.py:1616` | Exception | pass | `get_info` | raw_count = sum(1 for _ in iter_kb_documents(raw_dir)) if raw_dir else 0 |
| MEDIUM | `deeptutor/knowledge/manager.py:1623` | Exception | pass | `get_info` | images_count = ( |
| MEDIUM | `deeptutor/knowledge/manager.py:1630` | Exception | pass | `get_info` | content_lists_count = ( |
| MEDIUM | `deeptutor/knowledge/progress_tracker.py:103` | RuntimeError | pass | `_notify` | loop = asyncio.get_running_loop() |
| MEDIUM | `deeptutor/knowledge/progress_tracker.py:105` | ImportError, Exception | pass | `_notify` | from deeptutor.knowledge.progress_events import broadcast_progress |
| MEDIUM | `deeptutor/partners/channels/email.py:377` | Exception | pass | `_fetch_messages` | client.logout() |
| MEDIUM | `deeptutor/partners/channels/manager.py:294` | TimeoutError | continue | `_dispatch_outbound` | if pending: |
| MEDIUM | `deeptutor/partners/channels/matrix.py:529` | Exception | pass | `_set_typing` | response = await self.client.room_typing( |
| MEDIUM | `deeptutor/partners/channels/mochat.py:360` | Exception | pass | `stop` | await self._socket.disconnect() |
| MEDIUM | `deeptutor/partners/channels/mochat.py:512` | Exception | pass | `_start_socket_client` | await client.disconnect() |
| MEDIUM | `deeptutor/partners/channels/napcat.py:172` | Exception | pass | `stop` | await self._ws.close() |
| MEDIUM | `deeptutor/partners/channels/napcat.py:178` | Exception | pass | `stop` | await self._http.close() |
| MEDIUM | `deeptutor/partners/channels/napcat.py:219` | TypeError, ValueError | pass | `_dispatch_frame` | self._self_id = int(sid) |
| MEDIUM | `deeptutor/partners/channels/qq.py:134` | Exception | pass | `stop` | await self._client.close() |
| MEDIUM | `deeptutor/partners/channels/telegram.py:519` | Exception | pass | `_send_with_streaming` | step = max(len(text) // 8, 40) |
| MEDIUM | `deeptutor/partners/channels/zulip.py:173` | Exception | pass | `stop` | self._client.deregister(self._queue_id) |
| MEDIUM | `deeptutor/partners/channels/zulip.py:858` | Exception | pass | `_typing_loop` | self._client.set_typing_status( |
| MEDIUM | `deeptutor/reading/references.py:118` | Exception | continue | `resolve_reading_sources` | current_manifest = active_store.manifest(material_id) |
| MEDIUM | `deeptutor/reading/references.py:135` | Exception | continue | `resolve_reading_sources` | body = read_unit(material_id, locator).strip() |
| MEDIUM | `deeptutor/reading/store.py:1145` | OSError | pass | `delete_material_state` | (content_dir / state_dir).rmdir() |
| MEDIUM | `deeptutor/runtime/launcher.py:146` | Exception | pass | `_reset_runtime_singletons` | from deeptutor.services.path_service import PathService |
| MEDIUM | `deeptutor/runtime/launcher.py:152` | Exception | pass | `_reset_runtime_singletons` | from deeptutor.services.config.runtime_settings import RuntimeSettingsService |
| MEDIUM | `deeptutor/runtime/launcher.py:158` | Exception | pass | `_reset_runtime_singletons` | from deeptutor.services.config.model_catalog import ModelCatalogService |
| MEDIUM | `deeptutor/runtime/launcher.py:260` | Exception | pass | `_terminate` | _send_tree_signal(proc.process.pid, proc.pgid, signal.SIGTERM) |
| MEDIUM | `deeptutor/runtime/launcher.py:267` | Exception | pass | `_terminate` | _send_tree_signal(proc.process.pid, proc.pgid, KILL_SIGNAL) |
| MEDIUM | `deeptutor/runtime/launcher.py:502` | Exception | pass | `_kill_port_listeners` | _send_tree_signal(pid, None, signal.SIGTERM) |
| MEDIUM | `deeptutor/runtime/launcher.py:511` | Exception | pass | `_kill_port_listeners` | _send_tree_signal(pid, None, KILL_SIGNAL) |
| MEDIUM | `deeptutor/runtime/launcher.py:638` | Exception | pass | `_copy_packaged_web_if_needed` | if json.loads(marker.read_text(encoding="utf-8")) == marker_payload: |
| MEDIUM | `deeptutor/runtime/launcher.py:787` | Exception | pass | `_ensure_source_production_build` | if json.loads(marker.read_text(encoding="utf-8")) == payload: |
| MEDIUM | `deeptutor/runtime/launcher.py:943` | Exception | continue | `_detect_existing_source_frontend` | payload = json.loads(lock_path.read_text(encoding="utf-8")) |
| MEDIUM | `deeptutor/runtime/launcher.py:997` | OSError | pass | `_stop_unhealthy_source_frontend` | frontend.lock_path.unlink(missing_ok=True) |
| MEDIUM | `deeptutor/runtime/launcher.py:1022` | OSError | pass | `_stop_unhealthy_source_frontend` | frontend.lock_path.unlink(missing_ok=True) |
| MEDIUM | `deeptutor/runtime/memory_probe.py:304` | Exception | pass | `_host_memory` | vm = psutil.virtual_memory() |
| MEDIUM | `deeptutor/services/codebuddy_auth.py:79` | Exception | pass | `cancel_login` | await flow.cancel() |
| MEDIUM | `deeptutor/services/codebuddy_auth.py:99` | Exception | pass | `logout` | await flow.cancel() |
| MEDIUM | `deeptutor/services/codex_auth/service.py:872` | Exception | pass | `logout` | await self._oauth.revoke(credentials) |
| MEDIUM | `deeptutor/services/codex_auth/service.py:882` | Exception | pass | `logout` | await self._catalog.invalidate() |
| MEDIUM | `deeptutor/services/config/model_catalog.py:642` | Exception | pass | `get_model_catalog_service` | from deeptutor.multi_user.context import get_current_user |
| MEDIUM | `deeptutor/services/config/readiness.py:872` | Exception | pass | `_redis_reachable` | await asyncio.wait_for(coordinator.close(), timeout=1.0) |
| MEDIUM | `deeptutor/services/config/settings_spec.py:471` | Exception | pass | `_clear_runtime_caches` | from deeptutor.services.llm import clear_llm_config_cache |
| MEDIUM | `deeptutor/services/embedding/adapters/openai_sdk.py:113` | Exception | pass | `embed` | await client.close() |
| MEDIUM | `deeptutor/services/embedding/client.py:223` | Exception | pass | `supports_multimodal_contents` | info = self.adapter.get_model_info() |
| MEDIUM | `deeptutor/services/file_io.py:55` | OSError | pass | `atomic_write_json` | os.fsync(handle.fileno()) |
| MEDIUM | `deeptutor/services/file_io.py:80` | OSError | pass | `atomic_write_text` | os.fsync(handle.fileno()) |
| MEDIUM | `deeptutor/services/llm/provider_core/codebuddy_provider.py:115` | BaseException | pass | `_owner_loop` | await client.disconnect() |
| MEDIUM | `deeptutor/services/llm/provider_core/codebuddy_provider.py:144` | Exception | pass | `close` | await owner |
| MEDIUM | `deeptutor/services/llm/provider_core/codebuddy_provider.py:363` | Exception | pass | `aclose` | await session.close() |
| MEDIUM | `deeptutor/services/llm/provider_core/codebuddy_provider.py:553` | Exception | pass | `_consume_messages` | await interrupt() |
| MEDIUM | `deeptutor/services/memory/consolidator/meta.py:177` | OSError | pass | `_atomic_write_json` | os.remove(tmp_str) |
| MEDIUM | `deeptutor/services/memory/consolidator/runs.py:256` | ValueError | pass | `wait_for_events` | run._waiters.remove(waiter) |
| MEDIUM | `deeptutor/services/memory/snapshot/adapters.py:56` | Exception | pass | `_iso` | return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat() |
| MEDIUM | `deeptutor/services/memory/snapshot/adapters.py:138` | OSError, ? | continue | `read_cowriter_entities` | m = json.loads(manifest.read_text(encoding="utf-8")) |
| MEDIUM | `deeptutor/services/memory/snapshot/store.py:112` | OSError | pass | `clear_changes` | path.unlink() |
| MEDIUM | `deeptutor/services/notebook/service.py:153` | Exception | continue | `_rebuild_index_entries` | with open(path, encoding="utf-8") as f: |
| MEDIUM | `deeptutor/services/parsing/engines/markitdown/formats.py:76` | Exception | continue | `markitdown_supported_formats` | module = importlib.import_module(module_info.name) |
| MEDIUM | `deeptutor/services/parsing/engines/markitdown/formats.py:82` | Exception | pass | `markitdown_supported_formats` | converters = importlib.import_module("markitdown.converters") |
| MEDIUM | `deeptutor/services/parsing/engines/mineru/local.py:36` | FileNotFoundError | pass | `check_mineru_installed` | result = subprocess.run( |
| MEDIUM | `deeptutor/services/parsing/engines/mineru/local.py:50` | FileNotFoundError | pass | `check_mineru_installed` | result = subprocess.run( |
| MEDIUM | `deeptutor/services/parsing/engines/mineru/readiness.py:74` | Exception | continue | `mineru_models_ready` | if not root.is_dir(): |
| MEDIUM | `deeptutor/services/partners/workspace.py:432` | OSError, ? | pass | `remove_asset` | data = json.loads(index_path.read_text(encoding="utf-8")) |
| MEDIUM | `deeptutor/services/rag/pipelines/lightrag/cache_reuse.py:100` | ValueError | continue | `inherit_index_cache` | version = int(root.name.removeprefix("version-")) |
| MEDIUM | `deeptutor/services/rag/pipelines/lightrag/worker.py:250` | BaseException | pass | `run_in_worker_loop` | worker.result() |
| MEDIUM | `deeptutor/services/rag/pipelines/modes.py:37` | Exception | pass | `resolve_kb_mode` | cfg_path = Path(kb_base_dir) / "kb_config.json" |
| MEDIUM | `deeptutor/services/rag/service.py:183` | Exception | pass | `search` | from deeptutor.services.memory import get_memory_store |
| MEDIUM | `deeptutor/services/session/pocketbase_store.py:99` | ValueError | pass | `_to_float` | return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() |
| MEDIUM | `deeptutor/services/session/sqlite_store.py:454` | OperationalError | pass | `_initialize` | conn.execute("ALTER TABLE sessions DROP COLUMN kind") |
| MEDIUM | `deeptutor/services/session/turns/lifecycle.py:321` | CancelledError | pass | `cancel_turn` | await execution.task |
| MEDIUM | `deeptutor/services/storage/attachment_store.py:184` | OSError | pass | `_write_sync` | tmp.unlink() |
| MEDIUM | `deeptutor/services/storage/file_library.py:188` | OSError | pass | `_write_file` | tmp.unlink() |
| MEDIUM | `deeptutor/services/subagent/claude_models.py:215` | OSError | pass | `_capture_model_screen` | os.write(fd, keys) |
| MEDIUM | `deeptutor/services/subagent/opencode_family.py:410` | Exception | pass | `_swallow` | await awaitable |
| MEDIUM | `deeptutor/tools/builtin/__init__.py:1711` | SkillNotFoundError | continue | `execute` | content = service.read_skill_file(name, rel_path) |
| MEDIUM | `deeptutor/utils/config_manager.py:96` | OSError | pass | `save_config` | os.remove(tmp_path) |
| MEDIUM | `deeptutor/utils/document_images.py:557` | Exception | continue | `extract_pdf_images` | extracted = doc.extract_image(xref) |
| MEDIUM | `deeptutor_cli/init_cmd.py:35` | Exception | pass | `_reset_runtime_singletons` | from deeptutor.services.path_service import PathService |
| MEDIUM | `deeptutor_cli/init_cmd.py:41` | Exception | pass | `_reset_runtime_singletons` | from deeptutor.services.config.runtime_settings import RuntimeSettingsService |
| MEDIUM | `deeptutor_cli/init_cmd.py:47` | Exception | pass | `_reset_runtime_singletons` | from deeptutor.services.config.model_catalog import ModelCatalogService |
| MEDIUM | `deeptutor_cli/provider_cmd.py:150` | Exception | pass | `_login_codebuddy` | webbrowser.open(auth.auth_url) |
| MEDIUM | `deeptutor_cli/skill_login.py:123` | Exception | pass | `run_login` | webbrowser.open(url) |
| MEDIUM | `scripts/_cli_kit.py:10` | Exception | pass | `_ensure_replace_errors` | if getattr(sys.stdout, "errors", None) != "replace": |
| LOW | `deeptutor/agents/_shared/json_output.py:27` | JSONDecodeError | pass | `extract_json_object` | parsed = json.loads(raw) |
| LOW | `deeptutor/agents/_shared/json_output.py:69` | JSONDecodeError | continue | `_decode_first_json_object` | parsed, _end = decoder.raw_decode(stripped[start:]) |
| LOW | `deeptutor/agents/loop/dsml_tool_calls.py:189` | TypeError, ValueError | pass | `_coerce_param_value` | parsed = json.loads(stripped) |
| LOW | `deeptutor/agents/math_animator/duration_utils.py:27` | TypeError, ValueError | continue | `parse_target_duration_seconds` | candidates.append(float(match.group("value"))) |
| LOW | `deeptutor/agents/math_animator/duration_utils.py:32` | TypeError, ValueError | continue | `parse_target_duration_seconds` | candidates.append(float(match.group("value")) * 60.0) |
| LOW | `deeptutor/agents/question/pipeline.py:228` | TypeError, ValueError | continue | `_normalize_per_type_counts` | count = int(value) |
| LOW | `deeptutor/agents/question/pipeline.py:288` | TypeError, ValueError | continue | `_normalize_per_type_counts` | count = int(value) |
| LOW | `deeptutor/agents/research/data_structures.py:126` | TypeError, ValueError | pass | `_truncate_raw_answer` | truncated = json.dumps(data, ensure_ascii=False) |
| LOW | `deeptutor/agents/research/data_structures.py:538` | ValueError, IndexError | pass | `from_dict` | block_num = int(block.block_id.split("_")[1]) |
| LOW | `deeptutor/agents/research/pipeline.py:2608` | IndexError, ValueError | pass | `_citation_sort_key` | if citation_id.startswith("PLAN-"): |
| LOW | `deeptutor/agents/research/utils/citation_manager.py:433` | ?, Exception | pass | `_extract_web_citation` | answer_data = parse_json_response(raw_answer) |
| LOW | `deeptutor/agents/research/utils/citation_manager.py:754` | ValueError, IndexError | pass | `_extract_citation_sort_key` | if citation_id.startswith("PLAN-"): |
| LOW | `deeptutor/agents/research/utils/json_utils.py:30` | JSONDecodeError | pass | `extract_json_from_text` | return json.loads(snippet) |
| LOW | `deeptutor/agents/research/utils/json_utils.py:36` | JSONDecodeError | pass | `extract_json_from_text` | return json.loads(text) |
| LOW | `deeptutor/agents/research/utils/json_utils.py:46` | JSONDecodeError | continue | `extract_json_from_text` | parsed, _end = decoder.raw_decode(text[i:]) |
| LOW | `deeptutor/api/routers/auth.py:121` | ValueError | continue | `_trusted_proxy_ips` | trusted.add(str(ipaddress.ip_address(item.strip()))) |
| LOW | `deeptutor/api/routers/book.py:386` | ValueError | continue | `_normalize_block_types` | block_type = BlockType(value.strip().lower()) |
| LOW | `deeptutor/api/routers/book.py:1514` | ?, Exception | pass | `close` | await task |
| LOW | `deeptutor/api/routers/book.py:1812` | WebSocketDisconnect | pass | `book_websocket` | while not closed: |
| LOW | `deeptutor/api/routers/knowledge.py:3048` | OSError | continue | `list_kb_raw_files` | stat = entry.stat() |
| LOW | `deeptutor/api/routers/memory.py:116` | Exception | continue | `resolve_entry` | doc = parse(path.read_text(encoding="utf-8")) |
| LOW | `deeptutor/api/routers/multi_user.py:172` | ValueError | continue | `_admin_catalog_summary` | effective = resolve_profile_provider(catalog, service, profile, model) |
| LOW | `deeptutor/api/routers/partners.py:1735` | TimeoutError | continue | `_partner_chat_stream` | item = await asyncio.wait_for(queue.get(), timeout=0.15) |
| LOW | `deeptutor/api/routers/personas.py:91` | PersonaNotFoundError | pass | `get_persona` | return service.get_detail(name).to_dict() |
| LOW | `deeptutor/api/routers/personas.py:102` | PersonaNotFoundError, InvalidPersonaNameError | pass | `get_persona` | detail = presets.get_detail(name).to_dict() |
| LOW | `deeptutor/api/routers/question.py:334` | CancelledError | pass | `websocket_mimic_generate` | pusher_task.cancel() |
| LOW | `deeptutor/api/routers/question.py:564` | CancelledError | pass | `websocket_question_generate` | await pusher_task |
| LOW | `deeptutor/api/routers/settings.py:1187` | Exception | continue | `_document_parsing_payload` | parser = get_parser(entry["id"]) |
| LOW | `deeptutor/api/routers/settings.py:2336` | WorkspaceError | continue | `get_usage_statistics` | with workspace_context(workspace_id): |
| LOW | `deeptutor/api/routers/skills.py:205` | SkillNotFoundError | pass | `get_skill` | return service.get_detail(name).to_dict() |
| LOW | `deeptutor/api/routers/unified_ws.py:137` | CancelledError | pass | `stop_subscription` | await task |
| LOW | `deeptutor/api/utils/task_log_stream.py:80` | RuntimeError | continue | `emit` | loop.call_soon_threadsafe(self._queue_event, queue, event_payload) |
| LOW | `deeptutor/api/utils/task_log_stream.py:279` | QueueFull | pass | `_queue_event` | queue.put_nowait(payload) |
| LOW | `deeptutor/app/container.py:156` | WorkspaceError | continue | `recover_once` | activity = acquire_activity() |
| LOW | `deeptutor/app/container.py:186` | WorkspaceError | continue | `_recover_user_workspaces` | with workspace_context(workspace_id): |
| LOW | `deeptutor/book/agents/page_planner.py:363` | ValueError | continue | `plan_blocks_async` | block_type = BlockType(type_str) |
| LOW | `deeptutor/book/blocks/_llm_writer.py:120` | ?, ValueError | pass | `_strip_thinking_preamble` | json.loads(candidate) |
| LOW | `deeptutor/book/blocks/_rag_helpers.py:103` | Exception | pass | `optional_rag_lookup` | from deeptutor.multi_user.knowledge_access import resolve_kb |
| LOW | `deeptutor/book/compiler.py:65` | ValueError | continue | `_parse_allowed_block_types` | parsed.add(BlockType(value.strip().lower())) |
| LOW | `deeptutor/capabilities/obsidian/vault.py:183` | OSError | continue | `search_notes` | text = _read_text(path) |
| LOW | `deeptutor/capabilities/obsidian/vault.py:228` | OSError | continue | `backlinks` | text = _read_text(path) |
| LOW | `deeptutor/capabilities/obsidian/vault.py:249` | OSError | continue | `collect_tags` | text = _read_text(path) |
| LOW | `deeptutor/capabilities/reading/media_notes.py:61` | TypeError, ValueError | continue | `render_media_note` | locator = int(row.get("locator") or 0) |
| LOW | `deeptutor/capabilities/subagent/capability.py:178` | TypeError, ValueError | pass | `_resolve_budget` | return max(CONSULT_BUDGET_MIN, min(CONSULT_BUDGET_MAX, int(raw))) |
| LOW | `deeptutor/co_writer/docx_converter.py:541` | KeyError, ValueError | pass | `_append_markdown_table` | table.style = "Table Grid" |
| LOW | `deeptutor/events/event_bus.py:113` | TimeoutError | continue | `_process_events` | event = await asyncio.wait_for(self._task_queue.get(), timeout=1.0) |
| LOW | `deeptutor/events/event_bus.py:182` | CancelledError | pass | `stop` | await self._processor_task |
| LOW | `deeptutor/learning/storage.py:784` | OSError | pass | `_archive_legacy` | path.replace(target) |
| LOW | `deeptutor/learning/storage.py:1825` | ValueError | pass | `detach_session` | self._import_legacy_if_needed(session_id) |
| LOW | `deeptutor/multi_user/model_access.py:101` | ValueError | continue | `redacted_model_access` | effective = resolve_profile_provider(catalog, "llm", profile, model) |
| LOW | `deeptutor/multi_user/session_handoff.py:226` | FileNotFoundError | pass | `_initialize` | os.chmod(self.db_path, 0o600) |
| LOW | `deeptutor/partners/channels/matrix.py:293` | CancelledError | pass | `stop` | await self._sync_task |
| LOW | `deeptutor/partners/channels/matrix.py:544` | CancelledError | pass | `loop` | while self._running: |
| LOW | `deeptutor/partners/channels/matrix.py:554` | CancelledError | pass | `_stop_typing_keepalive` | await task |
| LOW | `deeptutor/partners/channels/mattermost.py:323` | JSONDecodeError | pass | `_should_respond_in_channel` | if self._bot_user_id in json.loads(mentions): |
| LOW | `deeptutor/partners/channels/napcat.py:148` | JSONDecodeError | continue | `_run_once` | payload = json.loads(raw) |
| LOW | `deeptutor/partners/channels/napcat.py:236` | CancelledError | pass | `_done` | done.result() |
| LOW | `deeptutor/partners/channels/napcat.py:360` | TypeError, ValueError | pass | `_parse_segments` | reply_to = int(rid) if rid is not None else None |
| LOW | `deeptutor/partners/channels/napcat.py:550` | TypeError, KeyError | pass | `_download_image` | declared_size = int(info["file_size"]) |
| LOW | `deeptutor/partners/channels/registry.py:86` | NotAChannelModule | continue | `discover_all_with_errors` | builtin[modname] = load_channel_class(modname) |
| LOW | `deeptutor/partners/channels/telegram.py:1030` | CancelledError | pass | `_typing_loop` | while self._app: |
| LOW | `deeptutor/partners/channels/weixin.py:372` | TimeoutException | continue | `start` | await self._poll_once() |
| LOW | `deeptutor/partners/channels/zulip.py:847` | CancelledError | pass | `_typing_loop` | while self._running and self._client: |
| LOW | `deeptutor/partners/network.py:92` | ValueError | continue | `validate_url_target` | addr = ipaddress.ip_address(info[4][0]) |
| LOW | `deeptutor/reading/epub_bilingual.py:99` | ReadingError | continue | `recommend_epub_candidates` | candidate_path = _raw_epub( |
| LOW | `deeptutor/reading/extract.py:301` | TypeError, ValueError | continue | `_pdf_outline` | level, title, page = int(row[0]), str(row[1]).strip(), int(row[2]) |
| LOW | `deeptutor/reading/ingestion.py:762` | TypeError, ValueError | continue | `normalize_transcript_segments` | start_value = max(0.0, float(start or 0)) |
| LOW | `deeptutor/reading/ingestion.py:1053` | ValueError | continue | `_segment_list_spans` | start, end = float(parts[-2]), float(parts[-1]) |
| LOW | `deeptutor/reading/models.py:336` | TypeError, ValueError | continue | `parse_text_selectors` | start = max(0, int(raw.get("start") or 0)) |
| LOW | `deeptutor/reading/service.py:96` | TypeError, ValueError | continue | `parse_locators` | raw.append(int(value)) |
| LOW | `deeptutor/reading/store.py:930` | KeyError, TypeError, ValueError | continue | `outline` | entries.append( |
| LOW | `deeptutor/runtime/background_leader.py:102` | TimeoutError | pass | `_run` | await asyncio.wait_for( |
| LOW | `deeptutor/runtime/launcher.py:288` | ValueError, OSError | continue | `_relax_console_encoding` | reconfigure(errors="replace") |
| LOW | `deeptutor/runtime/launcher.py:358` | ValueError | continue | `_port_listeners` | pid = int(line[1:]) |
| LOW | `deeptutor/runtime/launcher.py:389` | ValueError | continue | `_port_listeners_windows` | pid = int(parts[4]) |
| LOW | `deeptutor/runtime/launcher.py:671` | UnicodeDecodeError | continue | `_patch_packaged_web_placeholders` | text = path.read_text(encoding="utf-8") |
| LOW | `deeptutor/runtime/launcher.py:1042` | OSError, ValueError | pass | `_install_signal_handlers` | signal.signal(signal.SIGINT, signal.SIG_IGN) |
| LOW | `deeptutor/runtime/launcher.py:1061` | OSError, ValueError | continue | `_install_signal_handlers` | signal.signal(sig, _handler) |
| LOW | `deeptutor/runtime/memory_probe.py:173` | ?, PermissionError, OSError | continue | `_scan_psutil` | with proc.oneshot(): |
| LOW | `deeptutor/runtime/stream_bus.py:119` | RuntimeError | continue | `mark_closed` | if loop.is_running(): |
| LOW | `deeptutor/services/base_sync.py:87` | CancelledError | pass | `stop` | await self._task |
| LOW | `deeptutor/services/cli_apps/paths.py:100` | OSError | pass | `ensure_root` | os.chmod(path, 0o700) |
| LOW | `deeptutor/services/cli_apps/provider.py:405` | OSError | continue | `_read_guide` | candidates = sorted(root.glob(pattern)) |
| LOW | `deeptutor/services/cli_apps/provider.py:410` | OSError, UnicodeDecodeError | continue | `_read_guide` | return sanitize_provider_document(candidate.read_text(encoding="utf-8")) |
| LOW | `deeptutor/services/codebuddy_credentials.py:206` | OSError, ValueError | continue | `_iter_cached_product_configs` | raw = json.loads(path.read_text(encoding="utf-8", errors="ignore")) |
| LOW | `deeptutor/services/codebuddy_credentials.py:212` | Exception | continue | `_iter_cached_product_configs` | decoded = json.loads(gzip.decompress(base64.b64decode(raw)).decode("utf-8")) |
| LOW | `deeptutor/services/codex_auth/service.py:1113` | CodexAuthError | continue | `_credentials_from_payload` | claims = decode_codex_jwt(token) |
| LOW | `deeptutor/services/config/provider_runtime.py:1353` | TypeError, ValueError | pass | `_resolve_search_max_results` | value = int(raw) |
| LOW | `deeptutor/services/config/provider_runtime.py:1367` | TypeError, ValueError | pass | `_resolve_search_max_results` | value = int(raw) |
| LOW | `deeptutor/services/config/test_runner.py:202` | TypeError, ValueError | continue | `_capabilities_from_adapter` | supported.append(int(value)) |
| LOW | `deeptutor/services/cron/service.py:327` | CancelledError | pass | `stop` | await self._timer_task |
| LOW | `deeptutor/services/cron/service.py:343` | TimeoutError | pass | `_loop` | await asyncio.wait_for(self._wake.wait(), timeout=sleep_s) |
| LOW | `deeptutor/services/embedding/adapters/ollama.py:84` | HTTPError | pass | `embed` | health_check = await client.get(self._tags_url()) |
| LOW | `deeptutor/services/llm/client.py:244` | ImportError | pass | `reset_llm_client` | from deeptutor.runtime.agentic.client import reset_agentic_client_pool |
| LOW | `deeptutor/services/llm/provider_core/base.py:223` | TypeError, ValueError | continue | `_normalize_retry_delays` | value = float(delay) |
| LOW | `deeptutor/services/llm/provider_core/codebuddy_provider.py:438` | TypeError | continue | `_build_options` | return options_cls(**kwargs) |
| LOW | `deeptutor/services/llm/provider_core/openai_responses/parsing.py:239` | Exception | pass | `_parse_tool_arguments` | return _as_arguments_dict( |
| LOW | `deeptutor/services/llm/utils.py:96` | ValueError | pass | `is_local_llm_server` | ip = ipaddress.ip_address(hostname) |
| LOW | `deeptutor/services/mcp/network.py:96` | ValueError | continue | `validate_mcp_url` | addr = ipaddress.ip_address(info[4][0]) |
| LOW | `deeptutor/services/memory/consolidator/line_doc.py:392` | TypeError, ValueError | continue | `parse_edits_payload` | if kind == "replace": |
| LOW | `deeptutor/services/memory/consolidator/modes/audit.py:477` | Exception | continue | `_build_l2_entry_lookup` | doc = parse(path.read_text(encoding="utf-8")) |
| LOW | `deeptutor/services/memory/consolidator/modes/merge.py:180` | Exception | continue | `_migrate_l3_legacy_refs` | l2_doc = parse(l2_path.read_text(encoding="utf-8")) |
| LOW | `deeptutor/services/memory/consolidator/modes/update.py:692` | Exception | continue | `_load_all_l2_docs` | docs[surface] = parse(path.read_text(encoding="utf-8")) |
| LOW | `deeptutor/services/memory/snapshot/adapters.py:87` | OSError, ? | continue | `read_notebook_entities` | nb_data = json.loads(nb_file.read_text(encoding="utf-8")) |
| LOW | `deeptutor/services/memory/snapshot/adapters.py:171` | OSError, ? | continue | `read_book_entities` | m = json.loads(manifest_path.read_text(encoding="utf-8")) |
| LOW | `deeptutor/services/memory/snapshot/adapters.py:257` | JSONDecodeError | continue | `_partner_session_entity` | obj = json.loads(raw) |
| LOW | `deeptutor/services/memory/snapshot/store.py:95` | JSONDecodeError | continue | `iter_changes` | obj = json.loads(raw) |
| LOW | `deeptutor/services/memory/store.py:414` | OSError, ? | continue | `migrate_partner_surface_if_needed` | data = json.loads(meta_path.read_text(encoding="utf-8")) |
| LOW | `deeptutor/services/memory/trace.py:106` | JSONDecodeError | continue | `iter_since` | obj = json.loads(raw) |
| LOW | `deeptutor/services/memory/trace.py:111` | OSError | continue | `iter_since` | with path.open("r", encoding="utf-8") as fh: |
| LOW | `deeptutor/services/memory/trace.py:151` | OSError, ? | continue | `latest_ts` | last = "" |
| LOW | `deeptutor/services/notebook/service.py:676` | NotebookCorruptedError | continue | `get_statistics` | notebook = self._load_notebook(nb_info["id"]) |
| LOW | `deeptutor/services/office_preview.py:98` | OSError | pass | `_render_sync` | if 0 < cached.stat().st_size <= MAX_PREVIEW_PDF_BYTES: |
| LOW | `deeptutor/services/office_preview.py:142` | OSError | pass | `_render_sync` | process.kill() |
| LOW | `deeptutor/services/office_preview.py:166` | OSError | pass | `_render_sync` | with tempfile.NamedTemporaryFile( |
| LOW | `deeptutor/services/office_preview.py:196` | OSError | pass | `_prune_cache` | files = [entry for entry in cache_dir.iterdir() if entry.suffix == ".pdf"] |
| LOW | `deeptutor/services/parsing/service.py:66` | Exception | continue | `_find_fallback_engine` | parser = get_parser(name) |
| LOW | `deeptutor/services/partner_groups/memory.py:153` | JSONDecodeError | continue | `_entries_unlocked` | row = json.loads(line) |
| LOW | `deeptutor/services/partner_groups/store.py:292` | TypeError, ValueError, ? | continue | `_read_messages` | data = json.loads(line) |
| LOW | `deeptutor/services/partners/manager.py:824` | ?, ? | pass | `stop_partner` | await asyncio.wait_for(asyncio.shield(task), timeout=5.0) |
| LOW | `deeptutor/services/partners/manager.py:930` | ?, ? | pass | `_teardown_channel_listeners` | await asyncio.wait_for(asyncio.shield(t), timeout=5.0) |
| LOW | `deeptutor/services/partners/sessions.py:260` | JSONDecodeError | continue | `_read_records` | data = json.loads(line) |
| LOW | `deeptutor/services/partners/sessions.py:325` | JSONDecodeError | continue | `messages_page` | record = json.loads(line) |
| LOW | `deeptutor/services/partners/workspace.py:317` | OSError, ? | pass | `_merge_index_entry` | loaded = json.loads(index_path.read_text(encoding="utf-8")) |
| LOW | `deeptutor/services/partners/workspace.py:369` | OSError, ? | pass | `list_assets` | data = json.loads(index_path.read_text(encoding="utf-8")) |
| LOW | `deeptutor/services/persona/service.py:169` | OSError | continue | `list_personas` | text = file.read_text(encoding="utf-8") |
| LOW | `deeptutor/services/persona/service.py:289` | InvalidPersonaNameError | continue | `seed_presets` | name = self._validate_name(preset_dir.name) |
| LOW | `deeptutor/services/persona/service.py:295` | OSError | continue | `seed_presets` | text = source_file.read_text(encoding="utf-8") |
| LOW | `deeptutor/services/persona/service.py:326` | OSError | continue | `migrate_legacy_skills` | text = source_file.read_text(encoding="utf-8") |
| LOW | `deeptutor/services/rag/embedding_binding.py:90` | ValueError | continue | `migrate_binding` | config = get_embedding_config(selection, catalog=catalog) |
| LOW | `deeptutor/services/rag/file_routing.py:287` | UnicodeDecodeError | continue | `decode_bytes` | return data.decode(encoding) |
| LOW | `deeptutor/services/rag/file_routing.py:299` | UnicodeDecodeError | continue | `read_text_file` | with open(file_path, "r", encoding=encoding) as f: |
| LOW | `deeptutor/services/rag/linked_kb.py:87` | OSError | continue | `allowed_link_roots` | roots.append(Path(chunk).expanduser().resolve()) |
| LOW | `deeptutor/services/rag/pipelines/graphrag/pandas_compat.py:30` | arrow_key_error | continue | `_unregister_stale_extension_types` | pyarrow.unregister_extension_type(name) |
| LOW | `deeptutor/services/rag/pipelines/ima/envelope.py:87` | TypeError, ValueError | continue | `_first_present` | return int(payload[key]) |
| LOW | `deeptutor/services/rag/pipelines/kiwix/client.py:167` | KiwixError | continue | `parse_catalog_xml` | name = validate_zim_name(name) |
| LOW | `deeptutor/services/rag/pipelines/kiwix/client.py:203` | KiwixError | continue | `parse_search_xml` | article_path = validate_article_path(parsed.path[len(prefix) :]) |
| LOW | `deeptutor/services/rag/pipelines/kiwix/client.py:326` | KiwixError | pass | `search` | text = await self._read_article(client, hit.article_path) |
| LOW | `deeptutor/services/rag/pipelines/lightrag/engine.py:199` | OSError, ValueError | pass | `workspace_for` | meta = json.loads((root / "meta.json").read_text(encoding="utf-8")) |
| LOW | `deeptutor/services/rag/pipelines/lightrag/sidecar.py:44` | TypeError, ValueError | pass | `_position` | return IRPosition(type="bbox", anchor=page, range=[float(value) for value in bbox[:4]]) |
| LOW | `deeptutor/services/rag/pipelines/lightrag/storage.py:87` | OSError | continue | `has_output` | if path.is_file() and path.stat().st_size > 2: |
| LOW | `deeptutor/services/rag/pipelines/lightrag/worker.py:100` | RuntimeError | pass | `cancel` | loop.call_soon_threadsafe(task.cancel) |
| LOW | `deeptutor/services/rag/pipelines/llamaindex/storage.py:175` | Exception | continue | `_iter_file_embedding_dicts` | with open(path, "rb") as probe: |
| LOW | `deeptutor/services/rag/pipelines/weknora/client.py:64` | ValueError | pass | `_request_json` | if int(declared) > MAX_RESPONSE_BYTES: |
| LOW | `deeptutor/services/sandbox/artifacts.py:26` | OSError | continue | `_visible_files` | entries = os.scandir(directory) |
| LOW | `deeptutor/services/sandbox/artifacts.py:37` | OSError | continue | `_visible_files` | if entry.is_dir(follow_symlinks=False): |
| LOW | `deeptutor/services/sandbox/artifacts.py:90` | OSError, ValueError | continue | `snapshot_public_artifact_files` | relative = file_path.relative_to(root) |
| LOW | `deeptutor/services/sandbox/artifacts.py:152` | OSError, ValueError | continue | `collect_public_artifact_batch` | relative = file_path.relative_to(root) |
| LOW | `deeptutor/services/sandbox/artifacts.py:160` | ValueError | continue | `collect_public_artifact_batch` | rel_posix = content_service.relative_path(binding, file_path) |
| LOW | `deeptutor/services/sandbox/artifacts.py:171` | ValueError | continue | `collect_public_artifact_batch` | rel = file_path.resolve().relative_to(public_root) |
| LOW | `deeptutor/services/sandbox/backends.py:455` | ProcessLookupError, PermissionError | pass | `_terminate_process_tree` | os.killpg(process.pid, signal.SIGKILL) |
| LOW | `deeptutor/services/sandbox/backends.py:515` | UnicodeDecodeError | pass | `_decode_process_output` | return data.decode("utf-8") |
| LOW | `deeptutor/services/sandbox/backends.py:521` | LookupError, UnicodeDecodeError | continue | `_decode_process_output` | return data.decode(encoding) |
| LOW | `deeptutor/services/sandbox/runner/server.py:136` | ValueError, OSError | pass | `_apply` | resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes)) |
| LOW | `deeptutor/services/sandbox/runner/server.py:142` | ValueError, OSError | pass | `_apply` | resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds)) |
| LOW | `deeptutor/services/sandbox/runner/server.py:148` | ValueError, OSError | pass | `_apply` | resource.setrlimit(resource.RLIMIT_NOFILE, (_RLIMIT_NOFILE, _RLIMIT_NOFILE)) |
| LOW | `deeptutor/services/sandbox/runner/server.py:367` | KeyboardInterrupt | pass | `main` | server.serve_forever() |
| LOW | `deeptutor/services/session/_turn_runtime_shared.py:1063` | TypeError, ValueError | continue | `_build_question_bank_context` | entry_id = int(raw) |
| LOW | `deeptutor/services/session/source_inventory.py:400` | TypeError, ValueError | continue | `_add_fresh_questions` | eid = int(raw) |
| LOW | `deeptutor/services/session/source_inventory.py:640` | TypeError, ValueError | continue | `_collect_from_user_message` | eid = int(raw) |
| LOW | `deeptutor/services/session/sqlite_store.py:264` | OSError | pass | `_migrate_legacy_db` | os.replace(legacy_path, self.db_path) |
| LOW | `deeptutor/services/session/usage_recovery.py:94` | OSError, ValueError, TypeError, AttributeError | continue | `recover_summary` | data = json.loads(path.read_text()) |
| LOW | `deeptutor/services/setup/data_volume.py:167` | OSError | pass | `_try_write_or_raise` | probe.unlink(missing_ok=True) |
| LOW | `deeptutor/services/skill/service.py:302` | InvalidTagError | continue | `_read_tag_vocab` | out.append(self._normalize_tag(item)) |
| LOW | `deeptutor/services/skill/service.py:322` | InvalidTagError | continue | `_tags_from_meta` | out.append(self._normalize_tag(item)) |
| LOW | `deeptutor/services/skill/service.py:525` | SkillNotFoundError, InvalidSkillNameError | continue | `load_for_context` | detail = self.get_detail(name) |
| LOW | `deeptutor/services/skill/service.py:900` | InvalidTagError | continue | `_validate_tag_list` | cleaned.append(self._normalize_tag(raw)) |
| LOW | `deeptutor/services/subagent/claude_models.py:219` | OSError | pass | `_capture_model_screen` | os.close(fd) |
| LOW | `deeptutor/services/subagent/claude_models.py:223` | OSError | pass | `_capture_model_screen` | os.kill(pid, signal.SIGTERM) |
| LOW | `deeptutor/services/subagent/claude_models.py:227` | OSError | pass | `_capture_model_screen` | os.waitpid(pid, 0) |
| LOW | `deeptutor/services/subagent/models.py:209` | FileNotFoundError | pass | `_codex_options` | data = json.loads(cache.read_text(encoding="utf-8")) |
| LOW | `deeptutor/services/subagent/opencode_server.py:176` | ProcessLookupError | pass | `_terminate_sync` | handle.process.terminate() |
| LOW | `deeptutor/services/subagent/opencode_server.py:193` | ProcessLookupError | pass | `shutdown_servers` | handle.process.kill() |
| LOW | `deeptutor/services/subagent/process.py:133` | TimeoutError, ? | pass | `_terminate` | await asyncio.wait_for(process.wait(), timeout=_TERMINATE_GRACE_SECONDS) |
| LOW | `deeptutor/services/voice/adapters/openai_compat.py:469` | TypeError, ValueError | continue | `_parse_cues` | start = float(row.get("start", 0.0)) |
| LOW | `deeptutor/services/voice/adapters/volcengine.py:199` | KeyError, ValueError, TypeError | continue | `transcribe_cues` | start, end = float(row["start_time"]) / 1000, float(row["end_time"]) / 1000 |
| LOW | `deeptutor/services/voice/audio.py:39` | ?, EOFError | pass | `normalize_wav` | with wave.open(io.BytesIO(audio), "rb") as wav: |
| LOW | `deeptutor/services/voice/audio.py:98` | ValueError | continue | `_parse_pcm_content_type` | parsed = int(value) |
| LOW | `deeptutor/services/web_source/robots.py:91` | ValueError | continue | `parse_robots_txt` | delay = float(value) |
| LOW | `deeptutor/services/web_source/scheduler.py:99` | CancelledError | pass | `stop` | await self._task |
| LOW | `deeptutor/services/workspace/catalog.py:234` | WorkspaceError | continue | `list_workspaces` | legacy.append(self.binding_by_id(str(row.get("id") or ""))) |
| LOW | `deeptutor/services/workspace/data_migration.py:789` | UnicodeError | continue | `_rebind_feature_urls` | original = path.read_text(encoding="utf-8") |
| LOW | `deeptutor/services/workspace/data_migration.py:891` | OSError, ValueError | continue | `operations` | rows.append(json.loads(path.read_text())) |
| LOW | `deeptutor/services/workspace/dependencies.py:105` | OSError, ValueError | continue | `_forward_closure` | book = json.loads(path.read_text()) |
| LOW | `deeptutor/services/workspace/dependencies.py:214` | OSError, ValueError | continue | `_forward_closure` | document = json.loads(path.read_text()) |
| LOW | `deeptutor/services/workspace/dependencies.py:327` | ValueError, TypeError | continue | `_with_historical_references` | collect(json.loads(raw), prefs[sid]) |
| LOW | `deeptutor/services/workspace/dependencies.py:345` | ValueError | continue | `_with_historical_references` | value = json.loads(value) |
| LOW | `deeptutor/services/workspace/knowledge.py:129` | WorkspaceError, OSError | continue | `knowledge_catalog` | with workspace_context(row["workspace_id"]): |
| LOW | `deeptutor/services/workspace/service.py:201` | ValueError | continue | `_assert_allowed_root` | root.relative_to(allowed) |
| LOW | `deeptutor/services/workspace/service.py:413` | OSError | continue | `_walk_workspace` | entries = os.scandir(directory) |
| LOW | `deeptutor/services/workspace/service.py:423` | OSError, ValueError | continue | `_walk_workspace` | candidate.resolve().relative_to(binding.root) |
| LOW | `deeptutor/services/workspace/service.py:466` | OSError | continue | `list_entries_page` | stat = candidate.stat() |
| LOW | `deeptutor/services/workspace/service.py:587` | OSError, WorkspaceError | continue | `search_page` | relative = self.relative_path(binding, candidate) |
| LOW | `deeptutor/services/workspace/service.py:599` | OSError, UnicodeDecodeError | pass | `search_page` | for line_no, line in enumerate( |
| LOW | `deeptutor/tools/brainstorm.py:65` | ValueError | pass | `brainstorm` | llm_cfg = get_llm_config() |
| LOW | `deeptutor/tools/reason.py:77` | ValueError | pass | `reason` | llm_cfg = get_llm_config() |
| LOW | `deeptutor/tools/web_fetch.py:189` | ValueError | pass | `_is_disallowed_host` | return _is_disallowed_ip(ipaddress.ip_address(candidate)) |
| LOW | `deeptutor/utils/error_utils.py:77` | ?, AttributeError | pass | `format_exception_message` | error_data = json.loads(potential_json) |
| LOW | `deeptutor/utils/json_parser.py:21` | ImportError | pass | `<module>` | from json_repair import repair_json as _repair_json_import |
| LOW | `deeptutor/video_learning/notes.py:80` | NotebookCorruptedError | continue | `_matching_records` | records = manager.get_records(notebook_id) |
| LOW | `deeptutor/video_learning/service.py:222` | TypeError, ValueError | continue | `normalize_cues` | start = max(0.0, float(merged.get("start") or merged.get("from") or 0)) |
| LOW | `deeptutor/visualizers/store.py:121` | Exception | continue | `user_packages` | if manifest_file.stat().st_size > _MAX_MANIFEST_BYTES: |
| LOW | `scripts/export_discord_history.py:265` | ValueError | pass | `_request_json` | self._sleep(max(float(reset_after), 0.0)) |
| LOW | `tests/agents/test_failure_notices_name_the_cause.py:39` | Exception | continue | `_notice_definitions` | data = yaml.safe_load(path.read_text(encoding="utf-8")) or {} |
| LOW | `tests/conftest.py:44` | Exception | pass | `<module>` | from deeptutor.multi_user.paths import ADMIN_WORKSPACE_ROOT as _REAL_ADMIN_ROOT |
| LOW | `tests/multi_user/test_learner_profile.py:43` | ValueError | pass | `test_profile_rejects_invalid_age_oversized_text_and_control_characters` | normalize_profile(value) |
| LOW | `tests/services/partners/test_channel_secrets.py:182` | CancelledError | pass | `test_reload_lock_serialises_concurrent_calls` | await sentinel |
| LOW | `tests/services/partners/test_channel_secrets.py:222` | CancelledError | pass | `test_reload_failure_records_last_reload_error` | await sentinel |
| LOW | `tests/services/partners/test_wecom_channel.py:83` | CancelledError | pass | `exercise_startup` | await startup |
| LOW | `tests/services/rag/test_lightrag_server_pipeline.py:84` | LightRagServerNotConfiguredError | pass | `test_config_from_entry_requires_server_url` | config_from_entry({"api_key": "k"}) |

## 8. 附录 B：TS/JS 吞错清单（人工评级）

| 风险 | 位置 | 模式 | 说明 |
| --- | --- | --- | --- |
| HIGH | `web/app/(utility)/courses/[courseId]/page.tsx:414` | `void deleteCourse(...).then(...) — 无 .catch` | 删除课程的 Promise 完全未处理失败：拒绝时无任何用户反馈且产生 unhandled rejection |
| MEDIUM | `web/context/QuizFollowupContext.tsx:280` | `.catch(() => {})` | 笔记条目 followup_session_id 写入失败被静默丢弃 |
| MEDIUM | `web/features/settings/sections/DataMigrationSettingsSection.tsx:113` | `.catch(() => {})` | 数据迁移加载失败静默，界面无错误态 |
| MEDIUM | `web/features/settings/sections/DataMigrationSettingsSection.tsx:136` | `.catch(() => {})` | 数据迁移加载失败静默，界面无错误态 |
| MEDIUM | `web/features/chat/components/ChatWorkspace.tsx:1887` | `.catch(() => undefined)` | 聊天工作区后台操作失败静默 |
| MEDIUM | `web/components/chat/home/ChatComposer.tsx:658` | `void saveWorkspaceDraft(...).catch(() => {})` | 草稿保存失败静默，用户可能丢失输入 |
| MEDIUM | `web/components/chat/home/ChatComposer.tsx:545` | `.catch(() => {})` | 发送路径后台操作失败静默 |
| MEDIUM | `web/components/reading/library/AddMaterialsDialog.tsx:714` | `.catch(() => undefined)` | 资料库操作失败静默 |
| MEDIUM | `web/components/reading/library/ReadingLibrary.tsx:512` | `.catch(() => undefined)` | 资料库操作失败静默 |
| MEDIUM | `web/components/reading/library/MaterialLibrary.tsx:482` | `.catch(() => undefined)` | 资料库操作失败静默 |
| MEDIUM | `web/components/knowledge/KnowledgePage.tsx:198` | `.catch(() => undefined)` | 知识库页面后台操作失败静默 |
| MEDIUM | `web/components/reading/workspace/useReadingWorkspace.ts:453` | `.catch(() => {})` | 阅读工作区后台操作失败静默 |
| MEDIUM | `web/components/partners/PartnerConfigure.tsx:136` | `.catch(() => {})` | 伙伴配置加载失败静默 |
| MEDIUM | `web/components/partners/PartnerConfigure.tsx:164` | `.catch(() => {})` | 伙伴配置加载失败静默 |
| MEDIUM | `web/components/partners/PartnerComposer.tsx:143` | `.catch(() => {})` | 伙伴会话后台操作失败静默 |
| MEDIUM | `web/app/(workspace)/partners/new/page.tsx:113` | `.catch(() => {})` | 新建伙伴页后台操作失败静默 |
| MEDIUM | `web/components/watching/WatchingBrowser.tsx:279` | `.catch(() => undefined)` | 观看页后台操作失败静默 |
| MEDIUM | `web/components/reading/workspace/MediaReadingStage.tsx:240` | `.catch(() => undefined)` | 阅读媒体舞台后台操作失败静默 |
| MEDIUM | `web/components/reading/workspace/MediaReadingStage.tsx:328` | `.catch(() => undefined)` | 阅读媒体舞台后台操作失败静默 |
| MEDIUM | `web/components/chat/BookReferencePicker.tsx:106` | `.catch(() => undefined)` | 参考选择器加载失败静默 |
| MEDIUM | `web/components/chat/home/StandaloneComposer.tsx:615` | `.catch(() => undefined)` | 独立输入框后台操作失败静默 |
| MEDIUM | `web/components/chat/home/ConsultationTabBody.tsx:153` | `.catch(() => {})` | 咨询页后台操作失败静默 |
| MEDIUM | `web/features/chat/ChatStateAdapter.tsx:3217` | `void sendMessage(...) — 重试路径自带失败气泡` | 核心发送为 fire-and-forget，依赖内部错误气泡机制；若内部机制失效则静默 |
| LOW | `web/features/settings/sections/ArchivedChatsSettingsSection.tsx:113` | `await load().catch(() => {})` | 归档列表加载失败静默（仅展示） |
| LOW | `web/components/chat/home/SessionActivityPanel.tsx:87` | `.catch(() => {})` | 活动面板加载失败静默（仅展示） |
| LOW | `web/components/chat/home/SessionActivityPanel.tsx:103` | `.catch(() => {})` | 活动面板加载失败静默（仅展示） |
| LOW | `web/components/chat/home/SessionActivityPanel.tsx:120` | `.catch(() => {})` | 活动面板加载失败静默（仅展示） |
| LOW | `web/components/reading/EpubDocumentView.tsx:411` | `getReadingPosition(...).catch(() => null)` | 读取进度失败的 null 兜底（渐进增强） |
| LOW | `web/components/reading/ReadingExtensionBar.tsx:121` | `getOwnLearnerProfile().catch(() => null)` | profile 读取失败 null 兜底 |
| LOW | `web/components/reading/ReadingActionsProvider.tsx:80` | `getOwnLearnerProfile().catch(() => null)` | profile 读取失败 null 兜底 |
| LOW | `web/app/(utility)/courses/[courseId]/page.tsx:70` | `getCourseState(...).catch(() => null)` | 课程态读取失败 null 兜底 |
| LOW | `web/lib/courses-api.ts:132` | `response.json().catch(() => null)` | JSON 解析失败 null 兜底（调用方有判空） |
| LOW | `web/lib/guardian-api.ts:57` | `res.json().catch(() => null)` | JSON 解析失败 null 兜底 |
| LOW | `web/lib/attachment-limits.ts:46` | `response.json().catch(() => null)` | JSON 解析失败 null 兜底 |
| LOW | `web/hooks/useVoiceRecorder.ts:76` | `resp.json().catch(() => null)` | JSON 解析失败 null 兜底 |
| LOW | `web/components/reading/workspace/MediaReadingStage.tsx:142` | `void document.exitFullscreen().catch(() => undefined)` | 浏览器全屏 API 尽力而为 |
| LOW | `web/components/watching/WatchingPane.tsx:108` | `void saveVideoProgress(...).catch(...)` | 进度保存失败静默（后台进度写入，注释式兜底附近） |
| LOW | `web/tests/chat-reply-language.spec.tsx:56` | `.catch(() => undefined)` | 测试代码 |
| LOW | `web/tests/chat-reply-language.spec.tsx:57` | `.catch(() => undefined)` | 测试代码 |
| LOW | `web/tests/e2e/settings-navigation.audit.ts:557` | `.catch(() => {})` | 测试代码 |
| LOW | `web/next.config.js:89` | `} catch {}` | 版本号探测失败回退空串（构建期尽力而为） |
| LOW | `web/lib/iframe-html.ts:103` | `} catch (error) {}` | iframe 内 postMessage 可能因跨域抛同步异常，属预期 |
| LOW | `web/lib/iframe-html.ts:121` | `} catch (error) {}` | iframe 内 postMessage 可能因跨域抛同步异常，属预期 |
---
*报告由只读扫描生成（agent/dt22-todo-scan @ myfork）。任何条目的定级争议请以 §5 规则与源码现场为准。*
