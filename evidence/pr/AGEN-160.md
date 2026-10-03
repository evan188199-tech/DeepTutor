# PR: fix(codex): log a warning when token revocation fails during logout

## Summary

During logout, a failure of the remote token revocation call was silently
swallowed by `except Exception: pass`, so the remote refresh/access token
could remain valid with no trace in the logs. Local logout still succeeded,
which is the desired behavior, but operators and users had no way to notice
that the remote token was never actually revoked. This PR keeps local logout
fully intact and adds a single structured warning log when revocation fails.

## Root cause

In `CodexOAuthService.logout()` (`deeptutor/services/codex_auth/service.py`),
the `await self._oauth.revoke(credentials)` call was wrapped in
`except Exception: pass`. Any network error or remote 4xx/5xx (wrapped by
`oauth.py` as `CodexAuthError("token_revoke_failed", ..., 502)`) was discarded
entirely, leaving the remote credentials potentially active after a local
logout with zero observability.

## Changes

- `deeptutor/services/codex_auth/service.py` (logout only): on revocation
  failure, emit `logger.warning` with the error kind
  (`getattr(exc, "code", None) or type(exc).__name__`) and HTTP status
  (`getattr(exc, "http_status", None)`). No credential or account material is
  ever logged. Local credentials are still cleared via
  `clear_credentials(...)` exactly as before; the exception is not re-raised,
  so logout semantics and the API contract of
  `POST /providers/openai-codex/oauth/logout` are unchanged.

## Tests

- New test `test_revoke_failure_logs_warning_without_token_content` in
  `tests/services/codex_auth/test_service.py`: mocks `revoke` to raise
  `CodexAuthError`, then asserts a WARNING record is emitted, the rendered
  message contains `token_revoke_failed`, none of the secret strings
  (`old-access`, `old-refresh`, `old-id`, `account-123`) appear in the log,
  the connection ends up disconnected, and local credentials are cleared.
- Fail-first verified: against the unpatched baseline the test fails with
  `AssertionError: a failed token revocation during logout must be logged`;
  with the fix it passes.
- `pytest tests/services/codex_auth -q` → 224 passed.
- Regression: `pytest tests/api/test_settings_router.py
  tests/api/test_codex_oauth_callback.py tests/api/test_codex_oauth_scope.py -q`
  → 92 passed; `pytest tests/services/llm/test_openai_codex_oauth_provider.py
  tests/services/llm/test_codex_tool_choice_conversion.py
  tests/services/llm/test_codex_disable_ssl_verify.py -q` → 27 passed.
- `pre-commit run --files deeptutor/services/codex_auth/service.py
  tests/services/codex_auth/test_service.py` → all hooks passed (ruff,
  ruff format, detect-secrets, bandit, mypy, hygiene).

## Related issue

- Related to: none open upstream at submission time — this came out of an
  internal error-handling audit of silent `except: pass` sites. Will link an
  upstream issue here if one is filed.

## Module(s) Affected

- `services`
- `tests`

## Checklist

- [x] This PR targets `dev` (not `main`).
- [x] I have read and followed the contribution guidelines.
- [x] My code follows the project's coding standards.
- [x] I have run pre-commit on the changed files and fixed any issues.
- [x] I have added relevant tests for my changes.
- [x] I have updated the documentation (not necessary for this change).
- [x] My changes do not introduce any new security vulnerabilities.
