# PR: test(reading): pin progress API durability contract

The Immersive Reading progress endpoints (`PUT/GET /api/reading/materials/{id}/position` and `POST/GET/DELETE /api/reading/materials/{id}/bookmarks`) had no direct handler tests — a regression that loses, rolls back, or silently corrupts a reader's saved position or bookmarks would pass the existing suite unnoticed. This PR adds `tests/api/routers/test_reading_progress.py` with 20 TestClient contract tests. No product code is changed.

## Summary

- Add `tests/api/routers/test_reading_progress.py` (+241 lines): 20 contract tests for the position and bookmark handlers in `deeptutor/api/routers/reading.py`, the routes a reader trusts to survive a reload.
- Add empty `tests/api/routers/__init__.py` so pytest resolves the package.
- The suite drives a real `ReadingStore` / `LearningStore` behind the real ASGI routes (no stubs on the persistence path) and asserts on disk state, not just response bodies.

## Root cause

No product defect. A coverage audit showed the progress handlers (roughly lines 1392–1470 of `deeptutor/api/routers/reading.py`) had zero direct coverage — 25 of the file's 279 missing lines. Progress-loss bugs in these routes are invisible until a user reopens a book on another device, so they deserve contract tests that pin persistence behavior. This PR closes that gap with isolated contract tests only.

## Changes

- New file `tests/api/routers/test_reading_progress.py` (+241 lines), new empty `tests/api/routers/__init__.py`. Zero product-code changes (`deeptutor/` untouched).
- Four contract groups:
  1. **Save → retrieve round-trip**: a saved position returns exactly the saved locator / anchor / percentage; default state before any save is locator 1 at 0%.
  2. **Idempotency / convergence**: duplicate position saves leave a single `positions/*.json` state file with monotone `updated_at` and a single learning record; re-saving with a new locator overwrites in place; a duplicate bookmark POST keeps the first bookmark's id and label.
  3. **Malformed payload rejection (4xx) with no partial persistence**: out-of-range locator, percentage outside [0, 1], oversize source anchor / label, wrong locator type, and empty body are all rejected, and each rejected save persists nothing (state stays at the previous position).
  4. **Failure containment**: an out-of-range save returns 400 and leaves the previous position intact; every method 404s for an unknown material; deleting a bookmark removes exactly one row and 404s on repeat.
- Full isolation: `DEEPTUTOR_HOME` redirected to `tmp_path` with `PathService` reset per test — no writes to real user data, no network, no LLM calls.

## Tests

All commands run on a branch based on the current `dev` tip (`ef2d9e5c3`, v1.6.12):

- `python -m pytest tests/api/routers/test_reading_progress.py -q` → **20 passed**
- `python -m pytest tests/api/routers/test_reading_progress.py tests/reading/test_router.py -q` → **65 passed** (combined run, no cross-test pollution)
- `python -m pytest tests/api/routers/test_reading_progress.py tests/reading/ -q` → **422 passed** (full reading-module regression)
- `ruff check tests/api/routers/test_reading_progress.py` → All checks passed
- `ruff format --check tests/api/routers/test_reading_progress.py` → clean
- `pre-commit run --files tests/api/routers/test_reading_progress.py tests/api/routers/__init__.py` → all hooks Passed
- `python scripts/check_architecture.py` → OK; `python scripts/check_workspace_hygiene.py` → passed

## Related issue

Related to the reading-progress coverage gap identified in a coverage audit (the progress handlers had no direct tests; this change covers 23 of the 25 previously missing lines in that region). No upstream issue tracks this gap; this PR is standalone test hardening with no behavior change.
