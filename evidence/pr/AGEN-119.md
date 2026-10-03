# PR: fix(notebook): log unreadable files instead of skipping them silently during index rebuild

## Summary

- When `notebooks_index.json` is unreadable, `NotebookManager._rebuild_index_entries()` rebuilds the index by parsing every notebook file on disk — but a file that failed to parse was dropped via a bare `except Exception: continue` with no per-file log, so a damaged notebook silently vanished from the rebuilt index.
- This PR logs one `logger.warning` per skipped file (path + exception cause, never file contents). Skipping behavior is unchanged: the file is left untouched on disk and the existing `list_notebooks()` reconciliation keeps surfacing it as an `unreadable` entry, so the damage is alerted, visible, and repairable.
- Adds a regression test that drives `_rebuild_index_entries()` directly and fails on the pre-fix code.

## Root cause

`_rebuild_index_entries()` in `deeptutor/services/notebook/service.py` wrapped the per-file `json.load` in `except Exception: continue`. A truncated or unparsable notebook file therefore disappeared from the rebuilt index with no trace, and its absence stayed invisible until some later caller happened to re-scan the directory (which is what surfaces the `unreadable` placeholder).

## Changes

- `deeptutor/services/notebook/service.py` (+8/−1): capture the exception as `exc` and emit `logger.warning("notebook file %s is unreadable (%s); excluded from the rebuilt index", path, exc)` before `continue`. No return-value or exception semantics change; the rebuild still completes and still excludes unreadable files from the index.
- `tests/services/test_notebook_service.py` (+26): new `test_index_rebuild_reports_unreadable_files_instead_of_silence` — creates one valid and one corrupt notebook plus a corrupt index, drives `_rebuild_index_entries()` under `caplog`, and asserts (a) a warning naming `broken01.json` is emitted, (b) the good notebook survives the rebuild, and (c) `list_notebooks()` still shows the damaged file as `unreadable`.

## Tests

All commands run on `fix/notebook-index-skip-corrupted-pr`, rebased on the current `dev` tip (`ef2d9e5c3`, v1.6.12):

- `pytest tests/services/test_notebook_service.py -v` → **14 passed** (13 pre-existing + 1 new)
- `pytest tests/tools/test_list_notebook.py tests/cli/test_notebook_cli.py tests/api/test_notebook_router.py tests/api/test_main_notebook_router.py tests/api/test_book_quiz_attempt_notebook.py -q` → **49 passed**
- `pytest tests/agents/notebook -q` → **4 passed**
- Red-green check: with only the new test applied on the pre-fix base (`ef2d9e5c3`), it fails (**1 failed, 13 deselected**, no warning captured); on this branch it passes — confirming the test pins the fix.
- `ruff check deeptutor/services/notebook/service.py tests/services/test_notebook_service.py` → All checks passed
- `ruff format --check <same files>` → 2 files already formatted
- `python3 scripts/check_architecture.py` → OK; `python3 scripts/check_workspace_hygiene.py` → passed

## Related issue

None — found during an internal error-handling audit of silent `except: continue` sites in the notebook pipeline.
