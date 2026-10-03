# PR: fix: log runtime singleton reset failures instead of swallowing them

## Summary

- `_reset_runtime_singletons()` exists in two copies (`deeptutor_cli/init_cmd.py` and `deeptutor/runtime/launcher.py`) and drops cached `PathService` / `RuntimeSettingsService` / `ModelCatalogService` singletons so a newly selected `DEEPTUTOR_HOME` takes effect. Every step was wrapped in a bare `except Exception: pass`, so a failed reset was completely invisible.
- A failed `PathService` reset leaves the previous home's cached paths in place: `deeptutor init --home <dir>` and `launcher start` then keep writing into the *old* workspace with no log, no error, and no hint of why.
- This PR keeps the best-effort control-flow contract (no exception escapes, no return-value change, singletons still reset independently) and only makes failures observable: `PathService` reset failures log at ERROR with a full traceback and an explicit warning that writes may land in the previous `DEEPTUTOR_HOME`; the two config-cache clears log at WARNING with `exc_info`.

## Root cause

The reset helpers were written as fire-and-forget cleanup: each singleton reset sat inside `try/except Exception: pass`. That is reasonable for "don't crash startup because a cache clear failed", but for `PathService` the reset is what redirects *all later writes* to the selected home — swallowing its failure converts a recoverable misconfiguration into silent data misplacement (writes continue into the previous workspace across the whole process lifetime). The failure mode needed to be logged, not raised.

## Changes

- `deeptutor_cli/init_cmd.py` — module logger; `_reset_runtime_singletons()` logs `PathService.reset_instance()` failures at ERROR (`logger.exception`, message says later writes may keep going to the previous `DEEPTUTOR_HOME`) and `RuntimeSettingsService` / `ModelCatalogService` `_instances.clear()` failures at WARNING with `exc_info`; docstring updated to state the logging contract.
- `deeptutor/runtime/launcher.py` — same treatment for the launcher's duplicate copy of the helper, with the runtime-flavored message ("the runtime may keep writing to the previous DEEPTUTOR_HOME instead of the selected one").
- No behavior change outside the `except` blocks: exceptions are still contained per singleton, return value and call order unchanged.

## Tests

New focused unit tests (8 cases, monkeypatch each singleton entry point to raise):

- `tests/cli/test_init_cmd_reset_singletons.py` — ERROR log with traceback on `PathService` failure (message mentions the previous `DEEPTUTOR_HOME`); WARNING logs for the two cache clears; one singleton failing does not prevent the others from being reset.
- `tests/runtime/test_launcher_reset_singletons.py` — the same four assertions for the launcher copy.

Fail-first verification: with the two product files reverted to the `dev` baseline (`ef2d9e5c3`), the suite reports **6 failed, 2 passed** (all six log assertions fail because the exceptions are swallowed; the two independence assertions pass on the baseline too). On this branch: **8 passed**.

Full validation on this branch (rebased onto the current `dev` tip `ef2d9e5c3`, v1.6.12; commands run from the repo root):

- `pytest tests/cli/test_init_cmd_reset_singletons.py tests/runtime/test_launcher_reset_singletons.py -q` → **8 passed**
- `pytest tests/cli -q` → **87 passed**
- `pytest tests/runtime -q` → **204 passed, 4 skipped**
- `ruff check` / `ruff format --check` on the four files → all checks passed / already formatted
- `python scripts/check_architecture.py` → Architecture boundaries: OK
- `python scripts/check_workspace_hygiene.py` → Repository hygiene check passed

## Related issue

No upstream issue tracks this; the silent failure was found by an internal exception-swallowing scan of startup paths. Related to that internal audit only — no upstream `Fixes`.
