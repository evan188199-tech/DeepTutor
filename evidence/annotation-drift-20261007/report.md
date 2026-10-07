# Annotation drift scan — docstring vs annotation vs actual return

- repo commit assumed: `origin/main f07029cfcf2c8dfccdb671cdfc343db8334f5741`
- fanin source: `myfork/scan/coverage-gaps-det-20261006:evidence/coverage-gaps-20261005/summary.json#fanin_top50`
- scan interpreter: Python 3.14.6 (stdlib-only scan)
- runtime sampling interpreter: passed via --venv-python
- modules resolved: 29 (missing: 0)
- functions available in universe: 335
- sampled (cap): 200
- runtime-verified: 15
- drift rows total: 30

## Drift kind counts

| kind | count |
|---|---|
| `override_signature_mismatch` | 1 |
| `required_param_undocumented` | 29 |

## Drift rows (anchor = current main path:line)

| function | anchor | kind | detail |
|---|---|---|---|
| `PathService.get_co_writer_doc_root` | `deeptutor/services/path_service.py:394` | `required_param_undocumented` (low) | required param 'doc_id' not documented in docstring |
| `PathService.get_book_root` | `deeptutor/services/path_service.py:407` | `required_param_undocumented` (low) | required param 'book_id' not documented in docstring |
| `owner_secrets_dir` | `deeptutor/multi_user/paths.py:217` | `required_param_undocumented` (low) | required param 'owner_id' not documented in docstring |
| `atomic_write_json` | `deeptutor/services/file_io.py:37` | `required_param_undocumented` (low) | required param 'path' not documented in docstring |
| `atomic_write_text` | `deeptutor/services/file_io.py:63` | `required_param_undocumented` (low) | required param 'path' not documented in docstring |
| `account_workspace_context` | `deeptutor/services/workspace/context.py:37` | `required_param_undocumented` (low) | required param 'account_root' not documented in docstring |
| `workspace_url` | `deeptutor/services/workspace/context.py:53` | `required_param_undocumented` (low) | required param 'url' not documented in docstring |
| `BaseTool.get_prompt_hints` | `deeptutor/core/tool_protocol.py:258` | `required_param_undocumented` (low) | required param 'language' not documented in docstring |
| `StreamBus.stage` | `deeptutor/runtime/stream_bus.py:129` | `required_param_undocumented` (low) | required param 'source' not documented in docstring |
| `StreamBus.stage` | `deeptutor/runtime/stream_bus.py:129` | `required_param_undocumented` (low) | required param 'metadata' not documented in docstring |
| `StreamBus.wait_for_input` | `deeptutor/runtime/stream_bus.py:312` | `required_param_undocumented` (low) | required param 'stage' not documented in docstring |
| `StreamBus.submit_input` | `deeptutor/runtime/stream_bus.py:344` | `required_param_undocumented` (low) | required param 'content' not documented in docstring |
| `register_bus` | `deeptutor/runtime/stream_bus.py:363` | `required_param_undocumented` (low) | required param 'turn_id' not documented in docstring |
| `unregister_bus` | `deeptutor/runtime/stream_bus.py:368` | `required_param_undocumented` (low) | required param 'turn_id' not documented in docstring |
| `LLMConfig.model_copy` | `deeptutor/services/llm/config.py:147` | `required_param_undocumented` (low) | required param 'update' not documented in docstring |
| `LearningTransaction.put_topic` | `deeptutor/learning/storage.py:259` | `required_param_undocumented` (low) | required param 'sources' not documented in docstring |
| `LearningStore.rebuild_learning_evidence_projection` | `deeptutor/learning/storage.py:756` | `required_param_undocumented` (low) | required param 'book_id' not documented in docstring |
| `LearningStore.list_learning_evidence` | `deeptutor/learning/storage.py:920` | `required_param_undocumented` (low) | required param 'book_id' not documented in docstring |
| `LearningStore.list_learning_evidence` | `deeptutor/learning/storage.py:920` | `required_param_undocumented` (low) | required param 'knowledge_point_id' not documented in docstring |
| `LearningStore.load_with_learning_evidence` | `deeptutor/learning/storage.py:947` | `required_param_undocumented` (low) | required param 'book_id' not documented in docstring |
| `LearningStore.load_with_learning_evidence` | `deeptutor/learning/storage.py:947` | `required_param_undocumented` (low) | required param 'knowledge_point_id' not documented in docstring |
| `LearningStore.transaction` | `deeptutor/learning/storage.py:1092` | `required_param_undocumented` (low) | required param 'book_id' not documented in docstring |
| `LearningStore.record_reading_position` | `deeptutor/learning/storage.py:1291` | `required_param_undocumented` (low) | required param 'material_id' not documented in docstring |
| `LearningStore.record_reading_position` | `deeptutor/learning/storage.py:1291` | `required_param_undocumented` (low) | required param 'locator' not documented in docstring |
| `LearningStore.record_reading_position` | `deeptutor/learning/storage.py:1291` | `required_param_undocumented` (low) | required param 'percentage' not documented in docstring |
| `LearningStore.record_reading_activity` | `deeptutor/learning/storage.py:1370` | `required_param_undocumented` (low) | required param 'material_id' not documented in docstring |
| `LearningStore.record_reading_activity` | `deeptutor/learning/storage.py:1370` | `required_param_undocumented` (low) | required param 'extension_id' not documented in docstring |
| `LearningStore.record_reading_activity` | `deeptutor/learning/storage.py:1370` | `required_param_undocumented` (low) | required param 'locator' not documented in docstring |
| `LearningStore.record_reading_activity` | `deeptutor/learning/storage.py:1370` | `required_param_undocumented` (low) | required param 'result_type' not documented in docstring |
| (override) | `deeptutor/services/workspace/context.py:107` | `override_signature_mismatch` (medium) | WorkspacePathService.__init__ required params ['account', 'scope'] != PathService.__init__ required params ['workspace_root'] |

## Runtime-verified samples

| function | anchor | call | observed | verdict |
|---|---|---|---|---|
| `get_path_service` | `deeptutor/services/path_service.py:509` | `get_path_service()` | `{"kind": "object:PathService"}` | OK |
| `admin_scope` | `deeptutor/multi_user/paths.py:89` | `admin_scope()` | `{"kind": "object:UserScope"}` | OK |
| `local_admin_user` | `deeptutor/multi_user/paths.py:93` | `local_admin_user()` | `{"kind": "object:CurrentUser"}` | OK |
| `scope_for_user` | `deeptutor/multi_user/paths.py:102` | `scope_for_user('', is_admin=False)` | `{"kind": "object:UserScope"}` | OK |
| `get_admin_path_service` | `deeptutor/multi_user/paths.py:149` | `get_admin_path_service()` | `{"kind": "object:PathService"}` | OK |
| `get_account_path_service` | `deeptutor/multi_user/paths.py:153` | `get_account_path_service()` | `{"kind": "object:PathService"}` | OK |
| `get_current_path_service` | `deeptutor/multi_user/paths.py:164` | `get_current_path_service()` | `{"kind": "object:PathService"}` | OK |
| `get_owner_path_service` | `deeptutor/multi_user/paths.py:200` | `get_owner_path_service()` | `{"kind": "object:PathService"}` | OK |
| `current_owner_id` | `deeptutor/multi_user/paths.py:254` | `current_owner_id()` | `{"kind": "str", "len": 11}` | OK |
| `get_current_user` | `deeptutor/multi_user/context.py:22` | `get_current_user()` | `{"kind": "object:CurrentUser"}` | OK |
| `get_current_user_or_none` | `deeptutor/multi_user/context.py:26` | `get_current_user_or_none()` | `{"kind": "none"}` | OK |
| `user_from_token_payload` | `deeptutor/multi_user/context.py:30` | `user_from_token_payload(None)` | `{"kind": "object:CurrentUser"}` | OK |
| `get_workspace_scope` | `deeptutor/services/workspace/context.py:32` | `get_workspace_scope()` | `{"kind": "none"}` | OK |
| `current_workspace_id` | `deeptutor/services/workspace/context.py:48` | `current_workspace_id()` | `{"kind": "str", "len": 0}` | OK |
| `workspace_url` | `deeptutor/services/workspace/context.py:53` | `workspace_url('')` | `{"kind": "str", "len": 14}` | OK |

## Scope and dedup notes

- Universe: public functions (module-level + public methods) inside fanin Top50 modules from `scan/coverage-gaps-det-20261006` crossed with current `main`; sample capped at 200 functions ordered by (module fanin desc, path, line).
- Dedup vs `scan/mypy-adoption-20261006`: that scan measures annotation *adoption*; this scan reports *inconsistencies* between declared and actual behavior. Unannotated functions are not counted as drift here.
- Dedup vs `test/settings-docstring-field-parity-20261006`: that card guards config Field defaults vs docstrings in the settings domain (dataclass field level); this scan is function signature/return level and does not inspect Field defaults.
- Runtime pass is subprocess-isolated (temp HOME/cwd, 60s timeout, safe scalar args only); imports or calls that fail are recorded as skipped, never as drift.
- Anchor lines are valid for the commit noted above; regenerate on the same commit to reproduce.
- Re-run: `python3 scan_annotation_drift.py --repo-root <repo> --fanin fanin_top50.json [--venv-python <repo venv python>]` (deterministic: fixed ordering, fixed args, sorted output).
