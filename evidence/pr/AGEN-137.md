# PR: fix(knowledge): log folder sync state recording failures

## Summary

- `KnowledgeBaseManager.update_folder_sync_state()` in `deeptutor/knowledge/manager.py` swallowed per-file mtime recording errors with `except Exception: pass`. A file whose state could not be recorded (e.g. the source file vanished or became unreadable between scanning and recording) silently degraded the persisted sync state while `last_sync` still advanced, leaving the linked folder looking "synced" with no trace of the omission.
- This PR replaces the bare `pass` with a `logger.warning` naming the KB, folder id, file path, and the exception, so the degradation is diagnosable from logs.
- Behavior is otherwise unchanged: the un-recorded file is still omitted from `synced_files`, so the next `detect_folder_changes()` scan re-detects it as new and re-syncs it. No control flow, return value, or caller-visible semantics change.

## Root cause

The per-file loop that records modification times wraps `Path.stat()` / `datetime.fromtimestamp()` in `try/except Exception: pass` (introduced with the persisted folder sync state in #619). Under real concurrency — a source file deleted, locked, or permission-denied mid-sync — the failure was completely invisible: the file never entered `synced_files`, yet `last_sync` advanced and the metadata was persisted as success, making "why does my linked folder miss this file?" impossible to debug.

## Changes

- `deeptutor/knowledge/manager.py` (+7/−1): capture the exception and log one `logger.warning` per failed file (`Failed to record sync state for '<file>' in folder '<folder_id>' of KB '<kb_name>': <exc>`); the file stays un-recorded so the next scan re-syncs it.
- `tests/knowledge/test_linked_folder_sync.py` (+50): new regression test `test_update_folder_sync_state_mtime_failure_is_visible_not_fake_synced`. It monkeypatches `Path` with a flavour whose `exists()` succeeds but `stat()` raises `OSError` (the real mid-sync race), and asserts via `caplog` that a WARNING naming the file is emitted, that the file is not marked synced (`file_count == 0`), and that `detect_folder_changes()` re-detects it as a new file.

## Tests

All commands run on a branch based on the current `dev` tip (`ef2d9e5c3`, v1.6.12):

- `python -m pytest tests/knowledge/test_linked_folder_sync.py::test_update_folder_sync_state_mtime_failure_is_visible_not_fake_synced` → **1 passed**
- `python -m pytest tests/knowledge/test_linked_folder_sync.py tests/api/test_linked_folder_routes.py` → **14 passed**
- `python -m pytest tests/knowledge/` → **164 passed**
- `python -m pytest tests/api/test_knowledge_router.py` → **124 passed**
- Red-green check: with the product code reverted to pre-fix `dev` state, the new test fails (`AssertionError: expected a logged warning ..., got none`), confirming it pins the fix.
- `ruff check deeptutor/knowledge/manager.py tests/knowledge/test_linked_folder_sync.py` → All checks passed
- `ruff format --check <same files>` → 2 files already formatted

## Related issue

None — found during an internal error-handling audit of silent `except: pass` sites in the knowledge subsystem. Related to #619, which introduced the persisted folder sync state being fixed here.
