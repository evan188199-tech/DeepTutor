# PR: fix(chat): keep unsent drafts safe when restore fails

When `readWorkspaceDraft()` rejects on mount (for example while the auth status is briefly unavailable), the composer stays empty while the user's stored draft remains unshown in IndexedDB. On `dev`, that state has two bad outcomes: every workspace switch then rejects with a misleading "Could not save the draft" toast (the switch is blocked — the stored draft itself is not overwritten there), and sending any message saves an empty draft that clears the never-restored one, permanently losing unsent content.

## Summary

- Track the failed restore in a ref and skip the post-send draft clear in `doSend`, so the stored draft survives until it can be restored again.
- On the pre-switch save after a failed restore:
  - composer empty → skip saving (the unseen stored draft stays untouched and the switch proceeds instead of being blocked);
  - composer has new input → re-read the stored draft once per mount and save it merged with the new content, mirroring the successful-restore merge (`stored\ntyped`, attachments concatenated), so neither part is lost;
  - if that re-read also fails → reject the switch exactly as on `dev`, rather than silently dropping the new input.
- The stored draft is cached per mount so a blocked-then-retried switch merges the original stored draft instead of re-appending the composer text to itself.

## Root cause

`web/lib/workspace-drafts.ts` derives the IndexedDB key from the auth status; when `fetchAuthStatus()` returns `null` on mount (`web/lib/auth.ts`), `key()` throws and the mount-time restore rejects. The restore failure was swallowed (`.catch(() => {})`), leaving the composer out of sync with storage, but two code paths still assumed the composer reflected the stored draft:

1. the `deeptutor:before-workspace-switch` handler chained `restore.then(save)`, so a rejected restore rejected the whole switch chain (`web/lib/workspace-scope.ts`) — users got an error toast on every switch and could not leave the workspace;
2. `doSend` unconditionally saved `{ text: "", attachments: [] }` after sending, overwriting the never-restored draft — real data loss.

## Changes

- `web/components/chat/home/ChatComposer.tsx` (+53/−14):
  - new `restoreFailedRef`, set in the restore `.catch` (with a `console.warn` breadcrumb);
  - `doSend` skips the post-send draft clear when `restoreFailedRef.current` is set;
  - extracted `collectDraft()` and added `saveAfterFailedRestore()`, used by the pre-switch save handler both for the "restore already failed" path and as the rejection handler of `restore.then(save)`;
  - the re-read result is memoized in a per-mount `storedDraft` variable.
- `web/tests/composer-draft-restore-failure.spec.tsx` (new, 5 cases):
  1. keeps the workspace switch usable when restore failed and nothing new was typed;
  2. saves newly typed text merged with the stored draft when switching after a failed restore;
  3. rejects the switch when a re-read of the stored draft still fails after new input;
  4. does not clear the stored draft when the user sends text after a failed restore;
  5. still saves the composer content on workspace switch after a successful restore (positive control).

## Tests

Effectiveness cross-check: with the `dev` version of `ChatComposer.tsx` restored, this suite reports **3 failed / 2 passed** — exactly the three tests covering behavior changes fail, while the re-read-failure rejection (matches `dev`) and the successful-restore control stay green. `mockReset()` in `beforeEach` keeps `mockResolvedValueOnce` queues from leaking between specs.

All commands below pass on this branch (rebased onto the current `dev` tip `ef2d9e5c3`, v1.6.12):

- `npx vitest run tests/composer-draft-restore-failure.spec.tsx tests/workspace-scope.spec.tsx` → **2 files, 10 passed**
- `npx vitest run tests/workspace-navigation.spec.tsx` → **1 file, 4 passed**
- `npm run test:unit` → **114 files / 476 tests passed**
- `npm run test:node` → **1234 tests passed**
- `npm run typecheck` → passed
- `npx eslint .` → **0 errors** (49 warnings pre-exist on `dev`)
- `npm run contracts:check` and `npm run architecture:check` → passed

## Related issue

No upstream issue currently tracks this behavior (open PRs were checked for draft/composer/restore topics — none overlap). Intentionally not using `Fixes`/`Closes`; happy to link a tracking issue if maintainers point to one.
