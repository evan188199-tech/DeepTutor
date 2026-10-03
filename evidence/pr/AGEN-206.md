# PR: fix(sandbox): surface rlimit failures in the runner without leaking the report pipe

## Summary

- The sandbox runner's `preexec_fn` (`_apply`) swallowed every `resource.setrlimit` failure with `except (ValueError, OSError): pass`. On platforms where a limit cannot be applied (e.g. macOS rejects `RLIMIT_AS` with `ValueError: current limit exceeds maximum limit`), the command ran without that resource guard and left no trace anywhere.
- This PR collects each `setrlimit` failure in the child, reports it to the parent through a CLOEXEC-guarded pipe, surfaces it as an additive `limits_degraded` field in the execution response, and emits one `WARNING` line to the runner log. Command execution semantics are unchanged.
- Both pipe ends are released on every exit path (explicit returns plus a `finally` backstop for cancellation/interrupt), and the design deliberately avoids `pass_fds` so background/daemon processes spawned by the command cannot inherit the write end and block the parent's drain read.

## Root cause

`deeptutor/services/sandbox/runner/server.py` applied resource limits inside `preexec_fn`, where the only communication channel back to the parent is a pipe created before `fork`. The original code caught and discarded `setrlimit` exceptions, so degraded limits were invisible. Naively reporting them via a pipe whose fd leaks into the child (e.g. using `pass_fds`, which clears `FD_CLOEXEC`) reintroduces a worse bug: background processes inherit the write end, the pipe never reaches EOF, and the parent blocks reading it.

The fix relies on POSIX lifecycle ordering: `preexec_fn` runs after `fork` and before `execve`, so a pipe end that keeps its default `FD_CLOEXEC` is still writable inside `preexec_fn`, and the kernel closes it at `execve` — the report reaches the parent, yet nothing the command spawns inherits the fd.

## Changes

- `deeptutor/services/sandbox/runner/server.py` (+137/−40):
  - `_apply` records per-limit `setrlimit` failures and writes one short reason line to the report pipe instead of swallowing the exception.
  - `execute()` reads the report after the child exits and folds it into the response as `limits_degraded` (present only when a limit failed), plus one `WARNING` log line.
  - `subprocess.run` is called without `pass_fds`; a comment documents why clearing `FD_CLOEXEC` would leak the write end into background children and hang the parent's drain.
  - Both pipe ends are closed on every path: explicit return paths close and clear them during the drain; a `try...finally` backstop covers exits that skip those returns (cancellation, `KeyboardInterrupt`, unexpected exceptions), with None-guards avoiding double-close races when the thread pool reuses fd numbers.
- `tests/services/sandbox/test_runner_limit_degradation.py` (+140): 6 tests — no-degradation contract (response has no extra field), `ValueError` and `OSError` surfacing in response + log, timeout path also reporting degradation, background process (`sleep 2 &`) returning promptly (<1.5s) with no pipe fd leak, and interrupted execution releasing both fd ends.

## Tests

All commands run on a branch based on the current `dev` tip (`ef2d9e5c3`, v1.6.12):

- `pytest tests/services/sandbox/test_runner_limit_degradation.py -v` → **6 passed** (1.47s)
- `pytest tests/services/sandbox -q` → **70 passed, 1 failed** — the single failure is `test_runner_server_executes_and_truncates_output` (exit 127: the dev machine has no global `python` symlink), identical to the unfixed `dev` baseline
- `ruff check deeptutor/services/sandbox/runner/server.py tests/services/sandbox/test_runner_limit_degradation.py` → All checks passed
- `ruff format --check <same files>` → 2 files already formatted
- Red-green cross-check: on unfixed `dev` (`ef2d9e5c3`) the new tests report **3 failed** (`KeyError: 'limits_degraded'`); on the intermediate variant that used `pass_fds`, the two regression tests fail (background `sleep 2 &` blocks ~2s; interrupted run leaks both fds). All 6 pass on this branch.
- Non-blocking background check: `server.execute({"command": "sleep 2 >/dev/null 2>&1 &"})` returns in ~0.01s with no residual open fds.

## Related issue

None — found during an internal audit of silent `except: pass` sites in the sandbox runner. (No upstream issue or PR covers this topic as of 2026-10-03.)
