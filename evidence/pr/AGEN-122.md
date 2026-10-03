# PR: test(api): lock KB upload/delete guard contracts

## Summary

- Adds 11 contract tests for the knowledge-base HTTP entry points in `deeptutor/api/routers/knowledge.py`, locking three data-integrity guard contracts that the existing API suite did not cover:
  1. **Rejected uploads leave no partial state** — unsupported extensions, oversize files (validated against the configured size limit), duplicate names inside one batch, and provider/KB mismatch all return `400` while leaving zero staged files under `raw/`, dispatching zero background tasks, and never flipping the KB status to `processing`.
  2. **Task ids are idempotent per logical key and never collide across uploads** — a retried upload with the same logical key reuses the same task id; two distinct accepted uploads always get distinct task ids, each dispatching exactly one background task.
  3. **Deletes keep listing, metadata, and disk consistent** — deleting a raw file updates the `/files` listing, removes the disk file, and drops its hash from `metadata.json` (including the already-indexed case and a repeat delete returning `404`); deleting a whole KB (both the path-param and body routes) empties the listing and removes the directory and its config entry.
- Unit-level rollback companions: a batch member failing validation unlinks the files already written by `_save_uploaded_files`, and a stream that exceeds the size limit mid-write has its partial file removed.
- **No product code is changed** — a single new test file (`tests/api/test_knowledge_upload_guards.py`, 388 lines).

## Root cause

`deeptutor/api/routers/knowledge.py` is the primary write path for knowledge-base data, but its guard behavior had no direct tests: 923 of 2367 statements were uncovered by the existing API suite. Regressions in upload validation (e.g. leaving half-written files in `raw/` after a rejected batch), task-id minting, or delete bookkeeping (listing/hash-metadata/disk divergence) would not be caught by CI. This PR pins those contracts so future refactors of the router keep them intact.

## Changes

- `tests/api/test_knowledge_upload_guards.py` (new, +388 lines): 11 tests in three groups matching the contracts above. Route-level tests build a minimal FastAPI app around the real router with a real `KnowledgeBaseManager` on a throwaway directory; unit tests exercise `_save_uploaded_files` rollback and `TaskIDManager.build_unique_task_id` collision-freedom. All environment touch points (PocketBase, dispatch recorder, base dirs) are patched per-test, so the suite neither depends on nor pollutes runtime configuration and data.

## Tests

All commands run on a branch based on the current `dev` tip (`ef2d9e5c3`, v1.6.12):

- `pytest tests/api/test_knowledge_upload_guards.py -v` → **11 passed**
- `pytest tests/api/test_knowledge_router.py tests/api/test_knowledge_progress_ws.py tests/api/test_knowledge_zip_upload.py tests/api/test_knowledge_upload_guards.py tests/knowledge/ -q` → **304 passed** (no failures, no cross-test pollution)
- Coverage of the target router (existing API files vs. with the new file):
  `pytest tests/api/test_knowledge_router.py tests/api/test_knowledge_progress_ws.py tests/api/test_knowledge_zip_upload.py --cov=deeptutor.api.routers.knowledge --cov-report=term -q` → 130 passed, **923 missing** of 2367 stmts;
  same command plus `tests/api/test_knowledge_upload_guards.py` → 141 passed, **899 missing** (**−24 missing statements**)
- `ruff check tests/api/test_knowledge_upload_guards.py && ruff format --check tests/api/test_knowledge_upload_guards.py` → All checks passed; 1 file already formatted

## Related issue

None — the gap was identified by an internal coverage audit as the largest single coverage hole in the API layer (`deeptutor/api/routers/knowledge.py`, 61% line coverage from the existing API suite). No upstream issue tracks it; this PR is related to upload/delete guard hardening only, not a fix for a reported bug.
