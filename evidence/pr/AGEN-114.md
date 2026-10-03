# PR: test(notebook): pin Question Notebook API source/dedup/concurrency contract

`POST /api/question-notebook/entries/upsert` and the `GET /entries` source filter — the HTTP surface of the Question Notebook (wrong-question book) — had no route-level contract tests. Merged PR #1341 added the partner-side tooling plus `tests/tools/test_question_bank_tool.py`, but the router layer itself (legal source enumeration, 422 validation of unknown sources, identity dedup/update semantics, `origin_ref` rules, concurrent-write safety) remained unpinned: a refactor breaking any of these would pass the existing suite unnoticed. This PR adds `tests/api/test_notebook_api_contract.py` with 20 test cases. No product code is changed.

## Summary

- Add `tests/api/test_notebook_api_contract.py` (11 test functions / 20 cases):
  1. **Source catalog pinned**: `ASSESSMENT_SOURCES` equals the full 6-source set (`deep_question`, `mastery_path`, `immersive_reading`, `book`, `partner_chat`, `import`), so adding/removing a source fails explicitly instead of silently changing API behavior.
  2. **Valid sources accepted**: each of the 6 sources upserts with 200 and echoes `source` back.
  3. **Invalid sources rejected**: unlisted values (`wechat_chat`, `partner`, case variant `Partner_Chat`, `deepquest`, empty string) → 422 with Pydantic `literal_error` at `body.source` and zero rows written; `GET /entries?source=<unlisted>` also returns 422.
  4. **partner_chat roundtrip**: the #1244 target end state — a partner-chat entry persists, reads back by id, and filters by source.
  5. **Identity dedup + content update**: two upserts with the same `(origin_type, origin_ref, turn_id, question_id)` collapse to a single row updated in place (`user_answer` overwritten, `score_trend` new → declined); a different `turn_id` creates a distinct row (identity is turn-scoped).
  6. **origin_ref rules**: conversation entries whose `origin_ref` mismatches `session_id` → 422 with zero writes; non-conversation origins (`external_import`) require `origin_ref`.
  7. **Concurrency**: 8 parallel identical-key upserts (ASGITransport + `asyncio.gather`) all return 200 and leave exactly 1 row; 8 parallel distinct-turn upserts leave 8 rows, none lost.

## Root cause

No product defect. Issue #1244 reported that partner-chat wrong questions never reached the notebook; its API-layer half was already fixed by v1.6.12 (`partner_chat` and `import` are legal sources; #1341 added the partner tool path), but nothing pins the resulting contract. These tests are the regression guard for #1244-class changes: any change to the source enumeration, identity key, validation, or concurrent-write behavior turns these tests red first.

## Changes

- New file `tests/api/test_notebook_api_contract.py` (+274 lines).
- Zero product-code changes; assertions target HTTP status codes, Pydantic 422 structured fields, and actual SQLite row counts — no brittle regex or class-name matching.

## Tests

All commands run on a branch based on the current `dev` tip (`ef2d9e5c3`, v1.6.12):

- `pytest tests/api/test_notebook_api_contract.py -q` → **20 passed**
- `pytest tests/api/test_notebook_api_contract.py tests/api/test_notebook_router.py -q` → **38 passed** (existing router tests, no regression)
- Full notebook module suite (`tests/api/test_notebook_router.py tests/api/test_main_notebook_router.py tests/api/test_book_quiz_attempt_notebook.py tests/services/test_notebook_service.py tests/tools/test_list_notebook.py tests/cli/test_notebook_cli.py tests/agents/notebook`) → **66 passed**
- `pytest tests/tools/test_question_bank_tool.py -q` → **20 passed**
- `ruff check` and `ruff format --check` on the new file → clean
- `scripts/check_architecture.py`, `scripts/check_repo_hygiene.py` → OK

## Related issue

Related to #1244 (API-contract half; the partner tool-surface gap identified there is out of scope for this test-only PR).
