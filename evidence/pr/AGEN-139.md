# PR: fix(update): log and skip recovery when job state is unreadable

## Summary

- The update worker's failure-recovery path loaded the job state (`store.load()`) inside its broad exception handler without guarding the load itself: with a corrupt or unreadable `state.json`, the failed-update bookkeeping and the app restore were skipped silently — the job stayed stuck with no trace in `worker.log`.
- This PR catches the state-load failure separately: it appends a durable diagnostic record (the load error plus the original failure) to the worker log and exits with status 1, leaving the damaged state file untouched for inspection.

## Root cause

In `run_update_worker()` (`deeptutor/runtime/update_worker.py`), the recovery branch ran `current = store.load()` inside the `except Exception` handler with no protection of its own. When `state.json` was corrupt:

1. `store.load()` raised inside the handler, so `mark_failed()` never ran — the job never transitioned to `failed` and stayed pending forever.
2. The trusted restart vector (`restart_home` / `restart_argv`) comes from the loaded state; with the load failing, neither value was known, yet the error was swallowed with no log line — a silently aborted recovery was indistinguishable from a clean exit.

## Changes

- `deeptutor/runtime/update_worker.py` (+27):
  - New helper `_log_aborted_recovery(store, *, original, load_error)`: writes one durable record naming both the load error and the original failure to `store.log_path` (the same file the launcher redirects worker stderr into); falls back to `sys.stderr` when the log file itself is unreachable (`OSError`).
  - The recovery path now catches the load failure separately: log the aborted recovery, return exit code 1, and skip the round without touching the damaged state — no blind overwrite and no restart from an unknown vector.
- `tests/runtime/test_update_worker.py` (+26): `test_worker_recovery_reports_and_skips_on_corrupt_state` covers the full lifecycle — injects invalid JSON into `state.json` from the command runner, fails the update command (status 7), then asserts exit 1, no restart, the corrupt state preserved byte-for-byte, and `worker.log` containing both the load-error and original-failure diagnostics.

## Tests

All commands run on the branch rebased on the current `dev` tip (`ef2d9e5c3`, v1.6.12; the rebase was a no-op — the fix commit sits directly on that tip):

- `python -m pytest tests/runtime/test_update_worker.py -q` → **4 passed**
- `python -m pytest tests/services/test_app_update.py tests/runtime/test_update_worker.py tests/runtime/test_launcher.py -q` → **52 passed**
- Red-green: with only the new test file copied onto unmodified `dev` (`ef2d9e5c3`), the new test fails with `FileNotFoundError` (no `worker.log` diagnostic record is ever written) → **1 failed, 3 passed**; on the fix branch it passes.
- `ruff check deeptutor/runtime/update_worker.py tests/runtime/test_update_worker.py` → All checks passed
- `ruff format --check deeptutor/runtime/update_worker.py tests/runtime/test_update_worker.py` → 2 files already formatted

## Related issue

None — found during an internal review of the update-worker recovery path. No upstream issue or PR covers this path (searched "update worker state", "state.json", "mark_failed", "worker recovery" before preparing this PR; no matches).
