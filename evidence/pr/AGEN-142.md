# PR: fix(question): log failed error-event delivery in mimic websocket

When the mimic (exam-generation) WebSocket workflow fails, the endpoint's fallback handler tries to send `{"type": "error"}` back to the client. If that `send_json` itself fails, the exception is swallowed by a bare `except Exception: pass`: the frontend never learns why generation stopped, and the server leaves no trace that the error event was never delivered.

## Summary

- Split the swallowed exception in `websocket_mimic_generate`'s error handler into two branches:
  - client already closed/disconnecting (`RuntimeError`, `WebSocketDisconnect`) → `logger.debug`, matching the existing convention in the same file's `/generate` endpoint (a disconnecting client is not an error);
  - any other delivery failure → `logger.warning(..., exc_info=True)`, so lost error events are visible in server logs with a traceback.
- No behavior/protocol change: the endpoint's return value, the `finally` cleanup (task cancellation, queue draining, stdout restore) and the best-effort narrow handling of cleanup paths are untouched.

## Root cause

In `deeptutor/api/routers/question.py` (~line 320 on `dev`), the outer error handler logs the original workflow failure but then guards the error-event `send_json` with:

```python
except Exception:
    pass
```

so a secondary send failure (e.g. a broken pipe after the socket half-closed, or any unexpected send error) disappeared entirely — the original exception was logged, but the fact that the client never received the failure notice was not.

## Changes

- `deeptutor/api/routers/question.py` (+4/−1): the `except Exception: pass` becomes `except (RuntimeError, WebSocketDisconnect): logger.debug(...)` plus `except Exception: logger.warning(..., exc_info=True)`.
- `tests/api/test_question_router.py` (+119): new `_FakeMimicWebSocket` stub plus 3 focused tests driving the endpoint coroutine directly:
  1. workflow failure + error-event `send_json` raising a generic `Exception` → a warning (with traceback) is logged;
  2. error-event `send_json` raising `RuntimeError` → debug level, not a warning;
  3. error-event `send_json` raising `WebSocketDisconnect` → debug level, not a warning.

## Tests

All commands below pass on this branch (rebased onto the current `dev` tip `ef2d9e5c3`, v1.6.12):

- `pytest tests/api/test_question_router.py` → **4 passed**
- `pytest tests/api` → **749 passed, 5 warnings**
- `ruff check deeptutor/api/routers/question.py tests/api/test_question_router.py` → all checks passed
- `ruff format --check deeptutor/api/routers/question.py tests/api/test_question_router.py` → 2 files already formatted

Effectiveness cross-check (from the original review): with the product code reverted to the `dev` baseline, the new tests fail **3 failed / 1 passed**, confirming they pin the fix rather than the stub.

## Related issue

No upstream issue currently tracks this behavior (open/closed PRs were checked for `websocket_mimic_generate` / mimic-websocket topics — the closest is the long-merged #253 about missing imports, no overlap). Intentionally not using `Fixes`/`Closes`; happy to link a tracking issue if maintainers point to one.
